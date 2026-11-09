"""Read-only FAT16 reader over a himd_dev.Device (2048-byte sectors, READ(10))."""
import struct


class FatError(Exception):
    pass


class Fat16:
    def __init__(self, dev):
        self.dev = dev
        self._cache = {}
        boot = self.sector(0)
        self.bps, self.spc, self.reserved, self.nfats = struct.unpack_from('<HBHB', boot, 11)
        self.root_entries, tot16 = struct.unpack_from('<HH', boot, 17)
        self.fat_sectors = struct.unpack_from('<H', boot, 22)[0]
        tot32 = struct.unpack_from('<I', boot, 32)[0]
        self.total_sectors = tot16 or tot32
        if self.bps == 0 or self.spc == 0 or self.fat_sectors == 0:
            raise FatError('Not a FAT16 volume (is a disc inserted?)')
        self.root_sectors = (self.root_entries * 32 + self.bps - 1) // self.bps
        self.root_start = self.reserved + self.nfats * self.fat_sectors
        self.data_start = self.root_start + self.root_sectors
        self.cluster_bytes = self.spc * self.bps
        self.cluster_count = (self.total_sectors - self.data_start) // self.spc
        if self.cluster_count >= 65525:
            raise FatError('FAT32 volumes are not supported')
        self.fat = self.sectors(self.reserved, self.fat_sectors)

    # -- raw access ----------------------------------------------------
    def sector(self, lba):
        if lba not in self._cache:
            self._cache[lba] = self.dev.read10(lba, 1)
        return self._cache[lba]

    def sectors(self, lba, count, chunk=16):
        out = bytearray()
        done = 0
        while done < count:
            n = min(chunk, count - done)
            out += self.dev.read10(lba + done, n)
            done += n
        return bytes(out)

    # -- FAT -----------------------------------------------------------
    def next_cluster(self, c):
        return struct.unpack_from('<H', self.fat, c * 2)[0]

    def chain(self, first):
        out, c = [], first
        while 2 <= c < 0xFFF0 and len(out) <= self.cluster_count:
            out.append(c)
            c = self.next_cluster(c)
        return out

    def free_clusters(self):
        return sum(1 for c in range(2, self.cluster_count + 2)
                   if struct.unpack_from('<H', self.fat, c * 2)[0] == 0)

    def cluster_data(self, c):
        return self.sectors(self.data_start + (c - 2) * self.spc, self.spc)

    # -- directories ---------------------------------------------------
    @staticmethod
    def _entries(raw):
        lfn = []
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5:
                lfn = []
                continue
            attr = e[11]
            if attr == 0x0F:
                part = e[1:11] + e[14:26] + e[28:32]
                text = part.decode('utf-16-le', 'ignore').split('\x00')[0].split('￿')[0]
                lfn.insert(0, text)
                continue
            if attr & 0x08:
                lfn = []
                continue
            short = e[0:8].decode('latin1').rstrip() + ('.' + e[8:11].decode('latin1').rstrip() if e[8:11].strip() else '')
            name = ''.join(lfn) or short
            lfn = []
            if short in ('.', '..'):
                continue
            first = struct.unpack_from('<H', e, 26)[0]
            size = struct.unpack_from('<I', e, 28)[0]
            yield {'name': name, 'short': short, 'dir': bool(attr & 0x10), 'first': first, 'size': size}

    def listdir(self, path='/'):
        parts = [p for p in path.replace('\\', '/').split('/') if p]
        if not parts:
            raw = self.sectors(self.root_start, self.root_sectors)
            return list(self._entries(raw))
        cur = self.listdir('/')
        for i, p in enumerate(parts):
            hit = next((e for e in cur if e['name'].lower() == p.lower() or e['short'].lower() == p.lower()), None)
            if not hit or not hit['dir']:
                raise FatError('No such folder: ' + path)
            raw = b''.join(self.cluster_data(c) for c in self.chain(hit['first']))
            cur = list(self._entries(raw))
        return cur

    def file_lbas(self, path):
        """LBA of every sector of a file, in file order (used for in-place overwrites)."""
        parent, _, name = path.replace('\\', '/').rstrip('/').rpartition('/')
        hit = next((e for e in self.listdir(parent or '/')
                    if not e['dir'] and (e['name'].lower() == name.lower() or e['short'].lower() == name.lower())), None)
        if not hit:
            raise FatError('No such file: ' + path)
        lbas = []
        for c in self.chain(hit['first']):
            base = self.data_start + (c - 2) * self.spc
            lbas.extend(range(base, base + self.spc))
        need = (hit['size'] + self.bps - 1) // self.bps
        if len(lbas) < need:
            raise FatError('The file %s is shorter on disc than its size says' % path)
        return lbas[:need], hit['size']

    def read_file(self, path):
        parent, _, name = path.replace('\\', '/').rstrip('/').rpartition('/')
        hit = next((e for e in self.listdir(parent or '/')
                    if not e['dir'] and (e['name'].lower() == name.lower() or e['short'].lower() == name.lower())), None)
        if not hit:
            raise FatError('No such file: ' + path)
        data = b''.join(self.cluster_data(c) for c in self.chain(hit['first']))
        return data[:hit['size']]
