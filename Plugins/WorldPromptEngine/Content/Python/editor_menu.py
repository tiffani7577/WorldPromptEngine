"""
editor_menu.py — Tools → World Prompt Engine menu (beginner labels, UE 5.8)
"""

from __future__ import annotations

import unreal

_REGISTERED = False


def register_menus():
    """Idempotent Tools menu registration with plain-language entries."""
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        if not hasattr(unreal, "ToolMenus"):
            unreal.log_warning("WorldPromptEngine: ToolMenus unavailable")
            return

        menus = unreal.ToolMenus.get()
        tools = menus.find_menu("LevelEditor.MainMenu.Tools")
        if tools is None:
            unreal.log_warning("WorldPromptEngine: LevelEditor.MainMenu.Tools not found")
            return

        section = "WorldPromptEngine"
        try:
            tools.add_section(section, "World Prompt Engine")
        except Exception:
            pass

        commands = [
            ("WPE_PlaceBuilder", "1. Place World Builder (start here)",
             "Drops a helper actor in the level. Select it, then use the Details panel.",
             "import world_builder_actor; world_builder_actor.place_builder()"),
            ("WPE_DemoAlpine", "DEMO: Alpine Sunset",
             "misty alpine peaks at golden hour",
             "import demo_presets; demo_presets.run_alpine()"),
            ("WPE_DemoUnderwater", "DEMO: Underwater",
             "underwater seafloor with kelp and sunken ruins",
             "import demo_presets; demo_presets.run_underwater()"),
            ("WPE_DemoDesert", "DEMO: Desert Blood Moon",
             "desert dunes under a blood moon",
             "import demo_presets; demo_presets.run_desert()"),
            ("WPE_OpenPanel", "2. Open Easy Panel (browser)",
             "Simplest UI: type a prompt and press Create World.",
             "import init_unreal; init_unreal.open_ui()"),
            ("WPE_AutoMat", "Optional: Auto-Setup Landscape Look",
             "Creates Grass/Rock/Snow material automatically (no Material Editor).",
             "import landscape_auto_setup, unreal; unreal.log(str(landscape_auto_setup.ensure_landscape_material_stack(assign=True)))"),
            ("WPE_DemoPrompt", "3. Create Demo World (legacy alpine)",
             "One-click sample: misty alpine peaks at golden hour",
             "import init_unreal; init_unreal.prompt('misty alpine peaks at golden hour')"),
            ("WPE_CaptureKit", "Optional: Use Selected Fab Meshes",
             "Select tree/rock StaticMeshes in Content Browser first, then run this.",
             "import kit_library, unreal; unreal.log(str(kit_library.capture_selected_as_kit()))"),
            ("WPE_ContentStatus", "Help: Show Status In Log",
             "Prints plugin status. Open Window → Developer Tools → Output Log.",
             "import init_unreal; unreal.log(str(init_unreal.content_status()))"),
            ("WPE_Preforge", "Advanced: Prefabricate Structure Meshes",
             "Optional bake for castles/ruins (Geometry Script) or proxy shapes.",
             "import init_unreal; unreal.log(str(init_unreal.preforge_structures()))"),
            ("WPE_CineRandomize", "Cinematic: Randomize Camera Path",
             "Destroys prior WPE cinematic actors, then spawns a fresh USplineComponent path.",
             "import cinematic_camera, unreal; unreal.log(str(cinematic_camera.randomize_path()))"),
            ("WPE_CineStart", "Cinematic: Start Camera Fly-Through",
             "Cleans prior WPE cinematic actors, then flies along a USplineComponent path.",
             "import cinematic_camera, unreal; unreal.log(str(cinematic_camera.start_camera()))"),
            ("WPE_CineStop", "Cinematic: Stop Camera",
             "Stops the fly-through tick (actors remain until next randomize/start).",
             "import cinematic_camera; cinematic_camera.stop_camera()"),
        ]

        for name, label, tip, py in commands:
            try:
                entry = unreal.ToolMenuEntry(
                    name=name,
                    type=unreal.MultiBlockType.MENU_ENTRY,
                )
                entry.set_label(label)
                entry.set_tool_tip(tip)
                entry.set_string_command(
                    unreal.ToolMenuStringCommandType.PYTHON,
                    "",
                    py,
                )
                tools.add_menu_entry(section, entry)
            except Exception as e:
                unreal.log_warning("WorldPromptEngine: menu entry '{}' failed: {}".format(name, e))

        try:
            menus.refresh_all_widgets()
        except Exception:
            pass

        _REGISTERED = True
        unreal.log("WorldPromptEngine: Tools → World Prompt Engine menu ready (beginner labels)")
    except Exception as e:
        unreal.log_error("editor_menu.register_menus failed: {}".format(e))
