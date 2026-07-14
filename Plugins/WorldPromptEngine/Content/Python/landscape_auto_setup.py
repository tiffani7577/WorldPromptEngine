"""
landscape_auto_setup.py — zero-click landscape material bootstrap for WorldPromptEngine.

Creates (if missing):
  /Game/WPE/Materials/ML_WPE_Landscape
  /Game/WPE/Materials/Layers/LI_Grass|LI_Rock|LI_Snow

The material blends Grass → Rock by slope and Snow by height in the shader,
so it looks correct WITHOUT manual Landscape Layer painting or Material Editor work.

Optional: if textures named *grass* / *rock* / *snow* exist under /Game, they are used.
"""

from __future__ import annotations

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


MAT_DIR = "/Game/WPE/Materials"
LAYER_DIR = "/Game/WPE/Materials/Layers"
MAT_PATH = "/Game/WPE/Materials/ML_WPE_Landscape"
MAT_NAME = "ML_WPE_Landscape"
MPC_PATH = "/Game/WPE/Materials/MPC_WPE_World"
MPC_NAME = "MPC_WPE_World"

LAYER_INFOS = (
    ("LI_Grass", "Grass"),
    ("LI_Rock", "Rock"),
    ("LI_Snow", "Snow"),
)

# Fallback albedo if no project textures found
COLORS = {
    "Grass": (0.20, 0.36, 0.11),
    "Rock": (0.30, 0.28, 0.26),
    "Snow": (0.86, 0.89, 0.93),
}


def _ensure_dirs():
    if not hasattr(unreal, "EditorAssetLibrary"):
        return
    for d in (MAT_DIR, LAYER_DIR, "/Game/WPE"):
        try:
            if not unreal.EditorAssetLibrary.does_directory_exist(d):
                unreal.EditorAssetLibrary.make_directory(d)
        except Exception:
            pass


def _asset_exists(path: str) -> bool:
    try:
        if hasattr(unreal, "EditorAssetLibrary"):
            return bool(unreal.EditorAssetLibrary.does_asset_exist(path))
        return unreal.load_asset(path) is not None
    except Exception:
        return False


def ensure_layer_infos() -> dict:
    """Create LandscapeLayerInfoObject assets for Grass/Rock/Snow."""
    out = {}
    if not _HAS_UNREAL:
        return out
    try:
        _ensure_dirs()
        tools = unreal.AssetToolsHelpers.get_asset_tools() if hasattr(unreal, "AssetToolsHelpers") else None
        factory = None
        if hasattr(unreal, "LandscapeLayerInfoObjectFactory"):
            factory = unreal.LandscapeLayerInfoObjectFactory()

        for asset_name, layer_name in LAYER_INFOS:
            path = "{}/{}".format(LAYER_DIR, asset_name)
            if _asset_exists(path):
                out[layer_name] = path
                continue
            asset = None
            try:
                if tools is not None and factory is not None and hasattr(unreal, "LandscapeLayerInfoObject"):
                    asset = tools.create_asset(
                        asset_name, LAYER_DIR, unreal.LandscapeLayerInfoObject, factory)
                elif tools is not None and hasattr(unreal, "LandscapeLayerInfoObject"):
                    # Some builds omit the factory class — try None factory
                    asset = tools.create_asset(
                        asset_name, LAYER_DIR, unreal.LandscapeLayerInfoObject, None)
            except Exception as ce:
                unreal.log_warning("Layer info create {}: {}".format(asset_name, ce))
            if asset is not None:
                try:
                    if hasattr(asset, "set_editor_property"):
                        # Layer name used by landscape paint UI
                        asset.set_editor_property("layer_name", layer_name)
                except Exception:
                    pass
                try:
                    if hasattr(unreal, "EditorAssetLibrary"):
                        unreal.EditorAssetLibrary.save_asset(path)
                except Exception:
                    pass
                out[layer_name] = path
                unreal.log("WorldPromptEngine: created {}".format(path))
            else:
                unreal.log_warning("WorldPromptEngine: could not create {}".format(path))
        return out
    except Exception as e:
        unreal.log_error("ensure_layer_infos failed: {}".format(e))
        return out


def _find_texture_hint(hints) -> object:
    """Best-effort: first Texture2D in /Game whose name contains a hint."""
    if not hasattr(unreal, "AssetRegistryHelpers"):
        return None
    try:
        reg = unreal.AssetRegistryHelpers.get_asset_registry()
        # Narrow filter — avoid scanning the entire engine
        roots = ["/Game/WPE", "/Game"]
        for root in roots:
            try:
                assets = reg.get_assets_by_path(root, True)
            except Exception:
                assets = []
            for a in assets or []:
                try:
                    name = str(a.asset_name).lower()
                    cls = str(getattr(a, "asset_class_path", None) or getattr(a, "asset_class", "")).lower()
                    if "texture" not in cls and "Texture2D" not in str(getattr(a, "asset_class", "")):
                        # UE5 uses TopLevelAssetPath
                        ac = getattr(a, "asset_class_path", None)
                        if ac is not None and "Texture2D" not in str(ac):
                            continue
                    if any(h in name for h in hints):
                        path = a.package_name
                        # package_name is /Game/.../Asset without .Asset sometimes
                        full = "{}.{}".format(path, a.asset_name)
                        tex = unreal.load_asset(str(full))
                        if tex is None:
                            tex = unreal.load_asset(str(path))
                        if tex is not None:
                            return tex
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _mel():
    return unreal.MaterialEditingLibrary if hasattr(unreal, "MaterialEditingLibrary") else None


def ensure_mpc_world():
    """
    Ensure /Game/WPE/Materials/MPC_WPE_World exists with Director param names.
    Reuses wpe_material_bridge when available.
    """
    try:
        import wpe_material_bridge
        return wpe_material_bridge.ensure_mpc(MPC_PATH)
    except Exception:
        pass
    if _asset_exists(MPC_PATH):
        return unreal.load_asset(MPC_PATH)
    try:
        _ensure_dirs()
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.MaterialParameterCollectionFactoryNew()
        mpc = tools.create_asset(MPC_NAME, MAT_DIR, unreal.MaterialParameterCollection, factory)
        if mpc is None:
            return None
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
        v = unreal.CollectionVectorParameter()
        v.set_editor_property("parameter_name", "WorldTint")
        v.set_editor_property("default_value", unreal.LinearColor(1, 1, 1, 1))
        mpc.set_editor_property("vector_parameters", [v])
        try:
            unreal.EditorAssetLibrary.save_asset(MPC_PATH)
        except Exception:
            pass
        return mpc
    except Exception as e:
        unreal.log_warning("ensure_mpc_world failed: {}".format(e))
        return None


def _mpc_param(mat, mel, mpc, name, x, y):
    """MaterialExpressionCollectionParameter bound to MPC."""
    if not hasattr(unreal, "MaterialExpressionCollectionParameter"):
        return None
    node = mel.create_material_expression(
        mat, unreal.MaterialExpressionCollectionParameter, x, y)
    try:
        node.set_editor_property("collection", mpc)
        node.set_editor_property("parameter_name", name)
    except Exception as e:
        unreal.log_warning("MPC param {} bind failed: {}".format(name, e))
    return node


def _material_has_mpc_wiring(mat) -> bool:
    """True if ML_WPE_Landscape already samples Snowline from MPC_WPE_World."""
    try:
        exprs = []
        if hasattr(unreal, "MaterialEditingLibrary"):
            # get_material_expressions may not exist on all builds — scan via property
            try:
                exprs = list(mat.get_editor_property("expressions") or [])
            except Exception:
                exprs = []
        for e in exprs:
            try:
                if e is None:
                    continue
                cname = e.get_class().get_name()
                if "CollectionParameter" not in cname:
                    continue
                pname = str(e.get_editor_property("parameter_name") or "")
                coll = e.get_editor_property("collection")
                if pname == "Snowline" and coll is not None:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _new_material():
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew() if hasattr(unreal, "MaterialFactoryNew") else None
    if factory is None:
        return None
    if _asset_exists(MAT_PATH):
        # Delete and recreate only if force — caller handles
        return unreal.load_asset(MAT_PATH)
    mat = tools.create_asset(MAT_NAME, MAT_DIR, unreal.Material, factory)
    return mat


def _set_used_with_landscape(mat) -> None:
    try:
        if hasattr(mat, "set_editor_property"):
            mat.set_editor_property("b_used_with_landscape", True)
    except Exception:
        pass
    try:
        # Alternate property naming across builds
        mat.set_editor_property("used_with_landscape", True)
    except Exception:
        pass


def _const3(mat, mel, rgb, x, y):
    node = mel.create_material_expression(
        mat, unreal.MaterialExpressionConstant3Vector, x, y)
    try:
        r, g, b = rgb
        if hasattr(unreal, "LinearColor"):
            node.set_editor_property("constant", unreal.LinearColor(r, g, b, 1.0))
        else:
            node.constant = (r, g, b)
    except Exception:
        pass
    return node


def _connect_prop(mel, expr, prop):
    try:
        mel.connect_material_property(expr, "", prop)
        return True
    except Exception:
        return False


def build_auto_slope_material(force_rebuild: bool = False, color_set: str = "default",
                              wire_mpc: bool = True) -> dict:
    """
    Build/upgrade ML_WPE_Landscape that auto-blends:
      flat → grass, steep → rock, high → snow
    When wire_mpc=True, drives Snowline/RockSlope/Wetness/MacroScale/WorldTint from MPC_WPE_World.
    Never creates a different material path — only ML_WPE_Landscape.
    """
    summary = {"ok": False, "path": MAT_PATH, "mode": "slope_height_mpc", "created": False, "mpc_wired": False}
    if not _HAS_UNREAL:
        summary["error"] = "no_unreal"
        return summary

    try:
        _ensure_dirs()
        mel = _mel()
        if mel is None:
            summary["error"] = "MaterialEditingLibrary unavailable"
            unreal.log_warning("WorldPromptEngine: {}".format(summary["error"]))
            return summary

        mpc = ensure_mpc_world() if wire_mpc else None
        if wire_mpc and mpc is None:
            unreal.log_warning("WorldPromptEngine: MPC_WPE_World missing — building without MPC params")

        palette = dict(COLORS)
        if color_set == "underwater":
            palette = {
                "Grass": (0.52, 0.46, 0.30),   # seafloor sand
                "Rock": (0.12, 0.28, 0.32),    # teal stone
                "Snow": (0.45, 0.55, 0.48),    # algae / pale reef
            }
            force_rebuild = True

        existed = _asset_exists(MAT_PATH)
        if existed and not force_rebuild:
            mat = unreal.load_asset(MAT_PATH)
            _set_used_with_landscape(mat)
            if wire_mpc and mpc is not None and not _material_has_mpc_wiring(mat):
                unreal.log("WorldPromptEngine: upgrading existing ML_WPE_Landscape with MPC wiring (same asset)")
                force_rebuild = True
            elif wire_mpc and _material_has_mpc_wiring(mat):
                summary["ok"] = True
                summary["created"] = False
                summary["mpc_wired"] = True
                unreal.log("WorldPromptEngine: landscape material already MPC-wired at {}".format(MAT_PATH))
                return summary
            elif not force_rebuild:
                summary["ok"] = True
                summary["created"] = False
                unreal.log("WorldPromptEngine: landscape material already exists at {}".format(MAT_PATH))
                return summary

        if existed and force_rebuild:
            mat = unreal.load_asset(MAT_PATH)
            if mat is None:
                try:
                    unreal.EditorAssetLibrary.delete_asset(MAT_PATH)
                except Exception:
                    pass
                mat = _new_material()
                summary["created"] = True
            else:
                # In-place graph rebuild — do not replace the asset path
                try:
                    mel.delete_all_material_expressions(mat)
                except Exception:
                    pass
                summary["created"] = False
        else:
            mat = _new_material()
            if mat is None:
                summary["error"] = "material_create_failed"
                return summary
            summary["created"] = True
            try:
                mel.delete_all_material_expressions(mat)
            except Exception:
                pass

        if mat is None:
            summary["error"] = "material_missing"
            return summary

        _set_used_with_landscape(mat)

        # --- MPC parameters (optional) ---
        snowline = _mpc_param(mat, mel, mpc, "Snowline", -1400, 600) if mpc else None
        rock_slope = _mpc_param(mat, mel, mpc, "RockSlope", -1400, 700) if mpc else None
        wetness = _mpc_param(mat, mel, mpc, "Wetness", -1400, 800) if mpc else None
        macro_scale = _mpc_param(mat, mel, mpc, "MacroScale", -1400, 900) if mpc else None
        world_tint = _mpc_param(mat, mel, mpc, "WorldTint", -1400, 1000) if mpc else None
        summary["mpc_wired"] = bool(snowline and rock_slope and wetness and macro_scale and world_tint)

        # --- Slope from vertex normal (works on Landscape) ---
        nrm = None
        for cls_name in ("MaterialExpressionVertexNormalWS", "MaterialExpressionPixelNormalWS"):
            if hasattr(unreal, cls_name):
                nrm = mel.create_material_expression(mat, getattr(unreal, cls_name), -1200, 0)
                break
        up = _const3(mat, mel, (0.0, 0.0, 1.0), -1200, 160)

        flatness = None
        if nrm is not None and hasattr(unreal, "MaterialExpressionDotProduct"):
            flatness = mel.create_material_expression(
                mat, unreal.MaterialExpressionDotProduct, -900, 40)
            try:
                mel.connect_material_expressions(nrm, "", flatness, "A")
                mel.connect_material_expressions(up, "", flatness, "B")
            except Exception:
                try:
                    mel.connect_material_expressions(nrm, "", flatness, "a")
                    mel.connect_material_expressions(up, "", flatness, "b")
                except Exception:
                    pass

        if flatness is not None and hasattr(unreal, "MaterialExpressionAbs"):
            absn = mel.create_material_expression(mat, unreal.MaterialExpressionAbs, -720, 40)
            mel.connect_material_expressions(flatness, "", absn, "")
            flatness = absn

        # RockSlope: higher → more rock (steepen flatness curve via Power(flatness, 1+RockSlope*3))
        if flatness is not None and hasattr(unreal, "MaterialExpressionPower"):
            pow_n = mel.create_material_expression(mat, unreal.MaterialExpressionPower, -540, 40)
            try:
                if rock_slope is not None and hasattr(unreal, "MaterialExpressionAdd") and hasattr(unreal, "MaterialExpressionMultiply"):
                    one = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -720, 200)
                    one.set_editor_property("r", 1.0)
                    three = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -720, 260)
                    three.set_editor_property("r", 3.0)
                    mul_rs = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -560, 220)
                    mel.connect_material_expressions(rock_slope, "", mul_rs, "A")
                    mel.connect_material_expressions(three, "", mul_rs, "B")
                    exp = mel.create_material_expression(mat, unreal.MaterialExpressionAdd, -400, 220)
                    mel.connect_material_expressions(one, "", exp, "A")
                    mel.connect_material_expressions(mul_rs, "", exp, "B")
                    mel.connect_material_expressions(flatness, "", pow_n, "Base")
                    mel.connect_material_expressions(exp, "", pow_n, "Exp")
                else:
                    exp = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -720, 200)
                    exp.set_editor_property("r", 2.2)
                    mel.connect_material_expressions(flatness, "", pow_n, "Base")
                    mel.connect_material_expressions(exp, "", pow_n, "Exp")
                flatness = pow_n
            except Exception as pe:
                unreal.log_warning("RockSlope power wire: {}".format(pe))

        # Elevation 0..1 from world Z, then snow mask vs Snowline
        height_01 = None
        height_mask = None
        if hasattr(unreal, "MaterialExpressionAbsoluteWorldPosition"):
            wp = mel.create_material_expression(
                mat, unreal.MaterialExpressionAbsoluteWorldPosition, -1200, 400)
            if hasattr(unreal, "MaterialExpressionComponentMask"):
                zmask = mel.create_material_expression(
                    mat, unreal.MaterialExpressionComponentMask, -980, 400)
                try:
                    zmask.set_editor_property("r", False)
                    zmask.set_editor_property("g", False)
                    zmask.set_editor_property("b", True)
                    zmask.set_editor_property("a", False)
                except Exception:
                    pass
                mel.connect_material_expressions(wp, "", zmask, "")
                if hasattr(unreal, "MaterialExpressionMultiply"):
                    mul = mel.create_material_expression(
                        mat, unreal.MaterialExpressionMultiply, -780, 400)
                    scale = mel.create_material_expression(
                        mat, unreal.MaterialExpressionConstant, -980, 520)
                    try:
                        scale.set_editor_property("r", 0.00035)
                    except Exception:
                        pass
                    mel.connect_material_expressions(zmask, "", mul, "A")
                    mel.connect_material_expressions(scale, "", mul, "B")
                    if hasattr(unreal, "MaterialExpressionSaturate"):
                        sat = mel.create_material_expression(
                            mat, unreal.MaterialExpressionSaturate, -560, 400)
                        mel.connect_material_expressions(mul, "", sat, "")
                        height_01 = sat
                    else:
                        height_01 = mul

        if height_01 is not None and snowline is not None and hasattr(unreal, "MaterialExpressionSmoothStep"):
            # SmoothStep(Snowline, 1, height) → snow alpha
            one_c = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 520)
            try:
                one_c.set_editor_property("r", 1.0)
            except Exception:
                pass
            ss = mel.create_material_expression(mat, unreal.MaterialExpressionSmoothStep, -280, 400)
            try:
                mel.connect_material_expressions(snowline, "", ss, "Min")
                mel.connect_material_expressions(one_c, "", ss, "Max")
                mel.connect_material_expressions(height_01, "", ss, "Value")
                height_mask = ss
            except Exception:
                # Fallback: saturate(height - snowline)
                if hasattr(unreal, "MaterialExpressionSubtract"):
                    sub = mel.create_material_expression(mat, unreal.MaterialExpressionSubtract, -280, 400)
                    mel.connect_material_expressions(height_01, "", sub, "A")
                    mel.connect_material_expressions(snowline, "", sub, "B")
                    if hasattr(unreal, "MaterialExpressionSaturate"):
                        sat2 = mel.create_material_expression(mat, unreal.MaterialExpressionSaturate, -120, 400)
                        mel.connect_material_expressions(sub, "", sat2, "")
                        height_mask = sat2
                    else:
                        height_mask = sub
        elif height_01 is not None:
            height_mask = height_01

        grass_tex = None if color_set == "underwater" else _find_texture_hint(("grass", "soil", "ground", "lawn", "moss"))
        rock_tex = None if color_set == "underwater" else _find_texture_hint(("rock", "cliff", "stone", "granite", "slate"))
        snow_tex = None if color_set == "underwater" else _find_texture_hint(("snow", "ice", "frost"))

        def albedo_node(label, rgb, tex, x, y):
            if tex is not None and hasattr(unreal, "MaterialExpressionTextureSample"):
                ts = mel.create_material_expression(
                    mat, unreal.MaterialExpressionTextureSample, x, y)
                try:
                    ts.set_editor_property("texture", tex)
                except Exception:
                    pass
                # MacroScale drives UV tiling when LandscapeLayerCoords available
                if hasattr(unreal, "MaterialExpressionLandscapeLayerCoords"):
                    uv = mel.create_material_expression(
                        mat, unreal.MaterialExpressionLandscapeLayerCoords, x - 280, y + 80)
                    if macro_scale is not None and hasattr(unreal, "MaterialExpressionMultiply"):
                        # Append MacroScale.xx as UV scale
                        uv_mul = mel.create_material_expression(
                            mat, unreal.MaterialExpressionMultiply, x - 140, y + 80)
                        try:
                            mel.connect_material_expressions(uv, "", uv_mul, "A")
                            mel.connect_material_expressions(macro_scale, "", uv_mul, "B")
                            mel.connect_material_expressions(uv_mul, "", ts, "UVs")
                        except Exception:
                            try:
                                mel.connect_material_expressions(uv, "", ts, "UVs")
                            except Exception:
                                pass
                    else:
                        try:
                            mel.connect_material_expressions(uv, "", ts, "UVs")
                        except Exception:
                            pass
                return ts
            return _const3(mat, mel, rgb, x, y)

        grass = albedo_node("Grass", palette["Grass"], grass_tex, -400, -120)
        rock = albedo_node("Rock", palette["Rock"], rock_tex, -400, 80)
        snow = albedo_node("Snow", palette["Snow"], snow_tex, -400, 320)

        if hasattr(unreal, "MaterialExpressionLinearInterpolate") and flatness is not None:
            lerp_gr = mel.create_material_expression(
                mat, unreal.MaterialExpressionLinearInterpolate, -80, 0)
            try:
                mel.connect_material_expressions(rock, "", lerp_gr, "A")
                mel.connect_material_expressions(grass, "", lerp_gr, "B")
                mel.connect_material_expressions(flatness, "", lerp_gr, "Alpha")
            except Exception as le:
                unreal.log_warning("lerp grass/rock connect: {}".format(le))

            final_c = lerp_gr
            if height_mask is not None:
                lerp_sn = mel.create_material_expression(
                    mat, unreal.MaterialExpressionLinearInterpolate, 160, 40)
                try:
                    mel.connect_material_expressions(lerp_gr, "", lerp_sn, "A")
                    mel.connect_material_expressions(snow, "", lerp_sn, "B")
                    mel.connect_material_expressions(height_mask, "", lerp_sn, "Alpha")
                    final_c = lerp_sn
                except Exception as le2:
                    unreal.log_warning("lerp snow connect: {}".format(le2))

            # Wetness darkening: lerp(color, color*0.55, Wetness)
            if wetness is not None and hasattr(unreal, "MaterialExpressionMultiply"):
                try:
                    dark = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, 280, 200)
                    dark.set_editor_property("constant", unreal.LinearColor(0.55, 0.55, 0.55, 1.0))
                    mul_d = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 360, 40)
                    mel.connect_material_expressions(final_c, "", mul_d, "A")
                    mel.connect_material_expressions(dark, "", mul_d, "B")
                    lerp_w = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 480, 40)
                    mel.connect_material_expressions(final_c, "", lerp_w, "A")
                    mel.connect_material_expressions(mul_d, "", lerp_w, "B")
                    mel.connect_material_expressions(wetness, "", lerp_w, "Alpha")
                    final_c = lerp_w
                except Exception as we:
                    unreal.log_warning("Wetness wire: {}".format(we))

            # WorldTint multiply
            if world_tint is not None and hasattr(unreal, "MaterialExpressionMultiply"):
                try:
                    mul_t = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 640, 40)
                    mel.connect_material_expressions(final_c, "", mul_t, "A")
                    mel.connect_material_expressions(world_tint, "", mul_t, "B")
                    final_c = mul_t
                except Exception as te:
                    unreal.log_warning("WorldTint wire: {}".format(te))

            _connect_prop(mel, final_c, unreal.MaterialProperty.MP_BASE_COLOR)

            # Roughness: dry ~0.82, wet → ~0.45
            if hasattr(unreal, "MaterialExpressionConstant"):
                rough_dry = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, 480, 240)
                try:
                    rough_dry.set_editor_property("r", 0.88 if color_set == "underwater" else 0.82)
                except Exception:
                    pass
                rough_final = rough_dry
                if wetness is not None and hasattr(unreal, "MaterialExpressionLinearInterpolate"):
                    rough_wet = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, 480, 300)
                    try:
                        rough_wet.set_editor_property("r", 0.45)
                    except Exception:
                        pass
                    lerp_r = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 640, 260)
                    try:
                        mel.connect_material_expressions(rough_dry, "", lerp_r, "A")
                        mel.connect_material_expressions(rough_wet, "", lerp_r, "B")
                        mel.connect_material_expressions(wetness, "", lerp_r, "Alpha")
                        rough_final = lerp_r
                    except Exception:
                        pass
                _connect_prop(mel, rough_final, unreal.MaterialProperty.MP_ROUGHNESS)
        else:
            _connect_prop(mel, grass, unreal.MaterialProperty.MP_BASE_COLOR)

        try:
            if hasattr(unreal, "MaterialExpressionLandscapeLayerBlend"):
                blend = mel.create_material_expression(
                    mat, unreal.MaterialExpressionLandscapeLayerBlend, -400, 560)
                if hasattr(unreal, "LayerBlendInput"):
                    arr = []
                    for name, w in (("Grass", 1.0), ("Rock", 0.0), ("Snow", 0.0)):
                        inp = unreal.LayerBlendInput()
                        inp.set_editor_property("layer_name", name)
                        try:
                            inp.set_editor_property(
                                "blend_type", unreal.LayerBlendType.LB_WEIGHT_BLEND)
                        except Exception:
                            pass
                        try:
                            inp.set_editor_property("preview_weight", w)
                        except Exception:
                            pass
                        arr.append(inp)
                    try:
                        blend.set_editor_property("layers", arr)
                    except Exception:
                        pass
        except Exception as be:
            unreal.log_warning("layer blend stub skipped: {}".format(be))

        try:
            mel.layout_material_expressions(mat)
        except Exception:
            pass
        try:
            mel.recompile_material(mat)
        except Exception:
            pass
        try:
            unreal.EditorAssetLibrary.save_asset(MAT_PATH)
        except Exception:
            pass
        if mpc is not None:
            try:
                unreal.EditorAssetLibrary.save_asset(MPC_PATH)
            except Exception:
                pass

        summary["ok"] = True
        unreal.log(
            "WorldPromptEngine: auto landscape material ready at {} (set={} mpc_wired={})".format(
                MAT_PATH, color_set, summary["mpc_wired"]))
        return summary
    except Exception as e:
        unreal.log_error("build_auto_slope_material failed: {}".format(e))
        summary["error"] = str(e)
        return summary


def wire_mpc_into_existing_landscape_material(color_set: str = "default") -> dict:
    """
    Upgrade ML_WPE_Landscape in place with MPC controls. Does not create a new material asset.
    """
    return build_auto_slope_material(force_rebuild=True, color_set=color_set, wire_mpc=True)


def ensure_landscape_material_stack(force_rebuild: bool = False, assign: bool = True,
                                    color_set: str = "default") -> dict:
    """
    Full auto path: layer infos + material + assign to landscapes in level.
    """
    summary = {
        "ok": False,
        "layer_infos": {},
        "material": {},
        "assigned": False,
    }
    if not _HAS_UNREAL:
        return summary
    try:
        summary["layer_infos"] = ensure_layer_infos()
        summary["material"] = build_auto_slope_material(
            force_rebuild=force_rebuild, color_set=color_set, wire_mpc=True)
        if assign:
            import landscape_materials
            summary["assigned"] = landscape_materials.try_assign_landscape_material(MAT_PATH)
            # Also assign via landscape_apply helper path for WPE labeled actors
            try:
                import landscape_apply
                # soft assign already handled; ensure MPC defaults applied
                import wpe_material_bridge
                summary["mpc"] = wpe_material_bridge.apply_world_params()
            except Exception:
                pass
        summary["ok"] = bool(summary["material"].get("ok"))
        return summary
    except Exception as e:
        unreal.log_error("ensure_landscape_material_stack failed: {}".format(e))
        summary["error"] = str(e)
        return summary
