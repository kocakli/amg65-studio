#!/usr/bin/env python3
"""Compile the Icon Composer source with Apple's asset compiler.

The checked-in .icon document was created from Xcode's macOS Icon Composer
template and saved in Icon Composer 27.1. Artwork scale and layer properties
come from that editor; this script does not invent or rewrite its file format.

References:
https://developer.apple.com/documentation/xcode/creating-your-app-icon-using-icon-composer
The installed Xcode actool(1) manual documents the compilation and partial-plist
options used below. Full Xcode with Icon Composer support is required (26+).
Both modern Assets.car and the compiler's legacy ICNS are always produced.
"""
import argparse
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Resources/AppIcon.icon'
NAME = 'AppIcon'
TOOL_TIMEOUT = 60


def _run(arguments):
    try:
        result = subprocess.run(
            list(map(str, arguments)), capture_output=True, text=True,
            timeout=TOOL_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'Apple icon tool could not complete: {error}') from error
    if result.returncode:
        detail = (result.stdout + '\n' + result.stderr).strip()[-6000:]
        raise RuntimeError(
            'Modern icon compilation requires full Xcode 26 or later with working '
            'Icon Composer rendering services. Check xcode-select -p.\n' + detail
        )
    return result.stdout


def compile_icon(output_directory, minimum_macos='14.0'):
    """Write Assets.car/AppIcon.icns and return Apple's Info.plist icon entries.

    No GUI actions, global icon-cache changes, Dock restart, network access,
    image resampling or installation are performed. Outputs are validated before
    being copied into the caller's (normally staged) Resources directory.
    """
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}', minimum_macos):
        raise ValueError('minimum_macos must be a numeric macOS version, such as 14.0')
    if not (SOURCE / 'icon.json').is_file() or not (SOURCE / 'Assets').is_dir():
        raise FileNotFoundError(f'Missing complete Icon Composer source: {SOURCE}')

    # Resolve through the selected official developer directory, never a PATH
    # lookalike. An old actool is allowed to report its own unsupported-format error.
    actool = _run(['/usr/bin/xcrun', '--find', 'actool']).strip()
    assetutil = _run(['/usr/bin/xcrun', '--find', 'assetutil']).strip()
    destination = Path(output_directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.studio-icon-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        partial = stage / 'icon-info.plist'
        _run([
            actool, SOURCE, '--compile', stage,
            '--platform', 'macosx', '--target-device', 'mac',
            '--minimum-deployment-target', minimum_macos,
            '--app-icon', NAME, '--include-all-app-icons',
            '--standalone-icon-behavior', 'all',
            '--output-partial-info-plist', partial,
            '--warnings', '--errors', '--notices',
            '--output-format', 'human-readable-text',
        ])
        for name in ('Assets.car', NAME + '.icns', partial.name):
            path = stage / name
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f'Apple icon compiler did not produce {name}')

        info = plistlib.loads(partial.read_bytes())
        if info.get('CFBundleIconName') != NAME or info.get('CFBundleIconFile') not in (NAME, NAME + '.icns'):
            raise RuntimeError('Apple compiler returned unexpected app icon metadata')
        inventory = json.loads(_run([assetutil, '--info', stage / 'Assets.car']))
        if not isinstance(inventory, list) or not any(
            isinstance(entry, dict) and entry.get('AssetType') == 'IconImageStack'
            and entry.get('Name') == NAME for entry in inventory
        ):
            raise RuntimeError('Assets.car is missing the modern AppIcon icon stack')
        if not any(
            isinstance(entry, dict) and entry.get('AssetType') == 'MultiSized Image'
            and entry.get('Name') == NAME for entry in inventory
        ):
            raise RuntimeError('Assets.car is missing the legacy multi-size app icon')
        if (stage / (NAME + '.icns')).read_bytes()[:4] != b'icns':
            raise RuntimeError('Apple compiler returned an invalid ICNS file')

        for name in ('Assets.car', NAME + '.icns'):
            shutil.copy2(stage / name, destination / name)
        return {key: info[key] for key in ('CFBundleIconFile', 'CFBundleIconName')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--minimum-macos', default='14.0')
    args = parser.parse_args()
    try:
        info = compile_icon(args.output_dir, minimum_macos=args.minimum_macos)
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(info, sort_keys=True))


if __name__ == '__main__':
    main()
