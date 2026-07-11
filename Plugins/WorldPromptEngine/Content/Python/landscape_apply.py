"""
landscape_apply.py — make generated heightmaps VISIBLE in the viewport (UE 5.8).

Primary (Stage 1): native UWPEWorldGeneratorSubsystem.ApplyHeightmapToLandscape
via wpe_landscape_bridge (Python int → TArray<int32> → uint16 EDI write).
Secondary: create/find Landscape shell (PythonLandscapeLib / import helpers).
Fallback: ProceduralMesh (WPE_Terrain) only when allow_procedural_fallback=True.
"""

from __future__ import annotations

import math

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


WPE_TERRAIN_LABEL = "WPE_Terrain"
WPE_LANDSCAPE_LABEL = "WPE_Landscape"


def _editor_subsys():
    if hasattr(unreal, "EditorActorSubsystem"):
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    return None


def clear_wpe_terrains(state: dict) -> int:
    """Destroy previous WPE_Terrain / WPE_Landscape actors."""
    removed = 0
    if not _HAS_UNREAL:
        return 0
    try:
        subsys = _editor_subsys()
        if subsys is None:
            return 0
        for a in list(subsys.get_all_level_actors() or []):
            try:
                label = ""
                try:
                    label = a.get_actor_label() or ""
                except Exception:
                    pass
                if label in (WPE_TERRAIN_LABEL, WPE_LANDSCAPE_LABEL) or label.startswith("WPE_Terrain"):
                    subsys.destroy_actor(a)
                    removed += 1
            except Exception:
                continue
        # also clear tracked refs
        for key in ("wpe_terrain_actor", "wpe_landscape_actor"):
            state[key] = None
        if state.get("current_landscapes"):
            state["current_landscapes"] = [
                x for x in state["current_landscapes"]
                if x is not None
            ]
        if removed:
            unreal.log("WorldPromptEngine: cleared {} previous WPE terrain actor(s)".format(removed))
    except Exception as e:
        unreal.log_warning("clear_wpe_terrains failed: {}".format(e))
    return removed


def _fit_landscape_dims(width: int, height: int):
    """
    Pick section_size / components so Size = components * section + 1 is close to width.
    Prefer 63 quads/section, 1 section/component.
    """
    section = 63
    # nearest valid: n*63+1
    def nearest(n):
        c = max(1, int(round((n - 1) / float(section))))
        return c, c * section + 1

    cx, sx = nearest(width)
    cy, sy = nearest(height)
    return section, 1, cx, cy, sx, sy


def _resample_uint16(pixels, width, height, out_w, out_h):
    """Nearest-neighbor resample height grid."""
    out = [0] * (out_w * out_h)
    for y in range(out_h):
        sy = min(height - 1, int(y * height / float(out_h)))
        for x in range(out_w):
            sx = min(width - 1, int(x * width / float(out_w)))
            out[y * out_w + x] = pixels[sy * width + sx]
    return out


def _try_python_landscape_lib(pixels, width, height, params) -> object:
    if not hasattr(unreal, "PythonLandscapeLib"):
        return None
    try:
        section, spc, cx, cy, sx, sy = _fit_landscape_dims(width, height)
        data = _resample_uint16(pixels, width, height, sx, sy)
        lib = unreal.PythonLandscapeLib
        xf = unreal.Transform()
        xy = float(params.get("xy_scale", 100.0))
        # scale so each quad ~ xy_scale
        try:
            xf.scale3d = unreal.Vector(xy / 100.0, xy / 100.0, float(params.get("z_scale", 100.0)) / 100.0)
        except Exception:
            pass
        landscape = None
        if hasattr(lib, "create_landscape"):
            landscape = lib.create_landscape(xf, section, spc, cx, cy)
        if landscape is None:
            return None
        if hasattr(lib, "set_heightmap_data"):
            lib.set_heightmap_data(landscape, data)
        try:
            landscape.set_actor_label(WPE_LANDSCAPE_LABEL)
        except Exception:
            pass
        unreal.log("WorldPromptEngine: landscape via PythonLandscapeLib {}x{}".format(sx, sy))
        return landscape
    except Exception as e:
        unreal.log_warning("PythonLandscapeLib path failed: {}".format(e))
        return None


def _try_landscape_import(pixels, width, height, params) -> object:
    """Spawn Landscape and call .import / landscape_import if present."""
    if not hasattr(unreal, "Landscape"):
        return None
    subsys = _editor_subsys()
    if subsys is None:
        return None
    try:
        section, spc, cx, cy, sx, sy = _fit_landscape_dims(width, height)
        data = _resample_uint16(pixels, width, height, sx, sy)
        loc = unreal.Vector(
            -sx * float(params.get("xy_scale", 100.0)) * 0.5,
            -sy * float(params.get("xy_scale", 100.0)) * 0.5,
            0.0,
        )
        landscape = subsys.spawn_actor_from_class(unreal.Landscape, loc, unreal.Rotator())
        if landscape is None:
            return None
        try:
            landscape.set_actor_label(WPE_LANDSCAPE_LABEL)
        except Exception:
            pass

        # scale
        xy = float(params.get("xy_scale", 100.0))
        z = float(params.get("terrain_z_scale", 1.0))
        try:
            landscape.set_actor_scale3d(unreal.Vector(xy / 100.0, xy / 100.0, z))
        except Exception:
            pass

        imported = False
        # Method variants across engine builds
        for meth_name in ("landscape_import", "import_heightmap", "import"):
            if not hasattr(landscape, meth_name):
                continue
            meth = getattr(landscape, meth_name)
            try:
                # common signature: section, sections_per_comp, comp_x, comp_y, data
                meth(section, spc, cx, cy, data)
                imported = True
                break
            except TypeError:
                try:
                    meth(section, spc, cx, cy, bytes(bytearray(
                        b for v in data for b in (v & 0xFF, (v >> 8) & 0xFF))))
                    imported = True
                    break
                except Exception:
                    continue
            except Exception:
                continue

        if not imported:
            # Can't fill — destroy empty landscape
            try:
                subsys.destroy_actor(landscape)
            except Exception:
                pass
            return None

        unreal.log("WorldPromptEngine: Landscape.import path ok {}x{}".format(sx, sy))
        return landscape
    except Exception as e:
        unreal.log_warning("Landscape.import path failed: {}".format(e))
        return None


def _find_level_landscape(prefer_wpe_label=True):
    """Return an existing ALandscape in the level, preferring WPE_Landscape."""
    if not _HAS_UNREAL or not hasattr(unreal, "Landscape"):
        return None
    subsys = _editor_subsys()
    if subsys is None:
        return None
    preferred = None
    any_ls = None
    try:
        for a in list(subsys.get_all_level_actors() or []):
            try:
                if not isinstance(a, unreal.Landscape):
                    continue
            except Exception:
                # isinstance can fail across module reloads; fall back to class name
                try:
                    if a.get_class().get_name() not in ("Landscape", "LandscapeProxy"):
                        continue
                except Exception:
                    continue
            any_ls = a if any_ls is None else any_ls
            try:
                label = a.get_actor_label() or ""
            except Exception:
                label = ""
            if prefer_wpe_label and label == WPE_LANDSCAPE_LABEL:
                preferred = a
                break
        return preferred or any_ls
    except Exception as e:
        unreal.log_warning("_find_level_landscape failed: {}".format(e))
        return None


def _ensure_landscape_shell(pixels, width, height, params):
    """
    Find an existing Landscape or create one at a valid (63*N+1) resolution.
    Does not rely on Python height-write APIs for the final mesh shape.
    """
    existing = _find_level_landscape(prefer_wpe_label=True)
    if existing is not None:
        return existing

    # Create via PythonLandscapeLib (geometry shell); heights applied natively next.
    created = _try_python_landscape_lib(pixels, width, height, params)
    if created is not None:
        return created

    created = _try_landscape_import(pixels, width, height, params)
    return created


def _try_native_height_apply(pixels, width, height, params, state) -> object:
    """Resample to landscape extent and write through the C++ EDI path."""
    try:
        import wpe_landscape_bridge as bridge
    except Exception as e:
        unreal.log_warning("WPE native bridge import failed: {}".format(e))
        return None

    landscape = _ensure_landscape_shell(pixels, width, height, params)
    if landscape is None:
        unreal.log_warning("WPE: no Landscape target available for native apply.")
        return None

    res_x, res_y = bridge.query_landscape_resolution(landscape)
    if res_x <= 0 or res_y <= 0:
        # Fall back to fitted dims if extent query unavailable pre-compile
        _section, _spc, _cx, _cy, res_x, res_y = _fit_landscape_dims(width, height)
        unreal.log_warning(
            "WPE: extent query unavailable; using fitted {}x{} for native apply.".format(res_x, res_y))

    data = _resample_uint16(pixels, width, height, res_x, res_y)
    ok = bridge.send_flat_heightmap_to_native(landscape, data, res_x, res_y)
    if not ok:
        return None

    try:
        landscape.set_actor_label(WPE_LANDSCAPE_LABEL)
    except Exception:
        pass
    state["wpe_landscape_actor"] = landscape
    unreal.log("WorldPromptEngine: native Landscape height apply ok {}x{}".format(res_x, res_y))
    return landscape


def _assign_material(actor, material_path="/Game/WPE/Materials/ML_WPE_Landscape"):
    try:
        mat = unreal.load_asset(material_path)
        if mat is None:
            return
        # Landscape
        try:
            if hasattr(actor, "set_editor_property"):
                actor.set_editor_property("landscape_material", mat)
                return
        except Exception:
            pass
        # Procedural / static mesh component
        try:
            comps = []
            if hasattr(actor, "get_components_by_class"):
                if hasattr(unreal, "ProceduralMeshComponent"):
                    comps.extend(list(actor.get_components_by_class(unreal.ProceduralMeshComponent) or []))
                if hasattr(unreal, "StaticMeshComponent"):
                    comps.extend(list(actor.get_components_by_class(unreal.StaticMeshComponent) or []))
            for c in comps:
                try:
                    if hasattr(c, "set_material"):
                        c.set_material(0, mat)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


def _build_procedural_heightfield(pixels, width, height, params, state) -> object:
    """
    Guaranteed-visible fallback: ProceduralMesh grid from heightmap.
    Downsamples for editor performance.
    """
    if not hasattr(unreal, "ProceduralMeshComponent"):
        unreal.log_warning("WorldPromptEngine: ProceduralMeshComponent missing — no terrain fallback")
        return None
    subsys = _editor_subsys()
    if subsys is None:
        return None
    try:
        # Cap resolution for mesh
        max_res = int(params.get("terrain_mesh_res", 96))
        gw = min(width, max_res)
        gh = min(height, max_res)
        # keep roughly square
        data = _resample_uint16(pixels, width, height, gw, gh)

        xy_scale = float(params.get("xy_scale", 100.0))
        # world size roughly matches landscape intent
        world_w = float(params.get("terrain_world_size", max(width, height) * xy_scale * 0.35))
        step = world_w / float(max(1, gw - 1))
        z_amp = float(params.get("terrain_height_amp", 1800.0))

        origin_x = -world_w * 0.5
        origin_y = -world_w * 0.5

        verts = []
        normals = []
        uvs = []
        colors = []
        tris = []

        def h01(x, y):
            return data[y * gw + x] / 65535.0

        for y in range(gh):
            for x in range(gw):
                h = h01(x, y)
                verts.append(unreal.Vector(
                    origin_x + x * step,
                    origin_y + y * step,
                    h * z_amp,
                ))
                uvs.append(unreal.Vector2D(x / float(max(1, gw - 1)), y / float(max(1, gh - 1))))
                # rough normal later — flat up for speed, or compute
                normals.append(unreal.Vector(0.0, 0.0, 1.0))
                colors.append(unreal.LinearColor(h, h, h, 1.0))

        # recompute normals + airtight rock/grass/snow vertex colors (no user math)
        for y in range(gh):
            for x in range(gw):
                i = y * gw + x
                h_l = h01(max(0, x - 1), y)
                h_r = h01(min(gw - 1, x + 1), y)
                h_d = h01(x, max(0, y - 1))
                h_u = h01(x, min(gh - 1, y + 1))
                dx = (h_r - h_l) * z_amp
                dy = (h_u - h_d) * z_amp
                nx, ny, nz = -dx / (2.0 * step), -dy / (2.0 * step), 1.0
                inv = 1.0 / math.sqrt(nx * nx + ny * ny + nz * nz)
                nx, ny, nz = nx * inv, ny * inv, nz * inv
                normals[i] = unreal.Vector(nx, ny, nz)
                try:
                    import auto_surface_blend as asb
                    rock, grass, snow = asb.slope_to_blend_weights(nx, ny, nz, h01(x, y))
                except Exception:
                    flat = max(0.0, nz)
                    grass = max(0.0, (flat - 0.55) / 0.4)
                    rock = 1.0 - grass
                    snow = 0.0
                colors[i] = unreal.LinearColor(float(rock), float(grass), float(snow), 1.0)

        for y in range(gh - 1):
            for x in range(gw - 1):
                i = y * gw + x
                # two tris
                tris.extend([i, i + 1, i + gw])
                tris.extend([i + 1, i + gw + 1, i + gw])

        actor = subsys.spawn_actor_from_class(
            unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator())
        if actor is None:
            return None
        try:
            actor.set_actor_label(WPE_TERRAIN_LABEL)
        except Exception:
            pass

        pmc = None
        if hasattr(actor, "add_component_by_class"):
            pmc = actor.add_component_by_class(
                unreal.ProceduralMeshComponent, False, unreal.Transform(), False)
        if pmc is None:
            try:
                subsys.destroy_actor(actor)
            except Exception:
                pass
            return None

        # create_mesh_section(section, verts, tris, normals, uvs, colors, tangents, collide)
        tangents = []
        try:
            if hasattr(unreal, "ProcMeshTangent"):
                tangents = [unreal.ProcMeshTangent(1.0, 0.0, 0.0) for _ in verts]
        except Exception:
            tangents = []

        try:
            pmc.create_mesh_section(0, verts, tris, normals, uvs, colors, tangents, True)
        except TypeError:
            # older signature without tangents/colors variants
            try:
                pmc.create_mesh_section(0, verts, tris, normals, uvs, True)
            except Exception as ce:
                unreal.log_error("create_mesh_section failed: {}".format(ce))
                return None

        try:
            if hasattr(pmc, "set_mobility") and hasattr(unreal, "ComponentMobility"):
                pmc.set_mobility(unreal.ComponentMobility.STATIC)
        except Exception:
            pass

        # Airtight AutoSurface (vertex-color rock/grass/snow) — preferred on procedural mesh
        try:
            import auto_surface_blend as asb
            prompt = str(params.get("prompt") or "")
            arch = str(params.get("archetype") or "")
            mat = asb.ensure_auto_surface_material(
                color_set=asb.color_set_from_prompt(prompt, arch), force=False)
            if mat is not None and hasattr(pmc, "set_material"):
                pmc.set_material(0, mat)
            else:
                _assign_material(actor)
        except Exception:
            _assign_material(actor)

        state["wpe_terrain_actor"] = actor
        unreal.log(
            "WorldPromptEngine: WPE_Terrain procedural mesh {}x{} (amp={}) — viewport WILL change".format(
                gw, gh, z_amp))
        return actor
    except Exception as e:
        unreal.log_error("_build_procedural_heightfield failed: {}".format(e))
        return None


def apply_heightmap_to_level(state: dict, pixels, width: int, height: int, params: dict = None) -> dict:
    """
    Make the heightmap visible. Always clears prior WPE procedural terrains.
    Prefer native EDI write; ProceduralMesh only if allow_procedural_fallback=True.
    Returns summary with mode native_landscape|landscape_*|procedural|failed.
    """
    params = params or {}
    summary = {"ok": False, "mode": "none", "actor": None}
    if not _HAS_UNREAL:
        summary["error"] = "no_unreal"
        return summary
    try:
        # Keep existing level Landscapes; only wipe prior WPE procedural / labeled actors.
        clear_wpe_terrains(state)
        state["last_height_pixels"] = pixels

        allow_fallback = bool(params.get("allow_procedural_fallback", False))
        actor = None

        if params.get("prefer_landscape", True):
            actor = _try_native_height_apply(pixels, width, height, params, state)
            if actor is not None:
                summary["mode"] = "native_landscape"

        if actor is not None:
            _assign_material(actor)
            state["wpe_landscape_actor"] = actor
            state.setdefault("current_landscapes", []).append(actor)
        elif allow_fallback:
            actor = _build_procedural_heightfield(pixels, width, height, params, state)
            if actor is not None:
                summary["mode"] = "procedural_mesh"
        else:
            unreal.log_error(
                "WorldPromptEngine: native Landscape apply failed and "
                "allow_procedural_fallback is False — no ProceduralMesh fallback.")

        if actor is None:
            summary["error"] = "all_paths_failed"
            unreal.log_error(
                "WorldPromptEngine: could not apply heightmap to level — "
                "native Landscape path failed"
                + (" and ProceduralMesh fallback disabled" if not allow_fallback else ""))
            return summary

        summary["ok"] = True
        summary["actor"] = actor
        # Frame the camera on the new terrain
        try:
            if hasattr(unreal, "UnrealEditorSubsystem"):
                unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
                    unreal.Vector(0.0, -4500.0, 2200.0),
                    unreal.Rotator(0.0, -25.0, 25.0))
            elif hasattr(unreal, "EditorLevelLibrary"):
                unreal.EditorLevelLibrary.set_level_viewport_camera_info(
                    unreal.Vector(0.0, -4500.0, 2200.0),
                    unreal.Rotator(0.0, -25.0, 25.0))
        except Exception:
            pass

        unreal.log("WorldPromptEngine: terrain apply ok mode={}".format(summary["mode"]))
        state["last_terrain_apply"] = summary
        return summary
    except Exception as e:
        unreal.log_error("apply_heightmap_to_level failed: {}".format(e))
        summary["error"] = str(e)
        return summary
