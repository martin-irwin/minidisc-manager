"""A YouTube video for a track: the best match is searched for on YouTube's public results page (no account or key; only the artist and title are sent),
the user picks one (or pastes a link), and the link is kept with the track on this PC (videos.json) and, on a Hi-MD disc, in a "Video" column of the
TRACKS.CSV track list on the disc. A disc loaded later shows the links again, also on another PC. VideoLinksMixin is mixed into himd_app.Api."""
import csv
import io
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import lyrics
from mdm_paths import USER_DIR

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:                                           # without Pillow the app cannot tell a moving video from a still picture and just ranks by name
    Image = None

VIDEOS_FILE = os.path.join(USER_DIR, 'videos.json')
VIDEO_WINDOW_FILE = os.path.join(USER_DIR, 'video_window.json')       # where the video window was last left (x, y, width, height in screen-independent units)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36'
SEARCH = 'https://www.youtube.com/results?'
_URL = re.compile(r'^https?://(?:www\.|m\.|music\.)?(?:youtube\.com/watch\?(?:[^#\s]*&)?v=|youtu\.be/)([\w-]{11})(?:[&?#].*)?$')
_BAD = ('cover', 'karaoke', 'reaction', 'tutorial', 'lesson', 'instrumental', 'remix', 'live', 'sped up', 'slowed', '8d audio', 'nightcore')


def video_url(text):
    """The canonical https://www.youtube.com/watch?v=ID for a YouTube link, or '' when it is not one."""
    m = _URL.match((text or '').strip())
    return 'https://www.youtube.com/watch?v=' + m.group(1) if m else ''


def _seconds(text):
    parts = [int(p) for p in re.findall(r'\d+', text or '')]
    out = 0
    for p in parts:
        out = out * 60 + p
    return out


def _text(node):
    if not isinstance(node, dict):
        return ''
    return node.get('simpleText') or ''.join(r.get('text', '') for r in node.get('runs', []))


def search_youtube(query):
    """The first results of a YouTube search: [{id, title, channel, seconds, views}]. Raises OSError / ValueError when YouTube cannot be reached or read."""
    req = urllib.request.Request(SEARCH + urllib.parse.urlencode({'search_query': query, 'hl': 'en'}),
                                 headers={'User-Agent': UA, 'Accept-Language': 'en-GB,en;q=0.9', 'Cookie': 'CONSENT=YES+cb; SOCS=CAI'})     # the cookies: no consent page first
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode('utf-8', 'replace')
    m = re.search(r'var ytInitialData = (\{.*?\});</script>', html, re.S)
    if not m:
        raise ValueError('YouTube did not answer in the expected form')
    found = []

    def walk(o):
        if isinstance(o, dict):
            v = o.get('videoRenderer')
            if isinstance(v, dict) and v.get('videoId'):
                badge = ' '.join((b.get('metadataBadgeRenderer') or {}).get('style', '') for b in v.get('ownerBadges') or [])
                found.append({'id': v['videoId'], 'title': _text(v.get('title')), 'channel': _text(v.get('ownerText')), 'artistBadge': 'VERIFIED_ARTIST' in badge,
                              'seconds': _seconds(_text(v.get('lengthText'))), 'views': int(re.sub(r'\D', '', _text(v.get('viewCountText'))) or 0)})
            else:
                for x in o.values():
                    walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(json.loads(m.group(1)))
    return found[:15]


_OFFICIAL_VIDEO = re.compile(r'official\s+(?:music\s+|hd\s+|4k\s+|promo\s+)?video|official\s+promo|\(official\)|video\s+version')
_OFFICIAL_AUDIO = re.compile(r'official\s+(?:audio|lyric|visuali[sz]er)|visuali[sz]er')


def _compact(text):
    """The text lower-cased with only letters and digits, so "B-52's" and "B-52s" (or "A-ha" and "a ha") compare equal."""
    return lyrics._norm(text).replace(' ', '')


def _artist_channel(c, artist):
    """The channel is the artist's own (its name holds the artist's, or the other way round), or a VEVO channel of the artist."""
    ch, want = _compact(c['channel']), _compact(artist)
    return bool(want and ch and (want in ch or ch in want))


def kind(c, artist):
    """What sort of upload a result is, best first: 'Official video', 'Official audio', 'Artist channel', 'Topic (audio only)' or ''."""
    raw, ch = c['title'].lower(), c['channel'].lower()
    own = c.get('artistBadge') or 'vevo' in ch or _artist_channel(c, artist) or 'rhino' == ch or 'records' in ch
    if _OFFICIAL_VIDEO.search(raw) and own:
        return 'Official video'
    if 'vevo' in ch and 'lyric' not in raw:
        return 'Official video'                                                  # a VEVO channel carries the label's official videos
    if _OFFICIAL_AUDIO.search(raw) and own:
        return 'Official audio'
    if ch.endswith('- topic'):
        return 'Topic (audio only)'
    return 'Artist channel' if c.get('artistBadge') and _artist_channel(c, artist) else ''


_KIND_POINTS = {'Official video': 45, 'Official audio': 14, 'Artist channel': 12, 'Topic (audio only)': 4, '': 0}


_motion_cache = {}


def motion(video_id):
    """How much the picture changes between YouTube's three preview frames of a video: about 0-2 is a still picture with sound, 8 and more is a
    moving video. None when it cannot be told (no Pillow, no network)."""
    if video_id in _motion_cache:
        return _motion_cache[video_id]
    value = None
    if Image is not None:
        try:
            ims = []
            for i in (1, 2, 3):
                with urllib.request.urlopen(urllib.request.Request('https://i.ytimg.com/vi/%s/%d.jpg' % (video_id, i), headers={'User-Agent': UA}), timeout=8) as r:
                    ims.append(Image.open(io.BytesIO(r.read())).convert('L').resize((64, 48)))
            value = round(max(ImageStat.Stat(ImageChops.difference(a, b)).mean[0] for a, b in ((ims[0], ims[1]), (ims[1], ims[2]), (ims[0], ims[2]))), 1)
        except (OSError, ValueError):
            value = None
    _motion_cache[video_id] = value
    return value


STILL = 3.0                                                    # below this the video is a still picture with the sound


def score(c, title, artist, seconds):
    """How well a search result fits the track: about the same length, the song's title and the artist in its name, an OFFICIAL upload (the official
    video above all), and not a live / cover / remix version (unless the track itself is one). Higher is better."""
    t, want_t, want_a = lyrics._norm(c['title']), lyrics._norm(title), lyrics._norm(artist)
    raw = c['title'].lower()
    s = 0.0
    if seconds and c['seconds']:
        gap = abs(c['seconds'] - seconds)
        s += max(0, 40 - 2 * gap) - (30 if gap > 60 else 0)
    if want_t and want_t in t:
        s += 25
    if want_a and (_compact(artist) in _compact(c['title']) or _artist_channel(c, artist)):
        s += 20
    if want_t and want_t in t:                                                   # an official upload only counts for the right song
        s += _KIND_POINTS[kind(c, artist)]
    if c.get('artistBadge') and _artist_channel(c, artist):
        s += 8
    if ('lyric' in raw or 'with lyrics' in raw) and 'lyric' not in title.lower():
        s -= 15                                                  # a fan-made lyrics video: not what is wanted when an official video exists
    for bad in _BAD:
        if bad in raw and bad not in title.lower():
            s -= 25
    return s + min(10.0, math.log10(c['views'] + 1))


def confident(c, title, artist, seconds):
    """A result that can be used without asking: the song's title in its name, the artist in its name or channel, and about the same length
    (an official video may be a shorter or longer edit than the disc's track, so it is allowed to differ by up to a minute)."""
    t, ch, want_t, want_a = lyrics._norm(c['title']), lyrics._norm(c['channel']), lyrics._norm(title), lyrics._norm(artist)
    same_len = not (seconds and c['seconds']) or abs(c['seconds'] - seconds) <= (60 if kind(c, artist) == 'Official video' else 12)
    artist_ok = not want_a or _compact(artist) in _compact(c['title']) or _compact(artist) in _compact(c['channel'])
    return bool(want_t and want_t in t and artist_ok and same_len)


def _edge_windows():
    """The handles of the visible Edge windows right now (Windows only; an empty set elsewhere)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = set()
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def each(h, _):
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(h, buf, 64)
                if buf.value == 'Chrome_WidgetWin_1':
                    found.add(h)
            return True
        user32.EnumWindows(proto(each), 0)
        return found
    except Exception:
        return set()


_VIDEO_HWND = [0]                                              # the video window currently open, so the next one replaces it


def _close_old_video():
    try:
        import ctypes
        h = _VIDEO_HWND[0]
        if h and ctypes.windll.user32.IsWindow(h):
            ctypes.windll.user32.PostMessageW(h, 0x0010, 0, 0)      # WM_CLOSE
    except Exception:
        pass
    _VIDEO_HWND[0] = 0


def _remember_window(h):
    """Follows the video window while it is open and keeps its position and size, so the next one opens the same way (also when the person closes it)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        r = wintypes.RECT()
        last = None
        while user32.IsWindow(h):
            if not user32.IsIconic(h) and not user32.IsZoomed(h) and user32.GetWindowRect(h, ctypes.byref(r)):
                try:
                    scale = user32.GetDpiForWindow(h) / 96.0
                except Exception:
                    scale = 1.0
                now = [round(r.left / scale), round(r.top / scale), round((r.right - r.left) / scale), round((r.bottom - r.top) / scale)]
                if now != last and now[2] > 150 and now[3] > 100:
                    last = now
            time.sleep(0.5)
        if last:
            with open(VIDEO_WINDOW_FILE, 'w', encoding='utf-8') as f:
                json.dump(last, f)
    except Exception:
        pass


def _saved_window():
    try:
        with open(VIDEO_WINDOW_FILE, encoding='utf-8') as f:
            x, y, w, h = [int(v) for v in json.load(f)]
        return x, y, w, h
    except (OSError, ValueError, TypeError):
        return None


def _shrink_new_window(before, width=440, height=335):
    """Edge reuses the size it remembers for app windows (often huge), so the new video window is set to the size and place the person left the last one
    in, or else to a narrow, short size (narrow enough that YouTube drops its sidebar and shows the video first) near the top-left."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        end = time.time() + 12
        while time.time() < end:
            time.sleep(0.3)
            new = _edge_windows() - before
            if new:
                h = sorted(new)[-1]
                _VIDEO_HWND[0] = h
                try:
                    scale = user32.GetDpiForWindow(h) / 96.0
                except Exception:
                    scale = 1.0
                x, y, w, hh = _saved_window() or (60, 60, width, height)
                user32.ShowWindow(h, 9)                             # SW_RESTORE: a remembered maximised window cannot be resized
                user32.SetWindowPos(h, 0, int(x * scale), int(y * scale), int(w * scale), int(hh * scale), 0x0004)   # SWP_NOZORDER
                threading.Thread(target=_remember_window, args=(h,), daemon=True).start()
                return
    except Exception:
        pass


class VideoLinksMixin:
    # -- the PC's own list: [{title, artist, seconds, url, vtitle}] ----------------------------------
    def _video_read(self):
        items = self._json_read(VIDEOS_FILE).get('items')
        return items if isinstance(items, list) else []

    def _video_write(self, items):
        self._json_write(VIDEOS_FILE, {'items': items})

    @staticmethod
    def _video_find(items, t):
        return next((e for e in items if lyrics._same(e, t['title'], t['artist'], t['seconds'])), None)

    def _video_track(self, number):
        return next((t for t in self._tracks if t['number'] == int(number)), None)

    def _video_on_load(self, tracks, csv_bytes=None):
        """Marks each track with its link (t['video']); links found in the disc's TRACKS.CSV that this PC does not have yet are added to the PC's list."""
        items = self._video_read()
        if csv_bytes:
            try:
                added = False
                for row in csv.DictReader(io.StringIO(bytes(csv_bytes).decode('utf-8-sig'))):
                    url = video_url(row.get('Video'))
                    if not url:
                        continue
                    e = {'title': row.get('Title') or '', 'artist': row.get('Artist') or '', 'seconds': float(row.get('Length (s)') or 0), 'url': url, 'vtitle': ''}
                    if not self._video_find(items, e):
                        items.append(e)
                        added = True
                if added:
                    self._video_write(items)
            except (ValueError, OSError, csv.Error):
                pass                                                  # a track list that cannot be read is just ignored
        for t in tracks:
            e = self._video_find(items, t) if t['title'] != '(untitled)' else None
            t['video'] = e['url'] if e else ''

    # -- what the page calls --------------------------------------------------------------------
    def _video_candidates(self, t):
        """Ranked YouTube results for a track: (title, artist, results) or an {'error'} dict."""
        title, artist = lyrics._split_title(t)
        if not title or title == '(untitled)':
            return {'error': 'This track has no title to search with. Name it first.'}
        query = (artist + ' ' + title).strip()
        try:
            found = search_youtube(query)
            want = lyrics._norm(title)
            if not any(kind(c, artist) == 'Official video' and want in lyrics._norm(c['title']) for c in found):      # no official video of this song among them: ask for one by name, and merge the answers
                seen = {c['id'] for c in found}
                found += [c for c in search_youtube(query + ' official video') if c['id'] not in seen]
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return {'error': 'Could not search YouTube: %s' % exc}
        out = []
        for c in found:
            out.append(dict(c, url='https://www.youtube.com/watch?v=' + c['id'], score=round(score(c, title, artist, t['seconds']), 1), kind=kind(c, artist),
                            gap=(c['seconds'] - t['seconds']) if c['seconds'] else None, sure=confident(c, title, artist, t['seconds'])))
        with ThreadPoolExecutor(max_workers=8) as pool:                          # a still picture with the sound is not what is wanted: look at the best few
            top = sorted(out, key=lambda c: -c['score'])[:6]
            for c, m in zip(top, pool.map(lambda c: motion(c['id']), top)):
                c['motion'] = m
                c['still'] = m is not None and m < STILL
                if c['still']:
                    c['score'] = round(c['score'] - 40, 1)
        out.sort(key=lambda c: (c['kind'] != 'Official video' or not c['sure'] or c.get('still', False), not c['sure'], -c['score']))      # a confident official video first, then other confident matches, then by score
        return title, artist, out

    def video_search(self, number):
        """Looks for the best YouTube video for a track. Returns {track: {title, artist, seconds, video}, results: [{id, url, title, channel, seconds, views, gap, score, sure}]}."""
        t = self._video_track(number)
        if t is None:
            return {'error': 'That track is no longer on the disc. Reload it.'}
        r = self._video_candidates(t)
        if isinstance(r, dict):
            return r
        title, artist, out = r
        return {'track': {'title': title, 'artist': artist, 'seconds': t['seconds'], 'video': t.get('video') or ''}, 'results': out[:8]}

    def video_cancel(self):
        self._video_stop = True
        return {'ok': True}

    def video_find_all(self, numbers):
        """The best video for each listed track: a confident match is kept at once, the others are only reported (the user reviews them one by one).
        Progress goes to the page (window.onVideoProgress). Returns {saved: [{number, title, vtitle}], unsure: [{number, title, vtitle}], none: [numbers], failed: text}."""
        self._video_stop = False
        saved, unsure, none, failed, bad = [], [], [], '', 0
        nums = [int(n) for n in numbers or []]
        for i, n in enumerate(nums):
            if self._video_stop:
                break
            t = self._video_track(n)
            if t is None or t['title'] == '(untitled)':
                none.append(n)
                continue
            self._video_tell(i=i, total=len(nums), number=n, state='searching')
            r = self._video_candidates(t)
            if isinstance(r, dict):                                                  # a failed search: three in a row stop the run (offline, or YouTube says no)
                bad += 1
                none.append(n)
                self._video_tell(i=i, total=len(nums), number=n, state='error', text=r['error'])
                if bad >= 3:
                    failed = r['error']
                    break
                continue
            bad = 0
            out = r[2]
            if not out:
                none.append(n)
                self._video_tell(i=i, total=len(nums), number=n, state='none')
            elif out[0]['sure']:
                self.video_save(n, out[0]['url'], out[0]['title'])
                saved.append({'number': n, 'title': t['title'], 'vtitle': out[0]['title'], 'kind': out[0]['kind']})
                self._video_tell(i=i, total=len(nums), number=n, state='saved', text=out[0]['title'] + (' (' + out[0]['kind'].lower() + ')' if out[0]['kind'] else ''))
            else:
                unsure.append({'number': n, 'title': t['title'], 'vtitle': out[0]['title']})
                self._video_tell(i=i, total=len(nums), number=n, state='unsure', text=out[0]['title'])
            time.sleep(0.8)                                                          # be gentle with the search page
        return {'official': sum(1 for x in saved if x['kind'] == 'Official video'), 'saved': saved, 'unsure': unsure, 'none': none, 'failed': failed, 'stopped': bool(self._video_stop)}

    def _video_tell(self, **kw):
        w = getattr(self, '_window', None)
        if w:
            try:
                w.evaluate_js('window.onVideoProgress && window.onVideoProgress(%s)' % json.dumps(kw))
            except Exception:
                pass

    def video_save(self, number, url, vtitle=''):
        """Keeps the link for a track on this PC (the page then writes it to the disc's track list if the user wants that)."""
        t = self._video_track(number)
        link = video_url(url)
        if t is None or t['title'] == '(untitled)':
            return {'error': 'Name the track first: a link is kept by its title.'}
        if not link:
            return {'error': 'That is not a YouTube link (a youtube.com/watch?v=… or youtu.be/… address).'}
        items = [e for e in self._video_read() if not lyrics._same(e, t['title'], t['artist'], t['seconds'])]
        items.append({'title': t['title'], 'artist': t['artist'], 'seconds': t['seconds'], 'url': link, 'vtitle': (vtitle or '')[:200]})
        self._video_write(items)
        t['video'] = link
        return {'ok': True, 'url': link}

    def video_remove(self, number):
        t = self._video_track(number)
        if t is None:
            return {'error': 'That track is no longer on the disc. Reload it.'}
        self._video_write([e for e in self._video_read() if not lyrics._same(e, t['title'], t['artist'], t['seconds'])])
        t['video'] = ''
        return {'ok': True}

    def video_open(self, url):
        link = video_url(url)
        if not link:
            return {'error': 'That is not a YouTube link.'}
        webbrowser.open(link)
        return {'ok': True}

    def video_popup(self, url):
        """Plays the video in a small Edge app-style window (no tabs or address bar; movable and resizable) that uses the person's own Edge
        profile. Falls back to the default browser when Edge cannot be found."""
        link = video_url(url)
        if not link:
            return {'error': 'That is not a YouTube link.'}
        try:
            import shutil
            import subprocess
            exe = shutil.which('msedge') or next((p for p in (os.path.join(os.environ.get(k, ''), r'Microsoft\Edge\Application\msedge.exe')
                                                              for k in ('ProgramFiles(x86)', 'ProgramFiles', 'LocalAppData')) if os.path.isfile(p)), None)
            if not exe:
                raise OSError('Edge was not found')
            _close_old_video()
            time.sleep(1.3)                                          # the old window's size is saved a moment after it goes
            before = _edge_windows()
            subprocess.Popen([exe, '--app=' + link, '--autoplay-policy=no-user-gesture-required'], close_fds=True)
            threading.Thread(target=_shrink_new_window, args=(before,), daemon=True).start()
            return {'ok': True}
        except Exception as exc:
            webbrowser.open(link)
            return {'ok': True, 'popupError': '%s: %s' % (type(exc).__name__, exc)}


