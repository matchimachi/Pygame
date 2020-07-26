import ctypes
from distutils.version import LooseVersion
import io
import os
import platform
import re

from anaconda_navigator.api.download_api import DownloadAPI
from anaconda_navigator.config import (BITS_32, BITS_64, CONF_PATH, HOME_PATH,
                                       LINUX, MAC, OS_64_BIT, WIN)
from anaconda_navigator.utils.logs import logger


class BaseApp(object):
    def __init__(self, config, filename,
                 windows_ext, windows_folder_name,
                 mac_name, display_name, app_name,
                 description, image_path, needs_license,
                 non_conda, distro_map, process_api, conda_api):
        self.config = config
        self.filename = filename
        self.windows_ext = windows_ext
        self.windows_folder_name = windows_folder_name
        self.mac_name = mac_name
        self.display_name = display_name
        self.app_name = app_name
        self.description = description
        self.image_path = image_path
        self.needs_license = needs_license
        self.non_conda = non_conda
        self.distro_map = distro_map
        self._process_api = process_api
        self._conda_api = conda_api

        # These download methods return a worker
        self._download_api = DownloadAPI(config=config)
        _is_valid_url = self._download_api.is_valid_api_url
        self.download = self._download_api.download
        self.download_is_valid_api_url = _is_valid_url
        self.download_is_valid_channel = self._download_api.is_valid_channel
        self.download_terminate = self._download_api.terminate

        self.init()

    # --- App Handling
    # -------------------------------------------------------------------------
    def init(self):
        """Initialize App setttings for install."""
        DISTRO_NAME = ''
        DISTRO_VER = ''
        INST_DIR_FOUND = None

        self._DISTRO_VER = None

        if WIN:
            SUBDIR, INST_EXT, INST_DIR = self._find_win_install_dir()
        elif MAC:
            SUBDIR, INST_EXT, INST_DIR = self._find_mac_install_dir()
        elif LINUX:
            SUBDIR, INST_EXT, INST_DIR = self._find_linux_install_dir()

        INSTFILE = os.path.join(
            CONF_PATH,
            'temp',
            'apptemp.{}'.format(INST_EXT),
        )

        self._DISTRO_NAME = DISTRO_NAME
        self._DISTRO_VER = DISTRO_VER
        self._SUBDIR = SUBDIR
        self._INST_DIR = INST_DIR
        self._INSTFILE = INSTFILE

    def _find_win_install_dir(self):
        from anaconda_navigator.external.knownfolders import (
            get_folder_path,
            FOLDERID,
        )
        INST_EXT = 'exe'

        _kernel32 = ctypes.windll.kernel32
        _windir = ctypes.create_unicode_buffer(1024)
        _kernel32.GetWindowsDirectoryW(_windir, 1024)
        _windrive = _windir.value[:3]

        if BITS_32:
            SUBDIR = 'win32-user'
            PROGRAM_FILES = get_folder_path(FOLDERID.ProgramFilesX86)[0]
            _fallback = os.path.join(_windrive, 'Program Files (x86)')
        elif BITS_64:
            SUBDIR = 'win32-x64-user'
            PROGRAM_FILES = get_folder_path(FOLDERID.ProgramFilesX64)[0]
            _fallback = os.path.join(_windrive, 'Program Files')

        LOCAL_DATA = get_folder_path(FOLDERID.LocalAppData)[0]
        PROGRAM_FILES_64 = (
            get_folder_path(FOLDERID.ProgramFilesX64)[0]
            or os.path.join(_windrive, 'Program Files')
        )

        if PROGRAM_FILES is None:
            PROGRAM_FILES = os.environ.get('ProgramFiles', _fallback)

        # Check the correct location System vs. User bit independent
        INST_DIR_FOUND = None
        if os.path.exists(
            os.path.join(PROGRAM_FILES, self.windows_folder_name)
        ):
            INST_DIR_FOUND = os.path.join(
                PROGRAM_FILES, self.windows_folder_name
            )
        elif PROGRAM_FILES_64 and os.path.exists(
            os.path.join(PROGRAM_FILES_64, self.windows_folder_name)
        ):
            INST_DIR_FOUND = os.path.join(
                PROGRAM_FILES_64, self.windows_folder_name
            )
        else:
            INST_DIR_FOUND = os.path.join(
                LOCAL_DATA, self.windows_folder_name
            )
            if not os.path.isdir(INST_DIR_FOUND):
                INST_DIR_FOUND = os.path.join(LOCAL_DATA, 'Programs', self.windows_folder_name)

        return SUBDIR, INST_EXT, INST_DIR_FOUND

    def _find_mac_install_dir(self):
        SUBDIR = 'darwin'
        INST_EXT = 'zip'
        INST_DIR = os.path.join('/Applications')
        return SUBDIR, INST_EXT, INST_DIR

    def _find_linux_install_dir(self):
        raise NotImplementedError

    @property
    def executable(self):
        quote = '"' if ' ' in self._EXE else ''
        return quote + self._EXE + quote if os.path.exists(self._EXE) else None

    @property
    def is_available(self):
        """Is App available for installation on this platform."""
        try:
            if WIN:
                # Not checking XP, let their installer cry
                return True
            elif MAC:
                v = LooseVersion(platform.mac_ver()[0]) >= LooseVersion('10.11')
                return v
            elif LINUX:
                _distro_min_ver = self._DISTRO_MAP[self._DISTRO_NAME]
                return (
                    (len(self._DISTRO_NAME) > 0)
                    and (len(self._DISTRO_VER) > 0) and (
                        LooseVersion(self._DISTRO_VER) >=
                        LooseVersion(_distro_min_ver)
                    )
                )  # NOQA
        except Exception:
            return False
        return False

    @property
    def installed(self):
        """Return the installed status of the package."""
        return bool(self.executable)

    def log_path(self, uninstall=False, delete=False):
        """Return the log path for installer/uninstaller."""
        if uninstall:
            fname = '{}-uninstall-log.txt'.format(self.app_name)
        else:
            fname = '{}-install-log.txt'.format(self.app_name)

        log_path = os.path.join(CONF_PATH, 'temp', fname)

        if delete and os.path.isfile(log_path):
            try:
                os.remove(log_path)
            except Exception:
                pass

        return log_path

    def log_data(self, uninstall=False):
        """Return the parsed log data from installer/uninstaller."""
        log_path = self.log_path(uninstall=uninstall)

        if os.path.isfile(log_path):
            with io.open(log_path, 'r') as f:
                f.read()

        # TODO: load data!
        log_data = {'successful': True}
        return log_data

    @property
    def install_enabled(self):
        # Add App global app (if it does not exist as a conda package)
        return self.config.get('home', '{}_enable'.format(self.app_name))

    def create_config_backup(self, data):
        """
        Create a backup copy of the app configuration file `data`.

        Leave only the last 10 backups.
        """
        raise NotImplementedError

    def update_config(self, prefix):
        """Update app python interpreter user config."""
        raise NotImplementedError

    def install(self, password=None):
        """Install app."""
        raise NotImplementedError

    def install_extensions(self):
        """Install app extensions."""
        raise NotImplementedError

    def send_telemtry(self):
        """Send app telemetry."""
        raise NotImplementedError

    def win_uninstaller(self):
        """Check the right uninstaller file on windows."""
        raise NotImplementedError

    def remove(self, password=None):
        """Remove app files from computer or run uninstaller."""
        raise NotImplementedError
