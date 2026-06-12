#!/bin/bash
# Build "Zotero-RAG.app" — a double-clickable macOS launcher that runs the GUI
# using the project's virtual environment. No external packaging tools needed.
#
# The bundle is a thin launcher: it does not copy Python or the model, it simply
# invokes the venv interpreter against this project. Re-run after moving the
# project folder.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Zotero-RAG"
APP="${PROJECT_DIR}/${APP_NAME}.app"
VENV_PY="${PROJECT_DIR}/venv/bin/python"
ICON="${PROJECT_DIR}/assets/icon.icns"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "error: venv not found at ${VENV_PY}. Run: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Building ${APP} ..."
rm -rf "${APP}"
mkdir -p "${APP}/Contents/MacOS" "${APP}/Contents/Resources"

# Info.plist
cat > "${APP}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>com.zoterorag.app</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
</dict>
</plist>
PLIST

# Launcher executable
cat > "${APP}/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
cd "${PROJECT_DIR}"
exec "${VENV_PY}" "${PROJECT_DIR}/app.py" "\$@"
LAUNCH
chmod +x "${APP}/Contents/MacOS/launcher"

# Icon
if [[ -f "${ICON}" ]]; then
  cp "${ICON}" "${APP}/Contents/Resources/icon.icns"
fi

# Refresh Finder's icon cache for this bundle.
touch "${APP}"

echo "Done: ${APP}"
echo "Double-click it in Finder, or run: open '${APP}'"
