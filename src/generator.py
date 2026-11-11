from pathlib import Path
import json, random
import numpy as np
import pandas as pd

DEFAULT_SEED = 20261022
HORIZON_START = pd.Timestamp("2026-11-16 08:00:00")

def generate_dataset(data_dir="data", scale="starter", seed=DEFAULT_SEED):
    """Generate all parent/master entities before dependent transaction entities."""
    out = Path(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    random.seed(seed)
    rng = np.random.default_rng(seed)

    if scale == "full":
        n_products, n_machines, n_orders, n_materials = 100, 40, 500, 200
    else:
        n_products, n_machines, n_orders, n_materials = 10, 8, 20, 30

    # 1. Master data: Product, Machine, Material, Tool.
    products = pd.DataFrame([{
        "product_id": f"PROD-2026-{i:06d}", "sku": f"SKU-{i:04d}",
        "product_name": f"Product {i:03d}", "family": f"FAMILY-{(i-1)%5+1}",
        "unit": "unit", "lifecycle_state": "ACTIVE"
    } for i in range(1, n_products+1)])

    machines = pd.DataFrame([{
        "machine_id": f"MACH-{i:03d}", "machine_name": f"Machine {i:03d}",
        "machine_type": f"CELL-{(i-1)%4+1}",
        "capacity_units_per_hour": int(rng.integers(8, 21)),
        "calendar_id": f"CAL-{i:03d}", "lifecycle_state": "ACTIVE"
    } for i in range(1, n_machines+1)])

    materials = pd.DataFrame([{
        "material_id": f"MAT-{i:04d}", "material_name": f"Material {i:03d}",
        "unit": "kg", "safety_stock": int(rng.integers(5, 25)),
        "lifecycle_state": "ACTIVE"
    } for i in range(1, n_materials+1)])

    tools = pd.DataFrame([{
        "tool_id": f"TOOL-{i:03d}", "tool_type": f"TOOLTYPE-{i:02d}",
        "available_units": 1 if i % 3 else 2, "lifecycle_state": "ACTIVE"
    } for i in range(1, 7)])

    # 2. Routing and operations master.
    routings, route_operations, eligibility = [], [], []
    step_names = ["Cutting", "Drilling", "Assembly", "Inspection"]
    for p in products.itertuples():
        routing_id = f"ROUTE-{p.sku}-01"
        routings.append({
            "routing_id": routing_id, "product_id": p.product_id, "revision": 1,
            "effective_from": "2026-01-01", "effective_to": "",
            "lifecycle_state": "ACTIVE"
        })
        for seq, name in enumerate(step_names, 1):
            machine_type = f"CELL-{seq}"
            tool_id = f"TOOL-{(seq-1)%6+1:03d}" if seq in (2, 3) else ""
            route_operations.append({
                "route_operation_id": f"{routing_id}-STEP-{seq:02d}",
                "routing_id": routing_id, "sequence_no": seq,
                "operation_name": name, "machine_type_required": machine_type,
                "base_duration_minutes": int(rng.integers(35, 76)),
                "tool_id": tool_id, "setup_family": p.family
            })
            for m in machines[machines.machine_type == machine_type].itertuples():
                eligibility.append({
                    "routing_id": routing_id, "sequence_no": seq,
                    "machine_id": m.machine_id
                })

    routings = pd.DataFrame(routings)
    route_operations = pd.DataFrame(route_operations)
    eligibility = pd.DataFrame(eligibility)

    # 3. Calendars and machine downtime.
    calendars = pd.DataFrame([{
        "calendar_id": m.calendar_id, "machine_id": m.machine_id,
        "shift_start": "08:00", "shift_end": "16:00",
        "working_days": "0,1,2,3,4", "timezone": "Asia/Kolkata"
    } for m in machines.itertuples()])

    downtime_rows = []
    for m in machines.itertuples():
        if int(m.machine_id[-3:]) % 4 == 0:
            start = HORIZON_START + pd.Timedelta(days=2, hours=2)
            downtime_rows.append({
                "downtime_id": f"DOWN-{m.machine_id}", "machine_id": m.machine_id,
                "start_time": start.isoformat(),
                "end_time": (start + pd.Timedelta(hours=2)).isoformat(),
                "reason": "PLANNED_MAINTENANCE"
            })
    downtime = pd.DataFrame(downtime_rows, columns=[
        "downtime_id", "machine_id", "start_time", "end_time", "reason"
    ])

    # 4. Inventory lots. Selected materials are deliberately delayed but valid.
    lot_rows = []
    for i, mat in enumerate(materials.itertuples(), 1):
        delayed = (i % 13 == 0)
        available = HORIZON_START + pd.Timedelta(days=2) if delayed else HORIZON_START-pd.Timedelta(days=1)
        lot_rows.append({
            "lot_id": f"LOT-{i:04d}-01", "material_id": mat.material_id,
            "quantity": 10000, "available_at": available.isoformat(),
            "expiry_date": "2027-12-31", "lifecycle_state": "AVAILABLE"
        })
    inventory_lots = pd.DataFrame(lot_rows)

    # 5. Orders and dependent operations/material/tool requirements.
    orders, operations, material_requirements, tool_requirements = [], [], [], []
    for i in range(1, n_orders+1):
        p = products.iloc[(i-1) % n_products]
        routing_id = f"ROUTE-{p.sku}-01"
        quantity = int(rng.integers(10, 31))
        priority = "URGENT" if i % 17 == 0 else random.choice(["HIGH", "NORMAL", "LOW"])
        due_windows = {"URGENT": (7, 20), "HIGH": (20, 45), "NORMAL": (35, 75), "LOW": (60, 120)}
        low, high = due_windows[priority]
        due = HORIZON_START + pd.Timedelta(days=int(rng.integers(low, high+1)))
        order_id = f"ORD-2026-{i:06d}"
        orders.append({
            "order_id": order_id, "product_id": p.product_id,
            "routing_id": routing_id, "quantity": quantity,
            "order_date": (HORIZON_START-pd.Timedelta(days=3)).isoformat(),
            "due_date": due.isoformat(), "priority": priority,
            "lifecycle_state": "RELEASED"
        })
        route_steps = route_operations[route_operations.routing_id == routing_id].sort_values("sequence_no")
        for step in route_steps.itertuples():
            operations.append({
                "operation_id": f"OP-{order_id}-{step.sequence_no:02d}",
                "order_id": order_id, "routing_id": routing_id,
                "sequence_no": int(step.sequence_no), "operation_name": step.operation_name,
                "duration_minutes": int(step.base_duration_minutes),
                "required_machine_type": step.machine_type_required,
                "setup_family": p.family, "tool_id": step.tool_id,
                "lifecycle_state": "RELEASED"
            })
        # Two distinct material requirements per order.
        material_indexes = sorted({(i-1) % n_materials, (i*7) % n_materials})
        for ix in material_indexes:
            material_requirements.append({
                "order_id": order_id, "material_id": materials.iloc[ix].material_id,
                "required_quantity": quantity*2, "unit": "kg"
            })
        for step in route_steps.itertuples():
            if step.tool_id:
                tool_requirements.append({
                    "order_id": order_id, "operation_sequence": int(step.sequence_no),
                    "tool_id": step.tool_id, "required_units": 1
                })

    production_orders = pd.DataFrame(orders)
    operations = pd.DataFrame(operations)
    material_requirements = pd.DataFrame(material_requirements)
    tool_requirements = pd.DataFrame(tool_requirements)

    # 6. Directed, sequence-dependent changeovers.
    families = sorted(products.family.unique())
    changeovers = pd.DataFrame([{
        "from_family": a, "to_family": b,
        "changeover_minutes": 0 if a == b else 20 + ((families.index(a)+families.index(b)) % 3)*10
    } for a in families for b in families])

    tables = {
        "products": products, "machines": machines, "materials": materials, "tools": tools,
        "routings": routings, "route_operations": route_operations,
        "machine_eligibility": eligibility, "machine_calendars": calendars,
        "machine_downtime": downtime, "inventory_lots": inventory_lots,
        "production_orders": production_orders, "operations": operations,
        "material_requirements": material_requirements,
        "tool_requirements": tool_requirements, "changeover_matrix": changeovers
    }
    for name, df in tables.items():
        df.to_csv(out/f"{name}.csv", index=False)
        df.to_json(out/f"{name}.json", orient="records", indent=2)

    manifest = {
        "seed": seed, "scale": scale, "generated_at": "deterministic",
        "source": "Original synthetic data generated by this project; no external data used.",
        "row_counts": {name: len(df) for name, df in tables.items()}
    }
    (out/"source_manifest.json").write_text(json.dumps(manifest, indent=2))
    return tables
