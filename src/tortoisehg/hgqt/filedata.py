# filedata.py - generate displayable file data
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, posixpath
import cStringIO

from mercurial import commands, error, match, patch, subrepo, util, mdiff
from mercurial import copies
from mercurial import ui as uimod
from mercurial.node import nullrev

from tortoisehg.util import hglib, patchctx
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import fileencoding

forcedisplaymsg = _('Display the file anyway')

class _BadContent(Exception):
    """Failed to display file because it is binary or size limit exceeded"""

def _exceedsMaxLineLength(data, maxlength=100000):
    if len(data) < maxlength:
        return False
    for line in data.splitlines():
        if len(line) > maxlength:
            return True
    return False

def _checkdifferror(data, maxdiff):
    p = _('Diff not displayed: ')
    size = len(data)
    if size > maxdiff:
        return p + _('File is larger than the specified max size.\n'
                     'maxdiff = %s KB') % (maxdiff // 1024)
    elif '\0' in data:
        return p + _('File is binary')
    elif _exceedsMaxLineLength(data):
        # it's incredibly slow to render long line by QScintilla
        return p + _('File may be binary (maximum line length exceeded)')

def _trimdiffheader(diff):
    # trim first three lines, for example:
    # diff -r f6bfc41af6d7 -r c1b18806486d tortoisehg/hgqt/mq.py
    # --- a/tortoisehg/hgqt/mq.py
    # +++ b/tortoisehg/hgqt/mq.py
    out = diff.split('\n', 3)
    if len(out) == 4:
        return out[3]
    else:
        # there was an error or rename without diffs
        return diff


class _AbstractFileData(object):

    def __init__(self, ctx, ctx2, wfile, status=None, rpath=None):
        self._ctx = ctx
        self._pctx = ctx2
        self._wfile = wfile
        self._status = status
        self._rpath = rpath or ''
        self.contents = None
        self.ucontents = None
        self.error = None
        self.olddata = None
        self.diff = None
        self.flabel = u''
        self.elabel = u''
        self.changes = None

        self._textencoding = fileencoding.contentencoding(ctx._repo.ui)

    def createRebased(self, pctx):
        # new status is not known
        return self.__class__(self._ctx, pctx, self._wfile, rpath=self._rpath)

    def load(self, changeselect=False, force=False):
        # Note: changeselect may be set to True even if the underlying data
        # isn't chunk-selectable
        raise NotImplementedError

    def __eq__(self, other):
        # unlike changectx, this also compares hash in case it was stripped and
        # recreated.  FileData may live longer than changectx in Mercurial.
        return (isinstance(other, self.__class__)
                and self._ctx == other._ctx
                and self._ctx.node() == other._ctx.node()
                and self._pctx == other._pctx
                and (self._pctx is None
                     or self._pctx.node() == other._pctx.node())
                and self._wfile == other._wfile
                and self._rpath == other._rpath)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self._ctx, self._ctx.node(),
                     self._pctx, self._pctx is None or self._pctx.node(),
                     self._wfile, self._rpath))

    def __repr__(self):
        return '<%s %s@%s>' % (self.__class__.__name__,
                               posixpath.join(self._rpath, self._wfile),
                               self._ctx)

    def isLoaded(self):
        loadables = [self.contents, self.ucontents, self.error, self.diff]
        return any(e is not None for e in loadables)

    def isNull(self):
        return self._ctx.rev() == nullrev and not self._wfile

    def isValid(self):
        return self.error is None and not self.isNull()

    def rev(self):
        return self._ctx.rev()

    def baseRev(self):
        return self._pctx.rev()

    def parentRevs(self):
        # may contain nullrev, which allows "nullrev in parentRevs()"
        return [p.rev() for p in self._ctx.parents()]

    def rawContext(self):
        return self._ctx

    def rawBaseContext(self):
        return self._pctx

    # absoluteFilePath    : "C:\\Documents\\repo\\foo\\subrepo\\bar\\baz"
    # absoluteRepoRootPath: "C:\\Documents\\repo\\foo\\subrepo"
    # canonicalFilePath: "bar/baz"
    # filePath         : "foo/subrepo/bar/baz"
    # repoRootPath     : "foo/subrepo"

    def absoluteFilePath(self):
        """Absolute file-system path of this file"""
        repo = self._ctx._repo
        return hglib.tounicode(os.path.normpath(repo.wjoin(self._wfile)))

    def absoluteRepoRootPath(self):
        """Absolute file-system path to the root of the container repository"""
        # repo.root should be normalized
        repo = self._ctx._repo
        return hglib.tounicode(repo.root)

    def canonicalFilePath(self):
        """Path relative to the repository root which contains this file"""
        return hglib.tounicode(self._wfile)

    def filePath(self):
        """Path relative to the top repository root in the current context"""
        return hglib.tounicode(posixpath.join(self._rpath, self._wfile))

    def repoRootPath(self):
        """Root path of the container repository relative to the top repository
        in the current context; '' for top repository"""
        return hglib.tounicode(self._rpath)

    def fileStatus(self):
        return self._status

    def isDir(self):
        return not self._wfile

    def mergeStatus(self):
        pass

    def subrepoType(self):
        pass

    def textEncoding(self):
        return self._textencoding

    def setTextEncoding(self, name):
        self._textencoding = fileencoding.canonname(name)

    def detectTextEncoding(self):
        ui = self._ctx._repo.ui
        # use file content for better guess; diff may be mixed encoding or
        # have immature multi-byte sequence
        data = self.contents or self.diff or ''
        fallbackenc = self._textencoding
        self._textencoding = fileencoding.guessencoding(ui, data, fallbackenc)

    def _textToUnicode(self, s):
        return s.decode(self._textencoding, 'replace')

    def diffText(self):
        return self._textToUnicode(self.diff or '')

    def fileText(self):
        return self._textToUnicode(self.contents or '')


class FileData(_AbstractFileData):

    def __init__(self, ctx, pctx, path, status=None, rpath=None, mstatus=None):
        super(FileData, self).__init__(ctx, pctx, path, status, rpath)
        self._mstatus = mstatus

    def load(self, changeselect=False, force=False):
        if self.rev() == nullrev:
            return
        ctx = self._ctx
        ctx2 = self._pctx
        wfile = self._wfile
        status = self._status
        errorprefix = _('File or diffs not displayed: ')
        try:
            self._readStatus(ctx, ctx2, wfile, status, changeselect, force)
        except _BadContent, e:
            self.error = errorprefix + e.args[0] + '\n\n' + forcedisplaymsg
        except (EnvironmentError, error.LookupError, util.Abort), e:
            self.error = errorprefix + hglib.tounicode(str(e))

    def _checkMaxDiff(self, ctx, wfile, maxdiff, force):
        self.error = None
        fctx = ctx.filectx(wfile)
        if ctx.rev() is None:
            size = fctx.size()
        else:
            # fctx.size() can read all data into memory in rename cases so
            # we read the size directly from the filelog, this is deeper
            # under the API than I prefer to go, but seems necessary
            size = fctx._filelog.rawsize(fctx.filerev())
        if not force and size > maxdiff:
            raise _BadContent(_('File is larger than the specified max size.\n'
                                'maxdiff = %s KB') % (maxdiff // 1024))

        data = fctx.data()
        if not force:
            if '\0' in data or ctx.isStandin(wfile):
                raise _BadContent(_('File is binary'))
            elif _exceedsMaxLineLength(data):
                # it's incredibly slow to render long line by QScintilla
                raise _BadContent(_('File may be binary (maximum line length '
                                    'exceeded)'))
        return fctx, data

    def _checkRenamed(self, repo, ctx, pctx, wfile):
        m = match.exact(repo, '', [wfile])
        copy = copies.pathcopies(pctx, ctx, match=m)
        oldname = copy.get(wfile)
        if not oldname:
            self.flabel += _(' <i>(was added)</i>')
            return
        fr = hglib.tounicode(oldname)
        if oldname in ctx:
            self.flabel += _(' <i>(copied from %s)</i>') % fr
        else:
            self.flabel += _(' <i>(renamed from %s)</i>') % fr
        return oldname

    def _readStatus(self, ctx, ctx2, wfile, status, changeselect, force):
        def getstatus(repo, n1, n2, wfile):
            m = match.exact(repo.root, repo.getcwd(), [wfile])
            modified, added, removed = repo.status(n1, n2, match=m)[:3]
            if wfile in modified:
                return 'M'
            if wfile in added:
                return 'A'
            if wfile in removed:
                return 'R'
            if wfile in ctx:
                return 'C'
            return None

        isbfile = False
        repo = ctx._repo
        maxdiff = repo.maxdiff
        self.flabel = u'<b>%s</b>' % self.filePath()

        if ctx2:
            # If a revision to compare to was provided, we must put it in
            # the context of the subrepo as well
            if ctx2._repo.root != ctx._repo.root:
                wsub2, wfileinsub2, sctx2 = \
                    hglib.getDeepestSubrepoContainingFile(wfile, ctx2)
                if wsub2:
                    ctx2 = sctx2

        absfile = repo.wjoin(wfile)
        if (wfile in ctx and 'l' in ctx.flags(wfile)) or \
           os.path.islink(absfile):
            if wfile in ctx:
                data = ctx[wfile].data()
            else:
                data = os.readlink(absfile)
            self.contents = data
            self.flabel += _(' <i>(is a symlink)</i>')
            return

        if ctx2 is None:
            ctx2 = ctx.p1()
        if status is None:
            status = getstatus(repo, ctx2.node(), ctx.node(), wfile)

        mde = _('File or diffs not displayed: '
                'File is larger than the specified max size.\n'
                'maxdiff = %s KB') % (maxdiff // 1024)

        if status in ('R', '!'):
            if wfile in ctx.p1():
                fctx = ctx.p1()[wfile]
                if fctx._filelog.rawsize(fctx.filerev()) > maxdiff:
                    self.error = mde
                else:
                    olddata = fctx.data()
                    if '\0' in olddata:
                        self.error = 'binary file'
                    else:
                        self.contents = olddata
                self.flabel += _(' <i>(was deleted)</i>')
            elif hasattr(ctx.p1(), 'hasStandin') and ctx.p1().hasStandin(wfile):
                self.error = 'binary file'
                self.flabel += _(' <i>(was deleted)</i>')
            else:
                self.flabel += _(' <i>(was added, now missing)</i>')
            return

        if status in ('I', '?'):
            assert ctx.rev() is None
            self.flabel += _(' <i>(is unversioned)</i>')
            if os.path.getsize(absfile) > maxdiff:
                self.error = mde
                return
            data = util.posixfile(absfile, 'r').read()
            if not force and '\0' in data:
                self.error = 'binary file'
            else:
                self.contents = data
            return

        if status in ('M', 'A', 'C'):
            if ctx.hasStandin(wfile):
                wfile = ctx.findStandin(wfile)
                isbfile = True
            try:
                fctx, newdata = self._checkMaxDiff(ctx, wfile, maxdiff, force)
            except _BadContent:
                if status == 'A':
                    self._checkRenamed(repo, ctx, ctx2, wfile)
                raise
            self.contents = newdata
            if status == 'C':
                # no further comparison is necessary
                return
            for pctx in ctx.parents():
                if 'x' in fctx.flags() and 'x' not in pctx.flags(wfile):
                    self.elabel = _("exec mode has been "
                                    "<font color='red'>set</font>")
                elif 'x' not in fctx.flags() and 'x' in pctx.flags(wfile):
                    self.elabel = _("exec mode has been "
                                    "<font color='red'>unset</font>")

        if status == 'A':
            oldname = self._checkRenamed(repo, ctx, ctx2, wfile)
            if not oldname:
                return
            olddata = ctx2[oldname].data()
        elif status == 'M':
            if wfile not in ctx2:
                # merge situation where file was added in other branch
                self.flabel += _(' <i>(was added)</i>')
                return
            oldname = wfile
            olddata = ctx2[wfile].data()
        else:
            return

        self.olddata = olddata
        if changeselect:
            diffopts = patch.diffopts(repo.ui, {})
            diffopts.git = True
            m = match.exact(repo.root, repo.root, [wfile])
            fp = cStringIO.StringIO()
            for c in patch.diff(repo, ctx.node(), None, match=m, opts=diffopts):
                fp.write(c)
            fp.seek(0)

            # feed diffs through parsepatch() for more fine grained
            # chunk selection
            filediffs = patch.parsepatch(fp)
            if filediffs and filediffs[0].hunks:
                self.changes = filediffs[0]
            else:
                self.diff = ''
                return
            self.changes.excludecount = 0
            values = []
            lines = 0
            for chunk in self.changes.hunks:
                buf = cStringIO.StringIO()
                chunk.write(buf)
                chunk.excluded = False
                val = buf.getvalue()
                values.append(val)
                chunk.lineno = lines
                chunk.linecount = len(val.splitlines())
                lines += chunk.linecount
            self.diff = ''.join(values)
        else:
            diffopts = patch.diffopts(repo.ui, {})
            diffopts.git = False
            newdate = util.datestr(ctx.date())
            olddate = util.datestr(ctx2.date())
            if isbfile:
                olddata += '\0'
                newdata += '\0'
            difftext = mdiff.unidiff(olddata, olddate, newdata, newdate,
                                     oldname, wfile, opts=diffopts)
            if difftext:
                self.diff = ('diff -r %s -r %s %s\n' % (ctx, ctx2, oldname)
                             + difftext)
            else:
                self.diff = ''

    def mergeStatus(self):
        return self._mstatus

    def diffText(self):
        udiff = self._textToUnicode(self.diff or '')
        if self.changes:
            return udiff
        return _trimdiffheader(udiff)

    def setChunkExcluded(self, chunk, exclude):
        assert chunk in self.changes.hunks
        if chunk.excluded == exclude:
            return
        if exclude:
            chunk.excluded = True
            self.changes.excludecount += 1
        else:
            chunk.excluded = False
            self.changes.excludecount -= 1


class DirData(_AbstractFileData):

    def load(self, changeselect=False, force=False):
        self.error = None
        self.flabel = u'<b>%s</b>' % self.filePath()

        # TODO: enforce maxdiff before generating diff?
        ctx = self._ctx
        pctx = self._pctx
        try:
            m = ctx.match(['path:%s' % self._wfile])
            self.diff = ''.join(ctx.diff(pctx, m))
        except (EnvironmentError, util.Abort), e:
            self.error = hglib.tounicode(str(e))
            return

        if not force:
            self.error = _checkdifferror(self.diff, ctx._repo.maxdiff)
            if self.error:
                self.error += u'\n\n' + forcedisplaymsg

    def isDir(self):
        return True


class PatchFileData(_AbstractFileData):

    def load(self, changeselect=False, force=False):
        ctx = self._ctx
        wfile = self._wfile
        maxdiff = ctx._repo.maxdiff

        self.error = None
        self.flabel = u'<b>%s</b>' % self.filePath()

        try:
            self.diff = ctx.thgmqpatchdata(wfile)
            flags = ctx.flags(wfile)
        except EnvironmentError, e:
            self.error = hglib.tounicode(str(e))
            return

        if flags == 'x':
            self.elabel = _("exec mode has been "
                            "<font color='red'>set</font>")
        elif flags == '-':
            self.elabel = _("exec mode has been "
                            "<font color='red'>unset</font>")
        elif flags == 'l':
            self.flabel += _(' <i>(is a symlink)</i>')

        # Do not show patches that are too big or may be binary
        if not force:
            self.error = _checkdifferror(self.diff, maxdiff)
            if self.error:
                self.error += u'\n\n' + forcedisplaymsg

    def rev(self):
        # avoid mixing integer and localstr
        return nullrev

    def baseRev(self):
        # patch has no comparison base
        return nullrev

    def diffText(self):
        return _trimdiffheader(self._textToUnicode(self.diff or ''))


class PatchDirData(_AbstractFileData):

    def load(self, changeselect=False, force=False):
        self.error = None
        self.flabel = u'<b>%s</b>' % self.filePath()

        ctx = self._ctx
        try:
            self.diff = ''.join([ctx.thgmqpatchdata(f) for f in ctx.files()
                                 if f.startswith(self._wfile + '/')])
        except EnvironmentError, e:
            self.error = hglib.tounicode(str(e))
            return

        if not force:
            self.error = _checkdifferror(self.diff, ctx._repo.maxdiff)
            if self.error:
                self.error += u'\n\n' + forcedisplaymsg

    def rev(self):
        # avoid mixing integer and localstr
        return nullrev

    def baseRev(self):
        # patch has no comparison base
        return nullrev

    def isDir(self):
        return True


class SubrepoData(_AbstractFileData):

    def __init__(self, ctx, pctx, path, status, rpath, subkind):
        super(SubrepoData, self).__init__(ctx, pctx, path, status, rpath)
        self._subkind = subkind

    def createRebased(self, pctx):
        # new status should be unknown, but currently it is 'S'
        assert self._status == 'S'  # TODO: replace 'S' by subrepo's status
        return self.__class__(self._ctx, pctx, self._wfile, status=self._status,
                              rpath=self._rpath, subkind=self._subkind)

    def load(self, changeselect=False, force=False):
        ctx = self._ctx
        ctx2 = self._pctx
        if ctx2 is None:
            ctx2 = ctx.p1()
        wfile = self._wfile

        self.error = None
        self.flabel = u'<b>%s</b>' % self.filePath()

        try:
            def genSubrepoRevChangedDescription(subrelpath, sfrom, sto,
                                                repo):
                """Generate a subrepository revision change description"""
                out = []
                def getLog(_ui, srepo, opts):
                    if srepo is None:
                        return _('changeset: %s') % opts['rev'][0][:12]
                    _ui.pushbuffer()
                    logOutput = ''
                    try:
                        commands.log(_ui, srepo, **opts)
                        logOutput = _ui.popbuffer()
                        if not logOutput:
                            return _('Initial revision') + u'\n'
                    except error.ParseError, e:
                        # Some mercurial versions have a bug that results in
                        # saving a subrepo node id in the .hgsubstate file
                        # which ends with a "+" character. If that is the
                        # case, add a warning to the output, but try to
                        # get the revision information anyway
                        for n, rev in enumerate(opts['rev']):
                            if rev.endswith('+'):
                                logOutput += _('[WARNING] Invalid subrepo '
                                    'revision ID:\n\t%s\n\n') % rev
                                opts['rev'][n] = rev[:-1]
                        commands.log(_ui, srepo, **opts)
                        logOutput += _ui.popbuffer()
                    return hglib.tounicode(logOutput)

                opts = {'date':None, 'user':None, 'rev':[sfrom]}
                subabspath = os.path.join(repo.root, subrelpath)
                missingsub = srepo is None or not os.path.isdir(subabspath)
                sfromlog = ''
                def isinitialrevision(rev):
                    return all([el == '0' for el in rev])
                if isinitialrevision(sfrom):
                    sfrom = ''
                if isinitialrevision(sto):
                    sto = ''
                header = ''
                if not sfrom and not sto:
                    sstatedesc = 'new'
                    out.append(_('Subrepo created and set to initial '
                                 'revision.') + u'\n\n')
                    return out, sstatedesc
                elif not sfrom:
                    sstatedesc = 'new'
                    header = _('Subrepo initialized to revision:') + u'\n\n'
                elif not sto:
                    sstatedesc = 'removed'
                    out.append(_('Subrepo removed from repository.')
                               + u'\n\n')
                    out.append(_('Previously the subrepository was '
                                 'at the following revision:') + u'\n\n')
                    subinfo = getLog(_ui, srepo, {'rev': [sfrom]})
                    slog = hglib.tounicode(subinfo)
                    out.append(slog)
                    return out, sstatedesc
                elif sfrom == sto:
                    sstatedesc = 'unchanged'
                    header = _('Subrepo was not changed.')
                    slog = _('changeset: %s') % sfrom[:12] + u'\n'
                    if missingsub:
                        header = _('[WARNING] Missing subrepo. '
                               'Update to this revision to clone it.') \
                             + u'\n\n' + header
                    else:
                        try:
                            slog = getLog(_ui, srepo, opts)
                        except error.RepoError:
                            header = _('[WARNING] Incomplete subrepo. '
                               'Update to this revision to pull it.') \
                             + u'\n\n' + header
                    out.append(header + u' ')
                    out.append(_('Subrepo state is:') + u'\n\n' + slog)
                    return out, sstatedesc
                else:
                    sstatedesc = 'changed'

                    header = _('Revision has changed to:') + u'\n\n'
                    sfromlog = _('changeset: %s') % sfrom[:12] + u'\n\n'
                    if not missingsub:
                        try:
                            sfromlog = getLog(_ui, srepo, opts)
                        except error.RepoError:
                            sfromlog = _('changeset: %s '
                                         '(not found on subrepository)') \
                                            % sfrom[:12] + u'\n\n'
                    sfromlog = _('From:') + u'\n' + sfromlog

                stolog = ''
                if missingsub:
                    header = _(
                        '[WARNING] Missing changed subrepository. '
                        'Update to this revision to clone it.') \
                        + u'\n\n' + header
                    stolog = _('changeset: %s') % sto[:12] + '\n\n'
                    sfromlog += _(
                        'Subrepository not found in the working '
                        'directory.') + '\n'
                else:
                    try:
                        opts['rev'] = [sto]
                        stolog = getLog(_ui, srepo, opts)
                    except error.RepoError:
                        header = _(
                            '[WARNING] Incomplete changed subrepository. '
                            'Update to this revision to pull it.') \
                             + u'\n\n' + header
                        stolog = _('changeset: %s '
                                   '(not found on subrepository)') \
                                 % sto[:12] + u'\n\n'
                out.append(header)
                out.append(stolog)

                if sfromlog:
                    out.append(sfromlog)

                return out, sstatedesc

            srev = ctx.substate.get(wfile, subrepo.nullstate)[1]
            srepo = None
            subabspath = os.path.join(ctx._repo.root, wfile)
            sactual = ''
            if os.path.isdir(subabspath):
                try:
                    sub = ctx.sub(wfile)
                    if isinstance(sub, subrepo.hgsubrepo):
                        srepo = sub._repo
                        if srepo is not None:
                            sactual = srepo['.'].hex()
                    else:
                        self.error = _('Not a Mercurial subrepo, not '
                                       'previewable')
                        return
                except util.Abort, e:
                    self.error = (_('Error previewing subrepo: %s')
                                  % hglib.tounicode(str(e))) + u'\n\n'
                    self.error += _('Subrepo may be damaged or '
                                    'inaccessible.')
                    return
                except KeyError, e:
                    # Missing, incomplete or removed subrepo.
                    # Will be handled later as such below
                    pass
            out = []
            _ui = uimod.ui()

            if srepo is None or ctx.rev() is not None:
                data = []
            else:
                _ui.pushbuffer()
                commands.status(_ui, srepo, modified=True, added=True,
                                removed=True, deleted=True)
                data = _ui.popbuffer()
                if data:
                    out.append(_('The subrepository is dirty.') + u' '
                               + _('File Status:') + u'\n')
                    out.append(hglib.tounicode(data))
                    out.append(u'\n')

            sstatedesc = 'changed'
            if ctx.rev() is not None:
                sparent = ctx2.substate.get(wfile, subrepo.nullstate)[1]
                subrepochange, sstatedesc = \
                    genSubrepoRevChangedDescription(wfile,
                        sparent, srev, ctx._repo)
                out += subrepochange
            else:
                sstatedesc = 'dirty'
                if srev != sactual:
                    subrepochange, sstatedesc = \
                        genSubrepoRevChangedDescription(wfile,
                            srev, sactual, ctx._repo)
                    out += subrepochange
                    if data:
                        sstatedesc += ' and dirty'
                elif srev and not sactual:
                    sstatedesc = 'removed'
            self.ucontents = u''.join(out).strip()

            lbl = {
                'changed':   _('(is a changed sub-repository)'),
                'unchanged':   _('(is an unchanged sub-repository)'),
                'dirty':   _('(is a dirty sub-repository)'),
                'new':   _('(is a new sub-repository)'),
                'removed':   _('(is a removed sub-repository)'),
                'changed and dirty': _('(is a changed and dirty '
                                       'sub-repository)'),
                'new and dirty':   _('(is a new and dirty sub-repository)'),
                'removed and dirty':   _('(is a removed sub-repository)')
            }[sstatedesc]
            self.flabel += ' <i>' + lbl + '</i>'
            if sactual:
                lbl = ' <a href="repo:%%s">%s</a>' % _('open...')
                self.flabel += lbl % hglib.tounicode(srepo.root)
        except (EnvironmentError, error.RepoError, util.Abort), e:
            self.error = _('Error previewing subrepo: %s') % \
                    hglib.tounicode(str(e))

    def isDir(self):
        return True

    def subrepoType(self):
        return self._subkind


def createFileData(ctx, ctx2, wfile, status=None, rpath=None, mstatus=None):
    if isinstance(ctx, patchctx.patchctx):
        if mstatus:
            raise ValueError('invalid merge status for patch: %r' % mstatus)
        return PatchFileData(ctx, ctx2, wfile, status, rpath)
    return FileData(ctx, ctx2, wfile, status, rpath, mstatus)

def createDirData(ctx, pctx, path, rpath=None):
    if isinstance(ctx, patchctx.patchctx):
        return PatchDirData(ctx, pctx, path, rpath=rpath)
    return DirData(ctx, pctx, path, rpath=rpath)

def createSubrepoData(ctx, pctx, path, status=None, rpath=None, subkind=None):
    if not subkind:
        subkind = ctx.substate.get(path, subrepo.nullstate)[2]
    # TODO: replace 'S' by subrepo's status
    return SubrepoData(ctx, pctx, path, 'S', rpath, subkind)

def createNullData(repo):
    ctx = repo[nullrev]
    fd = FileData(ctx, ctx.p1(), '', 'C')
    return fd
