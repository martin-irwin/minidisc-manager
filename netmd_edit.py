"""Split, combine and trim on a standard disc (SP / LP2 / LP4). NetMdEditMixin is mixed into himd_app.Api; edit_tracks.EditMixin sends a
standard disc here (edit_prepare / edit_plan / edit_run) and the page uses the same split editor and sheets as for a Hi-MD disc.

A standard disc has no command to cut or join a track, so the track is read to this PC, cut or joined there (to the sample), and written
back as NEW tracks, which are then moved next to the originals. The originals are not touched: the page offers to delete them afterwards.
  - SP: the recorder only takes raw sound and encodes it itself, so the audio is decoded and encoded once more (one generation of loss).
  - LP2 / LP4: written the way "Add tracks" writes them (encoded on the PC), so also one more generation.
Reading a track back works on an MZ-RH1 directly, on a Hi-MD recorder such as the MZ-NH700 with the opt-in experimental download (one track
per run), or from the copy this app saved when it added the track."""
import os
import secrets
import shutil
import tempfile
import time

from mdm_common import wav_data_bytes, wav_header
from mdm_paths import COPIES_DIR, NETMD_HELPER, RESCUE_DIR

NETMD_CODECS = ('SP', 'LP2', 'LP4')                  # stereo only: a mono track would come back as stereo


class NetMdEditMixin:
    _fresh = False                                   # True: read tracks from the disc even when the app has a saved copy (set by each call that reads)
    _kept = False                                    # True when the last patched read was kept as a saved copy

    def _netmd_edit_ok(self, t):
        """Can this standard-disc track be split or combined? (stereo SP / LP2 / LP4)"""
        return t.get('codec') in NETMD_CODECS

    def _netmd_can_read(self, index, t, use_exploit):
        """How this track can be read back to the PC: 'copy' (the app saved it), 'direct' (an MZ-RH1), 'patch' (opt-in download), or None."""
        if not self._fresh and self._find_copy(t['title'], t['seconds'], codec=t['codec']):
            return 'copy'
        if self._can_fetch(index):
            return 'direct'
        if use_exploit and self._exploit_possible(index):
            return 'patch'
        return None

    def _netmd_read_wav(self, index, t, folder, use_exploit, n, count):
        """The track as a plain 44-byte-header 16-bit stereo WAV in `folder`. Returns (path, None), or (None, error) / (None, 'cancelled')."""
        label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
        tell = self._edit_tell
        how = self._netmd_can_read(index, t, use_exploit)
        if how is None:
            why = ('This recorder can only send audio back with the experimental download: allow it, then try again.' if self._exploit_possible(index)
                   else 'This recorder cannot send audio back, and the app has no saved copy of “%s”.' % label)
            return None, why
        tell(phase='reading', n=n, count=count, name=label, done=0, total=0)
        if how == 'copy':
            src = os.path.join(COPIES_DIR, self._find_copy(t['title'], t['seconds'], codec=t['codec'])['id'] + '.flac')
        else:
            src = os.path.join(folder, 'raw%d.wav' % t['number'])
            args = {'index': t['number'] - 1, 'out': src}
            if how == 'patch':
                args['exploit'] = True
            progress = lambda m: tell(phase='reading', n=n, count=count, name=label, done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None
            for attempt in (1, 2):                                  # the recorder may need a moment after the last read: one more try
                if attempt > 1:
                    time.sleep(12 if how == 'patch' else 4)
                with self._lock:
                    res = self._run_helper('fetch', args, progress, helper=NETMD_HELPER)
                if 'error' not in res or self._edit_cancel:
                    break
            if self._edit_cancel:
                return None, 'cancelled'
            if 'error' in res:
                return None, 'Reading “%s” from the recorder failed: %s' % (label, res['error'])
        if how == 'patch':                                              # a slow patched read: keep it as the track's saved copy (if it is the right length) for next time
            heard = self._audio_seconds(src)
            if heard and abs(heard - t['seconds']) <= max(3.0, t['seconds'] * 0.02) and self._keep_copy(src, t, replace=self._fresh):
                self._kept = True
        wav = os.path.join(folder, 'track%d.wav' % t['number'])
        try:
            self._ffmpeg(['-i', src, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', wav])
        except RuntimeError as exc:
            return None, str(exc)
        finally:
            if how != 'copy':
                try:
                    os.remove(src)
                except OSError:
                    pass
        return wav, None

    # -- the split editor's copy of a track -------------------------------------------------------------------------------
    def _netmd_edit_prepare(self, index, number, use_exploit=False, fresh=False):
        self._fresh = bool(fresh)
        t = next((x for x in self._tracks if x['number'] == int(number)), None)
        if t is None:
            return {'error': 'That track is no longer on the disc. Reload it.'}
        if not self._netmd_edit_ok(t):
            return {'error': 'Only stereo SP, LP2 or LP4 tracks can be split.'}
        if self._netmd_can_read(index, t, use_exploit) is None:
            if self._exploit_possible(index):
                return {'needPatch': True, 'error': 'This recorder can only send audio back with the experimental download.'}
            return {'error': 'This recorder cannot send audio back, and the app has no saved copy of this track, so it cannot be split.'}
        self._edit_prep_clear()
        self._edit_cancel = False
        tmp = tempfile.mkdtemp(prefix='mdm-split-')
        if shutil.disk_usage(tmp).free < t['seconds'] * 176400 * 2.2 + 50 * 1000 * 1000:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'error': 'There is not enough free space on this PC’s temporary drive to hold the track.'}
        self._kept = False
        wav, err = self._netmd_read_wav(index, t, tmp, use_exploit, 0, 1)
        if err:
            shutil.rmtree(tmp, ignore_errors=True)
            self._release_devices()
            return {'cancelled': True} if err == 'cancelled' else {'error': err}
        try:
            nbytes = wav_data_bytes(wav)
            peaks, top = self._peaks(wav, nbytes)
        except (RuntimeError, OSError) as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'error': str(exc)}
        finally:
            self._release_devices()
        name = 'split-%s.wav' % secrets.token_hex(6)
        self._ensure_server()
        self._streams[name] = {'key': name, 'name': name, 'format': 'wav', 'path': wav, 'total': 44 + nbytes, 'mime': 'audio/wav',
                               'done': True, 'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
        self._edit_prep = {'number': t['number'], 'path': wav, 'dir': tmp, 'name': name, 'kind': 'pcm', 'oma': None, 'frames': nbytes // 4, 'top': top}
        return {'url': 'http://127.0.0.1:%d/%s/%s' % (self._port, self._token, name), 'seconds': nbytes / 176400.0, 'peaks': peaks, 'name': name,
                'kind': 'pcm', 'codec': t['codec'], 'frameSeconds': 0.0, 'exploitUsed': self._kept or self._netmd_can_read(index, t, use_exploit) == 'patch', 'kept': self._kept}

    # -- checking what was asked for ----------------------------------------------------------------------------------------
    def _netmd_edit_validate(self, index, op, numbers, params, use_exploit):
        self._fresh = bool(params.get('fresh'))
        order =list(dict.fromkeys(int(n) for n in numbers))
        by_number = {t['number']: t for t in self._tracks}
        tracks = [by_number[n] for n in order if n in by_number]
        if not tracks or len(tracks) != len(order):
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}
        if not all(self._netmd_edit_ok(t) for t in tracks):
            return {'error': 'Only stereo SP, LP2 or LP4 tracks can be split or combined.'}
        if len({t['codec'] for t in tracks}) != 1:
            return {'error': 'These tracks are in different recording modes (SP, LP2, LP4), so they cannot be joined. Combine tracks of one mode.'}
        codec = tracks[0]['codec']
        name = lambda t: t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
        prep = self._edit_prep if (op == 'split' and self._edit_prep and params.get('prepared') == self._edit_prep.get('name')) else None
        unreadable = [t for t in tracks if self._netmd_can_read(index, t, use_exploit) is None]
        if unreadable and not prep:
            return {'error': ('This recorder can only send audio back with the experimental download: allow it, then try again.' if self._exploit_possible(index)
                              else 'This recorder cannot send audio back, and the app has no saved copy of “%s”.' % name(unreadable[0]))}
        if not prep and self._exploit_possible(index) and not self._can_fetch(index) and sum(1 for t in tracks if self._netmd_can_read(index, t, use_exploit) == 'patch') > 1:
            return {'error': 'On this recorder the experimental download reads one track at a time. Do this with one track, or with tracks the app saved copies of.'}
        if op == 'split':
            if len(tracks) != 1:
                return {'error': 'Choose one track to split.'}
            t = tracks[0]
            raw = params.get('points')
            try:
                points = sorted(float(x) for x in (raw if raw is not None else [params.get('seconds')]))
            except (TypeError, ValueError):
                return {'error': 'Choose where to split the track.'}
            if not points:
                return {'error': 'Choose where to split the track.'}
            if len(points) > self.EDIT_MAX_POINTS:
                return {'error': 'A track can be split at up to %d places at once.' % self.EDIT_MAX_POINTS}
            total = float(prep['frames']) / 44100.0 if prep else float(t['seconds'])
            edges = [0.0] + points + [total]
            parts = len(edges) - 1
            skip = [bool(x) for x in (params.get('skip') or [])][:parts]
            skip += [False] * (parts - len(skip))
            if all(skip):
                return {'error': 'Keep at least one part.'}
            if any(b - a < (0.0 if s else self.EDIT_MIN_PART) for (a, b), s in zip(zip(edges, edges[1:]), skip)):
                return {'error': 'Each part must be at least %d seconds long.' % self.EDIT_MIN_PART}
            titles = [str(x).strip() for x in (params.get('titles') or [])]
            titles += [''] * (parts - len(titles))
            kept = [k for k in range(parts) if not skip[k]]
            outs = [{'title': titles[k] or (name(t) if len(kept) == 1 else '%s (%d)' % (name(t), i + 1)), 'seconds': edges[k + 1] - edges[k]} for i, k in enumerate(kept)]
        elif op == 'combine':
            if len(tracks) < 2:
                return {'error': 'Choose at least two tracks to combine.'}
            kept = [0]
            outs = [{'title': str(params.get('title') or '').strip() or name(tracks[0]), 'seconds': float(sum(t['seconds'] for t in tracks))}]
        else:
            return {'error': 'Unknown edit.'}
        if any(o['seconds'] > 80 * 60 * (1 if codec == 'SP' else 2 if codec == 'LP2' else 4) for o in outs):
            return {'error': 'The new track would be longer than a disc can hold in this mode.'}
        return {'tracks': tracks, 'outs': outs, 'kept': kept, 'fmt': codec.lower(), 'codec': codec, 'prep': prep}

    def _netmd_edit_plan(self, index, op, numbers, params):
        params = params or {}
        use_exploit = bool(params.get('useExploit'))
        v = self._netmd_edit_validate(index, op, numbers, params, use_exploit)
        if 'error' in v:
            return v
        with self._lock:
            res = self._run_helper('plan', {'files': []}, helper=NETMD_HELPER)
        if 'error' in res:
            return res
        p = res['result']
        left = p['leftSeconds'][v['fmt']]                                     # seconds of audio in this mode the disc can still take
        need = sum(o['seconds'] for o in v['outs'])
        originals = sum(t['seconds'] for t in v['tracks'])
        src_bytes = sum(t['seconds'] * 176400 for t in v['tracks'])
        tmp_need = int(src_bytes * 2.2) + 50 * 1000 * 1000
        tmp_free = shutil.disk_usage(tempfile.gettempdir()).free
        return {'netmd': True, 'outs': [{'title': o['title'], 'seconds': o['seconds']} for o in v['outs']], 'needSeconds': need, 'freeSeconds': left,
                'originalsSeconds': originals, 'fits': need * 1.01 + 2 < left and not p.get('writeProtected'), 'writeProtected': bool(p.get('writeProtected')),
                'fitsAfterDelete': self._delete_first_need(v['outs'], v['fmt']) < left + originals, 'tmpNeed': tmp_need, 'tmpFree': tmp_free, 'tmpFits': tmp_free > tmp_need,
                'kind': 'pcm', 'mode': 'pcm', 'codec': v['codec']}

    # -- doing it -------------------------------------------------------------------------------------------------------
    @staticmethod
    def _delete_first_need(outs, fmt):
        """Seconds of free time needed once the original is deleted: the audio itself, a second per track for the disc's block rounding, and a little more
        for LP2 / LP4 (encoded on the PC)."""
        total = sum(o['seconds'] for o in outs)
        return total + len(outs) + 2 + (0.0 if fmt == 'sp' else 0.01 * total)

    @staticmethod
    def _rescue_keep(tmp, outs, fmt, t):
        """The cut parts of a split whose original was already deleted: moved out of Temp (which is swept) into the rescue folder. Returns the folder."""
        dest = os.path.join(RESCUE_DIR, time.strftime('%Y%m%d-%H%M%S'))
        try:
            os.makedirs(RESCUE_DIR, exist_ok=True)
            shutil.move(tmp, dest)
            with open(os.path.join(dest, 'ABOUT.txt'), 'w', encoding='utf-8') as f:
                f.write('MiniDisc Manager: these WAV files are the parts cut from "%s" (%s) before it was deleted from the disc.\n'
                        'Drag them onto the disc with "Add tracks from PC" to write them again, in this order:\n' % (t['title'], fmt.upper()))
                for k, o in enumerate(outs):
                    f.write('  out%d.wav  %s  (%d s)\n' % (k + 1, o['title'], round(o['seconds'])))
            return dest
        except OSError:
            return tmp

    def _netmd_edit_run(self, index, op, numbers, params):
        params = params or {}
        use_exploit = bool(params.get('useExploit'))
        v = self._netmd_edit_validate(index, op, numbers, params, use_exploit)
        if 'error' in v:
            return v
        tracks, outs, kept, fmt, prep = v['tracks'], v['outs'], v['kept'], v['fmt'], v['prep']
        self._edit_cancel = False
        tmp = tempfile.mkdtemp(prefix='mdm-edit-')
        tell = self._edit_tell
        delete_first = bool(params.get('deleteFirst')) and op == 'split' and len(tracks) == 1      # no room next to the original: delete it once a PC copy is verified
        deleted, keep_tmp = False, False

        def bad(msg):
            """An error. After the original was deleted the cut parts are kept in the rescue folder, so nothing is lost."""
            nonlocal keep_tmp
            if not deleted:
                return {'error': msg + ' Your original track' + ('s were' if len(tracks) > 1 else ' was') + ' not changed.'}
            keep_tmp = True
            folder = self._rescue_keep(tmp, outs, fmt, tracks[0])
            return {'error': msg + ' The original was already deleted from the disc, but nothing is lost: the cut parts are in ' + folder +
                    ' (drag them onto the disc with Add tracks from PC), and a copy of the whole original is in Saved copies.', 'originalDeleted': True}
        try:
            # 1. the audio of the track(s), as WAV on this PC
            srcs = []
            if prep and os.path.isfile(prep['path']):
                srcs = [prep['path']]
            else:
                for i, t in enumerate(tracks):
                    wav, err = self._netmd_read_wav(index, t, tmp, use_exploit, i, len(tracks))
                    if err == 'cancelled':
                        return {'cancelled': True}
                    if err:
                        return {'error': err + ' Nothing was written.'}
                    srcs.append(wav)
            if self._edit_cancel:
                return {'cancelled': True}
            if delete_first:                                                  # the safety net: the whole original on this PC, checked, BEFORE anything is deleted
                t0 = tracks[0]
                tell(phase='copycheck', n=0, count=1, name=t0['title'], done=0, total=0)
                self._keep_copy(srcs[0], t0, replace=True)
                cp = self._find_copy(t0['title'], t0['seconds'], codec=t0['codec'])
                cp_secs = self._audio_seconds(os.path.join(COPIES_DIR, cp['id'] + '.flac')) if cp else None
                if not cp or not cp_secs or abs(cp_secs - t0['seconds']) > max(3.0, t0['seconds'] * 0.02):
                    return {'error': 'The copy of the original on this PC could not be checked, so the original was not deleted. Nothing was written.'}
            # 2. cut or join, to the sample
            tell(phase='preparing')
            sizes = [wav_data_bytes(p) for p in srcs]
            if op == 'split':
                cuts = [int(round(float(x) * 44100)) * 4 for x in sorted(float(y) for y in params['points'])]
                edges = [0] + cuts + [sizes[0]]
                spans = list(zip(edges, edges[1:]))
                if any(spans[k][1] - spans[k][0] < self.EDIT_MIN_PART * 176400 for k in kept):
                    return {'error': 'A split position is too close to another one, or to the start or end of the track. Nothing was written.'}
                plan = [[(srcs[0], 44 + a, b - a)] for k, (a, b) in enumerate(spans) if k in kept]
            else:
                plan = [[(p, 44, n) for p, n in zip(srcs, sizes)]]
            files = []
            for k, ranges in enumerate(plan):
                path = os.path.join(tmp, 'out%d.wav' % (k + 1))
                total = sum(r[2] for r in ranges)
                with open(path, 'wb') as out:
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
                                left -= len(chunk)
                files.append({'path': path, 'title': outs[k]['title']})
                outs[k]['seconds'] = total / 176400.0
            for p in srcs:
                if not (prep and p == prep['path']):
                    os.remove(p)
            # 3. room on the disc, and how many tracks it has now
            with self._lock:
                pl = self._run_helper('plan', {'files': []}, helper=NETMD_HELPER)
            if 'error' in pl:
                return pl
            before = pl['result']['trackCountNow']
            if pl['result'].get('writeProtected'):
                return {'error': 'The disc is write-protected. Slide its tab so the small hole is closed, reload the disc and try again. Nothing was written.'}
            need = sum(o['seconds'] for o in outs) * 1.01 + 2
            if need >= pl['result']['leftSeconds'][fmt]:
                if not delete_first:
                    return {'error': 'There is not enough free space on the disc for the new tracks while the originals are still on it. Nothing was written.'}
                need_d = self._delete_first_need(outs, fmt)                   # with the original gone the free time is exactly what it held, so the margin is small
                if need_d >= pl['result']['leftSeconds'][fmt] + tracks[0]['seconds']:
                    return {'error': 'There is not enough free space on the disc for the new tracks, even with the original deleted. Nothing was deleted or written. '
                                     'Remove a part (untick it) or trim more, then try again.'}
                tell(phase='deleting', n=0, count=1, name=tracks[0]['title'], done=0, total=0)       # no room next to it: delete the original (its PC copy is verified)
                self._drop_cache()
                with self._lock:
                    dres = self._run_helper('delete', {'indexes': [tracks[0]['number'] - 1]}, helper=NETMD_HELPER)
                if 'error' in dres:
                    return {'error': 'Deleting the original failed: %s. Nothing was written.' % dres['error']}
                deleted = True
                with self._lock:
                    pl = self._run_helper('plan', {'files': []}, helper=NETMD_HELPER)
                if 'error' in pl:
                    return bad('The original was deleted, but reading the disc afterwards failed: %s.' % pl['error'])
                before = pl['result']['trackCountNow']
                if need_d >= pl['result']['leftSeconds'][fmt]:
                    return bad('There is still not enough free space on the disc for the new tracks.')
            # 4. write the new tracks (the recorder encodes SP while it receives it, so this takes about as long as the audio plays)
            self._drop_cache()
            state = {'n': 0}

            def progress(m):
                ev = m.get('event')
                if ev == 'progress':
                    state['n'] = m.get('file', 0)
                    tell(phase='writing', n=m.get('file', 0), count=len(files), name=outs[min(m.get('file', 0), len(outs) - 1)]['title'], done=m.get('done', 0), total=m.get('total', 0))
                elif ev == 'encoding':
                    tell(phase='preparing', n=m.get('file', 0), count=len(files), name=m.get('name', ''), done=0, total=0)
            tell(phase='writing', n=0, count=len(files), name=outs[0]['title'], done=0, total=0)
            with self._lock:
                res = self._run_helper('upload', {'files': files, 'copyDir': COPIES_DIR, 'format': fmt}, progress, helper=NETMD_HELPER)
            if 'error' in res:
                return bad('Writing the new tracks failed: %s. Check the disc, because some of the new tracks may have been written.' % res['error'])
            try:
                self._save_copies((res.get('result') or {}).get('copies'), fmt)
            except OSError:
                pass
            # 5. check the disc's track list: the new tracks are there, with the lengths that were written
            tell(phase='checking', n=0, count=len(files), name='', done=0, total=0)
            with self._lock:
                after = self._run_helper('list', {}, helper=NETMD_HELPER)
            if 'error' in after:
                return bad('The new tracks were written, but reading the disc back failed: %s. Reload the disc and look at it before deleting anything.' % after['error'])
            listed = sorted((t for g in after['result']['groups'] for t in g['tracks']), key=lambda t: t['index'])
            if len(listed) != before + len(outs):
                return bad('The disc lists %d tracks, but %d were expected after writing. Reload the disc and look at it.' % (len(listed), before + len(outs)))
            for k, o in enumerate(outs):
                got = listed[before + k]['seconds']
                if abs(got - o['seconds']) > 3:
                    return bad('New track %d is %d seconds long on the disc, but %d were written. Reload the disc and look at it before deleting anything.' % (k + 1, got, round(o['seconds'])))
            # 6. put the new tracks right after the originals (not possible on a disc with groups: they stay at the end)
            last = (tracks[0]['number'] - 1) if deleted else max(t['number'] for t in tracks)         # 1-based number of the last original (the original's own place if it was deleted)
            placed = True
            for k in range(len(outs)):
                if before == last:                                            # already where the original was (it was the last track)
                    break
                with self._lock:
                    mv = self._run_helper('move', {'from': before + k, 'to': last + k}, helper=NETMD_HELPER)
                if 'error' in mv:
                    placed = False
                    break
            new_positions = [last + 1 + k for k in range(len(outs))] if placed else [before + 1 + k for k in range(len(outs))]
            if self._edit_prep and op == 'split':
                self._edit_prep_clear()
            self._drop_cache()
            return {'ok': True, 'netmd': True, 'new': new_positions, 'placed': placed, 'originals': [] if deleted else [t['number'] for t in tracks],
                    'originalDeleted': deleted, 'mode': 'pcm', 'format': fmt}
        except (RuntimeError, OSError) as exc:
            return bad(str(exc))
        finally:
            if not keep_tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            self._release_devices()
