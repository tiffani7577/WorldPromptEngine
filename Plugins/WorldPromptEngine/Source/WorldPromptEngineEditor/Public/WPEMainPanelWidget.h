#pragma once

#include "CoreMinimal.h"
#include "EditorUtilityWidget.h"
#include "WPEMainPanelWidget.generated.h"

class UWebBrowser;
class UVerticalBox;

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

protected:
	UPROPERTY(Transient)
	TObjectPtr<UWebBrowser> Browser = nullptr;

	void EnsureBrowser();
	FString ResolveDefaultHtmlPath() const;
};
