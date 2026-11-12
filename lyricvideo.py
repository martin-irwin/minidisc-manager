"""A lyric video for a Google TV: cover picture on the left, title / artist and the timed lyrics on the right, with the track's audio
underneath. Google's built-in TV player can only show a title and a picture, so the app draws the screen itself with the bundled ffmpeg and
gives the TV an HLS stream (a playlist of short 2 s pieces) that grows while it is being made. The TV starts after the first few pieces,
so the wait is a few seconds, not the whole track. The lyrics are burned in from a generated ASS subtitle file."""
import os
import re
import shutil
import subprocess
import threading
import time

try:
    import vizrender
except ImportError:                                         # a copy without the new module: ffmpeg's own drawing is used
    class vizrender:                                        # noqa: N801
        OK = False

W, H = 1280, 720
FPS = 25                                                # a very low frame rate (5) made a Google TV show the picture only briefly
FONT = 'Segoe UI'                                       # ships with Windows (C:\Windows\Fonts\segoeui.ttf)
FONTS_DIR = 'C\\:/Windows/Fonts'                        # as an ffmpeg filter option: the drive colon is escaped
BG = '0x12161c'
TOP = 54                                                # top of the cover / visualizer: level with the top of the heading's letters
DIM, BRIGHT, ACCENT = '&H8F8F8F&', '&HFFFFFF&', '&H3CB4FF&'          # ASS colours are BGR
LYRIC = '&HFFD9A6&'                                                  # the lyric being sung: light blue, apart from the white track title


def _ts(sec):
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    return '%d:%02d:%02d.%02d' % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def _esc(text):
    return re.sub(r'\s+', ' ', text.replace('\\', '/').replace('{', '(').replace('}', ')')).strip()


def make_ass(title, artist, lines, offset, duration, has_cover, caption='', album='', compact=False):
    """ASS subtitle text. lines: [(seconds, text)] (timed lyrics) or []. offset: the lyric timing correction kept by the app."""
    x0 = 520 if has_cover else 110
    head = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: %d' % W, 'PlayResY: %d' % H, 'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
            'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
            'Style: Default,%s,40,%s,%s,&H000000&,&H000000&,0,0,0,0,100,100,0,0,1,0,0,7,%d,60,0,1' % (FONT, BRIGHT, BRIGHT, x0),
            '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    end_all = _ts(duration + 30)
    # Heading, top down, each in its own look so they read apart: the ARTIST small, amber, capitals, spaced out; the TRACK TITLE big, bold, white;
    # the album dim grey and light; a thin rule; then the lyrics in light blue (the line being sung bold). Missing ones are skipped and the rest move up.
    ev, y = [], 44                                       # the artist's capitals start level with the top of the cover
    for text, size, style, gap in ((artist.upper() if artist else '', 32, '\\b1\\fsp4\\c' + ACCENT, 8), (title or 'Track', 58, '\\b1\\fsp0\\c' + BRIGHT, 4),
                                   (album, 32, '\\b0\\fsp1\\c' + DIM, 0)):
        if text:
            ev.append('Dialogue: 0,%s,%s,Default,,0,0,0,,{\\an7\\pos(%d,%d)\\fs%d%s}%s' % (_ts(0), end_all, x0, y, size, style, _esc(text)))
            y += int(size * 1.25) + gap
    ev.append('Dialogue: 0,%s,%s,Default,,0,0,0,,{\\an7\\pos(%d,%d)\\p1\\bord0\\shad0\\c&H5A5A5A&}m 0 0 l 700 0 l 700 2 l 0 2{\\p0}' % (_ts(0), end_all, x0, y + 16))
    ly = y + 38                                          # where the lyrics start
    if caption:                                          # the connected recorder, small and dim in the top right corner of the screen
        ev.append('Dialogue: 0,%s,%s,Default,,0,0,0,,{\\an9\\pos(%d,8)\\fs26\\c%s}%s' % (_ts(0), end_all, W - 60, DIM, _esc(caption)))
    texts = [_esc(t) or '\u266a' for _, t in lines]
    for i, (t, _) in enumerate(lines):
        start = t + offset
        end = (lines[i + 1][0] + offset) if i + 1 < len(lines) else max(start + 8, duration)
        if end <= start:
            continue
        block = []
        if i > 0:
            block.append('{\\fs34\\b0\\c%s}%s' % (DIM, texts[i - 1]))
        block.append('{\\fs50\\b1\\c%s}%s' % (LYRIC, texts[i]))
        for j in range(i + 1, min(i + (3 if compact else 4), len(lines))):             # compact: one line fewer, the deck panel sits below
            block.append('{\\fs34\\b0\\c%s}%s' % (DIM, texts[j]))
        ev.append('Dialogue: 1,%s,%s,Default,,0,0,0,,{\\an7\\pos(%d,%d)}%s' % (_ts(start), _ts(end), x0, ly, '\\N\\N'.join(block)))
    if lines and lines[0][0] + offset > 1:               # before the first line: show what is coming
        pre = ['{\\fs34\\b0\\c%s}%s' % (DIM, texts[j]) for j in range(min(2 if compact else 3, len(lines)))]
        ev.append('Dialogue: 1,%s,%s,Default,,0,0,0,,{\\an7\\pos(%d,%d)}%s' % (_ts(0), _ts(lines[0][0] + offset), x0, ly, '\\N\\N'.join(pre)))
    return '\n'.join(head + ev) + '\n'


VIZ_COLOURS = {'accent': ('0x7aa2ff', '0x7aa2ff'), 'oled': ('0x4aa8ff', '0x4aa8ff'), 'white': ('white', 'white'), 'fire': ('0xff7a1a', '0xffd23c'),
               'ice': ('0x7fe0ff', '0xb9f0ff'), 'classic': ('0x3cdc5a', '0xe6e63c'), 'rainbow': ('0xff5a5a', '0x5ad2ff')}


def viz_filter(viz, w, h, fps=FPS):
    """The ffmpeg filter chain (from the audio) drawing the visualizer the user picked in the app, as close as ffmpeg can get to it, w x h with
    a transparent background; None for 'off' or no choice. viz: {'style', 'color', 'gain'} as kept by the page."""
    if not viz or viz.get('style') in (None, '', 'off'):
        return None
    style, gain = str(viz.get('style')), min(8.0, max(0.2, float(viz.get('gain') or 1)))
    c1, c2 = VIZ_COLOURS.get(viz.get('color'), VIZ_COLOURS['accent'])
    size = '%dx%d' % (w, h)
    if style in ('rh1std', 'rh1circle'):
        return _rh1_graph(style == 'rh1circle', c1, gain, w, h, fps)
    if style == 'bars':
        core = 'showfreqs=s=%s:mode=bar:cmode=combined:fscale=log:ascale=sqrt:win_size=2048:rate=%d:colors=%s|%s' % (size, fps, c1, c2)
    elif style == 'mirror':
        core = 'showfreqs=s=%s:mode=line:cmode=combined:fscale=log:ascale=sqrt:win_size=2048:rate=%d:colors=%s|%s' % (size, fps, c1, c2)
    elif style == 'scope':
        core = 'showwaves=s=%s:mode=cline:split_channels=1:rate=%d:colors=%s|%s' % (size, fps, c1, c2)
    elif style == 'radial':
        s = min(w, h)
        core = 'avectorscope=s=%dx%d:mode=lissajous_xy:rate=%d:zoom=1.5:draw=line:rc=%d:gc=%d:bc=%d' % (s, s, fps, *_rgb(c1)) + ',pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black' % (w, h)
    elif style == 'fall':
        core = 'showspectrum=s=%s:slide=scroll:mode=combined:color=intensity:scale=log:fps=%d' % (size, fps)
    else:                                                                # all the VU meters and the MZ-RH1 level meter: ffmpeg's level bars
        # The bars take the chosen colour (ffmpeg's own green-to-red only for Rainbow / Green-red); the MZ-RH1 level meter is cut into 22 segments.
        cexpr = ''
        if viz.get('color') not in ('rainbow', 'classic'):
            r, g_, b = _rgb(c1)
            cexpr = ':c=0x%02x%02x%02x%02x' % (255, b, g_, r)           # showvolume reads the colour as AABBGGRR
        core = ('compand=attacks=0.02:decays=0.2:points=%s,showvolume=r=%d:b=%d:w=%d:h=%d:f=0.92:t=0:v=0:o=h:p=0.25:m=r%s'
                % (_METER_CURVE, fps, 0 if style == 'rh1meter' else 4, w, max(10, min(40, h // 2 - 6)), cexpr))
        if style == 'rh1meter':
            m = 'gt(mod(X,%.3f),%.3f)' % (w / 22.0, w / 22.0 * 0.14)       # the gaps between segments are black, which the colour key then drops
            core += ",format=rgb24,geq=r='r(X,Y)*%s':g='g(X,Y)*%s':b='b(X,Y)*%s'" % (m, m, m)
        core += ',pad=%d:%d:0:(oh-ih)/2:color=black' % (w, h)
    return '[0:a]volume=%.2f,%s,scale=%d:%d,format=rgba,colorkey=black:0.12:0.1[vz]' % (gain, core, w, h)


RH1_HZ = (100, 250, 630, 1600, 4000, 10000)                             # the six analyzer bands of the MZ-RH1 (the same as the window's)
# The window reads each band on a -85 .. -12 dB scale; this maps a band's level the same way onto a straight 0..1 amplitude so a level bar can read it.
# Real music measured per band (one octave): about -24 .. -37 dB RMS with peaks near -8 .. -14, so the scale runs -62 dB (nothing) .. -6 dB (full) on the
# smoothed level, which keeps ordinary music in the middle of the six steps instead of pegged at the top (a first scale to -16 dB still pegged).
# (A wide scale of 56 dB squeezed the ordinary +-6 dB movement of music into one step, so it looked frozen: the scale is now 33 dB wide.)
_RH1_CURVE = '-80/-900|-45/-900|-40/-16.4|-35/-10.4|-30/-6.9|-25/-4.3|-20/-2.4|-15/-0.8|-12/0|0/0'
_METER_CURVE = '-70/-900|-40/-900|-35/-16.7|-30/-10.6|-24/-6.5|-18/-3.7|-12/-1.7|-6/0|0/0'     # level meters: -40 dB (nothing) .. -6 dB RMS (full)


def _rh1_graph(circle, colour, gain, w, h, fps):
    """The MZ-RH1 spectrum as the window draws it: six bands for the left channel, a gap, six for the right, in the recorder's six steps (bars), or
    as twelve dots that grow with the band (circle). Each band is filtered out of the audio, its level read by a level bar, averaged to one number
    and turned into a bar / dot by a small expression."""
    tw, gw = 30, 40
    th = min(h, 100 if circle else 150)
    cr, cg, cb = [v / 255.0 for v in _rgb(colour)]
    steps = 5 if circle else 6
    if circle:
        r = min(tw * 0.96, th * 0.8) / 2.0
        expr = "255*lt(hypot(X-W/2,Y-H/2),%.2f*(0.2+0.8*floor(lum(0,0)/255*%d+0.5)/%d))" % (r, steps, steps)
    else:
        expr = "255*gt(floor(lum(0,0)/255*6+0.5),0)*gte(Y,H*(1-floor(lum(0,0)/255*6+0.5)/6))*gt(X,0)*lt(X,W-1)"
    parts = ['[0:a]aformat=channel_layouts=stereo,channelsplit=channel_layout=stereo[L][R]']
    tiles = []
    for ch, name in (('L', 'l'), ('R', 'r')):
        parts.append('[%s]asplit=6%s' % (ch, ''.join('[%s%d]' % (name, i) for i in range(6))))
        for i, hz in enumerate(RH1_HZ):
            parts.append("[%s%d]volume=%.3f,bandpass=f=%d:width_type=o:w=1,compand=attacks=0.02:decays=0.15:points=%s,"
                         "showvolume=r=%d:b=0:w=200:h=20:t=0:v=0:f=0.9:m=r:c=0xffffffff,format=gray,scale=1:1:flags=area,scale=%d:%d:flags=neighbor,"
                         "geq=lum='%s'[t%s%d]" % (name, i, 0.28 * gain * (1 + 0.5 * i / 5.0), hz, _RH1_CURVE, fps, tw, th, expr, name, i))
            tiles.append('[t%s%d]' % (name, i))
    parts.append('color=c=black:s=%dx%d:r=%d[gap]' % (gw, th, fps))
    row = ''.join(tiles[:6]) + '[gap]' + ''.join(tiles[6:])
    parts.append('%shstack=inputs=13,format=rgb24,colorchannelmixer=rr=%.3f:gg=%.3f:bb=%.3f,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,'
                 'format=rgba,colorkey=black:0.05:0.05[vz]' % (row, cr, cg, cb, w, h))
    return ';'.join(parts)


def _rgb(c):
    named = {'white': 0xffffff}
    n = named.get(c) if c in named else int(c, 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


class Job:
    """One running ffmpeg making the stream for one track into `out_dir` (index.m3u8 + seg00000.ts ...)."""

    def __init__(self, ffmpeg, audio_src, out_dir, title, artist, lines, offset, duration, cover_bytes=None, log=None, growing=False, caption='', album='', viz=None, start=0.0, deck=None):
        """deck: {'pos', 'count', 'length'} to draw the deck's track number / time display (see vizrender.DeckPainter), or None.
        audio_src: the audio FILE (reading it from the app's own web address made ffmpeg stall). growing: the file is still being
        written from the disc, so ffmpeg keeps reading at its end instead of stopping."""
        self.dir, self.proc, self.error = out_dir, None, ''
        if start > 0:                                       # a remake from the middle of the track: the stream starts there, lyrics and length shift to match
            offset, duration = offset - start, max(0.0, duration - start) if duration else duration
        shutil.rmtree(out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        # The visualizer sits under the cover (or where the cover would be, with none); lyrics move right whenever either is shown.
        # The display is drawn in Python (vizrender.py: every style of the window); ffmpeg's own filters (viz_filter) are the fallback without numpy / Pillow.
        # Styles that need height (dials, columns, circle) get a bigger area under a smaller cover.
        on = bool(viz) and viz.get('style') not in (None, '', 'off')
        tall = on and viz.get('style') in ('radial', 'led', 'needle', 'vcream', 'vamber', 'rcream', 'ramber', 'rh1std')
        py_deck = bool(deck) and vizrender.OK                # the deck's track number / time display, drawn in Python at the bottom right
        py_viz = on and vizrender.OK
        piped = py_viz or py_deck                           # either one comes through stdin as one raw picture
        cov = 400
        # The cover's top is level with the top of the heading on the right (TOP); the visualizer sits under it at the bottom and the deck panel
        # on the right has the same top and height, so the two line up.
        vgeom = ((60, 490, 400, 190) if tall else (60, 584, 400, 96)) if cover_bytes else (60, TOP, 400, 400)
        vf = None if py_viz else viz_filter(viz, vgeom[2], vgeom[3])
        # The one picture is the box around the parts shown: x0, y0, width, height.
        dh = vgeom[3] if (py_viz and cover_bytes) else 96
        dgeom = (520, 680 - dh if not (py_viz and cover_bytes) else vgeom[1], vizrender.DECK_W, dh) if py_deck else None
        parts = ([vgeom] if py_viz else []) + ([dgeom] if py_deck else [])
        box = None
        if parts:
            bx0, by0 = min(p[0] for p in parts), min(p[1] for p in parts)
            box = (bx0, by0, max(p[0] + p[2] for p in parts) - bx0, max(p[1] + p[3] for p in parts) - by0)
        self.feeder = None
        with open(os.path.join(out_dir, 'lyrics.ass'), 'w', encoding='utf-8-sig') as f:
            f.write(make_ass(title, artist, lines, offset, duration, bool(cover_bytes) or bool(vf) or py_viz, caption, album, compact=py_deck))
        # A file still being read from the disc: the end of the track is its known length (-t below), not a pause in the data (a read from the recorder
        # can stall for ten seconds or more and then carry on; treating that as the end stopped the TV halfway). The long time-out is only the safety net
        # for a read that has really died; with no known length the old 10 s rule stays.
        known = growing and duration and duration > 5
        seek = ['-ss', '%.2f' % start] if start > 0 else []
        src = ['-follow', '1', '-rw_timeout', '120000000' if known else '10000000'] + seek + ['-i', 'file:' + audio_src] if growing else seek + ['-i', audio_src]
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y'] + src + ['-f', 'lavfi', '-i', 'color=c=%s:s=%dx%d:r=%d' % (BG, W, H, FPS)]
        sub = "subtitles=lyrics.ass:fontsdir='%s'" % FONTS_DIR
        if cover_bytes:
            with open(os.path.join(out_dir, 'cover.img'), 'wb') as f:
                f.write(cover_bytes)
            cmd += ['-loop', '1', '-framerate', str(FPS), '-i', 'cover.img']
            graph = '[2:v]scale=%d:%d:force_original_aspect_ratio=decrease[c];[1:v][c]overlay=%d:%d:shortest=1[b]' % (cov, cov, 60, TOP)
        else:
            graph = '[1:v]null[b]'
        if piped:                                           # the pictures come through stdin as raw RGB frames, made from a second decoding of the same audio
            vi = 3 if cover_bytes else 2
            cmd += ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (box[2], box[3]), '-framerate', str(vizrender.FPS), '-i', 'pipe:0']
            graph += ';[b][%d:v]overlay=%d:%d:shortest=1[b2]' % (vi, box[0], box[1])
        elif vf:
            graph += ';%s;[b][vz]overlay=%d:%d:shortest=1[b2]' % (vf, vgeom[0], vgeom[1])
        else:
            graph += ';[b]null[b2]'
        graph += ';[b2]%s,format=yuv420p[v]' % sub
        cmd += ['-filter_complex', graph, '-map', '[v]', '-map', '0:a', '-shortest'] + (['-t', '%.2f' % (duration + 0.3)] if known else []) + ['-c:v', 'libopenh264', '-r', str(FPS), '-b:v', '1200k', '-g', str(FPS * 2), '-bf', '0', '-allow_skip_frames', '0',
                '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-ac', '2',
                '-f', 'hls', '-hls_time', '2', '-hls_list_size', '0', '-hls_playlist_type', 'event', '-hls_segment_filename', 'seg%05d.ts', 'index.m3u8']
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.proc = subprocess.Popen(cmd, cwd=out_dir, stdin=subprocess.PIPE if piped else subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        if piped:
            try:
                if py_deck:
                    dk = dict(deck, start=start)
                    colour = str((viz or {}).get('color') or 'accent')
                    accent = vizrender._hex((viz or {}).get('accent') or '#7aa2ff')
                    pic = vizrender.Composite(box[2], box[3], vizrender.painter_for(viz, vgeom[2], vgeom[3]) if py_viz else None, (vgeom[0] - box[0], vgeom[1] - box[1]),
                                              vizrender.DeckPainter(dk, colour, accent, dgeom[3]), (dgeom[0] - box[0], dgeom[1] - box[1]), start)
                else:
                    pic = vizrender.painter_for(viz, vgeom[2], vgeom[3])
                self.feeder = vizrender.Feeder(ffmpeg, src, pic, self.proc.stdin, flags)
                self.feeder.start()
            except Exception as exc:                        # no pictures: the stream would wait for them, so end it and let the caller play the audio only
                self.error = 'visualizer: %s' % exc
                self.proc.kill()
        self._log = log
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        err = self.proc.stderr.read().decode('utf-8', 'replace').strip()
        self.proc.wait()
        if self.proc.returncode not in (0, None) and err:
            self.error = err.splitlines()[-1][:300]
            if self._log:
                self._log('lyric video ffmpeg failed: ' + err[-600:])

    def segments(self):
        try:
            with open(os.path.join(self.dir, 'index.m3u8'), encoding='utf-8') as f:
                return f.read().count('#EXTINF')
        except OSError:
            return 0

    def wait_ready(self, pieces=3, timeout=60):
        """Waits until `pieces` pieces exist (or the stream is complete). Returns True when the TV can start."""
        end = time.time() + timeout
        while time.time() < end:
            if self.segments() >= pieces or (self.proc.poll() == 0 and self.segments() > 0):
                return True
            if self.proc.poll() not in (None, 0):
                return False
            time.sleep(0.2)
        return False

    def stop(self):
        if self.feeder:
            self.feeder.stop()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
