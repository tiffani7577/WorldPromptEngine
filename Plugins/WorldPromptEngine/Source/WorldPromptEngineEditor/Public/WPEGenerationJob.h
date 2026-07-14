#pragma once

#include "CoreMinimal.h"
#include "WPEGenerationJob.generated.h"

/**
 * Versioned Director job — plain data only.
 * Mirrors Plugins/WorldPromptEngine/Content/Python/schemas/wpe_director_job.schema.json
 * and accepts panel snake_case via UWPEGenerationEditorSubsystem parser.
 *
 * Does NOT own height application — that remains UWPEWorldGeneratorSubsystem::ApplyHeightmapToLandscape.
 */
USTRUCT(BlueprintType)
struct FWPETerrainJobParams
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	int32 ResolutionX = 253;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	int32 ResolutionY = 253;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	float Frequency = 0.004f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	int32 Octaves = 6;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	float Persistence = 0.5f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	float Lacunarity = 2.0f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	bool bApplyErosion = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	int32 ThermalIterations = 12;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Terrain")
	int32 HydraulicIterations = 28;
};

USTRUCT(BlueprintType)
struct FWPEBiomeJobParams
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Biome")
	int32 RegionCount = 4;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Biome")
	float Snowline = 0.72f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Biome")
	float RockSlopeThreshold = 0.55f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Biome")
	float Wetness = 0.35f;
};

USTRUCT(BlueprintType)
struct FWPEFoliageJobParams
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	bool bEnabled = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	bool bUseHISM = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	float Density = 1.0f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	float MaxSlopeDegrees = 28.0f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	float MinAltitude01 = 0.05f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	float MaxAltitude01 = 0.92f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Foliage")
	float ClusterStrength = 0.45f;
};

USTRUCT(BlueprintType)
struct FWPEMaterialJobParams
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Material")
	FString LandscapeMaterialPath = TEXT("/Game/WPE/Materials/ML_WPE_Landscape");

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Material")
	FString MPCPath = TEXT("/Game/WPE/Materials/MPC_WPE_World");

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Material")
	float MacroScale = 1.0f;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Material")
	FLinearColor Tint = FLinearColor(1.0f, 1.0f, 1.0f, 1.0f);
};

USTRUCT(BlueprintType)
struct FWPEAtmosphereJobParams
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Atmosphere")
	FString WeatherPreset;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Atmosphere")
	bool bEnsureLighting = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE|Atmosphere")
	bool bHideSkySpheres = true;
};

USTRUCT(BlueprintType)
struct FWPEGenerationJob
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	int32 SchemaVersion = 1;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FString Action = TEXT("generate_world");

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FString Prompt;

	/** Deterministic RNG seed for terrain / foliage / biomes. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	int32 Seed = 1337;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	bool bAllowProceduralFallback = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	bool bPreferLandscape = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FWPETerrainJobParams Terrain;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FWPEBiomeJobParams Biome;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FWPEFoliageJobParams Foliage;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FWPEMaterialJobParams Material;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "WPE")
	FWPEAtmosphereJobParams Atmosphere;
};

UENUM(BlueprintType)
enum class EWPEGenerationPhase : uint8
{
	Idle UMETA(DisplayName = "Idle"),
	Validated UMETA(DisplayName = "Validated"),
	GeneratingTerrain UMETA(DisplayName = "Generating Terrain"),
	ApplyingLandscape UMETA(DisplayName = "Applying Landscape"),
	PlacingFoliage UMETA(DisplayName = "Placing Foliage"),
	Completed UMETA(DisplayName = "Completed"),
	Failed UMETA(DisplayName = "Failed"),
	Cancelled UMETA(DisplayName = "Cancelled")
};

USTRUCT(BlueprintType)
struct FWPEGenerationJobStatus
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "WPE")
	EWPEGenerationPhase Phase = EWPEGenerationPhase::Idle;

	UPROPERTY(BlueprintReadOnly, Category = "WPE")
	bool bOk = true;

	UPROPERTY(BlueprintReadOnly, Category = "WPE")
	FString Message;

	UPROPERTY(BlueprintReadOnly, Category = "WPE")
	float Progress = 0.0f;
};
