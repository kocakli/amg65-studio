# AMG65 Studio

A macOS control center for the **wired LEOBOG AMG65**, with a native driver and a live **Claude · Cursor · Codex** usage dashboard.

The dashboard reads CodexBar's local usage cache and sends the remaining percentages to the keyboard's 63 × 5 LED matrix. It keeps each provider's quota windows separate, shows reset times, and marks stale or unavailable data honestly.

## Features

- A graphite dashboard with all three providers, reset countdowns and a live matrix preview.
- Mac time and time-zone synchronization for the keyboard clock, including reconnect and periodic sync.
- Combined usage, rotating provider details, and scrolling text on the LED matrix.
- RGB effects, brightness, speed and color controls.
- Native SwiftUI controls for per-key color, key mapping, LCD images/GIFs, LED animations and device settings.
- One USB writer at a time, bounded image decoding, strict packet acknowledgments and a persistent stop after an uncertain USB failure.
- A per-user background service; no administrator installation, kernel extension, microphone access or telemetry.

## Requirements

- macOS 14+ and Xcode Command Line Tools / Swift 5.9+.
- Python 3.10+ for the companion service; no third-party Python packages.
- Homebrew `libusb` for the full native app (`brew install libusb`). The native bundle's actual minimum macOS version follows the installed libusb build and is printed during packaging.
- An AMG65 connected by USB in wired mode: vendor `0x0C45`, product `0x800A`, vendor usage page `0xFF68`, usage `0x61`.
- [CodexBar](https://github.com/steipete/CodexBar) for usage data, with Claude, Cursor and Codex configured and **Share usage with CLI** enabled. The integration was verified with CodexBar 0.84.0.

Wireless mode and other keyboards are not supported. Only one AMG65 may be connected.

## Build and install

```sh
git clone https://github.com/kocakli/amg65-studio.git
cd amg65-studio
brew install libusb
./build.sh
python3 install.py
open "$HOME/Applications/AMG65 Studio.app"
```

The installer starts the companion at login and opens no external network ports. The panel is available at **http://127.0.0.1:47866/**. User settings and logs live under `~/Library/Application Support/AMG65 Studio/`; the app lives in `~/Applications/`.

For the dashboard and LED bridge without the native app or libusb:

```sh
./build.sh --dashboard-only
python3 install.py --dashboard-only
```

Builds are signed ad hoc for local use and are **not notarized**. The build script verifies the bundle signature. This repository distributes source; it does not include a prebuilt release or a firmware flasher.

## Using the controls

The native app opens on **Overview**, where the embedded dashboard owns the USB connection. Opening a native device page temporarily takes control; returning to Overview releases it and resumes the live usage display. The shared process lock also prevents a separate helper from writing simultaneously. A lease expires if the app stops renewing it.

The three large percentages represent the first available primary or weekly window for each provider; the exact window label is shown. These allowances cannot be added together. A missing measurement stays unknown. Data older than 15 minutes, or past its reset time, is marked as the last known value. On the hardware, `A`, `X` and `C` represent Claude, Codex and Cursor respectively; an amber marker indicates stale data.

**Refresh** rereads CodexBar's local cache. It does not sign in or independently poll providers. Set CodexBar's refresh frequency to five minutes for timely updates. Provider credentials and browser cookies remain with CodexBar; Studio does not copy them into its configuration.

If an acknowledgment is lost, the application stops sending to that USB attachment. Reconnect the keyboard before retrying. Successful acknowledgments confirm protocol acceptance, not a readback of every persistent keyboard setting.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
python3 NativeApp/Tests/run_checks.py
./build.sh
```

The Python tests cover cache privacy, malformed input, independent quota windows, stale timestamps, rendering, HTTP origin/host restrictions, settings validation and USB ownership transitions. Hardware testing is separate from unit tests.

On one connected AMG65, clock sync, live usage streaming, pause/resume and RGB application received USB acknowledgments; the user also confirmed the displayed usage text. See [the original source audit](docs/UPSTREAM_SECURITY_REVIEW.md) and [Studio security notes](docs/STUDIO_SECURITY.md) for scope, evidence and remaining limits. Bulk uploads, every key mapping, multiple physical keyboards and sleep/wake behavior need broader device testing.

## Stop or remove login startup

```sh
python3 install.py --remove-startup
```

This stops the background process and removes its LaunchAgent. The app and saved settings remain available. To run a preview without USB:

```sh
python3 app.py --no-device --state-dir /tmp/amg65-studio-preview
```

Stop the installed service first because both use the same local port.

## Code and third-party components

This is an independent application and is not an official LEOBOG, AULA or CodexBar release. Vendor skins, fonts, icons and sample media are not bundled. The protocol bridge includes material covered by the MIT notice in [THIRD_PARTY_LICENSE.txt](THIRD_PARTY_LICENSE.txt). The native build dynamically bundles libusb with its LGPL license and replacement notice. No broader license grant for Studio's own code is implied by those third-party notices.

## Türkçe

**AMG65 Studio**, klavyenin saatini Mac ile eşitler; Claude, Cursor ve Codex kalan kullanımını tek panelde ve klavyenin LED ekranında gösterir. RGB, tuş rengi/eşleme, LCD görseli ve LED animasyonu için yerel macOS arayüzü içerir.

Kurulum: `./build.sh`, ardından `python3 install.py`. Uygulama `~/Applications/AMG65 Studio.app`, panel `http://127.0.0.1:47866/` adresindedir. CodexBar'da CLI kullanım paylaşımı açık olmalıdır. Yenileme düğmesi yerel veriyi okur; düzenli güncelleme CodexBar tarafından yapılır. USB yanıtı kesilirse aktarım durur ve kablonun yeniden bağlanması gerekir.
