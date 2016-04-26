# hginit.py - TortoiseHg dialog to initialize a repo
#
# Copyright 2008 Steve Borho <steve@borho.org>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from tortoisehg.hgqt import cmdcore, cmdui, qtlib
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class InitWidget(cmdui.AbstractCmdWidget):

    def __init__(self, ui, cmdagent, destdir='.', parent=None):
        super(InitWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cmdagent = cmdagent

        form = QFormLayout()
        self.setLayout(form)

        # dest widgets
        self._dest_edit = QLineEdit()
        self._dest_edit.setMinimumWidth(300)
        self._dest_btn = QPushButton(_('Browse...'))
        self._dest_btn.setAutoDefault(False)
        destbox = QHBoxLayout()
        destbox.addWidget(self._dest_edit, 1)
        destbox.addWidget(self._dest_btn)
        form.addRow(_('Destination path:'), destbox)

        # options checkboxes
        if ui.config('tortoisehg', 'initskel'):
            l = _('Copy working directory files from skeleton')
        else:
            l = _('Add special files (.hgignore, ...)')
        self._add_files_chk = QCheckBox(l)
        self._make_pre_1_7_chk = QCheckBox(
                _('Make repo compatible with Mercurial <1.7'))
        optbox = QVBoxLayout()
        optbox.addWidget(self._add_files_chk)
        optbox.addWidget(self._make_pre_1_7_chk)
        form.addRow('', optbox)

        # some extras
        self._hgcmd_txt = QLineEdit()
        self._hgcmd_txt.setReadOnly(True)
        form.addRow(_('Hg command:'), self._hgcmd_txt)

        # init defaults
        path = os.path.abspath(destdir)
        if os.path.isfile(path):
            path = os.path.dirname(path)
        self._dest_edit.setText(path)
        self._add_files_chk.setChecked(True)
        self._make_pre_1_7_chk.setChecked(False)
        self._composeCommand()

        # connecting slots
        self._dest_edit.textChanged.connect(self._composeCommand)
        self._dest_btn.clicked.connect(self._browseDestination)
        self._add_files_chk.toggled.connect(self._composeCommand)
        self._make_pre_1_7_chk.toggled.connect(self._composeCommand)

    @pyqtSlot()
    def _browseDestination(self):
        """Select the destination directory"""
        caption = _('Select Destination Folder')
        path = QFileDialog.getExistingDirectory(self, caption)
        if path:
            self._dest_edit.setText(path)

    def destination(self):
        return unicode(self._dest_edit.text()).strip()

    def _buildCommand(self):
        cfgs = []
        if self._add_files_chk.isChecked():
            cfgs.append('hooks.post-init.thgskel='
                        'python:tortoisehg.util.hgcommands.postinitskel')
        if self._make_pre_1_7_chk.isChecked():
            cfgs.append('format.dotencode=False')
        return hglib.buildcmdargs('init', self.destination(), config=cfgs)

    @pyqtSlot()
    def _composeCommand(self):
        cmdline = self._buildCommand()
        self._hgcmd_txt.setText('hg ' + hglib.prettifycmdline(cmdline))
        self.commandChanged.emit()

    def canRunCommand(self):
        return bool(self.destination())

    def runCommand(self):
        cmdline = self._buildCommand()
        return self._cmdagent.runCommand(cmdline, self)


class InitDialog(cmdui.CmdControlDialog):

    newRepository = pyqtSignal(str)

    def __init__(self, ui, destdir='.', parent=None):
        super(InitDialog, self).__init__(parent)
        self.setWindowTitle(_('New Repository'))
        self.setWindowIcon(qtlib.geticon('hg-init'))
        self.setObjectName('init')
        self.setRunButtonText(_('&Create'))
        self._cmdagent = cmdagent = cmdcore.CmdAgent(ui, self)
        cmdagent.serviceStopped.connect(self.reject)
        self.setCommandWidget(InitWidget(ui, cmdagent, destdir, self))
        self.commandFinished.connect(self._handleNewRepo)

    def destination(self):
        return self.commandWidget().destination()

    @pyqtSlot(int)
    def _handleNewRepo(self, ret):
        if ret != 0:
            return
        self.newRepository.emit(self.destination())

    def done(self, r):
        if self._cmdagent.isServiceRunning():
            self._cmdagent.stopService()
            return  # postponed until serviceStopped
        super(InitDialog, self).done(r)
