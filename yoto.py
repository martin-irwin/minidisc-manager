"""Reading a Yoto player's card and fetching its audio, through Yoto's own developer API (https://yoto.dev).

The user signs in once in the browser (OAuth with PKCE, redirected back to this PC at 127.0.0.1); the program keeps only a refresh token,
in USER_DIR\\yoto-token.json. Everything here only READS the Yoto account: the player list, the card in a player, a playlist's tracks and the
signed download links of its audio. The only things that ever change the Yoto account are create_playlist() and append_to_playlist() (after
upload_audio()), used by "Send to Yoto Card": a NEW playlist, or new tracks added at the END of a playlist the user picks (a backup copy is
kept and the result is checked). Nothing is ever deleted.

Make Your Own (MYO) playlists are the user's own uploads, so those are what the app offers. A card from Yoto's shop can be read too, but the
API only answers for content the signed-in account may view, which is the same limit the Yoto app has.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.yotoplay.com'
LOGIN = 'https://login.yotoplay.com'
REDIRECT_PORT = 8787
REDIRECT = 'http://127.0.0.1:%d/callback' % REDIRECT_PORT
# user:content:manage is only used by "Send to Yoto Card" (it creates a new playlist); everything else only reads.
SCOPES = 'user:content:view user:content:manage family:library:view family:devices:view family:devices:control offline_access'
# A public client made in the Yoto developer dashboard (https://dashboard.yoto.dev); a public client has no secret. A file named
# yoto-client-id.txt next to the token replaces it.
CLIENT_ID = 'tpc_funBgUXCHV89CEc1dcYjSd'
UA = 'MiniDiscManager'


class YotoError(Exception):
    pass


def _post_form(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(), {'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except ValueError:
            body = {}
        raise YotoError(body.get('error_description') or body.get('error') or 'Yoto answered with HTTP %d.' % exc.code)
    except (urllib.error.URLError, OSError) as exc:
        raise YotoError('Yoto could not be reached: %s' % getattr(exc, 'reason', exc))


class Yoto:
    def __init__(self, user_dir, log=None):
        self._dir = user_dir
        self._log = log or (lambda *a: None)
        self._lock = threading.Lock()
        self._tok = None
        self._cancel_login = False

    # -- sign-in ---------------------------------------------------------------------------------
    @property
    def _token_path(self):
        return os.path.join(self._dir, 'yoto-token.json')

    @property
    def client_id(self):
        try:
            with open(os.path.join(self._dir, 'yoto-client-id.txt'), 'r', encoding='utf-8') as f:
                text = f.read().strip()
                if text:
                    return text
        except OSError:
            pass
        return CLIENT_ID

    def _load(self):
        if self._tok is None:
            try:
                with open(self._token_path, 'r', encoding='utf-8') as f:
                    self._tok = json.load(f)
            except (OSError, ValueError):
                self._tok = {}
        return self._tok

    def _save(self, tok):
        tok = dict(tok, saved_at=int(time.time()))
        os.makedirs(self._dir, exist_ok=True)
        tmp = self._token_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(tok, f)
        os.replace(tmp, self._token_path)
        self._tok = tok

    def signed_in(self):
        return bool(self._load().get('refresh_token'))

    def can_manage(self):
        """True if the saved sign-in includes the permission to create playlists (a sign-in made before that was added does not)."""
        return 'user:content:manage' in (self._load().get('scope') or '').split()

    def sign_out(self):
        self._tok = {}
        try:
            os.remove(self._token_path)
        except OSError:
            pass

    def cancel_sign_in(self):
        self._cancel_login = True

    def sign_in(self, open_url, timeout=240):
        """Opens Yoto's login page (open_url(url)) and waits for the browser to come back to this PC. Raises YotoError."""
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        got = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                got.update({k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()})
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b'<html><body style="font-family:sans-serif;padding:40px"><h2>Signed in</h2>'
                                 b'<p>You can close this tab and go back to MiniDisc Manager.</p></body></html>')

            def log_message(self, *a):
                pass

        try:
            srv = http.server.HTTPServer(('127.0.0.1', REDIRECT_PORT), Handler)
        except OSError:
            raise YotoError('Port %d on this PC is busy, so the sign-in could not start. Close the program using it and try again.' % REDIRECT_PORT)
        srv.timeout = 1.0
        self._cancel_login = False
        url = LOGIN + '/authorize?' + urllib.parse.urlencode({
            'audience': API, 'scope': SCOPES, 'response_type': 'code', 'client_id': self.client_id,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'redirect_uri': REDIRECT})
        try:
            open_url(url)
            end = time.time() + timeout
            while 'code' not in got and 'error' not in got:
                if self._cancel_login:
                    raise YotoError('Sign-in cancelled.')
                if time.time() > end:
                    raise YotoError('The sign-in was not finished in time. Press "Sign in to Yoto" and try again.')
                srv.handle_request()
        finally:
            srv.server_close()
        if 'error' in got:
            raise YotoError('Yoto refused the sign-in: %s' % (got.get('error_description') or got['error']))
        tok = _post_form(LOGIN + '/oauth/token', {'grant_type': 'authorization_code', 'client_id': self.client_id, 'code_verifier': verifier,
                                                   'code': got['code'], 'redirect_uri': REDIRECT})
        self._save(tok)

    def _access_token(self):
        """A valid access token; refreshes it (refresh tokens are single use, so the new one is saved at once)."""
        with self._lock:
            tok = self._load()
            if not tok.get('refresh_token'):
                raise YotoError('Not signed in to Yoto.')
            try:
                exp = json.loads(base64.urlsafe_b64decode(tok['access_token'].split('.')[1] + '==')).get('exp', 0)
            except Exception:
                exp = 0
            if tok.get('access_token') and exp - 60 > time.time():
                return tok['access_token']
            try:
                new = _post_form(LOGIN + '/oauth/token', {'grant_type': 'refresh_token', 'client_id': self.client_id, 'refresh_token': tok['refresh_token']})
            except YotoError as exc:
                self.sign_out()
                raise YotoError('The Yoto sign-in has expired. Sign in again. (%s)' % exc)
            new.setdefault('refresh_token', tok['refresh_token'])
            self._save(new)
            return new['access_token']

    # -- reading the account ---------------------------------------------------------------------
    def _get(self, path):
        req = urllib.request.Request(API + path, headers={'Authorization': 'Bearer ' + self._access_token(), 'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise YotoError('Yoto has no playlist like that, or this account may not view it.')
            raise YotoError('Yoto answered with HTTP %d.' % exc.code)
        except (urllib.error.URLError, OSError) as exc:
            raise YotoError('Yoto could not be reached: %s' % getattr(exc, 'reason', exc))

    def playlists(self):
        """The signed-in user's own (MYO) playlists: [{id, title}]."""
        return [{'id': c.get('cardId'), 'title': c.get('title') or c.get('cardId')} for c in self._get('/content/mine').get('cards', []) if c.get('cardId')]

    def players(self):
        """The players of the family, each with the card in it now: [{id, name, online, card, inserted}]."""
        out = []
        for d in self._get('/device-v2/devices/mine').get('devices', []):
            row = {'id': d.get('deviceId'), 'name': d.get('name') or d.get('deviceId'), 'online': bool(d.get('online')), 'card': None, 'inserted': False}
            if row['online']:
                try:
                    st = (self._get('/device-v2/%s/config' % d['deviceId']).get('device') or {}).get('status') or {}
                    card = st.get('activeCard')
                    row['card'] = card if isinstance(card, str) and card and card != 'none' else None
                    row['inserted'] = bool(st.get('cardInserted'))
                except YotoError as exc:
                    self._log('yoto: status of %s failed: %s' % (row['name'], exc))
            out.append(row)
        return out

    def card(self, card_id):
        """A playlist: {id, title, cover, tracks: [{key, title, seconds, bytes, format, channels, url}]}. The URLs are signed and expire."""
        c = self._get('/content/%s?playable=true&signingType=s3' % urllib.parse.quote(card_id, safe='')).get('card') or {}
        tracks = []
        for ch in (c.get('content') or {}).get('chapters') or []:
            for t in ch.get('tracks') or []:
                if t.get('type', 'audio') != 'audio' or not t.get('trackUrl'):
                    continue
                title = (t.get('title') or ch.get('title') or '').strip()
                if len(tracks) and not t.get('title') and ch.get('title') and len(ch.get('tracks') or []) > 1:
                    title = (ch.get('title') + ' - ' + title).strip(' -')
                tracks.append({'key': '%s/%s' % (ch.get('key'), t.get('key')), 'title': _clean_title(title) or 'Track %d' % (len(tracks) + 1),
                               'seconds': t.get('duration') or ch.get('duration') or 0, 'bytes': t.get('fileSize') or 0,
                               'format': t.get('format') or '', 'channels': t.get('channels') or '', 'url': t['trackUrl']})
        cover = ((c.get('metadata') or {}).get('cover') or {}).get('imageL')
        return {'id': c.get('cardId') or card_id, 'title': c.get('title') or '', 'cover': cover, 'tracks': tracks,
                'author': ', '.join((c.get('metadata') or {}).get('authors') or [])}

    # -- sending audio to Yoto (creates a NEW playlist; nothing existing is changed) ---------------
    def _json(self, method, path, body=None):
        req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={'Authorization': 'Bearer ' + self._access_token(), 'User-Agent': UA, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            try:
                detail = (json.load(exc).get('error') or {}).get('message')
            except ValueError:
                detail = None
            raise YotoError('Yoto refused the request (HTTP %d%s).' % (exc.code, ': ' + detail if detail else ''))
        except (urllib.error.URLError, OSError) as exc:
            raise YotoError('Yoto could not be reached: %s' % getattr(exc, 'reason', exc))

    def upload_audio(self, path, progress=None, cancel=None, wait=900):
        """Uploads one audio file and waits for Yoto to convert it. Returns {sha, duration, fileSize, channels, format}, or None if
        cancelled. `progress(done, total)` follows the upload; the conversion is polled for up to `wait` seconds."""
        up = self._json('GET', '/media/transcode/audio/uploadUrl')
        info = up.get('upload', up)
        size = os.path.getsize(path)

        class Body:
            def __init__(self, f):
                self.f, self.done = f, 0

            def read(self, n=-1):
                if cancel and cancel():
                    raise YotoError('cancelled')
                chunk = self.f.read(n if n and n > 0 else 1 << 20)
                self.done += len(chunk)
                if progress:
                    progress(self.done, size)
                return chunk

        ctype = {'.flac': 'audio/flac', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
        try:
            with open(path, 'rb') as f:
                req = urllib.request.Request(info['uploadUrl'], data=Body(f), method='PUT',
                                             headers={'Content-Type': ctype, 'Content-Length': str(size), 'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=600):
                    pass
        except YotoError as exc:
            if str(exc) == 'cancelled':
                return None
            raise
        except (urllib.error.URLError, OSError) as exc:
            raise YotoError('The upload to Yoto failed: %s' % getattr(exc, 'reason', exc))
        end = time.time() + wait
        while time.time() < end:
            if cancel and cancel():
                return None
            tr = self._get('/media/upload/%s/transcoded?loudnorm=false' % urllib.parse.quote(info['uploadId'], safe=''))
            found = _find(tr, 'transcodedSha256')
            if found:
                ti = _find(tr, 'transcodedInfo') or {}
                return {'sha': found, 'duration': int(round(ti.get('duration') or 0)), 'fileSize': int(ti.get('fileSize') or 0),
                        'channels': ti.get('channels') or 'stereo', 'format': ti.get('format') or 'opus'}
            time.sleep(1)
        raise YotoError('Yoto took too long to convert the audio. It may still finish; check the Yoto app before trying again.')

    def create_playlist(self, title, items):
        """A new playlist with one chapter per item ({title, sha, duration, fileSize, channels, format}). Returns its card id."""
        chapters = []
        for i, it in enumerate(items, 1):
            name = (it['title'] or 'Track %d' % i)[:100]
            chapters.append({'key': '%02d' % i, 'title': name, 'overlayLabel': str(i), 'duration': it['duration'], 'fileSize': it['fileSize'], 'display': {},
                             'tracks': [{'key': '01', 'title': name, 'trackUrl': 'yoto:#' + it['sha'], 'duration': it['duration'], 'fileSize': it['fileSize'],
                                         'channels': it['channels'], 'format': it['format'], 'type': 'audio', 'overlayLabel': str(i)}]})
        secs, size = sum(i['duration'] for i in items), sum(i['fileSize'] for i in items)
        body = {'title': (title or 'MiniDisc')[:140], 'content': {'chapters': chapters},
                'metadata': {'media': {'duration': secs, 'fileSize': size, 'readableFileSize': round(size / 1e6, 1)}}}
        res = self._json('POST', '/content', body)
        return (res.get('card') or res).get('cardId')

    def append_to_playlist(self, card_id, items, backup_dir):
        """Adds the items ({title, sha, duration, fileSize, channels, format}) as new chapters at the END of one of the user's own playlists.
        Nothing else in the playlist is changed. A copy of the playlist is saved in backup_dir first; afterwards the playlist is read back and
        checked (every old chapter unchanged, in place, followed by the new ones), and if that fails the copy is written back. Returns
        {cardId, title, total (chapters now), backup (file)}."""
        card = self._get('/content/%s' % urllib.parse.quote(card_id, safe='')).get('card')
        if not card or not isinstance(card.get('content'), dict):
            raise YotoError('That playlist could not be read.')
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, '%s-%s.json' % (card_id, time.strftime('%Y%m%d-%H%M%S')))
        with open(backup, 'w', encoding='utf-8') as f:
            json.dump(card, f, indent=1)
        old = json.loads(json.dumps(card['content'].get('chapters') or []))
        used = {str(c.get('key')) for c in old}
        chapters = json.loads(json.dumps(old))
        n = len(old)
        for it in items:
            n += 1
            key = '%02d' % n
            while key in used:
                n += 1
                key = '%02d' % n
            used.add(key)
            name = (it['title'] or 'Track %d' % n)[:100]
            chapters.append({'key': key, 'title': name, 'overlayLabel': str(n), 'duration': it['duration'], 'fileSize': it['fileSize'], 'display': {},
                             'tracks': [{'key': '01', 'title': name, 'trackUrl': 'yoto:#' + it['sha'], 'duration': it['duration'], 'fileSize': it['fileSize'],
                                         'channels': it['channels'], 'format': it['format'], 'type': 'audio', 'overlayLabel': str(n)}]})
        content = dict(card['content'], chapters=chapters)
        media = dict((card.get('metadata') or {}).get('media') or {})
        secs = sum(c.get('duration') or 0 for c in chapters)
        size = sum(c.get('fileSize') or 0 for c in chapters)
        media.update(duration=secs, fileSize=size, readableFileSize=round(size / 1e6, 1))
        body = {'cardId': card_id, 'title': card.get('title'), 'content': content, 'metadata': dict(card.get('metadata') or {}, media=media)}
        self._json('POST', '/content', body)
        try:
            now = (self._get('/content/%s' % urllib.parse.quote(card_id, safe='')).get('card') or {}).get('content', {}).get('chapters') or []
            ok = len(now) == len(old) + len(items) and json.dumps(now[:len(old)], sort_keys=True) == json.dumps(old, sort_keys=True)
        except YotoError:
            ok = False
        if not ok:
            restore = {'cardId': card_id, 'title': card.get('title'), 'content': card['content'], 'metadata': card.get('metadata') or {}}
            try:
                self._json('POST', '/content', restore)
            except YotoError as exc:
                raise YotoError('The playlist did not look right after adding the tracks and could not be put back automatically (%s). '
                                'A copy of how it was is saved in %s' % (exc, backup))
            raise YotoError('The playlist did not look right after adding the tracks, so it was put back as it was. A copy is in %s' % backup)
        return {'cardId': card_id, 'title': card.get('title'), 'total': len(chapters), 'backup': backup}

    # -- fetching audio --------------------------------------------------------------------------
    @staticmethod
    def download(url, dest, progress=None, cancel=None):
        """Copies one signed audio URL to a file. Returns False if cancelled."""
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, 'wb') as f:
                total = int(r.headers.get('Content-Length') or 0)
                done = 0
                while True:
                    if cancel and cancel():
                        return False
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except (urllib.error.URLError, OSError, socket.timeout) as exc:
            raise YotoError('The audio could not be downloaded: %s' % getattr(exc, 'reason', exc))
        return True

    @staticmethod
    def to_wav(ffmpeg, src, dest):
        """Decodes what Yoto serves (Opus or AAC in an Ogg / MP4 / WebM container) to a 44.1 kHz stereo 16-bit WAV."""
        r = subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', src, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', dest],
                           capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode != 0 or not os.path.isfile(dest):
            raise YotoError('The downloaded audio could not be decoded: %s' % r.stderr.decode(errors='replace').strip()[-200:])

    @staticmethod
    def fetch_cover(url):
        if not url:
            return None
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30) as r:
                return r.read(20 * 1000 * 1000)
        except (urllib.error.URLError, OSError):
            return None


def _find(o, key):
    """The first non-empty value of `key` anywhere inside a nested answer."""
    if isinstance(o, dict):
        if o.get(key):
            return o[key]
        for v in o.values():
            r = _find(v, key)
            if r:
                return r
    return None


def _clean_title(title):
    """A track uploaded as 'D.I.L.F Act 1.wav' shows as 'D.I.L.F Act 1'."""
    low = title.lower()
    for ext in ('.wav', '.mp3', '.m4a', '.flac', '.ogg', '.opus', '.aac'):
        if low.endswith(ext):
            return title[:-len(ext)].strip()
    return title
