param([string]$Action = 'list', [string]$Id = '')
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Devices.Enumeration.DeviceInformation, Windows.Devices.Enumeration, ContentType = WindowsRuntime]
[void][Windows.Devices.Enumeration.DeviceInformationCollection, Windows.Devices.Enumeration, ContentType = WindowsRuntime]
[void][Windows.Devices.Enumeration.DevicePairingResult, Windows.Devices.Enumeration, ContentType = WindowsRuntime]
[void][Windows.Devices.Bluetooth.BluetoothDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); [void]$t.Wait(-1); $t.Result }
$props = [string[]]@('System.Devices.Aep.IsConnected', 'System.Devices.Aep.SignalStrength')
$minor = @{ 'AudioVideoWearableHeadset' = 'Headset'; 'AudioVideoHandsFree' = 'Hands-free'; 'AudioVideoLoudspeaker' = 'Speaker'; 'AudioVideoHeadphones' = 'Headphones';
            'AudioVideoPortableAudio' = 'Portable audio'; 'AudioVideoCarAudio' = 'Car audio'; 'AudioVideoHifiAudioDevice' = 'Hi-fi audio'; 'AudioVideoVideoDisplayAndLoudspeaker' = 'TV / display' }

function Describe($di, $isPaired) {
    $kind = ''; $audio = $false; $addr = ''
    try {
        $bd = Await ([Windows.Devices.Bluetooth.BluetoothDevice]::FromIdAsync($di.Id)) ([Windows.Devices.Bluetooth.BluetoothDevice])
        if ($bd) {
            $addr = [string]$bd.BluetoothAddress
            if ($bd.ClassOfDevice.MajorClass.ToString() -eq 'AudioVideo') { $audio = $true; $m = $bd.ClassOfDevice.MinorClass.ToString(); $kind = if ($minor.ContainsKey($m)) { $minor[$m] } else { 'Audio device' } }
            $bd.Dispose()
        }
    } catch { }
    $conn = $false; try { $conn = [bool]$di.Properties['System.Devices.Aep.IsConnected'] } catch { }
    $rssi = $null; try { $v = $di.Properties['System.Devices.Aep.SignalStrength']; if ($v -is [int] -or $v -is [int16]) { $rssi = [int]$v } } catch { }
    [pscustomobject]@{ id = $di.Id; name = [string]$di.Name; paired = [bool]$isPaired; connected = $conn; rssi = $rssi; audio = $audio; kind = $kind; address = $addr }
}

if ($Action -eq 'list' -or $Action -eq 'scan') {
    $paired = ($Action -eq 'list')                       # list = devices Windows already knows; scan = a fresh search for new ones (takes about ten seconds)
    $sel = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($paired)
    $all = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($sel, $props)) ([Windows.Devices.Enumeration.DeviceInformationCollection])
    $out = @(); foreach ($di in $all) { if ($di.Name) { $out += Describe $di $paired } }
    ConvertTo-Json -InputObject @($out) -Compress -Depth 4
}
elseif ($Action -eq 'pair') {
    $di = Await ([Windows.Devices.Enumeration.DeviceInformation]::CreateFromIdAsync($Id)) ([Windows.Devices.Enumeration.DeviceInformation])
    if ($di.Pairing.IsPaired) { ConvertTo-Json -InputObject ([pscustomobject]@{ status = 'AlreadyPaired' }) -Compress; exit 0 }
    $r = Await ($di.Pairing.PairAsync()) ([Windows.Devices.Enumeration.DevicePairingResult])
    ConvertTo-Json -InputObject ([pscustomobject]@{ status = $r.Status.ToString() }) -Compress
}
elseif ($Action -eq 'connect') {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BtConnect {
    [StructLayout(LayoutKind.Sequential)] struct ST { public ushort a, b, c, d, e, f, g, h; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct INFO { public int dwSize; public ulong Address; public uint Cod; public int fConnected; public int fRemembered; public int fAuthenticated; public ST seen; public ST used;
                  [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 248)] public string szName; }
    [DllImport("bthprops.cpl")] static extern uint BluetoothGetDeviceInfo(IntPtr h, ref INFO i);
    [DllImport("bthprops.cpl")] static extern uint BluetoothSetServiceState(IntPtr h, ref INFO i, ref Guid g, uint flags);
    public static string Go(ulong address) {
        INFO i = new INFO(); i.dwSize = Marshal.SizeOf(typeof(INFO)); i.Address = address;
        uint r = BluetoothGetDeviceInfo(IntPtr.Zero, ref i);
        if (r != 0) return "info:" + r;
        Guid a2dp = new Guid("0000110B-0000-1000-8000-00805F9B34FB");
        BluetoothSetServiceState(IntPtr.Zero, ref i, ref a2dp, 0);          // off, then on again: Windows opens the audio connection
        System.Threading.Thread.Sleep(600);
        r = BluetoothSetServiceState(IntPtr.Zero, ref i, ref a2dp, 1);
        return "state:" + r;
    }
}
'@
    $bd = Await ([Windows.Devices.Bluetooth.BluetoothDevice]::FromIdAsync($Id)) ([Windows.Devices.Bluetooth.BluetoothDevice])
    if (-not $bd) { ConvertTo-Json -InputObject ([pscustomobject]@{ result = 'nodevice' }) -Compress; exit 0 }
    $res = [BtConnect]::Go([uint64]$bd.BluetoothAddress); $bd.Dispose()
    ConvertTo-Json -InputObject ([pscustomobject]@{ result = $res }) -Compress
}

