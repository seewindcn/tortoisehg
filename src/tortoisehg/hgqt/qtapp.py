# qtapp.py - utility to start Qt application
#
# Copyright 2008 Steve Borho <steve@borho.org>
# Copyright 2008 TK Soh <teekaysoh@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import gc, os, platform, signal, sys, traceback

from PyQt4.QtCore import *
from PyQt4.QtGui import QApplication, QFont
from PyQt4.QtNetwork import QLocalServer, QLocalSocket

if os.name == 'nt' and getattr(sys, 'frozen', False):
    # load QtSvg4.dll and QtXml4.dll by .pyd, so that imageformats/qsvg4.dll
    # can find them without relying on unreliable PATH variable
    from PyQt4 import QtSvg, QtXml
    QtSvg.__name__, QtXml.__name__  # no demandimport, silence pyflakes

if PYQT_VERSION < 0x40600 or QT_VERSION < 0x40600:
    sys.stderr.write('TortoiseHg requires at least Qt 4.6 and PyQt 4.6\n')
    sys.stderr.write('You have Qt %s and PyQt %s\n' %
                     (QT_VERSION_STR, PYQT_VERSION_STR))
    sys.exit(-1)

from mercurial import error, util

from tortoisehg.util.i18n import _
from tortoisehg.util import hglib, i18n
from tortoisehg.util import version as thgversion
from tortoisehg.hgqt import bugreport, qtlib, thgrepo, workbench

if getattr(sys, 'frozen', False) and os.name == 'nt':
    # load icons and translations
    import icons_rc, translations_rc

try:
    from thginithook import thginithook
except ImportError:
    thginithook = None

# {exception class: message}
# It doesn't check the hierarchy of exception classes for simplicity.
_recoverableexc = {
    error.RepoLookupError: _('Try refreshing your repository.'),
    error.RevlogError:     _('Try refreshing your repository.'),
    error.ParseError: _('Error string "%(arg0)s" at %(arg1)s<br>Please '
                        '<a href="#edit:%(arg1)s">edit</a> your config'),
    error.ConfigError: _('Configuration Error: "%(arg0)s",<br>Please '
                         '<a href="#fix:%(arg0)s">fix</a> your config'),
    error.Abort: _('Operation aborted:<br><br>%(arg0)s.'),
    error.LockUnavailable: _('Repository is locked'),
    }

def earlyExceptionMsgBox(e):
    """Show message for recoverable error before the QApplication is started"""
    opts = {}
    opts['cmd'] = ' '.join(sys.argv[1:])
    opts['values'] = e
    opts['error'] = traceback.format_exc()
    opts['nofork'] = True
    errstring = _recoverableexc[e.__class__]
    if not QApplication.instance():
        main = QApplication(sys.argv)
    dlg = bugreport.ExceptionMsgBox(hglib.tounicode(str(e)), errstring, opts)
    dlg.exec_()

def earlyBugReport(e):
    """Show generic errors before the QApplication is started"""
    opts = {}
    opts['cmd'] = ' '.join(sys.argv[1:])
    opts['error'] = traceback.format_exc()
    if not QApplication.instance():
        main = QApplication(sys.argv)
    dlg = bugreport.BugReport(opts)
    dlg.exec_()

class ExceptionCatcher(QObject):
    """Catch unhandled exception raised inside Qt event loop"""

    _exceptionOccured = pyqtSignal(object, object, object)

    def __init__(self, ui, mainapp, parent=None):
        super(ExceptionCatcher, self).__init__(parent)
        self._ui = ui
        self._mainapp = mainapp
        self.errors = []

        # can be emitted by another thread; postpones it until next
        # eventloop of main (GUI) thread.
        self._exceptionOccured.connect(self.putexception,
                                       Qt.QueuedConnection)

        self._ui.debug('setting up excepthook\n')
        self._origexcepthook = sys.excepthook
        sys.excepthook = self.ehook
        self._originthandler = signal.signal(signal.SIGINT, self._inthandler)
        self._initWakeup()

    def release(self):
        if not self._origexcepthook:
            return
        self._ui.debug('restoring excepthook\n')
        sys.excepthook = self._origexcepthook
        self._origexcepthook = None
        signal.signal(signal.SIGINT, self._originthandler)
        self._originthandler = None
        self._releaseWakeup()

    def ehook(self, etype, evalue, tracebackobj):
        'Will be called by any thread, on any unhandled exception'
        if self._ui.debugflag:
            elist = traceback.format_exception(etype, evalue, tracebackobj)
            self._ui.debug(''.join(elist))
        self._exceptionOccured.emit(etype, evalue, tracebackobj)
        # not thread-safe to touch self.errors here

    @pyqtSlot(object, object, object)
    def putexception(self, etype, evalue, tracebackobj):
        'Enque exception info and display it later; run in main thread'
        if not self.errors:
            QTimer.singleShot(10, self.excepthandler)
        self.errors.append((etype, evalue, tracebackobj))

    @pyqtSlot()
    def excepthandler(self):
        'Display exception info; run in main (GUI) thread'
        try:
            self._showexceptiondialog()
        except:
            # make sure to quit mainloop first, so that it never leave
            # zombie process.
            self._mainapp.exit(1)
            self._printexception()
        finally:
            self.errors = []

    def _showexceptiondialog(self):
        opts = {}
        opts['cmd'] = ' '.join(sys.argv[1:])
        opts['error'] = ''.join(''.join(traceback.format_exception(*args))
                                for args in self.errors)
        etype, evalue = self.errors[0][:2]
        parent = self._mainapp.activeWindow()
        if (len(set(e[0] for e in self.errors)) == 1
            and etype in _recoverableexc):
            opts['values'] = evalue
            errstr = _recoverableexc[etype]
            if etype is error.Abort and evalue.hint:
                errstr = u''.join([errstr, u'<br><b>', _('hint:'),
                                   u'</b> %(arg1)s'])
                opts['values'] = [str(evalue), evalue.hint]
            dlg = bugreport.ExceptionMsgBox(hglib.tounicode(str(evalue)),
                                            errstr, opts, parent=parent)
            dlg.exec_()
        else:
            dlg = bugreport.BugReport(opts, parent=parent)
            dlg.exec_()

    def _printexception(self):
        for args in self.errors:
            traceback.print_exception(*args)

    def _inthandler(self, signum, frame):
        # QTimer makes sure to not enter new event loop in signal handler,
        # which will be invoked at random location.  Note that some windows
        # may show modal confirmation dialog in closeEvent().
        QTimer.singleShot(0, self._mainapp.closeAllWindows)

    if os.name == 'posix' and util.safehasattr(signal, 'set_wakeup_fd'):
        # Wake up Python interpreter via pipe so that SIGINT can be handled
        # immediately.  (http://qt-project.org/doc/qt-4.8/unix-signals.html)

        def _initWakeup(self):
            import fcntl
            rfd, wfd = os.pipe()
            for fd in (rfd, wfd):
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self._wakeupsn = QSocketNotifier(rfd, QSocketNotifier.Read, self)
            self._wakeupsn.activated.connect(self._handleWakeup)
            self._origwakeupfd = signal.set_wakeup_fd(wfd)

        def _releaseWakeup(self):
            self._wakeupsn.setEnabled(False)
            rfd = self._wakeupsn.socket()
            wfd = signal.set_wakeup_fd(self._origwakeupfd)
            self._origwakeupfd = -1
            os.close(rfd)
            os.close(wfd)

        @pyqtSlot()
        def _handleWakeup(self):
            # here Python signal handler will be invoked
            self._wakeupsn.setEnabled(False)
            rfd = self._wakeupsn.socket()
            try:
                os.read(rfd, 1)
            except OSError, inst:
                self._ui.debug('failed to read wakeup fd: %s\n' % inst)
            self._wakeupsn.setEnabled(True)

    else:
        # On Windows, non-blocking anonymous pipe or socket is not available.
        # So run Python instruction at a regular interval.  Because it wastes
        # CPU time, it is disabled if thg is known to be detached from tty.

        def _initWakeup(self):
            self._wakeuptimer = 0
            if self._ui.interactive():
                self._wakeuptimer = self.startTimer(200)

        def _releaseWakeup(self):
            if self._wakeuptimer > 0:
                self.killTimer(self._wakeuptimer)
                self._wakeuptimer = 0

        def timerEvent(self, event):
            # nop for instant SIGINT handling
            pass


class GarbageCollector(QObject):
    '''
    Disable automatic garbage collection and instead collect manually
    every INTERVAL milliseconds.

    This is done to ensure that garbage collection only happens in the GUI
    thread, as otherwise Qt can crash.
    '''

    INTERVAL = 5000

    def __init__(self, ui, parent):
        QObject.__init__(self, parent)
        self._ui = ui

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)

        self.threshold = gc.get_threshold()
        gc.disable()
        self.timer.start(self.INTERVAL)
        #gc.set_debug(gc.DEBUG_SAVEALL)

    def check(self):
        l0, l1, l2 = gc.get_count()
        if l0 > self.threshold[0]:
            num = gc.collect(0)
            self._ui.debug('GarbageCollector.check: %d %d %d\n' % (l0, l1, l2))
            self._ui.debug('collected gen 0, found %d unreachable\n' % num)
            if l1 > self.threshold[1]:
                num = gc.collect(1)
                self._ui.debug('collected gen 1, found %d unreachable\n' % num)
                if l2 > self.threshold[2]:
                    num = gc.collect(2)
                    self._ui.debug('collected gen 2, found %d unreachable\n'
                                   % num)

    def debug_cycles(self):
        gc.collect()
        for obj in gc.garbage:
            self._ui.debug('%s, %r, %s\n' % (obj, obj, type(obj)))


def allowSetForegroundWindow(processid=-1):
    """Allow a given process to set the foreground window"""
    # processid = -1 means ASFW_ANY (i.e. allow any process)
    if os.name == 'nt':
        # on windows we must explicitly allow bringing the main window to
        # the foreground. To do so we must use ctypes
        try:
            from ctypes import windll
            windll.user32.AllowSetForegroundWindow(processid)
        except ImportError:
            pass

def connectToExistingWorkbench(root, revset=None):
    """
    Connect and send data to an existing workbench server

    For the connection to be successful, the server must loopback the data
    that we send to it.

    Normally the data that is sent will be a repository root path, but we can
    also send "echo" to check that the connection works (i.e. that there is a
    server)
    """
    if revset:
        data = '\0'.join([root, revset])
    else:
        data = root
    servername = QApplication.applicationName() + '-' + util.getuser()
    socket = QLocalSocket()
    socket.connectToServer(servername, QIODevice.ReadWrite)
    if socket.waitForConnected(10000):
        # Momentarily let any process set the foreground window
        # The server process with revoke this permission as soon as it gets
        # the request
        allowSetForegroundWindow()
        socket.write(QByteArray(data))
        socket.flush()
        socket.waitForReadyRead(10000)
        reply = socket.readAll()
        if data == reply:
            return True
    elif socket.error() == QLocalSocket.ConnectionRefusedError:
        # last server process was crashed?
        QLocalServer.removeServer(servername)
    return False


def _fixapplicationfont():
    if os.name != 'nt':
        return
    try:
        import win32gui, win32con
    except ImportError:
        return

    # use configurable font like GTK, Mozilla XUL or Eclipse SWT
    ncm = win32gui.SystemParametersInfo(win32con.SPI_GETNONCLIENTMETRICS)
    lf = ncm['lfMessageFont']
    f = QFont(hglib.tounicode(lf.lfFaceName))
    f.setItalic(lf.lfItalic)
    if lf.lfWeight != win32con.FW_DONTCARE:
        weights = [(0, QFont.Light), (400, QFont.Normal), (600, QFont.DemiBold),
                   (700, QFont.Bold), (800, QFont.Black)]
        n, w = filter(lambda e: e[0] <= lf.lfWeight, weights)[-1]
        f.setWeight(w)
    f.setPixelSize(abs(lf.lfHeight))
    QApplication.setFont(f, 'QWidget')

def _gettranslationpath():
    """Return path to Qt's translation file (.qm)"""
    if getattr(sys, 'frozen', False) and os.name == 'nt':
        return ':/translations'
    else:
        return QLibraryInfo.location(QLibraryInfo.TranslationsPath)

class QtRunner(QObject):
    """Run Qt app and hold its windows

    NOTE: This object will be instantiated before QApplication, it means
    there's a limitation on Qt's event handling. See
    http://doc.qt.nokia.com/4.6/threads-qobject.html#per-thread-event-loop
    """

    def __init__(self):
        super(QtRunner, self).__init__()
        self._ui = None
        self._mainapp = None
        self._exccatcher = None
        self._server = None
        self._repomanager = None
        self._reporeleaser = None
        self._mainreporoot = None
        self._workbench = None

    def __call__(self, dlgfunc, ui, *args, **opts):
        if self._mainapp:
            self._opendialog(dlgfunc, args, opts)
            return

        QSettings.setDefaultFormat(QSettings.IniFormat)

        # fixes font placement on OSX 10.9 with QT <= 4.8.5
        # see QTBUG-32789 (https://bugreports.qt-project.org/browse/QTBUG-32789)
        if sys.platform == 'darwin' and QT_VERSION <= 0x040805:
            version = platform.mac_ver()[0]
            version = '.'.join(version.split('.')[:2])
            if version == '10.9':
                # needs to replace the font created in the constructor of
                # QApplication, which is invalid use of QFont but works on Mac
                QFont.insertSubstitution('.Lucida Grande UI', 'Lucida Grande')

        self._ui = ui
        self._mainapp = QApplication(sys.argv)
        self._exccatcher = ExceptionCatcher(ui, self._mainapp, self)
        self._gc = GarbageCollector(ui, self)

        # default org is used by QSettings
        self._mainapp.setApplicationName('TortoiseHgQt')
        self._mainapp.setOrganizationName('TortoiseHg')
        self._mainapp.setOrganizationDomain('tortoisehg.org')
        self._mainapp.setApplicationVersion(thgversion.version())
        self._fixlibrarypaths()
        self._installtranslator()
        QFont.insertSubstitutions('monospace', ['monaco', 'courier new'])
        _fixapplicationfont()
        qtlib.configstyles(ui)
        qtlib.initfontcache(ui)
        self._mainapp.setWindowIcon(qtlib.geticon('thg'))

        self._repomanager = thgrepo.RepoManager(ui, self)
        self._reporeleaser = releaser = QSignalMapper(self)
        releaser.mapped[unicode].connect(self._repomanager.releaseRepoAgent)

        # stop services after control returns to the main event loop
        self._mainapp.setQuitOnLastWindowClosed(False)
        self._mainapp.lastWindowClosed.connect(self._quitGracefully,
                                               Qt.QueuedConnection)

        dlg, reporoot = self._createdialog(dlgfunc, args, opts)
        self._mainreporoot = reporoot
        try:
            if dlg:
                dlg.show()
                dlg.raise_()
            else:
                if reporoot:
                    self._repomanager.releaseRepoAgent(reporoot)
                    self._mainreporoot = None
                return -1

            if thginithook is not None:
                thginithook()

            return self._mainapp.exec_()
        finally:
            self._exccatcher.release()
            self._mainapp = self._ui = None

    @pyqtSlot()
    def _quitGracefully(self):
        # won't be called if the application is quit by BugReport dialog
        if self._mainreporoot:
            self._repomanager.releaseRepoAgent(self._mainreporoot)
            self._mainreporoot = None
        if self._server:
            self._server.close()
        if self._tryQuit():
            return
        self._ui.debug('repositories are closing asynchronously\n')
        self._repomanager.repositoryClosed.connect(self._tryQuit)
        QTimer.singleShot(5000, self._mainapp.quit)  # in case of bug

    @pyqtSlot()
    def _tryQuit(self):
        if self._repomanager.repoRootPaths():
            return False
        self._mainapp.quit()
        return True

    def _fixlibrarypaths(self):
        # make sure to use the bundled Qt plugins to avoid ABI incompatibility
        # http://qt-project.org/doc/qt-4.8/deployment-windows.html#qt-plugins
        if os.name == 'nt' and getattr(sys, 'frozen', False):
            self._mainapp.setLibraryPaths([self._mainapp.applicationDirPath()])

    def _installtranslator(self):
        if not i18n.language:
            return
        t = QTranslator(self._mainapp)
        t.load('qt_' + i18n.language, _gettranslationpath())
        self._mainapp.installTranslator(t)

    def _createdialog(self, dlgfunc, args, opts):
        assert self._ui and self._repomanager
        reporoot = None
        try:
            args = list(args)
            if 'repository' in opts:
                repoagent = self._repomanager.openRepoAgent(
                    hglib.tounicode(opts['repository']))
                reporoot = repoagent.rootPath()
                args.insert(0, repoagent)
            return dlgfunc(self._ui, *args, **opts), reporoot
        except error.RepoError, inst:
            qtlib.WarningMsgBox(_('Repository Error'),
                                hglib.tounicode(str(inst)))
        except error.Abort, inst:
            qtlib.WarningMsgBox(_('Abort'),
                                hglib.tounicode(str(inst)),
                                hglib.tounicode(inst.hint or ''))
        if reporoot:
            self._repomanager.releaseRepoAgent(reporoot)
        return None, None

    def _opendialog(self, dlgfunc, args, opts):
        dlg, reporoot = self._createdialog(dlgfunc, args, opts)
        if not dlg:
            return

        dlg.setAttribute(Qt.WA_DeleteOnClose)
        if reporoot:
            dlg.destroyed[()].connect(self._reporeleaser.map)
            self._reporeleaser.setMapping(dlg, reporoot)
        if dlg is not self._workbench and not dlg.parent():
            # keep reference to avoid garbage collection.  workbench should
            # exist when run.dispatch() is called for the second time.
            assert self._workbench
            dlg.setParent(self._workbench, dlg.windowFlags())
        dlg.show()

    def createWorkbench(self):
        """Create Workbench window and keep single reference"""
        assert self._ui and self._mainapp and self._repomanager
        assert not self._workbench
        self._workbench = workbench.Workbench(self._ui, self._repomanager)
        return self._workbench

    @pyqtSlot(str)
    def openRepoInWorkbench(self, uroot):
        """Show the specified repository in Workbench; reuses the existing
        Workbench process"""
        assert self._ui
        singlewb = self._ui.configbool('tortoisehg', 'workbench.single', True)
        # only if the server is another process; otherwise it would deadlock
        if (singlewb and not self._server
            and connectToExistingWorkbench(hglib.fromunicode(uroot))):
            return
        self.showRepoInWorkbench(uroot)

    def showRepoInWorkbench(self, uroot, rev=-1):
        """Show the specified repository in Workbench"""
        assert self._mainapp
        if not self._workbench:
            self.createWorkbench()
            assert self._workbench

        wb = self._workbench
        wb.show()
        wb.activateWindow()
        wb.raise_()
        wb.showRepo(uroot)
        if rev != -1:
            wb.goto(hglib.fromunicode(uroot), rev)

    def createWorkbenchServer(self):
        assert self._mainapp
        assert not self._server
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handleNewConnection)
        self._server.listen(self._mainapp.applicationName() + '-' + util.getuser())

    @pyqtSlot()
    def _handleNewConnection(self):
        socket = self._server.nextPendingConnection()
        if socket:
            socket.waitForReadyRead(10000)
            data = str(socket.readAll())
            if data and data != '[echo]':
                args = data.split('\0', 1)
                if len(args) > 1:
                    uroot, urevset = map(hglib.tounicode, args)
                else:
                    uroot = hglib.tounicode(args[0])
                    urevset = None
                self.showRepoInWorkbench(uroot)

                wb = self._workbench
                if urevset:
                    wb.setRevsetFilter(uroot, urevset)

                # Bring the workbench window to the front
                # This assumes that the client process has
                # called allowSetForegroundWindow(-1) right before
                # sending the request
                wb.setWindowState(wb.windowState() & ~Qt.WindowMinimized
                                  | Qt.WindowActive)
                wb.show()
                wb.raise_()
                wb.activateWindow()
                # Revoke the blanket permission to set the foreground window
                allowSetForegroundWindow(os.getpid())

            socket.write(QByteArray(data))
            socket.flush()
