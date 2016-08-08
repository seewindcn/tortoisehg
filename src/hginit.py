import sys, os
from os.path import join, abspath, dirname

# os.wingide = 1

exe_path = abspath(dirname(sys.executable))
lib_path = join(exe_path, 'lib')
src_path = abspath(dirname(__file__))
sys.path.append(join(src_path, 'py27lib'))
sys.path.append(join(src_path, 'lib32'))
sys.path.append(join(src_path, 'ext'))
sys.path.append(join(src_path, 'ext', 'hg-fixutf8'))


if 1:
    os.environ['HGRCPATH'] = os.pathsep.join([join(src_path, 'hgrc')])
# exts = (
#     ('hgsvn', join(src_path, 'ext/hgsubversion/hgsubversion')),
#     ('hggit', join(src_path, 'ext/hggit/hggit')),
# )

import imp
class hgimporter(object):
    """Object that conforms to import hook interface defined in PEP-302."""
    def find_module(self, name, path=None):
        try:
            imp.find_module(name, [lib_path])
            return self
        except ImportError:
            return None

    def load_module(self, name):
        modinfo = imp.find_module(name, [lib_path])
        mod = imp.load_module(name, *modinfo)
        sys.modules[name] = mod
        return mod

def _hginit():
    v = getattr(os, 'wingide', 0)
    if v==1:
        import wingdbstub
        print 'wingdbstub ok'
    elif v > 1:
        os.wingide = v - 1

    import platform
    os._is_32bit_ = int(platform.architecture()[0][:-3]) < 64

    sys.meta_path.insert(0, hgimporter())
    #sys.frozen = False
    if not getattr(sys, 'frozen', None):
        print '~~~~~~~~~~~~~'

    # from mercurial import extensions
    # _old_loadall = extensions.loadall
    # def _my_loadall(ui):
    #     for n, p in exts:
    #         extensions.load(ui, n, p)
    #     _old_loadall(ui)
    # extensions.loadall = _my_loadall

os._hginit = _hginit

