# ADR 009: private interactive initialization

The current task explicitly authorizes an idempotent init wizard to read/write .env inside the setup process, preserving unrelated lines with an atomic mode-600 replacement. A tracked .env is refused before credential initialization. The key has no command-line argument. Non-TTY mode never prompts; --no-key disables model requests without deleting the stored credential. Exported values remain authoritative. Shadowing is reported using length/sha8 only, with the explicit unset command; the wizard never silently changes the parent shell.

setup.sh uses a dedicated child launcher to load dotenv without overriding exports. Direct Python library/CLI callers remain environment-driven. configs/local.yaml is ignored and layered over config.yaml; explicit --set wins. TRESATA_IGNORE_LOCAL_CONFIG=1 disables operator-local layers for hermetic checks; the wizard explicitly selects its own layer. The tracked base YAML is unchanged by init.

A matching bootstrap stamp allows repeat initialization after bootstrap without reinstalling or making package-manager network requests. Missing/stale installations delegate to the existing pinned bootstrap. Source archive production still uses scripts/package.sh only.

Provider verification first reads the documented GET /api/v1/key endpoint. Only allowlisted numeric account usage, authentication/status and verification flags are retained; provider bodies/key labels are never logged or written. A valid real response verified this endpoint. A fallback tiny :free completion reserves its single request first; 401/403 stops verification and selects offline mode. The public model catalog is checked for zero pricing where supplied. No model batch is started. Provider error bodies are no longer included in exceptions, and echoed credentials in successful completions are rejected before persistence.

The live environment key was rejected with 401; its metadata differed from the stored key. A separate explicitly environment-unset child verified the stored key with HTTP 200 and zero model requests. The account reported a daily ceiling of 1000; the configured limit remains 50. Per-minute allowance remains UNSURE. No cap was raised and no rotation was requested.

Reference: [OpenRouter limits and current-key endpoint](https://openrouter.ai/docs/api_reference/limits). Bootstrap may use network; cached/stamped reinitialization and offline checks do not require it. Timer installation remains an explicit, separate approval.
