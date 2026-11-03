import type { CanvasNode } from "../CanvasRegistry";
import type { StageState } from "../StageSnapshot";
import type { PaneResponse } from "../PaneResponse";

export function quantity(
  node: CanvasNode,
  stage?: StageState,
  data?: PaneResponse | null,
) {
  if (node.id === "run-all") return null; // The trigger has no single output quantity.
  const total =
    (data?.run && data.run !== stage?.last_run
      ? data.total
      : stage?.out_count) ??
    (data?.status !== "unavailable" ? data?.total : null);
  if (total == null || node.capability === "planned") return null;
  const unit = node.io.gives.unit_label;
  return {
    total,
    unit,
    text: `${total.toLocaleString()} ${unit}${total === 1 ? "" : "s"}`,
  };
}
const pseudonyms = new Map<string, string>();
const used = new Set<string>();
const salt = crypto.getRandomValues(new Uint32Array(4)).join("-");
export function pseudonym(token: string, kind: string) {
  const key = kind + token;
  if (pseudonyms.has(key)) return pseudonyms.get(key)!;
  let hash = 2166136261;
  for (const char of salt + token)
    hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  let number = (hash >>> 0) % 100000;
  while (used.has(kind + number)) number++;
  used.add(kind + number);
  const name = `${kind} ${String(number).padStart(3, "0")}`;
  pseudonyms.set(key, name);
  return name;
}
export function sourceBadge(mode: string, source?: string, readOnly = false) {
  return mode === "replay"
    ? "REPLAY"
    : source === "synthetic"
      ? "DEMO"
      : readOnly ? "REPLAY" : "LIVE";
}
