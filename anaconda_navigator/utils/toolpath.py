# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright (c) 2020 Anaconda, Inc.
#
# May be copied and distributed freely only as part of an Anaconda or
# Miniconda installation.
# -----------------------------------------------------------------------------
"""Tool path utilties."""

import os
import sys

def get_pyexec(prefix):
    """Provides the full path to python executable"""
    rslt = ''
    if sys.platform == "win32":
        rslt += os.sep.join([prefix, 'python.exe'])
    else:
        rslt += os.sep.join([prefix, 'bin', 'python'])
    return rslt

def get_pyscript(prefix, name):
    """Provides the OS dependent path in bin/Scripts for python script tool"""
    rslt = ''
    if sys.platform == "win32":
        rslt += os.sep.join([prefix, 'Scripts', name + '-script.py'])
    else:
        rslt += os.sep.join([prefix, 'bin', name])
    return rslt

