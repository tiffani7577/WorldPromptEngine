"""
prompt_matrix.py — WorldPromptEngine biome, weather, and prompt parsing (UE 5.8.0)

Implements:
  1. TERRAIN_ARCHETYPES: 20 terrain archetypes with keyword dictionaries and
     noise parameter profiles consumed by art_engine.generate_heightmap_task.
  2. parse_prompt(): natural-language keyword scoring -> archetype + weather.
  3. Slope-angle material layer calculation (per-pixel, degrees, from a
     heightmap grid + world scale).
  4. asset_manifest.json lookup logic for PCG spawn tables.
  5. WEATHER_PRESETS: 12 lighting/atmosphere configurations, applied to
     DirectionalLight / SkyAtmosphere / ExponentialHeightFog /
     VolumetricCloud actors via hasattr()-guarded 5.8 APIs.

MAIN THREAD ONLY for apply_weather_preset() and any unreal.* mutation.
Pure functions (parse_prompt, compute_slope_map, resolve_assets) are
thread-agnostic.
"""

import json
import math
import os

try:
    import unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False

    class _StubLog:
        @staticmethod
        def log_error(msg): print("[ERROR]", msg)
        @staticmethod
        def log(msg): print("[LOG]", msg)
        @staticmethod
        def log_warning(msg): print("[WARN]", msg)
    unreal = _StubLog()  # type: ignore


# ---------------------------------------------------------------------------
# SECTION 1 — 20 TERRAIN ARCHETYPES (keyword dicts + noise profiles)
# ---------------------------------------------------------------------------
# Each archetype: keywords (scored on hit), noise params fed straight into
# generate_heightmap_task, and pcg_tags used against asset_manifest.json.

TERRAIN_ARCHETYPES = {
    "alpine_peaks": {
        "keywords": {"alpine": 3, "peaks": 3, "mountain": 2, "summit": 2, "craggy": 2, "snowcap": 2, "ridge": 1},
        "noise": {"octaves": 8, "frequency": 0.0035, "persistence": 0.55, "lacunarity": 2.2, "amplitude": 1.0},
        "pcg_tags": ["pine", "rock_large", "snow_patch"],
    },
    "rolling_hills": {
        "keywords": {"rolling": 3, "hills": 3, "meadow": 2, "pasture": 2, "gentle": 2, "countryside": 2},
        "noise": {"octaves": 4, "frequency": 0.0018, "persistence": 0.45, "lacunarity": 2.0, "amplitude": 0.35},
        "pcg_tags": ["oak", "wildflower", "grass_tall"],
    },
    "desert_dunes": {
        "keywords": {"desert": 3, "dunes": 3, "sand": 2, "arid": 2, "sahara": 2, "barren": 1},
        "noise": {"octaves": 3, "frequency": 0.0025, "persistence": 0.6, "lacunarity": 1.8, "amplitude": 0.4},
        "pcg_tags": ["cactus", "rock_small", "dead_shrub"],
    },
    "volcanic_badlands": {
        "keywords": {"volcanic": 3, "volcano": 3, "lava": 3, "basalt": 2, "ash": 2, "caldera": 2, "scorched": 1},
        "noise": {"octaves": 7, "frequency": 0.005, "persistence": 0.62, "lacunarity": 2.4, "amplitude": 0.85},
        "pcg_tags": ["rock_volcanic", "ember_vent", "dead_tree"],
    },
    "coastal_cliffs": {
        "keywords": {"coastal": 3, "cliffs": 3, "coast": 2, "seaside": 2, "bluff": 2, "shoreline": 2},
        "noise": {"octaves": 6, "frequency": 0.003, "persistence": 0.58, "lacunarity": 2.1, "amplitude": 0.9},
        "pcg_tags": ["seagrass", "rock_coastal", "driftwood"],
    },
    "tropical_islands": {
        "keywords": {"tropical": 3, "island": 3, "atoll": 3, "lagoon": 2, "palm": 2, "beach": 1},
        "noise": {"octaves": 5, "frequency": 0.0022, "persistence": 0.5, "lacunarity": 2.0, "amplitude": 0.55},
        "pcg_tags": ["palm", "fern_tropical", "rock_beach"],
    },
    "tundra_flats": {
        "keywords": {"tundra": 3, "permafrost": 3, "arctic": 2, "frozen": 2, "polar": 2, "flats": 1},
        "noise": {"octaves": 4, "frequency": 0.0015, "persistence": 0.4, "lacunarity": 1.9, "amplitude": 0.2},
        "pcg_tags": ["lichen_rock", "shrub_arctic", "snow_drift"],
    },
    "dense_rainforest": {
        "keywords": {"rainforest": 3, "jungle": 3, "amazon": 2, "canopy": 2, "lush": 2, "overgrown": 1},
        "noise": {"octaves": 6, "frequency": 0.0028, "persistence": 0.52, "lacunarity": 2.0, "amplitude": 0.5},
        "pcg_tags": ["kapok", "vine_cluster", "fern_giant", "undergrowth"],
    },
    "canyon_mesas": {
        "keywords": {"canyon": 3, "mesa": 3, "plateau": 2, "gorge": 2, "arizona": 2, "striated": 1},
        "noise": {"octaves": 5, "frequency": 0.0026, "persistence": 0.7, "lacunarity": 2.6, "amplitude": 0.95},
        "pcg_tags": ["rock_sandstone", "sagebrush", "juniper"],
    },
    "swamp_wetlands": {
        "keywords": {"swamp": 3, "wetlands": 3, "marsh": 3, "bog": 2, "bayou": 2, "mangrove": 2},
        "noise": {"octaves": 4, "frequency": 0.002, "persistence": 0.42, "lacunarity": 1.9, "amplitude": 0.15},
        "pcg_tags": ["cypress", "reed_cluster", "lilypad", "moss_hang"],
    },
    "glacier_fields": {
        "keywords": {"glacier": 3, "glacial": 3, "icefield": 3, "crevasse": 2, "ice": 1, "moraine": 2},
        "noise": {"octaves": 6, "frequency": 0.0024, "persistence": 0.5, "lacunarity": 2.2, "amplitude": 0.7},
        "pcg_tags": ["ice_shard", "rock_glacial", "snow_drift"],
    },
    "highland_moors": {
        "keywords": {"moor": 3, "moors": 3, "highland": 3, "heather": 2, "scottish": 2, "misty": 1},
        "noise": {"octaves": 5, "frequency": 0.002, "persistence": 0.48, "lacunarity": 2.0, "amplitude": 0.4},
        "pcg_tags": ["heather", "rock_moss", "gorse"],
    },
    "savanna_plains": {
        "keywords": {"savanna": 3, "savannah": 3, "serengeti": 2, "acacia": 2, "grassland": 2, "plains": 1},
        "noise": {"octaves": 3, "frequency": 0.0014, "persistence": 0.4, "lacunarity": 1.8, "amplitude": 0.18},
        "pcg_tags": ["acacia", "grass_dry", "termite_mound"],
    },
    "karst_towers": {
        "keywords": {"karst": 3, "towers": 2, "limestone": 3, "guilin": 2, "pinnacle": 2, "spires": 2},
        "noise": {"octaves": 7, "frequency": 0.006, "persistence": 0.65, "lacunarity": 2.5, "amplitude": 0.9},
        "pcg_tags": ["bamboo", "rock_limestone", "vine_cluster"],
    },
    "fjord_valleys": {
        "keywords": {"fjord": 3, "fjords": 3, "norwegian": 2, "inlet": 2, "steep": 1, "nordic": 2},
        "noise": {"octaves": 7, "frequency": 0.0032, "persistence": 0.6, "lacunarity": 2.3, "amplitude": 1.0},
        "pcg_tags": ["spruce", "rock_granite", "waterfall_marker"],
    },
    "salt_flats": {
        "keywords": {"salt": 3, "flats": 2, "uyuni": 3, "playa": 2, "mirror": 1, "cracked": 2},
        "noise": {"octaves": 2, "frequency": 0.001, "persistence": 0.3, "lacunarity": 1.7, "amplitude": 0.05},
        "pcg_tags": ["salt_crust", "rock_small"],
    },
    "redwood_forest": {
        "keywords": {"redwood": 3, "sequoia": 3, "oldgrowth": 2, "towering": 1, "pacific": 1, "grove": 2},
        "noise": {"octaves": 5, "frequency": 0.0022, "persistence": 0.5, "lacunarity": 2.0, "amplitude": 0.45},
        "pcg_tags": ["redwood", "fern_giant", "log_fallen", "moss_hang"],
    },
    "steppe_ridges": {
        "keywords": {"steppe": 3, "mongolian": 2, "windswept": 2, "ridges": 2, "eurasian": 2, "vast": 1},
        "noise": {"octaves": 4, "frequency": 0.0016, "persistence": 0.46, "lacunarity": 2.0, "amplitude": 0.3},
        "pcg_tags": ["grass_dry", "rock_small", "shrub_hardy"],
    },
    "crater_wastes": {
        "keywords": {"crater": 3, "impact": 2, "wasteland": 3, "apocalyptic": 2, "lunar": 2, "desolate": 2},
        "noise": {"octaves": 6, "frequency": 0.004, "persistence": 0.58, "lacunarity": 2.2, "amplitude": 0.65},
        "pcg_tags": ["rock_scorched", "debris", "dead_tree"],
    },
    "terraced_valleys": {
        "keywords": {"terraced": 3, "terrace": 3, "rice": 2, "paddies": 2, "cultivated": 2, "stepped": 2},
        "noise": {"octaves": 5, "frequency": 0.002, "persistence": 0.5, "lacunarity": 2.0, "amplitude": 0.5,
                  "terrace_steps": 12},
        "pcg_tags": ["bamboo", "grass_wet", "stone_wall"],
    },
    "archipelago": {
        "keywords": {"archipelago": 3, "islands": 2, "chain": 1, "scattered": 1},
        "noise": {"octaves": 5, "frequency": 0.003, "persistence": 0.55, "lacunarity": 2.1, "amplitude": 0.6},
        "pcg_tags": ["palm", "rock_beach", "seagrass"],
    },
    "bamboo_highlands": {
        "keywords": {"bamboo": 3, "highlands": 2, "asian": 1},
        "noise": {"octaves": 5, "frequency": 0.0024, "persistence": 0.5, "lacunarity": 2.0, "amplitude": 0.55},
        "pcg_tags": ["bamboo", "rock_limestone", "fern_tropical"],
    },
    "enchanted_forest": {
        "keywords": {"enchanted": 3, "fairy": 2, "magic": 2, "mystical": 2, "glowing": 1},
        "noise": {"octaves": 6, "frequency": 0.0025, "persistence": 0.52, "lacunarity": 2.0, "amplitude": 0.48},
        "pcg_tags": ["oak", "fern_giant", "moss_hang", "wildflower"],
    },
    "obsidian_wastes": {
        "keywords": {"obsidian": 3, "blackglass": 2, "glassland": 2},
        "noise": {"octaves": 6, "frequency": 0.0045, "persistence": 0.6, "lacunarity": 2.3, "amplitude": 0.7},
        "pcg_tags": ["rock_volcanic", "rock_scorched", "ember_vent"],
    },
    "coral_shallows": {
        "keywords": {"coral": 3, "reef": 3, "shallow": 2, "turquoise": 2},
        "noise": {"octaves": 3, "frequency": 0.002, "persistence": 0.4, "lacunarity": 1.8, "amplitude": 0.12},
        "pcg_tags": ["seagrass", "rock_beach", "lilypad"],
        "structure_tags": ["coral_stack", "dock_pier", "temple_ruin"],
    },
    "underwater_seafloor": {
        "keywords": {
            "underwater": 5, "submerged": 4, "seafloor": 4, "aquatic": 3,
            "sunken": 3, "atlantis": 3, "abyss": 2, "kelp": 2, "trench": 2,
        },
        "noise": {"octaves": 5, "frequency": 0.0028, "persistence": 0.48, "lacunarity": 2.0, "amplitude": 0.32},
        "pcg_tags": ["seagrass", "rock_coastal", "rock_small", "coral"],
        "structure_tags": ["shipwreck", "coral_stack", "temple_ruin", "arch_rock"],
    },
    "floating_isles": {
        "keywords": {"floating": 3, "sky": 2, "isles": 3, "airborne": 2, "levitating": 2, "aether": 2},
        "noise": {"octaves": 6, "frequency": 0.0038, "persistence": 0.58, "lacunarity": 2.3, "amplitude": 0.85},
        "pcg_tags": ["pine", "rock_large", "wildflower"],
        "structure_tags": ["floating_boulder", "crystal_spire", "portal_ring", "wizard_tower"],
    },
}

DEFAULT_ARCHETYPE = "rolling_hills"

# Default structure tags per archetype (wired into parse + manifest)
ARCHETYPE_STRUCTURE_TAGS = {
    "alpine_peaks": ["stone_keep", "crystal_spire", "ice_monolith", "ruined_tower"],
    "rolling_hills": ["village_hut", "barn", "windmill", "stone_circle"],
    "desert_dunes": ["obelisk", "pyramid", "camp_tents", "giant_bone"],
    "volcanic_badlands": ["lava_spine", "dragon_perch", "portal_ring", "ruined_tower"],
    "coastal_cliffs": ["lighthouse", "shipwreck", "dock_pier", "arch_rock"],
    "tropical_islands": ["village_hut", "temple_ruin", "dock_pier", "coral_stack"],
    "tundra_flats": ["longhouse", "obelisk", "camp_tents", "ice_monolith"],
    "dense_rainforest": ["temple_ruin", "totem", "village_hut", "mangrove_root"],
    "canyon_mesas": ["mesa_butte", "arch_rock", "mine_entrance", "watchtower"],
    "swamp_wetlands": ["mangrove_root", "dock_pier", "ruined_tower", "totem"],
    "glacier_fields": ["ice_monolith", "longhouse", "crystal_spire", "stone_keep"],
    "highland_moors": ["stone_circle", "watchtower", "graveyard", "ruined_tower"],
    "savanna_plains": ["village_hut", "camp_tents", "obelisk", "barn"],
    "karst_towers": ["pagoda", "crystal_spire", "temple_ruin", "bridge_arch"],
    "fjord_valleys": ["longhouse", "lighthouse", "bridge_arch", "waterfall_rocks"],
    "salt_flats": ["obelisk", "radar_dish", "oil_derrick", "camp_tents"],
    "redwood_forest": ["totem", "village_hut", "ruined_tower", "waterfall_rocks"],
    "steppe_ridges": ["camp_tents", "watchtower", "obelisk", "windmill"],
    "crater_wastes": ["radar_dish", "portal_ring", "ruined_tower", "giant_bone"],
    "terraced_valleys": ["pagoda", "village_hut", "barn", "bridge_arch"],
    "archipelago": ["dock_pier", "lighthouse", "village_hut", "shipwreck"],
    "bamboo_highlands": ["pagoda", "temple_ruin", "totem", "bridge_arch"],
    "enchanted_forest": ["wizard_tower", "stone_circle", "crystal_spire", "totem"],
    "obsidian_wastes": ["lava_spine", "portal_ring", "obelisk", "ruined_tower"],
    "coral_shallows": ["coral_stack", "dock_pier", "temple_ruin", "shipwreck"],
    "underwater_seafloor": ["shipwreck", "coral_stack", "temple_ruin", "arch_rock"],
    "floating_isles": ["floating_boulder", "crystal_spire", "portal_ring", "wizard_tower"],
}

for _arch_name, _tags in ARCHETYPE_STRUCTURE_TAGS.items():
    if _arch_name in TERRAIN_ARCHETYPES:
        TERRAIN_ARCHETYPES[_arch_name].setdefault("structure_tags", list(_tags))


# ---------------------------------------------------------------------------
# SECTION 2 — 12 WEATHER PRESETS (lighting configurations)
# ---------------------------------------------------------------------------
# Values: sun_intensity (lux), sun_color RGB 0-1, sun_pitch/yaw degrees,
# fog_density, fog_height_falloff, fog_color, cloud_coverage 0-1,
# sky_rayleigh scale, post_exposure_bias.

WEATHER_PRESETS = {
    "clear_noon": {
        "keywords": {"clear": 2, "sunny": 3, "noon": 2, "bright": 2, "bluebird": 3},
        "sun_intensity": 10.0, "sun_color": (1.0, 0.96, 0.88), "sun_pitch": -70.0, "sun_yaw": 40.0,
        "fog_density": 0.005, "fog_height_falloff": 0.2, "fog_color": (0.65, 0.75, 0.9),
        "cloud_coverage": 0.1, "sky_rayleigh": 1.0, "exposure_bias": 0.0,
    },
    "golden_hour": {
        "keywords": {"golden": 3, "sunset": 3, "sunrise": 3, "dusk": 2, "warm": 1, "amber": 2},
        "sun_intensity": 5.0, "sun_color": (1.0, 0.62, 0.32), "sun_pitch": -8.0, "sun_yaw": 265.0,
        "fog_density": 0.02, "fog_height_falloff": 0.25, "fog_color": (0.95, 0.6, 0.4),
        "cloud_coverage": 0.35, "sky_rayleigh": 1.4, "exposure_bias": 0.3,
    },
    "overcast": {
        "keywords": {"overcast": 3, "cloudy": 3, "grey": 2, "gray": 2, "dull": 1, "flat": 1},
        "sun_intensity": 3.0, "sun_color": (0.85, 0.87, 0.9), "sun_pitch": -55.0, "sun_yaw": 30.0,
        "fog_density": 0.03, "fog_height_falloff": 0.18, "fog_color": (0.7, 0.72, 0.75),
        "cloud_coverage": 0.95, "sky_rayleigh": 0.8, "exposure_bias": 0.2,
    },
    "storm_front": {
        "keywords": {"storm": 3, "thunder": 3, "lightning": 3, "tempest": 2, "violent": 1, "squall": 2},
        "sun_intensity": 1.2, "sun_color": (0.6, 0.63, 0.7), "sun_pitch": -45.0, "sun_yaw": 120.0,
        "fog_density": 0.06, "fog_height_falloff": 0.15, "fog_color": (0.35, 0.38, 0.45),
        "cloud_coverage": 1.0, "sky_rayleigh": 0.6, "exposure_bias": 0.4,
    },
    "dense_fog": {
        "keywords": {"fog": 3, "foggy": 3, "mist": 2, "misty": 2, "haze": 2, "silent": 1},
        "sun_intensity": 2.0, "sun_color": (0.9, 0.9, 0.9), "sun_pitch": -40.0, "sun_yaw": 60.0,
        "fog_density": 0.25, "fog_height_falloff": 0.08, "fog_color": (0.78, 0.8, 0.82),
        "cloud_coverage": 0.85, "sky_rayleigh": 0.7, "exposure_bias": 0.5,
    },
    "blizzard": {
        "keywords": {"blizzard": 3, "snowstorm": 3, "whiteout": 3, "snowing": 2, "freezing": 1},
        "sun_intensity": 1.5, "sun_color": (0.82, 0.86, 0.95), "sun_pitch": -35.0, "sun_yaw": 200.0,
        "fog_density": 0.18, "fog_height_falloff": 0.1, "fog_color": (0.85, 0.88, 0.93),
        "cloud_coverage": 1.0, "sky_rayleigh": 0.65, "exposure_bias": 0.6,
    },
    "moonlit_night": {
        "keywords": {"night": 3, "moonlit": 3, "moon": 2, "midnight": 3, "stars": 2, "nocturnal": 2},
        "sun_intensity": 0.05, "sun_color": (0.55, 0.65, 0.9), "sun_pitch": -60.0, "sun_yaw": 310.0,
        "fog_density": 0.015, "fog_height_falloff": 0.2, "fog_color": (0.1, 0.13, 0.22),
        "cloud_coverage": 0.2, "sky_rayleigh": 0.3, "exposure_bias": 1.5,
    },
    "blood_dusk": {
        "keywords": {"blood": 3, "crimson": 3, "ominous": 2, "red": 1, "apocalypse": 2, "eerie": 1},
        "sun_intensity": 3.5, "sun_color": (0.95, 0.28, 0.15), "sun_pitch": -6.0, "sun_yaw": 250.0,
        "fog_density": 0.05, "fog_height_falloff": 0.12, "fog_color": (0.55, 0.18, 0.12),
        "cloud_coverage": 0.6, "sky_rayleigh": 1.8, "exposure_bias": 0.2,
    },
    "heavy_rain": {
        "keywords": {"rain": 3, "rainy": 3, "downpour": 3, "drizzle": 2, "wet": 1, "monsoon": 2},
        "sun_intensity": 2.2, "sun_color": (0.7, 0.74, 0.8), "sun_pitch": -50.0, "sun_yaw": 90.0,
        "fog_density": 0.08, "fog_height_falloff": 0.14, "fog_color": (0.5, 0.55, 0.62),
        "cloud_coverage": 1.0, "sky_rayleigh": 0.7, "exposure_bias": 0.35,
    },
    "sandstorm": {
        "keywords": {"sandstorm": 3, "duststorm": 3, "haboob": 3, "dust": 2, "choking": 1},
        "sun_intensity": 4.0, "sun_color": (0.95, 0.72, 0.45), "sun_pitch": -30.0, "sun_yaw": 150.0,
        "fog_density": 0.22, "fog_height_falloff": 0.06, "fog_color": (0.8, 0.6, 0.38),
        "cloud_coverage": 0.4, "sky_rayleigh": 1.6, "exposure_bias": 0.3,
    },
    "aurora_night": {
        "keywords": {"aurora": 3, "borealis": 3, "northern": 2, "lights": 1, "polar": 1, "magical": 1},
        "sun_intensity": 0.03, "sun_color": (0.3, 0.85, 0.6), "sun_pitch": -45.0, "sun_yaw": 0.0,
        "fog_density": 0.01, "fog_height_falloff": 0.22, "fog_color": (0.08, 0.2, 0.18),
        "cloud_coverage": 0.1, "sky_rayleigh": 0.25, "exposure_bias": 1.8,
    },
    "morning_haze": {
        "keywords": {"morning": 3, "dawn": 3, "haze": 1, "soft": 2, "gentle": 1, "pastel": 2},
        "sun_intensity": 4.5, "sun_color": (1.0, 0.85, 0.7), "sun_pitch": -15.0, "sun_yaw": 85.0,
        "fog_density": 0.045, "fog_height_falloff": 0.1, "fog_color": (0.88, 0.82, 0.78),
        "cloud_coverage": 0.3, "sky_rayleigh": 1.2, "exposure_bias": 0.25,
    },
    "ashfall": {
        "keywords": {"ash": 3, "ashfall": 3, "volcanic": 1, "smog": 2},
        "sun_intensity": 2.0, "sun_color": (0.75, 0.55, 0.4), "sun_pitch": -40.0, "sun_yaw": 100.0,
        "fog_density": 0.14, "fog_height_falloff": 0.09, "fog_color": (0.45, 0.4, 0.35),
        "cloud_coverage": 0.9, "sky_rayleigh": 1.3, "exposure_bias": 0.45,
    },
    "heat_haze": {
        "keywords": {"heat": 3, "scorching": 3, "swelter": 2, "mirage": 2},
        "sun_intensity": 12.0, "sun_color": (1.0, 0.92, 0.7), "sun_pitch": -75.0, "sun_yaw": 20.0,
        "fog_density": 0.035, "fog_height_falloff": 0.05, "fog_color": (0.9, 0.8, 0.55),
        "cloud_coverage": 0.05, "sky_rayleigh": 1.5, "exposure_bias": -0.1,
    },
    "twilight_blue": {
        "keywords": {"twilight": 3, "bluehour": 3, "evening": 2},
        "sun_intensity": 1.8, "sun_color": (0.45, 0.55, 0.95), "sun_pitch": -4.0, "sun_yaw": 280.0,
        "fog_density": 0.03, "fog_height_falloff": 0.18, "fog_color": (0.25, 0.3, 0.5),
        "cloud_coverage": 0.4, "sky_rayleigh": 0.9, "exposure_bias": 0.8,
    },
    "nuclear_winter": {
        "keywords": {"nuclear": 3, "winter": 1, "fallout": 3, "irradiated": 2},
        "sun_intensity": 0.8, "sun_color": (0.7, 0.75, 0.65), "sun_pitch": -30.0, "sun_yaw": 160.0,
        "fog_density": 0.2, "fog_height_falloff": 0.07, "fog_color": (0.55, 0.58, 0.45),
        "cloud_coverage": 1.0, "sky_rayleigh": 0.4, "exposure_bias": 0.7,
    },
    "carnival_neon": {
        "keywords": {"neon": 3, "cyber": 2, "synth": 2, "electric": 2},
        "sun_intensity": 0.4, "sun_color": (0.7, 0.3, 1.0), "sun_pitch": -25.0, "sun_yaw": 200.0,
        "fog_density": 0.07, "fog_height_falloff": 0.12, "fog_color": (0.25, 0.1, 0.35),
        "cloud_coverage": 0.5, "sky_rayleigh": 0.5, "exposure_bias": 1.2,
    },
    "monsoon_green": {
        "keywords": {"monsoon": 3, "humid": 2, "tropicalstorm": 2},
        "sun_intensity": 2.5, "sun_color": (0.65, 0.8, 0.7), "sun_pitch": -48.0, "sun_yaw": 70.0,
        "fog_density": 0.1, "fog_height_falloff": 0.11, "fog_color": (0.45, 0.6, 0.5),
        "cloud_coverage": 0.95, "sky_rayleigh": 0.85, "exposure_bias": 0.4,
    },
    "crystal_glow": {
        "keywords": {"crystal": 1, "glow": 2, "bioluminescent": 3, "luminous": 2},
        "sun_intensity": 0.6, "sun_color": (0.4, 0.9, 1.0), "sun_pitch": -35.0, "sun_yaw": 40.0,
        "fog_density": 0.04, "fog_height_falloff": 0.16, "fog_color": (0.15, 0.35, 0.4),
        "cloud_coverage": 0.25, "sky_rayleigh": 0.55, "exposure_bias": 1.4,
    },
    "dust_golden": {
        "keywords": {"dusty": 2, "golddust": 3, "amberdust": 2},
        "sun_intensity": 6.0, "sun_color": (1.0, 0.78, 0.4), "sun_pitch": -28.0, "sun_yaw": 140.0,
        "fog_density": 0.09, "fog_height_falloff": 0.08, "fog_color": (0.85, 0.65, 0.35),
        "cloud_coverage": 0.35, "sky_rayleigh": 1.35, "exposure_bias": 0.25,
    },
    "deep_ocean_dark": {
        "keywords": {"abyss": 3, "underdark": 2, "deepsea": 3, "trench": 2},
        "sun_intensity": 0.2, "sun_color": (0.2, 0.35, 0.7), "sun_pitch": -80.0, "sun_yaw": 10.0,
        "fog_density": 0.12, "fog_height_falloff": 0.2, "fog_color": (0.05, 0.1, 0.2),
        "cloud_coverage": 0.7, "sky_rayleigh": 0.35, "exposure_bias": 1.6,
    },
    "underwater_teal": {
        "keywords": {
            "underwater": 5, "submerged": 4, "aquatic": 3, "seafloor": 3,
            "sunken": 3, "kelp": 2, "atlantis": 2,
        },
        "sun_intensity": 2.0, "sun_color": (0.3, 0.75, 0.9), "sun_pitch": -55.0, "sun_yaw": 25.0,
        "fog_density": 0.09, "fog_height_falloff": 0.07, "fog_color": (0.04, 0.32, 0.42),
        "cloud_coverage": 0.15, "sky_rayleigh": 0.55, "exposure_bias": 0.55,
    },
    "cherry_blossom": {
        "keywords": {"cherry": 3, "blossom": 3, "sakura": 3, "spring": 2},
        "sun_intensity": 5.5, "sun_color": (1.0, 0.9, 0.92), "sun_pitch": -50.0, "sun_yaw": 50.0,
        "fog_density": 0.025, "fog_height_falloff": 0.15, "fog_color": (0.95, 0.85, 0.9),
        "cloud_coverage": 0.25, "sky_rayleigh": 1.1, "exposure_bias": 0.15,
    },
    "ember_night": {
        "keywords": {"ember": 3, "embers": 3, "fireflies": 2, "campfire": 1},
        "sun_intensity": 0.15, "sun_color": (1.0, 0.45, 0.15), "sun_pitch": -20.0, "sun_yaw": 300.0,
        "fog_density": 0.05, "fog_height_falloff": 0.14, "fog_color": (0.25, 0.12, 0.08),
        "cloud_coverage": 0.3, "sky_rayleigh": 0.45, "exposure_bias": 1.3,
    },
    "soft_drizzle": {
        "keywords": {"drizzle": 3, "sprinkle": 2, "light_rain": 2},
        "sun_intensity": 3.0, "sun_color": (0.8, 0.82, 0.88), "sun_pitch": -50.0, "sun_yaw": 95.0,
        "fog_density": 0.04, "fog_height_falloff": 0.16, "fog_color": (0.7, 0.74, 0.78),
        "cloud_coverage": 0.75, "sky_rayleigh": 0.85, "exposure_bias": 0.3,
    },
    "hailstorm": {
        "keywords": {"hail": 3, "hailstorm": 3, "ice_storm": 2},
        "sun_intensity": 1.0, "sun_color": (0.7, 0.75, 0.85), "sun_pitch": -40.0, "sun_yaw": 130.0,
        "fog_density": 0.1, "fog_height_falloff": 0.12, "fog_color": (0.55, 0.6, 0.7),
        "cloud_coverage": 1.0, "sky_rayleigh": 0.55, "exposure_bias": 0.55,
    },
    "whiteout": {
        "keywords": {"whiteout": 3, "white_out": 3},
        "sun_intensity": 2.5, "sun_color": (0.95, 0.97, 1.0), "sun_pitch": -25.0, "sun_yaw": 180.0,
        "fog_density": 0.35, "fog_height_falloff": 0.05, "fog_color": (0.92, 0.94, 0.98),
        "cloud_coverage": 1.0, "sky_rayleigh": 0.5, "exposure_bias": 0.9,
    },
    "blood_moon": {
        "keywords": {"bloodmoon": 3, "blood_moon": 3, "lunar_eclipse": 2},
        "sun_intensity": 0.08, "sun_color": (0.95, 0.25, 0.2), "sun_pitch": -55.0, "sun_yaw": 320.0,
        "fog_density": 0.04, "fog_height_falloff": 0.18, "fog_color": (0.25, 0.05, 0.05),
        "cloud_coverage": 0.35, "sky_rayleigh": 0.4, "exposure_bias": 1.7,
    },
    "eclipse": {
        "keywords": {"eclipse": 3, "solar_eclipse": 3},
        "sun_intensity": 0.25, "sun_color": (0.6, 0.55, 0.7), "sun_pitch": -60.0, "sun_yaw": 40.0,
        "fog_density": 0.03, "fog_height_falloff": 0.2, "fog_color": (0.15, 0.12, 0.2),
        "cloud_coverage": 0.2, "sky_rayleigh": 0.35, "exposure_bias": 1.9,
    },
    "toxic_fog": {
        "keywords": {"toxic": 3, "poison": 2, "acid": 2, "green_fog": 2},
        "sun_intensity": 2.0, "sun_color": (0.55, 0.9, 0.4), "sun_pitch": -35.0, "sun_yaw": 110.0,
        "fog_density": 0.2, "fog_height_falloff": 0.08, "fog_color": (0.35, 0.55, 0.25),
        "cloud_coverage": 0.7, "sky_rayleigh": 0.7, "exposure_bias": 0.5,
    },
    "indigo_night": {
        "keywords": {"indigo": 3, "violet_night": 2, "purple": 1},
        "sun_intensity": 0.04, "sun_color": (0.45, 0.35, 0.95), "sun_pitch": -50.0, "sun_yaw": 270.0,
        "fog_density": 0.02, "fog_height_falloff": 0.2, "fog_color": (0.12, 0.08, 0.25),
        "cloud_coverage": 0.15, "sky_rayleigh": 0.3, "exposure_bias": 1.6,
    },
    "desert_night": {
        "keywords": {"desert_night": 3, "cold_desert": 2, "starry_desert": 2},
        "sun_intensity": 0.06, "sun_color": (0.7, 0.75, 1.0), "sun_pitch": -65.0, "sun_yaw": 300.0,
        "fog_density": 0.008, "fog_height_falloff": 0.25, "fog_color": (0.08, 0.1, 0.18),
        "cloud_coverage": 0.05, "sky_rayleigh": 0.25, "exposure_bias": 1.8,
    },
    "humid_dawn": {
        "keywords": {"humid": 2, "dewy": 3, "dawn_mist": 2},
        "sun_intensity": 3.8, "sun_color": (1.0, 0.88, 0.75), "sun_pitch": -12.0, "sun_yaw": 80.0,
        "fog_density": 0.07, "fog_height_falloff": 0.09, "fog_color": (0.85, 0.88, 0.8),
        "cloud_coverage": 0.4, "sky_rayleigh": 1.15, "exposure_bias": 0.35,
    },
    "wildfire_sky": {
        "keywords": {"wildfire": 3, "smoke_sky": 3, "burning": 2},
        "sun_intensity": 4.0, "sun_color": (1.0, 0.45, 0.2), "sun_pitch": -30.0, "sun_yaw": 160.0,
        "fog_density": 0.16, "fog_height_falloff": 0.07, "fog_color": (0.55, 0.3, 0.15),
        "cloud_coverage": 0.85, "sky_rayleigh": 1.5, "exposure_bias": 0.2,
    },
    "clear_midnight": {
        "keywords": {"midnight": 2, "clear_night": 3, "starlight": 2},
        "sun_intensity": 0.02, "sun_color": (0.5, 0.6, 0.95), "sun_pitch": -70.0, "sun_yaw": 0.0,
        "fog_density": 0.005, "fog_height_falloff": 0.25, "fog_color": (0.05, 0.06, 0.12),
        "cloud_coverage": 0.0, "sky_rayleigh": 0.2, "exposure_bias": 2.0,
    },
    "silver_overcast": {
        "keywords": {"silver": 2, "pewter": 2, "soft_grey": 2},
        "sun_intensity": 3.2, "sun_color": (0.88, 0.9, 0.95), "sun_pitch": -52.0, "sun_yaw": 25.0,
        "fog_density": 0.025, "fog_height_falloff": 0.17, "fog_color": (0.75, 0.78, 0.82),
        "cloud_coverage": 0.9, "sky_rayleigh": 0.75, "exposure_bias": 0.25,
    },
    "amber_afternoon": {
        "keywords": {"amber": 3, "afternoon": 2, "honey_light": 2},
        "sun_intensity": 7.0, "sun_color": (1.0, 0.78, 0.45), "sun_pitch": -35.0, "sun_yaw": 220.0,
        "fog_density": 0.018, "fog_height_falloff": 0.2, "fog_color": (0.9, 0.75, 0.5),
        "cloud_coverage": 0.25, "sky_rayleigh": 1.25, "exposure_bias": 0.1,
    },
    "storm_aftermath": {
        "keywords": {"aftermath": 3, "post_storm": 3, "broken_clouds": 2},
        "sun_intensity": 4.5, "sun_color": (0.85, 0.9, 1.0), "sun_pitch": -25.0, "sun_yaw": 100.0,
        "fog_density": 0.035, "fog_height_falloff": 0.14, "fog_color": (0.65, 0.7, 0.78),
        "cloud_coverage": 0.55, "sky_rayleigh": 0.95, "exposure_bias": 0.35,
    },
    "polar_day": {
        "keywords": {"polar_day": 3, "midnight_sun": 3, "arctic_day": 2},
        "sun_intensity": 6.0, "sun_color": (0.95, 0.95, 1.0), "sun_pitch": -8.0, "sun_yaw": 10.0,
        "fog_density": 0.02, "fog_height_falloff": 0.15, "fog_color": (0.85, 0.9, 0.95),
        "cloud_coverage": 0.3, "sky_rayleigh": 0.8, "exposure_bias": 0.4,
    },
}

DEFAULT_WEATHER = "clear_noon"


# ---------------------------------------------------------------------------
# SECTION 3 — PROMPT PARSER (keyword scoring)
# ---------------------------------------------------------------------------

def _score_tokens(tokens, keyword_dict):
    score = 0
    for token in tokens:
        if token in keyword_dict:
            score += keyword_dict[token]
    return score


def parse_prompt(prompt: str) -> dict:
    """
    Parse a natural language prompt into an archetype + weather selection.

    Returns:
        {
          "archetype": str, "archetype_score": int,
          "weather": str, "weather_score": int,
          "noise": dict,          # noise params ready for generate_heightmap
          "pcg_tags": [str],
          "weather_config": dict,
        }
    """
    try:
        tokens = [t.strip(".,!?;:'\"()-").lower() for t in prompt.split()]
        tokens = [t for t in tokens if t]
        prompt_l = (prompt or "").lower()

        # Phrase boosts (multi-word prompts like "under water land")
        phrase_arch = []
        phrase_weather = []
        try:
            import underwater_world
            if underwater_world.prompt_wants_underwater(prompt_l):
                phrase_arch.append(("underwater_seafloor", 12))
                phrase_weather.append(("underwater_teal", 12))
        except Exception:
            if "underwater" in prompt_l or ("under" in tokens and "water" in tokens):
                phrase_arch.append(("underwater_seafloor", 12))
                phrase_weather.append(("underwater_teal", 12))

        if "blood moon" in prompt_l or "bloodmoon" in prompt_l:
            phrase_weather.append(("blood_moon", 10))
        if "golden hour" in prompt_l:
            phrase_weather.append(("golden_hour", 10))
        if "desert" in tokens and ("dune" in tokens or "dunes" in tokens):
            phrase_arch.append(("desert_dunes", 8))

        best_arch, best_arch_score = DEFAULT_ARCHETYPE, 0
        for name, spec in TERRAIN_ARCHETYPES.items():
            s = _score_tokens(tokens, spec["keywords"])
            if s > best_arch_score:
                best_arch, best_arch_score = name, s
        for name, bonus in phrase_arch:
            if name in TERRAIN_ARCHETYPES and best_arch_score < bonus:
                best_arch, best_arch_score = name, bonus
            elif name in TERRAIN_ARCHETYPES:
                # still prefer if close
                if name == "underwater_seafloor":
                    best_arch, best_arch_score = name, max(best_arch_score, bonus)

        best_weather, best_weather_score = DEFAULT_WEATHER, 0
        for name, spec in WEATHER_PRESETS.items():
            s = _score_tokens(tokens, spec["keywords"])
            if s > best_weather_score:
                best_weather, best_weather_score = name, s
        for name, bonus in phrase_weather:
            if name in WEATHER_PRESETS:
                best_weather, best_weather_score = name, max(best_weather_score, bonus)

        arch = TERRAIN_ARCHETYPES[best_arch]
        # Secondary biomes for regional Voronoi masks
        biome_scores = []
        for name, spec in TERRAIN_ARCHETYPES.items():
            s = _score_tokens(tokens, spec["keywords"])
            if s > 0:
                biome_scores.append((s, name))
        biome_scores.sort(reverse=True)
        biomes = []
        for _, n in biome_scores:
            if n not in biomes:
                biomes.append(n)
            if len(biomes) >= 4:
                break
        if best_arch not in biomes:
            biomes.insert(0, best_arch)

        result = {
            "archetype": best_arch,
            "archetype_score": best_arch_score,
            "weather": best_weather,
            "weather_score": best_weather_score,
            "noise": dict(arch["noise"]),
            "pcg_tags": list(arch["pcg_tags"]),
            "structure_tags": list(arch.get("structure_tags") or ARCHETYPE_STRUCTURE_TAGS.get(best_arch, [])),
            "weather_config": dict(WEATHER_PRESETS[best_weather]),
            "biomes": biomes[:4],
        }
        try:
            import structure_library
            # Prefer prompt-aware resolve; seed with archetype structure tags
            result["structures"] = structure_library.resolve_structures(
                best_arch, prompt, preferred_tags=result["structure_tags"])
        except Exception:
            result["structures"] = []
        return result
    except Exception as e:
        unreal.log_error("prompt_matrix.parse_prompt failed: {}".format(e))
        return {
            "archetype": DEFAULT_ARCHETYPE, "archetype_score": 0,
            "weather": DEFAULT_WEATHER, "weather_score": 0,
            "noise": dict(TERRAIN_ARCHETYPES[DEFAULT_ARCHETYPE]["noise"]),
            "pcg_tags": list(TERRAIN_ARCHETYPES[DEFAULT_ARCHETYPE]["pcg_tags"]),
            "weather_config": dict(WEATHER_PRESETS[DEFAULT_WEATHER]),
        }


# ---------------------------------------------------------------------------
# SECTION 4 — SLOPE-ANGLE MATERIAL CALCULATION
# ---------------------------------------------------------------------------

# Material layer bands by slope angle (degrees). Ordered ascending.
SLOPE_MATERIAL_BANDS = [
    (0.0,  12.0, "layer_grass"),
    (12.0, 28.0, "layer_dirt"),
    (28.0, 48.0, "layer_rock"),
    (48.0, 90.1, "layer_cliff"),
]


def slope_angle_degrees(h_left, h_right, h_down, h_up, xy_scale, z_scale) -> float:
    """
    Central-difference slope angle at a pixel, in degrees.

    Args:
        h_left/h_right/h_down/h_up: neighboring heights (uint16 0..65535).
        xy_scale: world units per pixel (e.g. 100.0 for default landscape).
        z_scale:  world units spanned by the full 0..65535 height range.
    """
    try:
        norm = z_scale / 65535.0
        dzdx = (h_right - h_left) * norm / (2.0 * xy_scale)
        dzdy = (h_up - h_down) * norm / (2.0 * xy_scale)
        gradient = math.sqrt(dzdx * dzdx + dzdy * dzdy)
        return math.degrees(math.atan(gradient))
    except Exception as e:
        unreal.log_error("prompt_matrix.slope_angle_degrees failed: {}".format(e))
        return 0.0


def material_for_slope(angle_deg: float) -> str:
    for lo, hi, layer in SLOPE_MATERIAL_BANDS:
        if lo <= angle_deg < hi:
            return layer
    return SLOPE_MATERIAL_BANDS[-1][2]


def compute_slope_map(pixels, width: int, height: int,
                      xy_scale: float = 100.0, z_scale: float = 51200.0):
    """
    Generator producing a per-pixel material layer map, frame-budget friendly.

    Yields ("progress", float) periodically; final yield is
    ("result", list_of_layer_name_indices, layer_names).

    Designed to be driven by art_engine's budgeted runner: the caller wraps
    this inside a budget-checked loop, or iterates directly for offline use.
    """
    try:
        layer_names = [b[2] for b in SLOPE_MATERIAL_BANDS]
        layer_index = {name: i for i, name in enumerate(layer_names)}
        out = [0] * (width * height)

        for y in range(height):
            y0 = max(0, y - 1) * width
            y1 = min(height - 1, y + 1) * width
            row = y * width
            for x in range(width):
                xl = row + max(0, x - 1)
                xr = row + min(width - 1, x + 1)
                angle = slope_angle_degrees(
                    pixels[xl], pixels[xr], pixels[y0 + x], pixels[y1 + x],
                    xy_scale, z_scale)
                out[row + x] = layer_index[material_for_slope(angle)]
            if (y & 31) == 0:
                yield ("progress", y / float(height))

        yield ("result", out, layer_names)
    except Exception as e:
        unreal.log_error("prompt_matrix.compute_slope_map failed: {}".format(e))
        yield ("result", [0] * (width * height), [b[2] for b in SLOPE_MATERIAL_BANDS])


# ---------------------------------------------------------------------------
# SECTION 5 — ASSET MANIFEST LOOKUP (PCG spawn tables)
# ---------------------------------------------------------------------------

_MANIFEST_CACHE = None
MANIFEST_FILENAME = "asset_manifest.json"


def _manifest_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MANIFEST_FILENAME)


def load_manifest(force_reload: bool = False) -> dict:
    """Load and cache asset_manifest.json living beside this module."""
    global _MANIFEST_CACHE
    try:
        if _MANIFEST_CACHE is not None and not force_reload:
            return _MANIFEST_CACHE
        path = _manifest_path()
        if not os.path.isfile(path):
            unreal.log_warning("prompt_matrix: manifest missing at {}".format(path))
            _MANIFEST_CACHE = {"assets": {}}
            return _MANIFEST_CACHE
        with open(path, "r", encoding="utf-8") as f:
            _MANIFEST_CACHE = json.load(f)
        if "assets" not in _MANIFEST_CACHE:
            _MANIFEST_CACHE["assets"] = {}
        return _MANIFEST_CACHE
    except Exception as e:
        unreal.log_error("prompt_matrix.load_manifest failed: {}".format(e))
        _MANIFEST_CACHE = {"assets": {}}
        return _MANIFEST_CACHE


def resolve_assets(pcg_tags) -> list:
    """
    Resolve archetype pcg_tags against the manifest.

    asset_path values are remapped through content_library.resolve_asset_path()
    so a single per-project content_root controls where meshes live.

    Returns a list of spawn entries:
        [{"tag", "asset_path", "density", "scale_min", "scale_max",
          "align_to_slope", "max_slope_deg"}]
    Missing tags are logged and skipped (never fatal).
    """
    results = []
    try:
        import content_library
        manifest = load_manifest()
        assets = manifest.get("assets", {})
        for tag in pcg_tags:
            entry = assets.get(tag)
            if entry is None:
                unreal.log_warning("prompt_matrix: no manifest entry for tag '{}'".format(tag))
                continue
            results.append({
                "tag": tag,
                "asset_path": content_library.resolve_asset_path(entry.get("asset_path", "")),
                "density": float(entry.get("density", 0.1)),
                "scale_min": float(entry.get("scale_min", 0.8)),
                "scale_max": float(entry.get("scale_max", 1.2)),
                "align_to_slope": bool(entry.get("align_to_slope", False)),
                "max_slope_deg": float(entry.get("max_slope_deg", 35.0)),
            })
        return results
    except Exception as e:
        unreal.log_error("prompt_matrix.resolve_assets failed: {}".format(e))
        return results


# ---------------------------------------------------------------------------
# SECTION 6 — WEATHER PRESET APPLICATION (MAIN THREAD, hasattr-guarded)
# ---------------------------------------------------------------------------

def _find_actor_of_class(class_names):
    """Locate the first level actor whose class name matches (5.8 subsystem)."""
    try:
        actors = []
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actors = subsys.get_all_level_actors()
        elif hasattr(unreal, "EditorLevelLibrary"):
            actors = unreal.EditorLevelLibrary.get_all_level_actors()
        for a in actors:
            try:
                if a.get_class().get_name() in class_names:
                    return a
            except Exception:
                continue
        return None
    except Exception as e:
        unreal.log_error("prompt_matrix._find_actor_of_class failed: {}".format(e))
        return None


def apply_weather_preset(preset_name: str) -> bool:
    """
    Apply one of the 12 weather presets to the level's lighting stack.
    MAIN THREAD ONLY. Every unreal endpoint is hasattr()-verified.
    """
    if not _HAS_UNREAL:
        unreal.log("Stub mode: would apply weather '{}'".format(preset_name))
        return True
    try:
        preset = WEATHER_PRESETS.get(preset_name)
        if preset is None:
            unreal.log_error("prompt_matrix: unknown weather preset '{}'".format(preset_name))
            return False

        applied = []

        # --- Directional light (sun) ---
        sun = _find_actor_of_class(("DirectionalLight",))
        if sun is not None:
            try:
                comp = sun.get_component_by_class(unreal.DirectionalLightComponent) \
                    if hasattr(unreal, "DirectionalLightComponent") else None
                if comp is not None:
                    if hasattr(comp, "set_intensity"):
                        comp.set_intensity(preset["sun_intensity"])
                    if hasattr(comp, "set_light_color") and hasattr(unreal, "LinearColor"):
                        r, g, b = preset["sun_color"]
                        comp.set_light_color(unreal.LinearColor(r, g, b, 1.0))
                sun.set_actor_rotation(
                    unreal.Rotator(0.0, preset["sun_pitch"], preset["sun_yaw"]), False)
                applied.append("sun")
            except Exception as sun_e:
                unreal.log_warning("weather: sun apply failed: {}".format(sun_e))

        # --- Exponential height fog ---
        fog = _find_actor_of_class(("ExponentialHeightFog",))
        if fog is not None:
            try:
                comp = fog.get_component_by_class(unreal.ExponentialHeightFogComponent) \
                    if hasattr(unreal, "ExponentialHeightFogComponent") else None
                if comp is not None:
                    if hasattr(comp, "set_fog_density"):
                        comp.set_fog_density(preset["fog_density"])
                    if hasattr(comp, "set_fog_height_falloff"):
                        comp.set_fog_height_falloff(preset["fog_height_falloff"])
                    if hasattr(comp, "set_fog_inscattering_color") and hasattr(unreal, "LinearColor"):
                        r, g, b = preset["fog_color"]
                        comp.set_fog_inscattering_color(unreal.LinearColor(r, g, b, 1.0))
                applied.append("fog")
            except Exception as fog_e:
                unreal.log_warning("weather: fog apply failed: {}".format(fog_e))

        # --- Sky atmosphere ---
        sky = _find_actor_of_class(("SkyAtmosphere",))
        if sky is not None:
            try:
                comp = sky.get_component_by_class(unreal.SkyAtmosphereComponent) \
                    if hasattr(unreal, "SkyAtmosphereComponent") else None
                if comp is not None and hasattr(comp, "set_rayleigh_scattering_scale"):
                    comp.set_rayleigh_scattering_scale(preset["sky_rayleigh"])
                applied.append("sky")
            except Exception as sky_e:
                unreal.log_warning("weather: sky apply failed: {}".format(sky_e))

        # --- Volumetric clouds (coverage via editor property, name-guarded) ---
        clouds = _find_actor_of_class(("VolumetricCloud",))
        if clouds is not None:
            try:
                comp = clouds.get_component_by_class(unreal.VolumetricCloudComponent) \
                    if hasattr(unreal, "VolumetricCloudComponent") else None
                if comp is not None and hasattr(comp, "set_editor_property"):
                    # layer_bottom_altitude is stable; coverage is material-driven,
                    # so we scale layer height as a coverage proxy when the
                    # material parameter route is unavailable.
                    comp.set_editor_property(
                        "layer_height", 4.0 + 6.0 * preset["cloud_coverage"])
                applied.append("clouds")
            except Exception as cloud_e:
                unreal.log_warning("weather: clouds apply failed: {}".format(cloud_e))

        # --- Post process exposure ---
        ppv = _find_actor_of_class(("PostProcessVolume",))
        if ppv is not None:
            try:
                settings = ppv.get_editor_property("settings")
                if hasattr(settings, "set_editor_property"):
                    settings.set_editor_property("override_auto_exposure_bias", True)
                    settings.set_editor_property("auto_exposure_bias", preset["exposure_bias"])
                    ppv.set_editor_property("settings", settings)
                applied.append("exposure")
            except Exception as ppv_e:
                unreal.log_warning("weather: exposure apply failed: {}".format(ppv_e))

        unreal.log("WorldPromptEngine: weather '{}' applied to [{}]".format(
            preset_name, ", ".join(applied) if applied else "nothing found"))
        return bool(applied)
    except Exception as e:
        unreal.log_error("prompt_matrix.apply_weather_preset failed: {}".format(e))
        return False
