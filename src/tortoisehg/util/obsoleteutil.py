# obsolete related util functions (taken from hgview)
#
# The functions in this file have been taken from hgview's util.py file
# (http://hg.logilab.org/review/hgview/file/default/hgviewlib/util.py)
#
# Copyright (C) 2009-2012 Logilab. All rights reserved.
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

from mercurial import error

def precursorsmarkers(obsstore, node):
    return obsstore.precursors.get(node, ())

def successorsmarkers(obsstore, node):
    return obsstore.successors.get(node, ())

def first_known_precursors(ctx):
    obsstore = getattr(ctx._repo, 'obsstore', None)
    startnode = ctx.node()
    nm = ctx._repo.changelog.nodemap
    if obsstore is not None:
        markers = precursorsmarkers(obsstore, startnode)
        # consider all precursors
        candidates = set(mark[0] for mark in markers)
        seen = set(candidates)
        if startnode in candidates:
            candidates.remove(startnode)
        else:
            seen.add(startnode)
        while candidates:
            current = candidates.pop()
            # is this changeset in the displayed set ?
            crev = nm.get(current)
            if crev is not None:
                try:
                    yield ctx._repo[crev]
                    continue
                except error.RepoLookupError:
                    # filtered-out changeset
                    pass
            for mark in precursorsmarkers(obsstore, current):
                if mark[0] not in seen:
                    candidates.add(mark[0])
                    seen.add(mark[0])

def first_known_successors(ctx):
    obsstore = getattr(ctx._repo, 'obsstore', None)
    startnode = ctx.node()
    nm = ctx._repo.changelog.nodemap
    if obsstore is not None:
        markers = successorsmarkers(obsstore, startnode)
        # consider all precursors
        candidates = set()
        for mark in markers:
            candidates.update(mark[1])
        seen = set(candidates)
        if startnode in candidates:
            candidates.remove(startnode)
        else:
            seen.add(startnode)
        while candidates:
            current = candidates.pop()
            # is this changeset in the displayed set ?
            crev = nm.get(current)
            if crev is not None:
                try:
                    yield ctx._repo[crev]
                    continue
                except error.RepoLookupError:
                    # filtered-out changeset
                    pass
            for mark in successorsmarkers(obsstore, current):
                for succ in mark[1]:
                    if succ not in seen:
                        candidates.add(succ)
                        seen.add(succ)
