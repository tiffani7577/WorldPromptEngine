"""
atmosphere_control.py — prompt → DirectionalLight / fog / sky / post-process.

Wraps and extends prompt_matrix weather presets: ensures actors exist when possible,
re-applies from prompt text, and exposes a single entry for the generate pipeline.
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


def _spawn_if_missing(class_name: str, label: str):
    if not _HAS_UNREAL or not hasattr(unreal, "EditorActorSubsystem"):
        return None
    try:
        import prompt_matrix
        existing = prompt_matrix._find_actor_of_class((class_name,))
        if existing is not None:
            return existing
        cls = getattr(unreal, class_name, None)
        if cls is None:
            return None
        subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actor = subsys.spawn_actor_from_class(
            cls, unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0))
        if actor is not None:
            try:
                actor.set_actor_label(label)
            except Exception:
                pass
            unreal.log("WorldPromptEngine: spawned missing {}".format(class_name))
        return actor
    except Exception as e:
        unreal.log_warning("atmosphere spawn {} failed: {}".format(class_name, e))
        return None


def ensure_lighting_stack(spawn_missing: bool = True) -> dict:
    found = {}
    try:
        import prompt_matrix
        for cls, label in (
            ("DirectionalLight", "WPE_Sun"),
            ("ExponentialHeightFog", "WPE_HeightFog"),
            ("SkyAtmosphere", "WPE_SkyAtmosphere"),
            ("PostProcessVolume", "WPE_PostProcess"),
        ):
            a = prompt_matrix._find_actor_of_class((cls,))
            if a is None and spawn_missing:
                a = _spawn_if_missing(cls, label)
            found[cls] = a is not None
        # unbound post-process so it affects whole level
        try:
            ppv = prompt_matrix._find_actor_of_class(("PostProcessVolume",))
            if ppv is not None and hasattr(ppv, "set_editor_property"):
                ppv.set_editor_property("unbound", True)
        except Exception:
            pass
    except Exception as e:
        unreal.log_warning("ensure_lighting_stack failed: {}".format(e))
    return found


def apply_from_prompt(prompt: str, preset_name: str = None) -> dict:
    """
    Parse weather from prompt (or use preset_name) and apply to the level.
    """
    summary = {"ok": False, "preset": None, "stack": {}, "underwater": None}
    try:
        import prompt_matrix
        t = (prompt or "").lower()
        wants_uw = False
        try:
            import underwater_world
            wants_uw = underwater_world.prompt_wants_underwater(prompt or "")
        except Exception:
            wants_uw = ("underwater" in t) or ("under water" in t)

        if wants_uw:
            preset_name = "underwater_teal"
        elif not preset_name:
            parsed = prompt_matrix.parse_prompt(prompt or "")
            preset_name = parsed.get("weather") or "clear_noon"

        summary["preset"] = preset_name
        summary["stack"] = ensure_lighting_stack(spawn_missing=True)

        # Always hide SM_SkySphere / skydomes so atmosphere/fog can show
        try:
            import underwater_world
            import init_unreal
            summary["hid_sky"] = underwater_world.hide_conflicting_sky_domes(
                init_unreal.GLOBAL_STATE)
        except Exception:
            summary["hid_sky"] = 0

        ok = prompt_matrix.apply_weather_preset(preset_name)
        summary["ok"] = bool(ok)

        sun = prompt_matrix._find_actor_of_class(("DirectionalLight",))
        if sun is not None and any(k in t for k in ("golden hour", "sunset", "sunrise", "dusk")) and not wants_uw:
            try:
                sun.set_actor_rotation(unreal.Rotator(0.0, -12.0 if "sunrise" in t else -8.0, 35.0), False)
            except Exception:
                pass
        if sun is not None and any(k in t for k in ("night", "midnight", "moonlit", "nocturnal")) and not wants_uw:
            try:
                sun.set_actor_rotation(unreal.Rotator(0.0, -85.0, 20.0), False)
                comp = sun.get_component_by_class(unreal.DirectionalLightComponent) \
                    if hasattr(unreal, "DirectionalLightComponent") else None
                if comp is not None and hasattr(comp, "set_intensity"):
                    comp.set_intensity(0.35)
            except Exception:
                pass

        if wants_uw:
            try:
                import underwater_world
                import init_unreal
                summary["underwater"] = underwater_world.apply_underwater_look(
                    init_unreal.GLOBAL_STATE, prompt or "")
                summary["ok"] = True
            except Exception as uw_e:
                unreal.log_warning("underwater apply failed: {}".format(uw_e))

        unreal.log("WorldPromptEngine: atmosphere '{}' ok={}".format(preset_name, summary["ok"]))
        return summary
    except Exception as e:
        unreal.log_error("atmosphere_control.apply_from_prompt failed: {}".format(e))
        return summary
