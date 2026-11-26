"""Compare unauthorized channel dispatch on an explicit checkout, using mock DB."""
import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for name, route in (("vk-publisher", "/publish"), ("mailer", "/send")):
        folder = args.checkout.resolve() / "services" / name
        spec = importlib.util.spec_from_file_location(name + "_control", folder / "main.py")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(folder))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        event_id = str(uuid.UUID(int=201))
        fixture = dict(id=event_id, expert_id=str(uuid.UUID(int=101)), title="Synthetic event",
            description="Synthetic body", date=None, location_raw=None, location_resolved=None,
            is_online=False, price_amount=0, expert_name="Synthetic owner")
        db = Mock()
        db.execute.return_value.mappings.return_value.first.return_value = fixture
        db.execute.return_value.mappings.return_value.all.return_value = [
            {"email": "synthetic@quality-check.invalid", "name": "Synthetic recipient"}]
        module.app.dependency_overrides[module.get_db] = lambda: db
        if name == "vk-publisher":
            module.resolve_vk_credentials = lambda event: None
            module.publish_to_vk_api = Mock(side_effect=AssertionError("external dispatch forbidden in test"))
        else:
            module.get_smtp_config = lambda event: None
            module.send_via_smtp = Mock(side_effect=AssertionError("external dispatch forbidden in test"))
        with TestClient(module.app) as client:
            response = client.post(route, json={"event_id": event_id})
        results.append(dict(service=name, status=response.status_code,
            mock_db_commit_calls=db.commit.call_count, external_dispatch=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
