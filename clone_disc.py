"""Cloning a Hi-MD disc to another disc through this PC. CloneMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import hashlib
import json
import os
import shutil

from mdm_common import CLONE_MAX_PCM
from mdm_paths import CLONE_DIR


class CloneMixin:
    def _clone_init(self):
        self._clone_cancel = False

    # 1. clone_read: every track is read off the source disc into CLONE_DIR\stage, exactly as stored (PCM as WAV, ATRAC as its frames,
    #    MP3 as its frames), with a manifest of the titles, groups, disc name and picture. Nothing is written to the source.
    # 2. The user swaps discs. clone_target says whether the new disc is a different, empty disc with room.
    # 3. clone_write: the tracks are written in the source's order with their own codec fields (nothing is decoded or encoded), then the
    #    groups, disc name and picture, then every track is read back and compared byte for byte with the PC copy. Only when all of
    #    that passes is the PC copy deleted. If anything fails the PC copy stays so the user can format the disc and try again.
    @staticmethod
    def _clone_kind(t):
        return {'PCM': 'pcm', 'MP3': 'mp3', 'A3+': 'atrac', 'AT3': 'atrac'}.get(t['codec'])

    @staticmethod
    def _clone_manifest():
        try:
            with open(os.path.join(CLONE_DIR, 'manifest.json'), encoding='utf-8') as f:
                m = json.load(f)
            return m if m.get('complete') else None
        except (OSError, ValueError):
            return None

    def _clone_tell(self, **msg):
        if self._window:
            try:
                self._window.evaluate_js('window.onCloneProgress && window.onCloneProgress(%s)' % json.dumps(msg))
            except Exception:
                pass

    @staticmethod
    def _clone_core(path, kind, t=None):
        """(bytes to skip, audio bytes, SHA-256 of the audio) of a staged or read-back file: the part that must survive the copy unchanged.
        PCM: after the 44-byte WAV header. ATRAC: after the 96-byte EA3 header. MP3: after the ID3 tag the helper puts in front."""
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            head = f.read(10)
            if kind == 'pcm':
                skip = 44
            elif kind == 'atrac':
                skip = 96
            else:
                skip = 0
                if head[:3] == b'ID3' and len(head) == 10:
                    skip = 10 + ((head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F)) + (10 if head[5] & 0x10 else 0)
            if size <= skip:
                raise RuntimeError('The audio read from the disc is empty.')
            f.seek(skip)
            digest = hashlib.sha256()
            for chunk in iter(lambda: f.read(1 << 20), b''):
                digest.update(chunk)
        return skip, size - skip, digest.hexdigest()

    def clone_status(self):
        """Is a PC copy of a disc waiting to be written? (It survives closing the program.)"""
        m = self._clone_manifest()
        if not m:
            return {'pending': None}
        return {'pending': {'title': m['discTitle'], 'tracks': len(m['tracks']), 'bytes': m['bytes'], 'when': m['when'], 'seconds': m['seconds'],
                            'type': m.get('type', 'himd')}}

    def clone_discard(self):
        """Deletes the PC copy."""
        shutil.rmtree(CLONE_DIR, ignore_errors=True)
        return {'ok': not os.path.exists(CLONE_DIR)}

    def clone_cancel(self):
        self._clone_cancel = True
        return self._stop_transfer()

    def _clone_wanted(self, numbers):
        """The loaded tracks to copy: those whose numbers are given (None: all of them). Raises RuntimeError for an empty or unknown choice."""
        if numbers is None:
            return list(self._tracks)
        wanted = {int(n) for n in numbers}
        tracks = [t for t in self._tracks if t['number'] in wanted]
        if not tracks or len(tracks) != len(wanted):
            raise RuntimeError('Choose at least one track to copy.' if not wanted else 'Those tracks are no longer on the disc. Reload it.')
        return tracks

    @staticmethod
    def _clone_remap_groups(groups, kept):
        """Hi-MD groups after leaving tracks out: `groups` [{first, last, title}] count tracks from 1; `kept` is the sorted list of original
        numbers still copied, which become 1..n in the same order. A group with no kept track disappears."""
        pos = {n: i + 1 for i, n in enumerate(kept)}
        out = []
        for g in groups:
            ns = [pos[n] for n in range(g['first'], g['last'] + 1) if n in pos]
            if ns:
                out.append({'first': ns[0], 'last': ns[-1], 'title': g['title']})
        return out

    def clone_plan(self, index, numbers=None):
        """Checks that the loaded disc can be copied and that this PC has room for it. Reads nothing from the recorder.
        `numbers`: copy only these tracks (None: all of them)."""
        if self._is_netmd(index):
            return self._clone_plan_netmd(index, numbers)
        if self._clone_manifest():
            return {'error': 'A saved copy of a disc is already waiting on this PC. Write it to a disc or discard it first.', 'pending': True}
        try:
            tracks = self._clone_wanted(numbers)
        except RuntimeError as exc:
            return {'error': str(exc)}
        if not tracks:
            return {'error': 'This disc has no tracks to copy.'}
        bad = [t['number'] for t in tracks if self._clone_kind(t) is None]
        if bad:
            return {'error': 'Track %s uses a format this app cannot read, so the disc cannot be cloned.' % ', '.join(map(str, bad))}
        big = [t['number'] for t in tracks if t['codec'] == 'PCM' and t['seconds'] * 176400 > CLONE_MAX_PCM]
        if big:
            return {'error': 'Track %s is a PCM track longer than %d minutes, which is more than can be written back in one piece.' % (', '.join(map(str, big)), CLONE_MAX_PCM // 176400 // 60)}
        need = sum(t['blocks'] for t in tracks) * 16384
        os.makedirs(CLONE_DIR, exist_ok=True)
        free = shutil.disk_usage(CLONE_DIR).free
        return {'tracks': len(tracks), 'seconds': sum(t['seconds'] for t in tracks), 'needBytes': need, 'freeBytes': free,
                'fits': free > need * 1.05 + 200 * 1000 * 1000}
