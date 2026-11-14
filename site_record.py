"""Recording from the streaming-site windows (Bandcamp, SoundCloud, internet radio and the others in bandcamp.SITES): opening a site's window, recording the tracks as they play, and adding the recorded tracks to the disc. SiteRecordMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import csv
import json
import os

import bandcamp
import radio
import webview
from mdm_paths import FFMPEG
from mdm_paths import APPAUDIO, BC_DIR, HERE, REC_DIR, USER_DIR


class SiteRecordMixin:
    def _site_init(self):
        self._recs = {}                # site -> bandcamp.Recorder, made when that site's window is first opened
        self._wins = {}                # site -> its window

    # A second window shows the site (the user logs in there). bandcamp.py watches the page's player and records that web view's own
    # sound, one WAV per track, in real time; the finished tracks are then written to the disc by the same code as "Add tracks".
    def _site(self, site):
        return site if site in bandcamp.SITES or site == 'radio' else 'bandcamp'

    def _recorder(self, site):
        """The recorder of a site, made on first use. Internet radio has no window: radio.RadioRecorder reads the stream itself."""
        rec = self._recs.get(site)
        if rec is None:
            if site == 'radio':
                rec = radio.RadioRecorder(FFMPEG, os.path.join(REC_DIR, site), self.log)
            else:
                rec = bandcamp.Recorder(APPAUDIO, os.path.join(REC_DIR, site), self.log)
            self._recs[site] = rec
        return rec

    def radio_search(self, query, by='name'):
        query = (query or '').strip()
        if not query:
            return {'error': 'Type a station name, a genre or a country to search for.'}
        try:
            return {'stations': radio.search(query, by)}
        except Exception as exc:
            self.log('radio_search failed: %r' % (exc,))
            return {'error': str(exc)}

    # favourite stations: a small list kept between runs in USER_DIR\radio-favourites.json
    def _fav_path(self):
        return os.path.join(USER_DIR, 'radio-favourites.json')

    def _fav_load(self):
        try:
            with open(self._fav_path(), 'r', encoding='utf-8') as f:
                favs = json.load(f)
            return [s for s in favs if isinstance(s, dict) and s.get('url')]
        except (OSError, ValueError):
            return []

    def _fav_save(self, favs):
        os.makedirs(USER_DIR, exist_ok=True)
        tmp = self._fav_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(favs, f, indent=1)
        os.replace(tmp, self._fav_path())

    @staticmethod
    def _fav_key(s):
        return s.get('id') or s.get('url')

    def radio_favs(self):
        return {'stations': self._fav_load()}

    def radio_fav_set(self, station, on):
        """Add (on) or remove (off) a station in the favourites; answers with the new list."""
        favs = [s for s in self._fav_load() if self._fav_key(s) != self._fav_key(station)]
        if on:
            favs.append({k: station.get(k, '') for k in ('id', 'name', 'url', 'codec', 'bitrate', 'country', 'tags', 'hls')})
            favs.sort(key=lambda s: (s.get('name') or '').lower())
        try:
            self._fav_save(favs)
        except OSError as exc:
            return {'error': 'The favourites could not be saved: %s' % exc}
        return {'stations': favs}

    def radio_start(self, station, mode='songs', minutes=10):
        """Start recording an internet radio station (see radio.py). A saved station whose address no longer works is looked up again."""
        rec = self._recorder('radio')
        mode = 'single' if mode == 'single' else 'songs'
        try:
            try:
                rec.start(station, mode, minutes)
            except Exception as first:
                fresh = radio.lookup(station.get('id'))
                if not fresh or fresh['url'] == station.get('url'):
                    raise
                self.log('radio_start: %r; the directory has a new address for %s' % (first, station.get('name')))
                station = dict(station, **fresh)
                rec.start(station, mode, minutes)
                favs = self._fav_load()                              # keep a saved favourite up to date
                if any(self._fav_key(s) == self._fav_key(station) for s in favs):
                    try:
                        self._fav_save([station if self._fav_key(s) == self._fav_key(station) else s for s in favs])
                    except OSError:
                        pass
        except Exception as exc:
            self.log('radio_start failed: %r' % (exc,))
            return {'error': str(exc) or 'The station could not be opened.'}
        return dict(self.bc_status('radio'), url=station.get('url'))

    def radio_stop(self):
        rec = self._recs.get('radio')
        if rec:
            rec.stop()
        return self.bc_status('radio')

    def bc_open(self, site='bandcamp'):
        """Open (or bring forward) the site's window and start listening."""
        site = self._site(site)
        info = bandcamp.SITES[site]
        try:
            rec = self._recs.get(site)
            if rec is None:
                rec = self._recs[site] = bandcamp.Recorder(APPAUDIO, os.path.join(REC_DIR, site), self.log)
            if self._wins.get(site) is None:
                w = webview.create_window(info['title'], info['url'], js_api=rec.bridge, width=1100, height=820,
                                          min_size=(700, 500), background_color='#ffffff')
                w.events.loaded += lambda *a: w.evaluate_js(info['js'])

                def closed(*a):
                    self._wins[site] = None
                    rec.stop()
                w.events.closed += closed
                self._wins[site] = w
            else:
                try:
                    self._wins[site].show()
                except Exception:
                    pass
            rec.start(os.getpid())
            return self.bc_status(site)
        except Exception as exc:
            self.log('bc_open(%s) failed: %r' % (site, exc))
            return {'error': 'The %s window could not be opened: %s' % (info['name'], exc)}

    def bc_status(self, site='bandcamp'):
        site = self._site(site)
        rec = self._recorder(site)                     # list the kept recordings even before the window is opened
        s = rec.status()
        s['window'] = site == 'radio' or self._wins.get(site) is not None
        return s

    def bc_arm(self, on, site='bandcamp'):
        rec = self._recs.get(self._site(site))
        if rec:
            rec.armed = bool(on)
        return {'ok': True}

    def bc_remove(self, ids, site='bandcamp'):
        rec = self._recs.get(self._site(site))
        if rec:
            rec.remove(set(int(i) for i in ids))
        return {'ok': True}

    def bc_add(self, index, tracks, fmt='auto', mp3_kbps=192, disc_title='', store_cover=False, site='bandcamp'):
        """WRITES TO THE DISC. `tracks`: [{id, title, artist, album}] of the recorded tracks to add, in order (titles as edited by the user)."""
        index = int(index)
        netmd = self._is_netmd(index)
        rec = self._recs.get(self._site(site))
        fmt = (fmt if fmt in ('sp', 'lp2', 'lp4') else 'sp') if netmd else (fmt if fmt in ('auto', 'pcm', 'mp3', 'lp2', 'lp4', 'at3p', 'hisp', 'hilp') else 'auto')
        if not rec or not tracks:
            return {'error': 'Choose at least one recorded track to add.'}
        have = {i['id']: i for i in rec.paths(set(int(t['id']) for t in tracks))}
        files = []
        for t in tracks:
            item = have.get(int(t['id']))
            if not item or not os.path.isfile(item['path']):
                return {'error': 'A recorded track is no longer available. Close this window and open it again.'}
            files.append({'path': item['path'], 'title': (t.get('title') or '').strip() or item['title'],
                          'artist': (t.get('artist') or '').strip(), 'album': (t.get('album') or '').strip()})
        art = have[int(tracks[0]['id'])].get('art')
        res = self.upload(files, fmt, mp3_kbps)
        if 'error' in res:
            return {'error': res['error']}
        notes = []
        title = (disc_title or '').strip()
        if title or (store_cover and not netmd):
            try:
                if not netmd:
                    self._reconnect(index)                      # a secure session can leave the recorder busy for a few seconds
                    self._release_devices()
                if title:
                    r = self.rename_disc(index, title)
                    if 'error' in r:
                        notes.append('The disc name could not be set: %s' % r['error'])
                if store_cover and not netmd:
                    data = bandcamp.fetch_cover(art)
                    if not data:
                        notes.append('The album picture could not be fetched, so the disc picture was left alone.')
                    else:
                        os.makedirs(BC_DIR, exist_ok=True)
                        pic = os.path.join(BC_DIR, 'cover.img')
                        with open(pic, 'wb') as f:
                            f.write(data)
                        prep = self.cover_prepare(pic)
                        r = prep if 'error' in prep else self.cover_set(index, prep['tmp'])
                        if 'error' in r:
                            notes.append('The cover could not be stored: %s' % r['error'])
            except Exception as exc:
                notes.append('The disc name or cover could not be set: %s' % exc)
        self._release_devices()
        rec.mark_added(set(int(t['id']) for t in tracks))              # the recordings are kept; only "Remove" deletes them
        return {'ok': True, 'added': len(files), 'notes': notes}
    def export_csv(self):
        if not self._tracks:
            return {'error': 'There is no track list to export.'}
        kind = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        path = self._window.create_file_dialog(kind, save_filename='hi-md-tracks.csv',
                                              file_types=('CSV file (*.csv)',))
        if not path:
            return {'cancelled': True}
        path = path if isinstance(path, str) else path[0]
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['#', 'Title', 'Artist', 'Album', 'Group', 'Codec', 'kbps', 'Length (s)'])
            for t in self._tracks:
                w.writerow([t['number'], t['title'], t['artist'], t['album'], t['group'], t['codec'],
                            t['kbps'] or '', t['seconds']])
        return {'saved': path}
