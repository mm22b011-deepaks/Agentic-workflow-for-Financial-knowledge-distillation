import { useEffect, useState } from "react";
import type { CanvasRegistry } from "../../CanvasRegistry";
import type { PaneResponse } from "../../PaneResponse";
import type { StageSnapshot } from "../../StageSnapshot";
import { useSession } from "../../shared/state";
import { quantity, pseudonym, sourceBadge } from "../../shared/io";
import { Icon } from "../../shared/Icon";
import { Button } from "../../shared/Button";
import { label } from "../../copy";
import { IOSummary } from "./IOSummary";
import { TraceEvidence } from "./TraceEvidence";

type Props = {
  nodeId: string;
  side: "input" | "output";
  data: PaneResponse | null;
  other: PaneResponse | null;
  loading: boolean;
  onRun: (run: string) => void;
  onUpstream: (id: string) => void;
  onQuery: (q: Record<string, string>) => void;
  upstreamValue?: string;
  registry: CanvasRegistry;
  stages: StageSnapshot;
  timestamp: string;
  retry: () => void;
};
const views = [
  ["summary", "chart", "Summary"],
  ["example", "evidence", "Example"],
  ["table", "table", "Table"],
  ["json", "json", "JSON"],
  ["fields", "schema", "Fields"],
] as const;
export function DataPane(props: Props) {
  const { nodeId, side, registry, stages, loading, timestamp } = props;
  const session = useSession();
  const [view, setView] = useState("summary");
  const [at, setAt] = useState(0);
  const [target, setTarget] = useState("");
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (
        side === "output" &&
        session.trace &&
        session.help === null &&
        e.key.toLowerCase() === "e" &&
        !(e.target as HTMLElement).closest("input,select,textarea")
      )
        setView("evidence");
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [side, session.trace, session.help]);
  const node = registry.nodes.find((n) => n.id === nodeId)!;
  const peers = registry.edges
    .filter(
      (e) =>
        !e.sub &&
        (side !== "input" ||
          registry.nodes.find((n) => n.id === e.source)?.variant !==
            "trigger") &&
        (side === "input" ? e.target === nodeId : e.source === nodeId),
    )
    .map((e) => (side === "input" ? e.source : e.target));
  const sources =
    side === "input"
      ? [...new Set([...(props.data?.upstream ?? []), ...peers])].filter(
          (id) =>
            registry.nodes.find((n) => n.id === id)?.variant !== "trigger",
        )
      : peers;
  const selected =
    (side === "input" ? props.upstreamValue : target) || sources[0];
  const peer = registry.nodes.find((n) => n.id === selected);
  const origin = side === "input" ? (peer ?? node) : node;
  const contract = node.io[side === "input" ? "takes" : "gives"];
  const synthetic = stages.source === "synthetic";
  const data =
    (!session.trace && props.data?.view === "trace") || props.data?.node !== nodeId ? null : props.data;
  const stage = stages.nodes.find((n) => n.id === origin.id);
  const count = quantity(origin, stage, data);
  const unit =
    side === "input" ? contract.unit_label : node.io.gives.unit_label;
  const total = count?.total ?? data?.total ?? 0;
  const countText =
    nodeId === "run-all" && side === "output"
      ? "Runs every step"
      : side === "output" && count
        ? count.text
        : `${total.toLocaleString()} ${unit}${total === 1 ? "" : "s"}`;
  const fields = [...origin.io.example_fields];
  const allowed = fields.filter((f) => f.key !== "text" || session.trace);
  if (session.trace)
    for (const key of ["document_id", "cik", "ticker", "company", "sector"])
      if (props.data?.columns.includes(key))
        allowed.push({
          key,
          label: key === "cik" ? "CIK" : key.replaceAll("_", " "),
          unit: "",
          format: "value",
          description: "Internal trace identifier",
        });
  const rows = (data?.rows ?? []).map((row) =>
    Object.fromEntries(
      allowed.filter((f) => f.key in row).map((f) => [f.key, row[f.key]]),
    ),
  );
  const row = rows[Math.min(at, Math.max(0, rows.length - 1))];
  const available = !!row && Object.keys(row).length >= 3;
  const badge = sourceBadge(session.mode, stages.source);
  const value = (key: string, v: unknown, item = row) => {
    if (key === "metric_value" && v != null)
      return `${item.metric_unit === "fraction" ? (Number(v) * 100).toFixed(1) : v}${item.metric_unit === "score" ? " score" : "%"}`;
    if (key === "pass" && v != null) return v ? "Pass" : "Fail";
    if ((key === "bytes" || key === "size_bytes") && v != null)
      return `${Math.round(Number(v) / 1000)} KB`;
    if (key === "review_field")
      return (
        registry.nodes
          .flatMap((n) => n.io.example_fields)
          .find((f) => f.key === v)?.label ?? "Record"
      );
    if (v == null)
      return key === "left" || key === "end_date" || key === "effective_to"
        ? "Still in"
        : "Not stated";
    if (key === "setting")
      return String(v).split(".").at(-1)?.replaceAll("_", " ");
    if (key.endsWith("_token"))
      return pseudonym(
        String(v),
        key === "member_token" ? "Member" : "Release",
      );
    const field = fields.find((f) => f.key === key);
    if (field?.format === "date")
      return new Date(String(v)).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      });
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (field?.unit === "%")
      return `${field.format === "fraction" ? Math.round(Number(v) * 100) : Number(v)}%`;
    return `${String(v)}${field?.unit ? " " + field.unit : ""}`;
  };
  const example = available ? (
    <article className="io-example" data-testid="example-card">
      <header>
        <strong>{"Example"}</strong>
        <div>
          <Button
            icon="previous"
            title={"Previous example"}
            disabled={at === 0}
            onClick={() => setAt(at - 1)}
          />
          <Button
            icon="next"
            title={"Next example"}
            disabled={at + 1 >= rows.length}
            onClick={() => setAt(at + 1)}
          />
        </div>
      </header>
      {row && "reported_eps" in row && (
        <dl className="io-facts">
          {["reported_eps", "revenue", "guidance_presence", "tone"].map(
            (key) => {
              const prefix =
                key === "reported_eps"
                  ? "eps"
                  : key === "guidance_presence"
                    ? "guidance"
                    : key;
              return (
                <div key={key}>
                  <dt>{fields.find((f) => f.key === key)?.label}</dt>
                  <dd>
                    <Icon
                      name={
                        row[key] == null
                          ? "question"
                          : row.flagged
                            ? "cross"
                            : "check"
                      }
                      size={13}
                    />
                    {value(key, row[key])}
                    <progress
                      aria-label={prefix + " confidence"}
                      max={1}
                      value={Number(row[prefix + "_confidence"] ?? 0)}
                    />
                    <small>
                      {row[prefix + "_confidence"] == null
                        ? "Confidence not saved"
                        : Math.round(
                            Number(row[prefix + "_confidence"]) * 100,
                          ) + "% confidence"}
                    </small>
                  </dd>
                </div>
              );
            },
          )}
        </dl>
      )}
      <dl>
        {Object.entries(row)
          .filter(
            ([key]) =>
              !("reported_eps" in row) ||
              ![
                "reported_eps",
                "revenue",
                "guidance_presence",
                "tone",
                "eps_confidence",
                "revenue_confidence",
                "guidance_confidence",
                "tone_confidence",
                "eps_status",
                "revenue_status",
                "guidance_status",
                "tone_status",
              ].includes(key),
          )
          .map(([key, v]) => (
            <div key={key}>
              <dt title={fields.find((f) => f.key === key)?.description}>
                {fields.find((f) => f.key === key)?.label}
              </dt>
              <dd>
                {value(key, v)}
                {key.includes("confidence") && (
                  <progress
                    aria-label={"Confidence"}
                    max={1}
                    value={Number(v)}
                  />
                )}
              </dd>
            </div>
          ))}
      </dl>
    </article>
  ) : (
    <div className="io-empty">
      <Icon name="privacy" />
      {data?.status === "private"
        ? "Details unavailable in this run"
        : "No example saved for this step"}
    </div>
  );
  return (
    <section
      className={`data-pane io-pane ${node.capability === "planned" ? "io-planned" : ""}`}
      aria-label={side.toUpperCase()}
    >
      <div className="pane-header">
        <span>{side.toUpperCase()}</span>
        {!session.trace && (
          <span className="lock-chip">
            <Icon name="privacy" size={13} />
            {"Names hidden"}
          </span>
        )}
      </div>
      <div className="io-source">
        <Icon name={side === "input" ? (peer?.icon ?? "config") : node.icon} />
        <span>
          {side === "input"
            ? peer
              ? label(peer.label_key)
              : "Settings file"
            : label(node.label_key)}
        </span>
        <Icon name="arrow" size={14} />
        <Icon name={side === "input" ? node.icon : (peer?.icon ?? "publish")} />
        {side === "output" && (
          <span>{peer ? label(peer.label_key) : "Saved output"}</span>
        )}
      </div>
      {sources.length > 1 && (
        <div className="io-chips">
          {sources.map((id) => (
            <button
              key={id}
              aria-pressed={selected === id}
              onClick={() =>
                side === "input" ? props.onUpstream(id) : setTarget(id)
              }
            >
              {label(registry.nodes.find((n) => n.id === id)?.label_key ?? id)}
            </button>
          ))}
        </div>
      )}
      <div className="io-headline" data-testid="io-count">
        <Icon name={contract.icon} size={26} />
        <strong>{countText}</strong>
      </div>
      <p className="io-plain">{contract.plain_line}</p>
      <nav className="format-toggle" aria-label={side + " data views"}>
        {views.map(([id, icon, title]) => (
          <Button
            key={id}
            icon={icon}
            title={title}
            aria-pressed={view === id}
            onClick={() => setView(id)}
            className={view === id ? "active" : ""}
          />
        ))}
        {session.trace && (
          <Button
            icon="evidence"
            title={"Evidence"}
            onClick={() => setView("evidence")}
          />
        )}
      </nav>
      <div className="io-body" aria-busy={loading}>
        {loading ? (
          <div className="io-shimmer" aria-label={"Loading"} />
        ) : node.capability === "planned" ? (
          <div className="io-empty">
            <Icon name="clock" />
            {"Not built yet"}
          </div>
        ) : !data && !synthetic && session.mode !== "replay" ? (
          <div className="io-empty">
            <Icon name="cross" />
            {`${label(node.label_key)}: data unavailable`}
            <Button
              icon="resume"
              title={"Retry step data"}
              onClick={props.retry}
            />
          </div>
        ) : (
          <>
            {view === "summary" && (
              <>
                <IOSummary
                  before={props.other?.total}
                  node={origin}
                  rows={rows}
                  total={total}
                  countText={countText}
                />
                {origin.id !== "estimate-scope" && example}
              </>
            )}
            {view === "example" && example}
            {view === "table" &&
              (available ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        {Object.keys(row).map((k) => (
                          <th key={k}>
                            {fields.find((f) => f.key === k)?.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}>
                          {Object.entries(r).map(([k, v]) => (
                            <td key={k}>{value(k, v, r)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                example
              ))}
            {view === "json" && (
              <pre>
                {JSON.stringify(
                  row
                    ? Object.fromEntries(
                        Object.entries(row).map(([k, v]) => [
                          fields.find((f) => f.key === k)?.label,
                          value(k, v),
                        ]),
                      )
                    : { Status: "No example saved" },
                  null,
                  2,
                )}
              </pre>
            )}
            {view === "fields" && (
              <dl className="io-fields">
                {allowed
                  .filter((f) => data?.columns.includes(f.key))
                  .map((f) => (
                    <div key={f.key}>
                      <dt>{f.label}</dt>
                      <dd>
                        {f.description}
                        {f.unit ? " · " + f.unit : ""}
                      </dd>
                    </div>
                  ))}
              </dl>
            )}
            {view === "evidence" && session.trace && (
              <TraceEvidence {...props} />
            )}
          </>
        )}
      </div>
      <footer className="io-footer">
        <span title={data?.run ?? stage?.last_run ?? "No saved run"}>
          {data?.run || stage?.last_run
            ? "Run " +
              Math.max(1, (data?.runs?.indexOf(data?.run ?? "") ?? 0) + 1)
            : "No saved run"}
        </span>
        <time title={timestamp}>{age(timestamp)}</time>
        <b title={timestamp}>{badge}</b>
        <span title={data?.config_hash ?? "Version 1"}>{"v1"}</span>
      </footer>
    </section>
  );
}
function age(timestamp: string) {
  const seconds = Math.max(0, (Date.now() - Date.parse(timestamp)) / 1000);
  return seconds < 60 ? "Just now" : Math.floor(seconds / 60) + " min ago";
}
