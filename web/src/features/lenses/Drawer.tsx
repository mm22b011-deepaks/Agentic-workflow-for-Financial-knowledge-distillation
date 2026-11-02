import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  PieChart,
  Pie,
  Cell,
  Tooltip,
} from "recharts";
import { copy, fieldLabel, label } from "../../copy";
import { Icon } from "../../shared/Icon";
import { Button } from "../../shared/Button";
import { useSession } from "../../shared/state";
import type { MetricSnapshot } from "../../MetricSnapshot";
import type { StageSnapshot } from "../../StageSnapshot";
import type { ScheduleSnapshot } from "../../ScheduleSnapshot";
const chartNames = Object.keys(copy.charts) as (keyof typeof copy.charts)[];
const colours = [
  "var(--teal)",
  "var(--accent)",
  "var(--muted)",
  "var(--green)",
];
export function Drawer({
  coverage,
  cost,
  bakeoff,
  plan,
  stages,
  schedule,
}: {
  coverage: MetricSnapshot;
  cost: MetricSnapshot;
  bakeoff: MetricSnapshot;
  plan: MetricSnapshot;
  stages: StageSnapshot;
  schedule: ScheduleSnapshot | null;
}) {
  const session = useSession();
  const [chart, setChart] = useState<keyof typeof copy.charts>("funnel");
  const metrics = cost.metrics ?? {};
  const series = coverage.series ?? [];
  let points: {
    name: string;
    value: number | null | undefined;
    stack?: string;
  }[] = [];
  if (chart === "funnel")
    points = [
      "cohort",
      "discover",
      "ingest",
      "extract",
      "validate",
      "aggregate",
    ].map((name) => ({
      name: label(name),
      value: stages.nodes.find((n) => n.id === name)?.out_count,
    }));
  if (["reasons", "fields"].includes(chart))
    points = series
      .filter((p) => p.category === chart)
      .map((p) => ({ name: fieldLabel(p.metric ?? ""), value: p.value }));
  if (chart === "cohort")
    points = series
      .filter((p) => p.category === "cohort")
      .map((p) => ({ name: p.season ?? "", value: p.value, stack: p.metric }));
  if (chart === "tokens")
    points = ["prompt", "reasoning", "content"].map((name) => ({
      name: label(name),
      value: metrics[name],
    }));
  if (chart === "latency")
    points = ["p50", "p95"].map((name) => ({ name, value: metrics[name] }));
  if (chart === "cache")
    points = [
      { name: copy.cache, value: metrics.cache },
      { name: copy.requests, value: metrics.calls },
    ];
  if (chart === "calls")
    points = [{ name: copy.documents, value: metrics.calls_per_document }];
  if (chart === "quota")
    points = [
      { name: copy.requests, value: metrics.used },
      {
        name: copy.limit,
        value:
          metrics.limit != null && metrics.used != null
            ? metrics.limit - metrics.used
            : null,
      },
    ];
  if (chart === "bakeoff")
    points = (bakeoff.series ?? [])
      .filter((p) => p.season === "parse_success_rate")
      .map((p) => ({ name: p.metric ?? "", value: p.value }));
  if (chart === "plan")
    points = (plan.series ?? []).map((p) => ({
      name: fieldLabel(p.metric ?? ""),
      value: p.value,
    }));
  const cohortSeasons = [
    ...new Set(
      series.filter((p) => p.category === "cohort").map((p) => p.season ?? ""),
    ),
  ];
  const cohortRows = cohortSeasons.map((season) =>
    Object.fromEntries([
      ["name", season],
      ...["downloaded", "no_release", "failed", "unvisited"].map((outcome) => [
        outcome,
        series.find(
          (p) =>
            p.category === "cohort" &&
            p.season === season &&
            p.metric === outcome,
        )?.value ?? null,
      ]),
    ]),
  );
  const measured = points.filter((p) => p.value != null);
  const unit =
    chart === "latency"
      ? copy.seconds
      : chart === "tokens"
        ? copy.tokens
        : ["quota", "calls", "plan"].includes(chart)
          ? copy.requests
          : chart === "fields" || chart === "coverage"
            ? copy.percent
            : copy.documents;
  return (
    <>
      <Button
        icon="chart"
        title={copy.chart}
        className={`drawer-toggle ${session.drawer ? "active" : ""}`}
        onClick={() => session.set({ drawer: !session.drawer })}
      />
      <AnimatePresence>
        {session.drawer && (
          <motion.aside
            className="lens-drawer"
            aria-label={copy.lens}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            data-testid="lens-view"
          >
            <div className="chart-controls">
              <select
                aria-label={copy.chart}
                value={chart}
                onChange={(e) => setChart(e.target.value as typeof chart)}
              >
                {chartNames.map((name) => (
                  <option key={name} value={name}>
                    {copy.charts[name]}
                  </option>
                ))}
              </select>
              <small>{unit}</small>
              <span
                className={`status-dot ${measured.length ? "done" : "idle"}`}
              />
              <Button
                icon="close"
                title={copy.close}
                onClick={() => session.set({ drawer: false })}
              />
            </div>
            <div className="chart-layout">
              <div className="chart-body" data-testid={`chart-${chart}`}>
                {chart === "coverage" ? (
                  <div
                    className="heat-grid"
                    role="img"
                    aria-label={copy.quality}
                  >
                    {series
                      .filter((p) => p.category === "coverage")
                      .map((p, i) => (
                        <div
                          key={i}
                          className={
                            p.value == null
                              ? "hollow"
                              : p.status === "ok"
                                ? "pass"
                                : "loss"
                          }
                          title={`${fieldLabel(p.metric ?? "")} ${p.season ?? ""} ${p.value == null ? copy.unknown : Math.round(p.value * 100)}`}
                        >
                          <span>
                            {p.value == null
                              ? copy.unknown
                              : Math.round(p.value * 100)}
                          </span>
                          <i
                            style={{
                              bottom: `${Math.min(100, ((coverage.metrics?.minimum_observations ?? coverage.metrics?.gate ?? 0) / (p.denominator || 1)) * 100)}%`,
                              visibility: p.denominator ? "visible" : "hidden",
                            }}
                          />
                        </div>
                      ))}
                  </div>
                ) : !measured.length ? (
                  <span className="chart-empty">{copy.unknown}</span>
                ) : chart === "bakeoff" ? (
                  <div className="bakeoff-grid">
                    {(bakeoff.series ?? []).slice(0, 8).map((point, i) => (
                      <span
                        key={i}
                        title={`${point.metric} ${point.season}`}
                        className={point.value == null ? "hollow" : ""}
                      >
                        {point.value == null
                          ? copy.unknown
                          : Number(point.value.toFixed(2))}
                      </span>
                    ))}
                  </div>
                ) : ["quota", "cache"].includes(chart) ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={measured}
                        dataKey="value"
                        innerRadius="60%"
                        outerRadius="82%"
                        stroke="none"
                        startAngle={90}
                        endAngle={-270}
                      >
                        {measured.map((_, i) => (
                          <Cell key={i} fill={colours[i % colours.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value) => [value, unit]} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : chart === "tokens" ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={[metrics]}
                      layout="vertical"
                      margin={{ left: 8, right: 8, top: 32, bottom: 32 }}
                    >
                      <XAxis type="number" hide />
                      <YAxis type="category" hide />
                      <Tooltip
                        content={({ payload }) => (
                          <div className="chart-tooltip">
                            {payload?.map((p, i) => (
                              <span
                                key={i}
                                style={{ color: colours[i % colours.length] }}
                              >
                                {p.value ?? copy.unknown}
                              </span>
                            ))}
                            <small>{unit}</small>
                          </div>
                        )}
                      />
                      {["prompt", "reasoning", "content"].map((name, i) => (
                        <Bar
                          key={name}
                          dataKey={name}
                          stackId="tokens"
                          fill={colours[i]}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                ) : chart === "cohort" ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={cohortRows}>
                      <XAxis dataKey="name" hide />
                      <YAxis hide />
                      <Tooltip
                        content={({ payload }) => (
                          <div className="chart-tooltip">
                            {payload?.map((p, i) => (
                              <span
                                key={i}
                                style={{ color: colours[i % colours.length] }}
                              >
                                {p.value ?? copy.unknown}
                              </span>
                            ))}
                            <small>{unit}</small>
                          </div>
                        )}
                      />
                      {["downloaded", "no_release", "failed", "unvisited"].map(
                        (name, i) => (
                          <Bar
                            key={name}
                            dataKey={name}
                            stackId="outcomes"
                            fill={colours[i]}
                          />
                        ),
                      )}
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={measured}
                      layout={
                        chart === "funnel" || chart === "reasons"
                          ? "vertical"
                          : "horizontal"
                      }
                      margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
                      accessibilityLayer
                    >
                      <XAxis
                        type={
                          chart === "funnel" || chart === "reasons"
                            ? "number"
                            : "category"
                        }
                        dataKey={
                          chart === "funnel" || chart === "reasons"
                            ? undefined
                            : "name"
                        }
                        hide
                      />
                      <YAxis
                        type={
                          chart === "funnel" || chart === "reasons"
                            ? "category"
                            : "number"
                        }
                        dataKey={
                          chart === "funnel" || chart === "reasons"
                            ? "name"
                            : undefined
                        }
                        hide
                      />
                      <Tooltip formatter={(value) => [value, unit]} />
                      <Bar dataKey="value" radius={4} fill="var(--teal)">
                        {measured.map((_, i) => (
                          <Cell key={i} fill={colours[i % colours.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
              <div className="opportunities">
                {(
                  ["truncations", "reasoning", "calls_per_document"] as const
                ).map((name, i) => (
                  <button
                    key={name}
                    title={fieldLabel(name)}
                    className={metrics[name] == null ? "hollow" : ""}
                    onClick={() => session.set({ help: i === 2 ? 11 : 3 })}
                  >
                    <Icon name={["extract", "model", "limiter"][i]} />
                    <span>
                      {metrics[name] == null
                        ? copy.unknown
                        : Number(metrics[name].toFixed(1))}
                    </span>
                    <i className="status-dot" />
                  </button>
                ))}
              </div>
            </div>
            <div className="schedule-strip" aria-label={copy.schedule}>
              <Icon name="calendar" />
              <div className="calendar-days">
                {schedule?.days.map((day) => (
                  <div
                    className={`calendar-day ${day.today ? "today" : ""}`}
                    key={day.utc_day}
                    title={`${day.utc_day} ${day.used}/${day.budget}`}
                  >
                    <div className="day-track">
                      <i
                        style={{
                          height: `${Math.min(100, (day.used / Math.max(1, day.budget)) * 100)}%`,
                        }}
                      />
                      <b
                        style={{
                          height: `${Math.min(100, (day.planned_requests / Math.max(1, day.budget)) * 100)}%`,
                        }}
                      />
                    </div>
                    <small>{day.utc_day.slice(8)}</small>
                  </div>
                )) ?? <span>{copy.unknown}</span>}
              </div>
              <span className="next-time">
                <Icon name="clock" />
                {schedule?.next_run_utc.slice(11, 16) ?? copy.unknown}
              </span>
              <div className="task-chips">
                {["done", "due", "blocked", "human"].map((status) => (
                  <span
                    key={status}
                    className={`task-chip ${status}`}
                    title={status === "human" ? copy.human : label(status)}
                  >
                    <Icon
                      name={
                        status === "done"
                          ? "check"
                          : status === "due"
                            ? "run"
                            : status === "human"
                              ? "privacy"
                              : "question"
                      }
                      size={14}
                    />
                    {schedule?.tasks.filter((t) =>
                      status === "human"
                        ? t.human
                        : t.status === status && !t.human,
                    ).length ?? copy.unknown}
                  </span>
                ))}
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
