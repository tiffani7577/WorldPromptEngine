#include "WPENiagaraVfxLibrary.h"

#include "EditorAssetLibrary.h"
#include "NiagaraEmitter.h"
#include "NiagaraExternalSystemEditorUtilities.h"
#include "NiagaraSystem.h"
#include "NiagaraTypes.h"
#include "NiagaraVariant.h"

DEFINE_LOG_CATEGORY_STATIC(LogWPENiagaraVfx, Log, All);

namespace WPENiagaraVfxPrivate
{
	static const FString VfxPackagePath(TEXT("/Game/WorldPromptEngine/VFX"));
	static const FName UserSpawnRateMultiplierName(TEXT("User.SpawnRateMultiplier"));

	struct FVfxSpec
	{
		const TCHAR* Name;
		const TCHAR* Label;
		const TCHAR* EmitterTemplatePath;
		float BaseSpawnRate;
	};

	// Emitter templates from /Niagara/DefaultAssets/Templates/Emitters — real spawn graphs.
	static const FVfxSpec Specs[] = {
		{
			TEXT("NS_WPE_BioBioluminescent"),
			TEXT("Floating soft glowing orbs, slow drift"),
			TEXT("/Niagara/DefaultAssets/Templates/Emitters/HangingParticulates"),
			12.0f
		},
		{
			TEXT("NS_WPE_Mist"),
			TEXT("Low ground fog wisps, atmospheric"),
			TEXT("/Niagara/DefaultAssets/Templates/Emitters/BlowingParticles"),
			20.0f
		},
		{
			TEXT("NS_WPE_Embers"),
			TEXT("Slow rising embers/sparks"),
			TEXT("/Niagara/DefaultAssets/Templates/Emitters/Fountain"),
			30.0f
		},
		{
			TEXT("NS_WPE_OceanSpray"),
			TEXT("Fine water mist particles"),
			TEXT("/Niagara/DefaultAssets/Templates/Emitters/Fountain"),
			45.0f
		},
		{
			TEXT("NS_WPE_CrystalShimmer"),
			TEXT("Small light flecks, high frequency shimmer"),
			TEXT("/Niagara/DefaultAssets/Templates/Emitters/HangingParticulates"),
			80.0f
		},
	};

	static void LogContextErrors(const FNiagaraExternalEditContext& Context, const TCHAR* Op)
	{
		for (const FText& Err : Context.Errors)
		{
			UE_LOG(LogWPENiagaraVfx, Warning, TEXT("%s: %s"), Op, *Err.ToString());
		}
	}

	static bool SaveSystemAsset(UNiagaraSystem* System)
	{
		if (!System)
		{
			return false;
		}
		return UEditorAssetLibrary::SaveLoadedAsset(System, /*bOnlyIfIsDirty=*/false);
	}

	static bool AddUserSpawnRateMultiplier(UNiagaraSystem* System, float DefaultMultiplier, FNiagaraExternalEditContext& Context)
	{
		if (!System)
		{
			return false;
		}

		// Skip if already present.
		FNiagaraExt_UserVariables Existing;
		UNiagaraExternalEditUtilities::GetUserVariables(System, Existing, Context);
		for (const FNiagaraExt_UserVariable& UV : Existing.UserVariables)
		{
			if (UV.Name == UserSpawnRateMultiplierName
				|| UV.Name == FName(TEXT("SpawnRateMultiplier")))
			{
				return true;
			}
		}

		FNiagaraExt_UserVariable UserVar;
		UserVar.Name = UserSpawnRateMultiplierName;
		UserVar.Type = FNiagaraTypeDefinition::GetFloatDef();
		UserVar.Description = FText::FromString(
			TEXT("Performance Mode OSC highs → spawn rate scale (driven by performance_engine.py)"));

		FNiagaraFloat FloatValue;
		FloatValue.Value = DefaultMultiplier;
		FNiagaraVariant Variant;
		Variant.SetBytesValue(FNiagaraTypeDefinition::GetFloatDef(), FloatValue);
		UserVar.DefaultValue.Set(FNiagaraTypeDefinition::GetFloatDef(), Variant);

		UNiagaraExternalEditUtilities::AddUserVariable(System, UserVar, Context);
		if (Context.HasErrors())
		{
			LogContextErrors(Context, TEXT("AddUserVariable"));
			return false;
		}
		return true;
	}

	static bool BindSpawnRateToUserMultiplier(UNiagaraSystem* System, float BaseSpawnRate, FNiagaraExternalEditContext& Context)
	{
		if (!System)
		{
			return false;
		}

		FNiagaraExt_SystemSummary Summary;
		UNiagaraExternalEditUtilities::GetSystemSummary(System, Summary, Context);
		if (Summary.Emitters.Num() == 0)
		{
			UE_LOG(LogWPENiagaraVfx, Warning, TEXT("%s has no emitters to bind SpawnRate"), *System->GetName());
			return false;
		}

		bool bBoundAny = false;
		for (const FNiagaraExt_EmitterSummary& Emitter : Summary.Emitters)
		{
			FNiagaraExt_StackItemReference EmitterRef(System, Emitter.EmitterName);
			FNiagaraExt_EmitterTopology Topology;
			UNiagaraExternalEditUtilities::GetEmitterTopology(EmitterRef, Topology, Context);
			if (Context.HasErrors())
			{
				LogContextErrors(Context, TEXT("GetEmitterTopology"));
				Context.Errors.Reset();
				continue;
			}

			for (const FNiagaraExt_ModuleTopology& Module : Topology.EmitterUpdateScript.Modules)
			{
				const FString ModuleNameStr = Module.ModuleName.ToString();
				const bool bLooksLikeSpawnRate =
					ModuleNameStr.Contains(TEXT("SpawnRate"), ESearchCase::IgnoreCase)
					|| ModuleNameStr.Equals(TEXT("Spawn Rate"), ESearchCase::IgnoreCase);
				if (!bLooksLikeSpawnRate)
				{
					continue;
				}

				// Prefer binding the SpawnRate float input via HLSL: User.SpawnRateMultiplier * Base
				for (const FNiagaraExt_StackInputTopology& Input : Module.Inputs)
				{
					const FString InputName = Input.Name.ToString();
					const bool bIsSpawnRateInput =
						InputName.Equals(TEXT("SpawnRate"), ESearchCase::IgnoreCase)
						|| InputName.EndsWith(TEXT(".SpawnRate"), ESearchCase::IgnoreCase)
						|| InputName.Equals(TEXT("Spawn Rate"), ESearchCase::IgnoreCase);
					if (!bIsSpawnRateInput || !Input.bIsEditable)
					{
						continue;
					}

					FNiagaraExt_StackItemReference InputRef(System, Emitter.EmitterName, Topology.EmitterUpdateScript.ScriptName, Module.ModuleName);
					InputRef.InputNameStack.Reset();
					InputRef.InputNameStack.Add(Input.Name);

					FNiagaraExt_StackInputValue Value;
					FNiagaraExt_StackInputData_HlslExpression& Expr =
						Value.InitializeAs<FNiagaraExt_StackInputData_HlslExpression>();
					Expr.HlslExpression = FString::Printf(
						TEXT("User.SpawnRateMultiplier * %g"), BaseSpawnRate);

					UNiagaraExternalEditUtilities::SetStackInputData(InputRef, Value, Context);
					if (Context.HasErrors())
					{
						// Fallback: link directly to the user float (spawn rate ~= multiplier).
						Context.Errors.Reset();
						FNiagaraExt_StackInputValue LinkedValue;
						FNiagaraExt_StackInputData_Linked& Linked =
							LinkedValue.InitializeAs<FNiagaraExt_StackInputData_Linked>();
						Linked.LinkedVariable.Name = UserSpawnRateMultiplierName;
						Linked.LinkedVariable.Type = FNiagaraTypeDefinition::GetFloatDef();
						UNiagaraExternalEditUtilities::SetStackInputData(InputRef, LinkedValue, Context);
						if (Context.HasErrors())
						{
							LogContextErrors(Context, TEXT("SetStackInputData SpawnRate"));
							Context.Errors.Reset();
							continue;
						}
					}

					UE_LOG(LogWPENiagaraVfx, Log,
						TEXT("Bound %s/%s/%s SpawnRate -> User.SpawnRateMultiplier * %g"),
						*System->GetName(), *Emitter.EmitterName.ToString(), *ModuleNameStr, BaseSpawnRate);
					bBoundAny = true;
					break;
				}
			}
		}

		return bBoundAny;
	}

	static UNiagaraEmitter* LoadEmitterTemplate(const TCHAR* Path)
	{
		UObject* Obj = UEditorAssetLibrary::LoadAsset(FString(Path));
		return Cast<UNiagaraEmitter>(Obj);
	}

	static UNiagaraSystem* CreateOrLoadSystem(const FVfxSpec& Spec, bool bForceRecreate)
	{
		const FString AssetPath = VfxPackagePath / Spec.Name;
		if (UEditorAssetLibrary::DoesAssetExist(AssetPath))
		{
			if (bForceRecreate)
			{
				UEditorAssetLibrary::DeleteAsset(AssetPath);
			}
			else
			{
				return Cast<UNiagaraSystem>(UEditorAssetLibrary::LoadAsset(AssetPath));
			}
		}

		if (!UEditorAssetLibrary::DoesDirectoryExist(VfxPackagePath))
		{
			UEditorAssetLibrary::MakeDirectory(VfxPackagePath);
		}

		FNiagaraExternalEditContext CreateContext;
		UNiagaraSystem* System = UNiagaraExternalEditUtilities::CreateNiagaraSystem(
			Spec.Name, VfxPackagePath, nullptr, CreateContext);
		if (!System)
		{
			LogContextErrors(CreateContext, TEXT("CreateNiagaraSystem"));
			return nullptr;
		}

		FNiagaraExternalEditContext EditContext(System);
		UNiagaraEmitter* Template = LoadEmitterTemplate(Spec.EmitterTemplatePath);
		if (!Template)
		{
			UE_LOG(LogWPENiagaraVfx, Warning,
				TEXT("Emitter template missing: %s — system will be empty until edited"),
				Spec.EmitterTemplatePath);
		}
		else
		{
			FNiagaraExt_EmitterTopology OutTopo;
			UNiagaraExternalEditUtilities::AddEmitter(Template, FName(Spec.Name), OutTopo, EditContext);
			if (EditContext.HasErrors())
			{
				LogContextErrors(EditContext, TEXT("AddEmitter"));
				EditContext.Errors.Reset();
			}
		}

		UEditorAssetLibrary::SetMetadataTag(System, TEXT("WPE.VFX.Label"), Spec.Label);
		UEditorAssetLibrary::SetMetadataTag(System, TEXT("WPE.VFX.UserParam"), TEXT("User.SpawnRateMultiplier"));
		UEditorAssetLibrary::SetMetadataTag(System, TEXT("WPE.VFX.SpawnRate"), FString::SanitizeFloat(Spec.BaseSpawnRate));

		return System;
	}
}

bool UWPENiagaraVfxLibrary::EnsureSpawnRateMultiplier(UNiagaraSystem* System, float BaseSpawnRate, float DefaultMultiplier)
{
	using namespace WPENiagaraVfxPrivate;
	if (!System)
	{
		return false;
	}

	FNiagaraExternalEditContext Context(System);
	const bool bAdded = AddUserSpawnRateMultiplier(System, DefaultMultiplier, Context);
	Context.Errors.Reset();
	const bool bBound = BindSpawnRateToUserMultiplier(System, BaseSpawnRate, Context);
	SaveSystemAsset(System);
	return bAdded && bBound;
}

bool UWPENiagaraVfxLibrary::CreateAllWpeVfxSystems(bool bForceRecreate)
{
	using namespace WPENiagaraVfxPrivate;

	int32 OkCount = 0;
	for (const FVfxSpec& Spec : Specs)
	{
		UNiagaraSystem* System = CreateOrLoadSystem(Spec, bForceRecreate);
		if (!System)
		{
			UE_LOG(LogWPENiagaraVfx, Error, TEXT("Failed to create %s"), Spec.Name);
			continue;
		}

		if (EnsureSpawnRateMultiplier(System, Spec.BaseSpawnRate, 1.0f))
		{
			++OkCount;
			UE_LOG(LogWPENiagaraVfx, Log, TEXT("Ready: %s/%s (%s)"),
				*VfxPackagePath, Spec.Name, Spec.Label);
		}
		else
		{
			// Still count as created if asset exists with user param even if bind failed.
			FNiagaraExternalEditContext Context(System);
			if (AddUserSpawnRateMultiplier(System, 1.0f, Context))
			{
				SaveSystemAsset(System);
				++OkCount;
				UE_LOG(LogWPENiagaraVfx, Warning,
					TEXT("%s created with User.SpawnRateMultiplier but SpawnRate bind incomplete"),
					Spec.Name);
			}
		}
	}

	const int32 Total = UE_ARRAY_COUNT(Specs);
	UE_LOG(LogWPENiagaraVfx, Log, TEXT("WPE VFX: %d/%d systems ready at %s"), OkCount, Total, *VfxPackagePath);
	return OkCount == Total;
}

bool UWPENiagaraVfxLibrary::RebuildCrystalShimmer()
{
	using namespace WPENiagaraVfxPrivate;

	const FString AssetPath = VfxPackagePath / TEXT("NS_WPE_CrystalShimmer");
	UNiagaraSystem* System = Cast<UNiagaraSystem>(UEditorAssetLibrary::LoadAsset(AssetPath));
	if (!System)
	{
		// Create empty then continue.
		FNiagaraExternalEditContext CreateContext;
		System = UNiagaraExternalEditUtilities::CreateNiagaraSystem(
			TEXT("NS_WPE_CrystalShimmer"), VfxPackagePath, nullptr, CreateContext);
		if (!System)
		{
			LogContextErrors(CreateContext, TEXT("RebuildCrystal CreateNiagaraSystem"));
			return false;
		}
	}

	FNiagaraExternalEditContext Context(System);

	// Strip existing emitters (e.g. InfiniteParticleLifetime) without deleting the package.
	{
		FNiagaraExt_SystemSummary Summary;
		UNiagaraExternalEditUtilities::GetSystemSummary(System, Summary, Context);
		Context.Errors.Reset();
		TArray<FName> EmitterNames;
		for (const FNiagaraExt_EmitterSummary& Em : Summary.Emitters)
		{
			EmitterNames.Add(Em.EmitterName);
		}
		for (const FName& EmName : EmitterNames)
		{
			FNiagaraExt_StackItemReference EmRef(System, EmName);
			UNiagaraExternalEditUtilities::RemoveEmitter(EmRef, Context);
			if (Context.HasErrors())
			{
				LogContextErrors(Context, TEXT("RebuildCrystal RemoveEmitter"));
				Context.Errors.Reset();
			}
		}
	}

	UNiagaraEmitter* Template = LoadEmitterTemplate(
		TEXT("/Niagara/DefaultAssets/Templates/Emitters/HangingParticulates"));
	if (!Template)
	{
		UE_LOG(LogWPENiagaraVfx, Error, TEXT("RebuildCrystal: HangingParticulates template missing"));
		return false;
	}

	FNiagaraExt_EmitterTopology OutTopo;
	UNiagaraExternalEditUtilities::AddEmitter(Template, FName(TEXT("NS_WPE_CrystalShimmer")), OutTopo, Context);
	if (Context.HasErrors())
	{
		LogContextErrors(Context, TEXT("RebuildCrystal AddEmitter"));
		return false;
	}

	UEditorAssetLibrary::SetMetadataTag(System, TEXT("WPE.VFX.Label"),
		TEXT("Small light flecks, high frequency shimmer"));
	UEditorAssetLibrary::SetMetadataTag(System, TEXT("WPE.VFX.UserParam"), TEXT("User.SpawnRateMultiplier"));
	UEditorAssetLibrary::SetMetadataTag(System, TEXT("WPE.VFX.SpawnRate"), TEXT("80.0"));

	const bool bOk = EnsureSpawnRateMultiplier(System, 80.0f, 1.0f);
	UE_LOG(LogWPENiagaraVfx, Log, TEXT("RebuildCrystalShimmer -> %s"), bOk ? TEXT("ok") : TEXT("partial"));
	return bOk;
}
