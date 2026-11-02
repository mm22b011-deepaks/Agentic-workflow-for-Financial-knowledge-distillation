# ADR 004: preserve evidence and budget truth

The quote similarity threshold remains 0.85. Evidence selection uses table labels and period columns before checking values; another row or period cannot supply a missing number. Signs, adjacent scales and table units are checked. Ambiguous rows remain reviewable rather than being accepted by scanning more windows.

Only llm_failed, truncated, document_error and empty_extraction invalidate a record. Summary review reasons do not withdraw unrelated fields. Other issues withdraw their affected fields, with guidance disagreements affecting guidance and EPS disagreement affecting EPS. A company can remain reported while a metric is unavailable.

Requests are the free-provider budget. Conservative defaults are 20/minute and 50/UTC day until account limits are verified. Reservations and cooldowns persist across worker processes. OpenRouter's larger free allowance depends on purchase history: see [provider limits](https://openrouter.ai/docs/api_reference/limits). No saved-call claim follows merely from reduced extraction tokens.

The historical 60 successful calls plus 42 truncations remain a failed one-call finding. The successful maximum completion size was 30,973 tokens; the configured reply budget is now 32,768 with the same ceiling. No post-change live success is claimed. Historical missing reasoning or latency measurements remain unknown.
