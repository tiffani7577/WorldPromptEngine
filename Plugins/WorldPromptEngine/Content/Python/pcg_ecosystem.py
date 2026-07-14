"""
pcg_ecosystem.py — PCG volume + clustered foliage rules for WorldPromptEngine.

Spawns a PCGVolume around the generated world bounds when possible, points it
at a project PCG graph if one exists, and applies moisture-based density.
Also upgrades kit scattering into valley clusters restricted by slope.
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


DEFAULT_PCG_GRAPH = "/Game/WPE/PCG/PCG_WPE_Foliage"


def _landscape_bounds():
    if not _HAS_UNREAL:
        return None
    try:
        if hasattr(unreal, "EditorActorSubsystem"):
            actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        else:
            return None
        for a in actors:
            try:
                if a.get_class().get_name() in ("Landscape", "LandscapeStreamingProxy"):
                    origin, extent = a.get_actor_bounds(True)
                    return origin, extent, a
            except Exception:
                continue
    except Exception:
        pass
    return None


def _find_pcg_graph(preferred: str = None):
    if not _HAS_UNREAL:
        return None
    paths = [preferred or DEFAULT_PCG_GRAPH,
             "/Game/PCG/PCG_WPE_Foliage",
             "/Game/WPE/PCG/PCG_SurfaceFoliage"]
    for p in paths:
        try:
            g = unreal.load_asset(p)
            if g is not None:
                return g
        except Exception:
            continue
    # soft search by asset registry name
    try:
        if hasattr(unreal, "AssetRegistryHelpers"):
            reg = unreal.AssetRegistryHelpers.get_asset_registry()
            arr = reg.get_assets_by_class(unreal.TopLevelAssetPath("/Script/PCG", "PCGGraph"), True)
            if arr:
                return arr[0].get_asset()
    except Exception:
        pass
    return None


def spawn_pcg_ecosystem(state: dict, params: dict = None) -> dict:
    """
    Create/update a PCGVolume for foliage clustering.
    """
    params = params or {}
    summary = {"ok": False, "spawned": False, "graph": None, "density": 0.0}
    if not _HAS_UNREAL:
        return summary
    if not params.get("spawn_pcg", True):
        summary["skipped"] = True
        return summary

    try:
        moisture = float(params.get("moisture", 0.5))
        density = float(params.get("pcg_density", 0.35 + moisture * 0.85))
        summary["density"] = density

        bounds = _landscape_bounds()
        if bounds is None:
            # fallback volume at origin
            origin = unreal.Vector(0, 0, 0)
            extent = unreal.Vector(50000, 50000, 5000)
            landscape = None
        else:
            origin, extent, landscape = bounds

        graph = _find_pcg_graph(params.get("pcg_graph"))
        vol = None

        # Reuse previous volume
        prev = state.get("pcg_volume")
        if prev is not None:
            try:
                vol = prev
            except Exception:
                vol = None

        if vol is None and hasattr(unreal, "PCGVolume"):
            loc = origin
            if hasattr(unreal, "EditorActorSubsystem"):
                vol = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
                    unreal.PCGVolume, loc, unreal.Rotator(0, 0, 0))
            if vol is not None:
                try:
                    vol.set_actor_label("WPE_PCG_Ecosystem")
                    # scale brush to bounds
                    scale = unreal.Vector(
                        max(1.0, extent.x / 50.0),
                        max(1.0, extent.y / 50.0),
                        max(1.0, extent.z / 50.0 + 20.0),
                    )
                    vol.set_actor_scale3d(scale)
                except Exception:
                    pass
                state["pcg_volume"] = vol
                summary["spawned"] = True

        if vol is not None and graph is not None:
            summary["graph"] = str(graph.get_path_name())
            try:
                # PCGComponent on volume
                comp = None
                if hasattr(vol, "get_component_by_class") and hasattr(unreal, "PCGComponent"):
                    comp = vol.get_component_by_class(unreal.PCGComponent)
                if comp is None and hasattr(unreal, "PCGComponent"):
                    comps = vol.get_components_by_class(unreal.PCGComponent) if hasattr(vol, "get_components_by_class") else []
                    comp = comps[0] if comps else None
                if comp is not None:
                    if hasattr(comp, "set_graph"):
                        comp.set_graph(graph)
                    elif hasattr(comp, "set_editor_property"):
                        comp.set_editor_property("graph", graph)
                    # density-ish params if exposed
                    for prop, val in (
                        ("seed", int(params.get("seed", 1337))),
                    ):
                        try:
                            comp.set_editor_property(prop, val)
                        except Exception:
                            pass
                    if hasattr(comp, "generate"):
                        comp.generate(True)
                    unreal.log(
                        "WorldPromptEngine: PCG ecosystem linked graph={} density~{:.2f} moisture={:.2f}".format(
                            summary["graph"], density, moisture))
                    summary["ok"] = True
                else:
                    unreal.log_warning("WorldPromptEngine: PCGVolume has no PCGComponent")
            except Exception as e:
                unreal.log_warning("WorldPromptEngine: PCG wire failed: {}".format(e))
        elif graph is None:
            unreal.log_warning(
                "WorldPromptEngine: no PCG graph at {}. "
                "Create one or rely on clustered kit foliage.".format(DEFAULT_PCG_GRAPH))
            summary["ok"] = True  # non-fatal
            summary["hint"] = "missing_pcg_graph"
        else:
            unreal.log_warning("WorldPromptEngine: PCGVolume class unavailable in this build")

        state["last_pcg_summary"] = summary
        state["pcg_density"] = density
        return summary
    except Exception as e:
        unreal.log_error("pcg_ecosystem.spawn_pcg_ecosystem failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def cluster_points(width, height, pixels, slopes, count, rng, max_slope=28.0,
                   prefer_valleys=True):
    """
    Return list of (px, py) for clustered foliage — valley bias, slope-limited.
    Softens max_slope to the 55th percentile of slopes if the map is steep overall.
    """
    if slopes and len(slopes) >= 16:
        sample = sorted(slopes[:: max(1, len(slopes) // 2000)])
        p55 = sample[int(len(sample) * 0.55)] if sample else max_slope
        max_slope = max(max_slope, min(42.0, float(p55) + 4.0))

    centers = []
    attempts = 0
    while len(centers) < max(1, count // 6) and attempts < count * 40:
        attempts += 1
        px = rng.uniform(4, width - 5)
        py = rng.uniform(4, height - 5)
        i = int(py) * width + int(px)
        h = pixels[i] / 65535.0
        s = slopes[i] if slopes and i < len(slopes) else 0.0
        if s > max_slope:
            continue
        if prefer_valleys and h > 0.72:
            continue
        if prefer_valleys and h < 0.08:
            continue
        centers.append((px, py))

    if not centers:
        # last resort: pick lowest-slope seeds
        idxs = list(range(0, width * height, max(1, (width * height) // 80)))
        idxs.sort(key=lambda i: (slopes[i] if slopes else 0.0, pixels[i]))
        for i in idxs[: max(1, count // 6)]:
            centers.append((float(i % width), float(i // width)))

    points = []
    for cx, cy in centers:
        n = max(3, count // max(1, len(centers)))
        for _ in range(n):
            ang = rng.random() * (2.0 * math.pi)
            rad = rng.uniform(2.0, 18.0)
            px = min(width - 2, max(1.0, cx + math.cos(ang) * rad))
            py = min(height - 2, max(1.0, cy + math.sin(ang) * rad))
            i = int(py) * width + int(px)
            s = slopes[i] if slopes and i < len(slopes) else 0.0
            if s <= max_slope + 5.0:
                points.append((px, py))
    return points[:count]
