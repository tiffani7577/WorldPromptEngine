"""
world_builder_actor.py — Beginner-friendly drop-in builder (UE 5.8)

Designed for people who have never used Unreal:
  Tools → World Prompt Engine → Place Builder In Level
  Select the glowing WorldPromptBuilder in the level
  Details panel shows numbered steps (not snake_case jargon)
"""

from __future__ import annotations

import unreal


_HOW_TO = (
    "TONIGHT DEMO — fastest path:\n"
    "Click DEMO: Alpine Sunset / Underwater / Desert Blood Moon.\n"
    "Watch the viewport — a new WPE_Terrain mesh should appear.\n"
    "\n"
    "Or: type a world in \"Describe Your World\" → Create World Now.\n"
    "Optional: Open Easy Panel for the browser UI.\n"
    "\n"
    "Ignore Rendering / Collision / Replication — those are Unreal defaults."
)


@unreal.uclass()
class WorldPromptBuilder(unreal.Actor):
    """Placeable editor actor with a guided, beginner Details layout."""

    # ------------------------------------------------------------------
    # 0 — Instructions (plain language)
    # ------------------------------------------------------------------
    how_to_use = unreal.uproperty(
        str,
        meta={
            "Category": "0 | Read Me First",
            "DisplayName": "How To Use",
            "MultiLine": "true",
            "Tooltip": "Simple instructions. You can leave this alone.",
        },
    )

    # ------------------------------------------------------------------
    # 1 — Prompt (the only required field)
    # ------------------------------------------------------------------
    prompt_text = unreal.uproperty(
        str,
        meta={
            "Category": "1 | Describe Your World",
            "DisplayName": "Describe Your World",
            "MultiLine": "true",
            "Tooltip": "Example: misty alpine peaks at golden hour",
        },
    )

    # ------------------------------------------------------------------
    # 2 — Optional Fab kit
    # ------------------------------------------------------------------
    kit_name = unreal.uproperty(
        str,
        meta={
            "Category": "2 | Optional Fab Meshes",
            "DisplayName": "Kit Folder Name",
            "Tooltip": "Optional name for a folder of your selected Fab meshes.",
        },
    )

    # ------------------------------------------------------------------
    # 3 — Optional content folder
    # ------------------------------------------------------------------
    folder_name = unreal.uproperty(
        str,
        meta={
            "Category": "3 | Optional Content Folder",
            "DisplayName": "Folder Name",
            "Tooltip": "Optional. Example: Forest_01",
        },
    )
    folder_where = unreal.uproperty(
        str,
        meta={
            "Category": "3 | Optional Content Folder",
            "DisplayName": "Parent Folder",
            "Tooltip": "Optional. Example: Builds or WPE/Kits",
        },
    )

    # ------------------------------------------------------------------
    # 4 — Advanced (collapsed mindset — still visible but labeled)
    # ------------------------------------------------------------------
    seed = unreal.uproperty(
        int,
        meta={
            "Category": "4 | Advanced (optional)",
            "DisplayName": "Random Seed",
            "ClampMin": "0",
            "Tooltip": "Same seed ≈ similar layout. Change for a new variation.",
        },
    )
    map_size = unreal.uproperty(
        int,
        meta={
            "Category": "4 | Advanced (optional)",
            "DisplayName": "Map Size (bigger = slower)",
            "ClampMin": "63",
            "ClampMax": "1009",
            "Tooltip": "505 is a good default. Larger maps take longer.",
        },
    )
    spawn_structures = unreal.uproperty(
        bool,
        meta={
            "Category": "4 | Advanced (optional)",
            "DisplayName": "Add Castles / Ruins / Props",
            "Tooltip": "Places structures on the terrain after generation.",
        },
    )
    structure_density = unreal.uproperty(
        float,
        meta={
            "Category": "4 | Advanced (optional)",
            "DisplayName": "How Many Structures",
            "ClampMin": "0.1",
            "ClampMax": "3.0",
            "Tooltip": "1.0 = normal. Higher = more buildings/props.",
        },
    )

    def _ensure_defaults(self):
        try:
            if not self.get_editor_property("how_to_use"):
                self.set_editor_property("how_to_use", _HOW_TO)
            if not self.get_editor_property("prompt_text"):
                self.set_editor_property(
                    "prompt_text", "misty alpine peaks at golden hour")
            size = self.get_editor_property("map_size")
            if not size or int(size) < 63:
                self.set_editor_property("map_size", 505)
            if self.get_editor_property("seed") is None:
                self.set_editor_property("seed", 1337)
        except Exception:
            pass

    def _queue_generate(self):
        self._ensure_defaults()
        import init_unreal
        import content_library

        prompt = (self.get_editor_property("prompt_text") or "").strip()
        if not prompt:
            unreal.log_error(
                "WorldPromptBuilder: Type something in \"Describe Your World\" first.")
            return False

        folder = (self.get_editor_property("folder_name") or "").strip()
        where = (self.get_editor_property("folder_where") or "").strip() or None
        if folder:
            content_library.use_folder(folder, where=where)

        seed = int(self.get_editor_property("seed") or 1337)
        size = int(self.get_editor_property("map_size") or 505)
        try:
            do_structs = bool(self.get_editor_property("spawn_structures"))
        except Exception:
            do_structs = True
        try:
            density = float(self.get_editor_property("structure_density") or 1.0)
        except Exception:
            density = 1.0

        init_unreal.GLOBAL_STATE["command_queue"].append({
            "action": "generate_from_prompt",
            "prompt": prompt,
            "params": {
                "width": size,
                "height": size,
                "seed": seed,
                "spawn_structures": do_structs,
                "structure_density": density,
                "spawn_kit": True,
                "use_hism": True,
                "carve_splines": True,
                "destination": content_library.heightmap_destination(),
            },
        })
        unreal.log(
            "WorldPromptBuilder: Creating world from \"{}\" — watch the viewport "
            "(and Window → Developer Tools → Output Log if curious).".format(prompt))
        return True

    # ------------------------------------------------------------------
    # CallInEditor buttons — names are alphabetical on purpose so the
    # Details panel lists them in beginner order (step1… step6).
    # DisplayName is what the user actually reads.
    # ------------------------------------------------------------------

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "1 | Describe Your World",
        "DisplayName": "DEMO: Alpine Sunset",
        "Tooltip": "One-click Base-X demo: misty alpine peaks at golden hour",
    })
    def step0a_demo_alpine_sunset(self):
        try:
            import demo_presets
            demo_presets.run_alpine()
        except Exception as e:
            unreal.log_error("DEMO Alpine failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "1 | Describe Your World",
        "DisplayName": "DEMO: Underwater",
        "Tooltip": "One-click Base-X demo: underwater seafloor",
    })
    def step0b_demo_underwater(self):
        try:
            import demo_presets
            demo_presets.run_underwater()
        except Exception as e:
            unreal.log_error("DEMO Underwater failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "1 | Describe Your World",
        "DisplayName": "DEMO: Desert Blood Moon",
        "Tooltip": "One-click Base-X demo: desert dunes under a blood moon",
    })
    def step0c_demo_desert_moon(self):
        try:
            import demo_presets
            demo_presets.run_desert()
        except Exception as e:
            unreal.log_error("DEMO Desert failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "1 | Describe Your World",
        "DisplayName": "Create World Now",
        "Tooltip": "Builds terrain, lighting, rivers, and props from your description.",
    })
    def step1_create_world_now(self):
        try:
            self._queue_generate()
        except Exception as e:
            unreal.log_error("Create World Now failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "1 | Describe Your World",
        "DisplayName": "Auto-Setup Landscape Look",
        "Tooltip": "Creates Grass/Rock/Snow material automatically and applies it. No Material Editor needed.",
    })
    def step1b_auto_setup_landscape_look(self):
        try:
            import landscape_auto_setup
            result = landscape_auto_setup.ensure_landscape_material_stack(
                force_rebuild=False, assign=True)
            if result.get("ok"):
                unreal.log(
                    "WorldPromptBuilder: Landscape look is ready "
                    "(auto slope/height blend). Generate a world if you have not yet.")
            else:
                unreal.log_error(
                    "WorldPromptBuilder: auto landscape setup failed: {}".format(
                        result.get("error") or result))
        except Exception as e:
            unreal.log_error("Auto-Setup Landscape Look failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "1 | Describe Your World",
        "DisplayName": "Open Easy Panel (recommended)",
        "Tooltip": "Opens a simple browser window — easiest if Unreal feels overwhelming.",
    })
    def step2_open_easy_panel(self):
        try:
            import init_unreal
            init_unreal.open_ui()
            unreal.log(
                "WorldPromptBuilder: Easy Panel opened in your browser. "
                "If nothing opened, check for a new browser tab.")
        except Exception as e:
            unreal.log_error("Open Easy Panel failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "2 | Optional Fab Meshes",
        "DisplayName": "Use Selected Fab Meshes",
        "Tooltip": "First select tree/rock meshes in the Content Browser (bottom), then click this.",
    })
    def step3_use_selected_fab_meshes(self):
        try:
            import kit_library
            name = ""
            try:
                name = (self.get_editor_property("kit_name") or "").strip()
            except Exception:
                name = ""
            if not name:
                try:
                    name = (self.get_editor_property("folder_name") or "").strip()
                except Exception:
                    name = ""
            result = kit_library.capture_selected_as_kit(kit_name=name or None)
            if result.get("ok"):
                try:
                    self.set_editor_property("kit_name", result.get("kit_name", ""))
                    self.set_editor_property("folder_name", result.get("kit_name", ""))
                    self.set_editor_property("folder_where", "WPE/Kits")
                except Exception:
                    pass
                unreal.log(
                    "WorldPromptBuilder: Saved your meshes as kit '{}'. "
                    "Now click Create World Now.".format(result.get("kit_name")))
            else:
                unreal.log_error(
                    "WorldPromptBuilder: {}".format(
                        result.get("error") or "Select Fab StaticMeshes in Content Browser first."))
        except Exception as e:
            unreal.log_error("Use Selected Fab Meshes failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "3 | Optional Content Folder",
        "DisplayName": "Use This Content Folder",
        "Tooltip": "Points the plugin at Folder Name / Parent Folder above.",
    })
    def step4_use_this_content_folder(self):
        try:
            import content_library
            folder = (self.get_editor_property("folder_name") or "").strip()
            if not folder:
                unreal.log_error(
                    "WorldPromptBuilder: Type a Folder Name in section 3 first.")
                return
            where = (self.get_editor_property("folder_where") or "").strip() or None
            result = content_library.use_folder(folder, where=where)
            unreal.log("WorldPromptBuilder: Using folder {}".format(
                result.get("content_root")))
        except Exception as e:
            unreal.log_error("Use This Content Folder failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "4 | Advanced (optional)",
        "DisplayName": "Clear Placed Props",
        "Tooltip": "Removes castles/ruins/props this plugin added (not your whole level).",
    })
    def step5_clear_placed_props(self):
        try:
            import init_unreal
            import structure_library
            structure_library.clear_spawned_structures(init_unreal.GLOBAL_STATE)
            unreal.log("WorldPromptBuilder: Cleared placed props.")
        except Exception as e:
            unreal.log_error("Clear Placed Props failed: {}".format(e))

    @unreal.ufunction(meta={
        "CallInEditor": "true",
        "Category": "4 | Advanced (optional)",
        "DisplayName": "Show Status In Log",
        "Tooltip": "Writes plugin status to the Output Log (Window → Developer Tools → Output Log).",
    })
    def step6_show_status_in_log(self):
        try:
            import init_unreal
            unreal.log("WorldPromptBuilder status: {}".format(init_unreal.status()))
            unreal.log("WorldPromptBuilder content: {}".format(init_unreal.content_status()))
            unreal.log(
                "Tip: open Window → Developer Tools → Output Log to read messages.")
        except Exception as e:
            unreal.log_error("Show Status failed: {}".format(e))

    # Back-compat aliases (old button names still callable from Python)
    def generate_world(self):
        return self.step1_create_world_now()

    def open_control_panel(self):
        return self.step2_open_easy_panel()

    def capture_selected_as_kit(self):
        return self.step3_use_selected_fab_meshes()

    def use_content_folder(self):
        return self.step4_use_this_content_folder()

    def clear_structures(self):
        return self.step5_clear_placed_props()

    def show_status(self):
        return self.step6_show_status_in_log()


def place_builder(location=None) -> unreal.Actor:
    """Spawn WorldPromptBuilder, select it, fill beginner defaults.
    Removes any old WorldPromptBuilder actors first so you always get the new UI.
    """
    try:
        # --- delete old builders ---
        try:
            if hasattr(unreal, "EditorActorSubsystem"):
                subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                actors = list(subsys.get_all_level_actors() or [])
                removed = 0
                for a in actors:
                    try:
                        label = ""
                        try:
                            label = a.get_actor_label() or ""
                        except Exception:
                            pass
                        cls = a.get_class().get_name() if a.get_class() else ""
                        if label == "WorldPromptBuilder" or "WorldPromptBuilder" in cls:
                            subsys.destroy_actor(a)
                            removed += 1
                    except Exception:
                        continue
                if removed:
                    unreal.log(
                        "WorldPromptEngine: removed {} old WorldPromptBuilder actor(s)".format(removed))
        except Exception as clear_e:
            unreal.log_warning("WorldPromptEngine: could not clear old builders: {}".format(clear_e))

        if location is None:
            location = unreal.Vector(0.0, 0.0, 200.0)

        actor = None
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actor = subsys.spawn_actor_from_class(WorldPromptBuilder, location)
        elif hasattr(unreal, "EditorLevelLibrary"):
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                WorldPromptBuilder, location)

        if actor is None:
            unreal.log_error("WorldPromptEngine: failed to spawn WorldPromptBuilder")
            return None

        try:
            actor.set_actor_label("WorldPromptBuilder")
        except Exception:
            pass

        try:
            actor.set_editor_property("how_to_use", _HOW_TO)
            actor.set_editor_property("prompt_text", "misty alpine peaks at golden hour")
            actor.set_editor_property("seed", 1337)
            actor.set_editor_property("map_size", 505)
            actor.set_editor_property("folder_name", "")
            actor.set_editor_property("folder_where", "Builds")
            actor.set_editor_property("kit_name", "")
            actor.set_editor_property("spawn_structures", True)
            actor.set_editor_property("structure_density", 1.0)
        except Exception as e:
            unreal.log_warning("WorldPromptBuilder defaults: {}".format(e))

        try:
            if hasattr(unreal, "EditorActorSubsystem"):
                unreal.get_editor_subsystem(unreal.EditorActorSubsystem).set_selected_level_actors([actor])
            elif hasattr(unreal, "EditorLevelLibrary"):
                unreal.EditorLevelLibrary.set_selected_level_actors([actor])
        except Exception:
            pass

        unreal.log(
            "WorldPromptEngine: Builder placed and selected.\n"
            "  → In Details: read \"0 | Read Me First\"\n"
            "  → Type a world in \"Describe Your World\"\n"
            "  → Click \"Create World Now\"  (or \"Open Easy Panel\")")
        return actor
    except Exception as e:
        unreal.log_error("world_builder_actor.place_builder failed: {}".format(e))
        return None
