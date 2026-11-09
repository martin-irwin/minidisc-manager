<#
Burns an ordinary audio CD with Windows' own burner (IMAPI2, track-at-once: 2-second gaps, no CD-Text). This is the route that was proven on a
real CD-R; the raw gapless / CD-Text writer (cdburn_raw.ps1) is experimental and is NOT used here.
  -List    the CD / DVD / BD writers and the disc in each; writes nothing
  -Check   the disc in -Drive: type, blank or not, free minutes, can it be written as an audio CD / erased; writes nothing
  -Erase   quick-erases the rewritable disc in -Drive (never touches a disc that is not rewritable)
  -Burn    burns the audio files listed in -ListFile (a JSON array of paths, in order) to the BLANK CD in -Drive
  -Data    puts the files of -Folder on a data disc (CD, DVD, Blu-ray: burnt to a blank disc; DVD-RAM: copied into a folder called -Label)
Output lines: "DRIVE ...", "DISC ...", "INFO ...", "TRACK n of m", "ERROR ..." and "DONE". Exit code 0 on success.
#>
param(
    [string]$Drive,
    [string]$ListFile,
    [string]$Ffmpeg,
    [switch]$List,
    [switch]$Check,
    [switch]$Erase,
    [switch]$Burn,
    [switch]$Data,
    [string]$Folder,
    [string]$Label
)
$ErrorActionPreference = 'Stop'
function Fail($m) { Write-Output "ERROR $m"; exit 1 }
$types = @{ 0 = 'unknown'; 1 = 'CD-ROM'; 2 = 'CD-R'; 3 = 'CD-RW'; 4 = 'DVD-ROM'; 5 = 'DVD-RAM'; 6 = 'DVD+R'; 7 = 'DVD+RW'; 8 = 'DVD+R DL'; 9 = 'DVD-R'
           10 = 'DVD-RW'; 11 = 'DVD-R DL'; 12 = 'random-access disc'; 13 = 'DVD+RW DL'; 14 = 'HD DVD-ROM'; 15 = 'HD DVD-R'; 16 = 'HD DVD-RAM'; 17 = 'BD-ROM'; 18 = 'BD-R'; 19 = 'BD-RE' }
$rewritable = 3, 5, 7, 10, 13, 19

try {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
public static class Shl {
    [DllImport("shlwapi.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    public static extern void SHCreateStreamOnFileEx(string path, uint mode, uint attrs, bool create, IntPtr templ, out IStream stream);
}
'@ -ErrorAction SilentlyContinue

    function Get-Recorders {
        $master = New-Object -ComObject IMAPI2.MsftDiscMaster2
        foreach ($id in $master) {
            $r = New-Object -ComObject IMAPI2.MsftDiscRecorder2; $r.InitializeDiscRecorder($id)
            $r
        }
    }
    function Disc-Info($rec) {
        $dat = New-Object -ComObject IMAPI2.MsftDiscFormat2Data
        try { $dat.Recorder = $rec } catch { return $null }
        try { $media = [int]$dat.CurrentPhysicalMediaType } catch { return $null }
        if ($media -eq 0) { return $null }
        $blank = $false
        try { $blank = [bool]$dat.MediaHeuristicallyBlank } catch { $blank = $false }
        $free = 0
        try { $free = [double]$dat.FreeSectorsOnMedia } catch { $free = 0 }
        $bytes = [int64]($free * 2048)
        $mounted = $false
        if ($media -eq 5 -or $media -eq 19) {       # a DVD-RAM, or a BD-RE that already has a file system, is used like a drive: free space is the volume's
            try {
                $vi = [IO.DriveInfo]$rec.VolumePathNames[0]
                if ($media -eq 5 -or ($vi.IsReady -and $vi.DriveFormat)) { $bytes = $vi.AvailableFreeSpace; $mounted = $true }
            } catch { if ($media -eq 5) { $bytes = 0 } }
        }
        [pscustomobject]@{ Media = $media; Name = $types[$media]; Blank = $blank; FreeMinutes = [math]::Round($free / 4500, 1); Rewritable = ($rewritable -contains $media); FreeBytes = $bytes; Mounted = $mounted }
    }
    function Find-Recorder($letter) {
        $letter = $letter.TrimEnd('\').ToUpper(); if ($letter.Length -eq 1) { $letter += ':' }
        foreach ($r in Get-Recorders) { if ($r.VolumePathNames -contains "$letter\") { return $r } }
        $null
    }

    if ($List) {
        foreach ($r in Get-Recorders) {
            $letters = ($r.VolumePathNames | ForEach-Object { $_.TrimEnd('\') }) -join ','
            Write-Output "DRIVE $letters|$($r.VendorId.Trim()) $($r.ProductId.Trim())"
            $d = Disc-Info $r
            if ($d) { Write-Output "DISC $letters|$($d.Name)|$($d.Blank)|$($d.FreeMinutes)|$($d.Rewritable)|$($d.FreeBytes)|$($d.Mounted)" } else { Write-Output "NODISC $letters" }
        }
        Write-Output 'DONE'; exit 0
    }

    if (-not $Drive) { Fail 'No drive was given.' }
    $rec = Find-Recorder $Drive
    if (-not $rec) { Fail "No disc writer was found for $Drive." }
    $d = Disc-Info $rec
    if (-not $d) { Fail 'There is no disc in the drive (or it cannot be read).' }
    Write-Output "INFO drive $($rec.VendorId.Trim()) $($rec.ProductId.Trim())"
    Write-Output "INFO disc $($d.Name), blank $($d.Blank), $($d.FreeMinutes) minutes free, rewritable $($d.Rewritable)"
    if ($Check) { Write-Output 'DONE'; exit 0 }

    if ($Erase) {
        if ($d.Media -eq 5) { Fail 'A DVD-RAM is not erased here: delete its files in File Explorer, or format it in Windows.' }
        if (-not $d.Rewritable) { Fail "This disc ($($d.Name)) cannot be erased: only rewritable discs (CD-RW, DVD-RW, DVD+RW, BD-RE) can." }
        $er = New-Object -ComObject IMAPI2.MsftDiscFormat2Erase
        $er.Recorder = $rec; $er.ClientName = 'MiniDisc Manager'; $er.FullErase = $false
        if (-not $er.IsCurrentMediaSupported($rec)) { Fail 'The drive cannot erase this disc.' }
        Write-Output 'INFO erasing (quick erase)'
        $er.EraseMedia()
        Write-Output 'DONE'; exit 0
    }

    if ($Burn) {
        if (-not $ListFile -or -not (Test-Path -LiteralPath $ListFile)) { Fail 'The list of tracks is missing.' }
        if (-not $Ffmpeg -or -not (Test-Path -LiteralPath $Ffmpeg)) { Fail 'The audio decoder is missing.' }
        $files = @(Get-Content -LiteralPath $ListFile -Raw -Encoding UTF8 | ConvertFrom-Json)
        if (-not $files.Count) { Fail 'There are no tracks to burn.' }
        if ($d.Media -notin 2, 3) { Fail "An audio CD needs a CD-R or CD-RW; this disc is a $($d.Name)." }
        if (-not $d.Blank) { Fail 'The disc is not blank. Erase it first (a CD-R can only be written once).' }
        $fmt = New-Object -ComObject IMAPI2.MsftDiscFormat2TrackAtOnce
        $fmt.Recorder = $rec; $fmt.ClientName = 'MiniDisc Manager'
        if (-not $fmt.IsCurrentMediaSupported($rec)) { Fail 'The disc in the drive cannot be written as an audio CD.' }

        $tmp = Join-Path $env:TEMP ('mdm-cdburn-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory $tmp | Out-Null
        try {
            $pcm = @(); $sectors = 0
            foreach ($f in $files) {
                $out = Join-Path $tmp ('t{0:00}.pcm' -f ($pcm.Count + 1))
                & $Ffmpeg -hide_banner -loglevel error -y -i $f -vn -f s16le -ar 44100 -ac 2 $out
                if ($LASTEXITCODE) { Fail "Could not decode $(Split-Path $f -Leaf)." }
                $len = (Get-Item $out).Length
                $pad = (2352 - ($len % 2352)) % 2352
                if ($pad) { $fs = [IO.File]::Open($out, 'Append'); $fs.Write([byte[]]::new($pad), 0, $pad); $fs.Close() }
                $sectors += (Get-Item $out).Length / 2352
                $pcm += $out
            }
            $minutes = $sectors / 4500
            Write-Output "INFO $($pcm.Count) tracks, $([math]::Round($minutes, 1)) minutes of audio"
            if ($minutes -gt $d.FreeMinutes) { Fail "The tracks ($([math]::Round($minutes, 1)) minutes) do not fit on the disc ($($d.FreeMinutes) minutes free)." }

            Write-Output 'INFO writing the disc'
            $fmt.PrepareMedia()
            try {
                for ($i = 0; $i -lt $pcm.Count; $i++) {
                    $stream = $null
                    [Shl]::SHCreateStreamOnFileEx($pcm[$i], 0, 0x80, $false, [IntPtr]::Zero, [ref]$stream)
                    Write-Output "TRACK $($i + 1) of $($pcm.Count)"
                    $fmt.AddAudioTrack($stream)
                }
            }
            finally {
                $fmt.ReleaseMedia()          # finishes and closes the disc so any CD player can read it
            }
        }
        finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
        Write-Output 'DONE'; exit 0
    }
    if ($Data) {
        # Files on a data disc. DVD-RAM behaves like a drive: the files are copied onto it (it must already be formatted). Every other
        # type is burnt as a finished disc image (UDF; plus Joliet on a CD) and only onto a BLANK disc, which is closed afterwards.
        if (-not $Folder -or -not (Test-Path -LiteralPath $Folder -PathType Container)) { Fail 'The folder with the files is missing.' }
        $bytes = (Get-ChildItem -LiteralPath $Folder -Recurse -File | Measure-Object Length -Sum).Sum
        if ($d.Media -eq 5 -or $d.Mounted) {
            $root = "$($Drive.TrimEnd('\').ToUpper().Substring(0, 1)):\"
            if (-not (Test-Path -LiteralPath $root)) { Fail 'This DVD-RAM is not formatted. Format it in Windows (File Explorer: right-click the drive, Format) and try again.' }
            $free = ([IO.DriveInfo]$root).AvailableFreeSpace
            if ($bytes -gt $free) { Fail "The files ($([math]::Round($bytes / 1MB)) MB) do not fit on the disc ($([math]::Round($free / 1MB)) MB free)." }
            $dest = Join-Path $root $Label
            if (Test-Path -LiteralPath $dest) { Fail "The disc already has a folder called $Label. Nothing was copied." }
            Write-Output 'INFO copying the files'
            Copy-Item -LiteralPath $Folder -Destination $dest -Recurse
            Write-Output 'DONE'; exit 0
        }
        if ($d.Media -in 1, 4, 14, 17) { Fail "This disc ($($d.Name)) is read-only." }
        if (-not $d.Blank) { Fail 'The disc is not blank. Erase it first if it is rewritable (a -R disc can only be written once).' }
        if ($bytes -gt $d.FreeBytes) { Fail "The files ($([math]::Round($bytes / 1MB)) MB) do not fit on the disc ($([math]::Round($d.FreeBytes / 1MB)) MB free)." }
        $fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
        $fsi.ChooseImageDefaultsForMediaType($d.Media)
        $fsi.FileSystemsToCreate = $(if ($d.Media -in 2, 3) { 7 } else { 4 })
        $fsi.VolumeName = $Label
        $fsi.Root.AddTree($Folder, $false)
        $res = $fsi.CreateResultImage()
        $need = [int64]$res.TotalBlocks * $res.BlockSize
        if ($need -gt $d.FreeBytes) { Fail "The disc image ($([math]::Round($need / 1MB)) MB) does not fit on the disc ($([math]::Round($d.FreeBytes / 1MB)) MB free)." }
        $dat = New-Object -ComObject IMAPI2.MsftDiscFormat2Data
        $dat.Recorder = $rec; $dat.ClientName = 'MiniDisc Manager'; $dat.ForceMediaToBeClosed = $true
        if (-not $dat.IsCurrentMediaSupported($rec)) { Fail 'The disc in the drive cannot be written as a data disc.' }
        Write-Output "INFO writing $([math]::Round($need / 1MB)) MB"
        $dat.Write($res.ImageStream)
        Write-Output 'DONE'; exit 0
    }
    Fail 'Nothing to do.'
} catch {
    Fail $_.Exception.Message
}
