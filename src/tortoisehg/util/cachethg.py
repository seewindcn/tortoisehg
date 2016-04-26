# cachethg.py - overlay/status cache
#
# Copyright 2008 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import sys

from mercurial import hg, util, ui, node, error, scmutil
from tortoisehg.util import paths, debugthg, hglib

debugging = False
enabled = True
localonly = False
includepaths = []
excludepaths = []

try:
    from _winreg import HKEY_CURRENT_USER, OpenKey, QueryValueEx
    from win32api import GetTickCount
    CACHE_TIMEOUT = 5000
    try:
        hkey = OpenKey(HKEY_CURRENT_USER, r"Software\TortoiseHg")
        enabled = QueryValueEx(hkey, 'EnableOverlays')[0] in ('1', 'True')
        localonly = QueryValueEx(hkey, 'LocalDisksOnly')[0] in ('1', 'True')
        incs = QueryValueEx(hkey, 'IncludePath')[0]
        excs = QueryValueEx(hkey, 'ExcludePath')[0]
        debugging = QueryValueEx(hkey, 'OverlayDebug')[0] in ('1', 'True')
        for p in incs.split(';'):
            path = p.strip()
            if path:
                includepaths.append(path)
        for p in excs.split(';'):
            path = p.strip()
            if path:
                excludepaths.append(path)
    except EnvironmentError:
        pass
except ImportError:
    from time import time as GetTickCount
    CACHE_TIMEOUT = 5.0
    debugging = debugthg.debug('O')

if debugging:
    debugf = debugthg.debugf
    debugf('Enabled %s', enabled)
    debugf('LocalDisksOnly %s', localonly)
    debugf('IncludePaths %s', includepaths)
    debugf('ExcludePaths %s', excludepaths)
else:
    debugf = debugthg.debugf_No

STATUS_STATES = 'MAR!?IC'
MODIFIED, ADDED, REMOVED, DELETED, UNKNOWN, IGNORED, UNCHANGED = STATUS_STATES
NOT_IN_REPO = ' '
ROOT = "r"
UNRESOLVED = 'U'

# file status cache
overlay_cache = {}
cache_tick_count = 0
cache_root = None
cache_pdir = None


def add_dirs(list):
    dirs = set()
    if list:
        dirs.add('')
    for f in list:
        pdir = os.path.dirname(f)
        if pdir in dirs:
            continue
        while pdir:
            dirs.add(pdir)
            pdir = os.path.dirname(pdir)
    list.extend(dirs)


def get_state(upath, repo=None):
    """
    Get the state of a given path in source control.
    """
    states = get_states(upath, repo)
    return states and states[0] or NOT_IN_REPO


def get_states(upath, repo=None):
    """
    Get the states of a given path in source control.
    """
    global overlay_cache, cache_tick_count
    global cache_root, cache_pdir
    global enabled, localonly
    global includepaths, excludepaths

    #debugf("called: _get_state(%s)", path)
    tc = GetTickCount()

    try:
        # handle some Asian charsets
        path = upath.encode('mbcs')
    except:
        path = upath
     # check if path is cached
    pdir = os.path.dirname(path)
    status = overlay_cache.get(path, '')
    if overlay_cache and (cache_pdir == pdir or cache_pdir and
              status not in ' r' and path.startswith(cache_pdir)):
        #use cached data when pdir has not changed or when the cached state is a repo state
        if tc - cache_tick_count < CACHE_TIMEOUT:
            if not status:
                if os.path.isdir(os.path.join(path, '.hg')):
                    add(path, ROOT)
                    status = ROOT
                else:
                    status = overlay_cache.get(pdir + '*', NOT_IN_REPO)
                    add(path, status)
                debugf("%s: %s (cached~)", (path, status))
            else:
                debugf("%s: %s (cached)", (path, status))
            return status
        else:
            debugf("Timed out!!")
            overlay_cache.clear()
            cache_tick_count = GetTickCount()
     # path is a drive
    if path.endswith(":\\"):
        add(path, NOT_IN_REPO)
        return NOT_IN_REPO
     # open repo
    if cache_pdir == pdir:
        root = cache_root
    else:
        debugf("find new root")
        root = paths.find_root(path)
        if root == path:
            if not overlay_cache:
                cache_root = pdir
            add(path, ROOT)
            debugf("%s: r", path)
            return ROOT
        cache_root = root
        cache_pdir = pdir

    if root is None:
        debugf("_get_state: not in repo")
        overlay_cache = {None: None}
        cache_tick_count = GetTickCount()
        return NOT_IN_REPO
    debugf("_get_state: root = " + root)
    hgdir = os.path.join(root, '.hg', '')
    if pdir == hgdir[:-1] or pdir.startswith(hgdir):
        add(pdir, NOT_IN_REPO)
        return NOT_IN_REPO
    try:
        if not enabled:
            overlay_cache = {None: None}
            cache_tick_count = GetTickCount()
            debugf("overlayicons disabled")
            return NOT_IN_REPO
        if localonly and not paths.is_on_fixed_drive(path):
            debugf("%s: is a network drive", path)
            overlay_cache = {None: None}
            cache_tick_count = GetTickCount()
            return NOT_IN_REPO
        if includepaths:
            for p in includepaths:
                if path.startswith(p):
                    break
            else:
                debugf("%s: is not in an include path", path)
                overlay_cache = {None: None}
                cache_tick_count = GetTickCount()
                return NOT_IN_REPO
        for p in excludepaths:
            if path.startswith(p):
                debugf("%s: is in an exclude path", path)
                overlay_cache = {None: None}
                cache_tick_count = GetTickCount()
                return NOT_IN_REPO
        tc1 = GetTickCount()
        real = os.path.realpath #only test if necessary (symlink in path)
        if not repo or (repo.root != root and repo.root != real(root)):
            repo = hg.repository(ui.ui(), path=root)
            debugf("hg.repository() took %g ticks", (GetTickCount() - tc1))
    except error.RepoError:
        # We aren't in a working tree
        debugf("%s: not in repo", pdir)
        add(pdir + '*', IGNORED)
        return IGNORED
    except Exception, e:
        debugf("error while handling %s:", pdir)
        debugf(e)
        add(pdir + '*', UNKNOWN)
        return UNKNOWN

     # get file status
    tc1 = GetTickCount()

    try:
        matcher = scmutil.match(repo[None], [pdir])
        repostate = repo.status(match=matcher, ignored=True,
                        clean=True, unknown=True)
    except util.Abort, inst:
        debugf("abort: %s", inst)
        debugf("treat as unknown : %s", path)
        return UNKNOWN

    debugf("status() took %g ticks", (GetTickCount() - tc1))
    mergestate = repo.dirstate.parents()[1] != node.nullid

    # cached file info
    tc = GetTickCount()
    overlay_cache = {}
    add(root, ROOT)
    add(os.path.join(root, '.hg'), NOT_IN_REPO)
    states = STATUS_STATES
    if mergestate:
        mstate = hglib.readmergestate(repo)
        unresolved = [f for f in mstate if mstate[f] == 'u']
        if unresolved:
            modified = repostate[0]
            modified[:] = set(modified) - set(unresolved)
            repostate.insert(0, unresolved)
            states = [UNRESOLVED] + states
    states = zip(repostate, states)
    states[-1], states[-2] = states[-2], states[-1] #clean before ignored
    for grp, st in states:
        add_dirs(grp)
        for f in grp:
            fpath = os.path.join(root, os.path.normpath(f))
            add(fpath, st)
    status = overlay_cache.get(path, UNKNOWN)
    debugf("%s: %s", (path, status))
    cache_tick_count = GetTickCount()
    return status


def add(path, state):
    overlay_cache[path] = overlay_cache.get(path, '') + state
