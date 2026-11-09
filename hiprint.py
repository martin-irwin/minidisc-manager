"""Polaroid Hi-Print 2x3 over Bluetooth (Prinics 'PPVP' protocol on a Serial Port Profile link). Standard library only.

Worked out 2026-11-01 by reading the Polaroid Hi-Print Android app (com.polaroid.printer, package com.prinics.ppvp). NOT yet tested on a print.

Message (both directions):  [cmd, p1, p2, 0, length as 4 bytes big-endian] + data
Commands used here:  1 ACK, 2 HELLO, 3 REQUEST_STATUS, 4 STATUS, 5 NEW_PRINT, 7 READY_TO_SEND, 8 REQUEST_PARTIAL_DATA, 9 SEND_PARTIAL_DATA,
                     10 CANCEL_PRINT, 100 CONNECT, 101 DISCONNECT, 102 TIMEOUT.
Flow (from the app): printer sends 100 -> host answers 100 (p1=1). Printer sends HELLO 2 (p1/p2 = firmware, p3 = printer type, data[1..2] = battery);
host answers 2 (p1=1, p2=37). Printer sends STATUS 4 with p1=1 when ready (battery in p2/p3): host sends NEW_PRINT 5 (p1 = copies,
data = 12 bytes: picture size as 4 bytes big-endian, then zeros). Printer acknowledges (1, p1=5): host sends 7. Printer then asks for the picture in
slices with 8 (data = offset, length as 4 bytes big-endian each): host answers each with 9 (p1/p2 copied from the request) carrying that slice.
STATUS 4 with p1=3 is printing progress. Over Bluetooth the app waits 0.5 s after every 100 KB sent.
The picture is a plain JPEG, 640 wide x 1024 tall for the 2x3 (printer types 52 and 102), padded to at least 33792 bytes.
Anything the printer sends that is not understood is kept in the log list so the protocol can be completed later."""
import socket
import struct
import time

IMAGE_SIZE = (640, 1024)                       # width, height of the 2x3 picture (from the app's PrinterType / native size table)
MIN_FILE = 33792                               # the app pads smaller files with zeros to this size
RFCOMM_CHANNEL = 1                             # Windows maps the one serial service onto several channel numbers
TWO_BY_THREE_TYPES = (52, 102)
CMD = dict(ACK=1, HELLO=2, REQ_STATUS=3, STATUS=4, NEW_PRINT=5, READY=7, REQ_DATA=8, SEND_DATA=9, CANCEL=10, CONNECT=100, DISCONNECT=101, TIMEOUT=102)
NAMES = {v: k for k, v in CMD.items()}


class HiPrintError(Exception):
    def __init__(self, message, detail=''):
        super().__init__(message)
        self.detail = detail                    # the technical reason, for the log


def frame(cmd, p1=0, p2=0, data=b''):
    return bytes([cmd & 255, p1 & 255, p2 & 255, 0]) + struct.pack('>I', len(data)) + data


def _read_exact(s, n, deadline):
    buf = b''
    while len(buf) < n:
        left = deadline - time.time()
        if left <= 0:
            raise socket.timeout()
        s.settimeout(left)
        d = s.recv(n - len(buf))
        if not d:
            raise HiPrintError('The Hi-Print closed the connection.')
        buf += d
    return buf


def read_message(s, timeout=5):
    """One message: (cmd, p1, p2, p3, data). Raises socket.timeout if nothing arrives in time."""
    deadline = time.time() + timeout
    head = _read_exact(s, 8, deadline)
    n = struct.unpack('>I', head[4:8])[0]
    if n > 1 << 20:
        raise HiPrintError('The Hi-Print sent something unexpected.', head.hex())
    data = _read_exact(s, n, time.time() + 10) if n else b''
    return head[0], head[1], head[2], head[3], data


def _open(mac, tries=2):
    last = None
    for _ in range(tries):
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.settimeout(12)
        try:
            s.connect((mac, RFCOMM_CHANNEL))
            return s
        except OSError as exc:
            last = exc
            s.close()
            time.sleep(1.5)
    raise HiPrintError('The Hi-Print is not answering. Switch it on, close the Polaroid app on your phone (it only talks to one device), '
                       'keep it close to the PC, then try again.', str(last))


def session(mac, jpeg=None, copies=1, progress=None, log=None, max_seconds=180):
    """Talks to the printer the way the Polaroid app does.
    jpeg=None: READ ONLY. Answers the greetings, reads type / firmware / battery / status, and never starts a print.
    jpeg=bytes: also starts a print once the printer reports it is ready. Returns a dict (printer_type, firmware, battery, status, printed, trace)."""
    info = {'printer_type': None, 'firmware': None, 'battery': None, 'status': None, 'printed': False, 'trace': []}
    note = lambda t: (info['trace'].append(t), log(t) if log else None)
    if jpeg is not None:
        if jpeg[:2] != b'\xff\xd8':
            raise HiPrintError('That is not a JPEG picture.')
        if len(jpeg) < MIN_FILE:
            jpeg = jpeg + b'\x00' * (MIN_FILE - len(jpeg))
    s = _open(mac)
    sent_new = False
    served = 0
    since_pause = 0
    end = time.time() + max_seconds
    quiet = 0
    try:
        while time.time() < end:
            try:
                cmd, p1, p2, p3, data = read_message(s, 6)
            except socket.timeout:
                quiet += 1
                if jpeg is None and quiet >= 2:
                    break                                       # read-only: nothing more is coming
                if quiet >= 6:
                    raise HiPrintError('The Hi-Print stopped answering.')
                try:
                    s.sendall(frame(CMD['REQ_STATUS']))
                except OSError:
                    pass
                continue
            quiet = 0
            note('%s p=%d,%d,%d data=%s' % (NAMES.get(cmd, cmd), p1, p2, p3, data[:24].hex()))
            if cmd == CMD['CONNECT']:
                s.sendall(frame(CMD['CONNECT'], 1))
            elif cmd == CMD['HELLO']:
                info['firmware'] = '%d.%d' % (p1, p2)
                info['printer_type'] = p3
                if len(data) >= 3:
                    info['battery'] = (data[1] << 8) + data[2]
                s.sendall(frame(CMD['HELLO'], 1, 37))
            elif cmd == CMD['STATUS']:
                info['status'] = (p1, p2, p3)
                if p1 == 1:
                    info['battery'] = (p2 << 8) + p3 if p2 else info['battery']
                    if jpeg is not None and not sent_new:
                        if info['printer_type'] not in TWO_BY_THREE_TYPES:
                            raise HiPrintError('This printer reports type %s, not a 2x3 Hi-Print; nothing was sent.' % info['printer_type'])
                        s.sendall(frame(CMD['NEW_PRINT'], copies, 0, struct.pack('>I', len(jpeg)) + b'\x00' * 8))
                        sent_new = True
                        note('NEW_PRINT sent (%d bytes)' % len(jpeg))
                elif p1 == 3 and not info['printed']:
                    info['printed'] = True
            elif cmd == CMD['ACK']:
                if p1 == 5:
                    s.sendall(frame(CMD['READY'], p3))
            elif cmd == CMD['REQ_DATA'] and jpeg is not None and len(data) >= 8:
                off, ln = struct.unpack('>II', data[:8])
                piece = jpeg[off:off + ln]
                s.sendall(frame(CMD['SEND_DATA'], p1, p2, piece))
                served = max(served, off + len(piece))
                since_pause += len(piece)
                if since_pause > 102400:
                    time.sleep(0.5)
                    since_pause = 0
                if progress:
                    progress(served, len(jpeg))
            elif cmd == CMD['DISCONNECT']:
                break
            elif cmd == CMD['TIMEOUT']:
                raise HiPrintError('The Hi-Print timed out waiting for the picture.')
        return info
    finally:
        try:
            s.sendall(frame(CMD['DISCONNECT']))
        except OSError:
            pass
        s.close()


def probe(mac, log=None):
    """Read only (nothing prints): the printer's type, firmware, battery and status."""
    return session(mac, None, log=log)


def send_jpeg(mac, jpeg, copies=1, progress=None, log=None):
    """Prints one picture (640 x 1024 JPEG). Uses one sheet of film."""
    return session(mac, jpeg, copies, progress, log)


def _long(b, i):
    return struct.unpack('>I', b[i:i + 4])[0]


def stats(mac, log=None, wait=15):
    """Read only (nothing prints): asks for the printer's statistics block (GET_STATS 112) and decodes it as the Polaroid app does.
    Returns dict with pages_remaining (sheets left in the cartridge), pages_printed, serial, sku, battery_charges, error counts, plus the type/firmware."""
    s = _open(mac)
    out = {'printer_type': None, 'firmware': None}
    asked = False
    end = time.time() + wait
    try:
        while time.time() < end:
            try:
                cmd, p1, p2, p3, data = read_message(s, 4)
            except socket.timeout:
                if asked:
                    continue
                cmd = None
            if log and cmd is not None:
                log('%s p=%d,%d,%d len=%d' % (NAMES.get(cmd, cmd), p1, p2, p3, len(data)))
            if cmd == CMD['CONNECT']:
                s.sendall(frame(CMD['CONNECT'], 1))
            elif cmd == CMD['HELLO']:
                out['firmware'] = '%d.%d' % (p1, p2)
                out['printer_type'] = p3
                s.sendall(frame(CMD['HELLO'], 1, 37))
            elif cmd == CMD['STATUS'] and p1 == 1 and not asked:
                s.sendall(frame(112))                         # GET_STATS
                asked = True
            elif cmd == 112 and len(data) >= 117:
                ascii_ = lambda a: data[a:a + 32].split(b'\x00')[0].decode('ascii', 'replace')
                out.update(pages_printed=_long(data, 9), pages_remaining=_long(data, 13), battery_charges=_long(data, 17),
                           out_of_ribbon_errors=_long(data, 25), pickup_errors=_long(data, 29), jam_errors=_long(data, 33),
                           serial=ascii_(53), sku=ascii_(85), raw=data.hex())
                return out
        raise HiPrintError('The Hi-Print did not send its statistics.')
    finally:
        try:
            s.sendall(frame(CMD['DISCONNECT']))
        except OSError:
            pass
        s.close()