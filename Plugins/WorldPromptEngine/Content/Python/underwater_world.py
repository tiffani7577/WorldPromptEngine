"""
underwater_world.py — make "underwater land" actually look underwater.

Problems this fixes:
  - Default SM_SkySphere paints orange/white sky over SkyAtmosphere
  - "underwater" prompts had weak keyword coverage → desert-looking hills
  - No seafloor tint / water plane / thick teal fog

Call apply_underwater_look() from atmosphere + generate when prompt matches.
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


UNDERWATER_PHRASES = (
    "underwater", "under water", "under-water", "submerged", "seafloor",
    "sea floor", "ocean floor", "ocean bed", "aquatic", "deep sea",
    "deepsea", "under the sea", "beneath the waves", "atlantis",
    "coral reef underwater", "sunken",
)


def prompt_wants_underwater(prompt: str) -> bool:
    t = (prompt or "").lower()
    if any(p in t for p in UNDERWATER_PHRASES):
        return True
    # token pairs
    tokens = set(t.replace("-", " ").split())
    if "under" in tokens and "water" in tokens:
        return True
    if "ocean" in tokens and ("floor" in tokens or "bed" in tokens or "bottom" in tokens):
        return True
    return False


def _all_actors():
    if not _HAS_UNREAL:
        return []
    try:
        if hasattr(unreal, "EditorActorSubsystem"):
            return list(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() or [])
    except Exception:
        pass
    return []


def hide_conflicting_sky_domes(state: dict = None) -> int:
    """
    Hide SM_SkySphere / skydome meshes that override SkyAtmosphere
    (common cause of solid orange/white band skies).
    """
    hidden = 0
    if not _HAS_UNREAL:
        return 0
    try:
        state = state if state is not None else {}
        state.setdefault("hidden_sky_domes", [])
        for a in _all_actors():
            try:
                label = ""
                try:
                    label = (a.get_actor_label() or "").lower()
                except Exception:
                    pass
                cls = a.get_class().get_name() if a.get_class() else ""
                mesh_name = ""
                try:
                    if hasattr(a, "static_mesh_component") and a.static_mesh_component:
                        sm = a.static_mesh_component.static_mesh
                        if sm:
                            mesh_name = sm.get_name().lower()
                except Exception:
                    pass
                hit = (
                    "skysphere" in label or "sky_sphere" in label or "skydome" in label
                    or "skysphere" in mesh_name or "sky_sphere" in mesh_name
                    or mesh_name == "sm_skysphere"
                )
                if hit:
                    if hasattr(a, "set_is_temporarily_hidden_in_editor"):
                        a.set_is_temporarily_hidden_in_editor(True)
                    if hasattr(a, "set_actor_hidden_in_game"):
                        a.set_actor_hidden_in_game(True)
                    # Also disable collision/render on mesh
                    try:
                        if hasattr(a, "static_mesh_component") and a.static_mesh_component:
                            a.static_mesh_component.set_visibility(False, True)
                    except Exception:
                        pass
                    state["hidden_sky_domes"].append(a)
                    hidden += 1
            except Exception:
                continue
        if hidden:
            unreal.log(
                "WorldPromptEngine: hid {} sky-dome mesh(es) so underwater/atmosphere can show".format(hidden))
    except Exception as e:
        unreal.log_warning("hide_conflicting_sky_domes failed: {}".format(e))
    return hidden


def _set_fog_underwater():
    try:
        import prompt_matrix
        fog = prompt_matrix._find_actor_of_class(("ExponentialHeightFog",))
        if fog is None:
            return False
        comp = fog.get_component_by_class(unreal.ExponentialHeightFogComponent) \
            if hasattr(unreal, "ExponentialHeightFogComponent") else None
        if comp is None:
            return False
        if hasattr(comp, "set_fog_density"):
            comp.set_fog_density(0.085)
        if hasattr(comp, "set_fog_height_falloff"):
            comp.set_fog_height_falloff(0.08)
        if hasattr(comp, "set_fog_inscattering_color") and hasattr(unreal, "LinearColor"):
            # teal / deep water
            comp.set_fog_inscattering_color(unreal.LinearColor(0.05, 0.35, 0.45, 1.0))
        try:
            if hasattr(comp, "set_editor_property"):
                comp.set_editor_property("fog_max_opacity", 0.95)
                comp.set_editor_property("directional_incoming_light_scattering_color",
                                        unreal.LinearColor(0.1, 0.55, 0.65, 1.0))
        except Exception:
            pass
        return True
    except Exception as e:
        unreal.log_warning("underwater fog failed: {}".format(e))
        return False


def _set_sun_underwater():
    try:
        import prompt_matrix
        sun = prompt_matrix._find_actor_of_class(("DirectionalLight",))
        if sun is None:
            return False
        sun.set_actor_rotation(unreal.Rotator(0.0, -55.0, 20.0), False)
        comp = sun.get_component_by_class(unreal.DirectionalLightComponent) \
            if hasattr(unreal, "DirectionalLightComponent") else None
        if comp is not None:
            if hasattr(comp, "set_intensity"):
                comp.set_intensity(2.2)
            if hasattr(comp, "set_light_color"):
                comp.set_light_color(unreal.LinearColor(0.35, 0.75, 0.9, 1.0))
        return True
    except Exception:
        return False


def _set_post_underwater():
    try:
        import prompt_matrix
        ppv = prompt_matrix._find_actor_of_class(("PostProcessVolume",))
        if ppv is None:
            return False
        try:
            ppv.set_editor_property("unbound", True)
        except Exception:
            pass
        settings = ppv.get_editor_property("settings")
        if settings is None:
            return False
        # Color grading toward teal; raise exposure slightly for murky water
        try:
            settings.set_editor_property("override_auto_exposure_bias", True)
            settings.set_editor_property("auto_exposure_bias", 0.6)
        except Exception:
            pass
        try:
            settings.set_editor_property("override_scene_color_tint", True)
            settings.set_editor_property(
                "scene_color_tint", unreal.LinearColor(0.55, 0.85, 1.0, 1.0))
        except Exception:
            pass
        try:
            settings.set_editor_property("override_vignetting_intensity", True)
            settings.set_editor_property("vignetting_intensity", 0.45)
        except Exception:
            pass
        try:
            ppv.set_editor_property("settings", settings)
        except Exception:
            pass
        return True
    except Exception as e:
        unreal.log_warning("underwater post failed: {}".format(e))
        return False


def _spawn_water_ceiling(state: dict, z: float = 2800.0) -> bool:
    """
    Big translucent plane above the camera/terrain so the scene reads as
    'below the surface' even without a full water system.
    """
    if not _HAS_UNREAL or not hasattr(unreal, "EditorActorSubsystem"):
        return False
    try:
        subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        # clear previous
        for a in list(state.get("water_planes") or []):
            try:
                subsys.destroy_actor(a)
            except Exception:
                pass
        state["water_planes"] = []

        mesh = unreal.load_asset("/Engine/BasicShapes/Plane")
        if mesh is None:
            mesh = unreal.load_asset("/Engine/BasicShapes/Plane.Plane")
        if mesh is None:
            return False

        loc = unreal.Vector(0.0, 0.0, float(z))
        actor = subsys.spawn_actor_from_class(
            unreal.StaticMeshActor, loc, unreal.Rotator(0, 0, 0))
        if actor is None:
            return False
        try:
            actor.set_actor_label("WPE_WaterSurface")
        except Exception:
            pass
        smc = actor.static_mesh_component
        smc.set_static_mesh(mesh)
        # Huge plane (uu)
        smc.set_world_scale3d(unreal.Vector(800.0, 800.0, 1.0))
        try:
            # Prefer a translucent engine material if present
            mat = unreal.load_asset("/Engine/EngineMaterials/DefaultTexturedDissolve")
            if mat is None:
                mat = unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial")
            if mat is not None:
                smc.set_material(0, mat)
        except Exception:
            pass
        # Tint via custom depth not available — scale/fog do the heavy lifting
        state["water_planes"].append(actor)
        unreal.log("WorldPromptEngine: spawned water surface plane at Z={}".format(z))
        return True
    except Exception as e:
        unreal.log_warning("water plane spawn failed: {}".format(e))
        return False


def apply_seafloor_material_colors() -> bool:
    """Rebuild landscape material with underwater sand/teal palette and assign."""
    try:
        import landscape_auto_setup
        result = landscape_auto_setup.ensure_landscape_material_stack(
            force_rebuild=True, assign=True, color_set="underwater")
        return bool(result.get("ok"))
    except Exception as e:
        unreal.log_warning("seafloor material failed: {}".format(e))
        return False


def apply_underwater_look(state: dict = None, prompt: str = "") -> dict:
    """
    Full underwater pass. Safe to call even if prompt is empty when archetype is underwater.
    """
    state = state if state is not None else {}
    summary = {"ok": False, "hid_sky": 0, "fog": False, "sun": False, "post": False, "water": False}
    if not _HAS_UNREAL:
        return summary
    try:
        import atmosphere_control
        atmosphere_control.ensure_lighting_stack(spawn_missing=True)

        # Prefer dedicated weather preset
        try:
            import prompt_matrix
            prompt_matrix.apply_weather_preset("underwater_teal")
        except Exception:
            pass

        summary["hid_sky"] = hide_conflicting_sky_domes(state)
        summary["fog"] = _set_fog_underwater()
        summary["sun"] = _set_sun_underwater()
        summary["post"] = _set_post_underwater()
        summary["water"] = _spawn_water_ceiling(state, z=3200.0)
        apply_seafloor_material_colors()

        # Pull camera under the water plane so the user *sees* underwater
        try:
            if hasattr(unreal, "UnrealEditorSubsystem"):
                unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
                    unreal.Vector(0.0, -2500.0, 900.0),
                    unreal.Rotator(0.0, -15.0, 20.0))
            elif hasattr(unreal, "EditorLevelLibrary"):
                unreal.EditorLevelLibrary.set_level_viewport_camera_info(
                    unreal.Vector(0.0, -2500.0, 900.0),
                    unreal.Rotator(0.0, -15.0, 20.0))
        except Exception:
            pass

        summary["ok"] = summary["fog"] or summary["hid_sky"] > 0 or summary["water"]
        unreal.log(
            "WorldPromptEngine: UNDERWATER look applied "
            "(hid_sky={}, fog={}, water_plane={})".format(
                summary["hid_sky"], summary["fog"], summary["water"]))
        state["last_underwater"] = summary
        return summary
    except Exception as e:
        unreal.log_error("apply_underwater_look failed: {}".format(e))
        return summary
