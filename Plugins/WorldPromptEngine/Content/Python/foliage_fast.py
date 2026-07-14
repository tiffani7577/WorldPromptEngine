"""
foliage_fast.py — high-density HISM foliage with collision off (editor-safe "zero lag" path).

True runtime C++ scatter lives in optional plugin Source (disabled in .uplugin so the
project still opens without a compile). This Python path batches thousands of instances
into HierarchicalInstancedStaticMeshComponents — one draw family per mesh.
"""

from __future__ import annotations

import math
import random

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


def _load_mesh(path: str):
    m = unreal.load_asset(path)
    if m is None:
        leaf = path.split("/")[-1]
        m = unreal.load_asset("{}.{}".format(path, leaf))
    return m


def _disable_instance_collision(comp):
    try:
        if hasattr(comp, "set_collision_enabled") and hasattr(unreal, "CollisionEnabled"):
            comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    except Exception:
        pass
    try:
        if hasattr(comp, "set_editor_property"):
            comp.set_editor_property("cast_shadow", True)
            # HISM: disable body instance collision
            try:
                comp.set_editor_property("body_instance", None)
            except Exception:
                pass
    except Exception:
        pass


def scatter_forest(state: dict, pixels, width: int, height: int, params: dict = None) -> dict:
    """
    Dense HISM forest/scatter. Uses kit foliage if present, else BasicShapes cones/cylinders.
    Caps instances for editor stability while still looking "full".
    """
    params = params or {}
    summary = {"ok": False, "instances": 0, "batches": 0, "mode": "hism"}
    if not _HAS_UNREAL or not params.get("spawn_fast_foliage", True):
        summary["skipped"] = True
        return summary

    try:
        import hism_foliage
        import kit_library

        hism_foliage.clear_hism(state)
        # also clear previous fast foliage holders
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for a in list(state.get("fast_foliage_actors") or []):
                try:
                    subsys.destroy_actor(a)
                except Exception:
                    pass
        state["fast_foliage_actors"] = []

        rng = random.Random(int(params.get("seed", 1337)) ^ 0xF011)
        world_w = float(params.get("terrain_world_size", max(width, height) * float(params.get("xy_scale", 100.0)) * 0.35))
        z_amp = float(params.get("terrain_height_amp", 1800.0))
        origin = -world_w * 0.5
        max_slope_cos = float(params.get("foliage_min_flatness", 0.72))  # ~nz
        density = float(params.get("foliage_density", 1.0))
        target = int(min(2500, max(80, 400 * density)))

        # Collect meshes
        meshes = []
        for entry in kit_library.kit_assets("Foliage") or []:
            m = _load_mesh(entry.get("asset_path") or "")
            if m is not None:
                meshes.append(m)
        if not meshes:
            for p in (
                "/Engine/BasicShapes/Cone",
                "/Engine/BasicShapes/Cylinder",
                "/Engine/BasicShapes/Sphere",
            ):
                m = _load_mesh(p)
                if m is not None:
                    meshes.append(m)
        if not meshes:
            summary["error"] = "no_meshes"
            return summary

        # Precompute candidate pixels (flat + mid height)
        candidates = []
        step = max(1, (width * height) // (target * 4))
        for i in range(0, width * height, step):
            h = pixels[i] / 65535.0
            if not (0.12 <= h <= 0.72):
                continue
            x = i % width
            y = i // width
            if x <= 1 or y <= 1 or x >= width - 2 or y >= height - 2:
                continue
            # cheap slope via neighbors
            hl = pixels[y * width + (x - 1)] / 65535.0
            hr = pixels[y * width + (x + 1)] / 65535.0
            hd = pixels[(y - 1) * width + x] / 65535.0
            hu = pixels[(y + 1) * width + x] / 65535.0
            # approximate flatness
            g = abs(hr - hl) + abs(hu - hd)
            if g > 0.08:  # too steep in heightmap space
                continue
            candidates.append((x, y, h))

        rng.shuffle(candidates)
        candidates = candidates[: target * 2]

        # Cluster: pick seeds then local points
        transforms_by_mesh = {id(m): [] for m in meshes}
        mesh_list = list(meshes)
        placed = 0
        seeds = candidates[:: max(1, len(candidates) // max(1, target // 8))][: max(8, target // 10)]
        if not seeds:
            seeds = candidates[:12]

        for sx, sy, sh in seeds:
            n_local = max(3, target // max(1, len(seeds)))
            for _ in range(n_local):
                if placed >= target:
                    break
                ang = rng.random() * math.tau
                rad = rng.uniform(1.0, 14.0)
                px = int(min(width - 2, max(1, sx + math.cos(ang) * rad)))
                py = int(min(height - 2, max(1, sy + math.sin(ang) * rad)))
                h = pixels[py * width + px] / 65535.0
                if not (0.12 <= h <= 0.75):
                    continue
                wx = origin + (px / float(max(1, width - 1))) * world_w
                wy = origin + (py / float(max(1, height - 1))) * world_w
                wz = h * z_amp
                mesh = mesh_list[placed % len(mesh_list)]
                yaw = rng.uniform(0, 360)
                s = rng.uniform(0.7, 1.8)
                name = mesh.get_name().lower()
                if "cylinder" in name:
                    scale = s * 0.25
                    zscale = s * 2.4
                elif "cone" in name:
                    scale = s * 0.7
                    zscale = s * 1.8
                else:
                    scale = s
                    zscale = s
                loc = unreal.Vector(float(wx), float(wy), float(wz))
                transforms_by_mesh[id(mesh)].append((loc, yaw, scale, zscale, mesh))
                placed += 1

        total_inst = 0
        batches = 0
        for mesh in mesh_list:
            entries = transforms_by_mesh.get(id(mesh)) or []
            if not entries:
                continue
            # Build list for hism helper (uniform scale) — use average scale path
            xforms = []
            for loc, yaw, scale, zscale, _m in entries:
                # hism helper uses uniform scale; approximate
                xforms.append((loc, yaw, (scale + zscale) * 0.5))
            batch = hism_foliage.scatter_hism_batch(
                state, mesh, xforms, "WPE_FastFoliage_{}".format(mesh.get_name()))
            if batch.get("ok"):
                total_inst += int(batch.get("instances", 0))
                batches += 1
                # disable collision on the last hism actor's components
                holders = state.get("hism_actors") or []
                if holders:
                    state.setdefault("fast_foliage_actors", []).append(holders[-1])
                    try:
                        comps = holders[-1].get_components_by_class(
                            unreal.HierarchicalInstancedStaticMeshComponent) \
                            if hasattr(unreal, "HierarchicalInstancedStaticMeshComponent") else []
                        for c in comps or []:
                            _disable_instance_collision(c)
                            # non-uniform scale: rewrite instances if API allows
                            try:
                                if hasattr(c, "clear_instances"):
                                    c.clear_instances()
                                for loc, yaw, scale, zscale, _m in entries:
                                    xf = unreal.Transform(
                                        loc,
                                        unreal.Rotator(0.0, float(yaw), 0.0),
                                        unreal.Vector(float(scale), float(scale), float(zscale)),
                                    )
                                    c.add_instance(xf)
                            except Exception:
                                pass
                    except Exception:
                        pass

        summary["ok"] = total_inst > 0
        summary["instances"] = total_inst
        summary["batches"] = batches
        unreal.log(
            "WorldPromptEngine: fast foliage HISM instances={} batches={} (collision off)".format(
                total_inst, batches))
        return summary
    except Exception as e:
        unreal.log_error("foliage_fast.scatter_forest failed: {}".format(e))
        return {"ok": False, "error": str(e), "instances": 0}
