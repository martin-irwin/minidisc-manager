#!/usr/bin/env bash
# Sets up MiniDisc Manager to run from source on Linux. Run it from anywhere:   linux/setup.sh
#
#   1. checks the system programs it needs, and says how to install any that are missing
#   2. makes a Python environment in .venv with the program's Python libraries
#   3. puts the Node libraries in runtime/node_modules, at the same versions as the Windows build, with the himd-js delete fix
#   4. copies the LP2 / LP4 encoder (atracdenc.js) into runtime/atracdenc
#   5. builds the Hi-SP / Hi-LP encoder (atracdenc 0.2.3 + the frame-size patch) into runtime/atracdenc3p   (skip: --no-atrac3plus)
#   6. with sudo: a udev rule so you can reach MiniDisc recorders over USB, and Linux leaves Hi-MD recorders unmounted (skip: --no-system)
#
# Safe to run again; every step checks what is already there. Then start the program with linux/run.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINUX="$ROOT/linux"
RT="$ROOT/runtime"
DO_SYSTEM=1
DO_AT3P=1
for arg in "$@"; do
    case "$arg" in
        --no-system) DO_SYSTEM=0 ;;
        --no-atrac3plus) DO_AT3P=0 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
    esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!   %s\033[0m\n' "$*"; }
die()  { printf '\033[31mx   %s\033[0m\n' "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Hi-MD recorders in Hi-MD mode (from himd-js; the same list as in 60-minidisc.rules): usb-storage must leave these to the program.
HIMD_IDS="054c:017f,054c:0181,054c:0183,054c:0185,054c:0187,054c:018b,054c:01ea,054c:021a,054c:021c,054c:022d,054c:023d,054c:0287"

# ---------------------------------------------------------------------------------------------------------------------------
say "1/6  Checking system programs"
missing=()
have python3 || missing+=(python3)
have node    || missing+=(node)
have npm     || missing+=(npm)
have ffmpeg  || missing+=(ffmpeg)
have patch   || missing+=(patch)
if [ "$DO_AT3P" = 1 ]; then
    have git   || missing+=(git)
    have c++   || missing+=(c++)                     # cmake is optional: without it, step 5 takes one from PyPI into .venv
    have pkg-config && pkg-config --exists sndfile || missing+=(libsndfile)
fi
gui_ok=1
python3 - <<'EOF' 2>/dev/null || gui_ok=0
import gi
gi.require_version('Gtk', '3.0')
try:
    gi.require_version('WebKit2', '4.1')
except ValueError:
    gi.require_version('WebKit2', '4.0')
EOF
[ "$gui_ok" = 1 ] || missing+=(gtk-webkit)

if [ ${#missing[@]} -gt 0 ]; then
    warn "Missing: ${missing[*]}"
    if have pacman; then
        echo "    Arch / Omarchy:  sudo pacman -S --needed python python-gobject webkit2gtk-4.1 nodejs npm ffmpeg patch git cmake base-devel libsndfile pkgconf"
    elif have apt-get; then
        echo "    Debian / Ubuntu: sudo apt install python3 python3-venv python3-gi gir1.2-webkit2-4.1 nodejs npm ffmpeg patch git cmake g++ libsndfile1-dev pkg-config"
    elif have dnf; then
        echo "    Fedora:          sudo dnf install python3 python3-gobject webkit2gtk4.1 nodejs npm ffmpeg-free patch git cmake gcc-c++ libsndfile-devel pkgconf"
    fi
    die "Install the missing programs, then run linux/setup.sh again."
fi
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 18 ] || die "Node $node_major is too old; Node 18 or newer is needed (the Windows build uses Node 24)."
echo "    python3 $(python3 -c 'import platform;print(platform.python_version())'), node $(node --version), $(ffmpeg -version | head -1 | cut -d' ' -f1-3)"

# ---------------------------------------------------------------------------------------------------------------------------
say "2/6  Python environment (.venv)"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$ROOT/.venv"     # system site packages: the GTK / WebKit bindings come from the system
fi
"$ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
"$ROOT/.venv/bin/python" -m pip install --quiet -r "$LINUX/requirements.txt"
echo "    ok"

# ---------------------------------------------------------------------------------------------------------------------------
say "3/6  Node libraries (runtime/node_modules)"
mkdir -p "$RT"
cp "$LINUX/package.json" "$LINUX/package-lock.json" "$RT/"
# --allow-git: himd-js / netmd-js take @originjs/crypto-js-wasm from GitHub at a pinned commit (see package-lock.json); npm 12 refuses
# git dependencies unless asked. Older npm versions ignore the option.
( cd "$RT" && npm ci --omit=dev --no-audit --no-fund --loglevel=error --allow-git=all )
if patch -d "$RT/node_modules/himd-js" -p1 --forward --dry-run --silent < "$LINUX/patches/himd-js-0.2.7-delete-fix.patch" >/dev/null 2>&1; then
    patch -d "$RT/node_modules/himd-js" -p1 --forward --silent < "$LINUX/patches/himd-js-0.2.7-delete-fix.patch"
fi
grep -q "PATCH (MiniDisc Manager)" "$RT/node_modules/himd-js/dist/himd-functions.js" || die "The himd-js delete fix did not apply."
node -e "require('$RT/node_modules/usb')" || die "The USB library did not load (runtime/node_modules/usb)."
echo "    ok (himd-js delete fix applied)"

# ---------------------------------------------------------------------------------------------------------------------------
say "4/6  LP2 / LP4 encoder (runtime/atracdenc)"
mkdir -p "$RT/atracdenc"
cp "$LINUX/vendor/atracdenc/atracdenc.js" "$LINUX/vendor/atracdenc/LICENSE-atracdenc.txt" "$RT/atracdenc/"
echo "    ok"

# ---------------------------------------------------------------------------------------------------------------------------
if [ "$DO_AT3P" = 1 ]; then
    say "5/6  Hi-SP / Hi-LP encoder (atracdenc 0.2.3 + frame-size patch -> runtime/atracdenc3p)"
    if [ -x "$RT/atracdenc3p/atracdenc" ]; then
        echo "    already built (delete runtime/atracdenc3p to build it again)"
    else
        work="$(mktemp -d)"
        trap 'rm -rf "$work"' EXIT
        git -c advice.detachedHead=false clone --quiet --depth 1 --branch 0.2.3 --recurse-submodules --shallow-submodules \
            https://github.com/dcherednik/atracdenc "$work/atracdenc"
        patch -d "$work/atracdenc" -p1 --silent < "$LINUX/patches/atracdenc-0.2.3-framesize.patch"
        CMAKE="$(command -v cmake || true)"
        if [ -z "$CMAKE" ]; then                     # no system cmake (or the package mirror failed): the PyPI build, into .venv only
            echo "    no cmake on this system; getting one from PyPI into .venv"
            "$ROOT/.venv/bin/python" -m pip install --quiet cmake
            CMAKE="$ROOT/.venv/bin/cmake"
        fi
        log="$work/build.log"
        { "$CMAKE" -S "$work/atracdenc/src" -B "$work/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-include cstdint" &&
          "$CMAKE" --build "$work/build" --parallel "$(nproc 2>/dev/null || echo 2)"; } >"$log" 2>&1 ||
            { tail -30 "$log"; die "The Hi-SP / Hi-LP encoder did not build (log above). Run again with --no-atrac3plus to skip it."; }
        mkdir -p "$RT/atracdenc3p"
        install -m 755 "$work/build/atracdenc" "$RT/atracdenc3p/atracdenc"
        cp "$LINUX/patches/atracdenc-0.2.3-framesize.patch" "$RT/atracdenc3p/"
        echo "    built"
    fi
else
    say "5/6  Hi-SP / Hi-LP encoder: skipped (--no-atrac3plus); PCM, MP3, SP and LP2 / LP4 still work"
fi

# ---------------------------------------------------------------------------------------------------------------------------
if [ "$DO_SYSTEM" = 1 ]; then
    say "6/6  USB access (needs sudo once)"
    echo "    /etc/udev/rules.d/60-minidisc.rules: you can use MiniDisc recorders without root, and Linux leaves Hi-MD recorders"
    echo "    to this program instead of mounting them as a USB drive (the Linux side of the Zadig step on Windows)"
    sudo install -m 644 "$LINUX/60-minidisc.rules" /etc/udev/rules.d/60-minidisc.rules
    if [ -e /etc/modprobe.d/minidisc.conf ]; then    # from an earlier version of this script: its usb-storage option was too long
        sudo rm -f /etc/modprobe.d/minidisc.conf     # for the kernel (127 characters), which could stop usb-storage loading at boot
        echo "    removed /etc/modprobe.d/minidisc.conf (left by an earlier setup)"
    fi
    sudo udevadm control --reload-rules
    # Recorders plugged in now get the access rule ("change" events; the unbind rule only acts on add / bind, so a mounted disc is safe).
    sudo udevadm trigger --action=change --subsystem-match=usb
    sudo udevadm settle --timeout=10 || true
    # A Hi-MD recorder that is plugged in now: hand it over straight away, unless its disc is mounted.
    for intf in /sys/bus/usb/drivers/usb-storage/*:*; do
        [ -e "$intf" ] || continue
        real="$(readlink -f "$intf")"
        id="$(cat "$(dirname "$real")/idVendor" 2>/dev/null):$(cat "$(dirname "$real")/idProduct" 2>/dev/null)"
        case ",$HIMD_IDS," in *",$id,"*) ;; *) continue ;; esac
        mounted=""
        for b in "$real"/host*/target*/*/block/*; do
            [ -e "$b" ] && lsblk -nro MOUNTPOINT "/dev/$(basename "$b")" 2>/dev/null | grep -q . && mounted="/dev/$(basename "$b")"
        done
        if [ -n "$mounted" ]; then
            warn "The Hi-MD recorder's disc is mounted ($mounted). Eject it (udisksctl unmount -b $mounted), then unplug the recorder and plug it in again."
        else
            echo -n "$(basename "$real")" | sudo tee /sys/bus/usb/drivers/usb-storage/unbind >/dev/null
            echo "    the connected Hi-MD recorder ($id) is ready for MiniDisc Manager"
        fi
    done
    echo "    ok"
else
    say "6/6  USB access: skipped (--no-system). Without it you may need to run as root, and Hi-MD recorders stay with usb-storage."
fi

say "Done. Start MiniDisc Manager with:  linux/run.sh"
