// Standard MiniDisc (NetMD protocol) helper, run on the bundled Node (..\runtime\node.exe) with netmd-js.
// Usage: netmd_helper.js <command> [json-args]
// Output: one JSON object per line on stdout ({"event":...} progress lines, then {"result":...} or {"error":...}).
const path = require('path');

const RT = process.env.HIMD_RUNTIME || path.join(__dirname, '..', 'runtime');
// A program from the runtime folder: runtime\name.exe on Windows (as always). On Linux and macOS runtime/name when it is there,
// else the system's own copy (found on PATH), e.g. ffmpeg from the package manager. A missing program gives the runtime path,
// so the 'missing (path)' messages still say where it was looked for.
const onPath = name => {                     // full path of a program on PATH (like `which`), or null
    for (const dir of (process.env.PATH || '').split(path.delimiter)) {
        const f = path.join(dir, name);
        try { require('fs').accessSync(f, require('fs').constants.X_OK); return f; } catch (e) { /* not here */ }
    }
    return null;
};
const BIN = name => {
    const exe = path.join(RT, name + (process.platform === 'win32' ? '.exe' : ''));
    return process.platform === 'win32' || require('fs').existsSync(exe) ? exe : (onPath(name) || exe);
};
const mod = name => require(path.join(RT, 'node_modules', name));

const { WebUSB } = mod('usb');
const netmd = mod('netmd-js');
const fs = require('fs');
const { Worker } = require('worker_threads');
const { parseWav } = require('./wav');
const atrac3 = require('./atrac3');

const say = obj => new Promise(resolve => process.stdout.write(JSON.stringify(obj) + '\n', resolve));

async function openDevice() {
    const ids = netmd.DevicesIds.map(d => ({ vendorId: d.vendorId, productId: d.deviceId }));
    const webusb = new WebUSB({ allowedDevices: ids, deviceTimeout: 10000000 });
    const iface = await netmd.openNewDevice(webusb);
    if (!iface) throw new Error('No NetMD recorder found. Put a standard MiniDisc in the recorder and reconnect it.');
    return iface;
}

const ENCODINGS = { 0x90: 'SP', 0x92: 'LP2', 0x93: 'LP4' };

// The download firmware patch (from the open-source netmd-exploits library, GPL-2.0) is only used on the Hi-MD recorder families
// the library has its addresses for: Hn1.000-1.200 (MZ-NH*) and Hr1.000 (MZ-RH10/RH910). Tried here on an MZ-NH700 (Hn1.100) only.
// It lives in the recorder's RAM and patch registers (nothing is written to flash or to the disc); unplugging the recorder clears it.
const EXPLOIT_FAMILY = /^H[nr]1\./;
const FIRST_LOAD_SECTORS = Number(process.env.MDM_FIRST_LOAD || 600);   // sectors in the first read when playing (0: the library's own size)

// Reads a whole track from a standard disc with the patch loaded. Returns {data, extension}: 'aea' (SP, ATRAC1) or 'wav' (LP2/LP4).
// A line "stop" on stdin ends the read between sectors. The patches are always taken out again afterwards.
async function exploitOpen(iface) {
    const ex = mod('netmd-exploits');
    const factory = await iface.factory();
    const trace = [];
    const esm = await ex.ExploitStateManager.create(iface, factory, { log: (tag, text) => trace.push(tag + ': ' + text) });
    const code = esm.device.versionCode;
    const Cls = ex.getBestSuited(ex.AtracRecovery, esm.device);
    if (!EXPLOIT_FAMILY.test(code) || !Cls) throw new Error('This recorder (firmware ' + code + ') is not one the download patch has been checked on, so the app will not use it.');
    return { esm, Cls, trace };
}

// Puts the recorder back to normal commands and takes every patch out again (the permanent one stays until the recorder is unplugged).
async function exploitClose(iface, esm, exploit) {
    try { if (exploit) await exploit.finishDownload(); } catch (e) { /* normal commands again, best effort */ }
    try { await iface.stop(); } catch (e) { /* not playing */ }
    for (const c of esm.getCurrentlyLoaded()) {
        try { await esm.unload(c); } catch (e) { /* permanent */ }
    }
}

async function fetchViaExploit(iface, index) {
    const { esm, Cls, trace } = await exploitOpen(iface);
    let stop = false;
    process.stdin.on('data', d => { if (String(d).includes('stop')) stop = true; });
    process.stdin.resume();
    let exploit = null;
    try {
        try { await iface.stop(); } catch (e) { /* already stopped */ }
        try { await makeIdle(iface); } catch (e) { /* the download below reports a recorder that stays busy */ }       // not while the drive is still settling from the last track
        exploit = await esm.require(Cls);
        const result = await exploit.downloadTrack(index, p => { say({ event: 'progress', done: p.read, total: p.total, action: p.action }); },
            { shouldCancelImmediately: () => stop });
        if (stop) throw new Error('stopped');
        if (!result.data || !result.data.length) throw new Error('The recorder returned no audio. ' + trace.slice(-3).join(' | '));
        return result;
    } finally {
        await exploitClose(iface, esm, exploit);
        await new Promise(r => setTimeout(r, 3000));      // let the drive stop and park before anything else is asked of it
    }
}

// Read-only: what the recorder is and what is on the standard disc.
async function listDisc(iface) {
    let name = null;
    try { name = await iface.netMd.getDeviceName(); } catch (e) { /* name is only informative */ }
    const status = await netmd.getDeviceStatus(iface);
    if (status && status.discPresent === false) {                // an empty recorder rejects the "list contents" command: report "no disc" instead
        return { device: name, firmware: null, status, discTitle: '', writeProtected: false, writable: true, used: 0, left: 0, total: 0, trackCount: 0, groups: [], rawTitle: null, rawTitleW: null };
    }
    const content = await netmd.listContent(iface);
    const groups = content.groups.map(g => ({
        title: g.title, index: g.index,
        tracks: g.tracks.map(t => ({ index: t.index, title: t.title, mono: t.channel === 1, codec: ENCODINGS[t.encoding] || '?', seconds: Math.round(t.duration / UNITS_PER_SECOND) })),
    }));
    let rawTitle = null, rawTitleW = null;                    // the disc title as stored, with the group ranges in it ("0;Disc//1-3;Group//")
    try { rawTitle = await iface._getDiscTitle(false); rawTitleW = await iface._getDiscTitle(true); } catch (e) { /* only used when cloning */ }
    let firmware = null;                                       // e.g. Hn1.100: the firmware the recorder reports (read-only question)
    try {
        const factory = await iface.factory();
        let timer; const limit = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error('timeout')), 4000); });
        firmware = await Promise.race([netmd.getDescriptiveDeviceCode(factory), limit]); clearTimeout(timer);
    } catch (e) { /* only informative */ }
    return { device: name, firmware, status, discTitle: content.title, writeProtected: content.writeProtected, writable: content.writable,
             used: content.used, left: content.left, total: content.total, trackCount: content.trackCount, groups, rawTitle, rawTitleW };
}

// ---------------------------------------------------------------------------
// Source files. A 16-bit 44.1 kHz stereo WAV is sent as PCM and the recorder itself encodes it to SP ATRAC.
// Other formats (MP3, FLAC, ...) are first decoded to such a WAV with the bundled ffmpeg.
// Sending PCM runs at about real-time speed; an SP disc holds 512 units per second of audio.
// ---------------------------------------------------------------------------
const UNITS_PER_SECOND = 512;
const os = require('os');

// NetMD titles are plain text; keep letters/digits/punctuation the recorder accepts and drop the rest.
const cleanTitle = s => String(s || '').normalize('NFKD').replace(/[^\x20-\x7e]/g, '').replace(/\s+/g, ' ').trim().slice(0, 120);

function convertToWav(file) {
    const exe = BIN('ffmpeg');
    if (!fs.existsSync(exe)) throw new Error('The bundled decoder is missing, so only .wav files can be added.');
    const out = path.join(os.tmpdir(), 'mdm-' + process.pid + '-' + Math.random().toString(36).slice(2) + '.wav');
    try {
        require('child_process').execFileSync(exe, ['-hide_banner', '-loglevel', 'error', '-y', '-i', file, '-vn', '-ar', '44100', '-ac', '2',
            '-acodec', 'pcm_s16le', '-f', 'wav', out], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
    } catch (e) {
        try { fs.unlinkSync(out); } catch (x) { /* nothing was written */ }
        throw new Error('Could not read ' + path.basename(file) + ' as audio.');
    }
    return out;
}

// Returns what we know about a file without touching the recorder. Call release() when done with it.
// Title / artist / album from the tags of any audio file ffmpeg can open (FLAC, M4A, OGG, Opus, WMA, WAV, AIFF...). Empty strings when there are none.
function ffmpegTags(file) {
    const none = { title: '', artist: '', album: '' };
    const run = extra => {                                         // the tags as ffmpeg's "ffmetadata" text, parsed into {lower-case name: value}
        const out = require('child_process').execFileSync(BIN('ffmpeg'), ['-hide_banner', '-loglevel', 'error', '-i', file, '-vn', ...extra, '-f', 'ffmetadata', '-'],
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

// Title / artist / album from the tags of the file: ID3 for an MP3, otherwise read through ffmpeg (empty strings if the tag is missing or unreadable).
function readTags(file) {
    if (/\.mp3$/i.test(file)) {
        try {
            const t = mod('node-id3').read(file) || {};
            return { title: String(t.title || '').trim(), artist: String(t.artist || '').trim(), album: String(t.album || '').trim() };
        } catch (e) { /* fall through to ffmpeg */ }
    }
    return ffmpegTags(file);
}

function inspect(f) {
    const file = typeof f === 'string' ? f : f.path;
    const isWav = /\.wav$/i.test(file);
    const wavPath = isWav ? file : convertToWav(file);
    const release = () => { if (!isWav) { try { fs.unlinkSync(wavPath); } catch (e) { /* already gone */ } } };
    try {
        const buf = fs.readFileSync(wavPath);
        const data = parseWav(buf);
        const title = cleanTitle((typeof f === 'object' && f.title) || path.basename(file, path.extname(file)));
        return { path: file, wavPath, kind: path.extname(file).slice(1).toLowerCase() || 'audio', bytes: fs.statSync(file).size, buf, data, title,
                 seconds: data.length / 176400, release };
    } catch (e) {
        release();
        throw e;
    }
}

// Disc formats. SP is sent as PCM and encoded by the recorder. LP2 and LP4 are encoded here with atracdenc (ATRAC3) and the
// recorder just stores the frames; each uses half / a quarter of the disc space per second of audio.
const FORMATS = {
    sp: { divisor: 1 },
    lp2: { divisor: 2, bitrate: '128', frame: 384, wire: () => netmd.Wireformat.lp2 },
    lp4: { divisor: 4, bitrate: '64', frame: 192, wire: () => netmd.Wireformat.lp4 },
};
// The ATRAC3 frames inside a .wav the recorder sent back (a WAV header, then the 'data' chunk). `frame` is 384 (LP2) or 192 (LP4) bytes.
function atrac3Frames(file, frame) {
    const buf = fs.readFileSync(file);
    if (buf.length < 12 || buf.toString('latin1', 0, 4) !== 'RIFF' || buf.toString('latin1', 8, 12) !== 'WAVE') throw new Error('The saved LP audio is not a WAV file.');
    let pos = 12;
    while (pos + 8 <= buf.length) {
        const id = buf.toString('latin1', pos, pos + 4), size = buf.readUInt32LE(pos + 4);
        if (id === 'data') {
            const data = buf.subarray(pos + 8, Math.min(buf.length, pos + 8 + size));
            if (!data.length || data.length % frame) throw new Error('The saved LP audio is not a whole number of ' + frame + '-byte frames.');
            return data;
        }
        pos += 8 + size + (size & 1);
    }
    throw new Error('The saved LP audio has no data chunk.');
}

const MAX_LP_SECONDS = 90 * 60;      // atracdenc runs in WebAssembly memory; an 80-minute file was tested (27 s), longer ones are not tried

// The library waits for the recorder to be idle before it sends audio, and waits forever if it is playing or paused
// (for example after the remote control was used). So stop it first, and give up with a clear message if it stays busy.
async function makeIdle(iface) {
    let st = await netmd.getDeviceStatus(iface);
    if (['playing', 'paused', 'fastForward', 'rewind'].includes(st.state)) {
        try { await iface.stop(); } catch (e) { /* the check below reports it */ }
    }
    for (let i = 0; i < 40; i++) {                      // up to about 10 seconds
        st = await netmd.getDeviceStatus(iface);
        if (st.state === 'ready' || st.state === 'discBlank') return;
        await new Promise(r => setTimeout(r, 250));
    }
    throw new Error('The recorder is busy (' + st.state + '). Press stop on the recorder, then try again.');
}

// A standard-disc recorder usually cannot send audio back, so the app keeps its own FLAC copy of every track it adds
// and plays that. Returns {id, title, seconds}, or null if the copy could not be made (the upload itself is not affected).
function saveCopy(info, copyDir) {
    try {
        const exe = BIN('ffmpeg');
        if (!copyDir || !fs.existsSync(exe)) return null;
        fs.mkdirSync(copyDir, { recursive: true });
        const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
        require('child_process').execFileSync(exe, ['-hide_banner', '-loglevel', 'error', '-y', '-i', info.wavPath, '-vn', '-c:a', 'flac',
            path.join(copyDir, id + '.flac')], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
        return { id, title: info.title, seconds: Math.round(info.seconds) };
    } catch (e) {
        return null;
    }
}

const commands = {
    // Read-only. What the recorder is and what is on the standard disc.
    async list() {
        return await listDisc(await openDevice());
    },

    // Read-only dry run: do the files fit? Problems are reported per file so one bad file does not hide the others.
    async plan({ files }) {
        const out = [];
        let needUnits = 0;
        for (const f of files) {
            try {
                const i = inspect(f);
                i.release();
                const tags = readTags(i.path);                  // MP3 ID3 tags: the title replaces the file name, the artist is kept for "Artist - Title"
                out.push({ path: i.path, kind: i.kind, bytes: i.bytes, seconds: Math.round(i.seconds), title: cleanTitle(tags.title || i.title), artist: tags.artist, album: tags.album });
                needUnits += Math.ceil(i.seconds * UNITS_PER_SECOND);
            } catch (e) {
                out.push({ path: typeof f === 'string' ? f : f.path, error: e.message });
            }
        }
        const disc = await listDisc(await openDevice());
        const left = Object.fromEntries(Object.entries(FORMATS).map(([k, f]) => [k, Math.floor(disc.left * f.divisor / UNITS_PER_SECOND)]));   // seconds of audio that fit, per format
        const needSeconds = Math.ceil(needUnits / UNITS_PER_SECOND);
        return {
            netmd: true, files: out, trackCountNow: disc.trackCount, secondsLeft: left.sp, leftSeconds: left,
            needSeconds, fits: needSeconds <= left.sp && !disc.writeProtected, writeProtected: disc.writeProtected,
            lpMaxSeconds: MAX_LP_SECONDS,
            note: 'In SP the recorder encodes the audio while it receives it, so adding takes about as long as the audio plays. LP2 and LP4 are encoded on the PC first (a few seconds) and then sent.',
        };
    },

    // WRITES TO THE DISC. Adds audio files as stereo tracks in the given format ('sp', 'lp2' or 'lp4').
    async upload({ files, copyDir = null, format = 'sp' }) {
        const infos = [], copies = [];
        const fmt = FORMATS[format];
        if (!fmt) throw new Error('Unknown format: ' + format);
        try {
            for (const f of files) infos.push(inspect(f));   // throws before touching the recorder if a file is bad
            if (format !== 'sp') {
                const long = infos.find(i => i.seconds > MAX_LP_SECONDS);
                if (long) throw new Error(path.basename(long.path) + ' is longer than ' + MAX_LP_SECONDS / 60 + ' minutes, which is too long to encode as ' + format.toUpperCase() + '. Use SP or split the file.');
            }
            const iface = await openDevice();
            const disc = await listDisc(iface);
            if (disc.writeProtected) throw new Error('The disc is write-protected.');
            await makeIdle(iface);
            const need = infos.reduce((n, i) => n + Math.ceil(i.seconds * UNITS_PER_SECOND / fmt.divisor), 0);
            if (need > disc.left) throw new Error('There is not enough space on the disc for these files in ' + format.toUpperCase() + '.');
            for (let n = 0; n < infos.length; n++) {
                const info = infos[n];
                let wire, raw;
                if (format === 'sp') {
                    wire = netmd.Wireformat.pcm;
                    const len = info.data.length - (info.data.length % 4);
                    raw = new Uint8Array(len);                  // WAV samples are little-endian, NetMD PCM is big-endian
                    for (let i = 0; i < len; i += 2) { raw[i] = info.buf[info.data.start + i + 1]; raw[i + 1] = info.buf[info.data.start + i]; }
                } else {
                    await say({ event: 'encoding', file: n, name: path.basename(info.path), format });
                    const frames = await atrac3.encodeAtrac3(RT, info.wavPath, format);
                    wire = fmt.wire();
                    raw = new Uint8Array(frames.length);
                    raw.set(frames);
                }
                info.buf = null;
                const worker = new Worker(path.join(RT, 'node_modules', 'netmd-js', 'dist', 'node-encrypt-worker.js'));
                try {
                    const iterator = mod('netmd-js/dist/node-encrypt-worker').makeGetAsyncPacketIteratorOnWorkerThread(worker);
                    const track = new netmd.MDTrack(info.title, wire, raw.buffer, 0x400, '', iterator);
                    await netmd.download(iface, track, p => say({ event: 'progress', file: n, name: path.basename(info.path), done: p.writtenBytes, total: p.totalBytes }));
                } finally {
                    await worker.terminate();
                }
                const copy = saveCopy(info, copyDir);               // only after the track is safely on the disc
                if (copy) copies.push(copy);
            }
            return { added: infos.length, copies, copiesMissing: infos.length - copies.length };
        } finally {
            infos.forEach(i => i.release());
        }
    },
    // WRITES TO THE DISC. Clone: writes tracks that were read off another standard disc (fetch with raw: true), in order.
    // tracks: [{title, codec: 'SP' | 'LP2' | 'LP4', file, kind: 'aea' | 'atrac3wav', seconds}]. SP: the ATRAC1 audio is decoded and sent as
    // PCM, so the recorder encodes it as SP again (one more generation; a mono track becomes stereo). LP2 / LP4: the ATRAC3 frames are
    // sent exactly as they were, nothing is decoded or encoded. rawTitle / rawTitleW: the source disc's titles as stored (they carry
    // the group ranges), written at the end so the disc name and the groups come across too.
    async upload_clone({ tracks, rawTitle = null, rawTitleW = null }) {
        for (const t of tracks) {
            if (t.codec === 'SP' ? t.kind !== 'aea' : !(FORMATS[t.codec.toLowerCase()] && t.kind === 'atrac3wav')) throw new Error('Track "' + t.title + '" is not in a format that can be written back.');
            if (!fs.existsSync(t.file)) throw new Error('The saved audio for "' + t.title + '" is missing.');
        }
        const unitsFor = t => Math.ceil(t.seconds * UNITS_PER_SECOND / (t.codec === 'SP' ? 1 : FORMATS[t.codec.toLowerCase()].divisor));
        const iface = await openDevice();
        const disc = await listDisc(iface);
        if (disc.writeProtected) throw new Error('The disc is write-protected.');
        if (disc.trackCount !== 0) throw new Error('The disc is not empty.');
        const need = tracks.reduce((n, t) => n + unitsFor(t), 0);
        if (need * 1.01 + 2 * UNITS_PER_SECOND > disc.left) throw new Error('The saved tracks do not fit on this disc.');
        await makeIdle(iface);
        for (let n = 0; n < tracks.length; n++) {
            const t = tracks[n], name = t.title;
            let wire, raw, temp = null;
            try {
                if (t.codec === 'SP') {
                    temp = path.join(os.tmpdir(), 'mdm-clone-' + process.pid + '-' + n + '.wav');
                    await say({ event: 'encoding', file: n, name, format: 'decode' });
                    require('child_process').execFileSync(BIN('ffmpeg'), ['-hide_banner', '-loglevel', 'error', '-y', '-i', t.file, '-vn', '-ar', '44100', '-ac', '2',
                        '-acodec', 'pcm_s16le', '-f', 'wav', temp], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
                    const buf = fs.readFileSync(temp), d = parseWav(buf);
                    const len = d.length - (d.length % 4);
                    if (Math.abs(len / 176400 - t.seconds) > 3) throw new Error('"' + name + '" decoded to ' + Math.round(len / 176400) + ' s, not the ' + t.seconds + ' s on the disc.');
                    raw = new Uint8Array(len);                          // WAV samples are little-endian, NetMD PCM is big-endian
                    for (let i = 0; i < len; i += 2) { raw[i] = buf[d.start + i + 1]; raw[i + 1] = buf[d.start + i]; }
                    wire = netmd.Wireformat.pcm;
                } else {
                    const f = FORMATS[t.codec.toLowerCase()];
                    const frames = atrac3Frames(t.file, f.frame);
                    const secs = frames.length / f.frame * 1024 / 44100;
                    if (Math.abs(secs - t.seconds) > 3) throw new Error('"' + name + '" holds ' + Math.round(secs) + ' s of audio, not the ' + t.seconds + ' s on the disc.');
                    raw = new Uint8Array(frames.length);
                    raw.set(frames);
                    wire = f.wire();
                }
                const worker = new Worker(path.join(RT, 'node_modules', 'netmd-js', 'dist', 'node-encrypt-worker.js'));
                try {
                    const iterator = mod('netmd-js/dist/node-encrypt-worker').makeGetAsyncPacketIteratorOnWorkerThread(worker);
                    const track = new netmd.MDTrack(cleanTitle(name), wire, raw.buffer, 0x400, '', iterator);
                    await netmd.download(iface, track, p => say({ event: 'progress', file: n, name, done: p.writtenBytes, total: p.totalBytes }));
                } finally {
                    await worker.terminate();
                }
            } finally {
                if (temp) { try { fs.unlinkSync(temp); } catch (e) { /* already gone */ } }
            }
        }
        if (rawTitle) await iface.setDiscTitle(rawTitle);
        if (rawTitleW) await iface.setDiscTitle(rawTitleW, true);
        return { added: tracks.length };
    },

    // WRITES TO THE DISC. Erases tracks by 0-based position (highest first, so the numbers stay valid).
    async delete({ indexes }) {
        const iface = await openDevice();
        const disc = await listDisc(iface);
        if (disc.writeProtected) throw new Error('The disc is write-protected.');
        const wanted = [...new Set(indexes)].sort((a, b) => b - a);
        if (!wanted.length) throw new Error('No tracks were selected.');
        for (const i of wanted) if (!Number.isInteger(i) || i < 0 || i >= disc.trackCount) throw new Error('There is no track ' + (i + 1) + ' on the disc.');
        for (const i of wanted) await iface.eraseTrack(i);
        return { deleted: wanted.length };
    },

    // WRITES TO THE DISC (order only). Moves the track at 0-based position `from` so it ends up at `to`. Not done on discs with
    // track groups: their ranges would have to be rewritten into the disc title. Afterwards the list is read back and
    // compared with the order that was expected.
    async move({ from, to }) {
        const iface = await openDevice();
        const before = await listDisc(iface);
        if (before.writeProtected) throw new Error('The disc is write-protected.');
        const n = before.trackCount;
        for (const p of [from, to]) if (!Number.isInteger(p) || p < 0 || p >= n) throw new Error('There is no track ' + (p + 1) + ' on the disc.');
        if (from === to) return { moved: false };
        if (before.groups.some(g => g.title)) throw new Error('This disc has track groups. Moving tracks on a grouped standard disc is not supported yet.');
        const flat = d => d.groups.flatMap(g => g.tracks).sort((a, b) => a.index - b.index).map(t => t.title + '|' + t.codec + '|' + t.seconds);
        const expected = flat(before);
        expected.splice(to, 0, expected.splice(from, 1)[0]);
        try { await iface.stop(); } catch (e) { /* already stopped */ }
        await iface.moveTrack(from, to);
        const got = flat(await listDisc(iface));
        if (got.length !== expected.length || got.some((v, i) => v !== expected[i])) {
            throw new Error('The recorder accepted the move, but the track order is not what was expected. Reload the disc to see its current order.');
        }
        return { moved: true };
    },

    // WRITES TO THE DISC: erases everything on it. mode 'standard' leaves a blank standard disc. mode 'himd' (Hi-MD recorders only)
    // erases it and switches the recorder into Hi-MD mode; the recorder then shows up as a Hi-MD device holding an unformatted
    // Hi-MD disc, which the Hi-MD helper's `format` command still has to initialise.
    async format({ mode }) {
        if (mode !== 'standard' && mode !== 'himd') throw new Error('Unknown format: ' + mode);
        const iface = await openDevice();
        const status = await netmd.getDeviceStatus(iface);
        if (!status.discPresent) throw new Error('There is no disc in the recorder.');
        const disc = await listDisc(iface);
        if (disc.writeProtected) throw new Error('The disc is write-protected. Slide its tab to make it writable, then try again.');
        if (mode === 'himd') {
            if (!/MZ-(RH|NH|DH)|DS-HMD1|CMT-AH/.test(String(disc.device || ''))) throw new Error('This recorder (' + (disc.device || 'unknown') + ') is not a Hi-MD recorder.');
            try { await iface.stop(); } catch (e) { /* already stopped */ }
            await netmd.formatToHiMD(iface);
            return { mode, tracksBefore: disc.trackCount, enteredHiMD: true };
        }
        try { await iface.stop(); } catch (e) { /* already stopped */ }
        await iface.eraseDisc();
        const after = await listDisc(iface);
        if (after.trackCount !== 0) throw new Error('The recorder accepted the erase but the disc still lists ' + after.trackCount + ' tracks.');
        return { mode, tracksBefore: disc.trackCount, enteredHiMD: false, left: after.left, total: after.total };
    },

    // Read-only. Copies one track from the disc to a WAV so the app can play it. Only recorders that can send audio back
    // over NetMD (the MZ-RH1 and MZ-M200) support this; others answer with an error. SP arrives as ATRAC1 (AEA),
    // LP2/LP4 as ATRAC3 in a WAV; the bundled ffmpeg decodes either.
    // exploit: true is for Hi-MD recorders that cannot send audio back by themselves (the MZ-NH700): the track is read with
    // the "ATRAC USB bulk transfer" firmware patch from netmd-exploits; see fetchViaExploit. Still reads only.
    // raw: true keeps the recorder's own data instead of decoding it: `out` is then a base path, the file written is out + '.aea' (SP,
    // ATRAC1) or out + '.atrac3.wav' (LP2 / LP4, ATRAC3 frames in a WAV), and the result says which ({file, kind}). Used by Clone.
    async fetch({ index, out, exploit = false, raw: keepRaw = false }) {
        const iface = await openDevice();
        try { await iface.stop(); } catch (e) { /* already stopped */ }
        if (!exploit) { try { await makeIdle(iface); } catch (e) { /* the transfer below reports a recorder that stays busy */ } }   // e.g. still settling after the previous track
        let raw, data;
        if (exploit) {
            const r = await fetchViaExploit(iface, index);
            data = r.data;
            raw = out + (r.extension === 'aea' ? '.aea' : '.atrac3.wav');
        } else {
            const [format, d] = await netmd.upload(iface, index, p => say({ event: 'progress', done: p.readBytes, total: p.totalBytes }));
            data = d;
            raw = out + (format === netmd.DiscFormat.spStereo || format === netmd.DiscFormat.spMono ? '.aea' : '.atrac3.wav');
            // The recorder plays the track to send it: leave it stopped and still before the next command (a second track straight
            // after the first made the drive seek hard and fail).
            try { await makeIdle(iface); } catch (e) { /* best effort */ }
            await new Promise(r => setTimeout(r, 2500));
        }
        fs.writeFileSync(raw, data);
        if (keepRaw) return { file: raw, kind: raw.endsWith('.aea') ? 'aea' : 'atrac3wav', bytes: data.length };
        try {
            const exe = BIN('ffmpeg');
            if (!fs.existsSync(exe)) throw new Error('The bundled decoder is missing.');
            require('child_process').execFileSync(exe, ['-hide_banner', '-loglevel', 'error', '-y', '-i', raw, '-vn', '-acodec', 'pcm_s16le', '-f', 'wav', out],
                { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
        } catch (e) {
            throw new Error('Got the track from the recorder but could not decode it: ' + String((e.stderr || e.message || e)).trim().slice(0, 300));
        } finally {
            try { fs.unlinkSync(raw); } catch (e) { /* already gone */ }
        }
        const bytes = fs.statSync(out).size;
        await say({ event: 'start', progressive: false, totalBytes: bytes, format: 'wav' });   // the app can serve the finished file now
        return { bytes, format: 'wav' };
    },

    // Read-only. For playing on the PC with the firmware-patch download (MZ-NH700...): the track is decoded as it arrives and appended to
    // `out`, a WAV whose header declares the length up front (the track's seconds + 3, the tail padded with silence), so the app can start
    // playing after about two seconds of audio. A line "stop" on stdin ends it between sectors.
    async fetch_stream({ index, out, seconds, spinWait: spinWaitArg }) {
        const iface = await openDevice();
        const T0 = Date.now(), mark = text => say({ event: 'log', ms: Date.now() - T0, text });
        const { esm, Cls, trace } = await exploitOpen(iface);
        await mark('patch state manager ready');
        let stop = false;
        process.stdin.on('data', d => { if (String(d).includes('stop')) stop = true; });
        process.stdin.resume();
        const exe = BIN('ffmpeg');
        if (!fs.existsSync(exe)) throw new Error('The bundled decoder is missing.');
        const declared = (Math.round(seconds) + 3) * 176400;
        const fd = fs.openSync(out, 'w');
        const h = Buffer.alloc(44);
        h.write('RIFF', 0); h.writeUInt32LE(36 + declared, 4); h.write('WAVEfmt ', 8); h.writeUInt32LE(16, 16);
        h.writeUInt16LE(1, 20); h.writeUInt16LE(2, 22); h.writeUInt32LE(44100, 24); h.writeUInt32LE(176400, 28);
        h.writeUInt16LE(4, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(declared, 40);
        fs.writeSync(fd, h, 0, 44, 0);
        let pos = 44, started = false, err = '', p = null, closed = null, exploit = null;
        const announce = async () => { if (!started) { started = true; await say({ event: 'start', progressive: true, totalBytes: 44 + declared, format: 'wav' }); } };
        try {
            try { await iface.stop(); } catch (e) { /* already stopped */ }
            exploit = await esm.require(Cls);
            // The library sleeps a fixed 20 s after seeking to the track on Hi-MD recorders (wait-for-disc-spinning.js: it cannot read the spin state
            // there), which is nearly all of the start-up time. MDM_SPIN_WAIT (milliseconds) replaces that wait; unset, the library's own 20 s is kept.
            const spinWait = Number.isFinite(Number(spinWaitArg)) && spinWaitArg !== undefined && spinWaitArg !== null ? Number(spinWaitArg)
                : (process.env.MDM_SPIN_WAIT === undefined || process.env.MDM_SPIN_WAIT === '' ? NaN : Number(process.env.MDM_SPIN_WAIT));
            if (Number.isFinite(spinWait) && spinWait >= 0) {
                const sleeper = await esm.require(mod('netmd-exploits').WaitForDiscToStopSpinning);
                sleeper.wait = async () => { await new Promise(r => setTimeout(r, spinWait)); };
                await mark('seek wait set to ' + spinWait + ' ms');
            }
            // The library fills its first read buffer completely (3,455 sectors, about 220 s of audio) before it returns the first sector, which
            // is most of the wait before playback can start. Load a smaller first piece and the normal size after it; the decoded audio
            // is the same (checked byte for byte against a normal read).
            if (FIRST_LOAD_SECTORS && exploit.sectorsPerLoad > FIRST_LOAD_SECTORS) {
                const normal = exploit.sectorsPerLoad, reload = exploit.reloadBuffer.bind(exploit);
                let first = true;
                exploit.sectorsPerLoad = FIRST_LOAD_SECTORS;
                exploit.reloadBuffer = async (n, cb) => { await reload(n, cb); if (first) { first = false; exploit.sectorsPerLoad = normal; } };
            }
            await mark('exploit loaded');
            let seen = {};
            for await (const chunk of exploit.downloadTrackGenerator(index, null, { shouldCancelImmediately: () => stop })) {
                if (stop) throw new Error('stopped');
                if (!seen[chunk.type]) { seen[chunk.type] = true; await mark('first chunk: ' + chunk.type); }
                if (chunk.type === 'fileExtension') {                      // SP arrives as an .aea (ATRAC1), LP2 / LP4 as a .wav holding ATRAC3
                    // The format and its parameters are in the header, so ffmpeg need not read megabytes ahead to probe the stream (it would
                    // otherwise hold back all output for ~25 s while the first 5 MB arrive).
                    p = require('child_process').spawn(exe, ['-hide_banner', '-loglevel', 'error', '-probesize', '32768', '-analyzeduration', '0',
                        '-f', chunk.textChunk === 'aea' ? 'aea' : 'wav', '-i', 'pipe:0',
                        '-vn', '-ar', '44100', '-ac', '2', '-acodec', 'pcm_s16le', '-f', 's16le', 'pipe:1'], { windowsHide: true });
                    closed = new Promise((resolve, reject) => { p.on('error', reject); p.on('close', resolve); });
                    p.stdin.on('error', () => { /* ffmpeg quit early; its exit code is reported below */ });
                    p.stderr.on('data', d => { err += d; });
                    p.stdout.on('data', d => {
                        const room = 44 + declared - pos;                // never write past what the header declares
                        if (room <= 0) return;
                        const b = d.length > room ? d.subarray(0, room) : d;
                        fs.writeSync(fd, b, 0, b.length, pos); pos += b.length;
                        if (!started && pos - 44 >= 2 * 176400) announce();
                    });
                } else if (p && (chunk.type === 'header' || chunk.type === 'audioData') && chunk.chunk) {
                    if (!p.stdin.write(Buffer.from(chunk.chunk.buffer, chunk.chunk.byteOffset, chunk.chunk.byteLength))) await new Promise(r => p.stdin.once('drain', r));
                }
            }
            if (stop) throw new Error('stopped');
            if (!p) throw new Error('The recorder returned no audio. ' + trace.slice(-3).join(' | '));
            p.stdin.end();
            const code = await closed;
            if (code !== 0) throw new Error('The audio decoder failed: ' + err.trim().slice(0, 300));
            if (pos - 44 < 5 * 176400) throw new Error('The recorder returned almost no audio. ' + trace.slice(-3).join(' | '));
            if (pos < 44 + declared) { const pad = Buffer.alloc(44 + declared - pos); fs.writeSync(fd, pad, 0, pad.length, pos); }
            await announce();
            return { bytes: 44 + declared, format: 'wav', decodedBytes: pos - 44 };
        } catch (e) {
            try { if (p) p.kill(); } catch (k) { /* already gone */ }
            throw e;
        } finally {
            fs.closeSync(fd);
            await exploitClose(iface, esm, exploit);
        }
    },

    // Read-only, applies no patch: which firmware the recorder runs and whether the download firmware patch exists for it.
    async exploit_probe() {
        const iface = await openDevice();
        const ex = mod('netmd-exploits');
        const factory = await iface.factory();
        const versionCode = await netmd.getDescriptiveDeviceCode(factory);
        const dev = { hwid: (await factory.getDeviceCode()).hwid, versionCode, isHimd: versionCode.startsWith('H') };
        const best = ex.getBestSuited(ex.AtracRecovery, dev);
        return { device: await iface.netMd.getDeviceName(), versionCode, hwid: dev.hwid, exploit: best ? best._name : null, allowed: EXPLOIT_FAMILY.test(versionCode) && !!best };
    },

    // Remote control: the recorder plays the disc itself, through its own output. Writes nothing to the disc.
    // action: play ({index}), pause, resume, stop, seek ({index, seconds}), next, previous, status.
    // Returns where the recorder is: {state, track (0-based), seconds}.
    async remote({ action, index, seconds }) {
        const iface = await openDevice();
        if (action === 'play') { await iface.gotoTrack(index); await iface.play(); }
        else if (action === 'pause') await iface.pause();
        else if (action === 'resume') await iface.play();
        else if (action === 'stop') await iface.stop();
        else if (action === 'seek') await iface.gotoTime(index, 0, Math.floor(seconds / 60), Math.floor(seconds % 60), 0);
        else if (action === 'next') await iface.nextTrack();
        else if (action === 'previous') await iface.previousTrack();
        else if (action !== 'status') throw new Error('Unknown remote action: ' + action);
        const st = await netmd.getDeviceStatus(iface);
        return { state: st.state, track: st.track, seconds: st.time ? st.time.minute * 60 + st.time.second : 0 };
    },

    // Stops the recorder if it is playing or sending audio (used after the app ended a track transfer because Stop was pressed). Changes nothing on the disc.
    async halt() {
        const iface = await openDevice();
        try { await iface.stop(); } catch (e) { /* already stopped */ }
        return {};
    },

    // WRITES TO THE DISC. Renames a track ({index, title}) or the disc ({disc: true, title}).
    async rename({ index, title, disc = false }) {
        const iface = await openDevice();
        const t = cleanTitle(title);
        if (disc) await iface.setDiscTitle(t); else await iface.setTrackTitle(index, t);
        return { title: t };
    },
};

(async () => {
    const [cmd, argJson] = process.argv.slice(2);
    try {
        if (!commands[cmd]) throw new Error('Unknown command: ' + cmd);
        const result = await commands[cmd](argJson ? JSON.parse(argJson) : {});
        await say({ result });
        process.exit(0);
    } catch (e) {
        await say({ error: String((e && e.message) || e) });
        process.exit(1);
    }
})();
