"""Audio CDs: ripping a CD in this PC's drive onto the disc, and burning the disc's tracks to an audio CD. CdMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import base64
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading

import cdrip
from mdm_paths import HERE


class CdMixin:
    def _cd_init(self):
        self._cd_cancel = False
        self._cd_cover = None          # {'id', 'bytes'}: the cover fetched for the release the user is looking at

    # The CD is read with Windows' own disc calls (cdrip.py): every chunk twice, to temporary WAV files; the tracks are then written to the
    # disc by the same code as "Add tracks", with the titles / artist / album from CD-Text, MusicBrainz or what the user typed.
    @staticmethod
    def _cd_fail(exc):
        return {'error': str(exc)}

    def cd_drives(self):
        """The CD drives and whether an audio disc is in each."""
        try:
            out = []
            for letter in cdrip.drives():
                try:
                    toc = cdrip.read_toc(letter)
                    out.append({'letter': letter, 'ok': True, 'tracks': len(toc['tracks']), 'seconds': round(sum(t['seconds'] for t in toc['tracks']))})
                except cdrip.CdError as exc:
                    out.append({'letter': letter, 'ok': False, 'message': str(exc)})
            return {'drives': out}
        except Exception as exc:
            return self._cd_fail(exc)

    def cd_read(self, letter):
        """The disc's track list and, if it has them, the titles stored on it (CD-Text). Reads only."""
        try:
            toc = cdrip.read_toc(letter)
            try:
                text = cdrip.cdtext(letter)
            except cdrip.CdError:
                text = None
            return {'letter': letter, 'discId': cdrip.disc_id(toc), 'text': text,
                    'tracks': [{'num': t['num'], 'seconds': round(t['seconds'], 1)} for t in toc['tracks']]}
        except cdrip.CdError as exc:
            return self._cd_fail(exc)

    def cd_lookup(self, letter):
        """MusicBrainz releases for the disc in the drive (exact disc ID first, then by track lengths). Needs the internet."""
        try:
            return cdrip.lookup(cdrip.read_toc(letter))
        except cdrip.CdError as exc:
            return self._cd_fail(exc)

    def cd_search(self, artist, album, ntracks=None):
        try:
            return {'releases': cdrip.search((artist or '').strip(), (album or '').strip(), int(ntracks) if ntracks else None)}
        except (cdrip.CdError, ValueError) as exc:
            return self._cd_fail(exc)

    def cd_release(self, rid, letter=None):
        """One release with its track list, arranged for this disc."""
        try:
            toc = cdrip.read_toc(letter) if letter else None
            return {'release': cdrip.release(rid, cdrip.disc_id(toc) if toc else None, len(toc['tracks']) if toc else None,
                                             [t['seconds'] for t in toc['tracks']] if toc else None)}
        except cdrip.CdError as exc:
            return self._cd_fail(exc)

    def cd_cover(self, rid):
        """The front cover of a release, as a picture the page can show; kept so it can be stored on a Hi-MD disc."""
        data = cdrip.cover(rid)
        if not data:
            self._cd_cover = None
            return {'none': True}
        self._cd_cover = {'id': rid, 'bytes': data}
        mime = 'image/png' if data[:4] == b'\x89PNG' else 'image/jpeg'
        return {'data': 'data:%s;base64,%s' % (mime, base64.b64encode(data).decode()), 'bytes': len(data)}

    def cd_pick_cover(self):
        """A picture file the user chooses, to store as a Hi-MD disc's picture once the CD has been ripped (kept like the online cover)."""
        path = self.pick_image().get('path')
        if not path:
            return {'cancelled': True}
        try:
            if os.path.getsize(path) > 20 * 1000 * 1000:
                return {'error': 'That picture is too large (over 20 MB).'}
            with open(path, 'rb') as f:
                data = f.read()
        except OSError as exc:
            return {'error': 'The picture could not be read: %s' % exc}
        self._cd_cover = {'id': 'file', 'bytes': data}
        mime = ('image/png' if data[:4] == b'\x89PNG' else 'image/gif' if data[:3] == b'GIF' else 'image/bmp' if data[:2] == b'BM'
                else 'image/webp' if data[8:12] == b'WEBP' else 'image/jpeg')
        return {'data': 'data:%s;base64,%s' % (mime, base64.b64encode(data).decode()), 'bytes': len(data)}

    def cd_cancel(self):
        self._cd_cancel = True
        return {'ok': True}

    def cd_rip_add(self, index, letter, tracks, fmt='auto', mp3_kbps=192, disc_title='', cover_id=None):
        """WRITES TO THE DISC. `tracks`: [{num, title, artist, album}] of the CD tracks to rip, in the order to add them. `fmt`: as for
        upload() (Hi-MD: auto / pcm / mp3 / lp2 / lp4 / hisp / hilp / at3p; standard disc: sp / lp2 / lp4). disc_title: set as the disc's name afterwards
        (if not empty). cover_id: store the cover fetched for that release as the picture of a Hi-MD disc."""
        index = int(index)
        netmd = self._is_netmd(index)
        fmt = (fmt if fmt in ('sp', 'lp2', 'lp4') else 'sp') if netmd else (fmt if fmt in ('auto', 'pcm', 'mp3', 'lp2', 'lp4', 'at3p', 'hisp', 'hilp') else 'auto')
        if not tracks:
            return {'error': 'Choose at least one track to rip.'}
        tell = lambda **m: self._window and self._window.evaluate_js('window.onCdProgress && window.onCdProgress(%s)' % json.dumps(m))
        try:
            toc = cdrip.read_toc(letter)
        except cdrip.CdError as exc:
            return self._cd_fail(exc)
        by_num = {t['num']: t for t in toc['tracks']}
        if any(int(t['num']) not in by_num for t in tracks):
            return {'error': 'The disc in the drive is not the one these tracks were chosen from. Open the CD again.'}
        seconds = sum(by_num[int(t['num'])]['seconds'] for t in tracks)
        tmp = tempfile.mkdtemp(prefix='mdm-cd-')
        self._cd_cancel = False
        try:
            if shutil.disk_usage(tmp).free < seconds * 176400 * 1.15 + 100 * 1000 * 1000:
                return {'error': 'There is not enough free space on this PC’s temporary drive for the ripped tracks (about %d MB).' % int(seconds * 176400 / 1e6)}
            files, stats = [], {'retries': 0, 'suspect': 0, 'bad': 0}
            for i, t in enumerate(tracks):
                num = int(t['num'])
                label = (t.get('title') or '').strip() or 'Track %d' % num
                tell(phase='ripping', n=i, count=len(tracks), name=label, done=0, total=0)
                wav = os.path.join(tmp, 'track%02d.wav' % num)
                r = cdrip.rip_track(letter, toc, num, wav, progress=lambda d, tot, i=i, label=label: tell(
                    phase='ripping', n=i, count=len(tracks), name=label, done=d, total=tot), cancel=lambda: self._cd_cancel)
                if r is None:
                    return {'cancelled': True}
                for k in stats:
                    stats[k] += r[k]
                files.append({'path': wav, 'title': label, 'artist': (t.get('artist') or '').strip(), 'album': (t.get('album') or '').strip()})
            tell(phase='writing', n=0, count=len(files), name='', done=0, total=0)
            res = self.upload(files, fmt, mp3_kbps)
            if 'error' in res:
                return {'error': 'The CD was ripped, but writing to the disc failed: %s' % res['error'], 'rip': stats}
            notes = []
            title = (disc_title or '').strip()
            if title or (cover_id and not netmd):
                try:
                    if not netmd:
                        self._reconnect(index)                  # a secure session can leave the recorder busy for a few seconds
                        self._release_devices()
                    if title:
                        r = self.rename_disc(index, title)
                        if 'error' in r:
                            notes.append('The disc name could not be set: %s' % r['error'])
                    if cover_id and not netmd and self._cd_cover and self._cd_cover['id'] == cover_id:
                        pic = os.path.join(tmp, 'cover.img')
                        with open(pic, 'wb') as f:
                            f.write(self._cd_cover['bytes'])
                        prep = self.cover_prepare(pic)
                        r = prep if 'error' in prep else self.cover_set(index, prep['tmp'])
                        if 'error' in r:
                            notes.append('The cover could not be stored: %s' % r['error'])
                except Exception as exc:
                    notes.append('The disc name or cover could not be set: %s' % exc)
            self._release_devices()
            return {'ok': True, 'added': len(files), 'rip': stats, 'notes': notes, 'seconds': round(seconds)}
        except cdrip.CdError as exc:
            return self._cd_fail(exc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # -- burning an audio CD from the tracks of the disc ---------------------------------------
    # Windows' own burner (IMAPI2, track-at-once) through helper\cdburn_plain.ps1: 2-second gaps, no CD-Text. Proven on real CD-Rs. Every call
    # runs in its own process with a time limit, because a drive that stops answering must never freeze the program.
    def _burn_ps(self, args, timeout, on_line=None):
        script = os.path.join(HERE, 'helper', 'cdburn_plain.ps1')
        if not os.path.exists(script):
            return {'error': 'The burn helper is missing (%s).' % script}
        proc = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script] + args,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        timed_out = []
        timer = threading.Timer(timeout, lambda: (timed_out.append(1), proc.kill()))
        timer.start()
        lines = []
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    lines.append(line)
                    if on_line:
                        on_line(line)
            proc.wait()
        finally:
            timer.cancel()
        if timed_out:
            return {'error': 'The disc drive did not answer in time. Take the disc out and put it back, then try again.', 'lines': lines}
        errors = [l[6:] for l in lines if l.startswith('ERROR ')]
        if errors:
            return {'error': errors[-1], 'lines': lines}
        if proc.returncode or 'DONE' not in lines:
            return {'error': 'The disc drive stopped without finishing.', 'lines': lines}
        return {'lines': lines}

    def cd_burn_drives(self):
        """The disc writers and the disc in each (type, blank or not, free minutes). Writes nothing."""
        res = self._burn_ps(['-List'], 60)
        if 'error' in res:
            return {'error': res['error']}
        drives, by_letter = [], {}
        for line in res['lines']:
            if line.startswith('DRIVE '):
                letters, name = line[6:].split('|', 1)
                d = {'letter': letters.split(',')[0], 'name': name, 'disc': None}
                drives.append(d)
                by_letter[letters] = d
            elif line.startswith('DISC '):
                f = line[5:].split('|')
                letters, kind, blank, minutes, rewritable, free = f[:6]
                mounted = (f[6] == 'True') if len(f) > 6 else (kind == 'DVD-RAM')
                if letters in by_letter:
                    by_letter[letters]['disc'] = {'type': kind, 'blank': blank == 'True', 'minutes': float(minutes), 'rewritable': rewritable == 'True',
                                                  'freeBytes': int(float(free)), 'mounted': mounted}
        return {'drives': drives}

    def cd_burn_erase(self, letter):
        """WRITES TO THE DISC. Quick-erases the rewritable disc in the drive."""
        res = self._burn_ps(['-Drive', letter, '-Erase'], 900)
        return {'error': res['error']} if 'error' in res else {'ok': True}

    def cd_burn_run(self, index, numbers, letter):
        """Reads the tracks from the recorder's disc (like Save to PC) and burns them, in order, to the blank CD-R / CD-RW in `letter`.
        Nothing is burned unless every track could be read: a CD-R can only be written once."""
        tell = lambda **m: self._window and self._window.evaluate_js('window.onCdBurnProgress && window.onCdBurnProgress(%s)' % json.dumps(m))
        check = self._burn_ps(['-Drive', letter, '-Check'], 60)
        if 'error' in check:
            return {'error': check['error']}
        tmp = tempfile.mkdtemp(prefix='mdm-burn-')
        try:
            saved = self.save_tracks(index, numbers, tmp, 'wav')
            if 'error' in saved:
                return {'error': saved['error']}
            if saved.get('cancelled'):
                return {'cancelled': True}
            if saved['failed']:
                return {'error': 'Nothing was burned, because %d %s could not be read: %s' % (
                    len(saved['failed']), 'track' if len(saved['failed']) == 1 else 'tracks',
                    '; '.join('%s (%s)' % (f['title'], f['error']) for f in saved['failed'][:3]))}
            files = [s['file'] for s in sorted(saved['saved'], key=lambda s: s['number'])]
            if not files:
                return {'error': 'There are no tracks to burn.'}
            listing = os.path.join(tmp, 'tracks.json')
            with open(listing, 'w', encoding='utf-8') as f:
                json.dump(files, f)
            tell(phase='burning', n=0, count=len(files))

            def on_line(line):
                m = re.match(r'TRACK (\d+) of (\d+)', line)
                if m:
                    tell(phase='burning', n=int(m.group(1)) - 1, count=int(m.group(2)))
            res = self._burn_ps(['-Drive', letter, '-Burn', '-ListFile', listing, '-Ffmpeg', os.path.join(HERE, 'runtime', 'ffmpeg.exe')], 2400, on_line)
            if 'error' in res:
                return {'error': res['error']}
            return {'ok': True, 'tracks': len(files)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def cd_data_run(self, index, numbers, letter, fmt='flac', mp3_quality='v0', label='', cover=''):
        """Reads the tracks from the recorder's disc (like Save to PC), as FLAC / WAV / MP3 files plus a TRACKS.CSV list, the disc picture
        (cover.jpg, from the `cover` data URL) and each track's lyrics (.lrc / .txt beside it), and puts them on the
        data disc in `letter`: burnt to a blank CD / DVD / Blu-ray, or copied into a folder on a formatted DVD-RAM. Nothing is written unless every
        track could be read."""
        tell = lambda **m: self._window and self._window.evaluate_js('window.onCdBurnProgress && window.onCdBurnProgress(%s)' % json.dumps(m))
        fmt = fmt if fmt in ('flac', 'wav', 'mp3') else 'flac'
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (label or '').strip()).strip(' .')[:32] or 'MiniDisc'
        check = self._burn_ps(['-Drive', letter, '-Check'], 60)
        if 'error' in check:
            return {'error': check['error']}
        tmp = tempfile.mkdtemp(prefix='mdm-data-')
        try:
            folder = os.path.join(tmp, 'files')
            os.makedirs(folder)
            saved = self.save_tracks(index, numbers, folder, fmt, False, mp3_quality)
            if 'error' in saved:
                return {'error': saved['error']}
            if saved.get('cancelled'):
                return {'cancelled': True}
            if saved['failed']:
                return {'error': 'Nothing was written, because %d %s could not be read: %s' % (
                    len(saved['failed']), 'track' if len(saved['failed']) == 1 else 'tracks',
                    '; '.join('%s (%s)' % (f['title'], f['error']) for f in saved['failed'][:3]))}
            wanted = {int(n) for n in numbers}
            with open(os.path.join(folder, 'TRACKS.CSV'), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['#', 'Title', 'Artist', 'Album', 'Length (s)'])
                for t in self._tracks:
                    if t['number'] in wanted:
                        w.writerow([t['number'], t['title'], t['artist'], t['album'], t['seconds']])
            extras = []
            if cover and cover.startswith('data:image') and ',' in cover:       # the disc picture, as shown in the page
                try:
                    with open(os.path.join(folder, 'cover.jpg'), 'wb') as f:
                        f.write(base64.b64decode(cover.split(',', 1)[1]))
                    extras.append('cover.jpg')
                except (ValueError, OSError):
                    pass
            lyr = 0
            try:
                import lyrics as _ly
                store = self._ly_read()
                by_number = {t['number']: t for t in self._tracks}
                for s in saved['saved']:
                    t = by_number.get(s['number'])
                    e = self._ly_find(store, t['title'], t['artist'], t['seconds']) if t else None
                    if not e or not e.get('lrc'):
                        continue
                    stem = os.path.splitext(s['file'])[0]
                    if e.get('synced'):
                        off = float(e.get('offset') or 0)
                        lines = []
                        for sec, text in _ly.parse_lrc(e['lrc']):
                            x = max(0.0, sec + off)
                            lines.append('[%02d:%05.2f]%s' % (int(x // 60), x % 60, text))
                        body, ext = '\n'.join(lines) + '\n', '.lrc'
                    else:
                        body, ext = e['lrc'], '.txt'
                    with open(stem + ext, 'w', encoding='utf-8-sig' if ext == '.txt' else 'utf-8', newline='\n') as f:
                        f.write(body)
                    lyr += 1
            except Exception:
                pass                                                            # lyrics are a bonus; never stop the save for them
            tell(phase='burning', n=0, count=1, data=True)
            res = self._burn_ps(['-Drive', letter, '-Data', '-Folder', folder, '-Label', name], 3600)
            if 'error' in res:
                return {'error': res['error']}
            return {'ok': True, 'tracks': len(saved['saved']), 'cover': bool(extras), 'lyrics': lyr}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
