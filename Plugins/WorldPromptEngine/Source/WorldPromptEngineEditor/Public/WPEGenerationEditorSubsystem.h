#pragma once

#include "CoreMinimal.h"
#include "EditorSubsystem.h"
#include "WPEGenerationJob.h"
#include <atomic>
#include "WPEGenerationEditorSubsystem.generated.h"

class ALandscape;

/**
 * Editor Director for versioned JSON jobs.
 * Milestone: parse + validate + status only.
 * Later: async plain-data gen → existing ApplyHeightmapToLandscape (no duplicate write path).
 */
UCLASS()
class WORLDPROMPTENGINEEDITOR_API UWPEGenerationEditorSubsystem : public UEditorSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Canonical JSON Schema (draft-07) document as a string. */
	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	FString GetJobSchemaJson() const;

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	bool ValidateJobJson(const FString& JsonText, FString& OutError) const;

	/**
	 * Parse Director JSON or panel-style generate_from_prompt JSON.
	 * Accepts snake_case and nested params.
	 */
	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	bool ParseJobJson(const FString& JsonText, FWPEGenerationJob& OutJob, FString& OutError);

	/** Validate + store LastJob; sets status Validated or Failed. Does not generate. */
	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	bool SubmitJobJson(const FString& JsonText, FString& OutError);

	/**
	 * Kick async plain-data height generation for LastJob (or optional Json).
	 * Worker threads never touch UObjects; game thread calls existing ApplyHeightmapToLandscape.
	 */
	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	bool BeginGenerateFromLastJob(ALandscape* TargetLandscape, FString& OutError);

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	bool BeginGenerateFromJson(const FString& JsonText, ALandscape* TargetLandscape, FString& OutError);

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	void CancelGeneration();

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	bool IsGenerationRunning() const { return bGenerationRunning; }

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	FWPEGenerationJob GetLastJob() const { return LastJob; }

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	FWPEGenerationJobStatus GetLastStatus() const { return LastStatus; }

	UFUNCTION(BlueprintCallable, Category = "WPE|Director")
	void ResetStatus();

private:
	bool ParseJobFromJsonObject(const TSharedPtr<FJsonObject>& Root, FWPEGenerationJob& OutJob, FString& OutError) const;
	bool ValidateJob(const FWPEGenerationJob& Job, FString& OutError) const;
	static int32 ReadIntField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, int32 DefaultValue);
	static bool ReadBoolField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, bool DefaultValue);
	static float ReadFloatField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, float DefaultValue);
	static FString ReadStringField(const TSharedPtr<FJsonObject>& Obj, const TArray<FString>& Keys, const FString& DefaultValue);
	static bool IsValidLandscapeResolution(int32 Value);
	void ApplyGeneratedHeightsOnGameThread(TArray<int32> Heights, int32 ResX, int32 ResY, TWeakObjectPtr<ALandscape> WeakLandscape);

	UPROPERTY()
	FWPEGenerationJob LastJob;

	UPROPERTY()
	FWPEGenerationJobStatus LastStatus;

	std::atomic<bool> bCancelRequested{false};
	bool bGenerationRunning = false;
	uint32 GenerationToken = 0;

	TArray<float> LastHeights01;
	int32 LastHeightResX = 0;
	int32 LastHeightResY = 0;
};
