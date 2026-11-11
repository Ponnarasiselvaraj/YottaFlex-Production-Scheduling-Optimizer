from pathlib import Path
import pandas as pd

def validate_all(data_dir="data"):
    d = Path(data_dir)
    issues = []
    def report(code, detail, count=1):
        issues.append({"issue_type": code, "count": int(count), "details": detail})

    # Primary-key uniqueness / null checks.
    primary_keys = {
        "products":"product_id", "machines":"machine_id", "materials":"material_id",
        "tools":"tool_id", "routings":"routing_id", "route_operations":"route_operation_id",
        "machine_calendars":"calendar_id", "inventory_lots":"lot_id",
        "production_orders":"order_id", "operations":"operation_id"
    }
    master_rows = []
    for table, pk in primary_keys.items():
        df = pd.read_csv(d/f"{table}.csv")
        unique = not df[pk].duplicated().any()
        nulls = int(df[pk].isna().sum())
        master_rows.append({"table":table,"rows":len(df),"primary_key":pk,
                            "unique":unique,"null_primary_keys":nulls})
        if not unique: report("DUPLICATE_PRIMARY_KEY", table)
        if nulls: report("NULL_PRIMARY_KEY", table, nulls)

    # Foreign-key integrity.
    fk_checks = [
        ("routings","product_id","products","product_id"),
        ("route_operations","routing_id","routings","routing_id"),
        ("machine_calendars","machine_id","machines","machine_id"),
        ("inventory_lots","material_id","materials","material_id"),
        ("production_orders","product_id","products","product_id"),
        ("production_orders","routing_id","routings","routing_id"),
        ("operations","order_id","production_orders","order_id"),
        ("operations","routing_id","routings","routing_id"),
        ("machine_eligibility","routing_id","routings","routing_id"),
        ("machine_eligibility","machine_id","machines","machine_id"),
        ("material_requirements","order_id","production_orders","order_id"),
        ("material_requirements","material_id","materials","material_id"),
        ("tool_requirements","tool_id","tools","tool_id"),
        ("machine_downtime","machine_id","machines","machine_id")
    ]
    for child, child_col, parent, parent_col in fk_checks:
        c = pd.read_csv(d/f"{child}.csv")
        p = pd.read_csv(d/f"{parent}.csv")
        invalid = ~c[child_col].isin(set(p[parent_col]))
        if invalid.any(): report("FOREIGN_KEY_VIOLATION", f"{child}.{child_col} -> {parent}.{parent_col}", invalid.sum())

    # Allowed values and positive values.
    orders = pd.read_csv(d/"production_orders.csv")
    products = pd.read_csv(d/"products.csv")
    if not set(orders.priority).issubset({"URGENT","HIGH","NORMAL","LOW"}):
        report("INVALID_PRIORITY_ENUM", "production_orders.priority")
    if (orders.quantity <= 0).any(): report("NON_POSITIVE_ORDER_QUANTITY", "production_orders.quantity")
    lots = pd.read_csv(d/"inventory_lots.csv")
    if (lots.quantity < 0).any(): report("NEGATIVE_INVENTORY", "inventory_lots.quantity")

    # Schedule constraints.
    s = pd.read_csv(d/"operation_schedules.csv")
    ops = pd.read_csv(d/"operations.csv")
    cal = pd.read_csv(d/"machine_calendars.csv").set_index("machine_id").to_dict("index")
    downtime = pd.read_csv(d/"machine_downtime.csv")
    valid = s[s.schedule_status == "SCHEDULED"].copy()
    if s.schedule_id.duplicated().any(): report("DUPLICATE_SCHEDULE_ID", "operation_schedules")
    if s.operation_id.duplicated().any(): report("DUPLICATE_OPERATION_SCHEDULE", "operation_schedules")
    missing = set(ops.operation_id)-set(s.operation_id)
    if missing: report("MISSING_OPERATION_SCHEDULE", "operations without schedule", len(missing))

    for r in valid.itertuples():
        st, en = pd.Timestamp(r.start_time), pd.Timestamp(r.end_time)
        if en <= st: report("INVALID_TIME_ORDER", r.schedule_id)
        c = cal[r.machine_id]
        sh, sm = map(int,c["shift_start"].split(":")); eh, em = map(int,c["shift_end"].split(":"))
        lower = st.normalize()+pd.Timedelta(hours=sh,minutes=sm)
        upper = st.normalize()+pd.Timedelta(hours=eh,minutes=em)
        if st.weekday() >= 5 or st < lower or en > upper: report("OUTSIDE_SHIFT", r.schedule_id)
        for dt in downtime[downtime.machine_id == r.machine_id].itertuples():
            if st < pd.Timestamp(dt.end_time) and en > pd.Timestamp(dt.start_time):
                report("MAINTENANCE_OVERLAP", r.schedule_id); break

    for machine_id, group in valid.groupby("machine_id"):
        group = group.sort_values("start_time")
        prior_end = None
        for r in group.itertuples():
            st, en = pd.Timestamp(r.start_time), pd.Timestamp(r.end_time)
            if prior_end is not None and st < prior_end: report("MACHINE_OVERLAP", r.schedule_id)
            prior_end = max(prior_end,en) if prior_end is not None else en

    joined = valid.merge(ops[["operation_id","order_id","sequence_no"]], on=["operation_id","order_id"])
    for order_id, group in joined.groupby("order_id"):
        group = group.sort_values("sequence_no")
        prior_end = None
        for r in group.itertuples():
            if prior_end is not None and pd.Timestamp(r.start_time) < prior_end:
                report("PRECEDENCE_VIOLATION", r.operation_id)
            prior_end = pd.Timestamp(r.end_time)

    # Machine eligibility and material availability at first operation.
    elig = pd.read_csv(d/"machine_eligibility.csv")
    allowed = set(zip(elig.routing_id, elig.sequence_no, elig.machine_id))
    op_lookup = ops.set_index("operation_id").to_dict("index")
    for r in valid.itertuples():
        op = op_lookup[r.operation_id]
        if (op["routing_id"], int(op["sequence_no"]), r.machine_id) not in allowed:
            report("INELIGIBLE_MACHINE", r.operation_id)


    # Inventory ledger reconciliation and availability.
    alloc_path=d/"material_allocations.csv"
    balance_path=d/"inventory_balances.csv"
    if alloc_path.exists() and balance_path.exists():
        allocations=pd.read_csv(alloc_path)
        balances=pd.read_csv(balance_path)
        if not balances.empty and (balances.remaining_quantity < -1e-9).any():
            report("NEGATIVE_INVENTORY_BALANCE","inventory_balances.remaining_quantity")
        if not balances.empty:
            delta=(balances.quantity-balances.allocated_quantity-balances.remaining_quantity).abs()
            if (delta>1e-6).any(): report("INVENTORY_RECONCILIATION_FAILURE","lot quantity != allocated + remaining",int((delta>1e-6).sum()))
        if not allocations.empty:
            bad=allocations[pd.to_datetime(allocations.consumption_time,errors="coerce") <
                            pd.to_datetime(allocations.available_at,errors="coerce")]
            if not bad.empty: report("MATERIAL_CONSUMED_BEFORE_AVAILABLE","material_allocations",len(bad))

    # Shared-tool finite-capacity validation using a sweep-line (end events before start events).
    tool_req_path=d/"tool_requirements.csv"
    if tool_req_path.exists():
        tool_master=pd.read_csv(d/"tools.csv").set_index("tool_id").available_units.to_dict()
        tool_req_df=pd.read_csv(tool_req_path)
        sched_ops=valid.merge(ops[["operation_id","sequence_no"]],on="operation_id")
        reservations=sched_ops.merge(tool_req_df,left_on=["order_id","sequence_no"],
                                     right_on=["order_id","operation_sequence"],how="inner")
        for tool_id,group in reservations.groupby("tool_id"):
            events=[]
            for r in group.itertuples():
                events.append((pd.Timestamp(r.start_time),1,int(r.required_units)))
                events.append((pd.Timestamp(r.end_time),0,-int(r.required_units)))
            active=0; peak=0
            for _,_,delta in sorted(events):
                active+=delta; peak=max(peak,active)
            if peak>int(tool_master[tool_id]):
                report("SHARED_TOOL_CAPACITY_EXCEEDED",f"{tool_id}: peak {peak}, capacity {tool_master[tool_id]}")

    # Sequence-dependent changeover validation against chronological machine transitions.
    change_path=d/"changeover_matrix.csv"
    if change_path.exists():
        change_df=pd.read_csv(change_path)
        change_map={(r.from_family,r.to_family):int(r.changeover_minutes) for r in change_df.itertuples()}
        family_map=products.set_index("product_id").family.to_dict()
        order_product=orders.set_index("order_id").product_id.to_dict()
        op_family=ops.set_index("operation_id").order_id.map(order_product).map(family_map).to_dict()
        for machine_id,group in valid.sort_values("start_time").groupby("machine_id"):
            previous_family=None
            for r in group.itertuples():
                current_family=op_family.get(r.operation_id)
                required=change_map.get((previous_family,current_family),0) if previous_family else 0
                if int(r.changeover_minutes)<required:
                    report("CHANGEOVER_MISSING_OR_SHORT",f"{r.schedule_id}: required {required}, recorded {r.changeover_minutes}")
                previous_family=current_family

    master = pd.DataFrame(master_rows)
    findings = pd.DataFrame(issues, columns=["issue_type","count","details"])
    return master, findings
