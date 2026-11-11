from pathlib import Path
import json
import pandas as pd
from .inventory import allocate_materials, finalize_consumption
from .objective import load_objective_config

HORIZON=pd.Timestamp("2026-11-16 08:00:00")

def next_shift(t,start="08:00",end="16:00"):
    t=pd.Timestamp(t); sh,sm=map(int,start.split(":")); eh,em=map(int,end.split(":"))
    ds=t.normalize()+pd.Timedelta(hours=sh,minutes=sm)
    de=t.normalize()+pd.Timedelta(hours=eh,minutes=em)
    if t.weekday()>=5:
        t=t.normalize()+pd.Timedelta(days=7-t.weekday())
        return t+pd.Timedelta(hours=sh,minutes=sm)
    if t<ds: return ds
    if t>=de:
        t=t.normalize()+pd.Timedelta(days=1)
        while t.weekday()>=5: t+=pd.Timedelta(days=1)
        return t+pd.Timedelta(hours=sh,minutes=sm)
    return t

def in_shift(st,dur,start="08:00",end="16:00"):
    st=pd.Timestamp(st); en=st+pd.Timedelta(minutes=dur)
    sh,sm=map(int,start.split(":")); eh,em=map(int,end.split(":"))
    return st.weekday()<5 and st>=st.normalize()+pd.Timedelta(hours=sh,minutes=sm) and en<=st.normalize()+pd.Timedelta(hours=eh,minutes=em)

def schedule_operations(data_dir="data"):
    """
    Four-stage finite-resource scheduler using a configurable weighted objective:
    makespan + priority-weighted tardiness + sequence-dependent changeover.
    Hard constraints remain precedence, shifts, downtime, material readiness,
    machine eligibility and shared-tool capacity.
    """
    d=Path(data_dir); read=lambda n:pd.read_csv(d/f"{n}.csv")
    orders,ops,machines,cal=read("production_orders"),read("operations"),read("machines"),read("machine_calendars")
    elig,down,change=read("machine_eligibility"),read("machine_downtime"),read("changeover_matrix")
    products,tools,tool_reqs=read("products"),read("tools"),read("tool_requirements")
    order_ready,_,_,_=allocate_materials(data_dir)
    objective=load_objective_config()
    weights=objective["weights"]
    norm=objective["normalization"]
    tardy_weights=objective["priority_tardiness_weights"]
    family_map=dict(zip(products.product_id,products.family))
    machine_map=machines.set_index("machine_id").to_dict("index")
    calmap=cal.set_index("machine_id").to_dict("index")
    eligible=elig.groupby(["routing_id","sequence_no"]).machine_id.apply(list).to_dict()
    change_map={(r.from_family,r.to_family):int(r.changeover_minutes) for r in change.itertuples()}
    tool_capacity=tools.set_index("tool_id").available_units.astype(int).to_dict()
    tool_req={(r.order_id,int(r.operation_sequence)):(r.tool_id,int(r.required_units)) for r in tool_reqs.itertuples()}
    downmap={}
    for r in down.itertuples(): downmap.setdefault(r.machine_id,[]).append((pd.Timestamp(r.start_time),pd.Timestamp(r.end_time)))
    machine_free={m:HORIZON for m in machines.machine_id}
    machine_last={m:None for m in machines.machine_id}
    tool_bookings={t:[] for t in tool_capacity}
    order_end={oid:order_ready.get(oid,HORIZON) for oid in orders.order_id}
    priority={"URGENT":0,"HIGH":1,"NORMAL":2,"LOW":3}
    # Estimate downstream work so dispatch order considers the whole order,
    # not only the operation currently being scheduled.
    mean_capacity=float(machines.capacity_units_per_hour.mean())
    order_work={oid:float((g.duration_minutes*order_qty/max(mean_capacity,1)).sum())
                for oid,g in ops.merge(orders[["order_id","quantity"]],on="order_id").groupby("order_id")
                for order_qty in [g.quantity.iloc[0]]}
    sorted_orders=orders.assign(_rank=orders.priority.map(priority)).sort_values(
        ["_rank","due_date","order_id"])
    result=[]; counter=1

    for order in sorted_orders.itertuples():
        if order_end[order.order_id]==pd.Timestamp.max:
            for op in ops[ops.order_id==order.order_id].sort_values("sequence_no").itertuples():
                result.append({"schedule_id":f"SCH-2026-{counter:06d}","operation_id":op.operation_id,
                    "order_id":order.order_id,"machine_id":"","start_time":"","end_time":"",
                    "duration_minutes":0,"changeover_minutes":0,"schedule_status":"UNSCHEDULED",
                    "reason":"INSUFFICIENT_INVENTORY"})
                counter+=1

    blocked_orders={o for o,v in order_end.items() if v==pd.Timestamp.max}
    for seq in range(1,5):
        stage_ops=ops[ops.sequence_no==seq].merge(
            orders[["order_id","product_id","priority","due_date","quantity"]],on="order_id")
        stage_ops["_rank"]=stage_ops.priority.map(priority)
        stage_ops["_priority_weight"]=stage_ops.priority.map(tardy_weights).fillna(1.0)
        # Keep deterministic priority / due-date dispatch; the weighted objective
        # decides among feasible machine assignments without destabilizing the queue.
        stage_ops=stage_ops.sort_values(["_rank","due_date","order_id"])
        for op in stage_ops.itertuples():
            oid=op.order_id
            if oid in blocked_orders: continue
            family=family_map[op.product_id]
            tid,tunits=tool_req.get((oid,seq),("",0))
            best=None
            for mid in eligible.get((op.routing_id,seq),[]):
                c=calmap[mid]
                setup=change_map.get((machine_last[mid],family),0) if machine_last[mid] else 0
                duration=max(20,int(int(op.duration_minutes)*int(op.quantity)/max(1,int(machine_map[mid]["capacity_units_per_hour"]))))
                st=next_shift(max(machine_free[mid],order_end[oid])+pd.Timedelta(minutes=setup),
                              c["shift_start"],c["shift_end"])
                for _ in range(200):
                    if not in_shift(st,duration,c["shift_start"],c["shift_end"]):
                        st=next_shift(st+pd.Timedelta(days=1),c["shift_start"],c["shift_end"]); continue
                    en=st+pd.Timedelta(minutes=duration)
                    hit=next(((a,b) for a,b in downmap.get(mid,[]) if st<b and en>a),None)
                    if hit:
                        st=next_shift(hit[1],c["shift_start"],c["shift_end"]); continue
                    if tid:
                        overlaps=[(a,b,u) for a,b,u in tool_bookings[tid] if st<b and en>a]
                        if sum(u for _,_,u in overlaps)+tunits>tool_capacity.get(tid,1):
                            st=next_shift(min(b for _,b,_ in overlaps),c["shift_start"],c["shift_end"]); continue
                    break
                else: continue
                # Project final order completion by adding estimated downstream work.
                remaining_minutes=max(0.0,order_work.get(oid,0.0)-
                    sum(float(x.duration_minutes)*float(op.quantity)/max(mean_capacity,1)
                        for x in ops[(ops.order_id==oid)&(ops.sequence_no<=seq)].itertuples()))
                projected_completion=en+pd.Timedelta(minutes=remaining_minutes)
                due=pd.Timestamp(op.due_date)
                projected_tardy=max(0.0,(projected_completion-due).total_seconds()/3600)
                priority_weight=float(tardy_weights.get(op.priority,1.0))
                makespan_component=max(0.0,(en-HORIZON).total_seconds()/3600)/float(norm["makespan_hours"])
                tardy_component=(projected_tardy*priority_weight)/float(norm["weighted_tardiness_hours"])
                changeover_component=setup/float(norm["changeover_minutes"])
                score=(weights["makespan"]*makespan_component+
                       weights["weighted_tardiness"]*tardy_component+
                       weights["changeover"]*changeover_component,
                       en,setup,st,mid)
                if best is None or score<best[0]: best=(score,st,mid,en,setup,duration)
            if best is None:
                result.append({"schedule_id":f"SCH-2026-{counter:06d}","operation_id":op.operation_id,
                    "order_id":oid,"machine_id":"","start_time":"","end_time":"","duration_minutes":0,
                    "changeover_minutes":0,"schedule_status":"UNSCHEDULED","reason":"NO_FEASIBLE_MACHINE_OR_RESOURCE_SLOT"})
            else:
                _,st,mid,en,setup,duration=best
                result.append({"schedule_id":f"SCH-2026-{counter:06d}","operation_id":op.operation_id,
                    "order_id":oid,"machine_id":mid,"start_time":st.isoformat(),"end_time":en.isoformat(),
                    "duration_minutes":duration,"changeover_minutes":setup,
                    "schedule_status":"SCHEDULED","reason":""})
                machine_free[mid]=en; machine_last[mid]=family; order_end[oid]=en
                if tid: tool_bookings[tid].append((st,en,tunits))
            counter+=1

    df=pd.DataFrame(result).sort_values("schedule_id")
    (d/"applied_objective_config.json").write_text(json.dumps(objective,indent=2),encoding="utf-8")
    df.to_csv(d/"operation_schedules.csv",index=False); df.to_json(d/"operation_schedules.json",orient="records",indent=2)
    event_rows=[]
    for i,row in enumerate(df.itertuples(),1):
        event_rows.append({"event_id":f"EVT-{i:07d}","entity_type":"OperationSchedule","entity_id":row.schedule_id,
            "event_type":"SCHEDULE_CREATED" if row.schedule_status=="SCHEDULED" else "SCHEDULE_REJECTED",
            "event_time":row.start_time if row.start_time else HORIZON.isoformat(),
            "details":f"machine={row.machine_id}; setup={row.changeover_minutes}; reason={row.reason}"})
    events=pd.DataFrame(event_rows)
    events.to_csv(d/"schedule_events.csv",index=False); events.to_json(d/"schedule_events.json",orient="records",indent=2)
    finalize_consumption(data_dir)
    return df,events
