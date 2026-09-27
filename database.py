"""database.py - Google Sheet is our simple database.

Rules that keep businesses separate:
  * Every tab (except Users) has a 'Business ID' column.
  * Read functions filter by Business ID first.
Rows are always built from the header names, so columns can never shift.
"""
import re
import uuid
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import google_services as gs

TABS = {
    "Users": ["User ID", "Name", "Email", "Created At"],
    "Businesses": ["Business ID", "User ID", "Business Name", "Owner Name", "Email",
                   "Business Type", "Website URL", "Description", "Products/Services",
                   "Target Audience", "Contact Info", "Preferred Language", "Created At"],
    "Social Accounts": ["Business ID", "Platform", "Account Label", "Status",
                        "Last Tested", "Notes"],
    "Posts": ["Post ID", "Date", "Business ID", "Business Name", "Platform", "Language",
              "Post Content", "Image URL", "Status", "Scheduled Date", "Scheduled Time",
              "Error Message", "Published At"],
    "Schedule": ["Schedule ID", "Post ID", "Business ID", "Platform", "Day",
                 "Scheduled Date", "Scheduled Time", "Status"],
    "Content History": ["Date", "Business ID", "Topic/Content Reference", "Platform",
                        "Language", "Post Status", "Content Hash"],
}

# Google Form question title -> Businesses column
FORM_TO_BUSINESS = {
    "Business Name": "Business Name",
    "Owner Name": "Owner Name",
    "Email": "Email",
    "Business Type": "Business Type",
    "Website URL": "Website URL",
    "Business Description": "Description",
    "Main Products / Services": "Products/Services",
    "Target Audience": "Target Audience",
    "Contact Information": "Contact Info",
    "Preferred Language": "Preferred Language",
}

_cache = {"sh": None, "ws": {}}


# ---------- Small helpers ----------
def now_text():
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M")


def today_text():
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")


def new_id(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:6])


def content_hash(business_id, text):
    """Same text (ignoring case, spaces, punctuation) gives the same hash."""
    clean = re.sub(r"[\W_]+", "", (text or "").lower())
    return hashlib.sha1((business_id + "|" + clean).encode("utf-8")).hexdigest()[:16]


# ---------- Sheet setup ----------
def spreadsheet():
    if _cache["sh"] is None:
        _cache["sh"] = gs.open_or_create_spreadsheet()
    return _cache["sh"]


def setup():
    """Create all tabs with headers. Safe to run many times."""
    sh = spreadsheet()
    existing = {w.title: w for w in sh.worksheets()}
    for tab, headers in TABS.items():
        ws = existing.get(tab)
        if ws is None:
            ws = sh.add_worksheet(title=tab, rows=1000, cols=max(len(headers), 10))
        first = ws.row_values(1)
        if not first:
            ws.batch_update([{"range": "A1", "values": [headers]}])
            ws.freeze(rows=1)
        elif first[:len(headers)] != headers:
            raise ValueError("Tab '%s' has different column names than the project expects. "
                             "Rename or delete that tab and run setup again." % tab)
        _cache["ws"][tab] = ws
    # Remove the empty default tab that Google creates
    default = existing.get("Sheet1")
    if default is not None and "Sheet1" not in TABS:
        try:
            if not default.get_all_values():          # delete it only if it is empty
                sh.del_worksheet(default)
        except Exception:
            pass
    return sh


def _ws(tab):
    if tab not in TABS:
        raise KeyError("Unknown tab: %s" % tab)
    if tab not in _cache["ws"]:
        setup()
    return _cache["ws"][tab]


# ---------- Generic row functions ----------
def rows(tab, **filters):
    """Return rows as dicts. Example: rows('Posts', **{'Business ID': 'BUS-1'})"""
    values = _ws(tab).get_all_values()
    if not values:
        return []
    headers = values[0]
    out = []
    for number, raw in enumerate(values[1:], start=2):
        raw = raw + [""] * (len(headers) - len(raw))
        item = dict(zip(headers, raw))
        item["_row"] = number
        if all(item.get(k, "") == v for k, v in filters.items()):
            out.append(item)
    return out


def append(tab, data):
    """Add one row. Keys must be real column names (no silent mismatch)."""
    headers = TABS[tab]
    unknown = [k for k in data if k not in headers]
    if unknown:
        raise ValueError("Unknown column(s) for %s: %s" % (tab, unknown))
    row = ["" if data.get(h) is None else str(data.get(h)) for h in headers]
    _ws(tab).append_row(row, value_input_option="RAW", table_range="A1")


def update_where(tab, key_col, key_value, updates):
    """Update the FIRST row where key_col == key_value. Returns True if found."""
    from gspread.utils import rowcol_to_a1
    headers = TABS[tab]
    unknown = [k for k in updates if k not in headers]
    if unknown:
        raise ValueError("Unknown column(s) for %s: %s" % (tab, unknown))
    found = rows(tab, **{key_col: key_value})
    if not found:
        return False
    number = found[0]["_row"]
    batch = [{"range": rowcol_to_a1(number, headers.index(col) + 1),
              "values": [["" if val is None else str(val)]]}
             for col, val in updates.items()]
    _ws(tab).batch_update(batch, value_input_option="RAW")
    return True


def delete_where(tab, key_col, key_value):
    """Delete all rows where key_col == key_value (used to clean test data)."""
    found = rows(tab, **{key_col: key_value})
    for item in sorted(found, key=lambda r: r["_row"], reverse=True):
        _ws(tab).delete_rows(item["_row"])
    return len(found)


# ---------- Users and businesses ----------
def ensure_user(name, email):
    email = (email or "").strip().lower()
    if email:
        found = [u for u in rows("Users") if u["Email"].lower() == email]
        if found:
            return found[0]["User ID"]
    user_id = new_id("USR")
    append("Users", {"User ID": user_id, "Name": name, "Email": email, "Created At": now_text()})
    return user_id


def save_business(data):
    """Save a new business. Returns its Business ID."""
    row = {h: str(data.get(h) or "").strip() for h in TABS["Businesses"]}
    if not row["Business Name"]:
        raise ValueError("Business Name is required.")
    row["Business ID"] = row["Business ID"] or new_id("BUS")
    row["User ID"] = ensure_user(row["Owner Name"], row["Email"])
    row["Preferred Language"] = row["Preferred Language"] or "English"
    row["Created At"] = row["Created At"] or now_text()
    append("Businesses", row)
    return row["Business ID"]


def update_business(business_id, data):
    allowed = [h for h in TABS["Businesses"] if h not in ("Business ID", "User ID", "Created At")]
    updates = {k: str(v or "").strip() for k, v in data.items() if k in allowed}
    return update_where("Businesses", "Business ID", business_id, updates)


def list_businesses():
    return rows("Businesses")


def get_business(business_id):
    found = rows("Businesses", **{"Business ID": business_id})
    return found[0] if found else None


def form_tab():
    """Return the 'Form Responses' worksheet if the Google Form is linked."""
    for ws in spreadsheet().worksheets():
        if ws.title.startswith("Form Responses"):
            return ws
    return None


def sync_form_responses():
    """Copy new Google Form answers into the Businesses tab (no duplicates)."""
    ws = form_tab()
    if ws is None:
        return {"ok": False, "added": 0,
                "message": "The Google Form is not linked yet (no 'Form Responses' tab)."}
    values = ws.get_all_values()
    if len(values) < 2:
        return {"ok": True, "added": 0, "message": "No form responses yet."}
    headers = values[0]
    known = {(b["Email"].lower(), b["Business Name"].lower()) for b in list_businesses()}
    added = 0
    for raw in values[1:]:
        raw = raw + [""] * (len(headers) - len(raw))
        answer = dict(zip(headers, raw))
        data = {col: answer.get(title, "") for title, col in FORM_TO_BUSINESS.items()}
        social = answer.get("Social Media Page Links", "").strip()
        if social:
            data["Contact Info"] = (data["Contact Info"] + " | Social: " + social).strip(" |")
        data["Created At"] = answer.get("Timestamp", "")
        key = (data["Email"].strip().lower(), data["Business Name"].strip().lower())
        if not data["Business Name"].strip() or key in known:
            continue
        save_business(data)
        known.add(key)
        added += 1
    return {"ok": True, "added": added, "message": "Imported %d new business(es)." % added}


# ---------- Social accounts (names and status only - never tokens) ----------
def set_social_account(business_id, platform, label, status, notes=""):
    data = {"Business ID": business_id, "Platform": platform, "Account Label": label,
            "Status": status, "Last Tested": now_text(), "Notes": notes}
    for item in rows("Social Accounts", **{"Business ID": business_id, "Platform": platform}):
        # Update the existing row for this business + platform
        from gspread.utils import rowcol_to_a1
        headers = TABS["Social Accounts"]
        batch = [{"range": rowcol_to_a1(item["_row"], headers.index(c) + 1), "values": [[str(v)]]}
                 for c, v in data.items()]
        _ws("Social Accounts").batch_update(batch, value_input_option="RAW")
        return
    append("Social Accounts", data)


def get_social_accounts(business_id):
    return rows("Social Accounts", **{"Business ID": business_id})


def is_platform_connected(business_id, platform):
    return any(a["Platform"] == platform and a["Status"] == "CONNECTED"
               for a in get_social_accounts(business_id))


def connected_platforms(business_id):
    return [a["Platform"] for a in get_social_accounts(business_id)
            if a["Status"] == "CONNECTED" and a["Platform"] in config.PLATFORMS]


# ---------- Posts ----------
def save_post(post):
    if not post.get("Post ID"):
        post["Post ID"] = new_id("POST")
    post.setdefault("Date", today_text())
    post.setdefault("Status", "DRAFT")
    append("Posts", post)
    return post["Post ID"]


def get_post(post_id):
    found = rows("Posts", **{"Post ID": post_id})
    return found[0] if found else None


def update_post(post_id, updates):
    return update_where("Posts", "Post ID", post_id, updates)


def list_posts(business_id):
    return rows("Posts", **{"Business ID": business_id})


def all_posts_with_status(status):
    return rows("Posts", **{"Status": status})


# ---------- Schedule ----------
def upsert_schedule(post, day, status="SCHEDULED"):
    data = {"Post ID": post["Post ID"], "Business ID": post["Business ID"],
            "Platform": post["Platform"], "Day": day,
            "Scheduled Date": post["Scheduled Date"],
            "Scheduled Time": post["Scheduled Time"], "Status": status}
    if not update_where("Schedule", "Post ID", post["Post ID"], data):
        data["Schedule ID"] = new_id("SCH")
        append("Schedule", data)


def set_schedule_status(post_id, status):
    return update_where("Schedule", "Post ID", post_id, {"Status": status})


# ---------- Content history (duplicate check) ----------
def record_history(post, topic, status):
    """Add or update the history row for this post text."""
    digest = content_hash(post["Business ID"], post["Post Content"])
    existing = rows("Content History", **{"Business ID": post["Business ID"], "Content Hash": digest})
    if existing:
        update_where("Content History", "Content Hash", digest, {"Post Status": status})
    else:
        append("Content History", {
            "Date": today_text(), "Business ID": post["Business ID"],
            "Topic/Content Reference": topic or post["Post Content"][:60],
            "Platform": post["Platform"], "Language": post["Language"],
            "Post Status": status, "Content Hash": digest})


def recent_history(business_id, limit=15):
    return rows("Content History", **{"Business ID": business_id})[-limit:]


def history_hashes(business_id):
    return {h["Content Hash"] for h in rows("Content History", **{"Business ID": business_id})}
