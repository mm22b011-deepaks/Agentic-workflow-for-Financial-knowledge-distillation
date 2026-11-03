"""Catch stale curated mutations before the slower mutation run starts."""

from __future__ import annotations

import runpy
from pathlib import Path


def test_curated_mutations_match_current_source() -> None:
    root = Path(__file__).resolve().parents[2]
    mutations = runpy.run_path(str(root / 'scripts/mutation_check.py'))['MUTANTS']
    invalid = {
        mutant.name: (root / mutant.path).read_text().count(mutant.old)
        for mutant in mutations
        if (root / mutant.path).read_text().count(mutant.old) != 1
    }
    assert not invalid, f'Mutation targets must match exactly once: {invalid}'
