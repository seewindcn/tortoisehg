# paths.py - TortoiseHg path utilities
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

try:
    from tortoisehg.util.config import (icon_path, bin_path, license_path,
                                        locale_path)
except ImportError:
    icon_path, bin_path, license_path, locale_path = None, None, None, None

import os, sys
import mercurial

_hg_command = None

def find_root(path=None):
    p = path or os.getcwd()
    while not os.path.isdir(os.path.join(p, ".hg")):
        oldp = p
        p = os.path.dirname(p)
        if p == oldp:
            return None
        if not os.access(p, os.R_OK):
            return None
    return p

def get_tortoise_icon(icon):
    "Find a tortoisehg icon"
    icopath = os.path.join(get_icon_path(), icon)
    if os.path.isfile(icopath):
        return icopath
    else:
        print 'icon not found', icon
        return None

def get_icon_path():
    global icon_path
    return icon_path or os.path.join(get_prog_root(), 'icons')

def get_license_path():
    global license_path
    return license_path or os.path.join(get_prog_root(), 'COPYING.txt')

def get_locale_path():
    global locale_path
    return locale_path or os.path.join(get_prog_root(), 'locale')

def _get_hg_path():
    return os.path.abspath(os.path.join(mercurial.__file__, '..', '..'))

def get_hg_command():
    """List of command to execute hg (equivalent to mercurial.util.hgcmd)"""
    global _hg_command
    if _hg_command is None:
        _hg_command = _find_hg_command()
    return _hg_command

if os.name == 'nt':
    import win32file

    def find_in_path(pgmname):
        "return first executable found in search path"
        global bin_path
        ospath = os.environ['PATH'].split(os.pathsep)
        ospath.insert(0, bin_path or get_prog_root())
        pathext = os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD')
        pathext = pathext.lower().split(os.pathsep)
        for path in ospath:
            ppath = os.path.join(path, pgmname)
            for ext in pathext:
                if os.path.exists(ppath + ext):
                    return ppath + ext
        return None

    def _find_hg_command():
        if hasattr(sys, 'frozen'):
            progdir = get_prog_root()
            exe = os.path.join(progdir, 'hg.exe')
            if os.path.exists(exe):
                return [exe]

        # look for in-place build, i.e. "make local"
        exe = os.path.join(_get_hg_path(), 'hg.exe')
        if os.path.exists(exe):
            return [exe]

        exe = find_in_path('hg')
        if not exe:
            return ['hg.exe']
        if exe.endswith('.bat'):
            # assumes Python script exists in the same directory.  .bat file
            # has problems like "Terminate Batch job?" prompt on Ctrl-C.
            if hasattr(sys, 'frozen'):
                python = find_in_path('python') or 'python'
            else:
                python = sys.executable
            return [python, exe[:-4]]
        return [exe]

    def get_prog_root():
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def get_thg_command():
        if getattr(sys, 'frozen', False):
            return [sys.executable]
        return [sys.executable] + sys.argv[:1]

    def is_unc_path(path):
        unc, rest = os.path.splitunc(path)
        return bool(unc)

    def is_on_fixed_drive(path):
        if is_unc_path(path):
            # All UNC paths (\\host\mount) are considered not-fixed
            return False
        drive, remain = os.path.splitdrive(path)
        if drive:
            return win32file.GetDriveType(drive) == win32file.DRIVE_FIXED
        else:
            return False

else: # Not Windows

    def find_in_path(pgmname):
        """ return first executable found in search path """
        global bin_path
        ospath = os.environ['PATH'].split(os.pathsep)
        ospath.insert(0, bin_path or get_prog_root())
        for path in ospath:
            ppath = os.path.join(path, pgmname)
            if os.access(ppath, os.X_OK):
                return ppath
        return None

    def _find_hg_command():
        # look for in-place build, i.e. "make local"
        exe = os.path.join(_get_hg_path(), 'hg')
        if os.path.exists(exe):
            return [exe]

        exe = find_in_path('hg')
        if not exe:
            return ['hg']
        return [exe]

    def get_prog_root():
        path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return path

    def get_thg_command():
        return sys.argv[:1]

    def is_unc_path(path):
        return False

    def is_on_fixed_drive(path):
        return True

