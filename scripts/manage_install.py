#!/usr/bin/env python3
"""Install only our own files. Never replace an existing Docker executable."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import sys

PACKAGE = 'wslc-docker'
MARKER = 'wslc-docker managed install v1\n'
NAMES = ('docker', 'docker-compose', 'docker-wslc', 'wslc-compose')


def manage():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'uninstall'))
    parser.add_argument('--prefix', default=str(Path.home() / '.local'))
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        raise RuntimeError('Python 3.9 or later is required.')
    prefix = Path(args.prefix).expanduser().absolute()
    dest = prefix / 'share' / PACKAGE
    bin_dir = prefix / 'bin'
    marker = dest / '.managed-install'
    if dest.is_symlink():
        raise RuntimeError('Refusing a symlink as the package destination.')
    if dest.exists() and (not marker.is_file() or marker.read_text() != MARKER):
        raise RuntimeError(f'Unmanaged destination already exists: {dest}')
    # Validate every entry before any mutation. An unrelated docker binary is untouched.
    for name in NAMES:
        link = bin_dir / name
        wanted = dest / 'bin' / name
        if os.path.lexists(link):
            if not link.is_symlink() or link.resolve() != wanted.resolve():
                raise RuntimeError(f'Refusing to replace or remove an existing command: {link}')
    if args.action == 'install':
        source = Path(__file__).resolve().parents[1]
        if source == dest.resolve():
            raise RuntimeError('Run install.sh from an extracted package, not the installed copy.')
        dest.mkdir(parents=True, exist_ok=True)
        # Marker is written before copy so interrupted installations remain recognizable.
        marker.write_text(MARKER)
        shutil.copytree(source, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.managed-install'))
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in NAMES:
            executable = dest / 'bin' / name
            executable.chmod(0o755)
            link = bin_dir / name
            if not os.path.lexists(link):
                link.symlink_to(os.path.relpath(executable, bin_dir))
        print('Installed: ' + ', '.join(str(bin_dir / name) for name in NAMES))
        print('Run in this shell:')
        print('  export PATH=' + shlex.quote(str(bin_dir)) + ':"$PATH"')
        print('  hash -r')
        print('  docker-wslc doctor')
        print('If docker is an old shell alias/function, remove that definition first.')
    else:
        for name in NAMES:
            link = bin_dir / name
            if link.is_symlink():
                link.unlink()
        if dest.exists():
            shutil.rmtree(dest)
        print('Removed wrapper commands and package files. WSL resources were not modified.')


if __name__ == '__main__':
    try:
        manage()
    except (OSError, RuntimeError) as exc:
        print('installer: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
