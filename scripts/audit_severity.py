"""Enrich pip-audit records with authoritative OSV advisory severities."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT


def main() -> None:
    """Fetch advisory metadata only; never send source code or credentials."""
    source = ROOT/"eval/reports/security/pip-audit.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    records = {}
    for package in data["dependencies"]:
        for vuln in package.get("vulns",[]):
            advisory = next((v for v in [vuln["id"],*vuln.get("aliases",[])] if v.startswith("GHSA-")),vuln["id"])
            records[advisory] = {"package":package["name"],"advisory":advisory,"fix_versions":vuln["fix_versions"]}
    def fetch(item: dict) -> dict:
        try:
            response = requests.get("https://api.osv.dev/v1/vulns/"+item["advisory"],timeout=30)
            response.raise_for_status()
            advisory = response.json()
            item.update(severity=advisory.get("database_specific",{}).get("severity","UNKNOWN"),
                        cvss=advisory.get("severity",[]),summary=advisory.get("summary",""))
        except requests.RequestException:
            item.update(severity="UNKNOWN",error="Advisory metadata unavailable")
        return item
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch,records.values()))
    target = source.with_name("advisory-severities.json")
    target.write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(json.dumps(results,indent=2))


if __name__ == "__main__":
    main()
