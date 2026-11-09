MiniDisc Manager - portable version 0.22.1 (Restricted edition)
=========================================
Copyright (c) 2026 Vinny Powell. Licence: see LICENSE.txt.

This is the no-installer version. Unzip it anywhere (a folder on your Desktop or Documents is fine) and run "MiniDisc Manager.exe".
To remove it, close the program and delete the folder.

BEFORE YOU UNZIP (this avoids a lot of Windows warnings)
  Right-click the .zip file -> Properties -> tick "Unblock" at the bottom -> OK. Then unzip it.
  If you skip this, Windows may warn about every program file inside.

FIRST RUN
  1. Windows SmartScreen may say "Windows protected your PC / unknown publisher", because the program is not code-signed.
     Click "More info", then "Run anyway".
  2. A "Before you start" notice appears once. Please read it.
  3. Until the USB driver is set up the program says "No recorder found". Open DRIVER-SETUP.html (in this folder) and follow it.
     It takes about two minutes, once per recorder, with a free tool called Zadig.
  4. The first time you play to a Sonos speaker or a Google TV, Windows Firewall may ask. Choose "Allow" for private networks.
  5. A standard MiniDisc (not Hi-MD) is only seen if the recorder is plugged in WITH the disc already inside it.

BACK UP FIRST
  MiniDisc Manager can write to and erase MiniDiscs. It has only been tried on a Sony MZ-NH700 and an MZ-RH1, and a disc can be left
  unplayable if a write is interrupted. Copy any recordings you cannot replace to your PC before editing a disc, and do not unplug
  the recorder while the program says it is working.

WHAT IT CAN DO  (README.txt has the full details of every function)
  Groups               Make, add to, dissolve and delete groups of tracks (one album per group), group a whole disc by album, group
                       what you add (files, CD, Yoto, Bandcamp / SoundCloud / radio), and play a group (stay in it, or shuffle it).
                       Hi-MD discs. Undo last change is also at the top right of the window. The disc picture shows each group
                       as a band with a clickable legend (names, track counts, times).
  Player               Stop and Repeat buttons, keyboard keys (Space, arrows, S), and the free space as time left in each mode.
  Lyric timing         "Fine-tune timing" listens to the start of a track and sets the lyric timing so the lines come when they are sung (needs
                       the optional speech recogniser, downloaded once). Only clear shifts are corrected.
  Tabs and window      Recording and the tool panels show one section at a time (tabs). The window remembers its size and place.
  Delete fix           Deleting tracks no longer damages the audio of a neighbouring track that shared a block with it.  Two kinds of disc    Hi-MD discs (read and edited directly) and standard MiniDiscs (over NetMD: SP, LP2, LP4). Each recorder that is
                       plugged in is listed and recognised by itself.
  Recording panel      Everything that puts new music on the disc sits in its own panel, to the left of Disc Management: Add tracks from PC,
                       Rip CD, and recording from Bandcamp, SoundCloud and Internet Radio.
  Add tracks           Drag files onto the window or press "Add tracks from PC...". MP3, WAV, FLAC, M4A, OGG, AAC, WMA and AIFF are converted for
                       you. You choose the recording format: Hi-MD - PCM (lossless), MP3 128-320 kbps, ATRAC3 LP2 / LP4, ATRAC3+ Hi-SP 256 kbps,
                       Hi-LP 64 kbps or 352 kbps; standard disc - SP, LP2, LP4. A preview shows what fits before anything is written. Loud tracks are
                       turned down by just enough when an ATRAC encoder would otherwise make them crackle.
  Rip CD...            Copies an audio CD from this PC's CD drive onto the disc (read twice and compared), with titles and cover looked up for you.
  Yoto                 "Rip Yoto Card..." copies the card in your Yoto player (or one of your own playlists) onto the disc; you sign in to
                       Yoto once, on Yoto's own page, and the program never sees your password. Yoto keeps its audio as Opus, so the copy is of
                       that. "Send to Yoto Card..." copies the ticked tracks to a NEW playlist in your Yoto account, which you then link to a
                       blank MYO card in the Yoto app; it never edits or deletes an existing playlist.
  Bandcamp             "Add tracks from Bandcamp..." opens Bandcamp in a window of its own. You
                       sign in to your own account there. Whatever you play is
                       recorded as it plays, in real time, from that window's sound only, one track at a time, with the title, artist,
                       album and cover read from the page; tick the tracks and add them to the disc. A track that plays from its
                       start to its end is complete; if you pause or skip, what was recorded is kept as a partial track you can still
                       add. Recordings are kept until you close the program. Only record music you are entitled to copy for your own use;
                       Bandcamp's terms of use apply to its streams.
  SoundCloud           "Add tracks from SoundCloud..." works the same way with soundcloud.com (sign in to your own account).
                       Without SoundCloud Go+ some tracks play only a 30-second preview, and that is all that is recorded.
  Internet radio       "Add tracks from Internet Radio..." searches the free station directory radio-browser.info by name,
                       genre or country. Pick a station and press Record: the stream is recorded as it plays and cut into songs
                       where the station announces a new title (or recorded as one stretch of a length you choose). Tick the
                       songs you want and add them to the disc. Stations you use often can be saved as favourites, and you can listen while it records.
                       Only record what you are entitled to copy for your own use.
  Recorder box        Shows the recorder's model, firmware version and year of introduction, which ATRAC generations it supports,
                       a short feature list and, for many models, a small photo.
  Move, Split, Combine Move a track anywhere (or drag it by its number). Trim silence off the start and end of a track ("Suggest trim" finds it for you). Split a track at as many points as you like in one go, exactly where you choose, on a waveform you can zoom into and listen to. Combine as many tracks as you like into
                       one, in the order you choose. PCM is cut to the sample; ATRAC is cut or joined with no re-encoding. The new tracks are read back and compared
                       with what was written, and the originals are only deleted if you say so (Hi-MD discs).
  Auto split & name    Got a whole record side or a live set as ONE long track (SP / LP on a standard disc, or PCM / ATRAC such as Hi-SP on a Hi-MD
                       disc)? Tick it and press "Auto split & name...": the program finds the quiet gaps between songs, opens the Split window with
                       the cuts already placed (click a cut's number to hear it), writes the separate tracks and goes on to name them. No song
                       shorter than 2 minutes is made; buttons let you ask for shorter or longer songs.
  Lyrics               Find timed lyrics online (LRCLIB, NetEase Cloud Music, lyrics.ovh), make them by listening to the track (an optional speech recogniser, downloaded once, about 200 MB, runs on this PC) or load an .lrc file, keep them on a Hi-MD disc as one small file, and read them in time with the music while a track plays: the current line is lit in the Recording panel. Only the artist, title, album and length are sent to the lyrics services; Listen never sends audio anywhere.
  Visualizer           While a track plays on this PC the top of the Disc Information panel shows spectrum bars, an oscilloscope, a circular spectrum, a waterfall or stereo VU meters (needles, LED columns, bars), in colours you choose. Three displays copy the Sony MZ-RH1's blue OLED: its level meter and its two spectrum analyzers (standard bars and circle dots, six frequencies per channel).
  Album art online     "Find online..." under the disc image of a Hi-MD disc suggests covers from the Cover Art Archive, iTunes and Deezer, by artist and album; you
                       pick one, see it full size, and it is stored on the disc as the disc image. Only the artist and album words are sent, never audio.
  Pre-recorded discs   Put in a commercial (pre-recorded) standard MiniDisc and the program notices it, tells you in a pop-up, looks the album up
                       online (MusicBrainz) for the artist, album and album art, then finds the lyrics, all by itself. The artist, album and
                       art are remembered on this PC (a standard disc cannot hold them) and the art shows in Disc Information and on a Google
                       TV. Nothing is written to the disc; only words from the disc (artist, album, track titles) are sent. A "Look up online"
                       button does the same for any standard disc.
  Bluetooth speakers   In the player bar, the speaker button then "Sound output & Bluetooth..." lists the PC's sound outputs and finds, pairs and connects a
                       Bluetooth speaker using the PC's own Bluetooth (Windows does the pairing). The equalizer, visualizer and lyrics keep working.
  Disc labelling       "Make disc label..." (Recording panel) draws a sticker label for the loaded disc: the album art, disc title and artist and the track
                       list with times, as a Portrait (2 x 3 in) or Landscape (3 x 2 in) picture, with tick boxes for each part. Save it as a PNG, store
                       it on a Hi-MD disc (it then shows in Disc Information; it can be replaced or removed), or print it straight on a paired
                       HP Sprocket over Bluetooth (older 2 x 3 inch models that take a Bluetooth file push; tried on one printer) or a Polaroid
                       Hi-Print 2 x 3 (paired in Windows; close the Polaroid phone app first; a Film button counts the sheets left; tried on one printer).
  Labels for groups    On a disc with groups the label sheet can label the whole disc (with the group names as headings), just the groups (a tile per
                       group with its picture), or one group on its own; one picture per group can be saved in one go.
  Card layout          The Cards menu in the header shows or hides the seven main cards (Lyrics has its own card). Drag a card by the dotted handle on its title to a new place
                       (beside, above or below another card, or on a row of its own); drag a card's right edge, bottom edge or corner to resize it
                       (double-click an edge for automatic). The disc ring, album art and label in Disc Information grow with their card. The layout
                       is remembered; "Reset layout" puts everything back to stock (places, sizes, hidden and folded cards, first tabs).
  Group pictures       When a CD, a Yoto playlist or a Bandcamp / SoundCloud recording is added in a new group, its cover also becomes the group's picture.
  Movable pop-ups      Every pop-up window can be dragged by its title; questions are asked in the program's own boxes.
  Remove lyrics        A button in the lyrics box removes the wrong lyrics of the playing track from this PC.
  Equalizer            The EQ button in the player bar opens a window of its own with a ten-band equalizer (31 Hz to 16 kHz, plus or minus 12 dB), a preamp, presets
                       and presets of your own. The settings are remembered for each disc. It changes only the sound played through this PC.
  Fade & level         Add a fade in / out or even out the volume of tracks (written as new tracks).
  Identify:            Three separate buttons name tracks: Search for album (online, matched by track length), Paste a track list (one song
  Search for album,    per line with its length; for music no online service knows) and Listen to the tracks (the names appear as each track
  Paste a track list,  is heard; it works at once). Standard discs
  Listen to the tracks keep a title only, so the artist can be put in front of it.
  Edit details,       Set the artist or album of many tracks at once (a standard disc cannot store them, so this PC remembers them and shows
                       them in the columns). The list has an Album column, a tick box in its heading that ticks every track, and columns you can resize. The
  Disc catalogue       catalogue remembers every disc you load, Hi-MD or standard, so you can search them all without the disc.
  Progress and help    Long steps show a moving bar with the percentage and about how long is left. If a recorder stops answering, the sheet
                       says what to do (close the program, unplug the cable, switch the recorder off for 10 seconds, start again) and anything
                       already saved on this PC is kept and offered again.
  Saved copies         lists the PC copies kept of tracks added to standard discs and removes the leftovers you tick.
  Clone disc...        Copies a whole disc to another disc through this PC, with a swap of discs in between. Hi-MD to Hi-MD is an exact copy
                       (no re-encoding) with the titles, groups, disc name and picture, checked byte for byte. A standard disc to another
                       standard disc copies LP2 / LP4 exactly; SP is written again by the destination recorder (one more generation of
                       loss). You can untick tracks you do not want. The destination must be empty (the program can erase it for you).
  Play                 Play PCM, MP3 and ATRAC tracks straight off the disc, with a player bar, seeking and volume, here, on a Sonos
                       room, or on a Google TV (with the cover and the timed lyrics shown as a video). Standard discs play from the program's own copy of tracks it added, or are read back from the recorder (MZ-RH1;
                       and the MZ-NH700 with the experimental download described below); a recorder that cannot send audio back is played by
                       remote control instead.
  Save to PC...        Copies tracks to your PC as FLAC, WAV or MP3 (tags included), or keeps ATRAC tracks as their original .oma data. Works
                       for recordings made on the recorder, and for SP / LP tracks on a standard disc. "Export CSV" saves the track list.
  Burn Audio CD...     Burns the ticked tracks (or all) to a blank CD-R or CD-RW in a disc writer on this PC, as an ordinary audio CD that plays
                       in any CD player (2-second gaps, no CD-Text). Nothing is burnt unless every track could be read first; a CD-R can only
                       be written once, and a CD-RW that is not blank can be erased from the same sheet. On a standard MiniDisc the audio can
                       only be read back with an MZ-RH1 (or from a copy the program saved); Hi-MD discs work with any Hi-MD recorder.
  Save to disc...      Puts the tracks on a CD, DVD, Blu-ray or DVD-RAM as files (FLAC, WAV or MP3, plus a TRACKS.CSV list). CD / DVD / Blu-ray
                       need a blank disc, which is finished afterwards; a DVD-RAM must already be formatted and gets a folder. New in 0.13.0 and
                       not yet tried on every disc type.
  Disc tools           Rename tracks, artists, groups and the disc (double-click), Delete tracks (with Undo for renames and moves), store a
                       picture on a Hi-MD disc, Format a disc (as standard or Hi-MD), set the recorder's clock (MZ-RH1). On a Hi-MD disc the program can also keep the track list on the disc as TRACKS.CSV, updated
                       whenever tracks change, and open it from there (Copy out: "Keep a track list on the disc", "Open track list").

THE EXPERIMENTAL DOWNLOAD (MZ-NH700 and similar Hi-MD recorders)
  A standard-disc recorder normally cannot send a track's audio back to the PC. The MZ-NH700 can be made to, with a small temporary
  patch to the recorder's memory (from the open-source netmd-exploits library). The program only does this on firmware it has been
  checked on, writes nothing to the disc, and removes the patch when it finishes. It stays partly in memory until you unplug the
  recorder, so unplug it and plug it back in afterwards (with the disc inside). It is used when you press play on such a track, and when
  you tick the "experimental" box on the Save to PC or Clone sheet. It has been tried on one MZ-NH700 only.

WHAT YOU NEED
  - 64-bit Windows 10 or 11.
  - The Microsoft Edge WebView2 Runtime (Windows 11 has it; on Windows 10 install the "Evergreen Standalone Installer" from
    https://developer.microsoft.com/microsoft-edge/webview2/ if the window does not open).
  - A Sony Hi-MD or NetMD recorder, with the WinUSB driver set up as described in DRIVER-SETUP.html.
  - For Rip CD: a CD or DVD drive with an audio CD in it, and (optional) an internet connection for the album lookup.
  - For Burn Audio CD and Save to disc: a CD / DVD / Blu-ray writer and a blank disc. Tried so far on one Panasonic BD-MLT writer, with CD-R.

WHERE YOUR DATA GOES
  Backups of each disc's track index and a small log are kept in %LOCALAPPDATA%\MiniDiscManager (not in this folder), so you can move
  or delete the program folder without losing them. The program's FLAC copies of tracks it added to standard discs are kept there too
  (in "copies"), and so is a PC copy of a disc while it is being cloned (in "clone"; it is deleted when the clone has been written and
  checked, and can be discarded from the Clone sheet). Ripped CD audio is held in a temporary folder and deleted afterwards.

FILES
  README.txt              what the program does, in full
  DRIVER-SETUP.html       USB driver guide
  LICENSE.txt, THIRD-PARTY-NOTICES.txt, LICENSES\    licences and the open-source components used

MiniDisc Manager is not affiliated with or endorsed by Sony or Sonos. MusicBrainz and the Cover Art Archive are separate services.
