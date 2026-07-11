using UnrealBuildTool;

public class WorldPromptEngineEditor : ModuleRules
{
	public WorldPromptEngineEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		IWYUSupport = IWYUSupport.Full;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"WorldPromptEngine"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			"EditorSubsystem",
			"EditorScriptingUtilities",
			"Landscape",
			"Slate",
			"SlateCore",
			"ToolMenus",
			"Projects"
		});
	}
}
