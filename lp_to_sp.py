"""Turning LP2 / LP4 tracks of a standard disc into SP. LpToSpMixin is mixed into himd_app.Api (the page calls these methods on it).

Why: a player without LP support plays an LP2 / LP4 track as silence. SP plays everywhere. SP takes 2x (LP2) or 4x (LP4) the room, so a well
filled LP disc does not fit back as SP: the tracks that do not fit can be spread over a second disc.

Steps (the page calls them in this order):
  1. lpsp_read: every chosen track (those that stay on this disc and those that go to a second disc) is copied to LPSP_DIR as FLAC, checked
     against the disc's playing time. All or nothing; nothing on the disc is touched. (An MZ-NH700 read with the experimental download needs
     the cable unplugged and plugged in again afterwards, which the page asks for.)
  2. lpsp_run: tracks for the second disc are deleted from this disc first (their PC copy is checked, and it frees the room), then each track
     that stays is rewritten as SP in its own place: the SP version is written next to the original when the disc has room, otherwise after the
     original was deleted, the disc's track list is read back and checked, the SP track is put in the original's place, and the LP original is
     removed. A copy of every LP original also goes to Saved copies.
  3. lpsp_spill_write: the tracks for the second disc are written, as SP, to the next standard disc the user inserts (kept on this PC until then,
     also after the program is closed).
Not done on a disc with named groups (the recorder's group ranges cannot be moved safely), on write-protected discs, or on mono LP tracks."""
import hashlib
import json
import os
import shutil
import tempfile
import time

from mdm_paths import COPIES_DIR, LPSP_DIR, NETMD_HELPER

RATIO = {'LP2': 2, 'LP4': 4}                         # how many times longer a disc plays in this mode than in SP
MANIFEST = os.path.join(LPSP_DIR, 'manifest.json')
STAGE = os.path.join(LPSP_DIR, 'stage')


class LpToSpMixin:
    # -- what the disc holds -------------------------------------------------------------------------------------------
    def _lpsp_tracks(self):
        """The convertible tracks of the loaded standard disc (stereo LP2 / LP4), and the numbers of mono LP tracks that cannot be."""
        tracks = list(self._tracks or [])
        ok = [t for t in tracks if t.get('codec') in RATIO]
        mono = [t['number'] for t in tracks if str(t.get('codec', '')).startswith('LP') and t.get('codec') not in RATIO]
        return ok, mono

    def lpsp_status(self, index):
        """Cheap, reads nothing from the recorder: how many tracks of the loaded standard disc are LP2 / LP4 (the page shows a note when > 0)."""
        try:
            if not self._is_netmd(int(index)):
                return {'lp': 0}
        except (IndexError, ValueError):
            return {'lp': 0}
        ok, mono = self._lpsp_tracks()
        return {'lp': len(ok), 'mono': len(mono)}

    def lpsp_plan(self, index):
        """Says which LP tracks can be converted and how much room there is. Reads the track list only."""
        try:
            index = int(index)
            self._devices[index]
        except (IndexError, ValueError):
            return {'error': 'That recorder is no longer connected. Press rescan.'}
        if not self._is_netmd(index):
            return {'error': 'Only standard discs (SP / LP) have LP tracks.'}
        mf = self._lpsp_manifest()
        if mf and mf.get('phase') == 'spill':
            return {'error': 'Converted tracks are already waiting on this PC for a second disc. Write them to a disc, or discard them, first.', 'pending': True}
        ok, mono = self._lpsp_tracks()
        if not ok:
            return {'error': 'This disc has no LP2 or LP4 tracks.' + (' (Mono LP tracks cannot be converted by this app.)' if mono else '')}
        with self._lock:
            pl = self._run_helper('plan', {'files': []}, helper=NETMD_HELPER)
            ls = self._run_helper('list', {}, helper=NETMD_HELPER) if 'error' not in pl else pl
        if 'error' in pl:
            return pl
        if 'error' in ls:
            return ls
        p = pl['result']
        if p.get('writeProtected'):
            return {'error': 'The disc is write-protected. Slide its tab so the small hole is closed, reload the disc and try again.'}
        if any(g.get('title') for g in ls['result'].get('groups', [])):
            return {'error': 'This disc has named track groups. Converting in place needs to move tracks, which this app cannot do on a grouped standard disc yet.'}
        can, exp = self._can_fetch(index), self._exploit_possible(index)
        rows = []
        for t in ok:
            if self._find_copy(t['title'], t['seconds'], codec=t['codec']):
                how = 'copy'
            elif can:
                how = 'direct'
            elif exp:
                how = 'patch'
            else:
                how = None
            rows.append({'number': t['number'], 'title': t['title'], 'codec': t['codec'], 'seconds': t['seconds'], 'ratio': RATIO[t['codec']], 'how': how})
        os.makedirs(LPSP_DIR, exist_ok=True)
        return {'tracks': rows, 'mono': mono, 'leftSp': p['leftSeconds']['sp'], 'needsExploit': any(r['how'] == 'patch' for r in rows),
                'unreadable': [r['number'] for r in rows if not r['how']], 'pcFree': shutil.disk_usage(LPSP_DIR).free}

    # -- the manifest of the PC copy ----------------------------------------------------------------------------------------
    @staticmethod
    def _lpsp_manifest():
        try:
            with open(MANIFEST, encoding='utf-8') as f:
                m = json.load(f)
        except (OSError, ValueError):
            return None
        return m if isinstance(m, dict) and m.get('complete') else None

    @staticmethod
    def _lpsp_save_manifest(m):
        tmp = MANIFEST + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(m, f, indent=1)
        os.replace(tmp, MANIFEST)

    def lpsp_discard(self):
        shutil.rmtree(LPSP_DIR, ignore_errors=True)
        return {'ok': True}

    @staticmethod
    def _sha(path):
        digest = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                digest.update(chunk)
        return digest.hexdigest()

    # -- step 1: copy to the PC -----------------------------------------------------------------------------------------------
    def lpsp_read(self, index, numbers, spill=None, use_exploit=False):
        """READS the chosen LP tracks to LPSP_DIR. Writes nothing to the recorder. `numbers`: tracks that stay on this disc (rewritten as SP in place);
        `spill`: tracks that move to a second disc (they are deleted from this one in step 2)."""
        index = int(index)
        plan = self.lpsp_plan(index)
        if 'error' in plan:
            return plan
        keep = sorted({int(n) for n in numbers or []})
        move = sorted({int(n) for n in spill or []})
        by_number = {r['number']: r for r in plan['tracks']}
        wanted = sorted(set(keep) | set(move))
        if not wanted or set(keep) & set(move) or any(n not in by_number for n in wanted):
            return {'error': 'Choose the LP2 / LP4 tracks to convert. The disc may have changed: reload it.'}
        bad = [by_number[n] for n in wanted if by_number[n]['how'] is None]
        if bad:
            return {'error': ('This recorder can only send audio back with the experimental download: allow it, then try again.' if self._exploit_possible(index)
                              else 'This recorder cannot send audio back, and the app has no saved copy of “%s”.' % bad[0]['title'])}
        if any(by_number[n]['how'] == 'patch' for n in wanted) and not use_exploit:
            return {'error': 'Some tracks can only be read with the experimental download. Tick the box to allow it.', 'needExploit': True}
        secs = sum(by_number[n]['seconds'] for n in wanted)
        os.makedirs(LPSP_DIR, exist_ok=True)
        if shutil.disk_usage(LPSP_DIR).free < secs * 5 * 1000 * 1000 / 60 * 1.3 + 300 * 1000 * 1000:
            return {'error': 'There is not enough free space on this PC to hold a copy of these tracks.'}
        by_track = {t['number']: t for t in self._tracks}
        shutil.rmtree(LPSP_DIR, ignore_errors=True)
        os.makedirs(STAGE)
        try:
            saved = self.save_tracks(index, wanted, STAGE, 'flac', False, 'v0', bool(use_exploit))
            if saved.get('error'):
                raise RuntimeError(saved['error'])
            if saved.get('cancelled'):
                shutil.rmtree(LPSP_DIR, ignore_errors=True)
                return {'cancelled': True}
            if saved['failed']:
                f = saved['failed'][0]
                raise RuntimeError('Track %d (%s) could not be saved: %s' % (f['number'], f['title'], f['error']))
            files = {s['number']: s['file'] for s in saved['saved']}
            items = {}
            for n in wanted:
                t, path = by_track[n], files.get(n)
                if not path or not os.path.isfile(path):
                    raise RuntimeError('Track %d was not saved.' % n)
                heard = self._probe_seconds(path)
                if abs(heard - t['seconds']) > 3:
                    raise RuntimeError('Track %d was saved as %d s of audio but the disc says %d s.' % (n, round(heard), t['seconds']))
                items[n] = {'number': n, 'title': '' if t['title'] == '(untitled)' else t['title'], 'artist': t.get('artist') or '', 'album': t.get('album') or '',
                            'seconds': t['seconds'], 'codec': t['codec'], 'ratio': RATIO[t['codec']], 'file': os.path.basename(path),
                            'bytes': os.path.getsize(path), 'sha': self._sha(path)}
            self._lpsp_save_manifest({'complete': True, 'phase': 'read', 'when': time.strftime('%Y-%m-%dT%H:%M:%S'), 'deleted': False,
                                      'keep': [items[n] for n in keep], 'spill': [items[n] for n in move]})
            return {'ok': True, 'keep': len(keep), 'spill': len(move), 'exploitUsed': bool(saved.get('exploitUsed'))}
        except (RuntimeError, OSError) as exc:
            shutil.rmtree(LPSP_DIR, ignore_errors=True)
            return {'error': 'Copying the tracks to this PC failed: %s Nothing was changed on the disc.' % exc}

    # -- step 2: change the disc ------------------------------------------------------------------------------------------------
    def lpsp_run(self, index):
        """WRITES TO THE DISC. Uses the PC copy made by lpsp_read. Stops at the first problem and says which tracks are done; every finished
        track stays converted."""
        index = int(index)
        m = self._lpsp_manifest()
        if not m or m.get('phase') != 'read':
            return {'error': 'There is nothing prepared to convert. Start again.'}
        keep, spill = m['keep'], m['spill']
        loaded = self.load(index)
        if 'error' in loaded:
            return loaded
        by_number = {t['number']: t for t in self._tracks}
        for it in keep + spill:                                         # the disc must still be exactly what was copied
            t = by_number.get(it['number'])
            p = os.path.join(STAGE, it['file'])
            if (not t or t['codec'] != it['codec'] or abs(t['seconds'] - it['seconds']) > 1 or (t['title'] if t['title'] != '(untitled)' else '') != it['title']
                    or not os.path.isfile(p) or os.path.getsize(p) != it['bytes'] or self._sha(p) != it['sha']):
                shutil.rmtree(LPSP_DIR, ignore_errors=True)
                return {'error': 'The disc or the saved copy changed since the tracks were copied. Nothing was changed on the disc; start again.'}
        ls = self._run_helper('list', {}, helper=NETMD_HELPER)
        if 'error' in ls or any(g.get('title') for g in ls['result'].get('groups', [])):
            shutil.rmtree(LPSP_DIR, ignore_errors=True)
            return {'error': ls['error'] if 'error' in ls else 'This disc has named track groups, so it was not changed.'}
        spill_nums = sorted(it['number'] for it in spill)
        shift = lambda n: n - sum(1 for s in spill_nums if s < n)         # a track's number once the second-disc tracks are gone
        details = {shift(n): (t.get('artist') or '', t.get('album') or '') for n, t in by_number.items() if n not in spill_nums}
        self._edit_cancel = False
        tell = self._edit_tell
        done, count = [], len(keep)

        def stop(msg, **extra):
            tail = (' Tracks already converted stay converted: %s.' % ', '.join(map(str, done))) if done else ''
            if spill and m.get('deleted'):
                tail += ' The tracks for the second disc are safe on this PC (the program offers to write them when you insert a disc).'
            elif not extra.get('originalDeleted') and not done:
                tail += ' Nothing was changed on the disc.'
            out = {'error': msg + tail, 'done': list(done)}
            out.update(extra)
            self._fin_details(index, details)
            if spill and m.get('deleted'):                                # the second-disc tracks are off this disc already: keep them waiting for a disc
                m['phase'], m['keep'] = 'spill', []
                self._lpsp_save_manifest(m)
            elif not extra.get('originalDeleted'):
                shutil.rmtree(LPSP_DIR, ignore_errors=True)               # the PC copy is not needed any more (nothing is waiting on it)
            return out

        # 2a. the tracks for the second disc leave this disc first: their PC copy is verified, and the room is needed for the SP versions
        if spill_nums:
            tell(phase='deleting', n=0, count=max(1, count), name='the tracks for the second disc', done=0, total=0)
            self._drop_cache()
            with self._lock:
                d = self._run_helper('delete', {'indexes': [n - 1 for n in spill_nums]}, helper=NETMD_HELPER)
            if 'error' in d:
                return stop('Removing the tracks for the second disc from this disc failed: %s' % d['error'])
            m['deleted'] = True
            self._lpsp_save_manifest(m)
        # 2b. rewrite each track that stays, in its place
        for i, it in enumerate(keep):
            if self._edit_cancel:
                return stop('Stopped.', cancelled=True)
            n = shift(it['number'])
            name = it['title'] or 'Track %d' % it['number']
            t = {'title': it['title'] or '(untitled)', 'seconds': it['seconds'], 'codec': it['codec'], 'number': n}
            tmp = tempfile.mkdtemp(prefix='mdm-edit-')
            keep_tmp, deleted = False, False
            src = os.path.join(STAGE, it['file'])
            try:
                tell(phase='preparing', n=i, count=count, name=name, done=0, total=0)
                out = os.path.join(tmp, 'out1.wav')
                self._ffmpeg(['-i', src, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', out])
                try:                                                         # a Saved copy of the LP original, as a safety net after it is gone
                    self._keep_copy(out, t, replace=True)
                except Exception:
                    pass
                secs = it['seconds']
                outs = [{'title': name, 'seconds': float(secs)}]
                with self._lock:
                    pl = self._run_helper('plan', {'files': []}, helper=NETMD_HELPER)
                if 'error' in pl:
                    return stop(pl['error'])
                left, before = pl['result']['leftSeconds']['sp'], pl['result']['trackCountNow']
                beside = secs * 1.01 + 2 < left
                if not beside and self._delete_first_need(outs, 'sp') >= left + secs / float(it['ratio']):
                    return stop('There is not enough room on the disc to convert “%s” to SP.' % name)
                if not beside:
                    tell(phase='deleting', n=i, count=count, name=name, done=0, total=0)
                    self._drop_cache()
                    with self._lock:
                        d = self._run_helper('delete', {'indexes': [n - 1]}, helper=NETMD_HELPER)
                    if 'error' in d:
                        return stop('Deleting the LP original of “%s” failed: %s' % (name, d['error']))
                    deleted = True
                    before -= 1

                def bad(msg):
                    nonlocal keep_tmp
                    if not deleted:
                        return stop(msg + ' The LP original of “%s” was not deleted.' % name)
                    keep_tmp = True
                    folder = self._rescue_keep(tmp, outs, 'sp', t)
                    return stop(msg + ' The LP original of “%s” was already deleted, but nothing is lost: its audio is in %s (drag out1.wav onto the disc with Add tracks from PC) '
                                      'and in %s.' % (name, folder, STAGE), originalDeleted=True)

                self._drop_cache()

                def progress(msg):
                    ev = msg.get('event')
                    if ev == 'progress':
                        tell(phase='writing', n=i, count=count, name=name, done=msg.get('done', 0), total=msg.get('total', 0))
                    elif ev == 'encoding':
                        tell(phase='preparing', n=i, count=count, name=name, done=0, total=0)
                tell(phase='writing', n=i, count=count, name=name, done=0, total=0)
                with self._lock:
                    res = self._run_helper('upload', {'files': [{'path': out, 'title': name}], 'copyDir': COPIES_DIR, 'format': 'sp'}, progress, helper=NETMD_HELPER)
                if 'error' in res:
                    return bad('Writing the SP version of “%s” failed: %s. Check the disc: part of it may have been written.' % (name, res['error']))
                try:
                    self._save_copies((res.get('result') or {}).get('copies'), 'sp')
                except OSError:
                    pass
                tell(phase='checking', n=i, count=count, name=name, done=0, total=0)
                with self._lock:
                    after = self._run_helper('list', {}, helper=NETMD_HELPER)
                if 'error' in after:
                    return bad('The SP version was written, but reading the disc back failed: %s.' % after['error'])
                listed = sorted((x for g in after['result']['groups'] for x in g['tracks']), key=lambda x: x['index'])
                if len(listed) != before + 1 or listed[-1]['codec'] != 'SP' or abs(listed[-1]['seconds'] - secs) > 3:
                    return bad('After writing, the disc does not show the new SP track of “%s” as expected (%d tracks, expected %d).' % (name, len(listed), before + 1))
                last = before                                                   # 0-based position of the new track
                target = (n - 1) if deleted else n                              # the original's own place, or right after it
                if last != target:
                    with self._lock:
                        mv = self._run_helper('move', {'from': last, 'to': target}, helper=NETMD_HELPER)
                    if 'error' in mv:
                        return bad('Moving the new track of “%s” into place failed: %s.' % (name, mv['error']))
                if not deleted:
                    with self._lock:
                        d = self._run_helper('delete', {'indexes': [n - 1]}, helper=NETMD_HELPER)
                    if 'error' in d:
                        return stop('The SP version of “%s” is on the disc, but deleting the LP original failed: %s. Both are on the disc now; delete the LP one yourself.' % (name, d['error']))
                    deleted = True
                self._drop_cache()
                done.append(it['number'])
                try:
                    os.remove(src)
                except OSError:
                    pass
            except (RuntimeError, OSError) as exc:
                if deleted:
                    keep_tmp = True
                    folder = self._rescue_keep(tmp, [{'title': name, 'seconds': it['seconds']}], 'sp', t)
                    return stop('%s The LP original of “%s” was already deleted; its audio is in %s and in %s.' % (exc, name, folder, STAGE), originalDeleted=True)
                return stop(str(exc))
            finally:
                if not keep_tmp:
                    shutil.rmtree(tmp, ignore_errors=True)
                self._release_devices()
        # 2c. done on this disc
        self._fin_details(index, details)
        if spill:
            m['phase'] = 'spill'
            m['keep'] = []
            self._lpsp_save_manifest(m)
            return {'ok': True, 'done': done, 'spill': len(spill), 'spillSeconds': sum(x['seconds'] for x in spill)}
        shutil.rmtree(LPSP_DIR, ignore_errors=True)
        return {'ok': True, 'done': done, 'spill': 0}

    def _fin_details(self, index, details):
        """The disc's track lengths changed by a second or so, which is how this PC recognises a disc: put the artist / album back under the new lengths."""
        try:
            self.load(int(index))
            items = [{'number': k, 'artist': a, 'album': b} for k, (a, b) in details.items() if (a or b) and any(t['number'] == k for t in self._tracks)]
            if items:
                self.set_netmd_details(int(index), items)
        except Exception:
            pass

    # -- step 3: the second disc ------------------------------------------------------------------------------------------------
    def lpsp_spill_status(self):
        m = self._lpsp_manifest()
        if not m or m.get('phase') != 'spill' or not m.get('spill'):
            return {'pending': None}
        return {'pending': {'tracks': len(m['spill']), 'seconds': sum(x['seconds'] for x in m['spill']), 'when': m.get('when', ''),
                            'titles': [x['title'] or 'Track %d' % x['number'] for x in m['spill']]}}

    def lpsp_spill_write(self, index):
        """WRITES TO THE DISC: the tracks waiting for a second disc, as SP, after what is already on the disc now in the recorder. The PC copy
        is deleted only when the disc's track list shows them all."""
        index = int(index)
        m = self._lpsp_manifest()
        if not m or m.get('phase') != 'spill' or not m.get('spill'):
            return {'error': 'There are no converted tracks waiting for a disc.'}
        keep = ' The tracks are still saved on this PC, so you can try again with another disc.'
        try:
            if not self._is_netmd(index):
                return {'error': 'The disc in the recorder is a Hi-MD disc. Insert a standard (SP / LP) disc.' + keep}
        except (IndexError, ValueError):
            return {'error': 'That recorder is no longer connected. Press rescan.'}
        items = m['spill']
        for it in items:
            p = os.path.join(STAGE, it['file'])
            if not os.path.isfile(p) or os.path.getsize(p) != it['bytes'] or self._sha(p) != it['sha']:
                return {'error': 'A saved track is missing or damaged (%s).' % it['file']}
        loaded = self.load(index)
        if 'error' in loaded:
            return loaded
        files = [{'path': os.path.join(STAGE, it['file']), 'title': it['title'] or 'Track %d' % it['number'], 'artist': it['artist'], 'album': it['album']} for it in items]
        plan = self.plan_upload([f['path'] for f in files])
        if 'error' in plan:
            return {'error': plan['error'] + keep}
        pl = plan.get('result') or {}
        if pl.get('writeProtected'):
            return {'error': 'The disc is write-protected. Slide its tab to make it writable.' + keep}
        if not pl.get('fits'):
            return {'error': 'These tracks need about %d minutes of SP and the disc has about %d minutes free. Use an emptier disc.%s' % (
                round(sum(x['seconds'] for x in items) / 60.0), round((pl.get('leftSeconds') or {}).get('sp', 0) / 60.0), keep), 'noRoom': True}
        before = len(self._tracks or [])
        res = self.upload(files, 'sp')
        if 'error' in res:
            return {'error': 'Writing the tracks failed: %s%s' % (res['error'], keep)}
        self._drop_cache()
        back = self.load(index)
        tracks = ((back.get('disc') or {}).get('tracks')) if 'error' not in back else None
        if tracks is None or len(tracks) != before + len(items):
            return {'error': 'The tracks were written, but reading the disc back found %s tracks instead of %d. The saved tracks are still on this PC.' % (
                'no' if tracks is None else len(tracks), before + len(items)), 'unchecked': True}
        notes = []
        for it, t in zip(items, tracks[before:]):
            if t['codec'] != 'SP' or abs(t['seconds'] - it['seconds']) > 3:
                notes.append('“%s” is %s, %d s on the disc (it was %d s).' % (it['title'] or 'Track %d' % it['number'], t['codec'], t['seconds'], it['seconds']))
        try:
            self.set_netmd_details(index, [{'number': before + k + 1, 'artist': it['artist'], 'album': it['album']} for k, it in enumerate(items) if it['artist'] or it['album']])
        except Exception:
            pass
        if not notes:
            shutil.rmtree(LPSP_DIR, ignore_errors=True)
        return {'ok': True, 'tracks': len(items), 'notes': notes}
