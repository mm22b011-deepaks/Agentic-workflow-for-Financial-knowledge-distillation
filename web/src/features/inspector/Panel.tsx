import { useEffect, useState, useRef } from "react";
import { AnimatePresence, motion, Reorder } from "framer-motion";
import { copy, label, fieldLabel, glyphs } from "../../copy";
import { Button } from "../../shared/Button";
import { Icon } from "../../shared/Icon";
import { api } from "../../shared/api";
import { useSession } from "../../shared/state";
import { validPaneResponse, validSettingsResponse } from "../../validators.js";
import { DataPane } from "./DataPane";
import type { CanvasRegistry } from "../../CanvasRegistry";
import demoPanes from "../../io-demo.json";
import type { StageSnapshot } from "../../StageSnapshot";
import type { PaneResponse } from "../../PaneResponse";
import type { CLIControl } from "../../CanvasRegistry";
import type { ConfigControl } from "../../SettingsResponse";
type Parameters = Record<string, string | number | boolean | string[]>;
const memory: Record<
  string,
  {
    parameters: Parameters;
    tab: string;
    section: number;
    runs?: { input: string; output: string };
    upstream?: string;
  }
> = {};
export function inspectionState(id: string) {
  return memory[id];
}
export function Panel({
  registry,
  badge,
  stages,
  timestamp,
  active,
  onExecute,
}: {
  registry: CanvasRegistry;
  badge: string;
  stages: StageSnapshot;
  timestamp: string;
  active: boolean;
  onExecute: (
    command: string,
    parameters: Parameters,
    upstream?: string,
  ) => void;
}) {
  const session = useSession();
  const id = session.panel;
  const node = registry.nodes.find((n) => n.id === id);
  const selectedStage = stages.nodes.find((stage) => stage.id === id);
  const remembered = useRef(id);
  const [input, setInput] = useState<PaneResponse | null>(null);
  const [output, setOutput] = useState<PaneResponse | null>(null);
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(false);
  const [settings, setSettings] = useState<ConfigControl[]>([]);
  const [draftParameters, setParameters] = useState<Parameters>(
    memory[id ?? ""]?.parameters ?? {},
  );
  const parameters: Parameters =
    session.mode === "replay" ? {} : draftParameters;
  const [tab, setTab] = useState(memory[id ?? ""]?.tab ?? "parameters");
  const [section, setSection] = useState(memory[id ?? ""]?.section ?? 0);
  const [runs, setRuns] = useState({ input: "", output: "" });
  const [upstream, setUpstream] = useState("");
  const [queries, setQueries] = useState({ input: {}, output: {} });
  useEffect(() => {
    if (!id) return;
    const saved = session.mode === "live" ? memory[id] : undefined;
    setParameters(saved?.parameters ?? {});
    setTab(saved?.tab ?? "parameters");
    setSection(saved?.section ?? 0);
    setInput(null);
    setOutput(null);
    setRuns(saved?.runs ?? { input: "", output: "" });
    setUpstream(saved?.upstream ?? "");
    setQueries({ input: {}, output: {} });
  }, [id, session.mode]);
  useEffect(() => {
    if (remembered.current !== id) {
      remembered.current = id;
      return;
    }
    if (id && session.mode === "live")
      memory[id] = {
        parameters: draftParameters,
        tab,
        section,
        runs,
        upstream,
      };
  }, [id, draftParameters, tab, section, session.mode, runs, upstream]);
  useEffect(() => {
    if (!id || !node) return;
    let alive = true;
    if (stages.source === "synthetic") {
      const output = (demoPanes as Record<string, PaneResponse>)[id];
      const source = node.io.takes.noun === "settings"
        ? id === "validate-config" ? undefined : "validate-config"
        : upstream ||
        registry.nodes.find((n) => n.id === id)?.io.source ||
        registry.edges.find(
          (e) =>
            e.target === id &&
            !e.sub &&
            registry.nodes.find((n) => n.id === e.source)?.variant !==
              "trigger",
        )?.source;
      const input = (demoPanes as Record<string, PaneResponse>)[
        id === "review" ? "review" : source ?? "validate-config"
      ];
      setInput({
        ...input,
        node: id,
        side: "input",
        upstream: source ? [source] : [],
      });
      setOutput(output);
      setLoading(false);
      return;
    }
    if (session.mode === "replay") {
      const unavailable: PaneResponse = {
        node: id,
        side: "input",
        total: 0,
        offset: 0,
        columns: [],
        rows: [],
        config_hash: "v1",
        status: "unavailable",
      };
      setInput(unavailable);
      setOutput({ ...unavailable, side: "output" });
      setLoading(false);
      return;
    }
    setLoading(true);
    void Promise.all(
      (["input", "output"] as const).map((side) => {
        const q = new URLSearchParams({
          ...queries[side],
          ...(runs[side] ? { run: runs[side] } : {}),
          ...(side === "input" && upstream ? { upstream } : {}),
        });
        return api(`nodes/${id}/${side}?${q.toString()}`, validPaneResponse);
      }),
    )
      .then(([a, b]) => {
        if (alive) {
          setInput(a);
          setOutput(b);
        }
      })
      .catch(() => {
        if (alive) {
          setInput(null);
          setOutput(null);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [
    id,
    session.mode,
    session.trace,
    runs,
    upstream,
    queries,
    active,
    selectedStage?.last_run,
    selectedStage?.status,
    selectedStage?.out_count,
    retry,
    stages.source,
    registry,
  ]);
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") session.set({ panel: null });
      if (event.altKey && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
        const all = registry.nodes;
        const at = all.findIndex((n) => n.id === id);
        session.set({
          panel:
            all[
              (at + (event.key === "ArrowRight" ? 1 : all.length - 1)) %
                all.length
            ].id,
        });
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [id, registry, session]);
  useEffect(() => {
    if (!id || session.mode === "replay") {
      setSettings([]);
      return;
    }
    let alive = true;
    setSettings([]);
    void api("settings", validSettingsResponse)
      .then((data) => {
        if (alive) setSettings(data.nodes[id] ?? []);
      })
      .catch(() => {
        if (alive) setSettings([]);
      });
    return () => {
      alive = false;
    };
  }, [id, session.mode]);
  function setValue(name: string, value: Parameters[string]) {
    if (name.startsWith("config:"))
      session.set({
        overrides: { ...session.overrides, [name.slice(7)]: value },
      });
    setParameters((old) => ({
      ...old,
      [name]: value,
      ...(name.startsWith("config:")
        ? {
            set: [
              ...((old.set ?? []) as string[]).filter(
                (part) => !part.startsWith(name.slice(7) + "="),
              ),
              name.slice(7) + "=" + JSON.stringify(value),
            ],
          }
        : {}),
    }));
  }
  const supported = node?.command?.length && node.capability === "executable";
  const controls: CLIControl[] = [
    ...(node?.controls ?? []),
    ...settings.map((s) => ({
      name: "config:" + s.path,
      flags: [],
      kind: s.kind,
      default: s.value,
      choices: null,
      multiple: s.multiple ?? false,
      help: "",
    })),
  ];
  const settingsSupported = true;
  const fields = controls.filter(
    (c) =>
      c.kind !== "help" &&
      c.name !== "set" &&
      (tab === "settings"
        ? c.name.startsWith("config:")
        : !c.name.startsWith("config:")),
  );
  const at = registry.nodes.findIndex((n) => n.id === id);
  return (
    <AnimatePresence>
      {node && (
        <motion.div
          className="panel-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) session.set({ panel: null });
          }}
        >
          <motion.div
            data-node={id}
            role="dialog"
            aria-modal="true"
            aria-label={label(node.label_key)}
            className="node-panel"
            initial={{ opacity: 0, scale: 0.94, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 340, damping: 32 }}
          >
            <DataPane
              key={id + ":input"}
              badge={badge}
              registry={registry}
              stages={stages}
              timestamp={timestamp}
              retry={() => setRetry((n) => n + 1)}
              nodeId={id ?? copy.empty}
              side="input"
              upstreamValue={upstream}
              data={input}
              other={output}
              loading={loading}
              onRun={(run) => setRuns((old) => ({ ...old, input: run }))}
              onUpstream={setUpstream}
              onQuery={(query) =>
                setQueries((old) => ({ ...old, input: query }))
              }
            />
            <section className="parameters-pane">
              <div className="node-panel-header">
                <Icon name={node.icon} size={24} />
                <span>{label(node.label_key)}</span>
                <Button
                  icon="flask"
                  title={copy.execute}
                  className="primary"
                  disabled={!supported || active || session.mode === "replay"}
                  onClick={() =>
                    onExecute(
                      (node.command ?? []).join("-"),
                      parameters,
                      runs.input || input?.runs?.[0],
                    )
                  }
                >
                  {copy.execute}
                </Button>
              </div>
              <nav className="panel-tabs" aria-label={copy.parameters}>
                <button
                  className={tab === "parameters" ? "active" : ""}
                  onClick={() => setTab("parameters")}
                >
                  {copy.parameters}
                </button>
                {settingsSupported && (
                  <button
                    className={tab === "settings" ? "active" : ""}
                    onClick={() => setTab("settings")}
                  >
                    {copy.settings}
                  </button>
                )}
                <Button
                  icon="export"
                  title={copy.docs}
                  className="docs-button"
                  onClick={() => session.set({ help: 0 })}
                >
                  {copy.docs}
                </Button>
              </nav>
              <div className="parameters-body">
                <div className="segmented">
                  <button
                    className={session.mode === "live" ? "active" : ""}
                    onClick={() => session.set({ mode: "live" })}
                  >
                    {copy.live}
                  </button>
                  <button
                    className={session.mode === "replay" ? "active" : ""}
                    onClick={() =>
                      session.set({ mode: "replay", trace: false })
                    }
                  >
                    {copy.replay}
                  </button>
                </div>
                {!!output?.runs?.length && (
                  <label className="field-control">
                    {copy.runs}
                    <select
                      aria-label={copy.runs}
                      value={runs.output}
                      onChange={(e) =>
                        setRuns((old) => ({ ...old, output: e.target.value }))
                      }
                    >
                      <option value="">{"Latest run"}</option>
                      {output.runs.map((run, i) => (
                        <option key={run} value={run}>
                          {"Run " + (i + 1)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {fields.length > 0 && (
                  <div className="parameter-section">
                    <h3>
                      {tab === "settings" ? copy.settings : copy.parameters}
                    </h3>
                    {fields.map((control) => (
                      <div
                        className="field-control"
                        data-flag={control.name}
                        key={control.name}
                      >
                        <label htmlFor={`${id}-${control.name}`}>
                          {control.name === "config"
                            ? "Settings file"
                            : fieldLabel(
                                control.name
                                  .split(".")
                                  .pop()
                                  ?.replace("config:", "") ?? control.name,
                              )}
                        </label>
                        {control.kind === "help" ? (
                          <Button
                            id={`${id}-${control.name}`}
                            icon="help"
                            title={copy.help}
                            onClick={() => session.set({ help: 13 })}
                          />
                        ) : control.kind === "boolean" ? (
                          <input
                            id={`${id}-${control.name}`}
                            role="switch"
                            type="checkbox"
                            checked={Boolean(
                              parameters[control.name] ?? control.default,
                            )}
                            onChange={(e) =>
                              setValue(control.name, e.target.checked)
                            }
                          />
                        ) : control.multiple ? (
                          <OrderedList
                            value={
                              (parameters[control.name] ??
                                control.default ??
                                []) as string[]
                            }
                            onChange={(value) => setValue(control.name, value)}
                            name={`${id}-${control.name}`}
                          />
                        ) : control.choices ? (
                          <select
                            id={`${id}-${control.name}`}
                            value={String(
                              parameters[control.name] ?? control.default ?? "",
                            )}
                            onChange={(e) =>
                              setValue(control.name, e.target.value)
                            }
                          >
                            {control.choices.map((value) => (
                              <option key={value}>{value}</option>
                            ))}
                          </select>
                        ) : (
                          <div className="input-copy">
                            <input
                              id={`${id}-${control.name}`}
                              type={
                                ["number", "integer"].includes(control.kind)
                                  ? "number"
                                  : "text"
                              }
                              readOnly={control.name === "config"}
                              value={String(
                                parameters[control.name] ??
                                  control.default ??
                                  "",
                              )}
                              placeholder={copy.unknown}
                              onChange={(e) =>
                                setValue(
                                  control.name,
                                  control.kind === "integer" ||
                                    control.kind === "number"
                                    ? Number(e.target.value)
                                    : e.target.value,
                                )
                              }
                            />
                            {control.name === "config" && (
                              <Button
                                icon="copy"
                                title={copy.copy}
                                onClick={() =>
                                  void navigator.clipboard?.writeText(
                                    String(control.default),
                                  )
                                }
                              />
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {!fields.length && (
                  <div className="empty-control">
                    {"No parameters for this step"}
                  </div>
                )}
                {node.id === "model" && (
                  <Button
                    icon="flask"
                    title={label("model-bakeoff")}
                    onClick={() => session.set({ panel: "model-bakeoff" })}
                  />
                )}
              </div>
              <div className="panel-footer">
                <Button
                  icon="previous"
                  title={copy.previous}
                  onClick={() =>
                    session.set({
                      panel:
                        registry.nodes[
                          (at + registry.nodes.length - 1) %
                            registry.nodes.length
                        ].id,
                    })
                  }
                />
                <span>{node.io.takes.noun + " → " + node.io.gives.noun}</span>
                <Button
                  icon="next"
                  title={copy.next}
                  onClick={() =>
                    session.set({
                      panel:
                        registry.nodes[(at + 1) % registry.nodes.length].id,
                    })
                  }
                />
              </div>
            </section>
            <DataPane
              key={id + ":output"}
              badge={badge}
              registry={registry}
              stages={stages}
              timestamp={timestamp}
              retry={() => setRetry((n) => n + 1)}
              nodeId={id ?? copy.empty}
              side="output"
              data={output}
              other={input}
              loading={loading}
              onRun={(run) => setRuns((old) => ({ ...old, output: run }))}
              onUpstream={() => {}}
              onQuery={(query) =>
                setQueries((old) => ({ ...old, output: query }))
              }
            />
            <Button
              icon="close"
              title={copy.close}
              className="close-panel"
              onClick={() => session.set({ panel: null })}
            />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
function OrderedList({
  value,
  onChange,
  name,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  name: string;
}) {
  return (
    <div>
      <Reorder.Group
        axis="y"
        values={value}
        onReorder={onChange}
        aria-label={copy.reorder}
      >
        {value.map((item, i) => (
          <Reorder.Item value={item} key={item + i}>
            <Icon name="config" size={14} />
            <input
              aria-label={name}
              value={item}
              onChange={(e) =>
                onChange(
                  value.map((old, index) =>
                    index === i ? e.target.value : old,
                  ),
                )
              }
            />
            <Button
              icon="close"
              title={copy.remove}
              onClick={() => onChange(value.filter((_, index) => index !== i))}
            />
          </Reorder.Item>
        ))}
      </Reorder.Group>
      {!value.length && <div className="empty-control">{copy.empty}</div>}
      <button className="add-item" onClick={() => onChange([...value, ""])}>
        {glyphs.plus} {copy.add}
      </button>
    </div>
  );
}
