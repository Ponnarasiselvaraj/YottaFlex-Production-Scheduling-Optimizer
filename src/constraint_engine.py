from pathlib import Path
import json
import pandas as pd

def detect_constraints(data_dir="data"):
    """
    Independent feature/rule-based detector. It does not read ground_truth or the
    anomaly issue_type label. Rules are selected only by the evidence fields
    available in each scenario and evaluate timestamps/resource constraints.
    """
    d=Path(data_dir)
    cases=pd.read_csv(d/"anomaly_scenarios.csv").fillna("")
    detected=[]
    for row in cases.to_dict("records"):
        hits=[]
        evidence=[]
        # Rule 1: same-machine interval overlap.
        if all(row.get(k,"")!="" for k in ["machine_id","start_time","end_time","conflict_start","conflict_end"]):
            a,b=pd.Timestamp(row["start_time"]),pd.Timestamp(row["end_time"])
            x,y=pd.Timestamp(row["conflict_start"]),pd.Timestamp(row["conflict_end"])
            if a<y and b>x:
                hits.append("OVERLAP_ON_MACHINE")
                evidence.append(f"Intervals [{a}, {b}) and [{x}, {y}) overlap on {row['machine_id']}")
        # Rule 2: operation precedence.
        if row.get("predecessor_end_time","")!="" and row.get("start_time","")!="":
            st=pd.Timestamp(row["start_time"]); pred_end=pd.Timestamp(row["predecessor_end_time"])
            if st<pred_end:
                hits.append("PRECEDENCE_VIOLATION")
                evidence.append(f"Operation starts {st} before predecessor ends {pred_end}")
        # Rule 3: material lot availability.
        if row.get("material_consumption_time","")!="" and row.get("material_available_at","")!="":
            consume=pd.Timestamp(row["material_consumption_time"])
            available=pd.Timestamp(row["material_available_at"])
            if consume<available:
                hits.append("MATERIAL_BEFORE_AVAILABLE")
                evidence.append(f"Consumption {consume} precedes lot availability {available}")
        # Rule 4: machine calendar.
        if all(row.get(k,"")!="" for k in ["start_time","end_time","shift_start","shift_end"]):
            st,en=pd.Timestamp(row["start_time"]),pd.Timestamp(row["end_time"])
            sh,sm=map(int,row["shift_start"].split(":")); eh,em=map(int,row["shift_end"].split(":"))
            lo=st.normalize()+pd.Timedelta(hours=sh,minutes=sm)
            hi=st.normalize()+pd.Timedelta(hours=eh,minutes=em)
            working=row.get("working_days","0,1,2,3,4")
            allowed_days={int(x) for x in str(working).split(",") if x.strip()!=""}
            if st.weekday() not in allowed_days or st<lo or en>hi:
                hits.append("OUTSIDE_SHIFT")
                evidence.append(f"Interval {st} to {en} violates shift {row['shift_start']}-{row['shift_end']}")
        # Rule 5: directed family changeover matrix.
        if row.get("expected_changeover_minutes","")!="" and row.get("observed_changeover_minutes","")!="":
            required=int(float(row["expected_changeover_minutes"]))
            observed=int(float(row["observed_changeover_minutes"]))
            if required>0 and observed<required:
                hits.append("CHANGEOVER_OMITTED")
                evidence.append(f"Recorded setup {observed}m is below required {required}m")
        detected.append({
            "scenario_id":row["scenario_id"],
            "detected_issue_type":";".join(hits),
            "detected":bool(hits),
            "detector_rule":"|".join(hits),
            "evidence":" | ".join(evidence)
        })
    result=pd.DataFrame(detected)
    result.to_csv(d/"constraint_detection_results.csv",index=False)
    result.to_json(d/"constraint_detection_results.json",orient="records",indent=2)
    # Ground truth is accessed only after predictions have been persisted, for scoring.
    truth=pd.read_csv(d/"ground_truth.csv")
    evaluation=result.merge(truth[["scenario_id","issue_type","ground_truth_label"]],
                            on="scenario_id",how="left")
    evaluation["correct_issue_type"]=evaluation.apply(
        lambda r:r.issue_type in str(r.detected_issue_type).split(";"),axis=1)
    tp=int(((evaluation.detected==True)&(evaluation.ground_truth_label==1)&evaluation.correct_issue_type).sum())
    fn=int((((evaluation.detected==False)|(evaluation.correct_issue_type==False))&(evaluation.ground_truth_label==1)).sum())
    fp=int(((evaluation.detected==True)&(evaluation.ground_truth_label==0)).sum())
    precision=tp/(tp+fp) if tp+fp else 1.0
    recall=tp/(tp+fn) if tp+fn else 1.0
    metrics={"true_positives":tp,"false_positives":fp,"false_negatives":fn,
             "precision":round(precision,4),"recall":round(recall,4),
             "f1":round(2*precision*recall/(precision+recall),4) if precision+recall else 0.0,
             "scenarios":len(evaluation)}
    (d/"constraint_detection_metrics.json").write_text(json.dumps(metrics,indent=2))
    return result,metrics
