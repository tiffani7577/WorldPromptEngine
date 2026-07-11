"""
wpe_director_bridge.py — Python access to UWPEGenerationEditorSubsystem (schema validate).

Does not generate terrain; later milestones will submit jobs that call the existing
ApplyHeightmapToLandscape path.
"""

from __future__ import annotations

import json

try:
    import unreal
except ImportError:
    unreal = None  # type: ignore


def _director():
    if unreal is None or not hasattr(unreal, "WPEGenerationEditorSubsystem"):
        return None
    return unreal.get_editor_subsystem(unreal.WPEGenerationEditorSubsystem)


def validate_director_job(job_dict) -> dict:
    """Validate a dict against the Director schema via C++."""
    sys = _director()
    if sys is None:
        return {"ok": False, "error": "WPEGenerationEditorSubsystem unavailable (rebuild editor module)"}
    text = json.dumps(job_dict)
    # UFUNCTION bool ValidateJobJson(FString, FString&) — Python may return (bool, str) or bool
    try:
        result = sys.validate_job_json(text)
        if isinstance(result, tuple):
            ok, err = result[0], (result[1] if len(result) > 1 else "")
        else:
            ok, err = bool(result), ""
        return {"ok": bool(ok), "error": err or None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def submit_director_job(job_dict) -> dict:
    sys = _director()
    if sys is None:
        return {"ok": False, "error": "WPEGenerationEditorSubsystem unavailable"}
    text = json.dumps(job_dict)
    try:
        result = sys.submit_job_json(text)
        if isinstance(result, tuple):
            ok, err = result[0], (result[1] if len(result) > 1 else "")
        else:
            ok, err = bool(result), ""
        status = None
        try:
            st = sys.get_last_status()
            status = {"phase": str(st.phase), "ok": bool(st.b_ok), "message": str(st.message), "progress": float(st.progress)}
        except Exception:
            pass
        return {"ok": bool(ok), "error": err or None, "status": status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def self_test():
    """Quick schema smoke test for the Output Log."""
    good = {
        "schema_version": 1,
        "prompt": "misty alpine peaks",
        "seed": 1337,
        "terrain": {"resolution_x": 253, "resolution_y": 253},
    }
    bad = {
        "schema_version": 1,
        "prompt": "x",
        "seed": 1,
        "terrain": {"resolution_x": 250, "resolution_y": 250},
    }
    g = submit_director_job(good)
    b = validate_director_job(bad)
    unreal.log("WPE Director self_test good={}".format(g))
    unreal.log("WPE Director self_test bad(expected fail)={}".format(b))
    return bool(g.get("ok")) and (not b.get("ok"))
