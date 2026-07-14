"""
biome_regions.py — multi-biome Voronoi / noise regional masks for WorldPromptEngine.

Carves the map into distinct biome cells (e.g. desert south, swamp north) so
material weightmaps and foliage rules can vary by region instead of globally.
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


# Soft regional tint hints (used by weightmap blending / kit filters)
BIOME_STYLE = {
    "alpine_peaks": {"prefer_height": (0.45, 1.0), "max_slope": 55, "foliage": "sparse_pine", "moisture": 0.45},
    "desert_dunes": {"prefer_height": (0.15, 0.7), "max_slope": 35, "foliage": "arid", "moisture": 0.1},
    "swamp_wetlands": {"prefer_height": (0.05, 0.4), "max_slope": 18, "foliage": "wet", "moisture": 0.95},
    "dense_rainforest": {"prefer_height": (0.15, 0.65), "max_slope": 28, "foliage": "dense", "moisture": 0.9},
    "rolling_hills": {"prefer_height": (0.2, 0.7), "max_slope": 25, "foliage": "meadow", "moisture": 0.5},
    "tundra_flats": {"prefer_height": (0.2, 0.85), "max_slope": 20, "foliage": "sparse", "moisture": 0.35},
    "savanna_plains": {"prefer_height": (0.15, 0.55), "max_slope": 18, "foliage": "grassland", "moisture": 0.3},
    "volcanic_badlands": {"prefer_height": (0.25, 0.95), "max_slope": 60, "foliage": "dead", "moisture": 0.15},
    "redwood_forest": {"prefer_height": (0.2, 0.7), "max_slope": 30, "foliage": "dense", "moisture": 0.7},
    "coastal_cliffs": {"prefer_height": (0.05, 0.85), "max_slope": 70, "foliage": "coast", "moisture": 0.55},
    "underwater_seafloor": {"prefer_height": (0.1, 0.55), "max_slope": 40, "foliage": "wet", "moisture": 1.0},
    "coral_shallows": {"prefer_height": (0.05, 0.35), "max_slope": 22, "foliage": "wet", "moisture": 0.95},
    "enchanted_forest": {"prefer_height": (0.15, 0.7), "max_slope": 28, "foliage": "dense", "moisture": 0.65},
}


def rank_biomes_from_prompt(prompt: str, primary: str = None, max_regions: int = 4) -> list:
    """
    Return up to max_regions archetypes ranked by keyword score.
    Always includes primary (if given). Falls back to complementary pairs.
    """
    try:
        import prompt_matrix
        tokens = [t.strip(".,!?;:'\"()-").lower() for t in (prompt or "").split()]
        tokens = [t for t in tokens if t]
        scored = []
        for name, spec in prompt_matrix.TERRAIN_ARCHETYPES.items():
            s = 0
            for tok in tokens:
                s += int(spec.get("keywords", {}).get(tok, 0))
            if s > 0:
                scored.append((s, name))
        scored.sort(reverse=True)
        names = []
        if primary:
            names.append(primary)
        for _, n in scored:
            if n not in names:
                names.append(n)
            if len(names) >= max_regions:
                break

        # If prompt only hit one biome, invent a complementary neighbor for visual variety
        if len(names) < 2:
            complements = {
                "alpine_peaks": ["swamp_wetlands", "rolling_hills"],
                "desert_dunes": ["savanna_plains", "canyon_mesas"],
                "swamp_wetlands": ["dense_rainforest", "rolling_hills"],
                "dense_rainforest": ["swamp_wetlands", "tropical_islands"],
                "coastal_cliffs": ["tropical_islands", "rolling_hills"],
                "volcanic_badlands": ["ash", "desert_dunes"],
            }
            base = names[0] if names else (primary or "rolling_hills")
            if base not in names:
                names.append(base)
            for c in complements.get(base, ["rolling_hills", "desert_dunes"]):
                # map typos
                if c == "ash":
                    c = "volcanic_badlands"
                if c in prompt_matrix.TERRAIN_ARCHETYPES and c not in names:
                    names.append(c)
                if len(names) >= max(2, min(3, max_regions)):
                    break
        return names[:max_regions]
    except Exception as e:
        unreal.log_error("biome_regions.rank_biomes_from_prompt failed: {}".format(e))
        return [primary or "rolling_hills", "desert_dunes"]


def generate_voronoi_regions(width: int, height: int, biome_names: list,
                             seed: int = 1337, blend: float = 0.12) -> dict:
    """
    Voronoi cell assignment + soft border blend weights.

    Returns:
      {
        "biome_names": [...],
        "cell_index": [int] per pixel (hard nearest site),
        "weights": { biome_name: [float 0..1] soft },
        "sites": [(x,y,biome_name), ...],
      }
    """
    try:
        biome_names = list(biome_names) or ["rolling_hills"]
        n = len(biome_names)
        rng = random.Random(seed ^ 0xB10E)
        sites = []
        # Space sites with a light jittered grid so regions are readable
        cols = max(1, int(math.ceil(math.sqrt(n))))
        rows = max(1, int(math.ceil(n / float(cols))))
        for i, name in enumerate(biome_names):
            gx = i % cols
            gy = i // cols
            cx = (gx + 0.5) / cols * width + rng.uniform(-width * 0.08, width * 0.08)
            cy = (gy + 0.5) / rows * height + rng.uniform(-height * 0.08, height * 0.08)
            cx = max(2.0, min(width - 3.0, cx))
            cy = max(2.0, min(height - 3.0, cy))
            sites.append((cx, cy, name))

        cell_index = [0] * (width * height)
        weights = {b: [0.0] * (width * height) for b in biome_names}
        inv_blend = 1.0 / max(1e-4, blend * max(width, height))

        for y in range(height):
            for x in range(width):
                i = y * width + x
                dists = []
                for si, (sx, sy, _name) in enumerate(sites):
                    dx = x - sx
                    dy = y - sy
                    # slight noise stretch for organic borders
                    d = math.sqrt(dx * dx + dy * dy)
                    dists.append((d, si))
                dists.sort()
                best_si = dists[0][1]
                cell_index[i] = best_si
                # soft weights via inverse-distance among nearest 2-3
                take = dists[: min(3, len(dists))]
                raw = []
                for d, si in take:
                    raw.append((max(0.0, 1.0 - d * inv_blend * 0.35), si))
                tot = sum(r for r, _ in raw) + 1e-6
                for r, si in raw:
                    b = sites[si][2]
                    weights[b][i] += r / tot
                # normalize across biomes at pixel
                s = sum(weights[b][i] for b in biome_names) + 1e-6
                for b in biome_names:
                    weights[b][i] /= s

        unreal.log("WorldPromptEngine: Voronoi biomes -> {}".format(biome_names))
        return {
            "biome_names": biome_names,
            "cell_index": cell_index,
            "weights": weights,
            "sites": sites,
        }
    except Exception as e:
        unreal.log_error("biome_regions.generate_voronoi_regions failed: {}".format(e))
        return {"biome_names": biome_names or ["rolling_hills"], "cell_index": [], "weights": {}, "sites": []}


def biome_at_pixel(regions: dict, x: int, y: int, width: int) -> str:
    try:
        names = regions.get("biome_names") or ["rolling_hills"]
        cells = regions.get("cell_index") or []
        if not cells:
            return names[0]
        i = y * width + x
        if i < 0 or i >= len(cells):
            return names[0]
        return names[cells[i]]
    except Exception:
        return "rolling_hills"


def apply_biome_height_bias(pixels, width: int, height: int, regions: dict,
                            strength: float = 0.08):
    """
    Gentle per-biome height shaping so deserts sit lower / alpine higher.
    Mutates pixels (uint16) in place; returns pixels.
    """
    try:
        if not regions or not regions.get("weights"):
            return pixels
        styles = BIOME_STYLE
        for y in range(height):
            for x in range(width):
                i = y * width + x
                h = pixels[i] / 65535.0
                bias = 0.0
                for b, wlist in regions["weights"].items():
                    w = wlist[i]
                    if w <= 0.01:
                        continue
                    st = styles.get(b) or {}
                    lo, hi = st.get("prefer_height", (0.2, 0.8))
                    mid = 0.5 * (lo + hi)
                    bias += w * (mid - 0.5) * strength
                nh = max(0.0, min(1.0, h + bias))
                pixels[i] = int(nh * 65535.0 + 0.5)
        return pixels
    except Exception as e:
        unreal.log_warning("biome_regions.apply_biome_height_bias failed: {}".format(e))
        return pixels


def build_biome_mask_summary(regions: dict, width: int, height: int) -> dict:
    counts = {}
    cells = regions.get("cell_index") or []
    names = regions.get("biome_names") or []
    for idx in cells:
        if 0 <= idx < len(names):
            n = names[idx]
            counts[n] = counts.get(n, 0) + 1
    total = max(1, width * height)
    return {k: round(v / float(total), 3) for k, v in counts.items()}
