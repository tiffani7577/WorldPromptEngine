"""
art_engine.py — WorldPromptEngine core artistic backend (UE 5.8.0)

Responsibilities:
  1. Pure-Python 16-bit grayscale PNG compiler (struct + zlib only).
  2. 2D value/gradient (Perlin-style) noise with frequency / octaves /
     persistence / lacunarity controls, plus simplex-style variant.
  3. Frame-budgeted generator runner driven by a Slate post-tick callback
     (hard budget: 8.0 ms per engine frame slice).
  4. Command consumer that drains the global thread-safe deque queue
     populated by utility_bridge.py and executes commands on the MAIN
     thread only.

UE 5.8 API notes:
  - Landscape heightmap import goes through AssetToolsHelpers /
    AutomatedAssetImportData or LandscapeSubsystem reflection. The legacy
    unreal.LandscapeEditorObject.import_landscape_data() is REMOVED in 5.8
    and is never referenced here.
  - PCG access uses unreal.PCGComponent / unreal.PCGGraphInterface via the
    subsystem pattern (5.7+).
  - All unreal.* calls are guarded with hasattr() probes where the API
    surface may vary between 5.8 preview builds.
"""

import json
import math
import os
import random
import struct
import tempfile
import time
import zlib

import prompt_matrix

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:  # allows offline unit-testing of pure-python parts
    _HAS_UNREAL = False

    class _StubLog:
        @staticmethod
        def log_error(msg):
            print("[ERROR]", msg)

        @staticmethod
        def log(msg):
            print("[LOG]", msg)

        @staticmethod
        def log_warning(msg):
            print("[WARN]", msg)

    unreal = _StubLog()  # type: ignore


# ---------------------------------------------------------------------------
# SECTION 1 — 16-BIT GRAYSCALE PNG COMPILER (struct + zlib only)
# ---------------------------------------------------------------------------

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Assemble a single PNG chunk: length + type + data + CRC32."""
    try:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)
    except Exception as e:
        unreal.log_error("art_engine._png_chunk failed: {}".format(e))
        raise


def write_png_16bit_grayscale(filepath: str, width: int, height: int, pixels) -> bool:
    """
    Write a valid 16-bit grayscale PNG.

    Args:
        filepath: destination path on disk.
        width, height: image dimensions.
        pixels: flat list/sequence of ints in [0, 65535], length == width*height,
                row-major (top row first).

    Returns True on success, False on failure (error logged).
    """
    try:
        expected = width * height
        if len(pixels) != expected:
            raise ValueError(
                "pixel count {} does not match {}x{}={}".format(
                    len(pixels), width, height, expected))

        # IHDR: width, height, bit depth 16, color type 0 (grayscale),
        # compression 0, filter 0, interlace 0
        ihdr = struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0)

        # Build raw scanlines: each row prefixed with filter byte 0x00,
        # each sample big-endian uint16.
        raw = bytearray()
        row_pack = struct.Struct(">" + "H" * width)
        idx = 0
        for _y in range(height):
            raw.append(0x00)  # filter type None
            row = pixels[idx:idx + width]
            # clamp defensively
            row = [0 if v < 0 else (65535 if v > 65535 else int(v)) for v in row]
            raw += row_pack.pack(*row)
            idx += width

        idat = zlib.compress(bytes(raw), 9)

        with open(filepath, "wb") as f:
            f.write(PNG_SIGNATURE)
            f.write(_png_chunk(b'IHDR', ihdr))
            f.write(_png_chunk(b'IDAT', idat))
            f.write(_png_chunk(b'IEND', b''))
        return True
    except Exception as e:
        unreal.log_error("art_engine.write_png_16bit_grayscale failed: {}".format(e))
        return False


# ---------------------------------------------------------------------------
# SECTION 2 — 2D NOISE (Perlin gradient noise + fBm layering)
# ---------------------------------------------------------------------------

class PerlinNoise2D:
    """Classic 2D gradient (Perlin) noise with a seeded permutation table."""

    __slots__ = ("perm",)

    def __init__(self, seed: int = 1337):
        try:
            rng = random.Random(seed)
            p = list(range(256))
            rng.shuffle(p)
            self.perm = p + p  # avoid wrapping math in hot loop
        except Exception as e:
            unreal.log_error("PerlinNoise2D.__init__ failed: {}".format(e))
            self.perm = list(range(256)) * 2

    @staticmethod
    def _fade(t: float) -> float:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + t * (b - a)

    @staticmethod
    def _grad(h: int, x: float, y: float) -> float:
        # 8 gradient directions
        h &= 7
        u = x if h < 4 else y
        v = y if h < 4 else x
        return (u if (h & 1) == 0 else -u) + ((v if (h & 2) == 0 else -v) * 2.0) * 0.5

    def noise(self, x: float, y: float) -> float:
        """Returns noise in approx [-1, 1]."""
        try:
            xi = int(math.floor(x)) & 255
            yi = int(math.floor(y)) & 255
            xf = x - math.floor(x)
            yf = y - math.floor(y)

            u = self._fade(xf)
            v = self._fade(yf)

            p = self.perm
            aa = p[p[xi] + yi]
            ab = p[p[xi] + yi + 1]
            ba = p[p[xi + 1] + yi]
            bb = p[p[xi + 1] + yi + 1]

            x1 = self._lerp(self._grad(aa, xf, yf),
                            self._grad(ba, xf - 1.0, yf), u)
            x2 = self._lerp(self._grad(ab, xf, yf - 1.0),
                            self._grad(bb, xf - 1.0, yf - 1.0), u)
            return self._lerp(x1, x2, v)
        except Exception as e:
            unreal.log_error("PerlinNoise2D.noise failed: {}".format(e))
            return 0.0

    def fbm(self, x: float, y: float, octaves: int = 5,
            frequency: float = 1.0, persistence: float = 0.5,
            lacunarity: float = 2.0) -> float:
        """Fractal Brownian Motion. Returns approx [-1, 1]."""
        try:
            total = 0.0
            amplitude = 1.0
            max_amp = 0.0
            freq = frequency
            for _ in range(max(1, octaves)):
                total += self.noise(x * freq, y * freq) * amplitude
                max_amp += amplitude
                amplitude *= persistence
                freq *= lacunarity
            return total / max_amp if max_amp > 0.0 else 0.0
        except Exception as e:
            unreal.log_error("PerlinNoise2D.fbm failed: {}".format(e))
            return 0.0


class SimplexNoise2D:
    """2D simplex-style noise (Gustavson formulation, pure Python)."""

    _GRAD3 = ((1, 1), (-1, 1), (1, -1), (-1, -1),
              (1, 0), (-1, 0), (0, 1), (0, -1))
    _F2 = 0.5 * (math.sqrt(3.0) - 1.0)
    _G2 = (3.0 - math.sqrt(3.0)) / 6.0

    __slots__ = ("perm",)

    def __init__(self, seed: int = 1337):
        try:
            rng = random.Random(seed)
            p = list(range(256))
            rng.shuffle(p)
            self.perm = p + p
        except Exception as e:
            unreal.log_error("SimplexNoise2D.__init__ failed: {}".format(e))
            self.perm = list(range(256)) * 2

    def noise(self, xin: float, yin: float) -> float:
        try:
            F2, G2 = self._F2, self._G2
            s = (xin + yin) * F2
            i = math.floor(xin + s)
            j = math.floor(yin + s)
            t = (i + j) * G2
            x0 = xin - (i - t)
            y0 = yin - (j - t)

            if x0 > y0:
                i1, j1 = 1, 0
            else:
                i1, j1 = 0, 1

            x1 = x0 - i1 + G2
            y1 = y0 - j1 + G2
            x2 = x0 - 1.0 + 2.0 * G2
            y2 = y0 - 1.0 + 2.0 * G2

            ii = int(i) & 255
            jj = int(j) & 255
            p = self.perm
            gi0 = p[ii + p[jj]] % 8
            gi1 = p[ii + i1 + p[jj + j1]] % 8
            gi2 = p[ii + 1 + p[jj + 1]] % 8

            n = 0.0
            for (gx, gy), x, y in (
                    (self._GRAD3[gi0], x0, y0),
                    (self._GRAD3[gi1], x1, y1),
                    (self._GRAD3[gi2], x2, y2)):
                tt = 0.5 - x * x - y * y
                if tt > 0.0:
                    tt *= tt
                    n += tt * tt * (gx * x + gy * y)
            return 70.0 * n
        except Exception as e:
            unreal.log_error("SimplexNoise2D.noise failed: {}".format(e))
            return 0.0


# ---------------------------------------------------------------------------
# SECTION 3 — FRAME-BUDGETED GENERATOR RUNNER (8 ms slices)
# ---------------------------------------------------------------------------

FRAME_BUDGET_MS = 8.0


def generate_heightmap_task(state: dict, params: dict):
    """
    Generator producing a heightmap incrementally under the frame budget.

    Yields True whenever the 8 ms slice budget is exceeded; the post-tick
    runner resumes on the next frame. On completion, writes the PNG,
    imports it via the 5.8 asset tooling path, and clears is_generating.
    """
    try:
        width = int(params.get("width", 505))
        height = int(params.get("height", 505))
        seed = int(params.get("seed", 1337))
        octaves = int(params.get("octaves", 6))
        frequency = float(params.get("frequency", 0.004))
        persistence = float(params.get("persistence", 0.5))
        lacunarity = float(params.get("lacunarity", 2.0))
        amplitude = float(params.get("amplitude", 1.0))
        noise_type = params.get("noise", "perlin")

        state["is_generating"] = True
        state["progress"] = 0.0

        if noise_type == "simplex":
            simplex = SimplexNoise2D(seed)

            def sample(x, y):
                total, amp, max_amp, freq = 0.0, 1.0, 0.0, frequency
                for _ in range(octaves):
                    total += simplex.noise(x * freq, y * freq) * amp
                    max_amp += amp
                    amp *= persistence
                    freq *= lacunarity
                return total / max_amp if max_amp else 0.0
        else:
            perlin = PerlinNoise2D(seed)

            def sample(x, y):
                return perlin.fbm(x, y, octaves, frequency, persistence, lacunarity)

        pixels = [0] * (width * height)
        slice_start = time.perf_counter()
        total_px = width * height

        for y in range(height):
            row_base = y * width
            for x in range(width):
                v = sample(float(x), float(y)) * amplitude
                # map [-1,1] -> [0,65535], 32768 = zero-plane
                pixels[row_base + x] = max(0, min(65535, int((v * 0.5 + 0.5) * 65535.0)))

                if (time.perf_counter() - slice_start) * 1000.0 >= FRAME_BUDGET_MS:
                    state["progress"] = (row_base + x + 1) / total_px * 0.9
                    yield True  # give the frame back to the engine
                    slice_start = time.perf_counter()

        # Optional terracing pass (e.g. terraced_valleys archetype)
        terrace_steps = int(params.get("terrace_steps", 0))
        if terrace_steps > 1:
            step = 65536.0 / terrace_steps
            slice_start = time.perf_counter()
            for i in range(total_px):
                pixels[i] = min(65535, int(round(pixels[i] / step) * step))
                if (time.perf_counter() - slice_start) * 1000.0 >= FRAME_BUDGET_MS:
                    yield True
                    slice_start = time.perf_counter()

        # Slope-angle material map (budget-driven via prompt_matrix generator)
        if params.get("compute_slopes", True):
            slope_gen = prompt_matrix.compute_slope_map(
                pixels, width, height,
                xy_scale=float(params.get("xy_scale", 100.0)),
                z_scale=float(params.get("z_scale", 51200.0)))
            slice_start = time.perf_counter()
            for item in slope_gen:
                if item[0] == "result":
                    state["last_slope_map"] = item[1]
                    state["slope_layer_names"] = item[2]
                elif (time.perf_counter() - slice_start) * 1000.0 >= FRAME_BUDGET_MS:
                    yield True
                    slice_start = time.perf_counter()

        state["progress"] = 0.92

        tmp_dir = tempfile.gettempdir()
        png_path = os.path.join(tmp_dir, "wpe_heightmap_{}.png".format(int(time.time())))
        if not write_png_16bit_grayscale(png_path, width, height, pixels):
            raise RuntimeError("PNG write failed at {}".format(png_path))

        state["progress"] = 0.95
        yield True  # one frame gap before the (potentially heavy) import

        _import_heightmap_5_8(state, png_path, params)

        # Structures (real meshes or BasicShapes proxies)
        state["progress"] = 0.97
        yield True
        try:
            import structure_library
            params_struct = dict(params)
            if state.get("last_parse"):
                params_struct.setdefault("prompt", "")
            structure_library.spawn_structures(state, pixels, width, height, params_struct)
        except Exception as struct_e:
            unreal.log_warning("WorldPromptEngine: structure pass skipped: {}".format(struct_e))

        # Refresh PCG if present
        try:
            refresh_pcg_components()
        except Exception:
            pass

        state["progress"] = 1.0
        state["is_generating"] = False
        if _HAS_UNREAL:
            unreal.log("WorldPromptEngine: heightmap generation complete ({}x{})".format(width, height))
    except Exception as e:
        state["is_generating"] = False
        unreal.log_error("art_engine.generate_heightmap_task failed: {}".format(e))


def _import_heightmap_5_8(state: dict, png_path: str, params: dict):
    """
    UE 5.8-compliant heightmap import.

    Primary path: AssetToolsHelpers.get_asset_tools().import_assets_automated()
    with AutomatedAssetImportData. Fallback: LandscapeSubsystem reflection.
    Never touches the removed LandscapeEditorObject.import_landscape_data().
    """
    if not _HAS_UNREAL:
        unreal.log("Stub mode: skipping editor import for {}".format(png_path))
        return
    try:
        try:
            import content_library
            default_dest = content_library.heightmap_destination()
        except Exception:
            default_dest = "/Game/WorldPromptEngine/Heightmaps"
        dest_path = params.get("destination", default_dest)

        if hasattr(unreal, "AssetToolsHelpers") and hasattr(unreal, "AutomatedAssetImportData"):
            asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
            import_data = unreal.AutomatedAssetImportData()
            import_data.destination_path = dest_path
            import_data.filenames = [png_path]
            import_data.replace_existing = True
            imported = asset_tools.import_assets_automated(import_data)
            if imported:
                state["last_heightmap_asset"] = imported[0]
                unreal.log("WorldPromptEngine: imported heightmap asset {}".format(imported[0].get_path_name()))
            else:
                unreal.log_warning("WorldPromptEngine: automated import returned no assets")

        # Optional: apply to landscape through LandscapeSubsystem if present
        if hasattr(unreal, "LandscapeSubsystem"):
            try:
                editor_subsys = None
                if hasattr(unreal, "get_editor_subsystem"):
                    editor_subsys = unreal.get_editor_subsystem(unreal.LandscapeSubsystem)
                if editor_subsys is not None:
                    state["landscape_subsystem"] = editor_subsys
                    unreal.log("WorldPromptEngine: LandscapeSubsystem acquired for post-import operations")
            except Exception as sub_e:
                unreal.log_warning("WorldPromptEngine: LandscapeSubsystem probe failed: {}".format(sub_e))
    except Exception as e:
        unreal.log_error("art_engine._import_heightmap_5_8 failed: {}".format(e))


# ---------------------------------------------------------------------------
# SECTION 4 — MAIN-THREAD COMMAND CONSUMER
# ---------------------------------------------------------------------------

def _cmd_move_editor_camera(payload: dict):
    try:
        loc = payload.get("location", [0.0, 0.0, 1000.0])
        rot = payload.get("rotation", [0.0, -45.0, 0.0])
        if hasattr(unreal, "UnrealEditorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            subsys.set_level_viewport_camera_info(
                unreal.Vector(float(loc[0]), float(loc[1]), float(loc[2])),
                unreal.Rotator(float(rot[0]), float(rot[1]), float(rot[2])))
        elif hasattr(unreal, "EditorLevelLibrary"):
            unreal.EditorLevelLibrary.set_level_viewport_camera_info(
                unreal.Vector(float(loc[0]), float(loc[1]), float(loc[2])),
                unreal.Rotator(float(rot[0]), float(rot[1]), float(rot[2])))
        else:
            unreal.log_warning("WorldPromptEngine: no camera API available")
    except Exception as e:
        unreal.log_error("art_engine._cmd_move_editor_camera failed: {}".format(e))


def _cmd_spawn_temporary_actor(state: dict, payload: dict):
    try:
        loc = payload.get("location", [0.0, 0.0, 0.0])
        asset_path = payload.get("asset", "/Engine/BasicShapes/Cube.Cube")
        actor = None
        vec = unreal.Vector(float(loc[0]), float(loc[1]), float(loc[2]))

        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            asset = unreal.load_asset(asset_path)
            if asset is not None:
                actor = subsys.spawn_actor_from_object(asset, vec)
        elif hasattr(unreal, "EditorLevelLibrary"):
            asset = unreal.load_asset(asset_path)
            if asset is not None:
                actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, vec)

        if actor is not None:
            actor.set_actor_label("WPE_Temp_{}".format(len(state["temporary_actors"])))
            state["temporary_actors"].append(actor)
            unreal.log("WorldPromptEngine: spawned temp actor at {}".format(vec))
        else:
            unreal.log_warning("WorldPromptEngine: spawn failed for {}".format(asset_path))
    except Exception as e:
        unreal.log_error("art_engine._cmd_spawn_temporary_actor failed: {}".format(e))


def _cmd_clear_temporary_actors(state: dict):
    try:
        subsys = None
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        for actor in state["temporary_actors"]:
            try:
                if actor is None:
                    continue
                if subsys is not None:
                    subsys.destroy_actor(actor)
                elif hasattr(unreal, "EditorLevelLibrary"):
                    unreal.EditorLevelLibrary.destroy_actor(actor)
            except Exception as inner:
                unreal.log_warning("WorldPromptEngine: temp actor destroy failed: {}".format(inner))
        state["temporary_actors"] = []
        unreal.log("WorldPromptEngine: temporary actors cleared")
    except Exception as e:
        unreal.log_error("art_engine._cmd_clear_temporary_actors failed: {}".format(e))


def _cmd_get_landscape_bounds(state: dict):
    try:
        landscapes = []
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            all_actors = subsys.get_all_level_actors()
        elif hasattr(unreal, "EditorLevelLibrary"):
            all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
        else:
            all_actors = []

        for a in all_actors:
            try:
                if a.get_class().get_name() in ("Landscape", "LandscapeStreamingProxy"):
                    origin, extent = a.get_actor_bounds(False)
                    landscapes.append({
                        "name": a.get_actor_label(),
                        "origin": [origin.x, origin.y, origin.z],
                        "extent": [extent.x, extent.y, extent.z],
                    })
            except Exception:
                continue

        state["last_landscape_bounds"] = landscapes
        unreal.log("WorldPromptEngine: landscape bounds -> {}".format(json.dumps(landscapes)))
    except Exception as e:
        unreal.log_error("art_engine._cmd_get_landscape_bounds failed: {}".format(e))


def execute_command(state: dict, command):
    """
    Execute a single command popped from the deque on the MAIN thread.
    Accepts a JSON string or a dict.
    """
    try:
        payload = json.loads(command) if isinstance(command, str) else command
        action = payload.get("action", "")

        if action == "move_editor_camera":
            _cmd_move_editor_camera(payload)
        elif action == "spawn_temporary_actor":
            _cmd_spawn_temporary_actor(state, payload)
        elif action == "clear_temporary_actors":
            _cmd_clear_temporary_actors(state)
        elif action == "get_landscape_bounds":
            _cmd_get_landscape_bounds(state)
        elif action == "generate_heightmap":
            if not state.get("is_generating"):
                state["active_task"] = generate_heightmap_task(state, payload.get("params", {}))
            else:
                unreal.log_warning("WorldPromptEngine: generation already in progress; command dropped")
        elif action == "generate_from_prompt":
            if not state.get("is_generating"):
                prompt = payload.get("prompt", "")
                parsed = prompt_matrix.parse_prompt(prompt)
                params = dict(payload.get("params", {}))
                # noise profile from archetype, overridable by explicit params
                merged = dict(parsed["noise"])
                merged.update(params)
                merged.setdefault("width", 505)
                merged.setdefault("height", 505)
                state["last_parse"] = parsed
                state["pcg_spawn_table"] = prompt_matrix.resolve_assets(parsed["pcg_tags"])
                state["structure_plan"] = parsed.get("structures") or []
                unreal.log("WorldPromptEngine: prompt -> archetype '{}' (score {}), weather '{}' (score {}), {} PCG entries, {} structure types".format(
                    parsed["archetype"], parsed["archetype_score"],
                    parsed["weather"], parsed["weather_score"],
                    len(state["pcg_spawn_table"]),
                    len(state["structure_plan"])))
                prompt_matrix.apply_weather_preset(parsed["weather"])
                merged["prompt"] = prompt
                merged.setdefault("spawn_structures", True)
                state["active_task"] = generate_heightmap_task(state, merged)
            else:
                unreal.log_warning("WorldPromptEngine: generation already in progress; command dropped")
        elif action == "apply_weather":
            prompt_matrix.apply_weather_preset(payload.get("preset", "clear_noon"))
        elif action == "setup_content":
            import content_library
            state["last_content_setup"] = content_library.setup_content(
                root=payload.get("root") or (payload.get("params") or {}).get("root"))
        elif action == "set_content_root":
            import content_library
            root = payload.get("root") or (payload.get("params") or {}).get("root")
            state["last_content_setup"] = content_library.set_content_root(root or "/Game/WPE")
        elif action == "use_folder":
            import content_library
            params = payload.get("params") or {}
            name = payload.get("folder") or payload.get("name") or params.get("folder") or params.get("name")
            where = payload.get("where") or params.get("where")
            state["last_content_setup"] = content_library.use_folder(name or "", where=where)
        elif action == "find_folder":
            import content_library
            params = payload.get("params") or {}
            name = payload.get("folder") or payload.get("name") or params.get("folder") or params.get("name")
            where = payload.get("where") or params.get("where")
            state["last_content_status"] = content_library.find_folder(name or "", where=where)
        elif action == "content_status":
            import content_library
            state["last_content_status"] = content_library.content_status()
        else:
            unreal.log_warning("WorldPromptEngine: unknown action '{}'".format(action))
    except Exception as e:
        unreal.log_error("art_engine.execute_command failed: {}".format(e))


def consume_queue_tick(state: dict, delta_seconds: float):
    """
    Slate post-tick callback body. MAIN THREAD ONLY.

    1. Drain pending commands from the thread-safe deque.
    2. Advance the active generator task under its own 8 ms budget
       (the generator self-yields on budget overrun).
    """
    try:
        queue = state["command_queue"]
        # Drain a bounded number per frame to avoid pathological floods
        for _ in range(32):
            try:
                command = queue.popleft()
            except IndexError:
                break
            execute_command(state, command)

        task = state.get("active_task")
        if task is not None:
            try:
                next(task)
            except StopIteration:
                state["active_task"] = None
            except Exception as task_e:
                state["active_task"] = None
                state["is_generating"] = False
                unreal.log_error("WorldPromptEngine: task crashed: {}".format(task_e))
    except Exception as e:
        unreal.log_error("art_engine.consume_queue_tick failed: {}".format(e))


# ---------------------------------------------------------------------------
# PCG helpers (5.8 subsystem pattern) — optional utilities
# ---------------------------------------------------------------------------

def refresh_pcg_components():
    """Regenerate all PCGComponents in the level via the 5.7+ subsystem pattern."""
    if not _HAS_UNREAL:
        return
    try:
        if not hasattr(unreal, "PCGComponent"):
            unreal.log_warning("WorldPromptEngine: PCGComponent unavailable in this build")
            return
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actors = subsys.get_all_level_actors()
        else:
            actors = []
        count = 0
        for a in actors:
            try:
                comps = a.get_components_by_class(unreal.PCGComponent)
                for c in comps:
                    if hasattr(c, "generate"):
                        c.generate(True)
                        count += 1
                    graph = getattr(c, "get_graph", None)
                    if graph is not None and hasattr(unreal, "PCGGraphInterface"):
                        _g = c.get_graph()  # PCGGraphInterface handle, reserved for future param pushes
            except Exception:
                continue
        unreal.log("WorldPromptEngine: regenerated {} PCG components".format(count))
    except Exception as e:
        unreal.log_error("art_engine.refresh_pcg_components failed: {}".format(e))
