"""
K1 Graph Visualizer + Review UI
Streamlit application -- JSON-first (does not require Neo4j).

Tabs:
  1. Graph -- interactive Pyvis graph of the fused DAG
  2. Review -- side-by-side: step text | generator JSON | critic verdict
  3. Gold set -- annotate the review queue into data/gold/*.gold.json

Usage:
  uv run streamlit run src/k1_pipeline/viz/app.py -- --run <run_id>
  # or without a run ID to browse all available runs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent.parent.parent.parent  # k1/
DATA = ROOT / "data"

# ── Color scheme ──────────────────────────────────────────────────────────────

NODE_COLORS = {
    "Process":     "#4A90D9",   # Blue
    "Transfer":    "#7ED321",   # Green
    "Plate":       "#F5A623",   # Orange
    "Ingredient":  "#9B9B9B",   # Gray
    "Tool":        "#BB8FCE",   # Lilac
    "SafetyBound": "#E74C3C",   # Red -- HAS_SAFETY_BOUND targets
}
SAFETY_EDGE_COLOR = "#E74C3C"
DEFAULT_EDGE_COLOR = "#AAAAAA"

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="K1 Graph", layout="wide", initial_sidebar_state="expanded")

# ── Parse --run from sys.argv (passed by `k1 viz --run <id>`) ─────────────────

_cli_run_id: str | None = None
_argv = sys.argv
if "--run" in _argv:
    _idx = _argv.index("--run")
    if _idx + 1 < len(_argv):
        _cli_run_id = _argv[_idx + 1]

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("K1 Knowledge Graph")
    st.markdown("---")

    # Run selector -- preselect the run passed via --run if present
    runs_dir = DATA / "artifacts" / "runs"
    available_runs = sorted([d.name for d in runs_dir.iterdir() if d.is_dir()]) if runs_dir.exists() else []
    if not available_runs:
        st.warning("No runs found. Run `k1 run` first.")
        st.stop()

    default_idx = len(available_runs) - 1
    if _cli_run_id and _cli_run_id in available_runs:
        default_idx = available_runs.index(_cli_run_id)

    run_id = st.selectbox("Run", available_runs, index=default_idx)
    run_dir = runs_dir / run_id

    # Load graph.json for this run
    graph_path = run_dir / "L4" / "graph.json"
    if not graph_path.exists():
        # Try the global k1/data/k1/graph.json
        graph_path = DATA / "k1" / "graph.json"

    if not graph_path.exists():
        st.error("graph.json not found for this run. Run `k1 validate` to generate it.")
        st.stop()

    with open(graph_path) as f:
        graph_data = json.load(f)

    branch_labels = graph_data.get("branch_labels", [])
    selected_branch = st.selectbox("Branch filter", ["All"] + branch_labels)

    st.markdown("---")
    st.subheader("Node types")
    visible_types = st.multiselect(
        "Show",
        list(NODE_COLORS.keys()),
        default=list(NODE_COLORS.keys()),
    )

    show_safety = st.checkbox("Highlight safety bounds", value=True)
    st.markdown("---")
    st.caption(f"Run: `{run_id}`")


# ── Main tabs ─────────────────────────────────────────────────────────────────

tab_graph, tab_review, tab_gold = st.tabs(["Graph", "Review", "Gold set"])

# ── Tab 1: Graph ──────────────────────────────────────────────────────────────

with tab_graph:
    try:
        from pyvis.network import Network
    except ImportError:
        st.error("pyvis not installed. Run: uv add pyvis")
        st.stop()

    net = Network(height="700px", width="100%", directed=True, bgcolor="#1a1a2e", font_color="white")
    net.set_options("""
    {
      "physics": {"solver": "barnesHut", "barnesHut": {"gravitationalConstant": -8000}},
      "edges": {"arrows": {"to": {"enabled": true}}},
      "interaction": {"navigationButtons": true, "keyboard": true}
    }
    """)

    # Filter nodes by branch
    if selected_branch != "All":
        branch_node_ids: set[str] = set()
        for node in graph_data.get("nodes", []):
            if selected_branch in node.get("source_recipe_ids", []):
                branch_node_ids.add(node["node_id"])
    else:
        branch_node_ids = None  # show all

    # Add K1 nodes
    for node in graph_data.get("nodes", []):
        nid = node["node_id"]
        if branch_node_ids is not None and nid not in branch_node_ids:
            continue
        ntype = node.get("node_type", "Process")
        if ntype not in visible_types:
            continue
        color = NODE_COLORS.get(ntype, "#CCCCCC")
        has_safety = bool(node.get("safety_bounds"))
        border_color = SAFETY_EDGE_COLOR if (show_safety and has_safety) else color
        label = node.get("action_phrase", nid)[:30]
        title = (
            f"<b>{ntype}</b>: {node.get('action_phrase', '')}<br>"
            f"<b>Confidence:</b> {node.get('mean_confidence', 0):.2f}<br>"
            f"<b>Recipes:</b> {', '.join(node.get('source_recipe_ids', []))}<br>"
            f"<b>Quote:</b> {'; '.join(node.get('source_spans', [])[:2])}"
        )
        net.add_node(nid, label=label, color={"background": color, "border": border_color},
                     title=title, shape="ellipse" if ntype == "Process" else "box")

    # Ingredient / Tool nodes
    if "Ingredient" in visible_types:
        for ing in graph_data.get("ingredient_nodes", []):
            net.add_node(ing["id"], label=ing["name"], color=NODE_COLORS["Ingredient"],
                         shape="diamond", size=10)
    if "Tool" in visible_types:
        for tool in graph_data.get("tool_nodes", []):
            net.add_node(tool["id"], label=tool["name"], color=NODE_COLORS["Tool"],
                         shape="triangle", size=10)

    # SafetyBound nodes (virtual -- created from edges)
    safety_bound_ids: set[str] = set()
    for edge in graph_data.get("edges", []):
        if edge.get("edge_type") == "HAS_SAFETY_BOUND":
            safety_bound_ids.add(edge["to_node_id"])
    if "SafetyBound" in visible_types:
        for bid in safety_bound_ids:
            net.add_node(bid, label=bid.replace("bound_", "").replace("_", " "),
                         color=NODE_COLORS["SafetyBound"], shape="star", size=12)

    # Add edges
    for edge in graph_data.get("edges", []):
        from_id = edge["from_node_id"]
        to_id = edge["to_node_id"]
        etype = edge.get("edge_type", "")
        color = SAFETY_EDGE_COLOR if (etype == "HAS_SAFETY_BOUND" and show_safety) else DEFAULT_EDGE_COLOR
        width = 2 if etype == "NEXT" else 1
        net.add_edge(from_id, to_id, label=etype, color=color, width=width)

    html = net.generate_html()
    components.html(html, height=720)

    # Node detail
    st.subheader("Node details")
    node_ids = [n["node_id"] for n in graph_data.get("nodes", [])]
    selected_node_id = st.selectbox("Select node", [""] + node_ids)
    if selected_node_id:
        node = next(n for n in graph_data["nodes"] if n["node_id"] == selected_node_id)
        col1, col2 = st.columns(2)
        with col1:
            st.json({k: v for k, v in node.items() if k not in ("pre_conditions", "post_conditions", "safety_bounds")})
        with col2:
            st.markdown("**Pre-conditions**")
            st.json(node.get("pre_conditions", []))
            st.markdown("**Post-conditions**")
            st.json(node.get("post_conditions", []))
            if node.get("safety_bounds"):
                st.markdown("**Safety bounds** (HAS_SAFETY_BOUND)")
                st.json(node["safety_bounds"])

# ── Tab 2: Review ──────────────────────────────────────────────────────────────

with tab_review:
    st.subheader("Step-by-step extraction review")
    st.caption("Compare source text, the extraction, and the critic. Gold labels are written from the Gold set tab.")

    gen_dir = run_dir / "L2" / "gen"
    critic_dir = run_dir / "L2" / "critic"

    gen_files = sorted(gen_dir.glob("*.gen.json")) if gen_dir.exists() else []
    if not gen_files:
        st.info("No extraction artifacts found for this run. Run `k1 extract` first.")
    else:
        # Load canonical recipes for source text
        recipes_dir = DATA / "recipes"
        recipe_cache: dict[str, dict] = {}
        from k1_pipeline.gold import mode_for as _mode_for, step_status as _step_status
        hidden_blind = 0

        for gen_file in gen_files:
            node_data = json.loads(gen_file.read_text())
            recipe_id = node_data.get("recipe_id", "unknown")
            step_n = node_data.get("step_number", 0)
            if (
                _mode_for(recipe_id) == "from_scratch"
                and _step_status(DATA / "gold", recipe_id, step_n) != "done"
            ):
                # Shown only after you have annotated it from scratch.
                hidden_blind += 1
                continue
            critic_file = critic_dir / gen_file.name.replace(".gen.json", ".critic.json")
            critic_data = json.loads(critic_file.read_text()) if critic_file.exists() else {}

            # Get source step text
            if recipe_id not in recipe_cache:
                canon_path = recipes_dir / recipe_id / "canonical.json"
                if canon_path.exists():
                    recipe_cache[recipe_id] = json.loads(canon_path.read_text())
            recipe = recipe_cache.get(recipe_id, {})
            step_text = next(
                (s["text"] for s in recipe.get("steps", []) if s["number"] == step_n),
                "(source not found)"
            )

            verdict = critic_data.get("verdict", "unknown")
            color = {"accept": "green", "revise": "orange", "reject": "red"}.get(verdict, "gray")

            with st.expander(f"`{recipe_id}` step {step_n} — :{color}[{verdict.upper()}]"):
                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    st.markdown("**Source text**")
                    st.info(step_text)
                with col2:
                    st.markdown("**Extraction**")
                    st.json({
                        "node_type": node_data.get("node_type"),
                        "action_phrase": node_data.get("action_phrase"),
                        "pre_conditions": node_data.get("pre_conditions", []),
                        "post_conditions": node_data.get("post_conditions", []),
                        "source_span": node_data.get("source_span"),
                        "confidence": node_data.get("confidence"),
                    })
                with col3:
                    st.markdown("**Critic**")
                    st.markdown(f"**Verdict:** :{color}[{verdict}]")
                    for issue in critic_data.get("issues", []):
                        st.warning(issue)
                    if critic_data.get("grounding_quote"):
                        st.caption(f'Quote: "{critic_data["grounding_quote"][:80]}"')

                st.caption("Annotate this step on the Gold set tab. That form is what becomes the gold file.")

        if hidden_blind:
            st.caption(
                f"{hidden_blind} steps are hidden: their recipes are annotated from scratch "
                "and appear here once reviewed."
            )

# ── Tab 3: Gold set ────────────────────────────────────────────────────────────

def _as_records(table) -> list[dict]:
    if hasattr(table, "to_dict"):
        return table.to_dict("records")
    return list(table or [])


def _tool_rows(raw) -> list[dict]:
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("tool", "")).strip()
        else:
            name = ""
        if name:
            names.append(name)
    return [{"tool": name} for name in names] or [{"tool": ""}]


def _condition_rows(raw: list[dict] | None) -> list[dict]:
    rows = []
    for item in raw or []:
        entity = str(item.get("entity_id", "")).strip()
        label = str(item.get("k2_label", "")).strip()
        if entity and label in ("liquid", "coagulating", "solid", "scorched"):
            rows.append({"entity_id": entity, "k2_label": label})
    return rows or [{"entity_id": "", "k2_label": "liquid"}]


with tab_gold:
    from k1_pipeline.gold import (
        MODE_FROM_SCRATCH,
        WorkTimer,
        auto_step,
        idle_cap_seconds,
        is_current,
        load_gold,
        load_queue,
        mode_for,
        save_gold,
        step_status,
    )
    from k1_pipeline.scope import INGREDIENTS, UTENSILS

    st.subheader("Gold set")
    st.caption(
        "One step at a time. A saved step is the gold label the pipeline is scored against "
        "and the corrected step the final graph is built from. Time on each step is recorded."
    )

    gold_dir = DATA / "gold"
    queue = load_queue(DATA / "recipes")

    if not queue:
        st.info("No ingested recipes in scope. Run `k1 ingest` first.")
    else:
        statuses = {
            r.recipe_id: [step_status(gold_dir, r.recipe_id, s.number) for s in r.steps]
            for r in queue
        }
        done = sum(v.count("done") for v in statuses.values())
        total = sum(len(v) for v in statuses.values())
        outdated = sum(v.count("outdated") for v in statuses.values())
        st.progress(done / total if total else 0.0, text=f"{done}/{total} steps reviewed")
        if outdated:
            st.warning(
                f"{outdated} steps were annotated under an older definition. "
                "They are not counted until you review them again."
            )

        def _recipe_label(recipe) -> str:
            v = statuses[recipe.recipe_id]
            return f"{recipe.recipe_id} · {mode_for(recipe.recipe_id)} · {v.count('done')}/{len(v)}"

        # Open on the first recipe and step that still need review.
        first_open_recipe = next(
            (i for i, r in enumerate(queue) if statuses[r.recipe_id].count("done") < len(r.steps)), 0
        )
        recipe = st.selectbox("Recipe", queue, index=first_open_recipe, format_func=_recipe_label)
        recipe_id = recipe.recipe_id
        step_states = statuses[recipe_id]
        first_open_step = next((i for i, v in enumerate(step_states) if v != "done"), 0)
        step = st.selectbox(
            "Step",
            recipe.steps,
            index=first_open_step,
            format_func=lambda s: f"Step {s.number} · {step_states[recipe.steps.index(s)]}",
        )
        step_n = step.number
        mode = mode_for(recipe_id)

        elapsed = WorkTimer.tick(
            st.session_state.setdefault("gold_timer", {}),
            f"{recipe_id}:{step_n}",
            idle_cap_seconds(),
        )

        st.markdown(f"[{recipe.source_url}]({recipe.source_url})")
        st.info(step.text)

        saved = load_gold(gold_dir, recipe_id, step_n)
        current = is_current(saved)
        auto = auto_step(run_dir, recipe_id, step_n)

        if mode == MODE_FROM_SCRATCH:
            st.caption(
                "From scratch: the form starts blank and the pipeline output is hidden. "
                "Do not look at this recipe on the Graph or Review tabs before saving."
            )
        elif auto["status"] == "kept":
            st.caption(f"Pipeline (run `{run_id}`): kept this step. The form starts from its output.")
        elif auto["status"] == "dropped":
            st.caption(f"Pipeline (run `{run_id}`): dropped this step — {auto['reason']}.")
        else:
            st.caption(f"Pipeline (run `{run_id}`): {auto['reason']}.")

        if saved is not None and not current:
            with st.expander("Earlier annotation (older definition, not counted)"):
                st.json(saved.expected.model_dump(mode="json"))

        if current:
            seed = saved.expected.model_dump(mode="json")
        elif mode != MODE_FROM_SCRATCH and auto["expected"]:
            seed = auto["expected"]
        else:
            seed = {"in_scope": True}

        k = f"{recipe_id}_{step_n}"
        in_scope = st.checkbox(
            "This step belongs to the dish (uses the station inventory)",
            value=bool(seed.get("in_scope", True)),
            key=f"scope_{k}",
            help="Untick for serving with other foods, garnishes, or anything outside the inventory.",
        )
        st.caption(
            f"Inventory — ingredients: {', '.join(sorted(INGREDIENTS))}. "
            f"Utensils: {', '.join(sorted(UTENSILS))}."
        )

        node_types = ["Process", "Transfer", "Plate"]
        node_type = st.selectbox(
            "Node type",
            node_types,
            index=node_types.index(seed["node_type"]) if seed.get("node_type") in node_types else 0,
            key=f"nt_{k}",
            disabled=not in_scope,
        )
        action = st.text_input(
            "Action phrase", value=seed.get("action_phrase", ""), key=f"ap_{k}", disabled=not in_scope
        )
        label_column = {
            "k2_label": st.column_config.SelectboxColumn(
                options=["liquid", "coagulating", "solid", "scorched"]
            )
        }
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("Before")
            pre = st.data_editor(
                _condition_rows(seed.get("pre_conditions")),
                num_rows="dynamic", key=f"pre_{k}", column_config=label_column, disabled=not in_scope,
            )
        with c2:
            st.markdown("After")
            post = st.data_editor(
                _condition_rows(seed.get("post_conditions")),
                num_rows="dynamic", key=f"post_{k}", column_config=label_column, disabled=not in_scope,
            )
        st.markdown("Tools")
        st.caption("Implements named in this step. Leave the row empty when the step names none. Tools have no state.")
        tools = st.data_editor(
            _tool_rows(seed.get("tools")), num_rows="dynamic", key=f"tools_{k}", disabled=not in_scope
        )
        safety = st.checkbox(
            "Heat can coagulate or scorch",
            value=bool(seed.get("has_safety_bound", False)),
            key=f"sb_{k}",
            disabled=not in_scope,
        )
        notes = st.text_input("Notes", value=saved.notes if current else "", key=f"notes_{k}")

        carried = (saved.seconds_spent or 0.0) if current else 0.0
        st.caption(f"Time on this step: {int(carried + elapsed)} s")

        if st.button("Save and go to the next step", key=f"save_{k}", type="primary"):
            if in_scope and not action.strip():
                st.error("Action phrase is required for a step that belongs to the dish.")
            else:
                try:
                    out = save_gold(
                        gold_dir,
                        recipe_id=recipe_id,
                        step_n=step_n,
                        expected={
                            "node_type": node_type,
                            "action_phrase": action,
                            "pre_conditions": _as_records(pre),
                            "post_conditions": _as_records(post),
                            "tools": [str(r.get("tool", "")) for r in _as_records(tools)],
                            "has_safety_bound": safety and in_scope,
                            "in_scope": in_scope,
                        },
                        mode=mode,
                        seconds_spent=elapsed,
                        seeded_from_run=run_id,
                        annotator="gil.arroteia",
                        notes=notes,
                    )
                except Exception as e:
                    st.error(f"Could not save: {e}")
                else:
                    WorkTimer.reset(st.session_state["gold_timer"])
                    st.toast(f"Saved {out.name}")
                    st.rerun()
