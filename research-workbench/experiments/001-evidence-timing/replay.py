"""Synthetic research exercise: event time is not information availability."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import platform


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("The exercise requires explicit timezones")
    return parsed


def state_at(events, decision_time, mode):
    decision = timestamp(decision_time)
    availability = "event_time" if mode == "hindsight" else "received_time"
    known = [row for row in events if timestamp(row[availability]) <= decision]
    if not known:
        return None
    order = "received_time" if mode == "last_arrival" else "event_time"
    selected = max(known, key=lambda row: timestamp(row[order]))
    return {"event_id": selected["id"], "price": str(Decimal(selected["price"]))}


def main():
    folder = Path(__file__).resolve().parent
    payload = (folder / "events.json").read_bytes()
    events = json.loads(payload)
    early, late = "2026-01-01T10:00:04.500Z", "2026-01-01T10:00:07.500Z"
    results = {
        "early_hindsight": state_at(events, early, "hindsight"),
        "early_available": state_at(events, early, "available"),
        "late_last_arrival": state_at(events, late, "last_arrival"),
        "late_latest_available": state_at(events, late, "available"),
    }
    assert results["early_hindsight"]["event_id"] == "C"
    assert results["early_available"]["event_id"] == "A"
    assert results["late_last_arrival"]["event_id"] == "B"
    assert results["late_latest_available"]["event_id"] == "C"
    output = {
        "synthetic_data": True,
        "input_sha256": sha256(payload).hexdigest(),
        "python": platform.python_version(),
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "decisions": {"early": early, "late": late},
        "results": results,
        "checks_passed": 4,
    }
    (folder / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
