# qrename.py - QRename dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib

def checkPatchname(patchfile, parent):
    if os.path.exists(patchfile):
        dlg = CheckPatchnameDialog(os.path.basename(patchfile), parent)
        choice = dlg.exec_()
        if choice == 1:
            # add .OLD to existing patchfile
            try:
                os.rename(patchfile, patchfile + '.OLD')
            except (OSError, IOError), inst:
                qtlib.ErrorMsgBox(_('Rename Error'),
                        _('Could not rename existing patchfile'),
                        hglib.tounicode(str(inst)))
                return False
            return True
        elif choice == 2:
            # overwite existing patchfile
            try:
                os.remove(patchfile)
            except (OSError, IOError), inst:
                qtlib.ErrorMsgBox(_('Rename Error'),
                        _('Could not delete existing patchfile'),
                        hglib.tounicode(str(inst)))
                return False
            return True
        elif choice == 3:
            # go back and change the new name
            return False
        else:
            return False
    else:
        return True

class CheckPatchnameDialog(QDialog):

    def __init__(self, patchname, parent):
        super(CheckPatchnameDialog, self).__init__(parent)
        self.setWindowTitle(_('QRename - Check patchname'))

        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.patchname = patchname

        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(4)

        lbl = QLabel(_('Patch name <b>%s</b> already exists:')
                        % (self.patchname))
        self.vbox.addWidget(lbl)

        self.extensionradio = \
                QRadioButton(_('Add .OLD extension to existing patchfile'))
        self.vbox.addWidget(self.extensionradio)
        self.overwriteradio = QRadioButton(_('Overwrite existing patchfile'))
        self.vbox.addWidget(self.overwriteradio)
        self.backradio = QRadioButton(_('Go back and change new patchname'))
        self.vbox.addWidget(self.backradio)

        self.extensionradio.toggled.connect(self.onExtensionRadioChecked)
        self.overwriteradio.toggled.connect(self.onOverwriteRadioChecked)
        self.backradio.toggled.connect(self.onBackRadioChecked)

        self.choice = 0
        self.extensionradio.setChecked(True)
        self.extensionradio.setFocus()

        self.setLayout(self.vbox)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Ok|BB.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

    @pyqtSlot()
    def onExtensionRadioChecked(self):
        if self.extensionradio.isChecked():
            self.choice = 1

    @pyqtSlot()
    def onOverwriteRadioChecked(self):
        if self.overwriteradio.isChecked():
            self.choice = 2

    @pyqtSlot()
    def onBackRadioChecked(self):
        if self.backradio.isChecked():
            self.choice = 3

    def accept(self):
        self.done(self.choice)
        self.close()

    def reject(self):
        self.done(0)
