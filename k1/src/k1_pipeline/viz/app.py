"""
K1 Graph Visualizer + Review UI
Streamlit application -- JSON-first (does not require Neo4j).

Tabs:
  1. Graph -- interactive Pyvis graph of the fused DAG
  2. Review -- side-by-side: step text | generator JSON | critic verdict
  3. Gold set -- annotate the review queue into data/gold/*.gold.json
  4. Merge pairs -- label which nodes of graph.unmerged.json are the same step
     (data/gold/merge_labels.json)

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

tab_graph, tab_review, tab_gold, tab_merge = st.tabs(["Graph", "Review", "Gold set", "Merge pairs"])

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
        may_be_compound,
        mode_for,
        save_gold,
        save_split,
        step_status,
    )
    from k1_pipeline.merge import load_labels as load_merge_labels
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

        # Steps that may hold several actions: their wording joins verbs, or a
        # merge label says they contain another step.
        containing: set[str] = set()
        for entry in load_merge_labels(gold_dir).values():
            if entry["label"] == "a_contains_b":
                containing.add(entry["a"]["action_phrase"])
            elif entry["label"] == "b_contains_a":
                containing.add(entry["b"]["action_phrase"])
        golds = {
            (r.recipe_id, s.number): load_gold(gold_dir, r.recipe_id, s.number)
            for r in queue for s in r.steps
        }
        compound = {
            key for key, g in golds.items() if is_current(g) and may_be_compound(g, containing)
        }
        checked = {key for key in compound if golds[key].split_checked}
        if compound:
            st.progress(
                len(checked) / len(compound),
                text=f"{len(checked)}/{len(compound)} steps that may hold several actions checked for splitting",
            )
        only_compound = st.checkbox(
            "Only steps that may hold several actions",
            value=False,
            help="Steps whose action joins several verbs, or that a merge label says contain another step.",
        )

        def _split_state(recipe_id: str, step_n: int) -> str:
            g = golds[(recipe_id, step_n)]
            if not is_current(g):
                return ""
            if g.sub_steps:
                return f" · split into {len(g.sub_steps)}"
            if g.split_checked:
                return " · kept as one"
            return " · check split" if (recipe_id, step_n) in compound else ""

        shown_queue = [r for r in queue if not only_compound or any(
            (r.recipe_id, s.number) in compound for s in r.steps
        )]
        if not shown_queue:
            st.info("No reviewed step looks like it holds several actions; showing all steps.")
            only_compound = False
            shown_queue = queue

        def _recipe_label(recipe) -> str:
            v = statuses[recipe.recipe_id]
            label = f"{recipe.recipe_id} · {mode_for(recipe.recipe_id)} · {v.count('done')}/{len(v)}"
            if only_compound:
                todo = [s for s in recipe.steps if (recipe.recipe_id, s.number) in compound - checked]
                label += f" · {len(todo)} to check"
            return label

        # Open on the first recipe and step that still need review (or a split check).
        def _needs_work(r, s, state) -> bool:
            if only_compound:
                return (r.recipe_id, s.number) in compound - checked
            return state != "done"

        first_open_recipe = next(
            (i for i, r in enumerate(shown_queue)
             if any(_needs_work(r, s, statuses[r.recipe_id][j]) for j, s in enumerate(r.steps))), 0
        )
        recipe = st.selectbox("Recipe", shown_queue, index=first_open_recipe, format_func=_recipe_label)
        recipe_id = recipe.recipe_id
        step_states = statuses[recipe_id]
        shown_steps = [s for s in recipe.steps if not only_compound or (recipe_id, s.number) in compound]
        first_open_step = next(
            (i for i, s in enumerate(shown_steps)
             if _needs_work(recipe, s, step_states[recipe.steps.index(s)])), 0
        )
        step = st.selectbox(
            "Step",
            shown_steps,
            index=first_open_step,
            format_func=lambda s: (
                f"Step {s.number} · {step_states[recipe.steps.index(s)]}"
                + _split_state(recipe_id, s.number)
            ),
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

        # ── Split into atomic steps ──────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Split into atomic steps")
        st.caption(
            "One action per node: one verb on one thing, with one visible result. "
            "\"Crack the eggs into a bowl and whisk\" is two actions; \"cook over low heat, "
            "folding slowly\" is one (heat and manner are details of the same action). "
            "The form above stays the label for the whole step; the actions below are what "
            "the graph is built from. Time here is recorded apart from the review time."
        )
        if not current:
            st.info("Save the review of this step above first.")
        elif not saved.expected.in_scope:
            st.caption("This step is left out of the dish, so there is nothing to split.")
        else:
            split_elapsed = WorkTimer.tick(
                st.session_state.setdefault("split_timer", {}),
                f"split:{recipe_id}:{step_n}",
                idle_cap_seconds(),
            )
            seeds = [x.model_dump(mode="json") for x in saved.graph_steps()]
            n_actions = st.number_input(
                "Actions in this step", min_value=1, max_value=6, value=len(seeds), key=f"nsub_{k}",
                help="1 keeps the step as one node.",
            )
            sub_rows = []
            for i in range(int(n_actions)):
                if i < len(seeds):
                    sd = seeds[i]
                else:
                    # A new action starts from the state the previous one leaves.
                    prev = seeds[-1] if seeds else {}
                    sd = {"node_type": "Process", "action_phrase": "",
                          "pre_conditions": prev.get("post_conditions", []),
                          "post_conditions": prev.get("post_conditions", []),
                          "tools": [], "has_safety_bound": False, "in_scope": True}
                sk = f"{k}_sub{i}"
                with st.container(border=True):
                    st.markdown(f"**Action {i + 1}**")
                    a1, a2 = st.columns([1, 3])
                    with a1:
                        s_type = st.selectbox(
                            "Node type", node_types,
                            index=node_types.index(sd["node_type"]) if sd.get("node_type") in node_types else 0,
                            key=f"nt_{sk}",
                        )
                    with a2:
                        s_action = st.text_input("Action phrase", value=sd.get("action_phrase", ""), key=f"ap_{sk}")
                    b1, b2 = st.columns(2)
                    with b1:
                        st.markdown("Before")
                        s_pre = st.data_editor(
                            _condition_rows(sd.get("pre_conditions")), num_rows="dynamic",
                            key=f"pre_{sk}", column_config=label_column,
                        )
                    with b2:
                        st.markdown("After")
                        s_post = st.data_editor(
                            _condition_rows(sd.get("post_conditions")), num_rows="dynamic",
                            key=f"post_{sk}", column_config=label_column,
                        )
                    s_tools = st.data_editor(
                        _tool_rows(sd.get("tools")), num_rows="dynamic", key=f"tools_{sk}"
                    )
                    s_heat = st.checkbox(
                        "Heat can coagulate or scorch", value=bool(sd.get("has_safety_bound", False)),
                        key=f"sb_{sk}",
                    )
                sub_rows.append({
                    "node_type": s_type,
                    "action_phrase": s_action,
                    "pre_conditions": _as_records(s_pre),
                    "post_conditions": _as_records(s_post),
                    "tools": [str(r.get("tool", "")) for r in _as_records(s_tools)],
                    "has_safety_bound": s_heat,
                    "in_scope": True,
                })
            carried_split = saved.split_seconds_spent or 0.0
            st.caption(f"Time on splitting this step: {int(carried_split + split_elapsed)} s")
            split_label = "Save split" if int(n_actions) > 1 else "Save: keep as one action"
            if st.button(split_label, key=f"split_save_{k}", type="primary"):
                try:
                    out = save_split(
                        gold_dir, recipe_id=recipe_id, step_n=step_n,
                        sub_steps=sub_rows if int(n_actions) > 1 else [saved.expected.model_dump(mode="json")],
                        seconds_spent=split_elapsed,
                    )
                except Exception as e:
                    st.error(f"Could not save: {e}")
                else:
                    WorkTimer.reset(st.session_state["split_timer"])
                    st.toast(f"Saved split for {out.name}")
                    st.rerun()


# ── Tab 4: Merge pairs ────────────────────────────────────────────────────────

def _cond_text(conds) -> str:
    return ", ".join(f"{c.entity_id}: {c.k2_label.value}" for c in conds) or "—"


def _node_card(node, graph, recipes: dict) -> None:
    st.markdown(f"#### {node.action_phrase}")
    st.caption(f"{node.node_type.value} · `{node.node_id}`")
    st.markdown(f"**Before:** {_cond_text(node.pre_conditions)}  \n**After:** {_cond_text(node.post_conditions)}")
    st.markdown(
        f"**Tools:** {', '.join(dict.fromkeys(node.tools)) or '—'}  \n"
        f"**Heat bounds:** {', '.join(b.bound_id for b in node.safety_bounds) or 'none'}"
    )
    names = {n.node_id: n.action_phrase for n in graph.nodes}
    seen = set()
    for recipe_id, step_n in zip(node.source_recipe_ids, node.source_step_indices):
        if (recipe_id, step_n) in seen:
            continue
        seen.add((recipe_id, step_n))
        prev = [names[e.from_node_id] for e in graph.edges
                if e.edge_type == "NEXT" and e.source_recipe_id == recipe_id and e.to_node_id == node.node_id]
        nxt = [names[e.to_node_id] for e in graph.edges
               if e.edge_type == "NEXT" and e.source_recipe_id == recipe_id and e.from_node_id == node.node_id]
        recipe = recipes.get(recipe_id)
        text = next((s.text for s in recipe.steps if s.number == step_n), None) if recipe else None
        st.markdown(f"**`{recipe_id}` step {step_n}**")
        st.info(text or "(added by rule: no source text)")
        st.caption(
            f"{(prev or ['start'])[0]}  →  **this step**  →  {(nxt or ['end'])[0]}"
        )


with tab_merge:
    from k1_pipeline.gold import WorkTimer, idle_cap_seconds, load_queue
    from k1_pipeline.merge import (
        LABEL_TEXT,
        LABELS,
        candidate_pairs,
        conflicts,
        delete_label,
        is_current as label_is_current,
        load_labels,
        merge_groups,
        oriented_label,
        pair_id,
        save_label,
    )
    from k1_pipeline.models import K1Graph

    st.subheader("Merge pairs")
    st.caption(
        "Is this the same step in different words? Candidates are node pairs in the reviewed "
        "graph (before merging) with the same node type and the same K2 transition. Labels are saved to "
        "`data/gold/merge_labels.json`. They decide merges for this graph and are the test set "
        "for any automatic judge. Time on each pair is recorded."
    )

    # Labels refer to the reviewed graph before merging.
    final_path = DATA / "k1" / "graph.unmerged.json"
    if not final_path.exists():
        st.info("graph.unmerged.json not found. Run `k1 finalize` first.")
    else:
        mgraph = K1Graph.model_validate_json(final_path.read_text())
        mnodes = {n.node_id: n for n in mgraph.nodes}
        gold_dir = DATA / "gold"
        labels = load_labels(gold_dir)
        mrecipes = {r.recipe_id: r for r in load_queue(DATA / "recipes")}

        pairs = [(block, a, b, False) for block, a, b in candidate_pairs(mgraph)]
        listed = {pair_id(a, b) for _, a, b, _ in pairs}
        manual = st.session_state.setdefault("merge_manual", [])
        for entry in labels.values():
            if entry.get("added_by_hand") and label_is_current(entry, mgraph):
                pair = (entry["a"]["node_id"], entry["b"]["node_id"])
                if pair not in manual:
                    manual.append(pair)
        for a, b in manual:
            if pair_id(a, b) not in listed:
                pairs.append(("added by hand", a, b, True))
                listed.add(pair_id(a, b))

        done = sum(1 for _, a, b, _ in pairs if pair_id(a, b) in labels)
        st.progress(done / len(pairs) if pairs else 0.0, text=f"{done}/{len(pairs)} pairs labelled")
        stale = [e for e in labels.values() if not label_is_current(e, mgraph)]
        if stale:
            st.warning(
                f"{len(stale)} labels refer to nodes no longer in the graph (a step was edited "
                "after labelling). They are not counted; the new pair, if any, is in the list."
            )

        def _pair_label(i: int) -> str:
            block, a, b, _ = pairs[i]
            entry = labels.get(pair_id(a, b))
            status = f"✓ {oriented_label(entry, a)}" if entry else "open"
            return f"[{status}] {mnodes[a].action_phrase}  ↔  {mnodes[b].action_phrase}   ·  {block}"

        first_open = next((i for i, (_, a, b, _) in enumerate(pairs) if pair_id(a, b) not in labels), 0)
        idx = st.selectbox("Pair", range(len(pairs)), index=first_open, format_func=_pair_label)
        block, node_a, node_b, by_hand = pairs[idx]
        pid = pair_id(node_a, node_b)
        saved = labels.get(pid)

        elapsed = WorkTimer.tick(
            st.session_state.setdefault("merge_timer", {}), f"merge:{pid}", idle_cap_seconds()
        )

        st.caption(f"Group: {block}")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("##### A")
            _node_card(mnodes[node_a], mgraph, mrecipes)
        with col_b:
            st.markdown("##### B")
            _node_card(mnodes[node_b], mgraph, mrecipes)

        st.markdown("---")
        current_label = oriented_label(saved, node_a) if saved else None
        choice = st.radio(
            "These two nodes are",
            LABELS,
            index=LABELS.index(current_label) if current_label else None,
            format_func=lambda x: LABEL_TEXT[x],
            horizontal=True,
            key=f"merge_choice_{pid}",
        )
        notes = st.text_input("Notes", value=saved.get("notes", "") if saved else "", key=f"merge_notes_{pid}")
        carried = saved["seconds_spent"] if saved and label_is_current(saved, mgraph) else 0.0
        st.caption(f"Time on this pair: {int(carried + elapsed)} s")

        c1, c2, _ = st.columns([2, 1, 3])
        with c1:
            if st.button("Save and go to the next pair", type="primary", key=f"merge_save_{pid}"):
                if choice is None:
                    st.error("Choose one of the four options first.")
                else:
                    save_label(
                        gold_dir, mgraph,
                        node_a=node_a, node_b=node_b, label=choice,
                        seconds_spent=elapsed, annotator="gil.arroteia",
                        added_by_hand=by_hand, notes=notes,
                    )
                    WorkTimer.reset(st.session_state["merge_timer"])
                    st.toast(f"Saved: {LABEL_TEXT[choice]}")
                    st.rerun()
        with c2:
            if saved and st.button("Clear label", key=f"merge_clear_{pid}"):
                delete_label(gold_dir, pid)
                st.rerun()

        with st.expander("Add a pair outside the candidate groups"):
            st.caption(
                "For two nodes you think are the same step although their type or K2 transition "
                "differs, which usually means one of the reviewed steps is labelled wrongly."
            )
            ids = sorted(mnodes, key=lambda n: mnodes[n].action_phrase.lower())
            fmt = lambda n: f"{mnodes[n].action_phrase}  ·  {', '.join(dict.fromkeys(mnodes[n].source_recipe_ids))}"
            m1 = st.selectbox("Node A", ids, format_func=fmt, key="merge_add_a")
            m2 = st.selectbox("Node B", ids, format_func=fmt, key="merge_add_b")
            if st.button("Add pair", key="merge_add"):
                if m1 == m2:
                    st.error("Pick two different nodes.")
                elif pair_id(m1, m2) in listed:
                    st.info("That pair is already in the list.")
                else:
                    manual.append((m1, m2))
                    st.rerun()

        with st.expander("What the labels imply", expanded=done == len(pairs) and bool(pairs)):
            current = {k: v for k, v in labels.items() if label_is_current(v, mgraph)}
            counts = {lab: sum(1 for v in current.values() if v["label"] == lab) for lab in LABELS}
            st.markdown("  \n".join(f"**{LABEL_TEXT[k]}:** {v}" for k, v in counts.items()))
            groups = merge_groups(current, mgraph)
            if groups:
                st.markdown("**Merge groups** (connected by 'same')")
                for g in groups:
                    st.markdown("- " + "  =  ".join(f"`{mnodes[n].action_phrase}`" for n in g))
            else:
                st.caption("No merges yet.")
            found = conflicts(current, mgraph)
            for c in found:
                if c["kind"] == "not_transitive":
                    st.error(f"Not transitive: {c['detail']}")
                else:
                    st.warning(f"Order conflict after merging: {c['detail']}")
            if groups and not found:
                st.success("No conflicts: these merges keep every recipe's order consistent.")
