param([string]$Action = 'list', [string]$Id = '')
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
