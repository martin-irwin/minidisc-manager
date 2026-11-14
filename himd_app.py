"""Hi-MD Manager (modern window). Same device code as himd_manager.py, new interface.

The page in ui/index.html talks to the Api class below. Reads only, apart from the
clock, which is set only when the page asks after the user confirms.
"""
import atexit
import base64
import datetime
import functools
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

import usb.core
import usb.util
import webbrowser
import webview

import cdrip
import backup_data
import catalogue
import cd_audio
import clone_disc
import convert_disc
import app_settings
import lp_to_sp
import groupart
import copies
import cover_search
import disc_edit
import disc_lookup
import disc_tools
import edit_tracks
import netmd_disc
import netmd_edit
import save_pc
import site_record
import yoto_disc
import identify_tracks
import label_print
import lyrics
import lyrics_asr
import pc_audio
import play_tracks
import himd_dev
import himd_disc
import himd_fs
import licensing
import sonos_cast
import video_links
from mdm_common import UNITS_PER_SECOND
from mdm_platform import IS_LINUX, data_root, omarchy_theme, open_path
from mdm_paths import (BC_DIR, COPIES_DIR, FROZEN, HELPER, HERE, NETMD_HELPER, NODE_EXE, PLAY_DIR, REC_DIR, USER_DIR,
                       WEBVIEW_DIR)

APP_VERSION = '0.27.9'                        # shown in the window; installer\build_installer.ps1 reads it for the installer and zip names
# Optional license-key check (Lemon Squeezy, see licensing.py). Switched off in every build: LICENSE_REQUIRED stays False.
LICENSE_REQUIRED = False
LS_STORE_ID = 0
LS_PRODUCT_ID = 0
BUY_URL = ''
LICENSE = licensing.License(USER_DIR, LICENSE_REQUIRED, LS_STORE_ID, LS_PRODUCT_ID, BUY_URL, version=APP_VERSION)
FIRST_RUN_FILE = os.path.join(USER_DIR, 'first_run_done.txt')
FETCH_PIDS = {0x0286}         # NetMD recorders that can send a track back to the PC (netmd-js: MZ-RH1, MZ-M200)
EXPLOIT_PIDS = {0x0184}       # Hi-MD recorders in NetMD mode (MZ-NH700...): can be made to send a track back with a firmware
                              # patch, opt-in; the helper checks the exact firmware (Hn / Hr 1.x) before using it

MODELS = {
    0x017F: 'MZ-NH1', 0x0181: 'MZ-NH3D', 0x0183: 'MZ-NH900', 0x0185: 'MZ-NH700', 0x0187: 'MZ-NH600',
    0x01EA: 'MZ-DH10P', 0x021A: 'MZ-RH10', 0x021C: 'MZ-RH910', 0x022D: 'CMT-AH10', 0x023D: 'DS-HMD1',
    0x0287: 'MZ-RH1',
}
# The year each recorder was introduced, from the launch dates on minidisc.org (a model that is not listed shows no year).
RECORDER_YEARS = {
    # Hi-MD: the NH models 2004, the DH10P / RH models 2005, the RH1 / M200 2006
    'NH1': 2004, 'NH3D': 2004, 'NH900': 2004, 'NH800': 2004, 'NHF800': 2004, 'NH700': 2004, 'NH600': 2004, 'NH600D': 2004,
    'DH10P': 2005, 'RH10': 2005, 'RH710': 2005, 'RH910': 2005, 'RH1': 2006, 'M200': 2006,
    # NetMD portables
    'N1': 2001, 'N505': 2002, 'N707': 2002, 'S1': 2002, 'N10': 2002, 'N910': 2003, 'N710': 2003, 'NF810': 2003, 'N510': 2003,
    'NE410': 2003, 'NE810': 2003, 'NF520D': 2004, 'N920': 2004,
    # NetMD decks, hi-fi systems and other makers
    'CMT-C7NT': 2001, 'CMT-M333NT': 2003, 'CMT-M373NT': 2003, 'MDS-NT1': 2001, 'MDS-JE780': 2002, 'MDS-JB980': 2002, 'MDS-S500': 2003,
    'LAM-1': 2001, 'IM-DR400': 2003, 'IM-DR80': 2003, 'AM-NX1': 2003, 'AM-NX9': 2003,
}


def recorder_year(model):
    """The year (or 'a - b' when a combined name covers models from different years) a recorder was introduced; None if unknown."""
    years = {y for code, y in RECORDER_YEARS.items() if re.search(r'(?<![A-Za-z0-9])' + re.escape(code) + r'(?![A-Za-z0-9])', model or '')}
    if not years:
        return None
    lo, hi = min(years), max(years)
    return str(lo) if lo == hi else '%dâ€“%d' % (lo, hi)



class _Gate:
    """The USB lock. Entering it first asks any playback read to stop, so playing never blocks other work."""
    def __init__(self, before, after=None):
        self.raw = threading.Lock()
        self._before = before
        self._after = after                           # called when the other operation is over: it may have moved the drive

    def __enter__(self):
        self._before()
        self.raw.acquire()
        return self

    def __exit__(self, *exc):
        self.raw.release()
        if self._after:
            self._after()


def _fmt_clock(result):
    if result is None:
        return {'state': 'unreadable', 'text': 'Could not be read'}
    when = result[0]
    if when is None:
        return {'state': 'unset', 'text': 'Not set'}
    return {'state': 'set', 'text': when.strftime('%d %b %Y, %H:%M:%S')}


# The AcoustID key built into the program (acoustid_full.py).
try:
    from acoustid_full import KEY as _BUILTIN_ACOUSTID_KEY
except ImportError:
    _BUILTIN_ACOUSTID_KEY = ''


class Api(lp_to_sp.LpToSpMixin, app_settings.AppSettingsMixin, backup_data.BackupMixin, edit_tracks.EditMixin, clone_disc.CloneMixin, convert_disc.ConvertMixin,netmd_disc.NetMdMixin, netmd_edit.NetMdEditMixin, disc_tools.DiscToolsMixin, cover_search.CoverSearchMixin, pc_audio.PcAudioMixin, save_pc.SavePcMixin, catalogue.CatalogueMixin, identify_tracks.IdentifyMixin, play_tracks.PlayMixin, copies.CopiesMixin, lyrics.LyricsMixin, groupart.GroupArtMixin, lyrics_asr.AsrMixin, disc_edit.DiscEditMixin, disc_lookup.DiscLookupMixin,
          sonos_cast.CastMixin, cd_audio.CdMixin, yoto_disc.YotoMixin, site_record.SiteRecordMixin, label_print.LabelMixin, video_links.VideoLinksMixin):
    def __init__(self):
        self._window = None
        self._devices = []
        self._tracks = []
        self._thread = None            # playback read in progress, if any
        self._active = None
        self._proc = None
        self._streams = {}             # file name -> state, for the local media server
        self._cache = {}               # track key -> finished state
        self._server = None
        self._port = 0
        self._token = secrets.token_urlsafe(8)
        self._disc_key = None
        self._netmd_from = 0           # self._devices[i] for i >= this is a NetMD recorder (a standard disc is inside)
        self._loaded_netmd = False     # the recorder the page has loaded holds a standard disc
        self._netmd_sig = None
        self._preview_dir = None    # the short 'what was read' previews of the last Identify run
        self._play_mutex = threading.Lock()   # one 'start a track' at a time; a newer request replaces an older one
        self._play_seq = 0
        self._lock = _Gate(self._cancel_extract, self._drive_touched)  # one USB operation at a time (and playing then no longer knows where the drive is parked)
        self._cast_init()              # Sonos casting state (sonos_cast.py)
        self._cd_init()                # audio CD state (cd_audio.py)
        self._yoto_init()              # Yoto sign-in and state (yoto_disc.py)
        self._edit_init()              # split / combine editor state (edit_tracks.py)
        self._clone_init()             # disc clone state (clone_disc.py)
        self._save_init()              # save-to-PC state (save_pc.py)
        self._site_init()              # the streaming-site recorder windows (site_record.py)
        self._ly_init()                # lyrics of tracks (lyrics.py)
        self._dl_init()                # online lookup of a standard disc's artist, album and art (disc_lookup.py)
        self._catalogue_init()         # which disc is showing, and whether this app changed a standard disc (catalogue.py)

    def _release_devices(self):
        """Close this process's handles on the recorders: Windows allows only one open handle per device."""
        for d in self._devices:
            try:
                usb.util.dispose_resources(d)
            except (usb.core.USBError, ValueError):
                pass

    def scan(self):
        with self._lock:
            try:
                self._release_devices()
                himd_devs = himd_dev.find_devices()
                self._devices = himd_devs + himd_dev.find_netmd_devices()
                self._netmd_from = len(himd_devs)
            except Exception as exc:
                self._devices = []
                self._netmd_from = 0
                return {'error': 'USB scan failed: %s' % exc, 'devices': []}
            return {'devices': [
                {'index': i, 'name': self._device_name(i), 'mode': 'netmd' if self._is_netmd(i) else 'himd',
                 'usb': '%04X:%04X' % (d.idVendor, d.idProduct)}
                for i, d in enumerate(self._devices)]}

    def _is_netmd(self, index):
        return int(index) >= self._netmd_from

    def _can_fetch(self, index):
        """Only some NetMD recorders (the MZ-RH1) can send a track back to the PC."""
        return self._devices[int(index)].idProduct in FETCH_PIDS

    def _exploit_possible(self, index):
        """A recorder that cannot send audio back by itself but may take the experimental download (the helper checks its firmware)."""
        pid = self._devices[int(index)].idProduct
        return pid in EXPLOIT_PIDS and pid not in FETCH_PIDS

    def _device_name(self, index):
        d = self._devices[index]
        if self._is_netmd(index):
            return '%s (standard disc)' % himd_dev.NETMD_IDS.get((d.idVendor, d.idProduct), 'NetMD recorder')
        return MODELS.get(d.idProduct, 'Hi-MD device')

    def load(self, index):
        with self._lock:
            try:
                usb_dev = self._devices[int(index)]
            except (IndexError, ValueError):
                return {'error': 'That recorder is no longer connected. Press rescan.'}
            self._loaded_netmd = self._is_netmd(index)
            if self._loaded_netmd:
                return self._load_netmd(usb_dev)
            try:
                dev = himd_dev.Device(usb_dev)
                inq = dev.inquiry()
                try:
                    clock = _fmt_clock(dev.get_time())
                except himd_dev.HiMDError:
                    clock = _fmt_clock(None)
                self._recorder_name = MODELS.get(usb_dev.idProduct, 'Hi-MD device')      # shown on a Google TV's lyric video
                out = {
                    'model': MODELS.get(usb_dev.idProduct, 'Hi-MD device'),
                    'reports': '%s %s' % (inq['vendor'], inq['product']),
                    'revision': inq['revision'], 'firmware': (inq['revision'] or '').strip(), 'year': recorder_year(MODELS.get(usb_dev.idProduct, '')), 'info': self._recorder_info(MODELS.get(usb_dev.idProduct, '')),
                    'clock': clock,
                    'disc': None,
                }
                cap = dev.capacity()
                if not cap:
                    out['discState'] = 'none'
                    return out
                try:
                    fs = himd_fs.Fat16(dev)
                    disc = himd_disc.Disc(fs)
                except (himd_fs.FatError, himd_dev.HiMDError) as exc:
                    out['discState'] = 'unreadable'
                    out['discMessage'] = str(exc)
                    return out
                groups = disc.groups()
                tracks = disc.tracks()
                for t in tracks:
                    g = next((g for g in groups if g['first'] <= t['number'] <= g['last']), None)
                    t['group'] = (g['title'] or 'Group %d' % g['index']) if g else ''
                    t['groupIndex'] = g['index'] if g else 0
                    t['groupTitle'] = g['title'] if g else ''
                    t['deletable'] = t['codec'] in ('MP3', 'PCM', 'A3+', 'AT3')
                    t['secure'] = t['codec'] != 'MP3'            # deleting needs the signing session; the audio is the disc's only copy
                self._tracks = tracks
                lyrics_stale = self._ly_on_load(fs, tracks)           # lyrics kept on this PC and in LYRICS.TXT on the disc: marks each track
                try:
                    self._disc_key = self._disc_id(fs, disc)
                except Exception:
                    self._disc_key = None
                total = fs.cluster_count * fs.cluster_bytes
                free = fs.free_clusters() * fs.cluster_bytes
                self._disc_free = free                               # for edit_staged_status
                cover = None                                       # a picture stored on the disc as COVER.JPG in the root folder
                try:
                    ent = next((e for e in fs.listdir('/') if not e['dir'] and e['short'].upper() == 'COVER.JPG'), None)
                    if ent and 0 < ent['size'] <= 1500000:
                        cover = 'data:image/jpeg;base64,' + base64.b64encode(fs.read_file('/COVER.JPG')).decode()
                except Exception:
                    cover = None
                self._cover_url = cover                            # the lyric video for a Google TV draws this picture
                label = None                                       # the sticker label stored on the disc as LABEL.JPG in the root folder
                try:
                    ent = next((e for e in fs.listdir('/') if not e['dir'] and e['short'].upper() == 'LABEL.JPG'), None)
                    if ent and 0 < ent['size'] <= 1500000:
                        label = 'data:image/jpeg;base64,' + base64.b64encode(fs.read_file('/LABEL.JPG')).decode()
                except Exception:
                    label = None
                self._ga_disc = {}                                     # the group pictures stored on the disc as GROUPART.JSN in the root folder
                try:
                    ent = next((e for e in fs.listdir('/') if not e['dir'] and e['short'].upper() == 'GROUPART.JSN'), None)
                    if ent and 0 < ent['size'] <= 4000000:
                        self._ga_disc = self._ga_parse(fs.read_file('/GROUPART.JSN'))
                except Exception:
                    self._ga_disc = {}
                tracklist, has_list, raw, listed = 'unknown', False, None, False      # TRACKS.CSV in the root folder: is it there, and does it match the tracks?
                try:
                    ent = next((e for e in fs.listdir('/') if not e['dir'] and e['short'].upper() == 'TRACKS.CSV'), None)
                    has_list = ent is not None
                    raw = bytes(fs.read_file('/TRACKS.CSV')) if ent else None
                    listed = True
                except Exception:
                    pass
                self._video_on_load(tracks, raw)                         # YouTube links: the PC's list plus those in the disc's track list; marks each track
                if listed:
                    tracklist = ('current' if raw == self._tracklist_bytes(tracks) else 'stale') if raw is not None else ('none' if tracks else 'current')
                extras = {}                                            # sizes of the small files kept in the root folder: lyrics, picture, track list
                try:
                    for e in fs.listdir('/'):
                        k = {'LYRICS.TXT': 'lyrics', 'COVER.JPG': 'cover', 'LABEL.JPG': 'label', 'TRACKS.CSV': 'list', 'GROUPART.JSN': 'groupart'}.get(e['short'].upper())
                        if k and not e['dir']:
                            extras[k] = e['size']
                except Exception:
                    pass
                try:                                                   # video links live inside TRACKS.CSV: show their bytes as "Video", the rest as "Track list"
                    if raw and 'list' in extras:
                        import csv as _csv, io as _io
                        vb = sum(len((r.get('Video') or '').strip().encode('utf-8')) + 1 for r in _csv.DictReader(_io.StringIO(bytes(raw).decode('utf-8-sig'))) if (r.get('Video') or '').strip())
                        if vb:
                            extras['video'] = vb
                            extras['list'] = max(0, extras['list'] - vb)
                except Exception:
                    pass
                out['discState'] = 'ok'
                self._catalogue_note(self._disc_key, disc.disc_title(), tracks, out.get('model', ''))
                out['disc'] = {'title': disc.disc_title(), 'total': total, 'free': free,
                               'tracks': tracks, 'seconds': sum(t['seconds'] for t in tracks),
                               'blockSize': 16384, 'cover': cover, 'label': label, 'tracklist': tracklist, 'hasTracklist': has_list, 'groupArt': {'pc': self._ga_state()['pc'], 'disc': self._ga_disc}, 'lyricsStale': lyrics_stale,
                               'audioBytes': getattr(disc, 'audio_bytes', None), 'extras': extras,
                               'key': ('himd-' + self._disc_key) if self._disc_key else None}       # stable disc id: the page keeps equalizer settings per disc
                return out
            except usb.core.USBError as exc:
                return {'error': 'Could not talk to the recorder (%s). Close any other program that uses '
                                 'it, then reload.' % exc}
            except himd_dev.HiMDError as exc:
                return {'error': str(exc)}

    def _load_netmd(self, usb_dev):
        """A standard MiniDisc: read through netmd_helper.js. Shaped like a Hi-MD load so the page can reuse it."""
        res = self._run_helper('list', {}, helper=NETMD_HELPER)
        if 'error' in res:
            return {'error': res['error']}
        d = res['result']
        name = himd_dev.NETMD_IDS.get((usb_dev.idVendor, usb_dev.idProduct), 'NetMD recorder')
        self._recorder_name = (d.get('device') or name).replace('Sony ', '')               # shown on a Google TV's lyric video
        out = {'model': (d.get('device') or name).replace('Sony ', ''), 'reports': 'Standard MiniDisc (NetMD)', 'revision': '-', 'firmware': d.get('firmware') or '', 'year': recorder_year(d.get('device') or name), 'info': self._recorder_info(d.get('device') or name),
               'clock': {'state': 'unreadable', 'text': 'Not available for standard discs'}, 'mode': 'netmd', 'disc': None}
        if not d['status'].get('discPresent'):
            out['discState'] = 'none'
            return out
        tracks = []
        for g in d['groups']:
            for t in g['tracks']:
                tracks.append({'number': t['index'] + 1, 'title': t['title'] or '(untitled)', 'artist': '', 'album': '',
                               'codec': t['codec'] + (' mono' if t['mono'] else ''), 'kbps': {'SP': 292, 'LP2': 132, 'LP4': 66}.get(t['codec'], 0),
                               'seconds': t['seconds'], 'blocks': t['seconds'] * UNITS_PER_SECOND, 'key': '',
                               'group': g['title'] or '', 'groupIndex': 0, 'groupTitle': g['title'] or '',
                               'deletable': not d['writeProtected'], 'secure': False})
        copies = self._copy_index()                                                     # read once, not once per track
        for t in tracks:
            t['hasCopy'] = self._find_copy(t['title'], t['seconds'], copies, t['codec']) is not None       # playable here from the saved copy
        tracks.sort(key=lambda t: t['number'])
        self._netmd_details_apply(tracks)                                               # the artist and album this PC remembers (a standard disc cannot store them)
        self._tracks = tracks
        self._ly_on_load_netmd(tracks)
        self._video_on_load(tracks)
        self._disc_key = None
        self._netmd_disc_title = d['discTitle'] or ''                                   # a standard disc has no artist / album fields: the TV shows this instead
        writable = d.get('writable')                                                     # the disc's "recordable" flag; a pre-recorded (pre-mastered) commercial disc lacks it
        self._netmd_commercial = writable is False
        try:
            self.log('standard disc writable=%s writeProtected=%s commercial=%s' % (writable, d.get('writeProtected'), self._netmd_commercial))
        except Exception:
            pass
        self._netmd_sig = '%s|%s|%s' % (d['used'], d['trackCount'], d['discTitle'])      # tells one state of the disc from another
        self._catalogue_note_netmd(d['discTitle'] or '', tracks, out.get('model', ''))
        out['canFetch'] = usb_dev.idProduct in FETCH_PIDS
        out['canExploit'] = usb_dev.idProduct in EXPLOIT_PIDS and usb_dev.idProduct not in FETCH_PIDS
        out['canHimd'] = self._himd_capable(usb_dev)
        out['discState'] = 'ok'
        out['disc'] = {'title': d['discTitle'] or '', 'total': d['total'], 'free': d['left'], 'tracks': tracks,
                       'seconds': sum(t['seconds'] for t in tracks), 'blockSize': 1, 'netmd': True,
                       'writeProtected': d['writeProtected'], 'perSecond': UNITS_PER_SECOND, 'commercial': self._netmd_commercial,
                       'key': self._netmd_disc_key(tracks),                  # the page keeps equalizer settings per disc
                       'pcCover': self._dl_cover_url(self._netmd_disc_key(tracks))}       # album art found online, kept on this PC (not on the disc)
        try:
            self._dl_background()                                                # artist, album and art found in the background, once per disc
        except Exception:
            pass
        return out

    def set_clock(self, index):
        if self._is_netmd(index):
            return {'error': 'Standard discs have no clock setting here.'}
        with self._lock:
            try:
                dev = himd_dev.Device(self._devices[int(index)])
                dev.set_time(datetime.datetime.now().replace(microsecond=0))
                return {'clock': _fmt_clock(dev.get_time())}
            except (usb.core.USBError, himd_dev.HiMDError, IndexError, ValueError) as exc:
                return {'error': 'Setting the clock failed: %s' % exc}

    def name_release(self, rid):
        """The tracks of one MusicBrainz release (every side / disc in one list), for naming tracks recorded from a record."""
        try:
            return {'release': cdrip.release_flat(rid)}
        except cdrip.CdError as exc:
            return self._cd_fail(exc)

    ACOUSTID_BUILTIN_KEY = _BUILTIN_ACOUSTID_KEY   # the key itself is used by identify_tracks.IdentifyMixin

    # -- adding tracks (done by himd-js through helper/himd_helper.js) --
    def _run_helper(self, cmd, args, on_event=None, helper=None, idle_timeout=None):
        """idle_timeout: seconds without any output after which the helper is judged stuck and ended (for writes, which normally answer in well under that)."""
        if not os.path.exists(NODE_EXE):
            return {'error': 'The bundled runtime is missing (%s). Re-copy the runtime folder.' % NODE_EXE}
        for d in self._devices:                       # make sure this process is not holding the recorder
            try:
                usb.util.dispose_resources(d)
            except usb.core.USBError:
                pass
        env = dict(os.environ)
        if helper == NETMD_HELPER and cmd in catalogue.NETMD_WRITES:
            self._netmd_wrote = True                  # the catalogue then treats the next load of this standard disc as the same disc, changed
        proc = subprocess.Popen([NODE_EXE, helper or HELPER, cmd, json.dumps(args)], stdout=subprocess.PIPE,
                                stdin=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
                                encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._proc = proc
        result, error, other = None, None, []
        last, stuck = [time.time()], []
        if idle_timeout:
            def watchdog():
                while proc.poll() is None:
                    time.sleep(2)
                    if proc.poll() is None and time.time() - last[0] > idle_timeout:
                        stuck.append(True)
                        try:
                            proc.kill()
                        except OSError:
                            pass
                        return
            threading.Thread(target=watchdog, daemon=True).start()
        for line in proc.stdout:
            last[0] = time.time()
            try:
                msg = json.loads(line)
            except ValueError:
                other.append(line.strip())
                continue
            if 'event' in msg:
                if on_event:
                    on_event(msg)
            elif 'result' in msg:
                result = msg['result']
            elif 'error' in msg:
                error = msg['error']
        proc.wait()
        if stuck and result is None:
            return {'error': 'The recorder stopped answering after %d seconds, so the operation was ended. The disc may be left half changed: '
                             'unplug and replug the USB cable (and reseat the disc), then check the track list before doing anything else.' % idle_timeout}
        if error:
            return {'error': error}
        if result is None:
            return {'error': 'The helper stopped without a result. %s' % ' '.join(other[-3:])}
        return {'result': result}

    def set_zoom(self, factor):
        """Scales the whole window like a browser page (Shift and + / -). 1.0 is normal size."""
        try:
            factor = max(0.5, min(3.0, float(factor)))
            if IS_LINUX:                                   # WebKitGTK: the page's zoom level, set on the GTK thread
                from gi.repository import GLib
                from webview.platforms.gtk import BrowserView
                view = BrowserView.instances[self._window.uid].webview
                GLib.idle_add(lambda: view.set_zoom_level(factor) and False)
                return {'zoom': factor}
            wv = self._window.native.webview               # the WebView2 control; its zoom must be set on the window's own thread
            from System import Func, Type
            def apply():
                wv.ZoomFactor = factor
            if wv.InvokeRequired:
                wv.Invoke(Func[Type](apply))
            else:
                apply()
            return {'zoom': factor}
        except Exception as exc:
            return {'error': 'Could not change the size: %s' % exc}

    def desktop_theme(self):
        """The desktop's own theme for the page's 'Omarchy' theme (colours and font), or None when there is none (Windows, macOS,
        Linux without Omarchy)."""
        return omarchy_theme()

    def log(self, text):
        """Page-side diagnostics (audio events, script errors) -> app.log (next to the app, or under AppData when installed)."""
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            path = os.path.join(USER_DIR, 'app.log')
            if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:     # keep the log small: one older copy
                os.replace(path, path + '.old')
            with open(path, 'a', encoding='utf-8') as f:
                f.write('%s %s\n' % (datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3], str(text)[:500]))
        except OSError:
            pass
        return {'ok': True}

    def app_info(self):
        """The version, and whether this is the packaged program (installed or unzipped) rather than the source folder."""
        return {'version': APP_VERSION, 'packaged': FROZEN, 'license': LICENSE.status()}

    # -- license (the paid edition only; in the personal build LICENSE.required is False and all of this is inert) -------
    def license_status(self):
        return LICENSE.status()

    def _license_allowed(self):
        return LICENSE.allowed()

    def license_activate(self, key):
        r = LICENSE.activate(key)
        return dict(r, status=LICENSE.status())

    def license_deactivate(self):
        r = LICENSE.deactivate()
        return dict(r, status=LICENSE.status())

    def license_buy(self):
        if LICENSE.buy_url.startswith('https://'):
            webbrowser.open(LICENSE.buy_url)
            return {'ok': True}
        return {'error': 'The purchase page has not been set up yet.'}

    def first_run_notice(self):
        """An installed copy shows a safety notice once (what the program can do to a disc, and to back up first)."""
        return {'show': FROZEN and not os.path.exists(FIRST_RUN_FILE)}

    def ack_first_run(self):
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            with open(FIRST_RUN_FILE, 'w', encoding='utf-8') as f:
                f.write('The first-run notice was accepted on %s.\n' % datetime.datetime.now().isoformat(timespec='seconds'))
        except OSError:
            pass
        return {'ok': True}

    def open_driver_guide(self):
        """Opens DRIVER-SETUP.html (how to put the WinUSB driver on a recorder) in the default browser; on Linux, linux/README.md."""
        path = os.path.join(HERE, 'linux', 'README.md') if IS_LINUX else os.path.join(HERE, 'DRIVER-SETUP.html')
        if not os.path.isfile(path):
            return {'error': 'The driver guide (%s) is missing from the app folder.' % os.path.basename(path)}
        try:
            open_path(path)
        except OSError as exc:
            return {'error': 'Could not open the driver guide: %s' % exc}
        return {'ok': True}

    def pick_files(self):
        kind = getattr(getattr(webview, 'FileDialog', None), 'OPEN', None) or webview.OPEN_DIALOG
        types = ('Audio files (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac;*.wma;*.aif;*.aiff;*.dts;*.dtshd;*.ac3;*.eac3;*.thd;*.mlp;*.mka;*.mkv;*.m2ts)',)
        paths = self._window.create_file_dialog(kind, allow_multiple=True, file_types=types)
        return {'paths': list(paths or [])}

    def plan_upload(self, paths):
        """Dry run: reads the disc, writes nothing."""
        with self._lock:
            if self._loaded_netmd:
                return self._run_helper('plan', {'files': list(paths)}, helper=NETMD_HELPER)
            return self._run_helper('plan', {'files': list(paths)})

    def upload(self, files, fmt='sp', mp3_kbps=192):
        """WRITES TO THE DISC. `files` is a list of {path, title, artist, album}. On a standard disc `fmt` is sp, lp2 or lp4; on a
        Hi-MD disc it is auto, pcm, mp3, lp2, lp4, hisp (ATRAC3+ Hi-SP 256 kbps), hilp (Hi-LP 64 kbps) or at3p (ATRAC3+ 352 kbps); mp3_kbps: 128, 192, 256 or 320 when
        audio has to be encoded to MP3."""
        def progress(msg):
            if self._window:
                self._window.evaluate_js('window.onUploadProgress && window.onUploadProgress(%s)' % json.dumps(msg))
        with self._lock:
            self._drop_cache()
            if not self._loaded_netmd:                 # Hi-MD: automatic (MP3 as MP3, the rest as PCM), or one chosen format for every file
                try:
                    kbps = int(mp3_kbps)
                except (TypeError, ValueError):
                    kbps = 192
                return self._run_helper('upload', {'files': list(files), 'format': fmt if fmt in ('auto', 'pcm', 'mp3', 'lp2', 'lp4', 'at3p', 'hisp', 'hilp') else 'auto',
                                                   'mp3Kbps': kbps if kbps in (128, 192, 256, 320) else 192}, progress)
            fmt = fmt if fmt in ('sp', 'lp2', 'lp4') else 'sp'
            res = self._run_helper('upload', {'files': list(files), 'copyDir': COPIES_DIR, 'format': fmt}, progress, helper=NETMD_HELPER)
            try:
                self._save_copies((res.get('result') or {}).get('copies'), fmt)
            except OSError:
                pass                                       # the tracks are on the disc; only playing them here is affected
            return res


# Everything that changes a disc, rips, records, clones or saves needs a valid license or a running trial (paid edition only). Looking at a
# disc and playing it stay free. The page shows the license sheet when it sees `licenseRequired` in an answer.
GATED = ('upload', 'bc_open', 'radio_start', 'bc_add', 'cd_rip_add', 'yoto_rip_add', 'yoto_send', 'edit_run', 'clone_read', 'clone_write', 'delete_tracks', 'rename_track', 'rename_tracks_each', 'move_track',
         'rename_group', 'make_group', 'make_groups', 'release_group', 'add_to_group', 'rename_disc', 'undo', 'set_clock', 'cover_set', 'cover_remove', 'label_save_disc', 'label_remove', 'format_disc', 'convert_read', 'convert_write', 'lpsp_read', 'lpsp_run', 'lpsp_spill_write', 'save_tracks','cd_burn_run', 'cd_burn_erase', 'cd_data_run', 'lyrics_save_disc', 'groupart_save_disc')


def _gate(fn):
    @functools.wraps(fn)
    def gated(*args, **kwargs):
        if not LICENSE.allowed():
            return {'error': 'The trial has ended. Enter a license key to keep changing discs.', 'licenseRequired': True}
        return fn(*args, **kwargs)
    return gated


for _name in GATED:
    setattr(Api, _name, _gate(getattr(Api, _name)))


def _sweep_temp(min_age=300):
    """Deletes the working folders of earlier runs from the Temp folder (the split editor's copy of a track, a split or clone in progress,
    the disc picture): they are only needed while a window is open. Folders younger than `min_age` seconds are left alone."""
    base = tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except OSError:
        return
    now = time.time()
    for name in names:
        if name.startswith(('mdm-split-', 'mdm-edit-', 'mdm-clone-', 'mdm-cover-', 'mdm-preview-', 'mdm-listen-')):
            path = os.path.join(base, name)
            try:
                if os.path.isdir(path) and now - os.path.getmtime(path) > min_age:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass


WINDOW_FILE = os.path.join(data_root(HERE), 'MiniDiscManager', 'window.json')     # the window's size, place and maximised state
WINDOW_DEFAULT, WINDOW_MIN = (1280, 820), (820, 560)


class WindowMemory:
    """Remembers where the window was and how big, and whether it was maximised, and puts it back at the next start. Kept in the same logical
    units the window library uses for creating and resizing, so the size does not drift on a scaled display. Anything unreadable or nonsensical
    (a monitor that is gone, a damaged file) is ignored and the window opens at its default size."""

    def __init__(self):
        self.width, self.height = WINDOW_DEFAULT
        self.x = self.y = None
        self.maximized = False
        self._timer = None
        self._lock = threading.Lock()
        self._start_size()                                              # always opens at a size that shows the full width of the cards; last time's size is not used

    def _start_size(self):
        """The same start size every time: wide enough for the whole row of cards, tall enough to show most things, centred, not maximised."""
        try:
            sw, sh = webview.screens[0].width, webview.screens[0].height
            try:
                import ctypes
                scale = max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)     # the screen is reported in real pixels, the window is sized in scaled (logical) units
            except Exception:
                scale = 1.0
            sw, sh = int(sw / scale), int(sh / scale)
        except Exception:
            return                                                      # no screen information: the default size
        w = min(sw - 40, min(2600, max(1400, int(sw * .8))))                # 80 % of the screen's width (1400 to 2600), so the whole row of cards shows
        h = min(sh - 80, min(1500, max(820, int(sh * .88))))                # 88 % of its height: most of the page, but not full screen
        self.width, self.height = max(WINDOW_MIN[0], w), max(WINDOW_MIN[1], h)
        self.x, self.y = max(0, (sw - self.width) // 2), max(0, (sh - self.height) // 2 - 20)
        self.maximized = False

    def _load(self):
        try:
            with open(WINDOW_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            w, h = int(d['width']), int(d['height'])
            if WINDOW_MIN[0] <= w <= 10000 and WINDOW_MIN[1] <= h <= 6000:
                self.width, self.height = w, h
            x, y = d.get('x'), d.get('y')
            if isinstance(x, int) and isinstance(y, int) and self._on_a_screen(x, y):
                self.x, self.y = x, y
            self.maximized = bool(d.get('maximized'))
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @staticmethod
    def _on_a_screen(x, y):
        """True if the window's title-bar area would be on some screen (so a removed monitor cannot leave it out of reach)."""
        try:
            screens = [(s.x, s.y, s.width, s.height) for s in webview.screens]
        except Exception:
            return -200 <= x <= 7000 and -50 <= y <= 4000
        px, py = x + 120, y + 20
        return any(sx - 200 <= px < sx + sw + 200 and sy - 50 <= py < sy + sh for sx, sy, sw, sh in screens)

    def save(self):
        with self._lock:
            data = {'width': self.width, 'height': self.height, 'x': self.x, 'y': self.y, 'maximized': self.maximized}
            try:
                os.makedirs(os.path.dirname(WINDOW_FILE), exist_ok=True)
                tmp = WINDOW_FILE + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                os.replace(tmp, WINDOW_FILE)
            except OSError:
                pass

    def _later(self):                                                   # a drag fires many events: write once, a moment after the last
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(1.0, self.save)
        self._timer.daemon = True
        self._timer.start()

    # window events (the library calls these with the new values)
    def on_resized(self, width, height):
        if not self.maximized and width >= WINDOW_MIN[0] and height >= WINDOW_MIN[1]:      # a maximised window's size is not the one to remember
            self.width, self.height = int(width), int(height)
            self._later()

    def on_moved(self, x, y):
        if not self.maximized:
            self.x, self.y = int(x), int(y)
            self._later()

    def on_maximized(self):
        self.maximized = True
        self._later()

    def on_restored(self):
        self.maximized = False
        self._later()


def main():
    api = Api()
    LICENSE._log = api.log
    threading.Thread(target=LICENSE.refresh, daemon=True).start()          # is the key still good? (once a day, silently)
    shutil.rmtree(PLAY_DIR, ignore_errors=True)
    shutil.rmtree(BC_DIR, ignore_errors=True)
    os.makedirs(WEBVIEW_DIR, exist_ok=True)
    # The window keeps a browser profile (for the Bandcamp login), and its page cache can serve the previous version's index.html after an
    # upgrade (found 2026-10-26: v0.13.3 showed the 0.13.2 split editor). Drop only the page caches when the version changes; cookies stay.
    # The page file's own size and date are part of the stamp too, so a page changed without a new version number (running from the source
    # folder while it is being worked on) is never shown from an old cached copy either.
    marker = os.path.join(WEBVIEW_DIR, 'cache_version.txt')
    try:
        page = os.stat(os.path.join(HERE, 'ui', 'index.html'))
        stamp = '%s|%d|%d' % (APP_VERSION, page.st_size, int(page.st_mtime))
    except OSError:
        stamp = APP_VERSION
    try:
        with open(marker, 'r', encoding='utf-8') as f:
            seen = f.read().strip()
    except OSError:
        seen = ''
    if seen != stamp:
        for name in ('Cache', 'Code Cache', 'GPUCache'):
            shutil.rmtree(os.path.join(WEBVIEW_DIR, 'EBWebView', 'Default', name), ignore_errors=True)
        try:
            with open(marker, 'w', encoding='utf-8') as f:
                f.write(stamp)
        except OSError:
            pass
    _sweep_temp()                                                       # working copies an earlier run left behind (a crash, or the program closed from outside)

    def cleanup():                                                      # every step on its own, so one failing step cannot skip the rest
        for step in (api._cancel_extract, api.stop_cast, api._edit_prep_clear, api._preview_clear, lambda: shutil.rmtree(PLAY_DIR, ignore_errors=True),
                     lambda: [r.stop() for r in list(api._recs.values())], lambda: shutil.rmtree(BC_DIR, ignore_errors=True),
                     lambda: shutil.rmtree(REC_DIR, ignore_errors=True)):          # recordings live only until the program is closed
            try:
                step()
            except Exception:
                pass
    atexit.register(cleanup)
    ui = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui', 'index.html')
    mem = WindowMemory()                                                # the size and place from last time
    api._window = webview.create_window('MiniDisc Manager', ui, js_api=api, width=mem.width, height=mem.height, x=mem.x, y=mem.y, maximized=mem.maximized,
                                       min_size=WINDOW_MIN, background_color='#0f1115', text_select=True)       # text_select: error messages and track names can be copied
    api._window.events.resized += mem.on_resized
    api._window.events.moved += mem.on_moved
    api._window.events.maximized += mem.on_maximized
    api._window.events.restored += mem.on_restored
    def on_loaded():
        # Dropped files: only the Python side sees their full paths.
        from webview.dom import DOMEventHandler

        def on_drop(event):
            paths = [f.get('pywebviewFullPath') for f in event['dataTransfer']['files'] if f.get('pywebviewFullPath')]
            if paths:
                api._window.evaluate_js('window.onFilesDropped && window.onFilesDropped(%s)' % json.dumps(paths))

        api._window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)

    api._window.events.loaded += on_loaded
    def on_closing(*args):
        # Closing the window must not leave a room playing on its own. This handler must return None: the window library reads
        # a returned False as "cancel the close", so stop_cast()'s own True/False answer must not be passed on.
        try:
            mem.save()                                                  # the size and place for next time
        except Exception:
            pass
        try:
            api.stop_cast()
        except Exception:
            pass
        try:
            for w in list(api._wins.values()):
                if w:
                    w.destroy()
        except Exception:
            pass

    api._window.events.closing += on_closing
    webview.start(private_mode=False, storage_path=WEBVIEW_DIR)


if __name__ == '__main__':
    main()

