"""Sound output and Bluetooth speakers on this PC.

The page cannot name the PC's sound outputs itself (the browser hides their names without a microphone permission, which this app
does not want), so Windows is asked directly, through two small PowerShell scripts kept in this file and written to
%LOCALAPPDATA%/MiniDiscManager/ps when first used:
  - OUTPUTS_PS: lists the sound outputs and makes one the Windows default (what the player then plays through).
  - BT_PS: lists / searches for Bluetooth devices (Windows' own Bluetooth service), pairs one and opens its audio connection.
PcAudioMixin is mixed into himd_app.Api. Nothing here touches the recorder or the disc."""
import json
import os
import subprocess
import threading
import time

from mdm_paths import USER_DIR

PS_DIR = os.path.join(USER_DIR, 'ps')
POWERSHELL = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')

OUTPUTS_PS = r"""param([string]$Action = 'list', [string]$Id = '')
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorCom { }

[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
    [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
    [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
    [PreserveSig] int RegisterEndpointNotificationCallback(IntPtr c);
    [PreserveSig] int UnregisterEndpointNotificationCallback(IntPtr c);
}
[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection {
    [PreserveSig] int GetCount(out int n);
    [PreserveSig] int Item(int i, out IMMDevice d);
}
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o);
    [PreserveSig] int OpenPropertyStore(int access, out IPropertyStore ps);
    [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    [PreserveSig] int GetState(out int s);
}
[StructLayout(LayoutKind.Sequential)] struct PropertyKey { public Guid fmtid; public int pid; }
[StructLayout(LayoutKind.Explicit, Size = 24)] struct PropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    [PreserveSig] int GetCount(out int c);
    [PreserveSig] int GetAt(int i, out PropertyKey k);
    [PreserveSig] int GetValue(ref PropertyKey k, out PropVariant v);
    [PreserveSig] int SetValue(ref PropertyKey k, ref PropVariant v);
    [PreserveSig] int Commit();
}
[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")] class PolicyConfigCom { }
[ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPolicyConfig {
    [PreserveSig] int GetMixFormat([MarshalAs(UnmanagedType.LPWStr)] string n, IntPtr f);
    [PreserveSig] int GetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string n, int d, IntPtr f);
    [PreserveSig] int ResetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string n);
    [PreserveSig] int SetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string n, IntPtr a, IntPtr b);
    [PreserveSig] int GetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string n, int d, IntPtr a, IntPtr b);
    [PreserveSig] int SetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string n, IntPtr a);
    [PreserveSig] int GetShareMode([MarshalAs(UnmanagedType.LPWStr)] string n, IntPtr a);
    [PreserveSig] int SetShareMode([MarshalAs(UnmanagedType.LPWStr)] string n, IntPtr a);
    [PreserveSig] int GetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string n, int fx, IntPtr k, IntPtr v);
    [PreserveSig] int SetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string n, int fx, IntPtr k, IntPtr v);
    [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string n, int role);
    [PreserveSig] int SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string n, int vis);
}

public class AudioOut {
    [DllImport("ole32.dll")] static extern int PropVariantClear(ref PropVariant pv);

    static string Name(IMMDevice d) {
        IPropertyStore ps; if (d.OpenPropertyStore(0, out ps) != 0) return "";
        PropertyKey k = new PropertyKey { fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"), pid = 14 };
        PropVariant v; if (ps.GetValue(ref k, out v) != 0) return "";
        string s = v.vt == 31 ? Marshal.PtrToStringUni(v.p) : "";
        PropVariantClear(ref v); return s ?? "";
    }
    public static List<string[]> List() {
        var e = (IMMDeviceEnumerator)new MMDeviceEnumeratorCom();
        string defId = ""; IMMDevice dd;
        if (e.GetDefaultAudioEndpoint(0, 1, out dd) == 0) dd.GetId(out defId);
        IMMDeviceCollection c; e.EnumAudioEndpoints(0, 1, out c);
        int n; c.GetCount(out n);
        var res = new List<string[]>();
        for (int i = 0; i < n; i++) {
            IMMDevice d; c.Item(i, out d); string id; d.GetId(out id);
            res.Add(new string[] { id, Name(d), id == defId ? "1" : "0" });
        }
        return res;
    }
    public static int SetDefault(string id) {
        var p = (IPolicyConfig)new PolicyConfigCom();
        int r = 0;
        for (int role = 0; role < 3; role++) { int x = p.SetDefaultEndpoint(id, role); if (x != 0) r = x; }
        return r;
    }
}
'@
if ($Action -eq 'list') {
    $out = @(); foreach ($d in [AudioOut]::List()) { $out += [pscustomobject]@{ id = $d[0]; name = $d[1]; isDefault = ($d[2] -eq '1') } }
    ConvertTo-Json -InputObject @($out) -Compress
} elseif ($Action -eq 'set') {
    $rc = [AudioOut]::SetDefault($Id)
    ConvertTo-Json -InputObject ([pscustomobject]@{ rc = $rc }) -Compress
}
"""

BT_PS = r"""param([string]$Action = 'list', [string]$Id = '')
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

"""

PAIR_MESSAGES = {
    'Paired': 'Paired.',
    'AlreadyPaired': 'Already paired.',
    'NotReadyToPair': 'The speaker is not ready to pair. Put it in pairing mode (usually hold its Bluetooth button until it flashes) and try again.',
    'ConnectionRejected': 'The speaker refused the connection. Put it in pairing mode and try again.',
    'AuthenticationTimeout': 'The speaker did not answer in time. Put it in pairing mode and try again.',
    'AuthenticationFailure': 'Pairing failed (the speaker may need a pairing code, or it was already paired to another device).',
    'AuthenticationNotAllowed': 'Windows needs you to confirm the pairing: open Windows Settings, Bluetooth & devices, and pair it there once.',
    'RequiredHandlerNotRegistered': 'Windows needs you to confirm the pairing: open Windows Settings, Bluetooth & devices, and pair it there once.',
    'NoSupportedProfiles': 'Windows could not find any audio profile on that device.',
    'TooManyConnections': 'The speaker is already connected to too many devices. Disconnect it from another device first.',
    'AccessDenied': 'Windows refused (access denied). Try pairing it in Windows Settings, Bluetooth & devices.',
    'PairingCanceled': 'Pairing was cancelled.',
    'OperationAlreadyInProgress': 'Windows is already pairing something. Wait a moment and try again.',
    'RemoteDeviceHasAssociation': 'The speaker is paired with something else. Reset its pairing (see its manual) and try again.',
}


class PcAudioMixin:
    _pa_lock = threading.Lock()

    def _pa_run(self, name, text, args, timeout=60):
        """Runs one of the scripts; returns the parsed JSON it prints. Raises RuntimeError with a readable message."""
        os.makedirs(PS_DIR, exist_ok=True)
        path = os.path.join(PS_DIR, name)
        try:
            with open(path, encoding='utf-8-sig') as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            with open(path, 'w', encoding='utf-8-sig') as f:                 # a BOM so PowerShell 5 reads it as UTF-8
                f.write(text)
        try:
            r = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path] + list(args),
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Windows took too long to answer.')
        except OSError as exc:
            raise RuntimeError('PowerShell could not be started (%s).' % exc)
        out = (r.stdout or '').strip()
        if r.returncode != 0 or not out:
            raise RuntimeError((r.stderr or out or 'Windows did not answer.').strip().splitlines()[0][:200])
        try:
            return json.loads(out.splitlines()[-1])
        except ValueError:
            raise RuntimeError('Windows gave an answer the app could not read.')

    # -- the PC's sound outputs --------------------------------------------------------------------
    def pc_outputs(self):
        """The sound outputs Windows has: {outputs: [{id, name, isDefault}]} or {error}."""
        try:
            return {'outputs': self._pa_run('outputs.ps1', OUTPUTS_PS, ['-Action', 'list'], 30)}
        except RuntimeError as exc:
            return {'error': str(exc)}

    def pc_output_set(self, out_id):
        """Makes this output the Windows default, so the player (and everything else on the PC) plays through it."""
        try:
            r = self._pa_run('outputs.ps1', OUTPUTS_PS, ['-Action', 'set', '-Id', str(out_id)], 30)
            if r.get('rc'):
                return {'error': 'Windows would not switch to that output (code %s).' % r.get('rc')}
            return self.pc_outputs()
        except RuntimeError as exc:
            return {'error': str(exc)}

    # -- Bluetooth ---------------------------------------------------------------------------------
    def bt_devices(self):
        """Bluetooth devices Windows already knows (paired): {devices: [...]} or {error}. Quick."""
        try:
            return {'devices': self._pa_run('bt.ps1', BT_PS, ['-Action', 'list'], 40)}
        except RuntimeError as exc:
            return {'error': str(exc)}

    def bt_scan(self):
        """Searches for nearby Bluetooth devices that are not paired yet (about half a minute): {devices: [...]} or {error}."""
        if not self._pa_lock.acquire(blocking=False):
            return {'error': 'Windows is already searching or connecting. Wait a moment.'}
        try:
            return {'devices': self._pa_run('bt.ps1', BT_PS, ['-Action', 'scan'], 120)}
        except RuntimeError as exc:
            return {'error': str(exc)}
        finally:
            self._pa_lock.release()

    def bt_connect(self, dev_id, name, paired):
        """Pairs the device (when it is not paired yet), opens its audio connection, and waits for Windows to show it as a sound output
        (then makes it the default). Returns {ok, output, outputs} on success, {error} or {warn, outputs} otherwise."""
        if not self._pa_lock.acquire(blocking=False):
            return {'error': 'Windows is already searching or connecting. Wait a moment.'}
        try:
            before = {o['id'] for o in self.pc_outputs().get('outputs', [])}
            if not paired:
                r = self._pa_run('bt.ps1', BT_PS, ['-Action', 'pair', '-Id', dev_id], 90)
                st = r.get('status', '')
                if st not in ('Paired', 'AlreadyPaired'):
                    return {'error': PAIR_MESSAGES.get(st, 'Pairing did not work (%s).' % st)}
            self._pa_run('bt.ps1', BT_PS, ['-Action', 'connect', '-Id', dev_id], 40)
            want = (name or '').strip().lower()
            for _ in range(10):                                            # up to about 15 seconds for the audio output to appear
                time.sleep(1.5)
                outs = self.pc_outputs().get('outputs', [])
                hit = next((o for o in outs if o['id'] not in before or (want and want in o['name'].lower())), None)
                if hit:
                    res = self.pc_output_set(hit['id'])
                    return {'ok': True, 'output': hit['name'], 'outputs': res.get('outputs', outs)}
            return {'warn': 'Paired, but Windows has not opened the speaker as a sound output yet. Switch the speaker off and on, or press Connect for it in Windows Settings, Bluetooth & devices, then look in the output list again.',
                    'outputs': self.pc_outputs().get('outputs', [])}
        except RuntimeError as exc:
            return {'error': str(exc)}
        finally:
            self._pa_lock.release()