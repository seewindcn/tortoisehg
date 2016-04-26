# backout.py - Backout dialog for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from tortoisehg.util import hglib, i18n
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, csinfo, cmdcore, cmdui, status, resolve
from tortoisehg.hgqt import qscilib, thgrepo, messageentry, wctxcleaner

from PyQt4.QtCore import *
from PyQt4.QtGui import *

def checkrev(repo, rev):
    op1, op2 = repo.dirstate.parents()
    if op1 is None:
        return _('Backout requires a parent revision')

    bctx = repo[rev]
    a = repo.changelog.ancestor(op1, bctx.node())
    if a != bctx.node():
        return _('Cannot backout change on a different branch')


class BackoutDialog(QWizard):

    def __init__(self, repoagent, rev, parent=None):
        super(BackoutDialog, self).__init__(parent)
        self._repoagent = repoagent
        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)

        repo = repoagent.rawRepo()
        parentbackout = repo[rev] == repo['.']

        self.setWindowTitle(_('Backout - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-revert'))
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.IndependentPages, True)

        self.addPage(SummaryPage(repoagent, rev, parentbackout, self))
        self.addPage(BackoutPage(repoagent, rev, parentbackout, self))
        self.addPage(CommitPage(repoagent, rev, parentbackout, self))
        self.addPage(ResultPage(repoagent, self))
        self.currentIdChanged.connect(self.pageChanged)

        self.resize(QSize(700, 489).expandedTo(self.minimumSizeHint()))

        repoagent.repositoryChanged.connect(self.repositoryChanged)
        repoagent.configChanged.connect(self.configChanged)

        self._readSettings()

    def _readSettings(self):
        qs = QSettings()
        qs.beginGroup('backout')
        for n in ['autoadvance', 'skiplast']:
            self.setField(n, qs.value(n, False))
        repo = self._repoagent.rawRepo()
        n = 'autoresolve'
        self.setField(n, repo.ui.configbool('tortoisehg', n,
                                            qs.value(n, True).toBool()))
        qs.endGroup()

    def _writeSettings(self):
        qs = QSettings()
        qs.beginGroup('backout')
        for n in ['autoadvance', 'autoresolve', 'skiplast']:
            qs.setValue(n, self.field(n))
        qs.endGroup()

    @pyqtSlot()
    def repositoryChanged(self):
        self.currentPage().repositoryChanged()

    @pyqtSlot()
    def configChanged(self):
        self.currentPage().configChanged()

    def pageChanged(self, id):
        if id != -1:
            self.currentPage().currentPage()

    def reject(self):
        if self.currentPage().canExit():
            super(BackoutDialog, self).reject()

    def done(self, r):
        self._writeSettings()
        super(BackoutDialog, self).done(r)


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
        pass

    def canExit(self):
        return True


class SummaryPage(BasePage):

    def __init__(self, repoagent, backoutrev, parentbackout, parent):
        super(SummaryPage, self).__init__(repoagent, parent)
        self._wctxcleaner = wctxcleaner.WctxCleaner(repoagent, self)
        self._wctxcleaner.checkStarted.connect(self._onCheckStarted)
        self._wctxcleaner.checkFinished.connect(self._onCheckFinished)
        self.setTitle(_('Prepare to backout'))
        self.setSubTitle(_('Verify backout revision and ensure your working '
                           'directory is clean.'))
        self.setLayout(QVBoxLayout())

        self.groups = qtlib.WidgetGroups()

        repo = self.repo
        bctx = repo[backoutrev]
        pctx = repo['.']

        if parentbackout:
            lbl = _('Backing out a parent revision is a single step operation')
            self.layout().addWidget(QLabel(u'<b>%s</b>' % lbl))

        ## backout revision
        style = csinfo.panelstyle(contents=csinfo.PANEL_DEFAULT)
        create = csinfo.factory(repo, None, style, withupdate=True)
        sep = qtlib.LabeledSeparator(_('Backout revision'))
        self.layout().addWidget(sep)
        backoutCsInfo = create(bctx.rev())
        self.layout().addWidget(backoutCsInfo)

        ## current revision
        contents = ('ishead',) + csinfo.PANEL_DEFAULT
        style = csinfo.panelstyle(contents=contents)
        def markup_func(widget, item, value):
            if item == 'ishead' and value is False:
                text = _('Not a head, backout will create a new head!')
                return qtlib.markup(text, fg='red', weight='bold')
            raise csinfo.UnknownItem(item)
        custom = csinfo.custom(markup=markup_func)
        create = csinfo.factory(repo, custom, style, withupdate=True)

        sep = qtlib.LabeledSeparator(_('Current local revision'))
        self.layout().addWidget(sep)
        localCsInfo = create(pctx.rev())
        self.layout().addWidget(localCsInfo)
        self.localCsInfo = localCsInfo

        ## working directory status
        sep = qtlib.LabeledSeparator(_('Working directory status'))
        self.layout().addWidget(sep)

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

        text = _('Before backout, you must <a href="commit"><b>commit</b></a>, '
                 '<a href="shelve"><b>shelve</b></a> to patch, '
                 'or <a href="discard"><b>discard</b></a> changes.')
        wd_text = QLabel(text)
        wd_text.setWordWrap(True)
        wd_text.linkActivated.connect(self._wctxcleaner.runCleaner)
        self.wd_text = wd_text
        self.groups.add(wd_text, 'dirty')
        self.layout().addWidget(wd_text)

        ## auto-resolve
        autoresolve_chk = QCheckBox(_('Automatically resolve merge conflicts '
                                      'where possible'))
        self.registerField('autoresolve', autoresolve_chk)
        self.layout().addWidget(autoresolve_chk)
        self.groups.set_visible(False, 'dirty')

    def isComplete(self):
        'should Next button be sensitive?'
        return self._wctxcleaner.isClean()

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        pctx = self.repo['.']
        self.localCsInfo.update(pctx)

    def canExit(self):
        'can backout tool be closed?'
        if self._wctxcleaner.isChecking():
            self._wctxcleaner.cancelCheck()
        return True

    def currentPage(self):
        self.refresh()

    def refresh(self):
        self._wctxcleaner.check()

    @pyqtSlot()
    def _onCheckStarted(self):
        self.groups.set_visible(True, 'prog')

    @pyqtSlot(bool)
    def _onCheckFinished(self, clean):
        self.groups.set_visible(False, 'prog')
        if self._wctxcleaner.isCheckCanceled():
            return
        if not clean:
            self.groups.set_visible(True, 'dirty')
            self.wd_status.set_status(_('<b>Uncommitted local changes '
                                        'are detected</b>'), 'thg-warning')
        else:
            self.groups.set_visible(False, 'dirty')
            self.wd_status.set_status(_('Clean'), True)
        self.completeChanged.emit()


class BackoutPage(BasePage):
    def __init__(self, repoagent, backoutrev, parentbackout, parent):
        super(BackoutPage, self).__init__(repoagent, parent)
        self._backoutrev = backoutrev
        self._parentbackout = parentbackout
        self.backoutcomplete = False

        self.setTitle(_('Backing out, then merging...'))
        self.setSubTitle(_('All conflicting files will be marked unresolved.'))
        self.setLayout(QVBoxLayout())

        self._cmdlog = cmdui.LogWidget(self)
        self.layout().addWidget(self._cmdlog)

        self.reslabel = QLabel()
        self.reslabel.linkActivated.connect(self.onLinkActivated)
        self.reslabel.setWordWrap(True)
        self.layout().addWidget(self.reslabel)

        autonext = QCheckBox(_('Automatically advance to next page '
                               'when backout and merge are complete.'))
        autonext.clicked.connect(self.tryAutoAdvance)
        self.registerField('autoadvance', autonext)
        self.layout().addWidget(autonext)

    def currentPage(self):
        if self._parentbackout:
            self.wizard().next()
            return
        tool = self.field('autoresolve').toBool() and ':merge' or ':fail'
        cmdline = hglib.buildcmdargs('backout', self._backoutrev, tool=tool,
                                     no_commit=True)
        self._cmdlog.clearLog()
        sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self.onCommandFinished)
        sess.outputReceived.connect(self._cmdlog.appendLog)

    def isComplete(self):
        'should Next button be sensitive?'
        if not self.backoutcomplete:
            return False
        count = 0
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                count += 1
        if count:
            # if autoresolve is enabled, we know these were real conflicts
            self.reslabel.setText(_('%d files have <b>merge conflicts</b> '
                                    'that must be <a href="resolve">'
                                    '<b>resolved</b></a>') % count)
            return False
        else:
            self.reslabel.setText(_('No merge conflicts, ready to commit'))
            return True

    @pyqtSlot(bool)
    def tryAutoAdvance(self, checked):
        if checked and self.isComplete():
            self.wizard().next()

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        if ret in (0, 1):
            self.backoutcomplete = True
            if self.field('autoadvance').toBool():
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

    def __init__(self, repoagent, backoutrev, parentbackout, parent):
        super(CommitPage, self).__init__(repoagent, parent)
        self._backoutrev = backoutrev
        self._parentbackout = parentbackout
        self.commitComplete = False

        self.setTitle(_('Commit backout and merge results'))
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
                if parentbackout:
                    return '%s (%s)' % (text, rev)
                else:
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
        bkCsInfo = csinfo.create(repo, None, style, custom=custom,
                                 withupdate=True)
        bkCsInfo.linkActivated.connect(self.onLinkActivated)
        self.layout().addWidget(bkCsInfo)

        # commit message area
        msg_sep = qtlib.LabeledSeparator(_('Commit message'))
        self.layout().addWidget(msg_sep)
        msgEntry = messageentry.MessageEntry(self)
        msgEntry.installEventFilter(qscilib.KeyPressInterceptor(self))
        msgEntry.refresh(repo)
        msgEntry.loadSettings(QSettings(), 'backout/message')

        msgEntry.textChanged.connect(self.completeChanged)
        self.layout().addWidget(msgEntry)
        self.msgEntry = msgEntry

        self._cmdsession = cmdcore.nullCmdSession()
        self._cmdlog = cmdui.LogWidget(self)
        self._cmdlog.hide()
        self.layout().addWidget(self._cmdlog)

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

        def eng_toggled(checked):
            if self.isComplete():
                oldmsg = self.msgEntry.text()
                msgset = i18n.keepgettext()._('Backed out changeset: ')
                msg = checked and msgset['id'] or msgset['str']
                if oldmsg and oldmsg != msg:
                    if not qtlib.QuestionMsgBox(_('Confirm Discard Message'),
                         _('Discard current backout message?'), parent=self):
                        self.engChk.blockSignals(True)
                        self.engChk.setChecked(not checked)
                        self.engChk.blockSignals(False)
                        return
                self.msgEntry.setText(msg + str(self.repo[self._backoutrev]))
                self.msgEntry.moveCursorToEnd()

        self.engChk = QCheckBox(_('Use English backout message'))
        self.engChk.toggled.connect(eng_toggled)
        engmsg = self.repo.ui.configbool('tortoisehg', 'engmsg', False)
        self.engChk.setChecked(engmsg)
        self.layout().addWidget(self.engChk)

    def refresh(self):
        pass

    def cleanupPage(self):
        s = QSettings()
        self.msgEntry.saveSettings(s, 'backout/message')

    def currentPage(self):
        engmsg = self.repo.ui.configbool('tortoisehg', 'engmsg', False)
        msgset = i18n.keepgettext()._('Backed out changeset: ')
        msg = engmsg and msgset['id'] or msgset['str']
        self.msgEntry.setText(msg + str(self.repo[self._backoutrev]))
        self.msgEntry.moveCursorToEnd()

    @pyqtSlot(str)
    def onLinkActivated(self, cmd):
        if cmd == 'view':
            dlg = status.StatusDialog(self._repoagent, [], {}, self)
            dlg.exec_()
            self.refresh()

    def isComplete(self):
        return len(self.msgEntry.text()) > 0

    def validatePage(self):
        if self.commitComplete:
            # commit succeeded, repositoryChanged() called wizard().next()
            if self.field('skiplast').toBool():
                self.wizard().close()
            return True
        if not self._cmdsession.isFinished():
            return False

        user = hglib.tounicode(qtlib.getCurrentUsername(self, self.repo))
        if not user:
            return False

        if self._parentbackout:
            self.setTitle(_('Backing out and committing...'))
            self.setSubTitle(_('Please wait while making backout.'))
            message = unicode(self.msgEntry.text())
            cmdline = hglib.buildcmdargs('backout', self._backoutrev,
                                         verbose=True,
                                         message=message, user=user)
        else:
            self.setTitle(_('Committing...'))
            self.setSubTitle(_('Please wait while committing merged files.'))
            message = unicode(self.msgEntry.text())
            cmdline = hglib.buildcmdargs('commit', verbose=True,
                                         message=message, user=user)
        commandlines = [cmdline]
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

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        if ret == 0:
            self.commitComplete = True
            self.wizard().next()


class ResultPage(BasePage):
    def __init__(self, repoagent, parent):
        super(ResultPage, self).__init__(repoagent, parent)
        self.setTitle(_('Finished'))
        self.setSubTitle(' ')
        self.setFinalPage(True)

        self.setLayout(QVBoxLayout())
        sep = qtlib.LabeledSeparator(_('Backout changeset'))
        self.layout().addWidget(sep)
        bkCsInfo = csinfo.create(self.repo, 'tip', withupdate=True)
        self.layout().addWidget(bkCsInfo)
        self.bkCsInfo = bkCsInfo
        self.layout().addStretch(1)

    def currentPage(self):
        self.bkCsInfo.update(self.repo['tip'])
        self.wizard().setOption(QWizard.NoCancelButton, True)
