import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import wslc_docker as compat


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compat test ')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'WSLC_DOCKER_PATH_MODE': 'native'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.paths = compat.Paths()

    def translate(self, *args):
        return compat.translate(list(args), self.paths)[0]

    def test_alias_and_combined_flags(self):
        self.assertEqual(self.translate('ps', '-aq'), ['container', 'list', '--all', '--quiet'])
        self.assertEqual(self.translate('rm', '-fv', 'old'),
                         ['container', 'remove', '--force', '--volumes', 'old'])

    def test_container_command_boundary(self):
        tail = ['alpine', 'sh', '-c', 'printf "%s" "$VAR"', '--mount', 'leave:this-alone']
        self.assertEqual(self.translate('run', '-it', *tail),
                         ['container', 'run', '--interactive', '--tty', *tail])

    def test_exec_command_boundary(self):
        self.assertEqual(self.translate('exec', '-i', 'c', 'env', '--env-file', 'untouched'),
                         ['container', 'exec', '--interactive', 'c', 'env', '--env-file', 'untouched'])

    def test_named_and_anonymous_volumes(self):
        self.assertEqual(compat.volume('db:/var/lib/db', self.paths), 'db:/var/lib/db')
        self.assertEqual(compat.volume('/data', self.paths), '/data')

    def test_bind_space_and_attached_option(self):
        source = str(self.directory / 'two words')
        argv = self.translate('run', '-v' + source + ':/data:ro', 'alpine')
        self.assertEqual(argv, ['container', 'run', '--volume', source + ':/data:ro', 'alpine'])

    def test_windows_drive_volume(self):
        spec = r'C:\Users\me\two words:/data:ro'
        self.assertEqual(compat.volume(spec, self.paths), spec)

    def test_container_paths_are_not_translated(self):
        self.assertEqual(self.translate('run', '-w', '/app', '--entrypoint', '/bin/sh', 'alpine'),
                         ['container', 'run', '--workdir', '/app', '--entrypoint', '/bin/sh', 'alpine'])

    def test_mount_csv_with_comma(self):
        source = self.directory / 'a,b'
        source.mkdir()
        value = compat.mount(f'type=bind,"source={source}",target=/a,readonly', self.paths)
        fields = dict(compat.csv_fields(value))
        self.assertEqual(fields['source'], str(source))
        self.assertIn('readonly', fields)

    def test_bind_mount_missing_source_rejected(self):
        with self.assertRaises(compat.CompatError):
            compat.mount('type=bind,source=/definitely-missing-compat-source,target=/x', self.paths)

    def test_unsupported_mount_field_rejected(self):
        with self.assertRaises(compat.CompatError):
            compat.mount('type=bind,source=/tmp,target=/x,bind-propagation=shared', self.paths)

    def test_no_silent_volume_mode_loss(self):
        with self.assertRaises(compat.CompatError):
            compat.volume('x:/x:Z', self.paths)

    def test_env_inherited_from_linux(self):
        with patch.dict(os.environ, {'TEST_NAME': 'a b="c"'}):
            self.assertEqual(self.translate('run', '-eTEST_NAME', 'alpine'),
                             ['container', 'run', '--env', 'TEST_NAME=a b="c"', 'alpine'])

    def test_unset_env_fails_instead_of_using_windows_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(compat.CompatError):
                self.translate('run', '-e', 'ABSENT_KEY', 'alpine')

    def test_env_file_precedence_and_literals(self):
        env_file = self.directory / 'vars.env'
        env_file.write_bytes(b'\xef\xbb\xbf# comment\r\nA=file\r\nB="a $HOME # literal"\r\n')
        argv = self.translate('run', '-e', 'A=explicit', '--env-file', str(env_file), 'alpine')
        self.assertEqual(argv, ['container', 'run', '--env', 'A=file', '--env', 'B="a $HOME # literal"',
                                '--env', 'A=explicit', 'alpine'])

    def test_env_file_cannot_execute_commands(self):
        sentinel = self.directory / 'sentinel'
        env_file = self.directory / 'vars.env'
        env_file.write_text('A=$(touch ' + str(sentinel) + ')\n')
        self.translate('run', '--env-file', str(env_file), 'alpine')
        self.assertFalse(sentinel.exists())

    def test_build_dockerfile_preference(self):
        (self.directory / 'Dockerfile').write_text('FROM scratch\n')
        (self.directory / 'Containerfile').write_text('FROM wrong\n')
        argv = self.translate('build', str(self.directory), '-ttest:latest')
        self.assertEqual(argv, ['image', 'build', '--tag', 'test:latest', '--file',
                                str(self.directory / 'Dockerfile'), str(self.directory)])

    def test_build_stdin_dockerfile_supported(self):
        argv = self.translate('build', '-f-', str(self.directory))
        self.assertEqual(argv, ['image', 'build', '--file', '-', str(self.directory)])

    def test_build_requires_local_directory(self):
        for value in ('-', 'https://example.invalid/repo.git', 'git@example.invalid:repo'):
            with self.subTest(value=value), self.assertRaises(compat.CompatError):
                self.translate('build', value)

    def test_build_arg_from_linux_environment(self):
        with patch.dict(os.environ, {'BUILD_TEST': 'yes'}):
            argv = self.translate('build', '--build-arg', 'BUILD_TEST', '-f-', str(self.directory))
        self.assertIn('BUILD_TEST=yes', argv)

    def test_build_secrets_environment_not_silently_lost(self):
        with self.assertRaises(compat.CompatError):
            self.translate('build', '--secret', 'id=token,env=TOKEN', '-f-', str(self.directory))

    def test_cp_both_directions_and_dot_suffix(self):
        target = str(self.directory) + '/.'
        self.assertEqual(self.translate('cp', 'web:/var/www/.', target),
                         ['container', 'cp', 'web:/var/www/.', target])
        self.assertEqual(self.translate('cp', str(self.directory), 'web:/tmp'),
                         ['container', 'cp', str(self.directory), 'web:/tmp'])

    def test_cp_rejects_two_containers(self):
        with self.assertRaises(compat.CompatError):
            self.translate('cp', 'a:/x', 'b:/y')

    def test_restart_timeout_alias(self):
        self.assertEqual(self.translate('restart', '--time', '3', 'web'),
                         ['container', 'restart', '--timeout', '3', 'web'])
        self.assertEqual(self.translate('stop', '--timeout', '3', 'web'),
                         ['container', 'stop', '--time', '3', 'web'])

    def test_unknown_options_and_false_flags_fail(self):
        for args in (('run', '--privileged', 'alpine'), ('run', '--restart=always', 'alpine'),
                     ('run', '--rm=false', 'alpine'), ('run', '--name')):
            with self.subTest(args=args), self.assertRaises(compat.CompatError):
                self.translate(*args)

    def test_templates(self):
        argv, template, _ = compat.translate(['inspect', '-f', '{{.State.Running}}', 'web'], self.paths)
        self.assertEqual(argv, ['inspect', '--format', 'json', 'web'])
        self.assertEqual(compat.render_template(template, {'State': {'Running': True}}), 'true')
        self.assertEqual(compat.render_template('{{json .Ports}}', {'Ports': {'80/tcp': None}}), '{"80/tcp":null}')

    def test_unsupported_templates_fail_before_execution(self):
        for value in ('{{range .}}{{.Id}}{{end}}', 'table {{.ID}}', '{{index .Ports "80/tcp"}}'):
            with self.subTest(value=value), self.assertRaises(compat.CompatError):
                self.translate('ps', '--format', value)

    def test_missing_json_field_is_an_error(self):
        with self.assertRaises(compat.CompatError):
            compat.render_template('{{.State.Running}}', {'State': {}})

    def test_load_stdin_is_planned(self):
        argv, _, spool = compat.translate(['load'], self.paths)
        self.assertEqual(argv, ['image', 'load'])
        self.assertTrue(spool)
        self.assertTrue(compat.translate(['image', 'load', '-i', '-'], self.paths)[2])

    def test_dry_run_redacts_values(self):
        result = compat.redact(['backend', 'run', '--env', 'PASSWORD=secret', '--password', 'secret'])
        self.assertNotIn('secret', repr(result))

    def test_docker_host_never_silently_redirected(self):
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://remote.invalid'}):
            with self.assertRaises(compat.CompatError):
                compat.check_docker_environment()

    def test_windows_paths_use_wslpath(self):
        with patch.dict(os.environ, {'WSLC_DOCKER_PATH_MODE': 'windows'}), \
             patch('shutil.which', return_value='/usr/bin/wslpath'), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'C:\\a b\r\n', '')) as run:
            self.assertEqual(compat.Paths().host('/mnt/c/a b'), 'C:\\a b')
            self.assertEqual(run.call_args[0][0], ['/usr/bin/wslpath', '-w', '/mnt/c/a b'])


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compat process ')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fake = self.directory / 'wslc mock.exe'
        self.log = self.directory / 'argv.json'
        self.fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
pathlib.Path(os.environ['FAKE_LOG']).write_text(json.dumps(args))
mode = os.environ.get('FAKE_MODE', 'args')
if mode == 'echo':
    sys.stdout.buffer.write(sys.stdin.buffer.read())
elif mode == 'inspect':
    print('[{"State":{"Running":true}},{"State":{"Running":false}}]')
elif mode == 'lines':
    print('{"ID":"first"}\\n{"ID":"second"}')
elif mode == 'load':
    archive = args[args.index('--input') + 1]
    sys.stdout.buffer.write(pathlib.Path(archive).read_bytes())
else:
    print(json.dumps(args))
sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
''')
        self.fake.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('DOCKER_', 'WSLC_DOCKER_'))}
        self.env.update(WSLC_DOCKER_BIN=str(self.fake), WSLC_DOCKER_PATH_MODE='native', FAKE_LOG=str(self.log))

    def call(self, *args, env=None, data=None, entry='docker'):
        return subprocess.run([sys.executable, str(ROOT / 'bin' / entry), *args],
                              env={**self.env, **(env or {})}, input=data, capture_output=True)

    def test_args_preserved_and_never_evaluated(self):
        literal = 'a b "$HOME" $(touch SHOULD_NOT_EXIST) ; ! & 日本語'
        result = self.call('run', '--rm', 'alpine', 'printf', '%s', literal)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text())[-1], literal)

    def test_binary_stdin_stdout_unchanged(self):
        data = b'\x00\xff\r\n\x80test\n'
        result = self.call('exec', '-i', 'test', 'cat', env={'FAKE_MODE': 'echo'}, data=data)
        self.assertEqual(result.stdout, data)

    def test_backend_exit_code_preserved(self):
        result = self.call('run', '--rm', 'alpine', 'false', env={'FAKE_EXIT': '42'})
        self.assertEqual(result.returncode, 42)

    def test_template_array_and_json_lines(self):
        result = self.call('inspect', '-f', '{{.State.Running}}', 'web', env={'FAKE_MODE': 'inspect'})
        self.assertEqual(result.stdout, b'true\nfalse\n', result.stderr)
        result = self.call('ps', '--format', '{{.ID}}', env={'FAKE_MODE': 'lines'})
        self.assertEqual(result.stdout, b'first\nsecond\n', result.stderr)

    def test_template_failure_does_not_print_partial_success(self):
        result = self.call('inspect', '-f', '{{.Missing}}', 'web', env={'FAKE_MODE': 'inspect'})
        self.assertEqual(result.returncode, 125)
        self.assertEqual(result.stdout, b'')

    def test_stdin_archive_spools_binary_and_cleans_up(self):
        payload = b'fake archive\x00\xff' * 2048
        result = self.call('load', env={'FAKE_MODE': 'load'}, data=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, payload)
        args = json.loads(self.log.read_text())
        self.assertFalse(Path(args[args.index('--input') + 1]).exists())

    def test_dry_run_does_not_invoke_backend_or_read_stdin(self):
        result = self.call('dry-run', 'load', entry='docker-wslc')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['stdin_archive_to_tempfile'])
        self.assertFalse(self.log.exists())

    def test_compose_bridge_and_legacy_entry(self):
        for entry, args in [('docker', ('compose', '-f', 'my compose.yaml', 'up', '-d')),
                            ('docker-compose', ('-f', 'my compose.yaml', 'up', '-d'))]:
            with self.subTest(entry=entry):
                result = self.call(*args, entry=entry, env={'WSLC_DOCKER_COMPOSE_BIN': str(self.fake)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(self.log.read_text()), ['-f', 'my compose.yaml', 'up', '-d'])

    def test_bundled_compose_cli_version(self):
        result = self.call('version', entry='wslc-compose')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'0.2.1', result.stdout)

    def test_docker_compose_uses_bundled_implementation(self):
        clean_env = {k: v for k, v in self.env.items() if k != 'WSLC_DOCKER_BIN'}
        result = subprocess.run([sys.executable, str(ROOT / 'bin' / 'docker'), 'compose', 'version'],
                                env=clean_env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'wslc-compose', result.stdout)

    def test_recursive_backend_rejected(self):
        wrapper = ROOT / 'bin' / 'docker'
        wrapper.chmod(0o755)
        result = self.call('ps', env={'WSLC_DOCKER_BIN': str(wrapper)})
        self.assertEqual(result.returncode, 125)
        self.assertIn(b'recursive', result.stderr)

    def test_invalid_command_does_not_invoke_backend(self):
        result = self.call('buildx', 'build', '.')
        self.assertEqual(result.returncode, 125)
        self.assertFalse(self.log.exists())


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compat install ')
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / 'prefix with spaces'
        self.script = ROOT / 'scripts' / 'manage_install.py'

    def run_manage(self, action):
        return subprocess.run([sys.executable, str(self.script), action, '--prefix', str(self.prefix)], capture_output=True)

    def test_install_reinstall_uninstall_and_preserve_unrelated_files(self):
        result = self.run_manage('install')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        installed = self.prefix / 'bin' / 'docker-wslc'
        result = subprocess.run([str(installed), 'version'], capture_output=True)
        self.assertEqual(result.stdout.strip(), b'0.2.0')
        unrelated = self.prefix / 'bin' / 'my-tool'
        unrelated.write_text('keep')
        result = self.run_manage('install')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(self.run_manage('uninstall').returncode, 0)
        self.assertFalse(os.path.lexists(installed))
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_existing_docker_is_not_overwritten(self):
        target = self.prefix / 'bin' / 'docker'
        target.parent.mkdir(parents=True)
        target.write_text('real-docker')
        result = self.run_manage('install')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_text(), 'real-docker')
        self.assertFalse((self.prefix / 'share' / 'wslc-docker').exists())

    def test_unmanaged_package_directory_is_not_removed(self):
        target = self.prefix / 'share' / 'wslc-docker'
        target.mkdir(parents=True)
        (target / 'keep').write_text('keep')
        self.assertEqual(self.run_manage('uninstall').returncode, 1)
        self.assertTrue((target / 'keep').exists())


if __name__ == '__main__':
    unittest.main()
