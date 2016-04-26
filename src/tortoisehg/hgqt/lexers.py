# lexers.py - select Qsci lexer for a filename and contents
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import re

from PyQt4 import Qsci, QtGui
from tortoisehg.hgqt import qtlib

if hasattr(QtGui.QColor, 'getHslF'):
    def _fixdarkcolors(lexer):
        """Invert lightness of low-contrast colors on dark theme"""
        if not qtlib.isDarkTheme():
            return  # fast path

        # QsciLexer defines 128 styles by default
        for style in xrange(128):
            h, s, l, a = lexer.color(style).getHslF()
            pl = lexer.paper(style).lightnessF()
            if abs(l - pl) < 0.2:
                lexer.setColor(QtGui.QColor.fromHslF(h, s, 1.0 - l, a), style)
else:
    # no support for PyQt 4.6.x
    def _fixdarkcolors(lexer):
        pass

class _LexerSelector(object):
    _lexer = None
    def match(self, filename, filedata):
        return False

    def lexer(self, parent):
        """
        Return a configured instance of the lexer
        """
        return self.cfg_lexer(self._lexer(parent))

    def cfg_lexer(self, lexer):
        font = qtlib.getfont('fontlog').font()
        lexer.setFont(font, -1)
        _fixdarkcolors(lexer)
        return lexer

class _FilenameLexerSelector(_LexerSelector):
    """
    Base class for lexer selector based on file name matching
    """
    extensions = ()
    def match(self, filename, filedata):
        filename = filename.lower()
        for ext in self.extensions:
            if filename.endswith(ext):
                return True
        return False

class _ScriptLexerSelector(_FilenameLexerSelector):
    """
    Base class for lexer selector based on content pattern matching
    """
    regex = None
    headersize = 3
    def match(self, filename, filedata):
        if super(_ScriptLexerSelector, self).match(filename, filedata):
            return True
        if self.regex and filedata:
            for line in filedata.splitlines()[:self.headersize]:
                if len(line)<1000 and self.regex.match(line):
                    return True
        return False

class PythonLexerSelector(_ScriptLexerSelector):
    extensions = ('.py', '.pyw')
    _lexer = Qsci.QsciLexerPython
    regex = re.compile(r'^#[!].*python')

class BashLexerSelector(_ScriptLexerSelector):
    extensions = ('.sh', '.bash')
    _lexer = Qsci.QsciLexerBash
    regex = re.compile(r'^#[!].*sh')

class PerlLexerSelector(_ScriptLexerSelector):
    extensions = ('.pl', '.perl')
    _lexer = Qsci.QsciLexerPerl
    regex = re.compile(r'^#[!].*perl')

class RubyLexerSelector(_ScriptLexerSelector):
    extensions = ('.rb', '.ruby')
    _lexer = Qsci.QsciLexerRuby
    regex = re.compile(r'^#[!].*ruby')

class LuaLexerSelector(_ScriptLexerSelector):
    extensions = ('.lua', )
    _lexer = Qsci.QsciLexerLua
    regex = None

class _LexerCPP(Qsci.QsciLexerCPP):
    def refreshProperties(self):
        super(_LexerCPP, self).refreshProperties()
        # disable grey-out of inactive block, which is hard to read.
        # as of QScintilla 2.7.2, this property isn't mapped to wrapper.
        self.propertyChanged.emit('lexer.cpp.track.preprocessor', '0')

class CppLexerSelector(_FilenameLexerSelector):
    extensions = ('.c', '.cpp', '.cc', '.cxx', '.cl', '.cu',
                  '.h', '.hpp', '.hh', '.hxx')
    _lexer = _LexerCPP

class DLexerSelector(_FilenameLexerSelector):
    extensions = ('.d',)
    _lexer = Qsci.QsciLexerD

class PascalLexerSelector(_FilenameLexerSelector):
    extensions = ('.pas',)
    _lexer = Qsci.QsciLexerPascal

class CSSLexerSelector(_FilenameLexerSelector):
    extensions = ('.css',)
    _lexer = Qsci.QsciLexerCSS

class XMLLexerSelector(_FilenameLexerSelector):
    extensions = ('.xhtml', '.xml', '.csproj', 'app.config', 'web.config')
    _lexer = Qsci.QsciLexerXML

class HTMLLexerSelector(_FilenameLexerSelector):
    extensions = ('.htm', '.html')
    _lexer = Qsci.QsciLexerHTML

class YAMLLexerSelector(_FilenameLexerSelector):
    extensions = ('.yml',)
    _lexer = Qsci.QsciLexerYAML

class VHDLLexerSelector(_FilenameLexerSelector):
    extensions = ('.vhd', '.vhdl')
    _lexer = Qsci.QsciLexerVHDL

class BatchLexerSelector(_FilenameLexerSelector):
    extensions = ('.cmd', '.bat')
    _lexer = Qsci.QsciLexerBatch

class MakeLexerSelector(_FilenameLexerSelector):
    extensions = ('.mk', 'makefile')
    _lexer = Qsci.QsciLexerMakefile

class CMakeLexerSelector(_FilenameLexerSelector):
    extensions = ('.cmake', 'cmakelists.txt')
    _lexer = Qsci.QsciLexerCMake

class SQLLexerSelector(_FilenameLexerSelector):
    extensions = ('.sql',)
    _lexer = Qsci.QsciLexerSQL

class JSLexerSelector(_FilenameLexerSelector):
    extensions = ('.js', '.json')
    _lexer = Qsci.QsciLexerJavaScript

class JavaLexerSelector(_FilenameLexerSelector):
    extensions = ('.java',)
    _lexer = Qsci.QsciLexerJava

class TeXLexerSelector(_FilenameLexerSelector):
    extensions = ('.tex', '.latex',)
    _lexer = Qsci.QsciLexerTeX

class CSharpLexerSelector(_FilenameLexerSelector):
    extensions = ('.cs',)
    _lexer = Qsci.QsciLexerCSharp

class TCLLexerSelector(_FilenameLexerSelector):
    extensions = ('.tcl', '.do', '.fdo', '.udo')
    _lexer = Qsci.QsciLexerTCL

class MatlabLexerSelector(_FilenameLexerSelector):
    extensions = ('.m',)
    try:
        _lexer = Qsci.QsciLexerMatlab
    except AttributeError:  # QScintilla<2.5.1
        # Python lexer is quite similar
        _lexer = Qsci.QsciLexerPython

class FortranLexerSelector(_FilenameLexerSelector):
    extensions = ('.f90', '.f95', '.f03',)
    _lexer = Qsci.QsciLexerFortran

class Fortran77LexerSelector(_FilenameLexerSelector):
    extensions = ('.f', '.f77',)
    _lexer = Qsci.QsciLexerFortran77

class SpiceLexerSelector(_FilenameLexerSelector):
    extensions = ('.cir', '.sp',)
    try:
        _lexer = Qsci.QsciLexerSpice
    except AttributeError:
        # is there a better fallback?
        _lexer = Qsci.QsciLexerCPP

class VerilogLexerSelector(_FilenameLexerSelector):
    extensions = ('.v', '.vh')
    try:
        _lexer = Qsci.QsciLexerVerilog
    except AttributeError:
        # is there a better fallback?
        _lexer = Qsci.QsciLexerCPP

class PropertyLexerSelector(_FilenameLexerSelector):
    extensions = ('.ini', '.properties')
    _lexer = Qsci.QsciLexerProperties

class DiffLexerSelector(_ScriptLexerSelector):
    extensions = ()
    _lexer = Qsci.QsciLexerDiff
    regex = re.compile(r'^@@ [-]\d+,\d+ [+]\d+,\d+ @@$')
    def cfg_lexer(self, lexer):
        for label, i in (('diff.inserted', 6),
                         ('diff.deleted', 5),
                         ('diff.hunk', 4)):
            effect = qtlib.geteffect(label)
            for e in effect.split(';'):
                if e.startswith('color:'):
                    lexer.setColor(QtGui.QColor(e[7:]), i)
                if e.startswith('background-color:'):
                    lexer.setEolFill(True, i)
                    lexer.setPaper(QtGui.QColor(e[18:]), i)
        font = qtlib.getfont('fontdiff').font()
        lexer.setFont(font, -1)
        _fixdarkcolors(lexer)
        return lexer


lexers = []
for clsname, cls in globals().items():
    if clsname.startswith('_'):
        continue
    if isinstance(cls, type) and issubclass(cls, _LexerSelector):
        lexers.append(cls())

def difflexer(parent):
    return DiffLexerSelector().lexer(parent)

def getlexer(ui, filename, filedata, parent):
    _, ext = os.path.splitext(filename)
    if ext and len(ext) > 1:
        ext = ext.lower()[1:]
        pref = ui.config('thg-lexer', ext)
        if pref:
            lexer = getattr(Qsci, 'QsciLexer' + pref)
            if lexer and isinstance(lexer, type):
                return lexer(parent)
    for lselector in lexers:
        if lselector.match(filename, filedata):
            return lselector.lexer(parent)
    return None
