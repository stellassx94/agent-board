#!/bin/sh
# Package the Agent Board Sidebar extension as a .vsix without npm or vsce.
set -eu
src=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$src")
version=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$src/package.json")
out="$repo/build/agent-board-sidebar-$version.vsix"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

mkdir -p "$stage/extension/media" "$repo/build"
cp "$src/extension.js" "$src/package.json" "$src/readme.md" "$stage/extension/"
cp "$src/media/icon.svg" "$src/media/logo.png" "$stage/extension/media/"

cat > "$stage/[Content_Types].xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension=".json" ContentType="application/json"/><Default Extension=".js" ContentType="application/javascript"/><Default Extension=".md" ContentType="text/markdown"/><Default Extension=".png" ContentType="image/png"/><Default Extension=".svg" ContentType="image/svg+xml"/><Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>
XML

cat > "$stage/extension.vsixmanifest" <<XML
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="agent-board-sidebar" Version="$version" Publisher="stella-simsx" />
    <DisplayName>Agent Board Sidebar</DisplayName>
    <Description xml:space="preserve">Compact sidebar list of your Claude Code and Codex sessions, fed by the local Agent Board.</Description>
    <Categories>Other</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.85.0" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />
      <Property Id="Microsoft.VisualStudio.Code.ExecutesCode" Value="true" />
    </Properties>
    <Icon>extension/media/logo.png</Icon>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/readme.md" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/media/logo.png" Addressable="true" />
  </Assets>
</PackageManifest>
XML

rm -f "$out"
(cd "$stage" && zip -qrX "$out" "[Content_Types].xml" extension.vsixmanifest extension)
echo "Built $out"
