"""Lyrics for tracks: found online (LRCLIB, a community database of timed lyrics) or loaded from an .lrc / .txt file, kept on this PC, and
copied onto a Hi-MD disc as one small file (/LYRICS.TXT in the root folder, next to TRACKS.CSV and COVER.JPG) so they travel with the disc.
The page shows them in time with the track that is playing. LyricsMixin is mixed into himd_app.Api.

A lyrics entry belongs to a track by title, artist and length (a Hi-MD track has no ID of its own that survives a rename), like the saved copies.
Only the track's artist, title, album and length are sent to lrclib.net; no audio is."""
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from mdm_paths import BACKUP_DIR, USER_DIR

LYRICS_FILE = os.path.join(USER_DIR, 'lyrics.json')                  # every lyric this PC knows, whatever disc the track is on
DISC_NAME = 'LYRICS.TXT'                                             # the copy kept in the root folder of a Hi-MD disc
API = 'https://lrclib.net/api'
UA = 'MiniDiscManager (personal lyrics lookup)'
_TS = re.compile(r'\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]')


def _norm(s):
    s = re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', (s or '').lower())                     # "(Remastered)", "[Live]" ...
    s = re.sub(r'\b(?:feat|ft|featuring)\b.*$', ' ', s)                              # "Song feat. Someone"
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    return re.sub(r'^the ', '', s)


def _split_title(t):
    """(title, artist) to search with. Commercial and compilation discs often hold "ARTIST - TITLE" in the title and no artist: with the artist empty,
    the part before the first " - " (or " -") is taken as the artist, so the lookup is by the real song name."""
    title, artist = (t.get('title') or '').strip(), (t.get('artist') or '').strip()
    m = re.match(r'^(.+?)\s+-\s*(\S.*)$|^(.+?)\s*-\s+(\S.*)$', title)
    if m:
        a, s = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if len(_norm(a)) >= 2 and len(_norm(s)) >= 1 and (not artist or _artist_ok(a, artist)):    # a known artist is also taken off the front of the title
            return s.strip(), artist or a.strip()
    return title, artist


def _artist_ok(a, b):
    """The same artist, allowing for "The Beatles" / "Beatles" and "A & B" / "A"; an unknown artist on either side does not stop a match."""
    a, b = _norm(a), _norm(b)
    if not a or not b or a == b or a in b or b in a:
        return True
    return bool({w for w in a.split() if len(w) > 2} & {w for w in b.split() if len(w) > 2})


def parse_lrc(text):
    """[(seconds, line)] from LRC text (several stamps on one line are fine), sorted; plain text without stamps gives []."""
    out = []
    for raw in (text or '').splitlines():
        stamps = _TS.findall(raw)
        if not stamps:
            continue
        line = _TS.sub('', raw).strip()
        if re.match(r'^\[[a-zA-Z]+:', raw.strip()):                                  # [ar:..] [ti:..] tags are not lyrics
            continue
        for m, s, frac in stamps:
            out.append((int(m) * 60 + int(s) + (int(frac) / (10 ** len(frac)) if frac else 0.0), line))
    out.sort(key=lambda x: x[0])
    return out


def _same(entry, title, artist, seconds):
    if _norm(entry.get('title')) != _norm(title) or abs(float(entry.get('seconds') or 0) - float(seconds or 0)) > 2.5:
        return False
    a, b = _norm(entry.get('artist')), _norm(artist)
    return not a or not b or a == b                                                  # an unknown artist on either side does not stop a match


def _get(url, timeout=20, headers=None, data=None):
    req = urllib.request.Request(url, headers=dict({'User-Agent': UA}, **(headers or {})), data=urllib.parse.urlencode(data).encode() if data else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


# NetEase Cloud Music: a very large catalogue with timed lyrics, no key needed. These two calls are the ones its own web player makes.
NE_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com', 'Cookie': 'appver=2.0.2'}
_CREDIT = re.compile(r'^\s*(?:作词|作曲|编曲|制作人|制作|词|曲|混音|录音|母带|监制|企划|出品|发行|吉他|贝斯|鼓|和声|OP|SP|lyrics by|composed by|written by|produced by|arranged by)\s*[:：]', re.I)


def _ne_clean(lrc):
    """NetEase's lyrics start with credit lines ("作词 : ..."); they are not lyrics."""
    keep = [ln for ln in (lrc or '').replace('\r\n', '\n').split('\n') if not _CREDIT.match(_TS.sub('', ln))]
    return '\n'.join(keep).strip()


def _ne_search(query):
    out = _get('https://music.163.com/api/cloudsearch/pc', headers=NE_HEADERS, data={'s': query, 'type': 1, 'limit': 8, 'offset': 0})
    return [{'id': s['id'], 'title': s.get('name') or '', 'artist': ' & '.join(a.get('name') or '' for a in s.get('ar') or []), 'album': (s.get('al') or {}).get('name') or '',
             'duration': float(s.get('dt') or 0) / 1000} for s in ((out.get('result') or {}).get('songs') or []) if isinstance(s, dict) and s.get('id')]


def _ne_lyric(song_id):
    out = _get('https://music.163.com/api/song/lyric?id=%s&lv=1&kv=1&tv=-1' % song_id, headers=NE_HEADERS)
    text = _ne_clean(((out.get('lrc') or {}).get('lyric')) or '')
    return '' if '纯音乐' in text and len(text) < 120 else text                       # "pure music, please enjoy": an instrumental


class LyricsMixin:
    def _ly_init(self):
        self._ly_disc = []                    # the entries found in /LYRICS.TXT on the disc now showing (Hi-MD)
        self._ly_cands = {}                   # track number -> the candidates of the last online search

    # -- the PC's own store ------------------------------------------------------------------
    @staticmethod
    def _ly_read():
        try:
            with open(LYRICS_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    @staticmethod
    def _ly_write(items):
        os.makedirs(USER_DIR, exist_ok=True)
        tmp = LYRICS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, LYRICS_FILE)

    @staticmethod
    def _ly_find(items, title, artist, seconds):
        return next((e for e in items if _same(e, title, artist, seconds)), None)

    def _ly_track(self, number):
        return next((t for t in self._tracks if t['number'] == int(number)), None)

    def _ly_put(self, t, text, source, synced=None, offset=None):
        """Stores `text` (LRC or plain) as the lyrics of track `t`, replacing any earlier ones for it."""
        items = [e for e in self._ly_read() if not _same(e, t['title'], t['artist'], t['seconds'])]
        old = self._ly_find(self._ly_read(), t['title'], t['artist'], t['seconds'])
        items.append({'title': t['title'], 'artist': t['artist'], 'seconds': t['seconds'], 'offset': offset if offset is not None else (old or {}).get('offset', 0.0),
                      'synced': bool(parse_lrc(text)) if synced is None else synced, 'source': source, 'lrc': text})
        self._ly_write(items)

    # -- what the page shows --------------------------------------------------------------------
    def _ly_annotate(self, tracks, disc_entries=None):
        """Puts t['lyrics'] ('sync', 'text' or '') and t['lyricsOnDisc'] on every track. disc_entries: what the disc's own file holds."""
        if disc_entries is not None:
            self._ly_disc = disc_entries
        items, on_disc = self._ly_read(), self._ly_disc
        stale = False
        for t in tracks:
            e = self._ly_find(items, t['title'], t['artist'], t['seconds'])
            t['lyrics'] = ('sync' if e.get('synced') else 'text') if e else ''
            d = self._ly_find(on_disc, t['title'], t['artist'], t['seconds']) if e else None
            t['lyricsOnDisc'] = bool(d and d.get('lrc') == e.get('lrc') and abs(float(d.get('offset') or 0) - float(e.get('offset') or 0)) < 0.01)
            stale = stale or (bool(e) and not t['lyricsOnDisc'])
        return stale

    def _ly_on_load(self, fs, tracks):
        """Hi-MD: reads /LYRICS.TXT from the disc, adds what this PC does not have yet, and marks the tracks. Returns True when the PC has lyrics the disc lacks."""
        entries = []
        try:
            ent = next((e for e in fs.listdir('/') if not e['dir'] and e['short'].upper() == DISC_NAME), None)
            if ent and 0 < ent['size'] <= 4000000:
                data = json.loads(bytes(fs.read_file('/' + DISC_NAME)).decode('utf-8-sig'))
                entries = [e for e in data.get('lyrics', []) if isinstance(e, dict) and e.get('lrc')]
        except Exception:
            entries = []
        try:
            store = self._ly_read()
            added = False
            for e in entries:
                if not self._ly_find(store, e.get('title'), e.get('artist'), e.get('seconds')):
                    store.append(e)
                    added = True
            if added:
                self._ly_write(store)
        except OSError:
            pass
        return self._ly_annotate(tracks, entries)

    def _ly_on_load_netmd(self, tracks):
        self._ly_annotate(tracks, [])
        for t in tracks:
            t['lyricsOnDisc'] = False

    def lyrics_status(self):
        """The lyrics flags of the tracks now showing, after something changed them (no recorder access)."""
        stale = self._ly_annotate(self._tracks)
        return {'tracks': {t['number']: {'lyrics': t['lyrics'], 'onDisc': t['lyricsOnDisc']} for t in self._tracks}, 'stale': stale}

    def lyrics_get(self, number):
        """The lyrics of a track for the player: {synced, offset, lines: [[seconds, text]]} (plain text: lines without seconds)."""
        t = self._ly_track(number)
        e = self._ly_find(self._ly_read(), t['title'], t['artist'], t['seconds']) if t else None
        if not e:
            return {'none': True}
        if e.get('synced'):
            lines = [[round(s, 2), x] for s, x in parse_lrc(e['lrc'])]
        else:
            lines = [[None, x] for x in e['lrc'].splitlines()]
        return {'synced': bool(e.get('synced')), 'offset': float(e.get('offset') or 0), 'lines': lines, 'source': e.get('source', '')}

    def lyrics_set_offset(self, number, offset):
        t = self._ly_track(number)
        items = self._ly_read()
        e = self._ly_find(items, t['title'], t['artist'], t['seconds']) if t else None
        if not e:
            return {'error': 'This track has no lyrics.'}
        e['offset'] = round(max(-60.0, min(60.0, float(offset))), 2)
        self._ly_write(items)
        return dict(self.lyrics_status(), ok=True)

    def lyrics_remove(self, number):
        t = self._ly_track(number)
        if t:
            self._ly_write([e for e in self._ly_read() if not _same(e, t['title'], t['artist'], t['seconds'])])
        return dict(self.lyrics_status(), ok=True)

    def lyrics_load_file(self, number):
        """Asks for an .lrc or .txt file and uses it as this track's lyrics."""
        import webview
        t = self._ly_track(number)
        if not t:
            return {'error': 'That track is no longer on the disc. Reload it.'}
        kind = getattr(getattr(webview, 'FileDialog', None), 'OPEN', None) or webview.OPEN_DIALOG
        paths = self._window.create_file_dialog(kind, allow_multiple=False, file_types=('Lyrics files (*.lrc;*.txt)',))
        if not paths:
            return {'cancelled': True}
        try:
            with open(list(paths)[0], 'rb') as f:
                raw = f.read(2000000)
        except OSError as exc:
            return {'error': 'The file could not be read: %s' % exc}
        for enc in ('utf-8-sig', 'cp1252'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        text = text.replace('\r\n', '\n').strip()
        if len(text) < 3:
            return {'error': 'That file is empty.'}
        self._ly_put(t, text, 'file')
        return dict(self.lyrics_status(), ok=True, synced=bool(parse_lrc(text)))

    # -- looking them up online ------------------------------------------------------------------
    # Three sources, tried in turn: LRCLIB (community, timed), NetEase Cloud Music (large catalogue, timed) and lyrics.ovh (text only, needs an artist).
    # A later source is only asked when the earlier ones gave no confident timed match, unless the caller wants everything (the Find… list).
    def _ly_candidates(self, t, everything=False):
        """Records that could be this track, best first: [{id, source, title, artist, album, duration, gap, synced, score, text, syncedText}]."""
        title, artist = _split_title(t)
        secs = int(t['seconds'])
        if title == '(untitled)' or len(_norm(title)) < 1:
            return []
        found = {}

        def add(source, rid, r_title, r_artist, r_album, duration, plain, syn):
            if not (plain or syn):
                return
            gap = abs(float(duration) - secs) if duration else 0.0                                  # a source that gives no length is not penalised
            score = 100 - min(gap, 30) * 2 + (25 if _norm(r_title) == _norm(title) else 0) + (25 if artist and _norm(r_artist) == _norm(artist) else 0) + (10 if syn else 0)
            stamps = parse_lrc(syn) if syn else []
            found[source + ':' + str(rid)] = {'id': source + ':' + str(rid), 'source': source, 'title': r_title or '', 'artist': r_artist or '', 'album': r_album or '',
                                              'duration': round(float(duration or 0)), 'gap': round(gap), 'synced': bool(syn), 'score': score, 'text': plain, 'syncedText': syn,
                                              'unknownLength': not duration, 'span': stamps[-1][0] if stamps else 0.0}
        busy, answered = [], []                                                     # a service answers 503 now and then: try again once, then move on

        def ask(call, *args):
            for attempt in (0, 1):
                try:
                    out = call(*args)
                    answered.append(call)
                    return out
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        answered.append(call)
                        return None
                    if exc.code < 500:
                        break                                                       # refused (rate limit, bad request): do not hammer it
                    if attempt:
                        busy.append(exc)
                    else:
                        time.sleep(1.5)
                except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
                    if attempt:
                        busy.append(exc)
                    else:
                        time.sleep(1.5)
            return None

        def sure():
            return any(c['synced'] and self._ly_confident(c, t) for c in found.values())

        # 1. LRCLIB
        def lr_add(r):
            if isinstance(r, dict) and r.get('id') is not None and not r.get('instrumental'):
                add('lr', r['id'], r.get('trackName'), r.get('artistName'), r.get('albumName'), r.get('duration'), (r.get('plainLyrics') or '').strip(), (r.get('syncedLyrics') or '').strip())
        if artist:
            lr_add(ask(lambda q: _get(API + '/get?' + urllib.parse.urlencode(q)), {'track_name': title, 'artist_name': artist, 'duration': secs}))   # no album_name: with it the service answers 503 every time
        for q in ({'track_name': title, 'artist_name': artist} if artist else {'track_name': title}, {'q': (artist + ' ' + title).strip()}):
            for r in (ask(lambda q: _get(API + '/search?' + urllib.parse.urlencode(q)), q) or [])[:15]:
                lr_add(r)
            if len(found) >= 3:
                break
        # 2. NetEase: the search gives the songs, then the lyrics of the most likely few are fetched
        if everything or not sure():
            songs = {}
            clean = re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', title).strip()
            for q in ((artist + ' ' + clean).strip(), clean):
                for s in ask(_ne_search, q) or []:
                    songs.setdefault(s['id'], s)
                if any(_norm(s['title']) == _norm(title) and abs(s['duration'] - secs) <= 10 for s in songs.values()):
                    break

            def near(s):
                return (_norm(s['title']) == _norm(title), _artist_ok(s['artist'], artist), -abs(s['duration'] - secs))
            for s in sorted(songs.values(), key=near, reverse=True)[:4]:
                if not (_norm(s['title']) and (_norm(s['title']) in _norm(title) or _norm(title) in _norm(s['title']))):
                    continue                                                        # a song with some other name: not worth a request
                text = ask(_ne_lyric, s['id'])
                if text:
                    syn = bool(parse_lrc(text))
                    add('ne', s['id'], s['title'], s['artist'], s['album'], s['duration'], '' if syn else text, text if syn else '')
        # 3. lyrics.ovh: plain text by artist and title
        if artist and (everything or not any(self._ly_confident(c, t) for c in found.values())):
            out = ask(lambda: _get('https://api.lyrics.ovh/v1/%s/%s' % (urllib.parse.quote(artist, safe=''), urllib.parse.quote(re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', title).strip(), safe='')), 12))
            text = re.sub(r'^Paroles de la chanson [^\n]*\n+', '', ((out or {}).get('lyrics') or '').replace('\r\n', '\n')).strip() if isinstance(out, dict) else ''
            if len(text) > 40:
                add('ov', 'x', title, artist, '', 0, text, '')
        if not found and busy and not answered:                                     # only "busy" when no source answered at all
            raise urllib.error.URLError('the lyrics services are busy')
        return sorted(found.values(), key=lambda c: -c['score'])[:10]

    @staticmethod
    def _ly_confident(c, t):
        """Good enough to use without asking: the same title and artist (when known) and a length within 10 seconds. A title that is only part of the other
        (a name cut short on the disc) also counts when the artist is known and the length is within 5 seconds. A source without a length needs a known artist."""
        title, artist = _split_title(t)
        a, b = _norm(c['title']), _norm(title)
        if c.get('unknownLength') and not artist:
            return False
        span, secs = c.get('span') or 0.0, float(t.get('seconds') or 0)
        if c.get('synced') and span and secs > 30 and (span > secs + 8 or span < 0.55 * secs):
            return False                                                            # the timed lines end far too early or run past the track: an incomplete or other version
        same = a == b or (len(min(a, b, key=len)) >= 5 and (a in b or b in a) and bool(artist) and c['gap'] <= 5)
        return same and c['gap'] <= 10 and _artist_ok(c['artist'], artist)

    def lyrics_search(self, number):
        """Online candidates for one track, to choose from."""
        t = self._ly_track(number)
        if not t:
            return {'error': 'That track is no longer on the disc. Reload it.'}
        try:
            cands = self._ly_candidates(t, everything=True)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            return {'error': 'The lyrics services could not be reached (%s). Try again in a moment.' % getattr(exc, 'reason', exc)}
        self._ly_cands[int(number)] = cands
        out = []
        for c in cands:
            first = [x for _, x in parse_lrc(c['syncedText'])][:3] if c['synced'] else c['text'].splitlines()[:3]
            out.append({k: c[k] for k in ('id', 'source', 'title', 'artist', 'album', 'duration', 'gap', 'synced')} | {'preview': ' / '.join(x for x in first if x)[:160],
                                                                                                                       'confident': self._ly_confident(c, t), 'unknownLength': c['unknownLength']})
        return {'candidates': out}

    def lyrics_use(self, number, cid):
        t = self._ly_track(number)
        c = next((x for x in self._ly_cands.get(int(number), []) if x['id'] == cid), None)
        if not t or not c:
            return {'error': 'Search again; that result is no longer available.'}
        self._ly_put(t, c['syncedText'] or c['text'], {'lr': 'lrclib', 'ne': 'netease', 'ov': 'lyrics.ovh'}.get(c['source'], c['source']), synced=bool(c['syncedText']))
        return dict(self.lyrics_status(), ok=True)

    def lyrics_find_all(self, numbers):
        """Looks up each listed track and keeps the result when it is a confident match. Returns what was found and what was not."""
        found, missed, skipped, failed = [], [], [], None
        todo = [n for n in (numbers or []) if self._ly_track(n)]
        def tell(i, t, stage):                                                      # live progress for the page: which track, and what happened to it
            if self._window:
                try:
                    self._window.evaluate_js('window.onLyricsProgress && window.onLyricsProgress(%s)' % json.dumps(
                        {'index': i, 'total': len(todo), 'number': t['number'], 'title': t.get('title') or '', 'artist': t.get('artist') or '', 'stage': stage,
                         'found': len(found), 'missed': len(missed), 'skipped': len(skipped)}))
                except Exception:
                    pass
        disc = None
        if self._loaded_netmd and any(not (self._ly_track(n) or {}).get('artist') for n in todo):
            # A standard disc has no artist or album of its own: look the disc up first (MusicBrainz), so the lyrics are searched for by the real artist
            def disc_stage(what=None):
                if self._window:
                    try:
                        self._window.evaluate_js('window.onLyricsProgress && window.onLyricsProgress(%s)' % json.dumps(
                            {'stage': 'disc', 'what': 'Looking the disc up online for the artist and album…' if not what else 'Getting the album art…'}))
                    except Exception:
                        pass
            try:
                disc = self._dl_run(progress=disc_stage)
            except Exception:
                disc = None
        for i, n in enumerate(todo):
            t = self._ly_track(n)
            if not t:
                continue
            tell(i, t, 'searching')
            cands = None
            for attempt in range(3):                                                # a busy service usually recovers within a few seconds
                try:
                    cands = self._ly_candidates(t)
                    break
                except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                    if attempt < 2:
                        tell(i, t, 'retry')
                    time.sleep(4 * (attempt + 1))
            if cands is None:
                skipped.append(t['number'])
                tell(i, t, 'busy')
                if len(skipped) >= 3 and not found and not missed:
                    break                                                           # nothing has worked at all: stop hammering it
                continue
            sure = [c for c in cands if self._ly_confident(c, t)]
            best = max(sure, key=lambda c: (c['gap'] <= 3, c['synced'], c['score'])) if sure else None            # a timed version of the same song beats a text-only one
            if best:
                self._ly_put(t, best['syncedText'] or best['text'], {'lr': 'lrclib', 'ne': 'netease', 'ov': 'lyrics.ovh'}.get(best['source'], best['source']), synced=bool(best['syncedText']))
                found.append(t['number'])
                tell(i, t, 'synced' if best['syncedText'] else 'text')
            else:
                missed.append(t['number'])
                tell(i, t, 'nomatch')
            time.sleep(0.6)                                                        # be gentle with free services
        if skipped:
            failed = 'The lyrics services were busy for ' + ', '.join('#%d' % n for n in skipped) + '; press the button again in a minute to try those.'
        info = ''
        if disc and disc.get('found'):
            info = 'Disc found online: %s%s (%d of %d tracks matched).' % (disc.get('artist') or '', ' – ' + disc['album'] if disc.get('album') else '', disc['matched'], disc['total'])
        return dict(self.lyrics_status(), found=found, missed=missed, failed=failed, discInfo=info, discChanged=bool(disc and disc.get('changed')))

    # -- keeping them on the disc ------------------------------------------------------------------
    def lyrics_save_disc(self, index):
        """WRITES A FILE TO THE DISC. Stores the lyrics of the tracks now on the disc as /LYRICS.TXT (replacing the earlier file)."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a lyrics file. Standard discs keep their lyrics on this PC.'}
        items = self._ly_read()
        entries = []
        for t in self._tracks:
            e = self._ly_find(items, t['title'], t['artist'], t['seconds'])
            if e:
                entries.append(dict(e, title=t['title'], artist=t['artist'], seconds=t['seconds']))
        if not entries:
            return {'error': 'None of the tracks on this disc has lyrics yet.'}
        folder = tempfile.mkdtemp(prefix='mdm-lyrics-')
        tmp = os.path.join(folder, DISC_NAME)
        try:
            with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'app': 'MiniDiscManager', 'version': 1, 'lyrics': entries}, f, ensure_ascii=False)
            res = {'error': 'not tried'}
            for attempt in range(3):                                                # a recorder can stay busy for a few seconds after a write
                with self._lock:
                    res = self._run_helper('lyrics_set', {'file': tmp, 'backupDir': os.path.join(BACKUP_DIR, 'lyrics_latest')})
                if 'error' not in res:
                    break
                time.sleep(2.5)
            if 'error' in res:
                self.log('lyrics_save_disc failed: %s' % res['error'])
                return res
            self._ly_annotate(self._tracks, entries)
            return dict(self.lyrics_status(), ok=True, saved=len(entries))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
