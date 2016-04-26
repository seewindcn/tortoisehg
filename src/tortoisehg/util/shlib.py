# shlib.py - TortoiseHg shell utilities
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2008 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import sys
import time
import threading
from mercurial import hg

def get_system_times():
    t = os.times()
    if t[4] == 0.0: # Windows leaves this as zero, so use time.clock()
        t = (t[0], t[1], t[2], t[3], time.clock())
    return t

if os.name == 'nt':
    def browse_url(url):
        try:
            import win32api
        except ImportError:
            return
        def start_browser():
            try:
                win32api.ShellExecute(0, 'open', url, None, None, 0)
            except Exception:
                pass
        threading.Thread(target=start_browser).start()

    def shell_notify(paths, noassoc=False):
        try:
            from win32com.shell import shell, shellcon
            import pywintypes
        except ImportError:
            return
        dirs = set()
        for path in paths:
            if path is None:
                continue
            abspath = os.path.abspath(path)
            if not os.path.isdir(abspath):
                abspath = os.path.dirname(abspath)
            dirs.add(abspath)
        # send notifications to deepest directories first
        for dir in sorted(dirs, key=len, reverse=True):
            try:
                pidl, ignore = shell.SHILCreateFromPath(dir, 0)
            except pywintypes.com_error:
                return
            if pidl is None:
                continue
            shell.SHChangeNotify(shellcon.SHCNE_UPDATEITEM,
                                 shellcon.SHCNF_IDLIST | shellcon.SHCNF_FLUSH,
                                 pidl, None)
        if not noassoc:
            shell.SHChangeNotify(shellcon.SHCNE_ASSOCCHANGED,
                                 shellcon.SHCNF_FLUSH,
                                 None, None)

    def update_thgstatus(ui, root, wait=False):
        '''Rewrite the file .hg/thgstatus

        Caches the information provided by repo.status() in the file 
        .hg/thgstatus, which can then be read by the overlay shell extension
        to display overlay icons for directories.

        The file .hg/thgstatus contains one line for each directory that has
        removed, modified or added files (in that order of preference). Each
        line consists of one char for the status of the directory (r, m or a),
        followed by the relative path of the directory in the repo. If the
        file .hg/thgstatus is empty, then the repo's working directory is
        clean.

        Specify wait=True to wait until the system clock ticks to the next
        second before accessing Mercurial's dirstate. This is useful when
        Mercurial's .hg/dirstate contains unset entries (in output of
        "hg debugstate"). unset entries happen if .hg/dirstate was updated
        within the same second as Mercurial updated the respective file in
        the working tree. This happens with a high probability for example
        when cloning a repo. The overlay shell extension will display unset
        dirstate entries as (potentially false) modified. Specifying wait=True
        ensures that there are no unset entries left in .hg/dirstate when this
        function exits.
        '''
        if wait:
            tref = time.time()
            tdelta = float(int(tref)) + 1.0 - tref
            if (tdelta > 0.0):
                time.sleep(tdelta)

        repo = hg.repository(ui, root) # a fresh repo object is needed
        repo.lfstatus = True
        repostate = repo.status() # will update .hg/dirstate as a side effect
        repo.lfstatus = False
        modified, added, removed, deleted = repostate[:4]

        dirstatus = {}
        def dirname(f):
            return '/'.join(f.split('/')[:-1])
        for fn in added:
            dirstatus[dirname(fn)] = 'a'
        for fn in modified:
            dirstatus[dirname(fn)] = 'm'
        for fn in removed + deleted:
            dirstatus[dirname(fn)] = 'r'

        update = False
        f = None
        try:
            f = repo.opener('thgstatus', 'rb')
            for dn in sorted(dirstatus):
                s = dirstatus[dn]
                e = f.readline()
                if e.startswith('@@noicons'):
                    break
                if e == '' or e[0] != s or e[1:-1] != dn:
                    update = True
                    break
            if f.readline() != '':
                # extra line in f, needs update
                update = True
        except IOError:
            update = True
        finally:
            if f != None:
                f.close()

        if update:
            f = repo.opener('thgstatus', 'wb', atomictemp=True)
            for dn in sorted(dirstatus):
                s = dirstatus[dn]
                f.write(s + dn + '\n')
                ui.note("%s %s\n" % (s, dn))
            if hasattr(f, 'rename'):
                # On Mercurial 1.9 and earlier, there was a rename() function
                # that served the purpose now served by close(), while close()
                # served the purpose now served by discard().
                f.rename()
            else:
                f.close()
        return update

else:
    def shell_notify(paths, noassoc=False):
        if not paths:
            return
        notify = os.environ.get('THG_NOTIFY', '.tortoisehg/notify')
        if not os.path.isabs(notify):
            notify = os.path.join(os.path.expanduser('~'), notify)
            os.environ['THG_NOTIFY'] = notify
        if not os.path.isfile(notify):
            return
        try:
            f_notify = open(notify, 'w')
        except IOError:
            return
        try:
            abspaths = [os.path.abspath(path) for path in paths if path]
            f_notify.write('\n'.join(abspaths))
        finally:
            f_notify.close()

    def update_thgstatus(*args, **kws):
        pass

    def browse_url(url):
        def start_browser():
            if sys.platform == 'darwin':
                # use Mac OS X internet config module (removed in Python 3.0)
                import ic
                ic.launchurl(url)
            else:
                try:
                    import gconf
                    client = gconf.client_get_default()
                    browser = client.get_string(
                            '/desktop/gnome/url-handlers/http/command') + '&'
                    os.system(browser % url)
                except ImportError:
                    # If gconf is not found, fall back to old standard
                    os.system('firefox ' + url)
        threading.Thread(target=start_browser).start()

