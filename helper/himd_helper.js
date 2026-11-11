// Runs on the bundled Node (..\runtime\node.exe) and uses the himd-js copy in ..\runtime\node_modules.
// Usage: himd_helper.js <command> [json-args]
// Output: one JSON object per line on stdout ({"event":...} progress lines, then {"result":...} or {"error":...}).
const path = require('path');

const RT = process.env.HIMD_RUNTIME || path.join(__dirname, '..', 'runtime');
const mod = name => require(path.join(RT, 'node_modules', name));

const { WebUSB } = mod('usb');
const himdjs = mod('himd-js');

// Resolves once the line has been flushed, so process.exit() right after cannot cut it off.
const say = obj => new Promise(resolve => process.stdout.write(JSON.stringify(obj) + '\n', resolve));

// In simulate mode the recorder's WRITE commands are kept in memory and reads see them, so the whole
// upload can be rehearsed against the real disc structures without changing the disc.
function installOverlay(driver) {
    const writes = new Map();                       // lba -> block
    const realRead = driver.readBlocks.bind(driver);
    driver.readBlocks = async (address, count, blockSize) => {
        const out = new Uint8Array(await realRead(address, count, blockSize));
        for (let i = 0; i < count; i++) {
            const w = writes.get(address + i);
            if (w) out.set(w, i * blockSize);
        }
        return out;
    };
    driver.writeBlocks = async (address, data, blockSize) => {
        for (let i = 0; i < data.length / blockSize; i++) writes.set(address + i, data.slice(i * blockSize, (i + 1) * blockSize));
    };
    return writes;
}

async function openDisc({ simulate = false } = {}) {
    const ids = himdjs.DevicesIds.filter(d => d.vendorId === 0x054c).map(d => ({ vendorId: d.vendorId, productId: d.deviceId }));
    const webusb = new WebUSB({ allowedDevices: ids, deviceTimeout: 10000000 });
    const device = await webusb.requestDevice({ filters: ids });
    await device.open();
    const fsDriver = new himdjs.UMSCHiMDFilesystem(device);
    const overlay = simulate ? installOverlay(fsDriver.driver) : null;
    await fsDriver.init();
    const himd = await himdjs.HiMD.init(fsDriver);
    return { device, fsDriver, himd, overlay };
}

async function closeDisc(ctx) {
    try { await ctx.fsDriver.driver.close(); } catch (e) { /* already closed */ }
}

// ---------------------------------------------------------------------------
// Source files. Any audio file the bundled ffmpeg can read is accepted; what ends up on the disc depends on the chosen format:
//   auto        MP3 files are added as they are (Hi-MD stores MP3 natively); everything else becomes lossless PCM
//   pcm         lossless PCM (16-bit 44.1 kHz stereo, stored as big-endian samples)
//   mp3         MP3 files as they are; anything else is encoded to MP3 (constant bit rate, mp3Kbps)
//   lp2 / lp4   ATRAC3 132 / 66 kbps, encoded here with atracdenc
// (ATRAC3+ cannot be written: there is no encoder for it.) Conversions use temporary files, removed when the helper ends.
// ---------------------------------------------------------------------------
const fs = require('fs');
const os = require('os');
const NodeID3 = mod('node-id3');

const { parseWav } = require('./wav');
const atrac3 = require('./atrac3');

const FORMATS = ['auto', 'pcm', 'mp3', 'lp2', 'lp4', 'at3p', 'hisp', 'hilp'];      // ATRAC3+: at3p 352 kbps, hisp (Hi-SP) 256 kbps, hilp (Hi-LP) 64 kbps
const MP3_RATES = [128, 192, 256, 320];
const OTHER_AUDIO = ['.flac', '.m4a', '.mp4', '.aac', '.ogg', '.oga', '.opus', '.wma', '.aif', '.aiff', '.dts', '.dtshd', '.ac3', '.eac3', '.thd', '.mlp', '.mka', '.mkv', '.m2ts'];

const temps = [];
function tempName(ext) {
    const p = path.join(os.tmpdir(), 'mdm-' + process.pid + '-' + Math.random().toString(36).slice(2) + ext);
    temps.push(p);
    return p;
}
process.on('exit', () => { for (const p of temps.splice(0)) { try { fs.unlinkSync(p); } catch (e) { /* already gone */ } } });

// Runs the bundled ffmpeg; returns its stderr. `what` completes "Could not …" if it fails.
function ffmpeg(args, what) {
    const exe = path.join(RT, 'ffmpeg.exe');
    if (!fs.existsSync(exe)) throw new Error('The bundled decoder is missing (' + exe + ').');
    const r = require('child_process').spawnSync(exe, ['-hide_banner', '-y', ...args], { windowsHide: true, encoding: 'utf8', maxBuffer: 1 << 26 });
    if (r.status !== 0) throw new Error('Could not ' + what + '.');
    return r.stderr || '';
}

// Length in seconds of any audio file, by decoding it (the last progress line ffmpeg prints is the true length).
// Title / artist / album from the tags of any audio file ffmpeg can open (FLAC, M4A, OGG, Opus, WMA, WAV, AIFF...). Empty strings when there are none.
function ffmpegTags(file) {
    const none = { title: '', artist: '', album: '' };
    const run = extra => {                                         // the tags as ffmpeg's "ffmetadata" text, parsed into {lower-case name: value}
        const out = require('child_process').execFileSync(path.join(RT, 'ffmpeg.exe'), ['-hide_banner', '-loglevel', 'error', '-i', file, '-vn', ...extra, '-f', 'ffmetadata', '-'],
            { encoding: 'utf8', timeout: 20000, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
        const tags = {};
        for (const line of out.split(/\r?\n/)) {
            if (/^[;#]/.test(line)) continue;
            const m = /^([^=\s][^=]*)=(.*)$/.exec(line);
            if (m) tags[m[1].trim().toLowerCase()] = m[2].replace(new RegExp(String.fromCharCode(92, 92) + '(.)', 'g'), '$1').trim();     // ffmetadata escapes = ; # and the backslash itself with a backslash
        }
        return tags;
    };
    try {
        let tags = run([]);                                        // FLAC, M4A, WAV, WMA...: file-level tags
        if (!tags.title && !tags.artist && !tags.album) tags = run(['-map_metadata', '0:s:0']);      // OGG / Opus keep them on the audio stream
        return { title: tags.title || '', artist: tags.artist || tags.album_artist || tags.albumartist || '', album: tags.album || '' };
    } catch (e) {
        return none;
    }
}

function probeSeconds(file) {
    const err = ffmpeg(['-i', file, '-vn', '-f', 'null', '-'], 'read ' + path.basename(file) + ' as audio');
    const m = [...err.matchAll(/time=(\d+):(\d\d):(\d\d(?:\.\d+)?)/g)].pop();
    if (!m) throw new Error('Could not read ' + path.basename(file) + ' as audio.');
    return Number(m[1]) * 3600 + Number(m[2]) * 60 + parseFloat(m[3]);
}

// Returns what we know about a file without touching the recorder.
function inspectFile(file) {
    const ext = path.extname(file).toLowerCase();
    const base = path.basename(file, path.extname(file));
    const other = () => {                                          // anything else ffmpeg can decode (or a WAV that is not 16-bit 44.1 kHz stereo)
        const secs = probeSeconds(file), tags = ffmpegTags(file);
        return { path: file, kind: 'audio', label: ext.slice(1) || 'audio', bytes: fs.statSync(file).size, seconds: Math.round(secs), exactSeconds: secs, title: tags.title || base, artist: tags.artist, album: tags.album };
    };
    if (ext === '.mp3') {
        const buf = fs.readFileSync(file);
        const tags = NodeID3.read(buf) || {};
        const secs = probeSeconds(file);
        return { path: file, kind: 'mp3', bytes: buf.length, seconds: Math.round(secs), exactSeconds: secs, title: tags.title || base, artist: tags.artist || '', album: tags.album || '' };
    }
    if (ext === '.wav') {
        let data;
        try { data = parseWav(fs.readFileSync(file)); } catch (e) { return other(); }
        const tags = ffmpegTags(file);
        return { path: file, kind: 'wav', bytes: data.length, seconds: Math.round(data.length / 176400), exactSeconds: data.length / 176400, title: tags.title || base, artist: tags.artist, album: tags.album };
    }
    if (OTHER_AUDIO.includes(ext)) return other();
    throw new Error('Unsupported file type ' + (ext || '(none)') + '. Add MP3, WAV, FLAC, M4A, OGG or similar audio files.');
}

const effectiveFormat = (info, format) => format === 'auto' ? (info.kind === 'mp3' ? 'mp3' : 'pcm') : format;
const needsConversion = (info, format) => { const f = effectiveFormat(info, format); return f === 'mp3' ? info.kind !== 'mp3' : info.kind !== 'wav'; };

// What is actually written for this file: {kind: 'mp3' | 'wav', file}. Converts through a temporary file when needed.
function resolveSource(info, format, mp3Kbps) {
    const f = effectiveFormat(info, format);
    if (f === 'mp3') {
        if (info.kind === 'mp3') return { kind: 'mp3', file: info.path };
        const out = tempName('.mp3');
        ffmpeg(['-i', info.path, '-vn', '-map_metadata', '-1', '-ar', '44100', '-ac', '2', '-c:a', 'libmp3lame', '-b:a', mp3Kbps + 'k',
            '-write_xing', '0', '-id3v2_version', '3', out], 'encode ' + path.basename(info.path) + ' as MP3');
        return { kind: 'mp3', file: out };
    }
    if (info.kind === 'wav') return { kind: 'wav', file: info.path };
    const out = tempName('.wav');                                  // PCM, LP2 and LP4 start from 16-bit 44.1 kHz stereo
    ffmpeg(['-i', info.path, '-vn', '-map_metadata', '-1', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-f', 'wav', out], 'convert ' + path.basename(info.path) + ' to WAV');
    return { kind: 'wav', file: out };
}

// Rough space an upload needs on the disc: audio is stored in 16 KB blocks.
function blocksNeeded(info, format = 'auto', mp3Kbps = 192) {
    const f = effectiveFormat(info, format);
    if (f === 'lp2' || f === 'lp4') {                              // whole ATRAC3 frames, as many as fit in one block
        return Math.ceil(atrac3.framesFor(info.exactSeconds) / Math.floor((himdjs.HIMD_AUDIO_SIZE - 1) / atrac3.ATRAC3[f].frame));
    }
    if (atrac3.AT3P[f]) return Math.ceil(atrac3.framesForPlus(info.exactSeconds) / Math.floor((himdjs.HIMD_AUDIO_SIZE - 1) / atrac3.AT3P[f].frame));   // ATRAC3+ frames: 2048 / 1488 / 376 bytes
    if (f === 'mp3') return Math.ceil((info.kind === 'mp3' ? info.bytes : info.exactSeconds * mp3Kbps * 125) * 1.03 / himdjs.HIMD_AUDIO_SIZE);
    return Math.ceil((info.kind === 'wav' ? info.bytes : info.exactSeconds * 176400) / himdjs.HIMD_AUDIO_SIZE);
}

// Accepts a path string or {path, title, artist, album}; the latter lets the caller override the tags.
function describe(f) {
    if (typeof f === 'string') return inspectFile(f);
    const info = inspectFile(f.path);
    for (const k of ['title', 'artist', 'album']) if (typeof f[k] === 'string') info[k] = f[k];
    return info;
}

// himd-js's openAtdataForWriting() starts seek-to-end without awaiting it. If audio is written before
// that finishes, the first block lands at the wrong place and is lost (found on 2026-10-19). So: let the
// seek settle, confirm the position, and then check every block lands exactly where it should.
async function openAtdataSafely(himd) {
    const atdata = await himd.openAtdataForWriting();
    await new Promise(r => setTimeout(r, 200));
    const chain = atdata.handle.chain;
    if (chain.cursor !== atdata.length) {
        throw new Error('Safety check failed: the write position is not at the end of the audio file (' +
            chain.cursor + ' vs ' + atdata.length + '). Nothing was written.');
    }
    return atdata;
}

function guardStream(stream, atdata) {
    const chain = atdata.handle.chain;
    let expected = stream.firstBlock * himdjs.BLOCK_SIZE;
    const write = stream.writeAudioBlock.bind(stream);
    stream.writeAudioBlock = async block => {
        if (chain.cursor !== expected) {
            throw new Error('Safety check failed: an audio block was about to be written at the wrong position (' +
                chain.cursor + ' instead of ' + expected + '). The track index was not changed.');
        }
        await write(block);
        expected += himdjs.BLOCK_SIZE;
    };
    return stream;
}

// Like himd-js dumpTrack for a PCM or ATRAC track, but the blocks start at track block `startBlock` (a seek while playing).
// The first chunk is the header, as with dumpTrack; skipping is free, since only the blocks from there on are read from the disc.
async function* dumpFrom(himd, slot, startBlock) {
    const track = himd.getTrack(slot);
    const isPcm = himdjs.getCodecName(track) === 'PCM';
    const stream = await himd.openNonMP3Stream(slot);
    const bs = stream.blockStream, frags = bs.fragments;
    const total = frags.reduce((a, f) => a + (f.lastBlock - f.firstBlock + 1), 0);
    yield { data: isPcm ? new Uint8Array(0) : mod('himd-js/dist/utils').createEA3Header(track), total };
    let rem = startBlock, fi = 0;
    while (fi < frags.length && rem >= frags[fi].lastBlock - frags[fi].firstBlock + 1) { rem -= frags[fi].lastBlock - frags[fi].firstBlock + 1; fi++; }
    bs.currentFragment = fi;
    if (fi < frags.length) {
        bs.currentBlock = frags[fi].firstBlock + rem;
        if (rem > 0) await bs.atdata.seek(bs.currentBlock * himdjs.BLOCK_SIZE);      // the first block of a fragment seeks by itself
    }
    let block;
    while ((block = await stream.readBlock()) !== null) {
        const b = block.block;
        if (isPcm) for (let i = 0; i < b.length; i += 2) { const t = b[i]; b[i] = b[i + 1]; b[i + 1] = t; }   // LE -> BE, as in himd-js
        yield { data: b, total };
    }
}

// Plays an ATRAC3 / ATRAC3+ track (kind 'oma') or an MP3 track (kind 'mp3'): the stream from himd-js goes into ffmpeg as it is
// read and the decoded audio is appended to a WAV whose header declares the full size up front (as for PCM), so playback can
// start after the first blocks. An MP3's exact length is not known until it has all been read, so its WAV is sized from the
// track's length in seconds (plus a little) and padded with silence. Reading is far faster than real time.
// Closes the disc once everything is read.
// startBlock > 0 (a seek): the file already has its header and the earlier part; decoded audio is written from that block's place on.
async function streamAtrac(ctx, track, dump, out, isStopped, exact = false, kind = 'oma', startBlock = 0) {
    const isMp3 = kind === 'mp3';
    const codecs = mod('himd-js/dist/codecs');
    const audioSize = mod('himd-js/dist/streams').HIMD_AUDIO_SIZE;
    const bytesPerFrame = isMp3 ? 0 : codecs.getBytesPerFrame(track), samplesPerFrame = isMp3 ? 0 : codecs.getSamplesPerFrame(track);
    const rate = isMp3 ? 44100 : codecs.getSampleRate(track);                  // an MP3 is converted to 44.1 kHz stereo
    const exe = path.join(RT, 'ffmpeg.exe');
    if (!fs.existsSync(exe)) throw new Error('The bundled decoder is missing (' + exe + ').');
    const p = require('child_process').spawn(exe, ['-hide_banner', '-loglevel', 'error', '-f', isMp3 ? 'mp3' : 'oma', '-i', 'pipe:0',
        '-vn', ...(isMp3 ? ['-ar', '44100', '-ac', '2'] : []), '-acodec', 'pcm_s16le', '-f', 's16le', 'pipe:1'], { windowsHide: true });
    const startPos = 44 + startBlock * (isMp3 ? 0 : Math.floor(audioSize / bytesPerFrame) * samplesPerFrame * 4);
    let err = '', pos = startPos, declared = 0;                                    // pos: where the next decoded byte goes
    const fd = fs.openSync(out, startBlock > 0 ? 'r+' : 'w');
    const closed = new Promise((resolve, reject) => { p.on('error', reject); p.on('close', resolve); });
    p.stdin.on('error', () => { /* ffmpeg quit early; its exit code is reported below */ });
    p.stderr.on('data', d => { err += d; });
    p.stdout.on('data', d => {
        const room = 44 + declared - pos;                                         // never write past what the header declares
        if (room <= 0) return;
        const b = d.length > room ? d.subarray(0, room) : d;
        fs.writeSync(fd, b, 0, b.length, pos); pos += b.length;
    });
    try {
        let first = true, blocksRead = 0, lastReport = 0;
        for await (const chunk of dump.data) {
            if (isStopped()) throw new Error('stopped');
            if (!first && Date.now() - lastReport > 250) { lastReport = Date.now(); await say({ event: 'progress', done: blocksRead, total: chunk.total, hi: pos }); }
            blocksRead++;
            if (first) {
                first = false;
                declared = isMp3 ? (track.seconds + 2) * rate * 4                                          // upper bound; the tail is padded
                    : chunk.total * Math.floor(audioSize / bytesPerFrame) * samplesPerFrame * 4;
                if (startBlock === 0) {
                    const h = Buffer.alloc(44);
                    h.write('RIFF', 0); h.writeUInt32LE(36 + declared, 4); h.write('WAVEfmt ', 8); h.writeUInt32LE(16, 16);
                    h.writeUInt16LE(1, 20); h.writeUInt16LE(2, 22); h.writeUInt32LE(rate, 24); h.writeUInt32LE(rate * 4, 28);
                    h.writeUInt16LE(4, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(declared, 40);
                    fs.writeSync(fd, h, 0, 44, 0);
                }
                await say({ event: 'start', progressive: true, totalBytes: 44 + declared, format: 'wav', lo: startPos });
            }
            const buf = Buffer.from(chunk.data.buffer, chunk.data.byteOffset, chunk.data.byteLength);
            if (!p.stdin.write(buf)) await new Promise(r => p.stdin.once('drain', r));
        }
        p.stdin.end();
        await closeDisc(ctx); ctx.closed = true;                                  // the recorder is free while ffmpeg finishes
        const code = await closed;
        if (code !== 0) throw new Error('The audio decoder failed: ' + err.trim().slice(0, 300));
        const produced = pos - 44;
        if (exact) {                                                              // a saved file: true length, header patched to match
            const sz = Buffer.alloc(4);
            sz.writeUInt32LE(36 + produced); fs.writeSync(fd, sz, 0, 4, 4);
            sz.writeUInt32LE(produced); fs.writeSync(fd, sz, 0, 4, 40);
            fs.ftruncateSync(fd, 44 + produced);
            return { bytes: 44 + produced, format: 'wav', decodedBytes: produced };
        }
        if (pos < 44 + declared) { const pad = Buffer.alloc(44 + declared - pos); fs.writeSync(fd, pad, 0, pad.length, pos); }
        return { bytes: 44 + declared, format: 'wav', decodedBytes: produced, hi: 44 + declared };
    } catch (e) {
        try { p.kill(); } catch (k) { /* already gone */ }
        throw e;
    } finally {
        fs.closeSync(fd);
    }
}

// ---------------------------------------------------------------------------
// A picture stored on the disc: /COVER.JPG in the root of the Hi-MD volume (next to HMDHIFI, which the recorder manages).
// The recorder ignores files it does not know. Writing a new file is the one thing here that changes the FAT and the root
// directory, so it is backed up first, and checked afterwards by re-mounting the volume.
// ---------------------------------------------------------------------------
const COVER = '/COVER.JPG';
const TRACKLIST = '/TRACKS.CSV';           // the track list (a spreadsheet file), kept up to date by the app when the user switches that on
const LABEL = '/LABEL.JPG';              // the printed-sticker label picture (JPEG), written when the user presses "Save to disc" in Disc labelling
const GROUPART = '/GROUPART.JSN';          // the pictures of the groups (JSON text), written when the user presses "Save group pictures to the disc"
const LYRICS = '/LYRICS.TXT';              // the lyrics of the tracks (JSON text), written when the user presses "Save lyrics to disc"

// Boot sector, reserved area, both FATs and the root directory, as raw bytes.
async function volumeHead(fsDriver) {
    const cap = await fsDriver.driver.getCapacity(), bs = cap.blockSize;
    const first = Buffer.from(await fsDriver.driver.readBlocks(0, 1, bs));
    const g = { bps: first.readUInt16LE(11), spc: first[13], res: first.readUInt16LE(14), nf: first[16], rootEnt: first.readUInt16LE(17), spf: first.readUInt16LE(22) };
    g.rootSecs = Math.ceil(g.rootEnt * 32 / g.bps);
    const bytes = (g.res + g.nf * g.spf + g.rootSecs) * g.bps;
    const all = Buffer.from(await fsDriver.driver.readBlocks(0, Math.ceil(bytes / bs), bs));
    return { geometry: g, data: all.subarray(0, bytes) };
}

// Every file in the root and in HMDHIFI: size, first cluster and the cluster chain.
async function snapshotFiles(fsDriver) {
    const fat = fsDriver.fatfs.getUnderlying();
    const files = [];
    for (const dir of ['/', '/HMDHIFI']) {
        for (const e of await fsDriver.list(dir)) {
            if (e.type !== 'file') continue;
            const p = '/' + e.name.replace(/^\/+/, '');
            const tree = await fat.traverseEntries(p);
            const entry = tree[tree.length - 1];
            files.push({ path: p, size: entry.fileSize, first: entry._firstCluster, chain: entry.fileSize ? fat.getClusterChainFromFAT(entry._firstCluster) : [] });
        }
    }
    return { files, clusterSize: fat.clusterSizeInBytes };
}

// Everything the recorder relies on must be exactly as it was, apart from the one file being written (`target`: the picture or the
// track list; the other of the two must be untouched). Throws with a clear message otherwise.
async function verifyVolume(fsDriver, before, after, expectCover, target = COVER) {
    const problems = [];
    const byPath = s => new Map(s.files.map(f => [f.path.toUpperCase(), f]));
    const b = byPath(before), a = byPath(after);
    for (const [p, f] of b) {
        if (p === target) continue;
        const g = a.get(p);
        if (!g) { problems.push(f.path + ' has disappeared'); continue; }
        if (g.size !== f.size || g.first !== f.first || JSON.stringify(g.chain) !== JSON.stringify(f.chain)) problems.push(f.path + ' has changed');
    }
    for (const p of a.keys()) if (p !== target && !b.has(p)) problems.push('an unexpected file appeared: ' + p);
    const seen = new Map();
    for (const f of after.files) {                          // no two files may share a cluster
        if (f.size && f.chain.length * after.clusterSize < f.size) problems.push(f.path + ' is shorter on disc than its size says');
        for (const c of f.chain) { if (seen.has(c)) problems.push(f.path + ' shares a cluster with ' + seen.get(c)); seen.set(c, f.path); }
    }
    const head = await volumeHead(fsDriver), g = head.geometry;
    const fat1 = head.data.subarray(g.res * g.bps, (g.res + g.spf) * g.bps), fat2 = head.data.subarray((g.res + g.spf) * g.bps, (g.res + 2 * g.spf) * g.bps);
    if (g.nf >= 2 && !fat1.equals(fat2)) problems.push('the two copies of the FAT differ');
    const present = a.has(target), what = target === COVER ? 'the picture' : target === LABEL ? 'the label' : target === LYRICS ? 'the lyrics file' : 'the track list';
    if (expectCover && !present) problems.push(what + ' is not in the root folder');
    if (!expectCover && present) problems.push(what + ' is still in the root folder');
    if (problems.length) throw new Error('Checking the disc afterwards found a problem: ' + problems.join('; ') + '.');
    return { clusters: after.files.find(f => f.path.toUpperCase() === target) ? after.files.find(f => f.path.toUpperCase() === target).chain.length : 0, filesChecked: b.size - (b.has(target) ? 1 : 0) };
}

// WRITES A FILE TO THE DISC (unless simulate): stores `data` as `target` in the root folder, replacing an earlier file of that name,
// after backing up the head of the volume, and checks by re-mounting that nothing else changed and that the file reads back the same.
async function putRootFile(target, data, label, { simulate = false, backupDir = null } = {}) {
    const ctx = await openDisc({ simulate });
    try {
        const { fsDriver } = ctx;
        const before = await snapshotFiles(fsDriver);
        const old = before.files.find(f => f.path.toUpperCase() === target);
        const space = await fsDriver.statFilesystem(), cs = before.clusterSize;
        const need = Math.ceil(data.length / cs) * cs, back = old ? Math.ceil(old.size / cs) * cs : 0;
        if (need > space.left + back - 4 * cs) throw new Error('There is not enough free space on the disc for the ' + label + '.');
        if (backupDir && !simulate) {                   // the part of the volume this changes, to restore by hand if ever needed
            fs.mkdirSync(backupDir, { recursive: true });
            const head = await volumeHead(fsDriver);
            fs.writeFileSync(path.join(backupDir, 'volume_head.bin'), head.data);
            fs.writeFileSync(path.join(backupDir, 'volume_head.json'), JSON.stringify(head.geometry));
        }
        if (old) await fsDriver.delete(target);
        const h = await fsDriver.open(target, 'rw');
        await h.write(new Uint8Array(data));
        await h.close();
        await fsDriver.initFS();                        // mount again from what is really there (the overlay when simulating)
        const after = await snapshotFiles(fsDriver);
        const checked = await verifyVolume(fsDriver, before, after, true, target);
        const rh = await fsDriver.open(target, 'ro');
        const back2 = Buffer.from(await rh.read(data.length));
        await rh.close();
        if (!back2.equals(data)) throw new Error('Checking the disc afterwards found a problem: the ' + label + ' does not read back the same.');
        return { stored: data.length, clusters: checked.clusters, replaced: !!old, filesChecked: checked.filesChecked, simulated: simulate, readBack: true,
                 sectorsWouldWrite: simulate ? ctx.overlay.size : undefined };
    } finally {
        await closeDisc(ctx);
    }
}
// Raw copies of the track index and the signed MAC list, to restore by hand if ever needed.
async function backupIndex(himd, dir) {
    fs.mkdirSync(dir, { recursive: true });
    for (const name of ['TRKIDX', 'MCLIST']) {
        const h = await himd.openDatanumDependent(name, 'ro');
        const data = Buffer.from(await h.read(h.length));
        await h.close();
        fs.writeFileSync(path.join(dir, himd.getDatanumDependentName(name).split('/').pop()), data);
    }
}

async function removeRootFile(target, { simulate = false, backupDir = null } = {}) {
    const ctx = await openDisc({ simulate });
    try {
        const { fsDriver } = ctx;
        const before = await snapshotFiles(fsDriver);
        if (!before.files.some(f => f.path.toUpperCase() === target)) return { removed: false };
        if (backupDir && !simulate) {
            fs.mkdirSync(backupDir, { recursive: true });
            const head = await volumeHead(fsDriver);
            fs.writeFileSync(path.join(backupDir, 'volume_head.bin'), head.data);
            fs.writeFileSync(path.join(backupDir, 'volume_head.json'), JSON.stringify(head.geometry));
        }
        await fsDriver.delete(target);
        await fsDriver.fatfs.flushMetadataChanges();
        await fsDriver.initFS();
        const after = await snapshotFiles(fsDriver);
        const checked = await verifyVolume(fsDriver, before, after, false, target);
        return { removed: true, filesChecked: checked.filesChecked, simulated: simulate };
    } finally {
        await closeDisc(ctx);
    }
}

const commands = {
    // WRITES A FILE TO THE DISC (unless simulate): stores the JPEG `file` as /COVER.JPG, replacing any earlier picture.
    async cover_set({ file, simulate = false, backupDir = null }) {
        const data = fs.readFileSync(file);
        if (data.length < 100 || data.length > 1500000) throw new Error('The picture must be a JPEG under 1.5 MB (the app shrinks pictures to fit).');
        if (data[0] !== 0xFF || data[1] !== 0xD8) throw new Error('The picture must be a JPEG (the app converts other formats first).');
        const ctx = await openDisc({ simulate });
        try {
            const { fsDriver } = ctx;
            const before = await snapshotFiles(fsDriver);
            const old = before.files.find(f => f.path.toUpperCase() === COVER);
            const space = await fsDriver.statFilesystem(), cs = before.clusterSize;
            const need = Math.ceil(data.length / cs) * cs, back = old ? Math.ceil(old.size / cs) * cs : 0;
            if (need > space.left + back - 4 * cs) throw new Error('There is not enough free space on the disc for the picture.');
            if (backupDir && !simulate) {                   // the part of the volume this changes, to restore by hand if ever needed
                fs.mkdirSync(backupDir, { recursive: true });
                const head = await volumeHead(fsDriver);
                fs.writeFileSync(path.join(backupDir, 'volume_head.bin'), head.data);
                fs.writeFileSync(path.join(backupDir, 'volume_head.json'), JSON.stringify(head.geometry));
            }
            if (old) await fsDriver.delete(COVER);
            const h = await fsDriver.open(COVER, 'rw');
            await h.write(new Uint8Array(data));
            await h.close();
            await fsDriver.initFS();                        // mount again from what is really there (the overlay when simulating)
            const after = await snapshotFiles(fsDriver);
            const checked = await verifyVolume(fsDriver, before, after, true);
            const rh = await fsDriver.open(COVER, 'ro');
            const back2 = Buffer.from(await rh.read(data.length));
            await rh.close();
            if (!back2.equals(data)) throw new Error('Checking the disc afterwards found a problem: the picture does not read back the same.');
            return { stored: data.length, clusters: checked.clusters, replaced: !!old, filesChecked: checked.filesChecked, simulated: simulate, readBack: true,
                     sectorsWouldWrite: simulate ? ctx.overlay.size : undefined };
        } finally {
            await closeDisc(ctx);
        }
    },

    // WRITES A FILE TO THE DISC (unless simulate): stores the CSV `file` as /TRACKS.CSV, replacing the earlier one.
    async tracklist_set({ file, simulate = false, backupDir = null }) {
        const data = fs.readFileSync(file);
        if (data.length < 10 || data.length > 2000000) throw new Error('The track list has an unexpected size.');
        return putRootFile(TRACKLIST, data, 'track list', { simulate, backupDir });
    },

    // WRITES A FILE TO THE DISC (unless simulate): stores the JSON `file` as /LYRICS.TXT (the lyrics of the tracks), replacing the earlier one.
    async lyrics_set({ file, simulate = false, backupDir = null }) {
        const data = fs.readFileSync(file);
        if (data.length < 10 || data.length > 4000000) throw new Error('The lyrics file has an unexpected size.');
        return putRootFile(LYRICS, data, 'lyrics', { simulate, backupDir });
    },

    // WRITES A FILE TO THE DISC (unless simulate): stores the JSON `file` as /GROUPART.JSN (the pictures of the groups), replacing the earlier one.
    async groupart_set({ file, simulate = false, backupDir = null }) {
        const data = fs.readFileSync(file);
        if (data.length < 10 || data.length > 4000000) throw new Error('The group pictures file has an unexpected size.');
        return putRootFile(GROUPART, data, 'group pictures', { simulate, backupDir });
    },

    // WRITES TO THE DISC (unless simulate): removes /GROUPART.JSN.
    async groupart_remove({ simulate = false, backupDir = null }) {
        return removeRootFile(GROUPART, { simulate, backupDir });
    },

    // WRITES A FILE TO THE DISC (unless simulate): stores the JPEG file as /LABEL.JPG, replacing an earlier label.
    async label_set({ file, simulate = false, backupDir = null }) {
        const data = fs.readFileSync(file);
        if (data.length < 100 || data.length > 1500000) throw new Error('The label must be a JPEG under 1.5 MB.');
        if (data[0] !== 0xFF || data[1] !== 0xD8) throw new Error('The label must be a JPEG.');
        return putRootFile(LABEL, data, 'label', { simulate, backupDir });
    },

    // WRITES TO THE DISC (unless simulate): removes /LABEL.JPG.
    async label_remove({ simulate = false, backupDir = null }) {
        return removeRootFile(LABEL, { simulate, backupDir });
    },

    // WRITES TO THE DISC (unless simulate): removes /COVER.JPG.
    async cover_remove({ simulate = false, backupDir = null }) {
        return removeRootFile(COVER, { simulate, backupDir });
    },
    // Read-only: save raw copies of the index files into {dir}.
    async backup({ dir }) {
        const ctx = await openDisc();
        try {
            await backupIndex(ctx.himd, dir);
            return { saved: fs.readdirSync(dir) };
        } finally {
            await closeDisc(ctx);
        }
    },

    // No recorder needed: describe each file and say whether it can be added.
    async inspect({ files }) {
        return files.map(f => {
            try { return describe(f); } catch (e) { return { path: typeof f === 'string' ? f : f.path, error: e.message }; }
        });
    },

    // Read-only dry run: check the files against the disc and report what an upload would do.
    async plan({ files }) {
        const ctx = await openDisc();
        try {
            const { himd } = ctx;
            const infos = files.map(f => { try { return describe(f); } catch (e) { return { path: typeof f === 'string' ? f : f.path, error: e.message }; } });
            for (const i of infos) {                                  // what each file alone needs, so the page can add up only the files that stay ticked
                if (i.error) continue;
                i.need = { byFormat: Object.fromEntries(['auto', 'pcm', 'lp2', 'lp4', 'at3p', 'hisp', 'hilp'].map(k => [k, blocksNeeded(i, k) * himdjs.BLOCK_SIZE])),
                           mp3: Object.fromEntries(MP3_RATES.map(k => [k, blocksNeeded(i, 'mp3', k) * himdjs.BLOCK_SIZE])) };
            }
            const space = await ctx.fsDriver.statFilesystem();
            const needFor = (fmt, kbps) => infos.reduce((n, i) => n + (i.error ? 0 : blocksNeeded(i, fmt, kbps)), 0) * himdjs.BLOCK_SIZE;
            const needMp3 = Object.fromEntries(MP3_RATES.map(k => [k, needFor('mp3', k)]));
            const needByFormat = { auto: needFor('auto'), pcm: needFor('pcm'), mp3: needMp3[192], lp2: needFor('lp2'), lp4: needFor('lp4'), at3p: needFor('at3p'), hisp: needFor('hisp'), hilp: needFor('hilp') };
            const needBytes = needByFormat.auto;
            const fitsIn = v => v < space.left * 0.98;
            const good = infos.filter(i => !i.error);
            return {
                files: infos,
                trackCountNow: himd.getTrackCount(),
                freeBytes: space.left,
                needBytes, needByFormat, needMp3,
                fits: fitsIn(needBytes),
                fitsByFormat: Object.fromEntries(Object.entries(needByFormat).map(([k, v]) => [k, fitsIn(v)])),
                fitsMp3: Object.fromEntries(Object.entries(needMp3).map(([k, v]) => [k, fitsIn(v)])),
                hasWav: infos.some(i => i.kind === 'wav'),
                hasNonMp3: good.some(i => i.kind !== 'mp3'),
                usesSecureSession: good.some(i => i.kind !== 'mp3'),
                note: good.some(i => i.kind !== 'mp3')
                    ? "Anything except MP3 needs the disc's copy-protection session, which renames the disc's data files and rewrites its integrity data."
                    : 'MP3 files add audio to the end of the data file and update the track index only.',
            };
        } finally {
            await closeDisc(ctx);
        }
    },

    // WRITES TO THE DISC. Mirrors Electron RT's prepareUpload / upload / finalizeUpload sequence.
    // format: auto | pcm | mp3 | lp2 | lp4 (see the note above inspectFile); mp3Kbps is used when audio has to be encoded to MP3.
    async upload({ files, simulate = false, format = 'auto', mp3Kbps = 192 }) {
        if (!FORMATS.includes(format)) throw new Error('Unknown format: ' + format);
        if (!MP3_RATES.includes(mp3Kbps)) throw new Error('Unknown MP3 bit rate: ' + mp3Kbps);
        const infos = files.map(describe);                 // throws before touching the disc if a file is bad
        if (simulate && infos.some(i => effectiveFormat(i, format) !== 'mp3')) {
            // Everything except MP3 talks to the recorder's copy-protection chip, which cannot be simulated.
            throw new Error('Simulation only supports MP3 output.');
        }
        const ctx = await openDisc({ simulate });
        let session = null, cryptoWorker = null, atdata = null;
        try {
            const { himd, fsDriver } = ctx;
            const space = await fsDriver.statFilesystem();
            const need = infos.reduce((n, i) => n + blocksNeeded(i, format, mp3Kbps), 0) * himdjs.BLOCK_SIZE;
            if (need >= space.left * 0.98) throw new Error('There is not enough free space on the disc for these files.');
            const atdataPath = '/HMDHIFI/ATDATA' + himd.datanum.toString(16).padStart(2, '0').toUpperCase() + '.HMA';
            let audioBefore = null;
            if (simulate) {
                const h = await fsDriver.open(atdataPath, 'ro');
                audioBefore = Buffer.from(await h.read(8 * himdjs.BLOCK_SIZE));
                await h.close();
            }
            atdata = await openAtdataSafely(himd);
            const startBlocks = atdata.length / himdjs.BLOCK_SIZE;
            for (let n = 0; n < infos.length; n++) {
                const info = infos[n];
                const progress = (done, total, phase) => say({ event: 'progress', file: n, name: path.basename(info.path), done, total, phase });      // phase: 'encrypting' (fast) then 'writing'
                if (needsConversion(info, format)) await say({ event: 'encoding', file: n, name: path.basename(info.path), format: effectiveFormat(info, format) === 'mp3' ? 'mp3' : 'pcm' });
                const src = resolveSource(info, format, mp3Kbps);        // may convert to a temporary file
                const buf = fs.readFileSync(src.file);
                const meta = { title: info.title, artist: info.artist, album: info.album };
                if (src.kind === 'mp3') {
                    const stream = guardStream(new himdjs.HiMDWriteStream(himd, atdata, true), atdata);
                    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
                    await himdjs.uploadMP3Track(himd, stream, ab, meta, o => progress(o.byte, o.totalBytes));
                } else {
                    if (!session) {
                        session = new himdjs.HiMDSecureSession(himd, fsDriver.driver);
                        await session.performAuthentication();
                        const { Worker } = require('worker_threads');
                        const w = new Worker(path.join(RT, 'node_modules', 'himd-js', 'dist', 'node-crypto-worker.js'));
                        cryptoWorker = mod('himd-js/dist/node-crypto-worker').makeAsyncCryptoBlockProvider(w);
                    }
                    let raw, codec;
                    const wavFormat = effectiveFormat(info, format);                // pcm, lp2 or lp4
                    if (wavFormat === 'pcm') {
                        const d = parseWav(buf);
                        raw = new Uint8Array(d.length - (d.length % 4));
                        for (let i = 0; i < raw.length; i += 2) { raw[i] = buf[d.start + i + 1]; raw[i + 1] = buf[d.start + i]; }   // LE -> BE
                        codec = himdjs.generateCodecInfo('PCM', 0);
                    } else if (atrac3.AT3P[wavFormat]) {           // ATRAC3+ (352 / Hi-SP 256 / Hi-LP 64 kbps): the disc stores the frames as they are
                        await say({ event: 'encoding', file: n, name: path.basename(info.path), format: wavFormat });
                        const enc = await atrac3.encodeAtrac3Plus(RT, src.file, wavFormat,       // how far the encode (and the clipping check) has got, for the page's bar
                            p => { Promise.resolve(say({ event: 'encodeProgress', file: n, name: path.basename(info.path), step: p.step, pass: p.pass, frac: p.frac })).catch(() => {}); });
                        raw = new Uint8Array(enc.frames.length);
                        raw.set(enc.frames);
                        codec = himdjs.generateCodecInfo('A3+', enc.frameSize);
                    } else {                                       // LP2 / LP4: encode to ATRAC3 first, the disc stores the frames as they are
                        await say({ event: 'encoding', file: n, name: path.basename(info.path), format: wavFormat });
                        const frames = await atrac3.encodeAtrac3(RT, src.file, wavFormat);
                        raw = new Uint8Array(frames.length);
                        raw.set(frames);
                        codec = himdjs.generateCodecInfo('AT3', atrac3.ATRAC3[wavFormat].frame);
                    }
                    const stream = guardStream(new himdjs.HiMDWriteStream(himd, atdata, true), atdata);
                    await himdjs.uploadStreamingMacDependent(himd, session, stream, raw.buffer, codec, meta, cryptoWorker,
                        o => progress(o.encryptedBytes, o.totalBytes, 'encrypting'), o => progress(o.writtenBytes, o.totalBytes, 'writing'));
                }
            }
            await atdata.close();
            atdata = null;
            await himd.flush();
            if (session) await session.finalizeSession();
            if (simulate) {
                // Re-mount from the overlay and report what the disc would now contain.
                await fsDriver.initFS();
                const sizeOf = async name => fsDriver.getSize('/HMDHIFI/' + name);
                const after = await himdjs.HiMD.init(fsDriver);
                const lbas = [...ctx.overlay.keys()].sort((a, b) => a - b);
                const h2 = await fsDriver.open(atdataPath, 'ro');
                const audioAfter = Buffer.from(await h2.read(8 * himdjs.BLOCK_SIZE));
                await h2.close();
                const atdataBytes = await sizeOf(atdataPath.split('/').pop());
                return {
                    simulated: true, added: infos.length, sectorsWouldWrite: lbas.length,
                    blocksBefore: startBlocks, blocksAfter: atdataBytes / himdjs.BLOCK_SIZE,
                    firstAudioBlocksUnchanged: audioBefore.equals(audioAfter),
                    atdataBytes,
                    tracksAfter: himdjs.getAllTracks(after).map(t => ({ index: t.index, title: t.title, codec: t.encoding, seconds: t.duration })),
                    lastTrackFragment: (() => {
                        const slot = after.trackIndexToTrackSlot(after.getTrackCount() - 1);
                        let f = after.getTrack(slot).firstFragment, chain = [];
                        while (f) { const fr = after.getFragment(f); chain.push({ first: fr.firstBlock, last: fr.lastBlock }); f = fr.nextFragment; }
                        return chain;
                    })(),
                };
            }
            return { added: infos.length };
        } finally {
            try { cryptoWorker && cryptoWorker.close(); } catch (e) { /* worker already gone */ }
            try { atdata && await atdata.close(); } catch (e) { /* surfaced by the main error if any */ }
            await closeDisc(ctx);
        }
    },


    // WRITES TO THE DISC. Writes ATRAC / ATRAC3+ frames as new tracks exactly as given, with the codec fields of the track they came
    // from: a lossless split or join, nothing is decoded or encoded. files: [{frames: path of a file of whole frames, codecId,
    // codecInfo: the 5 codec bytes as hex, title, artist, album}].
    async upload_frames({ files }) {
        const codecs = mod('himd-js/dist/codecs');
        const items = files.map(f => {
            if (!f.frames || !fs.existsSync(f.frames)) throw new Error('A frames file is missing.');
            if (![0, 1].includes(f.codecId) || !/^[0-9a-fA-F]{10}$/.test(String(f.codecInfo))) throw new Error('Unknown codec details for ' + (f.title || 'a track') + '.');
            const codec = { codecId: f.codecId, codecInfo: Uint8Array.from(Buffer.from(f.codecInfo, 'hex')) };
            if (codecs.getCodecName(codec) === 'MP3') throw new Error('Only ATRAC audio can be written this way.');
            const skip = Number.isInteger(f.skip) && f.skip >= 0 ? f.skip : 0;          // a header to ignore (the 96-byte EA3 header of a saved .oma file)
            const frame = codecs.getBytesPerFrame(codec), bytes = fs.statSync(f.frames).size - skip;
            if (!frame || !bytes || bytes % frame !== 0) throw new Error('The audio for ' + (f.title || 'a track') + ' is not a whole number of frames.');
            return { ...f, codec, frame, bytes, skip, blocks: Math.ceil(bytes / frame / Math.floor((himdjs.HIMD_AUDIO_SIZE - 1) / frame)) };
        });
        const ctx = await openDisc();
        let session = null, cryptoWorker = null, atdata = null;
        try {
            const { himd, fsDriver } = ctx;
            const space = await fsDriver.statFilesystem();
            if (items.reduce((n, i) => n + i.blocks, 0) * himdjs.BLOCK_SIZE >= space.left * 0.98) throw new Error('There is not enough free space on the disc for these tracks.');
            atdata = await openAtdataSafely(himd);
            session = new himdjs.HiMDSecureSession(himd, fsDriver.driver);
            await session.performAuthentication();
            const { Worker } = require('worker_threads');
            const w = new Worker(path.join(RT, 'node_modules', 'himd-js', 'dist', 'node-crypto-worker.js'));
            cryptoWorker = mod('himd-js/dist/node-crypto-worker').makeAsyncCryptoBlockProvider(w);
            for (let n = 0; n < items.length; n++) {
                const it = items[n];
                const progress = (done, total) => say({ event: 'progress', file: n, name: it.title || path.basename(it.frames), done, total });
                const buf = fs.readFileSync(it.frames).subarray(it.skip);
                const raw = new Uint8Array(buf.length);
                raw.set(buf);
                const stream = guardStream(new himdjs.HiMDWriteStream(himd, atdata, true), atdata);
                await himdjs.uploadStreamingMacDependent(himd, session, stream, raw.buffer, it.codec,
                    { title: it.title, artist: it.artist, album: it.album }, cryptoWorker,
                    o => progress(o.encryptedBytes, o.totalBytes), o => progress(o.writtenBytes, o.totalBytes));
            }
            await atdata.close();
            atdata = null;
            await himd.flush();
            await session.finalizeSession();
            return { added: items.length };
        } finally {
            try { cryptoWorker && cryptoWorker.close(); } catch (e) { /* worker already gone */ }
            try { atdata && await atdata.close(); } catch (e) { /* surfaced by the main error if any */ }
            await closeDisc(ctx);
        }
    },

    // WRITES TO THE DISC (unless simulate). Deletes tracks by 0-based position. MP3 tracks have no entry in the
    // disc's signed MAC list, so no copy-protection session is needed. PCM and ATRAC tracks (including the
    // recorder's own recordings) do, and are refused unless allowSecure is set: a secure session then zeroes
    // their entries and re-signs the list. That path talks to the recorder's chip, so simulate rehearses only
    // the filesystem part.
    async delete({ indexes, simulate = false, allowSecure = false, backupDir = null }) {
        const ctx = await openDisc({ simulate });
        try {
            const { himd, fsDriver } = ctx;
            const count = himd.getTrackCount();
            const wanted = [...new Set(indexes)].sort((a, b) => a - b);
            if (!wanted.length) throw new Error('No tracks were selected.');
            const secureSlots = [];
            for (const i of wanted) {
                if (!Number.isInteger(i) || i < 0 || i >= count) throw new Error('There is no track ' + (i + 1) + ' on the disc.');
                const slot = himd.trackIndexToTrackSlot(i);
                const codec = himdjs.getCodecName(himd.getTrack(slot));
                if (codec === 'MP3') continue;
                if (!allowSecure || !['PCM', 'A3+', 'AT3'].includes(codec)) {
                    throw new Error('Track ' + (i + 1) + ' is a ' + codec + ' track. Deleting it is not allowed here. Nothing was deleted.');
                }
                secureSlots.push(slot);
            }
            const spaceBefore = await fsDriver.statFilesystem();
            let session = null;
            if (secureSlots.length && backupDir) await backupIndex(himd, backupDir);
            if (secureSlots.length && !simulate) {
                session = new himdjs.HiMDSecureSession(himd, fsDriver.driver);
                await session.performAuthentication();
            }
            await himdjs.deleteTracks(himd, wanted);          // frees the clusters, fixes block numbers, writes the index
            if (session) {
                for (const slot of secureSlots) session.allMacs.set(new Uint8Array(8), (slot - 1) * 8);
                await session.finalizeSession();
            }
            if (!simulate) return { deleted: wanted.length, secure: secureSlots.length > 0 };
            await fsDriver.initFS();
            const after = await himdjs.HiMD.init(fsDriver);
            const spaceAfter = await fsDriver.statFilesystem();
            return {
                simulated: true, deleted: wanted.length, freedBytes: spaceAfter.left - spaceBefore.left,
                tracksAfter: himdjs.getAllTracks(after).map(t => ({ index: t.index, title: t.title, codec: t.encoding, seconds: t.duration })),
                sectorsWouldWrite: ctx.overlay.size,
            };
        } finally {
            await closeDisc(ctx);
        }
    },

    // Read-only: writes one track (by 0-based position) to a local WAV (PCM, or ATRAC decoded by ffmpeg) or MP3 file so the app can play it.
    // PCM is decrypted in software with the key stored on the disc; no copy-protection session is involved.
    // The file grows as blocks arrive; for PCM it is padded to the size its header declares. A line
    // containing "stop" on stdin ends the read cleanly between blocks.
    // exact: write the true length (a saved file) instead of padding to the promised length (a file being played).
    // raw: for ATRAC tracks, keep the original ATRAC data (an OMA file) instead of decoding it.
    // startByte: a seek while playing. Reading restarts at the block holding that byte of the WAV (PCM and ATRAC only) and is
    // written to the same, already started file at the same place; a 'start' event reports where the new part begins ('lo').
    async dump({ index, out, exact = false, raw = false, startByte = 0 }) {
        let stop = false;
        process.stdin.on('data', d => { if (String(d).includes('stop')) stop = true; });
        process.stdin.resume();
        const ctx = await openDisc();
        let fd = null;
        try {
            const { himd } = ctx;
            if (!Number.isInteger(index) || index < 0 || index >= himd.getTrackCount()) throw new Error('There is no track ' + (index + 1) + ' on the disc.');
            const slot = himd.trackIndexToTrackSlot(index);
            const codec = himdjs.getCodecName(himd.getTrack(slot));
            const atrac = codec === 'A3+' || codec === 'AT3';
            if (!atrac && codec !== 'PCM' && codec !== 'MP3') throw new Error('Cannot play ' + codec + ' tracks.');
            let startBlock = 0;
            if (startByte > 44 && !exact && !raw && (atrac || codec === 'PCM')) {
                const codecs = mod('himd-js/dist/codecs'), t = himd.getTrack(slot);
                const perBlock = codec === 'PCM' ? 0x3fc0 : Math.floor(0x3fc0 / codecs.getBytesPerFrame(t)) * codecs.getSamplesPerFrame(t) * 4;
                startBlock = Math.floor((startByte - 44) / perBlock);
            }
            const dump = startBlock > 0 ? { data: dumpFrom(himd, slot, startBlock) } : himdjs.dumpTrack(himd, slot);
            if (atrac && !raw) return await streamAtrac(ctx, himd.getTrack(slot), dump, out, () => stop, exact, 'oma', startBlock);
            if (codec === 'MP3' && !exact) return await streamAtrac(ctx, himd.getTrack(slot), dump, out, () => stop, false, 'mp3');   // playing: start at once
            fd = fs.openSync(out, startBlock > 0 ? 'r+' : 'w');
            let written = 0, first = true, declared = 0, blocksRead = 0, lastReport = 0;
            for await (const chunk of dump.data) {
                if (blocksRead > 0 && Date.now() - lastReport > 250) { lastReport = Date.now(); await say({ event: 'progress', done: blocksRead, total: chunk.total, hi: written }); }
                blocksRead++;
                if (first) {
                    first = false;
                    if (codec === 'PCM') {
                        declared = chunk.total * 0x3fc0;                     // every block carries 16,320 bytes of audio
                        if (startBlock === 0) {
                            const h = Buffer.alloc(44);
                            h.write('RIFF', 0); h.writeUInt32LE(36 + declared, 4); h.write('WAVEfmt ', 8); h.writeUInt32LE(16, 16);
                            h.writeUInt16LE(1, 20); h.writeUInt16LE(2, 22); h.writeUInt32LE(44100, 24); h.writeUInt32LE(176400, 28);
                            h.writeUInt16LE(4, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(declared, 40);
                            fs.writeSync(fd, h, 0, 44, 0);
                        }
                        written = 44 + startBlock * 0x3fc0;                  // a seek continues where its block belongs
                        await say({ event: 'start', progressive: true, totalBytes: 44 + declared, format: 'wav', lo: written });
                        continue;
                    }
                }
                if (stop) throw new Error('stopped');
                const buf = Buffer.from(chunk.data.buffer, chunk.data.byteOffset, chunk.data.byteLength);
                fs.writeSync(fd, buf, 0, buf.length, written); written += buf.length;
            }
            if (codec === 'PCM' && exact) {                                          // a saved file: true length, header patched to match
                const sz = Buffer.alloc(4);
                sz.writeUInt32LE(written - 8); fs.writeSync(fd, sz, 0, 4, 4);
                sz.writeUInt32LE(written - 44); fs.writeSync(fd, sz, 0, 4, 40);
                return { bytes: written, format: 'wav' };
            }
            if (codec === 'PCM' && written < 44 + declared) { const pad = Buffer.alloc(44 + declared - written); fs.writeSync(fd, pad, 0, pad.length, written); }
            return { bytes: codec === 'PCM' ? 44 + declared : written, format: atrac ? 'oma' : codec === 'PCM' ? 'wav' : 'mp3', hi: codec === 'PCM' ? 44 + declared : written };
        } finally {
            if (fd !== null) fs.closeSync(fd);
            if (!ctx.closed) await closeDisc(ctx);
        }
    },

    // WRITES TO THE DISC: erases everything and sets up a fresh Hi-MD volume (the recorder's own "reformat" command through
    // himd-js). Works on a disc whose file system is missing or damaged, so the disc is not mounted first. Afterwards it is
    // mounted again to check that it is a valid, empty Hi-MD disc.
    async format() {
        const ids = himdjs.DevicesIds.filter(d => d.vendorId === 0x054c).map(d => ({ vendorId: d.vendorId, productId: d.deviceId }));
        const webusb = new WebUSB({ allowedDevices: ids, deviceTimeout: 10000000 });
        const device = await webusb.requestDevice({ filters: ids });
        await device.open();
        const fsDriver = new himdjs.UMSCHiMDFilesystem(device);
        let timer;
        try {
            await fsDriver.driver.init();
            const limit = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('The recorder did not finish formatting within 15 minutes.')), 15 * 60 * 1000); });
            await Promise.race([fsDriver.wipeDisc(true), limit]);                // the reformat command, then mounts the new volume
            const himd = await himdjs.HiMD.init(fsDriver);
            const tracks = himd.getTrackCount();
            if (tracks !== 0) throw new Error('The disc was formatted but still lists ' + tracks + ' tracks.');
            return { tracks, space: await fsDriver.statFilesystem() };
        } finally {
            clearTimeout(timer);
            try { await fsDriver.driver.close(); } catch (e) { /* already closed */ }
        }
    },

    // Read-only: mount the disc with himd-js and list what it sees.
    async list() {
        const ctx = await openDisc();
        try {
            const { himd } = ctx;
            const tracks = himdjs.getAllTracks(himd);
            return {
                device: himd.getDeviceName(),
                discTitle: himd.getDiscTitle(),
                trackCount: himd.getTrackCount(),
                tracks: tracks.map(t => ({ index: t.index, title: t.title, artist: t.artist, codec: t.encoding, kbps: t.bitrate, seconds: t.duration })),
                space: await ctx.fsDriver.statFilesystem(),
            };
        } finally {
            await closeDisc(ctx);
        }
    },
};

(async () => {
    const [cmd, argJson] = process.argv.slice(2);
    if (!commands[cmd]) {
        await say({ error: 'Unknown command: ' + cmd });
        process.exit(2);
    }
    try {
        const result = await commands[cmd](argJson ? JSON.parse(argJson) : {});
        await say({ result });
        process.exit(0);
    } catch (e) {
        await say({ error: String(e && e.message || e) });
        process.exit(1);
    }
})();

