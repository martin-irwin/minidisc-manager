# MiniDisc Manager on Linux

MiniDisc Manager is written by Vinny Powell for Windows. These files let it run **from source on Linux**. Windows behaviour is unchanged: every difference is behind a platform check (see `mdm_platform.py`).

> **Status: early.** The setup and the program's start-up are tested on Arch / Omarchy (x86_64 and aarch64). Reading and writing a real recorder **has not been tested on Linux yet**. Back up anything you can't replace before you edit a disc, exactly as on Windows.

## Install

1. Get the system packages.

   **Arch / Omarchy**
   ```sh
   sudo pacman -S --needed python python-gobject webkit2gtk-4.1 nodejs npm ffmpeg patch git cmake base-devel libsndfile pkgconf
   ```
   **Debian / Ubuntu**
   ```sh
   sudo apt install python3 python3-venv python3-gi gir1.2-webkit2-4.1 nodejs npm ffmpeg patch git cmake g++ libsndfile1-dev pkg-config
   ```
   Node 18 or newer is needed. `cmake`, the compiler and `libsndfile` are only used to build the Hi-SP / Hi-LP encoder. If cmake can't be installed (for example a package-mirror error), setup.sh fetches cmake from PyPI into `.venv` instead.

2. Clone the repository and run the setup script. It asks for your password once, for the USB step.
   ```sh
   git clone https://github.com/martin-irwin/Minidisc-Manager.git
   cd Minidisc-Manager
   linux/setup.sh
   ```
3. Start the program.
   ```sh
   linux/run.sh
   ```

You can run `linux/setup.sh` again at any time, for example after `git pull`. The options are:

- `--no-atrac3plus`: skips building the Hi-SP / Hi-LP encoder. Everything else still works, including PCM, MP3, SP and LP2 / LP4.
- `--no-system`: skips the sudo step. Without it you may need to run the program as root, and Hi-MD recorders stay with the kernel.

## What setup.sh does

| Step | What | Where |
|---|---|---|
| Python | A venv with pywebview, pyusb, libusb-package, Pillow and numpy. It uses the system GTK / WebKit for the window. | `.venv/` |
| Node libraries | himd-js, netmd-js and the rest, at exactly the versions in the Windows 0.27.9 build, including the indirect ones (`linux/package.json` and its lock file). Vinny's himd-js delete fix is applied as `linux/patches/himd-js-0.2.7-delete-fix.patch`. | `runtime/node_modules/` |
| LP2 / LP4 encoder | atracdenc.js, the WebAssembly build used on Windows | `runtime/atracdenc/` |
| Hi-SP / Hi-LP encoder | atracdenc 0.2.3 (libgha `b4ed00bf`) built from source with Vinny's frame-size patch (`linux/patches/atracdenc-0.2.3-framesize.patch`). A stock atracdenc ignores the bit rate, so the program never falls back to one on PATH. | `runtime/atracdenc3p/` |
| USB access (sudo) | `linux/60-minidisc.rules`: you can use the recorders without root, and for the 12 Hi-MD models the desktop never mounts the disc and `usb-storage` is unbound as soon as it takes the recorder. This is the Linux version of the Zadig / WinUSB step on Windows. A recorder already plugged in is handed over at once, unless its disc is mounted. (It deletes `/etc/modprobe.d/minidisc.conf` if an earlier version of setup.sh left one.) | `/etc/udev/rules.d/60-minidisc.rules` |

ffmpeg and node come from your system (PATH). If you put your own copies in `runtime/`, the program uses those instead. The program's data goes to `~/.local/share/MiniDiscManager` (or to `$XDG_DATA_HOME`).

## Recorders

- **Hi-MD discs** (NH, RH and DH series in Hi-MD mode): Linux would normally treat the recorder as a USB drive. The setup step stops that for the 12 known Hi-MD models, including the **MZ-RH1** (`054c:0287`). If you see *"Linux is using this recorder as a USB drive"*, run `linux/setup.sh`, then unplug the recorder and plug it in again. The program doesn't take the recorder away from Linux by itself, because a mounted disc could be damaged.
- **Standard discs** (NetMD, including Hi-MD recorders with a standard disc inside, e.g. the RH1 as `054c:0286`): these only need the udev rule.
- As on Windows, put the disc in **before** you plug in the cable.

## Not on Linux yet

These need Windows-only parts. On Linux they show nothing (the CD drive list is empty) or fail with an error message.

- **Rip CD, Burn Audio CD, Save to disc**: drive access goes through Windows. On Linux no CD drives are listed. The online album lookups should still work.
- **Recording from Bandcamp / SoundCloud**: captures one program's sound through a Windows helper (`appaudio.exe`). Internet radio should work, because it's recorded with ffmpeg.
- **Sound output & Bluetooth panel**: uses PowerShell. Choose the output in your desktop's sound settings instead. The program's own player, EQ and visualizer should work.
- **Printing labels to an HP Sprocket / Polaroid Hi-Print**: the printing itself uses Bluetooth sockets that Linux has, but finding the paired printer uses PowerShell. Saving the label as a PNG should work.
- **Listen to the tracks (speech recogniser)**: downloads a Windows build of whisper.cpp.
- **Video links windows**, and **window zoom** (Shift and + / -).

## For developers

- `mdm_platform.py` has the OS checks, the data folder, the tool lookup and `open_path()`. `mdm_paths.FFMPEG` / `NODE_EXE` replace the hard-coded `.exe` paths. In the helpers, `BIN()` / `runtimeBin()` do the same.
- The page adds the class `linux` to `<html>` when it runs in WebKitGTK. It uses it for the drop-down style and the setup-guide wording.
- These files come from Vinny's 0.27.9 Windows build, unchanged: `linux/vendor/atracdenc/atracdenc.js` (GPL-2.0, see its licence file) and both patches.
