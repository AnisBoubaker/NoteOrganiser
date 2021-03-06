"""
.. module:: frames
    :synopsys: Define all the custom frames

.. moduleauthor:: Benjamin Audren <benjamin.audren@gmail.com>
"""
from __future__ import unicode_literals
import os
import shutil
from collections import OrderedDict as od
import pypandoc as pa
import six  # Used to replace the od iteritems from py2
import io
import traceback  # For failure display
import time  # for sleep

from PySide import QtGui
from PySide import QtCore
from PySide import QtWebKit

os.environ['QT_API'] = 'PySide'
import qtawesome

from .utils import FlowLayout
from .utils import fuzzySearch

from subprocess import Popen

# Local imports
from .popups import NewEntry, NewNotebook, NewFolder
import noteorganiser.text_processing as tp
from .constants import EXTENSION
from .configuration import search_folder_recursively
from .syntax import ModifiedMarkdownHighlighter
from .widgets import PicButton, VerticalScrollArea, LineEditWithClearButton


class CustomFrame(QtGui.QFrame):
    """Base class for all three tabbed frames"""

    def __init__(self, parent=None):
        """ Create the basic layout """
        QtGui.QFrame.__init__(self, parent)
        # Create a shortcut notation for the main information
        self.parent = parent
        self.info = parent.info
        self.log = parent.log

        # Create the main layout
        self.setLayout(QtGui.QVBoxLayout())

        if hasattr(self, 'initLogic'):
            self.initLogic()

        self.initUI()

    def initUI(self):
        """
        This will be called on creation

        A daughter class should implement this function
        """
        raise NotImplementedError

    def initToolBar(self):
        """
        This will initialize a toolbar in the parent window

        a daughter class should implement this function if it needs a toolbar.

        If this toolbar should only be visible, when the view is active,
        connect to tabs.currentChanged()
        Example:
            @QtCore.Slot(int)
            def showActiveToolBar(self, tabIndex):
                activeTab = self.tabs.tabText(tabIndex)
                # activate, if there's a toolbar in library / editing
                if activeTab == "&Library":
                    self.library.shelves.toolbar.setVisible(True)
                else:
                    self.library.shelves.toolbar.setVisible(False)
                if activeTab == "&Editing":
                    self.editing.toolbar.setVisible(True)
                else:
                    self.editing.toolbar.setVisible(False)
                if activeTab == "Previe&w":
                    self.preview.toolbar.setVisible(True)
                else:
                    self.preview.toolbar.setVisible(False)
        """
        raise NotImplementedError

    def clearUI(self):
        """ Common method for recursively cleaning layouts """
        while self.layout().count():
            item = self.layout().takeAt(0)
            if isinstance(item, QtGui.QLayout):
                self.clearLayout(item)
                item.deleteLater()
            else:
                try:
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
                except AttributeError:
                    pass

    def clearLayout(self, layout):
        """ Submethod to help cleaning the UI before redrawing """
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    self.clearLayout(item.layout())

    def zoomIn(self):
        raise NotImplementedError

    def zoomOut(self):
        raise NotImplementedError

    def resetSize(self):
        raise NotImplementedError


class Library(CustomFrame):
    r"""
    The notebooks will be stored and displayed there

    Should ressemble something like this:
     _________  _________  _________
    / Library \/ Editing \/ Preview \
    |          ----------------------------------
    |                              | global tag |
    |   notebook_1     notebook_2  | another tag|
    | ------------------------------ tag taggy  |
    |                              | taggy tag  |
    |   notebook_3                 |            |
    |                              |            |
    | [up] [new N] [new F]         |            |
    --------------------------------------------|
    """
    def initUI(self):
        self.log.info("Starting UI init of %s" % self.__class__.__name__)

        # Create the shelves object
        self.shelves = Shelves(self)
        self.layout().addWidget(self.shelves)

        # toolbar on top
        self.initToolBar()

        # right click in empty space
        self.initContextMenu()

        self.log.info("Finished UI init of %s" % self.__class__.__name__)

    def initToolBar(self):
        """initialize the toolbar for this view"""
        if not hasattr(self, 'toolbar'):
            self.toolbar = self.parent.addToolBar('Library')
            self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            self.toolbar.setIconSize(self.toolbar.iconSize() * 0.7)

            # Go up in the directories (disabled if in the root directory)
            upIcon = qtawesome.icon('fa.arrow-up')
            self.upAction = QtGui.QAction(upIcon, '&Up', self)
            self.upAction.setIconText('&Up')
            self.upAction.setShortcut('Ctrl+U')
            self.upAction.triggered.connect(self.shelves.upFolder)
            if self.info.level == self.info.root:
                self.upAction.setDisabled(True)
            self.toolbar.addAction(self.upAction)

            # Create a new notebook
            newNotebookIcon = qtawesome.icon('fa.file')
            self.newNotebookAction = QtGui.QAction(newNotebookIcon,
                                                   '&New Notebook', self)
            self.newNotebookAction.setIconText('&New Notebook')
            self.newNotebookAction.setShortcut('Ctrl+N')
            self.newNotebookAction.triggered.connect(
                self.shelves.createNotebook)
            self.toolbar.addAction(self.newNotebookAction)

            # Create a new folder
            newFolderIcon = qtawesome.icon('fa.folder')
            self.newFolderAction = QtGui.QAction(newFolderIcon, 'New Folde&r',
                                                 self)
            self.newFolderAction.setIconText('New Folde&r')
            self.newFolderAction.setShortcut('Ctrl+F')
            self.newFolderAction.triggered.connect(self.shelves.createFolder)
            self.toolbar.addAction(self.newFolderAction)

    def initContextMenu(self):
        """
        add actions to the context menu of the library itself
        (the empty space)
        this reuses the actions from initToolBar()
        """

        self.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
        self.addAction(self.newNotebookAction)
        self.addAction(self.newFolderAction)

    def refresh(self):
        """ Refresh all elements of the frame """
        self.shelves.refresh()


class Editing(CustomFrame):
    r"""
    Direct access to the markup files will be there

    The left hand side will be the text within a tab widget, named as the
    notebook it belongs to.

    Contrary to the Library tab, this one will have an additional state, the
    active state, which will dictate on which file the window is open.

     _________  _________  _________
    / Library \/ Editing \/ Preview \
    |----------           ----------------------------
    |    --------------------------|                  |
    |   /|                         | [+] new entry    |
    |   N|                         | [ ] save document|
    |   1|                         | [ ] preview      |
    |   \|_________________________|                  |
    ---------------------------------------------------
    """
    # Launched when the previewer is desired
    loadNotebook = QtCore.Signal(str)

    def initUI(self):
        self.log.info("Starting UI init of %s" % self.__class__.__name__)

        # toolbar on top
        self.initToolBar()

        # Global horizontal layout
        hbox = QtGui.QHBoxLayout()

        # Create the tabbed widgets containing the text editors. The tabs will
        # appear on the left-hand side
        self.tabs = QtGui.QTabWidget(self)
        self.tabs.setTabPosition(QtGui.QTabWidget.West)

        # The loop is over all the notebooks in the **current** folder
        for notebook in self.info.notebooks:
            editor = TextEditor(self)
            # Set the source of the TextEditor to the desired notebook
            editor.setSource(os.path.join(self.info.level, notebook))
            # Add the text editor to the tabbed area
            self.tabs.addTab(editor, os.path.splitext(notebook)[0])

        hbox.addWidget(self.tabs)
        self.layout().addLayout(hbox)

        self.log.info("Finished UI init of %s" % self.__class__.__name__)

    def initToolBar(self):
        """initialize the toolbar for this view"""
        if not hasattr(self, 'toolbar'):
            self.toolbar = self.parent.addToolBar('Editing')
            self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            self.toolbar.setIconSize(self.toolbar.iconSize() * 0.7)
            self.toolbar.setVisible(False)

            # save the Text in the current notebook editor
            saveIcon = qtawesome.icon('fa.floppy-o')
            self.saveAction = QtGui.QAction(saveIcon, '&Save', self)
            self.saveAction.setIconText('&Save')
            self.saveAction.setShortcut('Ctrl+S')
            self.saveAction.triggered.connect(self.saveText)
            self.toolbar.addAction(self.saveAction)

            # reload the Text in the current notebook editor
            readIcon = qtawesome.icon('fa.refresh')
            self.readAction = QtGui.QAction(readIcon, '&Reload', self)
            self.readAction.setIconText('&Reload')
            self.readAction.setShortcut('Ctrl+R')
            self.readAction.triggered.connect(self.loadText)
            self.toolbar.addAction(self.readAction)

            # separator between general and notebook specific actions
            self.toolbar.addSeparator()

            # Create a new entry - new field in the current notebook
            newEntryIcon = qtawesome.icon('fa.plus-square')
            self.newEntryAction = QtGui.QAction(newEntryIcon, '&New entry',
                                                self)
            self.newEntryAction.setIconText('&New entry')
            self.newEntryAction.setShortcut('Ctrl+N')
            self.newEntryAction.triggered.connect(self.newEntry)
            self.toolbar.addAction(self.newEntryAction)

            # Edit in an exterior editor
            editIcon = qtawesome.icon('fa.pencil-square-o')
            self.editAction = QtGui.QAction(editIcon,
                                            'Edi&t (exterior editor)', self)
            self.editAction.setIconText('Edi&t (exterior editor)')
            self.editAction.setShortcut('Ctrl+T')
            self.editAction.triggered.connect(self.editExternal)
            self.toolbar.addAction(self.editAction)

            # Launch the previewing of the current notebook
            previewIcon = qtawesome.icon('fa.desktop')
            self.previewAction = QtGui.QAction(previewIcon,
                                               '&Preview notebook', self)
            self.previewAction.setIconText('&Preview notebook')
            self.previewAction.setShortcut('Ctrl+P')
            self.previewAction.triggered.connect(self.preview)
            self.toolbar.addAction(self.previewAction)

            # open file dialog to insert an image path
            imageInsertIcon = qtawesome.icon('fa.image')
            self.imageInsertAction = QtGui.QAction(imageInsertIcon,
                                                   '&Insert Image', self)
            self.imageInsertAction.setIconText('Insert Image')
            self.imageInsertAction.setShortcut('Ctrl+I')
            self.imageInsertAction.triggered.connect(self.insertImage)
            self.toolbar.addAction(self.imageInsertAction)

    def refresh(self):
        """Redraw the UI (time consuming...)"""
        self.clearUI()
        self.initUI()

    def switchNotebook(self, notebook):
        """switching tab to desired notebook"""
        self.log.info("switching to "+notebook)
        index = self.info.notebooks.index(notebook+EXTENSION)
        self.tabs.setCurrentIndex(index)

    def newEntry(self):
        """
        Open a form and store the results to the file

        .. note::
            this method does not save the file automatically

        """
        self.popup = NewEntry(self)
        # This will popup the popup
        ok = self.popup.exec_()
        # The return code is True if successful
        if ok:
            # Recover the three fields
            title = self.popup.title
            tags = self.popup.tags
            corpus = self.popup.corpus

            # Create the post
            post = tp.create_post_from_entry(title, tags, corpus)
            # recover the editor of the current widget, i.e. the open editor
            editor = self.tabs.currentWidget()
            # Append the text
            editor.appendText(post)

    def editExternal(self):  # pragma: no cover
        """edit active file in external editor"""
        # get the current file
        index = self.tabs.currentIndex()
        notebook = os.path.join(self.info.level, self.info.notebooks[index])
        # open the file in the external editor set by the user
        # if this fails, show a popup
        try:
            Popen([self.info.externalEditor, notebook])
            self.log.info('external editor opened for notebook %s' % notebook)
        except OSError as e:
            self.log.error('Execution of external editor failed: %s' % e)
            self.popup = QtGui.QMessageBox(self)
            self.popup.setIcon(QtGui.QMessageBox.Critical)
            self.popup.setWindowTitle('NoteOrganiser')
            self.popup.setText(
                "The external editor '%s' couldn't be opened." % (
                    self.info.externalEditor))
            self.popup.setInformativeText("%s" % e)
            self.popup.exec_()

    def preview(self):
        """
        Launch the previewing of the current notebook

        Fires the loadNotebook signal with the desired notebook as an
        argument.
        """
        index = self.tabs.currentIndex()
        notebook = self.info.notebooks[index]
        self.log.info('ask to preview notebook %s' % notebook)
        self.loadNotebook.emit(notebook)

    def zoomIn(self):
        """
        So far only applies to the inside editor, and not the global fonts

        """
        # recover the current editor
        editor = self.tabs.currentWidget()
        editor.zoomIn()

    def zoomOut(self):
        # recover the current editor
        editor = self.tabs.currentWidget()
        editor.zoomOut()

    def resetSize(self):
        # recover the current editor
        editor = self.tabs.currentWidget()
        editor.resetSize()

    def loadText(self):
        """reload the text in the current notebook"""
        notebook = self.tabs.currentWidget()
        notebook.loadText()

    def saveText(self):
        """save the text in the current notebook"""
        notebook = self.tabs.currentWidget()
        notebook.saveText()

    def insertImage(self):
        """
        Open a file dialog and insert the selected image path as markdown
        """
        self.popup = QtGui.QFileDialog()
        filename = self.popup.getOpenFileName(self,
                "select an image",
                "",
                "Image Files (*.png *.jpg *.bmp *.jpeg *.svg *.gif)" + \
                ";;all files (*.*)")

        # QFileDialog returns a tuple with filename and used filter
        if filename[0]:
            imagemarkdown = tp.create_image_markdown(filename[0])
            editor = self.tabs.currentWidget()
            editor.insertText(imagemarkdown)


class Preview(CustomFrame):
    r"""
    Preview of the markdown in html, with tag selection

    The left hand side will be an html window, displaying the whole notebook.
    On the right, a list of tags will be displayed.
    At some point, a calendar for date selection should also be displayed TODO

     _________  _________  _________
    / Library \/ Editing \/ Preview \
    |---------------------          ------------------
    |    --------------------------|                  |
    |    |                         | TAG1 TAG2 tag3   |
    |    |                         | tag4 ...         |
    |    |                         |                  |
    |    |_________________________| Calendar         |
    ---------------------------------------------------
    """
    # Launched when the editor is desired after failed conversion
    loadEditor = QtCore.Signal(str, str)

    def initLogic(self):
        """
        Create variables for storing local information

        """
        # Where to store the produced html pages
        self.website_root = os.path.join(self.info.level, '.website')
        # Where to store the temporary markdown files (maybe this step is not
        # necessary with pypandoc?)
        self.temp_root = os.path.join(self.info.level, '.temp')
        # Create the two folders if they do not already exist
        for path in (self.website_root, self.temp_root):
            if not os.path.isdir(path):
                os.mkdir(path)
        self.extracted_tags = od()
        self.filters = []

        # Shortcuts for resizing
        acceptShortcut = QtGui.QShortcut(
            QtGui.QKeySequence(self.tr("Ctrl+k")), self)
        acceptShortcut.activated.connect(self.zoomIn)

    def initUI(self):
        self.log.info("Starting UI init of %s" % self.__class__.__name__)
        self.layout().setDirection(QtGui.QBoxLayout.LeftToRight)

        # toolbar on top
        self.initToolBar()

        # Left hand side: html window
        self.web = QtWebKit.QWebView(self)

        # Set the css file. Note that the path to the css needs to be absolute,
        # somehow...
        path = os.path.abspath(os.path.dirname(__file__))
        self.css = os.path.join(path, 'assets', 'style', 'bootstrap.css')
        self.template = os.path.join(
            path, 'assets', 'style', 'bootstrap-blog.html')
        self.web.settings().setUserStyleSheetUrl(QtCore.QUrl.fromLocalFile(
            self.css))

        # The 1 stands for a stretch factor, set to 0 by default (seems to be
        # only for QWebView, though...
        self.layout().addWidget(self.web, 1)

        # Right hand side: Vertical layout for the tags inside a QScrollArea
        scrollArea = QtGui.QScrollArea()
        scrollArea.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scrollArea.verticalScrollBar().setFocusPolicy(QtCore.Qt.StrongFocus)

        # Need to create a dummy Widget, because QScrollArea can not accept a
        # layout, only a Widget
        dummy = QtGui.QWidget()

        vbox = QtGui.QVBoxLayout()
        # let size grow AND shrink
        vbox.setSizeConstraint(QtGui.QLayout.SetMinAndMaxSize)

        # search field for the buttons
        self.searchField = LineEditWithClearButton()
        self.searchField.textChanged.connect(self.filterButtons)
        self.searchField.returnPressed.connect(self.searchFieldReturn)
        self.searchField.setPlaceholderText('filter tags')
        self.searchField.setMaximumWidth(165)
        vbox.addWidget(self.searchField)

        # create a shortcut to jump into the search field
        if not hasattr(self, 'searchAction'):
            self.searchAction = QtGui.QAction(self)
            self.searchAction.setShortcut('Ctrl+F')
            self.searchAction.triggered.connect(self.onSearchAction)
            self.addAction(self.searchAction)

        self.tagButtons = []
        if self.extracted_tags:
            for key, value in six.iteritems(self.extracted_tags):
                tag = QtGui.QPushButton(key)
                tag.setFlat(False)
                tag.setMinimumSize(100, 40+5*value)
                tag.setMaximumWidth(165)
                tag.setCheckable(True)
                tag.clicked.connect(self.addFilter)
                self.tagButtons.append([key, tag])
                vbox.addWidget(tag)
        # Adding everything to the scroll area
        dummy.setLayout(vbox)
        scrollArea.setWidget(dummy)
        # Limit its width
        dummy.setFixedWidth(200)

        self.layout().addWidget(scrollArea)

        # Logging
        self.log.info("Finished UI init of %s" % self.__class__.__name__)

    def initToolBar(self):
        """initialize the toolbar for this view"""
        if not hasattr(self, 'toolbar'):
            self.toolbar = self.parent.addToolBar('Preview')
            self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            self.toolbar.setIconSize(self.toolbar.iconSize() * 0.7)
            self.toolbar.setVisible(False)

            # Reload Action
            reloadIcon = qtawesome.icon('fa.refresh')
            self.reloadAction = QtGui.QAction(reloadIcon, '&Reload', self)
            self.reloadAction.setIconText('&Reload')
            self.reloadAction.setShortcut('Ctrl+R')
            self.reloadAction.triggered.connect(self.reload)
            self.toolbar.addAction(self.reloadAction)

    def addFilter(self):
        """
        Filter out/in a certain tag

        From the status of the sender button, the associated tag will be
        added/removed from the filter.

        """
        sender = self.sender()
        if not sender.isFlat():
            if sender.isChecked():
                self.log.info('tag '+sender.text()+' added to the filter')
                self.filters.append(sender.text())
            else:
                self.log.info('tag '+sender.text()+' removed from the filter')
                self.filters.pop(self.filters.index(sender.text()))

            self.log.info("filter %s out of %s" % (
                ', '.join(self.filters), self.info.current_notebook))
            url, self.remaining_tags = self.convert(
                os.path.join(self.info.level, self.info.current_notebook),
                self.filters)
            # Grey out not useful buttons
            for key, button in self.tagButtons:
                if key in self.remaining_tags:
                    self.enableButton(button)
                else:
                    self.disableButton(button)
            self.setWebpage(url)

    def setWebpage(self, page):
        self.web.load(QtCore.QUrl.fromLocalFile(page))

    def loadNotebook(self, notebook):
        """
        Load a given markdown file as an html page

        """
        # TODO the dates should be recovered as well"
        self.initLogic()
        self.info.current_notebook = notebook
        self.log.info("Extracting markdown from %s" % notebook)

        try:
            url, tags = self.convert(
                os.path.join(self.info.level, notebook), ())
        except ValueError:  # pragma: no cover
            self.log.error("Markdown conversion failed, aborting")
            return False
        except SyntaxError:  # pragma: no cover
            self.log.warning("Modified Markdown syntax error, aborting")
            return False

        self.extracted_tags = tags
        # Finally, set the url of the web viewer to the desired page
        self.clearUI()
        self.initUI()
        self.setWebpage(url)
        return True

    def convert(self, path, tags):
        """
        Convert a notebook to html, with entries corresponding to the tags

        TODO: during the execution of this method, a check should be performed
        to verify if the file already exists, or maybe inside the convert
        function.

        Returns
        -------
        url : string
            path to the html page
        remaining_tags : OrderedDict
            dictionary of the remaining tags (the ones appearing in posts where
            all the selected tags where appearing, for further refinment)
        """
        # If the conversion fails, a popup should appear to inform the user
        # about it
        try:
            markdown, remaining_tags = tp.from_notes_to_markdown(
                path, input_tags=tags)
        except (IndexError, UnboundLocalError):  # pragma: no cover
            self.log.error("Conversion of %s to markdown failed" % path)
            self.popup = QtGui.QMessageBox(self)
            self.popup.setIcon(QtGui.QMessageBox.Critical)
            self.popup.setText(
                "<b>The conversion to markdown has unexpectedly failed!</b>")
            self.popup.setInformativeText("%s" % traceback.format_exc())
            ok = self.popup.exec_()
            if ok:
                raise ValueError("The conversion of the notebook failed")
        except ValueError as e:  # pragma: no cover
            self.log.warn(
                "There was an expected error in converting"
                " %s to markdown" % path)
            self.popup = QtGui.QMessageBox(self)
            self.popup.setIcon(QtGui.QMessageBox.Warning)
            self.popup.setText(
                "<b>Oups, you (probably) did a syntax error!</b>")
            self.popup.setInformativeText("%s" % e.message)
            ok = self.popup.exec_()
            if ok:
                raise SyntaxError("There was a syntax error")

        # save a temp. The basename will be modified to reflect the selection
        # of tags.
        base = os.path.basename(path)[:-len(EXTENSION)]
        if tags:
            base += '_'+'_'.join(tags)
        temp_path = os.path.join(self.temp_root, base+EXTENSION)
        self.log.debug('Creating temp file %s' % temp_path)
        with io.open(temp_path, 'w', encoding='utf-8') as temp:
            temp.write('\n'.join(markdown))

        # extra arguments for pandoc
        extra_args = ['--highlight-style', 'pygments', '-s', '-c', self.css,
                      '--template', self.template]

        # use TOC if enabled
        if self.info.use_TOC:
            extra_args.append('--toc')

        # Apply pandoc to this markdown file, from pypandoc thin wrapper, and
        # recover the html
        html = pa.convert(temp_path, 'html', encoding='utf-8',
                          extra_args=extra_args)

        # Convert the windows ending of lines to simple line breaks (\r\n to
        # \n)
        html = html.replace('\r\n', '\n')

        # Write the html to a file
        url = os.path.join(self.website_root, base+'.html')
        with io.open(url, 'w', encoding='utf-8') as page:
            page.write(html)

        return url, remaining_tags

    def disableButton(self, button):
        """ TODO: this should also alter the style """
        button.setFlat(True)
        button.setCheckable(False)

    def enableButton(self, button):
        """ TODO: this should also alter the style """
        button.setFlat(False)
        button.setCheckable(True)

    def zoomIn(self):
        multiplier = self.web.textSizeMultiplier()
        self.web.setTextSizeMultiplier(multiplier+0.1)

    def zoomOut(self):
        multiplier = self.web.textSizeMultiplier()
        self.web.setTextSizeMultiplier(multiplier-0.1)

    def resetSize(self):
        self.web.setTextSizeMultiplier(1)

    def onSearchAction(self):
        """Search shortcut was pressed. Set focus to the searchfield"""
        self.searchField.setFocus()

    def reload(self):
        """
        recompute and reload current html file

        keep currently activated filters
        """
        self.log.info('reloading the current preview')
        url, self.remaining_tags = self.convert(
            os.path.join(self.info.level, self.info.current_notebook),
            self.filters)
        for key, button in self.tagButtons:
            if key in self.remaining_tags:
                self.enableButton(button)
            else:
                self.disableButton(button)
        self.setWebpage(url)

    def filterButtons(self, filterText):
        """
        filter buttons by the text in the search field

        gets called when the text in the search field changes
        """
        for key, button in self.tagButtons:
            button.setVisible(fuzzySearch(filterText, key))

    def searchFieldReturn(self):
        """
        return key was pressed in the searchField

        hit the first visible tag button
        """
        button = [button for _, button in self.tagButtons
                  if button.isVisible()][0]
        button.click()


class Shelves(CustomFrame):
    """
    Custom display of the notebooks and folder

    """
    # Fired when a change is made, so that the Editing panel can also adapt
    refreshSignal = QtCore.Signal()
    # Fired when a notebook is clicked, to navigate to the editor.
    # TODO also define as a shift+click to directly open the previewer
    switchTabSignal = QtCore.Signal(str, str)
    previewSignal = QtCore.Signal(str)

    def initUI(self):
        """Create the physical shelves"""
        self.setFrameStyle(QtGui.QFrame.StyledPanel | QtGui.QFrame.Sunken)

        self.path = os.path.dirname(__file__)
        self.buttons = []

        # update state of UpAction when shelves get refreshed
        self.refreshSignal.connect(self.updateUpAction)

        # Store the number of objects per line, for faster redrawing on
        # resizing. Initially set to zero, it will, the first time, be set by
        # the method createLines, and then be compared to.
        self.objectsPerLine = 0
        # Left hand side: Vertical layout for the notebooks and folders
        scrollArea = VerticalScrollArea(self)

        # Need to create a dummy Widget, because QScrollArea can not accept a
        # layout, only a Widget
        dummy = QtGui.QWidget()

        vbox = QtGui.QVBoxLayout()
        grid = self.createLines()

        vbox.addLayout(grid)
        vbox.addStretch(1)
        dummy.setLayout(vbox)
        scrollArea.setWidget(dummy)

        self.layout().addWidget(scrollArea)

    def refresh(self):
        # Redraw the graphical interface.
        self.clearUI()
        self.initUI()

        # Broadcast a refreshSignal order
        self.refreshSignal.emit()

    def createNotebook(self):
        self.popup = NewNotebook(self)
        ok = self.popup.exec_()
        if ok:
            desired_name = self.info.notebooks[-1]
            self.log.info(desired_name+' is the desired name')
            file_name = desired_name
            # Create a file, containing only the title
            with io.open(os.path.join(self.info.level, file_name),
                         'w', encoding='utf-8') as notebook:
                clean_name = os.path.splitext(desired_name)[0]
                notebook.write(clean_name.capitalize()+'\n')
                notebook.write(''.join(['=' for _ in clean_name]))
                notebook.write('\n\n')
            # Refresh both the library and Editing tab.
            self.refresh()

    def createFolder(self):
        self.popup = NewFolder(self)
        ok = self.popup.exec_()
        if ok:
            desired_name = self.info.folders[-1]
            self.log.info(desired_name+' is the desired name')
            folder_name = desired_name
            # Create the folder
            try:
                os.mkdir(os.path.join(self.info.level, folder_name))
            except OSError:
                # If it already exists, continue
                pass
            # Change the level to the newly created folder, and send a refresh
            # TODO display a warning that an empty folder will be discared if
            # browsed out.
            folder_path = os.path.join(self.info.root, folder_name)
            self.info.notebooks, self.info.folders = search_folder_recursively(
                self.log, folder_path, self.info.display_empty)
            # Update the current level as the folder_path, and refresh the
            # content of the window
            self.info.level = folder_path
            self.refresh()

    def toggleDisplayEmpty(self):
        self.info.display_empty = not self.info.display_empty
        # Read again the current folder
        self.info.notebooks, self.info.folders = search_folder_recursively(
            self.log, self.info.level, self.info.display_empty)
        # save settings
        self.settings = QtCore.QSettings("audren", "NoteOrganiser")
        self.settings.setValue("display_empty", self.info.display_empty)
        self.refresh()

    @QtCore.Slot(str)
    def removeNotebook(self, notebook):
        """Remove the notebook"""
        self.log.info(
            'deleting %s from the shelves' % notebook)
        path = os.path.join(self.info.level, notebook+EXTENSION)

        # Assert that the file is empty, or ask for confirmation
        if os.stat(path).st_size != 0:
            self.reply = QtGui.QMessageBox.question(
                self, 'Message',
                "Are you sure you want to delete %s?" % notebook,
                QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
                QtGui.QMessageBox.No)
        else:
            self.reply = QtGui.QMessageBox.Yes

        if self.reply == QtGui.QMessageBox.Yes:
            os.remove(path)
            # Delete the reference to the notebook
            index = self.info.notebooks.index(notebook+EXTENSION)
            self.info.notebooks.pop(index)

            # Refresh the display
            self.refresh()

        else:
            self.log.info("Aborting")

    @QtCore.Slot(str)
    def removeFolder(self, folder):
        """Remove the folder, with confirmation if non-empty"""
        self.log.info(
            'deleting folder %s from the shelves' % folder)
        path = os.path.join(self.info.level, folder)

        # Assert that the folder is empty, or ask for confirmation
        if not all(os.path.isdir(e) and e[0] == '.' for e in os.listdir(path)):
            self.reply = QtGui.QMessageBox.question(
                self, 'Message',
                "%s still contains notebooks, " % folder +
                "are you sure you want to delete it?",
                QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
                QtGui.QMessageBox.No)
        else:
            self.reply = QtGui.QMessageBox.Yes

        if self.reply == QtGui.QMessageBox.Yes:
            shutil.rmtree(path, ignore_errors=True)
            # Delete the reference to the notebook
            index = self.info.folders.index(path)
            self.info.folders.pop(index)

            # Refresh the display
            self.refresh()

        else:
            self.log.info("Aborting")

    def notebookClicked(self):
        sender = self.sender()
        self.log.info('notebook '+sender.label+' button cliked')
        # Emit a signal asking for changing the tab
        self.switchTabSignal.emit('editing', sender.label)

    def folderClicked(self):
        sender = self.sender()
        self.log.info('folder '+sender.label+' button cliked')
        folder_path = os.path.join(self.info.root, sender.label)
        self.info.notebooks, self.info.folders = search_folder_recursively(
            self.log, folder_path, self.info.display_empty)
        # Update the current level as the folder_path, and refresh the content
        # of the window
        self.info.level = folder_path
        self.refresh()

    def upFolder(self):
        folder_path = os.path.dirname(self.info.level)
        self.info.notebooks, self.info.folders = search_folder_recursively(
            self.log, folder_path, self.info.display_empty)
        # Update the current level as the folder_path, and refresh the content
        # of the window
        self.info.level = folder_path
        self.refresh()

    def createLines(self):
        # Defining the icon size used
        self.size = 128

        # Create the lines array
        flow = FlowLayout()
        for notebook in self.info.notebooks:
            # distinguish between a notebook and a folder, stored as a tuple.
            # When encountering a folder, simply put a different image for the
            # moment.
            button = PicButton(
                QtGui.QPixmap(
                    os.path.join(self.path, 'assets',
                                 'notebook-%i.png' % self.size)),
                os.path.splitext(notebook)[0], 'notebook', self)
            button.setMinimumSize(self.size, self.size)
            button.setMaximumSize(self.size, self.size)
            button.clicked.connect(self.notebookClicked)
            button.deleteNotebookSignal.connect(self.removeNotebook)
            button.previewSignal.connect(self.previewNotebook)
            self.buttons.append(button)
            flow.addWidget(button)

        for folder in self.info.folders:
            button = PicButton(
                QtGui.QPixmap(
                    os.path.join(self.path, 'assets',
                                 'folder-%i.png' % self.size)),
                os.path.basename(folder), 'folder', self)
            button.setMinimumSize(self.size, self.size)
            button.setMaximumSize(self.size, self.size)
            button.clicked.connect(self.folderClicked)
            button.deleteFolderSignal.connect(self.removeFolder)
            self.buttons.append(button)
            flow.addWidget(button)

        self.flow = flow
        return flow

    @QtCore.Slot(str)
    def previewNotebook(self, notebook):
        """emit signal to preview the current notebook"""
        self.log.info("preview called for notebook %s" % notebook)
        path = os.path.join(self.info.level, notebook+EXTENSION)
        self.previewSignal.emit(path)

    def updateUpAction(self):
        """
        update the state of the toolbar action 'Up'

        active if not in root
        """
        self.parent.upAction.setDisabled(self.info.level == self.info.root)


class TextEditor(CustomFrame):
    """Custom text editor"""
    defaultFontSize = 14

    def initUI(self):
        """top menu bar and the text area"""
        # Text
        self.text = CustomTextEdit(self)
        self.text.setTabChangesFocus(True)

        # Font
        self.font = QtGui.QFont()
        self.font.setFamily("Inconsolata")
        self.font.setStyleHint(QtGui.QFont.Monospace)
        self.font.setFixedPitch(True)
        self.font.setPointSize(self.defaultFontSize)

        self.text.setFont(self.font)

        self.highlighter = ModifiedMarkdownHighlighter(self.text.document())

        # watch notebooks on the filesystem for changes
        self.fileSystemWatcher = QtCore.QFileSystemWatcher(self)

        self.layout().addWidget(self.text)

    def setSource(self, source):
        self.log.info("Reading %s" % source)
        self.source = source
        self.loadText()
        self.setupAutoRefresh(source)

    def loadText(self):
        if self.source:
            # Store the last cursor position
            oldCursor = self.text.textCursor()
            text = io.open(self.source, 'r', encoding='utf-8',
                           errors='replace').read()
            self.text.setText(text)
            self.text.setTextCursor(oldCursor)
            self.text.ensureCursorVisible()
            self.text.document().setModified(False)

    def saveText(self):
        self.log.info("Writing modifications to %s" % self.source)
        text = self.text.toPlainText()
        with io.open(self.source, 'w', encoding='utf-8') as file_handle:
            file_handle.write(text)

    def appendText(self, text):
        self.text.append('\n'+text)
        self.saveText()

    def insertText(self, text):
        self.text.insertPlainText(text)

    def zoomIn(self):
        size = self.font.pointSize()
        self.font.setPointSize(size+1)
        self.text.setFont(self.font)

    def zoomOut(self):
        size = self.font.pointSize()
        self.font.setPointSize(size-1)
        self.text.setFont(self.font)

    def resetSize(self):
        self.font.setPointSize(self.defaultFontSize)
        self.text.setFont(self.font)

    def setupAutoRefresh(self, source):
        """add current file to QFileSystemWatcher and refresh when needed"""
        self.fileSystemWatcher.addPath(source)
        self.fileSystemWatcher.fileChanged.connect(
            self.autoRefresh)
        self.log.info("added file %s to FileSystemWatcher" % source)

    @QtCore.Slot(str)
    def autoRefresh(self, path=''):
        """refresh editor when needed"""
        # only refresh if wanted and the user didn't modify the text in the
        # internal editor
        if self.info.refreshEditor:
            if not self.text.document().isModified():
                # wait some time for the change to finish
                time.sleep(0.1)
                self.loadText()
                self.fileSystemWatcher.removePath(path)
                self.fileSystemWatcher.addPath(path)
                self.log.info(
                    'editor source reloaded because the file changed')
            else:
                self.log.info(
                    "reload of editor source skipped because it's modified")


class CustomTextEdit(QtGui.QTextEdit):

    def toPlainText(self):
        text = QtGui.QTextEdit.toPlainText(self)
        if isinstance(text, bytes):
            text = str(text)
        return text
