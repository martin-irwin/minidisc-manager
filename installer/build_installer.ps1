# Builds the MiniDisc Manager downloads: PyInstaller makes the program folder, then Inno Setup wraps it into a Setup.exe
# and the same folder is zipped as a portable version.
# Needs: Python 3.12 with the app's packages + PyInstaller, and Inno Setup 6 (ISCC.exe).
# Usage:  powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1 [-Version 0.9.1]
# The version defaults to APP_VERSION in himd_app.py (the number the window shows).
param([string]$Version = '')
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot                                    # ...\HiMD-Manager\installer
$app  = Split-Path $here -Parent                         # ...\HiMD-Manager
$work = Join-Path $env:TEMP 'MiniDiscManager-build'      # scratch folders (not in OneDrive)
$out  = Join-Path (Split-Path $app -Parent) 'HiMD-Manager-Installer'

if (-not $Version) {
    $m = [regex]::Match((Get-Content (Join-Path $app 'himd_app.py') -Raw), "APP_VERSION\s*=\s*'([^']+)'")
    if (-not $m.Success) { throw 'APP_VERSION was not found in himd_app.py' }
    $Version = $m.Groups[1].Value
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "The version must look like 1.2.3 (got '$Version')" }
Write-Host "Building MiniDisc Manager $Version"

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 (ISCC.exe) was not found.' }

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, $out | Out-Null
Set-Location $app                                        # PyInstaller refuses to run from C:\Windows\System32

# the version shown in the exe's Properties > Details
$p = $Version.Split('.')
$vi = "VSVersionInfo(ffi=FixedFileInfo(filevers=($($p[0]),$($p[1]),$($p[2]),0), prodvers=($($p[0]),$($p[1]),$($p[2]),0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)), " +
      "kids=[StringFileInfo([StringTable('040904B0', [StringStruct('FileDescription','MiniDisc Manager'), StringStruct('FileVersion','$Version'), " +
      "StringStruct('InternalName','MiniDisc Manager'), StringStruct('LegalCopyright','Copyright (c) 2026 Vinny Powell'), StringStruct('OriginalFilename','MiniDisc Manager.exe'), StringStruct('ProductName','MiniDisc Manager'), " +
      "StringStruct('ProductVersion','$Version')])]), VarFileInfo([VarStruct('Translation',[1033,1200])])])"
Set-Content "$work\version_info.txt" $vi -Encoding utf8

Write-Host '1/3  PyInstaller: building the program folder...'
& python -m PyInstaller --noconfirm --clean --onedir --noconsole --name 'MiniDisc Manager' --icon "$here\icon.ico" --version-file "$work\version_info.txt" `
    --distpath "$work\dist" --workpath "$work\build" --specpath "$work" `
    --add-data "$app\runtime;runtime" --add-data "$app\helper;helper" --add-data "$app\ui;ui" `
    --add-data "$app\DRIVER-SETUP.html;." --add-data "$app\LICENSE.txt;." --add-data "$app\THIRD-PARTY-NOTICES.txt;." `
    --add-data "$app\README.txt;." --add-data "$app\LICENSES;LICENSES" `
    --collect-all webview --hidden-import clr_loader --exclude-module tkinter `
    "$app\himd_app.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

Write-Host '2/3  Inno Setup: building Setup.exe...'
& $iscc "/DSrcDist=$work\dist\MiniDisc Manager" "/DBuildDir=$here" "/DAppVersion=$Version" "/O$out" "$here\MiniDisc-Manager.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }

Write-Host '3/3  Portable zip...'
$stage = Join-Path $work "zip\MiniDisc Manager $Version"
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item "$work\dist\MiniDisc Manager\*" $stage -Recurse -Force
foreach ($f in 'DRIVER-SETUP.html', 'LICENSE.txt', 'THIRD-PARTY-NOTICES.txt', 'README.txt') { Copy-Item (Join-Path $app $f) $stage -Force }
Copy-Item (Join-Path $app 'LICENSES') (Join-Path $stage 'LICENSES') -Recurse -Force
Copy-Item "$here\portable-readme.txt" (Join-Path $stage 'READ ME FIRST.txt') -Force
$zip = Join-Path $out "MiniDisc-Manager-$Version-portable.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
# Entries are written one by one with forward slashes: the zip then opens correctly in Explorer, 7-Zip, tar and on other systems
# (ZipFile.CreateFromDirectory in Windows PowerShell 5.1 stores backslashes).
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = Join-Path $work 'zip'
$fs = [System.IO.File]::Create($zip)
$za = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem $root -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($za, $_.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $za.Dispose(); $fs.Dispose() }

foreach ($f in @((Join-Path $out "MiniDisc-Manager-Setup-$Version.exe"), $zip)) {
    $i = Get-Item $f
    Write-Host ('Done: {0}  ({1:N1} MB)' -f $i.FullName, ($i.Length / 1MB))
    Write-Host ('      SHA-256: ' + (Get-FileHash $f -Algorithm SHA256).Hash)
}
