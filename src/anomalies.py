from pathlib import Path
import pandas as pd

def generate_labelled_anomalies(data_dir="data"):
    """Build five independent anomaly fixtures; ground truth is kept in a separate file."""
    d=Path(data_dir)
    s=pd.read_csv(d/"operation_schedules.csv")
    ops=pd.read_csv(d/"operations.csv")
    cal=pd.read_csv(d/"machine_calendars.csv").set_index("machine_id").to_dict("index")
    lots=pd.read_csv(d/"inventory_lots.csv")
    change=pd.read_csv(d/"changeover_matrix.csv")
    valid=s[s.schedule_status=="SCHEDULED"].copy()
    if valid.empty: return pd.DataFrame(),pd.DataFrame()
    rows=[]; truth=[]
    def add(issue,desc,**fields):
        sid=f"ANOM-{len(rows)+1:03d}"
        rows.append({"scenario_id":sid,"issue_type":issue,"description":desc,**fields})
        truth.append({"scenario_id":sid,"issue_type":issue,"ground_truth_label":1,
                      "expected_detection":True,"description":desc})

    # 1) Overlap: make a second interval that overlaps the selected scheduled interval.
    base=valid.iloc[0]
    conflict_start=pd.Timestamp(base.start_time)+pd.Timedelta(minutes=5)
    conflict_end=pd.Timestamp(base.end_time)+pd.Timedelta(minutes=5)
    add("OVERLAP_ON_MACHINE","Two operations overlap on the same machine.",
        machine_id=base.machine_id, start_time=conflict_start.isoformat(),
        end_time=conflict_end.isoformat(), conflict_start=base.start_time,
        conflict_end=base.end_time, conflicting_schedule_id=base.schedule_id)

    # 2) Precedence: select a scheduled sequence > 1 and move its start before predecessor end.
    joined=valid.merge(ops[["operation_id","order_id","sequence_no"]],on=["operation_id","order_id"])
    later=joined[joined.sequence_no>1]
    if later.empty: raise RuntimeError("Cannot create precedence anomaly: no later operation")
    selected=later.sort_values(["order_id","sequence_no"]).iloc[0]
    pred=joined[(joined.order_id==selected.order_id)&
                (joined.sequence_no==selected.sequence_no-1)].iloc[0]
    bad_start=pd.Timestamp(pred.end_time)-pd.Timedelta(minutes=10)
    add("PRECEDENCE_VIOLATION","Operation starts before its predecessor finishes.",
        order_id=selected.order_id, operation_id=selected.operation_id,
        predecessor_operation_id=pred.operation_id, predecessor_end_time=pred.end_time,
        start_time=bad_start.isoformat(), end_time=(bad_start+pd.Timedelta(minutes=int(selected.duration_minutes))).isoformat())

    # 3) Material consumption before lot availability.
    lot=lots.iloc[0]
    consumption=pd.Timestamp(lot.available_at)-pd.Timedelta(days=1)
    add("MATERIAL_BEFORE_AVAILABLE","Material consumption precedes inventory lot availability.",
        order_id=valid.iloc[0].order_id,material_id=lot.material_id,lot_id=lot.lot_id,
        material_available_at=lot.available_at,material_consumption_time=consumption.isoformat())

    # 4) Outside shift: explicit calendar is carried with the fixture.
    c=cal[base.machine_id]
    day=pd.Timestamp(base.start_time).normalize()
    outside=day+pd.Timedelta(hours=2)
    add("OUTSIDE_SHIFT","Operation is deliberately placed outside the machine shift.",
        machine_id=base.machine_id,start_time=outside.isoformat(),
        end_time=(outside+pd.Timedelta(minutes=int(base.duration_minutes))).isoformat(),
        shift_start=c["shift_start"],shift_end=c["shift_end"],working_days=c["working_days"])

    # 5) Changeover omitted: provide actual family transition and expected matrix value.
    # Find two adjacent operations on the same machine with different setup families.
    ops_family=ops.set_index("operation_id").setup_family.to_dict()
    candidates=[]
    for mid,g in valid.groupby("machine_id"):
        g=g.sort_values("start_time")
        prev=None
        for r in g.itertuples():
            family=ops_family.get(r.operation_id,"")
            if prev is not None and prev[2]!=family:
                required=change[(change.from_family==prev[2])&(change.to_family==family)]
                if not required.empty and int(required.iloc[0].changeover_minutes)>0:
                    candidates.append((mid,prev,r,family,int(required.iloc[0].changeover_minutes)))
            prev=(r.schedule_id,r.end_time,family)
    if candidates:
        mid,prev,current,family,required=candidates[0]
        observed=0
        from_family=prev[2]
        operation_id=current.operation_id
    else:
        # Fallback fixture still tests a valid directed matrix transition.
        families=sorted(change.from_family.unique())
        pair=change[(change.from_family!=change.to_family)&(change.changeover_minutes>0)].iloc[0]
        mid=base.machine_id; from_family=pair.from_family; family=pair.to_family
        required=int(pair.changeover_minutes); observed=0; operation_id=base.operation_id
    add("CHANGEOVER_OMITTED","A family transition has less setup time than required by the matrix.",
        machine_id=mid,operation_id=operation_id,from_family=from_family,to_family=family,
        expected_changeover_minutes=required,observed_changeover_minutes=observed)
    a=pd.DataFrame(rows); g=pd.DataFrame(truth)
    a.to_csv(d/"anomaly_scenarios.csv",index=False); a.to_json(d/"anomaly_scenarios.json",orient="records",indent=2)
    g.to_csv(d/"ground_truth.csv",index=False); g.to_json(d/"ground_truth.json",orient="records",indent=2)
    return a,g
