"""Naming tracks by listening (AcoustID / Chromaprint): the key handling, the short "what was read" previews, and Api.identify_tracks.
IdentifyMixin is mixed into himd_app.Api, which supplies ACOUSTID_BUILTIN_KEY (the built-in key) and the disc / helper methods used below. Reads the disc; never writes to it."""
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time

import cdrip
from mdm_paths import COPIES_DIR, HERE, NETMD_HELPER, USER_DIR


class IdentifyMixin:
    # AcoustID: names a track by listening to it (a Chromaprint fingerprint of its first two minutes is looked up online). It needs a free
    # application key from acoustid.org: the program has one built in (acoustid_full.py); a key the user pastes in is kept in ACOUSTID_KEY_FILE
    # and wins over it.
    ACOUSTID_KEY_FILE = os.path.join(USER_DIR, 'acoustid-key.txt')

    def _acoustid_key(self):
        try:
            with open(self.ACOUSTID_KEY_FILE, encoding='utf-8') as f:
                key = f.read().strip()
        except OSError:
            key = ''
        return key or self.ACOUSTID_BUILTIN_KEY

    def acoustid_status(self):
        return {'hasKey': bool(self._acoustid_key())}

    def acoustid_set_key(self, key):
        key = re.sub(r'\s+', '', key or '')
        if key and not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', key):
            return {'error': 'That does not look like an AcoustID key (letters and numbers only).'}
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            if key:
                with open(self.ACOUSTID_KEY_FILE, 'w', encoding='utf-8') as f:
                    f.write(key)
            elif os.path.exists(self.ACOUSTID_KEY_FILE):
                os.remove(self.ACOUSTID_KEY_FILE)
        except OSError as exc:
            return {'error': str(exc)}
        return {'ok': True}

    @staticmethod
    def _fingerprint(path):
        """Chromaprint fingerprint (base64) of the first two minutes of an audio file, made by the bundled ffmpeg."""
        exe = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
        r = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-i', path, '-t', '120', '-ac', '1', '-f', 'chromaprint', '-fp_format', 'base64', '-'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        fp = r.stdout.strip()
        if r.returncode or not fp:
            raise RuntimeError('Could not listen to this track: %s' % (r.stderr.strip()[-200:] or 'no fingerprint'))
        return fp

    @staticmethod
    def _audio_seconds(path):
        """Length in seconds of an audio file as ffmpeg reports it, or None when it cannot tell."""
        exe = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
        r = subprocess.run([exe, '-hide_banner', '-i', path], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', r.stderr)
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None

    def _preview_clear(self):
        """Forget the short 'what was read' previews of the last Identify run and delete their files."""
        d, self._preview_dir = self._preview_dir, None
        for name in [n for n in self._streams if n.startswith('listen-')]:
            self._streams.pop(name, None)
        if d:
            shutil.rmtree(d, ignore_errors=True)

    def _make_preview(self, src):
        """The first 45 seconds of the audio that was read, as a small MP3 the page can play (\"Hear what was read\"), so a wrong track is easy
        to spot. Returns its address, or None."""
        try:
            if not self._preview_dir:
                self._preview_dir = tempfile.mkdtemp(prefix='mdm-preview-')
            name = 'listen-%s.mp3' % secrets.token_hex(5)
            dest = os.path.join(self._preview_dir, name)
            self._ffmpeg(['-i', src, '-t', '45', '-vn', '-ac', '2', '-ar', '44100', '-map_metadata', '-1', '-c:a', 'libmp3lame', '-q:a', '5', dest])
            self._ensure_server()
            self._streams[name] = {'key': name, 'name': name, 'format': 'mp3', 'path': dest, 'total': os.path.getsize(dest), 'mime': 'audio/mpeg',
                                   'done': True, 'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
            return 'http://127.0.0.1:%d/%s/%s' % (self._port, self._token, name)
        except (RuntimeError, OSError):
            return None

    def identify_tracks(self, index, numbers, use_exploit=False, ignore_copies=False):
        """Names tracks by listening: reads each (PCM / ATRAC) track from the disc, fingerprints it and asks AcoustID. Writes nothing to the
        disc. Returns {results: [{number, seconds, matches: [{score, title, artist, album}] | error}], exploitUsed}.
        A standard disc: the MZ-RH1 sends a track back by itself (or a saved copy is used); a recorder such as the MZ-NH700 can only do it with
        the opt-in firmware-patch download (`use_exploit`, the same one Save to PC offers)."""
        index = int(index)
        netmd = self._is_netmd(index)
        used_exploit = False
        key = self._acoustid_key()
        if not key:
            return {'needKey': True, 'error': 'An AcoustID key is needed first.'}
        try:
            wanted = sorted({int(n) for n in numbers})
        except (TypeError, ValueError):
            return {'error': 'Choose the tracks to identify.'}
        tracks = [t for t in self._tracks if t['number'] in wanted]
        if not tracks or len(tracks) != len(wanted):
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}
        self._edit_cancel = False
        self._preview_clear()
        tmp = tempfile.mkdtemp(prefix='mdm-listen-')
        tell = self._edit_tell
        class _Live(list):                                             # each finished track is also sent to the page at once, so its names show while the rest are still being listened to
            def append(self, entry):
                super().append(entry)
                tell(phase='result', res=entry)
        results, kept = _Live(), []
        try:
            for i, t in enumerate(tracks):
                label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
                kind = 'netmd' if netmd else self._edit_kind(t)
                if kind is None or (kind == 'atrac' and t['rate'] != 44100):
                    results.append({'number': t['number'], 'seconds': t['seconds'], 'error': 'Only PCM and ATRAC tracks can be listened to.'})
                    continue
                from_disc = False                                              # True once this track was read from the recorder by the patched download
                later = sum(u['seconds'] for u in tracks[i + 1:])             # audio still to come after this track, for the time estimate
                tell(phase='reading', n=i, count=len(tracks), name=label, done=0, total=0, seconds=t['seconds'], later=later)
                src = os.path.join(tmp, 't%d.%s' % (i, 'oma' if kind == 'atrac' else 'wav'))
                progress = lambda m, i=i, label=label, secs=t['seconds'], later=later: tell(phase='reading', n=i, count=len(tracks), name=label, done=m.get('done', 0), total=m.get('total', 0), seconds=secs, later=later) if m.get('event') == 'progress' else None
                if netmd:
                    copy = None if ignore_copies else self._find_copy(t['title'], t['seconds'], codec=t['codec'])      # ignore_copies: read it from the disc again
                    if copy:                                                       # the app already saved this track: use that copy (never deleted below)
                        src = os.path.join(COPIES_DIR, copy['id'] + '.flac')
                        res = {}
                    elif self._can_fetch(index) or (use_exploit and self._exploit_possible(index)):
                        patched = not self._can_fetch(index)
                        used_exploit = used_exploit or patched
                        from_disc = patched
                        fetch_args = {'index': t['number'] - 1, 'out': src}
                        if patched:
                            fetch_args['exploit'] = True
                        for attempt in (1, 2):                                      # the recorder needs a moment between tracks; one more try if it was not ready
                            if i or attempt > 1:
                                time.sleep(12 if patched else 4)                    # the patched download works the drive harder: give it longer to settle
                            with self._lock:
                                res = self._run_helper('fetch', fetch_args, progress, helper=NETMD_HELPER)
                            if 'error' not in res or self._edit_cancel:
                                break
                    else:
                        why = ('This recorder can only send audio back with the experimental download: tick the box to allow it.' if self._exploit_possible(index)
                               else 'This recorder cannot send audio back, so this track cannot be listened to.')
                        results.append({'number': t['number'], 'seconds': t['seconds'], 'error': why})
                        continue
                else:
                    with self._lock:
                        res = self._run_helper('dump', {'index': t['number'] - 1, 'out': src, 'exact': True, 'raw': kind == 'atrac'}, progress)
                if self._edit_cancel:
                    return {'cancelled': True}
                if 'error' in res:
                    results.append({'number': t['number'], 'seconds': t['seconds'], 'error': 'Reading the track failed: %s' % res['error']})
                    continue
                heard = self._audio_seconds(src)                            # is this really the track that was ticked? the length must match the disc's list
                preview = self._make_preview(src)                           # so the user can hear what was read, also when it looks like the wrong track
                if heard and abs(heard - t['seconds']) > max(3.0, t['seconds'] * 0.02):
                    results.append({'number': t['number'], 'seconds': t['seconds'], 'readSeconds': round(heard), 'previewUrl': preview,
                                    'error': 'The audio read from the recorder is %d:%02d long, but the disc lists this track as %d:%02d, so the wrong track may have been read. '
                                             'Nothing was looked up.' % (heard // 60, heard % 60, t['seconds'] // 60, t['seconds'] % 60)})
                    if os.path.dirname(src) == tmp:
                        try:
                            os.remove(src)
                        except OSError:
                            pass
                    continue
                if from_disc and self._keep_copy(src, t, replace=bool(ignore_copies)):         # a slow patched read: keep it, so Combine / Split / Identify need not read it again
                    kept.append(t['number'])
                tell(phase='preparing', n=i, count=len(tracks), name=label, done=0, total=0)
                try:
                    fp = self._fingerprint(src)
                    matches = cdrip.acoustid_lookup(key, fp, t['seconds'])
                except cdrip.CdError as exc:
                    if 'api key' in str(exc).lower() or 'invalid' in str(exc).lower():
                        return {'needKey': True, 'error': str(exc)}
                    return {'error': str(exc)}
                except RuntimeError as exc:
                    results.append({'number': t['number'], 'seconds': t['seconds'], 'error': str(exc)})
                    continue
                finally:
                    if os.path.dirname(src) == tmp:                                # only our own temporary file, never a saved copy
                        try:
                            os.remove(src)
                        except OSError:
                            pass
                results.append({'number': t['number'], 'seconds': t['seconds'], 'matches': matches, 'previewUrl': preview, 'readSeconds': round(heard) if heard else None})
            return {'results': results, 'exploitUsed': used_exploit, 'kept': kept}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self._release_devices()
