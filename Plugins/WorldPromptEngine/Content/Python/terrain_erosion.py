"""
terrain_erosion.py — thermal + hydraulic erosion for WorldPromptEngine heightmaps.

Pure Python. Operates on float heights in [0,1], then callers convert back to uint16.
Frame-budget friendly via generator yields.
"""

from __future__ import annotations

import math
import random

try:
    import unreal
except ImportError:
    class unreal:  # type: ignore
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)


def uint16_to_float(pixels):
    return [p / 65535.0 for p in pixels]


def float_to_uint16(heights):
    out = []
    for h in heights:
        v = 0.0 if h < 0.0 else (1.0 if h > 1.0 else h)
        out.append(int(v * 65535.0 + 0.5))
    return out


def apply_erosion_budgeted(pixels, width: int, height: int, params: dict = None,
                           budget_ms: float = 8.0):
    """
    Generator: thermal then hydraulic erosion on a copy of the heightmap.
    Yields ("progress", t) and finally ("result", uint16_pixels).
    """
    import time
    params = params or {}
    if not params.get("apply_erosion", True):
        yield ("result", list(pixels))
        return

    try:
        heights = uint16_to_float(pixels)
        thermal_iters = int(params.get("thermal_iterations", 12))
        hydro_iters = int(params.get("hydraulic_iterations", 28))
        talus = float(params.get("talus_angle", 0.035))  # ~height delta per neighbor
        thermal_rate = float(params.get("thermal_rate", 0.35))
        rain = float(params.get("rain_amount", 0.012))
        evaporation = float(params.get("evaporation", 0.02))
        capacity_k = float(params.get("sediment_capacity", 0.08))
        deposition = float(params.get("deposition", 0.2))
        erosion_k = float(params.get("erosion", 0.25))
        seed = int(params.get("seed", 1337))

        # Moisture from prompt keywords (already scored upstream optionally)
        moisture = float(params.get("moisture", 0.5))
        rain *= 0.5 + moisture
        hydro_iters = max(8, int(hydro_iters * (0.6 + 0.8 * moisture)))

        water = [0.0] * (width * height)
        sediment = [0.0] * (width * height)
        rng = random.Random(seed ^ 0xE20)

        slice_start = time.perf_counter()
        total_steps = max(1, thermal_iters + hydro_iters)
        step_i = 0

        def maybe_yield(local_progress: float):
            nonlocal slice_start
            if (time.perf_counter() - slice_start) * 1000.0 >= budget_ms:
                yield_val = ("progress", local_progress)
                slice_start = time.perf_counter()
                return yield_val
            return None

        # ---- Thermal erosion (talus) ----
        neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1))
        for it in range(thermal_iters):
            delta = [0.0] * (width * height)
            for y in range(1, height - 1):
                for x in range(1, width - 1):
                    i = y * width + x
                    h = heights[i]
                    # steepest downhill neighbor
                    max_diff = 0.0
                    tx = ty = 0
                    for dx, dy in neighbors:
                        j = (y + dy) * width + (x + dx)
                        diff = h - heights[j]
                        if diff > max_diff:
                            max_diff = diff
                            tx, ty = dx, dy
                    if max_diff > talus:
                        move = (max_diff - talus) * thermal_rate
                        delta[i] -= move
                        delta[(y + ty) * width + (x + tx)] += move
            for i in range(width * height):
                heights[i] = max(0.0, min(1.0, heights[i] + delta[i]))
            step_i += 1
            yv = maybe_yield(step_i / float(total_steps) * 0.45)
            if yv:
                yield yv

        # ---- Hydraulic erosion (droplet-ish grid) ----
        for it in range(hydro_iters):
            # rain
            for i in range(width * height):
                water[i] += rain * (0.85 + 0.3 * rng.random())

            # flow + erode/deposit toward lowest neighbor
            new_h = list(heights)
            new_w = list(water)
            new_s = list(sediment)
            for y in range(1, height - 1):
                for x in range(1, width - 1):
                    i = y * width + x
                    h = heights[i]
                    # find lowest neighbor
                    best = i
                    best_h = h
                    for dx, dy in neighbors:
                        j = (y + dy) * width + (x + dx)
                        if heights[j] < best_h:
                            best_h = heights[j]
                            best = j
                    if best == i:
                        # flat/pit: evaporate and deposit
                        dep = sediment[i] * deposition
                        new_h[i] = min(1.0, h + dep)
                        new_s[i] = max(0.0, sediment[i] - dep)
                        new_w[i] = water[i] * (1.0 - evaporation)
                        continue

                    dh = h - best_h
                    flow = min(water[i], dh * 0.5 + water[i] * 0.25)
                    if flow <= 1e-8:
                        new_w[i] = water[i] * (1.0 - evaporation)
                        continue

                    # capacity proportional to slope * flow
                    cap = capacity_k * flow * (dh + 0.001)
                    sed = sediment[i]
                    if sed > cap:
                        dep = (sed - cap) * deposition
                        new_h[i] = min(1.0, h + dep)
                        sed = sed - dep
                    else:
                        ero = min(h * 0.25, (cap - sed) * erosion_k)
                        new_h[i] = max(0.0, h - ero)
                        sed = sed + ero

                    # transport water/sediment downhill
                    new_w[i] -= flow
                    new_w[best] += flow
                    moved = sed * min(1.0, flow / (water[i] + 1e-6))
                    new_s[i] -= moved
                    new_s[best] += moved
                    new_w[i] *= (1.0 - evaporation)

            heights, water, sediment = new_h, new_w, new_s
            # clamp
            for i in range(width * height):
                heights[i] = 0.0 if heights[i] < 0.0 else (1.0 if heights[i] > 1.0 else heights[i])
                water[i] = max(0.0, water[i])
                sediment[i] = max(0.0, sediment[i])

            step_i += 1
            yv = maybe_yield(0.45 + step_i / float(total_steps) * 0.55)
            if yv:
                yield yv

        unreal.log(
            "WorldPromptEngine: erosion done (thermal={}, hydraulic={}, moisture={:.2f})".format(
                thermal_iters, hydro_iters, moisture))
        yield ("result", float_to_uint16(heights))
    except Exception as e:
        unreal.log_error("terrain_erosion.apply_erosion_budgeted failed: {}".format(e))
        yield ("result", list(pixels))


def moisture_from_prompt(prompt: str) -> float:
    """0..1 moisture metric from prompt keywords."""
    t = (prompt or "").lower()
    wet = ("rain", "wet", "swamp", "marsh", "jungle", "mist", "fog", "river",
           "lake", "ocean", "monsoon", "humid", "flood", "creek", "stream")
    dry = ("desert", "arid", "dune", "dry", "ash", "scorched", "salt", "barren")
    score = 0.5
    for w in wet:
        if w in t:
            score += 0.08
    for d in dry:
        if d in t:
            score -= 0.1
    return max(0.0, min(1.0, score))
