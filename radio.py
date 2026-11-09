"""Record an internet radio station, song by song.

Stations come from radio-browser.info, a free community directory. Most stations are plain Icecast / Shoutcast streams (MP3 or AAC)
that announce the current "Artist - Title" inside the stream itself. This module reads such a stream directly, cuts the audio exactly
where the announced title changes, and decodes each song to a WAV with ffmpeg. Nothing else the PC plays is involved.

Streams that send no titles, or that are not MP3 / AAC (Ogg, FLAC, HLS), are recorded as one stretch of a chosen length instead.

The recorder offers the same members as bandcamp.Recorder (items, status, remove, paths, mark_added, clear_files, stop), so the page's
list of recorded tracks and the code that writes them to a disc are shared.
"""
import json
import os
import queue
import re
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import wave

from mdm_common import remove_item_files

UA = 'MiniDiscManager/0.11 (personal use)'
DIRECTORY = ['de1', 'nl1', 'at1', 'fi1']        # radio-browser.info mirrors, tried in turn
SHORT_SONG = 25.0                               # a "song" shorter than this is probably a jingle, announcement or advert
MAX_MINUTES = 120
EXT = {'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/aac': 'aac', 'audio/aacp': 'aac', 'audio/x-aac': 'aac'}


def search(query, by='name', limit=40):
    """Stations from radio-browser.info, most listened first: [{id, name, url, codec, bitrate, country, tags, hls}]."""
    key = {'name': 'name', 'genre': 'tag', 'country': 'country'}.get(by, 'name')
    qs = urllib.parse.urlencode({key: query, 'limit': limit, 'hidebroken': 'true', 'order': 'clickcount', 'reverse': 'true'})
    rows, last = None, None
    for host in DIRECTORY:
        try:
            req = urllib.request.Request('https://%s.api.radio-browser.info/json/stations/search?%s' % (host, qs), headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                rows = json.loads(r.read().decode('utf-8'))
            break
        except Exception as exc:
            last = exc
    if rows is None:
        raise RuntimeError('The station directory (radio-browser.info) could not be reached: %s' % (last,))
    out = []
    for r in rows:
        url = r.get('url_resolved') or r.get('url') or ''
        if not url.lower().startswith(('http://', 'https://')):
            continue
        out.append({'id': r.get('stationuuid', ''), 'name': (r.get('name') or '').strip() or 'Station', 'url': url,
                    'codec': (r.get('codec') or '').upper(), 'bitrate': r.get('bitrate') or 0, 'country': r.get('country') or '',
                    'tags': ', '.join((r.get('tags') or '').split(',')[:3]), 'hls': bool(r.get('hls'))})
    return out


def lookup(uuid):
    """The directory's current entry for a station id (its stream address may have changed since it was saved), or None."""
    if not uuid:
        return None
    for host in DIRECTORY:
        try:
            req = urllib.request.Request('https://%s.api.radio-browser.info/json/stations/byuuid/%s' % (host, urllib.parse.quote(uuid)), headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                rows = json.loads(r.read().decode('utf-8'))
            if rows:
                url = rows[0].get('url_resolved') or rows[0].get('url') or ''
                return {'url': url, 'codec': (rows[0].get('codec') or '').upper(), 'bitrate': rows[0].get('bitrate') or 0,
                        'hls': bool(rows[0].get('hls'))} if url.lower().startswith(('http://', 'https://')) else None
            return None
        except Exception:
            continue
    return None


def count_click(uuid):
    """radio-browser.info asks clients to say when a station is played (it ranks stations by this). Best effort."""
    if not uuid:
        return
    for host in DIRECTORY[:2]:
        try:
            req = urllib.request.Request('https://%s.api.radio-browser.info/json/url/%s' % (host, urllib.parse.quote(uuid)), headers={'User-Agent': UA})
            urllib.request.urlopen(req, timeout=6).read()
            return
        except Exception:
            continue


def open_stream(url, timeout=20):
    """Connect to a radio stream asking for in-stream titles. Shoutcast answers "ICY 200 OK", which http.client refuses, so this talks
    plain HTTP/1.0 itself. Returns (socket, buffered reader, lower-cased headers)."""
    for _ in range(6):
        u = urllib.parse.urlsplit(url)
        port = u.port or (443 if u.scheme == 'https' else 80)
        sock = socket.create_connection((u.hostname, port), timeout=timeout)
        try:
            if u.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
            path = (u.path or '/') + ('?' + u.query if u.query else '')
            sock.sendall(('GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: %s\r\nAccept: */*\r\nIcy-MetaData: 1\r\nConnection: close\r\n\r\n'
                          % (path, u.netloc, UA)).encode('latin-1'))
            f = sock.makefile('rb')
            status = f.readline().decode('latin-1').strip()
            headers = {}
            while True:
                line = f.readline()
                if line in (b'\r\n', b'\n', b''):
                    break
                k, _, v = line.decode('latin-1').partition(':')
                headers[k.strip().lower()] = v.strip()
            parts = status.split(' ', 2)
            code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else (200 if status.startswith('ICY 200') else 0)
            if code in (301, 302, 303, 307, 308) and headers.get('location'):
                sock.close()
                url = urllib.parse.urljoin(url, headers['location'])
                continue
            if code != 200:
                raise RuntimeError('The station answered "%s".' % (status or 'nothing'))
            return sock, f, headers
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            raise
    raise RuntimeError('The station redirected too many times.')


def _text(b):
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('latin-1')


def split_title(raw):
    """'Artist - Title' -> (title, artist)."""
    m = re.match(r'^(.*?)\s+-\s+(.*)$', raw.strip())
    return (m.group(2).strip(), m.group(1).strip()) if m else (raw.strip(), '')


class RadioRecorder:
    def __init__(self, ffmpeg, work_dir, log=lambda text: None):
        self._ffmpeg, self._dir, self._log = ffmpeg, work_dir, log
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._jobs = queue.Queue()
        self._worker = None
        self._discard = set()
        self._cur = None                    # the song being received: {item, file, path, ext, t0}
        self._next_id = 1
        self.armed = True
        self.items = []
        self.error = ''
        self.message = ''
        self.station = ''
        self.mode = ''

    # -- starting and stopping ---------------------------------------------------------------------
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self, station, mode='songs', minutes=10):
        """Begin recording `station` ({id, name, url, codec, hls}). mode 'songs' cuts by announced title; 'single' records `minutes`
        as one track. Raises RuntimeError with a message for the user if it cannot start."""
        self.stop()
        if not os.path.isfile(self._ffmpeg):
            raise RuntimeError('runtime\\ffmpeg.exe is missing, so the stream cannot be decoded.')
        os.makedirs(self._dir, exist_ok=True)
        self.error, self.message, self.station, self.mode = '', '', station['name'], mode
        self._stop = threading.Event()
        threading.Thread(target=count_click, args=(station.get('id'),), daemon=True).start()
        if mode == 'songs':
            if station.get('hls'):
                raise RuntimeError('This station uses HLS, which carries no song titles. Record it as one stretch of a chosen length instead.')
            sock, f, hdr = open_stream(station['url'])
            ext = EXT.get(hdr.get('content-type', '').split(';')[0].strip().lower())
            if not ext or not hdr.get('icy-metaint', '').isdigit() or int(hdr['icy-metaint']) <= 0:
                sock.close()
                raise RuntimeError('This station sends %s without song titles, so it cannot be split into songs. '
                                   'Record it as one stretch of a chosen length instead.'
                                   % ('audio of a kind that cannot be cut (' + hdr.get('content-type', 'unknown type') + ')' if not ext else 'audio'))
            self.message = 'Connected to %s. Waiting for the next song to begin…' % station['name']
            self._thread = threading.Thread(target=self._songs, args=(station, sock, f, hdr, ext), daemon=True)
        else:
            minutes = max(1, min(MAX_MINUTES, int(minutes)))
            self._thread = threading.Thread(target=self._single, args=(station, minutes), daemon=True)
        self._thread.start()

    def stop(self):
        t = self._thread
        self._stop.set()
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=8)
        self._thread = None

    # -- one stretch of a chosen length (any stream ffmpeg can read) -------------------------------
    def _new_item(self, title, artist, status='recording', note=''):
        with self._lock:
            item = {'id': self._next_id, 'title': title, 'artist': artist, 'album': '', 'num': 0, 'seconds': 0.0, 'status': status,
                    'note': note, 'art': '', 'path': '', 'partial': False, 'skip': False}
            self._next_id += 1
            self.items.append(item)
            return item

    def _single(self, station, minutes):
        stamp = time.strftime('%d %b %H:%M')
        item = self._new_item('%s %s' % (station['name'], stamp), station['name'])
        wav = os.path.join(self._dir, 'rd%03d.wav' % item['id'])
        t0 = time.monotonic()
        self.message = 'Recording %s for %d minutes…' % (station['name'], minutes)
        try:
            p = subprocess.Popen([self._ffmpeg, '-y', '-loglevel', 'error', '-user_agent', UA, '-i', station['url'], '-t', str(minutes * 60),
                                  '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', wav], stdin=subprocess.PIPE,
                                 stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            asked = False
            while p.poll() is None:
                item['seconds'] = round(time.monotonic() - t0, 1)
                if self._stop.is_set() and not asked:
                    asked = True
                    try:
                        p.stdin.write(b'q\n'); p.stdin.flush()          # ffmpeg then finishes the WAV properly
                    except OSError:
                        pass
                    try:
                        p.wait(timeout=6)
                    except subprocess.TimeoutExpired:
                        p.kill()
                    break
                time.sleep(0.4)
            err = _text(p.stderr.read()).strip() if p.stderr else ''
            if p.returncode not in (0, None) and not (os.path.isfile(wav) and os.path.getsize(wav) > 100000):
                raise RuntimeError(err.splitlines()[-1] if err else 'ffmpeg stopped (code %s).' % p.returncode)
            self._finish_wav(item, wav, early=self._stop.is_set(), want=minutes * 60)
        except Exception as exc:
            self._fail(item, 'Recording failed: %s' % exc)
            self.error = 'Recording failed: %s' % exc
        self.message = 'Recording finished.'

    # -- song by song ------------------------------------------------------------------------------
    def _songs(self, station, sock, f, hdr, ext):
        metaint = int(hdr['icy-metaint'])
        title_now, failures = None, 0
        while True:
            try:
                if sock is None:
                    self.message = 'Reconnecting to %s…' % station['name']
                    sock, f, hdr = open_stream(station['url'])
                    if int(hdr.get('icy-metaint', '0') or 0) != metaint:
                        raise RuntimeError('The station changed its stream format.')
                title_now = None
                self._begin_song('', 'Joined part-way through: the first song is only partly recorded.', ext, joined=True)
                self.message = 'Recording %s. Waiting for the first song title…' % station['name']
                while not self._stop.is_set():
                    audio = f.read(metaint)
                    if len(audio) < metaint:
                        raise EOFError('The station stopped sending.')
                    with self._lock:
                        if self._cur:
                            self._cur['file'].write(audio)
                            self._cur['item']['seconds'] = round(time.monotonic() - self._cur['t0'], 1)
                    n = f.read(1)
                    if not n:
                        raise EOFError('The station stopped sending.')
                    if n[0]:
                        raw = f.read(n[0] * 16)
                        m = re.search(r"StreamTitle='(.*?)'(?:;|\x00|$)", _text(raw).rstrip('\x00'), re.S)
                        title = m.group(1).strip() if m else ''
                        if title and title != title_now:
                            self._on_title(title, title_now is None, station, ext)
                            title_now = title
                    failures = 0
                break
            except Exception as exc:
                self._end_song(early=True, why='The connection dropped during this song.')
                try:
                    sock and sock.close()
                except OSError:
                    pass
                sock = None
                if self._stop.is_set():
                    break
                failures += 1
                self._log('radio: %s: %r' % (station['name'], exc))
                if failures > 3:
                    self.error = 'The connection to %s was lost: %s' % (station['name'], exc)
                    break
                self.message = 'Connection lost, trying again…'
                if self._stop.wait(3):
                    break
        self._end_song(early=True, why='Recording was stopped during this song.')
        try:
            sock and sock.close()
        except OSError:
            pass
        if not self.error:
            self.message = 'Stopped.'

    def _begin_song(self, title, note, ext, joined=False):
        item = self._new_item(title or 'Joined mid-song', '', note=note)
        item['joined'] = joined
        path = os.path.join(self._dir, 'rd%03d.%s' % (item['id'], ext))
        with self._lock:
            self._cur = {'item': item, 'file': open(path, 'wb'), 'path': path, 'ext': ext, 't0': time.monotonic()}

    def _on_title(self, raw, first, station, ext):
        title, artist = split_title(raw)
        with self._lock:
            cur = self._cur
            if first and cur:                         # the title of the song we joined part-way through
                cur['item'].update(title=title, artist=artist)
                self.message = 'Recording %s. Waiting for the next song to begin…' % station['name']
                return
        self._end_song(early=False)
        self._begin_song(title, '', ext)
        with self._lock:
            self._cur['item']['artist'] = artist
            if not title or title.lower() == station['name'].lower():
                self._cur['item']['skip'] = True
        self.message = 'Recording %s: %s' % (station['name'], raw)

    def _end_song(self, early, why=''):
        with self._lock:
            cur, self._cur = self._cur, None
        if not cur:
            return
        try:
            cur['file'].close()
        except OSError:
            pass
        item = cur['item']
        item['seconds'] = round(time.monotonic() - cur['t0'], 1)
        partial = early or item.get('joined')
        if item['id'] in self._discard or (early and item['seconds'] < 3):
            self._drop(item, cur['path'])
            return
        self._jobs.put((item, cur['path'], partial, why if early else ''))
        if not self._worker or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._decode_loop, daemon=True)
            self._worker.start()

    def _drop(self, item, path):
        try:
            os.remove(path)
        except OSError:
            pass
        with self._lock:
            if item in self.items:
                self.items.remove(item)
            self._discard.discard(item['id'])

    def _decode_loop(self):
        while True:
            try:
                item, path, partial, why = self._jobs.get(timeout=30)
            except queue.Empty:
                return
            wav = os.path.splitext(path)[0] + '.wav'
            try:
                r = subprocess.run([self._ffmpeg, '-y', '-loglevel', 'error', '-i', path, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', wav],
                                   capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if r.returncode != 0 or not os.path.isfile(wav):
                    raise RuntimeError(_text(r.stderr).strip().splitlines()[-1] if r.stderr else 'ffmpeg failed')
                if item['id'] in self._discard:
                    self._drop(item, wav)
                    continue
                self._finish_wav(item, wav, early=partial, want=0, why=why)
            except Exception as exc:
                self._fail(item, 'Could not decode this song: %s' % exc)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _finish_wav(self, item, wav, early, want, why=''):
        with wave.open(wav, 'rb') as w:
            secs = w.getnframes() / float(w.getframerate())
        if secs < 3:
            self._fail(item, 'Almost nothing was recorded.')
            try:
                os.remove(wav)
            except OSError:
                pass
            return
        item.update(path=wav, seconds=round(secs, 1), status='done')
        notes = []
        if item.get('joined') or (early and want == 0):
            item['partial'] = True; item['skip'] = True
            notes.append(item['note'] if item.get('joined') and item['note'] else 'Partial: ' + (why or 'recording was stopped').rstrip('.').lower() + '.')
        elif want and early and secs < want - 2:
            item['partial'] = True
            notes.append('Partial: stopped after %d:%02d of the %d:%02d asked for.' % (secs // 60, secs % 60, want // 60, want % 60))
        elif secs < SHORT_SONG and not want:
            item['skip'] = True
            notes.append('Only %d s long: probably a jingle or announcement, so it is not ticked.' % secs)
        item['note'] = ' '.join(notes)
        self._log('radio: recorded "%s" (%.1f s)' % (item['title'], secs))

    def _fail(self, item, why):
        item['status'] = 'incomplete'
        item['note'] = why
        self._log('radio: ' + why)

    # -- for the page / API (same shape as bandcamp.Recorder) ---------------------------------------
    def status(self):
        with self._lock:
            cur = self._cur['item'] if self._cur else None
            if not cur and self.mode == 'single' and self.running():
                cur = next((i for i in self.items if i['status'] == 'recording'), None)
            return {'running': self.running(), 'armed': True, 'error': self.error, 'message': self.message, 'station': self.station,
                    'mode': self.mode, 'items': [dict(i, path='') for i in self.items],
                    'current': {'id': cur['id'], 'done': 0, 'seconds': cur['seconds']} if cur else None}

    def remove(self, ids):
        with self._lock:
            for item in [i for i in self.items if i['id'] in ids]:
                if item['status'] == 'recording':
                    self._discard.add(item['id'])      # dropped as soon as it has ended
                    continue
                if item.get('path'):
                    try:
                        os.remove(item['path'])
                    except OSError:
                        pass
                self.items.remove(item)

    def paths(self, ids):
        with self._lock:
            return [i for i in self.items if i['id'] in ids and i['status'] == 'done']

    def mark_added(self, ids):
        with self._lock:
            for i in self.items:
                if i['id'] in ids:
                    i['added'] = True

    def clear_files(self):
        self.stop()
        with self._lock:
            remove_item_files(self.items)
            self.items = []
