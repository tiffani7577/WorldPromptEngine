# Hot-reload panel Python + reopen HTML for the live editor.
import importlib
import unreal

mods = [
    "performance_engine",
    "cinematic_camera",
    "wpe_dashboard",
    "world_library",
    "wpe_main_panel",
    "art_engine",
]
for name in mods:
    try:
        mod = __import__(name)
        importlib.reload(mod)
        unreal.log("[WorldPromptEngine] reloaded {}".format(name))
    except Exception as e:
        unreal.log_warning("[WorldPromptEngine] reload {}: {}".format(name, e))

import wpe_main_panel
# Force LoadPanelHtml again through open_panel
try:
    # Directly load HTML into any spawned WPEMainPanelWidget instances
    path = wpe_main_panel._html_path()
    widgets = []
    try:
        # Iterate editor utility widgets if API exists
        eus = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
    except Exception:
        eus = None
    result = wpe_main_panel.open_panel()
    # Also call LoadPanelHtml on C++ host if exposed from spawn
    unreal.log("[WorldPromptEngine] open_panel -> {} html={}".format(result, path))
except Exception as e:
    unreal.log_error("[WorldPromptEngine] reopen failed: {}".format(e))
