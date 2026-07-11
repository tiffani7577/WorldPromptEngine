#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"
#include "WPEFoliageScatterSubsystem.generated.h"

/**
 * Optional native foliage scatterer — batched HISM transforms on worker threads.
 * Stage 2: call ScatterForest from Blueprint / Python via unreal.get_engine_subsystem.
 * Python foliage_fast.py remains the editor path until foliage C++ is validated.
 */
UCLASS()
class WORLDPROMPTENGINE_API UWPEFoliageScatterSubsystem : public UEngineSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/**
	 * Scatter Count instances of Mesh into World at random points in Radius around Origin.
	 * Intended for runtime; filters by MaxSlopeDegrees using line traces when bTraceGround.
	 * Returns number of instances added to an internal HISM actor (created if needed).
	 */
	UFUNCTION(BlueprintCallable, Category="World Prompt Engine|Foliage")
	int32 ScatterForest(
		UStaticMesh* Mesh,
		FVector Origin,
		float Radius,
		int32 Count,
		int32 Seed,
		float MaxSlopeDegrees = 28.0f,
		bool bTraceGround = true,
		float ScaleMin = 0.8f,
		float ScaleMax = 1.4f);

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine|Foliage")
	void ClearScatteredFoliage();

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine|Foliage")
	int32 GetScatteredInstanceCount() const { return ScatteredCount; }

private:
	UPROPERTY()
	TObjectPtr<AActor> FoliageHolder = nullptr;

	int32 ScatteredCount = 0;
};
