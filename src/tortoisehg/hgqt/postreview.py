# postreview.py - post review dialog for TortoiseHg
#
# Copyright 2011 Michael De Wildt <michael.dewildt@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

"""A dialog to allow users to post a review to reviewboard

http:///www.reviewboard.org

This dialog requires a fork of the review board mercurial plugin, maintained
by mdelagra, that can be downloaded from:

https://bitbucket.org/mdelagra/mercurial-reviewboard/

More information can be found at http://www.mikeyd.com.au/tortoisehg-reviewboard
"""

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from mercurial import extensions, scmutil
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, qtlib
from tortoisehg.hgqt.postreview_ui import Ui_PostReviewDialog
from tortoisehg.hgqt.hgemail import _ChangesetsModel

class LoadReviewDataThread(QThread):
    def __init__ (self, dialog):
        super(LoadReviewDataThread, self).__init__(dialog)
        self.dialog = dialog

    def run(self):
        msg = None
        if not self.dialog.server:
            msg = _("Invalid Settings - The ReviewBoard server is not setup")
        elif not self.dialog.user:
            msg = _("Invalid Settings - Please provide your ReviewBoard username")
        else:
            rb = extensions.find("reviewboard")
            try:
                pwd = self.dialog.password
                #if we don't have a password send something here to skip
                #the cli getpass in the extension. We will set the password
                #later
                if not pwd:
                    pwd = "None"

                self.reviewboard = rb.make_rbclient(self.dialog.server,
                                                    self.dialog.user,
                                                    pwd)
                self.loadCombos()

            except rb.ReviewBoardError, e:
                msg = e.msg
            except TypeError:
                msg = _("Invalid reviewboard plugin. Please download the "
                        "Mercurial reviewboard plugin version 3.5 or higher "
                        "from the website below.\n\n %s") % \
                        u'http://bitbucket.org/mdelagra/mercurial-reviewboard/'

        self.dialog.error_message = msg

    def loadCombos(self):
        #Get the index of a users previously selected repo id
        index = 0
        count = 0

        self.dialog.qui.progress_label.setText("Loading repositories...")
        for r in self.reviewboard.repositories():
            if r.id == self.dialog.repo_id:
                index = count
            self.dialog.qui.repo_id_combo.addItem(str(r.id) + ": " + r.name)
            count += 1

        if self.dialog.qui.repo_id_combo.count():
            self.dialog.qui.repo_id_combo.setCurrentIndex(index)

        self.dialog.qui.progress_label.setText("Loading existing reviews...")
        for r in self.reviewboard.pending_user_requests():
            summary = str(r.id) + ": " + r.summary[0:100]
            self.dialog.qui.review_id_combo.addItem(summary)

        if self.dialog.qui.review_id_combo.count():
            self.dialog.qui.review_id_combo.setCurrentIndex(0)

class PostReviewDialog(QDialog):
    """Dialog for sending patches to reviewboard"""
    def __init__(self, ui, repoagent, revs, parent=None):
        super(PostReviewDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.ui = ui
        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self._cmdoutputs = []
        self.error_message = None

        self.qui = Ui_PostReviewDialog()
        self.qui.setupUi(self)

        self.initChangesets(revs)
        self.readSettings()

        self.review_thread = LoadReviewDataThread(self)
        self.review_thread.finished.connect(self.errorPrompt)
        self.review_thread.start()
        QShortcut(QKeySequence('Ctrl+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    @pyqtSlot()
    def passwordPrompt(self):
        pwd, ok = qtlib.getTextInput(self,
                                     _('Review Board'),
                                     _('Password:'),
                                     mode=QLineEdit.Password)
        if ok and pwd:
            self.password = pwd
            return True
        else:
            self.password = None
            return False

    @pyqtSlot()
    def errorPrompt(self):
        self.qui.progress_bar.hide()
        self.qui.progress_label.hide()

        if self.error_message:
            qtlib.ErrorMsgBox(_('Review Board'),
                              _('Error'), self.error_message)
            self.close()
        elif self.isValid():
            self.qui.post_review_button.setEnabled(True)

    def closeEvent(self, event):
        if not self._cmdsession.isFinished():
            self._cmdsession.abort()
            event.ignore()
            return

        # Dispose of the review data thread
        self.review_thread.terminate()
        self.review_thread.wait()

        self.writeSettings()
        super(PostReviewDialog, self).closeEvent(event)

    def readSettings(self):
        s = QSettings()

        self.restoreGeometry(s.value('reviewboard/geom').toByteArray())

        self.qui.publish_immediately_check.setChecked(
                s.value('reviewboard/publish_immediately_check').toBool())
        self.qui.outgoing_changes_check.setChecked(
                s.value('reviewboard/outgoing_changes_check').toBool())
        self.qui.branch_check.setChecked(
                s.value('reviewboard/branch_check').toBool())
        self.qui.update_fields.setChecked(
                s.value('reviewboard/update_fields').toBool())
        self.qui.summary_edit.addItems(
                s.value('reviewboard/summary_edit_history').toStringList())

        try:
            self.repo_id = int(self.repo.ui.config('reviewboard', 'repoid'))
        except Exception:
            self.repo_id = None

        if not self.repo_id:
            self.repo_id = s.value('reviewboard/repo_id').toInt()[0]

        self.server = self.repo.ui.config('reviewboard', 'server')
        self.user = self.repo.ui.config('reviewboard', 'user')
        self.password = self.repo.ui.config('reviewboard', 'password')
        self.browser = self.repo.ui.config('reviewboard', 'browser')

    def writeSettings(self):
        s = QSettings()
        s.setValue('reviewboard/geom', self.saveGeometry())
        s.setValue('reviewboard/publish_immediately_check',
                   self.qui.publish_immediately_check.isChecked())
        s.setValue('reviewboard/branch_check',
                   self.qui.branch_check.isChecked())
        s.setValue('reviewboard/outgoing_changes_check',
                   self.qui.outgoing_changes_check.isChecked())
        s.setValue('reviewboard/update_fields',
                   self.qui.update_fields.isChecked())
        s.setValue('reviewboard/repo_id', self.getRepoId())

        def itercombo(w):
            if w.currentText():
                yield w.currentText()
            for i in xrange(w.count()):
                if w.itemText(i) != w.currentText():
                    yield w.itemText(i)

        s.setValue('reviewboard/summary_edit_history',
                   list(itercombo(self.qui.summary_edit))[:10])

    def initChangesets(self, revs, selected_revs=None):
        def purerevs(revs):
            return scmutil.revrange(self.repo, iter(str(e) for e in revs))
        if selected_revs:
            selectedrevs = purerevs(selected_revs)
        else:
            selectedrevs = purerevs(revs)

        self._changesets = _ChangesetsModel(self.repo,
                                            # TODO: [':'] is inefficient
                                            revs=purerevs(revs or [':']),
                                            selectedrevs=selectedrevs,
                                            parent=self)

        self.qui.changesets_view.setModel(self._changesets)

    @property
    def selectedRevs(self):
        """Returns list of revisions to be sent"""
        return self._changesets.selectedrevs

    @property
    def allRevs(self):
        """Returns list of revisions to be sent"""
        return self._changesets.revs

    def getRepoId(self):
        comboText = self.qui.repo_id_combo.currentText().split(":")
        return str(comboText[0])

    def getReviewId(self):
        comboText = self.qui.review_id_combo.currentText().split(":")
        return str(comboText[0])

    def getSummary(self):
        comboText = self.qui.review_id_combo.currentText().split(":")
        return hglib.fromunicode(comboText[1])

    def postReviewOpts(self, **opts):
        """Generate opts for reviewboard by form values"""
        opts['outgoingchanges'] = self.qui.outgoing_changes_check.isChecked()
        opts['branch'] = self.qui.branch_check.isChecked()
        opts['publish'] = self.qui.publish_immediately_check.isChecked()

        if self.qui.tab_widget.currentIndex() == 1:
            opts["existing"] = self.getReviewId()
            opts['update'] = self.qui.update_fields.isChecked()
            opts['summary'] = self.getSummary()
        else:
            opts['repoid'] = self.getRepoId()
            opts['summary'] = hglib.fromunicode(self.qui.summary_edit.currentText())

        if (len(self.selectedRevs) > 1):
            #Set the parent to the revision below the last one on the list
            #so all checked revisions are included in the request
            ctx = self.repo[self.selectedRevs[0]]
            opts['parent'] = str(ctx.p1().rev())

        # Always use the upstream repo to determine the parent diff base
        # without the diff uploaded to review board dies
        opts['outgoing'] = True

        #Set the password just in  case the user has opted to not save it
        opts['password'] = str(self.password)

        return opts

    def isValid(self):
        """Filled all required values?"""
        if not self.qui.repo_id_combo.currentText():
            return False

        if self.qui.tab_widget.currentIndex() == 1:
            if not self.qui.review_id_combo.currentText():
                return False

        if not self.allRevs:
            return False

        return True

    @pyqtSlot()
    def tabChanged(self):
        self.qui.post_review_button.setEnabled(self.isValid())

    @pyqtSlot()
    def branchCheckToggle(self):
        if self.qui.branch_check.isChecked():
            self.qui.outgoing_changes_check.setChecked(False)

        self.toggleOutgoingChangesets()

    @pyqtSlot()
    def outgoingChangesCheckToggle(self):
        if self.qui.outgoing_changes_check.isChecked():
            self.qui.branch_check.setChecked(False)

        self.toggleOutgoingChangesets()

    def toggleOutgoingChangesets(self):
        branch = self.qui.branch_check.isChecked()
        outgoing = self.qui.outgoing_changes_check.isChecked()
        if branch or outgoing:
            self.initChangesets(self.allRevs, [self.selectedRevs.pop()])
            self.qui.changesets_view.setEnabled(False)
        else:
            self.initChangesets(self.allRevs, self.allRevs)
            self.qui.changesets_view.setEnabled(True)

    def close(self):
        super(PostReviewDialog, self).close()

    def accept(self):
        if not self.isValid():
            return
        if not self.password and not self.passwordPrompt():
            return

        self.qui.progress_bar.show()
        self.qui.progress_label.setText("Posting Review...")
        self.qui.progress_label.show()

        def cmdargs(opts):
            args = []
            for k, v in opts.iteritems():
                if isinstance(v, bool):
                    if v:
                        args.append('--%s' % k.replace('_', '-'))
                else:
                    for e in isinstance(v, basestring) and [v] or v:
                        args += ['--%s' % k.replace('_', '-'), e]

            return args

        opts = self.postReviewOpts()

        revstr = str(self.selectedRevs.pop())

        self.qui.post_review_button.setEnabled(False)
        self.qui.close_button.setEnabled(False)

        cmdline = map(hglib.tounicode,
                      ['postreview'] + cmdargs(opts) + [revstr])
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        del self._cmdoutputs[:]
        sess.commandFinished.connect(self.onCompletion)
        sess.outputReceived.connect(self._captureOutput)

    @pyqtSlot()
    def onCompletion(self):
        self.qui.progress_bar.hide()
        self.qui.progress_label.hide()

        output = hglib.fromunicode(''.join(self._cmdoutputs), 'replace')

        saved = 'saved:' in output
        published = 'published:' in output
        if (saved or published):
            if saved:
                url = output.split('saved: ').pop().strip()
                msg = _('Review draft posted to %s\n') % url
            else:
                url = output.split('published: ').pop().strip()
                msg = _('Review published to %s\n') % url

            QDesktopServices.openUrl(QUrl(url))

            qtlib.InfoMsgBox(_('Review Board'), _('Success'),
                               msg, parent=self)
        else:
            error = output.split('abort: ').pop().strip()
            if error[:29] == "HTTP Error: basic auth failed":
                if self.passwordPrompt():
                    self.accept()
                else:
                    self.qui.post_review_button.setEnabled(True)
                    self.qui.close_button.setEnabled(True)
                    return
            else:
                qtlib.ErrorMsgBox(_('Review Board'),
                                  _('Error'), error)

        self.writeSettings()
        super(PostReviewDialog, self).accept()

    @pyqtSlot(str, str)
    def _captureOutput(self, msg, label):
        if label != 'control':
            self._cmdoutputs.append(unicode(msg))

    @pyqtSlot()
    def onSettingsButtonClicked(self):
        from tortoisehg.hgqt import settings
        if settings.SettingsDialog(parent=self, focus='reviewboard.server').exec_():
            # not use repo.configChanged because it can clobber user input
            # accidentally.
            self.repo.invalidateui()  # force reloading config immediately
            self.readSettings()
