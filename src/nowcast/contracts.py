"""Versioned contracts shared by the CLI, API, exporter and local website."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class KPI(Contract):
    id: Literal['eps_growth', 'revenue_growth', 'guidance', 'tone']
    label: str
    field: str
    output: str
    definition: str
    unit: Literal['fraction', 'percent', 'score']


class ParameterBinding(Contract):
    label: str
    config_path: Literal[
        'data.start_date',
        'data.end_date',
        'llm.models',
        'llm.max_tokens',
        'aggregation.min_constituents',
        'aggregation.min_observations',
    ]
    value: str | int | list[str] | None = None


class Node(Contract):
    id: str = Field(pattern=r'^[a-z][a-z-]*$')
    label: str
    inputs: list[str]
    output: str
    capability: Literal['executable', 'planned']
    help: str
    parameters: list[ParameterBinding] = Field(default_factory=list)


class Workflow(Contract):
    id: str = Field(pattern=r'^[a-z][a-z-]*$')
    label: str
    nodes: list[str]
    edges: list[tuple[str, str]]


class PlanLimits(Contract):
    maximum_planned_pairs: int = Field(gt=0)
    maximum_requests: int = Field(gt=0)


class Registry(Contract):
    version: Literal['v1']
    kpis: list[KPI]
    nodes: list[Node]
    workflows: list[Workflow]
    concepts: dict[Literal['revenue', 'reported_eps'], list[str]]
    limits: PlanLimits

    @model_validator(mode='after')
    def valid(self) -> Registry:
        for values in (self.nodes, self.workflows, self.kpis):
            ids = [value.id for value in values]
            if len(ids) != len(set(ids)):
                raise ValueError('registry identifiers must be unique')
        if {k.id for k in self.kpis} != {'eps_growth', 'revenue_growth', 'guidance', 'tone'}:
            raise ValueError('closed KPI registry requires all four KPI definitions')
        for workflow in self.workflows:
            self.execution_order(workflow)
        return self

    def execution_order(self, workflow: Workflow) -> list[str]:
        """Validate ports, executable capabilities and DAG dependencies before execution."""
        nodes = {node.id: node for node in self.nodes}
        if len(set(workflow.nodes)) != len(workflow.nodes) or not workflow.nodes:
            raise ValueError('workflow nodes must be nonempty and unique')
        if any(key not in nodes or nodes[key].capability != 'executable' for key in workflow.nodes):
            raise ValueError('unknown or planned node cannot execute')
        if len(set(workflow.edges)) != len(workflow.edges):
            raise ValueError('duplicate edges')
        for left, right in workflow.edges:
            if left not in workflow.nodes or right not in workflow.nodes:
                raise ValueError('edge refers to a missing node')
            if nodes[left].output not in nodes[right].inputs:
                raise ValueError('incompatible node ports')
        order: list[str] = []
        while len(order) < len(workflow.nodes):
            ready = [
                key
                for key in workflow.nodes
                if key not in order
                and all(left in order for left, right in workflow.edges if right == key)
            ]
            if not ready:
                raise ValueError('workflow contains a cycle')
            for key in ready:
                provided = {nodes[left].output for left, right in workflow.edges if right == key}
                if set(nodes[key].inputs) != provided:
                    raise ValueError('workflow is missing an upstream artifact')
                order.append(key)
        return order


class RunRequest(Contract):
    version: Literal['v1'] = 'v1'
    workflow_id: str = Field(min_length=1, max_length=80)
    submission_id: str = Field(pattern=r'^[a-zA-Z0-9-]{8,80}$')
    node_id: str | None = None
    upstream_run_id: str | None = None
    command_id: str | None = None
    parameters: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)


class RunStatus(Contract):
    version: Literal['v1'] = 'v1'
    id: str
    workflow_id: str
    status: Literal['queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted']
    stage: str | None
    completed: int
    total: int
    cancel_requested: bool
    created_at: str


class RunEvent(Contract):
    sequence: int
    job_id: str
    stage: str | None
    kind: str
    created_at: str


INDEX_ROW_PATTERN = r'^(?:as_of_date|season_year|season_quarter|n_reported|n_expected|n_review_excluded|n_planned|n_attempted|execution_complete|n_eligible_releases|n_guidance_providers|share_reported|share_of_cohort|share_of_index|beat_rate|eps_growth_agg|revenue_growth_agg|guidance_raise_share|guidance_lower_share|guidance_ratio|tone_score_mean|suppressed|n_obs_[a-z_]+|theme_[a-z_]+_share|metric_status_[a-z_]+)$'
INDEX_STATUSES = ('ok', 'insufficient_observations', 'no_consensus', 'unavailable', 'unverified')
INDEX_ROW_SCHEMA = {
    'type': 'object',
    'propertyNames': {'pattern': INDEX_ROW_PATTERN},
    'properties': {
        'as_of_date': {
            'type': ['string', 'null'],
            'pattern': r'^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$',
        }
    },
    'patternProperties': {'^metric_status_': {'enum': list(INDEX_STATUSES)}},
    'additionalProperties': {'type': ['number', 'boolean', 'null']},
}
IndexRow = Annotated[
    dict[str, str | float | int | bool | None], Field(json_schema_extra=INDEX_ROW_SCHEMA)
]


class IndexSnapshot(Contract):
    version: Literal['v1'] = 'v1'
    label: Literal['index-level proxies'] = 'index-level proxies'
    source: Literal['pipeline', 'synthetic'] = 'pipeline'
    status: Literal['available', 'unavailable'] = 'available'
    snapshots: list[IndexRow]

    @field_validator('snapshots')
    @classmethod
    def identifier_free(
        cls, rows: list[dict[str, str | float | int | bool | None]]
    ) -> list[dict[str, str | float | int | bool | None]]:
        import re

        for row in rows:
            for key, value in row.items():
                if not re.fullmatch(INDEX_ROW_PATTERN, key):
                    raise ValueError('unexpected Index column')
                if key.startswith('metric_status_'):
                    if value not in INDEX_STATUSES:
                        raise ValueError('unknown metric status')
                elif key == 'as_of_date':
                    if value is not None and (
                        not isinstance(value, str)
                        or not re.fullmatch(
                            r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?',
                            value,
                        )
                    ):
                        raise ValueError('invalid Index date')
                elif isinstance(value, str):
                    raise ValueError('Index observations must be numeric')
        return rows


class ScheduleDay(Contract):
    utc_day: str
    local_time: str
    used: int
    budget: int
    configured_limit: int
    today: bool
    planned_requests: int
    retry_reserve: int
    planned_by_task: dict[str, int]


class ScheduleTask(Contract):
    id: str
    status: Literal['pending', 'due', 'running', 'done', 'blocked', 'failed']
    earliest_day: str
    quota_cost: int
    attempts: int
    last_error: str | None
    next_eligible: float | None
    human: bool
    capability: Literal['executable', 'planned', 'human'] = 'executable'


class ScheduleSnapshot(Contract):
    version: Literal['v1'] = 'v1'
    utc_day: str
    local_time: str
    paused: bool
    models_confirmed: bool
    auth_blocked: bool
    next_run_utc: str
    next_run_local: str
    forecast: dict[str, str | int | float | list[str] | None]
    days: list[ScheduleDay]
    tasks: list[ScheduleTask]


class CLIControl(Contract):
    name: str
    flags: list[str]
    kind: Literal['help', 'boolean', 'integer', 'number', 'string']
    default: str | int | float | bool | list[str] | None
    choices: list[str] | None
    multiple: bool
    help: str


class FlowPort(Contract):
    id: str
    direction: Literal['in', 'out']
    kind: str
    required: bool = False


class IOQuantity(Contract):
    noun: str
    unit_label: str
    plain_line: str
    icon: str


class IOField(Contract):
    key: str
    label: str
    unit: str
    format: str
    description: str = ''


class NodeIO(Contract):
    source: str | None = None
    takes: IOQuantity
    gives: IOQuantity
    example_fields: list[IOField]
    summaries: list[str]


class CanvasNode(Contract):
    io: NodeIO
    ports: list[FlowPort] = Field(default_factory=list)
    help_question: int = Field(default=0, ge=0, le=13)
    id: str
    command: list[str] = Field(default_factory=list)
    controls: list[CLIControl] = Field(default_factory=list)
    help: str = ''
    label_key: str
    icon: str
    variant: Literal['square', 'trigger', 'wide', 'branch', 'sub'] = 'square'
    group: str
    capability: Literal['executable', 'planned', 'inspect', 'terminal'] = 'executable'
    subnodes: list[str] = Field(default_factory=list)
    open_output: bool = False
    x: float | None = None
    y: float | None = None


class CanvasEdge(Contract):
    target_port: str | None = None
    source: str
    target: str
    port: str | None = None
    sub: bool = False


class GraphPoint(Contract):
    id: str = Field(pattern=r'^[a-z][a-z-]*$')
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)


class GraphLink(Contract):
    source_port: str | None = None
    target_port: str | None = None
    source: str
    target: str


class GraphDocument(Contract):
    version: Literal['v1'] = 'v1'
    nodes: list[GraphPoint] = Field(min_length=1, max_length=100)
    edges: list[GraphLink] = Field(max_length=200)

    @model_validator(mode='after')
    def dag(self) -> GraphDocument:
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids) or not ids:
            raise ValueError('unique nodes required')
        remaining = set(ids)
        if any(edge.source not in remaining or edge.target not in remaining for edge in self.edges):
            raise ValueError('unknown graph port')
        while remaining:
            ready = {
                node
                for node in remaining
                if not any(e.target == node and e.source in remaining for e in self.edges)
            }
            if not ready:
                raise ValueError('cycle')
            remaining -= ready
        from nowcast.workflow_registry import validate_ports

        validate_ports(self)
        return self


class CanvasRegistry(Contract):
    version: Literal['v1'] = 'v1'
    nodes: list[CanvasNode]
    edges: list[CanvasEdge]
    graph_schema: dict


class StageState(Contract):
    id: str
    status: Literal['idle', 'running', 'done', 'attention', 'error', 'planned']
    in_count: int | None = None
    out_count: int | None = None
    duration: float | None = None
    skipped_by_reason: dict[str, int] = Field(default_factory=dict)
    last_run: str | None = None


class StageSnapshot(Contract):
    version: Literal['v1'] = 'v1'
    source: Literal['pipeline', 'synthetic'] = 'pipeline'
    nodes: list[StageState]


class FieldProfile(Contract):
    field: str
    inferred_type: Literal['number', 'boolean', 'string', 'null', 'mixed']
    null_rate: float | None
    example: str | float | bool | None


class PaneResponse(Contract):
    profiles: list[FieldProfile] = Field(default_factory=list)
    view: Literal['index', 'trace'] = 'index'
    version: Literal['v1'] = 'v1'
    node: str
    side: Literal['input', 'output']
    status: Literal['available', 'unavailable', 'private'] = 'available'
    total: int
    offset: int
    columns: list[str]
    rows: list[dict[str, str | float | int | bool | None]]
    runs: list[str] = Field(default_factory=list)
    upstream: list[str] = Field(default_factory=list)
    duration: float | None = None
    config_hash: str
    run: str | None = None


class ChartPoint(Contract):
    category: str
    metric: str = ''
    season: str = ''
    value: float | None = None
    denominator: float | None = None
    status: str = 'unavailable'


class MetricSnapshot(Contract):
    version: Literal['v1'] = 'v1'
    metrics: dict[str, float | None] = Field(default_factory=dict)
    series: list[ChartPoint] = Field(default_factory=list)


class EvidenceField(Contract):
    field: str
    value: str | float | None
    unit: str | None = None
    confidence: float | None = None
    quote: str | None = None
    start: int | None = None
    end: int | None = None
    row_start: int | None = None
    row_end: int | None = None
    number_present: bool | None = None
    issues: list[str]


class EvidenceResponse(Contract):
    version: Literal['v1'] = 'v1'
    record_id: str
    source: str
    fields: list[EvidenceField]
    verdicts: dict[str, Literal['correct', 'wrong', 'unsure']] = Field(default_factory=dict)


class LabelRequest(Contract):
    record_id: str = Field(min_length=1, max_length=200)
    field: str = Field(pattern=r'^[a-z_]{1,40}$')
    value: str | float | None = None
    verdict: Literal['correct', 'wrong', 'unsure']


class LabelResponse(Contract):
    version: Literal['v1'] = 'v1'
    checked: int
    total: int
    fields: dict[str, dict[str, int]]


class KPIObservation(Contract):
    metric: Literal['eps_growth', 'revenue_growth', 'guidance', 'tone']
    season: str = Field(pattern=r'^20\d{2}Q[1-4]$')
    as_of: str = Field(pattern=r'^20\d{2}-\d{2}-\d{2}$')
    value: float | None = Field(allow_inf_nan=False)
    unit: Literal['fraction', 'percent', 'score']
    n_obs: int | None
    n_expected: int | None
    coverage: float | None
    status: Literal[
        'ok', 'insufficient_observations', 'no_consensus', 'unavailable', 'unverified', 'suppressed'
    ]
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    config_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class KPIKnowledgeBase(Contract):
    version: Literal['v1'] = 'v1'
    kind: Literal['index-level proxies'] = 'index-level proxies'
    records: list[KPIObservation]


class SessionResponse(Contract):
    version: Literal['v1'] = 'v1'
    csrf_token: str
    internal_trace_available: bool
    read_only: bool = False


class ConfigControl(Contract):
    path: str
    kind: Literal['boolean', 'integer', 'number', 'string']
    value: str | int | float | bool | list[str]
    multiple: bool = False


class SettingsResponse(Contract):
    version: Literal['v1'] = 'v1'
    nodes: dict[str, list[ConfigControl]]
