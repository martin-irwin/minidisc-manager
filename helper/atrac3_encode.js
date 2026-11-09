// Encodes a 16-bit 44.1 kHz stereo WAV to raw ATRAC3 frames with atracdenc (WebAssembly, runtime\atracdenc).
// Usage: node atrac3_encode.js <runtimeDir> <in.wav> <bitrateArg> <out.raw>
// It runs in its own process because atracdenc ends the process when it finishes. The output is the frames only
// (atracdenc's 96-byte header is dropped): 384-byte frames for bitrate 128 (LP2), 192-byte frames for bitrate 64 (LP4).
// This build rounds the requested bitrate UP to the next frame size it knows, so 132 would give 424-byte frames.
const fs = require('fs');
const path = require('path');

const [runtime, wav, bitrate, out] = process.argv.slice(2);

(async () => {
    const mod = await require(path.join(runtime, 'atracdenc', 'atracdenc.js'))({ print: () => {}, printErr: () => {} });
    mod.FS.writeFile('in.wav', new Uint8Array(fs.readFileSync(wav)));
    process.on('exit', () => {
        try { fs.writeFileSync(out, mod.FS.readFile('out.aea').subarray(96)); } catch (e) { /* the caller sees the missing file */ }
    });
    mod.callMain(['-e', 'atrac3', '-i', 'in.wav', '-o', 'out.aea', '--bitrate', String(bitrate)]);
})().catch(e => { process.stderr.write(String((e && e.message) || e)); process.exit(1); });
