"""Write pre-registered nurse-session cases (evals/cases/nurse_session). Colours come from the SATS rules engine;
sign labels are the author's reading of each complaint, fixed BEFORE any run."""
import json
import sys
from pathlib import Path

from afya_mcp import rules

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "evals/cases/nurse_session")
chart = rules.load_chart()
N = dict(mobility="walking", consciousness="alert", trauma="no")


def v(rr, hr, sbp, t, spo2, **kw):
    return {"resp_rate": rr, "heart_rate": hr, "systolic_bp": sbp, "temperature": t, "spo2": spo2, **N, **kw}


CASES = [
    ("n01-elderly-bp-drop", "72-year-old, BP falls and pulse climbs, no complaint", 72, "YELLOW", 50,
     [(v(18, 96, 128, 37.0, 96), None), (v(24, 124, 86, 37.1, 94), None)], [], [], "vitals only"),
    ("n02-worst-headache", "young adult, normal vitals, 'worst headache of my life'", 24, "GREEN", 30,
     [(v(16, 82, 124, 36.8, 99), None),
      (v(16, 84, 126, 36.8, 99), "This is the worst headache of my life, the pain is terrible, 10 out of 10.")],
     ["SEVERE_PAIN"], [], "severe pain stated by the patient"),
    ("n03-fainted-yesterday", "fainted yesterday, fine now, stable vitals", 35, "YELLOW", 40,
     [(v(16, 78, 118, 36.9, 98), None),
      (v(16, 80, 120, 36.9, 98), "I fainted at home yesterday but I feel fine now.")],
     [], ["LOC_REDUCED_CONFUSED"], "past event, alert now: no current sign"),
    ("n04-orange-improves", "confirmed ORANGE, vitals improve", 45, "ORANGE", 20,
     [(v(26, 118, 110, 38.7, 94), None), (v(18, 98, 120, 37.6, 97), None)], [], [], "never propose lower"),
    ("n05-face-arm-numb", "sudden one-sided numbness", 58, "YELLOW", 35,
     [(v(16, 84, 150, 36.9, 98), None),
      (v(16, 86, 152, 36.9, 98), "Since twenty minutes my left arm and the left side of my face feel numb.")],
     ["FOCAL_NEURO_ACUTE"], [], "acute focal neurology"),
    ("n06-french-blood-vomit", "French complaint: vomited blood this morning", 41, "GREEN", 25,
     [(v(17, 92, 116, 37.0, 98), None),
      (v(17, 94, 114, 37.0, 98), "J'ai vomi du sang rouge ce matin, deux fois.")],
     ["VOMITING_FRESH_BLOOD"], [], "fresh red blood vomited, in French"),
    ("n07-pregnant-belly-pain", "7 months pregnant, belly pain for one hour", 27, "YELLOW", 30,
     [(v(18, 90, 112, 36.9, 98), None),
      (v(18, 96, 110, 36.9, 98), "I am seven months pregnant and my belly started hurting an hour ago.")],
     ["PREGNANCY_ABDO_PAIN"], [], "pregnancy with abdominal pain"),
    ("n08-too-many-tablets", "took too many sleeping tablets", 33, "GREEN", 20,
     [(v(15, 76, 118, 36.7, 98), None),
      (v(14, 72, 116, 36.7, 98), "I took about fifteen of my sleeping tablets two hours ago.")],
     ["POISONING_OVERDOSE"], [], "overdose"),
    ("n09-negations-cough", "only a cough, explicitly no chest pain or breathlessness", 50, "YELLOW", 45,
     [(v(18, 88, 130, 37.3, 97), None),
      (v(18, 88, 130, 37.3, 97), "Just a cough for three days. No chest pain and no problem breathing.")],
     [], ["CHEST_PAIN", "SOB_ACUTE"], "negated signs must not count"),
    ("n10-becomes-drowsy", "responds only to voice now, breathing faster", 66, "YELLOW", 55,
     [(v(18, 92, 134, 37.4, 96), None),
      (v(24, 98, 130, 37.5, 94, consciousness="voice"), None)], [], [], "AVPU voice implies reduced consciousness"),
    ("n11-cut-bandaged", "bleeding from a cut stopped with a bandage", 29, "GREEN", 30,
     [(v(16, 80, 122, 36.8, 99), None),
      (v(16, 82, 120, 36.8, 99), "I cut my hand, it bled a lot but the bandage stopped it now.", )],
     ["HAEMORRHAGE_CONTROLLED"], ["HAEMORRHAGE_UNCONTROLLED"], "controlled bleeding is YELLOW, not ORANGE"),
    ("n12-swahili-severe-pain", "Swahili: head hurts very badly", 38, "GREEN", 25,
     [(v(16, 86, 124, 36.9, 99), None),
      (v(16, 88, 126, 36.9, 99), "Kichwa kinauma sana, maumivu makali mno tangu asubuhi.")],
     ["SEVERE_PAIN"], [], "severe headache since morning, in Swahili"),
]

# Cases that drove a prompt change no longer count as held-out (see README.md in the output folder).
TUNED = {"n02-worst-headache"}

OUT.mkdir(parents=True, exist_ok=True)
for cid, title, age, conf, arrived, readings, signs, forbidden, why in CASES:
    after = rules.score(readings[-1][0], chart)
    before = rules.score(readings[0][0], chart)
    trig = rules.evaluate_trigger(conf, after, signs, chart, previous_colour=before.colour)
    case = {
        "id": cid, "synthetic": True, "title": title, "split": "tuning" if cid in TUNED else "held_out",
        "tags": ["nurse_session", "fresh"] + (["drove-prompt-fix"] if cid in TUNED else []),
        "age_years": age, "confirmed_colour": conf, "arrived_minutes_ago": arrived,
        "readings": [{"values": vals, "complaint": c} for vals, c in readings],
        "expected": {"proposal": trig.propose, **({"to_colour": trig.to_colour} if trig.propose else {}),
                     "signs": signs, "forbidden_signs": forbidden,
                     "label_basis": f"TEWS {before.tews}->{after.tews} ({after.colour_by_tews}); {why}. "
                                    "Pre-registered before any run; colours from the SATS rules, signs by the author."},
    }
    (OUT / f"{cid}.json").write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")
    print(cid, conf, "->", case["expected"].get("to_colour", "no proposal"), f"TEWS {before.tews}->{after.tews}")
