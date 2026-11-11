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
import discogs
import lyrics
from mdm_paths import USER_DIR

LOOKUP_FILE = os.path.join(USER_DIR, 'disc-lookup.json')       # per disc: when it was looked up and what was found
COVER_DIR = os.path.join(USER_DIR, 'disc-covers')              # per disc: the album art found online (not stored on the disc)
RETRY_DAYS = 7                                                 # a disc that was not found is tried again after this long
_norm = lyrics._norm


_LEAD_NO = re.compile(r'^\s*\d{1,3}\s*[.):\-\u2013]\s*')                         # "01. ", "1) ", "02 - " at the start of a track title
_TAIL_YEAR = re.compile(r'\s*[(\[]\s*(?:19|20)\d\d\s*[)\]]\s*$')                  # "Toy (2016)": the year in brackets after an album name


def _clean_track(title):
    """A track title without a leading track number ("01. Limbo" -> "Limbo"): discs are often named that way."""
    t = _LEAD_NO.sub('', title or '').strip()
    return t or (title or '').strip()


def _clean_album(album):
    """An album name without a year in brackets at the end ("Toy (2016)" -> "Toy"), which the release is usually not listed with."""
    a = _TAIL_YEAR.sub('', album or '').strip()
    return a or (album or '').strip()


def _with_hint(tracks, hint):
    """The tracks with an artist / album filled in from a hint ({artist, album} from the lyrics searches) where they have none, so the search starts from them."""
    if not hint or not (hint.get('artist') or hint.get('album')):
        return tracks
    out = []
    for t in tracks:
        t2 = dict(t)
        if hint.get('artist') and not t2.get('artist'):
            t2['artist'] = hint['artist']
        if hint.get('album') and not t2.get('album'):
            t2['album'] = hint['album']
        out.append(t2)
    return out


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
        out.append((artist, _clean_album(album)))
        out.append((artist, album))
    elif title:
        parts = re.split(r'\s+[-–—:]\s+|\s{2,}|(?<=\S):(?=\S)', title, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out.append((parts[0].strip(), _clean_album(parts[1].strip())))
            out.append((parts[0].strip(), parts[1].strip()))
        out.append((artist, _clean_album(re.sub(r'\s+', ' ', title))))
        out.append((artist, re.sub(r'\s+', ' ', title)))
    for a, b in list(out):                                          # looser variants: no leading "The", the album alone (the artist may be spelt differently or "Various Artists")
        b2 = re.sub(r'^(?:the|a)\s+', '', b, flags=re.I)
        out.append((a, b2))
        if a:
            out.append(('', b))
            out.append(('', b2))
    return [q for q in dict.fromkeys(out) if q[0] or q[1]]


_BRACKETS = re.compile(r'\s*[(\[][^)\]]*[)\]]')                                   # "(Remastered 2009)", "[live]"
_FEAT = re.compile(r'\s+(?:feat\.?|ft\.?|featuring|with)\s+.*$', re.I)


def _loose(title):
    """A title boiled down for comparing: no brackets, no "feat. ...", no leading "The" / "A", only letters and digits."""
    t = _FEAT.sub('', _BRACKETS.sub('', title or ''))
    t = re.sub(r'^(?:the|a|an)\s+', '', t.strip(), flags=re.I)
    return _norm(t)


def _same(a, b):
    """How alike two track titles are, 0-1: the better of the exact comparison and the loose one (brackets / feat. / The ignored)."""
    r = difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()
    la, lb = _loose(a), _loose(b)
    if la and lb:
        r = max(r, difflib.SequenceMatcher(None, la, lb).ratio())
    return r


def _score(tracks, rel, tol=10, floor=0.85):
    """How many of the disc's tracks are in this release (same title, length within `tol` s; tol None = ignore lengths, for releases that list
    none or wrong ones): (count, {track number: release track})."""
    pool, found = list(rel['tracks']), {}
    for t in tracks:
        title = _clean_track(lyrics._split_title(t)[0])
        best, at = 0.0, None
        for i, r in enumerate(pool):
            if tol is not None and r['seconds'] and t.get('seconds') and abs(r['seconds'] - t['seconds']) > tol:
                continue
            ratio = _same(title, r['title'])
            if ratio > best:
                best, at = ratio, i
        if at is not None and best >= floor:
            found[t['number']] = pool.pop(at)
    return len(found), found


def _find_by_tracks(tracks, seen, need):
    """Searches MusicBrainz recordings for a handful of the disc's songs (artist + title) and takes the release that most of them appear on."""
    votes, probes, errors = {}, 0, 0
    step = max(1, len(tracks) // 10)
    for t in tracks[::step][:10]:
        title, artist = lyrics._split_title(t)
        title = _clean_track(title)
        if not title:
            continue
        clean = cdrip._lucene(re.sub(r'\([^)]*\)', ' ', title).strip())
        if not clean:
            continue
        # With an artist ("ARTIST - TITLE" on the disc) search that pair; with none (a disc that only has song titles) search the title alone and let
        # the releases the songs have in common decide: the release is still only accepted after most of the disc's tracks match its track list.
        query = 'recording:"%s" AND artist:"%s"' % (clean, cdrip._lucene(artist)) if artist else 'recording:"%s"' % clean
        try:
            data = cdrip._get('https://musicbrainz.org/ws/2/recording?query=%s&limit=40&fmt=json' % urllib.parse.quote(query), tries=3)
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


def _discogs_find(tracks, queries, need, rels):
    """The same search on Discogs (obscure pressings, compilations): by artist + album, then by a few of the songs. Capped, as Discogs allows
    only a few requests a minute. Returns (release, matched, {number: release track}) or None."""
    n = len(tracks)
    ids, hit = [], (0, None, {})
    for artist, album in queries[:4]:
        try:
            for c in discogs.search(artist, album)[:4]:
                if c['id'] not in ids:
                    ids.append(c['id'])
        except cdrip.CdError:
            break
    votes = {}
    step = max(1, n // 3)
    for t in tracks[::step][:3]:
        title, artist = lyrics._split_title(t)
        title = _clean_track(title)
        if not title:
            continue
        try:
            for c in discogs.search_track(artist, re.sub(r'\([^)]*\)', ' ', title).strip())[:10]:
                votes[c['id']] = votes.get(c['id'], 0) + 1
        except cdrip.CdError:
            break
    ids += [rid for rid, v in sorted(votes.items(), key=lambda x: -x[1]) if v >= 2 and rid not in ids]
    for rid in ids[:7]:
        key = 'discogs:' + rid
        try:
            rel = rels.get(key) or discogs.release(rid)
        except cdrip.CdError:
            continue
        rels[key] = rel
        for tol, floor in ((10, 0.85), (None, 0.9)):
            got, found = _score(tracks, rel, tol, floor)
            if got > hit[0]:
                hit = (got, rel, found)
        if hit[0] >= 0.9 * n:
            break
    if hit[1] is not None and hit[0] >= need:
        return hit[1], hit[0], hit[2]
    return None


def find_release(tracks, disc_title):
    """(release, matched, {number: release track}) for the best release found, or None: MusicBrainz first (by the disc name, then by the songs),
    then Discogs. Titles are compared loosely (brackets, "feat.", "The" ignored) and, as a last try, without the lengths.
    Raises cdrip.CdError when MusicBrainz cannot be reached."""
    n = len(tracks)
    need = max(2, math.ceil(0.6 * n))
    seen, best, failures, asked = set(), (0, None, {}), 0, 0
    rels = {}                                                  # releases already fetched, so the last tries do not ask again
    queries = _queries(tracks, disc_title)
    for artist, album in queries:
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
                if not c.get('id') or c['id'] in seen or len(seen) >= 12:
                    continue
                seen.add(c['id'])
                try:
                    rel = cdrip.release_flat(c['id'])
                except cdrip.CdError:
                    continue
                rels[c['id']] = rel
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
    for rel in list(rels.values()):                             # lengths in MusicBrainz are often missing or off on obscure releases: try the releases found again without them
        got, found = _score(tracks, rel, None, 0.9)
        if got > best[0]:
            best = (got, rel, found)
    if best[1] is not None and best[0] >= need:
        return best[1], best[0], best[2]
    if failures and not asked:
        raise cdrip.CdError('MusicBrainz could not be reached. Check the internet connection.')
    return _discogs_find(tracks, queries, need, rels)


def search_releases(artist, album, ntracks=None):
    """For the "search by hand" window: releases from MusicBrainz and Discogs for what the user typed, those with this disc's number of tracks first.
    A source that cannot be reached is named in 'notes' instead of failing the whole search."""
    out, notes = [], []
    artist, album = (artist or '').strip(), (album or '').strip()
    if not (artist or album):
        raise cdrip.CdError('Type an artist or an album title to search for.')
    try:
        for r in cdrip.search(artist, album, None):
            r['source'] = 'musicbrainz'
            out.append(r)
    except cdrip.CdError as exc:
        notes.append(str(exc))
    try:
        out += discogs.search(artist, album)
    except cdrip.CdError as exc:
        notes.append(str(exc))
    if not out and notes:
        raise cdrip.CdError(' '.join(notes))
    if ntracks:
        out.sort(key=lambda r: 0 if r.get('trackCount') == ntracks else 1)       # stable: otherwise the sources keep their order
    return out, notes


def fetch_release(source, rid):
    """A release with its tracks in one list, from MusicBrainz ('musicbrainz') or Discogs ('discogs')."""
    if source == 'discogs':
        return discogs.release(rid)
    rel = cdrip.release_flat(rid)
    rel['source'] = 'musicbrainz'
    return rel


def match_by_hand(tracks, rel):
    """(matched, {number: release track}, by_position) for a release the user chose: by title, then without the lengths, then (when it has as
    many tracks as the disc) simply track for track, since the user vouches for the album."""
    n, found = _score(tracks, rel)
    if n < len(tracks):
        n2, found2 = _score(tracks, rel, None, 0.8)
        if n2 > n:
            n, found = n2, found2
    if n < max(1, len(tracks) // 2) and len(rel['tracks']) == len(tracks):
        found = {t['number']: rel['tracks'][i] for i, t in enumerate(sorted(tracks, key=lambda t: t['number']))}
        return len(found), found, True
    return n, found, False


def _fetch_cover(release_id, artist, album, image=None):
    """The front cover as image bytes, or None: a Discogs release's own picture, else the Cover Art Archive picture of that very release, else a
    title-matched one from iTunes / Deezer / CAA."""
    if image:
        b = cover_search._http(image, binary=True, timeout=20, limit=3_000_000)
        if cover_search._is_image(b):
            return b
    elif release_id:
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

    def _dl_run(self, force=False, progress=None, hint=None, chosen=None):
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
                hit = chosen or find_release(_with_hint(tracks, hint), getattr(self, '_netmd_disc_title', ''))
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
                    pic = _fetch_cover(None if rel.get('source') == 'discogs' else rel['id'], rel['artist'], rel['title'], rel.get('image'))
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

    def auto_identify(self, index, steps, disc_title='', hint=None, chosen=None):
        """The "missing details" window's automatic mode: finds the album online by the disc's track names and lengths and, with no questions asked,
        fills in what is missing. `steps`: 'names' (artist / album, and the title of an untitled track) and / or 'cover'.
        Standard disc: kept on this PC only, as the "Look up online" button does. Hi-MD disc: the artist / album are written to the disc's track
        index (only fields that are empty; an existing title is never changed) and the cover is stored as the disc picture (rehearsed first).
        `hint` ({artist, album}, optional): what the lyrics searches say the songs are by / from, searched for first when the disc's own names found nothing.
        Only a release that matches most of the disc's tracks is accepted. Returns {found, artist, album, matched, total, namesSet, cover}."""
        steps = set(steps or [])
        if not steps & {'names', 'cover'}:
            return {'ok': True, 'found': False, 'skipped': True}

        def tell(stage, **kw):                                        # what is happening now, for the progress window
            if self._window:
                try:
                    self._window.evaluate_js('window.onAutoIdentify && window.onAutoIdentify(%s)' % json.dumps(dict(kw, stage=stage)))
                except Exception:
                    pass
        tell('search')
        hint = hint if isinstance(hint, dict) else {}
        if self._is_netmd(index):
            r = self._dl_run(force=True, progress=lambda what=None: tell('cover' if what else 'search'), hint=hint, chosen=chosen)
            if r.get('error'):
                return {'error': r['error']}
            return {'ok': True, 'found': bool(r.get('found')), 'artist': r.get('artist', ''), 'album': r.get('album', ''), 'matched': r.get('matched', 0),
                    'total': r.get('total', len(self._tracks)), 'namesSet': r.get('matched', 0) if r.get('found') else 0, 'cover': 'kept on this PC' if r.get('cover') else None}
        tracks = list(self._tracks)
        if not tracks:
            return {'error': 'Reload the disc first.'}
        try:
            hit = chosen or find_release(_with_hint(tracks, hint), disc_title or '')
        except cdrip.CdError as exc:
            return {'error': str(exc)}
        if hit is None:
            return {'ok': True, 'found': False, 'total': len(tracks)}
        rel, matched, found = hit
        out = {'ok': True, 'found': True, 'artist': rel['artist'], 'album': rel['title'], 'matched': matched, 'total': len(tracks), 'namesSet': 0, 'cover': None}
        tell('found', artist=rel['artist'], album=rel['title'], matched=matched, total=len(tracks))
        if 'names' in steps:
            items = []
            for t in tracks:
                r = found.get(t['number'])
                if not r:
                    continue
                untitled = t['title'] in ('', '(untitled)')
                artist = None if t.get('artist') else (r['artist'] or rel['artist'])
                album = None if t.get('album') else rel['title']
                if untitled or artist or album:
                    items.append({'number': t['number'], 'title': (r['title'] if untitled else t['title']), 'artist': artist, 'album': album})
            if items:
                tell('names', count=len(items))
                res = self.rename_tracks_each(index, items)
                if 'error' in res:
                    out['namesError'] = res['error']
                else:
                    out['namesSet'] = len(items)
        if 'cover' in steps:
            tell('cover')
            try:
                pic = _fetch_cover(None if rel.get('source') == 'discogs' else rel['id'], rel['artist'], rel['title'], rel.get('image'))
            except Exception:
                pic = None
            if not pic:
                out['cover'] = 'none found'
            else:
                import tempfile
                fd, path = tempfile.mkstemp(suffix='.img', prefix='mdm-autocover-')
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(pic)
                    tell('coverstore')
                    prep = self.cover_prepare(path)
                    if 'error' in prep:
                        out['cover'] = 'failed: ' + prep['error']
                    else:
                        rehearsal = self.cover_set(index, prep['tmp'], True)
                        if 'error' in rehearsal:
                            out['cover'] = 'failed: ' + rehearsal['error']
                        else:
                            res = self.cover_set(index, prep['tmp'], False)
                            out['cover'] = 'failed: ' + res['error'] if 'error' in res else 'stored on the disc'
                finally:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        return out

    def disc_search(self, artist, album):
        """The "Search by hand" window: releases from MusicBrainz and Discogs for the artist / album the user typed. Returns {releases, notes} or {error}."""
        try:
            releases, notes = search_releases(artist, album, len(self._tracks) or None)
        except cdrip.CdError as exc:
            return {'error': str(exc)}
        return {'releases': releases, 'notes': notes, 'tracks': len(self._tracks)}

    def disc_apply(self, index, source, rid, steps=None):
        """Uses the release the user picked in the "Search by hand" window: fills in the artist and album (and the title of an untitled track) and the
        album art exactly as the automatic lookup does (a standard disc: kept on this PC; a Hi-MD disc: written to the disc, rehearsed first).
        The tracks are matched by title, then without lengths, then one for one when the release has as many tracks as the disc."""
        tracks = list(self._tracks)
        if not tracks:
            return {'error': 'Reload the disc first.'}
        try:
            rel = fetch_release(source, rid)
        except cdrip.CdError as exc:
            return {'error': str(exc)}
        matched, found, by_position = match_by_hand(tracks, rel)
        if not found:
            return {'error': 'None of the tracks on this disc could be matched to that release’s track list (%d tracks listed, %d on the disc).' % (len(rel['tracks']), len(tracks))}
        steps = steps or ['names', 'cover']
        if self._is_netmd(index):
            r = self._dl_run(force=True, chosen=(rel, matched, found))
            if r.get('error'):
                return {'error': r['error']}
            out = {'ok': True, 'found': True, 'artist': rel['artist'], 'album': rel['title'], 'matched': matched, 'total': len(tracks), 'cover': 'kept on this PC' if r.get('cover') else None}
        else:
            out = self.auto_identify(index, steps, '', None, chosen=(rel, matched, found))
            if out.get('error'):
                return out
        out['byPosition'] = by_position
        return out

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
        if (not key or not getattr(self, '_netmd_commercial', False) or self._dl_busy or not self._app_setting('autoLookupCommercial')
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
