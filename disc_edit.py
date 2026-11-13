"""Changing a disc's names and order: rename a track / group / the disc, give several tracks details, move tracks, and Undo. DiscEditMixin is
mixed into himd_app.Api (which supplies _lock, _devices, _tracks, _is_netmd, _run_helper, _drop_cache, _drop_copy).
WRITES TO THE DISC: on a Hi-MD disc only the changed sectors of the track index are written (after a backup in BACKUP_DIR) and read back to
verify; on a standard disc the NetMD helper does the change."""
import datetime
import json
import os

import usb.core

import himd_dev
import himd_disc
import himd_fs
from mdm_paths import BACKUP_DIR, NETMD_HELPER


class DiscEditMixin:
    @staticmethod
    def _disc_id(fs, disc):
        raw = fs.read_file('/HMDHIFI/MCLIST%02X.HMA' % disc.datanum)
        return raw[0x40:0x50].hex()

    def _secure_delete_args(self, numbers):
        """Extra helper arguments when a delete includes PCM/ATRAC tracks (needs the signing session)."""
        by_number = {t['number']: t for t in self._tracks}
        if not any(by_number.get(n, {}).get('codec') != 'MP3' for n in numbers):
            return {}
        return {'allowSecure': True,
                'backupDir': os.path.join(BACKUP_DIR, 'secure_delete_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))}
    def _write_index(self, dev, fs, disc, new_bytes):
        """Overwrite only the changed sectors of the track index, flush, and verify by reading back.
        Writes stay inside the index file's own clusters. Returns the number of sectors written."""
        lbas, size = fs.file_lbas(disc.tif_path)
        if size != len(new_bytes) or size != len(disc.original):
            raise himd_fs.FatError('The track index has an unexpected size; nothing was written.')
        bps = fs.bps
        changed = [s for s in range(size // bps)
                   if new_bytes[s * bps:(s + 1) * bps] != disc.original[s * bps:(s + 1) * bps]]
        if not changed:
            return 0
        i = 0
        while i < len(changed):                      # group sectors that are adjacent on the disc
            j = i
            while j + 1 < len(changed) and changed[j + 1] == changed[j] + 1 and lbas[changed[j + 1]] == lbas[changed[j]] + 1:
                j += 1
            chunk = b''.join(new_bytes[s * bps:(s + 1) * bps] for s in changed[i:j + 1])
            dev.write10(lbas[changed[i]], chunk)
            i = j + 1
        # himd-js sends no SYNCHRONIZE CACHE here, and on the NH700 sending one left the recorder
        # stuck "busy". Wait for it to go idle, then read the file back from a fresh reader.
        dev.wait_ready()
        check = himd_fs.Fat16(dev).read_file(disc.tif_path)
        if bytes(check) != bytes(new_bytes):
            raise himd_fs.FatError('Verification failed: what the disc now holds is not what was written.')
        return len(changed)

    def _edit(self, index, label, change):
        """Common path for every edit: read, change in memory, back up, write, verify."""
        with self._lock:
            try:
                dev = himd_dev.Device(self._devices[int(index)])
                if not dev.capacity():
                    return {'error': 'There is no disc in the recorder.'}
                fs = himd_fs.Fat16(dev)
                disc = himd_disc.Disc(fs)
                disc_id = self._disc_id(fs, disc)
                change(disc)
                new_bytes = bytes(disc.tif)
                if new_bytes == disc.original:
                    return {'unchanged': True}
                os.makedirs(BACKUP_DIR, exist_ok=True)
                stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
                name = 'TRKIDX%02X_%s' % (disc.datanum, stamp)
                with open(os.path.join(BACKUP_DIR, name + '.HMA'), 'wb') as f:
                    f.write(disc.original)
                with open(os.path.join(BACKUP_DIR, name + '.json'), 'w') as f:
                    json.dump({'datanum': disc.datanum, 'disc_id': disc_id, 'label': label}, f)
                try:
                    self._write_index(dev, fs, disc, new_bytes)
                except Exception as first:
                    # put the original index back before reporting the problem
                    try:
                        dev.wait_ready()
                        fs2 = himd_fs.Fat16(dev)
                        d2 = himd_disc.Disc(fs2)
                        self._write_index(dev, fs2, d2, disc.original)
                    except Exception as second:
                        raise himd_fs.FatError(
                            '%s. Putting the old index back also failed (%s). A copy of the old index is in %s'
                            % (first, second, os.path.join(BACKUP_DIR, name + '.HMA')))
                    raise
            except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError, IndexError, ValueError) as exc:
                return {'error': 'The change was not made: %s' % exc}
        return {'ok': True}

    def _netmd_rename(self, args):
        with self._lock:
            res = self._run_helper('rename', args, helper=NETMD_HELPER)
        return {'error': res['error']} if 'error' in res else {'ok': True, 'title': res['result']['title']}

    def rename_track(self, index, number, field, value):
        if self._is_netmd(index):
            if field != 'title':
                return {'error': 'Standard discs only have track titles.'}
            old = next((t for t in self._tracks if t['number'] == int(number)), None)
            res = self._netmd_rename({'index': int(number) - 1, 'title': (value or '').strip()})
            if old and res.get('ok'):
                try:
                    self._drop_copy(old['title'], old['seconds'], new_title=res['title'])     # keep the saved copy matched to the track
                except OSError:
                    pass
            return res
        if field not in ('title', 'artist', 'album'):
            return {'error': 'Unknown field.'}
        value = (value or '').strip()
        return self._edit(index, 'track %s %s' % (number, field),
                          lambda disc: disc.rename_track(int(number) - 1, **{field: value}))

    def move_track(self, index, number, to):
        """Moves track `number` (1-based) so it ends up at position `to`; the tracks in between shift. Changes only the order."""
        try:
            number, to = int(number), int(to)
        except (TypeError, ValueError):
            return {'error': 'Choose a position by its number.'}
        if not any(t['number'] == number for t in self._tracks) or not 1 <= to <= len(self._tracks):
            return {'error': 'There is no such position on the disc.'}
        if number == to:
            return {'unchanged': True}
        self._drop_cache()                                     # play files are keyed by track number
        if self._is_netmd(index):
            with self._lock:
                res = self._run_helper('move', {'from': number - 1, 'to': to - 1}, helper=NETMD_HELPER)
            return {'error': res['error']} if 'error' in res else {'ok': True}
        return self._edit(index, 'move track %d to %d' % (number, to), lambda disc: disc.move_track(number - 1, to - 1))

    def rename_tracks(self, index, numbers, fields):
        """Sets the artist and / or album of several tracks in one change (Hi-MD only). `fields`: {'artist': text, 'album': text}; a field that
        is left out stays as it is, an empty text removes it."""
        if self._is_netmd(index):
            return {'error': 'Standard discs only have track titles.'}
        try:
            wanted = sorted({int(n) for n in numbers})
        except (TypeError, ValueError):
            return {'error': 'Choose the tracks to change.'}
        change = {k: (fields[k] or '').strip() for k in ('artist', 'album') if isinstance(fields, dict) and fields.get(k) is not None}
        if not wanted or not change:
            return {'error': 'Nothing to change.'}
        if any(not any(t['number'] == n for t in self._tracks) for n in wanted):
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}

        def apply(disc):
            for n in wanted:
                disc.rename_track(n - 1, **change)
        return self._edit(index, 'details of %d tracks' % len(wanted), apply)

    def rename_tracks_each(self, index, items):
        """As _rename_tracks_each_now; when the disc refuses the change (write-protected), the names are kept on this PC (pending-names.json) and
        offered again the next time the disc is loaded and writable, and a standard disc's artist / album are kept as usual."""
        res = self._rename_tracks_each_now(index, items)
        if 'error' in res and (res.get('protected') or 'protect' in res['error'].lower()):          # only a refusal because of the write protection is worth keeping for later
            self.pending_names_save(items)
            if self._is_netmd(index):
                try:
                    self.set_netmd_details(index, [{'number': it.get('number'), 'artist': it.get('artist'), 'album': it.get('album')} for it in items or []])
                except Exception:
                    pass
            res = dict(res, error=res['error'] + ' The names were kept on this PC: the next time this disc is loaded and can be written to, the app offers to put them on it.')
        return res

    def _rename_tracks_each_now(self, index, items):
        """Gives each listed track its own details in one change (Hi-MD only). `items`: [{number, title, artist, album}]; a title that is
        empty is left alone, artist / album are only set when given. A standard disc only has titles, which are set one track at a time."""
        if self._is_netmd(index):
            done, failed = 0, []
            for it in items or []:
                title = str((it or {}).get('title') or '').strip()
                if not title:
                    continue
                res = self.rename_track(index, int(it['number']), 'title', title)
                if 'error' in res:
                    failed.append(res['error'])
                else:
                    done += 1
            if failed and not done:
                if 'rejected' in failed[0].lower():                 # the recorder's own refusal (a long hex string): say what it nearly always means
                    protected = any(not t.get('deletable', True) for t in self._tracks)
                    return {'protected': True, 'error': 'The recorder refused to change the disc.' + (' It reports the disc as write-protected: ' if protected else ' If the disc is write-protected, ') +
                                      'slide the tab on the cartridge so the small hole is closed, put the disc back, press the reload button and try again. (Recorder reply: %s)' % failed[0][:120]}
                return {'error': failed[0]}
            return {'ok': True, 'done': done, 'failed': len(failed)}
        todo = []
        try:
            for it in items or []:
                n = int(it['number'])
                title = str(it.get('title') or '').strip()
                if not title or not any(t['number'] == n for t in self._tracks):
                    continue
                fields = {'title': title}
                for k in ('artist', 'album'):
                    if it.get(k) is not None:
                        fields[k] = str(it[k]).strip()
                todo.append((n, fields))
        except (KeyError, TypeError, ValueError):
            return {'error': 'Those names could not be read.'}
        if not todo:
            return {'error': 'There is nothing to set: no track has a new title.'}

        def apply(disc):
            for n, fields in todo:
                disc.rename_track(n - 1, **fields)
        return self._edit(index, 'names of %d tracks' % len(todo), apply)

    def move_tracks(self, index, numbers, to):
        """Moves the ticked tracks, keeping their order, so the first of them ends up at position `to` (counted among the tracks that stay)."""
        try:
            wanted = sorted({int(n) for n in numbers})
            to = int(to)
        except (TypeError, ValueError):
            return {'error': 'Choose a position by its number.'}
        count = len(self._tracks)
        if not wanted or any(not 1 <= n <= count for n in wanted):
            return {'error': 'Those tracks are no longer on the disc. Reload it.'}
        if len(wanted) == 1:
            return self.move_track(index, wanted[0], to)
        if self._is_netmd(index):
            return {'error': 'Standard discs can move one track at a time.'}
        others = [n for n in range(1, count + 1) if n not in wanted]
        to = max(1, min(to, len(others) + 1))
        final = others[:to - 1] + wanted + others[to - 1:]
        if final == list(range(1, count + 1)):
            return {'unchanged': True}
        self._drop_cache()

        def apply(disc):
            current = list(range(1, count + 1))
            for pos, num in enumerate(final):
                at = current.index(num)
                if at != pos:
                    disc.move_track(at, pos)
                    current.insert(pos, current.pop(at))
        return self._edit(index, 'move %d tracks' % len(wanted), apply)

    def rename_group(self, index, group, value):
        if self._is_netmd(index):
            return {'error': 'Groups on standard discs can’t be renamed here.'}
        value = (value or '').strip()
        return self._edit(index, 'group %s' % group,
                          lambda disc: disc.rename_group_record(int(group), value))

    # -- group tools (Hi-MD only for now): they change only the group records of the track index, never the audio -------------------
    def _group_numbers(self, numbers):
        try:
            wanted = sorted({int(n) for n in numbers})
        except (TypeError, ValueError):
            return None, {'error': 'Choose the tracks first.'}
        if not wanted or any(not any(t['number'] == n for t in self._tracks) for n in wanted):
            return None, {'error': 'Those tracks are no longer on the disc. Reload it.'}
        return wanted, None

    def make_group(self, index, numbers, title):
        """Group the ticked tracks (they must be next to each other) under `title`."""
        if self._is_netmd(index):
            return {'error': 'Groups on standard discs can’t be made here yet.'}
        wanted, err = self._group_numbers(numbers)
        if err:
            return err
        if wanted[-1] - wanted[0] + 1 != len(wanted):
            return {'error': 'Groups hold tracks that are next to each other. Move the tracks together first, or tick a run of tracks.'}
        title = (title or '').strip()
        return self._edit(index, 'group tracks %d-%d' % (wanted[0], wanted[-1]), lambda disc: disc.make_group(wanted[0], wanted[-1], title))

    def make_groups(self, index, groups):
        """Make several groups in one change (one Undo). groups: [{first, last, title}] on tracks that are in no group."""
        if self._is_netmd(index):
            return {'error': 'Groups on standard discs can’t be made here yet.'}
        try:
            new = [(int(g['first']), int(g['last']), str(g.get('title') or '').strip()) for g in groups]
        except (TypeError, ValueError, KeyError):
            return {'error': 'Those groups could not be read.'}
        if not new:
            return {'error': 'There are no groups to make.'}
        return self._edit(index, 'make %d groups' % len(new), lambda disc: disc.add_groups(new))

    def release_group(self, index, group):
        """Ungroup: the group (or list of groups) goes, the tracks stay."""
        if self._is_netmd(index):
            return {'error': 'Groups on standard discs can’t be changed here yet.'}
        try:
            groups = [int(g) for g in group] if isinstance(group, (list, tuple)) else [int(group)]
        except (TypeError, ValueError):
            return {'error': 'Choose a group first.'}
        return self._edit(index, 'release %d group(s)' % len(groups), lambda disc: disc.release_group(groups))

    def add_to_group(self, index, group, numbers):
        """Add the ticked ungrouped tracks to an existing group."""
        if self._is_netmd(index):
            return {'error': 'Groups on standard discs can’t be changed here yet.'}
        wanted, err = self._group_numbers(numbers)
        if err:
            return err
        return self._edit(index, 'add %d tracks to group %s' % (len(wanted), group), lambda disc: disc.add_to_group(int(group), wanted))

    def rename_disc(self, index, value):
        if self._is_netmd(index):
            return self._netmd_rename({'disc': True, 'title': (value or '').strip()})
        value = (value or '').strip()
        return self._edit(index, 'disc title', lambda disc: disc.rename_disc(value))

    def undo(self, index):
        """Restore the most recent saved copy of this disc's track index."""
        if self._is_netmd(index):
            return {'error': 'Undo is not available for standard discs.'}
        with self._lock:
            try:
                dev = himd_dev.Device(self._devices[int(index)])
                if not dev.capacity():
                    return {'error': 'There is no disc in the recorder.'}
                fs = himd_fs.Fat16(dev)
                disc = himd_disc.Disc(fs)
                disc_id = self._disc_id(fs, disc)
                metas = sorted(f for f in (os.listdir(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else [])
                               if f.endswith('.json'))
                for fname in reversed(metas):
                    with open(os.path.join(BACKUP_DIR, fname)) as f:
                        meta = json.load(f)
                    if meta.get('disc_id') == disc_id and meta.get('datanum') == disc.datanum:
                        base = os.path.join(BACKUP_DIR, fname[:-5])
                        with open(base + '.HMA', 'rb') as f:
                            old = f.read()
                        self._write_index(dev, fs, disc, old)
                        os.remove(base + '.HMA')
                        os.remove(base + '.json')
                        return {'ok': True, 'label': meta.get('label', '')}
                return {'error': 'There is nothing to undo for this disc.'}
            except (usb.core.USBError, himd_dev.HiMDError, himd_fs.FatError, IndexError, ValueError, OSError) as exc:
                return {'error': 'Undo failed: %s' % exc}
