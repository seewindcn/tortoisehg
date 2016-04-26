# revdetails.py - TortoiseHg revision details widget
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright (C) 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

import os # for os.name

from tortoisehg.hgqt.filelistview import HgFileListView
from tortoisehg.hgqt.fileview import HgFileView
from tortoisehg.hgqt.revpanel import RevPanelWidget
from tortoisehg.hgqt import filectxactions, manifestmodel, qtlib, cmdui, status
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

_fileactionsbytype = {
    'subrepo': ['openSubrepo', 'explore', 'terminal', 'copyPath', None,
                'revertFile'],
    'file': ['visualDiffFile', 'visualDiffFileToLocal', None, 'editFile',
             'saveFile', None, 'editLocalFile', 'openLocalFile',
             'exploreLocalFile', 'copyPath', None, 'revertFile', None,
             'navigateFileLog', 'navigateFileDiff', 'filterFile'],
    'dir': ['visualDiffFile', 'visualDiffFileToLocal', None, 'revertFile',
            None, 'filterFile', None, 'explore', 'terminal', 'copyPath'],
    }

class RevDetailsWidget(QWidget, qtlib.TaskWidget):

    showMessage = pyqtSignal(str)
    linkActivated = pyqtSignal(str)
    grepRequested = pyqtSignal(str, dict)
    revisionSelected = pyqtSignal(int)
    revsetFilterRequested = pyqtSignal(str)
    runCustomCommandRequested = pyqtSignal(str, list)

    def __init__(self, repoagent, parent, rev=None):
        QWidget.__init__(self, parent)

        self._repoagent = repoagent
        repo = repoagent.rawRepo()
        self.ctx = repo[rev]
        self.splitternames = []

        self.setupUi()
        self.createActions()
        self.setupModels()

        self.filelist.installEventFilter(self)
        self.filefilter.installEventFilter(self)

        self._deschtmlize = qtlib.descriptionhtmlizer(repo.ui)
        repoagent.configChanged.connect(self._updatedeschtmlizer)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def setupUi(self):
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # + basevbox -------------------------------------------------------+
        # |+ filelistsplit ........                                         |
        # | + filelistframe (vbox)    | + panelframe (vbox)                 |
        # |  + filelisttbar           |  + revpanel                         |
        # +---------------------------+-------------------------------------+
        # |  + filelist               |  + messagesplitter                  |
        # |                           |  :+ message                         |
        # |                           |  :----------------------------------+
        # |                           |   + fileview                        |
        # +---------------------------+-------------------------------------+

        basevbox = QVBoxLayout(self)
        basevbox.setSpacing(0)
        basevbox.setMargin(0)
        basevbox.setContentsMargins(2, 2, 2, 2)

        self.filelistsplit = QSplitter(self)
        basevbox.addWidget(self.filelistsplit)

        self.splitternames.append('filelistsplit')
        self.filelistsplit.setOrientation(Qt.Horizontal)
        self.filelistsplit.setChildrenCollapsible(False)

        self.filelisttbar = QToolBar(_('File List Toolbar'))
        self.filelisttbar.setIconSize(qtlib.smallIconSize())
        self.filelist = HgFileListView(self)
        self.filelist.setContextMenuPolicy(Qt.CustomContextMenu)
        self.filelist.customContextMenuRequested.connect(self.menuRequest)
        self.filelist.doubleClicked.connect(self.onDoubleClick)
        self._filelistpaletteswitcher = qtlib.PaletteSwitcher(self.filelist)

        self.filelistframe = QWidget(self.filelistsplit)
        self.filelistsplit.setStretchFactor(0, 3)
        vbox = QVBoxLayout()
        vbox.setSpacing(0)
        vbox.setMargin(0)
        vbox.addWidget(self.filelisttbar)
        vbox.addWidget(self.filelist)
        self.filelistframe.setLayout(vbox)

        self.fileviewframe = QWidget(self.filelistsplit)
        self.filelistsplit.setStretchFactor(1, 7)

        vbox = QVBoxLayout(self.fileviewframe)
        vbox.setSpacing(0)
        vbox.setSizeConstraint(QLayout.SetDefaultConstraint)
        vbox.setMargin(0)
        panelframevbox = vbox

        self.messagesplitter = QSplitter(self.fileviewframe)
        if os.name == 'nt':
            self.messagesplitter.setStyle(QStyleFactory.create('Plastique'))

        self.splitternames.append('messagesplitter')
        self.messagesplitter.setSizePolicy(QSizePolicy.Preferred,
                                           QSizePolicy.Expanding)
        self.messagesplitter.setMinimumSize(QSize(50, 50))
        self.messagesplitter.setFrameShape(QFrame.NoFrame)
        self.messagesplitter.setLineWidth(0)
        self.messagesplitter.setMidLineWidth(0)
        self.messagesplitter.setOrientation(Qt.Vertical)
        self.messagesplitter.setOpaqueResize(True)
        self.message = QTextBrowser(self.messagesplitter,
                                    lineWrapMode=QTextEdit.NoWrap,
                                    openLinks=False)
        self.message.minimumSizeHint = lambda: QSize(0, 25)
        self.message.anchorClicked.connect(self._forwardAnchorClicked)

        self.message.setMinimumSize(QSize(0, 0))
        self.message.sizeHint = lambda: QSize(0, 100)
        f = qtlib.getfont('fontcomment')
        self.message.setFont(f.font())
        f.changed.connect(self.forwardFont)

        self.fileview = HgFileView(self._repoagent, self.messagesplitter)
        self.messagesplitter.setStretchFactor(1, 1)
        self.fileview.setMinimumSize(QSize(0, 0))
        self.fileview.linkActivated.connect(self.linkActivated)
        self.fileview.showMessage.connect(self.showMessage)
        self.fileview.grepRequested.connect(self.grepRequested)
        self.fileview.revisionSelected.connect(self.revisionSelected)
        self.filelist.fileSelected.connect(self._onFileSelected)
        self.filelist.clearDisplay.connect(self._onFileSelected)

        self.revpanel = RevPanelWidget(self.repo)
        self.revpanel.linkActivated.connect(self.linkActivated)

        panelframevbox.addWidget(self.revpanel)
        panelframevbox.addSpacing(5)
        panelframevbox.addWidget(self.messagesplitter)

    def forwardFont(self, font):
        self.message.setFont(font)

    def setupModels(self):
        model = manifestmodel.ManifestModel(self._repoagent, self)
        model.setFlat(not self.isManifestMode() and self.isFlatFileList())
        model.setStatusFilter(self.fileStatusFilter())
        model.revLoaded.connect(self._expandShortFileList)
        self.filelist.setModel(model)

        # fileSelected is actually the wrapper of currentChanged, which is
        # unrelated to the selection
        self.filelist.selectionModel().selectionChanged.connect(
            self.updateItemFileActions)

    def createActions(self):
        self._createFileListActions()

        self._parentToggleGroup.actions()[0].setChecked(True)

        self._fileactions = filectxactions.FilectxActions(self._repoagent, self)
        self._fileactions.setupCustomToolsMenu('workbench.filelist.custom-menu')
        self._fileactions.linkActivated.connect(self.linkActivated)
        self._fileactions.filterRequested.connect(self.revsetFilterRequested)
        self._fileactions.runCustomCommandRequested.connect(
            self.runCustomCommandRequested)
        self.addActions(self._fileactions.actions())

    def _createFileListActions(self):
        tbar = self.filelisttbar
        self._actionManifestMode = a = tbar.addAction(_('Ma&nifest Mode'))
        a.setCheckable(True)
        a.setIcon(qtlib.geticon('hg-annotate'))
        a.setToolTip(_('Show all version-controlled files in tree view'))
        a.triggered.connect(self._applyManifestMode)

        self._actionFlatFileList = a = QAction(_('&Flat List'), self)
        a.setCheckable(True)
        a.setChecked(True)
        a.triggered.connect(self._applyFlatFileList)

        le = QLineEdit()
        if hasattr(le, 'setPlaceholderText'): # Qt >= 4.7
            le.setPlaceholderText(_('### filter text ###'))
        self.filefilter = le
        tbar.addWidget(self.filefilter)
        t = QTimer(self, interval=200, singleShot=True)
        t.timeout.connect(self._applyFileNameFilter)
        le.textEdited.connect(t.start)
        le.returnPressed.connect(self.filelist.expandAll)

        w = status.StatusFilterActionGroup('MARS', 'MARCS', self)
        self._fileStatusFilter = w
        w.statusChanged.connect(self._applyFileStatusFilter)

        # TODO: p1/p2 toggle should be merged with fileview's
        self._parentToggleGroup = QActionGroup(self)
        self._parentToggleGroup.triggered.connect(self._selectParentRevision)
        for i, (icon, text, tip) in enumerate([
                ('hg-merged-both', _('Changed by &This Commit'),
                 _('Show files changed by this commit')),
                ('hg-merged-p1', _('Compare to &1st Parent'),
                 _('Show changes from first parent')),
                ('hg-merged-p2', _('Compare to &2nd Parent'),
                 _('Show changes from second parent'))]):
            a = self._parentToggleGroup.addAction(qtlib.geticon(icon), text)
            a.setCheckable(True)
            a.setData(i)
            a.setStatusTip(tip)

        w = QToolButton(self)
        m = QMenu(w)
        m.addActions(self._parentToggleGroup.actions())
        w.setMenu(m)
        w.setPopupMode(QToolButton.MenuButtonPopup)
        self._actionParentToggle = a = tbar.addWidget(w)
        a.setIcon(qtlib.geticon('hg-merged-both'))
        a.setToolTip(_('Toggle parent to be used as the base revision'))
        a.triggered.connect(self._toggleParentRevision)
        w.setDefaultAction(a)

    def canswitch(self):
        # assumes a user wants to browse changesets in manifest mode.  commit
        # widget isn't suitable for such usage.
        return not self.isManifestMode()

    def eventFilter(self, watched, event):
        # switch between filter and list seamlessly
        if watched is self.filefilter:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Down:
                self.filelist.setFocus()
                return True
            return False
        elif watched is self.filelist:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Up:
                index = self.filelist.currentIndex()
                if index.row() == 0 and not index.parent().isValid():
                    self.filefilter.setFocus()
                    return True
            return False

        return super(RevDetailsWidget, self).eventFilter(watched, event)

    def onRevisionSelected(self, rev):
        'called by repowidget when repoview changes revisions'
        self.ctx = ctx = self.repo.changectx(rev)
        self.revpanel.set_revision(rev)
        self.revpanel.update(repo = self.repo)
        msg = ctx.description()
        inlinetags = self.repo.ui.configbool('tortoisehg', 'issue.inlinetags')
        if ctx.tags() and inlinetags:
            msg = ' '.join(['[%s]' % tag for tag in ctx.tags()]) + ' ' + msg
        # don't use <pre>...</pre>, which also changes font family
        self.message.setHtml('<div style="white-space: pre;">%s</div>'
                             % self._deschtmlize(msg))
        self._setContextToFileList(ctx)

    def _setContextToFileList(self, ctx):
        # useless to toggle manifest mode in patchctx
        self._actionManifestMode.setEnabled(not ctx.thgmqunappliedpatch())

        self._parentToggleGroup.setVisible(len(ctx.parents()) == 2)
        self._actionParentToggle.setVisible(self._parentToggleGroup.isVisible())

        m = self.filelist.model()

        if len(ctx.parents()) != 2:
            m.setRawContext(ctx)
            m.setChangedFilesOnly(False)
            self.updateItemFileActions()
            return

        parentmode = self._parentToggleGroup.checkedAction().data().toInt()[0]
        pnum, changedonly = [(0, True),
                             (0, False),
                             (1, False)][parentmode]
        m.setRev(ctx.rev(), ctx.parents()[pnum].rev())
        m.setChangedFilesOnly(changedonly)
        self.updateItemFileActions()

    @pyqtSlot(QAction)
    def _selectParentRevision(self, action):
        self._actionParentToggle.setIcon(action.icon())
        self._setContextToFileList(self.ctx)

    @pyqtSlot()
    def _toggleParentRevision(self):
        parentactions = [a for a in self._parentToggleGroup.actions()
                         if a.isEnabled()]
        i = parentactions.index(self._parentToggleGroup.checkedAction())
        parentactions[(i + 1) % len(parentactions)].trigger()

    @pyqtSlot()
    def _updatedeschtmlizer(self):
        self._deschtmlize = qtlib.descriptionhtmlizer(self.repo.ui)
        self.onRevisionSelected(self.ctx.rev())  # regenerate desc html

    def reload(self):
        'Task tab is reloaded, or repowidget is refreshed'
        rev = self.ctx.rev()
        if (type(self.ctx.rev()) is int and len(self.repo) <= self.ctx.rev()
            or (rev is not None  # wctxrev in repo raises TypeError
                and rev not in self.repo
                and rev not in self.repo.thgmqunappliedpatches)):
            rev = 'tip'
        self.onRevisionSelected(rev)

    @pyqtSlot(QUrl)
    def _forwardAnchorClicked(self, url):
        self.linkActivated.emit(url.toString())

    #@pyqtSlot(QModelIndex)
    def onDoubleClick(self, index):
        model = self.filelist.model()
        if model.subrepoType(index):
            self._fileactions.openSubrepo()
        elif model.isDir(index):
            # expand/collapse tree by default
            pass
        elif model.fileStatus(index) == 'C':
            self._fileactions.editFile()
        else:
            self._fileactions.visualDiffFile()

    def filePath(self):
        return hglib.tounicode(self.filelist.currentFile())

    def setFilePath(self, path):
        self.filelist.setCurrentFile(hglib.fromunicode(path))

    def showLine(self, line):
        self.fileview.showLine(line - 1)  # fileview should do -1 instead?

    def setSearchPattern(self, text):
        self.fileview.searchbar.setPattern(text)

    @pyqtSlot()
    def _onFileSelected(self):
        index = self.filelist.currentIndex()
        model = self.filelist.model()
        self.fileview.display(model.fileData(index))

    @pyqtSlot(QPoint)
    def menuRequest(self, point):
        contextmenu = QMenu(self)
        if self.filelist.selectionModel().hasSelection():
            self._setupFileMenu(contextmenu)
            contextmenu.addSeparator()
            m = contextmenu.addMenu(_('List Optio&ns'))
        else:
            m = contextmenu
        m.addAction(self._actionManifestMode)
        m.addSeparator()
        m.addActions(self._fileStatusFilter.actions())
        m.addSeparator()
        m.addActions(self._parentToggleGroup.actions())
        m.addSeparator()
        m.addAction(self._actionFlatFileList)

        contextmenu.setAttribute(Qt.WA_DeleteOnClose)
        contextmenu.popup(self.filelist.viewport().mapToGlobal(point))

    def _setupFileMenu(self, contextmenu):
        index = self.filelist.currentIndex()
        model = self.filelist.model()

        # Subrepos and regular items have different context menus
        if model.subrepoType(index):
            actnames = _fileactionsbytype['subrepo']
        elif model.isDir(index):
            actnames = _fileactionsbytype['dir']
        else:
            actnames = _fileactionsbytype['file']
        for act in actnames + [None, 'customToolsMenu']:
            if act:
                contextmenu.addAction(self._fileactions.action(act))
            else:
                contextmenu.addSeparator()

    @pyqtSlot()
    def updateItemFileActions(self):
        model = self.filelist.model()
        selmodel = self.filelist.selectionModel()
        selfds = map(model.fileData, selmodel.selectedIndexes())
        self._fileactions.setFileDataList(selfds)

    @pyqtSlot()
    def _applyFileNameFilter(self):
        model = self.filelist.model()
        match = self.filefilter.text()
        if model is not None:
            model.setNameFilter(match)
            self._filelistpaletteswitcher.enablefilterpalette(bool(match))
            self._expandShortFileList()

    def isManifestMode(self):
        """In manifest mode, clean files are listed and removed are hidden
        by default.  Also, the view is forcibly switched to the tree mode."""
        return self._actionManifestMode.isChecked()

    def setManifestMode(self, manifestmode):
        self._actionManifestMode.setChecked(manifestmode)
        self._applyManifestMode(manifestmode)

    @pyqtSlot(bool)
    def _applyManifestMode(self, manifestmode):
        self._fileStatusFilter.setChecked('C', manifestmode)
        self._fileStatusFilter.setChecked('R', not manifestmode)
        self._actionFlatFileList.setVisible(not manifestmode)
        self._applyFlatFileList(not manifestmode and self.isFlatFileList())

        # manifest should show clean files, so only p1/p2 toggles are valid
        parentactions = self._parentToggleGroup.actions()
        parentactions[0].setEnabled(not manifestmode)
        parentactions[int(manifestmode)].trigger()

    def isFlatFileList(self):
        return self._actionFlatFileList.isChecked()

    def setFlatFileList(self, flat):
        self._actionFlatFileList.setChecked(flat)
        if not self.isManifestMode():
            self._applyFlatFileList(flat)

    @pyqtSlot(bool)
    def _applyFlatFileList(self, flat):
        view = self.filelist
        model = view.model()
        model.setFlat(flat)
        view.setRootIsDecorated(not flat)
        if flat:
            view.setTextElideMode(Qt.ElideLeft)
        else:
            view.setTextElideMode(Qt.ElideRight)
        self._expandShortFileList()

    def fileStatusFilter(self):
        return self._fileStatusFilter.status()

    def setFileStatusFilter(self, statustext):
        self._fileStatusFilter.setStatus(statustext)

    @pyqtSlot(str)
    def _applyFileStatusFilter(self, statustext):
        model = self.filelist.model()
        model.setStatusFilter(statustext)
        self._expandShortFileList()

    @pyqtSlot()
    def _expandShortFileList(self):
        if self.isManifestMode():
            # because manifest will contain large tree of files
            return
        self.filelist.expandAll()

    def saveSettings(self, s):
        wb = "RevDetailsWidget/"
        for n in self.splitternames:
            s.setValue(wb + n, getattr(self, n).saveState())
        s.setValue(wb + 'flatfilelist', self.isFlatFileList())
        s.setValue(wb + 'revpanel.expanded', self.revpanel.is_expanded())
        self.fileview.saveSettings(s, 'revpanel/fileview')

    def loadSettings(self, s):
        wb = "RevDetailsWidget/"
        for n in self.splitternames:
            getattr(self, n).restoreState(s.value(wb + n).toByteArray())
        self.setFlatFileList(s.value(wb + 'flatfilelist', True).toBool())
        expanded = s.value(wb + 'revpanel.expanded', False).toBool()
        self.revpanel.set_expanded(expanded)
        self.fileview.loadSettings(s, 'revpanel/fileview')


class RevDetailsDialog(QDialog):
    'Standalone revision details tool, a wrapper for RevDetailsWidget'

    def __init__(self, repoagent, rev='.', parent=None):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowIcon(qtlib.geticon('hg-log'))
        self._repoagent = repoagent

        layout = QVBoxLayout()
        layout.setMargin(0)
        self.setLayout(layout)

        toplayout = QVBoxLayout()
        toplayout.setContentsMargins(5, 5, 5, 0)
        layout.addLayout(toplayout)

        revdetails = RevDetailsWidget(repoagent, parent, rev=rev)
        toplayout.addWidget(revdetails, 1)

        self.statusbar = cmdui.ThgStatusBar(self)
        revdetails.showMessage.connect(self.statusbar.showMessage)
        revdetails.linkActivated.connect(self.linkActivated)

        layout.addWidget(self.statusbar)

        s = QSettings()
        self.restoreGeometry(s.value('revdetails/geom').toByteArray())
        revdetails.loadSettings(s)
        repoagent.repositoryChanged.connect(self.refresh)

        self.revdetails = revdetails
        self.setRev(rev)
        qtlib.newshortcutsforstdkey(QKeySequence.Refresh, self, self.refresh)

    def setRev(self, rev):
        self.revdetails.onRevisionSelected(rev)
        self.refresh()

    def filePath(self):
        return self.revdetails.filePath()

    def setFilePath(self, path):
        self.revdetails.setFilePath(path)

    def showLine(self, line):
        self.revdetails.showLine(line)

    def setSearchPattern(self, text):
        self.revdetails.setSearchPattern(text)

    def isManifestMode(self):
        return self.revdetails.isManifestMode()

    def setManifestMode(self, manifestmode):
        self.revdetails.setManifestMode(manifestmode)

    def isFlatFileList(self):
        return self.revdetails.isFlatFileList()

    def setFlatFileList(self, flat):
        self.revdetails.setFlatFileList(flat)

    def fileStatusFilter(self):
        return self.revdetails.fileStatusFilter()

    def setFileStatusFilter(self, statustext):
        self.revdetails.setFileStatusFilter(statustext)

    def linkActivated(self, link):
        link = hglib.fromunicode(link)
        link = link.split(':', 1)
        if len(link) == 1:
            linktype = 'cset:'
            linktarget = link[0]
        else:
            linktype = link[0]
            linktarget = link[1]

        if linktype == 'cset':
            self.setRev(linktarget)
        elif linktype == 'repo':
            try:
                linkpath, rev = linktarget.split('?', 1)
            except ValueError:
                linkpath = linktarget
                rev = None
            # TODO: implement by using signal-slot if possible
            from tortoisehg.hgqt import run
            run.qtrun.showRepoInWorkbench(hglib.tounicode(linkpath), rev)

    @pyqtSlot()
    def refresh(self):
        rev = revnum = self.revdetails.ctx.rev()
        if rev is None:
            revstr = _('Working Directory')
        else:
            hash = self.revdetails.ctx.hex()[:12]
            revstr = '@%s: %s' % (str(revnum), hash)
        self.setWindowTitle(_('%s - Revision Details (%s)')
                            % (self._repoagent.displayName(), revstr))
        self.revdetails.reload()

    def done(self, ret):
        s = QSettings()
        s.setValue('revdetails/geom', self.saveGeometry())
        super(RevDetailsDialog, self).done(ret)


def createManifestDialog(repoagent, rev=None, parent=None):
    dlg = RevDetailsDialog(repoagent, rev, parent)
    dlg.setManifestMode(True)
    return dlg
