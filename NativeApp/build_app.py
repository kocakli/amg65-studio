#!/usr/bin/env python3
"""Build the native app with system artwork and bundled, replaceable libusb."""
from pathlib import Path
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from Tools.build_icon import compile_icon

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'build/AMG65 Studio.app'
SCRATCH = Path(os.environ.get('AMG65_BUILD_SCRATCH', ROOT / '.build')).resolve()


def run(*args):
    return subprocess.check_output(list(map(str,args)),text=True).strip()


def min_os(binary):
    text=run('/usr/bin/otool','-l',binary)
    found=re.findall(r'\bminos\s+([0-9.]+)',text)
    return max((tuple(map(int,v.split('.'))) for v in found),default=(14,0))


def main():
    prefix=Path(run('/opt/homebrew/bin/brew' if Path('/opt/homebrew/bin/brew').exists() else 'brew','--prefix','libusb'))
    dylib=prefix/'lib/libusb-1.0.0.dylib'
    if not dylib.is_file():
        raise SystemExit('libusb is required. Install it with: brew install libusb')
    build=['swift','build','--package-path',str(ROOT),'-c','release','--scratch-path',str(SCRATCH)]
    subprocess.run(build,check=True)
    binary=Path(run(*build,'--show-bin-path'))/'AMG65Studio'
    APP.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.package-',dir=APP.parent) as temporary:
        staged=Path(temporary)/APP.name
        package(binary,prefix,dylib,staged)
        previous=Path(temporary)/'previous.app'
        if APP.is_symlink():
            raise SystemExit('Refusing to replace a symlink at the app output path.')
        if APP.exists():
            info=plistlib.loads((APP/'Contents/Info.plist').read_bytes())
            if info.get('CFBundleIdentifier') != 'io.github.kocakli.amg65studio.desktop':
                raise SystemExit('Refusing to replace an unrelated app bundle.')
            APP.rename(previous)
        try:
            staged.rename(APP)
        except BaseException:
            if previous.exists(): previous.rename(APP)
            raise
    print(f'Built {APP}')


def package(binary,prefix,dylib,app):
    executable=app/'Contents/MacOS/AMG65Studio'
    frameworks=app/'Contents/Frameworks'
    resources=app/'Contents/Resources'
    executable.parent.mkdir(parents=True,exist_ok=True)
    frameworks.mkdir(parents=True,exist_ok=True)
    resources.mkdir(parents=True,exist_ok=True)
    shutil.copy2(binary,executable)
    bundled=frameworks/dylib.name
    shutil.copy2(dylib,bundled)
    bundled.chmod(0o755)
    subprocess.run(['/usr/bin/install_name_tool','-id','@rpath/'+dylib.name,str(bundled)],check=True)
    for line in run('/usr/bin/otool','-L',executable).splitlines()[1:]:
        dependency=line.strip().split(' (',1)[0]
        if dependency.endswith('/'+dylib.name):
            subprocess.run(['/usr/bin/install_name_tool','-change',dependency,'@executable_path/../Frameworks/'+dylib.name,str(executable)],check=True)
    minimum=max(min_os(binary),min_os(dylib))
    minimum_text='.'.join(map(str,minimum))
    info={'CFBundleName':'AMG65 Studio','CFBundleDisplayName':'AMG65 Studio',
          'CFBundleIdentifier':'io.github.kocakli.amg65studio.desktop',
          'CFBundleExecutable':'AMG65Studio','CFBundlePackageType':'APPL',
          'CFBundleVersion':'14','CFBundleShortVersionString':'0.3.0',
          'LSMinimumSystemVersion':minimum_text,'NSHighResolutionCapable':True,
          'NSPrincipalClass':'NSApplication'}
    catalogs=ROOT/'Sources/AMG65Studio/Resources/localizations'
    shutil.copytree(catalogs,resources/'localizations')
    info['CFBundleLocalizations']=['tr','en','es','zh-Hans','ja']
    info['CFBundleDevelopmentRegion']='tr'
    info.update(compile_icon(resources,minimum_macos=minimum_text))
    shutil.copy2(ROOT/'Resources/AppIcon.png',resources/'AppIcon.png')
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    actual_prefix=prefix.resolve()
    for name in ('COPYING','LICENSE','LICENSE.txt'):
        source=actual_prefix/name
        if source.is_file():
            shutil.copy2(source,resources/'libusb-LICENSE.txt')
            break
    else:
        raise SystemExit('Could not find installed libusb license; refusing to package an undocumented library.')
    (resources/'libusb-NOTICE.txt').write_text('libusb is dynamically linked under LGPL-2.1-or-later.\n'
        'Source and build instructions: https://github.com/libusb/libusb\n'
        'This ad-hoc signed bundle permits replacement and relinking of its libusb library.\n')
    (resources/'BUILD_INFO.json').write_text(json.dumps({'minimum_macos':minimum_text,'architecture':run('/usr/bin/uname','-m'),'signing':'ad-hoc; not notarized'},indent=2))
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(bundled)],check=True)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
    print(f'Minimum macOS for this build: {minimum_text}; ad-hoc signed, not notarized.')


if __name__ == '__main__': main()
