"""The small local web server behind the page's audio player (and, on another address, the Sonos speakers): it serves the track
being played with Range support, and a track that is still being read from the disc is served as it grows."""
import http.server
import os
import re
import time


def media_handler(api):
    """Serves the track being played to the page's <audio> element, with Range support. A file that is
    still being read from the disc is served as it grows: a request past the end waits for the data."""
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _serve_video(self, parts, head):
            """The lyric-video stream made for a Google TV: /<secret>/lv/<id>/index.m3u8 and its seg00000.ts pieces (see lyricvideo.py)."""
            job = getattr(api, '_lv', None)
            name = parts[3]
            if job is None or parts[2] != job['id'] or not re.match(r'^(index\.m3u8|seg\d+\.ts)$', name):
                self.send_error(404)
                return
            path = os.path.join(job['job'].dir, name)
            try:
                with open(path, 'rb') as f:
                    data = f.read()
            except OSError:
                self.send_error(404)
                return
            mime = 'application/x-mpegurl' if name.endswith('.m3u8') else 'video/mp2t'                 # the usual type for an HLS playlist
            m = re.match(r'bytes=(\d*)-(\d*)$', self.headers.get('Range', ''))
            start, end = 0, len(data) - 1
            if m and m.group(1) and not name.endswith('.m3u8'):
                start = int(m.group(1))
                end = min(int(m.group(2)), len(data) - 1) if m.group(2) else len(data) - 1
                if start > end:
                    self.send_response(416)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, len(data)))
            else:
                self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Access-Control-Allow-Origin', '*')            # a Cast receiver fetches from another origin and needs this
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(end - start + 1))
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(data[start:end + 1])
                except OSError:
                    pass

        def _serve(self, head):
            parts = self.path.split('?')[0].strip('/').split('/')
            if len(parts) == 4 and parts[0] == api._token and parts[1] == 'lv':
                return self._serve_video(parts, head)
            st = api._streams.get(parts[1]) if len(parts) == 2 and parts[0] == api._token else None
            if st is None or not st['total']:
                self.send_error(404)
                return
            total = st['total']
            start, end = 0, total - 1
            m = re.match(r'bytes=(\d*)-(\d*)$', self.headers.get('Range', ''))
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), total - 1) if m.group(2) else total - 1
                else:
                    start = max(total - int(m.group(2)), 0)
                if start > end:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % total)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, total))
            else:
                self.send_response(200)
            self.send_header('Content-Type', st['mime'])
            self.send_header('Access-Control-Allow-Origin', '*')            # the page's visualizer reads the audio (Web Audio needs this for a player on another address)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            self.end_headers()
            if head:
                return
            try:
                with open(st['path'], 'rb') as f:
                    pos, quiet_since = start, time.time()
                    while pos <= end:
                        have = total if st['done'] else os.path.getsize(st['path'])
                        if pos >= have:
                            if st['failed'] or time.time() - quiet_since > 40:
                                return                      # the connection closes short; the player reports it
                            time.sleep(0.05)
                            continue
                        f.seek(pos)
                        data = f.read(min(65536, end + 1 - pos, have - pos))
                        if not data:
                            time.sleep(0.05)
                            continue
                        self.wfile.write(data)
                        pos += len(data)
                        quiet_since = time.time()
            except (OSError, ValueError):
                pass                                        # the player went away

        def do_GET(self):
            self._serve(False)

        def do_HEAD(self):
            self._serve(True)

    return Handler
