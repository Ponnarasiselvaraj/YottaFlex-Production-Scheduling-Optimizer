# YottaFlex Production Scheduling System

Synthetic, reproducible manufacturing scheduling solution for the Associate AI Forward Deployed Engineer challenge.

## What it includes
- Master-first synthetic data generation (100 products, 40 machines, 500 orders, 2,000 operations, 200 materials in full mode).
- Routing and machine eligibility, weekday shift calendars, planned downtime, sequence-dependent changeovers.
- Priority-aware inventory lot reservation using FEFO (first-expiry-first-out), consumption timestamps and remaining lot balances.
- Finite shared-tool capacity reservations during scheduling.
- Four-stage deterministic finite-resource scheduler with a configurable weighted objective balancing makespan, priority-weighted tardiness and sequence-dependent changeover cost.
- Independent five-rule anomaly detector. The detector reads anomaly fixtures and operational context, not `ground_truth.csv`; ground truth is joined only afterward for evaluation.
- Append-only schedule event output, CSV/JSON exports, SQLite database, Streamlit dashboard, and automated tests.

## Requirements
Python 3.10+ and Visual Studio Code with the Python extension.

## Windows PowerShell setup
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If activation is blocked:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

## Run starter data
```powershell
python main.py --scale starter
```
Starter scale: 10 products, 8 machines, 20 orders, 80 operations, 30 materials.

## Run full challenge data
```powershell
python main.py --scale full
```
Full scale: 100 products, 40 machines, 500 orders, 2,000 operations, 200 materials.

## Launch the website dashboard
After running the CLI:
```powershell
streamlit run dashboard/app.py
```
Open the local URL printed in terminal (normally `http://localhost:8501`).

## Run tests
```powershell
pytest -q
```

## Generated outputs
`data/` contains:
- Master and transaction tables in CSV and JSON.
- `operation_schedules.csv/json` and append-style `schedule_events.csv/json`.
- `anomaly_scenarios.csv/json` and separate `ground_truth.csv/json`.
- `constraint_detection_results.csv/json` and `constraint_detection_metrics.json`.
- `material_allocations.csv/json`, `inventory_balances.csv/json`, and `inventory_shortages.csv`.
- `metrics.json` (including objective components and score), `applied_objective_config.json`, `validation_summary.csv`, `master_validation.csv`, `source_manifest.json`, and `production.db`.

## Independent detector rules
1. `OVERLAP_ON_MACHINE`: two intervals on the same machine overlap.
2. `PRECEDENCE_VIOLATION`: an operation starts before its predecessor ends.
3. `MATERIAL_BEFORE_AVAILABLE`: consumption timestamp is earlier than lot availability.
4. `OUTSIDE_SHIFT`: operation interval is outside weekday machine shift bounds.
5. `CHANGEOVER_OMITTED`: recorded setup is less than the directed family-transition matrix requirement.

Detector performance is evaluated against the separate ground-truth file only after predictions are written.

## Reproducibility
Default seed: `20261022`. The CLI regenerates two independent copies and compares SHA-256 checksums for CSV source tables. Skip the additional run with `--skip-repro`.

## Lawful provenance
All data is original synthetic data generated locally. No external or personal dataset is used.

## Scheduling model and limitations
This is a deterministic, finite-resource list-scheduling heuristic, not a globally optimal CP-SAT/MILP solver. It uses four routing-stage passes; machine allocation minimizes estimated completion time and setup cost within each stage. It is not guaranteed to minimize global makespan or tardiness. Material lots are reserved by priority and FEFO; inventory balances show allocated/reserved quantity, while scheduled orders receive consumption timestamps. For production deployment, add transactional inventory posting, schedule revision/versioning, and a CP-SAT optimizer with an objective balancing makespan, weighted tardiness and changeover cost.

## Developer edit map
See [`docs/edit_map.md`](docs/edit_map.md) for the exact file to edit for each feature.


## Multi-objective scheduling
Configure `config/scheduling_objective.json` to balance makespan, priority-weighted tardiness and changeover minutes. Default weights are 0.35 / 0.50 / 0.15. The metrics output reports each realized component and the weighted objective score. The heuristic is not guaranteed globally optimal; compare actual KPIs after tuning weights.


The full-scale run also reports a same-seed comparison against the earlier earliest-finish scheduler using `config/baseline_benchmark_full.json`. This is a heuristic benchmark, not a mathematical optimality proof. Expect trade-offs between the three KPIs when changing weights.

## Exact global optimization (OR-Tools CP-SAT)

The project also includes an exact constraint-programming model in `src/global_optimizer.py`.
It jointly chooses operation-to-machine assignments and start times, and encodes route
precedence, shift calendars, planned downtime, shared-tool cumulative capacity, and
sequence-dependent changeover separation. The weighted objective uses the configured
makespan, priority-weighted tardiness, and changeover weights in
`config/scheduling_objective.json`.

Install the solver dependency and run:

```bash
pip install -r requirements.txt
python main.py --scale starter --solver global --solver-time-limit 120
```

For the full 2,000-operation data set, try a longer limit (for example 1,800 seconds):

```bash
python main.py --scale full --solver global --solver-time-limit 1800
```

The solver writes `data/optimization_report.json`. **Only `status: OPTIMAL` with
`optimality_proven: true` means a global optimum has been proved for this encoded
finite-horizon integer model.** `FEASIBLE` means the solver found a valid schedule but
ran out of time before proving it optimal. `INFEASIBLE` means no schedule exists within
the modeled horizon and constraints. Scheduling is NP-hard; a global proof for 2,000
operations may require substantial compute and may not be reached within a practical
runtime. The model uses integer-minute time and the configured finite horizon, so the
proof is relative to that discretization and horizon, not an unrestricted continuous-time
industrial scheduling problem.

The existing fast heuristic remains available as the default (`--solver heuristic`).
