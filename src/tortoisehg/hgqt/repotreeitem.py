# repotreeitem.py - treeitems for the reporegistry
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os, re

from mercurial import node
from mercurial import ui, hg, util, error

from tortoisehg.util import hglib, paths
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, hgrcutil

from PyQt4.QtCore import *
from PyQt4.QtGui import *

def _dumpChild(xw, parent):
    for c in parent.childs:
        c.dumpObject(xw)

def undumpObject(xr):
    xmltagname = str(xr.name().toString())
    obj = _xmlUndumpMap[xmltagname](xr)
    assert obj.xmltagname == xmltagname
    return obj

def _undumpChild(xr, parent, undump=undumpObject):
    while not xr.atEnd():
        xr.readNext()
        if xr.isStartElement():
            try:
                item = undump(xr)
                parent.appendChild(item)
            except KeyError:
                pass # ignore unknown classes in xml
        elif xr.isEndElement():
            break

def flatten(root, stopfunc=None):
    """Iterate root and its child items recursively until stop condition"""
    yield root
    if stopfunc and stopfunc(root):
        return
    for c in root.childs:
        for e in flatten(c, stopfunc):
            yield e

def find(root, targetfunc, stopfunc=None):
    """Search recursively for item of which targetfunc evaluates to True"""
    for e in flatten(root, stopfunc):
        if targetfunc(e):
            return e
    raise ValueError('not found')

# '/' for path separator, '#n' for index of duplicated names
_quotenamere = re.compile(r'[%/#]')

def _quotename(s):
    r"""Replace special characters to %xx (minimal set of urllib.quote)

    >>> _quotename('foo/bar%baz#qux')
    'foo%2Fbar%25baz%23qux'
    >>> _quotename(u'\xa1')
    u'\xa1'
    """
    return _quotenamere.sub(lambda m: '%%%02X' % ord(m.group(0)), s)

def _buildquotenamemap(items):
    namemap = {}
    for e in items:
        q = _quotename(e.shortname())
        if q not in namemap:
            namemap[q] = [e]
        else:
            namemap[q].append(e)
    return namemap

def itempath(item):
    """Virtual path to the given item"""
    rnames = []
    while item.parent():
        namemap = _buildquotenamemap(item.parent().childs)
        q = _quotename(item.shortname())
        i = namemap[q].index(item)
        if i == 0:
            rnames.append(q)
        else:
            rnames.append('%s#%d' % (q, i))
        item = item.parent()
    return '/'.join(reversed(rnames))

def findbyitempath(root, path):
    """Return the item for the given virtual path

    >>> root = RepoTreeItem()
    >>> foo = RepoGroupItem('foo')
    >>> root.appendChild(foo)
    >>> bar = RepoGroupItem('bar')
    >>> root.appendChild(bar)
    >>> bar.appendChild(RepoItem('/tmp/baz', 'baz'))
    >>> root.appendChild(RepoGroupItem('foo'))
    >>> root.appendChild(RepoGroupItem('qux/quux'))

    >>> def f(path):
    ...     return itempath(findbyitempath(root, path))

    >>> f('')
    ''
    >>> f('foo')
    'foo'
    >>> f('bar/baz')
    'bar/baz'
    >>> f('qux%2Fquux')
    'qux%2Fquux'
    >>> f('bar/baz/unknown')
    Traceback (most recent call last):
      ...
    ValueError: not found

    >>> f('foo#1')
    'foo#1'
    >>> f('foo#2')
    Traceback (most recent call last):
      ...
    ValueError: not found
    >>> f('foo#bar')
    Traceback (most recent call last):
      ...
    ValueError: invalid path
    """
    if not path:
        return root
    item = root
    for q in path.split('/'):
        h = q.rfind('#')
        if h >= 0:
            try:
                i = int(q[h + 1:])
            except ValueError:
                raise ValueError('invalid path')
            q = q[:h]
        else:
            i = 0
        namemap = _buildquotenamemap(item.childs)
        try:
            item = namemap[q][i]
        except LookupError:
            raise ValueError('not found')
    return item


class RepoTreeItem(object):
    xmltagname = 'treeitem'

    def __init__(self, parent=None):
        self._parent = parent
        self.childs = []
        self._row = 0

    def appendChild(self, child):
        child._row = len(self.childs)
        child._parent = self
        self.childs.append(child)

    def insertChild(self, row, child):
        child._row = row
        child._parent = self
        self.childs.insert(row, child)

    def child(self, row):
        return self.childs[row]

    def childCount(self):
        return len(self.childs)

    def columnCount(self):
        return 2

    def data(self, column, role):
        return QVariant()

    def setData(self, column, value):
        return False

    def row(self):
        return self._row

    def parent(self):
        return self._parent

    def menulist(self):
        return []

    def flags(self):
        return Qt.NoItemFlags

    def removeRows(self, row, count):
        cs = self.childs
        remove = cs[row : row + count]
        keep = cs[:row] + cs[row + count:]
        self.childs = keep
        for c in remove:
            c._row = 0
            c._parent = None
        for i, c in enumerate(keep):
            c._row = i
        return True

    def dump(self, xw):
        _dumpChild(xw, parent=self)

    @classmethod
    def undump(cls, xr):
        obj = cls()
        _undumpChild(xr, parent=obj)
        return obj

    def dumpObject(self, xw):
        xw.writeStartElement(self.xmltagname)
        self.dump(xw)
        xw.writeEndElement()

    def isRepo(self):
        return False

    def details(self):
        return ''

    def okToDelete(self):
        return True

    def getSupportedDragDropActions(self):
        return Qt.MoveAction


class RepoItem(RepoTreeItem):
    xmltagname = 'repo'

    def __init__(self, root, shortname=None, basenode=None, sharedpath=None,
                 parent=None):
        RepoTreeItem.__init__(self, parent)
        self._root = root
        self._shortname = shortname or u''
        self._basenode = basenode or node.nullid
        # expensive check is done at appendSubrepos()
        self._sharedpath = sharedpath or ''
        self._valid = True

    def isRepo(self):
        return True

    def rootpath(self):
        return self._root

    def shortname(self):
        if self._shortname:
            return self._shortname
        else:
            return os.path.basename(self._root)

    def repotype(self):
        return 'hg'

    def basenode(self):
        """Return node id of revision 0"""
        return self._basenode

    def setBaseNode(self, basenode):
        self._basenode = basenode

    def setShortName(self, uname):
        uname = unicode(uname)
        if uname != self._shortname:
            self._shortname = uname

    def data(self, column, role):
        if role == Qt.DecorationRole and column == 0:
            baseiconname = 'hg'
            if paths.is_unc_path(self.rootpath()):
                baseiconname = 'thg-remote-repo'
            ico = qtlib.geticon(baseiconname)
            if not self._valid:
                ico = qtlib.getoverlaidicon(ico, qtlib.geticon('dialog-warning'))
            elif self._sharedpath:
                ico = qtlib.getoverlaidicon(ico, qtlib.geticon('hg-sharedrepo'))
            return ico
        elif role in (Qt.DisplayRole, Qt.EditRole):
            return [self.shortname, self.shortpath][column]()

    def getCommonPath(self):
        return self.parent().getCommonPath()

    def shortpath(self):
        try:
            cpath = self.getCommonPath()
        except:
            cpath = ''
        spath2 = spath = os.path.normpath(self._root)

        if os.name == 'nt':
            spath2 = spath2.lower()

        if cpath and spath2.startswith(cpath):
            iShortPathStart = len(cpath)
            spath = spath[iShortPathStart:]
            if spath and spath[0] in '/\\':
                # do not show a slash at the beginning of the short path
                spath = spath[1:]

        return spath

    def menulist(self):
        acts = ['open', 'clone', 'addsubrepo', None, 'explore',
                'terminal', 'copypath', None, 'rename', 'remove']
        if self.childCount() > 0:
            acts.extend([None, (_('&Sort'), ['sortbyname', 'sortbyhgsub'])])
        acts.extend([None, 'settings'])
        return acts

    def flags(self):
        return (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
            | Qt.ItemIsEditable)

    def dump(self, xw):
        xw.writeAttribute('root', self._root)
        xw.writeAttribute('shortname', self.shortname())
        xw.writeAttribute('basenode', node.hex(self.basenode()))
        if self._sharedpath:
            xw.writeAttribute('sharedpath', self._sharedpath)
        _dumpChild(xw, parent=self)

    @classmethod
    def undump(cls, xr):
        a = xr.attributes()
        obj = cls(unicode(a.value('', 'root').toString()),
                  unicode(a.value('', 'shortname').toString()),
                  node.bin(str(a.value('', 'basenode').toString())),
                  unicode(a.value('', 'sharedpath').toString()))
        _undumpChild(xr, parent=obj, undump=_undumpSubrepoItem)
        return obj

    def details(self):
        return _('Local Repository %s') % self._root

    def appendSubrepos(self, repo=None):
        self._sharedpath = ''
        invalidRepoList = []
        try:
            sri = None
            if repo is None:
                if not os.path.exists(self._root):
                    self._valid = False
                    return [hglib.fromunicode(self._root)]
                elif (not os.path.exists(os.path.join(self._root, '.hgsub'))
                      and not os.path.exists(
                          os.path.join(self._root, '.hg', 'sharedpath'))):
                    return []  # skip repo creation, which is expensive
                repo = hg.repository(ui.ui(), hglib.fromunicode(self._root))
            if repo.sharedpath != repo.path:
                self._sharedpath = hglib.tounicode(repo.sharedpath)
            wctx = repo['.']
            sortkey = lambda x: os.path.basename(util.normpath(repo.wjoin(x)))
            for subpath in sorted(wctx.substate, key=sortkey):
                sri = None
                abssubpath = repo.wjoin(subpath)
                subtype = wctx.substate[subpath][2]
                sriIsValid = os.path.isdir(abssubpath)
                sri = _newSubrepoItem(hglib.tounicode(abssubpath),
                                      repotype=subtype)
                sri._valid = sriIsValid
                self.appendChild(sri)

                if not sriIsValid:
                    self._valid = False
                    sri._valid = False
                    invalidRepoList.append(repo.wjoin(subpath))
                    return invalidRepoList

                if subtype == 'hg':
                    # Only recurse into mercurial subrepos
                    sctx = wctx.sub(subpath)
                    invalidSubrepoList = sri.appendSubrepos(sctx._repo)
                    if invalidSubrepoList:
                        self._valid = False
                        invalidRepoList += invalidSubrepoList

        except (EnvironmentError, error.RepoError, util.Abort), e:
            # Add the repo to the list of repos/subrepos
            # that could not be open
            self._valid = False
            if sri:
                sri._valid = False
                invalidRepoList.append(abssubpath)
            invalidRepoList.append(hglib.fromunicode(self._root))
        except Exception, e:
            # If any other sort of exception happens, show the corresponding
            # error message, but do not crash!
            # Note that we _also_ will mark the offending repos as invalid
            # It is unfortunate that Python 2.4, which we target does not
            # support combined try/except/finally clauses, forcing us
            # to duplicate some code here
            self._valid = False
            if sri:
                sri._valid = False
                invalidRepoList.append(abssubpath)
            invalidRepoList.append(hglib.fromunicode(self._root))

            # Show a warning message indicating that there was an error
            if repo:
                rootpath = hglib.tounicode(repo.root)
            else:
                rootpath = self._root
            warningMessage = (_('An exception happened while loading the ' \
                'subrepos of:<br><br>"%s"<br><br>') + \
                _('The exception error message was:<br><br>%s<br><br>') +\
                _('Click OK to continue or Abort to exit.')) \
                % (rootpath, hglib.tounicode(e.message))
            res = qtlib.WarningMsgBox(_('Error loading subrepos'),
                                warningMessage,
                                buttons = QMessageBox.Ok | QMessageBox.Abort)
            # Let the user abort so that he gets the full exception info
            if res == QMessageBox.Abort:
                raise
        return invalidRepoList

    def setData(self, column, value):
        if column == 0:
            shortname = hglib.fromunicode(value.toString())
            abshgrcpath = os.path.join(hglib.fromunicode(self.rootpath()),
                                       '.hg', 'hgrc')
            if not hgrcutil.setConfigValue(abshgrcpath, 'web.name', shortname):
                qtlib.WarningMsgBox(_('Unable to update repository name'),
                    _('An error occurred while updating the repository hgrc '
                      'file (%s)') % hglib.tounicode(abshgrcpath))
                return False
            self.setShortName(value.toString())
            return True
        return False


_subrepoType2IcoMap = {
    'hg': 'hg',
    'git': 'thg-git-subrepo',
    'svn': 'thg-svn-subrepo',
    }

def _newSubrepoIcon(repotype, valid=True):
    subiconame = _subrepoType2IcoMap.get(repotype)
    if subiconame is None:
        ico = qtlib.geticon('thg-subrepo')
    else:
        ico = qtlib.geticon(subiconame)
        ico = qtlib.getoverlaidicon(ico, qtlib.geticon('thg-subrepo'))
    if not valid:
        ico = qtlib.getoverlaidicon(ico, qtlib.geticon('dialog-warning'))
    return ico

class StandaloneSubrepoItem(RepoItem):
    """Mercurial repository just decorated as subrepo"""
    xmltagname = 'subrepo'

    def data(self, column, role):
        if role == Qt.DecorationRole and column == 0:
            return _newSubrepoIcon('hg', valid=self._valid)
        else:
            return super(StandaloneSubrepoItem, self).data(column, role)

class SubrepoItem(RepoItem):
    """Actual Mercurial subrepo"""
    xmltagname = 'subrepo'

    def data(self, column, role):
        if role == Qt.DecorationRole and column == 0:
            return _newSubrepoIcon('hg', valid=self._valid)
        else:
            return super(SubrepoItem, self).data(column, role)

    def menulist(self):
        acts = ['open', 'clone', None, 'addsubrepo', 'removesubrepo',
                None, 'explore', 'terminal', 'copypath']
        if self.childCount() > 0:
            acts.extend([None, (_('&Sort'), ['sortbyname', 'sortbyhgsub'])])
        acts.extend([None, 'settings'])
        return acts

    def getSupportedDragDropActions(self):
        return Qt.CopyAction

    def flags(self):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

# possibly this should not be a RepoItem because it lacks common functions
class AlienSubrepoItem(RepoItem):
    """Actual non-Mercurial subrepo"""
    xmltagname = 'subrepo'

    def __init__(self, root, repotype, parent=None):
        RepoItem.__init__(self, root, parent=parent)
        self._repotype = repotype

    def data(self, column, role):
        if role == Qt.DecorationRole and column == 0:
            return _newSubrepoIcon(self._repotype)
        else:
            return super(AlienSubrepoItem, self).data(column, role)

    def menulist(self):
        return ['explore', 'terminal', 'copypath']

    def flags(self):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def repotype(self):
        return self._repotype

    def dump(self, xw):
        xw.writeAttribute('root', self._root)
        xw.writeAttribute('repotype', self._repotype)

    @classmethod
    def undump(cls, xr):
        a = xr.attributes()
        obj = cls(unicode(a.value('', 'root').toString()),
                  str(a.value('', 'repotype').toString()))
        xr.skipCurrentElement()  # no child
        return obj

    def appendSubrepos(self, repo=None):
        raise Exception('unsupported by non-hg subrepo')

def _newSubrepoItem(root, repotype):
    if repotype == 'hg':
        return SubrepoItem(root)
    else:
        return AlienSubrepoItem(root, repotype=repotype)

def _undumpSubrepoItem(xr):
    a = xr.attributes()
    repotype = str(a.value('', 'repotype').toString()) or 'hg'
    if repotype == 'hg':
        return SubrepoItem.undump(xr)
    else:
        return AlienSubrepoItem.undump(xr)

class RepoGroupItem(RepoTreeItem):
    xmltagname = 'group'

    def __init__(self, name, parent=None):
        RepoTreeItem.__init__(self, parent)
        self.name = name
        self._commonpath = ''

    def data(self, column, role):
        if role == Qt.DecorationRole:
            if column == 0:
                s = QApplication.style()
                ico = s.standardIcon(QStyle.SP_DirIcon)
                return QVariant(ico)
            return QVariant()
        if column == 0:
            return QVariant(self.name)
        elif column == 1:
            return QVariant(self.getCommonPath())
        return QVariant()

    def setData(self, column, value):
        if column == 0:
            self.name = unicode(value.toString())
            return True
        return False

    def rootpath(self):  # for sortbypath()
        return ''  # may be okay to return _commonpath instead?

    def shortname(self):  # for sortbyname()
        return self.name

    def menulist(self):
        return ['openAll', 'add', None, 'newGroup', None, 'rename', 'remove',
            None, (_('&Sort'), ['sortbyname', 'sortbypath']), None,
            'reloadRegistry']

    def flags(self):
        return (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled
            | Qt.ItemIsDragEnabled | Qt.ItemIsEditable)

    def childRoots(self):
        return [c._root for c in self.childs if isinstance(c, RepoItem)]

    def dump(self, xw):
        xw.writeAttribute('name', self.name)
        _dumpChild(xw, parent=self)

    @classmethod
    def undump(cls, xr):
        a = xr.attributes()
        obj = cls(unicode(a.value('', 'name').toString()))
        _undumpChild(xr, parent=obj)
        return obj

    def okToDelete(self):
        return False

    def updateCommonPath(self, cpath=None):
        """
        Update or set the group 'common path'

        When called with no arguments, the group common path is calculated by
        looking for the common path of all the repos on a repo group

        When called with an argument, the group common path is set to the input
        argument. This is commonly used to set the group common path to an empty
        string, thus disabling the "show short paths" functionality.
        """
        if cpath is not None:
            self._commonpath = cpath
        elif len(self.childs) == 0:
            # If a group has no repo items, the common path is empty
            self._commonpath = ''
        else:
            childs = [os.path.normcase(child.rootpath())
                      for child in self.childs
                      if not isinstance(child, RepoGroupItem)]
            self._commonpath = os.path.dirname(os.path.commonprefix(childs))

    def getCommonPath(self):
        return self._commonpath

class AllRepoGroupItem(RepoGroupItem):
    xmltagname = 'allgroup'

    def __init__(self, name=None, parent=None):
        RepoGroupItem.__init__(self, name or _('default'), parent=parent)

    def menulist(self):
        return ['openAll', 'add', None, 'newGroup', None, 'rename',
            None, (_('&Sort'), ['sortbyname', 'sortbypath']), None,
            'reloadRegistry']

_xmlUndumpMap = {
    'allgroup': AllRepoGroupItem.undump,
    'group': RepoGroupItem.undump,
    'repo': RepoItem.undump,
    'subrepo': StandaloneSubrepoItem.undump,
    'treeitem': RepoTreeItem.undump,
    }
