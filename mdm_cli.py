"""mdm - MiniDisc Manager from the command line.

Uses the program's own code (the same Api the window uses), so it does exactly what the window does. Only one program can use a recorder
at a time: close MiniDisc Manager first, or add --close-gui.

  mdm devices                         the connected recorders
  mdm show [--json]                   the disc: title, space and tracks
  mdm add FILES... [--format F]       add tracks (shows the plan first; F: sp lp2 lp4 on a standard disc,
                                      auto pcm mp3 lp2 lp4 hisp hilp at3p on a Hi-MD disc)
  mdm rename N TITLE [--artist A] [--album B]   rename a track (artist / album: Hi-MD discs only)
  mdm rename-disc TITLE               rename the disc
  mdm move N TO                       move track N to position TO
  mdm delete N...                     delete tracks (asks first)
  mdm group N... TITLE                group tracks that are next to each other (Hi-MD discs)
  mdm save N...|all --to DIR [--as flac|wav|mp3]   copy tracks to this computer

Track numbers: 3, 3-5, or all. Every change is read back from the disc afterwards and the tracks it should not touch are checked.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FORMATS_NETMD = ('sp', 'lp2', 'lp4')
FORMATS_HIMD = ('auto', 'pcm', 'mp3', 'lp2', 'lp4', 'hisp', 'hilp', 'at3p')


def die(msg, code=1):
    print('mdm: ' + msg, file=sys.stderr)
    sys.exit(code)


def mmss(seconds):
    seconds = int(seconds or 0)
    return '%d:%02d' % (seconds // 60, seconds % 60)


def gui_pids():
    """Process ids of a running MiniDisc Manager window (Linux / macOS)."""
    if sys.platform == 'win32':
        return []
    try:
        out = subprocess.run(['pgrep', '-f', '[h]imd_app.py'], capture_output=True, text=True).stdout
    except OSError:
        return []
    return [int(p) for p in out.split() if p.isdigit() and int(p) != os.getpid()]


def numbers(spec, count):
    """'3', '3-5', 'all' (several allowed) -> sorted 1-based track numbers, checked against the disc."""
    out = set()
    for part in spec:
        for item in str(part).split(','):
            item = item.strip().lower()
            if not item:
                continue
            if item == 'all':
                out.update(range(1, count + 1))
            elif re.fullmatch(r'\d+-\d+', item):
                a, b = map(int, item.split('-'))
                out.update(range(min(a, b), max(a, b) + 1))
            elif item.isdigit():
                out.add(int(item))
            else:
                die('not a track number: %r' % item)
    bad = [n for n in out if not 1 <= n <= count]
    if bad:
        die('the disc has %d tracks; no track %s' % (count, ', '.join(map(str, sorted(bad)))))
    return sorted(out)


def confirm(question, assume_yes):
    if assume_yes:
        return
    if not sys.stdin.isatty():
        die('%s - add --yes to confirm when not running in a terminal' % question)
    if input(question + ' [y/N] ').strip().lower() not in ('y', 'yes'):
        die('nothing was changed', 0)


class Disc:
    """The recorder and its disc, through the program's own Api."""

    def __init__(self, args, need_disc=True):
        pids = gui_pids()
        if pids and not args.close_gui:
            die('MiniDisc Manager is open and is using the recorder. Close it, or add --close-gui.')
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        if pids:
            time.sleep(2)
        import himd_app
        self.api = himd_app.Api()
        scan = self.api.scan()
        if scan.get('error'):
            die(scan['error'])
        self.devices = scan.get('devices') or []
        if not self.devices:
            die('no recorder found (on Linux, has linux/setup.sh been run?)')
        if not need_disc:
            self.index = None
            return
        self.index = self._pick(args.device)
        self.reload()

    def _pick(self, want):
        if want not in (None, 'auto'):
            if str(want).isdigit():
                if int(want) >= len(self.devices):
                    die('there is no recorder %s (see: mdm devices)' % want)
                return int(want)
            hit = [d['index'] for d in self.devices if d['mode'] == want]
            if not hit:
                die('no %s recorder connected (see: mdm devices)' % want)
            return hit[0]
        first = self.devices[0]
        out = self.api.load(first['index'])
        if out.get('discState') == 'none':          # a Hi-MD recorder with a standard disc: its standard-disc entry has the disc
            twin = next((d for d in self.devices if d['index'] != first['index'] and d['mode'] == 'netmd' and d['usb'] == first['usb']), None)
            if twin:
                return twin['index']
        return first['index']

    def reload(self):
        self.info = self.api.load(self.index)
        if self.info.get('error'):
            die(self.info['error'])
        if self.info.get('discState') == 'none':
            die('no disc in the recorder (put the disc in before plugging the recorder in)')
        self.tracks = [dict(t) for t in (self.api._tracks or [])]
        return self.tracks

    @property
    def netmd(self):
        return self.devices[self.index]['mode'] == 'netmd'

    @staticmethod
    def key(t):
        return (t.get('title'), t.get('artist'), t.get('album'), t.get('seconds'), t.get('codec'))

    def check(self, expect_count, keep):
        """Reads the disc back: the track count must be expect_count and each (old, new) pair in keep must still match."""
        after = self.reload()
        problems = []
        if len(after) != expect_count:
            problems.append('the disc has %d tracks, expected %d' % (len(after), expect_count))
        for old, new_number in keep:
            new = next((t for t in after if t['number'] == new_number), None)
            if new is None or self.key(new) != self.key(old):
                problems.append('track %d changed: %s -> %s' % (new_number, self.key(old), new and self.key(new)))
        if problems:
            die('READ-BACK CHECK FAILED: ' + '; '.join(problems))
        print('read back from the disc: %d tracks, all as expected' % len(after))


def show(d, as_json=False):
    disc = d.info.get('disc') or {}
    if as_json:
        print(json.dumps({'device': d.devices[d.index], 'model': d.info.get('model'), 'disc': disc, 'tracks': d.tracks},
                         ensure_ascii=False, indent=1, default=str))
        return
    print('%s  [%s]' % (d.info.get('model') or '?', 'standard disc (NetMD)' if d.netmd else 'Hi-MD disc'))
    title = disc.get('title') or '(no title)'
    total = sum(t.get('seconds') or 0 for t in d.tracks)
    print('Disc: %s  -  %d tracks, %s of audio' % (title, len(d.tracks), mmss(total)))
    w = max([len(t.get('title') or '') for t in d.tracks] + [5])
    group = None
    for t in d.tracks:
        g = t.get('groupTitle') or t.get('group') or ''
        if g != group and (g or group):
            print('  [%s]' % (g or 'no group'))
            group = g
        extra = ' - '.join(x for x in (t.get('artist'), t.get('album')) if x)
        print('  %3d  %-*s  %6s  %-6s %s' % (t['number'], w, t.get('title') or '', mmss(t.get('seconds')), t.get('codec') or '', extra))


def cmd_add(d, args):
    fmts = FORMATS_NETMD if d.netmd else FORMATS_HIMD
    fmt = (args.format or ('sp' if d.netmd else 'auto')).lower()
    if fmt not in fmts:
        die('on a %s the format is one of: %s' % ('standard disc' if d.netmd else 'Hi-MD disc', ' '.join(fmts)))
    paths = [os.path.abspath(os.path.expanduser(p)) for p in args.files]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        die('no such file: ' + ', '.join(missing))
    plan = d.api.plan_upload(paths)
    if plan.get('error'):
        die(plan['error'])
    p = plan.get('result') or {}
    files = p.get('files') or []
    if len(files) != len(paths):
        die('the plan did not cover every file: %s' % json.dumps(p)[:300])
    if args.title and len(files) == 1:
        files[0]['title'] = args.title
    seconds = sum(f.get('seconds') or 0 for f in files)
    print('Adding %d track%s (%s) as %s:' % (len(files), '' if len(files) == 1 else 's', mmss(seconds), fmt.upper()))
    for i, f in enumerate(files, len(d.tracks) + 1):
        print('  %3d  %s%s  %s' % (i, f.get('title') or os.path.basename(f['path']), (' - ' + f['artist']) if f.get('artist') else '',
                                   mmss(f.get('seconds'))))
    left = (p.get('leftSeconds') or {}).get(fmt)
    if left is not None:
        print('Space left for %s: %s' % (fmt.upper(), mmss(left)))
        if seconds > left:
            die('that does not fit (%s needed, %s left)' % (mmss(seconds), mmss(left)))
    for k in ('warnings', 'notes'):
        for w in p.get(k) or []:
            print('  note: %s' % w)
    if args.dry_run:
        print('dry run: nothing was written')
        return
    confirm('Write these to the disc?', args.yes)
    before = list(d.tracks)
    items = [{'path': f['path'], 'title': f.get('title') or '', 'artist': f.get('artist') or '', 'album': f.get('album') or ''} for f in files]
    res = d.api.upload(items, fmt=fmt)
    if res.get('error'):
        die('the upload failed: %s' % res['error'])
    print('written: %s' % json.dumps(res.get('result') or res, ensure_ascii=False)[:200])
    d.check(len(before) + len(files), [(t, t['number']) for t in before])


def cmd_delete(d, args):
    nums = numbers(args.tracks, len(d.tracks))
    print('Deleting:')
    for t in d.tracks:
        if t['number'] in nums:
            print('  %3d  %s  %s' % (t['number'], t.get('title') or '', mmss(t.get('seconds'))))
    confirm('Delete %d track%s from the disc?' % (len(nums), '' if len(nums) == 1 else 's'), args.yes)
    before = list(d.tracks)
    res = d.api.delete_tracks(d.index, nums)
    if res.get('error'):
        die('the delete failed: %s' % res['error'])
    kept = [t for t in before if t['number'] not in nums]
    d.check(len(kept), [(t, i) for i, t in enumerate(kept, 1)])


def cmd_rename(d, args):
    n = numbers([args.track], len(d.tracks))[0]
    before = list(d.tracks)
    for field, value in (('title', args.title), ('artist', args.artist), ('album', args.album)):
        if value is None:
            continue
        res = d.api.rename_track(d.index, n, field, value)
        if res.get('error'):
            die(res['error'])
    d.reload()
    new = d.tracks[n - 1]
    print('track %d: %s' % (n, ' - '.join(x for x in (new.get('title'), new.get('artist'), new.get('album')) if x)))
    d.check(len(before), [(t, t['number']) for t in before if t['number'] != n])


def cmd_rename_disc(d, args):
    res = d.api.rename_disc(d.index, args.title)
    if res.get('error'):
        die(res['error'])
    d.reload()
    print('disc title: %s' % ((d.info.get('disc') or {}).get('title') or '(no title)'))


def cmd_move(d, args):
    n, to = numbers([args.track], len(d.tracks))[0], numbers([args.to], len(d.tracks))[0]
    before = list(d.tracks)
    res = d.api.move_track(d.index, n, to)
    if res.get('error'):
        die(res['error'])
    order = [t for t in before if t['number'] != n]
    order.insert(to - 1, before[n - 1])
    d.check(len(before), [(t, i) for i, t in enumerate(order, 1)])


def cmd_group(d, args):
    if d.netmd:
        die('grouping from here works on Hi-MD discs only')
    nums = numbers(args.tracks, len(d.tracks))
    res = d.api.make_group(d.index, nums, args.title)
    if res.get('error'):
        die(res['error'])
    d.reload()
    print('grouped tracks %s as %r' % (', '.join(map(str, nums)), args.title))


def cmd_save(d, args):
    nums = numbers(args.tracks, len(d.tracks))
    folder = os.path.abspath(os.path.expanduser(args.to))
    os.makedirs(folder, exist_ok=True)
    res = d.api.save_tracks(d.index, nums, folder, fmt=args.as_)
    if res.get('error'):
        die(res['error'])
    print(json.dumps(res.get('result') or res, ensure_ascii=False, indent=1)[:2000])


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mdm', description='MiniDisc Manager from the command line.',
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split('\n\n', 1)[1])
    ap.add_argument('--device', default='auto', help="auto (default), himd, netmd, or a number from 'mdm devices'")
    ap.add_argument('--close-gui', action='store_true', help='close the MiniDisc Manager window if it is open')
    ap.add_argument('-y', '--yes', action='store_true', help='do not ask before writing to the disc')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('devices', help='the connected recorders')
    s = sub.add_parser('show', help='the disc and its tracks')
    s.add_argument('--json', action='store_true')
    s = sub.add_parser('add', help='add tracks from files')
    s.add_argument('files', nargs='+')
    s.add_argument('--format', '-f')
    s.add_argument('--title', help='title for a single file (default: from its tags or name)')
    s.add_argument('--dry-run', action='store_true', help='show the plan only')
    s = sub.add_parser('delete', help='delete tracks')
    s.add_argument('tracks', nargs='+')
    s = sub.add_parser('rename', help='rename a track')
    s.add_argument('track')
    s.add_argument('title', nargs='?')
    s.add_argument('--artist')
    s.add_argument('--album')
    s = sub.add_parser('rename-disc', help='rename the disc')
    s.add_argument('title')
    s = sub.add_parser('move', help='move a track')
    s.add_argument('track')
    s.add_argument('to')
    s = sub.add_parser('group', help='group tracks (Hi-MD)')
    s.add_argument('tracks', nargs='+', help='track numbers, then the group title last')
    s = sub.add_parser('save', help='copy tracks to this computer')
    s.add_argument('tracks', nargs='+')
    s.add_argument('--to', required=True)
    s.add_argument('--as', dest='as_', choices=('flac', 'wav', 'mp3'), default='flac')
    args = ap.parse_args(argv)

    if args.cmd == 'group':
        if len(args.tracks) < 2:
            die('give the track numbers and then the group title')
        args.tracks, args.title = args.tracks[:-1], args.tracks[-1]
    if args.cmd == 'rename' and args.title is None and args.artist is None and args.album is None:
        die('give a new title, --artist or --album')

    d = Disc(args, need_disc=args.cmd != 'devices')
    if args.cmd == 'devices':
        for dev in d.devices:
            print('%d  %-40s %-6s %s' % (dev['index'], dev['name'], dev['mode'], dev['usb']))
        return
    {'show': lambda: show(d, args.json), 'add': lambda: cmd_add(d, args), 'delete': lambda: cmd_delete(d, args),
     'rename': lambda: cmd_rename(d, args), 'rename-disc': lambda: cmd_rename_disc(d, args), 'move': lambda: cmd_move(d, args),
     'group': lambda: cmd_group(d, args), 'save': lambda: cmd_save(d, args)}[args.cmd]()


if __name__ == '__main__':
    main()
