# Security boundary

## Never export or commit

OAuth access/refresh tokens, broker profiles, private keys, native Sites bearer tokens, Gmail sessions, model API keys and environment secrets are intentionally not recovered. Migration does not move the existing broker grant into Git. An absent local profile is not evidence the grant expired.

The private state ZIP contains real rules, account test samples, execution history and research evidence. **It is not encrypted by this export.** Keep it on an encrypted disk and never commit/upload it to a repository. Its user-owned saved copy is for download; sharing its access is separate from Git access. To make a transport-encrypted copy locally, use a tool such as `age -p -o niulai-private.zip.age niulai-private.zip`, entering the passphrase interactively and storing it separately. Do not pass passwords as command arguments.

## Local credentials

- Use the OS keychain or an external secret manager for long-lived service keys.
- The existing Tiger SDK uses a file-based profile. Keep it outside the checkout under a directory mode0700 and files0600, on an encrypted disk; preserve its single-owner refresh lock. Do not put a profile in cloud-sync/Git/fixtures.
- Use read-only broker scope. Do not broaden permissions while migrating.
- Keep OAuth consent interactive. The current wrapper's native ChatGPT service token is not a portable credential; do not scrape or embed it. Choose a supported local OAuth flow and validate rotation/persistence before scheduling.
- Use environment variables only to pass necessary runtime settings, not to create committed credential files. Never print process environment or raw authorization responses.
- A native-service error is not automatically a broker-grant error. Only an official grant-expired/revoked/refresh-rejected result should trigger consent.

## Repository hygiene

The root `.gitignore` blocks runtime databases, common credential files, profiles and result archives. It does not remove files already tracked. Before the first push, inspect `git diff --cached --name-only` and run the bounded scanner on the actual staged export. If a real secret ever reached a commit, revoke/rotate it; removing the file later is insufficient.

The scanner reports paths and finding types, never secret values. It includes negative/positive controls but is not a guarantee against every secret format. Use private GitHub visibility unless you separately review all strategy/integration metadata for publication.
