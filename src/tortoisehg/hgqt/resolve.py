# resolve.py - TortoiseHg merge conflict resolve
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
from tortoisehg.hgqt import qtlib, cmdcore, cmdui, csinfo, visdiff, thgrepo

MARGINS = (8, 0, 0, 0)

class ResolveDialog(QDialog):
    def __init__(self, repoagent, parent=None):
        super(ResolveDialog, self).__init__(parent)
        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint
                            | Qt.WindowMaximizeButtonHint)
        self.setWindowTitle(_('Resolve Conflicts - %s')
                            % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-merge'))

        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(5)

        hbox = QHBoxLayout()
        self.layout().addLayout(hbox)

        self.refreshButton = tb = QToolButton(self)
        tb.setIcon(qtlib.geticon('view-refresh'))
        tb.setShortcut(QKeySequence.Refresh)
        tb.clicked.connect(self.refresh)
        self.stlabel = QLabel()
        hbox.addWidget(tb)
        hbox.addWidget(self.stlabel)

        def revisionInfoLayout(repo):
            """
            Return a layout containg the revision information (local and other)
            """
            hbox = QHBoxLayout()
            hbox.setSpacing(0)
            hbox.setContentsMargins(*MARGINS)

            vbox = QVBoxLayout()
            vbox.setContentsMargins(*MARGINS)
            hbox.addLayout(vbox)
            localrevtitle = qtlib.LabeledSeparator(_('Local revision '
                                                     'information'))
            localrevinfo = csinfo.create(repo)
            localrevinfo.update(repo[None].p1())
            vbox.addWidget(localrevtitle)
            vbox.addWidget(localrevinfo)
            vbox.addStretch()

            vbox = QVBoxLayout()
            vbox.setContentsMargins(*MARGINS)
            hbox.addLayout(vbox)
            otherrevtitle = qtlib.LabeledSeparator(_('Other revision '
                                                     'information'))
            otherrevinfo = csinfo.create(repo)
            otherrevinfo.update(repo[None].p2())

            vbox.addWidget(otherrevtitle)
            vbox.addWidget(otherrevinfo)
            vbox.addStretch()

            return hbox

        if len(self.repo[None].parents()) > 1:
            self.layout().addLayout(revisionInfoLayout(self.repo))

        unres = qtlib.LabeledSeparator(_('Unresolved conflicts'))
        self.layout().addWidget(unres)

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        hbox.setContentsMargins(*MARGINS)
        self.layout().addLayout(hbox)

        self.utree = QTreeView(self)
        self.utree.setDragDropMode(QTreeView.DragOnly)
        self.utree.setSelectionMode(QTreeView.ExtendedSelection)
        self.utree.setSortingEnabled(True)
        hbox.addWidget(self.utree)

        self.utree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.utreecmenu = QMenu(self)
        mergeactions = QActionGroup(self)
        mergeactions.triggered.connect(self._mergeByAction)
        cmauto = self.utreecmenu.addAction(_('Mercurial Re&solve'))
        cmauto.setToolTip(_('Attempt automatic (trivial) merge'))
        cmauto.setData('internal:merge')
        mergeactions.addAction(cmauto)
        cmmanual = self.utreecmenu.addAction(_('Tool &Resolve'))
        cmmanual.setToolTip(_('Merge using selected merge tool'))
        mergeactions.addAction(cmmanual)
        cmlocal = self.utreecmenu.addAction(_('&Take Local'))
        cmlocal.setToolTip(_('Accept the local file version (yours)'))
        cmlocal.setData('internal:local')
        mergeactions.addAction(cmlocal)
        cmother = self.utreecmenu.addAction(_('Take &Other'))
        cmother.setToolTip(_('Accept the other file version (theirs)'))
        cmother.setData('internal:other')
        mergeactions.addAction(cmother)
        cmres = self.utreecmenu.addAction(_('&Mark as Resolved'))
        cmres.setToolTip(_('Mark this file as resolved'))
        cmres.triggered.connect(self.markresolved)
        self.utreecmenu.addSeparator()
        cmdiffLocToAnc = self.utreecmenu.addAction(_('Diff &Local to Ancestor'))
        cmdiffLocToAnc.triggered.connect(self.diffLocToAnc)
        cmdiffOthToAnc = self.utreecmenu.addAction(_('&Diff Other to Ancestor'))
        cmdiffOthToAnc.triggered.connect(self.diffOthToAnc)
        self.umenuitems = (cmauto, cmmanual, cmlocal, cmother, cmres,
                           cmdiffLocToAnc, cmdiffOthToAnc)
        self.utree.customContextMenuRequested.connect(self.utreeMenuRequested)

        self.utree.doubleClicked.connect(self.utreeDoubleClicked)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(*MARGINS)
        hbox.addLayout(vbox)
        for action in [cmauto, cmmanual, cmlocal, cmother, cmres]:
            vbox.addWidget(qtlib.ActionPushButton(action, self))
        vbox.addStretch(1)

        res = qtlib.LabeledSeparator(_('Resolved conflicts'))
        self.layout().addWidget(res)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(*MARGINS)
        hbox.setSpacing(0)
        self.layout().addLayout(hbox)

        self.rtree = QTreeView(self)
        self.rtree.setDragDropMode(QTreeView.DragOnly)
        self.rtree.setSelectionMode(QTreeView.ExtendedSelection)
        self.rtree.setSortingEnabled(True)
        hbox.addWidget(self.rtree)

        self.rtree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.rtreecmenu = QMenu(self)
        cmedit = self.rtreecmenu.addAction(_('&Edit File'))
        cmedit.setToolTip(_('Edit resolved file'))
        cmedit.triggered.connect(self.edit)
        cmv3way = self.rtreecmenu.addAction(_('3-&Way Diff'))
        cmv3way.setToolTip(_('Visual three-way diff'))
        cmv3way.triggered.connect(self.v3way)
        cmvp0 = self.rtreecmenu.addAction(_('Diff to &Local'))
        cmvp0.setToolTip(_('Visual diff between resolved file and first '
                           'parent'))
        cmvp0.triggered.connect(self.vp0)
        cmvp1 = self.rtreecmenu.addAction(_('&Diff to Other'))
        cmvp1.setToolTip(_('Visual diff between resolved file and second '
                           'parent'))
        cmvp1.triggered.connect(self.vp1)
        cmures = self.rtreecmenu.addAction(_('Mark as &Unresolved'))
        cmures.setToolTip(_('Mark this file as unresolved'))
        cmures.triggered.connect(self.markunresolved)
        self.rmenuitems = (cmedit, cmvp0, cmures)
        self.rmmenuitems = (cmvp1, cmv3way)
        self.rtree.customContextMenuRequested.connect(self.rtreeMenuRequested)

        self.rtree.doubleClicked.connect(self.v3way)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(*MARGINS)
        hbox.addLayout(vbox)
        for action in [cmedit, cmv3way, cmvp0, cmvp1, cmures]:
            vbox.addWidget(qtlib.ActionPushButton(action, self))
        vbox.addStretch(1)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(*MARGINS)
        hbox.setSpacing(4)
        self.layout().addLayout(hbox)

        self.tcombo = ToolsCombo(self.repo, self)
        hbox.addWidget(QLabel(_('Detected merge/diff tools:')))
        hbox.addWidget(self.tcombo)
        hbox.addStretch(1)

        out = qtlib.LabeledSeparator(_('Command output'))
        self.layout().addWidget(out)
        self._cmdlog = cmdui.LogWidget(self)
        self.layout().addWidget(self._cmdlog)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Close)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        s = QSettings()
        self.restoreGeometry(s.value('resolve/geom').toByteArray())

        self.refresh()
        self.utree.selectAll()
        self.utree.setFocus()
        repoagent.configChanged.connect(self.tcombo.reset)
        repoagent.repositoryChanged.connect(self.refresh)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def getSelectedPaths(self, tree):
        paths = []
        if not tree.selectionModel():
            return paths
        for idx in tree.selectionModel().selectedRows():
            root, wfile = tree.model().getPathForIndex(idx)
            paths.append((root, wfile))
        return paths

    def runCommand(self, tree, cmdline):
        cmdlines = []
        selected = self.getSelectedPaths(tree)
        while selected:
            curroot = selected[0][0]
            cmd = cmdline + ['--repository', curroot, '--']
            for root, wfile in selected:
                if root == curroot:
                    cmd.append(os.path.normpath(os.path.join(root, wfile)))
            cmdlines.append(map(hglib.tounicode, cmd))
            selected = [(r, w) for r, w in selected if r != curroot]
        if cmdlines:
            sess = self._repoagent.runCommandSequence(cmdlines, self)
            self._cmdsession = sess
            sess.commandFinished.connect(self.refresh)
            sess.outputReceived.connect(self._cmdlog.appendLog)
            self._updateActions()

    def merge(self, tool=False):
        if not tool:
            tool = self.tcombo.readValue()
        cmd = ['resolve']
        if tool:
            cmd += ['--tool='+tool]
        self.runCommand(self.utree, cmd)

    @pyqtSlot(QAction)
    def _mergeByAction(self, action):
        tool = str(action.data().toString())
        self.merge(tool)

    def markresolved(self):
        self.runCommand(self.utree, ['resolve', '--mark'])

    def markunresolved(self):
        self.runCommand(self.rtree, ['resolve', '--unmark'])

    def edit(self):
        paths = self.getSelectedPaths(self.rtree)
        if paths:
            abspaths = [os.path.join(r, w) for r, w in paths]
            qtlib.editfiles(self.repo, abspaths, parent=self)

    def getVdiffFiles(self, tree):
        paths = self.getSelectedPaths(tree)
        if not paths:
            return []
        files, sub = [], False
        for root, wfile in paths:
            if root == self.repo.root:
                files.append(wfile)
            else:
                sub = True
        if sub:
            qtlib.InfoMsgBox(_('Unable to show subrepository files'),
                    _('Visual diffs are not supported for files in '
                      'subrepositories. They will not be shown.'))
        return files

    def v3way(self):
        paths = self.getVdiffFiles(self.rtree)
        if paths:
            opts = {}
            opts['rev'] = []
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def vp0(self):
        paths = self.getVdiffFiles(self.rtree)
        if paths:
            opts = {}
            opts['rev'] = ['p1()']
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def vp1(self):
        paths = self.getVdiffFiles(self.rtree)
        if paths:
            opts = {}
            opts['rev'] = ['p2()']
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def diffLocToAnc(self):
        paths = self.getVdiffFiles(self.utree)
        if paths:
            opts = {}
            opts['rev'] = ['ancestor(p1(),p2())..p1()']
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def diffOthToAnc(self):
        paths = self.getVdiffFiles(self.utree)
        if paths:
            opts = {}
            opts['rev'] = ['ancestor(p1(),p2())..p2()']
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    @pyqtSlot()
    def refresh(self):
        u, r = [], []
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                u.append((root, path))
            else:
                r.append((root, path))
        paths = self.getSelectedPaths(self.utree)
        oldmodel = self.utree.model()
        self.utree.setModel(PathsModel(u, self))
        self.utree.resizeColumnToContents(0)
        self.utree.resizeColumnToContents(1)
        if oldmodel:
            oldmodel.setParent(None)  # gc-ed

        model = self.utree.model()
        smodel = self.utree.selectionModel()
        sflags = QItemSelectionModel.Select | QItemSelectionModel.Rows
        for i, path in enumerate(u):
            if path in paths:
                smodel.select(model.index(i, 0), sflags)

        smodel.selectionChanged.connect(self._updateUnresolvedActions)
        self._updateUnresolvedActions()

        paths = self.getSelectedPaths(self.rtree)
        oldmodel = self.rtree.model()
        self.rtree.setModel(PathsModel(r, self))
        self.rtree.resizeColumnToContents(0)
        self.rtree.resizeColumnToContents(1)
        if oldmodel:
            oldmodel.setParent(None)  # gc-ed

        model = self.rtree.model()
        smodel = self.rtree.selectionModel()
        for i, path in enumerate(r):
            if path in paths:
                smodel.select(model.index(i, 0), sflags)

        smodel.selectionChanged.connect(self._updateResolvedActions)
        self._updateResolvedActions()

        if u:
            txt = _('There are merge <b>conflicts</b> to be resolved')
        elif r:
            txt = _('All conflicts are resolved.')
        else:
            txt = _('There are no conflicting file merges.')
        self.stlabel.setText(u'<h2>' + txt + u'</h2>')

    def reject(self):
        s = QSettings()
        s.setValue('resolve/geom', self.saveGeometry())
        if self.utree.model().rowCount() > 0:
            main = _('Exit without finishing resolve?')
            text = _('Unresolved conflicts remain. Are you sure?')
            labels = ((QMessageBox.Yes, _('E&xit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                labels=labels, parent=self):
                return
        super(ResolveDialog, self).reject()

    def _updateActions(self):
        self._updateUnresolvedActions()
        self._updateResolvedActions()

    @pyqtSlot()
    def _updateUnresolvedActions(self):
        enable = (self.utree.selectionModel().hasSelection()
                  and self._cmdsession.isFinished())
        for c in self.umenuitems:
            c.setEnabled(enable)

    @pyqtSlot()
    def _updateResolvedActions(self):
        enable = (self.rtree.selectionModel().hasSelection()
                  and self._cmdsession.isFinished())
        for c in self.rmenuitems:
            c.setEnabled(enable)
        merge = len(self.repo[None].parents()) > 1
        for c in self.rmmenuitems:
            c.setEnabled(enable and merge)

    @pyqtSlot(QPoint)
    def utreeMenuRequested(self, point):
        self.utreecmenu.popup(self.utree.viewport().mapToGlobal(point))

    @pyqtSlot(QPoint)
    def rtreeMenuRequested(self, point):
        self.rtreecmenu.popup(self.rtree.viewport().mapToGlobal(point))

    def utreeDoubleClicked(self):
        if self.repo.ui.configbool('tortoisehg', 'autoresolve', True):
            self.merge()
        else:
            self.merge('internal:merge')


class PathsModel(QAbstractTableModel):
    def __init__(self, pathlist, parent):
        QAbstractTableModel.__init__(self, parent)
        self.headers = (_('Path'), _('Ext'), _('Repository'))
        self.rows = []
        for root, path in pathlist:
            name, ext = os.path.splitext(path)
            self.rows.append([path, ext, root])

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0 # no child
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0 # no child
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return QVariant()
        if role == Qt.DisplayRole:
            data = self.rows[index.row()][index.column()]
            return QVariant(hglib.tounicode(data))
        return QVariant()

    def flags(self, index):
        flags = super(PathsModel, self).flags(index)
        if not index.isValid():
            return flags
        flags |= Qt.ItemIsDragEnabled
        return flags

    def headerData(self, col, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()
        else:
            return QVariant(self.headers[col])

    def getPathForIndex(self, index):
        'return root, wfile for the given row'
        row = index.row()
        return self.rows[row][2], self.rows[row][0]

    def mimeTypes(self):
        return ['text/uri-list']

    def mimeData(self, indexes):
        paths = [hglib.tounicode(os.path.join(*self.getPathForIndex(i)))
                 for i in indexes if i.column() == 0]
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return data


class ToolsCombo(QComboBox):
    def __init__(self, repo, parent):
        QComboBox.__init__(self, parent)
        self.setEditable(False)
        self.loaded = False
        self.default = _('<default>')
        self.addItem(self.default)
        self.repo = repo

    @pyqtSlot()
    def reset(self):
        self.loaded = False
        self.clear()
        self.addItem(self.default)

    def showPopup(self):
        if not self.loaded:
            self.loaded = True
            self.clear()
            self.addItem(self.default)
            for t in self.repo.mergetools:
                self.addItem(hglib.tounicode(t))
        QComboBox.showPopup(self)

    def readValue(self):
        if self.loaded:
            text = self.currentText()
            if text != self.default:
                return hglib.fromunicode(text)
        else:
            return None
