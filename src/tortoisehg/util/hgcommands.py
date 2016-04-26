# hgcommands.py - miscellaneous Mercurial commands for TortoiseHg
#
# Copyright 2013, 2014 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os, socket

from mercurial import cmdutil, commands, extensions, sslutil, util

from tortoisehg.util import hgversion
from tortoisehg.util.i18n import agettext as _

cmdtable = {}
_mqcmdtable = {}
command = cmdutil.command(cmdtable)
mqcommand = cmdutil.command(_mqcmdtable)
testedwith = hgversion.testedwith

@command('debuggethostfingerprint',
    [],
    _('[SOURCE]'),
    optionalrepo=True)
def debuggethostfingerprint(ui, repo, source='default'):
    """retrieve a fingerprint of the server certificate

    The server certificate is not verified.
    """
    source = ui.expandpath(source)
    u = util.url(source)
    scheme = (u.scheme or '').split('+')[-1]
    host = u.host
    port = util.getport(u.port or scheme or '-1')
    if scheme != 'https' or not host or not (0 <= port <= 65535):
        raise util.Abort(_('unsupported URL: %s') % source)

    sock = socket.socket()
    try:
        sock.connect((host, port))
        sock = sslutil.wrapsocket(sock, None, None, ui, serverhostname=host)
        peercert = sock.getpeercert(True)
        if not peercert:
            raise util.Abort(_('%s certificate error: no certificate received')
                             % host)
    finally:
        sock.close()

    s = util.sha1(peercert).hexdigest()
    ui.write(':'.join([s[x:x + 2] for x in xrange(0, len(s), 2)]), '\n')

def postinitskel(ui, repo, hooktype, result, pats, **kwargs):
    """create common files in new repository"""
    assert hooktype == 'post-init'
    if result:
        return
    dest = ui.expandpath(pats and pats[0] or '.')
    skel = ui.config('tortoisehg', 'initskel')
    if skel:
        # copy working tree from user-defined path if any
        skel = util.expandpath(skel)
        for name in os.listdir(skel):
            if name == '.hg':
                continue
            util.copyfiles(os.path.join(skel, name),
                           os.path.join(dest, name),
                           hardlink=False)
        return
    # create .hg* files, mainly to workaround Explorer's problem in creating
    # files with a name beginning with a dot
    open(os.path.join(dest, '.hgignore'), 'a').close()

def _applymovemqpatches(q, after, patches):
    fullindexes = dict((q.guard_re.split(rpn, 1)[0], i)
                       for i, rpn in enumerate(q.fullseries))
    fullmap = {}  # patch: line in series file
    for i, n in sorted([(fullindexes[n], n) for n in patches], reverse=True):
        fullmap[n] = q.fullseries.pop(i)
    del fullindexes  # invalid

    if after is None:
        fullat = 0
    else:
        for i, rpn in enumerate(q.fullseries):
            if q.guard_re.split(rpn, 1)[0] == after:
                fullat = i + 1
                break
        else:
            fullat = len(q.fullseries)  # last ditch (should not happen)
    q.fullseries[fullat:fullat] = (fullmap[n] for n in patches)
    q.parseseries()
    q.seriesdirty = True

@mqcommand('qreorder',
    [('', 'after', '', _('move after the specified patch'))],
    _('[--after PATCH] PATCH...'))
def qreorder(ui, repo, *patches, **opts):
    """move patches to the beginning or after the specified patch"""
    after = opts['after'] or None
    q = repo.mq
    if any(n not in q.series for n in patches):
        raise util.Abort(_('unknown patch to move specified'))
    if after in patches:
        raise util.Abort(_('invalid patch position specified'))
    if any(q.isapplied(n) for n in patches):
        raise util.Abort(_('cannot move applied patches'))

    if after is None:
        at = 0
    else:
        try:
            at = q.series.index(after) + 1
        except ValueError:
            raise util.Abort(_('patch %s not in series') % after)
    if at < q.seriesend(True):
        raise util.Abort(_('cannot move into applied patches'))

    wlock = repo.wlock()
    try:
        _applymovemqpatches(q, after, patches)
        q.savedirty()
    finally:
        wlock.release()

def uisetup(ui):
    try:
        extensions.find('mq')
        cmdtable.update(_mqcmdtable)
    except KeyError:
        pass

    # ignore --no-commit on hg<3.7 (ce76c4d2b85c)
    _aliases, entry = cmdutil.findcmd('backout', commands.table)
    if not any(op for op in entry[1] if op[1] == 'no-commit'):
        entry[1].append(('', 'no-commit', None, '(EXPERIMENTAL)'))
