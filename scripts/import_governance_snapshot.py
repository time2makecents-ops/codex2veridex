"""Refresh vendored gate definitions without modifying the source Office-App."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SOURCE = Path(r"C:\Office-App\office_app\backend\master_governance_registry_v1_0_0.json")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "governance" / "navigator_governance_v1.0.0.json"


def active_gate_rows(source: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    rows = payload if isinstance(payload, list) else payload.get("objects") or payload.get("entries") or []
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("status") or "").casefold() != "active":
            continue
        object_id = str(row.get("object_id") or "").strip()
        upper = object_id.upper()
        if not (upper.startswith("GATE-") or upper.endswith("-GATE")):
            continue
        selected[object_id] = {
            "version": str(row.get("version") or ""),
            "source_definition": str(row.get("definition_text") or row.get("description") or ""),
        }
    return selected


def refresh(source: Path, output: Path, check: bool = False) -> bool:
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    source_gates = active_gate_rows(source)
    changed = False
    for gate in snapshot.get("gates", []):
        source_row = source_gates.get(str(gate.get("id") or ""))
        if not source_row:
            continue
        if (
            gate.get("version") != source_row["version"]
            or gate.get("source_definition") != source_row["source_definition"]
        ):
            gate["version"] = source_row["version"]
            gate["source_definition"] = source_row["source_definition"]
            changed = True
    if changed and not check:
        output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the standalone governance snapshot from a read-only source.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Report whether a refresh is needed without writing")
    args = parser.parse_args()
    changed = refresh(args.source.resolve(), args.output.resolve(), args.check)
    print(json.dumps({"source": str(args.source.resolve()), "output": str(args.output.resolve()), "changed": changed, "check": args.check}))
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
