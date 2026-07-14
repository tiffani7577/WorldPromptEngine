"""
kit_library.py — Pick Fab/Content assets → plugin makes a kit folder and arranges them.

Dummy-simple flow:
  1. In Content Browser, multi-select your Fab meshes
  2. Tools → World Prompt Engine → Capture Selected As Kit
     (or WorldPromptBuilder → capture_selected_as_kit)
  3. Plugin creates /Game/WPE/Kits/<KitName>/...
  4. generate_world places/arranges those meshes from the kit

MAIN THREAD ONLY.
"""

from __future__ import annotations

import json
import os
import re
import time

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


KITS_ROOT = "/Game/WPE/Kits"
_BUCKETS = ("Foliage", "Rocks", "Props", "Structures", "Decals")

_FOLIAGE_HINTS = (
    "tree", "pine", "oak", "palm", "spruce", "birch", "bush", "shrub",
    "grass", "fern", "flower", "weed", "plant", "foliage", "ivy", "vine",
    "moss", "cactus", "bamboo", "heather",
)
_ROCK_HINTS = (
    "rock", "stone", "boulder", "cliff", "pebble", "rubble", "marble",
    "granite", "basalt", "crystal",
)
_STRUCTURE_HINTS = (
    "column", "pillar", "temple", "ruin", "tower", "wall", "arch", "gate",
    "castle", "keep", "house", "hut", "barn", "bridge", "statue", "obelisk",
    "agora", "roman", "greek", "building", "door", "window", "roof",
)


def _normalize(path: str) -> str:
    path = (path or "").replace("\\", "/").strip()
    return path[:-1] if path.endswith("/") else path


def _classify(asset_name: str, asset_path: str) -> str:
    blob = "{} {}".format(asset_name, asset_path).lower()
    for h in _FOLIAGE_HINTS:
        if h in blob:
            return "Foliage"
    for h in _STRUCTURE_HINTS:
        if h in blob:
            return "Structures"
    for h in _ROCK_HINTS:
        if h in blob:
            return "Rocks"
    if "decal" in blob:
        return "Decals"
    return "Props"


def _safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_\-]+", "_", (name or "").strip())
    return name[:48] or "Kit_{}".format(int(time.time()) % 100000)


def _make_dir(path: str) -> bool:
    path = _normalize(path)
    if not _HAS_UNREAL:
        return True
    try:
        if unreal.EditorAssetLibrary.does_directory_exist(path):
            return True
        return bool(unreal.EditorAssetLibrary.make_directory(path))
    except Exception as e:
        unreal.log_warning("kit_library mkdir {} failed: {}".format(path, e))
        return False


def _selected_static_meshes() -> list:
    """Return list of {name, path, object_path} for selected StaticMesh assets."""
    out = []
    if not _HAS_UNREAL:
        return out
    try:
        assets = []
        if hasattr(unreal, "EditorUtilityLibrary"):
            assets = list(unreal.EditorUtilityLibrary.get_selected_assets() or [])
        for asset in assets:
            try:
                cls_name = asset.get_class().get_name() if hasattr(asset, "get_class") else ""
                # Soft object path
                path_name = asset.get_path_name()
                # /Game/Foo/SM_Bar.SM_Bar
                package = path_name.split(".", 1)[0]
                name = path_name.split(".")[-1] if "." in path_name else package.split("/")[-1]
                if "StaticMesh" not in cls_name and not hasattr(asset, "get_bounding_box"):
                    # still allow if path looks like a mesh asset user selected
                    if "SM_" not in name and "StaticMesh" not in cls_name:
                        # skip materials/textures
                        if any(x in cls_name for x in ("Texture", "Material", "MaterialInstance")):
                            continue
                if any(x in cls_name for x in ("Texture", "Material", "MaterialInstance", "Sound")):
                    continue
                if "StaticMesh" not in cls_name:
                    # Only keep StaticMesh for placement kit
                    continue
                out.append({
                    "name": name,
                    "package": package,
                    "object_path": path_name,
                })
            except Exception:
                continue
    except Exception as e:
        unreal.log_error("kit_library._selected_static_meshes failed: {}".format(e))
    return out


def _duplicate_into(package_path: str, dest_dir: str, new_name: str) -> str:
    """
    Duplicate asset into dest_dir/new_name. Returns new package path or "".
    """
    if not _HAS_UNREAL:
        return ""
    try:
        dest = "{}/{}".format(_normalize(dest_dir), new_name)
        if unreal.EditorAssetLibrary.does_asset_exist(dest):
            return dest
        ok = unreal.EditorAssetLibrary.duplicate_asset(package_path, dest)
        if ok:
            return dest
        # some builds return the asset
        if ok is not False and ok is not None:
            return dest
        return ""
    except Exception as e:
        unreal.log_warning("kit_library duplicate {} -> {} failed: {}".format(
            package_path, new_name, e))
        return ""


def capture_selected_as_kit(kit_name: str = None, where: str = None) -> dict:
    """
    Take Content Browser selection → create a new kit folder → copy meshes in
    → set that folder as the active content root for generation.
    """
    try:
        import content_library

        meshes = _selected_static_meshes()
        if not meshes:
            msg = (
                "No StaticMesh assets selected. In Content Browser, select your "
                "Fab meshes (trees/rocks/columns/etc.), then run Capture Selected As Kit."
            )
            unreal.log_error("WorldPromptEngine: {}".format(msg))
            return {"ok": False, "error": msg}

        kit_name = _safe_name(kit_name or "FabKit_{}".format(int(time.time()) % 100000))
        root_parent = _normalize(where) if where else KITS_ROOT
        if not root_parent.startswith("/Game"):
            root_parent = "{}/{}".format(KITS_ROOT, root_parent.strip("/"))
        kit_root = "{}/{}".format(_normalize(root_parent), kit_name)

        # Create folder tree
        for p in [KITS_ROOT, root_parent, kit_root] + [
                "{}/{}".format(kit_root, b) for b in _BUCKETS]:
            _make_dir(p)

        placed = []
        by_bucket = {b: [] for b in _BUCKETS}
        for i, item in enumerate(meshes):
            bucket = _classify(item["name"], item["package"])
            dest_dir = "{}/{}".format(kit_root, bucket)
            new_name = item["name"]
            # avoid collisions
            dest_pkg = "{}/{}".format(dest_dir, new_name)
            if _HAS_UNREAL and unreal.EditorAssetLibrary.does_asset_exist(dest_pkg):
                new_name = "{}_{}".format(item["name"], i)
            new_pkg = _duplicate_into(item["package"], dest_dir, new_name)
            if not new_pkg:
                # fall back to referencing original path (still usable)
                new_pkg = item["package"]
                unreal.log_warning(
                    "kit_library: using original path (no duplicate): {}".format(new_pkg))
            entry = {
                "tag": new_name.lower(),
                "name": new_name,
                "bucket": bucket,
                "asset_path": new_pkg,
                "source_path": item["package"],
                "density": 0.35 if bucket == "Foliage" else (0.08 if bucket == "Structures" else 0.15),
                "scale_min": 0.8,
                "scale_max": 1.4,
                "align_to_slope": bucket in ("Foliage", "Rocks", "Decals"),
                "max_slope_deg": 35.0 if bucket != "Structures" else 22.0,
            }
            placed.append(entry)
            by_bucket[bucket].append(entry)

        manifest = {
            "version": "1.0",
            "kit_name": kit_name,
            "kit_root": kit_root,
            "created_unix": int(time.time()),
            "count": len(placed),
            "buckets": {b: len(by_bucket[b]) for b in _BUCKETS},
            "assets": placed,
        }

        # Save kit_manifest next to plugin python for runtime + optional project file
        try:
            plugin_py = os.path.dirname(os.path.abspath(__file__))
            local_path = os.path.join(plugin_py, "active_kit.json")
            with open(local_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
                f.write("\n")
        except Exception as e:
            unreal.log_warning("kit_library: could not write active_kit.json: {}".format(e))

        # Point content root at kit
        content_library.set_content_root(kit_root, setup=True)

        summary = {
            "ok": True,
            "kit_name": kit_name,
            "kit_root": kit_root,
            "captured": len(placed),
            "buckets": manifest["buckets"],
            "hint": (
                "Kit ready. Click Create World Now — the plugin will arrange these "
                "meshes. You pick; it places."
            ),
        }
        unreal.log(
            "WorldPromptEngine: kit '{}' created at {} ({} meshes: {})".format(
                kit_name, kit_root, len(placed), manifest["buckets"]))
        return summary
    except Exception as e:
        unreal.log_error("kit_library.capture_selected_as_kit failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def load_active_kit() -> dict:
    try:
        plugin_py = os.path.dirname(os.path.abspath(__file__))
        local_path = os.path.join(plugin_py, "active_kit.json")
        if os.path.isfile(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        unreal.log_warning("kit_library.load_active_kit failed: {}".format(e))
    return {}


def kit_assets(bucket: str = None) -> list:
    data = load_active_kit()
    assets = data.get("assets") or []
    if bucket:
        return [a for a in assets if a.get("bucket") == bucket]
    return assets


def arrange_kit_in_level(state: dict, pixels, width: int, height: int, params: dict = None) -> dict:
    """
    Scatter the active kit's StaticMeshes across the heightmap.
    Foliage/Rocks/Props use HISM batches; Structures stay as unique actors.
    """
    params = params or {}
    summary = {"ok": True, "placed": 0, "by_bucket": {}, "hism_instances": 0, "mode": "hism"}
    if not params.get("spawn_kit", True):
        summary["skipped"] = True
        return summary

    assets = kit_assets()
    if not assets:
        summary["ok"] = True
        summary["hint"] = "No active kit. Select Fab meshes → Capture Selected As Kit first."
        unreal.log_warning("WorldPromptEngine: {}".format(summary["hint"]))
        return summary

    if not _HAS_UNREAL:
        return summary

    try:
        import random
        import hism_foliage
        import biome_regions

        rng = random.Random(int(params.get("seed", 1337)) ^ 0x5150)
        xy_scale = float(params.get("xy_scale", 100.0))
        origin_x = float(params.get("origin_x", -width * xy_scale * 0.5))
        origin_y = float(params.get("origin_y", -height * xy_scale * 0.5))
        density_scale = float(params.get("kit_density", 1.0))
        use_hism = bool(params.get("use_hism", True))
        # HISM can hold far more instances safely
        max_total = int(params.get("max_kit_actors", 800 if use_hism else 120))

        state.setdefault("kit_actors", [])
        try:
            if hasattr(unreal, "EditorActorSubsystem"):
                subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                for a in list(state.get("kit_actors") or []):
                    try:
                        subsys.destroy_actor(a)
                    except Exception:
                        pass
            state["kit_actors"] = []
        except Exception:
            pass
        hism_foliage.clear_hism(state)

        placed = 0
        by_bucket = {}
        hism_total = 0
        moisture = float(params.get("moisture", state.get("moisture", 0.5)))
        density_scale *= 0.55 + moisture * 0.9
        slopes = None
        wm = state.get("last_weightmaps") or {}
        if wm.get("slopes"):
            slopes = wm["slopes"]
        cluster = bool(params.get("cluster_foliage", True))
        regions = state.get("biome_regions") or {}

        def height01(px, py):
            x = max(0, min(width - 1, int(px)))
            y = max(0, min(height - 1, int(py)))
            return pixels[y * width + x] / 65535.0

        def slope_at(px, py):
            if not slopes:
                return 0.0
            x = max(0, min(width - 1, int(px)))
            y = max(0, min(height - 1, int(py)))
            return float(slopes[y * width + x])

        def biome_ok(px, py, bucket):
            if not regions or not regions.get("biome_names"):
                return True
            b = biome_regions.biome_at_pixel(regions, int(px), int(py), width)
            style = biome_regions.BIOME_STYLE.get(b) or {}
            foliage = style.get("foliage", "")
            # arid biomes: fewer foliage, more rocks
            if bucket == "Foliage" and foliage in ("arid", "dead", "sparse"):
                return rng.random() < 0.35
            if bucket == "Foliage" and foliage in ("dense", "wet"):
                return True
            if bucket == "Rocks" and foliage == "arid":
                return True
            return True

        for entry in assets:
            if placed >= max_total:
                break
            bucket = entry.get("bucket", "Props")
            path = entry.get("asset_path") or ""
            mesh = None
            try:
                mesh = unreal.load_asset(path)
                if mesh is None:
                    leaf = path.split("/")[-1]
                    mesh = unreal.load_asset("{}.{}".format(path, leaf))
            except Exception:
                mesh = None
            if mesh is None:
                unreal.log_warning("kit_library: missing mesh {}".format(path))
                continue

            base = float(entry.get("density", 0.1))
            count = max(1, int(round(base * 8.0 * density_scale)))
            if bucket == "Structures":
                count = max(1, min(count, 4))
            if bucket == "Foliage":
                count = max(2, min(count, 120 if use_hism else (28 if cluster else 20)))
            if bucket == "Rocks":
                count = max(1, min(count, 60 if use_hism else 12))
            count = min(count, max_total - placed)

            max_slope = float(entry.get("max_slope_deg", 35.0 if bucket != "Structures" else 22.0))
            spot_queue = []
            if cluster and bucket == "Foliage" and slopes is not None:
                try:
                    import pcg_ecosystem
                    spot_queue = pcg_ecosystem.cluster_points(
                        width, height, pixels, slopes, count, rng,
                        max_slope=min(max_slope, 28.0), prefer_valleys=True)
                except Exception:
                    spot_queue = []

            transforms = []  # for HISM
            for i in range(count):
                if placed + len(transforms) >= max_total:
                    break
                ok_spot = False
                wx = wy = wz = 0.0
                px = py = 0.0
                if i < len(spot_queue):
                    px, py = spot_queue[i]
                    h01 = height01(px, py)
                    if slope_at(px, py) <= max_slope and 0.12 <= h01 <= 0.78 and biome_ok(px, py, bucket):
                        wx = origin_x + px * xy_scale
                        wy = origin_y + py * xy_scale
                        wz = h01 * 1000.0
                        ok_spot = True
                if not ok_spot:
                    for _try in range(25):
                        px = rng.uniform(2, width - 3)
                        py = rng.uniform(2, height - 3)
                        h01 = height01(px, py)
                        if slope_at(px, py) > max_slope:
                            continue
                        if not biome_ok(px, py, bucket):
                            continue
                        if bucket == "Foliage" and not (0.15 <= h01 <= 0.75):
                            continue
                        if bucket == "Structures" and not (0.2 <= h01 <= 0.7):
                            continue
                        if bucket == "Rocks" and h01 < 0.1:
                            continue
                        wx = origin_x + px * xy_scale
                        wy = origin_y + py * xy_scale
                        wz = h01 * 1000.0
                        ok_spot = True
                        break
                if not ok_spot:
                    continue

                yaw = rng.uniform(0, 360)
                smin = float(entry.get("scale_min", 0.8))
                smax = float(entry.get("scale_max", 1.4))
                s = rng.uniform(smin, smax)
                loc = unreal.Vector(float(wx), float(wy), float(wz))

                # Unique actors for structures; HISM for dense buckets
                if bucket == "Structures" or not use_hism:
                    try:
                        actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
                            unreal.StaticMeshActor, loc, unreal.Rotator(0.0, yaw, 0.0))
                        if actor is not None:
                            smc = actor.static_mesh_component
                            smc.set_static_mesh(mesh)
                            smc.set_world_scale3d(unreal.Vector(s, s, s))
                            try:
                                actor.set_actor_label("WPEKit_{}_{}".format(entry.get("name", "mesh"), i))
                            except Exception:
                                pass
                            state["kit_actors"].append(actor)
                            placed += 1
                            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
                    except Exception as e:
                        unreal.log_warning("kit_library place failed: {}".format(e))
                else:
                    transforms.append((loc, yaw, s))

            if transforms and use_hism:
                batch = hism_foliage.scatter_hism_batch(
                    state, mesh, transforms,
                    "WPE_HISM_{}_{}".format(bucket, entry.get("name", "mesh")))
                if batch.get("ok"):
                    n = int(batch.get("instances", 0))
                    placed += n
                    hism_total += n
                    by_bucket[bucket] = by_bucket.get(bucket, 0) + n
                elif batch.get("mode") == "fallback_actors":
                    # emergency: one actor each (capped)
                    for j, (loc, yaw, s) in enumerate(transforms[:12]):
                        try:
                            actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
                                unreal.StaticMeshActor, loc, unreal.Rotator(0.0, yaw, 0.0))
                            if actor is not None:
                                actor.static_mesh_component.set_static_mesh(mesh)
                                actor.static_mesh_component.set_world_scale3d(unreal.Vector(s, s, s))
                                state["kit_actors"].append(actor)
                                placed += 1
                                by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
                        except Exception:
                            pass

        summary["placed"] = placed
        summary["by_bucket"] = by_bucket
        summary["hism_instances"] = hism_total
        summary["kit_root"] = (load_active_kit() or {}).get("kit_root")
        unreal.log(
            "WorldPromptEngine: kit arrange placed={} hism={} buckets={}".format(
                placed, hism_total, by_bucket))
        return summary
    except Exception as e:
        unreal.log_error("kit_library.arrange_kit_in_level failed: {}".format(e))
        return {"ok": False, "error": str(e), "placed": 0}
