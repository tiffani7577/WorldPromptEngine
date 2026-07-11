#include "WorldPromptEngineModule.h"

#define LOCTEXT_NAMESPACE "FWorldPromptEngineModule"

void FWorldPromptEngineModule::StartupModule()
{
	UE_LOG(LogTemp, Log, TEXT("WorldPromptEngine runtime module started (scale core ready)"));
}

void FWorldPromptEngineModule::ShutdownModule()
{
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FWorldPromptEngineModule, WorldPromptEngine)
