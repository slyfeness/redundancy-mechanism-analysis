"""Native masked input, with the result captured by a private subprocess pipe."""
import os
from pathlib import Path
import shutil
import subprocess


def ask_key(_prompt=None):
    if os.name != 'nt':
        raise RuntimeError('Native key input requires Windows')
    shell = shutil.which('pwsh') or shutil.which('powershell')
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'key-dialog.ps1'
    if shell is None or not script.is_file():
        raise RuntimeError('Native key input is unavailable')
    result = subprocess.run([shell, '-NoProfile', '-STA', '-File', str(script)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode == 130:
        raise KeyboardInterrupt
    if result.returncode:
        raise RuntimeError('Native key input failed')
    return result.stdout
