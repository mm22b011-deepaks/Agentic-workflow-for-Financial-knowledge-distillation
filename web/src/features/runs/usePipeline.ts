import { useCallback, useEffect, useRef, useState } from "react";
import registryData from "../../registry.json";
import rawFixture from "../../index-fixture.json";
import rawDemo from "../../demo.json";
import {
  validCanvasRegistry,
  validIndexSnapshot,
  validMetricSnapshot,
  validRunEvent,
  validRunStatus,
  validScheduleSnapshot,
  validSessionResponse,
  validStageSnapshot,
} from "../../validators.js";
import { api, apiList, setToken } from "../../shared/api";
import { useSession } from "../../shared/state";
import { copy } from "../../copy";
import type { CanvasRegistry } from "../../CanvasRegistry";
import type { IndexSnapshot } from "../../IndexSnapshot";
import type { MetricSnapshot } from "../../MetricSnapshot";
import type { RunStatus } from "../../RunStatus";
import type { RunEvent } from "../../RunEvent";
import type { StageSnapshot } from "../../StageSnapshot";
import type { ScheduleSnapshot } from "../../ScheduleSnapshot";
if (
  !validCanvasRegistry(registryData) ||
  !validIndexSnapshot(rawFixture) ||
  !validStageSnapshot(rawDemo)
)
  throw Error(copy.rejected);
const fixture: IndexSnapshot = rawFixture;
const demoData: StageSnapshot = rawDemo;
export const registry: CanvasRegistry = registryData;
const empty: MetricSnapshot = { metrics: {}, series: [] };
export function usePipeline() {
  const session = useSession();
  const [runs, setRuns] = useState<RunStatus[]>([]);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [index, setIndex] = useState<IndexSnapshot>(fixture);
  const [replay, setReplay] = useState<IndexSnapshot>(fixture);
  const [stages, setStages] = useState<StageSnapshot>(demoData);
  const [coverage, setCoverage] = useState<MetricSnapshot>(empty);
  const [cost, setCost] = useState<MetricSnapshot>(empty);
  const [bakeoff, setBakeoff] = useState<MetricSnapshot>(empty);
  const [plan, setPlan] = useState<MetricSnapshot>(empty);
  const [schedule, setSchedule] = useState<ScheduleSnapshot | null>(null);
  const [traceAvailable, setTraceAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const refreshing = useRef(false);
  const revision = useRef(0);
  const refresh = useCallback(async () => {
    if (useSession.getState().mode === "replay" || refreshing.current) return;
    refreshing.current = true;
    const started = revision.current;
    try {
      const token = await api("session", validSessionResponse);
      setToken(token.csrf_token);
      setTraceAvailable(token.internal_trace_available);
      const remote = await api("registry", validCanvasRegistry);
      if (JSON.stringify(remote) !== JSON.stringify(registryData))
        throw Error(copy.drift);
      const [jobs, snapshot, stageData, q, c, b, p, s] = await Promise.all([
        apiList("runs", validRunStatus).then((jobs) => {
          if (
            started === revision.current &&
            useSession.getState().mode === "live"
          )
            setRuns(jobs);
          return jobs;
        }),
        api("index", validIndexSnapshot),
        api("stages", validStageSnapshot),
        api("coverage", validMetricSnapshot),
        api("cost", validMetricSnapshot),
        api("bakeoff", validMetricSnapshot),
        api("plan", validMetricSnapshot),
        api("schedule", validScheduleSnapshot),
      ]);
      if (
        useSession.getState().mode === "replay" ||
        started !== revision.current
      )
        return;
      setRuns(jobs);
      const real =
        snapshot.source !== "synthetic" &&
        (snapshot.status === "available" ||
          stageData.nodes.some(
            (node) =>
              ["ingest", "extract", "download"].includes(node.id) &&
              (node.out_count ?? 0) > 0,
          ));
      setIndex(
        real ? snapshot : snapshot.status === "available" ? snapshot : fixture,
      );
      setStages(real ? stageData : demoData);
      setCoverage(q);
      setCost(c);
      setBakeoff(b);
      setPlan(p);
      setSchedule(s);
      if (jobs[0])
        setEvents(
          await apiList("runs/" + jobs[0].id + "/events", validRunEvent),
        );
    } catch (error) {
      useSession.getState().set({
        error: error instanceof Error ? error.message : copy.unavailable,
      });
    } finally {
      refreshing.current = false;
    }
  }, []);
  useEffect(() => {
    if (session.mode === "replay") {
      setIndex(replay);
      setStages(demoData);
      setCoverage(empty);
      setCost(empty);
      setBakeoff(empty);
      setPlan(empty);
      setSchedule(null);
      setEvents([]);
      setRuns([]);
      setTraceAvailable(false);
      return;
    }
    void refresh();
    const interval = window.setInterval(() => void refresh(), 4000);
    return () => clearInterval(interval);
  }, [session.mode, refresh, replay]);
  function loadReplay(value: unknown) {
    if (!validIndexSnapshot(value)) {
      session.set({ error: copy.rejected });
      return;
    }
    setReplay(value);
    session.set({ mode: "replay", trace: false, error: "" });
  }
  const active = runs.find(
    (r) => r.status === "running" || r.status === "queued",
  );
  async function mutate(path: string, body: unknown) {
    if (useSession.getState().mode === "replay") return;
    setBusy(true);
    revision.current++;
    try {
      const run = await api(path, validRunStatus, body);
      if (useSession.getState().mode === "live")
        setRuns((old) => [run, ...old.filter((item) => item.id !== run.id)]);
      await refresh();
    } catch (error) {
      session.set({
        error: error instanceof Error ? error.message : copy.unavailable,
      });
    } finally {
      setBusy(false);
    }
  }
  function execute(
    command: string,
    parameters: Record<string, string | number | boolean | string[]> = {},
    upstream?: string,
  ) {
    if (session.mode === "replay") return;
    void mutate("runs", {
      version: "v1",
      workflow_id: "command",
      submission_id: crypto.randomUUID(),
      command_id: command,
      node_id:
        command === "run-all" || command === "demo" ? undefined : command,
      parameters: {
        ...Object.fromEntries(
          Object.entries(parameters).filter(
            ([key]) => !key.startsWith("config:"),
          ),
        ),
        set: [
          ...Object.entries(session.overrides).map(
            ([key, value]) => key + "=" + JSON.stringify(value),
          ),
          ...((parameters.set ?? []) as string[]),
        ],
      },
      upstream_run_id: upstream,
    });
  }
  function cancel() {
    if (active) void mutate("runs/" + active.id + "/cancel", {});
  }
  function resume() {
    const interrupted = runs.find((r) =>
      ["interrupted", "cancelled", "failed"].includes(r.status),
    );
    if (interrupted) void mutate("runs/" + interrupted.id + "/resume", {});
  }
  return {
    registry,
    runs,
    events,
    index,
    stages,
    coverage,
    cost,
    bakeoff,
    plan,
    schedule,
    traceAvailable,
    busy,
    active,
    execute,
    cancel,
    resume,
    refresh,
    loadReplay,
  };
}
