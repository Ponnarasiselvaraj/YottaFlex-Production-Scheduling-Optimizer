# Data dictionary

All IDs are immutable strings. Plant timestamps use ISO-8601 and Asia/Kolkata. Durations are minutes. Order quantities are units; inventory/material requirements are kg.

| Entity | PK | Main fields and validation |
|---|---|---|
| Product | product_id | sku unique; family required; lifecycle_state ACTIVE/INACTIVE |
| Routing | routing_id | product_id FK; revision positive; effective_from <= effective_to; ACTIVE/RETIRED |
| RouteOperation | route_operation_id | routing_id FK; sequence_no unique per routing; duration > 0 |
| Operation | operation_id | order_id and routing_id FKs; sequence positive; RELEASED/SCHEDULED/COMPLETED/BLOCKED |
| Machine | machine_id | machine_type required; capacity_units_per_hour > 0; lifecycle state |
| MachineCalendar | calendar_id | machine_id FK; shift_start < shift_end; working_days enumerated weekday numbers |
| MachineEligibility | composite routing_id/sequence_no/machine_id | N:M bridge between route step and eligible machine |
| Material | material_id | unit and nonnegative safety_stock; lifecycle state |
| InventoryLot | lot_id | material_id FK; quantity >= 0; available_at <= expiry_date; AVAILABLE/QUARANTINED/CONSUMED |
| ProductionOrder | order_id | product_id/routing_id FKs; quantity > 0; due_date >= order_date; URGENT/HIGH/NORMAL/LOW |
| OperationSchedule | schedule_id | operation_id and machine_id FKs; end_time > start_time; SCHEDULED/UNSCHEDULED |
| ChangeoverMatrix | composite from_family/to_family | directed transition; changeover_minutes >= 0 |
| MaterialRequirement | composite order_id/material_id | both FKs; required_quantity > 0 |
| Tool | tool_id | tool_type; available_units > 0; lifecycle state |
| ToolRequirement | composite order_id/operation_sequence/tool_id | order/tool FKs; required_units > 0 |
| MachineDowntime | downtime_id | machine_id FK; end_time > start_time; reason |
| ScheduleEvent | event_id | entity_type/id, event_type, event_time, details; append-only history |
| GroundTruth | scenario_id | issue_type, binary ground_truth_label, expected_detection; separate from inputs |

## Cardinality
- Product 1:N Routing; Routing 1:N RouteOperation; ProductionOrder 1:N Operation.
- RouteOperation N:M Machine through MachineEligibility.
- ProductionOrder N:M Material through MaterialRequirement; Material 1:N InventoryLot.
- Machine 1:1 calendar in this dataset; Machine 1:N downtime and schedules.
- Operation 0:1 schedule row in this baseline run.
- Tool 1:N ToolRequirement; shared tool availability is a constrained resource.
- Effective dates are stored on Routing; lifecycle states are stored on master and transaction records.

Optional fields include routing.effective_to, operation.tool_id and schedule.reason.


## Added runtime ledgers and detector outputs
- MaterialAllocation (`allocation_id` PK): `order_id` FK, `material_id` FK, `lot_id` FK, allocated quantity (kg), lot availability timestamp, consumption timestamp, RESERVED/CONSUMED state.
- InventoryBalance (one derived row per `lot_id`): original quantity, allocated quantity and remaining quantity; validates `original = allocated + remaining`.
- ConstraintDetectionResult (`scenario_id` PK/FK to anomaly scenario): detector rule, boolean detection, evidence. Ground-truth labels are not detector input.
- Constraint detection metrics: aggregate TP/FP/FN, precision, recall and F1; evaluation output only.
