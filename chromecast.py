"""Minimal Google Cast sender (Google TV, Chromecast, Nest and other Cast speakers) over the local network. No third-party packages.

A Cast device listens on TCP port 8009 (TLS). Messages are a length-prefixed protobuf "CastMessage" carrying a JSON text. To play audio we
start the built-in Default Media Receiver app on the device and LOAD a web address into it; the device then fetches the audio itself,
exactly like the Sonos speakers do. Every call here opens its own short connection (no keep-alive needed), asks the device what it is
doing, sends one command and closes - the app's page polls every few seconds, so there is nothing to keep running between calls.
"""
import json
import random
import select
import socket
import ssl
import threading
import time
import urllib.request

PORT = 8009
DEFAULT_MEDIA_RECEIVER = 'CC1AD845'
NS_CONN = 'urn:x-cast:com.google.cast.tp.connection'
NS_HEART = 'urn:x-cast:com.google.cast.tp.heartbeat'
NS_RECV = 'urn:x-cast:com.google.cast.receiver'
NS_MEDIA = 'urn:x-cast:com.google.cast.media'


class CastError(Exception):
    pass


# ---- the little bit of protobuf the Cast message needs ---------------------------------------------------------------------------------------
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field_str(num, text):
    data = text.encode('utf-8')
    return _varint(num << 3 | 2) + _varint(len(data)) + data


def _encode(src, dst, namespace, text):
    # CastMessage: 1 protocol_version (0 = CASTV2_1_0), 2 source_id, 3 destination_id, 4 namespace, 5 payload_type (0 = string), 6 payload_utf8
    body = _varint(1 << 3) + _varint(0) + _field_str(2, src) + _field_str(3, dst) + _field_str(4, namespace) + _varint(5 << 3) + _varint(0) + _field_str(6, text)
    return len(body).to_bytes(4, 'big') + body


def _decode(body):
    fields, i = {}, 0
    while i < len(body):
        key, i = _read_varint(body, i)
        num, kind = key >> 3, key & 7
        if kind == 0:
            val, i = _read_varint(body, i)
        elif kind == 2:
            n, i = _read_varint(body, i)
            val = body[i:i + n]
            i += n
        else:
            raise CastError('Unexpected data from the device.')
        fields[num] = val
    return {'source': fields.get(2, b'').decode('utf-8', 'replace'), 'dest': fields.get(3, b'').decode('utf-8', 'replace'),
            'namespace': fields.get(4, b'').decode('utf-8', 'replace'), 'text': fields.get(6, b'').decode('utf-8', 'replace')}


def _read_varint(data, i):
    shift = n = 0
    while True:
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


# ---- one short connection --------------------------------------------------------------------------------------------------------------------
class _Conn:
    def __init__(self, ip, timeout=6):
        self.ip, self.req = ip, random.randint(1000, 900000)      # request numbers differ from one connection to the next: a "load cancelled" notice for an earlier
                                                                  # connection's request must not be taken for the answer to ours
        try:
            for attempt in range(4):                        # Windows now and then refuses a connection for a moment (WinError 10013: VPN adapters, firewall busy): try again shortly
                try:
                    raw = socket.create_connection((ip, PORT), timeout=timeout)
                    break
                except OSError as exc:
                    if attempt == 3 or getattr(exc, 'winerror', 0) != 10013:
                        raise
                    time.sleep(0.4 * (attempt + 1))
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE                 # Cast devices use their own certificates: there is nothing to check against
            self.sock = ctx.wrap_socket(raw)
            self.sock.settimeout(timeout)
        except (OSError, ssl.SSLError) as exc:
            raise CastError('Could not reach the device at %s (%s).' % (ip, exc))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, namespace, dest, payload):
        self.sock.sendall(_encode('sender-0', dest, namespace, json.dumps(payload)))

    def _recv_exact(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise CastError('The device closed the connection.')
            buf += chunk
        return buf

    def recv(self):
        msg = _decode(self._recv_exact(int.from_bytes(self._recv_exact(4), 'big')))
        try:
            msg['json'] = json.loads(msg['text']) if msg['text'] else {}
        except ValueError:
            msg['json'] = {}
        if msg['namespace'] == NS_HEART and msg['json'].get('type') == 'PING':
            self.send(NS_HEART, msg['source'], {'type': 'PONG'})
        return msg

    def connect(self, dest):
        self.send(NS_CONN, dest, {'type': 'CONNECT'})

    def ask(self, namespace, dest, payload, timeout=8, accept=None):
        """Sends a request and returns the first answer to it (matched by requestId, or by `accept(json)`)."""
        self.req += 1
        payload = dict(payload, requestId=self.req)
        self.send(namespace, dest, payload)
        end = time.time() + timeout
        last_ping = time.time()
        self.sock.settimeout(1.0)
        try:
            while time.time() < end:
                if time.time() - last_ping > 4:                              # keep the link alive while a slow TV starts its player
                    self.send(NS_HEART, 'receiver-0', {'type': 'PING'})
                    last_ping = time.time()
                try:
                    msg = self.recv()
                except socket.timeout:
                    continue
                j = msg['json']
                if accept:
                    if accept(j):                                           # waiting for a particular state, not just the first reply
                        return j
                elif j.get('requestId') == self.req:
                    return j
        finally:
            self.sock.settimeout(6)
        raise CastError('The device did not answer in time.')


_vol_lock = threading.Lock()          # one volume change at a time
_vol_conns = {}                       # ip -> (connection, time last used): kept briefly for the volume slider


# ---- one device ------------------------------------------------------------------------------------------------------------------------------
class Device:
    def __init__(self, ip):
        self.ip = ip

    def _open(self):
        c = _Conn(self.ip)
        c.connect('receiver-0')
        return c

    @staticmethod
    def _app(status):
        apps = (status or {}).get('applications') or []
        return next((a for a in apps if a.get('appId') == DEFAULT_MEDIA_RECEIVER), None)

    def _media_status(self, c, transport):
        j = c.ask(NS_MEDIA, transport, {'type': 'GET_STATUS'})
        items = j.get('status') or []
        return items[0] if items else None

    def _context(self, c):
        """(transportId, media status or None) for our Default Media Receiver session, or (None, None) when it is not running."""
        st = c.ask(NS_RECV, 'receiver-0', {'type': 'GET_STATUS'}).get('status')
        app = self._app(st)
        if not app:
            return None, None
        transport = app['transportId']
        c.connect(transport)
        return transport, self._media_status(c, transport)

    def _reset_player(self):
        """Quits the TV's media player app (a stuck one is the only cure) so that the next play starts a fresh one."""
        c = self._open()
        try:
            st = c.ask(NS_RECV, 'receiver-0', {'type': 'GET_STATUS'}).get('status')
            app = self._app(st)
            if app:
                c.send(NS_RECV, 'receiver-0', {'type': 'STOP', 'sessionId': app['sessionId'], 'requestId': 9001})
                time.sleep(2.5)
        finally:
            c.close()

    def play_url(self, url, title, mime, artist=None, album=None, video=False, source=None, _retry=True):
        """Starts the track on the TV and checks that it really is playing; a TV player that stays stuck on "buffering" at 0 seconds (it happens after a
        read was cancelled or a stream was replaced) is reset and tried once more."""
        c = self._open()
        stuck = False
        try:
            st = c.ask(NS_RECV, 'receiver-0', {'type': 'GET_STATUS'}).get('status')
            app = self._app(st)
            if not app:
                j = c.ask(NS_RECV, 'receiver-0', {'type': 'LAUNCH', 'appId': DEFAULT_MEDIA_RECEIVER}, timeout=15,
                          accept=lambda j: j.get('type') == 'LAUNCH_ERROR' or (j.get('type') == 'RECEIVER_STATUS' and self._app(j.get('status'))))
                if j.get('type') == 'LAUNCH_ERROR':
                    raise CastError('The device would not start its media player (%s).' % j.get('reason', 'unknown reason'))
                app = self._app(j.get('status'))
                if not app:
                    raise CastError('The device did not start its media player.')
            transport = app['transportId']
            c.connect(transport)
            # A "music track" makes the TV show only its audio screen, so a video (the lyric video) is announced as a generic one (0).
            meta = {'metadataType': 0 if video else 3, 'title': title or 'Track'}
            who = ' - '.join(x for x in (artist, album if video else None, source) if x)      # artist, album (video only: the music type has its own field), then the recorder
            if who:
                meta['subtitle' if video else 'artist'] = who
            if album and not video:
                meta['albumName'] = album
            media = {'contentId': url, 'contentType': mime, 'streamType': 'BUFFERED', 'metadata': meta}
            if video:
                media.update({'hlsSegmentFormat': 'ts', 'hlsVideoSegmentFormat': 'mpeg2_ts'})
            j = c.ask(NS_MEDIA, transport, {'type': 'LOAD', 'autoplay': True, 'currentTime': 0, 'media': media}, timeout=20)
            if j.get('type') in ('LOAD_FAILED', 'LOAD_CANCELLED', 'INVALID_REQUEST'):
                raise CastError('The device could not play that track (%s).' % j.get('reason', j.get('type')))
            end, playing = time.time() + 15, False
            while time.time() < end:                         # normally playing within a second or two (a lyric video can take a few seconds more)
                s = self._media_status(c, transport) or {}
                if s.get('playerState') == 'PLAYING' and (s.get('currentTime') or 0) > 0:
                    playing = True
                    break
                if s.get('playerState') == 'IDLE' and s.get('idleReason') in ('ERROR', 'INTERRUPTED', 'CANCELLED'):
                    break
                time.sleep(1.0)
            stuck = not playing
        finally:
            c.close()
        if stuck:
            if not _retry:
                raise CastError('The TV did not start playing. Switch it off and on again, then try again.')
            self._reset_player()
            self.play_url(url, title, mime, artist, album, video, source, _retry=False)

    def control(self, action, seconds=0):
        c = self._open()
        try:
            transport, media = self._context(c)
            if media is None:
                return
            sid = media['mediaSessionId']
            cmd = {'play': {'type': 'PLAY'}, 'pause': {'type': 'PAUSE'}, 'stop': {'type': 'STOP'},
                   'seek': {'type': 'SEEK', 'currentTime': max(0, int(seconds)), 'resumeState': 'PLAYBACK_START' if media.get('playerState') == 'PLAYING' else 'PLAYBACK_PAUSE'}}[action]
            c.ask(NS_MEDIA, transport, dict(cmd, mediaSessionId=sid))
        finally:
            c.close()

    def status(self):
        """{'state': playing|paused|ready, 'seconds', 'duration', 'uri'} - 'ready' means nothing is playing."""
        c = self._open()
        try:
            transport, media = self._context(c)
            if not media:
                return {'state': 'ready', 'seconds': 0, 'duration': 0, 'uri': ''}
            state = {'PLAYING': 'playing', 'BUFFERING': 'playing', 'PAUSED': 'paused'}.get(media.get('playerState'), 'ready')
            m = media.get('media') or {}
            return {'state': state, 'seconds': int(media.get('currentTime') or 0), 'duration': max(0, int(m.get('duration') or 0)), 'uri': m.get('contentId', '')}     # -1 = a stream still being made
        finally:
            c.close()

    def volume(self):
        c = self._open()
        try:
            vol = (c.ask(NS_RECV, 'receiver-0', {'type': 'GET_STATUS'}).get('status') or {}).get('volume') or {}
            return int(round(float(vol.get('level', 0)) * 100))
        finally:
            c.close()

    def set_volume(self, value):
        """Sets the volume (0-100). The TV applies it within about 50 ms but only acknowledges it after about a second, so the command is sent
        without waiting for that reply, and the connection is kept for a few seconds and reused: dragging a slider then follows at once instead
        of one step per second. (The TV rounds to its own steps, 1/60 on the Philips.)"""
        level = max(0, min(100, int(round(float(value))))) / 100.0
        with _vol_lock:
            for attempt in (0, 1):
                entry = _vol_conns.pop(self.ip, None)
                c = entry[0] if entry and time.time() - entry[1] < 4 else None      # an older one may have been dropped by the TV
                if entry and c is None:
                    entry[0].close()
                try:
                    if c is None:
                        c = self._open()
                    else:
                        while select.select([c.sock], [], [], 0)[0] or c.sock.pending():    # read what the TV sent meanwhile (acknowledgements, heartbeat pings)
                            c.recv()
                    c.send(NS_RECV, 'receiver-0', {'type': 'SET_VOLUME', 'volume': {'level': level}, 'requestId': 0})
                    _vol_conns[self.ip] = (c, time.time())
                    return
                except (CastError, OSError):
                    if c is not None:
                        c.close()
                    if attempt:
                        raise


# ---- finding devices -------------------------------------------------------------------------------------------------------------------------
def _private_subnets():
    from sonos import _local_addresses                      # the PC's own addresses (one per adapter)
    nets = []
    for ip in _local_addresses():
        p = [int(x) for x in ip.split('.')]
        if p[0] == 10 or (p[0] == 192 and p[1] == 168) or (p[0] == 172 and 16 <= p[1] <= 31):
            prefix = '.'.join(str(x) for x in p[:3])
            if prefix not in nets:
                nets.append(prefix)
    return nets


def friendly_name(ip):
    """The name the device shows (the TV's name), from its small information page; None if it does not have one."""
    try:
        with urllib.request.urlopen('http://%s:8008/setup/eureka_info?params=name' % ip, timeout=2) as r:
            return json.loads(r.read().decode('utf-8', 'replace')).get('name')
    except (OSError, ValueError):
        return None


def discover(timeout=0.6):
    """{ip: name} for every Cast device on this PC's network(s): the whole /24 is probed for the Cast port at the same time."""
    open_ips, lock, threads = [], threading.Lock(), []

    def probe(ip):
        try:
            with socket.create_connection((ip, PORT), timeout=timeout):
                with lock:
                    open_ips.append(ip)
        except OSError:
            pass

    for prefix in _private_subnets():
        for host in range(1, 255):
            th = threading.Thread(target=probe, args=('%s.%d' % (prefix, host),), daemon=True)
            th.start()
            threads.append(th)
    for th in threads:
        th.join(timeout + 2)
    found, names = {}, {}

    def name_it(ip):
        names[ip] = friendly_name(ip)

    ths = [threading.Thread(target=name_it, args=(ip,), daemon=True) for ip in open_ips]
    for th in ths:
        th.start()
    for th in ths:
        th.join(3)
    for ip in sorted(open_ips, key=lambda s: [int(x) for x in s.split('.')]):
        found[ip] = names.get(ip) or 'Cast device %s' % ip
    return found
