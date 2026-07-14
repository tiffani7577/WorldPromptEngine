#pragma once

#include "CoreMinimal.h"
#include "EditorUtilityWidget.h"
#include "WPEMainPanelWidget.generated.h"

class UWebBrowser;
class UOverlay;

/**
 * Dockable guided panel host. Builds a full-bleed WebBrowser that loads
 * Plugins/WorldPromptEngine/Content/Python/wpe_main_panel.html.
 */
UCLASS()
class WORLDPROMPTENGINEEDITOR_API UWPEMainPanelWidget : public UEditorUtilityWidget
{
	GENERATED_BODY()

public:
	UWPEMainPanelWidget(const FObjectInitializer& ObjectInitializer);

	UFUNCTION(BlueprintCallable, Category = "WPE")
	void LoadPanelHtml(const FString& AbsoluteHtmlPath);

	virtual void NativeConstruct() override;
	virtual TSharedRef<SWidget> RebuildWidget() override;

protected:
	UPROPERTY(Transient)
	TObjectPtr<UWebBrowser> Browser = nullptr;

	UPROPERTY(Transient)
	TObjectPtr<UOverlay> RootOverlay = nullptr;

	void EnsureBrowser();
	FString ResolveDefaultHtmlPath() const;
	bool TryLoadHtmlIntoBrowser(const FString& AbsoluteHtmlPath);
	bool DeferredLoadTick(float DeltaTime);

	FString PendingHtmlPath;
	int32 LoadRetryCount = 0;
	bool bLoadTickerActive = false;
};
