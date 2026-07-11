#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "WPEWorldTile.generated.h"

USTRUCT(BlueprintType)
struct WORLDPROMPTENGINE_API FWPEWorldTileCoord
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	int32 TileX = 0;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	int32 TileY = 0;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	FVector WorldOrigin = FVector::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	float TileSizeMeters = 1009.0f;
};

USTRUCT(BlueprintType)
struct WORLDPROMPTENGINE_API FWPEWorldPlan
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	float WorldExtentKilometers = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	int32 TilesX = 0;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	int32 TilesY = 0;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	int32 TotalTiles = 0;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	int32 TileResolution = 505;

	UPROPERTY(BlueprintReadOnly, Category="WPE")
	TArray<FWPEWorldTileCoord> Tiles;
};
