"""Timed lyrics made by listening: for a track no lyrics service knows, the optional speech recogniser (whisper.cpp with one model, about 200 MB,
downloaded once on request into ASR_DIR) turns the track's audio into timed lines. It runs on this PC; no audio is sent anywhere.
AsrMixin is mixed into himd_app.Api (with LyricsMixin, PlayMixin, SavePcMixin and EditMixin, whose helpers it uses). Reads the disc like playing a track
does; writes nothing to it. The result is kept like any other lyrics (see lyrics.py), marked source 'whisper'."""
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile

import lyrics
from mdm_paths import ASR_DIR

ENGINE_URL = 'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip'
MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin'
MODEL_FILE = 'ggml-small-q5_1.bin'
MODEL_BYTES = 190085487
_NOISE = re.compile(r'^[\s\[\(\*♪♫#_-]*(?:music|musik|musique|applause|silence|laughter|singing|instrumental|blank_audio|inaudible|no speech)?[\s\]\)\*♪♫#_.-]*$', re.I)


def _engine_exe():
    for root, _dirs, files in os.walk(os.path.join(ASR_DIR, 'bin')):
        if 'whisper-cli.exe' in files:
            return os.path.join(root, 'whisper-cli.exe')
    return None


def _model_path():
    p = os.path.join(ASR_DIR, MODEL_FILE)
    return p if os.path.isfile(p) and os.path.getsize(p) == MODEL_BYTES else None


def _tidy(lrc):
    """Whisper on music invents "[Music]" lines and sometimes loops on one phrase: drop the first and cut the second short. '' when nothing usable is left."""
    out, last, run = [], None, 0
    for stamp, text in lyrics.parse_lrc(lrc):
        text = text.strip()
        if _NOISE.match(text):
            continue
        run = run + 1 if text.lower() == last else 1
        last = text.lower()
        if run <= 2:
            out.append((stamp, text))
    if len(out) < 3 or len({x[1].lower() for x in out}) < max(2, len(out) // 6):       # a handful of words, or one phrase over and over: nothing was really made out
        return ''
    return '\n'.join('[%02d:%05.2f]%s' % (int(s // 60), s % 60, x) for s, x in out)


ALIGN_SECONDS = 100                 # how much of the start of a track is listened to when the timing of its lyrics is checked
ALIGN_MIN_LINES = 4                 # at least this many lines must be found in the audio, agreeing with each other, before an offset is trusted
ALIGN_IGNORE = 0.5                  # a shift smaller than this is not corrected: the recogniser's own word timing is not that accurate
ALIGN_AGREE = 0.5                   # the two listens (with and without -sns) must agree to within this, or the track is left alone (found on this PC:
                                    # the same audio gave +0.5 s and -0.3 s depending on that one setting, so a single listen cannot be trusted below ~1 s)


def _words(text):
    return [w for w in re.sub(r"[^a-z' ]", '', re.sub(r'\(.*?\)', '', (text or '').lower())).split() if w]


def estimate_offset(heard_lrc, stored_lrc, window=ALIGN_SECONDS):
    """How far the singing in the audio is from the timed lyrics. `heard_lrc`: what the recogniser heard, one WORD per line with its time (LRC);
    `stored_lrc`: the track's timed lyrics. Each stored line is looked for in the heard words (its first two words, nearest in time, within 8 s); the
    middle of the agreeing differences is the answer. Returns (offset_seconds, lines_used, lines_found) or None when it cannot tell. A positive offset
    means the singing is LATER than the lyrics say, so the lyrics need delaying by that much (the same sign the player's nudge uses)."""
    heard = []
    for t, text in lyrics.parse_lrc(heard_lrc):
        w = _words(text)
        if w:
            heard.append((t, w[0]))
    stored = [(t, _words(x)) for t, x in lyrics.parse_lrc(stored_lrc) if x.strip() and t < window - 5]
    deltas = []
    for t, w in stored:
        if len(w) < 2:
            continue
        best = None
        for k in range(len(heard) - 1):
            if heard[k][1] == w[0] and heard[k + 1][1] == w[1] and abs(heard[k][0] - t) <= 8:
                if best is None or abs(heard[k][0] - t) < abs(best):
                    best = heard[k][0] - t
        if best is not None:
            deltas.append(best)
    if len(deltas) < ALIGN_MIN_LINES:
        return None
    mid = sorted(deltas)[len(deltas) // 2] if len(deltas) % 2 else sum(sorted(deltas)[len(deltas) // 2 - 1:len(deltas) // 2 + 1]) / 2
    inliers = [d for d in deltas if abs(d - mid) <= 1.5]
    if len(inliers) < max(ALIGN_MIN_LINES, 0.6 * len(deltas)):
        return None                                                      # the lines disagree with each other: a different version, not a shift
    s = sorted(inliers)
    final = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
    return round(final, 1), len(inliers), len(deltas)


class AsrMixin:
    # -- the recogniser itself -------------------------------------------------------------------
    def lyrics_asr_status(self):
        return {'ready': bool(_engine_exe() and _model_path()), 'engine': bool(_engine_exe()), 'model': bool(_model_path()), 'megabytes': round((MODEL_BYTES + 9000000) / 1e6)}

    def lyrics_asr_remove(self):
        shutil.rmtree(ASR_DIR, ignore_errors=True)
        return self.lyrics_asr_status()

    def _asr_download(self, url, dest, expect, label, step, steps):
        """Downloads url to dest (via a .part file) and checks the size. Raises RuntimeError with a plain message."""
        part = dest + '.part'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': lyrics.UA})
            with urllib.request.urlopen(req, timeout=30) as r, open(part, 'wb') as f:
                total = int(r.headers.get('Content-Length') or expect or 0)
                done = 0
                while True:
                    if self._edit_cancel:
                        raise RuntimeError('Cancelled.')
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    self._edit_tell(phase='asr_download', n=step, count=steps, name=label, done=done, total=total)
            if expect and done != expect:
                raise RuntimeError('The download of %s was incomplete (%d of %d bytes). Try again.' % (label, done, expect))
            os.replace(part, dest)
        except (OSError, ValueError) as exc:
            raise RuntimeError('Could not download %s: %s' % (label, getattr(exc, 'reason', exc)))
        finally:
            try:
                os.remove(part)
            except OSError:
                pass

    def lyrics_asr_install(self):
        """Downloads the recogniser program (about 9 MB, from the whisper.cpp project on GitHub) and its model (about 190 MB, from Hugging Face)."""
        self._edit_cancel = False
        os.makedirs(ASR_DIR, exist_ok=True)
        steps = (0 if _engine_exe() else 1) + (0 if _model_path() else 1)
        step = 0
        try:
            if not _engine_exe():
                zpath = os.path.join(ASR_DIR, 'engine.zip')
                self._asr_download(ENGINE_URL, zpath, 0, 'the speech recogniser program', step, steps)
                step += 1
                dest = os.path.join(ASR_DIR, 'bin')
                shutil.rmtree(dest, ignore_errors=True)
                with zipfile.ZipFile(zpath) as z:
                    for m in z.infolist():                                          # only what the command line program needs
                        base = os.path.basename(m.filename).lower()
                        if m.is_dir() or not (base == 'whisper-cli.exe' or (base.endswith('.dll') and not base.startswith(('sdl2', 'llama', 'parakeet')))):
                            continue
                        target = os.path.join(dest, os.path.basename(m.filename))
                        os.makedirs(dest, exist_ok=True)
                        with z.open(m) as src, open(target, 'wb') as out:
                            shutil.copyfileobj(src, out)
                os.remove(zpath)
                if not _engine_exe():
                    raise RuntimeError('The downloaded program was not what was expected.')
            if not _model_path():
                self._asr_download(MODEL_URL, os.path.join(ASR_DIR, MODEL_FILE), MODEL_BYTES, 'the speech model', step, steps)
        except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
            if str(exc) == 'Cancelled.':
                return {'cancelled': True}
            return {'error': str(exc) if isinstance(exc, RuntimeError) else 'The download could not be unpacked: %s' % exc}
        return dict(self.lyrics_asr_status(), ok=True)

    # -- listening to tracks ----------------------------------------------------------------------
    def _asr_audio(self, index, number, t, label, n, count):
        """The track's audio as the path of a finished WAV file: the app's own saved copy, or read from the disc the way playing it does."""
        res = self.play_prepare(index, number)
        if res.get('superseded'):
            raise RuntimeError('Another track was started meanwhile.')
        if res.get('error'):
            raise RuntimeError(res['error'])
        st = self._streams.get(res['url'].rsplit('/', 1)[-1])
        if not st:
            raise RuntimeError('The track could not be read.')
        while not st['done']:
            if self._edit_cancel:
                raise RuntimeError('Cancelled.')
            if st['failed']:
                raise RuntimeError(st['error'] or 'Reading the track failed.')
            try:
                have = os.path.getsize(st['path'])
            except OSError:
                have = 0
            self._edit_tell(phase='reading', n=n, count=count, name=label, done=have, total=st.get('total') or 0)
            time.sleep(0.4)
        return st['path']

    def lyrics_asr_run(self, index, numbers, language='auto'):
        """Listens to the tracks and keeps what is heard as their (timed) lyrics. Returns {done: [numbers], failed: [{number, error}]} or {cancelled}."""
        exe, model = _engine_exe(), _model_path()
        if not (exe and model):
            return {'error': 'The speech recogniser is not installed yet.'}
        index = int(index)
        try:
            wanted = sorted({int(n) for n in numbers})
        except (TypeError, ValueError):
            return {'error': 'Choose the tracks to listen to.'}
        tracks = [t for t in self._tracks if t['number'] in wanted]
        if not tracks:
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}
        lang = language if re.fullmatch(r'[a-z]{2,3}|auto', str(language)) else 'auto'
        self._edit_cancel = False
        tell, done, failed = self._edit_tell, [], []
        tmp = tempfile.mkdtemp(prefix='mdm-asr-')
        try:
            for i, t in enumerate(tracks):
                label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
                try:
                    tell(phase='reading', n=i, count=len(tracks), name=label, done=0, total=0)
                    src = self._asr_audio(index, t['number'], t, label, i, len(tracks))
                    wav = os.path.join(tmp, 't%d.wav' % i)
                    self._ffmpeg(['-i', src, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav])          # the recogniser wants 16 kHz mono
                    text = self._asr_listen(exe, model, wav, os.path.join(tmp, 't%d' % i), lang, i, len(tracks), label)
                    text = _tidy(text)
                    if not text:
                        raise RuntimeError('No words could be made out (an instrumental, or the singing is too buried in the music).')
                    self._ly_put(t, text, 'whisper', synced=True)
                    done.append(t['number'])
                except RuntimeError as exc:
                    if str(exc) == 'Cancelled.' or self._edit_cancel:
                        return dict(self.lyrics_status(), cancelled=True, done=done, failed=failed)
                    failed.append({'number': t['number'], 'error': str(exc)})
                finally:
                    for f in os.listdir(tmp):
                        try:
                            os.remove(os.path.join(tmp, f))
                        except OSError:
                            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return dict(self.lyrics_status(), done=done, failed=failed)

    def lyrics_align_run(self, index, numbers, language='auto'):
        """Checks the timing of the tracks' timed lyrics against their audio and sets each track's offset so the lines come when they are sung. The
        start of each track is listened to (word by word); no lyrics are changed, only the offset, and a track whose lyrics do not fit the audio (a
        different version) is left alone and reported. Returns {done: [{number, offset, lines}], skipped: [{number, reason}], failed: [...]}."""
        exe, model = _engine_exe(), _model_path()
        if not (exe and model):
            return {'error': 'The speech recogniser is not installed yet.'}
        index = int(index)
        try:
            wanted = sorted({int(n) for n in numbers})
        except (TypeError, ValueError):
            return {'error': 'Choose the tracks to check.'}
        store = self._ly_read()
        tracks = [t for t in self._tracks if t['number'] in wanted]
        if not tracks:
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}
        lang = language if re.fullmatch(r'[a-z]{2,3}|auto', str(language)) else 'auto'
        self._edit_cancel = False
        tell, done, skipped, failed = self._edit_tell, [], [], []
        tmp = tempfile.mkdtemp(prefix='mdm-align-')
        try:
            for i, t in enumerate(tracks):
                label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
                entry = self._ly_find(store, t['title'], t['artist'], t['seconds'])
                if not entry or not entry.get('synced'):
                    skipped.append({'number': t['number'], 'reason': 'It has no timed lyrics.'})
                    continue
                if entry.get('source') == 'whisper':
                    skipped.append({'number': t['number'], 'reason': 'Its lyrics were made by listening, so they already follow the audio.'})
                    continue
                try:
                    tell(phase='reading', n=i, count=len(tracks), name=label, done=0, total=0)
                    src = self._asr_audio(index, t['number'], t, label, i, len(tracks))
                    wav = os.path.join(tmp, 't%d.wav' % i)
                    self._ffmpeg(['-i', src, '-t', str(ALIGN_SECONDS + 5), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav])
                    est = []
                    for variant, sns in enumerate((True, False)):                    # two listens, with and without suppressing non-speech sounds: they must agree
                        heard = self._asr_listen(exe, model, wav, os.path.join(tmp, 't%d_%d' % (i, variant)), lang, i, len(tracks), label, words=True, sns=sns)
                        est.append(estimate_offset(heard, entry.get('lrc')))
                    if None in est:
                        skipped.append({'number': t['number'], 'reason': 'The lyrics could not be matched to the singing closely enough to tell (a different version, or a quiet start).'})
                    elif abs(est[0][0] - est[1][0]) > ALIGN_AGREE:
                        skipped.append({'number': t['number'], 'reason': 'The two listens disagreed (%+.1f s and %+.1f s), so the shift is too small to measure reliably.' % (est[0][0], est[1][0])})
                    else:
                        offset = round((est[0][0] + est[1][0]) / 2, 1)
                        offset = 0.0 if abs(offset) < ALIGN_IGNORE else offset
                        self.lyrics_set_offset(t['number'], offset)
                        done.append({'number': t['number'], 'offset': offset, 'lines': min(est[0][1], est[1][1])})
                except RuntimeError as exc:
                    if str(exc) == 'Cancelled.' or self._edit_cancel:
                        return dict(self.lyrics_status(), cancelled=True, done=done, skipped=skipped, failed=failed)
                    failed.append({'number': t['number'], 'error': str(exc)})
                finally:
                    for f in os.listdir(tmp):
                        try:
                            os.remove(os.path.join(tmp, f))
                        except OSError:
                            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return dict(self.lyrics_status(), done=done, skipped=skipped, failed=failed)

    def _asr_listen(self, exe, model, wav, base, lang, n, count, label, words=False, sns=True):
        """Runs the recogniser on a 16 kHz WAV and returns its timed lines as LRC text (words=True: one word per line, only the first
        ALIGN_SECONDS, for checking lyric timing; sns=False: without suppressing non-speech sounds). Progress goes to the page; cancelling stops the program."""
        threads = max(2, min(8, (os.cpu_count() or 4) - 1))
        cmd = [exe, '-m', model, '-f', wav, '-of', base, '-olrc', '-pp', '-l', lang, '-t', str(threads), '-mc', '0'] + (['-sns'] if sns else []) + ['-ml', '1' if words else '60', '-sow']
        if words:
            cmd += ['-d', str(ALIGN_SECONDS * 1000)]
        proc = subprocess.Popen(cmd, cwd=os.path.dirname(exe), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        tail = []
        try:
            for line in proc.stderr:
                if self._edit_cancel:
                    proc.kill()
                    raise RuntimeError('Cancelled.')
                m = re.search(r'progress\s*=\s*(\d+)%', line)
                if m:
                    self._edit_tell(phase='listening', n=n, count=count, name=label, done=int(m.group(1)), total=100)
                elif line.strip():
                    tail = (tail + [line.strip()])[-4:]
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
        out = base + '.lrc'
        if proc.returncode or not os.path.isfile(out):
            raise RuntimeError('The speech recogniser stopped (%s).' % (' '.join(tail)[-200:] or 'code %s' % proc.returncode))
        with open(out, encoding='utf-8', errors='replace') as f:
            return f.read()
