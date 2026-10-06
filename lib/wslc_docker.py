"""Docker CLI subset for WSL's wslc.exe. Python standard library only."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = '0.2.0'
ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = json.loads((Path(__file__).with_name('options.json')).read_text())
ALIASES = {
    **{s: 'container ' + s for s in (
        'run', 'create', 'exec', 'start', 'stop', 'restart', 'kill', 'attach',
        'logs', 'stats', 'export', 'cp')},
    **{s: 'image ' + s for s in ('build', 'pull', 'push', 'tag', 'save', 'load', 'import')},
    'ps': 'container list', 'images': 'image list', 'rm': 'container remove',
    'rmi': 'image remove', 'info': 'system info', 'events': 'system events',
    'login': 'registry login', 'logout': 'registry logout',
    'version': 'version', 'inspect': 'inspect',
}
FORWARD = {'container run', 'container create', 'container exec'}
WIN_PATH = re.compile(r'^(?:[A-Za-z]:[\\/]|\\\\|//)')
FIELD = r'\.(?:[A-Za-z_][A-Za-z_0-9]*)(?:\.[A-Za-z_][A-Za-z_0-9]*)*'
TEMPLATE = re.compile(r'{{\s*(?:(json)\s+)?(' + FIELD + r')\s*}}')
HELP = '''wslc-docker-compat 0.2.0 — Docker CLI subset for Ubuntu on WSL

Usage: docker COMMAND [OPTIONS]
Commands: run create exec ps images build pull push tag start stop restart rm rmi
          logs inspect cp save load import export kill attach stats login logout
          container image network volume system info events version compose

docker-wslc doctor                   Check WSL interop and installed wslc
docker-wslc dry-run run --rm alpine  Show translated argv (redacted; no execution)
docker-wslc capabilities             List supported command/option names
docker-wslc raw COMMAND ...          Explicitly bypass translation

This is a CLI adapter, not a Docker Engine API server. See README.ja.md.
'''


class CompatError(Exception):
    pass


def error(message):
    raise CompatError(message)


def check_docker_environment():
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        if os.environ.get(key):
            error(f'{key} is set, but this wrapper uses local wslc. Unset it explicitly to proceed.')


def resolve_executable(value):
    value = os.path.expanduser(value)
    result = shutil.which(value)
    if not result:
        error(f'Executable not found or not executable: {value}')
    result = str(Path(result).absolute())
    if Path(result).resolve() in {(ROOT / 'bin' / n).resolve() for n in ('docker', 'docker-compose', 'docker-wslc')}:
        error('Backend points at this wrapper; recursive invocation refused.')
    return result


def backend():
    explicit = os.environ.get('WSLC_DOCKER_BIN')
    if explicit:
        return resolve_executable(explicit)
    for value in ('wslc.exe', '/mnt/c/Program Files/WSL/wslc.exe'):
        if shutil.which(value):
            return resolve_executable(value)
    error('wslc.exe was not found. Update WSL on Windows, or set WSLC_DOCKER_BIN to its executable path.')


class Paths:
    def __init__(self):
        self.mode = os.environ.get('WSLC_DOCKER_PATH_MODE', 'windows')
        if self.mode not in ('windows', 'native'):
            error('WSLC_DOCKER_PATH_MODE must be windows or native.')

    def host(self, value):
        if value == '-' or WIN_PATH.match(value):
            return value
        absolute = os.path.abspath(os.path.expanduser(value))
        # normpath discards '/.'; docker cp uses it to copy directory contents.
        if value.endswith('/.'):
            absolute += '/.'
        if self.mode == 'native':
            return absolute
        converter = shutil.which('wslpath')
        if not converter:
            error('wslpath was not found. Run this wrapper inside WSL Ubuntu.')
        result = subprocess.run([converter, '-w', absolute], capture_output=True, text=True)
        if result.returncode or not result.stdout.strip():
            error(f'wslpath could not convert host path: {value}')
        return result.stdout.rstrip('\r\n')

    def local(self, value):
        if WIN_PATH.match(value):
            converter = shutil.which('wslpath')
            if not converter:
                error('Reading a Windows path requires wslpath.')
            result = subprocess.run([converter, '-u', value], capture_output=True, text=True)
            if result.returncode:
                error('wslpath could not convert a Windows path to a local path.')
            value = result.stdout.rstrip('\r\n')
        return Path(os.path.abspath(os.path.expanduser(value)))


def volume(spec, paths):
    # Greedy source allows drive-letter colons; target must be an absolute Linux path.
    match = re.fullmatch(r'(.+):(/[^:]*)(?::([^:]*))?', spec)
    if not match:
        if spec.startswith('/') and ':' not in spec:
            return spec  # anonymous container volume, not a host path
        error('Volume must be SOURCE:/container/path[:ro|rw] or /container/path.')
    source, target, modes = match.groups()
    if modes and any(x not in ('ro', 'rw') for x in modes.split(',')):
        error('This adapter supports only ro/rw volume modes. Use docker-wslc raw for native wslc options.')
    if source.startswith(('/', '.', '~')) or WIN_PATH.match(source) or '/' in source:
        source = paths.host(source)
    return source + ':' + target + (':' + modes if modes else '')


def csv_fields(value):
    try:
        fields = next(csv.reader([value], strict=True))
    except (csv.Error, StopIteration):
        error('Invalid CSV option value.')
    result = []
    for field in fields:
        key, sep, val = field.partition('=')
        result.append((key, val if sep else None))
    return result


def csv_join(fields):
    out = io.StringIO()
    csv.writer(out, lineterminator='').writerow([k if v is None else k + '=' + v for k, v in fields])
    return out.getvalue()


def mount(spec, paths):
    fields = csv_fields(spec)
    normalized = []
    seen = set()
    aliases = {'src': 'source', 'dst': 'target', 'destination': 'target', 'ro': 'readonly'}
    allowed = {'type', 'source', 'target', 'readonly'}
    for key, value in fields:
        key = aliases.get(key, key)
        if key not in allowed or key in seen:
            error(f'Unsupported or duplicate --mount field: {key}')
        if value is None and key != 'readonly':
            error(f'--mount field requires a value: {key}')
        seen.add(key)
        normalized.append((key, value))
    values = dict(normalized)
    kind = values.get('type', 'volume')
    if kind not in ('bind', 'volume', 'tmpfs'):
        error('Supported --mount types: bind, volume, tmpfs.')
    if not (values.get('target') or '').startswith('/'):
        error('--mount requires an absolute container target path.')
    if values.get('readonly') not in (None, 'true', 'false', '1', '0'):
        error('readonly must be true or false.')
    if kind == 'bind':
        source = values.get('source')
        if not source or not paths.local(source).exists():
            error('--mount type=bind requires an existing source.')
        normalized = [(k, paths.host(v) if k == 'source' else v) for k, v in normalized]
    return csv_join(normalized)


def environment(value):
    key, sep, val = value.partition('=')
    if not key or any(c in key for c in ('\x00', '\r', '\n')):
        error('Invalid environment variable name.')
    if not sep:
        if key not in os.environ:
            error(f'{key} is unset in Ubuntu. Specify {key}=VALUE explicitly; unsetting image environment is not emulated.')
        val = os.environ[key]
    return key + '=' + val


def env_file(filename, paths):
    text = paths.local(filename).read_text(encoding='utf-8-sig')
    values = []
    for line in text.splitlines():
        line = line.lstrip()
        if not line or line.startswith('#'):
            continue
        key = line.partition('=')[0]
        if any(c.isspace() for c in key):
            error('Whitespace in an env-file variable name is unsupported.')
        values.append(environment(line))
    return values


def parse_options(args, schema, forward=False):
    """Parse Docker flags without interpreting the container's trailing command."""
    options, positional = [], []
    i = 0
    while i < len(args):
        token = args[i]
        i += 1
        if token == '--':
            positional.extend(args[i:])
            break
        if token == '-' or not token.startswith('-'):
            positional.append(token)
            if forward:
                positional.extend(args[i:])
                break
            continue
        parts = []
        if token.startswith('--'):
            name, sep, attached = token.partition('=')
            parts.append((name, attached if sep else None))
        else:
            # -it, -aq, -v/path:/work, -eKEY=VALUE, -itv/path:/work
            j = 1
            while j < len(token):
                name = '-' + token[j]
                if name not in schema:
                    error(f'Unsupported option: {name}')
                j += 1
                if schema[name]['kind'] == 'value':
                    attached = token[j:] or None
                    if attached is not None and attached.startswith('='):
                        attached = attached[1:]
                    parts.append((name, attached))
                    break
                parts.append((name, None))
        for name, value in parts:
            if name not in schema:
                error(f'Unsupported option for this command: {name}')
            definition = schema[name]
            if definition['kind'] == 'value':
                if value is None:
                    if i == len(args):
                        error(f'{name} requires a value.')
                    value = args[i]
                    i += 1
            elif value is not None:
                if value != 'true':
                    error(f'{name}={value} is unsupported; omit false flags explicitly.')
                value = None
            options.append((definition['target'], value))
    return options, positional


def validate_template(value):
    remaining = TEMPLATE.sub('', value)
    if '{{' in remaining or '}}' in remaining or value.startswith('table '):
        error('Supported --format templates: {{.Field}}, {{.Nested.Field}}, {{json .Field}}. Go logic and table templates are unsupported.')


def render_template(template, obj):
    def replace(match):
        value = obj
        for part in match[2][1:].split('.'):
            if not isinstance(value, dict) or part not in value:
                error(f'Field {match[2]} is absent in wslc JSON; its schema differs from Docker.')
            value = value[part]
        if match[1] or isinstance(value, (list, dict, bool)) or value is None:
            return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        return str(value)
    return TEMPLATE.sub(replace, template)


def canonical(args):
    if not args or args[0] in ('--help', '-h', 'help'):
        return 'help', []
    if args[0] in ('--version', '-v'):
        if len(args) > 1:
            error('--version cannot be combined with a command.')
        return 'version', []
    command = args[0]
    if command in ('container', 'image', 'network', 'volume', 'system'):
        if len(args) < 2 or args[1] == '--help':
            return 'group-help', [command]
        sub = {'ls': 'list', 'ps': 'list', 'rm': 'remove'}.get(args[1], args[1])
        return command + ' ' + sub, args[2:]
    return ALIASES.get(command, command), args[1:]


def translate(args, paths):
    key, rest = canonical(args)
    if key not in SCHEMAS:
        error(f'Unsupported command: {key}. See docker-wslc capabilities.')
    schema = dict(SCHEMAS[key])
    if '-h' not in schema:
        schema['-h'] = {'kind': 'flag', 'target': '--help'}
    # Docker supports both names; source names differ between stop/restart.
    if key in ('container stop', 'container restart'):
        target = '--time' if key.endswith('stop') else '--timeout'
        schema['--time'] = schema['--timeout'] = {'kind': 'value', 'target': target}
    options, pos = parse_options(rest, schema, key in FORWARD)
    command = key.split()
    if any(k == '--help' for k, v in options):
        return command + ['--help'], None, False
    if key in FORWARD and not pos:
        error(f'{key} requires an image or container name.')
    if key == 'container exec' and len(pos) < 2:
        error('exec requires a container and a command.')
    if key == 'image load' and pos:
        error('load takes no positional arguments; use -i FILE or stdin.')
    output = []
    file_env, explicit_env = [], []
    template = None
    has_input = False
    for name, value in options:
        if name == '--format' and value not in ('json', 'table'):
            validate_template(value)
            template, value = value, 'json'
        if name == '--volume' and key in ('container run', 'container create'):
            value = volume(value, paths)
        elif name == '--mount':
            value = mount(value, paths)
        elif name == '--env-file':
            file_env.extend(env_file(value, paths))
            continue
        elif name == '--env':
            explicit_env.append(environment(value))
            continue
        elif name == '--build-arg':
            value = environment(value)
        elif name in ('--file', '--cidfile', '--iidfile'):
            value = paths.host(value)
        elif name == '--input' and key == 'image load':
            has_input = value != '-'
            if not has_input:
                continue
            value = paths.host(value)
        elif name == '--output':
            if key == 'image build':
                fields = csv_fields(value)
                if not any(k == 'type' for k, v in fields):
                    error('build --output requires an explicit type; directory exporters are not supported.')
                value = csv_join([(k, paths.host(v) if k in ('dest', 'destination') and v is not None else v) for k, v in fields])
            else:
                value = paths.host(value)
        elif name == '--secret' and key == 'image build':
            fields = csv_fields(value)
            if any(k in ('env',) or (k == 'type' and v == 'env') for k, v in fields):
                error('Build secrets from environment require Windows env forwarding. Use type=file,src=PATH instead.')
            if not any(k in ('src', 'source') and v for k, v in fields):
                error('Build secrets must explicitly specify a source file.')
            value = csv_join([(k, paths.host(v) if k in ('src', 'source') and v is not None else v) for k, v in fields])
        output.append(name)
        if value is not None:
            output.append(value)
    # Docker env-file values precede explicit --env, irrespective of flag order.
    for value in file_env + explicit_env:
        output.extend(['--env', value])
    if key == 'image build':
        if len(pos) != 1:
            error('build requires one local directory context.')
        if pos[0] == '-' or re.match(r'^(?:[a-z]+://|git@)', pos[0]):
            error('URL and stdin build contexts are unsupported by this adapter. Use a local directory.')
        local = paths.local(pos[0])
        if not local.is_dir():
            error('Build context must be an existing local directory.')
        if not any(k == '--file' for k, v in options):
            # Dockerfile wins, even if Containerfile also exists.
            dockerfile = local / 'Dockerfile'
            if not dockerfile.is_file():
                error('Dockerfile not found. To use Containerfile, specify -f Containerfile.')
            output.extend(['--file', paths.host(str(dockerfile))])
        pos = [paths.host(pos[0])]
    elif key == 'container cp':
        if len(pos) != 2:
            error('cp requires SOURCE and DESTINATION.')
        def endpoint(value):
            if value == '-':
                error('cp tar streams are not supported by this adapter.')
            if WIN_PATH.match(value) or value.startswith(('/', './', '../', '~')) or ':' not in value:
                return paths.host(value), False
            return value, True
        endpoints = [endpoint(p) for p in pos]
        if sum(is_container for p, is_container in endpoints) != 1:
            error('cp requires one local endpoint and one CONTAINER:PATH endpoint.')
        pos = [p for p, _ in endpoints]
    elif key == 'image import':
        if not pos or pos[0] == '-' or '://' in pos[0]:
            error('import requires a local archive file; URLs and stdin are unsupported.')
        pos[0] = paths.host(pos[0])
    return command + output + pos, template, key == 'image load' and not has_input


def redact(argv):
    result = list(argv)
    for i, value in enumerate(argv[:-1]):
        if value in ('--env', '-e', '--build-arg', '--password', '-p'):
            # -p in native compose is project name, but conservative redaction is fine.
            raw = argv[i + 1]
            result[i + 1] = (raw.partition('=')[0] + '=<redacted>') if '=' in raw else '<redacted>'
    return result


def show_plan(argv, stdin_load=False):
    print(json.dumps({'argv': redact(argv), 'stdin_archive_to_tempfile': stdin_load}, ensure_ascii=False, indent=2))


def exit_code(code):
    return 128 - code if code < 0 else code


def execute(argv, template=None):
    if template is None:
        # No shell intermediary: quotes, spaces, binary streams and TTY are preserved.
        os.execvpe(argv[0], argv, os.environ.copy())
        raise AssertionError('exec returned')
    result = subprocess.run(argv, stdout=subprocess.PIPE)
    if result.returncode:
        return exit_code(result.returncode)
    text = result.stdout.decode('utf-8-sig')
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError:
            error('wslc did not return parseable JSON for --format.')
    rendered = [render_template(template, row) for row in rows]
    for line in rendered:
        print(line)
    return 0


def dispatch(args, dry=False):
    if not args or args == ['--help'] or args == ['-h'] or args == ['help']:
        print(HELP)
        return 0
    if args[0] == 'help':
        return dispatch([*args[1:], '--help'], dry=dry)
    check_docker_environment()
    key, rest = canonical(args)
    if key == 'compose':
        value = (
            os.environ.get('WSLC_DOCKER_COMPOSE_BIN')
            or shutil.which('wslc-compose')
            or str(ROOT / 'bin' / 'wslc-compose')
        )
        if not value:
            error('Compose needs a separate wslc-compatible backend. Install wslc-compose and/or set WSLC_DOCKER_COMPOSE_BIN. See README.ja.md.')
        argv = [resolve_executable(value), *rest]
        if dry:
            show_plan(argv)
            return 0
        return execute(argv)
    binary = backend()
    if key == 'group-help':
        argv = [binary, *rest, '--help']
        if dry:
            show_plan(argv)
            return 0
        return execute(argv)
    argv, template, stdin_load = translate(args, Paths())
    argv = [binary, *argv]
    if dry:
        show_plan(argv, stdin_load)
        return 0
    if stdin_load:
        if sys.stdin.isatty():
            error('load needs -i FILE or a tar archive on stdin.')
        # Current wslc image load only accepts a filename. Stream to disk, not RAM.
        with tempfile.TemporaryDirectory(prefix='wslc-docker-load-') as directory:
            archive = Path(directory) / 'image.tar'
            with archive.open('wb') as stream:
                shutil.copyfileobj(sys.stdin.buffer, stream, length=1024 * 1024)
            argv.extend(['--input', Paths().host(str(archive))])
            return exit_code(subprocess.run(argv).returncode)
    return execute(argv, template)


def guarded(call):
    try:
        return call()
    except CompatError as exc:
        print(f'docker-wslc: {exc}', file=sys.stderr)
        return 125
    except (OSError, UnicodeError, csv.Error) as exc:
        print(f'docker-wslc: {exc}', file=sys.stderr)
        return 125
    except KeyboardInterrupt:
        return 130


def main(args=None):
    return guarded(lambda: dispatch(sys.argv[1:] if args is None else args))


def doctor():
    print(f'wslc-docker-compat {VERSION}')
    print('Python:', sys.version.split()[0])
    print('WSL distro:', os.environ.get('WSL_DISTRO_NAME', '(not detected)'))
    print('wslpath:', shutil.which('wslpath') or '(missing)')
    print('Path mode:', Paths().mode)
    print('Compose:', os.environ.get('WSLC_DOCKER_COMPOSE_BIN') or shutil.which('wslc-compose') or '(not configured)')
    check_docker_environment()
    binary = backend()
    print('wslc:', binary, flush=True)
    ok = True
    for args in (['version'], ['container', 'list', '--quiet']):
        try:
            result = subprocess.run([binary, *args], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            print('FAIL: wslc ' + ' '.join(args) + ' timed out')
            ok = False
            continue
        print(('OK: ' if result.returncode == 0 else 'FAIL: ') + 'wslc ' + ' '.join(args))
        if args == ['version'] or result.returncode:
            print((result.stdout + result.stderr).strip())
        ok = ok and result.returncode == 0
    print('Bind-mount, build and TTY checks: run scripts/smoke-test.sh on your WSL machine.')
    return 0 if ok else 1


def admin(args):
    def run():
        if not args or args[0] in ('help', '--help', '-h'):
            print(HELP)
            return 0
        if args[0] == 'doctor':
            return doctor()
        if args[0] == 'version':
            print(VERSION)
            return 0
        if args[0] == 'dry-run':
            return dispatch(args[1:], dry=True)
        if args[0] == 'capabilities':
            for command, schema in sorted(SCHEMAS.items()):
                print(command + ': ' + ' '.join(sorted(k for k in schema if k.startswith('--'))))
            print('compose: separate backend required; see README.ja.md')
            return 0
        if args[0] == 'raw':
            if len(args) == 1:
                error('raw requires native wslc arguments.')
            return execute([backend(), *args[1:]])
        error('Unknown administration command. See docker-wslc --help.')
    return guarded(run)
