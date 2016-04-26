# repotab.py - stack of repository widgets
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright 2014 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os

from PyQt4.QtCore import Qt, SIGNAL, SLOT, pyqtSignal, pyqtSlot
from PyQt4.QtCore import QObject, QPoint, QSignalMapper
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, qtlib, repowidget

class _TabBar(QTabBar):

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MidButton:
            self.tabCloseRequested.emit(self.tabAt(event.pos()))
        super(_TabBar, self).mouseReleaseEvent(event)


class RepoTabWidget(QWidget):
    """Manage stack of RepoWidgets of open repositories"""

    currentRepoChanged = pyqtSignal(str, str)  # curpath, prevpath
    currentTabChanged = pyqtSignal(int)
    currentTaskTabChanged = pyqtSignal()
    currentTitleChanged = pyqtSignal()
    historyChanged = pyqtSignal()
    makeLogVisible = pyqtSignal(bool)
    progressReceived = pyqtSignal(str, cmdcore.ProgressMessage)
    showMessageSignal = pyqtSignal(str)
    toolbarVisibilityChanged = pyqtSignal(bool)

    # look-up of tab-index and stack-index:
    # 1. tabbar[tab-index] -> {tabData: rw, tabToolTip: root}
    # 2. stack[rw] -> stack-index
    #
    # tab-index is the master, so do not use stack.setCurrentIndex().

    def __init__(self, ui, repomanager, parent=None):
        super(RepoTabWidget, self).__init__(parent)
        self._ui = ui
        self._repomanager = repomanager
        # delay until the next event loop so that the current tab won't be
        # gone in the middle of switching tabs (issue #4253)
        repomanager.repositoryDestroyed.connect(self.closeRepo,
                                                Qt.QueuedConnection)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._tabbar = tabbar = _TabBar(self)

        if qtlib.IS_RETINA:
            tabbar.setIconSize(qtlib.barRetinaIconSize())
        tabbar.setDocumentMode(True)
        tabbar.setExpanding(False)
        tabbar.setTabsClosable(True)
        tabbar.setMovable(True)
        tabbar.currentChanged.connect(self._onCurrentTabChanged)
        tabbar.tabCloseRequested.connect(self.closeTab)
        tabbar.hide()
        vbox.addWidget(tabbar)

        self._initTabMenuActions()
        tabbar.setContextMenuPolicy(Qt.CustomContextMenu)
        tabbar.customContextMenuRequested.connect(self._onTabMenuRequested)

        self._stack = QStackedLayout()
        vbox.addLayout(self._stack, 1)

        self._curpath = ''  # != currentRepoRootPath until _onCurrentTabChanged
        self._lastclickedindex = -1
        self._lastclosedpaths = []

        self._iconmapper = QSignalMapper(self)
        self._iconmapper.mapped[QWidget].connect(self._updateIcon)
        self._titlemapper = QSignalMapper(self)
        self._titlemapper.mapped[QWidget].connect(self._updateTitle)

    def openRepo(self, root, bundle=None):
        """Open the specified repository in new tab"""
        rw = self._createRepoWidget(root, bundle)
        if not rw:
            return False
        # do not emit currentChanged until tab properties are fully set up.
        # the first tab is automatically selected.
        tabbar = self._tabbar
        tabbar.blockSignals(True)
        index = tabbar.insertTab(self._newTabIndex(), rw.title())
        tabbar.setTabData(index, rw)
        tabbar.setTabToolTip(index, rw.repoRootPath())
        self.setCurrentIndex(index)
        tabbar.blockSignals(False)
        self._updateTabVisibility()
        self._onCurrentTabChanged(index)
        return True

    def _addUnloadedRepos(self, rootpaths):
        """Add tabs of the specified repositories without loading them"""
        tabbar = self._tabbar
        tabbar.blockSignals(True)
        for index, root in enumerate(rootpaths, self._newTabIndex()):
            root = hglib.normreporoot(root)
            index = tabbar.insertTab(index, os.path.basename(root))
            tabbar.setTabToolTip(index, root)
        tabbar.blockSignals(False)
        self._updateTabVisibility()
        # must call _onCurrentTabChanged() appropriately

    def _newTabIndex(self):
        if self._ui.configbool('tortoisehg', 'opentabsaftercurrent', True):
            return self.currentIndex() + 1
        else:
            return self.count()

    @pyqtSlot(str)
    def closeRepo(self, root):
        """Close tabs of the specified repository"""
        root = hglib.normreporoot(root)
        return self._closeTabs(list(self._findIndexesByRepoRootPath(root)))

    @pyqtSlot(int)
    def closeTab(self, index):
        if 0 <= index < self.count():
            return self._closeTabs([index])
        return False

    def closeAllTabs(self):
        return self._closeTabs(range(self.count()))

    def _closeTabs(self, indexes):
        if not self._checkTabsClosable(indexes):
            return False
        self._lastclosedpaths = map(self.repoRootPath, indexes)
        self._removeTabs(indexes)
        return True

    def _checkTabsClosable(self, indexes):
        for i in indexes:
            rw = self._widget(i)
            if rw and not rw.closeRepoWidget():
                self.setCurrentIndex(i)
                return False
        return True

    def _removeTabs(self, indexes):
        # must call _checkRepoTabsClosable() before
        indexes = sorted(indexes, reverse=True)
        tabchange = indexes and indexes[-1] <= self.currentIndex()
        self._tabbar.blockSignals(True)
        for i in indexes:
            rw = self._widget(i)
            self._tabbar.removeTab(i)
            if rw:
                self._stack.removeWidget(rw)
                self._repomanager.releaseRepoAgent(rw.repoRootPath())
                rw.deleteLater()
        self._tabbar.blockSignals(False)
        self._updateTabVisibility()
        if tabchange:
            self._onCurrentTabChanged(self.currentIndex())

    def selectRepo(self, root):
        """Find the tab for the specified repository and make it current"""
        root = hglib.normreporoot(root)
        if self.currentRepoRootPath() == root:
            return True
        for i in self._findIndexesByRepoRootPath(root):
            self.setCurrentIndex(i)
            return True
        return False

    def restoreRepos(self, rootpaths, activepath):
        """Restore tabs of the last open repositories"""
        if not rootpaths:
            return
        self._addUnloadedRepos(rootpaths)
        self._tabbar.blockSignals(True)
        self.selectRepo(activepath)
        self._tabbar.blockSignals(False)
        self._onCurrentTabChanged(self.currentIndex())

    def _initTabMenuActions(self):
        actiondefs = [
            ('closetab', _('Close tab'),
             _('Close tab'), self._closeLastClickedTab),
            ('closeothertabs', _('Close other tabs'),
             _('Close other tabs'), self._closeNotLastClickedTabs),
            ('reopenlastclosed', _('Undo close tab'),
             _('Reopen last closed tab'), self._reopenLastClosedTabs),
            ('reopenlastclosedgroup', _('Undo close other tabs'),
             _('Reopen last closed tab group'), self._reopenLastClosedTabs),
            ]
        self._actions = {}
        for name, desc, tip, cb in actiondefs:
            self._actions[name] = act = QAction(desc, self)
            act.setStatusTip(tip)
            act.triggered.connect(cb)
            self.addAction(act)

    @pyqtSlot(QPoint)
    def _onTabMenuRequested(self, point):
        index = self._tabbar.tabAt(point)
        if index >= 0:
            self._lastclickedindex = index
        else:
            self._lastclickedindex = self.currentIndex()

        menu = QMenu(self)
        menu.addAction(self._actions['closetab'])
        menu.addAction(self._actions['closeothertabs'])
        menu.addSeparator()
        if len(self._lastclosedpaths) > 1:
            menu.addAction(self._actions['reopenlastclosedgroup'])
        elif self._lastclosedpaths:
            menu.addAction(self._actions['reopenlastclosed'])
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(self._tabbar.mapToGlobal(point))

    @pyqtSlot()
    def _closeLastClickedTab(self):
        self.closeTab(self._lastclickedindex)

    @pyqtSlot()
    def _closeNotLastClickedTabs(self):
        if self._lastclickedindex >= 0:
            self._closeTabs([i for i in xrange(self.count())
                             if i != self._lastclickedindex])

    @pyqtSlot()
    def _reopenLastClosedTabs(self):
        origindex = self.currentIndex()
        self._addUnloadedRepos(self._lastclosedpaths)
        del self._lastclosedpaths[:]
        if origindex != self.currentIndex():
            self._onCurrentTabChanged(self.currentIndex())

    def currentRepoRootPath(self):
        return self.repoRootPath(self.currentIndex())

    def repoRootPath(self, index):
        return unicode(self._tabbar.tabToolTip(index))

    def _findIndexesByRepoRootPath(self, root):
        for i in xrange(self.count()):
            if self.repoRootPath(i) == root:
                yield i

    def count(self):
        """Number of tabs including repositories of not-yet opened"""
        return self._tabbar.count()

    def currentIndex(self):
        return self._tabbar.currentIndex()

    def currentWidget(self):
        return self._stack.currentWidget()

    @pyqtSlot(int)
    def setCurrentIndex(self, index):
        self._tabbar.setCurrentIndex(index)

    @pyqtSlot(int)
    def _onCurrentTabChanged(self, index):
        rw = self._widget(index)
        if not rw and index >= 0:
            tabbar = self._tabbar
            rw = self._createRepoWidget(self.repoRootPath(index))
            if not rw:
                tabbar.removeTab(index)  # may reenter
                self._updateTabVisibility()
                return
            tabbar.setTabData(index, rw)
            tabbar.setTabText(index, rw.title())
            # update path in case filesystem changed after tab was added
            tabbar.setTabToolTip(index, rw.repoRootPath())
        if rw:
            self._stack.setCurrentWidget(rw)

        prevpath = self._curpath
        self._curpath = self.repoRootPath(index)
        self.currentTabChanged.emit(index)
        # there may be more than one tabs of the same repo
        if self._curpath != prevpath:
            self._onCurrentRepoChanged(self._curpath, prevpath)

    def _onCurrentRepoChanged(self, curpath, prevpath):
        prevrepoagent = currepoagent = None
        if prevpath:
            prevrepoagent = self._repomanager.repoAgent(prevpath)  # may be None
        if curpath:
            currepoagent = self._repomanager.repoAgent(curpath)
        if prevrepoagent:
            prevrepoagent.suspendMonitoring()
        if currepoagent:
            currepoagent.resumeMonitoring()
        self.currentRepoChanged.emit(curpath, prevpath)

    def _indexOf(self, rw):
        if self.currentWidget() is rw:
            return self.currentIndex()  # fast path
        for i in xrange(self.count()):
            if self._widget(i) is rw:
                return i
        return -1

    def _widget(self, index):
        return self._tabbar.tabData(index).toPyObject()

    def _createRepoWidget(self, root, bundle=None):
        try:
            repoagent = self._repomanager.openRepoAgent(root)
        except (error.Abort, error.RepoError), e:
            qtlib.WarningMsgBox(_('Failed to open repository'),
                                hglib.tounicode(str(e)), parent=self)
            return
        rw = repowidget.RepoWidget(repoagent, self, bundle=bundle)
        rw.currentTaskTabChanged.connect(self.currentTaskTabChanged)
        rw.makeLogVisible.connect(self.makeLogVisible)
        rw.progress.connect(self._mapProgressReceived)
        rw.repoLinkClicked.connect(self._openLinkedRepo)
        rw.revisionSelected.connect(self.historyChanged)
        rw.showMessageSignal.connect(self.showMessageSignal)
        rw.toolbarVisibilityChanged.connect(self.toolbarVisibilityChanged)
        # PyQt 4.6 cannot find compatible signal by new-style connection
        QObject.connect(rw, SIGNAL('busyIconChanged()'),
                        self._iconmapper, SLOT('map()'))
        self._iconmapper.setMapping(rw, rw)
        QObject.connect(rw, SIGNAL('titleChanged(QString)'),
                        self._titlemapper, SLOT('map()'))
        self._titlemapper.setMapping(rw, rw)
        self._stack.addWidget(rw)
        return rw

    @qtlib.senderSafeSlot(str, object, str, str, object)
    def _mapProgressReceived(self, topic, pos, item, unit, total):
        rw = self.sender()
        assert isinstance(rw, repowidget.RepoWidget)
        progress = cmdcore.ProgressMessage(
            unicode(topic), pos, unicode(item), unicode(unit), total)
        self.progressReceived.emit(rw.repoRootPath(), progress)

    @pyqtSlot(str)
    def _openLinkedRepo(self, path):
        uri = unicode(path).split('?', 1)
        path = hglib.normreporoot(uri[0])
        rev = None
        if len(uri) > 1:
            rev = hglib.fromunicode(uri[1])
        if self.selectRepo(path) or self.openRepo(path):
            rw = self.currentWidget()
            if rev:
                rw.goto(rev)
            else:
                # assumes that the request comes from commit widget; in this
                # case, the user is going to commit changes to this repo.
                rw.switchToNamedTaskTab('commit')

    @pyqtSlot(QWidget)
    def _updateIcon(self, rw):
        index = self._indexOf(rw)
        self._tabbar.setTabIcon(index, rw.busyIcon())

    @pyqtSlot(QWidget)
    def _updateTitle(self, rw):
        index = self._indexOf(rw)
        self._tabbar.setTabText(index, rw.title())
        if index == self.currentIndex():
            self.currentTitleChanged.emit()

    def _updateTabVisibility(self):
        forcetab = self._ui.configbool('tortoisehg', 'forcerepotab')
        self._tabbar.setVisible(self.count() > 1
                                or (self.count() == 1 and forcetab))
