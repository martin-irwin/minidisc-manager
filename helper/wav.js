// Shared by himd_helper.js and netmd_helper.js.
// Finds the audio in a WAV file. Only 16-bit, 44.1 kHz, stereo PCM is accepted, as the recorders need.
// Returns { start, length }: where the sample data begins in `buf` and how many bytes it has.
function parseWav(buf) {
    if (buf.length < 44 || buf.toString('latin1', 0, 4) !== 'RIFF' || buf.toString('latin1', 8, 12) !== 'WAVE') {
        throw new Error('Not a WAV file');
    }
    let pos = 12, fmt = null, data = null;
    while (pos + 8 <= buf.length) {
        const id = buf.toString('latin1', pos, pos + 4);
        const size = buf.readUInt32LE(pos + 4);
        const body = pos + 8;
        if (id === 'fmt ') fmt = { format: buf.readUInt16LE(body), channels: buf.readUInt16LE(body + 2), rate: buf.readUInt32LE(body + 4), bits: buf.readUInt16LE(body + 14) };
        if (id === 'data') { data = { start: body, length: Math.min(size, buf.length - body) }; break; }
        pos = body + size + (size & 1);
    }
    if (!fmt || !data) throw new Error('The WAV file is incomplete');
    if (fmt.format !== 1 || fmt.channels !== 2 || fmt.rate !== 44100 || fmt.bits !== 16) {
        throw new Error('Only 16-bit 44.1 kHz stereo WAV files can be added (this one is ' +
            fmt.bits + '-bit, ' + fmt.rate + ' Hz, ' + fmt.channels + ' channel' + (fmt.channels === 1 ? '' : 's') + ')');
    }
    return data;
}

module.exports = { parseWav };
