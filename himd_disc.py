"""Read-only parser for the Hi-MD track index (TRKIDXnn.HMA, magic 'TIF ').

The layout follows the one implemented in himd-js (all values big-endian):
  0x0100  track count (u16)          0x0102  track-index -> slot table (u16 each)
  0x2100  groups, 8 bytes each (group 0 = disc title)
  0x8000  track slots, 0x50 bytes each
  0x40000 string chunks, 16 bytes each (14 bytes of text + u16 flags: type<<12 | link)
"""
import re

from himd_fs import FatError

STR_ENCODINGS = {5: 'latin1', 132: 'utf-16-be', 144: 'cp932'}


def u16(b, o):
    return (b[o] << 8) | b[o + 1]


def _is_mpeg(ci):
    return (ci[0] & 3) == 3


def codec_name(codec_id, ci):
    if codec_id == 128:
        return 'PCM'
    if codec_id == 0:
        return 'AT3'
    if codec_id == 1:
        return 'MP3' if _is_mpeg(ci) else 'A3+'
    return '?'


def bytes_per_frame(codec_id, ci):
    if codec_id == 128:
        return 64
    if codec_id == 0:
        return ci[2] * 8
    if codec_id == 1 and not _is_mpeg(ci):
        return ((((ci[1] << 8) | ci[2]) & 0x3FF) + 1) * 8
    return None


def kbps(codec_id, ci):
    """Bit rate for the ATRAC family and PCM (MP3 rates are shown as 'MP3')."""
    bpf = bytes_per_frame(codec_id, ci)
    if bpf is None:
        return None
    rates = [32000, 44100, 48000, 88200, 96000]
    if codec_id == 128:
        return 1411
    rate = rates[ci[1] >> 5] if (ci[1] >> 5) < len(rates) else 44100
    spf = 1024 if codec_id == 0 else 2048
    return int(bpf * rate / (125 * spf))


class Disc:
    def __init__(self, fs):
        self.fs = fs
        self.datanum = None
        for e in fs.listdir('/HMDHIFI'):
            m = re.fullmatch(r'ATDATA([0-9A-F]{2})\.HMA', e['short'].upper())
            if m and not e['dir']:
                self.datanum = int(m.group(1), 16)
                self.audio_bytes = e['size']
        if self.datanum is None:
            raise FatError('This is not a Hi-MD disc (no HMDHIFI audio data found)')
        self.tif_path = '/HMDHIFI/TRKIDX%02X.HMA' % self.datanum
        self.tif = bytearray(fs.read_file(self.tif_path))
        if self.tif[:4] != b'TIF ' or len(self.tif) != 0x50000:
            raise FatError('The track index file is not valid')
        self.original = bytes(self.tif)

    # -- strings -------------------------------------------------------
    def _chunk(self, i):
        raw = self.tif[0x40000 + 0x10 * i: 0x40000 + 0x10 * i + 0x10]
        flags = u16(raw, 14)
        return raw[:14], flags & 0xFFF, flags >> 12

    def string(self, index):
        if index == 0:
            return ''
        parts, seen = [], set()
        content, link, kind = self._chunk(index)
        if kind < 8:
            return ''
        while True:
            parts.append(content)
            if link == 0 or link in seen:
                break
            seen.add(link)
            content, link, _ = self._chunk(link)
        raw = b''.join(parts)
        enc = STR_ENCODINGS.get(raw[0], 'latin1')
        text = raw[1:].decode(enc, 'replace')
        return text.split('\x00')[0]

    # -- structure -----------------------------------------------------
    def group(self, i):
        raw = self.tif[0x2100 + 8 * i: 0x2100 + 8 * i + 8]
        return {'start': u16(raw, 0) - 1, 'end': u16(raw, 2), 'title': u16(raw, 4)}

    def disc_title(self):
        g = self.group(0)
        return self.string(g['title']) if g['title'] else ''

    def groups(self):
        out = []
        for i in range(1, 256):
            g = self.group(i)
            if g['end'] == 0 and g['start'] == -1 and g['title'] == 0:
                break
            out.append({'index': i, 'first': g['start'] + 1, 'last': g['end'], 'title': self.string(g['title'])})
        return out

    def track_count(self):
        return u16(self.tif, 0x100)

    def fragments(self, n):
        """(first_block, last_block) pairs of track n (0-based), in play order."""
        slot = u16(self.tif, 0x102 + 2 * n)
        frag = u16(self.tif, 0x8000 + 0x50 * slot + 36)
        out, seen = [], set()
        while frag and frag not in seen:
            seen.add(frag)
            o = 0x30000 + 0x10 * frag
            out.append((u16(self.tif, o + 8), u16(self.tif, o + 10)))
            frag = u16(self.tif, o + 14) & 0xFFF
        return out

    def track(self, n):
        """n is the 0-based position on the disc."""
        slot = u16(self.tif, 0x102 + 2 * n)
        raw = self.tif[0x8000 + 0x50 * slot: 0x8000 + 0x50 * slot + 0x50]
        codec_id = raw[32]
        ci = bytes(raw[33:36]) + bytes(raw[44:46])
        seconds = u16(raw, 40)
        rates = [32000, 44100, 48000, 88200, 96000]
        return {
            'number': n + 1,
            'title': self.string(u16(raw, 8)) or '(untitled)',
            'artist': self.string(u16(raw, 10)),
            'album': self.string(u16(raw, 12)),
            'codec': codec_name(codec_id, ci),
            'kbps': kbps(codec_id, ci),
            'codecId': codec_id,                     # the codec fields as stored, so frames can be written back exactly
            'ci': bytes(ci).hex(),
            'frame': bytes_per_frame(codec_id, ci),  # bytes per frame (64 for PCM)
            'spf': 1024 if codec_id == 0 else 2048,  # samples per ATRAC frame
            'rate': rates[ci[1] >> 5] if (ci[1] >> 5) < len(rates) else 44100,
            'seconds': seconds,
            'key': bytes(raw[16:24]).hex(),          # random per uploaded PCM track; identifies it in uploads.json
            'blocks': sum(last - first + 1 for first, last in self.fragments(n)),
        }

    def tracks(self):
        return [self.track(i) for i in range(self.track_count())]

    # ------------------------------------------------------------------
    # Editing (in memory only; Api writes the changed sectors afterwards).
    # Ported from himd-js: strings live in 16-byte chunks (14 text bytes +
    # u16 type<<12|link). Chunk 0 heads the free list.
    # ------------------------------------------------------------------
    TYPE_UNUSED, TYPE_CONT = 0, 1
    TYPE_TITLE, TYPE_ARTIST, TYPE_ALBUM, TYPE_GROUP = 8, 9, 10, 12

    def _put_chunk(self, i, content, link, kind):
        o = 0x40000 + 0x10 * i
        self.tif[o:o + 14] = content
        self.tif[o + 14] = ((kind << 4) | (link >> 8)) & 0xFF
        self.tif[o + 15] = link & 0xFF

    def _remove_string(self, index):
        if index == 0:
            return
        head_content, head_link, head_kind = self._chunk(0)
        next_free = head_link
        self._put_chunk(0, head_content, index, head_kind)
        seen = set()
        while index != 0 and index not in seen:
            seen.add(index)
            _, link, _ = self._chunk(index)
            if link == 0:
                self._put_chunk(index, bytes(14), next_free, self.TYPE_UNUSED)
                return
            self._put_chunk(index, bytes(14), link, self.TYPE_UNUSED)
            index = link

    @staticmethod
    def _encode(text):
        for code, enc in ((5, 'latin-1'), (144, 'shift_jis'), (132, 'utf-16-be')):
            try:
                raw = text.encode(enc)
                if raw.decode(enc) == text:
                    return bytes([code]) + raw
            except (UnicodeError, LookupError):
                continue
        raise FatError('That text cannot be stored on a Hi-MD disc')

    def _add_string(self, text, kind):
        data = self._encode(text)
        slots = (len(data) + 13) // 14
        index = 0
        for _ in range(slots):                       # make sure the free list is long enough
            _, link, ckind = self._chunk(index)
            if ckind != self.TYPE_UNUSED and index != 0:
                raise FatError('The disc’s title memory is damaged (free list broken)')
            if link == 0:
                raise FatError('There is no room left on the disc for more titles')
            index = link
        start = self._chunk(0)[1]
        index = start
        for i in range(slots):
            _, link, _ = self._chunk(index)
            piece = data[i * 14:(i + 1) * 14].ljust(14, b'\x00')
            self._put_chunk(index, piece, 0 if i == slots - 1 else link,
                            kind if i == 0 else self.TYPE_CONT)
            index = link
        content, _, ckind = self._chunk(0)
        self._put_chunk(0, content, index, ckind)    # free list now starts after our chunks
        return start

    def _set_u16(self, off, value):
        self.tif[off] = (value >> 8) & 0xFF
        self.tif[off + 1] = value & 0xFF

    def rename_track(self, n, title=None, artist=None, album=None):
        """Change the text fields of track n (0-based). None leaves a field as it is,
        an empty string removes it. Only the three string pointers of the record change."""
        if not 0 <= n < self.track_count():
            raise FatError('No such track')
        slot = u16(self.tif, 0x102 + 2 * n)
        rec = 0x8000 + 0x50 * slot
        for value, off, kind in ((title, 8, self.TYPE_TITLE), (artist, 10, self.TYPE_ARTIST),
                                 (album, 12, self.TYPE_ALBUM)):
            if value is None:
                continue
            self._remove_string(u16(self.tif, rec + off))
            self._set_u16(rec + off, self._add_string(value, kind) if value else 0)

    def rename_group_record(self, physical_index, title):
        """physical_index 0 is the disc title; 1.. are groups."""
        rec = 0x2100 + 8 * physical_index
        self._remove_string(u16(self.tif, rec + 4))
        self._set_u16(rec + 4, self._add_string(title, self.TYPE_GROUP) if title else 0)
        self.tif[rec + 6] = 0x10                     # same as himd-js writeGroup

    def rename_disc(self, title):
        self.rename_group_record(0, title)

    def set_groups(self, groups):
        """Replace every group. groups: [(first, last, title)], track numbers counted from 1, last included, in track order and
        not overlapping. Written like himd-js addGroup/writeGroup; the disc title (record 0) is not touched."""
        n = self.track_count()
        prev = 0
        for first, last, _ in groups:
            if not (prev < first <= last <= n):
                raise FatError('The groups do not fit the tracks on this disc')
            prev = last
        if len(groups) > 254:
            raise FatError('Too many groups')
        for g in self.groups():                              # free the old titles, blank the old records
            o = 0x2100 + 8 * g['index']
            self._remove_string(u16(self.tif, o + 4))
            self.tif[o:o + 8] = bytes(8)
        for i, (first, last, title) in enumerate(groups, 1):
            o = 0x2100 + 8 * i
            self._set_u16(o, first)
            self._set_u16(o + 2, last)
            self._set_u16(o + 4, self._add_string(title, self.TYPE_GROUP) if title else 0)
            self.tif[o + 6] = 0x10
            self.tif[o + 7] = 0

    def _group_list(self):
        return [(g['first'], g['last'], g['title']) for g in self.groups()]

    def make_group(self, first, last, title):
        """Group tracks first..last (1-based, inclusive) under `title`, like the recorder's Group Set. The tracks must be next to each
        other; each must be ungrouped or belong to a group that lies wholly inside the range (such groups are folded into the new
        one, as groups cannot be nested). A range that cuts into a group from the middle is refused."""
        n = self.track_count()
        if not 1 <= first <= last <= n:
            raise FatError('Choose tracks that are on the disc')
        keep = []
        for f, l, t in self._group_list():
            if l < first or f > last:
                keep.append((f, l, t))
            elif f < first or l > last:
                raise FatError('The tracks would cut into the group “%s” (tracks %d–%d). Include all of that group, or none of it.' % (t or 'Group', f, l))
        keep.append((first, last, title))
        self.set_groups(sorted(keep))

    @staticmethod
    def groups_after_delete(groups, deleted):
        """groups [(first, last, title)] before tracks `deleted` (1-based numbers) are removed -> the same groups renumbered for the
        tracks that remain. A group that loses every track is dropped; one that loses some keeps the rest."""
        gone = sorted(set(deleted))
        out = []
        for first, last, title in groups:
            left = [t for t in range(first, last + 1) if t not in gone]
            if left:
                new_first = left[0] - sum(1 for d in gone if d < left[0])
                out.append((new_first, new_first + len(left) - 1, title))
        return out

    def add_groups(self, new):
        """Add several groups at once: new = [(first, last, title)] (1-based, last included). They must lie on tracks that are in no group
        yet and not overlap each other; the groups already on the disc are kept as they are."""
        n = self.track_count()
        existing = self._group_list()
        for first, last, _ in new:
            if not 1 <= first <= last <= n:
                raise FatError('Choose tracks that are on the disc')
            for f, l, t in existing:
                if not (l < first or f > last):
                    raise FatError('Tracks %d–%d are already in the group “%s”.' % (max(first, f), min(last, l), t or 'Group'))
        self.set_groups(sorted(existing + [(f, l, t) for f, l, t in new]))

    def release_group(self, indexes):
        """Ungroup the group(s) with these physical record numbers (one number or a list); the tracks stay where they are."""
        drop = {indexes} if isinstance(indexes, int) else set(indexes)
        gs = self.groups()
        if not drop or not drop <= {g['index'] for g in gs}:
            raise FatError('There is no such group on the disc')
        self.set_groups([(g['first'], g['last'], g['title']) for g in gs if g['index'] not in drop])

    def add_to_group(self, index, tracks):
        """Add ungrouped tracks (1-based numbers) to the group `index`. They must touch the group, or each other and then the group,
        so that the group stays in one piece; tracks that belong to another group cannot be taken."""
        gs = self.groups()
        g = next((x for x in gs if x['index'] == index), None)
        if g is None:
            raise FatError('There is no such group on the disc')
        tracks = set(tracks)
        if tracks & set(range(g['first'], g['last'] + 1)):
            raise FatError('Some of those tracks are already in this group')
        first, last = min([g['first']] + list(tracks)), max([g['last']] + list(tracks))
        if first < 1 or last > self.track_count():
            raise FatError('Choose tracks that are on the disc')
        missing = [t for t in range(first, last + 1) if t not in tracks and not g['first'] <= t <= g['last']]
        if missing:                                   # strict: nothing is pulled in that was not chosen
            raise FatError('Those tracks are not next to the group: track %d would be left out between them. Tick every track in between as well, or move the tracks next to the group first.' % missing[0])
        for o in gs:
            if o['index'] != index and not (o['last'] < first or o['first'] > last):
                raise FatError('Those tracks are not next to the group without taking in tracks of the group “%s”. Move them next to it first.' % (o['title'] or 'Group'))
        self.set_groups([(first, last, g['title']) if x['index'] == index else (x['first'], x['last'], x['title']) for x in gs])

    def move_track(self, src, dst):
        """Move the track at 0-based position src so that it ends up at position dst; the tracks in between shift by one.
        Only the track order table (slot numbers) and the group ranges change: the track records, the audio and the
        signed list are untouched, as with himd-js moveTrack. A track that lands inside or next to a group of its own joins
        or stays in that group; one that lands between two tracks of another group joins that group (a group's tracks
        must stay together); otherwise it is ungrouped."""
        n = self.track_count()
        if not (0 <= src < n and 0 <= dst < n):
            raise FatError('There is no such position on the disc')
        if src == dst:
            return
        order = [u16(self.tif, 0x102 + 2 * i) for i in range(n)]
        groups = self.groups()
        member = [0] * n                                   # group (physical record number) of each position; 0 = none
        for g in groups:
            for p in range(g['first'] - 1, g['last']):
                if 0 <= p < n:
                    member[p] = g['index']
        og = member[src]
        rest = member[:src] + member[src + 1:]
        left = rest[dst - 1] if dst > 0 else 0
        right = rest[dst] if dst < n - 1 else 0
        og_alone = bool(og) and og not in rest
        if og_alone:                                       # a group of one tracks moves with its track
            if left and left == right:
                raise FatError('This track is the only one in its group and cannot be moved into the middle of another group. '
                               'Move it to a place between groups instead.')
            new = og
        elif og and (left == og or right == og):
            new = og
        elif left and left == right:
            new = left
        else:
            new = 0
        order.insert(dst, order.pop(src))
        member = rest[:dst] + [new] + rest[dst:]
        for i, slot in enumerate(order):
            self._set_u16(0x102 + 2 * i, slot)
        # new ranges for the groups; the records are kept in order of their first track
        recs = []
        for g in groups:
            pos = [p for p, m in enumerate(member) if m == g['index']]
            if not pos:
                raise FatError('A group would become empty; nothing was changed')
            if pos[-1] - pos[0] + 1 != len(pos):
                raise FatError('The groups would no longer be in one piece; nothing was changed')
            o = 0x2100 + 8 * g['index']
            rec = bytearray(self.tif[o:o + 8])
            rec[0], rec[1] = (pos[0] + 1) >> 8, (pos[0] + 1) & 0xFF
            rec[2], rec[3] = (pos[-1] + 1) >> 8, (pos[-1] + 1) & 0xFF
            recs.append((pos[0], bytes(rec)))
        for k, (_, rec) in enumerate(sorted(recs)):
            o = 0x2100 + 8 * (k + 1)
            self.tif[o:o + 8] = rec

