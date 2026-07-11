"""
native_bridge.py — optional calls into the C++ scale core (UE 5.8)

When the native modules are compiled, Python uses them for huge tile plans.
If C++ isn't available yet (first open / compile pending), falls back gracefully.
"""

from __future__ import annotations

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False

    class _Stub:
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
    unreal = _Stub()  # type: ignore


def _get_native_subsystem():
    if not _HAS_UNREAL:
        return None
    try:
        cls = getattr(unreal, "WPEWorldGeneratorSubsystem", None)
        if cls is None:
            return None
        if hasattr(unreal, "get_engine_subsystem"):
            return unreal.get_engine_subsystem(cls)
    except Exception as e:
        unreal.log_warning("native_bridge: subsystem lookup failed: {}".format(e))
    return None


def is_native_available() -> bool:
    return _get_native_subsystem() is not None


def scale_summary() -> str:
    sys = _get_native_subsystem()
    if sys is None:
        return "native C++ core not loaded yet (compile the project once in UE 5.8)"
    try:
        return str(sys.get_scale_summary())
    except Exception as e:
        return "error: {}".format(e)


def build_world_plan(extent_km: float = -1.0, tile_size_m: float = -1.0, resolution: int = -1) -> dict:
    """
    Ask the C++ core to plan a huge tiled world.

      import native_bridge
      native_bridge.build_world_plan(extent_km=64)  # 64km x 64km
    """
    sys = _get_native_subsystem()
    if sys is None:
        return {
            "ok": False,
            "error": "C++ WorldPromptEngine module not loaded. Open the .uproject, allow compile, restart.",
        }
    try:
        plan = sys.build_world_plan(float(extent_km), float(tile_size_m), int(resolution))
        return {
            "ok": True,
            "extent_km": float(plan.world_extent_kilometers),
            "tiles_x": int(plan.tiles_x),
            "tiles_y": int(plan.tiles_y),
            "total_tiles": int(plan.total_tiles),
            "tile_resolution": int(plan.tile_resolution),
            "native": True,
        }
    except Exception as e:
        unreal.log_error("native_bridge.build_world_plan failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def enqueue_plan_batch(seed: int = 1337, resolution: int = -1, max_tiles: int = 64) -> dict:
    """Enqueue height generation for tiles from the last native plan (capped)."""
    sys = _get_native_subsystem()
    if sys is None:
        return {"ok": False, "error": "native core unavailable"}
    try:
        plan = sys.get_last_plan()
        tiles = list(plan.tiles)[: max(1, int(max_tiles))]
        accepted = sys.enqueue_tile_batch(tiles, int(seed), int(resolution))
        return {"ok": True, "accepted": int(accepted), "pending": int(sys.get_pending_tile_count())}
    except Exception as e:
        return {"ok": False, "error": str(e)}
