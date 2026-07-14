"""
wpe_create_vfx_niagara.py — Create WPE Niagara VFX systems for Performance Mode.

Creates under /Game/WorldPromptEngine/VFX/:
  NS_WPE_BioBioluminescent, NS_WPE_Mist, NS_WPE_Embers,
  NS_WPE_OceanSpray, NS_WPE_CrystalShimmer

Each exposes User.SpawnRateMultiplier (float, default 1.0) so
performance_engine.apply_live_params can drive spawn rate from OSC highs.

Preferred path: UWPENiagaraVfxLibrary (C++ NiagaraExternalEditUtilities wrapper).
Fallback: duplicate emitter templates + metadata if the C++ library is unavailable.

Run in editor Output Log:
  import wpe_create_vfx_niagara; wpe_create_vfx_niagara.run()

Or headless:
  UnrealEditor-Cmd <uproject> -ExecutePythonScript=".../wpe_create_vfx_niagara.py"
"""

from __future__ import annotations

try:
    import unreal
except ImportError:  # offline lint
    unreal = None  # type: ignore


VFX_PATH = "/Game/WorldPromptEngine/VFX"
USER_PARAM = "User.SpawnRateMultiplier"

SYSTEMS = [
    {
        "name": "NS_WPE_BioBioluminescent",
        "label": "Floating soft glowing orbs, slow drift",
        "emitter": "/Niagara/DefaultAssets/Templates/Emitters/HangingParticulates",
        "spawn_rate": 12.0,
    },
    {
        "name": "NS_WPE_Mist",
        "label": "Low ground fog wisps, atmospheric",
        "emitter": "/Niagara/DefaultAssets/Templates/Emitters/BlowingParticles",
        "spawn_rate": 20.0,
    },
    {
        "name": "NS_WPE_Embers",
        "label": "Slow rising embers/sparks",
        "emitter": "/Niagara/DefaultAssets/Templates/Emitters/Fountain",
        "spawn_rate": 30.0,
    },
    {
        "name": "NS_WPE_OceanSpray",
        "label": "Fine water mist particles",
        "emitter": "/Niagara/DefaultAssets/Templates/Emitters/Fountain",
        "spawn_rate": 45.0,
    },
    {
        "name": "NS_WPE_CrystalShimmer",
        "label": "Small light flecks, high frequency shimmer",
        "emitter": "/Niagara/DefaultAssets/Templates/Emitters/HangingParticulates",
        "spawn_rate": 80.0,
    },
]


def _log(msg: str):
    if unreal:
        unreal.log("WPE-VFX: {}".format(msg))
    else:
        print(msg)


def _warn(msg: str):
    if unreal:
        unreal.log_warning("WPE-VFX: {}".format(msg))
    else:
        print("WARN", msg)


def _ensure_folder(path: str) -> None:
    if not unreal.EditorAssetLibrary.does_directory_exist(path):
        unreal.EditorAssetLibrary.make_directory(path)
        _log("created folder {}".format(path))


def _create_via_cpp(force_recreate: bool) -> dict | None:
    """Use UWPENiagaraVfxLibrary when the editor module is loaded."""
    lib = getattr(unreal, "WPENiagaraVfxLibrary", None)
    if lib is None:
        return None
    try:
        ok = lib.create_all_wpe_vfx_systems(force_recreate)
        results = []
        for spec in SYSTEMS:
            path = "{}/{}".format(VFX_PATH, spec["name"])
            exists = unreal.EditorAssetLibrary.does_asset_exist(path)
            results.append({
                "name": spec["name"],
                "ok": exists,
                "path": path,
                "user_param": USER_PARAM,
                "label": spec["label"],
            })
        return {
            "ok": bool(ok) and all(r["ok"] for r in results),
            "created": sum(1 for r in results if r["ok"]),
            "total": len(SYSTEMS),
            "path": VFX_PATH,
            "user_param": USER_PARAM,
            "via": "WPENiagaraVfxLibrary",
            "results": results,
        }
    except Exception as e:
        _warn("WPENiagaraVfxLibrary failed: {}".format(e))
        return None


def _create_system_fallback(name: str, emitter_path: str, force: bool):
    """Best-effort asset creation without NiagaraExternalEditUtilities."""
    asset_path = "{}/{}".format(VFX_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        if force:
            unreal.EditorAssetLibrary.delete_asset(asset_path)
        else:
            return unreal.EditorAssetLibrary.load_asset(asset_path)

    # Prefer duplicating a System template, then empty factory.
    system_templates = (
        "/Niagara/DefaultAssets/Templates/Systems/FountainLightweight",
        "/Niagara/DefaultAssets/Templates/Systems/MinimalLightweight",
    )
    for tmpl in system_templates:
        if unreal.EditorAssetLibrary.does_asset_exist(tmpl):
            dup = unreal.EditorAssetLibrary.duplicate_asset(tmpl, asset_path)
            if dup:
                _log("duplicated {} -> {}".format(tmpl, asset_path))
                return unreal.EditorAssetLibrary.load_asset(asset_path)

    factory = unreal.NiagaraSystemFactoryNew()
    factory.set_editor_property("edit_after_new", False)
    system = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, VFX_PATH, unreal.NiagaraSystem, factory)
    if system is None:
        raise RuntimeError("Failed to create NiagaraSystem {}".format(name))
    _log("created empty system {} (open in Niagara to add emitter {})".format(
        asset_path, emitter_path))
    return system


def _stamp_metadata(system, spec: dict) -> None:
    try:
        unreal.EditorAssetLibrary.set_metadata_tag(system, "WPE.VFX.Label", spec["label"])
        unreal.EditorAssetLibrary.set_metadata_tag(
            system, "WPE.VFX.SpawnRate", str(spec["spawn_rate"]))
        unreal.EditorAssetLibrary.set_metadata_tag(system, "WPE.VFX.UserParam", USER_PARAM)
        unreal.EditorAssetLibrary.set_metadata_tag(
            system, "WPE.VFX.EmitterTemplate", spec["emitter"])
    except Exception as e:
        _warn("metadata stamp failed: {}".format(e))


def create_all(force_recreate: bool = False) -> dict:
    if unreal is None:
        return {"ok": False, "error": "unreal module unavailable"}

    _ensure_folder(VFX_PATH)

    cpp = _create_via_cpp(force_recreate)
    if cpp is not None:
        _log("done via C++: {}/{} at {}".format(
            cpp.get("created"), cpp.get("total"), VFX_PATH))
        return cpp

    _warn("WPENiagaraVfxLibrary unavailable — using Python fallback (User param may need Tools menu after rebuild)")
    results = []
    for spec in SYSTEMS:
        name = spec["name"]
        asset_path = "{}/{}".format(VFX_PATH, name)
        try:
            system = _create_system_fallback(name, spec["emitter"], force_recreate)
            if system is None:
                results.append({"name": name, "ok": False, "error": "create_failed"})
                continue
            # Prefer C++ ensure if available on a later hot-reload.
            lib = getattr(unreal, "WPENiagaraVfxLibrary", None)
            param_ok = False
            if lib is not None:
                try:
                    param_ok = bool(lib.ensure_spawn_rate_multiplier(
                        system, float(spec["spawn_rate"]), 1.0))
                except Exception as e:
                    _warn("ensure_spawn_rate_multiplier: {}".format(e))
            _stamp_metadata(system, spec)
            unreal.EditorAssetLibrary.save_asset(asset_path)
            results.append({
                "name": name,
                "ok": True,
                "path": asset_path,
                "user_param": USER_PARAM,
                "param_ok": param_ok,
                "label": spec["label"],
            })
        except Exception as e:
            _warn("{} failed: {}".format(name, e))
            results.append({"name": name, "ok": False, "error": str(e)})

    ok_n = sum(1 for r in results if r.get("ok"))
    summary = {
        "ok": ok_n == len(SYSTEMS),
        "created": ok_n,
        "total": len(SYSTEMS),
        "path": VFX_PATH,
        "user_param": USER_PARAM,
        "via": "python_fallback",
        "results": results,
    }
    _log("done: {}/{} systems at {}".format(ok_n, len(SYSTEMS), VFX_PATH))
    return summary


def verify() -> dict:
    out = []
    for spec in SYSTEMS:
        path = "{}/{}".format(VFX_PATH, spec["name"])
        exists = unreal.EditorAssetLibrary.does_asset_exist(path)
        param_ok = False
        if exists:
            sys = unreal.EditorAssetLibrary.load_asset(path)
            try:
                loc = unreal.Vector(0, 0, 200)
                actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                    unreal.NiagaraActor, loc)
                if actor:
                    comp = actor.get_component_by_class(unreal.NiagaraComponent)
                    if comp and sys:
                        comp.set_asset(sys)
                        comp.set_variable_float(USER_PARAM, 1.25)
                        param_ok = True
                    unreal.EditorLevelLibrary.destroy_actor(actor)
            except Exception as e:
                _warn("verify probe {}: {}".format(spec["name"], e))
        out.append({"path": path, "exists": exists, "param_settable": param_ok})
    return {"ok": all(x["exists"] for x in out), "systems": out}


def run(force_recreate: bool = False) -> dict:
    return create_all(force_recreate=force_recreate)


# UE ExecutePythonScript / `py` uses __main__; older paths used __builtin__.
if __name__ in ("__main__", "__builtin__", "builtins"):
    _summary = run(force_recreate=False)
    if unreal and not _summary.get("ok"):
        unreal.log_error("WPE-VFX: create incomplete: {}".format(_summary))
