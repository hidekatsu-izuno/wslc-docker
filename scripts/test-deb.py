#!/usr/bin/env python3
"""Verify a .deb with a private dpkg database and installation root."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(argv, *, env=None, expected=0):
    result = subprocess.run([str(arg) for arg in argv], env=env,
                            capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError(f'{argv!r}: exit {result.returncode}\n'
                             f'{result.stdout}\n{result.stderr}')
    return result


def check_package(package):
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo; all installation changes stay in a temporary root.')
    with tempfile.TemporaryDirectory(prefix='wslc-deb-test-') as directory:
        work = Path(directory)
        root = work / 'root'
        admin = root / 'var/lib/dpkg'
        admin.mkdir(parents=True)
        (admin / 'status').touch()

        def dpkg(*args, **kwargs):
            return run(['dpkg', f'--root={root}', *args], **kwargs)

        def fixture(name, version, files=None):
            stage = work / f'{name}-{version}'
            (stage / 'DEBIAN').mkdir(parents=True)
            (stage / 'DEBIAN/control').write_text(
                f'Package: {name}\nVersion: {version}\nArchitecture: all\n'
                'Maintainer: Package test <test@example.invalid>\n'
                'Description: Isolated packaging test fixture\n')
            for path, content in (files or {}).items():
                destination = stage / path.lstrip('/')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content)
                destination.chmod(0o755)
            archive = work / f'{name}-{version}.deb'
            run(['dpkg-deb', '--root-owner-group', '--build', stage, archive])
            return archive

        dpkg('--install', fixture('python3', '3.12.0'),
             fixture('python3-yaml', '6.0.1'))

        # Verify collisions are rejected before an existing provider is overwritten.
        providers = ('docker.io', 'docker-cli', 'docker-ce-cli',
                     'podman-docker', 'moby-cli', 'docker-compose')
        for provider in providers:
            command = 'docker-compose' if provider == 'docker-compose' else 'docker'
            original = '#!/bin/sh\necho original-provider\n'
            dpkg('--install', fixture(provider, '1.0.0',
                                      {f'/usr/bin/{command}': original}))
            rejected = subprocess.run(['dpkg', f'--root={root}', '--install', str(package)],
                                      capture_output=True, text=True)
            assert rejected.returncode != 0, f'Conflict with {provider} was accepted'
            assert provider in rejected.stderr and 'conflict' in rejected.stderr.lower(), rejected.stderr
            assert (root / f'usr/bin/{command}').read_text() == original
            dpkg('--remove', provider)

        # Upgrade from the old package, which did not register docker commands.
        old_marker = '/usr/lib/wslc-docker/legacy-marker'
        dpkg('--install', fixture('wslc-docker', '0.0.0', {old_marker: 'old-layout'}))
        dpkg('--install', package)
        assert not (root / old_marker.lstrip('/')).exists()
        dpkg('--install', package)  # Reinstallation must also work.

        commands = ('docker', 'docker-compose', 'docker-wslc', 'wslc-docker', 'wslc-compose')
        for command in commands:
            link = root / 'usr/bin' / command
            target = 'docker-wslc' if command == 'wslc-docker' else command
            assert link.is_symlink(), f'{command} is not registered'
            assert link.resolve() == root / 'usr/lib/wslc-docker/bin' / target
            assert os.access(link, os.X_OK), f'{command} is not executable'
            assert 'wslc-docker:' in dpkg('--search', f'/usr/bin/{command}').stdout

        # Use the normal command names in PATH and automatically find a fake wslc.exe.
        backend_dir = work / 'backend'
        backend_dir.mkdir()
        backend = backend_dir / 'wslc.exe'
        backend.write_text('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
        backend.chmod(0o755)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('DOCKER_', 'WSLC_'))}
        env.update(PATH=f'{root}/usr/bin:{backend_dir}:{Path(sys.executable).parent}:{os.environ["PATH"]}',
                   WSLC_DOCKER_PATH_MODE='native', PYTHONDONTWRITEBYTECODE='1')
        assert shutil.which('docker', path=env['PATH']) == str(root / 'usr/bin/docker')
        assert json.loads(run(['docker', 'ps', '-a'], env=env).stdout) == ['container', 'list', '--all']
        for argv in (['docker', 'compose', '--version'], ['docker-compose', '--version'],
                     ['wslc-compose', '--version']):
            assert 'wslc-compose 0.2.1' in run(argv, env=env).stdout
        for command in ('docker-wslc', 'wslc-docker'):
            assert run([command, 'version'], env=env).stdout.strip() == '0.2.0'

        dpkg('--remove', 'wslc-docker')
        for command in commands:
            assert not os.path.lexists(root / 'usr/bin' / command), f'{command} survived removal'
        assert backend.exists(), 'Removal touched the external backend'
        print('PASS: default commands, Compose, upgrade, reinstall, six conflicts and removal')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: sudo python3 scripts/test-deb.py path/to/package.deb')
    check_package(Path(sys.argv[1]).resolve())
