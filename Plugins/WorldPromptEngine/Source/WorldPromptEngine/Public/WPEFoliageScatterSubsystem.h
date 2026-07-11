#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"
#include "WPEFoliageScatterSubsystem.generated.h"

class UHierarchicalInstancedStaticMeshComponent;
class UStaticMesh;

/**
 * Native HISM foliage scatterer.
 * Terrain-aware path uses plain height/slope buffers (no per-instance actors).
 * Python foliage_fast.py remains available as fallback.
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
	 * Filters by MaxSlopeDegrees using line traces when bTraceGround.
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

	/**
	 * High-speed terrain-aware scatter using a flat 0..1 heightfield (row-major).
	 * Slope from finite differences; altitude + slope gates; optional clustering.
	 * Places HISM only — no floating (Z from height*ZAmp) and rejects steep/buried candidates.
	 */
	UFUNCTION(BlueprintCallable, Category="World Prompt Engine|Foliage")
	int32 ScatterTerrainAware(
		UStaticMesh* Mesh,
		const TArray<float>& Heights01,
		int32 ResX,
		int32 ResY,
		FVector Origin,
		float WorldSizeXY,
		float HeightAmp,
		int32 Count,
		int32 Seed,
		float MaxSlopeDegrees = 28.0f,
		float MinAltitude01 = 0.08f,
		float MaxAltitude01 = 0.88f,
		float ClusterStrength = 0.45f,
		float ScaleMin = 0.75f,
		float ScaleMax = 1.6f,
		bool bClearPrevious = true);

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine|Foliage")
	void ClearScatteredFoliage();

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine|Foliage")
	int32 GetScatteredInstanceCount() const { return ScatteredCount; }

private:
	UHierarchicalInstancedStaticMeshComponent* EnsureHISM(UStaticMesh* Mesh);
	static float SampleHeight(const TArray<float>& Heights01, int32 ResX, int32 ResY, int32 X, int32 Y);
	static float SampleSlopeDegrees(const TArray<float>& Heights01, int32 ResX, int32 ResY, int32 X, int32 Y, float WorldSizeXY, float HeightAmp);

	UPROPERTY()
	TObjectPtr<AActor> FoliageHolder = nullptr;

	UHierarchicalInstancedStaticMeshComponent* ActiveHISM = nullptr;

	int32 ScatteredCount = 0;
};
