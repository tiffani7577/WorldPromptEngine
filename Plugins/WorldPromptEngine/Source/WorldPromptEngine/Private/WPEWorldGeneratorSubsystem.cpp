#include "WPEWorldGeneratorSubsystem.h"
#include "WPEWorldScaleSettings.h"
#include "Async/Async.h"

namespace WPENoise
{
	static FORCEINLINE float Fade(float T)
	{
		return T * T * T * (T * (T * 6.0f - 15.0f) + 10.0f);
	}

	static FORCEINLINE float Lerp(float A, float B, float T)
	{
		return A + T * (B - A);
	}

	static FORCEINLINE float Grad(int32 Hash, float X, float Y)
	{
		const int32 H = Hash & 7;
		const float U = H < 4 ? X : Y;
		const float V = H < 4 ? Y : X;
		return ((H & 1) ? -U : U) + (((H & 2) ? -V : V) * 0.5f);
	}

	struct FPerlin2D
	{
		int32 Perm[512];

		explicit FPerlin2D(int32 Seed)
		{
			TArray<int32> P;
			P.Reserve(256);
			for (int32 I = 0; I < 256; ++I)
			{
				P.Add(I);
			}
			FRandomStream Rng(Seed);
			for (int32 I = 255; I > 0; --I)
			{
				const int32 J = Rng.RandRange(0, I);
				Swap(P[I], P[J]);
			}
			for (int32 I = 0; I < 256; ++I)
			{
				Perm[I] = P[I];
				Perm[I + 256] = P[I];
			}
		}

		float Noise(float X, float Y) const
		{
			const int32 Xi = FMath::FloorToInt(X) & 255;
			const int32 Yi = FMath::FloorToInt(Y) & 255;
			const float Xf = X - FMath::FloorToFloat(X);
			const float Yf = Y - FMath::FloorToFloat(Y);
			const float U = Fade(Xf);
			const float V = Fade(Yf);
			const int32 AA = Perm[Perm[Xi] + Yi];
			const int32 AB = Perm[Perm[Xi] + Yi + 1];
			const int32 BA = Perm[Perm[Xi + 1] + Yi];
			const int32 BB = Perm[Perm[Xi + 1] + Yi + 1];
			const float X1 = Lerp(Grad(AA, Xf, Yf), Grad(BA, Xf - 1.0f, Yf), U);
			const float X2 = Lerp(Grad(AB, Xf, Yf - 1.0f), Grad(BB, Xf - 1.0f, Yf - 1.0f), U);
			return Lerp(X1, X2, V);
		}

		float FBM(float X, float Y, int32 Octaves, float Frequency, float Persistence, float Lacunarity) const
		{
			float Total = 0.0f;
			float Amplitude = 1.0f;
			float MaxAmp = 0.0f;
			float Freq = Frequency;
			const int32 SafeOctaves = FMath::Max(1, Octaves);
			for (int32 O = 0; O < SafeOctaves; ++O)
			{
				Total += Noise(X * Freq, Y * Freq) * Amplitude;
				MaxAmp += Amplitude;
				Amplitude *= Persistence;
				Freq *= Lacunarity;
			}
			return MaxAmp > 0.0f ? Total / MaxAmp : 0.0f;
		}
	};
}

void UWPEWorldGeneratorSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	UE_LOG(LogTemp, Log, TEXT("WPEWorldGeneratorSubsystem online — %s"), *GetScaleSummary());
}

void UWPEWorldGeneratorSubsystem::Deinitialize()
{
	Super::Deinitialize();
}

FString UWPEWorldGeneratorSubsystem::GetScaleSummary() const
{
	const UWPEWorldScaleSettings* Settings = GetDefault<UWPEWorldScaleSettings>();
	const float ExtentM = Settings->WorldExtentKilometers * 1000.0f;
	const int32 Tiles = FMath::Max(1, FMath::CeilToInt(ExtentM / Settings->TileSizeMeters));
	return FString::Printf(
		TEXT("extent=%.1fkm tile=%.0fm res=%d grid~%dx%d (%d tiles) WP=%s"),
		Settings->WorldExtentKilometers,
		Settings->TileSizeMeters,
		Settings->TileResolution,
		Tiles, Tiles, Tiles * Tiles,
		Settings->bPlanForWorldPartition ? TEXT("yes") : TEXT("no"));
}

FWPEWorldPlan UWPEWorldGeneratorSubsystem::BuildWorldPlan(float ExtentKilometers, float TileSizeMeters, int32 TileResolution)
{
	const UWPEWorldScaleSettings* Settings = GetDefault<UWPEWorldScaleSettings>();
	const float ExtentKm = ExtentKilometers > 0.0f ? ExtentKilometers : Settings->WorldExtentKilometers;
	const float TileM = TileSizeMeters > 0.0f ? TileSizeMeters : Settings->TileSizeMeters;
	const int32 Res = TileResolution > 0 ? TileResolution : Settings->TileResolution;

	FWPEWorldPlan Plan;
	Plan.WorldExtentKilometers = ExtentKm;
	Plan.TileResolution = Res;

	const float ExtentMeters = ExtentKm * 1000.0f;
	Plan.TilesX = FMath::Max(1, FMath::CeilToInt(ExtentMeters / TileM));
	Plan.TilesY = Plan.TilesX;
	Plan.TotalTiles = Plan.TilesX * Plan.TilesY;

	const float OriginShift = -0.5f * Plan.TilesX * TileM;
	Plan.Tiles.Reserve(Plan.TotalTiles);
	for (int32 TY = 0; TY < Plan.TilesY; ++TY)
	{
		for (int32 TX = 0; TX < Plan.TilesX; ++TX)
		{
			FWPEWorldTileCoord Tile;
			Tile.TileX = TX;
			Tile.TileY = TY;
			Tile.TileSizeMeters = TileM;
			Tile.WorldOrigin = FVector(OriginShift + TX * TileM, OriginShift + TY * TileM, 0.0f);
			Plan.Tiles.Add(Tile);
		}
	}

	LastPlan = Plan;
	OnPlanReady.Broadcast(Plan);
	UE_LOG(LogTemp, Log, TEXT("WPE plan ready: %d tiles (%.1f km, tile %.0f m)"), Plan.TotalTiles, ExtentKm, TileM);
	return Plan;
}

bool UWPEWorldGeneratorSubsystem::GenerateHeightTile(
	int32 TileX, int32 TileY, int32 Resolution, int32 Seed, TArray<uint16>& OutHeights,
	float Frequency, int32 Octaves, float Persistence, float Lacunarity)
{
	const int32 Res = FMath::Clamp(Resolution, 63, 1009);
	OutHeights.SetNumUninitialized(Res * Res);

	const WPENoise::FPerlin2D Noise(Seed);
	const float WorldFreqScale = 1.0f;
	for (int32 Y = 0; Y < Res; ++Y)
	{
		for (int32 X = 0; X < Res; ++X)
		{
			const float NX = static_cast<float>(TileX * (Res - 1) + X);
			const float NY = static_cast<float>(TileY * (Res - 1) + Y);
			const float N = Noise.FBM(NX, NY, Octaves, Frequency * WorldFreqScale, Persistence, Lacunarity);
			const float Remapped = FMath::Clamp(N * 0.5f + 0.5f, 0.0f, 1.0f);
			OutHeights[Y * Res + X] = static_cast<uint16>(Remapped * 65535.0f);
		}
	}
	return true;
}

int32 UWPEWorldGeneratorSubsystem::GetPendingTileCount() const
{
	FScopeLock Lock(const_cast<FCriticalSection*>(&QueueLock));
	return PendingTiles.Num() + OutstandingTasks.Load();
}

int32 UWPEWorldGeneratorSubsystem::EnqueueTileBatch(const TArray<FWPEWorldTileCoord>& Tiles, int32 Seed, int32 Resolution)
{
	const UWPEWorldScaleSettings* Settings = GetDefault<UWPEWorldScaleSettings>();
	const int32 MaxBatch = Settings->MaxTilesPerBatch;
	const int32 Res = Resolution > 0 ? Resolution : Settings->TileResolution;

	int32 Accepted = 0;
	for (const FWPEWorldTileCoord& Tile : Tiles)
	{
		if (Accepted >= MaxBatch)
		{
			break;
		}

		OutstandingTasks.FetchAdd(1);
		++Accepted;

		const int32 TX = Tile.TileX;
		const int32 TY = Tile.TileY;
		TWeakObjectPtr<UWPEWorldGeneratorSubsystem> WeakThis(this);

		Async(EAsyncExecution::ThreadPool, [WeakThis, TX, TY, Res, Seed]()
		{
			TArray<uint16> Heights;
			if (UWPEWorldGeneratorSubsystem* Self = WeakThis.Get())
			{
				Self->GenerateHeightTile(TX, TY, Res, Seed, Heights);
				AsyncTask(ENamedThreads::GameThread, [WeakThis, TX, TY]()
				{
					if (UWPEWorldGeneratorSubsystem* SelfInner = WeakThis.Get())
					{
						SelfInner->OnTileGenerated.Broadcast(TX, TY);
						SelfInner->OutstandingTasks.FetchSub(1);
					}
				});
			}
		});
	}

	UE_LOG(LogTemp, Log, TEXT("WPE enqueued %d height tiles (seed=%d res=%d)"), Accepted, Seed, Res);
	return Accepted;
}
