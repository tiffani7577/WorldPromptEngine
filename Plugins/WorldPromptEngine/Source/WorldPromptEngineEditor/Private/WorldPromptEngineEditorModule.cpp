#include "WorldPromptEngineEditorModule.h"
#include "WPEWorldGeneratorSubsystem.h"
#include "WPEWorldScaleSettings.h"
#include "WPENiagaraVfxLibrary.h"
#include "Editor.h"
#include "ToolMenus.h"

#define LOCTEXT_NAMESPACE "FWorldPromptEngineEditorModule"

static void WPE_LogScaleSummary()
{
	if (GEngine)
	{
		if (UWPEWorldGeneratorSubsystem* Sys = GEngine->GetEngineSubsystem<UWPEWorldGeneratorSubsystem>())
		{
			UE_LOG(LogTemp, Log, TEXT("WPE Scale: %s"), *Sys->GetScaleSummary());
			return;
		}
	}
	UE_LOG(LogTemp, Warning, TEXT("WPE Scale: subsystem not available yet"));
}

static void WPE_BuildDefaultPlan()
{
	if (!GEngine)
	{
		return;
	}
	if (UWPEWorldGeneratorSubsystem* Sys = GEngine->GetEngineSubsystem<UWPEWorldGeneratorSubsystem>())
	{
		const FWPEWorldPlan Plan = Sys->BuildWorldPlan();
		UE_LOG(LogTemp, Log, TEXT("WPE built plan with %d tiles. Adjust in Project Settings → Plugins → World Prompt Engine Scale"), Plan.TotalTiles);
	}
}

void FWorldPromptEngineEditorModule::StartupModule()
{
	UE_LOG(LogTemp, Log, TEXT("WorldPromptEngineEditor started"));

	UToolMenus::RegisterStartupCallback(FSimpleMulticastDelegate::FDelegate::CreateLambda([]()
	{
		UToolMenu* Menu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Tools");
		if (!Menu)
		{
			return;
		}
		FToolMenuSection& Section = Menu->FindOrAddSection("WorldPromptEngineNative");
		Section.Label = LOCTEXT("WPENativeSection", "World Prompt Engine (Native)");
		Section.AddMenuEntry(
			"WPE_LogScale",
			LOCTEXT("WPELogScale", "Log Native Scale Summary"),
			LOCTEXT("WPELogScaleTT", "Print C++ world-extent / tile grid settings"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateStatic(&WPE_LogScaleSummary))
		);
		Section.AddMenuEntry(
			"WPE_BuildPlan",
			LOCTEXT("WPEBuildPlan", "Build Native World Tile Plan"),
			LOCTEXT("WPEBuildPlanTT", "Create the C++ tile plan for huge World Partition worlds"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateStatic(&WPE_BuildDefaultPlan))
		);
		Section.AddMenuEntry(
			"WPE_CreateVfx",
			LOCTEXT("WPECreateVfx", "Create Performance Mode Niagara VFX"),
			LOCTEXT("WPECreateVfxTT", "Create NS_WPE_* systems under /Game/WorldPromptEngine/VFX with User.SpawnRateMultiplier"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateLambda([]()
			{
				UWPENiagaraVfxLibrary::CreateAllWpeVfxSystems(false);
			}))
		);
	}));
}

void FWorldPromptEngineEditorModule::ShutdownModule()
{
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(this);
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FWorldPromptEngineEditorModule, WorldPromptEngineEditor)
