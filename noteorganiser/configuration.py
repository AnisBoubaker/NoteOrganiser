"""
.. module:: configuration
    :synopsys: Recover the list of existing notebooks

.. moduleauthor:: Benjamin Audren <benjamin.audren@gmail.com>
"""
import os
from constants import EXTENSION


def initialise(logger):
    """
    Platform independent recovery of the main folder and notebooks

    """
    # Platform independent recovery of the home directory. It is always put as
    # a hidden folder, '.noteorganiser', in the unix tradition.
    home = os.path.expanduser("~")
    main = os.path.join(home, '.noteorganiser')

    # Recursively search the main folder for notebooks or folders of notebooks
    # It also checks if the folder ".noteorganiser" exists, and creates it
    # otherwise.
    # folders will contain all the non-empty folders in the main. The method
    # search_folder_recursively will be called again when the user wants to
    # explore also the contents of this folder
    notebooks, folders = search_folder_recursively(logger, main)

    # Return both the path to the folder where it is stored, and the list of
    # notebooks
    return main, notebooks, folders


def search_folder_recursively(logger, main):
    """
    Search the main folder for notebooks and folders with notebooks

    Note that the returned notebooks and folders are flat (that is, folders is
    not a list that then contains all the subnotebooks. They are discarded, and
    only loaded if the folder is then clicked on).
    """
    notebooks, folders = [], []
    if os.path.isdir(main):
        logger.info("Main folder existed already")
        # If yes, check if there are already some notebooks
        for elem in os.listdir(main):
            if os.path.isfile(os.path.join(main, elem)):
                # If it is a valid file, append it to notebooks
                if elem.find(EXTENSION) != -1:
                    logger.info("Found the file %s as a valid notebook" % elem)
                    notebooks.append(elem)
            elif os.path.isdir(os.path.join(main, elem)):
                # Otherwise, check the folder for valid files, and append it to
                # folders in case there are some inside.
                # If the folder is hidden (linux convention, with a leading
                # dot), ignore
                if elem[0] != '.':
                    temp, _ = search_folder_recursively(
                        logger, os.path.join(main, elem))
                    if temp:
                        folders.append(os.path.join(main, elem))
    else:
        logger.info("Main folder non-existant: creating it now")
        os.mkdir(main)
    return notebooks, folders


class Information(object):
    """storage of information across the application"""

    def __init__(self, logger, root, notebooks, folders):
        # Store the main variables
        # This is a reference to the global logger
        self.logger = logger
        # root stores the absolute path to the noteorganiser folder. It should
        # point to ~/.noteorganiser on a Unix type machine, and I don't know
        # where on a Windows.
        self.root = root
        # level stores the current path in the root folder (still in absolute
        # path, though)
        self.level = root

        # notebooks is the list of notebooks files (ending with EXTENSION),
        # found in "level". Folders contains the list of non-empty, non-hidden
        # folders in this directory.
        self.notebooks = notebooks
        self.folders = folders

        # Reference towards the currently edited/previewed notebook
        self.current_notebook = ''
        # Stores the SHA sum for every notebook, in order to avoid re-analyzing
        # the entire file for each filtering TODO
        self.sha = {}


if __name__ == "__main__":
    from logger import create_logger
    LOGGER = create_logger()
    print(initialise(LOGGER))
