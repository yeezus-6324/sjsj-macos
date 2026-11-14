"""Assemble an App from the read-only v1.5 release and a Web runtime."""
import argparse
import hashlib
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = '神将世界-无补丁验证'
COMPAT_NAME = '神将世界-兼容版'
SWF_MAGIC = {b'FWS', b'CWS', b'ZWS', b'\xaf\xc3\xc2', b'\xac\xc3\xc2', b'\xc3\xc3\xc2'}
PYTHON_RUNTIME = 'runtime/python'
PERSONAL_ICON = 'Contents/Resources/PersonalIcon.icns'
WEB_RUNTIME_FILES = re.compile(
    r'ruffle\.js(?:\.map)?|core\.ruffle\.[0-9a-f]+\.js(?:\.map)?|[0-9a-f]+\.wasm'
    r'|ruffle_web(?:-wasm_mvp)?_bg\.[A-Z0-9]+\.wasm'
    r'|LICENSE_APACHE|LICENSE_MIT|README\.md|package\.json'
)


def copy_file(source, destination):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'Expected a regular input file: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build(source, runtime, target, name=NAME, diagnostics=None, viewport_pixel_ratio_limit=None,
          retina_single_sample=False, sliced_reclaim=False, distribution_notices=None,
          personal_icon=None, release_version=None):
    original = source / 'Contents'
    resources = original / 'Resources'
    contents = target / 'Contents'
    output = contents / 'Resources'

    info = plistlib.loads((original / 'Info.plist').read_bytes())
    if (info['CFBundleIdentifier'], info['CFBundleShortVersionString']) != ('local.sjsj.release', '1.5'):
        raise ValueError('Expected the v1.5 release App')
    info.update(CFBundleIdentifier='local.sjsj.original-test', CFBundleName=name, CFBundleDisplayName=name)
    if distribution_notices:
        info['CFBundleIdentifier'] = 'local.sjsj.compatibility'
    if release_version:
        info.update(CFBundleShortVersionString=release_version, CFBundleVersion=release_version)
    info.pop('CFBundleIconFile', None)

    copy_file(original / 'MacOS/SJSJNative', contents / 'MacOS/SJSJNative')
    if personal_icon:
        info['CFBundleIconFile'] = Path(PERSONAL_ICON).name
        copy_file(personal_icon, target / PERSONAL_ICON)
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    copy_file(HERE / 'bridge_server.py', output / 'bridge_server.py')
    copy_file(HERE / 'player.html', output / 'player.html')
    if distribution_notices:
        player = output / 'player.html'
        page = player.read_text()
        start = page.index('// Record WebAssembly capacity')
        end = page.index('window.BehaviacSjsj=', start)
        player.write_text(page[:start] + page[end:]
                          .replace("report('player_loaded');", '')
                          .replace('report(String(e));', ''))
        for filename in ('Ruffle-Web-LICENSE.md', 'OpenSSL-LICENSE.txt', 'SQLite-copyright.html'):
            copy_file(distribution_notices / filename, output / 'Licenses' / filename)
    if viewport_pixel_ratio_limit is not None or retina_single_sample or sliced_reclaim:
        player = output / 'player.html'
        page = player.read_text()
        marker = 'window.RufflePlayer={config:'
        if page.count(marker) != 1:
            raise ValueError('Expected one Ruffle configuration')
        settings = []
        if distribution_notices:
            settings.append('window.__sjsjEarlierGc = true;')
        if viewport_pixel_ratio_limit is not None:
            settings.append(f'window.__sjsjViewportPixelRatioLimit = {viewport_pixel_ratio_limit};')
        if retina_single_sample:
            settings.append('window.__sjsjRetinaStageSingleSample = true;')
        if sliced_reclaim:
            settings.append('window.__sjsjSlicedReclaim = true;')
        player.write_text(page.replace(marker, '\n'.join([*settings, marker])))
    if diagnostics:
        for filename in ('freeze_diagnostics.py', 'freeze_diagnostics.js'):
            copy_file(HERE / filename, output / filename)
        (output / 'diagnostics-mode.txt').write_text(diagnostics + '\n')

    python_files = ('bin/python3.12', 'lib/python3.12/LICENSE.txt', 'lib/python3.12/codex-rejected-cas.pem')
    for relative in python_files:
        copy_file(resources / PYTHON_RUNTIME / relative, output / PYTHON_RUNTIME / relative)
    library = resources / PYTHON_RUNTIME / 'lib/python3.12'
    for source_file in library.rglob('*.py'):
        copy_file(source_file, output / PYTHON_RUNTIME / 'lib/python3.12' / source_file.relative_to(library))
    for name in ('_crypt.cpython-312-darwin.so', '_dbm.cpython-312-darwin.so'):
        copy_file(library / 'lib-dynload' / name, output / PYTHON_RUNTIME / 'lib/python3.12/lib-dynload' / name)

    for source_file in sorted(runtime.iterdir()):
        if WEB_RUNTIME_FILES.fullmatch(source_file.name):
            if distribution_notices and source_file.suffix == '.map':
                continue
            copy_file(source_file, output / 'web-runtime' / source_file.name)
    for name in ('ruffle.js', 'LICENSE_APACHE', 'LICENSE_MIT'):
        if not (output / 'web-runtime' / name).is_file():
            raise ValueError(f'Missing Web runtime file: {name}')
    if not list((output / 'web-runtime').glob('*.wasm')):
        raise ValueError('Missing Web runtime WASM')

    python = output / PYTHON_RUNTIME / 'bin/python3.12'
    subprocess.run(
        [str(python), '-I', '-B', '-c', 'import http.server, sqlite3, ssl, urllib.request; ssl.create_default_context()'],
        check=True,
    )
    sign = ['/usr/bin/codesign', '--force', '--sign', '-']
    if distribution_notices:
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder) / 'parent.plist'
            child = Path(folder) / 'child.plist'
            sandbox = {'com.apple.security.app-sandbox': True}
            parent.write_bytes(plistlib.dumps({
                **sandbox,
                'com.apple.security.network.client': True,
                'com.apple.security.network.server': True,
            }))
            child.write_bytes(plistlib.dumps({**sandbox, 'com.apple.security.inherit': True}))
            for binary in (output / PYTHON_RUNTIME).rglob('*.so'):
                subprocess.run([*sign, str(binary)], check=True)
            subprocess.run([*sign, '--entitlements', str(child), str(python)], check=True)
            subprocess.run([*sign, '--entitlements', str(parent), str(target)], check=True)
    else:
        subprocess.run([*sign, str(target)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(target)], check=True)


def audit(app, personal_icon=None):
    manifest = {}
    for item in sorted(app.rglob('*')):
        if item.is_symlink() or not (item.is_dir() or item.is_file()):
            raise ValueError(f'Unexpected entry in App: {item}')
        if item.is_file():
            body = item.read_bytes()
            if personal_icon and item.relative_to(app).as_posix() == PERSONAL_ICON:
                if (len(body) < 8 or body[:4] != b'icns'
                        or int.from_bytes(body[4:8], 'big') != len(body)
                        or body != personal_icon.read_bytes()):
                    raise ValueError(f'Invalid personal icon: {item}')
                manifest[PERSONAL_ICON] = hashlib.sha256(body).hexdigest()
                continue
            if item.suffix.lower() in {'.swf', '.delta', '.icns', '.zip', '.cache', '.data'} or body[:3] in SWF_MAGIC:
                raise ValueError(f'Unexpected resource in App: {item}')
            manifest[str(item.relative_to(app))] = hashlib.sha256(body).hexdigest()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, help='New directory for the build')
    parser.add_argument('--runtime', type=Path, help='Extracted Ruffle Web runtime directory')
    parser.add_argument('--compat', action='store_true', help='Build the compatibility App with an explicit runtime')
    parser.add_argument('--diagnostics', choices=('on', 'off', 'early'), help='Add freeze monitoring and select a collection mode')
    parser.add_argument('--name', help='Display name for the validation App')
    rendering = parser.add_mutually_exclusive_group()
    rendering.add_argument('--viewport-pixel-ratio-limit', type=float, choices=(1.0, 1.5),
                           help='Cap the backing resolution in a runtime that supports it')
    rendering.add_argument('--retina-single-sample', action='store_true',
                           help='Keep the native resolution and use single-sample stage rendering')
    parser.add_argument('--sliced-reclaim', action='store_true',
                        help='Spread pressure collection across animation callbacks')
    parser.add_argument('--distribution-notices', type=Path,
                        help='Build a sandboxed local validation package with dependency notices')
    parser.add_argument('--personal-icon', type=Path,
                        help='Explicit ICNS file for a personal sandboxed validation package')
    parser.add_argument('--release-version', metavar='VERSION',
                        help='Set the sandboxed package version, such as 2.0')
    args = parser.parse_args()
    if args.release_version and (not args.distribution_notices
                                 or not re.fullmatch(r'[1-9][0-9]*\.[0-9]+(?:\.[0-9]+)?', args.release_version)):
        parser.error('--release-version requires --distribution-notices and a numeric version such as 2.0')
    if args.personal_icon and not args.distribution_notices:
        parser.error('--personal-icon requires --distribution-notices')
    if args.distribution_notices and (args.diagnostics or not args.runtime or not args.sliced_reclaim):
        parser.error('Distribution validation requires --runtime and --sliced-reclaim without diagnostics')
    if (args.viewport_pixel_ratio_limit is not None or args.retina_single_sample
            or args.sliced_reclaim) and not args.runtime:
        parser.error('Runtime settings require an explicit --runtime')
    if args.compat and not args.runtime:
        parser.error('--compat requires --runtime')
    name = COMPAT_NAME if args.compat else NAME
    if args.diagnostics:
        if not args.runtime:
            parser.error('--diagnostics requires an explicit instrumented --runtime')
        name = {
            'on': '神将世界-诊断版',
            'off': '神将世界-回收对照版',
            'early': '神将世界-回收调度复测版',
        }[args.diagnostics]
    if args.name is not None:
        if not args.name.strip() or '/' in args.name or '\\' in args.name:
            parser.error('--name must be a nonempty App name without path separators')
        name = args.name
    source, output = args.source.resolve(), args.output.resolve()
    runtime = args.runtime.resolve() if args.runtime else source / 'Contents/Resources/web-runtime'
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(dir=output) as staging:
        app = Path(staging) / (name + '.app')
        build(source, runtime, app, name=name, diagnostics=args.diagnostics,
              viewport_pixel_ratio_limit=args.viewport_pixel_ratio_limit,
              retina_single_sample=args.retina_single_sample,
              sliced_reclaim=args.sliced_reclaim,
              distribution_notices=args.distribution_notices, personal_icon=args.personal_icon,
              release_version=args.release_version)
        manifest = audit(app, personal_icon=args.personal_icon)
        app.rename(output / app.name)
    (output / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in manifest.items()))


if __name__ == '__main__':
    main()
