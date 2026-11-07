# Localization

AMG65 Studio supports Turkish (`tr`), English (`en`), Spanish (`es`), Simplified Chinese (`zh-Hans`) and Japanese (`ja`). The native app also offers **System language**. Existing installations keep Turkish unless the user changes the selection.

In **0.3.0**, usage comes from Studio's own UsageEngine and activity comes from real local host events. Neither translation nor data loading requires the CodexBar app, CLI, settings or cache. All translation resources are packaged locally; switching language does not contact a provider, refresh a credential or run a hardware command.

The native selection is stored in the `studioLanguage` user preference. System language resolves supported preferred languages in order, maps Chinese preferences to Simplified Chinese, and falls back to English. This changes interface text; the keyboard clock continues to use the Mac's time zone and a Gregorian calendar.

The embedded dashboard receives the selected native language through `#native&lang=code`. A supported fragment language takes precedence over the browser's saved `amg65-studio.language` value; the browser fallback is Turkish. Unsupported language identifiers are rejected rather than interpreted as resource paths. Browser storage failures do not prevent the page from rendering. Switching language preserves unsaved settings and pending requests and does not submit a USB operation.

## Updating translations

Native catalogs are flat JSON dictionaries under [`NativeApp/Sources/AMG65Studio/Resources/localizations`](../NativeApp/Sources/AMG65Studio/Resources/localizations). Their source tables are `NativeApp/Resources/localization_source.tsv` and `localization_technical.tsv`; regenerate JSON with `python3 NativeApp/Tools/build_localizations.py` after editing those tables. Keep the same keys in all five languages. Native templates use numbered placeholders such as `{0}` and `{1}`. Preserve every placeholder, including repeated occurrences, even when the target language reorders the sentence.

Use `L("source text")` for visible SwiftUI literals. Shared `Panel` and `ByteSlider` components translate their `title` internally. Stored status strings are translated when rendered, so previously displayed results also follow a language change. Add exact or template entries for new visible diagnostics. Template substitution must treat inserted arguments as plain text: a filename containing `{1}` or `$1` must remain unchanged.

The dashboard is self-contained. Its five dictionaries live in the `localization-catalog` JSON script in [`dashboard.html`](../dashboard.html). Static text, labels and placeholders retain their original keys; dynamic text uses `t(key, parameters)` with named placeholders such as `{time}`. Keep all dictionaries in step when adding a UI message. Display labels may use `Intl` formatting, but CSS widths, SVG colors and coordinates, input values and API payloads must keep their original numeric representation.

Product names, physical key legends, modifier symbols, filenames and user-entered text are intentionally preserved. The hardware's small LED font remains limited to its supported Latin characters and punctuation; selecting Chinese or Japanese does not add those glyphs to the keyboard. Unknown operating-system or transport diagnostics may retain their original language; the common application status messages are translated.

## Usage and activity terminology

Treat provider error codes and activity state/summary codes as protocol values. Translate them at the presentation boundary; do not persist translated sentences as state or branch on their displayed text. Known device/operation codes must use translated accessible labels and tooltips as well as visible text. Raw unknown diagnostics may remain in a detail tooltip, with a translated general failure message in the main interface.

Quota labels distinguish five-hour, weekly, monthly and provider-specific windows. `Fable only` and similar labels keep the model's proper name while localizing “only.” Preserve independent window identities: translating them must not combine, average or silently relabel limits. A missing or invalid percentage is unknown (`--`), not zero; a reported zero remaining is a valid exhausted allowance. Last-known usage retains its original measurement time and stale styling. The opaque account fingerprint belongs only to the private cache and must not appear in translated output, accessibility text or diagnostic tooltips.

Activity states are queued, running, waiting for approval, waiting for input, completed, error and unknown. Summary codes such as reading files, editing files and running a command use fixed catalog text; no prompt, command, filename or generated explanation is inserted. Missing or expired evidence maps to unknown, never to idle/success. Current TTLs are 30 seconds for queued, 120 for running, 300 for approval/input waits, 45 for completed and 90 for error. Client copy must not imply continuous tracking when the local connection is unavailable.

Host capability limits also need faithful wording: Codex 0.166 uses verified stable hooks; Claude Code 2.0.35 uses its verified safe subset without `PermissionRequest` or typed approval notifications; the passive Cursor integration does not supply a reliable approval-wait event. Unknown is an intentional state for unsupported or absent signals, not a translation defect. Do not infer approval from elapsed time or a running process.

The physical 63 × 5 display uses fixed ASCII activity codes `QUEUE`, `RUN`, `ASK`, `INPUT`, `DONE` and `ERROR` in every interface language. They are protocol/display abbreviations, while the web/native explanations are localized. Language selection must preserve all drafts, submitted operation state, activity timestamps and expiry behavior. Localized numbers belong in labels only; JSON percentages, SVG coordinates, CSS meter widths and form payload values must remain locale-independent.

## Verification

Run from the repository root:

```sh
python3 -B -m unittest discover -s tests -p test_localization.py -v
python3 NativeApp/Tests/run_checks.py
```

The Python suite checks duplicate keys, language/key parity, placeholder preservation, explicit native lookups, visible SwiftUI literals, stored diagnostics, HTML/accessibility text and dynamic web lookups. Two additional behavioral checks run the production JavaScript helpers in Node with a small fake DOM. They test fragment validation and precedence, language persistence, unavailable storage, draft/pending-state preservation, unknown versus zero quota values, and numeric rendering across all five languages. They make no network requests or USB calls. If Node is unavailable, those two checks are reported as skipped; the catalog checks still run.

These automated checks do not certify translation fluency or catch every dynamically constructed label. Review changed copy in context and check the actual native and embedded layouts for clipping, focus behavior and readable font fallback. Native runtime tests separately cover catalog lookup, locale resolution and template formatting without opening hardware.

For the independent data paths, also run `python3 -B -m unittest discover -s tests -v` and `python3 UsageEngine/build.py --test`. In the 7 November 2026 development session, 105 Python tests, 78 native checks and 122 UsageEngine checks were observed passing. These are intermediate observations, not a guarantee for later edits or a translation certification; rerun on the final revision. Engine fixtures use synthetic credentials and mocked HTTP, without reading real Keychain secrets, contacting providers or accessing USB. Native `LAContext` verification can require a normal macOS process environment rather than a service-restricted sandbox.
