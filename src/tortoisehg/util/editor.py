import os, sys
from mercurial import util, match

def _getplatformexecutablekey():
    if sys.platform == 'darwin':
        key = 'executable-osx'
    elif os.name == 'nt':
        key = 'executable-win'
    else:
        key = 'executable-unix'
    return key

_platformexecutablekey = _getplatformexecutablekey()

def _toolstr(ui, tool, part, default=""):
    return ui.config("editor-tools", tool + "." + part, default)

toolcache = {}
def _findtool(ui, tool):
    global toolcache
    if tool in toolcache:
        return toolcache[tool]
    for kn in ("regkey", "regkeyalt"):
        k = _toolstr(ui, tool, kn)
        if not k:
            continue
        p = util.lookupreg(k, _toolstr(ui, tool, "regname"))
        if p:
            p = util.findexe(p + _toolstr(ui, tool, "regappend"))
            if p:
                toolcache[tool] = p
                return p
    global _platformexecutablekey
    exe = _toolstr(ui, tool, _platformexecutablekey)
    if not exe:
        exe = _toolstr(ui, tool, 'executable', tool)
    path = util.findexe(util.expandpath(exe))
    if path:
        toolcache[tool] = path
        return path
    elif tool != exe:
        path = util.findexe(tool)
        toolcache[tool] = path
        return path
    toolcache[tool] = None
    return None

def _findeditor(repo, files):
    '''returns tuple of editor name and editor path.

    tools matched by pattern are returned as (name, toolpath)
    tools detected by search are returned as (name, toolpath)
    tortoisehg.editor is returned as         (None, tortoisehg.editor)
    HGEDITOR or ui.editor are returned as    (None, ui.editor)

    So first return value is an [editor-tool] name or None and
    second return value is a toolpath or user configured command line
    '''
    ui = repo.ui

    # first check for tool specified by file patterns.  The first file pattern
    # which matches one of the files being edited selects the editor
    for pat, tool in ui.configitems("editor-patterns"):
        mf = match.match(repo.root, '', [pat])
        toolpath = _findtool(ui, tool)
        if mf(files[0]) and toolpath:
            return (tool, util.shellquote(toolpath))

    # then editor-tools
    tools = {}
    for k, v in ui.configitems("editor-tools"):
        t = k.split('.')[0]
        if t not in tools:
            try:
                priority = int(_toolstr(ui, t, "priority", "0"))
            except ValueError, e:
                priority = -100
            tools[t] = priority
    names = tools.keys()
    tools = sorted([(-p, t) for t, p in tools.items()])
    editor = ui.config('tortoisehg', 'editor')
    if editor:
        if editor not in names:
            # if tortoisehg.editor does not match an editor-tools entry, take
            # the value directly
            return (None, editor)
        # else select this editor as highest priority (may still use another if
        # it is not found on this machine)
        tools.insert(0, (None, editor))
    for p, t in tools:
        toolpath = _findtool(ui, t)
        if toolpath:
            return (t, util.shellquote(toolpath))

    # fallback to potential CLI editor
    editor = os.environ.get('HGEDITOR') or repo.ui.config('ui', 'editor') \
             or os.environ.get('EDITOR', 'vi')
    return (None, editor)

def detecteditor(repo, files):
    'returns tuple of editor tool path and arguments'
    name, pathorconfig = _findeditor(repo, files)
    if name is None:
        return (pathorconfig, None, None, None)
    else:
        args = _toolstr(repo.ui, name, "args")
        argsln = _toolstr(repo.ui, name, "argsln")
        argssearch = _toolstr(repo.ui, name, "argssearch")
        return (pathorconfig, args, argsln, argssearch)

def findeditors(ui):
    seen = set()
    for key, value in ui.configitems('editor-tools'):
        t = key.split('.')[0]
        seen.add(t)
    return [t for t in seen if _findtool(ui, t)]
