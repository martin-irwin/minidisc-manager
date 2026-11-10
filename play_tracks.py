"""Playing a track from the disc in the window: the helper reads it into a temporary file while a small local server hands the growing file
to the page's audio player; plus the recorder's own remote control (standard discs). PlayMixin is mixed into himd_app.Api, which creates the
state used here (_streams, _cache, _active, _thread, _lock, _play_mutex ...) in __init__. Reads only; nothing is written to the disc."""
import hashlib
import http.server
import json
import os
import threading
import time

import mediaserver
from mdm_paths import COPIES_DIR, NETMD_HELPER, PLAY_DIR


class PlayMixin:
    # The helper reads the track from the disc into a temp file (PCM is decrypted with the key on the disc,
    # nothing is written to the recorder). A small local server hands the growing file to the page's <audio>.
    def _ensure_server(self):
        if self._server is None:
            self._server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), mediaserver.media_handler(self))
            self._server.daemon_threads = True
            self._port = self._server.server_address[1]
            threading.Thread(target=self._server.serve_forever, daemon=True).start()

    # Read-ahead (standard discs): once the track that is playing has been read from the recorder, the next tracks (up to _ra_depth of them) are read
    # into temporary files while it plays, and the last _ra_behind tracks played are kept, so "next", "previous" and the automatic advance start at once
    # instead of after the recorder's ~22 s start-up. It uses the same lock as everything else, and anything else that wants the recorder (or a play
    # request for a track that is not ready) cancels it first. Moving to a track that is ready does NOT cancel the reading that is going on.
    _ra_lock = threading.Lock()             # makes "has anything cancelled the reads?" and "start a read-ahead" one step
    _cancel_epoch = 0                       # counts cancellations: a read started under an older count must not chain a read-ahead
    _readahead_on = True
    _ra_depth = 3                           # how many tracks after the playing one are read ahead
    _ra_behind = 2                          # how many tracks before it stay ready (going back)
    _ra_cap = 700 * 1024 * 1024             # stop reading ahead when the ready tracks around the playing one are this big
    _ra_base = 0                            # the number of the track that is playing (or was asked for last)

    # Fast start (MZ-NH700 and other Hi-MD recorders read with the firmware patch): the library sleeps a fixed 20 s after seeking to the track, which is
    # nearly all of the 22.6 s start-up. Measured on an NH700 (reads compared byte for byte with the normal 20 s read): after a read that finished
    # cleanly, 10 / 12 / 16 s gave identical audio for the next track, 8 s or less left a few 23 ms glitches, and 4 s failed after a long jump. So 12 s
    # is used when the drive is known to be settled after a finished read, and the library's own 20 s whenever its state is uncertain (first read, a
    # read that was cancelled or failed, any other use of the recorder). Only playing uses this; Save, Clone, Identify and Split keep the full wait.
    _fast_start_on = True
    _fast_wait_ms = 12000
    _drive_ok = None                        # (disc signature, track number) of the last read that finished cleanly, or None when the drive state is unknown

    def play_fast_start(self, enabled=None):
        """Switches the shorter start-up wait on or off (on by default); returns the setting."""
        if enabled is not None:
            self._fast_start_on = bool(enabled)
        return {'fastStart': self._fast_start_on}

    def _drive_touched(self):
        """Something else used the recorder: where the drive is parked is unknown now."""
        self._drive_ok = None

    def _spin_args(self, args, sig):
        """Adds the seek wait to a read's arguments when the drive is known to be settled (see above); otherwise leaves the library's 20 s."""
        if self._fast_start_on and self._drive_ok is not None and self._drive_ok[0] == sig:
            args['spinWait'] = self._fast_wait_ms
        return args

    def _ra_cached(self, number_lo, number_hi):
        """The finished read-ahead / played reads of this disc with a track number in [number_lo, number_hi] whose files are complete."""
        out = []
        for st in list(self._cache.values()):
            n = st.get('number')
            if n is None or st.get('sig') != self._netmd_sig or not (number_lo <= n <= number_hi):
                continue
            try:
                if st['done'] and os.path.getsize(st['path']) == st['total']:
                    out.append(st)
            except OSError:
                pass
        return out

    def _ra_keep(self, number):
        """File names to keep in the temporary folder while `number` is the track being played: the ones around it, and the read in progress."""
        keep = {st['name'] for st in self._ra_cached(number - self._ra_behind, number + self._ra_depth)}
        if self._active is not None and self._active.get('name'):
            keep.add(self._active['name'])
        return keep

    def play_readahead(self, enabled=None):
        """Switches the read-ahead of the next track on or off (on by default); returns the setting."""
        if enabled is not None:
            self._readahead_on = bool(enabled)
        return {'readahead': self._readahead_on}

    def _cancel_extract(self):
        with self._ra_lock:
            self._cancel_epoch += 1
            t, st, proc = self._thread, self._active, self._proc
        if t is None or not t.is_alive() or st is None:
            return
        self._drive_ok = None                   # a read stopped half way: the drive is somewhere in the middle of a track
        st['cancelled'] = True
        try:
            proc.stdin.write('stop\n')          # the helper stops between blocks and closes the disc cleanly
            proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass
        t.join(40)
        if t.is_alive():
            try:
                proc.terminate()
            except OSError:
                pass
            t.join(10)
        self._last_cancel = time.time()

    _last_cancel = 0.0

    def _settle_drive(self, seconds=12):
        """After a read was stopped half way the drive is parked in the middle of a track. A write that starts at once (the copy-protection
        sign-in of a delete) can stall it for good, so wait until `seconds` have passed since that stop."""
        wait = self._last_cancel + seconds - time.time()
        if wait > 0:
            self.log('waiting %.1f s for the drive to settle before writing' % wait)
            time.sleep(wait)

    def _drop_cache(self):
        """Forget finished tracks; adding or deleting tracks changes the audio file's layout."""
        self._cache.clear()
        for name in list(self._streams):
            if self._streams[name]['done']:
                del self._streams[name]
        self._clean_play_dir()

    def _clean_play_dir(self, keep=None):
        if not os.path.isdir(PLAY_DIR):
            return
        keep = {keep} if isinstance(keep, str) else set(keep or ())
        for f in os.listdir(PLAY_DIR):
            if f not in keep:
                try:
                    os.remove(os.path.join(PLAY_DIR, f))
                except OSError:
                    pass                           # still being served; it goes at the next clean-up

    def _extract(self, st, args, started):
        """Reads the track of `st`; when that has finished (and nothing has cancelled it) goes on to read the next tracks ahead, one after the other,
        in this same thread (until _ra_depth tracks after the playing one are ready)."""
        while st is not None:
            self._extract_one(st, args, started)
            nxt = self._readahead_next(st) if (st['done'] and not st['failed'] and not st['cancelled']) else None
            if nxt is None:
                break
            st, args, started = nxt

    def _stream_for(self, number, track, patch, netmd, disc_key, index):
        """(key, name, state) for reading this track; the state is not registered anywhere yet."""
        fmt = 'wav'                                            # ATRAC and MP3 are decoded to WAV as they are read, so playback starts at once
        key = hashlib.sha1(('%s|%d|%d|%d|%s' % (disc_key, number, track['blocks'], track['seconds'], 'x' if patch else '')).encode()).hexdigest()[:16]
        name = '%s.%s' % (key, fmt)
        st = {'key': key, 'name': name, 'format': fmt, 'path': os.path.join(PLAY_DIR, name), 'total': 0,
              'mime': 'audio/wav' if fmt == 'wav' else 'audio/mpeg', 'done': False, 'failed': False,
              'cancelled': False, 'announced': False, 'error': '',
              'cmd': ('fetch_stream' if patch else 'fetch') if netmd else 'dump', 'helper': NETMD_HELPER if netmd else None,
              'number': number, 'sig': disc_key, 'index': index, 'ahead': False, 'ev': threading.Event(), 'epoch': 0, 'patch': patch}
        return key, name, st

    def _readahead_next(self, st):
        """The next track's (state, args, started event) to read ahead, registered as the active read, or None when there is nothing to do or anything
        has asked for the recorder since `st` was started."""
        try:
            if not (self._readahead_on and self._loaded_netmd) or st.get('number') is None or st.get('sig') != self._netmd_sig:
                return None
            for _ in range(8):                                 # let the drive settle after the last read, but give up at once if cancelled
                time.sleep(0.25)
                if self._cancel_epoch != st['epoch']:
                    return None
            index, base = st['index'], self._ra_base
            if sum(s['total'] for s in self._ra_cached(base - self._ra_behind, base + self._ra_depth)) >= self._ra_cap:
                return None                                    # enough is ready already (very long tracks)
            can = self._can_fetch(index)
            patch = bool(not can and self._exploit_possible(index))
            if not can and not patch:
                return None
            # the next track first, then the one before (going back), then further ahead, then further back
            order = [base + 1, base - 1] + [base + k for k in range(2, self._ra_depth + 1)] + [base - k for k in range(2, self._ra_behind + 1)]
            for n in order:
                track = next((t for t in self._tracks if t['number'] == n), None)
                if track is None:
                    continue                                   # before the first track or after the last
                if self._find_copy(track['title'], track['seconds'], codec=track['codec']):
                    continue                                   # the app has its own copy: instant already
                key, name, ra = self._stream_for(n, track, patch, True, st['sig'], index)
                cached = self._cache.get(key)
                if cached and os.path.exists(cached['path']) and os.path.getsize(cached['path']) == cached['total']:
                    continue                                   # already read
                with self._ra_lock:
                    if self._cancel_epoch != st['epoch'] or self._active is not st:
                        return None                            # something asked for the recorder in the meantime
                    ra['epoch'], ra['ahead'] = self._cancel_epoch, True
                    self._cache.pop(key, None)
                    self._streams[name] = ra
                    self._active = ra
                args = {'index': n - 1, 'out': ra['path']}     # the helper counts tracks from 0
                if patch:
                    args['seconds'] = track['seconds']
                    self._spin_args(args, st['sig'])
                self.log('read-ahead: track %d (playing %d)' % (n, base))
                return ra, args, ra['ev']
            return None
        except Exception as exc:                               # a convenience: never let it disturb playing
            self.log('read-ahead skipped: %s' % exc)
            return None

    def _readahead_kick(self, st, index):
        """Starts the read-ahead of the track after `st` when `st` is playing from the cache (no read of its own is running to continue from)."""
        if not (self._readahead_on and self._loaded_netmd):
            return
        with self._ra_lock:
            st['epoch'], st['index'], st['sig'] = self._cancel_epoch, index, self._netmd_sig
            self._active = st                                  # the "current" read, already finished: the read-ahead continues from it

        def chain():
            nxt = self._readahead_next(st)
            if nxt is not None:
                self._extract(*nxt)
        t = threading.Thread(target=chain, daemon=True)
        with self._ra_lock:
            self._thread = t
        t.start()

    def _extract_one(self, st, args, started):
        t_begin = time.time()

        def on_event(msg):
            if msg.get('event') == 'log':                      # the helper's own timing marks: where the start-up time of a read goes
                self.log('helper track %s: %s (%s ms)' % (st.get('number'), msg.get('text'), msg.get('ms')))
            elif msg.get('event') == 'start' and not st['cancelled']:
                st['total'] = msg['totalBytes']
                started.set()
                self.log('helper track %s: audio started after %.1f s' % (st.get('number'), time.time() - t_begin))
        try:
            with self._lock.raw:
                res = self._run_helper(st.get('cmd', 'dump'), args, on_event, helper=st.get('helper'))
        except Exception as exc:
            res = {'error': str(exc)}
        if 'error' in res:
            # A failed read leaves the drive state unknown. A read the helper stopped itself on request ("stopped": it closes the disc
            # cleanly between blocks) is fine: tested on the NH700, a read after such a cancel is identical with the 12 s wait.
            if st['cancelled'] and str(res['error']).strip().lower() == 'stopped' and st.get('cmd') == 'fetch_stream':
                self._drive_ok = (st.get('sig'), st.get('number'))
            else:
                self._drive_ok = None
            st['failed'] = True
            err = str(res['error'])
            if st.get('cmd') == 'fetch' and 'rejected' in err.lower():   # the recorder's own refusal to send this track back (a hex string)
                err = ('This recorder won’t send this track back to the PC. Even the MZ-RH1 only does that for tracks it considers its own, '
                       'not ones copied in from SonicStage or another deck. Try the disc in an MZ-NH700 (the app can read it there), '
                       'or use the remote control to play it on the recorder. (Recorder reply: %s)' % err[:60])
            st['error'] = ('Playback stopped because the recorder was needed for something else. Press play to read it again.'
                           if st['cancelled'] else err)
            self.log('read of %s failed: %s (cancelled=%s, announced=%s, current=%s)' % (st['name'], str(res['error'])[:200], st['cancelled'], st['announced'], self._active is st))
        else:
            st['total'] = res['result']['bytes']
            st['done'] = True
            self._cache[st['key']] = st
            if st.get('cmd') == 'fetch_stream':                # a read that finished cleanly leaves the drive settled
                self._drive_ok = (st.get('sig'), st.get('number'))
        started.set()
        # Only the track that is playing now may report an interruption. Clicking another track ends the previous read with an
        # "interrupted" result; applying that to the new track marked it broken and made the pause button restart it.
        if st['failed'] and st['announced'] and self._window and self._active is st:
            try:
                self._window.evaluate_js('window.onPlayInterrupted && window.onPlayInterrupted(%s)' % json.dumps(st['error']))
            except Exception:
                pass

    def _play_reply(self, st):
        return {'url': 'http://127.0.0.1:%d/%s/%s' % (self._port, self._token, st['name']), 'format': st['format']}

    def play_prepare(self, index, number):
        """Starts reading a track from the disc and returns a URL the page can play. Reads only."""
        netmd = self._is_netmd(index)
        self._play_seq += 1
        mine = self._play_seq                                  # a newer request replaces this one
        with self._play_mutex:
            if mine != self._play_seq:
                return {'superseded': True}                    # already replaced while waiting for its turn
            return self._play_prepare_locked(index, number, netmd, mine)

    def _adopt_readahead(self, ra, mine):
        """The track asked for is the one being read ahead right now: carry on with that read instead of cancelling it and starting again."""
        ra['ahead'], ra['announced'] = False, False
        self._ra_base = ra['number']                           # the reading goes on from here: the tracks after this one next
        self._play_mutex.release()                             # let a newer request in while this one waits for the read to start
        try:
            ready = ra['ev'].wait(300)
        finally:
            self._play_mutex.acquire()
        if mine != self._play_seq:
            return {'superseded': True}
        if not ready:
            self._cancel_extract()
            return {'error': 'The recorder did not respond in time.'}
        if ra['failed']:
            return {'error': ra['error']}
        ra['announced'] = True
        return self._play_reply(ra)

    def _quick_play(self, index, number, mine):
        """Standard discs: a track that is already read, or is being read ahead right now, is played WITHOUT cancelling the reading that is going on
        (so moving on or back through tracks that are ready never throws away work). Returns the reply, or None when the normal path must be taken."""
        track = next((t for t in self._tracks if t['number'] == number), None)
        if track is None or not self._netmd_sig or self._find_copy(track['title'], track['seconds'], codec=track['codec']):
            return None
        can = self._can_fetch(index)
        patch = bool(not can and self._exploit_possible(index))
        if not can and not patch:
            return None
        key, name, _st = self._stream_for(number, track, patch, True, self._netmd_sig, int(index))
        active = self._active
        cached = self._cache.get(key)
        if cached and os.path.exists(cached['path']) and os.path.getsize(cached['path']) == cached['total']:
            alive = self._thread is not None and self._thread.is_alive()
            if alive and active is not None and not active['done'] and not active['failed'] and not active.get('ahead'):
                return None                                    # a read of the track that was playing is still running: the normal path stops it
            self._ra_base = number
            self._streams[name] = cached
            self._ensure_server()
            self._clean_play_dir(keep=self._ra_keep(number) | {name})
            if not alive:
                self._readahead_kick(cached, int(index))       # nothing is reading: start reading the tracks after this one
            return self._play_reply(cached)
        if (active is not None and active.get('ahead') and active.get('number') == number and active.get('sig') == self._netmd_sig and active.get('index') == int(index)
                and not active['failed'] and not active['cancelled'] and not active['done']):
            self.log('read-ahead adopted: track %d' % number)
            return self._adopt_readahead(active, mine)
        return None

    def _play_prepare_locked(self, index, number, netmd, mine):
        number = int(number)
        if netmd and self._readahead_on:
            quick = self._quick_play(index, number, mine)
            if quick is not None:
                return quick
        if self._active is not None:
            self._active['announced'] = False                  # the read being replaced must not report to the page
        self._cancel_extract()
        if netmd:
            self._ra_base = number
        track = next((t for t in self._tracks if t['number'] == number), None)
        copy = self._find_copy(track['title'], track['seconds'], codec=track['codec']) if netmd and track else None
        if copy:                                               # the app's own copy: no need to ask the recorder
            path = os.path.join(COPIES_DIR, copy['id'] + '.flac')
            st = {'key': 'copy-' + copy['id'], 'name': copy['id'] + '.flac', 'format': 'flac', 'path': path, 'total': os.path.getsize(path),
                  'mime': 'audio/flac', 'done': True, 'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
            self._ensure_server()
            self._streams[st['name']] = st
            self._active = None                                # a read of an earlier track may no longer report to the page
            return self._play_reply(st)
        # A recorder that cannot send audio back (MZ-NH700...) is read with the firmware-patch download (the helper checks its firmware).
        patch = bool(netmd and not self._can_fetch(index) and self._exploit_possible(index))
        if netmd and not self._can_fetch(index) and not patch:
            return {'error': 'This recorder can’t send audio back to the PC, and the app has no saved copy of this track; use the remote control instead.'}
        disc_key = self._netmd_sig if netmd else self._disc_key
        if track is None or not disc_key:
            return {'error': 'Reload the disc first.'}
        if not netmd and track['codec'] not in ('PCM', 'MP3', 'A3+', 'AT3'):
            return {'error': 'This track type can’t be played here.'}
        key, name, st = self._stream_for(number, track, patch, netmd, disc_key, int(index))
        self._ensure_server()
        cached = self._cache.get(key)
        if cached and os.path.exists(cached['path']) and os.path.getsize(cached['path']) == cached['total']:
            self._streams[name] = cached
            if netmd:
                self._clean_play_dir(keep=self._ra_keep(number) | {name})
                self._readahead_kick(cached, int(index))       # the tracks after this one are read while it plays
            return self._play_reply(cached)
        os.makedirs(PLAY_DIR, exist_ok=True)
        self._clean_play_dir(keep=self._ra_keep(number) if netmd else None)       # the tracks around this one that are already read stay
        self._cache.pop(key, None)
        self._streams = {n: s for n, s in self._streams.items() if s['done']}
        self._streams[name] = st
        started = st['ev']
        with self._ra_lock:
            st['epoch'] = self._cancel_epoch                   # a later cancellation (anything else wanting the recorder) stops the read-ahead that would follow
        self._active = st
        args = {'index': number - 1, 'out': st['path']}
        if patch:
            args['seconds'] = track['seconds']                 # the growing WAV declares its length up front
            self._spin_args(args, disc_key)
        self._thread = threading.Thread(target=self._extract, args=(st, args, started), daemon=True)
        self._thread.start()
        self._play_mutex.release()                             # let a newer request in while this one waits for its read to start
        try:
            ready = started.wait(300)
        finally:
            self._play_mutex.acquire()
        if mine != self._play_seq:
            return {'superseded': True}                        # the user already picked another track
        if not ready:
            self._cancel_extract()
            return {'error': 'The recorder did not respond in time.'}
        if st['failed']:
            return {'error': st['error']}
        st['announced'] = True
        return self._play_reply(st)

    def remote(self, action, index=0, seconds=0):
        """Standard discs: make the recorder itself play, pause, stop or seek. Writes nothing to the disc."""
        if not self._loaded_netmd:
            return {'error': 'Remote control is only for standard discs.'}
        with self._lock:
            return self._run_helper('remote', {'action': action, 'index': int(index), 'seconds': int(seconds)}, helper=NETMD_HELPER)
