#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "WPENiagaraVfxLibrary.generated.h"

class UNiagaraSystem;

/**
 * Creates World Prompt Engine Niagara VFX systems with User.SpawnRateMultiplier
 * so performance_engine.py can drive spawn rate from the OSC highs channel.
 */
UCLASS()
class WORLDPROMPTENGINEEDITOR_API UWPENiagaraVfxLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Create / refresh all five NS_WPE_* systems under /Game/WorldPromptEngine/VFX/. */
	UFUNCTION(BlueprintCallable, Category = "WPE|Niagara")
	static bool CreateAllWpeVfxSystems(bool bForceRecreate = false);

	/** Ensure a single system exposes User.SpawnRateMultiplier and binds SpawnRate to it. */
	UFUNCTION(BlueprintCallable, Category = "WPE|Niagara")
	static bool EnsureSpawnRateMultiplier(UNiagaraSystem* System, float BaseSpawnRate = 20.0f, float DefaultMultiplier = 1.0f);

	/**
	 * Rebuild CrystalShimmer emitter stack from HangingParticulates (fixes soft-delete / bad template).
	 * Safe to call repeatedly; does not delete the asset package.
	 */
	UFUNCTION(BlueprintCallable, Category = "WPE|Niagara")
	static bool RebuildCrystalShimmer();
};
