"""
wpe_dashboard.py — WorldPromptEngine control surface (UE 5.8).

UE 5.8 Python cannot author full Slate/UMG widget hierarchies procedurally
with drag-reorder etc., so this module does three things:

1. If an Editor Utility Widget asset EUW_WPE_Dashboard exists in
   /Game/WorldPromptEngine/UI/, it registers and docks it via
   EditorUtilitySubsystem.spawn_and_register_tab(). (The EUW binds its
   buttons directly to the module functions below.)
2. Regardless, it installs Tools-menu entries covering every dashboard
   action so the whole system is fully operable without the asset.
3. It exposes a clean, stable Python API surface that the EUW, the
   Tools menu, the MCP bridge, and the console all call into:

   Author:      generate(prompt, map_size, roughness, foliage), abort(),
                status(), library(), save_current(world_name)
   Performance: setlist_*, next_world(), jump(index), osc_start/stop(),
                monitor()
"""

import json

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    unreal = None
    _HAS_UNREAL = False

import performance_engine
import world_library

EUW_PATH = "/Game/WorldPromptEngine/UI/EUW_WPE_Dashboard"
_TAB_ID = None


def _log(msg):
    if _HAS_UNREAL:
        unreal.log("[WorldPromptEngine][Dashboard] {}".format(msg))
    else:
        print(msg)


def _log_error(msg):
    if _HAS_UNREAL:
        unreal.log_error("[WorldPromptEngine][Dashboard] {}".format(msg))
    else:
        print("ERROR:", msg)


def _global_state():
    try:
        import init_unreal
        return init_unreal.GLOBAL_STATE
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# AUTHOR MODE API
# ---------------------------------------------------------------------------

def generate(prompt_text, map_size=2048, roughness=0.5, foliage_density=0.5):
    """Validate inputs and enqueue async world generation via art_engine."""
    try:
        state = _global_state()
        if state.get("is_generating"):
            _log_error("generation already in progress — abort first")
            return False
        prompt_text = (prompt_text or "").strip()
        if not prompt_text:
            _log_error("empty prompt")
            return False
        map_size = int(map_size)
        if map_size not in (1024, 2048, 4096):
            map_size = 2048
        roughness = max(0.0, min(1.0, float(roughness)))
        foliage_density = max(0.0, min(1.0, float(foliage_density)))
        state["last_prompt"] = prompt_text
        state.setdefault("command_queue", []).append({
            "command": "generate_world",
            "payload": {
                "prompt": prompt_text,
                "map_size": map_size,
                "roughness": roughness,
                "foliage_density": foliage_density,
            },
        })
        _log("generation queued: '{}' size={} rough={} foliage={}".format(
            prompt_text[:60], map_size, roughness, foliage_density))
        return True
    except Exception as e:
        _log_error("generate: {}".format(e))
        return False


def abort():
    try:
        state = _global_state()
        state["abort_flag"] = True
        _log("abort flag set")
        return True
    except Exception as e:
        _log_error("abort: {}".format(e))
        return False


def status():
    """Current phase + progress for progress bars / MCP get_generation_status."""
    try:
        state = _global_state()
        return {
            "is_generating": bool(state.get("is_generating")),
            "current_phase": str(state.get("current_phase", state.get("active_task") and "Working" or "Idle")),
            "progress_pct": float(state.get("progress", 0.0)) * (100.0 if state.get("progress", 0.0) <= 1.0 else 1.0),
            "last_prompt": state.get("last_prompt", ""),
        }
    except Exception as e:
        _log_error("status: {}".format(e))
        return {"is_generating": False, "current_phase": "Error", "progress_pct": 0.0, "last_prompt": ""}


def library():
    return world_library.load_world_library()


def save_current(world_name):
    return world_library.save_world(world_name, _global_state())


# ---------------------------------------------------------------------------
# PERFORMANCE MODE API (thin, delegates to performance_engine)
# ---------------------------------------------------------------------------

def setlist():
    return list(performance_engine.STATE["setlist"])


def setlist_add(world_path, display_name):
    performance_engine.add_world_to_setlist(world_path, display_name)


def setlist_remove(index):
    performance_engine.remove_world_from_setlist(index)


def setlist_move(from_index, to_index):
    performance_engine.reorder_setlist(from_index, to_index)


def setlist_save(name):
    return performance_engine.save_setlist(name)


def setlist_load(name):
    return performance_engine.load_setlist(name)


def setlists():
    return performance_engine.list_saved_setlists()


def next_world():
    return performance_engine.load_next_world()


def jump(index):
    return performance_engine.load_world_at_index(index)


def osc_start():
    return performance_engine.start_osc_receiver()


def osc_stop():
    return performance_engine.stop_osc_receiver()


def monitor():
    """Live readout for the dashboard's parameter monitor + OSC status panel."""
    s = performance_engine.STATE
    return {
        "osc_port": performance_engine.OSC_PORT,
        "osc_active": bool(s["osc_receiver_active"]),
        "last_address": s["last_osc_address"],
        "last_value": s["last_osc_value"],
        "last_scene_trigger": s["last_scene_trigger"],
        "current_index": s["current_setlist_index"],
        "current_world": (s["setlist"][s["current_setlist_index"]]["name"]
                          if 0 <= s["current_setlist_index"] < len(s["setlist"]) else ""),
        "transition_active": bool(s["transition_active"]),
        "params": dict(s["current_param_values"]),
    }


# ---------------------------------------------------------------------------
# Tab registration + Tools menu
# ---------------------------------------------------------------------------

def register_dashboard_tab():
    """Dock EUW_WPE_Dashboard if the asset exists."""
    global _TAB_ID
    try:
        if not _HAS_UNREAL:
            return False
        if not unreal.EditorAssetLibrary.does_asset_exist(EUW_PATH):
            _log("EUW_WPE_Dashboard asset not found — Tools menu fallback active")
            return False
        blueprint = unreal.EditorAssetLibrary.load_asset(EUW_PATH)
        eus = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        widget, tab_id = eus.spawn_and_register_tab(blueprint)
        _TAB_ID = tab_id
        _log("dashboard tab docked: {}".format(tab_id))
        return True
    except Exception as e:
        _log_error("register_dashboard_tab: {}".format(e))
        return False


def _menu_entry(menu, section, label, tooltip, command):
    try:
        entry = unreal.ToolMenuEntry(
            name=label.replace(" ", ""),
            type=unreal.MultiBlockType.MENU_ENTRY)
        entry.set_label(label)
        entry.set_tool_tip(tooltip)
        entry.set_string_command(
            unreal.ToolMenuStringCommandType.PYTHON, "", command)
        menu.add_menu_entry(section, entry)
    except Exception as e:
        _log_error("menu entry '{}': {}".format(label, e))


def install_tools_menu():
    """Full dashboard action set in Tools -> WPE Dashboard."""
    try:
        if not _HAS_UNREAL or not hasattr(unreal, "ToolMenus"):
            return False
        menus = unreal.ToolMenus.get()
        main = menus.find_menu("LevelEditor.MainMenu.Tools")
        if main is None:
            return False
        sub = main.add_sub_menu(
            "WPEDashboard", "WPE", "WPEDashboardMenu", "WPE Dashboard")
        sub.add_section("Author", "Author Mode")
        _menu_entry(sub, "Author", "Generate From Clipboard Prompt",
                    "Generate a world from the prompt text on the clipboard",
                    "import wpe_dashboard, unreal;"
                    "p=unreal.SystemLibrary.get_clipboard_content() if hasattr(unreal.SystemLibrary,'get_clipboard_content') else '';"
                    "wpe_dashboard.generate(p or 'misty alpine peaks at golden hour')")
        _menu_entry(sub, "Author", "Abort Generation",
                    "Stop the current generation task",
                    "import wpe_dashboard; wpe_dashboard.abort()")
        _menu_entry(sub, "Author", "Show Generation Status",
                    "Log phase + progress",
                    "import wpe_dashboard, unreal, json;"
                    "unreal.log(json.dumps(wpe_dashboard.status()))")
        _menu_entry(sub, "Author", "Save Current World...",
                    "Save the open level into the world library (name = level name)",
                    "import wpe_dashboard, unreal;"
                    "w=unreal.EditorLevelLibrary.get_editor_world();"
                    "wpe_dashboard.save_current(w.get_name() if w else 'Untitled')")
        _menu_entry(sub, "Author", "List World Library",
                    "Log all saved worlds",
                    "import wpe_dashboard, unreal, json;"
                    "[unreal.log(json.dumps(m)) for m in wpe_dashboard.library()]")
        sub.add_section("Performance", "Performance Mode")
        _menu_entry(sub, "Performance", "Start OSC Receiver (port 8000)",
                    "Begin listening for Ableton triggers",
                    "import wpe_dashboard; wpe_dashboard.osc_start()")
        _menu_entry(sub, "Performance", "Stop OSC Receiver",
                    "Stop listening",
                    "import wpe_dashboard; wpe_dashboard.osc_stop()")
        _menu_entry(sub, "Performance", "Next World",
                    "Fog transition to the next setlist world",
                    "import wpe_dashboard; wpe_dashboard.next_world()")
        _menu_entry(sub, "Performance", "Show Live Monitor",
                    "Log OSC status + smoothed parameter values",
                    "import wpe_dashboard, unreal, json;"
                    "unreal.log(json.dumps(wpe_dashboard.monitor()))")
        _menu_entry(sub, "Performance", "Open Dashboard Tab",
                    "Dock the EUW dashboard widget (if asset exists)",
                    "import wpe_dashboard; wpe_dashboard.register_dashboard_tab()")
        menus.refresh_all_widgets()
        _log("Tools menu installed")
        return True
    except Exception as e:
        _log_error("install_tools_menu: {}".format(e))
        return False


def initialize():
    """Called from init_unreal at editor startup."""
    try:
        install_tools_menu()
        register_dashboard_tab()
    except Exception as e:
        _log_error("initialize: {}".format(e))
