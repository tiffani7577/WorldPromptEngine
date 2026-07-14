"""
engine_commands.py — command dispatch helpers for WorldPromptEngine.

Keeps art_engine.execute_command lean by owning feature-level command handlers
(atmosphere, biomes status, spline/HISM toggles). art_engine still owns the
frame-budgeted heightmap generator.
"""

from __future__ import annotations

try:
    import unreal
except ImportError:
    class unreal:  # type: ignore
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)


def apply_atmosphere(state: dict, payload: dict) -> dict:
    try:
        import atmosphere_control
        prompt = payload.get("prompt") or ""
        preset = payload.get("preset")
        summary = atmosphere_control.apply_from_prompt(prompt, preset_name=preset)
        state["last_atmosphere"] = summary
        return summary
    except Exception as e:
        unreal.log_error("engine_commands.apply_atmosphere failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def biome_status(state: dict) -> dict:
    return {
        "biomes": (state.get("biome_regions") or {}).get("biome_names") or [],
        "summary": state.get("biome_mask_summary") or {},
        "routes": {
            "rivers": len((state.get("last_routes") or {}).get("rivers") or []),
            "trails": len((state.get("last_routes") or {}).get("trails") or []),
        },
        "atmosphere": state.get("last_atmosphere"),
        "kit": state.get("last_kit_summary"),
    }


def handle_extended_command(state: dict, action: str, payload: dict) -> bool:
    """
    Returns True if the action was handled here.
    """
    try:
        if action == "apply_atmosphere":
            apply_atmosphere(state, payload)
            return True
        if action == "biome_status":
            state["last_biome_status"] = biome_status(state)
            unreal.log("WorldPromptEngine: biome_status -> {}".format(state["last_biome_status"]))
            return True
        if action == "ensure_lighting":
            import atmosphere_control
            state["lighting_stack"] = atmosphere_control.ensure_lighting_stack(True)
            return True
        if action == "setup_landscape_material":
            import landscape_auto_setup
            force = bool(payload.get("force") or (payload.get("params") or {}).get("force"))
            state["last_landscape_auto"] = landscape_auto_setup.ensure_landscape_material_stack(
                force_rebuild=force, assign=True)
            unreal.log("WorldPromptEngine: setup_landscape_material -> {}".format(
                state["last_landscape_auto"]))
            return True
        return False
    except Exception as e:
        unreal.log_error("engine_commands.handle_extended_command failed: {}".format(e))
        return False
