MiniDisc Manager
================
Copyright (c) 2026 Vinny Powell. Licence: see LICENSE.txt.

Open it with MiniDisc-Manager.bat. Close any other recorder program first: only one program can use the recorder at a time.
Nothing else needs installing: Node, ffmpeg and the MiniDisc libraries are bundled in the runtime\ folder.

The window
- The top row has four panels, each with a heading (on a narrower window they wrap into two rows). Recording and the tool panels
  show one section at a time: click a tab to change section. The last tab you used is remembered.
  * Disc Information: the disc picture (one arc per track), the disc name, track count, used / free space, and the disc image. While a track plays on this PC a live display of the music appears at the top of this panel (see Visualizer).
  * Recording: tabs "Add tracks" and "Disc labelling". Add tracks: Add tracks from PC..., Rip CD..., Rip Yoto Card..., Send to Yoto Card...,
    Add tracks from Bandcamp..., Add tracks from SoundCloud..., Add tracks from Internet Radio... and a tick box "Put each batch of added
    tracks in a new group" (see Groups). Disc labelling: Make disc label....
  * Disc Management: tabs Arrange, Groups, Auto split & name, Clone, Remove and Format:
      Arrange              Move...  Split...  Combine...  Edit details...  Fade & level...
      Groups               Group by album...  Make group...  Add to group...  Ungroup...  Delete group...
      Auto split & name    Auto split & name...
      Clone                Clone disc...
      Remove               Delete...  Undo last change
      Format               Format disc...
  * Disc Conversion (under Disc Management): two sections that appear only when they apply to the loaded disc: "Convert SP Disc to Hi-MD"
    (Convert to Hi-MD...) and "Convert LP2/4 Disc to SP" (Convert LP to SP...). See the two chapters below. When a conversion is
    possible for the loaded disc and its switch in Settings is on (and its note has not been hidden for this disc), a bright pulsing
    "Suggestion" flag appears in the card's title, even when the card is folded, and the section concerned is outlined.
  * Disc Extras (under Disc Conversion): tabs Identify (Search for album..., Paste a track list..., Listen to the tracks...), Lyrics,
    Check (Check this disc...) and Copy out (Save to PC..., Burn Audio CD..., Save to disc..., Export CSV, Open track list, and the tick box
    "Keep a track list on the disc").
    Each tab has a line saying what its buttons do. Tick tracks in the list first (the box in the heading of the track list ticks or unticks all of them):
    Move, Split and Auto split & name need exactly one ticked track, Combine two or more, Edit details, Fade & level, the three Identify buttons and Delete one or more. A button that does not apply stays grey (dashed outline). You can also drag a
    track by its number to a new place (ticked tracks move together).
  * Lyrics (its own card, by default under Recording): the lyrics of the track that is playing, the current line lit in time with the music. It opens short (just a note) and grows while lyrics show.
  * Card sizes: drag a card's right edge to change its width (the other cards in its row give up or take the space), its bottom edge for its height (a minimum: a card never gets smaller than its contents) or its corner for both; double-click an edge to go back to automatic. In the default layout the bottoms of the columns line up. "Reset layout" restores everything to stock: places, sizes, hidden and folded cards and the first tab of each tabbed card.
  * Card layout (header, between Theme and the recorder name): the Cards menu ticks the eight main cards (Disc Information, Recording, Lyrics, Disc
    Management, Disc Conversion, Disc Extras, Recorder, Tracks) on or off; Show all and Reset layout are in it too. Each card can be dragged by the dotted
    handle at the end of its title (the title itself still folds the card): drop on the left or right edge of another card for a new column
    beside it, on its top or bottom half to stack it above or below, or on the line between two rows (or above / below all of them) for a row
    of its own. Cards are sized by where they land: the cards in a row share its width (a card on a row of its own takes the full width) and
    a row that is too narrow splits into balanced lines, down to one column. In Disc Information the disc-usage ring, the album art and the
    label grow with the card's width (limited by the window height), so they fill the space when the other cards are hidden. Escape cancels a drag. The layout and the hidden cards are
    remembered.
  * Recorder: the model, its firmware version and the year it was introduced, a small photo beside the name (for the models that have a free one, or one you put in the recorder_photos folder as MZ-NH700.jpg and so on; that folder stays on your PC and is not part of the installer), the ATRAC
    generations it supports, a short list of its main features, and its clock. The facts are summarised from minidisc.org; photos are from
    Wikimedia Commons (credits under each photo and in ui\recorders\CREDITS.txt).
  Below them is the track list. In a medium-width window Disc Management moves underneath Disc Information and Recorder; in a
  narrow one the panels stack (Disc Information, Disc Management, Recorder).
- "Undo last change" is also at the top right of the window, next to Backup.... It restores the disc's track index as it was before the
  last rename, move, group or similar change (not after a delete, which moves the audio).
- The window opens at 1280 x 820 the first time. After that it opens the way you left it: its size, its place on the screen and whether
  it was maximised are remembered in %LOCALAPPDATA%\MiniDiscManager\window.json (delete that file to go back to the default).
- Text in the window (error messages, track names) can be selected and copied.

Groups (Hi-MD discs)
- A group is a named run of tracks that sit next to each other, for example one album on a disc that holds several. The recorder can play
  one group on its own, skip between groups and shuffle within one. A track is in at most one group; groups cannot be nested; a Hi-MD
  disc holds up to 255 groups. The track list shows a header above each group (fold arrow, a tick box for the whole group, the name,
  its size and "Play group"); tracks in no group sit under "No group". Double-click a group's name to rename it.
- Make group...: tick a run of tracks, give a name. If a ticked track is already in a group, that whole group must be ticked too (it is
  folded into the new one). Add to group...: tick ungrouped tracks that touch a group (nothing is added that you did not tick).
  Ungroup...: dissolves the group, the tracks stay. Delete group...: ticks every track of the group and opens the normal delete sheet.
- Group by album...: offers one group for each run of tracks that are next to each other, in no group yet and share an album; you untick
  any you do not want. Single tracks and tracks with no album are left alone. One change, one Undo.
- Groups when adding: every add window (files, CD, Yoto card, Bandcamp / SoundCloud / radio) has "Put the new tracks in a
  new group" with a name box (empty: the album). The same setting is the tick box under the add buttons. A single new track stays ungrouped.
  When ripping a CD, the cover found online or chosen in the rip window also becomes the new group's picture (kept on this PC; "Save group
  pictures to the disc..." on the Groups tab copies it onto the disc), whether or not it is also stored as the disc picture. The same goes for
  the cover of a Yoto playlist and the album picture of Bandcamp / SoundCloud recordings (internet radio has no picture).
- Playing groups: "Play group" plays a group and stays in it. The player bar has previous / next buttons and a play mode: Play on,
  Stay in group (tracks in no group count as one group per run) or Shuffle group (each track once, in random order). Not used when the
  recorder itself plays a standard disc. The mode is not remembered: every start is "Play on". Any other mode lights up the dropdown in the
  accent colour (its tooltip says which mode is on and how to switch it off), so shuffle can not stay on unnoticed.
- Group display (disc picture): on a disc with groups the Disc Information line starts with the group count, the disc picture has a
  coloured band around it for each group (hover for its name, track count and time), and a legend lists each group with its track count
  and total time. Click a legend entry or a band to jump to the group and tick its tracks (click again to untick). Hovering a track's
  arc highlights its row in the list, and hovering a row highlights its arc; hovering an arc, band or legend entry scrolls the list to it.
- The top of the window stays put; only the track list scrolls (its column headings stay in view).
- Player: a Stop button (ends playback and closes the player; pause keeps your place) and a Repeat button (off, all - the whole disc or
  group as "Play on" says - or one track; this PC only). Keys: Space play/pause, Left/Right back/forward 5 seconds (Shift: 15), S stop.
- Time left: under Used / Free / Total, the free space as playing time - Hi-MD: PCM, Hi-SP, Hi-LP; standard disc: SP, LP2, LP4.
- Only the group records in the disc's track index change (never the audio); a copy of the old index is kept, so "Undo last change"
  puts the groups back. Deleting tracks renumbers the groups that lose tracks, and a group that loses all its tracks is removed.
- Standard (SP / LP) discs keep their groups in the disc title; the group tools here do not change them yet.

Two kinds of disc
- Hi-MD disc (the recorder shows up as "Hi-MD"): the recorder is read as a disk and the app edits it directly.
- Standard MiniDisc (80-minute MD in a Hi-MD or NetMD recorder): the recorder shows up as "(standard disc)" and is driven
  with the NetMD protocol. Put the disc in the recorder BEFORE plugging in the USB cable, and let it finish reading.
  Hi-MD units switch to NetMD mode on their own when a standard disc is inside.

What it does - both kinds of disc
- Lists the connected recorders and shows the model, disc space and the track list.
- Adds tracks: drag files onto the window, or press "Add tracks from PC...". A dry run (nothing written) shows what fits and what
  will happen, then you confirm. Every file in the list has a tick box: if they will not all fit, untick the ones to leave out (the
  fit check and the "needs" line are worked out again from the ticked files), or press "Untick files from the end until the rest fit".
- Deletes any track (tick the box, press Delete). A confirmation sheet comes first.
- Moves a track to another position (Move...).
- Renames track titles and the disc name (double-click).
- Plays tracks (press the triangle on a row) - see the notes for each disc type.
- Saves tracks to your PC (Save to PC...), including tracks that were recorded on the recorder rather than added from the PC.
- Exports the track list to CSV.
- Formats the disc (Format disc...).
- Splits and combines tracks (Hi-MD discs, and standard discs with some limits; see "Splitting and combining tracks").
- Clones a whole Hi-MD disc onto another Hi-MD disc, or a standard (SP / LP) disc onto another standard disc, through this PC
  (see "Cloning a disc").

Ripping a Yoto card (Rip Yoto Card...)
- Copies the tracks of a Yoto Make Your Own (MYO) playlist onto the disc in the recorder (either kind of disc). The sheet lists your
  Yoto players with the card that is in each one, and your own playlists; pick one, tick the tracks, edit titles, choose the recording
  format, optionally name the disc and store the playlist's cover as the disc picture.
- Sign-in: once, in your browser on Yoto's own login page (OAuth with PKCE, official Yoto developer API, https://yoto.dev). The
  program keeps only a refresh token in yoto-token.json and never sees your password. It only reads your Yoto account.
- A card itself holds no audio; the audio lives in your Yoto account, which is why the player (or your playlist list) is asked
  rather than the card. Yoto keeps the audio as Opus, so the disc gets a copy of that, not of your original files.
- Files: yoto.py (sign-in, players, playlists, download, decode with runtime\ffmpeg.exe). Optional yoto-client-id.txt next to the token
  replaces the built-in public client ID.

Sending tracks to a Yoto card (Send to Yoto Card...)
- The reverse of Rip Yoto Card: copies the ticked tracks (or every track, if none are ticked) from the loaded disc to ONE NEW playlist in
  your Yoto account. Reading is the same as "Save to PC" (Hi-MD tracks are read directly; on a standard disc a saved copy or a recorder
  that can send audio back, the MZ-RH1, is needed). Nothing is written to the recorder.
- The sheet lists every track on the disc with tick boxes (the ones ticked on the main screen start ticked).
- The tracks are read as FLAC into a temporary folder, uploaded, converted by Yoto (to Opus) and either put in a NEW playlist you name,
  or added at the END of one of your existing playlists. When adding to an existing playlist nothing in it is changed or removed: a copy
  is saved first (yoto-backups folder), the playlist is read back and checked afterwards, and if the check fails the copy is put back.
  If that playlist is already on a card the new tracks appear there by themselves (no relinking). Nothing is ever deleted from Yoto.
  The one-time sign-in asks for the extra "manage content" permission (an older sign-in is asked again).
- The last step is in the Yoto app on your phone: Make Your Own -> Playlists -> the playlist -> link it to a blank MYO card and tap the
  card. The card itself can only be written by the phone app (NFC), not from the PC.
- Verified: two tracks from a Hi-MD disc went up and played on a Yoto Mini; the in-app path was then built on the same calls.

Ripping an audio CD (Rip CD...)
- Copies an audio CD from this PC's CD / DVD drive onto the disc in the recorder (either kind of disc). The sheet lists the CD's
  audio tracks with tick boxes, editable titles and artists, an album title and album artist, and the recording format (Hi-MD:
  PCM, MP3 at 128 to 320 kbps, ATRAC3 LP2 / LP4, ATRAC3+ Hi-SP 256 / Hi-LP 64 / 352 kbps; standard disc: SP, LP2, LP4). A line shows how much
  of the disc the choice takes (it will not start if it does not fit) and how much temporary space the rip needs on the PC
  (about 10 MB a minute, deleted afterwards).
- Reading the CD: done by cdrip.py with Windows' own disc calls (no extra program, no admin rights). Every chunk of 24 sectors is
  read twice and compared, and read again until two reads agree; a sector that cannot be read becomes silence and one that never
  reads the same twice is kept but counted, and the end of the job says so ("wipe the CD and rip it again if it matters"). This is
  a careful ripper but not a forensic one: there is no check against other people's rips (AccurateRip). Mixed-mode / enhanced CDs:
  only the audio tracks are offered.
- Titles: if the CD carries them (CD-Text) they fill the sheet at once. "Look up online" asks MusicBrainz (free, needs the internet;
  only the disc's track lengths are sent) by the disc's ID: an exact match fills the sheet; if there is no exact match, MusicBrainz
  can offer albums with similar track lengths, but those are only suggestions: each is shown with how far its track lengths are from
  this CD, one more than about 3.5 seconds off is flagged "may be another album" and asks before it is used, and nothing is ever
  applied without a click. "Search by name" finds an album from the artist and title typed in. Everything stays editable. On a
  Hi-MD disc a front cover found at the Cover Art Archive can be stored as the disc picture (a tick box).
- The album title can become the disc's name (a tick box, on by default only when the disc is empty and has no name already).
- After the tracks are written the sheet reports any re-reads or unreadable sectors. The tracks are added by the same code as "Add
  tracks" (so on a standard disc the app also keeps its FLAC copies for playback). Cancel works while ripping, not while writing.
- Online data: radio-browser.info (station list for internet radio; community-run, free to use). MusicBrainz (core data CC0) and the Cover Art Archive (cover images belong to their owners; fine for your own copy).
  The app identifies itself as "MiniDiscManager/0.9 (personal use)" and keeps to MusicBrainz's one request per second.

Track list on the disc (Hi-MD discs only)
- Tick "Keep a track list on the disc" (Copy out group; off until you tick it, and remembered) and the program stores the track list
  on the disc as TRACKS.CSV in the root folder, next to the disc picture (COVER.JPG). It has the same columns as Export CSV: number,
  title, artist, album, group, codec, kbps, length in seconds. It opens in Excel and similar programs.
- It is brought up to date whenever the disc is read again after a change: after adding, deleting, renaming, moving, splitting,
  combining or undoing, and when you load a disc whose list is missing or out of date (for example after you recorded on the recorder
  itself). Nothing is written when the list on the disc is already right.
- Writing it is the same careful step as the disc picture: the start of the disc's file system is copied to
  backups\tracklist_latest first, then the disc is read again and checked (every other file unchanged, no shared clusters, both copies
  of the FAT equal, the list reads back identical). The file takes one 32 KB cluster. The recorder ignores it.
- "Open track list" copies TRACKS.CSV from the disc to a temporary folder and opens it. Changes made in the spreadsheet are not
  written back to the disc. Unticking the box stops updating but leaves the file on the disc.
- Standard (NetMD) discs have no file system, so this is not offered for them.

Recording from Bandcamp (Add tracks from Bandcamp...)
- Opens bandcamp.com in a second window (a small bar at its bottom right has Back / Forward / Home). Log in there as you
  normally would (the login is remembered between runs; sign-in with a password works best, "Sign in with Google / Apple" pop-ups
  may not). Play any track or album in that window; this window's sheet lists each track as it is recorded.
- It is a real-time recording of what the page plays, not a download: a 4-minute track takes 4 minutes. Only the Bandcamp
  window's own sound is captured (Windows "process loopback", helper\appaudio.exe, Windows 10 2004 or Windows 11), so notification
  sounds and other programs are not mixed in; you can mute the PC's speakers and it still records. The player in the main window
  is stopped when the sheet opens, because it would be recorded too.
- A track counts as complete (a tick) only if it plays from its start to its end. If you pause, seek or skip, or close the
  window, what was recorded so far is kept as a partial track (a half-circle, with a note saying how much of it was recorded)
  and can be added to the disc like any other; changing the speed marks the track "incomplete" and discards it. Titles, artist, album and album picture come from the Bandcamp page and can be edited before
  adding. Albums that play on by themselves are cut at each track's end, so gapless albums split cleanly; a cut can be a few
  milliseconds out. Keep Bandcamp's own volume slider at maximum (the track is flagged if it was lower). The sound is Bandcamp's
  stream (128 kbps MP3, or what the page serves), so a download you have bought is better quality when you have one.
- Tick the tracks to add, choose the format and press "Add ticked tracks to the disc"; they are written by the same code as "Add
  tracks" (Hi-MD: PCM, MP3, LP2 / LP4, ATRAC3+; standard disc: SP, LP2, LP4). The disc title (filled in as "Artist - Album" from the page; edit it if you like) and the album picture (Hi-MD) are
  optional ticks. Recorded tracks, added or not, are kept in %LOCALAPPDATA%\MiniDiscManager\recordings (about 10 MB a minute), so a track that
  does not fit can wait while you add the others; they are deleted when the program is closed, or earlier with "Remove ticked".
- Only record music you are entitled to copy for your own use; Bandcamp's terms of use apply to its streams.

Recording from SoundCloud (Add tracks from SoundCloud...)
- Works exactly like Bandcamp above, with soundcloud.com in the second window (same Back / Forward / Home bar, same sheet,
  same formats and the same rules: real time, only that window's sound, complete only if played from start to end).
- Log in to your own SoundCloud account in the window (the login is remembered). Titles, artists and artwork are read from
  SoundCloud's player bar at the bottom of the page and can be edited before adding; SoundCloud tracks have no album name, so
  the disc title is only filled in if you type one.
- Without SoundCloud Go+, some tracks play only a 30-second preview, and that is all that is recorded. Keep SoundCloud's own
  volume slider at maximum.
- Only record music you are entitled to copy for your own use; SoundCloud's terms of use apply to its streams.

Recording internet radio (Add tracks from Internet Radio...)
- No browser window: the program reads the station's stream itself (radio.py) and uses runtime\ffmpeg.exe to turn each song into a
  WAV. Nothing else the PC plays is involved, and the PC's speakers are not used.
- Search the station directory radio-browser.info (free, community-run; stations are listed most-listened first) by name, genre or
  country, pick a station and press Record. Pressing Stop (or closing the program) ends it; closing the sheet does NOT, so the
  recording carries on in the background until you open the sheet again and press Stop.
- Favourites: with a station selected, "Save as favourite" keeps it in a list (a star marks saved stations in search results too).
  Choose "Favourites" in the search type to see the list at once, with no internet lookup; it also opens first whenever you have
  any. "Remove from favourites" takes one out. The list is kept between runs in %LOCALAPPDATA%\MiniDiscManager\radio-favourites.json.
  If a saved station's stream address has stopped working, the program asks the directory for the station's current address,
  uses it and updates the saved entry.
- Song by song: most stations are Icecast / Shoutcast streams (MP3 or AAC) that announce "Artist - Title" inside the stream. The
  audio is cut exactly where the announced title changes and the song is named from it ("Artist - Title"; edit if the split is
  wrong). The song that was already playing when you pressed Record is kept as a partial track (not ticked), and so is the one
  playing when you stop. Songs shorter than 25 seconds, and tracks whose title is just the station's name, are probably jingles
  or announcements and are not ticked. Stations announce titles a little early or late, so a song can start with a second or two of
  the previous one, and talk, jingles and adverts are recorded too: untick what you do not want.
- One recording of a chosen length (1 to 120 minutes): used for streams that send no titles or are not MP3 / AAC (Ogg, FLAC, HLS);
  the program offers it automatically for those. It is one track named after the station and the time, which can be added to the
  disc as it is. Stopping early keeps what was recorded.
- It is a real-time recording: 4 minutes of radio take 4 minutes. If the connection drops the program tries again three times.
  Recordings are kept like the others (in %LOCALAPPDATA%\MiniDiscManager\recordings, about 10 MB a minute, deleted when the
  program closes). There is no album picture, so the disc picture option is not offered.
- The station directory is only contacted when you search or start a station (the program also tells it which station you
  played, as radio-browser.info asks of players). Only record what you are entitled to copy for your own use; each station's terms apply.

Converting a standard disc to Hi-MD (Convert to Hi-MD...)
- For a standard (SP / LP) disc in a recorder that also uses Hi-MD (MZ-NH700, MZ-RH1 and so on). When such a disc with audio is
  loaded, a note appears under the Recorder card saying the disc can be used as Hi-MD (nothing opens by itself; "Hide for this
  disc" hides it for that disc; the Settings button in the top bar switches it off); the Convert SP Disc to Hi-MD button in the Disc Conversion card does the same at any time. Pre-recorded commercial
  discs and write-protected discs are not offered.
- Choose the format the tracks are written back in: Hi-SP (ATRAC3+ 256 kbps, the default), Hi-LP (64 kbps) or PCM (lossless). The
  sheet shows the size of each against about how much the disc holds as a Hi-MD disc (an 80-minute disc: roughly 300 MB). Hi-SP and
  Hi-LP are a re-encode of the SP / LP audio and sound very slightly different. If the program still has the original file of a
  track from when it added it to the disc, that is used instead of the disc's SP audio.
- Steps: (1) every track is copied to %LOCALAPPDATA%\MiniDiscManager\convert as FLAC, with its title, artist, album, the groups
  and the disc name; each file's playing time is checked against the disc. If any track cannot be read back (a recorder that cannot
  send audio back and has no download for it) the job is refused and the disc is not touched; nothing is ever erased before all
  tracks are safe on the PC. (2) The disc is erased and set up as Hi-MD (the recorder switches mode and reconnects, about a minute).
  (3) The tracks are written back, the groups and disc name are put back, the disc is read again to check the track count and
  lengths, and only then is the PC copy deleted. If anything goes wrong the PC copy is kept and the program offers to write it again
  whenever an empty Hi-MD disc is loaded ("Write the saved tracks to this disc?"), also after closing the program.
- This app cannot turn the Hi-MD disc back into a standard-format disc; the recorder's own menu can (it erases the disc).

Converting LP2 / LP4 tracks to SP (Convert LP to SP..., "Convert LP2/4 Disc to SP")
- Players without LP support (many from the 1990s) play an LP2 or LP4 track as silence. When a standard disc with LP tracks is loaded, a note
  appears under the Recorder card (nothing opens by itself; "Hide for this disc" hides it, and the Settings button in the top bar switches
  it off); the same Convert LP to SP button is in the Disc Conversion card (title: Convert LP2/4 Disc to SP). Pre-recorded and write-protected discs are not offered.
- The window lists the LP tracks with tick boxes. SP takes 2 times (LP2) or 4 times (LP4) the room, so not every track of a full disc fits:
  the ticks start on as many tracks as fit, in disc order, and a line shows how much SP time the disc has and what would be left.
- Step 1: every ticked track is copied to this PC as FLAC (from the program's saved copy, straight from an MZ-RH1, or with the opt-in
  experimental download on an MZ-NH700, which then needs the cable unplugged and plugged in again), and each copy is checked against the
  disc's playing time. Nothing on the disc changes until all are safe. Step 2: each track, one at a time, a copy of the LP audio goes to
  Saved copies, the SP version is written (next to the original, or, when the disc is too full, after the original was deleted), the disc's
  track list is read back and checked, the SP track is put in the original's place and the LP original is removed. Titles, artists and
  albums stay. If something fails after an original was deleted, its audio is kept in the rescue folder and in the PC copy. Tracks already
  converted stay converted if a later one fails or you press Stop.
- Spread over two discs: LP2 / LP4 holds twice or four times as much music as SP, so a well-filled LP disc does not fit back as SP. Tick
  "Spread over two discs" (it starts ticked when nothing fits on one). The ticked tracks in disc order that fit stay on this disc and are
  converted in place; the rest are copied to this PC, removed from this disc first (which also frees the room), and kept as SP-ready audio
  until you insert a second standard disc. A note under the Recorder card (also after the program is closed and opened again) offers to
  write them; they are added as SP after anything already on that disc and the PC copy is deleted once the disc's track list shows them
  all. The second disc must have room for them (an 80-minute disc holds 80 minutes of SP); more than one disc's worth cannot be spread.
- SP is made by the recorder from the decoded sound, so there is one more generation of small quality loss; it does not improve an LP track.
- Not done on a disc with named track groups, on mono LP tracks, or on a write-protected disc.

Cloning a disc (Clone disc...)
- Works on a Hi-MD disc (to another Hi-MD disc) or a standard disc (to another standard disc); the sheet follows whichever disc is
  loaded. Before anything is read, the sheet lists every track with a tick box (all ticked): untick the ones you do not want on the
  copy. Skipped tracks are not read at all (so it is faster), the numbering closes up, and the groups are adjusted: a group
  keeps only its remaining tracks and disappears if none are left. A running line shows how many tracks, how much time and how
  much space on this PC the choice needs.
- Hi-MD to Hi-MD. Copies every chosen track exactly as stored, whoever put the tracks there (recorded on the
  recorder, added by this app, or put there by other software). Nothing is decoded or re-encoded, so there is no quality loss:
  PCM tracks are copied as WAV, ATRAC / ATRAC3+ tracks as their raw frames with the track's own codec fields, MP3 tracks as
  their MP3 frames. Track titles, artists, albums, the groups, the disc name and the disc picture come across too. The tracks keep
  their order. Recording dates are not carried over.
- Steps: (1) "Copy this disc to the PC" reads all tracks into %LOCALAPPDATA%\MiniDiscManager\clone (outside OneDrive; the sheet checks
  there is room). Nothing is written to the source disc. (2) Swap the discs in the recorder, press "Check the disc". (3) "Write the
  copy to this disc" writes the tracks, then the groups, disc name and picture, then reads every track back from the new disc and
  compares its audio byte for byte with the PC copy. Only when everything matches is the PC copy deleted. If anything fails
  the PC copy is kept and the sheet says what state the disc is in; format the disc and try again.
- The destination must be a different disc (checked by the disc's own ID), empty, and big enough. If it is not empty, or cannot be
  read as a Hi-MD disc, the sheet offers "Erase and format this disc" (type FORMAT to confirm). If it is a standard MiniDisc in a
  Hi-MD-capable recorder it offers "Erase and set up as Hi-MD" (the recorder switches to Hi-MD mode and reconnects; an 80-minute
  disc then holds about 300 MB). A disc too small even when empty is refused without offering to format it. To use a standard
  disc as the destination on an MZ-RH1, plug the recorder in with that disc already inside.
- The saved copy survives closing the program. Clone disc... then offers "Write it to a disc..." or "Discard the saved copy".
- Hi-MD limits: a PCM track longer than 56 minutes is refused (the helper holds a track in memory while writing it); needs free
  space on this PC about equal to the used space on the disc. A full disc takes a good half hour end to end (an 87 MB disc took
  about 2.5 minutes to read and 5 minutes to write and check).
- Standard disc to standard disc (SP, LP2, LP4). Reading: each chosen track is read from the disc as the recorder sends it (SP as
  ATRAC1 .aea, LP2 / LP4 as ATRAC3 frames in a .wav) and kept in the PC copy; an MZ-RH1 reads the official way, an MZ-NH700 (and
  other Hn / Hr 1.x Hi-MD recorders) needs the opt-in "experimental download" (a checkbox on the Clone sheet, same firmware patch as
  Save to PC; unplug and replug the recorder afterwards). Each track is decoded once to check that its length matches the disc.
  Writing: onto an EMPTY standard disc, in any recorder that is in standard-disc (NetMD) mode, so plug the recorder in with the
  disc already inside; it can be a different recorder from the one that read. LP2 / LP4 tracks go back as exactly the same
  ATRAC3 frames, with no loss. SP tracks cannot be written as SP data: the audio is decoded and sent as PCM and the destination
  recorder encodes it as SP again, which is one more generation of ATRAC loss (rarely audible). A mono SP track becomes stereo SP
  (twice the space). The disc name and the groups come across by copying the disc's raw title (rebuilt when tracks were skipped).
  If the destination is not empty the sheet offers "Erase this disc" (type FORMAT); a disc too short for the copy is refused;
  a recorder in Hi-MD mode is told to be replugged with a standard disc in.
- Standard-disc checking: most recorders cannot send a standard disc's audio back, so the new disc is checked by its track list
  (number of tracks, titles, SP / LP2 / LP4, lengths to within 2 seconds, the disc name and the groups), not byte for byte. Play
  the new disc on the recorder to confirm it. The PC copy is deleted only when that check passes.
- Standard-disc limits: mono LP is refused; titles are plain ASCII (as elsewhere for standard discs); writing SP runs at about
  twice the speed of playing (689 seconds of audio took 371 seconds), reading with the NH700 patch about 6 times faster than
  playing (a 75-minute disc in 748 seconds); a stopped write leaves the recorder reporting an "unknown" state until it is
  unplugged and plugged back in with the disc inside (wait for it to finish reading the disc before writing again).

Moving tracks (Move...)
- Tick one track, press Move..., type its new position (the sheet previews its neighbours). Only the order changes; the audio is
  not touched, and the tracks in between shift by one.
- Hi-MD: only the track-order table and the group ranges are edited, the same kind of change as a rename. A copy of the old
  index is saved first and "Undo last change" puts the old order back. A track that lands next to or inside a group joins it
  (a group's tracks must stay together); the only track of a group cannot be moved into the middle of another group.
- Standard disc: uses the recorder's own move command, then reads the track list back and checks the new order. Not done on
  discs that have track groups (their ranges would have to be rewritten into the disc title).

Splitting and combining tracks (Hi-MD discs: PCM and ATRAC tracks)
- A track cannot be cut or joined on the disc itself (each track's audio is encrypted with a key of its own), so the app writes
  NEW tracks and leaves the originals alone. When it finishes you choose "Keep the original(s)" or "Delete the original(s)...",
  which opens the normal delete sheet. Nothing is ever deleted automatically.
- Split: tick one track and press Split.... The app first copies the track to this PC (once; nothing is written to the disc),
  then shows a waveform. Click or drag on it to put the cut where you want it (the orange line; the white line is where it is
  playing). Quiet gaps show as flat parts. Play, "From 2 s before", the -1 s / -0.1 s / +0.1 s / +1 s buttons, "Move point
  here (playing position)" or a typed time help you place it. "+ Add split point" adds another cut (at the playing position if
  there is room, else in the middle of the longest part), so one long track can become many; click a numbered line, or its
  numbered button, to choose which point you are moving, and "Remove this point" joins two parts again. Up to 30 points
  (31 tracks) at once. Name the parts; they are placed right after the original, in order. Each part must be at least
  2 seconds long.
  When the new tracks do not fit: if the disc has no room for the new tracks next to the original (for example a 74 minute track on
  a nearly full disc), the sheet offers "Save the new tracks...". They are first cut and saved on this PC (in
  %LOCALAPPDATA%\MiniDiscManager\split, so they survive closing the program). Then you are asked, with a tick box, to confirm that the
  original will be deleted from the disc; the new tracks are written into the space it frees, read back from the disc and compared
  byte for byte with the saved copy, and placed where the original was. The saved copy is removed only after that check passes. If
  anything fails after the original has gone, the saved tracks stay on this PC and the program offers to write them again the next
  time it opens a disc or when you press Split.... The original is only ever deleted when the new tracks do not fit: if there is
  room, it stays on the disc. A different disc, or no room even after deleting, is refused before anything is deleted.
- The Split window works on a copy of the track in the Windows Temp folder (folders named mdm-split-...). The copy is removed when
  you finish or dismiss the window or close the program, and any a crash or an outside close left behind are removed the next
  time the program starts.
  Zoom: turn the mouse wheel over the picture to zoom in or out around the pointer (Shift + wheel moves along), or use the
  Zoom buttons (In, Out, Zoom to the point, Show all); the strip under the picture shows the whole track and the part on
  show, and can be dragged. Zoomed in, time marks appear along the picture and the point can be moved in 0.01 s steps;
  the times are shown to the millisecond. Playing while zoomed makes the picture follow the playing position.
  Size: the Split window opens wide. Drag the corner handle at its bottom right to make it larger or smaller (it grows from the
  centre), or press "Full window" to fill the program window and "Normal size" to go back. The waveform is redrawn sharply
  at whatever size you choose, and the size is remembered for next time.
  Find quiet gaps: press "Find quiet gaps..." to search the track for places where the sound drops away, such as the gaps
  between songs on a long recording. Choose how quiet (digital silence, or -60 / -50 / -40 dB) and for how long (0.3 to 3 s), and
  press "Search the track" (a few seconds, done on the PC copy). The gaps found are listed and shaded on the waveform; "Listen"
  plays each one from 1.5 s before it, untick any you do not want, then "Add the ticked gaps as split points" (a point goes in the
  middle of each gap, next to the points you already have) or "Use only the ticked gaps" (replaces your points). Gaps closer than
  2 s to the start or end are left out, and the 30-point limit still applies.
- Combine: tick two or more tracks of the same kind (all PCM, or all ATRAC with identical settings), as many as you like. The sheet
  lists them in the order they will be joined (it starts as the disc order); the up / down buttons change it, "Reverse" flips it
  and "Disc order" restores it. They are joined in that order, with no gap, into one track placed after the last of them. The
  new name follows the first track in the list unless you type your own.
- Trim: in the Split window every part has a tick box. An unticked part is shaded red and is NOT written, so splitting with the
  first and last parts unticked trims dead air off a track. "Suggest trim" finds silence at the very start and end (judged
  against the track itself, as "Find quiet gaps" does), sets the cut points and unticks the outer parts, keeping 0.25 s of lead-in
  and 0.5 s of tail. You can still move any point, listen, or tick a part back on. A kept part must be at least 2 s long; at
  least one part must be kept; with one part kept the new track keeps the original's name and the sheet asks "Trim this track?".
- The Split and Combine windows, and the confirmation sheets after them, can be moved by dragging their title. A click outside
  them no longer closes them (use Cancel), and the next one opens where you left the last.
- PCM tracks: cut or joined to the sample (a cut snaps to a 64-byte unit, 0.36 ms: Hi-MD stores PCM in 64-byte units and drops
  a partial unit at the end of a track, so a cut anywhere else would shorten both parts). Written as new PCM tracks, up to
  600 MB (about 57 minutes) each.
- ATRAC tracks (ATRAC3+ and ATRAC3, 44.1 kHz): the sheet offers two ways:
  * Lossless (recommended): the decrypted ATRAC frames are cut or joined at a frame boundary and written back unchanged with
    the original's own codec settings. Nothing is decoded or re-encoded, so there is no quality loss and it is fast. The cut
    falls on a frame (about 46 ms for ATRAC3+, 23 ms for ATRAC3). The first frame of the second part decodes without the
    previous frame's overlap, so its first 46 ms (23 ms) can sound distorted; everything before the cut is exact. Choose a quiet
    spot. Two tracks that were split apart rejoin exactly. Joining needs identical ATRAC settings (the app refuses otherwise).
  * Exact, as PCM: the track is decoded and written as lossless PCM, so the cut is exact to the sample, but the new tracks are
    several times larger (about 5 times for 256 kbps ATRAC3+).
- Safety: before anything is written the app checks the free space on the disc and on this PC's temporary drive. After writing it
  checks that every existing track is unchanged, that the new tracks are as expected, and then READS EACH NEW TRACK BACK from
  the disc and compares it byte for byte (PCM samples, or ATRAC frames) with what was written. If any check fails you get a message
  and the originals are untouched. A split can be cancelled until writing starts. For a long track it takes several minutes
  (read, write, read back).
- The split editor's temporary copy of the track is removed when you finish, cancel, or close the app.

Editing details, moving by dragging, and the catalogue (Hi-MD discs)
- Edit details...: tick tracks, tick "Set artist" and / or "Set album", type the text, Apply. All the ticked tracks are changed in
  one write (the same safe path as a rename, with a backup the Undo button can restore). An empty text removes that detail.
- Album column: the track list shows each track's album. Double-click it to edit. Standard discs have no albums (greyed).
- Column sizes: drag the right edge of a column heading to resize it; sizes are remembered. "Reset columns" (or a double-click on
  a column edge) goes back to automatic widths.
- Drag to move: drag a track by its number to a new place. Ticked tracks move together, in their order. Standard discs move one
  track at a time. Only the track order changes.
- Disc catalogue...: every disc the program loads, Hi-MD or standard (SP / LP), is remembered in %LOCALAPPDATA%\MiniDiscManager\catalogue.json
  (title, tracks, lengths, and artists / albums for Hi-MD discs, when last seen). The button above the track list searches them all
  without the disc (a box beside the search shows only Hi-MD or only standard discs); "Forget" removes one. A standard disc has no
  serial number, so it is recognised by its track count and lengths: a rename updates its entry, tracks this program adds, deletes or
  moves make the changed disc replace its old entry, and a different set of tracks is a new entry. Blank discs are not kept.
  Nothing on a disc changes. Floating windows (the catalogue, the split editor, ...) have an X at the top right as well as a Close button.
- Kept reads: on an MZ-NH700 a track read back with the experimental download (for Identify or Split) is also kept as a saved copy, so Combine, Split and Identify can use it without reading the disc again; this is how Combine becomes available there for tracks the program did not write itself (identify or open Split on each track once, then tick them and Combine). 'Read from the disc, not the saved copy' replaces such a copy with a fresh read.
- Saved copies...: when the program adds a track to a standard disc it keeps a FLAC copy in %LOCALAPPDATA%\MiniDiscManager\copies, so
  Identify, split and combine need not read it back. A copy goes when you delete the track here, rename follows it, and formatting
  a disc removes the copies of the tracks it erased. The Saved copies... button lists the leftovers (tracks that are no longer on the disc
  in the recorder, for example removed on the recorder itself) and removes the ones you tick. Only files on this PC are deleted.

Splitting and combining on a standard disc (SP / LP2 / LP4)
- A standard disc has no command to cut or join a track (the recorder's own front-panel Divide / Combine edits the disc's table of
  contents, which the PC protocol cannot do), so the app does it on the PC: it reads the track back, you cut it in the same split editor
  (or tick two or more tracks of one recording mode and press Combine), and the new tracks are written to the disc and moved next to
  the original. Trimming dead air with the Keep ticks works the same way.
- Reading back: an MZ-RH1 sends tracks back directly; an MZ-NH700 (or similar Hi-MD recorder in standard-disc mode) needs the opt-in
  experimental download (the app asks once) and reads one track per run, so a combine there needs tracks the app saved copies of; a
  track the app added earlier is read from its saved copy.
- Quality: the recorder encodes the sound again (SP is encoded by the recorder itself; LP2 / LP4 are encoded on the PC), so each new
  track is one generation further from the original: small, but not zero. Nothing can be read back byte for byte from a standard disc,
  so the check is the disc's track list (the new tracks are there with the lengths that were written). Writing takes about as long as
  the audio plays.
- Room: the new tracks are written while the original is still on the disc, so the disc needs free time for them (the confirmation
  says how much). Stereo SP, LP2 and LP4 only. Your originals are never deleted by the app until you say so. On a disc with groups the
  new tracks stay at the end (the move is not supported there). Use the recorder's own Divide / Combine when it can do the job: it is
  lossless and instant.

Auto split & name (standard discs)
- Tick one long track and press Auto split & name... (in the Identify group). The track is read to this PC, then the usual split editor opens with
  the cuts already suggested: the gaps between songs (the "Automatic" level, 1 s or longer) become split points and dead air at the start and end
  is trimmed (those parts are shaded red and not written). Check and adjust the cuts, then Continue. After the tracks are written the Identify
  window opens and starts listening by itself (the new tracks' audio is already on this PC); tick the names you want and Apply names.
- No room next to the original (a full disc): the plan window offers to delete the original FIRST. Before anything is deleted the app saves a copy
  of the whole original on this PC (FLAC, Saved copies) and checks its length against the disc. Then it deletes the original, writes the new tracks,
  checks the disc's track list and puts them where the original was. If writing fails after the delete, the cut parts are kept as WAV files in
  %LOCALAPPDATA%\MiniDiscManager\rescue\<date-time> (with ABOUT.txt); drag them onto the disc with Add tracks from PC. The copy of the original
  stays in Saved copies until you remove it. When the new tracks fit next to the original, the original is never deleted.
- Time: about the length of the track to read it (MZ-NH700: experimental download) and again to write it.
Fade & level (Hi-MD discs: PCM and ATRAC tracks)
- Tick one or more tracks of the same kind and press Fade & level.... Choose a fade in and / or out (0 to 30 s each) and a volume
  setting: "as loud as it can be without distorting" (each track's peak at -1 dB), or "even out the ticked tracks" (all brought to
  the same average volume; nobody is boosted past -1 dB peak, so a very loud track is not pushed into distortion).
- Like Split and Combine it writes NEW tracks (same name, artist and album; placed after the last ticked track), reads each back from the
  disc and compares it byte for byte, and leaves the originals until you choose to delete them. The sound is processed by the bundled
  ffmpeg on this PC. ATRAC tracks are decoded first, so their new tracks are lossless PCM (about 5 times larger).

Naming tracks: the Identify group (Hi-MD and standard discs)
- Tick tracks in disc order and press one of the three Identify buttons. Each opens its own sheet with only the fields it needs, then the names to check;
  press Apply names to save them (nothing changes on the disc before that).
  * Search for album...: search MusicBrainz by artist and album and choose the release (all its
    sides and discs are listed together; the ticked tracks are matched to it by length, starting where the lengths fit best, and a
    note under each track shows how far its length is from the album's).
  * Paste a track list...: for music no online service knows. Paste one song per line, in disc order, with its length if you have it
    ("1. First Song - 5:41"; bullets, numbering and blank lines are ignored). The songs are matched to the ticked tracks in order and
    each shows how far its length is from the track's. Optionally type an artist and album too.
  * Listen to the tracks...: see Identify by listening (below). Each track's names appear as soon as that track has been heard.
- A standard (SP / LP) disc stores only a title per track and a disc name, so it cannot hold an artist or album. The sheet can put the artist
  in front of each title ("Artist - Title") and name the disc "Artist - Album".

Artist and album on a standard disc (Edit details...)
- A standard disc has no artist or album field, so this PC remembers them for you: press Edit details..., type the artist and / or album and
  leave "Show them in the Artist and Album columns" ticked. Nothing is written to the disc; the columns show them (greyed when empty). They are
  kept in %LOCALAPPDATA%\MiniDiscManager\netmd-details.json (a disc is recognised by its track count and track lengths, and is still found
  when a few tracks have been added or deleted). Two optional tick boxes DO change the disc and cannot be undone on a standard disc: put the artist in front
  of the ticked titles, and name the disc "Artist - Album".

Auto split & name (its own group, Auto split & name)
- For one long track, such as a whole record side or a live set recorded in one go. SP / LP on a standard disc, or PCM / ATRAC (for example Hi-SP) on a Hi-MD disc.
  Tick the track and press Auto split & name.... The app copies the track to this PC (the progress line shows a percentage and about how long is left), looks for the
  quiet gaps between songs and any dead air at the ends (judged against the track itself), and opens the Split window with the cuts already placed.
- Check the cuts: click a split point's number to hear it (it plays from 2 seconds before the point). No song shorter than 2 minutes is made; press "- Shorter songs" /
  "+ Longer songs" if your songs are very short or very long (on a continuous mix with no real silence, the buttons are "- Fewer cuts" / "+ More cuts"). Move, add or remove any point.
- Press Continue: the new tracks are written (if the disc has no room next to the original, they are first saved on this PC and the original is deleted to make room,
  as described under Splitting and combining tracks) and the naming sheet opens, listening for each new track. If the music is not known to AcoustID, use Identify > Paste a track list.

When the recorder stops answering
- Very rarely a recorder stops answering in the middle of a step (the progress line stops changing and the recorder goes quiet). After a few minutes the sheet says so and shows what to do:
  wait a few minutes more; then close the program, unplug the USB cable, take the recorder's power adapter and batteries out for about 10 seconds, put them back, plug in the cable and start the program again.
  New tracks already saved on this PC are kept and offered again.
- If a Hi-MD disc then says "Fat backup invalid - filesystem damaged", the disc's file table was left half written (two copies that no longer match): the disc can still be read but not written to. Press "Format this disc..." in the message, then write the saved tracks.
- Progress lines: while a step runs, a bar moves and the line shows the percentage, about how long is left (for each track, and for all of them when there are several, with the clock time it should finish), or the time taken when no percentage is possible.

Identify by listening (Hi-MD discs; its own group, Identify)
- Tick tracks and press Listen to the tracks.... Each ticked PCM / ATRAC track is read from the disc, the first two minutes are turned into a Chromaprint
  fingerprint by the bundled ffmpeg, and only that fingerprint (plus the track length) is sent to AcoustID, which answers with likely
  titles, artists and albums and how sure it is. An AcoustID key is built in. You can also use your own free application key, kept in
  %LOCALAPPDATA%\MiniDiscManager\acoustid-key.txt (register at acoustid.org/new-application);
  a key you paste in is used in preference to the built-in one. Tracks from
  vinyl or tape are sometimes not recognised.
- Standard (SP / LP) discs: works on an MZ-RH1, which sends each track back to the PC, and on an MZ-NH700 (or similar Hi-MD recorder
  in standard-disc mode) with the opt-in experimental download (a tick box; the same temporary firmware patch Save to PC offers;
  unplug and replug the recorder afterwards). Reading takes about as long as each track lasts (the progress line shows about how long is left); several tracks can be ticked in one run, with a pause between reads; a track the app already saved is used at once. A saved copy is matched by title, length and recording mode (SP / LP2 / LP4), so a track re-recorded in another mode is read again; one changed without altering any of the three is not noticed, and the tick box 'Read from the disc again' listens to the disc instead. The same switch, 'Read from the disc, not the saved copy' (standard discs, under the Split / Combine buttons), makes Split and Combine read the tracks from the disc too; on an MZ-NH700 that needs the experimental download and one track per run, so Combine is greyed while it is ticked. A standard disc has no artist or album field, so the artist is put in front of the title
  ("Artist - Title", tick box, on by default) and a second tick box names the disc "Artist - Album". Other standard-disc
  recorders cannot send audio back. A Hi-MD disc works in any Hi-MD recorder, including the MZ-NH700.
- Checks you can rely on: the length of the audio read is compared with the disc's list for that track (a mismatch is reported as a
  possible wrong-track read and nothing is looked up), "Hear what was read" plays the first 45 s of what was read, and each suggestion shows
  the matched recording's length with a warning when it is very different.
- Both sheets: nothing is written until you press Apply names: every title, artist and album can be edited and each track unticked. The change is
  one write with a backup that Undo last change can restore.

Disc labelling (its own group in the Recording box, under the Add tracks buttons)
- Press Make disc label... to draw a sticker label for the loaded disc: the disc picture (Hi-MD discs only), album, artist and track list, as a
  portrait picture 2 x 3 inches (1000 x 1500 pixels), the size of an HP Sprocket sticker. Album and artist start from what is on the disc and can be
  edited; three tick boxes switch the album art, the disc title and artist, and the track list on or off. A long track list gets smaller type, then a smaller picture, then two columns,
  then "+ N more". Save as picture... writes a PNG; print it from the HP Sprocket app (copy it to your phone) or any printer. Nothing is written to
  the disc.
- Discs with groups: the label sheet then has a first box, Whole disc or one named group. Whole disc: "Group names as headings in the list" puts each
  group's name (bold, with a thin rule) above its tracks; tracks in no group are headed "No group". One group: the label takes that group's name as
  the title, its most common artist, the group's picture (Groups tab; the disc picture if it has none) and only its tracks, numbered from 1 unless
  "Number the group's tracks from 1" is off. Save a picture for every group... writes one PNG per group into a folder you choose. Only a
  whole-disc label can be stored on the disc.
  "Groups only (names and pictures)" draws a grid with one tile per group: its picture (a grey square with the first letter if it has none), name,
  and "N tracks · length" (the track-times tick switches the length), under the disc title and artist, with no track list. The grid uses the
  number of columns that gives the biggest pictures; the album-art tick switches the pictures off. It counts as a whole-disc label, so it can be
  saved to the disc.
- An Orientation box in the label sheet chooses Portrait (2 x 3 in) or Landscape (3 x 2 in, 1500 x 1000 pixels): in landscape the album art, title and
  artist are on the left and the track list is on the right. The choice is remembered. Sent to a Sprocket, a landscape label is turned a quarter
  turn (the printer takes portrait pictures), so read the sticker with the paper turned sideways.
- Send to Sprocket prints the label on a paired HP Sprocket (the older 2 x 3 inch models that take a Bluetooth file push, OBEX on RFCOMM channel 4;
  sprocket.py). Pair the printer once in Windows and switch it on; the program finds it. The label is sent as a 640 x 960 JPEG (under 45 KB), about
  5 seconds. The printer switches itself off when idle (a USB cable does not prevent it; the HP Sprocket phone app has a setting to keep it on): if it cannot be reached, press its power button. Tried on one printer only.
- Send to Hi-Print prints the label on a paired Polaroid Hi-Print 2 x 3 (hiprint.py). Pair it once in Windows (Settings > Bluetooth & devices) and switch it on. It
  can only talk to one device at a time, so close the Polaroid app on your phone (or turn the phone's Bluetooth off) first. The label is fitted to the printer's
  640 x 1024 picture with a little white above and below; a print takes about a minute. The program speaks the printer's own Bluetooth commands (worked out from
  the Polaroid app), tried on one printer only. The printer cannot report how many sheets are left, so the Film button keeps a count for you: click it, say how
  many sheets are in the printer now, and every print made here takes one off (prints made from your phone are not counted).
- The print buttons in the label sheet are grouped: "Print the label" (Sprocket, Hi-Print, Film), "Save the label" (picture, store on disc, remove) and Close.
- On a Hi-MD disc, Save to disc (Replace the label on the disc, if one is there) stores the label as LABEL.JPG in the disc's main folder, like
  COVER.JPG: the file table is backed up first (backups\label_<time>) and checked afterwards. The label then shows under the disc picture in Disc
  information (click it to see it larger, make a new one or remove it) and its size is listed with the other files. Standard discs cannot hold files.

Lyrics (its own group, Lyrics)
- Press Lyrics... to see the ticked tracks (or the whole disc when none is ticked), each marked Timed, Text only or None. "Find..." searches three free
  lyrics services for that track: LRCLIB (a community database of timed lyrics), NetEase Cloud Music (a very large catalogue, also timed) and lyrics.ovh
  (text only, no timing). It lets you pick the right match (each result shows its source, length and first lines). "Find lyrics for the ... without" does
  every track that has none and keeps only confident matches (same title and artist, ignoring "The" and "feat. ...", also a name cut short on the disc,
  with a length within 10 seconds); it says which it could not match. A later service is only asked when the earlier ones had no confident timed match.
  "File..." uses an .lrc file (timed lyrics) or a plain .txt file from your PC. Only the artist, title, album and length of a track are sent to the lyrics
  services, never the audio, and only when you press a button.
- "Listen..." is for a track no service knows: an optional speech recogniser (whisper.cpp with a 190 MB model) listens to the track on this PC and writes
  timed lines from the words it hears. The first time it downloads the recogniser once (about 200 MB: the program from the whisper.cpp project on GitHub
  and the speech model from Hugging Face); "Remove the recogniser" on its sheet deletes it again. You choose the language (or let it detect it). It works
  on any track with sung or spoken words, but it makes mistakes on loud music, can miss words and gives nothing for an instrumental; it takes a few minutes
  per track (on a standard disc each track is first read from the disc). Lyrics made this way say "made by listening, may contain mistakes" above the lines.
  The audio never leaves this PC.
- "Fine-tune timing..." (a button in the Lyrics sheet, and in the lyrics box while a track plays) fixes lyrics whose lines come early or late. Timed lyrics are
  timed for ONE recording of a song; your file may start later or be another master. The same optional speech recogniser listens to the first 100 seconds
  of each track (twice, with different settings), finds when the timed lines are really sung and sets the track's timing offset to match. The lyrics are not
  changed, only the offset (the player's nudge still works). A track is only changed when both listens agree, so a shift smaller than about half a second,
  which the recogniser cannot measure reliably, is left alone, and so is a track whose lyrics do not fit the singing (another version of the song); the
  sheet says which. It is off after "Find lyrics" by default because it takes a minute or more per track; run it when a track's lines are early or late, or tick "Do this automatically after Find lyrics" on the Fine-tune sheet to have it run by itself.
  It needs the same one-time download as Listen..., takes about a minute or more per track, and the audio never leaves this PC.- Tracks that have lyrics show a mark after their title: a coloured note (♪) for timed lyrics, which follow the music while the track plays, and a grey three-line mark (≡) for text-only lyrics, which show as plain scrolling text. While such a track plays here, its lines appear in a box in the Recording panel, the current line
  in large type; the note button in the player bar hides and shows the box. Lyrics without timing show as scrolling text.
- On a Hi-MD disc, "Save lyrics to the disc" writes ONE small file, LYRICS.TXT, to the disc's root folder (next to TRACKS.CSV and COVER.JPG), after backing
  up the disc's file table and reading the file back to check that nothing else changed. A disc that has it brings its lyrics to any PC running this
  program. A standard (SP / LP) disc cannot hold files, so its lyrics stay on this PC. A recorder itself cannot show lyrics.
- Wrong lyrics (for example a different edit of the song) can be removed with the "Remove lyrics" button at the top of the lyrics box while the track
  plays, or with the small cross beside the track in the Lyrics sheet. Both ask first and remove them from this PC only; on a Hi-MD disc the copy
  in LYRICS.TXT stays until "Save lyrics to the disc" is pressed again.
- A track is matched to its lyrics by title, artist and length, so after renaming a track find or load its lyrics again. The lyrics belong to their writers;
  use them for your own listening.
- Timed lyrics are also checked against the track: a timed version whose last line comes far too early (under about half way) or after the end of the
  track is an incomplete or different version and is not used, so the next candidate is tried. Some services still have lyrics timed for another edit of a
  song; if the lines drift, use Find... to choose another, Listen... to make them from the audio, or Remove lyrics.
- A disc title like "ARTIST - TITLE" with no artist stored (common on commercial and compilation discs) is understood: the part before the dash is
  used as the artist when looking lyrics up.

Pre-recorded (commercial) standard discs
- A standard MiniDisc bought pre-recorded reports itself as not recordable; the app notices this when the disc is read. For such a disc, the first
  time it is loaded, a pop-up "Pre-recorded disc detected" shows what is happening, and the line under the disc name keeps the result:
  1. The disc is looked up in MusicBrainz, by the disc name or, when that finds nothing, by its songs. A release is accepted only when most of its
     tracks match the disc's tracks by title and length (it says "17 of 18 tracks matched").
  2. The artist and album of the matched tracks are filled in (only fields that are empty) and remembered on this PC, as for Edit details, because a
     standard disc cannot store them. They show in the Artist and Album columns.
  3. The front cover is fetched (the Cover Art Archive picture of that release, else a title-matched one from iTunes or Deezer) and kept on this PC
     (disc-covers folder in %LOCALAPPDATA%\MiniDiscManager). It shows in Disc Information with the note that it is not stored on the disc; Remove forgets
     it. It is also drawn on the Google TV lyric video. "Find online..." can pick a different cover by hand, and "Look up online" repeats the whole lookup
     for any standard disc.
     If the automatic lookup finds nothing (a niche album), it also tries Discogs and compares titles loosely (brackets, "feat." and "The" are
     ignored, then the lengths too). "Search by hand..." (beside the disc picture) lets you type the artist and album, lists matches from MusicBrainz and
     Discogs, and fills the disc in from the one you pick. If its track names do not match but it has as many tracks as the disc, they are matched
     track for track. On a Hi-MD disc the artist / album are written to the tracks that have none and the picture is stored on the disc.
  4. Then the lyrics are looked up for every track that has none, with the same progress sheet as the Lyrics button.
- Nothing is written to the disc. Only the artist, album and track titles are sent (to MusicBrainz, the Cover Art Archive, iTunes / Deezer and the
  lyrics services), never audio, and only for a disc that reports as pre-recorded (or when you press a button). A disc that was found is not looked
  up again; one that was not found is tried again after 7 days. If MusicBrainz cannot be reached that is not counted as "not found".
- Hi-MD discs are not looked up automatically (their artist and album are written on the disc, so filling them in would mean writing to it).

Visualizer (top of the Disc Information panel, while a track plays on this PC)
- Choose the display: Spectrum bars, Mirror bars, Oscilloscope (stereo), Circular spectrum, Waterfall, and three stereo VU meters (needles, LED columns,
  bars), or Off. Colour (Accent, Rainbow, Fire, Ice, Green - red, White), Sensitivity and Peak marks can be changed while it plays; the choices are kept.
- The sound is only read, never changed (apart from the equalizer, below: the display shows the sound after it). It is not shown for a standard disc
  played on the recorder itself or on a Sonos speaker, because the program does not receive that sound.

Equalizer (the EQ button in the player bar, while a track plays on this PC)
- Opens in a small window of its own that you can drag around; the music keeps playing and the rest of the program stays usable. Close it with the
  cross or the EQ button; it keeps working while hidden.
- Ten bands (31 Hz, 62, 125, 250, 500, 1k, 2k, 4k, 8k, 16 kHz), each plus or minus 12 dB, and a Preamp. Double-click a slider to put it back to 0. A small
  curve shows the combined effect. Moving a slider or choosing a preset switches the equalizer on; "Equalizer on" switches it off to compare.
- Presets: Flat, Bass boost, Treble boost, Vocal, Rock, Classical, Loudness and MD warmth (softer highs). Type a name and press Save preset to keep your
  own; Delete preset removes one of yours.
- Auto headroom lowers the whole sound by the biggest boost so loud music cannot distort.
- Remembered per disc: with "Remember for this disc" ticked (the default), the settings you make are kept for that disc on this PC and come back
  when it is loaded again. A Hi-MD disc is recognised by its own ID; a standard disc by its number of tracks and their lengths, so adding or deleting
  a track makes it look like a new disc. A disc with no settings of its own uses the default settings (those changed while the tick was off).
- It changes only the sound played through this PC. Nothing is written to the disc, and it does not apply to a Sonos speaker, to a standard disc
  played by the recorder itself, or to the radio listen-along while recording.
Sound output of this PC and Bluetooth speakers (the "🔊" button in the player bar, then "Sound output & Bluetooth...")
- "This PC" plays through the sound output Windows has as its default. The sheet lists the outputs Windows has (speakers, headphones, a TV, a connected
  Bluetooth speaker) and switches the default to the one you pick. This is Windows' main output, so other programs follow it too. A Sonos room is still
  chosen in "Play on".
- "Find Bluetooth speakers..." uses this PC's own Bluetooth: it lists the audio devices Windows has already paired (Connect), and "Search for speakers"
  looks for new ones (about half a minute; put the speaker in pairing mode first). "Pair & connect" pairs it, opens its audio connection, waits for
  Windows to list it as a sound output and switches to it. Tick "Show other Bluetooth devices" if your speaker is not recognised as an audio device.
- The sound is still played by this PC, so the equalizer, the visualizer and the lyrics keep working. A Bluetooth link adds a short delay (about 0.1 to
  0.3 seconds), so lyrics and the visualizer may run slightly ahead of the sound. A standard disc played by the recorder itself cannot be redirected.
- If Windows asks you to confirm the pairing, or the speaker does not appear as an output, pair or connect it once in Windows Settings, Bluetooth &
  devices, then look in the output list again. Needs Windows 10 or 11 with a Bluetooth adapter. The app only asks Windows; nothing is stored on the disc.

Formatting a disc (Format disc...)
- Erases EVERYTHING on the disc. You must type FORMAT to confirm. There is no undo and no backup. Write-protected discs are refused.
- Hi-MD disc: sets the disc up again as an empty Hi-MD disc (the recorder's own reformat command, through himd-js).
- Standard disc: choose "Standard MiniDisc" (an empty standard disc) or, on a Hi-MD recorder, "Hi-MD". For Hi-MD the app erases the
  disc, switches the recorder into Hi-MD mode, waits for it to come back as a Hi-MD device (up to 90 seconds) and sets the disc
  up. An 80-minute standard disc holds about 300 MB in Hi-MD format. If a step fails the sheet says what state the disc is in:
  press rescan and use Format again (a disc that "could not be read" offers "Format this disc...").
- The app cannot turn a Hi-MD-formatted disc back into a standard one (no command for it is known; three guesses at the reformat
  command's flags changed nothing). Do that on the recorder itself: set its disc mode to MD and format the disc from its menu.

Playing to a Sonos speaker
- The player bar has a "Play on" button (shown as "This PC" until you choose). Press it to see your Sonos rooms - a stereo pair or a
  home-theatre set counts as one room, as in the Sonos app - and pick one. Remembered rooms appear instantly while a quick
  search (a couple of seconds) checks for changes. From then on, tracks you play go to that room instead of this PC.
- Play, pause, the seek bar and the volume slider control the room (the slider then changes the real speaker's volume, and starts
  at its current level), and when a track finishes the next one starts. Choose "This PC" to play here again.
- It works with Hi-MD discs and with standard discs (tracks the app added, or any track on an MZ-RH1). Tracks on a standard disc
  that the app cannot read back still play on the recorder itself (the remote control).
- How it works: the speaker fetches each track from a small web server the app runs on this PC's home-network address, behind a
  random secret in the address, and only while you are playing to a room. The speaker and this PC must be on the same network.
  The first time, Windows may ask whether to let the app on your network: choose Allow for private networks.
- Sending music to a room replaces whatever that room was playing (for example a line-in); start that again from the Sonos app.
- Closing the window stops the room, but only if it is still playing a track this app sent it; if you have since started
  something else on that room from the Sonos app, it is left alone.
- No packages are needed: the app talks to Sonos with the standard UPnP protocol (sonos.py). Remembered speakers are kept in
  %LOCALAPPDATA%\MiniDiscManager\sonos.json.

Playing to a Google TV (Chromecast built in)
- "Play on" lists Google TVs, Chromecasts and other Cast devices on your network next to the Sonos rooms, marked "(Cast)" - for
  example "65OLED705/12 (Cast)". Pick one and the tracks you play go to it. Play, pause, the volume slider (the TV's own volume,
  so it starts at its current level) and automatic next-track work as for a Sonos room. The volume slider follows your finger: each step is sent at
  once (the TV applies it in a fraction of a second but only confirms it after about a second), and when you let go the slider shows the value the TV took,
  since a TV rounds to its own steps. Choose "This PC" to play here again.
- A TV's built-in player can only show a title and a picture, so the app makes a LYRIC VIDEO for it: the disc's cover picture on the
  left, the title and artist, and the timed lyrics on the right with the current line large and the lines around it dim, over the
  track's audio. The video is made on this PC with the bundled ffmpeg while the TV plays it, so it starts after a few seconds, not
  after the whole track. A Hi-MD disc supplies the cover (COVER.JPG); a standard disc uses the album art found online and kept on this PC (see
  Pre-recorded standard discs), or shows a plain background when there is none. The artist and album are written in large type above the track title,
  the artist largest. A track with no timed lyrics shows just the cover, title and artist.
- The "Play on" window has a tick box to turn the video off: the TV then gets only the audio and its own simple player.
- The lyric offset you set for a track (in the lyrics panel) is used for the video as well. Skipping ahead inside a track on the TV may
  not work while the video is still being made.
- If the video cannot be made, the TV gets the audio only and the reason is written to app.log (lines starting "lyric video").
- Whole-screen alternative: Chrome on the PC can mirror its entire screen to the TV (menu - Cast, save and share - Cast - Sources -
  Cast screen), which shows the whole app; it runs about a second behind and is not controlled by the app.
- How it works: the app talks to the TV with the Google Cast protocol (chromecast.py, standard library only: a TLS connection to port
  8009 and the TV's built-in Default Media Receiver). It finds devices by probing your home network (a couple of seconds) and
  remembers them in %LOCALAPPDATA%\MiniDiscManager\chromecast.json. As with Sonos, the TV fetches the stream from a small web server
  this PC runs only while you play, behind a random secret in the address, and Windows may ask once to allow the app on private
  networks. A VPN that blocks the local network (for example NordVPN without "Allow LAN discovery") stops it from reaching the TV.
- Lyric-video technical notes (lyricvideo.py): 1280x720, 25 frames per second, H.264 (OpenH264) with AAC audio, sent as an HLS playlist
  of 2-second pieces kept in the temporary play folder and deleted when the track stops; the lyrics are drawn from a generated ASS
  subtitle file. The TV must be told the stream is a video (a "music track" makes it show only an audio screen) and 5 frames per second
  made one TV show the picture only briefly.

Saving tracks to your PC
- Tick the tracks you want (or tick none to save every track), press "Save to PC...", choose FLAC, WAV or MP3, and choose a
  folder. Files are named "NN - Title" and carry the title, artist, album and track number. The disc is only read.
- FLAC: lossless and compressed (about half the size of WAV) - the best choice for keeping a recording. WAV: lossless,
  uncompressed. MP3: small files; choose "high quality" (variable, about 245 kbps) or 320 kbps. A track that is already an
  MP3 on a Hi-MD disc is copied as it is when you choose MP3 (never re-encoded).
- Hi-MD discs: PCM recordings are decrypted on the PC (a 3-minute track takes about half a minute). ATRAC tracks are decoded
  to the chosen format, or, with "keep the original ATRAC data", saved unchanged as .oma files (most players cannot open
  these). A saved file has the track's true length, not padding.
- Standard discs: the app saves its own copy of the track if it has one (tracks it added). On an MZ-RH1 the recorder sends any
  other track back (SP and LP are decoded). The NH700 and other Hi-MD recorders cannot send audio back by themselves; for them
  there is an opt-in "experimental download" (next paragraph). SP, LP2 and LP4 tracks all come out as a normal FLAC, WAV or MP3
  in one step: the recorder's raw ATRAC data is converted as it arrives, so no .aea file has to be converted by hand.
- Experimental download (MZ-NH700 and other Hi-MD recorders with Hn / Hr 1.x firmware): when a standard disc's track has no saved
  copy, the Save sheet shows a checkbox, off by default, "Also read the tracks without a saved copy (experimental)". It uses the
  "ATRAC USB bulk transfer" firmware patch from the netmd-exploits library (GPL-2.0, by asivery and contributors). The
  patch is loaded into the recorder's RAM and patch registers only: nothing is written to the disc or to
  the recorder's permanent memory, the app removes it again when it finishes (one small patch stays until the recorder is
  unplugged), and unplugging and replugging the recorder clears everything. The app reads the firmware version first and
  refuses anything but Hn1.x / Hr1.x. A track is read at about 6 times real time (a 3-minute SP track in about 30 seconds). The
  recorder has to be plugged in with the standard disc already inside (so it shows up as NetMD). After saving, unplug and
  replug the recorder before using it for anything else.
- A progress bar shows each track, and Cancel stops straight away; tracks already saved are kept. When it finishes you can open
  the folder.

Burning an audio CD (Burn Audio CD...)
- Tick the tracks you want (or tick none for every track), put a BLANK CD-R or CD-RW in a disc writer on this PC, and press
  "Burn Audio CD...". The sheet shows the writer, the disc and whether the tracks fit; when it says Ready, press Burn. The result
  is an ordinary audio CD that plays in any CD player.
- The tracks are first read from the recorder's disc (like Save to PC) and nothing is burnt unless every track could be read:
  a CD-R can only be written once. Cancel works while the tracks are being read; once the writer has started it must not be
  interrupted, and the disc must not be ejected.
- It uses Windows' own burner, track by track: there is the usual 2-second gap between tracks and there is no CD-Text.
  Gapless playback and CD-Text are not offered.
- A CD-RW that is not blank can be erased from the same sheet (quick erase). A CD-R cannot be erased.
- Standard MiniDiscs: the audio can only be read back with an MZ-RH1 (or from a copy the program saved when you added the tracks);
  a recorder such as the MZ-NH700 cannot send audio back. Hi-MD discs can be read in any Hi-MD recorder.
- Every call to the disc writer runs in its own process with a time limit, so a writer that stops answering shows an error instead of
  freezing the program. If that happens, take the disc out of the writer and put it back.
- Tried so far on one Panasonic BD-MLT writer with CD-R discs only.

Saving tracks as files on a disc (Save to disc...)
- Tick the tracks (or none for all), choose FLAC, WAV or MP3, give the disc a name, put a disc in a writer on this PC and press
  "Save to disc...". The tracks go on the disc as files, with a TRACKS.CSV list.
- CD-R, DVD-R / DVD+R, DVD-RW / DVD+RW, BD-R and BD-RE are written as a finished disc (UDF; a CD also gets Joliet and ISO 9660)
  and need a BLANK disc. A rewritable disc that is not blank can be erased from the sheet. A -R disc can only be written once.
- DVD-RAM is used like a drive: the files are copied into a folder (named after the disc name) on a disc that is already
  formatted. The sheet shows the disc's free space and will not start if the files do not fit.
- The same safeguards apply: nothing is written unless every track was read, and the writer is called with a time limit.
- NOT yet tried on real discs (only the CD-R audio burn has been proven): treat the data-disc types as new.

Hi-MD discs
- Add: any audio the bundled ffmpeg can read (MP3, WAV, FLAC, M4A, OGG, AAC, WMA, AIFF). The "Add to disc" sheet lets you choose
  the recording format for all the files (your last choice is remembered):
  * Automatic: MP3 files are added as they are; everything else is added as lossless PCM (the default).
  * PCM: lossless, about 10 MB a minute (an MP3 converted to PCM keeps its MP3 quality).
  * MP3: files that are already MP3 are added unchanged; anything else is encoded to MP3 at 128, 192, 256 or 320 kbps
    (constant rate, by the bundled ffmpeg). About 1 to 2.4 MB a minute.
  * ATRAC3 LP2 (132 kbps, about 1 MB a minute) or LP4 (66 kbps, about 0.5 MB a minute): encoded on the PC first (an 80-minute
    file takes about half a minute) and limited to 90 minutes each.
  * ATRAC3+ Hi-SP 256 kbps (about 1.9 MB a minute), Hi-LP 64 kbps (about 0.5 MB a minute) and 352 kbps (about 2.6 MB a minute): see
    "ATRAC3+" below.
  The sheet shows what the chosen format needs and whether it fits. Other source formats are converted to 16-bit 44.1 kHz stereo
  first. A copy-protection session is used for everything except MP3 output.
- ATRAC3+: the PC encodes the track (atracdenc 0.2.3 in runtime\atracdenc3p, built for this program with one change: the new
  "framesize" option, because the stock program always wrote 2048-byte frames, about 352 kbps, and ignored the bit rate). Hi-SP is
  1488-byte frames (256 kbps), Hi-LP 376-byte frames (64 kbps) and the third option 2048-byte frames (352 kbps): the frame sizes the
  recorders use for their own Hi-SP / Hi-LP recordings. A minute of music took about 6 seconds to encode, and decoded with signal-to-noise
  ratios of about 32 dB at 352 and at 256 kbps and 9 to 16 dB at 64 kbps (Hi-LP is clearly the roughest). The program is run only if it and
  its sndfile.dll are byte-for-byte the files that were checked (SHA-256 in runtime\atracdenc3p\NOTICE.txt); it is not code-signed. The
  change is published as runtime\atracdenc3p\atracdenc-0.2.3-framesize.patch. The 352 kbps tracks the app wrote played correctly in the
  app and on the recorder; Hi-SP / Hi-LP are new (see Status). The app can also play and save ATRAC3+ tracks already on a disc.
- Also renames artists and groups. A copy of the old track index is saved in backups\ first, and "Undo last change" restores it.
- Sets the recorder's clock to this PC's time (asks first). It works on the MZ-RH1. The MZ-NH700 accepts the command but ignores it
  (it keeps reporting no valid time): set its clock from its own menu.
- Delete: a rehearsal runs first and the remaining tracks are checked afterwards. After a delete, Undo can no longer
  restore earlier renames (the saved indexes are moved to backups\retired-...).
- Find album art online (Hi-MD discs only, "Find online..." under the disc image): looks the album up by artist and album title in the Cover Art
  Archive (via MusicBrainz), iTunes Search and Deezer, and shows the covers it finds as pictures to choose from. The artist and album are filled in
  from the tracks (or from a disc name such as "Artist - Album"); correct them and search again if they are wrong. Click a cover to see it full size;
  it is stored exactly like a picture you chose yourself, and nothing is written until you press "Store on the disc". Only the artist and album words
  are sent, never audio. A standard disc cannot hold a picture, so it is skipped there.
- Disc image: the Disc Information panel has a picture box ("+ Disc image", then Change / Remove). Choose any picture (JPG, PNG,
  BMP, GIF, WebP or TIFF); the app shrinks it to a JPEG of at most 1024 pixels a side (usually 50 to 300 KB) and stores it on the
  disc as COVER.JPG in the main folder, beside HMDHIFI. The recorder ignores the file and the app shows the picture whenever the
  disc is loaded. A picture already there is replaced. Before anything is written the sheet rehearses the whole write in memory
  and checks that every existing file stays as it is; the real write then saves a raw backup of the disc's file-table area
  (backups\cover_*\volume_head.bin), re-mounts the disc and repeats the checks. Standard discs have no file system, so they
  cannot hold a picture.
- Play: PCM, MP3 and ATRAC. The track is read off the disc into a temp file while it plays (PCM is decrypted on the PC,
  ATRAC and MP3 are decoded by the bundled ffmpeg as they are read, so playback starts within a second or two); nothing is
  written to the recorder. Doing anything else that needs the recorder (rename, add, delete) pauses the read; press play to
  continue. Known limit: dragging the player's seek bar ahead of what has been read so far waits for the read to catch up (PCM is
  read at about twice real time), so it can stall; the Split editor avoids this by copying the track to the PC first.

Standard MiniDiscs (NetMD)
- Add: WAV, and anything ffmpeg can read (MP3, FLAC, M4A, OGG...). A mono or non-44.1 kHz source is converted first.
  The "Add to disc" sheet has a Recording format choice (your last choice is remembered):
  * SP: best sound, about 80 minutes on a disc. The PC sends the audio and the recorder encodes it to SP ATRAC itself,
    so adding takes about as long as the audio plays.
  * LP2: about twice as much music (160 minutes). LP4: about four times as much (320 minutes), at lower quality. The PC
    encodes the audio to ATRAC3 first (fast: an 80-minute file takes about half a minute) and then sends it, so a long
    track is sent much faster than real time. Sources up to 90 minutes can be encoded in LP.
  The sheet shows how much of the disc is free in the chosen format and warns if the files will not fit.
- Rename: track titles and the disc title only (a standard disc has no artist field). No undo and no clock setting.
- Delete: erases the track from the disc's table of contents. There is no rehearsal for this.
- Play:
  * Tracks the app added: the app saves a FLAC copy of every track it adds, in
    %LOCALAPPDATA%\MiniDiscManager\copies (outside OneDrive, about 5 MB per minute). Press play and it plays that copy
    through the PC, with seeking and volume. The copy is matched to the track by title and length, so two discs with a
    same-named track of the same length would share a copy. Renaming a track keeps its copy; deleting a track deletes it.
  * Other tracks on the MZ-RH1: the recorder sends the track to the PC and the app plays it.
  * Other tracks on other recorders (e.g. the MZ-NH700): standard NetMD recorders cannot send audio back, so the app acts as
    a remote control. The recorder plays through its own headphone output; the app shows the position and pause/seek work.
  * Other tracks on an MZ-NH700 (Hn / Hr 1.x Hi-MD recorders): just press play. The track is read with the same temporary firmware
    patch as the experimental download, decoded as it arrives and played here or on a Sonos room, with seeking and volume. SP,
    LP2 and LP4 all work the same way. The first sound comes after about 15 to 23 seconds (a fixed 10-second wait for the disc,
    the seek, and the first piece of the read); after that the audio arrives about 6 times faster than it plays, so there are no
    gaps, and a seek ahead of what has arrived waits for the read to catch up. The end of the track is padded with up to 3
    seconds of silence (the length is declared up front). Choosing another track or pressing stop ends the read in under 2
    seconds and the recorder is ready again. A small patch stays in the recorder's memory until it is unplugged and plugged back
    in (the app no longer says so; do that when you have finished). If the download cannot be used (for example the
    firmware is not one it has been checked on) the track plays on the recorder by remote control instead, with a message.
- Recorders recognised: about 46 NetMD models (Sony MZ-N, MZ-NE, MZ-NH, MZ-RH, Aiwa, Sharp, Kenwood, Panasonic). Only the
  MZ-NH700 and MZ-RH1 have been tried. The recorder needs the WinUSB driver (the app does not install drivers).
  If two NetMD recorders are connected, the first one found is used: connect them one at a time.

What it does not do
- Change menu settings (record mode, backlight, beep...). No documented command exists.
- Turn a Hi-MD-formatted disc back into a standard disc (do it from the recorder's menu).
- Record mono SP, or the "LP 105 kbps" mode, to a standard disc. Sources are always written as stereo.
- Use a different quality than the formats listed above, or re-encode tracks already on a disc (apart from the "Exact, as PCM"
  option when splitting or combining ATRAC).
- Split or combine MP3 tracks, mono tracks on a standard disc, or ATRAC tracks that are not 44.1 kHz.
- Move tracks on a standard disc that has groups.
- Clone between disc types (Hi-MD to standard or the reverse), or add a clone's tracks to a disc that already holds tracks (the
  destination is always emptied first).
- Save tracks from a standard-disc recorder that neither sends audio back (MZ-RH1) nor has the experimental download (Hn / Hr 1.x
  Hi-MD recorders); that experimental download has been tried on an MZ-NH700 only (see "Saving tracks to your PC").

How writing works
- Hi-MD: done by himd-js (the open-source Hi-MD library, GPL-2.0) through helper\himd_helper.js.
  MP3: the audio is appended to the disc's data file and the track index is updated.
  Everything else (PCM, LP2 / LP4, ATRAC3+, split / combine): also uses the disc's copy-protection session, which renames the
  data files (e.g. ...05 -> ...06) and rewrites the disc's integrity data. If that is interrupted, the recorder may not play
  the disc. LP2 / LP4 are encoded to ATRAC3 first (see below) and stored as the Hi-MD "AT3" type, with 384-byte (LP2) or
  192-byte (LP4) frames; ATRAC3+ as the "A3+" type with 2048- (352 kbps), 1488- (Hi-SP) or 376-byte (Hi-LP) frames.
  Deleting a PCM or ATRAC track uses the same session: the track's entry in the signed MAC list is zeroed and the list is
  re-signed. The audio is gone for good; raw copies of the index and MAC list are kept in backups\secure_delete_*.
  Copy any recordings you want to keep off the disc before deleting or adding.
  Moving tracks and renaming only edit the track index (himd_app.py writes just the changed sectors and reads them back).
  A lossless ATRAC split or join writes frames exactly as given (helper command upload_frames) with the source's own codec bytes.
  Formatting uses the recorder's vendor "reformat" command through himd-js (helper command format).
  Clone reads each track with the helper's dump command (exact, raw for ATRAC), writes runs of same-kind tracks with upload
  (PCM, MP3) or upload_frames (ATRAC, skipping the 96-byte EA3 header of the saved file), sets groups and the disc name by
  editing the track index (Disc.set_groups, with the usual index backup, so Undo reverts them), stores COVER.JPG like the
  disc image feature, and keeps a raw copy of the empty disc's index in backups\clone_before_*.
  Standard-disc clone: netmd_helper.js fetch with raw: true keeps the recorder's own data (out + .aea or .atrac3.wav); upload_clone
  writes it (SP: ffmpeg decodes the .aea to 16-bit stereo PCM and netmd-js sends it as Wireformat.pcm; LP2 / LP4: the ATRAC3
  frames are cut out of the .wav's data chunk and sent as Wireformat.lp2 / lp4) and then sets the disc's raw titles with
  setDiscTitle, as netmd-js does when it rewrites groups; list also returns the raw titles.
- Standard disc: done by netmd-js (GPL-2.0) through helper\netmd_helper.js. The experimental download (fetch with exploit: true;
  exploit_probe only reads the firmware version) uses netmd-exploits 0.5.11 (CachedSectorBulkDownload with HiMDUnboundedReading,
  USBCodeExecution and WaitForDiscToStopSpinning) and takes its patches out again in a finally block. If the recorder is playing or paused (for example
  after the remote control was used), the app stops it before adding tracks.
  LP2 / LP4 are encoded by atracdenc (an open-source ATRAC encoder, LGPL-2.1, in runtime\atracdenc) through
  helper\atrac3_encode.js, which runs it in its own process. This build of the encoder rounds the bitrate up to the next
  frame size it supports, so the app asks for 128 (LP2, true 132 kbps) and 64 (LP4, true 66 kbps), not 132 and 66.
- Headroom for ATRAC3 / ATRAC3+ (helper\atrac3.js): a lossy encoder's output can swing a little past the loudest samples of the
  original, and the recorder then clips those peaks flat, which sounds like crackle ("dust on a record") on a loud, hot-mastered
  CD. Measured on a ripped CD single: LP2 decoded with 5,174 full-scale samples in 214 flat-topped runs against 355 / 12 in the CD
  audio itself (LP4 4,730 / 36; MP3 49 / 7, so MP3 and PCM are not affected). So after encoding LP2, LP4 or ATRAC3+ the result is
  decoded without clipping; if it would clip, the source is turned down by just enough (peak 0.985) and encoded again, up to twice.
  Result on that track: LP2 -1.4 dB, LP4 -2.6 dB, ATRAC3+ -0.5 dB and no clipping left (0 full-scale samples). Quiet tracks are
  not touched, and the extra check adds a few seconds per track (ATRAC3+ about a minute for a 3-minute track). PCM is
  written exactly as it is; SP is encoded by the recorder itself.
- ATRAC3+ uses a second, newer atracdenc (runtime\atracdenc3p\atracdenc.exe, official 0.2.3 Windows build, LGPL, checked against
  a stored SHA-256 before every run, started without a shell) through helper\atrac3.js.
- Everything runs on the bundled Node in runtime\ (node.exe + node_modules). ATRAC and non-WAV audio are decoded or
  converted by runtime\ffmpeg.exe (LGPL build, BtbN n8.1).

Status (2026-10-21)
- Tested on an MZ-NH700 and an MZ-RH1.
- Hi-MD: disc reading, rename and undo, MP3 and WAV upload, MP3 / WAV / ATRAC delete, playback of PCM, MP3 and ATRAC. The
  recorders played the results afterwards.
- Standard disc: add (WAV, MP3, FLAC) in SP, delete, rename, saved-copy playback (NH700), copy-back playback (RH1) and
  remote control (NH700).
- LP2 and LP4 on a standard disc: a 20-second test tone was added in each format on the MZ-RH1, copied back from the disc
  and checked (length, level and pitch were right), then deleted. The same was then done on an MZ-NH700 with a standard disc:
  20-second tones in SP, LP2 and LP4 were added, the recorder reported each in the right format and length, all three
  played correctly on the NH700 (the app made the recorder play them through its headphone socket), and deleting them left
  the disc exactly as it was (the same two tracks, the same used and free space).
- LP2 and LP4 on a Hi-MD disc: a 20-second test tone was added in each format to a Hi-MD disc in the MZ-RH1. Both played
  correctly on the recorder, and also in the app. Both test tracks were then deleted; the disc, its index and its signed
  list came back identical to the start. The same two tests were then repeated on a Hi-MD disc in the MZ-NH700: LP2 and LP4
  both played correctly on the recorder itself and in the app, and the disc's tracks and index came back as they were (a
  deleted LP4 track can leave one 32 KB cluster unreclaimed, which is a limit of the Hi-MD library, not audio).
  Remember that a Hi-MD recorder cannot play while it is connected over USB: unplug it to listen on the recorder.
- Note: a recorder can only be used by one program at a time. If the window is open while something else is writing to the
  disc, playback is interrupted and a write can fail.
- Saving to the PC, Hi-MD PCM tracks: tested on the MZ-RH1 with a 3-second track in all three formats (exact length, tags
  present) and a 3.5-minute recording as FLAC (right length and level); Cancel tested on a 41-minute track. Also tried by the
  user in the window: an ATRAC track from a Hi-MD disc and two tracks from a standard disc were saved and played back correctly.
  Not yet tried: keeping ATRAC tracks as .oma files, and saving a standard-disc track from the MZ-RH1 that the app did not add.
- Disc image: a test picture was stored on a 14-track Hi-MD disc in the MZ-RH1. The checks passed, all 14 tracks and the track
  index were unchanged, the recorder played everything normally, and the app showed the picture when the disc was loaded.
  The user then replaced the picture from the window, removed the disc, put it back and reloaded it: it read correctly and
  the new picture showed. The user also removed the picture and added it again from the window, and that worked too.
  The picture was stored from the MZ-RH1; the same disc was then used in the MZ-NH700 (LP tests) and read and played normally
  with the picture on it. Not yet tried: storing the picture from the NH700.
- Sonos: a test tone was played to the Office room (a pair of Sonos Fives) and the user then played tracks to it from the
  window; it worked. The room search takes about 2.4 seconds (it was 14 seconds before it searched all network adapters at
  once and stopped early), and the room list is instant once speakers have been found. Switching tracks quickly, the display
  and closing the window while a room plays were fixed and checked by the user.
- MP3 playback: it now starts within about a second (checked from the command line and in the window; it used to wait for the
  whole track to be read).
- Clock: works on the MZ-RH1; the MZ-NH700 ignores the set-time command (see above). CSV export: tried by the user, it works.
- Format (on the MZ-NH700, tried by the user in the window): standard disc to standard disc worked, and standard disc to Hi-MD
  worked; the disc was empty afterwards each time. Going back from Hi-MD to standard was done from the recorder's menu and worked.
  Not tried separately: reformatting a Hi-MD disc that holds tracks.
- Move: tried by the user on a Hi-MD disc with several tracks and worked perfectly. Before that, 6200 random moves were run on
  31 saved track indexes (only the order and group records changed; moving back restored the original bytes). Not yet tried on a
  standard disc.
- Combine (PCM): worked, and the new track played. Split (PCM): the first try stopped at the byte-for-byte read-back check
  because the cut was not on a 64-byte unit (each part lost its last 8 samples, about 0.0002 s); the cut now snaps to a unit,
  and the retry worked flawlessly.
- ATRAC split, lossless: worked on a short ATRAC3+ 352 kbps track; both parts played. Before building it, a real ATRAC3+ stream
  was cut at three frame boundaries and decoded: the first part was identical to the original up to the cut, and only the first
  frame (46 ms) of the second part differed. Not yet tried: lossless Combine, "Exact, as PCM" on an ATRAC track, ATRAC3 (LP2 /
  LP4) tracks and the recorder's own Hi-SP recordings.
- ATRAC3+ 352 kbps: a short track added to a Hi-MD disc worked (played in the app and on the recorder).
- Other source formats and MP3 output on Hi-MD: the helper's size estimates were checked on a WAV, a FLAC and an MP3, and a
  FLAC was encoded to a 192 kbps MP3 and added in the helper's in-memory rehearsal on the real disc (nothing written, no
  temporary files left). A real write of an MP3 made from another format is not yet confirmed.
- The three-panel layout was checked in screenshots at three window widths (the user said it looks much better).
- Experimental NH700 download (2026-10-22): the probe read the NH700's firmware as Hn1.100 (supported). A 3:13 SP track from the
  user's own standard disc was read from the command line in 30 seconds; a second read was byte-for-byte identical, the level
  and the natural fade at the end were right, and the user said the file played perfectly. The user then saved an SP track as WAV
  from the app window with the same method, and it was flawless. Not yet tried: LP2 / LP4 and mono tracks this way, cancelling
  in the middle of a track, other Hi-MD recorders, and a sample-by-sample comparison with an MZ-RH1 download of the same track.
- Read-ahead (2026-11-03): a standard-disc track played through the PC (or sent to a Sonos room / Google TV) takes about 22 seconds to start the first
  time, because the recorder's read has to be set up. Once the track that is playing has been read (about a minute, much faster than it plays), the app
  reads the NEXT THREE tracks and the TWO tracks before it (next one first, then the previous one), one after the other, into temporary files
  while you listen, so "next", "previous" and the automatic advance start at once. Moving to a track that is ready never stops the reading that is going on; it simply carries on
  from the new place. If you pick the track being read right now, that read is carried on rather than restarted. If you pick a track that is not ready,
  or do anything else with the recorder (save, edit, rescan...), the reading is stopped first, so it never gets in the way. Skipping faster than the
  recorder can read (a 9-minute track takes over a minute to read) can still catch it out once; the 22-second start then applies. Nothing is written to
  the disc; the tracks kept are limited to about 700 MB, and the temporary files are deleted as you go and when the program closes.
  (play_tracks.py; api play_readahead(false) switches it off.)
- Fast start (2026-11-03): about 20 of the ~22.6 s a cold read takes on an MZ-NH700 is a fixed sleep inside the netmd-exploits library
  (wait-for-disc-spinning.js: on Hi-MD recorders it cannot read the disc's spin state, so it just sleeps 20 s after seeking to the track). Measured on an
  NH700 by reading tracks of one disc with a shorter wait and comparing the audio byte for byte with the normal read: reading the same track again was
  identical with any wait from 0 to 12 s; after a read that had finished, the next track was identical at 10, 12 and 16 s, had a few 23 ms glitches at
  8 s and below, and a long jump across the disc (track 11 to 1 and back) was identical at 8 s but failed at 4 s ("Cannot align!"); with no wait a long
  jump hung. So playing uses 12 s when the previous read finished cleanly (the drive is settled) and the library's own 20 s whenever the drive's position
  is uncertain (the first read, a read that was cancelled or failed, or any other use of the recorder), which brings a cold start from about 22.6 s to
  about 14.6 s. Only playing / casting uses it: Save to PC, Clone, Identify and Split keep the full wait. The helper takes a spinWait argument (milliseconds)
  or the MDM_SPIN_WAIT environment setting; api play_fast_start(false) switches it off. Each read's timing marks are written to app.log ("helper track N: ...").
- Playing NH700 standard-disc tracks through the PC (2026-10-22): tested from the command line / the same code the window calls, on
  the 2-track clone disc in the MZ-NH700 (not yet clicked through in the window). With the box ticked, "Goldfinger" (5:53, SP)
  started after 22.6 seconds (30.2 s with the library's full-size first read; the smaller first read gave byte-identical
  audio), was fully read 57.6 seconds after the start, and decoded correctly (music, natural fade, 2.4 s of padding at the end).
  Stopping 6 seconds in ended the read in 1.7 s, the
  recorder reported "ready", the disc listed normally and the next track started in the same 22.6 s. Not yet tried: LP2 / LP4 or
  mono tracks this way, a Sonos room, or a track longer than the library's 220-second read buffer (the 31-minute track would
  show the re-aligning pauses the library does between buffers). The user then tried it in the window: playback started in
  about 15 seconds with no dropouts and seeking worked. The volume slider went missing after a track had played by remote control
  (stopping the player did not bring it back); fixed. The "play through this PC (experimental)" tick box was then removed at the
  user's request, so play simply reads through the PC on the NH700.
- Clone (2026-10-22): tested on an MZ-RH1, run from the command line (not yet through the window). The source was a 10-track
  ATRAC3+ 352 kbps Hi-MD disc with a disc picture and no groups; it was copied to the PC (read-only), then a disposable full
  standard disc in the same recorder was erased and set up as Hi-MD (35 seconds), and the copy was written to it. All 10 tracks
  read back byte for byte, the picture was stored, titles / lengths / codec matched, the PC copy was deleted, and the user
  confirmed the cloned disc plays on the MZ-RH1. Group writing was tested on 41 saved track indexes (random groups, titles and
  tracks unchanged). Not yet tried: PCM or MP3 tracks, a disc with groups, ATRAC3 (LP2 / LP4) tracks, an MZ-NH700, the window's
  sheets, resuming a saved copy after restarting, and cancelling during the copy.
- Clone, standard disc (2026-10-22): from the command line. The whole 10-track SP disc in the user's MZ-NH700 (75 minutes of
  audio) was read with the experimental download in 748 seconds; every track was decoded once to check its length. The user then
  asked to leave the 31-minute track out and later to copy only the first two, so the saved copy was cut down by hand (before
  the tick-box list existed). Those two SP tracks were written to an empty standard disc in the same NH700 in 371 seconds; the
  new disc lists 2 SP tracks with the right titles and lengths (336 s and 353 s) and the original disc name, and the PC copy was
  deleted. A first attempt to write 9 tracks was stopped after a minute and a half at the user's request; it committed nothing,
  and the recorder needed an unplug / replug before it accepted another write. The tick-box list, its renumbering of groups and
  of the standard-disc title string were checked offline with sample groups, but the sheet has not been seen in the window.
  Not yet tried: the user playing the new disc on the recorder, LP2 / LP4 tracks, groups, mono SP, an MZ-RH1 as reader or
  writer for a standard-disc clone, and the standard-disc clone sheets in the window.

Requirements
- Windows, Python 3.12 with pyusb, libusb-package, pywebview; each recorder on the WinUSB driver. DRIVER-SETUP.html is a step by
  step guide to putting WinUSB on a recorder with Zadig (about two minutes, once per recorder and USB mode). It opens from the
  "Driver setup guide..." button on the "No recorder found" screen.
- The runtime\ folder (Node 24, ffmpeg, atracdenc, atracdenc3p, himd-js, netmd-js, netmd-exploits) must stay next to the app.

Files
- helper\cdburn_plain.ps1   disc writers: list / check / erase / burn an audio CD / write files to a data disc (Windows' IMAPI2)
- himd_app.py, ui\index.html   the window
- cdrip.py   audio CD access (track list, CD-Text, careful ripping) and the MusicBrainz / Cover Art Archive lookups
- himd_dev.py, himd_fs.py, himd_disc.py   USB access (and the list of NetMD models), read-only FAT16 reader, track-index
  reader / editor (renames, move, groups)
- helper\himd_helper.js   Hi-MD: inspect / plan / upload / upload_frames / delete / dump / list / backup / format / cover_set /
  cover_remove commands built on himd-js
- helper\netmd_helper.js   standard discs: list / plan / upload / delete / rename / move / format / fetch / remote commands built on
  netmd-js
- sonos.py   finds Sonos rooms and controls them (discovery, room layout, play / pause / seek / volume)
- chromecast.py   Google Cast sender for Google TVs / Chromecasts (device search, play / pause / seek / volume); sonos_cast.py holds
  the "Play on" logic for both Sonos and Cast
- lyricvideo.py   makes the lyric video (cover, title, timed lyrics + audio) as an HLS stream for a Google TV; mediaserver.py serves it
- disc_lookup.py   the online lookup of a pre-recorded standard disc (MusicBrainz release match, artist / album, album art kept on this PC)
- helper\wav.js   WAV parsing shared by both helpers
- helper\atrac3.js, helper\atrac3_encode.js   LP2 / LP4 encoding with atracdenc (one encode per process) and the checked ATRAC3+
  encoder wrapper, shared by both helpers
- runtime\   bundled Node, ffmpeg and libraries, with their licences (LICENSE-node.txt, LICENSE-ffmpeg.txt,
  atracdenc\LICENSE-atracdenc.txt, atracdenc3p\NOTICE.txt)
- backups\   track-index copies kept before changes;  app.log   playback and format diagnostics
- himd_manager.py   the older tkinter window (kept for reference)
- DRIVER-SETUP.html   the USB driver (WinUSB / Zadig) guide
- LICENSE.txt, THIRD-PARTY-NOTICES.txt, LICENSES\   the author's licence (a draft to confirm), every bundled component with its
  licence and source address, and the licence texts. Needed whenever copies are given to other people.
