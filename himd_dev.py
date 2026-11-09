"""Minimal Hi-MD Walkman access over USB mass storage (bulk-only, SCSI).

Only documented commands are used: INQUIRY, TEST UNIT READY, REQUEST SENSE,
READ FORMAT CAPACITIES, READ CAPACITY, READ(10), and the C2 Get Time / Set Time
sub-commands (as used by Sony's own software and by himd-js).
"""
import datetime
import struct

import libusb_package
import usb.backend.libusb1
import usb.core
import usb.util

SONY = 0x054C
EP_IN, EP_OUT = 0x81, 0x02


class HiMDError(Exception):
    pass


def _backend():
    return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)


def _mass_storage(dev):
    try:
        for cfg in dev:
            for intf in cfg:
                if intf.bInterfaceClass == 8 and intf.bInterfaceSubClass == 5 and intf.bInterfaceProtocol == 0x50:
                    return True
    except usb.core.USBError:
        pass
    return False


def find_devices():
    """Return open-able Hi-MD devices: list of (usb_device, label)."""
    found = []
    for d in usb.core.find(find_all=True, idVendor=SONY, backend=_backend()):
        if not _mass_storage(d):
            continue
        found.append(d)
    return found


# Recorders that speak NetMD (standard MiniDiscs, and Hi-MD units with a standard disc inside), from netmd-js.
# Python never opens these; helper\netmd_helper.js does. (vendor, product): name
NETMD_IDS = {
    (0x04dd, 0x7202): 'Sharp IM-MT899H', (0x04dd, 0x9013): 'Sharp IM-DR400', (0x04dd, 0x9014): 'Sharp IM-DR80',
    (0x054c, 0x0034): 'Sony PCLK-XX', (0x054c, 0x0036): 'Sony NetMD', (0x054c, 0x0075): 'Sony MZ-N1', (0x054c, 0x007c): 'Sony NetMD',
    (0x054c, 0x0080): 'Sony LAM-1', (0x054c, 0x0081): 'Sony MDS-JB980/MDS-NT1/MDS-JE780', (0x054c, 0x0084): 'Sony MZ-N505',
    (0x054c, 0x0085): 'Sony MZ-S1', (0x054c, 0x0086): 'Sony MZ-N707', (0x054c, 0x008e): 'Sony CMT-C7NT',
    (0x054c, 0x0097): 'Sony PCGA-MDN1', (0x054c, 0x00ad): 'Sony CMT-L7HD', (0x054c, 0x00c6): 'Sony MZ-N10',
    (0x054c, 0x00c7): 'Sony MZ-N910', (0x054c, 0x00c8): 'Sony MZ-N710/NF810', (0x054c, 0x00c9): 'Sony MZ-N510/N610',
    (0x054c, 0x00ca): 'Sony MZ-NE410/NF520D', (0x054c, 0x00e7): 'Sony CMT-M333NT/M373NT', (0x054c, 0x00eb): 'Sony MZ-NE810/NE910',
    (0x054c, 0x0101): 'Sony LAM', (0x054c, 0x0113): 'Aiwa AM-NX1', (0x054c, 0x013f): 'Sony MDS-S500', (0x054c, 0x014c): 'Aiwa AM-NX9',
    (0x054c, 0x017e): 'Sony MZ-NH1', (0x054c, 0x0180): 'Sony MZ-NH3D', (0x054c, 0x0182): 'Sony MZ-NH900',
    (0x054c, 0x0184): 'Sony MZ-NH700/NH800', (0x054c, 0x0186): 'Sony MZ-NH600', (0x054c, 0x0187): 'Sony MZ-NH600D',
    (0x054c, 0x0188): 'Sony MZ-N920', (0x054c, 0x018a): 'Sony LAM-3', (0x054c, 0x01e9): 'Sony MZ-DH10P',
    (0x054c, 0x0219): 'Sony MZ-RH10', (0x054c, 0x021b): 'Sony MZ-RH710/MZ-RH910', (0x054c, 0x021d): 'Sony CMT-AH10',
    (0x054c, 0x022c): 'Sony CMT-AH10', (0x054c, 0x023c): 'Sony DS-HMD1', (0x054c, 0x0286): 'Sony MZ-RH1',
    (0x054c, 0x011a): 'Sony CMT-SE7', (0x054c, 0x0148): 'Sony MDS-A1', (0x0b28, 0x1004): 'Kenwood MDX-J9',
    (0x04da, 0x23b3): 'Panasonic SJ-MR250', (0x04da, 0x23b6): 'Panasonic SJ-MR270',
}


def find_netmd_devices():
    """Return the NetMD recorders that are connected (not opened)."""
    return [d for d in usb.core.find(find_all=True, backend=_backend()) if (d.idVendor, d.idProduct) in NETMD_IDS]


class Device:
    def __init__(self, usb_dev):
        self.dev = usb_dev
        self.tag = 0
        self.block_size = 2048
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass
        self.reset()

    # -- transport -----------------------------------------------------
    def reset(self):
        """Bulk-only mass storage reset recovery."""
        try:
            self.dev.ctrl_transfer(0x21, 0xFF, 0, 0, None, 3000)
            self.dev.clear_halt(EP_IN)
            self.dev.clear_halt(EP_OUT)
        except usb.core.USBError:
            pass

    def _read(self, n, timeout):
        return bytes(self.dev.read(EP_IN, n, timeout))

    def scsi(self, cdb, length=0, timeout=5000, data_out=None):
        """Send a CDB. With data_out the data stage goes to the device, otherwise
        up to `length` bytes come back. Returns (data, status)."""
        for attempt in (0, 1):
            self.tag += 1
            cb = bytes(cdb) + bytes(max(0, 16 - len(cdb)))
            if data_out is not None:
                length = len(data_out)
            cbw = struct.pack('<4sIIBBB', b'USBC', self.tag, length,
                              0 if data_out is not None else 0x80, 0, len(cdb)) + cb
            try:
                self.dev.write(EP_OUT, cbw, timeout)
                data = b''
                if data_out is not None:
                    self.dev.write(EP_OUT, data_out, timeout)
                elif length:
                    try:
                        data = self._read(length, timeout)
                    except usb.core.USBTimeoutError:
                        raise
                    except usb.core.USBError:
                        self.dev.clear_halt(EP_IN)
                try:
                    csw = self._read(13, timeout)
                except usb.core.USBTimeoutError:
                    raise
                except usb.core.USBError:
                    self.dev.clear_halt(EP_IN)
                    csw = self._read(13, timeout)
                return data, csw[12]
            except usb.core.USBTimeoutError:
                self.reset()
                if attempt:
                    raise HiMDError('The recorder stopped responding (timeout).')
        raise HiMDError('unreachable')

    def sense(self):
        d, _ = self.scsi([0x03, 0, 0, 0, 18, 0], 18)
        if len(d) >= 14:
            return d[2] & 0xF, d[12], d[13]
        return None

    # -- documented commands -------------------------------------------
    def inquiry(self):
        d, s = self.scsi([0x12, 0, 0, 0, 0x38, 0], 0x38)
        if s or len(d) < 36:
            raise HiMDError('INQUIRY failed')
        return {
            'vendor': d[8:16].decode('ascii', 'replace').strip(),
            'product': d[16:32].decode('ascii', 'replace').strip(),
            'revision': d[32:36].decode('ascii', 'replace').strip(),
            'raw': d,
        }

    def capacity(self):
        d, s = self.scsi([0x25] + [0] * 9, 8)
        if s or len(d) != 8:
            return None
        last, bsize = struct.unpack('>II', d)
        self.block_size = bsize
        return {'blocks': last + 1, 'block_size': bsize, 'bytes': (last + 1) * bsize}

    def read10(self, lba, count=1):
        cdb = [0x28, 0] + list(struct.pack('>I', lba)) + [0] + list(struct.pack('>H', count)) + [0]
        d, s = self.scsi(cdb, count * self.block_size, timeout=10000)
        if s:
            raise HiMDError('READ(10) failed at LBA %d (sense %s)' % (lba, self.sense()))
        return d

    def write10(self, lba, data):
        """Standard WRITE(10), the same command himd-js uses for the disc's FAT volume."""
        if len(data) == 0 or len(data) % self.block_size:
            raise HiMDError('Writes must be whole sectors')
        count = len(data) // self.block_size
        cdb = [0x2A, 0] + list(struct.pack('>I', lba)) + [0] + list(struct.pack('>H', count)) + [0]
        _, s = self.scsi(cdb, timeout=15000, data_out=bytes(data))
        if s:
            raise HiMDError('WRITE(10) failed at LBA %d (sense %s). Is the disc write-protected?'
                            % (lba, self.sense()))

    def wait_ready(self, timeout=120):
        """Poll TEST UNIT READY until the recorder is idle (like himd-js awaitSystemReady)."""
        import time
        t0 = time.time()
        while True:
            _, status = self.scsi([0, 0, 0, 0, 0, 0], 0)
            if status == 0:
                return
            if time.time() - t0 > timeout:
                raise HiMDError('The recorder is still busy after %d s (sense %s). Unplug it and plug it back in.'
                                % (timeout, self.sense()))
            time.sleep(0.5)

    def get_time(self):
        """C2 sub-command 0x50. Returns (datetime or None, flags)."""
        cdb = [0xC2, 0, 0, 0x50, 0, 0, 0, 0, 7, 0, 0, 0]
        d, s = self.scsi(cdb, 7)
        if s or len(d) != 7:
            raise HiMDError('Get Time failed')
        flags, sec, minute, hour, day, month, year = d
        try:
            return datetime.datetime(1900 + year, month, day, hour, minute, sec), flags
        except ValueError:
            return None, flags

    def set_time(self, when):
        """C2 sub-command 0x90, same layout himd-js sends."""
        cdb = [0xC2, 0, 0, 0x90, 0, when.second, when.minute, when.hour,
               when.day, when.month, when.year - 1900, 0, 0, 0, 0, 0]
        _, s = self.scsi(cdb, 0)
        if s:
            raise HiMDError('Set Time was rejected (sense %s)' % (self.sense(),))
