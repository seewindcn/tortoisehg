# rename.py - TortoiseHg's dialogs for handling renames
#
# Copyright 2009 Steve Borho <steve@borho.org>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, sys

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import util

from tortoisehg.hgqt import cmdcore, cmdui, qtlib, manifestmodel
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _

class RenameWidget(cmdui.AbstractCmdWidget):

    def __init__(self, repoagent, parent=None, source=None, destination=None,
                 iscopy=False):
        super(RenameWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._repoagent = repoagent

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.setLayout(form)

        # widgets
        self.src_txt = QLineEdit(source or '')
        self.src_txt.setMinimumWidth(300)
        self.src_btn = QPushButton(_('Browse...'))
        self.dest_txt = QLineEdit(destination or source or '')
        self.dest_btn = QPushButton(_('Browse...'))
        # use QCompleter(model, parent) to avoid ownership bug of
        # QCompleter(parent /TransferBack/) in PyQt<4.11.4
        comp = manifestmodel.ManifestCompleter(None, self)
        comp.setModel(manifestmodel.ManifestModel(repoagent, comp))
        for lbl, txt, btn in [
                (_('Source:'), self.src_txt, self.src_btn),
                (_('Destination:'), self.dest_txt, self.dest_btn)]:
            box = QHBoxLayout()
            box.addWidget(txt, 1)
            box.addWidget(btn)
            form.addRow(lbl, box)
            txt.setCompleter(comp)

        self.copy_chk = QCheckBox(_('Copy source -> destination'))
        form.addRow('', self.copy_chk)

        # some extras
        form.addRow(QLabel(''))
        self.hgcmd_txt = QLineEdit()
        self.hgcmd_txt.setReadOnly(True)
        form.addRow(_('Hg command:'), self.hgcmd_txt)
        self.show_command(self.compose_command())

        # connecting slots
        self.src_txt.textChanged.connect(self.src_dest_edited)
        self.src_btn.clicked.connect(self.src_btn_clicked)
        self.dest_txt.textChanged.connect(self.src_dest_edited)
        self.dest_btn.clicked.connect(self.dest_btn_clicked)
        self.copy_chk.toggled.connect(self.copy_chk_toggled)

        # dialog setting
        self.copy_chk.setChecked(iscopy)
        self.dest_txt.setFocus()
        self.setRenameCopy()

    def setRenameCopy(self):
        if self.copy_chk.isChecked():
            self.msgTitle = _('Copy')
            self.errTitle = _('Copy Error')
        else:
            self.msgTitle = _('Rename')
            self.errTitle = _('Rename Error')

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def source(self):
        return unicode(self.src_txt.text())

    def destination(self):
        return unicode(self.dest_txt.text())

    def _sourceFile(self):
        root = self._repoagent.rootPath()
        return os.path.normpath(os.path.join(root, self.source()))

    def _destinationFile(self):
        root = self._repoagent.rootPath()
        return os.path.normpath(os.path.join(root, self.destination()))

    def src_dest_edited(self):
        self.show_command(self.compose_command())
        self.commandChanged.emit()

    def src_btn_clicked(self):
        """Select the source file of folder"""
        FD = QFileDialog
        if os.path.isfile(self._sourceFile()):
            caption = _('Select Source File')
            path = FD.getOpenFileName(self, caption, '', '', None, FD.ReadOnly)
        else:
            caption = _('Select Source Folder')
            path = FD.getExistingDirectory(self, caption, '',
                                           FD.ShowDirsOnly | FD.ReadOnly)
        relpath = self.to_relative_path(path)
        if not relpath:
            return
        self.src_txt.setText(relpath)

    def dest_btn_clicked(self):
        """Select the destination file of folder"""
        FD = QFileDialog
        if os.path.isfile(self._sourceFile()):
            caption = _('Select Destination File')
        else:
            caption = _('Select Destination Folder')
        path = FD.getSaveFileName(self, caption)
        relpath = self.to_relative_path(path)
        if not relpath:
            return
        self.dest_txt.setText(relpath)

    def to_relative_path(self, fullpath):  # unicode or QString
        if not fullpath:
            return
        fullpath = util.normpath(unicode(fullpath))
        pathprefix = util.normpath(hglib.tounicode(self.repo.root)) + '/'
        if not os.path.normcase(fullpath).startswith(os.path.normcase(pathprefix)):
            return
        return fullpath[len(pathprefix):]

    def isCopyCommand(self):
        return self.copy_chk.isChecked()

    def copy_chk_toggled(self):
        self.setRenameCopy()
        self.show_command(self.compose_command())
        self.commandChanged.emit()

    def isCaseFoldingOnWin(self):
        fullsrc, fulldest = self._sourceFile(), self._destinationFile()
        return (fullsrc.upper() == fulldest.upper() and sys.platform == 'win32')

    def compose_command(self):
        name = self.isCopyCommand() and 'copy' or 'rename'
        return hglib.buildcmdargs(name, self.source(), self.destination(),
                                  v=True, f=True)

    def show_command(self, cmdline):
        self.hgcmd_txt.setText('hg %s' % hglib.prettifycmdline(cmdline))

    def canRunCommand(self):
        src, dest = self.source(), self.destination()
        return bool(src and dest and src != dest
                    and not (self.isCopyCommand()
                             and self.isCaseFoldingOnWin()))

    def runCommand(self):
        # check inputs
        fullsrc, fulldest = self._sourceFile(), self._destinationFile()
        if not os.path.exists(fullsrc):
            qtlib.WarningMsgBox(self.msgTitle, _('Source does not exist.'))
            return cmdcore.nullCmdSession()
        if not fullsrc.startswith(self._repoagent.rootPath()):
            qtlib.ErrorMsgBox(self.errTitle,
                    _('The source must be within the repository tree.'))
            return cmdcore.nullCmdSession()
        if not fulldest.startswith(self._repoagent.rootPath()):
            qtlib.ErrorMsgBox(self.errTitle,
                    _('The destination must be within the repository tree.'))
            return cmdcore.nullCmdSession()
        if os.path.isfile(fulldest) and not self.isCaseFoldingOnWin():
            res = qtlib.QuestionMsgBox(self.msgTitle, '<p>%s</p><p>%s</p>' %
                    (_('Destination file already exists.'),
                    _('Are you sure you want to overwrite it ?')),
                    defaultbutton=QMessageBox.No)
            if not res:
                return cmdcore.nullCmdSession()

        cmdline = self.compose_command()
        self.show_command(cmdline)
        return self._repoagent.runCommand(cmdline, self)


class RenameDialog(cmdui.CmdControlDialog):

    def __init__(self, repoagent, parent=None, source=None, destination=None,
                 iscopy=False):
        super(RenameDialog, self).__init__(parent)
        self._repoagent = repoagent

        self.setWindowIcon(qtlib.geticon('hg-rename'))
        self.setObjectName('rename')
        cmdwidget = RenameWidget(repoagent, self, source, destination, iscopy)
        cmdwidget.commandChanged.connect(self._updateUi)
        self.setCommandWidget(cmdwidget)
        self.commandFinished.connect(self._checkKnownError)
        self._updateUi()

    @pyqtSlot(int)
    def _checkKnownError(self, ret):
        if ret == 1:
            # occurs if _some_ of the files cannot be copied
            cmdui.errorMessageBox(self.lastFinishedSession(), self)

    @pyqtSlot()
    def _updateUi(self):
        if self.commandWidget().isCopyCommand():
            bt = _('Copy')
            wt = _('Copy - %s')
        else:
            bt = _('Rename')
            wt = _('Rename - %s')
        self.setRunButtonText(bt)
        self.setWindowTitle(wt % self._repoagent.displayName())
