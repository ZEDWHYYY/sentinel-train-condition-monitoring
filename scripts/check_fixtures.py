"""Record actual pipeline outcomes for every generated fixture."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"command-center/backend"))
from diagnostics import registry
from diagnostics.common import finite

rows=[]
for entry in json.loads((ROOT/"tests/fixtures/manifest.json").read_text()):
    p=ROOT/"tests/fixtures"/entry["file"]
    row={**entry}
    try:
        row["recognition"]=registry.recognize(p,p.name)
        r=registry.analyze_file(entry["subsystem"],p,p.name)
        row.update(outcome="result",available=r["available"],headline=r["headline"],diagnosis=r.get("diagnosis"),
                   predictions=[i["prediction"] for i in r["items"]],issues=r.get("issues"))
    except Exception as e:
        row.update(outcome="error",error=type(e).__name__,message=str(e),code=getattr(e,"code",None))
    rows.append(row)
    registry._parsed.cache_clear()
    print(entry["file"],row["outcome"],row.get("headline",row.get("message")),flush=True)
out=ROOT/(sys.argv[1] if len(sys.argv)>1 else "reports/fixtures_before.json")
out.write_text(json.dumps(finite(rows),indent=2)+"\n")
