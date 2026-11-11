# Where to edit the project

| If you want to change... | Edit this file |
|---|---|
| Product, machine, material, orders, seed, generated data volume | `src/generator.py` |
| Inventory allocation, FEFO, material shortage, balances | `src/inventory.py` |
| Machine assignment, shift logic, downtime, setup, tool reservations and objective-aware machine choice | `src/scheduler.py` |
| Makespan / tardiness / changeover weights and priority multipliers | `config/scheduling_objective.json` |
| Objective scoring and KPI calculations | `src/objective.py` and `src/metrics.py` |
| Five injected anomaly examples | `src/anomalies.py` |
| Independent five-rule detection logic | `src/constraint_engine.py` |
| PK/FK, schedule, inventory, tool and changeover validation | `src/validation.py` |
| Makespan, lateness and inventory KPIs | `src/metrics.py` |
| Dashboard layout and tables | `dashboard/app.py` |
| Run order / CLI command flow | `main.py` |
| Automated tests | `tests/test_challenge.py` |
| Business rules and relationships documentation | `docs/architecture.md` and `docs/data_dictionary.md` |

## Safe editing workflow
1. Make a copy or commit your current working version before editing.
2. Edit one module at a time.
3. Run `pytest -q`.
4. Run `python main.py --scale starter`.
5. Check `data/validation_summary.csv` and `data/constraint_detection_metrics.json`.
6. Only then run `python main.py --scale full`.
