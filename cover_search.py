"""Album art suggestions: looks an album up by artist and album title in free online databases and offers the covers it finds.

Sources (none needs an account or key; only the artist and album words are sent, never any audio):
  - MusicBrainz release groups, with the picture from the Cover Art Archive (widest coverage, old and obscure records too)
  - iTunes Search (a public search service; clean high-resolution fronts for mainstream releases)
  - Deezer (a second public fallback)
The user picks one; it is then downloaded and goes through the same cover_prepare / cover_set path as a picture chosen from a file.
Hi-MD discs only: a standard disc cannot hold a picture."""
import base64
import concurrent.futures
import difflib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import cdrip

UA = 'MiniDiscManager/0.16 ( personal use )'
MAX_CANDIDATES = 12


def _http(url, binary=False, timeout=15, limit=12_000_000):
    """One GET (redirects followed). Returns bytes / parsed JSON, or None when the server has nothing (404) or cannot be reached."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'image/*' if binary else 'application/json'}), timeout=timeout) as r:
            body = r.read(limit)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if binary:
        return body
    try:
        return json.loads(body.decode('utf-8', 'replace'))
    except ValueError:
        return None


def _is_image(b):
    return bool(b) and (b[:3] == b'\xff\xd8\xff' or b[:8] == b'\x89PNG\r\n\x1a\n' or b[:4] == b'RIFF' or b[:3] == b'GIF')


def _q(s):
    return urllib.parse.quote(s or '')


def _caa(artist, album):
    out = []
    parts = ['releasegroup:"%s"' % cdrip._lucene(album)] if album else []
    if artist:
        parts.append('artist:"%s"' % cdrip._lucene(artist))
    if not parts:
        return out
    try:
        data = cdrip._get('https://musicbrainz.org/ws/2/release-group?query=%s&limit=8&fmt=json' % _q(' AND '.join(parts)), tries=3)
    except cdrip.CdError:
        return out
    for g in (data or {}).get('release-groups', []):
        gid = g.get('id')
        if not gid:
            continue
        out.append({'source': 'Cover Art Archive', 'title': g.get('title') or '', 'artist': cdrip._credit(g.get('artist-credit')),
                    'year': (g.get('first-release-date') or '')[:4],
                    'thumb': 'https://coverartarchive.org/release-group/%s/front-250' % gid,
                    'full': ['https://coverartarchive.org/release-group/%s/front-1200' % gid, 'https://coverartarchive.org/release-group/%s/front-500' % gid]})
    return out


def _itunes(artist, album):
    term = ' '.join(x for x in (artist, album) if x)
    data = _http('https://itunes.apple.com/search?term=%s&entity=album&limit=8' % _q(term))
    out = []
    for r in (data or {}).get('results', []):
        a = r.get('artworkUrl100') or ''
        if '100x100' not in a:
            continue
        out.append({'source': 'iTunes', 'title': r.get('collectionName') or '', 'artist': r.get('artistName') or '', 'year': (r.get('releaseDate') or '')[:4],
                    'thumb': a.replace('100x100', '250x250'), 'full': [a.replace('100x100', '1000x1000'), a.replace('100x100', '600x600')]})
    return out


def _deezer(artist, album):
    term = ' '.join(x for x in (artist, album) if x)
    data = _http('https://api.deezer.com/search/album?q=%s&limit=8' % _q(term))
    out = []
    for r in (data or {}).get('data', []):
        if not r.get('cover_medium'):
            continue
        out.append({'source': 'Deezer', 'title': r.get('title') or '', 'artist': (r.get('artist') or {}).get('name') or '', 'year': '',
                    'thumb': r.get('cover_medium'), 'full': [x for x in (r.get('cover_xl'), r.get('cover_big')) if x]})
    return out


class CoverSearchMixin:
    _cover_cands = []

    def cover_find(self, artist, album):
        """Covers for this artist / album: {cands: [{i, source, title, artist, year, thumb (a data: URL)}]} or {error}. Reads nothing from the disc."""
        artist, album = (artist or '').strip(), (album or '').strip()          # a standard disc cannot hold the picture: a chosen one is kept on this PC
        if not artist and not album:
            return {'error': 'Type an artist or an album title to search for.'}
        found, failed = {}, 0
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            jobs = {'caa': pool.submit(_caa, artist, album), 'itunes': pool.submit(_itunes, artist, album), 'deezer': pool.submit(_deezer, artist, album)}
            for k, j in jobs.items():
                try:
                    found[k] = j.result(timeout=60)
                except Exception:
                    found[k] = []
                    failed += 1
        # the best of each source in turn, so one source cannot crowd out the others; Deezer only when the others gave few
        order, seen = [], set()
        lists = [found['itunes'], found['caa']] + ([found['deezer']] if len(found['itunes']) + len(found['caa']) < 4 else [])
        for rank in range(8):
            for lst in lists:
                if rank < len(lst):
                    c = lst[rank]
                    key = (c['title'].lower(), c['artist'].lower(), c['source'])
                    if key not in seen:
                        seen.add(key)
                        order.append(c)
        def norm(s):
            return ' '.join(''.join(ch if ch.isalnum() else ' ' for ch in (s or '').lower()).split())

        def score(c):                                                 # how closely title and artist match what was typed (stable sort keeps the source mix for ties)
            s = 2.0 * difflib.SequenceMatcher(None, norm(c['title']), norm(album)).ratio() if album else 1.0
            if artist:
                s += difflib.SequenceMatcher(None, norm(c['artist']), norm(artist)).ratio()
            return s
        order.sort(key=score, reverse=True)
        order = order[:MAX_CANDIDATES + 6]
        with concurrent.futures.ThreadPoolExecutor(6) as pool:        # thumbnails, as data: URLs so the page needs no outside access
            blobs = list(pool.map(lambda c: _http(c['thumb'], binary=True, limit=2_000_000), order))
        cands, keep = [], []
        for c, b in zip(order, blobs):
            if not _is_image(b):
                continue                                              # no picture for that release (the Cover Art Archive often has none)
            mime = 'image/png' if b[:4] == b'\x89PNG' else 'image/jpeg'
            keep.append({'full': c['full'], 'title': c['title'], 'artist': c['artist']})
            cands.append({'i': len(cands), 'source': c['source'], 'title': c['title'], 'artist': c['artist'], 'year': c['year'],
                          'thumb': 'data:%s;base64,%s' % (mime, base64.b64encode(b).decode())})
            if len(cands) >= MAX_CANDIDATES:
                break
        self._cover_cands = keep
        if not cands:
            if failed == 3 or not any(found.values()):
                return {'cands': [], 'note': 'Nothing was found for that. Check the spelling, try fewer words, or check the internet connection.'}
            return {'cands': [], 'note': 'Albums were found, but none of them has a picture online.'}
        return {'cands': cands}

    def cover_pick(self, i):
        """Downloads the chosen cover and prepares it for the disc exactly like a picture chosen from a file: {tmp, bytes, preview} or {error}."""
        try:
            c = self._cover_cands[int(i)]
        except (IndexError, ValueError, TypeError):
            return {'error': 'Search again: that list is no longer available.'}
        data = next((b for b in (_http(u, binary=True, timeout=30) for u in c['full']) if _is_image(b)), None)
        if data is None:
            return {'error': 'The picture could not be downloaded. Check the internet connection and try another one.'}
        if self._loaded_netmd:                                        # standard disc: kept on this PC, shown in Disc information
            import disc_lookup
            key = self._netmd_disc_key(self._tracks)
            if not key:
                return {'error': 'There is no disc loaded to keep the picture for.'}
            disc_lookup.save_cover(key, data)
            return {'pcSaved': True}
        folder = tempfile.mkdtemp(prefix='mdm-coverdl-')
        try:
            path = os.path.join(folder, 'download.img')
            with open(path, 'wb') as f:
                f.write(data)
            return self.cover_prepare(path)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
