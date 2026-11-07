# Security

AMG65 Studio is a local, user-space macOS application. Its HTTP companion binds to `127.0.0.1`; its native helper only opens the AMG65 vendor HID interface. It does not read ordinary key input or microphone audio. Normal usage updates read CodexBar's local cache.

The loopback API rejects unexpected Host and Origin values, accepts bounded JSON requests, and has no cross-origin access policy. It is **not an authentication boundary against other local processes or users**. Do not expose this port through a proxy or tunnel.

USB operations are serialized and use a shared per-user process lock. Lost or invalid acknowledgments stop the current connection; a new USB attachment is needed before retrying. The application never flashes firmware. Device settings and media uploads can still change the keyboard's stored configuration; a successful ACK is not complete readback verification.

See [Studio security notes](docs/STUDIO_SECURITY.md) and [the reference-source review](docs/UPSTREAM_SECURITY_REVIEW.md) for testing scope and known limits. Source review, regression tests and ad-hoc signing are not a malware certification or Apple notarization.

Please use GitHub's private vulnerability reporting for security reports when available. Include the commit, macOS version, USB connection mode and a minimal reproduction without account credentials or private usage-cache files. General reproducible bugs may be filed as ordinary issues.
