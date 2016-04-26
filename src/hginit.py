import sys, os
from os.path import join, abspath, dirname

src_path = abspath(dirname(__file__))
sys.path.append(src_path + '\\py27lib')
# sys.path.append(src_path + '\\library')
sys.path.append(src_path + '\\lib32')
# print '*******', sys.path
os.wingide = 0

if 1:
    os.environ['HGRCPATH'] = os.pathsep.join([join(src_path, 'hgrc')])
# exts = (
#     ('hgsvn', join(src_path, 'ext/hgsubversion/hgsubversion')),
#     ('hggit', join(src_path, 'ext/hggit/hggit')),
# )

def _hginit():
    if os.wingide:
        import wingdbstub
        print 'wingdbstub ok'
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

