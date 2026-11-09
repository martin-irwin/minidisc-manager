// appaudio.exe - records the sound of ONE program (and the programs it started) on Windows 10 2004+ / Windows 11.
// Uses the "process loopback" part of WASAPI, so nothing else the PC plays is mixed in.
//
//   appaudio.exe <processId>            raw 16-bit stereo 44100 Hz PCM to standard output until standard input closes
//   appaudio.exe --probe                 prints OK and exits (checks the exe runs)
//
// Standard output carries a continuous timeline: when the program is silent the exe writes zeros, so
// "bytes received / 176400" is always the real elapsed seconds.
// Build: C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /optimize /target:exe /out:appaudio.exe appaudio.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

static class AppAudio
{
    const int Rate = 44100, Channels = 2, Bits = 16, FrameBytes = Channels * Bits / 8;

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    struct WaveFormatEx { public ushort wFormatTag, nChannels; public uint nSamplesPerSec, nAvgBytesPerSec; public ushort nBlockAlign, wBitsPerSample, cbSize; }

    [StructLayout(LayoutKind.Sequential)]
    struct ActivationParams { public int ActivationType; public uint TargetProcessId; public int ProcessLoopbackMode; }

    [StructLayout(LayoutKind.Sequential)]
    struct PropVariantBlob { public ushort vt, r1, r2, r3; public uint cbSize; public IntPtr pBlobData; }

    [ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioClient
    {
        [PreserveSig] int Initialize(int shareMode, uint flags, long bufferDuration, long periodicity, IntPtr format, IntPtr sessionGuid);
        [PreserveSig] int GetBufferSize(out uint frames);
        [PreserveSig] int GetStreamLatency(out long latency);
        [PreserveSig] int GetCurrentPadding(out uint frames);
        [PreserveSig] int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closest);
        [PreserveSig] int GetMixFormat(out IntPtr format);
        [PreserveSig] int GetDevicePeriod(out long defaultPeriod, out long minPeriod);
        [PreserveSig] int Start();
        [PreserveSig] int Stop();
        [PreserveSig] int Reset();
        [PreserveSig] int SetEventHandle(IntPtr eventHandle);
        [PreserveSig] int GetService([In] ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object service);
    }

    [ComImport, Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioCaptureClient
    {
        [PreserveSig] int GetBuffer(out IntPtr data, out uint frames, out uint flags, out ulong devicePosition, out ulong qpcPosition);
        [PreserveSig] int ReleaseBuffer(uint frames);
        [PreserveSig] int GetNextPacketSize(out uint frames);
    }

    [ComImport, Guid("72A22D78-CDE4-431D-B8CC-843A71199B6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceAsyncOperation
    {
        [PreserveSig] int GetActivateResult(out int activateResult, [MarshalAs(UnmanagedType.IUnknown)] out object activatedInterface);
    }

    [ComImport, Guid("41D949AB-9862-444A-80F6-C261334DA5EB"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceCompletionHandler
    {
        [PreserveSig] int ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation);
    }

    [ComImport, Guid("94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAgileObject { }

    [ClassInterface(ClassInterfaceType.None)]
    class Handler : IActivateAudioInterfaceCompletionHandler, IAgileObject
    {
        public ManualResetEvent Done = new ManualResetEvent(false);
        public IActivateAudioInterfaceAsyncOperation Op;
        public int ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation) { Op = operation; Done.Set(); return 0; }
    }

    [DllImport("Mmdevapi.dll", ExactSpelling = true, PreserveSig = false)]
    static extern void ActivateAudioInterfaceAsync([MarshalAs(UnmanagedType.LPWStr)] string path, [In] ref Guid riid, IntPtr activationParams,
        IActivateAudioInterfaceCompletionHandler handler, out IActivateAudioInterfaceAsyncOperation op);

    [DllImport("kernel32.dll")] static extern IntPtr CreateEvent(IntPtr attrs, bool manual, bool initial, string name);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h, uint ms);

    static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--probe") { Console.WriteLine("OK"); return 0; }
        uint pid;
        if (args.Length != 1 || !uint.TryParse(args[0], out pid)) { Console.Error.WriteLine("usage: appaudio <processId>"); return 2; }
        try { return Run(pid); }
        catch (Exception e) { Console.Error.WriteLine("ERROR " + e.Message); return 1; }
    }

    static int Run(uint pid)
    {
        var p = new ActivationParams { ActivationType = 1, TargetProcessId = pid, ProcessLoopbackMode = 0 };   // 0 = this process and its children
        IntPtr pp = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(ActivationParams)));
        Marshal.StructureToPtr(p, pp, false);
        var pv = new PropVariantBlob { vt = 0x41, cbSize = (uint)Marshal.SizeOf(typeof(ActivationParams)), pBlobData = pp };
        IntPtr pvp = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(PropVariantBlob)));
        Marshal.StructureToPtr(pv, pvp, false);

        var h = new Handler();
        Guid iid = typeof(IAudioClient).GUID;
        IActivateAudioInterfaceAsyncOperation op;
        ActivateAudioInterfaceAsync("VAD\\Process_Loopback", ref iid, pvp, h, out op);
        if (!h.Done.WaitOne(10000)) throw new Exception("Windows did not answer the audio request");
        int hr; object unk;
        h.Op.GetActivateResult(out hr, out unk);
        if (hr != 0 || unk == null) throw new Exception("Windows refused to capture that program's sound (0x" + hr.ToString("X8") + ")");
        var client = (IAudioClient)unk;

        var fmt = new WaveFormatEx { wFormatTag = 1, nChannels = Channels, nSamplesPerSec = Rate, wBitsPerSample = Bits, nBlockAlign = FrameBytes, nAvgBytesPerSec = (uint)(Rate * FrameBytes), cbSize = 0 };
        IntPtr fp = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WaveFormatEx)));
        Marshal.StructureToPtr(fmt, fp, false);
        // LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY
        hr = client.Initialize(0, 0x00020000 | 0x00040000 | 0x80000000 | 0x08000000, 2000000, 0, fp, IntPtr.Zero);
        if (hr != 0) throw new Exception("Initialize failed 0x" + hr.ToString("X8"));
        IntPtr ev = CreateEvent(IntPtr.Zero, false, false, null);
        hr = client.SetEventHandle(ev);
        if (hr != 0) throw new Exception("SetEventHandle failed 0x" + hr.ToString("X8"));
        Guid cid = typeof(IAudioCaptureClient).GUID;
        object cc;
        hr = client.GetService(ref cid, out cc);
        if (hr != 0) throw new Exception("GetService failed 0x" + hr.ToString("X8"));
        var cap = (IAudioCaptureClient)cc;

        bool stop = false;
        var watch = new Thread(() => { try { var si = Console.OpenStandardInput(); var b = new byte[64]; while (si.Read(b, 0, b.Length) > 0) { } } catch { } stop = true; });
        watch.IsBackground = true; watch.Start();

        var stdout = Console.OpenStandardOutput();
        var clock = Stopwatch.StartNew();
        long written = 0;                 // frames written so far
        byte[] zeros = new byte[Rate * FrameBytes];
        hr = client.Start();
        if (hr != 0) throw new Exception("Start failed 0x" + hr.ToString("X8"));
        try
        {
            while (!stop)
            {
                WaitForSingleObject(ev, 50);
                uint n;
                while (!stop && cap.GetNextPacketSize(out n) == 0 && n > 0)
                {
                    IntPtr data; uint frames, flags; ulong dpos, qpc;
                    if (cap.GetBuffer(out data, out frames, out flags, out dpos, out qpc) != 0) break;
                    int bytes = (int)frames * FrameBytes;
                    var buf = new byte[bytes];
                    if ((flags & 2) == 0) Marshal.Copy(data, buf, 0, bytes);   // 2 = AUDCLNT_BUFFERFLAGS_SILENT
                    cap.ReleaseBuffer(frames);
                    stdout.Write(buf, 0, bytes);
                    written += frames;
                }
                // keep the timeline equal to the wall clock while the program is silent
                long want = clock.ElapsedMilliseconds * Rate / 1000;
                long gap = want - written - Rate / 10;                       // allow 100 ms of slack
                while (gap > 0)
                {
                    int f = (int)Math.Min(gap, Rate);
                    stdout.Write(zeros, 0, f * FrameBytes);
                    written += f; gap -= f;
                }
                stdout.Flush();
            }
        }
        catch (IOException) { }
        client.Stop();
        return 0;
    }
}
