#!/bin/bash
cd "$(dirname "$0")"
# Wipe stale window positions (safe; regenerates on launch)
rm -rf "./Saved/Config/MacEditor"
exec "/Users/Shared/Epic Games/UE_5.8/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" \
  "$(pwd)/WorldPromptEngine.uproject" -log -stdout
