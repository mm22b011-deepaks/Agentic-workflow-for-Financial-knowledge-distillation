import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  MiniMap,
  Handle,
  Position,
  BaseEdge,
  getBezierPath,
  useNodesState,
  useEdgesState,
  useReactFlow,
  MarkerType,
  type NodeProps,
  type EdgeProps,
  type Node,
  type Edge,
  type Connection,
  addEdge,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import { Icon } from "../../shared/Icon";
import { Button } from "../../shared/Button";
import { copy, label, glyphs } from "../../copy";
import { validate } from "../../shared/api";
import { usePreferences, useSession } from "../../shared/state";
import type { CanvasRegistry } from "../../CanvasRegistry";
import type { StageSnapshot } from "../../StageSnapshot";
import type { MetricSnapshot } from "../../MetricSnapshot";

type CanvasData = {
  definition: CanvasRegistry["nodes"][number];
  stage?: StageSnapshot["nodes"][number];
  lens: string;
  active: boolean;
  measure?: number | null;
  quota?: number | null;
};
type FlowNode = Node<CanvasData, "stage">;
function StageNode({ data, selected }: NodeProps<FlowNode>) {
  const { definition: n, stage, lens } = data;
  const count = stage?.out_count;
  const status =
    n.capability === "planned" ? "planned" : (stage?.status ?? "idle");
  const variant = n.variant;
  return (
    <div
      className={`workflow-node ${variant} ${status} ${selected ? "selected" : ""} lens-${lens}`}
      data-node={n.id}
    >
      {variant === "trigger" && (
        <Icon
          name="lightning"
          size={21}
          style={{ position: "absolute", left: -26, color: "var(--accent)" }}
        />
      )}
      {variant !== "trigger" && (
        <Handle
          type="target"
          id="in"
          position={variant === "sub" ? Position.Top : Position.Left}
          className="input-port"
        />
      )}
      <div
        className={`node-shape ${lens !== "flow" && data.measure == null ? "unmeasured" : ""}`}
        style={
          lens !== "flow" && data.measure != null
            ? {
                borderColor: `color-mix(in srgb, var(--teal) ${Math.round(data.measure * 100)}%, var(--red))`,
              }
            : undefined
        }
      >
        {n.id === "limiter" && lens === "cost" && (
          <svg
            className="quota-ring"
            viewBox="0 0 80 80"
            aria-label={copy.limit}
          >
            <circle cx="40" cy="40" r="37" />
            <circle
              cx="40"
              cy="40"
              r="37"
              strokeDasharray={`${(data.quota ?? 0) * 232.48} 232.48`}
              visibility={data.quota == null ? "hidden" : "visible"}
            />
          </svg>
        )}
        <Button
          icon="help"
          title={copy.info}
          className="node-info nodrag"
          onClick={(event) => {
            event.stopPropagation();
            useSession.getState().set({ help: n.help_question ?? 0 });
          }}
        />
        <Icon name={n.icon} size={variant === "sub" ? 26 : 32} />
        {n.capability !== "planned" && (
          <span
            className={`status-marker ${status}`}
            role="img"
            aria-label={label(status)}
          >
            {status === "done"
              ? glyphs.check
              : status === "error"
                ? glyphs.cross
                : status === "attention"
                  ? glyphs.question
                  : ""}
          </span>
        )}
      </div>
      <div className="flow-label">
        <span>{label(n.label_key)}</span>
        <small>{count == null ? copy.unknown : count.toLocaleString()}</small>
      </div>
      {variant === "branch" ? (
        <>
          <Handle
            type="source"
            position={Position.Right}
            id="true"
            style={{ top: "30%" }}
          />
          <Handle
            type="source"
            position={Position.Right}
            id="false"
            style={{ top: "70%" }}
          />
          <span className="branch-true">{copy.true}</span>
          <span className="branch-false">{copy.false}</span>
        </>
      ) : variant !== "sub" ? (
        <Handle type="source" id="out" position={Position.Right} />
      ) : null}
      {(n.subnodes ?? []).map((id, i) => (
        <span key={id}>
          <Handle
            id={id}
            type="source"
            position={Position.Bottom}
            className="diamond-port"
            style={{
              left: `${((i + 1) * 100) / ((n.subnodes ?? []).length + 1)}%`,
            }}
          />
          <span
            className="diamond-label"
            style={{
              left: `${((i + 1) * 100) / ((n.subnodes ?? []).length + 1)}%`,
            }}
          >
            {id === "model"
              ? copy.model
              : id === "limiter" || id === "rate"
                ? copy.limit
                : id === "sec"
                  ? copy.sec
                  : id === "kpi"
                    ? copy.kpi
                    : label(id)}
            {n.ports?.find((p) => p.id === id)?.required && (
              <b>{copy.required}</b>
            )}
          </span>
        </span>
      ))}
      {n.ports
        ?.filter((p) => p.direction === "in" && p.id !== "in")
        .map((p) => (
          <Handle
            key={p.id}
            id={p.id}
            type="target"
            position={Position.Left}
            style={{ top: "75%" }}
          />
        ))}
      {n.open_output && <span className="output-stub">{glyphs.plus}</span>}
    </div>
  );
}
function FlowEdge(props: EdgeProps) {
  const [path] = getBezierPath(props);
  const active = props.data?.active === true;
  return (
    <>
      <BaseEdge
        {...props}
        path={path}
        style={{
          stroke:
            props.data?.loss == null
              ? "var(--edge)"
              : `color-mix(in srgb, var(--red) ${Number(props.data.loss) * 100}%, var(--teal))`,
          strokeWidth: props.data?.sub
            ? 2
            : Math.min(6, 2 + Math.log10(Number(props.data?.volume ?? 1) + 1)),
          strokeDasharray: props.data?.sub ? "6 6" : undefined,
        }}
      />
      {active && (
        <circle r="3" fill="var(--accent)">
          <animateMotion dur="2s" repeatCount="indefinite" path={path} />
        </circle>
      )}
      {props.label != null && (
        <foreignObject
          x={(props.sourceX + props.targetX) / 2 - 18}
          y={(props.sourceY + props.targetY) / 2 - 14}
          width={36}
          height={25}
        >
          <span className="edge-number">{String(props.label)}</span>
        </foreignObject>
      )}
    </>
  );
}
const nodeTypes = { stage: StageNode };
const edgeTypes = { volume: FlowEdge };
export function validDAG(
  nodes: string[],
  edges: { source: string; target: string }[],
) {
  const seen = new Set<string>();
  for (let i = 0; i < nodes.length; i++) {
    const ready = nodes.filter(
      (n) =>
        !seen.has(n) &&
        edges.filter((e) => e.target === n).every((e) => seen.has(e.source)),
    );
    if (!ready.length) return false;
    ready.forEach((n) => seen.add(n));
    if (seen.size === nodes.length)
      return edges.every(
        (e) => nodes.includes(e.source) && nodes.includes(e.target),
      );
  }
  return false;
}
function portsMatch(edge: Connection, registry: CanvasRegistry) {
  const source = registry.nodes
    .find((n) => n.id === edge.source)
    ?.ports?.find(
      (p) => p.id === (edge.sourceHandle ?? "out") && p.direction === "out",
    );
  const target = registry.nodes
    .find((n) => n.id === edge.target)
    ?.ports?.find(
      (p) => p.id === (edge.targetHandle ?? "in") && p.direction === "in",
    );
  return !!source && !!target && source.kind === target.kind;
}
function Surface({
  registry,
  stages,
  active,
  coverage,
  cost,
}: {
  registry: CanvasRegistry;
  stages: StageSnapshot;
  active: boolean;
  coverage: MetricSnapshot;
  cost: MetricSnapshot;
}) {
  const session = useSession();
  const preferences = usePreferences();
  const flow = useReactFlow<FlowNode>();
  const [group, setGroup] = useState("main");
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  function measurement(id: string) {
    if (preferences.lens === "quality") {
      const category = [
        "extract",
        "extract-step",
        "validate",
        "consolidate",
      ].includes(id)
        ? "fields"
        : ["aggregate", "gate", "publish", "suppressed"].includes(id)
          ? "coverage"
          : "";
      const values = (coverage.series ?? []).filter(
        (p) => category && p.category === category && p.value != null,
      );
      return values.length
        ? values.reduce((sum, p) => sum + p.value!, 0) / values.length
        : null;
    }
    if (preferences.lens === "cost") {
      const duration = stages.nodes.find((n) => n.id === id)?.duration;
      const maximum = Math.max(1, ...stages.nodes.map((n) => n.duration ?? 0));
      return duration == null ? null : 1 - duration / maximum;
    }
    return null;
  }
  const quota =
    cost.metrics?.used != null && cost.metrics?.limit
      ? Math.min(1, cost.metrics.used / cost.metrics.limit)
      : null;
  const visible = useMemo(
    () =>
      registry.nodes.filter(
        (n) =>
          !(preferences.hidden ?? []).includes(n.id) &&
          (n.group === group || (group === "main" && n.group === "sub")),
      ),
    [registry, group, preferences.hidden],
  );
  useEffect(() => {
    const graph = new dagre.graphlib.Graph()
      .setGraph({ rankdir: "LR", ranksep: 96, nodesep: 80 })
      .setDefaultEdgeLabel(() => ({}));
    visible
      .filter((n) => n.variant !== "sub")
      .forEach((n) =>
        graph.setNode(n.id, {
          width: n.variant === "wide" ? 240 : 80,
          height: 120,
        }),
      );
    registry.edges
      .filter(
        (e) =>
          visible.some((n) => n.id === e.source) &&
          visible.some((n) => n.id === e.target) &&
          !e.sub,
      )
      .forEach((e) => graph.setEdge(e.source, e.target));
    dagre.layout(graph);
    setNodes(
      visible.map((n) => {
        const p = graph.node(n.id) as { x: number; y: number } | undefined;
        const saved = preferences.positions[n.id];
        return {
          id: n.id,
          type: "stage",
          position: saved ?? {
            x: n.x ?? (p?.x ?? 80) - 40,
            y: n.y ?? (p?.y ?? 80) - 40,
          },
          style: {
            width: n.variant === "wide" ? 240 : n.variant === "sub" ? 64 : 80,
          },
          data: {
            definition: n,
            stage: stages.nodes.find((s) => s.id === n.id),
            lens: preferences.lens,
            active,
            measure: measurement(n.id),
            quota,
          },
        };
      }),
    );
    setEdges(
      registry.edges
        .filter(
          (e) =>
            visible.some((n) => n.id === e.source) &&
            visible.some((n) => n.id === e.target),
        )
        .map((e, i) => ({
          id: `edge-${i}`,
          source: e.source,
          target: e.target,
          sourceHandle: e.port ?? "out",
          targetHandle: e.target_port ?? "in",
          type: "volume",
          markerEnd: e.sub
            ? undefined
            : { type: MarkerType.ArrowClosed, color: "var(--edge)" },
          label: e.sub
            ? undefined
            : (stages.nodes.find((s) => s.id === e.source)?.out_count ??
              undefined),
          data: {
            active:
              active &&
              !e.sub &&
              registry.nodes.find((n) => n.id === e.target)?.capability !==
                "planned",
            sub: e.sub,
            volume: stages.nodes.find((s) => s.id === e.source)?.out_count,
          },
        })),
    );
  }, [registry, visible, setNodes, setEdges]);
  useEffect(() => {
    setNodes((old) =>
      old.map((n) => ({
        ...n,
        data: {
          ...n.data,
          stage: stages.nodes.find((s) => s.id === n.id),
          lens: preferences.lens,
          active,
          measure: measurement(n.id),
          quota,
        },
      })),
    );
    setEdges((old) =>
      old.map((e) => ({
        ...e,
        label: e.data?.sub
          ? undefined
          : (stages.nodes.find((s) => s.id === e.source)?.out_count ??
            undefined),
        data: {
          ...e.data,
          active:
            active &&
            !e.data?.sub &&
            registry.nodes.find((n) => n.id === e.target)?.capability !==
              "planned",
          volume: stages.nodes.find((s) => s.id === e.source)?.out_count,
          loss: (() => {
            if (preferences.lens !== "quality" || e.data?.sub) return null;
            const target = stages.nodes.find((n) => n.id === e.target);
            return target?.in_count &&
              target.out_count != null &&
              target.out_count <= target.in_count
              ? 1 - target.out_count / target.in_count
              : null;
          })(),
        },
      })),
    );
  }, [
    stages,
    preferences.lens,
    active,
    registry,
    coverage,
    cost,
    setNodes,
    setEdges,
  ]);
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        void flow.fitView({
          padding: 0.14,
          minZoom: 0.25,
          maxZoom: 1,
          duration: 200,
        }),
      100,
    );
    return () => clearTimeout(timer);
  }, [group, flow]);
  const connect = useCallback(
    (connection: Connection) => {
      const next = addEdge(connection, edges);
      if (
        validDAG(
          nodes.map((n) => n.id),
          next,
        ) &&
        portsMatch(connection, registry) &&
        !nodes.some(
          (n) =>
            [connection.source, connection.target].includes(n.id) &&
            n.data.definition.capability === "planned",
        )
      )
        setEdges(next);
      else session.set({ error: copy.rejected });
    },
    [nodes, edges, setEdges, session],
  );
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).closest("input,textarea,select"))
        return;
      if (event.key.toLowerCase() === "f") void flow.fitView({ duration: 200 });
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [flow]);
  function exportGraph() {
    const graph = {
      version: "v1",
      nodes: nodes.map((n) => ({ id: n.id, x: n.position.x, y: n.position.y })),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        source_port: e.sourceHandle ?? "out",
        target_port: e.targetHandle ?? "in",
      })),
    };
    if (
      !validate(registry.graph_schema, graph) ||
      !validDAG(
        graph.nodes.map((n) => n.id),
        graph.edges,
      )
    ) {
      session.set({ error: copy.rejected });
      return;
    }
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(graph)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = copy.exportName;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function importGraph(file?: File) {
    if (!file) return;
    try {
      if (file.size > 1000000) throw Error();
      const raw: unknown = JSON.parse(await file.text());
      const result = registry.graph_schema;
      if (!validate(result, raw)) throw Error();
      const g = raw as {
        nodes: { id: string; x: number; y: number }[];
        edges: {
          source: string;
          target: string;
          source_port?: string | null;
          target_port?: string | null;
        }[];
      };
      if (
        g.nodes.some((n) => !registry.nodes.some((d) => d.id === n.id)) ||
        !validDAG(
          g.nodes.map((n) => n.id),
          g.edges,
        ) ||
        !g.edges.every((e) =>
          portsMatch(
            {
              source: e.source,
              target: e.target,
              sourceHandle: e.source_port ?? "out",
              targetHandle: e.target_port ?? "in",
            },
            registry,
          ),
        )
      )
        throw Error();
      preferences.set({
        positions: Object.fromEntries(
          g.nodes.map((n) => [n.id, { x: n.x, y: n.y }]),
        ),
        hidden: [
          ...(preferences.hidden ?? []).filter(
            (id) => !g.nodes.some((n) => n.id === id),
          ),
          ...visible
            .filter((n) => !g.nodes.some((v) => v.id === n.id))
            .map((n) => n.id),
        ],
      });
      setNodes((old) =>
        old.map((n) => ({
          ...n,
          position: g.nodes.find((v) => v.id === n.id) ?? n.position,
        })),
      );
      setEdges(
        g.edges.map((e, i) => ({
          ...e,
          sourceHandle: e.source_port ?? "out",
          targetHandle: e.target_port ?? "in",
          id: `import-${i}`,
          type: "volume",
        })),
      );
    } catch {
      session.set({ error: copy.rejected });
    }
  }
  return (
    <div
      className={`canvas ${session.panel ? "panel-open" : ""}`}
      data-testid="canvas-view"
    >
      <div className="canvas-switch" role="toolbar" aria-label={copy.palette}>
        {["main", "ingest", "extract", "maintenance", "demo"].map((g, i) => (
          <Button
            key={g}
            icon={["run", "ingest", "extract", "config", "flask"][i]}
            title={g === "main" ? copy.production : label(g)}
            className={g === group ? "active" : ""}
            onClick={() => setGroup(g)}
          />
        ))}
        <i />
        <Button icon="export" title={copy.export} onClick={exportGraph} />
        <label className="icon-upload" title={copy.import}>
          <Icon name="import" />
          <input
            type="file"
            accept="application/json"
            aria-label={copy.import}
            onChange={(event) => void importGraph(event.target.files?.[0])}
          />
        </label>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodesDelete={(deleted) =>
          preferences.set({
            hidden: [
              ...(preferences.hidden ?? []),
              ...deleted.map((n) => n.id),
            ],
          })
        }
        onEdgesChange={onEdgesChange}
        onConnect={connect}
        onNodeClick={(_, n) => session.set({ selected: n.id })}
        onNodeDoubleClick={(_, n) =>
          session.set({ selected: n.id, panel: n.id })
        }
        onNodeDragStop={(_, n) =>
          preferences.set({
            positions: { ...preferences.positions, [n.id]: n.position },
          })
        }
        fitView
        minZoom={0.25}
        maxZoom={2}
        panOnDrag
        selectionOnDrag={false}
        panActivationKeyCode="Space"
        deleteKeyCode="Backspace"
        proOptions={{ hideAttribution: true }}
        onlyRenderVisibleElements
        aria-label={copy.production}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          color="var(--grid)"
        />
        <MiniMap
          nodeColor="var(--node)"
          nodeStrokeColor="var(--edge)"
          maskColor="var(--map-mask)"
          pannable
          zoomable
          aria-label={copy.fit}
        />
      </ReactFlow>
      <div className="zoom-controls">
        <Button
          icon="minus"
          title={copy.zoomOut}
          onClick={() => void flow.zoomOut({ duration: 200 })}
        />
        <Button
          icon="fit"
          title={copy.fit}
          onClick={() => void flow.fitView({ duration: 200 })}
        />
        <Button
          icon="plus"
          title={copy.zoomIn}
          onClick={() => void flow.zoomIn({ duration: 200 })}
        />
      </div>
    </div>
  );
}
export function Canvas(props: Parameters<typeof Surface>[0]) {
  return (
    <ReactFlowProvider>
      <Surface {...props} />
    </ReactFlowProvider>
  );
}
