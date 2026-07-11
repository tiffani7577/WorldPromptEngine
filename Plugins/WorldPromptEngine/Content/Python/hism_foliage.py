"""
hism_foliage.py — Hierarchical Instanced Static Mesh scattering for WorldPromptEngine.

Replaces per-tree StaticMeshActor spam with HISM batches (one draw call family per mesh).
Falls back to InstancedStaticMeshComponent, then single actors only if needed.
"""

from __future__ import annotations

import math
import random

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False

    class unreal:  # type: ignore
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)


def _destroy_list(state, key="hism_actors"):
    if not _HAS_UNREAL:
        return
    try:
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for a in list(state.get(key) or []):
                try:
                    subsys.destroy_actor(a)
                except Exception:
                    pass
        state[key] = []
    except Exception:
        state[key] = []


def _make_holder(label: str):
    if not hasattr(unreal, "EditorActorSubsystem"):
        return None
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = subsys.spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    if actor is not None:
        try:
            actor.set_actor_label(label)
        except Exception:
            pass
    return actor


def _add_hism(holder, mesh):
    """Prefer HierarchicalInstancedStaticMeshComponent, else ISM."""
    comp_cls = None
    for name in (
        "HierarchicalInstancedStaticMeshComponent",
        "FoliageInstancedStaticMeshComponent",
        "InstancedStaticMeshComponent",
    ):
        if hasattr(unreal, name):
            comp_cls = getattr(unreal, name)
            break
    if holder is None or comp_cls is None:
        return None
    try:
        if hasattr(holder, "add_component_by_class"):
            comp = holder.add_component_by_class(
                comp_cls, False, unreal.Transform(), False)
        else:
            return None
        if comp is None:
            return None
        if hasattr(comp, "set_static_mesh"):
            comp.set_static_mesh(mesh)
        if hasattr(comp, "set_mobility") and hasattr(unreal, "ComponentMobility"):
            try:
                comp.set_mobility(unreal.ComponentMobility.STATIC)
            except Exception:
                pass
        if hasattr(comp, "set_editor_property"):
            try:
                comp.set_editor_property("cast_shadow", True)
            except Exception:
                pass
        return comp
    except Exception as e:
        unreal.log_warning("hism_foliage._add_hism failed: {}".format(e))
        return None


def _add_instance(comp, loc, yaw_deg, scale):
    try:
        if hasattr(unreal, "Transform") and hasattr(unreal, "Rotator"):
            xf = unreal.Transform(
                loc,
                unreal.Rotator(0.0, float(yaw_deg), 0.0),
                unreal.Vector(float(scale), float(scale), float(scale)),
            )
            if hasattr(comp, "add_instance"):
                comp.add_instance(xf)
                return True
        return False
    except Exception:
        return False


def scatter_hism_batch(state: dict, mesh, transforms: list, label: str) -> dict:
    """
    transforms: list of (Vector loc, yaw_deg, uniform_scale)
    """
    summary = {"ok": False, "instances": 0, "mode": "none"}
    if not _HAS_UNREAL or mesh is None or not transforms:
        return summary
    try:
        state.setdefault("hism_actors", [])
        holder = _make_holder(label)
        if holder is None:
            return summary
        comp = _add_hism(holder, mesh)
        if comp is None:
            # last resort: destroy holder, caller may spawn actors
            try:
                unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(holder)
            except Exception:
                pass
            summary["mode"] = "fallback_actors"
            return summary

        count = 0
        for loc, yaw, scale in transforms:
            if _add_instance(comp, loc, yaw, scale):
                count += 1
        if hasattr(comp, "mark_render_state_dirty"):
            try:
                comp.mark_render_state_dirty()
            except Exception:
                pass
        state["hism_actors"].append(holder)
        summary["ok"] = True
        summary["instances"] = count
        summary["mode"] = comp.get_class().get_name() if hasattr(comp, "get_class") else "HISM"
        return summary
    except Exception as e:
        unreal.log_error("hism_foliage.scatter_hism_batch failed: {}".format(e))
        return summary


def clear_hism(state: dict):
    _destroy_list(state, "hism_actors")
