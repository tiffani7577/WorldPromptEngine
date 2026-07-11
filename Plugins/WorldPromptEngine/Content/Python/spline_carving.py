"""
spline_carving.py — A* river / trail routing + heightmap carving + spline actors.

Plots paths from highlands to lowlands (rivers) or across moderate slopes (trails),
lowers/flattens the heightmap under the path, and optionally spawns a SplineComponent.
"""

from __future__ import annotations

import heapq
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


def _h01(pixels, width, x, y):
    return pixels[y * width + x] / 65535.0


def _neighbors(x, y, width, height):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            yield nx, ny, (1.414 if dx and dy else 1.0)


def astar_path(pixels, width, height, start, goal, prefer_downhill=True):
    """
    A* on the height grid. prefer_downhill biases rivers toward descending terrain.
    Returns list of (x,y) inclusive, or [].
    """
    try:
        sx, sy = start
        gx, gy = goal
        sx = max(0, min(width - 1, int(sx)))
        sy = max(0, min(height - 1, int(sy)))
        gx = max(0, min(width - 1, int(gx)))
        gy = max(0, min(height - 1, int(gy)))

        def heuristic(x, y):
            return math.hypot(gx - x, gy - y)

        open_h = []
        heapq.heappush(open_h, (0.0, sx, sy))
        came = {}
        gscore = {(sx, sy): 0.0}
        closed = set()

        while open_h:
            _, x, y = heapq.heappop(open_h)
            if (x, y) in closed:
                continue
            if abs(x - gx) + abs(y - gy) == 0:
                # reconstruct
                path = [(x, y)]
                while (x, y) in came:
                    x, y = came[(x, y)]
                    path.append((x, y))
                path.reverse()
                return path
            closed.add((x, y))
            h_here = _h01(pixels, width, x, y)
            for nx, ny, step in _neighbors(x, y, width, height):
                if (nx, ny) in closed:
                    continue
                h_n = _h01(pixels, width, nx, ny)
                climb = max(0.0, h_n - h_here)
                drop = max(0.0, h_here - h_n)
                cost = step + climb * (4.0 if prefer_downhill else 1.5)
                if prefer_downhill:
                    cost -= min(0.35, drop * 0.8)
                ng = gscore[(x, y)] + max(0.05, cost)
                if ng < gscore.get((nx, ny), 1e18):
                    gscore[(nx, ny)] = ng
                    came[(nx, ny)] = (x, y)
                    f = ng + heuristic(nx, ny) * 1.05
                    heapq.heappush(open_h, (f, nx, ny))
        return []
    except Exception as e:
        unreal.log_error("spline_carving.astar_path failed: {}".format(e))
        return []


def _pick_river_endpoints(pixels, width, height, rng):
    # start: high percentile, end: low percentile near border preference
    samples = []
    step = max(1, (width * height) // 800)
    for i in range(0, width * height, step):
        samples.append((pixels[i], i % width, i // width))
    samples.sort(reverse=True)
    highs = samples[: max(8, len(samples) // 20)]
    lows = sorted(samples, key=lambda t: t[0])[: max(8, len(samples) // 20)]
    if not highs or not lows:
        return (2, 2), (width - 3, height - 3)
    sh = rng.choice(highs)
    # prefer low end far from start
    best = None
    best_d = -1
    for lo in lows:
        d = math.hypot(lo[1] - sh[1], lo[2] - sh[2])
        if d > best_d:
            best_d = d
            best = lo
    return (sh[1], sh[2]), (best[1], best[2])


def _pick_trail_endpoints(pixels, width, height, rng):
    # mid-elevation edge-ish points
    mid = []
    for _ in range(40):
        x = rng.randint(2, width - 3)
        y = rng.randint(2, height - 3)
        h = _h01(pixels, width, x, y)
        if 0.25 <= h <= 0.7:
            mid.append((x, y, h))
    if len(mid) < 2:
        return (4, height // 2), (width - 5, height // 2)
    a = rng.choice(mid)
    b = max(mid, key=lambda t: math.hypot(t[0] - a[0], t[1] - a[1]))
    return (a[0], a[1]), (b[0], b[1])


def carve_path(pixels, width, height, path, mode="river",
               half_width: int = 2, depth: float = 0.045):
    """
    Lower (river) or flatten (trail) heightmap under path. Mutates pixels.
    depth is relative to 0..1 height.
    """
    if not path:
        return pixels
    try:
        touched = set()
        for (x, y) in path:
            for oy in range(-half_width, half_width + 1):
                for ox in range(-half_width, half_width + 1):
                    if ox * ox + oy * oy > (half_width + 0.5) ** 2:
                        continue
                    nx, ny = x + ox, y + oy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    touched.add((nx, ny))
        path_heights = [_h01(pixels, width, px, py) for px, py in path]
        path_avg = sum(path_heights) / float(len(path_heights)) if path_heights else 0.4

        for (x, y) in touched:
            i = y * width + x
            h = pixels[i] / 65535.0
            mind = half_width + 1.0
            for px, py in path:
                d = math.hypot(px - x, py - y)
                if d < mind:
                    mind = d
            fall = max(0.0, 1.0 - mind / (half_width + 0.75))
            if mode == "river":
                nh = h - depth * fall
            else:
                nh = h + (path_avg - h) * 0.55 * fall - depth * 0.25 * fall
            pixels[i] = int(max(0.0, min(1.0, nh)) * 65535.0 + 0.5)

        # light bank smoothing for rivers
        if mode == "river":
            for (x, y) in list(touched):
                i = y * width + x
                acc = float(pixels[i])
                n = 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        acc += pixels[ny * width + nx]
                        n += 1
                pixels[i] = int(acc / n)
        return pixels
    except Exception as e:
        unreal.log_error("spline_carving.carve_path failed: {}".format(e))
        return pixels


def generate_and_carve_routes(pixels, width, height, params: dict = None) -> dict:
    """
    Create river (+ optional trail) paths, carve heightmap, store polylines in state-friendly dict.
    """
    params = params or {}
    summary = {"rivers": [], "trails": [], "carved": False}
    try:
        if not params.get("carve_splines", True):
            summary["skipped"] = True
            return summary

        rng = random.Random(int(params.get("seed", 1337)) ^ 0x5A11)
        moisture = float(params.get("moisture", 0.5))
        river_count = int(params.get("river_count", 1 if moisture >= 0.25 else 0))
        if moisture >= 0.7:
            river_count = max(river_count, 2)
        trail_count = int(params.get("trail_count", 1))
        prompt = (params.get("prompt") or "").lower()
        if any(k in prompt for k in ("road", "trail", "path", "highway", "hiking")):
            trail_count = max(trail_count, 1)
        if any(k in prompt for k in ("river", "stream", "creek", "waterfall", "delta")):
            river_count = max(river_count, 1)

        for _ in range(river_count):
            start, goal = _pick_river_endpoints(pixels, width, height, rng)
            path = astar_path(pixels, width, height, start, goal, prefer_downhill=True)
            if len(path) < 8:
                continue
            depth = float(params.get("river_depth", 0.05 + 0.03 * moisture))
            half_w = int(params.get("river_half_width", 2 if width < 400 else 3))
            carve_path(pixels, width, height, path, mode="river",
                       half_width=half_w, depth=depth)
            summary["rivers"].append({"start": start, "goal": goal, "points": len(path), "path": path})

        for _ in range(trail_count):
            start, goal = _pick_trail_endpoints(pixels, width, height, rng)
            path = astar_path(pixels, width, height, start, goal, prefer_downhill=False)
            if len(path) < 8:
                continue
            carve_path(pixels, width, height, path, mode="trail",
                       half_width=int(params.get("trail_half_width", 1)),
                       depth=float(params.get("trail_depth", 0.012)))
            summary["trails"].append({"start": start, "goal": goal, "points": len(path), "path": path})

        summary["carved"] = bool(summary["rivers"] or summary["trails"])
        unreal.log(
            "WorldPromptEngine: spline carve rivers={} trails={}".format(
                len(summary["rivers"]), len(summary["trails"])))
        return summary
    except Exception as e:
        unreal.log_error("spline_carving.generate_and_carve_routes failed: {}".format(e))
        return summary


def spawn_spline_actors(state: dict, routes: dict, width: int, height: int, params: dict = None):
    """Spawn visible editor splines for rivers/trails (debug + future mesh deform)."""
    params = params or {}
    if not _HAS_UNREAL or not params.get("spawn_spline_actors", True):
        return
    try:
        xy_scale = float(params.get("xy_scale", 100.0))
        origin_x = float(params.get("origin_x", -width * xy_scale * 0.5))
        origin_y = float(params.get("origin_y", -height * xy_scale * 0.5))
        pixels = state.get("last_height_pixels")

        def world_pt(px, py):
            h01 = 0.3
            if pixels is not None:
                x = max(0, min(width - 1, int(px)))
                y = max(0, min(height - 1, int(py)))
                h01 = pixels[y * width + x] / 65535.0
            return unreal.Vector(
                origin_x + px * xy_scale,
                origin_y + py * xy_scale,
                h01 * 1000.0 + 40.0,
            )

        state.setdefault("spline_actors", [])
        # clear old
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for a in list(state.get("spline_actors") or []):
                try:
                    subsys.destroy_actor(a)
                except Exception:
                    pass
            state["spline_actors"] = []

            def make_spline(label, path):
                if not path or not hasattr(unreal, "SplineComponent"):
                    return
                # Actor with spline: use empty actor + add component if possible
                loc = world_pt(path[0][0], path[0][1])
                actor = subsys.spawn_actor_from_class(unreal.Actor, loc, unreal.Rotator())
                if actor is None:
                    return
                try:
                    actor.set_actor_label(label)
                except Exception:
                    pass
                sc = None
                if hasattr(actor, "add_component_by_class"):
                    sc = actor.add_component_by_class(
                        unreal.SplineComponent, False, unreal.Transform(), False)
                if sc is None:
                    return
                # clear default points then add
                try:
                    if hasattr(sc, "clear_spline_points"):
                        sc.clear_spline_points(True)
                    for i, (px, py) in enumerate(path[:: max(1, len(path) // 48)]):
                        sc.add_spline_point(world_pt(px, py), unreal.SplineCoordinateSpace.WORLD, False)
                    if hasattr(sc, "update_spline"):
                        sc.update_spline()
                except Exception as se:
                    unreal.log_warning("spline points failed: {}".format(se))
                state["spline_actors"].append(actor)

            for i, r in enumerate(routes.get("rivers") or []):
                make_spline("WPE_River_{}".format(i), r.get("path") or [])
            for i, t in enumerate(routes.get("trails") or []):
                make_spline("WPE_Trail_{}".format(i), t.get("path") or [])
    except Exception as e:
        unreal.log_warning("spline_carving.spawn_spline_actors failed: {}".format(e))
