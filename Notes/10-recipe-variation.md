# Recipe variation — definition

Agreed on 2026-10-11. This note fixes what counts as a *recipe variation* in this project, and therefore what `K1` may contain.

It has two parts:

- **Part A** is written to be lifted into the dissertation. It is self-contained and does not refer to the codebase.
- **Part B** is project-internal: the decisions behind the definition, what it implies for the current `K1` graph, and what is still open.

This is original to the project, not a transcription of the PIC. The PIC (§4.6) only says that `K1` is a multi-path DAG whose branches are "variations".

---

# Part A — Thesis text

## A.1 Motivation

The static knowledge tier `K1` encodes a dish as a multi-path graph, not as one linear recipe. At runtime the system compares the cook's observed trajectory against this graph and stays silent while the cook follows any path the graph contains. The graph therefore defines the set of behaviours the assistant treats as *correct*. A graph that is too narrow makes the assistant interrupt a cook who is doing nothing wrong; a graph that is too broad admits content that is unrelated to the dish (serving suggestions, accompaniments, other dishes) and cannot be checked against perception.

Published recipes for the same dish differ in wording, tools, quantities, added ingredients, order of steps, and cooking parameters. Only some of these differences are relevant to an assistant that monitors execution. A precise definition of *recipe variation* is needed to decide which differences become alternative paths in `K1`, which become parameters of a shared step, and which are discarded.

## A.2 Preliminaries

A **dish specification** is a tuple *D = (s₀, G, I, B)* where:

- *s₀* is the **start state**: the fixed initial configuration of the workspace.
- *G* is the **goal state set**: the set of final states that count as the finished dish.
- *I = I_ing ∪ I_ut* is the **inventory**: a closed set of ingredients and utensils available to the cook.
- *B* is the set of **safety bounds**: domain-physics limits that no execution may cross.

A **step** is a tuple *σ = (a, E, π → ρ, θ)* where *a* is an action, *E ⊆ I* is the set of ingredients and utensils involved, *π → ρ* is the state transition it causes (pre-conditions to post-conditions over the entities in *E*), and *θ* is a vector of **execution parameters** (heat level, duration, agitation).

Two steps are **equivalent**, *σ ≡ σ′*, when they cause the same state transition on the same ingredients, using utensils from the same functional class. Equivalent steps may differ in wording, in language, and in *θ*.

## A.3 Definition

> **Definition (Recipe variation).** Given a dish specification *D = (s₀, G, I, B)*, a **recipe variation** of *D* is a pair *V = (Σ, ≺)*, where *Σ* is a set of parameterised steps and *≺* is a partial order on *Σ*, such that:
>
> 1. **Closed inventory.** Every step in *Σ* involves only elements of *I*.
> 2. **Goal reaching.** Executing *Σ* in any order consistent with *≺*, starting from *s₀*, ends in a state in *G*.
> 3. **Safety.** No state reached during that execution violates a bound in *B*.
> 4. **Dependency.** *σᵢ ≺ σⱼ* whenever a pre-condition of *σⱼ* is established by a post-condition of *σᵢ*.

Two variations of the same dish can differ in two ways:

- **Structural variation.** They differ in which steps occur (up to equivalence) or in the order *≺*.
- **Parametric variation.** They contain equivalent steps in the same order, but differ in the execution parameters *θ* of at least one step.

A difference that is neither structural nor parametric is a **nominal difference** and does not constitute a variation: different wording or language for the same step, or a different utensil from the same functional class.

**Compositionality.** Any pair *(Σ, ≺)* that satisfies conditions 1–4 is a valid variation, whether or not a single published source describes it in full. A variation that corresponds to one complete source recipe is called **attested**; one obtained by combining steps from several sources is called **composed**.

**Deviation.** An execution that starts from *s₀* but is not a prefix of any valid variation is a **deviation**. A deviation is the condition under which the assistant may intervene.

## A.4 The three kinds of difference

| Kind | What differs | Example (scrambled eggs) | Representation in `K1` |
| --- | --- | --- | --- |
| Structural variation | Which steps occur, or their order | Salt added in the bowl, in the pan, or at the end; butter or olive oil as fat; eggs beaten in a bowl or broken directly in the pan | Alternative branches |
| Parametric variation | How a step is executed | Low heat for several minutes, or medium-high heat for about one minute; constant stirring or occasional folding | One step node carrying several attested parameter settings |
| Nominal difference (not a variation) | Wording, language, interchangeable utensil | Fork or hand whisk; "frigideira" or "skillet"; "beat" or "whisk" | One step node |

Execution parameters are not independent. Heat level and duration are coupled: a duration that is correct at low heat causes scorching at high heat. Parametric variation is therefore recorded as attested **parameter tuples** (heat level, duration, agitation), not as independent ranges.

## A.5 What the definition excludes

- **Composition with other foods.** Steps that occur after a state in *G* is reached, or that act on entities outside *I* (serving on toast, adding a chutney), produce a different dish and are outside the variation.
- **Ingredient extension.** A recipe whose steps require an ingredient outside *I* (cream, cheese) is not a variation of *D*. If the remaining steps still satisfy conditions 1–4, the recipe can contribute them after the out-of-inventory steps are removed.
- **Equipment extension.** A recipe whose goal-reaching path requires a utensil outside *I* (a double boiler) is not a variation of *D* and contributes nothing.
- **Scaling.** A different number of servings changes *s₀* and is a different dish specification.

## A.6 Instantiation for this work

| Element | Value |
| --- | --- |
| Dish | One serving of scrambled eggs |
| *s₀* | Standardised laboratory station: eggs in shell, all inventory items at hand, pan cold, heat source off |
| *G* | Egg in state `coagulating` or `solid`, transferred to the plate. `scorched` is never in *G* |
| *I_ing* | Eggs, salt, pepper, oregano, butter, olive oil |
| *I_ut* | Pan, bowl, wooden spatula or spoon, hand whisk, fork, plate, heat source |
| *B* | Egg coagulation onset (≈62 °C), full coagulation (≈70 °C), Maillard browning onset, butter smoke point, syneresis risk |

Functional utensil classes: {fork, hand whisk} for beating; {wooden spatula, wooden spoon} for stirring and folding.

The goal is a *set* because sources legitimately target different doneness (soft and slightly runny, or fully set). The goal is placed at the plate, not at removal from the heat, because residual pan heat continues to cook the eggs and can still scorch them after the heat is off.

The inventory equals what is physically present at the study station. A path the participant cannot execute cannot be followed, so it carries no information for the assistant.

## A.7 LaTeX-ready statement

```latex
\begin{definition}[Recipe variation]
Let $D = (s_0, G, I, B)$ be a dish specification with start state $s_0$,
goal state set $G$, closed inventory $I$ of ingredients and utensils, and
safety bounds $B$. A \emph{recipe variation} of $D$ is a pair
$V = (\Sigma, \prec)$, where $\Sigma$ is a set of parameterised steps
$\sigma = (a, E, \pi \rightarrow \rho, \theta)$ and $\prec$ is a partial
order on $\Sigma$, such that
(i) every $\sigma \in \Sigma$ involves only elements of $I$;
(ii) executing $\Sigma$ from $s_0$ in any order consistent with $\prec$
ends in a state in $G$;
(iii) no state reached during that execution violates a bound in $B$; and
(iv) $\sigma_i \prec \sigma_j$ whenever a pre-condition of $\sigma_j$ is
established by a post-condition of $\sigma_i$.

Two variations differ \emph{structurally} if they differ in which steps
occur, up to step equivalence, or in $\prec$; they differ
\emph{parametrically} if they contain equivalent steps in the same order
but differ in the execution parameters $\theta$ of at least one step.
Differences in wording or between functionally equivalent utensils are
not variations.
\end{definition}
```

---

# Part B — Project notes

## B.1 Decisions and who made them

All decisions below were made by the author on 2026-10-11.

| Decision | Choice | Reason |
| --- | --- | --- |
| Ingredients on the station | Eggs, salt, pepper, oregano, butter, olive oil | Author's choice. No milk or cream. |
| Utensils on the station | Pan, bowl, wooden spatula or spoon, hand whisk, fork, plate, heat source | Author's choice. |
| Goal state | Eggs on the plate | Carry-over cooking can scorch eggs left in the pan. |
| Composed variations | Allowed | Novices will not follow one source exactly; branch selection in Fusion already assumes steps can be mixed. |
| Parametric differences | Count as variation | A step done for a different time at a different heat is a different way of cooking, and changes the timing the system should expect. |

## B.2 Why the definition is shaped this way

- **Fusion** (`04-architecture.md` §4.8) selects the branch whose pre-conditions match `K2` and stays at `D_t = 0` while the cook is on a valid path. "Valid variation" is exactly "do not intervene".
- **The study** (`05-evaluation.md` §5.1) uses one standardised kitchen with identical equipment, so the inventory is fixed and known in advance.
- **`K2`** sees four egg states. The goal set and the notion of deviation are stated in that vocabulary so they can be checked at runtime.

## B.3 State of `k1/data/k1/graph.json` against this definition

Observed on 2026-10-11 (53 nodes, 11 recipes), before k1-0.3.0. The second and third points
are fixed by the scope rule in k1-0.3.0 (`Notes/08-k1-pipeline.md`, "Scope enforcement"). The
first and last are still open.

- **No shared nodes.** The only merge is a duplicated `serious_eats` step. Fingerprints use the raw action string (`fuse/dag_builder.py`), so equivalent steps in different wording or language stay separate. The graph is 11 chains, which makes composed variations impossible.
- **Out-of-inventory entities present:** bread/toast, chutney, goat cheese, chives, parsley, milk, cream, soy cream, water, charcoal griddle, coals, measuring jug.
- **Unresolved Portuguese entities:** `ovos`/`ovo`, `manteiga`, `sal`, `azeite`, `natas`, `leite`, `frigideira`, `tigela`, `taça`, `garfo`, `espátula`, `fogo` are separate from their English equivalents.
- **Heat and duration** are not stored as coupled parameter tuples.

## B.4 Effect on the corpus (`k1/config/recipes.yaml`)

| Recipe | Outcome | Why |
| --- | --- | --- |
| `epicurious_bain_marie`, `heston_blumenthal` | Exclude | Goal-reaching path needs a double boiler |
| `food_network_goat_cheese` | Exclude | Charcoal griddle, 16 eggs, goat cheese |
| `couple_cooks_goat_cheese` | Exclude (check after ingest) | Goat cheese and asparagus |
| `food52_fluffiest` | Exclude (recommended) | Little remains without goat cheese and soy cream |
| `simply_recipes_creme_fraiche`, `ina_garten_fluffy` | Check after ingest | Defining ingredient is outside the inventory |
| `jamie_oliver` | Keep, trim serving on toast | Core path fits |
| `recipe_tin_eats` | Keep, trim milk, toast and parsley garnish | Core path fits |
| `love_and_lemons`, `the_kitchn_soft_creamy`, `continente`, `serious_eats` | Keep, trim milk/cream/water and garnish | Core path fits |
| `tudo_gostoso` | Keep, trim late milk | In-pan cold-start technique is a structural variation |
| `pingo_doce` | Keep as is | Fully inside the inventory |

Recipes not yet ingested need the same check once they scrape.

## B.5 Goal completion (k1-0.4.1)

Condition 2 of the definition requires every variation to end in a goal state, with the eggs
on the plate. Many sources stop at the pan, or end with a serving line that is outside the
dish. The pipeline therefore appends one closing `Plate` step, by rule, to any recipe that
has none. The step is marked `rule/goal_completion` and has no source span, so it is never
presented as something a source says. In the reviewed graph of run `scope02` this applies to
`continente`, `jamie_oliver`, `love_and_lemons`, and `tudo_gostoso`.

## B.6 Open points

- **Oregano has no source.** None of the 11 ingested recipes uses it. Either model a generic optional-herb seasoning step that chive and parsley steps map onto, or remove oregano from the station.
- **Granularity of step equivalence.** At the four-label `K2` level, "beat eggs" and "add salt" are both `egg: liquid → liquid` and would collide. Equivalence has to be decided on the fine-grained `physics_state` plus the set of entities involved, not on `k2_label` alone.
- **Heat is a level, not a temperature.** Sources say "low", "medium-low", "lume brando". The parameter in `K1` should be a hob level mapped to the lab's induction hob.
- **Bowl or measuring jug.** The jug in `jamie_oliver` is aliased to `bowl` in `ontology.yaml`; confirm.
- **Pipeline changes still to do:** transition-based node merging and parameter tuples on nodes. The inventory filter and PT→EN aliases are done (k1-0.3.0).
