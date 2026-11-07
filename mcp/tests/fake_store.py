"""In-memory VisitStore for unit tests (the real one is afya_mcp.db.PgVisitStore)."""
from __future__ import annotations


class FakeStore:
    def __init__(self, fail: bool = False) -> None:
        self.visits: dict[str, dict[str, str]] = {}
        self.calls = 0
        self.fail = fail
        self.proposals: list[dict] = []
        self.notifications: list[dict] = []
        self.complaints: dict[str, tuple[str, str]] = {}
        self.worsening: set[str] = set()

    def record_reading(self, visit_id: str, patient_id: str, latest_obs_id: str,
                       patient_label: str | None = None, latest_at=None, reading_obs_id: str | None = None,
                       complaint: str | None = None, reported_worsening: bool = False) -> None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("database down")
        self.visits[visit_id] = {"patient_id": patient_id, "latest_obs_id": latest_obs_id,
                                 "patient_label": patient_label}
        if reading_obs_id:
            self.save_complaint(visit_id, reading_obs_id, complaint, reported_worsening)

    def save_complaint(self, visit_id: str, obs_id: str, complaint: str | None,
                       reported_worsening: bool = False) -> None:
        if complaint:
            self.complaints.setdefault(obs_id, (visit_id, complaint))
        if reported_worsening:
            self.worsening.add(obs_id)

    def open_notifications(self) -> list[dict]:
        return list(self.notifications)

    def open_proposals(self) -> list[dict]:
        return list(self.proposals)
