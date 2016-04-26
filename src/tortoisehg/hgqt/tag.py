# tag.py - Tag dialog for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from tortoisehg.util import hglib, i18n
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, qtlib

from PyQt4.QtCore import *
from PyQt4.QtGui import *

keep = i18n.keepgettext()

class TagDialog(QDialog):

    def __init__(self, repoagent, tag='', rev='tip', parent=None, opts={}):
        super(TagDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() &
                            ~Qt.WindowContextHelpButtonHint)

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self.setWindowTitle(_('Tag - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-tag'))

        # base layout box
        base = QVBoxLayout()
        base.setSpacing(0)
        base.setContentsMargins(0, 0, 0, 0)
        base.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.setLayout(base)

        formwidget = QWidget(self)
        formwidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form = QFormLayout(fieldGrowthPolicy=QFormLayout.AllNonFixedFieldsGrow)
        formwidget.setLayout(form)
        base.addWidget(formwidget)

        repo = repoagent.rawRepo()
        ctx = repo[rev]
        form.addRow(_('Revision:'), QLabel('%d (%s)' % (ctx.rev(), ctx)))
        self.rev = ctx.rev()

        ### tag combo
        self.tagCombo = QComboBox()
        self.tagCombo.setEditable(True)
        self.tagCombo.setEditText(hglib.tounicode(tag))
        self.tagCombo.setMinimumContentsLength(30)  # cut long name
        self.tagCombo.currentIndexChanged.connect(self.updateStates)
        self.tagCombo.editTextChanged.connect(self.updateStates)
        qtlib.allowCaseChangingInput(self.tagCombo)
        form.addRow(_('Tag:'), self.tagCombo)

        self.tagRevLabel = QLabel('')
        form.addRow(_('Tagged:'), self.tagRevLabel)

        ### options
        expander = qtlib.ExpanderLabel(_('Options'), False)
        expander.expanded.connect(self.show_options)
        optbox = QVBoxLayout()
        optbox.setSpacing(6)
        form.addRow(expander, optbox)

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        optbox.addLayout(hbox)

        self.localCheckBox = QCheckBox(_('Local tag'))
        self.localCheckBox.toggled.connect(self.updateStates)
        self.replaceCheckBox = QCheckBox(_('Replace existing tag (-f/--force)'))
        self.replaceCheckBox.toggled.connect(self.updateStates)
        optbox.addWidget(self.localCheckBox)
        optbox.addWidget(self.replaceCheckBox)

        self.englishCheckBox = QCheckBox(_('Use English commit message'))
        engmsg = repo.ui.configbool('tortoisehg', 'engmsg', False)
        self.englishCheckBox.setChecked(engmsg)
        optbox.addWidget(self.englishCheckBox)

        self.customCheckBox = QCheckBox(_('Use custom commit message:'))
        self.customCheckBox.toggled.connect(self.customMessageToggle)
        self.customTextLineEdit = QLineEdit()
        optbox.addWidget(self.customCheckBox)
        optbox.addWidget(self.customTextLineEdit)

        ## bottom buttons
        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Close)
        bbox.rejected.connect(self.reject)
        self.addBtn = bbox.addButton(_('&Add'), BB.ActionRole)
        self.removeBtn = bbox.addButton(_('&Remove'), BB.ActionRole)
        form.addRow(bbox)

        self.addBtn.clicked.connect(self.onAddTag)
        self.removeBtn.clicked.connect(self.onRemoveTag)

        ## horizontal separator
        self.sep = QFrame()
        self.sep.setFrameShadow(QFrame.Sunken)
        self.sep.setFrameShape(QFrame.HLine)
        base.addWidget(self.sep)

        ## status line
        self.status = qtlib.StatusLabel()
        self.status.setContentsMargins(4, 2, 4, 4)
        base.addWidget(self.status)
        self._finishmsg = None

        repoagent.repositoryChanged.connect(self.refresh)
        self.customTextLineEdit.setDisabled(True)
        self.replaceCheckBox.setChecked(bool(opts.get('force')))
        self.localCheckBox.setChecked(bool(opts.get('local')))
        if not opts.get('local') and opts.get('message'):
            msg = hglib.tounicode(opts['message'])
            self.customCheckBox.setChecked(True)
            self.customTextLineEdit.setText(msg)
        self.clear_status()
        self.show_options(False)
        self.tagCombo.setFocus()
        self.refresh()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    @pyqtSlot()
    def refresh(self):
        """ update display on dialog with recent repo data """
        cur = self.tagCombo.currentText()

        tags = list(self.repo.tags())
        tags.sort(reverse=True)
        self.tagCombo.clear()
        for tag in tags:
            if tag in ('tip', 'qbase', 'qtip', 'qparent'):
                continue
            self.tagCombo.addItem(hglib.tounicode(tag))
        if cur:
            self.tagCombo.setEditText(cur)
        else:
            self.tagCombo.clearEditText()
            self.updateStates()

    @pyqtSlot()
    def updateStates(self):
        """ update bottom button sensitives based on rev and tag """
        tagu = self.tagCombo.currentText()
        tag = hglib.fromunicode(tagu)

        # check tag existence
        if tag:
            exists = tag in self.repo.tags()
            if exists:
                tagtype = self.repo.tagtype(tag)
                islocal = 'local' == tagtype
                try:
                    ctx = self.repo[self.repo.tags()[tag]]
                    trev = ctx.rev()
                    thash = str(ctx)
                except:
                    trev, thash, local = 0, '????????', ''
                self.localCheckBox.setChecked(islocal)
                self.localCheckBox.setEnabled(False)
                local = islocal and _('local') or ''
                self.tagRevLabel.setText('%d (%s) %s' % (trev, thash, local))
                samerev = trev == self.rev
            else:
                islocal = self.localCheckBox.isChecked()
                self.localCheckBox.setEnabled(True)
                self.tagRevLabel.clear()

            force = self.replaceCheckBox.isChecked()
            custom = self.customCheckBox.isChecked()
            self.addBtn.setEnabled(not exists or (force and not samerev))
            if exists and not samerev:
                self.addBtn.setText(_('Move'))
            else:
                self.addBtn.setText(_('Add'))
            self.removeBtn.setEnabled(exists)
            self.englishCheckBox.setEnabled(not islocal)
            self.customCheckBox.setEnabled(not islocal)
            self.customTextLineEdit.setEnabled(not islocal and custom)
        else:
            self.addBtn.setEnabled(False)
            self.removeBtn.setEnabled(False)
            self.localCheckBox.setEnabled(False)
            self.englishCheckBox.setEnabled(False)
            self.customCheckBox.setEnabled(False)
            self.customTextLineEdit.setEnabled(False)
            self.tagRevLabel.clear()

    def customMessageToggle(self, checked):
        self.customTextLineEdit.setEnabled(checked)
        if checked:
            self.customTextLineEdit.setFocus()

    def show_options(self, visible):
        self.localCheckBox.setVisible(visible)
        self.replaceCheckBox.setVisible(visible)
        self.englishCheckBox.setVisible(visible)
        self.customCheckBox.setVisible(visible)
        self.customTextLineEdit.setVisible(visible)

    def set_status(self, text, icon):
        self.status.setVisible(True)
        self.sep.setVisible(True)
        self.status.set_status(text, icon)

    def clear_status(self):
        self.status.setHidden(True)
        self.sep.setHidden(True)

    def _runTag(self, tagname, **opts):
        if not self._cmdsession.isFinished():
            self.set_status(_('Repository command still running'), False)
            return

        self._finishmsg = opts.pop('finishmsg')
        cmdline = hglib.buildcmdargs('tag', tagname, **opts)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onTagFinished)

    @pyqtSlot(int)
    def _onTagFinished(self, ret):
        if ret == 0:
            self.set_status(self._finishmsg, True)
        else:
            self.set_status(self._cmdsession.errorString(), False)

    def onAddTag(self):
        tagu = self.tagCombo.currentText()
        tag = hglib.fromunicode(tagu)
        local = self.localCheckBox.isChecked()
        force = self.replaceCheckBox.isChecked()
        english = self.englishCheckBox.isChecked()
        if self.customCheckBox.isChecked() and not local:
            message = self.customTextLineEdit.text()
        else:
            message = None

        exists = tag in self.repo.tags()
        if not local:
            if not message:
                ctx = self.repo[self.rev]
                if exists:
                    origctx = self.repo[self.repo.tags()[tag]]
                    msgset = keep._('Moved tag %s to changeset %s'
                                    ' (from changeset %s)')
                    message = ((english and msgset['id'] or msgset['str'])
                               % (tagu, str(ctx), str(origctx)))
                else:
                    msgset = keep._('Added tag %s for changeset %s')
                    message = ((english and msgset['id'] or msgset['str'])
                               % (tagu, str(ctx)))

        if exists:
            finishmsg = _("Tag '%s' has been moved") % tagu
        else:
            finishmsg = _("Tag '%s' has been added") % tagu

        user = qtlib.getCurrentUsername(self, self.repo)
        if not user:
            return
        self._runTag(tagu, rev=self.rev, user=hglib.tounicode(user),
                     local=local, force=force, message=message,
                     finishmsg=finishmsg)

    def onRemoveTag(self):
        tagu = self.tagCombo.currentText()
        local = self.localCheckBox.isChecked()
        force = self.replaceCheckBox.isChecked()
        english = self.englishCheckBox.isChecked()
        if self.customCheckBox.isChecked() and not local:
            message = self.customTextLineEdit.text()
        else:
            message = None

        if not local:
            if not message:
                msgset = keep._('Removed tag %s')
                message = (english and msgset['id'] or msgset['str']) % tagu

        finishmsg = _("Tag '%s' has been removed") % tagu
        self._runTag(tagu, remove=True,
                     local=local, force=force, message=message,
                     finishmsg=finishmsg)

    def reject(self):
        if not self._cmdsession.isFinished():
            self.set_status(_('Repository command still running'), False)
            return

        super(TagDialog, self).reject()
