"""Gapless audio CDs with CD-Text, written with Windows' own raw CD writer (IMAPI2, "DAO-96").

Windows' ordinary audio burner (track-at-once) always leaves a 2-second gap between tracks and cannot write CD-Text. Its raw CD writer takes a
complete disc image instead: lead-in (the table of contents and the CD-Text, in the sub-channels), the program area and the lead-out. This
module builds that image from the Red Book / MMC layouts, using nothing but the standard library:

  main channel : 2352 bytes of 44.1 kHz stereo 16-bit little-endian PCM per sector (zeros in lead-in / lead-out)
  sub-channel  : 96 bytes per sector, "raw" interleaved: one byte per symbol, bit 7 = P, bit 6 = Q, bits 5..0 = R..W
  one sector   : 2448 bytes

The image starts at MSF 95:00:00 (IMAPI's default start for WriteMedia): 22500 lead-in sectors that end exactly where the program area
(pre-gap of track 1, at 00:00:00) begins. The writer skips the part of the lead-in that the disc does not need.
"""
import os
import struct

SECTOR = 2352
SUB = 96
FULL = SECTOR + SUB
LEADIN_SECTORS = 5 * 60 * 75                   # 95:00:00 .. 99:59:74
PREGAP = 150
LEADOUT_SECTORS = 6750                         # 90 s, the minimum for a first session
CTL_ADR = 0x41                                 # audio, 2 channels, no pre-emphasis, digital copy permitted; Q mode 1


class CdBurnError(Exception):
    pass


def bcd(n):
    return ((n // 10) << 4) | (n % 10)


def msf(frames):
    return frames // 4500, (frames // 75) % 60, frames % 75


def crc16(data):
    """CRC-16/CCITT (x^16 + x^12 + x^5 + 1), inverted: used by the Q channel and by CD-Text packs."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc ^ 0xFFFF


_QBITS = [bytes(0x40 if (b >> (7 - k)) & 1 else 0 for k in range(8)) for b in range(256)]
_P_ALL = int.from_bytes(b'\x80' * SUB, 'big')


def q_channel(ctl_adr, tno, idx_or_point, m, s, f, zero, pm, ps, pf):
    """The 12-byte Q channel (mode 1): 10 bytes of data and the CRC."""
    body = bytes([ctl_adr, tno, idx_or_point, m, s, f, zero, pm, ps, pf])
    return body + struct.pack('>H', crc16(body))


def sub96(q12, p=False, rw=None):
    """96 sub-channel bytes (raw interleaved) from a 12-byte Q channel, the P flag and optionally 96 six-bit R..W symbols."""
    v = int.from_bytes(b''.join(_QBITS[b] for b in q12), 'big')
    if p:
        v |= _P_ALL
    if rw is not None:
        v |= int.from_bytes(bytes(rw), 'big')
    return v.to_bytes(SUB, 'big')


# -- CD-Text ---------------------------------------------------------------------------------------
def _latin1(text):
    return (text or '').encode('latin-1', 'replace')[:160]


def _text_packs(ptype, strings, block, first_seq):
    """The packs of one text type. `strings`: [(track number, bytes)] for the album (track 0) and every track, in order."""
    stream, owner = bytearray(), []                    # owner[i] = (track number, offset inside its string) of byte i
    for tno, text in strings:
        for off, c in enumerate(text + b'\0'):
            stream.append(c)
            owner.append((tno, off))
    packs = []
    for j in range(0, len(stream), 12):
        chunk = bytes(stream[j:j + 12]).ljust(12, b'\0')
        tno, off = owner[j]
        head = bytes([ptype, tno, (first_seq + len(packs)) & 0xFF, (block << 4) | min(off, 15)])
        packs.append(head + chunk + struct.pack('>H', crc16(head + chunk)))
    return packs


def cdtext_packs(album, album_artist, tracks):
    """All CD-Text packs of block 0 (English, ISO 8859-1): titles (0x80), performers (0x81) and the three block-size packs (0x8F).
    `tracks`: [(title, artist)]. Performers are written only if at least one is given."""
    n = len(tracks)
    sets = [(0x80, [(0, _latin1(album))] + [(i + 1, _latin1(t[0])) for i, t in enumerate(tracks)])]
    if album_artist or any(t[1] for t in tracks):
        sets.append((0x81, [(0, _latin1(album_artist))] + [(i + 1, _latin1(t[1])) for i, t in enumerate(tracks)]))
    packs, counts = [], {}
    for ptype, strings in sets:
        got = _text_packs(ptype, strings, 0, len(packs))
        counts[ptype] = len(got)
        packs += got
    total = len(packs) + 3
    last_seq = total - 1
    cnt = [counts.get(0x80 + i, 0) for i in range(16)]
    cnt[0x0F] = 3
    data = [bytes([0x00, 1, n, 0] + cnt[0:8]),
            bytes(cnt[8:16]) + bytes([last_seq, 0, 0, 0]),
            bytes([0, 0, 0, 0]) + bytes([0x09, 0, 0, 0, 0, 0, 0, 0])]
    for i, d in enumerate(data):
        head = bytes([0x8F, i, (len(packs)) & 0xFF, 0])
        packs.append(head + d + struct.pack('>H', crc16(head + d)))
    return packs


def _pack_symbols(pack18):
    """An 18-byte pack as 24 six-bit symbols (the R..W bits of 24 consecutive sub-channel symbols)."""
    bits = int.from_bytes(pack18, 'big')
    return [(bits >> (138 - 6 * i)) & 0x3F for i in range(24)]


# -- the image -------------------------------------------------------------------------------------
def build_image(tracks, out_path, album='', album_artist='', text=True, progress=None, cancel=None):
    """Writes the disc image. `tracks`: [{'pcm': path of raw 44.1 kHz 16-bit stereo PCM whose size is a multiple of 2352, 'title', 'artist'}].
    Returns {'sectors', 'tracks': [(start LBA, sectors)], 'leadout_lba'}; None if cancelled. Tracks follow each other with no gap."""
    if not tracks or len(tracks) > 99:
        raise CdBurnError('An audio CD holds 1 to 99 tracks.')
    sizes = []
    for t in tracks:
        n = os.path.getsize(t['pcm'])
        if n == 0 or n % SECTOR:
            raise CdBurnError('The audio of "%s" is not a whole number of CD sectors.' % t.get('title', t['pcm']))
        sizes.append(n // SECTOR)
    starts = [sum(sizes[:i]) for i in range(len(sizes))]
    program = sum(sizes)
    if (program + PREGAP + LEADOUT_SECTORS) / 75 > 80 * 60 + 90:
        raise CdBurnError('The tracks are longer than an 80-minute CD.')
    packs = [_pack_symbols(p) for p in cdtext_packs(album, album_artist, [(t.get('title', ''), t.get('artist', '')) for t in tracks])] if text else []
    silence = bytes(SECTOR)

    # the table of contents: A0 (first track), A1 (last track), A2 (start of lead-out), then every track; each entry three times in a row
    toc = [(0xA0, 1, 0, 0), (0xA1, len(tracks), 0, 0), (0xA2,) + msf(program + 150)]
    toc += [(bcd(i + 1),) + msf(starts[i] + 150) for i in range(len(tracks))]
    toc = [(p, bcd(a), bcd(b), bcd(c)) for p, a, b, c in toc]
    cycle = [e for e in toc for _ in range(3)]
    pack_i = 0

    done = 0
    total = LEADIN_SECTORS + PREGAP + program + LEADOUT_SECTORS
    with open(out_path, 'wb') as out:
        # lead-in: 95:00:00 .. 99:59:74
        for i in range(LEADIN_SECTORS):
            if cancel and cancel():
                return None
            m, s, f = msf(95 * 4500 + i)
            point, pm, ps, pf = cycle[i % len(cycle)]
            q = q_channel(CTL_ADR, 0, point, bcd(m), bcd(s), bcd(f), 0, pm, ps, pf)
            rw = None
            if packs:
                rw = []
                for _ in range(4):                       # four 24-symbol packs fit in one sector's 96 symbols
                    rw += packs[pack_i % len(packs)]
                    pack_i += 1
            out.write(silence + sub96(q, False, rw))
        # pre-gap of track 1: 2 seconds of silence, index 0, relative time counting down to 00:00:00
        for i in range(PREGAP):
            rm, rs, rf = msf(PREGAP - 1 - i)
            am, as_, af = msf(i)
            out.write(silence + sub96(q_channel(CTL_ADR, 1, 0, bcd(rm), bcd(rs), bcd(rf), 0, bcd(am), bcd(as_), bcd(af)), True))
        # the tracks, one after the other: index 1, relative time counting up from the start of each track
        lba = 0
        for tn, t in enumerate(tracks, 1):
            with open(t['pcm'], 'rb') as src:
                for k in range(sizes[tn - 1]):
                    audio = src.read(SECTOR)
                    rm, rs, rf = msf(k)
                    am, as_, af = msf(lba + 150)
                    out.write(audio + sub96(q_channel(CTL_ADR, bcd(tn), 1, bcd(rm), bcd(rs), bcd(rf), 0, bcd(am), bcd(as_), bcd(af))))
                    lba += 1
                    done += 1
                    if progress and done % 2000 == 0:
                        progress(done, program)
                    if cancel and cancel() and done % 2000 == 0:
                        return None
        # lead-out: track AA, index 1, relative time counting up
        for j in range(LEADOUT_SECTORS):
            rm, rs, rf = msf(j)
            am, as_, af = msf(program + 150 + j)
            out.write(silence + sub96(q_channel(CTL_ADR, 0xAA, 1, bcd(rm), bcd(rs), bcd(rf), 0, bcd(am), bcd(as_), bcd(af)), j >= 150 and (j // 19) % 2 == 0))
    return {'sectors': total, 'tracks': [(starts[i], sizes[i]) for i in range(len(tracks))], 'leadout_lba': program}


# -- checking an image ---------------------------------------------------------------------------------
def _q_from_sub(sub):
    """The 12 Q bytes from 96 raw sub-channel bytes."""
    bits = [(b >> 6) & 1 for b in sub]
    return bytes(sum(bits[i * 8 + k] << (7 - k) for k in range(8)) for i in range(12))


def verify_image(path, tracks_info):
    """Reads an image back and checks it: every Q CRC, the lead-in table of contents, the first and last sector of each track, the gapless
    joins and the CD-Text packs. Returns a list of problems (empty if all is right)."""
    problems = []
    total = os.path.getsize(path) // FULL
    with open(path, 'rb') as f:
        def sector(n):
            f.seek(n * FULL)
            d = f.read(FULL)
            return d[:SECTOR], d[SECTOR:]

        def q_at(n):
            q = _q_from_sub(sector(n)[1])
            if struct.unpack('>H', q[10:])[0] != crc16(q[:10]):
                problems.append('Q CRC wrong at sector %d' % n)
            return q
        for n in list(range(0, 60)) + list(range(LEADIN_SECTORS - 40, LEADIN_SECTORS)) + list(range(LEADIN_SECTORS, LEADIN_SECTORS + PREGAP + 3)):
            q_at(n)
        base = LEADIN_SECTORS + PREGAP
        seen = {}
        for n in range(LEADIN_SECTORS - len(tracks_info) * 9 - 30, LEADIN_SECTORS):
            q = q_at(n)
            seen[q[2]] = q[7:10]
        if 0xA0 not in seen or 0xA1 not in seen or 0xA2 not in seen:
            problems.append('lead-in table of contents is missing A0/A1/A2')
        for i, (start, count) in enumerate(tracks_info['tracks']):
            for n, rel in ((base + start, 0), (base + start + count - 1, count - 1)):
                q = q_at(n)
                if q[1] != bcd(i + 1) or q[2] != 1:
                    problems.append('track %d: wrong track/index in sector %d' % (i + 1, n))
                m, s, fr = msf(rel)
                if q[3:6] != bytes([bcd(m), bcd(s), bcd(fr)]):
                    problems.append('track %d: wrong relative time in sector %d' % (i + 1, n))
            if i and q_at(base + start)[2] != 1:
                problems.append('track %d: there is a pause (index 0) before it, so it is not gapless' % (i + 1))
        q = q_at(base + tracks_info['leadout_lba'])
        if q[1] != 0xAA:
            problems.append('lead-out does not start where expected')
        if total != tracks_info['sectors']:
            problems.append('image has %d sectors, expected %d' % (total, tracks_info['sectors']))
    return problems
