"""
wpe_foliage_bridge.py — Python → native ScatterTerrainAware (HISM).

Reuses height pixels from generate; falls back to foliage_fast.py if native unavailable.
"""

from __future__ import annotations

try:
    import unreal
except ImportError:
    unreal = None  # type: ignore


def _foliage_sys():
    if unreal is None or not hasattr(unreal, "WPEFoliageScatterSubsystem"):
        return None
    return unreal.get_engine_subsystem(unreal.WPEFoliageScatterSubsystem)


def scatter_from_height_pixels(pixels, width, height, params=None) -> dict:
    params = params or {}
    sys = _foliage_sys()
    if sys is None:
        try:
            import foliage_fast
            return foliage_fast.scatter_forest({}, pixels, width, height, params)
        except Exception as e:
            return {"ok": False, "error": "native missing and foliage_fast failed: {}".format(e)}

    mesh_path = params.get("mesh_path") or "/Engine/BasicShapes/Cone"
    mesh = unreal.load_asset(mesh_path)
    if mesh is None:
        mesh = unreal.load_asset("/Engine/BasicShapes/Cone.Cone")
    if mesh is None:
        return {"ok": False, "error": "no mesh"}

    heights = unreal.Array(float)
    heights.resize(width * height)
    for i, v in enumerate(pixels):
        heights[i] = float(v) / 65535.0

    world_w = float(params.get("terrain_world_size", max(width, height) * float(params.get("xy_scale", 100.0)) * 0.35))
    z_amp = float(params.get("terrain_height_amp", 1800.0))
    origin = unreal.Vector(-world_w * 0.5, -world_w * 0.5, 0.0)
    count = int(min(2500, max(40, 400 * float(params.get("foliage_density", 1.0)))))
    seed = int(params.get("seed", 1337)) ^ 0xF011

    n = sys.scatter_terrain_aware(
        mesh,
        heights,
        width,
        height,
        origin,
        world_w,
        z_amp,
        count,
        seed,
        float(params.get("max_slope_degrees", 28.0)),
        float(params.get("min_altitude_01", 0.08)),
        float(params.get("max_altitude_01", 0.88)),
        float(params.get("cluster_strength", 0.45)),
        0.75,
        1.6,
        True,
    )
    unreal.log("WPE Foliage bridge: native ScatterTerrainAware placed {}".format(n))
    return {"ok": n > 0, "instances": int(n), "mode": "native_hism"}
