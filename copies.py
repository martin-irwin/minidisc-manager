"""The app's saved copies of tracks added to (or read from) standard discs: FLAC files in COPIES_DIR plus an index.json that matches them by
title and length. CopiesMixin is mixed into himd_app.Api (which supplies _ffmpeg). Touches only files on this PC, never a disc."""
import json
import os
import secrets

from mdm_paths import COPIES_DIR


class CopiesMixin:
    # A standard disc gives a track no ID, so a copy is matched by title and length (to the second).
    @staticmethod
    def _copy_index():
        try:
            with open(os.path.join(COPIES_DIR, 'index.json'), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    @staticmethod
    def _write_copy_index(items):
        os.makedirs(COPIES_DIR, exist_ok=True)
        with open(os.path.join(COPIES_DIR, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=1)

    def _find_copy(self, title, seconds, index=None, codec=None):
        """`index`: the copies list, when the caller looks up many tracks and has read it once already.
        `codec`: the track's recording mode on the disc now (SP / LP2 / LP4): a copy saved in another mode is a different recording."""
        mode = codec.split()[0] if codec else None
        for c in reversed(self._copy_index() if index is None else index):                  # newest first
            if c['title'] == title and abs(c['seconds'] - seconds) <= 1 and os.path.exists(os.path.join(COPIES_DIR, c['id'] + '.flac')):
                if mode and c.get('codec') and c['codec'] != mode:
                    continue
                return c
        return None

    def _save_copies(self, items, fmt=None):
        if items:
            if fmt:
                items = [dict(c, codec=str(fmt).upper()) for c in items]                 # remembered so a later re-recording in another mode is not mistaken for it
            self._write_copy_index(self._copy_index() + list(items))

    def _keep_copy(self, src, t, replace=False):
        """Keeps audio just read from a standard disc (the slow, patched read) as the app's saved copy of that track, so Combine, Split and
        Identify can use it later without reading the disc again. `replace`: a fresh read supersedes an older copy. True when kept."""
        title, seconds, codec = t['title'], t['seconds'], (t.get('codec') or '').split()[0] or None
        dest = None
        try:
            if self._find_copy(title, seconds, codec=codec):
                if not replace:
                    return False
                self._drop_copy(title, seconds)
            os.makedirs(COPIES_DIR, exist_ok=True)
            cid = 'rd' + secrets.token_hex(6)
            dest = os.path.join(COPIES_DIR, cid + '.flac')
            self._ffmpeg(['-i', src, '-vn', '-c:a', 'flac', '-map_metadata', '-1', dest])
            self._write_copy_index(self._copy_index() + [{'id': cid, 'title': title, 'seconds': seconds, 'codec': codec}])
            return True
        except (RuntimeError, OSError):
            if dest:
                try:
                    os.remove(dest)
                except OSError:
                    pass
            return False

    def _drop_copy(self, title, seconds, new_title=None):
        """Forget (or retitle) the copy of a track that was deleted (or renamed) on the disc."""
        c = self._find_copy(title, seconds)
        if c is None:
            return
        items = [x for x in self._copy_index() if x['id'] != c['id']]
        if new_title is None:
            try:
                os.remove(os.path.join(COPIES_DIR, c['id'] + '.flac'))
            except OSError:
                pass
        else:
            items.append(dict(c, title=new_title))
        self._write_copy_index(items)
