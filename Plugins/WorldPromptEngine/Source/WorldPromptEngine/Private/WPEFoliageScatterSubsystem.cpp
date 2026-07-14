#include "WPEFoliageScatterSubsystem.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/SceneComponent.h"

void UWPEFoliageScatterSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	ScatteredCount = 0;
}

void UWPEFoliageScatterSubsystem::Deinitialize()
{
	ClearScatteredFoliage();
	Super::Deinitialize();
}

void UWPEFoliageScatterSubsystem::ClearScatteredFoliage()
{
	if (FoliageHolder)
	{
		FoliageHolder->Destroy();
		FoliageHolder = nullptr;
	}
	ActiveHISM = nullptr;
	ScatteredCount = 0;
}

static UWorld* WPE_FindEditorOrPlayWorld()
{
	if (!GEngine)
	{
		return nullptr;
	}
	if (UWorld* Play = GEngine->GetCurrentPlayWorld())
	{
		return Play;
	}
	for (const FWorldContext& Ctx : GEngine->GetWorldContexts())
	{
		if (Ctx.World() &&
			(Ctx.WorldType == EWorldType::Editor || Ctx.WorldType == EWorldType::PIE || Ctx.WorldType == EWorldType::Game))
		{
			return Ctx.World();
		}
	}
	return nullptr;
}

UHierarchicalInstancedStaticMeshComponent* UWPEFoliageScatterSubsystem::EnsureHISM(UStaticMesh* Mesh)
{
	UWorld* World = WPE_FindEditorOrPlayWorld();
	if (!World || !Mesh)
	{
		return nullptr;
	}

	if (!FoliageHolder)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		FoliageHolder = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
		if (!FoliageHolder)
		{
			return nullptr;
		}
#if WITH_EDITOR
		FoliageHolder->SetActorLabel(TEXT("WPE_NativeFoliage"));
#endif
		USceneComponent* Root = NewObject<USceneComponent>(FoliageHolder, TEXT("Root"));
		Root->RegisterComponent();
		FoliageHolder->SetRootComponent(Root);
	}

	ActiveHISM = NewObject<UHierarchicalInstancedStaticMeshComponent>(FoliageHolder);
	ActiveHISM->SetupAttachment(FoliageHolder->GetRootComponent());
	ActiveHISM->SetStaticMesh(Mesh);
	ActiveHISM->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	ActiveHISM->SetMobility(EComponentMobility::Static);
	ActiveHISM->SetCastShadow(true);
	ActiveHISM->RegisterComponent();
	FoliageHolder->AddInstanceComponent(ActiveHISM);
	return ActiveHISM;
}

float UWPEFoliageScatterSubsystem::SampleHeight(const TArray<float>& Heights01, int32 ResX, int32 ResY, int32 X, int32 Y)
{
	X = FMath::Clamp(X, 0, ResX - 1);
	Y = FMath::Clamp(Y, 0, ResY - 1);
	return Heights01[Y * ResX + X];
}

float UWPEFoliageScatterSubsystem::SampleSlopeDegrees(
	const TArray<float>& Heights01, int32 ResX, int32 ResY, int32 X, int32 Y, float WorldSizeXY, float HeightAmp)
{
	const float Step = WorldSizeXY / float(FMath::Max(1, ResX - 1));
	const float Hl = SampleHeight(Heights01, ResX, ResY, X - 1, Y) * HeightAmp;
	const float Hr = SampleHeight(Heights01, ResX, ResY, X + 1, Y) * HeightAmp;
	const float Hd = SampleHeight(Heights01, ResX, ResY, X, Y - 1) * HeightAmp;
	const float Hu = SampleHeight(Heights01, ResX, ResY, X, Y + 1) * HeightAmp;
	const float Dx = (Hr - Hl) / (2.0f * FMath::Max(1.0f, Step));
	const float Dy = (Hu - Hd) / (2.0f * FMath::Max(1.0f, Step));
	const FVector Normal = FVector(-Dx, -Dy, 1.0f).GetSafeNormal();
	const float CosTheta = FMath::Clamp(FVector::DotProduct(Normal, FVector::UpVector), -1.0f, 1.0f);
	return FMath::RadiansToDegrees(FMath::Acos(CosTheta));
}

int32 UWPEFoliageScatterSubsystem::ScatterForest(
	UStaticMesh* Mesh,
	FVector Origin,
	float Radius,
	int32 Count,
	int32 Seed,
	float MaxSlopeDegrees,
	bool bTraceGround,
	float ScaleMin,
	float ScaleMax)
{
	if (!Mesh || Count <= 0 || Radius <= 0.f)
	{
		return 0;
	}

	UWorld* World = WPE_FindEditorOrPlayWorld();
	if (!World)
	{
		return 0;
	}

	ClearScatteredFoliage();
	UHierarchicalInstancedStaticMeshComponent* HISM = EnsureHISM(Mesh);
	if (!HISM)
	{
		return 0;
	}

	FRandomStream Rng(Seed);
	const float MaxSlopeRad = FMath::DegreesToRadians(MaxSlopeDegrees);
	int32 Added = 0;

	for (int32 i = 0; i < Count; ++i)
	{
		const float Ang = Rng.FRandRange(0.f, 2.f * PI);
		const float Rad = Rng.FRandRange(0.f, Radius);
		FVector Pos = Origin + FVector(FMath::Cos(Ang) * Rad, FMath::Sin(Ang) * Rad, 5000.f);

		if (bTraceGround)
		{
			FHitResult Hit;
			const FVector Start = Pos;
			const FVector End = Pos - FVector(0, 0, 20000.f);
			FCollisionQueryParams Q;
			Q.bTraceComplex = false;
			if (!World->LineTraceSingleByChannel(Hit, Start, End, ECC_WorldStatic, Q))
			{
				continue;
			}
			Pos = Hit.ImpactPoint;
			const float Slope = FMath::Acos(FVector::DotProduct(Hit.ImpactNormal.GetSafeNormal(), FVector::UpVector));
			if (Slope > MaxSlopeRad)
			{
				continue;
			}
		}
		else
		{
			Pos.Z = Origin.Z;
		}

		const float S = Rng.FRandRange(ScaleMin, ScaleMax);
		const FRotator Rot(0.f, Rng.FRandRange(0.f, 360.f), 0.f);
		HISM->AddInstance(FTransform(Rot, Pos, FVector(S)), true);
		++Added;
	}

	ScatteredCount = Added;
	UE_LOG(LogTemp, Log, TEXT("WPE Foliage: ScatterForest added %d HISM instances"), Added);
	return Added;
}

int32 UWPEFoliageScatterSubsystem::ScatterTerrainAware(
	UStaticMesh* Mesh,
	const TArray<float>& Heights01,
	int32 ResX,
	int32 ResY,
	FVector Origin,
	float WorldSizeXY,
	float HeightAmp,
	int32 Count,
	int32 Seed,
	float MaxSlopeDegrees,
	float MinAltitude01,
	float MaxAltitude01,
	float ClusterStrength,
	float ScaleMin,
	float ScaleMax,
	bool bClearPrevious)
{
	if (!Mesh || Count <= 0 || ResX < 3 || ResY < 3 || Heights01.Num() != ResX * ResY || WorldSizeXY <= 0.f)
	{
		UE_LOG(LogTemp, Warning, TEXT("WPE Foliage: ScatterTerrainAware invalid args"));
		return 0;
	}

	if (bClearPrevious)
	{
		ClearScatteredFoliage();
	}

	UHierarchicalInstancedStaticMeshComponent* HISM = EnsureHISM(Mesh);
	if (!HISM)
	{
		return 0;
	}

	// Build candidate list from height/slope gates (plain data — no traces required)
	TArray<FIntPoint> Candidates;
	Candidates.Reserve(ResX * ResY / 8);
	for (int32 Y = 1; Y < ResY - 1; ++Y)
	{
		for (int32 X = 1; X < ResX - 1; ++X)
		{
			const float H = SampleHeight(Heights01, ResX, ResY, X, Y);
			if (H < MinAltitude01 || H > MaxAltitude01)
			{
				continue;
			}
			const float SlopeDeg = SampleSlopeDegrees(Heights01, ResX, ResY, X, Y, WorldSizeXY, HeightAmp);
			if (SlopeDeg > MaxSlopeDegrees)
			{
				continue;
			}
			Candidates.Add(FIntPoint(X, Y));
		}
	}

	if (Candidates.Num() == 0)
	{
		UE_LOG(LogTemp, Warning, TEXT("WPE Foliage: no candidates after slope/altitude filters"));
		return 0;
	}

	FRandomStream Rng(Seed);
	// Shuffle
	for (int32 I = Candidates.Num() - 1; I > 0; --I)
	{
		const int32 J = Rng.RandRange(0, I);
		Candidates.Swap(I, J);
	}

	const int32 ClusterSeeds = FMath::Clamp(Count / 10, 8, 64);
	TArray<FIntPoint> Seeds;
	Seeds.Reserve(ClusterSeeds);
	for (int32 I = 0; I < Candidates.Num() && Seeds.Num() < ClusterSeeds; ++I)
	{
		Seeds.Add(Candidates[I]);
	}

	int32 Added = 0;
	const float ClusterRadiusPx = FMath::Lerp(2.0f, 18.0f, FMath::Clamp(ClusterStrength, 0.0f, 1.0f));

	auto PlaceAt = [&](int32 X, int32 Y)
	{
		if (Added >= Count)
		{
			return;
		}
		const float H = SampleHeight(Heights01, ResX, ResY, X, Y);
		if (H < MinAltitude01 || H > MaxAltitude01)
		{
			return;
		}
		if (SampleSlopeDegrees(Heights01, ResX, ResY, X, Y, WorldSizeXY, HeightAmp) > MaxSlopeDegrees)
		{
			return;
		}
		const float U = float(X) / float(ResX - 1);
		const float V = float(Y) / float(ResY - 1);
		const FVector Pos(
			Origin.X + U * WorldSizeXY,
			Origin.Y + V * WorldSizeXY,
			Origin.Z + H * HeightAmp);
		const float S = Rng.FRandRange(ScaleMin, ScaleMax);
		const FRotator Rot(0.f, Rng.FRandRange(0.f, 360.f), 0.f);
		HISM->AddInstance(FTransform(Rot, Pos, FVector(S)), true);
		++Added;
	};

	for (const FIntPoint& SeedPt : Seeds)
	{
		if (Added >= Count)
		{
			break;
		}
		PlaceAt(SeedPt.X, SeedPt.Y);
		const int32 LocalN = FMath::Max(2, Count / FMath::Max(1, Seeds.Num()));
		for (int32 K = 0; K < LocalN && Added < Count; ++K)
		{
			const float Ang = Rng.FRandRange(0.f, 2.f * PI);
			const float Rad = Rng.FRandRange(1.0f, ClusterRadiusPx);
			const int32 X = FMath::Clamp(SeedPt.X + FMath::RoundToInt(FMath::Cos(Ang) * Rad), 1, ResX - 2);
			const int32 Y = FMath::Clamp(SeedPt.Y + FMath::RoundToInt(FMath::Sin(Ang) * Rad), 1, ResY - 2);
			PlaceAt(X, Y);
		}
	}

	// Fill remainder from shuffled candidates if clusters under-filled
	for (int32 I = 0; I < Candidates.Num() && Added < Count; ++I)
	{
		PlaceAt(Candidates[I].X, Candidates[I].Y);
	}

	ScatteredCount += Added;
	UE_LOG(LogTemp, Log, TEXT("WPE Foliage: ScatterTerrainAware added %d / requested %d (candidates=%d)"),
		Added, Count, Candidates.Num());
	return Added;
}
