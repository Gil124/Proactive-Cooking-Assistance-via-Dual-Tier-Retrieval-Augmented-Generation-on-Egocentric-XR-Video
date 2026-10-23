"""
Eval -- Pipeline output versus human review.

Answers three questions from the reviewed steps in data/gold/, with no manual
counting (Notes/09-k1-evaluation.md):

  1. Accuracy: how often did the pipeline get a step right?
  2. Correction effort: how much did the reviewer have to change?
  3. Time: how long did correcting take, against annotating from scratch?

Only gold files saved under the current definition_version are counted.
Writes eval/correction.json and eval/correction_steps.csv next to report.md.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from k1_pipeline.gold import (
    MODE_CORRECTED,
    MODE_FROM_SCRATCH,
    auto_step,
    is_current,
    load_gold,
    load_queue,
)

# Fields compared on a step that both sides keep. action_phrase is reported
# separately: rewording it does not change what the graph means.
STRUCTURAL_FIELDS = ("node_type", "pre_conditions", "post_conditions", "tools", "has_safety_bound")
ALL_FIELDS = STRUCTURAL_FIELDS + ("action_phrase",)


def _norm_action(text: str) -> str:
    return " ".join(str(text).lower().split())


def _cond_set(items: list[dict]) -> set[tuple[str, str]]:
    return {(c["entity_id"], c["k2_label"]) for c in items}


def _field_equal(field: str, auto: dict, gold: dict) -> bool:
    if field in ("pre_conditions", "post_conditions"):
        return _cond_set(auto[field]) == _cond_set(gold[field])
    if field == "tools":
        return set(auto["tools"]) == set(gold["tools"])
    if field == "action_phrase":
        return _norm_action(auto[field]) == _norm_action(gold[field])
    return auto[field] == gold[field]


def compare_step(auto: dict, gold_expected: dict) -> dict:
    """
    Compare the pipeline's step with the reviewed step.

    `auto` is gold.auto_step(...); `gold_expected` is GoldExpected as a dict.
    Returns the scope outcome and, when both keep the step, the fields changed.
    """
    auto_in = auto["status"] == "kept"
    gold_in = bool(gold_expected.get("in_scope", True))
    row: dict = {
        "auto_status": auto["status"],
        "auto_in_scope": auto_in,
        "gold_in_scope": gold_in,
        "scope_agrees": auto_in == gold_in,
        "fields_changed": [],
        "unchanged": False,
        "unchanged_ignoring_wording": False,
    }
    if auto_in and gold_in:
        changed = [f for f in ALL_FIELDS if not _field_equal(f, auto["expected"], gold_expected)]
        row["fields_changed"] = changed
        row["unchanged"] = not changed
        row["unchanged_ignoring_wording"] = not [f for f in changed if f != "action_phrase"]
        for side in ("pre_conditions", "post_conditions"):
            a, g = _cond_set(auto["expected"][side]), _cond_set(gold_expected[side])
            row[f"{side}_tp"] = len(a & g)
            row[f"{side}_fp"] = len(a - g)
            row[f"{side}_fn"] = len(g - a)
    elif not auto_in and not gold_in:
        # Both leave the step out: nothing for the reviewer to fix.
        row["unchanged"] = True
        row["unchanged_ignoring_wording"] = True
    return row


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    return {k: (round(v, 3) if v is not None else None) for k, v in (("precision", p), ("recall", r), ("f1", f))}


def _time_stats(rows: list[dict]) -> dict:
    secs = [r["seconds_spent"] for r in rows if r["seconds_spent"] is not None]
    return {
        "steps": len(rows),
        "steps_timed": len(secs),
        "total_minutes": round(sum(secs) / 60, 1) if secs else None,
        "mean_seconds_per_step": round(statistics.mean(secs), 1) if secs else None,
        "median_seconds_per_step": round(statistics.median(secs), 1) if secs else None,
    }


def _accuracy_block(rows: list[dict]) -> dict:
    """Agreement between pipeline and review over a set of steps."""
    n = len(rows)
    both = [r for r in rows if r["auto_in_scope"] and r["gold_in_scope"]]
    field_acc = {
        f: _pct(sum(1 for r in both if f not in r["fields_changed"]), len(both))
        for f in ALL_FIELDS
    }
    conds = {
        side: _prf(
            sum(r.get(f"{side}_tp", 0) for r in both),
            sum(r.get(f"{side}_fp", 0) for r in both),
            sum(r.get(f"{side}_fn", 0) for r in both),
        )
        for side in ("pre_conditions", "post_conditions")
    }
    return {
        "steps": n,
        "scope_agreement_pct": _pct(sum(1 for r in rows if r["scope_agrees"]), n),
        "wrongly_kept": sum(1 for r in rows if r["auto_in_scope"] and not r["gold_in_scope"]),
        "wrongly_dropped": sum(1 for r in rows if not r["auto_in_scope"] and r["gold_in_scope"]),
        "steps_kept_by_both": len(both),
        "field_accuracy_pct": field_acc,
        "condition_scores": conds,
        "unchanged_pct": _pct(sum(1 for r in rows if r["unchanged"]), n),
        "unchanged_ignoring_wording_pct": _pct(
            sum(1 for r in rows if r["unchanged_ignoring_wording"]), n
        ),
    }


def correction_metrics(run_id: str, run_dir: Path, recipes_dir: Path, gold_dir: Path) -> dict:
    """Everything the report needs, as one JSON-serialisable dict."""
    queue = load_queue(recipes_dir)
    rows: list[dict] = []
    total_steps = 0
    outdated = 0
    other_run = 0

    for recipe in queue:
        for step in recipe.steps:
            total_steps += 1
            gold = load_gold(gold_dir, recipe.recipe_id, step.number)
            if gold is None:
                continue
            if not is_current(gold):
                outdated += 1
                continue
            if gold.seeded_from_run and gold.seeded_from_run != run_id:
                other_run += 1
            auto = auto_step(run_dir, recipe.recipe_id, step.number)
            row = {
                "recipe_id": recipe.recipe_id,
                "step_number": step.number,
                "mode": gold.mode or MODE_CORRECTED,
                "seconds_spent": gold.seconds_spent,
                "seeded_from_run": gold.seeded_from_run,
                "auto_reason": auto["reason"],
            }
            row.update(compare_step(auto, gold.expected.model_dump(mode="json")))
            rows.append(row)

    corrected = [r for r in rows if r["mode"] == MODE_CORRECTED]
    scratch = [r for r in rows if r["mode"] == MODE_FROM_SCRATCH]

    edits_by_field = {
        f: sum(1 for r in rows if f in r["fields_changed"]) for f in ALL_FIELDS
    }
    scope_fixes = sum(1 for r in rows if not r["scope_agrees"])
    total_edits = sum(edits_by_field.values()) + scope_fixes

    t_corr, t_scratch = _time_stats(corrected), _time_stats(scratch)
    saving = None
    if t_corr["mean_seconds_per_step"] is not None and t_scratch["mean_seconds_per_step"] is not None:
        per_step = t_scratch["mean_seconds_per_step"] - t_corr["mean_seconds_per_step"]
        saving = {
            "seconds_saved_per_step": round(per_step, 1),
            "pct_saved_per_step": _pct(round(per_step), round(t_scratch["mean_seconds_per_step"])),
            "by_hand_estimate_minutes_all_steps": round(
                t_scratch["mean_seconds_per_step"] * total_steps / 60, 1
            ),
            "corrected_estimate_minutes_all_steps": round(
                t_corr["mean_seconds_per_step"] * total_steps / 60, 1
            ),
        }

    return {
        "run_id": run_id,
        "coverage": {
            "recipes_in_queue": len(queue),
            "steps_in_queue": total_steps,
            "steps_reviewed": len(rows),
            "steps_reviewed_pct": _pct(len(rows), total_steps),
            "gold_files_out_of_date": outdated,
            "reviewed_against_another_run": other_run,
        },
        "accuracy_all": _accuracy_block(rows),
        # Not anchored by the pipeline output: the fairer accuracy figure.
        "accuracy_from_scratch": _accuracy_block(scratch),
        "accuracy_corrected": _accuracy_block(corrected),
        "effort": {
            "total_edits": total_edits,
            "edits_per_step": round(total_edits / len(rows), 2) if rows else None,
            "scope_fixes": scope_fixes,
            "edits_by_field": edits_by_field,
        },
        "time": {"corrected": t_corr, "from_scratch": t_scratch, "saving": saving},
        "graph": graph_diff(run_dir),
        "steps": rows,
    }


def graph_diff(run_dir: Path) -> dict | None:
    """Pipeline graph versus the reviewed graph, once `k1 finalize` has been run."""
    auto_path = run_dir / "L3" / "fused_dag.json"
    final_path = run_dir / "final" / "L3" / "fused_dag.json"
    if not (auto_path.exists() and final_path.exists()):
        return None
    auto = json.loads(auto_path.read_text())
    final = json.loads(final_path.read_text())

    def _summary(g: dict) -> dict:
        nodes = g.get("nodes", [])
        return {
            "nodes": len(nodes),
            "next_edges": sum(1 for e in g.get("edges", []) if e["edge_type"] == "NEXT"),
            "nodes_shared_by_recipes": sum(
                1 for n in nodes if len(set(n.get("source_recipe_ids", []))) > 1
            ),
        }

    # node_id is the fingerprint of (type, action, k2 pre, k2 post).
    a_ids = {n["node_id"] for n in auto.get("nodes", [])}
    f_ids = {n["node_id"] for n in final.get("nodes", [])}
    return {
        "auto": _summary(auto),
        "final": _summary(final),
        "nodes_identical": len(a_ids & f_ids),
        "nodes_only_in_auto": len(a_ids - f_ids),
        "nodes_only_in_final": len(f_ids - a_ids),
        "auto_nodes_kept_pct": _pct(len(a_ids & f_ids), len(a_ids)),
    }


# ── Output ────────────────────────────────────────────────────────────────────

def _v(value, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def render_section(m: dict) -> str:
    cov, eff, tm = m["coverage"], m["effort"], m["time"]
    acc, acc_s = m["accuracy_all"], m["accuracy_from_scratch"]

    lines = [
        "## Human review (pipeline output vs reviewed steps)",
        "",
        "### Coverage",
        "| Metric | Value |",
        "|---|---|",
        f"| Steps reviewed | {cov['steps_reviewed']}/{cov['steps_in_queue']} ({_v(cov['steps_reviewed_pct'], '%')}) |",
        f"| Gold files out of date (not counted) | {cov['gold_files_out_of_date']} |",
        f"| Reviewed against another run | {cov['reviewed_against_another_run']} |",
        "",
        "### Accuracy",
        "| Metric | All reviewed | From scratch only |",
        "|---|---|---|",
        f"| Steps | {acc['steps']} | {acc_s['steps']} |",
        f"| Keep/drop decision agrees | {_v(acc['scope_agreement_pct'], '%')} | {_v(acc_s['scope_agreement_pct'], '%')} |",
        f"| Wrongly kept / wrongly dropped | {acc['wrongly_kept']} / {acc['wrongly_dropped']} | {acc_s['wrongly_kept']} / {acc_s['wrongly_dropped']} |",
    ]
    for field in ALL_FIELDS:
        lines.append(
            f"| `{field}` correct | {_v(acc['field_accuracy_pct'][field], '%')} "
            f"| {_v(acc_s['field_accuracy_pct'][field], '%')} |"
        )
    for side in ("pre_conditions", "post_conditions"):
        a, s = acc["condition_scores"][side], acc_s["condition_scores"][side]
        lines.append(
            f"| `{side}` P / R / F1 | {_v(a['precision'])} / {_v(a['recall'])} / {_v(a['f1'])} "
            f"| {_v(s['precision'])} / {_v(s['recall'])} / {_v(s['f1'])} |"
        )
    lines += [
        f"| Steps needing no change | {_v(acc['unchanged_pct'], '%')} | {_v(acc_s['unchanged_pct'], '%')} |",
        f"| Steps needing no change, ignoring wording | {_v(acc['unchanged_ignoring_wording_pct'], '%')} | {_v(acc_s['unchanged_ignoring_wording_pct'], '%')} |",
        "",
        "### Correction effort",
        "| Metric | Value |",
        "|---|---|",
        f"| Total edits | {eff['total_edits']} |",
        f"| Edits per step | {_v(eff['edits_per_step'])} |",
        f"| Keep/drop fixes | {eff['scope_fixes']} |",
    ]
    lines += [f"| `{f}` edits | {n} |" for f, n in eff["edits_by_field"].items()]
    lines += [
        "",
        "### Time",
        "| Metric | Corrected | From scratch |",
        "|---|---|---|",
        f"| Steps timed | {tm['corrected']['steps_timed']} | {tm['from_scratch']['steps_timed']} |",
        f"| Total minutes | {_v(tm['corrected']['total_minutes'])} | {_v(tm['from_scratch']['total_minutes'])} |",
        f"| Mean seconds per step | {_v(tm['corrected']['mean_seconds_per_step'])} | {_v(tm['from_scratch']['mean_seconds_per_step'])} |",
        f"| Median seconds per step | {_v(tm['corrected']['median_seconds_per_step'])} | {_v(tm['from_scratch']['median_seconds_per_step'])} |",
    ]
    if tm["saving"]:
        s = tm["saving"]
        lines += [
            "",
            f"Correcting saves {s['seconds_saved_per_step']} s per step "
            f"({_v(s['pct_saved_per_step'], '%')}). Over all {cov['steps_in_queue']} steps: "
            f"about {s['by_hand_estimate_minutes_all_steps']} min by hand against "
            f"{s['corrected_estimate_minutes_all_steps']} min correcting.",
        ]
    g = m["graph"]
    lines += ["", "### Graph (pipeline vs reviewed)"]
    if g is None:
        lines.append("Run `k1 finalize --run <run_id>` to build the reviewed graph.")
    else:
        lines += [
            "| Metric | Pipeline | Reviewed |",
            "|---|---|---|",
            f"| Nodes | {g['auto']['nodes']} | {g['final']['nodes']} |",
            f"| NEXT edges | {g['auto']['next_edges']} | {g['final']['next_edges']} |",
            f"| Nodes shared by several recipes | {g['auto']['nodes_shared_by_recipes']} | {g['final']['nodes_shared_by_recipes']} |",
            "",
            f"{g['nodes_identical']} nodes are identical in both ({_v(g['auto_nodes_kept_pct'], '%')} "
            f"of the pipeline's), {g['nodes_only_in_auto']} exist only in the pipeline graph, "
            f"{g['nodes_only_in_final']} only in the reviewed graph.",
        ]
    return "\n".join(lines) + "\n"


def write_outputs(m: dict, eval_dir: Path) -> None:
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "correction.json").write_text(json.dumps(m, indent=2))
    columns = [
        "recipe_id", "step_number", "mode", "seconds_spent", "auto_status", "auto_reason",
        "gold_in_scope", "scope_agrees", "fields_changed", "unchanged",
        "unchanged_ignoring_wording",
    ]
    with open(eval_dir / "correction_steps.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in m["steps"]:
            writer.writerow({**row, "fields_changed": ";".join(row["fields_changed"])})
