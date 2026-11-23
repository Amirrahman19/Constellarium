"""Split seed/seed_data.json (kept in git history) into seed_ideabank.json and seed_problembank.json.
Problems = the 'Problem Discovery & Research' items; everything else is an idea. Run once from the project root."""
import json
from pathlib import Path
root = Path(__file__).resolve().parent.parent
d = json.loads((root / "seed" / "seed_data.json").read_text(encoding="utf-8"))
PB_CAT = "Problem Lab & ExCo > Problem Discovery & Research"
DOMAIN = {
    "Transcribe SEEPO healthcare problem statements": "Healthcare",
    "Satellite-data insights (EASOS, IPP Kenya)": "Climate & Space",
    "User interviews: reducing reading friction for higher-ed students": "Education",
    "Help survey on EV / low-emission mobility adoption": "Climate & Space",
}
pb = [dict(i) for i in d["ideas"] if i["category"] == PB_CAT]
ib = [i for i in d["ideas"] if i["category"] != PB_CAT]
for i in pb:
    i["category"] = DOMAIN.get(i["title"], "Method & Delivery")
pb_titles = {i["title"] for i in pb}
for i in pb:
    i["related"] = [r for r in i.get("related", []) if r in pb_titles]
for i in ib:
    i["related"] = [r for r in i.get("related", []) if r not in pb_titles]
used_ib = {i["category"] for i in ib}
cats_ib = [c for c in d["categories"] if c["name"] in used_ib or any(u.startswith(c["name"] + " > ") for u in used_ib)]
pb_proj = {p for i in pb for p in i.get("projects", [])}
desc = {"Healthcare": "Problems from health and care settings.", "Climate & Space": "Environment, mobility and satellite-data problems.",
        "Education": "Problems students and learners face.", "Method & Delivery": "How problems are found, validated and handed to makers."}
cats_pb = [{"name": n, "description": desc[n]} for n in sorted({i["category"] for i in pb})]
(root / "seed" / "seed_ideabank.json").write_text(json.dumps({"categories": cats_ib, "projects": d["projects"], "ideas": ib}, indent=1, ensure_ascii=False), encoding="utf-8")
(root / "seed" / "seed_problembank.json").write_text(json.dumps({"categories": cats_pb, "projects": [p for p in d["projects"] if (p["name"] if isinstance(p, dict) else p) in pb_proj], "ideas": pb}, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(ib), "ideas ->", "seed_ideabank.json;", len(pb), "problems -> seed_problembank.json")
