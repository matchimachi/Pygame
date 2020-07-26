
# THIS FILE WAS AUTOMATICALLY GENERATED BY deprecated_modules.py
import sys
# mypy error: Module X has no attribute y (typically for C extensions)
from . import _twenty_newsgroups  # type: ignore
from ..externals._pep562 import Pep562
from ..utils.deprecation import _raise_dep_warning_if_not_pytest

deprecated_path = 'sklearn.datasets.twenty_newsgroups'
correct_import_path = 'sklearn.datasets'

_raise_dep_warning_if_not_pytest(deprecated_path, correct_import_path)

def __getattr__(name):
    return getattr(_twenty_newsgroups, name)

if not sys.version_info >= (3, 7):
    Pep562(__name__)
