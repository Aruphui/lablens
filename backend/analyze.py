"""Turn lab-report text into structured, flagged results.

Pipeline (the LLM is allowed to READ, never to be trusted):
  1. clean text, drop repeated headers/footers, split into overlapping chunks
  2. LLM proposes rows per chunk  ->  every row must be GROUNDED in the source text
       - the value must exist as a number in the text, right after the test's name
       - each reference bound must exist as a number next to that value
       - the unit is copied from the text, not from the model
     anything that fails is dropped and reported, never silently kept
  3. a rule-based reader also scans every chunk (catches rows the LLM missed, and is the
     fallback if the LLM is down). Its rows are text-grounded by construction.
  4. status (HIGH/LOW/CRITICAL) is computed by code, never by the LLM
"""
import datetime as dt
import json
import logging
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dateutil import parser as dparser

from llm import chat

log = logging.getLogger("lablens")

# ───────────────────────── canonical test names ─────────────────────────
def _R(canon, inc, exc=None):
    return canon, re.compile(inc, re.I), (re.compile(exc, re.I) if exc else None)


_RULES = [
    _R("Estimated Avg Glucose", r"estimated.*glucose|average.*glucose|\beag\b"),
    _R("HbA1c", r"hba1c|hb\s*a1c|glycat|glycosylat|\ba1c\b"),
    _R("Glucose (Post-meal)", r"post[\s-]?prandial|\bppbs\b|\bppg\b|\bpp\b.*(glucose|sugar)|(glucose|sugar).*\bpp\b"),
    _R("Glucose (Fasting)", r"^(?=.*(?:glucose|sugar|\bfbs\b|\bfbg\b|\bfpg\b)).*(?:fasting|\bfbs\b|\bfbg\b|\bfpg\b)", r"insulin"),
    _R("Glucose (Random)", r"random.*(glucose|sugar)|(glucose|sugar).*random|\brbs\b|\brbg\b|^(?:blood\s+)?(?:glucose|sugar)\b"),
    _R("Insulin", r"^insulin"),
    _R("Free T3", r"free\s*t3|\bft3\b|free\s*tri"),
    _R("Free T4", r"free\s*t4|\bft4\b|free\s*thyrox"),
    _R("TSH", r"\btsh\b|thyroid stimulating|thyrotropin"),
    _R("T3 (Total)", r"\bt3\b|tri-?\s*iodothyronine", r"free|\bft3\b|uptake|resin"),
    _R("T4 (Total)", r"\bt4\b|thyroxine", r"free|\bft4\b|uptake"),
    _R("Cholesterol/HDL Ratio", r"chol.*hdl.*ratio|ratio.*hdl"),
    _R("Non-HDL Cholesterol", r"non[\s-]*hdl"),
    _R("VLDL Cholesterol", r"\bvldl\b"),
    _R("LDL Cholesterol", r"\bldl\b|low density"),
    _R("HDL Cholesterol", r"\bhdl\b|high density"),
    _R("Total Cholesterol", r"cholesterol"),
    _R("Triglycerides", r"triglycerid|\btg\b"),
    _R("MCHC", r"\bmchc\b|mean corp\w*\s+h\w*\s+conc"),
    _R("MCH", r"\bmch\b|mean corp\w*\s+h\w*", r"conc|mchc"),
    _R("MCV", r"\bmcv\b|mean corp\w*\s+vol"),
    _R("MPV", r"\bmpv\b|mean platelet vol"),
    _R("RDWI", r"\brdwi\b"),
    _R("RDW-SD", r"rdw.*\bsd\b|distribution width.*\bsd\b"),
    _R("RDW-CV", r"\brdw\b|distribution width", r"\bsd\b"),
    _R("Neutrophil/Lymphocyte Ratio", r"neutrophil.*lymphocyte|\bnlr\b"),
    _R("Plateletcrit", r"platelet\s*h[a]?ematocrit|plateletcrit|\bpct\b"),
    _R("Platelet Count", r"platelet|\bplt\b"),
    _R("Hematocrit (PCV)", r"h[a]?ematocrit|\bpcv\b|\bhct\b|packed cell"),
    _R("Hemoglobin", r"\b(?:h(?:a)?emoglobin|hgb|hb)\b", r"glyco|glycat|a1c|mean|corp|mch|conc|fetal"),
    _R("WBC Count", r"\bwbc\b|\btlc\b|\btc\b|leu[ck]ocyte count|white blood cell", r"differential|absolute"),
    _R("RBC Count", r"\brbc\b|red blood cell|red cell count", r"distribution|width"),
    _R("ESR", r"\besr\b|erythrocyte sediment"),
    _R("Vitamin D", r"vitamin\s*d|25[\s-]*(?:oh|hydroxy)"),
    _R("Vitamin B12", r"b[\s-]?12|cobalamin"),
    _R("Calcium", r"^calcium"),
    _R("Creatinine", r"creatinine", r"clearance|ratio"),
    _R("Urea", r"^(?:blood\s+)?urea|\bbun\b"),
    _R("Uric Acid", r"uric acid"),
    _R("SGPT (ALT)", r"\bsgpt\b|\balt\b|alanine"),
    _R("SGOT (AST)", r"\bsgot\b|\bast\b|aspartate"),
    _R("Alkaline Phosphatase", r"alkaline phos|\balp\b"),
    _R("Bilirubin (Direct)", r"bilirubin.*direct|direct.*bilirubin"),
    _R("Bilirubin (Total)", r"bilirubin"),
    _R("Albumin", r"^albumin"),
    _R("Sodium", r"^sodium"),
    _R("Potassium", r"^potassium"),
    _R("Chloride", r"^chloride"),
    _R("Prolactin", r"prolactin"),
    _R("Testosterone", r"testosterone"),
    _R("LH:FSH Ratio", r"(lh|luteinizing).*(fsh|follicle).*ratio|lh\s*:\s*fsh"),
    _R("LH", r"\blh\b|luteinizing"),
    _R("FSH", r"\bfsh\b|follicle[\s-]*stimulating"),
]
for _cell, _pat in (("Neutrophils", "neutrophil"), ("Lymphocytes", "lymphocyte"), ("Monocytes", "monocyte"),
                    ("Eosinophils", "eosinophil"), ("Basophils", "basophil")):
    _i = next(i for i, r in enumerate(_RULES) if r[0] == "Plateletcrit")
    _RULES[_i:_i] = [_R(f"{_cell} (Absolute)", rf"absolute.*{_pat}|{_pat}.*absolute|\ba[a-z]c\b.*{_pat}"),
                     _R(f"{_cell} (%)", _pat, r"absolute|ratio")]

CRITICAL = {  # (low, high): at/below low or at/above high is treated as critical
    "Glucose (Fasting)": (50, 300),
    "Hemoglobin": (7, None),
    "Potassium": (2.8, 6.5),
}


def normalize_name(raw: str) -> str:
    clean = re.sub(r"\s+", " ", raw.strip()).strip(" :-.,|")
    for canon, inc, exc in _RULES:
        if inc.search(clean) and not (exc and exc.search(clean)):
            return canon
    return clean.title() if clean.isupper() else clean


def compute_status(name, value, low, high) -> str:
    lo_c, hi_c = CRITICAL.get(name, (None, None))
    if (lo_c is not None and value <= lo_c) or (hi_c is not None and value >= hi_c):
        return "CRITICAL"
    if low is None and high is None:
        return "UNKNOWN"
    if low is not None and value < low:
        return "LOW"
    if high is not None and value > high:
        return "HIGH"
    return "NORMAL"


# ───────────────────────── dates ─────────────────────────
def norm_date(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        pass
    try:
        d = dparser.parse(s, dayfirst=True).date()
        if 2000 <= d.year <= dt.date.today().year + 1:
            return d.isoformat()
    except (ValueError, OverflowError):
        pass
    return None


_DATE = r"(\d{1,2}[-/ .][A-Za-z0-9]{1,9}[-/ .]\d{2,4}|\d{4}-\d{2}-\d{2})"
_DATE_HINTS = [  # most reliable first: the day the blood was drawn
    re.compile(r"(?:sample\s+)?collect(?:ed|ion)(?:\s+(?:on|date))?[^\n\d]{0,25}" + _DATE, re.I),
    re.compile(r"(?:received|reported|report\s+(?:generated\s+)?(?:on|date)|date)[^\n\d]{0,25}" + _DATE, re.I),
]


def guess_date(text: str):
    for pat in _DATE_HINTS:
        for m in pat.finditer(text):
            d = norm_date(m.group(1))
            if d:
                return d
    return None


# ───────────────────────── number helpers ─────────────────────────
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_UNIT_RE = re.compile(r"\s*(%|/\S+|\d+[\^³]\d*/\S+|[A-Za-zµμ][^\s]*)")
_STOP = {"count", "total", "serum", "blood", "test", "level", "levels", "mean", "ratio", "index", "plasma", "whole",
         "absolute", "hormone", "with", "and", "the", "of", "ultrasensitive"}


def _nums(s):
    return [(m.start(), m.end(), float(m.group().replace(",", ""))) for m in NUM_RE.finditer(s)]


def to_float(x):
    if x is None or isinstance(x, bool):
        return None
    m = NUM_RE.search(str(x))
    return float(m.group().replace(",", "")) if m else None


# ───────────────────────── grounding (the anti-hallucination check) ─────────────────────────
def _unit_after(text, end, claimed):
    m = _UNIT_RE.match(text[end : end + 40])
    if m and not re.fullmatch(r"[-–]|to", m.group(1)):
        return m.group(1).rstrip(",;")
    if claimed and claimed.lower().replace(" ", "") in text[end : end + 60].lower().replace(" ", ""):
        return claimed
    return ""


def ground(name, value, claimed_unit, lo, hi, text, low_text, nums):
    """Return a verified row, or None if `value` is not really this test's result in `text`."""
    toks = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 2 and t not in _STOP]
    best = None
    for s, e, v in nums:
        if abs(v - value) > 1e-9:
            continue
        pre = low_text[max(0, s - 300) : s]
        if toks and not any(re.search(r"(?<![a-z0-9])" + re.escape(t), pre) for t in toks):
            continue  # right number, wrong place: it is not next to this test's name
        near = [x for x in nums if abs(x[0] - s) <= 160 and (x[0], x[1]) != (s, e)]
        ok_lo = lo is None or any(abs(x[2] - lo) < 1e-9 for x in near)
        ok_hi = hi is None or any(abs(x[2] - hi) < 1e-9 for x in near)
        score = int(ok_lo) + int(ok_hi)
        if best is None or score > best[0]:
            best = (score, s, e, ok_lo, ok_hi)
        if score == 2:
            break
    if best is None:
        return None
    _, s, e, ok_lo, ok_hi = best
    lo_f, hi_f = (lo if ok_lo else None), (hi if ok_hi else None)
    refs_dropped = (lo is not None and not ok_lo) or (hi is not None and not ok_hi)
    if lo_f is not None and hi_f is not None and lo_f >= hi_f:
        lo_f = hi_f = None
    q = re.search(r"([<>])=?\s*$", text[max(0, s - 4) : s])
    return {"pos": s, "value": value, "qualifier": q.group(1) if q else "",
            "unit": _unit_after(text, e, claimed_unit),
            "ref_low": lo_f, "ref_high": hi_f, "refs_dropped": refs_dropped}


# ───────────────────────── LLM reader ─────────────────────────
SYSTEM = ("You copy lab test results out of medical report text into JSON. "
          "You only copy what is printed. You never calculate, correct, infer or add anything.")
PROMPT = """Extract every lab test that has a measured numeric result from the TEXT.

Return ONLY a JSON array with one object per test:
{{"test_name": "...", "value": "...", "unit": "...", "ref_low": "...", "ref_high": "..."}}

Rules:
- Copy every field exactly as printed, as a string. Keep digits unchanged ("2.940" stays "2.940").
- "value" is the patient's own result. Keep a leading sign: "<105".
- Reference "70 - 99": ref_low "70", ref_high "99".  "< 100": ref_low "", ref_high "100".  "> 40": ref_low "40", ref_high "".
- If the reference is missing, depends on phase/age/pregnancy/condition (several ranges), or is only words, use "" for both.
- A test name can span two lines. The method (e.g. "Calculated", "CLIA", "HPLC") is not part of the name or unit.
- Skip: reference or interpretation tables, pregnancy/paediatric ranges, patient details, dates, IDs, phone numbers, page numbers, and tests without a numeric result.
- If unsure, leave the test out. If there are no results, return [].

Example TEXT:
Haemoglobin (Hb)
Photometric method
13.1 g/dL 12 - 15
TSH 2.940 uIU/mL 0.270-4.20 ECLIA
Vitamin B12 <105 pg/mL 222 - 1439
Example JSON:
[{{"test_name":"Haemoglobin (Hb)","value":"13.1","unit":"g/dL","ref_low":"12","ref_high":"15"}},
{{"test_name":"TSH","value":"2.940","unit":"uIU/mL","ref_low":"0.270","ref_high":"4.20"}},
{{"test_name":"Vitamin B12","value":"<105","unit":"pg/mL","ref_low":"222","ref_high":"1439"}}]

TEXT:
<<<
{text}
>>>"""


def _iter_objects(raw: str):
    """Yield every complete {...} in `raw`; survives prose around the JSON and truncated output."""
    dec, i = json.JSONDecoder(), 0
    while True:
        i = raw.find("{", i)
        if i == -1:
            return
        try:
            obj, end = dec.raw_decode(raw, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = end


def llm_items(chunk: str):
    last = None
    for attempt in range(2):
        try:
            raw = chat(SYSTEM, PROMPT.format(text=chunk), max_tokens=3000, temperature=0)
            return [o for o in _iter_objects(raw) if "test_name" in o]
        except Exception as e:  # network, quota, timeout ...
            last = e
            time.sleep(2)
    raise last


# ───────────────────────── rule-based reader (fallback + recall check) ─────────────────────────
_RESULT = re.compile(
    r"(?<![\w.])(?P<val>[<>]?\s*\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>%|/\S+|\d+[\^³]\d*/\S+|[A-Za-zµμ][^\s]*)?\s+"
    r"(?:[A-Za-z][A-Za-z\- ]{0,20}:\s*)?"
    r"(?P<ref>\d+(?:\.\d+)?\s*(?:-|–|to)\s*\d+(?:\.\d+)?|[<>]=?\s*\d+(?:\.\d+)?)"
    r"(?:\s+[A-Za-z]{1,12}){0,2}\s*$"
)
_METHOD = re.compile(
    r"oxidase|peroxidase|hexokinase|immunoassay|chemiluminescen|spectrophotom|impedance|cytometry|hplc|\beclia\b|"
    r"\bclia\b|\bcmia\b|\belisa\b|electrode|photometr|nephelometr|turbidimetr|^calculated$|\bmethod\b|^method\s*:|^machine\s*:",
    re.I)
_REFROW = re.compile(r"trimester|phase\b|pregnan|deficien|sufficien|goal|diabet|non-?diabetic|at risk|normal\b", re.I)


def _is_result_line(ln):
    return bool(_RESULT.search(ln))


def rule_items(chunk: str):
    lines = chunk.split("\n")
    offs, o = [], 0
    for ln in lines:
        offs.append(o)
        o += len(ln) + 1
    out = []
    for i, ln in enumerate(lines):
        m = _RESULT.search(ln.strip())
        if not m:
            continue
        shift = len(ln) - len(ln.lstrip())
        frag = ln.strip()[: m.start()].strip(" :-|")
        j, prev = i - 1, None
        while j >= 0 and j >= i - 4:  # walk back: skip method lines, take the first real line
            p = lines[j].strip()
            if not p:
                j -= 1
                continue
            if _is_result_line(p):
                break
            if _METHOD.search(p):
                j -= 1
                continue
            prev = p
            break
        if frag and _METHOD.search(frag):
            frag = ""  # "Fluoride Plasma, Glucose Oxidase-Peroxidase (GOD-POD)84 mg/dL ..." is a method, not a name
        name = frag
        if prev:
            if not frag:
                name = prev
            elif frag.startswith("(") or frag[:1].islower() or (
                    not re.search(r"\d|,", prev) and len(prev) <= 40 and not prev.endswith(")")):
                name = f"{prev} {frag}"
        name = re.sub(r"\s+", " ", name).strip(" :-|")
        if len(re.findall(r"[A-Za-z]", name)) < 3 or _REFROW.search(name):
            continue
        val = m.group("val")
        dm = NUM_RE.search(val)
        lo_hi = re.match(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", m.group("ref"))
        if lo_hi:
            lo, hi = float(lo_hi.group(1)), float(lo_hi.group(2))
        else:
            c = re.match(r"([<>])=?\s*(\d+(?:\.\d+)?)", m.group("ref"))
            lo, hi = (None, float(c.group(2))) if c.group(1) == "<" else (float(c.group(2)), None)
        out.append({"name": name, "value": float(dm.group().replace(",", "")), "unit": m.group("unit") or "",
                    "qualifier": val.strip()[:1] if val.strip()[:1] in "<>" else "",
                    "ref_low": lo, "ref_high": hi, "pos": offs[i] + shift + m.start("val") + dm.start()})
    return out


# ───────────────────────── chunking ─────────────────────────
_RANGE_ANY = re.compile(r"\d\s*(?:-|–|to)\s*\d|[<>]=?\s*\d")


def strip_repeated(pages):
    """Drop headers/footers that repeat on 3+ pages (saves tokens and keeps patient details out of the prompt)."""
    cnt = Counter(l.strip() for p in pages for l in set(p.split("\n")) if l.strip())
    return [
        "\n".join(l for l in p.split("\n") if not (cnt[l.strip()] >= 3 and len(l) < 120 and not _is_result_line(l.strip())))
        for p in pages
    ]


def make_chunks(pages, max_chars=4500, overlap_lines=3):
    lines = [l for p in pages for l in p.split("\n")]
    chunks, cur, size = [], [], 0
    for ln in lines:
        if size + len(ln) + 1 > max_chars and cur:
            chunks.append("\n".join(cur))
            cur = cur[-overlap_lines:]
            size = sum(len(x) + 1 for x in cur)
        cur.append(ln)
        size += len(ln) + 1
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if len(_RANGE_ANY.findall(c)) >= 2]  # skip terms & conditions, ads, etc.


# ───────────────────────── main entry ─────────────────────────
def _process_chunk(chunk):
    low, nums = chunk.lower(), _nums(chunk.lower())
    accepted, dropped, used = [], [], set()
    llm_ok = True
    try:
        raw = llm_items(chunk)
    except Exception as e:
        log.warning("LLM failed on a chunk (%s); using rule-based reading for it", e)
        raw, llm_ok = [], False

    rules = rule_items(chunk)
    by_key = {(normalize_name(r["name"]), r["value"]): r for r in rules}
    for it in raw:
        name = str(it.get("test_name") or "").strip()
        v = to_float(it.get("value"))
        if not name or v is None:
            continue
        g = ground(name, v, str(it.get("unit") or ""), to_float(it.get("ref_low")), to_float(it.get("ref_high")),
                   chunk, low, nums)
        if g is None:
            dropped.append(name)
            continue
        if g["refs_dropped"] and (r := by_key.get((normalize_name(name), v))):
            # the AI's reference range is not in the text: use the one the rule reader parsed from it
            g.update(pos=r["pos"], ref_low=r["ref_low"], ref_high=r["ref_high"], qualifier=r["qualifier"],
                     unit=r["unit"] or g["unit"], refs_dropped=False)
        if g["pos"] in used:
            continue
        used.add(g["pos"])
        accepted.append({**g, "name": name, "source": "ai"})

    rule_added = 0
    for r in rules:
        if r["pos"] in used:
            continue
        used.add(r["pos"])
        accepted.append({**r, "source": "rule", "refs_dropped": False})
        rule_added += 1
    return accepted, dropped, llm_ok, rule_added


def analyze_report(pages, form_date: str | None):
    full = "\n".join(pages)
    chunks = make_chunks(strip_repeated(pages))
    workers = max(1, int(os.getenv("LLM_CONCURRENCY", "2")))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        outs = list(ex.map(_process_chunk, chunks))  # keeps page order

    results, seen = [], set()
    notes = {"dropped": [], "refs_unverified": [], "rule_added": 0, "ai_failed_chunks": 0, "chunks": len(chunks)}
    for accepted, dropped, llm_ok, rule_added in outs:
        notes["dropped"] += dropped
        notes["rule_added"] += rule_added
        notes["ai_failed_chunks"] += 0 if llm_ok else 1
        for r in accepted:
            name = normalize_name(r["name"])
            if not name:
                continue
            row = {"test_name": name, "value": r["value"], "qualifier": r.get("qualifier", ""), "unit": r["unit"],
                   "ref_low": r["ref_low"], "ref_high": r["ref_high"],
                   "status": compute_status(name, r["value"], r["ref_low"], r["ref_high"])}
            if name in seen:
                # same test twice (summary page + lab page): keep the first, unless the later one has a range and it doesn't
                i = next(k for k, x in enumerate(results) if x["test_name"] == name)
                if results[i]["ref_low"] is None and results[i]["ref_high"] is None and (
                        row["ref_low"] is not None or row["ref_high"] is not None):
                    results[i] = row
                    if name in notes["refs_unverified"]:
                        notes["refs_unverified"].remove(name)
                continue
            seen.add(name)
            if r["refs_dropped"]:
                notes["refs_unverified"].append(name)
            results.append(row)
    notes["rejected"] = len(notes["dropped"])  # every row the AI proposed that the text did not back up
    notes["dropped"] = sorted({n for n in notes["dropped"] if normalize_name(n) not in seen})
    notes["mode"] = "rules" if chunks and notes["ai_failed_chunks"] == len(chunks) else "ai"
    date = norm_date(form_date) or guess_date(full) or dt.date.today().isoformat()
    return date, results, notes


# ───────────────────────── explanation ─────────────────────────
def _loose_json(s: str):
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object")
    return json.loads(s[start : end + 1])


EXPLAIN_SYSTEM = (
    "You are a careful health-information assistant writing for a patient in plain language. "
    "You never diagnose, never recommend prescription drugs or doses, and you always encourage "
    "discussing abnormal results with a doctor. Output valid JSON only."
)
EXPLAIN_PROMPT = """These lab results are outside their reference range:
{items}

Return JSON in exactly this shape:
{{"overview": "2-3 sentence plain-language summary",
  "findings": [{{"test": "name exactly as given",
                 "meaning": "what this may indicate, 1-2 sentences",
                 "steps": ["up to 4 practical diet, lifestyle or follow-up steps"],
                 "see_doctor": "routine" or "soon" or "urgent"}}]}}
Only talk about the tests listed above and use only the numbers given. Do not add values.
"""


def explain(abnormal: list[dict], total: int) -> dict:
    if not abnormal:
        return {"overview": f"All {total} values with a reference range are within normal limits.", "findings": []}
    items = json.dumps(
        [{k: r[k] for k in ("test_name", "value", "unit", "ref_low", "ref_high", "status")} for r in abnormal],
        indent=1,
    )
    try:
        raw = chat(EXPLAIN_SYSTEM, EXPLAIN_PROMPT.format(items=items), max_tokens=2500)
    except Exception as e:
        log.warning("LLM explanation failed: %s", e)
        return {"overview": "The AI explanation is unavailable right now. Your extracted values are shown below.",
                "findings": []}
    try:
        data = _loose_json(raw)
    except ValueError:
        return {"overview": raw.strip()[:1500], "findings": []}

    known = {r["test_name"] for r in abnormal}
    findings = []
    for f in data.get("findings", []):
        if isinstance(f, dict) and f.get("test") in known:
            findings.append(
                {"test": f["test"],
                 "meaning": str(f.get("meaning", "")),
                 "steps": [str(s) for s in (f.get("steps") or [])][:4],
                 "see_doctor": f.get("see_doctor") if f.get("see_doctor") in ("routine", "soon", "urgent") else "soon"}
            )
    crit = {r["test_name"] for r in abnormal if r["status"] == "CRITICAL"}
    for f in findings:
        if f["test"] in crit:
            f["see_doctor"] = "urgent"
    return {"overview": str(data.get("overview", "")), "findings": findings}
