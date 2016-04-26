# workbench.py - main TortoiseHg Window
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.
"""
Main Qt4 application for TortoiseHg
"""

import os
import subprocess
import sys
from tortoisehg.util import paths, hglib
from tortoisehg.util.i18n import _

from tortoisehg.hgqt import cmdcore, cmdui, qtlib, mq, repotab, serve
from tortoisehg.hgqt.reporegistry import RepoRegistryView
from tortoisehg.hgqt.docklog import LogDockWidget
from tortoisehg.hgqt.settings import SettingsDialog

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class Workbench(QMainWindow):
    """hg repository viewer/browser application"""

    def __init__(self, ui, repomanager):
        QMainWindow.__init__(self)
        self.ui = ui
        self._repomanager = repomanager
        self._repomanager.configChanged.connect(self._setupUrlComboIfCurrent)

        self.setupUi()
        repomanager.busyChanged.connect(self._onBusyChanged)
        repomanager.progressReceived.connect(self.statusbar.setRepoProgress)

        self.reporegistry = rr = RepoRegistryView(repomanager, self)
        rr.setObjectName('RepoRegistryView')
        rr.showMessage.connect(self.statusbar.showMessage)
        rr.openRepo.connect(self.openRepo)
        rr.removeRepo.connect(self.repoTabsWidget.closeRepo)
        rr.cloneRepoRequested.connect(self.cloneRepository)
        rr.progressReceived.connect(self.statusbar.progress)
        self._repomanager.repositoryChanged.connect(rr.scanRepo)
        rr.hide()
        self.addDockWidget(Qt.LeftDockWidgetArea, rr)

        self.mqpatches = p = mq.MQPatchesWidget(self)
        p.setObjectName('MQPatchesWidget')
        p.patchSelected.connect(self.gotorev)
        p.hide()
        self.addDockWidget(Qt.LeftDockWidgetArea, p)

        cmdagent = cmdcore.CmdAgent(ui, self)
        self._console = LogDockWidget(repomanager, cmdagent, self)
        self._console.setObjectName('Log')
        self._console.hide()
        self._console.visibilityChanged.connect(self._updateShowConsoleAction)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._console)

        self._setupActions()

        self.restoreSettings()
        self.repoTabChanged()
        self.setAcceptDrops(True)
        self.setIconSize(qtlib.toolBarIconSize())
        if os.name == 'nt':
            # Allow CTRL+Q to close Workbench on Windows
            QShortcut(QKeySequence('CTRL+Q'), self, self.close)
        if sys.platform == 'darwin':
            self.dockMenu = QMenu(self)
            self.dockMenu.addAction(_('New &Workbench'),
                                    self.newWorkbench)
            self.dockMenu.addAction(_('&New Repository...'),
                                    self.newRepository)
            self.dockMenu.addAction(_('Clon&e Repository...'),
                                    self.cloneRepository)
            self.dockMenu.addAction(_('&Open Repository...'),
                                    self.openRepository)
            qt_mac_set_dock_menu(self.dockMenu)
            # On Mac OS X, we do not want icons on menus
            qt_mac_set_menubar_icons(False)

        self._dialogs = qtlib.DialogKeeper(
            lambda self, dlgmeth: dlgmeth(self), parent=self)

    def setupUi(self):
        desktopgeom = qApp.desktop().availableGeometry()
        self.resize(desktopgeom.size() * 0.8)

        self.repoTabsWidget = tw = repotab.RepoTabWidget(
            self.ui, self._repomanager, self)
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sp.setHorizontalStretch(1)
        sp.setVerticalStretch(1)
        sp.setHeightForWidth(tw.sizePolicy().hasHeightForWidth())
        tw.setSizePolicy(sp)
        tw.currentTabChanged.connect(self.repoTabChanged)
        tw.currentRepoChanged.connect(self._onCurrentRepoChanged)
        tw.currentTaskTabChanged.connect(self._updateTaskViewMenu)
        tw.currentTitleChanged.connect(self._updateWindowTitle)
        tw.historyChanged.connect(self._updateHistoryActions)
        tw.makeLogVisible.connect(self._setConsoleVisible)
        tw.toolbarVisibilityChanged.connect(self._updateToolBarActions)

        self.setCentralWidget(tw)
        self.statusbar = cmdui.ThgStatusBar(self)
        self.setStatusBar(self.statusbar)

        tw.progressReceived.connect(self.statusbar.setRepoProgress)
        tw.showMessageSignal.connect(self.statusbar.showMessage)

    def _setupActions(self):
        """Setup actions, menus and toolbars"""
        self.menubar = QMenuBar(self)
        self.setMenuBar(self.menubar)

        self.menuFile = self.menubar.addMenu(_("&File"))
        self.menuView = self.menubar.addMenu(_("&View"))
        self.menuRepository = self.menubar.addMenu(_("&Repository"))
        self.menuHelp = self.menubar.addMenu(_("&Help"))

        self.edittbar = QToolBar(_("&Edit Toolbar"), objectName='edittbar')
        self.addToolBar(self.edittbar)
        self.docktbar = QToolBar(_("&Dock Toolbar"), objectName='docktbar')
        self.addToolBar(self.docktbar)
        self.tasktbar = QToolBar(_('&Task Toolbar'), objectName='taskbar')
        self.addToolBar(self.tasktbar)
        self.customtbar = QToolBar(_('&Custom Toolbar'), objectName='custombar')
        self.addToolBar(self.customtbar)
        self.synctbar = QToolBar(_('S&ync Toolbar'), objectName='synctbar')
        self.addToolBar(self.synctbar)

        # availability map of actions; applied by _updateMenu()
        self._actionavails = {'repoopen': []}
        self._actionvisibles = {'repoopen': []}

        modifiedkeysequence = qtlib.modifiedkeysequence
        newaction = self._addNewAction
        newseparator = self._addNewSeparator

        newaction(_("New &Workbench"), self.newWorkbench,
                  shortcut='Shift+Ctrl+W', menu='file', icon='hg-log')
        newseparator(menu='file')
        newaction(_("&New Repository..."), self.newRepository,
                  shortcut='New', menu='file', icon='hg-init')
        newaction(_("Clon&e Repository..."), self.cloneRepository,
                  shortcut=modifiedkeysequence('New', modifier='Shift'),
                  menu='file', icon='hg-clone')
        newseparator(menu='file')
        newaction(_("&Open Repository..."), self.openRepository,
                  shortcut='Open', menu='file')
        newaction(_("&Close Repository"), self.closeCurrentRepoTab,
                  shortcut='Close', enabled='repoopen', menu='file')
        newseparator(menu='file')
        newaction(_('&Settings'), self.editSettings, icon='thg-userconfig',
                  shortcut='Preferences', menu='file')
        newseparator(menu='file')
        newaction(_("E&xit"), self.close, shortcut='Quit', menu='file')

        a = self.reporegistry.toggleViewAction()
        a.setText(_('Sh&ow Repository Registry'))
        a.setShortcut('Ctrl+Shift+O')
        a.setIcon(qtlib.geticon('thg-reporegistry'))
        self.docktbar.addAction(a)
        self.menuView.addAction(a)

        a = self.mqpatches.toggleViewAction()
        a.setText(_('Show &Patch Queue'))
        a.setIcon(qtlib.geticon('thg-mq'))
        self.docktbar.addAction(a)
        self.menuView.addAction(a)

        self._actionShowConsole = a = QAction(_('Show Conso&le'), self)
        a.setCheckable(True)
        a.setShortcut('Ctrl+L')
        a.setIcon(qtlib.geticon('thg-console'))
        a.triggered.connect(self._setConsoleVisible)
        self.docktbar.addAction(a)
        self.menuView.addAction(a)

        self._actionDockedConsole = a = QAction(self)
        a.setText(_('Place Console in Doc&k Area'))
        a.setCheckable(True)
        a.setChecked(True)
        a.triggered.connect(self._updateDockedConsoleMode)

        newseparator(menu='view')
        menu = self.menuView.addMenu(_('R&epository Registry Options'))
        menu.addActions(self.reporegistry.settingActions())

        newseparator(menu='view')
        newaction(_("C&hoose Log Columns..."), self._setHistoryColumns,
                  enabled='repoopen', menu='view')
        self.actionSaveRepos = \
        newaction(_("Save Open Repositories on E&xit"), checkable=True,
                  menu='view')
        self.actionSaveLastSyncPaths = \
        newaction(_("Sa&ve Current Sync Paths on Exit"), checkable=True,
                  menu='view')
        newseparator(menu='view')

        self.actionGroupTaskView = QActionGroup(self)
        self.actionGroupTaskView.triggered.connect(self._onSwitchRepoTaskTab)
        def addtaskview(icon, label, name):
            a = newaction(label, icon=None, checkable=True, data=name,
                          enabled='repoopen', menu='view')
            a.setIcon(qtlib.geticon(icon))
            self.actionGroupTaskView.addAction(a)
            self.tasktbar.addAction(a)
            return a

        # note that 'grep' and 'search' are equivalent
        taskdefs = {
            'commit': ('hg-commit', _('&Commit')),
            'pbranch': ('hg-branch', _('&Patch Branch')),
            'log': ('hg-log', _("Revision &Details")),
            'grep': ('hg-grep', _('&Search')),
            'sync': ('thg-sync', _('S&ynchronize')),
            # 'console' is toggled by "Show Console" action
        }
        tasklist = self.ui.configlist(
            'tortoisehg', 'workbench.task-toolbar', [])
        if tasklist == []:
            tasklist = ['log', 'commit', 'grep', 'pbranch', '|', 'sync']

        self.actionSelectTaskPbranch = None

        for taskname in tasklist:
            taskname = taskname.strip()
            taskinfo = taskdefs.get(taskname, None)
            if taskinfo is None:
                newseparator(toolbar='task')
                continue
            tbar = addtaskview(taskinfo[0], taskinfo[1], taskname)
            if taskname == 'pbranch':
                self.actionSelectTaskPbranch = tbar

        newseparator(menu='view')

        a = newaction(_("&Refresh"), self.refresh, icon='view-refresh',
                      enabled='repoopen', menu='view', toolbar='edit',
                      tooltip=_('Refresh current repository'))
        a.setShortcuts(QKeySequence.keyBindings(QKeySequence.Refresh)
                       + [QKeySequence('Ctrl+F5')])  # Ctrl+ to ignore status
        newaction(_("Refresh &Task Tab"), self._repofwd('reloadTaskTab'),
                  enabled='repoopen',
                  shortcut=modifiedkeysequence('Refresh', modifier='Shift'),
                  tooltip=_('Refresh only the current task tab'),
                  menu='view')
        newaction(_("Load &All Revisions"), self.loadall,
                  enabled='repoopen', menu='view', shortcut='Shift+Ctrl+A',
                  tooltip=_('Load all revisions into graph'))

        self.actionAbort = \
        newaction(_('Cancel'), self._abortCommands, icon='process-stop',
                  toolbar='edit',
                  tooltip=_('Stop current operation'))
        self.actionAbort.setEnabled(False)

        newseparator(toolbar='edit')
        newaction(_("Go to current revision"), self._repofwd('gotoParent'),
                  icon='go-home', tooltip=_('Go to current revision'),
                  enabled='repoopen', toolbar='edit', shortcut='Ctrl+.')
        newaction(_("&Goto Revision..."), self._gotorev, icon='go-to-rev',
                  shortcut='Ctrl+/', enabled='repoopen',
                  tooltip=_('Go to a specific revision'),
                  menu='view', toolbar='edit')

        self.actionBack = \
        newaction(_("Back"), self._repofwd('back'), icon='go-previous',
                  shortcut=QKeySequence.Back,
                  enabled=False, toolbar='edit')
        self.actionForward = \
        newaction(_("Forward"), self._repofwd('forward'), icon='go-next',
                  shortcut=QKeySequence.Forward,
                  enabled=False, toolbar='edit')
        newseparator(toolbar='edit', menu='View')

        self.filtertbaction = \
        newaction(_('&Filter Toolbar'), self._repotogglefwd('toggleFilterBar'),
                  icon='view-filter', shortcut='Ctrl+S', enabled='repoopen',
                  toolbar='edit', menu='View', checkable=True,
                  tooltip=_('Filter graph with revision sets or branches'))

        menu = QMenu(_('&Workbench Toolbars'), self)
        menu.addAction(self.edittbar.toggleViewAction())
        menu.addAction(self.docktbar.toggleViewAction())
        menu.addAction(self.tasktbar.toggleViewAction())
        menu.addAction(self.synctbar.toggleViewAction())
        menu.addAction(self.customtbar.toggleViewAction())
        self.menuView.addMenu(menu)

        newseparator(toolbar='edit')
        menuSync = self.menuRepository.addMenu(_('S&ynchronize'))
        a = newaction(_("&Lock File..."), self._repofwd('lockTool'),
                    icon='thg-password', enabled='repoopen',
                    menu='repository', toolbar='edit',
                    tooltip=_('Lock or unlock files'))
        self.lockToolAction = a
        newseparator(menu='repository')
        newaction(_("&Update..."), self._repofwd('updateToRevision'),
                  icon='hg-update', enabled='repoopen',
                  menu='repository', toolbar='edit',
                  tooltip=_('Update working directory or switch revisions'))
        newaction(_("&Shelve..."), self._repofwd('shelve'), icon='hg-shelve',
                  enabled='repoopen', menu='repository')
        newaction(_("&Import Patches..."), self._repofwd('thgimport'),
                  icon='hg-import', enabled='repoopen', menu='repository')
        newaction(_("U&nbundle..."), self._repofwd('unbundle'),
                  icon='hg-unbundle', enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_('&Merge...'), self._repofwd('mergeWithOtherHead'),
                  icon='hg-merge', enabled='repoopen',
                  menu='repository', toolbar='edit',
                  tooltip=_('Merge with the other head of the current branch'))
        newaction(_("&Resolve..."), self._repofwd('resolve'),
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("R&ollback/Undo..."), self._repofwd('rollback'),
                  shortcut='Ctrl+u',
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("&Purge..."), self._repofwd('purge'), enabled='repoopen',
                  icon='hg-purge', menu='repository')
        newseparator(menu='repository')
        newaction(_("&Bisect..."), self._repofwd('bisect'),
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("&Verify"), self._repofwd('verify'), enabled='repoopen',
                  menu='repository')
        newaction(_("Re&cover"), self._repofwd('recover'),
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("E&xplore"), self.explore, shortcut='Shift+Ctrl+X',
                  icon='system-file-manager', enabled='repoopen',
                  menu='repository')
        newaction(_("&Terminal"), self.terminal, shortcut='Shift+Ctrl+T',
                  icon='utilities-terminal', enabled='repoopen',
                  menu='repository')
        newaction(_("&Web Server"), self.serve, menu='repository',
                  icon='hg-serve')

        newaction(_("&Help"), self.onHelp, menu='help', icon='help-browser')
        newaction(_("E&xplorer Help"), self.onHelpExplorer, menu='help')
        visiblereadme = 'repoopen'
        if  self.ui.config('tortoisehg', 'readme', None):
            visiblereadme = True
        newaction(_("&Readme"), self.onReadme, menu='help', icon='help-readme',
                  visible=visiblereadme, shortcut='Ctrl+F1')
        newseparator(menu='help')
        newaction(_("About &Qt"), QApplication.aboutQt, menu='help')
        newaction(_("&About TortoiseHg"), self.onAbout, menu='help', icon='thg')

        newaction(_('&Incoming'), data='incoming', icon='hg-incoming',
                  enabled='repoopen', toolbar='sync', shortcut='Ctrl+Shift+,')
        newaction(_('&Pull'), data='pull', icon='hg-pull',
                  enabled='repoopen', toolbar='sync')
        newaction(_('&Outgoing'), data='outgoing', icon='hg-outgoing',
                  enabled='repoopen', toolbar='sync', shortcut='Ctrl+Shift+.')
        newaction(_('P&ush'), data='push', icon='hg-push',
                  enabled='repoopen', toolbar='sync')
        menuSync.addActions(self.synctbar.actions())
        menuSync.addSeparator()

        action = QAction(_('&Sync Bookmarks...'), self)
        action.setIcon(qtlib.geticon('thg-sync-bookmarks'))
        self._actionavails['repoopen'].append(action)
        action.triggered.connect(self._runSyncBookmarks)
        menuSync.addAction(action)

        self._lastRepoSyncPath = {}
        self.urlCombo = QComboBox(self)
        self.urlCombo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.urlCombo.currentIndexChanged.connect(self._updateSyncUrl)
        self.urlComboAction = self.synctbar.addWidget(self.urlCombo)
        # hide it because workbench could be started without open repo
        self.urlComboAction.setVisible(False)
        self.synctbar.actionTriggered.connect(self._runSyncAction)

    def _setupUrlCombo(self, repo):
        """repository has been switched, fill urlCombo with URLs"""
        pathdict = dict((hglib.tounicode(alias), hglib.tounicode(path))
                         for alias, path in repo.ui.configitems('paths'))
        aliases = pathdict.keys()

        combo_setting = repo.ui.config('tortoisehg', 'workbench.target-combo',
                                       'auto')
        self.urlComboAction.setVisible(len(aliases) > 1
                                       or combo_setting == 'always')

        # 1. Sort the list if aliases
        aliases.sort()
        # 2. Place the default alias at the top of the list
        if 'default' in aliases:
            aliases.remove('default')
            aliases.insert(0, 'default')
        # 3. Make a list of paths that have a 'push path'
        # note that the default path will be first (if it has a push path),
        # followed by the other paths that have a push path, alphabetically
        haspushaliases = [alias for alias in aliases
                         if alias + '-push' in aliases]
        # 4. Place the "-push" paths next to their "pull paths"
        regularaliases = []
        for a in aliases[:]:
            if a.endswith('-push'):
                if a[:-len('-push')] in haspushaliases:
                    continue
            regularaliases.append(a)
            if a in haspushaliases:
                regularaliases.append(a + '-push')
        # 5. Create the list of 'combined aliases'
        combinedaliases = [(a, a + '-push') for a in haspushaliases]
        # 6. Put the combined aliases first, followed by the regular aliases
        aliases = combinedaliases + regularaliases
        # 7. Ensure the first path is a default path (either a
        # combined "default | default-push" path or a regular default path)
        if not 'default-push' in aliases and 'default' in aliases:
            aliases.remove('default')
            aliases.insert(0, 'default')

        self.urlCombo.blockSignals(True)
        self.urlCombo.clear()
        for n, a in enumerate(aliases):
            # text, (pull-alias, push-alias)
            if isinstance(a, tuple):
                itemtext = u'\u2193 %s | %s \u2191' % a
                itemdata = tuple(pathdict[alias] for alias in a)
                tooltip = _('pull: %s\npush: %s') % itemdata
            else:
                itemtext = a
                itemdata = (pathdict[a], pathdict[a])
                tooltip = pathdict[a]
            self.urlCombo.addItem(itemtext, itemdata)
            self.urlCombo.setItemData(n, tooltip, Qt.ToolTipRole)
        # Try to select the previously selected path, if any
        prevpath = self._lastRepoSyncPath.get(hglib.tounicode(repo.root))
        if prevpath:
            idx = self.urlCombo.findText(prevpath)
            if idx >= 0:
                self.urlCombo.setCurrentIndex(idx)
        self.urlCombo.blockSignals(False)
        self._updateSyncUrlToolTip(self.urlCombo.currentIndex())

    @pyqtSlot(str)
    def _setupUrlComboIfCurrent(self, root):
        w = self._currentRepoWidget()
        if w.repoRootPath() == root:
            self._setupUrlCombo(w.repo)

    def _syncUrlFor(self, op):
        """Current URL for the given sync operation"""
        urlindex = self.urlCombo.currentIndex()
        if urlindex < 0:
            return
        opindex = {'incoming': 0, 'pull': 0, 'outgoing': 1, 'push': 1}[op]
        return self.urlCombo.itemData(urlindex).toPyObject()[opindex]

    @pyqtSlot(int)
    def _updateSyncUrl(self, index):
        self._updateSyncUrlToolTip(index)
        # save the new url for later recovery
        reporoot = self.currentRepoRootPath()
        if not reporoot:
            return
        path = self.urlCombo.currentText()
        self._lastRepoSyncPath[reporoot] = path

    def _updateSyncUrlToolTip(self, index):
        self._updateUrlComboToolTip(index)
        self._updateSyncActionToolTip(index)

    def _updateUrlComboToolTip(self, index):
        if not self.urlCombo.count():
            tooltip = _('There are no configured sync paths.\n'
                        'Open the Synchronize tab to configure them.')
        else:
            tooltip = self.urlCombo.itemData(index, Qt.ToolTipRole).toString()
        self.urlCombo.setToolTip(tooltip)

    def _updateSyncActionToolTip(self, index):
        if index < 0:
            tooltips = {
                'incoming': _('Check for incoming changes'),
                'pull':     _('Pull incoming changes'),
                'outgoing': _('Detect outgoing changes'),
                'push':     _('Push outgoing changes'),
                }
        else:
            pullurl, pushurl = self.urlCombo.itemData(index).toPyObject()
            tooltips = {
                'incoming': _('Check for incoming changes from\n%s') % pullurl,
                'pull':     _('Pull incoming changes from\n%s') % pullurl,
                'outgoing': _('Detect outgoing changes to\n%s') % pushurl,
                'push':     _('Push outgoing changes to\n%s') % pushurl,
                }

        for a in self.synctbar.actions():
            op = str(a.data().toString())
            if op in tooltips:
                a.setToolTip(tooltips[op])

    def _setupCustomTools(self, ui):
        tools, toollist = hglib.tortoisehgtools(ui,
            selectedlocation='workbench.custom-toolbar')
        # Clear the existing "custom" toolbar
        self.customtbar.clear()
        # and repopulate it again with the tool configuration
        # for the current repository
        if not tools:
            return
        for name in toollist:
            if name == '|':
                self._addNewSeparator(toolbar='custom')
                continue
            info = tools.get(name, None)
            if info is None:
                continue
            command = info.get('command', None)
            if not command:
                continue
            showoutput = info.get('showoutput', False)
            workingdir = info.get('workingdir', '')
            label = info.get('label', name)
            tooltip = info.get('tooltip', _("Execute custom tool '%s'") % label)
            icon = info.get('icon', 'tools-spanner-hammer')

            self._addNewAction(label,
                self._repofwd('runCustomCommand',
                              [command, showoutput, workingdir]),
                icon=icon, tooltip=tooltip,
                enabled=True, toolbar='custom')

    def _addNewAction(self, text, slot=None, icon=None, shortcut=None,
                  checkable=False, tooltip=None, data=None, enabled=None,
                  visible=None, menu=None, toolbar=None):
        """Create new action and register it

        :slot: function called if action triggered or toggled.
        :checkable: checkable action. slot will be called on toggled.
        :data: optional data stored on QAction.
        :enabled: bool or group name to enable/disable action.
        :visible: bool or group name to show/hide action.
        :shortcut: QKeySequence, key sequence or name of standard key.
        :menu: name of menu to add this action.
        :toolbar: name of toolbar to add this action.
        """
        action = QAction(text, self, checkable=checkable)
        if slot:
            if checkable:
                action.toggled.connect(slot)
            else:
                action.triggered.connect(slot)
        if icon:
            action.setIcon(qtlib.geticon(icon))
        if shortcut:
            keyseq = qtlib.keysequence(shortcut)
            if isinstance(keyseq, QKeySequence.StandardKey):
                action.setShortcuts(keyseq)
            else:
                action.setShortcut(keyseq)
        if tooltip:
            if action.shortcut():
                tooltip += ' (%s)' % action.shortcut().toString()
            action.setToolTip(tooltip)
        if data is not None:
            action.setData(data)
        if isinstance(enabled, bool):
            action.setEnabled(enabled)
        elif enabled:
            self._actionavails[enabled].append(action)
        if isinstance(visible, bool):
            action.setVisible(visible)
        elif visible:
            self._actionvisibles[visible].append(action)
        if menu:
            getattr(self, 'menu%s' % menu.title()).addAction(action)
        if toolbar:
            getattr(self, '%stbar' % toolbar).addAction(action)
        return action

    def _addNewSeparator(self, menu=None, toolbar=None):
        """Insert a separator action; returns nothing"""
        if menu:
            getattr(self, 'menu%s' % menu.title()).addSeparator()
        if toolbar:
            getattr(self, '%stbar' % toolbar).addSeparator()

    def createPopupMenu(self):
        """Create new popup menu for toolbars and dock widgets"""
        menu = super(Workbench, self).createPopupMenu()
        assert menu  # should have toolbar/dock menu
        # replace default log dock action by customized one
        menu.insertAction(self._console.toggleViewAction(),
                          self._actionShowConsole)
        menu.removeAction(self._console.toggleViewAction())
        menu.addSeparator()
        menu.addAction(self._actionDockedConsole)
        menu.addAction(_('Custom Toolbar &Settings'),
                       self._editCustomToolsSettings)
        return menu

    @pyqtSlot(QAction)
    def _onSwitchRepoTaskTab(self, action):
        rw = self._currentRepoWidget()
        if rw:
            rw.switchToNamedTaskTab(str(action.data().toString()))

    @pyqtSlot(bool)
    def _setConsoleVisible(self, visible):
        if self._actionDockedConsole.isChecked():
            self._setDockedConsoleVisible(visible)
        else:
            self._setConsoleTaskTabVisible(visible)

    def _setDockedConsoleVisible(self, visible):
        self._console.setVisible(visible)
        if visible:
            # not hook setVisible() or showEvent() in order to move focus
            # only when console is activated by user action
            self._console.setFocus()

    def _setConsoleTaskTabVisible(self, visible):
        rw = self._currentRepoWidget()
        if not rw:
            return
        if visible:
            rw.switchToNamedTaskTab('console')
        else:
            # it'll be better if it can switch to the last tab
            rw.switchToPreferredTaskTab()

    @pyqtSlot()
    def _updateShowConsoleAction(self):
        if self._actionDockedConsole.isChecked():
            visible = self._console.isVisibleTo(self)
            enabled = True
        else:
            rw = self._currentRepoWidget()
            visible = bool(rw and rw.currentTaskTabName() == 'console')
            enabled = bool(rw)
        self._actionShowConsole.setChecked(visible)
        self._actionShowConsole.setEnabled(enabled)

    @pyqtSlot()
    def _updateDockedConsoleMode(self):
        docked = self._actionDockedConsole.isChecked()
        visible = self._actionShowConsole.isChecked()
        self._console.setVisible(docked and visible)
        self._setConsoleTaskTabVisible(not docked and visible)
        self._updateShowConsoleAction()

    @pyqtSlot(str, bool)
    def openRepo(self, root, reuse, bundle=None):
        """Open tab of the specified repo [unicode]"""
        root = unicode(root)
        if not root or root.startswith('ssh://'):
            return
        if reuse and self.repoTabsWidget.selectRepo(root):
            return
        if not self.repoTabsWidget.openRepo(root, bundle):
            return

    @pyqtSlot(str)
    def showRepo(self, root):
        """Activate the repo tab or open it if not available [unicode]"""
        self.openRepo(root, True)

    @pyqtSlot(str, str)
    def setRevsetFilter(self, path, filter):
        if self.repoTabsWidget.selectRepo(path):
            w = self.repoTabsWidget.currentWidget()
            w.setFilter(filter)

    def dragEnterEvent(self, event):
        d = event.mimeData()
        for u in d.urls():
            root = paths.find_root(unicode(u.toLocalFile()))
            if root:
                event.setDropAction(Qt.LinkAction)
                event.accept()
                break

    def dropEvent(self, event):
        accept = False
        d = event.mimeData()
        for u in d.urls():
            root = paths.find_root(unicode(u.toLocalFile()))
            if root:
                self.showRepo(root)
                accept = True
        if accept:
            event.setDropAction(Qt.LinkAction)
            event.accept()

    def _updateMenu(self):
        """Enable actions when repoTabs are opened or closed or changed"""

        # Update actions affected by repo open/close
        someRepoOpen = bool(self._currentRepoWidget())
        for action in self._actionavails['repoopen']:
            action.setEnabled(someRepoOpen)
        for action in self._actionvisibles['repoopen']:
            action.setVisible(someRepoOpen)

        # Update actions affected by repo open/close/change
        self._updateTaskViewMenu()
        self._updateToolBarActions()

    @pyqtSlot()
    def _updateWindowTitle(self):
        w = self._currentRepoWidget()
        if not w:
            self.setWindowTitle(_('TortoiseHg Workbench'))
        elif w.repo.ui.configbool('tortoisehg', 'fullpath'):
            self.setWindowTitle(_('%s - TortoiseHg Workbench - %s') %
                                (w.title(), w.repoRootPath()))
        else:
            self.setWindowTitle(_('%s - TortoiseHg Workbench') % w.title())

    @pyqtSlot()
    def _updateToolBarActions(self):
        w = self._currentRepoWidget()
        if w:
            self.filtertbaction.setChecked(w.filterBarVisible())

    @pyqtSlot()
    def _updateTaskViewMenu(self):
        'Update task tab menu for current repository'
        repoWidget = self._currentRepoWidget()
        if not repoWidget:
            for a in self.actionGroupTaskView.actions():
                a.setChecked(False)
            if self.actionSelectTaskPbranch is not None:
                self.actionSelectTaskPbranch.setVisible(False)
            self.lockToolAction.setVisible(False)
        else:
            exts = repoWidget.repo.extensions()
            if self.actionSelectTaskPbranch is not None:
                self.actionSelectTaskPbranch.setVisible('pbranch' in exts)
            name = repoWidget.currentTaskTabName()
            for action in self.actionGroupTaskView.actions():
                action.setChecked(str(action.data().toString()) == name)
            self.lockToolAction.setVisible('simplelock' in exts)
        self._updateShowConsoleAction()

        for i, a in enumerate(a for a in self.actionGroupTaskView.actions()
                              if a.isVisible()):
            a.setShortcut('Alt+%d' % (i + 1))

    @pyqtSlot()
    def _updateHistoryActions(self):
        'Update back / forward actions'
        rw = self._currentRepoWidget()
        self.actionBack.setEnabled(bool(rw and rw.canGoBack()))
        self.actionForward.setEnabled(bool(rw and rw.canGoForward()))

    @pyqtSlot()
    def repoTabChanged(self):
        self._updateHistoryActions()
        self._updateMenu()
        self._updateWindowTitle()

    @pyqtSlot(str)
    def _onCurrentRepoChanged(self, curpath):
        curpath = unicode(curpath)
        self._console.setCurrentRepoRoot(curpath or None)
        self.reporegistry.setActiveTabRepo(curpath)
        if curpath:
            repoagent = self._repomanager.repoAgent(curpath)
            repo = repoagent.rawRepo()
            self.mqpatches.setRepoAgent(repoagent)
            self._setupCustomTools(repo.ui)
            self._setupUrlCombo(repo)
            self._updateAbortAction(repoagent)
        else:
            self.mqpatches.setRepoAgent(None)
            self.actionAbort.setEnabled(False)

    @pyqtSlot()
    def _setHistoryColumns(self):
        """Display the column selection dialog"""
        w = self._currentRepoWidget()
        assert w
        w.repoview.setHistoryColumns()

    def _repotogglefwd(self, name):
        """Return function to forward action to the current repo tab"""
        def forwarder(checked):
            w = self._currentRepoWidget()
            if w:
                getattr(w, name)(checked)
        return forwarder

    def _repofwd(self, name, params=[], namedparams={}):
        """Return function to forward action to the current repo tab"""
        def forwarder():
            w = self._currentRepoWidget()
            if w:
                getattr(w, name)(*params, **namedparams)

        return forwarder

    @pyqtSlot()
    def refresh(self):
        clear = QApplication.keyboardModifiers() & Qt.ControlModifier
        w = self._currentRepoWidget()
        if w:
            # check unnoticed changes to emit corresponding signals
            repoagent = self._repomanager.repoAgent(w.repoRootPath())
            if clear:
                repoagent.clearStatus()
            repoagent.pollStatus()
            # TODO if all objects are responsive to repository signals, some
            # of the following actions are not necessary
            w.reload()

    @pyqtSlot(QAction)
    def _runSyncAction(self, action):
        w = self._currentRepoWidget()
        if w:
            op = str(action.data().toString())
            w.setSyncUrl(self._syncUrlFor(op) or '')
            getattr(w, op)()

    @pyqtSlot()
    def _runSyncBookmarks(self):
        w = self._currentRepoWidget()
        if w:
            # the sync bookmark dialog is bidirectional but is only able to
            # handle one remote location therefore we use the push location
            w.setSyncUrl(self._syncUrlFor('push') or '')
            w.syncBookmark()

    @pyqtSlot()
    def _abortCommands(self):
        root = self.currentRepoRootPath()
        if not root:
            return
        repoagent = self._repomanager.repoAgent(root)
        repoagent.abortCommands()

    def _updateAbortAction(self, repoagent):
        self.actionAbort.setEnabled(repoagent.isBusy())

    @pyqtSlot(str)
    def _onBusyChanged(self, root):
        repoagent = self._repomanager.repoAgent(root)
        self._updateAbortAction(repoagent)
        if not repoagent.isBusy():
            self.statusbar.clearRepoProgress(root)
        self.statusbar.setRepoBusy(root, repoagent.isBusy())

    def serve(self):
        self._dialogs.open(Workbench._createServeDialog)

    def _createServeDialog(self):
        w = self._currentRepoWidget()
        if w:
            return serve.run(w.repo.ui, root=w.repo.root)
        else:
            return serve.run(self.ui)

    def loadall(self):
        w = self._currentRepoWidget()
        if w:
            w.repoview.model().loadall()

    def _gotorev(self):
        rev, ok = qtlib.getTextInput(self,
                                     _("Goto revision"),
                                     _("Enter revision identifier"))
        if ok:
            self.gotorev(rev)

    @pyqtSlot(str)
    def gotorev(self, rev):
        w = self._currentRepoWidget()
        if w:
            w.repoview.goto(rev)

    def newWorkbench(self):
        cmdline = list(paths.get_thg_command())
        cmdline.extend(['workbench', '--nofork', '--newworkbench'])
        subprocess.Popen(cmdline, creationflags=qtlib.openflags)

    def newRepository(self):
        """ Run init dialog """
        from tortoisehg.hgqt.hginit import InitDialog
        path = self.currentRepoRootPath() or '.'
        dlg = InitDialog(self.ui, path, self)
        if dlg.exec_() == 0:
            self.openRepo(dlg.destination(), False)

    @pyqtSlot()
    @pyqtSlot(str)
    def cloneRepository(self, uroot=None):
        """ Run clone dialog """
        # it might be better to reuse existing CloneDialog
        dlg = self._dialogs.openNew(Workbench._createCloneDialog)
        if not uroot:
            uroot = self.currentRepoRootPath()
        if uroot:
            dlg.setSource(uroot)
            dlg.setDestination(uroot + '-clone')

    def _createCloneDialog(self):
        from tortoisehg.hgqt.clone import CloneDialog
        dlg = CloneDialog(self.ui, parent=self)
        dlg.clonedRepository.connect(self._openClonedRepo)
        return dlg

    @pyqtSlot(str, str)
    def _openClonedRepo(self, root, sourceroot):
        root = unicode(root)
        sourceroot = unicode(sourceroot)
        self.reporegistry.addClonedRepo(root, sourceroot)
        self.showRepo(root)

    def openRepository(self):
        """ Open repo from File menu """
        caption = _('Select repository directory to open')
        root = self.currentRepoRootPath()
        if root:
            cwd = os.path.dirname(root)
        else:
            cwd = os.getcwdu()
        FD = QFileDialog
        path = FD.getExistingDirectory(self, caption, cwd,
                                       FD.ShowDirsOnly | FD.ReadOnly)
        self.openRepo(path, False)

    def _currentRepoWidget(self):
        return self.repoTabsWidget.currentWidget()

    def currentRepoRootPath(self):
        return self.repoTabsWidget.currentRepoRootPath()

    def onAbout(self, *args):
        """ Display about dialog """
        from tortoisehg.hgqt.about import AboutDialog
        ad = AboutDialog(self)
        ad.finished.connect(ad.deleteLater)
        ad.exec_()

    def onHelp(self, *args):
        """ Display online help """
        qtlib.openhelpcontents('workbench.html')

    def onHelpExplorer(self, *args):
        """ Display online help for shell extension """
        qtlib.openhelpcontents('explorer.html')

    def onReadme(self, *args):
        """Display the README file or URL for the current repo, or the global
        README if no repo is open"""
        readme = None
        def getCurrentReadme(repo):
            """
            Get the README file that is configured for the current repo.

            README files can be set in 3 ways, which are checked in the
            following order of decreasing priority:
            - From the tortoisehg.readme key on the current repo's configuration
              file
            - An existing "README" file found on the repository root
                * Valid README files are those called README and whose extension
                  is one of the following:
                    ['', '.txt', '.html', '.pdf', '.doc', '.docx', '.ppt', '.pptx',
                     '.markdown', '.textile', '.rdoc', '.org', '.creole',
                     '.mediawiki','.rst', '.asciidoc', '.pod']
                * Note that the match is CASE INSENSITIVE on ALL OSs.
            - From the tortoisehg.readme key on the user's global configuration file
            """
            readme = None
            if repo:
                # Try to get the README configured for the repo of the current tab
                readmeglobal = self.ui.config('tortoisehg', 'readme', None)
                if readmeglobal:
                    # Note that repo.ui.config() falls back to the self.ui.config()
                    # if the key is not set on the current repo's configuration file
                    readme = repo.ui.config('tortoisehg', 'readme', None)
                    if readmeglobal != readme:
                        # The readme is set on the current repo configuration file
                        return readme

                # Otherwise try to see if there is a file at the root of the
                # repository that matches any of the valid README file names
                # (in a non case-sensitive way)
                # Note that we try to match the valid README names in order
                validreadmes = ['readme.txt', 'read.me', 'readme.html',
                                'readme.pdf', 'readme.doc', 'readme.docx',
                                'readme.ppt', 'readme.pptx',
                                'readme.md', 'readme.markdown', 'readme.mkdn',
                                'readme.rst', 'readme.textile', 'readme.rdoc',
                                'readme.asciidoc', 'readme.org', 'readme.creole',
                                'readme.mediawiki', 'readme.pod', 'readme']

                readmefiles = [filename for filename in os.listdir(repo.root)
                               if filename.lower().startswith('read')]
                for validname in validreadmes:
                    for filename in readmefiles:
                        if filename.lower() == validname:
                            return repo.wjoin(filename)

            # Otherwise try use the global setting (or None if readme is just
            # not configured)
            return readmeglobal

        w = self._currentRepoWidget()
        if w:
            # Try to get the help doc from the current repo tap
            readme = getCurrentReadme(w.repo)

        if readme:
            qtlib.openlocalurl(os.path.expandvars(os.path.expandvars(readme)))
        else:
            qtlib.WarningMsgBox(_("README not configured"),
                _("A README file is not configured for the current repository.<p>"
                "To configure a README file for a repository, "
                "open the repository settings file, add a '<i>readme</i>' "
                "key to the '<i>tortoisehg</i>' section, and set it "
                "to the filename or URL of your repository's README file."))

    def _storeSettings(self, repostosave, lastactiverepo):
        s = QSettings()
        wb = "Workbench/"
        s.setValue(wb + 'geometry', self.saveGeometry())
        s.setValue(wb + 'windowState', self.saveState())
        s.setValue(wb + 'dockedConsole', self._actionDockedConsole.isChecked())
        s.setValue(wb + 'saveRepos', self.actionSaveRepos.isChecked())
        s.setValue(wb + 'saveLastSyncPaths',
            self.actionSaveLastSyncPaths.isChecked())
        s.setValue(wb + 'lastactiverepo', lastactiverepo)
        s.setValue(wb + 'openrepos', (',').join(repostosave))
        s.beginWriteArray('lastreposyncpaths')
        lastreposyncpaths = {}
        if self.actionSaveLastSyncPaths.isChecked():
            lastreposyncpaths = self._lastRepoSyncPath
        for n, root in enumerate(sorted(lastreposyncpaths)):
            s.setArrayIndex(n)
            s.setValue('root', root)
            s.setValue('path', self._lastRepoSyncPath[root])
        s.endArray()

    def restoreSettings(self):
        s = QSettings()
        wb = "Workbench/"
        self.restoreGeometry(s.value(wb + 'geometry').toByteArray())
        self.restoreState(s.value(wb + 'windowState').toByteArray())
        self._actionDockedConsole.setChecked(
            s.value(wb + 'dockedConsole', True).toBool())

        lastreposyncpaths = {}
        npaths = s.beginReadArray('lastreposyncpaths')
        for n in range(npaths):
            s.setArrayIndex(n)
            root = unicode(s.value('root').toString())
            lastreposyncpaths[root] = s.value('path').toString()
        s.endArray()
        self._lastRepoSyncPath = lastreposyncpaths

        save = s.value(wb + 'saveRepos').toBool()
        self.actionSaveRepos.setChecked(save)
        savelastsyncpaths = s.value(wb + 'saveLastSyncPaths').toBool()
        self.actionSaveLastSyncPaths.setChecked(savelastsyncpaths)

        openreposvalue = unicode(s.value(wb + 'openrepos').toString())
        if openreposvalue:
            openrepos = openreposvalue.split(',')
        else:
            openrepos = []
        # Note that if a "root" has been passed to the "thg" command,
        # "lastactiverepo" will have no effect
        lastactiverepo = unicode(s.value(wb + 'lastactiverepo').toString())
        self.repoTabsWidget.restoreRepos(openrepos, lastactiverepo)

        # Clear the lastactiverepo and the openrepos list once the workbench state
        # has been reload, so that opening additional workbench windows does not
        # reopen these repos again
        s.setValue(wb + 'openrepos', '')
        s.setValue(wb + 'lastactiverepo', '')

    def goto(self, root, rev):
        if self.repoTabsWidget.selectRepo(hglib.tounicode(root)):
            rw = self.repoTabsWidget.currentWidget()
            rw.goto(rev)

    def closeEvent(self, event):
        repostosave = []
        lastactiverepo = ''
        if self.actionSaveRepos.isChecked():
            tw = self.repoTabsWidget
            repostosave = map(tw.repoRootPath, xrange(tw.count()))
            lastactiverepo = tw.currentRepoRootPath()
        if not self.repoTabsWidget.closeAllTabs():
            event.ignore()
        else:
            self._storeSettings(repostosave, lastactiverepo)
            self.reporegistry.close()

    @pyqtSlot()
    def closeCurrentRepoTab(self):
        """close the current repo tab"""
        self.repoTabsWidget.closeTab(self.repoTabsWidget.currentIndex())

    def explore(self):
        root = self.currentRepoRootPath()
        if root:
            qtlib.openlocalurl(hglib.fromunicode(root))

    def terminal(self):
        w = self._currentRepoWidget()
        if w:
            qtlib.openshell(w.repo.root, hglib.fromunicode(w.repoDisplayName()),
                            w.repo.ui)

    @pyqtSlot()
    def editSettings(self, focus=None):
        sd = SettingsDialog(configrepo=False, focus=focus,
                            parent=self,
                            root=hglib.fromunicode(self.currentRepoRootPath()))
        sd.exec_()

    @pyqtSlot()
    def _editCustomToolsSettings(self):
        self.editSettings('tools')
