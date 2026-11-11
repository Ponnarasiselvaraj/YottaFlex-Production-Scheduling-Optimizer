"""Exact CP-SAT production scheduling model.

A returned OPTIMAL status is a mathematical optimality proof for the encoded
integer model. FEASIBLE means a valid incumbent was found but optimality was
not proved before the configured time limit.
"""
from __future__ import annotations
from pathlib import Path
import json
import math
import pandas as pd

HORIZON = pd.Timestamp("2026-11-16 08:00:00")


def _minute(ts: pd.Timestamp) -> int:
    return int((pd.Timestamp(ts) - HORIZON).total_seconds() // 60)


def _shift_domain(start_min: int, duration: int, shift_start: str, shift_end: str,
                  working_days: str, horizon_min: int):
    """Allowed start ranges; each operation must fit wholly in one working shift."""
    sh, sm = map(int, shift_start.split(":"))
    eh, em = map(int, shift_end.split(":"))
    workdays = {int(x) for x in str(working_days).split(",") if str(x).strip()}
    ranges = []
    first_day = HORIZON.normalize()
    days = max(1, math.ceil(horizon_min / 1440) + 1)
    for offset in range(days):
        day = first_day + pd.Timedelta(days=offset)
        if day.weekday() not in workdays:
            continue
        lo = _minute(day + pd.Timedelta(hours=sh, minutes=sm))
        hi = _minute(day + pd.Timedelta(hours=eh, minutes=em)) - duration
        lo, hi = max(0, lo), min(horizon_min, hi)
        if lo <= hi:
            ranges.append((lo, hi))
    return ranges


def solve_global(data_dir="data", time_limit_seconds=None, workers=None, log_search=False):
    """Solve the finite-horizon scheduling MILP/CP model using OR-Tools CP-SAT."""
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise RuntimeError("Global optimization requires OR-Tools. Install with: pip install ortools>=9.10") from exc

    d = Path(data_dir)
    read = lambda name: pd.read_csv(d / f"{name}.csv")
    orders, ops, machines = read("production_orders"), read("operations"), read("machines")
    calendars, eligibility = read("machine_calendars"), read("machine_eligibility")
    downtime, changes = read("machine_downtime"), read("changeover_matrix")
    tools, tool_reqs, products = read("tools"), read("tool_requirements"), read("products")
    from .inventory import allocate_materials, finalize_consumption
    from .objective import load_objective_config

    ready, _, _, shortages = allocate_materials(data_dir)
    blocked = set(shortages.order_id.unique()) if not shortages.empty else set()
    cfg = load_objective_config()
    w, norm = cfg["weights"], cfg["normalization"]
    priority_w = cfg["priority_tardiness_weights"]

    # Time is represented in integer minutes from the fixed planning origin.
    horizon_days = int(json.loads((d / "global_solver_config.json").read_text()).get("horizon_days", 180)) if (d / "global_solver_config.json").exists() else 180
    horizon = horizon_days * 24 * 60
    time_limit_seconds = float(time_limit_seconds or (json.loads((d / "global_solver_config.json").read_text()).get("time_limit_seconds", 120) if (d / "global_solver_config.json").exists() else 120))
    workers = int(workers or (json.loads((d / "global_solver_config.json").read_text()).get("workers", 8) if (d / "global_solver_config.json").exists() else 8))

    machine_rows = machines.set_index("machine_id").to_dict("index")
    cal_rows = calendars.set_index("machine_id").to_dict("index")
    eligible_map = eligibility.groupby(["routing_id", "sequence_no"]).machine_id.apply(list).to_dict()
    family = dict(zip(products.product_id, products.family))
    setup_map = {(r.from_family, r.to_family): int(r.changeover_minutes) for r in changes.itertuples()}
    tool_caps = tools.set_index("tool_id").available_units.astype(int).to_dict()
    tool_req_map = {(r.order_id, int(r.operation_sequence)): (r.tool_id, int(r.required_units)) for r in tool_reqs.itertuples()}
    order_rows = orders.set_index("order_id").to_dict("index")

    model = cp_model.CpModel()
    starts, ends, presences, intervals_by_machine = {}, {}, {}, {m: [] for m in machines.machine_id}
    machine_choice = {}
    op_rows = {r.operation_id: r for r in ops.itertuples()}
    candidates_by_machine = {m: [] for m in machines.machine_id}
    op_duration_by_machine = {}

    for op in ops.itertuples():
        oid = op.order_id
        if oid in blocked:
            continue
        order = order_rows[oid]
        duration_by_machine = {}
        for mid in eligible_map.get((op.routing_id, int(op.sequence_no)), []):
            capacity = max(1, int(machine_rows[mid]["capacity_units_per_hour"]))
            duration = max(1, math.ceil(int(op.duration_minutes) * int(order["quantity"]) / capacity))
            ranges = _shift_domain(0, duration, cal_rows[mid]["shift_start"], cal_rows[mid]["shift_end"], cal_rows[mid]["working_days"], horizon)
            if ranges:
                duration_by_machine[mid] = (duration, ranges)
        if not duration_by_machine:
            raise RuntimeError(f"No eligible machine/calendar domain for operation {op.operation_id}")
        s = model.NewIntVar(0, horizon, f"start_{op.operation_id}")
        e = model.NewIntVar(0, horizon, f"end_{op.operation_id}")
        starts[op.operation_id], ends[op.operation_id] = s, e
        choices = []
        for mid, (duration, ranges) in duration_by_machine.items():
            p = model.NewBoolVar(f"assign_{op.operation_id}_{mid}")
            local_s = model.NewIntVarFromDomain(cp_model.Domain.FromIntervals(ranges), f"s_{op.operation_id}_{mid}")
            local_e = model.NewIntVar(0, horizon, f"e_{op.operation_id}_{mid}")
            interval = model.NewOptionalIntervalVar(local_s, duration, local_e, p, f"iv_{op.operation_id}_{mid}")
            model.Add(s == local_s).OnlyEnforceIf(p)
            model.Add(e == local_e).OnlyEnforceIf(p)
            choices.append(p)
            machine_choice[(op.operation_id, mid)] = p
            candidates_by_machine[mid].append((op.operation_id, p, interval, duration, op.setup_family))
            intervals_by_machine[mid].append(interval)
            op_duration_by_machine[(op.operation_id, mid)] = duration
        model.AddExactlyOne(choices)

    # Route precedence and material availability.
    for oid, group in ops[~ops.order_id.isin(blocked)].groupby("order_id"):
        ordered = group.sort_values("sequence_no")
        ids = ordered.operation_id.tolist()
        if oid in ready and pd.Timestamp(ready[oid]) != pd.Timestamp.max:
            ready_min = max(0, _minute(pd.Timestamp(ready[oid])))
            model.Add(starts[ids[0]] >= ready_min)
        for a, b in zip(ids, ids[1:]):
            model.Add(starts[b] >= ends[a])

    # Machine no-overlap, planned downtime, and sequence-dependent setup.
    setup_terms = []
    for mid, entries in candidates_by_machine.items():
        fixed = []
        for row in downtime[downtime.machine_id == mid].itertuples():
            a, b = max(0, _minute(pd.Timestamp(row.start_time))), min(horizon, _minute(pd.Timestamp(row.end_time)))
            if b > a:
                fixed.append(model.NewIntervalVar(a, b-a, b, f"down_{mid}_{len(fixed)}"))
        model.AddNoOverlap([x[2] for x in entries] + fixed)
        # Add sequence-dependent separation for each pair of candidate operations.
        for i in range(len(entries)):
            id_a, p_a, _, _, fam_a = entries[i]
            for j in range(i + 1, len(entries)):
                id_b, p_b, _, _, fam_b = entries[j]
                if id_a == id_b:
                    continue
                before_ab = model.NewBoolVar(f"before_{id_a}_{id_b}_{mid}")
                before_ba = model.NewBoolVar(f"before_{id_b}_{id_a}_{mid}")
                model.AddBoolOr([p_a.Not(), p_b.Not(), before_ab, before_ba])
                model.AddAtMostOne(before_ab, before_ba)
                ab = setup_map.get((fam_a, fam_b), 0)
                ba = setup_map.get((fam_b, fam_a), 0)
                model.Add(starts[id_b] >= ends[id_a] + ab).OnlyEnforceIf(before_ab)
                model.Add(starts[id_a] >= ends[id_b] + ba).OnlyEnforceIf(before_ba)
                if ab:
                    setup_terms.append(ab * before_ab)
                if ba:
                    setup_terms.append(ba * before_ba)

    # Shared-tool cumulative capacities.
    for tool_id, cap in tool_caps.items():
        tool_intervals, demands = [], []
        for op in ops.itertuples():
            req = tool_req_map.get((op.order_id, int(op.sequence_no)))
            if not req or req[0] != tool_id or op.operation_id not in starts:
                continue
            demand = req[1]
            for mid in eligible_map.get((op.routing_id, int(op.sequence_no)), []):
                p = machine_choice.get((op.operation_id, mid))
                if p is None:
                    continue
                duration = op_duration_by_machine[(op.operation_id, mid)]
                interval = model.NewOptionalIntervalVar(starts[op.operation_id], duration,
                    ends[op.operation_id], p, f"tool_{tool_id}_{op.operation_id}_{mid}")
                tool_intervals.append(interval); demands.append(demand)
        if tool_intervals:
            model.AddCumulative(tool_intervals, demands, int(cap))

    # Objective: normalized makespan + weighted order tardiness + sequence setups.
    makespan = model.NewIntVar(0, horizon, "makespan")
    completion_vars = []
    order_tardy_terms = []
    for oid, group in ops[~ops.order_id.isin(blocked)].groupby("order_id"):
        last_id = group.sort_values("sequence_no").iloc[-1].operation_id
        completion = ends[last_id]
        completion_vars.append(completion)
        due = max(0, min(horizon, _minute(pd.Timestamp(order_rows[oid]["due_date"]))))
        tardy = model.NewIntVar(0, horizon, f"tardy_{oid}")
        model.Add(tardy >= completion - due)
        model.Add(tardy >= 0)
        pr_weight = float(priority_w.get(order_rows[oid]["priority"], 1.0))
        order_tardy_terms.append(int(round(pr_weight * 1000)) * tardy)
    if completion_vars:
        model.AddMaxEquality(makespan, completion_vars)

    # Scale all terms to integers. Positive coefficients preserve the configured objective.
    scale = 1_000_000_000_000
    c_m = int(round(w["makespan"] / (float(norm["makespan_hours"]) * 60) * scale))
    c_t = int(round(w["weighted_tardiness"] / (float(norm["weighted_tardiness_hours"]) * 60 * 1000) * scale))
    c_c = int(round(w["changeover"] / float(norm["changeover_minutes"]) * scale))
    model.Minimize(c_m * makespan + c_t * sum(order_tardy_terms) + c_c * sum(setup_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = bool(log_search)
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        report = {"solver": "OR-Tools CP-SAT", "status": status_name, "optimality_proven": False,
                  "time_limit_seconds": time_limit_seconds, "message": "No feasible schedule found."}
        (d / "optimization_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        raise RuntimeError(f"Global optimizer did not find a feasible schedule: {status_name}")

    rows = []
    for op in ops.itertuples():
        if op.operation_id not in starts:
            rows.append({"operation_id":op.operation_id,"order_id":op.order_id,"machine_id":"","start_time":"","end_time":"",
                         "duration_minutes":0,"changeover_minutes":0,"schedule_status":"UNSCHEDULED","reason":"INSUFFICIENT_INVENTORY"})
            continue
        chosen = next(mid for mid in eligible_map[(op.routing_id, int(op.sequence_no))]
                      if (op.operation_id, mid) in machine_choice and solver.Value(machine_choice[(op.operation_id, mid)]))
        st, en = solver.Value(starts[op.operation_id]), solver.Value(ends[op.operation_id])
        rows.append({"operation_id":op.operation_id,"order_id":op.order_id,"machine_id":chosen,
            "start_time":(HORIZON+pd.Timedelta(minutes=st)).isoformat(),
            "end_time":(HORIZON+pd.Timedelta(minutes=en)).isoformat(),
            "duration_minutes":en-st,"changeover_minutes":0,"schedule_status":"SCHEDULED","reason":""})

    
    out = pd.DataFrame(rows)
    
    scheduled = out[out.schedule_status == "SCHEDULED"].copy()


    scheduled = scheduled.merge(
    ops[["operation_id", "setup_family"]],
    on="operation_id",
    how="left"
)

    scheduled["family"] = scheduled["setup_family"]

    for mid, g in scheduled.sort_values("start_time").groupby("machine_id"):
        prev = None
        for idx, row in g.iterrows():
            setup = setup_map.get((prev, row.family), 0) if prev is not None else 0
            out.loc[idx, "changeover_minutes"] = setup
            prev = row.family
    out.insert(0, "schedule_id", [f"SCH-OPT-{i:06d}" for i in range(1, len(out)+1)])
    out.to_csv(d/"operation_schedules.csv", index=False)
    out.to_json(d/"operation_schedules.json", orient="records", indent=2)
    event_rows = []
    for i, row in enumerate(out.itertuples(), 1):
        event_rows.append({"event_id": f"EVT-OPT-{i:07d}", "entity_type": "OperationSchedule",
            "entity_id": row.schedule_id,
            "event_type": "SCHEDULE_CREATED" if row.schedule_status == "SCHEDULED" else "SCHEDULE_REJECTED",
            "event_time": row.start_time if row.start_time else HORIZON.isoformat(),
            "details": f"machine={row.machine_id}; setup={row.changeover_minutes}; reason={row.reason}"})
    events = pd.DataFrame(event_rows)
    events.to_csv(d/"schedule_events.csv", index=False)
    events.to_json(d/"schedule_events.json", orient="records", indent=2)
    finalize_consumption(data_dir)

    report = {
        "solver": "OR-Tools CP-SAT", "status": status_name,
        "optimality_proven": status == cp_model.OPTIMAL,
        "objective_value": solver.ObjectiveValue(), "best_objective_bound": solver.BestObjectiveBound(),
        "absolute_gap": abs(solver.ObjectiveValue()-solver.BestObjectiveBound()),
        "wall_time_seconds": solver.WallTime(), "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts(), "workers": workers,
        "time_limit_seconds": time_limit_seconds,
        "scheduled_operations": int((out.schedule_status == "SCHEDULED").sum()),
        "unscheduled_operations": int((out.schedule_status != "SCHEDULED").sum()),
        "objective_weights": w,
        "model_scope": "finite-horizon, integer-minute CP-SAT model; machine assignment, precedence, shifts, downtime, shared tools, and sequence-dependent setup"
    }
    (d/"optimization_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out, report
