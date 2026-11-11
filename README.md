# MiniDisc Manager

A Windows program for managing Hi-MD and standard MiniDisc recorders over USB: see what is on a disc, add, move, split, combine, rename and delete tracks, group them, copy a disc, save tracks to the PC, and play a disc on the PC, a Sonos speaker or a Google TV while the disc is read.

Version 0.27.2 · Copyright (c) 2026 Vinny Powell · see `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt`

## What it does

- Reads and edits Hi-MD discs (PCM, ATRAC3 LP2/LP4, ATRAC3plus, MP3) and NetMD / standard MiniDisc discs.
- Adds tracks from files, audio CDs, Bandcamp, SoundCloud, internet radio and Yoto cards.
- Splits, combines, moves, fades and renames tracks, with groups, auto split, album look-up and timed lyrics.
- Clones a disc, saves tracks to the PC, burns an audio CD, keeps a track list on the disc.
- Converts a standard (SP / LP) disc to Hi-MD, and rewrites LP2 / LP4 tracks as SP (spreading them over two discs when they do not fit) so that players without LP support can play them.
- Prints disc labels (HP Sprocket and Polaroid Hi-Print over Bluetooth, or as a picture).
- Plays the disc on the PC, a Sonos room or a Google TV, with a choice of level-meter and spectrum displays.

## What is in this repository

The source of the Restricted edition (the full program without the Apple Music recorder).

| Path | Purpose |
|---|---|
| `himd_app.py` and the other `.py` files | the application, USB access to Hi-MD and NetMD recorders, disc editing, lyrics, album look-up, recording from online sources, playing to Sonos and Google TV |
| `ui/` | the window (one HTML page) and the recorder pictures |
| `helper/` | the Node helper scripts that read and write the disc, an audio helper and a CD-burn script |
| `ps/` | small PowerShell scripts (Bluetooth, sound outputs) |
| `installer/` | the build script and Inno Setup file that make the installer and portable zip |
| `LICENSES/`, `LICENSE.txt`, `THIRD-PARTY-NOTICES.txt` | licences |
| `README.txt` | the full user guide |
| `experimental/` | work in progress, not used by the program |

**Not included:** the bundled runtime (Python, Node.js with the MiniDisc libraries, ffmpeg), which is large. The installer and portable zip on the Releases page contain everything and need nothing else installed. To run from source you need Windows, Python 3.12 with the packages in `LICENSES/python`, and the runtime folder from a release (copy its `runtime` folder next to `himd_app.py`).

## Download

See the Releases page for the Windows installer, the portable zip and the user manual.

## Warning

MiniDisc Manager can write to and erase MiniDiscs. It has been tested on a Sony MZ-NH700 and an MZ-RH1 only. Copy any recordings you cannot replace to your PC before editing a disc. Use it at your own risk. Close any other recorder software first: only one program can use the recorder at a time.

## Licence

The Python program and the window are under the MIT licence; the helper scripts in `helper/` that load the GPL-2.0 libraries are under GPL-2.0. `LICENSE.txt` says which is which, and `THIRD-PARTY-NOTICES.txt` lists the libraries the program uses.

Not affiliated with, authorised or endorsed by Sony or Sonos. Product and company names belong to their owners.
