"""Made-up patient identity: deterministic, on the Patient, shown to the screens only, never in model-facing output."""
import json
import re

from afya_mcp import identity, rules, services
from fake_fhir import FakeFhir
from fake_store import FakeStore

REG, SITE = rules.load_registry(), rules.load_site()


def seeded(label="EV-case-abc123"):
    f = FakeFhir()
    v = services.seed_demo_visit(f, label, "1990-01-01", 10, "YELLOW")
    return f, v


def test_same_label_same_name_and_file_number():
    assert identity.name_for("NS-1") == identity.name_for("NS-1")
    assert identity.file_number_for("NS-1") == identity.file_number_for("NS-1")
    assert re.fullmatch(r"F-\d{4}", identity.file_number_for("NS-1"))
    assert len({identity.name_for(f"EV-{i}") for i in range(40)}) > 5


def test_p014_is_grace_achieng():
    assert identity.name_for("P-014") == ("Grace", "Achieng")
    f, v = seeded("P-014")
    patient = f.read("Patient", v["patient_id"])
    assert identity.full_name_of(patient) == "Grace Achieng"


def test_seed_stores_name_file_number_and_keeps_label():
    f, v = seeded()
    p = f.read("Patient", v["patient_id"])
    assert services.label_of(p) == "EV-case-abc123"
    assert identity.file_number_of(p) == identity.file_number_for("EV-case-abc123")
    assert p["name"][0]["text"] == identity.full_name_of(p)
    assert services.demo_visit(f, "EV-case-abc123")["status"] == "found"   # label lookup still works


def test_seed_names_an_older_unnamed_demo_patient():
    f = FakeFhir()
    old = {"resourceType": "Patient", "birthDate": "1986-01-01",
           "identifier": [{"system": services.LABEL_SYSTEM, "value": "P-014"}]}
    f.conditional_create(old, f"{services.LABEL_SYSTEM}|P-014")
    v = services.seed_demo_visit(f, "P-014", "1986-01-01", 5, "YELLOW")
    p = f.read("Patient", v["patient_id"])
    assert identity.full_name_of(p) == "Grace Achieng" and services.label_of(p) == "P-014"


def test_screens_queue_has_identity_model_facing_queue_does_not():
    f, v = seeded()
    patient = f.read("Patient", v["patient_id"])
    name, number = identity.full_name_of(patient), identity.file_number_of(patient)
    ui = services.get_queue_state(f, REG, SITE, FakeStore(), include_identity=True)["patients"][0]
    assert ui["patient_name"] == name and ui["file_number"] == number and ui["patient_label"] == "EV-case-abc123"
    model_facing = json.dumps(services.get_queue_state(f, REG, SITE, FakeStore()))
    assert name not in model_facing and number not in model_facing
    assert "patient_name" not in model_facing and "file_number" not in model_facing
    for part in (*name.split(), number):
        assert part not in model_facing


def test_unnamed_patient_gives_nulls():
    f, v = seeded()
    p = f.read("Patient", v["patient_id"])
    f.put({k: x for k, x in p.items() if k not in ("name",)} | {"identifier": [p["identifier"][0]]})
    row = services.get_queue_state(f, REG, SITE, FakeStore(), include_identity=True)["patients"][0]
    assert row["patient_name"] is None and row["file_number"] is None and row["patient_label"]
