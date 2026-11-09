"""The window's visualizer drawn frame by frame in Python, for the lyric video on a Google TV.

The window draws its displays on a canvas from the browser's Web Audio analysers. The TV stream is made faster than real time, so the picture cannot be
copied from the window; instead this module reads the same audio (decoded by ffmpeg), does the same analysis (the analysers' FFT, smoothing and dB scale)
and draws every style again with Pillow: spectrum bars, mirror, oscilloscope, circular, waterfall, the four vintage / round VU meters, needles, LED
columns, bars and the three MZ-RH1 displays. The numbers (sizes, colours, steps) follow the window's code in ui\\index.html (see "Visualizer" there).
Frames are plain RGB on the lyric video's background colour and go to ffmpeg through a pipe."""
import colorsys
import math
import subprocess
import threading

try:
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
    OK = True
except ImportError:                                            # the caller falls back to ffmpeg's own (simpler) drawing
    OK = False

BG = (18, 22, 28)                                              # the lyric video's background, 0x12161c
SR, FPS = 44100, 25
HOP = SR // FPS
S = 2                                                          # drawn at twice the size and reduced: smooth edges
K = 60.0 / FPS                                                 # the window draws about 60 times a second: its per-frame steps are scaled to this
WHITE = (255, 255, 255)
HEADROOM, VU_REF = 0.8, -14                                    # the same as VIZ_HEADROOM / VU_REF in the window: loud music pegged the displays


def _mix(top, alpha, base=BG):
    return tuple(int(round(base[i] * (1 - alpha) + top[i] * alpha)) for i in range(3))


def _hex(c):
    c = str(c).lstrip('#')
    if c.startswith('0x'):
        c = c[2:]
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except (ValueError, IndexError):
        return (122, 162, 255)


_fonts = {}


def _font(size, bold=False):
    key = (int(round(size)), bold)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype('C:/Windows/Fonts/%s.ttf' % ('segoeuib' if bold else 'segoeui'), key[0])
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l, s)
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


class Analysis:
    """The window's analysers, fed the audio frame by frame (HOP stereo samples at a time)."""

    def __init__(self):
        self.L = np.zeros(2048, np.float32)
        self.R = np.zeros(2048, np.float32)
        self.prev = {}
        self.win = {n: np.blackman(n).astype(np.float32) for n in (1024, 2048)}

    def feed(self, l, r):
        n = len(l)
        self.L = np.concatenate((self.L[n:], l))[-2048:]
        self.R = np.concatenate((self.R[n:], r))[-2048:]

    def _bytes(self, key, x, fft, tau, lo, hi):
        spec = np.abs(np.fft.rfft(x[-fft:] * self.win[fft]))[:fft // 2] / fft
        tau = tau ** K
        prev = self.prev.get(key)
        sm = spec if prev is None else tau * prev + (1 - tau) * spec
        self.prev[key] = sm
        db = 20 * np.log10(np.maximum(sm, 1e-12))
        return np.clip(np.floor(255 * (db - lo) / (hi - lo)), 0, 255)

    def tick(self):
        """Reads the analysers once for this frame."""
        m = (self.L + self.R) * 0.5
        self.freq = self._bytes('m', m, 2048, 0.7, -85, -12)                  # aM
        self.qL = self._bytes('l', self.L, 1024, 0.6, -85, -12)               # aL, aR (the MZ-RH1 displays)
        self.qR = self._bytes('r', self.R, 1024, 0.6, -85, -12)
        self.wL, self.wR = self.L[-1024:], self.R[-1024:]


class Painter:
    def __init__(self, w, h, style, colour, accent, gain, peaks):
        self.w1, self.h1 = w, h
        self.W, self.H = w * S, h * S
        self.style, self.colour, self.accent, self.gain, self.peaks = style, colour, accent, gain, peaks
        self.an = Analysis()
        self.n = 0
        self.lv, self.pk, self.pkAt = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
        self.bars, self.peak = [0.0] * 80, [0.0] * 80
        self.rb = [[0.0] * 6, [0.0] * 6]
        self.rp = [[0.0] * 6, [0.0] * 6]
        self.fall = None

    # ------------------------------------------------------------------ colours
    def col(self, frac, i, n):
        k = self.colour
        if k == 'rainbow':
            return _hsl(300 * i / max(1, n - 1), 0.85, 0.58)
        if k == 'fire':
            return _hsl(55 - 55 * frac, 0.95, (42 + 18 * frac) / 100)
        if k == 'ice':
            return _hsl(235 - 55 * frac, 0.85, (50 + 15 * frac) / 100)
        if k == 'classic':
            return (255, 75, 62) if frac > 0.85 else (255, 210, 63) if frac > 0.62 else (61, 220, 132)
        if k == 'white':
            return (236, 239, 244)
        if k == 'oled':
            return (63, 162, 255)
        return self.accent

    # ------------------------------------------------------------------ analysis helpers
    def band(self, i, n):
        nyq, bins = SR / 2.0, len(self.an.freq)
        f0, f1 = 40 * 400 ** (i / n), 40 * 400 ** ((i + 1) / n)
        a = max(0, int(f0 / nyq * bins))
        b = min(bins - 1, max(a, int(math.ceil(f1 / nyq * bins)) - 1))
        s = float(self.an.freq[a:b + 1].mean())
        return min(1.0, s / 255 * self.gain * HEADROOM * (1 + 0.6 * i / n))

    def levels(self):
        t = self.n / float(FPS)
        for c, x in enumerate((self.an.wL, self.an.wR)):
            rms = float(np.sqrt(np.mean(x * x)))
            db = 20 * math.log10(rms * self.gain + 1e-9)
            target = max(0.0, min(1.0, (db + 40) / 43))
            k = 0.17 if target > self.lv[c] else 0.08
            self.lv[c] += (target - self.lv[c]) * (1 - (1 - k) ** K)
            if self.lv[c] >= self.pk[c]:
                self.pk[c], self.pkAt[c] = self.lv[c], t
            elif t - self.pkAt[c] > 1.1:
                self.pk[c] = max(self.lv[c], self.pk[c] - 0.012 * K)

    # ------------------------------------------------------------------ frame
    def frame(self, l, r):
        """The picture (RGB bytes, w x h) for the next HOP samples of audio."""
        self.an.feed(l, r)
        self.an.tick()
        self.n += 1
        st = self.style
        W, H = self.W, self.H
        if st == 'fall':
            if self.fall is None:
                self.fall = Image.new('RGB', (W, H), BG)
            img = self.fall
            self.d_fall(img)
        else:
            img = Image.new('RGB', (W, H), BG)
            d = ImageDraw.Draw(img)
            if st in ('bars', 'mirror'):
                self.d_bars(d, st == 'mirror')
            elif st == 'scope':
                self.d_scope(d)
            elif st == 'radial':
                self.d_radial(d)
            elif st.startswith('rh1'):
                img = self.d_rh1(img, st)
            else:
                self.levels()
                if st in ('vcream', 'vamber', 'rcream', 'ramber'):
                    self.d_vintage(img, 'amber' in st, st[0] == 'r')
                elif st == 'needle':
                    self.d_needle(d)
                elif st == 'led':
                    self.d_led(d)
                else:
                    self.d_hbars(d)
        return img.reduce(S).tobytes()

    # ------------------------------------------------------------------ spectrum styles
    def d_bars(self, d, mid):
        W, H = self.W, self.H
        N = max(16, min(64, self.w1 // 9))
        bw = W / float(N)
        for i in range(N):
            v = self.band(i, N)
            self.bars[i] = max(v, self.bars[i] - 0.035 * K)
            self.peak[i] = max(self.bars[i], self.peak[i] - 0.01 * K)
            full = (H / 2 - 4) if mid else (H - 6)
            hh = self.bars[i] * full
            x, w = i * bw + bw * 0.12, bw * 0.76
            c = self.col(self.bars[i], i, N)
            if mid:
                d.rectangle([x, H / 2 - hh, x + w, H / 2 + hh], fill=c)
            else:
                d.rectangle([x, H - max(hh, 1), x + w, H], fill=c)
            if self.peaks:
                ph, pc = self.peak[i] * full, _mix(WHITE, 0.85)
                if mid:
                    d.rectangle([x, H / 2 - ph - 2 * S, x + w, H / 2 - ph], fill=pc)
                    d.rectangle([x, H / 2 + ph, x + w, H / 2 + ph + 2 * S], fill=pc)
                else:
                    d.rectangle([x, H - ph - 3 * S, x + w, H - ph - S], fill=pc)

    def d_scope(self, d):
        W, H = self.W, self.H
        for c, (a, shade) in enumerate(((self.an.wL, 0.0), (self.an.wR, 0.55))):
            n = len(a)
            xs = np.arange(n) / (n - 1.0) * W
            ys = np.clip(H / 2 - a * self.gain * H * 0.46, 2, H - 2)
            col = _mix(self.col(0.35, 6, 10), 0.85) if c else self.col(0.8, 1, 10)
            d.line(list(zip(xs.tolist(), ys.tolist())), fill=col, width=int(2 * S), joint='curve')

    def d_radial(self, d):
        W, H = self.W, self.H
        N, cx, cy = 72, W / 2.0, H / 2.0
        r0 = min(W, H) * 0.2
        rm = min(W, H) * 0.46 - r0
        for i in range(N):
            v = self.band(i * 2 if i < N / 2 else (N - 1 - i) * 2, N)
            a = i / float(N) * math.pi * 2 - math.pi / 2
            self.bars[i] = max(v, self.bars[i] - 0.035 * K)
            ln = 2 + self.bars[i] * rm
            d.line([(cx + math.cos(a) * r0, cy + math.sin(a) * r0), (cx + math.cos(a) * (r0 + ln), cy + math.sin(a) * (r0 + ln))],
                   fill=self.col(self.bars[i], i, N), width=int(max(2, 2.4 * S)))

    def d_fall(self, img):
        W, H = self.W, self.H
        step, N = int(round(2 * S * K)), 48
        img.paste(img.crop((step, 0, W, H)), (0, 0))
        strip = _mix((0, 0, 0), 0.30)
        d = ImageDraw.Draw(img)
        d.rectangle([W - step, 0, W, H], fill=strip)
        for i in range(N):
            v = self.band(i, N)
            c = _mix(self.col(v, i, N), min(1.0, v * 1.5), strip)
            d.rectangle([W - step, H - (i + 1) * H / N, W, H - i * H / N + 1], fill=c)

    # ------------------------------------------------------------------ meters
    def scale(self, d, x0, y0, x1, y1, vertical):
        col, f = _mix((220, 225, 235), 0.65), _font(9 * S)
        for db in (-40, -30, -20, -10, -6, -3, 0):
            fr = (db + 40) / 43.0
            if vertical:
                d.text((x0, y1 - fr * (y1 - y0)), str(db), fill=col, font=f, anchor='mm')
            else:
                d.text((x0 + fr * (x1 - x0), y0), str(db), fill=col, font=f, anchor='mm')

    def arc(self, d, cx, cy, r, a0, a1, fill, width):
        if width < 1:
            width = 1
        R = r + width / 2.0
        d.arc([cx - R, cy - R, cx + R, cy + R], math.degrees(a0), math.degrees(a1), fill=fill, width=int(round(width)))

    def d_needle(self, d):
        W, H = self.W, self.H
        w = S
        for c in range(2):
            hw = W / 2.0
            cx, cy = hw * c + hw / 2, H * 0.94
            r = min(hw * 0.46, H * 0.84)
            ang = lambda f: math.pi * (0.8 - 0.6 * f)
            pt = lambda f, rr: (cx + math.cos(ang(f)) * rr, cy - math.sin(ang(f)) * rr)
            dim = _mix(WHITE, 0.14)
            self.arc(d, cx, cy, r, -ang(0) * 1, -ang(1), dim, 6 * w)
            self.arc(d, cx, cy, r, -ang(40 / 43.0), -ang(1), (255, 75, 62), 6 * w)
            f9 = _font(9 * w)
            for db in (-40, -30, -20, -10, -6, -3, 0):
                fr = (db + 40) / 43.0
                x, y = pt(fr, r + 11 * w)
                d.text((x, y), str(db), fill=_mix((220, 225, 235), 0.7), font=f9, anchor='mm')
                d.line([pt(fr, r - 6 * w), pt(fr, r + 2 * w)], fill=_mix((220, 225, 235), 0.5), width=int(w))
            d.text((cx, cy - r * 0.32), 'R' if c else 'L', fill=_mix((220, 225, 235), 0.7), font=_font(13 * w, True), anchor='mm')
            nx, ny = pt(self.lv[c], r - 3 * w)
            d.line([(cx, cy), (nx, ny)], fill=(255, 210, 63) if self.colour == 'classic' else self.col(0.9, 3, 6), width=int(2.4 * w))
            d.ellipse([cx - 5 * w, cy - 5 * w, cx + 5 * w, cy + 5 * w], fill=_mix(WHITE, 0.85))
            if self.peaks:
                px, py = pt(self.pk[c], r + 2 * w)
                d.ellipse([px - 2.6 * w, py - 2.6 * w, px + 2.6 * w, py + 2.6 * w], fill=WHITE)

    def d_led(self, d):
        W, H = self.W, self.H
        w, seg = S, 26
        colW = min(W * 0.2, 90 * w)
        cxs = [W / 2 - colW * 0.9 - 14 * w, W / 2 + colW * 0.9 + 14 * w]
        top, bot = 12 * w, H - 12 * w
        sh = (bot - top) / seg
        self.scale(d, W / 2, top, W / 2, bot, True)
        for c in range(2):
            for s in range(seg):
                f, on = (s + 0.5) / seg, self.lv[c] * seg > s
                col = self.col(f, s, seg)
                d.rectangle([cxs[c] - colW / 2, bot - (s + 1) * sh + 1.5 * w, cxs[c] + colW / 2, bot - s * sh - 1.5 * w], fill=col if on else _mix(col, 0.13))
            if self.peaks:
                s = min(seg - 1, int(self.pk[c] * seg))
                d.rectangle([cxs[c] - colW / 2, bot - (s + 1) * sh + 1.5 * w, cxs[c] + colW / 2, bot - (s + 1) * sh + 4 * w], fill=WHITE)
            d.text((cxs[c], H - 4 * w), 'R' if c else 'L', fill=_mix((220, 225, 235), 0.8), font=_font(12 * w, True), anchor='mm')

    def d_hbars(self, d):
        W, H = self.W, self.H
        w = S
        x0, x1, bh = 26 * w, W - 14 * w, (H - 52 * w) / 2
        for c in range(2):
            y = 10 * w + c * (bh + 10 * w)
            d.rectangle([x0, y, x1, y + bh], fill=_mix(WHITE, 0.08))
            n = 48
            for s in range(n):
                if self.lv[c] * n <= s:
                    break
                d.rectangle([x0 + s * (x1 - x0) / n, y, x0 + (s + 1) * (x1 - x0) / n + 0.5, y + bh], fill=self.col((s + 0.5) / n, s, n))
            if self.peaks:
                px = x0 + self.pk[c] * (x1 - x0)
                d.rectangle([px - 1.5 * w, y, px + 1.5 * w, y + bh], fill=WHITE)
            d.text((12 * w, y + bh / 2), 'R' if c else 'L', fill=_mix((220, 225, 235), 0.85), font=_font(12 * w, True), anchor='mm')
        self.scale(d, x0, H - 14 * w, x1, H - 14 * w, False)

    # ------------------------------------------------------------------ vintage VU
    MARKS = [(-20, 0), (-10, 0.2), (-7, 0.3), (-5, 0.4), (-3, 0.52), (-2, 0.6), (-1, 0.68), (0, 0.77), (1, 0.86), (2, 0.93), (3, 1)]

    def vupos(self, vu):
        m = self.MARKS
        if vu <= -20:
            return 0.0
        if vu >= 3:
            return 1.0
        for i in range(1, len(m)):
            if vu <= m[i][0]:
                a, pa = m[i - 1]
                b, pb = m[i]
                return pa + (pb - pa) * (vu - a) / float(b - a)
        return 1.0

    def d_vintage(self, img, amber, rnd):
        W, H = self.W, self.H
        w = S
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W - 1, H - 1], 8 * w, fill=(21, 23, 28))                 # the dark bezel
        gap = 10 * w
        pw0, ph0 = (W - gap * 3) / 2.0, H - gap * 2
        for c in range(2):
            dm = min(pw0, ph0) * (0.9 if rnd else 1)
            pw, ph = (dm, dm) if rnd else (pw0, ph0)
            pw, ph = int(pw), int(ph)
            x0 = gap + c * (pw0 + gap) + ((pw0 - dm) / 2 if rnd else 0)
            y0 = gap + ((ph0 - dm) / 2 if rnd else 0)
            x0, y0 = int(x0), int(y0)
            cx, cy = pw / 2.0, ph * (0.72 if rnd else 1.08)                                # local to the panel
            R = ph * (0.38 if rnd else 0.74)
            th = 0.9 if rnd else min(0.95, 0.42 * pw / R)
            ang = lambda p: -th + 2 * th * p
            pt = lambda p, r: (cx + math.sin(ang(p)) * r, cy - math.cos(ang(p)) * r)
            ink = (42, 22, 6) if amber else (43, 33, 24)
            red = (192, 30, 18) if amber else (216, 64, 60)
            ins = 5 * w if rnd else 0
            if rnd:                                                                          # the chrome ring
                yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
                t = np.clip((xx * pw + yy * ph) / float(pw * pw + ph * ph), 0, 1)[..., None]
                c0, c1, c2 = np.array([217, 221, 227], np.float32), np.array([108, 113, 122], np.float32), np.array([196, 200, 207], np.float32)
                ring = np.where(t < 0.5, c0 + (c1 - c0) * (t / 0.5), c1 + (c2 - c1) * ((t - 0.5) / 0.5))
                rimg = Image.fromarray(ring.astype(np.uint8), 'RGB')
                m = Image.new('L', (pw, ph), 0)
                ImageDraw.Draw(m).ellipse([0, 0, pw - 1, ph - 1], fill=255)
                img.paste(rimg, (x0, y0), m)
            # the face
            top, bot = ((245, 163, 28), (255, 201, 90)) if amber else ((232, 207, 156), (246, 232, 194))
            yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
            t = (yy / float(ph))[..., None]
            face = np.array(top, np.float32) + (np.array(bot, np.float32) - np.array(top, np.float32)) * t
            dist = np.sqrt((xx - cx) ** 2 + (yy - ph) ** 2)
            a = (0.55 * np.clip(1 - dist / (pw * 0.5), 0, 1))[..., None]                     # the lamp glow along the bottom
            face = face * (1 - a) + np.array([255, 255, 230], np.float32) * a
            sub = Image.fromarray(np.clip(face, 0, 255).astype(np.uint8), 'RGB')
            sd = ImageDraw.Draw(sub)
            self.arc(sd, cx, cy, R, -math.pi / 2 + ang(0), -math.pi / 2 + ang(0.77), ink, 1.4 * w)
            self.arc(sd, cx, cy, R, -math.pi / 2 + ang(0.77), -math.pi / 2 + ang(1), red, 5 * w)
            fs = max(8.0, ph * 0.1)
            fnt = _font(fs, True)
            for vu, p in self.MARKS:
                hot = vu > 0
                sd.line([pt(p, R - (2 if hot else 0)), pt(p, R + 7 * w)], fill=red if hot else ink, width=max(1, int(1.3 * w)))
                tx, ty = pt(p, R + 7 * w + fs * 0.75)
                sd.text((tx, ty), str(vu) if vu > 0 else '20' if vu == -20 else str(-vu), fill=red if hot else ink, font=fnt, anchor='mm')
            for v in range(-20, 0):
                if any(mk[0] == v for mk in self.MARKS):
                    continue
                p = self.vupos(v)
                sd.line([pt(p, R), pt(p, R + 3.5 * w)], fill=ink, width=int(w))
            fv = _font(fs * 1.3, True)
            if rnd:
                sd.text((cx, ph * 0.5), 'VU', fill=ink, font=fv, anchor='mm')
            else:
                sd.text((pw * 0.08, ph * 0.3), 'VU', fill=ink, font=fv, anchor='lm')
            sd.text((cx, ph * (0.9 if rnd else 0.78)), 'R' if c else 'L', fill=ink, font=_font(fs * 0.8, True), anchor='mm')
            lit = self.lv[c] * 43 - 40 - VU_REF > 0.5                                                # the peak lamp
            lx, ly = (cx + ph * 0.3, ph * 0.2) if rnd else (pw - 16 * w, 16 * w)
            sd.ellipse([lx - 6 * w, ly - 6 * w, lx + 6 * w, ly + 6 * w], fill=(224, 42, 26) if lit else (44, 51, 48))
            sd.ellipse([lx - 3 * w, ly - 3 * w, lx + 1 * w, ly + 1 * w], fill=(255, 176, 160) if lit else (138, 149, 144))
            p = self.vupos(self.lv[c] * 43 - 40 - VU_REF)
            nx, ny = pt(p, R * 1.1)
            sd.line([(cx + 2 * w, cy), (nx + 2 * w, ny + 1.5 * w)], fill=_mix((0, 0, 0), 0.25, _mix(top, 0.5, bot)), width=int(2.4 * w))      # shadow
            sd.line([(cx, cy), (nx, ny)], fill=(22, 22, 22), width=int(1.6 * w))
            if rnd:
                sd.ellipse([cx - 5 * w, cy - 5 * w, cx + 5 * w, cy + 5 * w], fill=(42, 42, 42))
            m = Image.new('L', (pw, ph), 0)
            md = ImageDraw.Draw(m)
            if rnd:
                md.ellipse([ins, ins, pw - 1 - ins, ph - 1 - ins], fill=255)
            else:
                md.rounded_rectangle([0, 0, pw - 1, ph - 1], 5 * w, fill=255)
            img.paste(sub, (x0, y0), m)
            if not rnd:
                d.rounded_rectangle([x0, y0, x0 + pw - 1, y0 + ph - 1], 5 * w, outline=_mix(WHITE, 0.18, (21, 23, 28)), width=int(w))

    # ------------------------------------------------------------------ MZ-RH1
    RH1_HZ = (100, 250, 630, 1600, 4000, 10000)

    def rh1_bands(self):
        nyq = SR / 2.0
        for c, q in enumerate((self.an.qL, self.an.qR)):
            bins = len(q)
            for i, hz in enumerate(self.RH1_HZ):
                lo = math.sqrt(self.RH1_HZ[i - 1] * hz) if i else hz / 1.6
                hi = math.sqrt(hz * self.RH1_HZ[i + 1]) if i < 5 else hz * 1.6
                a = max(0, int(lo / nyq * bins))
                b = min(bins - 1, max(a, int(math.ceil(hi / nyq * bins)) - 1))
                s = float(q[a:b + 1].mean())
                v = min(1.0, s / 255 * self.gain * HEADROOM * (1 + 0.5 * i / 5))
                self.rb[c][i] = max(v, self.rb[c][i] - 0.04 * K)
                self.rp[c][i] = max(self.rb[c][i], self.rp[c][i] - 0.012 * K)

    def d_rh1(self, img, style):
        W, H = self.W, self.H
        w = S
        oled = self.colour == 'oled'
        hi = (212, 234, 255) if oled else WHITE
        panel = (0, 0, 0) if oled else (10, 12, 16)
        pd = ImageDraw.Draw(img)
        pd.rounded_rectangle([0, 0, W - 1, H - 1], 8 * w, fill=panel, outline=_mix((63, 162, 255), 0.25, panel) if oled else _mix(WHITE, 0.1, panel), width=int(w))
        lit = Image.new('RGB', (W, H), (0, 0, 0))
        d = ImageDraw.Draw(lit)
        lblc = (lambda a: _mix((120, 190, 255), a, panel)) if oled else (lambda a: _mix((220, 225, 235), a, panel))

        def lbl(t, x, y, size, a=0.8):
            d.text((x, y), t, fill=lblc(a), font=_font(size * w, True), anchor='mm')

        def seg(x, y, sw, sh, on, color):
            d.rectangle([x, y, x + sw, y + sh], fill=color if on else _mix(color, 0.12, panel))

        mesh = None
        if style == 'rh1meter':
            self.levels()
            n = 22
            x0, x1 = 34 * w, W - 16 * w
            sw, rowH, rgap = (x1 - x0) / n, 11 * w, 7 * w
            tot = rowH * 2 + rgap
            y0 = (H - tot - 16 * w) / 2
            for c in range(2):
                y = y0 + c * (rowH + rgap)
                on_n = int(round(self.lv[c] * n))
                pk = min(n - 1, int(self.pk[c] * n))
                for s in range(n):
                    seg(x0 + s * sw + 1.2 * w, y, sw - 2.4 * w, rowH, s < on_n, self.col((s + 0.5) / n, s, n))
                if self.peaks and self.pk[c] > 0.05 and pk >= on_n:
                    seg(x0 + pk * sw + 1.2 * w, y, sw - 2.4 * w, rowH, True, hi)
                lbl('R' if c else 'L', 16 * w, y + rowH / 2, 11)
            mesh = (x0, y0 - w, x1 - x0, tot + 2 * w)
            ty = y0 + tot + 12 * w
            lbl('-40', x0 + 10 * w, ty, 8, 0.55)
            lbl('-10', x0 + sw * 16.5, ty, 8, 0.55)
            lbl('0 dB', x1 - 12 * w, ty, 8, 0.55)
        else:
            self.rh1_bands()
            STEPS = 6
            if style == 'rh1std':
                lblW, gapG = 30 * w, 30 * w
                zone = (W - 2 * lblW - 2 * 10 * w - gapG) / 2
                cw, top, bot, base = zone / 8, 18 * w, H - 22 * w, 3 * w
                for c in range(2):
                    zx = lblW + 10 * w + c * (zone + gapG)
                    d.rectangle([zx, bot, zx + cw * 8, bot + base], fill=_mix((63, 162, 255), 0.7, panel) if oled else _mix((220, 225, 235), 0.55, panel))
                    for i in range(6):
                        st, pk = int(round(self.rb[c][i] * STEPS)), int(round(self.rp[c][i] * STEPS))
                        x = zx + (i + 1) * cw
                        if st > 0:
                            d.rectangle([x + 0.6 * w, bot - st / float(STEPS) * (bot - top), x + cw - 0.6 * w, bot], fill=self.col(st / float(STEPS), i, 6))
                        if self.peaks and pk > st:
                            yy = bot - pk / float(STEPS) * (bot - top) - 2 * w
                            d.rectangle([x + 0.6 * w, yy, x + cw - 0.6 * w, yy + 2 * w], fill=hi)
                mesh = (lblW + 10 * w, top - 6 * w, W - 2 * lblW - 20 * w, bot - top + 6 * w + base)
                lbl('L', lblW / 2 + 4 * w, bot - 12 * w, 20)
                lbl('R', W - lblW / 2 - 4 * w, bot - 12 * w, 20)
            else:
                gapG = 40 * w
                zone = (W - 40 * w - gapG) / 2
                cell = zone / 6
                dMax = min(cell * 0.96, H * 0.8)
                cy = H / 2.0
                rad = lambda s: dMax / 2 * (0.2 + 0.8 * s / (STEPS - 1))
                for c in range(2):
                    for i in range(6):
                        st, pk = int(round(self.rb[c][i] * (STEPS - 1))), int(round(self.rp[c][i] * (STEPS - 1)))
                        cx = 20 * w + c * (zone + gapG) + (i + 0.5) * cell
                        r = rad(st)
                        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=self.col(st / float(STEPS - 1), i, 6))
                        if self.peaks and pk > st:
                            r = rad(pk)
                            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=hi, width=int(1.5 * w))
                mesh = (10 * w, cy - dMax / 2 - 3 * w, W - 20 * w, dMax + 6 * w)
        if oled:                                                                             # the soft glow of lit pixels
            lit = ImageChops.lighter(lit, lit.filter(ImageFilter.GaussianBlur(2 * w)).point(lambda v: int(v * 0.7)))     # the glow only fills in around the pixels, they keep the pure blue
        out = ImageChops.lighter(img, lit)
        if mesh:                                                                             # an OLED's pixel grid: a fine dark mesh over what is lit
            x, y, mw, mh = [int(v) for v in mesh]
            a = np.asarray(out).copy()
            px = 2.4 * w
            xs = (x + np.arange(0, mw, px)).astype(int)
            ys = (y + np.arange(0, mh, px)).astype(int)
            xs, ys = xs[(xs >= 0) & (xs < W)], ys[(ys >= 0) & (ys < H)]
            y1, x1 = min(H, y + mh), min(W, x + mw)
            for off in range(max(1, int(0.7 * w))):
                a[max(0, y):y1, np.clip(xs + off, 0, W - 1)] = (a[max(0, y):y1, np.clip(xs + off, 0, W - 1)] * 0.6).astype(np.uint8)
                a[np.clip(ys + off, 0, H - 1), max(0, x):x1] = (a[np.clip(ys + off, 0, H - 1), max(0, x):x1] * 0.6).astype(np.uint8)
            out = Image.fromarray(a, 'RGB')
        return out


# ---------------------------------------------------------------------- the feeder
def painter_for(viz, w, h):
    style = str(viz.get('style'))
    accent = _hex(viz.get('accent') or '#7aa2ff')
    return Painter(w, h, style, str(viz.get('color') or 'accent'), accent, min(8.0, max(0.2, float(viz.get('gain') or 1))), viz.get('peaks') is not False)


class Feeder(threading.Thread):
    """Decodes the same audio as the video job, draws a picture per 1/25 s and writes the raw pictures to `sink` (the video job's stdin)."""

    def __init__(self, ffmpeg, src_args, painter, sink, flags=0):
        super().__init__(daemon=True)
        self.painter, self.sink, self.proc, self.stopped = painter, sink, None, False
        self.cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error'] + src_args + ['-vn', '-f', 'f32le', '-ac', '2', '-ar', str(SR), 'pipe:1']
        self.flags = flags

    def run(self):
        need = HOP * 2 * 4
        try:
            self.proc = subprocess.Popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=self.flags)
            while not self.stopped:
                buf = self.proc.stdout.read(need)
                if len(buf) < need:
                    break
                a = np.frombuffer(buf, np.float32).reshape(-1, 2)
                self.sink.write(self.painter.frame(a[:, 0].copy(), a[:, 1].copy()))
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.sink.close()
            except (OSError, ValueError):
                pass
            self.stop()

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
