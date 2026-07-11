"""
content_library.py — WorldPromptEngine per-project content root helpers (UE 5.8.0)

Makes asset setup a one-liner inside Unreal:

  import init_unreal
  init_unreal.setup_content()                      # create /Game/WPE/... buckets
  init_unreal.set_content_root("/Game/Builds/A")   # point this project at a new root

All manifest paths resolve through the active content_root so you only change
one folder per build instead of editing dozens of asset paths.
"""

from __future__ import annotations

import json
import os

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


_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "content_config.json")

DEFAULT_CONFIG = {
    "content_root": "/Game/WPE",
    "heightmap_destination": "/Game/WorldPromptEngine/Heightmaps",
    "legacy_root": "/Game/WPE",
    "auto_setup_on_boot": True,
    "buckets": ["Foliage", "Rocks", "Decals", "Props", "FX", "Materials"],
}

_CONFIG_CACHE = None


def _project_config_path() -> str:
    """Per-project override lives in the project Config/ folder (survives plugin updates)."""
    try:
        if _HAS_UNREAL and hasattr(unreal, "Paths") and hasattr(unreal.Paths, "project_config_dir"):
            return os.path.join(unreal.Paths.project_config_dir(), "WPEContent.json")
    except Exception:
        pass
    # Walk up from this file to find a .uproject (dev / offline)
    cur = _PLUGIN_DIR
    for _ in range(8):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        try:
            for name in os.listdir(parent):
                if name.endswith(".uproject"):
                    return os.path.join(parent, "Config", "WPEContent.json")
        except Exception:
            pass
        cur = parent
    return os.path.join(_PLUGIN_DIR, "WPEContent.local.json")


def load_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.isfile(_DEFAULT_CONFIG_PATH):
            with open(_DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception as e:
        unreal.log_warning("content_library: default config read failed: {}".format(e))

    try:
        project_path = _project_config_path()
        if os.path.isfile(project_path):
            with open(project_path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception as e:
        unreal.log_warning("content_library: project config read failed: {}".format(e))

    _CONFIG_CACHE = cfg
    return cfg


def save_project_config(updates: dict) -> dict:
    """Merge updates into the per-project config and persist."""
    global _CONFIG_CACHE
    cfg = load_config()
    cfg.update(updates or {})
    _CONFIG_CACHE = cfg
    path = _project_config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Only persist the keys we care about (not full DEFAULT merge noise)
        payload = {
            "content_root": cfg["content_root"],
            "heightmap_destination": cfg["heightmap_destination"],
            "legacy_root": cfg.get("legacy_root", DEFAULT_CONFIG["legacy_root"]),
            "auto_setup_on_boot": bool(cfg.get("auto_setup_on_boot", True)),
            "buckets": list(cfg.get("buckets", DEFAULT_CONFIG["buckets"])),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        unreal.log("WorldPromptEngine: saved content config -> {}".format(path))
    except Exception as e:
        unreal.log_error("content_library.save_project_config failed: {}".format(e))
    return cfg


def invalidate_cache():
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def content_root() -> str:
    return load_config().get("content_root", DEFAULT_CONFIG["content_root"]).rstrip("/")


def heightmap_destination() -> str:
    return load_config().get(
        "heightmap_destination", DEFAULT_CONFIG["heightmap_destination"]).rstrip("/")


def _normalize_game_path(path: str) -> str:
    path = (path or "").replace("\\", "/").strip()
    if not path:
        return ""
    if path.endswith("/"):
        path = path[:-1]
    return path


def resolve_asset_path(asset_path: str) -> str:
    """
    Map a manifest path onto the active content_root.

    Accepts:
      - relative:  "Foliage/SM_Pine_01"  ->  {content_root}/Foliage/SM_Pine_01
      - legacy:    "/Game/WPE/Foliage/SM_Pine_01"  ->  remapped under content_root
      - absolute other /Game/... paths: left alone (explicit overrides)
    """
    raw = _normalize_game_path(asset_path)
    if not raw:
        return ""

    root = content_root()
    legacy = _normalize_game_path(
        load_config().get("legacy_root", DEFAULT_CONFIG["legacy_root"]))

    if not raw.startswith("/"):
        return "{}/{}".format(root, raw.lstrip("/"))

    if legacy and (raw == legacy or raw.startswith(legacy + "/")):
        suffix = raw[len(legacy):].lstrip("/")
        return "{}/{}".format(root, suffix) if suffix else root

    # Already under the active root, or a fully custom absolute path
    return raw


def _manifest_paths() -> list:
    try:
        manifest_path = os.path.join(_PLUGIN_DIR, "asset_manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        paths = []
        for entry in (data.get("assets") or {}).values():
            p = entry.get("asset_path")
            if p:
                paths.append(resolve_asset_path(p))
        return paths
    except Exception as e:
        unreal.log_warning("content_library._manifest_paths failed: {}".format(e))
        return []


def _parent_dirs_for_asset(asset_path: str) -> list:
    """
    /Game/WPE/Foliage/SM_Pine_01 -> ["/Game", "/Game/WPE", "/Game/WPE/Foliage"]
    """
    path = _normalize_game_path(asset_path)
    if not path.startswith("/Game"):
        return []
    parts = [p for p in path.split("/") if p]
    # drop asset name (last segment)
    folder_parts = parts[:-1]
    dirs = []
    cur = ""
    for part in folder_parts:
        cur = "{}/{}".format(cur, part) if cur else "/{}".format(part)
        dirs.append(cur)
    return dirs


def _make_directory(path: str) -> bool:
    path = _normalize_game_path(path)
    if not path:
        return False
    if not _HAS_UNREAL:
        unreal.log("Stub: would make_directory {}".format(path))
        return True
    try:
        if hasattr(unreal, "EditorAssetLibrary"):
            if unreal.EditorAssetLibrary.does_directory_exist(path):
                return True
            ok = unreal.EditorAssetLibrary.make_directory(path)
            if ok:
                unreal.log("WorldPromptEngine: created folder {}".format(path))
            return bool(ok)
        unreal.log_warning("WorldPromptEngine: EditorAssetLibrary unavailable; cannot create {}".format(path))
        return False
    except Exception as e:
        unreal.log_error("content_library._make_directory({}) failed: {}".format(path, e))
        return False


def setup_content(root: str = None, also_heightmaps: bool = True) -> dict:
    """
    Create the content-root bucket folders (+ any parent folders implied by the
    asset manifest) so you can drop meshes into a known place per build.

    Returns a summary dict for the console / WebSocket ack.
    """
    try:
        if root:
            save_project_config({"content_root": _normalize_game_path(root)})
        else:
            load_config()

        root = content_root()
        created = []
        existed = []
        buckets = list(load_config().get("buckets") or DEFAULT_CONFIG["buckets"])

        # Root + standard buckets
        targets = [root] + ["{}/{}".format(root, b) for b in buckets]
        if also_heightmaps:
            targets.append(heightmap_destination())

        # Parents implied by remapped manifest asset paths
        for asset_path in _manifest_paths():
            targets.extend(_parent_dirs_for_asset(asset_path))

        # Stable unique order
        seen = set()
        ordered = []
        for t in targets:
            t = _normalize_game_path(t)
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)

        for path in ordered:
            if _HAS_UNREAL and hasattr(unreal, "EditorAssetLibrary") and \
                    unreal.EditorAssetLibrary.does_directory_exist(path):
                existed.append(path)
            elif _make_directory(path):
                created.append(path)
            else:
                # still record attempt
                pass

        summary = {
            "ok": True,
            "content_root": root,
            "heightmap_destination": heightmap_destination(),
            "created": created,
            "already_existed": existed,
            "drop_meshes_in": ["{}/{}".format(root, b) for b in buckets],
            "hint": "Drop static meshes into the folders above (names can match asset_manifest.json), "
                    "or call init_unreal.set_content_root('/Game/YourBuild') for a new build folder.",
        }
        unreal.log(
            "WorldPromptEngine: content ready at {} (created {}, existed {})".format(
                root, len(created), len(existed)))
        return summary
    except Exception as e:
        unreal.log_error("content_library.setup_content failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def set_content_root(root: str, setup: bool = True) -> dict:
    """Point this project/build at a new /Game/... folder and optionally scaffold it."""
    root = _normalize_game_path(root)
    if not root.startswith("/Game"):
        return {"ok": False, "error": "content_root must be a /Game/... path"}
    save_project_config({"content_root": root})
    if setup:
        return setup_content(root=None)
    return {"ok": True, "content_root": root}


def _list_content_directories(search_root: str = "/Game") -> list:
    """Return /Game/... directory paths under search_root (best-effort)."""
    search_root = _normalize_game_path(search_root) or "/Game"
    found = set()
    if not _HAS_UNREAL or not hasattr(unreal, "EditorAssetLibrary"):
        return []
    try:
        # include_folder=True yields directory paths alongside assets
        entries = unreal.EditorAssetLibrary.list_assets(
            search_root, recursive=True, include_folder=True) or []
        for entry in entries:
            path = _normalize_game_path(str(entry))
            if not path.startswith("/Game"):
                continue
            # Folder entries often look like /Game/Foo or /Game/Foo/
            # Asset entries look like /Game/Foo/Asset.Asset — keep only folders.
            if "." in path.split("/")[-1]:
                # parent folder of an asset
                parent = "/".join(path.split("/")[:-1])
                if parent.startswith("/Game"):
                    found.add(parent)
            else:
                found.add(path)
        # Always include the search root itself if it exists
        if unreal.EditorAssetLibrary.does_directory_exist(search_root):
            found.add(search_root)
    except Exception as e:
        unreal.log_warning("content_library._list_content_directories failed: {}".format(e))
    return sorted(found)


def find_folder(name: str, where: str = None) -> dict:
    """
    Find a Content Browser folder by name.

      find_folder("Forest_01")
      find_folder("Forest_01", where="/Game/Builds")
      find_folder("/Game/Builds/Forest_01")
    """
    name = (name or "").strip().replace("\\", "/")
    where = _normalize_game_path(where) if where else None

    if not name:
        return {"ok": False, "error": "folder name is required", "matches": []}

    # Full path given
    if name.startswith("/Game"):
        exists = True
        if _HAS_UNREAL and hasattr(unreal, "EditorAssetLibrary"):
            exists = unreal.EditorAssetLibrary.does_directory_exist(name)
        return {
            "ok": exists,
            "path": _normalize_game_path(name),
            "matches": [_normalize_game_path(name)] if exists else [],
            "error": None if exists else "folder not found: {}".format(name),
        }

    folder_name = name.strip("/")
    # where may be "Builds" or "/Game/Builds"
    search_root = "/Game"
    if where:
        if where.startswith("/Game"):
            search_root = where
        else:
            search_root = "/Game/{}".format(where.strip("/"))

    # Fast path: exact join
    direct = "{}/{}".format(search_root.rstrip("/"), folder_name)
    if _HAS_UNREAL and hasattr(unreal, "EditorAssetLibrary"):
        if unreal.EditorAssetLibrary.does_directory_exist(direct):
            return {"ok": True, "path": direct, "matches": [direct], "error": None}
    elif not _HAS_UNREAL:
        # stub: assume direct path
        return {"ok": True, "path": direct, "matches": [direct], "error": None}

    # Search by leaf folder name (case-insensitive)
    matches = []
    needle = folder_name.lower()
    for path in _list_content_directories(search_root):
        leaf = path.rstrip("/").split("/")[-1]
        if leaf.lower() == needle:
            matches.append(path)

    # de-dupe preserve order
    seen = set()
    uniq = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            uniq.append(m)

    if not uniq:
        return {
            "ok": False,
            "path": None,
            "matches": [],
            "error": "no folder named '{}' under {}".format(folder_name, search_root),
            "searched": search_root,
        }
    return {
        "ok": True,
        "path": uniq[0],
        "matches": uniq,
        "error": None if len(uniq) == 1 else "multiple matches; using first. Pass where= to be specific.",
        "searched": search_root,
    }


def use_folder(name: str, where: str = None, create_if_missing: bool = True,
               setup: bool = True) -> dict:
    """
    Tell WorldPromptEngine which Content folder to use for this build.

    You only need the folder name + optional location:

      use_folder("Forest_01")
      use_folder("Forest_01", where="/Game/Builds")
      use_folder("Forest_01", where="Builds")
      use_folder("/Game/Builds/Forest_01")

    If it exists, we lock content_root to it.
    If it doesn't and create_if_missing=True, we create it (under where or /Game).
    """
    try:
        found = find_folder(name, where=where)
        path = found.get("path")

        if not found.get("ok") or not path:
            # Create it where the user said (or /Game/<name>)
            folder_name = name.strip("/").split("/")[-1] if name else ""
            if not folder_name:
                return {"ok": False, "error": "folder name is required"}
            if where:
                w = _normalize_game_path(where) if str(where).startswith("/") else \
                    "/Game/{}".format(str(where).strip("/"))
                if not w.startswith("/Game"):
                    w = "/Game/{}".format(str(where).strip("/"))
                path = "{}/{}".format(w.rstrip("/"), folder_name)
            elif name.startswith("/Game"):
                path = _normalize_game_path(name)
            else:
                path = "/Game/{}".format(folder_name)

            if not create_if_missing:
                return {
                    "ok": False,
                    "error": found.get("error") or "folder not found",
                    "matches": found.get("matches") or [],
                }

            # Ensure parents + folder exist
            for parent in _parent_dirs_for_asset(path + "/_"):
                _make_directory(parent)
            _make_directory(path)
            unreal.log("WorldPromptEngine: created content folder {}".format(path))
            created = True
        else:
            created = False
            if len(found.get("matches") or []) > 1:
                unreal.log_warning(
                    "WorldPromptEngine: multiple folders named '{}': {}. Using {}".format(
                        name, found["matches"], path))

        result = set_content_root(path, setup=setup)
        result["folder_name"] = path.rstrip("/").split("/")[-1]
        result["where"] = "/".join(path.rstrip("/").split("/")[:-1]) or "/Game"
        result["created_folder"] = created
        result["matches"] = found.get("matches") or [path]
        result["hint"] = (
            "Using {}. Drop meshes into Foliage/Rocks/etc inside it, then "
            "init_unreal.prompt('...')".format(path)
        )
        unreal.log("WorldPromptEngine: now using folder {} (where={})".format(
            result["folder_name"], result["where"]))
        return result
    except Exception as e:
        unreal.log_error("content_library.use_folder failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def content_status() -> dict:
    cfg = load_config()
    root = content_root()
    missing = []
    present = []
    try:
        import prompt_matrix
        # avoid circular issues: only use load_manifest if available
        manifest = None
        try:
            manifest = prompt_matrix.load_manifest()
        except Exception:
            manifest = None
        assets = (manifest or {}).get("assets", {})
        for tag, entry in assets.items():
            path = resolve_asset_path(entry.get("asset_path", ""))
            exists = False
            if _HAS_UNREAL and hasattr(unreal, "EditorAssetLibrary") and path:
                # Soft check: directory of asset or asset itself
                exists = unreal.EditorAssetLibrary.does_asset_exist(path) or \
                    unreal.EditorAssetLibrary.does_asset_exist(path + "." + path.split("/")[-1])
            (present if exists else missing).append({"tag": tag, "asset_path": path})
    except Exception as e:
        unreal.log_warning("content_library.content_status scan failed: {}".format(e))

    return {
        "content_root": root,
        "heightmap_destination": heightmap_destination(),
        "config_file": _project_config_path(),
        "assets_found": len(present),
        "assets_missing": len(missing),
        "missing_sample": missing[:12],
        "auto_setup_on_boot": bool(cfg.get("auto_setup_on_boot", True)),
    }
