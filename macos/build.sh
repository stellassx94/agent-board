#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
app_path=${AGENT_BOARD_APP_PATH:-"$repo_dir/build/Agent Board.app"}
contents="$app_path/Contents"
version=$(sed 's/^v//' "$repo_dir/VERSION")
cache_dir=${AGENT_BOARD_BUILD_CACHE:-"${TMPDIR:-/tmp}/agent-board-build-cache"}

mkdir -p "$contents/MacOS" "$contents/Resources/Backend" "$cache_dir/swift" "$cache_dir/clang"
cp "$repo_dir/agent_board.py" "$repo_dir/agent_board_classify.py" \
  "$repo_dir/agent_board_workstreams.py" "$repo_dir/VERSION" "$contents/Resources/Backend/"
cp "$repo_dir/macos/AgentBoardIcon.png" "$contents/Resources/Backend/"
rm -rf "$contents/Resources/BackendExecutable"
if [ "${AGENT_BOARD_BUNDLE_RUNTIME:-1}" = "1" ]; then
  command -v uvx >/dev/null || { echo "uvx is required to bundle Python" >&2; exit 1; }
  pyi_dist="$cache_dir/pyinstaller-dist"
  uvx --python 3.13.13 --from pyinstaller==6.22.3 pyinstaller --noconfirm --onedir \
    --name agent-board-service --distpath "$pyi_dist" \
    --workpath "$cache_dir/pyinstaller-work" --specpath "$cache_dir" \
    --add-data "$repo_dir/VERSION:." \
    --add-data "$repo_dir/macos/AgentBoardIcon.png:." "$repo_dir/agent_board.py"
  ditto "$pyi_dist/agent-board-service" "$contents/Resources/BackendExecutable"
fi
xcrun swiftc -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$cache_dir/swift" \
  -Xcc "-fmodules-cache-path=$cache_dir/clang" \
  "$repo_dir/macos/AgentBoardApp.swift" -framework AppKit -framework WebKit \
  -framework ServiceManagement -o "$contents/MacOS/AgentBoard"
iconset="$cache_dir/AgentBoard.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  doubled=$((size * 2))
  sips -s format png -z "$size" "$size" "$repo_dir/macos/AgentBoardIcon.png" \
    --out "$iconset/icon_${size}x${size}.png" >/dev/null
  sips -s format png -z "$doubled" "$doubled" "$repo_dir/macos/AgentBoardIcon.png" \
    --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$contents/Resources/AgentBoard.icns"
cat > "$contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>AgentBoard</string>
<key>CFBundleIdentifier</key><string>com.stella.agentboard.trial</string>
<key>CFBundleName</key><string>Agent Board</string>
<key>CFBundleDisplayName</key><string>Agent Board</string>
<key>CFBundleIconFile</key><string>AgentBoard.icns</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>$version</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force --deep --sign - "$app_path"
plutil -lint "$contents/Info.plist"
printf 'Built %s\n' "$app_path"
