"""Audio CD access for MiniDisc Manager (Windows only, standard library only).

 - drives() / read_toc(): the CD drives and an audio disc's track list, through DeviceIoControl (no admin rights needed).
 - cdtext(): titles and performers stored on the disc itself, when it has them.
 - disc_id() and the MusicBrainz functions: find the album and track titles online (and the front cover from the Cover Art Archive).
 - rip_track(): copies one track to a 16-bit 44.1 kHz stereo WAV. Every chunk is read twice and compared, and read again until two
   reads agree, so a dirty or scratched disc is noticed instead of silently ripped with clicks; unreadable sectors become silence and
   are counted in the result.
"""
import base64
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(ctypes, 'WinDLL'):      # Windows: the drive is read directly. Elsewhere only the online lookups below are used (no drives listed).
    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _k32.CreateFileW.restype = wt.HANDLE
    _k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    _k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _k32.GetDriveTypeW.argtypes = [wt.LPCWSTR]
else:
    _k32 = None
_INVALID = wt.HANDLE(-1).value

IOCTL_CDROM_READ_TOC = 0x00024000
IOCTL_CDROM_READ_TOC_EX = 0x00024054
IOCTL_CDROM_RAW_READ = 0x0002403E
SECTOR = 2352                       # one audio sector: 588 stereo 16-bit samples
CHUNK = 24                          # sectors per read (24 * 2352 = 56 KB, under the 64 KB limit most drives have)
USER_AGENT = 'MiniDiscManager/0.9 ( personal use )'     # MusicBrainz wants an identifying agent; no personal details go in it


class CdError(Exception):
    pass


def drives():
    """Letters of the CD / DVD drives (none yet on Linux and macOS)."""
    if _k32 is None:
        return []
    mask = _k32.GetLogicalDrives()
    return [chr(65 + i) for i in range(26) if mask & (1 << i) and _k32.GetDriveTypeW('%s:\\' % chr(65 + i)) == 5]


def _open(letter):
    h = _k32.CreateFileW(r'\\.\%s:' % letter.upper().rstrip(':'), 0x80000000, 3, None, 3, 0, None)    # read access, shared
    if h == _INVALID:
        raise CdError('Could not open drive %s: (Windows error %d).' % (letter, ctypes.get_last_error()))
    return h


def _ioctl(h, code, inbuf, outsize):
    out = ctypes.create_string_buffer(outsize)
    got = wt.DWORD(0)
    ok = _k32.DeviceIoControl(h, code, inbuf, len(inbuf) if inbuf is not None else 0, out, outsize, ctypes.byref(got), None)
    if not ok:
        return None, ctypes.get_last_error()
    return bytes(out)[:got.value], 0


def read_toc(letter):
    """The disc's table of contents: {first, last, leadout, tracks: [{num, start, frames, seconds, audio}]} (positions in 1/75 s,
    counted from the start of the disc). Raises CdError when there is no readable audio disc."""
    h = _open(letter)
    try:
        b, err = _ioctl(h, IOCTL_CDROM_READ_TOC, None, 804)
    finally:
        _k32.CloseHandle(h)
    if b is None or len(b) < 12:
        raise CdError('There is no audio CD in drive %s: (or it could not be read).' % letter)
    length, first, last = struct.unpack('>HBB', b[:4])
    raw = []
    for i in range(0, length - 2, 8):
        e = b[4 + i:12 + i]
        if len(e) < 8:
            break
        _, adrctl, num, _, _, m, s, f = e
        raw.append({'num': num, 'data': bool(adrctl & 4), 'start': (m * 60 + s) * 75 + f})
    leadout = next((t['start'] for t in raw if t['num'] == 0xAA), None)
    tracks = [t for t in raw if t['num'] != 0xAA]
    if leadout is None or not tracks or all(t['data'] for t in tracks):
        raise CdError('The disc in drive %s: is not an audio CD.' % letter)
    # An enhanced CD ends with a data track after the audio; the audio ends 11,400 frames before it
    for t in reversed(tracks):
        if t['data']:
            leadout = min(leadout, t['start'] - 11400)
    audio = [t for t in tracks if not t['data']]
    for k, t in enumerate(audio):
        end = audio[k + 1]['start'] if k + 1 < len(audio) else leadout
        t['frames'] = end - t['start']
        t['seconds'] = t['frames'] / 75.0
        t['audio'] = True
    return {'first': audio[0]['num'], 'last': audio[-1]['num'], 'leadout': leadout, 'tracks': audio}


def disc_id(toc):
    """The MusicBrainz disc ID: SHA-1 over the first and last track numbers, the lead-out and 99 track offsets, in a URL-safe base64."""
    offs = {t['num']: t['start'] for t in toc['tracks']}
    s = '%02X%02X%08X' % (toc['first'], toc['last'], toc['leadout']) + ''.join('%08X' % offs.get(n, 0) for n in range(1, 100))
    return base64.b64encode(hashlib.sha1(s.encode('ascii')).digest()).decode().replace('+', '.').replace('/', '_').replace('=', '-')


def _toc_string(toc):
    return '%d+%d+%d+' % (toc['first'], toc['last'], toc['leadout']) + '+'.join(str(t['start']) for t in toc['tracks'])


def cdtext(letter):
    """Titles and performers stored on the disc (CD-Text): {title, artist, tracks: {n: {title, artist}}}, or None if there are none."""
    h = _open(letter)
    try:
        b, err = _ioctl(h, IOCTL_CDROM_READ_TOC_EX, struct.pack('<BBBBI', 5, 0, 0, 0, 0), 16384)    # format 5: CD-TEXT
    finally:
        _k32.CloseHandle(h)
    if not b or len(b) < 22:
        return None
    length = struct.unpack('>H', b[:2])[0]
    streams = {}
    for i in range(0, length - 2, 18):
        p = b[4 + i:4 + i + 18]
        if len(p) < 18:
            break
        if p[0] in (0x80, 0x81) and not (p[3] & 0x80):                   # titles and performers, single-byte text
            streams.setdefault(p[0], bytearray()).extend(p[4:16])

    def split(data):
        parts = [x.decode('latin-1', 'replace') for x in bytes(data).split(b'\x00')]
        out = []
        for x in parts:
            out.append(out[-1] if x == '\t' and out else x)               # a tab means "same as the previous one"
        while out and out[-1] == '':
            out.pop()
        return out

    titles = split(streams.get(0x80, b''))
    artists = split(streams.get(0x81, b''))
    if not titles and not artists:
        return None
    pick = lambda lst, i: lst[i].strip() if i < len(lst) else ''
    n = max(len(titles), len(artists))
    return {'title': pick(titles, 0), 'artist': pick(artists, 0),
            'tracks': {i: {'title': pick(titles, i), 'artist': pick(artists, i)} for i in range(1, n)}}


# ---------------------------------------------------------------------------------------------------------- ripping
def _wav_header(nbytes):
    return (b'RIFF' + struct.pack('<I', 36 + nbytes) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 2, 44100, 176400, 4, 16)
            + b'data' + struct.pack('<I', nbytes))


def _raw_read(h, lba, count):
    """count audio sectors from sector lba, or None if the drive reports an error."""
    req = struct.pack('<qII', lba * 2048, count, 2)                       # RAW_READ_INFO: byte offset, sectors, CDDA mode
    b, err = _ioctl(h, IOCTL_CDROM_RAW_READ, req, count * SECTOR)
    return b if b is not None and len(b) == count * SECTOR else None


def _secure_read(h, lba, count, stats):
    """Reads the sectors until two reads in a row agree. Falls back to one sector at a time when a chunk keeps failing."""
    last = None
    for attempt in range(8):
        data = _raw_read(h, lba, count)
        if data is None:
            stats['retries'] += 1
            last = None
            continue
        if last is not None and data == last:
            return data
        if last is not None:
            stats['retries'] += 1
        last = data
    if count > 1:                                                          # find the bad sector(s) inside the chunk
        return b''.join(_secure_read(h, lba + i, 1, stats) for i in range(count))
    if last is not None:
        stats['suspect'] += 1                                              # reads kept differing: keep the last one, but say so
        return last
    stats['bad'] += 1                                                      # unreadable: silence
    return b'\x00' * SECTOR


def rip_track(letter, toc, num, out_path, progress=None, cancel=None):
    """Copies track `num` to a WAV. Returns {seconds, bytes, retries, suspect, bad} (suspect: sectors whose repeated reads never
    agreed; bad: sectors that could not be read and became silence). `cancel` is called between chunks; True stops (returns None)."""
    t = next((x for x in toc['tracks'] if x['num'] == num), None)
    if t is None:
        raise CdError('There is no audio track %d on this disc.' % num)
    start, total = t['start'] - 150, t['frames']
    stats = {'retries': 0, 'suspect': 0, 'bad': 0}
    h = _open(letter)
    try:
        with open(out_path, 'wb') as f:
            f.write(_wav_header(total * SECTOR))
            done = 0
            while done < total:
                if cancel and cancel():
                    return None
                n = min(CHUNK, total - done)
                f.write(_secure_read(h, start + done, n, stats))
                done += n
                if progress:
                    progress(done, total)
    finally:
        _k32.CloseHandle(h)
    return {'seconds': total / 75.0, 'bytes': total * SECTOR, **stats}


# --------------------------------------------------------------------------------------------------- MusicBrainz
_mb_lock = threading.Lock()
_mb_last = [0.0]


def _get(url, accept='application/json', binary=False, timeout=25, tries=3):
    """GET with MusicBrainz's rules: at most one request a second, and a pause and retry when the server says it is busy (503)."""
    err = None
    for attempt in range(tries):
        with _mb_lock:
            wait = 1.1 - (time.time() - _mb_last[0])
            if wait > 0:
                time.sleep(wait)
            _mb_last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept}), timeout=timeout) as r:
                body = r.read(6_000_000)
                return body if binary else json.loads(body.decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = 'HTTP %d' % e.code
            if e.code not in (429, 502, 503, 504):
                break
            time.sleep(2 + 2 * attempt)
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = str(getattr(e, 'reason', e))
            time.sleep(1.5)
    raise CdError('MusicBrainz could not be reached (%s). Check the internet connection, or fill the details in by hand.' % err)


def _credit(ac):
    return ''.join((a.get('name') or (a.get('artist') or {}).get('name') or '') + (a.get('joinphrase') or '') for a in (ac or []) if isinstance(a, dict)).strip()


def _release(rel, ident=None, ntracks=None, lengths=None):
    """One MusicBrainz release as {id, title, artist, date, country, tracks: [{n, title, artist, seconds}], maxDiff}, using the medium that
    holds this disc (by disc ID), else the first one with the right number of tracks. maxDiff: the biggest difference in seconds between
    a track's length here and on the CD in the drive (None when the number of tracks differs): a real match is within a few seconds."""
    media = rel.get('media') or []
    medium = None
    if ident:
        medium = next((m for m in media if any(d.get('id') == ident for d in (m.get('discs') or []))), None)
    if medium is None and ntracks:
        medium = next((m for m in media if len(m.get('tracks') or []) == ntracks), None)
    if medium is None and media:
        medium = media[0]
    tracks = []
    for t in (medium or {}).get('tracks') or []:
        tracks.append({'n': len(tracks) + 1, 'title': t.get('title') or (t.get('recording') or {}).get('title') or '',
                       'artist': _credit(t.get('artist-credit') or (t.get('recording') or {}).get('artist-credit')),
                       'seconds': (t.get('length') or 0) / 1000.0})
    diff = None
    if lengths and len(lengths) == len(tracks) and all(t['seconds'] for t in tracks):
        diff = round(max(abs(a['seconds'] - b) for a, b in zip(tracks, lengths)), 1)
    return {'id': rel.get('id'), 'title': rel.get('title') or '', 'artist': _credit(rel.get('artist-credit')), 'date': rel.get('date') or '',
            'country': rel.get('country') or '', 'tracks': tracks, 'discs': len(media), 'maxDiff': diff,
            'medium': (medium or {}).get('position'), 'mediumTitle': (medium or {}).get('title') or ''}


_INC = 'artist-credits+recordings+discids'          # for /release/<id>
_INC_DISC = 'artist-credits+recordings'             # for /discid/<id> (it does not accept "discids")


def lookup(toc):
    """Releases for this disc: the exact disc-ID match, then (if none) the approximate match by track lengths. Returns
    {'releases': [...], 'how': 'discid' | 'toc' | None}."""
    ident = disc_id(toc)
    n = len(toc['tracks'])
    lengths = [t['seconds'] for t in toc['tracks']]
    data = _get('https://musicbrainz.org/ws/2/discid/%s?inc=%s&fmt=json' % (urllib.parse.quote(ident), _INC_DISC))
    if data and data.get('releases'):
        return {'releases': [_release(r, ident, n, lengths) for r in data['releases']], 'how': 'discid'}
    try:
        data = _get('https://musicbrainz.org/ws/2/discid/-?toc=%s&cdstubs=no&inc=%s&fmt=json' % (_toc_string(toc), _INC_DISC))
    except CdError:
        data = None                                                        # the approximate search is often busy; the exact one has answered
    if data and data.get('releases'):
        return {'releases': [_release(r, None, n, lengths) for r in data['releases']], 'how': 'toc'}
    return {'releases': [], 'how': None}


def _lucene(s):
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r'\\\1', s or '').strip()


def search(artist, album, ntracks=None):
    """Releases found by artist and album title. Track lists are fetched by release() when one is chosen."""
    parts = []
    if album:
        parts.append('release:"%s"' % _lucene(album))
    if artist:
        parts.append('artist:"%s"' % _lucene(artist))
    if not parts:
        raise CdError('Type an artist or an album title to search for.')
    if ntracks:
        parts.append('tracks:%d' % ntracks)
    data = _get('https://musicbrainz.org/ws/2/release?query=%s&limit=10&fmt=json' % urllib.parse.quote(' AND '.join(parts)))
    out = []
    for r in (data or {}).get('releases', []):
        out.append({'id': r.get('id'), 'title': r.get('title') or '', 'artist': _credit(r.get('artist-credit')), 'date': r.get('date') or '',
                    'country': r.get('country') or '', 'tracks': None, 'trackCount': r.get('track-count')})
    return out


def release(rid, ident=None, ntracks=None, lengths=None):
    data = _get('https://musicbrainz.org/ws/2/release/%s?inc=%s&fmt=json' % (urllib.parse.quote(rid), _INC))
    if not data:
        raise CdError('That release is no longer in MusicBrainz.')
    return _release(data, ident, ntracks, lengths)


def release_flat(rid):
    """A release with the tracks of ALL its discs / sides in one list (a vinyl album is often one medium with A1, A2 ... B1, B2 ...):
    {id, title, artist, date, country, tracks: [{n, label, title, artist, seconds}]}. Used to name tracks that were recorded from a record."""
    data = _get('https://musicbrainz.org/ws/2/release/%s?inc=%s&fmt=json' % (urllib.parse.quote(rid), _INC))
    if not data:
        raise CdError('That release is no longer in MusicBrainz.')
    media = data.get('media') or []
    tracks = []
    for m in media:
        for t in m.get('tracks') or []:
            tracks.append({'n': len(tracks) + 1, 'label': ('Disc %s ' % m.get('position') if len(media) > 1 else '') + str(t.get('number') or t.get('position') or ''),
                           'title': t.get('title') or (t.get('recording') or {}).get('title') or '',
                           'artist': _credit(t.get('artist-credit') or (t.get('recording') or {}).get('artist-credit')),
                           'seconds': (t.get('length') or 0) / 1000.0})
    return {'id': data.get('id'), 'title': data.get('title') or '', 'artist': _credit(data.get('artist-credit')), 'date': data.get('date') or '',
            'country': data.get('country') or '', 'tracks': tracks}


def acoustid_lookup(key, fingerprint, duration):
    """What AcoustID knows about a Chromaprint fingerprint: [{score, title, artist, album}] best first (score 0..1). Needs the internet and
    the user's free AcoustID application key."""
    body = urllib.parse.urlencode({'client': key, 'duration': int(round(duration)), 'fingerprint': fingerprint, 'meta': 'recordings releasegroups', 'format': 'json'}).encode()
    req = urllib.request.Request('https://api.acoustid.org/v2/lookup', body, {'User-Agent': USER_AGENT, 'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode('utf-8', 'replace'))
        except (ValueError, OSError):
            data = {}
        raise CdError((data.get('error') or {}).get('message') or 'AcoustID refused the request (HTTP %s).' % exc.code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CdError('AcoustID could not be reached (%s). Check the internet connection.' % exc)
    if data.get('status') != 'ok':
        raise CdError((data.get('error') or {}).get('message') or 'AcoustID gave an unexpected answer.')
    seen, out = set(), []
    for res in sorted(data.get('results') or [], key=lambda r: -(r.get('score') or 0)):
        for rec in res.get('recordings') or []:
            title = rec.get('title') or ''
            artist = ''.join((a.get('name') or '') + (a.get('joinphrase') or '') for a in (rec.get('artists') or [])).strip()
            groups = [g.get('title') for g in (rec.get('releasegroups') or []) if g.get('title')]
            key2 = (title.lower(), artist.lower())
            if not title or key2 in seen:
                continue
            seen.add(key2)
            out.append({'score': round(res.get('score') or 0, 2), 'title': title, 'artist': artist, 'album': groups[0] if groups else '', 'albums': groups[:6],
                    'seconds': rec.get('duration')})
    return out[:6]


def cover(rid):
    """The front cover (about 500 px) from the Cover Art Archive, as JPEG / PNG bytes, or None if there is none."""
    try:
        return _get('https://coverartarchive.org/release/%s/front-500' % urllib.parse.quote(rid), accept='image/*', binary=True, tries=2)
    except CdError:
        return None
