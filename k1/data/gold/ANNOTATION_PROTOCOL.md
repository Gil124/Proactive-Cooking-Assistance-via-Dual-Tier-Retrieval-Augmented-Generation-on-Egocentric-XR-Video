# Gold Annotation Protocol — K1 v1

## Overview

Annotate exactly **three** scrambled-egg recipes:
1. Serious Eats — Fluffy Scrambled Eggs (`serious_eats`)
2. Gordon Ramsay — Scrambled Eggs (`gordon_ramsay`)
3. Bon Appétit — Best Scrambled Eggs (`bon_appetit`)

These recipes must **never** be used as few-shot examples in extraction prompts.

## How to annotate

1. Open the recipe URL listed in `k1/config/recipes.yaml`.
2. Read each step.
3. Fill in one JSON file per step following the schema below.
4. Save as `{recipe_id}_step{NN:02d}.gold.json` in this directory.
5. Do not modify gold files after annotation. Corrections go into a new `v2` folder.

## Step annotation schema

```json
{
  "recipe_id": "serious_eats",
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
    "has_safety_bound": true
  },
  "annotator": "gil.arroteia",
  "annotation_date": "YYYY-MM-DD",
  "notes": "Optional annotation notes"
}
```

## Rules

- `node_type`: Process = state-changing action; Transfer = move/add/remove; Plate = serve.
- `k2_label`: use only `liquid`, `coagulating`, `solid`, `scorched`.
- `has_safety_bound`: true if the step involves heat that could cause coagulation/scorching.
- `action_phrase`: a short 2–5 word verb phrase, e.g. "whisk eggs", "melt butter over heat".
- `pre_conditions`: what state the entity is in BEFORE this step.
- `post_conditions`: what state the entity should be in AFTER this step.

## Entity alias reminder

Use canonical names: `egg`, `butter`, `oil`, `salt`, `pan`, `spatula`, `bowl`, `whisk`, `plate`.

## Gold synonym table for entity resolution

Save as `entity_aliases.yaml` (create this file):

```yaml
aliases:
  - canonical: egg
    aliases: [eggs, whole eggs, egg mixture, beaten egg]
  - canonical: butter
    aliases: [unsalted butter, cold butter, knob of butter]
```
