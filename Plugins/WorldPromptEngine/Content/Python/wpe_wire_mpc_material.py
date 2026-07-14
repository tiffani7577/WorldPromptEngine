"""
wpe_wire_mpc_material.py — upgrade ML_WPE_Landscape in place with MPC_WPE_World controls.

Run in Unreal Python console after rebuild:

    import wpe_wire_mpc_material
    wpe_wire_mpc_material.run()

Then verify by sweeping MPC params (see verify_sweep below).
"""

from __future__ import annotations

try:
    import unreal
except ImportError:
    unreal = None  # type: ignore


def run(color_set: str = "default") -> dict:
    import landscape_auto_setup as las
    import wpe_material_bridge

    summary = {"ok": False}
    # 1) Ensure MPC + wire material graph in place (same ML_WPE_Landscape asset)
    mat_sum = las.wire_mpc_into_existing_landscape_material(color_set=color_set)
    summary["material"] = mat_sum

    # 2) Assign to all landscapes in level
    try:
        import landscape_materials
        summary["assigned"] = landscape_materials.try_assign_landscape_material(las.MAT_PATH)
    except Exception as e:
        summary["assigned_error"] = str(e)

    # 3) Apply default MPC values
    summary["mpc"] = wpe_material_bridge.apply_world_params()

    summary["ok"] = bool(mat_sum.get("ok")) and bool(mat_sum.get("mpc_wired"))
    unreal.log("WPE MPC wire summary: {}".format(summary))
    if not summary["ok"]:
        unreal.log_warning(
            "WPE: MPC wiring incomplete. Open ML_WPE_Landscape and confirm CollectionParameter "
            "nodes for Snowline/RockSlope/Wetness/MacroScale/WorldTint exist.")
    return summary


def verify_sweep():
    """
    Push extreme MPC values so viewport differences are obvious.
    Call between visual checks; restore defaults at end.
    """
    import wpe_material_bridge
    steps = [
        ("snow_low", dict(snowline=0.15, rock_slope=0.55, wetness=0.2, macro_scale=1.0, tint=(1, 1, 1, 1))),
        ("snow_high", dict(snowline=0.85, rock_slope=0.55, wetness=0.2, macro_scale=1.0, tint=(1, 1, 1, 1))),
        ("rock_low", dict(snowline=0.72, rock_slope=0.15, wetness=0.2, macro_scale=1.0, tint=(1, 1, 1, 1))),
        ("rock_high", dict(snowline=0.72, rock_slope=0.95, wetness=0.2, macro_scale=1.0, tint=(1, 1, 1, 1))),
        ("wet", dict(snowline=0.72, rock_slope=0.55, wetness=0.95, macro_scale=1.0, tint=(1, 1, 1, 1))),
        ("macro", dict(snowline=0.72, rock_slope=0.55, wetness=0.2, macro_scale=4.0, tint=(1, 1, 1, 1))),
        ("tint_red", dict(snowline=0.72, rock_slope=0.55, wetness=0.2, macro_scale=1.0, tint=(1.0, 0.55, 0.45, 1))),
        ("defaults", dict(snowline=0.72, rock_slope=0.55, wetness=0.35, macro_scale=1.0, tint=(1, 1, 1, 1))),
    ]
    out = []
    for name, kw in steps:
        r = wpe_material_bridge.apply_world_params(**kw)
        out.append({"step": name, "ok": r.get("ok")})
        unreal.log("WPE MPC verify step '{}' -> {}".format(name, r))
    return out


if __name__ == "__builtin__" or __name__ == "__main__":
    run()
