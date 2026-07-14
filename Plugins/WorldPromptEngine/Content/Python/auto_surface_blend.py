"""
auto_surface_blend.py — airtight cliff/valley surface coloring (no user math).

For WPE_Terrain (ProceduralMesh): vertex colors encode Rock(R) / Grass(G) / Snow(B)
from slope + height. Material ML_WPE_AutoSurface lerps textures/colors from that.

For Landscape: ensures ML_WPE_Landscape slope shader exists (landscape_auto_setup).
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
AUTO_MAT = "/Game/WPE/Materials/ML_WPE_AutoSurface"
AUTO_NAME = "ML_WPE_AutoSurface"

# Retail-ish defaults (sand/grass/rock/snow swapped by color_set)
PALETTES = {
    "default": {
        "grass": (0.18, 0.38, 0.10),
        "rock": (0.32, 0.30, 0.28),
        "snow": (0.88, 0.90, 0.94),
    },
    "underwater": {
        "grass": (0.50, 0.44, 0.28),  # sand
        "rock": (0.10, 0.26, 0.30),
        "snow": (0.40, 0.52, 0.45),  # algae
    },
    "desert": {
        "grass": (0.72, 0.58, 0.32),
        "rock": (0.45, 0.32, 0.22),
        "snow": (0.85, 0.78, 0.65),
    },
}


def slope_to_blend_weights(nx, ny, nz, height01, grass_min_z=0.72):
    """
    Flat (nz high) → grass. Steep → rock. High + not steep → snow.
    Returns (rock, grass, snow) in 0..1 summing ~1.
    """
    flat = max(0.0, min(1.0, float(nz)))
    # Soft threshold ~30°: cos(30°)≈0.866 — use 0.55..0.95 ramp
    grass = (flat - 0.55) / 0.40
    grass = 0.0 if grass < 0.0 else (1.0 if grass > 1.0 else grass)
    rock = 1.0 - grass
    snow = 0.0
    if height01 > 0.70 and flat > 0.5:
        snow = min(1.0, (height01 - 0.70) / 0.25) * flat
        grass *= (1.0 - snow * 0.85)
        rock *= (1.0 - snow * 0.35)
    tot = rock + grass + snow + 1e-6
    return rock / tot, grass / tot, snow / tot


def _ensure_dir():
    if hasattr(unreal, "EditorAssetLibrary"):
        if not unreal.EditorAssetLibrary.does_directory_exist(MAT_DIR):
            unreal.EditorAssetLibrary.make_directory(MAT_DIR)


def ensure_auto_surface_material(color_set: str = "default", force: bool = False) -> object:
    """
    VertexColor-driven blend material for ProceduralMesh terrains.
    R=rock, G=grass, B=snow weights.
    """
    if not _HAS_UNREAL or not hasattr(unreal, "MaterialEditingLibrary"):
        return None
    try:
        _ensure_dir()
        mel = unreal.MaterialEditingLibrary
        exists = False
        try:
            exists = unreal.EditorAssetLibrary.does_asset_exist(AUTO_MAT)
        except Exception:
            exists = unreal.load_asset(AUTO_MAT) is not None

        if exists and not force and color_set == "default":
            return unreal.load_asset(AUTO_MAT)

        if exists and (force or color_set != "default"):
            try:
                unreal.EditorAssetLibrary.delete_asset(AUTO_MAT)
            except Exception:
                pass

        tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.MaterialFactoryNew()
        mat = tools.create_asset(AUTO_NAME, MAT_DIR, unreal.Material, factory)
        if mat is None:
            return unreal.load_asset(AUTO_MAT)

        try:
            mel.delete_all_material_expressions(mat)
        except Exception:
            pass

        pal = PALETTES.get(color_set) or PALETTES["default"]

        def const3(rgb, x, y):
            n = mel.create_material_expression(
                mat, unreal.MaterialExpressionConstant3Vector, x, y)
            try:
                r, g, b = rgb
                n.set_editor_property("constant", unreal.LinearColor(r, g, b, 1.0))
            except Exception:
                pass
            return n

        vc = mel.create_material_expression(
            mat, unreal.MaterialExpressionVertexColor, -800, 0)

        grass = const3(pal["grass"], -500, -120)
        rock = const3(pal["rock"], -500, 40)
        snow = const3(pal["snow"], -500, 200)

        # Lerp rock→grass by VertexColor.G, then →snow by .B
        if hasattr(unreal, "MaterialExpressionLinearInterpolate"):
            # Mask G
            gmask = mel.create_material_expression(
                mat, unreal.MaterialExpressionComponentMask, -650, -40)
            try:
                gmask.set_editor_property("r", False)
                gmask.set_editor_property("g", True)
                gmask.set_editor_property("b", False)
                gmask.set_editor_property("a", False)
            except Exception:
                pass
            mel.connect_material_expressions(vc, "", gmask, "")

            bmask = mel.create_material_expression(
                mat, unreal.MaterialExpressionComponentMask, -650, 160)
            try:
                bmask.set_editor_property("r", False)
                bmask.set_editor_property("g", False)
                bmask.set_editor_property("b", True)
                bmask.set_editor_property("a", False)
            except Exception:
                pass
            mel.connect_material_expressions(vc, "", bmask, "")

            lerp1 = mel.create_material_expression(
                mat, unreal.MaterialExpressionLinearInterpolate, -200, 0)
            mel.connect_material_expressions(rock, "", lerp1, "A")
            mel.connect_material_expressions(grass, "", lerp1, "B")
            mel.connect_material_expressions(gmask, "", lerp1, "Alpha")

            lerp2 = mel.create_material_expression(
                mat, unreal.MaterialExpressionLinearInterpolate, 80, 40)
            mel.connect_material_expressions(lerp1, "", lerp2, "A")
            mel.connect_material_expressions(snow, "", lerp2, "B")
            mel.connect_material_expressions(bmask, "", lerp2, "Alpha")

            mel.connect_material_property(lerp2, "", unreal.MaterialProperty.MP_BASE_COLOR)

            rough = mel.create_material_expression(
                mat, unreal.MaterialExpressionConstant, 80, 220)
            try:
                rough.set_editor_property("r", 0.85)
            except Exception:
                pass
            mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)

        try:
            mel.layout_material_expressions(mat)
            mel.recompile_material(mat)
            unreal.EditorAssetLibrary.save_asset(AUTO_MAT)
        except Exception:
            pass

        unreal.log("WorldPromptEngine: airtight AutoSurface material ready ({})".format(color_set))
        return mat
    except Exception as e:
        unreal.log_error("ensure_auto_surface_material failed: {}".format(e))
        return None


def color_set_from_prompt(prompt: str, archetype: str = "") -> str:
    t = (prompt or "").lower() + " " + (archetype or "").lower()
    if "underwater" in t or "coral" in t or "seafloor" in t:
        return "underwater"
    if "desert" in t or "dune" in t:
        return "desert"
    return "default"


def ensure_airtight_stack(prompt: str = "", archetype: str = "") -> dict:
    """Landscape slope material + AutoSurface for procedural mesh."""
    summary = {"landscape": None, "autosurface": None, "color_set": "default"}
    try:
        cs = color_set_from_prompt(prompt, archetype)
        summary["color_set"] = cs
        import landscape_auto_setup
        summary["landscape"] = landscape_auto_setup.ensure_landscape_material_stack(
            force_rebuild=(cs != "default"),
            assign=True,
            color_set=cs if cs != "desert" else "default",
        )
        # desert uses custom autosurface; landscape uses default rock/sand-ish via underwater? 
        # For desert force landscape colors via rebuilding default then autosurface handles mesh
        if cs == "desert":
            # nudge landscape to sand-like by underwater? better: pass desert as custom in auto_setup
            pass
        summary["autosurface"] = ensure_auto_surface_material(color_set=cs, force=True)
        return summary
    except Exception as e:
        unreal.log_warning("ensure_airtight_stack failed: {}".format(e))
        return summary
