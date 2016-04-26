# commit.py - TortoiseHg's commit widget and standalone dialog
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import re
import tempfile
import time

from mercurial import util, error, scmutil, phases
from mercurial import obsolete  # delete if obsolete becomes enabled by default

from tortoisehg.util import hglib, i18n, shlib, wconfig
from tortoisehg.util.i18n import _

from tortoisehg.hgqt.messageentry import MessageEntry
from tortoisehg.hgqt import cmdcore, cmdui, thgrepo
from tortoisehg.hgqt import qtlib, qscilib, status, branchop, revpanel
from tortoisehg.hgqt import hgrcutil, lfprompt

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciAPIs

if os.name == 'nt':
    from tortoisehg.util import bugtraq
    _hasbugtraq = True
else:
    _hasbugtraq = False

def readopts(ui):
    opts = {}
    opts['ciexclude'] = ui.config('tortoisehg', 'ciexclude', '')
    opts['pushafter'] = ui.config('tortoisehg', 'cipushafter', '')
    opts['autoinc'] = ui.config('tortoisehg', 'autoinc', '')
    opts['recurseinsubrepos'] = ui.config('tortoisehg', 'recurseinsubrepos')
    opts['bugtraqplugin'] = ui.config('tortoisehg', 'issue.bugtraqplugin')
    opts['bugtraqparameters'] = ui.config('tortoisehg',
                                          'issue.bugtraqparameters')
    if opts['bugtraqparameters']:
        opts['bugtraqparameters'] = os.path.expandvars(
            opts['bugtraqparameters'])
    opts['bugtraqtrigger'] = ui.config('tortoisehg', 'issue.bugtraqtrigger')

    return opts

def commitopts2str(opts, mode='commit'):
    optslist = []
    for opt, value in opts.iteritems():
        if opt in ['user', 'date', 'pushafter', 'autoinc',
                   'recurseinsubrepos']:
            if mode == 'merge' and opt == 'autoinc':
                # autoinc does not apply to merge commits
                continue
            if value is True:
                optslist.append('--' + opt)
            elif value:
                optslist.append('--%s=%s' % (opt, value))
    return ' '.join(optslist)

def mergecommitmessage(repo):
    wctx = repo[None]
    engmsg = repo.ui.configbool('tortoisehg', 'engmsg', False)
    if wctx.p1().branch() == wctx.p2().branch():
        msgset = i18n.keepgettext()._('Merge')
        text = engmsg and msgset['id'] or msgset['str']
        text = unicode(text)
    else:
        msgset = i18n.keepgettext()._('Merge with %s')
        text = engmsg and msgset['id'] or msgset['str']
        text = unicode(text) % hglib.tounicode(wctx.p2().branch())
    return text

def _getUserOptions(opts, *optionlist):
    out = []
    for opt in optionlist:
        if opt not in opts:
            continue
        val = opts[opt]
        if val is False:
            continue
        elif val is True:
            out.append('--' + opt)
        else:
            out.append('--' + opt)
            out.append(val)
    return out

def _mqNewRefreshCommand(repo, isnew, stwidget, pnwidget, message, opts, olist):
    if isnew:
        name = hglib.fromunicode(pnwidget.text())
        if not name:
            qtlib.ErrorMsgBox(_('Patch Name Required'),
                              _('You must enter a patch name'))
            pnwidget.setFocus()
            return
        cmdline = ['qnew', name]
    else:
        cmdline = ['qrefresh']
    if message:
        cmdline += ['--message=' + hglib.fromunicode(message)]
    cmdline += _getUserOptions(opts, *olist)
    files = ['--'] + [repo.wjoin(x) for x in stwidget.getChecked()]
    addrem = [repo.wjoin(x) for x in stwidget.getChecked('!?')]
    if len(files) > 1:
        cmdline += files
    else:
        cmdline += ['--exclude', repo.root]
    if addrem:
        cmdlines = [['addremove'] + addrem, cmdline]
    else:
        cmdlines = [cmdline]
    return cmdlines

_topicmap = {
    'amend': _('Commit', 'start progress'),
    'commit': _('Commit', 'start progress'),
    'qnew': _('MQ Action', 'start progress'),
    'qref': _('MQ Action', 'start progress'),
    'rollback': _('Rollback', 'start progress'),
    }

# Technical Debt for CommitWidget
#  disable commit button while no message is entered or no files are selected
#  qtlib decode failure dialog (ask for retry locale, suggest HGENCODING)
#  spell check / tab completion
#  in-memory patching / committing chunk selected files

class CommitWidget(QWidget, qtlib.TaskWidget):
    'A widget that encompasses a StatusWidget and commit extras'
    commitButtonEnable = pyqtSignal(bool)
    linkActivated = pyqtSignal(str)
    showMessage = pyqtSignal(str)
    grepRequested = pyqtSignal(str, dict)
    runCustomCommandRequested = pyqtSignal(str, list)
    commitComplete = pyqtSignal()

    progress = pyqtSignal(str, object, str, str, object)

    def __init__(self, repoagent, pats, opts, parent=None, rev=None):
        QWidget.__init__(self, parent)

        repoagent.configChanged.connect(self.refresh)
        repoagent.repositoryChanged.connect(self.repositoryChanged)
        self._repoagent = repoagent
        repo = repoagent.rawRepo()
        self._cmdsession = cmdcore.nullCmdSession()
        self._rev = rev
        self.lastAction = None
        # Dictionary storing the last (commit message, modified flag)
        # 'commit' is used for 'commit' and 'qnew', while
        # 'amend' is used for 'amend' and 'qrefresh'
        self.lastCommitMsgs = {'commit': ('', False), 'amend': ('', False)}
        self.currentAction = None

        self.opts = opts = readopts(repo.ui) # user, date

        self.stwidget = status.StatusWidget(repoagent, pats, opts, self)
        self.stwidget.showMessage.connect(self.showMessage)
        self.stwidget.progress.connect(self.progress)
        self.stwidget.linkActivated.connect(self.linkActivated)
        self.stwidget.fileDisplayed.connect(self.fileDisplayed)
        self.stwidget.grepRequested.connect(self.grepRequested)
        self.stwidget.runCustomCommandRequested.connect(
            self.runCustomCommandRequested)
        self.msghistory = []

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(self.stwidget)
        self.setLayout(layout)

        vbox = QVBoxLayout()
        vbox.setMargin(0)
        vbox.setSpacing(0)
        vbox.setContentsMargins(*(0,)*4)

        hbox = QHBoxLayout()
        hbox.setMargin(0)
        hbox.setContentsMargins(*(0,)*4)
        tbar = QToolBar(_("Commit Dialog Toolbar"), self)
        tbar.setStyleSheet(qtlib.tbstylesheet)
        hbox.addWidget(tbar)

        self.branchbutton = tbar.addAction(_('Branch: '))
        font = self.branchbutton.font()
        font.setBold(True)
        self.branchbutton.setFont(font)
        self.branchbutton.triggered.connect(self.branchOp)
        self.branchop = None

        self.recentMessagesButton = QToolButton(
            text=_('Copy message'),
            popupMode=QToolButton.InstantPopup,
            toolTip=_('Copy one of the recent commit messages'))
        m = QMenu(self.recentMessagesButton)
        m.triggered.connect(self.msgSelected)
        self.recentMessagesButton.setMenu(m)
        tbar.addWidget(self.recentMessagesButton)
        self.updateRecentMessages()

        tbar.addAction(_('Options')).triggered.connect(self.details)
        tbar.setIconSize(qtlib.smallIconSize())

        if _hasbugtraq and self.opts['bugtraqplugin'] != None:
            # We create the "Show Issues" button, but we delay its setup
            # because creating the bugtraq object is slow and blocks the GUI,
            # which would result in a noticeable slow down while creating
            # the commit widget
            self.showIssues = tbar.addAction(_('Show Issues'))
            self.showIssues.setEnabled(False)
            self.showIssues.setToolTip(_('Please wait...'))
            def setupBugTraqButton():
                self.bugtraq = self.createBugTracker()
                try:
                    parameters = self.opts['bugtraqparameters']
                    linktext = self.bugtraq.get_link_text(parameters)
                except Exception, e:
                    tracker = self.opts['bugtraqplugin'].split(' ', 1)[1]
                    errormsg =  _('Failed to load issue tracker \'%s\': %s') \
                                 % (tracker, hglib.tounicode(str(e)))
                    self.showIssues.setToolTip(errormsg)
                    qtlib.ErrorMsgBox(_('Issue Tracker'), errormsg,
                                      parent=self)
                    self.bugtraq = None
                else:
                    # connect UI because we have a valid bug tracker
                    self.commitComplete.connect(self.bugTrackerPostCommit)
                    self.showIssues.setText(linktext)
                    self.showIssues.triggered.connect(
                        self.getBugTrackerCommitMessage)
                    self.showIssues.setToolTip(_('Show Issues...'))
                    self.showIssues.setEnabled(True)
            QTimer.singleShot(100, setupBugTraqButton)

        self.stopAction = tbar.addAction(_('Stop'))
        self.stopAction.triggered.connect(self.stop)
        self.stopAction.setIcon(qtlib.geticon('process-stop'))
        self.stopAction.setEnabled(False)

        hbox.addStretch(1)

        vbox.addLayout(hbox, 0)
        self.buttonHBox = hbox

        if 'mq' in self.repo.extensions():
            self.hasmqbutton = True
            pnhbox = QHBoxLayout()
            self.pnlabel = QLabel()
            pnhbox.addWidget(self.pnlabel)
            self.pnedit = QLineEdit()
            if hasattr(self.pnedit, 'setPlaceholderText'):  # Qt >= 4.7
                self.pnedit.setPlaceholderText(_('### patch name ###'))
            self.pnedit.setMaximumWidth(250)
            pnhbox.addWidget(self.pnedit)
            pnhbox.addStretch()
            vbox.addLayout(pnhbox)
        else:
            self.hasmqbutton = False

        self.optionslabel = QLabel()
        self.optionslabel.setSizePolicy(QSizePolicy.Ignored,
                                        QSizePolicy.Preferred)
        vbox.addWidget(self.optionslabel, 0)

        self.pcsinfo = revpanel.ParentWidget(repo)
        vbox.addWidget(self.pcsinfo, 0)

        msgte = MessageEntry(self, self.stwidget.getChecked)
        msgte.installEventFilter(qscilib.KeyPressInterceptor(self))
        vbox.addWidget(msgte, 1)
        upperframe = QFrame()

        SP = QSizePolicy
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(1)
        upperframe.setSizePolicy(sp)
        upperframe.setLayout(vbox)

        self.split = QSplitter(Qt.Vertical)
        if os.name == 'nt':
            self.split.setStyle(QStyleFactory.create('Plastique'))
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(1)
        sp.setVerticalStretch(0)
        self.split.setSizePolicy(sp)
        # Add our widgets to the top of our splitter
        self.split.addWidget(upperframe)
        self.split.setCollapsible(0, False)
        # Add status widget document frame below our splitter
        # this reparents the docf from the status splitter
        self.split.addWidget(self.stwidget.docf)

        # add our splitter where the docf used to be
        self.stwidget.split.addWidget(self.split)
        self.msgte = msgte

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    @property
    def rev(self):
        """Return current revision"""
        return self._rev

    def selectRev(self, rev):
        """
        Select the revision that must be set when the dialog is shown again
        """
        self._rev = rev

    @pyqtSlot(int)
    @pyqtSlot(object)
    def setRev(self, rev):
        """Change revision to show"""
        self.selectRev(rev)
        if self.hasmqbutton:
            preferredActionName = self._getPreferredActionName()
            curractionName = self.mqgroup.checkedAction()._name
            if curractionName != preferredActionName:
                self.commitSetAction(refresh=True,
                    actionName=preferredActionName)

    def _getPreferredActionName(self):
        """Select the preferred action, depending on the selected revision"""
        if not self.hasmqbutton:
            return 'commit'
        else:
            pctx = self.repo.changectx('.')
            ispatch = 'qtip' in pctx.tags()
            if not ispatch:
                # Set the button to Commit
                return 'commit'
            elif self.rev is None:
                # Set the button to QNew
                return 'qnew'
            else:
                # Set the button to QRefresh
                return 'qref'

    def commitSetupButton(self):
        ispatch = lambda r: 'qtip' in r.changectx('.').tags()
        notpatch = lambda r: 'qtip' not in r.changectx('.').tags()
        def canamend(r):
            if ispatch(r):
                return False
            ctx = r.changectx('.')
            return (ctx.phase() != phases.public) \
                and len(r.changectx(None).parents()) < 2 \
                and (obsolete._enabled or not ctx.children())

        acts = [
            ('commit', _('Commit changes'), _('Commit'), notpatch),
            ('amend', _('Amend current revision'), _('Amend'), canamend),
        ]
        if self.hasmqbutton:
            acts += [
                ('qnew', _('Create a new patch'), _('QNew'), None),
                ('qref', _('Refresh current patch'), _('QRefresh'), ispatch),
            ]
        acts = tuple(acts)

        class CommitToolButton(QToolButton):
            def styleOption(self):
                opt = QStyleOptionToolButton()
                opt.initFrom(self)
                return opt
            def menuButtonWidth(self):
                style = self.style()
                opt = self.styleOption()
                opt.features = QStyleOptionToolButton.MenuButtonPopup
                rect = style.subControlRect(QStyle.CC_ToolButton, opt,
                                            QStyle.SC_ToolButtonMenu, self)
                return rect.width()
            def setBold(self):
                f = self.font()
                f.setWeight(QFont.Bold)
                self.setFont(f)
            def sizeHint(self):
                # Set the desired width to keep the button from resizing
                return QSize(self._width, QToolButton.sizeHint(self).height())

        self.committb = committb = CommitToolButton(self)
        committb.setBold()
        committb.setPopupMode(QToolButton.MenuButtonPopup)
        fmk = lambda s: committb.fontMetrics().width(hglib.tounicode(s[2]))
        committb._width = max(map(fmk, acts)) + 4*committb.menuButtonWidth()

        class CommitButtonMenu(QMenu):
            def __init__(self, parent, repo):
                self.repo = repo
                return QMenu.__init__(self, parent)
            def getActionByName(self, act):
                return [a for a in self.actions() if a._name == act][0]
            def showEvent(self, event):
                for a in self.actions():
                    if a._enablefunc:
                        a.setEnabled(a._enablefunc(self.repo))
                return QMenu.showEvent(self, event)
        self.mqgroup = QActionGroup(self)
        commitbmenu = CommitButtonMenu(committb, self.repo)
        menurefresh = lambda: self.commitSetAction(refresh=True)
        for a in acts:
            action = QAction(a[1], self.mqgroup)
            action._name = a[0]
            action._text = a[2]
            action._enablefunc = a[3]
            action.triggered.connect(menurefresh)
            action.setCheckable(True)
            commitbmenu.addAction(action)
        committb.setMenu(commitbmenu)
        committb.clicked.connect(self.mqPerformAction)
        self.commitButtonEnable.connect(committb.setEnabled)
        self.commitSetAction(actionName=self._getPreferredActionName())
        sc = QShortcut(QKeySequence('Ctrl+Return'), self, self.mqPerformAction)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc = QShortcut(QKeySequence('Ctrl+Enter'), self, self.mqPerformAction)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        return committb

    @pyqtSlot(bool)
    def commitSetAction(self, refresh=False, actionName=None):
        allowcs = False
        if actionName:
            selectedAction = \
                [act for act in self.mqgroup.actions() \
                    if act._name == actionName][0]
            selectedAction.setChecked(True)
        curraction = self.mqgroup.checkedAction()
        oldpctx = self.stwidget.pctx
        pctx = self.repo.changectx('.')
        if curraction._name == 'qnew':
            self.pnlabel.setVisible(True)
            self.pnedit.setVisible(True)
            self.pnedit.setFocus()
            pn = time.strftime('%Y-%m-%d_%H-%M-%S')
            pn += '_r%d+.diff' % self.repo['.'].rev()
            self.pnedit.setText(pn)
            self.pnedit.selectAll()
            self.stwidget.setPatchContext(None)
            refreshwctx = refresh and oldpctx is not None
        else:
            if self.hasmqbutton:
                self.pnlabel.setVisible(False)
                self.pnedit.setVisible(False)
            ispatch = 'qtip' in pctx.tags()
            def switchAction(action, name):
                action.setChecked(False)
                action = self.committb.menu().getActionByName(name)
                action.setChecked(True)
                return action
            if curraction._name == 'qref' and not ispatch:
                curraction = switchAction(curraction, 'commit')
            elif curraction._name == 'commit' and ispatch:
                curraction = switchAction(curraction, 'qref')
            if curraction._name in ('qref', 'amend'):
                refreshwctx = refresh
                self.stwidget.setPatchContext(pctx)
            elif curraction._name == 'commit':
                refreshwctx = refresh and oldpctx is not None
                self.stwidget.setPatchContext(None)
                allowcs = len(self.repo[None].parents()) == 1
        if curraction._name in ('qref', 'amend'):
            if self.lastAction not in ('qref', 'amend'):
                self.lastCommitMsgs['commit'] = (self.msgte.text(),
                                                 self.msgte.isModified())
            if self.lastCommitMsgs['amend'][0]:
                self.setMessage(*self.lastCommitMsgs['amend'])
            elif oldpctx is None or oldpctx.node() != pctx.node():
                # pctx must be refreshed if hash changes
                self.setMessage(hglib.tounicode(pctx.description()))
        else:
            if self.lastAction in ('qref', 'amend'):
                self.lastCommitMsgs['amend'] = (self.msgte.text(),
                                                self.msgte.isModified())
                self.setMessage(*self.lastCommitMsgs['commit'])
            elif len(self.repo[None].parents()) > 1:
                self.setMessage(mergecommitmessage(self.repo))
        if curraction._name == 'amend':
            self.stwidget.defcheck = 'amend'
        else:
            self.stwidget.defcheck = 'commit'
        self.stwidget.fileview.enableChangeSelection(allowcs)
        if not allowcs:
            self.stwidget.partials = {}
        if refreshwctx:
            self.stwidget.refreshWctx()
        self.committb.setText(curraction._text)
        self.lastAction = curraction._name

    def getBranchCommandLine(self):
        '''
        Create the command line to change or create the selected branch unless
        it is the selected branch

        Verify whether a branch exists on a repo. If it doesn't ask the user
        to confirm that it wants to create the branch. If it does and it is not
        the current branch as the user whether it wants to change to that branch.
        Depending on the user input, create the command line which will perform
        the selected action
        '''
        # This function is used both by commit() and mqPerformAction()
        repo = self.repo
        commandlines = []
        newbranch = False
        branch = hglib.fromunicode(self.branchop)
        if branch in repo.branchmap():
            # response: 0=Yes, 1=No, 2=Cancel
            if branch in [p.branch() for p in repo[None].parents()]:
                resp = 0
            else:
                rev = repo[branch].rev()
                resp = qtlib.CustomPrompt(_('Confirm Branch Change'),
                    _('Named branch "%s" already exists, '
                      'last used in revision %d\n'
                      ) % (self.branchop, rev),
                    self,
                    (_('Restart &Branch'),
                     _('&Commit to current branch'),
                     _('Cancel')), 2, 2).run()
        else:
            resp = qtlib.CustomPrompt(_('Confirm New Branch'),
                _('Create new named branch "%s" with this commit?\n'
                  ) % self.branchop,
                self,
                (_('Create &Branch'),
                 _('&Commit to current branch'),
                 _('Cancel')), 2, 2).run()
        if resp == 0:
            newbranch = True
            commandlines.append(['branch', '--force', branch])
        elif resp == 2:
            return None, False
        return commandlines, newbranch

    @pyqtSlot()
    def mqPerformAction(self):
        curraction = self.mqgroup.checkedAction()
        if curraction._name == 'commit':
            return self.commit()
        elif curraction._name == 'amend':
            return self.commit(amend=True)

        # Check if we need to change branch first
        wholecmdlines = []  # [[cmd1, ...], [cmd2, ...], ...]
        if self.branchop:
            cmdlines, newbranch = self.getBranchCommandLine()
            if cmdlines is None:
                return
            wholecmdlines.extend(cmdlines)

        olist = ('user', 'date')
        cmdlines = _mqNewRefreshCommand(self.repo,
                                        curraction._name == 'qnew',
                                        self.stwidget, self.pnedit,
                                        self.msgte.text(), self.opts,
                                        olist)
        if not cmdlines:
            return
        wholecmdlines.extend(cmdlines)
        self._runCommand(curraction._name, wholecmdlines)

    @pyqtSlot(str, str)
    def fileDisplayed(self, wfile, contents):
        'Status widget is displaying a new file'
        if not (wfile and contents):
            return
        if self.msgte.autoCompletionThreshold() <= 0:
            # do not search for tokens if auto completion is disabled
            # pygments has several infinite loop problems we'd like to avoid
            return
        if self.msgte.lexer() is None:
            # qsci will crash if None is passed to QsciAPIs constructor
            return
        wfile = unicode(wfile)
        self._apis = QsciAPIs(self.msgte.lexer())
        tokens = set()
        for e in self.stwidget.getChecked():
            e = hglib.tounicode(e)
            tokens.add(e)
            tokens.add(os.path.basename(e))
        tokens.add(wfile)
        tokens.add(os.path.basename(wfile))
        try:
            from pygments.lexers import guess_lexer_for_filename
            from pygments.token import Token
            from pygments.util import ClassNotFound
            try:
                contents = unicode(contents)
                lexer = guess_lexer_for_filename(wfile, contents)
                for tokentype, value in lexer.get_tokens(contents):
                    if tokentype in Token.Name and len(value) > 4:
                        tokens.add(value)
            except ClassNotFound, TypeError:
                pass
        except ImportError:
            pass
        for n in sorted(list(tokens)):
            self._apis.add(n)
        self._apis.apiPreparationFinished.connect(self.apiPrepFinished)
        self._apis.prepare()

    def apiPrepFinished(self):
        'QsciAPIs has finished parsing displayed file'
        self.msgte.lexer().setAPIs(self._apis)

    def bugTrackerPostCommit(self):
        if not _hasbugtraq or self.opts['bugtraqtrigger'] != 'commit':
            return
        # commit already happened, get last message in history
        message = self.lastmessage
        error = self.bugtraq.on_commit_finished(message)
        if error != None and len(error) > 0:
            qtlib.ErrorMsgBox(_('Issue Tracker'), error, parent=self)
        # recreate bug tracker to get new COM object for next commit
        self.bugtraq = self.createBugTracker()

    def createBugTracker(self):
        bugtraqid = self.opts['bugtraqplugin'].split(' ', 1)[0]
        result = bugtraq.BugTraq(bugtraqid)
        return result

    def getBugTrackerCommitMessage(self):
        parameters = self.opts['bugtraqparameters']
        message = self.getMessage(True)
        newMessage = self.bugtraq.get_commit_message(parameters, message)
        self.setMessage(newMessage)

    def details(self):
        mode = 'commit'
        if len(self.repo[None].parents()) > 1:
            mode = 'merge'
        dlg = DetailsDialog(self._repoagent, self.opts, self.userhist, self,
                            mode=mode)
        dlg.finished.connect(dlg.deleteLater)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self.opts.update(dlg.outopts)
            self.refresh()

    @pyqtSlot(int)
    def repositoryChanged(self, flags):
        if flags & thgrepo.WorkingParentChanged:
            self._refreshWorkingState()
        elif flags & thgrepo.WorkingBranchChanged:
            self.refresh()

    def _refreshWorkingState(self):
        curraction = self.mqgroup.checkedAction()
        if curraction._name == 'commit' and not self.msgte.isModified():
            # default merge or close-branch message is outdated if new commit
            # was made by other widget or process
            self.msgte.clear()
        self.lastCommitMsgs['amend'] = ('', False)  # avoid loading stale cache
        # refresh() may load/save the stale 'amend' message in commitSetAction()
        self.refresh()
        self.stwidget.refreshWctx() # Trigger reload of working context
        # clear the last 'amend' message
        # do not clear the last 'commit' message because there are many cases
        # in which we may write a commit message first, modify the repository
        # (e.g. amend or update and merge uncommitted changes) and then do the
        # actual commit
        self.lastCommitMsgs['amend'] = ('', False)  # clear saved stale cache

    @pyqtSlot()
    def refreshWctx(self):
        'User has requested a working context refresh'
        self.stwidget.refreshWctx() # Trigger reload of working context

    @pyqtSlot()
    def reload(self):
        'User has requested a reload'
        self.repo.thginvalidate()
        self.refresh()
        self.stwidget.refreshWctx() # Trigger reload of working context

    @pyqtSlot()
    def refresh(self):
        ispatch = self.repo.changectx('.').thgmqappliedpatch()
        if not self.hasmqbutton:
            self.commitButtonEnable.emit(not ispatch)
        self.msgte.refresh(self.repo)

        # Update branch operation button
        branchu = hglib.tounicode(self.repo[None].branch())
        if self.branchop is None:
            title = _('Branch: ') + branchu
        elif self.branchop == False:
            title = _('Close Branch: ') + branchu
        else:
            title = _('New Branch: ') + self.branchop
        self.branchbutton.setText(title)

        # Update options label, showing only whitelisted options.
        opts = commitopts2str(self.opts)
        self.optionslabelfmt = _('<b>Selected Options:</b> %s')
        self.optionslabel.setText(self.optionslabelfmt
                                  % Qt.escape(hglib.tounicode(opts)))
        self.optionslabel.setVisible(bool(opts))

        # Update parent csinfo widget
        self.pcsinfo.set_revision(None)
        self.pcsinfo.update()

        # This is ugly, but want pnlabel to have the same alignment/style/etc
        # as pcsinfo, so extract the needed parts of pcsinfo's markup.  Would
        # be nicer if csinfo exposed this information, or if csinfo could hold
        # widgets like pnlabel.
        if self.hasmqbutton:
            parent = _('Parent:')
            patchname = _('Patch name:')
            text = unicode(self.pcsinfo.revlabel.text())
            cellend = '</td>'
            firstidx = text.find(cellend) + len(cellend)
            secondidx = text[firstidx:].rfind('</tr>')
            if firstidx >= 0 and secondidx >= 0:
                start = text[0:firstidx].replace(parent, patchname)
                self.pnlabel.setText(start + text[firstidx+secondidx:])
            else:
                self.pnlabel.setText(patchname)
            self.commitSetAction()

    def branchOp(self):
        d = branchop.BranchOpDialog(self._repoagent, self.branchop, self)
        d.setWindowFlags(Qt.Sheet)
        d.setWindowModality(Qt.WindowModal)
        if d.exec_() == QDialog.Accepted:
            self.branchop = d.branchop
            if self.branchop is False:
                if not self.getMessage(True).strip():
                    engmsg = self.repo.ui.configbool(
                        'tortoisehg', 'engmsg', False)
                    msgset = i18n.keepgettext()._('Close %s branch')
                    text = engmsg and msgset['id'] or msgset['str']
                    self.setMessage(unicode(text) %
                                    hglib.tounicode(self.repo[None].branch()))
            self.refresh()

    def canUndo(self):
        'Returns undo description or None if not valid'
        desc, oldlen = hglib.readundodesc(self.repo)
        if desc == 'commit':
            return _('Rollback commit to revision %d') % (oldlen - 1)
        return None

    def rollback(self):
        msg = self.canUndo()
        if not msg:
            return
        d = QMessageBox.question(self, _('Confirm Undo'), msg,
                                 QMessageBox.Ok | QMessageBox.Cancel)
        if d != QMessageBox.Ok:
            return
        self._runCommand('rollback', [['rollback']])

    def updateRecentMessages(self):
        # Define a menu that lists recent messages
        m = self.recentMessagesButton.menu()
        m.clear()
        for s in self.msghistory:
            title = s.split('\n', 1)[0][:70]
            a = m.addAction(title)
            a.setData(s)

    def getMessage(self, allowreplace):
        text = self.msgte.text()
        try:
            return hglib.fromunicode(text, 'strict')
        except UnicodeEncodeError:
            if allowreplace:
                return hglib.fromunicode(text, 'replace')
            else:
                raise

    @pyqtSlot(QAction)
    def msgSelected(self, action):
        if self.msgte.text() and self.msgte.isModified():
            d = QMessageBox.question(self, _('Confirm Discard Message'),
                        _('Discard current commit message?'),
                        QMessageBox.Ok | QMessageBox.Cancel)
            if d != QMessageBox.Ok:
                return
        message = action.data().toString()
        self.setMessage(message)
        self.msgte.setFocus()

    def setMessage(self, msg, modified=False):
        self.msgte.setText(msg)
        self.msgte.moveCursorToEnd()
        self.msgte.setModified(modified)

    def canExit(self):
        if not self.stwidget.canExit():
            return False
        return self._cmdsession.isFinished()

    def loadSettings(self, s, prefix):
        'Load history, etc, from QSettings instance'
        repoid = hglib.shortrepoid(self.repo)
        lpref = prefix + '/commit/' # local settings (splitter, etc)
        gpref = 'commit/'           # global settings (history, etc)
        # message history is stored in unicode
        self.split.restoreState(s.value(lpref+'split').toByteArray())
        self.msgte.loadSettings(s, lpref+'msgte')
        self.stwidget.loadSettings(s, lpref+'status')
        self.msghistory = list(s.value(gpref+'history-'+repoid).toStringList())
        self.msghistory = [unicode(m) for m in self.msghistory if m]
        self.updateRecentMessages()
        self.userhist = map(unicode, s.value(gpref+'userhist').toStringList())
        self.userhist = [u for u in self.userhist if u]
        try:
            curmsg = self.repo.opener('cur-message.txt').read()
            self.setMessage(hglib.tounicode(curmsg))
        except EnvironmentError:
            pass
        try:
            curmsg = self.repo.opener('last-message.txt').read()
            if curmsg:
                self.addMessageToHistory(hglib.tounicode(curmsg))
        except EnvironmentError:
            pass

    def saveSettings(self, s, prefix):
        'Save history, etc, in QSettings instance'
        try:
            repoid = hglib.shortrepoid(self.repo)
            lpref = prefix + '/commit/'
            gpref = 'commit/'
            s.setValue(lpref+'split', self.split.saveState())
            self.msgte.saveSettings(s, lpref+'msgte')
            self.stwidget.saveSettings(s, lpref+'status')
            s.setValue(gpref+'history-'+repoid, self.msghistory)
            s.setValue(gpref+'userhist', self.userhist)
            msg = self.getMessage(True)
            self.repo.opener('cur-message.txt', 'w').write(msg)
        except (EnvironmentError, IOError):
            pass

    def addMessageToHistory(self, umsg):
        umsg = unicode(umsg)
        if umsg in self.msghistory:
            self.msghistory.remove(umsg)
        self.msghistory.insert(0, umsg)
        self.msghistory = self.msghistory[:10]
        self.updateRecentMessages()

    def addUsernameToHistory(self, user):
        user = hglib.tounicode(user)
        if user in self.userhist:
            self.userhist.remove(user)
        self.userhist.insert(0, user)
        self.userhist = self.userhist[:10]

    def commit(self, amend=False):
        repo = self.repo
        try:
            msg = self.getMessage(False)
        except UnicodeEncodeError:
            res = qtlib.CustomPrompt(
                    _('Message Translation Failure'),
                    _('Unable to translate message to local encoding.\n'
                      'Consider setting HGENCODING environment variable.\n\n'
                      'Replace untranslatable characters with "?"?\n'), self,
                     (_('&Replace'), _('Cancel')), 0, 1, []).run()
            if res == 0:
                msg = self.getMessage(True)
                msg = str(msg)  # drop round-trip utf8 data
                self.msgte.setText(hglib.tounicode(msg))
            self.msgte.setFocus()
            return

        if not msg:
            qtlib.WarningMsgBox(_('Nothing Committed'),
                                _('Please enter commit message'),
                                parent=self)
            self.msgte.setFocus()
            return

        linkmandatory = self.repo.ui.configbool('tortoisehg',
                                                'issue.linkmandatory', False)
        if linkmandatory:
            issueregex = None
            s = self.repo.ui.config('tortoisehg', 'issue.regex')
            if s:
                try:
                    issueregex = re.compile(s)
                except re.error:
                    pass
            if issueregex:
                m = issueregex.search(msg)
                if not m:
                    qtlib.WarningMsgBox(_('Nothing Committed'),
                                        _('No issue link was found in the '
                                          'commit message.  The commit message '
                                          'should contain an issue link.  '
                                          "Configure this in the 'Issue "
                                          "Tracking' section of the settings."),
                                        parent=self)
                    self.msgte.setFocus()
                    return False

        commandlines = []

        brcmd = []
        newbranch = False
        if self.branchop is None:
            newbranch = repo[None].branch() != repo['.'].branch()
        elif self.branchop == False:
            brcmd = ['--close-branch']
        else:
            commandlines, newbranch = self.getBranchCommandLine()
            if commandlines is None:
                return
        partials = []
        if len(repo[None].parents()) > 1:
            merge = True
            self.files = []
        else:
            merge = False
            files = self.stwidget.getChecked('MAR?!IS')
            # make list of files with partial change selections
            for fname, c in self.stwidget.partials.iteritems():
                if c.excludecount > 0 and c.excludecount < len(c.hunks):
                    partials.append(fname)
            self.files = set(files + partials)
        canemptycommit = bool(brcmd or newbranch or amend)
        if not (self.files or canemptycommit or merge):
            qtlib.WarningMsgBox(_('No files checked'),
                                _('No modified files checkmarked for commit'),
                                parent=self)
            self.stwidget.tv.setFocus()
            return

        # username will be prompted as necessary by hg if ui.askusername
        user = self.opts.get('user')
        if not amend and not repo.ui.configbool('ui', 'askusername'):
            # TODO: no need to specify --user if it was read from ui
            user = qtlib.getCurrentUsername(self, self.repo, self.opts)
            if not user:
                return
            self.addUsernameToHistory(user)

        checkedUnknowns = self.stwidget.getChecked('?I')
        if checkedUnknowns and 'largefiles' in repo.extensions():
            result = lfprompt.promptForLfiles(self, repo.ui, repo,
                                              checkedUnknowns)
            if not result:
                return
            checkedUnknowns, lfiles = result
            if lfiles:
                cmd = ['add', '--large', '--']
                cmd.extend(map(hglib.escapepath, lfiles))
                commandlines.append(cmd)
        if checkedUnknowns:
            confirm = self.repo.ui.configbool('tortoisehg',
                                              'confirmaddfiles', True)
            if confirm:
                res = qtlib.CustomPrompt(
                        _('Confirm Add'),
                        _('Add selected untracked files?'), self,
                        (_('&Add'), _('Cancel')), 0, 1,
                        checkedUnknowns).run()
            else:
                res = 0
            if res == 0:
                cmd = ['add', '--']
                cmd.extend(map(hglib.escapepath, checkedUnknowns))
                commandlines.append(cmd)
            else:
                return
        checkedMissing = self.stwidget.getChecked('!')
        if checkedMissing:
            confirm = self.repo.ui.configbool('tortoisehg',
                                              'confirmdeletefiles', True)
            if confirm:
                res = qtlib.CustomPrompt(
                        _('Confirm Remove'),
                        _('Remove selected deleted files?'), self,
                        (_('&Remove'), _('Cancel')), 0, 1,
                        checkedMissing).run()
            else:
                res = 0
            if res == 0:
                cmd = ['remove', '--']
                cmd.extend(map(hglib.escapepath, checkedMissing))
                commandlines.append(cmd)
            else:
                return
        cmdline = ['commit', '--verbose', '--message='+msg]
        if user:
            cmdline.extend(['--user', user])
        date = self.opts.get('date')
        if date:
            cmdline += ['--date', date]
        cmdline += brcmd

        if partials:
            # write patch for partial change selections to temp file
            fd, tmpname = tempfile.mkstemp(prefix='thg-patch-')
            fp = os.fdopen(fd, 'wb')
            for fname in partials:
                changes = self.stwidget.partials[fname]
                changes.write(fp)
                for chunk in changes.hunks:
                    if not chunk.excluded:
                        chunk.write(fp)
            fp.close()

            cmdline.append('--partials')
            cmdline.append(tmpname)
            assert not amend

        if self.opts.get('recurseinsubrepos'):
            cmdline.append('--subrepos')

        if amend:
            cmdline.append('--amend')

        if not self.files and canemptycommit and not merge:
            # make sure to commit empty changeset by excluding all files
            cmdline.extend(['--exclude', repo.root])
            assert not self.stwidget.partials

        cmdline.append('--')
        cmdline.extend(map(hglib.escapepath, self.files))
        if len(repo[None].parents()) == 1:
            for fname in self.opts.get('autoinc', '').split(','):
                fname = fname.strip()
                if fname:
                    cmdline.append('glob:%s' % fname)
        commandlines.append(cmdline)

        if self.opts.get('pushafter'):
            cmd = ['push', self.opts['pushafter']]
            if newbranch:
                cmd.append('--new-branch')
            commandlines.append(cmd)

        self._runCommand(amend and 'amend' or 'commit', commandlines)

    def stop(self):
        self._cmdsession.abort()

    def _runCommand(self, action, cmdlines):
        self.currentAction = action
        self.progress.emit(*cmdui.startProgress(_topicmap[action], ''))
        self.commitButtonEnable.emit(False)
        ucmdlines = [map(hglib.tounicode, xs) for xs in cmdlines]
        self._cmdsession = sess = self._repoagent.runCommandSequence(ucmdlines,
                                                                     self)
        sess.commandFinished.connect(self.commandFinished)

    def commandFinished(self, ret):
        self.progress.emit(*cmdui.stopProgress(_topicmap[self.currentAction]))
        self.stopAction.setEnabled(False)
        self.commitButtonEnable.emit(True)
        if ret == 0:
            self.stwidget.partials = {}
            if self.currentAction == 'rollback':
                shlib.shell_notify([self.repo.root])
                return
            self.branchop = None
            umsg = self.msgte.text()
            if self.currentAction not in ('qref', 'amend'):
                self.lastCommitMsgs['commit'] = ('', False)
                if self.currentAction == 'commit':
                    # capture last message for BugTraq plugin
                    self.lastmessage = self.getMessage(True)
                if umsg:
                    self.addMessageToHistory(umsg)
                self.setMessage('')
                if self.currentAction == 'commit':
                    shlib.shell_notify(self.files)
                    self.commitComplete.emit()
        elif ret == 1 and self.currentAction in ('amend', 'commit'):
            qtlib.WarningMsgBox(_('Nothing Committed'),
                                _('Nothing changed.'),
                                parent=self)
        else:
            cmdui.errorMessageBox(self._cmdsession, self,
                                  _('Commit', 'window title'))

class DetailsDialog(QDialog):
    'Utility dialog for configuring uncommon settings'
    def __init__(self, repoagent, opts, userhistory, parent, mode='commit'):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('%s - commit options') % repoagent.displayName())
        self._repoagent = repoagent

        layout = QVBoxLayout()
        self.setLayout(layout)

        hbox = QHBoxLayout()
        self.usercb = QCheckBox(_('Set username:'))

        usercombo = QComboBox()
        usercombo.setEditable(True)
        usercombo.setEnabled(False)
        SP = QSizePolicy
        usercombo.setSizePolicy(SP(SP.Expanding, SP.Minimum))
        self.usercb.toggled.connect(usercombo.setEnabled)
        self.usercb.toggled.connect(lambda s: s and usercombo.setFocus())

        l = []
        if opts.get('user'):
            val = hglib.tounicode(opts['user'])
            self.usercb.setChecked(True)
            l.append(val)
        try:
            val = hglib.tounicode(self.repo.ui.username())
            l.append(val)
        except util.Abort:
            pass
        for name in userhistory:
            if name not in l:
                l.append(name)
        for name in l:
            usercombo.addItem(name)
        self.usercombo = usercombo

        usersaverepo = QPushButton(_('Save in Repo'))
        usersaverepo.clicked.connect(self.saveInRepo)
        usersaverepo.setEnabled(False)
        self.usercb.toggled.connect(usersaverepo.setEnabled)

        usersaveglobal = QPushButton(_('Save Global'))
        usersaveglobal.clicked.connect(self.saveGlobal)
        usersaveglobal.setEnabled(False)
        self.usercb.toggled.connect(usersaveglobal.setEnabled)

        hbox.addWidget(self.usercb)
        hbox.addWidget(self.usercombo)
        hbox.addWidget(usersaverepo)
        hbox.addWidget(usersaveglobal)
        layout.addLayout(hbox)

        hbox = QHBoxLayout()
        self.datecb = QCheckBox(_('Set Date:'))
        self.datele = QLineEdit()
        self.datele.setEnabled(False)
        self.datecb.toggled.connect(self.datele.setEnabled)
        curdate = QPushButton(_('Update'))
        curdate.setEnabled(False)
        self.datecb.toggled.connect(curdate.setEnabled)
        self.datecb.toggled.connect(lambda s: s and curdate.setFocus())
        curdate.clicked.connect( lambda: self.datele.setText(
                hglib.tounicode(hglib.displaytime(util.makedate()))))
        if opts.get('date'):
            self.datele.setText(opts['date'])
            self.datecb.setChecked(True)
        else:
            self.datecb.setChecked(False)
            curdate.clicked.emit(True)

        hbox.addWidget(self.datecb)
        hbox.addWidget(self.datele)
        hbox.addWidget(curdate)
        layout.addLayout(hbox)

        hbox = QHBoxLayout()
        self.pushaftercb = QCheckBox(_('Push After Commit:'))
        self.pushafterle = QLineEdit()
        self.pushafterle.setEnabled(False)
        self.pushaftercb.toggled.connect(self.pushafterle.setEnabled)
        self.pushaftercb.toggled.connect(lambda s:
                s and self.pushafterle.setFocus())

        pushaftersave = QPushButton(_('Save in Repo'))
        pushaftersave.clicked.connect(self.savePushAfter)
        pushaftersave.setEnabled(False)
        self.pushaftercb.toggled.connect(pushaftersave.setEnabled)

        if opts.get('pushafter'):
            val = hglib.tounicode(opts['pushafter'])
            self.pushafterle.setText(val)
            self.pushaftercb.setChecked(True)

        hbox.addWidget(self.pushaftercb)
        hbox.addWidget(self.pushafterle)
        hbox.addWidget(pushaftersave)
        layout.addLayout(hbox)

        hbox = QHBoxLayout()
        self.autoinccb = QCheckBox(_('Auto Includes:'))
        self.autoincle = QLineEdit()
        self.autoincle.setEnabled(False)
        self.autoinccb.toggled.connect(self.autoincle.setEnabled)
        self.autoinccb.toggled.connect(lambda s:
                s and self.autoincle.setFocus())

        autoincsave = QPushButton(_('Save in Repo'))
        autoincsave.clicked.connect(self.saveAutoInc)
        autoincsave.setEnabled(False)
        self.autoinccb.toggled.connect(autoincsave.setEnabled)

        if opts.get('autoinc'):
            val = hglib.tounicode(opts['autoinc'])
            self.autoincle.setText(val)
            self.autoinccb.setChecked(True)

        hbox.addWidget(self.autoinccb)
        hbox.addWidget(self.autoincle)
        hbox.addWidget(autoincsave)
        if mode != 'merge':
            #self.autoinccb.setVisible(False)
            layout.addLayout(hbox)

        hbox = QHBoxLayout()
        recursesave = QPushButton(_('Save in Repo'))
        recursesave.clicked.connect(self.saveRecurseInSubrepos)
        self.recursecb = QCheckBox(_('Recurse into subrepositories '
                                     '(--subrepos)'))
        SP = QSizePolicy
        self.recursecb.setSizePolicy(SP(SP.Expanding, SP.Minimum))
        #self.recursecb.toggled.connect(recursesave.setEnabled)

        if opts.get('recurseinsubrepos'):
            self.recursecb.setChecked(True)

        hbox.addWidget(self.recursecb)
        hbox.addWidget(recursesave)
        layout.addLayout(hbox)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.bb = bb
        layout.addWidget(bb)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def saveInRepo(self):
        fn = os.path.join(self.repo.root, '.hg', 'hgrc')
        self.saveToPath([fn])

    def saveGlobal(self):
        self.saveToPath(scmutil.userrcpath())

    def saveToPath(self, path):
        fn, cfg = hgrcutil.loadIniFile(path, self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save username'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            user = hglib.fromunicode(self.usercombo.currentText())
            if user:
                cfg.set('ui', 'username', user)
            else:
                try:
                    del cfg['ui']['username']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def savePushAfter(self):
        path = os.path.join(self.repo.root, '.hg', 'hgrc')
        fn, cfg = hgrcutil.loadIniFile([path], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save after commit push'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            remote = hglib.fromunicode(self.pushafterle.text())
            if remote:
                cfg.set('tortoisehg', 'cipushafter', remote)
            else:
                try:
                    del cfg['tortoisehg']['cipushafter']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def saveAutoInc(self):
        path = os.path.join(self.repo.root, '.hg', 'hgrc')
        fn, cfg = hgrcutil.loadIniFile([path], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save auto include list'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            list = hglib.fromunicode(self.autoincle.text())
            if list:
                cfg.set('tortoisehg', 'autoinc', list)
            else:
                try:
                    del cfg['tortoisehg']['autoinc']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def saveRecurseInSubrepos(self):
        path = os.path.join(self.repo.root, '.hg', 'hgrc')
        fn, cfg = hgrcutil.loadIniFile([path], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save recurse in subrepos.'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            state = self.recursecb.isChecked()
            if state:
                cfg.set('tortoisehg', 'recurseinsubrepos', state)
            else:
                try:
                    del cfg['tortoisehg']['recurseinsubrepos']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def accept(self):
        outopts = {}
        if self.datecb.isChecked():
            date = hglib.fromunicode(self.datele.text())
            try:
                util.parsedate(date)
            except error.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                qtlib.WarningMsgBox(_('Invalid date format'), err, parent=self)
                return
            outopts['date'] = date
        else:
            outopts['date'] = ''

        if self.usercb.isChecked():
            user = hglib.fromunicode(self.usercombo.currentText())
        else:
            user = ''
        outopts['user'] = user
        if not user:
            try:
                self.repo.ui.username()
            except util.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                qtlib.WarningMsgBox(_('No username configured'),
                                    err, parent=self)
                return

        if self.pushaftercb.isChecked():
            remote = hglib.fromunicode(self.pushafterle.text())
            outopts['pushafter'] = remote
        else:
            outopts['pushafter'] = ''

        if self.autoinccb.isChecked():
            outopts['autoinc'] = hglib.fromunicode(self.autoincle.text())
        else:
            outopts['autoinc'] = ''

        if self.recursecb.isChecked():
            outopts['recurseinsubrepos'] = 'true'
        else:
            outopts['recurseinsubrepos'] = ''

        self.outopts = outopts
        QDialog.accept(self)


class CommitDialog(QDialog):
    'Standalone commit tool, a wrapper for CommitWidget'

    def __init__(self, repoagent, pats, opts, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowIcon(qtlib.geticon('hg-commit'))
        self._repoagent = repoagent
        self.pats = pats
        self.opts = opts

        layout = QVBoxLayout()
        layout.setMargin(0)
        self.setLayout(layout)

        toplayout = QVBoxLayout()
        toplayout.setContentsMargins(5, 5, 5, 0)
        layout.addLayout(toplayout)

        commit = CommitWidget(repoagent, pats, opts, self, rev='.')
        toplayout.addWidget(commit, 1)

        self.statusbar = cmdui.ThgStatusBar(self)
        commit.showMessage.connect(self.statusbar.showMessage)
        commit.progress.connect(self.statusbar.progress)
        commit.linkActivated.connect(self.linkActivated)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Close|BB.Discard)
        bb.rejected.connect(self.reject)
        bb.button(BB.Discard).setText('Undo')
        bb.button(BB.Discard).clicked.connect(commit.rollback)
        bb.button(BB.Close).setDefault(False)
        bb.button(BB.Discard).setDefault(False)
        self.commitButton = commit.commitSetupButton()
        bb.addButton(self.commitButton, BB.AcceptRole)

        self.bb = bb

        toplayout.addWidget(self.bb)
        layout.addWidget(self.statusbar)

        self._subdialogs = qtlib.DialogKeeper(CommitDialog._createSubDialog,
                                              parent=self)

        s = QSettings()
        self.restoreGeometry(s.value('commit/geom').toByteArray())
        commit.loadSettings(s, 'committool')
        repoagent.repositoryChanged.connect(self.updateUndo)
        commit.commitComplete.connect(self.postcommit)

        self.setWindowTitle(_('%s - commit') % repoagent.displayName())
        self.commit = commit
        self.commit.reload()
        self.updateUndo()
        self.commit.msgte.setFocus()
        qtlib.newshortcutsforstdkey(QKeySequence.Refresh, self, self.refresh)

    def linkActivated(self, link):
        link = unicode(link)
        if link.startswith('repo:'):
            self._subdialogs.open(link[len('repo:'):])

    def _createSubDialog(self, uroot):
        repoagent = self._repoagent.subRepoAgent(uroot)
        return CommitDialog(repoagent, [], {}, parent=self)

    @pyqtSlot()
    def updateUndo(self):
        BB = QDialogButtonBox
        undomsg = self.commit.canUndo()
        if undomsg:
            self.bb.button(BB.Discard).setEnabled(True)
            self.bb.button(BB.Discard).setToolTip(undomsg)
        else:
            self.bb.button(BB.Discard).setEnabled(False)
            self.bb.button(BB.Discard).setToolTip('')

    def refresh(self):
        self.updateUndo()
        self.commit.reload()

    def postcommit(self):
        repo = self.commit.stwidget.repo
        if repo.ui.configbool('tortoisehg', 'closeci'):
            if self.commit.canExit():
                self.reject()
            else:
                self.commit.stwidget.refthread.wait()
                QTimer.singleShot(0, self.reject)

    def promptExit(self):
        exit = self.commit.canExit()
        if not exit:
            exit = qtlib.QuestionMsgBox(_('TortoiseHg Commit'),
                _('Are you sure that you want to cancel the commit operation?'),
                parent=self)
        if exit:
            s = QSettings()
            s.setValue('commit/geom', self.saveGeometry())
            self.commit.saveSettings(s, 'committool')
        return exit

    def accept(self):
        self.commit.commit()

    def reject(self):
        if self.promptExit():
            QDialog.reject(self)
