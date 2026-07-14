"""
performance_engine.py — WorldPromptEngine Performance Mode (UE 5.8).

Live show playback system. Architecturally isolated from world authoring:
NO generation code is called here. Pre-built worlds only.

- OSC receiver on port 8000 (Unreal built-in OSC plugin, with a pure-Python
  UDP fallback if OSC plugin bindings are unavailable).
- Per-parameter EnvelopeFollower smoothing (fast attack, slow release).
- Tick-based live parameter application to fog / lights / MPC / Niagara.
  NiagaraActors using NS_WPE_* under /Game/WorldPromptEngine/VFX/ respond to
  OSC highs via User.SpawnRateMultiplier (0.5 + 1.5 * highs).
- Non-blocking fog-in / load / fog-out world transitions (tick generators).
- Setlist management with JSON persistence.
"""

import json
import os
import socket
import struct
import threading
import time

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    unreal = None
    _HAS_UNREAL = False

import world_library

OSC_PORT = 8000
TICK_RATE = 60.0
TRANSITION_TICKS = 120          # 2.0s at 60fps
TRANSITION_FOG_DENSITY = 5.0
KICK_DECAY_TICKS = 18           # 0.3s at 60fps

PARAM_NAMES = ("energy", "bass", "mids", "highs", "kick", "vocal")

STATE = {
    "setlist": [],                  # [{"path":..., "name":...}]
    "current_setlist_index": -1,
    "osc_receiver_active": False,
    "osc_server": None,             # unreal OSC server object or fallback thread
    "osc_fallback_socket": None,
    "last_osc_address": "",
    "last_osc_value": 0.0,
    "last_scene_trigger": "",
    "targets": {n: 0.0 for n in PARAM_NAMES},   # raw incoming values
    "current_param_values": {n: 0.0 for n in PARAM_NAMES},
    "kick_ticks_remaining": 0,
    "transition_active": False,
    "pending_scene": None,          # queued scene change from OSC thread
    "actor_cache": {},
    "base_values": {},
    "live_tick_handle": None,
    "transition_tick_handle": None,
    "transition_gen": None,
    "show_running": False,
}


def _log(msg):
    if _HAS_UNREAL:
        unreal.log("[WorldPromptEngine][Perf] {}".format(msg))
    else:
        print(msg)


def _log_error(msg):
    if _HAS_UNREAL:
        unreal.log_error("[WorldPromptEngine][Perf] {}".format(msg))
    else:
        print("ERROR:", msg)


# ---------------------------------------------------------------------------
# Envelope follower
# ---------------------------------------------------------------------------

class EnvelopeFollower(object):
    """Attack/release smoothing so parameter motion feels musical."""

    def __init__(self, attack_time=0.05, release_time=0.8, sample_rate=TICK_RATE):
        self.current_value = 0.0
        self.attack_time = max(1e-4, float(attack_time))
        self.release_time = max(1e-4, float(release_time))
        self.sample_rate = max(1.0, float(sample_rate))

    def process(self, target_value):
        try:
            target = float(target_value)
            if target > self.current_value:
                coef = 1.0 - pow(0.01, 1.0 / (self.attack_time * self.sample_rate))
            else:
                coef = 1.0 - pow(0.01, 1.0 / (self.release_time * self.sample_rate))
            self.current_value += (target - self.current_value) * coef
            if abs(self.current_value - target) < 1e-5:
                self.current_value = target
            return self.current_value
        except Exception as e:
            _log_error("EnvelopeFollower.process: {}".format(e))
            return self.current_value


_ENVELOPES = {n: EnvelopeFollower() for n in PARAM_NAMES}
# Kick wants near-instant attack
_ENVELOPES["kick"] = EnvelopeFollower(attack_time=0.005, release_time=0.25)


# ---------------------------------------------------------------------------
# Actor cache
# ---------------------------------------------------------------------------

def _find_actor_of_class(cls):
    try:
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
        for a in actors:
            if isinstance(a, cls):
                return a
    except Exception as e:
        _log_error("_find_actor_of_class: {}".format(e))
    return None


def _refresh_actor_cache(force=False):
    """Cache scene actor references. Re-run after each world load."""
    try:
        if not _HAS_UNREAL:
            return
        cache = STATE["actor_cache"]
        if cache and not force:
            return
        cache.clear()
        cache["fog"] = _find_actor_of_class(unreal.ExponentialHeightFog)
        cache["sun"] = _find_actor_of_class(unreal.DirectionalLight)
        cache["ppv"] = _find_actor_of_class(unreal.PostProcessVolume)
        cache["niagara"] = []
        try:
            if hasattr(unreal, "NiagaraActor"):
                for a in unreal.EditorLevelLibrary.get_all_level_actors():
                    if isinstance(a, unreal.NiagaraActor):
                        cache["niagara"].append(a)
        except Exception:
            pass
        # Record base values so live modulation is relative, not absolute.
        base = STATE["base_values"]
        base.clear()
        try:
            fog = cache.get("fog")
            if fog is not None:
                comp = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
                if comp is not None:
                    base["fog_density"] = float(comp.get_editor_property("fog_density"))
                    cache["fog_comp"] = comp
        except Exception as e:
            _log_error("cache fog base: {}".format(e))
        try:
            sun = cache.get("sun")
            if sun is not None:
                comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
                if comp is not None:
                    base["sun_intensity"] = float(comp.get_editor_property("intensity"))
                    cache["sun_comp"] = comp
        except Exception as e:
            _log_error("cache sun base: {}".format(e))
        _log("actor cache refreshed: fog={} sun={} ppv={} niagara={}".format(
            cache.get("fog") is not None, cache.get("sun") is not None,
            cache.get("ppv") is not None, len(cache.get("niagara") or [])))
    except Exception as e:
        _log_error("_refresh_actor_cache: {}".format(e))


def _set_mpc_scalar(name, value):
    """Write a scalar into the WPE material parameter collection if present."""
    try:
        if not hasattr(unreal, "MaterialParameterCollection"):
            return
        mpc_path = "/Game/WPE/Materials/MPC_WPE_World"
        if not unreal.EditorAssetLibrary.does_asset_exist(mpc_path):
            return
        mpc = unreal.EditorAssetLibrary.load_asset(mpc_path)
        world = unreal.EditorLevelLibrary.get_editor_world()
        if mpc is not None and world is not None and hasattr(unreal, "MaterialParameterCollectionFunctionLibrary"):
            unreal.MaterialParameterCollectionFunctionLibrary.set_scalar_parameter_value(
                world, mpc, name, float(value))
    except Exception:
        # Parameter may not exist in the collection; stay silent per-tick.
        pass


# ---------------------------------------------------------------------------
# OSC receiver — Unreal OSC plugin first, pure-Python UDP fallback
# ---------------------------------------------------------------------------

def _handle_osc(address, value):
    """Route one OSC message. Safe to call from any thread — scene changes
    are queued and executed on the main tick."""
    try:
        STATE["last_osc_address"] = address
        try:
            STATE["last_osc_value"] = float(value)
        except (TypeError, ValueError):
            STATE["last_osc_value"] = 0.0

        if address.startswith("/music/"):
            name = address[len("/music/"):]
            if name in STATE["targets"]:
                v = max(0.0, min(1.0, STATE["last_osc_value"]))
                STATE["targets"][name] = v
                if name == "kick" and v >= 0.5:
                    STATE["kick_ticks_remaining"] = KICK_DECAY_TICKS
        elif address == "/scene/next":
            STATE["pending_scene"] = "next"
            STATE["last_scene_trigger"] = "/scene/next"
        elif address.startswith("/scene/"):
            tail = address[len("/scene/"):]
            try:
                idx = int(tail)
                STATE["pending_scene"] = idx
                STATE["last_scene_trigger"] = address
            except ValueError:
                pass
    except Exception as e:
        _log_error("_handle_osc: {}".format(e))


def _parse_osc_packet(data):
    """Minimal OSC 1.0 parser: address + first float/int argument."""
    try:
        if not data or data[0:1] != b"/":
            return None, None
        # address string, null-padded to 4 bytes
        end = data.index(b"\x00")
        address = data[:end].decode("utf-8", "replace")
        pos = (end + 4) & ~3
        if pos >= len(data) or data[pos:pos + 1] != b",":
            return address, 1.0
        tend = data.index(b"\x00", pos)
        typetags = data[pos + 1:tend].decode("ascii", "replace")
        apos = (tend + 4) & ~3
        for tag in typetags:
            if tag == "f":
                return address, struct.unpack(">f", data[apos:apos + 4])[0]
            if tag == "i":
                return address, float(struct.unpack(">i", data[apos:apos + 4])[0])
            if tag in ("d",):
                return address, struct.unpack(">d", data[apos:apos + 8])[0]
            if tag == "T":
                return address, 1.0
            if tag == "F":
                return address, 0.0
        return address, 1.0
    except Exception:
        return None, None


def _fallback_udp_loop(sock):
    _log("OSC fallback UDP receiver listening on port {}".format(OSC_PORT))
    while STATE["osc_receiver_active"]:
        try:
            sock.settimeout(0.5)
            data, _addr = sock.recvfrom(4096)
            # Handle OSC bundles crudely: scan for element packets
            if data.startswith(b"#bundle"):
                pos = 16
                while pos + 4 <= len(data):
                    (size,) = struct.unpack(">i", data[pos:pos + 4])
                    pos += 4
                    if size <= 0 or pos + size > len(data):
                        break
                    addr, val = _parse_osc_packet(data[pos:pos + size])
                    if addr:
                        _handle_osc(addr, val)
                    pos += size
            else:
                addr, val = _parse_osc_packet(data)
                if addr:
                    _handle_osc(addr, val)
        except socket.timeout:
            continue
        except OSError:
            break
        except Exception as e:
            _log_error("fallback UDP loop: {}".format(e))
    try:
        sock.close()
    except Exception:
        pass
    _log("OSC fallback receiver stopped")


def start_osc_receiver():
    """Start the OSC server on port 8000. Prefers Unreal's OSC plugin."""
    try:
        if STATE["osc_receiver_active"]:
            _log("OSC receiver already active")
            return True

        if _HAS_UNREAL and hasattr(unreal, "OSCManager"):
            try:
                server = unreal.OSCManager.create_osc_server(
                    "0.0.0.0", OSC_PORT, False, True, "WPE_OSC_Server", None)
                if server is not None:
                    def _on_message(message, ip, port):
                        try:
                            addr = str(unreal.OSCManager.get_osc_message_address(message).get_full_path())
                            floats = unreal.OSCManager.get_all_floats(message)
                            val = float(floats[0]) if floats else 1.0
                            _handle_osc(addr, val)
                        except Exception as e:
                            _log_error("OSC dispatch: {}".format(e))
                    try:
                        server.on_osc_message_received.add_callable(_on_message)
                    except Exception:
                        server.on_message_received_event.add_callable(_on_message)
                    if hasattr(server, "listen"):
                        server.listen()
                    STATE["osc_server"] = server
                    STATE["osc_receiver_active"] = True
                    _ensure_live_tick()
                    _log("Unreal OSC server listening on port {}".format(OSC_PORT))
                    return True
            except Exception as e:
                _log_error("Unreal OSC plugin path failed, falling back to UDP: {}".format(e))

        # Pure-Python fallback (background daemon thread, never touches unreal)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", OSC_PORT))
        STATE["osc_fallback_socket"] = sock
        STATE["osc_receiver_active"] = True
        t = threading.Thread(target=_fallback_udp_loop, args=(sock,), daemon=True)
        t.start()
        _ensure_live_tick()
        return True
    except Exception as e:
        _log_error("start_osc_receiver: {}".format(e))
        STATE["osc_receiver_active"] = False
        return False


def stop_osc_receiver():
    try:
        STATE["osc_receiver_active"] = False
        server = STATE.get("osc_server")
        if server is not None:
            try:
                if hasattr(server, "stop"):
                    server.stop()
                if _HAS_UNREAL and hasattr(unreal, "OSCManager"):
                    unreal.OSCManager.destroy_osc_server(server)
            except Exception as e:
                _log_error("stop_osc_receiver server: {}".format(e))
            STATE["osc_server"] = None
        sock = STATE.get("osc_fallback_socket")
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
            STATE["osc_fallback_socket"] = None
        _log("OSC receiver stopped")
        return True
    except Exception as e:
        _log_error("stop_osc_receiver: {}".format(e))
        return False


# ---------------------------------------------------------------------------
# Live parameter application (main-thread tick)
# ---------------------------------------------------------------------------

def apply_live_params():
    """Smooth targets through envelopes and apply to cached scene actors."""
    try:
        if not _HAS_UNREAL:
            return
        _refresh_actor_cache()
        vals = STATE["current_param_values"]
        for name in PARAM_NAMES:
            vals[name] = _ENVELOPES[name].process(STATE["targets"][name])

        cache = STATE["actor_cache"]
        base = STATE["base_values"]

        # energy -> fog density blend + vignette
        fog_comp = cache.get("fog_comp")
        if fog_comp is not None and not STATE["transition_active"]:
            try:
                bd = base.get("fog_density", 0.02)
                fog_comp.set_editor_property(
                    "fog_density", bd + (bd * 1.5) * vals["energy"])
            except Exception:
                pass
        ppv = cache.get("ppv")
        if ppv is not None:
            try:
                settings = ppv.get_editor_property("settings")
                settings.set_editor_property("override_vignette_intensity", True)
                settings.set_editor_property("vignette_intensity", 0.4 * vals["energy"])
                # vocal -> ambient occlusion intensity
                settings.set_editor_property("override_ambient_occlusion_intensity", True)
                settings.set_editor_property(
                    "ambient_occlusion_intensity", 0.5 + 0.5 * vals["vocal"])
                ppv.set_editor_property("settings", settings)
            except Exception:
                pass

        # bass + kick -> directional light intensity
        sun_comp = cache.get("sun_comp")
        if sun_comp is not None:
            try:
                bi = base.get("sun_intensity", 10.0)
                intensity = bi * (1.0 + vals["bass"] * 0.6)
                if STATE["kick_ticks_remaining"] > 0:
                    k = STATE["kick_ticks_remaining"] / float(KICK_DECAY_TICKS)
                    intensity = max(intensity, bi * (1.0 + 1.5 * k))
                    STATE["kick_ticks_remaining"] -= 1
                sun_comp.set_editor_property("intensity", intensity)
            except Exception:
                pass

        # vocal -> fog inscattering color saturation shift
        if fog_comp is not None:
            try:
                c = fog_comp.get_editor_property("fog_inscattering_luminance")
                lum = (c.r + c.g + c.b) / 3.0
                s = vals["vocal"]
                fog_comp.set_editor_property(
                    "fog_inscattering_luminance",
                    unreal.LinearColor(
                        lum + (c.r - lum) * (1.0 + s),
                        lum + (c.g - lum) * (1.0 + s),
                        lum + (c.b - lum) * (1.0 + s), c.a))
            except Exception:
                pass

        # material parameter collection channels
        _set_mpc_scalar("WPE_EmissiveBoost", vals["bass"])
        _set_mpc_scalar("WPE_MidShimmer", vals["mids"])
        _set_mpc_scalar("WPE_Sparkle", vals["highs"])

        # highs -> Niagara spawn rate multiplier
        for na in cache.get("niagara") or []:
            try:
                comp = na.get_component_by_class(unreal.NiagaraComponent)
                if comp is not None:
                    comp.set_variable_float("User.SpawnRateMultiplier",
                                            0.5 + 1.5 * vals["highs"])
            except Exception:
                pass
    except Exception as e:
        _log_error("apply_live_params: {}".format(e))


def _live_tick(_delta):
    try:
        apply_live_params()
        pending = STATE.get("pending_scene")
        if pending is not None and not STATE["transition_active"]:
            STATE["pending_scene"] = None
            if pending == "next":
                load_next_world()
            else:
                load_world_at_index(int(pending))
    except Exception as e:
        _log_error("_live_tick: {}".format(e))


def _ensure_live_tick():
    try:
        if not _HAS_UNREAL:
            return
        if STATE["live_tick_handle"] is None and hasattr(unreal, "register_slate_post_tick_callback"):
            STATE["live_tick_handle"] = unreal.register_slate_post_tick_callback(_live_tick)
            _log("live parameter tick registered")
    except Exception as e:
        _log_error("_ensure_live_tick: {}".format(e))


def stop_live_tick():
    try:
        if STATE["live_tick_handle"] is not None:
            unreal.unregister_slate_post_tick_callback(STATE["live_tick_handle"])
            STATE["live_tick_handle"] = None
    except Exception as e:
        _log_error("stop_live_tick: {}".format(e))


# ---------------------------------------------------------------------------
# World transition system (never blocks)
# ---------------------------------------------------------------------------

def _transition_generator(target_path, target_index, target_name):
    """Tick-counted generator: fog in (120t) -> load -> fog out (120t)."""
    fog_comp = STATE["actor_cache"].get("fog_comp")
    start_density = 0.02
    try:
        if fog_comp is not None:
            start_density = float(fog_comp.get_editor_property("fog_density"))
    except Exception:
        pass

    # Phase 1: fog fade in
    for t in range(TRANSITION_TICKS):
        alpha = (t + 1) / float(TRANSITION_TICKS)
        try:
            if fog_comp is not None:
                fog_comp.set_editor_property(
                    "fog_density",
                    start_density + (TRANSITION_FOG_DENSITY - start_density) * alpha)
        except Exception:
            pass
        yield

    # Phase 2: load target level
    ok = world_library.load_world(target_path)
    if ok:
        STATE["current_setlist_index"] = target_index
        _log("transition loaded '{}' (index {})".format(target_name, target_index))
    else:
        _log_error("transition failed to load '{}'".format(target_path))
    # New level: recache actors, grab new fog
    _refresh_actor_cache(force=True)
    fog_comp = STATE["actor_cache"].get("fog_comp")
    end_density = STATE["base_values"].get("fog_density", 0.02)
    try:
        if fog_comp is not None:
            fog_comp.set_editor_property("fog_density", TRANSITION_FOG_DENSITY)
    except Exception:
        pass
    yield

    # Phase 3: fog fade out
    for t in range(TRANSITION_TICKS):
        alpha = (t + 1) / float(TRANSITION_TICKS)
        try:
            if fog_comp is not None:
                fog_comp.set_editor_property(
                    "fog_density",
                    TRANSITION_FOG_DENSITY + (end_density - TRANSITION_FOG_DENSITY) * alpha)
        except Exception:
            pass
        yield


def _transition_tick(_delta):
    gen = STATE.get("transition_gen")
    if gen is None:
        _end_transition()
        return
    try:
        next(gen)
    except StopIteration:
        _end_transition()
    except Exception as e:
        _log_error("_transition_tick: {}".format(e))
        _end_transition()


def _end_transition():
    try:
        STATE["transition_active"] = False
        STATE["transition_gen"] = None
        if STATE["transition_tick_handle"] is not None:
            unreal.unregister_slate_post_tick_callback(STATE["transition_tick_handle"])
            STATE["transition_tick_handle"] = None
    except Exception as e:
        _log_error("_end_transition: {}".format(e))


def _start_transition(index):
    try:
        setlist = STATE["setlist"]
        if not setlist:
            _log_error("transition: setlist is empty")
            return False
        if index < 0 or index >= len(setlist):
            _log_error("transition: index {} out of range 0..{}".format(index, len(setlist) - 1))
            return False
        if STATE["transition_active"]:
            _log("transition already in progress; ignoring")
            return False
        entry = setlist[index]
        _refresh_actor_cache()
        STATE["transition_active"] = True
        STATE["transition_gen"] = _transition_generator(
            entry["path"], index, entry.get("name", entry["path"]))
        if _HAS_UNREAL and hasattr(unreal, "register_slate_post_tick_callback"):
            STATE["transition_tick_handle"] = unreal.register_slate_post_tick_callback(_transition_tick)
        else:
            # Headless/testing: drain synchronously
            for _ in STATE["transition_gen"]:
                pass
            _end_transition()
        return True
    except Exception as e:
        _log_error("_start_transition: {}".format(e))
        STATE["transition_active"] = False
        return False


def load_next_world():
    idx = STATE["current_setlist_index"] + 1
    if STATE["setlist"] and idx >= len(STATE["setlist"]):
        idx = 0  # wrap for encore safety
    return _start_transition(idx)


def load_world_at_index(index):
    return _start_transition(int(index))


# ---------------------------------------------------------------------------
# Setlist management
# ---------------------------------------------------------------------------

def _setlist_dir():
    try:
        if _HAS_UNREAL and hasattr(unreal, "SystemLibrary"):
            base = unreal.SystemLibrary.get_project_saved_directory()
        else:
            base = os.path.join(os.getcwd(), "Saved")
        path = os.path.join(base, "WorldPromptEngine", "Setlists")
        os.makedirs(path, exist_ok=True)
        return path
    except Exception as e:
        _log_error("_setlist_dir: {}".format(e))
        return os.getcwd()


def add_world_to_setlist(world_path, display_name):
    try:
        STATE["setlist"].append({"path": str(world_path), "name": str(display_name)})
        _log("setlist add: {} ({} total)".format(display_name, len(STATE["setlist"])))
    except Exception as e:
        _log_error("add_world_to_setlist: {}".format(e))


def remove_world_from_setlist(index):
    try:
        index = int(index)
        if 0 <= index < len(STATE["setlist"]):
            removed = STATE["setlist"].pop(index)
            if STATE["current_setlist_index"] >= index:
                STATE["current_setlist_index"] -= 1
            _log("setlist remove: {}".format(removed.get("name")))
    except Exception as e:
        _log_error("remove_world_from_setlist: {}".format(e))


def reorder_setlist(from_index, to_index):
    try:
        sl = STATE["setlist"]
        from_index, to_index = int(from_index), int(to_index)
        if 0 <= from_index < len(sl) and 0 <= to_index < len(sl):
            item = sl.pop(from_index)
            sl.insert(to_index, item)
            _log("setlist reorder {} -> {}".format(from_index, to_index))
    except Exception as e:
        _log_error("reorder_setlist: {}".format(e))


def save_setlist(setlist_name):
    try:
        name = world_library.sanitize_world_name(setlist_name)
        path = os.path.join(_setlist_dir(), name + ".json")
        with open(path, "w") as f:
            json.dump({"name": name, "saved": time.time(),
                       "entries": STATE["setlist"]}, f, indent=2)
        _log("setlist saved: {}".format(path))
        return True
    except Exception as e:
        _log_error("save_setlist: {}".format(e))
        return False


def load_setlist(setlist_name):
    try:
        name = world_library.sanitize_world_name(setlist_name)
        path = os.path.join(_setlist_dir(), name + ".json")
        with open(path) as f:
            data = json.load(f)
        STATE["setlist"] = list(data.get("entries", []))
        STATE["current_setlist_index"] = -1
        _log("setlist loaded: {} ({} worlds)".format(name, len(STATE["setlist"])))
        return True
    except Exception as e:
        _log_error("load_setlist: {}".format(e))
        return False


def list_saved_setlists():
    try:
        return sorted(f[:-5] for f in os.listdir(_setlist_dir()) if f.endswith(".json"))
    except Exception as e:
        _log_error("list_saved_setlists: {}".format(e))
        return []


def set_live_param(param_name, value):
    """Dev/testing hook (used by MCP tool): directly set a target value."""
    try:
        if param_name in STATE["targets"]:
            STATE["targets"][param_name] = max(0.0, min(1.0, float(value)))
            if param_name == "kick" and STATE["targets"]["kick"] >= 0.5:
                STATE["kick_ticks_remaining"] = KICK_DECAY_TICKS
            return True
        return False
    except Exception as e:
        _log_error("set_live_param: {}".format(e))
        return False
