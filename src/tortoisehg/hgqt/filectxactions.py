# filectxactions.py - context menu actions for repository files
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2012 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, re

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.hgqt import cmdcore, cmdui, lfprompt, qtlib, revert, visdiff
from tortoisehg.hgqt import customtools, rejects
from tortoisehg.util.i18n import _
from tortoisehg.util import hglib, shlib

def _lcanonpaths(fds):
    return [hglib.fromunicode(e.canonicalFilePath()) for e in fds]

# predicates to filter files
def _anydeleted(fds):
    if any(e.rev() is None and e.rawContext().deleted() for e in fds):
        return fds
    return []
def _committed(fds):
    return [e for e in fds if e.rev() is not None and e.rev() >= 0]
def _filepath(pat):
    patre = re.compile(pat)
    return lambda fds: [e for e in fds if patre.search(e.filePath())]
def _filestatus(s):
    s = frozenset(s)
    # include directory since its status is unknown
    return lambda fds: [e for e in fds if e.isDir() or e.fileStatus() in s]
def _indirectbaserev(fds):
    return [e for e in fds if e.baseRev() not in e.parentRevs()]
def _isdir(fds):
    return [e for e in fds if e.isDir()]
def _isfile(fds):
    return [e for e in fds if not e.isDir()]
def _merged(fds):
    return [e for e in fds if len(e.rawContext().parents()) > 1]
def _mergestatus(s):
    s = frozenset(s)
    # include directory since its status is unknown
    return lambda fds: [e for e in fds if e.isDir() or e.mergeStatus() in s]
def _notpatch(fds):
    return [e for e in fds if e.rev() is None or e.rev() >= 0]
def _notsubrepo(fds):
    return [e for e in fds if not e.repoRootPath() and not e.subrepoType()]
def _notsubroot(fds):
    return [e for e in fds if not e.subrepoType()]
def _single(fds):
    if len(fds) != 1:
        return []
    return fds
def _subrepotype(t):
    return lambda fds: [e for e in fds if e.subrepoType() == t]

def _filterby(fdfilters, fds):
    for f in fdfilters:
        if not fds:
            return []
        fds = f(fds)
    return fds

def _tablebuilder(table):
    """Make decorator to define actions that receive filtered files

    If the slot, wrapped(), is invoked, the specified function is called
    with filtered files, func(fds), only if "fds" is not empty.
    """
    def slot(text, icon, shortcut, statustip, fdfilters=()):
        if not isinstance(fdfilters, tuple):
            fdfilters = (fdfilters,)
        def decorate(func):
            name = func.__name__
            table[name] = (text, icon, shortcut, statustip, fdfilters)
            def wrapped(self):
                fds = self.fileDataListForAction(name)
                if not fds:
                    return
                func(self, fds)
            return pyqtSlot(name=name)(wrapped)
        return decorate
    return slot


class FilectxActions(QObject):
    """Container for repository file actions"""

    linkActivated = pyqtSignal(str)
    filterRequested = pyqtSignal(str)
    """Ask the repowidget to change its revset filter"""
    runCustomCommandRequested = pyqtSignal(str, list)

    _actiontable = {}
    actionSlot = _tablebuilder(_actiontable)

    def __init__(self, repoagent, parent):
        super(FilectxActions, self).__init__(parent)
        if not isinstance(parent, QWidget):
            raise ValueError('parent must be a QWidget')

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self._selfds = []

        self._nav_dialogs = qtlib.DialogKeeper(FilectxActions._createnavdialog,
                                               FilectxActions._gennavdialogkey,
                                               self)

        self._actions = {}
        self._customactions = {}
        for name, d in self._actiontable.iteritems():
            desc, icon, key, tip, fdfilters = d
            # QAction must be owned by QWidget; otherwise statusTip for context
            # menu cannot be displayed (QTBUG-16114)
            act = QAction(desc, self.parent())
            if icon:
                act.setIcon(qtlib.geticon(icon))
            if key:
                act.setShortcut(key)
                act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            if tip:
                act.setStatusTip(tip)
            QObject.connect(act, SIGNAL('triggered()'),
                            self, SLOT('%s()' % name))
            self._addAction(name, act, fdfilters)

        self._initAdditionalActions()
        self._updateActions()

    def _initAdditionalActions(self):
        # override to add actions that cannot be declared as actionSlot
        pass

    @property
    def _ui(self):
        repo = self._repoagent.rawRepo()
        return repo.ui

    def _repoAgentFor(self, fd):
        rpath = fd.repoRootPath()
        if not rpath:
            return self._repoagent
        return self._repoagent.subRepoAgent(rpath)

    def _updateActions(self):
        idle = self._cmdsession.isFinished()
        selfds = self._selfds
        allactions = self._actions.values() + self._customactions.values()
        for act, fdfilters in allactions:
            act.setEnabled(idle and bool(_filterby(fdfilters, selfds)))

    def fileDataListForAction(self, name):
        fdfilters = self._actions[name][1]
        return _filterby(fdfilters, self._selfds)

    def setFileDataList(self, selfds):
        self._selfds = list(selfds)
        self._updateActions()

    def actions(self):
        """List of the actions; The owner widget should register them"""
        return [a for a, _f in self._actions.itervalues()]

    def action(self, name):
        return self._actions[name][0]

    def _addAction(self, name, action, fdfilters):
        assert name not in self._actions
        self._actions[name] = action, fdfilters

    def _runCommand(self, cmdline):
        if not self._cmdsession.isFinished():
            return cmdcore.nullCmdSession()
        sess = self._repoagent.runCommand(cmdline, self)
        self._handleNewCommand(sess)
        return sess

    def _runCommandSequence(self, cmdlines):
        if not self._cmdsession.isFinished():
            return cmdcore.nullCmdSession()
        sess = self._repoagent.runCommandSequence(cmdlines, self)
        self._handleNewCommand(sess)
        return sess

    def _handleNewCommand(self, sess):
        assert self._cmdsession.isFinished()
        self._cmdsession = sess
        sess.commandFinished.connect(self._onCommandFinished)
        self._updateActions()

    @pyqtSlot(int)
    def _onCommandFinished(self, ret):
        if ret == 255:
            cmdui.errorMessageBox(self._cmdsession, self.parent())
        self._updateActions()

    @actionSlot(_('File &History / Annotate'), 'hg-log', 'Shift+Return',
                _('Show the history of the selected file'),
                (_isfile, _notpatch, _filestatus('MARC!')))
    def navigateFileLog(self, fds):
        from tortoisehg.hgqt import filedialogs, fileview
        for fd in fds:
            dlg = self._navigate(filedialogs.FileLogDialog, fd)
            if not dlg:
                continue
            dlg.setFileViewMode(fileview.AnnMode)

    @actionSlot(_('Co&mpare File Revisions'), 'compare-files', None,
                _('Compare revisions of the selected file'),
                (_isfile, _notpatch))
    def navigateFileDiff(self, fds):
        from tortoisehg.hgqt import filedialogs
        for fd in fds:
            self._navigate(filedialogs.FileDiffDialog, fd)

    def _navigate(self, dlgclass, fd):
        repoagent = self._repoAgentFor(fd)
        repo = repoagent.rawRepo()
        filename = hglib.fromunicode(fd.canonicalFilePath())
        if repo.file(filename):
            dlg = self._nav_dialogs.open(dlgclass, repoagent, filename)
            dlg.goto(fd.rev())
            return dlg

    def _createnavdialog(self, dlgclass, repoagent, filename):
        return dlgclass(repoagent, filename)

    def _gennavdialogkey(self, dlgclass, repoagent, filename):
        repo = repoagent.rawRepo()
        return dlgclass, repo.wjoin(filename)

    @actionSlot(_('Filter Histor&y'), 'hg-log', None,
                _('Query about changesets affecting the selected files'),
                _notsubrepo)
    def filterFile(self, fds):
        pats = ["file('path:%s')" % e.filePath() for e in fds]
        self.filterRequested.emit(' or '.join(pats))

    @actionSlot(_('Diff &Changeset to Parent'), 'visualdiff', None, '',
                _notpatch)
    def visualDiff(self, fds):
        self._visualDiffToBase(fds, [])

    @actionSlot(_('Diff Changeset to Loc&al'), 'ldiff', None, '',
                _committed)
    def visualDiffToLocal(self, fds):
        self._visualDiff(fds, [], rev=['rev(%d)' % fds[0].rev()])

    @actionSlot(_('&Diff to Parent'), 'visualdiff', 'Ctrl+D',
                _('View file changes in external diff tool'),
                (_notpatch, _notsubroot, _filestatus('MAR!')))
    def visualDiffFile(self, fds):
        self._visualDiffToBase(fds, _lcanonpaths(fds))

    @actionSlot(_('Diff to &Local'), 'ldiff', 'Shift+Ctrl+D',
                _('View changes to current in external diff tool'),
                _committed)
    def visualDiffFileToLocal(self, fds):
        self._visualDiff(fds, _lcanonpaths(fds), rev=['rev(%d)' % fds[0].rev()])

    def _visualDiffToBase(self, fds, filenames):
        if fds[0].baseRev() == fds[0].parentRevs()[0]:
            self._visualDiff(fds, filenames, change=fds[0].rev())  # can 3-way
        else:
            revs = [fds[0].baseRev()]
            if fds[0].rev() is not None:
                revs.append(fds[0].rev())
            self._visualDiff(fds, filenames, rev=['rev(%d)' % r for r in revs])

    def _visualDiff(self, fds, filenames, **opts):
        repo = self._repoAgentFor(fds[0]).rawRepo()
        dlg = visdiff.visualdiff(repo.ui, repo, filenames, opts)
        if dlg:
            dlg.exec_()

    @actionSlot(_('&View at Revision'), 'view-at-revision', 'Shift+Ctrl+E',
                _('View file as it appeared at this revision'),
                _committed)
    def editFile(self, fds):
        self._editFileAt(fds, fds[0].rawContext())

    def _editFileAt(self, fds, ctx):
        repo = self._repoAgentFor(fds[0]).rawRepo()
        filenames = _lcanonpaths(fds)
        base, _ = visdiff.snapshot(repo, filenames, ctx)
        files = [os.path.join(base, filename)
                 for filename in filenames]
        qtlib.editfiles(repo, files, parent=self.parent())

    @actionSlot(_('&Save at Revision...'), None, 'Shift+Ctrl+S',
                _('Save file as it appeared at this revision'),
                _committed)
    def saveFile(self, fds):
        cmdlines = []
        for fd in fds:
            wfile, ext = os.path.splitext(fd.absoluteFilePath())
            extfilter = [_("All files (*)")]
            filename = "%s@%d%s" % (wfile, fd.rev(), ext)
            if ext:
                extfilter.insert(0, "*%s" % ext)

            result = QFileDialog.getSaveFileName(
                self.parent(), _("Save file to"), filename,
                ";;".join(extfilter))
            if not result:
                continue
            # checkout in working-copy line endings, etc. by --decode
            cmdlines.append(hglib.buildcmdargs(
                'cat', hglib.escapepath(fd.canonicalFilePath()), rev=fd.rev(),
                output=result, decode=True))

        if cmdlines:
            self._runCommandSequence(cmdlines)

    @actionSlot(_('&Edit Local'), 'edit-file', None,
                _('Edit current file in working copy'),
                (_isfile, _filestatus('MACI?')))
    def editLocalFile(self, fds):
        repo = self._repoAgentFor(fds[0]).rawRepo()
        filenames = _lcanonpaths(fds)
        qtlib.editfiles(repo, filenames, parent=self.parent())

    @actionSlot(_('&Open Local'), None, 'Shift+Ctrl+L',
                _('Edit current file in working copy'),
                (_isfile, _filestatus('MACI?')))
    def openLocalFile(self, fds):
        repo = self._repoAgentFor(fds[0]).rawRepo()
        filenames = _lcanonpaths(fds)
        qtlib.openfiles(repo, filenames)

    @actionSlot(_('E&xplore Local'), 'system-file-manager', None,
                _('Open parent folder of current file in the system file '
                  'manager'),
                (_isfile, _filestatus('MACI?')))
    def exploreLocalFile(self, fds):
        for fd in fds:
            qtlib.openlocalurl(os.path.dirname(fd.absoluteFilePath()))

    @actionSlot(_('&Copy Patch'), 'copy-patch', None, '',
                (_notpatch, _notsubroot, _filestatus('MAR!')))
    def copyPatch(self, fds):
        paths = [hglib.escapepath(fd.filePath()) for fd in fds]
        revs = map(hglib.escaperev, [fds[0].baseRev(), fds[0].rev()])
        cmdline = hglib.buildcmdargs('diff', *paths, r=revs)
        sess = self._runCommand(cmdline)
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._copyPatchOutputToClipboard)

    @pyqtSlot(int)
    def _copyPatchOutputToClipboard(self, ret):
        if ret != 0:
            return
        output = self._cmdsession.readAll()
        mdata = QMimeData()
        mdata.setData('text/x-diff', output)  # for lossless import
        mdata.setText(hglib.tounicode(str(output)))
        QApplication.clipboard().setMimeData(mdata)

    @actionSlot(_('Copy &Path'), None, 'Shift+Ctrl+C',
                _('Copy full path of file(s) to the clipboard'))
    def copyPath(self, fds):
        paths = [e.absoluteFilePath() for e in fds]
        QApplication.clipboard().setText(os.linesep.join(paths))

    @actionSlot(_('&Revert to Revision...'), 'hg-revert', 'Shift+Ctrl+R',
                _('Revert file(s) to contents at this revision'),
                _notpatch)
    def revertFile(self, fds):
        repoagent = self._repoAgentFor(fds[0])
        fileSelection = _lcanonpaths(fds)
        rev = fds[0].rev()
        if rev is None:
            repo = repoagent.rawRepo()
            rev = repo[rev].p1().rev()
        dlg = revert.RevertDialog(repoagent, fileSelection, rev,
                                  parent=self.parent())
        dlg.exec_()

    @actionSlot(_('Open S&ubrepository'), 'thg-repository-open', None,
                _('Open the selected subrepository'),
                _subrepotype('hg'))
    def openSubrepo(self, fds):
        for fd in fds:
            if fd.rev() is None:
                link = 'repo:%s' % fd.absoluteFilePath()
            else:
                ctx = fd.rawContext()
                spath = hglib.fromunicode(fd.canonicalFilePath())
                revid = ctx.substate[spath][1]
                link = 'repo:%s?%s' % (fd.absoluteFilePath(), revid)
            self.linkActivated.emit(link)

    @actionSlot(_('E&xplore Folder'), 'system-file-manager', None,
                _('Open the selected folder in the system file manager'),
                _isdir)
    def explore(self, fds):
        for fd in fds:
            qtlib.openlocalurl(fd.absoluteFilePath())

    @actionSlot(_('Open &Terminal'), 'utilities-terminal', None,
                _('Open a shell terminal in the selected folder'),
                _isdir)
    def terminal(self, fds):
        for fd in fds:
            root = hglib.fromunicode(fd.absoluteFilePath())
            currentfile = hglib.fromunicode(fd.filePath())
            qtlib.openshell(root, currentfile, self._ui)

    def setupCustomToolsMenu(self, location):
        tools, toollist = hglib.tortoisehgtools(self._ui, location)
        submenu = QMenu(_('Custom Tools'), self.parent())
        submenu.triggered.connect(self._runCustomCommandByMenu)
        for name in toollist:
            if name == '|':
                submenu.addSeparator()
                continue
            info = tools.get(name, None)
            if info is None:
                continue
            command = info.get('command', None)
            if not command:
                continue
            label = info.get('label', name)
            icon = info.get('icon', customtools.DEFAULTICONNAME)
            status = info.get('status')
            a = submenu.addAction(label)
            a.setData(name)
            if icon:
                a.setIcon(qtlib.geticon(icon))
            if status:
                fdfilters = (_filestatus(status),)
            else:
                fdfilters = ()
            self._customactions[name] = (a, fdfilters)
        submenu.menuAction().setVisible(bool(self._customactions))
        self._addAction('customToolsMenu', submenu.menuAction(), ())
        self._updateActions()

    @pyqtSlot(QAction)
    def _runCustomCommandByMenu(self, action):
        name = str(action.data().toString())
        fdfilters = self._customactions[name][1]
        fds = _filterby(fdfilters, self._selfds)
        files = [hglib.fromunicode(fd.filePath()) for fd in fds]
        self.runCustomCommandRequested.emit(name, files)


class WctxActions(FilectxActions):
    'container class for working context actions'

    refreshNeeded = pyqtSignal()

    _actiontable = FilectxActions._actiontable.copy()
    actionSlot = _tablebuilder(_actiontable)

    def _initAdditionalActions(self):
        repo = self._repoagent.rawRepo()
        # the same shortcut as editFile that is disabled for working rev
        a = self.action('editLocalFile')
        a.setShortcut('Ctrl+Shift+E')
        a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a = self.action('addLargefile')
        a.setVisible('largefiles' in repo.extensions())
        self._addAction('renameFileMenu', *self._createRenameFileMenu())
        self._addAction('remergeFileMenu', *self._createRemergeFileMenu())

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def _runWorkingFileCommand(self, cmdname, fds, opts=None):
        if not opts:
            opts = {}
        paths = [hglib.escapepath(fd.filePath()) for fd in fds]
        cmdline = hglib.buildcmdargs(cmdname, *paths, **opts)
        sess = self._runCommand(cmdline)
        sess.commandFinished.connect(self._notifyChangesOnCommandFinished)
        return sess

    @pyqtSlot(int)
    def _notifyChangesOnCommandFinished(self, ret):
        if ret == 0:
            self._notifyChanges()

    def _notifyChanges(self):
        # include all selected files for maximum possibility
        wfiles = [hglib.fromunicode(fd.absoluteFilePath())
                  for fd in self._selfds]
        shlib.shell_notify(wfiles)
        self.refreshNeeded.emit()

    # this action will no longer be necessary if status widget can toggle
    # base revision in amend/qrefresh mode
    @actionSlot(_('Diff &Local'), 'ldiff', 'Ctrl+Shift+D', '',
                (_indirectbaserev, _notsubroot, _filestatus('MARC!')))
    def visualDiffLocalFile(self, fds):
        self._visualDiff(fds, _lcanonpaths(fds))

    @actionSlot(_('&View Missing'), None, None, '',
                (_isfile, _filestatus('R!')))
    def editMissingFile(self, fds):
        wctx = fds[0].rawContext()
        self._editFileAt(fds, wctx.p1())

    @actionSlot(_('View O&ther'), None, None, '',
                (_isfile, _merged, _filestatus('MA')))
    def editOtherFile(self, fds):
        wctx = fds[0].rawContext()
        self._editFileAt(fds, wctx.p2())

    @actionSlot(_('&Add'), 'hg-add', None, '',
                (_notsubroot, _filestatus('RI?')))
    def addFile(self, fds):
        repo = self._repoAgentFor(fds[0]).rawRepo()
        if 'largefiles' in repo.extensions():
            self._addFileWithPrompt(fds)
        else:
            self._runWorkingFileCommand('add', fds)

    def _addFileWithPrompt(self, fds):
        repo = self._repoAgentFor(fds[0]).rawRepo()
        result = lfprompt.promptForLfiles(self.parent(), repo.ui, repo,
                                          _lcanonpaths(fds))
        if not result:
            return
        cmdlines = []
        for opt, paths in zip(('normal', 'large'), result):
            if not paths:
                continue
            paths = [hglib.escapepath(hglib.tounicode(e)) for e in paths]
            cmdlines.append(hglib.buildcmdargs('add', *paths, **{opt: True}))
        sess = self._runCommandSequence(cmdlines)
        sess.commandFinished.connect(self._notifyChangesOnCommandFinished)

    @actionSlot(_('Add &Largefiles...'), None, None, '',
                (_notsubroot, _filestatus('I?')))
    def addLargefile(self, fds):
        self._runWorkingFileCommand('add', fds, {'large': True})

    @actionSlot(_('&Forget'), 'hg-remove', None, '',
                (_notsubroot, _filestatus('MAC!')))
    def forgetFile(self, fds):
        self._runWorkingFileCommand('forget', fds)

    @actionSlot(_('&Delete Unversioned...'), 'hg-purge', 'Delete', '',
                (_notsubroot, _filestatus('?I')))
    def purgeFile(self, fds):
        parent = self.parent()
        files = [hglib.fromunicode(fd.filePath()) for fd in fds]
        res = qtlib.CustomPrompt(
            _('Confirm Delete Unversioned'),
            _('Delete the following unversioned files?'),
            parent, (_('&Delete'), _('Cancel')), 1, 1, files).run()
        if res == 1:
            return
        opts = {'config': 'extensions.purge=', 'all': True}
        self._runWorkingFileCommand('purge', fds, opts)

    @actionSlot(_('Re&move Versioned'), 'hg-remove', None, '',
                (_notsubroot, _filestatus('C')))
    def removeFile(self, fds):
        self._runWorkingFileCommand('remove', fds)

    @actionSlot(_('&Revert...'), 'hg-revert', None, '',
                _filestatus('MAR!'))
    def revertWorkingFile(self, fds):
        parent = self.parent()
        files = _lcanonpaths(fds)
        wctx = fds[0].rawContext()
        revertopts = {'date': None, 'rev': '.', 'all': False}
        if len(wctx.parents()) > 1:
            res = qtlib.CustomPrompt(
                _('Uncommited merge - please select a parent revision'),
                _('Revert files to local or other parent?'), parent,
                (_('&Local'), _('&Other'), _('Cancel')), 0, 2, files).run()
            if res == 0:
                revertopts['rev'] = wctx.p1().rev()
            elif res == 1:
                revertopts['rev'] = wctx.p2().rev()
            else:
                return
        elif [file for file in files if file in wctx.modified()]:
            res = qtlib.CustomPrompt(
                _('Confirm Revert'),
                _('Revert local file changes?'), parent,
                (_('&Revert with backup'), _('&Discard changes'),
                 _('Cancel')), 2, 2, files).run()
            if res == 2:
                return
            if res == 1:
                revertopts['no_backup'] = True
        else:
            res = qtlib.CustomPrompt(
                _('Confirm Revert'),
                _('Revert the following files?'),
                parent, (_('&Revert'), _('Cancel')), 1, 1, files).run()
            if res == 1:
                return
        self._runWorkingFileCommand('revert', fds, revertopts)

    @actionSlot(_('&Copy...'), 'edit-copy', None, '',
                (_single, _isfile, _filestatus('MC')))
    def copyFile(self, fds):
        self._openRenameDialog(fds, iscopy=True)

    @actionSlot(_('Re&name...'), 'hg-rename', None, '',
                (_single, _isfile, _filestatus('MC')))
    def renameFile(self, fds):
        self._openRenameDialog(fds, iscopy=False)

    def _openRenameDialog(self, fds, iscopy):
        from tortoisehg.hgqt.rename import RenameDialog
        srcfd, = fds
        repoagent = self._repoAgentFor(srcfd)
        dlg = RenameDialog(repoagent, self.parent(), srcfd.canonicalFilePath(),
                           iscopy=iscopy)
        if dlg.exec_() == 0:
            self._notifyChanges()

    @actionSlot(_('&Ignore...'), 'thg-ignore', None, '',
                (_notsubroot, _filestatus('?')))
    def editHgignore(self, fds):
        from tortoisehg.hgqt.hgignore import HgignoreDialog
        repoagent = self._repoAgentFor(fds[0])
        parent = self.parent()
        files = _lcanonpaths(fds)
        dlg = HgignoreDialog(repoagent, parent, *files)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        self._notifyChanges()

    @actionSlot(_('Edit Re&jects'), None, None,
                _('Manually resolve rejected patch chunks'),
                (_single, _isfile, _filestatus('?I'), _filepath(r'\.rej$')))
    def editRejects(self, fds):
        lpath = hglib.fromunicode(fds[0].absoluteFilePath()[:-4])  # drop .rej
        dlg = rejects.RejectsDialog(self._ui, lpath, self.parent())
        if dlg.exec_():
            self._notifyChanges()

    @actionSlot(_('De&tect Renames...'), 'thg-guess', None, '',
                (_isfile, _filestatus('A?!')))
    def guessRename(self, fds):
        from tortoisehg.hgqt.guess import DetectRenameDialog
        repoagent = self._repoAgentFor(fds[0])
        parent = self.parent()
        files = _lcanonpaths(fds)
        dlg = DetectRenameDialog(repoagent, parent, *files)
        def matched():
            ret[0] = True
        ret = [False]
        dlg.matchAccepted.connect(matched)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        if ret[0]:
            self._notifyChanges()

    @actionSlot(_('&Mark Resolved'), None, None, '',
                (_notsubroot, _mergestatus('U')))
    def markFileAsResolved(self, fds):
        self._runWorkingFileCommand('resolve', fds, {'mark': True})

    @actionSlot(_('&Mark Unresolved'), None, None, '',
                (_notsubroot, _mergestatus('R')))
    def markFileAsUnresolved(self, fds):
        self._runWorkingFileCommand('resolve', fds, {'unmark': True})

    @actionSlot(_('Restart Mer&ge'), None, None, '',
                (_notsubroot, _mergestatus('U')))
    def remergeFile(self, fds):
        self._runWorkingFileCommand('resolve', fds)

    def _createRenameFileMenu(self):
        menu = QMenu(_('Was renamed from'), self.parent())
        menu.aboutToShow.connect(self._updateRenameFileMenu)
        menu.triggered.connect(self._renameFrom)
        fdfilters = (_single, _isfile, _filestatus('?'), _anydeleted)
        return menu.menuAction(), fdfilters

    @qtlib.senderSafeSlot()
    def _updateRenameFileMenu(self):
        menu = self.sender()
        assert isinstance(menu, QMenu)
        menu.clear()
        fds = self.fileDataListForAction('renameFileMenu')
        if not fds:
            return
        wctx = fds[0].rawContext()
        for d in wctx.deleted()[:15]:
            menu.addAction(hglib.tounicode(d))

    @pyqtSlot(QAction)
    def _renameFrom(self, action):
        fds = self.fileDataListForAction('renameFileMenu')
        if not fds:
            # selection might be changed after menu is shown
            return
        deleted = hglib.escapepath(action.text())
        unknown = hglib.escapepath(fds[0].filePath())
        cmdlines = [hglib.buildcmdargs('copy', deleted, unknown, after=True),
                    hglib.buildcmdargs('forget', deleted)]  # !->R
        sess = self._runCommandSequence(cmdlines)
        sess.commandFinished.connect(self._notifyChangesOnCommandFinished)

    def _createRemergeFileMenu(self):
        menu = QMenu(_('Restart Merge &with'), self.parent())
        menu.aboutToShow.connect(self._populateRemergeFileMenu)  # may be slow
        menu.triggered.connect(self._remergeFileWith)
        return menu.menuAction(), (_notsubroot, _mergestatus('U'))

    @qtlib.senderSafeSlot()
    def _populateRemergeFileMenu(self):
        menu = self.sender()
        assert isinstance(menu, QMenu)
        menu.aboutToShow.disconnect(self._populateRemergeFileMenu)
        for tool in hglib.mergetools(self._ui):
            menu.addAction(hglib.tounicode(tool))

    @pyqtSlot(QAction)
    def _remergeFileWith(self, action):
        fds = self.fileDataListForAction('remergeFileMenu')
        self._runWorkingFileCommand('resolve', fds, {'tool': action.text()})
