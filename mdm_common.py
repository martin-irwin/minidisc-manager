"""Small helpers and constants shared by himd_app.py and the modules split out of it."""
import os
import struct

UNITS_PER_SECOND = 512        # a standard disc's capacity is counted in 1/512-second units of SP
CLONE_MAX_PCM = 600 * 1000 * 1000                     # the helper holds a PCM track in memory while writing it


def wav_data_bytes(path):
    """Size of the sample data of a 16-bit 44.1 kHz stereo PCM WAV with the plain 44-byte header the helper writes."""
    with open(path, 'rb') as f:
        h = f.read(44)
    if len(h) < 44 or h[:4] != b'RIFF' or h[8:12] != b'WAVE' or h[12:16] != b'fmt ' or h[36:40] != b'data':
        raise RuntimeError('The audio read from the disc is not in the expected format.')
    fmt, ch, rate, _, _, bits = struct.unpack('<HHIIHH', h[20:36])
    n = struct.unpack('<I', h[40:44])[0]
    if (fmt, ch, rate, bits) != (1, 2, 44100, 16) or n % 4 or os.path.getsize(path) != 44 + n:
        raise RuntimeError('The audio read from the disc is not complete 16-bit 44.1 kHz stereo PCM.')
    return n


def remove_item_files(items):
    """Deletes the audio file of every recorded item that has one (a missing or locked file is ignored)."""
    for item in items:
        if item.get('path'):
            try:
                os.remove(item['path'])
            except OSError:
                pass


def wav_header(data_bytes):
    return (b'RIFF' + struct.pack('<I', 36 + data_bytes) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 2, 44100, 176400, 4, 16)
            + b'data' + struct.pack('<I', data_bytes))
