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
