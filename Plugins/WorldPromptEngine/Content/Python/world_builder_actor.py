"""
world_builder_actor.py — Base-X-style drop-in builder for WorldPromptEngine (UE 5.8)

Usage (inside Unreal, no Python console required after first place):
  1. Tools → World Prompt Engine → Place Builder In Level
     (or: import init_unreal; init_unreal.place_builder())
  2. Select the WorldPromptBuilder actor in the level
  3. In Details: type Prompt Text, optional Folder Name / Where
  4. Click the Generate World button (Call In Editor)
"""

from __future__ import annotations

import unreal


@unreal.uclass()
class WorldPromptBuilder(unreal.Actor):
    """Placeable editor actor: prompt in Details → Generate World button."""

    # --- Details panel fields ---
    prompt_text = unreal.uproperty(
        str,
        meta={
            "Category": "World Prompt",
            "DisplayName": "Prompt Text",
            "MultiLine": "true",
        },
    )
    folder_name = unreal.uproperty(
        str,
        meta={
            "Category": "World Prompt|Content Folder",
            "DisplayName": "Folder Name",
            "Tooltip": "Optional. Example: Forest_01 — plugin will find or create it.",
        },
    )
    folder_where = unreal.uproperty(
        str,
        meta={
            "Category": "World Prompt|Content Folder",
            "DisplayName": "Where",
            "Tooltip": "Optional. Example: Builds or /Game/Builds",
        },
    )
    seed = unreal.uproperty(
        int,
        meta={"Category": "World Prompt|Generation", "DisplayName": "Seed", "ClampMin": "0"},
    )
    map_size = unreal.uproperty(
        int,
        meta={
            "Category": "World Prompt|Generation",
            "DisplayName": "Map Size",
            "ClampMin": "63",
            "ClampMax": "1009",
        },
    )
    spawn_structures = unreal.uproperty(
        bool,
        meta={
            "Category": "World Prompt|Generation",
            "DisplayName": "Spawn Structures",
            "Tooltip": "Place castles, ruins, crystals, etc. (uses your meshes or shape proxies)",
        },
    )
    structure_density = unreal.uproperty(
        float,
        meta={
            "Category": "World Prompt|Generation",
            "DisplayName": "Structure Density",
            "ClampMin": "0.1",
            "ClampMax": "3.0",
        },
    )

    def _ensure_defaults(self):
        """uproperty defaults are unreliable in Python — fill empties safely."""
        try:
            if not self.get_editor_property("prompt_text"):
                self.set_editor_property(
                    "prompt_text", "misty alpine peaks at golden hour")
            if self.get_editor_property("seed") in (None, 0):
                # 0 is valid; only set if somehow unset — leave user 0 alone
                pass
            size = self.get_editor_property("map_size")
            if not size or int(size) < 63:
                self.set_editor_property("map_size", 505)
            if self.get_editor_property("seed") is None:
                self.set_editor_property("seed", 1337)
        except Exception:
            pass

    @unreal.ufunction(meta={"CallInEditor": "true", "Category": "World Prompt"})
    def generate_world(self):
        """Details-panel button: Generate World."""
        try:
            self._ensure_defaults()
            import init_unreal
            import content_library

            prompt = (self.get_editor_property("prompt_text") or "").strip()
            if not prompt:
                unreal.log_error("WorldPromptBuilder: Prompt Text is empty")
                return

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

            # Queue with structure flags via generate_from_prompt path
            init_unreal.GLOBAL_STATE["command_queue"].append({
                "action": "generate_from_prompt",
                "prompt": prompt,
                "params": {
                    "width": size,
                    "height": size,
                    "seed": seed,
                    "spawn_structures": do_structs,
                    "structure_density": density,
                    "destination": __import__("content_library").heightmap_destination(),
                },
            })
            unreal.log("WorldPromptBuilder: queued prompt '{}' (structures={})".format(
                prompt, do_structs))
        except Exception as e:
            unreal.log_error("WorldPromptBuilder.generate_world failed: {}".format(e))

    @unreal.ufunction(meta={"CallInEditor": "true", "Category": "World Prompt"})
    def use_content_folder(self):
        """Details-panel button: point plugin at Folder Name / Where."""
        try:
            import content_library
            folder = (self.get_editor_property("folder_name") or "").strip()
            if not folder:
                unreal.log_error("WorldPromptBuilder: set Folder Name first")
                return
            where = (self.get_editor_property("folder_where") or "").strip() or None
            result = content_library.use_folder(folder, where=where)
            unreal.log("WorldPromptBuilder: use_folder -> {}".format(result.get("content_root")))
        except Exception as e:
            unreal.log_error("WorldPromptBuilder.use_content_folder failed: {}".format(e))

    @unreal.ufunction(meta={"CallInEditor": "true", "Category": "World Prompt"})
    def clear_structures(self):
        """Remove previously spawned WPE structures."""
        try:
            import init_unreal
            import structure_library
            structure_library.clear_spawned_structures(init_unreal.GLOBAL_STATE)
        except Exception as e:
            unreal.log_error("WorldPromptBuilder.clear_structures failed: {}".format(e))

    @unreal.ufunction(meta={"CallInEditor": "true", "Category": "World Prompt"})
    def open_control_panel(self):
        """Details-panel button: open browser control panel."""
        try:
            import init_unreal
            init_unreal.open_ui()
        except Exception as e:
            unreal.log_error("WorldPromptBuilder.open_control_panel failed: {}".format(e))

    @unreal.ufunction(meta={"CallInEditor": "true", "Category": "World Prompt"})
    def show_status(self):
        """Details-panel button: log engine + content status."""
        try:
            import init_unreal
            unreal.log("WorldPromptBuilder status: {}".format(init_unreal.status()))
            unreal.log("WorldPromptBuilder content: {}".format(init_unreal.content_status()))
        except Exception as e:
            unreal.log_error("WorldPromptBuilder.show_status failed: {}".format(e))


def place_builder(location=None) -> unreal.Actor:
    """
    Spawn a WorldPromptBuilder in the current level and select it.
    Returns the actor (or None on failure).
    """
    try:
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
            actor.set_editor_property("prompt_text", "misty alpine peaks at golden hour")
            actor.set_editor_property("seed", 1337)
            actor.set_editor_property("map_size", 505)
            actor.set_editor_property("folder_name", "")
            actor.set_editor_property("folder_where", "Builds")
            actor.set_editor_property("spawn_structures", True)
            actor.set_editor_property("structure_density", 1.0)
        except Exception as e:
            unreal.log_warning("WorldPromptBuilder defaults: {}".format(e))

        # Select it so Details panel shows the Generate button immediately
        try:
            if hasattr(unreal, "EditorActorSubsystem"):
                unreal.get_editor_subsystem(unreal.EditorActorSubsystem).set_selected_level_actors([actor])
            elif hasattr(unreal, "EditorLevelLibrary"):
                unreal.EditorLevelLibrary.set_selected_level_actors([actor])
        except Exception:
            pass

        unreal.log(
            "WorldPromptEngine: placed WorldPromptBuilder. "
            "Select it → Details → set Prompt Text → Generate World")
        return actor
    except Exception as e:
        unreal.log_error("world_builder_actor.place_builder failed: {}".format(e))
        return None
