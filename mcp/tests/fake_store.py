"""In-memory VisitStore for unit tests (the real one is afya_mcp.db.PgVisitStore)."""
from __future__ import annotations


class FakeStore:
    def __init__(self, fail: bool = False) -> None:
        self.visits: dict[str, dict[str, str]] = {}
        self.calls = 0
        self.fail = fail
        self.proposals: list[dict] = []

    def record_reading(self, visit_id: str, patient_id: str, latest_obs_id: str) -> None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("database down")
        self.visits[visit_id] = {"patient_id": patient_id, "latest_obs_id": latest_obs_id}

    def open_proposals(self) -> list[dict]:
        return list(self.proposals)
