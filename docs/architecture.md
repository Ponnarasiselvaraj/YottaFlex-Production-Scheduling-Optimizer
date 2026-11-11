# Architecture and business assumptions

## Component map
- `main.py`: CLI orchestration.
- `src/generator.py`: deterministic master-first synthetic data generation.
- `src/inventory.py`: FEFO lot allocation, shortage reporting, consumption timestamps and lot balance reconciliation.
- `src/scheduler.py`: finite-resource four-stage scheduler using the weighted objective.
- `src/objective.py`: objective configuration validation and realized objective metrics.
- `config/scheduling_objective.json`: objective weights, normalizers and priority tardiness multipliers.
- `src/anomalies.py`: five isolated labelled anomaly fixtures.
- `src/constraint_engine.py`: independent rule-based detector and precision/recall/F1 evaluation.
- `src/validation.py`: PK/FK integrity, enums, calendars, downtime, overlap, precedence, inventory arithmetic, shared-tool capacity and changeover checks.
- `src/metrics.py`: makespan, tardiness, on-time delivery, changeover and inventory KPIs.
- `src/database.py`: SQLite export.
- `src/reproducibility.py`: fixed-seed SHA-256 reproducibility comparison.
- `dashboard/app.py`: Streamlit web dashboard for Gantt, schedules, detection, inventory and tools.

## Scheduling workflow
1. Generate master data and then dependent orders/operations/material/tool requirements.
2. Allocate required materials to lots in priority and FEFO order. Orders with shortages are blocked and their operations become unscheduled with an explicit reason.
3. Schedule operations in routing sequence stages. Within each stage, priority and due date determine dispatch order.
4. Select only eligible machines. Candidate completion time, setup time and machine ID determine the selected machine.
5. Respect weekday shift calendars, planned downtime, machine availability, sequence-dependent setup and finite shared-tool units.
6. Update machine availability and order precedence state after each operation.
7. Persist schedule events, material allocations/consumption, inventory balances, anomalies, detector results and KPIs.

## Five independent detection rules
- Machine overlap: compare scenario interval to the reference schedule interval on the same machine.
- Precedence: compare operation start against predecessor end.
- Material availability: compare consumption time against lot availability.
- Shift calendar: verify weekday and start/end within the shift.
- Changeover: compare observed setup against the directed family-to-family matrix.

`src/constraint_engine.py` does not use the ground-truth labels to make predictions. It loads ground truth only after detector output is persisted, for evaluation metrics.

## Data relationships
- Product 1:N Routing; Routing 1:N RouteOperation; ProductionOrder 1:N Operation.
- RouteOperation N:M Machine through MachineEligibility.
- ProductionOrder N:M Material through MaterialRequirement; Material 1:N InventoryLot.
- Machine 1:1 MachineCalendar; Machine 1:N MachineDowntime and OperationSchedule.
- Tool 1:N ToolRequirement; tool availability is enforced as overlapping interval capacity.
- ProductionOrder 1:N MaterialAllocation; InventoryLot 1:N MaterialAllocation.
- Operation 0:1 OperationSchedule; schedule events are recorded separately.

## Multi-objective optimization and limitations
`config/scheduling_objective.json` controls the weighted objective:
`J = alpha * normalized_makespan + beta * normalized_weighted_tardiness + gamma * normalized_changeover`.

Defaults: `alpha=0.35`, `beta=0.50`, `gamma=0.15`. Weights are normalized to sum to one. Priority tardiness multipliers are URGENT=4, HIGH=3, NORMAL=2, LOW=1. Normalization scales are explicit configuration values so the three terms are comparable. For each eligible machine candidate, the scheduler estimates the operation end, adds estimated remaining order processing time, calculates projected order tardiness and setup cost, then chooses the lowest weighted score. Queue dispatch remains priority/due-date ordered.

Realized metrics are written to `metrics.json`: makespan hours, priority-weighted tardiness hours, changeover minutes, normalized component values, applied weights and composite objective score. The dashboard displays these values. The exact configuration is saved to `data/applied_objective_config.json`.

This remains a deterministic list-scheduling heuristic, not a globally optimal CP-SAT/MILP solver. Downstream processing time is estimated from average machine capacity and does not fully model future queueing. A next step could be an OR-Tools CP-SAT model with optional intervals, cumulative tool constraints, sequence-dependent setup transitions and a weighted objective. Any claimed improvement should be based on same-seed, same-data KPI comparisons.

## Inventory semantics
Lots are allocated in priority/due-date order using FEFO. Allocated quantity is subtracted from lot remaining balance; allocations for orders that receive a schedule get a consumption timestamp at their first operation start. The sample dataset does not model partial scrap, returns or mid-process material consumption.

## Event/history semantics
Initial scheduling emits one event per operation schedule. The `append_schedule_event` helper appends additional events rather than rewriting the existing event log. A production deployment should add immutable schedule revision IDs and transactional writes.

## Assumptions
- Calendar: Monday-Friday, 08:00-16:00 Asia/Kolkata.
- Operations are non-preemptive and must fit within one shift.
- Material must be available before the first operation.
- Tools are finite reusable resources reserved over operation intervals.
- Downtime is a hard machine unavailability interval.
- External data is not used; all records are synthetic and reproducible.
