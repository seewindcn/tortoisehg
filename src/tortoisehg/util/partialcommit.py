# partialcommit.py - commit extension for partial commits (change selection)
#
# Copyright 2012 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
from mercurial import patch, commands, extensions, context, util, node
from tortoisehg.util import hgversion

testedwith = hgversion.testedwith

def partialcommit(orig, ui, repo, *pats, **opts):
    patchfilename = opts.get('partials', None)
    if patchfilename:
        # attach a patch.filestore to this repo prior to calling commit()
        # the wrapped workingfilectx methods will see this filestore and use
        # the patched file data rather than the working copy data (for only the
        # files modified by the patch)
        fp = open(patchfilename, 'rb')
        store = patch.filestore()
        try:
            # patch files in tmp directory
            patch.patchrepo(ui, repo, repo['.'], store, fp, 1, prefix='')
            store.keys = set(store.files.keys() + store.data.keys())
            repo._filestore = store
        except patch.PatchError, e:
            raise util.Abort(str(e))
        finally:
            fp.close()

    try:
        ret = orig(ui, repo, *pats, **opts)
        if hasattr(repo, '_filestore'):
            store.close()
            del repo._filestore
            wlock = repo.wlock()
            try:
                # mark partially committed files for 'needing lookup' in
                # the dirstate.  The next status call will find them as M
                for f in store.keys:
                    repo.dirstate.normallookup(f)
            finally:
                wlock.release()
        return ret
    finally:
        if patchfilename:
            os.unlink(patchfilename)

def wfctx_data(orig, self):
    'wrapper function for workingfilectx.data()'
    if hasattr(self._repo, '_filestore'):
        store = self._repo._filestore
        if self._path in store.keys:
            data, (islink, isexec), copied = store.getfile(self._path)
            return data
    return orig(self)

def wfctx_flags(orig, self):
    'wrapper function for workingfilectx.flags()'
    if hasattr(self._repo, '_filestore'):
        store = self._repo._filestore
        if self._path in store.keys:
            data, (islink, isexec), copied = store.getfile(self._path)
            return (islink and 'l' or '') + (isexec and 'x' or '')
    return orig(self)

def wfctx_renamed(orig, self):
    'wrapper function for workingfilectx.renamed()'
    if hasattr(self._repo, '_filestore'):
        store = self._repo._filestore
        if self._path in store.keys:
            data, (islink, isexec), copied = store.getfile(self._path)
            if copied:
                return copied, node.nullid
            else:
                return None
    return orig(self)

def uisetup(ui):
    extensions.wrapfunction(context.workingfilectx, 'data', wfctx_data)
    extensions.wrapfunction(context.workingfilectx, 'flags', wfctx_flags)
    extensions.wrapfunction(context.workingfilectx, 'renamed', wfctx_renamed)
    entry = extensions.wrapcommand(commands.table, 'commit', partialcommit)
    entry[1].append(('', 'partials', '',
                     'selected patch chunks (internal use only)'))
