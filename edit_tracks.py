"""Split, combine, trim and fade & level for Hi-MD PCM and ATRAC tracks: the split editor, writing the new tracks, and the saved copies for when they do not fit. EditMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import array
import datetime
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading

import himd_dev
import himd_disc
import himd_fs
import usb.util
from mdm_common import wav_data_bytes, wav_header
from mdm_paths import FFMPEG
from mdm_paths import HERE, NETMD_HELPER, SPLIT_DIR


class EditMixin:
    def _edit_init(self):
        self._edit_cancel = False
        self._edit_prep = None      # the split editor's temporary copy of a track: {number, path, dir, name}

    # A track cannot be cut or joined on the disc itself: its audio is encrypted with a key of its own. So new tracks are written:
    #  - PCM: the app reads the audio, cuts or joins it on the PC (to the sample) and writes the result as new PCM tracks.
    #  - ATRAC, "lossless": the decrypted ATRAC frames are cut or joined at a frame boundary and written back unchanged with the
    #    original's own codec fields; nothing is decoded or encoded. The first frame of a second part decodes without the previous
    #    frame's overlap, so its first ~46 ms (ATRAC3+) / ~23 ms (ATRAC3) is distorted; everything before the cut is exact.
    #  - ATRAC, "pcm": the track is decoded and written as PCM, so the cut is exact to the sample (and the files are larger).
    # The new tracks are read back and compared byte for byte, then placed next to the originals. The originals are never touched
    # here; deleting them is a separate step the user confirms.
    EDIT_MAX_BYTES = 600 * 1000 * 1000                     # per new PCM track (the helper holds a track in memory while writing it)
    EDIT_MIN_PART = 2.0                                    # seconds
    EDIT_MAX_POINTS = 30                                   # split points in one go (so up to 31 new tracks)

    @staticmethod
    def _edit_kind(t):
        return 'pcm' if t['codec'] == 'PCM' else 'atrac' if t['codec'] in ('A3+', 'AT3') else None

    @staticmethod
    def _oma_frames(path, t):
        """Whole ATRAC frames in a .oma file written by the helper (96-byte EA3 header), checked against the track's frame size."""
        with open(path, 'rb') as f:
            head = f.read(96)
        size = os.path.getsize(path)
        if len(head) < 96 or head[:3] != b'EA3' or ((head[4] << 8) | head[5]) != 96 or head[32] != t['codecId']:
            raise RuntimeError('The audio read from the disc is not in the expected ATRAC format.')
        frame = t['frame']
        if not frame or size <= 96 or (size - 96) % frame:
            raise RuntimeError('The ATRAC audio read from the disc is not a whole number of frames.')
        return (size - 96) // frame

    @staticmethod
    def _adjust_params(params):
        """(fade in seconds, fade out seconds, level) of a Fade & level edit, or (None, None, None) when they are not usable.
        level: 'none', 'peak' (each track as loud as it can be without clipping) or 'match' (the ticked tracks brought to one average volume)."""
        try:
            fade_in, fade_out = float(params.get('fadeIn') or 0), float(params.get('fadeOut') or 0)
        except (TypeError, ValueError):
            return None, None, None
        level = params.get('level') or 'none'
        if not (0 <= fade_in <= 30 and 0 <= fade_out <= 30) or level not in ('none', 'peak', 'match', 'gain'):
            return None, None, None
        if level == 'gain' and not EditMixin._adjust_gain(params):
            level = 'none'                                                       # a change of 0 dB is no change
        return round(fade_in, 2), round(fade_out, 2), level

    @staticmethod
    def _adjust_suffix(params):
        """The text added to a changed track's title, such as ' (+6 dB)', ' (fade)' or ' (+3 dB, fade)'."""
        fade_in, fade_out, level = EditMixin._adjust_params(params)
        parts = []
        if level == 'gain':
            parts.append('%+g dB' % EditMixin._adjust_gain(params))
        elif level == 'peak':
            parts.append('louder')
        elif level == 'match':
            parts.append('levelled')
        if fade_in or fade_out:
            parts.append('fade')
        return ' (%s)' % ', '.join(parts) if parts else ''

    @staticmethod
    def _adjust_gain(params):
        """The chosen volume change in dB for level 'gain' (-30 to +30), 0.0 when unusable."""
        try:
            g = float(params.get('gainDb') or 0)
        except (TypeError, ValueError):
            return 0.0
        return round(max(-30.0, min(30.0, g)), 1)

    def _volume_stats(self, path):
        """(mean dB, peak dB) of a WAV file as ffmpeg's volumedetect reports them."""
        exe = FFMPEG
        r = subprocess.run([exe, '-hide_banner', '-nostats', '-i', path, '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        mean = re.search(r'mean_volume:\s*(-?[\d.]+|-inf) dB', r.stderr)
        peak = re.search(r'max_volume:\s*(-?[\d.]+|-inf) dB', r.stderr)
        if not mean or not peak or 'inf' in mean.group(1) + peak.group(1):
            raise RuntimeError('This track is completely silent, so its volume can not be adjusted.')
        return float(mean.group(1)), float(peak.group(1))

    def _edit_adjust(self, srcs, params, tmp, tell):
        """Fade in / out and the volume setting applied to each PCM WAV in `srcs`; returns the new WAV paths (same length as the originals).
        'match' brings every track to the average of the tracks' average volumes, but never past -1 dB peak (no clipping)."""
        fade_in, fade_out, level = self._adjust_params(params)
        gains = [0.0] * len(srcs)
        manual = self._adjust_gain(params) if level == 'gain' else 0.0
        if level == 'gain':
            gains = [manual] * len(srcs)                                         # exactly the amount asked; a boost is followed by a limiter below, so loud tracks get louder too
        elif level != 'none':
            stats = []
            for i, p in enumerate(srcs):
                if self._edit_cancel:
                    return None
                tell(phase='preparing')
                stats.append(self._volume_stats(p))
            ceiling = [-1.0 - peak for _mean, peak in stats]                      # the most gain each track can take
            if level == 'peak':
                gains = ceiling
            else:
                target = sum(m for m, _p in stats) / len(stats)
                gains = [min(target - m, c) for (m, _p), c in zip(stats, ceiling)]
        out = []
        for i, p in enumerate(srcs):
            if self._edit_cancel:
                return None
            tell(phase='preparing')
            seconds = wav_data_bytes(p) / 176400.0
            chain = []
            if abs(gains[i]) >= 0.05:
                chain.append('volume=%.2fdB' % gains[i])
                if gains[i] > 0 and level == 'gain':                           # a track already near full scale can not just be multiplied: the limiter keeps the peaks at -1 dB
                    chain.append('alimiter=limit=0.89:attack=5:release=80:level=disabled')
            if fade_in:
                chain.append('afade=t=in:st=0:d=%.2f' % fade_in)
            if fade_out:
                chain.append('afade=t=out:st=%.3f:d=%.2f' % (max(0.0, seconds - fade_out), fade_out))
            dest = os.path.join(tmp, 'adj%d.wav' % i)
            args = ['-i', p]
            if chain:
                args += ['-af', ','.join(chain)]
            self._ffmpeg(args + ['-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', dest])
            os.remove(p)
            out.append(dest)
        return out

    def _edit_validate(self, op, numbers, params):
        order = list(dict.fromkeys(int(n) for n in numbers))        # the order given (a combine joins in this order), each track once
        wanted = set(order)
        by_number = {t['number']: t for t in self._tracks}
        tracks = [by_number[n] for n in order if n in by_number]
        if not tracks or len(tracks) != len(wanted):
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}
        kinds = {self._edit_kind(t) for t in tracks}
        if None in kinds or len(kinds) != 1:
            return {'error': 'Only PCM or ATRAC tracks can be split or combined, and not a mixture of the two.'}
        kind = kinds.pop()
        mode = 'pcm'
        if kind == 'atrac':
            mode = 'pcm' if (params.get('mode') == 'pcm' or op == 'adjust') else 'lossless'      # changing the sound means decoding it
            if any(t['rate'] != 44100 for t in tracks):
                return {'error': 'Only 44.1 kHz ATRAC tracks can be split or combined.'}
            if mode == 'lossless' and len({t['ci'] for t in tracks}) != 1:
                return {'error': 'These tracks use different ATRAC settings, so they cannot be joined without re-encoding. Choose the PCM option instead.'}
        name = lambda t: t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
        if op == 'split':
            if len(tracks) != 1:
                return {'error': 'Choose one track to split.'}
            t = tracks[0]
            raw = params.get('points')
            if raw is None:
                raw = [params.get('seconds')]                  # one split point (older callers)
            try:
                points = sorted(float(x) for x in raw)
            except (TypeError, ValueError):
                return {'error': 'Choose where to split the track.'}
            if not points:
                return {'error': 'Choose where to split the track.'}
            if len(points) > self.EDIT_MAX_POINTS:
                return {'error': 'A track can be split at up to %d places at once.' % self.EDIT_MAX_POINTS}
            edges = [0.0] + points + [float(t['seconds'])]
            parts = len(edges) - 1
            skip = [bool(x) for x in (params.get('skip') or [])][:parts]      # parts that are left out (trimmed away) instead of written
            skip += [False] * (parts - len(skip))
            if all(skip):
                return {'error': 'Keep at least one part.'}
            if any(b - a < (0.0 if s else self.EDIT_MIN_PART) for (a, b), s in zip(zip(edges, edges[1:]), skip)):
                return {'error': 'Each part must be at least %d seconds long.' % self.EDIT_MIN_PART}
            titles = [str(x).strip() for x in (params.get('titles') or [])]
            titles += [''] * (parts - len(titles))
            kept = [k for k in range(parts) if not skip[k]]
            outs = [{'title': titles[k] or (name(t) if len(kept) == 1 else '%s (%d)' % (name(t), i + 1)), 'seconds': edges[k + 1] - edges[k]}
                    for i, k in enumerate(kept)]
        elif op == 'combine':
            if len(tracks) < 2:
                return {'error': 'Choose at least two tracks to combine.'}
            kept = [0]
            outs = [{'title': str(params.get('title') or '').strip() or name(tracks[0]), 'seconds': sum(t['seconds'] for t in tracks)}]
        elif op == 'adjust':
            fade_in, fade_out, level = self._adjust_params(params)
            if fade_in is None:
                return {'error': 'Choose a fade between 0 and 30 seconds, and one of the volume options.'}
            if not fade_in and not fade_out and level == 'none':
                return {'error': 'Choose a fade or a volume setting first.'}
            if any(t['seconds'] < fade_in + fade_out or t['seconds'] < self.EDIT_MIN_PART for t in tracks):
                return {'error': 'A fade can not be longer than the track it is on.'}
            kept = list(range(len(tracks)))
            suffix = self._adjust_suffix(params)
            outs = [{'title': name(t) + suffix, 'seconds': t['seconds']} for t in tracks]           # each track becomes one new track with the same details, its title saying what was changed
        else:
            return {'error': 'Unknown edit.'}
        t0 = tracks[0]
        need = 2 * 16384
        for k, o in enumerate(outs):
            src = tracks[k] if op == 'adjust' else t0
            o['artist'], o['album'] = src['artist'], src['album']
            if mode == 'lossless':
                frames = -(-int(o['seconds'] * t0['rate']) // t0['spf'])
                o['bytes'] = frames * t0['frame']
                need += -(-frames // ((16320 - 1) // t0['frame'])) * 16384
            else:
                o['bytes'] = int(o['seconds'] * 176400)
                if o['bytes'] > self.EDIT_MAX_BYTES:
                    return {'error': 'The new track would be longer than %d minutes, which is more than this can write at once.' % (self.EDIT_MAX_BYTES // 176400 // 60)}
                need += -(-o['bytes'] // 16320) * 16384
        return {'tracks': tracks, 'outs': outs, 'need': need, 'kind': kind, 'mode': mode, 'kept': kept}

    # The split editor works on a local copy of the track: it is read from the disc once, played from the PC (so seeking is instant)
    # and drawn as a waveform; the split then cuts that same copy instead of reading the disc again.
    def _edit_prep_clear(self):
        prep, self._edit_prep = self._edit_prep, None
        if prep:
            self._streams.pop(prep['name'], None)
            shutil.rmtree(prep['dir'], ignore_errors=True)

    def edit_discard(self):
        self._edit_prep_clear()
        return {'ok': True}

    @staticmethod
    def _peak16(chunk):
        try:
            import audioop
            return audioop.max(chunk, 2)
        except ImportError:
            a = array.array('h')
            a.frombytes(chunk[:len(chunk) // 2 * 2])
            return max(max(a), -min(a)) if a else 0

    def _peaks_range(self, path, first, last, buckets):
        """Loudest sample in each of up to `buckets` equal slices of the stereo frames first..last (unscaled)."""
        frames = last - first
        per = max(1, frames // buckets)
        out = []
        with open(path, 'rb') as f:
            f.seek(44 + first * 4)
            for b in range(buckets):
                n = per if b < buckets - 1 else frames - per * (buckets - 1)
                if n <= 0:
                    break
                out.append(self._peak16(f.read(n * 4)))
        return out

    def _peaks(self, path, nbytes, buckets=1000):
        """Whole track: loudest sample per slice, scaled so the loudest is 1. Returns (peaks, the unscaled loudest)."""
        out = self._peaks_range(path, 0, nbytes // 4, buckets)
        top = max(out) or 1
        return [round(v / top, 3) for v in out], top

    def edit_peaks(self, name, start, end, buckets=1000):
        """Waveform detail for the split editor's zoom: the same scale as the whole-track picture, for start..end seconds. Reads the PC copy only."""
        prep = self._edit_prep
        if not prep or prep['name'] != name or not os.path.isfile(prep['path']):
            return {'error': 'The editor’s copy of the track is gone.'}
        try:
            first = max(0, int(float(start) * 44100))
            last = min(prep['frames'], int(float(end) * 44100))
            buckets = max(10, min(2000, int(buckets)))
        except (TypeError, ValueError):
            return {'error': 'Bad range.'}
        if last - first < 400:
            return {'error': 'Too small a range.'}
        try:
            raw = self._peaks_range(prep['path'], first, last, buckets)
        except OSError as exc:
            return {'error': str(exc)}
        return {'peaks': [round(min(1.0, v / prep['top']), 3) for v in raw], 'start': first / 44100.0, 'end': last / 44100.0}

    EDIT_MAX_GAPS = 400                                    # most quiet gaps one search reports

    def edit_silences(self, name, threshold_db=-60, min_gap=0.5):
        """Finds the quiet gaps of the split editor's copy: stretches where every 10 ms stays at or below `threshold_db` (dB below the
        loudest possible sample) for at least `min_gap` seconds. Reads the PC copy only."""
        prep = self._edit_prep
        if not prep or prep['name'] != name or not os.path.isfile(prep['path']):
            return {'error': 'The editor’s copy of the track is gone.'}
        auto = str(threshold_db).lower() == 'auto'
        try:
            fixed = None if auto else 32768.0 * 10 ** (max(-100.0, min(-10.0, float(threshold_db))) / 20.0)
            min_gap = max(0.1, min(30.0, float(min_gap)))
        except (TypeError, ValueError):
            return {'error': 'Bad search settings.'}
        need = int(round(min_gap * 100))
        try:
            wp = self._edit_wpeaks(prep)
        except OSError as exc:
            return {'error': str(exc)}
        if not wp:
            return {'gaps': [], 'truncated': False}
        continuous = None
        if auto:
            # Judged against the track itself (as the waveform picture is): the noise floor (quietest 5 %) with some headroom,
            # never above 20 dB under the loud parts. Copes with hiss, hum and quiet recordings that a fixed level misses.
            s = sorted(wp)
            floor, loud = s[len(s) // 20], s[len(s) * 95 // 100]
            limit = min(max(floor * 3.0, 12.0), max(loud * 0.1, 12.0))
            continuous = floor > loud * 0.05                  # even the quietest 5 % is within 26 dB of the loud parts: no real silence (a continuous mix)
        else:
            limit = fixed
        quiet = [v <= limit for v in wp]
        n = len(quiet)
        i = 0
        while i < n:                                         # a click or pop (up to 30 ms) inside a gap does not end it
            if quiet[i]:
                i += 1
                continue
            j = i
            while j < n and not quiet[j]:
                j += 1
            if j - i <= 3 and i > 0 and j < n:
                for k in range(i, j):
                    quiet[k] = True
            i = j
        gaps, run = [], None
        for k, q in enumerate(quiet):
            if q:
                if run is None:
                    run = k
            elif run is not None:
                if k - run >= need:
                    gaps.append((run / 100.0, k / 100.0))
                run = None
        if run is not None and n - run >= need:
            gaps.append((run / 100.0, n / 100.0))
        if continuous and len(gaps) >= max(2, n / 100.0 / 60.0 / 12.0):
            continuous = False                                # real gaps were found, about one per 12 minutes or more: songs with short gaps, not a continuous mix
        db = round(20 * math.log10(max(limit, 1.0) / 32768.0), 1)
        return {'gaps': [{'start': round(a, 2), 'end': round(b, 2)} for a, b in gaps[:self.EDIT_MAX_GAPS]], 'truncated': len(gaps) > self.EDIT_MAX_GAPS, 'level_db': db,
                'continuous': continuous}

    def _edit_wpeaks(self, prep):
        """The loudest sample of every 10 ms of the editor's copy of the track (16-bit stereo WAV), read once per editor session."""
        wp = prep.get('wpeaks')
        if wp is None:
            win, per_chunk = 441 * 4, 100                   # 10 ms of 16-bit stereo; windows read at a time (one second)
            wp = []
            with open(prep['path'], 'rb') as f:
                f.seek(44)
                while True:
                    chunk = f.read(win * per_chunk)
                    if not chunk:
                        break
                    wp.extend(self._peak16(chunk[i:i + win]) for i in range(0, len(chunk) - win + 1, win))
            prep['wpeaks'] = wp
        return wp

    def edit_dips(self, name, min_dip_db=9.0, min_song=90.0, max_points=28):
        """For a recording with no real silence between songs (a continuous mix): the places where the loudness drops furthest below its
        surroundings, as a guide to where songs change. A dip is how far a 0.5 s stretch sits below the median level of the 20 s either side;
        the strongest dips are kept, at least `min_song` seconds apart. Reads the PC copy only. Returns {dips: [{at, dip}]} in time order."""
        prep = self._edit_prep
        if not prep or prep['name'] != name or not os.path.isfile(prep['path']):
            return {'error': 'The editor’s copy of the track is gone.'}
        try:
            min_dip_db = max(2.0, min(30.0, float(min_dip_db)))
            min_song = max(10.0, min(600.0, float(min_song)))
            max_points = max(1, min(60, int(max_points)))
            wp = self._edit_wpeaks(prep)
        except (TypeError, ValueError, OSError) as exc:
            return {'error': str(exc)}
        blk, half = 50, 40                                    # 0.5 s blocks; 20 s either side for the baseline
        nb = len(wp) // blk
        if nb < 2 * half:
            return {'dips': []}
        env = [10.0 * math.log10(max(1.0, sum(v * v for v in wp[i * blk:(i + 1) * blk]) / blk)) for i in range(nb)]
        score = []
        for i in range(nb):
            w = sorted(env[max(0, i - half):min(nb, i + half + 1)])
            score.append(w[len(w) // 2] - env[i])
        cand = [i for i in range(nb) if score[i] >= min_dip_db and score[i] == max(score[max(0, i - 3):i + 4])]
        cand.sort(key=lambda i: -score[i])
        picks = []
        for i in cand:
            if len(picks) >= max_points:
                break
            if all(abs(i - j) * 0.5 >= min_song for j in picks):
                picks.append(i)
        picks.sort()
        return {'dips': [{'at': round(i * 0.5, 1), 'dip': round(score[i], 1)} for i in picks]}

    def _edit_tell(self, **msg):
        if self._window:
            try:
                self._window.evaluate_js('window.onEditProgress && window.onEditProgress(%s)' % json.dumps(msg))
            except Exception:
                pass

    def edit_prepare(self, index, number, use_exploit=False, ignore_copies=False):
        """Reads one PCM or ATRAC track from the disc into a temporary WAV for the split editor (ATRAC: also keeps its frames). Reads only.
        A standard disc is handled by netmd_edit.py (`use_exploit`: the opt-in download for an MZ-NH700)."""
        if self._is_netmd(index):
            return self._netmd_edit_prepare(index, number, bool(use_exploit), bool(ignore_copies))
        t = next((x for x in self._tracks if x['number'] == int(number)), None)
        if t is None:
            return {'error': 'That track is no longer on the disc. Reload it.'}
        kind = self._edit_kind(t)
        if kind is None:
            return {'error': 'Only PCM or ATRAC tracks can be split for now.'}
        if kind == 'atrac' and t['rate'] != 44100:
            return {'error': 'Only 44.1 kHz ATRAC tracks can be split.'}
        self._edit_prep_clear()
        self._edit_cancel = False
        tmp = tempfile.mkdtemp(prefix='mdm-split-')
        label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
        if shutil.disk_usage(tmp).free < t['seconds'] * 176400 * 1.4 + 50 * 1000 * 1000:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'error': 'There is not enough free space on this PC’s temporary drive to hold the track.'}
        src = os.path.join(tmp, 'track.wav' if kind == 'pcm' else 'track.oma')
        self._edit_tell(phase='reading', n=0, count=1, name=label, done=0, total=0)
        with self._lock:
            res = self._run_helper('dump', {'index': t['number'] - 1, 'out': src, 'exact': True, 'raw': kind == 'atrac'}, lambda m: self._edit_tell(
                phase='reading', n=0, count=1, name=label, done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None)
        if self._edit_cancel:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'cancelled': True}
        if 'error' in res:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'error': 'Reading “%s” from the disc failed: %s' % (label, res['error'])}
        try:
            wav, oma = src, None
            if kind == 'atrac':
                oma = src
                self._oma_frames(oma, t)
                wav = os.path.join(tmp, 'track.wav')
                self._ffmpeg(['-i', oma, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', wav])      # plain 44-byte header; for the waveform and for listening
            nbytes = wav_data_bytes(wav)
            peaks, top = self._peaks(wav, nbytes)
        except (RuntimeError, OSError) as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'error': str(exc)}
        name = 'split-%s.wav' % secrets.token_hex(6)
        self._ensure_server()
        self._streams[name] = {'key': name, 'name': name, 'format': 'wav', 'path': wav, 'total': 44 + nbytes, 'mime': 'audio/wav',
                               'done': True, 'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
        self._edit_prep = {'number': t['number'], 'path': wav, 'dir': tmp, 'name': name, 'kind': kind, 'oma': oma,
                          'frames': nbytes // 4, 'top': top}
        return {'url': 'http://127.0.0.1:%d/%s/%s' % (self._port, self._token, name), 'seconds': nbytes / 176400.0, 'peaks': peaks, 'name': name,
                'kind': kind, 'codec': t['codec'], 'frameSeconds': (t['spf'] / float(t['rate'])) if kind == 'atrac' else 0.0}

    def edit_plan(self, index, op, numbers, params):
        """Checks a split or combine and says what it needs. Writes nothing."""
        if self._is_netmd(index):
            return self._netmd_edit_plan(index, op, numbers, params)
        v = self._edit_validate(op, numbers, params or {})
        if 'error' in v:
            return v
        with self._lock:
            res = self._run_helper('plan', {'files': []})
        if 'error' in res:
            return res
        free = res['result']['freeBytes']
        src_bytes = sum(t['seconds'] * 176400 for t in v['tracks'])
        tmp_need = (int(src_bytes * 2.2) if v['mode'] == 'pcm' else int(src_bytes * 1.2)) + 50 * 1000 * 1000
        tmp_free = shutil.disk_usage(tempfile.gettempdir()).free
        return {'outs': [{'title': o['title'], 'seconds': o['seconds']} for o in v['outs']], 'needBytes': v['need'], 'freeBytes': free,
                'fits': v['need'] < free * 0.98, 'tmpNeed': tmp_need, 'tmpFree': tmp_free, 'tmpFits': tmp_free > tmp_need,
                'kind': v['kind'], 'mode': v['mode'],
                'freedByDelete': sum(x['blocks'] for x in v['tracks']) * 16384,
                'fitsAfterDelete': v['need'] < (free + sum(x['blocks'] for x in v['tracks']) * 16384) * 0.98}

    def _stop_transfer(self):
        """Asks the running copy / save / edit helper to stop, then ends the NetMD transfer."""
        try:
            self._proc.stdin.write('stop\n')
            self._proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass
        self._end_netmd_transfer()
        return {'ok': True}

    def _end_netmd_transfer(self):
        """Stop pressed while a standard-disc track is being sent to the PC. That transfer is one long read the helper cannot interrupt (it ignores
        'stop'), so the helper is ended and the recorder is told to stop playing. Other helper jobs, and the firmware-patch download (which
        stops itself between sectors), are left alone."""
        proc = self._proc
        try:
            args = list(proc.args)
            if proc.poll() is not None or args[2] != 'fetch' or '"exploit": true' in args[3]:
                return
            proc.terminate()
        except (AttributeError, IndexError, OSError, TypeError):
            return

        def halt():
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                return
            with self._lock:
                self._run_helper('halt', {}, helper=NETMD_HELPER)
        threading.Thread(target=halt, daemon=True).start()

    def edit_cancel(self):
        self._edit_cancel = True
        return self._stop_transfer()

    def edit_run(self, index, op, numbers, params):
        """WRITES TO THE DISC (new tracks only; the originals are not touched). See the note above."""
        index = int(index)
        if self._is_netmd(index):
            return self._netmd_edit_run(index, op, numbers, params)
        params = params or {}
        v = self._edit_validate(op, numbers, params)
        if 'error' in v:
            return v
        if params.get('stage') and self._edit_staged_manifest():
            return {'error': 'Saved parts from an earlier split are already waiting on this PC. Write them to the disc or discard them first.'}
        tracks, outs, kind, mode = v['tracks'], v['outs'], v['kind'], v['mode']
        t0 = tracks[0]
        lossless = mode == 'lossless'
        if op == 'split':
            points = sorted(float(x) for x in (params['points'] if params.get('points') is not None else [params['seconds']]))
        count_before = len(self._tracks)
        self._edit_cancel = False
        tmp = tempfile.mkdtemp(prefix='mdm-edit-')
        tell = self._edit_tell

        def reading(phase, n, count, label):
            return lambda m: tell(phase=phase, n=n, count=count, name=label, done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None

        try:
            # 1. the source audio: the split editor's copy, or read from the disc (PCM as WAV, ATRAC as its frames)
            prep = self._edit_prep
            if not (op == 'split' and prep and params.get('prepared') == prep['name'] and prep['number'] == t0['number'] and os.path.isfile(prep['path'])
                    and (not lossless or (prep.get('oma') and os.path.isfile(prep['oma'])))):
                prep = None
            srcs = []                                           # what the cutting step reads: .oma files (lossless) or WAV files
            if prep:
                srcs = [prep['oma'] if lossless else prep['path']]
            else:
                for i, t in enumerate(tracks):
                    label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
                    tell(phase='reading', n=i, count=len(tracks), name=label, done=0, total=0)
                    src = os.path.join(tmp, 'src%d.%s' % (t['number'], 'wav' if kind == 'pcm' else 'oma'))
                    with self._lock:
                        res = self._run_helper('dump', {'index': t['number'] - 1, 'out': src, 'exact': True, 'raw': kind == 'atrac'}, reading('reading', i, len(tracks), label))
                    if self._edit_cancel:
                        return {'cancelled': True}
                    if 'error' in res:
                        return {'error': 'Reading “%s” from the disc failed: %s Nothing was written.' % (label, res['error'])}
                    if kind == 'atrac':
                        self._oma_frames(src, t)
                        if not lossless:                        # decode, so the cut is exact to the sample
                            wav = os.path.join(tmp, 'src%d.wav' % t['number'])
                            self._ffmpeg(['-i', src, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', wav])
                            os.remove(src)
                            src = wav
                    srcs.append(src)

            # 2. cut or join on the PC
            tell(phase='preparing')
            if lossless:
                counts = [self._oma_frames(p, t) for p, t in zip(srcs, tracks)]
                frame = t0['frame']
                if op == 'split':
                    min_frames = -(-int(self.EDIT_MIN_PART * t0['rate']) // t0['spf'])
                    cuts = [int(round(s * t0['rate'] / t0['spf'])) for s in points]
                    edges = [0] + cuts + [counts[0]]
                    spans = list(zip(edges, edges[1:]))
                    if any(spans[k][1] - spans[k][0] < min_frames for k in v['kept']):
                        return {'error': 'A split position is too close to another one, or to the start or end of the track. Nothing was written.'}
                    plan = [[(srcs[0], 96 + a * frame, (b - a) * frame)] for k, (a, b) in enumerate(spans) if k in v['kept']]
                else:
                    plan = [[(p, 96, n * frame) for p, n in zip(srcs, counts)]]
            else:
                sizes = [wav_data_bytes(p) for p in srcs]
                if op == 'split':
                    # Hi-MD stores PCM in 64-byte units (16 samples) and drops a partial unit at the end of a track, so the cut must
                    # fall on one: then both parts are whole units and nothing is lost (found 2026-10-21: an unaligned split lost
                    # 32 bytes from the end of each part, and the read-back check refused it).
                    cuts = [int(round(s * 44100 / 16)) * 64 for s in points]
                    edges = [0] + cuts + [sizes[0]]
                    spans = list(zip(edges, edges[1:]))
                    if any(spans[k][1] - spans[k][0] < self.EDIT_MIN_PART * 176400 for k in v['kept']):
                        return {'error': 'A split position is too close to another one, or to the start or end of the track. Nothing was written.'}
                    plan = [[(srcs[0], 44 + a, b - a)] for k, (a, b) in enumerate(spans) if k in v['kept']]
                elif op == 'adjust':
                    srcs = self._edit_adjust(srcs, params, tmp, tell)
                    if srcs is None or self._edit_cancel:
                        return {'cancelled': True}
                    sizes = [wav_data_bytes(p) for p in srcs]
                    sizes = [n - n % 64 for n in sizes]                                  # a decoded ATRAC track may end part-way through a 64-byte unit
                    plan = [[(p, 44, n)] for p, n in zip(srcs, sizes)]                  # one new track for each original
                else:
                    plan = [[(p, 44, n) for p, n in zip(srcs, sizes)]]
            files = []
            for k, ranges in enumerate(plan):
                path = os.path.join(tmp, 'out%d.%s' % (k + 1, 'frames' if lossless else 'wav'))
                total = sum(r[2] for r in ranges)
                if not lossless and total % 64:
                    return {'error': 'The new audio is not a whole number of 64-byte units, which the disc would shorten. Nothing was written.'}
                digest = hashlib.sha256()
                with open(path, 'wb') as out:
                    if not lossless:
                        out.write(wav_header(total))
                    for p, start, length in ranges:
                        with open(p, 'rb') as f:
                            f.seek(start)
                            left = length
                            while left > 0:
                                if self._edit_cancel:
                                    return {'cancelled': True}
                                chunk = f.read(min(1 << 20, left))
                                if not chunk:
                                    return {'error': 'The audio read from the disc ended early. Nothing was written.'}
                                out.write(chunk)
                                digest.update(chunk)
                                left -= len(chunk)
                files.append({'path': path, 'sha': digest.hexdigest(), 'bytes': total})
                outs[k]['bytes'] = total
                outs[k]['seconds'] = (total // t0['frame']) * t0['spf'] / float(t0['rate']) if lossless else total / 176400.0
            if not prep:
                for p in srcs:
                    os.remove(p)

            if params.get('stage'):                                  # the new tracks do not fit next to the original: keep them on this PC for edit_staged_write
                res = self._edit_stage(files, outs, t0, lossless, mode, kind, tracks, op, bool(params.get('autoName')))
                if prep:
                    self._edit_prep_clear()
                return res

            place_first = t0['number'] + 1 if op == 'split' else max(t['number'] for t in tracks) + 1
            res = self._edit_commit(index, files, outs, t0, kind, lossless, count_before, tmp, tell, place_first, kept=True)
            if 'ok' not in res:
                return res
            if prep:
                self._edit_prep_clear()                                         # done with the editor's copy
            return dict(res, originals=[t['number'] for t in tracks], mode=mode)
        except RuntimeError as exc:
            return {'error': str(exc)}
        except OSError as exc:
            return {'error': 'A file operation failed: %s' % exc}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self._release_devices()

    def _edit_commit(self, index, files, outs, t0, kind, lossless, count_before, tmp, tell, place_first, kept):
        """WRITES TO THE DISC. Steps 3 to 6 of a split or combine: the room check, a snapshot of what must stay as it is, writing the new
        tracks, checking the disc, reading every new track back and comparing it byte for byte, then moving the new tracks to position
        `place_first` (None: they stay at the end). `files` are the PC copies of the new audio; `t0` has the ATRAC fields of the source
        (frame, codecId, ci, codec); `kept`: the original track(s) are still on the disc (it changes what the error messages say)."""
        note = 'Your original track(s) were not touched.' if kept else 'The saved copy of the new tracks is still on this PC, so you can write it again.'
        no_delete = ' Do not delete the original(s).' if kept else ''

        def reading(phase, n, count, label):
            return lambda m: tell(phase=phase, n=n, count=count, name=label, done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None

        # 3. the definitive room check, and a snapshot of what must stay exactly as it is
        if lossless:
            need = sum(-(-(f['bytes'] // t0['frame']) // ((16320 - 1) // t0['frame'])) for f in files) * 16384
            with self._lock:
                res = self._run_helper('plan', {'files': []})
            if 'error' in res:
                return {'error': res['error'] + ' Nothing was written.'}
            if not need < res['result']['freeBytes'] * 0.98:
                return {'error': 'There is not enough free space on the disc for the new track(s). Nothing was written.'}
        else:
            with self._lock:
                res = self._run_helper('plan', {'files': [f['path'] for f in files]})
            if 'error' in res:
                return {'error': res['error'] + ' Nothing was written.'}
            if any(i.get('error') for i in res['result']['files']) or not res['result']['fits']:
                return {'error': 'There is not enough free space on the disc for the new track(s). Nothing was written.'}
        if self._edit_cancel:
            return {'cancelled': True}
        try:
            with self._lock:
                fs = himd_fs.Fat16(himd_dev.Device(self._devices[index]))
                disc = himd_disc.Disc(fs)
                if disc.track_count() != count_before:
                    return {'error': 'The disc has changed since it was loaded. Reload it and try again. Nothing was written.'}
                before_samples, _ = self._audio_samples(fs, disc, range(count_before))
                before_info = [(tr['title'], tr['seconds'], tr['codec']) for tr in disc.tracks()]
                self._release_devices()
        except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError, IndexError) as exc:
            return {'error': 'Could not read the disc: %s Nothing was written.' % exc}

        # 4. write the new tracks (from here on there is no cancelling)
        self._drop_cache()
        tell(phase='writing', n=0, count=len(files), name=outs[0]['title'], done=0, total=0)
        if lossless:
            specs = [{'frames': f['path'], 'codecId': t0['codecId'], 'codecInfo': t0['ci'], 'title': o['title'], 'artist': o['artist'], 'album': o['album']}
                     for f, o in zip(files, outs)]
            cmd, cmd_args = 'upload_frames', {'files': specs}
        else:
            specs = [{'path': f['path'], 'title': o['title'], 'artist': o['artist'], 'album': o['album']} for f, o in zip(files, outs)]
            cmd, cmd_args = 'upload', {'files': specs, 'format': 'pcm'}
        with self._lock:
            res = self._run_helper(cmd, cmd_args, lambda m: tell(
                phase='writing', n=m.get('file', 0), count=len(files), name=m.get('name', ''), done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None)
        if 'error' in res:
            return {'error': 'Writing the new track(s) failed: %s Reload the disc to see what it holds. %s' % (res['error'], note)}

        # 5. check the disc: nothing else changed, and the new tracks are what was written
        tell(phase='checking', n=0, count=len(files), name='', done=0, total=0)
        want_codec = t0['codec'] if lossless else 'PCM'
        try:
            with self._lock:
                dev = self._reconnect(index)
                fs2 = himd_fs.Fat16(dev)
                disc2 = himd_disc.Disc(fs2)
                if disc2.track_count() != count_before + len(files):
                    raise himd_fs.FatError('the disc has %d tracks, expected %d' % (disc2.track_count(), count_before + len(files)))
                after_samples, _ = self._audio_samples(fs2, disc2, range(count_before))
                if after_samples != before_samples:
                    raise himd_fs.FatError('the audio of an existing track is no longer the same')
                for i, old in enumerate(before_info):
                    new = disc2.track(i)
                    if (new['title'], new['seconds'], new['codec']) != old:
                        raise himd_fs.FatError('track %d changed' % (i + 1))
                for k, o in enumerate(outs):
                    new = disc2.track(count_before + k)
                    if (new['title'] != o['title'] or new['codec'] != want_codec or abs(new['seconds'] - round(o['seconds'])) > 1
                            or (lossless and new['frame'] != t0['frame'])):
                        raise himd_fs.FatError('the new track “%s” is not as expected' % o['title'])
                self._release_devices()
        except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError) as exc:
            return {'error': 'The new track(s) were written, but checking the disc failed: %s. %s Reload the disc before doing anything else.' % (exc, note)}
        for k, (f, o) in enumerate(zip(files, outs)):                       # read them back and compare every byte
            tell(phase='verifying', n=k, count=len(files), name=o['title'], done=0, total=0)
            back = os.path.join(tmp, 'back%d.%s' % (k, 'oma' if lossless else 'wav'))
            with self._lock:
                res = self._run_helper('dump', {'index': count_before + k, 'out': back, 'exact': True, 'raw': lossless}, reading('verifying', k, len(files), o['title']))
            if 'error' in res:
                return {'error': 'The new track “%s” was written but could not be read back to check it: %s %s%s' % (o['title'], res['error'], note, no_delete)}
            digest = hashlib.sha256()
            skip = 96 if lossless else 44
            with open(back, 'rb') as bf:
                bf.seek(skip)
                for chunk in iter(lambda: bf.read(1 << 20), b''):
                    digest.update(chunk)
            same = os.path.getsize(back) - skip == f['bytes'] and digest.hexdigest() == f['sha']
            os.remove(back)
            if not same:
                return {'error': 'The new track “%s” does not match what was written. Do not trust it: delete it. %s' % (o['title'], note)}

        # 6. put the new tracks where they belong
        targets = [(place_first or count_before + 1) + k for k in range(len(files))]
        placed = True
        for k, to in enumerate(targets):
            frm = count_before + 1 + k
            if frm != to:
                r = self._edit(index, 'place new track %d at %d' % (frm, to), lambda d, frm=frm, to=to: d.move_track(frm - 1, to - 1))
                if 'error' in r:
                    placed = False
                    break
        return {'ok': True, 'new': targets if placed else [count_before + 1 + k for k in range(len(files))], 'placed': placed, 'verified': True}

    # -- split or combine when the new tracks do not fit next to the original ----------------------------------------------------
    # The new tracks are saved on this PC (SPLIT_DIR\stage, with a manifest, so they survive closing the program), the original is deleted
    # from the disc, and the saved tracks are written into the space that frees, then read back and compared byte for byte. Until that
    # has been verified the saved copy is never removed, so a failure part-way loses nothing: the parts can be written again.
    @staticmethod
    def _edit_staged_manifest():
        try:
            with open(os.path.join(SPLIT_DIR, 'manifest.json'), encoding='utf-8') as f:
                m = json.load(f)
            return m if m.get('complete') else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _edit_file_check(path, skip):
        """(bytes, sha256) of a saved part, without its WAV header when `skip` is 44."""
        digest, size = hashlib.sha256(), 0
        with open(path, 'rb') as f:
            f.seek(skip)
            for chunk in iter(lambda: f.read(1 << 20), b''):
                digest.update(chunk)
                size += len(chunk)
        return size, digest.hexdigest()

    def _edit_stage(self, files, outs, t0, lossless, mode, kind, tracks, op, auto_name=False):
        """Moves the freshly cut parts from the working folder into SPLIT_DIR\\stage and writes the manifest last."""
        stage = os.path.join(SPLIT_DIR, 'stage')
        shutil.rmtree(SPLIT_DIR, ignore_errors=True)
        os.makedirs(stage)
        entries = []
        for k, f in enumerate(files):
            name = 'part%02d.%s' % (k + 1, 'frames' if lossless else 'wav')
            shutil.move(f['path'], os.path.join(stage, name))
            entries.append({'file': name, 'sha': f['sha'], 'bytes': f['bytes']})
        manifest = {'complete': True, 'version': 1, 'when': datetime.datetime.now().isoformat(timespec='seconds'), 'op': op, 'kind': kind, 'lossless': lossless, 'autoName': bool(auto_name),     # autoName: Auto split & name went on to naming the new tracks once written
                    'mode': mode, 'sourceId': self._disc_key, 'info': {'frame': t0.get('frame'), 'codecId': t0.get('codecId'), 'ci': t0.get('ci'), 'codec': t0['codec']},
                    'originals': [{'number': t['number'], 'title': t['title'], 'seconds': t['seconds'], 'codec': t['codec'], 'blocks': t['blocks']} for t in tracks],
                    'outs': [{'title': o['title'], 'artist': o['artist'], 'album': o['album'], 'seconds': o['seconds']} for o in outs], 'files': entries}
        tmp = os.path.join(SPLIT_DIR, 'manifest.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=1)
        os.replace(tmp, os.path.join(SPLIT_DIR, 'manifest.json'))
        return {'staged': True, 'parts': len(files), 'folder': stage, 'bytes': sum(e['bytes'] for e in entries)}

    @staticmethod
    def _edit_need(m):
        """Bytes of disc space the saved parts need (whole 16 KB blocks, plus a little to spare)."""
        frame = (m.get('info') or {}).get('frame')
        if m['lossless']:
            blocks = sum(-(-(f['bytes'] // frame) // ((16320 - 1) // frame)) for f in m['files'])
        else:
            blocks = sum(-(-f['bytes'] // 16320) for f in m['files'])
        return blocks * 16384 + 2 * 16384

    def edit_staged_status(self):
        """The saved parts waiting on this PC (None when there are none), and how they relate to the disc that is loaded now."""
        m = self._edit_staged_manifest()
        if not m:
            return {'staged': None}
        by_number = {t['number']: t for t in self._tracks}
        present = all(by_number.get(o['number'], {}).get('title') == o['title'] and by_number.get(o['number'], {}).get('seconds') == o['seconds'] for o in m['originals'])
        need, free = self._edit_need(m), getattr(self, '_disc_free', 0)
        freed = sum(o['blocks'] for o in m['originals']) * 16384
        return {'staged': {'parts': len(m['files']), 'titles': [o['title'] for o in m['outs']], 'seconds': sum(o['seconds'] for o in m['outs']), 'when': m['when'],
                           'fitsNow': need < free * 0.98, 'fitsAfterDelete': need < (free + freed) * 0.98,
                           'originals': [{'number': o['number'], 'title': o['title'], 'seconds': o['seconds']} for o in m['originals']],
                           'sameDisc': bool(self._disc_key) and self._disc_key == m['sourceId'], 'originalsPresent': present,
                           'bytes': sum(f['bytes'] for f in m['files']), 'folder': os.path.join(SPLIT_DIR, 'stage'), 'autoName': bool(m.get('autoName'))}}

    def edit_staged_discard(self):
        shutil.rmtree(SPLIT_DIR, ignore_errors=True)
        return {'ok': not os.path.exists(SPLIT_DIR)}

    def edit_staged_write(self, index, delete_originals=False):
        """WRITES TO THE DISC. Writes the saved parts to the disc in the recorder. With `delete_originals` the original track(s) are deleted first
        (the disc must be the one they came from); that is what makes room. The saved copy is removed only after everything has been verified."""
        index = int(index)
        if self._is_netmd(index):
            return {'error': 'Split and combine work on Hi-MD discs only for now.'}
        m = self._edit_staged_manifest()
        if not m:
            return {'error': 'There are no saved parts to write.'}
        stage = os.path.join(SPLIT_DIR, 'stage')
        tell = self._edit_tell
        self._edit_cancel = False
        keep = ' The saved copy is still on this PC.'
        files = []
        tell(phase='copycheck', n=0, count=len(m['files']), name='', done=0, total=0)
        for f in m['files']:                                    # the PC copy must still be exactly what was cut
            p = os.path.join(stage, f['file'])
            if not os.path.isfile(p) or self._edit_file_check(p, 0 if m['lossless'] else 44) != (f['bytes'], f['sha']):
                return {'error': 'The saved parts on this PC are damaged or incomplete (%s). Discard them and split the track again.' % f['file']}
            files.append({'path': p, 'sha': f['sha'], 'bytes': f['bytes']})
        r = self.load(index)
        if 'error' in r:
            return {'error': r['error'] + keep}
        if r.get('mode') == 'netmd' or r.get('discState') != 'ok':
            return {'error': 'There is no readable Hi-MD disc in the recorder.' + keep}
        info, outs = m['info'], [dict(o) for o in m['outs']]
        for o, f in zip(outs, files):
            o['bytes'] = f['bytes']
        need = self._edit_need(m)
        free = r['disc']['free']
        same = bool(self._disc_key) and self._disc_key == m['sourceId']
        by_number = {t['number']: t for t in self._tracks}
        present = all(by_number.get(o['number'], {}).get('title') == o['title'] and by_number.get(o['number'], {}).get('seconds') == o['seconds'] for o in m['originals'])
        numbers = sorted(o['number'] for o in m['originals'])
        if delete_originals and need < free * 0.98:
            delete_originals = False                           # there is room next to the original now: it stays on the disc
        if delete_originals:
            if not (same and present):
                return {'error': 'This is not the disc the original track(s) were split from, or they are no longer on it. Insert that disc, or write the saved parts without deleting.' + keep}
            freed = sum(o['blocks'] for o in m['originals']) * 16384
            if not need < (free + freed) * 0.98:
                return {'error': 'Even with the original track(s) deleted there would not be enough room on the disc.' + keep}
            tell(phase='deleting', n=0, count=len(numbers), name=m['originals'][0]['title'], done=0, total=0)
            res = self.delete_tracks(index, numbers)
            if 'error' in res:
                return {'error': 'Deleting the original failed: %s%s' % (res['error'], keep)}
            r = self.load(index)
            if 'error' in r or r.get('discState') != 'ok':
                return {'error': 'The original was deleted, but the disc could not be read again: %s%s' % (r.get('error') or r.get('discState'), keep), 'originalDeleted': True}
            free = r['disc']['free']
            place_first = numbers[0]
        else:
            place_first = (numbers[-1] + 1) if (same and present) else (numbers[0] if same and numbers[0] <= len(self._tracks) + 1 else None)
        if not need < free * 0.98:
            return {'error': 'There is not enough free space on the disc: the new tracks need about %d MB and it has %d MB free.%s' % (need // 1000000, free // 1000000, keep),
                    'originalDeleted': bool(delete_originals)}
        count_before = len(self._tracks)
        t0 = dict(info, number=numbers[0])
        tmp = tempfile.mkdtemp(prefix='mdm-edit-')
        try:
            res = self._edit_commit(index, files, outs, t0, m['kind'], m['lossless'], count_before, tmp, tell, place_first, kept=False)
        except RuntimeError as exc:
            return {'error': str(exc) + keep, 'originalDeleted': bool(delete_originals)}
        except OSError as exc:
            return {'error': 'A file operation failed: %s.%s' % (exc, keep), 'originalDeleted': bool(delete_originals)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self._release_devices()
        if 'ok' not in res:
            return dict(res, originalDeleted=bool(delete_originals))
        shutil.rmtree(SPLIT_DIR, ignore_errors=True)          # everything verified: the saved copy has done its job
        return dict(res, originals=numbers, mode=m['mode'], deleted=bool(delete_originals), cleaned=not os.path.exists(SPLIT_DIR))
