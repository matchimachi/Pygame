# This file is generated by numpy's setup.py
# It contains system_info results at the time of building this package.
__all__ = ["get_info","show"]


import os
import sys

extra_dll_dir = os.path.join(os.path.dirname(__file__), '.libs')
if sys.platform == 'win32' and os.path.isdir(extra_dll_dir):
    os.environ.setdefault('PATH', '')
    os.environ['PATH'] += os.pathsep + extra_dll_dir
mkl_info={'libraries': ['mkl_rt'], 'library_dirs': ['C:/Users/matis/anaconda3\\Library\\lib'], 'define_macros': [('SCIPY_MKL_H', None), ('HAVE_CBLAS', None)], 'include_dirs': ['C:/Users/matis/anaconda3\\Library\\include']}

def get_info(name):
    g = globals()
    return g.get(name, g.get(name + "_info", {}))

def show():
    for name,info_dict in list(globals().items()):
        if name[0] == "_" or type(info_dict) is not type({}): continue
        print((name + ":"))
        if not info_dict:
            print("  NOT AVAILABLE")
        for k,v in list(info_dict.items()):
            v = str(v)
            if k == "sources" and len(v) > 200:
                v = v[:60] + " ...\n... " + v[-60:]
            print(("    %s = %s" % (k,v)))
    