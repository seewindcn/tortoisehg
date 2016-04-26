# merge.py - Merge dialog for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, csinfo, cmdcore, cmdui, status, resolve
from tortoisehg.hgqt import qscilib, thgrepo, messageentry, commit, wctxcleaner

from PyQt4.QtCore import *
from PyQt4.QtGui import *

MARGINS = (8, 0, 0, 0)

class MergeDialog(QWizard):

    def __init__(self, repoagent, otherrev, parent=None):
        super(MergeDialog, self).__init__(parent)
        self._repoagent = repoagent
        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle(_('Merge - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-merge'))
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.IndependentPages, True)

        # set pages
        summarypage = SummaryPage(repoagent, str(otherrev), self)
        self.addPage(summarypage)
        self.addPage(MergePage(repoagent, str(otherrev), self))
        self.addPage(CommitPage(repoagent, self))
        self.addPage(ResultPage(repoagent, self))
        self.currentIdChanged.connect(self.pageChanged)

        # move focus to "Next" button so that "Cancel" doesn't eat Enter key
        summarypage.refreshFinished.connect(
            self.button(QWizard.NextButton).setFocus)

        self.resize(QSize(700, 489).expandedTo(self.minimumSizeHint()))

        repoagent.repositoryChanged.connect(self.repositoryChanged)
        repoagent.configChanged.connect(self.configChanged)

        self._readSettings()

    def _readSettings(self):
        qs = QSettings()
        qs.beginGroup('merge')
        for n in ['autoadvance', 'skiplast']:
            self.setField(n, qs.value(n, False))
        repo = self._repoagent.rawRepo()
        n = 'autoresolve'
        self.setField(n, repo.ui.configbool('tortoisehg', n,
                                            qs.value(n, True).toBool()))
        qs.endGroup()

    def _writeSettings(self):
        qs = QSettings()
        qs.beginGroup('merge')
        for n in ['autoadvance', 'autoresolve', 'skiplast']:
            qs.setValue(n, self.field(n))
        qs.endGroup()

    @pyqtSlot()
    def repositoryChanged(self):
        if self.currentPage():
            self.currentPage().repositoryChanged()

    @pyqtSlot()
    def configChanged(self):
        if self.currentPage():
            self.currentPage().configChanged()

    def pageChanged(self, id):
        if id != -1:
            self.currentPage().currentPage()

    def reject(self):
        if self.currentPage().canExit():
            super(MergeDialog, self).reject()

    def done(self, r):
        self._writeSettings()
        super(MergeDialog, self).done(r)


class BasePage(QWizardPage):
    def __init__(self, repoagent, parent):
        super(BasePage, self).__init__(parent)
        self._repoagent = repoagent

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def validatePage(self):
        'user pressed NEXT button, can we proceed?'
        return True

    def isComplete(self):
        'should NEXT button be sensitive?'
        return True

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        pass

    def configChanged(self):
        'repository has detected a change to config files'
        pass

    def currentPage(self):
        self.wizard().setOption(QWizard.NoDefaultButton, False)

    def canExit(self):
        if len(self.repo[None].parents()) == 2:
            main = _('Do you want to exit?')
            text = _('To finish merging, you must commit '
                     'the working directory.\n\n'
                     'To cancel the merge you can update to one '
                     'of the merge parent revisions.')
            labels = ((QMessageBox.Yes, _('&Exit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                        labels=labels, parent=self):
                return False
        return True

class SummaryPage(BasePage):
    refreshFinished = pyqtSignal()

    def __init__(self, repoagent, otherrev, parent):
        super(SummaryPage, self).__init__(repoagent, parent)
        self._wctxcleaner = wctxcleaner.WctxCleaner(repoagent, self)
        self._wctxcleaner.checkStarted.connect(self._onCheckStarted)
        self._wctxcleaner.checkFinished.connect(self._onCheckFinished)

        self.setTitle(_('Prepare to merge'))
        self.setSubTitle(_('Verify merge targets and ensure your working '
                           'directory is clean.'))
        self.setLayout(QVBoxLayout())

        repo = self.repo
        contents = ('ishead',) + csinfo.PANEL_DEFAULT
        style = csinfo.panelstyle(contents=contents)
        def markup_func(widget, item, value):
            if item == 'ishead' and value is False:
                text = _('Not a head revision!')
                return qtlib.markup(text, fg='red', weight='bold')
            raise csinfo.UnknownItem(item)
        custom = csinfo.custom(markup=markup_func)
        create = csinfo.factory(repo, custom, style, withupdate=True)

        ## merge target
        other_sep = qtlib.LabeledSeparator(_('Merge from (other revision)'))
        self.layout().addWidget(other_sep)
        otherCsInfo = create(otherrev)
        self.layout().addWidget(otherCsInfo)
        self.otherCsInfo = otherCsInfo

        ## current revision
        local_sep = qtlib.LabeledSeparator(_('Merge to (working directory)'))
        self.layout().addWidget(local_sep)
        localCsInfo = create(str(repo['.'].rev()))
        self.layout().addWidget(localCsInfo)
        self.localCsInfo = localCsInfo

        ## working directory status
        wd_sep = qtlib.LabeledSeparator(_('Working directory status'))
        self.layout().addWidget(wd_sep)

        self.groups = qtlib.WidgetGroups()

        wdbox = QHBoxLayout()
        self.layout().addLayout(wdbox)
        self.wd_status = qtlib.StatusLabel()
        self.wd_status.set_status(_('Checking...'))
        wdbox.addWidget(self.wd_status)
        wd_prog = QProgressBar()
        wd_prog.setMaximum(0)
        wd_prog.setTextVisible(False)
        self.groups.add(wd_prog, 'prog')
        wdbox.addWidget(wd_prog, 1)

        wd_merged = QLabel(_('The working directory is already <b>merged</b>. '
                             '<a href="skip"><b>Continue</b></a> or '
                             '<a href="discard"><b>discard</b></a> existing '
                             'merge.'))
        wd_merged.linkActivated.connect(self.onLinkActivated)
        wd_merged.setWordWrap(True)
        self.groups.add(wd_merged, 'merged')
        self.layout().addWidget(wd_merged)

        text = _('Before merging, you must <a href="commit"><b>commit</b></a>, '
                 '<a href="shelve"><b>shelve</b></a> to patch, '
                 'or <a href="discard"><b>discard</b></a> changes.')
        wd_text = QLabel(text)
        wd_text.setWordWrap(True)
        wd_text.linkActivated.connect(self._wctxcleaner.runCleaner)
        self.wd_text = wd_text
        self.groups.add(wd_text, 'dirty')
        self.layout().addWidget(wd_text)

        wdbox = QHBoxLayout()
        self.layout().addLayout(wdbox)
        wd_alt = QLabel(_('Or use:'))
        self.groups.add(wd_alt, 'dirty')
        wdbox.addWidget(wd_alt)
        force_chk = QCheckBox(_('Force a merge with outstanding changes '
                                '(-f/--force)'))
        force_chk.toggled.connect(lambda c: self.completeChanged.emit())
        self.registerField('force', force_chk)
        self.groups.add(force_chk, 'dirty')
        wdbox.addWidget(force_chk)

        ### discard option
        discard_chk = QCheckBox(_('Discard all changes from the other '
                                  'revision'))
        self.registerField('discard', discard_chk)
        self.layout().addWidget(discard_chk)

        ## auto-resolve
        autoresolve_chk = QCheckBox(_('Automatically resolve merge conflicts '
                                      'where possible'))
        self.registerField('autoresolve', autoresolve_chk)
        self.layout().addWidget(autoresolve_chk)

        self.groups.set_visible(False, 'dirty')
        self.groups.set_visible(False, 'merged')

    def isComplete(self):
        'should Next button be sensitive?'
        return self._wctxcleaner.isClean() or self.field('force').toBool()

    def validatePage(self):
        'validate that we can continue with the merge'
        if self.field('discard').toBool():
            labels = [(QMessageBox.Yes, _('&Discard')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Discard Changes'),
                _('The changes from revision %s and all unmerged parents '
                  'will be discarded.\n\n'
                  'Are you sure this is what you want to do?')
                      % (self.otherCsInfo.get_data('revid')),
                         labels=labels, parent=self):
                return False
        return super(SummaryPage, self).validatePage()

    ## custom methods ##

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        pctx = self.repo['.']
        self.localCsInfo.update(pctx)

    def canExit(self):
        'can merge tool be closed?'
        if self._wctxcleaner.isChecking():
            self._wctxcleaner.cancelCheck()
        return True

    def currentPage(self):
        super(SummaryPage, self).currentPage()
        self.refresh()

    def refresh(self):
        self._wctxcleaner.check()

    @pyqtSlot()
    def _onCheckStarted(self):
        self.groups.set_visible(True, 'prog')

    @pyqtSlot(bool, int)
    def _onCheckFinished(self, clean, parents):
        self.groups.set_visible(False, 'prog')
        if self._wctxcleaner.isCheckCanceled():
            return
        if not clean:
            self.groups.set_visible(parents == 2, 'merged')
            self.groups.set_visible(parents == 1, 'dirty')
            self.wd_status.set_status(_('<b>Uncommitted local changes '
                                        'are detected</b>'), 'thg-warning')
        else:
            self.groups.set_visible(False, 'dirty')
            self.groups.set_visible(False, 'merged')
            self.wd_status.set_status(_('Clean', 'working dir state'), True)
        self.completeChanged.emit()
        self.refreshFinished.emit()

    @pyqtSlot(str)
    def onLinkActivated(self, cmd):
        if cmd == 'skip':
            self.wizard().next()
        else:
            self._wctxcleaner.runCleaner(cmd)


class MergePage(BasePage):
    def __init__(self, repoagent, otherrev, parent):
        super(MergePage, self).__init__(repoagent, parent)
        self._otherrev = otherrev
        self.mergecomplete = False

        self.setTitle(_('Merging...'))
        self.setSubTitle(_('All conflicting files will be marked unresolved.'))
        self.setLayout(QVBoxLayout())

        self._cmdsession = cmdcore.nullCmdSession()
        self._cmdlog = cmdui.LogWidget(self)
        self.layout().addWidget(self._cmdlog)

        self.reslabel = QLabel()
        self.reslabel.linkActivated.connect(self.onLinkActivated)
        self.reslabel.setWordWrap(True)
        self.layout().addWidget(self.reslabel)

        autonext = QCheckBox(_('Automatically advance to next page '
                               'when merge is complete.'))
        autonext.clicked.connect(self.tryAutoAdvance)
        self.registerField('autoadvance', autonext)
        self.layout().addWidget(autonext)

    def currentPage(self):
        super(MergePage, self).currentPage()
        if len(self.repo[None].parents()) > 1:
            self.mergecomplete = True
            self.completeChanged.emit()
            return

        discard = self.field('discard').toBool()
        rev = hglib.tounicode(self._otherrev)
        cfgs = []
        if discard:
            tool = ':local'
            # disable changed/deleted prompt because we'll revert changes
            cfgs.append('ui.interactive=False')
        else:
            tool = self.field('autoresolve').toBool() and ':merge' or ':fail'
        cmdlines = [hglib.buildcmdargs('merge', rev, verbose=True, tool=tool,
                                       force=self.field('force').toBool(),
                                       config=cfgs)]
        if discard:
            # revert files added/removed at other side
            cmdlines.append(hglib.buildcmdargs('revert', rev='.', all=True))

        self._cmdlog.clearLog()
        self._cmdsession = sess = self._repoagent.runCommandSequence(cmdlines,
                                                                     self)
        sess.commandFinished.connect(self.onCommandFinished)
        sess.outputReceived.connect(self._cmdlog.appendLog)

    def isComplete(self):
        'should Next button be sensitive?'
        if not self.mergecomplete:
            return False
        ucount = 0
        rcount = 0
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                ucount += 1
            if status == 'r':
                rcount += 1
        if ucount:
            if self.field('autoresolve').toBool():
                # if autoresolve is enabled, we know these were real conflicts
                self.reslabel.setText(_('%d files have <b>merge conflicts</b> '
                                        'that must be <a href="resolve">'
                                        '<b>resolved</b></a>') % ucount)
            else:
                # else give a calmer indication of conflicts
                self.reslabel.setText(_('%d files were modified on both '
                                        'branches and must be <a href="resolve">'
                                        '<b>resolved</b></a>') % ucount)
            return False
        elif rcount:
            self.reslabel.setText(_('No merge conflicts, ready to commit or '
                                    '<a href="resolve"><b>review</b></a>'))
        else:
            self.reslabel.setText(_('No merge conflicts, ready to commit'))
        return True

    @pyqtSlot(bool)
    def tryAutoAdvance(self, checked):
        if checked and self.isComplete():
            self.wizard().next()

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        sess = self._cmdsession
        if ret in (0, 1):
            self.mergecomplete = True
            if self.field('autoadvance').toBool() and not sess.warningString():
                self.tryAutoAdvance(True)
            self.completeChanged.emit()

    @pyqtSlot(str)
    def onLinkActivated(self, cmd):
        if cmd == 'resolve':
            dlg = resolve.ResolveDialog(self._repoagent, self)
            dlg.exec_()
            if self.field('autoadvance').toBool():
                self.tryAutoAdvance(True)
            self.completeChanged.emit()


class CommitPage(BasePage):

    def __init__(self, repoagent, parent):
        super(CommitPage, self).__init__(repoagent, parent)

        self.setTitle(_('Commit merge results'))
        self.setSubTitle(' ')
        self.setLayout(QVBoxLayout())
        self.setCommitPage(True)

        repo = repoagent.rawRepo()

        # csinfo
        def label_func(widget, item, ctx):
            if item == 'rev':
                return _('Revision:')
            elif item == 'parents':
                return _('Parents')
            raise csinfo.UnknownItem()
        def data_func(widget, item, ctx):
            if item == 'rev':
                return _('Working Directory'), str(ctx)
            elif item == 'parents':
                parents = []
                cbranch = ctx.branch()
                for pctx in ctx.parents():
                    branch = None
                    if hasattr(pctx, 'branch') and pctx.branch() != cbranch:
                        branch = pctx.branch()
                    parents.append((str(pctx.rev()), str(pctx), branch, pctx))
                return parents
            raise csinfo.UnknownItem()
        def markup_func(widget, item, value):
            if item == 'rev':
                text, rev = value
                return '<a href="view">%s</a> (%s)' % (text, rev)
            elif item == 'parents':
                def branch_markup(branch):
                    opts = dict(fg='black', bg='#aaffaa')
                    return qtlib.markup(' %s ' % branch, **opts)
                csets = []
                for rnum, rid, branch, pctx in value:
                    line = '%s (%s)' % (rnum, rid)
                    if branch:
                        line = '%s %s' % (line, branch_markup(branch))
                    msg = widget.info.get_data('summary', widget,
                                               pctx, widget.custom)
                    if msg:
                        line = '%s %s' % (line, msg)
                    csets.append(line)
                return csets
            raise csinfo.UnknownItem()
        custom = csinfo.custom(label=label_func, data=data_func,
                               markup=markup_func)
        contents = ('rev', 'user', 'dateage', 'branch', 'parents')
        style = csinfo.panelstyle(contents=contents, margin=6)

        # merged files
        rev_sep = qtlib.LabeledSeparator(_('Working Directory (merged)'))
        self.layout().addWidget(rev_sep)
        mergeCsInfo = csinfo.create(repo, None, style, custom=custom,
                                    withupdate=True)
        mergeCsInfo.linkActivated.connect(self.onLinkActivated)
        self.layout().addWidget(mergeCsInfo)
        self.mergeCsInfo = mergeCsInfo

        # commit message area
        msg_sep = qtlib.LabeledSeparator(_('Commit message'))
        self.layout().addWidget(msg_sep)
        msgEntry = messageentry.MessageEntry(self)
        msgEntry.installEventFilter(qscilib.KeyPressInterceptor(self))
        msgEntry.refresh(repo)
        msgEntry.loadSettings(QSettings(), 'merge/message')

        msgEntry.textChanged.connect(self.completeChanged)
        self.layout().addWidget(msgEntry)
        self.msgEntry = msgEntry

        self._cmdsession = cmdcore.nullCmdSession()
        self._cmdlog = cmdui.LogWidget(self)
        self._cmdlog.hide()
        self.layout().addWidget(self._cmdlog)

        self.delayednext = False

        def tryperform():
            if self.isComplete():
                self.wizard().next()
        actionEnter = QAction('alt-enter', self)
        actionEnter.setShortcuts([Qt.CTRL+Qt.Key_Return, Qt.CTRL+Qt.Key_Enter])
        actionEnter.triggered.connect(tryperform)
        self.addAction(actionEnter)

        skiplast = QCheckBox(_('Skip final confirmation page, '
                               'close after commit.'))
        self.registerField('skiplast', skiplast)
        self.layout().addWidget(skiplast)

        hblayout = QHBoxLayout()
        self.opts = commit.readopts(self.repo.ui)
        self.optionsbtn = QPushButton(_('Commit Options'))
        self.optionsbtn.clicked.connect(self.details)
        hblayout.addWidget(self.optionsbtn)
        self.optionslabelfmt = _('<b>Selected Options:</b> %s')
        self.optionslabel = QLabel('')
        hblayout.addWidget(self.optionslabel)
        hblayout.addStretch()
        self.layout().addLayout(hblayout)

        self.setButtonText(QWizard.CommitButton, _('Commit Now'))
        # The cancel button does not really "cancel" the merge
        self.setButtonText(QWizard.CancelButton, _('Commit Later'))

        # Update the options label
        self.refresh()

    def refresh(self):
        opts = commit.commitopts2str(self.opts)
        self.optionslabel.setText(self.optionslabelfmt
            % hglib.tounicode(opts))
        self.optionslabel.setVisible(bool(opts))

    def cleanupPage(self):
        s = QSettings()
        self.msgEntry.saveSettings(s, 'merge/message')

    def currentPage(self):
        super(CommitPage, self).currentPage()
        self.wizard().setOption(QWizard.NoDefaultButton, True)
        self.mergeCsInfo.update()  # show post-merge state

        self.msgEntry.setText(commit.mergecommitmessage(self.repo))
        self.msgEntry.moveCursorToEnd()

    @pyqtSlot(str)
    def onLinkActivated(self, cmd):
        if cmd == 'view':
            dlg = status.StatusDialog(self._repoagent, [], {}, self)
            dlg.exec_()
            self.refresh()

    def isComplete(self):
        return (len(self.repo[None].parents()) == 2 and
                len(self.msgEntry.text()) > 0)

    def validatePage(self):
        if not self._cmdsession.isFinished():
            return False

        if len(self.repo[None].parents()) == 1:
            # commit succeeded, repositoryChanged() called wizard().next()
            if self.field('skiplast').toBool():
                self.wizard().close()
            return True

        user = hglib.tounicode(qtlib.getCurrentUsername(self, self.repo,
                                                        self.opts))
        if not user:
            return False

        self.setTitle(_('Committing...'))
        self.setSubTitle(_('Please wait while committing merged files.'))

        opts = {'verbose': True,
                'message': self.msgEntry.text(),
                'user': user,
                'subrepos': bool(self.opts.get('recurseinsubrepos')),
                'date': hglib.tounicode(self.opts.get('date')),
                }
        commandlines = [hglib.buildcmdargs('commit', **opts)]
        pushafter = self.repo.ui.config('tortoisehg', 'cipushafter')
        if pushafter:
            cmd = ['push', hglib.tounicode(pushafter)]
            commandlines.append(cmd)
        self._cmdlog.show()
        sess = self._repoagent.runCommandSequence(commandlines, self)
        self._cmdsession = sess
        sess.commandFinished.connect(self.onCommandFinished)
        sess.outputReceived.connect(self._cmdlog.appendLog)
        return False

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        if len(self.repo[None].parents()) == 1:
            if not self._cmdsession.isFinished():
                # call self.wizard().next() after the current command finishes
                self.delayednext = True
            else:
                self.wizard().next()

    @pyqtSlot()
    def onCommandFinished(self):
        if self.delayednext:
            self.delayednext = False
            self.wizard().next()
        self.completeChanged.emit()

    def readUserHistory(self):
        'Load user history from the global commit settings'
        s = QSettings()
        userhist = s.value('commit/userhist').toStringList()
        userhist = [u for u in userhist if u]
        return userhist

    def details(self):
        self.userhist = self.readUserHistory()
        dlg = commit.DetailsDialog(self._repoagent, self.opts, self.userhist,
                                   self, mode='merge')
        dlg.finished.connect(dlg.deleteLater)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self.opts.update(dlg.outopts)
            self.refresh()

class ResultPage(BasePage):
    def __init__(self, repoagent, parent):
        super(ResultPage, self).__init__(repoagent, parent)
        self.setTitle(_('Finished'))
        self.setSubTitle(' ')
        self.setFinalPage(True)

        self.setLayout(QVBoxLayout())
        merge_sep = qtlib.LabeledSeparator(_('Merge changeset'))
        self.layout().addWidget(merge_sep)
        mergeCsInfo = csinfo.create(self.repo, 'tip', withupdate=True)
        self.layout().addWidget(mergeCsInfo)
        self.mergeCsInfo = mergeCsInfo
        self.layout().addStretch(1)

    def currentPage(self):
        super(ResultPage, self).currentPage()
        self.mergeCsInfo.update(self.repo['tip'])
        self.wizard().setOption(QWizard.NoCancelButton, True)
