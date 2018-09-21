#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2016 - 2018 Bas van Meerten and Wouter Franssen

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

import numpy as np
try:
    from PyQt5 import QtGui, QtCore, QtWidgets
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from PyQt4 import QtGui, QtCore
    from PyQt4 import QtGui as QtWidgets
    from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib as mpl
from matplotlib.figure import Figure
import scipy.optimize
import multiprocessing
import re
import time
import os
import copy
from safeEval import safeEval
from views import Current1D, CurrentContour
import widgetClasses as wc
import functions as func
import simFunctions as simFunc
import specIO as io
import spectrum as sc
from ssNake import SideFrame
import Czjzek as Czjzek

stopDict = {}  # Global dictionary with stopping commands for fits


def isfloat(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def checkLinkTuple(inp):
    if len(inp) == 2:
        inp += (1, 0, 0)
    elif len(inp) == 3:
        inp += (0, 0)
    return inp

class FittingException(sc.SpectrumException):
    pass

#############################################################################################


class TabFittingWindow(QtWidgets.QWidget):

    PRECIS = 4
    MINMETHOD = 'Powell'
    NUMFEVAL = 150

    def __init__(self, father, oldMainWindow):
        super(TabFittingWindow, self).__init__(father)
        self.father = father
        self.oldMainWindow = oldMainWindow
        self.subFitWindows = []
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setTabPosition(2)
        self.mainFitWindow = FittingWindow(father, oldMainWindow, self)
        self.current = self.mainFitWindow.current
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.closeTab)
        self.tabs.addTab(self.mainFitWindow, self.current.data.name)
        self.tabs.addTab(QtWidgets.QWidget(), '+Add data+')
        self.tabs.tabBar().setTabButton(0, QtWidgets.QTabBar.RightSide, QtWidgets.QLabel(''));
        self.tabs.tabBar().setTabButton(1, QtWidgets.QTabBar.RightSide, QtWidgets.QLabel(''));
        self.tabs.currentChanged.connect(self.changeTab)
        self.oldTabIndex = 0
        grid3 = QtWidgets.QGridLayout(self)
        grid3.addWidget(self.tabs, 0, 0)
        grid3.setColumnStretch(0, 1)
        grid3.setRowStretch(0, 1)

    def getTabNames(self):
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def getCurrentTabName(self):
        return self.tabs.tabText(self.tabs.currentIndex())

    def getParamTextList(self):
        parametertxtlist = self.mainFitWindow.paramframe.PARAMTEXT.copy()
        for subfit in self.subFitWindows:
            parametertxtlist.update(subfit.paramframe.PARAMTEXT)
        return parametertxtlist

    def addSpectrum(self):
        text = QtWidgets.QInputDialog.getItem(self, "Select data to add", "Workspace name:", self.father.workspaceNames, 0, False)
        if text[1]:
            self.subFitWindows.append(FittingWindow(self.father, self.father.workspaces[self.father.workspaceNames.index(text[0])], self, False))
            self.tabs.insertTab(self.tabs.count() - 1, self.subFitWindows[-1], str(text[0]))
            self.tabs.setCurrentIndex(len(self.subFitWindows))
            self.oldTabIndex = len(self.subFitWindows)

    def removeSpectrum(self, spec):
        num = self.subFitWindows.index(spec)
        self.tabs.setCurrentIndex(num) 
        self.oldTabIndex = num
        self.tabs.removeTab(num + 1)
        del self.subFitWindows[num]

    def changeTab(self, index):
        if index == self.tabs.count() - 1:
            self.tabs.setCurrentIndex(self.oldTabIndex) #Quickly set to old tab, to avoid showing the `add data' tab
            self.addSpectrum()
        else:
            self.oldTabIndex = index

    def closeTab(self, num):
        count = self.tabs.count()
        if num > 0:
            if num != count - 1:
                self.tabs.setCurrentIndex(num - 1) #Set one step lower to avoid 'addSpectrum' to be run
                self.tabs.removeTab(num)
                del self.subFitWindows[num - 1]

    def fit(self):
        value = self.mainFitWindow.paramframe.getFitParams()
        if value is None:
            return
        else:
            xax, data1D, guess, args, out = value
        xax = [xax]
        data1D = [data1D]
        out = [out]
        selectList = [slice(0, len(guess))]
        for i in range(len(self.subFitWindows)):
            xax_tmp, data1D_tmp, guess_tmp, args_tmp, out_tmp = self.subFitWindows[i].paramframe.getFitParams()
            out.append(out_tmp)
            xax.append(xax_tmp)
            selectList.append(slice(len(guess), len(guess) + len(guess_tmp)))
            data1D.append(data1D_tmp)
            guess += guess_tmp
            new_args = ()
            for n in range(len(args)):
                new_args += (args[n] + args_tmp[n],)
            args = new_args  # tuples are immutable
        new_args = (selectList,) + args
        allFitVal = self.mainFitWindow.paramframe.fit(xax, np.array(data1D), guess, new_args)
        if allFitVal is None:
            return
        allFitVal = allFitVal['x']
        fitVal = []
        for length in selectList:
            if allFitVal.ndim is 0:
                fitVal.append(np.array([allFitVal]))
            else:
                fitVal.append(allFitVal[length])
        args_out = []
        for n in range(len(args)):
            args_out.append([args[n][0]])
        self.mainFitWindow.paramframe.setResults(fitVal[0], args_out, out[0])
        for i in (range(len(self.subFitWindows))):
            args_out = []
            for n in range(len(args)):
                args_out.append([args[n][i + 1]])
            self.subFitWindows[i].paramframe.setResults(fitVal[i + 1], args_out, out[i + 1])

    def getNum(self, paramfitwindow):
        fitwindow = paramfitwindow.rootwindow
        if fitwindow is self.mainFitWindow:
            return 0
        else:
            return self.subFitWindows.index(fitwindow) + 1

    def getParams(self):
        params = [self.mainFitWindow.paramframe.getSimParams()]
        for window in self.subFitWindows:
            tmp_params = window.paramframe.getSimParams()
            params = np.append(params, [tmp_params], axis=0)
        if params[0] is None:
            return None
        return params
            
    def disp(self, *args, **kwargs):
        params = self.getParams()
        if params is None:
            return
        self.mainFitWindow.paramframe.disp(params, 0, *args, **kwargs)
        for i in range(len(self.subFitWindows)):
            self.subFitWindows[i].paramframe.disp(params, i + 1, *args, **kwargs)

    def get_masterData(self):
        return self.oldMainWindow.get_masterData()

    def get_current(self):
        return self.oldMainWindow.get_current()

    def kill(self):
        self.tabs.currentChanged.disconnect() #Prevent call for data on close
        self.mainFitWindow.kill()

##############################################################################


class ResultsExportWindow(QtWidgets.QWidget):

    def __init__(self, parent):
        super(ResultsExportWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.Tool)
        self.father = parent
        self.setWindowTitle("Export results")
        grid = QtWidgets.QGridLayout(self)

        self.parToWorkButton = QtWidgets.QPushButton("Parameters to Workspace")
        self.parToWorkButton.clicked.connect(self.parToWork)
        grid.addWidget(self.parToWorkButton, 0, 0)
        self.curvesToWorkButton = QtWidgets.QPushButton("Curves to Workspace")
        self.curvesToWorkButton.clicked.connect(self.curvesToWork)
        grid.addWidget(self.curvesToWorkButton, 1, 0)

        cancelButton = QtWidgets.QPushButton("&Cancel")
        cancelButton.clicked.connect(self.closeEvent)
        grid.addWidget(cancelButton, 2, 0)
        grid.setRowStretch(100, 1)
        self.show()
        self.setGeometry(self.frameSize().width() - self.geometry().width(), self.frameSize().height() - self.geometry().height(), 0, 0)

    def closeEvent(self, *args):
        self.deleteLater()

    def parToWork(self, *args):
        self.deleteLater()
        self.father.paramToWorkspaceWindow()

    def curvesToWork(self, *args):
        self.deleteLater()
        self.father.resultToWorkspaceWindow()

##################################################################################################

class FitCopySettingsWindow(QtWidgets.QWidget):

    def __init__(self, parent, single=False):
        super(FitCopySettingsWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.Tool)
        self.father = parent
        self.setWindowTitle("Settings")
        layout = QtWidgets.QGridLayout(self)
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid, 0, 0, 1, 2)
        self.allSlices = QtWidgets.QCheckBox("Export all slices")
        if not single:
            grid.addWidget(self.allSlices, 0, 0)
        self.original = QtWidgets.QCheckBox("Include original")
        self.original.setChecked(True)
        grid.addWidget(self.original, 1, 0)
        self.subFits = QtWidgets.QCheckBox("Include subfits")
        self.subFits.setChecked(True)
        grid.addWidget(self.subFits, 2, 0)
        self.difference = QtWidgets.QCheckBox("Include difference")
        grid.addWidget(self.difference, 3, 0)
        cancelButton = QtWidgets.QPushButton("&Cancel")
        cancelButton.clicked.connect(self.closeEvent)
        layout.addWidget(cancelButton, 2, 0)
        okButton = QtWidgets.QPushButton("&Ok", self)
        okButton.clicked.connect(self.applyAndClose)
        okButton.setFocus()
        layout.addWidget(okButton, 2, 1)
        grid.setRowStretch(100, 1)
        self.show()
        self.setGeometry(self.frameSize().width() - self.geometry().width(), self.frameSize().height() - self.geometry().height(), 0, 0)

    def closeEvent(self, *args):
        self.deleteLater()

    def applyAndClose(self, *args):
        self.deleteLater()
        self.father.resultToWorkspace([self.allSlices.isChecked(), self.original.isChecked(), self.subFits.isChecked(), self.difference.isChecked()])

##################################################################################################


class ParamCopySettingsWindow(QtWidgets.QWidget):

    def __init__(self, parent, paramNames, single=False):
        super(ParamCopySettingsWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.Tool)
        self.father = parent
        self.setWindowTitle("Parameters to export")
        layout = QtWidgets.QGridLayout(self)
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid, 0, 0, 1, 2)
        self.allSlices = QtWidgets.QCheckBox("Export all slices")
        if not single:
            grid.addWidget(self.allSlices, 0, 0)
        self.exportList = []
        for i in range(len(paramNames)):
            self.exportList.append(QtWidgets.QCheckBox(paramNames[i]))
            grid.addWidget(self.exportList[-1], i + 1, 0)
        cancelButton = QtWidgets.QPushButton("&Cancel")
        cancelButton.clicked.connect(self.closeEvent)
        layout.addWidget(cancelButton, 2, 0)
        okButton = QtWidgets.QPushButton("&Ok", self)
        okButton.clicked.connect(self.applyAndClose)
        okButton.setFocus()
        layout.addWidget(okButton, 2, 1)
        grid.setRowStretch(100, 1)
        self.show()
        self.setGeometry(self.frameSize().width() - self.geometry().width(), self.frameSize().height() - self.geometry().height(), 0, 0)

    def closeEvent(self, *args):
        self.deleteLater()

    def applyAndClose(self, *args):
        self.deleteLater()
        answers = []
        for checkbox in self.exportList:
            answers.append(checkbox.isChecked())
        self.father.paramToWorkspace(self.allSlices.isChecked(), answers)

################################################################################


class FittingWindow(QtWidgets.QWidget):
    # Inherited by the fitting windows

    def __init__(self, father, oldMainWindow, tabWindow, isMain=True):
        super(FittingWindow, self).__init__(father)
        self.isMain = isMain
        self.father = father
        self.oldMainWindow = oldMainWindow
        self.tabWindow = tabWindow
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        grid = QtWidgets.QGridLayout(self)
        grid.addWidget(self.canvas, 0, 0)
        self.current = self.tabWindow.CURRENTWINDOW(self, self.fig, self.canvas, self.oldMainWindow.get_current())
        self.paramframe = self.tabWindow.PARAMFRAME(self.current, self, isMain=self.isMain)
        grid.addWidget(self.paramframe, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setRowStretch(0, 1)
        self.grid = grid
        self.sideframe = FittingSideFrame(self)
        self.grid.addWidget(self.sideframe, 0, 1)
        self.canvas.mpl_connect('button_press_event', self.buttonPress)
        self.canvas.mpl_connect('button_release_event', self.buttonRelease)
        self.canvas.mpl_connect('motion_notify_event', self.pan)
        self.canvas.mpl_connect('scroll_event', self.scroll)

    def updAllFrames(self, *args):
        pass
        
    def fit(self):
        self.tabWindow.fit()
        self.paramframe.togglePick()

    def sim(self, *args, **kwargs):
        self.tabWindow.disp(**kwargs)
        self.paramframe.togglePick()

    def getCurrentTabName(self, *args, **kwargs):
        return self.tabWindow.getCurrentTabName(*args, **kwargs)

    def getTabNames(self, *args, **kwargs):
        return self.tabWindow.getTabNames(*args, **kwargs)

    def getParams(self, *args, **kwargs):
        return self.tabWindow.getParams(*args, **kwargs)

    def getNum(self, *args, **kwargs):
        return self.tabWindow.getNum(*args, **kwargs)

    def getParamTextList(self, *args, **kwargs):
        return self.tabWindow.getParamTextList(*args, **kwargs)

    def addSpectrum(self):
        self.tabWindow.addSpectrum()

    def removeSpectrum(self):
        self.tabWindow.removeSpectrum(self)

    def createNewData(self, data, axis, params=False, fitAll=False):
        masterData = self.get_masterData()
        if fitAll:
            if params:
                self.father.dataFromFit(data,
                                        masterData.filePath,
                                        np.append([masterData.freq[axis], masterData.freq[axis]], np.delete(masterData.freq, axis)),
                                        np.append([masterData.sw[axis], masterData.sw[axis]], np.delete(masterData.sw, axis)),
                                        np.append([False, False], np.delete(masterData.spec, axis)),
                                        np.append([False, False], np.delete(masterData.wholeEcho, axis)),
                                        np.append([None, None], np.delete(masterData.ref, axis)),
                                        None,
                                        None)
            else:
                self.father.dataFromFit(data,
                                        masterData.filePath,
                                        np.append(masterData.freq[axis], masterData.freq),
                                        np.append(masterData.sw[axis], masterData.sw),
                                        np.append(False, masterData.spec),
                                        np.append(False, masterData.wholeEcho),
                                        np.append(None, masterData.ref),
                                        None,
                                        None)
        else:
            if params:
                self.father.dataFromFit(data,
                                        masterData.filePath,
                                        [masterData.freq[axis], masterData.freq[axis]],
                                        [masterData.sw[axis], masterData.sw[axis]],
                                        [False, False],
                                        [False, False],
                                        [None, None],
                                        [np.arange(data.shape[0]), np.arange(data.shape[1])],
                                        0)
            else:
                self.father.dataFromFit(data,
                                        masterData.filePath,
                                        np.append(masterData.freq[axis], self.current.data1D.freq),
                                        np.append(masterData.sw[axis], self.current.data1D.sw),
                                        np.append(False, self.current.data1D.spec),
                                        np.append(False, self.current.data1D.wholeEcho),
                                        np.append(None, self.current.data1D.ref),
                                        [np.arange(len(data))] + self.current.data1D.xaxArray,
                                        0)

    def rename(self, name):
        self.canvas.draw()
        self.oldMainWindow.rename(name)

    def buttonPress(self, event):
        self.current.buttonPress(event)

    def buttonRelease(self, event):
        self.current.buttonRelease(event)

    def pan(self, event):
        self.current.pan(event)

    def scroll(self, event):
        self.current.scroll(event)

    def get_mainWindow(self):
        return self.oldMainWindow

    def get_masterData(self):
        return self.oldMainWindow.get_masterData()

    def get_current(self):
        return self.oldMainWindow.get_current()

    def kill(self):
        for i in reversed(range(self.grid.count())):
            self.grid.itemAt(i).widget().deleteLater()
        self.grid.deleteLater()
        self.current.kill()
        self.oldMainWindow.kill()
        del self.current
        del self.paramframe
        del self.fig
        del self.canvas
        self.deleteLater()

    def cancel(self):
        self.tabWindow.tabs.currentChanged.disconnect() #Disconnect tabs before closing, to avoid change index signal
        for i in reversed(range(self.grid.count())):
            self.grid.itemAt(i).widget().deleteLater()
        self.grid.deleteLater()
        del self.current
        del self.paramframe
        del self.canvas
        del self.fig
        self.father.closeFitWindow(self.oldMainWindow)
        self.deleteLater()

##############################################################################


class FittingSideFrame(SideFrame):

    FITTING = True


#################################################################################


class FitPlotFrame(Current1D):

    MARKER = ''
    LINESTYLE = '-'
    FITNUM = 10  # Standard number of fits

    def __init__(self, rootwindow, fig, canvas, current):
        self.data = current.data
        tmp = np.array(current.data.shape(), dtype=int)
        tmp = np.delete(tmp, self.fixAxes(current.axes))
        self.fitDataList = np.full(tmp, None, dtype=object)
        self.fitPickNumList = np.zeros(tmp, dtype=int)
        self.rootwindow = rootwindow
        super(FitPlotFrame, self).__init__(rootwindow, fig, canvas, current.data, current)

    def getRedLocList(self):
        return tuple(np.delete(self.locList, self.axes))
        
    def setSlice(self, axes, locList):
        self.rootwindow.paramframe.checkInputs()
        self.pickWidth = False
        super(FitPlotFrame, self).setSlice(axes, locList)
        self.rootwindow.paramframe.checkFitParamList(self.getRedLocList())
        self.rootwindow.paramframe.dispParams()
        self.rootwindow.paramframe.togglePick()

    def getData1D(self):
        return np.real(self.getDataType(self.data1D.getHyperData(0)))

    def showFid(self):
        extraX = []
        extraY = []
        self.locList = np.array(self.locList, dtype=int)
        if self.fitDataList[self.getRedLocList()] is not None:
            tmp = self.fitDataList[self.getRedLocList()]
            extraX.append(tmp[0])
            extraY.append(tmp[1])
            for i in range(len(tmp[2])):
                extraX.append(tmp[2][i])
                extraY.append(tmp[3][i])
        super(FitPlotFrame, self).showFid(extraX=extraX, extraY=extraY)

#################################################################################


class AbstractParamFrame(QtWidgets.QWidget):

    FITFUNC = None # Function used for fitting and simulation
    SINGLENAMES = []
    MULTINAMES = []
    EXTRANAMES = []
    TICKS = True  # Fitting parameters can be fixed by checkboxes
    FFT_AXES = () # Which axes should be transformed after simulation
    FFTSHIFT_AXES = () # Which axes should be transformed after simulation
    DIM = 1 # Number of dimensions of the fit

    def __init__(self, parent, rootwindow, isMain=True):
        super(AbstractParamFrame, self).__init__(rootwindow)
        self.parent = parent
        self.FITNUM = self.parent.FITNUM
        self.rootwindow = rootwindow
        self.isMain = isMain # display fitting buttons
        self.ticks = {key: [] for key in (self.SINGLENAMES + self.MULTINAMES)}
        self.entries = {key: [] for key in (self.SINGLENAMES + self.MULTINAMES + self.EXTRANAMES)}
        tmp = np.array(self.parent.data.shape(), dtype=int)
        tmp = np.delete(tmp, self.parent.axes)
        self.fitParamList = np.zeros(tmp, dtype=object)
        self.fitNumList = np.zeros(tmp, dtype=int)
        grid = QtWidgets.QGridLayout(self)
        self.setLayout(grid)
        self.axMult = self.parent.getAxMult(self.parent.spec(),
                                            self.parent.getAxType(),
                                            self.parent.getppm(),
                                            self.parent.freq(),
                                            self.parent.ref())
        if self.parent.spec() == 1:
            if self.parent.viewSettings["ppm"][-1]:
                self.axUnit = 'ppm'
            else:
                axUnits = ['Hz', 'kHz', 'MHz']
                self.axUnit = axUnits[self.parent.getAxType()]
        elif self.parent.spec() == 0:
            axUnits = ['s', 'ms', u"\u03bcs"]
            self.axUnit = axUnits[self.parent.getAxType()]
        self.frame1 = QtWidgets.QGridLayout()
        self.optframe = QtWidgets.QGridLayout()
        self.frame2 = QtWidgets.QGridLayout()
        self.frame3 = QtWidgets.QGridLayout()
        grid.addLayout(self.frame1, 0, 0)
        grid.addLayout(self.optframe, 0, 1)
        grid.addLayout(self.frame2, 0, 2)
        grid.addLayout(self.frame3, 0, 3)
        grid.setColumnStretch(10, 1)
        grid.setAlignment(QtCore.Qt.AlignLeft)
        self.frame1.setColumnStretch(10, 1)
        self.frame1.setAlignment(QtCore.Qt.AlignTop)
        self.optframe.setColumnStretch(21, 1)
        self.optframe.setRowStretch(21, 1)
        self.optframe.setAlignment(QtCore.Qt.AlignTop)
        self.frame2.setColumnStretch(self.FITNUM, 1)
        self.frame2.setAlignment(QtCore.Qt.AlignTop)
        self.frame3.setColumnStretch(20, 1)
        self.frame3.setAlignment(QtCore.Qt.AlignTop)
        simButton = QtWidgets.QPushButton("Sim")
        simButton.clicked.connect(self.rootwindow.sim)
        self.frame1.addWidget(simButton, 0, 0,1,1)
        if self.isMain:
            fitButton = QtWidgets.QPushButton("Fit")
            fitButton.clicked.connect(self.rootwindow.fit)
            self.frame1.addWidget(fitButton, 0, 1)
            self.stopButton = QtWidgets.QPushButton("Stop")
            self.stopButton.clicked.connect(self.stopMP)
            self.stopButton.setStyleSheet('background-color: green') 
            self.frame1.addWidget(self.stopButton, 0, 1)
            self.stopButton.hide()
            fitAllButton = QtWidgets.QPushButton("Fit all")
            fitAllButton.clicked.connect(self.fitAll)
            self.frame1.addWidget(fitAllButton, 1, 0)
            self.stopAllButton = QtWidgets.QPushButton("Stop all")
            self.stopAllButton.clicked.connect(self.stopAll)
            self.stopAllButton.setStyleSheet('background-color: green') 
            self.frame1.addWidget(self.stopAllButton, 1, 0)
            self.stopAllButton.hide()
            prefButton = QtWidgets.QPushButton("Preferences")
            prefButton.clicked.connect(self.createPrefWindow)
            self.frame1.addWidget(prefButton, 3, 1)
        self.process1 = None
        self.queue = None
        self.resetButton = QtWidgets.QPushButton("Reset")
        self.resetButton.clicked.connect(self.reset)
        self.frame1.addWidget(self.resetButton, 1, 1)
        copyParamsButton = QtWidgets.QPushButton("Copy parameters")
        copyParamsButton.clicked.connect(self.copyParams)
        self.frame1.addWidget(copyParamsButton, 2, 0,1,2)
        exportResultButton = QtWidgets.QPushButton("Export")
        exportResultButton.clicked.connect(self.exportResultWindow)
        self.frame1.addWidget(exportResultButton, 3, 0)
        if self.isMain:
            cancelButton = QtWidgets.QPushButton("&Cancel")
            cancelButton.clicked.connect(self.closeWindow)
        else:
            cancelButton = QtWidgets.QPushButton("&Delete")
            cancelButton.clicked.connect(self.rootwindow.removeSpectrum)
        self.frame1.addWidget(cancelButton, 4, 0, 1, 2)
        self.checkFitParamList(self.getRedLocList())

    def getRedLocList(self):
        return self.parent.getRedLocList()

    def togglePick(self):
        # Dummy function for fitting routines which require peak picking
        pass

    def reset(self):
        locList = self.getRedLocList()
        self.fitNumList[locList] = 0
        self.fitParamList[locList] = self.defaultValues(0)
        self.dispParams()
    
    def checkFitParamList(self, locList):
        locList = tuple(locList)
        if not self.fitParamList[locList]:
            self.fitParamList[locList] = self.defaultValues(0)

    def defaultValues(self, inp):
        if inp:
            return inp
        tmpVal = {key: None for key in (self.SINGLENAMES + self.MULTINAMES)}
        for name in self.SINGLENAMES:
            if name in self.DEFAULTS.keys():
                tmpVal[name] = self.DEFAULTS[name]
            else:
                tmpVal[name] = [0.0, False]
        for name in self.MULTINAMES:
            if name in self.DEFAULTS.keys():
                tmpVal[name] = np.repeat([np.array(self.DEFAULTS[name], dtype=object)], self.FITNUM, axis=0)
            else:
                tmpVal[name] = np.repeat([np.array([0.0, False], dtype=object)], self.FITNUM, axis=0)
        return tmpVal

    def closeWindow(self, *args):
        self.stopMP()
        self.rootwindow.cancel()

    def copyParams(self):
        self.checkInputs()
        locList = self.getRedLocList()
        self.checkFitParamList(locList)
        for elem in np.nditer(self.fitParamList, flags=["refs_ok"], op_flags=['readwrite']):
            elem[...] = copy.deepcopy(self.fitParamList[locList])
        for elem in np.nditer(self.fitNumList, flags=["refs_ok"], op_flags=['readwrite']):
            elem[...] = self.fitNumList[locList]

    def dispParams(self):
        locList = self.getRedLocList()
        val = self.fitNumList[locList] + 1
        for name in self.SINGLENAMES:
            if isinstance(self.fitParamList[locList][name][0], (float, int)):
                self.entries[name][0].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % self.fitParamList[locList][name][0])
            if self.TICKS:
                self.ticks[name][0].setChecked(self.fitParamList[locList][name][1])
        self.setNumExp()
        for i in range(self.FITNUM):
            for name in self.MULTINAMES:
                if isinstance(self.fitParamList[locList][name][i][0], (float, int)):
                    self.entries[name][i].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % self.fitParamList[locList][name][i][0])
                if self.TICKS:
                    self.ticks[name][i].setChecked(self.fitParamList[locList][name][i][1])
                if i < val:
                    if self.TICKS:
                        self.ticks[name][i].show()
                    self.entries[name][i].show()
                else:
                    if self.TICKS:
                        self.ticks[name][i].hide()
                    self.entries[name][i].hide()

    def setNumExp(self):
        locList = self.getRedLocList()
        self.numExp.setCurrentIndex(self.fitNumList[locList])

    def changeNum(self, *args):
        val = self.numExp.currentIndex() + 1
        locList = self.getRedLocList()
        self.fitNumList[locList] = self.numExp.currentIndex()
        for i in range(self.FITNUM):
            for name in self.MULTINAMES:
                if i < val:
                    if self.TICKS:
                        self.ticks[name][i].show()
                    self.entries[name][i].show()
                else:
                    if self.TICKS:
                        self.ticks[name][i].hide()
                    self.entries[name][i].hide()

    def checkInputs(self):
        locList = self.getRedLocList()
        numExp = self.getNumExp()
        for name in self.SINGLENAMES:
            if self.TICKS:
                self.fitParamList[locList][name][1] = self.ticks[name][0].isChecked()
            inp = safeEval(self.entries[name][0].text())
            if inp is None:
                return False
            elif isinstance(inp, float):
                self.entries[name][0].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % inp)
            else:
                self.entries[name][0].setText(str(inp))
            self.fitParamList[locList][name][0] = inp
        for i in range(numExp):
            for name in self.MULTINAMES:
                if self.TICKS:
                    self.fitParamList[locList][name][i][1] = self.ticks[name][i].isChecked()
                inp = safeEval(self.entries[name][i].text())
                if inp is None:
                    return False
                elif isinstance(inp, float):
                    self.entries[name][i].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % inp)
                else:
                    self.entries[name][i].setText(str(inp))
                self.fitParamList[locList][name][i][0] = inp
        return True

    def getNumExp(self):
        return self.numExp.currentIndex() + 1

    def getExtraParams(self, out):
        return (out, [])

    def getFitParams(self):
        if not self.checkInputs():
            raise FittingException("Fitting: One of the inputs is not valid")
        struc = {}
        for name in (self.SINGLENAMES + self.MULTINAMES):
            struc[name] = []
        guess = []
        argu = []
        numExp = self.getNumExp()
        locList = self.getRedLocList()
        out = {}
        for name in self.SINGLENAMES:
            out[name] = [0.0]
        for name in self.MULTINAMES:
            out[name] = np.zeros(numExp)
        for name in self.SINGLENAMES:
            if isfloat(self.entries[name][0].text()):
                if not self.fitParamList[locList][name][1]:
                    guess.append(float(self.entries[name][0].text()))
                    struc[name].append((1, len(guess) - 1))
                else:
                    out[name][0] = float(self.entries[name][0].text())
                    argu.append(out[name][0])
                    struc[name].append((0, len(argu) - 1))
            else:
                struc[name].append((2, checkLinkTuple(safeEval(self.entries[name][0].text()))))
        for i in range(numExp):
            for name in self.MULTINAMES:
                if isfloat(self.entries[name][i].text()):
                    if not self.fitParamList[locList][name][i][1]:
                        guess.append(float(self.entries[name][i].text()))
                        struc[name].append((1, len(guess) - 1))
                    else:
                        out[name][i] = float(self.entries[name][i].text())
                        argu.append(out[name][i])
                        struc[name].append((0, len(argu) - 1))
                else:
                    struc[name].append((2, checkLinkTuple(safeEval(self.entries[name][i].text()))))
        out, extraArgu = self.getExtraParams(out)
        argu.append(extraArgu)
        args = ([numExp], [struc], [argu], [self.parent.data1D.freq], [self.parent.data1D.sw], [self.axMult], [self.FFT_AXES], [self.FFTSHIFT_AXES], [self.SINGLENAMES], [self.MULTINAMES])
        return (self.parent.data1D.xaxArray[-self.DIM:], self.parent.getData1D(), guess, args, out)

    def fit(self, xax, data1D, guess, args):
        self.queue = multiprocessing.Queue()
        self.process1 = multiprocessing.Process(target=mpFit, args=(xax, data1D, guess, args, self.queue, self.FITFUNC, self.rootwindow.tabWindow.MINMETHOD, self.rootwindow.tabWindow.NUMFEVAL))
        self.process1.start()
        self.running = True
        self.stopButton.show()
        while self.running:
            if not self.queue.empty():
                self.running = False
            QtWidgets.qApp.processEvents()
            time.sleep(0.1)
        if self.queue is None:
            return
        fitVal = self.queue.get(timeout=2)
        self.stopMP()
        if fitVal is None:
            raise FittingException('Optimal parameters not found')
        elif isinstance(fitVal, str):
            raise FittingException(fitVal)
        return fitVal

    def setResults(self, fitVal, args, out):
        locList = self.getRedLocList()
        numExp = args[0][0]
        struc = args[1][0]
        for name in self.SINGLENAMES:
            if struc[name][0][0] == 1:
                self.fitParamList[locList][name][0] = fitVal[struc[name][0][1]]
        for i in range(numExp):
            for name in self.MULTINAMES:
                if struc[name][i][0] == 1:
                    self.fitParamList[locList][name][i][0] = fitVal[struc[name][i][1]]
        self.checkResults(numExp,struc)
        self.dispParams()
        self.rootwindow.sim()

    def checkResults(self,struc,numExp):
        #A placeholder for a function that checks the fit results (e.g. makes values absolute, etc)
        pass

    def stopMP(self, *args):
        if self.queue is not None:
            self.process1.terminate()
            self.queue.close()
            self.queue.join_thread()
            self.process1.join()
        self.queue = None
        self.process1 = None
        self.running = False
        self.stopButton.hide()

    def stopAll(self, *args):
        self.runningAll = False
        self.stopMP()
        self.stopAllButton.hide()

    def fitAll(self, *args):
        self.runningAll = True
        self.stopAllButton.show()
        tmp = np.array(self.parent.data.shape())
        tmp[self.parent.axes] = 1
        tmp2 = ()
        for i in tmp:
            tmp2 += (np.arange(i),)
        grid = np.array([i.flatten() for i in np.meshgrid(*tmp2)]).T
        for i in grid:
            QtWidgets.qApp.processEvents()
            if self.runningAll is False:
                break
            self.parent.setSlice(self.parent.axes, i)
            self.rootwindow.fit()
            self.rootwindow.sideframe.upd()
        self.stopAllButton.hide()

    def getSimParams(self):
        if not self.checkInputs():
            raise FittingException("Fitting: One of the inputs is not valid")
        numExp = self.getNumExp()
        out = {'extra' : []}
        for name in self.SINGLENAMES:
            out[name] = [0.0]
        for name in self.MULTINAMES:
            out[name] = [0.0] * numExp
        for name in self.SINGLENAMES:
            inp = safeEval(self.entries[name][0].text())
            out[name][0] = inp
        for i in range(numExp):
            for name in self.MULTINAMES:
                inp = safeEval(self.entries[name][i].text())
                out[name][i] = inp
        out, tmp = self.getExtraParams(out)
        return out

    def paramToWorkspaceWindow(self):
        paramNameList = self.SINGLENAMES + self.MULTINAMES
        if self.parent.data.ndim() == 1:
            single = True
        else:
            single = False
        ParamCopySettingsWindow(self, paramNameList, single)

    def paramToWorkspace(self, allSlices, settings):
        if not self.checkInputs():
            raise FittingException("Fitting: One of the inputs is not valid")
        paramNameList = np.array(self.SINGLENAMES + self.MULTINAMES, dtype=object)
        locList = self.getRedLocList()
        if not np.any(settings):
            return
        names = paramNameList[settings]
        params = self.rootwindow.getParams()
        if allSlices:
            num = self.rootwindow.getNum(self)
            maxNum = np.max(self.fitNumList)+1
            tmp = np.array(self.parent.data.shape(), dtype=int)
            tmp = np.delete(tmp, self.parent.axes)
            data = np.zeros((sum(settings), maxNum) + tuple(tmp))
            tmp2 = ()
            for i in tmp:
                tmp2 += (np.arange(i),)
            grid = np.array([i.flatten() for i in np.meshgrid(*tmp2)]).T
            for i in grid:
                self.checkFitParamList(tuple(i))
                for j in range(len(names)):
                    if names[j] in self.SINGLENAMES:
                        inp = self.fitParamList[tuple(i)][names[j]][0]
                        if isinstance(inp, tuple):
                            inp = checkLinkTuple(inp)
                            if inp[4] is num:
                                inp = inp[2] * self.fitParamList[tuple(i)][inp[0]][inp[1]][0] + inp[3]
                            else:
                                inp = inp[2] * params[inp[4]][inp[0]][inp[1]] + inp[3]
                        data[(j,) + (slice(None),) + tuple(i)].fill(inp)
                    else:
                        tmpInp = self.fitParamList[tuple(i)][names[j]].T[0][:(self.fitNumList[tuple(i)] + 1)]
                        for n in range(len(tmpInp)):
                            inp = tmpInp[n]
                            if isinstance(inp, tuple):
                                inp = checkLinkTuple(inp)
                                if inp[4] is num:
                                    inp = inp[2] * self.fitParamList[tuple(i)][inp[0]][inp[1]][0] + inp[3]
                                else:
                                    inp = inp[2] * params[inp[4]][inp[0]][inp[1]] + inp[3]
                            data[(j,) + (slice(None),) + tuple(i)][n] = inp
            self.rootwindow.createNewData(data, self.parent.axes[-1], True, True)
        else:
            data = np.zeros((sum(settings), self.fitNumList[locList] + 1))
            for i in range(len(names)):
                if names[i] in self.SINGLENAMES:
                    inp = self.fitParamList[locList][names[i]][0]
                    if isinstance(inp, tuple):
                        inp = checkLinkTuple(inp)
                        inp = inp[2] * params[inp[4]][inp[0]][inp[1]] + inp[3]
                    data[i].fill(inp)
                else:
                    tmpInp = self.fitParamList[locList][names[i]].T[0][:(self.fitNumList[locList] + 1)]
                    for j in range(len(tmpInp)):
                        inp = tmpInp[j]
                        if isinstance(inp, tuple):
                            inp = checkLinkTuple(inp)
                            inp = inp[2] * params[inp[4]][inp[0]][inp[1]] + inp[3]
                        data[i][j] = inp
            self.rootwindow.createNewData(data, self.parent.axes[-1], True)

    def exportResultWindow(self):
        ResultsExportWindow(self)

    def resultToWorkspaceWindow(self):
        if self.parent.data.ndim() == 1:
            single = True
        else:
            single = False
        FitCopySettingsWindow(self, single)

    def resultToWorkspace(self, settings):
        if settings is None:
            return
        if settings[0]:
            oldLocList = self.parent.locList
            maxNum = np.max(self.fitNumList) + 1
            extraLength = 1
            if settings[1]:
                extraLength += 1
            if settings[2]:
                extraLength += maxNum
            if settings[3]:
                extraLength += 1
            data = np.zeros((extraLength,) + self.parent.data.shape())
            tmp = np.array(self.parent.data.shape(), dtype=int)
            tmp[self.parent.axes] = 1
            tmp2 = ()
            for i in tmp:
                tmp2 += (np.arange(i),)
            grid = np.array([i.flatten() for i in np.meshgrid(*tmp2)]).T
            for i in grid:
                self.parent.setSlice(self.parent.axes, i)
                j = np.delete(i, self.parent.axes)
                data[(slice(None),) + tuple(j[:self.parent.axes[-1]]) + (slice(None),) + tuple(j[self.parent.axes[-1]:])] = self.prepareResultToWorkspace(settings, maxNum)
            self.parent.setSlice(self.parent.axes, oldLocList)
            self.rootwindow.createNewData(data, self.parent.axes[-1], False, True)
        else:
            data = self.prepareResultToWorkspace(settings)
            self.rootwindow.createNewData(data, self.parent.axes[-1], False)

    def prepareResultToWorkspace(self, settings, minLength=1):
        self.calculateResultsToWorkspace()
        locList = self.getRedLocList()
        fitData = self.parent.fitDataList[locList]
        if fitData is None:
            fitData = [np.zeros(len(self.parent.getData1D())), np.zeros(len(self.parent.getData1D())), np.zeros(len(self.parent.getData1D())), np.array([np.zeros(len(self.parent.getData1D()))] * minLength)]
        outCurvePart = []
        if settings[1]:
            outCurvePart.append(self.parent.getData1D())
        if settings[2]:
            for i in fitData[3]:
                outCurvePart.append(i)
            if len(fitData[3]) < minLength:
                for i in range(minLength - len(fitData[3])):
                    outCurvePart.append(np.zeros(len(self.parent.getData1D())))
        if settings[3]:
            outCurvePart.append(self.parent.getData1D() - fitData[1])
        outCurvePart.append(fitData[1])
        return np.array(outCurvePart)

    def calculateResultsToWorkspace(self, *args):
        # Some fitting methods need to recalculate the curves before exporting
        pass

    def createPrefWindow(self, *args):
        PrefWindow(self.rootwindow.tabWindow)

    def getDispX(self, *args):
        return self.parent.data.xaxArray[-self.DIM:]
        
    def disp(self, params, num, display=True):
        out = params[num]
        try:
            for name in self.SINGLENAMES:
                inp = out[name][0]
                if isinstance(inp, tuple):
                    inp = checkLinkTuple(inp)
                    out[name][0] = inp[2] * params[inp[4]][inp[0]][inp[1]] + inp[3]
            if len(self.MULTINAMES) == 0: #Abort if no names
                return
            numExp = len(out[self.MULTINAMES[0]])
            for i in range(numExp):
                for name in self.MULTINAMES:
                    inp = out[name][i]
                    if isinstance(inp, tuple):
                        inp = checkLinkTuple(inp)
                        out[name][i] = inp[2] * params[inp[4]][inp[0]][inp[1]] + inp[3]
                    if not np.isfinite(out[name][i]):
                        raise FittingException("Fitting: One of the inputs is not valid")
        except KeyError:
            raise FittingException("Fitting: One of the keywords is not correct")
        if display:
            tmpx = self.getDispX()
        else:
            tmpx = self.parent.data.xaxArray[-self.DIM:]
        if "offset" in out.keys():
            offset = out['offset'][0]
        else:
            offset = 0.0
        outCurve = offset * np.ones([len(item) for item in tmpx])
        if self.DIM == 1:
            plotx = tmpx[-1]
        else:
            plotx = tmpx
        outCurvePart = []
        x = []
        for i in range(len(out[self.MULTINAMES[0]])):
            x.append(plotx)
            inputVars = [out[name][0] for name in self.SINGLENAMES]
            inputVars += [out[name][i] for name in self.MULTINAMES]
            y = self.FITFUNC(tmpx, self.parent.data.freq, self.parent.data.sw, self.axMult, out['extra'], *inputVars)
            if y is None:
                raise FittingException("Fitting: The fitting function didn't output anything")
            y = np.real(np.fft.fftshift(np.fft.fftn(y, axes=self.FFT_AXES), axes=self.FFTSHIFT_AXES))
            outCurvePart.append(offset + y)
            outCurve += y
        locList = self.getRedLocList()
        self.parent.fitDataList[locList] = [plotx, outCurve, x, outCurvePart]
        if display:
            self.parent.showFid()

##############################################################################

def lstSqrs(dataList, *args):
    simData = fitFunc(*args)
    costValue = 0
    for i in range(len(dataList)):
        costValue += np.sum((dataList[i] - simData[i])**2)
    return costValue

def mpFit(xax, data1D, guess, args, queue, func, minmethod, numfeval):
    try:
        fitVal = scipy.optimize.minimize(lambda *param: lstSqrs(data1D, func, param, xax, args), guess, method=minmethod, options = {'maxfev': numfeval})
    except simFunc.SimException as e:
        fitVal = str(e)
    except Exception:
        fitVal = None
    queue.put(fitVal)

def fitFunc(func, params, allX, args):
    params = params[0]
    specSlices = args[0]
    allParam = []
    for length in specSlices:
        allParam.append(params[length])
    allStruc = args[2]
    allArgu = args[3]
    fullTestFunc = []
    for n in range(len(allX)):
        x = allX[n]
        testFunc = np.zeros([len(item) for item in x], dtype=complex)
        param = allParam[n]
        numExp = args[1][n]
        struc = allStruc[n]
        argu = allArgu[n]
        extra = argu[-1]
        freq = args[4][n]
        sw = args[5][n]
        axMult = args[6][n]
        fft_axes = args[7][n]
        fftshift_axes = args[8][n]
        singleNames = args[9][n]
        multiNames = args[10][n]
        parameters = {}
        try:
            for name in singleNames:
                if struc[name][0][0] == 1:
                    parameters[name] = param[struc[name][0][1]]
                elif struc[name][0][0] == 0:
                    parameters[name] = argu[struc[name][0][1]]
                else:
                    altStruc = struc[name][0][1]
                    if struc[altStruc[0]][altStruc[1]][0] == 1:
                        parameters[name] = altStruc[2] * allParam[altStruc[4]][struc[altStruc[0]][altStruc[1]][1]] + altStruc[3]
                    elif struc[altStruc[0]][altStruc[1]][0] == 0:
                        parameters[name] = altStruc[2] * allArgu[altStruc[4]][struc[altStruc[0]][altStruc[1]][1]] + altStruc[3]
            for i in range(numExp):
                for name in multiNames:
                    if struc[name][i][0] == 1:
                        parameters[name] = param[struc[name][i][1]]
                    elif struc[name][i][0] == 0:
                        parameters[name] = argu[struc[name][i][1]]
                    else:
                        altStruc = struc[name][i][1]
                        strucTarget = allStruc[altStruc[4]]
                        if strucTarget[altStruc[0]][altStruc[1]][0] == 1:
                            parameters[name] = altStruc[2] * allParam[altStruc[4]][strucTarget[altStruc[0]][altStruc[1]][1]] + altStruc[3]
                        elif strucTarget[altStruc[0]][altStruc[1]][0] == 0:
                            parameters[name] = altStruc[2] * allArgu[altStruc[4]][strucTarget[altStruc[0]][altStruc[1]][1]] + altStruc[3]
                inputVars = [parameters[name] for name in singleNames]
                inputVars += [parameters[name] for name in multiNames]
                testFunc += func(x, freq, sw, axMult, extra, *inputVars)
            testFunc = np.real(np.fft.fftshift(np.fft.fftn(testFunc, axes=fft_axes), axes=fftshift_axes))
        except KeyError:
            raise(simFunc.SimException("Fitting: One of the keywords is not correct"))
        if "offset" in parameters.keys():
            testFunc += parameters['offset']
        fullTestFunc.append(testFunc)
    return fullTestFunc

##############################################################################


class PrefWindow(QtWidgets.QWidget):

    METHODLIST = ['Powell', 'Nelder-Mead']

    def __init__(self, parent):
        super(PrefWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.Tool)
        self.father = parent
        self.setWindowTitle("Preferences")
        layout = QtWidgets.QGridLayout(self)
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid, 0, 0, 1, 2)
        grid.addWidget(wc.QLabel("Min. method:"), 0, 0)
        self.minmethodBox = QtWidgets.QComboBox(self)
        self.minmethodBox.addItems(self.METHODLIST)
        self.minmethodBox.setCurrentIndex(self.METHODLIST.index(self.father.MINMETHOD))
        grid.addWidget(self.minmethodBox, 0, 1)
        grid.addWidget(wc.QLabel("Significant digits:"), 1, 0)
        self.precisBox = QtWidgets.QSpinBox(self)
        self.precisBox.setValue(self.father.PRECIS)
        grid.addWidget(self.precisBox, 1, 1)
        grid.addWidget(wc.QLabel("# evaluations:"), 2, 0)
        self.numFevalBox = QtWidgets.QSpinBox(self)
        self.numFevalBox.setMaximum(100000)
        self.numFevalBox.setMinimum(1)
        self.numFevalBox.setValue(self.father.NUMFEVAL)
        grid.addWidget(self.numFevalBox, 2, 1)
        cancelButton = QtWidgets.QPushButton("&Cancel")
        cancelButton.clicked.connect(self.closeEvent)
        layout.addWidget(cancelButton, 4, 0)
        okButton = QtWidgets.QPushButton("&Ok", self)
        okButton.clicked.connect(self.applyAndClose)
        okButton.setFocus()
        layout.addWidget(okButton, 4, 1)
        grid.setRowStretch(100, 1)
        self.show()
        self.setGeometry(self.frameSize().width() - self.geometry().width(), self.frameSize().height() - self.geometry().height(), 0, 0)

    def closeEvent(self, *args):
        self.deleteLater()

    def applyAndClose(self, *args):
        self.father.PRECIS = self.precisBox.value()
        self.father.MINMETHOD = self.METHODLIST[self.minmethodBox.currentIndex()]
        self.father.NUMFEVAL = self.numFevalBox.value()
        self.closeEvent()

##############################################################################


class RelaxWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = RelaxFrame
        self.PARAMFRAME = RelaxParamFrame
        super(RelaxWindow, self).__init__(father, oldMainWindow)

#################################################################################


class RelaxFrame(FitPlotFrame):

    MARKER = 'o'
    LINESTYLE = 'none'
    FITNUM = 4  # Maximum number of fits

#################################################################################


class RelaxParamFrame(AbstractParamFrame):

    SINGLENAMES = ['amp', 'const']
    MULTINAMES = ['coeff', 't']
    PARAMTEXT = {'amp': 'Amplitude', 'const': 'Constant', 'coeff': 'Coefficient', 't': 'Relaxation time'}
    
    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.relaxationFunc
        self.fullInt = np.max(parent.getData1D())
        self.DEFAULTS = {'amp': [self.fullInt, False], 'const': [1.0, False], 'coeff': [-1.0, False], 't': [1.0, False]}
        self.extraDefaults = {'xlog': False, 'ylog': False}
        super(RelaxParamFrame, self).__init__(parent, rootwindow, isMain)
        locList = self.getRedLocList()
        self.frame2.addWidget(wc.QLabel("Amplitude:"), 0, 0, 1, 2)
        self.ticks['amp'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['amp'][-1], 1, 0)
        self.entries['amp'].append(wc.FitQLineEdit(self, 'amp', ('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % self.fitParamList[locList]['amp'][0]))
        self.frame2.addWidget(self.entries['amp'][-1], 1, 1)
        self.frame2.addWidget(wc.QLabel("Constant:"), 2, 0, 1, 2)
        self.ticks['const'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['const'][-1], 3, 0)
        self.entries['const'].append(wc.FitQLineEdit(self, 'const', ('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % self.fitParamList[locList]['const'][0]))
        self.frame2.addWidget(self.entries['const'][-1], 3, 1)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems(['1', '2', '3', '4'])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel("Coefficient:"), 1, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel("T [s]:"), 1, 2, 1, 2)
        self.xlog = QtWidgets.QCheckBox('x-log')
        self.xlog.stateChanged.connect(self.setLog)
        self.optframe.addWidget(self.xlog, 0, 0, QtCore.Qt.AlignTop)
        self.ylog = QtWidgets.QCheckBox('y-log')
        self.ylog.stateChanged.connect(self.setLog)
        self.optframe.addWidget(self.ylog, 1, 0, QtCore.Qt.AlignTop)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j], ('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % self.fitParamList[locList][self.MULTINAMES[j]][i][0]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def reset(self):
        self.xlog.setChecked(self.extraDefaults['xlog'])
        self.ylog.setChecked(self.extraDefaults['ylog'])
        super(RelaxParamFrame, self).reset()

    def setLog(self, *args):
        self.parent.setLog(self.xlog.isChecked(), self.ylog.isChecked())
        self.rootwindow.sim()

    def getExtraParams(self, out):
        out['extra'] = []
        return (out, out['extra'])
    
    def calculateResultsToWorkspace(self):
        self.rootwindow.sim(display=False)

    def getDispX(self, *args):
        numCurve = 256  # number of points in output curve
        realx = self.parent.xax()
        minx = min(realx)
        maxx = max(realx)
        if self.xlog.isChecked() and (minx > 0) and (maxx > 0):
            x = np.logspace(np.log(minx), np.log(maxx), numCurve)
        else:
            x = np.linspace(minx, maxx, numCurve)
        return [x]


    def checkResults(self,numExp,struc):
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['t'][i][0] == 1:
                self.fitParamList[locList]['t'][i][0] = abs(self.fitParamList[locList]['t'][i][0])


##############################################################################


class DiffusionWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = RelaxFrame
        self.PARAMFRAME = DiffusionParamFrame
        super(DiffusionWindow, self).__init__(father, oldMainWindow)

#################################################################################


class DiffusionParamFrame(AbstractParamFrame):

    SINGLENAMES = ['amp', 'const']
    MULTINAMES = ['coeff', 'd']
    PARAMTEXT = {'amp': 'Amplitude', 'const': 'Constant', 'coeff': 'Coefficient', 'd': 'Diffusion constant'}
    
    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.diffusionFunc
        self.fullInt = np.max(parent.getData1D())
        self.DEFAULTS = {'amp': [self.fullInt, False], 'const': [0.0, True], 'coeff': [1.0, False], 'd': [1.0e-9, False]}
        self.extraDefaults = {'xlog': False, 'ylog': False, 'gamma': "42.576", 'delta': '1.0', 'triangle': '1.0'}
        super(DiffusionParamFrame, self).__init__(parent, rootwindow, isMain)
        locList = self.getRedLocList()
        self.optframe.addWidget(wc.QLabel(u"γ [MHz/T]:"), 0, 1)
        self.gammaEntry = wc.QLineEdit()
        self.optframe.addWidget(self.gammaEntry, 1, 1)
        self.optframe.addWidget(wc.QLabel(u"δ [s]:"), 2, 1)
        self.deltaEntry = wc.QLineEdit()
        self.optframe.addWidget(self.deltaEntry, 3, 1)
        self.optframe.addWidget(wc.QLabel(u"Δ [s]:"), 4, 1)
        self.triangleEntry = wc.QLineEdit()
        self.optframe.addWidget(self.triangleEntry, 5, 1)
        self.frame2.addWidget(wc.QLabel("Amplitude:"), 0, 0, 1, 2)
        self.ticks['amp'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['amp'][-1], 1, 0)
        self.entries['amp'].append(wc.FitQLineEdit(self, 'amp', ('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % np.max(self.parent.getData1D())))
        self.frame2.addWidget(self.entries['amp'][-1], 1, 1)
        self.frame2.addWidget(wc.QLabel("Constant:"), 2, 0, 1, 2)
        self.ticks['const'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['const'][-1], 3, 0)
        self.entries['const'].append(wc.FitQLineEdit(self, 'const', "0.0"))
        self.frame2.addWidget(self.entries['const'][-1], 3, 1)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems(['1', '2', '3', '4'])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel("Coefficient:"), 1, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel("D [m^2/s]:"), 1, 2, 1, 2)
        self.frame3.setColumnStretch(20, 1)
        self.frame3.setAlignment(QtCore.Qt.AlignTop)
        self.xlog = QtWidgets.QCheckBox('x-log')
        self.xlog.stateChanged.connect(self.setLog)
        self.optframe.addWidget(self.xlog, 0, 0)
        self.ylog = QtWidgets.QCheckBox('y-log')
        self.ylog.stateChanged.connect(self.setLog)
        self.optframe.addWidget(self.ylog, 1, 0)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j], ''))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def reset(self):
        self.xlog.setChecked(self.extraDefaults['xlog'])
        self.ylog.setChecked(self.extraDefaults['ylog'])
        self.gammaEntry.setText(self.extraDefaults['gamma'])
        self.deltaEntry.setText(self.extraDefaults['delta'])
        self.triangleEntry.setText(self.extraDefaults['triangle'])
        super(DiffusionParamFrame, self).reset()

    def setLog(self, *args):
        self.parent.setLog(self.xlog.isChecked(), self.ylog.isChecked())
        self.rootwindow.sim()

    def getExtraParams(self, out):
        gamma = safeEval(self.gammaEntry.text())
        delta = safeEval(self.deltaEntry.text())
        triangle = safeEval(self.triangleEntry.text())
        out['extra'] = [gamma, delta, triangle]
        return (out, out['extra'])

    def calculateResultsToWorkspace(self):
        self.rootwindow.sim(display=False)

    def getDispX(self, *args):
        numCurve = 256  # number of points in output curve
        realx = self.parent.xax()
        minx = min(realx)
        maxx = max(realx)
        if self.xlog.isChecked() and (minx > 0) and (maxx > 0):
            x = np.logspace(np.log(minx), np.log(maxx), numCurve)
        else:
            x = np.linspace(minx, maxx, numCurve)
        return [x]

    def checkResults(self,numExp,struc):
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['d'][i][0] == 1:
                self.fitParamList[locList]['d'][i][0] = abs(self.fitParamList[locList]['d'][i][0])

##############################################################################


class PeakDeconvWindow(TabFittingWindow):
    
    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = PeakDeconvFrame
        self.PARAMFRAME = PeakDeconvParamFrame
        super(PeakDeconvWindow, self).__init__(father, oldMainWindow)

#################################################################################


class PeakDeconvFrame(FitPlotFrame):
    
    FITNUM = 10

    def togglePick(self, var):
        self.peakPickReset()
        if var == 1 and self.fitPickNumList[self.getRedLocList()] < self.FITNUM:
            self.peakPickFunc = lambda pos, self=self: self.pickDeconv(pos)
            self.peakPick = True
        else:
            self.peakPickFunc = None
            self.peakPick = False

    def pickDeconv(self, pos):
        locList = self.getRedLocList()
        pickNum = self.fitPickNumList[locList]
        if self.pickWidth:
            axMult = self.getAxMult(self.spec(), self.getAxType(), self.getppm(), self.freq(), self.ref())
            width = (2 * abs(float(self.rootwindow.paramframe.entries['pos'][pickNum].text()) - pos[1])) / self.getAxMult(self.spec(), self.getAxType(), self.getppm(), self.freq(), self.ref())
            self.rootwindow.paramframe.entries['amp'][pickNum].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % (float(self.rootwindow.paramframe.entries['amp'][pickNum].text()) * width))
            self.rootwindow.paramframe.entries['lor'][pickNum].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % abs(width))
            self.fitPickNumList[locList] += 1
            self.pickWidth = False
            self.rootwindow.sim()
        else:
            self.rootwindow.paramframe.entries['pos'][pickNum].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % pos[1])
            left = pos[0] - self.FITNUM
            if left < 0:
                left = 0
            right = pos[0] + self.FITNUM
            if right >= self.len():
                right = self.len() - 1
            self.rootwindow.paramframe.entries['amp'][pickNum].setText(('%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g') % (pos[2] * np.pi * 0.5))
            if pickNum < self.FITNUM:
                self.rootwindow.paramframe.numExp.setCurrentIndex(pickNum)
                self.rootwindow.paramframe.changeNum()
            self.pickWidth = True
        if pickNum < self.FITNUM:
            self.peakPickFunc = lambda pos, self=self: self.pickDeconv(pos)
            self.peakPick = True

#################################################################################


class PeakDeconvParamFrame(AbstractParamFrame):

    FFT_AXES = (0,) # Which axes should be transformed after simulation
    FFTSHIFT_AXES = (0,) # Which axes should be transformed after simulation
    SINGLENAMES = ['offset', 'mult']
    MULTINAMES = ['pos', 'amp', 'lor', 'gauss']
    PARAMTEXT = {'offset': 'Offset', 'mult': 'Multiplier', 'pos': 'Position', 'amp': 'Integral', 'lor': 'Lorentz', 'gauss': 'Gauss'}
    
    def __init__(self, parent, rootwindow, isMain=True):
        self.fullInt = np.sum(parent.getData1D()) * parent.sw() / float(len(parent.getData1D()))
        self.FITFUNC = simFunc.peakSim
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'pos': [0.0, False], 'amp': [self.fullInt, False], 'lor': [1.0, False], 'gauss': [0.0, True]}
        super(PeakDeconvParamFrame, self).__init__(parent, rootwindow, isMain)
        self.pickTick = QtWidgets.QCheckBox("Pick")
        self.pickTick.stateChanged.connect(self.togglePick)
        self.frame1.addWidget(self.pickTick, 0, 2)
        self.frame2.addWidget(wc.QLabel("Offset:"), 0, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['offset'][0], 1, 0)
        self.entries['offset'].append(wc.FitQLineEdit(self, 'offset', "0.0"))
        self.frame2.addWidget(self.entries['offset'][0], 1, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 2, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['mult'][0], 3, 0)
        self.entries['mult'].append(wc.FitQLineEdit(self, 'mult', "1.0"))
        self.frame2.addWidget(self.entries['mult'][0], 3, 1)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel("Position [" + self.axUnit + "]:"), 1, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel("Integral:"), 1, 2, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz [Hz]:"), 1, 4, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss [Hz]:"), 1, 6, 1, 2)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()
        
    def reset(self):
        locList = self.getRedLocList()
        self.pickTick.setChecked(True)
        self.togglePick()
        self.parent.pickWidth = False
        self.parent.fitPickNumList[locList] = 0
        super(PeakDeconvParamFrame, self).reset()

    def togglePick(self):
        self.parent.togglePick(self.pickTick.isChecked())

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['lor'][i][0] == 1:
                self.fitParamList[locList]['lor'][i][0] = abs(self.fitParamList[locList]['lor'][i][0])
           if struc['gauss'][i][0] == 1:
                self.fitParamList[locList]['gauss'][i][0] = abs(self.fitParamList[locList]['gauss'][i][0])



##############################################################################


class CsaDeconvWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = CsaDeconvFrame
        self.PARAMFRAME = CsaDeconvParamFrame
        super(CsaDeconvWindow, self).__init__(father, oldMainWindow)

#####################################################################################


class CsaDeconvFrame(FitPlotFrame):

    FITNUM = 10  # Maximum number of fits

    def __init__(self, rootwindow, fig, canvas, current):
        self.pickNum = 0
        self.pickNum2 = 0
        super(CsaDeconvFrame, self).__init__(rootwindow, fig, canvas, current)

    def togglePick(self, var):
        self.peakPickReset()
        if var == 1:
            self.peakPickFunc = lambda pos, self=self: self.pickDeconv(pos)
            self.peakPick = True
        else:
            self.peakPickFunc = None
            self.peakPick = False

    def pickDeconv(self, pos):
        printStr = "%#." + str(self.rootwindow.tabWindow.PRECIS) + "g"
        axMult = self.getAxMult(self.spec(), self.getAxType(), self.getppm(), self.freq(), self.ref())
        if self.pickNum2 == 0:
            if self.pickNum < self.FITNUM:
                self.rootwindow.paramframe.numExp.setCurrentIndex(self.pickNum)
                self.rootwindow.paramframe.changeNum()
            self.rootwindow.paramframe.entries['t11'][self.pickNum].setText(printStr % (self.xax()[pos[0]] * axMult))
            self.pickNum2 = 1
        elif self.pickNum2 == 1:
            self.rootwindow.paramframe.entries['t22'][self.pickNum].setText(printStr % (self.xax()[pos[0]] * axMult))
            self.pickNum2 = 2
        elif self.pickNum2 == 2:
            self.rootwindow.paramframe.entries['t33'][self.pickNum].setText(printStr % (self.xax()[pos[0]] * axMult))
            self.pickNum2 = 0
            self.pickNum += 1
        if self.pickNum < self.FITNUM:
            self.peakPickFunc = lambda pos, self=self: self.pickDeconv(pos)
            self.peakPick = True

#################################################################################


class CsaDeconvParamFrame(AbstractParamFrame):

    FFT_AXES = (0,)
    SINGLENAMES = ['offset', 'mult', 'spinspeed']
    MULTINAMES = ['t11', 't22', 't33', 'amp', 'lor', 'gauss']
    EXTRANAMES = ['spinType', 'satBool', 'angle', 'shiftdef', 'cheng', 'numssb']
    PARAMTEXT = {'offset': 'Offset', 'mult':'Multiplier', 'spinspeed': 'Spinning Speed', 't11': 'T11', 't22': 'T22', 't33': 'T33', 'amp': 'Integral', 'lor': 'Lorentz', 'gauss': 'Gauss'}

    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.csaFunc
        self.fullInt = np.sum(parent.getData1D()) * parent.sw() / float(len(parent.getData1D()))
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'spinspeed': [10.0, True], 't11': [0.0, False], 't22': [0.0, False], 't33': [0.0, False], 'amp': [self.fullInt, False], 'lor': [1.0, False], 'gauss': [0.0, True]}
        self.extraDefaults = {'cheng': 15, 'shiftdef': 0, 'spinType': 0, 'rotorAngle': "arctan(sqrt(2))", 'numssb': 32, 'spinspeed': '10.0'}
        super(CsaDeconvParamFrame, self).__init__(parent, rootwindow, isMain)
        self.pickTick = QtWidgets.QCheckBox("Pick")
        self.pickTick.stateChanged.connect(self.togglePick)
        self.optframe.addWidget(self.pickTick, 4, 0)
        self.optframe.addWidget(wc.QLabel("MAS:"), 0, 0)
        self.entries['spinType'].append(QtWidgets.QComboBox(self))
        self.entries['spinType'][-1].addItems(["Static", "Finite MAS", "Infinite MAS"])
        self.entries['spinType'][-1].currentIndexChanged.connect(self.MASChange)
        self.optframe.addWidget(self.entries['spinType'][-1], 1, 0)
        self.angleLabel = wc.QLabel("Rotor Angle:")
        self.optframe.addWidget(self.angleLabel, 2, 1)
        self.entries['angle'].append(wc.QLineEdit())
        self.entries['angle'][-1].setEnabled(False)
        self.optframe.addWidget(self.entries['angle'][-1], 3, 1)
        self.sidebandLabel = wc.QLabel("# sidebands:")
        self.optframe.addWidget(self.sidebandLabel, 4, 1)
        self.entries['numssb'].append(QtWidgets.QSpinBox())
        self.entries['numssb'][-1].setAlignment(QtCore.Qt.AlignHCenter)
        self.entries['numssb'][-1].setMaximum(100000)
        self.entries['numssb'][-1].setMinimum(2)
        self.optframe.addWidget(self.entries['numssb'][-1], 5, 1)
        self.optframe.addWidget(wc.QLabel("Cheng:"), 0, 1)
        self.entries['cheng'].append(QtWidgets.QSpinBox())
        self.entries['cheng'][-1].setAlignment(QtCore.Qt.AlignHCenter)
        self.optframe.addWidget(self.entries['cheng'][-1], 1, 1)
        self.shiftDefType = 0  # variable to remember the selected tensor type
        self.optframe.addWidget(wc.QLabel("Definition:"), 2, 0)
        self.entries['shiftdef'].append(QtWidgets.QComboBox())
        self.entries['shiftdef'][-1].addItems([u'δ11 - δ22 - δ33',
                                               u'δxx - δyy - δzz',
                                               u'δiso - δaniso - η',
                                               u'δiso - Ω - κ'])
        self.entries['shiftdef'][-1].currentIndexChanged.connect(self.changeShiftDef)
        self.optframe.addWidget(self.entries['shiftdef'][-1], 3, 0)
        self.spinLabel = wc.QLabel("Spin. speed [kHz]:")
        self.frame2.addWidget(self.spinLabel, 0, 0, 1, 2)
        self.ticks['spinspeed'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['spinspeed'][-1], 1, 0)
        self.entries['spinspeed'].append(wc.FitQLineEdit(self, 'spinspeed', ""))
        self.frame2.addWidget(self.entries['spinspeed'][-1], 1, 1)
        self.frame2.addWidget(wc.QLabel("Offset:"), 2, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['offset'][-1], 3, 0)
        self.entries['offset'].append(wc.FitQLineEdit(self, 'offset', ""))
        self.frame2.addWidget(self.entries['offset'][-1], 3, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 4, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['mult'][-1], 5, 0)
        self.entries['mult'].append(wc.FitQLineEdit(self, 'mult', ""))
        self.frame2.addWidget(self.entries['mult'][-1], 5, 1)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        if self.parent.viewSettings["ppm"]:
            axUnit = 'ppm'
        else:
            axUnit = ['Hz', 'kHz', 'MHz'][self.parent.getAxType()]
        # Labels
        self.label11 = wc.QLabel(u'δ' + '<sub>11</sub> [' + axUnit + '] :')
        self.label22 = wc.QLabel(u'δ' + '<sub>22</sub> [' + axUnit + '] :')
        self.label33 = wc.QLabel(u'δ' + '<sub>33</sub> [' + axUnit + '] :')
        self.frame3.addWidget(self.label11, 1, 0, 1, 2)
        self.frame3.addWidget(self.label22, 1, 2, 1, 2)
        self.frame3.addWidget(self.label33, 1, 4, 1, 2)
        self.labelxx = wc.QLabel(u'δ' + '<sub>xx</sub> [' + axUnit + '] :')
        self.labelyy = wc.QLabel(u'δ' + '<sub>yy</sub> [' + axUnit + '] :')
        self.labelzz = wc.QLabel(u'δ' + '<sub>zz</sub> [' + axUnit + '] :')
        self.labelxx.hide()
        self.labelyy.hide()
        self.labelzz.hide()
        self.frame3.addWidget(self.labelxx, 1, 0, 1, 2)
        self.frame3.addWidget(self.labelyy, 1, 2, 1, 2)
        self.frame3.addWidget(self.labelzz, 1, 4, 1, 2)
        self.labeliso = wc.QLabel(u'δ' + '<sub>iso</sub> [' + axUnit + '] :')
        self.labelaniso = wc.QLabel(u'δ' + '<sub>aniso</sub> [' + axUnit + '] :')
        self.labeleta = wc.QLabel(u'η:')
        self.labeliso.hide()
        self.labelaniso.hide()
        self.labeleta.hide()
        self.frame3.addWidget(self.labeliso, 1, 0, 1, 2)
        self.frame3.addWidget(self.labelaniso, 1, 2, 1, 2)
        self.frame3.addWidget(self.labeleta, 1, 4, 1, 2)
        self.labeliso2 = wc.QLabel(u'δ' + '<sub>iso</sub> [' + axUnit + '] :')
        self.labelspan = wc.QLabel(u'Ω [' + axUnit + '] :')
        self.labelskew = wc.QLabel(u'κ:')
        self.labeliso2.hide()
        self.labelspan.hide()
        self.labelskew.hide()
        self.frame3.addWidget(self.labeliso2, 1, 0, 1, 2)
        self.frame3.addWidget(self.labelspan, 1, 2, 1, 2)
        self.frame3.addWidget(self.labelskew, 1, 4, 1, 2)
        self.frame3.addWidget(wc.QLabel("Integral:"), 1, 6, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz [Hz]:"), 1, 8, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss [Hz]:"), 1, 10, 1, 2)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def MASChange(self, MAStype):
        if MAStype > 0:
            self.angleLabel.setEnabled(True)
            self.entries['angle'][-1].setEnabled(True)
        else:
            self.angleLabel.setEnabled(False)
            self.entries['angle'][-1].setEnabled(False)
        if MAStype == 1:  # Finite MAS
            self.entries['spinspeed'][-1].setEnabled(True)
            self.ticks['spinspeed'][-1].setEnabled(True)
            self.spinLabel.setEnabled(True)
            self.entries['numssb'][-1].setEnabled(True)
            self.sidebandLabel.setEnabled(True)
        else:
            self.ticks['spinspeed'][-1].setChecked(True)
            self.entries['spinspeed'][-1].setEnabled(False)
            self.ticks['spinspeed'][-1].setEnabled(False)
            self.spinLabel.setEnabled(False)
            self.entries['numssb'][-1].setEnabled(False)
            self.sidebandLabel.setEnabled(False)

    def reset(self):
        self.entries['cheng'][-1].setValue(self.extraDefaults['cheng'])
        self.entries['shiftdef'][-1].setCurrentIndex(self.extraDefaults['shiftdef'])
        self.shiftDefType = self.extraDefaults['shiftdef']
        self.entries['spinType'][-1].setCurrentIndex(self.extraDefaults['spinType'])
        self.MASChange(self.extraDefaults['spinType'])
        self.entries['numssb'][-1].setValue(self.extraDefaults['numssb'])
        self.entries['angle'][-1].setText(self.extraDefaults['rotorAngle'])
        self.entries['spinspeed'][-1].setText(self.extraDefaults['spinspeed'])
        self.parent.pickNum = 0
        self.parent.pickNum2 = 0
        self.pickTick.setChecked(True)
        self.togglePick()
        super(CsaDeconvParamFrame, self).reset()

    def togglePick(self):
        self.parent.togglePick(self.pickTick.isChecked())

    def changeShiftDef(self):
        NewType = self.entries['shiftdef'][-1].currentIndex()
        OldType = self.shiftDefType
        if NewType == 0:
            self.label11.show()
            self.label22.show()
            self.label33.show()
            self.labelxx.hide()
            self.labelyy.hide()
            self.labelzz.hide()
            self.labeliso.hide()
            self.labelaniso.hide()
            self.labeleta.hide()
            self.labeliso2.hide()
            self.labelspan.hide()
            self.labelskew.hide()
            self.pickTick.setChecked(True)
            self.pickTick.show()
        elif NewType == 1:
            self.label11.hide()
            self.label22.hide()
            self.label33.hide()
            self.labelxx.show()
            self.labelyy.show()
            self.labelzz.show()
            self.labeliso.hide()
            self.labelaniso.hide()
            self.labeleta.hide()
            self.labeliso2.hide()
            self.labelspan.hide()
            self.labelskew.hide()
            self.pickTick.setChecked(True)
            self.pickTick.show()
        elif NewType == 2:
            self.label11.hide()
            self.label22.hide()
            self.label33.hide()
            self.labelxx.hide()
            self.labelyy.hide()
            self.labelzz.hide()
            self.labeliso.show()
            self.labelaniso.show()
            self.labeleta.show()
            self.labeliso2.hide()
            self.labelspan.hide()
            self.labelskew.hide()
            self.pickTick.setChecked(False)
            self.pickTick.hide()
        elif NewType == 3:
            self.label11.hide()
            self.label22.hide()
            self.label33.hide()
            self.labelxx.hide()
            self.labelyy.hide()
            self.labelzz.hide()
            self.labeliso.hide()
            self.labelaniso.hide()
            self.labeleta.hide()
            self.labeliso2.show()
            self.labelspan.show()
            self.labelskew.show()
            self.pickTick.setChecked(False)
            self.pickTick.hide()
        val = self.numExp.currentIndex() + 1
        tensorList = []
        for i in range(10):  # Convert input
            if i < val:
                T11 = safeEval(self.entries['t11'][i].text())
                T22 = safeEval(self.entries['t22'][i].text())
                T33 = safeEval(self.entries['t33'][i].text())
                startTensor = [T11, T22, T33]
                if None in startTensor:
                    self.entries['shiftdef'][-1].setCurrentIndex(OldType)  # error, reset to old view
                    raise FittingException("Fitting: One of the inputs is not valid")
                Tensors = func.shiftConversion(startTensor, OldType)
                for element in range(3):  # Check for `ND' s
                    if isinstance(Tensors[NewType][element], str):
                        Tensors[NewType][element] = 0
                tensorList.append(Tensors)
        printStr = '%#.' + str(self.rootwindow.tabWindow.PRECIS) + 'g'
        for i in range(10):  # Print output if not stopped before
            if i < val:
                self.entries['t11'][i].setText(printStr % tensorList[i][NewType][0])
                self.entries['t22'][i].setText(printStr % tensorList[i][NewType][1])
                self.entries['t33'][i].setText(printStr % tensorList[i][NewType][2])
        self.shiftDefType = NewType

    def getExtraParams(self, out):
        shiftdef = self.entries['shiftdef'][0].currentIndex()
        angle = safeEval(self.entries['angle'][-1].text())
        if angle is None:
            raise FittingException("Fitting: Rotor Angle is not valid")
        cheng = safeEval(self.entries['cheng'][-1].text())
        alpha, beta, weight = simFunc.zcw_angles(cheng, 2)
        D2 = simFunc.D2tens(alpha, beta, np.zeros_like(alpha))
        numssb = self.entries['numssb'][0].value()
        MAStype = self.entries['spinType'][-1].currentIndex()
        out['extra'] = [shiftdef, numssb, angle, D2, weight, MAStype]
        return (out, out['extra'])

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
            if struc['lor'][i][0] == 1:
                self.fitParamList[locList]['lor'][i][0] = abs(self.fitParamList[locList]['lor'][i][0])
            if struc['gauss'][i][0] == 1:
                self.fitParamList[locList]['gauss'][i][0] = abs(self.fitParamList[locList]['gauss'][i][0])
            if struc['t33'][i][0] == 1:
                if self.shiftDefType == 2:
                    self.fitParamList[locList]['t33'][i][0] = 1 - abs(abs(self.fitParamList[locList]['t33'][i][0])%2 - 1)
                if self.shiftDefType == 3:
                    self.fitParamList[locList]['t33'][i][0] = 1 - abs(abs(self.fitParamList[locList]['t33'][i][0] + 1)%4 - 2)


##############################################################################


class QuadDeconvWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = QuadDeconvFrame
        self.PARAMFRAME = QuadDeconvParamFrame
        super(QuadDeconvWindow, self).__init__(father, oldMainWindow)

#################################################################################


class QuadDeconvFrame(FitPlotFrame):

    FITNUM = 10  # Maximum number of fits

#################################################################################


class QuadDeconvParamFrame(AbstractParamFrame):

    FFT_AXES = (0,)    
    Ioptions = ['1', '3/2', '2', '5/2', '3', '7/2', '4', '9/2']
    Ivalues = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
    SINGLENAMES = ['offset', 'mult', 'spinspeed']
    MULTINAMES = ['pos', 'cq', 'eta', 'amp', 'lor', 'gauss']
    EXTRANAMES = ['spinType', 'satBool', 'angle', 'cheng', 'I', 'numssb']
    PARAMTEXT = {'offset': 'Offset', 'mult':'Multiplier', 'spinspeed': 'Spinning Speed', 'pos': 'Position', 'cq': 'Cq', 'eta': 'eta', 'amp': 'Integral', 'lor': 'Lorentz', 'gauss': 'Gauss'}

    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.quadFunc
        self.fullInt = np.sum(parent.getData1D()) * parent.sw() / float(len(parent.getData1D()))
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'spinspeed': [10.0, True], 'pos': [0.0, False], 'cq': [1.0, False], 'eta': [0.0, False], 'amp': [self.fullInt, False], 'lor': [1.0, False], 'gauss': [0.0, True]}
        self.extraDefaults = {'I': 1, 'Satellites': False, 'cheng': 15, 'spinType': 0, 'rotorAngle': "arctan(sqrt(2))", 'numssb': 32, 'spinspeed': '10.0'}
        super(QuadDeconvParamFrame, self).__init__(parent, rootwindow, isMain)
        self.optframe.addWidget(wc.QLabel("MAS:"), 2, 0)
        self.entries['spinType'].append(QtWidgets.QComboBox(self))
        self.entries['spinType'][-1].addItems(["Static", "Finite", "Infinite"])
        self.entries['spinType'][-1].currentIndexChanged.connect(self.MASChange)
        self.optframe.addWidget(self.entries['spinType'][-1], 3, 0)
        self.entries['satBool'].append(QtWidgets.QCheckBox("Satellites"))
        self.optframe.addWidget(self.entries['satBool'][-1], 4, 0)
        self.angleLabel = wc.QLabel("Rotor Angle:")
        self.optframe.addWidget(self.angleLabel, 2, 1)
        self.entries['angle'].append(wc.QLineEdit())
        self.optframe.addWidget(self.entries['angle'][-1], 3, 1)
        self.sidebandLabel = wc.QLabel("# sidebands:")
        self.optframe.addWidget(self.sidebandLabel, 4, 1)
        self.entries['numssb'].append(QtWidgets.QSpinBox())
        self.entries['numssb'][-1].setAlignment(QtCore.Qt.AlignHCenter)
        self.entries['numssb'][-1].setMaximum(100000)
        self.entries['numssb'][-1].setMinimum(2)
        self.optframe.addWidget(self.entries['numssb'][-1], 5, 1)
        self.optframe.addWidget(wc.QLabel("Cheng:"), 0, 1)
        self.entries['cheng'].append(QtWidgets.QSpinBox())
        self.entries['cheng'][-1].setAlignment(QtCore.Qt.AlignHCenter)
        self.optframe.addWidget(self.entries['cheng'][-1], 1, 1)
        self.optframe.addWidget(wc.QLabel("I:"), 0, 0)
        self.entries['I'].append(QtWidgets.QComboBox())
        self.entries['I'][-1].addItems(self.Ioptions)
        self.optframe.addWidget(self.entries['I'][-1], 1, 0)
        self.spinLabel = wc.QLabel("Spin. speed [kHz]:")
        self.frame2.addWidget(self.spinLabel, 0, 0, 1, 2)
        self.ticks['spinspeed'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['spinspeed'][-1], 1, 0)
        self.entries['spinspeed'].append(wc.QLineEdit())
        self.frame2.addWidget(self.entries['spinspeed'][-1], 1, 1)
        self.entries['spinspeed'][-1].setEnabled(False)
        self.frame2.addWidget(wc.QLabel("Offset:"), 2, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['offset'][-1], 3, 0)
        self.entries['offset'].append(wc.QLineEdit())
        self.frame2.addWidget(self.entries['offset'][-1], 3, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 4, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['mult'][-1], 5, 0)
        self.entries['mult'].append(wc.QLineEdit())
        self.frame2.addWidget(self.entries['mult'][-1], 5, 1)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        if self.parent.viewSettings["ppm"]:
            axUnit = 'ppm'
        else:
            axUnit = ['Hz', 'kHz', 'MHz'][self.parent.getAxType()]
        # Labels
        self.labelpos = wc.QLabel(u'Position [' + axUnit + ']:')
        self.labelcq = wc.QLabel(u'C<sub>Q</sub> [MHz]:')
        self.labeleta = wc.QLabel(u'η:')
        self.frame3.addWidget(self.labelpos, 1, 0, 1, 2)
        self.frame3.addWidget(self.labelcq, 1, 2, 1, 2)
        self.frame3.addWidget(self.labeleta, 1, 4, 1, 2)
        self.frame3.addWidget(wc.QLabel("Integral:"), 1, 6, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz [Hz]:"), 1, 8, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss [Hz]:"), 1, 10, 1, 2)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def MASChange(self, MAStype):
        if MAStype > 0:
            self.angleLabel.setEnabled(True)
            self.entries['angle'][-1].setEnabled(True)
        else:
            self.angleLabel.setEnabled(False)
            self.entries['angle'][-1].setEnabled(False)
        if MAStype == 1:  # Finite MAS
            self.entries['spinspeed'][-1].setEnabled(True)
            self.ticks['spinspeed'][-1].setEnabled(True)
            self.spinLabel.setEnabled(True)
            self.entries['numssb'][-1].setEnabled(True)
            self.sidebandLabel.setEnabled(True)
        else:
            self.ticks['spinspeed'][-1].setChecked(True)
            self.entries['spinspeed'][-1].setEnabled(False)
            self.ticks['spinspeed'][-1].setEnabled(False)
            self.spinLabel.setEnabled(False)
            self.entries['numssb'][-1].setEnabled(False)
            self.sidebandLabel.setEnabled(False)

    def reset(self):
        self.entries['cheng'][-1].setValue(self.extraDefaults['cheng'])
        self.entries['spinType'][-1].setCurrentIndex(self.extraDefaults['spinType'])
        self.MASChange(self.extraDefaults['spinType'])
        self.entries['numssb'][-1].setValue(self.extraDefaults['numssb'])
        self.entries['angle'][-1].setText(self.extraDefaults['rotorAngle'])
        self.entries['spinspeed'][-1].setText(self.extraDefaults['spinspeed'])
        self.entries['I'][-1].setCurrentIndex(self.extraDefaults['I'])
        self.entries['satBool'][-1].setChecked(self.extraDefaults["Satellites"])
        super(QuadDeconvParamFrame, self).reset()

    def getExtraParams(self, out):
        satBool = self.entries['satBool'][-1].isChecked()
        angle = safeEval(self.entries['angle'][-1].text())
        if angle is None:
            raise FittingException("Fitting: Rotor Angle is not valid")
        I = self.entries['I'][-1].currentIndex() * 0.5 + 1
        cheng = safeEval(self.entries['cheng'][-1].text())
        alpha, beta, weight = simFunc.zcw_angles(cheng, 2)
        D2 = simFunc.D2tens(alpha, beta, np.zeros_like(alpha))
        D4 = simFunc.D4tens(alpha, beta, np.zeros_like(alpha))
        numssb = self.entries['numssb'][-1].value()
        MAStype = self.entries['spinType'][-1].currentIndex()
        out['extra'] = [satBool, I, numssb, angle, D2, D4, weight, MAStype]
        return (out, out['extra'])

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['lor'][i][0] == 1:
                self.fitParamList[locList]['lor'][i][0] = abs(self.fitParamList[locList]['lor'][i][0])
           if struc['gauss'][i][0] == 1:
                self.fitParamList[locList]['gauss'][i][0] = abs(self.fitParamList[locList]['gauss'][i][0])
           if struc['eta'][i][0] == 1:
                #eta is between 0--1 in a continuous way.
                self.fitParamList[locList]['eta'][i][0] = 1 - abs(abs(self.fitParamList[locList]['eta'][i][0]) % 2 - 1)
           if struc['cq'][i][0] == 1:
                self.fitParamList[locList]['cq'][i][0] = abs(self.fitParamList[locList]['cq'][i][0])



##############################################################################


class CzjzekPrefWindow(QtWidgets.QWidget):

    Ioptions = ['1', '3/2', '2', '5/2', '3', '7/2', '4', '9/2']
    
    def __init__(self, parent, mqmas=False):
        super(CzjzekPrefWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.Tool)
        self.father = parent
        self.mqmas = mqmas
        if mqmas:
            self.Ioptions = self.Ioptions[1::2]
        self.setWindowTitle("Library")
        layout = QtWidgets.QGridLayout(self)
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid, 0, 0, 1, 4)
        grid.addWidget(wc.QLabel("I:"), 0, 0)
        self.Ientry = QtWidgets.QComboBox()
        self.Ientry.addItems(self.Ioptions)
        grid.addWidget(self.Ientry, 1, 0)
        grid.addWidget(wc.QLabel("Cheng:"), 0, 1)
        self.chengEntry = QtWidgets.QSpinBox()
        self.chengEntry.setAlignment(QtCore.Qt.AlignHCenter)
        self.chengEntry.setValue(self.father.cheng)
        grid.addWidget(self.chengEntry, 1, 1)
        grid.addWidget(wc.QLabel(u"C<sub>Q</sub> grid size:"), 2, 0)
        self.cqsteps = QtWidgets.QSpinBox()
        self.cqsteps.setMinimum(2)
        self.cqsteps.setMaximum(1000)
        self.cqsteps.setAlignment(QtCore.Qt.AlignHCenter) 
        grid.addWidget(self.cqsteps, 3, 0)
        grid.addWidget(wc.QLabel(u"η grid size:"), 2, 1)
        self.etasteps = QtWidgets.QSpinBox()
        self.etasteps.setMinimum(2)
        self.etasteps.setMaximum(1000)
        self.etasteps.setAlignment(QtCore.Qt.AlignHCenter) 
        grid.addWidget(self.etasteps, 3, 1)
        grid.addWidget(wc.QLabel(u"C<sub>Q</sub> limits [MHz]:"), 4, 0, 1, 2)
        self.cqmin = wc.QLineEdit(str(self.father.cqmin), self.checkCq)
        grid.addWidget(self.cqmin, 5, 0)
        self.cqmax = wc.QLineEdit(str(self.father.cqmax), self.checkCq)
        grid.addWidget(self.cqmax, 5, 1)
        grid.addWidget(wc.QLabel(u"η limits:"), 6, 0, 1, 2)
        self.etamin = wc.QLineEdit(str(self.father.etamin), self.checkEta)
        grid.addWidget(self.etamin, 7, 0)
        self.etamax = wc.QLineEdit(str(self.father.etamax), self.checkEta)
        grid.addWidget(self.etamax, 7, 1)
        if not mqmas:
            grid.addWidget(wc.QLabel("MAS:"), 8, 0)
            self.masEntry = QtWidgets.QComboBox(self)
            self.masEntry.addItems(["Static", "Finite MAS", "Infinite MAS"])
            self.masEntry.currentIndexChanged.connect(self.MASChange)
            grid.addWidget(self.masEntry, 9, 0)
            self.angleLabel = wc.QLabel("Rotor Angle:")
            self.angleLabel.setEnabled(False)
            grid.addWidget(self.angleLabel, 8, 1)
            self.angleEntry = wc.QLineEdit(self.father.angle)
            self.angleEntry.setEnabled(False)
            grid.addWidget(self.angleEntry, 9, 1)
            self.spinLabel = wc.QLabel("Spin. speed [kHz]:")
            self.spinLabel.setEnabled(False)
            grid.addWidget(self.spinLabel, 10, 0)
            self.spinEntry = wc.QLineEdit(str(self.father.spinspeed))
            self.spinEntry.setEnabled(False)
            grid.addWidget(self.spinEntry, 11, 0)
            self.sidebandLabel = wc.QLabel("# sidebands:")
            self.sidebandLabel.setEnabled(False)
            grid.addWidget(self.sidebandLabel, 10, 1)
            self.numssbEntry = QtWidgets.QSpinBox()
            self.numssbEntry.setAlignment(QtCore.Qt.AlignHCenter)
            self.numssbEntry.setMaximum(100000)
            self.numssbEntry.setMinimum(2)
            self.numssbEntry.setEnabled(False)
            grid.addWidget(self.numssbEntry, 11, 1)
            self.satBoolEntry = QtWidgets.QCheckBox("Satellites")
            grid.addWidget(self.satBoolEntry, 12, 0)
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        grid.addWidget(self.canvas, 0, 2, 14, 4)
        self.ax = self.fig.add_subplot(111)
        self.simButton = QtWidgets.QPushButton("Show", parent=self)
        self.simButton.clicked.connect(self.plotDist)
        grid.addWidget(self.simButton, 14, 4)
        grid.addWidget(wc.QLabel("Site:"), 14, 2)
        self.site = QtWidgets.QSpinBox()
        self.site.setMinimum(1)
        self.site.setMaximum(self.father.numExp.currentIndex() + 1)
        self.site.setAlignment(QtCore.Qt.AlignHCenter) 
        grid.addWidget(self.site, 14, 3)
        cancelButton = QtWidgets.QPushButton("&Close")
        cancelButton.clicked.connect(self.closeEvent)
        layout.addWidget(cancelButton, 4, 0)
        genButton = QtWidgets.QPushButton("&Generate", self)
        genButton.clicked.connect(self.generate)
        genButton.setFocus()
        layout.addWidget(genButton, 4, 1)
        loadButton = QtWidgets.QPushButton("&Load", self)
        loadButton.clicked.connect(self.loadLib)
        layout.addWidget(loadButton, 4, 2)
        grid.setRowStretch(13, 1)
        grid.setColumnStretch(5, 1)
        layout.setColumnStretch(3, 1)
        self.upd()
        #self.plotDist()
        self.show()
        self.resize(800, 600)

    def MASChange(self, MAStype):
        if self.mqmas:
            return
        if MAStype > 0:
            self.angleLabel.setEnabled(True)
            self.angleEntry.setEnabled(True)
        else:
            self.angleLabel.setEnabled(False)
            self.angleEntry.setEnabled(False)
        if MAStype == 1:  # Finite MAS
            self.spinEntry.setEnabled(True)
            self.spinLabel.setEnabled(True)
            self.numssbEntry.setEnabled(True)
            self.sidebandLabel.setEnabled(True)
        else:
            self.spinEntry.setEnabled(False)
            self.spinLabel.setEnabled(False)
            self.numssbEntry.setEnabled(False)
            self.sidebandLabel.setEnabled(False)
        
    def upd(self):
        if self.mqmas:
            self.Ientry.setCurrentIndex(int(self.father.I-1.5))
        else:
            self.Ientry.setCurrentIndex(int(self.father.I*2.0-2.0))            
        self.chengEntry.setValue(self.father.cheng)
        if not self.mqmas:
            self.masEntry.setCurrentIndex(self.father.mas)
            self.numssbEntry.setValue(self.father.numssb)
            self.angleEntry.setText(self.father.angle)
            self.spinEntry.setText(str(self.father.spinspeed))
            self.satBoolEntry.setChecked(self.father.satBool)
        self.cqsteps.setValue(self.father.cqsteps)
        self.etasteps.setValue(self.father.etasteps)
        self.cqmin.setText(str(self.father.cqmin))
        self.cqmax.setText(str(self.father.cqmax))
        self.etamin.setText(str(self.father.etamin))
        self.etamax.setText(str(self.father.etamax))

    def plotDist(self):
        self.ax.cla()
        cqsteps = self.cqsteps.value()
        etasteps = self.etasteps.value()
        cqmax = safeEval(self.cqmax.text(), type='FI')
        cqmin = safeEval(self.cqmin.text(), type='FI')
        etamax = safeEval(self.etamax.text(), type='FI')
        etamin = safeEval(self.etamin.text(), type='FI')
        cq, eta = np.meshgrid(np.linspace(cqmin, cqmax, cqsteps), np.linspace(etamin, etamax, etasteps))
        method = self.father.entries['method'][0].currentIndex()
        d = self.father.entries['d'][0].currentIndex() + 1
        site = self.site.value() - 1
        sigma = safeEval(self.father.entries['sigma'][site].text(), type='FI')
        cq0 = safeEval(self.father.entries['cq0'][site].text(), type='FI')
        eta0 = safeEval(self.father.entries['eta0'][site].text(), type='FI')
        if method == 0:
            czjzek = Czjzek.czjzekIntensities(sigma, d, cq.flatten(), eta.flatten())
        else:
            czjzek = Czjzek.czjzekIntensities(sigma, d, cq.flatten(), eta.flatten(), cq0, eta0)
        czjzek = czjzek.reshape(etasteps, cqsteps)
        self.ax.contour(cq.transpose(), eta.transpose(), czjzek.transpose(), 10)
        self.ax.set_xlabel(u"C$_Q$ [MHz]")
        self.ax.set_ylabel(u"η")
        self.canvas.draw()

    def checkCq(self):
        inp = safeEval(self.cqmax.text(), type='FI')
        if inp is None:
            return False
        self.cqmax.setText(str(float(inp)))
        inp = safeEval(self.cqmin.text(), type='FI')
        if inp is None:
            return False
        self.cqmin.setText(str(float(inp)))
        return True

    def checkEta(self):
        inp = safeEval(self.etamax.text(), type='FI')
        if inp is None:
            return False
        if inp < 0.0 or inp > 1.0:
            return False
        self.etamax.setText(str(abs(float(inp))))
        inp = safeEval(self.etamin.text(), type='FI')
        if inp is None:
            return False
        if inp < 0.0 or inp > 1.0:
            return False
        self.etamin.setText(str(abs(float(inp))))

    def closeEvent(self, *args):
        self.deleteLater()

    def generate(self, *args):
        self.father.cqsteps = self.cqsteps.value()
        self.father.etasteps = self.etasteps.value()
        self.father.cheng = self.chengEntry.value()
        if not self.mqmas:
            self.father.I = self.Ientry.currentIndex() * 0.5 + 1.0
            self.father.mas = self.masEntry.currentIndex()
            inp = safeEval(self.spinEntry.text(), type='FI')
            if inp is None:
                raise FittingException("Spin speed value not valid.")
            self.father.spinspeed = inp
            self.father.angle = self.angleEntry.text()
            self.father.numssb = self.numssbEntry.value()
            self.father.satBool = self.satBoolEntry.isChecked()
        else:
            self.father.I = self.Ientry.currentIndex() + 1.5
        inp = safeEval(self.cqmax.text(), type='FI')
        if inp is None:
            raise FittingException(u"C_Q_max value not valid.")
        self.father.cqmax = abs(safeEval(self.cqmax.text()))
        inp = abs(safeEval(self.cqmin.text(), type='FI'))
        if inp is None:
            raise FittingException(u"C_Q_min value not valid.")
        self.father.cqmin = abs(safeEval(self.cqmin.text()))
        #eta
        inp = safeEval(self.etamax.text(), type='FI')
        if inp is None:
            raise FittingException(u"η_max value not valid.")
        if inp < 0.0 or inp > 1.0:
            raise FittingException(u"η_max value not valid.")
        self.father.etamax = abs(float(inp))
        inp = safeEval(self.etamin.text(), type='FI')
        if inp is None:
            raise FittingException(u"η_min value not valid.")
        if inp < 0.0 or inp > 1.0:
            raise FittingException(u"η_min value not valid.")
        self.father.etamin = abs(float(inp))
        self.father.simLib()

    def loadLib(self, *args):
        dirName = self.father.rootwindow.father.loadFitLibDir()
        nameList = os.listdir(dirName)
        cq = []
        eta = []
        data = []
        for name in nameList:
            matchName = re.search("-(\d+\.\d+)-(\d+\.\d+)\.(fid|spe)$", name)
            if matchName:
                eta.append(float(matchName.group(1)))
                cq.append(float(matchName.group(2)))
                fullName = os.path.join(dirName, name)
                libData = io.autoLoad(fullName)
                if libData.ndim() != 1:
                    raise FittingException("A spectrum in the library is not a 1D spectrum.")
                if not libData.spec[0]:
                    libData.fourier(0)
                libData.regrid([self.father.parent.xax()[0], self.father.parent.xax()[-1]], len(self.father.parent.xax()), 0)
                libData.fftshift(0)
                libData.fourier(0)
                data.append(np.real(libData.data[0]))
        cq = np.array(cq) * 1e6
        eta = np.array(eta)
        data = np.array(data)
        numCq = len(np.unique(cq))
        numEta = len(np.unique(eta))
        if len(cq) != numCq * numEta:
            raise FittingException("Library to be loaded is not of a rectangular grid in Cq and eta.")
        sortIndex = np.lexsort((cq, eta))
        self.father.cqLib = cq[sortIndex]
        self.father.etaLib = eta[sortIndex]
        self.father.lib = data[sortIndex]
        self.father.cqsteps = numCq
        self.father.etasteps = numEta
        self.father.cqmax = np.max(cq) * 1e-6
        self.father.cqmin = np.min(cq) * 1e-6
        self.father.etamax = np.max(eta)
        self.father.etamin = np.min(eta)
        self.upd()

##############################################################################

class QuadCzjzekWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = QuadDeconvFrame
        self.PARAMFRAME = QuadCzjzekParamFrame
        super(QuadCzjzekWindow, self).__init__(father, oldMainWindow)

#################################################################################


class QuadCzjzekParamFrame(AbstractParamFrame):

    FFT_AXES = (0,)
    SINGLENAMES = ['offset', 'mult']
    MULTINAMES = ['pos', 'sigma', 'cq0', 'eta0', 'amp', 'lor', 'gauss']
    EXTRANAMES = ['method', 'd']
    PARAMTEXT = {'offset': 'Offset', 'mult':'Multiplier', 'pos': 'Position', 'sigma': 'Sigma', 'cq0': 'Cq0', 'eta0': 'Eta0', 'amp': 'Integral', 'lor': 'Lorentz', 'gauss': 'Gauss'}

    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.quadCzjzekFunc
        self.fullInt = np.sum(parent.getData1D()) * parent.sw() / float(len(parent.getData1D()))
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'pos': [0.0, False], 'sigma': [1.0, False], 'cq0': [0.0, True], 'eta0': [0.0, True], 'amp': [self.fullInt, False], 'lor': [10.0, False], 'gauss': [0.0, True]}
        self.extraDefaults = {'method': 0, 'd': 5, 'cqsteps': 50, 'etasteps': 10, 'cqmax': 4.0, 'cqmin': 0.0, 'etamin': 0, 'etamax': 1,
                'lib': None, 'cqLib': None, 'etaLib': None, 'I': 3 / 2.0, 'cheng': 15, 'mas': 2, 'spinspeed': 10.0,
                'angle': "arctan(sqrt(2))", 'numssb': 32, 'satBool': False}
        super(QuadCzjzekParamFrame, self).__init__(parent, rootwindow, isMain)
        czjzekPrefButton = QtWidgets.QPushButton("Library")
        czjzekPrefButton.clicked.connect(self.createCzjzekPrefWindow)
        self.optframe.addWidget(czjzekPrefButton, 4, 0)
        self.frame2.addWidget(wc.QLabel("Offset:"), 0, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.ticks['offset'][-1].setChecked(True)
        self.frame2.addWidget(self.ticks['offset'][-1], 1, 0)
        self.entries['offset'].append(wc.FitQLineEdit(self, 'offset', "0.0"))
        self.frame2.addWidget(self.entries['offset'][-1], 1, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 2, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.ticks['mult'][-1].setChecked(True)
        self.frame2.addWidget(self.ticks['mult'][-1], 3, 0)
        self.entries['mult'].append(wc.FitQLineEdit(self, 'mult', "1.0"))
        self.frame2.addWidget(self.entries['mult'][-1], 3, 1)
        self.optframe.addWidget(wc.QLabel("Type:"), 0, 0)
        self.entries['method'].append(QtWidgets.QComboBox())
        self.entries['method'][0].addItems(['Normal', 'Extended'])
        self.entries['method'][0].currentIndexChanged.connect(self.changeType)
        self.optframe.addWidget(self.entries['method'][0], 1, 0)
        self.optframe.addWidget(wc.QLabel("d:"), 2, 0)
        self.entries['d'].append(QtWidgets.QComboBox())
        self.entries['d'][0].addItems(['1', '2','3','4','5'])
        self.optframe.addWidget(self.entries['d'][0], 3, 0)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        if self.parent.viewSettings["ppm"]:
            axUnit = 'ppm'
        else:
            axUnit = ['Hz', 'kHz', 'MHz'][self.parent.getAxType()]
        self.frame3.addWidget(wc.QLabel("Pos [" + axUnit + "]:"), 1, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"σ [MHz]:"), 1, 2, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"C<sub>Q</sub>0 [MHz]:"), 1, 4, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"η0:"), 1, 6, 1, 2)
        self.frame3.addWidget(wc.QLabel("Integral:"), 1, 8, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz [Hz]:"), 1, 10, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss [Hz]:"), 1, 12, 1, 2)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def reset(self):
        self.cqsteps = self.extraDefaults['cqsteps']
        self.etasteps = self.extraDefaults['etasteps']
        self.cqmax = self.extraDefaults['cqmax']
        self.cqmin = self.extraDefaults['cqmin']
        self.etamax = self.extraDefaults['etamax']
        self.etamin = self.extraDefaults['etamin']
        self.lib = self.extraDefaults['lib']
        self.cqLib = self.extraDefaults['cqLib']
        self.etaLib = self.extraDefaults['etaLib']
        self.I = self.extraDefaults['I']
        self.cheng = self.extraDefaults['cheng']
        self.mas = self.extraDefaults['mas']
        self.spinspeed = self.extraDefaults['spinspeed']
        self.angle = self.extraDefaults['angle']
        self.numssb = self.extraDefaults['numssb']
        self.satBool = self.extraDefaults['satBool']
        self.entries['d'][0].setCurrentIndex(self.extraDefaults['d'] - 1)
        self.entries['method'][0].setCurrentIndex(self.extraDefaults['method'])
        self.changeType(self.extraDefaults['method'])
        super(QuadCzjzekParamFrame, self).reset()

    def changeType(self, index):
        if index == 0:
            for i in range(self.FITNUM): 
                self.entries['cq0'][i].setEnabled(False)
                self.entries['eta0'][i].setEnabled(False)
                self.ticks['cq0'][i].setChecked(True)
                self.ticks['eta0'][i].setChecked(True)
                self.ticks['cq0'][i].setEnabled(False)
                self.ticks['eta0'][i].setEnabled(False)
        elif index == 1:
            for i in range(self.FITNUM): 
                self.entries['cq0'][i].setEnabled(True)
                self.entries['eta0'][i].setEnabled(True)
                self.ticks['cq0'][i].setEnabled(True)
                self.ticks['eta0'][i].setEnabled(True)

    def createCzjzekPrefWindow(self, *args):
        CzjzekPrefWindow(self)

    def simLib(self):
        angle = safeEval(self.angle, type='FI')
        alpha, beta, weight = simFunc.zcw_angles(self.cheng, 2)
        D2 = simFunc.D2tens(alpha, beta, np.zeros_like(alpha))
        D4 = simFunc.D4tens(alpha, beta, np.zeros_like(alpha))
        extra = [self.satBool, self.I, self.numssb, angle, D2, D4, weight, self.mas]
        self.lib, self.cqLib, self.etaLib = simFunc.genLib(len(self.parent.xax()), self.cqmin, self.cqmax, self.etamin, self.etamax, self.cqsteps, self.etasteps, extra, self.parent.freq(), self.parent.sw(), self.spinspeed)
        
    def getExtraParams(self, out):
        if self.lib is None:
            raise FittingException("No library available")
        method = self.entries['method'][0].currentIndex()
        d = self.entries['d'][0].currentIndex() + 1
        out['extra'] = [method, d, self.lib, self.cqLib, self.etaLib]
        return (out, out['extra'])

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['lor'][i][0] == 1:
                self.fitParamList[locList]['lor'][i][0] = abs(self.fitParamList[locList]['lor'][i][0])
           if struc['gauss'][i][0] == 1:
                self.fitParamList[locList]['gauss'][i][0] = abs(self.fitParamList[locList]['gauss'][i][0])
           if struc['sigma'][i][0] == 1:
                self.fitParamList[locList]['sigma'][i][0] = abs(self.fitParamList[locList]['sigma'][i][0])
           if struc['cq0'][i][0] == 1:
                self.fitParamList[locList]['cq0'][i][0] = abs(self.fitParamList[locList]['cq0'][i][0])
           if struc['eta0'][i][0] == 1:
                self.fitParamList[locList]['eta0'][i][0] = 1 - abs(abs(self.fitParamList[locList]['eta0'][i][0])%2 - 1)

#################################################################################


class ExternalFitDeconvWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = ExternalFitDeconvFrame
        self.PARAMFRAME = ExternalFitDeconvParamFrame
        super(ExternalFitDeconvWindow, self).__init__(father, oldMainWindow)

#################################################################################


class ExternalFitDeconvFrame(FitPlotFrame):

    FITNUM = 10  # Maximum number of fits

#################################################################################


class ExternalFitDeconvParamFrame(AbstractParamFrame):

    SINGLENAMES = []
    MULTINAMES = []
    PARAMTEXT = {}
    
    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.externalFitRunScript
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'amp': [1.0, False]}
        super(ExternalFitDeconvParamFrame, self).__init__(parent, rootwindow, isMain)
        self.numExp = QtWidgets.QComboBox()
        self.script = None
        self.txtOutput = [b"", b""]
        loadButton = QtWidgets.QPushButton("Load Script")
        loadButton.clicked.connect(self.loadScript)
        self.optframe.addWidget(loadButton, 0, 0)
        outputButton = QtWidgets.QPushButton("Output")
        outputButton.clicked.connect(self.txtOutputWindow)
        self.optframe.addWidget(outputButton, 1, 0)
        self.optframe.addWidget(wc.QLabel("Command:"), 2, 0)
        self.commandLine = wc.QLineEdit("simpson")
        self.optframe.addWidget(self.commandLine, 3, 0)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 2, 1, 2)
        self.labels = {}
        self.reset()

    def txtOutputWindow(self):
        TxtOutputWindow(self.rootwindow, self.txtOutput[0], self.txtOutput[1])

    def loadScript(self):
        fileName = self.rootwindow.father.loadSIMPSONScript()
        if len(fileName) == 0:
            return
        try:
            with open(fileName, "r") as myfile:
                inFile = myfile.read()
        except Exception:
            raise FittingException("Fitting: No valid script found")
        matches = np.unique(re.findall("(@\w+@)", inFile))
        self.script = inFile
        self.SINGLENAMES = ["offset", "mult"]
        self.MULTINAMES = [e[1:-1] for e in matches]
        self.MULTINAMES.extend(["amp", "lor", "gauss"])
        for n in self.PARAMTEXT.keys():
            self.labels[n][0].deleteLater()
            for i in range(self.FITNUM):
                self.ticks[n][i].deleteLater()
                self.entries[n][i].deleteLater()
        self.PARAMTEXT = {}
        self.labels = {}
        self.ticks = {'offset': [], 'mult': []}
        self.entries = {'offset': [], 'mult': []}
        self.frame2.addWidget(wc.QLabel("Offset:"), 1, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['offset'][-1], 2, 0)
        self.entries['offset'].append(wc.QLineEdit("0.0"))
        self.frame2.addWidget(self.entries['offset'][-1], 2, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 3, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['mult'][-1], 4, 0)
        self.entries['mult'].append(wc.QLineEdit("1.0"))
        self.frame2.addWidget(self.entries['mult'][-1], 4, 1)
        for i in range(len(self.MULTINAMES)):
            name = self.MULTINAMES[i]
            self.PARAMTEXT[name] = name
            self.labels[name] = [wc.QLabel(name)]
            self.frame3.addWidget(self.labels[name][0], 1, 2*i+2, 1, 2)
            self.ticks[name] = []
            self.entries[name] = []
            for j in range(self.FITNUM):
                self.ticks[name].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[name][j], 2+j, 2*i+2)
                self.entries[name].append(wc.FitQLineEdit(self, name))
                self.frame3.addWidget(self.entries[name][j], 2+j, 2*i+3)
        self.reset()

    def getExtraParams(self, out):
        out['extra'] = [self.MULTINAMES, self.commandLine.text(), self.script, self.txtOutput, self.parent.spec()]
        return (out, out['extra'])

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['lor'][i][0] == 1:
                self.fitParamList[locList]['lor'][i][0] = abs(self.fitParamList[locList]['lor'][i][0])
           if struc['gauss'][i][0] == 1:
                self.fitParamList[locList]['gauss'][i][0] = abs(self.fitParamList[locList]['gauss'][i][0])

##############################################################################


class TxtOutputWindow(wc.ToolWindows):

    NAME = "Script Output"
    RESIZABLE = True
    MENUDISABLE = False

    def __init__(self, parent, txt, errTxt):
        super(TxtOutputWindow, self).__init__(parent)
        self.cancelButton.hide()
        self.grid.addWidget(QtWidgets.QLabel("Output:"), 1, 0)
        self.valEntry = QtWidgets.QTextEdit()
        self.valEntry.setReadOnly(True)
        self.valEntry.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.valEntry.setText(txt.decode())
        self.grid.addWidget(self.valEntry, 2, 0)
        self.grid.addWidget(QtWidgets.QLabel("Errors:"), 3, 0)
        self.errEntry = QtWidgets.QTextEdit()
        self.errEntry.setReadOnly(True)
        self.errEntry.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.errEntry.setText(errTxt.decode())
        self.grid.addWidget(self.errEntry, 4, 0)
        self.resize(550, 700)

#################################################################################


class FunctionFitWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = FunctionFitFrame
        self.PARAMFRAME = FunctionFitParamFrame
        super(FunctionFitWindow, self).__init__(father, oldMainWindow)

#################################################################################


class FunctionFitFrame(FitPlotFrame):

    FITNUM = 10  # Maximum number of fits

#################################################################################


class FunctionFitParamFrame(AbstractParamFrame):

    SINGLENAMES = []
    MULTINAMES = []
    PARAMTEXT = {}
    
    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.functionRun
        self.numExp = QtWidgets.QComboBox()
        self.function = ""
        self.DEFAULTS = {}
        super(FunctionFitParamFrame, self).__init__(parent, rootwindow, isMain)
        functionButton = QtWidgets.QPushButton("Input Function")
        functionButton.clicked.connect(self.functionInput)
        self.frame1.addWidget(functionButton, 0, 2)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        self.labels = {}
        self.reset()

    def functionInput(self):
        FunctionInputWindow(self, self.function)

    def functionInputSetup(self):
        matches = np.unique(re.findall("(@\w+@)", self.function))
        self.MULTINAMES = [e[1:-1] for e in matches]
        for n in self.PARAMTEXT.keys():
            self.labels[n][0].deleteLater()
            for i in range(self.FITNUM):
                self.ticks[n][i].deleteLater()
                self.entries[n][i].deleteLater()
        self.PARAMTEXT = {}
        self.labels = {}
        self.ticks = {}
        self.entries = {}
        for i in range(len(self.MULTINAMES)):
            name = self.MULTINAMES[i]
            self.PARAMTEXT[name] = name
            self.labels[name] = [wc.QLabel(name)]
            self.frame3.addWidget(self.labels[name][0], 1, 2*i, 1, 2)
            self.ticks[name] = []
            self.entries[name] = []
            for j in range(self.FITNUM):
                self.ticks[name].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[name][j], 2+j, 2*i)
                self.entries[name].append(wc.FitQLineEdit(self, name))
                self.frame3.addWidget(self.entries[name][j], 2+j, 2*i+1)
        self.reset()

    def getExtraParams(self, out):
        if self.function == "":
            raise FittingException("Fitting: No function defined")
        out["extra"] = [self.MULTINAMES, self.function]
        return (out, out["extra"])

##############################################################################


class FunctionInputWindow(wc.ToolWindows):

    NAME = "Fitting Function"
    RESIZABLE = True
    MENUDISABLE = False

    def __init__(self, parent, txt):
        super(FunctionInputWindow, self).__init__(parent)
        self.grid.addWidget(QtWidgets.QLabel("Function:"), 1, 0)
        self.valEntry = QtWidgets.QTextEdit()
        self.valEntry.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.valEntry.setText(txt)
        self.grid.addWidget(self.valEntry, 2, 0)
        self.resize(550, 400)

    def applyFunc(self):
        self.father.function = self.valEntry.toPlainText()
        self.father.functionInputSetup()

    def closeEvent(self, *args):
        self.deleteLater()

#################################################################################


class FitContourFrame(CurrentContour, FitPlotFrame):

    def __init__(self, rootwindow, fig, canvas, current):
        self.data = current.data
        tmp = np.array(current.data.shape(), dtype=int)
        tmp = np.delete(tmp, self.fixAxes(current.axes))
        self.fitDataList = np.full(tmp, None, dtype=object)
        self.fitPickNumList = np.zeros(tmp, dtype=int)
        self.rootwindow = rootwindow
        CurrentContour.__init__(self, rootwindow, fig, canvas, current.data, current)

    def showFid(self):
        extraX = []
        extraY = []
        extraZ = []
        self.locList = np.array(self.locList, dtype=int)
        if self.fitDataList[self.getRedLocList()] is not None:
            tmp = self.fitDataList[self.getRedLocList()]
            extraX.append(tmp[0][1])
            extraY.append(tmp[0][0])
            extraZ.append(tmp[1])
            for i in range(len(tmp[2])):
                extraX.append(tmp[2][i][1])
                extraY.append(tmp[2][i][0])
                extraZ.append(tmp[3][i])
        if mpl.__version__[0] > '1':
            super(FitContourFrame, self).showFid(extraX=extraX, extraY=extraY, extraZ=extraZ, extraColor=['C'+str(x%10) for x in range(len(extraX))])
        else:
            super(FitContourFrame, self).showFid(extraX=extraX, extraY=extraY, extraZ=extraZ, extraColor=['g']*len(extraX))

##############################################################################


class MqmasDeconvWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = MqmasDeconvFrame
        self.PARAMFRAME = MqmasDeconvParamFrame
        super(MqmasDeconvWindow, self).__init__(father, oldMainWindow)

#################################################################################


class MqmasDeconvFrame(FitContourFrame):

    FITNUM = 10  # Maximum number of fits

#################################################################################


class MqmasDeconvParamFrame(AbstractParamFrame):

    FFT_AXES = (0,1) # Which axes should be transformed after simulation
    DIM = 2
    Ioptions = ['3/2', '5/2', '7/2', '9/2']
    Ivalues = [1.5, 2.5, 3.5, 4.5]
    MQvalues = [3, 5, 7, 9]
    SINGLENAMES = ['offset', 'mult', 'spinspeed']
    MULTINAMES = ['pos', 'cq', 'eta', 'amp', 'lor2', 'gauss2', 'lor1', 'gauss1']
    EXTRANAMES = ['spinType', 'angle', 'numssb','cheng', 'I', 'MQ', 'shear', 'scale']
    PARAMTEXT = {'offset': 'Offset', 'mult':'Multiplier', 'pos': 'Position', 'cq': 'Cq', 'eta': 'eta', 'amp': 'Integral', 'lor2': 'Lorentz 2', 'gauss2': 'Gauss 2', 'lor1': 'Lorentz 1', 'gauss1': 'Gauss 1'}

    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.mqmasFunc
        self.fullInt = np.sum(parent.getData1D()) * parent.sw() / float(parent.getData1D().shape[-1]) * parent.sw(-2) / float(parent.getData1D().shape[-2])
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'spinspeed': [10.0, True], 'pos': [0.0, False], 'cq': [1.0, False], 'eta': [0.0, False], 'amp': [self.fullInt, False], 'lor2': [10.0, False], 'gauss2': [0.0, True], 'lor1': [10.0, False], 'gauss1': [0.0, True]}
        self.extraDefaults = {'spinType': 2, 'angle': "arctan(sqrt(2))", 'numssb': 32, 'cheng': 15, 'I': 0, 'MQ': 0, 'shear': '0.0', 'scale': '1.0'}
        super(MqmasDeconvParamFrame, self).__init__(parent, rootwindow, isMain)
        self.optframe.addWidget(wc.QLabel("MAS:"), 2, 0)
        self.entries['spinType'].append(QtWidgets.QComboBox(self))
        self.entries['spinType'][-1].addItems(["Static", "Finite MAS", "Infinite MAS"])
        self.entries['spinType'][-1].currentIndexChanged.connect(self.MASChange)
        self.optframe.addWidget(self.entries['spinType'][-1], 3, 0)
        self.angleLabel = wc.QLabel("Rotor Angle:")
        self.optframe.addWidget(self.angleLabel, 6, 0)
        self.entries['angle'].append(wc.QLineEdit())
        self.optframe.addWidget(self.entries['angle'][-1], 7, 0)
        self.sidebandLabel = wc.QLabel("# sidebands:")
        self.sidebandLabel.setEnabled(False)
        self.optframe.addWidget(self.sidebandLabel, 0, 1)
        self.entries['numssb'].append(QtWidgets.QSpinBox())
        self.entries['numssb'][-1].setAlignment(QtCore.Qt.AlignHCenter)
        self.entries['numssb'][-1].setMaximum(100000)
        self.entries['numssb'][-1].setMinimum(2)
        self.optframe.addWidget(self.entries['numssb'][-1], 1, 1)
        self.optframe.addWidget(wc.QLabel("Cheng:"), 4, 0)
        self.entries['cheng'].append(QtWidgets.QSpinBox())
        self.entries['cheng'][-1].setAlignment(QtCore.Qt.AlignHCenter)
        self.optframe.addWidget(self.entries['cheng'][-1], 5, 0)
        self.optframe.addWidget(wc.QLabel("I:"), 0, 0)
        self.entries['I'].append(QtWidgets.QComboBox())
        self.entries['I'][-1].addItems(self.Ioptions)
        self.optframe.addWidget(self.entries['I'][-1], 1, 0)
        self.optframe.addWidget(wc.QLabel("MQ:"), 2, 1)
        self.entries['MQ'].append(QtWidgets.QComboBox())
        self.entries['MQ'][-1].addItems([str(i) for i in self.MQvalues])
        self.optframe.addWidget(self.entries['MQ'][-1], 3, 1)
        self.optframe.addWidget(wc.QLabel("Shear:"), 4, 1)
        self.entries['shear'].append(wc.QLineEdit())
        self.optframe.addWidget(self.entries['shear'][-1], 5, 1)
        self.optframe.addWidget(wc.QLabel("Scale sw:"), 6, 1)
        self.entries['scale'].append(wc.QLineEdit())
        self.optframe.addWidget(self.entries['scale'][-1], 7, 1)
        autoButton = QtWidgets.QPushButton("&Auto")
        autoButton.clicked.connect(self.autoShearScale)
        self.optframe.addWidget(autoButton, 8, 1)
        self.spinLabel = wc.QLabel("Spin. speed [kHz]:")
        self.frame2.addWidget(self.spinLabel, 0, 0, 1, 2)
        self.ticks['spinspeed'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['spinspeed'][-1], 1, 0)
        self.entries['spinspeed'].append(wc.QLineEdit())
        self.frame2.addWidget(self.entries['spinspeed'][-1], 1, 1)
        self.frame2.addWidget(wc.QLabel("Offset:"), 2, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['offset'][-1], 3, 0)
        self.entries['offset'].append(wc.QLineEdit())
        self.frame2.addWidget(self.entries['offset'][-1], 3, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 4, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.frame2.addWidget(self.ticks['mult'][-1], 5, 0)
        self.entries['mult'].append(wc.QLineEdit())
        self.frame2.addWidget(self.entries['mult'][-1], 5, 1)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        if self.parent.viewSettings["ppm"][-1]:
            axUnit = 'ppm'
        else:
            axUnit = ['Hz', 'kHz', 'MHz'][self.parent.getAxType()]
        # Labels
        self.labelpos = wc.QLabel(u'Position [' + axUnit + ']:')
        self.labelcq = wc.QLabel(u'C<sub>Q</sub> [MHz]:')
        self.labeleta = wc.QLabel(u'η:')
        self.frame3.addWidget(self.labelpos, 1, 0, 1, 2)
        self.frame3.addWidget(self.labelcq, 1, 2, 1, 2)
        self.frame3.addWidget(self.labeleta, 1, 4, 1, 2)
        self.frame3.addWidget(wc.QLabel("Integral:"), 1, 6, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz 2 [Hz]:"), 1, 8, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss 2 [Hz]:"), 1, 10, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz 1 [Hz]:"), 1, 12, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss 1 [Hz]:"), 1, 14, 1, 2)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def reset(self):
        self.entries['angle'][-1].setText(self.extraDefaults['angle'])
        self.entries['spinType'][-1].setCurrentIndex(self.extraDefaults['spinType'])
        self.entries['numssb'][-1].setValue(self.extraDefaults['numssb'])
        self.entries['cheng'][-1].setValue(self.extraDefaults['cheng'])
        self.entries['I'][-1].setCurrentIndex(self.extraDefaults['I'])
        self.entries['MQ'][-1].setCurrentIndex(self.extraDefaults['MQ'])
        self.entries['shear'][-1].setText(self.extraDefaults['shear'])
        self.entries['scale'][-1].setText(self.extraDefaults['scale'])
        self.MASChange(self.extraDefaults['spinType'])
        super(MqmasDeconvParamFrame, self).reset()

    def autoShearScale(self, *args):
        from fractions import gcd
        I = self.entries['I'][-1].currentIndex() + 3/2.0
        mq = self.MQvalues[self.entries['MQ'][-1].currentIndex()]
        m = 0.5 * mq
        numerator = m * (18 * I * (I + 1) - 34 * m**2 - 5)
        denomenator = 0.5 * (18 * I * (I + 1) - 34 * 0.5**2 - 5)
        divis = gcd(numerator, denomenator)
        numerator /= divis
        denomenator /= divis
        self.entries['shear'][-1].setText(str(numerator) + '/' + str(denomenator))
        self.entries['scale'][-1].setText(str(denomenator) + '/' + str(mq * denomenator - numerator))
        
    def MASChange(self, MAStype):
        if MAStype > 0:
            self.angleLabel.setEnabled(True)
            self.entries['angle'][-1].setEnabled(True)
        else:
            self.angleLabel.setEnabled(False)
            self.entries['angle'][-1].setEnabled(False)
        if MAStype == 1:  # Finite MAS
            self.entries['spinspeed'][-1].setEnabled(True)
            self.ticks['spinspeed'][-1].setEnabled(True)
            self.spinLabel.setEnabled(True)
            self.entries['numssb'][-1].setEnabled(True)
            self.sidebandLabel.setEnabled(True)
        else:
            self.ticks['spinspeed'][-1].setChecked(True)
            self.entries['spinspeed'][-1].setEnabled(False)
            self.ticks['spinspeed'][-1].setEnabled(False)
            self.spinLabel.setEnabled(False)
            self.entries['numssb'][-1].setEnabled(False)
            self.sidebandLabel.setEnabled(False)
        
    def getExtraParams(self, out):
        angle = safeEval(self.entries['angle'][-1].text())
        if angle is None:
            raise FittingException("Fitting: Rotoe Angle is not valid")
        I = self.entries['I'][-1].currentIndex() + 3/2.0
        MQ = self.MQvalues[self.entries['MQ'][-1].currentIndex()]
        if MQ > (I*2):
            raise RuntimeError("MQ cannot be larger than I")
        cheng = safeEval(self.entries['cheng'][-1].text())
        alpha, beta, weight = simFunc.zcw_angles(cheng, 2)
        D2 = simFunc.D2tens(alpha, beta, np.zeros_like(alpha))
        D4 = simFunc.D4tens(alpha, beta, np.zeros_like(alpha))
        numssb = self.entries['numssb'][-1].value()
        MAStype = self.entries['spinType'][-1].currentIndex()
        shear = safeEval(self.entries['shear'][-1].text())
        scale = safeEval(self.entries['scale'][-1].text())
        out['extra'] = [I, MQ, numssb, angle, D2, D4, weight, shear, scale, MAStype]
        return (out, out['extra'])

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['lor1'][i][0] == 1:
                self.fitParamList[locList]['lor1'][i][0] = abs(self.fitParamList[locList]['lor1'][i][0])
           if struc['gauss1'][i][0] == 1:
                self.fitParamList[locList]['gauss1'][i][0] = abs(self.fitParamList[locList]['gauss1'][i][0])
           if struc['lor2'][i][0] == 1:
                self.fitParamList[locList]['lor2'][i][0] = abs(self.fitParamList[locList]['lor2'][i][0])
           if struc['gauss2'][i][0] == 1:
                self.fitParamList[locList]['gauss2'][i][0] = abs(self.fitParamList[locList]['gauss2'][i][0])
           if struc['eta'][i][0] == 1:
                #eta is between 0--1 in a continuous way.
                self.fitParamList[locList]['eta'][i][0] = 1 - abs(abs(self.fitParamList[locList]['eta'][i][0]) % 2 - 1)
           if struc['cq'][i][0] == 1:
                self.fitParamList[locList]['cq'][i][0] = abs(self.fitParamList[locList]['cq'][i][0])

##############################################################################

class MqmasCzjzekWindow(TabFittingWindow):

    def __init__(self, father, oldMainWindow):
        self.CURRENTWINDOW = MqmasDeconvFrame
        self.PARAMFRAME = MqmasCzjzekParamFrame
        super(MqmasCzjzekWindow, self).__init__(father, oldMainWindow)

#################################################################################


class MqmasCzjzekParamFrame(AbstractParamFrame):

    FFT_AXES = (0,) # Which axes should be transformed after simulation
    DIM = 2
    Ioptions = ['3/2', '5/2', '7/2', '9/2']
    Ivalues = [1.5, 2.5, 3.5, 4.5]
    MQvalues = [3, 5, 7, 9]
    SINGLENAMES = ['offset', 'mult']
    MULTINAMES = ['pos', 'sigma', 'sigmaCS', 'cq0', 'eta0', 'amp', 'lor2', 'gauss2', 'lor1', 'gauss1']
    EXTRANAMES = ['method', 'd', 'MQ', 'shear', 'scale']
    PARAMTEXT = {'offset': 'Offset', 'mult': 'Multiplier', 'pos': 'Position', 'sigma': 'Sigma', 'sigmaCS': 'Sigma CS', 'cq0': 'Cq0', 'eta0': 'Eta0', 'amp': 'Integral', 'lor': 'Lorentz', 'gauss': 'Gauss'}

    def __init__(self, parent, rootwindow, isMain=True):
        self.FITFUNC = simFunc.mqmasCzjzekFunc
        self.fullInt = np.sum(parent.getData1D()) * parent.sw() / float(parent.getData1D().shape[-1]) * parent.sw(-2) / float(parent.getData1D().shape[-2])
        self.DEFAULTS = {'offset': [0.0, True], 'mult': [1.0, True], 'pos': [0.0, False], 'sigma': [1.0, False], 'sigmaCS': [10.0, False], 'cq0': [0.0, True], 'eta0': [0.0, True], 'amp': [self.fullInt, False], 'lor2': [10.0, False], 'gauss2': [0.0, True], 'lor1': [10.0, False], 'gauss1': [0.0, True]}
        self.extraDefaults = {'mas': 2, 'method': 0, 'd': 5, 'cheng': 15, 'I': 3/2.0, 'MQ': 0, 'shear': '0.0', 'scale': '1.0',
                'cqsteps': 50, 'etasteps': 10, 'cqmax': 4, 'cqmin': 0, 'etamax': 1, 'etamin': 0, 'lib': None, 'cqLib': None, 'etaLib': None}
        super(MqmasCzjzekParamFrame, self).__init__(parent, rootwindow, isMain)
        czjzekPrefButton = QtWidgets.QPushButton("Library")
        czjzekPrefButton.clicked.connect(self.createCzjzekPrefWindow)
        self.optframe.addWidget(czjzekPrefButton, 4, 0)
        self.optframe.addWidget(wc.QLabel("MQ:"), 0, 1)
        self.entries['MQ'].append(QtWidgets.QComboBox())
        self.entries['MQ'][-1].addItems([str(i) for i in self.MQvalues])
        self.optframe.addWidget(self.entries['MQ'][-1], 1, 1)
        self.optframe.addWidget(wc.QLabel("Shear:"), 2, 1)
        self.entries['shear'].append(wc.QLineEdit())
        self.optframe.addWidget(self.entries['shear'][-1], 3, 1)
        self.optframe.addWidget(wc.QLabel("Scale sw:"), 4, 1)
        self.entries['scale'].append(wc.QLineEdit())
        self.optframe.addWidget(self.entries['scale'][-1], 5, 1)
        autoButton = QtWidgets.QPushButton("&Auto")
        autoButton.clicked.connect(self.autoShearScale)
        self.optframe.addWidget(autoButton, 6, 1)
        self.frame2.addWidget(wc.QLabel("Offset:"), 0, 0, 1, 2)
        self.ticks['offset'].append(QtWidgets.QCheckBox(''))
        self.ticks['offset'][-1].setChecked(True)
        self.frame2.addWidget(self.ticks['offset'][-1], 1, 0)
        self.entries['offset'].append(wc.FitQLineEdit(self, 'offset', ""))
        self.frame2.addWidget(self.entries['offset'][-1], 1, 1)
        self.frame2.addWidget(wc.QLabel("Multiplier:"), 2, 0, 1, 2)
        self.ticks['mult'].append(QtWidgets.QCheckBox(''))
        self.ticks['mult'][-1].setChecked(True)
        self.frame2.addWidget(self.ticks['mult'][-1], 3, 0)
        self.entries['mult'].append(wc.FitQLineEdit(self, 'mult', ""))
        self.frame2.addWidget(self.entries['mult'][-1], 3, 1)
        self.optframe.addWidget(wc.QLabel("Type:"), 0, 0)
        self.entries['method'].append(QtWidgets.QComboBox())
        self.entries['method'][0].addItems(['Normal', 'Extended'])
        self.entries['method'][0].currentIndexChanged.connect(self.changeType)
        self.optframe.addWidget(self.entries['method'][0], 1, 0)
        self.optframe.addWidget(wc.QLabel("d:"), 2, 0)
        self.entries['d'].append(QtWidgets.QComboBox())
        self.entries['d'][0].addItems(['1', '2', '3', '4', '5'])
        self.optframe.addWidget(self.entries['d'][0], 3, 0)
        self.numExp = QtWidgets.QComboBox()
        self.numExp.addItems([str(x + 1) for x in range(self.FITNUM)])
        self.numExp.currentIndexChanged.connect(self.changeNum)
        self.frame3.addWidget(self.numExp, 0, 0, 1, 2)
        if self.parent.viewSettings["ppm"][-1]:
            axUnit = 'ppm'
        else:
            axUnit = ['Hz', 'kHz', 'MHz'][self.parent.getAxType()]
        self.frame3.addWidget(wc.QLabel("Pos [" + axUnit + "]:"), 1, 0, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"σ [MHz]:"), 1, 2, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"σCS [Hz]:"), 1, 4, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"C<sub>Q</sub>0 [MHz]:"), 1, 6, 1, 2)
        self.frame3.addWidget(wc.QLabel(u"η0:"), 1, 8, 1, 2)
        self.frame3.addWidget(wc.QLabel("Integral:"), 1, 10, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz 2 [Hz]:"), 1, 12, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss 2 [Hz]:"), 1, 14, 1, 2)
        self.frame3.addWidget(wc.QLabel("Lorentz 1 [Hz]:"), 1, 16, 1, 2)
        self.frame3.addWidget(wc.QLabel("Gauss 1 [Hz]:"), 1, 18, 1, 2)
        for i in range(self.FITNUM):
            for j in range(len(self.MULTINAMES)):
                self.ticks[self.MULTINAMES[j]].append(QtWidgets.QCheckBox(''))
                self.frame3.addWidget(self.ticks[self.MULTINAMES[j]][i], i + 2, 2 * j)
                self.entries[self.MULTINAMES[j]].append(wc.FitQLineEdit(self, self.MULTINAMES[j]))
                self.frame3.addWidget(self.entries[self.MULTINAMES[j]][i], i + 2, 2 * j + 1)
        self.reset()

    def reset(self):
        self.cqsteps = self.extraDefaults['cqsteps']
        self.etasteps = self.extraDefaults['etasteps']
        self.cqmax = self.extraDefaults['cqmax']
        self.cqmin = self.extraDefaults['cqmin']
        self.etamax = self.extraDefaults['etamax']
        self.etamin = self.extraDefaults['etamin']
        self.lib = self.extraDefaults['lib']
        self.cqLib = self.extraDefaults['cqLib']
        self.etaLib = self.extraDefaults['etaLib']
        self.I = self.extraDefaults['I']
        self.cheng = self.extraDefaults['cheng']
        self.mas = self.extraDefaults['mas']
        self.entries['MQ'][-1].setCurrentIndex(self.extraDefaults['MQ'])
        self.entries['shear'][-1].setText(self.extraDefaults['shear'])
        self.entries['scale'][-1].setText(self.extraDefaults['scale'])
        self.entries['method'][-1].setCurrentIndex(self.extraDefaults['method'])
        self.entries['d'][-1].setCurrentIndex(self.extraDefaults['d'] - 1)
        self.changeType(self.extraDefaults['method'])
        super(MqmasCzjzekParamFrame, self).reset()

    def autoShearScale(self, *args):
        from fractions import gcd
        mq = self.MQvalues[self.entries['MQ'][-1].currentIndex()]
        m = 0.5 * mq
        numerator = m * (18 * self.I * (self.I + 1) - 34 * m**2 - 5)
        denomenator = 0.5 * (18 * self.I * (self.I + 1) - 34 * 0.5**2 - 5)
        divis = gcd(numerator, denomenator)
        numerator /= divis
        denomenator /= divis
        self.entries['shear'][-1].setText(str(numerator) + '/' + str(denomenator))
        self.entries['scale'][-1].setText(str(denomenator) + '/' + str(mq * denomenator - numerator))
        
    def changeType(self, index):
        if index == 0:
            for i in range(self.FITNUM): 
                self.entries['cq0'][i].setEnabled(False)
                self.entries['eta0'][i].setEnabled(False)
                self.ticks['cq0'][i].setChecked(True)
                self.ticks['eta0'][i].setChecked(True)
                self.ticks['cq0'][i].setEnabled(False)
                self.ticks['eta0'][i].setEnabled(False)
        elif index == 1:
            for i in range(self.FITNUM): 
                self.entries['cq0'][i].setEnabled(True)
                self.entries['eta0'][i].setEnabled(True)
                self.ticks['cq0'][i].setEnabled(True)
                self.ticks['eta0'][i].setEnabled(True)

    def createCzjzekPrefWindow(self, *args):
        CzjzekPrefWindow(self, mqmas=True)

    def simLib(self):
        angle = np.arctan(np.sqrt(2))
        alpha, beta, weight = simFunc.zcw_angles(self.cheng, 2)
        D2 = simFunc.D2tens(alpha, beta, np.zeros_like(alpha))
        D4 = simFunc.D4tens(alpha, beta, np.zeros_like(alpha))
        extra = [False, self.I, 2, angle, D2, D4, weight, 2]
        self.lib, self.cqLib, self.etaLib = simFunc.genLib(len(self.parent.xax()), self.cqmin, self.cqmax, self.etamin, self.etamax, self.cqsteps, self.etasteps, extra, self.parent.freq(), self.parent.sw(), np.inf)

    def getExtraParams(self, out):
        if self.lib is None:
            raise FittingException("No library available")
        MQ = self.MQvalues[self.entries['MQ'][-1].currentIndex()]
        if MQ > (self.I*2):
            raise FittingException("MQ cannot be larger than I")
        shear = safeEval(self.entries['shear'][-1].text())
        scale = safeEval(self.entries['scale'][-1].text())
        I = self.I
        method = self.entries['method'][0].currentIndex()
        d = self.entries['d'][0].currentIndex() + 1
        out['extra'] = [I, MQ, self.cqLib, self.etaLib, self.lib, shear, scale, method, d]
        return (out, out['extra'])

    def checkResults(self,numExp,struc):
        #After fit, set lor and gauss absolute
        locList = self.getRedLocList()
        for i in range(numExp):
           if struc['lor1'][i][0] == 1:
                self.fitParamList[locList]['lor1'][i][0] = abs(self.fitParamList[locList]['lor1'][i][0])
           if struc['gauss1'][i][0] == 1:
                self.fitParamList[locList]['gauss1'][i][0] = abs(self.fitParamList[locList]['gauss1'][i][0])
           if struc['lor2'][i][0] == 1:
                self.fitParamList[locList]['lor2'][i][0] = abs(self.fitParamList[locList]['lor2'][i][0])
           if struc['gauss2'][i][0] == 1:
                self.fitParamList[locList]['gauss2'][i][0] = abs(self.fitParamList[locList]['gauss2'][i][0])
           if struc['eta0'][i][0] == 1:
                #eta is between 0--1 in a continuous way.
                self.fitParamList[locList]['eta0'][i][0] = 1 - abs(abs(self.fitParamList[locList]['eta0'][i][0]) % 2 - 1)
           if struc['cq0'][i][0] == 1:
                self.fitParamList[locList]['cq0'][i][0] = abs(self.fitParamList[locList]['cq0'][i][0])

