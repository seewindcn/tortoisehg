# win32ill.py - listen to WM_CLOSE to shutdown cleanly
#
# Copyright 2014 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

"""listen to WM_CLOSE to shutdown cleanly

In short, this extension provides alternative to `kill pid` on Windows.

Background:

Windows cannot send Ctrl-C signal to CLI process without a console window, which
means there is no easy way to abort `hg push` safely from your application.
`GenerateConsoleCtrlEvent()` is very attractive, but look now, it's just able
to signal `CTRL_C_EVENT` to all processes sharing the console.

This extension spawns a thread to listen to `WM_CLOSE` message, and generates
`CTRL_C_EVENT` to itself on `WM_CLOSE`.

- http://stackoverflow.com/questions/1453520/
- http://msdn.microsoft.com/en-us/library/windows/desktop/ms683155(v=vs.85).aspx
- http://support.microsoft.com/kb/178893/en-us

Caveats:

- Make sure to set `CREATE_NO_WINDOW` or `CREATE_NEW_CONSOLE` to
  `dwCreationFlags` when creating hg process; otherwise the master process
  will also receive `CTRL_C_EVENT`.
- If the master process communicates with the sub hg process via stdio, the
  master also needs to close the write channel of the sub.
- Blocking winsock calls cannot be interrupted as Ctrl-C in `cmd.exe` has no
  effect.
"""

import atexit, ctypes, os, threading

from mercurial import util

from tortoisehg.util import hgversion
from tortoisehg.util.i18n import agettext as _

testedwith = hgversion.testedwith

_CTRL_C_EVENT = 0
_WM_APP = 0x8000
_WM_CLOSE = 0x0010
_WM_DESTROY = 0x0002
_WS_EX_NOACTIVATE = 0x08000000
_WS_POPUP = 0x80000000

_WM_STOPMESSAGELOOP = _WM_APP + 0

def _errcheckbool(result, func, args):
    if not result:
        raise ctypes.WinError()
    return args

def _errcheckminus1(result, func, args):
    if result == -1:
        raise ctypes.WinError()
    return args

if os.name == 'nt':
    from ctypes import wintypes

    _ATOM = wintypes.ATOM
    _BOOL = wintypes.BOOL
    _DWORD = wintypes.DWORD
    _HBRUSH = wintypes.HBRUSH
    _HCURSOR = wintypes.HICON
    _HICON = wintypes.HICON
    _HINSTANCE = wintypes.HINSTANCE
    _HMENU = wintypes.HMENU
    _HMODULE = wintypes.HMODULE
    _HWND = wintypes.HWND
    _LPARAM = wintypes.LPARAM
    _LPCTSTR = wintypes.LPCSTR
    _LPVOID = wintypes.LPVOID
    _LRESULT = wintypes.LPARAM  # LRESULT and LPARAM are defined as LONG_PTR
    _MSG = wintypes.MSG
    _UINT = wintypes.UINT
    _WPARAM = wintypes.WPARAM

    _WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, _HWND, _UINT, _WPARAM, _LPARAM)

    class _WNDCLASS(ctypes.Structure):
        _fields_ = [
            ('style', _UINT),
            ('lpfnWndProc', _WNDPROC),
            ('cbClsExtra', ctypes.c_int),
            ('cbWndExtra', ctypes.c_int),
            ('hInstance', _HINSTANCE),
            ('hIcon', _HICON),
            ('hCursor', _HCURSOR),
            ('hbrBackground', _HBRUSH),
            ('lpszMenuName', _LPCTSTR),
            ('lpszClassName', _LPCTSTR),
            ]

    _CreateWindowEx = ctypes.windll.user32.CreateWindowExA
    _CreateWindowEx.restype = _HWND
    _CreateWindowEx.argtypes = (_DWORD, _LPCTSTR, _LPCTSTR, _DWORD,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, _HWND, _HMENU, _HINSTANCE,
                                _LPVOID)
    _CreateWindowEx.errcheck = _errcheckbool

    _DefWindowProc = ctypes.windll.user32.DefWindowProcA
    _DefWindowProc.restype = _LRESULT
    _DefWindowProc.argtypes = (_HWND, _UINT, _WPARAM, _LPARAM)

    _DestroyWindow = ctypes.windll.user32.DestroyWindow
    _DestroyWindow.restype = _BOOL
    _DestroyWindow.argtypes = (_HWND,)
    _DestroyWindow.errcheck = _errcheckbool

    _DispatchMessage = ctypes.windll.user32.DispatchMessageA
    _DispatchMessage.restype = _LRESULT
    _DispatchMessage.argtypes = (ctypes.POINTER(_MSG),)

    _GenerateConsoleCtrlEvent = ctypes.windll.kernel32.GenerateConsoleCtrlEvent
    _GenerateConsoleCtrlEvent.restype = _BOOL
    _GenerateConsoleCtrlEvent.argtypes = (_DWORD, _DWORD)
    _GenerateConsoleCtrlEvent.errcheck = _errcheckbool

    _GetMessage = ctypes.windll.user32.GetMessageA
    _GetMessage.restype = _BOOL  # -1, 0, or non-zero
    _GetMessage.argtypes = (ctypes.POINTER(_MSG), _HWND, _UINT, _UINT)
    _GetMessage.errcheck = _errcheckminus1

    _GetModuleHandle = ctypes.windll.kernel32.GetModuleHandleA
    _GetModuleHandle.restype = _HMODULE
    _GetModuleHandle.argtypes = (_LPCTSTR,)
    _GetModuleHandle.errcheck = _errcheckbool

    _PostQuitMessage = ctypes.windll.user32.PostQuitMessage
    _PostQuitMessage.restype = None
    _PostQuitMessage.argtypes = (ctypes.c_int,)

    _PostMessage = ctypes.windll.user32.PostMessageA
    _PostMessage.restype = _BOOL
    _PostMessage.argtypes = (_HWND, _UINT, _WPARAM, _LPARAM)
    _PostMessage.errcheck = _errcheckbool

    _RegisterClass = ctypes.windll.user32.RegisterClassA
    _RegisterClass.restype = _ATOM
    _RegisterClass.argtypes = (ctypes.POINTER(_WNDCLASS),)
    _RegisterClass.errcheck = _errcheckbool

    _TranslateMessage = ctypes.windll.user32.TranslateMessage
    _TranslateMessage.restype = _BOOL
    _TranslateMessage.argtypes = (ctypes.POINTER(_MSG),)

class messageserver(object):

    def __init__(self, logfile):
        self._logfile = logfile
        self._thread = threading.Thread(target=self._mainloop)
        self._thread.setDaemon(True)  # skip global join before atexit
        self._wndcreated = threading.Event()
        self._hwnd = None
        self._wndclass = wc = _WNDCLASS()
        wc.lpfnWndProc = _WNDPROC(self._wndproc)
        wc.hInstance = _GetModuleHandle(None)
        wc.lpszClassName = 'HgMessage'
        _RegisterClass(ctypes.byref(wc))

    def start(self):
        if self._hwnd:
            raise RuntimeError('window already created')
        self._wndcreated.clear()
        self._thread.start()
        self._wndcreated.wait()
        if not self._hwnd:
            raise util.Abort(_('win32ill: cannot create window for messages'))

    def stop(self):
        hwnd = self._hwnd
        if hwnd:
            _PostMessage(hwnd, _WM_STOPMESSAGELOOP, 0, 0)
            self._thread.join()

    def _log(self, msg):
        if not self._logfile:
            return
        self._logfile.write(msg + '\n')
        self._logfile.flush()

    def _mainloop(self):
        try:
            # no HWND_MESSAGE so that it can be found by EnumWindows
            # WS_EX_NOACTIVATE and WS_POPUP exist just for strictness
            self._hwnd = _CreateWindowEx(
                _WS_EX_NOACTIVATE,  # dwExStyle
                self._wndclass.lpszClassName,
                None,  # lpWindowName
                _WS_POPUP,  # dwStyle
                0, 0, 0, 0,  # x, y, nWidth, nHeight
                None,  # hWndParent
                None,  # hMenu
                _GetModuleHandle(None),  # hInstance
                None)  # lpParam
        finally:
            self._wndcreated.set()

        self._log('starting message loop (pid = %d)' % os.getpid())
        msg = _MSG()
        lpmsg = ctypes.byref(msg)
        while _GetMessage(lpmsg, None, 0, 0):
            _TranslateMessage(lpmsg)
            _DispatchMessage(lpmsg)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == _WM_CLOSE:
            self._log('received WM_CLOSE')
            # dwProcessGroupId=0 means all processes sharing the same console,
            # which is the only choice for CTRL_C_EVENT.
            _GenerateConsoleCtrlEvent(_CTRL_C_EVENT, 0)
            return 0
        if msg == _WM_STOPMESSAGELOOP and self._hwnd:
            self._log('destroying window')
            _DestroyWindow(self._hwnd)
            self._hwnd = None
        if msg == _WM_DESTROY:
            self._log('received WM_DESTROY')
            _PostQuitMessage(0)
            return 0
        return _DefWindowProc(hwnd, msg, wparam, lparam)

def _openlogfile(ui):
    log = ui.config('win32ill', 'log')
    if log == '-':
        return ui.ferr
    elif log:
        return open(log, 'a')

def uisetup(ui):
    if os.name != 'nt':
        ui.warn(_('win32ill: unsupported platform: %s\n') % os.name)
        return
    # message loop is per process
    sv = messageserver(_openlogfile(ui))
    def stop():
        try:
            sv.stop()
        except KeyboardInterrupt:
            # can happen if command finished just before WM_CLOSE request
            ui.warn(_('win32ill: interrupted while stopping message loop\n'))
    atexit.register(stop)
    sv.start()
