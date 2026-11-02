# 010 — Quota-aware workstation scheduling

Accepted 2026-11-02.

Reuse jobs, events, the pipeline writer lock and SQLite request reservations. Migration 0003 adds task/dependency metadata and durable request receipts, rather than a second execution queue. Day 0 performs SEC/offline work. Model work requires explicit human confirmation. Human labelling and NDA tasks do not block unrelated automation. XBRL stays planned.

The usable model allocation is floor(daily cap × (1 − safety margin)) minus retry reserve. Reservations are shared across processes and UTC days. Cache hits require no reservation; authentication rejection releases its reservation. Every actual attempt retains ledger instrumentation. A first 429 ends the current batch conservatively, retaining both Retry-After cooldown and the next-day boundary, rather than repeatedly probing the provider. Configured limits remain unverified account limits; an authenticated account response does not raise them.

Successful responses are durably receipted before extraction artifacts. Replaying a completed receipt costs no new call. A crash after a request might have reached the provider but before its receipt is written is inherently ambiguous: block it for attention instead of issuing a potentially duplicate call. This is deliberately conservative and is not an exactly-once guarantee from the external provider.

A user systemd timer is preferred, with Persistent=true and an explicit UTC calendar. Crontab fallback uses a marked block and the same command's UTC eligibility check, preserving unrelated entries. Installation requires approval of the exact proposed files. Tests generate/install only temporary mocked units; no real timer or cron change is part of verification.

Canonical argparse definitions also supply Typer dispatch and worker argv validation. Server-side paths and credential environment names cannot be overridden by a browser job. Changing quota allocation during resume is permitted; changing semantic parameters or configuration requires a new run.
