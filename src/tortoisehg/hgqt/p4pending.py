# p4pending.py - Display pending p4 changelists, created by perfarce extension
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cslist, cmdcore, cmdui


class PerforcePending(QDialog):
    'Dialog for selecting a revision'

    showMessage = pyqtSignal(str)

    def __init__(self, repoagent, pending, url, parent):
        QDialog.__init__(self, parent)
        self._repoagent = repoagent
        repo = repoagent.rawRepo()
        self._cmdsession = cmdcore.nullCmdSession()
        self.url = url
        self.pending = pending # dict of changelist -> hash tuple

        layout = QVBoxLayout()
        self.setLayout(layout)

        clcombo = QComboBox()
        layout.addWidget(clcombo)

        self.cslist = cslist.ChangesetList(repo)
        layout.addWidget(self.cslist)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel|BB.Discard)
        bb.rejected.connect(self.reject)
        bb.button(BB.Discard).setText('Revert')
        bb.button(BB.Discard).setAutoDefault(False)
        bb.button(BB.Discard).clicked.connect(self.revert)
        bb.button(BB.Discard).setEnabled(False)
        bb.button(BB.Ok).setText('Submit')
        bb.button(BB.Ok).setAutoDefault(True)
        bb.button(BB.Ok).clicked.connect(self.submit)
        bb.button(BB.Ok).setEnabled(False)
        layout.addWidget(bb)
        self.bb = bb

        clcombo.activated[str].connect(self.p4clActivated)
        for changelist in self.pending:
            clcombo.addItem(hglib.tounicode(changelist))
        self.p4clActivated(clcombo.currentText())

        self.setWindowTitle(_('Pending Perforce Changelists - %s') %
                            repoagent.displayName())
        self.setWindowFlags(self.windowFlags() &
                            ~Qt.WindowContextHelpButtonHint)

    @pyqtSlot(str)
    def p4clActivated(self, curcl):
        'User has selected a changelist, fill cslist'
        repo = self._repoagent.rawRepo()
        curcl = hglib.fromunicode(curcl)
        try:
            hashes = self.pending[curcl]
            revs = [repo[hash] for hash in hashes]
        except (error.Abort, error.RepoLookupError), e:
            revs = []
        self.cslist.clear()
        self.cslist.update(revs)
        sensitive = not curcl.endswith('(submitted)')
        self.bb.button(QDialogButtonBox.Ok).setEnabled(sensitive)
        self.bb.button(QDialogButtonBox.Discard).setEnabled(sensitive)
        self.curcl = curcl

    def submit(self):
        assert(self.curcl.endswith('(pending)'))
        cmdline = ['p4submit', '--verbose',
                   '--config', 'extensions.perfarce=',
                   '--repository', hglib.tounicode(self.url),
                   hglib.tounicode(self.curcl[:-10])]
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)
        self.bb.button(QDialogButtonBox.Discard).setEnabled(False)
        self.showMessage.emit(_('Submitting p4 changelist...'))
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self.commandFinished)

    def revert(self):
        assert(self.curcl.endswith('(pending)'))
        cmdline = ['p4revert', '--verbose',
                   '--config', 'extensions.perfarce=',
                   '--repository', hglib.tounicode(self.url),
                   hglib.tounicode(self.curcl[:-10])]
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)
        self.bb.button(QDialogButtonBox.Discard).setEnabled(False)
        self.showMessage.emit(_('Reverting p4 changelist...'))
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self.commandFinished)

    @pyqtSlot(int)
    def commandFinished(self, ret):
        self.showMessage.emit('')
        self.bb.button(QDialogButtonBox.Ok).setEnabled(True)
        self.bb.button(QDialogButtonBox.Discard).setEnabled(True)
        if ret == 0:
            self.reject()
        else:
            cmdui.errorMessageBox(self._cmdsession, self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if not self._cmdsession.isFinished():
                self._cmdsession.abort()
            else:
                self.reject()
        else:
            return super(PerforcePending, self).keyPressEvent(event)
