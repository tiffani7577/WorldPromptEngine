"""
landscape_materials.py — slope/height weightmaps + best-effort landscape layer paint.

UE 5.8: legacy LandscapeEditorObject.import_landscape_data is gone.
We:
  1. Build Grass/Rock weightmaps from slope + height
  2. Save PNG weightmaps for tooling / debug
  3. Try native APIs if present; otherwise keep weightmaps in state for PCG/kit rules
"""

from __future__ import annotations

import os
import struct
import tempfile
import zlib

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False

    class unreal:  # type: ignore
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)


def _png_gray8(path: str, width: int, height: int, pixels) -> bool:
    try:
        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(
                ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        raw = bytearray()
        for y in range(height):
            raw.append(0)
            row = pixels[y * width:(y + 1) * width]
            raw.extend(int(max(0, min(255, v))) for v in row)
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(chunk(b"IHDR", ihdr))
            f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
            f.write(chunk(b"IEND", b""))
        return True
    except Exception as e:
        unreal.log_error("landscape_materials._png_gray8 failed: {}".format(e))
        return False


def compute_weightmaps(pixels, width: int, height: int,
                       xy_scale: float = 100.0, z_scale: float = 51200.0,
                       grass_max_slope: float = 30.0) -> dict:
    """
    Returns dict with grass/rock/snow uint8 lists + slope degrees list.
    Flat (< grass_max_slope) -> grass; steep -> rock; high elevation boosts snow.

    Uses a material-friendly z factor so mild hills still get grass (full
    landscape z_scale alone often pushes every pixel toward cliff angles).
    """
    import prompt_matrix
    grass = [0] * (width * height)
    rock = [0] * (width * height)
    snow = [0] * (width * height)
    slopes = [0.0] * (width * height)
    # Softer vertical scale for paint decisions (~retail landscape look)
    mat_z = float(z_scale) * 0.22

    for y in range(height):
        for x in range(width):
            i = y * width + x
            xl = i if x == 0 else i - 1
            xr = i if x == width - 1 else i + 1
            yu = i if y == 0 else i - width
            yd = i if y == height - 1 else i + width
            ang = prompt_matrix.slope_angle_degrees(
                pixels[xl], pixels[xr], pixels[yu], pixels[yd], xy_scale, mat_z)
            slopes[i] = ang
            h01 = pixels[i] / 65535.0
            # soft blend around threshold
            if ang <= grass_max_slope:
                g = 1.0 - (ang / max(1.0, grass_max_slope)) * 0.55
            else:
                g = max(0.0, 1.0 - (ang - grass_max_slope) / 28.0)
            r = 1.0 - g
            # snow on high + not too steep
            s = 0.0
            if h01 > 0.72:
                s = min(1.0, (h01 - 0.72) / 0.2) * (1.0 - min(1.0, ang / 55.0))
                g *= (1.0 - s * 0.8)
                r *= (1.0 - s * 0.3)
            tot = g + r + s + 1e-6
            grass[i] = int(255 * g / tot)
            rock[i] = int(255 * r / tot)
            snow[i] = int(255 * s / tot)
    return {"grass": grass, "rock": rock, "snow": snow, "slopes": slopes}


def write_weightmap_pngs(weightmaps: dict, width: int, height: int, prefix: str = None) -> dict:
    prefix = prefix or os.path.join(tempfile.gettempdir(), "wpe_weights")
    paths = {}
    for name in ("grass", "rock", "snow"):
        path = "{}_{}.png".format(prefix, name)
        if _png_gray8(path, width, height, weightmaps[name]):
            paths[name] = path
    return paths


def _find_landscape_actors():
    actors = []
    if not _HAS_UNREAL:
        return actors
    try:
        if hasattr(unreal, "EditorActorSubsystem"):
            all_a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        elif hasattr(unreal, "EditorLevelLibrary"):
            all_a = unreal.EditorLevelLibrary.get_all_level_actors()
        else:
            all_a = []
        for a in all_a:
            try:
                n = a.get_class().get_name()
                if n in ("Landscape", "LandscapeStreamingProxy", "LandscapeProxy"):
                    actors.append(a)
            except Exception:
                continue
    except Exception as e:
        unreal.log_warning("landscape_materials._find_landscape_actors failed: {}".format(e))
    return actors


def try_assign_landscape_material(material_path: str = "/Game/WPE/Materials/ML_WPE_Landscape") -> bool:
    if not _HAS_UNREAL:
        return False
    try:
        mat = unreal.load_asset(material_path)
        if mat is None:
            unreal.log_warning(
                "WorldPromptEngine: landscape material missing at {}. "
                "Create ML_WPE_Landscape with Grass/Rock/Snow layers for auto look.".format(material_path))
            return False
        assigned = 0
        for a in _find_landscape_actors():
            try:
                # LandscapeProxy.landscape_material
                if hasattr(a, "set_editor_property"):
                    a.set_editor_property("landscape_material", mat)
                    assigned += 1
            except Exception:
                try:
                    a.landscape_material = mat
                    assigned += 1
                except Exception:
                    pass
        if assigned:
            unreal.log("WorldPromptEngine: assigned landscape material on {} actors".format(assigned))
            return True
        return False
    except Exception as e:
        unreal.log_warning("landscape_materials.try_assign_landscape_material failed: {}".format(e))
        return False


def apply_slope_materials(state: dict, pixels, width: int, height: int, params: dict = None) -> dict:
    """
    Compute + store weightmaps, write PNGs, best-effort assign landscape material.
    Full per-texel layer painting APIs vary by UE build; weightmaps always available.
    """
    params = params or {}
    try:
        wm = compute_weightmaps(
            pixels, width, height,
            xy_scale=float(params.get("xy_scale", 100.0)),
            z_scale=float(params.get("z_scale", 51200.0)),
            grass_max_slope=float(params.get("grass_max_slope", 30.0)),
        )

        # Multi-biome regional modulation of grass/rock weights
        regions = state.get("biome_regions") or params.get("biome_regions")
        if regions and regions.get("weights"):
            try:
                import biome_regions as br
                for y in range(height):
                    for x in range(width):
                        i = y * width + x
                        # deserts: less grass, more rock; swamps: more grass
                        g_mul = r_mul = 1.0
                        for bname, wlist in regions["weights"].items():
                            w = wlist[i]
                            if w < 0.05:
                                continue
                            style = (br.BIOME_STYLE.get(bname) or {}).get("foliage", "")
                            if style in ("arid", "dead"):
                                g_mul -= 0.55 * w
                                r_mul += 0.35 * w
                            elif style in ("wet", "dense", "meadow"):
                                g_mul += 0.35 * w
                                r_mul -= 0.2 * w
                            elif style == "sparse":
                                g_mul -= 0.15 * w
                        g_mul = max(0.05, g_mul)
                        r_mul = max(0.05, r_mul)
                        g = wm["grass"][i] * g_mul
                        r = wm["rock"][i] * r_mul
                        s = float(wm["snow"][i])
                        tot = g + r + s + 1e-6
                        wm["grass"][i] = int(255 * g / tot)
                        wm["rock"][i] = int(255 * r / tot)
                        wm["snow"][i] = int(255 * s / tot)
            except Exception as be:
                unreal.log_warning("biome weight modulate skipped: {}".format(be))

        paths = write_weightmap_pngs(wm, width, height)
        state["last_weightmaps"] = {
            "paths": paths,
            "grass": wm["grass"],
            "rock": wm["rock"],
            "snow": wm["snow"],
            "slopes": wm["slopes"],
        }
        # Keep slope map aligned to grass/rock for other systems
        state["last_slope_map"] = [
            0 if s < 30 else (1 if s < 48 else 2) for s in wm["slopes"]
        ]
        state["slope_layer_names"] = ["layer_grass", "layer_dirt", "layer_rock", "layer_cliff"]

        # Auto-create ML_WPE_Landscape (slope/height blend) if missing, then assign
        try:
            import landscape_auto_setup
            auto = landscape_auto_setup.ensure_landscape_material_stack(
                force_rebuild=bool(params.get("rebuild_landscape_material", False)),
                assign=True,
            )
            state["last_landscape_auto"] = auto
        except Exception as auto_e:
            unreal.log_warning("WorldPromptEngine: landscape auto-setup skipped: {}".format(auto_e))
            try_assign_landscape_material(params.get(
                "landscape_material", "/Game/WPE/Materials/ML_WPE_Landscape"))

        if _HAS_UNREAL and hasattr(unreal, "AssetToolsHelpers") and hasattr(unreal, "AutomatedAssetImportData"):
            try:
                dest = params.get("weightmap_destination", "/Game/WorldPromptEngine/Weightmaps")
                if hasattr(unreal, "EditorAssetLibrary"):
                    if not unreal.EditorAssetLibrary.does_directory_exist(dest):
                        unreal.EditorAssetLibrary.make_directory(dest)
                tools = unreal.AssetToolsHelpers.get_asset_tools()
                data = unreal.AutomatedAssetImportData()
                data.destination_path = dest
                data.filenames = list(paths.values())
                data.replace_existing = True
                imported = tools.import_assets_automated(data)
                state["last_weightmap_assets"] = imported
                unreal.log("WorldPromptEngine: imported {} weightmap textures".format(
                    len(imported) if imported else 0))
            except Exception as ie:
                unreal.log_warning("WorldPromptEngine: weightmap import skipped: {}".format(ie))

        unreal.log(
            "WorldPromptEngine: slope materials ready (grass/rock/snow weightmaps). "
            "Steep >30° → rock, flat → grass, peaks → snow.")
        return {"ok": True, "paths": paths}
    except Exception as e:
        unreal.log_error("landscape_materials.apply_slope_materials failed: {}".format(e))
        return {"ok": False, "error": str(e)}
