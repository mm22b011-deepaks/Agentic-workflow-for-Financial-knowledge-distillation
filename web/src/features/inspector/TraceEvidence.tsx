import { useEffect, useState } from "react";
import { api } from "../../shared/api";
import { useSession } from "../../shared/state";
import { validEvidenceResponse, validLabelResponse } from "../../validators.js";
import type { EvidenceResponse } from "../../EvidenceResponse";
import type { PaneResponse } from "../../PaneResponse";
import { copy, fieldLabel } from "../../copy";
import { Button } from "../../shared/Button";
export function TraceEvidence({ data }: { data: PaneResponse | null }) {
  const session = useSession();
  const [at, setAt] = useState(0);
  const [field, setField] = useState(0);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const id = String(data?.rows[at]?.document_id ?? "");
  useEffect(() => {
    if (!session.trace || session.mode === "replay" || !id) return;
    let alive = true;
    void api(
      "records/" +
        encodeURIComponent(id) +
        "/evidence" +
        (data?.run ? "?run=" + encodeURIComponent(data.run) : ""),
      validEvidenceResponse,
    )
      .then((e) => {
        if (alive) setEvidence(e);
      })
      .catch(() => {
        if (alive) setEvidence(null);
      });
    return () => {
      alive = false;
    };
  }, [id, data?.run, session.trace, session.mode]);
  const current = evidence?.fields[field];
  async function verdict(value: "correct" | "wrong" | "unsure") {
    if (!session.trace || session.mode === "replay" || !evidence || !current)
      return;
    try {
      await api("labels", validLabelResponse, {
        record_id: evidence.record_id,
        field: current.field,
        value: current.value,
        verdict: value,
      });
      setEvidence({
        ...evidence,
        verdicts: { ...evidence.verdicts, [current.field]: value },
      });
    } catch {
      session.set({ error: copy.unavailable });
    }
  }
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if ((e.target as HTMLElement).closest("input,select,textarea")) return;
      if (e.key === "j")
        setAt((n) => Math.min((data?.rows.length ?? 1) - 1, n + 1));
      if (e.key === "k") setAt((n) => Math.max(0, n - 1));
      if (["1", "2", "3"].includes(e.key))
        void verdict(
          (["correct", "wrong", "unsure"] as const)[Number(e.key) - 1],
        );
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  if (!session.trace || !current || !evidence)
    return <div className="io-empty">{"Evidence unavailable"}</div>;
  const start = current.row_start ?? current.start ?? 0;
  const end =
    current.row_end ??
    current.end ??
    Math.min(evidence.source.length, start + 200);
  return (
    <div className="evidence-view">
      <select
        aria-label={copy.field}
        value={field}
        onChange={(e) => setField(Number(e.target.value))}
      >
        {evidence.fields.map((f, i) => (
          <option key={f.field} value={i}>
            {fieldLabel(f.field)}
          </option>
        ))}
      </select>
      <strong>{String(current.value ?? "Not stated")}</strong>
      <small>{current.unit}</small>
      <progress
        value={current.confidence ?? 0}
        max={1}
        aria-label={"Confidence"}
      />
      <div
        className={`source-row ${current.number_present === false ? "wrong-row" : ""}`}
        data-testid="evidence-row"
        data-number-present={String(current.number_present)}
      >
        <mark>{evidence.source.slice(start, end)}</mark>
      </div>
      <div className="verdicts">
        {(["correct", "wrong", "unsure"] as const).map((v, i) => (
          <Button
            key={v}
            icon={["check", "cross", "question"][i]}
            title={copy[v]}
            aria-pressed={evidence.verdicts?.[current.field] === v}
            onClick={() => void verdict(v)}
          />
        ))}
      </div>
      <div className="pager">
        <Button
          icon="previous"
          title={"Previous example"}
          disabled={!at}
          onClick={() => {
            setAt(at - 1);
            setEvidence(null);
          }}
        />
        <Button
          icon="next"
          title={"Next example"}
          disabled={at + 1 >= (data?.rows.length ?? 0)}
          onClick={() => {
            setAt(at + 1);
            setEvidence(null);
          }}
        />
      </div>
    </div>
  );
}
