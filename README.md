# WorldPromptEngine

Natural-language procedural world generation plugin for **Unreal Engine 5.8**.

Prompt text → terrain archetype → frame-budgeted heightmap → landscape import → PCG scatter tags → optional weather preset. External tools talk to the editor over a local WebSocket bridge on port **3001**.

## Open the project

1. Double-click `WorldPromptEngine.uproject` (or open it from the Epic Launcher / Unreal Editor).
2. Confirm **UE 5.8** when prompted.
3. On first launch, allow missing content / rebuild if asked.
4. Watch the Output Log for:

```text
WorldPromptEngine v1.0.0 initializing (UE 5.8.0 target)...
WorldPromptEngine: online. WebSocket ws://127.0.0.1:3001
```

Required editor plugins (enabled by this project):

- Python Editor Script Plugin
- Procedural Content Generation Framework
- Editor Scripting Utilities
- WorldPromptEngine (this plugin)

## Generate from the Python console

In the editor: **Window → Developer Tools → Output Log**, then the Python console, or **Tools → Execute Python Script**.

```python
import init_unreal
init_unreal.prompt("misty alpine peaks at golden hour")
init_unreal.status()
```

Direct heightmap controls:

```python
init_unreal.generate(width=505, height=505, seed=42, noise="perlin")
```

## WebSocket API (`ws://127.0.0.1:3001`)

Send a JSON object; the bridge replies with an ack and queues work for the main thread.

| Action | Purpose |
|--------|---------|
| `generate_from_prompt` | Parse NL prompt → heightmap + PCG tags + weather |
| `generate_heightmap` | Raw noise heightmap generation |
| `apply_weather` | Apply a weather/lighting preset |
| `move_editor_camera` | Reposition the editor viewport camera |
| `spawn_temporary_actor` | Spawn a temporary debug actor |
| `clear_temporary_actors` | Remove temporary actors |
| `get_landscape_bounds` | Query last landscape bounds |

Example:

```json
{
  "action": "generate_from_prompt",
  "prompt": "volcanic badlands under ash-choked skies",
  "params": { "width": 505, "height": 505, "seed": 99 }
}
```

Helper client (from this repo):

```bash
python3 tools/wpe_client.py "misty alpine peaks at golden hour"
```

## Layout

```text
WorldPromptEngine/
├── WorldPromptEngine.uproject
├── Config/
├── Content/                      # project content (heightmaps land under /Game/...)
├── Plugins/WorldPromptEngine/
│   ├── WorldPromptEngine.uplugin
│   └── Content/Python/
│       ├── init_unreal.py        # editor boot + console API
│       ├── art_engine.py         # noise, PNG, frame-budget runner
│       ├── prompt_matrix.py      # archetypes, weather, slope maps
│       ├── utility_bridge.py     # stdlib WebSocket server (port 3001)
│       └── asset_manifest.json   # PCG spawn table (swap in your meshes)
└── tools/wpe_client.py
```

## Content folders (per build)

Just tell it the folder name (and where it lives if you want). It finds it and uses it.

```python
import init_unreal

# folder name only — searches Content Browser
init_unreal.use_folder("Forest_01")

# name + where
init_unreal.use_folder("Forest_01", where="/Game/Builds")
init_unreal.use_folder("Forest_01", where="Builds")

# full path also fine
init_unreal.use_folder("/Game/Builds/Forest_01")
```

If the folder doesn’t exist yet, it creates it, adds `Foliage` / `Rocks` / etc. inside, and remembers it in `Config/WPEContent.json` for this project.

```python
init_unreal.content_status()    # what’s still missing
init_unreal.prompt("misty alpine peaks at golden hour")
```

## Notes

- Generation is sliced to **~8 ms per editor frame** so the UI stays responsive.
- The WebSocket thread never calls `unreal.*` APIs; only the Slate post-tick pump does.
- Landscape import uses UE 5.8 asset tooling paths (not the removed 5.7-era `import_landscape_data` API).
