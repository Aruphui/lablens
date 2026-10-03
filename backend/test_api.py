"""End-to-end API test with the AI stubbed out.  Run:  python -m pytest -q   (or: python test_api.py)"""
import json
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["AUTH_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

import analyze  # noqa: E402
import llm  # noqa: E402
import main  # noqa: E402

analyze.time.sleep = lambda *_: None


def fake_chat(system, user, max_tokens=1200, temperature=0.1):
    if "same measurement" in system:  # the duplicate-grouping call
        return json.dumps([
            {"names": ["Homocysteine, Serum", "Plasma Homocysteine"], "into": "Homocysteine", "reason": "same"},
            {"names": ["Homocysteine, Serum", "Ghost Test"], "into": "Ghost Test", "reason": "invented name"},
            {"names": ["TSH", "Free T3"], "into": "TSH", "reason": "rules say these differ"},
        ])
    if "copy lab test results" in system:  # extraction: pretend the AI is down -> rule reader
        raise RuntimeError("down")
    return json.dumps({"overview": "ok", "findings": []})


analyze.chat = fake_chat
main.canon.chat = fake_chat

TEXT = {
    1: "Collected on 10/01/2025\nHomocysteine, Serum 18.2 umol/L 5.0 - 15.0\nTSH 2.9 uIU/mL 0.27 - 4.2\nFree T3 3.1 pg/mL 2.0 - 4.4\n",
    2: "Collected on 10/03/2026\nPlasma Homocysteine 12.0 umol/L 5.0 - 15.0\nTSH 3.1 uIU/mL 0.27 - 4.2\nFree T3 3.3 pg/mL 2.0 - 4.4\n",
    3: "Collected on 11/03/2026\nPlasma Homocysteine 9.0 umol/L 5.0 - 15.0\nTSH 3.0 uIU/mL 0.27 - 4.2\nFree T3 3.2 pg/mL 2.0 - 4.4\n",
}
cur = {"n": 1}
main.extract_pages = lambda data, name: [TEXT[cur["n"]]]

import db as _db  # noqa: E402
_db.init()
c = TestClient(main.app)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def upload(tok, n):
    cur["n"] = n
    r = c.post("/api/reports", files={"file": ("r.pdf", b"x", "application/pdf")}, headers=H(tok))
    assert r.status_code == 200, r.text
    return r.json()


def test_everything():
    # --- auth ---
    assert c.get("/api/reports").status_code == 401
    assert c.get("/api/reports", headers=H("garbage")).status_code == 401
    assert c.post("/api/auth/register", json={"name": "A", "email": "bad", "password": "longenough"}).status_code == 422
    assert c.post("/api/auth/register", json={"name": "A", "email": "a@x.com", "password": "short"}).status_code == 422
    r = c.post("/api/auth/register", json={"name": "Asha", "email": "A@x.com", "password": "correct horse"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert r.json()["user"]["email"] == "a@x.com"
    assert c.post("/api/auth/register", json={"name": "A2", "email": "a@x.com", "password": "correct horse"}).status_code == 409
    assert c.post("/api/auth/login", json={"email": "a@x.com", "password": "nope nope"}).status_code == 401
    ok = c.post("/api/auth/login", json={"email": " A@X.com ", "password": "correct horse"})
    assert ok.status_code == 200
    assert c.get("/api/auth/me", headers=H(tok)).json()["name"] == "Asha"
    for _ in range(10):
        c.post("/api/auth/login", json={"email": "thr@x.com", "password": "wrong wrong"})
    assert c.post("/api/auth/login", json={"email": "thr@x.com", "password": "wrong wrong"}).status_code == 429

    # --- reports + duplicate names ---
    upload(tok, 1)
    upload(tok, 2)
    names = {t["test_name"] for t in c.get("/api/tests", headers=H(tok)).json()}
    assert {"Homocysteine, Serum", "Plasma Homocysteine", "TSH", "Free T3"} <= names, names

    sug = c.post("/api/tests/suggestions/scan", headers=H(tok)).json()
    assert len(sug) == 1, sug  # invented-name group and TSH/Free T3 group were rejected by code
    assert sorted(sug[0]["names"]) == ["Homocysteine, Serum", "Plasma Homocysteine"]
    assert sug[0]["unit_mismatch"] is False

    # a second user sees none of it
    t2 = c.post("/api/auth/register", json={"name": "B", "email": "b@x.com", "password": "correct horse"}).json()["token"]
    assert c.get("/api/tests", headers=H(t2)).json() == []
    assert c.get("/api/tests/suggestions", headers=H(t2)).json() == []
    assert c.post(f"/api/tests/suggestions/{sug[0]['id']}/accept", json={}, headers=H(t2)).status_code == 404

    r = c.post(f"/api/tests/suggestions/{sug[0]['id']}/accept", json={"into": "Homocysteine"}, headers=H(tok))
    assert r.status_code == 200 and r.json()["merged"] == 2, r.text
    tr = c.get("/api/trends", params={"test": "Homocysteine"}, headers=H(tok)).json()
    assert [round(p["value"], 1) for p in tr] == [18.2, 12.0]
    assert tr[0]["status"] == "HIGH" and tr[1]["status"] == "NORMAL"
    assert c.get("/api/tests/suggestions", headers=H(tok)).json() == []

    # the merge is remembered: a new report using the old wording lands on the merged name
    rep = upload(tok, 3)
    assert "Homocysteine" in {x["test_name"] for x in rep["results"]}
    assert len(c.get("/api/trends", params={"test": "Homocysteine"}, headers=H(tok)).json()) == 3

    # manual merge + validation
    assert c.post("/api/tests/merge", json={"names": ["Nope"], "into": "X"}, headers=H(tok)).status_code == 400
    assert c.post("/api/tests/merge", json={"names": ["TSH"], "into": "tsh"}, headers=H(tok)).status_code == 422

    # dismissed groups are not offered again
    s2 = c.post("/api/tests/suggestions/scan", headers=H(tok)).json()
    assert s2 == []

    # --- legacy data claim ---
    legacy = "11111111-2222-3333-4444-555555555555"
    import db
    with db.conn() as cn:
        cn.execute("INSERT INTO reports(user_id,filename,report_date,summary) VALUES (?,?,?,?)", (legacy, "old.pdf", "2025-01-01", "{}"))
    t3 = c.post("/api/auth/register", json={"name": "C", "email": "c@x.com", "password": "correct horse", "legacy_uid": legacy}).json()["token"]
    assert [x["filename"] for x in c.get("/api/reports", headers=H(t3)).json()] == ["old.pdf"]

    # --- delete account ---
    assert c.post("/api/auth/delete", json={"password": "wrong wrong"}, headers=H(t3)).status_code == 401
    assert c.post("/api/auth/delete", json={"password": "correct horse"}, headers=H(t3)).status_code == 200
    assert c.get("/api/reports", headers=H(t3)).status_code == 401


def test_dismiss():
    tok = c.post("/api/auth/register", json={"name": "D", "email": "d@x.com", "password": "correct horse"}).json()["token"]
    upload(tok, 1)
    upload(tok, 2)
    s = c.post("/api/tests/suggestions/scan", headers=H(tok)).json()
    assert len(s) == 1
    assert c.post(f"/api/tests/suggestions/{s[0]['id']}/dismiss", headers=H(tok)).status_code == 200
    assert c.post("/api/tests/suggestions/scan", headers=H(tok)).json() == []
    assert len(c.get("/api/tests", headers=H(tok)).json()) == 4  # nothing was renamed


if __name__ == "__main__":
    test_everything()
    test_dismiss()
    print("all passed")
