# reporegistry.py - registry for a user's repositories
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os

from mercurial import commands, hg, ui, util

from tortoisehg.util import hglib, paths
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, repotreemodel, settings

from PyQt4.QtCore import *
from PyQt4.QtGui import *

def settingsfilename():
    """Return path to thg-reporegistry.xml as unicode"""
    s = QSettings()
    dir = os.path.dirname(unicode(s.fileName()))
    return dir + '/' + 'thg-reporegistry.xml'


class RepoTreeView(QTreeView):
    showMessage = pyqtSignal(str)
    openRequested = pyqtSignal(QModelIndex)
    removeRequested = pyqtSignal(QModelIndex)
    dropAccepted = pyqtSignal()

    def __init__(self, parent):
        QTreeView.__init__(self, parent, allColumnsShowFocus=True)
        if qtlib.IS_RETINA:
            self.setIconSize(qtlib.treeviewRetinaIconSize())
        self.msg = ''

        self.setHeaderHidden(True)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)

        # enable drag and drop
        # (see http://doc.qt.nokia.com/4.6/model-view-dnd.html)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setAutoScroll(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        if PYQT_VERSION >= 0x40700:
            self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setEditTriggers(QAbstractItemView.DoubleClicked
                             | QAbstractItemView.EditKeyPressed)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)

    def dragEnterEvent(self, event):
        if event.source() is self:
            # Use the default event handler for internal dragging
            super(RepoTreeView, self).dragEnterEvent(event)
            return

        d = event.mimeData()
        for u in d.urls():
            root = paths.find_root(hglib.fromunicode(u.toLocalFile()))
            if root:
                event.setDropAction(Qt.LinkAction)
                event.accept()
                self.setState(QAbstractItemView.DraggingState)
                break

    def dropLocation(self, event):
        index = self.indexAt(event.pos())

        # Determine where the item was dropped.
        target = index.internalPointer()
        if not target.isRepo():
            group = index
            row = -1
        else:
            indicator = self.dropIndicatorPosition()
            group = index.parent()
            row = index.row()
            if indicator == QAbstractItemView.BelowItem:
                row = index.row() + 1

        return index, group, row

    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        # Make sure that all selected items are of the same type
        if len(indexes) == 0:
            # Nothing to drag!
            return

        # Make sure that all items that we are dragging are of the same type
        firstItem = indexes[0].internalPointer()
        selectionInstanceType = type(firstItem)
        for idx in indexes[1:]:
            if selectionInstanceType != type(idx.internalPointer()):
                # Cannot drag mixed type items
                return

        # Each item type may support different drag & drop actions
        # For instance, suprepo items support Copy actions only
        supportedActions = firstItem.getSupportedDragDropActions()

        super(RepoTreeView, self).startDrag(supportedActions)

    def dropEvent(self, event):
        data = event.mimeData()
        index, group, row = self.dropLocation(event)

        if index:
            m = self.model()
            if event.source() is self:
                # Event is an internal move, so pass it to the model
                col = 0
                if m.dropMimeData(data, event.dropAction(), row, col, group):
                    event.accept()
                    self.dropAccepted.emit()
            else:
                # Event is a drop of an external repo
                accept = False
                for u in data.urls():
                    uroot = paths.find_root(unicode(u.toLocalFile()))
                    if uroot and not m.isKnownRepoRoot(uroot, standalone=True):
                        repoindex = m.addRepo(uroot, row, group)
                        m.loadSubrepos(repoindex)
                        accept = True
                if accept:
                    event.setDropAction(Qt.LinkAction)
                    event.accept()
                    self.dropAccepted.emit()
        self.setAutoScroll(False)
        self.setState(QAbstractItemView.NoState)
        self.viewport().update()
        self.setAutoScroll(True)

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key_Enter, Qt.Key_Return)
            and self.state() != QAbstractItemView.EditingState):
            index = self.currentIndex()
            if index.isValid():
                self.openRequested.emit(index)
                return
        if event.key() == Qt.Key_Delete:
            index = self.currentIndex()
            if index.isValid():
                self.removeRequested.emit(index)
                return
        super(RepoTreeView, self).keyPressEvent(event)

    def mouseMoveEvent(self, event):
        self.msg  = ''
        pos = event.pos()
        idx = self.indexAt(pos)
        if idx.isValid():
            item = idx.internalPointer()
            self.msg  = item.details()
        self.showMessage.emit(self.msg)

        if event.buttons() == Qt.NoButton:
            # Bail out early to avoid tripping over this bug:
            # http://bugreports.qt.nokia.com/browse/QTBUG-10180
            return
        super(RepoTreeView, self).mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self.msg != '':
            self.showMessage.emit('')

    def mouseDoubleClickEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid() and index.internalPointer().isRepo():
            self.openRequested.emit(index)
        else:
            # a double-click on non-repo rows opens an editor
            super(RepoTreeView, self).mouseDoubleClickEvent(event)

    def sizeHint(self):
        size = super(RepoTreeView, self).sizeHint()
        size.setWidth(QFontMetrics(self.font()).width('M') * 15)
        return size

class RepoRegistryView(QDockWidget):

    showMessage = pyqtSignal(str)
    openRepo = pyqtSignal(str, bool)
    removeRepo = pyqtSignal(str)
    cloneRepoRequested = pyqtSignal(str)
    progressReceived = pyqtSignal(str, object, str, str, object)

    def __init__(self, repomanager, parent):
        QDockWidget.__init__(self, parent)

        self._repomanager = repomanager
        repomanager.repositoryOpened.connect(self._addAndScanRepo)
        self.watcher = None
        self._setupSettingActions()

        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable  |
                         QDockWidget.DockWidgetFloatable)
        self.setWindowTitle(_('Repository Registry'))

        mainframe = QFrame()
        mainframe.setLayout(QVBoxLayout())
        self.setWidget(mainframe)
        mainframe.layout().setContentsMargins(0, 0, 0, 0)

        self.contextmenu = QMenu(self)
        self.tview = tv = RepoTreeView(self)
        mainframe.layout().addWidget(tv)

        tv.setIndentation(10)
        tv.setFirstColumnSpanned(0, QModelIndex(), True)
        tv.setColumnHidden(1, True)

        tv.setContextMenuPolicy(Qt.CustomContextMenu)
        tv.customContextMenuRequested.connect(self._onMenuRequested)
        tv.showMessage.connect(self.showMessage)
        tv.openRequested.connect(self._openRepoAt)
        tv.removeRequested.connect(self._removeAt)
        tv.dropAccepted.connect(self.dropAccepted)

        self.createActions()
        self._loadSettings()
        self._updateSettingActions()

        sfile = settingsfilename()
        model = repotreemodel.RepoTreeModel(sfile, repomanager, self,
            showShortPaths=self._isSettingEnabled('showShortPaths'))
        tv.setModel(model)

        # Setup a file system watcher to update the reporegistry
        # anytime it is modified by another thg instance
        # Note that we must make sure that the settings file exists before
        # setting thefile watcher
        if not os.path.exists(sfile):
            if not os.path.exists(os.path.dirname(sfile)):
                os.makedirs(os.path.dirname(sfile))
            tv.model().write(sfile)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.addPath(sfile)
        self._reloadModelTimer = QTimer(self, interval=2000, singleShot=True)
        self._reloadModelTimer.timeout.connect(self.reloadModel)
        self.watcher.fileChanged.connect(self._reloadModelTimer.start)

        QTimer.singleShot(0, self._initView)

    @pyqtSlot()
    def _initView(self):
        self._loadExpandedState()
        self._updateColumnVisibility()
        if self._isSettingEnabled('showSubrepos'):
            self._scanAllRepos()

    def _loadSettings(self):
        defaultmap = {'showPaths': False, 'showSubrepos': False,
                      'showNetworkSubrepos': False, 'showShortPaths': True}
        s = QSettings()
        s.beginGroup('Workbench')  # for compatibility with old release
        for key, action in self._settingactions.iteritems():
            action.setChecked(s.value(key, defaultmap[key]).toBool())
        s.endGroup()

    def _saveSettings(self):
        s = QSettings()
        s.beginGroup('Workbench')  # for compatibility with old release
        for key, action in self._settingactions.iteritems():
            s.setValue(key, action.isChecked())
        s.endGroup()
        s.beginGroup('reporegistry')
        self._writeExpandedState(s)
        s.endGroup()

    def _loadExpandedState(self):
        s = QSettings()
        s.beginGroup('reporegistry')
        self._readExpandedState(s)
        s.endGroup()

    def _setupSettingActions(self):
        settingtable = [
            ('showPaths', _('Show &Paths'), self._updateColumnVisibility),
            ('showShortPaths', _('Show S&hort Paths'), self._updateCommonPath),
            ('showSubrepos', _('&Scan Repositories at Startup'), None),
            ('showNetworkSubrepos', _('Scan &Remote Repositories'), None),
            ]
        self._settingactions = {}
        for i, (key, text, slot) in enumerate(settingtable):
            a = QAction(text, self, checkable=True)
            a.setData(i)  # sort key
            if slot:
                a.triggered.connect(slot)
            a.triggered.connect(self._updateSettingActions)
            self._settingactions[key] = a

    @pyqtSlot()
    def _updateSettingActions(self):
        ax = self._settingactions
        ax['showNetworkSubrepos'].setEnabled(ax['showSubrepos'].isChecked())
        ax['showShortPaths'].setEnabled(ax['showPaths'].isChecked())

    def settingActions(self):
        return sorted(self._settingactions.itervalues(),
                      key=lambda a: a.data().toInt())

    def _isSettingEnabled(self, key):
        return self._settingactions[key].isChecked()

    @pyqtSlot()
    def _updateCommonPath(self):
        show = self._isSettingEnabled('showShortPaths')
        self.tview.model().updateCommonPaths(show)
        # FIXME: access violation; should be done by model
        self.tview.dataChanged(QModelIndex(), QModelIndex())

    def updateSettingsFile(self):
        # If there is a settings watcher, we must briefly stop watching the
        # settings file while we save it, otherwise we'll get the update signal
        # that we do not want
        sfile = settingsfilename()
        if self.watcher:
            self.watcher.removePath(sfile)
        self.tview.model().write(sfile)
        if self.watcher:
            self.watcher.addPath(sfile)

        # Whenver the settings file must be updated, it is also time to ensure
        # that the commonPaths are up to date
        QTimer.singleShot(0, self.tview.model().updateCommonPaths)

    @pyqtSlot()
    def dropAccepted(self):
        # Whenever a drag and drop operation is completed, update the settings
        # file
        QTimer.singleShot(0, self.updateSettingsFile)

    @pyqtSlot()
    def reloadModel(self):
        oldmodel = self.tview.model()
        activeroot = oldmodel.repoRoot(oldmodel.activeRepoIndex())
        newmodel = repotreemodel.RepoTreeModel(settingsfilename(),
            self._repomanager, self,
            self._isSettingEnabled('showShortPaths'))
        self.tview.setModel(newmodel)
        oldmodel.deleteLater()
        if self._isSettingEnabled('showSubrepos'):
            self._scanAllRepos()
        self._loadExpandedState()
        if activeroot:
            self.setActiveTabRepo(activeroot)
        self._reloadModelTimer.stop()

    def _readExpandedState(self, s):
        model = self.tview.model()
        for path in s.value('expanded').toStringList():
            self.tview.expand(model.indexFromItemPath(path))

    def _writeExpandedState(self, s):
        model = self.tview.model()
        paths = [model.itemPath(i) for i in model.persistentIndexList()
                 if i.column() == 0 and self.tview.isExpanded(i)]
        s.setValue('expanded', paths)

    # TODO: better to handle repositoryOpened signal by model
    @pyqtSlot(str)
    def _addAndScanRepo(self, uroot):
        """Add repo if not exists; called when the workbench has opened it"""
        uroot = unicode(uroot)
        m = self.tview.model()
        knownindex = m.indexFromRepoRoot(uroot)
        if knownindex.isValid():
            self._scanAddedRepo(knownindex)  # just scan stale subrepos
        else:
            index = m.addRepo(uroot)
            self._scanAddedRepo(index)
            self.updateSettingsFile()

    def addClonedRepo(self, root, sourceroot):
        """Add repo to the same group as the source"""
        m = self.tview.model()
        src = m.indexFromRepoRoot(sourceroot, standalone=True)
        if src.isValid() and not m.isKnownRepoRoot(root):
            index = m.addRepo(root, parent=src.parent())
            self._scanAddedRepo(index)

    def setActiveTabRepo(self, root):
        """"The selected tab has changed on the workbench"""
        m = self.tview.model()
        index = m.indexFromRepoRoot(root)
        m.setActiveRepo(index)
        self.tview.scrollTo(index)

    @pyqtSlot()
    def _updateColumnVisibility(self):
        show = self._isSettingEnabled('showPaths')
        self.tview.setColumnHidden(1, not show)
        self.tview.setHeaderHidden(not show)
        if show:
            self.tview.resizeColumnToContents(0)
            self.tview.resizeColumnToContents(1)

    def close(self):
        # We must stop monitoring the settings file and then we can save it
        sfile = settingsfilename()
        self.watcher.removePath(sfile)
        self.tview.model().write(sfile)
        self._saveSettings()

    def _action_defs(self):
        a = [("reloadRegistry", _("&Refresh Repository List"), 'view-refresh',
                _("Refresh the Repository Registry list"), self.reloadModel),
             ("open", _("&Open"), 'thg-repository-open',
                _("Open the repository in a new tab"), self.open),
             ("openAll", _("&Open All"), 'thg-repository-open',
                _("Open all repositories in new tabs"), self.openAll),
             ("newGroup", _("New &Group"), 'new-group',
                _("Create a new group"), self.newGroup),
             ("rename", _("Re&name"), None,
                _("Rename the entry"), self.startRename),
             ("settings", _("Settin&gs"), 'thg-userconfig',
                _("View the repository's settings"), self.startSettings),
             ("remove", _("Re&move from Registry"), 'hg-strip',
                _("Remove the node and all its subnodes."
                  " Repositories are not deleted from disk."),
                  self.removeSelected),
             ("clone", _("Clon&e..."), 'hg-clone',
                _("Clone Repository"), self.cloneRepo),
             ("explore", _("E&xplore"), 'system-file-manager',
                _("Open the repository in a file browser"), self.explore),
             ("terminal", _("&Terminal"), 'utilities-terminal',
                _("Open a shell terminal in the repository root"), self.terminal),
             ("add", _("&Add Repository..."), 'hg',
                _("Add a repository to this group"), self.addNewRepo),
             ("addsubrepo", _("A&dd Subrepository..."), 'thg-add-subrepo',
                _("Convert an existing repository into a subrepository"),
                self.addSubrepo),
             ("removesubrepo", _("Remo&ve Subrepository..."),
                'thg-remove-subrepo',
                _("Remove this subrepository from the current revision"),
                self.removeSubrepo),
             ("copypath", _("Copy &Path"), '',
                _("Copy the root path of the repository to the clipboard"),
                self.copyPath),
             ("sortbyname", _("Sort by &Name"), '',
                _("Sort the group by short name"), self.sortbyname),
             ("sortbypath", _("Sort by &Path"), '',
                _("Sort the group by full path"), self.sortbypath),
             ("sortbyhgsub", _("&Sort by .hgsub"), '',
                _("Order the subrepos as in .hgsub"), self.sortbyhgsub),
             ]
        return a

    def createActions(self):
        self._actions = {}
        for name, desc, icon, tip, cb in self._action_defs():
            self._actions[name] = QAction(desc, self)
        QTimer.singleShot(0, self.configureActions)

    def configureActions(self):
        for name, desc, icon, tip, cb in self._action_defs():
            act = self._actions[name]
            if icon:
                act.setIcon(qtlib.geticon(icon))
            if tip:
                act.setStatusTip(tip)
            if cb:
                act.triggered.connect(cb)
            self.addAction(act)

    @pyqtSlot(QPoint)
    def _onMenuRequested(self, pos):
        index = self.tview.currentIndex()
        if not index.isValid():
            return
        menulist = index.internalPointer().menulist()
        if not menulist:
            return
        self.addtomenu(self.contextmenu, menulist)
        self.contextmenu.popup(self.tview.viewport().mapToGlobal(pos))

    def addtomenu(self, menu, actlist):
        menu.clear()
        for act in actlist:
            if isinstance(act, basestring) and act in self._actions:
                menu.addAction(self._actions[act])
            elif isinstance(act, tuple) and len(act) == 2:
                submenu = menu.addMenu(act[0])
                self.addtomenu(submenu, act[1])
            else:
                menu.addSeparator()

    #
    ## Menu action handlers
    #

    def _currentRepoRoot(self):
        model = self.tview.model()
        index = self.tview.currentIndex()
        return model.repoRoot(index)

    def cloneRepo(self):
        self.cloneRepoRequested.emit(self._currentRepoRoot())

    def explore(self):
        qtlib.openlocalurl(self._currentRepoRoot())

    def terminal(self):
        model = self.tview.model()
        index = self.tview.currentIndex()
        repoitem = index.internalPointer()
        qtlib.openshell(hglib.fromunicode(model.repoRoot(index)),
                        hglib.fromunicode(repoitem.shortname()))

    def addNewRepo(self):
        'menu action handler for adding a new repository'
        caption = _('Select repository directory to add')
        FD = QFileDialog
        path = FD.getExistingDirectory(caption=caption,
                                       options=FD.ShowDirsOnly | FD.ReadOnly)
        if path:
            m = self.tview.model()
            uroot = paths.find_root(unicode(path))
            if uroot and not m.isKnownRepoRoot(uroot, standalone=True):
                index = m.addRepo(uroot, parent=self.tview.currentIndex())
                self._scanAddedRepo(index)

    def addSubrepo(self):
        'menu action handler for adding a new subrepository'
        root = self._currentRepoRoot()
        caption = _('Select an existing repository to add as a subrepo')
        FD = QFileDialog
        path = unicode(FD.getExistingDirectory(caption=caption,
            directory=root, options=FD.ShowDirsOnly | FD.ReadOnly))
        if path:
            path = os.path.normpath(path)
            sroot = paths.find_root(path)

            root = os.path.normcase(os.path.normpath(root))

            if not sroot:
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('%s is not a valid repository') % path,
                    parent=self)
                return
            elif not os.path.isdir(sroot):
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('"%s" is not a folder') % sroot,
                    parent=self)
                return
            elif os.path.normcase(sroot) == root:
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('A repository cannot be added as a subrepo of itself'),
                    parent=self)
                return
            elif root != paths.find_root(os.path.dirname(os.path.normcase(path))):
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('The selected folder:<br><br>%s<br><br>'
                    'is not inside the target repository.<br><br>'
                    'This may be allowed but is greatly discouraged.<br>'
                    'If you want to add a non trivial subrepository mapping '
                    'you must manually edit the <i>.hgsub</i> file') % root, parent=self)
                return
            else:
                # The selected path is the root of a repository that is inside
                # the selected repository

                # Use forward slashes for relative subrepo root paths
                srelroot = sroot[len(root)+1:]
                srelroot = util.pconvert(srelroot)

                # Is is already on the selected repository substate list?
                try:
                    repo = hg.repository(ui.ui(), hglib.fromunicode(root))
                except:
                    qtlib.WarningMsgBox(_('Cannot open repository'),
                        _('The selected repository:<br><br>%s<br><br>'
                        'cannot be open!') % root, parent=self)
                    return

                if hglib.fromunicode(srelroot) in repo['.'].substate:
                    qtlib.WarningMsgBox(_('Subrepository already exists'),
                        _('The selected repository:<br><br>%s<br><br>'
                        'is already a subrepository of:<br><br>%s<br><br>'
                        'as: "%s"') % (sroot, root, srelroot), parent=self)
                    return
                else:
                    # Read the current .hgsub file contents
                    lines = []
                    hasHgsub = os.path.exists(repo.wjoin('.hgsub'))
                    if hasHgsub:
                        try:
                            fsub = repo.wopener('.hgsub', 'r')
                            lines = fsub.readlines()
                            fsub.close()
                        except:
                            qtlib.WarningMsgBox(
                                _('Failed to add subrepository'),
                                _('Cannot open the .hgsub file in:<br><br>%s') \
                                % root, parent=self)
                            return

                    # Make sure that the selected subrepo (or one of its
                    # subrepos!) is not already on the .hgsub file
                    linesep = ''
                    # On Windows case is unimportant, while on posix it is
                    srelrootnormcase = os.path.normcase(srelroot)
                    for line in lines:
                        line = hglib.tounicode(line)
                        spath = line.split("=")[0].strip()
                        if not spath:
                            continue
                        if not linesep:
                            linesep = hglib.getLineSeparator(line)
                        spath = util.pconvert(spath)
                        if os.path.normcase(spath) == srelrootnormcase:
                            qtlib.WarningMsgBox(
                                _('Failed to add repository'),
                                _('The .hgsub file already contains the '
                                'line:<br><br>%s') % line, parent=self)
                            return
                    if not linesep:
                        linesep = os.linesep

                    # Append the new subrepo to the end of the .hgsub file
                    lines.append(hglib.fromunicode('%s = %s'
                                                   % (srelroot, srelroot)))
                    lines = [line.strip(linesep) for line in lines]

                    # and update the .hgsub file
                    try:
                        fsub = repo.wopener('.hgsub', 'w')
                        fsub.write(linesep.join(lines) + linesep)
                        fsub.close()
                        if not hasHgsub:
                            commands.add(ui.ui(), repo, repo.wjoin('.hgsub'))
                        qtlib.InfoMsgBox(
                            _('Subrepo added to .hgsub file'),
                            _('The selected subrepo:<br><br><i>%s</i><br><br>'
                            'has been added to the .hgsub file of the repository:<br><br><i>%s</i><br><br>'
                            'Remember that in order to finish adding the '
                            'subrepo <i>you must still <u>commit</u></i> the '
                            'changes to the .hgsub file in order to confirm '
                            'the addition of the subrepo.') \
                            % (srelroot, root), parent=self)
                    except:
                        qtlib.WarningMsgBox(
                            _('Failed to add repository'),
                            _('Cannot update the .hgsub file in:<br><br>%s') \
                            % root, parent=self)
                return

    def removeSubrepo(self):
        'menu action handler for removing an existing subrepository'
        model = self.tview.model()
        index = self.tview.currentIndex()
        path = model.repoRoot(index)
        root = model.repoRoot(index.parent())
        relsubpath = os.path.normcase(os.path.normpath(path[1+len(root):]))
        hgsubfilename = os.path.join(root, '.hgsub')

        try:
            f = open(hgsubfilename, 'r')
            hgsub = []
            found = False
            for line in f.readlines():
                spath = os.path.normcase(
                    os.path.normpath(
                        line.split('=')[0].strip()))
                if spath != relsubpath:
                    hgsub.append(line)
                else:
                    found = True
            f.close()
        except IOError:
            qtlib.ErrorMsgBox(_('Could not open .hgsub file'),
                _('Cannot read the .hgsub file.<p>'
                  'Subrepository removal failed.'),
                parent=self)
            return

        if not found:
            qtlib.WarningMsgBox(_('Subrepository not found'),
                _('The selected subrepository was not found '
                  'on the .hgsub file.<p>'
                  'Perhaps it has already been removed?'),
                parent=self)
            return
        choices = (_('&Yes'), _('&No'))
        answer = qtlib.CustomPrompt(_('Remove the selected repository?'),
            _('Do you really want to remove the repository "<i>%s</i>" '
              'from its parent repository "<i>%s</i>"') % (relsubpath, root),
            self, choices=choices, default=choices[0]).run()
        if answer != 0:
            return
        try:
            f = open(hgsubfilename, 'w')
            f.writelines(hgsub)
            f.close()
            qtlib.InfoMsgBox(_('Subrepository removed from .hgsub'),
                _('The selected subrepository has been removed '
                  'from the .hgsub file.<p>'
                  'Remember that you must commit this .hgsub change in order '
                  'to complete the removal of the subrepository!'),
                parent=self)
        except IOError:
            qtlib.ErrorMsgBox(_('Could not update .hgsub file'),
                _('Cannot update the .hgsub file.<p>'
                  'Subrepository removal failed.'),
                parent=self)

    def startSettings(self):
        root = hglib.fromunicode(self._currentRepoRoot())
        sd = settings.SettingsDialog(configrepo=True, focus='web.name',
                                     parent=self, root=root)
        sd.finished.connect(sd.deleteLater)
        sd.exec_()

    def openAll(self):
        index = self.tview.currentIndex()
        for root in index.internalPointer().childRoots():
            self.openRepo.emit(root, False)

    def open(self, root=None):
        'open context menu action, open repowidget unconditionally'
        if not root:
            model = self.tview.model()
            index = self.tview.currentIndex()
            root = model.repoRoot(index)
            repotype = index.internalPointer().repotype()
        else:
            if os.path.exists(os.path.join(root, '.hg')):
                repotype = 'hg'
            else:
                repotype = 'unknown'
        if repotype == 'hg':
            self.openRepo.emit(root, False)
        else:
            qtlib.WarningMsgBox(
                _('Unsupported repository type (%s)') % repotype,
                _('Cannot open non Mercurial repositories or subrepositories'),
                parent=self)

    @pyqtSlot(QModelIndex)
    def _openRepoAt(self, index):
        model = self.tview.model()
        root = model.repoRoot(index)
        if root:
            # We can only open mercurial repositories and subrepositories
            repotype = index.internalPointer().repotype()
            if repotype == 'hg':
                self.openRepo.emit(root, True)
            else:
                qtlib.WarningMsgBox(
                    _('Unsupported repository type (%s)') % repotype,
                    _('Cannot open non Mercurial repositories or '
                      'subrepositories'),
                    parent=self)

    def copyPath(self):
        clip = QApplication.clipboard()
        clip.setText(self._currentRepoRoot())

    def startRename(self):
        self.tview.edit(self.tview.currentIndex())

    def newGroup(self):
        self.tview.model().addGroup(_('New Group'))

    def removeSelected(self):
        root = self._currentRepoRoot()
        self._removeAt(self.tview.currentIndex())
        if root:
            self.removeRepo.emit(root)

    @pyqtSlot(QModelIndex)
    def _removeAt(self, index):
        item = index.internalPointer()
        if 'remove' not in item.menulist():  # check capability
            return
        if not item.okToDelete():
            labels = [(QMessageBox.Yes, _('&Delete')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Delete'),
                                        _("Delete Group '%s' and all its "
                                          "entries?") % item.name,
                                        labels=labels, parent=self):
                return
        m = self.tview.model()
        m.removeRows(index.row(), 1, index.parent())
        self.updateSettingsFile()

    def sortbyname(self):
        index = self.tview.currentIndex()
        childs = index.internalPointer().childs
        self.tview.model().sortchilds(childs, lambda x: x.shortname().lower())

    def sortbypath(self):
        index = self.tview.currentIndex()
        childs = index.internalPointer().childs
        def keyfunc(x):
            l = hglib.fromunicode(x.rootpath())
            return os.path.normcase(util.normpath(l))
        self.tview.model().sortchilds(childs, keyfunc)

    def sortbyhgsub(self):
        model = self.tview.model()
        index = self.tview.currentIndex()
        ip = index.internalPointer()
        repo = hg.repository(ui.ui(), hglib.fromunicode(model.repoRoot(index)))
        ctx = repo['.']
        wfile = '.hgsub'
        if wfile not in ctx:
            return self.sortbypath()
        data = ctx[wfile].data().strip()
        data = data.split('\n')
        getsubpath = lambda x: x.split('=')[0].strip()
        abspath = lambda x: util.normpath(repo.wjoin(x))
        hgsuborder = [abspath(getsubpath(x)) for x in data]
        def keyfunc(x):
            l = hglib.fromunicode(x.rootpath())
            try:
                return hgsuborder.index(util.normpath(l))
            except ValueError:
                # If an item is not found, place it at the top
                return 0
        self.tview.model().sortchilds(ip.childs, keyfunc)

    def _scanAddedRepo(self, index):
        m = self.tview.model()
        invalidpaths = m.loadSubrepos(index)
        if not invalidpaths:
            return

        root = m.repoRoot(index)
        if root in invalidpaths:
            qtlib.WarningMsgBox(_('Could not get subrepository list'),
                _('It was not possible to get the subrepository list for '
                  'the repository in:<br><br><i>%s</i>') % root, parent=self)
        else:
            qtlib.WarningMsgBox(_('Could not open some subrepositories'),
                _('It was not possible to fully load the subrepository '
                  'list for the repository in:<br><br><i>%s</i><br><br>'
                  'The following subrepositories may be missing, broken or '
                  'on an inconsistent state and cannot be accessed:'
                  '<br><br><i>%s</i>')
                % (root, "<br>".join(invalidpaths)), parent=self)

    @pyqtSlot(str)
    def scanRepo(self, uroot):
        uroot = unicode(uroot)
        m = self.tview.model()
        index = m.indexFromRepoRoot(uroot)
        if index.isValid():
            m.loadSubrepos(index)

    def _scanAllRepos(self):
        m = self.tview.model()
        indexes = m.indexesOfRepoItems(standalone=True)
        if not self._isSettingEnabled('showNetworkSubrepos'):
            indexes = [idx for idx in indexes
                       if paths.is_on_fixed_drive(m.repoRoot(idx))]

        topic = _('Updating repository registry')
        for n, idx in enumerate(indexes):
            self.progressReceived.emit(
                topic, n, _('Loading repository %s') % m.repoRoot(idx), '',
                len(indexes))
            m.loadSubrepos(idx)
        self.progressReceived.emit(
            topic, None, _('Repository Registry updated'), '', None)
