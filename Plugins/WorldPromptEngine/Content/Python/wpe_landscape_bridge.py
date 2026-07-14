"""
wpe_landscape_bridge.py — Python → native Landscape height apply (Stage 1 spike).

UE 5.8 Python marshals unreal.Array(int) → TArray<int32>. C++ clamps to uint16
and writes via FLandscapeEditDataInterface::SetHeightData.
"""

from __future__ import annotations

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False

    class unreal:  # type: ignore
        @staticmethod
        def log(msg):
            print("[LOG]", msg)

        @staticmethod
        def log_warning(msg):
            print("[WARN]", msg)

        @staticmethod
        def log_error(msg):
            print("[ERROR]", msg)


def _matrix_to_unreal_int32_array(height_matrix_2d):
    res_y = len(height_matrix_2d)
    res_x = len(height_matrix_2d[0]) if res_y > 0 else 0
    if res_x == 0 or res_y == 0:
        return None, 0, 0

    flat_data = []
    for y in range(res_y):
        row = height_matrix_2d[y]
        if len(row) != res_x:
            unreal.log_error("WPE Bridge: jagged height matrix row {} (expected {}).".format(len(row), res_x))
            return None, 0, 0
        for x in range(res_x):
            flat_data.append(int(max(0, min(int(row[x]), 65535))))

    unreal_int32_array = unreal.Array(int)
    unreal_int32_array.resize(len(flat_data))
    for i, val in enumerate(flat_data):
        unreal_int32_array[i] = val
    return unreal_int32_array, res_x, res_y


def _flat_to_unreal_int32_array(flat_pixels, res_x, res_y):
    expected = res_x * res_y
    if flat_pixels is None or len(flat_pixels) != expected:
        unreal.log_error(
            "WPE Bridge: flat buffer length mismatch. Expected {} ({}x{}), got {}.".format(
                expected, res_x, res_y, 0 if flat_pixels is None else len(flat_pixels)))
        return None

    unreal_int32_array = unreal.Array(int)
    unreal_int32_array.resize(expected)
    for i in range(expected):
        unreal_int32_array[i] = int(max(0, min(int(flat_pixels[i]), 65535)))
    return unreal_int32_array


def _get_wpe_subsystem():
    if not _HAS_UNREAL:
        return None
    if not hasattr(unreal, "WPEWorldGeneratorSubsystem"):
        unreal.log_error("WPE Bridge: WPEWorldGeneratorSubsystem type missing (plugin C++ not loaded).")
        return None
    return unreal.get_engine_subsystem(unreal.WPEWorldGeneratorSubsystem)


def send_heightmap_to_native(target_landscape, height_matrix_2d, allow_procedural_fallback=False):
    """
    Safely flattens and bounds 2D python arrays before passing across the UFUNCTION
    int32 boundary, keeping the legacy procedural mesh intact strictly behind a flag.
    """
    if not target_landscape:
        if allow_procedural_fallback:
            unreal.log_warning("WPE Bridge: Falling back to Procedural Mesh - Target Landscape is missing.")
            return _execute_procedural_mesh_fallback(height_matrix_2d)
        unreal.log_error("WPE Bridge: Landscape Target required but missing.")
        return False

    unreal_int32_array, res_x, res_y = _matrix_to_unreal_int32_array(height_matrix_2d)
    if unreal_int32_array is None:
        unreal.log_error("WPE Bridge: Provided height matrix contains empty records.")
        return False

    wpe_subsystem = _get_wpe_subsystem()
    if not wpe_subsystem:
        unreal.log_error("WPE Bridge: UWPEWorldGeneratorSubsystem is unavailable.")
        return False

    return bool(wpe_subsystem.apply_heightmap_to_landscape(
        target_landscape, unreal_int32_array, res_x, res_y))


def send_flat_heightmap_to_native(target_landscape, flat_pixels, res_x, res_y):
    """Flat row-major uint16/int buffer → native ApplyHeightmapToLandscape."""
    if not target_landscape:
        unreal.log_error("WPE Bridge: Landscape Target required but missing.")
        return False

    unreal_int32_array = _flat_to_unreal_int32_array(flat_pixels, res_x, res_y)
    if unreal_int32_array is None:
        return False

    wpe_subsystem = _get_wpe_subsystem()
    if not wpe_subsystem:
        unreal.log_error("WPE Bridge: UWPEWorldGeneratorSubsystem is unavailable.")
        return False

    return bool(wpe_subsystem.apply_heightmap_to_landscape(
        target_landscape, unreal_int32_array, res_x, res_y))


def query_landscape_resolution(target_landscape):
    """Return (width, height) from native extent, or (0, 0) on failure."""
    wpe_subsystem = _get_wpe_subsystem()
    if not wpe_subsystem or not target_landscape:
        return (0, 0)
    try:
        pt = wpe_subsystem.get_landscape_height_resolution(target_landscape)
        return (int(pt.x), int(pt.y))
    except Exception as e:
        unreal.log_warning("WPE Bridge: get_landscape_height_resolution failed: {}".format(e))
        return (0, 0)


def _execute_procedural_mesh_fallback(height_matrix_2d):
    unreal.log("WPE Bridge: Running fallback ProceduralMesh logic pipeline.")
    # Legacy fallback is owned by landscape_apply; bridge only signals intent.
    return True
