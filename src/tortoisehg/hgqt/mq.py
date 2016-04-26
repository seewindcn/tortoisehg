# mq.py - TortoiseHg MQ widget
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os, re

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, qtlib, cmdui
from tortoisehg.hgqt import commit, qdelete, qfold, qrename, rejects

def _checkForRejects(repo, rawoutput, parent=None):
    """Parse output of qpush/qpop to resolve hunk failure manually"""
    rejre = re.compile(r'saving rejects to file (.*)\.rej')
    rejfiles = dict((m.group(1), False) for m in rejre.finditer(rawoutput))
    for wfile in sorted(rejfiles):
        if not os.path.exists(repo.wjoin(wfile)):
            continue
        ufile = hglib.tounicode(wfile)
        if qtlib.QuestionMsgBox(_('Manually resolve rejected chunks?'),
                                _('%s had rejected chunks, edit patched '
                                  'file together with rejects?') % ufile,
                                parent=parent):
            dlg = rejects.RejectsDialog(repo.ui, repo.wjoin(wfile), parent)
            r = dlg.exec_()
            rejfiles[wfile] = (r == QDialog.Accepted)

    # empty rejfiles means we failed to parse output message
    return bool(rejfiles) and all(rejfiles.itervalues())

class QueueManagementActions(QObject):
    """Container for patch queue management actions"""

    def __init__(self, parent=None):
        super(QueueManagementActions, self).__init__(parent)
        assert parent is None or isinstance(parent, QWidget)
        self._repoagent = None
        self._cmdsession = cmdcore.nullCmdSession()

        self._actions = {
            'commitQueue': QAction(_('&Commit to Queue...'), self),
            'createQueue': QAction(_('Create &New Queue...'), self),
            'renameQueue': QAction(_('&Rename Active Queue...'), self),
            'deleteQueue': QAction(_('&Delete Queue...'), self),
            'purgeQueue':  QAction(_('&Purge Queue...'), self),
            }
        for name, action in self._actions.iteritems():
            action.triggered.connect(getattr(self, '_' + name))
        self._updateActions()

    def setRepoAgent(self, repoagent):
        self._repoagent = repoagent
        self._updateActions()

    def _updateActions(self):
        enabled = bool(self._repoagent) and self._cmdsession.isFinished()
        for action in self._actions.itervalues():
            action.setEnabled(enabled)

    def createMenu(self, parent=None):
        menu = QMenu(parent)
        menu.addAction(self._actions['commitQueue'])
        menu.addSeparator()
        for name in ['createQueue', 'renameQueue', 'deleteQueue', 'purgeQueue']:
            menu.addAction(self._actions[name])
        return menu

    @pyqtSlot()
    def _commitQueue(self):
        assert self._repoagent
        repo = self._repoagent.rawRepo()
        if os.path.isdir(repo.mq.join('.hg')):
            self._launchCommitDialog()
            return
        if not self._cmdsession.isFinished():
            return

        cmdline = hglib.buildcmdargs('init', mq=True)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onQueueRepoInitialized)
        self._updateActions()

    @pyqtSlot(int)
    def _onQueueRepoInitialized(self, ret):
        if ret == 0:
            self._launchCommitDialog()
        self._onCommandFinished(ret)

    def _launchCommitDialog(self):
        if not self._repoagent:
            return
        repo = self._repoagent.rawRepo()
        repoagent = self._repoagent.subRepoAgent(hglib.tounicode(repo.mq.path))
        dlg = commit.CommitDialog(repoagent, [], {}, self.parent())
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def switchQueue(self, name):
        return self._runQqueue(None, name)

    @pyqtSlot()
    def _createQueue(self):
        name = self._getNewName(_('Create Patch Queue'),
                                _('New patch queue name'),
                                _('Create'))
        if name:
            self._runQqueue('create', name)

    @pyqtSlot()
    def _renameQueue(self):
        curname = self._activeName()
        newname = self._getNewName(_('Rename Patch Queue'),
                                   _("Rename patch queue '%s' to") % curname,
                                   _('Rename'))
        if newname and curname != newname:
            self._runQqueue('rename', newname)

    @pyqtSlot()
    def _deleteQueue(self):
        name = self._getExistingName(_('Delete Patch Queue'),
                                     _('Delete reference to'),
                                     _('Delete'))
        if name:
            self._runQqueueInactive('delete', name)

    @pyqtSlot()
    def _purgeQueue(self):
        name = self._getExistingName(_('Purge Patch Queue'),
                                     _('Remove patch directory of'),
                                     _('Purge'))
        if name:
            self._runQqueueInactive('purge', name)

    def _activeName(self):
        assert self._repoagent
        repo = self._repoagent.rawRepo()
        return hglib.tounicode(repo.thgactivemqname)

    def _existingNames(self):
        assert self._repoagent
        return hglib.getqqueues(self._repoagent.rawRepo())

    def _getNewName(self, title, labeltext, oktext):
        dlg = QInputDialog(self.parent())
        dlg.setWindowTitle(title)
        dlg.setLabelText(labeltext)
        dlg.setOkButtonText(oktext)
        if dlg.exec_():
            return dlg.textValue()

    def _getExistingName(self, title, labeltext, oktext):
        dlg = QInputDialog(self.parent())
        dlg.setWindowTitle(title)
        dlg.setLabelText(labeltext)
        dlg.setOkButtonText(oktext)
        dlg.setComboBoxEditable(False)
        dlg.setComboBoxItems(self._existingNames())
        dlg.setTextValue(self._activeName())
        if dlg.exec_():
            return dlg.textValue()

    def abort(self):
        self._cmdsession.abort()

    def _runQqueue(self, op, name):
        """Execute qqueue operation against the specified queue"""
        assert self._repoagent
        if not self._cmdsession.isFinished():
            return cmdcore.nullCmdSession()

        opts = {}
        if op:
            opts[op] = True
        cmdline = hglib.buildcmdargs('qqueue', name, **opts)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onCommandFinished)
        self._updateActions()
        return sess

    def _runQqueueInactive(self, op, name):
        """Execute qqueue operation after inactivating the specified queue"""
        assert self._repoagent
        if not self._cmdsession.isFinished():
            return cmdcore.nullCmdSession()

        if name != self._activeName():
            return self._runQqueue(op, name)

        sacrifices = [n for n in self._existingNames() if n != name]
        if not sacrifices:
            return self._runQqueue(op, name)  # will exit with error

        opts = {}
        if op:
            opts[op] = True
        cmdlines = [hglib.buildcmdargs('qqueue', sacrifices[0]),
                    hglib.buildcmdargs('qqueue', name, **opts)]
        self._cmdsession = sess = self._repoagent.runCommandSequence(cmdlines,
                                                                     self)
        sess.commandFinished.connect(self._onCommandFinished)
        self._updateActions()
        return sess

    @pyqtSlot(int)
    def _onCommandFinished(self, ret):
        if ret != 0:
            cmdui.errorMessageBox(self._cmdsession, self.parent())
        self._updateActions()


class PatchQueueActions(QObject):
    """Container for MQ patch actions except for queue management"""

    def __init__(self, parent=None):
        super(PatchQueueActions, self).__init__(parent)
        assert parent is None or isinstance(parent, QWidget)
        self._repoagent = None
        self._cmdsession = cmdcore.nullCmdSession()
        self._opts = {'force': False, 'keep_changes': False}

    def setRepoAgent(self, repoagent):
        self._repoagent = repoagent

    def gotoPatch(self, patch):
        opts = {'force': self._opts['force'],
                'keep_changes': self._opts['keep_changes']}
        return self._runCommand('qgoto', [patch], opts, self._onPushFinished)

    @pyqtSlot()
    def pushPatch(self, patch=None, move=False, exact=False):
        return self._runPush(patch, move=move, exact=exact)

    @pyqtSlot()
    def pushAllPatches(self):
        return self._runPush(None, all=True)

    def _runPush(self, patch, **opts):
        opts['force'] = self._opts['force']
        if not opts.get('exact'):
            # --exact and --keep-changes cannot be used simultaneously
            # thus we ignore the "default" setting for --keep-changes
            # when --exact is explicitly set
            opts['keep_changes'] = self._opts['keep_changes']
        return self._runCommand('qpush', [patch], opts, self._onPushFinished)

    @pyqtSlot()
    def popPatch(self, patch=None):
        return self._runPop(patch)

    @pyqtSlot()
    def popAllPatches(self):
        return self._runPop(None, all=True)

    def _runPop(self, patch, **opts):
        opts['force'] = self._opts['force']
        opts['keep_changes'] = self._opts['keep_changes']
        return self._runCommand('qpop', [patch], opts)

    def finishRevision(self, rev):
        return self._runCommand('qfinish', ['qbase::%s' % rev], {})

    def deletePatches(self, patches):
        dlg = qdelete.QDeleteDialog(patches, self.parent())
        if not dlg.exec_():
            return cmdcore.nullCmdSession()
        return self._runCommand('qdelete', patches, dlg.options())

    def foldPatches(self, patches):
        lpatches = map(hglib.fromunicode, patches)
        dlg = qfold.QFoldDialog(self._repoagent, lpatches, self.parent())
        dlg.finished.connect(dlg.deleteLater)
        if not dlg.exec_():
            return cmdcore.nullCmdSession()
        return self._runCommand('qfold', dlg.patches(), dlg.options())

    def renamePatch(self, patch):
        newname = patch
        while True:
            newname = self._getNewName(_('Rename Patch'),
                                       _('Rename patch <b>%s</b> to:') % patch,
                                       newname, _('Rename'))
            if not newname or patch == newname:
                return cmdcore.nullCmdSession()
            repo = self._repoagent.rawRepo()
            newfilename = hglib.tounicode(
                repo.mq.join(hglib.fromunicode(newname)))
            ok = qrename.checkPatchname(newfilename, self.parent())
            if ok:
                break
        return self._runCommand('qrename', [patch, newname], {})

    def guardPatch(self, patch, guards):
        args = [patch]
        args.extend(guards)
        opts = {'none': not guards}
        return self._runCommand('qguard', args, opts)

    def selectGuards(self, guards):
        opts = {'none': not guards}
        return self._runCommand('qselect', guards, opts)

    def _getNewName(self, title, labeltext, curvalue, oktext):
        dlg = QInputDialog(self.parent())
        dlg.setWindowTitle(title)
        dlg.setLabelText(labeltext)
        dlg.setTextValue(curvalue)
        dlg.setOkButtonText(oktext)
        if dlg.exec_():
            return unicode(dlg.textValue())

    def abort(self):
        self._cmdsession.abort()

    def _runCommand(self, name, args, opts, finishslot=None):
        assert self._repoagent
        if not self._cmdsession.isFinished():
            return cmdcore.nullCmdSession()
        cmdline = hglib.buildcmdargs(name, *args, **opts)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(finishslot or self._onCommandFinished)
        return sess

    @pyqtSlot(int)
    def _onPushFinished(self, ret):
        if ret == 2 and self._repoagent:
            repo = self._repoagent.rawRepo()
            output = hglib.fromunicode(self._cmdsession.warningString())
            if _checkForRejects(repo, output, self.parent()):
                ret = 0  # no further error dialog
        if ret != 0:
            cmdui.errorMessageBox(self._cmdsession, self.parent())

    @pyqtSlot(int)
    def _onCommandFinished(self, ret):
        if ret != 0:
            cmdui.errorMessageBox(self._cmdsession, self.parent())

    @pyqtSlot()
    def launchOptionsDialog(self):
        dlg = OptionsDialog(self._opts, self.parent())
        dlg.finished.connect(dlg.deleteLater)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self._opts.update(dlg.outopts)


class PatchQueueModel(QAbstractListModel):
    """List of all patches in active queue"""

    def __init__(self, repoagent, parent=None):
        super(PatchQueueModel, self).__init__(parent)
        self._repoagent = repoagent
        self._repoagent.repositoryChanged.connect(self._updateCache)
        self._series = []
        self._seriesguards = []
        self._statusmap = {}  # patch: applied/guarded/unguarded
        self._buildCache()

    @pyqtSlot()
    def _updateCache(self):
        # optimize range of changed signals if necessary
        repo = self._repoagent.rawRepo()
        if self._series == repo.mq.series[::-1]:
            self._buildCache()
        else:
            self._updateCacheAndLayout()
        self.dataChanged.emit(self.index(0), self.index(self.rowCount() - 1))

    def _updateCacheAndLayout(self):
        self.layoutAboutToBeChanged.emit()
        oldindexes = [(oi, self._series[oi.row()])
                      for oi in self.persistentIndexList()]
        self._buildCache()
        for oi, patch in oldindexes:
            try:
                ni = self.index(self._series.index(patch), oi.column())
            except ValueError:
                ni = QModelIndex()
            self.changePersistentIndex(oi, ni)
        self.layoutChanged.emit()

    def _buildCache(self):
        repo = self._repoagent.rawRepo()
        self._series = repo.mq.series[::-1]
        self._seriesguards = [list(xs) for xs in reversed(repo.mq.seriesguards)]

        self._statusmap.clear()
        self._statusmap.update((p.name, 'applied') for p in repo.mq.applied)
        for i, patch in enumerate(repo.mq.series):
            if patch in self._statusmap:
                continue  # applied
            pushable, why = repo.mq.pushable(i)
            if not pushable:
                self._statusmap[patch] = 'guarded'
            elif why is not None:
                self._statusmap[patch] = 'unguarded'

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self.patchName(index)
        if role == Qt.DecorationRole:
            return self._statusIcon(index)
        if role == Qt.FontRole:
            return self._statusFont(index)
        if role == Qt.ToolTipRole:
            return self._toolTip(index)

    def flags(self, index):
        flags = super(PatchQueueModel, self).flags(index)
        if not index.isValid():
            return flags | Qt.ItemIsDropEnabled  # insertion point
        patch = self._series[index.row()]
        if self._statusmap.get(patch) != 'applied':
            flags |= Qt.ItemIsDragEnabled
        return flags

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._series)

    def appliedCount(self):
        return sum(s == 'applied' for s in self._statusmap.itervalues())

    def patchName(self, index):
        if not index.isValid():
            return ''
        return hglib.tounicode(self._series[index.row()])

    def patchGuards(self, index):
        if not index.isValid():
            return []
        return map(hglib.tounicode, self._seriesguards[index.row()])

    def isApplied(self, index):
        if not index.isValid():
            return False
        patch = self._series[index.row()]
        return self._statusmap.get(patch) == 'applied'

    def _statusIcon(self, index):
        assert index.isValid()
        patch = self._series[index.row()]
        status = self._statusmap.get(patch)
        if status:
            return qtlib.geticon('hg-patch-%s' % status)

    def _statusFont(self, index):
        assert index.isValid()
        patch = self._series[index.row()]
        status = self._statusmap.get(patch)
        if status not in ('applied', 'guarded'):
            return
        f = QFont()
        f.setBold(status == 'applied')
        f.setItalic(status == 'guarded')
        return f

    def _toolTip(self, index):
        assert index.isValid()
        repo = self._repoagent.rawRepo()
        patch = self._series[index.row()]
        try:
            ctx = repo.changectx(patch)
        except error.RepoLookupError:
            # cache not updated after qdelete or qfinish
            return
        guards = self.patchGuards(index)
        return '%s: %s\n%s' % (self.patchName(index),
                               guards and ', '.join(guards) or _('no guards'),
                               ctx.longsummary())

    def topAppliedIndex(self, column=0):
        """Index of the last applied, i.e. qtip, patch"""
        for row, patch in enumerate(self._series):
            if self._statusmap.get(patch) == 'applied':
                return self.index(row, column)
        return QModelIndex()

    def mimeTypes(self):
        return ['application/vnd.thg.mq.series', 'text/uri-list']

    def mimeData(self, indexes):
        repo = self._repoagent.rawRepo()
        # in the same order as series file
        patches = [self._series[i.row()]
                   for i in sorted(indexes, reverse=True)]
        data = QMimeData()
        data.setData('application/vnd.thg.mq.series',
                     QByteArray('\n'.join(patches) + '\n'))
        data.setUrls([QUrl.fromLocalFile(hglib.tounicode(repo.mq.join(p)))
                      for p in patches])
        return data

    def dropMimeData(self, data, action, row, column, parent):
        if (action != Qt.MoveAction
            or not data.hasFormat('application/vnd.thg.mq.series')
            or row < 0 or parent.isValid()):
            return False

        repo = self._repoagent.rawRepo()
        qtiprow = len(self._series) - repo.mq.seriesend(True)
        if row > qtiprow:
            return False
        if row < len(self._series):
            after = self._series[row]
        else:
            after = None  # next to working rev
        patches = str(data.data('application/vnd.thg.mq.series')).splitlines()
        cmdline = hglib.buildcmdargs('qreorder', after=after, *patches)
        cmdline = map(hglib.tounicode, cmdline)
        self._repoagent.runCommand(cmdline)
        return True

    def supportedDropActions(self):
        return Qt.MoveAction


class MQPatchesWidget(QDockWidget):
    patchSelected = pyqtSignal(str)

    def __init__(self, parent):
        QDockWidget.__init__(self, parent)
        self._repoagent = None

        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable  |
                         QDockWidget.DockWidgetFloatable)
        self.setWindowTitle(_('Patch Queue'))

        w = QWidget()
        mainlayout = QVBoxLayout()
        mainlayout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(mainlayout)
        self.setWidget(w)

        self._patchActions = PatchQueueActions(self)

        # top toolbar
        w = QWidget()
        tbarhbox = QHBoxLayout()
        tbarhbox.setContentsMargins(0, 0, 0, 0)
        w.setLayout(tbarhbox)
        mainlayout.addWidget(w)

        # TODO: move QAction instances to PatchQueueActions
        self._qpushAct = a = QAction(
            qtlib.geticon('hg-qpush'), _('Push', 'MQ QPush'), self)
        a.setToolTip(_('Apply one patch'))
        self._qpushAllAct = a = QAction(
            qtlib.geticon('hg-qpush-all'), _('Push all', 'MQ QPush'), self)
        a.setToolTip(_('Apply all patches'))
        self._qpopAct = a = QAction(
            qtlib.geticon('hg-qpop'), _('Pop'), self)
        a.setToolTip(_('Unapply one patch'))
        self._qpopAllAct = a = QAction(
            qtlib.geticon('hg-qpop-all'), _('Pop all'), self)
        a.setToolTip(_('Unapply all patches'))
        self._qgotoAct = QAction(
            qtlib.geticon('hg-qgoto'), _('Go &to Patch'), self)
        self._qfinishAct = a = QAction(
            qtlib.geticon('qfinish'), _('&Finish Patch'), self)
        a.setToolTip(_('Move applied patches into repository history'))
        self._qdeleteAct = a = QAction(
            qtlib.geticon('hg-qdelete'), _('&Delete Patches...'), self)
        a.setToolTip(_('Delete selected patches'))
        self._qrenameAct = QAction(_('Re&name Patch...'), self)
        self._setGuardsAct = a = QAction(
            qtlib.geticon('hg-qguard'), _('Set &Guards...'), self)
        a.setToolTip(_('Configure guards for selected patch'))
        tbar = QToolBar(_('Patch Queue Actions Toolbar'), self)
        tbar.setIconSize(qtlib.smallIconSize())
        tbarhbox.addWidget(tbar)
        tbar.addAction(self._qpushAct)
        tbar.addAction(self._qpushAllAct)
        tbar.addSeparator()
        tbar.addAction(self._qpopAct)
        tbar.addAction(self._qpopAllAct)
        tbar.addSeparator()
        tbar.addAction(self._qfinishAct)
        tbar.addAction(self._qdeleteAct)
        tbar.addSeparator()
        tbar.addAction(self._setGuardsAct)

        self._queueFrame = w = QFrame()
        mainlayout.addWidget(w)

        # Patch Queue Frame
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        self._queueFrame.setLayout(layout)

        qqueuehbox = QHBoxLayout()
        qqueuehbox.setSpacing(5)
        layout.addLayout(qqueuehbox)
        self._qqueueComboWidget = QComboBox(self)
        qqueuehbox.addWidget(self._qqueueComboWidget, 1)
        self._qqueueConfigBtn = QToolButton(self)
        self._qqueueConfigBtn.setText('...')
        self._qqueueConfigBtn.setPopupMode(QToolButton.InstantPopup)
        qqueuehbox.addWidget(self._qqueueConfigBtn)

        self._qqueueActions = QueueManagementActions(self)
        self._qqueueConfigBtn.setMenu(self._qqueueActions.createMenu(self))

        self._queueListWidget = QListView(self)
        self._queueListWidget.setDragDropMode(QAbstractItemView.InternalMove)
        self._queueListWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._queueListWidget.setIconSize(qtlib.smallIconSize() * 0.75)
        self._queueListWidget.setSelectionMode(
            QAbstractItemView.ExtendedSelection)
        self._queueListWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self._queueListWidget.customContextMenuRequested.connect(
            self._onMenuRequested)
        layout.addWidget(self._queueListWidget, 1)

        bbarhbox = QHBoxLayout()
        bbarhbox.setSpacing(5)
        layout.addLayout(bbarhbox)
        self._guardSelBtn = QPushButton()
        menu = QMenu(self)
        menu.triggered.connect(self._onGuardSelectionChange)
        self._guardSelBtn.setMenu(menu)
        bbarhbox.addWidget(self._guardSelBtn)

        self._qqueueComboWidget.activated[str].connect(self._onQQueueActivated)

        self._queueListWidget.activated.connect(self._onGotoPatch)

        self._qpushAct.triggered[()].connect(self._patchActions.pushPatch)
        self._qpushAllAct.triggered.connect(self._patchActions.pushAllPatches)
        self._qpopAct.triggered[()].connect(self._patchActions.popPatch)
        self._qpopAllAct.triggered.connect(self._patchActions.popAllPatches)
        self._qgotoAct.triggered.connect(self._onGotoPatch)
        self._qfinishAct.triggered.connect(self._onFinishRevision)
        self._qdeleteAct.triggered.connect(self._onDelete)
        self._qrenameAct.triggered.connect(self._onRenamePatch)
        self._setGuardsAct.triggered.connect(self._onGuardConfigure)

        self.setAcceptDrops(True)

        self.layout().setContentsMargins(2, 2, 2, 2)

        QTimer.singleShot(0, self.reload)

    @property
    def _repo(self):
        if self._repoagent:
            return self._repoagent.rawRepo()

    def setRepoAgent(self, repoagent):
        if self._repoagent:
            self._repoagent.repositoryChanged.disconnect(self.reload)
        self._repoagent = None
        if repoagent and 'mq' in repoagent.rawRepo().extensions():
            self._repoagent = repoagent
            self._repoagent.repositoryChanged.connect(self.reload)
        self._changePatchQueueModel()
        self._patchActions.setRepoAgent(repoagent)
        self._qqueueActions.setRepoAgent(repoagent)
        QTimer.singleShot(0, self.reload)

    def _changePatchQueueModel(self):
        oldmodel = self._queueListWidget.model()
        if self._repoagent:
            newmodel = PatchQueueModel(self._repoagent, self)
            self._queueListWidget.setModel(newmodel)
            newmodel.dataChanged.connect(self._updatePatchActions)
            selmodel = self._queueListWidget.selectionModel()
            selmodel.currentRowChanged.connect(self._onPatchSelected)
            selmodel.selectionChanged.connect(self._updatePatchActions)
            self._updatePatchActions()
        else:
            self._queueListWidget.setModel(None)
        if oldmodel:
            oldmodel.setParent(None)

    @pyqtSlot()
    def _showActiveQueue(self):
        combo = self._qqueueComboWidget
        q = hglib.tounicode(self._repo.thgactivemqname)
        index = combo.findText(q)
        combo.setCurrentIndex(index)

    @pyqtSlot(QPoint)
    def _onMenuRequested(self, pos):
        menu = QMenu(self)
        menu.addAction(self._qgotoAct)
        menu.addAction(self._qfinishAct)
        menu.addAction(self._qdeleteAct)
        menu.addAction(self._qrenameAct)
        menu.addAction(self._setGuardsAct)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(self._queueListWidget.viewport().mapToGlobal(pos))

    def _currentPatchName(self):
        model = self._queueListWidget.model()
        index = self._queueListWidget.currentIndex()
        return model.patchName(index)

    @pyqtSlot()
    def _onGuardConfigure(self):
        model = self._queueListWidget.model()
        index = self._queueListWidget.currentIndex()
        patch = model.patchName(index)
        uguards = ' '.join(model.patchGuards(index))
        new, ok = qtlib.getTextInput(self,
                      _('Configure guards'),
                      _('Input new guards for %s:') % patch,
                      text=uguards)
        if not ok or new == uguards:
            return
        self._patchActions.guardPatch(patch, unicode(new).split())

    @pyqtSlot()
    def _onDelete(self):
        model = self._queueListWidget.model()
        selmodel = self._queueListWidget.selectionModel()
        patches = map(model.patchName, selmodel.selectedRows())
        self._patchActions.deletePatches(patches)

    @pyqtSlot()
    def _onGotoPatch(self):
        patch = self._currentPatchName()
        self._patchActions.gotoPatch(patch)

    @pyqtSlot()
    def _onFinishRevision(self):
        patch = self._currentPatchName()
        self._patchActions.finishRevision(patch)

    @pyqtSlot()
    def _onRenamePatch(self):
        patch = self._currentPatchName()
        self._patchActions.renamePatch(patch)

    @pyqtSlot()
    def _onPatchSelected(self):
        patch = self._currentPatchName()
        if patch:
            self.patchSelected.emit(patch)

    @pyqtSlot()
    def _updatePatchActions(self):
        model = self._queueListWidget.model()
        selmodel = self._queueListWidget.selectionModel()

        appliedcnt = model.appliedCount()
        seriescnt = model.rowCount()
        self._qpushAllAct.setEnabled(seriescnt > appliedcnt)
        self._qpushAct.setEnabled(seriescnt > appliedcnt)
        self._qpopAct.setEnabled(appliedcnt > 0)
        self._qpopAllAct.setEnabled(appliedcnt > 0)

        indexes = selmodel.selectedRows()
        anyapplied = any(model.isApplied(i) for i in indexes)
        self._qgotoAct.setEnabled(len(indexes) == 1
                                  and indexes[0] != model.topAppliedIndex())
        self._qfinishAct.setEnabled(len(indexes) == 1 and anyapplied)
        self._qdeleteAct.setEnabled(len(indexes) > 0 and not anyapplied)
        self._setGuardsAct.setEnabled(len(indexes) == 1)
        self._qrenameAct.setEnabled(len(indexes) == 1)

    @pyqtSlot(str)
    def _onQQueueActivated(self, text):
        if text == hglib.tounicode(self._repo.thgactivemqname):
            return

        if qtlib.QuestionMsgBox(_('Confirm patch queue switch'),
                _("Do you really want to activate patch queue '%s' ?") % text,
                parent=self, defaultbutton=QMessageBox.No):
            sess = self._qqueueActions.switchQueue(text)
            sess.commandFinished.connect(self._showActiveQueue)
        else:
            self._showActiveQueue()

    @pyqtSlot()
    def reload(self):
        self.widget().setEnabled(bool(self._repoagent))
        if not self._repoagent:
            return

        self._loadQQueues()
        self._showActiveQueue()

        repo = self._repo

        self._allguards = set()
        for idx, patch in enumerate(repo.mq.series):
            patchguards = repo.mq.seriesguards[idx]
            if patchguards:
                for guard in patchguards:
                    self._allguards.add(guard[1:])

        for guard in repo.mq.active():
            self._allguards.add(guard)
        self._refreshSelectedGuards()

        self._qqueueComboWidget.setEnabled(self._qqueueComboWidget.count() > 1)

    def _loadQQueues(self):
        repo = self._repo
        combo = self._qqueueComboWidget
        combo.clear()
        combo.addItems(hglib.getqqueues(repo))

    def _refreshSelectedGuards(self):
        total = len(self._allguards)
        count = len(self._repo.mq.active())
        menu = self._guardSelBtn.menu()
        menu.clear()
        for guard in self._allguards:
            a = menu.addAction(hglib.tounicode(guard))
            a.setCheckable(True)
            a.setChecked(guard in self._repo.mq.active())
        self._guardSelBtn.setText(_('Guards: %d/%d') % (count, total))
        self._guardSelBtn.setEnabled(bool(total))

    @pyqtSlot(QAction)
    def _onGuardSelectionChange(self, action):
        guard = hglib.fromunicode(action.text())
        newguards = self._repo.mq.active()[:]
        if action.isChecked():
            newguards.append(guard)
        elif guard in newguards:
            newguards.remove(guard)
        self._patchActions.selectGuards(map(hglib.tounicode, newguards))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._patchActions.abort()
            self._qqueueActions.abort()
        else:
            return super(MQPatchesWidget, self).keyPressEvent(event)


class OptionsDialog(QDialog):
    'Utility dialog for configuring uncommon options'
    def __init__(self, opts, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('MQ options'))

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.forcecb = QCheckBox(
            _('Force push or pop (--force)'))
        layout.addWidget(self.forcecb)

        self.keepcb = QCheckBox(
            _('Tolerate non-conflicting local changes (--keep-changes)'))
        layout.addWidget(self.keepcb)

        self.forcecb.setChecked(opts.get('force', False))
        self.keepcb.setChecked(opts.get('keep_changes', False))

        for cb in [self.forcecb, self.keepcb]:
            cb.clicked.connect(self._resolveopts)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.bb = bb
        layout.addWidget(bb)

    @qtlib.senderSafeSlot()
    def _resolveopts(self):
        # cannot use both --force and --keep-changes
        exclmap = {self.forcecb: [self.keepcb],
                   self.keepcb: [self.forcecb],
                   }
        sendercb = self.sender()
        if sendercb.isChecked():
            for cb in exclmap[sendercb]:
                cb.setChecked(False)

    def accept(self):
        outopts = {}
        outopts['force'] = self.forcecb.isChecked()
        outopts['keep_changes'] = self.keepcb.isChecked()
        self.outopts = outopts
        QDialog.accept(self)
