# Independent usage engine

This engine adapts selected provider authentication formats, endpoint contracts,
and quota parsing from [CodexBar](https://github.com/steipete/CodexBar), pinned at
`53f9e1e24d28b0d7f451449b4a25d0e076ea5bc9`. It does not require the CodexBar app,
CLI, preferences, credentials cache, or shared usage cache at runtime.

Source references under `Sources/CodexBarCore/`:

- `Providers/Codex/CodexOAuth/CodexOAuthCredentials.swift`
- `Providers/Codex/CodexOAuth/CodexOAuthUsageFetcher.swift`
- `Providers/Claude/ClaudeOAuth/ClaudeOAuthCredentialModels.swift`
- `Providers/Claude/ClaudeOAuth/ClaudeOAuthUsageFetcher.swift`
- `Providers/Claude/ClaudeConfigPaths.swift`
- `Providers/Claude/ClaudeWeb/ClaudeWebExtraRateWindowParser.swift`
- `Providers/Cursor/CursorAppAuth.swift`
- `Providers/Cursor/CursorStatusProbe.swift`
- `Providers/Cursor/CursorStatusProbe+UsageSummary.swift`
- `Providers/Cursor/CursorSandUsage.swift`
- `ChromiumSafeStorage.swift` and `KeychainNoUIQuery.swift`

Adaptations: macOS SDK-only executable, three providers, bounded no-redirect HTTP,
noninteractive Keychain reads, no credential refresh/persistence, no browser-cookie
import, and no account identifiers in display data. Missing usage remains unknown;
it is not converted to zero usage. An opaque SHA-256 account discriminator is sent
only to the parent bridge's private cache; the bridge must remove it from HTTP/UI
responses. Claude's token fingerprint is deliberately invalidated on rotation when
its local credential does not identify an organization.

These are provider session endpoints, not a guaranteed public API contract. An
expired provider-owned session must be renewed by signing in to Codex, Claude Code,
or Cursor. The engine never rotates shared refresh tokens or modifies their stores.
Blocked Keychain access returns a fixed error without prompting. Interactive access
is a separate `--authorize-keychain claude` mode that only the native application's
explicit **Allow Keychain Access** action starts; it prints an outcome, never the secret.

A valid Claude profile file takes precedence. When the default profile file is
missing, invalid, or expired, the engine can reuse a valid Claude Code Keychain
record without prompting; custom profiles cannot borrow that default record.
Explicit credential-directory overrides must be absolute paths. Unsupported
relative overrides fail instead of silently selecting the default account.

Build: `python3 UsageEngine/build.py`. Offline production-parser checks:
`python3 UsageEngine/build.py --test`. These checks do not read real credentials,
contact providers, or access USB. Run `bin/amg65-usage --provider all` only for an
authorized live refresh; its stdout is the normalized JSON protocol.

## CodexBar license

MIT License

Copyright (c) 2026 Peter Steinberger

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
