# debugthg.py - debugging library for TortoiseHg shell extensions
#
# Copyright 2008 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

debugging = ''
try:
    import _winreg
    try:
        hkey = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER,
                           r"Software\TortoiseHg", 0,
                           _winreg.KEY_ALL_ACCESS)
        val = _winreg.QueryValueEx(hkey, 'OverlayDebug')[0]
        if val in ('1', 'True'):
            debugging += 'O'
        val = _winreg.QueryValueEx(hkey, 'ContextMenuDebug')[0]
        if val in ('1', 'True'):
            debugging += 'M'
        if debugging:
            import win32traceutil
    except EnvironmentError:
        pass
except ImportError:
    import os
    debugging = os.environ.get("DEBUG_THG", "")
    if debugging.lower() in ("1", "true"):
        debugging = True

def debugf_No(str, args=None, level=''):
    pass

if debugging:
    def debug(level=''):
        return debugging == True or level in debugging
    def debugf(str, args=None, level=''):
        if not debug(level):
            return
        if args:
            print str % args
        elif debug('e') and isinstance(str, BaseException):
            import traceback
            traceback.print_exc()
        else:
            print str
else:
    def debug(level=''):
        return False
    debugf = debugf_No
