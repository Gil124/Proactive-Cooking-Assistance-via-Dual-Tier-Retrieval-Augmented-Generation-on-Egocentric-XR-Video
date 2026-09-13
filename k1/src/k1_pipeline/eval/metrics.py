"""
Eval -- Per-stage metrics computed from run artifacts vs frozen gold.
No LLM judge is used. Ontology, physics bounds, and gold labels are frozen files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from k1_pipeline.config_loader import load_physics_bounds
from k1_pipeline.models import K1Graph, K2Label, NodeType

_PHYSICS_BOUNDS = load_physics_bounds()
_KNOWN_TEMPS = {b["temperature_c"] for b in _PHYSICS_BOUNDS if b["temperature_c"] is not None}
_TEMP_RE = re.compile(r"\b(\d{2,3})\b")


# ── L1 metrics ────────────────────────────────────────────────────────────────

def l1_metrics(l1_dir: Path, recipes_dir: Path) -> dict:
    canonical_files = list(l1_dir.glob("*.canonical.json"))
    schema_valid = 0
    missing_ingredients = 0

    for f in canonical_files:
        try:
            data = json.loads(f.read_text())
            if data.get("ingredients"):
                schema_valid += 1
            else:
                missing_ingredients += 1
        except Exception:
            pass

    return {
        "canonical_files": len(canonical_files),
        "schema_valid_pct": round(schema_valid / max(len(canonical_files), 1) * 100, 1),
        "missing_ingredient_recipes": missing_ingredients,
    }


# ── L2 metrics ────────────────────────────────────────────────────────────────

def l2_metrics(gen_dir: Path, critic_dir: Path, recipes_dir: Path) -> dict:
    gen_files = list(gen_dir.glob("*.gen.json"))
    critic_files = list(critic_dir.glob("*.critic.json"))

    total = len(gen_files)
    span_grounded = 0
    k2_valid = 0
    verdict_counts = {"accept": 0, "revise": 0, "reject": 0, "unknown": 0}
    invented_temp_count = 0

    valid_k2 = {lbl.value for lbl in K2Label}

    for gen_file in gen_files:
        node = json.loads(gen_file.read_text())
        recipe_id = node.get("recipe_id", "")
        step_n = node.get("step_number", 0)

        # Source span groundedness
        canon_path = recipes_dir / recipe_id / "canonical.json"
        if canon_path.exists():
            recipe = json.loads(canon_path.read_text())
            step = next((s for s in recipe.get("steps", []) if s["number"] == step_n), None)
            if step and node.get("source_span", "") in step["text"]:
                span_grounded += 1

        # K2 label validity
        all_conds = node.get("pre_conditions", []) + node.get("post_conditions", [])
        if all(c.get("k2_label") in valid_k2 for c in all_conds):
            k2_valid += 1

        # Invented temperature check
        node_text = json.dumps(node)
        step_text = step["text"] if step else ""
        node_temps = {float(m.group(1)) for m in _TEMP_RE.finditer(node_text)}
        step_temps = {float(m.group(1)) for m in _TEMP_RE.finditer(step_text)}
        if any(t not in step_temps and t not in _KNOWN_TEMPS for t in node_temps):
            invented_temp_count += 1

    for critic_file in critic_files:
        try:
            critic = json.loads(critic_file.read_text())
            v = critic.get("verdict", "unknown")
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
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

def l3_metrics(l3_dir: Path) -> dict:
    fused_path = l3_dir / "fused_dag.json"
    if not fused_path.exists():
        return {"error": "fused_dag.json not found"}

    graph = json.loads(fused_path.read_text())
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    branch_labels = graph.get("branch_labels", [])

    # Check NEXT edge acyclicity (rough check)
    next_edges = [(e["from_node_id"], e["to_node_id"]) for e in edges if e["edge_type"] == "NEXT"]
    node_ids = {n["node_id"] for n in nodes}

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "branch_count": len(branch_labels),
        "branch_labels": branch_labels,
        "safety_bound_edges": sum(1 for e in edges if e["edge_type"] == "HAS_SAFETY_BOUND"),
        "ingredient_nodes": len(graph.get("ingredient_nodes", [])),
        "tool_nodes": len(graph.get("tool_nodes", [])),
    }


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


# ── Gold comparison ───────────────────────────────────────────────────────────

def gold_comparison(gen_dir: Path, gold_dir: Path) -> dict:
    """Compare extracted nodes against frozen gold labels."""
    gold_files = list(gold_dir.glob("*.gold.json"))
    if not gold_files:
        return {"error": "No gold files found. Annotate gold recipes first."}

    node_type_tp = node_type_fp = node_type_fn = 0
    k2_correct = k2_total = 0
    safety_present = safety_expected = 0

    for gf in gold_files:
        gold = json.loads(gf.read_text())
        recipe_id = gold["recipe_id"]
        step_n = gold["step_number"]

        gen_file = gen_dir / f"{recipe_id}_step{step_n:02d}.gen.json"
        if not gen_file.exists():
            node_type_fn += 1
            continue

        extracted = json.loads(gen_file.read_text())

        # Node type
        if extracted.get("node_type") == gold["expected"].get("node_type"):
            node_type_tp += 1
        else:
            node_type_fp += 1
            node_type_fn += 1

        # K2 label accuracy (per entity)
        gold_post = {c["entity_id"]: c["k2_label"] for c in gold["expected"].get("post_conditions", [])}
        ext_post = {c.get("entity_id"): c.get("k2_label") for c in extracted.get("post_conditions", [])}
        for eid, gl in gold_post.items():
            k2_total += 1
            if ext_post.get(eid) == gl:
                k2_correct += 1

        # Safety bound coverage
        if gold["expected"].get("has_safety_bound"):
            safety_expected += 1
            if extracted.get("safety_bounds"):
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
    """
    Compute all metrics and write a Markdown report.
    Returns the report text.
    """
    l1 = l1_metrics(run_dir / "L1", recipes_dir)
    l2 = l2_metrics(run_dir / "L2" / "gen", run_dir / "L2" / "critic", recipes_dir)
    l3 = l3_metrics(run_dir / "L3")
    l4 = l4_metrics(run_dir / "L4")
    gold = gold_comparison(run_dir / "L2" / "gen", gold_dir)

    report = f"""# K1 Eval Report — Run `{run_id}`

## L1 Ingest
| Metric | Value |
|---|---|
| Canonical files | {l1.get('canonical_files')} |
| Schema valid | {l1.get('schema_valid_pct')}% |
| Missing ingredient recipes | {l1.get('missing_ingredient_recipes')} |

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
