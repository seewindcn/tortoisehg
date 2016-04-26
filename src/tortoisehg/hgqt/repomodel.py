# Copyright (c) 2009-2010 LOGILAB S.A. (Paris, FRANCE).
# http://www.logilab.fr/ -- mailto:contact@logilab.fr
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import binascii, os, re

from mercurial import util, error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, filedata, graph

from PyQt4.QtCore import *
from PyQt4.QtGui import *

mqpatchmimetype = 'application/thg-mqunappliedpatch'

# TODO: Remove these two when we adopt GTK author color scheme
COLORS = ["blue",
          "darkgreen",
          "green",
          "darkblue",
          "purple",
          "dodgerblue",
          Qt.darkYellow,
          "magenta",
          "darkmagenta",
          "darkcyan",
          ]
COLORS = [str(QColor(x).name()) for x in COLORS]

# pick names from "hg help templating" if any
GraphColumn = 0
RevColumn = 1
BranchColumn = 2
DescColumn = 3
AuthorColumn = 4
TagsColumn = 5
LatestTagColumn = 6
NodeColumn = 7
AgeColumn = 8
LocalDateColumn = 9
UtcDateColumn = 10
ChangesColumn = 11
ConvertedColumn = 12
PhaseColumn = 13
FileColumn = 14

COLUMNHEADERS = (
    ('Graph', _('Graph', 'column header')),
    ('Rev', _('Rev', 'column header')),
    ('Branch', _('Branch', 'column header')),
    ('Description', _('Description', 'column header')),
    ('Author', _('Author', 'column header')),
    ('Tags', _('Tags', 'column header')),
    ('Latest tags', _('Latest tags', 'column header')),
    ('Node', _('Node', 'column header')),
    ('Age', _('Age', 'column header')),
    ('LocalTime', _('Local Time', 'column header')),
    ('UTCTime', _('UTC Time', 'column header')),
    ('Changes', _('Changes', 'column header')),
    ('Converted', _('Converted From', 'column header')),
    ('Phase', _('Phase', 'column header')),
    ('Filename', _('Filename', 'column header')),
    )
ALLCOLUMNS = tuple(name for name, _text in COLUMNHEADERS)

UNAPPLIED_PATCH_COLOR = QColor('#999999')
HIDDENREV_COLOR = QColor('#666666')
TROUBLED_COLOR = QColor(172, 34, 34)

GraphNodeRole = Qt.UserRole + 0
LabelsRole = Qt.UserRole + 1  # [(text, style), ...]

def _hashcolor(data, modulo=None):
    """function to reliably map a string to a color index

    The algorithm used is very basic and can be improved if needed.
    """
    if modulo is None:
        modulo = len(COLORS)
    idx = sum([ord(c) for c in data])
    idx %= modulo
    return idx

def _parsebranchcolors(value):
    r"""Parse tortoisehg.branchcolors setting

    >>> _parsebranchcolors('foo:#123456  bar:#789abc ')
    [('foo', '#123456'), ('bar', '#789abc')]
    >>> _parsebranchcolors(r'foo\ bar:black foo\:bar:white')
    [('foo bar', 'black'), ('foo:bar', 'white')]

    >>> _parsebranchcolors(r'\u00c0:black')
    [('\xc0', 'black')]
    >>> _parsebranchcolors('\xc0:black')
    [('\xc0', 'black')]

    >>> _parsebranchcolors(None)
    []
    >>> _parsebranchcolors('ill:formed:value no-value')
    []
    >>> _parsebranchcolors(r'\ubad:unicode-repr')
    []
    """
    if not value:
        return []

    colors = []
    for e in re.split(r'(?:(?<=\\\\)|(?<!\\)) ', value):
        pair = re.split(r'(?:(?<=\\\\)|(?<!\\)):', e)
        if len(pair) != 2:
            continue # ignore ill-formed
        key, val = pair
        key = key.replace('\\:', ':').replace('\\ ', ' ')
        if r'\u' in key:
            # apply unicode_escape only if \u found, so that raw non-ascii
            # value isn't always mangled.
            try:
                key = hglib.fromunicode(key.decode('unicode_escape'))
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        colors.append((key, val))
    return colors


class HgRepoListModel(QAbstractTableModel):
    """
    Model used for displaying the revisions of a Hg *local* repository
    """
    showMessage = pyqtSignal(str)

    # emitted when listed revisions are updated because of repository or
    # filter option change; a view might have to change current index
    revsUpdated = pyqtSignal()

    _defaultcolumns = ('Graph', 'Rev', 'Branch', 'Description', 'Author',
                       'Age', 'Tags', 'Phase')

    _mqtags = ('qbase', 'qtip', 'qparent')

    def __init__(self, repoagent, parent=None):
        QAbstractTableModel.__init__(self, parent)
        self._cache = []
        self._timerhandle = None
        self._rowcount = 0
        self._repoagent = repoagent
        self._selectedrevs = frozenset([])
        self._revspec = ''
        self._filterbyrevset = True
        self.unicodestar = True
        self.unicodexinabox = True
        self._latesttags = {-1: (0, 0, 'null')}  # date, dist, tag
        self._fullauthorname = False
        self._filterbranch = ''  # unicode
        self._allparents = False
        self._showgraftsource = True

        # To be deleted
        self._user_colors = {}
        self._branch_colors = {}

        self._querysess = cmdcore.nullCmdSession()
        self._pendingrebuild = False

        repoagent.configChanged.connect(self._invalidate)
        repoagent.repositoryChanged.connect(self._reloadGraph)

        self._initBranchColors()
        self._reloadConfig()
        self.graph = self._createGraph()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def _initBranchColors(self):
        # Always assign the first color to the default branch
        self._branch_colors['default'] = COLORS[0]

        # Set the colors specified in the tortoisehg.brachcolors config key
        self._branch_colors.update(_parsebranchcolors(
            self.repo.ui.config('tortoisehg', 'branchcolors')))

    def setBranch(self, branch, allparents=False):
        branchchanged = (branch != self._filterbranch)
        parentchanged = (allparents != self._allparents)
        self._filterbranch = branch
        self._allparents = allparents
        if branchchanged or (branch and parentchanged):
            self._rebuildGraph()

    def setShowGraftSource(self, visible):
        if self._showgraftsource == visible:
            return
        self._showgraftsource = visible
        self._rebuildGraph()

    def _createGraph(self):
        opts = {
            'branch': hglib.fromunicode(self._filterbranch),
            'showgraftsource': self._showgraftsource,
            }
        if self._revspec and not self._selectedrevs and self._filterbyrevset:
            return graph.Graph(self.repo, [])  # no matches found
        if self._selectedrevs and self._filterbyrevset:
            opts['revset'] = self._selectedrevs
            opts['showfamilyline'] = \
                self.repo.ui.configbool('tortoisehg', 'showfamilyline', True)
            grapher = graph.revision_grapher(self.repo, opts)
            return graph.Graph(self.repo, grapher, include_mq=False)
        else:
            opts['allparents'] = self._allparents
            grapher = graph.revision_grapher(self.repo, opts)
            return graph.Graph(self.repo, grapher, include_mq=True)

    @pyqtSlot()
    def _reloadGraph(self):
        self._latesttags = {-1: self._latesttags[-1]}  # clear
        if self._revspec:
            self._runQuery()
        self._rebuildGraph()

    def _rebuildGraph(self):
        if not self._querysess.isFinished():
            self._pendingrebuild = True
            return
        # skip costly operation while initializing options
        if self._rowcount <= 0 and not self.graph.isfilled():
            assert not self._cache
            self.graph = self._createGraph()
            return

        self.layoutAboutToBeChanged.emit()
        try:
            oldindexmap = {}  # rev: [index, ...]
            for i in self.persistentIndexList():
                rev = self.graph[i.row()].rev
                if rev not in oldindexmap:
                    oldindexmap[rev] = []
                oldindexmap[rev].append(i)
            try:
                brev = min(rev for rev in oldindexmap if isinstance(rev, int))
            except ValueError:
                brev = None

            self._cache = []
            try:
                self.graph = self._createGraph()
                self._ensureBuilt(brev)
            except (error.RevlogError, error.RepoError):
                self._shrinkRowCount()  # avoid further exceptions at data()
                raise
            self._expandRowCount()  # old rows may be mapped to inserted rows
            for rev, ois in oldindexmap.iteritems():
                row = self.graph.index(rev)
                nis = [self.index(row, i.column(), i.parent()) for i in ois]
                self.changePersistentIndexList(ois, nis)
            self._shrinkRowCount()  # old rows should be mapped before removal
            self._pendingrebuild = False
        finally:
            self.layoutChanged.emit()
        self._emitAllDataChanged()
        self.revsUpdated.emit()

    def revset(self):
        return self._revspec

    def setRevset(self, revspec):
        revspec = unicode(revspec)
        if revspec == self._revspec:
            return
        self._revspec = revspec
        if not revspec:
            self._querysess.abort()
            self._applyRevsetResult([])
            return
        self._runQuery()

    def _runQuery(self):
        self.showMessage.emit(_('Searching...'))

        self._querysess.abort()
        cmdline = ['log', '-T', '{rev}\n', '-r', self._revspec]
        self._querysess = sess = self._repoagent.runCommand(cmdline)
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._onQueryFinished)

    @pyqtSlot(int)
    def _onQueryFinished(self, ret):
        sess = self._querysess
        if not sess.isFinished():
            # new query is already running
            return
        if ret == 0:
            revs = map(int, str(sess.readAll()).splitlines())
            if revs:
                self.showMessage.emit(_('%d matches found') % len(revs))
            else:
                self.showMessage.emit(_('No matches found'))
            self._applyRevsetResult(revs)
        elif not sess.isAborted():
            self.showMessage.emit(sess.errorString() or sess.warningString())
        if self._pendingrebuild:
            self._rebuildGraph()  # invalid revspec

    def _applyRevsetResult(self, revset):
        self._selectedrevs = frozenset(revset)
        if self._filterbyrevset or self._pendingrebuild:
            self._rebuildGraph()
        else:
            self._invalidate()
            self.revsUpdated.emit()  # some revisions may be disabled

    def setFilterByRevset(self, filtered):
        if self._filterbyrevset == filtered:
            return
        self._filterbyrevset = filtered
        if self._revspec:
            self._rebuildGraph()

    def _reloadConfig(self):
        _ui = self.repo.ui
        self._fill_step = int(_ui.config('tortoisehg', 'graphlimit', 500))
        self._authorcolor = _ui.configbool('tortoisehg', 'authorcolor')
        self._fullauthorname = _ui.configbool('tortoisehg', 'fullauthorname')

    @pyqtSlot()
    def _invalidate(self):
        self._reloadConfig()
        self._cache = []
        self._emitAllDataChanged()

    def _emitAllDataChanged(self):
        if self._rowcount <= 0:
            return
        # optimize range if necessary
        bottomright = self.index(self._rowcount - 1, self.columnCount() - 1)
        self.dataChanged.emit(self.index(0, 0), bottomright)

    def branch(self):
        return self._filterbranch

    def canFetchMore(self, parent):
        if parent.isValid():
            return False
        return not self.graph.isfilled()

    def fetchMore(self, parent):
        if parent.isValid() or self.graph.isfilled():
            return
        self.graph.build_nodes(self._fill_step)
        self._expandRowCount()

    def _ensureBuilt(self, rev):
        """
        Make sure rev data is available (graph element created).

        """
        if not isinstance(rev, int):
            rev = len(self.repo)  # working dir or unapplied patch
        self.graph.build_nodes(rev=rev)
        # caller should do _expandRowCount() or _shrinkRowCount() by itself

    def loadall(self):
        self._timerhandle = self.startTimer(1)

    def timerEvent(self, event):
        if event.timerId() == self._timerhandle:
            self.showMessage.emit(_('filling (%d)')%(len(self.graph)))
            self.graph.build_nodes()
            # we only fill the graph data structures without telling
            # views until the model is loaded, to keep maximal GUI
            # reactivity
            if self.graph.isfilled():
                self.killTimer(self._timerhandle)
                self._timerhandle = None
                self._expandRowCount()
                self.showMessage.emit('')

    def _expandRowCount(self):
        newlen = len(self.graph)
        if newlen > self._rowcount:
            self.beginInsertRows(QModelIndex(), self._rowcount, newlen - 1)
            self._rowcount = newlen
            self.endInsertRows()

    def _shrinkRowCount(self):
        newlen = len(self.graph)
        if newlen < self._rowcount:
            self.beginRemoveRows(QModelIndex(), newlen, self._rowcount - 1)
            self._rowcount = newlen
            self.endRemoveRows()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return self._rowcount

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(ALLCOLUMNS) - 1  # no FileColumn

    def maxWidthValueForColumn(self, column):
        if column == RevColumn:
            return '8' * len(str(len(self.repo))) + '+'
        if column == NodeColumn:
            return '8' * 12 + '+'
        if column in (LocalDateColumn, UtcDateColumn):
            return hglib.displaytime(util.makedate())
        if column in (TagsColumn, LatestTagColumn):
            try:
                return sorted(self.repo.tags().keys(), key=lambda x: len(x))[-1][:10]
            except IndexError:
                pass
        if column == BranchColumn:
            try:
                return sorted(self.repo.branchmap(), key=lambda x: len(x))[-1]
            except IndexError:
                pass
        if column == FileColumn:
            return self._filename
        if column == ChangesColumn:
            return 'Changes'
        # Fall through for DescColumn
        return None

    def rev(self, index):
        """Revision number of the specified row; None for working-dir"""
        if not index.isValid():
            return -1
        gnode = self.graph[index.row()]
        if gnode.rev is not None and not isinstance(gnode.rev, int):
            # avoid mixing integer and localstr
            return -1
        return gnode.rev

    def _user_color(self, user):
        'deprecated, please replace with hgtk color scheme'
        if user not in self._user_colors:
            idx = _hashcolor(user)
            self._user_colors[user] = COLORS[idx]
        return self._user_colors[user]

    def _namedbranch_color(self, branch):
        'deprecated, please replace with hgtk color scheme'
        if branch not in self._branch_colors:
            idx = _hashcolor(branch)
            self._branch_colors[branch] = COLORS[idx]
        return self._branch_colors[branch]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        gnode = self.graph[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == FileColumn:
                return hglib.tounicode(gnode.extra[0])
        if role == Qt.FontRole:
            if index.column() in (NodeColumn, ConvertedColumn):
                return QFont("Monospace")
            if index.column() == DescColumn and gnode.wdparent:
                font = QApplication.font('QAbstractItemView')
                font.setBold(True)
                return font
        if role == Qt.ForegroundRole:
            if (gnode.shape == graph.NODE_SHAPE_UNAPPLIEDPATCH
                and index.column() != DescColumn):
                return UNAPPLIED_PATCH_COLOR
        if role == GraphNodeRole:
            return gnode
        if (PYQT_VERSION < 0x40701 and role == Qt.DecorationRole
            and self._safedata(index, LabelsRole)):
            # hack to flag HasDecoration where extended attributes of
            # QStyleOptionViewItem are not accessible in initStyleOption()
            return QColor(Qt.transparent)
        # repo may be changed while reading in case of postpull=rebase for
        # example, and result in RevlogError. (issue #429)
        try:
            return self._safedata(index, role)
        except error.RevlogError, e:
            if 'THGDEBUG' in os.environ:
                raise
            if role == Qt.DisplayRole:
                return hglib.tounicode(str(e))
            else:
                return None

    def _safedata(self, index, role):
        row = index.row()
        graphlen = len(self.graph)
        cachelen = len(self._cache)
        if graphlen > cachelen:
            self._cache.extend({} for _i in xrange(graphlen - cachelen))
        data = self._cache[row]
        idx = (role, index.column())
        if idx not in data:
            try:
                result = self._rawdata(index, role)
            except error.RepoLookupError:
                # happens if repository pruned/stripped or bundle unapplied
                # but model is not reloaded yet because repository is busy
                return None
            except util.Abort:
                return None
            data[idx] = result
        return data[idx]

    def _rawdata(self, index, role):
        row = index.row()
        column = index.column()
        gnode = self.graph[row]
        ctx = self.repo.changectx(gnode.rev)

        if role == Qt.DisplayRole:
            textfunc = self._columnmap.get(column)
            if textfunc is None:
                return None
            text = textfunc(self, ctx)
            if not isinstance(text, (QString, unicode)):
                text = hglib.tounicode(text)
            return text
        elif role == Qt.ForegroundRole:
            color = None
            if gnode.troubles:
                color = TROUBLED_COLOR
            elif column == AuthorColumn and self._authorcolor:
                color = QColor(self._user_color(ctx.user()))
            elif column in (GraphColumn, BranchColumn):
                color = QColor(self._namedbranch_color(ctx.branch()))
            if index.column() != GraphColumn:
                if gnode.faded:
                    if color is None:
                        color = HIDDENREV_COLOR
                    else:
                        color = color.lighter()
            return color
        elif role == LabelsRole and column == DescColumn:
            return self._getrevlabels(ctx)
        elif role == LabelsRole and column == ChangesColumn:
            return self._getchanges(ctx)
        return None

    def flags(self, index):
        flags = super(HgRepoListModel, self).flags(index)
        if not index.isValid():
            return flags
        row = index.row()
        if row >= len(self.graph) and not self.repo.ui.debugflag:
            # TODO: should not happen; internal data went wrong (issue #754)
            return Qt.NoItemFlags
        gnode = self.graph[row]
        if not self.isActiveRev(gnode.rev):
            return Qt.NoItemFlags
        if gnode.shape == graph.NODE_SHAPE_UNAPPLIEDPATCH:
            flags |= Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        if gnode.rev is None:
            flags |= Qt.ItemIsDropEnabled
        return flags

    def isActiveRev(self, rev):
        """True if the specified rev is not excluded by revset"""
        return (not self._revspec
                or rev in self._selectedrevs
                # consider everything is active while first query is running
                or (self._revspec and not self._selectedrevs
                    and not self._querysess.isFinished()))

    def mimeTypes(self):
        return [mqpatchmimetype]

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeData(self, indexes):
        data = set()
        for index in indexes:
            row = str(index.row())
            if row not in data:
                data.add(row)
        qmd = QMimeData()
        bytearray = QByteArray(','.join(sorted(data, reverse=True)))
        qmd.setData(mqpatchmimetype, bytearray)
        return qmd

    def dropMimeData(self, data, action, row, column, parent):
        if mqpatchmimetype not in data.formats():
            return False
        dragrows = [int(r) for r in str(data.data(mqpatchmimetype)).split(',')]
        destrow = parent.row()
        if destrow < 0:
            return False
        unapplied = self.repo.thgmqunappliedpatches[::-1]
        applied = [p.name for p in self.repo.mq.applied[::-1]]
        if max(dragrows) >= len(unapplied):
            return False
        dragpatches = [unapplied[d] for d in dragrows]
        allpatches = unapplied + applied
        if destrow < len(allpatches):
            destpatch = allpatches[destrow]
        else:
            destpatch = None  # next to working rev

        cmdline = hglib.buildcmdargs('qreorder', after=destpatch, *dragpatches)
        cmdline = map(hglib.tounicode, cmdline)
        self._repoagent.runCommand(cmdline)
        return True

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNHEADERS[section][1]

    def defaultIndex(self):
        """Index that should be selected when the model is initially loaded
        or the row previously selected is gone"""
        repo = self.repo
        initialsel = repo.ui.config('tortoisehg', 'initialrevision', 'current')
        changeid = {'current': '.',
                    'tip': 'tip',
                    'workingdir': None,
                    }.get(initialsel, '.')
        rev = repo[changeid].rev()
        if self._selectedrevs and rev not in self._selectedrevs:
            rev = max(self._selectedrevs)
        index = self.indexFromRev(rev)
        if index.flags() & Qt.ItemIsEnabled:
            return index

        if self._filterbranch:
            # look for the first active revision as last ditch; should be
            # removed if filterbranch is merged with revset
            for row, gnode in enumerate(self.graph.nodes):
                if not isinstance(gnode.rev, int):
                    continue
                index = self.index(row, 0)
                if index.flags() & Qt.ItemIsEnabled:
                    return index
        return QModelIndex()

    def indexFromRev(self, rev):
        self._ensureBuilt(rev)
        self._expandRowCount()
        row = self.graph.index(rev)
        if row >= 0:
            return self.index(row, 0)
        return QModelIndex()

    def _getbranch(self, ctx):
        b = hglib.tounicode(ctx.branch())
        if ctx.extra().get('close'):
            if self.unicodexinabox:
                b += u' \u2327'
            else:
                b += u'--'
        return b

    def _getlatesttags(self, ctx):
        rev = ctx.rev()
        todo = [rev]
        repo = self.repo
        while todo:
            rev = todo.pop()
            if rev in self._latesttags:
                continue
            ctx = repo[rev]
            tags = [t for t in ctx.tags()
                    if repo.tagtype(t) and repo.tagtype(t) != 'local']
            if tags:
                self._latesttags[rev] = ctx.date()[0], 0, ':'.join(sorted(tags))
                continue
            try:
                # The tuples are laid out so the right one can be found by
                # comparison.
                if (ctx.parents()):
                    pdate, pdist, ptag = max(
                        self._latesttags[p.rev()] for p in ctx.parents())
                else:
                    pdate, pdist, ptag = 0, -1, ""
            except KeyError:
                # Cache miss - recurse
                todo.append(rev)
                todo.extend(p.rev() for p in ctx.parents())
                continue
            self._latesttags[rev] = pdate, pdist + 1, ptag
        return self._latesttags[rev][2]

    def _gettags(self, ctx):
        if ctx.rev() is None:
            return ''
        tags = [t for t in ctx.tags() if t not in self._mqtags]
        return hglib.tounicode(','.join(tags))

    def _getrev(self, ctx):
        rev = ctx.rev()
        if type(rev) is int:
            return str(rev)
        elif rev is None:
            return u'%d+' % ctx.p1().rev()
        else:
            return ''

    def _getauthor(self, ctx):
        try:
            user = ctx.user()
            if not self._fullauthorname:
                user = hglib.username(user)
            return user
        except error.Abort:
            return _('Mercurial User')

    def _getlog(self, ctx):
        if ctx.rev() is None:
            if self.unicodestar:
                # The Unicode symbol is a black star:
                return u'\u2605 ' + _('Working Directory') + u' \u2605'
            else:
                return '*** ' + _('Working Directory') + ' ***'
        if self.repo.ui.configbool('tortoisehg', 'longsummary'):
            limit = 0x7fffffff  # unlimited (elide it by view)
        else:
            limit = None  # first line
        return hglib.longsummary(ctx.description(), limit)

    def _getrevlabels(self, ctx):
        labels = []
        branchheads = self.repo.branchheads(ctx.branch())
        if ctx.rev() is None:
            for pctx in ctx.parents():
                if branchheads and pctx.node() not in branchheads:
                    labels.append((_('Not a head revision!'), 'log.warning'))
            return labels

        if ctx.node() in branchheads:
            labels.append((hglib.tounicode(ctx.branch()), 'log.branch'))

        if ctx.thgmqunappliedpatch():
            style = 'log.unapplied_patch'
            labels.append((hglib.tounicode(ctx._patchname), style))

        for mark in ctx.bookmarks():
            style = 'log.bookmark'
            if mark == hglib.activebookmark(self.repo):
                bn = self.repo._bookmarks[hglib.activebookmark(self.repo)]
                if bn in self.repo.dirstate.parents():
                    style = 'log.curbookmark'
            labels.append((hglib.tounicode(mark), style))

        for tag in ctx.thgtags():
            if self.repo.thgmqtag(tag):
                style = 'log.patch'
            else:
                style = 'log.tag'
            labels.append((hglib.tounicode(tag), style))

        names = set(self.repo.ui.configlist('experimental', 'thg.displaynames'))
        for name, ns in self.repo.names.iteritems():
            if name not in names:
                continue
            # we will use the templatename as the color name since those
            # two should be the same
            for name in ns.names(self.repo, ctx.node()):
                labels.append((hglib.tounicode(name), 'log.%s' % ns.colorname))

        return labels

    def _getchanges(self, ctx):
        """Return the MAR status for the given ctx."""
        labels = []
        M, A, R = ctx.changesToParent(0)
        if A:
            labels.append((str(len(A)), 'log.added'))
        if M:
            labels.append((str(len(M)), 'log.modified'))
        if R:
            labels.append((str(len(R)), 'log.removed'))
        return labels

    def _getconv(self, ctx):
        if ctx.rev() is not None:
            extra = ctx.extra()
            cvt = extra.get('convert_revision', '')
            if cvt:
                if cvt.startswith('svn:'):
                    return cvt.split('@')[-1]
                if len(cvt) == 40:
                    try:
                        binascii.unhexlify(cvt)
                        return cvt[:12]
                    except TypeError:
                        pass
            cvt = extra.get('p4', '')
            if cvt:
                return cvt
        return ''

    def _getphase(self, ctx):
        if ctx.rev() is None:
            return ''
        try:
            return ctx.phasestr()
        except:
            return 'draft'

    _columnmap = {
        RevColumn: _getrev,
        BranchColumn: _getbranch,
        DescColumn: _getlog,
        AuthorColumn: _getauthor,
        TagsColumn: _gettags,
        LatestTagColumn: _getlatesttags,
        NodeColumn: lambda self, ctx: str(ctx),
        AgeColumn: lambda self, ctx: hglib.age(ctx.date()).decode('utf-8'),
        LocalDateColumn: lambda self, ctx: hglib.displaytime(ctx.date()),
        UtcDateColumn: lambda self, ctx: hglib.utctime(ctx.date()),
        ConvertedColumn: _getconv,
        PhaseColumn: _getphase,
        }


class FileRevModel(HgRepoListModel):
    """
    Model used to manage the list of revisions of a file, in file
    viewer of in diff-file viewer dialogs.
    """

    _defaultcolumns = ('Graph', 'Rev', 'Branch', 'Description', 'Author',
                       'Age', 'Filename')

    def __init__(self, repoagent, filename, parent=None):
        self._filename = filename
        HgRepoListModel.__init__(self, repoagent, parent)

    def _createGraph(self):
        grapher = graph.filelog_grapher(self.repo, self._filename)
        return graph.Graph(self.repo, grapher)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(ALLCOLUMNS)

    def indexLinkedFromRev(self, rev):
        """Index for the last changed revision before the specified revision

        This does not follow renames.
        """
        # as of Mercurial 2.6, workingfilectx.linkrev() does not work, and
        # this model has no virtual working-dir revision.
        if rev is None:
            rev = '.'
        try:
            fctx = self.repo[rev][self._filename]
        except error.LookupError:
            return QModelIndex()
        return self.indexFromRev(fctx.linkrev())

    def fileData(self, index, baseindex=QModelIndex()):
        """Displayable file data at the given index; baseindex specifies the
        revision where status is calculated from"""
        row = index.row()
        if not index.isValid() or row < 0 or row >= len(self.graph):
            return filedata.createNullData(self.repo)
        rev = self.graph[row].rev
        ctx = self.repo.changectx(rev)
        if baseindex.isValid():
            prev = self.graph[baseindex.row()].rev
            pctx = self.repo.changectx(prev)
        else:
            pctx = ctx.p1()
        filename = self.graph.filename(rev)
        if filename in pctx:
            status = 'M'
        else:
            status = 'A'
        return filedata.createFileData(ctx, pctx, filename, status)
