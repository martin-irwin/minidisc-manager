"""The app's own on/off settings (the Settings button in the top bar). AppSettingsMixin is mixed into himd_app.Api.

Kept in app-settings.json in USER_DIR (it is part of a backup). To add a setting: put its key and default in DEFAULTS, read it in Python with
self._app_setting('key') and in the page from the object get_app_settings() returns, then add a row for it in openSettings() in ui\\index.html."""
import json
import os

from mdm_paths import USER_DIR

SETTINGS_FILE = os.path.join(USER_DIR, 'app-settings.json')
DEFAULTS = {
    'autoLookupCommercial': True,        # a pre-recorded (commercial) standard disc is looked up online by itself when it is inserted
    'askConvert': True,                  # a standard disc with audio in a Hi-MD-capable recorder shows the "can be converted to Hi-MD" note under the Recorder card
    'askLpToSp': True,                   # a standard disc with LP2 / LP4 tracks shows the "convert to SP" note under the Recorder card
    'autoAlign': False,                  # after lyrics are found, fine-tune their timing by listening to each track (slow; OFF unless switched on)
    'fillArtist': True,                  # a track whose lyrics were found and matched, and that has no artist, takes the artist the lyrics record names
    'askMissing': True,                  # a disc with details missing (artist, album, picture, lyrics) shows the "missing some details" prompt
}


class AppSettingsMixin:
    def _app_settings_read(self):
        out = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in DEFAULTS:
                    if isinstance(saved.get(k), bool):
                        out[k] = saved[k]
        except (OSError, ValueError):
            pass
        return out

    def _app_setting(self, key):
        return self._app_settings_read().get(key, DEFAULTS.get(key))

    def get_app_settings(self):
        return self._app_settings_read()

    def set_app_setting(self, key, value):
        if key not in DEFAULTS:
            return {'error': 'Unknown setting.'}
        cur = self._app_settings_read()
        cur[key] = bool(value)
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            tmp = SETTINGS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cur, f, indent=1)
            os.replace(tmp, SETTINGS_FILE)
        except OSError as e:
            return {'error': 'The setting could not be saved: %s' % e}
        return cur
