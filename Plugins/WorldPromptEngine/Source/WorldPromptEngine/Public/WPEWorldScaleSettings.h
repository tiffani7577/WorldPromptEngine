#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "WPEWorldScaleSettings.generated.h"

/**
 * Project-wide scale targets for "biggest worlds" generation.
 * Tune these instead of hard-coding sizes in Python.
 */
UCLASS(Config=Game, DefaultConfig, meta=(DisplayName="World Prompt Engine Scale"))
class WORLDPROMPTENGINE_API UWPEWorldScaleSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	/** Target world extent on one axis, in kilometers (e.g. 64 = 64km x 64km). */
	UPROPERTY(EditAnywhere, Config, Category="Scale", meta=(ClampMin="1.0", ClampMax="1024.0"))
	float WorldExtentKilometers = 16.0f;

	/** Size of one generation / World Partition tile edge, in meters. */
	UPROPERTY(EditAnywhere, Config, Category="Scale", meta=(ClampMin="256.0", ClampMax="8192.0"))
	float TileSizeMeters = 1009.0f;

	/** Height samples per tile edge (landscape-friendly odd sizes: 63,127,253,505,1009). */
	UPROPERTY(EditAnywhere, Config, Category="Scale", meta=(ClampMin="63", ClampMax="1009"))
	int32 TileResolution = 505;

	/** Max tiles to generate in one editor batch (protects machine). */
	UPROPERTY(EditAnywhere, Config, Category="Scale", meta=(ClampMin="1", ClampMax="4096"))
	int32 MaxTilesPerBatch = 64;

	/** Worker threads for heightfield generation (0 = auto). */
	UPROPERTY(EditAnywhere, Config, Category="Performance", meta=(ClampMin="0", ClampMax="64"))
	int32 WorkerThreads = 0;

	/** When true, generator emits World Partition-oriented tile coords. */
	UPROPERTY(EditAnywhere, Config, Category="World Partition")
	bool bPlanForWorldPartition = true;

	virtual FName GetCategoryName() const override { return FName(TEXT("Plugins")); }
};
