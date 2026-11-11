from pathlib import Path
import pandas as pd

def append_schedule_event(data_dir, entity_id, event_type, details, event_time):
    """Append-only event log helper. Existing history is never overwritten."""
    path=Path(data_dir)/"schedule_events.csv"
    row={"event_id":f"EVT-MANUAL-{pd.Timestamp.utcnow().strftime('%Y%m%d%H%M%S%f')}",
         "entity_type":"OperationSchedule","entity_id":entity_id,
         "event_type":event_type,"event_time":event_time,"details":details}
    if path.exists():
        old=pd.read_csv(path)
        pd.concat([old,pd.DataFrame([row])],ignore_index=True).to_csv(path,index=False)
    else:
        pd.DataFrame([row]).to_csv(path,index=False)
    return row
