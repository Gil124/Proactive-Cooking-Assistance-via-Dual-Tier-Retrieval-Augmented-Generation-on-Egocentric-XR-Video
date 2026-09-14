// K1 Graph Schema Constraints and Indexes
// Apply before ingestion: k1 store --apply-schema
// Compatible with Neo4j 5.x

// ── Uniqueness constraints ────────────────────────────────────────────────────

CREATE CONSTRAINT k1_process_node_id IF NOT EXISTS
FOR (n:Process) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT k1_transfer_node_id IF NOT EXISTS
FOR (n:Transfer) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT k1_plate_node_id IF NOT EXISTS
FOR (n:Plate) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT k1_ingredient_node_id IF NOT EXISTS
FOR (n:Ingredient) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT k1_tool_node_id IF NOT EXISTS
FOR (n:Tool) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT k1_safety_bound_node_id IF NOT EXISTS
FOR (n:SafetyBound) REQUIRE n.node_id IS UNIQUE;

// ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX k1_node_type IF NOT EXISTS
FOR (n:Process) ON (n.node_type);

CREATE INDEX k1_canonical_action IF NOT EXISTS
FOR (n:Process) ON (n.canonical_action);

CREATE INDEX k1_transfer_canonical IF NOT EXISTS
FOR (n:Transfer) ON (n.canonical_action);

CREATE INDEX k1_plate_canonical IF NOT EXISTS
FOR (n:Plate) ON (n.canonical_action);
