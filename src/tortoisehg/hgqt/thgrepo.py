# thgrepo.py - TortoiseHg additions to key Mercurial classes
#
# Copyright 2010 George Marrows <george.marrows@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.
#
# See mercurial/extensions.py, comments to wrapfunction, for this approach
# to extending repositories and change contexts.

import os
import sys
import shutil
import tempfile
import re
import time

from PyQt4.QtCore import *

from mercurial import hg, error, bundlerepo, extensions, filemerge, node
from mercurial import localrepo, subrepo
from mercurial import ui as uimod
from hgext import mq

from tortoisehg.util import hglib, paths
from tortoisehg.util.patchctx import patchctx
from tortoisehg.hgqt import cmdcore, qtlib

_repocache = {}
_kbfregex = re.compile(r'^\.kbf/')
_lfregex = re.compile(r'^\.hglf/')

# thgrepo.repository() will be deprecated
def repository(_ui=None, path=''):
    '''Returns a subclassed Mercurial repository to which new
    THG-specific methods have been added. The repository object
    is obtained using mercurial.hg.repository()'''
    if path not in _repocache:
        if _ui is None:
            _ui = uimod.ui()
        try:
            repo = hg.repository(_ui, path)
            repo = repo.unfiltered()
            repo.__class__ = _extendrepo(repo)
            repo = repo.filtered('visible')
            agent = RepoAgent(repo)
            _repocache[path] = agent.rawRepo()
            return agent.rawRepo()
        except EnvironmentError:
            raise error.RepoError('Cannot open repository at %s' % path)
    if not os.path.exists(os.path.join(path, '.hg/')):
        del _repocache[path]
        # this error must be in local encoding
        raise error.RepoError('%s is not a valid repository' % path)
    return _repocache[path]

def _filteredrepo(repo, hiddenincluded):
    if hiddenincluded:
        return repo.unfiltered()
    else:
        return repo.filtered('visible')


# flags describing changes that could occur in repository
LogChanged = 0x1
WorkingParentChanged = 0x2
WorkingBranchChanged = 0x4
WorkingStateChanged = 0x8  # internal flag to invalidate dirstate cache


class RepoWatcher(QObject):
    """Notify changes of repository by optionally monitoring filesystem"""

    configChanged = pyqtSignal()
    repositoryChanged = pyqtSignal(int)
    repositoryDestroyed = pyqtSignal()

    def __init__(self, repo, parent=None):
        super(RepoWatcher, self).__init__(parent)
        self._repo = repo
        self._ui = repo.ui
        self._fswatcher = None
        self._filesmap = {}  # path: (flag, watched)
        self._datamap = {}  # readmeth: (flag, dep-path)
        self._lastmtimes = {}  # path: mtime
        self._lastdata = {}  # readmeth: content
        self._fixState()
        self._uimtime = time.time()

    def startMonitoring(self):
        """Start filesystem monitoring to notify changes automatically"""
        if not self._fswatcher:
            self._fswatcher = QFileSystemWatcher(self)
            self._fswatcher.directoryChanged.connect(self._pollChanges)
            self._fswatcher.fileChanged.connect(self._pollChanges)
        self._fswatcher.addPath(hglib.tounicode(self._repo.path))
        self._fswatcher.addPath(hglib.tounicode(self._repo.spath))
        self._addMissingPaths()
        self._fswatcher.blockSignals(False)

    def stopMonitoring(self):
        """Stop filesystem monitoring by removing all watched paths"""
        if not self._fswatcher:
            return
        self._fswatcher.blockSignals(True)  # ignore pending events
        dirs = self._fswatcher.directories()
        if dirs:
            self._fswatcher.removePaths(dirs)
        files = self._fswatcher.files()
        if files:
            self._fswatcher.removePaths(files)

        # QTBUG-32917: On Windows, removePaths() fails to remove ".hg" and
        # ".hg/store" from the list, but actually they are not watched.
        # Thus, they cannot be watched again by the same fswatcher instance.
        if self._fswatcher.directories() or self._fswatcher.files():
            self._ui.debug('failed to remove paths - destroying watcher\n')
            self._fswatcher.setParent(None)
            self._fswatcher = None

    def isMonitoring(self):
        """True if filesystem monitor is running"""
        if not self._fswatcher:
            return False
        return not self._fswatcher.signalsBlocked()

    @pyqtSlot()
    def _pollChanges(self):
        '''Catch writes or deletions of files, or writes to .hg/ folder,
        most importantly lock files'''
        self.pollStatus()
        # filesystem monitor may be stopped inside pollStatus()
        if self.isMonitoring():
            self._addMissingPaths()

    def _addMissingPaths(self):
        'Add files to watcher that may have been added or replaced'
        existing = [f for f, (_flag, watched) in self._filesmap.iteritems()
                    if watched and f in self._lastmtimes]
        files = [unicode(f) for f in self._fswatcher.files()]
        for f in existing:
            if hglib.tounicode(f) not in files:
                self._ui.debug('add file to watcher: %s\n' % f)
                self._fswatcher.addPath(hglib.tounicode(f))
        for f in self._repo.uifiles():
            if f and os.path.exists(f) and hglib.tounicode(f) not in files:
                self._ui.debug('add ui file to watcher: %s\n' % f)
                self._fswatcher.addPath(hglib.tounicode(f))

    def clearStatus(self):
        self._lastmtimes.clear()
        self._lastdata.clear()

    def pollStatus(self):
        if not os.path.exists(self._repo.path):
            self._ui.debug('repository destroyed: %s\n' % self._repo.root)
            self.repositoryDestroyed.emit()
            return
        if self._locked():
            self._ui.debug('locked, aborting\n')
            return
        curmtimes, curdata = self._readState()
        changeflags = self._calculateChangeFlags(curmtimes, curdata)
        if self._locked():
            self._ui.debug('lock still held - ignoring for now\n')
            return
        self._lastmtimes = curmtimes
        self._lastdata = curdata
        if changeflags:
            self._ui.debug('change found (flags = 0x%x)\n' % changeflags)
            self.repositoryChanged.emit(changeflags)  # may update repo paths
            self._fixState()
        self._checkuimtime()

    def _locked(self):
        if os.path.lexists(self._repo.join('wlock')):
            return True
        if os.path.lexists(self._repo.sjoin('lock')):
            return True
        return False

    def _fixState(self):
        """Update paths to be checked and record state of new paths"""
        repo = self._repo
        q = getattr(repo, 'mq', None)
        newfilesmap = {
            repo.join('bookmarks'): (LogChanged, False),
            repo.join('bookmarks.current'): (LogChanged, False),
            repo.join('branch'): (0, False),
            repo.join('dirstate'): (WorkingStateChanged, False),
            repo.join('localtags'): (LogChanged, False),
            repo.sjoin('00changelog.i'): (LogChanged, False),
            repo.sjoin('obsstore'): (LogChanged, False),
            repo.sjoin('phaseroots'): (LogChanged, False),
            }
        if q:
            newfilesmap.update({
                q.join('guards'): (LogChanged, True),
                q.join('series'): (LogChanged, True),
                q.join('status'): (LogChanged, True),
                repo.join('patches.queue'): (LogChanged, True),
                repo.join('patches.queues'): (LogChanged, True),
                })
        newpaths = set(newfilesmap) - set(self._filesmap)
        if not newpaths:
            return
        self._filesmap = newfilesmap
        self._datamap = {
            RepoWatcher._readbranch: (WorkingBranchChanged,
                                      repo.join('branch')),
            RepoWatcher._readparents: (WorkingParentChanged,
                                       repo.join('dirstate')),
            }
        newmtimes, newdata = self._readState(newpaths)
        self._lastmtimes.update(newmtimes)
        self._lastdata.update(newdata)

    def _readState(self, targetpaths=None):
        if targetpaths is None:
            targetpaths = self._filesmap

        curmtimes = {}
        for path in targetpaths:
            try:
                curmtimes[path] = os.path.getmtime(path)
            except EnvironmentError:
                pass

        curdata = {}
        for readmeth, (_flag, path) in self._datamap.iteritems():
            if path not in targetpaths:
                continue
            last = self._lastmtimes.get(path, -1)
            cur = curmtimes.get(path, -1)
            if last != cur:  # mtime can go back on rollback
                try:
                    curdata[readmeth] = readmeth(self)
                except EnvironmentError:
                    pass
            elif cur >= 0 and readmeth in self._lastdata:
                curdata[readmeth] = self._lastdata[readmeth]

        return curmtimes, curdata

    def _calculateChangeFlags(self, curmtimes, curdata):
        changeflags = 0
        for path, (flag, _watched) in self._filesmap.iteritems():
            last = self._lastmtimes.get(path, -1)
            cur = curmtimes.get(path, -1)
            if last != cur:  # mtime can go back on rollback
                self._ui.debug(' mtime: %s (%r -> %r)\n' % (path, last, cur))
                changeflags |= flag
        for readmeth, (flag, _path) in self._datamap.iteritems():
            last = self._lastdata.get(readmeth)
            cur = curdata.get(readmeth)
            if last != cur:
                self._ui.debug(' data: %s (%r -> %r)\n'
                               % (readmeth.__name__, last, cur))
                changeflags |= flag
        return changeflags

    def _readparents(self):
        return self._repo.opener('dirstate').read(40)

    def _readbranch(self):
        return self._repo.opener('branch').read()

    def _checkuimtime(self):
        'Check for modified config files, or a new .hg/hgrc file'
        try:
            files = self._repo.uifiles()
            mtime = max(os.path.getmtime(f) for f in files if os.path.isfile(f))
            if mtime > self._uimtime:
                self._ui.debug('config change detected\n')
                self._uimtime = mtime
                self.configChanged.emit()
        except (EnvironmentError, ValueError):
            pass


class RepoAgent(QObject):
    """Proxy access to repository and keep its states up-to-date"""

    # change notifications are not emitted while command is running because
    # repository files are likely to be modified
    configChanged = pyqtSignal()
    repositoryChanged = pyqtSignal(int)
    repositoryDestroyed = pyqtSignal()

    serviceStopped = pyqtSignal()
    busyChanged = pyqtSignal(bool)

    commandFinished = pyqtSignal(cmdcore.CmdSession)
    outputReceived = pyqtSignal(str, str)
    progressReceived = pyqtSignal(cmdcore.ProgressMessage)

    def __init__(self, repo):
        QObject.__init__(self)
        self._repo = self._baserepo = repo
        # TODO: remove repo-to-agent references later; all widgets should own
        # RepoAgent instead of thgrepository.
        repo._pyqtobj = self
        # base repository for bundle or union (set in dispatch._dispatch)
        repo.ui.setconfig('bundle', 'mainreporoot', repo.root)
        # keep url separately from repo.url() because it is abbreviated to
        # relative path to cwd in bundle or union repo
        self._overlayurl = ''
        self._repochanging = 0

        self._watcher = watcher = RepoWatcher(repo, self)
        watcher.configChanged.connect(self._onConfigChanged)
        watcher.repositoryChanged.connect(self._onRepositoryChanged)
        watcher.repositoryDestroyed.connect(self._onRepositoryDestroyed)

        self._cmdagent = cmdagent = cmdcore.CmdAgent(repo.ui, self,
                                                     cwd=self.rootPath())
        cmdagent.outputReceived.connect(self.outputReceived)
        cmdagent.progressReceived.connect(self.progressReceived)
        cmdagent.serviceStopped.connect(self._tryEmitServiceStopped)
        cmdagent.busyChanged.connect(self._onBusyChanged)
        cmdagent.commandFinished.connect(self._onCommandFinished)

        self._subrepoagents = {}  # path: agent

    def startMonitoringIfEnabled(self):
        """Start filesystem monitoring on repository open by RepoManager or
        running command finished"""
        repo = self._repo
        ui = repo.ui
        monitorrepo = repo.ui.config('tortoisehg', 'monitorrepo', 'localonly')
        if monitorrepo == 'never':
            ui.debug('watching of F/S events is disabled by configuration\n')
        elif self._overlayurl:
            ui.debug('not watching F/S events for overlay repository\n')
        elif (monitorrepo == 'localonly'
              and not paths.is_on_fixed_drive(repo.path)):
            ui.debug('not watching F/S events for network drive\n')
        elif self.isBusy():
            ui.debug('not watching F/S events while busy\n')
        else:
            self._watcher.startMonitoring()

    def isServiceRunning(self):
        return self._watcher.isMonitoring() or self._cmdagent.isServiceRunning()

    def stopService(self):
        """Shut down back-end services on repository closed by RepoManager"""
        if self._watcher.isMonitoring():
            self._watcher.stopMonitoring()
            self._tryEmitServiceStopped()
        self._cmdagent.stopService()

    @pyqtSlot()
    def _tryEmitServiceStopped(self):
        if not self.isServiceRunning():
            self.serviceStopped.emit()

    def suspendMonitoring(self):
        """Stop filesystem monitoring temporarily; may be resumed when command
        finished or overlay repository changed"""
        # no "suspended" status until we really need it
        self._watcher.stopMonitoring()

    def resumeMonitoring(self):
        """Resume filesystem monitoring if possible"""
        if self._watcher.isMonitoring():
            return
        self.pollStatus()
        self.startMonitoringIfEnabled()

    def rawRepo(self):
        return self._repo

    def rootPath(self):
        return hglib.tounicode(self._repo.root)

    def displayName(self):
        """Name for window titles and similar"""
        if self._repo.ui.configbool('tortoisehg', 'fullpath'):
            return self.rootPath()
        else:
            return self.shortName()

    def shortName(self):
        """Name for tables, tabs, and sentences"""
        webname = hglib.shortreponame(self._repo.ui)
        if webname:
            return hglib.tounicode(webname)
        else:
            return os.path.basename(self.rootPath())

    def hiddenRevsIncluded(self):
        return self._repo.filtername != 'visible'

    def setHiddenRevsIncluded(self, included):
        """Switch visibility of hidden (i.e. pruned) changesets"""
        if self.hiddenRevsIncluded() == included:
            return
        self._changeRepo(_filteredrepo(self._repo, included))
        self._flushRepositoryChanged()

    def overlayUrl(self):
        return self._overlayurl

    def setOverlay(self, url):
        """Switch to bundle or union repository overlaying this"""
        url = unicode(url)
        if self._overlayurl == url:
            return
        repo = hg.repository(self._baserepo.ui, hglib.fromunicode(url))
        if repo.root != self._baserepo.root:
            raise ValueError('invalid overlay repository: %s' % url)
        repo = repo.unfiltered()
        repo.__class__ = _extendrepo(repo)
        repo._pyqtobj = self  # TODO: remove repo-to-agent references
        repo = repo.filtered('visible')
        self._changeRepo(_filteredrepo(repo, self.hiddenRevsIncluded()))
        self._overlayurl = url
        self.suspendMonitoring()
        self._flushRepositoryChanged()

    def clearOverlay(self):
        if not self._overlayurl:
            return
        repo = self._baserepo
        repo.thginvalidate()  # take changes during overlaid
        self._changeRepo(_filteredrepo(repo, self.hiddenRevsIncluded()))
        self._overlayurl = ''
        self.resumeMonitoring()

    def _changeRepo(self, repo):
        # bundle/union repo will append temporary revisions to changelog
        self._repochanging = LogChanged
        self._repo = repo

    def _emitRepositoryChanged(self, flags):
        flags |= self._repochanging
        self._repochanging = 0
        self.repositoryChanged.emit(flags)

    def _flushRepositoryChanged(self):
        if self._cmdagent.isBusy():
            return  # delayed until _onBusyChanged(False)
        if self._repochanging:
            self._emitRepositoryChanged(0)

    def clearStatus(self):
        """Forget last status so that next poll should emit change signals"""
        self._watcher.clearStatus()

    def pollStatus(self):
        """Force checking changes to emit corresponding signals"""
        if self._cmdagent.isBusy():
            return  # delayed until _onBusyChanged(False)
        self._watcher.pollStatus()
        self._flushRepositoryChanged()

    @pyqtSlot()
    def _onConfigChanged(self):
        self._repo.invalidateui()
        assert not self._cmdagent.isBusy()
        self._cmdagent.stopService()  # to reload config
        self.configChanged.emit()

    @pyqtSlot(int)
    def _onRepositoryChanged(self, flags):
        self._repo.thginvalidate()
        # ignore signal that just contains internal flags
        if flags & ~WorkingStateChanged:
            self._emitRepositoryChanged(flags)

    @pyqtSlot()
    def _onRepositoryDestroyed(self):
        if self._repo.root in _repocache:
            del _repocache[self._repo.root]
        # avoid further changed/destroyed signals
        self._watcher.stopMonitoring()
        self.repositoryDestroyed.emit()

    def isBusy(self):
        return self._cmdagent.isBusy()

    def _preinvalidateCache(self):
        if self._cmdagent.isBusy():
            # A lot of logic will depend on invalidation happening within
            # the context of this call. Signals will not be emitted till later,
            # but we at least invalidate cached data in the repository
            self._repo.thginvalidate()

    @pyqtSlot(bool)
    def _onBusyChanged(self, busy):
        if busy:
            self.suspendMonitoring()
        else:
            self.resumeMonitoring()
        self.busyChanged.emit(busy)

    def runCommand(self, cmdline, uihandler=None, overlay=True):
        """Executes a single command asynchronously in this repository"""
        cmdline = self._extendCmdline(cmdline, overlay)
        return self._cmdagent.runCommand(cmdline, uihandler)

    def runCommandSequence(self, cmdlines, uihandler=None, overlay=True):
        """Executes a series of commands asynchronously in this repository"""
        cmdlines = [self._extendCmdline(l, overlay) for l in cmdlines]
        return self._cmdagent.runCommandSequence(cmdlines, uihandler)

    def _extendCmdline(self, cmdline, overlay):
        if self.hiddenRevsIncluded():
            cmdline = ['--hidden'] + cmdline
        if overlay and self._overlayurl:
            cmdline = ['-R', self._overlayurl] + cmdline
        return cmdline

    def abortCommands(self):
        """Abort running and queued commands"""
        self._cmdagent.abortCommands()

    @pyqtSlot(cmdcore.CmdSession)
    def _onCommandFinished(self, sess):
        self._preinvalidateCache()
        self.commandFinished.emit(sess)

    def subRepoAgent(self, path):
        """Return RepoAgent of sub or patch repository"""
        root = self.rootPath()
        path = hglib.normreporoot(os.path.join(root, path))
        if path == root or not path.startswith(root.rstrip(os.sep) + os.sep):
            # only sub path is allowed to avoid circular references
            raise ValueError('invalid sub path: %s' % path)
        try:
            return self._subrepoagents[path]
        except KeyError:
            pass

        manager = self.parent()
        if not manager:
            raise RuntimeError('cannot open sub agent of unmanaged repo')
        assert isinstance(manager, RepoManager)
        self._subrepoagents[path] = agent = manager.openRepoAgent(path)
        return agent

    def releaseSubRepoAgents(self):
        """Release RepoAgents referenced by this when repository closed by
        RepoManager"""
        if not self._subrepoagents:
            return
        manager = self.parent()
        if not manager:
            raise RuntimeError('cannot release sub agents of unmanaged repo')
        assert isinstance(manager, RepoManager)
        for path in self._subrepoagents:
            manager.releaseRepoAgent(path)
        self._subrepoagents.clear()


class RepoManager(QObject):
    """Cache open RepoAgent instances and bundle their signals"""

    repositoryOpened = pyqtSignal(str)
    repositoryClosed = pyqtSignal(str)

    configChanged = pyqtSignal(str)
    repositoryChanged = pyqtSignal(str, int)
    repositoryDestroyed = pyqtSignal(str)

    busyChanged = pyqtSignal(str, bool)
    progressReceived = pyqtSignal(str, cmdcore.ProgressMessage)

    _SIGNALMAP = [
        # source, dest
        (SIGNAL('configChanged()'),
         SIGNAL('configChanged(QString)')),
        (SIGNAL('repositoryDestroyed()'),
         SIGNAL('repositoryDestroyed(QString)')),
        (SIGNAL('serviceStopped()'),
         SLOT('_tryCloseRepoAgent(QString)')),
        (SIGNAL('busyChanged(bool)'),
         SLOT('_mapBusyChanged(QString)')),
        ]

    def __init__(self, ui, parent=None):
        super(RepoManager, self).__init__(parent)
        self._ui = ui
        self._openagents = {}  # path: (agent, refcount)
        # refcount=0 means the repo is about to be closed

        self._sigmappers = []
        for _sig, slot in self._SIGNALMAP:
            mapper = QSignalMapper(self)
            self._sigmappers.append(mapper)
            QObject.connect(mapper, SIGNAL('mapped(QString)'), self, slot)

    def openRepoAgent(self, path):
        """Return RepoAgent for the specified path and increment refcount"""
        path = hglib.normreporoot(path)
        if path in self._openagents:
            agent, refcount = self._openagents[path]
            self._openagents[path] = (agent, refcount + 1)
            return agent

        # TODO: move repository creation from thgrepo.repository()
        self._ui.debug('opening repo: %s\n' % hglib.fromunicode(path))
        agent = repository(self._ui, hglib.fromunicode(path))._pyqtobj
        assert agent.parent() is None
        agent.setParent(self)
        for (sig, _slot), mapper in zip(self._SIGNALMAP, self._sigmappers):
            QObject.connect(agent, sig, mapper, SLOT('map()'))
            mapper.setMapping(agent, agent.rootPath())
        agent.repositoryChanged.connect(self._mapRepositoryChanged)
        agent.progressReceived.connect(self._mapProgressReceived)
        agent.startMonitoringIfEnabled()

        assert agent.rootPath() == path
        self._openagents[path] = (agent, 1)
        self.repositoryOpened.emit(path)
        return agent

    @pyqtSlot(str)
    def releaseRepoAgent(self, path):
        """Decrement refcount of RepoAgent and close it if possible"""
        path = hglib.normreporoot(path)
        agent, refcount = self._openagents[path]
        self._openagents[path] = (agent, refcount - 1)
        if refcount > 1:
            return

        # close child agents first, which may reenter to releaseRepoAgent()
        agent.releaseSubRepoAgents()

        if agent.isServiceRunning():
            self._ui.debug('stopping service: %s\n' % hglib.fromunicode(path))
            agent.stopService()
        else:
            self._tryCloseRepoAgent(path)

    @pyqtSlot(str)
    def _tryCloseRepoAgent(self, path):
        path = unicode(path)
        agent, refcount = self._openagents[path]
        if refcount > 0:
            # repo may be reopen before its services stopped
            return
        self._ui.debug('closing repo: %s\n' % hglib.fromunicode(path))
        del self._openagents[path]
        # TODO: disconnected automatically if _repocache does not exist
        for (sig, _slot), mapper in zip(self._SIGNALMAP, self._sigmappers):
            QObject.disconnect(agent, sig, mapper, SLOT('map()'))
            mapper.removeMappings(agent)
        agent.repositoryChanged.disconnect(self._mapRepositoryChanged)
        agent.progressReceived.disconnect(self._mapProgressReceived)
        agent.setParent(None)
        self.repositoryClosed.emit(path)

    def repoAgent(self, path):
        """Peek open RepoAgent for the specified path without refcount change;
        None for unknown path"""
        path = hglib.normreporoot(path)
        return self._openagents.get(path, (None, 0))[0]

    def repoRootPaths(self):
        """Return list of root paths of open repositories"""
        return self._openagents.keys()

    @qtlib.senderSafeSlot(int)
    def _mapRepositoryChanged(self, flags):
        agent = self.sender()
        assert isinstance(agent, RepoAgent)
        self.repositoryChanged.emit(agent.rootPath(), flags)

    @pyqtSlot(str)
    def _mapBusyChanged(self, path):
        agent, _refcount = self._openagents[unicode(path)]
        self.busyChanged.emit(path, agent.isBusy())

    @qtlib.senderSafeSlot(cmdcore.ProgressMessage)
    def _mapProgressReceived(self, progress):
        agent = self.sender()
        assert isinstance(agent, RepoAgent)
        self.progressReceived.emit(agent.rootPath(), progress)


_uiprops = '''_uifiles postpull tabwidth maxdiff
              deadbranches _exts _thghiddentags summarylen
              mergetools'''.split()
_thgrepoprops = '''_thgmqpatchnames thgmqunappliedpatches'''.split()

def _extendrepo(repo):
    class thgrepository(repo.__class__):

        def __getitem__(self, changeid):
            '''Extends Mercurial's standard __getitem__() method to
            a) return a thgchangectx with additional methods
            b) return a patchctx if changeid is the name of an MQ
            unapplied patch
            c) return a patchctx if changeid is an absolute patch path
            '''

            # Mercurial's standard changectx() (rather, lookup())
            # implies that tags and branch names live in the same namespace.
            # This code throws patch names in the same namespace, but as
            # applied patches have a tag that matches their patch name this
            # seems safe.
            if changeid in self.thgmqunappliedpatches:
                q = self.mq # must have mq to pass the previous if
                return genPatchContext(self, q.join(changeid), rev=changeid)
            elif type(changeid) is str and '\0' not in changeid and \
                    os.path.isabs(changeid) and os.path.isfile(changeid):
                return genPatchContext(repo, changeid)

            # If changeid is a basectx, repo[changeid] returns the same object.
            # We assumes changectx is already wrapped in that case; otherwise,
            # changectx would be double wrapped by thgchangectx.
            changectx = super(thgrepository, self).__getitem__(changeid)
            if changectx is changeid:
                return changectx
            changectx.__class__ = _extendchangectx(changectx)
            return changectx

        def hgchangectx(self, changeid):
            '''Returns unwrapped changectx or workingctx object'''
            # This provides temporary workaround for troubles caused by class
            # extension: e.g. changectx(n) != thgchangectx(n).
            # thgrepository and thgchangectx should be removed in some way.
            return super(thgrepository, self).__getitem__(changeid)

        @localrepo.unfilteredpropertycache
        def _thghiddentags(self):
            ht = self.ui.config('tortoisehg', 'hidetags', '')
            return [t.strip() for t in ht.split()]

        @localrepo.unfilteredpropertycache
        def thgmqunappliedpatches(self):
            '''Returns a list of (patch name, patch path) of all self's
            unapplied MQ patches, in patch series order, first unapplied
            patch first.'''
            if not hasattr(self, 'mq'): return []

            q = self.mq
            applied = set([p.name for p in q.applied])

            return [pname for pname in q.series if not pname in applied]

        @localrepo.unfilteredpropertycache
        def _thgmqpatchnames(self):
            '''Returns all tag names used by MQ patches. Returns []
            if MQ not in use.'''
            return hglib.getmqpatchtags(self)

        @property
        def thgactivemqname(self):
            '''Currenty-active qqueue name (see hgext/mq.py:qqueue)'''
            return hglib.getcurrentqqueue(self)

        @localrepo.unfilteredpropertycache
        def _uifiles(self):
            cfg = self.ui._ucfg
            files = set()
            for line in cfg._source.values():
                f = line.rsplit(':', 1)[0]
                files.add(f)
            files.add(self.join('hgrc'))
            return files

        @localrepo.unfilteredpropertycache
        def _exts(self):
            lclexts = []
            allexts = [n for n,m in extensions.extensions()]
            for name, path in self.ui.configitems('extensions'):
                if name.startswith('hgext.'):
                    name = name[6:]
                if name in allexts:
                    lclexts.append(name)
            return lclexts

        @localrepo.unfilteredpropertycache
        def postpull(self):
            pp = self.ui.config('tortoisehg', 'postpull')
            if pp in ('rebase', 'update', 'fetch', 'updateorrebase'):
                return pp
            return 'none'

        @localrepo.unfilteredpropertycache
        def tabwidth(self):
            tw = self.ui.config('tortoisehg', 'tabwidth')
            try:
                tw = int(tw)
                tw = min(tw, 16)
                return max(tw, 2)
            except (ValueError, TypeError):
                return 8

        @localrepo.unfilteredpropertycache
        def maxdiff(self):
            maxdiff = self.ui.config('tortoisehg', 'maxdiff')
            try:
                maxdiff = int(maxdiff)
                if maxdiff < 1:
                    return sys.maxint
            except (ValueError, TypeError):
                maxdiff = 1024 # 1MB by default
            return maxdiff * 1024

        @localrepo.unfilteredpropertycache
        def summarylen(self):
            slen = self.ui.config('tortoisehg', 'summarylen')
            try:
                slen = int(slen)
                if slen < 10:
                    return 80
            except (ValueError, TypeError):
                slen = 80
            return slen

        @localrepo.unfilteredpropertycache
        def deadbranches(self):
            db = self.ui.config('tortoisehg', 'deadbranch', '')
            return [b.strip() for b in db.split(',')]

        @localrepo.unfilteredpropertycache
        def mergetools(self):
            seen, installed = [], []
            for key, value in self.ui.configitems('merge-tools'):
                t = key.split('.')[0]
                if t not in seen:
                    seen.append(t)
                    if filemerge._findtool(self.ui, t):
                        installed.append(t)
            return installed

        def uifiles(self):
            'Returns complete list of config files'
            return self._uifiles

        def extensions(self):
            'Returns list of extensions enabled in this repository'
            return self._exts

        def thgmqtag(self, tag):
            'Returns true if `tag` marks an applied MQ patch'
            return tag in self._thgmqpatchnames

        def thgshelves(self):
            self.shelfdir = sdir = self.join('shelves')
            if os.path.isdir(sdir):
                def getModificationTime(x):
                    try:
                        return os.path.getmtime(os.path.join(sdir, x))
                    except EnvironmentError:
                        return 0
                shelves = sorted(os.listdir(sdir),
                    key=getModificationTime, reverse=True)
                return [s for s in shelves if \
                           os.path.isfile(os.path.join(self.shelfdir, s))]
            return []

        def makeshelf(self, patch):
            if not os.path.exists(self.shelfdir):
                os.mkdir(self.shelfdir)
            f = open(os.path.join(self.shelfdir, patch), "wb")
            f.close()

        def thginvalidate(self):
            'Should be called when mtime of repo store/dirstate are changed'
            self.dirstate.invalidate()
            if not isinstance(repo, bundlerepo.bundlerepository):
                self.invalidate()
            # mq.queue.invalidate does not handle queue changes, so force
            # the queue object to be rebuilt
            if localrepo.hasunfilteredcache(self, 'mq'):
                delattr(self.unfiltered(), 'mq')
            for a in _thgrepoprops + _uiprops:
                if localrepo.hasunfilteredcache(self, a):
                    delattr(self.unfiltered(), a)

        def invalidateui(self):
            'Should be called when mtime of ui files are changed'
            origui = self.ui
            self.ui = uimod.ui()
            self.ui.readconfig(self.join('hgrc'))
            hglib.copydynamicconfig(origui, self.ui)
            for a in _uiprops:
                if localrepo.hasunfilteredcache(self, a):
                    delattr(self.unfiltered(), a)

        def thgbackup(self, path):
            'Make a backup of the given file in the repository "trashcan"'
            # The backup name will be the same as the orginal file plus '.bak'
            trashcan = self.join('Trashcan')
            if not os.path.isdir(trashcan):
                os.mkdir(trashcan)
            if not os.path.exists(path):
                return
            name = os.path.basename(path)
            root, ext = os.path.splitext(name)
            dest = tempfile.mktemp(ext+'.bak', root+'_', trashcan)
            shutil.copyfile(path, dest)

        def isStandin(self, path):
            if 'largefiles' in self.extensions():
                if _lfregex.match(path):
                    return True
            if 'largefiles' in self.extensions() or 'kbfiles' in self.extensions():
                if _kbfregex.match(path):
                    return True
            return False

        def bfStandin(self, path):
            return '.kbf/' + path

        def lfStandin(self, path):
            return '.hglf/' + path

    return thgrepository

_changectxclscache = {}  # parentcls: extendedcls

def _extendchangectx(changectx):
    # cache extended changectx class, since we may create bunch of instances
    parentcls = changectx.__class__
    try:
        return _changectxclscache[parentcls]
    except KeyError:
        pass

    assert parentcls not in _changectxclscache.values(), 'double thgchangectx'
    _changectxclscache[parentcls] = cls = _createchangectxcls(parentcls)
    return cls

def _createchangectxcls(parentcls):
    class thgchangectx(parentcls):
        def sub(self, path):
            srepo = super(thgchangectx, self).sub(path)
            if isinstance(srepo, subrepo.hgsubrepo):
                r = srepo._repo
                r = r.unfiltered()
                r.__class__ = _extendrepo(r)
                srepo._repo = r.filtered('visible')
            return srepo

        def thgtags(self):
            '''Returns all unhidden tags for self'''
            htlist = self._repo._thghiddentags
            return [tag for tag in self.tags() if tag not in htlist]

        def _thgmqpatchtags(self):
            '''Returns the set of self's tags which are MQ patch names'''
            mytags = set(self.tags())
            patchtags = self._repo._thgmqpatchnames
            result = mytags.intersection(patchtags)
            assert len(result) <= 1, "thgmqpatchname: rev has more than one tag in series"
            return result

        def thgmqappliedpatch(self):
            '''True if self is an MQ applied patch'''
            return self.rev() is not None and bool(self._thgmqpatchtags())

        def thgmqunappliedpatch(self):
            return False

        def thgmqpatchname(self):
            '''Return self's MQ patch name. AssertionError if self not an MQ patch'''
            patchtags = self._thgmqpatchtags()
            assert len(patchtags) == 1, "thgmqpatchname: called on non-mq patch"
            return list(patchtags)[0]

        def thgmqoriginalparent(self):
            '''The revisionid of the original patch parent'''
            if not self.thgmqunappliedpatch() and not self.thgmqappliedpatch():
                return ''
            try:
                patchpath = self._repo.mq.join(self.thgmqpatchname())
                mqoriginalparent = mq.patchheader(patchpath).parent
            except EnvironmentError:
                return ''
            return mqoriginalparent

        def changesToParent(self, whichparent):
            parent = self.parents()[whichparent]
            return self._repo.status(parent.node(), self.node())[:3]

        def longsummary(self):
            if self._repo.ui.configbool('tortoisehg', 'longsummary'):
                limit = 80
            else:
                limit = None
            return hglib.longsummary(self.description(), limit)

        def hasStandin(self, file):
            if 'largefiles' in self._repo.extensions():
                if self._repo.lfStandin(file) in self.manifest():
                    return True
            elif 'largefiles' in self._repo.extensions() or 'kbfiles' in self._repo.extensions():
                if self._repo.bfStandin(file) in self.manifest():
                    return True
            return False

        def isStandin(self, path):
            return self._repo.isStandin(path)

        def findStandin(self, file):
            if 'largefiles' in self._repo.extensions():
                if self._repo.lfStandin(file) in self.manifest():
                    return self._repo.lfStandin(file)
            return self._repo.bfStandin(file)

    return thgchangectx

_pctxcache = {}
def genPatchContext(repo, patchpath, rev=None):
    global _pctxcache
    try:
        if os.path.exists(patchpath) and patchpath in _pctxcache:
            cachedctx = _pctxcache[patchpath]
            if cachedctx._mtime == os.path.getmtime(patchpath) and \
               cachedctx._fsize == os.path.getsize(patchpath):
                return cachedctx
    except EnvironmentError:
        pass
    # create a new context object
    ctx = patchctx(patchpath, repo, rev=rev)
    _pctxcache[patchpath] = ctx
    return ctx

def recursiveMergeStatus(repo):
    ms = hglib.readmergestate(repo)
    for wfile in ms:
        yield repo.root, wfile, ms[wfile]
    try:
        wctx = repo[None]
        for s in wctx.substate:
            sub = wctx.sub(s)
            if isinstance(sub, subrepo.hgsubrepo):
                for root, file, status in recursiveMergeStatus(sub._repo):
                    yield root, file, status
    except (EnvironmentError, error.Abort, error.RepoError):
        pass

def relatedRepositories(repoid):
    'Yields root paths for local related repositories'
    from tortoisehg.hgqt import reporegistry, repotreemodel
    if repoid == node.nullid:  # empty repositories shouldn't be related
        return

    f = QFile(reporegistry.settingsfilename())
    f.open(QIODevice.ReadOnly)
    try:
        for e in repotreemodel.iterRepoItemFromXml(f):
            if e.basenode() == repoid:
                # TODO: both in unicode because this is Qt-layer function?
                yield (hglib.fromunicode(e.rootpath()),
                       hglib.fromunicode(e.shortname()))
    except:
        f.close()
        raise
    else:
        f.close()

def isBfStandin(path):
    return _kbfregex.match(path)

def isLfStandin(path):
    return _lfregex.match(path)
