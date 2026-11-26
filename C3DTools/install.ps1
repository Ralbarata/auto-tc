# Pasang hasil build ke bundle autoload Civil 3D.
# Bila Civil 3D sedang terbuka, DLL lama terkunci: DLL itu diganti nama dulu (boleh walau terkunci),
# lalu DLL baru ditaruh di tempatnya. Versi baru terpakai saat Civil 3D dibuka lagi.
param([string]$Dll = "$PSScriptRoot\obj\Release\C3DTools.dll")

$bundle = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins\C3DTools.bundle"
$contents = Join-Path $bundle "Contents"
New-Item -ItemType Directory -Force $contents | Out-Null
Copy-Item "$PSScriptRoot\PackageContents.xml" $bundle -Force

# buang sisa versi lama yang sudah tidak terkunci
Get-ChildItem $contents -Filter "*.old" -ErrorAction SilentlyContinue | ForEach-Object {
    try { [IO.File]::Delete($_.FullName) } catch { }
}

$target = Join-Path $contents "C3DTools.dll"
try {
    Copy-Item $Dll $target -Force -ErrorAction Stop
    "Bundle diperbarui."
} catch {
    $old = Join-Path $contents ("C3DTools." + (Get-Date -Format "HHmmss") + ".old")
    [IO.File]::Move($target, $old)
    Copy-Item $Dll $target -Force
    "Bundle diperbarui (Civil 3D sedang terbuka: versi baru aktif setelah Civil 3D dibuka ulang)."
}
