"""
wpe_stage1_validate.py — Stage 1 spike gates G-02 / G-03 (and a light G-04 proxy).

Run from Unreal Editor Python console, or:
  UnrealEditor <uproject> -ExecutePythonScript="<path>/wpe_stage1_validate.py"

Expect:
  G-02: 250x250 into 253x253 landscape → False + Size mismatch log
  G-03: 253x253 apply → True + "Native heightfield apply finished in X ms" (< 30ms target)
  G-04 proxy: spawn physics cube above terrain (manual drop/pawn still recommended)
"""

from __future__ import annotations

import unreal


SECTION = 63
COMPONENTS = 4  # 4*63+1 = 253
RES = COMPONENTS * SECTION + 1  # 253


def _editor_actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _ensure_253_landscape():
    """Find WPE_Landscape or create a 253x253 shell via PythonLandscapeLib if available."""
    subsys = _editor_actors()
    for a in list(subsys.get_all_level_actors() or []):
        try:
            if isinstance(a, unreal.Landscape):
                label = ""
                try:
                    label = a.get_actor_label() or ""
                except Exception:
                    pass
                if label == "WPE_Landscape":
                    return a
        except Exception:
            continue

    landscape = None
    if hasattr(unreal, "PythonLandscapeLib") and hasattr(unreal.PythonLandscapeLib, "create_landscape"):
        try:
            xf = unreal.Transform()
            landscape = unreal.PythonLandscapeLib.create_landscape(xf, SECTION, 1, COMPONENTS, COMPONENTS)
        except Exception as e:
            unreal.log_warning("create_landscape failed: {}".format(e))

    if landscape is None:
        # Prefer any existing Landscape in the level
        for a in list(subsys.get_all_level_actors() or []):
            try:
                if isinstance(a, unreal.Landscape):
                    return a
            except Exception:
                continue
        unreal.log_error("G-validate: no Landscape available. Place a 253x253 Landscape or enable PythonLandscapeLib.")
        return None

    try:
        landscape.set_actor_label("WPE_Landscape")
    except Exception:
        pass
    return landscape


def _make_matrix(res_x, res_y, pattern="ramp"):
    m = []
    for y in range(res_y):
        row = []
        for x in range(res_x):
            if pattern == "ramp":
                t = (x + y) / float(max(1, res_x + res_y - 2))
                row.append(int(t * 65535))
            else:
                row.append(32768)
        m.append(row)
    return m


def run_g02(landscape):
    unreal.log("===== G-02 Array Guard =====")
    import wpe_landscape_bridge as bridge
    bad = _make_matrix(250, 250)
    ok = bridge.send_heightmap_to_native(landscape, bad, allow_procedural_fallback=False)
    if ok:
        unreal.log_error("G-02 FAIL: expected rejection for 250x250 vs landscape extent.")
        return False
    unreal.log("G-02 PASS: mismatched 250x250 rejected (check Output Log for Size mismatch).")
    return True


def run_g03(landscape):
    unreal.log("===== G-03 Render Validation =====")
    import wpe_landscape_bridge as bridge
    wpe = unreal.get_engine_subsystem(unreal.WPEWorldGeneratorSubsystem)
    res = wpe.get_landscape_height_resolution(landscape)
    rx, ry = int(res.x), int(res.y)
    if rx <= 0 or ry <= 0:
        unreal.log_error("G-03 FAIL: could not read landscape resolution.")
        return False
    unreal.log("G-03: landscape extent {}x{}".format(rx, ry))
    good = _make_matrix(rx, ry, pattern="ramp")
    ok = bridge.send_heightmap_to_native(landscape, good, allow_procedural_fallback=False)
    if not ok:
        unreal.log_error("G-03 FAIL: native apply returned False.")
        return False
    unreal.log("G-03 PASS: native apply returned True — confirm viewport reshape + timing log < 30ms.")
    return True


def run_g04_proxy():
    unreal.log("===== G-04 Physics Drop (proxy) =====")
    subsys = _editor_actors()
    loc = unreal.Vector(0.0, 0.0, 2500.0)
    actor = None
    try:
        cube_mesh = unreal.load_asset("/Engine/BasicShapes/Cube")
        if cube_mesh is not None and hasattr(unreal, "StaticMeshActor"):
            actor = subsys.spawn_actor_from_class(unreal.StaticMeshActor, loc, unreal.Rotator())
            if actor:
                smc = actor.static_mesh_component
                smc.set_static_mesh(cube_mesh)
                # Static mobility blocks Simulate Physics — must be Movable first
                try:
                    if hasattr(unreal, "ComponentMobility"):
                        smc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
                    smc.set_mobility(unreal.ComponentMobility.MOVABLE)
                except Exception:
                    try:
                        smc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
                    except Exception:
                        pass
                smc.set_simulate_physics(True)
                try:
                    actor.set_actor_label("WPE_G04_PhysicsCube")
                except Exception:
                    pass
    except Exception as e:
        unreal.log_warning("G-04 proxy spawn issue: {}".format(e))

    if actor is None:
        unreal.log_warning("G-04: could not spawn physics cube — drop a pawn manually onto the landscape.")
        return False
    unreal.log("G-04 PROXY: spawned WPE_G04_PhysicsCube (Movable + simulate) at Z=2500. PIE and verify landing.")
    return True


def main():
    unreal.log("===== WPE Stage 1 Validation =====")
    if not hasattr(unreal, "WPEWorldGeneratorSubsystem"):
        unreal.log_error("WPEWorldGeneratorSubsystem missing — rebuild with Modules enabled.")
        return False

    landscape = _ensure_253_landscape()
    if landscape is None:
        return False

    g02 = run_g02(landscape)
    g03 = run_g03(landscape)
    g04 = run_g04_proxy()
    unreal.log("===== Stage 1 summary: G-02={} G-03={} G-04_proxy={} =====".format(g02, g03, g04))
    return bool(g02 and g03)


if __name__ == "__builtin__" or __name__ == "__main__":
    main()
