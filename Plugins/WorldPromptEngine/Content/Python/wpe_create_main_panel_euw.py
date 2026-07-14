# Recreate EUW with WPEMainPanelWidget parent (deletes wrong parent if needed).
import unreal

EUW_PATH = "/Game/WorldPromptEngine/UI/EUW_WPE_Main"
EUW_DIR = "/Game/WorldPromptEngine/UI"


def _log(msg):
    unreal.log("[WorldPromptEngine][CreateEUW] {}".format(msg))


def main():
    host = unreal.load_class(None, "/Script/WorldPromptEngineEditor.WPEMainPanelWidget")
    if host is None:
        _log("ERROR: WPEMainPanelWidget class not loaded — restart editor after compiling")
        return

    if unreal.EditorAssetLibrary.does_asset_exist(EUW_PATH):
        unreal.EditorAssetLibrary.delete_asset(EUW_PATH)
        _log("deleted old EUW")

    if not unreal.EditorAssetLibrary.does_directory_exist(EUW_DIR):
        unreal.EditorAssetLibrary.make_directory(EUW_DIR)

    factory = unreal.EditorUtilityWidgetBlueprintFactory()
    try:
        factory.set_editor_property("edit_after_new", False)
    except Exception:
        pass
    try:
        factory.set_editor_property("parent_class", host)
    except Exception:
        factory.set_editor_property("ParentClass", host)

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset = tools.create_asset("EUW_WPE_Main", EUW_DIR, unreal.EditorUtilityWidgetBlueprint, factory)
    if asset is None:
        _log("create_asset returned None")
        return
    unreal.EditorAssetLibrary.save_asset(EUW_PATH)
    _log("created {} with parent WPEMainPanelWidget".format(EUW_PATH))

    # Also open the panel so the artist sees it immediately after recreate.
    try:
        import wpe_main_panel
        wpe_main_panel.open_panel()
    except Exception as e:
        _log("open_panel: {}".format(e))


if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
