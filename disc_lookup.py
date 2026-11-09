"""Looks a standard (SP / LP) disc up online so that its artist, album and album art are known without anyone typing them.

A commercial or compilation MiniDisc usually holds only track titles (often "ARTIST - TITLE" in capitals) and a disc name. The disc name and
titles are searched for in MusicBrainz; a release is accepted only when most of its tracks match the disc's tracks by title and length. The artist
and album of the matched tracks are then remembered on this PC (a standard disc cannot store them, see catalogue.set_netmd_details) and the front
cover is fetched (Cover Art Archive, then iTunes / Deezer) and kept on this PC too, to be shown in Disc information. Nothing is written to the disc.

Only words from the disc (artist, album, track titles) are sent to the services, never any audio. DiscLookupMixin is mixed into himd_app.Api."""
import base64
import datetime
import difflib
import json
import math
import os
import re
import threading
import time
import urllib.parse

import cdrip
import cover_search
import lyrics
from mdm_paths import USER_DIR

LOOKUP_FILE = os.path.join(USER_DIR, 'disc-lookup.json')       # per disc: when it was looked up and what was found
COVER_DIR = os.path.join(USER_DIR, 'disc-covers')              # per disc: the album art found online (not stored on the disc)
RETRY_DAYS = 7                                                 # a disc that was not found is tried again after this long
_norm = lyrics._norm


def _top(values):
    count = {}
    for v in values:
        if v:
            count[v] = count.get(v, 0) + 1
    return max(count, key=count.get) if count else ''


def _queries(tracks, disc_title):
    """[(artist, album)] to search for, best first: from the tracks' own album / artist, else from the disc name ("Artist - Album", "Artist  Album",
    "Artist:Album" or just the album)."""
    artist, album = _top((t.get('artist') or '').strip() for t in tracks), _top((t.get('album') or '').strip() for t in tracks)
    title = (disc_title or '').strip()                              # double spaces kept: "ARTIST  ALBUM" is split on them below
    out = []
    if album:
        out.append((artist, album))
    elif title:
        parts = re.split(r'\s+[-–—:]\s+|\s{2,}|(?<=\S):(?=\S)', title, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out.append((parts[0].strip(), parts[1].strip()))
        out.append((artist, re.sub(r'\s+', ' ', title)))
    return list(dict.fromkeys(out))


def _score(tracks, rel):
    """How many of the disc's tracks are in this release (same title, length within 10 s): (count, {track number: release track})."""
    pool, found = list(rel['tracks']), {}
    for t in tracks:
        title = lyrics._split_title(t)[0]
        want = _norm(title)
        best, at = 0.0, None
        for i, r in enumerate(pool):
            if r['seconds'] and abs(r['seconds'] - t['seconds']) > 10:
                continue
            ratio = difflib.SequenceMatcher(None, want, _norm(r['title'])).ratio()
            if ratio > best:
                best, at = ratio, i
        if at is not None and best >= 0.85:
            found[t['number']] = pool.pop(at)
    return len(found), found


def _find_by_tracks(tracks, seen, need):
    """Searches MusicBrainz recordings for a handful of the disc's songs (artist + title) and takes the release that most of them appear on."""
    votes, probes, errors = {}, 0, 0
    step = max(1, len(tracks) // 10)
    for t in tracks[::step][:10]:
        title, artist = lyrics._split_title(t)
        if not artist or not title:
            continue
        try:
            data = cdrip._get('https://musicbrainz.org/ws/2/recording?query=%s&limit=40&fmt=json' % urllib.parse.quote(
                'recording:"%s" AND artist:"%s"' % (cdrip._lucene(re.sub(r'\([^)]*\)', ' ', title).strip()), cdrip._lucene(artist))), tries=3)
        except cdrip.CdError:
            errors += 1
            continue
        probes += 1
        mine = set()
        for rec in (data or {}).get('recordings', []):
            for rel in rec.get('releases') or []:
                if rel.get('id'):
                    mine.add(rel['id'])
        for rid in mine:
            votes[rid] = votes.get(rid, 0) + 1
    hit = (0, None, {})
    # A release that several of the songs appear on is a candidate; it is only accepted after its whole track list matches the disc (below),
    # so a low number of votes is safe.
    for rid, v in sorted(votes.items(), key=lambda x: -x[1])[:6]:
        if v < 2 or rid in seen:
            continue
        try:
            rel = cdrip.release_flat(rid)
        except cdrip.CdError:
            errors += 1
            continue
        n, found = _score(tracks, rel)
        if n > hit[0]:
            hit = (n, rel, found)
        if n >= 0.9 * len(tracks):
            break
    if hit[1] is not None and hit[0] >= need:
        return hit[1], hit[0], hit[2]
    if errors and probes < 2:
        raise cdrip.CdError('MusicBrainz did not answer properly. Try again in a minute.')       # not "not found": do not remember it as unknown
    return None


def find_release(tracks, disc_title):
    """(release, matched, {number: release track}) for the best MusicBrainz release, or None. Raises cdrip.CdError when MusicBrainz cannot be reached."""
    n = len(tracks)
    need = max(2, math.ceil(0.6 * n))
    seen, best, failures, asked = set(), (0, None, {}), 0, 0
    for artist, album in _queries(tracks, disc_title):
        for count in (n, None):                                   # first releases with this many tracks, then any
            try:
                cands = cdrip.search(artist, album, count)
                asked += 1
            except cdrip.CdError as exc:
                failures += 1
                if 'Type an artist' in str(exc):
                    continue
                if failures >= 2 and not asked:
                    raise
                continue
            for c in cands[:4]:
                if not c.get('id') or c['id'] in seen or len(seen) >= 10:
                    continue
                seen.add(c['id'])
                try:
                    rel = cdrip.release_flat(c['id'])
                except cdrip.CdError:
                    continue
                hit, found = _score(tracks, rel)
                if hit > best[0]:
                    best = (hit, rel, found)
                if hit >= 0.9 * n:
                    return rel, hit, found
            if best[0] >= 0.8 * n:
                break
    if best[1] is not None and best[0] >= need:
        return best[1], best[0], best[2]
    by_tracks = _find_by_tracks(tracks, seen, need)             # the disc name is not an album name (or is spelt differently): identify it from its songs
    if by_tracks:
        return by_tracks
    if failures and not asked:
        raise cdrip.CdError('MusicBrainz could not be reached. Check the internet connection.')
    return None


def _fetch_cover(release_id, artist, album):
    """The front cover as image bytes, or None: the Cover Art Archive picture of that very release, else a title-matched one from iTunes / Deezer / CAA."""
    b = cover_search._http('https://coverartarchive.org/release/%s/front-500' % release_id, binary=True, timeout=20, limit=3_000_000)
    if cover_search._is_image(b):
        return b
    for source in (cover_search._itunes, cover_search._deezer, cover_search._caa):
        try:
            found = source(artist, album)
        except Exception:
            continue
        for c in found:
            if difflib.SequenceMatcher(None, _norm(c['title']), _norm(album)).ratio() < 0.85:
                continue
            for url in c['full'][::-1]:                           # the smaller size first: it is only shown in a small box
                b = cover_search._http(url, binary=True, timeout=25, limit=3_000_000)
                if cover_search._is_image(b):
                    return b
    return None


def save_cover(key, data):
    os.makedirs(COVER_DIR, exist_ok=True)
    path = os.path.join(COVER_DIR, key + '.img')
    with open(path + '.tmp', 'wb') as f:
        f.write(data)
    os.replace(path + '.tmp', path)


def cover_bytes(key):
    """The saved cover of this disc as image bytes, or None."""
    if not key:
        return None
    try:
        with open(os.path.join(COVER_DIR, key + '.img'), 'rb') as f:
            b = f.read(4_000_000)
    except OSError:
        return None
    return b if cover_search._is_image(b) else None


def cover_url(key):
    """The saved cover of this disc as a data: address, or None."""
    if not key:
        return None
    try:
        with open(os.path.join(COVER_DIR, key + '.img'), 'rb') as f:
            b = f.read(4_000_000)
    except OSError:
        return None
    if not cover_search._is_image(b):
        return None
    return 'data:%s;base64,%s' % ('image/png' if b[:4] == b'\x89PNG' else 'image/jpeg', base64.b64encode(b).decode())


class DiscLookupMixin:
    def _dl_init(self):
        self._dl_lock = threading.Lock()                          # one lookup at a time
        self._dl_busy = False

    @staticmethod
    def _dl_read():
        try:
            with open(LOOKUP_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _dl_write(data):
        os.makedirs(USER_DIR, exist_ok=True)
        with open(LOOKUP_FILE + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(LOOKUP_FILE + '.tmp', LOOKUP_FILE)

    def _dl_cover_url(self, key):
        return cover_url(key)

    def _dl_due(self, key, force=False):
        """Should this disc be looked up now? Not when it was found already, or not found within the last RETRY_DAYS."""
        if force:
            return True
        old = self._dl_read().get(key)
        if not old:
            return True
        if old.get('found'):
            return False
        try:
            return (datetime.datetime.now() - datetime.datetime.fromisoformat(old.get('when'))).days >= RETRY_DAYS
        except (TypeError, ValueError):
            return True

    def _dl_run(self, force=False, progress=None):
        """Looks the loaded standard disc up and keeps what is found on this PC. Returns {found, album, artist, matched, total, cover, key, changed}
        ({'skipped': True} when there is nothing to do, {'error'} when the services cannot be reached)."""
        if not self._loaded_netmd or not self._tracks:
            return {'skipped': True}
        tracks = list(self._tracks)
        key = self._netmd_disc_key(tracks)
        if not key:
            return {'skipped': True}
        with self._dl_lock:
            if not self._dl_due(key, force):
                return {'skipped': True, 'key': key}
            if progress:
                progress()
            try:
                hit = find_release(tracks, getattr(self, '_netmd_disc_title', ''))
            except cdrip.CdError as exc:
                return {'error': str(exc), 'key': key}
            data = self._dl_read()
            when = datetime.datetime.now().isoformat(timespec='seconds')
            if hit is None:
                data[key] = {'when': when, 'found': False}
                self._dl_write(data)
                return {'found': False, 'key': key, 'total': len(tracks)}
            rel, matched, found = hit
            items = []
            for t in tracks:
                r = found.get(t['number'])
                if not r:
                    continue
                items.append({'number': t['number'], 'artist': None if t.get('artist') else (r['artist'] or rel['artist']), 'album': None if t.get('album') else rel['title']})
            changed = bool(items)
            if items:
                self.set_netmd_details(self._netmd_from, items)
            have_cover = cover_url(key) is not None
            if not have_cover:
                if progress:
                    progress('cover')
                try:
                    pic = _fetch_cover(rel['id'], rel['artist'], rel['title'])
                except Exception:
                    pic = None
                if pic:
                    save_cover(key, pic)
                    have_cover = changed = True
            data[key] = {'when': when, 'found': True, 'release': rel['id'], 'album': rel['title'], 'artist': rel['artist']}
            self._dl_write(data)
            return {'found': True, 'key': key, 'album': rel['title'], 'artist': rel['artist'], 'matched': matched, 'total': len(tracks), 'cover': have_cover, 'changed': changed}

    # -- called by the page ------------------------------------------------------------------------------
    def disc_lookup(self, index):
        """The "Look up online" button: artist, album and album art for the standard disc that is showing (tried again even if tried before)."""
        if not self._is_netmd(index):
            return {'error': 'This looks up standard discs; a Hi-MD disc keeps its own artist and album.'}
        r = self._dl_run(force=True)
        if r.get('error'):
            return {'error': r['error']}
        return r

    def cover_pc_remove(self):
        """Forgets the album art kept on this PC for the standard disc that is showing."""
        key = self._netmd_disc_key(self._tracks) if self._loaded_netmd else None
        if key:
            try:
                os.remove(os.path.join(COVER_DIR, key + '.img'))
            except OSError:
                pass
        return {'ok': True}

    def _dl_background(self):
        """After a standard disc has loaded: when it is a pre-recorded commercial disc that lacks an artist or a picture, look it up once in the
        background, telling the page what is happening (the line under the disc name)."""
        tracks = list(self._tracks)
        key = self._netmd_disc_key(tracks) if tracks else None
        if (not key or not getattr(self, '_netmd_commercial', False) or self._dl_busy
                or not (any(not t.get('artist') for t in tracks) or cover_url(key) is None) or not self._dl_due(key)):
            return
        self._dl_busy = True

        def tell(msg):
            if self._window:
                try:
                    self._window.evaluate_js('window.onDiscLookup && window.onDiscLookup(%s)' % json.dumps(dict(msg, key=key)))
                except Exception:
                    pass

        def work():
            try:
                time.sleep(1.5)                                       # let the page finish drawing the disc first
                tell({'stage': 'lookup'})
                r = self._dl_run(progress=lambda what=None: tell({'stage': 'cover' if what else 'lookup'}))
                if r.get('error'):
                    tell({'stage': 'error', 'text': r['error']})
                elif r.get('found'):
                    tell({'stage': 'done', 'changed': bool(r.get('changed')), 'album': r.get('album'), 'artist': r.get('artist'), 'cover': bool(r.get('cover')),
                          'matched': r.get('matched'), 'total': r.get('total')})
                elif r.get('skipped'):
                    tell({'stage': 'idle'})
                else:
                    tell({'stage': 'none'})
            except Exception:
                tell({'stage': 'idle'})
            finally:
                self._dl_busy = False
        threading.Thread(target=work, daemon=True).start()
