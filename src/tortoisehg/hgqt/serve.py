# serve.py - TortoiseHg dialog to start web server
#
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, tempfile
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from mercurial import util, error
from tortoisehg.util import paths, wconfig, hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, qtlib
from tortoisehg.hgqt.serve_ui import Ui_ServeDialog
from tortoisehg.hgqt.webconf import WebconfForm

class ServeDialog(QDialog):
    """Dialog for serving repositories via web"""
    def __init__(self, ui, webconf, parent=None):
        super(ServeDialog, self).__init__(parent)
        self.setWindowFlags((self.windowFlags() | Qt.WindowMinimizeButtonHint)
                            & ~Qt.WindowContextHelpButtonHint)
        self.setWindowIcon(qtlib.geticon('hg-serve'))

        self._qui = Ui_ServeDialog()
        self._qui.setupUi(self)

        self._initwebconf(webconf)
        self._initcmd(ui)
        self._initactions()
        self._updateform()

    def _initcmd(self, ui):
        # TODO: forget old logs?
        self._log_edit = cmdui.LogWidget(self)
        self._qui.details_tabs.addTab(self._log_edit, _('Log'))
        # as of hg 3.0, hgweb does not cooperate with command-server channel
        self._agent = cmdcore.CmdAgent(ui, self, worker='proc')
        self._agent.outputReceived.connect(self._log_edit.appendLog)
        self._agent.busyChanged.connect(self._updateform)

    def _initwebconf(self, webconf):
        self._webconf_form = WebconfForm(webconf=webconf, parent=self)
        self._qui.details_tabs.addTab(self._webconf_form, _('Repositories'))

    def _initactions(self):
        self._qui.start_button.clicked.connect(self.start)
        self._qui.stop_button.clicked.connect(self.stop)

    @pyqtSlot()
    def _updateform(self):
        """update form availability and status text"""
        self._updatestatus()
        self._qui.start_button.setEnabled(not self.isstarted())
        self._qui.stop_button.setEnabled(self.isstarted())
        self._qui.settings_button.setEnabled(not self.isstarted())
        self._qui.port_edit.setEnabled(not self.isstarted())
        self._webconf_form.setEnabled(not self.isstarted())

    def _updatestatus(self):
        if self.isstarted():
            # TODO: escape special chars
            link = '<a href="%s">%s</a>' % (self.rooturl, self.rooturl)
            msg = _('Running at %s') % link
        else:
            msg = _('Stopped')

        self._qui.status_edit.setText(msg)

    @pyqtSlot()
    def start(self):
        """Start web server"""
        if self.isstarted():
            return

        self._agent.runCommand(map(hglib.tounicode, self._cmdargs()))

    def _cmdargs(self):
        """Build command args to run server"""
        a = ['serve', '--port', str(self.port), '-v']
        if self._singlerepo:
            a += ['-R', self._singlerepo]
        else:
            a += ['--web-conf', self._tempwebconf()]
        return a

    def _tempwebconf(self):
        """Save current webconf to temporary file; return its path"""
        if not hasattr(self._webconf, 'write'):
            return self._webconf.path

        fd, fname = tempfile.mkstemp(prefix='webconf_', dir=qtlib.gettempdir())
        f = os.fdopen(fd, 'w')
        try:
            self._webconf.write(f)
            return fname
        finally:
            f.close()

    @property
    def _webconf(self):
        """Selected webconf object"""
        return self._webconf_form.webconf

    @property
    def _singlerepo(self):
        """Return repository path if serving single repository"""
        # NOTE: we cannot use web-conf to serve single repository at '/' path
        if len(self._webconf['paths']) != 1:
            return
        path = self._webconf.get('paths', '/')
        if path and '*' not in path:  # exactly a single repo (no wildcard)
            return path

    @pyqtSlot()
    def stop(self):
        """Stop web server"""
        self._agent.abortCommands()

    def reject(self):
        self.stop()
        super(ServeDialog, self).reject()

    def isstarted(self):
        """Is the web server running?"""
        return self._agent.isBusy()

    @property
    def rooturl(self):
        """Returns the root URL of the web server"""
        # TODO: scheme, hostname ?
        return 'http://localhost:%d' % self.port

    @property
    def port(self):
        """Port number of the web server"""
        return int(self._qui.port_edit.value())

    def setport(self, port):
        self._qui.port_edit.setValue(port)

    def keyPressEvent(self, event):
        if self.isstarted() and event.key() == Qt.Key_Escape:
            self.stop()
            return

        return super(ServeDialog, self).keyPressEvent(event)

    def closeEvent(self, event):
        if self.isstarted():
            self._minimizetotray()
            event.ignore()
            return

        return super(ServeDialog, self).closeEvent(event)

    @util.propertycache
    def _trayicon(self):
        icon = QSystemTrayIcon(self.windowIcon(), parent=self)
        icon.activated.connect(self._restorefromtray)
        icon.setToolTip(self.windowTitle())
        # TODO: context menu
        return icon

    # TODO: minimize to tray by minimize button

    @pyqtSlot()
    def _minimizetotray(self):
        self._trayicon.show()
        self._trayicon.showMessage(_('TortoiseHg Web Server'),
                                   _('Running at %s') % self.rooturl)
        self.hide()

    @pyqtSlot()
    def _restorefromtray(self):
        self._trayicon.hide()
        self.show()

    @pyqtSlot()
    def on_settings_button_clicked(self):
        from tortoisehg.hgqt import settings
        settings.SettingsDialog(parent=self, focus='web.name').exec_()


def _asconfigliststr(value):
    r"""
    >>> _asconfigliststr('foo')
    'foo'
    >>> _asconfigliststr('foo bar')
    '"foo bar"'
    >>> _asconfigliststr('foo,bar')
    '"foo,bar"'
    >>> _asconfigliststr('foo "bar"')
    '"foo \\"bar\\""'
    """
    # ui.configlist() uses isspace(), which is locale-dependent
    if any(c.isspace() or c == ',' for c in value):
        return '"' + value.replace('"', '\\"') + '"'
    else:
        return value

def _readconfig(ui, repopath, webconfpath):
    """Create new ui and webconf object and read appropriate files"""
    lui = ui.copy()
    if webconfpath:
        lui.readconfig(webconfpath)
        # TODO: handle file not found
        c = wconfig.readfile(webconfpath)
        c.path = os.path.abspath(webconfpath)
        return lui, c
    elif repopath:  # imitate webconf for single repo
        lui.readconfig(os.path.join(repopath, '.hg', 'hgrc'), repopath)
        c = wconfig.config()
        try:
            if not os.path.exists(os.path.join(repopath, '.hgsub')):
                # no _asconfigliststr(repopath) for now, because ServeDialog
                # cannot parse it as a list in single-repo mode.
                c.set('paths', '/', repopath)
            else:
                # since hg 8cbb59124e67, path entry is parsed as a list
                base = hglib.shortreponame(lui) or os.path.basename(repopath)
                c.set('paths', base,
                      _asconfigliststr(os.path.join(repopath, '**')))
        except (EnvironmentError, error.Abort, error.RepoError):
            c.set('paths', '/', repopath)
        return lui, c
    else:
        return lui, None

def run(ui, *pats, **opts):
    repopath = opts.get('root') or paths.find_root()
    webconfpath = opts.get('web_conf') or opts.get('webdir_conf')

    lui, webconf = _readconfig(ui, repopath, webconfpath)
    dlg = ServeDialog(lui, webconf=webconf)
    try:
        dlg.setport(int(lui.config('web', 'port', '8000')))
    except ValueError:
        pass

    if repopath or webconfpath:
        dlg.start()
    return dlg
