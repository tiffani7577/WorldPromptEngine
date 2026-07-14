using UnrealBuildTool;
using System.Collections.Generic;

public class WorldPromptEngineTarget : TargetRules
{
	public WorldPromptEngineTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("WorldPromptEngineHost");
	}
}
