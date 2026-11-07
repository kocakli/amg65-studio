#!/usr/bin/env python3
"""Compile actual production logic and run checks without opening hardware."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('AMG65_CHECKS_BUILD', ROOT/'.build/checks')).resolve()
BUILD.mkdir(parents=True, exist_ok=True)
BREW = '/opt/homebrew/bin/brew' if Path('/opt/homebrew/bin/brew').exists() else 'brew'
prefix = Path(subprocess.check_output([BREW,'--prefix','libusb'],text=True).strip())
sources = sorted(path for path in (ROOT/'Sources/AMG65Studio').glob('*.swift') if path.name != 'StudioApp.swift')
binary = BUILD/'native-checks'
subprocess.run(['xcrun','swiftc','-parse-as-library','-module-name','AMG65OfflineChecks',
                '-module-cache-path',str(BUILD/'module-cache'),
                '-I',str(ROOT/'Sources/CLibUSB'),'-Xcc','-I'+str(prefix/'include/libusb-1.0'),
                '-L',str(prefix/'lib'),'-lusb-1.0','-framework','IOKit',
                *map(str,sources),str(ROOT/'Tests/NativeChecks.swift'),'-o',str(binary)],check=True)
subprocess.run([str(binary)],check=True)
