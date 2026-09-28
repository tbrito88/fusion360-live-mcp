#!/bin/bash
# Install/reinstall the Fusion360LiveMCP add-in via symlink (for development)
# Usage: ./scripts/install-addon.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
ADDON_SRC="$REPO_DIR/addon"

# Determine Fusion 360 AddIns folder
if [[ "$OSTYPE" == "darwin"* ]]; then
    ADDINS_DIR="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
    ADDINS_DIR="$APPDATA/Autodesk/Autodesk Fusion 360/API/AddIns"
else
    echo "Unsupported OS: $OSTYPE"
    exit 1
fi

TARGET="$ADDINS_DIR/Fusion360LiveMCP"

echo "Installing Fusion360LiveMCP add-in..."
echo "  Source: $ADDON_SRC"
echo "  Target: $TARGET"

# Remove existing installation
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "  Removing existing installation..."
    rm -rf "$TARGET"
fi

# Link (not copy) so changes to addon/ reflect immediately.
if [[ "$OSTYPE" == "darwin"* ]]; then
    ln -s "$ADDON_SRC" "$TARGET"
else
    # Git Bash's ln -s silently copies the folder; a junction needs no admin rights.
    powershell.exe -NoProfile -Command         "New-Item -ItemType Junction -Path '$(cygpath -w "$TARGET")' -Target '$(cygpath -w "$ADDON_SRC")' | Out-Null"
fi

echo "  ✓ Installed as a link to $ADDON_SRC"
echo ""
echo "Next steps:"
echo "  1. Open Fusion 360"
echo "  2. Press Shift+S to open Scripts and Add-Ins"
echo "  3. Find 'Fusion360LiveMCP' in the Add-Ins tab"
echo "  4. Click 'Run' to start the add-in"
echo ""
echo "The add-in will listen on localhost:9876"
