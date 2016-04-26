# rebase.py - Rebase dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import os

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, csinfo, resolve, thgrepo, wctxcleaner
from tortoisehg.hgqt import cmdcore, cmdui

BB = QDialogButtonBox

class RebaseDialog(QDialog):

    def __init__(self, repoagent, parent, **opts):
        super(RebaseDialog, self).__init__(parent)
        self.setWindowIcon(qtlib.geticon('hg-rebase'))
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint)
        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        repo = repoagent.rawRepo()
        self.opts = opts

        box = QVBoxLayout()
        box.setSpacing(8)
        box.setContentsMargins(*(6,)*4)
        self.setLayout(box)

        style = csinfo.panelstyle(selectable=True)

        srcb = QGroupBox(_('Rebase changeset and descendants'))
        srcb.setLayout(QVBoxLayout())
        srcb.layout().setContentsMargins(*(2,)*4)
        s = opts.get('source', '.')
        source = csinfo.create(self.repo, s, style, withupdate=True)
        srcb.layout().addWidget(source)
        self.sourcecsinfo = source
        self.layout().addWidget(srcb)

        destb = QGroupBox(_('To rebase destination'))
        destb.setLayout(QVBoxLayout())
        destb.layout().setContentsMargins(*(2,)*4)
        d = opts.get('dest', '.')
        dest = csinfo.create(self.repo, d, style, withupdate=True)
        destb.layout().addWidget(dest)
        self.destcsinfo = dest
        self.layout().addWidget(destb)

        self.swaplabel = QLabel('<a href="X">%s</a>'  # don't care href
                                % _('Swap source and destination'))
        self.swaplabel.linkActivated.connect(self.swap)
        self.layout().addWidget(self.swaplabel)

        sep = qtlib.LabeledSeparator(_('Options'))
        self.layout().addWidget(sep)

        self.keepchk = QCheckBox(_('Keep original changesets (--keep)'))
        self.keepchk.setChecked(opts.get('keep', False))
        self.layout().addWidget(self.keepchk)

        self.keepbrancheschk = QCheckBox(_('Keep original branch names '
                                           '(--keepbranches)'))
        self.keepbrancheschk.setChecked(opts.get('keepbranches', False))
        self.layout().addWidget(self.keepbrancheschk)

        self.collapsechk = QCheckBox(_('Collapse the rebased changesets '
                                       '(--collapse)'))
        self.collapsechk.setChecked(opts.get('collapse', False))
        self.layout().addWidget(self.collapsechk)

        self.basechk = QCheckBox(_('Rebase entire source branch (-b/--base)'))
        self.layout().addWidget(self.basechk)

        self.autoresolvechk = QCheckBox(_('Automatically resolve merge '
                                          'conflicts where possible'))
        self.layout().addWidget(self.autoresolvechk)

        self.svnchk = QCheckBox(_('Rebase unpublished onto Subversion head '
                                  '(override source, destination)'))
        self.svnchk.setVisible('hgsubversion' in repo.extensions())
        self.layout().addWidget(self.svnchk)

        self._cmdlog = cmdui.LogWidget(self)
        self._cmdlog.hide()
        self.layout().addWidget(self._cmdlog, 2)
        self._stbar = cmdui.ThgStatusBar(self)
        self._stbar.setSizeGripEnabled(False)
        self._stbar.linkActivated.connect(self.linkActivated)
        self.layout().addWidget(self._stbar)

        bbox = QDialogButtonBox()
        self.cancelbtn = bbox.addButton(QDialogButtonBox.Cancel)
        self.cancelbtn.clicked.connect(self.reject)
        self.rebasebtn = bbox.addButton(_('Rebase'),
                                        QDialogButtonBox.ActionRole)
        self.rebasebtn.clicked.connect(self.rebase)
        self.abortbtn = bbox.addButton(_('Abort'),
                                       QDialogButtonBox.ActionRole)
        self.abortbtn.clicked.connect(self.abort)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        self._wctxcleaner = wctxcleaner.WctxCleaner(repoagent, self)
        self._wctxcleaner.checkFinished.connect(self._onCheckFinished)
        if self.checkResolve() or not (s or d):
            for w in (srcb, destb, sep, self.keepchk,
                      self.collapsechk, self.keepbrancheschk):
                w.setHidden(True)
            self._cmdlog.show()
        else:
            self._stbar.showMessage(_('Checking...'))
            self.abortbtn.setEnabled(False)
            self.rebasebtn.setEnabled(False)
            QTimer.singleShot(0, self._wctxcleaner.check)

        self.setMinimumWidth(480)
        self.setMaximumHeight(800)
        self.resize(0, 340)
        self.setWindowTitle(_('Rebase - %s') % repoagent.displayName())
        self._readSettings()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def _readSettings(self):
        qs = QSettings()
        qs.beginGroup('rebase')
        self.autoresolvechk.setChecked(
            self.repo.ui.configbool('tortoisehg', 'autoresolve',
                                    qs.value('autoresolve', True).toBool()))
        qs.endGroup()

    def _writeSettings(self):
        qs = QSettings()
        qs.beginGroup('rebase')
        qs.setValue('autoresolve', self.autoresolvechk.isChecked())
        qs.endGroup()

    @pyqtSlot(bool)
    def _onCheckFinished(self, clean):
        if not clean:
            self.rebasebtn.setEnabled(False)
            txt = _('Before rebase, you must '
                    '<a href="commit"><b>commit</b></a>, '
                    '<a href="shelve"><b>shelve</b></a> to patch, '
                    'or <a href="discard"><b>discard</b></a> changes.')
        else:
            self.rebasebtn.setEnabled(True)
            txt = _('You may continue the rebase')
        self._stbar.showMessage(txt)

    def rebase(self):
        self.rebasebtn.setEnabled(False)
        self.cancelbtn.setVisible(False)
        self.keepchk.setEnabled(False)
        self.keepbrancheschk.setEnabled(False)
        self.basechk.setEnabled(False)
        self.collapsechk.setEnabled(False)
        self.swaplabel.setVisible(False)

        itool = self.autoresolvechk.isChecked() and 'merge' or 'fail'
        opts = {'config': 'ui.merge=internal:%s' % itool}
        if os.path.exists(self.repo.join('rebasestate')):
            opts['continue'] = True
        else:
            opts.update({
                'keep': self.keepchk.isChecked(),
                'keepbranches': self.keepbrancheschk.isChecked(),
                'collapse': self.collapsechk.isChecked(),
                })
            if self.svnchk.isChecked():
                opts['svn'] = True
            else:
                sourcearg = 'source'
                if self.basechk.isChecked():
                    sourcearg = 'base'
                opts[sourcearg] = hglib.tounicode(str(self.opts.get('source')))
                opts['dest'] = hglib.tounicode(str(self.opts.get('dest')))
        cmdline = hglib.buildcmdargs('rebase', **opts)
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._rebaseFinished)

    def swap(self):
        oldsource = self.opts.get('source', '.')
        olddest = self.opts.get('dest', '.')

        self.sourcecsinfo.update(target=olddest)
        self.destcsinfo.update(target=oldsource)

        self.opts['source'] = olddest
        self.opts['dest'] = oldsource

    def abort(self):
        cmdline = hglib.buildcmdargs('rebase', abort=True)
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._abortFinished)

    def _runCommand(self, cmdline):
        assert self._cmdsession.isFinished()
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._stbar.clearProgress)
        sess.outputReceived.connect(self._cmdlog.appendLog)
        sess.progressReceived.connect(self._stbar.setProgress)
        cmdui.updateStatusMessage(self._stbar, sess)
        return sess

    @pyqtSlot(int)
    def _rebaseFinished(self, ret):
        # TODO since hg 2.6, rebase will end with ret=1 in case of "unresolved
        # conflicts", so we can fine-tune checkResolve() later.
        if self.checkResolve() is False:
            msg = _('Rebase is complete')
            if ret == 255:
                msg = _('Rebase failed')
                self._cmdlog.show()  # contains hint
            self._stbar.showMessage(msg)
            self._makeCloseButton()

    @pyqtSlot()
    def _abortFinished(self):
        if self.checkResolve() is False:
            self._stbar.showMessage(_('Rebase aborted'))
            self._makeCloseButton()

    def _makeCloseButton(self):
        self.rebasebtn.setEnabled(True)
        self.rebasebtn.setText(_('Close'))
        self.rebasebtn.clicked.disconnect(self.rebase)
        self.rebasebtn.clicked.connect(self.accept)

    def checkResolve(self):
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                txt = _('Rebase generated merge <b>conflicts</b> that must '
                        'be <a href="resolve"><b>resolved</b></a>')
                self.rebasebtn.setEnabled(False)
                break
        else:
            self.rebasebtn.setEnabled(True)
            txt = _('You may continue the rebase')
        self._stbar.showMessage(txt)

        if os.path.exists(self.repo.join('rebasestate')):
            self.swaplabel.setVisible(False)
            self.abortbtn.setEnabled(True)
            self.rebasebtn.setText('Continue')
            return True
        else:
            self.abortbtn.setEnabled(False)
            return False

    def linkActivated(self, cmd):
        if cmd == 'resolve':
            dlg = resolve.ResolveDialog(self._repoagent, self)
            dlg.exec_()
            self.checkResolve()
        else:
            self._wctxcleaner.runCleaner(cmd)

    def reject(self):
        if os.path.exists(self.repo.join('rebasestate')):
            main = _('Exiting with an unfinished rebase is not recommended.')
            text = _('Consider aborting the rebase first.')
            labels = ((QMessageBox.Yes, _('&Exit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                        labels=labels, parent=self):
                return
        super(RebaseDialog, self).reject()

    def done(self, r):
        self._writeSettings()
        super(RebaseDialog, self).done(r)
