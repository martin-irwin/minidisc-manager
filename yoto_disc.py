"""Yoto cards and MYO playlists: sending the disc's tracks to a Yoto playlist, and ripping a card onto the disc. YotoMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import json
import os
import shutil
import tempfile
import webbrowser

import yoto
from mdm_paths import HERE, USER_DIR


class YotoMixin:
    def _yoto_init(self):
        self._yoto = yoto.Yoto(USER_DIR, self.log)
        self._yoto_cancel = False

    # yoto.py talks to Yoto's developer API after a one-time browser sign-in. The page lists the family's players (with the card in each)
    # and the user's own playlists; the chosen playlist's audio is downloaded, decoded to WAV and written like "Add tracks".
    def yoto_state(self):
        """Whether the user is signed in to Yoto and, if so, the players (with their cards) and the user's own playlists."""
        if not self._yoto.signed_in():
            return {'signedIn': False}
        try:
            return {'signedIn': True, 'canManage': self._yoto.can_manage(), 'players': self._yoto.players(), 'playlists': self._yoto.playlists()}
        except yoto.YotoError as exc:
            self.log('yoto_state failed: %s' % exc)
            return {'signedIn': self._yoto.signed_in(), 'error': str(exc)}

    def yoto_sign_in(self):
        """Opens Yoto's login page in the browser and waits (up to 4 minutes) for the user to approve."""
        try:
            self._yoto.sign_in(webbrowser.open)
        except yoto.YotoError as exc:
            return {'error': str(exc)}
        return self.yoto_state()

    def yoto_cancel_sign_in(self):
        self._yoto.cancel_sign_in()
        return {'ok': True}

    def yoto_sign_out(self):
        self._yoto.sign_out()
        return {'signedIn': False}

    def yoto_card(self, card_id):
        """One playlist with its tracks (the download links are left out; they expire and are fetched again when ripping)."""
        try:
            c = self._yoto.card(card_id)
        except yoto.YotoError as exc:
            return {'error': str(exc)}
        return {'card': dict(c, cover=bool(c['cover']), tracks=[{k: v for k, v in t.items() if k != 'url'} for t in c['tracks']])}

    def yoto_cancel(self):
        self._yoto_cancel = True
        self._save_cancel = True
        return {'ok': True}

    def yoto_can_send(self):
        """Whether the Yoto sign-in allows creating a playlist (a sign-in made before 'Send to Yoto Card' existed does not)."""
        return {'signedIn': self._yoto.signed_in(), 'canManage': self._yoto.can_manage()}

    def yoto_playlists(self):
        """The user's own playlists, for choosing one to add tracks to."""
        try:
            return {'playlists': self._yoto.playlists()}
        except yoto.YotoError as exc:
            return {'error': str(exc)}

    def yoto_send(self, index, numbers, title, add_to=None):
        """Copies the chosen tracks of the disc in the recorder to the user's Yoto account (reads the disc only). The tracks are read like
        'Save to PC' (FLAC, in a temporary folder), uploaded and converted by Yoto, and then either put in a NEW playlist called `title`, or,
        if `add_to` is a playlist's card id, added at the END of that playlist (see yoto.append_to_playlist: backed up and checked). A new
        playlist is then linked to a blank card in the Yoto app; one that is already linked to a card needs nothing more."""
        index = int(index)
        title = (title or '').strip()
        if not title and not add_to:
            return {'error': 'Give the playlist a title.'}
        if not self._yoto.can_manage():
            return {'error': 'Sign in to Yoto again to allow creating a playlist.', 'needSignIn': True}
        tell = lambda **m: self._window and self._window.evaluate_js('window.onYotoProgress && window.onYotoProgress(%s)' % json.dumps(m))
        tmp = tempfile.mkdtemp(prefix='mdm-toyoto-')
        self._yoto_cancel = False
        try:
            names = {t['number']: (t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']) for t in self._tracks}
            r = self.save_tracks(index, numbers, tmp, 'flac')            # progress goes to the page as onSaveProgress
            if 'error' in r:
                return r
            if self._yoto_cancel or r.get('cancelled'):
                return {'cancelled': True}
            files = sorted(r['saved'], key=lambda s: s['number'])
            if not files:
                return {'error': 'None of the tracks could be read from the disc.', 'failed': r.get('failed', [])}
            items = []
            for i, s in enumerate(files):
                label = names.get(s['number'], 'Track %d' % s['number'])
                tell(phase='uploading', n=i, count=len(files), name=label, done=0, total=0)
                up = self._yoto.upload_audio(s['file'], progress=lambda d, tot, i=i, label=label: tell(
                    phase='uploading' if d < tot else 'converting', n=i, count=len(files), name=label, done=d, total=tot),
                    cancel=lambda: self._yoto_cancel)
                if up is None:
                    return {'cancelled': True}
                os.remove(s['file'])
                items.append(dict(up, title=label))
            tell(phase='creating', n=len(files), count=len(files), name='', done=0, total=0)
            seconds = sum(i['duration'] for i in items)
            if add_to:
                res = self._yoto.append_to_playlist(add_to, items, os.path.join(USER_DIR, 'yoto-backups'))
                self.log('yoto_send: added %d tracks to playlist %s %r (now %d), backup %s' % (len(items), add_to, res['title'], res['total'], res['backup']))
                return {'ok': True, 'cardId': add_to, 'title': res['title'], 'added': len(items), 'failed': r.get('failed', []), 'seconds': seconds,
                        'appended': True, 'total': res['total'], 'backup': res['backup']}
            card_id = self._yoto.create_playlist(title, items)
            self.log('yoto_send: created playlist %s %r with %d tracks' % (card_id, title, len(items)))
            return {'ok': True, 'cardId': card_id, 'title': title, 'added': len(items), 'failed': r.get('failed', []), 'seconds': seconds}
        except yoto.YotoError as exc:
            self.log('yoto_send failed: %s' % exc)
            return {'error': str(exc)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def yoto_rip_add(self, index, card_id, tracks, fmt='auto', mp3_kbps=192, disc_title='', store_cover=False):
        """WRITES TO THE DISC. `tracks`: [{key, title, artist, album}] of the playlist's tracks to copy, in the order to add them. `fmt` and
        the rest as for cd_rip_add()."""
        index = int(index)
        netmd = self._is_netmd(index)
        fmt = (fmt if fmt in ('sp', 'lp2', 'lp4') else 'sp') if netmd else (fmt if fmt in ('auto', 'pcm', 'mp3', 'lp2', 'lp4', 'at3p', 'hisp', 'hilp') else 'auto')
        if not tracks:
            return {'error': 'Choose at least one track to copy.'}
        tell = lambda **m: self._window and self._window.evaluate_js('window.onYotoProgress && window.onYotoProgress(%s)' % json.dumps(m))
        try:
            card = self._yoto.card(card_id)                       # fresh download links: they are only valid for a while
        except yoto.YotoError as exc:
            return {'error': str(exc)}
        by_key = {t['key']: t for t in card['tracks']}
        if any(t.get('key') not in by_key for t in tracks):
            return {'error': 'The playlist has changed on Yoto since it was opened. Open it again.'}
        seconds = sum(by_key[t['key']]['seconds'] for t in tracks)
        tmp = tempfile.mkdtemp(prefix='mdm-yoto-')
        self._yoto_cancel = False
        ffmpeg = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
        try:
            if shutil.disk_usage(tmp).free < seconds * 176400 * 1.15 + 200 * 1000 * 1000:
                return {'error': 'There is not enough free space on this PC’s temporary drive (about %d MB are needed).' % int(seconds * 176400 / 1e6)}
            files = []
            for i, t in enumerate(tracks):
                src = by_key[t['key']]
                label = (t.get('title') or '').strip() or src['title']
                tell(phase='downloading', n=i, count=len(tracks), name=label, done=0, total=0)
                raw = os.path.join(tmp, 'raw%02d.bin' % i)
                ok = self._yoto.download(src['url'], raw, progress=lambda d, tot, i=i, label=label: tell(
                    phase='downloading', n=i, count=len(tracks), name=label, done=d, total=tot), cancel=lambda: self._yoto_cancel)
                if not ok:
                    return {'cancelled': True}
                tell(phase='decoding', n=i, count=len(tracks), name=label, done=0, total=0)
                wav = os.path.join(tmp, 'track%02d.wav' % (i + 1))
                self._yoto.to_wav(ffmpeg, raw, wav)
                os.remove(raw)
                files.append({'path': wav, 'title': label, 'artist': (t.get('artist') or '').strip(), 'album': (t.get('album') or '').strip()})
            tell(phase='writing', n=0, count=len(files), name='', done=0, total=0)
            res = self.upload(files, fmt, mp3_kbps)
            if 'error' in res:
                return {'error': 'The audio was downloaded, but writing to the disc failed: %s' % res['error']}
            notes = []
            title = (disc_title or '').strip()
            if title or (store_cover and not netmd):
                try:
                    if not netmd:
                        self._reconnect(index)                  # a secure session can leave the recorder busy for a few seconds
                        self._release_devices()
                    if title:
                        r = self.rename_disc(index, title)
                        if 'error' in r:
                            notes.append('The disc name could not be set: %s' % r['error'])
                    if store_cover and not netmd:
                        data = self._yoto.fetch_cover(card['cover'])
                        if not data:
                            notes.append('The playlist’s picture could not be fetched, so the disc picture was left alone.')
                        else:
                            pic = os.path.join(tmp, 'cover.img')
                            with open(pic, 'wb') as f:
                                f.write(data)
                            prep = self.cover_prepare(pic)
                            r = prep if 'error' in prep else self.cover_set(index, prep['tmp'])
                            if 'error' in r:
                                notes.append('The cover could not be stored: %s' % r['error'])
                except Exception as exc:
                    notes.append('The disc name or cover could not be set: %s' % exc)
            self._release_devices()
            return {'ok': True, 'added': len(files), 'notes': notes, 'seconds': round(seconds)}
        except yoto.YotoError as exc:
            return {'error': str(exc)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
