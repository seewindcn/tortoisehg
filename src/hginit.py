import sys, os
from os.path import join, abspath, dirname

src_path = abspath(dirname(__file__))
sys.path.append(join(src_path, 'py27lib'))
sys.path.append(join(src_path, 'lib32'))
sys.path.append(join(src_path, 'ext'))
sys.path.append(join(src_path, 'ext', 'hg-fixutf8'))
# os.wingide = 1

if 1:
    os.environ['HGRCPATH'] = os.pathsep.join([join(src_path, 'hgrc')])
# exts = (
#     ('hgsvn', join(src_path, 'ext/hgsubversion/hgsubversion')),
#     ('hggit', join(src_path, 'ext/hggit/hggit')),
# )

def _hginit():
    v = getattr(os, 'wingide', 0)
    if v==1:
        import wingdbstub
        print 'wingdbstub ok'
    elif v > 1:
        os.wingide = v - 1

    #sys.frozen = False
    if not getattr(sys, 'frozen'):
        print '~~~~~~~~~~~~~'

    # from mercurial import extensions
    # _old_loadall = extensions.loadall
    # def _my_loadall(ui):
    #     for n, p in exts:
    #         extensions.load(ui, n, p)
    #     _old_loadall(ui)
    # extensions.loadall = _my_loadall

os._hginit = _hginit

