"""Deleting tracks, the disc picture, the TRACKS.CSV track list kept on a Hi-MD disc, and formatting. DiscToolsMixin is mixed into himd_app.Api (the page calls these methods on it)."""
import base64
import csv
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time

import himd_dev
import himd_disc
import himd_fs
import recorders
import usb.util
import webview
from mdm_paths import BACKUP_DIR, COPIES_DIR, NETMD_HELPER, RECORDER_PHOTOS


class DiscToolsMixin:
    def copies_list(self):
        """The PC copies kept of tracks added to standard discs (what makes Identify, split and combine skip reading them back).
        `onDisc`: matches a track of the disc loaded now."""
        here = {(t['title'], t['seconds']) for t in (getattr(self, '_tracks', None) or [])}
        out, total = [], 0
        for c in self._copy_index():
            path = os.path.join(COPIES_DIR, c['id'] + '.flac')
            try:
                size = os.path.getsize(path)
            except OSError:
                continue                                                       # the file is gone: nothing to show
            total += size
            out.append({'id': c['id'], 'title': c['title'], 'seconds': c['seconds'], 'size': size,
                        'onDisc': any(t == c['title'] and abs(s - c['seconds']) <= 1 for t, s in here)})
        return {'copies': out, 'bytes': total}

    def copies_remove(self, ids):
        """Deletes the chosen PC copies (the disc is not touched; a track whose copy is gone is simply read from the recorder again)."""
        gone = {str(i) for i in (ids or [])}
        keep = []
        for c in self._copy_index():
            if c['id'] in gone:
                try:
                    os.remove(os.path.join(COPIES_DIR, c['id'] + '.flac'))
                except OSError:
                    pass
            else:
                keep.append(c)
        try:
            self._write_copy_index(keep)
        except OSError as exc:
            return {'error': str(exc)}
        return self.copies_list()

    @staticmethod
    def _audio_samples(fs, disc, positions):
        """SHA-256 of the first and last block of every fragment of the given tracks (0-based positions)."""
        ent = next(e for e in fs.listdir('/HMDHIFI') if e['short'].upper() == 'ATDATA%02X.HMA' % disc.datanum)
        chain = fs.chain(ent['first'])
        size = 16384

        def block(n):
            c = chain[(n * size) // fs.cluster_bytes]
            off = (n * size) % fs.cluster_bytes
            return fs.cluster_data(c)[off:off + size]

        out = []
        for p in positions:
            frags = disc.fragments(p)
            if not frags or any((last + 1) * size > ent['size'] for _, last in frags):
                raise himd_fs.FatError('Track %d points outside the audio file.' % (p + 1))
            out.append([(hashlib.sha256(block(first)).hexdigest(), hashlib.sha256(block(last)).hexdigest())
                        for first, last in frags])
        return out, ent['size']

    def delete_preview(self, numbers):
        """Rehearsal: runs the delete against an in-memory copy of the write commands. Writes nothing."""
        if self._loaded_netmd:                         # nothing to rehearse: a standard disc is just a table of contents
            freed = sum(t['seconds'] for t in self._tracks if t['number'] in {int(n) for n in numbers})
            return {'result': {'netmd': True, 'freedSeconds': freed}}
        with self._lock:
            extra = self._secure_delete_args([int(n) for n in numbers])
            return self._run_helper('delete', dict({'indexes': [int(n) - 1 for n in numbers], 'simulate': True}, **extra))

    def _delete_netmd(self, numbers):
        self._drop_cache()
        freed = sum(t['seconds'] for t in self._tracks if t['number'] in numbers)
        with self._lock:
            res = self._run_helper('delete', {'indexes': [n - 1 for n in numbers]}, helper=NETMD_HELPER)
        if 'error' in res:
            return {'error': res['error']}
        for t in self._tracks:
            if t['number'] in numbers:
                try:
                    self._drop_copy(t['title'], t['seconds'])                 # the saved copy of a deleted track goes too
                except OSError:
                    pass
        return {'ok': True, 'deleted': len(numbers), 'freed': 0, 'freedSeconds': freed, 'netmd': True}

    def delete_tracks(self, index, numbers):
        """WRITES TO THE DISC. numbers are 1-based track numbers. Verified by reading the disc back."""
        numbers = sorted({int(n) for n in numbers})
        if self._is_netmd(index):
            return self._delete_netmd(numbers)
        with self._lock:
            self._drop_cache()
            try:
                dev = himd_dev.Device(self._devices[int(index)])
                if not dev.capacity():
                    return {'error': 'There is no disc in the recorder.'}
                dev.wait_ready()
                fs = himd_fs.Fat16(dev)
                disc = himd_disc.Disc(fs)
                keep = [n for n in range(disc.track_count()) if (n + 1) not in numbers]
                before_tracks = [disc.track(n) for n in keep]
                before_samples, _ = self._audio_samples(fs, disc, keep)
                free_before = fs.free_clusters() * fs.cluster_bytes
                old_groups = [(g['first'], g['last'], g['title']) for g in disc.groups()]
                new_groups = himd_disc.Disc.groups_after_delete(old_groups, numbers)        # the library leaves the group ranges as they were
            except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError, IndexError, ValueError) as exc:
                return {'error': 'Could not read the disc before deleting: %s. Nothing was deleted.' % exc}

            extra = self._secure_delete_args(numbers)
            res = self._run_helper('delete', dict({'indexes': [n - 1 for n in numbers]}, **extra))
            if 'error' in res:
                return {'error': res['error']}

            # The saved index copies describe the old block layout; restoring one now would be harmful.
            self._retire_backups()
            try:
                dev = self._reconnect(int(index))
                fs2 = himd_fs.Fat16(dev)
                disc2 = himd_disc.Disc(fs2)
                if disc2.track_count() != len(keep):
                    raise himd_fs.FatError('the disc has %d tracks, expected %d' % (disc2.track_count(), len(keep)))
                note = ''
                if old_groups:                                  # the library removes the tracks but not their place in the groups: fix the ranges first,
                    try:                                         # so they are right even if the audio check below finds a problem
                        disc2.set_groups(new_groups)
                        self._write_index(dev, fs2, disc2, bytes(disc2.tif))
                        fs2 = himd_fs.Fat16(dev)
                        disc2 = himd_disc.Disc(fs2)
                    except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError) as exc:
                        note = 'The tracks were deleted, but the groups could not be tidied (%s). Check the group names and ranges.' % exc
                after_samples, _ = self._audio_samples(fs2, disc2, range(len(keep)))
                for i, old in enumerate(before_tracks):
                    new = disc2.track(i)
                    if (new['title'], new['seconds'], new['codec']) != (old['title'], old['seconds'], old['codec']):
                        raise himd_fs.FatError('track "%s" changed' % old['title'])
                    if after_samples[i] != before_samples[i]:
                        raise himd_fs.FatError('the audio of "%s" is no longer the same' % old['title'])
                freed = fs2.free_clusters() * fs2.cluster_bytes - free_before
                return {'ok': True, 'deleted': len(numbers), 'freed': freed, 'groupsNote': note}
            except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError) as exc:
                return {'error': 'The tracks were deleted, but checking the remaining tracks failed: %s. '
                                 'Unplug and re-plug the recorder and check the disc before doing anything else.' % exc}
            finally:
                self._release_devices()                # let the page's rescan open the recorder itself

    def _reconnect(self, index, tries=10):
        """Opens the recorder again after the helper used it. A secure session renames the disc's files and the
        recorder can be busy, or show up as a new USB device, for a few seconds afterwards: wait and look again."""
        want = self._devices[index].idProduct if index < len(self._devices) else None
        last = None
        for attempt in range(tries):
            if attempt:
                time.sleep(1.5)
            try:
                self._release_devices()                # a second open handle would be refused (Errno 13)
                found = himd_dev.find_devices()
                dev_obj = next((d for d in found if want is None or d.idProduct == want), None)
                if dev_obj is None:
                    raise himd_dev.HiMDError('The recorder is not showing up on USB yet.')
                dev = himd_dev.Device(dev_obj)
                dev.capacity()
                dev.wait_ready()
                self._devices = found
                return dev
            except (usb.core.USBError, himd_dev.HiMDError) as exc:
                last = exc
        raise last

    @staticmethod
    def _retire_backups():
        """Move saved track-index copies aside; they no longer match the audio file after a delete."""
        if not os.path.isdir(BACKUP_DIR):
            return
        files = [f for f in os.listdir(BACKUP_DIR) if os.path.isfile(os.path.join(BACKUP_DIR, f))]
        if not files:
            return
        dest = os.path.join(BACKUP_DIR, 'retired-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        os.makedirs(dest, exist_ok=True)
        for f in files:
            os.replace(os.path.join(BACKUP_DIR, f), os.path.join(dest, f))

    @staticmethod
    def _recorder_info(model):
        """recorders.lookup(model), with the picture from the recorder_photos folder (name.jpg) instead if there is one (shown small in the Recorder box)."""
        info = recorders.lookup(model)
        if info:
            path = os.path.join(RECORDER_PHOTOS, info['name'] + '.jpg')
            try:
                if os.path.isfile(path):
                    with open(path, 'rb') as f:
                        info = dict(info, photo='data:image/jpeg;base64,' + base64.b64encode(f.read()).decode(), credit='')
            except OSError:
                pass
        return info
    # -- a picture stored on a Hi-MD disc -------------------------------------------
    def pick_image(self):
        kind = getattr(getattr(webview, 'FileDialog', None), 'OPEN', None) or webview.OPEN_DIALOG
        paths = self._window.create_file_dialog(kind, allow_multiple=False,
                                                file_types=('Pictures (*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.webp;*.tif;*.tiff)',))
        return {'path': (paths if isinstance(paths, str) else paths[0]) if paths else None}

    def cover_prepare(self, path):
        """Shrinks any picture to a JPEG of at most 1024 pixels a side, ready to store on the disc."""
        if self._loaded_netmd:
            return {'error': 'Only Hi-MD discs can hold a picture.'}
        out = os.path.join(tempfile.mkdtemp(prefix='mdm-cover-'), 'COVER.JPG')
        for q in ('3', '6', '10', '16'):                          # lower quality until it is small enough
            try:
                self._ffmpeg(['-i', path, '-frames:v', '1', '-vf', "scale='min(1024,iw)':'min(1024,ih)':force_original_aspect_ratio=decrease",
                              '-pix_fmt', 'yuvj420p', '-q:v', q, out])
            except RuntimeError:
                return {'error': 'That file could not be read as a picture.'}
            if os.path.getsize(out) <= 400000:
                break
        size = os.path.getsize(out)
        with open(out, 'rb') as f:
            preview = 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode()
        return {'tmp': out, 'bytes': size, 'preview': preview}

    def cover_set(self, index, tmp, simulate=False):
        """WRITES A FILE TO THE DISC (unless simulate, which does it all in memory). Stores the prepared picture as COVER.JPG."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a picture.'}
        if not tmp or not os.path.isfile(tmp) or os.path.basename(os.path.dirname(tmp)).startswith('mdm-cover-') is False:
            return {'error': 'The picture is no longer available; choose it again.'}
        args = {'file': tmp, 'simulate': bool(simulate)}
        if not simulate:
            args['backupDir'] = os.path.join(BACKUP_DIR, 'cover_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        with self._lock:
            return self._run_helper('cover_set', args)

    # -- the track list kept on a Hi-MD disc as TRACKS.CSV (root folder, like COVER.JPG) ----------------
    @staticmethod
    def _tracklist_bytes(tracks):
        """The CSV text for a track list; the same bytes every time for the same tracks, so a file on the disc can be compared with it."""
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator='\r\n')
        w.writerow(['#', 'Title', 'Artist', 'Album', 'Group', 'Codec', 'kbps', 'Length (s)'])
        for t in tracks:
            w.writerow([t['number'], t['title'], t['artist'], t['album'], t['group'], t['codec'], t['kbps'] or '', t['seconds']])
        return buf.getvalue().encode('utf-8-sig')

    def tracklist_sync(self, index):
        """WRITES A FILE TO THE DISC. Stores the current track list as TRACKS.CSV (the page calls this only when the disc's copy is
        missing or out of date, and only if the user switched the feature on)."""
        if not self._license_allowed():
            return {'skipped': True}
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a track list file.'}
        if not self._tracks:
            return {'skipped': True}
        tmp = os.path.join(tempfile.mkdtemp(prefix='mdm-tracklist-'), 'TRACKS.CSV')
        try:
            with open(tmp, 'wb') as f:
                f.write(self._tracklist_bytes(self._tracks))
            res = {'error': 'not tried'}
            for attempt in range(3):                      # a recorder can stay busy for a few seconds after a write
                with self._lock:
                    res = self._run_helper('tracklist_set', {'file': tmp, 'backupDir': os.path.join(BACKUP_DIR, 'tracklist_latest')})
                if 'error' not in res:
                    break
                time.sleep(2.5)
            if 'error' in res:
                self.log('tracklist_sync failed: %s' % res['error'])
            return res
        finally:
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)

    def tracklist_open(self, index):
        """Copies TRACKS.CSV off the disc into a temporary folder and opens it with the program Windows uses for .csv files."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a track list file.'}
        with self._lock:
            try:
                dev = himd_dev.Device(self._devices[int(index)])
                fs = himd_fs.Fat16(dev)
                if not any(not e['dir'] and e['short'].upper() == 'TRACKS.CSV' for e in fs.listdir('/')):
                    return {'error': 'There is no track list on this disc yet. Switch on “Keep a track list on the disc” first.'}
                data = bytes(fs.read_file('/TRACKS.CSV'))
            except Exception as exc:
                return {'error': 'The track list could not be read from the disc: %s' % exc}
            finally:
                self._release_devices()
        folder = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-tracklist')
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, 'Track list.csv')
        try:
            with open(path, 'wb') as f:
                f.write(data)
            os.startfile(path)
        except OSError as exc:
            return {'error': 'The track list could not be opened: %s' % exc}
        return {'ok': True, 'path': path}

    def cover_remove(self, index):
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a picture.'}
        with self._lock:
            return self._run_helper('cover_remove', {'backupDir': os.path.join(BACKUP_DIR, 'cover_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})
    # -- formatting ------------------------------------------------------------------
    @staticmethod
    def _himd_capable(usb_dev):
        name = himd_dev.NETMD_IDS.get((usb_dev.idVendor, usb_dev.idProduct), '')
        return re.search(r'MZ-(RH|NH|DH)|DS-HMD1|CMT-AH', name) is not None

    def format_disc(self, index, mode, confirm):
        """WRITES TO THE DISC AND ERASES EVERYTHING ON IT. The page makes the user type FORMAT; that is checked again here.
        Hi-MD disc: mode 'reformat'. Standard disc: mode 'standard' (blank standard disc) or 'himd' (Hi-MD recorders only: the disc
        is erased, the recorder switches to Hi-MD mode and the disc is then initialised as a Hi-MD disc)."""
        if confirm != 'FORMAT':
            return {'error': 'Formatting was not confirmed.'}
        try:
            index = int(index)
            usb_dev = self._devices[index]
        except (IndexError, ValueError):
            return {'error': 'That recorder is no longer connected. Press rescan.'}
        netmd = self._is_netmd(index)
        if mode not in (('standard', 'himd') if netmd else ('reformat',)):
            return {'error': 'That format is not available for this disc.'}
        if mode == 'himd' and not self._himd_capable(usb_dev):
            return {'error': 'This recorder cannot use Hi-MD discs.'}

        def say(text):
            self.log('format: ' + text)
            if self._window:
                try:
                    self._window.evaluate_js('window.onFormatProgress && window.onFormatProgress(%s)' % json.dumps(text))
                except Exception:
                    pass

        with self._lock:
            self._drop_cache()
            if not netmd:
                say('Formatting the disc…')
                return self._run_helper('format', {})
            on_disc = [(t['title'], t['seconds']) for t in (self._tracks or [])]
            say('Erasing the disc…')
            res = self._run_helper('format', {'mode': mode}, helper=NETMD_HELPER)
            if 'error' not in res:
                for title, seconds in on_disc:                                # the PC copies of the erased tracks go with them
                    self._drop_copy(title, seconds)
            if 'error' in res or mode == 'standard':
                return res
            say('Switching the recorder to Hi-MD mode…')              # it disconnects and comes back as a Hi-MD device
            self._release_devices()
            deadline, back = time.time() + 90, False
            while time.time() < deadline and not back:
                time.sleep(2)
                try:
                    back = bool(himd_dev.find_devices())
                except Exception:
                    back = False
            if not back:
                return {'error': 'The disc was erased and the recorder was switched to Hi-MD mode, but it did not reappear. Unplug and reconnect it, press rescan, '
                                 'and use Format again to finish setting up the disc.', 'unfinished': True}
            time.sleep(3)
            say('Setting up the Hi-MD disc…')
            res = self._run_helper('format', {})
            if 'error' in res:
                res['error'] = 'The disc was erased and the recorder is in Hi-MD mode, but setting up the Hi-MD disc failed: %s. Press rescan and use Format again.' % res['error']
                res['unfinished'] = True
            return res
