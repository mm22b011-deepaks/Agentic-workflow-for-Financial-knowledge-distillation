import type { CanvasNode } from "../../CanvasRegistry";
import type { PaneResponse } from "../../PaneResponse";
import { Icon } from "../../shared/Icon";
type Row = PaneResponse["rows"][number];
const titles: Record<string, string> = {
  joined: "Joined by year",
  membership: "Still in / left",
  mapping: "Identifier mapping",
  equation: "Release plan",
  selection: "Frozen selection",
  quarters: "By quarter",
  found: "Found / missing",
  sizes: "File sizes",
  skipped: "Skipped by reason",
  lengths: "Text lengths",
  truncated: "Truncated",
  presence: "Present / not stated / flagged",
  checks: "Pass / fail",
  completion: "Action result",
  "model-scores": "Model quality",
  reasons: "Review reasons",
  duplicates: "Duplicates removed",
  heatmap: "KPI × quarter",
  thresholds: "Coverage gate",
  funnel: "Step total",
};
const candidates: Record<string, string[]> = {
  joined: ["effective_from", "joined", "start_date"],
  membership: ["effective_to", "left", "end_date"],
  mapping: ["mapped"],
  quarters: ["season", "season_quarter"],
  found: ["outcome"],
  sizes: ["size_bytes", "bytes"],
  skipped: ["outcome"],
  lengths: ["chars", "chars_sent"],
  truncated: ["truncated"],
  reasons: ["reason"],
};
export function IOSummary({
  node,
  rows,
  total,
  countText,
  before,
}: {
  node: CanvasNode;
  rows: Row[];
  total: number;
  countText: string;
  before?: number;
}) {
  const human = (key: string) =>
    node.io.example_fields.find((f) => f.key === key)?.label ?? "Value";
  function bars(kind: string) {
    const key = candidates[kind]?.find((k) => rows.some((r) => k in r));
    if (!key)
      return (
        <p className="io-empty">
          {total ? "Breakdown not saved" : "Not run yet"}
        </p>
      );
    const counts = new Map<string, number>();
    for (const row of rows) {
      const v = row[key];
      let text = v == null ? "Not stated" : String(v).replaceAll("_", " ");
      if (kind === "joined")
        text = v ? String(v).slice(0, 4) : "Date not saved";
      if (kind === "membership") text = v ? "Left" : "Still in";
      if (kind === "mapping") text = v ? "Mapped" : "Unmapped";
      if (kind === "truncated") text = v ? "Shortened" : "Full length";
      if (kind === "sizes")
        text =
          v == null
            ? "Size not saved"
            : Number(v) < 10000
              ? "Under 10 KB"
              : Number(v) < 50000
                ? "10–50 KB"
                : "Over 50 KB";
      if (kind === "lengths")
        text =
          v == null
            ? "Length not saved"
            : Number(v) < 5000
              ? "Under 5,000 characters"
              : Number(v) < 20000
                ? "5,000–20,000 characters"
                : "Over 20,000 characters";
      counts.set(text, (counts.get(text) ?? 0) + 1);
    }
    return [...counts]
      .sort((a, b) =>
        kind === "reasons" ? b[1] - a[1] : a[0].localeCompare(b[0]),
      )
      .slice(0, 5)
      .map(([name, n]) => (
        <div className="io-bar" key={name}>
          <span>{name}</span>
          <meter min={0} max={rows.length} value={n} aria-label={name} />
          <small>{`${n} ${node.io.gives.unit_label}${n === 1 ? "" : "s"}`}</small>
        </div>
      ));
  }
  function split(keys: string[], checks = false) {
    return keys
      .filter((k) => rows.some((r) => k in r))
      .map((key) => {
        const present = rows.filter(
          (r) => r[key] != null && (checks ? Boolean(r[key]) : !r.flagged),
        ).length;
        const flagged = rows.filter((r) =>
          checks
            ? r[key] === false || r[key] === 0
            : r[key] != null && r.flagged,
        ).length;
        const absent = rows.length - present - flagged;
        return (
          <div className="io-split" key={key}>
            <span>{human(key)}</span>
            <div
              role="img"
              aria-label={`${present} ${checks ? "passed checks" : "present records"}, ${absent} not stated records, ${flagged} ${checks ? "failed checks" : "flagged records"}`}
            >
              <i style={{ width: `${(100 * present) / rows.length}%` }} />
              <i style={{ width: `${(100 * absent) / rows.length}%` }} />
              <i style={{ width: `${(100 * flagged) / rows.length}%` }} />
            </div>
            <small>{`${present} ${checks ? "passed checks" : "present records"} · ${absent} not stated records · ${flagged} ${checks ? "failed checks" : "flagged records"}`}</small>
          </div>
        );
      });
  }
  const percent = (v: Row[string]) =>
    v == null ? "Not saved" : `${Math.round(Number(v) * 100)}%`;
  const failed = rows.some((row) => row.status === "failed");
  const metricValue = (r: Row) =>
    r.metric_value == null
      ? "Not stated"
      : `${r.metric_unit === "fraction" ? (Number(r.metric_value) * 100).toFixed(1) : r.metric_value}${r.metric_unit === "score" ? " score" : "%"}`;
  return (
    <div className="io-summary" data-testid="summary-tile">
      <div className="summary-total">{countText}</div>
      {node.io.summaries.slice(0, 3).map((kind) => (
        <article className="io-tile" key={kind}>
          <strong>{titles[kind] ?? "Step summary"}</strong>
          {kind === "completion" ? (
            <div className="io-empty">
              <Icon name={failed ? "cross" : rows.length ? "check" : "clock"} />
              {failed ? "Failed" : rows.length ? "Completed" : "Not run yet"}
            </div>
          ) : kind === "model-scores" ? (
            <>
              {rows.map((row, index) => (
                <div className="io-equation" key={index}>
                  <span>{row.model ?? "Model"}</span>
                  <progress aria-label={"Parsed releases"} max={1} value={Number(row.parse_success_rate ?? 0)} />
                  <span>{`${percent(row.parse_success_rate)} parsed`}</span>
                  <span>{`${row.latency_p95_seconds ?? "Unknown"} seconds · slow response`}</span>
                </div>
              ))}
              {!rows.length && <p className="io-empty">{"Scores not saved"}</p>}
            </>
          ) : kind === "equation" || kind === "selection" ? (
            <div className="io-equation">
              {(kind === "selection" ? ["companies", "seasons", "company_quarters"] : [
                "companies",
                "seasons",
                "releases",
                "base_requests",
                "model_days",
              ])
                .filter((k) => rows[0]?.[k] != null)
                .map((key, i) => (
                  <span key={key}>
                    {i > 0 ? (
                      <b aria-hidden="true">
                        {i === 1 ? "×" : i === 2 ? "=" : "→"}
                      </b>
                    ) : null}
                    {`${rows[0][key]} ${key === "companies" ? "members" : key === "seasons" ? "quarters" : key === "company_quarters" ? "company-quarters" : key === "releases" ? "releases" : key === "base_requests" ? "requests" : "days"}`}
                  </span>
                ))}
              {!rows.length && <p className="io-empty">{"Plan not saved"}</p>}
            </div>
          ) : kind === "presence" ? (
            <>
              {split(["reported_eps", "revenue", "guidance_presence", "tone"])}
              {!rows.some((r) => "reported_eps" in r) && (
                <p className="io-empty">{"Field results not saved"}</p>
              )}
            </>
          ) : kind === "checks" ? (
            <>
              {split(
                [
                  "quote_check",
                  "number_check",
                  "scale_check",
                  "row_check",
                  "period_check",
                ],
                true,
              )}
              {!rows.some((r) => "quote_check" in r) && (
                <p className="io-empty">
                  <Icon name="check" size={15} />
                  {node.id === "validate-config"
                    ? `${rows.length} settings available`
                    : "Check results not saved"}
                </p>
              )}
            </>
          ) : kind === "duplicates" ? (
            <div className="io-equation">
              {before != null && before >= total && <span>{`${before} records before`}</span>}
              <span>{`${total} records after`}</span>
              <span>
                {before == null || before < total
                  ? "Before count not saved"
                  : `${Math.max(0, before - total)} duplicates removed`}
              </span>
            </div>
          ) : kind === "funnel" ? (
            <div className="io-equation">
              <span>{countText}</span>
            </div>
          ) : kind === "heatmap" ? (
            <div className="io-heatmap">
              {rows.map((r, i) => (
                <div key={i}>
                  <strong>{r.metric ?? "KPI"}</strong>
                  <span>{r.season}</span>
                  <b>{metricValue(r)}</b>
                  <small>{`${r.n_reported ?? "Unknown"} records · ${percent(r.coverage)} coverage`}</small>
                </div>
              ))}
            </div>
          ) : kind === "thresholds" ? (
            <div className="io-rings">
              {rows.slice(0, 4).map((r, i) => (
                <div key={i}>
                  <svg role="img" aria-label={"Coverage"} viewBox="0 0 40 40">
                    <circle
                      cx="20"
                      cy="20"
                      r="16"
                      fill="none"
                      stroke="var(--line)"
                      strokeWidth="4"
                    />
                    <circle
                      cx="20"
                      cy="20"
                      r="16"
                      pathLength="100"
                      fill="none"
                      stroke={
                        r.pass === true || r.pass === 1
                          ? "var(--accent)"
                          : "var(--red)"
                      }
                      strokeWidth="4"
                      strokeDasharray={`${Math.max(0, Math.min(100, Number(r.coverage ?? 0) * 100))} 100`}
                    />
                    <text
                      x="20"
                      y="22"
                      textAnchor="middle"
                      fontSize="8"
                      fill="currentColor"
                    >{`${Math.round(Number(r.coverage ?? 0) * 100)}%`}</text>
                  </svg>
                  <strong>{r.metric ?? "KPI"}</strong>
                  <span>{`${r.season ?? ""} · ${r.pass == null ? "Not checked" : r.pass ? "Pass" : "Fail"}`}</span>
                  <small>
                    {r.threshold == null
                      ? "Threshold not saved"
                      : percent(r.threshold) + " minimum"}
                  </small>
                </div>
              ))}
            </div>
          ) : (
            bars(kind)
          )}
          {rows.length > 0 && kind !== "equation" && (
            <small>{`Saved sample · ${rows.length} ${node.io.gives.unit_label}${rows.length === 1 ? "" : "s"}`}</small>
          )}
        </article>
      ))}
    </div>
  );
}
