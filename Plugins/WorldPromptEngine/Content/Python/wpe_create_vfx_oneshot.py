# One-shot headless entry for UnrealEditor-Cmd -ExecutePythonScript
import unreal

ok = unreal.WPENiagaraVfxLibrary.create_all_wpe_vfx_systems(False)
unreal.log("WPE-VFX: CreateAllWpeVfxSystems -> {}".format(ok))
for name in (
    "NS_WPE_BioBioluminescent",
    "NS_WPE_Mist",
    "NS_WPE_Embers",
    "NS_WPE_OceanSpray",
    "NS_WPE_CrystalShimmer",
):
    path = "/Game/WorldPromptEngine/VFX/{}".format(name)
    exists = unreal.EditorAssetLibrary.does_asset_exist(path)
    unreal.log("WPE-VFX: {} exists={}".format(path, exists))
