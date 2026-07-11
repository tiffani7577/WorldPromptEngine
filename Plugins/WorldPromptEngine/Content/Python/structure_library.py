"""
structure_library.py — WorldPromptEngine structure catalog + placer (UE 5.8)

Base-X ships hundreds of authored meshes. We can't invent that art pack from
nothing — but we CAN:

  1. Define a large structure catalog (types, biomes, density, slope rules).
  2. Prefer real meshes from the active content_root when present.
  3. Fall back to composed Engine BasicShapes proxies so generations still
     place castles, ruins, crystals, arches, monoliths, etc. immediately.

MAIN THREAD ONLY for spawn_structures().
"""

from __future__ import annotations

import math
import random

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


# Engine primitives used as proxies when project meshes are missing.
_PROXY = {
    "cube": "/Engine/BasicShapes/Cube.Cube",
    "sphere": "/Engine/BasicShapes/Sphere.Sphere",
    "cylinder": "/Engine/BasicShapes/Cylinder.Cylinder",
    "cone": "/Engine/BasicShapes/Cone.Cone",
    "plane": "/Engine/BasicShapes/Plane.Plane",
}

# ---------------------------------------------------------------------------
# Structure catalog
# Each entry:
#   category, keywords, archetypes (or ["*"]), count range, slope limits,
#   height band (0-1 normalized), preferred mesh path under content root,
#   proxy recipe: list of {shape, offset=(x,y,z), scale=(x,y,z), yaw}
# ---------------------------------------------------------------------------

STRUCTURE_CATALOG = {
    # --- Settlements / architecture ---
    "stone_keep": {
        "category": "architecture", "keywords": {"castle": 3, "keep": 3, "fortress": 3, "citadel": 2},
        "archetypes": ["rolling_hills", "highland_moors", "fjord_valleys", "alpine_peaks", "steppe_ridges"],
        "count": (1, 2), "max_slope": 18, "h_min": 0.35, "h_max": 0.75,
        "mesh": "Props/SM_StoneKeep_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 200), "scale": (6, 6, 4), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 450), "scale": (4, 4, 2), "yaw": 0},
            {"shape": "cylinder", "offset": (350, 350, 250), "scale": (1.2, 1.2, 5), "yaw": 0},
            {"shape": "cylinder", "offset": (-350, 350, 250), "scale": (1.2, 1.2, 5), "yaw": 0},
            {"shape": "cylinder", "offset": (350, -350, 250), "scale": (1.2, 1.2, 5), "yaw": 0},
            {"shape": "cylinder", "offset": (-350, -350, 250), "scale": (1.2, 1.2, 5), "yaw": 0},
            {"shape": "cone", "offset": (350, 350, 520), "scale": (1.4, 1.4, 1.5), "yaw": 0},
        ],
    },
    "ruined_tower": {
        "category": "ruins", "keywords": {"ruin": 3, "ruins": 3, "tower": 2, "crumbling": 2, "broken": 1},
        "archetypes": ["*"],
        "count": (2, 5), "max_slope": 28, "h_min": 0.25, "h_max": 0.85,
        "mesh": "Props/SM_RuinedTower_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 250), "scale": (1.5, 1.5, 5), "yaw": 15},
            {"shape": "cube", "offset": (80, -40, 420), "scale": (1.2, 0.6, 1.5), "yaw": 35},
            {"shape": "cube", "offset": (-60, 90, 80), "scale": (1.0, 0.8, 0.6), "yaw": 10},
        ],
    },
    "watchtower": {
        "category": "architecture", "keywords": {"watchtower": 3, "lookout": 2, "sentry": 2},
        "archetypes": ["rolling_hills", "coastal_cliffs", "steppe_ridges", "savanna_plains", "canyon_mesas"],
        "count": (1, 3), "max_slope": 22, "h_min": 0.4, "h_max": 0.9,
        "mesh": "Props/SM_Watchtower_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 300), "scale": (1.0, 1.0, 6), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 620), "scale": (2.2, 2.2, 0.8), "yaw": 0},
        ],
    },
    "village_hut": {
        "category": "settlement", "keywords": {"village": 3, "hut": 3, "cottage": 2, "hamlet": 2, "settlement": 2},
        "archetypes": ["rolling_hills", "dense_rainforest", "redwood_forest", "savanna_plains", "highland_moors", "tropical_islands"],
        "count": (4, 10), "max_slope": 16, "h_min": 0.2, "h_max": 0.55,
        "mesh": "Props/SM_Hut_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 80), "scale": (2.2, 2.0, 1.4), "yaw": 0},
            {"shape": "cone", "offset": (0, 0, 200), "scale": (2.6, 2.6, 1.4), "yaw": 0},
        ],
    },
    "longhouse": {
        "category": "settlement", "keywords": {"longhouse": 3, "nordic": 2, "viking": 2, "hall": 2},
        "archetypes": ["fjord_valleys", "highland_moors", "tundra_flats", "glacier_fields"],
        "count": (1, 3), "max_slope": 14, "h_min": 0.2, "h_max": 0.5,
        "mesh": "Props/SM_Longhouse_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 120), "scale": (5, 2.2, 2), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 240), "scale": (5.2, 2.4, 0.4), "yaw": 0},
        ],
    },
    "stone_circle": {
        "category": "megalith", "keywords": {"stonehenge": 3, "circle": 2, "megalith": 3, "ritual": 2, "druid": 2},
        "archetypes": ["highland_moors", "rolling_hills", "steppe_ridges", "tundra_flats"],
        "count": (1, 2), "max_slope": 12, "h_min": 0.25, "h_max": 0.55,
        "mesh": "Props/SM_StoneCircle_01",
        "proxy": [
            {"shape": "cube", "offset": (400, 0, 150), "scale": (0.6, 0.4, 3), "yaw": 0},
            {"shape": "cube", "offset": (-400, 0, 150), "scale": (0.6, 0.4, 3), "yaw": 0},
            {"shape": "cube", "offset": (0, 400, 150), "scale": (0.6, 0.4, 3), "yaw": 90},
            {"shape": "cube", "offset": (0, -400, 150), "scale": (0.6, 0.4, 3), "yaw": 90},
            {"shape": "cube", "offset": (280, 280, 150), "scale": (0.6, 0.4, 3), "yaw": 45},
            {"shape": "cube", "offset": (-280, -280, 150), "scale": (0.6, 0.4, 3), "yaw": 45},
        ],
    },
    "obelisk": {
        "category": "megalith", "keywords": {"obelisk": 3, "monolith": 3, "pillar": 2, "stele": 2},
        "archetypes": ["desert_dunes", "salt_flats", "crater_wastes", "canyon_mesas", "karst_towers"],
        "count": (2, 6), "max_slope": 20, "h_min": 0.2, "h_max": 0.7,
        "mesh": "Props/SM_Obelisk_01",
        "proxy": [{"shape": "cube", "offset": (0, 0, 300), "scale": (0.7, 0.7, 6), "yaw": 0}],
    },
    "temple_ruin": {
        "category": "ruins", "keywords": {"temple": 3, "shrine": 2, "sanctum": 2, "ancient": 2},
        "archetypes": ["dense_rainforest", "karst_towers", "desert_dunes", "tropical_islands", "canyon_mesas"],
        "count": (1, 2), "max_slope": 18, "h_min": 0.25, "h_max": 0.65,
        "mesh": "Props/SM_TempleRuin_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 50), "scale": (8, 8, 0.5), "yaw": 0},
            {"shape": "cylinder", "offset": (-250, -250, 200), "scale": (0.8, 0.8, 4), "yaw": 0},
            {"shape": "cylinder", "offset": (250, -250, 200), "scale": (0.8, 0.8, 4), "yaw": 0},
            {"shape": "cylinder", "offset": (-250, 250, 200), "scale": (0.8, 0.8, 4), "yaw": 0},
            {"shape": "cylinder", "offset": (250, 250, 200), "scale": (0.8, 0.8, 3), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 280), "scale": (3, 3, 0.4), "yaw": 0},
        ],
    },
    "bridge_arch": {
        "category": "architecture", "keywords": {"bridge": 3, "arch": 2, "crossing": 2},
        "archetypes": ["fjord_valleys", "canyon_mesas", "karst_towers", "coastal_cliffs", "terraced_valleys"],
        "count": (1, 2), "max_slope": 35, "h_min": 0.15, "h_max": 0.6,
        "mesh": "Props/SM_BridgeArch_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 180), "scale": (8, 1.2, 0.4), "yaw": 0},
            {"shape": "cylinder", "offset": (-300, 0, 100), "scale": (0.6, 0.6, 2), "yaw": 0},
            {"shape": "cylinder", "offset": (300, 0, 100), "scale": (0.6, 0.6, 2), "yaw": 0},
        ],
    },
    "dock_pier": {
        "category": "settlement", "keywords": {"dock": 3, "pier": 3, "harbor": 2, "wharf": 2},
        "archetypes": ["coastal_cliffs", "tropical_islands", "fjord_valleys", "swamp_wetlands"],
        "count": (1, 3), "max_slope": 10, "h_min": 0.05, "h_max": 0.35,
        "mesh": "Props/SM_Dock_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 40), "scale": (6, 1.5, 0.3), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 20), "scale": (0.3, 0.3, 1.2), "yaw": 0},
        ],
    },

    # --- Geological / natural formations as "structures" ---
    "crystal_spire": {
        "category": "geological", "keywords": {"crystal": 3, "spire": 2, "gem": 2, "quartz": 2, "iridescent": 2},
        "archetypes": ["karst_towers", "crater_wastes", "alpine_peaks", "volcanic_badlands", "glacier_fields"],
        "count": (3, 8), "max_slope": 40, "h_min": 0.4, "h_max": 0.95,
        "mesh": "Props/SM_CrystalSpire_01",
        "proxy": [
            {"shape": "cone", "offset": (0, 0, 250), "scale": (1.2, 1.2, 5), "yaw": 0},
            {"shape": "cone", "offset": (60, 40, 180), "scale": (0.7, 0.7, 3.5), "yaw": 20},
            {"shape": "cone", "offset": (-50, -30, 160), "scale": (0.5, 0.5, 3), "yaw": -15},
        ],
    },
    "floating_boulder": {
        "category": "mystical", "keywords": {"floating": 3, "levitating": 3, "skyrock": 2, "suspended": 2},
        "archetypes": ["karst_towers", "crater_wastes", "alpine_peaks", "volcanic_badlands"],
        "count": (2, 5), "max_slope": 90, "h_min": 0.5, "h_max": 1.0,
        "mesh": "Props/SM_FloatingRock_01",
        "proxy": [
            {"shape": "sphere", "offset": (0, 0, 800), "scale": (3, 2.2, 2), "yaw": 0},
            {"shape": "cube", "offset": (40, -20, 920), "scale": (1.5, 1.2, 0.8), "yaw": 25},
        ],
    },
    "arch_rock": {
        "category": "geological", "keywords": {"arch": 3, "natural": 1, "hoodoo": 2, "window": 1},
        "archetypes": ["canyon_mesas", "desert_dunes", "coastal_cliffs", "karst_towers"],
        "count": (1, 3), "max_slope": 30, "h_min": 0.3, "h_max": 0.8,
        "mesh": "Props/SM_ArchRock_01",
        "proxy": [
            {"shape": "cube", "offset": (-150, 0, 200), "scale": (1, 1.5, 4), "yaw": 0},
            {"shape": "cube", "offset": (150, 0, 200), "scale": (1, 1.5, 4), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 420), "scale": (4, 1.5, 1), "yaw": 0},
        ],
    },
    "mesa_butte": {
        "category": "geological", "keywords": {"butte": 3, "mesa": 2, "table": 1},
        "archetypes": ["canyon_mesas", "desert_dunes", "steppe_ridges"],
        "count": (1, 3), "max_slope": 25, "h_min": 0.45, "h_max": 0.9,
        "mesh": "Props/SM_Butte_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 200), "scale": (4, 4, 4), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 420), "scale": (5, 5, 0.5), "yaw": 0},
        ],
    },
    "lava_spine": {
        "category": "geological", "keywords": {"lava": 2, "spine": 2, "basalt": 2, "column": 2},
        "archetypes": ["volcanic_badlands", "crater_wastes"],
        "count": (3, 7), "max_slope": 45, "h_min": 0.35, "h_max": 0.95,
        "mesh": "Props/SM_LavaSpine_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 200), "scale": (0.8, 0.8, 4), "yaw": 10},
            {"shape": "cylinder", "offset": (70, 40, 160), "scale": (0.5, 0.5, 3.2), "yaw": -8},
        ],
    },
    "ice_monolith": {
        "category": "geological", "keywords": {"ice": 2, "frozen": 1, "glacial": 2},
        "archetypes": ["glacier_fields", "tundra_flats", "alpine_peaks", "fjord_valleys"],
        "count": (2, 6), "max_slope": 30, "h_min": 0.35, "h_max": 0.9,
        "mesh": "Props/SM_IceMonolith_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 250), "scale": (1.2, 0.9, 5), "yaw": 12},
            {"shape": "cube", "offset": (40, 20, 180), "scale": (0.7, 0.5, 3.5), "yaw": -20},
        ],
    },
    "mangrove_root": {
        "category": "natural", "keywords": {"mangrove": 3, "roots": 2},
        "archetypes": ["swamp_wetlands", "tropical_islands", "dense_rainforest"],
        "count": (4, 9), "max_slope": 12, "h_min": 0.05, "h_max": 0.35,
        "mesh": "Props/SM_MangroveRoot_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 120), "scale": (0.5, 0.5, 2.5), "yaw": 0},
            {"shape": "cube", "offset": (80, 0, 40), "scale": (1.5, 0.25, 0.25), "yaw": 20},
            {"shape": "cube", "offset": (-70, 40, 50), "scale": (1.3, 0.25, 0.25), "yaw": -30},
        ],
    },
    "giant_bone": {
        "category": "mystical", "keywords": {"bone": 3, "skeleton": 3, "fossil": 2, "colossal": 1},
        "archetypes": ["desert_dunes", "crater_wastes", "salt_flats", "volcanic_badlands"],
        "count": (1, 3), "max_slope": 25, "h_min": 0.15, "h_max": 0.55,
        "mesh": "Props/SM_GiantBone_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 80), "scale": (0.6, 0.6, 5), "yaw": 70},
            {"shape": "sphere", "offset": (220, 0, 100), "scale": (1.2, 1.0, 1.0), "yaw": 0},
        ],
    },
    "shipwreck": {
        "category": "ruins", "keywords": {"shipwreck": 3, "wreck": 3, "ship": 2, "boat": 1},
        "archetypes": ["coastal_cliffs", "tropical_islands", "fjord_valleys"],
        "count": (1, 2), "max_slope": 18, "h_min": 0.05, "h_max": 0.4,
        "mesh": "Props/SM_Shipwreck_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 80), "scale": (6, 2, 1.2), "yaw": 15},
            {"shape": "cube", "offset": (-50, 0, 160), "scale": (1.5, 0.3, 3), "yaw": 15},
        ],
    },
    "windmill": {
        "category": "settlement", "keywords": {"windmill": 3, "mill": 2},
        "archetypes": ["rolling_hills", "savanna_plains", "steppe_ridges", "highland_moors"],
        "count": (1, 2), "max_slope": 14, "h_min": 0.25, "h_max": 0.55,
        "mesh": "Props/SM_Windmill_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 250), "scale": (1.4, 1.4, 5), "yaw": 0},
            {"shape": "cone", "offset": (0, 0, 520), "scale": (1.8, 1.8, 1.5), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 480), "scale": (4, 0.3, 0.3), "yaw": 25},
        ],
    },
    "lighthouse": {
        "category": "architecture", "keywords": {"lighthouse": 3, "beacon": 2},
        "archetypes": ["coastal_cliffs", "tropical_islands", "fjord_valleys"],
        "count": (1, 1), "max_slope": 20, "h_min": 0.35, "h_max": 0.85,
        "mesh": "Props/SM_Lighthouse_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 400), "scale": (1.6, 1.6, 8), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 820), "scale": (2.2, 2.2, 1), "yaw": 0},
            {"shape": "sphere", "offset": (0, 0, 920), "scale": (1.2, 1.2, 1.2), "yaw": 0},
        ],
    },
    "pagoda": {
        "category": "architecture", "keywords": {"pagoda": 3, "asian": 1, "temple": 1},
        "archetypes": ["karst_towers", "terraced_valleys", "dense_rainforest", "highland_moors"],
        "count": (1, 2), "max_slope": 16, "h_min": 0.3, "h_max": 0.7,
        "mesh": "Props/SM_Pagoda_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 80), "scale": (3, 3, 1.2), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 200), "scale": (2.4, 2.4, 1.0), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 300), "scale": (1.8, 1.8, 0.9), "yaw": 0},
            {"shape": "cone", "offset": (0, 0, 380), "scale": (1.5, 1.5, 1.2), "yaw": 0},
        ],
    },
    "pyramid": {
        "category": "architecture", "keywords": {"pyramid": 3, "ziggurat": 3},
        "archetypes": ["desert_dunes", "jungle_ruins", "canyon_mesas", "dense_rainforest"],
        "count": (1, 1), "max_slope": 14, "h_min": 0.2, "h_max": 0.55,
        "mesh": "Props/SM_Pyramid_01",
        "proxy": [{"shape": "cone", "offset": (0, 0, 250), "scale": (8, 8, 5), "yaw": 0}],
    },
    "camp_tents": {
        "category": "settlement", "keywords": {"camp": 3, "tent": 3, "encampment": 2, "caravan": 2},
        "archetypes": ["desert_dunes", "savanna_plains", "steppe_ridges", "rolling_hills", "tundra_flats"],
        "count": (3, 7), "max_slope": 14, "h_min": 0.15, "h_max": 0.5,
        "mesh": "Props/SM_Tent_01",
        "proxy": [{"shape": "cone", "offset": (0, 0, 90), "scale": (1.8, 1.8, 1.8), "yaw": 0}],
    },
    "oil_derrick": {
        "category": "industrial", "keywords": {"derrick": 3, "oil": 2, "industrial": 2, "rig": 2},
        "archetypes": ["desert_dunes", "salt_flats", "crater_wastes", "steppe_ridges"],
        "count": (1, 3), "max_slope": 12, "h_min": 0.15, "h_max": 0.45,
        "mesh": "Props/SM_OilDerrick_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 300), "scale": (0.4, 0.4, 6), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 50), "scale": (3, 3, 0.4), "yaw": 0},
            {"shape": "cube", "offset": (100, 0, 200), "scale": (2.5, 0.25, 0.25), "yaw": 35},
        ],
    },
    "radar_dish": {
        "category": "industrial", "keywords": {"radar": 3, "dish": 2, "antenna": 2, "sci-fi": 2, "scifi": 2},
        "archetypes": ["crater_wastes", "salt_flats", "tundra_flats", "desert_dunes"],
        "count": (1, 2), "max_slope": 10, "h_min": 0.2, "h_max": 0.55,
        "mesh": "Props/SM_RadarDish_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 150), "scale": (0.5, 0.5, 3), "yaw": 0},
            {"shape": "sphere", "offset": (0, 0, 320), "scale": (3, 3, 1.2), "yaw": 0},
        ],
    },
    "portal_ring": {
        "category": "mystical", "keywords": {"portal": 3, "gate": 2, "rift": 3, "wormhole": 2, "magic": 2},
        "archetypes": ["crater_wastes", "karst_towers", "volcanic_badlands", "alpine_peaks"],
        "count": (1, 2), "max_slope": 20, "h_min": 0.35, "h_max": 0.8,
        "mesh": "Props/SM_PortalRing_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 250), "scale": (4, 0.4, 4), "yaw": 90},
        ],
    },
    "totem": {
        "category": "mystical", "keywords": {"totem": 3, "idol": 2, "spirit": 1},
        "archetypes": ["dense_rainforest", "redwood_forest", "highland_moors", "tundra_flats", "savanna_plains"],
        "count": (2, 5), "max_slope": 20, "h_min": 0.2, "h_max": 0.65,
        "mesh": "Props/SM_Totem_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 200), "scale": (0.5, 0.5, 4), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 420), "scale": (1.2, 0.8, 1.0), "yaw": 0},
        ],
    },
    "waterfall_rocks": {
        "category": "natural", "keywords": {"waterfall": 3, "cascade": 2, "falls": 2},
        "archetypes": ["fjord_valleys", "alpine_peaks", "dense_rainforest", "redwood_forest", "karst_towers"],
        "count": (1, 3), "max_slope": 55, "h_min": 0.45, "h_max": 0.95,
        "mesh": "FX/BP_WaterfallMarker",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 200), "scale": (3, 1.5, 4), "yaw": 0},
            {"shape": "cube", "offset": (0, 80, 50), "scale": (2.5, 2, 0.4), "yaw": 0},
        ],
    },
    "coral_stack": {
        "category": "natural", "keywords": {"coral": 3, "reef": 3},
        "archetypes": ["tropical_islands", "coastal_cliffs"],
        "count": (3, 8), "max_slope": 20, "h_min": 0.02, "h_max": 0.3,
        "mesh": "Props/SM_Coral_01",
        "proxy": [
            {"shape": "cone", "offset": (0, 0, 60), "scale": (1.2, 1.2, 1.5), "yaw": 0},
            {"shape": "sphere", "offset": (40, 20, 90), "scale": (0.8, 0.8, 0.8), "yaw": 0},
        ],
    },
    "barn": {
        "category": "settlement", "keywords": {"barn": 3, "farm": 3, "farmhouse": 2},
        "archetypes": ["rolling_hills", "savanna_plains", "steppe_ridges", "terraced_valleys"],
        "count": (1, 3), "max_slope": 12, "h_min": 0.2, "h_max": 0.5,
        "mesh": "Props/SM_Barn_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 120), "scale": (4, 3, 2.2), "yaw": 0},
            {"shape": "cube", "offset": (0, 0, 250), "scale": (4.2, 3.2, 0.5), "yaw": 0},
        ],
    },
    "mine_entrance": {
        "category": "architecture", "keywords": {"mine": 3, "entrance": 1, "tunnel": 2, "shaft": 2},
        "archetypes": ["alpine_peaks", "canyon_mesas", "karst_towers", "volcanic_badlands", "highland_moors"],
        "count": (1, 2), "max_slope": 35, "h_min": 0.35, "h_max": 0.8,
        "mesh": "Props/SM_MineEntrance_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 100), "scale": (3, 1, 2), "yaw": 0},
            {"shape": "cylinder", "offset": (0, 40, 100), "scale": (1.5, 0.2, 1.5), "yaw": 90},
        ],
    },
    "graveyard": {
        "category": "ruins", "keywords": {"graveyard": 3, "cemetery": 3, "tomb": 2, "grave": 2},
        "archetypes": ["highland_moors", "rolling_hills", "dense_fog_woods", "crater_wastes"],
        "count": (1, 2), "max_slope": 14, "h_min": 0.2, "h_max": 0.5,
        "mesh": "Props/SM_Graveyard_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 60), "scale": (0.4, 0.15, 1.2), "yaw": 0},
            {"shape": "cube", "offset": (120, 40, 50), "scale": (0.35, 0.12, 1.0), "yaw": 10},
            {"shape": "cube", "offset": (-100, 80, 55), "scale": (0.35, 0.12, 1.1), "yaw": -8},
            {"shape": "cube", "offset": (40, -90, 45), "scale": (0.3, 0.1, 0.9), "yaw": 20},
        ],
    },
    "wizard_tower": {
        "category": "mystical", "keywords": {"wizard": 3, "mage": 3, "sorcerer": 2, "arcane": 2},
        "archetypes": ["alpine_peaks", "karst_towers", "highland_moors", "dense_rainforest"],
        "count": (1, 1), "max_slope": 22, "h_min": 0.45, "h_max": 0.9,
        "mesh": "Props/SM_WizardTower_01",
        "proxy": [
            {"shape": "cylinder", "offset": (0, 0, 400), "scale": (1.8, 1.8, 8), "yaw": 0},
            {"shape": "cone", "offset": (0, 0, 820), "scale": (2.4, 2.4, 2), "yaw": 0},
            {"shape": "sphere", "offset": (0, 0, 920), "scale": (0.8, 0.8, 0.8), "yaw": 0},
        ],
    },
    "dragon_perch": {
        "category": "mystical", "keywords": {"dragon": 3, "perch": 2, "wyrm": 2},
        "archetypes": ["alpine_peaks", "volcanic_badlands", "karst_towers", "canyon_mesas"],
        "count": (1, 2), "max_slope": 40, "h_min": 0.65, "h_max": 1.0,
        "mesh": "Props/SM_DragonPerch_01",
        "proxy": [
            {"shape": "cube", "offset": (0, 0, 150), "scale": (4, 3, 2), "yaw": 0},
            {"shape": "cylinder", "offset": (0, 0, 350), "scale": (0.8, 0.8, 3), "yaw": 0},
        ],
    },
}

# Extra archetype names referenced above that we'll add to prompt_matrix
EXTRA_ARCHETYPE_ALIASES = {
    "jungle_ruins": "dense_rainforest",
    "dense_fog_woods": "redwood_forest",
}


def catalog_stats() -> dict:
    cats = {}
    for name, spec in STRUCTURE_CATALOG.items():
        cats.setdefault(spec["category"], 0)
        cats[spec["category"]] += 1
    return {
        "structure_types": len(STRUCTURE_CATALOG),
        "categories": cats,
    }


def resolve_structures(archetype: str, prompt: str = "", max_types: int = 8,
                       preferred_tags=None) -> list:
    """
    Pick structure types for an archetype + optional prompt keyword boosts.
    preferred_tags (from archetype structure_tags / manifest) are boosted.
    Returns list of {name, spec, weight, forge_family}.
    """
    tokens = [t.strip(".,!?;:'\"()-").lower() for t in (prompt or "").split() if t.strip()]
    preferred = set(preferred_tags or [])
    scored = []
    for name, spec in STRUCTURE_CATALOG.items():
        arches = spec.get("archetypes") or []
        allowed = ("*" in arches) or (archetype in arches) or (
            EXTRA_ARCHETYPE_ALIASES.get(archetype) in arches) or (name in preferred)
        kw = spec.get("keywords") or {}
        kw_score = sum(kw.get(t, 0) for t in tokens)
        if not allowed and kw_score < 3:
            continue
        weight = 1.0 + kw_score
        if allowed:
            weight += 2.0
        if name in preferred:
            weight += 3.0
        try:
            import structure_forge
            family = structure_forge.resolve_family(name, spec.get("category", ""))
        except Exception:
            family = "hut"
        scored.append((weight, name, spec, family))
    scored.sort(key=lambda x: -x[0])
    picked = scored[:max_types]
    # Always include preferred tags that exist in catalog if room
    have = {n for _, n, _, _ in picked}
    for tag in preferred:
        if tag in STRUCTURE_CATALOG and tag not in have and len(picked) < max_types:
            spec = STRUCTURE_CATALOG[tag]
            try:
                import structure_forge
                family = structure_forge.resolve_family(tag, spec.get("category", ""))
            except Exception:
                family = "hut"
            picked.append((2.5, tag, spec, family))
            have.add(tag)
    return [{"name": n, "spec": s, "weight": w, "forge_family": f} for w, n, s, f in picked[:max_types]]


def _load_mesh(path: str):
    if not _HAS_UNREAL:
        return None
    try:
        asset = unreal.load_asset(path)
        if asset is not None:
            return asset
        # Soft object path style
        if "." not in path.split("/")[-1]:
            leaf = path.rstrip("/").split("/")[-1]
            asset = unreal.load_asset("{}.{}".format(path, leaf))
        return asset
    except Exception:
        return None


def _resolve_mesh_for_structure(spec: dict):
    """Prefer project mesh under content root; else None (use proxy)."""
    try:
        import content_library
        rel = spec.get("mesh") or ""
        if not rel:
            return None
        if rel.startswith("/Game") or rel.startswith("/Engine"):
            path = rel
        else:
            path = content_library.resolve_asset_path(rel)
        return _load_mesh(path)
    except Exception:
        return None


def _spawn_static_mesh(mesh, location, rotation, scale, label: str):
    if not _HAS_UNREAL:
        return None
    try:
        actor = None
        if hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actor = subsys.spawn_actor_from_class(
                unreal.StaticMeshActor, location, rotation)
        elif hasattr(unreal, "EditorLevelLibrary"):
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.StaticMeshActor, location, rotation)
        if actor is None:
            return None
        try:
            smc = actor.static_mesh_component
            smc.set_static_mesh(mesh)
            smc.set_world_scale3d(scale)
        except Exception:
            pass
        try:
            actor.set_actor_label(label)
        except Exception:
            pass
        return actor
    except Exception as e:
        unreal.log_warning("structure_library._spawn_static_mesh failed: {}".format(e))
        return None


def _spawn_proxy(recipe, base_loc, base_yaw, label_prefix: str):
    actors = []
    for i, part in enumerate(recipe or []):
        shape = part.get("shape", "cube")
        mesh_path = _PROXY.get(shape, _PROXY["cube"])
        mesh = _load_mesh(mesh_path)
        if mesh is None:
            continue
        ox, oy, oz = part.get("offset", (0, 0, 0))
        sx, sy, sz = part.get("scale", (1, 1, 1))
        yaw = base_yaw + float(part.get("yaw", 0))
        # rotate offset by base yaw
        rad = math.radians(base_yaw)
        rx = ox * math.cos(rad) - oy * math.sin(rad)
        ry = ox * math.sin(rad) + oy * math.cos(rad)
        loc = unreal.Vector(base_loc.x + rx, base_loc.y + ry, base_loc.z + oz)
        rot = unreal.Rotator(0.0, yaw, 0.0)
        scale = unreal.Vector(float(sx), float(sy), float(sz))
        actor = _spawn_static_mesh(mesh, loc, rot, scale, "{}_{}".format(label_prefix, i))
        if actor:
            actors.append(actor)
    return actors


def _height_at(pixels, width, height, x, y):
    x = max(0, min(width - 1, int(x)))
    y = max(0, min(height - 1, int(y)))
    return pixels[y * width + x] / 65535.0


def _slope_at(slope_map, width, height, x, y, layer_names):
    if not slope_map:
        return 0.0
    x = max(0, min(width - 1, int(x)))
    y = max(0, min(height - 1, int(y)))
    idx = slope_map[y * width + x]
    # approximate degrees from band midpoints
    bands = [6.0, 20.0, 38.0, 70.0]
    if isinstance(idx, int) and 0 <= idx < len(bands):
        return bands[idx]
    return 15.0


def clear_spawned_structures(state: dict):
    actors = state.get("structure_actors") or []
    if not actors:
        return
    try:
        if _HAS_UNREAL and hasattr(unreal, "EditorActorSubsystem"):
            subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for a in list(actors):
                try:
                    subsys.destroy_actor(a)
                except Exception:
                    try:
                        a.destroy_actor()
                    except Exception:
                        pass
        state["structure_actors"] = []
        unreal.log("WorldPromptEngine: cleared previous structures")
    except Exception as e:
        unreal.log_error("structure_library.clear_spawned_structures failed: {}".format(e))


def spawn_structures(state: dict, pixels, width: int, height: int, params: dict = None) -> dict:
    """
    Place resolved structures into the level using heightmap samples.
    Uses real meshes when available; otherwise BasicShapes proxies.
    """
    params = params or {}
    summary = {"ok": True, "placed": 0, "types": [], "proxies": 0, "meshes": 0}
    if not params.get("spawn_structures", True):
        summary["ok"] = True
        summary["skipped"] = True
        return summary

    try:
        parsed = state.get("last_parse") or {}
        archetype = parsed.get("archetype", "rolling_hills")
        prompt = params.get("prompt") or ""
        picks = state.get("structure_plan") or resolve_structures(archetype, prompt)
        if not picks:
            unreal.log_warning("WorldPromptEngine: no structures resolved for '{}'".format(archetype))
            return summary

        clear_spawned_structures(state)
        state.setdefault("structure_actors", [])

        seed = int(params.get("seed", 1337)) ^ 0xA5A5
        rng = random.Random(seed)
        xy_scale = float(params.get("xy_scale", 100.0))
        z_scale = float(params.get("z_scale", 51200.0))
        origin_x = float(params.get("origin_x", -width * xy_scale * 0.5))
        origin_y = float(params.get("origin_y", -height * xy_scale * 0.5))
        slope_map = state.get("last_slope_map")
        layer_names = state.get("slope_layer_names") or []

        density_scale = float(params.get("structure_density", 1.0))
        max_total = int(params.get("max_structures", 48))
        placed_total = 0
        forged = 0
        try:
            import structure_forge
        except Exception:
            structure_forge = None

        preferred = parsed.get("structure_tags") or []
        if not state.get("structure_plan"):
            picks = resolve_structures(archetype, prompt, preferred_tags=preferred)

        for entry in picks:
            if placed_total >= max_total:
                break
            name = entry["name"]
            spec = entry["spec"]
            family = entry.get("forge_family")
            if not family and structure_forge is not None:
                family = structure_forge.resolve_family(name, spec.get("category", ""))
            family = family or "hut"

            cmin, cmax = spec.get("count", (1, 2))
            target = int(round(rng.randint(cmin, cmax) * density_scale))
            target = max(0, min(target, max_total - placed_total))
            mesh = _resolve_mesh_for_structure(spec)
            placed_this = 0
            attempts = 0
            while placed_this < target and attempts < target * 40:
                attempts += 1
                px = rng.uniform(2, width - 3)
                py = rng.uniform(2, height - 3)
                h01 = _height_at(pixels, width, height, px, py)
                if h01 < spec.get("h_min", 0.0) or h01 > spec.get("h_max", 1.0):
                    continue
                slope = _slope_at(slope_map, width, height, px, py, layer_names)
                if slope > float(spec.get("max_slope", 45)):
                    continue

                wx = origin_x + px * xy_scale
                wy = origin_y + py * xy_scale
                wz = h01 * 1000.0
                loc = unreal.Vector(float(wx), float(wy), float(wz)) if _HAS_UNREAL else None
                yaw = rng.uniform(0, 360)
                label = "WPE_{}_{}".format(name, placed_this)

                if mesh is not None and _HAS_UNREAL:
                    scale = unreal.Vector(1, 1, 1)
                    actor = _spawn_static_mesh(
                        mesh, loc, unreal.Rotator(0, yaw, 0), scale, label)
                    if actor:
                        state["structure_actors"].append(actor)
                        summary["meshes"] += 1
                        placed_this += 1
                        placed_total += 1
                elif structure_forge is not None and _HAS_UNREAL:
                    actors = structure_forge.spawn_family(
                        family, loc, yaw, label, state=state)
                    if actors:
                        forged += 1
                        summary["proxies"] += len(actors)
                        placed_this += 1
                        placed_total += 1
                else:
                    actors = _spawn_proxy(spec.get("proxy"), loc, yaw, label) if _HAS_UNREAL else []
                    if actors:
                        state["structure_actors"].extend(actors)
                        summary["proxies"] += len(actors)
                        placed_this += 1
                        placed_total += 1

            if placed_this:
                summary["types"].append({
                    "name": name,
                    "count": placed_this,
                    "forge_family": family,
                    "proxy": mesh is None,
                })

        summary["placed"] = placed_total
        summary["forged_instances"] = forged
        state["last_structure_summary"] = summary
        unreal.log(
            "WorldPromptEngine: structures placed={} types={} (meshes={}, forge/proxy_parts={})".format(
                placed_total, len(summary["types"]), summary["meshes"], summary["proxies"]))
        return summary
    except Exception as e:
        unreal.log_error("structure_library.spawn_structures failed: {}".format(e))
        return {"ok": False, "error": str(e), "placed": summary.get("placed", 0)}
