# graft.py - Graft dialog for TortoiseHg
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
from tortoisehg.hgqt import qtlib, cmdcore, cmdui, resolve, thgrepo, wctxcleaner
from tortoisehg.hgqt import csinfo, cslist

BB = QDialogButtonBox

class GraftDialog(QDialog):

    def __init__(self, repoagent, parent, **opts):
        super(GraftDialog, self).__init__(parent)
        self.setWindowIcon(qtlib.geticon('hg-transplant'))
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint)

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self._graftstatefile = self.repo.join('graftstate')
        self.valid = True

        def cleanrevlist(revlist):
            return [self.repo[rev].rev() for rev in revlist]
        self.sourcelist = cleanrevlist(opts.get('source', ['.']))
        currgraftrevs = self.graftstate()
        if currgraftrevs:
            currgraftrevs = cleanrevlist(currgraftrevs)
            if self.sourcelist != currgraftrevs:
                res = qtlib.CustomPrompt(_('Interrupted graft operation found'),
                    _('An interrupted graft operation has been found.\n\n'
                      'You cannot perform a different graft operation unless '
                      'you abort the interrupted graft operation first.'),
                    self,
                    (_('Continue or abort interrupted graft operation?'),
                     _('Cancel')), 1, 2).run()
                if res != 0:
                    # Cancel
                    self.valid = False
                    return
                # Continue creating the dialog, but use the graft source
                # of the existing, interrupted graft as the source, rather than
                # the one that was passed as an option to the dialog constructor
                self.sourcelist = currgraftrevs

        box = QVBoxLayout()
        box.setSpacing(8)
        box.setContentsMargins(*(6,)*4)
        self.setLayout(box)

        self.srcb = srcb = QGroupBox()
        srcb.setLayout(QVBoxLayout())
        srcb.layout().setContentsMargins(*(2,)*4)

        self.cslist = cslist.ChangesetList(self.repo)
        self._updateSource(0)
        srcb.layout().addWidget(self.cslist)
        self.layout().addWidget(srcb)

        destrev = self.repo['.'].rev()
        style = csinfo.panelstyle(selectable=True)
        destb = QGroupBox(_('To graft destination'))
        destb.setLayout(QVBoxLayout())
        destb.layout().setContentsMargins(*(2,)*4)
        dest = csinfo.create(self.repo, destrev, style, withupdate=True)
        destb.layout().addWidget(dest)
        self.destcsinfo = dest
        self.layout().addWidget(destb)

        sep = qtlib.LabeledSeparator(_('Options'))
        self.layout().addWidget(sep)

        self._optchks = {}
        for name, text in [
                ('currentuser', _('Use my user name instead of graft '
                                  'committer user name')),
                ('currentdate', _('Use current date')),
                ('log', _('Append graft info to log message')),
                ('autoresolve', _('Automatically resolve merge conflicts '
                                  'where possible'))]:
            self._optchks[name] = w = QCheckBox(text)
            self.layout().addWidget(w)

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
        self.graftbtn = bbox.addButton(_('Graft'), QDialogButtonBox.ActionRole)
        self.graftbtn.clicked.connect(self.graft)
        self.abortbtn = bbox.addButton(_('Abort'), QDialogButtonBox.ActionRole)
        self.abortbtn.clicked.connect(self.abort)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        self._wctxcleaner = wctxcleaner.WctxCleaner(repoagent, self)
        self._wctxcleaner.checkFinished.connect(self._onCheckFinished)
        if self.checkResolve():
            self.abortbtn.setEnabled(True)
        else:
            self._stbar.showMessage(_('Checking...'))
            self.abortbtn.setEnabled(False)
            self.graftbtn.setEnabled(False)
            QTimer.singleShot(0, self._wctxcleaner.check)

        self.setMinimumWidth(480)
        self.setMaximumHeight(800)
        self.resize(0, 340)
        self.setWindowTitle(_('Graft - %s') % repoagent.displayName())
        self._readSettings()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def _readSettings(self):
        ui = self.repo.ui
        qs = QSettings()
        qs.beginGroup('graft')
        for n, w in self._optchks.iteritems():
            if n == 'autoresolve':
                w.setChecked(ui.configbool('tortoisehg', n,
                                           qs.value(n, True).toBool()))
            else:
                w.setChecked(qs.value(n).toBool())
        qs.endGroup()

    def _writeSettings(self):
        qs = QSettings()
        qs.beginGroup('graft')
        for n, w in self._optchks.iteritems():
            qs.setValue(n, w.isChecked())
        qs.endGroup()

    def _updateSourceTitle(self, idx):
        numrevs = len(self.sourcelist)
        if numrevs <= 1:
            title = _('Graft changeset')
        else:
            title = _('Graft changeset #%d of %d') % (idx + 1, numrevs)
        self.srcb.setTitle(title)

    def _updateSource(self, idx):
        self._updateSourceTitle(idx)
        self.cslist.update(self.sourcelist[idx:])

    @pyqtSlot(bool)
    def _onCheckFinished(self, clean):
        if not clean:
            self.graftbtn.setEnabled(False)
            txt = _('Before graft, you must '
                    '<a href="commit"><b>commit</b></a>, '
                    '<a href="shelve"><b>shelve</b></a> to patch, '
                    'or <a href="discard"><b>discard</b></a> changes.')
        else:
            self.graftbtn.setEnabled(True)
            txt = _('You may continue or start the graft')
        self._stbar.showMessage(txt)

    def graft(self):
        self.graftbtn.setEnabled(False)
        self.cancelbtn.setVisible(False)
        opts = dict((n, w.isChecked()) for n, w in self._optchks.iteritems())
        itool = opts.pop('autoresolve') and 'merge' or 'fail'
        opts['config'] = 'ui.merge=internal:%s' % itool
        if os.path.exists(self._graftstatefile):
            opts['continue'] = True
            args = []
        else:
            args = [hglib.tounicode(str(s)) for s in self.sourcelist]
        cmdline = hglib.buildcmdargs('graft', *args, **opts)
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._graftFinished)

    def abort(self):
        self.abortbtn.setDisabled(True)
        if os.path.exists(self._graftstatefile):
            # Remove the existing graftstate file!
            os.remove(self._graftstatefile)
        cmdline = hglib.buildcmdargs('update', clean=True, rev='p1()')
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._abortFinished)

    def graftstate(self):
        graftstatefile = self.repo.join('graftstate')
        if os.path.exists(graftstatefile):
            f = open(graftstatefile, 'r')
            info = f.readlines()
            f.close()
            if len(info):
                revlist = [rev.strip() for rev in info]
                revlist = [rev for rev in revlist if rev != '']
                if revlist:
                    return revlist
        return None

    def _runCommand(self, cmdline):
        assert self._cmdsession.isFinished()
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._stbar.clearProgress)
        sess.outputReceived.connect(self._cmdlog.appendLog)
        sess.progressReceived.connect(self._stbar.setProgress)
        cmdui.updateStatusMessage(self._stbar, sess)
        return sess

    @pyqtSlot(int)
    def _graftFinished(self, ret):
        if self.checkResolve() is False:
            msg = _('Graft is complete')
            if ret == 255:
                msg = _('Graft failed')
                self._cmdlog.show()  # contains hint
            else:
                self._updateSource(len(self.sourcelist) - 1)
            self._stbar.showMessage(msg)
            self._makeCloseButton()

    @pyqtSlot()
    def _abortFinished(self):
        if self.checkResolve() is False:
            self._stbar.showMessage(_('Graft aborted'))
            self._makeCloseButton()

    def _makeCloseButton(self):
        self.graftbtn.setEnabled(True)
        self.graftbtn.setText(_('Close'))
        self.graftbtn.clicked.disconnect(self.graft)
        self.graftbtn.clicked.connect(self.accept)

    def checkResolve(self):
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                txt = _('Graft generated merge <b>conflicts</b> that must '
                        'be <a href="resolve"><b>resolved</b></a>')
                self.graftbtn.setEnabled(False)
                break
        else:
            self.graftbtn.setEnabled(True)
            txt = _('You may continue the graft')
        self._stbar.showMessage(txt)

        currgraftrevs = self.graftstate()
        if currgraftrevs:
            def findrev(rev, revlist):
                rev = self.repo[rev].rev()
                for n, r in enumerate(revlist):
                    r = self.repo[r].rev()
                    if rev == r:
                        return n
                return None
            idx = findrev(currgraftrevs[0], self.sourcelist)
            if idx is not None:
                self._updateSource(idx)
            self.abortbtn.setEnabled(True)
            self.graftbtn.setText('Continue')
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
        if self._wctxcleaner.isChecking():
            return
        if os.path.exists(self._graftstatefile):
            main = _('Exiting with an unfinished graft is not recommended.')
            text = _('Consider aborting the graft first.')
            labels = ((QMessageBox.Yes, _('&Exit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                        labels=labels, parent=self):
                return
        super(GraftDialog, self).reject()

    def done(self, r):
        self._writeSettings()
        super(GraftDialog, self).done(r)
