"""Converting a standard (SP / LP) disc to a Hi-MD disc through this PC. ConvertMixin is mixed into himd_app.Api (the page calls these methods on it).

Steps: 1. convert_read: every track of the standard disc is saved to CONVERT_DIR as FLAC (the app's own saved copy when there is one, otherwise
read off the recorder), with its title, artist, album, the disc name and the groups. Nothing is erased until all tracks are safely on the PC.
2. The page formats the disc as Hi-MD (format_disc, mode 'himd'; the recorder switches to Hi-MD mode and comes back).
3. convert_write: the saved tracks are written to the empty Hi-MD disc as Hi-SP (default), Hi-LP or PCM, the groups and the disc name are put back, the
disc is read again to check, and only then is the PC copy deleted. A saved copy survives closing the program, so step 3 can wait."""
import datetime
import hashlib
import json
import os
import shutil

from mdm_paths import CONVERT_DIR, NETMD_HELPER

CODECS = {'hisp': 32000, 'hilp': 8000, 'at3p': 44000, 'pcm': 176400}           # bytes of disc space per second of audio
CAP_80_MIN = 305 * 1000 * 1000                                   # an 80-minute disc used as a Hi-MD disc holds about this much


class ConvertMixin:
    @staticmethod
    def _convert_manifest():
        try:
            with open(os.path.join(CONVERT_DIR, 'manifest.json'), encoding='utf-8') as f:
                m = json.load(f)
        except (OSError, ValueError):
            return None
        return m if isinstance(m, dict) and m.get('complete') else None

    def convert_status(self):
        m = self._convert_manifest()
        if not m:
            return {'pending': None}
        return {'pending': {'title': m.get('discTitle') or '', 'tracks': len(m['tracks']), 'seconds': m.get('seconds', 0), 'when': m.get('when', ''),
                            'codec': m.get('codec', 'hisp')}}

    def convert_discard(self):
        shutil.rmtree(CONVERT_DIR, ignore_errors=True)
        return {'ok': True}

    def convert_plan(self, index):
        """Reads nothing from the recorder. Says whether the loaded standard disc can be converted, and how much room it would need."""
        try:
            index = int(index)
            usb_dev = self._devices[index]
        except (IndexError, ValueError):
            return {'error': 'That recorder is no longer connected. Press rescan.'}
        if not self._is_netmd(index):
            return {'error': 'This is already a Hi-MD disc.'}
        if not self._himd_capable(usb_dev):
            return {'error': 'This recorder cannot use Hi-MD discs.'}
        if self._convert_manifest():
            return {'error': 'A saved disc is already waiting on this PC. Write it to a disc or discard it first.', 'pending': True}
        tracks = list(self._tracks or [])
        if not tracks:
            return {'error': 'The disc has no tracks.'}
        can, exp = self._can_fetch(index), self._exploit_possible(index)
        rows, secs = [], 0
        for t in tracks:
            if self._find_copy(t['title'], t['seconds'], codec=t['codec']):
                how = 'copy'
            elif can:
                how = 'recorder'
            elif exp:
                how = 'exploit'
            else:
                how = None
            rows.append({'number': t['number'], 'title': t['title'], 'seconds': t['seconds'], 'codec': t['codec'], 'how': how})
            secs += t['seconds']
        os.makedirs(CONVERT_DIR, exist_ok=True)
        free = shutil.disk_usage(CONVERT_DIR).free
        need_pc = int(secs * 5 * 1000 * 1000 / 60 * 1.2)         # FLAC of CD audio is roughly 5 MB a minute
        return {'tracks': rows, 'seconds': secs, 'unreadable': [r['number'] for r in rows if not r['how']],
                'needsExploit': any(r['how'] == 'exploit' for r in rows), 'pcFree': free, 'pcFits': free > need_pc + 200 * 1000 * 1000,
                'bytes': {k: int(secs * v) for k, v in CODECS.items()}, 'cap80': CAP_80_MIN}

    def convert_read(self, index, use_exploit=False):
        """READS the whole standard disc to CONVERT_DIR. Writes nothing to the recorder. All or nothing: if one track cannot be saved
        (or the playing time of a saved file does not match the disc) the PC copy is thrown away and the user is told, with the disc untouched."""
        plan = self.convert_plan(index)
        if 'error' in plan:
            return plan
        if plan['unreadable']:
            return {'error': 'Track %s cannot be read back from this recorder, so the disc cannot be converted safely.' % ', '.join(map(str, plan['unreadable']))}
        if not plan['pcFits']:
            return {'error': 'There is not enough free space on this PC to hold a copy of the disc.'}
        if plan['needsExploit'] and not use_exploit:
            return {'error': 'Some tracks can only be read with the experimental download. Tick the box to allow it.', 'needExploit': True}
        index = int(index)
        stage = os.path.join(CONVERT_DIR, 'stage')
        shutil.rmtree(CONVERT_DIR, ignore_errors=True)
        os.makedirs(stage)
        try:
            with self._lock:
                res = self._run_helper('list', {}, helper=NETMD_HELPER)
            if 'error' in res:
                raise RuntimeError(res['error'])
            d = res['result']
            numbers = [t['number'] for t in self._tracks]
            saved = self.save_tracks(index, numbers, stage, 'flac', False, 'v0', bool(use_exploit))
            if saved.get('error'):
                raise RuntimeError(saved['error'])
            if saved.get('cancelled'):
                shutil.rmtree(CONVERT_DIR, ignore_errors=True)
                return {'cancelled': True}
            if saved['failed']:
                f = saved['failed'][0]
                raise RuntimeError('Track %d (%s) could not be saved: %s' % (f['number'], f['title'], f['error']))
            files = {s['number']: s['file'] for s in saved['saved']}
            items = []
            for t in self._tracks:
                path = files.get(t['number'])
                if not path or not os.path.isfile(path):
                    raise RuntimeError('Track %d was not saved.' % t['number'])
                secs = self._probe_seconds(path)
                if abs(secs - t['seconds']) > 3:
                    raise RuntimeError('Track %d was saved as %d s of audio but the disc says %d s.' % (t['number'], round(secs), t['seconds']))
                digest = hashlib.sha256()
                with open(path, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        digest.update(chunk)
                items.append({'number': t['number'], 'title': '' if t['title'] == '(untitled)' else t['title'], 'artist': t.get('artist') or '',
                              'album': t.get('album') or '', 'seconds': t['seconds'], 'codec': t['codec'], 'file': os.path.basename(path),
                              'bytes': os.path.getsize(path), 'sha': digest.hexdigest()})
            groups = []
            for g in d.get('groups', []):                       # the disc's named groups, as ranges of track numbers (a standard disc keeps them contiguous)
                if g.get('title') is None:
                    continue
                nums = sorted(t['index'] + 1 for t in g['tracks'])
                if nums and nums[-1] - nums[0] + 1 == len(nums):
                    groups.append({'first': nums[0], 'last': nums[-1], 'title': g['title']})
            manifest = {'complete': True, 'version': 1, 'when': datetime.datetime.now().isoformat(timespec='seconds'), 'discTitle': d.get('discTitle') or '',
                        'groups': groups, 'tracks': items, 'seconds': sum(x['seconds'] for x in items), 'bytes': sum(x['bytes'] for x in items), 'codec': 'hisp'}
            tmp = os.path.join(CONVERT_DIR, 'manifest.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=1)
            os.replace(tmp, os.path.join(CONVERT_DIR, 'manifest.json'))
            return {'ok': True, 'tracks': len(items), 'title': manifest['discTitle'], 'exploitUsed': bool(saved.get('exploitUsed'))}
        except (RuntimeError, OSError) as exc:
            shutil.rmtree(CONVERT_DIR, ignore_errors=True)
            return {'error': 'Copying the disc to this PC failed: %s Nothing was changed on the disc.' % exc}

    def convert_target(self, index):
        """Reads the disc now in the recorder and says whether the saved tracks can be written to it. Reads only."""
        m = self._convert_manifest()
        if not m:
            return {'error': 'There is no saved disc waiting to be written.'}
        r = self.load(int(index))
        if 'error' in r:
            return r
        if r.get('mode') == 'netmd':
            return {'state': 'netmd', 'canHimd': bool(r.get('canHimd')), 'tracks': len((r.get('disc') or {}).get('tracks', []))}
        if r.get('discState') != 'ok':
            return {'state': r.get('discState') or 'none', 'message': r.get('discMessage', '')}
        d = r['disc']
        return {'state': 'ok', 'empty': len(d['tracks']) == 0, 'tracks': len(d['tracks']), 'free': d['free'], 'total': d['total'],
                'bytes': {k: int(m['seconds'] * v) for k, v in CODECS.items()}, 'seconds': m['seconds'], 'count': len(m['tracks']),
                'title': m.get('discTitle') or '', 'writeProtected': bool(d.get('writeProtected'))}

    def convert_write(self, index, codec='hisp'):
        """WRITES TO THE DISC: the saved tracks onto an empty Hi-MD disc, then groups and disc name, then a read-back check. The PC copy is
        deleted only when the check passes."""
        codec = codec if codec in CODECS else 'hisp'
        m = self._convert_manifest()
        if not m:
            return {'error': 'There is no saved disc waiting to be written.'}
        stage = os.path.join(CONVERT_DIR, 'stage')
        keep = ' The saved tracks are still on this PC, so you can try again.'
        items = m['tracks']
        for it in items:                                          # the PC copy must still be exactly what was read
            p = os.path.join(stage, it['file'])
            if not os.path.isfile(p) or os.path.getsize(p) != it['bytes']:
                return {'error': 'A saved track is missing or damaged (%s). Discard the saved disc and convert it again.' % it['file']}
            digest = hashlib.sha256()
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    digest.update(chunk)
            if digest.hexdigest() != it['sha']:
                return {'error': 'A saved track is damaged (%s). Discard the saved disc and convert it again.' % it['file']}
        tgt = self.convert_target(index)
        if 'error' in tgt:
            return tgt
        if tgt['state'] != 'ok':
            return {'error': 'There is no readable Hi-MD disc in the recorder (state: %s).%s' % (tgt['state'], keep)}
        if tgt['writeProtected']:
            return {'error': 'The disc is write-protected. Slide its tab to make it writable.' + keep}
        if not tgt['empty']:
            return {'error': 'This Hi-MD disc is not empty (%d tracks). Erase it first.%s' % (tgt['tracks'], keep)}
        files = [{'path': os.path.join(stage, it['file']), 'title': it['title'], 'artist': it['artist'], 'album': it['album']} for it in items]
        plan = self.plan_upload([f['path'] for f in files])
        if 'error' in plan:
            return {'error': plan['error'] + keep}
        pl = plan.get('result') or {}
        if not (pl.get('fitsByFormat') or {}).get(codec, False):
            return {'error': 'The tracks do not fit on this disc as %s: they need about %d MB and the disc has about %d MB free. '
                             'Try Hi-LP, or put the tracks on a bigger disc.%s' % (codec.upper(), (pl.get('needByFormat') or {}).get(codec, 0) // 1000000, pl.get('freeBytes', 0) // 1000000, keep),
                    'noRoom': True}
        res = self.upload(files, codec)
        if 'error' in res:
            return {'error': 'Writing the tracks failed: %s%s' % (res['error'], keep)}
        notes = []
        self._drop_cache()
        back = self.load(int(index))
        tracks = ((back.get('disc') or {}).get('tracks')) if 'error' not in back else None
        if tracks is None or len(tracks) != len(items):
            return {'error': 'The tracks were written, but reading the disc back found %s tracks instead of %d. The saved tracks are still on this PC.' %
                             ('no' if tracks is None else len(tracks), len(items)), 'unchecked': True}
        for it, t in zip(items, tracks):
            if abs(t['seconds'] - it['seconds']) > 3:
                notes.append('Track %d is %d s on the disc but was %d s on the standard disc.' % (it['number'], t['seconds'], it['seconds']))
        if m.get('groups'):
            gr = self.make_groups(int(index), m['groups'])
            if 'error' in gr:
                notes.append('The groups could not be put back (%s). Make them again from the Groups tools.' % gr['error'])
        if m.get('discTitle'):
            rn = self.rename_disc(int(index), m['discTitle'])
            if 'error' in rn:
                notes.append('The disc name could not be put back (%s).' % rn['error'])
        if not notes:
            shutil.rmtree(CONVERT_DIR, ignore_errors=True)
        else:
            notes.append('The saved tracks are still on this PC until you discard them.')
        try:
            self.log('convert: wrote %d tracks as %s; notes: %s; PC copy %s' % (len(items), codec, notes or 'none', 'kept' if notes else 'deleted'))
        except Exception:
            pass
        return {'ok': True, 'tracks': len(items), 'codec': codec, 'notes': notes, 'kept': bool(notes)}
