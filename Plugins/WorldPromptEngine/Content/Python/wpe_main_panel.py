"""
wpe_main_panel.py — Dead-simple guided panel for performing artists (UE 5.8).

Business logic for EUW_WPE_Main. The visual UI is wpe_main_panel.html hosted
inside a docked Editor Utility Widget (WebBrowser). All button actions route
here via the WebSocket bridge (panel_rpc) or direct Python calls.

Never exposes Python/tracebacks to the artist — every entry point returns
friendly status dicts: {"ok": True/False, "message": "..."}.
"""

from __future__ import annotations

import json
import os

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    unreal = None  # type: ignore
    _HAS_UNREAL = False

import cinematic_camera
import performance_engine
import wpe_dashboard
import world_library

EUW_PATH = "/Game/WorldPromptEngine/UI/EUW_WPE_Main"
EUW_DIR = "/Game/WorldPromptEngine/UI"

# UI labels → landscape resolutions the pipeline can actually apply.
MAP_SIZE_CHOICES = {
    "Small (faster)": 1024,
    "Medium": 2048,
    "Large (best quality)": 4096,
}
MAP_SIZE_TO_PIXELS = {
    1024: 1009,
    2048: 2017,
    4096: 4033,
}

MOOD_KEYWORDS = {
    "Ethereal & Beautiful": "ethereal luminous soft glow crystalline beauty",
    "Dark & Dramatic": "dark dramatic ominous shadows blood moon intensity",
    "Epic & Massive": "epic colossal vast monumental grandeur",
    "Dreamy & Soft": "dreamy soft pastel haze gentle quiet wonder",
}

# Ten visually distinct weather presets (friendly label → asset_manifest key).
WEATHER_CHOICES = [
    ("Clear Noon", "clear_noon"),
    ("Golden Hour", "golden_hour"),
    ("Blood Moon", "blood_moon"),
    ("Dense Fog", "dense_fog"),
    ("Storm Front", "storm_front"),
    ("Aurora Night", "aurora_night"),
    ("Deep Ocean Dark", "deep_ocean_dark"),
    ("Blizzard", "blizzard"),
    ("Ember Night", "ember_night"),
    ("Crystal Glow", "crystal_glow"),
]

_TAB_ID = None
_TICK_HANDLE = None
_LAST_FRIENDLY_ERROR = ""


def _log(msg: str):
    if _HAS_UNREAL:
        unreal.log("[WorldPromptEngine][MainPanel] {}".format(msg))
    else:
        print(msg)


def _friendly(ok: bool, message: str, **extra) -> dict:
    global _LAST_FRIENDLY_ERROR
    if not ok:
        _LAST_FRIENDLY_ERROR = message
    out = {"ok": bool(ok), "message": str(message)}
    out.update(extra)
    return out


def _global_state():
    try:
        import init_unreal
        return init_unreal.GLOBAL_STATE
    except Exception:
        return {}


def _html_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "wpe_main_panel.html")


def _compose_prompt(user_prompt: str, mood_label: str, weather_key: str) -> str:
    parts = [(user_prompt or "").strip()]
    mood = MOOD_KEYWORDS.get(mood_label) or ""
    if mood:
        parts.append(mood)
    # Weather key as readable words so prompt_matrix can score it.
    weather_words = (weather_key or "").replace("_", " ")
    if weather_words:
        parts.append(weather_words)
    return " ".join(p for p in parts if p)


def _phase_label(state: dict) -> str:
    if not state.get("is_generating"):
        prog = float(state.get("progress") or 0.0)
        if prog >= 1.0 and state.get("last_prompt"):
            return "Done!"
        return "Ready"
    phase = str(state.get("current_phase") or "").strip()
    if phase and phase.lower() not in ("idle", "working", ""):
        return phase
    p = float(state.get("progress") or 0.0)
    if p < 0.86:
        return "Building terrain..."
    if p < 0.95:
        return "Placing assets..."
    if p < 0.99:
        return "Configuring sky..."
    return "Finishing..."


# ---------------------------------------------------------------------------
# Author actions
# ---------------------------------------------------------------------------

def action_generate(prompt_text, map_size_label="Medium", mood_label="Ethereal & Beautiful",
                    weather_label="Blood Moon") -> dict:
    try:
        prompt_text = (prompt_text or "").strip()
        if not prompt_text:
            return _friendly(False, "Please describe the world for this song first.")

        size_label = map_size_label if map_size_label in MAP_SIZE_CHOICES else "Medium"
        map_size = MAP_SIZE_CHOICES[size_label]
        weather_key = "blood_moon"
        for label, key in WEATHER_CHOICES:
            if label == weather_label or key == weather_label:
                weather_key = key
                break

        full_prompt = _compose_prompt(prompt_text, mood_label, weather_key)
        # Prefer dashboard API; it validates sizes 1024/2048/4096.
        ok = wpe_dashboard.generate(
            full_prompt,
            map_size=map_size,
            roughness=0.55 if size_label.startswith("Large") else 0.45,
            foliage_density=0.75 if size_label.startswith("Large") else 0.55,
        )
        if not ok:
            state = _global_state()
            if state.get("is_generating"):
                return _friendly(False, "A world is already building — please wait.")
            return _friendly(False, "Something went wrong — try again.")

        state = _global_state()
        state["current_phase"] = "Building terrain..."
        state["last_prompt"] = full_prompt
        state["last_user_prompt"] = prompt_text
        state["last_weather_choice"] = weather_key
        state["last_mood_choice"] = mood_label
        return _friendly(True, "Building your world — watch the 3D view.", generating=True)
    except Exception:
        return _friendly(False, "Something went wrong — try again.")


def action_save_world(world_name: str) -> dict:
    try:
        name = (world_name or "").strip()
        if not name:
            return _friendly(False, "Give this world a name first.")
        ok = wpe_dashboard.save_current(name)
        if ok:
            return _friendly(True, "World saved!", world_name=name)
        return _friendly(False, "Could not save — try a simpler name.")
    except Exception:
        return _friendly(False, "Something went wrong — try again.")


def action_library() -> dict:
    try:
        rows = []
        for m in wpe_dashboard.library() or []:
            prompt = (m.get("prompt_text") or "").strip()
            rows.append({
                "world_name": m.get("world_name", ""),
                "level_path": m.get("level_path", ""),
                "prompt_preview": (prompt[:60] + ("…" if len(prompt) > 60 else "")),
                "creation_date": m.get("creation_date", ""),
            })
        return _friendly(True, "ok", worlds=rows)
    except Exception:
        return _friendly(False, "Could not connect — check your setup", worlds=[])


# ---------------------------------------------------------------------------
# Setlist actions — call performance_engine via dashboard wrappers
# ---------------------------------------------------------------------------

def _setlist_snapshot() -> list:
    rows = []
    for i, e in enumerate(performance_engine.STATE.get("setlist") or []):
        rows.append({
            "index": i,
            "name": e.get("name", ""),
            "path": e.get("path", ""),
        })
    return rows


def _saved_setlists() -> list:
    try:
        return list(performance_engine.list_saved_setlists() or [])
    except Exception:
        return []


def action_setlist_add(world_path: str, display_name: str) -> dict:
    try:
        if not world_path:
            return _friendly(False, "Pick a saved world first.")
        performance_engine.add_world_to_setlist(world_path, display_name or world_path)
        return _friendly(True, "Added to setlist.", setlist=_setlist_snapshot(), saved=_saved_setlists())
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_setlist_remove(index: int) -> dict:
    try:
        performance_engine.remove_world_from_setlist(int(index))
        return _friendly(True, "Removed.", setlist=_setlist_snapshot(), saved=_saved_setlists())
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_setlist_move(index: int, direction: str) -> dict:
    try:
        idx = int(index)
        sl = performance_engine.STATE.get("setlist") or []
        if direction == "up":
            to = max(0, idx - 1)
        else:
            to = min(len(sl) - 1, idx + 1)
        if to != idx:
            performance_engine.reorder_setlist(idx, to)
        return _friendly(True, "Reordered.", setlist=_setlist_snapshot(), saved=_saved_setlists())
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_setlist_get() -> dict:
    try:
        return _friendly(True, "ok", setlist=_setlist_snapshot(), saved=_saved_setlists())
    except Exception:
        return _friendly(False, "Could not connect — check your setup", setlist=[], saved=[])


def action_setlist_save(name: str) -> dict:
    try:
        name = (name or "").strip()
        if not name:
            return _friendly(False, "Name your setlist first.")
        if not (performance_engine.STATE.get("setlist") or []):
            return _friendly(False, "Add at least one world to the setlist first.")
        ok = bool(performance_engine.save_setlist(name))
        if ok:
            return _friendly(True, "Setlist saved!", setlist=_setlist_snapshot(), saved=_saved_setlists())
        return _friendly(False, "Could not save setlist — try again.")
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_setlist_load(name: str) -> dict:
    try:
        name = (name or "").strip()
        if not name:
            return _friendly(False, "Pick a setlist to load.")
        ok = bool(performance_engine.load_setlist(name))
        if ok:
            return _friendly(True, "Setlist loaded.", setlist=_setlist_snapshot(), saved=_saved_setlists())
        return _friendly(False, "Could not load that setlist.")
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def _current_and_next_world():
    sl = performance_engine.STATE.get("setlist") or []
    idx = int(performance_engine.STATE.get("current_setlist_index", -1))
    current = ""
    nxt = ""
    if not sl:
        return current, nxt, idx
    if 0 <= idx < len(sl):
        current = sl[idx].get("name", "")
        nxt = sl[(idx + 1) % len(sl)].get("name", "")
    else:
        # Show not advanced yet — next press loads the first world.
        nxt = sl[0].get("name", "")
    return current, nxt, idx


# ---------------------------------------------------------------------------
# Perform actions
# ---------------------------------------------------------------------------

def action_start_show() -> dict:
    try:
        state = _global_state()
        state["mode"] = "performance"
        state["show_running"] = True
        performance_engine.STATE["show_running"] = True
        osc_ok = bool(performance_engine.start_osc_receiver())
        cam = cinematic_camera.start_camera(speed=1200.0, num_points=8, loop=True)
        cam_ok = bool(cam.get("ok"))
        cur, nxt, _idx = _current_and_next_world()
        if not cam_ok:
            return _friendly(
                True,
                "Show started. Camera needs a moment — try New Camera Path.",
                osc=osc_ok, camera=False, show_running=True,
                current_world=cur, next_world=nxt)
        return _friendly(
            True, "Show started — you are live.",
            osc=osc_ok, camera=True, show_running=True,
            current_world=cur, next_world=nxt)
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_next_world() -> dict:
    try:
        sl = performance_engine.STATE.get("setlist") or []
        if not sl:
            return _friendly(False, "Add worlds to your setlist first.")
        ok = bool(performance_engine.load_next_world())
        cur, nxt, _idx = _current_and_next_world()
        if ok:
            return _friendly(True, "Moving to the next world...", current_world=cur, next_world=nxt)
        return _friendly(False, "Could not change worlds — try again.")
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_new_camera_path() -> dict:
    try:
        cinematic_camera.stop_camera()
        path = cinematic_camera.randomize_path(num_points=8)
        if not path.get("ok"):
            return _friendly(False, "Could not build a camera path — try again.")
        cam = cinematic_camera.start_camera(speed=1200.0, num_points=8, loop=True)
        if cam.get("ok"):
            return _friendly(True, "New camera path ready.", camera=True)
        return _friendly(False, "Path ready, but camera could not start — try again.")
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_stop_show() -> dict:
    try:
        state = _global_state()
        state["mode"] = "author"
        state["show_running"] = False
        performance_engine.STATE["show_running"] = False
        try:
            performance_engine.stop_osc_receiver()
        except Exception:
            pass
        try:
            cinematic_camera.stop_camera()
        except Exception:
            pass
        return _friendly(True, "Show stopped.", show_running=False, camera=False)
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def action_status() -> dict:
    """Polling payload for the HTML panel (progress, OSC, meters, lists)."""
    try:
        state = _global_state()
        st = wpe_dashboard.status()
        cam_on = bool(cinematic_camera.STATE.get("playing"))
        osc_active = bool(performance_engine.STATE.get("osc_receiver_active"))
        last_addr = str(performance_engine.STATE.get("last_osc_address") or "")
        ableton_live = osc_active and bool(last_addr)
        show_running = bool(performance_engine.STATE.get("show_running")) or bool(state.get("show_running"))
        cur, nxt, idx = _current_and_next_world()
        params = dict(performance_engine.STATE.get("current_param_values") or {})
        lib = action_library()
        return _friendly(
            True,
            "ok",
            generating=bool(st.get("is_generating")),
            phase=_phase_label(state),
            progress_pct=float(st.get("progress_pct") or 0.0),
            last_prompt=st.get("last_prompt") or "",
            current_world=cur,
            next_world=nxt,
            current_index=idx,
            show_running=show_running,
            osc_active=osc_active,
            ableton_live=ableton_live,
            osc_label=("Ableton Connected" if ableton_live
                       else ("Waiting for Ableton..." if osc_active else "Show not started")),
            camera_on=cam_on,
            params=params,
            worlds=lib.get("worlds") or [],
            setlist=_setlist_snapshot(),
            saved_setlists=_saved_setlists(),
            map_sizes=list(MAP_SIZE_CHOICES.keys()),
            moods=list(MOOD_KEYWORDS.keys()),
            weathers=[w[0] for w in WEATHER_CHOICES],
        )
    except Exception:
        return _friendly(False, "Could not connect — check your setup")


def handle_rpc(op: str, payload: dict = None) -> dict:
    """Main-thread RPC router used by art_engine panel_rpc action."""
    payload = payload or {}
    op = (op or "").strip().lower()
    try:
        if op in ("generate", "action_generate"):
            return action_generate(
                payload.get("prompt", ""),
                payload.get("map_size", "Medium"),
                payload.get("mood", "Ethereal & Beautiful"),
                payload.get("weather", "Blood Moon"),
            )
        if op in ("save_world", "action_save_world"):
            return action_save_world(payload.get("world_name", ""))
        if op in ("library", "action_library"):
            return action_library()
        if op == "setlist_add":
            return action_setlist_add(payload.get("path", ""), payload.get("name", ""))
        if op == "setlist_remove":
            return action_setlist_remove(int(payload.get("index", -1)))
        if op == "setlist_move":
            return action_setlist_move(int(payload.get("index", 0)), payload.get("direction", "up"))
        if op == "setlist_get":
            return action_setlist_get()
        if op == "setlist_save":
            return action_setlist_save(payload.get("name", ""))
        if op == "setlist_load":
            return action_setlist_load(payload.get("name", ""))
        if op == "start_show":
            return action_start_show()
        if op == "next_world":
            return action_next_world()
        if op == "new_camera_path":
            return action_new_camera_path()
        if op == "stop_show":
            return action_stop_show()
        if op in ("status", "action_status"):
            return action_status()
        return _friendly(False, "Something went wrong — try again.")
    except Exception:
        return _friendly(False, "Something went wrong — try again.")


# ---------------------------------------------------------------------------
# EUW asset + dock
# ---------------------------------------------------------------------------

def ensure_euw_asset(force_recreate: bool = False) -> bool:
    """Create EUW_WPE_Main parented to WPEMainPanelWidget (WebBrowser host)."""
    if not _HAS_UNREAL:
        return False
    try:
        host = None
        try:
            host = unreal.load_class(None, "/Script/WorldPromptEngineEditor.WPEMainPanelWidget")
        except Exception:
            host = None

        if unreal.EditorAssetLibrary.does_asset_exist(EUW_PATH):
            if not force_recreate:
                # ParentClass is protected on EditorUtilityWidgetBlueprint — do not read it.
                # Verify by checking the generated widget class ancestry when possible.
                if host is not None:
                    try:
                        gen = unreal.load_class(None, EUW_PATH + ".EUW_WPE_Main_C")
                        if gen is not None and unreal.SystemLibrary.is_child_of(gen, host):
                            return True
                        # Generated class missing or wrong — recreate below.
                        _log("EUW generated class missing/wrong parent; recreating")
                        unreal.EditorAssetLibrary.delete_asset(EUW_PATH)
                    except Exception:
                        return True
                else:
                    return True
            else:
                unreal.EditorAssetLibrary.delete_asset(EUW_PATH)

        if not unreal.EditorAssetLibrary.does_directory_exist(EUW_DIR):
            unreal.EditorAssetLibrary.make_directory(EUW_DIR)

        factory = unreal.EditorUtilityWidgetBlueprintFactory()
        try:
            factory.set_editor_property("edit_after_new", False)
        except Exception:
            pass

        parent = host if host is not None else unreal.EditorUtilityWidget
        try:
            factory.set_editor_property("parent_class", parent)
        except Exception:
            try:
                factory.set_editor_property("ParentClass", parent)
            except Exception:
                pass

        tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset = tools.create_asset("EUW_WPE_Main", EUW_DIR, unreal.EditorUtilityWidgetBlueprint, factory)
        if asset is None:
            _log("EUW create returned None")
            return False
        unreal.EditorAssetLibrary.save_asset(EUW_PATH)
        _log("created {} parent={}".format(EUW_PATH, "WPEMainPanelWidget" if host else "EditorUtilityWidget"))
        return True
    except Exception as e:
        _log("ensure_euw_asset: {}".format(e))
        return False


def open_panel() -> dict:
    """Dock EUW_WPE_Main as an editor tab. Safe to call repeatedly."""
    global _TAB_ID
    if not _HAS_UNREAL:
        return _friendly(False, "Editor not available.")
    try:
        ensure_euw_asset()
        if not unreal.EditorAssetLibrary.does_asset_exist(EUW_PATH):
            # Fallback: open HTML in default browser so the artist is never stuck.
            html = _html_path()
            if os.path.isfile(html):
                try:
                    import webbrowser
                    webbrowser.open("file://" + html)
                except Exception:
                    pass
            return _friendly(False, "Panel is opening in your browser.")

        bp = unreal.EditorAssetLibrary.load_asset(EUW_PATH)
        eus = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        # Prefer id-returning API.
        try:
            widget, tab_id = eus.spawn_and_register_tab_and_get_id(bp)
            _TAB_ID = tab_id
        except Exception:
            widget = eus.spawn_and_register_tab(bp)
            _TAB_ID = "EUW_WPE_Main"
        # If C++ host exposes LoadPanelHtml, call it.
        try:
            if widget is not None and hasattr(widget, "load_panel_html"):
                widget.load_panel_html(_html_path())
            elif widget is not None and hasattr(widget, "LoadPanelHtml"):
                widget.LoadPanelHtml(_html_path())
        except Exception:
            pass
        _ensure_status_tick()
        return _friendly(True, "Panel ready.", tab_id=str(_TAB_ID))
    except Exception:
        return _friendly(False, "Something went wrong — try again.")


def _status_tick(_dt):
    # Keep GLOBAL_STATE phase labels fresh for any listeners.
    try:
        state = _global_state()
        if state.get("is_generating"):
            state["current_phase"] = _phase_label(state)
        elif float(state.get("progress") or 0.0) >= 1.0 and state.get("last_prompt"):
            if state.get("current_phase") not in ("Done!",):
                state["current_phase"] = "Done!"
    except Exception:
        pass


def _ensure_status_tick():
    global _TICK_HANDLE
    if not _HAS_UNREAL:
        return
    if _TICK_HANDLE is None and hasattr(unreal, "register_slate_post_tick_callback"):
        _TICK_HANDLE = unreal.register_slate_post_tick_callback(_status_tick)


def initialize():
    """Called from init_unreal after other systems boot — auto-open the panel."""
    try:
        ensure_euw_asset()
        open_panel()
        _log("guided panel initialized")
    except Exception as e:
        _log("initialize failed: {}".format(e))
