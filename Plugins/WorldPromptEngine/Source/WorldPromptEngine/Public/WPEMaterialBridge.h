#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "WPEMaterialBridge.generated.h"

class UMaterialParameterCollection;

/**
 * Drives authored MPC / material params — does not build material graphs in C++.
 * Snowline, rock slope, wetness, macro scale, tint.
 */
UCLASS()
class WORLDPROMPTENGINE_API UWPEMaterialBridge : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "WPE|Material")
	static bool ApplyWorldMPCParams(
		UMaterialParameterCollection* Collection,
		float Snowline = 0.72f,
		float RockSlope = 0.55f,
		float Wetness = 0.35f,
		float MacroScale = 1.0f,
		FLinearColor Tint = FLinearColor::White);

	UFUNCTION(BlueprintCallable, Category = "WPE|Material", meta = (WorldContext = "WorldContextObject"))
	static bool ApplyWorldMPCParamsByPath(
		UObject* WorldContextObject,
		const FString& MPCPath,
		float Snowline = 0.72f,
		float RockSlope = 0.55f,
		float Wetness = 0.35f,
		float MacroScale = 1.0f,
		FLinearColor Tint = FLinearColor::White);
};
