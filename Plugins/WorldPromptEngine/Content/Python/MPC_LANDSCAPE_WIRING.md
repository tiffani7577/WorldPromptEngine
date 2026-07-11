# WPE MPC → ML_WPE_Landscape visual integration

## What the automation does
`landscape_auto_setup.wire_mpc_into_existing_landscape_material()` upgrades the **existing**
`/Game/WPE/Materials/ML_WPE_Landscape` asset in place (same path — not a new material) and binds:

| MPC param (`/Game/WPE/Materials/MPC_WPE_World`) | Material effect |
|---|---|
| **Snowline** | Elevation snow blend threshold (`SmoothStep(Snowline → 1, height01)`) |
| **RockSlope** | Power exponent on flatness → more rock on cliffs when raised |
| **Wetness** | Darkens base color + lowers roughness |
| **MacroScale** | Scales LandscapeLayerCoords into albedo UVs |
| **WorldTint** | Multiplies final base color |

Textures found under `/Game` (`*grass*`, `*rock*`, `*snow*`) are still preferred over solid colors.

## Run in editor (Python console — not Cmd)
```python
import wpe_wire_mpc_material
wpe_wire_mpc_material.run()
```

Visual sweep (watch the Landscape after each log line):
```python
import wpe_wire_mpc_material
wpe_wire_mpc_material.verify_sweep()
```

## Manual check if auto-wire reports mpc_wired=False
1. Open `ML_WPE_Landscape`.
2. Confirm five **Collection Parameter** nodes exist, Collection = `MPC_WPE_World`.
3. Confirm Base Color chain ends with `… → Wetness lerp → WorldTint multiply → Base Color`.
4. Confirm Roughness is `Lerp(0.82, 0.45, Wetness)`.
5. Apply / Save, then run `wpe_material_bridge.apply_world_params(snowline=0.2)` and confirm snow expands.

## Assign Landscape
Generate / demo already assigns `/Game/WPE/Materials/ML_WPE_Landscape`. To force:
```python
import landscape_materials, landscape_auto_setup as las
landscape_materials.try_assign_landscape_material(las.MAT_PATH)
```
