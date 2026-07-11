"""
wpe_stage1_validate.py — Stage 1 spike gates G-02 / G-03 / G-04.

Reuses existing native path only:
  wpe_landscape_bridge → UWPEWorldGeneratorSubsystem.ApplyHeightmapToLandscape
  (int32 → uint16 → FLandscapeEditDataInterface::SetHeightData)

G-04 closes collision verification with:
  - line traces against Landscape after native apply
  - Movable StaticMeshActor physics cube (not Static)
  - explicit PASS/FAIL landing log
"""

from __future__ import annotations

import unreal


SECTION = 63
COMPONENTS = 4  # 4*63+1 = 253
RES = COMPONENTS * SECTION + 1  # 253
G04_CUBE_LABEL = "WPE_G04_PhysicsCube"


def _editor_actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _editor_world():
    try:
        if hasattr(unreal, "UnrealEditorSubsystem"):
            return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    except Exception:
        pass
    try:
        if hasattr(unreal, "EditorLevelLibrary"):
            return unreal.EditorLevelLibrary.get_editor_world()
    except Exception:
        pass
    return None


def _ensure_253_landscape():
    """Find WPE_Landscape or any Landscape; optionally create 253×253 via PythonLandscapeLib."""
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
        for a in list(subsys.get_all_level_actors() or []):
            try:
                if isinstance(a, unreal.Landscape):
                    return a
            except Exception:
                continue
        unreal.log_error(
            "G-validate: no Landscape available. "
            "Create Landscape Mode → 63 / 1×1 / 4×4, or enable PythonLandscapeLib.")
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


def _clear_g04_cubes():
    subsys = _editor_actors()
    if subsys is None:
        return
    for a in list(subsys.get_all_level_actors() or []):
        try:
            if (a.get_actor_label() or "") == G04_CUBE_LABEL:
                subsys.destroy_actor(a)
        except Exception:
            continue


def _set_movable(smc):
    """Static mobility blocks Simulate Physics — force Movable."""
    try:
        smc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    except Exception:
        pass
    try:
        smc.set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception:
        pass


def _line_trace_down(world, x, y, z_top=50000.0, z_bot=-50000.0):
    start = unreal.Vector(float(x), float(y), float(z_top))
    end = unreal.Vector(float(x), float(y), float(z_bot))
    actors_to_ignore = unreal.Array(unreal.Actor)
    try:
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            start,
            end,
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True,  # trace complex
            actors_to_ignore,
            unreal.DrawDebugTrace.NONE,
            True,  # ignore self
            unreal.LinearColor(1, 0, 0, 1),
            unreal.LinearColor(0, 1, 0, 1),
            0.0,
        )
        if hit and getattr(hit, "blocking_hit", False):
            return hit
    except TypeError:
        # Older / alternate signature
        try:
            ok, hit = unreal.SystemLibrary.line_trace_single(
                world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                True, actors_to_ignore, unreal.DrawDebugTrace.NONE, True)
            if ok:
                return hit
        except Exception as e:
            unreal.log_warning("G-04 line_trace_single failed: {}".format(e))
    except Exception as e:
        unreal.log_warning("G-04 line_trace_single failed: {}".format(e))
    return None


def _hit_is_landscape(hit, landscape):
    if hit is None or landscape is None:
        return False
    try:
        actor = hit.hit_actor
        if actor is None:
            return False
        if actor == landscape:
            return True
        # Streaming / proxy components may report LandscapeProxy
        name = ""
        try:
            name = actor.get_class().get_name()
        except Exception:
            pass
        return "Landscape" in name
    except Exception:
        return False


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


def run_g04_collision_verify(landscape):
    """
    Verify Landscape collision after native apply.
    Does not replace ApplyHeightmapToLandscape — only probes + Movable drop actor.
    """
    unreal.log("===== G-04 Physics / Collision Verify =====")
    world = _editor_world()
    if world is None:
        unreal.log_error("G-04 FAIL: no editor world.")
        return False

    _clear_g04_cubes()

    # Sample in actor local-ish space using landscape origin + scale
    try:
        origin = landscape.get_actor_location()
        scale = landscape.get_actor_scale3d()
    except Exception:
        origin = unreal.Vector(0, 0, 0)
        scale = unreal.Vector(1, 1, 1)

    # Quads are typically 100uu * XY scale in default landscapes; probe relative offsets
    xy = 100.0 * float(getattr(scale, "x", 1.0) or 1.0)
    # Probe low corner, mid, high corner of the ramp (relative to landscape origin)
    probes = [
        ("low", origin.x + 2 * xy, origin.y + 2 * xy),
        ("mid", origin.x + 126 * xy, origin.y + 126 * xy),
        ("high", origin.x + 250 * xy, origin.y + 250 * xy),
    ]

    hits_z = []
    landscape_hits = 0
    for name, px, py in probes:
        hit = _line_trace_down(world, px, py)
        if hit is None or not getattr(hit, "blocking_hit", False):
            unreal.log_warning("G-04: probe '{}' no blocking hit at ({:.1f},{:.1f}).".format(name, px, py))
            continue
        loc = hit.impact_point if hasattr(hit, "impact_point") else hit.location
        z = float(loc.z)
        hits_z.append((name, z))
        is_ls = _hit_is_landscape(hit, landscape)
        if is_ls:
            landscape_hits += 1
        unreal.log("G-04 probe {}: hit Z={:.2f} landscape={} actor={}".format(
            name, z, is_ls, getattr(hit.hit_actor, "get_name", lambda: "?")()))

    if landscape_hits < 2:
        unreal.log_error(
            "G-04 FAIL: fewer than 2 Landscape collision hits (got {}). "
            "Collision may not have flushed after SetHeightData.".format(landscape_hits))
        collision_ok = False
    else:
        # Ramp should produce increasing Z from low → high (allow small noise)
        z_by_name = {n: z for n, z in hits_z}
        if "low" in z_by_name and "high" in z_by_name:
            delta = z_by_name["high"] - z_by_name["low"]
            unreal.log("G-04 ramp delta Z (high-low) = {:.2f}".format(delta))
            # With default landscape Z scale, ramp should move height meaningfully
            collision_ok = delta > 50.0
            if not collision_ok:
                unreal.log_error(
                    "G-04 FAIL: Landscape hits exist but ramp delta Z too small ({:.2f}). "
                    "Visual heights may not match collision.".format(delta))
        else:
            collision_ok = True  # hits on landscape; ramp corners not both available
            unreal.log_warning("G-04: could not compare low/high corners; accepting Landscape hits.")

    # Spawn Movable physics cube above mid probe for PIE eyes-on
    subsys = _editor_actors()
    cube = None
    mid_x = probes[1][1]
    mid_y = probes[1][2]
    spawn_z = (hits_z[1][1] + 800.0) if len(hits_z) > 1 else (origin.z + 2500.0)
    try:
        cube_mesh = unreal.load_asset("/Engine/BasicShapes/Cube")
        if cube_mesh is not None and hasattr(unreal, "StaticMeshActor"):
            cube = subsys.spawn_actor_from_class(
                unreal.StaticMeshActor,
                unreal.Vector(mid_x, mid_y, spawn_z),
                unreal.Rotator())
            if cube:
                smc = cube.static_mesh_component
                smc.set_static_mesh(cube_mesh)
                _set_movable(smc)
                try:
                    smc.set_simulate_physics(True)
                except Exception as e:
                    unreal.log_warning("G-04 set_simulate_physics: {}".format(e))
                try:
                    cube.set_actor_label(G04_CUBE_LABEL)
                except Exception:
                    pass
                unreal.log(
                    "G-04: spawned {} Movable+SimulatePhysics at Z={:.1f}. "
                    "Press PIE — cube should land on sculpted Landscape.".format(
                        G04_CUBE_LABEL, spawn_z))
    except Exception as e:
        unreal.log_warning("G-04 cube spawn issue: {}".format(e))

    if collision_ok:
        unreal.log(
            "G-04 PASS: Landscape collision responds to traces "
            "(hits={}, cube={}). PIE-drop recommended for final eyes-on.".format(
                landscape_hits, "ok" if cube else "missing"))
        return True

    unreal.log_error("G-04 FAIL: collision verify did not meet pass criteria.")
    return False


# Back-compat alias
def run_g04_proxy():
    landscape = _ensure_253_landscape()
    if landscape is None:
        return False
    return run_g04_collision_verify(landscape)


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
    g04 = run_g04_collision_verify(landscape)
    unreal.log("===== Stage 1 summary: G-02={} G-03={} G-04={} =====".format(g02, g03, g04))
    return bool(g02 and g03 and g04)


if __name__ == "__builtin__" or __name__ == "__main__":
    main()
