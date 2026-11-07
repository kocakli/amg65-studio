# Activity on the AMG65 strip

Studio observes local agent lifecycle events and shows a short action label beside the provider color. It does not read task descriptions into the interface. Percentage quotas remain independent of activity. `unknown` means there is no fresh supported observation; it does not mean idle, available, or finished.

Version 0.3 obtains quotas through its own UsageEngine; CodexBar is not required. Activity has a separate source and freshness clock. Signing in, refreshing quota or opening a menu section must not synthesize a running/completed event.

## Menu controls and sign-in

The native menu contains Usage, Display, Lighting, Key assignments, LCD, LED animation, Device settings and Accounts. Hardware sections coordinate the same USB ownership lease as the main window; opening Accounts does not take USB control. Display can enable/disable activity overlays without changing quota collection. The quota/status client reads the local bridge every 15 seconds while the menu is visible; the Accounts section polls its separate local status every two seconds. These reads are not provider network polling intervals.

Accounts offers explicit user-initiated official CLI/app sign-in. It neither creates agent activity events nor accepts permission requests on an agent's behalf. Claude first-run setup/trust prompts remain user decisions. A recognized trust prompt for Studio’s private login directory has a separate explicit confirmation button; it does not approve agent tool requests or change a project’s permission policy. Unsupported onboarding is completed in the provider’s own application instead of receiving a guessed answer. Cursor opens its own application because a browser-only session would not update the local credential store used for quota. Closing the menu for browser sign-in does not cancel that login; Cancel is a separate action. No password/API-key field is provided. A requested one-time authorization code belongs to the sign-in flow, never to activity metadata.

## Integration API

```python
from activity import ActivityCollector
activity = ActivityCollector(state_dir, codex_home=None)
snapshot = activity.snapshot()
```

The result contains `updated_at`, three `providers` rows, and `selected` (a row or `None`). A row has `provider`, `state`, `summary`, epoch-second `observed_at` / `expires_at`, `source`, opaque `session_id`, `active_count`, and `stale`. The public session value is a 20-character SHA-256 prefix, never the original chat ID. Selection prioritizes approval, input, error, running, queued, completed. The renderer can rotate equally urgent providers. It must use unknown/stale as missing information, not a green success.

| State | Lifetime after the last qualifying event |
| --- | ---: |
| queued | 30 seconds |
| running | 120 seconds |
| waiting_approval | 300 seconds |
| waiting_input | 300 seconds |
| completed | 45 seconds |
| error | 90 seconds |

These are freshness limits, not estimates of task duration. A quiet long operation can become unknown. A permission event records a request; another policy hook may immediately resolve it. With no subsequent event, Studio cannot prove that a dialog is still open. Tool failures describe a tool attempt and can be followed by recovery. Interruption/session close becomes unknown rather than successful completion.

The `summary` localization keys are: `unknown`, `prompt_submitted`, `working`, `using_tool`, `running_command`, `reading_files`, `editing_files`, `searching`, `approval_requested`, `input_requested`, `input_received`, `completed`, `tool_failed`, `failed`, `interrupted`, `session_ended`, `compacting`.

## Verified event sources

**Codex:** recent local rollout metadata supplies `task_started`, `task_complete` and tool lifecycle records without configuration. The transcript format is not a stable API, so unrecognized records are ignored. Current official hooks supply `PermissionRequest`, model/tool events, `Stop`, and interruption. Explicit `request_user_input` tools supply an input request. Hook definitions require review in the host; Studio never changes trust records. [Official Codex hooks](https://learn.chatgpt.com/docs/hooks)

**Claude Code:** supported current hosts expose permission/input hooks and typed notifications. `idle_prompt` means the reply finished earlier, so Studio deliberately ignores it. `agent_completed` does not distinguish success from failure and is also ignored. An explicit `AskUserQuestion` tool can indicate input. [Official Claude Code hooks](https://code.claude.com/docs/en/hooks)

**Cursor:** passive post-tool, response, compaction, stop, and session-end hooks provide activity. A response message alone is not completion; only `stop.status` supplies that result. The verified public contract lacks a pending-approval observation. Studio installs no Cursor permission hooks and returns no permission decisions. [Official Cursor hooks](https://cursor.com/docs/hooks)

Local verification on 2026-11-07:

| Host | Verified capabilities / limitation |
| --- | --- |
| Bundled Codex `0.166.0-alpha.6` | Executable under `ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`; `features list` reports `hooks stable true`. Its generated `HookEventName` schema includes all configured events below. |
| Global Codex CLI `0.42.0` | Older than the verified desktop hook host; no assumption of lifecycle-hook support. No CLI upgrade performed. |
| Claude Code native binary `2.0.35` | Actual embedded hook enum: `PreToolUse`, `PostToolUse`, `Notification`, `UserPromptSubmit`, `SessionStart`, `SessionEnd`, `Stop`, `SubagentStop`, `PreCompact`. No `PermissionRequest` hook or typed `notification_type`; approval waiting unavailable. Global `claude` launcher points at a missing legacy install. |
| Cursor `3.27.6` | Current documented passive hook contract; approval waiting unavailable. New hooks affect subsequent host events, not historical conversations. |

Configured desktop Codex set: `UserPromptSubmit`, `PreModelRequest`, `PostModelRequest`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `Stop`, `Interrupt`, `SessionEnd`.

Configured legacy Claude set: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `Stop`, `SessionEnd`. The newer normalizer also supports `PermissionRequest`, `PostToolUseFailure`, `Notification`, `Elicitation`, `ElicitationResult`, `StopFailure`, but these must not be installed without verifying that host's capabilities.

Configured Cursor set: `postToolUse`, `postToolUseFailure`, `afterAgentResponse`, `preCompact`, `stop`, `sessionEnd`.

## Safe additive configuration

The pure `activity_hooks.build_hook_config(...)` function requires an explicit `supported_events` set and returns a copy with only supported observer entries appended. It never writes settings. User locations are `~/.codex/hooks.json`, `~/.claude/settings.json`, and `~/.cursor/hooks.json`. Existing hooks, settings, and permission policies are preserved. No feature flags are changed. Removing the integration with `remove_hook_config(...)` removes only exact matching entries it created.

The installer should back up each existing regular owner-owned configuration at mode `0600`, then atomically replace it with the merged configuration. Refuse symlinks, malformed JSON, unknown Cursor config versions, and concurrent modification. Use absolute interpreter/script/state paths and a two-second host timeout. Review new Codex hooks through the host's normal Review Hooks flow; do not modify its trust database. Existing sessions may need a fresh turn/session before loading changes.

Hook commands run `activity_hooks.py receive --provider NAME --state-dir PATH`, accept bounded JSON on stdin, and always emit `{}` with exit status 0. They cannot approve, deny, answer, continue, rewrite inputs, inject prompts, or send network requests. The legacy Claude source is not repaired or upgraded by this integration.

## Privacy and limits

Only allowlisted labels, event names, hashed session/turn/tool identities, timestamps and state are retained. Prompts, reasoning, answers, commands, paths, email, credentials, tool arguments/results and model-generated summaries are discarded. Unknown tool names become `using_tool`. Reading a JSON event transiently parses its bounded payload; no raw payload is logged or sent to another service.

The current-state journal is `state/activity.json`, mode `0600`, in an owner-only `0700` directory. Writes use a bounded process lock and atomic replacement; at most 64 records are retained, with a ten-minute merge horizon. Expired records are ignored by the collector; the last private file is not automatically deleted while Studio is stopped. Hook stdin is limited to 256 KiB and 0.5 seconds. Log reads scan only today's/yesterday's directories, at most 2,048 entries per directory, eight recently modified files, 256 KiB and 2,048 records per file per poll. Polls are spaced at least two seconds apart. Oversized/partial/unrecognized records are skipped, not treated as activity.

No recursive transcript/history search, process polling, accessibility monitoring, credential access, telemetry or network requests are used. Concurrent sessions remain separate. Subagent lifecycle hooks do not mark the parent complete; hosts that share identifiers without an origin discriminator can still have ambiguous concurrency. Timestamps, TTL and source make the observation limits explicit.

Run offline tests without credentials, network, or USB:

```sh
python3 -m unittest discover -s tests -p test_activity.py -v
```
