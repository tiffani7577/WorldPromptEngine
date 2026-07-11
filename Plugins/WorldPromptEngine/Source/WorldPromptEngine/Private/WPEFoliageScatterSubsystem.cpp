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

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	FoliageHolder = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	if (!FoliageHolder)
	{
		return 0;
	}

	USceneComponent* Root = NewObject<USceneComponent>(FoliageHolder, TEXT("Root"));
	Root->RegisterComponent();
	FoliageHolder->SetRootComponent(Root);

	UHierarchicalInstancedStaticMeshComponent* HISM = NewObject<UHierarchicalInstancedStaticMeshComponent>(FoliageHolder);
	HISM->SetupAttachment(Root);
	HISM->SetStaticMesh(Mesh);
	HISM->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	HISM->SetMobility(EComponentMobility::Static);
	HISM->RegisterComponent();
	FoliageHolder->AddInstanceComponent(HISM);

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
		const FTransform Xf(Rot, Pos, FVector(S));
		HISM->AddInstance(Xf, true);
		++Added;
	}

	ScatteredCount = Added;
	return Added;
}
