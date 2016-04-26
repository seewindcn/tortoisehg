# pbranch.py - TortoiseHg's patch branch widget
#
# Copyright 2010 Peer Sommerlund <peso@users.sourceforge.net>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import errno

from mercurial import extensions, error, util

from tortoisehg.hgqt import qtlib, cmdcore, cmdui, update, revdetails
from tortoisehg.hgqt.qtlib import geticon
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

PATCHCACHEPATH = 'thgpbcache'
nullvariant = QVariant()

class PatchBranchWidget(QWidget, qtlib.TaskWidget):
    '''
    A widget that show the patch graph and provide actions
    for the pbranch extension
    '''

    def __init__(self, repoagent, parent=None, logwidget=None):
        QWidget.__init__(self, parent)

        # Set up variables and connect signals

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self.pbranch = extensions.find('pbranch') # Unfortunately global instead of repo-specific
        self.show_internal_branches = False

        repoagent.configChanged.connect(self.configChanged)
        repoagent.repositoryChanged.connect(self.refresh)

        # Build child widgets

        def BuildChildWidgets():
            vbox = QVBoxLayout()
            vbox.setContentsMargins(0, 0, 0, 0)
            self.setLayout(vbox)
            vbox.addWidget(Toolbar(), 1)
            vbox.addWidget(BelowToolbar(), 1)

        def Toolbar():
            tb = QToolBar(_("Patch Branch Toolbar"), self)
            tb.setIconSize(qtlib.toolBarIconSize())
            tb.setEnabled(True)
            tb.setObjectName("toolBar_patchbranch")
            tb.setFloatable(False)

            self.actionPMerge = a = QWidgetAction(self)
            a.setIcon(geticon("hg-merge"))
            a.setToolTip(_('Merge all pending dependencies'))
            tb.addAction(self.actionPMerge)
            self.actionPMerge.triggered.connect(self.pmerge_clicked)

            self.actionBackport = a = QWidgetAction(self)
            a.setIcon(geticon("go-previous"))
            a.setToolTip(_('Backout current patch branch'))
            #tb.addAction(self.actionBackport)
            #self.actionBackport.triggered.connect(self.pbackout_clicked)

            self.actionReapply = a = QWidgetAction(self)
            a.setIcon(geticon("go-next"))
            a.setToolTip(_('Backport part of a changeset to a dependency'))
            #tb.addAction(self.actionReapply)
            #self.actionReapply.triggered.connect(self.reapply_clicked)

            self.actionPNew = a = QWidgetAction(self)
            a.setIcon(geticon("hg-add")) #STOCK_NEW
            a.setToolTip(_('Start a new patch branch'))
            tb.addAction(self.actionPNew)
            self.actionPNew.triggered.connect(self.pnew_clicked)

            self.actionEditPGraph = a = QWidgetAction(self)
            a.setIcon(geticon("edit-file")) #STOCK_EDIT
            a.setToolTip(_('Edit patch dependency graph'))
            tb.addAction(self.actionEditPGraph)
            self.actionEditPGraph.triggered.connect(self.edit_pgraph_clicked)

            return tb

        def BelowToolbar():
            w = QSplitter(self)
            w.addWidget(PatchList())
            w.addWidget(PatchDiff())
            return w

        def PatchList():
            self.patchlistmodel = PatchBranchModel(self.compute_model(),
                                                   self.repo.changectx('.').branch(),
                                                   self)
            self.patchlist = QTableView(self)
            self.patchlist.setModel(self.patchlistmodel)
            self.patchlist.setShowGrid(False)
            self.patchlist.verticalHeader().setDefaultSectionSize(20)
            self.patchlist.horizontalHeader().setHighlightSections(False)
            self.patchlist.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.patchlist.clicked.connect(self.patchBranchSelected)
            return self.patchlist

        def PatchDiff():
            # pdiff view to the right of pgraph
            self.patchDiffStack = QStackedWidget()
            self.patchDiffStack.addWidget(PatchDiffMessage())
            self.patchDiffStack.addWidget(PatchDiffDetails())
            return self.patchDiffStack

        def PatchDiffMessage():
            # message if no patch is selected
            self.patchDiffMessage = QLabel()
            self.patchDiffMessage.setAlignment(Qt.AlignCenter)
            return self.patchDiffMessage

        def PatchDiffDetails():
            # pdiff view of selected patc
            self.patchdiff = revdetails.RevDetailsWidget(self._repoagent, self)
            return self.patchdiff

        BuildChildWidgets()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def reload(self):
        'User has requested a reload'
        self.repo.thginvalidate()
        self.refresh()

    @pyqtSlot()
    def refresh(self):
        """
        Refresh the list of patches.
        This operation will try to keep selection state.
        """
        if not self.pbranch:
            return

        # store selected patch name
        selname = None
        patchnamecol = PatchBranchModel._columns.index('Name') # Column used to store patch name
        selinxs = self.patchlist.selectedIndexes()
        if len(selinxs) > 0:
            selrow = selinxs[0].row()
            patchnameinx = self.patchlist.model().index(selrow, patchnamecol)
            selname = self.patchlist.model().data(patchnameinx)

        # compute model data
        self.patchlistmodel.setModel(
            self.compute_model(),
            self.repo.changectx('.').branch() )

        # restore patch selection
        if selname:
            selinxs = self.patchlistmodel.match(
                self.patchlistmodel.index(0, patchnamecol),
                Qt.DisplayRole,
                selname,
                flags = Qt.MatchExactly)
            if len(selinxs) > 0:
                self.patchlist.setCurrentIndex(selinxs[0])

        # update UI sensitives
        self.update_sensitivity()

    #
    # Data functions
    #

    def compute_model(self):
        """
        Compute content of table, including patch graph and other columns
        """

        # compute model data
        model = []
        # Generate patch branch graph from all heads (option --tips)
        opts = {'tips': True}
        mgr = self.pbranch.patchmanager(self.repo.ui, self.repo, opts)
        graph = mgr.graphforopts(opts)
        target_graph = mgr.graphforopts({})
        if not self.show_internal_branches:
            graph = mgr.patchonlygraph(graph)
        names = None
        patch_list = graph.topolist(names)
        in_lines = []
        if patch_list:
            dep_list = [patch_list[0]]
        cur_branch = self.repo['.'].branch()
        patch_status = {}
        for name in patch_list:
            patch_status[name] = self.pstatus(name)
        for name in patch_list:
            parents = graph.deps(name)

            # Node properties
            if name in dep_list:
                node_column = dep_list.index(name)
            else:
                node_column = len(dep_list)
            node_color = patch_status[name] and '#ff0000' or 0
            node_status = nodestatus_NORMAL
            if graph.ispatch(name) and not target_graph.ispatch(name):
                node_status = nodestatus_CLOSED
            if name == cur_branch:
                node_status = node_status | nodestatus_CURRENT
            node = PatchGraphNodeAttributes(node_column, node_color, node_status)

            # Find next dependency list
            my_deps = []
            for p in parents:
                if p not in dep_list:
                    my_deps.append(p)
            next_dep_list = dep_list[:]
            next_dep_list[node_column:node_column+1] = my_deps

            # Dependency lines
            shift = len(parents) - 1
            out_lines = []
            for p in parents:
                dep_column = next_dep_list.index(p)
                color = 0 # black
                if patch_status[p]:
                    color = '#ff0000' # red
                style = 0 # solid lines
                out_lines.append(GraphLine(node_column, dep_column, color, style))
            for line in in_lines:
                if line.end_column == node_column:
                    # Deps to current patch end here
                    pass
                else:
                    # Find line continuations
                    dep = dep_list[line.end_column]
                    dep_column = next_dep_list.index(dep)
                    out_lines.append(GraphLine(line.end_column, dep_column, line.color, line.style))

            stat = patch_status[name] and 'M' or 'C' # patch status
            patchname = name
            msg = self.pmessage(name) # summary
            if msg:
                title = msg.split('\n')[0]
            else:
                title = None
            model.append(PatchGraphNode(node, in_lines, out_lines, patchname, stat,
                               title, msg))
            # Loop
            in_lines = out_lines
            dep_list = next_dep_list

        return model


    #
    # pbranch extension functions
    #

    def pgraph(self):
        """
        [pbranch] Execute 'pgraph' command.

        :returns: A list of patches and dependencies
        """
        if self.pbranch is None:
            return None
        opts = {}
        mgr = self.pbranch.patchmanager(self.repo.ui, self.repo, opts)
        return mgr.graphforopts(opts)

    def pstatus(self, patch_name):
        """
        [pbranch] Execute 'pstatus' command.

        :param patch_name: Name of patch-branch
        :retv: list of status messages. If empty there is no pending merges
        """
        if self.pbranch is None:
            return None
        status = []
        opts = {}
        mgr = self.pbranch.patchmanager(self.repo.ui, self.repo, opts)
        graph = mgr.graphforopts(opts)
        graph_cur = mgr.graphforopts({'tips': True})
        heads = self.repo.branchheads(patch_name)
        if graph_cur.isinner(patch_name) and not graph.isinner(patch_name):
            status.append(_('will be closed'))
        if len(heads) > 1:
            status.append(_('needs merge of %i heads\n') % len(heads))
        for dep, through in graph.pendingmerges(patch_name):
            if through:
                status.append(_('needs merge with %s (through %s)\n') %
                          (dep, ", ".join(through)))
            else:
                status.append(_('needs merge with %s\n') % dep)
        for dep in graph.pendingrebases(patch_name):
            status.append(_('needs update of diff base to tip of %s\n') % dep)
        return status

    def pmessage(self, patch_name):
        """
        Get patch message

        :param patch_name: Name of patch-branch
        :retv: Full patch message. If you extract the first line
        you will get the patch title. If the repo does not contain
        message or patch, the function returns None
        """
        opts = {}
        mgr = self.pbranch.patchmanager(self.repo.ui, self.repo, opts)
        try:
            return mgr.patchdesc(patch_name)
        except:
            return None

    def pdiff(self, patch_name):
        """
        [pbranch] Execute 'pdiff --tips' command.

        :param patch_name: Name of patch-branch
        :retv: list of lines of generated patch
        """
        opts = {}
        mgr = self.pbranch.patchmanager(self.repo.ui, self.repo, opts)
        graph = mgr.graphattips()
        return graph.diff(patch_name, None, opts)

    def pnew_ui(self):
        """
        Create new patch.
        Prompt user for new patch name. Patch is created
        on current branch.
        """
        dialog = PNewDialog()
        if dialog.exec_() != QDialog.Accepted:
            return False
        cmdline = dialog.getCmd()
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self.commandFinished)
        return True

    def pnew(self, patch_name):
        """
        [pbranch] Execute 'pnew' command.

        :param patch_name: Name of new patch-branch
        """
        if self.pbranch is None:
            return False
        self.pbranch.cmdnew(self.repo.ui, self.repo, patch_name)
        self._repoagent.pollStatus()
        return True

    def pmerge(self, patch_name=None):
        """
        [pbranch] Execute 'pmerge' command.

        :param patch_name: Merge to this patch-branch
        """
        if not self.has_patch():
            return
        cmdline = ['pmerge']
        if patch_name:
            cmdline += [hglib.tounicode(patch_name)]
        else:
            cmdline += ['--all']
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self.commandFinished)

    def has_pbranch(self):
        """ return True if pbranch extension can be used """
        return self.pbranch is not None

    def has_patch(self):
        """ return True if pbranch extension is in use on repo """
        return self.has_pbranch() and self.pgraph() != []

    def is_patch(self, branch_name):
        """ return True if branch is a patch. This excludes root branches
        and internal diff base branches (for patches with multiple
        dependencies). """
        return self.has_pbranch() and self.pgraph().ispatch(branch_name)

    def cur_branch(self):
        """ Return branch that workdir belongs to. """
        return self.repo.dirstate.branch()

    ### internal functions ###

    def patchFromIndex(self, index):
        if not index.isValid():
            return
        model = self.patchlistmodel
        col = model._columns.index('Name')
        patchIndex = model.createIndex(index.row(), col)
        return str(model.data(patchIndex).toString())

    def updatePatchCache(self, patchname):
        # TODO: Parameters should include rev, as one patch may have several heads
        # rev should be appended to filename and used by pdiff
        assert(len(patchname)>0)
        cachepath = self.repo.join(PATCHCACHEPATH)
        # TODO: Fix this - it looks ugly
        try:
            os.mkdir(cachepath)
        except OSError, err:
            if err.errno != errno.EEXIST:
                raise
        # TODO: Convert filename if any funny characters are present
        patchfile = os.path.join(cachepath, patchname)
        dirstate = self.repo.join('dirstate')
        try:
            patch_age = os.path.getmtime(patchfile) - os.path.getmtime(dirstate)
        except:
            patch_age = -1

        if patch_age < 0:
            pf = open(patchfile, 'wb')
            try:
                pf.writelines(self.pdiff(patchname))
            #  except (util.Abort, error.RepoError), e:
            #      # Do something with str(e)
            finally:
                pf.close()

        return patchfile


    def update_sensitivity(self):
        """ Update the sensitivity of entire UI """
        in_pbranch = True #TODO
        is_merge = len(self.repo[None].parents()) > 1
        self.actionPMerge.setEnabled(in_pbranch)
        self.actionBackport.setEnabled(in_pbranch)
        self.actionReapply.setEnabled(True)
        self.actionPNew.setEnabled(not is_merge)
        self.actionEditPGraph.setEnabled(True)

    def selected_patch(self):
        C_NAME = PatchBranchModel._columns.index('Name')
        indexes = self.patchlist.selectedIndexes()
        if len(indexes) == 0:
            return None
        index = indexes[0]
        return str(index.sibling(index.row(), C_NAME).data().toString())

    def show_patch_cmenu(self, pos):
        """Context menu for selected patch"""
        patchname = self.selected_patch()
        if not patchname:
            return

        menu = QMenu(self)
        def append(label, handler):
            menu.addAction(label).triggered.connect(handler)

        has_pbranch = self.has_pbranch()
        is_current = self.has_patch() and self.cur_branch() == patchname
        is_patch = self.is_patch(patchname)
        is_internal = self.pbranch.isinternal(patchname)
        is_merge = len(self.repo.branchheads(patchname)) > 1

        #if has_pbranch and not is_merge and not is_internal:
        #    append(_('&New'), self.pnew_activated)
        if not is_current:
            append(_('&Goto (update workdir)'), self.goto_activated)
        if is_patch:
            append(_('&Merge'), self.merge_activated)
        #    append(_('&Edit message'), self.edit_message_activated)
        #    append(_('&Rename'), self.rename_activated)
        #    append(_('&Delete'), self.delete_activated)
        #    append(_('&Finish'), self.finish_activated)

        if len(menu.actions()) > 0:
            menu.exec_(pos)

    # Signal handlers

    def patchBranchSelected(self, index):
        patchname = self.patchFromIndex(index)
        if self.is_patch(patchname):
            patchfile = self.updatePatchCache(patchname)
            self.patchdiff.onRevisionSelected(patchfile)
            self.patchDiffStack.setCurrentWidget(self.patchdiff)
        else:
            self.patchDiffMessage.setText(_('No patch branch selected'))
            self.patchDiffStack.setCurrentWidget(self.patchDiffMessage)

    def contextMenuEvent(self, event):
        if self.patchlist.geometry().contains(event.pos()):
            self.show_patch_cmenu(event.globalPos())

    @pyqtSlot(int)
    def commandFinished(self, ret):
        if ret != 0:
            cmdui.errorMessageBox(self._cmdsession, self)
        self.refresh()

    @pyqtSlot()
    def configChanged(self):
        pass

    def pmerge_clicked(self):
        self.pmerge()

    def pnew_clicked(self, toolbutton):
        self.pnew_ui()

    def edit_pgraph_clicked(self):
        opts = {} # TODO: How to find user ID
        mgr = self.pbranch.patchmanager(self.repo.ui, self.repo, opts)
        if not mgr.hasgraphdesc():
            self.pbranch.writefile(mgr.graphdescpath(), '')
        oldtext = mgr.graphdesc()
        # run editor in the repository root
        olddir = os.getcwd()
        os.chdir(self.repo.root)
        try:
            newtext = None
            newtext = self.repo.ui.edit(oldtext, opts.get('user'))
        except error.Abort:
            no_editor_configured =(os.environ.get("HGEDITOR") or
                self.repo.ui.config("ui", "editor") or
                os.environ.get("VISUAL") or
                os.environ.get("EDITOR","editor-not-configured")
                == "editor-not-configured")
            if no_editor_configured:
                qtlib.ErrorMsgBox(_('No editor found'),
                    _('Mercurial was unable to find an editor. Please configure Mercurial to use an editor installed on your system.'))
            else:
                raise
        os.chdir(olddir)
        if newtext is not None:
            mgr.updategraphdesc(newtext)
            self.refresh()

    ### context menu signal handlers ###

    def pnew_activated(self):
        """Insert new patch after this row"""
        assert False

    def edit_message_activated(self):
        assert False

    def goto_activated(self):
        branch = self.selected_patch()
        # TODO: Fetch list of heads of branch
        # - use a list of revs if more than one found
        dlg = update.UpdateDialog(self._repoagent, branch, self)
        dlg.exec_()

    def merge_activated(self):
        self.pmerge(self.selected_patch())

    def delete_activated(self):
        assert False

    def rename_activated(self):
        assert False

    def finish_activated(self):
        assert False

class PatchGraphNode(object):
    """
    Simple class to encapsulate a node in the patch branch graph.
    Does nothing but declaring attributes.
    """
    def __init__(self, node, in_lines, out_lines, patchname, stat,
                 title, msg):
        """
        :node: attributes related to the node
        :in_lines: List of lines above node
        :out_lines: List of lines below node
        :patchname: Patch branch name
        :stat: Status of node - does it need updating or not
        :title: First line of patch message
        :msg: Full patch message
        """
        self.node = node
        self.toplines = in_lines
        self.bottomlines = out_lines
        # Find rightmost column used
        self.cols = max([max(line.start_column,line.end_column) for line in in_lines + out_lines])
        self.patchname = patchname
        self.status = stat
        self.title = title
        self.message = msg
        self.msg_esc = msg # u''.join(msg) # escaped summary (utf-8)


nodestatus_CURRENT = 4
nodestatus_NORMAL = 0
nodestatus_PATCH = 1
nodestatus_CLOSED = 2
nodestatus_shapemask = 3

class PatchGraphNodeAttributes(object):
    """
    Simple class to encapsulate attributes about a node in the patch branch graph.
    Does nothing but declaring attributes.
    """
    def __init__(self, column, color, status):
        self.column = column
        self.color = color
        self.status = status

class GraphLine(object):
    """
    Simple class to encapsulate attributes about a line in the patch branch graph.
    Does nothing but declaring attributes.
    """
    def __init__(self, start_column, end_column, color, style):
        self.start_column = start_column
        self.end_column = end_column
        self.color = color
        self.style = style

class PatchBranchContext(object):
    """
    Similar to patchctx in thgrepo, this class simulates a changeset
    for a particular patch branch-
    """

class PatchBranchModel(QAbstractTableModel):
    """
    Model used to list patch branches
    TODO: Should be extended to list all branches
    """
    _columns = ['Graph', 'Name', 'Status', 'Title', 'Message',]
    _headers = (_('Graph'), _('Name'), _('Status'), _('Title'), _('Message'))

    def __init__(self, model, wd_branch="", parent=None):
        QAbstractTableModel.__init__(self, parent)
        self.rowcount = 0
        self._columnmap = {'Graph':    lambda ctx, gnode: "",
                           'Name':     lambda ctx, gnode: gnode.patchname,
                           'Status':   lambda ctx, gnode: gnode.status,
                           'Title':    lambda ctx, gnode: gnode.title,
                           'Message':  lambda ctx, gnode: gnode.message
                           }
        self.model = model
        self.wd_branch = wd_branch
        self.dotradius = 8
        self.rowheight = 20

    # virtual functions required to subclass QAbstractTableModel

    def rowCount(self, parent=None):
        return len(self.model)

    def columnCount(self, parent=None):
        return len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return nullvariant
        row = index.row()
        column = self._columns[index.column()]
        gnode = self.model[row]
        ctx = None
        #ctx = self.repo.changectx(gnode.rev)

        if role == Qt.DisplayRole:
            text = self._columnmap[column](ctx, gnode)
            if not isinstance(text, (QString, unicode)):
                text = hglib.tounicode(text)
            return QVariant(text)
        elif role == Qt.ForegroundRole:
            return gnode.node.color
        elif role == Qt.DecorationRole:
            if column == 'Graph':
                return self.graphctx(ctx, gnode)
        return nullvariant

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return QVariant(self._headers[section])
            if role == Qt.TextAlignmentRole:
                return QVariant(Qt.AlignLeft)
        return nullvariant

    # end of functions required to subclass QAbstractTableModel




    def setModel(self, model, wd_branch):
        self.beginResetModel()
        self.model = model
        self.wd_branch = wd_branch
        self.endResetModel()

    def col2x(self, col):
        return 2 * self.dotradius * col + self.dotradius/2 + 8

    def graphctx(self, ctx, gnode):
        """
        Return a QPixmap for the patch graph for the current row

        :ctx: Data for current row = branch (not used)
        :gnode: PatchGraphNode in patch branch graph

        :returns: QPixmap of pgraph for ctx
        """
        w = self.col2x(gnode.cols) + 10
        h = self.rowheight

        dot_y = h / 2

        # Prepare painting: Target pixmap, blue and black pen
        pix = QPixmap(w, h)
        pix.fill(QColor(0,0,0,0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(Qt.blue)
        pen.setWidth(2)
        painter.setPen(pen)

        lpen = QPen(pen)
        lpen.setColor(Qt.black)
        painter.setPen(lpen)

        # Draw lines
        for y1, y4, lines in ((dot_y, dot_y + h, gnode.bottomlines),
                              (dot_y - h, dot_y, gnode.toplines)):
            y2 = y1 + 1 * (y4 - y1)/4
            ymid = (y1 + y4)/2
            y3 = y1 + 3 * (y4 - y1)/4

            for line in lines:
                start = line.start_column
                end = line.end_column
                color = line.color
                lpen = QPen(pen)
                lpen.setColor(QColor(color))
                lpen.setWidth(2)
                painter.setPen(lpen)
                x1 = self.col2x(start)
                x2 = self.col2x(end)
                path = QPainterPath()
                path.moveTo(x1, y1)
                path.cubicTo(x1, y2,
                             x1, y2,
                             (x1 + x2)/2, ymid)
                path.cubicTo(x2, y3,
                             x2, y3,
                             x2, y4)
                painter.drawPath(path)

        # Draw node
        dot_color = QColor(gnode.node.color)
        dotcolor = dot_color.lighter()
        pencolor = dot_color.darker()
        white = QColor("white")
        fillcolor = dotcolor #gnode.rev is None and white or dotcolor

        pen = QPen(pencolor)
        pen.setWidthF(1.5)
        painter.setPen(pen)

        radius = self.dotradius
        centre_x = self.col2x(gnode.node.column)
        centre_y = h/2

        def circle(r):
            rect = QRectF(centre_x - r,
                          centre_y - r,
                          2 * r, 2 * r)
            painter.drawEllipse(rect)

        def closesymbol(s, offset = 0):
            rect_ = QRectF(centre_x - 1.5 * s, centre_y - 0.5 * s, 3 * s, s)
            rect_.adjust(-offset, -offset, offset, offset)
            painter.drawRect(rect_)

        def diamond(r):
            poly = QPolygonF([QPointF(centre_x - r, centre_y),
                              QPointF(centre_x, centre_y - r),
                              QPointF(centre_x + r, centre_y),
                              QPointF(centre_x, centre_y + r),
                              QPointF(centre_x - r, centre_y),])
            painter.drawPolygon(poly)

        nodeshape = gnode.node.status & nodestatus_shapemask
        if nodeshape ==  nodestatus_PATCH:  # diamonds for patches
            if gnode.node.status & nodestatus_CURRENT:
                painter.setBrush(white)
                diamond(2 * 0.9 * radius / 1.5)
            painter.setBrush(fillcolor)
            diamond(radius / 1.5)
        elif nodeshape == nodestatus_CLOSED:
            if gnode.node.status & nodestatus_CURRENT:
                painter.setBrush(white)
                closesymbol(0.5 * radius, 2 * pen.widthF())
            painter.setBrush(fillcolor)
            closesymbol(0.5 * radius)
        else:  # circles for normal branches
            if gnode.node.status & nodestatus_CURRENT:
                painter.setBrush(white)
                circle(0.9 * radius)
            painter.setBrush(fillcolor)
            circle(0.5 * radius)

        painter.end()
        return QVariant(pix)

class PNewDialog(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowIcon(qtlib.geticon("hg-add"))
        self.setWindowTitle(_('New Patch Branch'))

        def AddField(var, label, optional=False):
            hbox = QHBoxLayout()
            SP = QSizePolicy
            le = QLineEdit()
            le.setSizePolicy(SP(SP.Expanding, SP.Fixed))
            if optional:
                cb = QCheckBox(label)
                le.setEnabled(False)
                cb.toggled.connect(le.setEnabled)
                hbox.addWidget(cb)
                setattr(self, var+'cb', cb)
            else:
                hbox.addWidget(QLabel(label))
            hbox.addWidget(le)
            setattr(self, var+'le', le)
            return hbox

        def DialogButtons():
            BB = QDialogButtonBox
            bb = QDialogButtonBox(BB.Ok|BB.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            bb.button(BB.Ok).setDefault(True)
            bb.button(BB.Cancel).setDefault(False)
            self.commitButton = bb.button(BB.Ok)
            self.commitButton.setText(_('Commit', 'action button'))
            self.bb = bb
            return bb

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        self.setLayout(layout)
        layout.addLayout(AddField('patchname',_('Patch name:')))
        layout.addLayout(AddField('patchtext',_('Patch message:'), optional=True))
        layout.addLayout(AddField('patchdate',_('Patch date:'), optional=True))
        layout.addLayout(AddField('patchuser',_('Patch user:'), optional=True))
        layout.addWidget(DialogButtons())

        self.patchdatele.setText(
                hglib.tounicode(hglib.displaytime(util.makedate())))

    def patchname(self):
        return self.patchnamele.text()

    def getCmd(self):
        cmd = ['pnew', unicode(self.patchname())]
        optList = [('patchtext','--text'),
                   ('patchdate','--date'),
                   ('patchuser','--user')]
        for v,o in optList:
            if getattr(self,v+'cb').isChecked():
                cmd.extend([o,unicode(getattr(self,v+'le').text())])
        return cmd
