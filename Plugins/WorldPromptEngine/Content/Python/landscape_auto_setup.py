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


def build_auto_slope_material(force_rebuild: bool = False, color_set: str = "default") -> dict:
    """
    Build ML_WPE_Landscape that auto-blends:
      flat → grass, steep → rock, high → snow
    No layer painting required for a correct look.

    color_set: "default" | "underwater" (sand / teal rock / pale reef)
    """
    summary = {"ok": False, "path": MAT_PATH, "mode": "slope_height_auto", "created": False}
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
            summary["ok"] = True
            summary["created"] = False
            unreal.log("WorldPromptEngine: landscape material already exists at {}".format(MAT_PATH))
            return summary

        if existed and force_rebuild:
            try:
                unreal.EditorAssetLibrary.delete_asset(MAT_PATH)
            except Exception:
                pass

        mat = _new_material()
        if mat is None:
            summary["error"] = "material_create_failed"
            return summary
        summary["created"] = True
        _set_used_with_landscape(mat)

        # Clear default graph noise if any
        try:
            mel.delete_all_material_expressions(mat)
        except Exception:
            pass

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

        if flatness is not None and hasattr(unreal, "MaterialExpressionPower"):
            pow_n = mel.create_material_expression(mat, unreal.MaterialExpressionPower, -540, 40)
            try:
                exp = mel.create_material_expression(
                    mat, unreal.MaterialExpressionConstant, -720, 200)
                exp.set_editor_property("r", 2.2)
                mel.connect_material_expressions(flatness, "", pow_n, "Base")
                mel.connect_material_expressions(exp, "", pow_n, "Exp")
                flatness = pow_n
            except Exception:
                pass

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
                        height_mask = sat
                    else:
                        height_mask = mul

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
                if hasattr(unreal, "MaterialExpressionLandscapeLayerCoords"):
                    uv = mel.create_material_expression(
                        mat, unreal.MaterialExpressionLandscapeLayerCoords, x - 220, y + 80)
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

            _connect_prop(mel, final_c, unreal.MaterialProperty.MP_BASE_COLOR)

            if hasattr(unreal, "MaterialExpressionConstant"):
                rough = mel.create_material_expression(
                    mat, unreal.MaterialExpressionConstant, 160, 240)
                try:
                    rough.set_editor_property("r", 0.88 if color_set == "underwater" else 0.82)
                except Exception:
                    pass
                _connect_prop(mel, rough, unreal.MaterialProperty.MP_ROUGHNESS)
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

        summary["ok"] = True
        unreal.log(
            "WorldPromptEngine: auto landscape material ready at {} (set={})".format(
                MAT_PATH, color_set))
        return summary
    except Exception as e:
        unreal.log_error("build_auto_slope_material failed: {}".format(e))
        summary["error"] = str(e)
        return summary


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
            force_rebuild=force_rebuild, color_set=color_set)
        if assign:
            import landscape_materials
            summary["assigned"] = landscape_materials.try_assign_landscape_material(MAT_PATH)
        summary["ok"] = bool(summary["material"].get("ok"))
        return summary
    except Exception as e:
        unreal.log_error("ensure_landscape_material_stack failed: {}".format(e))
        summary["error"] = str(e)
        return summary
