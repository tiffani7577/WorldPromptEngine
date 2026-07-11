#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"
#include "WPEWorldTile.h"
#include <atomic>
#include "WPEWorldGeneratorSubsystem.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FWPETileGenerated, int32, TileX, int32, TileY);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FWPEPlanReady, const FWPEWorldPlan&, Plan);

/**
 * Native scale core — tile planning + multithreaded heightfield generation.
 * Python / Blueprint remain the control plane; this is the muscle for huge worlds.
 */
UCLASS()
class WORLDPROMPTENGINE_API UWPEWorldGeneratorSubsystem : public UEngineSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Build a World Partition-friendly tile plan for the configured (or override) extent. */
	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	FWPEWorldPlan BuildWorldPlan(float ExtentKilometers = -1.0f, float TileSizeMeters = -1.0f, int32 TileResolution = -1);

	/** Generate one tile's 16-bit height samples into OutHeights (row-major). */
	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	bool GenerateHeightTile(int32 TileX, int32 TileY, int32 Resolution, int32 Seed, TArray<uint16>& OutHeights,
		float Frequency = 0.004f, int32 Octaves = 6, float Persistence = 0.5f, float Lacunarity = 2.0f);

	/** Queue many tiles; processes on worker threads. Returns accepted tile count. */
	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	int32 EnqueueTileBatch(const TArray<FWPEWorldTileCoord>& Tiles, int32 Seed, int32 Resolution);

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	FWPEWorldPlan GetLastPlan() const { return LastPlan; }

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	int32 GetPendingTileCount() const;

	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	FString GetScaleSummary() const;

	UPROPERTY(BlueprintAssignable, Category="World Prompt Engine")
	FWPETileGenerated OnTileGenerated;

	UPROPERTY(BlueprintAssignable, Category="World Prompt Engine")
	FWPEPlanReady OnPlanReady;

private:
	FWPEWorldPlan LastPlan;
	mutable FCriticalSection QueueLock;
	TArray<FWPEWorldTileCoord> PendingTiles;
	std::atomic<int32> OutstandingTasks{0};
};
