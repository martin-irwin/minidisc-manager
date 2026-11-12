"""The disc catalogue: every disc this app has loaded (Hi-MD and standard), kept on this PC so it can be searched without the disc. CatalogueMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import datetime
import hashlib
import json
import os

from mdm_paths import USER_DIR

# The recorder-helper commands that change a standard disc. After one of them the next load of that disc is the same disc, changed.
NETMD_WRITES = ('upload', 'upload_clone', 'delete', 'move', 'format', 'rename')


class CatalogueMixin:
    CATALOGUE_FILE = os.path.join(USER_DIR, 'catalogue.json')

    def _catalogue_init(self):
        self._netmd_wrote = False         # this app changed the standard disc since it was last loaded
        self._netmd_last_key = None       # the catalogue key of the standard disc loaded last
        self._catalogue_current = None    # the key of the disc the page is showing now

    def _catalogue_read(self):
        try:
            with open(self.CATALOGUE_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _catalogue_write(self, data):
        os.makedirs(USER_DIR, exist_ok=True)
        tmp = self.CATALOGUE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.CATALOGUE_FILE)

    def _catalogue_note(self, key, title, tracks, model='', kind='hi-md'):
        """Remembers this disc (called on every load). Written only when something changed."""
        if not key:
            return
        self._catalogue_current = key
        try:
            entry = {'kind': kind, 'title': title or '', 'model': model or '', 'tracks': [
                {'n': t['number'], 'title': t['title'], 'artist': t.get('artist', ''), 'album': t.get('album', ''), 'codec': t['codec'],
                 'kbps': t.get('kbps') or 0, 'seconds': t['seconds']} for t in tracks]}
            data = self._catalogue_read()
            old = data.get(key) or {}
            if {k: old.get(k) for k in entry} == entry:
                return
            entry['seen'] = datetime.datetime.now().isoformat(timespec='minutes')
            data[key] = entry
            self._catalogue_write(data)
        except Exception:
            pass                                             # the catalogue is a convenience: never let it break loading a disc

    DETAILS_FILE = os.path.join(USER_DIR, 'netmd-details.json')

    @staticmethod
    def _netmd_disc_key(tracks):
        return ('md-' + hashlib.sha1(('%d|%s' % (len(tracks), ','.join(str(t['seconds']) for t in tracks))).encode()).hexdigest()[:16]) if tracks else None

    def _details_read(self):
        try:
            with open(self.DETAILS_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _netmd_details_apply(self, tracks):
        """A standard disc cannot store an artist or album, so this PC remembers them: per disc (recognised like the catalogue does), each
        entry the track lengths with their artist and album. A disc whose tracks were added, deleted or moved is still found when most of its
        track lengths match. Fills the artist and album of `tracks` in place."""
        try:
            data = self._details_read()
            entry = data.get(self._netmd_disc_key(tracks))
            if entry is None:
                have = [t['seconds'] for t in tracks]
                best, bestn = None, 0
                for e in data.values():
                    sec = [x.get('s') for x in e.get('tracks', [])]
                    n = sum(min(sec.count(s), have.count(s)) for s in set(have) & set(sec))
                    if n > bestn:
                        best, bestn = e, n
                if best is not None and bestn >= max(2, int(len(tracks) * 0.6)):
                    entry = best
            if not entry:
                return
            pool = list(entry.get('tracks', []))
            for t in tracks:
                for i, x in enumerate(pool):
                    if x.get('s') == t['seconds']:
                        t['artist'], t['album'] = x.get('a') or '', x.get('b') or ''
                        pool.pop(i)
                        break
        except Exception:
            pass                                             # a convenience: never let it break loading a disc

    def set_netmd_details(self, index, items):
        """Remembers artist / album for tracks of a standard disc on this PC only (the disc cannot hold them). `items`: [{number, artist, album}];
        a field that is left out (null) stays as it is, an empty text removes it."""
        if not self._is_netmd(index):
            return {'error': 'Only standard discs keep their artist and album on this PC; a Hi-MD disc stores them itself.'}
        try:
            for it in items or []:
                t = next((x for x in self._tracks if x['number'] == int(it['number'])), None)
                if t is None:
                    continue
                for k in ('artist', 'album'):
                    if it.get(k) is not None:
                        t[k] = str(it[k]).strip()
            key = self._netmd_disc_key(self._tracks)
            data = self._details_read()
            entry = [{'s': t['seconds'], 'a': t.get('artist', ''), 'b': t.get('album', '')} for t in self._tracks]
            if any(x['a'] or x['b'] for x in entry):
                data[key] = {'tracks': entry}
            else:
                data.pop(key, None)
            os.makedirs(USER_DIR, exist_ok=True)
            tmp = self.DETAILS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.DETAILS_FILE)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            return {'error': 'Could not save the artist and album on this PC: %s' % exc}
        return {'ok': True}

    # ---- Names that could not be written (write-protected disc) are kept on this PC and offered again when the disc is loaded writable --------
    PENDING_FILE = os.path.join(USER_DIR, 'pending-names.json')

    def _pending_read(self):
        try:
            with open(self.PENDING_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _pending_write(self, data):
        os.makedirs(USER_DIR, exist_ok=True)
        tmp = self.PENDING_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.PENDING_FILE)

    def _pending_find(self, data, tracks):
        """The key of the saved entry for this disc: the same track count and lengths, or most of the lengths (a disc that was edited since)."""
        key = self._netmd_disc_key(tracks)
        if key in data:
            return key
        have = [t['seconds'] for t in tracks]
        best, bestn = None, 0
        for k, e in data.items():
            sec = [x.get('s') for x in e.get('tracks', [])]
            n = sum(min(sec.count(s), have.count(s)) for s in set(have) & set(sec))
            if n > bestn:
                best, bestn = k, n
        return best if best is not None and bestn >= max(2, int(len(tracks) * 0.6)) else None

    def pending_names_save(self, items):
        """Keeps names the app wanted to write but could not (the disc is write-protected). items: [{number, title, artist, album}]. Never raises."""
        try:
            tracks = self._tracks or []
            data = self._pending_read()
            key = self._pending_find(data, tracks) or self._netmd_disc_key(tracks)
            if not key:
                return
            by_s = {x['s']: x for x in data.get(key, {}).get('tracks', []) if x.get('s') is not None}
            for it in items or []:
                t = next((x for x in tracks if x['number'] == int(it['number'])), None)
                title = str(it.get('title') or '').strip()
                if t is None or not title:
                    continue
                by_s[t['seconds']] = {'s': t['seconds'], 'title': title, 'artist': str(it.get('artist') or '').strip(), 'album': str(it.get('album') or '').strip()}
            if by_s:
                data[key] = {'tracks': list(by_s.values()), 'saved': datetime.datetime.now().isoformat(timespec='minutes')}
                self._pending_write(data)
        except Exception:
            pass

    def pending_names_check(self):
        """What this PC kept for the loaded disc and the disc does not have yet: {'items': [{number, title, artist, album}]}."""
        try:
            tracks = self._tracks or []
            data = self._pending_read()
            key = self._pending_find(data, tracks) if tracks else None
            if key is None:
                return {'items': []}
            pool, items = list(data[key].get('tracks', [])), []
            for t in tracks:
                for i, x in enumerate(pool):
                    if x.get('s') == t['seconds']:
                        pool.pop(i)
                        diff = (x.get('title') or '').strip().lower() != (t.get('title') or '').strip().lower()
                        if not getattr(self, '_loaded_netmd', False):             # a standard disc keeps artist / album on this PC anyway
                            diff = diff or ((x.get('artist') or '') != (t.get('artist') or '')) or ((x.get('album') or '') != (t.get('album') or ''))
                        if diff and x.get('title'):
                            items.append({'number': t['number'], 'title': x['title'], 'artist': x.get('artist') or '', 'album': x.get('album') or ''})
                        break
            return {'items': items}
        except Exception:
            return {'items': []}

    def pending_names_clear(self):
        try:
            data = self._pending_read()
            key = self._pending_find(data, self._tracks or [])
            if key is not None:
                data.pop(key, None)
                self._pending_write(data)
        except Exception:
            pass
        return {'ok': True}

    def _catalogue_note_netmd(self, title, tracks, model=''):
        """A standard disc has no serial number, so it is recognised by its track count and track lengths (a rename keeps them). When this
        app has added, deleted or moved tracks since the last load, the changed disc replaces the old entry instead of becoming a second one."""
        try:
            key = self._netmd_disc_key(tracks)
            old = self._netmd_last_key
            if self._netmd_wrote and old and old != key:
                data = self._catalogue_read()
                if data.pop(old, None) is not None:
                    self._catalogue_write(data)
            self._netmd_wrote = False
            self._netmd_last_key = key
            if key:
                self._catalogue_note(key, title, tracks, model, 'standard')
            else:
                self._catalogue_current = None               # a blank disc is not worth an entry
        except Exception:
            pass

    def catalogue_list(self):
        data = self._catalogue_read()
        discs = [dict(v, id=k) for k, v in data.items() if isinstance(v, dict)]
        discs.sort(key=lambda d: d.get('seen', ''), reverse=True)
        return {'discs': discs, 'current': self._catalogue_current}

    def catalogue_remove(self, key):
        data = self._catalogue_read()
        if data.pop(str(key), None) is not None:
            try:
                self._catalogue_write(data)
            except OSError as exc:
                return {'error': str(exc)}
        return {'ok': True}
