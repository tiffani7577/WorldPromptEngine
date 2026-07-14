"""
init_unreal.py — WorldPromptEngine plugin entry point (UE 5.8.0)

Auto-executed by PythonScriptPlugin at editor startup (PostEngineInit).

Wiring:
  - GLOBAL_STATE: thread-safe shared state (deque command queue + flags).
  - utility_bridge WebSocket server on a background daemon thread
    (never touches unreal APIs).
  - Slate post-tick callback registered on the MAIN thread that drains the
    queue and advances frame-budgeted generation tasks via art_engine.
"""

import collections
import threading

import unreal

import art_engine
import content_library
import editor_menu
import native_bridge
import utility_bridge
import world_builder_actor


# ---------------------------------------------------------------------------
# Global thread-safe state
# ---------------------------------------------------------------------------

GLOBAL_STATE = {
    # deque append/popleft are GIL-atomic => safe producer(bg)/consumer(main)
    "command_queue": collections.deque(),
    "is_generating": False,
    "progress": 0.0,
    "active_task": None,            # generator being advanced each frame
    "temporary_actors": [],         # actors spawned via bridge commands
    "current_landscapes": [],       # landscape actor references
    "last_landscape_bounds": [],
    "last_heightmap_asset": None,
    "landscape_subsystem": None,
    "last_parse": None,             # last prompt_matrix.parse_prompt result
    "pcg_spawn_table": [],          # resolved asset_manifest entries
    "last_slope_map": None,         # per-pixel material layer indices
    "slope_layer_names": [],
    "last_weightmaps": None,        # grass/rock/snow weightmaps + paths
    "last_material_summary": None,
    "moisture": 0.5,                # prompt-derived moisture for erosion/PCG
    "pcg_volume": None,
    "last_pcg_summary": None,
    "pcg_density": 0.0,
    "biome_regions": None,
    "biome_mask_summary": None,
    "last_routes": None,
    "spline_actors": [],
    "hism_actors": [],
    "last_atmosphere": None,
    "structure_plan": [],           # resolved structure types for last prompt
    "structure_actors": [],         # spawned structure actors
    "last_structure_summary": None,
    "kit_actors": [],               # spawned user-kit (Fab) meshes
    "last_kit_summary": None,
}

_TICK_HANDLE = None
_BRIDGE_THREAD = None


# ---------------------------------------------------------------------------
# Main-thread post-tick pump
# ---------------------------------------------------------------------------

def _post_tick(delta_seconds: float):
    """Runs on the game/main thread every Slate tick."""
    try:
        art_engine.consume_queue_tick(GLOBAL_STATE, delta_seconds)
    except Exception as e:
        unreal.log_error("WorldPromptEngine._post_tick failed: {}".format(e))



def _force_mac_editor_visible():
    """Mac: recover when Level Editor opens off-space after monitor changes."""
    try:
        world = None
        try:
            world = unreal.EditorLevelLibrary.get_editor_world()
        except Exception:
            world = None
        # Console commands that reload a known-good single-window layout
        for cmd in (
            "LoadDefaultLayout",
            "Editor.LoadDefaultLayout",
            "MainFrame.LoadDefaultLayout",
        ):
            try:
                unreal.SystemLibrary.execute_console_command(world, cmd)
                unreal.log("WorldPromptEngine: tried {}".format(cmd))
            except Exception:
                pass
    except Exception as e:
        unreal.log_warning("WorldPromptEngine: mac window recover failed: {}".format(e))


_MAC_VISIBLE_FRAMES = {"n": 0}

def _mac_visible_tick(delta_seconds: float):
    try:
        _MAC_VISIBLE_FRAMES["n"] += 1
        # Run once ~2s after editor is up
        if _MAC_VISIBLE_FRAMES["n"] == 120:
            _force_mac_editor_visible()
    except Exception:
        pass


def _register_tick():
    global _TICK_HANDLE
    try:
        if hasattr(unreal, "register_slate_post_tick_callback"):
            _TICK_HANDLE = unreal.register_slate_post_tick_callback(_post_tick)
            unreal.register_slate_post_tick_callback(_mac_visible_tick)
            unreal.log("WorldPromptEngine: Slate post-tick callback registered")
        else:
            unreal.log_error("WorldPromptEngine: register_slate_post_tick_callback unavailable")
    except Exception as e:
        unreal.log_error("WorldPromptEngine._register_tick failed: {}".format(e))


def _unregister_tick():
    global _TICK_HANDLE
    try:
        if _TICK_HANDLE is not None and hasattr(unreal, "unregister_slate_post_tick_callback"):
            unreal.unregister_slate_post_tick_callback(_TICK_HANDLE)
            _TICK_HANDLE = None
            unreal.log("WorldPromptEngine: Slate post-tick callback unregistered")
    except Exception as e:
        unreal.log_error("WorldPromptEngine._unregister_tick failed: {}".format(e))


# ---------------------------------------------------------------------------
# Background WebSocket bridge thread
# ---------------------------------------------------------------------------

def _start_bridge_thread():
    global _BRIDGE_THREAD
    try:
        if _BRIDGE_THREAD is not None and _BRIDGE_THREAD.is_alive():
            unreal.log_warning("WorldPromptEngine: bridge thread already running")
            return
        _BRIDGE_THREAD = threading.Thread(
            target=utility_bridge.run_server,
            args=(GLOBAL_STATE,),
            name="WPE_WebSocketBridge",
            daemon=True,
        )
        _BRIDGE_THREAD.start()
        unreal.log("WorldPromptEngine: WebSocket bridge daemon thread started (port {})".format(
            utility_bridge.WS_PORT))
    except Exception as e:
        unreal.log_error("WorldPromptEngine._start_bridge_thread failed: {}".format(e))


# ---------------------------------------------------------------------------
# Public convenience API (usable from the UE Python console)
# ---------------------------------------------------------------------------

def generate(width=505, height=505, seed=1337, octaves=6, frequency=0.004,
             persistence=0.5, lacunarity=2.0, amplitude=1.0, noise="perlin",
             destination=None):
    """
    Kick off a frame-budgeted heightmap generation directly from the
    Python console:  import init_unreal; init_unreal.generate(seed=42)
    """
    try:
        if destination is None:
            destination = content_library.heightmap_destination()
        GLOBAL_STATE["command_queue"].append({
            "action": "generate_heightmap",
            "params": {
                "width": width, "height": height, "seed": seed,
                "octaves": octaves, "frequency": frequency,
                "persistence": persistence, "lacunarity": lacunarity,
                "amplitude": amplitude, "noise": noise,
                "destination": destination,
            },
        })
        unreal.log("WorldPromptEngine: generation queued ({}x{}, seed {})".format(width, height, seed))
    except Exception as e:
        unreal.log_error("WorldPromptEngine.generate failed: {}".format(e))


def prompt(text: str, width=505, height=505, seed=1337):
    """
    Natural language world generation from the Python console:
      init_unreal.prompt("misty alpine peaks at golden hour")
    """
    try:
        GLOBAL_STATE["command_queue"].append({
            "action": "generate_from_prompt",
            "prompt": text,
            "params": {
                "width": width,
                "height": height,
                "seed": seed,
                "destination": content_library.heightmap_destination(),
            },
        })
        unreal.log("WorldPromptEngine: prompt queued: '{}'".format(text))
    except Exception as e:
        unreal.log_error("WorldPromptEngine.prompt failed: {}".format(e))


def setup_content(root: str = None):
    """
    Create the per-build content folders inside Unreal's Content Browser.

      init_unreal.setup_content()
      init_unreal.setup_content("/Game/Builds/Forest_01")
    """
    try:
        return content_library.setup_content(root=root)
    except Exception as e:
        unreal.log_error("WorldPromptEngine.setup_content failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def use_folder(name: str, where: str = None):
    """
    Tell the plugin which Content folder to use — just the name (+ optional where).

      init_unreal.use_folder("Forest_01")
      init_unreal.use_folder("Forest_01", where="/Game/Builds")
      init_unreal.use_folder("Forest_01", where="Builds")
      init_unreal.use_folder("/Game/Builds/Forest_01")

    It finds that folder in the Content Browser (or creates it), then routes
    all mesh lookups through it for this project.
    """
    try:
        return content_library.use_folder(name, where=where)
    except Exception as e:
        unreal.log_error("WorldPromptEngine.use_folder failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def find_folder(name: str, where: str = None):
    """Search for a Content folder by name without switching to it yet."""
    try:
        return content_library.find_folder(name, where=where)
    except Exception as e:
        unreal.log_error("WorldPromptEngine.find_folder failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def set_content_root(root: str):
    """
    Point this project at a different /Game/... folder for meshes.

      init_unreal.set_content_root("/Game/Builds/Desert_A")
    """
    try:
        return content_library.set_content_root(root, setup=True)
    except Exception as e:
        unreal.log_error("WorldPromptEngine.set_content_root failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def content_status() -> dict:
    """Show active content root + which manifest assets are still missing."""
    try:
        return content_library.content_status()
    except Exception as e:
        unreal.log_error("WorldPromptEngine.content_status failed: {}".format(e))
        return {}


def place_builder():
    """
    Drop a WorldPromptBuilder into the level (Base-X style).

    Select it → Details → type prompt → click Generate World.
    Also available: Tools → World Prompt Engine → Place Builder In Level
    """
    try:
        return world_builder_actor.place_builder()
    except Exception as e:
        unreal.log_error("WorldPromptEngine.place_builder failed: {}".format(e))
        return None


def build_huge_world(extent_km: float = 16.0):
    """
    Native C++ path: plan a World Partition-scale tiled world.

      init_unreal.build_huge_world(64)  # 64km
    """
    try:
        result = native_bridge.build_world_plan(extent_km=extent_km)
        unreal.log("WorldPromptEngine huge plan: {}".format(result))
        return result
    except Exception as e:
        unreal.log_error("WorldPromptEngine.build_huge_world failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def preforge_structures(force: bool = False):
    """
    Bake the six structure_forge family meshes (Geometry Script if available).

      init_unreal.preforge_structures()
    """
    try:
        import structure_forge
        return structure_forge.preforge_all_families(force=force)
    except Exception as e:
        unreal.log_error("WorldPromptEngine.preforge_structures failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def capture_selected_as_kit(kit_name: str = None):
    """
    Select Fab StaticMeshes in Content Browser, then:

      init_unreal.capture_selected_as_kit('MyFabKit')

    Creates /Game/WPE/Kits/<name> and uses it on generate_world.
    """
    try:
        import kit_library
        return kit_library.capture_selected_as_kit(kit_name=kit_name)
    except Exception as e:
        unreal.log_error("WorldPromptEngine.capture_selected_as_kit failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def setup_landscape_material(force: bool = False):
    """
    Auto-create Grass/Rock/Snow landscape material and assign it.

      init_unreal.setup_landscape_material()
    """
    try:
        import landscape_auto_setup
        result = landscape_auto_setup.ensure_landscape_material_stack(
            force_rebuild=force, assign=True)
        unreal.log("WorldPromptEngine.setup_landscape_material: {}".format(result))
        return result
    except Exception as e:
        unreal.log_error("WorldPromptEngine.setup_landscape_material failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def demo_alpine():
    import demo_presets
    return demo_presets.run_alpine()


def demo_underwater():
    import demo_presets
    return demo_presets.run_underwater()


def demo_desert():
    import demo_presets
    return demo_presets.run_desert()


def open_ui():
    """
    Open the clickable WorldPromptEngine control panel in your browser.

    Easier than the Python console — type a prompt, click Generate.
    Unreal must stay open so the panel can talk to ws://127.0.0.1:3001.
    """
    import os
    try:
        import webbrowser
    except Exception:
        webbrowser = None

    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, "wpe_panel.html"))
    except Exception:
        pass
    try:
        if hasattr(unreal, "Paths") and hasattr(unreal.Paths, "project_dir"):
            candidates.append(os.path.join(
                unreal.Paths.project_dir(), "tools", "wpe_panel.html"))
    except Exception:
        pass

    path = None
    for c in candidates:
        if c and os.path.isfile(c):
            path = c
            break

    if not path:
        unreal.log_error("WorldPromptEngine.open_ui: wpe_panel.html not found")
        return {"ok": False, "error": "wpe_panel.html not found"}

    url = "file://" + path.replace(" ", "%20")
    try:
        if webbrowser is not None:
            webbrowser.open(url)
        elif hasattr(unreal, "SystemLibrary"):
            # fallback: log the path for manual open
            pass
        unreal.log("WorldPromptEngine: opened UI -> {}".format(path))
        unreal.log("WorldPromptEngine: keep the editor open; panel uses ws://127.0.0.1:3001")
        return {"ok": True, "path": path, "url": url}
    except Exception as e:
        unreal.log_error("WorldPromptEngine.open_ui failed: {}".format(e))
        return {"ok": False, "error": str(e), "path": path}


def status() -> dict:
    """Return a snapshot of engine state for debugging."""
    try:
        snap = {
            "is_generating": GLOBAL_STATE["is_generating"],
            "progress": GLOBAL_STATE["progress"],
            "queue_depth": len(GLOBAL_STATE["command_queue"]),
            "temp_actors": len(GLOBAL_STATE["temporary_actors"]),
            "has_active_task": GLOBAL_STATE["active_task"] is not None,
            "content_root": content_library.content_root(),
            "heightmap_destination": content_library.heightmap_destination(),
        }
        return snap
    except Exception as e:
        unreal.log_error("WorldPromptEngine.status failed: {}".format(e))
        return {}


def shutdown():
    """Manual teardown (tick unregister). Daemon thread dies with the editor."""
    _unregister_tick()


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

def _boot():
    try:
        unreal.log("WorldPromptEngine v1.0.0 initializing (UE 5.8.0 target)...")
        art_engine  # imported above; touch to satisfy linters
        _register_tick()
        _start_bridge_thread()
        cfg = content_library.load_config()
        if cfg.get("auto_setup_on_boot", True):
            content_library.setup_content()
        editor_menu.register_menus()
        # Touch the uclass so Unreal registers WorldPromptBuilder for spawning
        _ = world_builder_actor.WorldPromptBuilder
        unreal.log(
            "WorldPromptEngine: online. EASIEST → Tools → World Prompt Engine → Place Builder In Level. "
            "NATIVE SCALE → {} | content_root={} | ws://127.0.0.1:{}".format(
                native_bridge.scale_summary(),
                content_library.content_root(),
                utility_bridge.WS_PORT))
    except Exception as e:
        unreal.log_error("WorldPromptEngine._boot failed: {}".format(e))


_boot()
