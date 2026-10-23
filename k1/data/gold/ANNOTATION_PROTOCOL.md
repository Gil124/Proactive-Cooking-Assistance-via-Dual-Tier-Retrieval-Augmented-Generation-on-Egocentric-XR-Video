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
  "definition_version": "2026-10-11"
}
```

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

## Entity names

Use the inventory names. Aliases and Portuguese names are resolved on save.

- Ingredients: `egg`, `salt`, `pepper`, `oregano`, `butter`, `oil`.
- Utensils: `pan`, `bowl`, `spatula`, `whisk`, `plate`, `heat_source`.

`entity_aliases.yaml` in this folder is the synonym table used for the alias-accuracy metric.
