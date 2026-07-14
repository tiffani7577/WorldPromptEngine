#include "WPEGenerationEditorSubsystem.h"
#include "WPEWorldGeneratorSubsystem.h"
#include "WPEFoliageScatterSubsystem.h"
#include "WPEMaterialBridge.h"
#include "Landscape.h"
#include "Engine/StaticMesh.h"
#include "Async/Async.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

void UWPEGenerationEditorSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	ResetStatus();
	UE_LOG(LogTemp, Log, TEXT("WPEGenerationEditorSubsystem online (Director schema v1 — validate only)."));
}

void UWPEGenerationEditorSubsystem::Deinitialize()
{
	Super::Deinitialize();
}

void UWPEGenerationEditorSubsystem::ResetStatus()
{
	bCancelRequested.store(false);
	bGenerationRunning = false;
	LastStatus = FWPEGenerationJobStatus();
	LastStatus.Phase = EWPEGenerationPhase::Idle;
	LastStatus.bOk = true;
	LastStatus.Message = TEXT("Idle");
	LastStatus.Progress = 0.0f;
}

FString UWPEGenerationEditorSubsystem::GetJobSchemaJson() const
{
	// Kept inline so Python / panel can fetch without Content cooking.
	return TEXT(R"({
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WPEDirectorJob",
  "type": "object",
  "required": ["schema_version", "prompt", "seed"],
  "additionalProperties": true,
  "properties": {
    "schema_version": { "type": "integer", "const": 1 },
    "action": { "type": "string" },
    "prompt": { "type": "string", "minLength": 1 },
    "seed": { "type": "integer" },
    "allow_procedural_fallback": { "type": "boolean" },
    "prefer_landscape": { "type": "boolean" },
    "params": { "type": "object" },
    "terrain": {
      "type": "object",
      "properties": {
        "resolution_x": { "type": "integer", "minimum": 2 },
        "resolution_y": { "type": "integer", "minimum": 2 },
        "frequency": { "type": "number" },
        "octaves": { "type": "integer", "minimum": 1, "maximum": 16 },
        "persistence": { "type": "number" },
        "lacunarity": { "type": "number" },
        "apply_erosion": { "type": "boolean" },
        "thermal_iterations": { "type": "integer", "minimum": 0 },
        "hydraulic_iterations": { "type": "integer", "minimum": 0 }
      }
    },
    "biome": {
      "type": "object",
      "properties": {
        "region_count": { "type": "integer", "minimum": 1 },
        "snowline": { "type": "number", "minimum": 0, "maximum": 1 },
        "rock_slope_threshold": { "type": "number", "minimum": 0, "maximum": 1 },
        "wetness": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "foliage": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "use_hism": { "type": "boolean" },
        "density": { "type": "number", "minimum": 0 },
        "max_slope_degrees": { "type": "number", "minimum": 0, "maximum": 90 },
        "min_altitude_01": { "type": "number", "minimum": 0, "maximum": 1 },
        "max_altitude_01": { "type": "number", "minimum": 0, "maximum": 1 },
        "cluster_strength": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "material": {
      "type": "object",
      "properties": {
        "landscape_material_path": { "type": "string" },
        "mpc_path": { "type": "string" },
        "macro_scale": { "type": "number" }
      }
    },
    "atmosphere": {
      "type": "object",
      "properties": {
        "weather_preset": { "type": "string" },
        "ensure_lighting": { "type": "boolean" },
        "hide_sky_spheres": { "type": "boolean" }
      }
    }
  }
})");
}

bool UWPEGenerationEditorSubsystem::IsValidLandscapeResolution(int32 Value)
{
	return Value > 1 && ((Value - 1) % 63) == 0;
}

int32 UWPEGenerationEditorSubsystem::ReadIntField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, int32 DefaultValue)
{
	if (!Obj.IsValid())
	{
		return DefaultValue;
	}
	for (const FString& Key : Keys)
	{
		if (Obj->HasTypedField<EJson::Number>(Key))
		{
			return static_cast<int32>(Obj->GetNumberField(Key));
		}
	}
	return DefaultValue;
}

bool UWPEGenerationEditorSubsystem::ReadBoolField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, bool DefaultValue)
{
	if (!Obj.IsValid())
	{
		return DefaultValue;
	}
	for (const FString& Key : Keys)
	{
		if (Obj->HasTypedField<EJson::Boolean>(Key))
		{
			return Obj->GetBoolField(Key);
		}
	}
	return DefaultValue;
}

float UWPEGenerationEditorSubsystem::ReadFloatField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, float DefaultValue)
{
	if (!Obj.IsValid())
	{
		return DefaultValue;
	}
	for (const FString& Key : Keys)
	{
		if (Obj->HasTypedField<EJson::Number>(Key))
		{
			return static_cast<float>(Obj->GetNumberField(Key));
		}
	}
	return DefaultValue;
}

FString UWPEGenerationEditorSubsystem::ReadStringField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, const FString& DefaultValue)
{
	if (!Obj.IsValid())
	{
		return DefaultValue;
	}
	for (const FString& Key : Keys)
	{
		if (Obj->HasTypedField<EJson::String>(Key))
		{
			return Obj->GetStringField(Key);
		}
	}
	return DefaultValue;
}

bool UWPEGenerationEditorSubsystem::ValidateJob(const FWPEGenerationJob& Job, FString& OutError) const
{
	if (Job.SchemaVersion != 1)
	{
		OutError = TEXT("schema_version must be 1");
		return false;
	}
	if (Job.Prompt.TrimStartAndEnd().IsEmpty())
	{
		OutError = TEXT("prompt is required");
		return false;
	}
	if (Job.Terrain.ResolutionX < 2 || Job.Terrain.ResolutionY < 2)
	{
		OutError = TEXT("terrain resolution must be >= 2");
		return false;
	}
	if (!IsValidLandscapeResolution(Job.Terrain.ResolutionX) || !IsValidLandscapeResolution(Job.Terrain.ResolutionY))
	{
		OutError = FString::Printf(
			TEXT("terrain resolution %dx%d is not 63*N+1 (Landscape-compatible)"),
			Job.Terrain.ResolutionX, Job.Terrain.ResolutionY);
		return false;
	}
	if (Job.Terrain.Octaves < 1 || Job.Terrain.Octaves > 16)
	{
		OutError = TEXT("terrain.octaves must be in [1,16]");
		return false;
	}
	if (Job.Biome.Snowline < 0.0f || Job.Biome.Snowline > 1.0f
		|| Job.Biome.RockSlopeThreshold < 0.0f || Job.Biome.RockSlopeThreshold > 1.0f
		|| Job.Biome.Wetness < 0.0f || Job.Biome.Wetness > 1.0f)
	{
		OutError = TEXT("biome snowline/rock_slope_threshold/wetness must be in [0,1]");
		return false;
	}
	if (Job.Foliage.Density < 0.0f)
	{
		OutError = TEXT("foliage.density must be >= 0");
		return false;
	}
	if (Job.Foliage.MinAltitude01 > Job.Foliage.MaxAltitude01)
	{
		OutError = TEXT("foliage.min_altitude_01 must be <= max_altitude_01");
		return false;
	}
	OutError.Reset();
	return true;
}

bool UWPEGenerationEditorSubsystem::ParseJobFromJsonObject(
	const TSharedPtr<FJsonObject>& Root,
	FWPEGenerationJob& OutJob,
	FString& OutError) const
{
	if (!Root.IsValid())
	{
		OutError = TEXT("root JSON object is null");
		return false;
	}

	OutJob = FWPEGenerationJob();
	OutJob.SchemaVersion = ReadIntField(Root, { TEXT("schema_version"), TEXT("SchemaVersion") }, 1);
	OutJob.Action = ReadStringField(Root, { TEXT("action"), TEXT("Action") }, TEXT("generate_world"));
	OutJob.Prompt = ReadStringField(Root, { TEXT("prompt"), TEXT("Prompt") }, FString());
	OutJob.Seed = ReadIntField(Root, { TEXT("seed"), TEXT("Seed") }, 1337);
	OutJob.bAllowProceduralFallback = ReadBoolField(
		Root, { TEXT("allow_procedural_fallback"), TEXT("AllowProceduralFallback") }, true);
	OutJob.bPreferLandscape = ReadBoolField(
		Root, { TEXT("prefer_landscape"), TEXT("PreferLandscape") }, true);

	// Panel-style: params.width / params.height / params.seed
	const TSharedPtr<FJsonObject>* ParamsObj = nullptr;
	TSharedPtr<FJsonObject> Params;
	if (Root->TryGetObjectField(TEXT("params"), ParamsObj) && ParamsObj && ParamsObj->IsValid())
	{
		Params = *ParamsObj;
		OutJob.Seed = ReadIntField(Params, { TEXT("seed"), TEXT("Seed") }, OutJob.Seed);
		OutJob.Terrain.ResolutionX = ReadIntField(Params, { TEXT("width"), TEXT("resolution_x") }, OutJob.Terrain.ResolutionX);
		OutJob.Terrain.ResolutionY = ReadIntField(Params, { TEXT("height"), TEXT("resolution_y") }, OutJob.Terrain.ResolutionY);
		OutJob.bAllowProceduralFallback = ReadBoolField(
			Params, { TEXT("allow_procedural_fallback") }, OutJob.bAllowProceduralFallback);
		OutJob.bPreferLandscape = ReadBoolField(Params, { TEXT("prefer_landscape") }, OutJob.bPreferLandscape);
		OutJob.Terrain.bApplyErosion = ReadBoolField(Params, { TEXT("apply_erosion") }, OutJob.Terrain.bApplyErosion);
		OutJob.Foliage.bUseHISM = ReadBoolField(Params, { TEXT("use_hism") }, OutJob.Foliage.bUseHISM);
		OutJob.Foliage.bEnabled = ReadBoolField(Params, { TEXT("spawn_kit"), TEXT("spawn_foliage") }, OutJob.Foliage.bEnabled);
	}

	const TSharedPtr<FJsonObject>* TerrainObj = nullptr;
	if (Root->TryGetObjectField(TEXT("terrain"), TerrainObj) && TerrainObj && TerrainObj->IsValid())
	{
		const TSharedPtr<FJsonObject>& T = *TerrainObj;
		OutJob.Terrain.ResolutionX = ReadIntField(T, { TEXT("resolution_x"), TEXT("width") }, OutJob.Terrain.ResolutionX);
		OutJob.Terrain.ResolutionY = ReadIntField(T, { TEXT("resolution_y"), TEXT("height") }, OutJob.Terrain.ResolutionY);
		OutJob.Terrain.Frequency = ReadFloatField(T, { TEXT("frequency") }, OutJob.Terrain.Frequency);
		OutJob.Terrain.Octaves = ReadIntField(T, { TEXT("octaves") }, OutJob.Terrain.Octaves);
		OutJob.Terrain.Persistence = ReadFloatField(T, { TEXT("persistence") }, OutJob.Terrain.Persistence);
		OutJob.Terrain.Lacunarity = ReadFloatField(T, { TEXT("lacunarity") }, OutJob.Terrain.Lacunarity);
		OutJob.Terrain.bApplyErosion = ReadBoolField(T, { TEXT("apply_erosion") }, OutJob.Terrain.bApplyErosion);
		OutJob.Terrain.ThermalIterations = ReadIntField(T, { TEXT("thermal_iterations") }, OutJob.Terrain.ThermalIterations);
		OutJob.Terrain.HydraulicIterations = ReadIntField(T, { TEXT("hydraulic_iterations") }, OutJob.Terrain.HydraulicIterations);
	}

	const TSharedPtr<FJsonObject>* BiomeObj = nullptr;
	if (Root->TryGetObjectField(TEXT("biome"), BiomeObj) && BiomeObj && BiomeObj->IsValid())
	{
		const TSharedPtr<FJsonObject>& B = *BiomeObj;
		OutJob.Biome.RegionCount = ReadIntField(B, { TEXT("region_count") }, OutJob.Biome.RegionCount);
		OutJob.Biome.Snowline = ReadFloatField(B, { TEXT("snowline") }, OutJob.Biome.Snowline);
		OutJob.Biome.RockSlopeThreshold = ReadFloatField(B, { TEXT("rock_slope_threshold") }, OutJob.Biome.RockSlopeThreshold);
		OutJob.Biome.Wetness = ReadFloatField(B, { TEXT("wetness") }, OutJob.Biome.Wetness);
	}

	const TSharedPtr<FJsonObject>* FoliageObj = nullptr;
	if (Root->TryGetObjectField(TEXT("foliage"), FoliageObj) && FoliageObj && FoliageObj->IsValid())
	{
		const TSharedPtr<FJsonObject>& F = *FoliageObj;
		OutJob.Foliage.bEnabled = ReadBoolField(F, { TEXT("enabled") }, OutJob.Foliage.bEnabled);
		OutJob.Foliage.bUseHISM = ReadBoolField(F, { TEXT("use_hism") }, OutJob.Foliage.bUseHISM);
		OutJob.Foliage.Density = ReadFloatField(F, { TEXT("density") }, OutJob.Foliage.Density);
		OutJob.Foliage.MaxSlopeDegrees = ReadFloatField(F, { TEXT("max_slope_degrees") }, OutJob.Foliage.MaxSlopeDegrees);
		OutJob.Foliage.MinAltitude01 = ReadFloatField(F, { TEXT("min_altitude_01") }, OutJob.Foliage.MinAltitude01);
		OutJob.Foliage.MaxAltitude01 = ReadFloatField(F, { TEXT("max_altitude_01") }, OutJob.Foliage.MaxAltitude01);
		OutJob.Foliage.ClusterStrength = ReadFloatField(F, { TEXT("cluster_strength") }, OutJob.Foliage.ClusterStrength);
	}

	const TSharedPtr<FJsonObject>* MaterialObj = nullptr;
	if (Root->TryGetObjectField(TEXT("material"), MaterialObj) && MaterialObj && MaterialObj->IsValid())
	{
		const TSharedPtr<FJsonObject>& M = *MaterialObj;
		OutJob.Material.LandscapeMaterialPath = ReadStringField(
			M, { TEXT("landscape_material_path") }, OutJob.Material.LandscapeMaterialPath);
		OutJob.Material.MPCPath = ReadStringField(M, { TEXT("mpc_path") }, OutJob.Material.MPCPath);
		OutJob.Material.MacroScale = ReadFloatField(M, { TEXT("macro_scale") }, OutJob.Material.MacroScale);
	}

	const TSharedPtr<FJsonObject>* AtmosphereObj = nullptr;
	if (Root->TryGetObjectField(TEXT("atmosphere"), AtmosphereObj) && AtmosphereObj && AtmosphereObj->IsValid())
	{
		const TSharedPtr<FJsonObject>& A = *AtmosphereObj;
		OutJob.Atmosphere.WeatherPreset = ReadStringField(A, { TEXT("weather_preset") }, OutJob.Atmosphere.WeatherPreset);
		OutJob.Atmosphere.bEnsureLighting = ReadBoolField(A, { TEXT("ensure_lighting") }, OutJob.Atmosphere.bEnsureLighting);
		OutJob.Atmosphere.bHideSkySpheres = ReadBoolField(A, { TEXT("hide_sky_spheres") }, OutJob.Atmosphere.bHideSkySpheres);
	}

	// Panel generate_from_prompt often omits schema_version — normalize to 1 when prompt present.
	if (!Root->HasField(TEXT("schema_version")) && !OutJob.Prompt.IsEmpty())
	{
		OutJob.SchemaVersion = 1;
		if (OutJob.Action.IsEmpty() || OutJob.Action == TEXT("generate_from_prompt"))
		{
			OutJob.Action = TEXT("generate_world");
		}
	}

	return ValidateJob(OutJob, OutError);
}

bool UWPEGenerationEditorSubsystem::ParseJobJson(const FString& JsonText, FWPEGenerationJob& OutJob, FString& OutError)
{
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = TEXT("invalid JSON");
		return false;
	}
	return ParseJobFromJsonObject(Root, OutJob, OutError);
}

bool UWPEGenerationEditorSubsystem::ValidateJobJson(const FString& JsonText, FString& OutError) const
{
	FWPEGenerationJob Job;
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = TEXT("invalid JSON");
		return false;
	}
	return ParseJobFromJsonObject(Root, Job, OutError);
}

bool UWPEGenerationEditorSubsystem::SubmitJobJson(const FString& JsonText, FString& OutError)
{
	FWPEGenerationJob Job;
	if (!ParseJobJson(JsonText, Job, OutError))
	{
		LastStatus.Phase = EWPEGenerationPhase::Failed;
		LastStatus.bOk = false;
		LastStatus.Message = OutError;
		LastStatus.Progress = 0.0f;
		return false;
	}

	LastJob = Job;
	LastStatus.Phase = EWPEGenerationPhase::Validated;
	LastStatus.bOk = true;
	LastStatus.Message = FString::Printf(
		TEXT("Validated schema v%d seed=%d res=%dx%d"),
		Job.SchemaVersion, Job.Seed, Job.Terrain.ResolutionX, Job.Terrain.ResolutionY);
	LastStatus.Progress = 0.05f;
	UE_LOG(LogTemp, Log, TEXT("WPE Director: %s"), *LastStatus.Message);
	return true;
}

namespace WPEDirectorNoise
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
			const int32 SafeOctaves = FMath::Clamp(Octaves, 1, 16);
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

	/** Lightweight thermal-ish smoothing on plain arrays (no UObjects). */
	static void SimpleErosionPass(TArray<float>& Height01, int32 ResX, int32 ResY, int32 Iterations, const TFunctionRef<bool()>& ShouldCancel)
	{
		if (Iterations <= 0 || ResX < 3 || ResY < 3)
		{
			return;
		}
		TArray<float> Scratch = Height01;
		for (int32 It = 0; It < Iterations; ++It)
		{
			if (ShouldCancel())
			{
				return;
			}
			for (int32 Y = 1; Y < ResY - 1; ++Y)
			{
				for (int32 X = 1; X < ResX - 1; ++X)
				{
					const int32 I = Y * ResX + X;
					const float C = Height01[I];
					const float Avg = 0.25f * (
						Height01[I - 1] + Height01[I + 1] + Height01[I - ResX] + Height01[I + ResX]);
					const float Diff = C - Avg;
					Scratch[I] = C - Diff * 0.35f;
				}
			}
			Height01 = Scratch;
		}
	}
}

void UWPEGenerationEditorSubsystem::CancelGeneration()
{
	bCancelRequested.store(true);
	if (bGenerationRunning)
	{
		LastStatus.Phase = EWPEGenerationPhase::Cancelled;
		LastStatus.Message = TEXT("Cancel requested");
	}
}

void UWPEGenerationEditorSubsystem::ApplyGeneratedHeightsOnGameThread(
	TArray<int32> Heights,
	int32 ResX,
	int32 ResY,
	TWeakObjectPtr<ALandscape> WeakLandscape)
{
	bGenerationRunning = false;

	if (bCancelRequested.load())
	{
		LastStatus.Phase = EWPEGenerationPhase::Cancelled;
		LastStatus.bOk = false;
		LastStatus.Message = TEXT("Cancelled before Landscape apply");
		LastStatus.Progress = 0.0f;
		return;
	}

	ALandscape* Landscape = WeakLandscape.Get();
	if (!Landscape)
	{
		LastStatus.Phase = EWPEGenerationPhase::Failed;
		LastStatus.bOk = false;
		LastStatus.Message = TEXT("Landscape target became invalid before apply");
		return;
	}

	if (!GEngine)
	{
		LastStatus.Phase = EWPEGenerationPhase::Failed;
		LastStatus.bOk = false;
		LastStatus.Message = TEXT("GEngine unavailable");
		return;
	}

	UWPEWorldGeneratorSubsystem* Native = GEngine->GetEngineSubsystem<UWPEWorldGeneratorSubsystem>();
	if (!Native)
	{
		LastStatus.Phase = EWPEGenerationPhase::Failed;
		LastStatus.bOk = false;
		LastStatus.Message = TEXT("UWPEWorldGeneratorSubsystem missing");
		return;
	}

	LastStatus.Phase = EWPEGenerationPhase::ApplyingLandscape;
	LastStatus.Message = TEXT("Applying heights via existing SetHeightData adapter");
	LastStatus.Progress = 0.9f;

	// REUSE Stage 1 path — do not duplicate FLandscapeEditDataInterface writes here.
	const bool bOk = Native->ApplyHeightmapToLandscape(Landscape, Heights, ResX, ResY);
	if (!bOk)
	{
		LastStatus.Phase = EWPEGenerationPhase::Failed;
		LastStatus.bOk = false;
		LastStatus.Message = TEXT("ApplyHeightmapToLandscape rejected or failed");
		LastStatus.Progress = 1.0f;
		return;
	}

	// Cache 0..1 heights for terrain-aware foliage (same buffer family, no re-noise).
	LastHeights01.SetNumUninitialized(Heights.Num());
	for (int32 I = 0; I < Heights.Num(); ++I)
	{
		LastHeights01[I] = FMath::Clamp(Heights[I] / 65535.0f, 0.0f, 1.0f);
	}
	LastHeightResX = ResX;
	LastHeightResY = ResY;

	// MPC bridge — authored materials only.
	if (LastJob.Material.MPCPath.Len() > 0)
	{
		UWPEMaterialBridge::ApplyWorldMPCParamsByPath(
			Landscape,
			LastJob.Material.MPCPath,
			LastJob.Biome.Snowline,
			LastJob.Biome.RockSlopeThreshold,
			LastJob.Biome.Wetness,
			LastJob.Material.MacroScale,
			LastJob.Material.Tint);
	}

	// Terrain-aware HISM foliage when enabled.
	if (LastJob.Foliage.bEnabled && LastJob.Foliage.bUseHISM)
	{
		LastStatus.Phase = EWPEGenerationPhase::PlacingFoliage;
		LastStatus.Message = TEXT("Placing terrain-aware HISM foliage");
		LastStatus.Progress = 0.95f;
		if (UWPEFoliageScatterSubsystem* Foliage = GEngine->GetEngineSubsystem<UWPEFoliageScatterSubsystem>())
		{
			UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cone.Cone"));
			if (Mesh)
			{
				const float WorldSize = float(FMath::Max(ResX, ResY)) * 100.0f;
				const FVector Origin(-0.5f * WorldSize, -0.5f * WorldSize, 0.0f);
				const int32 Count = FMath::Clamp(int32(400.0f * LastJob.Foliage.Density), 40, 2500);
				Foliage->ScatterTerrainAware(
					Mesh,
					LastHeights01,
					ResX,
					ResY,
					Origin,
					WorldSize,
					1800.0f,
					Count,
					LastJob.Seed ^ 0xF011,
					LastJob.Foliage.MaxSlopeDegrees,
					LastJob.Foliage.MinAltitude01,
					LastJob.Foliage.MaxAltitude01,
					LastJob.Foliage.ClusterStrength,
					0.75f,
					1.6f,
					true);
			}
		}
	}

	LastStatus.Phase = EWPEGenerationPhase::Completed;
	LastStatus.bOk = true;
	LastStatus.Message = FString::Printf(TEXT("Applied %dx%d via existing native adapter"), ResX, ResY);
	LastStatus.Progress = 1.0f;
	UE_LOG(LogTemp, Log, TEXT("WPE Director: %s"), *LastStatus.Message);
}

bool UWPEGenerationEditorSubsystem::BeginGenerateFromJson(const FString& JsonText, ALandscape* TargetLandscape, FString& OutError)
{
	if (!SubmitJobJson(JsonText, OutError))
	{
		return false;
	}
	return BeginGenerateFromLastJob(TargetLandscape, OutError);
}

bool UWPEGenerationEditorSubsystem::BeginGenerateFromLastJob(ALandscape* TargetLandscape, FString& OutError)
{
	if (bGenerationRunning)
	{
		OutError = TEXT("generation already running");
		return false;
	}
	if (!TargetLandscape)
	{
		OutError = TEXT("TargetLandscape is null");
		LastStatus.Phase = EWPEGenerationPhase::Failed;
		LastStatus.bOk = false;
		LastStatus.Message = OutError;
		return false;
	}
	if (LastStatus.Phase != EWPEGenerationPhase::Validated
		&& LastStatus.Phase != EWPEGenerationPhase::Completed
		&& LastStatus.Phase != EWPEGenerationPhase::Failed
		&& LastStatus.Phase != EWPEGenerationPhase::Cancelled
		&& LastStatus.Phase != EWPEGenerationPhase::Idle)
	{
		// Allow restart from Validated primarily; also tolerate Idle if LastJob already set.
	}
	if (LastJob.Prompt.IsEmpty())
	{
		OutError = TEXT("no validated job — call SubmitJobJson first");
		return false;
	}

	bCancelRequested.store(false);
	bGenerationRunning = true;
	++GenerationToken;
	const uint32 Token = GenerationToken;
	const FWPEGenerationJob JobCopy = LastJob;
	TWeakObjectPtr<ALandscape> WeakLandscape(TargetLandscape);
	TWeakObjectPtr<UWPEGenerationEditorSubsystem> WeakThis(this);

	LastStatus.Phase = EWPEGenerationPhase::GeneratingTerrain;
	LastStatus.bOk = true;
	LastStatus.Message = TEXT("Async fBm / erosion on worker (plain arrays)");
	LastStatus.Progress = 0.1f;

	Async(EAsyncExecution::ThreadPool, [WeakThis, WeakLandscape, JobCopy, Token]()
	{
		const int32 ResX = JobCopy.Terrain.ResolutionX;
		const int32 ResY = JobCopy.Terrain.ResolutionY;
		const int32 Count = ResX * ResY;

		auto ShouldCancel = [WeakThis, Token]() -> bool
		{
			if (UWPEGenerationEditorSubsystem* Self = WeakThis.Get())
			{
				return Self->bCancelRequested.load() || Self->GenerationToken != Token;
			}
			return true;
		};

		TArray<float> Height01;
		Height01.SetNumUninitialized(Count);
		const WPEDirectorNoise::FPerlin2D Noise(JobCopy.Seed);
		for (int32 Y = 0; Y < ResY; ++Y)
		{
			if (ShouldCancel())
			{
				break;
			}
			for (int32 X = 0; X < ResX; ++X)
			{
				const float N = Noise.FBM(
					static_cast<float>(X),
					static_cast<float>(Y),
					JobCopy.Terrain.Octaves,
					JobCopy.Terrain.Frequency,
					JobCopy.Terrain.Persistence,
					JobCopy.Terrain.Lacunarity);
				Height01[Y * ResX + X] = FMath::Clamp(N * 0.5f + 0.5f, 0.0f, 1.0f);
			}
		}

		if (!ShouldCancel() && JobCopy.Terrain.bApplyErosion)
		{
			const int32 Passes = FMath::Max(JobCopy.Terrain.ThermalIterations, JobCopy.Terrain.HydraulicIterations) / 4;
			WPEDirectorNoise::SimpleErosionPass(Height01, ResX, ResY, FMath::Clamp(Passes, 0, 32), ShouldCancel);
		}

		TArray<int32> Heights;
		Heights.SetNumUninitialized(Count);
		for (int32 I = 0; I < Count; ++I)
		{
			Heights[I] = static_cast<int32>(FMath::Clamp(Height01[I], 0.0f, 1.0f) * 65535.0f);
		}

		AsyncTask(ENamedThreads::GameThread, [WeakThis, WeakLandscape, Heights = MoveTemp(Heights), ResX, ResY, Token]() mutable
		{
			UWPEGenerationEditorSubsystem* Self = WeakThis.Get();
			if (!Self || Self->GenerationToken != Token)
			{
				return;
			}
			if (Self->bCancelRequested.load())
			{
				Self->bGenerationRunning = false;
				Self->LastStatus.Phase = EWPEGenerationPhase::Cancelled;
				Self->LastStatus.bOk = false;
				Self->LastStatus.Message = TEXT("Cancelled after worker");
				return;
			}
			Self->LastStatus.Progress = 0.75f;
			Self->ApplyGeneratedHeightsOnGameThread(MoveTemp(Heights), ResX, ResY, WeakLandscape);
		});
	});

	OutError.Reset();
	return true;
}
