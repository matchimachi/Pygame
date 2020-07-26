import os

import xmltodict

from anaconda_navigator.static import images
from anaconda_navigator.utils.logs import logger
from anaconda_navigator.config import MAC, WIN
from .base import BaseApp


class PyCharmApp(BaseApp):
    def __init__(self, **kwargs):
        # minimum supported linux distro versions
        distro_map = {
            'rhel': '6',
            'sles': '11',
            'centos': '6',
            'debian': '7',
            'fedora': '20',
            'suse': '42.1',
            'ubuntu': '14.04'
        }

        super(PyCharmApp, self).__init__(
            app_name='pycharm',
            filename='pycharm',
            windows_ext='.exe',
            windows_folder_name='JetBrains',
            mac_name='PyCharm.app',
            display_name='PyCharm',
            description=('Full-featured Python IDE by JetBrains.  Supports '
                         'code completion, linting, debugging, and '
                         'domain-specific enhancements for web development '
                         'and data science.'),
            image_path=images.PYCHARM_ICON_1024_PATH,
            needs_license=False,
            non_conda=True,
            distro_map=distro_map,
            **kwargs
        )

        self._appdata = None
        self.app_data = self._application_data()

    def _find_linux_install_dir(self):
        if os.path.isdir('/snap/bin') and any(_.startswith('pycharm') for _ in os.listdir('/snap/bin')):
            install_dir = '/snap'
        else:
            install_dir = '/opt'
        return None, None, install_dir

    @property
    def executable(self):
        launch_str = None
        if MAC:
            # pycharm will be available as a .app bundle
            dirs = [name for name in os.listdir(self._INST_DIR)
                    if os.path.isdir(os.path.join(self._INST_DIR, name)) if name.startswith("PyCharm")]
            found_pycharm_app = dirs[0] if dirs else None
            launch_str = 'open -a "{}"'.format(found_pycharm_app.rstrip('.app')) if found_pycharm_app else None
        elif WIN:
            if os.path.isdir(self._INST_DIR):
                for root, dirs, files in os.walk(self._INST_DIR):
                    for file in files:
                        if file.lower().startswith('pycharm') and file.lower().endswith(".exe"):
                            return '"{}"'.format(os.path.join(root, file))
        else:
            # snaps on Ubuntu have this naming.  They are ideally on PATH.
            for edition in ('professional', 'community', 'educational'):
                exe = os.path.join(self._INST_DIR, 'bin', 'pycharm-{}'.format(edition))
                if os.path.lexists(exe):
                    launch_str = exe
            # this is the other method listed on JetBrains' site
            # https://www.jetbrains.com/help/pycharm/installation-guide.html#snap-install-tar
            if not launch_str and os.path.isdir(self._INST_DIR):
                pycharm_dirs = [_ for _ in os.listdir(self._INST_DIR) if os.path.isdir(_) and _.startswith('pycharm')]
                for pc_dir in pycharm_dirs:
                    for root, dirs, files in os.walk(pc_dir):
                        for file in files:
                            if file.lower() == 'pycharm.sh':
                                return 'sh "{}"'.format(os.path.join(root, file))
        return launch_str

    def _application_data(self):
        if self._appdata:
            return self._appdata
        url = "https://www.jetbrains.com/updates/updates.xml"
        data = self._download_api.get_url(
            url=url,
            as_json=False,
            non_blocking=False,
        )
        rel = {}
        if data:
            data = xmltodict.parse(data)
            p = [_ for _ in data['products']['product'] if _['@name'] == 'PyCharm'][0]
            rel = [_ for _ in p['channel'] if _['@status'] == 'release'][0]
        self._appdata = rel
        return rel

    @property
    def versions(self):
        versions = set()
        for build in self._application_data().get('build', []):
            versions.add(build['@version'])
            # for k in list(build.keys()):
            #     if k.startswith("@"):
            #         build[k[1:]] = build[k]
            #         del build[k]
        return sorted(list(versions))

    def _pycharm_version(self):
        version = None
        # Version info is in a file called build.txt.  On mac, it is at
        # Contents/Resources/build.txt
        # from vlan: 193 means 2019.3 (EAP or release or 2019.3.x updates), 201 means 2020.1, etc.
        return ""

    @property
    def version(self):
        """Return the current installed version or the highest version."""
        return self._pycharm_version() or self.versions[-1] if self.versions else None

    def create_config_backup(self, data):
        """
        Create a backup copy of the app configuration file `data`.

        Leave only the last 10 backups.
        """
        # no effect for pycharm
        pass

    def update_config(self, prefix):
        """Update app python interpreter user config."""
        # no effect for pycharm
        pass

    def install_extensions(self):
        """Install app extensions."""
        # no effect for pycharm
        wm = self._process_api
        worker = wm.create_process_worker(['python', '-V'])
        return worker

    def install(self, password=None):
        """Install app."""
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
