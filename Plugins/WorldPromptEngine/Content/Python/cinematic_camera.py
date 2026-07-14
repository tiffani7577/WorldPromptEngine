"""
cinematic_camera.py — WPE cinematic fly-through (UE 5.8 Python).

Uses a real spawned actor + USplineComponent for the path. Camera position /
rotation each tick come only from:
  spline.get_location_at_distance_along_spline(...)
  spline.get_rotation_at_distance_along_spline(...)
No custom spline math.

randomize_path() and start_camera() both destroy any prior WPE cinematic
camera / spline actors before spawning new ones so nothing stacks across
world generations or camera resets.
"""

from __future__ import annotations

import math
import random

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    unreal = None  # type: ignore
    _HAS_UNREAL = False


# Actor labels — used for cleanup scans (must stay stable).
LABEL_SPLINE = "WPE_CinematicSpline"
LABEL_CAMERA = "WPE_CinematicCamera"
LABEL_PREFIX = "WPE_Cinematic"

STATE = {
    "spline_actor": None,
    "spline_comp": None,
    "camera_actor": None,
    "distance": 0.0,
    "speed": 1200.0,          # uu / second along spline
    "playing": False,
    "loop": True,
    "tick_handle": None,
    "drive_viewport": True,   # also move editor viewport so the path is visible
}


def _log(msg: str):
    if _HAS_UNREAL:
        unreal.log("[WorldPromptEngine][Cine] {}".format(msg))
    else:
        print(msg)


def _warn(msg: str):
    if _HAS_UNREAL:
        unreal.log_warning("[WorldPromptEngine][Cine] {}".format(msg))
    else:
        print("WARN", msg)


def _error(msg: str):
    if _HAS_UNREAL:
        unreal.log_error("[WorldPromptEngine][Cine] {}".format(msg))
    else:
        print("ERR", msg)


def _actor_label(actor) -> str:
    try:
        return str(actor.get_actor_label() or "")
    except Exception:
        return ""


def _actor_name(actor) -> str:
    try:
        return str(actor.get_name() or "")
    except Exception:
        return ""


def _is_wpe_cinematic_actor(actor) -> bool:
    """True for previously spawned WPE cinematic cameras or spline actors."""
    if actor is None:
        return False
    label = _actor_label(actor)
    name = _actor_name(actor)
    if label.startswith(LABEL_PREFIX) or name.startswith(LABEL_PREFIX):
        return True
    # Tags set at spawn time (belt-and-suspenders for renamed actors).
    try:
        tags = list(actor.tags) if hasattr(actor, "tags") else []
        for t in tags:
            ts = str(t)
            if ts.startswith(LABEL_PREFIX) or ts in (LABEL_SPLINE, LABEL_CAMERA):
                return True
    except Exception:
        pass
    return False


def cleanup_existing_cinematic_actors() -> int:
    """
    Scan the level and destroy every previously spawned WPE cinematic camera /
    spline actor. Returns number destroyed.
    """
    if not _HAS_UNREAL:
        return 0

    destroyed = 0
    try:
        actors = list(unreal.EditorLevelLibrary.get_all_level_actors() or [])
    except Exception as e:
        _error("get_all_level_actors failed: {}".format(e))
        return 0

    for actor in actors:
        try:
            if not _is_wpe_cinematic_actor(actor):
                continue
            unreal.EditorLevelLibrary.destroy_actor(actor)
            destroyed += 1
        except Exception as e:
            _warn("destroy failed: {}".format(e))

    # Drop stale handles — destroyed actors are invalid.
    STATE["spline_actor"] = None
    STATE["spline_comp"] = None
    STATE["camera_actor"] = None
    STATE["distance"] = 0.0

    if destroyed:
        _log("cleaned up {} prior cinematic actor(s)".format(destroyed))
    return destroyed


def stop_camera() -> None:
    """Stop traversal tick (does not destroy actors)."""
    STATE["playing"] = False
    handle = STATE.get("tick_handle")
    if handle is not None and _HAS_UNREAL and hasattr(unreal, "unregister_slate_post_tick_callback"):
        try:
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception:
            pass
    STATE["tick_handle"] = None
    _log("camera stopped")


def _landscape_center_and_extent():
    """Rough world AABB from landscape actors, or a sensible default."""
    center = unreal.Vector(0.0, 0.0, 500.0)
    extent = 8000.0
    z_base = 200.0
    try:
        actors = unreal.EditorLevelLibrary.get_all_level_actors() or []
        for a in actors:
            if not isinstance(a, unreal.Landscape):
                continue
            origin = a.get_actor_location()
            # Landscape actors are large; use a wide orbit around origin.
            center = unreal.Vector(origin.x, origin.y, origin.z + 800.0)
            try:
                bounds = a.get_actor_bounds(False)
                # get_actor_bounds returns (origin, extent) in some bindings
                if isinstance(bounds, (tuple, list)) and len(bounds) >= 2:
                    ext = bounds[1]
                    extent = max(float(ext.x), float(ext.y), 4000.0)
                    z_base = float(bounds[0].z) + 400.0
                    center = unreal.Vector(bounds[0].x, bounds[0].y, z_base + 400.0)
            except Exception:
                extent = 10000.0
            break
    except Exception:
        pass
    return center, extent, z_base


def _spawn_spline_actor(points) -> tuple:
    """
    Spawn an empty actor with a USplineComponent and load world-space points.
    Returns (actor, spline_component) or (None, None).
    """
    if not points:
        return None, None

    start = points[0]
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.Actor, start, unreal.Rotator(0.0, 0.0, 0.0))
    if actor is None:
        _error("failed to spawn spline actor")
        return None, None

    try:
        actor.set_actor_label(LABEL_SPLINE)
    except Exception:
        pass
    try:
        actor.tags = [unreal.Name(LABEL_SPLINE)]
    except Exception:
        pass

    # Prefer add_component_by_class; fall back to root if already a spline.
    spline = None
    try:
        spline = actor.add_component_by_class(
            unreal.SplineComponent, False, unreal.Transform(), False)
    except Exception:
        spline = None
    if spline is None:
        try:
            spline = actor.get_component_by_class(unreal.SplineComponent)
        except Exception:
            spline = None
    if spline is None:
        _error("SplineComponent unavailable on cinematic spline actor")
        try:
            unreal.EditorLevelLibrary.destroy_actor(actor)
        except Exception:
            pass
        return None, None

    try:
        if hasattr(spline, "clear_spline_points"):
            spline.clear_spline_points(True)
        space = unreal.SplineCoordinateSpace.WORLD
        for pt in points:
            spline.add_spline_point(pt, space, False)
        if hasattr(spline, "update_spline"):
            spline.update_spline()
        # Closed loop for continuous fly-throughs.
        try:
            spline.set_closed_loop(True, True)
        except Exception:
            pass
    except Exception as e:
        _error("failed to populate spline points: {}".format(e))
        return actor, spline

    return actor, spline


def _spawn_camera_actor(location, rotation):
    cls = getattr(unreal, "CineCameraActor", None) or unreal.CameraActor
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, location, rotation)
    if actor is None:
        return None
    try:
        actor.set_actor_label(LABEL_CAMERA)
    except Exception:
        pass
    try:
        actor.tags = [unreal.Name(LABEL_CAMERA)]
    except Exception:
        pass
    return actor


def _set_viewport_camera(location, rotation):
    if not STATE.get("drive_viewport", True):
        return
    try:
        subsys = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        if subsys is not None and hasattr(subsys, "set_level_viewport_camera_info"):
            subsys.set_level_viewport_camera_info(location, rotation)
            return
    except Exception:
        pass
    try:
        unreal.EditorLevelLibrary.set_level_viewport_camera_info(location, rotation)
    except Exception:
        pass


def _sample_spline(spline, distance: float):
    """Only approved pathway: distance-along-spline queries on USplineComponent."""
    space = unreal.SplineCoordinateSpace.WORLD
    loc = spline.get_location_at_distance_along_spline(distance, space)
    rot = spline.get_rotation_at_distance_along_spline(distance, space)
    return loc, rot


def _build_random_points(num_points: int = 8):
    """World-space control points for a new cinematic spline (not interpolated here)."""
    center, extent, z_base = _landscape_center_and_extent()
    radius = max(extent * 0.35, 2500.0)
    height_amp = max(extent * 0.08, 600.0)
    points = []
    # Slight jitter so each randomize differs, still a coherent orbit.
    phase0 = random.uniform(0.0, math.pi * 2.0)
    for i in range(max(4, int(num_points))):
        t = phase0 + (2.0 * math.pi * i / float(num_points))
        r = radius * random.uniform(0.75, 1.15)
        x = center.x + math.cos(t) * r
        y = center.y + math.sin(t) * r
        z = z_base + height_amp * (0.55 + 0.45 * math.sin(t * 1.5 + phase0))
        z += random.uniform(-height_amp * 0.1, height_amp * 0.1)
        points.append(unreal.Vector(x, y, z))
    return points


def randomize_path(num_points: int = 8) -> dict:
    """
    Destroy any prior WPE cinematic camera/spline actors, then spawn a fresh
    actor with a USplineComponent holding randomized path points.
    """
    if not _HAS_UNREAL:
        return {"ok": False, "error": "unreal unavailable"}

    stop_camera()
    cleanup_existing_cinematic_actors()

    points = _build_random_points(num_points)
    actor, spline = _spawn_spline_actor(points)
    if actor is None or spline is None:
        return {"ok": False, "error": "spline spawn failed"}

    STATE["spline_actor"] = actor
    STATE["spline_comp"] = spline
    STATE["distance"] = 0.0

    length = 0.0
    try:
        length = float(spline.get_spline_length())
    except Exception:
        pass

    _log("randomized path: {} points, length={:.1f}".format(len(points), length))
    return {
        "ok": True,
        "points": len(points),
        "length": length,
        "spline_actor": LABEL_SPLINE,
    }


def _tick(delta_seconds: float):
    if not STATE.get("playing"):
        return
    spline = STATE.get("spline_comp")
    camera = STATE.get("camera_actor")
    if spline is None:
        return

    try:
        length = float(spline.get_spline_length())
    except Exception:
        return
    if length <= 1.0:
        return

    speed = float(STATE.get("speed") or 1200.0)
    dist = float(STATE.get("distance") or 0.0) + speed * max(float(delta_seconds), 0.0)
    if dist >= length:
        if STATE.get("loop", True):
            dist = dist % length
        else:
            dist = length
            stop_camera()
    STATE["distance"] = dist

    try:
        loc, rot = _sample_spline(spline, dist)
    except Exception as e:
        _warn("spline sample failed: {}".format(e))
        return

    if camera is not None:
        try:
            camera.set_actor_location_and_rotation(loc, rot, False, True)
        except Exception:
            try:
                camera.set_actor_location(loc, False, True)
                camera.set_actor_rotation(rot, True)
            except Exception as e:
                _warn("camera set transform failed: {}".format(e))

    _set_viewport_camera(loc, rot)


def start_camera(speed: float = 1200.0, num_points: int = 8, loop: bool = True) -> dict:
    """
    Destroy any prior WPE cinematic camera/spline actors, spawn a fresh spline
    path + camera, and begin distance-along-spline traversal each slate tick.
    """
    if not _HAS_UNREAL:
        return {"ok": False, "error": "unreal unavailable"}

    stop_camera()
    cleanup_existing_cinematic_actors()

    points = _build_random_points(num_points)
    spline_actor, spline = _spawn_spline_actor(points)
    if spline_actor is None or spline is None:
        return {"ok": False, "error": "spline spawn failed"}

    STATE["spline_actor"] = spline_actor
    STATE["spline_comp"] = spline
    STATE["distance"] = 0.0
    STATE["speed"] = float(speed)
    STATE["loop"] = bool(loop)

    try:
        loc, rot = _sample_spline(spline, 0.0)
    except Exception as e:
        _error("initial spline sample failed: {}".format(e))
        return {"ok": False, "error": str(e)}

    camera = _spawn_camera_actor(loc, rot)
    if camera is None:
        return {"ok": False, "error": "camera spawn failed"}
    STATE["camera_actor"] = camera

    _set_viewport_camera(loc, rot)

    STATE["playing"] = True
    if STATE.get("tick_handle") is None and hasattr(unreal, "register_slate_post_tick_callback"):
        STATE["tick_handle"] = unreal.register_slate_post_tick_callback(_tick)

    length = float(spline.get_spline_length())
    _log("started camera along spline length={:.1f} speed={:.1f}".format(length, speed))
    return {
        "ok": True,
        "length": length,
        "speed": speed,
        "loop": loop,
        "camera": LABEL_CAMERA,
        "spline": LABEL_SPLINE,
    }


def on_world_generation_begin() -> None:
    """Call from art_engine so cinematic actors never survive a new world gen."""
    stop_camera()
    cleanup_existing_cinematic_actors()
