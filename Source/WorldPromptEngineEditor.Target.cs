using UnrealBuildTool;
using System.Collections.Generic;

public class WorldPromptEngineEditorTarget : TargetRules
{
	public WorldPromptEngineEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("WorldPromptEngineHost");
	}
}
