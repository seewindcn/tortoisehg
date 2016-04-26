# run.py - front-end script for TortoiseHg dialogs
#
# Copyright 2008 Steve Borho <steve@borho.org>
# Copyright 2008 TK Soh <teekaysoh@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

shortlicense = '''
Copyright (C) 2008-2016 Steve Borho <steve@borho.org> and others.
This is free software; see the source for copying conditions.  There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
'''

import os
import pdb
import sys
import subprocess

import mercurial.ui as uimod
from mercurial import util, fancyopts, cmdutil, extensions, error, scmutil
from mercurial import pathutil
from mercurial import revset as revsetmod

from tortoisehg.util.i18n import agettext as _
from tortoisehg.util import hglib, paths, i18n
from tortoisehg.util import version as thgversion
from tortoisehg.hgqt import qtapp, qtlib, thgrepo
from tortoisehg.hgqt import cmdui, quickop

try:
    from tortoisehg.util.config import nofork as config_nofork
except ImportError:
    config_nofork = None

console_commands = 'help thgstatus version'
nonrepo_commands = '''userconfig shellconfig clone init debugblockmatcher
debugbugreport about help version thgstatus serve rejects log'''

def dispatch(args, u=None):
    """run the command specified in args"""
    try:
        if u is None:
            u = uimod.ui()
        if '--traceback' in args:
            u.setconfig('ui', 'traceback', 'on')
        if '--debugger' in args:
            pdb.set_trace()
        return _runcatch(u, args)
    except error.ParseError, e:
        qtapp.earlyExceptionMsgBox(e)
    except SystemExit, e:
        return e.code
    except Exception, e:
        if '--debugger' in args:
            pdb.post_mortem(sys.exc_info()[2])
        qtapp.earlyBugReport(e)
        return -1
    except KeyboardInterrupt:
        print _('\nCaught keyboard interrupt, aborting.\n')
        return -1

def portable_fork(ui, opts):
    if 'THG_GUI_SPAWN' in os.environ or (
        not opts.get('fork') and opts.get('nofork')):
        os.environ['THG_GUI_SPAWN'] = '1'
        return
    elif 'THG_OSX_APP' in os.environ:
        # guifork seems to break Mac app bundles
        return
    elif ui.configbool('tortoisehg', 'guifork', None) is not None:
        if not ui.configbool('tortoisehg', 'guifork'):
            return
    elif config_nofork:
        return
    os.environ['THG_GUI_SPAWN'] = '1'
    try:
        _forkbg()
    except OSError, inst:
        ui.warn(_('failed to fork GUI process: %s\n') % inst.strerror)

# native window API can't be used after fork() on Mac OS X
if os.name == 'posix' and sys.platform != 'darwin':
    def _forkbg():
        pid = os.fork()
        if pid > 0:
            sys.exit(0)

else:
    _origwdir = os.getcwd()

    def _forkbg():
        # Spawn background process and exit
        cmdline = list(paths.get_thg_command())
        cmdline.extend(sys.argv[1:])
        os.chdir(_origwdir)
        subprocess.Popen(cmdline, creationflags=qtlib.openflags)
        sys.exit(0)

# Windows and Nautilus shellext execute
# "thg subcmd --listfile TMPFILE" or "thg subcmd --listfileutf8 TMPFILE"(planning) .
# Extensions written in .hg/hgrc is enabled after calling
# extensions.loadall(lui)
#
# 1. win32mbcs extension
#     Japanese shift_jis and Chinese big5 include '0x5c'(backslash) in filename.
#     Mercurial resolves this problem with win32mbcs extension.
#     So, thg must parse path after loading win32mbcs extension.
#
# 2. fixutf8 extension
#     fixutf8 extension requires paths encoding utf-8.
#     So, thg need to convert to utf-8.
#

_lines     = []
_linesutf8 = []

def get_lines_from_listfile(filename, isutf8):
    global _lines
    global _linesutf8
    try:
        if filename == '-':
            lines = [ x.replace("\n", "") for x in sys.stdin.readlines() ]
        else:
            fd = open(filename, "r")
            lines = [ x.replace("\n", "") for x in fd.readlines() ]
            fd.close()
            os.unlink(filename)
        if isutf8:
            _linesutf8 = lines
        else:
            _lines = lines
    except IOError:
        sys.stderr.write(_('can not read file "%s". Ignored.\n') % filename)

def get_files_from_listfile():
    global _lines
    global _linesutf8
    lines = []
    need_to_utf8 = False
    if os.name == 'nt':
        try:
            fixutf8 = extensions.find("fixutf8")
            if fixutf8:
                need_to_utf8 = True
        except KeyError:
            pass

    if need_to_utf8:
        lines += _linesutf8
        for l in _lines:
            lines.append(hglib.toutf(l))
    else:
        lines += _lines
        for l in _linesutf8:
            lines.append(hglib.fromutf(l))

    # Convert absolute file paths to repo/cwd canonical
    cwd = os.getcwd()
    root = paths.find_root(cwd)
    if not root:
        return lines
    if cwd == root:
        cwd_rel = ''
    else:
        cwd_rel = cwd[len(root+os.sep):] + os.sep
    files = []
    for f in lines:
        try:
            cpath = pathutil.canonpath(root, cwd, f)
            # canonpath will abort on .hg/ paths
        except util.Abort:
            continue
        if cpath.startswith(cwd_rel):
            cpath = cpath[len(cwd_rel):]
            files.append(cpath)
        else:
            files.append(f)
    return files

def _parse(ui, args):
    options = {}
    cmdoptions = {}

    try:
        args = fancyopts.fancyopts(args, globalopts, options)
    except fancyopts.getopt.GetoptError, inst:
        raise error.CommandError(None, inst)

    if args:
        alias, args = args[0], args[1:]
    elif options['help']:
        help_(ui, None)
        sys.exit()
    else:
        alias, args = 'workbench', []
    aliases, i = cmdutil.findcmd(alias, table, ui.config("ui", "strict"))
    for a in aliases:
        if a.startswith(alias):
            alias = a
            break
    cmd = aliases[0]
    c = list(i[1])

    # combine global options into local
    for o in globalopts:
        c.append((o[0], o[1], options[o[1]], o[3]))

    try:
        args = fancyopts.fancyopts(args, c, cmdoptions, True)
    except fancyopts.getopt.GetoptError, inst:
        raise error.CommandError(cmd, inst)

    # separate global options back out
    for o in globalopts:
        n = o[1]
        options[n] = cmdoptions[n]
        del cmdoptions[n]

    listfile = options.get('listfile')
    if listfile:
        del options['listfile']
        get_lines_from_listfile(listfile, False)
    listfileutf8 = options.get('listfileutf8')
    if listfileutf8:
        del options['listfileutf8']
        get_lines_from_listfile(listfileutf8, True)

    return (cmd, cmd and i[0] or None, args, options, cmdoptions, alias)

def _runcatch(ui, args):
    try:
        # read --config before doing anything else like Mercurial
        hglib.parseconfigopts(ui, args)
        try:
            return runcommand(ui, args)
        finally:
            ui.flush()
    except error.AmbiguousCommand, inst:
        ui.warn(_("thg: command '%s' is ambiguous:\n    %s\n") %
                (inst.args[0], " ".join(inst.args[1])))
    except error.UnknownCommand, inst:
        ui.warn(_("thg: unknown command '%s'\n") % inst.args[0])
        help_(ui, 'shortlist')
    except error.CommandError, inst:
        if inst.args[0]:
            ui.warn(_("thg %s: %s\n") % (inst.args[0], inst.args[1]))
            help_(ui, inst.args[0])
        else:
            ui.warn(_("thg: %s\n") % inst.args[1])
            help_(ui, 'shortlist')
    except error.RepoError, inst:
        ui.warn(_("abort: %s!\n") % inst)
    except util.Abort, inst:
        ui.warn(_("abort: %s\n") % inst)
        if inst.hint:
            ui.warn(_("(%s)\n") % inst.hint)

    return -1

def runcommand(ui, args):
    cmd, func, args, options, cmdoptions, alias = _parse(ui, args)

    if options['config']:
        raise util.Abort(_('option --config may not be abbreviated!'))

    cmdoptions['alias'] = alias
    ui.setconfig("ui", "verbose", str(bool(options["verbose"])))
    ui.setconfig('ui', 'debug',
                 str(bool(options['debug'] or 'THGDEBUG' in os.environ)))
    i18n.setlanguage(ui.config('tortoisehg', 'ui.language'))

    if options['help']:
        return help_(ui, cmd)

    path = options['repository']
    if path:
        if path.startswith('bundle:'):
            s = path[7:].split('+', 1)
            if len(s) == 1:
                path, bundle = os.getcwd(), s[0]
            else:
                path, bundle = s
            cmdoptions['bundle'] = os.path.abspath(bundle)
        path = ui.expandpath(path)
        # TODO: replace by abspath() if chdir() isn't necessary
        try:
            os.chdir(path)
            path = os.getcwd()
        except OSError:
            pass
    if options['profile']:
        options['nofork'] = True
    path = paths.find_root(path)
    if path:
        try:
            lui = ui.copy()
            lui.readconfig(os.path.join(path, ".hg", "hgrc"))
        except IOError:
            pass
    else:
        lui = ui

    hglib.wrapextensionsloader()  # enable blacklist of extensions
    extensions.loadall(lui)

    args += get_files_from_listfile()

    if options['quiet']:
        ui.quiet = True

    # repository existence will be tested in qtrun()
    if cmd not in nonrepo_commands.split():
        cmdoptions['repository'] = path or options['repository'] or '.'

    cmdoptions['mainapp'] = True
    checkedfunc = util.checksignature(func)
    if cmd in console_commands.split():
        d = lambda: checkedfunc(ui, *args, **cmdoptions)
    else:
        portable_fork(ui, options)
        d = lambda: qtrun(checkedfunc, ui, *args, **cmdoptions)
    return _runcommand(lui, options, cmd, d)

def _runcommand(ui, options, cmd, cmdfunc):
    def checkargs():
        try:
            return cmdfunc()
        except error.SignatureError:
            raise error.CommandError(cmd, _("invalid arguments"))

    if options['profile']:
        format = ui.config('profiling', 'format', default='text')

        if not format in ['text', 'kcachegrind']:
            ui.warn(_("unrecognized profiling format '%s'"
                        " - Ignored\n") % format)
            format = 'text'

        output = ui.config('profiling', 'output')

        if output:
            path = ui.expandpath(output)
            ostream = open(path, 'wb')
        else:
            ostream = sys.stderr

        try:
            from mercurial import lsprof
        except ImportError:
            raise util.Abort(_(
                'lsprof not available - install from '
                'http://codespeak.net/svn/user/arigo/hack/misc/lsprof/'))
        p = lsprof.Profiler()
        p.enable(subcalls=True)
        try:
            return checkargs()
        finally:
            p.disable()

            if format == 'kcachegrind':
                import lsprofcalltree
                calltree = lsprofcalltree.KCacheGrind(p)
                calltree.output(ostream)
            else:
                # format == 'text'
                stats = lsprof.Stats(p.getstats())
                stats.sort()
                stats.pprint(top=10, file=ostream, climit=5)

            if output:
                ostream.close()
    else:
        return checkargs()

qtrun = qtapp.QtRunner()

table = {}
command = cmdutil.command(table)

# common command options

globalopts = [
    ('R', 'repository', '',
     _('repository root directory or symbolic path name')),
    ('v', 'verbose', None, _('enable additional output')),
    ('q', 'quiet', None, _('suppress output')),
    ('h', 'help', None, _('display help and exit')),
    ('', 'config', [],
     _("set/override config option (use 'section.name=value')")),
    ('', 'debug', None, _('enable debugging output')),
    ('', 'debugger', None, _('start debugger')),
    ('', 'profile', None, _('print command execution profile')),
    ('', 'nofork', None, _('do not fork GUI process')),
    ('', 'fork', None, _('always fork GUI process')),
    ('', 'listfile', '', _('read file list from file')),
    ('', 'listfileutf8', '', _('read file list from file encoding utf-8')),
]

# common command functions

def _formatfilerevset(pats):
    q = ["file('path:%s')" % f for f in hglib.canonpaths(pats)]
    return ' or '.join(q)

def _workbench(ui, *pats, **opts):
    root = opts.get('root') or paths.find_root()

    # TODO: unclear that _workbench() is called inside qtrun(). maybe this
    # function should receive factory object instead of using global qtrun.
    w = qtrun.createWorkbench()
    if root:
        root = hglib.tounicode(root)
        bundle = opts.get('bundle')
        if bundle:
            w.openRepo(root, False, bundle=hglib.tounicode(bundle))
        else:
            w.showRepo(root)
        rev = opts.get('rev')
        if rev:
            w.goto(hglib.fromunicode(root), rev)

        q = opts.get('query') or _formatfilerevset(pats)
        if q:
            w.setRevsetFilter(root, hglib.tounicode(q))
    if not w.currentRepoRootPath():
        w.reporegistry.setVisible(True)
    return w

# commands start here, listed alphabetically

@command('about', [], _('thg about'))
def about(ui, *pats, **opts):
    """about dialog"""
    from tortoisehg.hgqt import about as aboutmod
    return aboutmod.AboutDialog()

@command('add', [], _('thg add [FILE]...'))
def add(ui, repoagent, *pats, **opts):
    """add files"""
    return quickop.run(ui, repoagent, *pats, **opts)

@command('^annotate|blame',
    [('r', 'rev', '', _('revision to annotate')),
     ('n', 'line', '', _('open to line')),
     ('p', 'pattern', '', _('initial search pattern'))],
    _('thg annotate'))
def annotate(ui, repoagent, *pats, **opts):
    """annotate dialog"""
    from tortoisehg.hgqt import fileview
    dlg = filelog(ui, repoagent, *pats, **opts)
    dlg.setFileViewMode(fileview.AnnMode)
    if opts.get('line'):
        try:
            lineno = int(opts['line'])
        except ValueError:
            raise util.Abort(_('invalid line number: %s') % opts['line'])
        dlg.showLine(lineno)
    if opts.get('pattern'):
        dlg.setSearchPattern(hglib.tounicode(opts['pattern']))
    return dlg

@command('archive',
    [('r', 'rev', '', _('revision to archive'))],
    _('thg archive'))
def archive(ui, repoagent, *pats, **opts):
    """archive dialog"""
    from tortoisehg.hgqt import archive as archivemod
    rev = opts.get('rev')
    return archivemod.createArchiveDialog(repoagent, rev)

@command('^backout',
    [('', 'merge', None, _('merge with old dirstate parent after backout')),
     ('', 'parent', '', _('parent to choose when backing out merge')),
     ('r', 'rev', '', _('revision to backout'))],
    _('thg backout [OPTION]... [[-r] REV]'))
def backout(ui, repoagent, *pats, **opts):
    """backout tool"""
    from tortoisehg.hgqt import backout as backoutmod
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    else:
        rev = 'tip'
    repo = repoagent.rawRepo()
    rev = scmutil.revsingle(repo, rev).rev()
    msg = backoutmod.checkrev(repo, rev)
    if msg:
        raise util.Abort(hglib.fromunicode(msg))
    return backoutmod.BackoutDialog(repoagent, rev)

@command('^bisect', [], _('thg bisect'))
def bisect(ui, repoagent, *pats, **opts):
    """bisect dialog"""
    from tortoisehg.hgqt import bisect as bisectmod
    return bisectmod.BisectDialog(repoagent)

@command('bookmarks|bookmark',
    [('r', 'rev', '', _('revision'))],
    _('thg bookmarks [-r REV] [NAME]'))
def bookmark(ui, repoagent, *names, **opts):
    """add or remove a movable marker"""
    from tortoisehg.hgqt import bookmark as bookmarkmod
    repo = repoagent.rawRepo()
    rev = scmutil.revsingle(repo, opts.get('rev')).rev()
    if len(names) > 1:
        raise util.Abort(_('only one new bookmark name allowed'))
    dlg = bookmarkmod.BookmarkDialog(repoagent, rev)
    if names:
        dlg.setBookmarkName(hglib.tounicode(names[0]))
    return dlg

@command('^clone',
    [('U', 'noupdate', None, _('the clone will include an empty working copy '
                               '(only a repository)')),
     ('u', 'updaterev', '', _('revision, tag or branch to check out')),
     ('r', 'rev', '', _('include the specified changeset')),
     ('b', 'branch', [], _('clone only the specified branch')),
     ('', 'pull', None, _('use pull protocol to copy metadata')),
     ('', 'uncompressed', None, _('use uncompressed transfer '
                                  '(fast over LAN)'))],
    _('thg clone [OPTION]... [SOURCE] [DEST]'))
def clone(ui, *pats, **opts):
    """clone tool"""
    from tortoisehg.hgqt import clone as clonemod
    dlg = clonemod.CloneDialog(ui, pats, opts)
    dlg.clonedRepository.connect(qtrun.openRepoInWorkbench)
    return dlg

@command('^commit|ci',
    [('u', 'user', '', _('record user as committer')),
     ('d', 'date', '', _('record datecode as commit date'))],
    _('thg commit [OPTIONS] [FILE]...'))
def commit(ui, repoagent, *pats, **opts):
    """commit tool"""
    from tortoisehg.hgqt import commit as commitmod
    repo = repoagent.rawRepo()
    pats = hglib.canonpaths(pats)
    os.chdir(repo.root)
    return commitmod.CommitDialog(repoagent, pats, opts)

@command('debugblockmatcher', [], _('thg debugblockmatcher'))
def debugblockmatcher(ui, *pats, **opts):
    """show blockmatcher widget"""
    from tortoisehg.hgqt import blockmatcher
    return blockmatcher.createTestWidget(ui)

@command('debugbugreport', [], _('thg debugbugreport [TEXT]'))
def debugbugreport(ui, *pats, **opts):
    """open bugreport dialog by exception"""
    raise Exception(' '.join(pats))

@command('debugconsole', [], _('thg debugconsole'))
def debugconsole(ui, repoagent, *pats, **opts):
    """open console window"""
    from tortoisehg.hgqt import docklog
    dlg = docklog.ConsoleWidget(repoagent)
    dlg.closeRequested.connect(dlg.close)
    dlg.resize(700, 400)
    return dlg

@command('debuglighthg', [], _('thg debuglighthg'))
def debuglighthg(ui, repoagent, *pats, **opts):
    from tortoisehg.hgqt import repowidget
    return repowidget.LightRepoWindow(repoagent)

@command('debugruncommand', [],
    _('thg debugruncommand -- COMMAND [ARGUMENT]...'))
def debugruncommand(ui, repoagent, *cmdline, **opts):
    """run hg command in dialog"""
    if not cmdline:
        raise util.Abort(_('no command specified'))
    dlg = cmdui.CmdSessionDialog()
    dlg.setLogVisible(ui.verbose)
    sess = repoagent.runCommand(map(hglib.tounicode, cmdline), dlg)
    dlg.setSession(sess)
    return dlg

@command('drag_copy', [], _('thg drag_copy SOURCE... DEST'))
def drag_copy(ui, repoagent, *pats, **opts):
    """copy the selected files to the desired directory"""
    opts.update(alias='copy', headless=True)
    return quickop.run(ui, repoagent, *pats, **opts)

@command('drag_move', [], _('thg drag_move SOURCE... DEST'))
def drag_move(ui, repoagent, *pats, **opts):
    """move the selected files to the desired directory"""
    opts.update(alias='move', headless=True)
    return quickop.run(ui, repoagent, *pats, **opts)

@command('^email',
    [('r', 'rev', [], _('a revision to send'))],
    _('thg email [REVS]'))
def email(ui, repoagent, *revs, **opts):
    """send changesets by email"""
    from tortoisehg.hgqt import hgemail
    # TODO: same options as patchbomb
    if opts.get('rev'):
        if revs:
            raise util.Abort(_('use only one form to specify the revision'))
        revs = opts.get('rev')

    repo = repoagent.rawRepo()
    revs = scmutil.revrange(repo, revs)
    return hgemail.EmailDialog(repoagent, revs)

@command('^filelog',
    [('r', 'rev', '', _('select the specified revision')),
     ('', 'compare', False, _('side-by-side comparison of revisions'))],
    _('thg filelog [OPTION]... FILE'))
def filelog(ui, repoagent, *pats, **opts):
    """show history of the specified file"""
    from tortoisehg.hgqt import filedialogs
    if len(pats) != 1:
        raise util.Abort(_('requires a single filename'))
    repo = repoagent.rawRepo()
    rev = scmutil.revsingle(repo, opts.get('rev')).rev()
    filename = hglib.canonpaths(pats)[0]
    if opts.get('compare'):
        dlg = filedialogs.FileDiffDialog(repoagent, filename)
    else:
        dlg = filedialogs.FileLogDialog(repoagent, filename)
    dlg.goto(rev)
    return dlg

@command('forget', [], _('thg forget [FILE]...'))
def forget(ui, repoagent, *pats, **opts):
    """forget selected files"""
    return quickop.run(ui, repoagent, *pats, **opts)

@command('graft',
    [('r', 'rev', [], _('revisions to graft'))],
    _('thg graft [-r] REV...'))
def graft(ui, repoagent, *revs, **opts):
    """graft dialog"""
    from tortoisehg.hgqt import graft as graftmod
    repo = repoagent.rawRepo()
    revs = list(revs)
    revs.extend(opts['rev'])
    if not os.path.exists(repo.join('graftstate')) and not revs:
        raise util.Abort(_('You must provide revisions to graft'))
    return graftmod.GraftDialog(repoagent, None, source=revs)

@command('^grep|search',
    [('i', 'ignorecase', False, _('ignore case during search'))],
    _('thg grep'))
def grep(ui, repoagent, *pats, **opts):
    """grep/search dialog"""
    from tortoisehg.hgqt import grep as grepmod
    upats = [hglib.tounicode(p) for p in pats]
    return grepmod.SearchDialog(repoagent, upats, **opts)

@command('^guess', [], _('thg guess'))
def guess(ui, repoagent, *pats, **opts):
    """guess previous renames or copies"""
    from tortoisehg.hgqt import guess as guessmod
    return guessmod.DetectRenameDialog(repoagent, None, *pats)

### help management, adapted from mercurial.commands.help_()
@command('help', [], _('thg help [COMMAND]'))
def help_(ui, name=None, with_version=False, **opts):
    """show help for a command, extension, or list of commands

    With no arguments, print a list of commands and short help.

    Given a command name, print help for that command.

    Given an extension name, print help for that extension, and the
    commands it provides."""
    option_lists = []
    textwidth = ui.termwidth() - 2

    def addglobalopts(aliases):
        if ui.verbose:
            option_lists.append((_("global options:"), globalopts))
            if name == 'shortlist':
                option_lists.append((_('use "thg help" for the full list '
                                       'of commands'), ()))
        else:
            if name == 'shortlist':
                msg = _('use "thg help" for the full list of commands '
                        'or "thg -v" for details')
            elif aliases:
                msg = _('use "thg -v help%s" to show aliases and '
                        'global options') % (name and " " + name or "")
            else:
                msg = _('use "thg -v help %s" to show global options') % name
            option_lists.append((msg, ()))

    def helpcmd(name):
        if with_version:
            version(ui)
            ui.write('\n')

        try:
            aliases, i = cmdutil.findcmd(name, table, False)
        except error.AmbiguousCommand, inst:
            select = lambda c: c.lstrip('^').startswith(inst.args[0])
            helplist(_('list of commands:\n\n'), select)
            return

        # synopsis
        ui.write("%s\n" % i[2])

        # aliases
        if not ui.quiet and len(aliases) > 1:
            ui.write(_("\naliases: %s\n") % ', '.join(aliases[1:]))

        # description
        doc = i[0].__doc__
        if not doc:
            doc = _("(no help text available)")
        if ui.quiet:
            doc = doc.splitlines(0)[0]
        ui.write("\n%s\n" % doc.rstrip())

        if not ui.quiet:
            # options
            if i[1]:
                option_lists.append((_("options:\n"), i[1]))

            addglobalopts(False)

    def helplist(header, select=None):
        h = {}
        cmds = {}
        for c, e in table.iteritems():
            f = c.split("|", 1)[0]
            if select and not select(f):
                continue
            if (not select and name != 'shortlist' and
                e[0].__module__ != __name__):
                continue
            if name == "shortlist" and not f.startswith("^"):
                continue
            f = f.lstrip("^")
            if not ui.debugflag and f.startswith("debug"):
                continue
            doc = e[0].__doc__
            if doc and 'DEPRECATED' in doc and not ui.verbose:
                continue
            #doc = gettext(doc)
            if not doc:
                doc = _("(no help text available)")
            h[f] = doc.splitlines()[0].rstrip()
            cmds[f] = c.lstrip("^")

        if not h:
            ui.status(_('no commands defined\n'))
            return

        ui.status(header)
        fns = sorted(h)
        m = max(map(len, fns))
        for f in fns:
            if ui.verbose:
                commands = cmds[f].replace("|",", ")
                ui.write(" %s:\n      %s\n"%(commands, h[f]))
            else:
                ui.write('%s\n' % (util.wrap(h[f], textwidth,
                                             initindent=' %-*s   ' % (m, f),
                                             hangindent=' ' * (m + 4))))

        if not ui.quiet:
            addglobalopts(True)

    def helptopic(name):
        from mercurial import help
        for names, header, doc in help.helptable:
            if name in names:
                break
        else:
            raise error.UnknownCommand(name)

        # description
        if not doc:
            doc = _("(no help text available)")
        if hasattr(doc, '__call__'):
            doc = doc()

        ui.write("%s\n" % header)
        ui.write("%s\n" % doc.rstrip())

    if name and name != 'shortlist':
        i = None
        for f in (helpcmd, helptopic):
            try:
                f(name)
                i = None
                break
            except error.UnknownCommand, inst:
                i = inst
        if i:
            raise i

    else:
        # program name
        if ui.verbose or with_version:
            version(ui)
        else:
            ui.status(_("Thg - TortoiseHg's GUI tools for Mercurial SCM (Hg)\n"))
        ui.status('\n')

        # list of commands
        if name == "shortlist":
            header = _('basic commands:\n\n')
        else:
            header = _('list of commands:\n\n')

        helplist(header)

    # list all option lists
    opt_output = []
    for title, options in option_lists:
        opt_output.append(("\n%s" % title, None))
        for shortopt, longopt, default, desc in options:
            if "DEPRECATED" in desc and not ui.verbose: continue
            opt_output.append(("%2s%s" % (shortopt and "-%s" % shortopt,
                                          longopt and " --%s" % longopt),
                               "%s%s" % (desc,
                                         default
                                         and _(" (default: %s)") % default
                                         or "")))

    if opt_output:
        opts_len = max([len(line[0]) for line in opt_output if line[1]] or [0])
        for first, second in opt_output:
            if second:
                initindent = ' %-*s  ' % (opts_len, first)
                hangindent = ' ' * (opts_len + 3)
                ui.write('%s\n' % (util.wrap(second, textwidth,
                                             initindent=initindent,
                                             hangindent=hangindent)))
            else:
                ui.write("%s\n" % first)

@command('^hgignore|ignore|filter', [], _('thg hgignore [FILE]'))
def hgignore(ui, repoagent, *pats, **opts):
    """ignore filter editor"""
    from tortoisehg.hgqt import hgignore as hgignoremod
    if pats and pats[0].endswith('.hgignore'):
        pats = []
    return hgignoremod.HgignoreDialog(repoagent, None, *pats)

@command('import',
    [('', 'mq', False, _('import to the patch queue (MQ)'))],
    _('thg import [OPTION] [SOURCE]...'))
def import_(ui, repoagent, *pats, **opts):
    """import an ordered set of patches"""
    from tortoisehg.hgqt import thgimport
    dlg = thgimport.ImportDialog(repoagent, None, **opts)
    dlg.setfilepaths(pats)
    return dlg

@command('^init', [], _('thg init [DEST]'))
def init(ui, dest='.', **opts):
    """init dialog"""
    from tortoisehg.hgqt import hginit
    dlg = hginit.InitDialog(ui, hglib.tounicode(dest))
    dlg.newRepository.connect(qtrun.openRepoInWorkbench)
    return dlg

@command('^lock|unlock', [], _('thg lock'))
def lock(ui, repoagent, **opts):
    """lock dialog"""
    from tortoisehg.hgqt import locktool
    return locktool.LockDialog(repoagent)

@command('^log|history|explorer|workbench',
    [('k', 'query', '', _('search for a given text or revset')),
     ('r', 'rev', '', _('select the specified revision')),
     ('l', 'limit', '', _('(DEPRECATED)')),
     ('', 'newworkbench', None, _('open a new workbench window'))],
    _('thg log [OPTIONS] [FILE]'))
def log(ui, *pats, **opts):
    """workbench application"""
    if opts.get('query') and pats:
        # 'filelog' does not support -k, and multiple filenames are packed
        # into revset query that may conflict with user-supplied one.
        raise util.Abort(_('cannot specify both -k/--query and filenames'))

    root = opts.get('root') or paths.find_root()
    if root and len(pats) == 1 and os.path.isfile(pats[0]):
        # TODO: do not instantiate repo here
        repo = thgrepo.repository(ui, root)
        repoagent = repo._pyqtobj
        return filelog(ui, repoagent, *pats, **opts)

    # Before starting the workbench, we must check if we must try to reuse an
    # existing workbench window (we don't by default)
    # Note that if the "single workbench mode" is enabled, and there is no
    # existing workbench window, we must tell the Workbench object to create
    # the workbench server
    singleworkbenchmode = ui.configbool('tortoisehg', 'workbench.single', True)
    mustcreateserver = False
    if singleworkbenchmode:
        newworkbench = opts.get('newworkbench')
        if root and not newworkbench:
            # TODO: send -rREV to server
            q = opts.get('query') or _formatfilerevset(pats)
            if qtapp.connectToExistingWorkbench(root, q):
                # The were able to connect to an existing workbench server, and
                # it confirmed that it has opened the selected repo for us
                sys.exit(0)
            # there is no pre-existing workbench server
            serverexists = False
        else:
            serverexists = qtapp.connectToExistingWorkbench('[echo]')
        # When in " single workbench mode", we must create a server if there
        # is not one already
        mustcreateserver = not serverexists

    w = _workbench(ui, *pats, **opts)
    if mustcreateserver:
        qtrun.createWorkbenchServer()
    return w

@command('manifest',
    [('r', 'rev', '', _('revision to display')),
     ('n', 'line', '', _('open to line')),
     ('p', 'pattern', '', _('initial search pattern'))],
    _('thg manifest [-r REV] [FILE]'))
def manifest(ui, repoagent, *pats, **opts):
    """display the current or given revision of the project manifest"""
    from tortoisehg.hgqt import revdetails as revdetailsmod
    repo = repoagent.rawRepo()
    rev = scmutil.revsingle(repo, opts.get('rev')).rev()
    dlg = revdetailsmod.createManifestDialog(repoagent, rev)
    if pats:
        path = hglib.canonpaths(pats)[0]
        dlg.setFilePath(hglib.tounicode(path))
        if opts.get('line'):
            try:
                lineno = int(opts['line'])
            except ValueError:
                raise util.Abort(_('invalid line number: %s') % opts['line'])
            dlg.showLine(lineno)
    if opts.get('pattern'):
        dlg.setSearchPattern(hglib.tounicode(opts['pattern']))
    return dlg

@command('^merge',
    [('r', 'rev', '', _('revision to merge'))],
    _('thg merge [[-r] REV]'))
def merge(ui, repoagent, *pats, **opts):
    """merge wizard"""
    from tortoisehg.hgqt import merge as mergemod
    rev = opts.get('rev') or None
    if not rev and len(pats):
        rev = pats[0]
    if not rev:
        raise util.Abort(_('Merge revision not specified or not found'))
    repo = repoagent.rawRepo()
    rev = scmutil.revsingle(repo, rev).rev()
    return mergemod.MergeDialog(repoagent, rev)

@command('postreview',
    [('r', 'rev', [], _('a revision to post'))],
    _('thg postreview [-r] REV...'))
def postreview(ui, repoagent, *pats, **opts):
    """post changesets to reviewboard"""
    from tortoisehg.hgqt import postreview as postreviewmod
    repo = repoagent.rawRepo()
    revs = opts.get('rev') or None
    if not revs and len(pats):
        revs = pats[0]
    if not revs:
        raise util.Abort(_('no revisions specified'))
    return postreviewmod.PostReviewDialog(repo.ui, repoagent, revs)

@command('^prune|obsolete|kill',
    [('r', 'rev', [], _('revisions to prune'))],
    _('thg prune [-r] REV...'))
def prune(ui, repoagent, *revs, **opts):
    """hide changesets by marking them obsolete"""
    from tortoisehg.hgqt import prune as prunemod
    revs = list(revs)
    revs.extend(opts.get('rev'))
    if len(revs) < 2:
        revspec = ''.join(revs)
    else:
        revspec = revsetmod.formatspec('%lr', revs)
    return prunemod.createPruneDialog(repoagent, hglib.tounicode(revspec))

@command('^purge', [], _('thg purge'))
def purge(ui, repoagent, *pats, **opts):
    """purge unknown and/or ignore files from repository"""
    from tortoisehg.hgqt import purge as purgemod
    return purgemod.PurgeDialog(repoagent)

@command('^rebase',
    [('', 'keep', False, _('keep original changesets')),
     ('', 'keepbranches', False, _('keep original branch names')),
     ('', 'detach', False, _('(DEPRECATED)')),
     ('s', 'source', '', _('rebase from the specified changeset')),
     ('d', 'dest', '', _('rebase onto the specified changeset'))],
    _('thg rebase -s REV -d REV [--keep]'))
def rebase(ui, repoagent, *pats, **opts):
    """rebase dialog"""
    from tortoisehg.hgqt import rebase as rebasemod
    repo = repoagent.rawRepo()
    if os.path.exists(repo.join('rebasestate')):
        # TODO: move info dialog into RebaseDialog if possible
        qtlib.InfoMsgBox(hglib.tounicode(_('Rebase already in progress')),
                         hglib.tounicode(_('Resuming rebase already in '
                                           'progress')))
    elif not opts['source'] or not opts['dest']:
        raise util.Abort(_('You must provide source and dest arguments'))
    return rebasemod.RebaseDialog(repoagent, None, **opts)

@command('rejects', [], _('thg rejects [FILE]'))
def rejects(ui, *pats, **opts):
    """manually resolve rejected patch chunks"""
    from tortoisehg.hgqt import rejects as rejectsmod
    if len(pats) != 1:
        raise util.Abort(_('You must provide the path to a file'))
    path = pats[0]
    if path.endswith('.rej'):
        path = path[:-4]
    return rejectsmod.RejectsDialog(ui, path)

@command('remove|rm', [], _('thg remove [FILE]...'))
def remove(ui, repoagent, *pats, **opts):
    """remove selected files"""
    return quickop.run(ui, repoagent, *pats, **opts)

@command('rename|mv|copy', [], _('thg rename [SOURCE] [DEST]'))
def rename(ui, repoagent, source=None, dest=None, **opts):
    """rename dialog"""
    from tortoisehg.hgqt import rename as renamemod
    repo = repoagent.rawRepo()
    cwd = repo.getcwd()
    if source:
        source = hglib.tounicode(pathutil.canonpath(repo.root, cwd, source))
    if dest:
        dest = hglib.tounicode(pathutil.canonpath(repo.root, cwd, dest))
    iscopy = (opts.get('alias') == 'copy')
    return renamemod.RenameDialog(repoagent, None, source, dest, iscopy)

@command('^repoconfig',
    [('', 'focus', '', _('field to give initial focus'))],
    _('thg repoconfig'))
def repoconfig(ui, repoagent, *pats, **opts):
    """repository configuration editor"""
    from tortoisehg.hgqt import settings
    return settings.SettingsDialog(True, focus=opts.get('focus'))

@command('resolve', [], _('thg resolve'))
def resolve(ui, repoagent, *pats, **opts):
    """resolve dialog"""
    from tortoisehg.hgqt import resolve as resolvemod
    return resolvemod.ResolveDialog(repoagent)

@command('^revdetails',
    [('r', 'rev', '', _('the revision to show'))],
    _('thg revdetails [-r REV]'))
def revdetails(ui, repoagent, *pats, **opts):
    """revision details tool"""
    from tortoisehg.hgqt import revdetails as revdetailsmod
    repo = repoagent.rawRepo()
    os.chdir(repo.root)
    rev = opts.get('rev', '.')
    return revdetailsmod.RevDetailsDialog(repoagent, rev=rev)

@command('revert', [], _('thg revert [FILE]...'))
def revert(ui, repoagent, *pats, **opts):
    """revert selected files"""
    return quickop.run(ui, repoagent, *pats, **opts)

@command('rupdate',
    [('r', 'rev', '', _('revision to update'))],
    _('thg rupdate [[-r] REV]'))
def rupdate(ui, repoagent, *pats, **opts):
    """update a remote repository"""
    from tortoisehg.hgqt import rupdate as rupdatemod
    rev = None
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    return rupdatemod.createRemoteUpdateDialog(repoagent, rev)

@command('^serve',
    [('', 'web-conf', '', _('name of the hgweb config file (serve more than '
                            'one repository)')),
     ('', 'webdir-conf', '', _('name of the hgweb config file (DEPRECATED)'))],
    _('thg serve [--web-conf FILE]'))
def serve(ui, *pats, **opts):
    """start stand-alone webserver"""
    from tortoisehg.hgqt import serve as servemod
    return servemod.run(ui, *pats, **opts)

if os.name == 'nt':
    # TODO: extra detection to determine if shell extension is installed
    @command('shellconfig', [], _('thg shellconfig'))
    def shellconfig(ui, *pats, **opts):
        """explorer extension configuration editor"""
        from tortoisehg.hgqt import shellconf
        return shellconf.ShellConfigWindow()

@command('shelve|unshelve', [], _('thg shelve'))
def shelve(ui, repoagent, *pats, **opts):
    """move changes between working directory and patches"""
    from tortoisehg.hgqt import shelve as shelvemod
    return shelvemod.ShelveDialog(repoagent)

@command('^sign',
    [('f', 'force', None, _('sign even if the sigfile is modified')),
     ('l', 'local', None, _('make the signature local')),
     ('k', 'key', '', _('the key id to sign with')),
     ('', 'no-commit', None, _('do not commit the sigfile after signing')),
     ('m', 'message', '', _('use <text> as commit message'))],
    _('thg sign [-f] [-l] [-k KEY] [-m TEXT] [REV]'))
def sign(ui, repoagent, *pats, **opts):
    """sign tool"""
    from tortoisehg.hgqt import sign as signmod
    repo = repoagent.rawRepo()
    if 'gpg' not in repo.extensions():
        raise util.Abort(_('Please enable the Gpg extension first.'))
    kargs = {}
    rev = len(pats) > 0 and pats[0] or None
    if rev:
        kargs['rev'] = rev
    return signmod.SignDialog(repoagent, opts=opts, **kargs)

@command('^status|st',
    [('c', 'clean', False, _('show files without changes')),
     ('i', 'ignored', False, _('show ignored files'))],
    _('thg status [OPTIONS] [FILE]'))
def status(ui, repoagent, *pats, **opts):
    """browse working copy status"""
    from tortoisehg.hgqt import status as statusmod
    repo = repoagent.rawRepo()
    pats = hglib.canonpaths(pats)
    os.chdir(repo.root)
    return statusmod.StatusDialog(repoagent, pats, opts)

@command('^strip',
    [('f', 'force', None, _('discard uncommitted changes (no backup)')),
     ('n', 'nobackup', None, _('do not back up stripped revisions')),
     ('k', 'keep', None, _('do not modify working copy during strip')),
     ('r', 'rev', '', _('revision to strip'))],
    _('thg strip [-k] [-f] [-n] [[-r] REV]'))
def strip(ui, repoagent, *pats, **opts):
    """strip dialog"""
    from tortoisehg.hgqt import thgstrip
    rev = None
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    return thgstrip.createStripDialog(repoagent, rev=rev, opts=opts)

@command('^sync|synchronize',
    [('B', 'bookmarks', False, _('open the bookmark sync window'))],
    _('thg sync [OPTION]... [PEER]'))
def sync(ui, repoagent, url=None, **opts):
    """synchronize with other repositories"""
    from tortoisehg.hgqt import bookmark as bookmarkmod, repowidget
    url = hglib.tounicode(url)
    if opts.get('bookmarks'):
        return bookmarkmod.SyncBookmarkDialog(repoagent, url)

    repo = repoagent.rawRepo()
    repo.ui.setconfig('tortoisehg', 'defaultwidget', 'sync')
    w = repowidget.LightRepoWindow(repoagent)
    if url:
        w.setSyncUrl(url)
    return w

@command('^tag',
    [('f', 'force', None, _('replace existing tag')),
     ('l', 'local', None, _('make the tag local')),
     ('r', 'rev', '', _('revision to tag')),
     ('', 'remove', None, _('remove a tag')),
     ('m', 'message', '', _('use <text> as commit message'))],
    _('thg tag [-f] [-l] [-m TEXT] [-r REV] [NAME]'))
def tag(ui, repoagent, *pats, **opts):
    """tag tool"""
    from tortoisehg.hgqt import tag as tagmod
    kargs = {}
    tag = len(pats) > 0 and pats[0] or None
    if tag:
        kargs['tag'] = tag
    rev = opts.get('rev')
    if rev:
        kargs['rev'] = rev
    return tagmod.TagDialog(repoagent, opts=opts, **kargs)

@command('thgstatus',
    [('',  'delay', None, _('wait until the second ticks over')),
     ('n', 'notify', [], _('notify the shell for paths given')),
     ('',  'remove', None, _('remove the status cache')),
     ('s', 'show', None, _('show the contents of the status cache '
                           '(no update)')),
     ('',  'all', None, _('update all repos in current dir'))],
    _('thg thgstatus [OPTION]'))
def thgstatus(ui, *pats, **opts):
    """update TortoiseHg status cache"""
    from tortoisehg.util import thgstatus as thgstatusmod
    thgstatusmod.run(ui, *pats, **opts)

@command('^update|checkout|co',
    [('C', 'clean', None, _('discard uncommitted changes (no backup)')),
     ('r', 'rev', '', _('revision to update')),],
    _('thg update [-C] [[-r] REV]'))
def update(ui, repoagent, *pats, **opts):
    """update/checkout tool"""
    from tortoisehg.hgqt import update as updatemod
    rev = None
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    return updatemod.UpdateDialog(repoagent, rev, None, opts)

@command('^userconfig',
    [('', 'focus', '', _('field to give initial focus'))],
    _('thg userconfig'))
def userconfig(ui, *pats, **opts):
    """user configuration editor"""
    from tortoisehg.hgqt import settings
    return settings.SettingsDialog(False, focus=opts.get('focus'))

@command('^vdiff',
    [('c', 'change', '', _('changeset to view in diff tool')),
     ('r', 'rev', [], _('revisions to view in diff tool')),
     ('b', 'bundle', '', _('bundle file to preview'))],
    _('launch visual diff tool'))
def vdiff(ui, repoagent, *pats, **opts):
    """launch configured visual diff tool"""
    from tortoisehg.hgqt import visdiff
    repo = repoagent.rawRepo()
    if opts.get('bundle'):
        repo = thgrepo.repository(ui, opts.get('bundle'))
    pats = hglib.canonpaths(pats)
    return visdiff.visualdiff(ui, repo, pats, opts)

@command('^version',
    [('v', 'verbose', None, _('print license'))],
    _('thg version [OPTION]'))
def version(ui, **opts):
    """output version and copyright information"""
    ui.write(_('TortoiseHg Dialogs (version %s), '
               'Mercurial (version %s)\n') %
               (thgversion.version(), hglib.hgversion))
    if not ui.quiet:
        ui.write(shortlicense)
