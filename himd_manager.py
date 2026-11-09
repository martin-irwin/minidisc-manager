"""Hi-MD Manager: look at a Hi-MD Walkman and its disc, and set its clock.

Uses only documented commands. The one thing it can change on the recorder is
the clock, and only after you confirm. Close any other program
using the recorder) first, because only one program can use the USB device.
"""
import csv
import datetime
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import usb.core

import himd_dev
import himd_disc
import himd_fs

MODELS = {
    0x017F: 'Sony MZ-NH1', 0x0181: 'Sony MZ-NH3D', 0x0183: 'Sony MZ-NH900',
    0x0185: 'Sony MZ-NH700', 0x0187: 'Sony MZ-NH600', 0x01EA: 'Sony MZ-DH10P',
    0x021A: 'Sony MZ-RH10', 0x021C: 'Sony MZ-RH910', 0x022D: 'Sony CMT-AH10',
    0x023D: 'Sony DS-HMD1', 0x0287: 'Sony MZ-RH1',
}


def fmt_bytes(n):
    return '%.0f MB' % (n / 1e6) if n < 1e9 else '%.2f GB' % (n / 1e9)


def fmt_len(sec):
    return '%d:%02d' % (sec // 60, sec % 60)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Hi-MD Manager')
        self.minsize(760, 520)
        self.devices = []
        self.tracks = []
        self.results = queue.Queue()
        self.busy = False
        self._build()
        self.refresh_devices()
        self.after(100, self._poll)

    # -- layout --------------------------------------------------------
    def _build(self):
        pad = {'padx': 10, 'pady': 6}
        top = ttk.Frame(self)
        top.pack(fill='x', **pad)
        ttk.Label(top, text='Recorder:').pack(side='left')
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(top, textvariable=self.device_var, state='readonly', width=46)
        self.device_box.pack(side='left', padx=8)
        self.device_box.bind('<<ComboboxSelected>>', lambda e: self.load())
        ttk.Button(top, text='Rescan', command=self.refresh_devices).pack(side='left')
        ttk.Button(top, text='Reload', command=self.load).pack(side='left', padx=6)

        info = ttk.LabelFrame(self, text='Recorder')
        info.pack(fill='x', **pad)
        info.columnconfigure(1, weight=1)
        self.labels = {}
        for r, (key, text) in enumerate((('model', 'Model'), ('inquiry', 'Reports as'),
                                         ('clock', 'Clock'), ('disc', 'Disc'))):
            ttk.Label(info, text=text + ':').grid(row=r, column=0, sticky='w', padx=8, pady=2)
            lab = ttk.Label(info, text='-')
            lab.grid(row=r, column=1, sticky='w', padx=4)
            self.labels[key] = lab
        self.clock_btn = ttk.Button(info, text='Set clock to this PC’s time', command=self.set_clock, state='disabled')
        self.clock_btn.grid(row=2, column=2, padx=8, pady=2)

        disc = ttk.LabelFrame(self, text='Disc contents')
        disc.pack(fill='both', expand=True, **pad)
        self.disc_title = ttk.Label(disc, text='-')
        self.disc_title.pack(anchor='w', padx=8, pady=(6, 0))
        cols = ('no', 'title', 'artist', 'group', 'codec', 'rate', 'length')
        self.tree = ttk.Treeview(disc, columns=cols, show='headings', height=10)
        for c, text, w, anchor in (('no', '#', 40, 'e'), ('title', 'Title', 240, 'w'), ('artist', 'Artist', 150, 'w'),
                                   ('group', 'Group', 120, 'w'), ('codec', 'Codec', 60, 'center'),
                                   ('rate', 'kbps', 60, 'e'), ('length', 'Length', 70, 'e')):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == 'title'))
        sb = ttk.Scrollbar(disc, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True, padx=(8, 0), pady=8)
        sb.pack(side='left', fill='y', pady=8, padx=(0, 8))

        bottom = ttk.Frame(self)
        bottom.pack(fill='x', **pad)
        ttk.Button(bottom, text='Export track list (CSV)…', command=self.export_csv).pack(side='left')
        self.status = ttk.Label(bottom, text='', anchor='e')
        self.status.pack(side='right', fill='x', expand=True)
        ttk.Label(self, foreground='#666666', wraplength=720, justify='left',
                  text='Menu settings (record mode, backlight, etc.) cannot be changed from here: no documented '
                       'command for them exists. This tool only reads, apart from setting the clock.'
                  ).pack(fill='x', padx=10, pady=(0, 8))

    # -- background work -----------------------------------------------
    def run_bg(self, work, done, busy_text):
        if self.busy:
            return
        self.busy = True
        self.status.config(text=busy_text)
        self.config(cursor='watch')

        def task():
            try:
                self.results.put((done, work(), None))
            except Exception as exc:  # shown to the user, not swallowed
                self.results.put((done, None, exc))

        threading.Thread(target=task, daemon=True).start()

    def _poll(self):
        try:
            while True:
                done, value, exc = self.results.get_nowait()
                self.busy = False
                self.config(cursor='')
                done(value, exc)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # -- actions -------------------------------------------------------
    def refresh_devices(self):
        try:
            self.devices = himd_dev.find_devices()
        except Exception as exc:
            self.devices = []
            self.status.config(text='USB scan failed: %s' % exc)
        names = ['%s (USB %04X:%04X)' % (MODELS.get(d.idProduct, 'Hi-MD device'), d.idVendor, d.idProduct)
                 for d in self.devices]
        self.device_box['values'] = names
        if names:
            self.device_box.current(0)
            self.load()
        else:
            self.device_var.set('')
            self._clear()
            self.status.config(text='No recorder found. Connect it by USB and press Rescan.')

    def _clear(self):
        for k in self.labels:
            self.labels[k].config(text='-')
        self.disc_title.config(text='-')
        self.tree.delete(*self.tree.get_children())
        self.tracks = []
        self.clock_btn.config(state='disabled')

    def _selected(self):
        i = self.device_box.current()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def load(self):
        usb_dev = self._selected()
        if usb_dev is None:
            return
        self._clear()

        def work():
            dev = himd_dev.Device(usb_dev)
            out = {'inq': dev.inquiry()}
            try:
                out['clock'] = dev.get_time()
            except himd_dev.HiMDError:
                out['clock'] = None
            out['cap'] = dev.capacity()
            if out['cap']:
                try:
                    fs = himd_fs.Fat16(dev)
                    disc = himd_disc.Disc(fs)
                    free = fs.free_clusters() * fs.cluster_bytes
                    groups = disc.groups()
                    tracks = disc.tracks()
                    for t in tracks:
                        t['group'] = next((g['title'] or 'Group %d' % g['index'] for g in groups
                                           if g['first'] <= t['number'] <= g['last']), '')
                    out['disc'] = {'title': disc.disc_title(), 'tracks': tracks, 'free': free,
                                   'total': fs.cluster_count * fs.cluster_bytes}
                except (himd_fs.FatError, himd_dev.HiMDError) as exc:
                    out['disc_error'] = str(exc)
            return out

        self.run_bg(work, lambda v, e: self._loaded(usb_dev, v, e), 'Reading the recorder…')

    def _loaded(self, usb_dev, out, exc):
        if exc:
            hint = ''
            if isinstance(exc, usb.core.USBError):
                hint = ' Close any other program using the recorder, then press Reload.'
            self.status.config(text='Could not read the recorder: %s.%s' % (exc, hint))
            return
        inq = out['inq']
        self.labels['model'].config(text=MODELS.get(usb_dev.idProduct, 'Hi-MD device'))
        self.labels['inquiry'].config(text='%s %s, revision %s' % (inq['vendor'], inq['product'], inq['revision']))
        clock = out['clock']
        if clock is None:
            self.labels['clock'].config(text='could not be read')
        elif clock[0] is None:
            self.labels['clock'].config(text='not set')
        else:
            self.labels['clock'].config(text=clock[0].strftime('%Y-%m-%d %H:%M:%S'))
        self.clock_btn.config(state='normal' if clock is not None else 'disabled')
        cap = out['cap']
        if not cap:
            self.labels['disc'].config(text='no disc inserted')
            self.status.config(text='No disc in the recorder.')
            return
        if 'disc_error' in out:
            self.labels['disc'].config(text='%s, but it could not be read' % fmt_bytes(cap['bytes']))
            self.status.config(text=out['disc_error'])
            return
        d = out['disc']
        used = d['total'] - d['free']
        self.labels['disc'].config(text='%s total, %s used, %s free' % (fmt_bytes(d['total']), fmt_bytes(used), fmt_bytes(d['free'])))
        self.disc_title.config(text='Disc title: %s' % (d['title'] or '(none)'))
        self.tracks = d['tracks']
        for t in self.tracks:
            self.tree.insert('', 'end', values=(t['number'], t['title'], t['artist'], t['group'], t['codec'],
                                                t['kbps'] or '', fmt_len(t['seconds'])))
        total = sum(t['seconds'] for t in self.tracks)
        self.status.config(text='%d tracks, %s of audio.' % (len(self.tracks), fmt_len(total)))

    def set_clock(self):
        usb_dev = self._selected()
        if usb_dev is None:
            return
        now = datetime.datetime.now().replace(microsecond=0)
        if not messagebox.askokcancel(
                'Set the recorder’s clock',
                'Set the recorder’s clock to %s?\n\nThis is the only change this program makes to the recorder.'
                % now.strftime('%Y-%m-%d %H:%M:%S')):
            return

        def work():
            dev = himd_dev.Device(usb_dev)
            dev.set_time(now)
            return dev.get_time()

        def done(value, exc):
            if exc:
                self.status.config(text='Setting the clock failed: %s' % exc)
                return
            when = value[0]
            self.labels['clock'].config(text=when.strftime('%Y-%m-%d %H:%M:%S') if when else 'not set')
            self.status.config(text='Clock set.' if when else 'The recorder accepted the command but still reports no valid time.')

        self.run_bg(work, done, 'Setting the clock…')

    def export_csv(self):
        if not self.tracks:
            messagebox.showinfo('Export', 'There is no track list to export.')
            return
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV file', '*.csv')],
                                            initialfile='hi-md-tracks.csv')
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['#', 'Title', 'Artist', 'Album', 'Group', 'Codec', 'kbps', 'Length'])
            for t in self.tracks:
                w.writerow([t['number'], t['title'], t['artist'], t['album'], t['group'], t['codec'],
                            t['kbps'] or '', fmt_len(t['seconds'])])
        self.status.config(text='Saved %s' % path)


if __name__ == '__main__':
    App().mainloop()
