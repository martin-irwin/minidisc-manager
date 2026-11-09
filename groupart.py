"""A picture for each group of tracks on a Hi-MD disc.

The pictures are kept on this PC (groupart.json, per disc, by group name) and can be copied onto the disc as one small file, /GROUPART.JSN in the
root folder (next to COVER.JPG, LYRICS.TXT and TRACKS.CSV), so they travel with the disc. The recorder ignores the file. A group belongs to its picture
by its name, so a group needs a name before it can have a picture; renaming a group carries its picture along. GroupArtMixin is mixed into himd_app.Api.
"""
import base64
import json
import os
import shutil
import tempfile
import time

from mdm_paths import BACKUP_DIR, USER_DIR

ART_FILE = os.path.join(USER_DIR, 'groupart.json')            # {disc key: {group name: 'data:image/jpeg;base64,...'}}
DISC_NAME = 'GROUPART.JSN'                                    # the copy kept in the root folder of a Hi-MD disc
MAX_BYTES = 60000                                             # one small picture (the app shows it a few hundred pixels wide at most)


class GroupArtMixin:
    def _ga_read(self):
        try:
            with open(ART_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _ga_write(self, d):
        tmp = ART_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, ART_FILE)

    def _ga_key(self):
        return getattr(self, '_disc_key', None) or ''

    def _ga_state(self):
        """What the page needs: the pictures kept on this PC and the ones read from the disc, for the disc now loaded."""
        return {'pc': self._ga_read().get(self._ga_key(), {}) if self._ga_key() else {}, 'disc': getattr(self, '_ga_disc', None) or {}}

    def _ga_for_track(self, number):
        """The picture (a data URL) of the group that track `number` is in, or '' (no group, no name, or no picture)."""
        try:
            t = next((x for x in self._tracks if x.get('number') == number), None)
            title = (t or {}).get('groupTitle')
            if not title:
                return ''
            st = self._ga_state()
            return st['pc'].get(title) or st['disc'].get(title) or ''
        except Exception:
            return ''

    @staticmethod
    def _ga_parse(data):
        """{group name: data URL} from the bytes of GROUPART.JSN; anything unreadable gives {}."""
        try:
            d = json.loads(bytes(data).decode('utf-8-sig'))
            out = {}
            for name, url in (d.get('groups') or {}).items():
                if isinstance(name, str) and isinstance(url, str) and url.startswith('data:image/jpeg;base64,'):
                    out[name] = url
            return out
        except (ValueError, AttributeError, UnicodeDecodeError):
            return {}

    def _ga_shrink(self, path):
        """A small JPEG data URL (at most 360 pixels a side) from any picture file, or None."""
        folder = tempfile.mkdtemp(prefix='mdm-groupart-')
        try:
            out = os.path.join(folder, 'g.jpg')
            for q in ('4', '8', '12', '18'):
                try:
                    self._ffmpeg(['-i', path, '-frames:v', '1', '-vf', "scale='min(360,iw)':'min(360,ih)':force_original_aspect_ratio=decrease",
                                  '-pix_fmt', 'yuvj420p', '-q:v', q, out])
                except RuntimeError:
                    return None
                if os.path.getsize(out) <= MAX_BYTES:
                    break
            with open(out, 'rb') as f:
                return 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode()
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _ga_store(self, title, url):
        key = self._ga_key()
        if not key:
            return {'error': 'This disc cannot be recognised, so a picture cannot be kept for it.'}
        title = (title or '').strip()
        if not title:
            return {'error': 'Give the group a name first; its picture is kept under that name.'}
        d = self._ga_read()
        d.setdefault(key, {})[title] = url
        self._ga_write(d)
        return dict(self._ga_state(), ok=True)

    def groupart_set(self, title, path):
        """Keeps a picture the user chose from a file for the group `title` (on this PC only)."""
        if getattr(self, '_loaded_netmd', False):
            return {'error': 'Only Hi-MD discs have groups with pictures.'}
        url = self._ga_shrink(path)
        if not url:
            return {'error': 'That file could not be read as a picture.'}
        return self._ga_store(title, url)

    def groupart_from_tmp(self, title, tmp):
        """Keeps a picture the online search just downloaded (the prepared file in a mdm-cover- folder) for the group `title`."""
        if not tmp or not os.path.isfile(tmp) or not os.path.basename(os.path.dirname(tmp)).startswith('mdm-cover-'):
            return {'error': 'The picture is no longer available; choose it again.'}
        url = self._ga_shrink(tmp)
        if not url:
            return {'error': 'That picture could not be read.'}
        return self._ga_store(title, url)

    def groupart_from_cd(self, title, cover_id):
        """Keeps the cover chosen in the CD rip window (cd_audio's _cd_cover; `cover_id` says which one) as the picture of the group `title`, on this PC."""
        c = getattr(self, '_cd_cover', None)
        if getattr(self, '_loaded_netmd', False):
            return {'error': 'Only Hi-MD discs have groups with pictures.'}
        if not c or not cover_id or c.get('id') != cover_id:
            return {'error': 'The CD cover is no longer available.'}
        return self._ga_from_bytes(title, c['bytes'])

    def _ga_from_bytes(self, title, data):
        """Keeps the picture whose file bytes are `data` for the group `title`."""
        folder = tempfile.mkdtemp(prefix='mdm-groupart-')
        try:
            path = os.path.join(folder, 'cover.img')
            with open(path, 'wb') as f:
                f.write(data)
            url = self._ga_shrink(path)
        except OSError as exc:
            return {'error': 'The cover could not be read: %s' % exc}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        if not url:
            return {'error': 'That cover could not be read as a picture.'}
        return self._ga_store(title, url)

    def groupart_from_yoto(self, title, card_id):
        """Keeps the cover of the Yoto playlist `card_id` as the picture of the group `title`. {'none': True} if the playlist has no cover."""
        if getattr(self, '_loaded_netmd', False):
            return {'error': 'Only Hi-MD discs have groups with pictures.'}
        try:
            cover = self._yoto.card(card_id).get('cover')
            if not cover:
                return {'none': True}
            data = self._yoto.fetch_cover(cover)
        except Exception as exc:                                  # YotoError or a network problem
            return {'error': 'The playlist’s picture could not be fetched: %s' % exc}
        if not data:
            return {'error': 'The playlist’s picture could not be fetched.'}
        return self._ga_from_bytes(title, data)

    def groupart_from_site(self, title, track_id, site):
        """Keeps the album picture of a recorded track (Bandcamp, SoundCloud, …; `track_id` as given to bc_add) as the picture of the group `title`.
        {'none': True} if the track has no picture (internet radio, for one)."""
        if getattr(self, '_loaded_netmd', False):
            return {'error': 'Only Hi-MD discs have groups with pictures.'}
        try:
            import bandcamp
            rec = self._recs.get(self._site(site))
            items = rec.paths({int(track_id)}) if rec else []
            art = items[0].get('art') if items else None
            if not art:
                return {'none': True}
            data = bandcamp.fetch_cover(art)
        except Exception as exc:
            return {'error': 'The album picture could not be fetched: %s' % exc}
        if not data:
            return {'error': 'The album picture could not be fetched.'}
        return self._ga_from_bytes(title, data)

    def groupart_remove(self, title):
        """Forgets the picture of one group on this PC (the copy on the disc stays until 'Save group pictures to the disc' is pressed again)."""
        key = self._ga_key()
        d = self._ga_read()
        if key in d and title in d[key]:
            del d[key][title]
            if not d[key]:
                del d[key]
            self._ga_write(d)
        return dict(self._ga_state(), ok=True)

    def groupart_rename(self, old, new):
        """A group was renamed: its picture (on this PC) follows the new name."""
        key = self._ga_key()
        old, new = (old or '').strip(), (new or '').strip()
        d = self._ga_read()
        if key in d and old and new and old != new and old in d[key]:
            d[key][new] = d[key].pop(old)
            self._ga_write(d)
        disc = getattr(self, '_ga_disc', None)
        if disc and old in disc and new and old != new and new not in disc:
            disc[new] = disc.pop(old)
        return dict(self._ga_state(), ok=True)

    def groupart_save_disc(self, index):
        """WRITES A FILE TO THE DISC. Stores the pictures of the groups now on the disc as /GROUPART.JSN (replacing the earlier file). A group's
        picture on this PC wins over the disc's own copy; groups that no longer exist are left out. With no pictures left the file is removed."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold group pictures.'}
        names = {t.get('groupTitle') for t in self._tracks if t.get('groupTitle')}
        have = dict(getattr(self, '_ga_disc', None) or {})
        have.update(self._ga_state()['pc'])
        groups = {n: have[n] for n in sorted(names) if n in have}
        if not groups:
            if not getattr(self, '_ga_disc', None):
                return {'error': 'None of the named groups on this disc has a picture yet.'}
            with self._lock:
                res = self._run_helper('groupart_remove', {'backupDir': os.path.join(BACKUP_DIR, 'groupart_latest')})
            if 'error' in res:
                return res
            self._ga_disc = {}
            return dict(self._ga_state(), ok=True, saved=0)
        folder = tempfile.mkdtemp(prefix='mdm-groupart-')
        tmp = os.path.join(folder, DISC_NAME)
        try:
            with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'app': 'MiniDiscManager', 'version': 1, 'groups': groups}, f, ensure_ascii=False)
            res = {'error': 'not tried'}
            for attempt in range(3):                                                # a recorder can stay busy for a few seconds after a write
                with self._lock:
                    res = self._run_helper('groupart_set', {'file': tmp, 'backupDir': os.path.join(BACKUP_DIR, 'groupart_latest')})
                if 'error' not in res:
                    break
                time.sleep(2.5)
            if 'error' in res:
                self.log('groupart_save_disc failed: %s' % res['error'])
                return res
            self._ga_disc = dict(groups)
            return dict(self._ga_state(), ok=True, saved=len(groups))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
