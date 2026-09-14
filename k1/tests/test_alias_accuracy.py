"""
Regression test for l3_metrics alias accuracy against the real
data/gold/entity_aliases.yaml schema: {"aliases": [{"canonical": ..., "aliases": [...]}]}.

Found via the k1-0.2.1 smoke test: l3_metrics originally assumed a flat
{canonical: [alias, ...]} mapping and crashed with
AttributeError: 'dict' object has no attribute 'lower' on the real file.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from k1_pipeline.eval.metrics import l3_metrics


def _write_fused_dag(l3_dir: Path) -> None:
    l3_dir.mkdir(parents=True, exist_ok=True)
    (l3_dir / "fused_dag.json").write_text(
        '{"nodes": [], "edges": [], "branch_labels": [], '
        '"ingredient_nodes": [], "tool_nodes": []}'
    )


def test_alias_accuracy_handles_real_schema():
    """
    entity_aliases.yaml uses {"aliases": [{"canonical": "egg", "aliases": ["eggs", ...]}]},
    NOT a flat {canonical: [alias, ...]} dict. l3_metrics must not crash on this shape.
    """
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        gold_dir = Path(tmp) / "gold"
        gold_dir.mkdir(parents=True)
        _write_fused_dag(run_dir)

        alias_data = {
            "aliases": [
                {"canonical": "egg", "aliases": ["eggs", "whole egg"]},
                {"canonical": "butter", "aliases": ["unsalted butter"]},
            ]
        }
        (gold_dir / "entity_aliases.yaml").write_text(yaml.dump(alias_data))

        result = l3_metrics(run_dir, gold_dir)

        assert "alias_accuracy_pct" in result
        assert result["alias_total"] == 3
        assert 0.0 <= result["alias_accuracy_pct"] <= 100.0


def test_alias_accuracy_missing_file_does_not_crash():
    """If entity_aliases.yaml is absent, l3_metrics must not error."""
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        gold_dir = Path(tmp) / "gold"
        gold_dir.mkdir(parents=True)
        _write_fused_dag(run_dir)

        result = l3_metrics(run_dir, gold_dir)
        assert "alias_accuracy_pct" not in result  # skipped entirely, not crashed


def test_alias_accuracy_against_real_gold_file():
    """Sanity check against the actual project gold file (schema-only, no LLM)."""
    real_gold_dir = Path(__file__).parent.parent / "data" / "gold"
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        _write_fused_dag(run_dir)
        result = l3_metrics(run_dir, real_gold_dir)
        assert result["alias_total"] > 0
        assert 0.0 <= result["alias_accuracy_pct"] <= 100.0
