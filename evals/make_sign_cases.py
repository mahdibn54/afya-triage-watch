"""Write pre-registered sign-coverage cases (evals/cases/sign_coverage): one case for each SATS warning sign that no
earlier case expected the model to find, plus two tricky neighbours. Colours come from the SATS rules engine; sign
labels are the author's reading of each complaint, fixed BEFORE any run. French and Swahili wording is the author's and
is listed for review by a native speaker.

    python evals/make_sign_cases.py evals/cases/sign_coverage
"""
import json
import sys
from pathlib import Path

from afya_mcp import rules

OUT = Path(sys.argv[1])
chart = rules.load_chart()
N = dict(mobility="walking", consciousness="alert", trauma="no")


def v(rr, hr, sbp, t, spo2, **kw):
    return {"resp_rate": rr, "heart_rate": hr, "systolic_bp": sbp, "temperature": t, "spo2": spo2, **{**N, **kw}}


CALM = v(16, 82, 122, 36.9, 98)

# id, title, age, confirmed colour, arrived minutes ago, [(values, complaint)], signs, forbidden signs, why
CASES = [
    ("s01-airway-choking", "relative: choking, cannot breathe", 34, "YELLOW", 15,
     [(CALM, None),
      (v(28, 118, 130, 37.0, 90),
       "He is choking, something is stuck in his throat and he cannot breathe.")],
     ["AIRWAY_OBSTRUCTED"], [], "airway obstruction is RED whatever the score"),
    ("s02-fitting-now", "relative: fitting right now", 22, "YELLOW", 20,
     [(CALM, None), (v(22, 124, 134, 37.4, 94, consciousness="pain"),
                     "She is fitting right now, shaking all over and not answering me.")],
     ["SEIZURE_CURRENT"], [], "current seizure is RED"),
    ("s03-postictal-french", "French: had a fit twenty minutes ago, tired now", 29, "GREEN", 30,
     [(CALM, None),
      (v(16, 88, 124, 36.9, 98),
       "J'ai fait une crise d'épilepsie il y a vingt minutes, je suis très fatigué.")],
     ["SEIZURE_POSTICTAL"], ["SEIZURE_CURRENT"], "just had a fit, not fitting now"),
    ("s04-coughing-blood-swahili", "Swahili: coughing blood since last night", 47, "GREEN", 25,
     [(CALM, None),
      (v(18, 90, 120, 37.2, 97),
       "Nakohoa damu tangu jana usiku.")],
     ["COUGHING_BLOOD"], ["VOMITING_FRESH_BLOOD"], "coughing up blood, in Swahili; not vomiting"),
    ("s05-bleeding-will-not-stop", "leg wound keeps bleeding through the cloth", 31, "YELLOW", 15,
     [(CALM, None),
      (v(18, 104, 116, 36.8, 98),
       "My leg wound keeps bleeding, the cloth is soaked and it will not stop.")],
     ["HAEMORRHAGE_UNCONTROLLED"], ["HAEMORRHAGE_CONTROLLED"], "uncontrolled bleeding is ORANGE"),
    ("s06-aggression", "threatening staff", 26, "GREEN", 40,
     [(CALM, None),
      (v(20, 108, 138, 36.9, 98),
       "Leave me alone or I will hit you, I am going to break everything here!")],
     ["AGGRESSION"], [], "aggressive or violent behaviour"),
    ("s07-confused-said-by-family", "family says he is confused, reading recorded as alert", 74, "YELLOW", 60,
     [(CALM, None),
      (v(18, 90, 132, 37.3, 96),
       "My father is confused since this morning, he does not know where he is.")],
     ["LOC_REDUCED_CONFUSED"], [], "confusion reported in the complaint, not in the AVPU reading"),
    ("s08-vomiting-all-night", "vomiting all night, cannot keep water down", 36, "GREEN", 30,
     [(CALM, None),
      (v(18, 96, 116, 37.1, 98),
       "I have been vomiting all night, I cannot keep even water down.")],
     ["VOMITING_PERSISTENT"], ["VOMITING_FRESH_BLOOD"], "persistent vomiting, no blood"),
    ("s09-belly-pain-swahili", "Swahili: stomach hurts since yesterday", 40, "GREEN", 35,
     [(CALM, None),
      (v(16, 86, 124, 37.0, 98),
       "Tumbo linauma tangu jana.")],
     ["ABDOMINAL_PAIN"], ["PREGNANCY_ABDO_PAIN", "SEVERE_PAIN"], "belly pain, no severity given"),
    ("s10-knee-pain-six", "knee pain six out of ten", 52, "GREEN", 45,
     [(CALM, None),
      (v(16, 84, 128, 36.8, 98),
       "My knee hurts a lot when I walk, about 6 out of 10.")],
     ["MODERATE_PAIN"], ["SEVERE_PAIN"], "pain 6/10 is moderate under the 5-7 cutoff"),
    ("s11-pregnant-bleeding", "five months pregnant, bleeding from below", 30, "GREEN", 20,
     [(CALM, None),
      (v(18, 92, 114, 36.9, 98),
       "I am five months pregnant and I have some bleeding from below since this morning.")],
     ["PREGNANCY_PV_BLEED"], ["PREGNANCY_ABDO_PAIN"], "pregnancy with vaginal bleeding, no belly pain stated"),
    ("s12-yellow-sign-already-yellow", "keeps vomiting, but already confirmed YELLOW", 44, "YELLOW", 50,
     [(CALM, None),
      (v(18, 94, 118, 37.0, 98),
       "I keep vomiting, four times since I arrived.")],
     ["VOMITING_PERSISTENT"], [], "a YELLOW sign on a YELLOW patient: no proposal, never the same or lower"),
    ("s13-no-convulsions-swahili", "code-switched: no convulsions, just a fever", 19, "GREEN", 30,
     [(CALM, None),
      (v(18, 96, 122, 38.4, 98),
       "Hakuna degedege, just a fever since yesterday.")],
     [], ["SEIZURE_CURRENT", "SEIZURE_POSTICTAL"], "negated convulsions ('hakuna degedege') must not count"),
]

OUT.mkdir(parents=True, exist_ok=True)
for cid, title, age, conf, arrived, readings, signs, forbidden, why in CASES:
    after = rules.score(readings[-1][0], chart)
    before = rules.score(readings[0][0], chart)
    trig = rules.evaluate_trigger(conf, after, signs, chart, previous_colour=before.colour)
    case = {
        "id": cid, "synthetic": True, "title": title, "split": "held_out", "tags": ["sign_coverage", "fresh"],
        "age_years": age, "confirmed_colour": conf, "arrived_minutes_ago": arrived,
        "readings": [{"values": vals, "complaint": c} for vals, c in readings],
        "expected": {"proposal": trig.propose, **({"to_colour": trig.to_colour} if trig.propose else {}),
                     "signs": signs, "forbidden_signs": forbidden,
                     "label_basis": f"TEWS {before.tews}->{after.tews} ({after.colour_by_tews}); {why}. "
                                    "Pre-registered before any run; colours from the SATS rules, signs by the author."},
    }
    (OUT / f"{cid}.json").write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")
    to = case["expected"].get("to_colour", "no proposal")
    print(f"{cid:34} {conf:6} -> {to:11} TEWS {before.tews}->{after.tews}")
