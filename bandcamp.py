"""Record what a Bandcamp window in the app plays, in real time, one WAV per track.

The window is an ordinary web view of bandcamp.com (the user logs in there). A small script injected into each page reports what the
page's audio player is doing (which track, how far in, paused or not) to Recorder.report(); the sound itself is captured by
helper\\appaudio.exe, which records only this program's audio (WASAPI process loopback), so nothing else the PC plays is mixed in.

A track is recorded only if it plays from its start to its end without pausing or seeking. Its start is found in the captured sound,
its end is start + the length the page reports. Gapless albums are cut at the previous track's end. Nothing is downloaded: the
recording is the sound that is playing, so it takes as long as the music does.
"""
import array
import collections
import json
import os
import re
import subprocess
import threading
import urllib.request
import wave

from mdm_common import remove_item_files

RATE, FRAME = 44100, 4
BPS = RATE * FRAME                  # bytes per second of the captured sound
LEAD = 0.8                          # seconds kept before the page said the track started (the sound can lead the report)
TAIL = 0.7                          # seconds recorded after the reported end
HEAD_BYTES = int((LEAD + 2.0) * BPS)    # the first part of a track that is searched for where the music starts
GAP_JOIN = 1.5                      # a track starting within this long after the previous one ended is cut at that boundary
SILENT = 40                         # |sample| below this is silence when looking for where the music starts

# Injected into every page of the Bandcamp window. Finds the page's audio element (by watching play()), reads the track list the page
# itself carries (data-tralbum: titles, lengths) and reports the player state to Python four times a second.
PAGE_JS = r"""
(function () {
  if (window.__mdm) return; window.__mdm = true;
  var media = null, seen = [], proto = HTMLMediaElement.prototype, orig = proto.play;
  proto.play = function () { if (seen.indexOf(this) < 0) seen.push(this); media = this; return orig.apply(this, arguments); };
  Array.prototype.forEach.call(document.querySelectorAll('audio'), function (a) { if (!a.paused) { media = a; seen.push(a); } });
  function pick() {        // the page may use several audio elements (e.g. one preloading the next track): follow the one that is playing
    var best = null;
    for (var i = 0; i < seen.length; i++) { var m = seen[i]; if (!m.paused && !m.ended && (m.currentSrc || m.src)) best = m; }
    return best || media;
  }
  function tralbum() {
    try { var n = document.querySelector('[data-tralbum]'); return n ? JSON.parse(n.getAttribute('data-tralbum')) : null; } catch (e) { return null; }
  }
  function base(u) { return (u || '').split('?')[0]; }
  function text(sel) { var n = document.querySelector(sel); return n ? (n.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  function describe(src) {
    var t = tralbum(), r = { title: '', artist: '', album: '', num: 0, art: '' };
    if (t) {
      var cur = t.current || {};
      r.album = cur.title || ''; r.artist = t.artist || cur.artist || '';
      if (t.art_id) r.art = 'https://f4.bcbits.com/img/a' + t.art_id + '_10.jpg';
      var list = t.trackinfo || [];
      for (var i = 0; i < list.length; i++) {
        var f = list[i].file || {};
        for (var k in f) if (base(f[k]) === base(src)) { r.title = list[i].title || ''; r.num = list[i].track_num || (i + 1); if (list[i].artist) r.artist = list[i].artist; return r; }
      }
    }
    try {      // the page may publish what is playing through the browser's media controls
      var md = navigator.mediaSession && navigator.mediaSession.metadata;
      if (md && md.title) {
        r.title = md.title; r.artist = md.artist || r.artist; r.album = md.album || r.album;
        if (md.artwork && md.artwork.length) r.art = md.artwork[md.artwork.length - 1].src;
        return r;
      }
    } catch (e) { }
    r.title = text('.title-section .title') || text('.track_info .title') || text('.player-title') || text('[class*="track-title"]') || text('.inline_player .title');
    if (!r.title) r.title = (document.title || '').split(' | ')[0];
    if (!r.artist) r.artist = text('.back-link-text') || text('[class*="artist"]');
    return r;
  }
  var meta = {}, lastSrc = '', stamp = 0, dumped = false;
  function bar() {
    if (document.getElementById('__mdm_bar')) return;
    var b = document.createElement('div'); b.id = '__mdm_bar';
    // a small bar at the top centre, clear of Bandcamp's player and volume at the bottom; drag the grip to move it, the dash folds it away
    b.style.cssText = 'position:fixed;z-index:2147483647;top:4px;left:50%;transform:translateX(-50%);display:flex;gap:4px;align-items:center;font:11px Segoe UI,sans-serif;background:#111d;color:#fff;padding:2px 5px;border-radius:7px;opacity:.9';
    var body = document.createElement('span'); body.style.cssText = 'display:flex;gap:4px;align-items:center';
    function btn(t, fn, tip) { var x = document.createElement('button'); x.textContent = t; x.title = tip; x.style.cssText = 'cursor:pointer;border:0;border-radius:4px;padding:1px 7px;font-size:11px'; x.onclick = fn; body.appendChild(x); return x; }
    var grip = document.createElement('span'); grip.textContent = '☰'; grip.title = 'Drag to move this bar'; grip.style.cssText = 'cursor:move;padding:0 3px'; b.appendChild(grip);
    btn('◀', function () { history.back(); }, 'Back'); btn('▶', function () { history.forward(); }, 'Forward');
    btn('Home', function () { location.href = 'https://bandcamp.com/'; }, 'bandcamp.com');
    var open = btn(openFirst() ? 'Albums: open first' : 'Albums: play', function () {
      var on = !openFirst(); try { localStorage.setItem('__mdm_open', on ? '1' : '0'); } catch (e) { }
      open.textContent = on ? 'Albums: open first' : 'Albums: play';
    }, 'In your collection, clicking an album opens its page (so you can pick a track) instead of starting to play it');
    var s = document.createElement('span'); s.id = '__mdm_status'; s.textContent = 'Recording'; s.title = 'MiniDisc Manager is watching this window'; body.appendChild(s);
    b.appendChild(body);
    var fold = document.createElement('button'); fold.textContent = '–'; fold.title = 'Fold away'; fold.style.cssText = 'cursor:pointer;border:0;border-radius:4px;padding:0 6px';
    fold.onclick = function () { var h = body.style.display === 'none'; body.style.display = h ? 'flex' : 'none'; fold.textContent = h ? '–' : '+'; };
    b.appendChild(fold);
    grip.onmousedown = function (e) {
      var r = b.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      b.style.transform = 'none'; b.style.left = r.left + 'px'; b.style.top = r.top + 'px';
      function mv(ev) { b.style.left = Math.max(0, ev.clientX - dx) + 'px'; b.style.top = Math.max(0, ev.clientY - dy) + 'px'; }
      function up() { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); }
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up); e.preventDefault();
    };
    (document.body || document.documentElement).appendChild(b);
  }
  function openFirst() { try { return localStorage.getItem('__mdm_open') !== '0'; } catch (e) { return true; } }
  // In the collection grid a click on an album's artwork / play button normally starts the album at once. With "open first" on it
  // goes to the album's own page instead, where the tracks are listed and one can be chosen.
  var navigating = false;
  function tell(note) { var api = window.pywebview && window.pywebview.api; if (api && api.report) api.report({ note: note }); }
  function chain(t) { var o = []; for (var n = t; n && n.nodeType === 1 && o.length < 7; n = n.parentNode) o.push(n.tagName.toLowerCase() + '.' + (n.className + '').replace(/\s+/g, '.').slice(0, 36)); return o.join(' < '); }
  function intercept(e) {
    var t = e.target;
    if (!openFirst() || !t || !t.closest || navigating) return;
    if (/\/(album|track)\//.test(location.pathname)) return;               // already on an album / track page: its play buttons must work
    // the smallest box around the click that holds exactly one album / track link is that album's tile
    var link = null, why = '';
    for (var n = t; n && n !== document.body && n.nodeType === 1; n = n.parentNode) {
      var cs = getComputedStyle(n);
      if (cs.position === 'fixed' || cs.position === 'sticky') { why = 'fixed ' + n.className; break; }
      var links = n.querySelectorAll('a[href*="/album/"], a[href*="/track/"]'), hrefs = {}, count = 0;
      for (var i = 0; i < links.length; i++) { var h = links[i].href.split('?')[0].split('#')[0]; if (!hrefs[h]) { hrefs[h] = links[i]; count++; } }
      if (count === 1) { link = links[0]; break; }
      if (count > 1) { why = 'several albums in ' + n.tagName + '.' + n.className; break; }
    }
    // clicks on real links and on the buy / gift / wishlist / share / menu controls keep their own behaviour
    var own = t.closest('a[href], input, select, textarea, [class*="buy"], [class*="gift"], [class*="wishlist"], [class*="share"], [class*="menu"]');
    // the page's own classes sit on <body> too, and the artwork is wrapped in a "play" link: neither counts as a control to leave alone
    if (own && (own === document.body || own === document.documentElement || (own.tagName === 'A' && /play/i.test(own.className + '')))) own = null;
    if (e.type === 'click' || e.type === 'mousedown') tell(e.type + ' ' + chain(t) + ' => ' + (own ? 'left alone (' + own.tagName + '.' + (own.className + '').slice(0, 30) + ')' : link ? 'open ' + link.href.slice(0, 80) : 'no album link: ' + why));
    if (own || !link) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    if (e.type === 'click') { navigating = true; location.href = link.href; }
  }
  ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(function (k) { document.addEventListener(k, intercept, true); });  if (document.body) bar(); else document.addEventListener('DOMContentLoaded', bar);
  function debug() {      // what the page shows about the current track, for the log (helps when the title cannot be found)
    var out = [];
    try { var md = navigator.mediaSession && navigator.mediaSession.metadata; out.push('mediaSession=' + (md ? md.title + ' / ' + md.artist : 'none')); } catch (e) { }
    out.push('audios=' + document.querySelectorAll('audio').length + ' seen=' + seen.length + ' url=' + location.href.slice(0, 80));
    var nodes = document.querySelectorAll('[class*="player"],[class*="playing"],[class*="now"],[class*="track-title"],[class*="track_title"]');
    for (var i = 0; i < nodes.length && out.length < 14; i++) {
      var t = (nodes[i].textContent || '').replace(/\s+/g, ' ').trim();
      if (t && t.length < 90) out.push((nodes[i].className + '').slice(0, 50) + ' = ' + t);
    }
    var all = document.querySelectorAll('div,section,footer,aside');       // the player bar: fixed / sticky boxes with a little text
    for (var j = 0; j < all.length && out.length < 24; j++) {
      var cs = getComputedStyle(all[j]);
      if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
      var tx = (all[j].innerText || '').replace(/\s+/g, ' ').trim();
      if (tx && tx.length < 200) out.push('FIXED ' + (all[j].id || '') + '.' + (all[j].className + '').slice(0, 40) + ' = ' + tx);
    }
    out.push('src=' + (media && (media.currentSrc || '')).slice(0, 120));
    return out.join(' | ');
  }
  setInterval(function () {
    var api = window.pywebview && window.pywebview.api;
    media = pick();
    if (!media || !api || !api.report) return;
    var src = media.currentSrc || media.src || '', dbg = '';
    var now = Date.now();
    if (src !== lastSrc) { lastSrc = src; meta = describe(src); stamp = now; dumped = false; }
    else if (now - stamp > 2000) { stamp = now; var m2 = describe(src); if (m2.title) meta = m2; if (!dumped) { dumped = true; dbg = debug(); } }
    api.report({ src: src, pos: media.currentTime || 0, dur: isFinite(media.duration) ? media.duration : 0, paused: !!media.paused || !!media.ended,
                 vol: media.muted ? 0 : media.volume, rate: media.playbackRate, title: meta.title, artist: meta.artist, album: meta.album, num: meta.num, art: meta.art, dbg: dbg });
  }, 250);
})();
"""


# Injected into every page of the SoundCloud window. soundcloud.com plays through an ordinary audio element (blob source), so the player
# state comes from that element (found by watching play(), as on Bandcamp) and the track details from the player bar at the bottom of
# the page (or the browser's media controls, which SoundCloud also fills in).
SOUNDCLOUD_JS = r"""
(function () {
  if (window.__mdm) return; window.__mdm = true;
  var media = null, seen = [], proto = HTMLMediaElement.prototype, orig = proto.play;
  proto.play = function () { if (seen.indexOf(this) < 0) seen.push(this); media = this; return orig.apply(this, arguments); };
  Array.prototype.forEach.call(document.querySelectorAll('audio'), function (a) { if (!a.paused) { media = a; seen.push(a); } });
  function pick() {
    var best = null;
    for (var i = 0; i < seen.length; i++) { var m = seen[i]; if (!m.paused && !m.ended && (m.currentSrc || m.src)) best = m; }
    return best || media;
  }
  function text(sel) { var n = document.querySelector(sel); return n ? (n.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  function describe() {
    var r = { title: '', artist: '', album: '', num: 0, art: '' };
    var link = document.querySelector('.playbackSoundBadge__titleLink');
    if (link) r.title = (link.getAttribute('title') || '').trim() || text('.playbackSoundBadge__titleLink span[aria-hidden="true"]') || text('.playbackSoundBadge__titleLink');
    r.artist = text('.playbackSoundBadge__lightLink');
    var art = document.querySelector('.playbackSoundBadge .image__lightOutline span, .playbackSoundBadge span.sc-artwork');
    if (art) { var m = /url\(["']?([^"')]+)/.exec(art.style.backgroundImage || ''); if (m) r.art = m[1].replace(/-t\d+x\d+\./, '-t500x500.'); }
    try {
      var md = navigator.mediaSession && navigator.mediaSession.metadata;
      if (md && md.title && !r.title) { r.title = md.title; r.artist = r.artist || md.artist || ''; }
      if (md && md.artwork && md.artwork.length && !r.art) r.art = md.artwork[md.artwork.length - 1].src;
      if (md && md.album) r.album = md.album;
    } catch (e) { }
    if (!r.title) r.title = (document.title || '').split(' by ')[0].replace(/^Stream /, '');
    return r;
  }
  function bar() {
    if (document.getElementById('__mdm_bar')) return;
    var b = document.createElement('div'); b.id = '__mdm_bar';
    b.style.cssText = 'position:fixed;z-index:2147483647;top:4px;left:50%;transform:translateX(-50%);display:flex;gap:4px;align-items:center;font:11px Segoe UI,sans-serif;background:#111d;color:#fff;padding:2px 5px;border-radius:7px;opacity:.9';
    var body = document.createElement('span'); body.style.cssText = 'display:flex;gap:4px;align-items:center';
    function btn(t, fn, tip) { var x = document.createElement('button'); x.textContent = t; x.title = tip; x.style.cssText = 'cursor:pointer;border:0;border-radius:4px;padding:1px 7px;font-size:11px'; x.onclick = fn; body.appendChild(x); }
    var grip = document.createElement('span'); grip.textContent = '☰'; grip.title = 'Drag to move this bar'; grip.style.cssText = 'cursor:move;padding:0 3px'; b.appendChild(grip);
    btn('◀', function () { history.back(); }, 'Back'); btn('▶', function () { history.forward(); }, 'Forward');
    btn('Home', function () { location.href = 'https://soundcloud.com/'; }, 'soundcloud.com');
    var s = document.createElement('span'); s.textContent = 'Recording'; s.title = 'MiniDisc Manager is watching this window'; body.appendChild(s);
    b.appendChild(body);
    var fold = document.createElement('button'); fold.textContent = '–'; fold.title = 'Fold away'; fold.style.cssText = 'cursor:pointer;border:0;border-radius:4px;padding:0 6px';
    fold.onclick = function () { var h = body.style.display === 'none'; body.style.display = h ? 'flex' : 'none'; fold.textContent = h ? '–' : '+'; };
    b.appendChild(fold);
    grip.onmousedown = function (e) {
      var r = b.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      b.style.transform = 'none'; b.style.left = r.left + 'px'; b.style.top = r.top + 'px';
      function mv(ev) { b.style.left = Math.max(0, ev.clientX - dx) + 'px'; b.style.top = Math.max(0, ev.clientY - dy) + 'px'; }
      function up() { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); }
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up); e.preventDefault();
    };
    (document.body || document.documentElement).appendChild(b);
  }
  if (document.body) bar(); else document.addEventListener('DOMContentLoaded', bar);
  var meta = {}, lastSrc = '', stamp = 0;
  setInterval(function () {
    var api = window.pywebview && window.pywebview.api;
    media = pick();
    if (!media || !api || !api.report) return;
    var src = media.currentSrc || media.src || '', dbg = '', now = Date.now();
    if (src !== lastSrc) { lastSrc = src; meta = describe(); stamp = now; dbg = 'soundcloud: ' + meta.title + ' / ' + meta.artist + ' (' + (media.duration || 0) + ' s)'; }
    else if (now - stamp > 1500) { stamp = now; var m2 = describe(); if (m2.title) meta = m2; }   // the bar can still show the old track just after a change
    api.report({ src: src, pos: media.currentTime || 0, dur: isFinite(media.duration) ? media.duration : 0, paused: !!media.paused || !!media.ended,
                 vol: media.muted ? 0 : media.volume, rate: media.playbackRate, title: meta.title, artist: meta.artist, album: meta.album, num: meta.num, art: meta.art, dbg: dbg });
  }, 250);
})();
"""

SITES = {
    'bandcamp': {'name': 'Bandcamp', 'title': 'Bandcamp - MiniDisc Manager', 'url': 'https://bandcamp.com/', 'js': PAGE_JS},
    'soundcloud': {'name': 'SoundCloud', 'title': 'SoundCloud - MiniDisc Manager', 'url': 'https://soundcloud.com/', 'js': SOUNDCLOUD_JS},
}

def _fname(text):
    return re.sub(r'[^\w.-]+', '_', text).strip('_')[:60] or 'track'


def browser_pid(parent):
    """The web view's browser process (msedgewebview2.exe started by this program), whose process tree holds all the page sound.
    Capturing this program's own process tree does not pick that sound up, but this process does. None if there is none yet."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    found = None
    try:
        e = Entry(); e.dwSize = ctypes.sizeof(Entry)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.th32ParentProcessID == parent and e.szExeFile.lower() == 'msedgewebview2.exe':
                found = e.th32ProcessID
                break
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return found


class Bridge:
    """The object the Bandcamp window's page talks to (js_api). Only report() is public: pywebview inspects public attributes."""
    def __init__(self, rec):
        self._rec = rec

    def report(self, state):
        self._rec._report(state)


class Recorder:
    def __init__(self, exe, work_dir, log=lambda text: None):
        self._exe, self._dir, self._log = exe, work_dir, log
        self._lock = threading.RLock()
        self._proc = None
        self._thread = None
        self._abs = 0                                   # bytes of sound captured since the capture started
        self._ring = collections.deque()                # (absolute offset, bytes) of the last few seconds
        self._ring_bytes = 0
        self._seg = None                                # the track being recorded
        self._closing = []                              # tracks the page has moved on from whose last seconds are still arriving
        self._last_end = None                           # absolute offset where the last finished track ended (for gapless albums)
        self._last_key = None
        self._far = False
        self.armed = True
        self.items = []                                 # recorded tracks, oldest first
        self._next_id = 1
        self.error = ''
        self.bridge = Bridge(self)
        self._load()

    # -- the kept recordings: <dir>\index.json lists the finished tracks, so they survive closing the program --------
    def _index(self):
        return os.path.join(self._dir, 'index.json')

    def _load(self):
        try:
            with open(self._index(), 'r', encoding='utf-8') as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        for name in os.listdir(self._dir):               # half-recorded leftovers of a crash
            if name.endswith('.raw'):
                try:
                    os.remove(os.path.join(self._dir, name))
                except OSError:
                    pass
        for item in saved:
            if item.get('status') == 'done' and item.get('path') and os.path.isfile(item['path']):
                self.items.append(item)
        self._next_id = max([i['id'] for i in self.items] + [0]) + 1

    def _save(self):
        keep = [i for i in self.items if i['status'] == 'done']
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp = self._index() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(keep, f)
            os.replace(tmp, self._index())
        except OSError as exc:
            self._log('bandcamp: could not save the recordings list: %r' % (exc,))

    def mark_added(self, ids):
        with self._lock:
            for i in self.items:
                if i['id'] in ids:
                    i['added'] = True
            self._save()

    # -- capture ---------------------------------------------------------------------------------
    def start(self, pid):
        """Begin capturing the sound of the web view that belongs to process `pid` (this program)."""
        pid = browser_pid(pid) or pid
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            if not os.path.isfile(self._exe):
                self.error = 'helper\\appaudio.exe is missing, so the sound cannot be recorded.'
                return
            self.error = ''
            os.makedirs(self._dir, exist_ok=True)
            self._abs = 0; self._ring.clear(); self._ring_bytes = 0; self._seg = None; self._closing = []; self._last_end = None
            self._proc = subprocess.Popen([self._exe, str(pid)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._thread = threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            p, self._proc = self._proc, None
            for seg in list(self._closing) + ([self._seg] if self._seg else []):
                self._abandon(seg, 'The Bandcamp window was closed before this track ended.')
            self._seg = None
        if p:
            try:
                p.stdin.close()
                p.wait(timeout=3)
            except Exception:
                p.kill()

    def _read_loop(self, proc):
        while True:
            chunk = proc.stdout.read(BPS // 10)
            if not chunk:
                break
            with self._lock:
                self._feed(chunk)
        try:
            err = proc.stderr.read().decode('utf-8', 'replace').strip()
        except Exception:
            err = ''
        with self._lock:
            if self._proc is proc and err:
                self.error = 'Sound capture stopped: ' + err
                self._log('appaudio: ' + err)

    def _feed(self, chunk):
        start = self._abs
        self._abs += len(chunk)
        self._ring.append((start, chunk)); self._ring_bytes += len(chunk)
        while self._ring_bytes > BPS * 10:
            _, old = self._ring.popleft(); self._ring_bytes -= len(old)
        for seg in list(self._closing) + ([self._seg] if self._seg else []):
            if seg['dead']:
                continue
            skip = max(0, seg['next'] - start)                 # a gapless track can start slightly after the bytes we have just got
            data = chunk[skip:]
            if not data:
                continue
            seg['file'].write(data); seg['have'] += len(data); seg['next'] += len(data)
            if seg['onset'] is None:
                if len(seg['head']) < HEAD_BYTES:
                    seg['head'] += data
                if len(seg['head']) >= HEAD_BYTES:
                    self._find_onset(seg)
            if seg['onset'] is not None and not seg['dead'] and seg['have'] >= seg['end_have']:
                self._finish(seg)

    def _find_onset(self, seg):
        """Where the music really starts inside the first seconds of the file; fixes where the track ends."""
        pcm = array.array('h'); pcm.frombytes(bytes(seg['head'][:len(seg['head']) // FRAME * FRAME]))
        onset = -1
        for i in range(0, len(pcm)):
            if abs(pcm[i]) >= SILENT:
                onset = max(0, i // 2 - RATE // 50)                      # 20 ms before the first sound
                break
        if onset < 0:
            self._drop(seg, 'No sound was captured. Check that the Bandcamp window is not muted in Windows.')
            return
        seg['onset'] = onset
        seg['head'] = b''
        seg['end_have'] = (onset + int(seg['dur'] * RATE)) * FRAME
        seg['end_abs'] = seg['start'] + seg['end_have']
        self._last_end = seg['end_abs']                                   # a gapless next track starts here

    def _drop(self, seg, why):
        """Throw a recording away and say why (the entry stays in the list as incomplete)."""
        seg['dead'] = True
        try:
            seg['file'].close()
            os.remove(seg['path'])
        except OSError:
            pass
        seg['item']['status'] = 'incomplete'; seg['item']['note'] = why
        if self._seg is seg:
            self._seg = None
        if seg in self._closing:
            self._closing.remove(seg)
        self._log('bandcamp: dropped "%s": %s' % (seg['item']['title'], why))

    def _ring_from(self, offset):
        """The captured sound from absolute `offset` to now (as much of it as is still in the ring)."""
        parts, first = [], None
        for start, data in self._ring:
            if start + len(data) <= offset:
                continue
            skip = max(0, offset - start)
            if first is None:
                first = start + skip
            parts.append(data[skip:])
        return (first if first is not None else self._abs), b''.join(parts)

    # -- the page's reports ----------------------------------------------------------------------
    def _report(self, s):
        try:
            with self._lock:
                self._handle(s)
        except Exception as exc:
            self._log('bandcamp report error: %r' % (exc,))

    def _handle(self, s):
        if s.get('note'):                                # a message from the page, not a player report
            self._log('bandcamp: page: ' + str(s['note'])[:300])
            return
        if not self.armed or not self._proc:
            return
        if s.get('src') and s['src'] == self._last_key and s.get('pos', 0) > 3:
            self._far = True                             # the track has been playing for a while: a start near 0 now is a replay
        if s.get('dbg'):
            self._log('bandcamp: page says: ' + s['dbg'][:1500])
        seg = self._seg
        playing = not s.get('paused') and s.get('dur', 0) > 1
        key = s.get('src') or ''
        if seg and not seg['dead']:
            if key != seg['key']:
                if seg['pos'] >= seg['dur'] - 2.0:
                    self._closing.append(seg)            # the album moved on by itself: this track played to its end; its last
                    self._seg = None                     # moments are still on their way from the speaker path, so it finishes on its own
                else:
                    self._abandon(seg, 'You skipped to another track before this one ended.')
            else:
                if seg['pos'] < seg['dur'] - 1.5:        # near the end the player stops by itself, which is not a pause
                    expect = seg['pos'] + (self._abs - seg['at']) / BPS
                    if s.get('paused') or abs(s['pos'] - expect) > 1.5:
                        self._log('bandcamp: stop reason: paused=%s pos=%.2f expected=%.2f dur=%.1f src=%s' % (s.get('paused'), s['pos'], expect, seg['dur'], key[-40:]))
                        self._abandon(seg, 'You paused or moved within this track, so it is not complete. Play it again from its start.')
                        return
                    seg['pos'], seg['at'] = s['pos'], self._abs
                if s.get('vol', 1) < 0.99:
                    seg['item']['note'] = 'Bandcamp’s volume was below maximum while this recorded, so it is quieter than the original.'
                if s.get('rate', 1) != 1:
                    self._abandon(seg, 'The playback speed was changed, so this track is not usable.', keep=False)
                return
        if not playing or not key:
            return
        if key == self._last_key and (s['pos'] > 3 or not self._far):
            return                                       # the tail of a track that has just been recorded
        if s['pos'] > 3:
            return                                       # joined in the middle: wait for the next track
        self._begin(s, key)

    def _begin(self, s, key):
        dur = float(s['dur'])
        gapless = self._last_end is not None and (self._abs - self._last_end) / BPS <= GAP_JOIN + max(0.0, s['pos'])
        if gapless:
            offset = self._last_end
        else:
            offset = max(0, self._abs - int((s['pos'] + LEAD) * BPS))
            offset -= offset % FRAME                     # stay on a sample boundary
        first, head = self._ring_from(offset)
        if offset > self._abs:                           # the previous track's sound has not all arrived yet: start where it ends
            first, head = offset, b''
        item = {'id': self._next_id, 'title': s.get('title') or 'Track', 'artist': s.get('artist') or '', 'album': s.get('album') or '',
                'num': s.get('num') or 0, 'seconds': round(dur, 1), 'status': 'recording', 'note': '', 'art': s.get('art') or '', 'path': ''}
        self._next_id += 1
        self.items.append(item)
        path = os.path.join(self._dir, 'bc%03d_%s.raw' % (item['id'], _fname(item['title'])))
        f = open(path, 'wb')
        f.write(head)
        # the file holds [lead] + the track; _find_onset() works out where the music really starts and so where it ends
        need = int(((0 if gapless else LEAD + 0.15) + dur) * BPS)
        seg = {'item': item, 'key': key, 'dur': dur, 'pos': s['pos'], 'at': self._abs, 'file': f, 'path': path, 'have': len(head),
               'next': first + len(head), 'need': max(need, len(head)), 'gapless': gapless, 'dead': False, 'start': first,
               'onset': None, 'head': bytearray(head), 'end_have': 0, 'end_abs': 0}
        self._seg = seg
        if seg['onset'] is None and len(seg['head']) >= HEAD_BYTES:
            self._find_onset(seg)
        if seg['onset'] is not None and not seg['dead'] and seg['have'] >= seg['end_have']:
            self._finish(seg)
        self._last_key = key
        self._far = False
        self._log('bandcamp: recording "%s" (%.0f s, %s)' % (item['title'], dur, 'gapless' if gapless else 'from the start'))

    def _salvage(self, seg, why):
        """Keep what was recorded of a track that stopped early, as a shorter 'done' entry marked partial. False if there is nothing usable."""
        item = seg['item']
        try:
            with open(seg['path'], 'rb') as f:
                data = f.read()
            n = len(data) // FRAME * FRAME
            pcm = array.array('h'); pcm.frombytes(data[:n])
            onset = seg['onset']
            if onset is None:                            # the music's start was never worked out: first sound in what we have
                onset = next((max(0, i // 2 - RATE // 50) for i in range(len(pcm)) if abs(pcm[i]) >= SILENT), None)
                if onset is None:
                    return False
            out = pcm[onset * 2:]
            end = len(out)
            quiet = RATE // 20 * 2                       # drop the silence recorded after a pause, in 50 ms steps
            while end > quiet and max(abs(v) for v in out[end - quiet:end]) < SILENT:
                end -= quiet
            out = out[:end]
            secs = len(out) / 2 / RATE
            if secs < 3:
                return False
            wav = os.path.join(self._dir, 'bc%03d_%s.wav' % (item['id'], _fname(item['title'])))
            with wave.open(wav, 'wb') as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
                w.writeframes(out.tobytes())
            full = item['seconds']
            item.update(path=wav, status='done', partial=True, seconds=round(secs, 1), peak=round(max(max(out), -min(out)) / 32767, 3),
                        note='Partial: only %d:%02d of %d:%02d was recorded (%s)' % (secs // 60, secs % 60, full // 60, full % 60, why.rstrip('.').lower()))
            self._log('bandcamp: kept the first %.1f s of "%s" as a partial recording' % (secs, item['title']))
            self._save()
            return True
        except Exception as exc:
            self._log('bandcamp: salvage failed: %r' % (exc,))
            return False

    def _abandon(self, seg, why, keep=True):
        seg['dead'] = True
        try:
            seg['file'].close()
        except OSError:
            pass
        kept = keep and self._salvage(seg, why)
        try:
            os.remove(seg['path'])
        except OSError:
            pass
        if kept:
            if self._seg is seg:
                self._seg = None
            if seg in self._closing:
                self._closing.remove(seg)
            self._last_end = None; self._last_key = None; self._far = False
            return
        seg['item']['status'] = 'incomplete'; seg['item']['note'] = why
        if self._seg is seg:
            self._seg = None
        if seg in self._closing:
            self._closing.remove(seg)
        self._last_end = None
        self._last_key = None
        self._far = False
        self._log('bandcamp: abandoned "%s": %s' % (seg['item']['title'], why))

    def _finish(self, seg):
        """The file now holds the whole track (from the lead to the end): cut it at the music's start and write the WAV."""
        seg['dead'] = True
        seg['file'].close()
        item = seg['item']
        if self._seg is seg:
            self._seg = None
        if seg in self._closing:
            self._closing.remove(seg)
        try:
            with open(seg['path'], 'rb') as f:
                data = f.read()
            os.remove(seg['path'])
            n = len(data) // FRAME * FRAME
            pcm = array.array('h'); pcm.frombytes(data[:n])
            onset = seg['onset']
            want = int(seg['dur'] * RATE)
            out = pcm[onset * 2:(onset + want) * 2]
            if len(out) < want * 2:
                out.extend([0] * (want * 2 - len(out)))
            peak = max(max(out), -min(out)) if len(out) else 0
            if peak < SILENT:
                item['status'] = 'incomplete'; item['note'] = 'The track was silent.'
                self._last_end = None
                self._log('bandcamp: "%s" was silent' % item['title'])
                return
            wav = os.path.join(self._dir, 'bc%03d_%s.wav' % (item['id'], _fname(item['title'])))
            with wave.open(wav, 'wb') as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
                w.writeframes(out.tobytes())
            item['path'] = wav
            item['peak'] = round(peak / 32767, 3)
            item['status'] = 'done'
            self._log('bandcamp: recorded "%s" (%.1f s, peak %.2f)' % (item['title'], want / RATE, peak / 32767))
            self._save()
        except Exception as exc:
            item['status'] = 'incomplete'; item['note'] = 'Recording failed: %s' % exc
            self._log('bandcamp: finish failed: %r' % (exc,))
    # -- for the page / API ----------------------------------------------------------------------
    def status(self):
        with self._lock:
            seg = self._seg
            cur = None
            if seg and not seg['dead']:
                cur = {'id': seg['item']['id'], 'done': min(1.0, seg['have'] / max(1, seg['end_have'] or seg['need']))}
            return {'running': bool(self._proc and self._proc.poll() is None), 'armed': self.armed, 'error': self.error,
                    'items': [dict(i, path='') for i in self.items], 'current': cur}

    def remove(self, ids):
        with self._lock:
            for item in [i for i in self.items if i['id'] in ids]:
                for seg in list(self._closing) + ([self._seg] if self._seg else []):
                    if seg['item'] is item:
                        self._abandon(seg, 'Removed.', keep=False)
                if item.get('path'):
                    try:
                        os.remove(item['path'])
                    except OSError:
                        pass
                self.items.remove(item)
            self._save()

    def paths(self, ids):
        with self._lock:
            return [i for i in self.items if i['id'] in ids and i['status'] == 'done']

    def clear_files(self):
        self.stop()
        with self._lock:
            remove_item_files(self.items)
            self.items = []


def fetch_cover(url, limit=8 * 1000 * 1000):
    """The album picture of a Bandcamp page (a public image), or None."""
    if not url or not url.startswith('https://') or not any(h in url.split('/')[2] for h in ('.bcbits.com')):
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MiniDiscManager (personal use)'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(limit + 1)
        return data if 0 < len(data) <= limit else None
    except Exception:
        return None

