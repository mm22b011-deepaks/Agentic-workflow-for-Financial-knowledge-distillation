"""Typed configuration loading, validation and path resolution."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nowcast.errors import ConfigError
from nowcast.paths import (
    Paths,
    aggregates_dir,
    cache_dir,
    data_root,
    extractions_dir,
    manifests_dir,
    prompts_dir,
    raw_dir,
    reports_dir,
    resolve_data_path,
    sub_dir,
)

__all__ = [
    'Config',
    'Paths',
    'aggregates_dir',
    'cache_dir',
    'data_root',
    'extractions_dir',
    'load_config',
    'manifests_dir',
    'prompts_dir',
    'raw_dir',
    'reports_dir',
    'resolve_data_path',
    'sub_dir',
    'validate_config',
]

DEFAULT_CONFIG_PATH = Path('configs') / 'config.yaml'
FREE_MODEL_SUFFIX = ':free'


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime execution settings."""

    max_concurrency: int = 4
    seed: int = 0
    log_level: str = 'INFO'
    data_dir_env: str = 'DATA_DIR'


@dataclass(frozen=True)
class PathsConfig:
    """Directory layout settings, relative to the project or data directory."""

    project_dir: str = '.'
    data_dir: str = 'data'
    raw_dir: str = 'raw'
    cache_dir: str = '.cache/llm'
    extractions_dir: str = 'extractions'
    aggregates_dir: str = 'aggregates'
    reports_dir: str = 'reports'
    manifests_dir: str = 'manifests'
    prompts_dir: str = 'prompts'


@dataclass(frozen=True)
class DataConfig:
    """Input file locations and SEC download settings."""

    start_date: str = ''
    end_date: str = ''
    constituents_csv: str = 'inputs/constituents.csv'
    local_manifest_csv: str = 'inputs/local_manifest.csv'
    labels_csv: str = 'inputs/labels.csv'
    consensus_csv: str = 'inputs/consensus.csv'
    weights_csv: str = 'inputs/weights.csv'
    sec_user_agent_env: str = 'SEC_USER_AGENT'
    sec_max_requests_per_sec: float = 8.0
    edgar_submissions_url_template: str = ''
    edgar_archive_url_template: str = ''
    edgar_index_url_template: str = ''
    edgar_index_headers_url_template: str = ''
    edgar_forms: tuple[str, ...] = ()
    edgar_document_suffixes: tuple[str, ...] = ()
    edgar_earnings_items: tuple[str, ...] = ()
    edgar_lookback_days: int = 730
    edgar_max_documents: int = 100
    edgar_docs_per_cik: int = 3


@dataclass(frozen=True)
class ParsingConfig:
    """HTML and section splitting settings."""

    min_section_chars: int = 200
    section_patterns: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMConfig:
    """Model caller settings; only free OpenRouter models are permitted."""

    base_url: str = ''
    api_key_env: str = 'OPENROUTER_API_KEY'
    models: tuple[str, ...] = ()
    timeout_seconds: float = 120.0
    temperature: float = 0.0
    max_tokens: int = 8192
    reasoning_effort: str = 'low'
    max_reasoning_tokens: int = 3000
    retry_attempts: int = 3
    retry_backoff_seconds: float = 2.0
    retry_max_wait_seconds: float = 120.0
    app_name: str = ''


@dataclass(frozen=True)
class CacheConfig:
    """Response cache settings."""

    enabled: bool = True
    dir: str = '.cache/llm'
    ttl_days: int = 30


@dataclass(frozen=True)
class BudgetConfig:
    """Spend cap and ledger location."""

    max_usd: float = 0.0
    ledger_path: str = ''


@dataclass(frozen=True)
class ExtractionConfig:
    """Extraction, validation and review-queue settings."""

    schema_version: str = 'v1'
    max_doc_chars: int = 24000
    max_repairs: int = 2
    quote_match_min_ratio: float = 0.85
    confidence_penalty_on_issue: float = 0.7
    min_confidence: float = 0.5
    eps_tolerance_abs: float = 0.02
    max_evidence_words: int = 25
    themes: tuple[str, ...] = ()
    review_queue_path: str = ''


@dataclass(frozen=True)
class AggregationConfig:
    """Index-level aggregation settings, including the privacy guardrail."""

    weighting: str = 'equal'
    weights_csv: str = ''
    min_constituents: int = 10
    winsorize_pct: float = 0.05


@dataclass(frozen=True)
class NowcastConfig:
    """Nowcast aggregation settings."""

    min_documents: int = 3
    min_observations: int = 3


@dataclass(frozen=True)
class UniverseConfig:
    """S&P 500 universe builder settings."""

    source: str = 'wikipedia_changes'
    current_table_url: str = ''
    changes_table_url: str = ''
    historical_csv_path_or_url: str = ''
    historical_url_template: str = ''
    sec_ticker_map_url: str = ''
    cik_overrides_csv: str = ''
    http_user_agent_env: str = 'SEC_USER_AGENT'
    expected_members: int = 500
    member_count_tolerance: int = 8
    min_cik_coverage: float = 0.98
    as_of_sample_freq: str = 'QS'
    subset_n: int = 0
    subset_seed: int = 42
    avg_tokens_per_doc_in: int = 6000
    avg_tokens_per_doc_out: int = 800
    licence_note: str = ''
    refresh: bool = False


@dataclass(frozen=True)
class ReportingConfig:
    """Report settings."""

    report_path: str = 'reports/report.md'
    top_n: int = 10


@dataclass(frozen=True)
class Config:
    """Root configuration object."""

    runtime: RuntimeConfig = RuntimeConfig()
    paths: PathsConfig = PathsConfig()
    data: DataConfig = DataConfig()
    parsing: ParsingConfig = ParsingConfig()
    llm: LLMConfig = LLMConfig()
    cache: CacheConfig = CacheConfig()
    budget: BudgetConfig = BudgetConfig()
    extraction: ExtractionConfig = ExtractionConfig()
    aggregation: AggregationConfig = AggregationConfig()
    nowcast: NowcastConfig = NowcastConfig()
    reporting: ReportingConfig = ReportingConfig()
    universe: UniverseConfig = UniverseConfig()


def _section(
    raw: dict[str, Any], name: str, allowed: frozenset[str] | None = None
) -> dict[str, Any]:
    """Return one config section as a dict, rejecting non-mapping values and unknown keys."""
    value = raw.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f'config section {name!r} must be a mapping, got {type(value).__name__}')
    if allowed is not None:
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ConfigError(
                f'config section {name!r} has unknown keys: {", ".join(unknown)}; '
                f'allowed: {", ".join(sorted(allowed))}'
            )
    return value


def _fields(cls: Any) -> frozenset[str]:
    """Return the dataclass field names of a config section type."""
    return frozenset(item.name for item in dataclasses.fields(cls))


def _tuple(value: Any, name: str) -> tuple[str, ...]:
    """Coerce a list-like config value into a tuple of strings."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f'config key {name!r} must be a list, got {type(value).__name__}')
    return tuple(str(item) for item in value)


def _apply_overrides(raw: dict[str, Any], overrides: dict[str, str]) -> dict[str, Any]:
    """Apply dotted-key string overrides onto the raw config mapping."""
    for dotted, raw_value in overrides.items():
        parts = dotted.split('.')
        node: dict[str, Any] = raw
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        leaf = parts[-1]
        node[leaf] = _coerce_override(raw_value, node.get(leaf))
    return raw


TRUE_TEXT = {'1', 'true', 'yes', 'on'}


def _coerce_override(raw_value: object, existing: Any) -> Any:
    """Coerce an override value to the type of the value it replaces.

    Overrides arriving from a command line are strings, but callers such as tests
    pass Python values directly, so both must work.
    """
    if isinstance(existing, bool):
        if isinstance(raw_value, bool):
            return raw_value
        return str(raw_value).strip().lower() in TRUE_TEXT
    if isinstance(existing, int):
        return int(str(raw_value).strip())
    if isinstance(existing, float):
        return float(str(raw_value).strip())
    if isinstance(existing, (list, tuple)):
        if isinstance(raw_value, (list, tuple)):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        return [item.strip() for item in str(raw_value).split(',') if item.strip()]
    if existing is None and not isinstance(raw_value, str):
        raise ConfigError(
            f'cannot apply override value {raw_value!r} to an unset config key; '
            'pass it as a string so its type can be inferred from the default'
        )
    return raw_value if isinstance(raw_value, str) else str(raw_value)


def load_config(path: Path | str | None = None, overrides: dict[str, str] | None = None) -> Config:
    """Load and validate the YAML config, optionally applying dotted-key overrides."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f'config file not found: {config_path}')
    try:
        raw_loaded = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        raise ConfigError(f'config file is not valid YAML: {exc}') from exc
    raw: dict[str, Any] = raw_loaded or {}
    if not isinstance(raw, dict):
        raise ConfigError('config root must be a mapping')
    if overrides:
        raw = _apply_overrides(raw, overrides)

    runtime = _section(raw, 'runtime', _fields(RuntimeConfig))
    paths = _section(raw, 'paths', _fields(PathsConfig))
    data = _section(raw, 'data', _fields(DataConfig))
    parsing = _section(raw, 'parsing', _fields(ParsingConfig))
    llm = _section(raw, 'llm', _fields(LLMConfig))
    cache = _section(raw, 'cache', _fields(CacheConfig))
    budget = _section(raw, 'budget', _fields(BudgetConfig))
    extraction = _section(raw, 'extraction', _fields(ExtractionConfig))
    aggregation = _section(raw, 'aggregation', _fields(AggregationConfig))
    nowcast = _section(raw, 'nowcast', _fields(NowcastConfig))
    reporting = _section(raw, 'reporting', _fields(ReportingConfig))
    universe = _section(raw, 'universe', _fields(UniverseConfig))

    patterns = parsing.get('section_patterns') or {}
    if not isinstance(patterns, dict):
        raise ConfigError("config key 'parsing.section_patterns' must be a mapping")

    return Config(
        runtime=RuntimeConfig(**runtime),
        paths=PathsConfig(**paths),
        data=DataConfig(
            **{
                **data,
                'edgar_forms': _tuple(data.get('edgar_forms'), 'data.edgar_forms'),
                'edgar_earnings_items': _tuple(
                    data.get('edgar_earnings_items'), 'data.edgar_earnings_items'
                ),
                'edgar_document_suffixes': _tuple(
                    data.get('edgar_document_suffixes'), 'data.edgar_document_suffixes'
                ),
            }
        ),
        parsing=ParsingConfig(
            min_section_chars=int(parsing.get('min_section_chars', 200)),
            section_patterns={str(k): str(v) for k, v in patterns.items()},
        ),
        llm=LLMConfig(**{**llm, 'models': _tuple(llm.get('models'), 'llm.models')}),
        cache=CacheConfig(**cache),
        budget=BudgetConfig(**budget),
        extraction=ExtractionConfig(
            **{**extraction, 'themes': _tuple(extraction.get('themes'), 'extraction.themes')}
        ),
        aggregation=AggregationConfig(**aggregation),
        nowcast=NowcastConfig(**nowcast),
        reporting=ReportingConfig(**reporting),
        universe=UniverseConfig(**universe),
    )


def validate_config(config: Config, strict: bool = False) -> list[str]:
    """Return validation problems; raise ConfigError when strict and any exist."""
    problems: list[str] = []
    if config.runtime.max_concurrency < 1:
        problems.append('runtime.max_concurrency must be >= 1')
    if config.data.sec_max_requests_per_sec <= 0:
        problems.append('data.sec_max_requests_per_sec must be > 0')
    for key in (
        'edgar_submissions_url_template',
        'edgar_archive_url_template',
        'edgar_index_url_template',
        'edgar_index_headers_url_template',
    ):
        if not getattr(config.data, key):
            problems.append(f'data.{key} must be set')
    if '{cik' not in config.data.edgar_submissions_url_template:
        problems.append("data.edgar_submissions_url_template must contain '{cik")
    # The accession directory is not optional: EDGAR's CDN answers 403 (not 404) when it
    # is missing, which hides the mistake behind what looks like a permissions failure.
    if '{accession_nodash}' not in config.data.edgar_index_headers_url_template:
        problems.append(
            'data.edgar_index_headers_url_template must contain {accession_nodash} '
            '(the accession directory); without it EDGAR returns 403'
        )
    if not config.llm.models:
        problems.append('llm.models must list at least one model')
    for model in config.llm.models:
        if not model.endswith(FREE_MODEL_SUFFIX):
            problems.append(f'llm.models entry {model!r} is not a free model (must end in :free)')
    for key in (config.llm.api_key_env, config.data.sec_user_agent_env):
        if not key:
            problems.append('environment variable name must not be empty')
    if strict:
        for key in (config.llm.api_key_env, config.data.sec_user_agent_env):
            if key and not os.environ.get(key):
                problems.append(f'environment variable {key} is not set')
    if config.budget.max_usd <= 0:
        problems.append('budget.max_usd must be > 0')
    if config.universe.source not in {'wikipedia_changes', 'historical_csv'}:
        problems.append("universe.source must be 'wikipedia_changes' or 'historical_csv'")
    if not 0.0 <= config.universe.min_cik_coverage <= 1.0:
        problems.append('universe.min_cik_coverage must be between 0 and 1')
    if config.universe.subset_n < 0:
        problems.append('universe.subset_n must be >= 0')
    if config.aggregation.weighting not in {'equal', 'market_cap'}:
        problems.append("aggregation.weighting must be 'equal' or 'market_cap'")
    if config.aggregation.weighting == 'market_cap' and not config.aggregation.weights_csv:
        problems.append('aggregation.weights_csv must be set when weighting is market_cap')
    if not 0.0 <= config.aggregation.winsorize_pct < 0.5:
        problems.append('aggregation.winsorize_pct must be in [0, 0.5)')
    if config.aggregation.min_constituents < 1:
        problems.append('aggregation.min_constituents must be >= 1')
    if config.extraction.max_doc_chars <= 0:
        problems.append('extraction.max_doc_chars must be > 0')
    if problems and strict:
        raise ConfigError('config validation failed: ' + '; '.join(problems))
    return problems
