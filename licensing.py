"""Optional license-key check (switched off: LICENSE_REQUIRED is False in himd_app.py), checked against Lemon Squeezy's public License API (no secret key is needed or stored).

Flow: the user buys on Lemon Squeezy and gets a key by e-mail; "Activate" sends the key and this PC's name to
https://api.lemonsqueezy.com/v1/licenses/activate; the answer says whether the key belongs to OUR product and how many PCs it is on.
The key and the instance id are kept in license.json; about once a day the app asks again (validate) so a refunded or disabled key stops
working, and it keeps working offline for OFFLINE_DAYS after the last good answer. Before a key is entered there is a TRIAL_DAYS trial.

Not licensed (trial over) = the program still opens, shows and plays discs, but everything that writes to a disc, rips, records, clones
or saves is switched off (himd_app.py wraps those methods; see GATED there). When `required` is False (the personal build) nothing is checked.
"""
import json
import os
import platform
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = 'https://api.lemonsqueezy.com/v1/licenses'
TRIAL_DAYS = 7
OFFLINE_DAYS = 30                  # how long a key keeps working with no successful online check
CHECK_EVERY = 24 * 3600            # ask the server again after this long
DAY = 86400.0
REG_PATH = r'Software\MiniDiscManager'


def _reg_name(version):
    return 'ts_' + version if version else 'ts'         # one value per program version (the trial belongs to the version)


def _reg_get(version=''):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            return float(winreg.QueryValueEx(k, _reg_name(version))[0])
    except Exception:
        return None


def _reg_set(value, version=''):
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            winreg.SetValueEx(k, _reg_name(version), 0, winreg.REG_SZ, repr(float(value)))
    except Exception:
        pass


class License:
    def __init__(self, state_dir, required, store_id=0, product_id=0, buy_url='', log=lambda text: None, version=''):
        self.version = str(version or '')                  # the program version: every new version starts its own TRIAL_DAYS trial
        self.required = bool(required)
        self.store_id, self.product_id, self.buy_url, self._log = int(store_id), int(product_id), buy_url, log
        self._path = os.path.join(state_dir, 'license.json')
        self._lock = threading.RLock()
        self._s = {}
        self._load()
        if self.required:
            self._start_trial()

    # -- the saved state (the trial's start is kept in two places, the earlier one counts) ---------------------------
    def _load(self):
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                self._s = json.load(f)
        except (OSError, ValueError):
            self._s = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._s, f)
            os.replace(tmp, self._path)
        except OSError as exc:
            self._log('license: could not save: %r' % (exc,))

    def _key(self):
        return self.version or 'legacy'

    def _start_trial(self):
        """The trial starts the first time THIS version runs (kept in license.json and in the registry; the earlier one counts), so installing the
        same version again never gives days back, while a newer version has no start yet and begins its own trial."""
        with self._lock:
            now = time.time()
            starts_map = self._s.get('trial_starts')
            if not isinstance(starts_map, dict):
                starts_map = self._s['trial_starts'] = {}
            candidates = [starts_map.get(self._key()), _reg_get(self.version)]
            if not self.version:
                candidates.append(self._s.get('trial_start'))               # files written before the trial belonged to a version
            starts = [v for v in candidates if isinstance(v, (int, float)) and v > 0]
            start = min(starts) if starts else now
            starts_map[self._key()] = start
            self._s['last_seen'] = max(float(self._s.get('last_seen') or 0), now)   # winding the clock back does not give days back
            _reg_set(start, self.version)
            self._save()

    # -- what the program asks ---------------------------------------------------------------------------------------
    def _trial_left(self):
        starts_map = self._s.get('trial_starts') if isinstance(self._s.get('trial_starts'), dict) else {}
        used = (max(time.time(), float(self._s.get('last_seen') or 0)) - float(starts_map.get(self._key()) or time.time())) / DAY
        return max(0.0, TRIAL_DAYS - used)

    def _licensed(self):
        if not (self._s.get('key') and self._s.get('instance_id')):
            return False
        return (time.time() - float(self._s.get('last_ok') or 0)) <= OFFLINE_DAYS * DAY

    def allowed(self):
        """May the program change discs (add, delete, rip, record, clone, save...)?"""
        if not self.required:
            return True
        with self._lock:
            return self._licensed() or self._trial_left() > 0

    def status(self):
        if not self.required:
            return {'required': False, 'allowed': True, 'licensed': False}
        with self._lock:
            key = self._s.get('key') or ''
            lic = self._licensed()
            left = self._trial_left()
            msg = ''
            if key and not lic:
                msg = 'The license could not be re-checked for %d days. Connect to the internet and press Activate again.' % OFFLINE_DAYS
            return {'required': True, 'allowed': lic or left > 0, 'licensed': lic, 'keyHint': ('…' + key[-4:]) if key else '',
                    'trialDaysLeft': int(left + 0.999) if left > 0 else 0, 'message': msg, 'buyUrl': self.buy_url,
                    'configured': bool(self.store_id and self.product_id)}

    # -- talking to Lemon Squeezy --------------------------------------------------------------------------------------
    def _post(self, action, fields):
        data = urllib.parse.urlencode(fields).encode('ascii')
        req = urllib.request.Request('%s/%s' % (API_BASE, action), data=data, method='POST',
                                     headers={'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded',
                                              'User-Agent': 'MiniDiscManager'})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:           # 400 / 404: the body still says why
            try:
                return json.loads(exc.read().decode('utf-8'))
            except Exception:
                return {'error': 'The license server answered with an error (%s).' % exc.code}

    def _ours(self, reply):
        meta = reply.get('meta') or {}
        return int(meta.get('store_id') or 0) == self.store_id and int(meta.get('product_id') or 0) == self.product_id

    def activate(self, key):
        key = (key or '').strip()
        if not self.required:
            return {'ok': True}
        if not key:
            return {'error': 'Type or paste your license key first.'}
        if not (self.store_id and self.product_id):
            return {'error': 'This copy has not been set up for license keys yet.'}
        try:
            with self._lock:
                old = (self._s.get('key'), self._s.get('instance_id'))
            if old[0] and old[0] == key and old[1]:                # same key again: just re-check it
                reply = self._post('validate', {'license_key': key, 'instance_id': old[1]})
                ok = bool(reply.get('valid'))
                inst = old[1]
            else:
                reply = self._post('activate', {'license_key': key, 'instance_name': platform.node() or 'PC'})
                ok = bool(reply.get('activated'))
                inst = (reply.get('instance') or {}).get('id')
        except (OSError, ValueError) as exc:
            self._log('license: activate failed: %r' % (exc,))
            return {'error': 'Could not reach the license server. Check your internet connection and try again.'}
        if not ok:
            return {'error': reply.get('error') or 'That key was not accepted.'}
        if not self._ours(reply):
            return {'error': 'That key is for a different product.'}
        with self._lock:
            self._s.update(key=key, instance_id=inst, last_ok=time.time())
            self._save()
        self._log('license: activated (…%s)' % key[-4:])
        return {'ok': True}

    def deactivate(self):
        """Free this PC's seat so the key can be used on another PC."""
        with self._lock:
            key, inst = self._s.get('key'), self._s.get('instance_id')
        if not (key and inst):
            return {'ok': True}
        try:
            reply = self._post('deactivate', {'license_key': key, 'instance_id': inst})
        except (OSError, ValueError):
            return {'error': 'Could not reach the license server, so this PC was not released. Try again when online.'}
        if not reply.get('deactivated'):
            return {'error': reply.get('error') or 'The license server did not release this PC.'}
        with self._lock:
            for k in ('key', 'instance_id', 'last_ok'):
                self._s.pop(k, None)
            self._save()
        return {'ok': True}

    def refresh(self):
        """Once a day: ask the server whether the key is still good (refunded or disabled keys stop working). Offline is not a failure."""
        if not self.required:
            return
        with self._lock:
            key, inst, last = self._s.get('key'), self._s.get('instance_id'), float(self._s.get('last_ok') or 0)
        if not (key and inst) or time.time() - last < CHECK_EVERY:
            return
        try:
            reply = self._post('validate', {'license_key': key, 'instance_id': inst})
        except (OSError, ValueError):
            return
        with self._lock:
            if reply.get('valid') and self._ours(reply):
                self._s['last_ok'] = time.time()
            elif reply.get('valid') is False:                     # the server said no: refunded, disabled, expired or released
                self._log('license: the key is no longer valid (%s)' % (reply.get('error') or 'no reason given'))
                for k in ('key', 'instance_id', 'last_ok'):
                    self._s.pop(k, None)
            self._save()
