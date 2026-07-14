#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"
#include "WPEWorldTile.h"
#include <atomic>
#include "WPEWorldGeneratorSubsystem.generated.h"

class ALandscape;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FWPETileGenerated, int32, TileX, int32, TileY);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FWPEPlanReady, const FWPEWorldPlan&, Plan);

/**
 * Native scale core — Landscape height apply + tile planning.
 * Python remains the control plane; this is the muscle for heightfields / huge worlds.
 */
UCLASS()
class WORLDPROMPTENGINE_API UWPEWorldGeneratorSubsystem : public UEngineSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/**
	 * Accepts a flat 32-bit integer array from Python (UE 5.8 marshalling),
	 * converts to uint16, and writes via FLandscapeEditDataInterface::SetHeightData.
	 * Enforces size match against the target landscape extent.
	 */
	UFUNCTION(BlueprintCallable, Category = "WPE|Core")
	bool ApplyHeightmapToLandscape(ALandscape* TargetLandscape, const TArray<int32>& RawHeights, int32 ResolutionX, int32 ResolutionY);

	/** Returns landscape height sample resolution (Width, Height), or (0,0) on failure. */
	UFUNCTION(BlueprintCallable, Category = "WPE|Core")
	FIntPoint GetLandscapeHeightResolution(ALandscape* TargetLandscape) const;

	/** Build a World Partition-friendly tile plan for the configured (or override) extent. */
	UFUNCTION(BlueprintCallable, Category="World Prompt Engine")
	FWPEWorldPlan BuildWorldPlan(float ExtentKilometers = -1.0f, float TileSizeMeters = -1.0f, int32 TileResolution = -1);

	/** Generate one tile's 16-bit height samples into OutHeights (row-major). Not Blueprint-exposed (uint16). */
	UFUNCTION(Category="World Prompt Engine")
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
