# bisect.py - Bisect dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import util, error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, qtlib

class BisectDialog(QDialog):

    newCandidate = pyqtSignal()

    def __init__(self, repoagent, parent=None):
        super(BisectDialog, self).__init__(parent)
        self.setWindowTitle(_('Bisect - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-bisect'))
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint)

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()

        # base layout box
        box = QVBoxLayout()
        box.setSpacing(6)
        self.setLayout(box)

        form = QFormLayout()
        box.addLayout(form)

        hbox = QHBoxLayout()
        self._gle = gle = QLineEdit()
        hbox.addWidget(gle, 1)
        self._gb = gb = QPushButton(_('Accept'))
        hbox.addWidget(gb)
        form.addRow(_('Known good revision:'), hbox)

        hbox = QHBoxLayout()
        self._ble = ble = QLineEdit()
        hbox.addWidget(ble, 1)
        self._bb = bb = QPushButton(_('Accept'))
        hbox.addWidget(bb)
        form.addRow(_('Known bad revision:'), hbox)

        self.discard_chk = QCheckBox(_('Discard local changes '
                                       '(revert --all)'))
        form.addRow(self.discard_chk)

        ## command widget
        self._cmdlog = log = cmdui.LogWidget(self)
        box.addWidget(log, 1)
        self._stbar = stbar = cmdui.ThgStatusBar(self)
        stbar.setSizeGripEnabled(False)
        box.addWidget(stbar)

        self._nextbuttons = buttons = QDialogButtonBox(self)
        buttons.setCenterButtons(True)
        buttons.clicked.connect(self._markRevision)
        box.addWidget(buttons)
        for state, text in [('good', _('Revision is &Good')),
                            ('bad',  _('Revision is &Bad')),
                            ('skip', _('&Skip this Revision'))]:
            btn = buttons.addButton(text, QDialogButtonBox.ActionRole)
            btn.setObjectName(state)

        hbox = QHBoxLayout()
        box.addLayout(hbox)
        hbox.addStretch()
        closeb = QPushButton(_('Close'))
        hbox.addWidget(closeb)
        closeb.clicked.connect(self.reject)

        self.goodrev = self.badrev = self.lastrev = None
        self.restart()

        gb.clicked.connect(self._verifyGood)
        bb.clicked.connect(self._verifyBad)
        gle.returnPressed.connect(self._verifyGood)
        ble.returnPressed.connect(self._verifyBad)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def restart(self, goodrev=None, badrev=None):
        if not self._cmdsession.isFinished():
            return
        self._gle.setEnabled(True)
        self._gle.setText(goodrev or '')
        self._gb.setEnabled(True)
        self._ble.setEnabled(False)
        self._ble.setText(badrev or '')
        self._bb.setEnabled(False)
        self._nextbuttons.setEnabled(False)
        self._cmdlog.clearLog()
        self._stbar.showMessage('')
        self.goodrev = self.badrev = self.lastrev = None

    def _setSession(self, sess):
        assert self._cmdsession.isFinished()
        self._cmdsession = sess
        sess.commandFinished.connect(self._cmdFinished)
        sess.outputReceived.connect(self._cmdlog.appendLog)
        sess.progressReceived.connect(self._stbar.setProgress)
        cmdui.updateStatusMessage(self._stbar, sess)

    @pyqtSlot(int)
    def _cmdFinished(self, ret):
        self._stbar.clearProgress()
        if ret != 0:
            self._stbar.showMessage(_('Error encountered.'), True)
            return
        self.repo.dirstate.invalidate()
        ctx = self.repo['.']
        if ctx.rev() == self.lastrev:
            self._stbar.showMessage(_('Culprit found.'))
            return
        self.lastrev = ctx.rev()
        self._nextbuttons.setEnabled(True)
        self._stbar.showMessage('%s: %d (%s) -> %s'
                                % (_('Revision'), ctx.rev(), ctx,
                                   _('Test this revision and report findings. '
                                     '(good/bad/skip)')))
        self.newCandidate.emit()

    def _lookupRevision(self, changeid):
        try:
            ctx = self.repo[hglib.fromunicode(changeid)]
            return ctx.rev()
        except (error.LookupError, error.RepoLookupError), e:
            self._stbar.showMessage(hglib.tounicode(str(e)))
        except util.Abort, e:
            if e.hint:
                err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                            hglib.tounicode(e.hint))
            else:
                err = hglib.tounicode(str(e))
            self._stbar.showMessage(err)

    @pyqtSlot()
    def _verifyGood(self):
        self.goodrev = self._lookupRevision(self._gle.text().simplified())
        if self.goodrev is None:
            return
        self._gb.setEnabled(False)
        self._gle.setEnabled(False)
        self._bb.setEnabled(True)
        self._ble.setEnabled(True)
        self._ble.setFocus()

    @pyqtSlot()
    def _verifyBad(self):
        self.badrev = self._lookupRevision(self._ble.text().simplified())
        if self.badrev is None:
            return
        self._ble.setEnabled(False)
        self._bb.setEnabled(False)
        cmds = []
        if self.discard_chk.isChecked():
            cmds.append(hglib.buildcmdargs('revert', all=True))
        cmds.append(hglib.buildcmdargs('bisect', reset=True))
        cmds.append(hglib.buildcmdargs('bisect', self.goodrev, good=True))
        cmds.append(hglib.buildcmdargs('bisect', self.badrev, bad=True))
        self._setSession(self._repoagent.runCommandSequence(cmds, self))

    @pyqtSlot(QAbstractButton)
    def _markRevision(self, button):
        self._nextbuttons.setEnabled(False)
        state = str(button.objectName())
        cmds = []
        if self.discard_chk.isChecked():
            cmds.append(hglib.buildcmdargs('revert', all=True))
        cmds.append(hglib.buildcmdargs('bisect', '.', **{state: True}))
        self._setSession(self._repoagent.runCommandSequence(cmds, self))
