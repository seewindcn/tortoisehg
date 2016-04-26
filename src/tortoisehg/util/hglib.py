# hglib.py - Mercurial API wrappers for TortoiseHg
#
# Copyright 2007 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import cStringIO
import glob
import os
import re
import sys
import shlex
import time

from mercurial import ui, util, extensions
from mercurial import encoding, templatefilters, filemerge, error, pathutil
from mercurial import dispatch as dispatchmod
from mercurial import merge as mergemod
from mercurial import revset as revsetmod
from mercurial.node import nullrev
from hgext import mq as mqmod

_encoding = encoding.encoding
_fallbackencoding = encoding.fallbackencoding

# extensions which can cause problem with TortoiseHg
_extensions_blacklist = ('color', 'pager', 'progress', 'zeroconf')

from tortoisehg.util import paths
from tortoisehg.util.hgversion import hgversion
from tortoisehg.util.i18n import _ as _gettext, ngettext as _ngettext

# TODO: use unicode version globally
def _(message, context=''):
    return _gettext(message, context).encode('utf-8')
def ngettext(singular, plural, n):
    return _ngettext(singular, plural, n).encode('utf-8')

def tounicode(s):
    """
    Convert the encoding of string from MBCS to Unicode.

    Based on mercurial.util.tolocal().
    Return 'unicode' type string.
    """
    if s is None:
        return None
    if isinstance(s, unicode):
        return s
    if isinstance(s, encoding.localstr):
        return s._utf8.decode('utf-8')
    try:
        return s.decode(_encoding, 'strict')
    except UnicodeDecodeError:
        pass
    return s.decode(_fallbackencoding, 'replace')

def fromunicode(s, errors='strict'):
    """
    Convert the encoding of string from Unicode to MBCS.

    Return 'str' type string.

    If you don't want an exception for conversion failure,
    specify errors='replace'.
    """
    if s is None:
        return None
    s = unicode(s)  # s can be QtCore.QString
    for enc in (_encoding, _fallbackencoding):
        try:
            l = s.encode(enc)
            if s == l.decode(enc):
                return l  # non-lossy encoding
            return encoding.localstr(s.encode('utf-8'), l)
        except UnicodeEncodeError:
            pass

    l = s.encode(_encoding, errors)  # last ditch
    return encoding.localstr(s.encode('utf-8'), l)

def toutf(s):
    """
    Convert the encoding of string from MBCS to UTF-8.

    Return 'str' type string.
    """
    if s is None:
        return None
    if isinstance(s, encoding.localstr):
        return s._utf8
    return tounicode(s).encode('utf-8').replace('\0','')

def fromutf(s):
    """
    Convert the encoding of string from UTF-8 to MBCS

    Return 'str' type string.
    """
    if s is None:
        return None
    try:
        return fromunicode(s.decode('utf-8'), 'replace')
    except UnicodeDecodeError:
        # can't round-trip
        return str(fromunicode(s.decode('utf-8', 'replace'), 'replace'))


def activebookmark(repo):
    return repo._activebookmark

def namedbranches(repo):
    branchmap = repo.branchmap()
    dead = repo.deadbranches
    return sorted(br for br, _heads, _tip, isclosed
                  in branchmap.iterbranches()
                  if not isclosed and br not in dead)

def _firstchangectx(repo):
    try:
        # try fast path, which may be hidden
        return repo[0]
    except error.RepoLookupError:
        pass
    for rev in revsetmod.spanset(repo):
        return repo[rev]
    return repo[nullrev]

def shortrepoid(repo):
    """Short hash of the first root changeset; can be used for settings key"""
    return str(_firstchangectx(repo))

def repoidnode(repo):
    """Hash of the first root changeset in binary form"""
    return _firstchangectx(repo).node()

def _getfirstrevisionlabel(repo, ctx):
    # see context.changectx for look-up order of labels

    bookmarks = ctx.bookmarks()
    if ctx in repo[None].parents():
        # keep bookmark unchanged when updating to current rev
        if activebookmark(repo) in bookmarks:
            return activebookmark(repo)
    else:
        # more common switching bookmark, rather than deselecting it
        if bookmarks:
            return bookmarks[0]

    tags = ctx.tags()
    if tags:
        return tags[0]

    branch = ctx.branch()
    if repo.branchtip(branch) == ctx.node():
        return branch

def getrevisionlabel(repo, rev):
    """Return symbolic name for the specified revision or stringfy it"""
    if rev is None:
        return None  # no symbol for working revision

    ctx = repo[rev]
    label = _getfirstrevisionlabel(repo, ctx)
    if label and ctx == repo[label]:
        return label

    return str(rev)

def getmqpatchtags(repo):
    '''Returns all tag names used by MQ patches, or []'''
    if hasattr(repo, 'mq'):
        repo.mq.parseseries()
        return repo.mq.series[:]
    else:
        return []

def getcurrentqqueue(repo):
    """Return the name of the current patch queue."""
    if not hasattr(repo, 'mq'):
        return None
    cur = os.path.basename(repo.mq.path)
    if cur.startswith('patches-'):
        cur = cur[8:]
    return cur

def getqqueues(repo):
    ui = repo.ui.copy()
    ui.quiet = True  # don't append "(active)"
    ui.pushbuffer()
    try:
        opts = {'list': True}
        mqmod.qqueue(ui, repo, None, **opts)
        qqueues = tounicode(ui.popbuffer()).splitlines()
    except (util.Abort, EnvironmentError):
        qqueues = []
    return qqueues

try:
    readmergestate = mergemod.mergestate.read
except AttributeError:
    # hg<3.7 (2ddc92bae4a7, 3185c01c551c)
    readmergestate = mergemod.mergestate

def readundodesc(repo):
    """Read short description and changelog size of last transaction"""
    if os.path.exists(repo.sjoin('undo')):
        try:
            args = repo.opener('undo.desc', 'r').read().splitlines()
            return args[1], int(args[0])
        except (IOError, IndexError, ValueError):
            pass
    return '', len(repo)

def enabledextensions():
    """Return the {name: shortdesc} dict of enabled extensions

    shortdesc is in local encoding.
    """
    return extensions.enabled()

def disabledextensions():
    return extensions.disabled()

def allextensions():
    """Return the {name: shortdesc} dict of known extensions

    shortdesc is in local encoding.
    """
    enabledexts = enabledextensions()
    disabledexts = disabledextensions()
    exts = (disabledexts or {}).copy()
    exts.update(enabledexts)
    if hasattr(sys, "frozen"):
        if 'hgsubversion' not in exts:
            exts['hgsubversion'] = _('hgsubversion packaged with thg')
        if 'hggit' not in exts:
            exts['hggit'] = _('hggit packaged with thg')
    return exts

def validateextensions(enabledexts):
    """Report extensions which should be disabled

    Returns the dict {name: message} of extensions expected to be disabled.
    message is 'utf-8'-encoded string.
    """
    exts = {}
    if os.name != 'posix':
        exts['inotify'] = _('inotify is not supported on this platform')
    if 'win32text' in enabledexts:
        exts['eol'] = _('eol is incompatible with win32text')
    if 'eol' in enabledexts:
        exts['win32text'] = _('win32text is incompatible with eol')
    if 'perfarce' in enabledexts:
        exts['hgsubversion'] = _('hgsubversion is incompatible with perfarce')
    if 'hgsubversion' in enabledexts:
        exts['perfarce'] = _('perfarce is incompatible with hgsubversion')
    return exts

def _loadextensionwithblacklist(orig, ui, name, path):
    if name.startswith('hgext.') or name.startswith('hgext/'):
        shortname = name[6:]
    else:
        shortname = name
    if shortname in _extensions_blacklist and not path:  # only bundled ext
        return

    return orig(ui, name, path)

def wrapextensionsloader():
    """Wrap extensions.load(ui, name) for blacklist to take effect"""
    extensions.wrapfunction(extensions, 'load',
                            _loadextensionwithblacklist)

# TODO: provide singular canonpath() wrapper instead?
def canonpaths(list):
    'Get canonical paths (relative to root) for list of files'
    # This is a horrible hack.  Please remove this when HG acquires a
    # decent case-folding solution.
    canonpats = []
    cwd = os.getcwd()
    root = paths.find_root(cwd)
    for f in list:
        try:
            canonpats.append(pathutil.canonpath(root, cwd, f))
        except util.Abort:
            # Attempt to resolve case folding conflicts.
            fu = f.upper()
            cwdu = cwd.upper()
            if fu.startswith(cwdu):
                canonpats.append(
                    pathutil.canonpath(root, cwd, f[len(cwd + os.sep):]))
            else:
                # May already be canonical
                canonpats.append(f)
    return canonpats

def normreporoot(path):
    """Normalize repo root path in the same manner as localrepository"""
    # see localrepo.localrepository and scmutil.vfs
    lpath = fromunicode(path)
    lpath = os.path.realpath(util.expandpath(lpath))
    return tounicode(lpath)


def mergetools(ui, values=None):
    'returns the configured merge tools and the internal ones'
    if values == None:
        values = []
    seen = values[:]
    for key, value in ui.configitems('merge-tools'):
        t = key.split('.')[0]
        if t not in seen:
            seen.append(t)
            # Ensure the tool is installed
            if filemerge._findtool(ui, t):
                values.append(t)
    values.append('internal:merge')
    values.append('internal:prompt')
    values.append('internal:dump')
    values.append('internal:local')
    values.append('internal:other')
    values.append('internal:fail')
    return values


_difftools = None
def difftools(ui):
    global _difftools
    if _difftools:
        return _difftools

    def fixup_extdiff(diffopts):
        if '$child' not in diffopts:
            diffopts.append('$parent1')
            diffopts.append('$child')
        if '$parent2' in diffopts:
            mergeopts = diffopts[:]
            diffopts.remove('$parent2')
        else:
            mergeopts = []
        return diffopts, mergeopts

    tools = {}
    for cmd, path in ui.configitems('extdiff'):
        if cmd.startswith('cmd.'):
            cmd = cmd[4:]
            if not path:
                path = cmd
            diffopts = ui.config('extdiff', 'opts.' + cmd, '')
            diffopts = shlex.split(diffopts)
            diffopts, mergeopts = fixup_extdiff(diffopts)
            tools[cmd] = [path, diffopts, mergeopts]
        elif cmd.startswith('opts.'):
            continue
        else:
            # command = path opts
            if path:
                diffopts = shlex.split(path)
                path = diffopts.pop(0)
            else:
                path, diffopts = cmd, []
            diffopts, mergeopts = fixup_extdiff(diffopts)
            tools[cmd] = [path, diffopts, mergeopts]
    mt = []
    mergetools(ui, mt)
    for t in mt:
        if t.startswith('internal:'):
            continue
        dopts = ui.config('merge-tools', t + '.diffargs', '')
        mopts = ui.config('merge-tools', t + '.diff3args', '')
        dopts, mopts = shlex.split(dopts), shlex.split(mopts)
        tools[t] = [filemerge._findtool(ui, t), dopts, mopts]
    _difftools = tools
    return tools


tortoisehgtoollocations = (
    ('workbench.custom-toolbar', _('Workbench custom toolbar')),
    ('workbench.revdetails.custom-menu', _('Revision details context menu')),
    ('workbench.commit.custom-menu', _('Commit context menu')),
    ('workbench.filelist.custom-menu', _('File context menu (on manifest '
                                         'and revision details)')),
)

def tortoisehgtools(uiorconfig, selectedlocation=None):
    """Parse 'tortoisehg-tools' section of ini file.

    >>> from pprint import pprint
    >>> from mercurial import config
    >>> class memui(ui.ui):
    ...     def readconfig(self, filename, root=None, trust=False,
    ...                    sections=None, remap=None):
    ...         pass  # avoid reading settings from file-system

    Changes:

    >>> hgrctext = '''
    ... [tortoisehg-tools]
    ... update_to_tip.icon = hg-update
    ... update_to_tip.command = hg update tip
    ... update_to_tip.tooltip = Update to tip
    ... '''
    >>> uiobj = memui()
    >>> uiobj._tcfg.parse('<hgrc>', hgrctext)

    into the following dictionary

    >>> tools, toollist = tortoisehgtools(uiobj)
    >>> pprint(tools) #doctest: +NORMALIZE_WHITESPACE
    {'update_to_tip': {'command': 'hg update tip',
                       'icon': 'hg-update',
                       'tooltip': 'Update to tip'}}
    >>> toollist
    ['update_to_tip']

    If selectedlocation is set, only return those tools that have been
    configured to be shown at the given "location".
    Tools are added to "locations" by adding them to one of the
    "extension lists", which are lists of tool names, which follow the same
    format as the workbench.task-toolbar setting, i.e. a list of tool names,
    separated by spaces or "|" to indicate separators.

    >>> hgrctext_full = hgrctext + '''
    ... update_to_null.icon = hg-update
    ... update_to_null.command = hg update null
    ... update_to_null.tooltip = Update to null
    ... explore_wd.command = explorer.exe /e,{ROOT}
    ... explore_wd.enable = iswd
    ... explore_wd.label = Open in explorer
    ... explore_wd.showoutput = True
    ...
    ... [tortoisehg]
    ... workbench.custom-toolbar = update_to_tip | explore_wd
    ... workbench.revdetails.custom-menu = update_to_tip update_to_null
    ... '''
    >>> uiobj = memui()
    >>> uiobj._tcfg.parse('<hgrc>', hgrctext_full)

    >>> tools, toollist = tortoisehgtools(
    ...     uiobj, selectedlocation='workbench.custom-toolbar')
    >>> sorted(tools.keys())
    ['explore_wd', 'update_to_tip']
    >>> toollist
    ['update_to_tip', '|', 'explore_wd']

    >>> tools, toollist = tortoisehgtools(
    ...     uiobj, selectedlocation='workbench.revdetails.custom-menu')
    >>> sorted(tools.keys())
    ['update_to_null', 'update_to_tip']
    >>> toollist
    ['update_to_tip', 'update_to_null']

    Valid "locations lists" are:
        - workbench.custom-toolbar
        - workbench.revdetails.custom-menu

    >>> tortoisehgtools(uiobj, selectedlocation='invalid.location')
    Traceback (most recent call last):
      ...
    ValueError: invalid location 'invalid.location'

    This function can take a ui object or a config object as its input.

    >>> cfg = config.config()
    >>> cfg.parse('<hgrc>', hgrctext)
    >>> tools, toollist = tortoisehgtools(cfg)
    >>> pprint(tools) #doctest: +NORMALIZE_WHITESPACE
    {'update_to_tip': {'command': 'hg update tip',
                       'icon': 'hg-update',
                       'tooltip': 'Update to tip'}}
    >>> toollist
    ['update_to_tip']

    >>> cfg = config.config()
    >>> cfg.parse('<hgrc>', hgrctext_full)
    >>> tools, toollist = tortoisehgtools(
    ...     cfg, selectedlocation='workbench.custom-toolbar')
    >>> sorted(tools.keys())
    ['explore_wd', 'update_to_tip']
    >>> toollist
    ['update_to_tip', '|', 'explore_wd']

    No error for empty config:

    >>> emptycfg = config.config()
    >>> tortoisehgtools(emptycfg)
    ({}, [])
    >>> tortoisehgtools(emptycfg, selectedlocation='workbench.custom-toolbar')
    ({}, [])
    """
    if isinstance(uiorconfig, ui.ui):
        configitems = uiorconfig.configitems
        configlist = uiorconfig.configlist
    else:
        configitems = uiorconfig.items
        def configlist(section, name):
            return uiorconfig.get(section, name, '').split()

    tools = {}
    for key, value in configitems('tortoisehg-tools'):
        toolname, field = key.split('.')
        if toolname not in tools:
            tools[toolname] = {}
        bvalue = util.parsebool(value)
        if bvalue is not None:
            value = bvalue
        tools[toolname][field] = value

    if selectedlocation is None:
        return tools, sorted(tools.keys())

    # Only return the tools that are linked to the selected location
    if selectedlocation not in dict(tortoisehgtoollocations):
        raise ValueError('invalid location %r' % selectedlocation)

    guidef = configlist('tortoisehg', selectedlocation) or []
    toollist = []
    selectedtools = {}
    for name in guidef:
        if name != '|':
            info = tools.get(name, None)
            if info is None:
                continue
            selectedtools[name] = info
        toollist.append(name)
    return selectedtools, toollist

def copydynamicconfig(srcui, destui):
    """Copy config values that come from command line or code

    >>> srcui = ui.ui()
    >>> srcui.setconfig('paths', 'default', 'http://example.org/',
    ...                 '/repo/.hg/hgrc:2')
    >>> srcui.setconfig('patch', 'eol', 'auto', 'eol')
    >>> destui = ui.ui()
    >>> copydynamicconfig(srcui, destui)
    >>> destui.config('paths', 'default') is None
    True
    >>> destui.config('patch', 'eol'), destui.configsource('patch', 'eol')
    ('auto', 'eol')
    """
    for section, name, value in srcui.walkconfig():
        source = srcui.configsource(section, name)
        if ':' in source:
            # path:line
            continue
        if source == 'none':
            # ui.configsource returns 'none' by default
            source = ''
        destui.setconfig(section, name, value, source)

def shortreponame(ui):
    name = ui.config('web', 'name')
    if not name:
        return
    src = ui.configsource('web', 'name')  # path:line
    if '/.hg/hgrc:' not in util.pconvert(src):
        # global web.name will set the same name to all repositories
        ui.debug('ignoring global web.name defined at %s\n' % src)
        return
    return name

def extractchoices(prompttext):
    """Extract prompt message and list of choice (char, label) pairs

    This is slightly different from ui.extractchoices() in that
    a. prompttext may be a unicode
    b. choice label includes &-accessor

    >>> extractchoices("awake? $$ &Yes $$ &No")
    ('awake? ', [('y', '&Yes'), ('n', '&No')])
    >>> extractchoices("line\\nbreak? $$ &Yes $$ &No")
    ('line\\nbreak? ', [('y', '&Yes'), ('n', '&No')])
    >>> extractchoices("want lots of $$money$$?$$Ye&s$$N&o")
    ('want lots of $$money$$?', [('s', 'Ye&s'), ('o', 'N&o')])
    """
    m = re.match(r'(?s)(.+?)\$\$([^\$]*&[^ \$].*)', prompttext)
    msg = m.group(1)
    choices = [p.strip(' ') for p in m.group(2).split('$$')]
    resps = [p[p.index('&') + 1].lower() for p in choices]
    return msg, zip(resps, choices)

def displaytime(date):
    return util.datestr(date, '%Y-%m-%d %H:%M:%S %1%2')

def utctime(date):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(date[0]))

agescales = [
    ((lambda n: ngettext("%d year", "%d years", n)), 3600 * 24 * 365),
    ((lambda n: ngettext("%d month", "%d months", n)), 3600 * 24 * 30),
    ((lambda n: ngettext("%d week", "%d weeks", n)), 3600 * 24 * 7),
    ((lambda n: ngettext("%d day", "%d days", n)), 3600 * 24),
    ((lambda n: ngettext("%d hour", "%d hours", n)), 3600),
    ((lambda n: ngettext("%d minute", "%d minutes", n)), 60),
    ((lambda n: ngettext("%d second", "%d seconds", n)), 1),
    ]

def age(date):
    '''turn a (timestamp, tzoff) tuple into an age string.'''
    # This is i18n-ed version of mercurial.templatefilters.age().

    now = time.time()
    then = date[0]
    if then > now:
        return _('in the future')

    delta = int(now - then)
    if delta == 0:
        return _('now')
    if delta > agescales[0][1] * 2:
        return util.shortdate(date)

    for t, s in agescales:
        n = delta // s
        if n >= 2 or s == 1:
            return t(n) % n

def username(user):
    author = templatefilters.person(user)
    if not author:
        author = util.shortuser(user)
    return author

def user(ctx):
    '''
    Get the username of the change context. Does not abort and just returns
    an empty string if ctx is a working context and no username has been set
    in mercurial's config.
    '''
    try:
        user = ctx.user()
    except error.Abort:
        if ctx._rev is not None:
            raise
        # ctx is a working context and probably no username has
        # been configured in mercurial's config
        user = ''
    return user

def get_revision_desc(fctx, curpath=None):
    """return the revision description as a string"""
    author = tounicode(username(fctx.user()))
    rev = fctx.linkrev()
    # If the source path matches the current path, don't bother including it.
    if curpath and curpath == fctx.path():
        source = u''
    else:
        source = u'(%s)' % tounicode(fctx.path())
    date = age(fctx.date()).decode('utf-8')
    l = tounicode(fctx.description()).splitlines()
    summary = l and l[0] or ''
    return u'%s@%s%s:%s "%s"' % (author, rev, source, date, summary)

def longsummary(description, limit=None):
    summary = tounicode(description)
    lines = summary.splitlines()
    if not lines:
        return ''
    summary = lines[0].strip()
    add_ellipsis = False
    if limit:
        for raw_line in lines[1:]:
            if len(summary) >= limit:
                break
            line = raw_line.strip().replace('\t', ' ')
            if line:
                summary += u'  ' + line
        if len(summary) > limit:
            add_ellipsis = True
            summary = summary[0:limit]
    elif len(lines) > 1:
        add_ellipsis = True
    if add_ellipsis:
        summary += u' \u2026' # ellipsis ...
    return summary

def getDeepestSubrepoContainingFile(wfile, ctx):
    """
    Given a filename and context, get the deepest subrepo that contains the file

    Also return the corresponding subrepo context and the filename relative to
    its containing subrepo
    """
    if wfile in ctx:
        return '', wfile, ctx
    for wsub in ctx.substate:
        if wfile.startswith(wsub):
            srev = ctx.substate[wsub][1]
            stype = ctx.substate[wsub][2]
            if stype != 'hg':
                continue
            if not os.path.exists(ctx._repo.wjoin(wsub)):
                # Maybe the repository does not exist in the working copy?
                continue
            try:
                sctx = ctx.sub(wsub)._repo[srev]
            except:
                # The selected revision does not exist in the working copy
                continue
            wfileinsub =  wfile[len(wsub)+1:]
            if wfileinsub in sctx.substate or wfileinsub in sctx:
                return wsub, wfileinsub, sctx
            else:
                wsubsub, wfileinsub, sctx = \
                    getDeepestSubrepoContainingFile(wfileinsub, sctx)
                if wsubsub is None:
                    return None, wfile, ctx
                else:
                    return os.path.join(wsub, wsubsub), wfileinsub, sctx
    return None, wfile, ctx

def getLineSeparator(line):
    """Get the line separator used on a given line"""
    # By default assume the default OS line separator
    linesep = os.linesep
    lineseptypes = ['\r\n', '\n', '\r']
    for sep in lineseptypes:
        if line.endswith(sep):
            linesep = sep
            break
    return linesep

def parseconfigopts(ui, args):
    """Pop the --config options from the command line and apply them

    >>> u = ui.ui()
    >>> args = ['log', '--config', 'extensions.mq=!']
    >>> parseconfigopts(u, args)
    [('extensions', 'mq', '!')]
    >>> args
    ['log']
    >>> u.config('extensions', 'mq')
    '!'
    """
    config = dispatchmod._earlygetopt(['--config'], args)
    return dispatchmod._parseconfig(ui, config)


# (unicode, QString) -> unicode, otherwise -> str
_stringify = '%s'.__mod__

def escapepath(path):
    r"""Convert path to command-line-safe string; path must be relative to
    the repository root

    >>> from PyQt4.QtCore import QString
    >>> escapepath('foo/[bar].txt')
    'path:foo/[bar].txt'
    >>> escapepath(QString(u'\xc0'))
    u'\xc0'
    """
    p = _stringify(path)
    if '[' in p or '{' in p or '*' in p or '?' in p:
        # bare path is expanded by scmutil.expandpats() on Windows
        return 'path:' + p
    else:
        return p

def escaperev(rev, default=None):
    """Convert revision number to command-line-safe string"""
    if rev is None:
        return default
    if rev == nullrev:
        return 'null'
    assert rev >= 0
    return '%d' % rev

def _escaperevrange(a, b):
    if a == b:
        return escaperev(a)
    else:
        return '%s:%s' % (escaperev(a), escaperev(b))

def compactrevs(revs):
    """Build command-line-safe revspec from list of revision numbers; revs
    should be sorted in ascending order to get compact form

    >>> compactrevs([])
    ''
    >>> compactrevs([0])
    '0'
    >>> compactrevs([0, 1])
    '0:1'
    >>> compactrevs([-1, 0, 1, 3])
    'null:1 + 3'
    >>> compactrevs([0, 4, 5, 6, 8, 9])
    '0 + 4:6 + 8:9'
    """
    if not revs:
        return ''
    specs = []
    k = m = revs[0]
    for n in revs[1:]:
        if m + 1 == n:
            m = n
        else:
            specs.append(_escaperevrange(k, m))
            k = m = n
    specs.append(_escaperevrange(k, m))
    return ' + '.join(specs)

def buildcmdargs(name, *args, **opts):
    r"""Build list of command-line arguments

    >>> buildcmdargs('push', branch='foo')
    ['push', '--branch', 'foo']
    >>> buildcmdargs('graft', r=['0', '1'])
    ['graft', '-r', '0', '-r', '1']
    >>> buildcmdargs('diff', r=[0, None])
    ['diff', '-r', '0']
    >>> buildcmdargs('log', no_merges=True, quiet=False, limit=None)
    ['log', '--no-merges']
    >>> buildcmdargs('commit', user='')
    ['commit', '--user', '']

    positional arguments:

    >>> buildcmdargs('add', 'foo', 'bar')
    ['add', 'foo', 'bar']
    >>> buildcmdargs('cat', '-foo', rev='0')
    ['cat', '--rev', '0', '--', '-foo']
    >>> buildcmdargs('qpush', None)
    ['qpush']
    >>> buildcmdargs('update', '')
    ['update', '']

    type conversion to string:

    >>> from PyQt4.QtCore import QString
    >>> buildcmdargs('email', r=[0, 1])
    ['email', '-r', '0', '-r', '1']
    >>> buildcmdargs('grep', 'foo', rev=2)
    ['grep', '--rev', '2', 'foo']
    >>> buildcmdargs('tag', u'\xc0', message=u'\xc1')
    ['tag', '--message', u'\xc1', u'\xc0']
    >>> buildcmdargs(QString('tag'), QString(u'\xc0'), message=QString(u'\xc1'))
    [u'tag', '--message', u'\xc1', u'\xc0']
    """
    fullargs = [_stringify(name)]
    for k, v in opts.iteritems():
        if v is None:
            continue

        if len(k) == 1:
            aname = '-%s' % k
        else:
            aname = '--%s' % k.replace('_', '-')
        if isinstance(v, bool):
            if v:
                fullargs.append(aname)
        elif isinstance(v, list):
            for e in v:
                if e is None:
                    continue
                fullargs.append(aname)
                fullargs.append(_stringify(e))
        else:
            fullargs.append(aname)
            fullargs.append(_stringify(v))

    args = [_stringify(v) for v in args if v is not None]
    if any(e.startswith('-') for e in args):
        fullargs.append('--')
    fullargs.extend(args)

    return fullargs

_urlpassre = re.compile(r'^([a-zA-Z0-9+.\-]+://[^:@/]*):[^@/]+@')

def _reprcmdarg(arg):
    arg = _urlpassre.sub(r'\1:***@', arg)
    arg = arg.replace('\n', '^M')

    # only for display; no use to construct command string for os.system()
    if not arg or ' ' in arg or '\\' in arg or '"' in arg:
        return '"%s"' % arg.replace('"', '\\"')
    else:
        return arg

def prettifycmdline(cmdline):
    r"""Build pretty command-line string for display

    >>> prettifycmdline(['log', 'foo\\bar', '', 'foo bar', 'foo"bar'])
    'log "foo\\bar" "" "foo bar" "foo\\"bar"'
    >>> prettifycmdline(['log', '--template', '{node}\n'])
    'log --template {node}^M'

    mask password in url-like string:

    >>> prettifycmdline(['push', 'http://foo123:bar456@example.org/'])
    'push http://foo123:***@example.org/'
    >>> prettifycmdline(['clone', 'svn+http://:bar@example.org:8080/trunk/'])
    'clone svn+http://:***@example.org:8080/trunk/'
    """
    return ' '.join(_reprcmdarg(e) for e in cmdline)

def parsecmdline(cmdline, cwd):
    r"""Split command line string to imitate a unix shell

    >>> origfuncs = glob.glob, os.path.expanduser, os.path.expandvars
    >>> glob.glob = lambda p: [p.replace('*', e) for e in ['foo', 'bar', 'baz']]
    >>> os.path.expanduser = lambda p: re.sub(r'^~', '/home/foo', p)
    >>> os.path.expandvars = lambda p: p.replace('$var', 'bar')

    emulates glob/variable expansion rule for simple cases:

    >>> parsecmdline('foo * "qux quux" "*"  "*"', '.')
    [u'foo', u'foo', u'bar', u'baz', u'qux quux', u'*', u'*']
    >>> parsecmdline('foo /*', '.')
    [u'foo', u'/foo', u'/bar', u'/baz']
    >>> parsecmdline('''foo ~/bar '~/bar' "~/bar"''', '.')
    [u'foo', u'/home/foo/bar', u'~/bar', u'~/bar']
    >>> parsecmdline('''foo $var '$var' "$var"''', '.')
    [u'foo', u'bar', u'$var', u'bar']

    but the following cases are unsupported:

    >>> parsecmdline('"foo"*"bar"', '.')  # '*' should be expanded
    [u'foo*bar']
    >>> parsecmdline(r'\*', '.')  # '*' should be a literal
    [u'foo', u'bar', u'baz']

    >>> glob.glob, os.path.expanduser, os.path.expandvars = origfuncs
    """
    _ = _gettext  # TODO: use unicode version globally
    # shlex can't process unicode on Python < 2.7.3
    cmdline = cmdline.encode('utf-8')
    src = cStringIO.StringIO(cmdline)
    lex = shlex.shlex(src, posix=True)
    lex.whitespace_split = True
    lex.commenters = ''
    args = []
    while True:
        # peek first char of next token to guess its type. this isn't perfect
        # but can catch common cases.
        q = cmdline[src.tell():].lstrip(lex.whitespace)[:1]
        try:
            e = lex.get_token()
        except ValueError as err:
            raise ValueError(_('command parse error: %s') % err)
        if e == lex.eof:
            return args
        e = e.decode('utf-8')
        if q not in lex.quotes or q in lex.escapedquotes:
            e = os.path.expandvars(e)  # $var or "$var"
        if q not in lex.quotes:
            e = os.path.expanduser(e)  # ~user
        if q not in lex.quotes and any(c in e for c in '*?[]'):
            expanded = glob.glob(os.path.join(cwd, e))
            if not expanded:
                raise ValueError(_('no matches found: %s') % e)
            if os.path.isabs(e):
                args.extend(expanded)
            else:
                args.extend(p[len(cwd) + 1:] for p in expanded)
        else:
            args.append(e)
