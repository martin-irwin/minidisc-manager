// LP2 / LP4 (ATRAC3) encoding, shared by himd_helper.js (Hi-MD discs) and netmd_helper.js (standard discs).
// The encoder is atracdenc (WebAssembly, in runtime\atracdenc); helper\atrac3_encode.js runs it in a child process because it
// ends the process when it finishes.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

// Windows uses the bundled .exe files, as always. On Linux and macOS a program in the runtime folder is used when it is there,
// else the system's own copy (found on PATH).
const WIN = process.platform === 'win32';
const onPath = name => {                     // full path of a program on PATH (like `which`), or null
    for (const dir of (process.env.PATH || '').split(path.delimiter)) {
        const f = path.join(dir, name);
        try { require('fs').accessSync(f, require('fs').constants.X_OK); return f; } catch (e) { /* not here */ }
    }
    return null;
};
const runtimeBin = (runtimeDir, name) => {
    const exe = path.join(runtimeDir, name + (WIN ? '.exe' : ''));
    return WIN || fs.existsSync(exe) ? exe : (onPath(name) || exe);
};

// bitrate: what to ask atracdenc for (this build rounds UP to a frame size it knows: 128 -> 384-byte frames, 64 -> 192-byte frames).
// frame: bytes per ATRAC3 frame. divisor: how much longer than SP the disc lasts. Each frame holds 1024 samples per channel.
const ATRAC3 = {
    lp2: { bitrate: '128', frame: 384, divisor: 2 },
    lp4: { bitrate: '64', frame: 192, divisor: 4 },
};

// Frames in `seconds` of 44.1 kHz audio.
const framesFor = seconds => Math.ceil(seconds * 44100 / 1024);

// Encodes a WAV file (16-bit 44.1 kHz stereo) and resolves with the raw frames in a Buffer.
function rawEncodeAtrac3(runtimeDir, wavPath, kind) {
    const fmt = ATRAC3[kind];
    if (!fmt) return Promise.reject(new Error('Unknown ATRAC3 format: ' + kind));
    const out = path.join(os.tmpdir(), 'mdm-' + process.pid + '-' + Math.random().toString(36).slice(2) + '.at3raw');
    return new Promise((resolve, reject) => {
        const p = spawn(process.execPath, [path.join(__dirname, 'atrac3_encode.js'), runtimeDir, wavPath, fmt.bitrate, out],
            { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
        let err = '';
        p.stderr.on('data', d => { err += d; });
        p.on('error', reject);
        p.on('close', () => {
            let frames = null;
            try { frames = fs.readFileSync(out); } catch (e) { /* reported below */ }
            try { fs.unlinkSync(out); } catch (e) { /* nothing was written */ }
            if (!frames || !frames.length || frames.length % fmt.frame !== 0) {
                reject(new Error('The ' + kind.toUpperCase() + ' encoder failed' + (err ? ': ' + err.trim().slice(0, 200) : '.')));
            } else {
                resolve(frames);
            }
        });
    });
}

// ATRAC3+: atracdenc 0.2.3 in runtime\atracdenc3p, built for this program with one change (the "framesize" option; the stock program always
// made 2048-byte frames). 2048 bytes a frame = 352 kbps, 1488 = Hi-SP (256 kbps), 376 = Hi-LP (64 kbps): the same sizes himd-js lists.
// The program and its sndfile.dll are run only if they are byte-for-byte the files that were inspected and approved (see
// runtime\atracdenc3p\NOTICE.txt), and never through a shell.
const AT3P_EXE_SHA256 = '52E7CC649A210390AC06CBFD238402559606C4324CC13F34CCC0621D7B71FBCC';
const AT3P_DLL_SHA256 = '4E3BD2DE8E1485110EAEBEF8E1239471F73D608773831C323BF528E05645655E';
const AT3P = { at3p: { frame: 2048, kbps: 352 }, hisp: { frame: 1488, kbps: 256 }, hilp: { frame: 376, kbps: 64 } };
const AT3P_SAMPLES_PER_FRAME = 2048;
const framesForPlus = seconds => Math.ceil(seconds * 44100 / AT3P_SAMPLES_PER_FRAME) + 1;       // the encoder adds one frame of padding

// Encodes a WAV file (16-bit 44.1 kHz stereo) and resolves with {frames: Buffer of whole frames, frameSize, header}.
// onProgress(fraction 0..1), if given: the encoder writes its file as it goes, so the share of the expected size written so far is how far it has got.
function rawEncodeAtrac3Plus(runtimeDir, wavPath, frameBytes = 2048, onProgress = null) {
    // Windows: the checked build and its sndfile.dll, refused if either file's SHA-256 differs. Linux / macOS: runtime/atracdenc3p/atracdenc,
    // built from source with the same frame-size patch by linux/setup.sh (the stock atracdenc ignores the bit rate, so no PATH fallback).
    const exe = path.join(runtimeDir, 'atracdenc3p', WIN ? 'atracdenc.exe' : 'atracdenc'), dll = WIN ? path.join(runtimeDir, 'atracdenc3p', 'sndfile.dll') : null;
    if (!fs.existsSync(exe) || (dll && !fs.existsSync(dll))) return Promise.reject(new Error('The ATRAC3+ encoder is missing (' + exe + ').'));
    const sha = f => require('crypto').createHash('sha256').update(fs.readFileSync(f)).digest('hex').toUpperCase();
    if (WIN && (sha(exe) !== AT3P_EXE_SHA256 || sha(dll) !== AT3P_DLL_SHA256)) return Promise.reject(new Error('The ATRAC3+ encoder is not the file that was checked and approved, so it was not run.'));
    const out = path.join(os.tmpdir(), 'mdm-' + process.pid + '-' + Math.random().toString(36).slice(2) + '.oma');
    let expect = 0;
    try { expect = framesForPlus(Math.max(0, fs.statSync(wavPath).size - 44) / 176400) * frameBytes + 96; } catch (e) { /* no estimate: no progress */ }
    return new Promise((resolve, reject) => {
        const timer = onProgress && expect ? setInterval(() => { try { onProgress(Math.min(0.99, fs.statSync(out).size / expect)); } catch (e) { /* not there yet */ } }, 700) : null;
        require('child_process').execFile(exe, ['-e', 'atrac3plus', '-i', wavPath, '-o', out, '--advanced', 'framesize=' + frameBytes], { windowsHide: true, maxBuffer: 1 << 26 }, (err, stdout, stderr) => {
            if (timer) clearInterval(timer);
            let data = null;
            try { data = fs.readFileSync(out); } catch (e) { /* reported below */ }
            try { fs.unlinkSync(out); } catch (e) { /* nothing was written */ }
            if (err || !data) return reject(new Error('The ATRAC3+ encoder failed' + (stderr ? ': ' + String(stderr).trim().slice(0, 200) : '.')));
            try {
                if (data.toString('latin1', 0, 3) !== 'EA3' || data[32] !== 1) throw new Error('not an ATRAC3+ file');
                const headerLen = (data[4] << 8) | data[5];                       // EA3 header: "EA3", version, then its length as a 16-bit number (96)
                if (headerLen < 36 || headerLen >= data.length) throw new Error('bad header length ' + headerLen);
                const params = (data[33] << 16) | (data[34] << 8) | data[35];
                if (((params >> 13) & 7) !== 1) throw new Error('not 44.1 kHz');
                const frameSize = (params & 0x3ff) * 8 + 8;
                const body = data.subarray(headerLen);
                if (frameSize !== frameBytes) throw new Error('it made ' + frameSize + '-byte frames, not the ' + frameBytes + ' asked for');
                if (!body.length || body.length % frameSize !== 0) throw new Error('the audio is not a whole number of frames');
                resolve({ frames: body, frameSize, header: data.subarray(0, headerLen) });
            } catch (e) {
                reject(new Error('The ATRAC3+ encoder produced a file this app does not understand (' + e.message + ').'));
            }
        });
    });
}

// ---------------------------------------------------------------------------------------------------------------------------
// Headroom. A lossy encoder's output can swing a little beyond the loudest samples of the original, and the player then clips
// those peaks flat: on a loud, mastered-hot CD that is a crackle like dust on a record (measured on a CD single: LP2 gave 14 times
// as many full-scale samples as the CD itself, MP3 none). So after encoding the result is decoded without clipping; if it would
// clip, the source is turned down by just enough (peak -> 0.985) and encoded again. Quiet tracks are not touched.
// ---------------------------------------------------------------------------------------------------------------------------
const HEADROOM_TARGET = 0.985;
const HEADROOM_PASSES = 2;
const AT3P_OVERSHOOT = 1.19;           // ATRAC3+ output peak / input peak. It varies by track: 1.006 to 1.182 on 12 full-scale tracks of a decoded SP disc (Hi-SP, 2026-11-11; 1.028 on 17 CD tracks the day before), so 1.045 left 8 of 12 needing a second encode. 1.19 covers all of them; the check after the encode stays as the safety net. LP2 / LP4 are not pre-lowered: not measured

// Loudest sample (1.0 = full scale) of `bytes` (a WAV or OMA file) decoded to 32-bit float by ffmpeg, so nothing is clipped.
// onProgress(fraction), if given, with expectBytes (the decoded size to expect, as 32-bit float stereo): how much has been checked so far.
function decodedPeak(runtimeDir, inputFormat, bytes, onProgress = null, expectBytes = 0) {
    return new Promise((resolve, reject) => {
        const exe = runtimeBin(runtimeDir, 'ffmpeg');
        if (!fs.existsSync(exe)) return reject(new Error('The bundled decoder is missing.'));
        const p = spawn(exe, ['-hide_banner', '-loglevel', 'error', '-f', inputFormat, '-i', 'pipe:0', '-vn', '-f', 'f32le', '-acodec', 'pcm_f32le', 'pipe:1'], { windowsHide: true });
        let peak = 0, carry = Buffer.alloc(0), err = '', seen = 0, last = 0;
        p.stdout.on('data', d => {
            seen += d.length;
            if (onProgress && expectBytes && Date.now() - last > 700) { last = Date.now(); try { onProgress(Math.min(0.99, seen / expectBytes)); } catch (e) { /* progress is only a courtesy */ } }
            const b = carry.length ? Buffer.concat([carry, d]) : d;
            const n = b.length - (b.length % 4);
            for (let i = 0; i < n; i += 4) { const v = Math.abs(b.readFloatLE(i)); if (v > peak) peak = v; }
            carry = b.subarray(n);
        });
        p.stderr.on('data', d => { err += d; });
        p.stdin.on('error', () => { /* ffmpeg quit early; reported below */ });
        p.on('error', reject);
        p.on('close', code => code === 0 || peak > 0 ? resolve(peak) : reject(new Error('Could not check the encoded audio: ' + err.trim().slice(0, 200))));
        p.stdin.end(bytes);
    });
}

// A copy of the WAV at `gain` times its level (a temporary file), made by ffmpeg.
function scaledCopy(runtimeDir, wavPath, gain) {
    const out = path.join(os.tmpdir(), 'mdm-' + process.pid + '-' + Math.random().toString(36).slice(2) + '-gain.wav');
    return new Promise((resolve, reject) => {
        const p = spawn(runtimeBin(runtimeDir, 'ffmpeg'), ['-hide_banner', '-loglevel', 'error', '-y', '-i', wavPath, '-vn', '-af', 'volume=' + gain.toFixed(5),
            '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', '-f', 'wav', out], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
        let err = '';
        p.stderr.on('data', d => { err += d; });
        p.on('error', reject);
        p.on('close', code => code === 0 ? resolve(out) : reject(new Error('Could not lower the level before encoding: ' + err.trim().slice(0, 200))));
    });
}

// Loudest sample (1.0 = full scale) of a WAV file, read straight from disk by ffmpeg (decoded to 32-bit float, nothing clipped).
function filePeak(runtimeDir, wavPath, onProgress = null, expectBytes = 0) {
    return new Promise((resolve, reject) => {
        const exe = runtimeBin(runtimeDir, 'ffmpeg');
        if (!fs.existsSync(exe)) return reject(new Error('The bundled decoder is missing.'));
        const p = spawn(exe, ['-hide_banner', '-loglevel', 'error', '-i', wavPath, '-vn', '-f', 'f32le', '-acodec', 'pcm_f32le', 'pipe:1'], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
        let peak = 0, carry = Buffer.alloc(0), err = '', seen = 0, last = 0;
        p.stdout.on('data', d => {
            seen += d.length;
            if (onProgress && expectBytes && Date.now() - last > 700) { last = Date.now(); try { onProgress(Math.min(0.99, seen / expectBytes)); } catch (e) { /* progress is only a courtesy */ } }
            const b = carry.length ? Buffer.concat([carry, d]) : d;
            const n = b.length - (b.length % 4);
            for (let i = 0; i < n; i += 4) { const v = Math.abs(b.readFloatLE(i)); if (v > peak) peak = v; }
            carry = b.subarray(n);
        });
        p.stderr.on('data', d => { err += d; });
        p.on('error', reject);
        p.on('close', code => code === 0 || peak > 0 ? resolve(peak) : reject(new Error('Could not check the level of the audio: ' + err.trim().slice(0, 200))));
    });
}

// Runs `encode(wav)` (resolving with something `peakOf` can decode), lowering the source level and encoding again while the decoded
// result would clip. Resolves with {result, gain} (gain 1: untouched).
// pre = {overshoot, onProgress}: how much this encoder's output can exceed its input's peak (Hi-SP: measured at 1.028 on a full-scale
// track; 1.045 is used). The source is measured FIRST (about a second) and a source that would clip is turned down before the first encode,
// so the usual loud track is encoded once instead of twice. The check after the encode stays as the safety net (a second encode only
// if the guess was too small).
async function encodeWithHeadroom(runtimeDir, wavPath, encode, peakOf, pre = null) {
    let gain = 1, src = wavPath, temp = null;
    try {
        if (pre) {
            let bytes = 0;
            try { bytes = Math.max(0, fs.statSync(wavPath).size - 44) * 2; } catch (e) { /* no estimate: no progress */ }          // the float decode is twice the 16-bit size
            const peak = await filePeak(runtimeDir, wavPath, pre.onProgress, bytes);
            if (peak * pre.overshoot > 0.999) {
                gain = HEADROOM_TARGET / (peak * pre.overshoot);
                src = temp = await scaledCopy(runtimeDir, wavPath, gain);
            }
        }
        let result = await encode(src, 0);
        for (let pass = 0; pass < HEADROOM_PASSES; pass++) {
            const peak = await peakOf(result, pass);
            if (peak <= 0.999) break;
            gain *= HEADROOM_TARGET / peak;
            if (temp) { try { fs.unlinkSync(temp); } catch (e) { /* already gone */ } }
            src = temp = await scaledCopy(runtimeDir, wavPath, gain);
            result = await encode(src, pass + 1);
        }
        return { result, gain };
    } finally {
        if (temp) { try { fs.unlinkSync(temp); } catch (e) { /* already gone */ } }
    }
}

async function encodeAtrac3(runtimeDir, wavPath, kind) {
    const netmd = require(path.join(runtimeDir, 'node_modules', 'netmd-js'));
    const disc = kind === 'lp2' ? netmd.DiscFormat.lp2 : netmd.DiscFormat.lp4;
    const wrap = frames => Buffer.concat([Buffer.from(netmd.createWavHeader(disc, frames.length)), frames]);
    const { result, gain } = await encodeWithHeadroom(runtimeDir, wavPath, w => rawEncodeAtrac3(runtimeDir, w, kind), frames => decodedPeak(runtimeDir, 'wav', wrap(frames)));
    result.gain = gain;
    return result;
}

// onProgress({step: 'encoding' | 'checking', pass, frac}), if given: how far the encoder (then the check for clipping) has got; pass counts the
// encodes made again at a lower level (0 is the first).
async function encodeAtrac3Plus(runtimeDir, wavPath, kind = 'at3p', onProgress = null) {
    const fmt = AT3P[kind];
    if (!fmt) throw new Error('Unknown ATRAC3+ format: ' + kind);
    let seconds = 0;
    try { seconds = Math.max(0, fs.statSync(wavPath).size - 44) / 176400; } catch (e) { /* no estimate: no progress */ }
    const tell = (step, pass) => onProgress ? frac => onProgress({ step, pass, frac }) : null;
    const { result, gain } = await encodeWithHeadroom(runtimeDir, wavPath, (w, pass) => rawEncodeAtrac3Plus(runtimeDir, w, fmt.frame, tell('encoding', pass)),
        (enc, pass) => decodedPeak(runtimeDir, 'oma', Buffer.concat([enc.header, enc.frames]), tell('checking', pass), seconds * 44100 * 2 * 4),
        { overshoot: AT3P_OVERSHOOT, onProgress: tell('checking', 0) });
    result.gain = gain;
    return result;
}

module.exports = { ATRAC3, AT3P, framesFor, encodeAtrac3, encodeAtrac3Plus, framesForPlus, AT3P_SAMPLES_PER_FRAME };
