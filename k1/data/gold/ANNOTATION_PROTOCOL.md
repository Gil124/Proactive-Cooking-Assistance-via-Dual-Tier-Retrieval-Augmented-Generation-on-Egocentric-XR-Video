# Review Protocol — K1 reviewed steps

Full protocol and metrics: [`Notes/09-k1-evaluation.md`](../../../Notes/09-k1-evaluation.md).
What belongs to the dish: [`Notes/10-recipe-variation.md`](../../../Notes/10-recipe-variation.md).

## What to review

Every step of every ingested recipe that is not `excluded` in `k1/config/recipes.yaml`.
A reviewed step is both the gold label and the corrected step the final graph is built from.

## How to review

1. Run `uv run k1 viz --run <run_id>` and open the **Gold set** tab.
2. The tab opens on the first step that still needs review. Read the source step.
3. Decide whether the step belongs to the dish. Untick the box for serving with other
   foods, garnishes, or anything outside the station inventory.
4. Correct the fields, then press **Save and go to the next step**.
5. If the step does more than one action, split it (see "Atomic steps" below) in the
   **Split into atomic steps** section under the form, then press **Save split**. Tick
   **Only steps that may hold several actions** to go through just the steps flagged for
   it; each needs a decision, split or **keep as one action**.

Do not write the files by hand: the tab records the mode, the time spent, the run, and the
definition version, and the metrics need all four.

Recipes listed under `from_scratch` in `k1/config/gold_review.yaml` start from a blank form
with the pipeline output hidden. Do not open them on the Graph tab before saving.

A file saved under an older `definition_version` is shown as outdated and is not counted
until you save it again.

## File schema

`{recipe_id}_step{NN}.gold.json`:

```json
{
  "recipe_id": "pingo_doce",
  "step_number": 1,
  "expected": {
    "node_type": "Process | Transfer | Plate",
    "action_phrase": "short verb phrase",
    "pre_conditions": [
      {"entity_id": "egg", "k2_label": "liquid | coagulating | solid | scorched"}
    ],
    "post_conditions": [
      {"entity_id": "egg", "k2_label": "liquid | coagulating | solid | scorched"}
    ],
    "tools": ["whisk", "bowl"],
    "has_safety_bound": true,
    "in_scope": true
  },
  "annotator": "gil.arroteia",
  "annotation_date": "YYYY-MM-DD",
  "notes": "",
  "mode": "corrected | from_scratch",
  "seconds_spent": 41.5,
  "seeded_from_run": "run id",
  "definition_version": "2026-10-11",
  "sub_steps": [
    {"node_type": "Process", "action_phrase": "crack eggs into bowl", "...": "same fields as expected"},
    {"node_type": "Process", "action_phrase": "whisk eggs", "...": "same fields as expected"}
  ],
  "split_checked": true,
  "split_seconds_spent": 25.0
}
```

`expected` labels the whole step, and the pipeline's step-level output is scored against
it. `sub_steps` is empty for a step that is one action; otherwise it holds two or more
actions in order, and the graph is built from those. `split_checked` records that the split
decision was made; `split_seconds_spent` keeps that time apart from `seconds_spent`.

## Rules

- `in_scope`: false when nothing in the step uses the eggs or the station inventory. The
  other fields are then ignored.
- `node_type`: Process = state-changing action; Transfer = move/add/remove; Plate = eggs onto the plate.
- `k2_label`: use only `liquid`, `coagulating`, `solid`, `scorched`.
- `has_safety_bound`: true if the step involves heat that could cause coagulation/scorching.
- `action_phrase`: a short 2–5 word verb phrase, e.g. "whisk eggs", "melt butter over heat".
  Name only inventory items.
- `pre_conditions`: what state the entity is in BEFORE this step.
- `post_conditions`: what state the entity should be in AFTER this step.
- `tools`: implements the step names. One name per row. A step that happens on the heat
  (`has_safety_bound` true) always lists `heat_source`, even when the text does not name it. Tools have no k2 state, so they do
  not go in Before or After. Leave the list empty when the step names no tool.

## Atomic steps

One graph node is one action: one verb applied to one thing, with one visible result.
Several small steps are better than one large one (author decision, 2026-10-23): small
steps are shared between recipes, and each has one transition K2 can observe.

Split when the step does two things in sequence:

| Source step | Actions |
|---|---|
| "Crack the eggs into a bowl and whisk them" | crack eggs into bowl · whisk eggs |
| "Melt the butter, then pour in the eggs" | melt butter · pour eggs into pan |
| "Stir until just set, then remove from the heat" | stir eggs until just set · remove pan from heat |
| "Finish cooking, then slide onto a plate" | finish cooking eggs · transfer eggs to plate |

Do not split:

- manner, heat level, duration or end point of the same action: "cook over low heat,
  folding slowly, until soft curds form" is one action. Heat level is a detail of the
  action, not a step of its own.
- seasoning added during the same action: "whisk the eggs with salt and pepper" is one.
- heating the pan to melt the butter: "heat the pan and melt the butter" is one action,
  because heating the pan is how the butter melts (author decision, 2026-10-25).

Each action gets its own Before and After: a later action starts from the state the earlier
one leaves. Tick heat on the actions in which heat changes a state: melting the butter,
cooking or stirring the eggs on the heat, and eggs still cooking from the pan's residual heat
(same rule as the remove-from-heat steps). Do not tick it on a quick transfer or a seasoning
added in the pan ("pour eggs in pan", "add salt").

Use the same wording for the same action in every recipe ("whisk eggs", "pour eggs in pan",
"crack the eggs into a bowl"). Nodes with the same wording and the same states merge
without a merge label.

## Entity names

Use the inventory names. Aliases and Portuguese names are resolved on save.

- Ingredients: `egg`, `salt`, `pepper`, `butter`, `oil`.
- Utensils: `pan`, `bowl`, `spatula`, `whisk`, `plate`, `heat_source`.

`entity_aliases.yaml` in this folder is the synonym table used for the alias-accuracy metric.
