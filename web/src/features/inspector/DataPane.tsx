import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  copy,
  fieldLabel,
  glyphs,
  label,
  tooltip,
  typeLabel,
} from "../../copy";
import { Button } from "../../shared/Button";
import { Icon } from "../../shared/Icon";
import { useSession } from "../../shared/state";
import { api } from "../../shared/api";
import { validEvidenceResponse, validLabelResponse } from "../../validators.js";
import type { PaneResponse } from "../../PaneResponse";
import type { EvidenceResponse } from "../../EvidenceResponse";
import type { LabelResponse } from "../../LabelResponse";
type Row = PaneResponse["rows"][number];
type Format = "table" | "json" | "schema" | "diff" | "evidence";
const paneMemory: Record<
  string,
  { format: Format; column: number; record: number; fact: number }
> = {};
const formats: Format[] = ["table", "json", "schema", "diff", "evidence"];
export function DataPane({
  nodeId,
  side,
  data: incomingData,
  other: incomingOther,
  loading,
  onRun,
  onUpstream,
  onQuery,
  upstreamValue = "",
}: {
  nodeId: string;
  side: "input" | "output";
  data: PaneResponse | null;
  other: PaneResponse | null;
  loading: boolean;
  onRun: (run: string) => void;
  onUpstream: (node: string) => void;
  onQuery: (query: Record<string, string>) => void;
  upstreamValue?: string;
}) {
  const session = useSession();
  const data =
    incomingData?.view === "trace" && !session.trace ? null : incomingData;
  const other =
    incomingOther?.view === "trace" && !session.trace ? null : incomingOther;
  const memoryKey = nodeId + ":" + side;
  const saved = paneMemory[memoryKey];
  const [format, setFormat] = useState<Format>(saved?.format ?? "table");
  const [column, setColumn] = useState(saved?.column ?? 0);
  const [descending, setDescending] = useState(false);
  const [record, setRecord] = useState(saved?.record ?? 0);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [fact, setFact] = useState(saved?.fact ?? 0);
  const [stats, setStats] = useState<LabelResponse | null>(null);
  const [query, setQuery] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const columns = data?.columns ?? [];
  const rows = useMemo(
    () =>
      [...(data?.rows ?? [])].sort((a, b) => {
        const key = columns[column];
        const value =
          typeof a[key] === "number" && typeof b[key] === "number"
            ? Number(a[key]) - Number(b[key])
            : String(a[key] ?? "").localeCompare(String(b[key] ?? ""));
        return descending ? -value : value;
      }),
    [data, column, descending],
  );
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroll.current,
    estimateSize: () => 48,
    overscan: 0,
  });
  const selected = rows[record];
  const id = String(selected?.document_id ?? "");
  useEffect(() => {
    paneMemory[memoryKey] = { format, column, record, fact };
  }, [memoryKey, format, column, record, fact]);
  useEffect(() => {
    if (
      format !== "evidence" ||
      !session.trace ||
      session.mode === "replay" ||
      !id
    ) {
      setEvidence(null);
      return;
    }
    let alive = true;
    setEvidence(null);
    void api(
      "records/" +
        encodeURIComponent(id) +
        "/evidence" +
        (data?.run ? "?run=" + encodeURIComponent(data.run) : ""),
      validEvidenceResponse,
    )
      .then((value) => {
        if (alive) {
          setEvidence(value);
          setFact(0);
        }
      })
      .catch(() => {
        if (alive) setEvidence(null);
      });
    return () => {
      alive = false;
    };
  }, [format, id, data?.run, session.trace, session.mode]);
  async function verdict(value: "correct" | "wrong" | "unsure") {
    if (!evidence || session.mode === "replay" || !session.trace) return;
    const current =
      fact < 0 ? { field: "record", value: null } : evidence.fields[fact];
    if (!current) return;
    try {
      const result = await api("labels", validLabelResponse, {
        record_id: evidence.record_id,
        field: current.field,
        value: current.value,
        verdict: value,
      });
      setStats(result);
      setEvidence({
        ...evidence,
        verdicts: { ...evidence.verdicts, [current.field]: value },
      });
    } catch {
      session.set({ error: copy.unavailable });
    }
  }
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if ((event.target as HTMLElement).closest("input,textarea,select"))
        return;
      if (side !== "output" || session.help !== null) return;
      if (event.key.toLowerCase() === "e") setFormat("evidence");
      if (event.key.toLowerCase() === "j")
        setRecord((old) => Math.min(rows.length - 1, old + 1));
      if (event.key.toLowerCase() === "k")
        setRecord((old) => Math.max(0, old - 1));
      if (["1", "2", "3"].includes(event.key))
        void verdict(
          (["correct", "wrong", "unsure"] as const)[Number(event.key) - 1],
        );
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [
    evidence,
    fact,
    rows.length,
    side,
    session.mode,
    session.trace,
    session.help,
  ]);
  function updateQuery(name: string, value: string) {
    const next = { ...query, offset: "0", [name]: value };
    setQuery(next);
    onQuery(next);
  }
  function copyPath(path: string) {
    void navigator.clipboard?.writeText(path);
  }
  const visibleColumns = [
    columns[0],
    columns[Math.min(column || 1, columns.length - 1)],
  ].filter((v, i, a) => v && a.indexOf(v) === i);
  const current =
    fact < 0 && evidence
      ? {
          field: "record",
          value: null,
          unit: null,
          confidence: null,
          quote: null,
          issues: [],
          row_start: null,
          row_end: null,
          start: null,
          end: null,
          number_present: null,
        }
      : evidence?.fields[fact];
  const excerpt = useMemo(() => {
    if (!evidence || !current) return null;
    const start = current.row_start ?? current.start ?? 0;
    const end =
      current.row_end ??
      current.end ??
      Math.min(evidence.source.length, start + 200);
    const source = evidence.source.slice(start, end);
    const words = source.split(/\s+/).slice(0, 12).join(" ");
    const quote = current.quote ?? "";
    const at = words.toLowerCase().indexOf(quote.toLowerCase());
    return (
      <div
        className={`source-row ${current.number_present === false ? "wrong-row" : ""}`}
        data-testid="evidence-row"
        data-number-present={String(current.number_present)}
      >
        {at >= 0 && quote ? (
          <>
            {words.slice(0, at)}
            <mark>{words.slice(at, at + quote.length)}</mark>
            {words.slice(at + quote.length)}
          </>
        ) : (
          <mark>{words}</mark>
        )}
      </div>
    );
  }, [evidence, current]);
  return (
    <section
      className={`data-pane ${loading ? "loading" : ""}`}
      aria-label={side === "input" ? copy.input : copy.output}
    >
      <div className="pane-header">
        <span>{side === "input" ? copy.input : copy.output}</span>
        <span className="count">
          {data?.status === "unavailable"
            ? copy.unknown
            : (data?.total ?? copy.unknown)}
        </span>
        <span className="status-dot" data-status={data?.status} />
      </div>
      <div className="pane-selects">
        {side === "input" && !!data?.upstream?.length && (
          <select
            aria-label={copy.upstream}
            value={upstreamValue || data.upstream[0]}
            onChange={(e) => onUpstream(e.target.value)}
          >
            {data.upstream.map((n) => (
              <option key={n} value={n}>
                {label(n)}
              </option>
            ))}
          </select>
        )}
        <select
          aria-label={copy.runs}
          value={data?.run ?? ""}
          onChange={(e) => onRun(e.target.value)}
        >
          <option value="">{copy.live}</option>
          {data?.runs?.map((run, i) => (
            <option key={run} value={run}>
              {i + 1}
            </option>
          ))}
        </select>
        {data?.duration != null && (
          <small>
            {data.duration.toFixed(1)}
            {copy.seconds}
          </small>
        )}
      </div>
      <div className="format-toggle">
        <div className="format-tabs" role="tablist" aria-label={copy.select}>
          {formats.map((f) => (
            <Button
              key={f}
              icon={f}
              title={copy[f]}
              role="tab"
              aria-selected={format === f}
              onClick={() => setFormat(f)}
              className={format === f ? "active" : ""}
            />
          ))}
        </div>
        {session.trace && (
          <Button
            icon="config"
            title={copy.source}
            onClick={() => setFilter(!filter)}
          />
        )}
      </div>
      {filter && session.trace && (
        <div className="filters">
          <input
            aria-label={copy.search}
            placeholder={copy.search}
            value={query.search ?? ""}
            onChange={(e) => updateQuery("search", e.target.value)}
          />
          <select
            aria-label={copy.reason}
            value={query.flagged ?? ""}
            onChange={(e) => updateQuery("flagged", e.target.value)}
          >
            <option value="">{copy.unknown}</option>
            <option value="true">{copy.flagged}</option>
            <option value="false">{copy.ok}</option>
          </select>
          {["reason", "field", "season", "sample", "seed"].map((key) => (
            <input
              key={key}
              type={key === "sample" || key === "seed" ? "number" : "text"}
              aria-label={label(key)}
              placeholder={label(key)}
              value={query[key] ?? ""}
              onChange={(e) => updateQuery(key, e.target.value)}
            />
          ))}
        </div>
      )}
      {format === "table" && (
        <>
          <div className="column-select">
            <select
              aria-label={copy.field}
              value={columns[column] ?? ""}
              onChange={(e) => {
                setColumn(columns.indexOf(e.target.value));
                setDescending(!descending);
              }}
            >
              {columns.map((col) => (
                <option key={col} value={col}>
                  {fieldLabel(col)}
                </option>
              ))}
            </select>
            <button
              aria-label={copy.select}
              onClick={() => setDescending(!descending)}
            >
              {glyphs.sort}
            </button>
          </div>
          <div className="table-scroll" ref={scroll}>
            <table>
              <thead>
                <tr>
                  {visibleColumns.map((col) => (
                    <th
                      key={col}
                      scope="col"
                      onClick={() => setDescending(!descending)}
                    >
                      {fieldLabel(col)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody
                style={{ height: virtual.getTotalSize(), position: "relative" }}
              >
                {virtual
                  .getVirtualItems()
                  .slice(0, 1)
                  .map((item) => (
                    <tr
                      key={item.key}
                      style={{
                        position: "absolute",
                        top: 0,
                        transform: `translateY(${item.start}px)`,
                        height: 48,
                        width: "100%",
                      }}
                      onClick={() => {
                        setRecord(item.index);
                        if (session.trace && side === "output")
                          setFormat("evidence");
                      }}
                    >
                      {visibleColumns.map((col, i) => (
                        <td
                          key={col}
                          className={i === 0 ? "pinned" : ""}
                          title={tooltip(
                            rows[item.index]?.[col] ?? copy.unknown,
                          )}
                        >
                          {cell(rows[item.index]?.[col])}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {(data?.total ?? 0) > 50 && (
            <Pager
              current={Math.floor((data?.offset ?? 0) / 50)}
              total={Math.ceil((data?.total ?? 0) / 50)}
              onChange={(page) => updateQuery("offset", String(page * 50))}
            />
          )}
        </>
      )}
      {format === "json" && <JsonTree row={selected} onCopy={copyPath} />}
      {format === "schema" && (
        <div className="schema-view">
          {columns.slice(column, column + 1).map((key) => {
            const profile = data?.profiles?.find(
              (field) => field.field === key,
            );
            return (
              <div key={key}>
                <code>{fieldLabel(key)}</code>
                <small>{typeLabel(profile?.inferred_type ?? "null")}</small>
                <progress
                  value={profile?.null_rate ?? undefined}
                  max={1}
                  aria-label={copy.nulls}
                />
                <code>{cell(profile?.example)}</code>
              </div>
            );
          })}
          <Pager current={column} total={columns.length} onChange={setColumn} />
        </div>
      )}
      {format === "diff" && (
        <div className="diff-view">
          {[...new Set([...columns, ...(other?.columns ?? [])])]
            .slice(column, column + 1)
            .map((key) => {
              const before = other?.profiles?.find(
                (field) => field.field === key,
              );
              const after = data?.profiles?.find(
                (field) => field.field === key,
              );
              return (
                <div
                  key={key}
                  className={
                    JSON.stringify(before) !== JSON.stringify(after)
                      ? "changed"
                      : ""
                  }
                >
                  <code>{fieldLabel(key)}</code>
                  <del>
                    {before ? typeLabel(before.inferred_type) : copy.unknown}
                  </del>
                  <ins>
                    {after ? typeLabel(after.inferred_type) : copy.unknown}
                  </ins>
                </div>
              );
            })}
          <Pager
            current={column}
            total={Math.max(columns.length, other?.columns.length ?? 0)}
            onChange={setColumn}
          />
        </div>
      )}
      {format === "evidence" && (
        <div className="evidence-view">
          {!session.trace || !current ? (
            <span className="hollow">
              <Icon name="privacy" size={36} />
              {copy.unknown}
            </span>
          ) : (
            <>
              <div className="evidence-field">
                <select
                  aria-label={copy.field}
                  value={fact}
                  onChange={(e) => setFact(Number(e.target.value))}
                >
                  <option value={-1}>{copy.record}</option>
                  {evidence?.fields.map((f, i) => (
                    <option key={f.field} value={i}>
                      {fieldLabel(f.field)}
                    </option>
                  ))}
                </select>
                <strong
                  className={current.number_present === false ? "invalid" : ""}
                >
                  {cell(current.value)}
                </strong>
                <small>{current.unit ?? copy.unknown}</small>
                <progress
                  value={
                    current.value === null
                      ? undefined
                      : (current.confidence ?? undefined)
                  }
                  max={1}
                  aria-label={copy.value}
                />
                <span className="issue-chips">
                  {current.issues.slice(0, 1).map((issue) => (
                    <span
                      key={issue}
                      role="img"
                      aria-label={label(issue)}
                      title={tooltip(label(issue))}
                    >
                      {glyphs.cross}
                    </span>
                  ))}
                </span>
              </div>
              {excerpt}
              <div className="verdicts">
                {(["correct", "wrong", "unsure"] as const).map((v, i) => (
                  <Button
                    key={v}
                    icon={["check", "cross", "question"][i]}
                    title={copy[v]}
                    aria-pressed={evidence?.verdicts?.[current.field] === v}
                    disabled={session.mode === "replay"}
                    onClick={() => void verdict(v)}
                  />
                ))}
                <svg
                  className="progress-ring"
                  viewBox="0 0 36 36"
                  aria-label={copy.saved}
                >
                  <circle cx="18" cy="18" r="15" pathLength="100" />
                  <circle
                    cx="18"
                    cy="18"
                    r="15"
                    pathLength="100"
                    strokeDasharray={`${stats?.total ? (stats.checked / stats.total) * 100 : 0} 100`}
                  />
                </svg>
                <small>
                  {stats?.checked ?? 0}/
                  {stats?.total ?? data?.total ?? copy.unknown}
                </small>
              </div>
              {stats?.fields?.[current.field] && (
                <progress
                  value={stats.fields[current.field].correct}
                  max={
                    stats.fields[current.field].correct +
                    stats.fields[current.field].wrong
                  }
                  aria-label={copy.correct}
                />
              )}
              <Pager
                current={record}
                total={rows.length}
                onChange={setRecord}
              />
            </>
          )}
        </div>
      )}
    </section>
  );
}
function cell(value: Row[string] | undefined) {
  return value == null
    ? copy.unknown
    : typeof value === "boolean"
      ? value
        ? glyphs.check
        : glyphs.cross
      : typeof value === "number"
        ? Number(value.toFixed(3)).toLocaleString()
        : String(value).trim().startsWith("{") ||
            String(value).trim().startsWith("[")
          ? copy.json
          : String(value).split(/\s+/).slice(0, 2).join(" ").slice(0, 24);
}
function Pager({
  current,
  total,
  onChange,
}: {
  current: number;
  total: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="pager">
      <Button
        icon="previous"
        title={copy.previous}
        disabled={current <= 0}
        onClick={() => onChange(Math.max(0, current - 1))}
      />
      <small>
        {total ? current + 1 : 0}/{total}
      </small>
      <Button
        icon="next"
        title={copy.next}
        disabled={current + 1 >= total}
        onClick={() => onChange(current + 1)}
      />
    </div>
  );
}

function parsed(value: unknown): unknown {
  if (typeof value === "string" && /^[{[]/.test(value.trim())) {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  return value;
}
function JsonTree({
  row,
  onCopy,
}: {
  row: Row | undefined;
  onCopy: (path: string) => void;
}) {
  const [path, setPath] = useState<string[]>([]);
  const [page, setPage] = useState(0);
  let value: unknown = row;
  for (const key of path) {
    const object = parsed(value);
    value =
      object && typeof object === "object"
        ? (object as Record<string, unknown>)[key]
        : undefined;
  }
  const object = parsed(value);
  const entries =
    object && typeof object === "object" ? Object.entries(object) : [];
  return (
    <div className="json-tree">
      <div className="json-level">
        <Button
          icon="previous"
          title={copy.previous}
          disabled={!path.length}
          onClick={() => {
            setPath(path.slice(0, -1));
            setPage(0);
          }}
        />
        <code>{path.length}</code>
        <Button
          icon="copy"
          title={copy.path}
          onClick={() => onCopy("$" + path.map((key) => "." + key).join(""))}
        />
      </div>
      {entries.slice(page * 2, page * 2 + 2).map(([key, item]) => {
        const child = parsed(item);
        const nested = child !== null && typeof child === "object";
        return (
          <div className="json-entry" key={key}>
            <button
              aria-expanded={nested ? false : undefined}
              title={tooltip(key)}
              disabled={!nested}
              onClick={() => {
                setPath([...path, key]);
                setPage(0);
              }}
            >
              <Icon name={nested ? "json" : "schema"} size={14} />
              <code>{fieldLabel(key)}</code>
            </button>
            {!nested && <code>{cell(item as Row[string])}</code>}
            <Button
              icon="copy"
              title={copy.path}
              onClick={() =>
                onCopy("$" + [...path, key].map((part) => "." + part).join(""))
              }
            />
          </div>
        );
      })}
      {!entries.length && copy.unknown}
      <Pager
        current={page}
        total={Math.ceil(entries.length / 2)}
        onChange={setPage}
      />
    </div>
  );
}
