# update.py - Update dialog for TortoiseHg
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, csinfo, qtlib, resolve

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class UpdateWidget(cmdui.AbstractCmdWidget):

    def __init__(self, repoagent, rev=None, parent=None, opts={}):
        super(UpdateWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._repoagent = repoagent
        repo = repoagent.rawRepo()

        ## main layout
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.setLayout(form)

        ### target revision combo
        self.rev_combo = combo = QComboBox()
        combo.setEditable(True)
        combo.setMinimumContentsLength(30)  # cut long name
        combo.installEventFilter(qtlib.BadCompletionBlocker(combo))
        form.addRow(_('Update to:'), combo)

        # always include integer revision
        try:
            assert not isinstance(rev, (unicode, QString))
            ctx = self.repo[rev]
            if isinstance(ctx.rev(), int):  # could be None or patch name
                combo.addItem(str(ctx.rev()))
        except error.RepoLookupError:
            pass

        combo.addItems(map(hglib.tounicode, hglib.namedbranches(repo)))
        tags = list(self.repo.tags()) + repo._bookmarks.keys()
        tags.sort(reverse=True)
        combo.addItems(map(hglib.tounicode, tags))

        if rev is None:
            selecturev = hglib.tounicode(self.repo.dirstate.branch())
        else:
            selecturev = hglib.tounicode(str(rev))
        selectindex = combo.findText(selecturev)
        if selectindex >= 0:
            combo.setCurrentIndex(selectindex)
        else:
            combo.setEditText(selecturev)

        ### target revision info
        items = ('%(rev)s', ' %(branch)s', ' %(tags)s', '<br />%(summary)s')
        style = csinfo.labelstyle(contents=items, width=350, selectable=True)
        factory = csinfo.factory(self.repo, style=style)
        self.target_info = factory()
        form.addRow(_('Target:'), self.target_info)

        ### parent revision info
        self.ctxs = self.repo[None].parents()
        if len(self.ctxs) == 2:
            self.p1_info = factory()
            form.addRow(_('Parent 1:'), self.p1_info)
            self.p2_info = factory()
            form.addRow(_('Parent 2:'), self.p2_info)
        else:
            self.p1_info = factory()
            form.addRow(_('Parent:'), self.p1_info)

        # show a subrepo "pull path" combo, with the
        # default path as the first (and default) path
        self.path_combo_label = QLabel(_('Pull subrepos from:'))
        self.path_combo = QComboBox(self)
        syncpaths = dict(repo.ui.configitems('paths'))
        aliases = sorted(syncpaths)
        # make sure that the default path is the first one
        if 'default' in aliases:
            aliases.remove('default')
            aliases.insert(0, 'default')
        for n, alias in enumerate(aliases):
            self.path_combo.addItem(hglib.tounicode(alias))
            self.path_combo.setItemData(
                n, hglib.tounicode(syncpaths[alias]))
        self.path_combo.currentIndexChanged.connect(
            self._updatePathComboTooltip)
        self._updatePathComboTooltip(0)
        form.addRow(self.path_combo_label, self.path_combo)

        ### options
        self.optbox = QVBoxLayout()
        self.optbox.setSpacing(6)
        self.optexpander = expander = qtlib.ExpanderLabel(_('Options:'), False)
        expander.expanded.connect(self.show_options)
        form.addRow(expander, self.optbox)

        self.verbose_chk = QCheckBox(_('List updated files (--verbose)'))
        self.discard_chk = QCheckBox(_('Discard local changes, no backup '
                                       '(-C/--clean)'))
        self.merge_chk = QCheckBox(_('Always merge (when possible)'))
        self.autoresolve_chk = QCheckBox(_('Automatically resolve merge '
                                           'conflicts where possible'))
        self.optbox.addWidget(self.verbose_chk)
        self.optbox.addWidget(self.discard_chk)
        self.optbox.addWidget(self.merge_chk)
        self.optbox.addWidget(self.autoresolve_chk)

        self.discard_chk.setChecked(bool(opts.get('clean')))

        # signal handlers
        self.rev_combo.editTextChanged.connect(self.update_info)
        self.discard_chk.toggled.connect(self.update_info)

        # prepare to show
        self.merge_chk.setHidden(True)
        self.autoresolve_chk.setHidden(True)
        self.update_info()
        if not self.canRunCommand():
            # need to change rev
            self.rev_combo.lineEdit().selectAll()

    def readSettings(self, qs):
        self.merge_chk.setChecked(qs.value('merge').toBool())
        self.autoresolve_chk.setChecked(
            self.repo.ui.configbool('tortoisehg', 'autoresolve',
                                    qs.value('autoresolve', True).toBool()))
        self.verbose_chk.setChecked(qs.value('verbose').toBool())

        # expand options if a hidden one is checked
        self.optexpander.set_expanded(self.hiddenSettingIsChecked())

    def writeSettings(self, qs):
        qs.setValue('merge', self.merge_chk.isChecked())
        qs.setValue('autoresolve', self.autoresolve_chk.isChecked())
        qs.setValue('verbose', self.verbose_chk.isChecked())

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def hiddenSettingIsChecked(self):
        return (self.merge_chk.isChecked()
                or self.autoresolve_chk.isChecked())

    @pyqtSlot()
    def update_info(self):
        self.p1_info.update(self.ctxs[0].node())
        merge = len(self.ctxs) == 2
        if merge:
            self.p2_info.update(self.ctxs[1])
        new_rev = hglib.fromunicode(self.rev_combo.currentText())
        if new_rev == 'null':
            self.target_info.setText(_('remove working directory'))
            self.commandChanged.emit()
            return
        try:
            new_ctx = self.repo[new_rev]
            if not merge and new_ctx.rev() == self.ctxs[0].rev() \
                    and not new_ctx.bookmarks():
                self.target_info.setText(_('(same as parent)'))
            else:
                self.target_info.update(self.repo[new_rev])
            # only show the path combo when there are multiple paths
            # and the target revision has subrepos
            showpathcombo = self.path_combo.count() > 1 and \
                '.hgsubstate' in new_ctx
            self.path_combo_label.setVisible(showpathcombo)
            self.path_combo.setVisible(showpathcombo)
        except (error.LookupError, error.RepoError, EnvironmentError):
            self.target_info.setText(_('unknown revision!'))
        self.commandChanged.emit()

    def canRunCommand(self):
        new_rev = hglib.fromunicode(self.rev_combo.currentText())
        try:
            new_ctx = self.repo[new_rev]
        except (error.LookupError, error.RepoError, EnvironmentError):
            return False
        return (self.discard_chk.isChecked()
                or len(self.ctxs) == 2
                or new_ctx.rev() != self.ctxs[0].rev()
                or bool(new_ctx.bookmarks()))

    def runCommand(self):
        cmdline = ['update']
        if self.verbose_chk.isChecked():
            cmdline += ['--verbose']
        cmdline += ['--config', 'ui.merge=internal:' +
                    (self.autoresolve_chk.isChecked() and 'merge' or 'fail')]
        rev = hglib.fromunicode(self.rev_combo.currentText())

        activatebookmarkmode = self.repo.ui.config(
            'tortoisehg', 'activatebookmarks', 'prompt')
        if activatebookmarkmode != 'never':
            bookmarks = self.repo[rev].bookmarks()
            if bookmarks and rev not in bookmarks:
                # The revision that we are updating into has bookmarks,
                # but the user did not refer to the revision by one of them
                # (probably used a revision number or hash)
                # Ask the user if it wants to update to one of these bookmarks
                # instead
                selectedbookmark = None
                if len(bookmarks) == 1:
                    if activatebookmarkmode == 'auto':
                        activatebookmark = True
                    else:
                        activatebookmark = qtlib.QuestionMsgBox(
                            _('Activate bookmark?'),
                            _('The selected revision (%s) has a bookmark on it '
                              'called "<i>%s</i>".<p>Do you want to activate '
                              'it?<br></b>'
                              '<i>You can disable this prompt by configuring '
                              'Settings/Workbench/Activate Bookmarks</i>') \
                            % (hglib.tounicode(rev),
                               hglib.tounicode(bookmarks[0])))
                    if activatebookmark:
                        selectedbookmark = bookmarks[0]
                else:
                    # Even in auto mode, when there is more than one bookmark
                    # we must ask the user which one must be activated
                    selectedbookmark = qtlib.ChoicePrompt(
                        _('Activate bookmark?'),
                        _('The selected revision (<i>%s</i>) has <i>%d</i> '
                          'bookmarks on it.<p>Select the bookmark that you '
                          'want to activate and click <i>OK</i>.'
                          "<p>Click <i>Cancel</i> if you don't want to "
                          'activate any of them.<p><p>'
                          '<i>You can disable this prompt by configuring '
                          'Settings/Workbench/Activate Bookmarks</i><p>') \
                        % (hglib.tounicode(rev), len(bookmarks)),
                        self, bookmarks, hglib.activebookmark(self.repo)).run()
                if selectedbookmark:
                    rev = selectedbookmark
                elif self.repo[rev] == self.repo[hglib.activebookmark(self.repo)]:
                    deactivatebookmark = qtlib.QuestionMsgBox(
                        _('Deactivate current bookmark?'),
                        _('Do you really want to deactivate the <i>%s</i> '
                          'bookmark?')
                        % hglib.tounicode(hglib.activebookmark(self.repo)))
                    if deactivatebookmark:
                        cmdline = ['bookmark']
                        if self.verbose_chk.isChecked():
                            cmdline += ['--verbose']
                        cmdline += ['-i',
                                    hglib.tounicode(hglib.activebookmark(self.repo))]
                        return self._repoagent.runCommand(cmdline, self)
                    return cmdcore.nullCmdSession()

        cmdline.append('--rev')
        cmdline.append(rev)

        pullpathname = hglib.fromunicode(
            self.path_combo.currentText())
        if pullpathname and pullpathname != 'default':
            # We must tell mercurial to pull any missing repository
            # revisions from the selected path. The only way to do so is
            # to temporarily set the default path to the selected path URL
            pullpath = hglib.fromunicode(
                self.path_combo.itemData(
                    self.path_combo.currentIndex()).toString())
            cmdline.append('--config')
            cmdline.append('paths.default=%s' % pullpath)

        if self.discard_chk.isChecked():
            cmdline.append('--clean')
        else:
            cur = self.repo.hgchangectx('.')
            try:
                node = self.repo.hgchangectx(rev)
            except (error.LookupError, error.RepoError, EnvironmentError):
                return cmdcore.nullCmdSession()
            def isclean():
                '''whether WD is changed'''
                try:
                    wc = self.repo[None]
                    if wc.modified() or wc.added() or wc.removed():
                        return False
                    for s in wc.substate:
                        if wc.sub(s).dirty():
                            return False
                except EnvironmentError:
                    return False
                return True
            def ismergedchange():
                '''whether the local changes are merged (have 2 parents)'''
                wc = self.repo[None]
                return len(wc.parents()) == 2
            def islocalmerge(p1, p2, clean=None):
                if clean is None:
                    clean = isclean()
                pa = p1.ancestor(p2)
                return not clean and (p1 == pa or p2 == pa)
            def confirmupdate(clean=None):
                if clean is None:
                    clean = isclean()

                msg = _('Detected uncommitted local changes in working tree.\n'
                        'Please select to continue:\n')
                data = {'discard': (_('&Discard'),
                                    _('Discard - discard local changes, no '
                                      'backup')),
                        'shelve': (_('&Shelve'),
                                  _('Shelve - move local changes to a patch')),
                        'merge': (_('&Merge'),
                                  _('Merge - allow to merge with local '
                                    'changes'))}

                opts = ['discard']
                if not ismergedchange():
                    opts.append('shelve')
                if islocalmerge(cur, node, clean):
                    opts.append('merge')

                dlg = QMessageBox(QMessageBox.Question, _('Confirm Update'),
                                  '', QMessageBox.Cancel, self)
                buttonnames = {}
                for name in opts:
                    label, desc = data[name]
                    msg += '\n'
                    msg += desc
                    btn = dlg.addButton(label, QMessageBox.ActionRole)
                    buttonnames[btn] = name
                dlg.setDefaultButton(QMessageBox.Cancel)
                dlg.setText(msg)
                dlg.exec_()
                clicked = buttonnames.get(dlg.clickedButton())
                return clicked

            # If merge-by-default, we want to merge whenever possible,
            # without prompting user (similar to command-line behavior)
            defaultmerge = self.merge_chk.isChecked()
            clean = isclean()
            if clean:
                cmdline.append('--check')
            elif not (defaultmerge and islocalmerge(cur, node, clean)):
                clicked = confirmupdate(clean)
                if clicked == 'discard':
                    cmdline.append('--clean')
                elif clicked == 'shelve':
                    from tortoisehg.hgqt import shelve
                    dlg = shelve.ShelveDialog(self._repoagent, self)
                    dlg.finished.connect(dlg.deleteLater)
                    dlg.exec_()
                    return cmdcore.nullCmdSession()
                elif clicked == 'merge':
                    pass # no args
                else:
                    return cmdcore.nullCmdSession()

        cmdline = map(hglib.tounicode, cmdline)
        return self._repoagent.runCommand(cmdline, self)

    @pyqtSlot(bool)
    def show_options(self, visible):
        self.merge_chk.setVisible(visible)
        self.autoresolve_chk.setVisible(visible)

    @pyqtSlot(int)
    def _updatePathComboTooltip(self, idx):
        self.path_combo.setToolTip(self.path_combo.itemData(idx).toString())


class UpdateDialog(cmdui.CmdControlDialog):

    def __init__(self, repoagent, rev=None, parent=None, opts={}):
        super(UpdateDialog, self).__init__(parent)
        self._repoagent = repoagent

        self.setWindowTitle(_('Update - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-update'))
        self.setObjectName('update')
        self.setRunButtonText(_('&Update'))
        self.setCommandWidget(UpdateWidget(repoagent, rev, self, opts))
        self.commandFinished.connect(self._checkMergeConflicts)

    @pyqtSlot(int)
    def _checkMergeConflicts(self, ret):
        if ret != 1:
            return
        qtlib.InfoMsgBox(_('Merge caused file conflicts'),
                         _('File conflicts need to be resolved'))
        dlg = resolve.ResolveDialog(self._repoagent, self)
        dlg.exec_()
        if not self.isLogVisible():
            self.reject()
