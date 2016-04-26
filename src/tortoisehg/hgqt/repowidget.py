# repowidget.py - TortoiseHg repository widget
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright (C) 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

import binascii
import os
import shlex, subprocess  # used by runCustomCommand
import cStringIO
from mercurial import error, patch, phases, util, ui

from tortoisehg.util import hglib, shlib, paths
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import infobar, qtlib, repomodel
from tortoisehg.hgqt.qtlib import QuestionMsgBox, InfoMsgBox, WarningMsgBox
from tortoisehg.hgqt.qtlib import DemandWidget
from tortoisehg.hgqt import cmdcore, cmdui, update, tag, backout, merge, visdiff
from tortoisehg.hgqt import archive, thgimport, thgstrip, purge, bookmark
from tortoisehg.hgqt import bisect, rebase, resolve, compress, mq
from tortoisehg.hgqt import prune, settings, shelve
from tortoisehg.hgqt import matching, graft, hgemail, postreview, revdetails
from tortoisehg.hgqt import sign

from tortoisehg.hgqt.repofilter import RepoFilterBar
from tortoisehg.hgqt.repoview import HgRepoView
from tortoisehg.hgqt.commit import CommitWidget
from tortoisehg.hgqt.sync import SyncWidget
from tortoisehg.hgqt.grep import SearchWidget
from tortoisehg.hgqt.pbranch import PatchBranchWidget
from tortoisehg.hgqt.docklog import ConsoleWidget

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class RepoWidget(QWidget):

    currentTaskTabChanged = pyqtSignal()
    showMessageSignal = pyqtSignal(str)
    toolbarVisibilityChanged = pyqtSignal(bool)

    # TODO: progress can be removed if all actions are run as hg command
    progress = pyqtSignal(str, object, str, str, object)
    makeLogVisible = pyqtSignal(bool)

    revisionSelected = pyqtSignal(object)

    titleChanged = pyqtSignal(str)
    """Emitted when changed the expected title for the RepoWidget tab"""

    busyIconChanged = pyqtSignal()

    repoLinkClicked = pyqtSignal(str)
    """Emitted when clicked a link to open repository"""

    def __init__(self, repoagent, parent=None, bundle=None):
        QWidget.__init__(self, parent, acceptDrops=True)

        self._repoagent = repoagent
        self.bundlesource = None  # source URL of incoming bundle [unicode]
        self.outgoingMode = False
        self._busyIconNames = []
        self._namedTabs = {}
        self.destroyed.connect(self.repo.thginvalidate)

        self.currentMessage = ''

        self.setupUi()
        self.createActions()
        self.loadSettings()
        self._initModel()

        if bundle:
            self.setBundle(bundle)

        self._dialogs = qtlib.DialogKeeper(
            lambda self, dlgmeth, *args: dlgmeth(self, *args), parent=self)

        # listen to change notification after initial settings are loaded
        repoagent.repositoryChanged.connect(self.repositoryChanged)
        repoagent.configChanged.connect(self.configChanged)

        QTimer.singleShot(0, self._initView)

    def setupUi(self):
        self.repotabs_splitter = QSplitter(orientation=Qt.Vertical)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(0)

        # placeholder to shift repoview while infobar is overlaid
        self._repoviewFrame = infobar.InfoBarPlaceholder(self._repoagent, self)
        self._repoviewFrame.linkActivated.connect(self._openLink)

        self.filterbar = RepoFilterBar(self._repoagent, self)
        self.layout().addWidget(self.filterbar)

        self.filterbar.branchChanged.connect(self.setBranch)
        self.filterbar.showHiddenChanged.connect(self.setShowHidden)
        self.filterbar.showGraftSourceChanged.connect(self.setShowGraftSource)
        self.filterbar.setRevisionSet.connect(self.setRevisionSet)
        self.filterbar.filterToggled.connect(self.filterToggled)
        self.filterbar.visibilityChanged.connect(self.toolbarVisibilityChanged)
        self.filterbar.hide()

        self.layout().addWidget(self.repotabs_splitter)

        cs = ('workbench', _('Workbench Log Columns'))
        self.repoview = view = HgRepoView(self._repoagent, 'repoWidget', cs,
                                          self)
        view.clicked.connect(self._clearInfoMessage)
        view.revisionSelected.connect(self.onRevisionSelected)
        view.revisionActivated.connect(self.onRevisionActivated)
        view.showMessage.connect(self.showMessage)
        view.menuRequested.connect(self.viewMenuRequest)
        self._repoviewFrame.setView(view)

        self.repotabs_splitter.addWidget(self._repoviewFrame)
        self.repotabs_splitter.setCollapsible(0, True)
        self.repotabs_splitter.setStretchFactor(0, 1)

        self.taskTabsWidget = tt = QTabWidget()
        self.repotabs_splitter.addWidget(self.taskTabsWidget)
        self.repotabs_splitter.setStretchFactor(1, 1)
        tt.setDocumentMode(True)
        self.updateTaskTabs()
        tt.currentChanged.connect(self.currentTaskTabChanged)

        w = revdetails.RevDetailsWidget(self._repoagent, self)
        self.revDetailsWidget = w
        self.revDetailsWidget.filelisttbar.setStyleSheet(qtlib.tbstylesheet)
        w.linkActivated.connect(self._openLink)
        w.revisionSelected.connect(self.repoview.goto)
        w.grepRequested.connect(self.grep)
        w.showMessage.connect(self.showMessage)
        w.revsetFilterRequested.connect(self.setFilter)
        w.runCustomCommandRequested.connect(
            self.handleRunCustomCommandRequest)
        idx = tt.addTab(w, qtlib.geticon('hg-log'), '')
        self._namedTabs['log'] = idx
        tt.setTabToolTip(idx, _("Revision details", "tab tooltip"))

        self.commitDemand = w = DemandWidget('createCommitWidget', self)
        idx = tt.addTab(w, qtlib.geticon('hg-commit'), '')
        self._namedTabs['commit'] = idx
        tt.setTabToolTip(idx, _("Commit", "tab tooltip"))

        self.grepDemand = w = DemandWidget('createGrepWidget', self)
        idx = tt.addTab(w, qtlib.geticon('hg-grep'), '')
        self._namedTabs['grep'] = idx
        tt.setTabToolTip(idx, _("Search", "tab tooltip"))

        w = ConsoleWidget(self._repoagent, self)
        self.consoleWidget = w
        w.closeRequested.connect(self.switchToPreferredTaskTab)
        idx = tt.addTab(w, qtlib.geticon('thg-console'), '')
        self._namedTabs['console'] = idx
        tt.setTabToolTip(idx, _("Console log", "tab tooltip"))

        self.syncDemand = w = DemandWidget('createSyncWidget', self)
        idx = tt.addTab(w, qtlib.geticon('thg-sync'), '')
        self._namedTabs['sync'] = idx
        tt.setTabToolTip(idx, _("Synchronize", "tab tooltip"))

        if 'pbranch' in self.repo.extensions():
            self.pbranchDemand = w = DemandWidget('createPatchBranchWidget', self)
            idx = tt.addTab(w, qtlib.geticon('hg-branch'), '')
            tt.setTabToolTip(idx, _("Patch Branch", "tab tooltip"))
            self._namedTabs['pbranch'] = idx

    @pyqtSlot()
    def _initView(self):
        self._updateRepoViewForModel()
        # restore column widths when model is initially loaded.  For some
        # reason, this needs to be deferred after updating the view.  Otherwise
        # repoview.HgRepoView.resizeEvent() fires as the vertical scrollbar is
        # added, which causes the last column to grow by the scrollbar width on
        # each restart (and steal from the description width).
        QTimer.singleShot(0, self.repoview.resizeColumns)

        # select the widget chosen by the user
        name = self.repo.ui.config('tortoisehg', 'defaultwidget')
        if name:
            name = {'revdetails': 'log', 'search': 'grep'}.get(name, name)
            self.taskTabsWidget.setCurrentIndex(self._namedTabs.get(name, 0))

    def currentTaskTabName(self):
        indexmap = dict((idx, name)
                        for name, idx in self._namedTabs.iteritems())
        return indexmap.get(self.taskTabsWidget.currentIndex())

    @pyqtSlot(str)
    def switchToNamedTaskTab(self, tabname):
        tabname = str(tabname)
        if tabname in self._namedTabs:
            idx = self._namedTabs[tabname]
            # refresh status even if current widget is already a 'commit'
            if (tabname == 'commit'
                and self.taskTabsWidget.currentIndex() == idx):
                self._refreshCommitTabIfNeeded()
            self.taskTabsWidget.setCurrentIndex(idx)

            # restore default splitter position if task tab is invisible
            if self.repotabs_splitter.sizes()[1] == 0:
                self.repotabs_splitter.setSizes([1, 1])

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def repoRootPath(self):
        return self._repoagent.rootPath()

    def repoDisplayName(self):
        return self._repoagent.displayName()

    def title(self):
        """Returns the expected title for this widget [unicode]"""
        name = self._repoagent.shortName()
        if self._repoagent.overlayUrl():
            return _('%s <incoming>') % name
        elif self.repomodel.branch():
            return u'%s [%s]' % (name, self.repomodel.branch())
        else:
            return name

    def busyIcon(self):
        if self._busyIconNames:
            return qtlib.geticon(self._busyIconNames[-1])
        else:
            return QIcon()

    def filterBar(self):
        return self.filterbar

    def filterBarVisible(self):
        return self.filterbar.isVisible()

    @pyqtSlot(bool)
    def toggleFilterBar(self, checked):
        """Toggle display repowidget filter bar"""
        if self.filterbar.isVisibleTo(self) == checked:
            return
        self.filterbar.setVisible(checked)
        if checked:
            self.filterbar.setFocus()

    def _openRepoLink(self, upath):
        path = hglib.fromunicode(upath)
        if not os.path.isabs(path):
            path = self.repo.wjoin(path)
        self.repoLinkClicked.emit(hglib.tounicode(path))

    @pyqtSlot(str)
    def _openLink(self, link):
        link = unicode(link)
        handlers = {'cset': self.goto,
                    'log': lambda a: self.makeLogVisible.emit(True),
                    'repo': self._openRepoLink,
                    'shelve' : self.shelve}
        if ':' in link:
            scheme, param = link.split(':', 1)
            hdr = handlers.get(scheme)
            if hdr:
                return hdr(param)
        if os.path.isabs(link):
            qtlib.openlocalurl(link)
        else:
            QDesktopServices.openUrl(QUrl(link))

    def setInfoBar(self, cls, *args, **kwargs):
        return self._repoviewFrame.setInfoBar(cls, *args, **kwargs)

    def clearInfoBar(self, priority=None):
        return self._repoviewFrame.clearInfoBar(priority)

    def createCommitWidget(self):
        pats, opts = {}, {}
        cw = CommitWidget(self._repoagent, pats, opts, self, rev=self.rev)
        cw.buttonHBox.addWidget(cw.commitSetupButton())
        cw.loadSettings(QSettings(), 'workbench')

        cw.progress.connect(self.progress)
        cw.linkActivated.connect(self._openLink)
        cw.showMessage.connect(self.showMessage)
        cw.grepRequested.connect(self.grep)
        cw.runCustomCommandRequested.connect(
            self.handleRunCustomCommandRequest)
        QTimer.singleShot(0, self._initCommitWidgetLate)
        return cw

    @pyqtSlot()
    def _initCommitWidgetLate(self):
        cw = self.commitDemand.get()
        cw.reload()
        # auto-refresh should be enabled after initial reload(); otherwise
        # refreshWctx() can be doubled
        self.taskTabsWidget.currentChanged.connect(
            self._refreshCommitTabIfNeeded)

    def createSyncWidget(self):
        sw = SyncWidget(self._repoagent, self)
        sw.newCommand.connect(self._handleNewSyncCommand)
        sw.outgoingNodes.connect(self.setOutgoingNodes)
        sw.showMessage.connect(self.showMessage)
        sw.showMessage.connect(self._repoviewFrame.showMessage)
        sw.incomingBundle.connect(self.setBundle)
        sw.pullCompleted.connect(self.onPullCompleted)
        sw.pushCompleted.connect(self.clearRevisionSet)
        sw.refreshTargets(self.rev)
        sw.switchToRequest.connect(self.switchToNamedTaskTab)
        return sw

    @pyqtSlot(cmdcore.CmdSession)
    def _handleNewSyncCommand(self, sess):
        self._handleNewCommand(sess)
        if sess.isFinished():
            return
        sess.commandFinished.connect(self._onSyncCommandFinished)
        self._setBusyIcon('thg-sync')

    @pyqtSlot()
    def _onSyncCommandFinished(self):
        self._clearBusyIcon('thg-sync')

    def _setBusyIcon(self, iconname):
        self._busyIconNames.append(iconname)
        self.busyIconChanged.emit()

    def _clearBusyIcon(self, iconname):
        if iconname in self._busyIconNames:
            self._busyIconNames.remove(iconname)
        self.busyIconChanged.emit()

    @pyqtSlot(str)
    def setFilter(self, filter):
        self.filterbar.setQuery(filter)
        self.filterbar.setVisible(True)
        self.filterbar.runQuery()

    @pyqtSlot(str, str)
    def setBundle(self, bfile, bsource=None):
        if self._repoagent.overlayUrl():
            self.clearBundle()
        self.bundlesource = bsource and unicode(bsource) or None
        oldlen = len(self.repo)
        # no "bundle:<bfile>" because bfile may contain "+" separator
        self._repoagent.setOverlay(bfile)
        self.filterbar.setQuery('bundle()')
        self.filterbar.runQuery()
        self.titleChanged.emit(self.title())
        newlen = len(self.repo)

        w = self.setInfoBar(infobar.ConfirmInfoBar,
            _('Found %d incoming changesets') % (newlen - oldlen))
        assert w
        w.acceptButton.setText(_('Pull'))
        w.acceptButton.setToolTip(_('Pull incoming changesets into '
                                    'your repository'))
        w.rejectButton.setText(_('Cancel'))
        w.rejectButton.setToolTip(_('Reject incoming changesets'))
        w.accepted.connect(self.acceptBundle)
        w.rejected.connect(self.clearBundle)

    @pyqtSlot()
    def clearBundle(self):
        self.clearRevisionSet()
        self.bundlesource = None
        self._repoagent.clearOverlay()
        self.titleChanged.emit(self.title())

    @pyqtSlot()
    def onPullCompleted(self):
        if self._repoagent.overlayUrl():
            self.clearBundle()

    @pyqtSlot()
    def acceptBundle(self):
        bundle = self._repoagent.overlayUrl()
        if bundle:
            w = self.syncDemand.get()
            w.pullBundle(bundle, None, self.bundlesource)

    @pyqtSlot()
    def pullBundleToRev(self):
        bundle = self._repoagent.overlayUrl()
        if bundle:
            # manually remove infobar to work around unwanted clearBundle
            # during pull operation (issue #2596)
            self._repoviewFrame.discardInfoBar()

            w = self.syncDemand.get()
            w.pullBundle(bundle, self.repo[self.rev].hex(), self.bundlesource)

    @pyqtSlot()
    def clearRevisionSet(self):
        self.filterbar.setQuery('')
        self.setRevisionSet('')

    def setRevisionSet(self, revspec):
        self.repomodel.setRevset(revspec)
        if not revspec:
            self.outgoingMode = False

    @pyqtSlot(bool)
    def filterToggled(self, checked):
        self.repomodel.setFilterByRevset(checked)

    def setOutgoingNodes(self, nodes):
        self.filterbar.setQuery('outgoing()')
        revs = [self.repo[n].rev() for n in nodes]
        self.setRevisionSet(hglib.compactrevs(revs))
        self.outgoingMode = True
        numnodes = len(nodes)
        numoutgoing = numnodes

        if self.syncDemand.get().isTargetSelected():
            # Outgoing preview is already filtered by target selection
            defaultpush = None
        else:
            # Read the tortoisehg.defaultpush setting to determine what to push
            # by default, and set the button label and action accordingly
            defaultpush = self.repo.ui.config('tortoisehg', 'defaultpush',
                                              'all')
        rev = None
        branch = None
        pushall = False
        # note that we assume that none of the revisions
        # on the nodes/revs lists is secret
        if defaultpush == 'branch':
            branch = self.repo['.'].branch()
            ubranch = hglib.tounicode(branch)
            # Get the list of revs that will be actually pushed
            outgoingrevs = self.repo.revs('%ld and branch(.)', revs)
            numoutgoing = len(outgoingrevs)
        elif defaultpush == 'revision':
            rev = self.repo['.'].rev()
            # Get the list of revs that will be actually pushed
            # excluding (potentially) the current rev
            outgoingrevs = self.repo.revs('%ld and ::.', revs)
            numoutgoing = len(outgoingrevs)
            maxrev = rev
            if numoutgoing > 0:
                maxrev = max(outgoingrevs)
        else:
            pushall = True

        # Set the default acceptbuttontext
        # Note that the pushall case uses the default accept button text
        if branch is not None:
            acceptbuttontext = _('Push current branch (%s)') % ubranch
        elif rev is not None:
            if maxrev == rev:
                acceptbuttontext = _('Push up to current revision (#%d)') % rev
            else:
                acceptbuttontext = _('Push up to revision #%d') % maxrev
        else:
            acceptbuttontext = _('Push all')

        if numnodes == 0:
            msg = _('no outgoing changesets')
        elif numoutgoing == 0:
            if branch:
                msg = _('no outgoing changesets in current branch (%s) '
                    '/ %d in total') % (ubranch, numnodes)
            elif rev is not None:
                if maxrev == rev:
                    msg = _('no outgoing changesets up to current revision '
                            '(#%d) / %d in total') % (rev, numnodes)
                else:
                    msg = _('no outgoing changesets up to revision #%d '
                            '/ %d in total') % (maxrev, numnodes)
        elif numoutgoing == numnodes:
            # This case includes 'Push all' among others
            msg = _('%d outgoing changesets') % numoutgoing
        elif branch:
            msg = _('%d outgoing changesets in current branch (%s) '
                    '/ %d in total') % (numoutgoing, ubranch, numnodes)
        elif rev:
            if maxrev == rev:
                msg = _('%d outgoing changesets up to current revision (#%d) '
                        '/ %d in total') % (numoutgoing, rev, numnodes)
            else:
                msg = _('%d outgoing changesets up to revision #%d '
                        '/ %d in total') % (numoutgoing, maxrev, numnodes)
        else:
            # This should never happen but we leave this else clause
            # in case there is a flaw in the logic above (e.g. due to
            # a future change in the code)
            msg = _('%d outgoing changesets') % numoutgoing

        w = self.setInfoBar(infobar.ConfirmInfoBar, msg.strip())
        assert w

        if numoutgoing == 0:
            acceptbuttontext = _('Nothing to push')
            w.acceptButton.setEnabled(False)
        w.acceptButton.setText(acceptbuttontext)
        w.accepted.connect(lambda: self.push(False,
            rev=rev, branch=branch, pushall=pushall))  # TODO: to the same URL
        w.rejected.connect(self.clearRevisionSet)

    def createGrepWidget(self):
        upats = {}
        gw = SearchWidget(self._repoagent, upats, self)
        gw.setRevision(self.repoview.current_rev)
        gw.showMessage.connect(self.showMessage)
        gw.progress.connect(self.progress)
        gw.revisionSelected.connect(self.goto)
        return gw

    def createPatchBranchWidget(self):
        pbw = PatchBranchWidget(self._repoagent, parent=self)
        return pbw

    @property
    def rev(self):
        """Returns the current active revision"""
        return self.repoview.current_rev

    def showMessage(self, msg):
        self.currentMessage = msg
        if self.isVisible():
            self.showMessageSignal.emit(msg)

    def keyPressEvent(self, event):
        if self._repoviewFrame.activeInfoBar() and event.key() == Qt.Key_Escape:
            self.clearInfoBar(infobar.INFO)
        else:
            QWidget.keyPressEvent(self, event)

    def showEvent(self, event):
        QWidget.showEvent(self, event)
        self.showMessageSignal.emit(self.currentMessage)
        if not event.spontaneous():
            # RepoWidget must be the main widget in any window, so grab focus
            # when it gets visible at start-up or by switching tabs.
            self.repoview.setFocus()

    def createActions(self):
        self._mqActions = None
        if 'mq' in self.repo.extensions():
            self._mqActions = mq.PatchQueueActions(self)
            self._mqActions.setRepoAgent(self._repoagent)
            self.generateUnappliedPatchMenu()

        self.generateSingleMenu()
        self.generatePairMenu()
        self.generateMultipleSelectionMenu()
        self.generateBundleMenu()
        self.generateOutgoingMenu()

    def detectPatches(self, paths):
        filepaths = []
        for p in paths:
            if not os.path.isfile(p):
                continue
            try:
                pf = open(p, 'rb')
                earlybytes = pf.read(4096)
                if '\0' in earlybytes:
                    continue
                pf.seek(0)
                data = patch.extract(self.repo.ui, pf)
                filename = data.get('filename')
                if filename:
                    filepaths.append(p)
                    os.unlink(filename)
            except EnvironmentError:
                pass
        return filepaths

    def dragEnterEvent(self, event):
        paths = [unicode(u.toLocalFile()) for u in event.mimeData().urls()]
        if self.detectPatches(paths):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event):
        paths = [unicode(u.toLocalFile()) for u in event.mimeData().urls()]
        patches = self.detectPatches(paths)
        if not patches:
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.thgimport(patches)

    ## Begin Workbench event forwards

    def back(self):
        self.repoview.back()

    def forward(self):
        self.repoview.forward()

    def bisect(self):
        self._dialogs.open(RepoWidget._createBisectDialog)

    def _createBisectDialog(self):
        dlg = bisect.BisectDialog(self._repoagent, self)
        dlg.newCandidate.connect(self.gotoParent)
        return dlg

    def resolve(self):
        dlg = resolve.ResolveDialog(self._repoagent, self)
        dlg.exec_()

    def thgimport(self, paths=None):
        dlg = thgimport.ImportDialog(self._repoagent, self)
        if paths:
            dlg.setfilepaths(paths)
        if dlg.exec_() == 0:
            self.gotoTip()

    def unbundle(self):
         w = self.syncDemand.get()
         w.unbundle()

    def shelve(self, arg=None):
        self._dialogs.open(RepoWidget._createShelveDialog)

    def _createShelveDialog(self):
        dlg = shelve.ShelveDialog(self._repoagent)
        dlg.finished.connect(self._refreshCommitTabIfNeeded)
        return dlg

    def verify(self):
        cmdline = ['verify', '--verbose']
        dlg = cmdui.CmdSessionDialog(self)
        dlg.setWindowIcon(qtlib.geticon('hg-verify'))
        dlg.setWindowTitle(_('%s - verify repository') % self.repoDisplayName())
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint)
        dlg.setSession(self._repoagent.runCommand(cmdline, self))
        dlg.exec_()

    def recover(self):
        cmdline = ['recover', '--verbose']
        dlg = cmdui.CmdSessionDialog(self)
        dlg.setWindowIcon(qtlib.geticon('hg-recover'))
        dlg.setWindowTitle(_('%s - recover repository')
                           % self.repoDisplayName())
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint)
        dlg.setSession(self._repoagent.runCommand(cmdline, self))
        dlg.exec_()

    def rollback(self):
        desc, oldlen = hglib.readundodesc(self.repo)
        if not desc:
            InfoMsgBox(_('No transaction available'),
                       _('There is no rollback transaction available'))
            return
        elif desc == 'commit':
            if not QuestionMsgBox(_('Undo last commit?'),
                   _('Undo most recent commit (%d), preserving file changes?') %
                   oldlen):
                return
        else:
            if not QuestionMsgBox(_('Undo last transaction?'),
                    _('Rollback to revision %d (undo %s)?') %
                    (oldlen - 1, desc)):
                return
            try:
                rev = self.repo['.'].rev()
            except error.LookupError, e:
                InfoMsgBox(_('Repository Error'),
                           _('Unable to determine working copy revision\n') +
                           hglib.tounicode(e))
                return
            if rev >= oldlen and not QuestionMsgBox(
                    _('Remove current working revision?'),
                    _('Your current working revision (%d) will be removed '
                      'by this rollback, leaving uncommitted changes.\n '
                      'Continue?') % rev):
                return
        cmdline = ['rollback', '--verbose']
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._notifyWorkingDirChanges)

    def purge(self):
        dlg = purge.PurgeDialog(self._repoagent, self)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.showMessage.connect(self.showMessage)
        dlg.progress.connect(self.progress)
        dlg.exec_()
        # ignores result code of PurgeDialog because it's unreliable
        self._refreshCommitTabIfNeeded()

    ## End workbench event forwards

    @pyqtSlot(str, dict)
    def grep(self, pattern='', opts={}):
        """Open grep task tab"""
        opts = dict((str(k), str(v)) for k, v in opts.iteritems())
        self.taskTabsWidget.setCurrentIndex(self._namedTabs['grep'])
        self.grepDemand.setSearch(pattern, **opts)
        self.grepDemand.runSearch()

    def _initModel(self):
        self.repomodel = repomodel.HgRepoListModel(self._repoagent, self)
        self.repomodel.setBranch(self.filterbar.branch(),
                                 self.filterbar.branchAncestorsIncluded())
        self.repomodel.setFilterByRevset(self.filterbar.filtercb.isChecked())
        self.repomodel.setShowGraftSource(self.filterbar.getShowGraftSource())
        self.repomodel.showMessage.connect(self.showMessage)
        self.repomodel.showMessage.connect(self._repoviewFrame.showMessage)
        self.repoview.setModel(self.repomodel)
        self.repomodel.revsUpdated.connect(self._updateRepoViewForModel)

    @pyqtSlot()
    def _updateRepoViewForModel(self):
        model = self.repoview.model()
        selmodel = self.repoview.selectionModel()
        index = selmodel.currentIndex()
        if not (index.flags() & Qt.ItemIsEnabled):
            index = model.defaultIndex()
            f = QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
            selmodel.setCurrentIndex(index, f)
        self.repoview.scrollTo(index)
        self.repoview.enablefilterpalette(bool(model.revset()))
        self.clearInfoBar(infobar.INFO)  # clear progress message

    @pyqtSlot()
    def _clearInfoMessage(self):
        self.clearInfoBar(infobar.INFO)

    @pyqtSlot()
    def switchToPreferredTaskTab(self):
        tw = self.taskTabsWidget
        rev = self.rev
        ctx = self.repo.changectx(rev)
        if rev is None or ('mq' in self.repo.extensions() and 'qtip' in ctx.tags()
                           and self.repo['.'].rev() == rev):
            # Clicking on working copy or on the topmost applied patch
            # (_if_ it is also the working copy parent) switches to the commit tab
            tw.setCurrentIndex(self._namedTabs['commit'])
        else:
            # Clicking on a normal revision switches from commit tab
            tw.setCurrentIndex(self._namedTabs['log'])

    def onRevisionSelected(self, rev):
        'View selection changed, could be a reload'
        self.showMessage('')
        try:
            self.revDetailsWidget.onRevisionSelected(rev)
            self.revisionSelected.emit(rev)
            if type(rev) != str:
                # Regular patch or working directory
                self.grepDemand.forward('setRevision', rev)
                self.syncDemand.forward('refreshTargets', rev)
                self.commitDemand.forward('setRev', rev)
        except (IndexError, error.RevlogError, error.Abort), e:
            self.showMessage(hglib.tounicode(str(e)))

        cw = self.taskTabsWidget.currentWidget()
        if cw.canswitch():
            self.switchToPreferredTaskTab()

    @pyqtSlot()
    def gotoParent(self):
        self.goto('.')

    def gotoTip(self):
        self.repoview.clearSelection()
        self.goto('tip')

    def goto(self, rev):
        self.repoview.goto(rev)

    def onRevisionActivated(self, rev):
        qgoto = False
        if isinstance(rev, basestring):
            qgoto = True
        else:
            ctx = self.repo.changectx(rev)
            if 'qparent' in ctx.tags() or ctx.thgmqappliedpatch():
                qgoto = True
            if 'qtip' in ctx.tags():
                qgoto = False
        if qgoto:
            self.qgotoSelectedRevision()
        else:
            self.visualDiffRevision()

    def reload(self, invalidate=True):
        'Initiate a refresh of the repo model, rebuild graph'
        try:
            if invalidate:
                self.repo.thginvalidate()
            self.rebuildGraph()
            self.reloadTaskTab()
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))

    def rebuildGraph(self):
        'Called by repositoryChanged signals, and during reload'
        self.showMessage('')
        self.filterbar.refresh()
        self.repoview.saveSettings()

    def reloadTaskTab(self):
        w = self.taskTabsWidget.currentWidget()
        w.reload()

    @pyqtSlot()
    def repositoryChanged(self):
        'Repository has detected a changelog / dirstate change'
        try:
            self.rebuildGraph()
        except (error.RevlogError, error.RepoError), e:
            self.showMessage(hglib.tounicode(str(e)))

    @pyqtSlot()
    def configChanged(self):
        'Repository is reporting its config files have changed'
        self.revDetailsWidget.reload()
        self.titleChanged.emit(self.title())
        self.updateTaskTabs()

    def updateTaskTabs(self):
        val = self.repo.ui.config('tortoisehg', 'tasktabs', 'off').lower()
        if val == 'east':
            self.taskTabsWidget.setTabPosition(QTabWidget.East)
            self.taskTabsWidget.tabBar().show()
        elif val == 'west':
            self.taskTabsWidget.setTabPosition(QTabWidget.West)
            self.taskTabsWidget.tabBar().show()
        else:
            self.taskTabsWidget.tabBar().hide()

    @pyqtSlot(str, bool)
    def setBranch(self, branch, allparents):
        self.repomodel.setBranch(branch, allparents=allparents)
        self.titleChanged.emit(self.title())

    @pyqtSlot(bool)
    def setShowHidden(self, showhidden):
        self._repoagent.setHiddenRevsIncluded(showhidden)

    @pyqtSlot(bool)
    def setShowGraftSource(self, showgraftsource):
        self.repomodel.setShowGraftSource(showgraftsource)

    ##
    ## Workbench methods
    ##

    def canGoBack(self):
        return self.repoview.canGoBack()

    def canGoForward(self):
        return self.repoview.canGoForward()

    def loadSettings(self):
        s = QSettings()
        repoid = hglib.shortrepoid(self.repo)
        self.revDetailsWidget.loadSettings(s)
        self.filterbar.loadSettings(s)
        self._repoagent.setHiddenRevsIncluded(self.filterbar.getShowHidden())
        self.repotabs_splitter.restoreState(
            s.value('repowidget/splitter-'+repoid).toByteArray())

    def okToContinue(self):
        if self._repoagent.isBusy():
            r = QMessageBox.question(self, _('Confirm Exit'),
                                     _('Mercurial command is still running.\n'
                                       'Are you sure you want to terminate?'),
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
            if r == QMessageBox.Yes:
                self._repoagent.abortCommands()
            return False
        for i in xrange(self.taskTabsWidget.count()):
            w = self.taskTabsWidget.widget(i)
            if w.canExit():
                continue
            self.taskTabsWidget.setCurrentWidget(w)
            self.showMessage(_('Tab cannot exit'))
            return False
        return True

    def closeRepoWidget(self):
        '''returns False if close should be aborted'''
        if not self.okToContinue():
            return False
        s = QSettings()
        if self.isVisible():
            try:
                repoid = hglib.shortrepoid(self.repo)
                s.setValue('repowidget/splitter-'+repoid,
                           self.repotabs_splitter.saveState())
            except EnvironmentError:
                pass
        self.revDetailsWidget.saveSettings(s)
        self.commitDemand.forward('saveSettings', s, 'workbench')
        self.grepDemand.forward('saveSettings', s)
        self.filterbar.saveSettings(s)
        self.repoview.saveSettings(s)
        return True

    def setSyncUrl(self, url):
        """Change the current peer-repo url of the sync widget; url may be
        a symbolic name defined in [paths] section"""
        self.syncDemand.get().setUrl(url)

    def incoming(self):
        self.syncDemand.get().incoming()

    def pull(self):
        self.syncDemand.get().pull()
    def outgoing(self):
        self.syncDemand.get().outgoing()
    def push(self, confirm=None, **kwargs):
        """Call sync push.

        If confirm is False, the user will not be prompted for
        confirmation. If confirm is True, the prompt might be used.
        """
        self.syncDemand.get().push(confirm, **kwargs)
        self.outgoingMode = False

    def syncBookmark(self):
        self.syncDemand.get().syncBookmark()

    ##
    ## Repoview context menu
    ##

    def viewMenuRequest(self, point, selection):
        'User requested a context menu in repo view widget'

        # selection is a list of the currently selected revisions.
        # Integers for changelog revisions, None for the working copy,
        # or strings for unapplied patches.

        if len(selection) == 0:
            return

        self.menuselection = selection
        if self._repoagent.overlayUrl():
            if len(selection) == 1:
                self.bundlemenu.exec_(point)
            return
        if self.outgoingMode:
            if len(selection) == 1:
                self.outgoingcmenu.exec_(point)
                return

        allunapp = False
        if 'mq' in self.repo.extensions():
            for rev in selection:
                if not self.repo.changectx(rev).thgmqunappliedpatch():
                    break
            else:
                allunapp = True
        if allunapp:
            self.unappliedPatchMenu(point, selection)
        elif len(selection) == 1:
            self.singleSelectionMenu(point, selection)
        elif len(selection) == 2:
            self.doubleSelectionMenu(point, selection)
        else:
            self.multipleSelectionMenu(point, selection)

    def singleSelectionMenu(self, point, selection):
        ctx = self.repo.changectx(self.rev)
        applied = ctx.thgmqappliedpatch()
        working = self.rev is None
        tags = ctx.tags()

        for item in self.singlecmenuitems:
            enabled = item.enableFunc(applied, working, tags)
            item.setEnabled(enabled)

        self.singlecmenu.exec_(point)

    def doubleSelectionMenu(self, point, selection):
        for r in selection:
            # No pair menu if working directory or unapplied patch
            if type(r) is not int:
                return
        self.paircmenu.exec_(point)

    def multipleSelectionMenu(self, point, selection):
        for r in selection:
            # No multi menu if working directory or unapplied patch
            if type(r) is not int:
                return
        self.multicmenu.exec_(point)

    def unappliedPatchMenu(self, point, selection):
        q = self.repo.mq
        ispushable = False
        unapplied = 0
        for i in xrange(q.seriesend(), len(q.series)):
            pushable, reason = q.pushable(i)
            if pushable:
                if unapplied == 0:
                    qnext = q.series[i]
                if self.rev == q.series[i]:
                    ispushable = True
                unapplied += 1
        self.unappacts[0].setEnabled(ispushable and len(selection) == 1)
        self.unappacts[1].setEnabled(ispushable and len(selection) == 1)
        self.unappacts[2].setEnabled(ispushable and len(selection) == 1 and \
                                     self.rev != qnext)
        self.unappacts[3].setEnabled('qtip' in self.repo.tags())
        self.unappacts[4].setEnabled(True)
        self.unappacts[5].setEnabled(len(selection) == 1)
        self.unappcmenu.exec_(point)

    def generateSingleMenu(self, mode=None):
        items = []
        # This menu will never be opened for an unapplied patch, they
        # have their own menu.
        #
        # iswd = working directory
        # isrev = the changeset has an integer revision number
        # isctx = changectx or workingctx
        # fixed = the changeset is considered permanent
        # applied = an applied patch
        # qgoto = applied patch or qparent
        isrev   = lambda ap, wd, tags: not wd
        iswd   = lambda ap, wd, tags: bool(wd)
        isctx   = lambda ap, wd, tags: True
        fixed   = lambda ap, wd, tags: not (ap or wd)
        applied = lambda ap, wd, tags: ap
        qgoto   = lambda ap, wd, tags: ('qparent' in tags) or \
                                       (ap)

        exs = self.repo.extensions()

        def entry(menu, ext=None, func=None, desc=None, icon=None, cb=None):
            if ext and ext not in exs:
                return
            if desc is None:
                return menu.addSeparator()
            act = QAction(desc, self)
            if cb:
                act.triggered.connect(cb)
            if icon:
                act.setIcon(qtlib.geticon(icon))
            act.enableFunc = func
            menu.addAction(act)
            items.append(act)
            return act
        menu = QMenu(self)
        if mode == 'outgoing':
            pushtypeicon = {'all': None, 'branch': None, 'revision': None}
            defaultpush = self.repo.ui.config(
                'tortoisehg', 'defaultpush', 'all')
            pushtypeicon[defaultpush] = 'hg-push'
            submenu = menu.addMenu(_('Pus&h'))
            entry(submenu, None, isrev, _('Push to &Here'),
                  pushtypeicon['revision'], self.pushToRevision)
            entry(submenu, None, isrev, _('Push Selected &Branch'),
                  pushtypeicon['branch'], self.pushBranch)
            entry(submenu, None, isrev, _('Push &All'),
                  pushtypeicon['all'], self.pushAll)
            entry(menu)
        entry(menu, None, isrev, _('&Update...'), 'hg-update',
              self.updateToRevision)
        entry(menu)
        entry(menu, None, isctx, _('&Diff to Parent'), 'visualdiff',
              self.visualDiffRevision)
        entry(menu, None, isrev, _('Diff to &Local'), 'ldiff',
              self.visualDiffToLocal)
        entry(menu, None, isctx, _('Bro&wse at Revision'), 'hg-annotate',
              self.manifestRevision)
        act = self._createFilterBySelectedRevisionsMenu()
        act.enableFunc = isrev
        menu.addAction(act)
        items.append(act)
        entry(menu)
        entry(menu, None, fixed, _('&Merge with Local...'), 'hg-merge',
              self.mergeWithRevision)
        entry(menu)
        entry(menu, None, fixed, _('&Tag...'), 'hg-tag',
              self.tagToRevision)
        entry(menu, None, isrev, _('Boo&kmark...'), 'hg-bookmarks',
              self.bookmarkRevision)
        entry(menu, 'gpg', fixed, _('Sig&n...'), 'hg-sign',
              self.signRevision)
        entry(menu)
        entry(menu, None, fixed, _('&Backout...'), 'hg-revert',
              self.backoutToRevision)
        entry(menu, None, isctx, _('Revert &All Files...'), 'hg-revert',
              self.revertToRevision)
        entry(menu)

        entry(menu, None, isrev, _('Copy &Hash'), 'copy-hash',
              self.copyHash)
        entry(menu)

        submenu = menu.addMenu(_('E&xport'))
        entry(submenu, None, isrev, _('E&xport Patch...'), 'hg-export',
              self.exportRevisions)
        entry(submenu, None, isrev, _('&Email Patch...'), 'mail-forward',
              self.emailSelectedRevisions)
        entry(submenu, None, isrev, _('&Archive...'), 'hg-archive',
              self.archiveRevision)
        entry(submenu, None, isrev, _('&Bundle Rev and Descendants...'),
              'hg-bundle', self.bundleRevisions)
        entry(submenu, None, isctx, _('&Copy Patch'), 'copy-patch',
              self.copyPatch)
        entry(menu)

        submenu = menu.addMenu(_('Change &Phase to'))
        submenu.triggered.connect(self._changePhaseByMenu)
        for pnum, pname in enumerate(phases.phasenames):
            entry(submenu, None, isrev, pname).setData(pnum)
        entry(menu)

        entry(menu, None, isrev, _('&Graft to Local...'), 'hg-transplant',
              self.graftRevisions)

        if 'mq' in exs or 'rebase' in exs or 'strip' in exs or 'evolve' in exs:
            submenu = menu.addMenu(_('Modi&fy History'))
            entry(submenu, 'mq', applied, _('&Unapply Patch'), 'hg-qgoto',
                  self.qgotoParentRevision)
            entry(submenu, 'mq', fixed, _('Import to &MQ'), 'qimport',
                  self.qimportRevision)
            entry(submenu, 'mq', applied, _('&Finish Patch'), 'qfinish',
                  self.qfinishRevision)
            entry(submenu, 'mq', applied, _('Re&name Patch...'), None,
                  self.qrename)
            entry(submenu, 'mq')
            if self._mqActions:
                entry(submenu, 'mq', isctx, _('MQ &Options'), None,
                      self._mqActions.launchOptionsDialog)
                entry(submenu, 'mq')
            entry(submenu, 'rebase', isrev, _('&Rebase...'), 'hg-rebase',
                  self.rebaseRevision)
            entry(submenu, 'rebase')
            entry(submenu, 'evolve', fixed, _('&Prune...'), 'edit-cut',
                  self._pruneSelected)
            if 'mq' in exs or 'strip' in exs:
                entry(submenu, None, fixed, _('&Strip...'), 'hg-strip',
                      self.stripRevision)

        entry(menu, 'reviewboard', isrev, _('Post to Re&view Board...'), 'reviewboard',
              self.sendToReviewBoard)

        entry(menu, 'rupdate', fixed, _('&Remote Update...'), 'hg-update',
              self.rupdate)

        def _setupCustomSubmenu(menu):
            tools, toollist = hglib.tortoisehgtools(self.repo.ui,
                selectedlocation='workbench.revdetails.custom-menu')
            if not tools:
                return

            istrue = lambda ap, wd, tags: True
            enablefuncs = {
                'istrue': istrue, 'iswd': iswd, 'isrev': isrev, 'isctx': isctx,
                'fixed': fixed, 'applied': applied, 'qgoto': qgoto
            }

            entry(menu)
            submenu = menu.addMenu(_('Custom Tools'))
            submenu.triggered.connect(self._runCustomCommandByMenu)
            for name in toollist:
                if name == '|':
                    entry(submenu)
                    continue
                info = tools.get(name, None)
                if info is None:
                    continue
                command = info.get('command', None)
                if not command:
                    continue
                workingdir = info.get('workingdir', '')
                showoutput = info.get('showoutput', False)
                label = info.get('label', name)
                icon = info.get('icon', 'tools-spanner-hammer')
                enable = info.get('enable', 'istrue').lower()
                if enable in enablefuncs:
                    enable = enablefuncs[enable]
                else:
                    continue
                a = entry(submenu, None, enable, label, icon)
                a.setData((command, showoutput, workingdir))

        _setupCustomSubmenu(menu)

        if mode == 'outgoing':
            self.outgoingcmenu = menu
            self.outgoingcmenuitems = items
        else:
            self.singlecmenu = menu
            self.singlecmenuitems = items

    def _gotoAncestor(self):
        ancestor = self.repo[self.menuselection[0]]
        for rev in self.menuselection[1:]:
            ctx = self.repo[rev]
            ancestor = ancestor.ancestor(ctx)
        self.goto(ancestor.rev())

    def generatePairMenu(self):
        def dagrange():
            revA, revB = self.menuselection
            if revA > revB:
                B, A = self.menuselection
            else:
                A, B = self.menuselection
            # simply disable lazy evaluation as we won't handle slow query
            return list(self.repo.revs('%s::%s' % (A, B)))

        def exportPair():
            self.exportRevisions(self.menuselection)
        def exportDiff():
            root = self.repo.root
            filename = '%s_%d_to_%d.diff' % (os.path.basename(root),
                                             self.menuselection[0],
                                             self.menuselection[1])
            file = QFileDialog.getSaveFileName(self, _('Write diff file'),
                               hglib.tounicode(os.path.join(root, filename)))
            if not file:
                return
            f = QFile(file)
            if not f.open(QIODevice.WriteOnly | QIODevice.Truncate):
                WarningMsgBox(_('Repository Error'),
                              _('Unable to write diff file'))
                return
            sess = self._buildPatch('diff')
            sess.setOutputDevice(f)
        def exportDagRange():
            l = dagrange()
            if l:
                self.exportRevisions(l)
        def diffPair():
            revA, revB = self.menuselection
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, [],
                    {'rev':(str(revA), str(revB))})
            if dlg:
                dlg.exec_()
        def emailPair():
            self._emailRevisions(self.menuselection)
        def emailDagRange():
            l = dagrange()
            if l:
                self._emailRevisions(l)
        def bundleDagRange():
            l = dagrange()
            if l:
                self.bundleRevisions(base=l[0], tip=l[-1])
        def bisectNormal():
            revA, revB = self.menuselection
            dlg = self._dialogs.open(RepoWidget._createBisectDialog)
            dlg.restart(str(revA), str(revB))
        def bisectReverse():
            revA, revB = self.menuselection
            dlg = self._dialogs.open(RepoWidget._createBisectDialog)
            dlg.restart(str(revB), str(revA))
        def compressDlg():
            ctxa, ctxb = map(self.repo.hgchangectx, self.menuselection)
            if ctxa.ancestor(ctxb) == ctxb:
                revs = self.menuselection[:]
            elif ctxa.ancestor(ctxb) == ctxa:
                revs = [self.menuselection[1], self.menuselection[0]]
            else:
                InfoMsgBox(_('Unable to compress history'),
                           _('Selected changeset pair not related'))
                return
            dlg = compress.CompressDialog(self._repoagent, revs, self)
            dlg.exec_()
        def rebaseDlg():
            opts = {'source': self.menuselection[0],
                    'dest': self.menuselection[1]}
            dlg = rebase.RebaseDialog(self._repoagent, self, **opts)
            dlg.exec_()

        exs = self.repo.extensions()

        menu = QMenu(self)
        for name, cb, icon, ext in (
                (_('Visual Diff...'), diffPair, 'visualdiff', None),
                (_('Export Diff...'), exportDiff, 'hg-export', None),
                (None, None, None, None),
                (_('Export Selected...'), exportPair, 'hg-export', None),
                (_('Email Selected...'), emailPair, 'mail-forward', None),
                (_('Copy Selected as Patch'), self.copyPatch, 'copy-patch', None),
                (None, None, None, None),
                (_('Export DAG Range...'), exportDagRange, 'hg-export', None),
                (_('Email DAG Range...'), emailDagRange, 'mail-forward', None),
                (_('Bundle DAG Range...'), bundleDagRange, 'hg-bundle', None),
                (None, None, None, None),
                (_('Bisect - Good, Bad...'), bisectNormal, 'hg-bisect-good-bad', None),
                (_('Bisect - Bad, Good...'), bisectReverse, 'hg-bisect-bad-good', None),
                (_('Compress History...'), compressDlg, 'hg-compress', None),
                (_('Rebase...'), rebaseDlg, 'hg-rebase', 'rebase'),
                (None, None, None, None),
                (_('Goto common ancestor'), self._gotoAncestor, 'hg-merge', None),
                (self._createFilterBySelectedRevisionsMenu, None, None, None),
                (None, None, None, None),
                (_('Graft Selected to local...'), self.graftRevisions, 'hg-transplant', None),
                (None, None, None, None),
                (_('&Prune Selected...'), self._pruneSelected, 'edit-cut',
                 'evolve'),
                ):
            if name is None:
                menu.addSeparator()
                continue
            if ext and ext not in exs:
                continue
            if callable(name):
                a = name()
            else:
                a = QAction(name, self)
            if icon:
                a.setIcon(qtlib.geticon(icon))
            if cb:
                a.triggered.connect(cb)
            menu.addAction(a)

        if 'reviewboard' in self.repo.extensions():
            menu.addSeparator()
            a = QAction(_('Post Selected to Review Board...'), self)
            a.triggered.connect(self.sendToReviewBoard)
            menu.addAction(a)
        self.paircmenu = menu

    def generateUnappliedPatchMenu(self):
        def qdeleteact():
            """Delete unapplied patch(es)"""
            patches = map(hglib.tounicode, self.menuselection)
            self._mqActions.deletePatches(patches)
        def qfoldact():
            patches = map(hglib.tounicode, self.menuselection)
            self._mqActions.foldPatches(patches)

        menu = QMenu(self)
        acts = []
        for name, cb, icon in (
            (_('Apply patch'), self.qpushRevision, 'hg-qpush'),
            (_('Apply onto original parent'), self.qpushExactRevision, None),
            (_('Apply only this patch'), self.qpushMoveRevision, None),
            (_('Fold patches...'), qfoldact, 'hg-qfold'),
            (_('Delete patches...'), qdeleteact, 'hg-qdelete'),
            (_('Rename patch...'), self.qrename, None)):
            act = QAction(name, self)
            act.triggered.connect(cb)
            if icon:
                act.setIcon(qtlib.geticon(icon))
            acts.append(act)
            menu.addAction(act)
        menu.addSeparator()
        acts.append(menu.addAction(_('MQ &Options'),
                                   self._mqActions.launchOptionsDialog))
        self.unappcmenu = menu
        self.unappacts = acts

    def generateMultipleSelectionMenu(self):
        def exportSel():
            self.exportRevisions(self.menuselection)
        def emailSel():
            self._emailRevisions(self.menuselection)
        menu = QMenu(self)
        for name, cb, icon in (
                (_('Export Selected...'), exportSel, 'hg-export'),
                (_('Email Selected...'), emailSel, 'mail-forward'),
                (_('Copy Selected as Patch'), self.copyPatch, 'copy-patch'),
                (None, None, None),
                (_('Goto common ancestor'), self._gotoAncestor, 'hg-merge'),
                (self._createFilterBySelectedRevisionsMenu, None, None),
                (None, None, None),
                (_('Graft Selected to local...'), self.graftRevisions, 'hg-transplant'),
                ):
            if name is None:
                menu.addSeparator()
                continue
            if callable(name):
                a = name()
            else:
                a = QAction(name, self)
            if icon:
                a.setIcon(qtlib.geticon(icon))
            if cb:
                a.triggered.connect(cb)
            menu.addAction(a)

        if 'evolve' in self.repo.extensions():
            menu.addSeparator()
            a = QAction(_('&Prune Selected...'), self)
            a.setIcon(qtlib.geticon('edit-cut'))
            a.triggered.connect(self._pruneSelected)
            menu.addAction(a)

        if 'reviewboard' in self.repo.extensions():
            a = QAction(_('Post Selected to Review Board...'), self)
            a.triggered.connect(self.sendToReviewBoard)
            menu.addAction(a)
        self.multicmenu = menu

    def generateBundleMenu(self):
        menu = QMenu(self)
        for name, cb, icon in (
                (_('Pull to here...'), self.pullBundleToRev, 'hg-pull-to-here'),
                (_('Visual diff...'), self.visualDiffRevision, 'visualdiff'),
                ):
            a = QAction(name, self)
            a.triggered.connect(cb)
            if icon:
                a.setIcon(qtlib.geticon(icon))
            menu.addAction(a)
        self.bundlemenu = menu
    def generateOutgoingMenu(self):
        self.generateSingleMenu(mode='outgoing')

    def exportRevisions(self, revisions):
        if not revisions:
            revisions = [self.rev]
        if len(revisions) == 1:
            if isinstance(self.rev, int):
                defaultpath = os.path.join(self.repoRootPath(),
                                           '%d.patch' % self.rev)
            else:
                defaultpath = self.repoRootPath()

            ret = QFileDialog.getSaveFileName(self, _('Export patch'),
                                              defaultpath,
                                              _('Patch Files (*.patch)'))
            if not ret:
                return
            epath = unicode(ret)
            udir = os.path.dirname(epath)
            custompath = True
        else:
            udir = QFileDialog.getExistingDirectory(self, _('Export patch'),
                                                   hglib.tounicode(self.repo.root))
            if not udir:
                return
            udir = unicode(udir)
            ename = self._repoagent.shortName() + '_%r.patch'
            epath = os.path.join(udir, ename)
            custompath = False

        cmdline = hglib.buildcmdargs('export', verbose=True, output=epath,
                                     rev=hglib.compactrevs(sorted(revisions)))

        existingRevisions = []
        for rev in revisions:
            if custompath:
                path = epath
            else:
                path = epath % rev
            if os.path.exists(path):
                if os.path.isfile(path):
                    existingRevisions.append(rev)
                else:
                    QMessageBox.warning(self,
                        _('Cannot export revision'),
                        (_('Cannot export revision %s into the file named:'
                        '\n\n%s\n') % (rev, epath % rev)) + \
                        _('There is already an existing folder '
                        'with that same name.'))
                    return

        if existingRevisions:
            buttonNames = [_("Replace"), _("Append"), _("Abort")]

            warningMessage = \
                _('There are existing patch files for %d revisions (%s) '
                'in the selected location (%s).\n\n') \
                % (len(existingRevisions),
                    " ,".join([str(rev) for rev in existingRevisions]),
                    udir)

            warningMessage += \
                _('What do you want to do?\n') + u'\n' + \
                u'- ' + _('Replace the existing patch files.\n') + \
                u'- ' + _('Append the changes to the existing patch files.\n') + \
                u'- ' + _('Abort the export operation.\n')

            res = qtlib.CustomPrompt(_('Patch files already exist'),
                warningMessage,
                self,
                buttonNames, 0, 2).run()

            if buttonNames[res] == _("Replace"):
                # Remove the existing patch files
                for rev in existingRevisions:
                    if custompath:
                        os.remove(epath)
                    else:
                        os.remove(epath % rev)
            elif buttonNames[res] == _("Abort"):
                return

        self._runCommand(cmdline)

        if len(revisions) == 1:
            # Show a message box with a link to the export folder and to the
            # exported file
            rev = revisions[0]
            patchfilename = os.path.normpath(epath)
            patchdirname = os.path.normpath(os.path.dirname(epath))
            patchshortname = os.path.basename(patchfilename)
            if patchdirname.endswith(os.path.sep):
                patchdirname = patchdirname[:-1]
            qtlib.InfoMsgBox(_('Patch exported'),
                _('Revision #%d (%s) was exported to:<p>'
                '<a href="file:///%s">%s</a>%s'
                '<a href="file:///%s">%s</a>') \
                % (rev, str(self.repo[rev]),
                   patchdirname, patchdirname, os.path.sep,
                   patchfilename, patchshortname))
        else:
            # Show a message box with a link to the export folder
            qtlib.InfoMsgBox(_('Patches exported'),
                _('%d patches were exported to:<p>'
                '<a href="file:///%s">%s</a>') \
                % (len(revisions), udir, udir))

    def visualDiffRevision(self):
        opts = dict(change=self.rev)
        dlg = visdiff.visualdiff(self.repo.ui, self.repo, [], opts)
        if dlg:
            dlg.exec_()

    def visualDiffToLocal(self):
        if self.rev is None:
            return
        opts = dict(rev=['rev(%d)' % self.rev])
        dlg = visdiff.visualdiff(self.repo.ui, self.repo, [], opts)
        if dlg:
            dlg.exec_()

    @pyqtSlot()
    def updateToRevision(self):
        rev = None
        if isinstance(self.rev, int):
            rev = hglib.getrevisionlabel(self.repo, self.rev)
        dlg = update.UpdateDialog(self._repoagent, rev, self)
        r = dlg.exec_()
        if r in (0, 1):
            self.gotoParent()

    @pyqtSlot()
    def lockTool(self):
        from locktool import LockDialog
        dlg = LockDialog(self._repoagent, self)
        if dlg:
            dlg.exec_()

    @pyqtSlot()
    def revertToRevision(self):
        if not qtlib.QuestionMsgBox(
                _('Confirm Revert'),
                _('Reverting all files will discard changes and '
                  'leave affected files in a modified state.<br>'
                  '<br>Are you sure you want to use revert?<br><br>'
                  '(use update to checkout another revision)'),
                parent=self):
            return
        cmdline = hglib.buildcmdargs('revert', all=True, rev=self.rev)
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._refreshCommitTabIfNeeded)

    def _createFilterBySelectedRevisionsMenu(self):
        menu = QMenu(_('Filter b&y'), self)
        menu.setIcon(qtlib.geticon('view-filter'))
        menu.triggered.connect(self._filterBySelectedRevisions)
        for t, r in [(_('&Ancestors and Descendants'),
                      "ancestors({revs}) or descendants({revs})"),
                     (_('A&uthor'), "matching({revs}, 'author')"),
                     (_('&Branch'), "branch({revs})"),
                     ]:
            a = menu.addAction(t)
            a.setData(r)
        menu.addSeparator()
        menu.addAction(_('&More Options...'))
        return menu.menuAction()

    @pyqtSlot(QAction)
    def _filterBySelectedRevisions(self, action):
        revs = hglib.compactrevs(sorted(self.repoview.selectedRevisions()))
        expr = str(action.data().toString())
        if not expr:
            self._filterByMatchDialog(revs)
            return
        self.setFilter(expr.format(revs=revs))

    def _filterByMatchDialog(self, revlist):
        dlg = matching.MatchDialog(self._repoagent, revlist, self)
        if dlg.exec_():
            self.setFilter(dlg.revsetexpression)

    def pushAll(self):
        self.syncDemand.forward('push', False, pushall=True)

    def pushToRevision(self):
        # Do not ask for confirmation
        self.syncDemand.forward('push', False, rev=self.rev)

    def pushBranch(self):
        # Do not ask for confirmation
        self.syncDemand.forward('push', False,
            branch=self.repo[self.rev].branch())

    def manifestRevision(self):
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self._dialogs.openNew(RepoWidget._createManifestDialog)
        else:
            dlg = self._dialogs.open(RepoWidget._createManifestDialog)
            dlg.setRev(self.rev)

    def _createManifestDialog(self):
        return revdetails.createManifestDialog(self._repoagent, self.rev)

    def mergeWithOtherHead(self):
        """Open dialog to merge with the other head of the current branch"""
        cmdline = hglib.buildcmdargs('merge', preview=True,
                                     config='ui.logtemplate={rev}\n')
        sess = self._runCommand(cmdline)
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._onMergePreviewFinished)

    @qtlib.senderSafeSlot(int)
    def _onMergePreviewFinished(self, ret):
        sess = self.sender()
        if ret == 255 and 'hg heads' in sess.errorString():
            # multiple heads
            self.filterbar.setQuery('head() - .')
            self.filterbar.runQuery()
            msg = '\n'.join(sess.errorString().splitlines()[:-1])  # drop hint
            w = self.setInfoBar(infobar.ConfirmInfoBar, msg)
            assert w
            w.acceptButton.setText(_('Merge'))
            w.accepted.connect(self.mergeWithRevision)
            w.finished.connect(self.clearRevisionSet)
            return
        if ret != 0:
            return
        revs = map(int, str(sess.readAll()).splitlines())
        if not revs:
            return
        self._dialogs.open(RepoWidget._createMergeDialog, revs[-1])

    @pyqtSlot()
    def mergeWithRevision(self):
        pctx = self.repo['.']
        octx = self.repo[self.rev]
        if pctx == octx:
            QMessageBox.warning(self, _('Unable to merge'),
                _('You cannot merge a revision with itself'))
            return
        self._dialogs.open(RepoWidget._createMergeDialog, self.rev)

    def _createMergeDialog(self, rev):
        return merge.MergeDialog(self._repoagent, rev, self)

    def tagToRevision(self):
        dlg = tag.TagDialog(self._repoagent, rev=str(self.rev), parent=self)
        dlg.exec_()

    def bookmarkRevision(self):
        dlg = bookmark.BookmarkDialog(self._repoagent, self.rev, self)
        dlg.exec_()

    def signRevision(self):
        dlg = sign.SignDialog(self._repoagent, self.rev, self)
        dlg.exec_()

    def graftRevisions(self):
        """Graft selected revision on top of working directory parent"""
        revlist = []
        for rev in sorted(self.repoview.selectedRevisions()):
            revlist.append(str(rev))
        if not revlist:
            revlist = [self.rev]
        dlg = graft.GraftDialog(self._repoagent, self, source=revlist)
        if dlg.valid:
            dlg.exec_()

    def backoutToRevision(self):
        msg = backout.checkrev(self._repoagent.rawRepo(), self.rev)
        if msg:
            qtlib.InfoMsgBox(_('Unable to backout'), msg, parent=self)
            return
        dlg = backout.BackoutDialog(self._repoagent, self.rev, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    @pyqtSlot()
    def _pruneSelected(self):
        revspec = hglib.compactrevs(sorted(self.repoview.selectedRevisions()))
        dlg = prune.createPruneDialog(self._repoagent, revspec, self)
        dlg.exec_()

    def stripRevision(self):
        'Strip the selected revision and all descendants'
        dlg = thgstrip.createStripDialog(self._repoagent, rev=str(self.rev),
                                         parent=self)
        dlg.exec_()

    def sendToReviewBoard(self):
        self._dialogs.open(RepoWidget._createPostReviewDialog,
                           tuple(self.repoview.selectedRevisions()))

    def _createPostReviewDialog(self, revs):
        return postreview.PostReviewDialog(self.repo.ui, self._repoagent, revs)

    def rupdate(self):
        import rupdate
        dlg = rupdate.createRemoteUpdateDialog(self._repoagent, self.rev, self)
        dlg.exec_()

    @pyqtSlot()
    def emailSelectedRevisions(self):
        self._emailRevisions(self.repoview.selectedRevisions())

    def _emailRevisions(self, revs):
        self._dialogs.open(RepoWidget._createEmailDialog, tuple(revs))

    def _createEmailDialog(self, revs):
        return hgemail.EmailDialog(self._repoagent, revs)

    def archiveRevision(self):
        rev = hglib.getrevisionlabel(self.repo, self.rev)
        dlg = archive.createArchiveDialog(self._repoagent, rev, self)
        dlg.exec_()

    def bundleRevisions(self, base=None, tip=None):
        root = self.repoRootPath()
        if base is None or base is False:
            base = self.rev
        data = dict(name=os.path.basename(root), base=base)
        if tip is None:
            filename = '%(name)s_%(base)s_and_descendants.hg' % data
        else:
            data.update(rev=tip)
            filename = '%(name)s_%(base)s_to_%(rev)s.hg' % data

        file = QFileDialog.getSaveFileName(self, _('Write bundle'),
                                           os.path.join(root, filename))
        if not file:
            return

        cmdline = ['bundle', '--verbose']
        parents = [hglib.escaperev(r.rev()) for r in self.repo[base].parents()]
        for p in parents:
            cmdline.extend(['--base', p])
        if tip:
            cmdline.extend(['--rev', str(tip)])
        else:
            cmdline.extend(['--rev', 'heads(descendants(%s))' % base])
        cmdline.append(unicode(file))
        self._runCommand(cmdline)

    def _buildPatch(self, command=None):
        if not command:
            # workingdir revision cannot be exported
            if self.rev is None:
                command = 'diff'
            else:
                command = 'export'
        assert command in ('export', 'diff')
        if command == 'export':
            # patches should be in chronological order
            revs = sorted(self.menuselection)
            cmdline = hglib.buildcmdargs('export', rev=hglib.compactrevs(revs))
        else:
            revs = self.rev and self.menuselection or None
            cmdline = hglib.buildcmdargs('diff', rev=revs)
        return self._runCommand(cmdline)

    @pyqtSlot()
    def copyPatch(self):
        sess = self._buildPatch()
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._copyPatchOutputToClipboard)

    @qtlib.senderSafeSlot(int)
    def _copyPatchOutputToClipboard(self, ret):
        if ret == 0:
            sess = self.sender()
            output = sess.readAll()
            mdata = QMimeData()
            mdata.setData('text/x-diff', output)  # for lossless import
            mdata.setText(hglib.tounicode(str(output)))
            QApplication.clipboard().setMimeData(mdata)

    def copyHash(self):
        clip = QApplication.clipboard()
        clip.setText(binascii.hexlify(self.repo[self.rev].node()))

    def changePhase(self, phase):
        currentphase = self.repo[self.rev].phase()
        if currentphase == phase:
            # There is nothing to do, we are already in the target phase
            return
        phasestr = phases.phasenames[phase]
        cmdline = ['phase', '--rev', '%s' % self.rev, '--%s' % phasestr]
        if currentphase < phase:
            # Ask the user if he wants to force the transition
            title = _('Backwards phase change requested')
            if currentphase == phases.draft and phase == phases.secret:
                # Here we are sure that the current phase is draft and the target phase is secret
                # Nevertheless we will not hard-code those phase names on the dialog strings to
                # make sure that the proper phase name translations are used
                main = _('Do you really want to make this revision <i>secret</i>?')
                text = _('Making a "<i>draft</i>" revision "<i>secret</i>" '
                         'is generally a safe operation.\n\n'
                         'However, there are a few caveats:\n\n'
                         '- "secret" revisions are not pushed. '
                         'This can cause you trouble if you\n'
                         'refer to a secret subrepo revision.\n\n'
                         '- If you pulled this revision from '
                         'a non publishing server it may be\n'
                         'moved back to "<i>draft</i>" if you pull '
                         'again from that particular server.\n\n'
                         'Please be careful!')
                labels = ((QMessageBox.Yes, _('&Make secret')),
                          (QMessageBox.No, _('&Cancel')))
            else:
                main = _('Do you really want to <i>force</i> a backwards phase transition?')
                text = _('You are trying to move the phase of revision %d backwards,\n'
                         'from "<i>%s</i>" to "<i>%s</i>".\n\n'
                         'However, "<i>%s</i>" is a lower phase level than "<i>%s</i>".\n\n'
                         'Moving the phase backwards is not recommended.\n'
                         'For example, it may result in having multiple heads\nif you '
                         'modify a revision that you have already pushed\nto a server.\n\n'
                         'Please be careful!') % (self.rev, phases.phasenames[currentphase], phasestr, phasestr,
                                                  phases.phasenames[currentphase])
                labels = ((QMessageBox.Yes, _('&Force')),
                          (QMessageBox.No, _('&Cancel')))
            if not qtlib.QuestionMsgBox(title, main, text,
                    labels=labels, parent=self):
                return
            cmdline.append('--force')
        self._runCommand(cmdline)

    @pyqtSlot(QAction)
    def _changePhaseByMenu(self, action):
        phasenum, _ok = action.data().toInt()
        self.changePhase(phasenum)

    def rebaseRevision(self):
        """Rebase selected revision on top of working directory parent"""
        opts = {'source' : self.rev, 'dest': self.repo['.'].rev()}
        dlg = rebase.RebaseDialog(self._repoagent, self, **opts)
        dlg.exec_()

    def qimportRevision(self):
        """QImport revision and all descendents to MQ"""
        if 'qparent' in self.repo.tags():
            endrev = 'qparent'
        else:
            endrev = ''

        # Check whether there are existing patches in the MQ queue whose name
        # collides with the revisions that are going to be imported
        revList = self.repo.revs('%s::%s and not hidden()' % (self.rev, endrev))

        if endrev and not revList:
            # There is a qparent but the revision list is empty
            # This means that the qparent is not a descendant of the
            # selected revision
            QMessageBox.warning(self, _('Cannot import selected revision'),
                _('The selected revision (rev #%d) cannot be imported '
                'because it is not a descendant of ''qparent'' (rev #%d)') \
                % (self.rev, self.repo['qparent'].rev()))
            return

        patchdir = self.repo.join('patches')
        def patchExists(p):
            return os.path.exists(os.path.join(patchdir, p))

        # Note that the following two arrays are both ordered by "rev"
        defaultPatchNames = ['%d.diff' % rev for rev in revList]
        defaultPatchesExist = [patchExists(p) for p in defaultPatchNames]
        if any(defaultPatchesExist):
            # We will qimport each revision one by one, starting from the newest
            # To do so, we will find a valid and unique patch name for each
            # revision that we must qimport (i.e. a filename that does not
            # already exist)
            # and then we will import them one by one starting from the newest
            # one, using these unique names
            def getUniquePatchName(baseName):
                maxRetries = 99
                for n in range(1, maxRetries):
                    patchName = baseName + '_%02d.diff' % n
                    if not patchExists(patchName):
                        return patchName
                return baseName

            patchNames = {}
            for n, rev in enumerate(revList):
                if defaultPatchesExist[n]:
                    patchNames[rev] = getUniquePatchName(str(rev))
                else:
                    # The default name is safe
                    patchNames[rev] = defaultPatchNames[n]

            # qimport each revision individually, starting from the topmost one
            revList.reverse()
            cmdlines = []
            for rev in revList:
                cmdlines.append(['qimport', '--rev', '%s' % rev,
                                 '--name', patchNames[rev]])
            self._runCommandSequence(cmdlines)
        else:
            # There were no collisions with existing patch names, we can
            # simply qimport the whole revision set in a single go
            cmdline = ['qimport', '--rev', '%s::%s' % (self.rev, endrev)]
            self._runCommand(cmdline)

    def qfinishRevision(self):
        """Finish applied patches up to and including selected revision"""
        self._mqActions.finishRevision(hglib.tounicode(str(self.rev)))

    @pyqtSlot()
    def qgotoParentRevision(self):
        """Apply an unapplied patch, or qgoto the parent of an applied patch"""
        self.qgotoRevision(self.repo[self.rev].p1().rev())

    @pyqtSlot()
    def qgotoSelectedRevision(self):
        self.qgotoRevision(self.rev)

    def qgotoRevision(self, rev):
        """Make REV the top applied patch"""
        mqw = self._mqActions
        ctx = self.repo.changectx(rev)
        if 'qparent'in ctx.tags():
            mqw.popAllPatches()
        else:
            mqw.gotoPatch(hglib.tounicode(ctx.thgmqpatchname()))

    def qrename(self):
        sel = self.menuselection[0]
        if not isinstance(sel, str):
            sel = self.repo.changectx(sel).thgmqpatchname()
        self._mqActions.renamePatch(hglib.tounicode(sel))

    def _qpushRevision(self, move=False, exact=False):
        """QPush REV with the selected options"""
        ctx = self.repo.changectx(self.rev)
        patchname = hglib.tounicode(ctx.thgmqpatchname())
        self._mqActions.pushPatch(patchname, move=move, exact=exact)

    def qpushRevision(self):
        """Call qpush with no options"""
        self._qpushRevision(move=False, exact=False)

    def qpushExactRevision(self):
        """Call qpush using the exact flag"""
        self._qpushRevision(exact=True)

    def qpushMoveRevision(self):
        """Make REV the top applied patch"""
        self._qpushRevision(move=True)

    def runCustomCommand(self, command, showoutput=False, workingdir='',
            files=None):
        """Execute 'custom commands', on the selected repository"""
        # Perform variable expansion
        # This is done in two steps:
        # 1. Expand environment variables
        command = os.path.expandvars(command).strip()
        if not command:
            InfoMsgBox(_('Invalid command'),
                       _('The selected command is empty'))
            return
        if workingdir:
            workingdir = os.path.expandvars(workingdir).strip()

        # 2. Expand internal workbench variables
        def filelist2str(filelist):
            return ' '.join(util.shellquote(
                            os.path.normpath(self.repo.wjoin(filename)))
                            for filename in filelist)
        if files is None:
            files = []
        vars = {
            'ROOT': self.repo.root,
            'REVID': str(self.repo[self.rev]),
            'REV': self.rev,
            'FILES': filelist2str(self.repo[self.rev].files()),
            'ALLFILES': filelist2str(self.repo[self.rev]),
            'SELECTEDFILES': filelist2str(files),
        }
        for var in vars:
            command = command.replace('{%s}' % var, str(vars[var]))
            if workingdir:
                workingdir = workingdir.replace('{%s}' % var, str(vars[var]))
        if not workingdir:
            workingdir = self.repo.root

        # Show the Output Log if configured to do so
        if showoutput:
            self.makeLogVisible.emit(True)

        # If the user wants to run mercurial,
        # do so via our usual runCommand method
        cmd = shlex.split(command)
        cmdtype = cmd[0].lower()
        if cmdtype == 'hg':
            sess = self._runCommand(map(hglib.tounicode, cmd[1:]))
            sess.commandFinished.connect(self._notifyWorkingDirChanges)
            return
        elif cmdtype == 'thg':
            cmd = cmd[1:]
            if '--repository' in cmd:
                _ui = ui.ui()
            else:
                cmd += ['--repository', self.repo.root]
                _ui = self.repo.ui.copy()
            _ui.ferr = cStringIO.StringIO()
            # avoid circular import of hgqt.run by importing it inplace
            from tortoisehg.hgqt import run
            res = run.dispatch(cmd, u=_ui)
            if res:
                errormsg = _ui.ferr.getvalue().strip()
                if errormsg:
                    errormsg = \
                        _('The following error message was returned:'
                          '\n\n<b>%s</b>') % hglib.tounicode(errormsg)
                errormsg +=\
                    _('\n\nPlease check that the "thg" command is valid.')
                qtlib.ErrorMsgBox(
                    _('Failed to execute custom TortoiseHg command'),
                    _('The command "%s" failed (code %d).')
                    % (hglib.tounicode(command), res), errormsg)
            return res

        # Otherwise, run the selected command in the background
        try:
            res = subprocess.Popen(command, cwd=workingdir, shell=True)
        except OSError, ex:
            res = 1
            qtlib.ErrorMsgBox(_('Failed to execute custom command'),
                _('The command "%s" could not be executed.') % hglib.tounicode(command),
                _('The following error message was returned:\n\n"%s"\n\n'
                'Please check that the command path is valid and '
                'that it is a valid application') % hglib.tounicode(ex.strerror))
        return res

    @pyqtSlot(QAction)
    def _runCustomCommandByMenu(self, action):
        command, showoutput, workingdir = action.data().toPyObject()
        self.runCustomCommand(command, showoutput, workingdir)

    @pyqtSlot(str, list)
    def handleRunCustomCommandRequest(self, toolname, files):
        tools, toollist = hglib.tortoisehgtools(self.repo.ui)
        if not tools or toolname not in toollist:
            return
        toolname = str(toolname)
        command = tools[toolname].get('command', '')
        showoutput = tools[toolname].get('showoutput', False)
        workingdir = tools[toolname].get('workingdir', '')
        self.runCustomCommand(command, showoutput, workingdir, files)

    def _runCommand(self, cmdline):
        sess = self._repoagent.runCommand(cmdline, self)
        self._handleNewCommand(sess)
        return sess

    def _runCommandSequence(self, cmdlines):
        sess = self._repoagent.runCommandSequence(cmdlines, self)
        self._handleNewCommand(sess)
        return sess

    def _handleNewCommand(self, sess):
        self.clearInfoBar()
        sess.outputReceived.connect(self._repoviewFrame.showOutput)

    @pyqtSlot()
    def _notifyWorkingDirChanges(self):
        shlib.shell_notify([self.repo.root])

    @pyqtSlot()
    def _refreshCommitTabIfNeeded(self):
        """Refresh the Commit tab if the user settings require it"""
        if self.taskTabsWidget.currentIndex() != self._namedTabs['commit']:
            return

        refreshwd = self.repo.ui.config('tortoisehg', 'refreshwdstatus', 'auto')
        # Valid refreshwd values are 'auto', 'always' and 'alwayslocal'
        if refreshwd != 'auto':
            if refreshwd == 'always' \
                    or paths.is_on_fixed_drive(self.repo.root):
                self.commitDemand.forward('refreshWctx')


class LightRepoWindow(QMainWindow):
    def __init__(self, repoagent):
        super(LightRepoWindow, self).__init__()
        self._repoagent = repoagent
        self.setIconSize(qtlib.smallIconSize())

        repo = repoagent.rawRepo()
        val = repo.ui.config('tortoisehg', 'tasktabs', 'off').lower()
        if val not in ('east', 'west'):
            repo.ui.setconfig('tortoisehg', 'tasktabs', 'east')
        rw = RepoWidget(repoagent, self)
        self.setCentralWidget(rw)

        self._edittbar = tbar = self.addToolBar(_('&Edit Toolbar'))
        tbar.setObjectName('edittbar')
        a = tbar.addAction(qtlib.geticon('view-refresh'), _('&Refresh'))
        a.setShortcuts(QKeySequence.Refresh)
        a.triggered.connect(self.refresh)

        tbar = rw.filterBar()
        tbar.setObjectName('filterbar')
        tbar.setWindowTitle(_('&Filter Toolbar'))
        self.addToolBar(tbar)

        s = QSettings()
        s.beginGroup('LightRepoWindow')
        self.restoreGeometry(s.value('geometry').toByteArray())
        self.restoreState(s.value('windowState').toByteArray())
        s.endGroup()

    def createPopupMenu(self):
        menu = super(LightRepoWindow, self).createPopupMenu()
        assert menu  # should have toolbar
        menu.addSeparator()
        menu.addAction(_('&Settings'), self._editSettings)
        return menu

    def closeEvent(self, event):
        rw = self.centralWidget()
        if not rw.closeRepoWidget():
            event.ignore()
            return
        s = QSettings()
        s.beginGroup('LightRepoWindow')
        s.setValue('geometry', self.saveGeometry())
        s.setValue('windowState', self.saveState())
        s.endGroup()
        event.accept()

    @pyqtSlot()
    def refresh(self):
        self._repoagent.pollStatus()
        rw = self.centralWidget()
        rw.reload()

    def setSyncUrl(self, url):
        rw = self.centralWidget()
        rw.setSyncUrl(url)

    @pyqtSlot()
    def _editSettings(self):
        dlg = settings.SettingsDialog(parent=self)
        dlg.exec_()
