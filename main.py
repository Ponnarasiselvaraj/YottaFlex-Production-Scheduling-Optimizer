import argparse,json
from pathlib import Path
from src.generator import generate_dataset
from src.scheduler import schedule_operations
from src.global_optimizer import solve_global
from src.anomalies import generate_labelled_anomalies
from src.validation import validate_all
from src.metrics import calculate_metrics
from src.database import export_sqlite
from src.reproducibility import verify_reproducibility
from src.constraint_engine import detect_constraints
from src.inventory import allocate_materials

def main():
    parser=argparse.ArgumentParser(description="YottaFlex Production Scheduling System")
    parser.add_argument("--scale",choices=["starter","full"],default="starter")
    parser.add_argument("--seed",type=int,default=20261022)
    parser.add_argument("--data-dir",default="data")
    parser.add_argument("--skip-repro",action="store_true")
    parser.add_argument("--solver",choices=["heuristic","global"],default="heuristic",help="Use heuristic scheduler or exact CP-SAT optimizer")
    parser.add_argument("--solver-time-limit",type=float,default=None,help="CP-SAT time limit in seconds")
    args=parser.parse_args()
    out=Path(args.data_dir); out.mkdir(parents=True,exist_ok=True)
    print("\\n=== YottaFlex Production Scheduler ===")
    print("[1/9] Generating master and transaction data...")
    generate_dataset(args.data_dir,args.scale,args.seed)
    print("[2/9] Allocating inventory lots (FEFO, priority-aware)...")
    allocate_materials(args.data_dir)
    print("[3/9] Scheduling with machine, shift, downtime, changeover and tool constraints...")
    if args.solver == "global":
        _, optimization_report = solve_global(args.data_dir, time_limit_seconds=args.solver_time_limit)
        print("Global optimization:", json.dumps(optimization_report, indent=2))
    else:
        schedule_operations(args.data_dir)
    print("[4/9] Generating five isolated labelled anomaly fixtures...")
    generate_labelled_anomalies(args.data_dir)
    print("[5/9] Running independent constraint detection (ground truth hidden from detector)...")
    detections,detection_metrics=detect_constraints(args.data_dir)
    print(json.dumps(detection_metrics,indent=2))
    print("[6/9] Validating keys, joins, calendars and precedence...")
    master,findings=validate_all(args.data_dir)
    master.to_csv(out/"master_validation.csv",index=False)
    findings.to_csv(out/"validation_summary.csv",index=False)
    print("[7/9] Calculating KPIs and inventory reconciliation...")
    metrics=calculate_metrics(args.data_dir)
    metrics["constraint_detection"]=detection_metrics
    (out/"metrics.json").write_text(json.dumps(metrics,indent=2))
    print("[8/9] Exporting SQLite database...")
    db=export_sqlite(args.data_dir)
    if not args.skip_repro:
        print("[9/9] Reproducibility:",verify_reproducibility(args.seed,args.scale)["identical"])
    print("\\n--- RUN SUMMARY ---")
    print(json.dumps(metrics,indent=2))
    print("Master tables:",len(master),"| Validation findings:",len(findings))
    print("SQLite database:",db)
    print("Output folder:",out.resolve())

if __name__=="__main__":
    main()
