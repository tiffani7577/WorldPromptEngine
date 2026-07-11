"""
wpe_material_bridge.py — ensure MPC asset + drive params via UWPEMaterialBridge.

Does not generate material graphs; only sets scalar/vector MPC values that authored
materials already reference (Snowline, RockSlope, Wetness, MacroScale, WorldTint).
"""

from __future__ import annotations

try:
    import unreal
except ImportError:
    unreal = None  # type: ignore

MPC_PATH = "/Game/WPE/Materials/MPC_WPE_World"
PARAM_SCALARS = ("Snowline", "RockSlope", "Wetness", "MacroScale")
PARAM_VECTORS = ("WorldTint",)


def ensure_mpc(path: str = MPC_PATH):
    """Create MPC with expected parameter names if missing (editor only)."""
    if unreal is None:
        return None
    existing = unreal.load_asset(path)
    if existing is not None:
        return existing

    try:
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.MaterialParameterCollectionFactory()
        package_path = "/Game/WPE/Materials"
        name = "MPC_WPE_World"
        mpc = asset_tools.create_asset(name, package_path, unreal.MaterialParameterCollection, factory)
        if mpc is None:
            unreal.log_warning("WPE Material: could not create MPC at {}".format(path))
            return None

        # Populate parameters via editor property arrays when available
        try:
            scalars = []
            for pname, default in (
                ("Snowline", 0.72),
                ("RockSlope", 0.55),
                ("Wetness", 0.35),
                ("MacroScale", 1.0),
            ):
                p = unreal.CollectionScalarParameter()
                p.set_editor_property("parameter_name", pname)
                p.set_editor_property("default_value", float(default))
                scalars.append(p)
            mpc.set_editor_property("scalar_parameters", scalars)

            vectors = []
            v = unreal.CollectionVectorParameter()
            v.set_editor_property("parameter_name", "WorldTint")
            v.set_editor_property("default_value", unreal.LinearColor(1, 1, 1, 1))
            vectors.append(v)
            mpc.set_editor_property("vector_parameters", vectors)
        except Exception as e:
            unreal.log_warning("WPE Material: MPC created but param populate partial: {}".format(e))

        try:
            unreal.EditorAssetLibrary.save_asset(path)
        except Exception:
            pass
        unreal.log("WPE Material: created {}".format(path))
        return mpc
    except Exception as e:
        unreal.log_warning("WPE Material: ensure_mpc failed: {}".format(e))
        return None


def apply_world_params(snowline=0.72, rock_slope=0.55, wetness=0.35, macro_scale=1.0, tint=(1, 1, 1, 1), path=MPC_PATH) -> dict:
    ensure_mpc(path)
    if not hasattr(unreal, "WPEMaterialBridge"):
        return {"ok": False, "error": "WPEMaterialBridge missing — rebuild Runtime module"}
    color = unreal.LinearColor(float(tint[0]), float(tint[1]), float(tint[2]), float(tint[3] if len(tint) > 3 else 1.0))
    ok = unreal.WPEMaterialBridge.apply_world_mpc_params_by_path(
        None, path, float(snowline), float(rock_slope), float(wetness), float(macro_scale), color)
    unreal.log("WPE Material bridge apply ok={}".format(ok))
    return {"ok": bool(ok), "path": path}
