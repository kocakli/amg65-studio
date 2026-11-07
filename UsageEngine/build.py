#!/usr/bin/env python3
"""Build the independent usage helper using only macOS SDK frameworks.

--test compiles actual production parsers with secret-free offline checks. It
never runs Main.swift, provider fetch(), Keychain reads, or a provider request.
"""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent


def build(output=None, tests=False):
    target = Path(output) if output else PROJECT/'bin/amg65-usage'
    scratch = ROOT/'.build'
    scratch.mkdir(parents=True, exist_ok=True)
    sources = sorted(ROOT.glob('*.swift'))
    if tests:
        sources = [path for path in sources if path.name != 'Main.swift']
        sources += sorted((ROOT/'Tests').glob('*.swift'))
    architecture = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x86_64'}.get(platform.machine())
    if architecture is None:
        raise SystemExit('The usage helper requires an arm64 or x86_64 macOS build host.')
    with tempfile.TemporaryDirectory(prefix='usage-build-', dir=scratch) as directory:
        executable = Path(directory)/('usage-checks' if tests else 'amg65-usage')
        command = ['/usr/bin/xcrun', 'swiftc', '-swift-version', '6', '-parse-as-library', '-O',
                   '-target', architecture+'-apple-macos14.0', '-module-cache-path', str(scratch/'module-cache'),
                   *map(str, sources), '-framework', 'Security', '-framework', 'LocalAuthentication',
                   '-lsqlite3', '-o', str(executable)]
        subprocess.run(command, check=True, timeout=240)
        if tests:
            subprocess.run([str(executable)], check=True, timeout=30)
            return
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier',
                        'io.github.kocakli.amg65studio.usage', str(executable)], check=True, timeout=30)
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(executable)], check=True, timeout=30)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.usage-', dir=target.parent, delete=False) as staging:
            temporary = Path(staging.name)
        try:
            shutil.copy2(executable, temporary)
            temporary.chmod(0o755)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        print(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--test', action='store_true')
    arguments = parser.parse_args()
    build(arguments.output, tests=arguments.test)
