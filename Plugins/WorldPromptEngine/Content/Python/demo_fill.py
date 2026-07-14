"""
demo_fill.py — BasicShapes proxy clusters when no Fab kit is active.

Keeps demo screenshots from looking empty.
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


_MESHES = (
    "/Engine/BasicShapes/Cube",
    "/Engine/BasicShapes/Cylinder",
    "/Engine/BasicShapes/Cone",
    "/Engine/BasicShapes/Sphere",
)


def clear_demo_fill(state: dict):
    if not _HAS_UNREAL:
        return
    try:
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for a in list(state.get("demo_fill_actors") or []):
                try:
                    subsys.destroy_actor(a)
                except Exception:
                    pass
        state["demo_fill_actors"] = []
    except Exception:
        state["demo_fill_actors"] = []


def spawn_proxy_clusters(state: dict, pixels, width: int, height: int, params: dict = None) -> dict:
    params = params or {}
    summary = {"ok": False, "placed": 0}
    if not _HAS_UNREAL or not params.get("spawn_demo_fill", True):
        summary["skipped"] = True
        return summary
    try:
        clear_demo_fill(state)
        rng = random.Random(int(params.get("seed", 1337)) ^ 0xD3F0)
        xy_scale = float(params.get("xy_scale", 100.0))
        # Match procedural terrain world size if present
        world_w = float(params.get("terrain_world_size", max(width, height) * xy_scale * 0.35))
        z_amp = float(params.get("terrain_height_amp", 1800.0))
        origin = -world_w * 0.5
        count = int(params.get("demo_fill_count", 48))
        max_total = min(count, 64)

        meshes = []
        for p in _MESHES:
            m = unreal.load_asset(p)
            if m is None:
                m = unreal.load_asset(p + "." + p.split("/")[-1])
            if m is not None:
                meshes.append(m)
        if not meshes:
            summary["error"] = "no_basicshapes"
            return summary

        # cluster centers in valleys (low height)
        centers = []
        attempts = 0
        while len(centers) < 6 and attempts < 200:
            attempts += 1
            px = rng.randint(4, width - 5)
            py = rng.randint(4, height - 5)
            h = pixels[py * width + px] / 65535.0
            if 0.15 <= h <= 0.55:
                centers.append((px, py, h))
        if not centers:
            centers = [(width // 2, height // 2, 0.4)]

        subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        placed = 0
        state.setdefault("demo_fill_actors", [])

        for i in range(max_total):
            cx, cy, ch = centers[i % len(centers)]
            ang = rng.random() * math.tau
            rad = rng.uniform(2.0, 22.0)
            px = min(width - 2, max(1, int(cx + math.cos(ang) * rad)))
            py = min(height - 2, max(1, int(cy + math.sin(ang) * rad)))
            h = pixels[py * width + px] / 65535.0
            # map pixel -> world matching procedural terrain mapping
            wx = origin + (px / float(max(1, width - 1))) * world_w
            wy = origin + (py / float(max(1, height - 1))) * world_w
            wz = h * z_amp + 40.0
            mesh = meshes[i % len(meshes)]
            loc = unreal.Vector(float(wx), float(wy), float(wz))
            actor = subsys.spawn_actor_from_class(
                unreal.StaticMeshActor, loc, unreal.Rotator(0.0, rng.uniform(0, 360), 0.0))
            if actor is None:
                continue
            smc = actor.static_mesh_component
            smc.set_static_mesh(mesh)
            s = rng.uniform(0.8, 3.5)
            # trees-ish = tall cylinders
            if mesh.get_name().lower().find("cylinder") >= 0:
                smc.set_world_scale3d(unreal.Vector(s * 0.35, s * 0.35, s * 2.2))
            elif mesh.get_name().lower().find("cone") >= 0:
                smc.set_world_scale3d(unreal.Vector(s * 0.8, s * 0.8, s * 1.6))
            else:
                smc.set_world_scale3d(unreal.Vector(s, s, s * rng.uniform(0.6, 1.4)))
            try:
                actor.set_actor_label("WPE_Proxy_{}".format(i))
            except Exception:
                pass
            state["demo_fill_actors"].append(actor)
            placed += 1

        summary["ok"] = True
        summary["placed"] = placed
        unreal.log("WorldPromptEngine: demo fill placed {} BasicShapes proxies".format(placed))
        return summary
    except Exception as e:
        unreal.log_error("demo_fill.spawn_proxy_clusters failed: {}".format(e))
        return {"ok": False, "error": str(e), "placed": 0}
