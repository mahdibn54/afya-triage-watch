"""Synthetic demo data (E6-6). Nothing here is real: invented numbers and a made-up identity.

The P-014 patient is always named Grace Achieng (fixed in afya-mcp identity.py, which also makes the file number from
the label). The name goes to the screens only, never to the model or an audit payload.

P-014 numbers are the ones of docs/api.md: reading 1 scores TEWS 3 (YELLOW), reading 2 scores TEWS 6 (ORANGE).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

P014: dict[str, Any] = {
    "label": "P-014",
    "age_years": 40,
    "arrived_minutes_ago": 52,
    "confirmed_colour": "YELLOW",
    "readings": [
        {"values": {"resp_rate": 22, "heart_rate": 105, "systolic_bp": 120, "temperature": 37.2, "spo2": 97,
                    "mobility": "walking", "consciousness": "alert", "trauma": "no"}, "complaint": None},
        {"values": {"resp_rate": 26, "heart_rate": 112, "systolic_bp": 120, "temperature": 38.6, "spo2": 93,
                    "mobility": "walking", "consciousness": "alert", "trauma": "no"},
         "complaint": "Short of breath since morning. My mother had chest pain last year."},
    ],
}
SCENARIOS = {"p014": P014}


def birth_date(age_years: int, today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=round(365.25 * age_years) + 30)).isoformat()
