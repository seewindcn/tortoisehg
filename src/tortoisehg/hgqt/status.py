# status.py - working copy browser
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from mercurial import hg, util, error, context, scmutil

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, filectxactions, filedata, fileview

from PyQt4.QtCore import *
from PyQt4.QtGui import *

# This widget can be used as the basis of the commit tool or any other
# working copy browser.

# Technical Debt
#  We need a real icon set for file status types
#  Thread rowSelected, connect to an external progress bar
#  Chunk selection, tri-state checkboxes for commit
# Maybe, Maybe Not
#  Investigate folding/nesting of files

COL_PATH = 0
COL_STATUS = 1
COL_MERGE_STATE = 2
COL_PATH_DISPLAY = 3
COL_EXTENSION = 4
COL_SIZE = 5

_colors = {}

class StatusWidget(QWidget):
    '''Working copy status widget
       SIGNALS:
       progress()                   - for progress bar
       showMessage(str)             - for status bar
       titleTextChanged(str)        - for window title
    '''
    progress = pyqtSignal(str, object, str, str, object)
    titleTextChanged = pyqtSignal(str)
    linkActivated = pyqtSignal(str)
    showMessage = pyqtSignal(str)
    fileDisplayed = pyqtSignal(str, str)
    grepRequested = pyqtSignal(str, dict)
    runCustomCommandRequested = pyqtSignal(str, list)

    def __init__(self, repoagent, pats, opts, parent=None, checkable=True,
                 defcheck='commit'):
        QWidget.__init__(self, parent)

        self.opts = dict(modified=True, added=True, removed=True, deleted=True,
                         unknown=True, clean=False, ignored=False, subrepo=True)
        self.opts.update(opts)
        self._repoagent = repoagent
        self.pats = pats
        self.checkable = checkable
        self.defcheck = defcheck
        self.pctx = None
        self.savechecks = True
        self.refthread = None
        self.refreshWctxLater = QTimer(self, interval=10, singleShot=True)
        self.refreshWctxLater.timeout.connect(self.refreshWctx)
        self.partials = {}

        # determine the user configured status colors
        # (in the future, we could support full rich-text tags)
        labels = [(stat, val.uilabel) for stat, val in statusTypes.items()]
        labels.extend([('r', 'resolve.resolved'), ('u', 'resolve.unresolved')])
        for stat, label in labels:
            effect = qtlib.geteffect(label)
            for e in effect.split(';'):
                if e.startswith('color:'):
                    _colors[stat] = QColor(e[7:])
                    break

        SP = QSizePolicy

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        layout = QVBoxLayout()
        layout.setMargin(0)
        layout.addWidget(split)
        self.setLayout(layout)

        vbox = QVBoxLayout()
        vbox.setMargin(0)
        frame = QFrame(split)
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(0)
        frame.setSizePolicy(sp)
        frame.setLayout(vbox)
        hbox = QHBoxLayout()
        hbox.setMargin(4)
        hbox.setContentsMargins(0, 0, 0, 0)
        self.refreshBtn = tb = QToolButton()
        tb.setToolTip(_('Refresh file list'))
        tb.setIcon(qtlib.geticon('view-refresh'))
        tb.clicked.connect(self.refreshWctx)
        le = QLineEdit()
        if hasattr(le, 'setPlaceholderText'): # Qt >= 4.7
            le.setPlaceholderText(_('### filter text ###'))
        else:
            lbl = QLabel(_('Filter:'))
            hbox.addWidget(lbl)

        st = ''
        for s in statusTypes:
            val = statusTypes[s]
            if self.opts[val.name]:
                st = st + s
        self.statusfilter = StatusFilterActionGroup(
            statustext=st, types=StatusType.preferredOrder)

        if self.checkable:
            self.checkAllTT = _('Check all files')
            self.checkNoneTT = _('Uncheck all files')
            self.checkAllNoneBtn = QCheckBox()
            self.checkAllNoneBtn.setToolTip(self.checkAllTT)
            self.checkAllNoneBtn.clicked.connect(self.checkAllNone)

        self.filelistToolbar = QToolBar(_('Status File List Toolbar'))
        self.filelistToolbar.setIconSize(qtlib.smallIconSize())
        self.filelistToolbar.setStyleSheet(qtlib.tbstylesheet)
        hbox.addWidget(self.filelistToolbar)
        if self.checkable:
            self.filelistToolbar.addWidget(qtlib.Spacer(3, 2))
            self.filelistToolbar.addWidget(self.checkAllNoneBtn)
            self.filelistToolbar.addSeparator()
        self.filelistToolbar.addWidget(le)
        self.filelistToolbar.addSeparator()
        self.filelistToolbar.addWidget(
            createStatusFilterMenuButton(self.statusfilter, self))
        self.filelistToolbar.addSeparator()
        self.filelistToolbar.addWidget(self.refreshBtn)
        self._fileactions = filectxactions.WctxActions(self._repoagent, self)
        self._fileactions.setupCustomToolsMenu('workbench.commit.custom-menu')
        self._fileactions.linkActivated.connect(self.linkActivated)
        self._fileactions.refreshNeeded.connect(self.refreshWctx)
        self._fileactions.runCustomCommandRequested.connect(
            self.runCustomCommandRequested)
        self.addActions(self._fileactions.actions())
        tv = WctxFileTree(self)
        vbox.addLayout(hbox)
        vbox.addWidget(tv)
        split.addWidget(frame)

        self.clearPatternBtn = QPushButton(_('Remove filter, show root'))
        vbox.addWidget(self.clearPatternBtn)
        self.clearPatternBtn.clicked.connect(self.clearPattern)
        self.clearPatternBtn.setAutoDefault(False)
        self.clearPatternBtn.setVisible(bool(self.pats))

        tv.setAllColumnsShowFocus(True)
        tv.setContextMenuPolicy(Qt.CustomContextMenu)
        tv.setDragDropMode(QTreeView.DragOnly)
        tv.setItemsExpandable(False)
        tv.setRootIsDecorated(False)
        tv.setSelectionMode(QTreeView.ExtendedSelection)
        tv.setTextElideMode(Qt.ElideLeft)
        tv.sortByColumn(COL_STATUS, Qt.AscendingOrder)
        tv.doubleClicked.connect(self.onRowDoubleClicked)
        tv.customContextMenuRequested.connect(self.onMenuRequest)
        le.textEdited.connect(self.setFilter)

        self.statusfilter.statusChanged.connect(self.setStatusFilter)

        self.tv = tv
        self.le = le
        self._tvpaletteswitcher = qtlib.PaletteSwitcher(tv)

        self._togglefileshortcut = a = QShortcut(Qt.Key_Space, tv)
        a.setContext(Qt.WidgetShortcut)
        a.setEnabled(False)
        a.activated.connect(self._toggleSelectedFiles)

        # Diff panel side of splitter
        vbox = QVBoxLayout()
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)
        docf = QFrame(split)
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(1)
        sp.setVerticalStretch(0)
        docf.setSizePolicy(sp)
        docf.setLayout(vbox)
        self.docf = docf

        self.fileview = fileview.HgFileView(self._repoagent, self)
        self.fileview.setShelveButtonVisible(True)
        self.fileview.showMessage.connect(self.showMessage)
        self.fileview.linkActivated.connect(self.linkActivated)
        self.fileview.fileDisplayed.connect(self.fileDisplayed)
        self.fileview.shelveToolExited.connect(self.refreshWctx)
        self.fileview.chunkSelectionChanged.connect(self.chunkSelectionChanged)
        self.fileview.grepRequested.connect(self.grepRequested)
        self.fileview.setMinimumSize(QSize(16, 16))
        vbox.addWidget(self.fileview, 1)

        self.split = split
        self.diffvbox = vbox

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def __get_defcheck(self):
        if self._defcheck is None:
            return 'MAR!S'
        return self._defcheck

    def __set_defcheck(self, newdefcheck):
        if newdefcheck.lower() == 'amend':
            newdefcheck = 'MAS'
        elif newdefcheck.lower() in ('commit', 'qnew', 'qrefresh'):
            newdefcheck = 'MAR!S'
        self._defcheck = newdefcheck

    defcheck = property(__get_defcheck, __set_defcheck)

    @pyqtSlot()
    def checkAllNone(self):
        state = self.checkAllNoneBtn.checkState()
        if state == Qt.Checked:
            self.checkAll()
            self.checkAllNoneBtn.setToolTip(self.checkNoneTT)
        else:
            if state == Qt.Unchecked:
                self.checkNone()
            self.checkAllNoneBtn.setToolTip(self.checkAllTT)
        if state != Qt.PartiallyChecked:
            self.checkAllNoneBtn.setTristate(False)

    def getTitle(self):
        name = self._repoagent.displayName()
        if self.pats:
            return _('%s - status (selection filtered)') % name
        else:
            return _('%s - status') % name

    def loadSettings(self, qs, prefix):
        self.fileview.loadSettings(qs, prefix+'/fileview')
        self.split.restoreState(qs.value(prefix+'/state').toByteArray())

    def saveSettings(self, qs, prefix):
        self.fileview.saveSettings(qs, prefix+'/fileview')
        qs.setValue(prefix+'/state', self.split.saveState())

    def _updatePartials(self, fd):
        # remove files from the partials dictionary if they are not partial
        # selections, in order to simplify refresh.
        dels = []
        for file, oldchanges in self.partials.iteritems():
            assert file in self.tv.model().checked
            if oldchanges.excludecount == 0:
                self.tv.model().checked[file] = True
                dels.append(file)
            elif oldchanges.excludecount == len(oldchanges.hunks):
                self.tv.model().checked[file] = False
                dels.append(file)
        for file in dels:
            del self.partials[file]

        wfile = hglib.fromunicode(fd.filePath())
        changes = fd.changes
        if changes is None:
            if wfile in self.partials:
                del self.partials[wfile]
                self.chunkSelectionChanged()
            return

        if wfile in self.partials:
            # merge selection state from old hunk list to new hunk list
            oldhunks = self.partials[wfile].hunks
            oldstates = dict([(c.fromline, c.excluded) for c in oldhunks])
            for chunk in changes.hunks:
                if chunk.fromline in oldstates:
                    fd.setChunkExcluded(chunk, oldstates[chunk.fromline])
        else:
            # the file was not in the partials dictionary, so it is either
            # checked (all changes enabled) or unchecked (all changes
            # excluded).
            if wfile not in self.getChecked():
                for chunk in changes.hunks:
                    fd.setChunkExcluded(chunk, True)
        self.chunkSelectionChanged()
        self.partials[wfile] = changes

    @pyqtSlot()
    def chunkSelectionChanged(self):
        'checkbox state has changed via chunk selection'
        # inform filelist view that the file selection state may have changed
        model = self.tv.model()
        if model:
            model.layoutChanged.emit()
            model.checkCountChanged.emit()

    @pyqtSlot(QPoint)
    def onMenuRequest(self, point):
        menu = QMenu(self)
        selmodel = self.tv.selectionModel()
        if selmodel and selmodel.hasSelection():
            self._setupFileMenu(menu)
            menu.addSeparator()
            optmenu = menu.addMenu(_('List Optio&ns'))
        else:
            optmenu = menu
        optmenu.addActions(self.statusfilter.actions())

        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(self.tv.viewport().mapToGlobal(point))

    def _setupFileMenu(self, menu):
        self._addFileActionsToMenu(menu, [
            'visualDiffFile', 'visualDiffLocalFile', 'copyPatch',
            'editLocalFile', 'openLocalFile', 'exploreLocalFile', 'editRejects',
            None, 'openSubrepo', 'explore', 'terminal', None, 'copyPath',
            'editMissingFile', None, 'revertWorkingFile', None,
            'navigateFileLog', None, 'forgetFile', 'addFile', 'addLargefile',
            'guessRename', 'editHgignore', 'removeFile', 'purgeFile', None,
            'markFileAsUnresolved', 'markFileAsResolved'])
        if self.checkable:
            menu.addSeparator()
            # no &-shortcut because check/uncheck can be done by space key
            menu.addAction(_('Check'), self._checkSelectedFiles)
            menu.addAction(_('Uncheck'), self._uncheckSelectedFiles)
        self._addFileActionsToMenu(menu, [
            'editOtherFile', None, 'copyFile', 'renameFile', None,
            'customToolsMenu', None, 'renameFileMenu', None, 'remergeFile',
            None, 'remergeFileMenu'])

    def _addFileActionsToMenu(self, menu, actnames):
        for name in actnames:
            if not name:
                menu.addSeparator()
                continue
            action = self._fileactions.action(name)
            if action.isEnabled():
                menu.addAction(action)

    def setPatchContext(self, pctx):
        if pctx != self.pctx:
            # clear out the current checked state on next refreshWctx()
            self.savechecks = False
        self.pctx = pctx

    @pyqtSlot()
    def refreshWctx(self):
        if self.refthread:
            self.refreshWctxLater.start()
            return
        self.refreshWctxLater.stop()
        self.fileview.clearDisplay()

        # store selected paths or current path
        model = self.tv.model()
        if model and model.rowCount(QModelIndex()):
            smodel = self.tv.selectionModel()
            curidx = smodel.currentIndex()
            if curidx.isValid():
                curpath = model.getRow(curidx)[COL_PATH]
            else:
                curpath = None
            spaths = [model.getRow(i)[COL_PATH] for i in smodel.selectedRows()]
            self.reselection = spaths, curpath
        else:
            self.reselection = None

        if self.checkable:
            self.checkAllNoneBtn.setEnabled(False)
        self.refreshBtn.setEnabled(False)
        self.progress.emit(*cmdui.startProgress(_('Refresh'), _('status')))
        self.refthread = StatusThread(self.repo, self.pctx, self.pats, self.opts)
        self.refthread.finished.connect(self.reloadComplete)
        self.refthread.showMessage.connect(self.reloadFailed)
        self.refthread.start()

    @pyqtSlot()
    def reloadComplete(self):
        self.refthread.wait()
        if self.checkable:
            self.checkAllNoneBtn.setEnabled(True)
        self.refreshBtn.setEnabled(True)
        self.progress.emit(*cmdui.stopProgress(_('Refresh')))
        if self.refthread.wctx is not None:
            assert self.refthread.wstatus is not None
            self.updateModel(self.refthread.wctx, self.refthread.wstatus,
                             self.refthread.patchecked)
        self.refthread = None
        if len(self.repo[None].parents()) > 1:
            # nuke partial selections if wctx has a merge in-progress
            self.partials = {}
        match = self.le.text()
        if match:
            self.setFilter(match)

    # better to handle error in reloadComplete in place of separate signal?
    @pyqtSlot(str)
    def reloadFailed(self, msg):
        qtlib.ErrorMsgBox(_('Failed to refresh'), msg, parent=self)

    def isRefreshingWctx(self):
        return bool(self.refthread)

    def canExit(self):
        return not self.isRefreshingWctx()

    def updateModel(self, wctx, wstatus, patchecked):
        self.tv.setSortingEnabled(False)
        if self.tv.model():
            checked = self.tv.model().getChecked()
        else:
            checked = patchecked
            if self.pats and not checked:
                qtlib.WarningMsgBox(_('No appropriate files'),
                                    _('No files found for this operation'),
                                    parent=self)
        ms = hglib.readmergestate(self.repo)
        tm = WctxModel(self._repoagent, wctx, wstatus, ms, self.pctx,
                       self.savechecks, self.opts, checked, self,
                       checkable=self.checkable, defcheck=self.defcheck)
        if self.checkable:
            tm.checkToggled.connect(self.checkToggled)
            tm.checkCountChanged.connect(self.updateCheckCount)
        self.savechecks = True

        oldtm = self.tv.model()
        self.tv.setModel(tm)
        if oldtm:
            oldtm.deleteLater()
        self.tv.setSortingEnabled(True)
        self.tv.setColumnHidden(COL_PATH, bool(wctx.p2()) or not self.checkable)
        self.tv.setColumnHidden(COL_MERGE_STATE, not tm.anyMerge())
        if self.checkable:
            self.updateCheckCount()

        # remove non-existent file from partials table because model changed
        for file in self.partials.keys():
            if file not in tm.checked:
                del self.partials[file]

        for col in (COL_PATH, COL_STATUS, COL_MERGE_STATE):
            w = self.tv.sizeHintForColumn(col)
            self.tv.setColumnWidth(col, w)
        for col in (COL_PATH_DISPLAY, COL_EXTENSION, COL_SIZE):
            self.tv.resizeColumnToContents(col)

        # reset selection, or select first row
        curidx = tm.index(0, 0)
        selmodel = self.tv.selectionModel()
        flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
        if self.reselection:
            selected, current = self.reselection
            for i, row in enumerate(tm.getAllRows()):
                if row[COL_PATH] in selected:
                    selmodel.select(tm.index(i, 0), flags)
                if row[COL_PATH] == current:
                    curidx = tm.index(i, 0)
        else:
            selmodel.select(curidx, flags)
        selmodel.currentChanged.connect(self.onCurrentChange)
        selmodel.selectionChanged.connect(self.onSelectionChange)
        if curidx and curidx.isValid():
            selmodel.setCurrentIndex(curidx, QItemSelectionModel.Current)
        self.onSelectionChange()

        self._togglefileshortcut.setEnabled(True)

    # Disabled decorator because of bug in older PyQt releases
    #@pyqtSlot(QModelIndex)
    def onRowDoubleClicked(self, index):
        'tree view emitted a doubleClicked signal, index guarunteed valid'
        fd = self.tv.model().fileData(index)
        if fd.subrepoType():
            self._fileactions.openSubrepo()
        elif fd.mergeStatus() == 'U':
            self._fileactions.remergeFile()
        elif fd.fileStatus() in set('MAR!'):
            self._fileactions.visualDiffFile()
        elif fd.fileStatus() in set('C?'):
            self._fileactions.editLocalFile()

    @pyqtSlot(str)
    def setStatusFilter(self, status):
        status = str(status)
        for s in statusTypes:
            val = statusTypes[s]
            self.opts[val.name] = s in status
        self.refreshWctx()

    @pyqtSlot(str)
    def setFilter(self, match):
        model = self.tv.model()
        if model:
            model.setFilter(match)
            self._tvpaletteswitcher.enablefilterpalette(bool(match))

    @pyqtSlot()
    def clearPattern(self):
        self.pats = []
        self.refreshWctx()
        self.clearPatternBtn.setVisible(False)
        self.titleTextChanged.emit(self.getTitle())

    @pyqtSlot()
    def updateCheckCount(self):
        'user has toggled one or more checkboxes, update counts and checkall'
        model = self.tv.model()
        if model:
            model.checkCount = len(self.getChecked())
            if model.checkCount == 0:
                state = Qt.Unchecked
            elif model.checkCount == len(model.rows):
                state = Qt.Checked
            else:
                state = Qt.PartiallyChecked
            self.checkAllNoneBtn.setTristate(state == Qt.PartiallyChecked)
            self.checkAllNoneBtn.setCheckState(state)

    @pyqtSlot(str, bool)
    def checkToggled(self, wfile, checked):
        'user has toggled a checkbox, update partial chunk selection status'
        wfile = hglib.fromunicode(wfile)
        if wfile in self.partials:
            del self.partials[wfile]
            if wfile == hglib.fromunicode(self.fileview.filePath()):
                self.onCurrentChange(self.tv.currentIndex())

    def checkAll(self):
        model = self.tv.model()
        if model:
            model.checkAll(True)

    def checkNone(self):
        model = self.tv.model()
        if model:
            model.checkAll(False)

    def getChecked(self, types=None):
        model = self.tv.model()
        if model:
            checked = model.getChecked()
            if types is None:
                files = []
                for f, v in checked.iteritems():
                    if f in self.partials:
                        changes = self.partials[f]
                        if changes.excludecount < len(changes.hunks):
                            files.append(f)
                    elif v:
                        files.append(f)
                return files
            else:
                files = []
                for row in model.getAllRows():
                    path, status, mst, upath, ext, sz = row
                    if status in types:
                        if path in self.partials:
                            changes = self.partials[path]
                            if changes.excludecount < len(changes.hunks):
                                files.append(path)
                        elif checked[path]:
                            files.append(path)
                return files
        else:
            return []

    @pyqtSlot()
    def onSelectionChange(self):
        model = self.tv.model()
        selmodel = self.tv.selectionModel()
        selfds = map(model.fileData, selmodel.selectedRows())
        self._fileactions.setFileDataList(selfds)

    # Disabled decorator because of bug in older PyQt releases
    #@pyqtSlot(QModelIndex)
    def onCurrentChange(self, index):
        'Connected to treeview "currentChanged" signal'
        changeselect = self.fileview.isChangeSelectionEnabled()
        model = self.tv.model()
        fd = model.fileData(index)
        fd.load(changeselect)
        if changeselect and not fd.isNull() and not fd.subrepoType():
            self._updatePartials(fd)
        self.fileview.display(fd)

    def _setCheckStateOfSelectedFiles(self, value):
        model = self.tv.model()
        selmodel = self.tv.selectionModel()
        for index in selmodel.selectedRows(COL_PATH):
            model.setData(index, value, Qt.CheckStateRole)

    @pyqtSlot()
    def _checkSelectedFiles(self):
        self._setCheckStateOfSelectedFiles(Qt.Checked)

    @pyqtSlot()
    def _uncheckSelectedFiles(self):
        self._setCheckStateOfSelectedFiles(Qt.Unchecked)

    @pyqtSlot()
    def _toggleSelectedFiles(self):
        model = self.tv.model()
        selmodel = self.tv.selectionModel()
        for index in selmodel.selectedRows(COL_PATH):
            if model.data(index, Qt.CheckStateRole) == Qt.Checked:
                newvalue = Qt.Unchecked
            else:
                newvalue = Qt.Checked
            model.setData(index, newvalue, Qt.CheckStateRole)


class StatusThread(QThread):
    '''Background thread for generating a workingctx'''

    showMessage = pyqtSignal(str)

    def __init__(self, repo, pctx, pats, opts, parent=None):
        super(StatusThread, self).__init__()
        self.repo = hg.repository(repo.ui, repo.root)
        self.pctx = pctx
        self.pats = pats
        self.opts = opts
        self.wctx = None
        self.wstatus = None
        self.patchecked = {}

    def run(self):
        self.repo.dirstate.invalidate()
        extract = lambda x, y: dict(zip(x, map(y.get, x)))
        stopts = extract(('unknown', 'ignored', 'clean'), self.opts)
        patchecked = {}
        try:
            if self.pats:
                if self.opts.get('checkall'):
                    # quickop sets this flag to pre-check even !?IC files
                    precheckfn = lambda x: True
                else:
                    # status and commit only pre-check MAR files
                    precheckfn = lambda x: x < 4
                m = scmutil.match(self.repo[None], self.pats)
                self.repo.lfstatus = True
                status = self.repo.status(match=m, **stopts)
                self.repo.lfstatus = False
                # Record all matched files as initially checked
                for i, stat in enumerate(StatusType.preferredOrder):
                    if stat == 'S':
                        continue
                    val = statusTypes[stat]
                    if self.opts[val.name]:
                        d = dict([(fn, precheckfn(i)) for fn in status[i]])
                        patchecked.update(d)
                wctx = context.workingctx(self.repo, changes=status)
                self.patchecked = patchecked
            elif self.pctx:
                self.repo.lfstatus = True
                status = self.repo.status(node1=self.pctx.p1().node(), **stopts)
                self.repo.lfstatus = False
                wctx = context.workingctx(self.repo, changes=status)
            else:
                self.repo.lfstatus = True
                status = self.repo.status(**stopts)
                self.repo.lfstatus = False
                wctx = context.workingctx(self.repo, changes=status)
            self.wctx = wctx
            self.wstatus = status

            wctx.dirtySubrepos = []
            for s in wctx.substate:
                if wctx.sub(s).dirty():
                    wctx.dirtySubrepos.append(s)
        except EnvironmentError, e:
            self.showMessage.emit(hglib.tounicode(str(e)))
        except (error.LookupError, error.RepoError, error.ConfigError), e:
            self.showMessage.emit(hglib.tounicode(str(e)))
        except util.Abort, e:
            if e.hint:
                err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                            hglib.tounicode(e.hint))
            else:
                err = hglib.tounicode(str(e))
            self.showMessage.emit(err)


class WctxFileTree(QTreeView):

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        # don't update horizontal position by selection change
        orighoriz = self.horizontalScrollBar().value()
        super(WctxFileTree, self).scrollTo(index, hint)
        self.horizontalScrollBar().setValue(orighoriz)


class WctxModel(QAbstractTableModel):
    checkCountChanged = pyqtSignal()
    checkToggled = pyqtSignal(str, bool)

    def __init__(self, repoagent, wctx, wstatus, ms, pctx, savechecks, opts,
                 checked, parent, checkable=True, defcheck='MAR!S'):
        QAbstractTableModel.__init__(self, parent)
        self._repoagent = repoagent
        self._pctx = pctx
        self.partials = parent.partials
        self.checkCount = 0
        rows = []
        nchecked = {}
        excludes = [f.strip() for f in opts.get('ciexclude', '').split(',')]
        def mkrow(fname, st):
            ext, sizek = '', ''
            try:
                mst = fname in ms and ms[fname].upper() or ""
                name, ext = os.path.splitext(fname)
                sizebytes = wctx[fname].size()
                sizek = (sizebytes + 1023) // 1024
            except EnvironmentError:
                pass
            return [fname, st, mst, hglib.tounicode(fname), ext[1:], sizek]
        if not savechecks:
            checked = {}
        if pctx:
            # Currently, having a patch context means it's a qrefresh, so only
            # auto-check files in pctx.files()
            pctxfiles = pctx.files()
            pctxmatch = lambda f: f in pctxfiles
        else:
            pctxmatch = lambda f: True
        if opts['modified']:
            for m in wstatus.modified:
                nchecked[m] = checked.get(m, 'M' in defcheck and
                                          m not in excludes and pctxmatch(m))
                rows.append(mkrow(m, 'M'))
        if opts['added']:
            for a in wstatus.added:
                nchecked[a] = checked.get(a, 'A' in defcheck and
                                          a not in excludes and pctxmatch(a))
                rows.append(mkrow(a, 'A'))
        if opts['removed']:
            for r in wstatus.removed:
                nchecked[r] = checked.get(r, 'R' in defcheck and
                                          r not in excludes and pctxmatch(r))
                rows.append(mkrow(r, 'R'))
        if opts['deleted']:
            for d in wstatus.deleted:
                nchecked[d] = checked.get(d, 'D' in defcheck and
                                          d not in excludes and pctxmatch(d))
                rows.append(mkrow(d, '!'))
        if opts['unknown']:
            for u in wstatus.unknown or []:
                nchecked[u] = checked.get(u, '?' in defcheck)
                rows.append(mkrow(u, '?'))
        if opts['ignored']:
            for i in wstatus.ignored or []:
                nchecked[i] = checked.get(i, 'I' in defcheck)
                rows.append(mkrow(i, 'I'))
        if opts['clean']:
            for c in wstatus.clean or []:
                nchecked[c] = checked.get(c, 'C' in defcheck)
                rows.append(mkrow(c, 'C'))
        if opts['subrepo']:
            for s in wctx.dirtySubrepos:
                nchecked[s] = checked.get(s, 'S' in defcheck)
                rows.append(mkrow(s, 'S'))
        # include clean unresolved files
        for f in ms:
            if ms[f] == 'u' and f not in nchecked:
                nchecked[f] = checked.get(f, True)
                rows.append(mkrow(f, 'C'))
        self.headers = ('*', _('Stat'), _('M'), _('Filename'),
                        _('Type'), _('Size (KB)'))
        self.checked = nchecked
        self.unfiltered = rows
        self.rows = rows
        self.checkable = checkable

    def rowCount(self, parent):
        if parent.isValid():
            return 0 # no child
        return len(self.rows)

    def checkAll(self, state):
        for data in self.rows:
            self.checked[data[0]] = state
            self.checkToggled.emit(data[3], state)
        self.layoutChanged.emit()
        self.checkCountChanged.emit()

    def columnCount(self, parent):
        if parent.isValid():
            return 0 # no child
        return len(self.headers)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()

        path, status, mst, upath, ext, sz = self.rows[index.row()]
        if index.column() == COL_PATH:
            if role == Qt.CheckStateRole and self.checkable:
                if path in self.partials:
                    changes = self.partials[path]
                    if changes.excludecount == 0:
                        return Qt.Checked
                    elif changes.excludecount == len(changes.hunks):
                        return Qt.Unchecked
                    else:
                        return Qt.PartiallyChecked
                if self.checked[path]:
                    return Qt.Checked
                else:
                    return Qt.Unchecked
            elif role == Qt.DisplayRole:
                return QVariant("")
            elif role == Qt.ToolTipRole:
                return QVariant(_('Checked count: %d') % self.checkCount)
        elif role == Qt.DisplayRole:
            return QVariant(self.rows[index.row()][index.column()])
        elif role == Qt.TextColorRole:
            if mst:
                return _colors.get(mst.lower(), QColor('black'))
            else:
                return _colors.get(status, QColor('black'))
        elif role == Qt.ToolTipRole:
            return QVariant(statusMessage(status, mst, upath))
        '''
        elif role == Qt.DecorationRole and index.column() == COL_STATUS:
            if status in statusTypes:
                ico = QIcon()
                ico.addPixmap(QPixmap('icons/' + statusTypes[status].icon))
                return QVariant(ico)
        '''
        return QVariant()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        if (index.column() == COL_PATH and role == Qt.CheckStateRole
            and self.checkable):
            if self.data(index, role) == value:
                return True
            if value not in (Qt.Checked, Qt.Unchecked):
                # Qt.PartiallyChecked cannot be set explicitly
                return False
            path = self.rows[index.row()][COL_PATH]
            upath = self.rows[index.row()][COL_PATH_DISPLAY]
            self.checked[path] = checked = (value == Qt.Checked)
            self.checkToggled.emit(upath, checked)
            self.checkCountChanged.emit()
            self.dataChanged.emit(index, index)
            return True
        return False

    def headerData(self, col, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()
        else:
            return QVariant(self.headers[col])

    def flags(self, index):
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled
        if index.column() == COL_PATH and self.checkable:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def mimeTypes(self):
        return ['text/uri-list']

    def mimeData(self, indexes):
        repo = self._repoagent.rawRepo()
        urls = []
        for index in indexes:
            if index.column() != 0:
                continue
            path = self.rows[index.row()][COL_PATH]
            urls.append(QUrl.fromLocalFile(hglib.tounicode(repo.wjoin(path))))
        data = QMimeData()
        data.setUrls(urls)
        return data

    # Custom methods

    def anyMerge(self):
        for r in self.rows:
            if r[COL_MERGE_STATE]:
                return True
        return False

    def fileData(self, index):
        """Returns the displayable file data at the given index"""
        repo = self._repoagent.rawRepo()
        if not index.isValid():
            return filedata.createNullData(repo)
        path, status, mst, upath, ext, sz = self.rows[index.row()]
        wfile = util.pconvert(path)
        ctx = repo[None]
        pctx = self._pctx and self._pctx.p1() or ctx.p1()
        if status == 'S':
            return filedata.createSubrepoData(ctx, pctx, wfile)
        else:
            return filedata.createFileData(ctx, pctx, wfile, status, None, mst)

    def getRow(self, index):
        assert index.isValid()
        return self.rows[index.row()]

    def getAllRows(self):
        for row in self.rows:
            yield row

    def sort(self, col, order):
        self.layoutAboutToBeChanged.emit()

        def getStatusRank(value):
            """Helper function used to sort items according to their hg status

            Statuses are ranked in the following order:
                'S','M','A','R','!','?','C','I',''
            """
            sortList = ['S','M','A','R','!','?','C','I','']

            try:
                rank = sortList.index(value)
            except (IndexError, ValueError):
                rank = len(sortList) # Set the lowest rank by default

            return rank

        def getMergeStatusRank(value):
            """Helper function used to sort according to item merge status

            Merge statuses are ranked in the following order:
                'S','U','R',''
            """
            sortList = ['S','U','R','']

            try:
                rank = sortList.index(value)
            except (IndexError, ValueError):
                rank = len(sortList) # Set the lowest rank by default

            return rank

        # We want to sort the list by one of the columns (checked state,
        # mercurial status, file path, file extension, etc)
        # However, for files which have the same status or extension, etc,
        # we want them to be sorted alphabetically (without taking into account
        # the case)
        # Since Python 2.3 the sort function is guaranteed to be stable.
        # Thus we can perform the sort in two passes:
        # 1.- Perform a secondary sort by path
        # 2.- Perform a primary sort by the actual column that we are sorting on

        # Secondary sort:
        self.rows.sort(key=lambda x: x[COL_PATH].lower())

        if col == COL_PATH_DISPLAY:
            # Already sorted!
            pass
        else:
            if order == Qt.DescendingOrder:
                # We want the secondary sort to be by _ascending_ path,
                # even when the primary sort is in descending order
                self.rows.reverse()

            # Now we can perform the primary sort
            if col == COL_PATH:
                c = self.checked
                self.rows.sort(key=lambda x: c[x[col]])
            elif col == COL_STATUS:
                self.rows.sort(key=lambda x: getStatusRank(x[col]))
            elif col == COL_MERGE_STATE:
                self.rows.sort(key=lambda x: getMergeStatusRank(x[col]))
            else:
                self.rows.sort(key=lambda x: x[col])

        if order == Qt.DescendingOrder:
            self.rows.reverse()
        self.layoutChanged.emit()
        self.reset()

    def setFilter(self, match):
        'simple match in filename filter'
        self.layoutAboutToBeChanged.emit()
        self.rows = [r for r in self.unfiltered
                     if unicode(match) in r[COL_PATH_DISPLAY]]
        self.layoutChanged.emit()
        self.reset()

    def getChecked(self):
        assert len(self.checked) == len(self.unfiltered)
        return self.checked.copy()

def statusMessage(status, mst, upath):
    tip = ''
    if status in statusTypes:
        upath = "<span style='font-family:Courier'>%s </span>" % upath
        tip = statusTypes[status].desc % upath
        if mst == 'R':
            tip += _(', resolved merge')
        elif mst == 'U':
            tip += _(', unresolved merge')
    return tip

class StatusType(object):
    preferredOrder = 'MAR!?ICS'
    def __init__(self, name, icon, desc, uilabel, trname):
        self.name = name
        self.icon = icon
        self.desc = desc
        self.uilabel = uilabel
        self.trname = trname

statusTypes = {
    'M' : StatusType('modified', 'hg-modified', _('%s is modified'),
                     'status.modified', _('modified')),
    'A' : StatusType('added', 'hg-add', _('%s is added'),
                     'status.added', _('added')),
    'R' : StatusType('removed', 'hg-removed', _('%s is removed'),
                     'status.removed', _('removed')),
    '?' : StatusType('unknown', '', _('%s is not tracked (unknown)'),
                     'status.unknown', _('unknown')),
    '!' : StatusType('deleted', '',
                     _('%s is deleted by non-hg command, but still tracked'),
                     'status.deleted', _('missing')),
    'I' : StatusType('ignored', '', _('%s is ignored'),
                     'status.ignored', _('ignored')),
    'C' : StatusType('clean', '', _('%s is not modified (clean)'),
                     'status.clean', _('clean')),
    'S' : StatusType('subrepo', 'thg-subrepo', _('%s is a dirty subrepo'),
                     'status.subrepo', _('subrepo')),
}


class StatusFilterActionGroup(QObject):
    """Actions to switch status filter"""

    statusChanged = pyqtSignal(str)

    def __init__(self, statustext, types=None, parent=None):
        super(StatusFilterActionGroup, self).__init__(parent)
        self._TYPES = 'MARSC'
        if types is not None:
            self._TYPES = types

        self._actions = {}
        for c in self._TYPES:
            st = statusTypes[c]
            a = QAction('&%s %s' % (c, st.trname), self)
            a.setCheckable(True)
            a.setChecked(c in statustext)
            a.toggled.connect(self._update)
            self._actions[c] = a

    @pyqtSlot()
    def _update(self):
        self.statusChanged.emit(self.status())

    def actions(self):
        return [self._actions[c] for c in self._TYPES]

    def isChecked(self, c):
        return self._actions[c].isChecked()

    def setChecked(self, c, checked):
        self._actions[c].setChecked(checked)

    def status(self):
        """Return the text for status filter"""
        return ''.join(c for c in self._TYPES
                       if self._actions[c].isChecked())

    @pyqtSlot(str)
    def setStatus(self, text):
        """Set the status text"""
        assert all(c in self._TYPES for c in text)
        for c in self._TYPES:
            self._actions[c].setChecked(c in text)


def createStatusFilterMenuButton(actiongroup, parent=None):
    """Create button with drop-down menu for status filter"""
    button = QToolButton(parent)
    button.setIcon(qtlib.geticon('hg-status'))
    button.setPopupMode(QToolButton.InstantPopup)
    menu = QMenu(button)
    menu.addActions(actiongroup.actions())
    button.setMenu(menu)
    return button


class StatusDialog(QDialog):
    'Standalone status browser'
    def __init__(self, repoagent, pats, opts, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowIcon(qtlib.geticon('hg-status'))
        self._repoagent = repoagent

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        toplayout = QVBoxLayout()
        toplayout.setContentsMargins(10, 10, 10, 0)
        self.stwidget = StatusWidget(repoagent, pats, opts, self,
                                     checkable=False)
        toplayout.addWidget(self.stwidget, 1)
        layout.addLayout(toplayout)

        self.statusbar = cmdui.ThgStatusBar(self)
        layout.addWidget(self.statusbar)
        self.stwidget.showMessage.connect(self.statusbar.showMessage)
        self.stwidget.progress.connect(self.statusbar.progress)
        self.stwidget.titleTextChanged.connect(self.setWindowTitle)
        self.stwidget.linkActivated.connect(self.linkActivated)

        self._subdialogs = qtlib.DialogKeeper(StatusDialog._createSubDialog,
                                              parent=self)

        self.setWindowTitle(self.stwidget.getTitle())
        self.setWindowFlags(Qt.Window)
        self.loadSettings()

        qtlib.newshortcutsforstdkey(QKeySequence.Refresh, self,
                                    self.stwidget.refreshWctx)
        QTimer.singleShot(0, self.stwidget.refreshWctx)

    def linkActivated(self, link):
        link = unicode(link)
        if link.startswith('repo:'):
            self._subdialogs.open(link[len('repo:'):])

    def _createSubDialog(self, uroot):
        repoagent = self._repoagent.subRepoAgent(uroot)
        return StatusDialog(repoagent, [], {}, parent=self)

    def loadSettings(self):
        s = QSettings()
        self.stwidget.loadSettings(s, 'status')
        self.restoreGeometry(s.value('status/geom').toByteArray())

    def saveSettings(self):
        s = QSettings()
        self.stwidget.saveSettings(s, 'status')
        s.setValue('status/geom', self.saveGeometry())

    def accept(self):
        if not self.stwidget.canExit():
            return
        self.saveSettings()
        QDialog.accept(self)

    def reject(self):
        if not self.stwidget.canExit():
            return
        self.saveSettings()
        QDialog.reject(self)
