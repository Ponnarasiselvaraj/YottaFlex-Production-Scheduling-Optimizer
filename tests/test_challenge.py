import pandas as pd
from src.generator import generate_dataset
from src.scheduler import schedule_operations
from src.validation import validate_all
from src.anomalies import generate_labelled_anomalies
from src.reproducibility import verify_reproducibility
from src.constraint_engine import detect_constraints
from src.inventory import allocate_materials

def build(tmp_path):
    generate_dataset(tmp_path,"starter",20261022)
    allocate_materials(tmp_path)
    schedule_operations(tmp_path)
    generate_labelled_anomalies(tmp_path)

def test_starter_generation_and_schedule(tmp_path):
    build(tmp_path)
    schedules=pd.read_csv(tmp_path/"operation_schedules.csv")
    events=pd.read_csv(tmp_path/"schedule_events.csv")
    assert len(schedules)==80
    assert schedules.schedule_id.is_unique
    assert len(events)==80

def test_primary_keys_and_joins(tmp_path):
    build(tmp_path)
    master,findings=validate_all(tmp_path)
    assert master["unique"].all()
    assert (master.null_primary_keys==0).all()

def test_five_ground_truth_scenarios(tmp_path):
    build(tmp_path)
    anomalies,truth=generate_labelled_anomalies(tmp_path)
    assert len(truth)==5
    assert set(truth.issue_type)=={"OVERLAP_ON_MACHINE","PRECEDENCE_VIOLATION",
        "MATERIAL_BEFORE_AVAILABLE","OUTSIDE_SHIFT","CHANGEOVER_OMITTED"}

def test_fixed_seed_reproducibility(tmp_path):
    result=verify_reproducibility(20261022,"starter",tmp_path/"repro")
    assert result["identical"] is True

def test_detector_finds_all_five_without_reading_truth(tmp_path):
    build(tmp_path)
    result,metrics=detect_constraints(tmp_path)
    assert len(result)==5
    assert result.detected.all()
    assert metrics["recall"]==1.0

def test_inventory_reconciles_and_no_negative_balance(tmp_path):
    build(tmp_path)
    allocations=pd.read_csv(tmp_path/"material_allocations.csv")
    balances=pd.read_csv(tmp_path/"inventory_balances.csv")
    assert (balances.remaining_quantity>=0).all()
    assert abs(balances.quantity.sum()-balances.allocated_quantity.sum()-balances.remaining_quantity.sum())<1e-6
    assert set(allocations.allocation_status).issubset({"CONSUMED","RESERVED"})

def test_tool_capacity_never_exceeded_in_schedule(tmp_path):
    build(tmp_path)
    tools=pd.read_csv(tmp_path/"tools.csv").set_index("tool_id").available_units.to_dict()
    req=pd.read_csv(tmp_path/"tool_requirements.csv")
    ops=pd.read_csv(tmp_path/"operations.csv")
    sch=pd.read_csv(tmp_path/"operation_schedules.csv")
    x=sch[sch.schedule_status=="SCHEDULED"].merge(ops[["operation_id","sequence_no"]],on="operation_id")
    x=x.merge(req,left_on=["order_id","sequence_no"],right_on=["order_id","operation_sequence"],how="inner")
    for tool_id,g in x.groupby("tool_id"):
        intervals=[(pd.Timestamp(r.start_time),pd.Timestamp(r.end_time),int(r.required_units)) for r in g.itertuples()]
        events=[]
        for start,end,units in intervals:
            events.append((start,1,units))
            events.append((end,0,-units))  # process releases before acquisitions at same instant
        active=0
        peak=0
        for _,kind,delta in sorted(events):
            active+=delta
            peak=max(peak,active)
        assert peak<=int(tools[tool_id])


def test_multiobjective_config_weights_are_normalized(tmp_path):
    from src.objective import load_objective_config
    cfg=load_objective_config()
    assert abs(sum(cfg["weights"].values())-1.0)<1e-9
    assert set(cfg["weights"])=={"makespan","weighted_tardiness","changeover"}

def test_multiobjective_metrics_are_emitted(tmp_path):
    from src.metrics import calculate_metrics
    build(tmp_path)
    metrics=calculate_metrics(tmp_path)
    obj=metrics["optimization_objective"]
    assert obj["objective_score"]>=0
    assert obj["makespan_hours"]>0
    assert obj["changeover_minutes"]>=0
    assert obj["weighted_tardiness_hours"]>=0
