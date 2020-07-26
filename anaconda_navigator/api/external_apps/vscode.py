import datetime
import errno
import json
import io
import os
import re
import shutil
import sys


from .base import BaseApp

from anaconda_navigator.api.process import DummyWorker
from anaconda_navigator.config import (CONF_PATH, LINUX, LINUX_DEB, HOME_PATH,
                                       LINUX_DNF, LINUX_RPM, MAC, WIN, OS_64_BIT)
from anaconda_navigator.static import scripts, images
from anaconda_navigator.utils.py3compat import PY3, to_binary_string
from anaconda_navigator.utils.logs import logger


class VSCodeApp(BaseApp):
    def __init__(self, **kwargs):
        # minimum supported linux distro versions
        distro_map = {
            'rhel': '7',
            'sles': '12',
            'centos': '7',
            'debian': '8',
            'fedora': '23',
            'suse': '42.1',
            'ubuntu': '14.04'
        }

        super(VSCodeApp, self).__init__(
            app_name='vscode',
            filename='code',
            windows_ext='.cmd',
            windows_folder_name='Microsoft VS Code',
            mac_name='Visual Studio Code.app',
            display_name='VS Code',
            description=('Streamlined code editor with support for '
                         'development operations like debugging, task '
                         'running and version control.'),
            image_path=images.VSCODE_ICON_1024_PATH,
            needs_license=False,
            non_conda=True,
            distro_map=distro_map,
            **kwargs
        )

        self.rpm_asc_file_url = 'https://packages.microsoft.com/keys/microsoft.asc'
        self.app_data = self._application_data()
        if MAC:
            self._EXE = os.path.join(
                    self._INST_DIR,
                    self.mac_name,
                    'Contents/Resources/app/bin/code'
                )
        elif LINUX:
            self._EXE = os.path.join(self._INST_DIR, 'bin', 'code')
        else:
            self._EXE = os.path.join(
                self._INST_DIR, 'bin', 'code.cmd'
            )


    @property
    def versions(self):
        return [self.app_data.get('productVersion')]

    def _version(self):
        """Query the vscode version for the default installation path."""
        # TODO: generalize for external app, not just vscode
        version = None
        if self._vscode_version_value is None:
            if self.executable:
                cmd = [self.executable, '--version']

                import subprocess
                stdout = ''
                stderr = ''
                try:
                    p = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        executable=self.executable,
                    )
                    stdout, stderr = p.communicate()
                    if PY3:
                        stdout = stdout.decode()
                        stderr = stderr.decode()
                except OSError:
                    pass

                if stdout:
                    output = [o for o in stdout.split('\n') if o and '.' in o]
                    version = output[0]

                self._vscode_version_value = version
        else:
            version = self._vscode_version_value

        return version

    @property
    def version(self):
        """Return the current installed version or the highest version."""
        return self._vscode_version() or self.versions[-1]

    def install_extensions(self):
        """Install app extensions."""
        wm = self._process_api
        logger.debug('Installing vscode extensions')
        cmd = [
            '"{}"'.format(self._EXE),  # must wrap in quotes so that spaces don't mess things up
            '--install-extension',
            'ms-python.anaconda-extension-pack',
            # ms-python-anaconda-extension
            # ms-python.python
        ]
        logger.debug(' '.join(cmd))
        worker = wm.create_process_worker(cmd)
        return worker

    def send_telemetry(self):
        """Send app telemetry."""
        wm = self._process_api
        logger.debug('Sending vscode telemetry')
        cmd = [
            '"{}"'.format(self._EXE),  # must wrap in quotes so that spaces don't mess things up
            '--install-source',
            'Anaconda-Navigator',
        ]
        logger.debug(' '.join(cmd))
        worker = wm.create_process_worker(cmd)
        return worker

    def _application_data(self):
        """Get app data from microsoft rest api."""
        data = {}
        url = (
            'https://update.code.visualstudio.com/api/update'
            '/{}/stable/version'.format(self._SUBDIR)
        )
        if url:
            data = self._download_api.get_url(
                url=url,
                as_json=True,
                non_blocking=False,
            )
        return data

    def _find_linux_install_dir(self):
        INST_DIR = None
        exe = os.path.join('/snap', 'bin', 'code')
        if os.path.lexists(exe):
            INST_DIR = '/snap'

        for distro in self.distro_map.keys():
            _distro_regex = ".*{}/([^ ]*)".format(distro)
            m = re.match(_distro_regex, self._conda_api.user_agent)
            if m:
                DISTRO_NAME = distro
                DISTRO_VER = m.group(1)
                break

        if DISTRO_NAME in ['ubuntu', 'debian']:
            _pkg_type = 'deb'
        else:
            _pkg_type = 'rpm'

        _os_arch = 'x64' if OS_64_BIT else 'ia32'
        SUBDIR = 'linux-{}-{}'.format(_pkg_type, _os_arch)
        INST_EXT = _pkg_type
        if not INST_DIR:
            INST_DIR = '/usr/share/{}'.format(self.filename)

        return SUBDIR, INST_EXT, INST_DIR

    def install(self, password=None):
        dummy_worker = DummyWorker()

        # On windows there is a User setup file also
        url = self.app_data.get('url')

        is_opensuse = 'opensuse' in self._DISTRO_NAME
        is_deb = self._DISTRO_NAME in ['ubuntu', 'debian']
        is_rpm = self._DISTRO_NAME in ['centos', 'rhel', 'fedora']
        wm = self._process_api

        if not url:
            self.trigger_finished_error(
                'Connectivity Error',
                'Please check your internet connection is working.',
                dummy_worker,
            )
            return dummy_worker

        if LINUX:
            if password is None:  # This should not happen, but just in case!
                self.trigger_finished_error(
                    'Password Error',
                    'Please try again and provide the correct credentials.',
                    dummy_worker,
                )
                return dummy_worker
            elif password == '':  # The install process was cancelled
                return dummy_worker

        def _download_finished(worker, output, error):
            """Download callback."""
            logger.debug('Finished App download')

            if error:
                dummy_worker.sig_finished.emit(dummy_worker, output, error)
                return

            if MAC:
                try:
                    os.makedirs(self._INST_DIR)
                except OSError as e:
                    if e.errno != errno.EEXIST:
                        logger.error(e)

                logger.debug('Decompressing app application')

                # Unzip using Mac defalut command/application
                command = [
                    '/usr/bin/unzip',
                    '-qo',
                    self._INSTFILE,
                    '-d',
                    self._INST_DIR,
                ]

                worker = wm.create_process_worker(command)
                worker.sig_partial.connect(dummy_worker.sig_partial)
                worker.sig_partial.emit(
                    dummy_worker,
                    {'message': 'Uncompressing file...'},
                    None,
                )
                worker.sig_finished.connect(_install_extensions)
                worker.start()
            elif WIN:
                # Run windows installer silently
                # When quotes are used  with START the first param is the title
                # that is why we add an empty string and then the actual
                # executable after the /WAIT. The quotes are for users with
                # spaces
                command = [
                    'START',
                    '/WAIT',
                    '""',
                    '"{}"'.format(self._INSTFILE),
                    '/VERYSILENT',
                    '/MERGETASKS=!runcode',
                    '/SUPPRESSMSGBOXES',
                    '/NORESTART',
                    '/LOG="{}"'.format(self.log_path(delete=True)),
                    '/DIR="{0}\\"'.format(self._INST_DIR),
                ]

                # Create temp batch file and run that
                cmd = u' '.join(command)  # The u'... is important on py27!
                logger.debug(cmd)
                bat_path = os.path.join(
                    CONF_PATH,
                    'temp',
                    'app-install.bat',
                )

                base_temp_path = os.path.dirname(bat_path)
                if not os.path.isdir(base_temp_path):
                    os.makedirs(base_temp_path)

                with io.open(bat_path, 'w') as f:
                    f.write(cmd)

                worker = wm.create_process_worker([bat_path])
                worker.sig_partial.connect(dummy_worker.sig_partial)
                worker.sig_finished.connect(_install_extensions)
                worker.start()

            elif LINUX:
                # See: https://code.visualstudio.com/docs/setup/linux
                if LINUX_DEB and is_deb:
                    cmd = ['sudo', '-kS', 'dpkg', '-i', self._INSTFILE]
                    worker = wm.create_process_worker(cmd)
                    worker.sig_partial.connect(dummy_worker.sig_partial)
                    worker.sig_finished.connect(_install_deb_dependencies)
                    worker.start()
                    stdin = to_binary_string(password + '\n')
                    worker.write(stdin)
                elif LINUX_RPM and is_rpm:
                    # Add key
                    cmd = [
                        'sudo', '-kS', 'rpm', '--import',
                        self.rpm_asc_file_url
                    ]
                    worker = wm.create_process_worker(cmd)
                    worker.sig_partial.connect(dummy_worker.sig_partial)
                    worker.sig_finished.connect(_install_rpm_repodata)
                    worker.start()
                    stdin = to_binary_string(password + '\n')
                    worker.write(stdin)
                else:
                    dummy_worker.sig_finished.emit(dummy_worker, None, None)

        def _install_deb_dependencies(worker, output, error):
            cmd = ['sudo', '-kS', 'apt-get', 'install', '-f']
            worker = wm.create_process_worker(cmd)
            worker.sig_partial.connect(dummy_worker.sig_partial)
            worker.sig_finished.connect(_install_extensions)
            worker.sig_partial.emit(
                dummy_worker,
                {'message': 'Installing dependencies...'},
                None,
            )
            worker.start()
            stdin = to_binary_string(password + '\n')
            worker.write(stdin)

        def _install_rpm_repodata(worker, output, error):
            logger.debug('install rpm repodata')
            distro = 'opensuse' if is_opensuse else 'fedora'
            cmd = [
                'sudo',
                '-kS',
                sys.executable,
                scripts.INSTALL_SCRIPT,
                distro,
            ]
            logger.debug(' '.join(cmd))
            worker = wm.create_process_worker(cmd)
            worker.sig_partial.connect(dummy_worker.sig_partial)
            worker.sig_finished.connect(_update_rpm_manager)
            worker.sig_partial.emit(
                dummy_worker,
                {'message': 'Installing repodata...'},
                None,
            )
            worker.start()
            stdin = to_binary_string(password + '\n')
            worker.write(stdin)

        def _update_rpm_manager(worker, output, error):
            logger.debug('update rpm manager')
            if is_opensuse:
                cmd = ['sudo', '-kS', 'zypper', 'refresh']
            elif LINUX_DNF:
                cmd = ['dnf', 'check-update']
            else:
                cmd = ['yum', 'check-update']
            logger.debug(' '.join(cmd))
            worker = wm.create_process_worker(cmd)
            worker.sig_partial.connect(dummy_worker.sig_partial)
            worker.sig_finished.connect(_install_rpm_package)
            worker.sig_partial.emit(
                dummy_worker,
                {'message': 'Updating manager...'},
                None,
            )
            worker.start()

            if is_opensuse:
                stdin = to_binary_string(password + '\n')
                worker.write(stdin)

        def _install_rpm_package(worker, output, error):
            logger.debug('install rpm package')
            if is_opensuse:
                cmd = [
                    'sudo', '-kS', 'zypper', '--non-interactive', 'install',
                    'code'
                ]
            elif LINUX_DNF:
                cmd = ['sudo', '-kS', 'dnf', '--assumeyes', 'install', 'code']
            else:
                cmd = ['sudo', '-kS', 'yum', '--assumeyes', 'install', 'code']

            logger.debug(' '.join(cmd))
            worker = wm.create_process_worker(cmd)
            worker.sig_partial.connect(dummy_worker.sig_partial)
            worker.sig_finished.connect(_install_extensions)
            worker.sig_partial.emit(
                dummy_worker,
                {'message': 'Installing rpm package...'},
                None,
            )
            worker.start()
            stdin = to_binary_string(password + '\n')
            worker.write(stdin)

        def _install_extensions(worker, output, error):
            """Install app extensions as part of install process."""
            logger.debug('install extensions')
            error = error.lower()
            check_in = 'error' in error
            check_not_in = 'password' not in error or 'sudo' not in error
            if error and check_in and check_not_in:
                dummy_worker.sig_finished.emit(dummy_worker, output, error)
                return

            worker = self.install_extensions()
            worker.sig_partial.emit(
                dummy_worker,
                {'message': 'Installing python extensions...'},
                None,
            )
            worker.sig_finished.connect(_send_telemetry)
            worker.start()

        def _send_telemetry(worker, output, error):
            """Send app telemetry as part of install process."""
            logger.debug('send telemetry')
            check_in = 'error' in error
            check_not_in = 'password' not in error or 'sudo' not in error
            if error and check_in and check_not_in:
                dummy_worker.sig_finished.emit(dummy_worker, output, error)
                return

            worker = self.send_telemetry()
            worker.sig_partial.emit(
                dummy_worker,
                {'message': 'Updating app data...'},
                None,
            )
            worker.sig_finished.connect(_installation_finished)
            worker.start()

        def _installation_finished(worker, output, error):
            # Check the log!
            logger.debug('Finished app installation')
            dummy_worker.sig_finished.emit(dummy_worker, output, error)

        # Download file
        worker = self._download_api.download(url, path=self._INSTFILE)
        worker.sig_partial.connect(dummy_worker.sig_partial)
        worker.sig_finished.connect(_download_finished)

        return dummy_worker

    def win_uninstaller(self):
        dats = []
        unins = []
        names = set()
        INST_FOLDER = self._INST_DIR
        for item in os.listdir(INST_FOLDER):
            path = os.path.join(INST_FOLDER, item).lower()
            item = item.lower()
            if os.path.isfile(path):
                parts = item.split('.')
                if parts:
                    basename = parts[0]
                else:
                    basename = item

                if item.startswith('unins') and item.endswith('.dat'):
                    dats.append(item)
                    names.add(basename)
                elif item.startswith('unins') and item.endswith('.exe'):
                    unins.append(item)
                    names.add(basename)
        for name in sorted(names):
            if name + '.dat' in dats and name + '.exe' in unins:
                # print(name + '.exe')
                break
        return name + '.exe' or 'unins000.exe'

    def remove(self, password=None):
        logger.debug('Removing app')
        wm = self._process_api
        dummy_worker = DummyWorker()
        locations = []
        uninstall_cmd = []
        is_opensuse = 'opensuse' in self._DISTRO_NAME
        is_deb = self._DISTRO_NAME in ['ubuntu', 'debian']
        is_rpm = self._DISTRO_NAME in ['centos', 'rhel', 'fedora']

        if MAC:
            locations = [self._INST_DIR]
        elif WIN:
            locations = [self._INST_DIR]
            uninstaller_path = os.path.join(
                self._INST_DIR,
                self.win_uninstaller(),
            )

            if ' ' in uninstaller_path:
                uninstaller_path = '"' + uninstaller_path + '"'
            command = [uninstaller_path]

            # Create temp batch file and run that
            cmd = ' '.join(command)
            bat_path = os.path.join(CONF_PATH, 'temp', 'app-uninstall.bat')
            base_temp_path = os.path.dirname(bat_path)

            if not os.path.isdir(base_temp_path):
                os.makedirs(base_temp_path)

            mode = 'w' if PY3 else 'wb'
            with io.open(bat_path, mode) as f:
                f.write(cmd)

            uninstall_cmd = [bat_path]

        elif LINUX:
            if LINUX_DEB and is_deb:
                uninstall_cmd = [
                    'sudo',
                    '-kS',
                    'apt-get',
                    '--yes',
                    'remove',
                    'code',
                ]
            elif LINUX_RPM and is_rpm:
                if is_opensuse:
                    uninstall_cmd = [
                        'sudo',
                        '-kS',
                        'zypper',
                        '--non-interactive',
                        'remove',
                        'code',
                    ]
                elif LINUX_DNF:
                    uninstall_cmd = [
                        'sudo',
                        '-kS',
                        'dnf',
                        '--assumeyes',
                        'remove',
                        'code',
                    ]
                else:
                    uninstall_cmd = [
                        'sudo',
                        '-kS',
                        'yum',
                        '--assumeyes',
                        'remove',
                        'code',
                    ]

        def _remove_locations(locations, dummy_worker):
            """Remove location."""
            for location in locations:
                if os.path.isdir(location):
                    logger.debug('Removing location: {}'.format(location))
                    try:
                        shutil.rmtree(location)
                    except Exception as e:
                        logger.debug(e)

            # Wait and check the folder has been indeed removed
            dummy_worker.sig_finished.emit(dummy_worker, {}, None)
            return locations

        def _uninstall_finished(worker, output, error):
            """Remove location callback."""
            new_worker = wm.create_python_worker(
                _remove_locations,
                locations,
                dummy_worker,
            )
            new_worker.sig_partial.connect(dummy_worker.sig_partial)
            new_worker.sig_finished.connect(_finished)
            new_worker.start()

        def _finished(worker, output, error):
            # Check uninstall log!
            log_data = self.log_data()
            if error or not log_data['successful']:
                out = {'error': error}
            else:
                out = output
            dummy_worker.sig_finished.emit(dummy_worker, out, None)

        if uninstall_cmd:
            logger.debug(' '.join(uninstall_cmd))
            worker = wm.create_process_worker(uninstall_cmd)
            worker.sig_partial.connect(dummy_worker.sig_partial)
            worker.sig_finished.connect(_uninstall_finished)
            worker.start()

            if LINUX:
                if password:
                    stdin = to_binary_string(password + '\n')
                    worker.write(stdin)
                else:
                    _uninstall_finished(dummy_worker, None, None)
        else:
            _uninstall_finished(dummy_worker, None, None)

        return dummy_worker

    def update_config(self, prefix):
        logger.debug('Update app config to use prefix {}'.format(prefix))
        try:
            _config = os.path.join(
                CONF_PATH,
                'Code',
                'User',
                'settings.json',
            )
            _config_dir = os.path.dirname(_config)

            try:
                if not os.path.isdir(_config_dir):
                    os.makedirs(_config_dir)
            except Exception as e:
                logger.error(e)

            config_update = {'python.pythonPath': prefix}

            if os.path.isfile(_config):
                try:
                    with io.open(_config, 'r', encoding='utf-8') as f:
                        data = f.read()

                    self.create_config_backup(data)

                    config_data = json.loads(data)
                    for key, val in config_update.items():
                        config_data[key] = val
                except Exception:
                    # If there is any error, don't overwrite app config
                    return False
            else:
                config_data = config_update.copy()

            mode = 'w' if PY3 else 'wb'
            with io.open(_config, mode) as f:
                json.dump(
                    config_data,
                    f,
                    sort_keys=True,
                    indent=4,
                )
        except Exception as e:
            logger.error(e)
            return False

        return True

    def create_config_backup(self, data):
        """
        Create a backup copy of the app configuration file `data`.

        Leave only the last 10 backups.
        """
        now = datetime.datetime.now()
        date = now.strftime('%Y%m%d%H%M%S')
        _config_dir = os.path.join(
            CONF_PATH,
            'Code',
            'User',
        )
        _config_bck = os.path.join(
            _config_dir,
            'bck.{date}.navigator.settings.json'.format(date=date),
        )

        # Make the backup
        logger.debug(
            'Creating backup app config file: {}'
            ''.format(_config_bck)
        )
        with io.open(_config_bck, 'w', encoding='utf-8') as f_handle:
            f_handle.write(data)

        # Only keep the latests 10 backups
        files = os.listdir(_config_dir)
        fpaths = [
            os.path.join(_config_dir, f) for f in files
            if f.startswith('bck.') and f.endswith('.navigator.settings.json')
        ]

        fpaths_remove = list(sorted(fpaths, reverse=True))[10:]
        for fpath in fpaths_remove:
            try:
                os.remove(fpath)
            except Exception:
                pass
