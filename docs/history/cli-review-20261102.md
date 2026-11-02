# CLI and scheduler review — 2026-11-02

Reviewed canonical argparse/Typer dispatch, standalone phase services, worker/job paths, source and artifact handling, shared quota reservations, durable receipts, scheduler dependency/calendar logic, wizard secret handling, free-only configuration, KPI export and packaging boundaries.

Resolved findings:

- Serve passed an argparse string to the path-only app factory. Normalize at the shared boundary; the browser process exercises the actual entry point.
- Run all previously collapsed progress to one job stage. It now uses the same canonical stage list as direct CLI execution, with per-stage artifact snapshots and filtered command flags.
- A selected bakeoff model override was appended before the parameter list existed. Build the parameter list first.
- Old submission JSON compared unequal when new optional fields were absent. Compare validated request values.
- A resumed cache-only bakeoff could lack a ledger file. Treat it as zero actual attempts, retaining unmeasured latency/token breakdowns.
- WorkingDirectory quotes are not removed by systemd. Native unit verification found and corrected this; the actual timer is enabled and active.
- An inspector command could bypass upstream checking. Validate server-owned hashes both at submission and again under the worker lock.
- Model IDs supplied through the bakeoff flag need their own free-only check before any reservation. The real command regression rejects paid IDs before the provider path.
- A skipped-key setup unnecessarily created an empty dotenv file. Keep it absent when there is nothing to persist.
- CLI registry parity caught stale generated output after the new start-models flag. Regenerate from the canonical parser.

Exact-value secret scanning covers the candidate tree and this session's commit range. Key material is never included in review evidence. Provider account GET verification is separately recorded as HTTP 200, 1,000/day, used 0, remaining 1,000; the human selected the local 1,000/day cap. Model pricing was verified zero without a completion request.

The timer is installed by explicit approval. Approval of model work is retained, with a temporary acceptance hold until CLI and website checks pass. Final code/check evidence belongs in HANDOVER.md; this review does not assert that the still-unfinished website has passed browser acceptance.

Final delivery review also resolved stale-scope human-label sheets, partial bakeoff score loss, absent per-attempt telemetry, public nested bakeoff identifiers, stale job polling, replay/provenance controls and graph import round trips. The final offline gate passed 454 tests in 175.17s, coverage 84.95%, Ruff/format 136 files and mypy 71 source files. Website checks now passed incrementally across the requested four browser configurations; see docs/verification.md. The acceptance hold was released, bakeoff completed and primary extraction is running under the approved user service. R0 and human quality gates remain open.
