#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'AMG65 Studio requires macOS.' >&2
  exit 1
fi
mkdir -p bin .build/clang
architecture="$(uname -m)"
xcrun swiftc -O -target "${architecture}-apple-macosx14.0" \
  -module-cache-path .build/clang -framework IOKit \
  AMG65HID.swift -o bin/amg65-hid
python3 UsageEngine/build.py
if [[ "${1:-}" != --dashboard-only ]]; then
  python3 NativeApp/build_app.py
fi
echo 'Build complete. Install with: python3 install.py'
