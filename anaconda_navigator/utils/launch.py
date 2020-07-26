# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright (c) 2016-2017 Anaconda, Inc.
#
# May be copied and distributed freely only as part of an Anaconda or
# Miniconda installation.
# -----------------------------------------------------------------------------
"""Launch applications utilities."""

# yapf: disable

# Standard library imports
import codecs
import glob
import json
import os
import shutil
import subprocess
import sys
import uuid

# Local imports
from anaconda_navigator.api.anaconda_api import AnacondaAPI
from anaconda_navigator.config import CONF_PATH, LAUNCH_SCRIPTS_PATH, LINUX, MAC, WIN
from anaconda_navigator.utils.logs import logger
from anaconda_navigator.utils.win_elevate import run_as_admin
from anaconda_navigator.utils.toolpath import get_pyexec


# yapf: enable

if WIN:
    import ctypes


def get_scripts_path(
    root_prefix, prefix, default_scripts_path=LAUNCH_SCRIPTS_PATH
):
    """Return the launch scripts path."""
    # Normalize slashes
    scripts_path = default_scripts_path
    root_prefix = root_prefix.replace('\\', '/')
    prefix = prefix.replace('\\', '/')
    default_scripts_path = default_scripts_path.replace('\\', '/')
    if root_prefix != prefix:
        scripts_path = os.path.join(
            default_scripts_path, prefix.split('/')[-1]
        )
    return scripts_path


def get_quotes(prefix):
    """Return quotes if needed for spaces on prefix."""
    return '"' if ' ' in prefix and '"' not in prefix else ''


def remove_package_logs(
    root_prefix, prefix, default_scripts_path=LAUNCH_SCRIPTS_PATH
):
    """Try to remove output, error logs for launched applications."""
    scripts_p = get_scripts_path(
        root_prefix, prefix, default_scripts_path=default_scripts_path
    )
    if not os.path.isdir(scripts_p):
        return

    scripts_p = scripts_p if scripts_p[-1] == os.sep else scripts_p + os.sep
    files = glob.glob(scripts_p + '*.txt')
    for file_ in files:
        log_path = os.path.join(scripts_p, file_)
        try:
            os.remove(log_path)
        except Exception:
            pass


def get_package_logs(
    package_name,
    prefix=None,
    root_prefix=None,
    id_=None,
    default_scripts_path=LAUNCH_SCRIPTS_PATH,
):
    """Return the package log names for launched applications."""
    scripts_path = get_scripts_path(
        root_prefix, prefix, default_scripts_path=default_scripts_path
    )
    if os.path.isdir(scripts_path):
        files = os.listdir(scripts_path)
    else:
        files = []

    if id_ is None:
        for i in range(1, 10000):
            stdout_log = "{package_name}-out-{i}.txt".format(
                package_name=package_name, i=i
            )
            stderr_log = "{package_name}-err-{i}.txt".format(
                package_name=package_name, i=i
            )
            if stdout_log not in files and stderr_log not in files:
                id_ = i
                break
    else:
        stdout_log = "{package_name}-out-{i}.txt".format(
            package_name=package_name, i=id_
        )
        stderr_log = "{package_name}-err-{i}.txt".format(
            package_name=package_name, i=id_
        )

    if prefix and root_prefix:
        stdout_log_path = os.path.join(scripts_path, stdout_log)
        stderr_log_path = os.path.join(scripts_path, stderr_log)
    else:
        stdout_log_path = stdout_log
        stderr_log_path = stderr_log

    return stdout_log_path, stderr_log_path, id_


def is_program_installed(basename):
    """
    Return program absolute path if installed in PATH.

    Otherwise, return None
    """
    for path in os.environ["PATH"].split(os.pathsep):
        abspath = os.path.join(path, basename)
        if os.path.isfile(abspath):
            return abspath


def create_app_run_script(
    command,
    package_name,
    prefix,
    root_prefix,
    suffix,
    default_scripts_path=LAUNCH_SCRIPTS_PATH,
):
    """Create the script to run the application and activate th eenvironemt."""
    # qtpy is adding this to env on startup and this is messing qtconsole
    # and other apps on other envs with different versions of QT
    if 'QT_API' in os.environ:
        os.environ.pop('QT_API')

    package_name = package_name or 'app'

    scripts_path = get_scripts_path(
        root_prefix, prefix, default_scripts_path=default_scripts_path
    )

    if not os.path.isdir(scripts_path):
        os.makedirs(scripts_path)
    fpath = os.path.join(scripts_path, '{0}.{1}'.format(package_name, suffix))

    # Try to clean log files
    remove_package_logs(root_prefix=root_prefix, prefix=prefix)

    # Create the launch script
    if WIN:
        codepage = str(ctypes.cdll.kernel32.GetACP())
        cp = 'cp' + codepage
        with codecs.open(fpath, "w", cp) as f:
            f.write(command)
    else:
        # Unicode is disabled on unix systems until properly fixed!
        # Using normal open and not codecs.open
        # cp = 'utf-8'
        with open(fpath, "w") as f:
            f.write(command)

    os.chmod(fpath, 0o777)

    return fpath


def get_command_on_win(
    prefix,
    command,
    package_name,
    root_prefix,
    environment=None,
    default_scripts_path=LAUNCH_SCRIPTS_PATH,
    non_conda=False,
    cwd=None
):
    """Generate command to run on win system and enforce env activation."""
    stdout_log_path, stderr_log_path, id_ = get_package_logs(
        package_name,
        root_prefix=root_prefix,
        prefix=prefix,
        default_scripts_path=default_scripts_path,
    )
    quote = get_quotes(prefix)
    quote_logs = get_quotes(stdout_log_path)
    command = command.replace(r'${PREFIX}', prefix)

    codepage = str(ctypes.cdll.kernel32.GetACP())
    prefix = prefix.replace('\\', '/')
    cmd = (
        'chcp {CODEPAGE}\n'
        # Call is needed to avoid the batch script from closing after running
        # the first (environment activation) line
        'call {QUOTE}{CONDA_ROOT_PREFIX}/Scripts/activate{QUOTE} '
        '{QUOTE}{CONDA_PREFIX}{QUOTE}\n'
        '{COMMAND} '
        '>{QUOTE_LOGS}{OUT}{QUOTE_LOGS} 2>{QUOTE_LOGS}{ERR}{QUOTE_LOGS}\n'
    ).format(
        CODEPAGE=codepage,
        CONDA_PREFIX=prefix,
        CONDA_ROOT_PREFIX=root_prefix,  # Activate only exist now on root env
        COMMAND=command.format(CONDA_PREFIX=prefix, CONDA_ROOT_PREFIX=root_prefix),
        QUOTE=quote,
        QUOTE_LOGS=quote_logs,
        OUT=stdout_log_path,
        ERR=stderr_log_path,
    )
    cmd = cmd.replace('/', '\\')  # Turn slashes back to windows standard

    suffix = 'bat'
    fpath = create_app_run_script(
        cmd,
        package_name,
        prefix,
        root_prefix,
        suffix,
    )
    # subprocess.CREATE_NO_WINDOW doesn't exist in python2
    CREATE_NO_WINDOW = 0x08000000
    popen_dict = {
        'creationflags': CREATE_NO_WINDOW,
        'shell': True,
        'cwd': cwd or os.path.expanduser('~'),
        'env': environment,
        'args': fpath,
        'id': id_,
        'cmd': cmd,
    }

    return popen_dict


def get_command_on_unix(
    prefix,
    command,
    package_name,
    root_prefix,
    environment=None,
    default_scripts_path=LAUNCH_SCRIPTS_PATH,
    non_conda=False,
    cwd=None,
):
    """Generate command to run on unix system and enforce env activation."""
    command = command.replace('${PREFIX}', prefix)
    stdout_log_path, stderr_log_path, id_ = get_package_logs(
        package_name,
        root_prefix=root_prefix,
        prefix=prefix,
        default_scripts_path=default_scripts_path,
    )
    quote = get_quotes(prefix)
    quote_logs = get_quotes(stdout_log_path)

    cmd = (
        '#!/usr/bin/env bash\n'
        '. {QUOTE}{CONDA_ROOT_PREFIX}/bin/activate{QUOTE} '
        '{QUOTE}{CONDA_PREFIX}{QUOTE}\n'
        '{COMMAND} '
        '>{QUOTE_LOGS}{OUT}{QUOTE_LOGS} 2>{QUOTE_LOGS}{ERR}{QUOTE_LOGS}\n'
    ).format(
        CONDA_PREFIX=prefix,
        CONDA_ROOT_PREFIX=root_prefix,  # Activate only exist now on root env
        COMMAND=command,
        QUOTE=quote,
        QUOTE_LOGS=quote_logs,
        OUT=stdout_log_path,
        ERR=stderr_log_path,
    )
    suffix = 'sh'
    fpath = create_app_run_script(
        cmd,
        package_name,
        prefix,
        root_prefix,
        suffix,
        default_scripts_path=default_scripts_path,
    )
    popen_dict = {
        'shell': True,
        'cwd': cwd or os.path.expanduser('~'),
        'env': environment,
        'args': fpath,
        'id': id_,
        'cmd': cmd,
    }
    return popen_dict


def launch(
    prefix,
    command,
    leave_path_alone,
    working_directory=os.path.expanduser('~'),
    package_name=None,
    root_prefix=None,
    environment=None,
    non_conda=False,
    as_admin=False,
):
    """Handle launching commands from projects."""
    logger.debug(str((prefix, command)))
    prefix = prefix.replace('\\', '/')
    root_prefix = root_prefix.replace('\\', '/')
    new_command = command.replace('\\', '/')

    pid = -1

    # if os.name == 'nt' and not leave_path_alone:
    #     command = command.replace('/bin', '/Scripts')

    if MAC or LINUX:
        popen_dict = get_command_on_unix(
            prefix=prefix,
            command=new_command,
            package_name=package_name,
            root_prefix=root_prefix,
            environment=environment,
            non_conda=non_conda,
            cwd=working_directory,
        )

    else:
        popen_dict = get_command_on_win(
            prefix=prefix,
            command=new_command,
            package_name=package_name,
            root_prefix=root_prefix,
            environment=environment,
            non_conda=non_conda,
            cwd=working_directory,
        )

    # args here is the temporary file that gets generated to carry
    #    out activation
    args = popen_dict.pop('args')
    id_ = popen_dict.pop('id')
    cmd = popen_dict.pop('cmd')
    cmd   # dummy usage for linter

    if WIN:
        if as_admin:
            p = run_as_admin(args)
        else:
            p = subprocess.Popen(args, **popen_dict).pid
    else:
        p = subprocess.Popen('sh {}'.format(args), **popen_dict).pid

    return p, id_


def console(activate=None, working_directory=os.path.expanduser('~'), term_command=''):
    """
    Open command prompt console and optionally activate the environment.
    optionally pass an application to be launched in terminal such as python,
    ipython, or jupyter as when called from py_in_console()
    """
    cwd = working_directory

    if os.name == 'nt':
        if activate:
            # cmd = 'start cmd.exe /k activate ' + activate
            cmd = 'start cmd.exe /k "activate "{}" & {}"'.format(activate, term_command)
        else:
            cmd = 'start cmd.exe'
        logger.debug(cmd)
        subprocess.Popen(cmd, shell=True, cwd=cwd)
    elif sys.platform == 'darwin':
        if activate:
            from anaconda_navigator.api.conda_api import CONDA_API
            rootprefix = CONDA_API.ROOT_PREFIX
            cmd = '''\
#!/usr/bin/osascript
tell application "Terminal"
    activate
    do script ". {}/bin/activate && conda activate {}; {}"
end tell
'''.format(rootprefix, activate, term_command)
        else:
            cmd = 'bash'
        fname = os.path.join(CONF_PATH, 'a.tool')

        with open(fname, 'w') as f:
            f.write(cmd)
        os.chmod(fname, 0o777)

        logger.debug(fname)
        subprocess.call([fname], shell=True, cwd=cwd)
    else:  # Linux, solaris, etc
        if is_program_installed('gnome-terminal'):
            if activate:
                cmd = [
                    'gnome-terminal',
                    '-x',
                    'bash',
                    '-c',
                    'bash --init-file'
                    ' <(echo ". activate {0};")'.format(activate),
                    '; {}'.format(term_command),
                ]
            else:
                cmd = ['gnome-terminal', '-e', 'bash']
            logger.debug(' '.join(cmd))
            subprocess.Popen(cmd, cwd=cwd)
        elif is_program_installed('xterm'):
            if activate:
                cmd = [
                    'xterm',
                    '-e',
                    'bash --init-file'
                    ' <(echo ". activate {0};")'.format(activate),
                    '; {}'.format(term_command),
                ]
            else:
                cmd = ['xterm']
            logger.debug(' '.join(cmd))
            subprocess.Popen(cmd, cwd=cwd)


def check_prog(prog, prefix=None):
    """Check if program exists in prefix."""
    api = AnacondaAPI()
    prefix = prefix or api.conda_get_prefix_envname(name='root')

    if prog in ['notebook', 'jupyter notebook']:
        pkgs = ['notebook', 'ipython-notebook', 'jupyter-notebook']
    elif prog in ['ipython', 'jupyter console']:
        pkgs = ['ipython', 'jupyter']
    else:
        pkgs = [prog]

    return any(
        api.conda_package_version(prefix=prefix, pkg=p) is not None
        for p in pkgs
    )


def py_in_console(activate=None, prog='python'):
    """
    Run (i)python in a new console.

    It optionally run activate first on the given env name/path.
    """
    logger.debug("%s, %s", activate, prog)
    if not check_prog(prog, activate):
        raise RuntimeError(
            'Program not available in environment: %s, %s', prog, activate
        )
    if prog == 'python':
        cmd = 'python -i'
    elif prog == 'ipython':
        cmd = 'ipython -i'
    elif 'notebook' in prog:
        cmd = 'jupyter notebook'
        from anaconda_navigator.api.conda_api import CONDA_API
        # Jupyter notebook shouldn't be launched from a console
        launch(activate, cmd, True, root_prefix=CONDA_API.ROOT_PREFIX)
        return
    else:
        cmd = None

    console(activate=activate, term_command=cmd)


def run_notebook(project_path, project=None, filename=""):
    """Start notebook server."""
    from anaconda_navigator.api import AnacondaAPI
    api = AnacondaAPI()

    if project is None:
        project = api.load_project(project_path)

    kernels_folder = os.sep.join([os.path.expanduser('~'), ".ipython", "kernels"])
    display_name = '{0} ({1})'.format(project.name, project_path)
    kernel_uuid = uuid.uuid1()
    kernel_path = os.sep.join([kernels_folder, "{name}", "kernel.json"])
    pyexec = get_pyexec(project.env_prefix(project_path))
    spec = {
        "argv": [pyexec, "-m", "IPython.kernel", "-f", "{connection_file}"],
        "display_name": display_name,
        "language": "python",
    }

    # Delete any other kernel sec mathching this name!
    kernels = os.listdir(kernels_folder)
    for kernel in kernels:
        path = os.sep.join([kernels_folder, kernel])
        file_path = os.sep.join([path, 'kernel.json'])

        if os.path.isfile(file_path):
            with open(file_path, 'r') as f:
                data = json.loads(f.read())

            name = data.get('display_name')
            if name is not None and project_path in name:
                shutil.rmtree(path)

    os.makedirs(os.path.split(kernel_path.format(name=kernel_uuid))[0])

    with open(kernel_path.format(name=kernel_uuid), 'w') as f:
        f.write(json.dumps(spec))

    # This is not working!
    cmd = (
        'jupyter notebook '
        '--KernelSpecManager.whitelist={0}'.format(kernel_uuid)
    )

    cmd = ('jupyter notebook')
    command = (cmd + ' ' + filename)
    logger.debug(",".join([command, project_path]))
    subprocess.Popen(command.split(), cwd=project_path)


def run_python_file(project_path, project=None, filename=""):
    """Execute python in environment."""
    from anaconda_navigator.api import AnacondaAPI
    api = AnacondaAPI()

    if project is None:
        project = api.load_project(project_path)

    cmd = get_pyexec(project.env_prefix(project_path))
    logger.debug(",".join([cmd, filename]))
    subprocess.Popen([cmd, filename])
