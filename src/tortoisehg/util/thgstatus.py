# thgstatus.py - update TortoiseHg status cache
#
# Copyright 2009 Adrian Buehlmann
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

'''update TortoiseHg status cache'''

from mercurial import hg
from tortoisehg.util import paths, shlib
import os

def cachefilepath(repo):
    return repo.join("thgstatus")

def run(_ui, *pats, **opts):

    if opts.get('all'):
        roots = []
        base = os.getcwd()
        for f in os.listdir(base):
            r = paths.find_root(os.path.join(base, f))
            if r is not None:
                roots.append(r)
        for r in roots:
            _ui.note("%s\n" % r) 
            shlib.update_thgstatus(_ui, r, wait=False)
            shlib.shell_notify([r])
        return

    root = paths.find_root()
    if opts.get('repository'):
        root = opts.get('repository')
    if root is None:
        _ui.status("no repository\n")
        return

    repo = hg.repository(_ui, root)

    if opts.get('remove'):
        try:
            os.remove(cachefilepath(repo))
        except OSError:
            pass
        return

    if opts.get('show'):
        try:
            f = open(cachefilepath(repo), 'rb')
            for e in f:
                _ui.status("%s %s\n" % (e[0], e[1:-1]))
            f.close()
        except IOError:
            _ui.status("*no status*\n")
        return

    wait = opts.get('delay') is not None
    shlib.update_thgstatus(_ui, root, wait=wait)

    if opts.get('notify'):
        shlib.shell_notify(opts.get('notify'))
    _ui.note("thgstatus updated\n") 
