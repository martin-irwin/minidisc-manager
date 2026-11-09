"""Backing up and restoring the app's own data (lyrics, disc catalogue, track details, favourites, printer settings and the page's settings), as one zip file.
BackupMixin is mixed into himd_app.Api (the page calls these methods on it).

Not included on purpose: sign-in tokens and the licence (a backup file may be copied around, and those must not travel), the saved copies of tracks
(far too big), logs, and caches that are rebuilt by themselves."""
import json
import os
import shutil
import time
import zipfile

import webview
from mdm_paths import BACKUP_DIR, USER_DIR

APP_TAG = 'MiniDiscManager-backup'
# the only files a backup holds (and the only ones a restore will write, by exactly these names)
DATA_FILES = ('lyrics.json', 'catalogue.json', 'netmd-details.json', 'radio-favourites.json', 'hiprint.json', 'hiprint_film.json', 'sprocket.json', 'acoustid-key.txt')
MAX_ZIP_ENTRY = 50 * 1000 * 1000


class BackupMixin:
    def backup_make(self, settings):
        """Asks where to save, then writes the zip. `settings`: the page's remembered settings (theme, equalizer presets, ...), a dict of text values."""
        kind = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        name = 'MiniDisc-Manager-backup-%s.zip' % time.strftime('%Y-%m-%d')
        start = os.path.join(os.path.expanduser('~'), 'Documents')
        path = self._window.create_file_dialog(kind, directory=start if os.path.isdir(start) else '', save_filename=name, file_types=('Backup file (*.zip)',))
        if not path:
            return {'cancelled': True}
        path = path if isinstance(path, str) else path[0]
        if not path.lower().endswith('.zip'):
            path += '.zip'
        kept = []
        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
                for f in DATA_FILES:
                    src = os.path.join(USER_DIR, f)
                    if os.path.isfile(src):
                        z.write(src, 'data/' + f)
                        kept.append(f)
                z.writestr('settings.json', json.dumps(settings if isinstance(settings, dict) else {}, ensure_ascii=False))
                z.writestr('manifest.json', json.dumps({'app': APP_TAG, 'version': 1, 'made': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': kept}))
        except OSError as exc:
            return {'error': 'The backup could not be written: %s' % exc}
        return {'ok': True, 'path': path, 'files': kept, 'settings': len(settings or {})}

    def backup_restore(self):
        """Asks for a backup zip and puts its data back. The files being replaced are first copied to backups\\before-restore-<time>. Returns the page settings to apply."""
        kind = getattr(getattr(webview, 'FileDialog', None), 'OPEN', None) or webview.OPEN_DIALOG
        start = os.path.join(os.path.expanduser('~'), 'Documents')
        paths = self._window.create_file_dialog(kind, directory=start if os.path.isdir(start) else '', allow_multiple=False, file_types=('Backup file (*.zip)',))
        if not paths:
            return {'cancelled': True}
        path = paths if isinstance(paths, str) else paths[0]
        try:
            with zipfile.ZipFile(path) as z:
                try:
                    man = json.loads(z.read('manifest.json').decode('utf-8'))
                except (KeyError, ValueError):
                    man = {}
                if man.get('app') != APP_TAG:
                    return {'error': 'That file is not a MiniDisc Manager backup.'}
                incoming = {}
                for f in DATA_FILES:                                  # only the known names, never a path taken from the zip
                    try:
                        info = z.getinfo('data/' + f)
                    except KeyError:
                        continue
                    if info.file_size > MAX_ZIP_ENTRY:
                        return {'error': 'The backup holds an unexpectedly large file (%s); it was not restored.' % f}
                    data = z.read('data/' + f)
                    if f.endswith('.json'):
                        try:
                            json.loads(data.decode('utf-8'))
                        except ValueError:
                            return {'error': 'The backup holds a damaged file (%s); nothing was restored.' % f}
                    incoming[f] = data
                try:
                    settings = json.loads(z.read('settings.json').decode('utf-8'))
                    settings = settings if isinstance(settings, dict) else {}
                except (KeyError, ValueError):
                    settings = {}
        except (OSError, zipfile.BadZipFile) as exc:
            return {'error': 'That backup could not be read: %s' % exc}
        safety = os.path.join(BACKUP_DIR, 'before-restore-' + time.strftime('%Y%m%d-%H%M%S'))
        try:
            os.makedirs(safety, exist_ok=True)
            os.makedirs(USER_DIR, exist_ok=True)
            for f, data in incoming.items():
                cur = os.path.join(USER_DIR, f)
                if os.path.isfile(cur):
                    shutil.copy2(cur, os.path.join(safety, f))
                tmp = cur + '.tmp'
                with open(tmp, 'wb') as fh:
                    fh.write(data)
                os.replace(tmp, cur)
        except OSError as exc:
            return {'error': 'The data could not be put back: %s' % exc}
        return {'ok': True, 'files': sorted(incoming), 'settings': settings, 'made': man.get('made', ''), 'safety': safety}
