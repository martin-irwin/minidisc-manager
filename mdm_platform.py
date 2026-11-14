"""The few things that differ between Windows, Linux and macOS, in one place.

On Windows everything behaves exactly as before: the bundled runtime\\*.exe files are used and data goes under %LOCALAPPDATA%.
On Linux and macOS the program uses the runtime folder when it has the tool in it (runtime/node, runtime/ffmpeg), and otherwise the
one installed on the system (found on PATH). Data goes where each system expects it:
  Linux   $XDG_DATA_HOME/MiniDiscManager, normally ~/.local/share/MiniDiscManager
  macOS   ~/Library/Application Support/MiniDiscManager
"""
import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')
EXE = '.exe' if IS_WINDOWS else ''


def data_root(fallback):
    """The folder that holds the program's own 'MiniDiscManager' data folder. `fallback` is used on Windows when LOCALAPPDATA is not set
    (as before)."""
    if IS_WINDOWS:
        return os.environ.get('LOCALAPPDATA') or fallback
    if IS_MAC:
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    return os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')


def tool(here, name, *subdirs):
    """Full path of a helper program: runtime[/subdirs]/name(.exe) when it is there, else (not on Windows) the one on PATH.
    Always returns a path, so a missing tool still gives a readable 'missing (path)' message."""
    bundled = os.path.join(here, 'runtime', *subdirs, name + EXE)
    if IS_WINDOWS or os.path.exists(bundled):
        return bundled
    return shutil.which(name) or bundled


def open_path(path):
    """Opens a file or folder with the system's own program (Explorer, Finder, or the desktop's file manager)."""
    if IS_WINDOWS:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


def windows_only(feature):
    """The error dict the program's own API returns for a feature that has not been brought to this system yet."""
    return {'error': '%s is only available on Windows for now.' % feature}
