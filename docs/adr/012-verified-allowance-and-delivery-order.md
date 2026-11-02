# 012 — Verified account allowance and execution order

Accepted 2026-11-02.

The authenticated OpenRouter key endpoint returned HTTP 200, daily limit 1,000, used 0 and remaining 1,000. Model pricing was verified zero. These checks made no model request. The human explicitly set 1,000/day; only the ignored local overlay changed. The default tracked configuration remains the conservative 50/day. The 40 × 4 frozen panel and 20/minute setting are unchanged. The scheduler usable allocation is now 895/day, with a one-model-day scope estimate. Published per-minute policy is checked in OpenRouter documentation; it is not an account-specific endpoint measurement.

The human approved the user timer and free-model batches. The timer is active at 00:10 UTC, Persistent=true. A temporary models_hold state preserves approval while preventing automatic execution before CLI and website acceptance. The final requested order is CLI implementation/review/checks, then website completion/checks, then a real extraction batch and outcome review. The explicit start-models flag can advance the approved model day after Day 0 without bypassing dependency, hold or quota checks. No fresh confirmation is needed.

Provider reference: https://openrouter.ai/pricing and https://openrouter.ai/docs/api_reference/limits. Account evidence: evidence/account-quota.json.

The acceptance hold was released after the CLI and website gates passed. Twenty actual free-model bakeoff requests completed, ten documents per model. Both models parsed all ten responses; each had nine usable core records. Lightning was selected because measured aggregate field coverage ranked before token/latency cost; its median request latency was 246.68s versus 45.99s for Nano Omni. Both produced reasoning tokens, so neither establishes a non-reasoning option. No human accuracy ranking is asserted.

The controller was transferred to the already-approved user service while preserving the same independent worker/job and unchanged reservations. The service now runs the primary extraction independently of the chat or API process, with unlimited service startup timeout. The existing timer remains enabled; no second queue or unattended installation was introduced. Aggregate/export/quality/report and private label preparation follow automatically. Human tasks remain nonblocking.
