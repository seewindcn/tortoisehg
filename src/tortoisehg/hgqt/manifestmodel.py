# manifestmodel.py - Model for TortoiseHg manifest view
#
# Copyright (C) 2009-2010 LOGILAB S.A. <http://www.logilab.fr/>
# Copyright (C) 2010 Yuya Nishihara <yuya@tcha.org>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.

import os, re

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error, subrepo
from mercurial import match as matchmod

from tortoisehg.util import hglib
from tortoisehg.hgqt import filedata, qtlib, status, visdiff

_subrepoType2IcoMap = {
    'hg': 'hg',
    'hgsubversion': 'thg-svn-subrepo',
    'git': 'thg-git-subrepo',
    'svn': 'thg-svn-subrepo',
    }

_subrepoStatus2IcoMap = {
    'A': 'thg-added-subrepo',
    'R': 'thg-removed-subrepo',
    }

class ManifestModel(QAbstractItemModel):
    """Status of files between two revisions or patch"""

    # emitted when all files of the revision has been loaded successfully
    revLoaded = pyqtSignal(object)

    StatusRole = Qt.UserRole + 1
    """Role for file change status"""

    # -1 and None are valid revision number
    FirstParent = -2
    SecondParent = -3

    def __init__(self, repoagent, parent=None, rev=None, namefilter=None,
                 statusfilter='MASC', flat=False):
        QAbstractItemModel.__init__(self, parent)

        self._fileiconprovider = QFileIconProvider()
        self._iconcache = {}  # (path, status, subkind): icon
        self._repoagent = repoagent

        self._namefilter = unicode(namefilter or '')
        assert all(c in 'MARSC' for c in statusfilter)
        self._statusfilter = statusfilter
        self._changedfilesonly = False
        self._nodeop = _nodeopmap[bool(flat)]

        self._rootentry = self._newRevNode(rev)
        self._populate = _populaterepo
        self._rootpopulated = False

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return

        if role == Qt.DecorationRole:
            return self.fileIcon(index)
        if role == self.StatusRole:
            return self.fileStatus(index)

        e = index.internalPointer()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return e.name

    def filePath(self, index):
        """Return path at the given index [unicode]"""
        if not index.isValid():
            return ''

        return index.internalPointer().path

    def fileData(self, index):
        """Returns the displayable file data at the given index"""
        repo = self._repoagent.rawRepo()
        if not index.isValid():
            return filedata.createNullData(repo)

        f = index.internalPointer()
        e = f.parent
        while e and e.ctx is None:
            e = e.parent
        assert e, 'root entry must have ctx'
        wfile = hglib.fromunicode(f.path[len(e.path):].lstrip('/'))
        rpath = hglib.fromunicode(e.path)
        if f.subkind:
            # TODO: use subrepo ctxs and status resolved by this model
            return filedata.createSubrepoData(e.ctx, e.pctx, wfile, f.status,
                                              rpath, f.subkind)
        if f.isdir:
            return filedata.createDirData(e.ctx, e.pctx, wfile, rpath)
        return filedata.createFileData(e.ctx, e.pctx, wfile, f.status, rpath)

    def subrepoType(self, index):
        """Return the subrepo type the specified index"""
        if not index.isValid():
            return
        e = index.internalPointer()
        return e.subkind

    def fileIcon(self, index):
        if not index.isValid():
            return QIcon()
        e = index.internalPointer()
        k = (e.path, e.status, e.subkind)
        try:
            return self._iconcache[k]
        except KeyError:
            self._iconcache[k] = ic = self._makeFileIcon(e)
            return ic

    def _makeFileIcon(self, e):
        if e.subkind in _subrepoType2IcoMap:
            ic = qtlib.geticon(_subrepoType2IcoMap[e.subkind])
            # use fine-tuned status overlay if any
            n = _subrepoStatus2IcoMap.get(e.status)
            if n:
                return qtlib.getoverlaidicon(ic, qtlib.geticon(n))
            ic = qtlib.getoverlaidicon(ic, qtlib.geticon('thg-subrepo'))
        elif e.isdir:
            ic = self._fileiconprovider.icon(QFileIconProvider.Folder)
        else:
            # do not use fileiconprovier.icon(fileinfo), which may return icon
            # with shell (i.e. status of working directory) overlay.
            # default file icon looks ugly with status overlay on Windows
            ic = qtlib.geticon('text-x-generic')

        if not e.status:
            return ic
        st = status.statusTypes[e.status]
        if st.icon:
            icOverlay = qtlib.geticon(st.icon)
            ic = qtlib.getoverlaidicon(ic, icOverlay)

        return ic

    def fileStatus(self, index):
        """Return the change status of the specified file"""
        if not index.isValid():
            return
        e = index.internalPointer()
        # TODO: 'S' should not be a status
        if e.subkind:
            return 'S'
        return e.status

    # TODO: this should be merged to fileStatus()
    def subrepoStatus(self, index):
        """Return the change status of the specified subrepo"""
        if not index.isValid():
            return
        e = index.internalPointer()
        if not e.subkind:
            return
        return e.status

    def isDir(self, index):
        if not index.isValid():
            return True  # root entry must be a directory
        e = index.internalPointer()
        return e.isdir

    def mimeData(self, indexes):
        files = [self.filePath(i) for i in indexes if i.isValid()]
        ctx = self._rootentry.ctx
        if ctx.rev() is not None:
            repo = self._repoagent.rawRepo()
            lfiles = map(hglib.fromunicode, files)
            lbase, _fns = visdiff.snapshot(repo, lfiles, ctx)
            base = hglib.tounicode(lbase)
        else:
            # working copy
            base = self._repoagent.rootPath()

        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(os.path.join(base, e)) for e in files])
        return m

    def mimeTypes(self):
        return ['text/uri-list']

    def flags(self, index):
        f = super(ManifestModel, self).flags(index)
        if not index.isValid():
            return f
        if not (self.isDir(index) or self.fileStatus(index) == 'R'
                or self._populate is _populatepatch):
            f |= Qt.ItemIsDragEnabled
        return f

    def index(self, row, column, parent=QModelIndex()):
        if row < 0 or self.rowCount(parent) <= row or column != 0:
            return QModelIndex()
        return self.createIndex(row, column, self._parententry(parent).at(row))

    def indexFromPath(self, path, column=0):
        """Return index for the specified path if found [unicode]

        If not found, returns invalid index.
        """
        if not path:
            return QModelIndex()

        try:
            e = self._nodeop.findpath(self._rootentry, unicode(path))
        except KeyError:
            return QModelIndex()

        return self.createIndex(e.parent.index(e.name), column, e)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        e = index.internalPointer()
        if e.path:
            return self.indexFromPath(e.parent.path, index.column())
        else:
            return QModelIndex()

    def _parententry(self, parent):
        if parent.isValid():
            return parent.internalPointer()
        else:
            return self._rootentry

    def rowCount(self, parent=QModelIndex()):
        return len(self._parententry(parent))

    def columnCount(self, parent=QModelIndex()):
        return 1

    def rev(self, parent=QModelIndex()):
        """Revision number of the current changectx"""
        e = self._parententry(parent)
        if e.ctx is None or not _isreporev(e.ctx.rev()):
            return -1
        return e.ctx.rev()

    def baseRev(self, parent=QModelIndex()):
        """Revision of the base changectx where status is calculated from"""
        e = self._parententry(parent)
        if e.pctx is None or not _isreporev(e.pctx.rev()):
            return -1
        return e.pctx.rev()

    def setRev(self, rev, prev=FirstParent):
        """Change to the specified repository revision; None for working-dir"""
        roote = self._rootentry
        newroote = self._newRevNode(rev, prev)
        if (_samectx(newroote.ctx, roote.ctx)
            and _samectx(newroote.pctx, roote.pctx)):
            return
        self._populate = _populaterepo
        self._repopulateNodes(newroote=newroote)
        if self._rootpopulated:
            self.revLoaded.emit(self.rev())

    def setRawContext(self, ctx):
        """Change to the specified changectx in place of repository revision"""
        if _samectx(self._rootentry.ctx, ctx):
            return
        if _isreporev(ctx.rev()):
            repo = self._repoagent.rawRepo()
            try:
                if ctx == repo[ctx.rev()]:
                    return self.setRev(ctx.rev())
            except error.RepoLookupError:
                pass
        newroote = _Entry()
        newroote.ctx = ctx
        self._populate = _populatepatch
        self._repopulateNodes(newroote=newroote)
        if self._rootpopulated:
            self.revLoaded.emit(self.rev())

    def nameFilter(self):
        """Return the current name filter"""
        return self._namefilter

    @pyqtSlot(str)
    def setNameFilter(self, pattern):
        """Filter file name by partial match of glob pattern"""
        pattern = unicode(pattern)
        if self._namefilter == pattern:
            return
        self._namefilter = pattern
        self._repopulateNodes()

    def statusFilter(self):
        """Return the current status filter"""
        return self._statusfilter

    # TODO: split or remove 'S' which causes several design flaws
    @pyqtSlot(str)
    def setStatusFilter(self, status):
        """Filter file tree by change status 'MARSC'"""
        status = str(status)
        assert all(c in 'MARSC' for c in status)
        if self._statusfilter == status:
            return  # for performance reason
        self._statusfilter = status
        self._repopulateNodes()

    def isChangedFilesOnly(self):
        """Whether or not to filter by ctx.files, i.e. to exclude files not
        changed in the current revision.

        If this filter is enabled, 'C' (clean) files are not listed.  For
        merge changeset, 'M' (modified) files in one side are also excluded.
        """
        return self._changedfilesonly

    def setChangedFilesOnly(self, changedonly):
        if self._changedfilesonly == bool(changedonly):
            return
        self._changedfilesonly = bool(changedonly)
        self._repopulateNodes()

    def isFlat(self):
        """Whether all entries are listed in the same level or per directory"""
        return self._nodeop is _listnodeop

    def setFlat(self, flat):
        if self.isFlat() == bool(flat):
            return
        # self._nodeop must be changed after layoutAboutToBeChanged; otherwise
        # client code may obtain invalid indexes in its slot
        self._repopulateNodes(newnodeop=_nodeopmap[bool(flat)])

    def canFetchMore(self, parent):
        if parent.isValid():
            return False
        return not self._rootpopulated

    def fetchMore(self, parent):
        if parent.isValid() or self._rootpopulated:
            return
        assert len(self._rootentry) == 0
        newroote = self._rootentry.copyskel()
        self._populateNodes(newroote)
        self.beginInsertRows(parent, 0, len(newroote) - 1)
        self._rootentry = newroote
        self._rootpopulated = True
        self.endInsertRows()
        self.revLoaded.emit(self.rev())

    def _repopulateNodes(self, newnodeop=None, newroote=None):
        """Recreate populated nodes if any"""
        if not self._rootpopulated:
            # no stale nodes
            if newnodeop:
                self._nodeop = newnodeop
            if newroote:
                self._rootentry = newroote
            return

        self.layoutAboutToBeChanged.emit()
        try:
            oldindexmap = [(i, self.filePath(i))
                           for i in self.persistentIndexList()]
            if newnodeop:
                self._nodeop = newnodeop
            if not newroote:
                newroote = self._rootentry.copyskel()
            self._populateNodes(newroote)
            self._rootentry = newroote
            for oi, path in oldindexmap:
                self.changePersistentIndex(oi, self.indexFromPath(path))
        finally:
            self.layoutChanged.emit()

    def _newRevNode(self, rev, prev=FirstParent):
        """Create empty root node for the specified revision"""
        if not _isreporev(rev):
            raise ValueError('unacceptable revision number: %r' % rev)
        if not _isreporev(prev):
            raise ValueError('unacceptable parent revision number: %r' % prev)
        repo = self._repoagent.rawRepo()
        roote = _Entry()
        roote.ctx = repo[rev]
        if prev == ManifestModel.FirstParent:
            roote.pctx = roote.ctx.p1()
        elif prev == ManifestModel.SecondParent:
            roote.pctx = roote.ctx.p2()
        else:
            roote.pctx = repo[prev]
        return roote

    def _populateNodes(self, roote):
        repo = self._repoagent.rawRepo()
        lpat = hglib.fromunicode(self._namefilter)
        match = _makematcher(repo, roote.ctx, lpat, self._changedfilesonly)
        self._populate(roote, repo, self._nodeop, self._statusfilter, match)
        roote.sort()


class _Entry(object):
    """Each file or directory"""

    __slots__ = ('_name', '_parent', 'status', 'ctx', 'pctx', 'subkind',
                 '_child', '_nameindex')

    def __init__(self, name='', parent=None):
        self._name = name
        self._parent = parent
        self.status = None
        self.ctx = None
        self.pctx = None
        self.subkind = None
        self._child = {}
        self._nameindex = []

    def copyskel(self):
        """Create unpopulated copy of this entry"""
        e = self.__class__()
        e.status = self.status
        e.ctx = self.ctx
        e.pctx = self.pctx
        e.subkind = self.subkind
        return e

    @property
    def parent(self):
        return self._parent

    @property
    def path(self):
        if self.parent is None or not self.parent.name:
            return self.name
        else:
            return self.parent.path + '/' + self.name

    @property
    def name(self):
        return self._name

    @property
    def isdir(self):
        return bool(self.subkind or self._child)

    def __len__(self):
        return len(self._child)

    def __nonzero__(self):
        # leaf node should not be False because of len(node) == 0
        return True

    def __getitem__(self, name):
        return self._child[name]

    def makechild(self, name):
        if name not in self._child:
            self._nameindex.append(name)
        self._child[name] = e = self.__class__(name, parent=self)
        return e

    def putchild(self, name, e):
        assert not e.name and not e.parent
        e._name = name
        e._parent = self
        if name not in self._child:
            self._nameindex.append(name)
        self._child[name] = e

    def __contains__(self, item):
        return item in self._child

    def at(self, index):
        return self._child[self._nameindex[index]]

    def index(self, name):
        return self._nameindex.index(name)

    def sort(self, reverse=False):
        """Sort the entries recursively; directories first"""
        for e in self._child.itervalues():
            e.sort(reverse=reverse)
        self._nameindex.sort(
            key=lambda s: (not self[s].isdir, os.path.normcase(s)),
            reverse=reverse)


def _isreporev(rev):
    # patchctx.rev() returns str, which isn't a valid repository revision
    return rev is None or isinstance(rev, int)

def _samectx(ctx1, ctx2):
    # no fast way to detect changes in uncommitted ctx, just assumes different
    if ctx1.rev() is None or not _isreporev(ctx1.rev()):
        return False
    # compare hash in case it was stripped and recreated (e.g. by qrefresh)
    return ctx1 == ctx2 and ctx1.node() == ctx2.node()

# TODO: visual feedback to denote query type and error as in repofilter
def _makematcher(repo, ctx, pat, changedonly):
    cwd = ''  # always relative to repo root
    patterns = []
    if pat and ':' not in pat and '*' not in pat:
        # mimic case-insensitive partial string match
        patterns.append('relre:(?i)' + re.escape(pat))
    elif pat:
        patterns.append(pat)

    include = []
    if changedonly:
        include.extend('path:%s' % p for p in ctx.files())
        if not include:
            # no match
            return matchmod.exact(repo.root, cwd, [])

    try:
        return matchmod.match(repo.root, cwd, patterns, include=include,
                              default='relglob', auditor=repo.auditor, ctx=ctx)
    except (error.Abort, error.ParseError):
        # no match
        return matchmod.exact(repo.root, cwd, [])


class _listnodeop(object):
    subreporecursive = False

    @staticmethod
    def findpath(e, path):
        return e[path]

    @staticmethod
    def makepath(e, path):
        return e.makechild(path)

    @staticmethod
    def putpath(e, path, c):
        e.putchild(path, c)

class _treenodeop(object):
    subreporecursive = True

    @staticmethod
    def findpath(e, path):
        for p in path.split('/'):
            e = e[p]
        return e

    @staticmethod
    def makepath(e, path):
        for p in path.split('/'):
            if p not in e:
                e.makechild(p)
            e = e[p]
        return e

    @staticmethod
    def putpath(e, path, c):
        rp = path.rfind('/')
        if rp >= 0:
            e = _treenodeop.makepath(e, path[:rp])
        e.putchild(path[rp + 1:], c)

_nodeopmap = {
    False: _treenodeop,
    True: _listnodeop,
    }


def _populaterepo(roote, repo, nodeop, statusfilter, match):
    if 'S' in statusfilter:
        _populatesubrepos(roote, repo, nodeop, statusfilter, match)

    ctx = roote.ctx
    pctx = roote.pctx
    repo.lfstatus = True
    try:
        stat = repo.status(pctx, ctx, match, clean='C' in statusfilter)
    finally:
        repo.lfstatus = False
    for st, files in zip('MAR!?IC', stat):
        if st not in statusfilter:
            continue
        for path in files:
            e = nodeop.makepath(roote, hglib.tounicode(path))
            e.status = st

def _comparesubstate(state1, state2):
    if state1 == state2:
        return 'C'
    elif state1 == subrepo.nullstate:
        return 'A'
    elif state2 == subrepo.nullstate:
        return 'R'
    else:
        return 'M'

def _populatesubrepos(roote, repo, nodeop, statusfilter, match):
    ctx = roote.ctx
    pctx = roote.pctx
    subpaths = set(pctx.substate)
    subpaths.update(ctx.substate)
    for path in subpaths:
        substate = ctx.substate.get(path, subrepo.nullstate)
        psubstate = pctx.substate.get(path, subrepo.nullstate)
        e = _Entry()
        e.status = _comparesubstate(psubstate, substate)
        if e.status == 'R':
            # denotes the original subrepo has been removed
            e.subkind = psubstate[2]
        else:
            e.subkind = substate[2]

        # do not call ctx.sub() unnecessarily, which may raise Abort or OSError
        # if git or svn executable not found
        if (nodeop.subreporecursive and e.subkind == 'hg' and e.status != 'R'
            and os.path.isdir(repo.wjoin(path))):
            smatch = matchmod.narrowmatcher(path, match)
            try:
                srepo = ctx.sub(path)._repo
                e.ctx = srepo[substate[1]]
                e.pctx = srepo[psubstate[1] or 'null']
                _populaterepo(e, srepo, nodeop, statusfilter, smatch)
            except (error.RepoError, EnvironmentError):
                pass

        # subrepo is filtered out only if the node and its children do not
        # match the specified condition at all
        if len(e) > 0 or (e.status in statusfilter and match(path)):
            nodeop.putpath(roote, hglib.tounicode(path), e)

def _populatepatch(roote, repo, nodeop, statusfilter, match):
    ctx = roote.ctx
    stat = ctx.changesToParent(0)
    for st, files in zip('MAR', stat):
        if st not in statusfilter:
            continue
        for path in files:
            if not match(path):
                continue
            e = nodeop.makepath(roote, hglib.tounicode(path))
            e.status = st


class ManifestCompleter(QCompleter):
    """QCompleter for ManifestModel"""

    def splitPath(self, path):
        """
        >>> c = ManifestCompleter()
        >>> c.splitPath(QString('foo/bar'))
        [u'foo', u'bar']

        trailing slash appends extra '', so that QCompleter can descend to
        next level:
        >>> c.splitPath(QString('foo/'))
        [u'foo', u'']
        """
        return unicode(path).split('/')

    def pathFromIndex(self, index):
        if not index.isValid():
            return ''
        m = self.model()
        if not m:
            return ''
        return m.filePath(index)
