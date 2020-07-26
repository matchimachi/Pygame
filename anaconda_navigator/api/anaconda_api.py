# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright (c) 2016-2017 Anaconda, Inc.
#
# May be copied and distributed freely only as part of an Anaconda or
# Miniconda installation.
# -----------------------------------------------------------------------------
"""API for using the api (anaconda-client, downloads and conda)."""

# yapf: disable

# Standard library imports
from collections import OrderedDict
import bz2
import copy
import datetime
import json
import os
import shutil
import sys
import time

# Third party imports
from qtpy.QtCore import QObject, QTimer, Signal
import psutil

# Local imports
from anaconda_navigator.api.client_api import ClientAPI
from anaconda_navigator.api.conda_api import CondaAPI
from anaconda_navigator.api.download_api import DownloadAPI
from anaconda_navigator.api.process import DummyWorker, WorkerManager
from anaconda_navigator.api.project_api import ProjectAPI
from anaconda_navigator.api import external_apps
from anaconda_navigator.config import (CONF, LAUNCH_SCRIPTS_PATH,
                                       LICENSE_NAME_FOR_PACKAGE, LICENSE_PATH,
                                       METADATA_PATH, PACKAGES_WITH_LICENSE,
                                       REMOVED_LICENSE_PATH,
                                       VALID_PRODUCT_LICENSES, WIN)
from anaconda_navigator.static import content, images
from anaconda_navigator.utils import constants as C
from anaconda_navigator.utils.logs import logger

from anaconda_navigator.utils.py3compat import PY2, is_binary_string

from anaconda_navigator.utils.misc import path_is_writable, ensure_list


# yapf: enable

try:
    import _license
    LICENSE_PACKAGE = True
except ImportError:
    LICENSE_PACKAGE = False


class _AnacondaAPI(QObject):
    """
    Anaconda Manager API.

    This class contains all methods from the different apis and acts as
    a controller for the main actions Navigator needs to execute.
    """
    sig_metadata_updated = Signal(object)  # metadata_dictionary
    sig_repodata_loaded = Signal(object, object)  # packages, apps

    sig_repodata_updated = Signal(object)
    sig_repodata_errored = Signal()
    sig_error = Signal()

    def __init__(self):
        """Anaconda Manager API process worker."""
        super(_AnacondaAPI, self).__init__()

        # API's
        self.config = CONF
        self._conda_api = CondaAPI()
        self._client_api = ClientAPI(config=self.config)
        self._download_api = DownloadAPI(config=self.config)
        self._project_api = ProjectAPI()
        self._process_api = WorkerManager()
        self.ROOT_PREFIX = self._conda_api.ROOT_PREFIX
        self.CONDA_PREFIX = self._conda_api.CONDA_PREFIX
        self._metadata = {}

        # Variables
        self._data_directory = None

        # Expose some methods for convenient access. Methods return a worker
        self.conda_dependencies = self._conda_api.dependencies
        self.conda_remove = self._conda_api.remove
        self.conda_terminate = self._conda_api.terminate_all_processes
        # self.conda_config = self._conda_api.config_show
        # self.conda_config_sources = self._conda_api.config_show_sources
        self.conda_config_add = self._conda_api.config_add
        self.conda_config_set = self._conda_api.config_set
        self.conda_config_remove = self._conda_api.config_remove
        self.download = self._download_api.download
        self.download_is_valid_url = self._download_api.is_valid_url
        _is_valid_url = self._download_api.is_valid_api_url
        _get_api_info = self._download_api.get_api_info
        _get_api_url = self._client_api.get_api_url
        self.download_is_valid_api_url = _is_valid_url
        self.download_get_api_info = lambda: _get_api_info(_get_api_url())
        self.download_is_valid_channel = self._download_api.is_valid_channel
        self.download_terminate = self._download_api.terminate

        # No workers are returned for these methods
        self.conda_clear_lock = self._conda_api.clear_lock
        self.conda_environment_exists = self._conda_api.environment_exists
        self.conda_get_envs = self._conda_api.get_envs
        self.conda_linked = self._conda_api.linked
        self.conda_linked_apps_info = self._conda_api.linked_apps_info
        self.conda_get_prefix_envname = self._conda_api.get_prefix_envname
        self.conda_package_version = self._conda_api.package_version
        self.conda_platform = self._conda_api.get_platform
        self.conda_load_proxy_config = self._conda_api.load_proxy_config

        self.conda_split_canonical_name = self._conda_api.split_canonical_name

        # These client methods return a worker
        self.client_login = self._client_api.login
        self.client_logout = self._client_api.logout
        self.client_user = self._client_api.user
        self.client_get_api_url = self._client_api.get_api_url
        self.client_set_api_url = self._client_api.set_api_url
        self.client_get_ssl = self._client_api.get_ssl
        self.client_set_ssl = self._client_api.set_ssl
        self.client_get_user_licenses = self._client_api.get_user_licenses
        self.client_domain = self._client_api.domain
        self.client_reload = self._client_api.reload_binstar_client

        # Project calls
        self.project_create = self._project_api.create_project
        self.project_upload = self._project_api.upload
        self.project_load = self._project_api.load_project

    # --- Public API
    # -------------------------------------------------------------------------
    def set_data_directory(self, data_directory):
        """Set the directory where metadata is stored."""
        logger.debug('data_directory: {}'.format(data_directory))
        self._data_directory = data_directory

    def check_valid_channel(
        self, channel, conda_url='https://conda.anaconda.org'
    ):
        """Check if channel is valid."""
        logger.debug('channel: {}, conda_url: {}'.format(channel, conda_url))

        if channel.startswith('https://') or channel.startswith('http://'):
            url = channel
        else:
            url = "{0}/{1}".format(conda_url, channel)

        if url[-1] == '/':
            url = url[:-1]
        plat = self.conda_platform()
        repodata_url = "{0}/{1}/{2}".format(url, plat, 'repodata.json')
        worker = self.download_is_valid_url(repodata_url)
        worker.url = url
        return worker

    def check_pid(self, processes, package_name, command, prefix):
        """Check pids and child spawned by pid."""
        dummy_worker = DummyWorker()
        wm = self._process_api

        def _check_pid(processes, package_name, command, prefix):
            """Check pids and child spawned by pid."""
            pids = set(processes)
            count = 0
            while count < 50:
                new_pids = set()
                for pid in pids:
                    if psutil.pid_exists(pid):
                        proc = psutil.Process(pid)
                        for p in proc.children(recursive=True):
                            new_pids.add(p.pid)
                count += 1
                pids = pids.union(new_pids)

            pids = list(sorted(pids))
            data = {
                'pids': pids,
                'package': package_name,
                'command': command,
                'prefix': prefix,
            }

            return data

        def _finished(worker, output, error):
            """Callback for _check_pid."""
            logger.debug((output, error))
            dummy_worker.sig_finished.emit(dummy_worker, output, error)

        worker = wm.create_python_worker(
            _check_pid,
            processes,
            package_name,
            command,
            prefix,
        )
        worker.sig_partial.connect(dummy_worker.sig_partial)
        worker.sig_finished.connect(_finished)
        worker.start()

        return dummy_worker

    # --- Client
    # -------------------------------------------------------------------------
    def is_internet_available(self):
        """Check initernet availability."""
        if self.config.get('main', 'offline_mode'):
            connectivity = False
        else:
            connectivity = True  # is_internet_available()

        return connectivity

    def is_offline(self):
        """"""
        return not self.is_internet_available()

    def login(self, username, password):
        """
        Login to anaconda cloud via the anaconda-client API.

        This method does not use workers.
        """
        logger.debug(
            'username: {}, password: {}'.format(username, '*' * len(password))
        )
        return self._client_api.login(
            username, password, 'Anaconda Navigator', ''
        )

    def logout(self):
        """
        Logout from anaconda cloud via the anaconda-client API.

        This method does not use workers.
        """
        logger.debug('')
        return self._client_api.logout()

    def is_logged_in(self):
        """Check if an user is logged in."""
        logger.debug('')
        return bool(self._client_api.user())

    def api_urls(self):
        """Get all the api urls for the current api url."""
        logger.debug('')
        api_url = self._client_api.get_api_url()

        def _config(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker
            proxy_servers = output.get('proxy_servers', {})
            verify = output.get('ssl_verify', True)
            worker = self._client_api.get_api_info(
                api_url,
                proxy_servers=proxy_servers,
                verify=verify,
            )
            worker.base_worker = base_worker
            worker.sig_finished.connect(_api_info)

        def _api_info(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            base_worker.sig_chain_finished.emit(base_worker, output, error)

        worker = self._conda_api.config_show()
        worker.sig_finished.connect(_config)
        return worker

    def load_repodata(self, prefix=None):
        """
        Load packages and apps from conda cache, based on `prefix`.

        Returns a Conda Worker with chained finish signal.
        """
        logger.debug('prefix: {}'.format(prefix))

        def _load_channels(base_worker, info, error):
            """Load processed channels for prefix using conda info."""
            logger.debug('info: {}, error: {}'.format(info, error))
            channels = info['channels']
            prefix = info['default_prefix']
            python_version = self._conda_api.package_version(
                pkg='python', prefix=prefix
            )
            repodata = self._conda_api.get_repodata(channels=channels)
            worker = self._client_api.load_repodata(
                repodata=repodata,
                metadata=self._metadata,
                python_version=python_version
            )
            worker.base_worker = base_worker
            worker.sig_finished.connect(_load_repo_data)

        def _load_repo_data(worker, output, error):
            """Loads the repository data from speficied channels."""
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            if error:
                output = ({}, {})

            if output:
                self.sig_repodata_loaded.emit(*output)
                base_worker.sig_chain_finished.emit(base_worker, output, error)

        worker = self._conda_api.info(prefix=prefix)
        worker.sig_finished.connect(_load_channels)

        return worker

    def get_username_token(self):
        """Get username and token."""
        logger.debug('')
        user = self._client_api.user()
        return user.get('username'), self._client_api.token

    # --- Conda
    # -------------------------------------------------------------------------
    @staticmethod
    def _process_unsafe_channels(channels, unsafe_channels):
        """
        Fix channels with tokens so that we can correctly process conda cache.

        From this:
            - 'https://conda.anaconda.org/t/<TOKEN>/goanpeca/<SUBDIR>'
        to this:
            - 'https://conda.anaconda.org/t/<ACTUAL-VALUE>/goanpeca/<SUBDIR>'
        """
        TOKEN_START_MARK = '/t/'
        TOKEN_VALUE_MARK = '<TOKEN>'
        token_channels = OrderedDict()
        for ch in unsafe_channels:
            if TOKEN_START_MARK in ch:
                start, token_plus_user_and_system = ch.split(TOKEN_START_MARK)
                start = start + TOKEN_START_MARK
                parts = token_plus_user_and_system.split('/')
                token = parts[0]
                end = '/'.join([''] + parts[1:])
                token_channels[start + TOKEN_VALUE_MARK + end] = token

        new_channels = []
        for ch in channels:
            if TOKEN_VALUE_MARK in ch:
                for uch, token in token_channels.items():
                    if ch.startswith(uch):
                        ch = ch.replace(TOKEN_VALUE_MARK, token)
            new_channels.append(ch)

        return new_channels

    def conda_data(self, prefix=None):
        """
        Return all the conda data needed to make the application work.

        If prefix is None, the root prefix is used.
        """
        logger.debug('prefix: {}'.format(prefix))

        # On startup this should be loaded once
        if not self._metadata:
            self.load_bundled_metadata()

        def _load_unsafe_channels(base_worker, info, error):
            """"""
            new_worker = self._conda_api.info(prefix=prefix)
            new_worker.sig_finished.connect(_conda_info_processed)
            new_worker.unsafe_channels = info['channels']
            new_worker.base_worker = base_worker

        def _conda_info_processed(worker, info, error):
            logger.debug('info: {}, error: {}'.format(info, error))
            base_worker = worker.base_worker
            processed_info = self._process_conda_info(info)
            # info = processed_info
            base_worker.info = info
            base_worker.processed_info = processed_info

            channels = self._process_unsafe_channels(
                info['channels'], worker.unsafe_channels
            )
            prefix = info['default_prefix']
            python_version = self._conda_api.package_version(
                pkg='python', prefix=prefix
            )
            pkgs_dirs = info['pkgs_dirs']
            repodata = self._conda_api.get_repodata(
                channels=channels, pkgs_dirs=pkgs_dirs
            )

            if repodata:
                new_worker = self._client_api.load_repodata(
                    repodata=repodata,
                    metadata=self._metadata,
                    python_version=python_version
                )
                new_worker.base_worker = base_worker
                new_worker.sig_finished.connect(_load_repo_data)
            else:
                # Force a refresh of the cache due to empty repodata
                new_worker = self._conda_api.search('conda', prefix=prefix)
                new_worker.base_worker = base_worker
                new_worker.channels = channels
                new_worker.pkgs_dirs = pkgs_dirs
                new_worker.python_version = python_version
                new_worker.sig_finished.connect(_get_repodata)

        def _get_repodata(worker, output, error):
            repodata = self._conda_api.get_repodata(
                channels=worker.channels, pkgs_dirs=worker.pkgs_dirs
            )
            new_worker = self._client_api.load_repodata(
                repodata=repodata,
                metadata=self._metadata,
                python_version=worker.python_version
            )
            new_worker.base_worker = worker.base_worker
            new_worker.sig_finished.connect(_load_repo_data)

        def _load_repo_data(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            packages, applications = output
            new_output = {
                'info': base_worker.info,
                'processed_info': base_worker.processed_info,
                'packages': packages,
                'applications': applications,
            }
            base_worker.sig_chain_finished.emit(base_worker, new_output, error)

        worker = self._conda_api.info(prefix=prefix, unsafe_channels=True)
        worker.sig_finished.connect(_load_unsafe_channels)
        return worker

    def conda_info(self, prefix=None):
        """
        Return the processed conda info for a given prefix.

        If prefix is None, the root prefix is used.
        """
        logger.debug('prefix: {}'.format(prefix))

        def _conda_info_processed(worker, info, error):
            logger.debug('info: {}, error: {}'.format(info, error))
            processed_info = self._process_conda_info(info)
            worker.sig_chain_finished.emit(worker, processed_info, error)

        worker = self._conda_api.info(prefix=prefix)
        worker.sig_finished.connect(_conda_info_processed)
        return worker

    def conda_config(self, prefix=None):
        """Show config for a given prefix."""
        logger.debug('prefix: {}'.format(prefix))

        def _config(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            config = output
            new_output = {'config': config}
            worker.sig_chain_finished.emit(worker, new_output, error)

        worker = self._conda_api.config_show(prefix=prefix)
        worker.sig_finished.connect(_config)
        return worker

    def conda_config_sources(self, prefix=None):
        """Show config sources for a given prefix."""
        logger.debug('prefix: {}'.format(prefix))

        def _config_sources(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            config_sources = output
            new_output = {'config_sources': config_sources}
            worker.sig_chain_finished.emit(worker, new_output, error)

        worker = self._conda_api.config_show_sources(prefix=prefix)
        worker.sig_finished.connect(_config_sources)
        return worker

    def conda_config_and_sources(self, prefix=None):
        """Show config and config sources for a given prefix."""
        logger.debug('prefix: {}'.format(prefix))

        def _config_sources(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker
            worker = self._conda_api.config_show(prefix=prefix)
            worker.config_sources = output
            worker.base_worker = base_worker
            worker.sig_finished.connect(_config)

        def _config(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            config_sources = worker.config_sources
            config = output
            new_output = {
                'config': config,
                'config_sources': config_sources,
            }
            base_worker.sig_chain_finished.emit(base_worker, new_output, error)

        worker = self._conda_api.config_show_sources(prefix=prefix)
        worker.sig_finished.connect(_config_sources)
        return worker

    def conda_info_and_config(self, prefix=None):
        """
        Return the processed conda info for a given prefix.

        If prefix is None, the root prefix is used.
        """
        logger.debug('prefix: {}'.format(prefix))

        def _conda_info_processed(worker, info, error):
            logger.debug('info: {}, error: {}'.format(info, error))

            processed_info = self._process_conda_info(info)
            base_worker = worker
            base_worker.processed_info = processed_info
            base_worker.info = info
            worker = self._conda_api.config_show_sources(prefix=prefix)
            worker.base_worker = base_worker
            worker.sig_finished.connect(_config_sources)

        def _config_sources(worker, config_sources, error):
            logger.debug(
                'config_sources: {}, error: {}'.format(config_sources, error)
            )
            base_worker = worker.base_worker
            worker = self._conda_api.config_show(prefix=prefix)
            base_worker.config_sources = config_sources
            worker.base_worker = base_worker
            worker.sig_finished.connect(_config)

        def _config(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            base_worker.config = output
            new_output = {
                'info': base_worker.info,
                'processed_info': base_worker.processed_info,
                'config': base_worker.config,
                'config_sources': base_worker.config_sources,
            }
            base_worker.sig_chain_finished.emit(base_worker, new_output, error)

        worker = self._conda_api.info(prefix=prefix)
        worker.sig_finished.connect(_conda_info_processed)
        return worker

    @staticmethod
    def _process_conda_info(info):
        """Process conda info output and add some extra keys."""
        logger.debug('info: {}'.format(info))
        processed_info = info.copy()

        # Add a key for writable environment directories
        envs_dirs_writable = []
        for env_dir in info['envs_dirs']:
            if path_is_writable(env_dir):
                envs_dirs_writable.append(env_dir)
        processed_info['__envs_dirs_writable'] = envs_dirs_writable

        # Add a key for writable environment directories
        pkgs_dirs_writable = []
        for pkg_dir in info.get('pkgs_dirs'):
            if path_is_writable(pkg_dir):
                pkgs_dirs_writable.append(pkg_dir)
        processed_info['__pkgs_dirs_writable'] = pkgs_dirs_writable

        # Add a key for all environments
        root_prefix = info.get('root_prefix')
        environments = OrderedDict()
        environments[root_prefix] = 'base (root)'  # Ensure order
        envs = info.get('envs')
        envs_names = [os.path.basename(env) for env in envs]
        for env_name, env_prefix in sorted(zip(envs_names, envs)):
            if WIN:
                # See: https://github.com/ContinuumIO/navigator/issues/1496
                env_prefix = env_prefix[0].upper() + env_prefix[1:]

            environments[env_prefix] = env_name

        # Since conda 4.4.x the root environment is also listed, so we
        # "patch" the name of the env after processing all other envs
        environments[root_prefix] = 'base (root)'
        processed_info['__environments'] = environments

        return processed_info

    def process_packages(self, packages, prefix=None, blacklist=()):
        """Process packages data and metadata to row format for table model."""
        logger.debug(
            'prefix: {}, packages: {}, blacklist={}'.
            format(prefix, packages, blacklist)
        )

        def _pip_data_ready(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker
            clean_packages = base_worker.packages  # Blacklisted removed!

            if error:
                logger.error(error)
            else:
                logger.debug('')

            pip_packages = output or []

            # Get linked data
            linked = self._conda_api.linked(prefix=prefix)
            worker = self._client_api.prepare_model_data(
                clean_packages, linked, pip_packages
            )
            worker.base_worker = base_worker
            worker.sig_finished.connect(_model_data_ready)

        def _model_data_ready(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            clean_packages = base_worker.packages
            data = output[:]

            # Remove blacklisted packages (Double check!)
            for package_name in blacklist:
                if package_name in clean_packages:
                    clean_packages.pop(package_name)

                for row, row_data in enumerate(data):
                    if package_name == data[row][C.COL_NAME]:
                        data.pop(row)

            # Worker, Output, Error
            base_worker.sig_chain_finished.emit(
                base_worker, (clean_packages, data), error
            )

        # Remove blacklisted packages, copy to avoid mutating packages dict!
        # See: https://github.com/ContinuumIO/navigator/issues/1244
        clean_packages = packages.copy()
        for package_name in blacklist:
            if package_name in clean_packages:
                clean_packages.pop(package_name)

        # Get pip data
        worker = self._conda_api.pip_list(prefix=prefix)
        worker.packages = clean_packages
        worker.sig_finished.connect(_pip_data_ready)

        return worker

    def process_apps(self, apps, prefix=None):
        """Process app information."""
        logger.debug('prefix: {}, apps: {}'.format(prefix, apps))
        applications = {}
        if prefix is None:
            prefix = self.ROOT_PREFIX

        # This checks installed apps in the prefix
        linked_apps = self.conda_linked_apps_info(prefix)
        missing_apps = [app for app in linked_apps if app not in apps]
        for app in missing_apps:
            apps[app] = linked_apps[app]

        # Temporal hardcoded images
        image_paths = {
            'glueviz': images.GLUEVIZ_ICON_1024_PATH,
            'spyder-app': images.SPYDER_ICON_1024_PATH,
            'spyder': images.SPYDER_ICON_1024_PATH,
            'ipython-qtconsole': images.QTCONSOLE_ICON_1024_PATH,
            'qtconsole': images.QTCONSOLE_ICON_1024_PATH,
            'ipython-notebook': images.NOTEBOOK_ICON_1024_PATH,
            'notebook': images.NOTEBOOK_ICON_1024_PATH,
            'orange-app': images.ORANGE_ICON_1024_PATH,
            'orange3': images.ORANGE_ICON_1024_PATH,
            'rodeo': images.RODEO_ICON_1024_PATH,
            'veusz': images.VEUSZ_ICON_1024_PATH,
            'rstudio': images.RSTUDIO_ICON_1024_PATH,
            'jupyterlab': images.JUPYTERLAB_ICON_1024_PATH,
            'pyvscode': images.VSCODE_ICON_1024_PATH,
            'qtcreator': images.QTCREATOR_ICON_1024_PATH,
            'qt3dstudio': images.QTCREATOR_ICON_1024_PATH,
        }

        APPS_DESCRIPTIONS = {
            'anaconda-fusion': (
                'Integration between Excel ® and Anaconda '
                'via Notebooks. Run data science functions, '
                'interact with results and create advanced '
                'visualizations in a code-free app inside '
                'Excel.'
            ),
            'anaconda-mosaic': (
                'Interactive exploration of larger than '
                'memory datasets. Create data sources, '
                'perform transformations and combinations.'
            ),
            'glueviz': (
                'Multidimensional data visualization across files. '
                'Explore relationships within and among related '
                'datasets.'
            ),
            'jupyterlab': (
                'An extensible environment for interactive '
                'and reproducible computing, based on the '
                'Jupyter Notebook and Architecture.'
            ),
            'notebook': (
                'Web-based, interactive computing notebook '
                'environment. Edit and run human-readable docs while '
                'describing the data analysis.'
            ),
            'orange-app': (
                'Component based data mining framework. Data '
                'visualization and data analysis for novice and '
                'expert. Interactive workflows with a large '
                'toolbox.'
            ),
            'qtconsole': (
                'PyQt GUI that supports inline figures, proper '
                'multiline editing with syntax highlighting, '
                'graphical calltips, and more.'
            ),
            'rodeo': (
                'A browser-based IDE for data science with python. '
                'Includes autocomplete, syntax highlighting, IPython '
                'support.'
            ),
            'rstudio': (
                'A set of integrated tools designed to help you be '
                'more productive with R. Includes R essentials and notebooks.'
            ),
            'spyder': (
                'Scientific PYthon Development EnviRonment. Powerful '
                'Python IDE with advanced editing, interactive '
                'testing, debugging and introspection features'
            ),
            'veusz': (
                'Veusz is a GUI scientific plotting and graphing '
                'package. It is designed to produce publication-ready '
                'Postscript or PDF output.'
            ),
            'vscode': (

            ),
            'qtcreator': (
                'Cross platform integrated development environment (IDE) to '
                'create C++ and QML applications.'
            ),
            'qt3dstudio': (
                'Rapidly build and prototype high quality 2D and 3D user '
                'interfaces using the built-in material and effects library '
                'or import your own design assets.'
            ),
            'console_shortcut': (
                'Run a cmd.exe terminal with your current environment from '
                'Navigator activated'
            ),
            'powershell_shortcut': (
                'Run a Powershell terminal with your current environment from '
                'Navigator activated'
            )
        }

        APPS_DESCRIPTIONS['orange3'] = APPS_DESCRIPTIONS['orange-app']
        APPS_DESCRIPTIONS['pyvscode'] = APPS_DESCRIPTIONS['vscode']

        APPS_DISPLAY_NAMES = {
            'glueviz': 'Glueviz',
            'jupyterlab': 'JupyterLab',
            'notebook': 'Notebook',
            'orange3': 'Orange 3',
            'console_shortcut': 'CMD.exe Prompt',
            'powershell_shortcut': 'Powershell Prompt',
            'qtconsole': 'Qt Console',
            'rstudio': 'RStudio',
            'spyder': 'Spyder',
            'vscode': 'VS Code',
        }

        invalid_apps = [
            'spyder-app',
            'ipython-qtconsole',
            'ipython-notebook',
            'anacondafusion',
        ]

        for app_name in apps:
            if app_name in invalid_apps:
                continue

            data = apps[app_name]
            display_name = APPS_DISPLAY_NAMES.get(app_name, app_name)
            versions = data.get('versions')
            description = APPS_DESCRIPTIONS.get(
                app_name, data.get('description', '')
            )

            version = versions[-1]  # Versions are sorted from small to big
            image_path = image_paths.get(
                app_name, images.ANACONDA_ICON_256_PATH
            )
            app_entry = data.get('app_entry').get(version)

            if app_entry:
                # Handle deprecated entrypoints for notebook and qtconsole
                if 'ipython notebook' in app_entry.lower():
                    app_entry = app_entry.replace(
                        'ipython notebook', 'jupyter-notebook'
                    )
                elif 'ipython qtconsole' in app_entry.lower():
                    app_entry = app_entry.replace(
                        'ipython qtconsole', 'jupyter-qtconsole'
                    )

            needs_license = app_name.lower() in PACKAGES_WITH_LICENSE

            conda_pkg_version = self.conda_package_version(
                    prefix=prefix, pkg=app_name, build=False
                )
            application = dict(
                name=app_name,
                display_name=display_name,
                description=description,
                version=conda_pkg_version or version,
                versions=versions,
                command=app_entry,
                image_path=image_path,
                needs_license=needs_license,
                non_conda=False,
                installed=bool(conda_pkg_version),
            )
            applications[app_name] = application

        # VSCode and PyCharm get registered here
        for app in external_apps.apps.values():
            app = app(config=self.config, process_api=self._process_api, conda_api=self._conda_api)
            if app.non_conda and app.executable:
                # This is stuff that enables tiles as an installation mechanism.  It was another condition under
                # which to show the tile (not installed, but available to install). We dropped it in 1.9.10.
                # (app.install_enabled and app.is_available)):
                applications[app.app_name] = dict(
                        name=app.app_name,
                        display_name=app.display_name,
                        description=app.description,
                        versions=app.versions,
                        command=app.executable,
                        image_path=app.image_path,
                        needs_license=app.needs_license,
                        non_conda=app.non_conda,
                        installed=app.installed,
                )
        return applications

    def trigger_finished_error(self, title, message, worker):
        def func():
            error = (title, message)
            o = {'error': error}
            worker.sig_finished.emit(worker, o, None)

        self._timer_error = QTimer()
        self._timer_error.setInterval(4000)
        self._timer_error.setSingleShot(True)
        self._timer_error.timeout.connect(lambda: func())
        self._timer_error.start()

    # --- Conda environments
    # -------------------------------------------------------------------------
    def load_bundled_metadata(self):
        """Load bundled metadata."""
        logger.debug('')
        comp_meta_filepath = content.BUNDLE_METADATA_COMP_PATH
        conf_meta_filepath = content.CONF_METADATA_PATH
        conf_meta_folder = METADATA_PATH

        if not os.path.isdir(conf_meta_folder):
            try:
                os.makedirs(conf_meta_folder)
            except Exception:
                pass

        binary_data = None
        if comp_meta_filepath and os.path.isfile(comp_meta_filepath):
            with open(comp_meta_filepath, 'rb') as f:
                binary_data = f.read()

        if binary_data:
            try:
                data = bz2.decompress(binary_data)
                with open(conf_meta_filepath, 'wb') as f:
                    f.write(data)

                if is_binary_string(data):
                    data = data.decode()

                self._metadata = json.loads(data)
            except Exception as e:
                logger.error(e)
                self._metadata = {}

    def update_index_and_metadata(self, prefix=None):
        """
        Update the metadata available for packages in repo.anaconda.com.

        Returns a download worker with chained finish signal.
        """
        logger.debug('')

        def _metadata_updated(worker, path, error):
            """Callback for update_metadata."""
            logger.debug('path: {}, error: {}'.format(path, error))
            base_worker = worker
            if path and os.path.isfile(path):
                with open(path, 'r') as f:
                    data = f.read()
            try:
                self._metadata = json.loads(data)
            except Exception:
                self._metadata = {}

            worker = self._conda_api.search('conda', prefix=prefix)
            worker.base_worker = base_worker
            worker.sig_finished.connect(_index_updated)

        def _index_updated(worker, output, error):
            logger.debug('output: {}, error: {}'.format(output, error))
            base_worker = worker.base_worker
            base_worker.sig_chain_finished.emit(base_worker, None, None)

        # TODO: there needs to be an uniform way to query the metadata for
        # both repo and anaconda.org
        if self._data_directory is None:
            raise Exception('Need to call `api.set_data_directory` first.')

        metadata_url = 'https://repo.anaconda.com/pkgs/metadata.json'
        filepath = content.CONF_METADATA_PATH
        worker = self.download(metadata_url, filepath)
        worker.action = C.ACTION_SEARCH
        worker.prefix = prefix
        worker.old_prefix = prefix
        worker.sig_finished.connect(_metadata_updated)
        return worker

    def create_environment(
        self,
        prefix,
        packages=('python', ),
        no_default_python=False,
    ):
        """Create environment and install `packages`."""
        logger.debug('prefix: {}, pkgs: {}'.format(prefix, packages))
        worker = self._conda_api.create(
            prefix=prefix,
            pkgs=packages,
            no_default_python=no_default_python,
            offline=self.is_offline(),
        )
        worker.action = C.ACTION_CREATE
        worker.action_msg = 'Creating environment <b>{0}</b>'.format(prefix)
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        return worker

    def clone_environment(self, clone_from_prefix, prefix):
        """Clone environment located at `clone` (prefix) into name."""
        logger.debug(
            'prefix: {}, clone_from_prefix: {}'.
            format(prefix, clone_from_prefix)
        )
        worker = self._conda_api.clone_environment(
            clone_from_prefix, prefix=prefix, offline=self.is_offline()
        )
        worker.action = C.ACTION_CLONE
        clone_from_name = self._conda_api.get_name_envprefix(clone_from_prefix)
        worker.action_msg = (
            'Cloning from environment <b>{0}</b> into '
            '<b>{1}</b>'
        ).format(clone_from_name, prefix)
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        worker.clone = clone_from_prefix
        return worker

    def import_environment(self, prefix, file):
        """Import new environment on `prefix` with specified `file`."""
        logger.debug('prefix: {}, file: {}'.format(prefix, file))
        worker = self._conda_api.create(
            prefix=prefix, file=file, offline=self.is_offline()
        )
        worker.action = C.ACTION_IMPORT
        worker.action_msg = 'Importing environment <b>{0}</b>'.format(prefix)
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        worker.file = file
        return worker

    def remove_environment(self, prefix):
        """Remove environment `name`."""
        logger.debug('prefix: {}'.format(prefix))
        worker = self._conda_api.remove_environment(
            prefix=prefix, offline=self.is_offline()
        )
        worker.action = C.ACTION_REMOVE_ENV
        worker.action_msg = 'Removing environment <b>{0}</b>'.format(prefix)
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)

        # Remove scripts folder
        scripts_path = LAUNCH_SCRIPTS_PATH
        if prefix != self.ROOT_PREFIX:
            scripts_path = os.path.join(scripts_path, worker.name)
        try:
            shutil.rmtree(scripts_path)
        except Exception:
            pass

        return worker

    def install_packages(
        self, prefix, pkgs, dry_run=False, no_default_python=False
    ):
        """Install `pkgs` in environment `prefix`."""
        logger.debug(
            'prefix: {}, pkgs: {}, dry-run: {}'.format(prefix, pkgs, dry_run)
        )
        worker = self._conda_api.install(
            prefix=prefix,
            pkgs=pkgs,
            dry_run=dry_run,
            no_default_python=no_default_python,
            offline=self.is_offline(),
        )
        worker.action_msg = 'Installing packages on <b>{0}</b>'.format(prefix)
        worker.action = C.ACTION_INSTALL
        worker.dry_run = dry_run
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        worker.pkgs = pkgs
        return worker

    def update_packages(
        self,
        prefix,
        pkgs=None,
        dry_run=False,
        no_default_python=False,
        all_=False,
    ):
        """Update `pkgs` in environment `prefix`."""
        logger.debug(
            'prefix: {}, pkgs: {}, dry-run: {}'.format(prefix, pkgs, dry_run)
        )
        worker = self._conda_api.update(
            prefix=prefix,
            pkgs=pkgs,
            dry_run=dry_run,
            no_default_python=no_default_python,
            all_=all_,
            offline=self.is_offline(),
        )
        worker.action_msg = 'Updating packages on <b>{0}</b>'.format(prefix)
        worker.action = C.ACTION_UPDATE
        worker.dry_run = dry_run
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        worker.pkgs = pkgs
        return worker

    def remove_packages(self, prefix, pkgs, dry_run=False):
        """Remove `pkgs` from environment `prefix`."""
        logger.debug('prefix: {}, pkgs: {}'.format(prefix, pkgs))
        worker = self._conda_api.remove(
            prefix=prefix,
            pkgs=pkgs,
            dry_run=dry_run,
            offline=self.is_offline(),
        )
        worker.action_msg = 'Removing packages from <b>{0}</b>'.format(prefix)
        worker.action = C.ACTION_REMOVE
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        worker.pkgs = pkgs
        return worker

    def remove_pip_packages(self, prefix, pkgs):
        """Remove pip `pkgs` from environment `prefix`."""
        logger.debug('prefix: {}, pkgs: {}'.format(prefix, pkgs))
        worker = self._conda_api.pip_remove(prefix=prefix, pkgs=pkgs)
        worker.action_msg = 'Removing packages from <b>{0}</b>'.format(prefix)
        worker.action = C.ACTION_REMOVE
        worker.prefix = prefix
        worker.name = self._conda_api.get_name_envprefix(prefix)
        worker.pkgs = pkgs
        return worker

    def check_navigator_dependencies(self, actions, prefix):
        """Check if navigator is affected by the operation on (base/root)."""
        logger.debug('actions: {}, prefix: {}'.format(actions, prefix))

        # Check that the dependencies are not changing the current prefix
        # This allows running this check on any environment that navigator
        # is installed on, instead of hardcoding self.ROOT_PREFIX
        if prefix != sys.prefix:
            conflicts = False
        else:
            # Minimum requirements to disable downgrading
            navigator_dependencies = {
                '_license': None,
                'anaconda-client': '1.6.14',
                'chardet': None,
                'pillow': None,
                'psutil': None,
                'pyqt': '5.6' if WIN and PY2 else '5.9',
                'pyyaml': None,
                'qtpy': '1.4.1',
            }
            conflicts = False
            if actions and isinstance(actions, list):
                actions = actions[0]

            if actions:
                linked = actions.get('LINK', [])
                unlinked = actions.get('UNLINK', [])

                split_cano = self.conda_split_canonical_name
                try:
                    # Old conda json format
                    linked = {split_cano(p)[0]: split_cano(p) for p in linked}
                except AttributeError:
                    # New conda json format
                    linked = {
                        split_cano(p['dist_name'])[0]:
                        split_cano(p['dist_name'])
                        for p in linked
                    }

                try:
                    # Old conda json format
                    unlinked = {
                        split_cano(p)[0]: split_cano(p)
                        for p in unlinked
                    }
                except AttributeError:
                    # New conda json format
                    unlinked = {
                        split_cano(p['dist_name'])[0]:
                        split_cano(p['dist_name'])
                        for p in unlinked
                    }

                from distutils.version import LooseVersion as lv

                downgraded_deps = {}
                removed_deps = []
                for pkg in unlinked:
                    if pkg in navigator_dependencies:
                        u_pkg_ver = lv(unlinked[pkg][1])
                        l_pkg = linked.get(pkg)
                        l_pkg_ver = lv(linked[pkg][1]) if l_pkg else None

                        # If downgrading or removing a dependency
                        if l_pkg and u_pkg_ver > l_pkg_ver:
                            downgraded_deps[pkg] = l_pkg_ver

                        if not l_pkg:
                            removed_deps.append(pkg)

                for down_dep, down_dep_version in downgraded_deps.items():
                    nav_dep_version = navigator_dependencies.get(down_dep)
                    if nav_dep_version:
                        nav_dep_version = lv(nav_dep_version)
                        if nav_dep_version > down_dep_version:
                            conflicts = True
                            break

                if removed_deps:
                    conflicts = True

        return conflicts

    # --- Anaconda Projects
    # -------------------------------------------------------------------------
    @staticmethod
    def get_projects(paths=None):
        """Return an ordered dictionary of all existing projects on paths."""
        logger.debug(paths)
        projects = OrderedDict()
        if paths and None not in paths:
            project_paths = []
            if paths and isinstance(paths, (list, tuple)):
                for path in paths:
                    project_paths.extend(
                        [
                            os.path.join(path, i) for i in os.listdir(path)
                            if os.path.isdir(os.path.join(path, i))
                        ]
                    )

                for project_path in project_paths:
                    files = []
                    # See https://github.com/ContinuumIO/navigator/issues/1207
                    try:
                        files = os.listdir(project_path)
                    except Exception:
                        pass

                    if 'anaconda-project.yml' in files:
                        projects[project_path] = os.path.basename(project_path)

        return projects

    # --- License management
    # -------------------------------------------------------------------------
    def add_license(self, paths):
        """Add license file callback."""
        logger.debug(paths)
        valid_licenses = {}
        invalid_licenses = {}
        paths = [p for p in paths if os.path.isfile(p)]
        for path in paths:
            lic = _license.read_licenses(path)
            if lic:
                valid_licenses[path] = lic
            else:
                invalid_licenses[path] = None

        # FIXME: Check  if license name exists in any of the paths
        # And then ask the user a question based on this
        if not os.path.isdir(self.license_location()):
            os.mkdir(self.license_location())

        for path in valid_licenses:
            head, tail = os.path.split(path)
            new_path = os.path.join(self.license_location(), tail)
            with open(new_path, 'w') as f:
                json.dump(valid_licenses[path], f)

        return valid_licenses, invalid_licenses

    @classmethod
    def remove_all_licenses(cls):
        """Remove all found licenses."""
        logger.debug('')
        paths = cls.license_paths()
        for path in paths:
            try:
                os.remove(path)
            except Exception:
                logger.warning(
                    'Could not remove license located at '
                    '{}'.format(path)
                )

    @staticmethod
    def remove_license(lic):
        """Remove license callback."""
        logger.debug(lic)
        path = lic.get(LICENSE_PATH)
        sig = lic.get('sig')

        with open(path) as f:
            licenses = json.load(f)

        for i, lic in enumerate(licenses):
            if lic.get('sig') == sig:
                break

        removed_license = licenses.pop(i)
        with open(path, 'w') as f:
            json.dump(licenses, f)

        head, tail = os.path.split(os.path.abspath(path))
        removed_folder = os.path.join(head, REMOVED_LICENSE_PATH)
        removed_path = os.path.join(removed_folder, tail)

        if not os.path.isdir(removed_folder):
            try:
                os.mkdir(removed_folder)
            except Exception:
                logger.warning(
                    'Could not create folder for removed licenses '
                    'at {}'.format(path)
                )

        removed_licenses = [removed_license]
        if os.path.isfile(removed_path):
            # Merge removed files
            try:
                with open(removed_path) as f:
                    existing_removed_licenses = json.load(f)
                    removed_licenses.extend(existing_removed_licenses)
            except Exception:
                logger.warning(
                    'Could not remove license located at '
                    '{}'.format(removed_path)
                )

        try:
            with open(removed_path, 'w') as f:
                json.dump(removed_licenses, f)
        except Exception:
            logger.warning(
                'Could not store removed license on '
                '{}'.format(removed_path)
            )

    @classmethod
    def load_licenses(cls, product=None):
        """Load license files."""
        logger.debug(product)
        res = []
        # This is used instead of _license.find_licenses to have the path
        # for each file
        for license_path in cls.license_paths():
            try:
                licenses = _license.read_licenses(license_path)
            except Exception:
                logger.warning(
                    "Can't read licenses from folder {0}".format(license_path)
                )
                licenses = []

            for lic in licenses:
                product_name = lic.get('product')
                product_filter = product == product_name if product else True
                if product_name in VALID_PRODUCT_LICENSES and product_filter:
                    valid = cls.is_valid_license(lic)
                    lic['__valid__'] = valid
                    lic['__status__'] = 'Valid' if valid else 'Invalid'
                    lic['__type__'] = lic.get('type', 'Enterprise').lower()
                    lic[LICENSE_PATH] = license_path
                    res.append(lic)
        return res

    @classmethod
    def get_package_license(cls, package_name):
        """
        Get stored license for a package.

        If several license found only the valid ones with the largest date
        is returned including expired and non expired licenses. Priority is
        given to nontrial over trial licenses, even if a trial has a larger
        date.
        """
        if not LICENSE_PACKAGE:
            return {}

        logger.debug(package_name)
        all_licenses = []
        for name in LICENSE_NAME_FOR_PACKAGE.get(package_name, []):
            licenses = cls.load_licenses(product=name)
            valid_licenses = [
                l for l in licenses
                if cls.is_valid_license(l, check_expired=False)
            ]
            all_licenses.extend(valid_licenses)

        # Order by trial and non trial. And select the one with the
        # longest remaining days giving priority to non trial.
        trial_valid_licenses = []
        nontrial_valid_licenses = []

        for lic in all_licenses:
            if cls.is_trial_license(lic):
                trial_valid_licenses.append(lic)
            else:
                nontrial_valid_licenses.append(lic)

        trial_valid_licenses = sorted(
            trial_valid_licenses,
            key=lambda i: i.get('end_date'),
        )
        nontrial_valid_licenses = sorted(
            nontrial_valid_licenses,
            key=lambda i: i.get('end_date'),
        )

        if nontrial_valid_licenses:
            lic = nontrial_valid_licenses[-1]  # Larger date
        elif trial_valid_licenses:
            lic = trial_valid_licenses[-1]  # Larger date
        else:
            lic = {}

        return lic

    @classmethod
    def license_paths(cls):
        """Return licenses paths founds on main location."""
        if not LICENSE_PACKAGE:
            return []

        logger.debug('')
        _license.get_license_paths()
        return _license.get_license_paths()

    @classmethod
    def license_location(cls):
        """Return license main location."""
        if not LICENSE_PACKAGE:
            return []

        logger.debug('')
        return _license.get_license_dirs()[0]

    @classmethod
    def is_valid_license(cls, lic, check_expired=True):
        """Return wether a license dictionary is valid."""
        if not LICENSE_PACKAGE:
            return False

        logger.debug('{} check_expired={}'.format(lic, check_expired))
        verified = cls.is_verified_license(lic)
        if check_expired:
            expired = cls.is_expired_license(lic)
        else:
            expired = False
        valid_vendor = cls.is_valid_vendor(lic)
        return verified and not expired and valid_vendor

    @classmethod
    def is_verified_license(cls, lic):
        """Check that the license is verified."""
        if not LICENSE_PACKAGE:
            return False

        logger.debug(lic)

        # Clean license from additional keys
        check_license = copy.deepcopy(lic)

        for key in lic:
            if key.startswith('__') and key.endswith('__'):
                check_license.pop(key)

        return bool(_license.verify_license(check_license))

    @classmethod
    def is_valid_vendor(cls, lic):
        """Check if a license is from a valid vendor."""
        if not LICENSE_PACKAGE:
            return False

        logger.debug(lic)
        vendor = lic["vendor"]
        return vendor in (
            "Anaconda, Inc.",
            "Continuum Analytics, Inc.",
            "Continuum Analytics",
            "Anaconda",
            "continuum",
            "anaconda",
        )

    @classmethod
    def is_expired_license(cls, lic):
        """Check if the license is expired."""
        if not LICENSE_PACKAGE:
            return True

        logger.debug(lic)
        return cls.get_days_left(lic) == 0

    @classmethod
    def is_trial_license(cls, lic):
        """Check if a license is of trial type."""
        if not LICENSE_PACKAGE:
            return True

        logger.debug(lic)
        return lic.get('type', '').lower() == 'trial'

    @classmethod
    def is_enterprise_license(cls, lic):
        """Check if a license is of enterprise type."""
        if not LICENSE_PACKAGE:
            return False

        logger.debug(lic)
        return not cls.is_trial_license(lic)

    @classmethod
    def get_days_left(cls, lic):
        """Get the number of days left for a license."""
        if not LICENSE_PACKAGE:
            return 0

        logger.debug(lic)
        days = 0
        try:
            end_date = _license.date_from_string(lic.get("end_date", ''))
            days = (end_date - datetime.date.today()).days
            if days < 0:
                days = 0
        except (ValueError, TypeError):
            days = 0

        # If license is an empty dict this should not return inf!
        if lic and "end_date" not in lic:
            days = float("inf")

        return days


# pass
ANACONDA_API = None


def AnacondaAPI():
    """Manager API threaded worker."""
    global ANACONDA_API

    if ANACONDA_API is None:
        ANACONDA_API = _AnacondaAPI()

    return ANACONDA_API


# --- Local testing
# -----------------------------------------------------------------------------
def finished(worker, output, error):  # pragma: no cover
    """Print information on test finished."""
    print(worker, output, error)
    print(time.time() - worker.start_time)
    print()
    print()


def download_finished(url, path):  # pragma: no cover
    """Print information on downlaod finished."""
    print(url, path)


def repodata_updated(repos):  # pragma: no cover
    """Print information on repodata updated."""
    print(repos)


def local_test():  # pragma: no cover
    """Main local test."""
    from anaconda_navigator.utils.qthelpers import qapplication

    app = qapplication()
    api = AnacondaAPI()
    #    worker = api.load_repodata()
    # api.sig_repodata_updated.connect(repodata_updated)
    data_directory = METADATA_PATH
    api.set_data_directory(data_directory)
    worker = api.update_index_and_metadata()
    worker.start_time = time.time()
    worker.sig_chain_finished.connect(finished)
    # worker = api.update_metadata()
    # worker.sig_chain_finished.connect(finished)
    # worker = api.load_repodata()
    # worker.sig_chain_finished.connect(finished)
    # worker = api.update_index()
    # worker.sig_finished.connect(finished)
    # worker = api.update_metadata()
    # worker.sig_download_finished.connect(download_finished)
    # api.update_repodata()
    #    lic = api.get_package_license('anaconda-fusion')
    #    print(lic)
    app.exec_()


if __name__ == '__main__':  # pragma: no cover
    local_test()
