#include "WPEMaterialBridge.h"
#include "Materials/MaterialParameterCollection.h"
#include "Materials/MaterialParameterCollectionInstance.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "Misc/Paths.h"

bool UWPEMaterialBridge::ApplyWorldMPCParams(
	UMaterialParameterCollection* Collection,
	float Snowline,
	float RockSlope,
	float Wetness,
	float MacroScale,
	FLinearColor Tint)
{
	if (!Collection)
	{
		UE_LOG(LogTemp, Warning, TEXT("WPE MaterialBridge: MPC is null"));
		return false;
	}

	UWorld* World = nullptr;
	if (GEngine)
	{
		World = GEngine->GetCurrentPlayWorld();
		if (!World)
		{
			for (const FWorldContext& Ctx : GEngine->GetWorldContexts())
			{
				if (Ctx.World() && (Ctx.WorldType == EWorldType::Editor || Ctx.WorldType == EWorldType::PIE))
				{
					World = Ctx.World();
					break;
				}
			}
		}
	}
	if (!World)
	{
		UE_LOG(LogTemp, Warning, TEXT("WPE MaterialBridge: no world for MPC instance"));
		return false;
	}

	UMaterialParameterCollectionInstance* Inst = World->GetParameterCollectionInstance(Collection);
	if (!Inst)
	{
		UE_LOG(LogTemp, Warning, TEXT("WPE MaterialBridge: failed to get MPC instance"));
		return false;
	}

	auto SetScalar = [Inst](FName Name, float Value)
	{
		Inst->SetScalarParameterValue(Name, Value);
	};
	auto SetVector = [Inst](FName Name, const FLinearColor& Value)
	{
		Inst->SetVectorParameterValue(Name, Value);
	};

	// Canonical names — authored materials should reference these MPC params.
	SetScalar(TEXT("Snowline"), FMath::Clamp(Snowline, 0.0f, 1.0f));
	SetScalar(TEXT("RockSlope"), FMath::Clamp(RockSlope, 0.0f, 1.0f));
	SetScalar(TEXT("Wetness"), FMath::Clamp(Wetness, 0.0f, 1.0f));
	SetScalar(TEXT("MacroScale"), FMath::Max(0.01f, MacroScale));
	SetVector(TEXT("WorldTint"), Tint);

	UE_LOG(LogTemp, Log, TEXT("WPE MaterialBridge: MPC params applied (snow=%.2f rock=%.2f wet=%.2f macro=%.2f)"),
		Snowline, RockSlope, Wetness, MacroScale);
	return true;
}

bool UWPEMaterialBridge::ApplyWorldMPCParamsByPath(
	UObject* WorldContextObject,
	const FString& MPCPath,
	float Snowline,
	float RockSlope,
	float Wetness,
	float MacroScale,
	FLinearColor Tint)
{
	UMaterialParameterCollection* Collection = LoadObject<UMaterialParameterCollection>(nullptr, *MPCPath);
	if (!Collection)
	{
		// Soft path variants
		const FString DotPath = MPCPath.Contains(TEXT(".")) ? MPCPath : (MPCPath + TEXT(".") + FPaths::GetBaseFilename(MPCPath));
		Collection = LoadObject<UMaterialParameterCollection>(nullptr, *DotPath);
	}
	if (!Collection)
	{
		UE_LOG(LogTemp, Warning, TEXT("WPE MaterialBridge: could not load MPC at %s"), *MPCPath);
		return false;
	}
	return ApplyWorldMPCParams(Collection, Snowline, RockSlope, Wetness, MacroScale, Tint);
}
