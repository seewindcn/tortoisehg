# version.py - TortoiseHg version
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
from mercurial import ui, hg, commands, error
from tortoisehg.util.i18n import _ as _gettext

# TODO: use unicode version globally
def _(message, context=''):
    return _gettext(message, context).encode('utf-8')

def liveversion():
    'Attempt to read the version from the live repository'
    utilpath = os.path.dirname(os.path.realpath(__file__))
    thgpath = os.path.dirname(os.path.dirname(utilpath))
    if not os.path.isdir(os.path.join(thgpath, '.hg')):
        raise error.RepoError(_('repository %s not found') % thgpath)

    u = ui.ui()
    # prevent loading additional extensions
    for k, _v in u.configitems('extensions'):
        u.setconfig('extensions', k, '!')
    repo = hg.repository(u, path=thgpath)

    u.pushbuffer()
    commands.identify(u, repo, id=True, tags=True, rev='.')
    l = u.popbuffer().split()
    while len(l) > 1 and l[-1][0].isalpha(): # remove non-numbered tags
        l.pop()
    if len(l) > 1: # tag found
        version = l[-1]
        if l[0].endswith('+'): # propagate the dirty status to the tag
            version += '+'
    elif len(l) == 1: # no tag found
        u.pushbuffer()
        commands.parents(u, repo, template='{latesttag}+{latesttagdistance}-')
        version = u.popbuffer().rpartition(':')[2] + l[0]
    return repo[None].branch(), version

def version():
    try:
        branch, version = liveversion()
        return version
    except:
        pass
    try:
        import __version__
        return __version__.version
    except ImportError:
        return _('unknown')

def package_version():
    try:
        branch, version = liveversion()

        extra = None
        if '+' in version:
            version, extra = version.split('+', 1)

        v = [int(x) for x in version.split('.')]
        while len(v) < 3:
            v.append(0)
        major, minor, periodic = v

        if extra != None:
            tagdistance = int(extra.split('-', 1)[0])
            periodic *= 10000
            if branch == 'default':
                periodic += tagdistance + 5000
            else:
                periodic += tagdistance + 1000

        return '.'.join([str(x) for x in (major, minor, periodic)])
    except:
        pass
    return _('unknown')
