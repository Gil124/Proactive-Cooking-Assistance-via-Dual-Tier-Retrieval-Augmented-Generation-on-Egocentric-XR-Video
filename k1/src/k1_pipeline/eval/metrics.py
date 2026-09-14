"""
Eval -- Per-stage metrics computed from run artifacts vs frozen gold.
No LLM judge is used. Ontology, physics bounds, and gold labels are frozen files.

Fixes in v0.2.0:
  - L1: real Pydantic schema validation (not just "has ingredients")
  - L2: use physics.find_invented_temperatures (unit-bearing only)
  - L3: alias accuracy against entity_aliases.yaml
  - gold_comparison: safety bounds read from L3 fused graph
  - validate_gold_files: validate *.gold.json against GoldNode schema
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from k1_pipeline.models import GoldNode, K1Graph, K2Label, NodeType


# ── L1 metrics ────────────────────────────────────────────────────────────────

def l1_metrics(l1_dir: Path, recipes_dir: Path) -> dict:
    """
    Compute L1 ingest metrics.
    - schema_valid_pct: percentage of canonical.json files that pass Pydantic validation.
    - junk_drop_rate: from ingest_stats.json written by the runner.
    """
    from k1_pipeline.models import CanonicalRecipe

    canonical_files = list(recipes_dir.glob("*/canonical.json"))
    schema_valid = 0
    schema_errors = []

    for f in canonical_files:
        try:
            CanonicalRecipe.model_validate_json(f.read_text())
            schema_valid += 1
        except Exception as e:
            schema_errors.append(f"{f.parent.name}: {e}")

    # Junk-drop stats written by ingest/runner.py
    ingest_stats_path = l1_dir / "ingest_stats.json"
    junk_drop_rate = None
    if ingest_stats_path.exists():
        try:
            stats = json.loads(ingest_stats_path.read_text())
            kept = stats.get("steps_kept", 0)
            dropped = stats.get("steps_dropped", 0)
            total = kept + dropped
            junk_drop_rate = round(dropped / max(total, 1) * 100, 1)
        except Exception:
            pass

    return {
        "canonical_files": len(canonical_files),
        "schema_valid_pct": round(schema_valid / max(len(canonical_files), 1) * 100, 1),
        "schema_errors": schema_errors,
        "junk_drop_rate_pct": junk_drop_rate,
    }


# ── L2 metrics ────────────────────────────────────────────────────────────────

def l2_metrics(gen_dir: Path, critic_dir: Path, recipes_dir: Path) -> dict:
    from k1_pipeline.models import ExtractedNode
    from k1_pipeline.physics import find_invented_temperatures

    gen_files = list(gen_dir.glob("*.gen.json"))
    critic_files = list(critic_dir.glob("*.critic.json"))

    total = len(gen_files)
    span_grounded = 0
    k2_valid = 0
    verdict_counts = {"accept": 0, "revise": 0, "reject": 0}
    invented_temp_count = 0

    valid_k2 = {lbl.value for lbl in K2Label}

    for gen_file in gen_files:
        try:
            node = ExtractedNode.model_validate_json(gen_file.read_text())
        except Exception:
            continue

        recipe_id = node.recipe_id
        step_n = node.step_number

        # Source span groundedness
        canon_path = recipes_dir / recipe_id / "canonical.json"
        step_text = ""
        if canon_path.exists():
            recipe_raw = json.loads(canon_path.read_text())
            step = next((s for s in recipe_raw.get("steps", []) if s["number"] == step_n), None)
            if step:
                step_text = step["text"]
                if node.source_span in step_text:
                    span_grounded += 1

        # K2 label validity
        all_conds = node.pre_conditions + node.post_conditions
        if all(c.k2_label.value in valid_k2 for c in all_conds):
            k2_valid += 1

        # Invented temperature check (unit-bearing only)
        invented = find_invented_temperatures(node, step_text)
        if invented:
            invented_temp_count += 1

    for critic_file in critic_files:
        try:
            critic = json.loads(critic_file.read_text())
            v = critic.get("verdict", "unknown")
            if v in verdict_counts:
                verdict_counts[v] += 1
        except Exception:
            pass

    return {
        "total_steps": total,
        "span_groundedness_pct": round(span_grounded / max(total, 1) * 100, 1),
        "k2_label_validity_pct": round(k2_valid / max(total, 1) * 100, 1),
        "invented_temp_count": invented_temp_count,
        "critic_accept_pct": round(verdict_counts["accept"] / max(len(critic_files), 1) * 100, 1),
        "critic_revise_pct": round(verdict_counts["revise"] / max(len(critic_files), 1) * 100, 1),
        "critic_reject_pct": round(verdict_counts["reject"] / max(len(critic_files), 1) * 100, 1),
    }


# ── L3 metrics ────────────────────────────────────────────────────────────────

def l3_metrics(l3_dir: Path, gold_dir: Path | None = None) -> dict:
    fused_path = l3_dir / "fused_dag.json"
    if not fused_path.exists():
        return {"error": "fused_dag.json not found"}

    graph_raw = json.loads(fused_path.read_text())
    nodes = graph_raw.get("nodes", [])
    edges = graph_raw.get("edges", [])
    branch_labels = graph_raw.get("branch_labels", [])

    base = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "branch_count": len(branch_labels),
        "branch_labels": branch_labels,
        "safety_bound_edges": sum(1 for e in edges if e["edge_type"] == "HAS_SAFETY_BOUND"),
        "ingredient_nodes": len(graph_raw.get("ingredient_nodes", [])),
        "tool_nodes": len(graph_raw.get("tool_nodes", [])),
    }

    # Alias accuracy: % of aliases in entity_aliases.yaml that resolve to their canonical form.
    # File schema: {"aliases": [{"canonical": "egg", "aliases": ["eggs", "whole egg", ...]}, ...]}
    if gold_dir is not None:
        alias_path = gold_dir / "entity_aliases.yaml"
        if alias_path.exists():
            from k1_pipeline.fuse.entity_resolver import resolve_entity
            alias_data = yaml.safe_load(alias_path.read_text()) or {}
            entries = alias_data.get("aliases", [])
            total_aliases = 0
            correct_aliases = 0
            for entry in entries:
                canonical = entry.get("canonical")
                for alias in entry.get("aliases", []) or []:
                    total_aliases += 1
                    if resolve_entity(alias) == canonical:
                        correct_aliases += 1
            base["alias_accuracy_pct"] = round(correct_aliases / max(total_aliases, 1) * 100, 1)
            base["alias_total"] = total_aliases

            # Non-canonical entity_ids still in fused graph
            non_canonical = [
                c["entity_id"]
                for n in nodes
                for c in (n.get("pre_conditions", []) + n.get("post_conditions", []))
                if resolve_entity(c["entity_id"]) != c["entity_id"]
            ]
            base["non_canonical_entity_ids"] = sorted(set(non_canonical))

    return base


# ── L4 metrics ────────────────────────────────────────────────────────────────

def l4_metrics(l4_dir: Path) -> dict:
    report_path = l4_dir / "validation_report.txt"
    if not report_path.exists():
        return {"validation": "not run"}
    text = report_path.read_text()
    passed = "All 6 validation gates passed" in text
    errors = [line for line in text.splitlines() if "FAIL" in line]
    return {
        "all_gates_passed": passed,
        "gate_errors": errors,
    }


# ── Gold schema validation ────────────────────────────────────────────────────

def validate_gold_files(gold_dir: Path) -> list[str]:
    """
    Validate every *.gold.json against the GoldNode Pydantic schema.
    Returns a list of error strings (empty = all valid).
    """
    errors = []
    for gf in sorted(gold_dir.glob("*.gold.json")):
        try:
            GoldNode.model_validate_json(gf.read_text())
        except Exception as e:
            errors.append(f"{gf.name}: {e}")
    return errors


# ── Gold comparison ───────────────────────────────────────────────────────────

def gold_comparison(gen_dir: Path, l3_dir: Path, gold_dir: Path) -> dict:
    """
    Compare extracted nodes against frozen gold labels.
    Safety bounds are read from L3 fused graph (not L2 gen artifacts).
    """
    gold_files = list(gold_dir.glob("*.gold.json"))
    if not gold_files:
        return {"error": "No gold files found. Annotate gold recipes first."}

    # Build lookup: (recipe_id, step_number) -> K1Node from fused graph
    fused_path = l3_dir / "fused_dag.json"
    fused_node_map: dict[tuple[str, int], dict] = {}
    if fused_path.exists():
        graph_raw = json.loads(fused_path.read_text())
        for n in graph_raw.get("nodes", []):
            recipe_ids = n.get("source_recipe_ids", [])
            step_indices = n.get("source_step_indices", [])
            for rid, sidx in zip(recipe_ids, step_indices):
                fused_node_map[(rid, sidx)] = n

    node_type_tp = node_type_fp = node_type_fn = 0
    k2_correct = k2_total = 0
    safety_present = safety_expected = 0

    for gf in gold_files:
        gold = GoldNode.model_validate_json(gf.read_text())
        recipe_id = gold.recipe_id
        step_n = gold.step_number

        # L2 gen artifact for node_type and k2 labels
        gen_file = gen_dir / f"{recipe_id}_step{step_n:02d}.gen.json"
        if not gen_file.exists():
            node_type_fn += 1
            continue

        extracted_raw = json.loads(gen_file.read_text())

        # Node type
        if extracted_raw.get("node_type") == gold.expected.node_type.value:
            node_type_tp += 1
        else:
            node_type_fp += 1
            node_type_fn += 1

        # K2 label accuracy (per entity, post_conditions)
        gold_post = {c.entity_id: c.k2_label.value for c in gold.expected.post_conditions}
        ext_post = {c.get("entity_id"): c.get("k2_label") for c in extracted_raw.get("post_conditions", [])}
        for eid, gl in gold_post.items():
            k2_total += 1
            if ext_post.get(eid) == gl:
                k2_correct += 1

        # Safety bound coverage: check fused graph node (not L2 artifact)
        if gold.expected.has_safety_bound:
            safety_expected += 1
            fused_node = fused_node_map.get((recipe_id, step_n))
            if fused_node and fused_node.get("safety_bounds"):
                safety_present += 1

    precision = node_type_tp / max(node_type_tp + node_type_fp, 1)
    recall = node_type_tp / max(node_type_tp + node_type_fn, 1)

    return {
        "gold_recipes_evaluated": len(gold_files),
        "node_type_precision": round(precision, 3),
        "node_type_recall": round(recall, 3),
        "k2_label_accuracy_pct": round(k2_correct / max(k2_total, 1) * 100, 1),
        "safety_bound_coverage_pct": round(safety_present / max(safety_expected, 1) * 100, 1),
    }


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(run_id: str, run_dir: Path, recipes_dir: Path, gold_dir: Path) -> str:
    """Compute all metrics and write a Markdown report. Returns the report text."""
    l1 = l1_metrics(run_dir / "L1", recipes_dir)
    l2 = l2_metrics(run_dir / "L2" / "gen", run_dir / "L2" / "critic", recipes_dir)
    l3 = l3_metrics(run_dir / "L3", gold_dir)
    l4 = l4_metrics(run_dir / "L4")
    gold = gold_comparison(run_dir / "L2" / "gen", run_dir / "L3", gold_dir)

    alias_line = (
        f"| Alias accuracy | {l3.get('alias_accuracy_pct', 'N/A')}% "
        f"({l3.get('alias_total', 0)} aliases) |"
    )

    report = f"""# K1 Eval Report — Run `{run_id}`

## L1 Ingest
| Metric | Value |
|---|---|
| Canonical files | {l1.get('canonical_files')} |
| Schema valid | {l1.get('schema_valid_pct')}% |
| Junk drop rate | {l1.get('junk_drop_rate_pct', 'N/A')}% |

## L2 Extraction
| Metric | Value |
|---|---|
| Total steps extracted | {l2.get('total_steps')} |
| Span groundedness | {l2.get('span_groundedness_pct')}% |
| K2 label validity | {l2.get('k2_label_validity_pct')}% |
| Invented temperature count | {l2.get('invented_temp_count')} |
| Critic accept rate | {l2.get('critic_accept_pct')}% |
| Critic revise rate | {l2.get('critic_revise_pct')}% |
| Critic reject rate | {l2.get('critic_reject_pct')}% |

## L3 Fusion
| Metric | Value |
|---|---|
| Total K1 nodes | {l3.get('total_nodes')} |
| Total edges | {l3.get('total_edges')} |
| Branch count | {l3.get('branch_count')} |
| Branch labels | {', '.join(l3.get('branch_labels', []))} |
| HAS_SAFETY_BOUND edges | {l3.get('safety_bound_edges')} |
{alias_line}

## L4 Validation
| Metric | Value |
|---|---|
| All gates passed | {l4.get('all_gates_passed')} |
| Gate errors | {len(l4.get('gate_errors', []))} |

{chr(10).join(f'- {e}' for e in l4.get('gate_errors', []))}

## Gold Comparison (vs frozen gold labels)
| Metric | Value |
|---|---|
| Gold recipes evaluated | {gold.get('gold_recipes_evaluated', 0)} |
| Node-type precision | {gold.get('node_type_precision', 'N/A')} |
| Node-type recall | {gold.get('node_type_recall', 'N/A')} |
| K2 label accuracy | {gold.get('k2_label_accuracy_pct', 'N/A')}% |
| Safety-bound coverage | {gold.get('safety_bound_coverage_pct', 'N/A')}% |

{gold.get('error', '')}
"""

    report_dir = run_dir / "eval"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.md"
    report_path.write_text(report)
    return report
