#include "WPEMainPanelWidget.h"

#include "Blueprint/WidgetTree.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "WebBrowser.h"

DEFINE_LOG_CATEGORY_STATIC(LogWPEMainPanel, Log, All);

UWPEMainPanelWidget::UWPEMainPanelWidget(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	bAlwaysReregisterWithWindowsMenu = true;
}

FString UWPEMainPanelWidget::ResolveDefaultHtmlPath() const
{
	TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("WorldPromptEngine"));
	if (Plugin.IsValid())
	{
		return FPaths::ConvertRelativePathToFull(
			FPaths::Combine(Plugin->GetBaseDir(), TEXT("Content/Python/wpe_main_panel.html")));
	}
	return FString();
}

void UWPEMainPanelWidget::EnsureBrowser()
{
	if (!WidgetTree)
	{
		return;
	}

	if (Browser == nullptr)
	{
		UVerticalBox* Root = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass(), TEXT("WPE_Root"));
		Browser = WidgetTree->ConstructWidget<UWebBrowser>(UWebBrowser::StaticClass(), TEXT("WPE_Browser"));
		if (Root && Browser)
		{
			UVerticalBoxSlot* Slot = Root->AddChildToVerticalBox(Browser);
			if (Slot)
			{
				Slot->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
			}
			WidgetTree->RootWidget = Root;
		}
	}
}

void UWPEMainPanelWidget::LoadPanelHtml(const FString& AbsoluteHtmlPath)
{
	EnsureBrowser();
	if (!Browser)
	{
		UE_LOG(LogWPEMainPanel, Warning, TEXT("WebBrowser unavailable"));
		return;
	}

	FString Path = AbsoluteHtmlPath;
	if (Path.IsEmpty() || !FPaths::FileExists(Path))
	{
		Path = ResolveDefaultHtmlPath();
	}
	if (Path.IsEmpty() || !FPaths::FileExists(Path))
	{
		UE_LOG(LogWPEMainPanel, Warning, TEXT("wpe_main_panel.html not found"));
		return;
	}

	const FString Url = FString::Printf(TEXT("file:///%s"), *Path.Replace(TEXT("\\"), TEXT("/")));
	Browser->LoadURL(Url);
	UE_LOG(LogWPEMainPanel, Log, TEXT("Loaded guided panel: %s"), *Url);
}

void UWPEMainPanelWidget::NativeConstruct()
{
	Super::NativeConstruct();
	EnsureBrowser();
	LoadPanelHtml(ResolveDefaultHtmlPath());
}
