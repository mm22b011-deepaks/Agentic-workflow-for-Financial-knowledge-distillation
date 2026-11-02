import { StrictMode, useEffect, useRef, useState, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "framer-motion";
import { Canvas } from "./features/canvas/Canvas";
import { Panel, inspectionState } from "./features/inspector/Panel";
const Drawer = lazy(() =>
  import("./features/lenses/Drawer").then((module) => ({
    default: module.Drawer,
  })),
);
import { Help, Tour } from "./features/help/Help";
import { usePipeline } from "./features/runs/usePipeline";
import { usePreferences, useSession } from "./shared/state";
import { Button } from "./shared/Button";
import { Icon } from "./shared/Icon";
import { copy, label } from "./copy";
import { api } from "./shared/api";
import {
  validIndexSnapshot,
  validKPIKnowledgeBase,
  validPaneResponse,
} from "./validators.js";
import "./style.css";
function App() {
  const pipeline = usePipeline();
  const session = useSession();
  const preferences = usePreferences();
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [confirmation, setConfirmation] = useState<null | (() => void)>(null);
  const paletteInput = useRef<HTMLInputElement>(null);
  function download(value: unknown, name: string) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function loadReplay(file?: File) {
    if (!file) return;
    try {
      if (file.size > 2000000) throw Error();
      pipeline.loadReplay(JSON.parse(await file.text()));
    } catch {
      session.set({ error: copy.rejected });
    }
  }
  async function exportKpis() {
    try {
      download(await api("kpis", validKPIKnowledgeBase), copy.kpiFile);
    } catch {
      session.set({ error: copy.unavailable });
    }
  }
  async function runSelected() {
    const node = pipeline.registry.nodes.find(
      (item) => item.id === session.selected,
    );
    if (!node || node.capability !== "executable" || session.mode === "replay")
      return;
    try {
      const saved = inspectionState(node.id);
      const input = await api("nodes/" + node.id + "/input", validPaneResponse);
      execute(
        (node.command ?? []).join("-"),
        saved?.parameters ?? {},
        saved?.runs?.input || input.runs?.[0],
      );
    } catch {
      session.set({ error: copy.unavailable });
    }
  }
  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    document.title = copy.app;
  }, [preferences.theme]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      const typing = !!(event.target as HTMLElement).closest(
        "input,textarea,select",
      );
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        session.set({ panel: null, help: null });
        setPalette((old) => !old);
      }
      if (!typing && event.key === "?")
        session.set({ help: session.help === null ? -1 : null });
      if (event.key === "Escape") {
        setPalette(false);
        setConfirmation(null);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [session]);
  useEffect(() => {
    if (palette) paletteInput.current?.focus();
  }, [palette]);
  useEffect(() => {
    const target = document.querySelector<HTMLElement>(
      session.help !== null
        ? ".help-drawer"
        : palette
          ? ".command-palette"
          : confirmation
            ? ".confirm-dialog"
            : session.panel
              ? ".node-panel"
              : "[data-no-dialog]",
    );
    if (!target) return;
    const before = document.activeElement as HTMLElement | null;
    const focusable = () =>
      [
        ...target.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select,textarea,summary,[tabindex="0"]',
        ),
      ].filter((element) => element.getBoundingClientRect().width > 0);
    window.setTimeout(() => focusable()[0]?.focus(), 100);
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      if (event.shiftKey && document.activeElement === items[0]) {
        event.preventDefault();
        items.at(-1)?.focus();
      } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
        event.preventDefault();
        items[0].focus();
      }
    };
    target.addEventListener("keydown", trap);
    return () => {
      target.removeEventListener("keydown", trap);
      if (before?.isConnected) before.focus();
    };
  }, [session.panel, session.help, palette, confirmation]);
  const selected = pipeline.registry.nodes.find(
    (n) => n.id === session.selected,
  );
  const disabled =
    pipeline.busy || !!pipeline.active || session.mode === "replay";
  function execute(
    command: string,
    parameters: Record<string, string | number | boolean | string[]> = {},
    upstream?: string,
  ) {
    if (command === "rebuild-index" && parameters.force) {
      setConfirmation(
        () => () => pipeline.execute(command, parameters, upstream),
      );
      return;
    }
    pipeline.execute(command, parameters, upstream);
  }
  const choices = pipeline.registry.nodes.filter((n) =>
    label(n.label_key).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <main>
      <div
        className="workstation"
        inert={
          !!session.panel || session.help !== null || palette || !!confirmation
        }
      >
        <header className="topbar">
          <div className="pipeline-badge">
            <i className="status-dot done" />
            <span>
              {pipeline.index.source === "synthetic"
                ? copy.demo
                : copy.production}
            </span>
          </div>
          <div className="toolbar" role="toolbar" aria-label={copy.runAll}>
            <Button
              icon="run"
              title={copy.runAll}
              className="primary"
              disabled={disabled}
              onClick={() => execute("run-all")}
            />
            <Button
              icon="flask"
              title={copy.runSelected}
              disabled={disabled || selected?.capability !== "executable"}
              onClick={() => void runSelected()}
            />
            <Button
              icon="stop"
              title={copy.stop}
              disabled={!pipeline.active || session.mode === "replay"}
              onClick={pipeline.cancel}
            />
            <Button
              icon="resume"
              title={copy.resume}
              disabled={
                disabled ||
                !pipeline.runs.some((r) =>
                  ["failed", "cancelled", "interrupted"].includes(r.status),
                )
              }
              onClick={pipeline.resume}
            />
            <i className="toolbar-divider" />
            <Button
              icon="lens"
              title={copy.lens}
              className={preferences.lens !== "flow" ? "active" : ""}
              onClick={() =>
                preferences.set({
                  lens:
                    preferences.lens === "flow"
                      ? "quality"
                      : preferences.lens === "quality"
                        ? "cost"
                        : "flow",
                })
              }
            />
            <Button
              icon="privacy"
              title={copy.privacy}
              className={session.trace ? "active" : ""}
              disabled={!pipeline.traceAvailable || session.mode === "replay"}
              onClick={() => session.set({ trace: !session.trace })}
            />
            <Button
              icon="theme"
              title={copy.theme}
              onClick={() =>
                preferences.set({
                  theme: preferences.theme === "dark" ? "light" : "dark",
                })
              }
            />
            <Button
              icon="help"
              title={copy.help}
              onClick={() => session.set({ help: -1 })}
            />
          </div>
          <div className="mode-switch">
            <button
              className={session.mode === "live" ? "active" : ""}
              onClick={() => session.set({ mode: "live" })}
            >
              {copy.live}
            </button>
            <button
              className={session.mode === "replay" ? "active" : ""}
              onClick={() =>
                session.set({ mode: "replay", trace: false, error: "" })
              }
            >
              {copy.replay}
            </button>
            {session.mode === "replay" && (
              <label className="icon-upload" title={copy.importReplay}>
                <Icon name="import" />
                <input
                  type="file"
                  accept="application/json"
                  aria-label={copy.importReplay}
                  onChange={(event) => void loadReplay(event.target.files?.[0])}
                />
              </label>
            )}
          </div>
        </header>

        <Canvas
          registry={pipeline.registry}
          stages={pipeline.stages}
          active={!!pipeline.active || session.mode === "replay"}
          coverage={pipeline.coverage}
          cost={pipeline.cost}
        />
        <div className="public-exports">
          <Button
            icon="export"
            title={copy.exportIndex}
            onClick={() => {
              if (validIndexSnapshot(pipeline.index))
                download(pipeline.index, copy.indexFile);
              else session.set({ error: copy.rejected });
            }}
          />
          <Button
            icon="aggregate"
            title={copy.exportKpis}
            disabled={session.mode === "replay"}
            onClick={() => void exportKpis()}
          />
        </div>
        <div className="lens-badge" title={copy.lens}>
          <Icon
            name={
              preferences.lens === "flow"
                ? "run"
                : preferences.lens === "quality"
                  ? "validate"
                  : "limiter"
            }
          />
          <span>{copy[preferences.lens]}</span>
          <i className="status-dot" />
        </div>
        <Suspense fallback={null}>
          <Drawer {...pipeline} />
        </Suspense>
        <Tour />
      </div>
      {session.trace && (
        <div className="trace-banner" role="status">
          <Icon name="privacy" size={16} />
          {copy.trace}
        </div>
      )}
      <Panel
        registry={pipeline.registry}
        active={!!pipeline.active || pipeline.busy}
        onExecute={execute}
      />
      <Help />
      <AnimatePresence>
        {session.error && (
          <motion.button
            role="alert"
            className="error-chip"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            onClick={() => session.set({ error: "" })}
            title={session.error}
          >
            <Icon name="cross" />
            <span>{session.error}</span>
          </motion.button>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {palette && (
          <motion.div
            className="palette-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setPalette(false);
            }}
          >
            <section
              className="command-palette"
              role="dialog"
              aria-modal="true"
              aria-label={copy.palette}
            >
              <div>
                <Icon name="search" />
                <input
                  ref={paletteInput}
                  aria-label={copy.palette}
                  placeholder={copy.palette}
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                />
                <Button
                  icon="close"
                  title={copy.close}
                  onClick={() => setPalette(false)}
                />
              </div>
              {choices.slice(page * 6, page * 6 + 6).map((n) => (
                <button
                  data-command={n.id}
                  key={n.id}
                  onClick={() => {
                    preferences.set({
                      hidden: (preferences.hidden ?? []).filter(
                        (id) => id !== n.id,
                      ),
                    });
                    session.set({ selected: n.id, panel: n.id });
                    setPalette(false);
                  }}
                >
                  <Icon name={n.icon} />
                  {label(n.label_key)}
                  <span
                    className={`status-dot ${n.capability === "planned" ? "idle" : ""}`}
                  />
                </button>
              ))}
              <div className="pager">
                <Button
                  icon="previous"
                  title={copy.previous}
                  disabled={!page}
                  onClick={() => setPage(page - 1)}
                />
                <span>
                  {page + 1}/{Math.max(1, Math.ceil(choices.length / 6))}
                </span>
                <Button
                  icon="next"
                  title={copy.next}
                  disabled={(page + 1) * 6 >= choices.length}
                  onClick={() => setPage(page + 1)}
                />
              </div>
            </section>
          </motion.div>
        )}
      </AnimatePresence>
      {confirmation && (
        <div className="palette-backdrop">
          <section
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-label={copy.force}
          >
            <Icon name="cache" />
            <span>{copy.backup}</span>
            <strong>{copy.force}</strong>
            <button onClick={() => setConfirmation(null)}>{copy.cancel}</button>
            <button
              className="primary"
              onClick={() => {
                confirmation();
                setConfirmation(null);
              }}
            >
              {copy.confirm}
            </button>
          </section>
        </div>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
