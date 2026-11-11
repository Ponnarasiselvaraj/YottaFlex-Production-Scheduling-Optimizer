from pathlib import Path
import hashlib, json
from .generator import generate_dataset

def verify_reproducibility(seed=20261022, scale="starter", output_dir="repro_check"):
    base=Path(output_dir); a=base/"run_a"; b=base/"run_b"
    generate_dataset(a,scale,seed); generate_dataset(b,scale,seed)
    def checksums(folder):
        return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*.csv"))}
    ca,cb=checksums(a),checksums(b)
    report={"seed":seed,"scale":scale,"identical":ca==cb,
            "checksums_run_a":ca,"checksums_run_b":cb}
    base.mkdir(parents=True,exist_ok=True)
    (base/"reproducibility_report.json").write_text(json.dumps(report,indent=2))
    return report
