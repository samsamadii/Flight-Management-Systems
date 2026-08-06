# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately before discussing them in a public issue.

**Security contact:** `[ADD A PRIVATE SECURITY-CONTACT EMAIL BEFORE PUBLICATION]`

The maintainer must replace that placeholder with a monitored security-contact address before publishing the repository. Until a private contact is configured, do not disclose exploit details, credentials, API keys, personal data, or other sensitive information in a public GitHub issue.

Include a concise description, affected version or commit, reproduction steps, impact, and any suggested mitigation. Remove or redact local paths, profile data, route history, callsigns, tokens, screenshots containing private data, and unrelated logs.

## Supported versions

Only the latest published source revision is intended to receive security fixes. Older snapshots, local builds, packaged executables, and modified copies are unsupported. Support is best-effort and does not imply a warranty or a service-level commitment.

## Secrets and local data

- Store `MAPTILER_API_KEY` and `INFINITE_FLIGHT_API_KEY` in the process environment when possible.
- Never commit `.env`, `infinite_flight_config.json`, credentials, tokens, private keys, profile data, calendar records, exports, or logs.
- Be aware that the in-app Infinite Flight key save action writes the key in plaintext to `infinite_flight_config.json`.
- Restrict access to the machine and local application-data directory. The application does not encrypt its JSON files.
- Treat screenshots, exported JSON, profile-image paths, flight history, callsigns, and diagnostic output as potentially sensitive.

If a key is exposed, immediately revoke or deactivate it with the issuing provider, create a replacement, update the local environment or configuration, and review provider logs if available. Deleting the key from the latest file or commit is not sufficient because it may remain in Git history, forks, caches, logs, or downloads.

## Demo login is not authentication

The existing login screen is a visual demonstration, not a security boundary. Any non-empty username and password are accepted. There is no identity verification, password database, authorization layer, or access control. The public variant bypasses the login UI entirely.

## Aviation safety

This software must not be used to make operational aviation decisions. It is not certified, approved, or validated for real-world flight planning, navigation, aircraft performance calculations, dispatch, or flight operations. Do not report simulation-output inaccuracies as though the application were an approved aviation system.

