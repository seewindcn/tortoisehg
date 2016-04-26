# revert.py - File revert dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial.node import nullid

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, qtlib

class RevertDialog(QDialog):
    def __init__(self, repoagent, wfiles, rev, parent):
        super(RevertDialog, self).__init__(parent)

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self.setWindowTitle(_('Revert - %s') % repoagent.displayName())

        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        repo = repoagent.rawRepo()
        self.wfiles = [repo.wjoin(wfile) for wfile in wfiles]

        self.setLayout(QVBoxLayout())

        if len(wfile) == 1:
            lblText = _('<b>Revert %s to its contents'
                        ' at the following revision?</b>') % (
                      hglib.tounicode(wfiles[0]))
        else:
            lblText = _('<b>Revert %d files to their contents'
                        ' at the following revision?</b>') % (
                      len(wfiles))
        lbl = QLabel(lblText)
        self.layout().addWidget(lbl)

        self._addRevertTargetCombo(rev)

        self.allchk = QCheckBox(_('Revert all files to this revision'))
        self.layout().addWidget(self.allchk)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Ok|BB.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

    def _addRevertTargetCombo(self, rev):
        if rev is None:
            raise ValueError('Cannot revert to working directory')
        self.revcombo = QComboBox()
        revnames = ['revision %d' % rev]
        repo = self._repoagent.rawRepo()
        ctx = repo[rev]
        parents = ctx.parents()[:2]
        if len(parents) == 1:
            parentdesctemplate = ("revision %d's parent (i.e. revision %d)",)
        else:
            parentdesctemplate = (
                _("revision %d's first parent (i.e. revision %d)"),
                _("revision %d's second parent (i.e. revision %d)"),
            )
        for n, pctx in enumerate(parents):
            if pctx.node() == nullid:
                revdesc = _('null revision (i.e. remove file(s))')
            else:
                revdesc = parentdesctemplate[n] % (rev, pctx.rev())
            revnames.append(revdesc)
        self.revcombo.addItems(revnames)
        reverttargets = [ctx] + parents
        for n, ctx in enumerate(reverttargets):
            self.revcombo.setItemData(n, ctx.hex())
        self.layout().addWidget(self.revcombo)

    def accept(self):
        rev = self.revcombo.itemData(self.revcombo.currentIndex()).toString()
        if self.allchk.isChecked():
            if not qtlib.QuestionMsgBox(_('Confirm Revert'),
                     _('Reverting all files will discard changes and '
                       'leave affected files in a modified state.<br>'
                       '<br>Are you sure you want to use revert?<br><br>'
                       '(use update to checkout another revision)'),
                       parent=self):
                return
            cmdline = hglib.buildcmdargs('revert', all=True, rev=rev)
        else:
            files = map(hglib.tounicode, self.wfiles)
            cmdline = hglib.buildcmdargs('revert', rev=rev, *files)
        self.bbox.button(QDialogButtonBox.Ok).setEnabled(False)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onCommandFinished)

    @pyqtSlot(int)
    def _onCommandFinished(self, ret):
        if ret == 0:
            self.reject()
        else:
            cmdui.errorMessageBox(self._cmdsession, self)
