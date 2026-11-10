"""Where the program's files are, and where it keeps what it writes. Shared by himd_app.py and the modules split out of it."""
import os
import sys
import tempfile

FROZEN = bool(getattr(sys, 'frozen', False))          # True in the installed / portable program (built with PyInstaller)
HERE = os.path.dirname(os.path.abspath(__file__))     # the program's own files: runtime\, helper\, ui\ (only read)

# Files the program writes (index backups, the log): next to the program when it runs from source, under AppData when installed
# (an installed program may sit in a folder it is not allowed to write to).
USER_DIR = os.path.join(os.environ.get('LOCALAPPDATA') or HERE, 'MiniDiscManager') if FROZEN else HERE
BACKUP_DIR = os.path.join(USER_DIR, 'backups')

HELPER = os.path.join(HERE, 'helper', 'himd_helper.js')
NETMD_HELPER = os.path.join(HERE, 'helper', 'netmd_helper.js')     # standard MiniDiscs (NetMD)
# Bundled Node runtime (with himd-js in runtime\node_modules); no other program needs to be installed.
NODE_EXE = os.path.join(HERE, 'runtime', 'node.exe')
APPAUDIO = os.path.join(HERE, 'helper', 'appaudio.exe')   # records one program's sound (used for the streaming-site windows)

# Big working copies are kept out of OneDrive on purpose, always under AppData (also when run from source).
_APPDATA = os.path.join(os.environ.get('LOCALAPPDATA') or HERE, 'MiniDiscManager')
COPIES_DIR = os.path.join(_APPDATA, 'copies')    # FLAC copies of the tracks this app adds to standard discs, so they can be played here
CLONE_DIR = os.path.join(_APPDATA, 'clone')      # the PC copy of a disc being cloned (it can be a gigabyte); stays until the clone is written and checked
CONVERT_DIR = os.path.join(_APPDATA, 'convert')  # the PC copy of a standard disc being converted to Hi-MD; stays until it is written back and checked
SPLIT_DIR = os.path.join(_APPDATA, 'split')     # new tracks saved by a split that did not fit, until they are written
ASR_DIR = os.path.join(_APPDATA, 'whisper')      # the optional speech recogniser (whisper.cpp + one model, ~200 MB) that writes timed lyrics from a track's audio
RESCUE_DIR =os.path.join(_APPDATA, 'rescue')    # the cut parts of a standard-disc split whose original was deleted first and whose writing then failed (kept, never swept)

RECORDER_PHOTOS = os.path.join(USER_DIR, 'recorder_photos')   # pictures of recorders kept on this PC only, e.g. MZ-NH700.jpg (not part of the installer)
REC_DIR = os.path.join(USER_DIR, 'recordings')                # tracks recorded from the streaming-site windows: KEPT until removed
WEBVIEW_DIR = os.path.join(USER_DIR, 'webview')               # the web views' cookies: keeps the site logins between runs
BC_DIR = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-bandcamp')   # scratch (cover picture), deleted on exit
PLAY_DIR = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-play')     # tracks being played, deleted on exit
