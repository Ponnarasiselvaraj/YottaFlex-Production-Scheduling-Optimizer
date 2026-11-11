from pathlib import Path
import pandas as pd

PRIORITY = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}

def allocate_materials(data_dir="data"):
    """
    Reserve material quantities from eligible inventory lots in priority/due-date order.
    Lots are allocated FEFO (earliest availability, then expiry, then lot ID).
    Reservations are not consumed until the order's first operation starts.
    """
    d=Path(data_dir)
    orders=pd.read_csv(d/"production_orders.csv")
    reqs=pd.read_csv(d/"material_requirements.csv")
    lots=pd.read_csv(d/"inventory_lots.csv")
    orders=orders.assign(_rank=orders.priority.map(PRIORITY)).sort_values(
        ["_rank","due_date","order_id"])
    remaining={r.lot_id:float(r.quantity) for r in lots.itertuples()}
    lot_lookup=lots.set_index("lot_id").to_dict("index")
    allocations=[]
    order_ready={}
    shortages=[]
    for order in orders.itertuples():
        ready_dates=[]
        for req in reqs[reqs.order_id==order.order_id].itertuples():
            candidates=lots[lots.material_id==req.material_id].copy()
            candidates["available_at"]=pd.to_datetime(candidates.available_at)
            candidates["expiry_date"]=pd.to_datetime(candidates.expiry_date)
            candidates=candidates[candidates.apply(
                lambda x: remaining[x.lot_id] > 0 and x.expiry_date >= x.available_at,axis=1)]
            candidates=candidates.sort_values(["available_at","expiry_date","lot_id"])
            needed=float(req.required_quantity)
            for lot in candidates.itertuples():
                if needed<=0: break
                take=min(needed,remaining[lot.lot_id])
                if take<=0: continue
                remaining[lot.lot_id]-=take
                needed-=take
                ready_dates.append(pd.Timestamp(lot.available_at))
                allocations.append({
                    "allocation_id":f"ALLOC-{len(allocations)+1:07d}",
                    "order_id":order.order_id,"material_id":req.material_id,
                    "lot_id":lot.lot_id,"allocated_quantity":take,
                    "available_at":lot.available_at,"consumption_time":"",
                    "allocation_status":"RESERVED"
                })
            if needed>0:
                shortages.append({"order_id":order.order_id,"material_id":req.material_id,
                                  "shortage_quantity":needed,"issue_type":"INSUFFICIENT_INVENTORY"})
        order_ready[order.order_id]=max(ready_dates) if ready_dates else pd.Timestamp("2026-11-16 08:00")
        if any(x["order_id"]==order.order_id for x in shortages):
            order_ready[order.order_id]=pd.Timestamp.max
    alloc_df=pd.DataFrame(allocations,columns=[
        "allocation_id","order_id","material_id","lot_id","allocated_quantity",
        "available_at","consumption_time","allocation_status"])
    short_df=pd.DataFrame(shortages,columns=["order_id","material_id","shortage_quantity","issue_type"])
    balances=lots[["lot_id","material_id","quantity","available_at","expiry_date"]].copy()
    balances["allocated_quantity"]=balances.lot_id.map(
        alloc_df.groupby("lot_id").allocated_quantity.sum() if not alloc_df.empty else {})
    balances["allocated_quantity"]=balances["allocated_quantity"].fillna(0)
    balances["remaining_quantity"]=balances.quantity-balances.allocated_quantity
    alloc_df.to_csv(d/"material_allocations.csv",index=False)
    alloc_df.to_json(d/"material_allocations.json",orient="records",indent=2)
    balances.to_csv(d/"inventory_balances.csv",index=False)
    balances.to_json(d/"inventory_balances.json",orient="records",indent=2)
    short_df.to_csv(d/"inventory_shortages.csv",index=False)
    return order_ready,alloc_df,balances,short_df

def finalize_consumption(data_dir="data"):
    """Mark reservations consumed at each order's first scheduled operation start."""
    d=Path(data_dir)
    alloc_path=d/"material_allocations.csv"
    schedule=pd.read_csv(d/"operation_schedules.csv")
    allocations=pd.read_csv(alloc_path)
    if allocations.empty:
        return allocations
    first=schedule[schedule.schedule_status=="SCHEDULED"].groupby("order_id").start_time.min().to_dict()
    allocations["consumption_time"]=allocations.order_id.map(first).fillna("")
    allocations["allocation_status"]=allocations.consumption_time.map(
        lambda x:"CONSUMED" if x else "RESERVED")
    allocations.to_csv(alloc_path,index=False)
    allocations.to_json(d/"material_allocations.json",orient="records",indent=2)
    return allocations
