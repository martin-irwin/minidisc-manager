"""Playing the disc's tracks to a Sonos room: finding the speakers, sending a track to one, and the play / pause / seek / volume controls.
CastMixin is mixed into himd_app.Api (the page calls these methods on it). It uses the Api's play_prepare(), _streams, _tracks and log()."""
import http.server
import json
import os
import threading
import time

import base64
import shutil

import chromecast
import lyricvideo
import mediaserver
import sonos
from mdm_paths import FFMPEG
from mdm_platform import data_root
from mdm_paths import HERE, PLAY_DIR


class CastMixin:
    def _cast_init(self):
        self._cast_server = None       # a second media server, on this PC's network address, while a Sonos room is being played to
        self._cast_ip = None
        self._cast_port = 0
        self._cast_known = {}          # Sonos speakers found by the last search
        self._cast_last = None         # {'ip', 'prefix'}: the room this app last sent music to, and the start of our addresses
        self._cast_seq = 0
        self._lv = None                # the lyric video being made for a Google TV: {'id', 'job', 'start', 'ctx'}
        self._lv_base = 0.0            # seconds into the track the TV's current video starts at (0 unless it was remade mid-track)
        self._cast_video = True        # Google TVs get a lyric video (cover, title, timed lyrics) instead of just the audio
        self._recorder_name = ''     # the connected recorder's model (e.g. MZ-RH1), set when a disc loads
        self._cover_url = None         # the disc's picture as a data: address (set when a Hi-MD disc loads)
        self._cast_tvs = None          # {ip: name} of Google Cast devices (Google TV, Chromecast, Nest) found so far; None = not loaded yet

    # Google Cast devices (a Google TV such as the Philips OLED) are listed next to the Sonos rooms. They are told to play the same web
    # address a Sonos room would be given; see chromecast.py. Their addresses are remembered in chromecast.json so the list is instant.
    _CAST_CACHE = os.path.join(data_root(HERE), 'MiniDiscManager', 'chromecast.json')

    def _cast_devices(self, refresh=False):
        if self._cast_tvs is None:
            try:
                with open(self._CAST_CACHE, encoding='utf-8') as f:
                    self._cast_tvs = dict(json.load(f))
            except (OSError, ValueError):
                self._cast_tvs = {}
        if refresh:
            try:
                found = chromecast.discover()
            except OSError:
                found = {}
            if found:
                self._cast_tvs = found
                try:
                    os.makedirs(os.path.dirname(self._CAST_CACHE), exist_ok=True)
                    with open(self._CAST_CACHE, 'w', encoding='utf-8') as f:
                        json.dump(found, f)
                except OSError:
                    pass
        return [{'name': name if name.startswith('Cast device') else '%s (Cast)' % name, 'ip': ip, 'kind': 'cast'} for ip, name in self._cast_tvs.items()]

    def cast_options(self, video=None):
        """The Play on sheet's switch: should a Google TV get the lyric video (True) or just the audio (False)?"""
        if video is not None:
            self._cast_video = bool(video)
        return {'video': self._cast_video}

    def cast_viz(self, style=None, color=None, gain=1, apply=False, peaks=True, accent=None):
        """The visualizer the user has picked in the window. The next lyric video for a Google TV draws it; with apply=True a lyric video that is
        playing now is remade from the current position (a short pause on the TV)."""
        self._cast_viz = {'style': str(style or 'off'), 'color': str(color or 'accent'), 'gain': float(gain or 1), 'peaks': bool(peaks),
                          'accent': str(accent or '#7aa2ff')}
        return self._lv_restart() if apply else {'ok': True}

    def _lv_stop(self):
        lv, self._lv = self._lv, None
        self._lv_base = 0.0
        if lv:
            lv['job'].stop()
            shutil.rmtree(lv['job'].dir, ignore_errors=True)

    def _lv_restart(self, at=None):
        """Remakes the TV's lyric video from where it is now (or from `at` seconds into the track) with the current visualizer, and tells the TV to
        play the new one. The TV counts the new stream from 0, so _lv_base keeps the track position (status adds it back)."""
        lock = self.__dict__.setdefault('_lv_lock', threading.Lock())
        with lock:
            old = self._lv
            if not old or not old.get('ctx') or not self._cast_video:
                return {'ok': True, 'restarted': False}
            c, seq = old['ctx'], self._cast_seq
            try:
                dev = chromecast.Device(c['ip'])
                st = dev.status()
                if st['state'] == 'ready':
                    return {'ok': True, 'restarted': False}                          # nothing is playing on the TV
                pos = float(at) if at is not None else self._lv_base + st['seconds']
                t0 = time.time()
                url = self._lyric_video(c['stream'], c['track'], c['lan'], c['ip'], start=pos)      # replaces self._lv; on failure it stops the new one
                if not url:
                    self._lv, self._lv_base = old, (old.get('start') or 0.0)        # the old one keeps playing (the failed attempt reset the base)
                    return {'ok': True, 'restarted': False}
                new = self._lv
                if seq != self._cast_seq:                                            # another track was started meanwhile: this one is out of date
                    new['job'].stop(); shutil.rmtree(new['job'].dir, ignore_errors=True); self._lv = None
                    return {'ok': True, 'restarted': False}
                self._lv_base = pos
                try:
                    dev.play_url(url, c['track'].get('title'), 'application/x-mpegurl', c['track'].get('artist'), c['track'].get('album'), video=True,
                                 source=self._recorder_name or None)
                except chromecast.CastError:
                    self._lv, self._lv_base = old, (old.get('start') or 0.0)
                    new['job'].stop(); shutil.rmtree(new['job'].dir, ignore_errors=True)
                    raise
                if st['state'] == 'paused':
                    dev.control('pause')
                old['job'].stop(); shutil.rmtree(old['job'].dir, ignore_errors=True)
                self.log('cast: lyric video remade from %.0fs with the new visualizer in %.1fs' % (pos, time.time() - t0))
                return {'ok': True, 'restarted': True}
            except (chromecast.CastError, OSError) as exc:
                return {'error': str(exc)}

    def _caption(self):
        """The small line at the bottom of the TV picture: the recorder and the kind of disc, e.g. 'MZ-NH700 - Playing an SP disc'."""
        name = self._recorder_name or ''
        try:
            if getattr(self, '_loaded_netmd', False):             # a standard MiniDisc: SP, LP2 or LP4 (a disc can mix them)
                modes = sorted({str(t.get('codec', '')).replace(' mono', '') for t in (self._tracks or []) if t.get('codec')} & {'SP', 'LP2', 'LP4'})
                if len(modes) == 1:
                    what = 'Playing an %s disc' % modes[0]                 # "an SP", "an LP2", "an LP4"
                else:
                    what = 'Playing a standard MiniDisc' + (' (%s)' % ' / '.join(modes) if modes else '')
            else:
                what = 'Playing a Hi-MD disc'
        except (AttributeError, TypeError):
            return name
        return (name + '  ·  ' if name else '') + what

    def _lyric_video(self, stream, track, lan, ip=None, start=0.0):
        """Starts making the lyric video for `track` (its audio is the file of `stream`) and returns the address the TV should play, or None.
        start: seconds into the track the video begins at (a remake after the visualizer was changed)."""
        try:
            if not stream or not os.path.exists(stream['path']):
                return None
            ly = self.lyrics_get(track.get('number')) if track.get('number') else {'none': True}
            lines = [(s, x) for s, x in ly.get('lines', []) if s is not None] if ly.get('synced') else []
            cover = None
            if getattr(self, '_loaded_netmd', False):                               # standard disc: the album art found online and kept on this PC (disc_lookup.py)
                import disc_lookup
                cover = disc_lookup.cover_bytes(self._netmd_disc_key(self._tracks))
            else:                                                                   # the picture of the track's group, else the disc's own picture
                url = self._ga_for_track(track.get('number')) or self._cover_url
                if url and url.startswith('data:'):
                    cover = base64.b64decode(url.split(',', 1)[1])
            import lyrics
            title, artist = lyrics._split_title(track)                              # "ARTIST - TITLE" titles of commercial discs: the artist is shown once
            vid = '%d' % int(time.time() * 1000)
            num, tracks = track.get('number'), self._tracks or []                   # the deck's track number / time display on the TV picture
            deck = {'pos': sum(1 for t in tracks if t['number'] <= num), 'count': len(tracks), 'length': float(track.get('seconds') or 0)} if num is not None and tracks else None
            job = lyricvideo.Job(FFMPEG, stream['path'], os.path.join(PLAY_DIR, 'lyricvideo-' + vid),
                                 title or 'Track', artist or '', lines, float(ly.get('offset') or 0), float(track.get('seconds') or 0),
                                 cover, self.log, growing=not stream.get('done'), caption=self._caption(), album=track.get('album') or '',
                                 viz=getattr(self, '_cast_viz', None), start=start, deck=deck)
            self._lv = {'id': vid, 'job': job, 'start': start, 'ctx': {'stream': stream, 'track': track, 'lan': lan, 'ip': ip}}
            if not job.wait_ready():
                self.log('lyric video: not ready (%s); playing the audio only' % (job.error or 'timed out'))
                self._lv_stop()
                return None
            return 'http://%s:%d/%s/lv/%s/index.m3u8' % (lan, self._cast_port, self._token, vid)
        except (OSError, ValueError) as exc:
            self.log('lyric video failed: %s' % exc)
            self._lv_stop()
            return None

    def _is_cast_device(self, ip):
        self._cast_devices()
        return ip in self._cast_tvs

    def _cast_to_device(self, action, device_index, track_index, seconds, ip):
        """Same contract as cast(), for a Google Cast device."""
        try:
            dev = chromecast.Device(ip)
            viz_url = None
            if action == 'play':
                self._cast_seq += 1
                mine, t0 = self._cast_seq, time.time()
                r = self.play_prepare(int(device_index), int(track_index) + 1)
                if r.get('superseded') or mine != self._cast_seq:
                    return {'superseded': True}
                if 'error' in r:
                    return r
                viz_url = r.get('url')                                              # the window runs a silent copy of this track so its visualizer keeps moving
                t1 = time.time()
                lan = sonos.local_ip_towards(ip)
                self._ensure_cast_server(lan)
                path = r['url'].split('//', 1)[1].split('/', 1)[1]
                name = path.rsplit('/', 1)[-1]
                st = next((s for s in self._streams.values() if s['name'] == name), None)
                track = dict(next((t for t in self._tracks if t['number'] == int(track_index) + 1), None) or {})
                if getattr(self, '_loaded_netmd', False):                           # standard disc: no artist / album stored, so use what the disc is called
                    dt = getattr(self, '_netmd_disc_title', '') or track.get('group') or ''
                    if dt and not track.get('album'):
                        track['album'] = dt
                url, mime = 'http://%s:%d/%s' % (lan, self._cast_port, path), st['mime'] if st else 'audio/wav'
                self._lv_stop()
                if self._cast_video:
                    vurl = self._lyric_video(st, track, lan, ip)               # None when it could not be made: the TV then just gets the audio
                    if vurl:
                        url, mime = vurl, 'application/x-mpegurl'
                video = mime.startswith('application/x-mpegurl')
                dev.play_url(url, track.get('title'), mime, track.get('artist'), track.get('album'), video=video,
                             source=self._recorder_name or None)
                self._cast_last = {'ip': ip, 'prefix': 'http://%s:%d/' % (lan, self._cast_port), 'cast': True}
                self.log('cast (Google Cast) play track %d (%s): track ready after %.1fs, device told in %.1fs' % (
                    int(track_index) + 1, 'lyric video' if mime.startswith('application/x-mpegurl') else 'audio only', t1 - t0, time.time() - t1))
            elif action in ('pause', 'resume', 'stop', 'seek'):
                if action == 'stop':
                    self._lv_stop()
                base = getattr(self, '_lv_base', 0.0)
                if action == 'seek' and base and float(seconds) < base:             # before where the remade video starts: remake it from there
                    r = self._lv_restart(at=float(seconds))
                    if 'error' in r:
                        return r
                else:
                    dev.control({'resume': 'play'}.get(action, action), max(0, float(seconds) - base) if action == 'seek' else seconds)
            elif action != 'status':
                return {'error': 'Unknown action: %s' % action}
            st = dev.status()
            base = getattr(self, '_lv_base', 0.0)                                    # the TV counts a remade video from 0; the page counts the track
            out = {'result': {'state': st['state'], 'track': int(track_index), 'seconds': st['seconds'] + int(base) if st['state'] != 'ready' else 0,
                              'duration': st['duration'] + int(base) if st['duration'] > 0 else st['duration']}}
            if viz_url:
                out['viz_url'] = viz_url
            return out
        except (chromecast.CastError, OSError) as exc:
            return {'error': str(exc)}

    # The speaker fetches the track itself from a small web server on this PC (the same files the window plays, behind the same
    # secret in the address). The page controls it like the NetMD remote: play, pause, seek, position, volume.
    _SONOS_CACHE = os.path.join(data_root(HERE), 'MiniDiscManager', 'sonos.json')

    def _remembered_speakers(self):
        if not self._cast_known:
            try:
                with open(self._SONOS_CACHE, encoding='utf-8') as f:
                    self._cast_known = {ip: None for ip in json.load(f)}
            except (OSError, ValueError):
                pass
        return self._cast_known

    def cast_rooms(self, refresh=True):
        """The Sonos rooms. refresh=False asks speakers found last time (instant); refresh=True searches the network (a few seconds)."""
        devices = self._cast_devices(refresh)
        try:
            rooms = []
            if not refresh:
                known = self._remembered_speakers()
                rooms = sonos.rooms(known) if known else []
                return {'rooms': [{'name': r['name'], 'ip': r['ip']} for r in rooms] + devices, 'cached': True}
            found = sonos.discover()
            if found:
                self._cast_known = found
                try:
                    os.makedirs(os.path.dirname(self._SONOS_CACHE), exist_ok=True)
                    with open(self._SONOS_CACHE, 'w', encoding='utf-8') as f:
                        json.dump(sorted(found), f)
                except OSError:
                    pass                                          # only means the next list is not instant
            rooms = sonos.rooms(found)
        except (sonos.SonosError, OSError) as exc:
            if devices:
                return {'rooms': devices}                         # no Sonos answered, but a TV or Cast speaker did
            return {'error': 'Could not search for Sonos speakers: %s' % exc}
        allrooms = [{'name': r['name'], 'ip': r['ip']} for r in rooms] + devices
        if not allrooms:
            return {'rooms': [], 'note': 'No Sonos speakers or Google TV / Chromecast devices answered. They must be on the same network as this PC, and Windows Firewall must allow this app on private networks.'}
        return {'rooms': allrooms}

    def _ensure_cast_server(self, lan_ip):
        if self._cast_server is not None and self._cast_ip == lan_ip:
            return
        if self._cast_server is not None:
            self._cast_server.shutdown()
            self._cast_server.server_close()
        self._cast_server = http.server.ThreadingHTTPServer((lan_ip, 0), mediaserver.media_handler(self))
        self._cast_server.daemon_threads = True
        self._cast_ip, self._cast_port = lan_ip, self._cast_server.server_address[1]
        threading.Thread(target=self._cast_server.serve_forever, daemon=True).start()

    def cast(self, action, device_index, track_index, seconds, ip):
        """Controls the Sonos room whose coordinator is at `ip`. Answers like remote(): {'result': {state, track, seconds}}."""
        if self._is_cast_device(ip):
            return self._cast_to_device(action, device_index, track_index, seconds, ip)
        try:
            sp = sonos.Speaker(ip)
            if action == 'play':
                self._cast_seq += 1
                mine, t0 = self._cast_seq, time.time()
                r = self.play_prepare(int(device_index), int(track_index) + 1)           # starts reading the track, gives its local address
                if r.get('superseded') or mine != self._cast_seq:
                    return {'superseded': True}                                       # the user already chose another track
                if 'error' in r:
                    return r
                t1 = time.time()
                lan = sonos.local_ip_towards(ip)
                self._ensure_cast_server(lan)
                path = r['url'].split('//', 1)[1].split('/', 1)[1]
                name = path.rsplit('/', 1)[-1]
                st = next((s for s in self._streams.values() if s['name'] == name), None)
                track = next((t for t in self._tracks if t['number'] == int(track_index) + 1), None)
                sp.play_url('http://%s:%d/%s' % (lan, self._cast_port, path), (track or {}).get('title'), st['mime'] if st else 'audio/wav')
                self._cast_last = {'ip': ip, 'prefix': 'http://%s:%d/' % (lan, self._cast_port)}
                t2 = time.time()
                for _ in range(10):                            # the speaker says "stopped" for a moment before it starts to fetch
                    if sp.status()['state'] != 'ready':
                        break
                    time.sleep(0.4)
                self.log('cast play track %d: track ready after %.1fs, speaker told in %.1fs, speaker started %.1fs later' % (int(track_index) + 1, t1 - t0, t2 - t1, time.time() - t2))
            elif action == 'pause':
                sp.pause()
            elif action == 'resume':
                sp.play()
            elif action == 'stop':
                sp.stop()
            elif action == 'seek':
                sp.seek(seconds)
            elif action != 'status':
                return {'error': 'Unknown action: %s' % action}
            st = sp.status()
            return {'result': {'state': st['state'], 'track': int(track_index), 'seconds': st['seconds'], 'duration': st['duration']}}
        except sonos.SonosError as exc:
            return {'error': str(exc)}

    def stop_cast(self):
        """Stops the room this app was playing to - but only if it is still playing one of our tracks, never something else."""
        last = self._cast_last
        self._lv_stop()
        if not last:
            return False
        try:
            if last.get('cast'):
                dev = chromecast.Device(last['ip'])
                st = dev.status()
                if st['uri'].startswith(last['prefix']) and st['state'] != 'ready':
                    dev.control('stop')
                    return True
                return False
            sp = sonos.Speaker(last['ip'])
            if sp.current_uri().startswith(last['prefix']) and sp.status()['state'] != 'ready':
                sp.stop()
                return True
        except (sonos.SonosError, chromecast.CastError, OSError):
            pass                                                # the speaker is gone: nothing to stop
        finally:
            self._cast_last = None
        return False

    def cast_volume(self, ip, value=None):
        try:
            sp = chromecast.Device(ip) if self._is_cast_device(ip) else sonos.Speaker(ip)
            if value is not None:
                sp.set_volume(value)
                return {'volume': max(0, min(100, int(round(float(value)))))}      # no read-back: it cost a second round trip per step
            return {'volume': sp.volume()}
        except (sonos.SonosError, chromecast.CastError, OSError) as exc:
            return {'error': str(exc)}
