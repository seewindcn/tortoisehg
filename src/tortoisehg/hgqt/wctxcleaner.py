# wctxcleaner.py - check and clean dirty working directory
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import QObject, QThread
from PyQt4.QtCore import pyqtSignal, pyqtSlot
from PyQt4.QtGui import QMessageBox, QWidget

from mercurial import cmdutil, hg, util

from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, qtlib, thgrepo

def _checkchanged(repo):
    try:
        cmdutil.bailifchanged(repo)
        return False
    except util.Abort:
        return True


class CheckThread(QThread):
    def __init__(self, repo, parent):
        QThread.__init__(self, parent)
        self.repo = hg.repository(repo.ui, repo.root)
        self.results = (False, 1)
        self.canceled = False

    def run(self):
        self.repo.invalidate()
        self.repo.dirstate.invalidate()
        unresolved = False
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if self.canceled:
                return
            if status == 'u':
                unresolved = True
                break
        wctx = self.repo[None]
        try:
            dirty = _checkchanged(self.repo) or unresolved
            self.results = (dirty, len(wctx.parents()))
        except EnvironmentError:
            self.results = (True, len(wctx.parents()))

    def cancel(self):
        self.canceled = True


class WctxCleaner(QObject):

    checkStarted = pyqtSignal()
    checkFinished = pyqtSignal(bool, int)  # clean, parents

    def __init__(self, repoagent, parent=None):
        super(WctxCleaner, self).__init__(parent)
        assert parent is None or isinstance(parent, QWidget)
        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self._checkth = CheckThread(repoagent.rawRepo(), self)
        self._checkth.started.connect(self.checkStarted)
        self._checkth.finished.connect(self._onCheckFinished)
        self._clean = False

    @pyqtSlot()
    def check(self):
        """Check states of working directory asynchronously"""
        if self._checkth.isRunning():
            return
        self._checkth.start()

    def cancelCheck(self):
        self._checkth.cancel()
        self._checkth.wait()

    def isChecking(self):
        return self._checkth.isRunning()

    def isCheckCanceled(self):
        return self._checkth.canceled

    def isClean(self):
        return self._clean

    @pyqtSlot()
    def _onCheckFinished(self):
        dirty, parents = self._checkth.results
        self._clean = not dirty
        self.checkFinished.emit(not dirty, parents)

    @pyqtSlot(str)
    def runCleaner(self, cmd):
        """Clean working directory by the specified action"""
        cmd = str(cmd)
        if cmd == 'commit':
            self.launchCommitDialog()
        elif cmd == 'shelve':
            self.launchShelveDialog()
        elif cmd.startswith('discard'):
            confirm = cmd != 'discard:noconfirm'
            self.discardChanges(confirm)
        else:
            raise ValueError('unknown command: %s' % cmd)

    def launchCommitDialog(self):
        from tortoisehg.hgqt import commit
        dlg = commit.CommitDialog(self._repoagent, [], {}, self.parent())
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        self.check()

    def launchShelveDialog(self):
        from tortoisehg.hgqt import shelve
        dlg = shelve.ShelveDialog(self._repoagent, self.parent())
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        self.check()

    def discardChanges(self, confirm=True):
        if confirm:
            labels = [(QMessageBox.Yes, _('&Discard')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Discard'),
                     _('Discard outstanding changes to working directory?'),
                     labels=labels, parent=self.parent()):
                return

        cmdline = ['update', '--clean', '--rev', '.']
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onCommandFinished)

    @pyqtSlot(int)
    def _onCommandFinished(self, ret):
        if ret == 0:
            self.check()
        else:
            cmdui.errorMessageBox(self._cmdsession, self.parent())
