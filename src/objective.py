from pathlib import Path
import json
import pandas as pd

DEFAULT_CONFIG={
    "weights":{"makespan":0.35,"weighted_tardiness":0.50,"changeover":0.15},
    "normalization":{"makespan_hours":5000.0,"weighted_tardiness_hours":20000.0,"changeover_minutes":50000.0},
    "priority_tardiness_weights":{"URGENT":4.0,"HIGH":3.0,"NORMAL":2.0,"LOW":1.0}
}

def load_objective_config(config_path="config/scheduling_objective.json"):
    path=Path(config_path)
    config=json.loads(path.read_text(encoding="utf-8")) if path.exists() else DEFAULT_CONFIG.copy()
    weights=config.get("weights",{})
    keys=("makespan","weighted_tardiness","changeover")
    if any(float(weights.get(k,0))<0 for k in keys):
        raise ValueError("Objective weights must be non-negative.")
    total=sum(float(weights.get(k,0)) for k in keys)
    if total<=0:
        raise ValueError("At least one objective weight must be positive.")
    config["weights"]={k:float(weights.get(k,0))/total for k in keys}
    for k,v in DEFAULT_CONFIG["normalization"].items():
        config.setdefault("normalization",{}).setdefault(k,v)
    config.setdefault("priority_tardiness_weights",DEFAULT_CONFIG["priority_tardiness_weights"])
    return config

def objective_components(schedule, orders, config=None):
    """Return normalized multi-objective components and weighted objective score."""
    config=config or load_objective_config()
    valid=schedule[schedule.schedule_status=="SCHEDULED"].copy()
    if valid.empty:
        return {"makespan_hours":0.0,"weighted_tardiness_hours":0.0,
                "changeover_minutes":0,"objective_score":0.0,
                "objective_weights":config["weights"]}
    valid["start_time"]=pd.to_datetime(valid.start_time)
    valid["end_time"]=pd.to_datetime(valid.end_time)
    horizon=valid.start_time.min()
    makespan=max(0.0,(valid.end_time.max()-horizon).total_seconds()/3600)
    completion=valid.groupby("order_id").end_time.max()
    data=orders.copy()
    data["due_date"]=pd.to_datetime(data.due_date)
    data["completion"]=data.order_id.map(completion)
    data["tardiness_hours"]=((data.completion-data.due_date).dt.total_seconds()/3600).clip(lower=0).fillna(0)
    pweights=config["priority_tardiness_weights"]
    data["priority_weight"]=data.priority.map(pweights).fillna(1.0)
    weighted_tardiness=float((data.tardiness_hours*data.priority_weight).sum())
    changeovers=int(valid.changeover_minutes.sum())
    norm=config["normalization"]; weights=config["weights"]
    components={
        "makespan":makespan/float(norm["makespan_hours"]),
        "weighted_tardiness":weighted_tardiness/float(norm["weighted_tardiness_hours"]),
        "changeover":changeovers/float(norm["changeover_minutes"])
    }
    score=sum(weights[k]*components[k] for k in weights)
    return {
        "makespan_hours":round(makespan,2),
        "weighted_tardiness_hours":round(weighted_tardiness,2),
        "changeover_minutes":changeovers,
        "normalized_components":{k:round(v,6) for k,v in components.items()},
        "objective_weights":weights,
        "objective_score":round(score,6)
    }
