# bugreport.py - Report Python tracebacks to the user
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import sys
import re

from mercurial import encoding, extensions
from tortoisehg.util import hglib, version
from tortoisehg.util.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtNetwork import QNetworkAccessManager, QNetworkRequest
try:
    from PyQt4.Qsci import QSCINTILLA_VERSION_STR
except (ImportError, AttributeError, RuntimeError):
    # show BugReport dialog even if QScintilla is missing
    # or incompatible (RuntimeError: the sip module implements API v...)
    QSCINTILLA_VERSION_STR = '(unknown)'

def _safegetcwd():
    try:
        return os.getcwd()
    except OSError:
        return '.'

class BugReport(QDialog):

    def __init__(self, opts, parent=None):
        super(BugReport, self).__init__(parent)

        layout = QVBoxLayout()
        self.setLayout(layout)

        lbl = QLabel(_('Please report this bug to our '
            '<a href="%s">bug tracker</a>') %
            u'http://bitbucket.org/tortoisehg/thg/wiki/BugReport')
        lbl.setOpenExternalLinks(True)
        self.layout().addWidget(lbl)

        tb = QTextBrowser()
        self.text = self.gettext(opts)
        tb.setHtml('<pre>' + Qt.escape(self.text) + '</pre>')
        tb.setWordWrapMode(QTextOption.NoWrap)
        layout.addWidget(tb)

        self.download_url_lbl = QLabel(_('Checking for updates...'))
        self.download_url_lbl.setMouseTracking(True)
        self.download_url_lbl.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.download_url_lbl.setOpenExternalLinks(True)
        layout.addWidget(self.download_url_lbl)

        # dialog buttons
        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Save)
        bb.button(BB.Ok).clicked.connect(self.accept)
        bb.button(BB.Save).clicked.connect(self.save)
        bb.button(BB.Ok).setDefault(True)
        bb.addButton(_('Copy'), BB.HelpRole).clicked.connect(self.copyText)
        bb.addButton(_('Quit'), BB.DestructiveRole).clicked.connect(qApp.quit)
        layout.addWidget(bb)

        self.setWindowTitle(_('TortoiseHg Bug Report'))
        self.setWindowFlags(self.windowFlags() & \
                            ~Qt.WindowContextHelpButtonHint)
        self.resize(650, 400)
        self._readsettings()
        QTimer.singleShot(0, self.getUpdateInfo)

    def getUpdateInfo(self):
        verurl = 'http://tortoisehg.bitbucket.org/curversion.txt'
        # If we use QNetworkAcessManager elsewhere, it should be shared
        # through the application.
        self._netmanager = QNetworkAccessManager(self)
        self._newverreply = self._netmanager.get(QNetworkRequest(QUrl(verurl)))
        self._newverreply.finished.connect(self.uFinished)

    def uFinished(self):
        newver = (0,0,0)
        try:
            f = self._newverreply.readAll().data().splitlines()
            self._newverreply.close()
            self._newverreply = None
            newver = tuple([int(p) for p in f[0].split('.')])
            upgradeurl = f[1] # generic download URL
            platform = sys.platform
            if platform == 'win32':
                from win32process import IsWow64Process as IsX64
                platform = IsX64() and 'x64' or 'x86'
            # linux2 for Linux, darwin for OSX
            for line in f[2:]:
                p, _url = line.split(':', 1)
                if platform == p:
                    upgradeurl = _url.strip()
                    break
        except (IndexError, ImportError, ValueError):
            pass
        try:
            thgv = version.version()
            if '+' in thgv:
                thgv = thgv[:thgv.index('+')]
            curver = tuple([int(p) for p in thgv.split('.')])
        except ValueError:
            curver = (0,0,0)
        if newver > curver:
            url_lbl = _('Upgrading to a more recent TortoiseHg is recommended.')
            urldata = ('<a href=%s>%s</a>' % (upgradeurl, url_lbl))
            self.download_url_lbl.setText(urldata)
        else:
            self.download_url_lbl.setText(_('Your TortoiseHg is up to date.'))

    def gettext(self, opts):
        # TODO: make this more uniformly unicode safe
        text = '#!python\n' # Bitbucket wiki marker for python code
        text += '** Mercurial version (%s).  TortoiseHg version (%s)\n' % (
                hglib.hgversion, version.version())
        text += '** Command: %s\n' % (hglib.tounicode(opts.get('cmd', 'N/A')))
        text += '** CWD: %s\n' % hglib.tounicode(_safegetcwd())
        text += '** Encoding: %s\n' % encoding.encoding
        extlist = [x[0] for x in extensions.extensions()]
        text += '** Extensions loaded: %s\n' % ', '.join(extlist)
        text += '** Python version: %s\n' % sys.version.replace('\n', '')
        if os.name == 'nt':
            text += self.getarch()
        elif os.name == 'posix':
            text += '** System: %s\n' % hglib.tounicode(' '.join(os.uname()))
        text += ('** Qt-%s PyQt-%s QScintilla-%s\n'
                 % (QT_VERSION_STR, PYQT_VERSION_STR, QSCINTILLA_VERSION_STR))
        text += hglib.tounicode(opts.get('error', 'N/A'))
        # Bitbucket wiki marker for code: 4 spaces indent (Markdown syntax)
        regexp = re.compile(r'^', re.MULTILINE)
        text = regexp.sub(r'    ', text)
        return text

    def copyText(self):
        QApplication.clipboard().setText(self.text)

    def getarch(self):
        text = '** Windows version: %s\n' % str(sys.getwindowsversion())
        arch = 'unknown (failed to import win32api)'
        try:
            import win32api
            arch = 'unknown'
            archval = win32api.GetNativeSystemInfo()[0]
            if archval == 9:
                arch = 'x64'
            elif archval == 0:
                arch = 'x86'
        except (ImportError, AttributeError):
            pass
        text += '** Processor architecture: %s\n' % arch
        return text

    def save(self):
        try:
            fname = QFileDialog.getSaveFileName(self,
                        _('Save error report to'),
                        os.path.join(_safegetcwd(), 'bugreport.txt'),
                        _('Text files (*.txt)'))
            if fname:
                open(fname, 'wb').write(hglib.fromunicode(self.text))
        except (EnvironmentError), e:
            QMessageBox.critical(self, _('Error writing file'), str(e))

    def accept(self):
        self._writesettings()
        super(BugReport, self).accept()

    def reject(self):
        self._writesettings()
        super(BugReport, self).reject()

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('bugreport/geom').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('bugreport/geom', self.saveGeometry())

class ExceptionMsgBox(QDialog):
    """Message box for recoverable exception"""
    def __init__(self, main, text, opts, parent=None):
        super(ExceptionMsgBox, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle(_('TortoiseHg Error'))

        self._opts = opts

        labelflags = Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse

        self.setLayout(QVBoxLayout())

        if '%(arg' in text:
            values = opts.get('values', [])
            msgopts = {}
            for i, val in enumerate(values):
                msgopts['arg' + str(i)] = Qt.escape(hglib.tounicode(val))
            try:
                text = text % msgopts
            except Exception, e:
                print e, msgopts
        else:
            self._mainlabel = QLabel('<b>%s</b>' % Qt.escape(main),
                                     textInteractionFlags=labelflags)
            self.layout().addWidget(self._mainlabel)

        text = text + "<br><br>" + _('If you still have trouble, '
              '<a href="#bugreport">please file a bug report</a>.')
        self._textlabel = QLabel(text, wordWrap=True,
                                 textInteractionFlags=labelflags)
        self._textlabel.linkActivated.connect(self._openlink)
        self._textlabel.setWordWrap(False)
        self.layout().addWidget(self._textlabel)

        bb = QDialogButtonBox(QDialogButtonBox.Close, centerButtons=True)
        bb.rejected.connect(self.reject)
        self.layout().addWidget(bb)
        desktopgeom = qApp.desktop().availableGeometry()
        self.resize(desktopgeom.size() * 0.20)

    @pyqtSlot(str)
    def _openlink(self, ref):
        ref = str(ref)
        if ref == '#bugreport':
            return BugReport(self._opts, self).exec_()
        if ref.startswith('#edit:'):
            fname, lineno = ref[6:].rsplit(':', 1)
            try:
                # A chicken-egg problem here, we need a ui to get your
                # editor in order to repair your ui config file.
                from mercurial import ui as uimod
                from tortoisehg.hgqt import qtlib
                class FakeRepo(object):
                    def __init__(self):
                        self.root = os.getcwd()
                        self.ui = uimod.ui()
                fake = FakeRepo()
                qtlib.editfiles(fake, [fname], lineno, parent=self)
            except Exception, e:
                qtlib.openlocalurl(fname)
        if ref.startswith('#fix:'):
            from tortoisehg.hgqt import settings
            errtext = ref[5:].split(' ')[0]
            sd = settings.SettingsDialog(configrepo=False, focus=errtext,
                                parent=self, root='')
            sd.exec_()

def run(ui, *pats, **opts):
    return BugReport(opts)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    form = BugReport({'cmd':'cmd', 'error':'error'})
    form.show()
    app.exec_()
