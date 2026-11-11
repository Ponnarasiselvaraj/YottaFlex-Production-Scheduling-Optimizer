from pathlib import Path
import json
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="YottaFlex Production Scheduler",layout="wide")
st.title("YottaFlex | Production Scheduling Dashboard")
st.caption("Synthetic factory planning · finite-resource scheduling · independent constraint detection")
d=Path("data")
if not (d/"operation_schedules.csv").exists():
    st.warning("Run `python main.py --scale starter` from the project root first.")
    st.stop()
s=pd.read_csv(d/"operation_schedules.csv")
orders=pd.read_csv(d/"production_orders.csv")
metrics=json.loads((d/"metrics.json").read_text()) if (d/"metrics.json").exists() else {}
k1,k2,k3,k4=st.columns(4)
k1.metric("Orders",metrics.get("total_orders",len(orders)))
k2.metric("Scheduled operations",metrics.get("scheduled_operations",0))
k3.metric("On-time delivery",f"{metrics.get('on_time_delivery_pct',0)}%")
k4.metric("Makespan",f"{metrics.get('makespan_hours',0)} hours")

st.subheader("Multi-objective scheduling")
objective=metrics.get("optimization_objective",{})
if objective:
    a,b,c,e=st.columns(4)
    a.metric("Objective score",objective.get("objective_score",0))
    b.metric("Makespan",f"{objective.get('makespan_hours',0)} h")
    c.metric("Weighted tardiness",f"{objective.get('weighted_tardiness_hours',0)} h")
    e.metric("Changeover",f"{objective.get('changeover_minutes',0)} min")
    st.caption("Weighted objective = makespan + priority-weighted tardiness + changeover cost. Tune config/scheduling_objective.json.")
    st.json(objective.get("objective_weights",{}))
    comparison=metrics.get("baseline_comparison",{})
    if comparison:
        st.markdown("**Compared with the same-seed earliest-finish baseline**")
        x,y,z=st.columns(3)
        x.metric("Composite objective",f"{comparison['optimized_objective_score']:.6f}",
                 f"{comparison['objective_score_change_pct']}%")
        y.metric("Makespan change",f"{comparison['makespan_change_pct']}%")
        z.metric("Changeover change",f"{comparison['changeover_change_pct']}%")
        st.caption(f"Weighted tardiness change: {comparison['weighted_tardiness_change_pct']}% · "
                   f"On-time delivery: {comparison['baseline_on_time_delivery_pct']}% → "
                   f"{comparison['optimized_on_time_delivery_pct']}%")
st.subheader("Machine schedule / Gantt chart")
valid=s[s.schedule_status=="SCHEDULED"].copy()
if not valid.empty:
    valid["start_time"]=pd.to_datetime(valid.start_time); valid["end_time"]=pd.to_datetime(valid.end_time)
    fig=px.timeline(valid,x_start="start_time",x_end="end_time",y="machine_id",
                    color="order_id",hover_data=["operation_id","changeover_minutes"])
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig,use_container_width=True)

st.subheader("Independent constraint detection")
det_path=d/"constraint_detection_results.csv"
if det_path.exists():
    det=pd.read_csv(det_path)
    st.dataframe(det,use_container_width=True,hide_index=True)
    dm=metrics.get("constraint_detection",{})
    a,b,c=st.columns(3)
    a.metric("Detection precision",dm.get("precision",0))
    b.metric("Detection recall",dm.get("recall",0))
    c.metric("Detection F1",dm.get("f1",0))

st.subheader("Inventory ledger")
for filename,label in [("material_allocations.csv","Material allocations / consumption"),
                       ("inventory_balances.csv","Inventory lot balances"),
                       ("inventory_shortages.csv","Inventory shortages")]:
    path=d/filename
    if path.exists():
        st.markdown(f"**{label}**")
        st.dataframe(pd.read_csv(path),use_container_width=True,hide_index=True)

st.subheader("Tool master and requirements")
for filename in ["tools.csv","tool_requirements.csv"]:
    path=d/filename
    if path.exists(): st.dataframe(pd.read_csv(path),use_container_width=True,hide_index=True)

st.subheader("Operation schedule")
st.dataframe(s,use_container_width=True,hide_index=True)
st.subheader("Production orders")
st.dataframe(orders,use_container_width=True,hide_index=True)
vp=d/"validation_summary.csv"
if vp.exists():
    st.subheader("Baseline validation findings")
    findings=pd.read_csv(vp)
    if findings.empty: st.success("No baseline validation findings.")
    else: st.dataframe(findings,use_container_width=True,hide_index=True)
gp=d/"ground_truth.csv"
if gp.exists():
    with st.expander("Ground-truth anomaly labels (evaluation only)"):
        st.dataframe(pd.read_csv(gp),use_container_width=True,hide_index=True)
st.download_button("Download schedule CSV",s.to_csv(index=False),
                   file_name="operation_schedules.csv",mime="text/csv")
