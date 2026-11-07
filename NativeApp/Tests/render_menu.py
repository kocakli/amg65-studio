#!/usr/bin/env python3
"""Render actual SwiftUI popover from fixtures, without windows, USB or HTTP."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'.build/menu-preview'
BUILD.mkdir(parents=True,exist_ok=True)
DESTINATION=Path(sys.argv[1]).resolve()
DESTINATION.mkdir(parents=True,exist_ok=True)
brew='/opt/homebrew/bin/brew' if Path('/opt/homebrew/bin/brew').exists() else 'brew'
prefix=Path(subprocess.check_output([brew,'--prefix','libusb'],text=True).strip())
sources=sorted(path for path in (ROOT/'Sources/AMG65Studio').glob('*.swift'))
subprocess.run(['xcrun','swiftc','-parse-as-library','-D','STUDIO_UI_PREVIEW','-D','STUDIO_HOST_PREVIEW','-module-name','AMG65MenuPreview',
    '-module-cache-path',str(BUILD/'module-cache'),'-I',str(ROOT/'Sources/CLibUSB'),'-Xcc','-I'+str(prefix/'include/libusb-1.0'),
    '-L',str(prefix/'lib'),'-lusb-1.0','-framework','IOKit',*map(str,sources),str(ROOT/'Tests/MenuPreview.swift'),'-o',str(BUILD/'menu-preview')],check=True)
subprocess.run([str(BUILD/'menu-preview'),str(DESTINATION)],check=True)
print(DESTINATION)
