import logging
import os
import re
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pathlib import Path  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import auth  # noqa: E402
import canon  # noqa: E402
import db  # noqa: E402
from analyze import analyze_report, compute_status, explain  # noqa: E402
from extract import extract_pages  # noqa: E402

logging.basicConfig(level=logging.INFO)
MAX_BYTES = 10 * 1024 * 1024
ALLOWED = (".pdf", ".png", ".jpg", ".jpeg", ".webp")


@asynccontextmanager
async def lifespan(_):
    db.init()
    yield


app = FastAPI(title="LabLens API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user(authorization: str | None = Header(None)) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    uid = auth.read_token(token) if token else None
    if uid is None or not db.user_by_id(uid):
        raise HTTPException(401, "Please sign in again.")
    return f"u{uid}"


# ───────────────────────── accounts ─────────────────────────
class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    legacy_uid: str | None = None


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    legacy_uid: str | None = None


def _session(uid: int, legacy: str | None):
    if legacy and re.fullmatch(r"[A-Za-z0-9-]{8,64}", legacy) and not re.fullmatch(r"u\d+", legacy):
        db.claim_legacy(f"u{uid}", legacy)  # reports made before accounts existed
    return {"token": auth.make_token(uid), "user": db.user_by_id(uid)}


@app.post("/api/auth/register")
def register(body: RegisterIn):
    email = body.email.strip().lower()
    if not auth.EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    name = re.sub(r"\s+", " ", body.name).strip()
    if not name:
        raise HTTPException(422, "Enter your name.")
    uid = db.create_user(email, name, auth.hash_password(body.password))
    if uid is None:
        raise HTTPException(409, "An account with this email already exists. Try signing in.")
    return _session(uid, body.legacy_uid)


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    email = body.email.strip().lower()
    key = f"{email}|{request.client.host if request.client else '-'}"
    if auth.throttled(key):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    u = db.user_by_email(email)
    # verify against a dummy hash when the email is unknown so timing does not reveal which emails exist
    ok = auth.verify_password(body.password, u["pw_hash"] if u else _DUMMY)
    if not (u and ok):
        auth.record_fail(key)
        raise HTTPException(401, "Email or password is incorrect.")
    auth.clear_fails(key)
    return _session(u["id"], body.legacy_uid)


_DUMMY = auth.hash_password("not-a-real-password")


@app.get("/api/auth/me")
def me(user: str = Depends(current_user)):
    return db.user_by_id(int(user[1:]))


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=128)


@app.post("/api/auth/delete")
def delete_account(body: DeleteAccountIn, user: str = Depends(current_user)):
    u = db.user_by_email(db.user_by_id(int(user[1:]))["email"])
    if not auth.verify_password(body.password, u["pw_hash"]):
        raise HTTPException(401, "Password is incorrect.")
    db.delete_user(u["id"])
    return {"ok": True}


# ───────────────────────── reports ─────────────────────────
@app.post("/api/reports")
def create_report(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    report_date: str | None = Form(None),
    user: str = Depends(current_user),
):
    filename = file.filename or "report"
    if not filename.lower().endswith(ALLOWED):
        raise HTTPException(415, "Upload a PDF, PNG, JPG or WEBP file.")
    data = file.file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 10 MB.")

    try:
        pages = extract_pages(data, filename)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    if sum(len(p.strip()) for p in pages) < 20:
        raise HTTPException(422, "No readable text found in this file.")

    date, results, notes = analyze_report(pages, report_date)
    if not results:
        raise HTTPException(422, "No numeric test results were found. Try a clearer copy of the report.")

    results = canon.apply_aliases(results, db.get_aliases(user))  # names the user already merged
    abnormal = [r for r in results if r["status"] in ("HIGH", "LOW", "CRITICAL")]
    summary = explain(abnormal, len(results))
    summary["extraction"] = notes
    # Only extracted values are stored; the uploaded file itself is discarded.
    rid = db.save_report(user, filename, date, summary, results)
    background.add_task(_scan, user)  # let the AI look for duplicate test names; the user confirms them later
    return db.get_report(user, rid)


@app.get("/api/reports")
def reports(user: str = Depends(current_user)):
    return db.list_reports(user)


@app.get("/api/reports/{report_id}")
def report(report_id: int, user: str = Depends(current_user)):
    r = db.get_report(user, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return r


@app.delete("/api/reports/{report_id}")
def remove_report(report_id: int, user: str = Depends(current_user)):
    if not db.delete_report(user, report_id):
        raise HTTPException(404, "Report not found")
    return {"ok": True}


@app.get("/api/tests")
def tests(user: str = Depends(current_user)):
    return db.list_tests(user)


@app.get("/api/trends")
def trends(test: str, user: str = Depends(current_user)):
    return db.trend(user, test)


# ───────────────────────── merging duplicate test names (AI suggests, user confirms) ─────────────────────────
def _scan(user: str) -> int:
    groups = canon.suggest_groups(db.tests_with_units(user), db.dismissed_keys(user))
    db.save_suggestions(user, groups)
    return len(groups)


@app.get("/api/tests/suggestions")
def suggestions(user: str = Depends(current_user)):
    return db.list_suggestions(user)


@app.post("/api/tests/suggestions/scan")
def scan_suggestions(user: str = Depends(current_user)):
    try:
        _scan(user)
    except Exception as e:
        logging.getLogger("lablens").warning("duplicate scan failed: %s", e)
        raise HTTPException(502, "The AI is unavailable right now. You can still merge tests by hand.")
    return db.list_suggestions(user)


class MergeIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=40)
    into: str = Field(min_length=1, max_length=80)


def _merge(user: str, names: list[str], into: str) -> dict:
    into = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f]", " ", into)).strip()
    if not into:
        raise HTTPException(422, "Enter a name for the merged test.")
    have = {t["test_name"] for t in db.list_tests(user)}
    names = list(dict.fromkeys(names))
    if any(n not in have for n in names):
        raise HTTPException(400, "One of those tests no longer exists. Refresh and try again.")
    if len(set(n.lower() for n in names) | {into.lower()}) < 2:
        raise HTTPException(422, "Pick at least two different tests to merge.")
    n = db.merge_tests(user, names, into, compute_status)
    return {"merged": n, "into": into}


@app.post("/api/tests/merge")
def merge(body: MergeIn, user: str = Depends(current_user)):
    return _merge(user, body.names, body.into)


class AcceptIn(BaseModel):
    into: str | None = Field(None, max_length=80)


@app.post("/api/tests/suggestions/{sid}/accept")
def accept(sid: int, body: AcceptIn, user: str = Depends(current_user)):
    s = db.get_suggestion(user, sid)
    if not s:
        raise HTTPException(404, "Suggestion not found")
    return _merge(user, s["names"], body.into or s["into"])


@app.post("/api/tests/suggestions/{sid}/dismiss")
def dismiss(sid: int, user: str = Depends(current_user)):
    if not db.dismiss_suggestion(user, sid):
        raise HTTPException(404, "Suggestion not found")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


# ───────────────────────── serve the built frontend (single-container deploys) ─────────────────────────
_static = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent.parent / "frontend" / "dist")).resolve()
if (_static / "index.html").exists():

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (_static / path).resolve()
        if path and f.is_file() and _static in f.parents:  # real asset (never escapes the folder)
            return FileResponse(f)
        return FileResponse(_static / "index.html")  # app routes fall back to the SPA
