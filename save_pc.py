"""Saving the disc's tracks to this PC as FLAC / WAV / MP3 / .oma files. SavePcMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import json
import os
import re
import shutil
import subprocess
import tempfile

import webview
from mdm_paths import COPIES_DIR, HERE, NETMD_HELPER


class SavePcMixin:
    def _save_init(self):
        self._save_cancel = False
        self._last_save_dir = None

    # Hi-MD discs: read through himd_helper.js `dump` (PCM is decrypted on the PC, ATRAC is decoded or kept as it is, MP3 as it is).
    # Standard discs: the app's saved copy if it has one, else the recorder sends the track back (MZ-RH1 only).
    def pick_folder(self):
        kind = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or webview.FOLDER_DIALOG
        start = getattr(self, '_last_save_dir', None) or os.path.join(os.path.expanduser('~'), 'Music')
        paths = self._window.create_file_dialog(kind, directory=start if os.path.isdir(start) else '')
        if not paths:
            return {'cancelled': True}
        folder = paths if isinstance(paths, str) else paths[0]
        self._last_save_dir = folder
        return {'folder': folder}

    def save_plan(self, index, numbers):
        """What saving each of these tracks would do. Reads nothing from the recorder."""
        wanted = {int(n) for n in numbers}
        out = []
        for t in self._tracks:
            if t['number'] not in wanted:
                continue
            item = {'number': t['number'], 'title': t['title'], 'codec': t['codec'], 'seconds': t['seconds'], 'ok': True}
            if self._is_netmd(index):
                if self._find_copy(t['title'], t['seconds'], codec=t['codec']):
                    item['how'] = 'saved copy'
                elif self._can_fetch(index):
                    item['how'] = 'sent back by the recorder'
                elif self._exploit_possible(index):
                    item.update(ok=False, exploit=True, how='experimental download',
                                reason='no saved copy, and this recorder cannot send audio back by itself')
                else:
                    item.update(ok=False, reason='This recorder cannot send audio back, and the app has no saved copy of this track.')
            else:
                if t['codec'] in ('PCM', 'MP3', 'A3+', 'AT3'):
                    item['how'] = 'read from the disc'
                    item['atrac'] = t['codec'] in ('A3+', 'AT3')
                else:
                    item.update(ok=False, reason='This track type cannot be read.')
            out.append(item)
        return {'tracks': out, 'netmd': self._is_netmd(index)}

    @staticmethod
    def _file_stem(number, title):
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (title or '').strip()).strip(' .')
        if not clean or clean == '(untitled)':
            clean = 'Track %d' % number
        return ('%02d - %s' % (number, clean))[:120].rstrip(' .')

    @staticmethod
    def _unique(path):
        base, ext = os.path.splitext(path)
        n, candidate = 2, path
        while os.path.exists(candidate):
            candidate = '%s (%d)%s' % (base, n, ext)
            n += 1
        return candidate

    @staticmethod
    def _ffmpeg(args):
        exe = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
        if not os.path.exists(exe):
            raise RuntimeError('The bundled decoder is missing (%s).' % exe)
        r = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-y'] + args, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode:
            raise RuntimeError('Could not convert the audio: %s' % (r.stderr.strip()[-300:] or 'unknown error'))

    def open_folder(self, path):
        if path and os.path.isdir(path):
            os.startfile(path)
        return {'ok': True}

    def save_cancel(self):
        self._save_cancel = True
        return self._stop_transfer()

    def save_tracks(self, index, numbers, folder, fmt='flac', keep_atrac=False, mp3_quality='v0', use_exploit=False):
        """Saves the tracks to `folder` as FLAC, WAV or MP3. An MP3 track already on a Hi-MD disc is saved as it is when MP3 is
        chosen (never re-encoded). With keep_atrac, Hi-MD ATRAC tracks keep their original ATRAC data as .oma. With use_exploit, tracks
        on a standard disc that have no saved copy are read from a recorder that cannot send audio back (MZ-NH700) with the experimental
        firmware-patch download. Reads the disc only. Returns what was saved and what could not be."""
        fmt = fmt if fmt in ('flac', 'wav', 'mp3') else 'flac'
        if not folder or not os.path.isdir(folder):
            return {'error': 'Choose a folder to save into.'}
        wanted = sorted({int(n) for n in numbers})
        tracks = [t for t in self._tracks if t['number'] in wanted]
        if not tracks:
            return {'error': 'There are no tracks to save.'}
        netmd = self._is_netmd(index)
        self._save_cancel = False
        saved, failed = [], []
        used_exploit = False
        tmp = tempfile.mkdtemp(prefix='mdm-save-')

        def tell(**msg):
            if self._window:
                try:
                    self._window.evaluate_js('window.onSaveProgress && window.onSaveProgress(%s)' % json.dumps(msg))
                except Exception:
                    pass

        try:
            for n, t in enumerate(tracks):
                if self._save_cancel:
                    break
                label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
                tell(n=n, count=len(tracks), name=label, phase='reading', done=0, total=0)
                work = os.path.join(tmp, 'track%d' % t['number'])
                tags = []
                for key, val in (('title', t['title'] if t['title'] != '(untitled)' else ''), ('artist', t.get('artist')), ('album', t.get('album'))):
                    if val:
                        tags += ['-metadata', '%s=%s' % (key, val)]
                tags += ['-metadata', 'track=%d' % t['number']]
                try:
                    src, ext = None, None
                    if netmd:
                        copy = self._find_copy(t['title'], t['seconds'], codec=t['codec'])
                        if copy:
                            src, ext = os.path.join(COPIES_DIR, copy['id'] + '.flac'), 'flac'
                        elif self._can_fetch(index):
                            src = work + '.wav'
                            with self._lock:
                                res = self._run_helper('fetch', {'index': t['number'] - 1, 'out': src}, lambda m: tell(
                                    n=n, count=len(tracks), name=label, phase='reading', done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None,
                                    helper=NETMD_HELPER)
                            if 'error' in res:
                                raise RuntimeError(res['error'])
                            ext = 'wav'
                        elif use_exploit and self._exploit_possible(index):
                            src = work + '.wav'
                            used_exploit = True
                            with self._lock:
                                res = self._run_helper('fetch', {'index': t['number'] - 1, 'out': src, 'exploit': True}, lambda m: tell(
                                    n=n, count=len(tracks), name=label, phase='reading', done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None,
                                    helper=NETMD_HELPER)
                            if 'error' in res:
                                raise RuntimeError('Saving was cancelled.' if self._save_cancel else res['error'])
                            ext = 'wav'
                        else:
                            raise RuntimeError('This recorder cannot send audio back, and the app has no saved copy of this track.')
                    else:
                        atrac = t['codec'] in ('A3+', 'AT3')
                        raw = bool(keep_atrac and atrac)
                        ext = 'oma' if raw else ('mp3' if t['codec'] == 'MP3' else 'wav')
                        src = work + '.' + ext
                        with self._lock:
                            res = self._run_helper('dump', {'index': t['number'] - 1, 'out': src, 'exact': True, 'raw': raw}, lambda m: tell(
                                n=n, count=len(tracks), name=label, phase='reading', done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None)
                        if 'error' in res:
                            raise RuntimeError('Saving was cancelled.' if self._save_cancel else res['error'])
                    if self._save_cancel:
                        break
                    keep_as_is = ext == 'oma' or (ext == 'mp3' and fmt == 'mp3')     # original ATRAC data, or an MP3 that is already MP3
                    final_ext = ext if keep_as_is else fmt
                    dest = self._unique(os.path.join(folder, self._file_stem(t['number'], t['title']) + '.' + final_ext))
                    tell(n=n, count=len(tracks), name=label, phase='writing', done=0, total=0)
                    if keep_as_is:
                        shutil.move(src, dest)                           # kept exactly as the disc holds it
                    else:
                        if final_ext == 'flac':
                            codec = ['-c:a', 'flac']
                        elif final_ext == 'wav':
                            codec = ['-c:a', 'pcm_s16le']
                        else:                                            # MP3: VBR V0 (about 245 kbps) or constant 320 kbps
                            codec = ['-c:a', 'libmp3lame'] + (['-b:a', '320k'] if mp3_quality == '320' else ['-q:a', '0']) + ['-id3v2_version', '3']
                        self._ffmpeg(['-i', src, '-vn', '-map_metadata', '-1'] + tags + codec + [dest])
                    saved.append({'number': t['number'], 'file': dest})
                except (RuntimeError, OSError) as exc:
                    if self._save_cancel:
                        break                                            # stopped on request: not a failure
                    failed.append({'number': t['number'], 'title': label, 'error': str(exc)})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return {'saved': saved, 'failed': failed, 'cancelled': bool(self._save_cancel), 'folder': folder, 'exploitUsed': used_exploit}
