#include "WPEMainPanelWidget.h"

#include "Blueprint/WidgetTree.h"
#include "Components/Overlay.h"
#include "Components/OverlaySlot.h"
#include "Containers/Ticker.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/FileHelper.h"
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

	// Must run BEFORE Super::RebuildWidget / TakeWidget. NativeConstruct is too late —
	// the Slate tree would already be built from an empty Blueprint root (black tab).
	if (Browser == nullptr || RootOverlay == nullptr || WidgetTree->RootWidget != RootOverlay)
	{
		RootOverlay = WidgetTree->ConstructWidget<UOverlay>(UOverlay::StaticClass(), TEXT("WPE_RootOverlay"));
		Browser = WidgetTree->ConstructWidget<UWebBrowser>(UWebBrowser::StaticClass(), TEXT("WPE_Browser"));
		if (RootOverlay && Browser)
		{
			// Prefer opaque fill — transparency often shows as solid black in editor tabs.
			Browser->SetVisibility(ESlateVisibility::Visible);
			if (UOverlaySlot* Slot = RootOverlay->AddChildToOverlay(Browser))
			{
				Slot->SetHorizontalAlignment(HAlign_Fill);
				Slot->SetVerticalAlignment(VAlign_Fill);
			}
			WidgetTree->RootWidget = RootOverlay;
		}
	}
}

bool UWPEMainPanelWidget::TryLoadHtmlIntoBrowser(const FString& AbsoluteHtmlPath)
{
	if (!Browser)
	{
		return false;
	}

	FString Path = AbsoluteHtmlPath;
	if (Path.IsEmpty() || !FPaths::FileExists(Path))
	{
		Path = ResolveDefaultHtmlPath();
	}
	if (Path.IsEmpty() || !FPaths::FileExists(Path))
	{
		UE_LOG(LogWPEMainPanel, Warning, TEXT("wpe_main_panel.html not found at '%s'"), *AbsoluteHtmlPath);
		return false;
	}

	FString Html;
	if (!FFileHelper::LoadFileToString(Html, *Path))
	{
		UE_LOG(LogWPEMainPanel, Warning, TEXT("Failed to read HTML: %s"), *Path);
		return false;
	}

	// Both LoadURL and LoadString are silent no-ops until SWebBrowser exists
	// (RebuildWidget). Prefer LoadString + http dummy URL so paths with spaces
	// (e.g. "Unreal Projects") never break loading.
	const FString DummyUrl = TEXT("http://worldpromptengine.local/panel");
	Browser->LoadString(Html, DummyUrl);

	FString Current = Browser->GetUrl();
	if (Current.IsEmpty())
	{
		// Slate browser not ready yet — encode a correct file:/// URL and try LoadURL.
		FString Encoded = Path.Replace(TEXT("\\"), TEXT("/"));
		Encoded.ReplaceInline(TEXT(" "), TEXT("%20"));
		if (!Encoded.StartsWith(TEXT("/")))
		{
			Encoded = TEXT("/") + Encoded;
		}
		const FString FileUrl = FString(TEXT("file://")) + Encoded; // file:///Users/...
		Browser->LoadURL(FileUrl);
		Current = Browser->GetUrl();
		UE_LOG(LogWPEMainPanel, Log, TEXT("Slate not ready for LoadString; tried file URL=%s url_now=%s"),
			*FileUrl, *Current);
	}
	else
	{
		UE_LOG(LogWPEMainPanel, Log, TEXT("Loaded guided panel via LoadString (%d chars) url=%s"),
			Html.Len(), *Current);
	}

	return !Current.IsEmpty();
}

void UWPEMainPanelWidget::LoadPanelHtml(const FString& AbsoluteHtmlPath)
{
	EnsureBrowser();
	PendingHtmlPath = AbsoluteHtmlPath.IsEmpty() ? ResolveDefaultHtmlPath() : AbsoluteHtmlPath;

	if (TryLoadHtmlIntoBrowser(PendingHtmlPath))
	{
		return;
	}

	// Slate browser often not ready on first NativeConstruct — retry for a few frames.
	if (!bLoadTickerActive)
	{
		bLoadTickerActive = true;
		LoadRetryCount = 0;
		FTSTicker::GetCoreTicker().AddTicker(
			FTickerDelegate::CreateUObject(this, &UWPEMainPanelWidget::DeferredLoadTick),
			0.05f);
	}
}

bool UWPEMainPanelWidget::DeferredLoadTick(float /*DeltaTime*/)
{
	++LoadRetryCount;
	EnsureBrowser();
	if (TryLoadHtmlIntoBrowser(PendingHtmlPath))
	{
		UE_LOG(LogWPEMainPanel, Log, TEXT("Guided panel HTML loaded on retry %d"), LoadRetryCount);
		bLoadTickerActive = false;
		return false; // stop ticker
	}

	if (LoadRetryCount >= 40)
	{
		UE_LOG(LogWPEMainPanel, Warning, TEXT("Guided panel HTML failed to load after %d retries"), LoadRetryCount);
		bLoadTickerActive = false;
		return false;
	}
	return true; // keep trying
}

TSharedRef<SWidget> UWPEMainPanelWidget::RebuildWidget()
{
	// Inject WebBrowser into the WidgetTree BEFORE TakeWidget so the docked tab
	// actually contains the browser (not an empty Blueprint spacer).
	EnsureBrowser();
	return Super::RebuildWidget();
}

void UWPEMainPanelWidget::NativeConstruct()
{
	Super::NativeConstruct();
	EnsureBrowser();
	LoadPanelHtml(ResolveDefaultHtmlPath());
}
