# WorldPromptEngine

Hybrid **C++ + Python** natural-language world generation for **Unreal Engine 5.8**.

- **Python** = easy prompts, builder actor, folders, structures, WebSocket UI
- **C++** = tile planner + multithreaded height core for **huge** World Partition worlds

You are not limited to Python-sized maps.

## How to use (easiest — like Base-X)

1. Open `WorldPromptEngine.uproject` in **UE 5.8** (first open will **compile C++** — let it finish)
2. Wait for Output Log: `WorldPromptEngine: online`
3. **Tools → World Prompt Engine → Place Builder In Level**
4. Select **WorldPromptBuilder** → set **Prompt Text** → **Generate World**

### Huge worlds (native C++)

**Project Settings → Plugins → World Prompt Engine Scale** (extent in km, tile size, resolution).

```python
import init_unreal
init_unreal.build_huge_world(64)  # plan a 64km x 64km tiled world
```

Also: **Tools → World Prompt Engine (Native) → Build Native World Tile Plan**

### Architecture (no artificial ceiling)

| Layer | Job |
|--|--|
| Python prompt / Builder actor | Tell it what world you want |
| C++ `WPEWorldGeneratorSubsystem` | Tile plan + threaded heightfields |
| World Partition | Stream continents, not one giant mesh |
| PCG + your Content folder | Foliage / structures at scale |

**Power now:** 26 terrain archetypes · 38 weather presets · structure_forge (6 families: keep/ruin/crystal/megalith/hut/arch) · 35+ structure types wired through the manifest · native tile planner.

Optional bake (in editor Python):

```python
import init_unreal
init_unreal.preforge_structures()
```

### First launch
This is a **C++ project**. UE will compile on open. On Mac you need **Xcode**. After that, Python UI and native scale both work.
