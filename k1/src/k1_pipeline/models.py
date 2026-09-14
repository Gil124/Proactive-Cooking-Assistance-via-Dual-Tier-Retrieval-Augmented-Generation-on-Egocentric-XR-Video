"""
Pydantic models for the K1 pipeline.

Node types follow PIC §4.6 and Notes/08-k1-pipeline.md.
K2 labels are the four values {liquid, coagulating, solid, scorched} only.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


# ── K2 label set (frozen) ─────────────────────────────────────────────────────

class K2Label(str, Enum):
    liquid = "liquid"
    coagulating = "coagulating"
    solid = "solid"
    scorched = "scorched"


# ── Ontology node types ───────────────────────────────────────────────────────

class NodeType(str, Enum):
    Process = "Process"
    Transfer = "Transfer"
    Plate = "Plate"


# ── L1 Ingest ─────────────────────────────────────────────────────────────────

class RecipeStep(BaseModel):
    number: int
    text: str


class CanonicalRecipe(BaseModel):
    """Output of L1 ingest for a single recipe."""
    recipe_id: str
    title: str
    source_url: str
    variant_label: str
    gold: bool = False
    ingredients: list[str]
    tools: list[str]
    steps: list[RecipeStep]
    temperatures_mentioned: list[str] = Field(default_factory=list)
    timings_mentioned: list[str] = Field(default_factory=list)


# ── L2 Extraction ─────────────────────────────────────────────────────────────

class StateCondition(BaseModel):
    """A (entity, physics_state, k2_label) triple used in pre/post conditions."""
    entity_id: str = Field(description="Canonical entity name, e.g. 'egg', 'butter'")
    physics_state: str = Field(
        description="Fine-grained physics state, e.g. 'soft_curd', 'HETEROGENEOUS_LIQUID'"
    )
    k2_label: K2Label = Field(
        description="Compiled K2 label: liquid | coagulating | solid | scorched"
    )


class TimingConstraints(BaseModel):
    duration_s: Optional[float] = Field(
        default=None,
        description="Expected duration in seconds, if stated in the recipe."
    )
    deadline: Optional[str] = Field(
        default=None,
        description="Qualitative deadline, e.g. 'before eggs start to set'."
    )


class ExtractedNode(BaseModel):
    """Generator output for one recipe step."""
    node_id: UUID = Field(default_factory=uuid4)
    recipe_id: str = Field(default="")
    step_number: int = Field(default=0)
    node_type: NodeType = Field(description="Process | Transfer | Plate")
    action_phrase: str = Field(description="Short verb phrase naming the action, e.g. 'whisk eggs'")
    pre_conditions: list[StateCondition] = Field(
        default_factory=list,
        description="Entity states BEFORE this step executes."
    )
    post_conditions: list[StateCondition] = Field(
        default_factory=list,
        description="Entity states AFTER this step executes."
    )
    timing_constraints: Optional[TimingConstraints] = None
    ingredients: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    source_span: str = Field(
        description="Verbatim substring of the step text that grounds this extraction."
    )
    # Explicit temperature field: LLM sets this ONLY when the step text states a temperature.
    # temperature_c is checked directly for invented-temperature detection.
    # Never inferred from digit patterns in the JSON dump.
    temperature_c: Optional[float] = Field(
        default=None,
        description=(
            "Temperature in Celsius stated explicitly in the recipe step text. "
            "Set ONLY when the step mentions a specific temperature. "
            "Do NOT invent a value; leave null if the text has no temperature."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)
    extractor_model: str = Field(default="")

    @model_validator(mode="after")
    def check_process_conditions(self) -> "ExtractedNode":
        if self.node_type == NodeType.Process:
            if not self.pre_conditions:
                raise ValueError("Process nodes must have at least one pre_condition.")
            if not self.post_conditions:
                raise ValueError("Process nodes must have at least one post_condition.")
        return self


# ── L2 Critic ─────────────────────────────────────────────────────────────────

class CriticVerdict(str, Enum):
    accept = "accept"
    revise = "revise"
    reject = "reject"


class CriticOutput(BaseModel):
    """Critic model output for one extracted node."""
    node_id: UUID = Field(default_factory=uuid4)
    verdict: CriticVerdict
    grounding_quote: str = Field(
        description="A substring of the source step text confirming or denying the extraction."
    )
    issues: list[str] = Field(
        default_factory=list,
        description="List of identified problems. Empty for 'accept'."
    )
    critic_model: str = Field(default="")
    revision_instructions: Optional[str] = Field(
        default=None,
        description="Populated only for 'revise' verdict. Specific fix instructions for the generator."
    )


# ── L3 Fused graph ────────────────────────────────────────────────────────────

class SafetyBound(BaseModel):
    """A HAS_SAFETY_BOUND edge value, sourced from physics_bounds.yaml."""
    bound_id: str
    label: str
    temperature_c: Optional[float]
    description: str
    k2_transition: Optional[str]
    severity: str  # "suggestion" | "alert"


class K1Node(BaseModel):
    """A node in the fused K1 DAG, ready for Neo4j ingestion."""
    node_id: str  # deterministic fingerprint-based ID after fusion
    node_type: NodeType
    action_phrase: str
    canonical_action: str  # lowercased, normalized
    pre_conditions: list[StateCondition]
    post_conditions: list[StateCondition]
    timing_constraints: Optional[TimingConstraints] = None
    ingredients: list[str]
    tools: list[str]
    safety_bounds: list[SafetyBound] = Field(default_factory=list)
    # Provenance -- parallel lists, one entry per observation (merge appends to all)
    source_recipe_ids: list[str]
    source_step_indices: list[int]
    source_spans: list[str]
    extractor_models: list[str]
    critic_verdicts: list[str]
    confidences: list[float]          # raw per-observation values
    mean_confidence: float             # derived: mean(confidences)


class K1Edge(BaseModel):
    """A directed edge in the K1 DAG."""
    from_node_id: str
    to_node_id: str
    edge_type: str  # NEXT | REQUIRES | HAS_SAFETY_BOUND | INGREDIENT_OF | USES_TOOL
    source_recipe_id: Optional[str] = None
    weight: float = 1.0
    properties: dict = Field(default_factory=dict)


class K1Graph(BaseModel):
    """The complete fused K1 graph."""
    version: str = "k1-0.2.0"
    nodes: list[K1Node]
    edges: list[K1Edge]
    ingredient_nodes: list[dict] = Field(default_factory=list)
    tool_nodes: list[dict] = Field(default_factory=list)
    branch_labels: list[str] = Field(default_factory=list)


# ── Evaluation ────────────────────────────────────────────────────────────────

class GoldCondition(BaseModel):
    """One (entity_id, k2_label) pair in the gold annotation."""
    entity_id: str
    k2_label: K2Label


class GoldExpected(BaseModel):
    """The expected extraction values for one recipe step."""
    node_type: NodeType
    action_phrase: str
    pre_conditions: list[GoldCondition] = Field(default_factory=list)
    post_conditions: list[GoldCondition] = Field(default_factory=list)
    has_safety_bound: bool = False


class GoldNode(BaseModel):
    """
    A human-annotated gold node for evaluation.
    Schema matches data/gold/ANNOTATION_PROTOCOL.md exactly.
    """
    recipe_id: str
    step_number: int
    expected: GoldExpected
    annotator: str
    annotation_date: str
    notes: str = ""
