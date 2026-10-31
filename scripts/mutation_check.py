"""A small mutation check over the modules whose bugs would matter most.

Each mutant is one exact textual edit to one source file. The mutant is written in
place, the module's tests are run, and the original bytes are restored in a `finally`
block. A mutant that the tests still pass is printed as SURVIVED: it marks a behaviour
the suite does not pin.

This is deliberately not a full mutation-testing tool: the mutations are the ones a
person would actually make while editing this code, and each is paired with the test
file that should catch it. Run it from the repository root:

    python scripts/mutation_check.py --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VALIDATORS = 'src/nowcast/extraction/validators.py'
EDGAR = 'src/nowcast/ingestion/edgar.py'
RUNNER = 'src/nowcast/extraction/runner.py'
AGGREGATE = 'src/nowcast/aggregation/aggregate.py'
UNITS = 'src/nowcast/extraction/units.py'
PROMPTS = 'src/nowcast/llm/prompts.py'

VALIDATOR_TESTS = ['tests/unit/test_validators.py']
EDGAR_TESTS = ['tests/unit/test_edgar.py']
RUNNER_TESTS = ['tests/unit/test_runner.py', 'tests/unit/test_truncation.py']
AGGREGATE_TESTS = ['tests/unit/test_aggregate.py']
UNITS_TESTS = ['tests/unit/test_units.py']
PROMPT_TESTS = ['tests/unit/test_prompts.py']


@dataclass(frozen=True)
class Mutant:
    """One textual edit and the tests expected to notice it."""

    name: str
    path: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTANTS = (
    # validators.py
    Mutant(
        'quote threshold becomes <=',
        VALIDATORS,
        'if verify_quote(quote, source) < float(config.extraction.quote_match_min_ratio):',
        'if verify_quote(quote, source) <= float(config.extraction.quote_match_min_ratio):',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'confidence penalty dropped',
        VALIDATORS,
        'adjust(confidence * penalty)\n        return',
        'adjust(confidence)\n        return',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'number-in-quote check dropped',
        VALIDATORS,
        'if field.evidence_quote and not number_in_quote(float(field.value), field.evidence_quote):',
        'if False:',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'empty-extraction check inverted',
        VALIDATORS,
        'return all(getattr(record, name).value is None for name in CORE_NUMERIC_FIELDS)',
        'return any(getattr(record, name).value is None for name in CORE_NUMERIC_FIELDS)',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'low-confidence boundary becomes strict',
        VALIDATORS,
        'if field.value is not None and field.confidence < minimum:',
        'if field.value is not None and field.confidence > minimum:',
        tuple(VALIDATOR_TESTS),
    ),
    # edgar.py
    Mutant(
        'earnings item filter removed',
        EDGAR,
        'if wanted_items and not item_codes.intersection(wanted_items):',
        'if False:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'window lower bound exclusive',
        EDGAR,
        'if not lower <= filing_date <= upper:',
        'if not lower < filing_date <= upper:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'non-text exhibits allowed',
        EDGAR,
        'if not is_text_document(filename, allowed):',
        'if False:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'abort threshold ignores the run',
        EDGAR,
        'if active_report.consecutive_blocked >= abort_after:',
        'if active_report.consecutive_blocked > abort_after + 1000:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'blocked counter never resets',
        EDGAR,
        '            self.consecutive_blocked = 0',
        '            pass',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'content-length check skipped',
        EDGAR,
        'if expected and len(response.content) != expected:',
        'if False:',
        tuple(EDGAR_TESTS),
    ),
    # runner.py
    Mutant(
        'earnings-item index filter removed',
        RUNNER,
        'if not has_earnings_item(items, wanted_items):',
        'if False:',
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'fingerprint drops validation settings',
        RUNNER,
        "digest.update(json.dumps(validation_settings(config), sort_keys=True).encode('utf-8'))",
        'pass',
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'truncation reported as llm_failed',
        RUNNER,
        "return _record_failure(queue_target, document, model, 'truncated', str(exc))",
        "return _record_failure(queue_target, document, model, 'llm_failed', str(exc))",
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'per-document guard removed',
        RUNNER,
        "        except Exception as exc:\n            LOGGER.exception('document failed",
        "        except ZeroDivisionError as exc:\n            LOGGER.exception('document failed",
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'diagnostics claim no truncation',
        RUNNER,
        "'truncated': prepared.truncated,",
        "'truncated': False,",
        tuple(RUNNER_TESTS + UNITS_TESTS),
    ),
    # units.py
    Mutant(
        'growth fraction correction dropped',
        UNITS,
        'candidates = [value] if abs(value) >= 1 else [value, value * 100]',
        'candidates = [value]',
        tuple(UNITS_TESTS),
    ),
    Mutant(
        'units canonicalisation dropped',
        UNITS,
        "return f'{recognised_currency} {recognised_scale}'",
        'return text or None',
        tuple(UNITS_TESTS),
    ),
    # prompts.py
    Mutant(
        'prompt hash drops few-shots',
        PROMPTS,
        'if bundle.few_shots:',
        'if False:',
        tuple(PROMPT_TESTS),
    ),
    # aggregate.py
    Mutant(
        'company collapse removed',
        AGGREGATE,
        '            counted, _duplicate_rows = collapse_to_companies(\n                counted, str(config.aggregation.dedupe_rule)\n            )',
        '            _duplicate_rows = 0',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'share guard removed',
        AGGREGATE,
        'if n_expected and n_reported > n_expected:',
        'if False:',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'review exclusion computed over the whole season',
        AGGREGATE,
        "excluded = int(reported_docs['in_review'].sum())",
        "excluded = int(season['in_review'].sum())",
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'beat tolerance comparison inverted',
        AGGREGATE,
        '[graded > tolerance, graded < -tolerance],',
        '[graded >= tolerance, graded <= -tolerance],',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'counted rows not excluded from metrics',
        AGGREGATE,
        "counted = reported_docs[~reported_docs['in_review']]",
        'counted = reported_docs',
        tuple(AGGREGATE_TESTS),
    ),
)


def _digest(path: Path) -> str:
    """Return the sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_tests(tests: tuple[str, ...]) -> bool:
    """Return True when the selected tests pass."""
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--no-header', '-x', *tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _apply(path: Path, old: str, new: str) -> None:
    """Replace exactly one occurrence of `old`, refusing an ambiguous mutant."""
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise LookupError(f'mutant text occurs {count} times in {path}: {old[:60]!r}')
    path.write_text(text.replace(old, new), encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    """Run every mutant, restore the sources, and report the survivors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', action='store_true', help='print each mutant as it runs')
    args = parser.parse_args(argv)

    survivors: list[str] = []
    broken: list[str] = []
    for index, mutant in enumerate(MUTANTS, start=1):
        path = ROOT / mutant.path
        original = path.read_bytes()
        before = _digest(path)
        try:
            _apply(path, mutant.old, mutant.new)
            killed = not _run_tests(mutant.tests)
        except LookupError as exc:
            broken.append(f'{mutant.name}: {exc}')
            killed = True
        finally:
            path.write_bytes(original)
            if _digest(path) != before:  # pragma: no cover - would mean days are over
                raise SystemExit(f'FAILED TO RESTORE {path}; restore it from git now')
        label = 'killed  ' if killed else 'SURVIVED'
        if args.verbose:
            print(f'[{index:2d}/{len(MUTANTS)}] {label} {mutant.name}')
        if not killed:
            survivors.append(mutant.name)
    for problem in broken:
        print(f'MALFORMED {problem}')
    print(
        f'{len(MUTANTS)} mutants, {len(MUTANTS) - len(survivors)} killed, {len(survivors)} survived'
    )
    for name in survivors:
        print(f'  SURVIVED {name}')
    return 0 if not broken else 2


if __name__ == '__main__':
    raise SystemExit(main())
