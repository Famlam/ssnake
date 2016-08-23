#!/usr/bin/env python

# Copyright 2016 Bas van Meerten and Wouter Franssen

# This file is part of ssNake.
#
# ssNake is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ssNake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ssNake. If not, see <http://www.gnu.org/licenses/>.

from PyQt4 import QtGui, QtCore
import os
import sys
import json
import zipfile
import tempfile
import shutil
if sys.version_info >= (3, 0):
    from urllib.request import urlopen, urlretrieve
else:
    from urllib import urlopen, urlretrieve


class UpdateWindow(QtGui.QWidget):

    def __init__(self, parent):
        QtGui.QWidget.__init__(self, parent)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.Tool)
        self.father = parent
        try:
            req = urlopen('https://api.github.com/repos/smeerten/ssnake/tags')
            if sys.version_info >= (3, 0):
                info = json.loads(str(req.read().decode('utf-8')))
            else:
                info = json.loads(str(req.read()))
            req.close()
            self.nameList = [u'develop']
            self.urlList = [u'https://api.github.com/repos/smeerten/ssnake/zipball/develop']
            for i in range(len(info)):
                self.nameList.append(info[i]['name'])
                self.urlList.append(info[i]['zipball_url'])
        except:
            self.father.dispMsg("Could not connect to the server")
            return
        self.setWindowTitle("Update ssNake")
        layout = QtGui.QGridLayout(self)
        grid = QtGui.QGridLayout()
        layout.addLayout(grid, 0, 0, 1, 2)
        grid.addWidget(QtGui.QLabel("Update to version:"), 0, 0)
        self.versionDrop = QtGui.QComboBox(parent=self)
        self.versionDrop.addItems(self.nameList)
        self.versionDrop.setCurrentIndex(1)
        grid.addWidget(self.versionDrop, 1, 0)
        grid.addWidget(QtGui.QLabel("Current version: " + self.father.VERSION), 2, 0)
        cancelButton = QtGui.QPushButton("&Cancel")
        cancelButton.clicked.connect(self.closeEvent)
        layout.addWidget(cancelButton, 2, 0)
        okButton = QtGui.QPushButton("&Ok")
        okButton.clicked.connect(self.applyAndClose)
        layout.addWidget(okButton, 2, 1)
        layout.setColumnStretch(1, 1)
        self.show()
        self.father.menuDisable()

    def closeEvent(self, *args):
        self.father.menuEnable()
        self.deleteLater()

    def applyAndClose(self, *args):
        ssnake_location = os.path.dirname(os.path.dirname(__file__))
        message = "Update is going to replace all files in " + str(ssnake_location) + "\n ssNake needs to be restarted for the changes to take effect.\n Are you sure?"
        reply = QtGui.QMessageBox.question(self, 'Update', message, QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            self.father.menuEnable()
            self.deleteLater()
            progress = QtGui.QProgressDialog("Downloading...", "Cancel", 0, 3)
            progress.show()
            tempDir = tempfile.mkdtemp()
            filehandle, _ = urlretrieve(self.urlList[self.versionDrop.currentIndex()])
            progress.setValue(1)
            progress.setLabelText("Extracting...")
            zip_file = zipfile.ZipFile(filehandle, 'r')
            tmpPath = os.path.join(tempDir, zip_file.namelist()[0])
            zip_file.extractall(tempDir)
            progress.setValue(2)
            progress.setLabelText("Copying to destination...")
            shutil.rmtree(ssnake_location)
            shutil.move(tmpPath, ssnake_location)
            progress.setValue(2)
            progress.setLabelText("Cleaning up...")
            shutil.rmtree(tempDir)
            progress.close()
