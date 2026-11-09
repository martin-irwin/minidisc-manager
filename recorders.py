"""What the app says about a recorder: the ATRAC generation it has, a few headline features and, for some models, a photo.

The facts are summarised from the equipment pages at minidisc.org (Sony's own product names and launch dates); a model that is not
listed here shows nothing extra. The photos are freely licensed pictures from Wikimedia Commons, shipped in ui\\recorders\\ and credited
in ui\\recorders\\CREDITS.txt and on screen.
"""
import re

HIMD_ATRAC = 'ATRAC (SP), ATRAC3 (LP2 / LP4), ATRAC3plus (Hi-SP / Hi-LP) and linear PCM'
HIMD2_ATRAC = HIMD_ATRAC + '; plays MP3 directly'
NETMD_ATRAC = 'ATRAC SP and ATRAC3 long play (MDLP: LP2 / LP4)'

# key: (display name, ATRAC line, [features], photo key or None, [(photo credit: author, licence)])
MODELS = {
    'NH1': ('MZ-NH1', HIMD_ATRAC, [
        'One of the first Hi-MD recorders (2004)', 'Records to 1 GB Hi-MD discs or standard MDs formatted to 300 MB',
        'Line, mic and optical inputs; USB data and PC upload', 'Removable Li-ion battery (about 18 hours of playback)',
        'Backlit remote with jog dial', 'Magnesium body, 6-band equaliser, VPT virtual surround, digital pitch control'],
        'NH1', ('Darklanlan', 'CC BY 4.0')),
    'NH3D': ('MZ-NH3D', HIMD_ATRAC, [
        'Hi-MD player and downloader: no line or mic inputs, it records only over USB', 'Plays and downloads to Hi-MD and standard MDs',
        'USB data connection (works as a USB drive)', 'Li-ion battery with charging stand', 'Optional backlit remote with jog dial'],
        'NH3D', ('DietrichLiao', 'CC BY 2.0')),
    'NH900': ('MZ-NH900', HIMD_ATRAC, [
        'Hi-MD recorder (2004) with a jog dial on the case', 'Line, mic and optical inputs; line / headphone output',
        'NiMH rechargeable battery, with an AA case for alkaline cells', 'VPT virtual surround, 6-band equaliser, digital pitch control',
        'Bookmarks for up to 2047 tracks', 'Backlit stick remote'], None, None),
    'NH700': ('MZ-NH700', HIMD_ATRAC, [
        'Records to 1 GB Hi-MD discs or standard MDs formatted to 300 MB', 'Line, mic and optical inputs', 'USB data (works as a USB drive)',
        'NiMH AA-format rechargeable battery (about 9 hours of Hi-LP playback)', 'Stick remote with no display',
        '6-band equaliser, bookmarks for up to 2047 tracks'],
        'NH700', ('Product image (the Sony / retailer picture of the MZ-NH700); copyright remains with its owner',)),
    'NH600': ('MZ-NH600', HIMD_ATRAC, [
        'Cost-reduced, entry-level Hi-MD recorder', 'No remote; USB connection on the main unit',
        'The European model has a line / optical input; the US MZ-NH600D has no inputs', '6-band equaliser, bookmarks for up to 2047 tracks'],
        None, None),
    'DH10P': ('MZ-DH10P', HIMD2_ATRAC, [
        'Hi-MD player with a built-in 1.3 megapixel camera and 4x digital zoom', '1.5-inch colour screen with slide-show mode',
        'Plays MP3 and ATRAC3plus files directly', 'No recording inputs; headphone output', 'Li-ion battery with charging cradle'], None, None),
    'RH10': ('MZ-RH10', HIMD2_ATRAC, [
        'Second-generation Hi-MD recorder (2005)', 'Line / optical, mic and USB recording sources', 'Remote with a display',
        'Digital amp and G-Protection anti-skip', 'Stores audio, video and data files on Hi-MD discs'],
        'RH10', ('DietrichLiao', 'CC BY 2.0')),
    'RH910': ('MZ-RH910', HIMD2_ATRAC, [
        'Second-generation Hi-MD recorder (2005)', 'Line / optical, mic and USB recording sources', '5-line LCD and a remote',
        'NiMH battery (about 25 hours)', 'Digital amp and G-Protection anti-skip'], None, None),
    'RH710': ('MZ-RH710', HIMD2_ATRAC, [
        'Second-generation Hi-MD recorder (2005)', 'Line / optical input', '3-line LCD and a basic remote', 'NiMH battery (about 25 hours)',
        'Digital amp and G-Protection anti-skip'], None, None),
    'RH1': ('MZ-RH1', HIMD2_ATRAC, [
        'The most advanced Hi-MD recorder (2006)', 'Records Hi-MD (PCM / Hi-SP / Hi-LP) and standard discs (SP / LP2 / LP4)',
        'Uploads recordings, including standard-MD ones, back to a PC', 'Mic and line inputs; switchable line / headphone output',
        'OLED display and a remote with an LCD', 'Li-ion battery charged over USB', 'Digital pitch control, spectrum analyser, manual record level'],
        'RH1', ('Esteban García González', 'CC BY-SA 4.0')),
    'N1': ('MZ-N1', NETMD_ATRAC, [
        'The first NetMD Walkman (2001), with the ATRAC DSP Type-R chip', 'USB downloads from a PC (no upload); the USB port is on the cradle',
        'Line / optical and mic inputs', 'NiMH battery, or one AA cell in an adapter case', 'Magnesium case, 3-line display, backlit remote',
        'LP4 downloads at up to 30x real time'], None, None),
    'N505': ('MZ-N505', NETMD_ATRAC, [
        'Budget NetMD recorder (2002) with no microphone input', 'USB downloads from a PC', 'Line / optical input', 'Rechargeable AA battery'],
        None, None),
    'N510': ('MZ-N510', 'ATRAC Type-S; ' + NETMD_ATRAC, [
        'Entry-level NetMD recorder (2003)', 'Line / optical input, no microphone input', 'One AA battery (NiCd) and a non-LCD remote',
        'Groups, bookmark tracks and quick mode', 'Level change and character input while recording'],
        'N510', ('Sony net md walkman mz n510.jpg on Wikimedia Commons (CC BY-SA 3.0)',)),    'N707': ('MZ-N707', NETMD_ATRAC, [
        'NetMD recorder (2002): an MZ-N505 with a microphone input', 'Remote control with editing', 'Charging stand',
        'Car-adapter kit', 'USB downloads from a PC'], 'N707', ('Evan-Amos', 'public domain')),
    'S1': ('MZ-S1', NETMD_ATRAC, [
        'Splash-proof NetMD recorder (2002) with a thumb joystick on top', 'Backlit amber LCD, no remote', 'Line / optical input, no mic input',
        'One AA battery (about 54 hours of LP4 playback)', 'Long-play recording up to 320 minutes on an 80-minute disc'], None, None),
    'N10': ('MZ-N10', 'ATRAC DSP Type-S; ' + NETMD_ATRAC, [
        'NetMD recorder (2002), thinner and lighter than the MZ-N1', 'Built-in Li-ion battery with an optional AA case',
        'Mic and line / optical inputs', 'Rehearsal mode for fine track marks, auto time marks', 'Virtual headphone effects',
        'Playback speed 0.5x to 2.0x without changing pitch'], None, None),
    'N910': ('MZ-N910', 'ATRAC DSP Type-S; ' + NETMD_ATRAC, [
        'NetMD recorder (2003)', 'Mic and line / optical inputs', 'NiMH battery (with an optional AA case)',
        'Backlit LCD remote, 3-line display', '6-band equaliser, virtual sound, melody alarm', 'Variable playback speed (50 to 150 %)'],
        None, None),
    'NE410': ('MZ-NE410', NETMD_ATRAC, [
        'Entry-level NetMD downloader (2003): no audio inputs, it records only over USB', 'Downloads at up to 32x speed (LP4)',
        'One AA battery', 'No remote', 'Quick mode trades battery life for faster searching'],
        None, None),
    'NE810': ('MZ-NE810', 'ATRAC DSP Type-S; ' + NETMD_ATRAC, [
        'NetMD downloader / player (2003): no line or mic inputs', 'One-button CD ripping and downloading with the included software',
        'One AA NiMH battery', 'Remote shows Roman, Kana and Kanji titles', 'Digital amplifier'],
        'NE810', ('Solomon203', 'CC BY-SA 3.0')),
    'N920': ('MZ-N920', NETMD_ATRAC, [
        'NetMD recorder (2004)', 'Line / optical and mic inputs', 'USB downloads at up to 64x speed', 'NiMH battery',
        'Backlit stick remote with Kanji display', 'Digital amp, 6-band equaliser, VPT surround'],
        'N920', ('Kuha455405', 'CC BY-SA 3.0')),
}


def lookup(model):
    """The entry for a model name such as 'Sony MZ-NH700' or 'Sony MZ-RH710/MZ-RH910' (the first one named), or None."""
    best = None
    for key in MODELS:
        m = re.search(r'(?<![A-Za-z0-9])' + re.escape(key) + r'(?![A-Za-z0-9])', model or '')
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), key)
    if not best:
        return None
    name, atrac, features, photo, credit = MODELS[best[1]]
    return {'name': name, 'atrac': atrac, 'features': features,
            'photo': 'recorders/%s.jpg' % photo if photo else None,
            'credit': (credit[0] if len(credit) == 1 else 'Photo: %s, %s (Wikimedia Commons)' % credit) if credit else None}