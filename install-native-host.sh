#!/usr/bin/env bash
# Register the UEU dean extension native messaging host with Chrome.
#
# Run this once after loading the extension in Chrome unpacked.
# Find your extension ID at chrome://extensions → "ID" under the extension.
#
# Usage: ./install-native-host.sh <CHROME_EXTENSION_ID>

set -euo pipefail

EXTENSION_ID="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST_SRC="$SCRIPT_DIR/com.ueu.dean.json"
MANIFEST_DEST="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.ueu.dean.json"
HOST_SCRIPT="$SCRIPT_DIR/rhizome_alkahest/native_host.py"

if [[ -z "$EXTENSION_ID" ]]; then
  echo "Usage: $0 <CHROME_EXTENSION_ID>"
  echo ""
  echo "Find your extension ID at chrome://extensions"
  exit 1
fi

# Make the host script executable
chmod +x "$HOST_SCRIPT"

# Ensure the host script has a proper shebang line and is invokable
if ! head -1 "$HOST_SCRIPT" | grep -q "python"; then
  echo "Warning: $HOST_SCRIPT may not be directly executable — check shebang"
fi

# Write manifest with the real extension ID
mkdir -p "$(dirname "$MANIFEST_DEST")"
sed "s/CHROME_EXTENSION_ID/$EXTENSION_ID/" "$MANIFEST_SRC" > "$MANIFEST_DEST"

echo "Installed: $MANIFEST_DEST"
echo "Extension: chrome-extension://$EXTENSION_ID/"
echo ""
echo "Reload the extension in Chrome (chrome://extensions → reload button)"
echo "Then test with: edge about ueu-dean-extension"
