"""Disc labels: the page draws the label (cover, album, artist, track list) on a canvas; this saves the picture as a PNG.
LabelMixin is mixed into himd_app.Api. The label can also be sent to a paired HP Sprocket printer over Bluetooth (sprocket.py)."""
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

import webview
import sprocket
import hiprint
from mdm_paths import BACKUP_DIR, USER_DIR


class LabelMixin:
    def label_save(self, data_url, name):
        """Ask where to save, then write the PNG the page drew (a data: URL)."""
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        try:
            data = base64.b64decode(m.group(1))
        except Exception:
            return {'error': 'The label picture could not be read.'}
        safe = re.sub(r'[\\/:*?"<>|]+', ' ', name or 'disc label').strip()[:80] or 'disc label'
        kind = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        start = getattr(self, '_last_save_dir', None)
        path = self._window.create_file_dialog(
            kind, directory=start if start and os.path.isdir(start) else os.path.join(os.path.expanduser('~'), 'Pictures'),
            save_filename=safe + ' label.png', file_types=('PNG picture (*.png)',))
        if not path:
            return {'cancelled': True}
        path = path if isinstance(path, str) else path[0]
        if not path.lower().endswith('.png'):
            path += '.png'
        try:
            with open(path, 'wb') as f:
                f.write(data)
        except OSError as exc:
            return {'error': 'The label could not be saved: %s' % exc}
        return {'saved': path}

    def label_save_many(self, items):
        """Ask for a folder, then write one PNG per item ({name, data}: data is a PNG data: URL), e.g. one label per group of a disc."""
        kind = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or webview.FOLDER_DIALOG
        start = getattr(self, '_last_save_dir', None)
        folder = self._window.create_file_dialog(
            kind, directory=start if start and os.path.isdir(start) else os.path.join(os.path.expanduser('~'), 'Pictures'))
        if not folder:
            return {'cancelled': True}
        folder = folder if isinstance(folder, str) else folder[0]
        count = 0
        try:
            for i, item in enumerate(items or [], 1):
                m = re.match(r'data:image/png;base64,(.+)$', (item or {}).get('data') or '', re.S)
                if not m:
                    return {'error': 'A label picture was not in the expected form.'}
                safe = re.sub(r'[\\/:*?"<>|]+', ' ', (item.get('name') or 'group')).strip()[:60] or 'group'
                path = os.path.join(folder, '%02d %s label.png' % (i, safe))
                with open(path, 'wb') as f:
                    f.write(base64.b64decode(m.group(1)))
                count += 1
        except (OSError, ValueError) as exc:
            return {'error': 'The labels could not be saved: %s' % exc}
        return {'saved': folder, 'count': count}

    def label_save_disc(self, index, data_url):
        """WRITES A FILE TO THE DISC. Stores the label the page drew as /LABEL.JPG in the root folder (a Hi-MD disc only), replacing an earlier one."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a label picture.'}
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        folder = tempfile.mkdtemp(prefix='mdm-label-')
        try:
            png, jpg = os.path.join(folder, 'label.png'), os.path.join(folder, 'LABEL.JPG')
            with open(png, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            for q in ('2', '4', '8'):                                  # high quality first, lower only if the file is large
                try:
                    self._ffmpeg(['-i', png, '-frames:v', '1', '-pix_fmt', 'yuvj420p', '-q:v', q, jpg])
                except RuntimeError as exc:
                    return {'error': 'The label could not be prepared: %s' % exc}
                if os.path.getsize(jpg) <= 600000:
                    break
            res = {'error': 'not tried'}
            for attempt in range(3):                                   # a recorder can stay busy for a few seconds after a write
                with self._lock:
                    res = self._run_helper('label_set', {'file': jpg, 'backupDir': os.path.join(BACKUP_DIR, 'label_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})
                if 'error' not in res:
                    break
                time.sleep(2.5)
            if 'error' in res:
                self.log('label_save_disc failed: %s' % res['error'])
            return res
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def label_remove(self, index):
        """WRITES TO THE DISC. Removes /LABEL.JPG."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a label picture.'}
        with self._lock:
            return self._run_helper('label_remove', {'backupDir': os.path.join(BACKUP_DIR, 'label_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})

    # -- printing on an HP Sprocket ---------------------------------------------------------------------
    @staticmethod
    def _sprocket_cache():
        return os.path.join(USER_DIR, 'sprocket.json')

    @staticmethod
    def _paired_bluetooth(name_regex, cache, default_name):
        """(address, name) of a paired Bluetooth device whose name matches: Windows' list of paired devices, remembered once found."""
        ps = ("Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match '" + name_regex + "' -and "
              "$_.InstanceId -match 'BTHENUM\\\\DEV_([0-9A-F]{12})' } | ForEach-Object { $_.FriendlyName + '|' + $matches[1] }")
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, timeout=25,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            found = [ln.strip().split('|') for ln in r.stdout.splitlines() if '|' in ln]
        except Exception:
            found = []
        if found:
            name, raw = found[0]
            mac = ':'.join(raw[i:i + 2] for i in range(0, 12, 2))
            try:
                with open(cache, 'w') as f:
                    json.dump({'mac': mac, 'name': name}, f)
            except OSError:
                pass
            return mac, name
        try:
            with open(cache) as f:
                c = json.load(f)
            return c['mac'], c.get('name', default_name)
        except Exception:
            return None, None

    def _sprocket_mac(self):
        """The Bluetooth address of the paired HP Sprocket."""
        return self._paired_bluetooth('sprocket', self._sprocket_cache(), 'HP Sprocket')

    def label_sprocket_print(self, data_url, landscape=False):
        """Shrinks the label to 640 x 960 and sends it to the paired Sprocket, which prints it. A landscape label is turned a quarter turn first,
        because the printer takes portrait pictures (the sticker is then read with the paper turned sideways)."""
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        mac, name = self._sprocket_mac()
        if not mac:
            return {'error': 'No paired HP Sprocket was found. Pair it first in Windows (Settings > Bluetooth & devices), with the printer switched on.'}
        folder = tempfile.mkdtemp(prefix='mdm-sprocket-')
        try:
            png, jpg = os.path.join(folder, 'label.png'), os.path.join(folder, 'label.jpg')
            with open(png, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            for q in ('3', '6', '10', '16'):                                  # the printer wants a small file: lower the quality until it is
                try:
                    self._ffmpeg(['-i', png, '-frames:v', '1', '-vf', ('transpose=1,' if landscape else '') + 'scale=640:960:flags=lanczos', '-pix_fmt', 'yuvj420p', '-q:v', q, jpg])
                except RuntimeError as exc:
                    return {'error': 'The label could not be prepared: %s' % exc}
                if os.path.getsize(jpg) <= 45000:
                    break
            with open(jpg, 'rb') as f:
                data = f.read()
            self.log('sprocket: sending %d bytes to %s (%s)' % (len(data), name, mac))
            try:
                sprocket.send_jpeg(mac, data)
            except sprocket.SprocketError as exc:
                self.log('sprocket failed: %s (%s)' % (exc, getattr(exc, 'detail', '')))
                return {'error': str(exc)}
            return {'ok': True, 'printer': name, 'bytes': len(data)}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    # -- printing on a Polaroid Hi-Print (groundwork: the print commands are not known yet, see hiprint.py) ---------------
    def _hiprint_mac(self):
        """The Bluetooth address of the paired Polaroid Hi-Print, found like the Sprocket and remembered once found."""
        return self._paired_bluetooth('hi-?print', os.path.join(USER_DIR, 'hiprint.json'), 'Polaroid Hi-Print')

    # The printer cannot report how many sheets are left (it ignores the statistics request), so the program keeps its own count:
    # the user says how many sheets are in the printer, and every successful print here takes one off. Prints made from the phone are not seen.
    @staticmethod
    def _hiprint_film_file():
        return os.path.join(USER_DIR, 'hiprint_film.json')

    def label_hiprint_film_get(self):
        try:
            with open(self._hiprint_film_file()) as f:
                left = json.load(f).get('left')
            return {'left': int(left) if left is not None else None}
        except Exception:
            return {'left': None}

    def label_hiprint_film_set(self, left):
        """The user says how many sheets are in the printer now (None clears the count)."""
        try:
            n = None if left in (None, '') else max(0, min(99, int(left)))
        except (TypeError, ValueError):
            return {'error': 'Please give a whole number of sheets.'}
        try:
            with open(self._hiprint_film_file(), 'w') as f:
                json.dump({'left': n}, f)
        except OSError as exc:
            return {'error': 'The count could not be saved: %s' % exc}
        return {'left': n}

    def label_hiprint_print(self, data_url, landscape=False):
        """Prepares the label for the Hi-Print as a 640 x 1024 JPEG (a landscape label is turned a quarter turn, as for the Sprocket) and prints it
        with hiprint.send_jpeg (Prinics protocol worked out from the Polaroid app; uses one sheet of film)."""
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        mac, name = self._hiprint_mac()
        if not mac:
            return {'error': 'No paired Polaroid Hi-Print was found. Pair it first in Windows (Settings > Bluetooth & devices), with the printer switched on.'}
        w, h = hiprint.IMAGE_SIZE
        folder = tempfile.mkdtemp(prefix='mdm-hiprint-')
        try:
            png, jpg = os.path.join(folder, 'label.png'), os.path.join(folder, 'label.jpg')
            with open(png, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            try:
                self._ffmpeg(['-i', png, '-frames:v', '1', '-vf', ('transpose=1,' if landscape else '') + 'scale=%d:-2:flags=lanczos,pad=%d:%d:0:(oh-ih)/2:white' % (w, w, h),
                              '-pix_fmt', 'yuvj420p', '-q:v', '2', jpg])           # fit the width, white margin top and bottom (the label is 2:3, the paper 5:8)
            except RuntimeError as exc:
                return {'error': 'The label could not be prepared: %s' % exc}
            with open(jpg, 'rb') as f:
                data = f.read()
            self.log('hiprint: prepared %d bytes for %s (%s)' % (len(data), name, mac))
            try:
                res = hiprint.send_jpeg(mac, data, log=self.log)
                self.log('hiprint: done, status %s' % (res.get('status'),))
                left = self.label_hiprint_film_get().get('left')
                if res.get('printed') and left is not None:                      # one sheet used: count down (never below 0)
                    self.label_hiprint_film_set(max(0, left - 1))
            except hiprint.HiPrintError as exc:
                self.log('hiprint: %s (%s)' % (exc, getattr(exc, 'detail', '')))
                return {'error': str(exc)}
            return {'ok': True, 'printer': name, 'bytes': len(data)}
        finally:
            shutil.rmtree(folder, ignore_errors=True)