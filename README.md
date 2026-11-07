# AMG65 Studio

A macOS control center for the **wired LEOBOG AMG65**, with a native driver and a live **Claude · Cursor · Codex** usage dashboard.

Studio's bundled usage engine reads the providers' own signed-in sessions, fetches quotas directly, and sends the remaining percentages to the keyboard's 63 × 5 LED matrix. It keeps each provider's quota windows separate, shows reset times, and marks stale or unavailable data honestly.

## Features

- A graphite dashboard with all three providers, reset countdowns and a live matrix preview.
- A custom macOS icon and Turkish, English, Spanish, Simplified Chinese and Japanese interfaces.
- A native translucent menu bar control center with provider tabs, quota bars, reset times, account sign-in and every Studio device page.
- Mac time and time-zone synchronization for the keyboard clock, including reconnect and periodic sync.
- Combined usage, rotating provider details, and scrolling text on the LED matrix.
- RGB effects, brightness, speed and color controls.
- Native SwiftUI controls for per-key color, key mapping, LCD images/GIFs, LED animations and device settings.
- One USB writer at a time, bounded image decoding, strict packet acknowledgments and a persistent stop after an uncertain USB failure.
- Live job activity on the LED strip: real approval/input events take priority, working states alternate with quotas, and completion fades back to normal.
- A per-user background service; no administrator installation, kernel extension, microphone access or telemetry.

## Requirements

- macOS 14+ and Swift 6.2+. The full native app's modern icon build requires Xcode with Icon Composer support; the dashboard-only build works with Command Line Tools.
- Python 3.10+ for the companion service; no third-party Python packages.
- Homebrew `libusb` for the full native app (`brew install libusb`). The native bundle's actual minimum macOS version follows the installed libusb build and is printed during packaging.
- An AMG65 connected by USB in wired mode: vendor `0x0C45`, product `0x800A`, vendor usage page `0xFF68`, usage `0x61`.
- The Codex CLI for sign-in, and a signed-in Cursor desktop app. The full build prepares a private, official Claude sign-in helper; an existing Claude Code installation is not modified. CodexBar is **not required**. The independent helper uses only macOS SDK frameworks; no additional runtime package is installed.

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

The installer starts the companion and menu bar app at login and opens no external network ports. The panel is available at **http://127.0.0.1:47866/**. User settings and logs live under `~/Library/Application Support/AMG65 Studio/`; the app lives in `~/Applications/`.

For the dashboard and LED bridge without the native app or libusb:

```sh
./build.sh --dashboard-only
python3 install.py --dashboard-only
```

The full build downloads the pinned official Claude Code native binary for sign-in, verifies its size, SHA-256 and Apple signature, and installs it privately as `bin/claude-auth`. It invokes only `auth login --claudeai`, so legacy interactive agent startup and its MCP approvals are not part of sign-in. The vendor binary is not committed or redistributed in this repository. Building the full app needs internet access for that preparation; subsequent builds reuse the verified file.

Builds are signed ad hoc for local use and are **not notarized**. The build script verifies the bundle signature. This repository distributes source; it does not include a prebuilt release or a firmware flasher.

## Using the controls

Choose the interface language in the native app's sidebar, or in the standalone browser panel. The choice is saved locally and applies immediately, including number/date formats and remaining-time labels. The native picker also controls the embedded dashboard. Changing language does not interrupt USB streaming.

Click the Studio icon in the macOS menu bar to see Claude, Codex and Cursor together. The provider tabs show each independent quota window. The side rail opens Display, Lighting, Keys, LCD, LED, Device and Accounts; all controls work inside the panel. Display includes scrolling text, color, brightness and activity priority. The gear menu contains language and quit controls. **Open Studio** is an optional larger workspace. Closing it keeps the menu bar available. **Quit** exits the menu bar app until you open it again or log in next time. The independent bridge continues updating the keyboard. `--menu-bar` starts the native app without opening its main window.

The native app opens on **Overview**, where the embedded dashboard owns the USB connection. Opening a native device page in either window temporarily takes control. The live usage display resumes once neither visible surface needs native USB control; closing a panel during an upload waits for that operation to finish. The shared process lock also prevents a separate helper from writing simultaneously. A lease expires if the app stops renewing it.

The three large percentages represent the first available primary or weekly window for each provider; the exact window label is shown. These allowances cannot be added together. A missing measurement stays unknown. Data older than 15 minutes, or past its reset time, is marked as the last known value. On the hardware, `A`, `X` and `C` represent Claude, Codex and Cursor respectively; an amber marker indicates stale data.

**Refresh** requests direct provider measurements. A separate worker refreshes every five minutes, so network requests never delay keyboard output. The bundled helper reads only the original provider credential stores; tokens and account identities never enter the dashboard or usage cache. It does not rotate shared refresh tokens. For expired sessions, open **Accounts** in the menu bar and choose **Connect**. Studio starts the official Codex or Claude Code login flow; authorize in the provider browser screen and, if requested, paste its authorization code into the panel. Passwords are entered only on the provider website. Cursor opens its own app because its local desktop session is the quota source. Login processes are time-limited and can be cancelled; background refresh never initiates a login. Background Keychain reads never show prompts. Provider session endpoints can change; missing measurements remain unknown.

If an acknowledgment is lost, the application stops sending to that USB attachment. Reconnect the keyboard before retrying. Successful acknowledgments confirm protocol acceptance, not a readback of every persistent keyboard setting.

## Job activity

The LED strip uses provider colours and short ASCII states: `RUN`, `ASK`, `INPUT`, `DONE`, `ERROR`. Genuine approval/input requests preempt quota display; working states share time with the normal quota view. The three quota meters stay visible on the right. Activity can be disabled in Display settings.

Recent Codex desktop rollout metadata works without hooks. Passive Claude Code, Codex and Cursor hooks add documented lifecycle events where the installed host supports them. They observe events and never approve, deny or rewrite an action. Prompt text, commands and file paths are discarded. Unknown or expired events never become a guessed approval request. See [activity setup and compatibility](docs/ACTIVITY.md).

## Development and verification

```sh
python3 -m unittest discover -s tests -v
python3 NativeApp/Tests/run_checks.py
python3 UsageEngine/build.py --test
./build.sh
```

The Python tests cover cache privacy, malformed input, independent quota windows, stale timestamps, rendering, HTTP origin/host restrictions, settings validation and USB ownership transitions. Hardware testing is separate from unit tests.

On one connected AMG65, clock sync, live usage streaming, pause/resume and RGB application received USB acknowledgments; the user also confirmed the displayed usage text. See [the original source audit](docs/UPSTREAM_SECURITY_REVIEW.md) and [Studio security notes](docs/STUDIO_SECURITY.md) for scope, evidence and remaining limits. Bulk uploads, every key mapping, multiple physical keyboards and sleep/wake behavior need broader device testing.

## Stop or remove login startup

```sh
python3 install.py --remove-startup
```

This stops the menu bar app and background process and removes both LaunchAgents. The app and saved settings remain available. To run a preview without USB:

```sh
python3 app.py --no-device --state-dir /tmp/amg65-studio-preview
```

Stop the installed service first because both use the same local port.

## Code and third-party components

This is an independent application and is not an official LEOBOG, AULA or CodexBar release. Vendor skins, fonts, icons and sample media are not bundled. The standalone usage engine adapts MIT-licensed CodexBar provider logic; its pinned source and full notice are in [UsageEngine/NOTICE.md](UsageEngine/NOTICE.md). The protocol bridge includes material covered by the MIT notice in [THIRD_PARTY_LICENSE.txt](THIRD_PARTY_LICENSE.txt). The native build dynamically bundles libusb with its LGPL license and replacement notice. No broader license grant for Studio's own code is implied by those third-party notices.

## Türkçe

**AMG65 Studio**, klavyenin saatini Mac ile eşitler; Claude, Cursor ve Codex kalan kullanımını tek panelde ve klavyenin LED ekranında gösterir. RGB, tuş rengi/eşleme, LCD görseli ve LED animasyonu için yerel macOS arayüzü içerir.

Kurulum: `./build.sh`, ardından `python3 install.py`. Uygulama `~/Applications/AMG65 Studio.app`, panel `http://127.0.0.1:47866/` adresindedir. Menü çubuğundaki Studio simgesinden hesap girişi, ekran yazısı, parlaklık, RGB, tuşlar, LCD, LED ve cihaz ayarlarına ulaşılır; büyük pencere isteğe bağlıdır. CodexBar kurulumu gerekmez. Studio, sağlayıcıların kendi açık oturumlarından kullanım verisini doğrudan alır ve beş dakikada bir yeniler. İş durumu, onay/bilgi bekleme ve tamamlanma göstergeleri LED şeridinde öncelikli gösterilir. USB yanıtı kesilirse aktarım durur ve kablonun yeniden bağlanması gerekir.
