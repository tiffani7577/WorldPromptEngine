"""
structure_forge.py — procedural structure mesh families for WorldPromptEngine (UE 5.8)

Six generator families:
  keep | ruin | crystal | megalith | hut | arch

Strategy:
  1. Prefer an already-forged StaticMesh under /Game/WPE/Structures/Generated/
  2. If Geometry Script / DynamicMesh APIs exist, build and save a mesh
  3. Else fall back to composed BasicShapes proxies (distinct silhouettes)

MAIN THREAD ONLY.
"""

from __future__ import annotations

import math

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False

    class _StubLog:
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
    unreal = _StubLog()  # type: ignore


GENERATED_ROOT = "/Game/WPE/Structures/Generated"

_PROXY_MESHES = {
    "cube": "/Engine/BasicShapes/Cube.Cube",
    "sphere": "/Engine/BasicShapes/Sphere.Sphere",
    "cylinder": "/Engine/BasicShapes/Cylinder.Cylinder",
    "cone": "/Engine/BasicShapes/Cone.Cone",
}

# family -> list of box/cylinder/cone parts in local cm (used by GS and proxy)
# Each part: kind, center (x,y,z), size (x,y,z) or (r,r,h) for cyl/cone, yaw_deg
FAMILY_RECIPES = {
    "keep": [
        {"kind": "box", "center": (0, 0, 200), "size": (600, 600, 400), "yaw": 0},
        {"kind": "box", "center": (0, 0, 450), "size": (400, 400, 200), "yaw": 0},
        {"kind": "cyl", "center": (320, 320, 280), "size": (70, 70, 560), "yaw": 0},
        {"kind": "cyl", "center": (-320, 320, 280), "size": (70, 70, 560), "yaw": 0},
        {"kind": "cyl", "center": (320, -320, 280), "size": (70, 70, 560), "yaw": 0},
        {"kind": "cyl", "center": (-320, -320, 280), "size": (70, 70, 560), "yaw": 0},
        {"kind": "cone", "center": (320, 320, 600), "size": (90, 90, 160), "yaw": 0},
        {"kind": "cone", "center": (-320, -320, 600), "size": (90, 90, 160), "yaw": 0},
    ],
    "ruin": [
        {"kind": "cyl", "center": (0, 0, 220), "size": (90, 90, 440), "yaw": 12},
        {"kind": "box", "center": (70, -30, 380), "size": (140, 60, 160), "yaw": 28},
        {"kind": "box", "center": (-50, 80, 60), "size": (120, 90, 50), "yaw": 8},
        {"kind": "box", "center": (40, 100, 20), "size": (80, 50, 30), "yaw": -15},
    ],
    "crystal": [
        {"kind": "cone", "center": (0, 0, 260), "size": (110, 110, 520), "yaw": 0},
        {"kind": "cone", "center": (70, 40, 200), "size": (70, 70, 380), "yaw": 18},
        {"kind": "cone", "center": (-55, -35, 180), "size": (55, 55, 320), "yaw": -12},
        {"kind": "cone", "center": (20, -70, 140), "size": (40, 40, 240), "yaw": 40},
    ],
    "megalith": [
        {"kind": "box", "center": (350, 0, 160), "size": (60, 40, 320), "yaw": 0},
        {"kind": "box", "center": (-350, 0, 160), "size": (60, 40, 320), "yaw": 0},
        {"kind": "box", "center": (0, 350, 160), "size": (60, 40, 320), "yaw": 90},
        {"kind": "box", "center": (0, -350, 160), "size": (60, 40, 320), "yaw": 90},
        {"kind": "box", "center": (250, 250, 160), "size": (55, 35, 300), "yaw": 45},
        {"kind": "box", "center": (-250, -250, 160), "size": (55, 35, 300), "yaw": 45},
        {"kind": "box", "center": (0, 0, 40), "size": (220, 220, 40), "yaw": 0},
    ],
    "hut": [
        {"kind": "box", "center": (0, 0, 90), "size": (240, 200, 160), "yaw": 0},
        {"kind": "cone", "center": (0, 0, 220), "size": (280, 280, 160), "yaw": 0},
        {"kind": "box", "center": (0, 110, 70), "size": (60, 20, 100), "yaw": 0},
    ],
    "arch": [
        {"kind": "box", "center": (-160, 0, 200), "size": (100, 140, 400), "yaw": 0},
        {"kind": "box", "center": (160, 0, 200), "size": (100, 140, 400), "yaw": 0},
        {"kind": "box", "center": (0, 0, 420), "size": (420, 140, 100), "yaw": 0},
        {"kind": "box", "center": (0, 0, 40), "size": (480, 200, 40), "yaw": 0},
    ],
}

# Map structure catalog ids / categories -> forge family
FAMILY_BY_STRUCTURE = {
    "stone_keep": "keep", "watchtower": "keep", "lighthouse": "keep",
    "wizard_tower": "keep", "pagoda": "keep", "windmill": "keep",
    "ruined_tower": "ruin", "temple_ruin": "ruin", "shipwreck": "ruin",
    "graveyard": "ruin", "mine_entrance": "ruin",
    "crystal_spire": "crystal", "floating_boulder": "crystal",
    "portal_ring": "crystal", "ice_monolith": "crystal", "lava_spine": "crystal",
    "stone_circle": "megalith", "obelisk": "megalith", "totem": "megalith",
    "dragon_perch": "megalith",
    "village_hut": "hut", "longhouse": "hut", "barn": "hut",
    "camp_tents": "hut", "dock_pier": "hut",
    "bridge_arch": "arch", "arch_rock": "arch", "mesa_butte": "arch",
    "waterfall_rocks": "arch", "pyramid": "arch",
    "oil_derrick": "keep", "radar_dish": "keep",
    "mangrove_root": "ruin", "giant_bone": "ruin", "coral_stack": "crystal",
}

FAMILY_BY_CATEGORY = {
    "architecture": "keep",
    "ruins": "ruin",
    "mystical": "crystal",
    "geological": "arch",
    "megalith": "megalith",
    "settlement": "hut",
    "natural": "arch",
    "industrial": "keep",
}


def list_families():
    return sorted(FAMILY_RECIPES.keys())


def resolve_family(structure_name: str, category: str = "") -> str:
    if structure_name in FAMILY_BY_STRUCTURE:
        return FAMILY_BY_STRUCTURE[structure_name]
    if category in FAMILY_BY_CATEGORY:
        return FAMILY_BY_CATEGORY[category]
    return "hut"


def geometry_script_available() -> bool:
    if not _HAS_UNREAL:
        return False
    has_dm = hasattr(unreal, "DynamicMesh")
    # Probe common GS library names across UE 5.x Python bindings
    libs = (
        "GeometryScript_MeshPrimitiveFunctions",
        "GeometryScriptMeshPrimitiveFunctions",
        "GeometryScriptLibrary",
    )
    has_lib = any(hasattr(unreal, name) for name in libs)
    return bool(has_dm and has_lib)


def _gs_primitive_lib():
    for name in (
        "GeometryScript_MeshPrimitiveFunctions",
        "GeometryScriptMeshPrimitiveFunctions",
    ):
        lib = getattr(unreal, name, None)
        if lib is not None:
            return lib
    return None


def _ensure_generated_dir():
    if not _HAS_UNREAL or not hasattr(unreal, "EditorAssetLibrary"):
        return
    try:
        if not unreal.EditorAssetLibrary.does_directory_exist(GENERATED_ROOT):
            unreal.EditorAssetLibrary.make_directory(GENERATED_ROOT)
        # parents
        for path in ("/Game/WPE", "/Game/WPE/Structures"):
            if not unreal.EditorAssetLibrary.does_directory_exist(path):
                unreal.EditorAssetLibrary.make_directory(path)
    except Exception as e:
        unreal.log_warning("structure_forge: mkdir failed: {}".format(e))


def generated_asset_path(family: str) -> str:
    return "{}/SM_WPE_{}".format(GENERATED_ROOT, family)


def load_forged_mesh(family: str):
    if not _HAS_UNREAL:
        return None
    path = generated_asset_path(family)
    try:
        mesh = unreal.load_asset(path)
        if mesh is None:
            leaf = path.split("/")[-1]
            mesh = unreal.load_asset("{}.{}".format(path, leaf))
        return mesh
    except Exception:
        return None


def _append_gs_part(dyn_mesh, part: dict) -> bool:
    """Best-effort Geometry Script primitive append. Returns False if API missing."""
    lib = _gs_primitive_lib()
    if lib is None or dyn_mesh is None:
        return False
    kind = part.get("kind", "box")
    cx, cy, cz = part["center"]
    sx, sy, sz = part["size"]
    yaw = float(part.get("yaw", 0.0))
    try:
        transform = unreal.Transform(
            unreal.Vector(float(cx), float(cy), float(cz)),
            unreal.Rotator(0.0, yaw, 0.0),
            unreal.Vector(1.0, 1.0, 1.0),
        )
        opts = None
        if hasattr(unreal, "GeometryScriptPrimitiveOptions"):
            opts = unreal.GeometryScriptPrimitiveOptions()

        if kind == "box" and hasattr(lib, "append_box"):
            # signatures vary; try common ones
            try:
                lib.append_box(dyn_mesh, transform, float(sx), float(sy), float(sz), 0, 0, 0, opts)
            except TypeError:
                lib.append_box(dyn_mesh, float(sx), float(sy), float(sz), 0, 0, 0, transform, opts)
            return True
        if kind == "cyl" and hasattr(lib, "append_cylinder"):
            try:
                lib.append_cylinder(dyn_mesh, transform, float(sx), float(sz), 16, 0, True, True, opts)
            except TypeError:
                lib.append_cylinder(dyn_mesh, float(sx), float(sz), 16, transform, opts)
            return True
        if kind == "cone" and hasattr(lib, "append_cone"):
            try:
                lib.append_cone(dyn_mesh, transform, float(sx), 0.0, float(sz), 16, 0, True, True, opts)
            except TypeError:
                lib.append_cone(dyn_mesh, float(sx), float(sz), 16, transform, opts)
            return True
        # Fallbacks via box if specific primitive missing
        if hasattr(lib, "append_box"):
            try:
                lib.append_box(dyn_mesh, transform, float(sx), float(sy), float(sz), 0, 0, 0, opts)
                return True
            except Exception:
                return False
    except Exception as e:
        unreal.log_warning("structure_forge GS part failed ({}): {}".format(kind, e))
    return False


def _save_dynamic_mesh_as_static(dyn_mesh, family: str):
    """Create a StaticMesh asset from DynamicMesh if editor helpers exist."""
    if not _HAS_UNREAL:
        return None
    _ensure_generated_dir()
    asset_path = generated_asset_path(family)
    try:
        # UE 5.x path: GeometryScript_CreateNewAssetFunctions / Editor APIs
        creators = (
            "GeometryScript_CreateNewAssetFunctions",
            "GeometryScriptCreateNewAssetFunctions",
        )
        for name in creators:
            lib = getattr(unreal, name, None)
            if lib is None:
                continue
            if hasattr(lib, "create_static_mesh_asset_from_dynamic_mesh"):
                options = None
                if hasattr(unreal, "GeometryScriptCreateNewStaticMeshAssetOptions"):
                    options = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
                result = lib.create_static_mesh_asset_from_dynamic_mesh(
                    dyn_mesh, asset_path, options)
                # result may be (mesh, success) or mesh
                if isinstance(result, (tuple, list)):
                    mesh = result[0]
                else:
                    mesh = result
                if mesh is not None:
                    unreal.log("structure_forge: saved Geometry Script mesh {}".format(asset_path))
                    return mesh
        unreal.log_warning("structure_forge: no GS create-static-mesh helper; using proxies")
        return None
    except Exception as e:
        unreal.log_warning("structure_forge: save mesh failed: {}".format(e))
        return None


def forge_mesh(family: str, force: bool = False):
    """
    Return a StaticMesh for the family, forging via Geometry Script when possible.
    Returns None if only proxy fallback should be used.
    """
    family = family if family in FAMILY_RECIPES else "hut"
    if not force:
        existing = load_forged_mesh(family)
        if existing is not None:
            return existing

    if not geometry_script_available():
        return None

    try:
        dyn = unreal.DynamicMesh()
        ok_any = False
        for part in FAMILY_RECIPES[family]:
            if _append_gs_part(dyn, part):
                ok_any = True
        if not ok_any:
            return None
        return _save_dynamic_mesh_as_static(dyn, family)
    except Exception as e:
        unreal.log_warning("structure_forge.forge_mesh failed: {}".format(e))
        return None


def proxy_recipe_for_family(family: str) -> list:
    """Convert family recipe to structure_library-style proxy parts."""
    family = family if family in FAMILY_RECIPES else "hut"
    out = []
    for part in FAMILY_RECIPES[family]:
        kind = part["kind"]
        shape = {"box": "cube", "cyl": "cylinder", "cone": "cone"}.get(kind, "cube")
        cx, cy, cz = part["center"]
        sx, sy, sz = part["size"]
        # BasicShapes unit is 100cm cube; scale = size/100
        if shape == "cylinder" or shape == "cone":
            scale = (sx / 50.0, sy / 50.0, sz / 100.0)
        else:
            scale = (sx / 100.0, sy / 100.0, sz / 100.0)
        out.append({
            "shape": shape,
            "offset": (cx, cy, cz),
            "scale": scale,
            "yaw": float(part.get("yaw", 0.0)),
        })
    return out


def _load_engine_mesh(shape: str):
    path = _PROXY_MESHES.get(shape, _PROXY_MESHES["cube"])
    try:
        return unreal.load_asset(path)
    except Exception:
        return None


def _spawn_sma(mesh, location, rotation, scale, label: str):
    if not _HAS_UNREAL or mesh is None:
        return None
    try:
        actor = None
        if hasattr(unreal, "EditorActorSubsystem"):
            actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
                unreal.StaticMeshActor, location, rotation)
        elif hasattr(unreal, "EditorLevelLibrary"):
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.StaticMeshActor, location, rotation)
        if actor is None:
            return None
        try:
            smc = actor.static_mesh_component
            smc.set_static_mesh(mesh)
            smc.set_world_scale3d(scale)
        except Exception:
            pass
        try:
            actor.set_actor_label(label)
        except Exception:
            pass
        return actor
    except Exception as e:
        unreal.log_warning("structure_forge spawn failed: {}".format(e))
        return None


def spawn_family(family: str, location, yaw: float, label_prefix: str, state: dict = None) -> list:
    """
    Spawn one structure instance for a forge family.
    Returns list of actors (single SMA if forged mesh, or many proxy parts).
    """
    family = family if family in FAMILY_RECIPES else "hut"
    actors = []
    if not _HAS_UNREAL:
        return actors

    mesh = forge_mesh(family)
    if mesh is not None:
        actor = _spawn_sma(
            mesh, location, unreal.Rotator(0.0, float(yaw), 0.0),
            unreal.Vector(1, 1, 1), label_prefix)
        if actor:
            actors.append(actor)
            if state is not None:
                state.setdefault("structure_actors", []).append(actor)
            return actors

    # Primitive fallback
    rad = math.radians(yaw)
    for i, part in enumerate(proxy_recipe_for_family(family)):
        ox, oy, oz = part["offset"]
        sx, sy, sz = part["scale"]
        rx = ox * math.cos(rad) - oy * math.sin(rad)
        ry = ox * math.sin(rad) + oy * math.cos(rad)
        loc = unreal.Vector(location.x + rx, location.y + ry, location.z + oz)
        rot = unreal.Rotator(0.0, yaw + part["yaw"], 0.0)
        scale = unreal.Vector(float(sx), float(sy), float(sz))
        mesh_part = _load_engine_mesh(part["shape"])
        actor = _spawn_sma(mesh_part, loc, rot, scale, "{}_{}".format(label_prefix, i))
        if actor:
            actors.append(actor)
            if state is not None:
                state.setdefault("structure_actors", []).append(actor)
    return actors


def preforge_all_families(force: bool = False) -> dict:
    """Editor helper: try to bake all six family meshes once."""
    results = {}
    for family in list_families():
        mesh = forge_mesh(family, force=force)
        results[family] = {
            "ok": mesh is not None,
            "path": generated_asset_path(family),
            "geometry_script": geometry_script_available(),
            "mode": "geometry_script" if mesh is not None else "proxy_fallback",
        }
    unreal.log("structure_forge preforge: {}".format(results))
    return results


def manifest_structure_entries() -> dict:
    """
    Build asset_manifest-compatible entries for the six families + aliases.
    Paths point at forged assets (may not exist until first forge/preforge).
    """
    entries = {}
    for family in list_families():
        entries[family] = {
            "asset_path": "{}/SM_WPE_{}".format(GENERATED_ROOT, family),
            "density": 0.02,
            "scale_min": 0.85,
            "scale_max": 1.25,
            "align_to_slope": False,
            "max_slope_deg": 25,
            "forge_family": family,
            "kind": "structure",
        }
    # Aliases commonly used as pcg/structure tags
    aliases = {
        "stone_keep": "keep", "castle": "keep", "watchtower": "keep",
        "ruined_tower": "ruin", "ruins": "ruin",
        "crystal_spire": "crystal", "crystal": "crystal",
        "stone_circle": "megalith", "obelisk": "megalith",
        "village_hut": "hut", "hut": "hut",
        "arch_rock": "arch", "bridge_arch": "arch",
    }
    for tag, family in aliases.items():
        entries[tag] = dict(entries[family])
        entries[tag]["forge_family"] = family
        entries[tag]["alias_of"] = family
    return entries
