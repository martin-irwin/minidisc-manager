"""Sending a picture to an HP Sprocket (older, Zink 2x3 models) over Bluetooth: OBEX Object Push on RFCOMM channel 4.
Standard library only (Python's Bluetooth sockets on Windows). The printer takes a portrait baseline JPEG, 640 x 960 pixels."""
import socket
import struct
import time

OBEX_CHANNEL = 4
CHUNK = 4096                                   # body bytes per packet: the printer drops data if it is sent faster or in bigger pieces
ERRORS = {0xC0: 'The printer is busy.', 0xC1: 'The printer could not read the picture.', 0xC2: 'There is a paper jam.',
          0xC5: 'The printer is out of paper.', 0xC7: 'The printer battery is too low to print.', 0xC8: 'The printer reported a system error.',
          0xC9: 'The printer cover is open.', 0xCB: 'The printer is too hot; let it cool down.', 0xCC: 'The printer is too cold.',
          0xCD: 'The paper in the printer is the wrong kind.', 0xCF: 'The printer is cooling down; wait a moment.'}


class SprocketError(Exception):
    def __init__(self, message, detail=''):
        super().__init__(message)
        self.detail = detail                     # the technical reason, for the log


def _read_packet(s, timeout=15):
    s.settimeout(timeout)
    head = b''
    while len(head) < 3:
        d = s.recv(3 - len(head))
        if not d:
            raise SprocketError('The printer closed the connection.')
        head += d
    length = struct.unpack('>H', head[1:3])[0]
    body = b''
    while len(body) < length - 3:
        d = s.recv(length - 3 - len(body))
        if not d:
            raise SprocketError('The printer closed the connection.')
        body += d
    return head[0], body


def _expect(code, wanted, what):
    if code in wanted:
        return
    raise SprocketError(ERRORS.get(code, 'The printer did not accept %s (answer 0x%02X).' % (what, code)))


def send_jpeg(mac, jpeg, name='label.jpg', progress=None):
    """Send one JPEG to the printer, which starts printing when it has all of it. Raises SprocketError with a plain message."""
    if jpeg[:2] != b'\xff\xd8':
        raise SprocketError('That is not a JPEG picture.')
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    try:
        last = None
        for attempt in range(2):                 # a printer that has only just woken can miss the first try
            s.settimeout(12)
            try:
                s.connect((mac, OBEX_CHANNEL)); last = None
                break
            except OSError as exc:
                last = exc
                s.close()
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                time.sleep(1.5)
        if last is not None:
            raise SprocketError('The Sprocket is not answering. It switches itself off after a few minutes, so press its power button, '
                                'wait a few seconds, then press Send to Sprocket again. Keep it close to the PC.', str(last))
        s.sendall(bytes.fromhex('80000710' '00FFFF'))                          # OBEX CONNECT
        code, _ = _read_packet(s)
        _expect(code, (0xA0,), 'the connection')
        uname = name.encode('utf-16-be') + b'\x00\x00'
        hdr = (b'\x01' + struct.pack('>H', 3 + len(uname)) + uname +             # Name
               b'\x42' + struct.pack('>H', 3 + 11) + b'image/jpeg\x00' +         # Type
               b'\xC3' + struct.pack('>I', len(jpeg)))                           # Length
        pos, first, total = 0, True, len(jpeg)
        while True:
            piece = jpeg[pos:pos + CHUNK]
            last = pos + len(piece) >= total
            h = hdr if first else b''
            if last:
                body = b'\x49' + struct.pack('>H', 3 + len(piece)) + piece       # End-of-Body
            else:
                body = b'\x48' + struct.pack('>H', 3 + len(piece)) + piece       # Body
            pkt = (b'\x82' if last else b'\x02') + struct.pack('>H', 3 + len(h) + len(body)) + h + body
            s.sendall(pkt)
            started = time.time()
            code, _ = _read_packet(s, 30 if last else 15)
            if last:
                _expect(code, (0xA0,), 'the picture')
                break
            _expect(code, (0x90,), 'the picture')
            pos += len(piece); first = False
            if progress:
                progress(pos, total)
            pause = CHUNK / 12000.0 - (time.time() - started)                    # about 12 KB/s
            if pause > 0:
                time.sleep(pause)
        if progress:
            progress(total, total)
        try:
            s.sendall(b'\x81\x00\x03')                                             # OBEX DISCONNECT
            _read_packet(s, 5)
        except Exception:
            pass
    finally:
        s.close()
