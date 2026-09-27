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
from datetime import date
from pathlib import Path

import streamlit as st
import yaml
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

        for gen_file in gen_files:
            node_data = json.loads(gen_file.read_text())
            recipe_id = node_data.get("recipe_id", "unknown")
            step_n = node_data.get("step_number", 0)
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

# ── Tab 3: Gold set ────────────────────────────────────────────────────────────

def _as_records(table) -> list[dict]:
    if hasattr(table, "to_dict"):
        return table.to_dict("records")
    return list(table or [])


def _condition_rows(raw: list[dict] | None) -> list[dict]:
    rows = []
    for item in raw or []:
        entity = str(item.get("entity_id", "")).strip()
        label = str(item.get("k2_label", "")).strip()
        if entity and label in ("liquid", "coagulating", "solid", "scorched"):
            rows.append({"entity_id": entity, "k2_label": label})
    return rows or [{"entity_id": "", "k2_label": "liquid"}]


def _load_gold_step(gold_dir: Path, recipe_id: str, step_n: int) -> dict | None:
    path = gold_dir / f"{recipe_id}_step{step_n:02d}.gold.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


with tab_gold:
    st.subheader("Gold set")
    st.caption(
        "Read the source step, correct the fields, then save. "
        "A saved file is your annotation. The model suggestion is only a starting point."
    )

    review_path = ROOT / "config" / "gold_review.yaml"
    review_cfg = yaml.safe_load(review_path.read_text()) if review_path.exists() else {}
    candidates = review_cfg.get("candidates", [])
    gold_dir = DATA / "gold"
    recipes_dir = DATA / "recipes"
    gen_dir = run_dir / "L2" / "gen"

    if not candidates:
        st.info("No recipes in config/gold_review.yaml.")
    else:
        done = 0
        total = 0
        for candidate in candidates:
            canon_path = recipes_dir / candidate["recipe_id"] / "canonical.json"
            if not canon_path.exists():
                continue
            recipe = json.loads(canon_path.read_text())
            for step in recipe.get("steps", []):
                total += 1
                if (gold_dir / f"{candidate['recipe_id']}_step{step['number']:02d}.gold.json").exists():
                    done += 1
        st.progress(done / total if total else 0.0, text=f"{done}/{total} queued steps annotated")

        for candidate in candidates:
            recipe_id = candidate["recipe_id"]
            canon_path = recipes_dir / recipe_id / "canonical.json"
            with st.expander(f"{recipe_id} — {candidate.get('why', '')}", expanded=False):
                if not canon_path.exists():
                    st.warning("Not ingested yet. The source steps will appear here after ingest.")
                    continue
                recipe = json.loads(canon_path.read_text())
                st.markdown(f"[{recipe.get('source_url', recipe_id)}]({recipe.get('source_url', '')})")
                for step in recipe.get("steps", []):
                    step_n = step["number"]
                    saved = _load_gold_step(gold_dir, recipe_id, step_n)
                    gen_path = gen_dir / f"{recipe_id}_step{step_n:02d}.gen.json"
                    suggestion = json.loads(gen_path.read_text()) if gen_path.exists() else None
                    seed = (saved or {}).get("expected") or suggestion or {}
                    status = "saved" if saved else "open"
                    st.markdown(f"**Step {step_n}** · {status}")
                    st.info(step.get("text", ""))
                    if suggestion and not saved:
                        st.caption(
                            f"Model suggestion: {suggestion.get('node_type', '')} — "
                            f"{suggestion.get('action_phrase', '')}"
                        )

                    node_type = st.selectbox(
                        "Node type",
                        ["Process", "Transfer", "Plate"],
                        index=["Process", "Transfer", "Plate"].index(seed.get("node_type", "Process"))
                        if seed.get("node_type") in ("Process", "Transfer", "Plate") else 0,
                        key=f"nt_{recipe_id}_{step_n}",
                    )
                    action = st.text_input(
                        "Action phrase",
                        value=seed.get("action_phrase", ""),
                        key=f"ap_{recipe_id}_{step_n}",
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("Before")
                        pre = st.data_editor(
                            _condition_rows(seed.get("pre_conditions")),
                            num_rows="dynamic",
                            key=f"pre_{recipe_id}_{step_n}",
                            column_config={
                                "k2_label": st.column_config.SelectboxColumn(
                                    options=["liquid", "coagulating", "solid", "scorched"]
                                )
                            },
                        )
                    with c2:
                        st.markdown("After")
                        post = st.data_editor(
                            _condition_rows(seed.get("post_conditions")),
                            num_rows="dynamic",
                            key=f"post_{recipe_id}_{step_n}",
                            column_config={
                                "k2_label": st.column_config.SelectboxColumn(
                                    options=["liquid", "coagulating", "solid", "scorched"]
                                )
                            },
                        )
                    safety = st.checkbox(
                        "Heat can coagulate or scorch",
                        value=bool(seed.get("has_safety_bound", False)),
                        key=f"sb_{recipe_id}_{step_n}",
                    )
                    notes = st.text_input("Notes", value=(saved or {}).get("notes", ""), key=f"notes_{recipe_id}_{step_n}")
                    if st.button(f"Save step {step_n}", key=f"save_{recipe_id}_{step_n}"):
                        entry = {
                            "recipe_id": recipe_id,
                            "step_number": step_n,
                            "expected": {
                                "node_type": node_type,
                                "action_phrase": action.strip(),
                                "pre_conditions": _condition_rows(_as_records(pre)),
                                "post_conditions": _condition_rows(_as_records(post)),
                                "has_safety_bound": safety,
                            },
                            "annotator": "gil.arroteia",
                            "annotation_date": str(date.today()),
                            "notes": notes.strip(),
                        }
                        if not entry["expected"]["action_phrase"]:
                            st.error("Action phrase is required.")
                        else:
                            gold_dir.mkdir(exist_ok=True)
                            out = gold_dir / f"{recipe_id}_step{step_n:02d}.gold.json"
                            out.write_text(json.dumps(entry, indent=2))
                            st.success(f"Saved {out.name}")
