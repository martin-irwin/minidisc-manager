"""Minimal Sonos control over the local network (UPnP). No third-party packages.

Discovery asks for "ZonePlayer" devices (SSDP). The room layout (which speakers are one room: stereo pairs, home-theatre sets,
groups) comes from any one speaker's ZoneGroupTopology service. Playing is the standard UPnP AVTransport service on port 1400:
the speaker is given a web address and fetches the audio itself.
"""
import html
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR = ('239.255.255.250', 1900)
AVT = ('/MediaRenderer/AVTransport/Control', 'urn:schemas-upnp-org:service:AVTransport:1')
GRC = ('/MediaRenderer/GroupRenderingControl/Control', 'urn:schemas-upnp-org:service:GroupRenderingControl:1')
ZGT = ('/ZoneGroupTopology/Control', 'urn:schemas-upnp-org:service:ZoneGroupTopology:1')


class SonosError(Exception):
    pass


def _local_addresses():
    """This PC's IPv4 addresses (one per network adapter) to search from."""
    found = set()
    try:
        found |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith(('127.', '169.254.')))


def local_ip_towards(target_ip):
    """The address of this PC's adapter that is on the same network as `target_ip` (the one the speaker can reach)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_ip, 1400))
        return s.getsockname()[0]
    finally:
        s.close()


def _search_from(ip, wait, found, lock, stop):
    """Asks the network for Sonos units from one adapter. Stops early once answers have stopped coming in."""
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 1\r\n'
           'ST: urn:schemas-upnp-org:device:ZonePlayer:1\r\n\r\n').encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
        sock.bind((ip, 0))
        sock.settimeout(0.15)
        start = time.time()
        sent_second = False
        last_answer = None
        sock.sendto(msg, SSDP_ADDR)
        while time.time() - start < wait and not stop.is_set():
            if not sent_second and time.time() - start > 0.5:          # one repeat: multicast replies are sometimes lost
                sock.sendto(msg, SSDP_ADDR)
                sent_second = True
            if last_answer is not None and time.time() - last_answer > 1.1 and sent_second:
                stop.set()                                             # the speakers have all had their say: every adapter can stop
                break
            try:
                data, addr = sock.recvfrom(65507)
            except socket.timeout:
                continue
            loc = re.search(rb'(?i)location:\s*(\S+)', data)
            if loc:
                with lock:
                    found[addr[0]] = loc.group(1).decode()
                last_answer = time.time()
    except OSError:
        pass                                                           # an adapter that cannot multicast (some VPNs): skip it
    finally:
        sock.close()


def discover(wait=3.0):
    """Returns {ip: description-url} for every Sonos unit that answers. All adapters are searched at the same time."""
    found, lock, threads, stop = {}, threading.Lock(), [], threading.Event()
    for ip in _local_addresses():
        th = threading.Thread(target=_search_from, args=(ip, wait, found, lock, stop), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(wait + 1)
    return found

def _soap(ip, service, action, args='', timeout=6):
    path, urn = service
    body = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>'
            % (action, urn, args, action)).encode('utf-8')
    req = urllib.request.Request('http://%s:1400%s' % (ip, path), data=body, headers={
        'Content-Type': 'text/xml; charset="utf-8"', 'SOAPACTION': '"%s#%s"' % (urn, action)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        text = e.read().decode('utf-8', 'replace')
        code = re.search(r'<errorCode>(\d+)</errorCode>', text)
        raise SonosError('The speaker refused %s (error %s).' % (action, code.group(1) if code else e.code))
    except (urllib.error.URLError, OSError) as e:
        raise SonosError('Could not reach the speaker at %s (%s).' % (ip, getattr(e, 'reason', e)))


def _tag(text, name):
    m = re.search(r'<%s>([^<]*)</%s>' % (name, name), text)
    return html.unescape(m.group(1)) if m else ''


def rooms(known=None, wait=3.0):
    """The rooms as Sonos shows them: [{'name', 'ip' (the speaker to talk to), 'members'}]. Bonded speakers count once."""
    found = known or discover(wait)
    if not found:
        return []
    state = None
    for ip in found:                                      # any speaker knows the whole layout
        try:
            state = _tag(_soap(ip, ZGT, 'GetZoneGroupState', timeout=2.5), 'ZoneGroupState')
            if state:
                break
        except SonosError:
            continue
    if not state:
        return []
    out = []
    root = ET.fromstring(state)
    for group in root.iter('ZoneGroup'):
        members = list(group.iter('ZoneGroupMember'))
        coord = next((m for m in members if m.get('UUID') == group.get('Coordinator')), None)
        if coord is None:
            continue
        host = re.search(r'//([\d.]+):', coord.get('Location', ''))
        names = []
        for m in members:
            if m.get('Invisible') == '1' or m.get('IsZoneBridge') == '1':
                continue
            if m.get('ZoneName') not in names:
                names.append(m.get('ZoneName'))
        if host and names:
            out.append({'name': ' + '.join(names), 'ip': host.group(1), 'members': len(members)})
    return sorted(out, key=lambda r: r['name'].lower())


def _didl(title, url, mime):
    t = html.escape(title or 'Track', quote=False)
    return ('<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
            'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
            '<item id="-1" parentID="-1" restricted="true"><dc:title>%s</dc:title><upnp:class>object.item.audioItem.musicTrack</upnp:class>'
            '<res protocolInfo="http-get:*:%s:*">%s</res></item></DIDL-Lite>' % (t, mime, html.escape(url, quote=False)))


def _seconds(text):
    m = re.match(r'(\d+):(\d+):(\d+)', text or '')
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else 0


class Speaker:
    """One room, addressed by its coordinator speaker."""

    def __init__(self, ip):
        self.ip = ip

    def play_url(self, url, title, mime):
        _soap(self.ip, AVT, 'SetAVTransportURI', '<InstanceID>0</InstanceID><CurrentURI>%s</CurrentURI><CurrentURIMetaData>%s</CurrentURIMetaData>'
              % (html.escape(url, quote=False), html.escape(_didl(title, url, mime), quote=False)))
        _soap(self.ip, AVT, 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>')

    def play(self):
        _soap(self.ip, AVT, 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>')

    def pause(self):
        _soap(self.ip, AVT, 'Pause', '<InstanceID>0</InstanceID>')

    def stop(self):
        _soap(self.ip, AVT, 'Stop', '<InstanceID>0</InstanceID>')

    def seek(self, seconds):
        s = max(0, int(seconds))
        _soap(self.ip, AVT, 'Seek', '<InstanceID>0</InstanceID><Unit>REL_TIME</Unit><Target>%d:%02d:%02d</Target>' % (s // 3600, s % 3600 // 60, s % 60))

    def status(self):
        """{'state': playing|paused|ready, 'seconds': position, 'duration': length} - 'ready' means stopped."""
        info = _soap(self.ip, AVT, 'GetTransportInfo', '<InstanceID>0</InstanceID>')
        pos = _soap(self.ip, AVT, 'GetPositionInfo', '<InstanceID>0</InstanceID>')
        raw = _tag(info, 'CurrentTransportState')
        state = {'PLAYING': 'playing', 'TRANSITIONING': 'playing', 'PAUSED_PLAYBACK': 'paused'}.get(raw, 'ready')
        return {'state': state, 'seconds': _seconds(_tag(pos, 'RelTime')), 'duration': _seconds(_tag(pos, 'TrackDuration')), 'raw': raw}

    def current_uri(self):
        """The address of the track the room is on now (empty if none)."""
        return _tag(_soap(self.ip, AVT, 'GetPositionInfo', '<InstanceID>0</InstanceID>', timeout=3), 'TrackURI')

    def volume(self):
        return int(_tag(_soap(self.ip, GRC, 'GetGroupVolume', '<InstanceID>0</InstanceID>'), 'CurrentVolume') or 0)

    def set_volume(self, value):
        _soap(self.ip, GRC, 'SetGroupVolume', '<InstanceID>0</InstanceID><DesiredVolume>%d</DesiredVolume>' % max(0, min(100, int(value))))
