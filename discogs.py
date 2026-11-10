"""Discogs lookups for disc_lookup.py: a second source for albums MusicBrainz does not have (obscure pressings, compilations, bootlegs).

Uses Discogs' public database API without an account (it allows about 25 requests a minute that way, so requests are spaced out). Only words
(artist, album, track titles) are sent. Releases come back in the same shape as cdrip.release_flat, plus 'source': 'discogs' and 'image'."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import cdrip

_lock = threading.Lock()
_last = [0.0]
GAP = 2.5                                              # seconds between requests: stays under the 25-a-minute limit for clients without a key


def _get(url, tries=3):
    """The parsed JSON at a Discogs API address, None when it is not there (404). Raises cdrip.CdError when Discogs cannot be reached."""
    err = None
    for attempt in range(tries):
        with _lock:
            wait = GAP - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': cdrip.USER_AGENT, 'Accept': 'application/json'}), timeout=25) as r:
                return json.loads(r.read(6_000_000).decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = 'HTTP %d' % e.code
            if e.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(5 + 5 * attempt)
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = str(getattr(e, 'reason', e))
            time.sleep(1.5)
    raise cdrip.CdError('Discogs could not be reached (%s).' % err)


_NUMBERED = re.compile(r'\s*\(\d+\)$')                  # Discogs tells two artists of the same name apart as "Name (2)"


def _name(s):
    return _NUMBERED.sub('', (s or '').strip())


def _credit(artists):
    out = ''
    for a in artists or []:
        out += _name(a.get('name')) + (' ' + a['join'] + ' ' if a.get('join') and a['join'] != ',' else ', ' if a.get('join') == ',' else '')
    return out.strip(' ,')


def _seconds(text):
    m = re.fullmatch(r'\s*(?:(\d+):)?(\d{1,3}):(\d{2})\s*', text or '')
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def search(artist, album):
    """Releases found by artist and album title: [{id, source, title, artist, date, country, trackCount, format}]."""
    params = {'type': 'release', 'per_page': '10'}
    if album:
        params['release_title'] = album
    if artist:
        params['artist'] = artist
    if not (album or artist):
        raise cdrip.CdError('Type an artist or an album title to search for.')
    return _results(_get('https://api.discogs.com/database/search?' + urllib.parse.urlencode(params)))


def search_track(artist, title):
    """Releases that have a track of this name (by this artist)."""
    params = {'type': 'release', 'per_page': '10', 'track': title}
    if artist:
        params['artist'] = artist
    return _results(_get('https://api.discogs.com/database/search?' + urllib.parse.urlencode(params)))


def _results(data):
    out = []
    for r in (data or {}).get('results', []):
        if not r.get('id'):
            continue
        name = r.get('title') or ''
        artist, _, album = name.partition(' - ')          # Discogs gives "Artist - Album"
        if not album:
            artist, album = '', name
        out.append({'id': str(r['id']), 'source': 'discogs', 'title': album.strip(), 'artist': _name(artist), 'date': str(r.get('year') or ''),
                    'country': r.get('country') or '', 'trackCount': None, 'format': ', '.join((r.get('format') or [])[:3])})
    return out


def release(rid):
    """A release with its tracks in one list, like cdrip.release_flat: {id, source, title, artist, date, country, image, tracks: [{n, label, title, artist, seconds}]}."""
    data = _get('https://api.discogs.com/releases/%s' % urllib.parse.quote(str(rid)))
    if not data or not data.get('tracklist'):
        raise cdrip.CdError('That Discogs release has no track list.')
    tracks = []
    for t in data['tracklist']:
        if t.get('type_') not in (None, 'track') or not (t.get('title') or '').strip():
            continue                                     # headings and index entries
        tracks.append({'n': len(tracks) + 1, 'label': t.get('position') or str(len(tracks) + 1), 'title': t['title'].strip(),
                       'artist': _credit(t.get('artists')), 'seconds': _seconds(t.get('duration'))})
    images = data.get('images') or []
    primary = next((i for i in images if i.get('type') == 'primary'), images[0] if images else {})
    return {'id': str(data.get('id') or rid), 'source': 'discogs', 'title': (data.get('title') or '').strip(), 'artist': _credit(data.get('artists')),
            'date': str(data.get('year') or ''), 'country': data.get('country') or '', 'image': primary.get('uri') or primary.get('resource_url') or '', 'tracks': tracks}
