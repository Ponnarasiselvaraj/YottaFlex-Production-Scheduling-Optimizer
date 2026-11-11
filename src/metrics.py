from pathlib import Path
import json
import pandas as pd
from .objective import load_objective_config, objective_components

def calculate_metrics(data_dir="data"):
    d=Path(data_dir)
    s=pd.read_csv(d/"operation_schedules.csv")
    orders=pd.read_csv(d/"production_orders.csv")
    valid=s[s.schedule_status=="SCHEDULED"].copy()
    if valid.empty:
        return {"total_orders":len(orders),"scheduled_operations":0,"unscheduled_operations":len(s)}
    valid["start_time"]=pd.to_datetime(valid.start_time)
    valid["end_time"]=pd.to_datetime(valid.end_time)
    completion=valid.groupby("order_id").end_time.max().rename("completion")
    merged=orders.merge(completion,left_on="order_id",right_index=True,how="left")
    merged["due_date"]=pd.to_datetime(merged.due_date)
    tardy=((merged.completion-merged.due_date).dt.total_seconds()/3600).clip(lower=0).fillna(0)
    balances=pd.read_csv(d/"inventory_balances.csv") if (d/"inventory_balances.csv").exists() else pd.DataFrame()
    allocations=pd.read_csv(d/"material_allocations.csv") if (d/"material_allocations.csv").exists() else pd.DataFrame()
    tools=pd.read_csv(d/"tools.csv") if (d/"tools.csv").exists() else pd.DataFrame()
    objective_summary=objective_components(s,orders,load_objective_config())
    baseline_comparison={}
    baseline_path=d.parent/"config"/"baseline_benchmark_full.json"
    if len(orders)==500 and baseline_path.exists():
        baseline=json.loads(baseline_path.read_text(encoding="utf-8"))
        def pct_change(current,previous):
            return round((current-previous)/previous*100,2) if previous else None
        baseline_comparison={
            "baseline_scheduler":baseline["scheduler"],
            "baseline_objective_score":baseline["objective_score"],
            "optimized_objective_score":objective_summary["objective_score"],
            "objective_score_change_pct":pct_change(objective_summary["objective_score"],baseline["objective_score"]),
            "makespan_change_pct":pct_change(objective_summary["makespan_hours"],baseline["makespan_hours"]),
            "weighted_tardiness_change_pct":pct_change(objective_summary["weighted_tardiness_hours"],baseline["weighted_tardiness_hours"]),
            "changeover_change_pct":pct_change(objective_summary["changeover_minutes"],baseline["changeover_minutes"]),
            "baseline_on_time_delivery_pct":baseline["on_time_delivery_pct"],
            "optimized_on_time_delivery_pct":round(float(((merged.completion.notna())&(tardy==0)).mean()*100),2)
        }
    return {
        "baseline_comparison":baseline_comparison,
        "total_orders":int(len(orders)),
        "optimization_objective":objective_summary,
        "scheduled_operations":int(len(valid)),
        "unscheduled_operations":int(len(s)-len(valid)),
        "makespan_hours":round(float((valid.end_time.max()-valid.start_time.min()).total_seconds()/3600),2),
        "total_tardiness_hours":round(float(tardy.sum()),2),
        "on_time_delivery_pct":round(float(((merged.completion.notna())&(tardy==0)).mean()*100),2),
        "changeover_minutes":int(valid.changeover_minutes.sum()),
        "machines_used":int(valid.machine_id.nunique()),
        "schedule_feasibility_pct":round(float(len(valid)/len(s)*100),2) if len(s) else 100.0,
        "material_allocations":int(len(allocations)),
        "material_consumed_quantity":round(float(allocations.allocated_quantity.sum()),2) if not allocations.empty else 0,
        "inventory_remaining_quantity":round(float(balances.remaining_quantity.sum()),2) if not balances.empty else 0,
        "tool_types":int(tools.tool_id.nunique()) if not tools.empty else 0
    }
