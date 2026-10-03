import json
import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "labs.db")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS reports (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              filename TEXT,
              report_date TEXT NOT NULL,
              summary TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS results (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
              test_name TEXT NOT NULL,
              value REAL NOT NULL,
              unit TEXT,
              ref_low REAL,
              ref_high REAL,
              status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              pw_hash TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            -- names the user confirmed are the same test: alias (lower-case) -> canonical name
            CREATE TABLE IF NOT EXISTS aliases (
              user_id TEXT NOT NULL,
              alias TEXT NOT NULL,
              canonical TEXT NOT NULL,
              PRIMARY KEY (user_id, alias)
            );
            -- AI-proposed merges waiting for the user's yes/no
            CREATE TABLE IF NOT EXISTS merge_suggestions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              key TEXT NOT NULL,
              names TEXT NOT NULL,
              into_name TEXT NOT NULL,
              reason TEXT,
              unit_mismatch INTEGER DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'pending',
              UNIQUE (user_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, report_date);
            CREATE INDEX IF NOT EXISTS idx_results_test ON results(test_name);
            """
        )
        cols = {r["name"] for r in c.execute("PRAGMA table_info(results)")}
        if "qualifier" not in cols:  # migrate databases created by the first version
            c.execute("ALTER TABLE results ADD COLUMN qualifier TEXT DEFAULT ''")


def save_report(user_id, filename, report_date, summary: dict, results: list[dict]) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO reports(user_id, filename, report_date, summary) VALUES (?,?,?,?)",
            (user_id, filename, report_date, json.dumps(summary)),
        )
        rid = cur.lastrowid
        c.executemany(
            "INSERT INTO results(report_id,test_name,value,qualifier,unit,ref_low,ref_high,status) VALUES (?,?,?,?,?,?,?,?)",
            [
                (rid, r["test_name"], r["value"], r.get("qualifier", ""), r["unit"], r["ref_low"], r["ref_high"], r["status"])
                for r in results
            ],
        )
        return rid


def list_reports(user_id):
    with conn() as c:
        rows = c.execute(
            """
            SELECT r.id, r.filename, r.report_date,
                   COUNT(x.id) AS total,
                   COALESCE(SUM(CASE WHEN x.status IN ('HIGH','LOW','CRITICAL') THEN 1 ELSE 0 END),0) AS flagged
            FROM reports r LEFT JOIN results x ON x.report_id = r.id
            WHERE r.user_id = ?
            GROUP BY r.id ORDER BY r.report_date DESC, r.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_report(user_id, report_id):
    with conn() as c:
        r = c.execute(
            "SELECT id, filename, report_date, summary FROM reports WHERE id=? AND user_id=?",
            (report_id, user_id),
        ).fetchone()
        if not r:
            return None
        res = c.execute(
            "SELECT test_name, value, qualifier, unit, ref_low, ref_high, status FROM results WHERE report_id=? ORDER BY id",
            (report_id,),
        ).fetchall()
        out = dict(r)
        out["summary"] = json.loads(out["summary"] or "{}")
        out["results"] = [dict(x) for x in res]
        return out


def delete_report(user_id, report_id) -> bool:
    with conn() as c:
        cur = c.execute("DELETE FROM reports WHERE id=? AND user_id=?", (report_id, user_id))
        return cur.rowcount > 0


def list_tests(user_id):
    with conn() as c:
        rows = c.execute(
            """
            SELECT x.test_name, COUNT(*) AS n,
                   (SELECT x2.unit FROM results x2 JOIN reports r2 ON r2.id = x2.report_id
                     WHERE r2.user_id = r.user_id AND x2.test_name = x.test_name AND x2.unit != ''
                     ORDER BY r2.report_date DESC, x2.id DESC LIMIT 1) AS unit
            FROM results x JOIN reports r ON r.id = x.report_id
            WHERE r.user_id = ?
            GROUP BY x.test_name ORDER BY n DESC, x.test_name
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def trend(user_id, test_name):
    with conn() as c:
        rows = c.execute(
            """
            SELECT r.report_date AS date, x.value, x.qualifier, x.status, x.unit, x.ref_low, x.ref_high
            FROM results x JOIN reports r ON r.id = x.report_id
            WHERE r.user_id = ? AND x.test_name = ?
            ORDER BY r.report_date, r.id
            """,
            (user_id, test_name),
        ).fetchall()
        return [dict(r) for r in rows]


# ───────────────────────── accounts ─────────────────────────
def create_user(email, name, pw_hash):
    with conn() as c:
        try:
            cur = c.execute("INSERT INTO users(email,name,pw_hash) VALUES (?,?,?)", (email, name, pw_hash))
        except sqlite3.IntegrityError:
            return None
        return cur.lastrowid


def user_by_email(email):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(r) if r else None


def user_by_id(uid):
    with conn() as c:
        r = c.execute("SELECT id,email,name,created_at FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None


def claim_legacy(user_id: str, legacy_uid: str) -> int:
    """Attach reports made before accounts existed (random browser id) to the new account."""
    with conn() as c:
        cur = c.execute("UPDATE reports SET user_id=? WHERE user_id=?", (user_id, legacy_uid))
        return cur.rowcount


def delete_user(uid: int) -> None:
    with conn() as c:
        key = f"u{uid}"
        c.execute("DELETE FROM reports WHERE user_id=?", (key,))
        c.execute("DELETE FROM aliases WHERE user_id=?", (key,))
        c.execute("DELETE FROM merge_suggestions WHERE user_id=?", (key,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))


# ───────────────────────── test-name merging ─────────────────────────
def get_aliases(user_id) -> dict:
    with conn() as c:
        return {r["alias"]: r["canonical"] for r in c.execute(
            "SELECT alias, canonical FROM aliases WHERE user_id=?", (user_id,))}


def tests_with_units(user_id):
    """[{name, unit, n}] for the AI grouping step; unit is the most recent non-empty one."""
    return [{"name": t["test_name"], "unit": t["unit"] or "", "n": t["n"]} for t in list_tests(user_id)]


def merge_tests(user_id, names: list[str], into: str, status_fn) -> int:
    """Rename every result called one of `names` to `into`, remember the aliases, and drop
    same-report duplicates (keeping the row that has a reference range). Returns rows renamed."""
    names = list(dict.fromkeys(n for n in names if n))
    with conn() as c:
        ph = ",".join("?" * len(names))
        both = list(dict.fromkeys(names + [into]))
        rows = c.execute(
            f"""SELECT x.id, x.report_id, x.test_name, x.value, x.ref_low, x.ref_high
                FROM results x JOIN reports r ON r.id = x.report_id
                WHERE r.user_id=? AND x.test_name IN ({",".join("?" * len(both))})
                ORDER BY x.report_id, x.id""",
            (user_id, *both),
        ).fetchall()
        by_report: dict[int, list] = {}
        for r in rows:
            by_report.setdefault(r["report_id"], []).append(r)
        renamed = 0
        for items in by_report.values():
            ranked = sorted(items, key=lambda r: (r["ref_low"] is None and r["ref_high"] is None, r["id"]))
            keep, extra = ranked[0], ranked[1:]
            for e in extra:
                c.execute("DELETE FROM results WHERE id=?", (e["id"],))
            c.execute("UPDATE results SET test_name=?, status=? WHERE id=?",
                      (into, status_fn(into, keep["value"], keep["ref_low"], keep["ref_high"]), keep["id"]))
            renamed += 1
        for n in names:
            if n.lower() != into.lower():
                c.execute("INSERT OR REPLACE INTO aliases(user_id,alias,canonical) VALUES (?,?,?)",
                          (user_id, n.lower(), into))
        c.execute("DELETE FROM aliases WHERE user_id=? AND alias=?", (user_id, into.lower()))
        c.execute(f"UPDATE aliases SET canonical=? WHERE user_id=? AND canonical IN ({ph})", (into, user_id, *names))
        # any suggestion touching these names is settled now
        for s in c.execute("SELECT id, names FROM merge_suggestions WHERE user_id=? AND status='pending'", (user_id,)).fetchall():
            if set(json.loads(s["names"])) & set(names):
                c.execute("UPDATE merge_suggestions SET status='accepted' WHERE id=?", (s["id"],))
        return renamed


def _skey(names):
    return "|".join(sorted(n.lower() for n in names))


def save_suggestions(user_id, groups: list[dict]) -> None:
    """Replace pending suggestions; groups the user already dismissed/accepted are not offered again."""
    with conn() as c:
        c.execute("DELETE FROM merge_suggestions WHERE user_id=? AND status='pending'", (user_id,))
        for g in groups:
            c.execute(
                "INSERT OR IGNORE INTO merge_suggestions(user_id,key,names,into_name,reason,unit_mismatch) VALUES (?,?,?,?,?,?)",
                (user_id, _skey(g["names"]), json.dumps(g["names"]), g["into"], g.get("reason", ""),
                 1 if g.get("unit_mismatch") else 0),
            )


def dismissed_keys(user_id) -> set:
    with conn() as c:
        return {r["key"] for r in c.execute(
            "SELECT key FROM merge_suggestions WHERE user_id=? AND status='dismissed'", (user_id,))}


def list_suggestions(user_id):
    with conn() as c:
        out = []
        for r in c.execute("SELECT * FROM merge_suggestions WHERE user_id=? AND status='pending' ORDER BY id", (user_id,)):
            out.append({"id": r["id"], "names": json.loads(r["names"]), "into": r["into_name"],
                        "reason": r["reason"] or "", "unit_mismatch": bool(r["unit_mismatch"])})
        return out


def dismiss_suggestion(user_id, sid) -> bool:
    with conn() as c:
        cur = c.execute("UPDATE merge_suggestions SET status='dismissed' WHERE id=? AND user_id=?", (sid, user_id))
        return cur.rowcount > 0


def get_suggestion(user_id, sid):
    with conn() as c:
        r = c.execute("SELECT * FROM merge_suggestions WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
        return {"id": r["id"], "names": json.loads(r["names"]), "into": r["into_name"]} if r else None
