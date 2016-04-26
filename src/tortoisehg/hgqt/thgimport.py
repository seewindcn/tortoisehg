# thgimport.py - Import dialog for TortoiseHg
#
# Copyright 2009 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 David Wilhelm <dave@jumbledpile.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import shutil
import tempfile

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdui, cslist, qtlib, commit

_FILE_FILTER = "%s;;%s" % (_("Patch files (*.diff *.patch)"),
                           _("All files (*)"))

def _writetempfile(text):
    fd, filename = tempfile.mkstemp(suffix='.patch', prefix='thg-import-',
                                    dir=qtlib.gettempdir())
    try:
        os.write(fd, text)
    finally:
        os.close(fd)
    return filename

# TODO: handle --mq options from command line or MQ widget

class ImportDialog(QDialog):
    """Dialog to import patches"""

    def __init__(self, repoagent, parent, **opts):
        super(ImportDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint
                            | Qt.WindowMaximizeButtonHint)
        self.setWindowTitle(_('Import - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-import'))

        self._repoagent = repoagent

        # base layout box
        box = QVBoxLayout()
        box.setSpacing(6)
        self.setLayout(box)

        ## main layout grid
        self.grid = grid = QGridLayout()
        grid.setSpacing(6)
        box.addLayout(grid, 1)

        ### source input
        self.src_combo = QComboBox()
        self.src_combo.setEditable(True)
        self.src_combo.setMinimumWidth(310)
        self.file_btn = QPushButton(_('Browse...'))
        self.file_btn.setAutoDefault(False)
        self.file_btn.clicked.connect(self.browsefiles)
        self.dir_btn = QPushButton(_('Browse Directory...'))
        self.dir_btn.setAutoDefault(False)
        self.dir_btn.clicked.connect(self.browsedir)
        self.clip_btn = QPushButton(_('Import from Clipboard'))
        self.clip_btn.setAutoDefault(False)
        self.clip_btn.clicked.connect(self.getcliptext)
        grid.addWidget(QLabel(_('Source:')), 0, 0)
        grid.addWidget(self.src_combo, 0, 1)
        srcbox = QHBoxLayout()
        srcbox.addWidget(self.file_btn)
        srcbox.addWidget(self.dir_btn)
        srcbox.addWidget(self.clip_btn)
        grid.addLayout(srcbox, 1, 1)
        self.p0chk = QCheckBox(_('Do not strip paths (-p0), '
                                 'required for SVN patches'))
        grid.addWidget(self.p0chk, 2, 1, Qt.AlignLeft)

        ### patch list
        self.cslist = cslist.ChangesetList(self.repo)
        cslistrow = 4
        cslistcol = 1
        grid.addWidget(self.cslist, cslistrow, cslistcol)
        grid.addWidget(QLabel(_('Preview:')), 3, 0, Qt.AlignLeft | Qt.AlignTop)
        statbox = QHBoxLayout()
        self.status = QLabel("")
        statbox.addWidget(self.status)
        self.targetcombo = QComboBox()
        self.targetcombo.addItem(_('Repository'), ('import',))
        self.targetcombo.addItem(_('Shelf'), ('copy',))
        self.targetcombo.addItem(_('Working Directory'),
                                 ('import', '--no-commit'))
        cur = self.repo.thgactivemqname
        if cur:
            self.targetcombo.addItem(hglib.tounicode(cur), ('qimport',))
        self.targetcombo.currentIndexChanged.connect(self._updatep0chk)
        statbox.addWidget(self.targetcombo)
        grid.addLayout(statbox, 3, 1)

        ## command widget
        self._cmdcontrol = cmd = cmdui.CmdSessionControlWidget(self)
        cmd.finished.connect(self.done)
        cmd.linkActivated.connect(self.commitActivated)
        box.addWidget(cmd)

        cmd.showStatusMessage(_('Checking working directory status...'))
        QTimer.singleShot(0, self.checkStatus)

        self._runbutton = cmd.addButton(_('&Import'),
                                        QDialogButtonBox.AcceptRole)
        self._runbutton.clicked.connect(self._runCommand)

        grid.setRowStretch(cslistrow, 1)
        grid.setColumnStretch(cslistcol, 1)

        # signal handlers
        self.src_combo.editTextChanged.connect(self.preview)
        self.p0chk.toggled.connect(self.preview)

        # prepare to show
        self.src_combo.lineEdit().selectAll()
        self._updatep0chk()
        self.preview()

    ### Private Methods ###

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def commitActivated(self):
        dlg = commit.CommitDialog(self._repoagent, [], {}, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        self.checkStatus()

    def checkStatus(self):
        self.repo.dirstate.invalidate()
        wctx = self.repo[None]
        M, A, R = wctx.status()[:3]
        if M or A or R:
            text = _('Working directory is not clean!  '
                     '<a href="view">View changes...</a>')
            self._cmdcontrol.showStatusMessage(text)
        else:
            self._cmdcontrol.showStatusMessage('')

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Refresh):
            self.checkStatus()
        else:
            return super(ImportDialog, self).keyPressEvent(event)

    def browsefiles(self):
        caption = _("Select patches")
        filelist = QFileDialog.getOpenFileNames(self, caption,
                                                self._repoagent.rootPath(),
                                                _FILE_FILTER)
        if filelist:
            # Qt file browser uses '/' in paths, even on Windows.
            nl = [unicode(QDir.toNativeSeparators(x)) for x in filelist]
            self.src_combo.setEditText(os.pathsep.join(nl))
            self.src_combo.setFocus()

    def browsedir(self):
        caption = _("Select Directory containing patches")
        path = QFileDialog.getExistingDirectory(self, caption,
                                                self._repoagent.rootPath())
        if path:
            self.src_combo.setEditText(QDir.toNativeSeparators(path))
            self.src_combo.setFocus()

    def getcliptext(self):
        mdata = QApplication.clipboard().mimeData()
        if mdata.hasFormat('text/x-diff'):  # lossless
            text = str(mdata.data('text/x-diff'))
        elif mdata.hasText():  # could be encoding damaged
            text = hglib.fromunicode(mdata.text(), errors='ignore')
        else:
            return
        filename = _writetempfile(text)
        curtext = self.src_combo.currentText()
        if curtext:
            self.src_combo.setEditText(curtext + os.pathsep + filename)
        else:
            self.src_combo.setEditText(filename)

    def _targetcommand(self):
        index = self.targetcombo.currentIndex()
        return self.targetcombo.itemData(index).toPyObject()

    @pyqtSlot()
    def _updatep0chk(self):
        cmd = self._targetcommand()[0]
        self.p0chk.setEnabled(cmd == 'import')
        if not self.p0chk.isEnabled():
            self.p0chk.setChecked(False)

    def updatestatus(self):
        items = self.cslist.curitems
        count = items and len(items) or 0
        countstr = qtlib.markup(_("%s patches") % count, weight='bold')
        if count:
            self.targetcombo.setVisible(True)
            text = _('%s will be imported to ') % countstr
        else:
            self.targetcombo.setVisible(False)
            text = qtlib.markup(_('Nothing to import'), weight='bold',
                                fg='red')
        self.status.setText(text)

    def preview(self):
        patches = self.getfilepaths()
        if not patches:
            self.cslist.clear()
        else:
            self.cslist.update([os.path.abspath(p) for p in patches])
        self.updatestatus()
        self._updateUi()

    def getfilepaths(self):
        src = hglib.fromunicode(self.src_combo.currentText())
        if not src:
            return []
        files = []
        for path in src.split(os.pathsep):
            path = path.strip('\r\n\t ')
            if not os.path.exists(path) or path in files:
                continue
            if os.path.isfile(path):
                files.append(path)
            elif os.path.isdir(path):
                entries = os.listdir(path)
                for entry in sorted(entries):
                    _file = os.path.join(path, entry)
                    if os.path.isfile(_file) and not _file in files:
                        files.append(_file)
        return files

    def setfilepaths(self, paths):
        """Set file paths of patches to import; paths is in locale encoding"""
        self.src_combo.setEditText(
            os.pathsep.join(hglib.tounicode(p) for p in paths))

    @pyqtSlot()
    def _runCommand(self):
        if self.cslist.curitems is None:
            return
        cmdline = map(str, self._targetcommand())
        if cmdline == ['copy']:
            # import to shelf
            self.repo.thgshelves()  # initialize repo.shelfdir
            if not os.path.exists(self.repo.shelfdir):
                os.mkdir(self.repo.shelfdir)
            for file in self.cslist.curitems:
                shutil.copy(file, self.repo.shelfdir)
            return

        if self.p0chk.isChecked():
            cmdline.append('-p0')
        cmdline.extend(['--verbose', '--'])
        cmdline.extend(map(hglib.tounicode, self.cslist.curitems))
        sess = self._repoagent.runCommand(cmdline, self)
        self._cmdcontrol.setSession(sess)
        sess.commandFinished.connect(self._onCommandFinished)
        self._updateUi()

    @pyqtSlot(int)
    def _onCommandFinished(self, ret):
        self._updateUi()
        if ret == 0:
            self._runbutton.hide()
            self._cmdcontrol.setFocusToCloseButton()
        elif not self._cmdcontrol.session().isAborted():
            cmdui.errorMessageBox(self._cmdcontrol.session(), self)
        if ret == 0 and not self._cmdcontrol.isLogVisible():
            self._cmdcontrol.reject()

    def reject(self):
        self._cmdcontrol.reject()

    def _updateUi(self):
        self._runbutton.setEnabled(bool(self.getfilepaths())
                                   and self._cmdcontrol.session().isFinished())
