"""
world_library.py — Author-mode world save + library system (UE 5.8).

Saves the currently open level to /Game/WorldPromptEngine/Worlds/{name}
with a companion metadata JSON, and enumerates the saved library.

Kept as its own module so existing art_engine code is untouched;
art_engine's generation state feeds the metadata via init_unreal.GLOBAL_STATE.
"""

import json
import os
import re
import time

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    unreal = None
    _HAS_UNREAL = False

WORLDS_PACKAGE_ROOT = "/Game/WorldPromptEngine/Worlds"


def _log(msg):
    if _HAS_UNREAL:
        unreal.log("[WorldPromptEngine] {}".format(msg))
    else:
        print(msg)


def _log_error(msg):
    if _HAS_UNREAL:
        unreal.log_error("[WorldPromptEngine] {}".format(msg))
    else:
        print("ERROR:", msg)


def sanitize_world_name(name):
    name = re.sub(r"[^A-Za-z0-9_\- ]", "", (name or "").strip())
    name = name.replace(" ", "_")
    return name[:64] or "Untitled_World"


def _metadata_dir():
    """Filesystem dir for metadata JSON, alongside the project's Saved dir."""
    try:
        if _HAS_UNREAL and hasattr(unreal, "SystemLibrary"):
            base = unreal.SystemLibrary.get_project_saved_directory()
        else:
            base = os.path.join(os.getcwd(), "Saved")
        path = os.path.join(base, "WorldPromptEngine", "WorldMeta")
        os.makedirs(path, exist_ok=True)
        return path
    except Exception as e:
        _log_error("world_library._metadata_dir: {}".format(e))
        return os.getcwd()


def _level_editor_subsystem():
    if not _HAS_UNREAL:
        return None
    try:
        if hasattr(unreal, "LevelEditorSubsystem"):
            return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    except Exception:
        pass
    return None


def save_world(world_name, state=None):
    """Save current level as a named world asset plus metadata JSON.

    Returns True on success.
    """
    try:
        if not _HAS_UNREAL:
            _log_error("save_world requires the Unreal editor environment")
            return False
        world_name = sanitize_world_name(world_name)
        package_path = "{}/{}".format(WORLDS_PACKAGE_ROOT, world_name)

        saved = False
        les = _level_editor_subsystem()
        if les is not None and hasattr(les, "save_current_level"):
            # Save-as if the level was never saved: use save_as via console fallback
            try:
                if hasattr(les, "save_all_dirty_levels"):
                    les.save_all_dirty_levels()
                saved = bool(les.save_current_level())
            except Exception as e:
                _log_error("save_world LevelEditorSubsystem path: {}".format(e))
        if not saved and hasattr(unreal, "EditorLevelLibrary"):
            try:
                saved = bool(unreal.EditorLevelLibrary.save_current_level())
            except Exception as e:
                _log_error("save_world EditorLevelLibrary path: {}".format(e))

        # Duplicate the saved level asset into the world library path so the
        # library is a stable, named collection regardless of working level.
        try:
            editor_world = None
            if hasattr(unreal, "EditorLevelLibrary"):
                editor_world = unreal.EditorLevelLibrary.get_editor_world()
            src_path = None
            if editor_world is not None:
                src_path = editor_world.get_path_name().split(".")[0]
            if src_path and hasattr(unreal, "EditorAssetLibrary"):
                if not unreal.EditorAssetLibrary.does_directory_exist(WORLDS_PACKAGE_ROOT):
                    unreal.EditorAssetLibrary.make_directory(WORLDS_PACKAGE_ROOT)
                if src_path != package_path:
                    if unreal.EditorAssetLibrary.does_asset_exist(package_path):
                        unreal.EditorAssetLibrary.delete_asset(package_path)
                    dup = unreal.EditorAssetLibrary.duplicate_asset(src_path, package_path)
                    if dup is not None:
                        unreal.EditorAssetLibrary.save_asset(package_path)
                        saved = True
        except Exception as e:
            _log_error("save_world duplicate-to-library: {}".format(e))

        # Metadata JSON
        meta = {
            "world_name": world_name,
            "level_path": package_path,
            "creation_timestamp": time.time(),
            "creation_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_text": "",
            "terrain_type": "",
            "biome_palette": "",
            "weather_preset": "",
            "structure_types": [],
            "map_size": 0,
        }
        try:
            if state is None:
                import init_unreal
                state = getattr(init_unreal, "GLOBAL_STATE", {})
            parse = state.get("last_parse") or {}
            meta["prompt_text"] = parse.get("prompt", state.get("last_prompt", ""))
            meta["terrain_type"] = parse.get("archetype", "")
            meta["biome_palette"] = parse.get("biome", parse.get("archetype", ""))
            meta["weather_preset"] = parse.get("weather", "")
            meta["structure_types"] = list(state.get("structure_plan") or [])
            meta["map_size"] = int(parse.get("map_size", 0) or 0)
        except Exception as e:
            _log_error("save_world metadata harvest: {}".format(e))

        meta_path = os.path.join(_metadata_dir(), world_name + ".json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        _log("save_world: '{}' saved={} meta={}".format(world_name, saved, meta_path))
        return bool(saved)
    except Exception as e:
        _log_error("save_world: {}".format(e))
        return False


def load_world_library():
    """List saved worlds (metadata dicts), newest first."""
    out = []
    try:
        meta_dir = _metadata_dir()
        known_assets = set()
        if _HAS_UNREAL and hasattr(unreal, "EditorAssetLibrary"):
            try:
                if unreal.EditorAssetLibrary.does_directory_exist(WORLDS_PACKAGE_ROOT):
                    for p in unreal.EditorAssetLibrary.list_assets(WORLDS_PACKAGE_ROOT, recursive=True):
                        known_assets.add(str(p).split(".")[0])
            except Exception as e:
                _log_error("load_world_library asset scan: {}".format(e))
        for fname in os.listdir(meta_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(meta_dir, fname)) as f:
                    meta = json.load(f)
                lp = meta.get("level_path", "")
                meta["asset_exists"] = (lp in known_assets) if known_assets else True
                out.append(meta)
            except Exception as e:
                _log_error("load_world_library read {}: {}".format(fname, e))
        out.sort(key=lambda m: m.get("creation_timestamp", 0.0), reverse=True)
    except Exception as e:
        _log_error("load_world_library: {}".format(e))
    return out


def load_world(level_path):
    """Open a saved world level in the editor. Returns True on success."""
    try:
        if not _HAS_UNREAL:
            return False
        les = _level_editor_subsystem()
        if les is not None and hasattr(les, "load_level"):
            return bool(les.load_level(level_path))
        if hasattr(unreal, "EditorLevelLibrary"):
            return bool(unreal.EditorLevelLibrary.load_level(level_path))
        return False
    except Exception as e:
        _log_error("load_world({}): {}".format(level_path, e))
        return False
