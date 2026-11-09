"""Standard discs (SP / LP2 / LP4, NetMD): adding tracks, saved copies, remote control, moving, deleting and reading back. NetMdMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile

import himd_dev
import himd_disc
import himd_fs
import usb.util
from mdm_common import UNITS_PER_SECOND
from mdm_paths import BACKUP_DIR, CLONE_DIR, HERE, NETMD_HELPER


class NetMdMixin:
    # Read: each track comes off the disc as the recorder's own raw data (SP: ATRAC1 as .aea, LP2 / LP4: ATRAC3 frames in a .wav), on an
    # MZ-RH1 the official way, on an MZ-NH700 with the opt-in firmware-patch download. Write: LP tracks go back as the same frames; SP
    # is decoded and sent as PCM so the destination recorder encodes it as SP again (one more generation). The disc's raw title is
    # copied last, which brings the disc name and the groups across. A standard disc cannot be read back on most recorders, so it is
    # checked by its track list (count, titles, formats, lengths), not byte for byte.
    LP_FRAME = {'LP2': 384, 'LP4': 192}

    def _clone_plan_netmd(self, index, numbers=None):
        if self._clone_manifest():
            return {'error': 'A saved copy of a disc is already waiting on this PC. Write it to a disc or discard it first.', 'pending': True}
        try:
            tracks = self._clone_wanted(numbers)
        except RuntimeError as exc:
            return {'error': str(exc)}
        if not tracks:
            return {'error': 'This disc has no tracks to copy.'}
        can = self._can_fetch(index)
        exp = (not can) and self._exploit_possible(index)
        if not (can or exp):
            return {'error': 'This recorder cannot send audio back, so it cannot read this disc. Use an MZ-RH1, or a Hi-MD recorder such as the MZ-NH700 with the experimental download.'}
        bad = [t['number'] for t in tracks if t['codec'].split(' ')[0] not in ('SP', 'LP2', 'LP4') or (t['codec'] != 'SP' and t['codec'].endswith('mono'))]
        if bad:
            return {'error': 'Track %s is mono LP or another format this app cannot copy, so the disc cannot be cloned.' % ', '.join(map(str, bad))}
        per_second = {'SP': 37000, 'LP2': 17000, 'LP4': 9000}
        need = int(sum(t['seconds'] * per_second[t['codec'].split(' ')[0]] for t in tracks))
        os.makedirs(CLONE_DIR, exist_ok=True)
        free = shutil.disk_usage(CLONE_DIR).free
        return {'netmd': True, 'tracks': len(tracks), 'seconds': sum(t['seconds'] for t in tracks), 'needBytes': need, 'freeBytes': free,
                'fits': free > need * 1.2 + 200 * 1000 * 1000, 'needsExploit': exp,
                'sp': sum(1 for t in tracks if t['codec'].startswith('SP')), 'monoSp': sum(1 for t in tracks if t['codec'] == 'SP mono'),
                'lp': sum(1 for t in tracks if t['codec'].startswith('LP'))}

    @staticmethod
    def _probe_seconds(path):
        """Playing time of an audio file, by decoding it with the bundled ffmpeg (the last time= line)."""
        exe = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
        r = subprocess.run([exe, '-hide_banner', '-nostats', '-i', path, '-vn', '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8',
                           errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        hits = re.findall(r'time=(\d+):(\d\d):(\d\d(?:\.\d+)?)', r.stderr)
        if r.returncode or not hits:
            raise RuntimeError('The audio read from the recorder could not be decoded.')
        h, mi, s = hits[-1]
        return int(h) * 3600 + int(mi) * 60 + float(s)

    @staticmethod
    def _atrac3_seconds(path, frame):
        with open(path, 'rb') as f:
            buf = f.read()
        if buf[:4] != b'RIFF' or buf[8:12] != b'WAVE':
            raise RuntimeError('The LP audio read from the recorder is not a WAV file.')
        pos = 12
        while pos + 8 <= len(buf):
            cid, size = buf[pos:pos + 4], struct.unpack('<I', buf[pos + 4:pos + 8])[0]
            if cid == b'data':
                n = min(size, len(buf) - pos - 8)
                if not n or n % frame:
                    raise RuntimeError('The LP audio read from the recorder is not a whole number of frames.')
                return n / frame * 1024 / 44100.0
            pos += 8 + size + (size & 1)
        raise RuntimeError('The LP audio read from the recorder has no data.')

    @staticmethod
    def _clone_netmd_titles(d, kept):
        """For a standard disc listing `d`: (raw title, raw full-width title, groups) to write when only the tracks whose 0-based positions
        are in `kept` are copied. The raw title carries the group ranges ("0;Disc//1-3;Group//"), so it is rebuilt for the new numbering;
        with every track kept it is copied as it is."""
        total = sum(len(g['tracks']) for g in d['groups'])
        pos = {idx: i for i, idx in enumerate(kept)}
        groups = [{'title': g['title'], 'count': sum(1 for t in g['tracks'] if t['index'] in pos)} for g in d['groups']]
        groups = [g for g in groups if g['count']]
        if len(kept) == total:
            return d.get('rawTitle'), d.get('rawTitleW'), groups
        title = d['discTitle'] or ''
        real = [[pos[t['index']] for t in g['tracks'] if t['index'] in pos] for g in d['groups'] if g['title'] is not None]
        names = [g['title'] for g in d['groups'] if g['title'] is not None]
        raw = title
        if any(real):
            raw = ('0;%s//' % title) if title else ''
            for ns, name in zip(real, names):
                if ns:
                    raw += '%s;%s//' % (str(ns[0] + 1) if ns[0] == ns[-1] else '%d-%d' % (ns[0] + 1, ns[-1] + 1), name)
        return raw, None, groups

    def _clone_read_netmd(self, index, use_exploit, numbers=None):
        plan = self._clone_plan_netmd(index, numbers)
        if 'error' in plan:
            return plan
        if not plan['fits']:
            return {'error': 'There is not enough free space on this PC to hold a copy of the disc.'}
        if plan['needsExploit'] and not use_exploit:
            return {'error': 'This recorder can only be read with the experimental download. Tick the box to allow it.', 'needExploit': True}
        exploit = bool(plan['needsExploit'])
        self._clone_cancel = False
        self._drop_cache()
        stage = os.path.join(CLONE_DIR, 'stage')
        shutil.rmtree(CLONE_DIR, ignore_errors=True)
        os.makedirs(stage)
        tell = self._clone_tell
        try:
            with self._lock:
                res = self._run_helper('list', {}, helper=NETMD_HELPER)
            if 'error' in res:
                raise RuntimeError(res['error'])
            d = res['result']
            everything = [t for g in d['groups'] for t in g['tracks']]
            everything.sort(key=lambda t: t['index'])
            if [(t['index'] + 1, t['seconds']) for t in everything] != [(t['number'], t['seconds']) for t in self._tracks]:
                return {'error': 'The disc has changed since it was loaded. Reload it and try again.'}
            wanted = None if numbers is None else {int(n) for n in numbers}
            tracks = [t for t in everything if wanted is None or t['index'] + 1 in wanted]
            raw_title, raw_title_w, group_counts = self._clone_netmd_titles(d, [t['index'] for t in tracks])
            items = []
            for i, t in enumerate(tracks):
                label = t['title'] or 'Track %d' % (t['index'] + 1)
                tell(phase='reading', n=i, count=len(tracks), name=label, done=0, total=0)
                base = os.path.join(stage, '%03d' % (i + 1))
                with self._lock:
                    res = self._run_helper('fetch', {'index': t['index'], 'out': base, 'raw': True, 'exploit': exploit}, lambda m, i=i, label=label: tell(
                        phase='reading', n=i, count=len(tracks), name=label, done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None,
                        helper=NETMD_HELPER)
                if self._clone_cancel:
                    shutil.rmtree(CLONE_DIR, ignore_errors=True)
                    return {'cancelled': True}
                if 'error' in res:
                    shutil.rmtree(CLONE_DIR, ignore_errors=True)
                    return {'error': 'Reading “%s” from the disc failed: %s Nothing was changed on the disc.' % (label, res['error'])}
                got = res['result']
                path = got['file']
                if got['kind'] == 'aea':
                    if t['codec'] != 'SP' or os.path.getsize(path) <= 2048:
                        raise RuntimeError('“%s” came back in an unexpected format.' % label)
                    secs = self._probe_seconds(path)
                else:
                    if t['codec'] not in self.LP_FRAME:
                        raise RuntimeError('“%s” came back in an unexpected format.' % label)
                    secs = self._atrac3_seconds(path, self.LP_FRAME[t['codec']])
                if abs(secs - t['seconds']) > 3:
                    raise RuntimeError('“%s” was read as %d s of audio but the disc says %d s. Nothing was changed on the disc.' % (label, round(secs), t['seconds']))
                digest = hashlib.sha256()
                with open(path, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        digest.update(chunk)
                items.append({'title': t['title'], 'codec': t['codec'], 'mono': bool(t['mono']), 'seconds': t['seconds'], 'file': os.path.basename(path),
                              'kind': got['kind'], 'bytes': os.path.getsize(path), 'sha': digest.hexdigest()})
            manifest = {'complete': True, 'version': 1, 'type': 'netmd', 'when': datetime.datetime.now().isoformat(timespec='seconds'),
                        'discTitle': d['discTitle'] or '', 'rawTitle': raw_title, 'rawTitleW': raw_title_w,
                        'groups': group_counts, 'skipped': len(everything) - len(tracks),
                        'tracks': items, 'bytes': sum(x['bytes'] for x in items), 'seconds': sum(x['seconds'] for x in items),
                        'needUnits': sum(-(-x['seconds'] * UNITS_PER_SECOND // (1 if x['codec'].startswith('SP') else int(x['codec'][2]))) for x in items)}
            tmp = os.path.join(CLONE_DIR, 'manifest.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=1)
            os.replace(tmp, os.path.join(CLONE_DIR, 'manifest.json'))
            return {'ok': True, 'tracks': len(items), 'bytes': manifest['bytes'], 'title': manifest['discTitle'], 'exploitUsed': exploit}
        except (RuntimeError, OSError) as exc:
            shutil.rmtree(CLONE_DIR, ignore_errors=True)
            return {'error': 'Copying the disc to this PC failed: %s Nothing was changed on the disc.' % exc}

    def clone_read(self, index, use_exploit=False, numbers=None):
        """READS the disc (or the chosen tracks, `numbers`) into CLONE_DIR\\stage. Writes nothing to the recorder."""
        index = int(index)
        if self._is_netmd(index):
            return self._clone_read_netmd(index, use_exploit, numbers)
        plan = self.clone_plan(index, numbers)
        if 'error' in plan:
            return plan
        if not plan['fits']:
            return {'error': 'There is not enough free space on this PC to hold a copy of the disc.'}
        self._clone_cancel = False
        self._drop_cache()
        stage = os.path.join(CLONE_DIR, 'stage')
        shutil.rmtree(CLONE_DIR, ignore_errors=True)
        os.makedirs(stage)
        tell = self._clone_tell
        try:
            with self._lock:                                   # the disc as it is now: tracks, groups, name, picture
                self._release_devices()
                dev = himd_dev.Device(self._devices[index])
                fs = himd_fs.Fat16(dev)
                disc = himd_disc.Disc(fs)
                tracks, groups, disc_title, disc_id = disc.tracks(), disc.groups(), disc.disc_title(), self._disc_id(fs, disc)
                cover = None
                ent = next((e for e in fs.listdir('/') if not e['dir'] and e['short'].upper() == 'COVER.JPG'), None)
                if ent and 0 < ent['size'] <= 1500000:
                    cover = bytes(fs.read_file('/COVER.JPG'))
                self._release_devices()
            if [(t['number'], t['codec'], t['seconds']) for t in tracks] != [(t['number'], t['codec'], t['seconds']) for t in self._tracks]:
                return {'error': 'The disc has changed since it was loaded. Reload it and try again.'}
            wanted = None if numbers is None else {int(n) for n in numbers}
            everything = len(tracks)
            tracks = [t for t in tracks if wanted is None or t['number'] in wanted]
            kept = [t['number'] for t in tracks]
            groups = self._clone_remap_groups(groups, kept)         # the groups, renumbered for the tracks that are copied
            items = []
            for i, t in enumerate(tracks):
                kind = self._clone_kind(t)
                label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
                path = os.path.join(stage, '%03d.%s' % (i + 1, {'pcm': 'wav', 'atrac': 'oma', 'mp3': 'mp3'}[kind]))
                tell(phase='reading', n=i, count=len(tracks), name=label, done=0, total=0)
                with self._lock:
                    res = self._run_helper('dump', {'index': t['number'] - 1, 'out': path, 'exact': True, 'raw': kind == 'atrac'}, lambda m, i=i, label=label: tell(
                        phase='reading', n=i, count=len(tracks), name=label, done=m.get('done', 0), total=m.get('total', 0)) if m.get('event') == 'progress' else None)
                if self._clone_cancel:
                    shutil.rmtree(CLONE_DIR, ignore_errors=True)
                    return {'cancelled': True}
                if 'error' in res:
                    shutil.rmtree(CLONE_DIR, ignore_errors=True)
                    return {'error': 'Reading “%s” from the disc failed: %s Nothing was changed on the disc.' % (label, res['error'])}
                if kind == 'atrac':
                    self._oma_frames(path, t)
                skip, nbytes, sha = self._clone_core(path, kind)
                if kind == 'pcm' and nbytes % 64:
                    raise RuntimeError('“%s” is not a whole number of 64-byte units, which the disc could not store back exactly.' % label)
                items.append({'kind': kind, 'codec': t['codec'], 'codecId': t['codecId'], 'ci': t['ci'], 'frame': t['frame'], 'seconds': t['seconds'],
                              'title': '' if t['title'] == '(untitled)' else t['title'], 'artist': t['artist'], 'album': t['album'],
                              'file': os.path.basename(path), 'skip': skip, 'bytes': nbytes, 'sha': sha, 'blocks': t['blocks']})
            if cover:
                with open(os.path.join(stage, 'cover.jpg'), 'wb') as f:
                    f.write(cover)
            manifest = {'complete': True, 'version': 1, 'when': datetime.datetime.now().isoformat(timespec='seconds'), 'discTitle': disc_title,
                        'sourceId': disc_id, 'groups': [{'first': g['first'], 'last': g['last'], 'title': g['title']} for g in groups],
                        'skipped': everything - len(tracks),
                        'cover': 'cover.jpg' if cover else None, 'tracks': items, 'bytes': sum(os.path.getsize(os.path.join(stage, x['file'])) for x in items),
                        'seconds': sum(x['seconds'] for x in items), 'needBytes': sum(x['blocks'] for x in items) * 16384}
            tmp = os.path.join(CLONE_DIR, 'manifest.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=1)
            os.replace(tmp, os.path.join(CLONE_DIR, 'manifest.json'))
            return {'ok': True, 'tracks': len(items), 'bytes': manifest['bytes'], 'title': disc_title}
        except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError, RuntimeError, OSError) as exc:
            shutil.rmtree(CLONE_DIR, ignore_errors=True)
            return {'error': 'Copying the disc to this PC failed: %s Nothing was changed on the disc.' % exc}
        finally:
            self._release_devices()

    def clone_target(self, index):
        """Reads the disc now in the recorder and says whether the saved copy can be written to it. Reads only."""
        m = self._clone_manifest()
        if not m:
            return {'error': 'There is no saved copy of a disc to write.'}
        r = self.load(int(index))
        if 'error' in r:
            return r
        if m.get('type') == 'netmd':                           # the copy is of a standard disc: it needs a standard disc
            if r.get('mode') != 'netmd':
                return {'state': 'himdmode'}
            if r.get('discState') != 'ok':
                return {'state': r.get('discState') or 'none', 'message': r.get('discMessage', '')}
            d = r['disc']
            need = m['needUnits']
            return {'state': 'ok', 'netmd': True, 'same': False, 'empty': len(d['tracks']) == 0, 'tracks': len(d['tracks']), 'title': d['title'],
                    'free': d['free'], 'total': d['total'], 'need': need, 'fits': need * 1.01 + 2 * UNITS_PER_SECOND <= d['free'],
                    'writeProtected': bool(d.get('writeProtected')), 'perSecond': UNITS_PER_SECOND}
        if r.get('mode') == 'netmd' and r.get('discState') == 'ok':
            return {'state': 'netmd', 'canHimd': bool(r.get('canHimd')), 'tracks': len((r.get('disc') or {}).get('tracks', []))}
        if r.get('discState') != 'ok':
            return {'state': r.get('discState') or 'none', 'message': r.get('discMessage', '')}
        d = r['disc']
        need = m['needBytes'] + 2 * 16384 * len(m['tracks']) + 1000 * 1000
        same = bool(self._disc_key) and self._disc_key == m['sourceId']
        return {'state': 'ok', 'same': same, 'empty': len(d['tracks']) == 0, 'tracks': len(d['tracks']), 'title': d['title'], 'free': d['free'],
                'total': d['total'], 'need': need, 'fits': need < d['free'] * 0.98}

    @staticmethod
    def _md_clean(s):
        """The title as a standard disc stores it (plain ASCII), to compare what was asked for with what the disc holds."""
        import unicodedata
        s = re.sub(r'[^\x20-\x7e]', '', unicodedata.normalize('NFKD', str(s or '')))
        return re.sub(r'\s+', ' ', s).strip()[:120]

    def _clone_write_netmd(self, index, m):
        """WRITES TO THE DISC: a saved copy of a standard disc, onto an empty standard disc. See the note above."""
        stage = os.path.join(CLONE_DIR, 'stage')
        tell = self._clone_tell
        items = m['tracks']
        count = len(items)
        keep = ' The copy on this PC is kept, so you can erase the disc and try again.'
        tell(phase='copycheck', n=0, count=count, name='', done=0, total=0)
        try:
            for it in items:                                    # the PC copy must still be exactly what was read
                p = os.path.join(stage, it['file'])
                if not os.path.isfile(p) or os.path.getsize(p) != it['bytes']:
                    return {'error': 'The saved copy is incomplete or damaged (%s). Discard it and copy the disc again.' % it['file']}
                digest = hashlib.sha256()
                with open(p, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        digest.update(chunk)
                if digest.hexdigest() != it['sha']:
                    return {'error': 'The saved copy on this PC is damaged (%s). Discard it and copy the disc again.' % it['file']}
            tgt = self.clone_target(index)
            if 'error' in tgt:
                return tgt
            if tgt['state'] != 'ok':
                return {'error': 'There is no readable standard disc in the recorder.'}
            if tgt['writeProtected']:
                return {'error': 'The disc is write-protected. Slide its tab to make it writable.'}
            if not tgt['empty']:
                return {'error': 'This disc is not empty (%d tracks). Erase it first, or insert an empty disc.' % tgt['tracks']}
            if not tgt['fits']:
                return {'error': 'The copy does not fit on this disc: it needs about %d minutes of SP and the disc has %d minutes free.' % (tgt['need'] // UNITS_PER_SECOND // 60, tgt['free'] // UNITS_PER_SECOND // 60)}
            self._drop_cache()
            specs = [{'title': it['title'], 'codec': it['codec'].split(' ')[0], 'file': os.path.join(stage, it['file']), 'kind': it['kind'], 'seconds': it['seconds']} for it in items]
            with self._lock:
                res = self._run_helper('upload_clone', {'tracks': specs, 'rawTitle': m.get('rawTitle'), 'rawTitleW': m.get('rawTitleW')}, lambda e: tell(
                    phase='writing', n=e.get('file', 0), count=count, name=e.get('name', ''), done=e.get('done', 0), total=e.get('total', 0)) if e.get('event') == 'progress' else None,
                    helper=NETMD_HELPER)
            if 'error' in res:
                return {'error': 'Writing the tracks failed: %s The disc now holds a partly written copy.%s' % (res['error'], keep), 'partial': True}

            tell(phase='checking', n=0, count=count, name='', done=0, total=0)
            with self._lock:
                res = self._run_helper('list', {}, helper=NETMD_HELPER)
            if 'error' in res:
                return {'error': 'The copy was written, but reading the disc back failed: %s%s' % (res['error'], keep), 'partial': True}
            d = res['result']
            got = sorted((t for g in d['groups'] for t in g['tracks']), key=lambda t: t['index'])
            problems = []
            if len(got) != count:
                problems.append('the disc has %d tracks, expected %d' % (len(got), count))
            else:
                for k, (it, t) in enumerate(zip(items, got)):
                    if self._md_clean(t['title']) != self._md_clean(it['title']):
                        problems.append('track %d has the title “%s”' % (k + 1, t['title']))
                    elif t['codec'] != it['codec'].split(' ')[0]:
                        problems.append('track %d is %s, expected %s' % (k + 1, t['codec'], it['codec'].split(' ')[0]))
                    elif abs(t['seconds'] - it['seconds']) > 2:
                        problems.append('track %d is %d s long, expected %d s' % (k + 1, t['seconds'], it['seconds']))
                if [(g['title'], len(g['tracks'])) for g in d['groups'] if g['tracks']] != [(g['title'], g['count']) for g in m['groups'] if g['count']] or (d['discTitle'] or '') != m['discTitle']:
                    problems.append('the disc name or the groups are not the same as the original’s')
            if problems:
                return {'error': 'The copy was written, but the disc does not match: %s.%s' % ('; '.join(problems[:3]), keep), 'partial': True}
            shutil.rmtree(CLONE_DIR, ignore_errors=True)
            mono = sum(1 for it in items if it['codec'] == 'SP mono')
            return {'ok': True, 'tracks': count, 'verified': True, 'netmd': True, 'bytes': m['bytes'], 'cover': False, 'monoSp': mono,
                    'deleted': not os.path.exists(CLONE_DIR)}
        except (RuntimeError, OSError) as exc:
            return {'error': 'Cloning stopped: %s%s' % (exc, keep), 'partial': True}

    def clone_write(self, index):
        """WRITES TO THE DISC: the saved copy, in order, then groups, name and picture, then a byte-for-byte check. See the note above."""
        index = int(index)
        m = self._clone_manifest()
        if not m:
            return {'error': 'There is no saved copy of a disc to write.'}
        if m.get('type') == 'netmd':
            return self._clone_write_netmd(index, m)
        stage = os.path.join(CLONE_DIR, 'stage')
        tell = self._clone_tell
        items = m['tracks']
        count = len(items)
        keep = ' The copy on this PC is kept, so you can format the disc and try again.'
        self._clone_cancel = False
        tmp = tempfile.mkdtemp(prefix='mdm-clone-')
        try:
            tell(phase='copycheck', n=0, count=count, name='', done=0, total=0)
            for k, it in enumerate(items):                      # the PC copy must still be exactly what was read
                p = os.path.join(stage, it['file'])
                if not os.path.isfile(p):
                    return {'error': 'The saved copy is incomplete (%s is missing). Discard it and copy the disc again.' % it['file']}
                if self._clone_core(p, it['kind'])[1:] != (it['bytes'], it['sha']):
                    return {'error': 'The saved copy on this PC is damaged (%s). Discard it and copy the disc again.' % it['file']}
            tgt = self.clone_target(index)
            if 'error' in tgt:
                return tgt
            if tgt['state'] != 'ok':
                return {'error': 'There is no readable Hi-MD disc in the recorder.'}
            if tgt['same']:
                return {'error': 'This is the disc the copy was made from. Insert the disc you want to write to.'}
            if not tgt['empty']:
                return {'error': 'This disc is not empty (%d tracks). Format it first, or insert an empty disc.' % tgt['tracks']}
            if not tgt['fits']:
                return {'error': 'The copy does not fit on this disc: it needs about %d MB and the disc has %d MB free.' % (tgt['need'] // 1000000, tgt['free'] // 1000000)}
            self._drop_cache()
            with self._lock:
                res = self._run_helper('backup', {'dir': os.path.join(BACKUP_DIR, 'clone_before_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})
            if 'error' in res:
                return {'error': 'Could not back up the disc’s index first: %s Nothing was written.' % res['error']}

            runs = []                                           # consecutive tracks of one kind are written in one go
            for it in items:
                if runs and runs[-1][0] == it['kind']:
                    runs[-1][1].append(it)
                else:
                    runs.append((it['kind'], [it]))
            pos = 0
            for kind, group in runs:
                if pos:
                    self._reconnect(index)
                first = pos
                label = group[0]['title'] or 'Track %d' % (pos + 1)
                tell(phase='writing', n=pos, count=count, name=label, done=0, total=0)
                specs = []
                for it in group:
                    p = os.path.join(stage, it['file'])
                    s = {'title': it['title'], 'artist': it['artist'], 'album': it['album']}
                    if kind == 'atrac':
                        s.update(frames=p, skip=it['skip'], codecId=it['codecId'], codecInfo=it['ci'])
                    else:
                        s['path'] = p
                    specs.append(s)
                cmd, args = ('upload_frames', {'files': specs}) if kind == 'atrac' else ('upload', {'files': specs, 'format': kind})
                with self._lock:
                    res = self._run_helper(cmd, args, lambda e, first=first: tell(phase='writing', n=first + e.get('file', 0), count=count, name=e.get('name', ''),
                                                                                    done=e.get('done', 0), total=e.get('total', 0)) if e.get('event') == 'progress' else None)
                if 'error' in res:
                    return {'error': 'Writing tracks %d–%d failed: %s The disc now holds a partly written copy.%s' % (first + 1, first + len(group), res['error'], keep), 'partial': True}
                pos += len(group)

            tell(phase='finishing', n=0, count=count, name='', done=0, total=0)          # groups, disc name, picture
            self._reconnect(index)
            groups = [(g['first'], g['last'], g['title']) for g in m['groups']]
            r = self._edit(index, 'clone: groups and disc name', lambda d: (d.set_groups(groups), d.rename_disc(m['discTitle'])))
            if 'error' in r:
                return {'error': 'The tracks were written, but setting the groups and disc name failed: %s%s' % (r['error'], keep), 'partial': True}
            cover_note = ''
            if m.get('cover'):
                cdir = tempfile.mkdtemp(prefix='mdm-cover-')
                try:
                    shutil.copyfile(os.path.join(stage, m['cover']), os.path.join(cdir, 'COVER.JPG'))
                    r = self.cover_set(index, os.path.join(cdir, 'COVER.JPG'))
                finally:
                    shutil.rmtree(cdir, ignore_errors=True)
                if 'error' in r:
                    cover_note = ' The disc picture could not be stored: %s' % r['error']
            if cover_note:
                return {'error': 'The tracks, groups and name are on the disc, but the disc is not complete.%s%s' % (cover_note, keep), 'partial': True}

            tell(phase='checking', n=0, count=count, name='', done=0, total=0)         # what the disc now says it holds
            try:
                with self._lock:
                    dev = self._reconnect(index)
                    disc2 = himd_disc.Disc(himd_fs.Fat16(dev))
                    if disc2.track_count() != count:
                        raise himd_fs.FatError('the disc has %d tracks, expected %d' % (disc2.track_count(), count))
                    for k, it in enumerate(items):
                        t = disc2.track(k)
                        ok = (t['title'] == (it['title'] or '(untitled)') and t['artist'] == it['artist'] and t['album'] == it['album'] and t['codec'] == it['codec']
                              and abs(t['seconds'] - it['seconds']) <= 1 and (it['kind'] != 'atrac' or (t['codecId'] == it['codecId'] and t['ci'] == it['ci'])))
                        if not ok:
                            raise himd_fs.FatError('track %d is not as expected' % (k + 1))
                    if [(g['first'], g['last'], g['title']) for g in disc2.groups()] != groups or disc2.disc_title() != m['discTitle']:
                        raise himd_fs.FatError('the groups or the disc name are not as expected')
                    self._release_devices()
            except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError) as exc:
                return {'error': 'The copy was written, but checking the disc failed: %s.%s' % (exc, keep), 'partial': True}

            for k, it in enumerate(items):                                       # read every track back and compare the audio byte for byte
                label = it['title'] or 'Track %d' % (k + 1)
                tell(phase='verifying', n=k, count=count, name=label, done=0, total=0)
                back = os.path.join(tmp, 'back.%s' % it['file'].rsplit('.', 1)[1])
                with self._lock:
                    res = self._run_helper('dump', {'index': k, 'out': back, 'exact': True, 'raw': it['kind'] == 'atrac'}, lambda e, k=k, label=label: tell(
                        phase='verifying', n=k, count=count, name=label, done=e.get('done', 0), total=e.get('total', 0)) if e.get('event') == 'progress' else None)
                if 'error' in res:
                    return {'error': 'Track %d was written but could not be read back to check it: %s%s' % (k + 1, res['error'], keep), 'partial': True}
                got = self._clone_core(back, it['kind'])[1:]
                os.remove(back)
                if got != (it['bytes'], it['sha']):
                    return {'error': 'Track %d (“%s”) on the new disc does not match the original. Do not rely on this disc.%s' % (k + 1, label, keep), 'partial': True}
            shutil.rmtree(CLONE_DIR, ignore_errors=True)                         # everything matched: the PC copy has done its job
            return {'ok': True, 'tracks': count, 'verified': True, 'bytes': m['bytes'], 'cover': bool(m.get('cover')), 'deleted': not os.path.exists(CLONE_DIR)}
        except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError, RuntimeError, OSError) as exc:
            return {'error': 'Cloning stopped: %s%s' % (exc, keep), 'partial': True}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self._release_devices()
