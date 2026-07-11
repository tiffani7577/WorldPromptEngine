"""
editor_menu.py — Tools → World Prompt Engine menu (UE 5.8)
"""

from __future__ import annotations

import unreal

_REGISTERED = False


def register_menus():
    """Idempotent Tools menu registration."""
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
            ("WPE_PlaceBuilder", "Place Builder In Level",
             "Drop WorldPromptBuilder (prompt + Generate in Details)",
             "import world_builder_actor; world_builder_actor.place_builder()"),
            ("WPE_OpenPanel", "Open Control Panel",
             "Open the browser Generate panel",
             "import init_unreal; init_unreal.open_ui()"),
            ("WPE_DemoPrompt", "Generate Demo Prompt",
             "Queue a sample alpine world",
             "import init_unreal; init_unreal.prompt('misty alpine peaks at golden hour')"),
            ("WPE_ContentStatus", "Log Content Status",
             "Print missing mesh folders/assets",
             "import init_unreal; unreal.log(str(init_unreal.content_status()))"),
            ("WPE_Preforge", "Preforge Structure Meshes",
             "Bake keep/ruin/crystal/megalith/hut/arch via Geometry Script (or note proxy mode)",
             "import init_unreal; unreal.log(str(init_unreal.preforge_structures()))"),
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
        unreal.log("WorldPromptEngine: Tools → World Prompt Engine menu ready")
    except Exception as e:
        unreal.log_error("editor_menu.register_menus failed: {}".format(e))
