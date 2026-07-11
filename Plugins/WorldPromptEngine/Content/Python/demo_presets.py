"""
demo_presets.py — one-click Base-X tonight demo worlds.
"""

from __future__ import annotations

try:
    import unreal
except ImportError:
    class unreal:  # type: ignore
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)


PRESETS = {
    "alpine_sunset": {
        "label": "Alpine Sunset",
        "prompt": "misty alpine peaks at golden hour",
        "seed": 1337,
        "size": 505,
    },
    "underwater": {
        "label": "Underwater Seafloor",
        "prompt": "underwater seafloor with kelp and sunken ruins",
        "seed": 42,
        "size": 505,
    },
    "desert_moon": {
        "label": "Desert Blood Moon",
        "prompt": "desert dunes under a blood moon",
        "seed": 9001,
        "size": 505,
    },
}


def run_preset(name: str) -> dict:
    """Queue generate_from_prompt for a locked demo preset."""
    try:
        import init_unreal
        spec = PRESETS.get(name)
        if not spec:
            unreal.log_error("Unknown demo preset '{}'".format(name))
            return {"ok": False, "error": "unknown_preset"}
        prompt = spec["prompt"]
        seed = int(spec["seed"])
        size = int(spec["size"])
        init_unreal.GLOBAL_STATE["command_queue"].append({
            "action": "generate_from_prompt",
            "prompt": prompt,
            "params": {
                "width": size,
                "height": size,
                "seed": seed,
                "spawn_structures": True,
                "structure_density": 1.0,
                "spawn_kit": True,
                "use_hism": True,
                "carve_splines": True,
                "spawn_demo_fill": True,
                "apply_erosion": True,
            },
        })
        unreal.log(
            "WorldPromptEngine: DEMO preset '{}' queued — \"{}\"".format(
                spec["label"], prompt))
        return {"ok": True, "preset": name, "prompt": prompt}
    except Exception as e:
        unreal.log_error("demo_presets.run_preset failed: {}".format(e))
        return {"ok": False, "error": str(e)}


def run_alpine():
    return run_preset("alpine_sunset")


def run_underwater():
    return run_preset("underwater")


def run_desert():
    return run_preset("desert_moon")
