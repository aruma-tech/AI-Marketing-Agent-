"""scheduler.py - draft, approval, schedule and publish logic.

IMPORTANT: Colab is not an always-on server. Posts are published when you run
publish_due_posts() (or run_loop() while this notebook stays open).
Nothing is ever published without the owner pressing Approve.
"""
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import database as db
import ai_agent
import image_finder
import website_reader
import social_media

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
CREDIT_PATTERN = r"\n*📷 Photo by .* on Unsplash\s*$"


# ---------- Date and time helpers ----------
def parse_time(text):
    """'10:00 AM', '10am', '22:30' -> '10:00' / '22:30' (24 hour)."""
    match = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?\s*$", (text or "").lower())
    if not match:
        raise ValueError("Time must look like 10:00 AM or 22:30.")
    hour, minute, ampm = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError("Hour must be 1-12 when using AM/PM.")
        hour = hour % 12 + (12 if ampm == "p" else 0)
    if hour > 23 or minute > 59:
        raise ValueError("That time is not valid.")
    return "%02d:%02d" % (hour, minute)


def format_time(time24):
    hour, minute = map(int, time24.split(":"))
    return "%d:%02d %s" % (hour % 12 or 12, minute, "AM" if hour < 12 else "PM")


def resolve_schedule(day, date_text, time_text, now=None):
    """Return ('YYYY-MM-DD', 'HH:MM'). A typed date wins over the day name."""
    tz = ZoneInfo(config.TIMEZONE)
    now = now or datetime.now(tz)
    time24 = parse_time(time_text)
    hour, minute = map(int, time24.split(":"))
    if (date_text or "").strip():
        try:
            target = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Date must look like 2026-09-28 (year-month-day).")
    else:
        name = (day or "").strip().lower()
        if name == "today":
            target = now.date()
        elif name == "tomorrow":
            target = now.date() + timedelta(days=1)
        else:
            weekdays = [i for i, d in enumerate(DAYS) if len(name) >= 3 and d[:3] == name[:3]]
            if not weekdays:
                raise ValueError("Please choose a day or type a date.")
            gap = (weekdays[0] - now.weekday()) % 7
            target = now.date() + timedelta(days=gap)
            if gap == 0 and (hour, minute) <= (now.hour, now.minute):
                target += timedelta(days=7)          # today's time already passed
    when = datetime(target.year, target.month, target.day, hour, minute, tzinfo=tz)
    if when <= now:
        raise ValueError("That date and time has already passed (timezone %s)." % config.TIMEZONE)
    return target.isoformat(), time24


def _due_time(post):
    tz = ZoneInfo(config.TIMEZONE)
    return datetime.strptime("%s %s" % (post["Scheduled Date"], post["Scheduled Time"]),
                             "%Y-%m-%d %H:%M").replace(tzinfo=tz)


def _with_credit(caption, credit):
    caption = re.sub(CREDIT_PATTERN, "", caption).rstrip()
    return caption + ("\n\n📷 " + credit if credit else "")


def _check_caption(platform, caption):
    if not caption.strip():
        raise ValueError("The post text is empty.")
    if platform == "Instagram":
        if len(caption) > 2200:
            raise ValueError("Instagram captions can have at most 2200 characters.")
        if caption.count("#") > 30:
            raise ValueError("Instagram allows at most 30 hashtags.")


# ---------- Create a draft ----------
def create_draft(business_id, platform, language, instruction="", day="", date_text="",
                 time_text="10:00 AM", image_url="", post_id=None):
    """Write a post from the business information and save it as DRAFT."""
    business = db.get_business(business_id)
    if not business:
        return {"ok": False, "message": "Business not found."}
    if platform not in config.PLATFORMS:
        return {"ok": False, "message": "%s is not supported." % platform}
    if language not in config.LANGUAGES:
        return {"ok": False, "message": "Choose English, Urdu or Roman Urdu."}
    try:
        sched_date, sched_time = resolve_schedule(day, date_text, time_text)
    except ValueError as e:
        return {"ok": False, "message": str(e)}

    website = website_reader.get_website_info(business)
    history = db.recent_history(business_id)
    topics = [h["Topic/Content Reference"] for h in history]
    used = db.history_hashes(business_id)

    result = ai_agent.generate_post(business, website, platform, language, instruction, topics)
    if result["ok"] and db.content_hash(business_id, result["caption"]) in used:
        # Same text was used before: ask once more for something different
        result = ai_agent.generate_post(business, website, platform, language,
                                        (instruction + " Write a clearly different post.").strip(), topics)
        if result["ok"] and db.content_hash(business_id, result["caption"]) in used:
            return {"ok": False, "message": "The AI produced text that was already used. Try a different request."}
    if not result["ok"]:
        return {"ok": False, "message": result["message"],
                "needs_more_info": result.get("needs_more_info", False)}

    image = image_finder.find_image(result["image_query"], website, platform, image_url)
    caption = _with_credit(result["caption"], image.get("credit", ""))
    notes = result["message"]
    if not image["url"]:
        notes += " " + image.get("message", "")

    existing = db.get_post(post_id) if post_id else None
    fields = {"Business ID": business_id, "Business Name": business["Business Name"],
              "Platform": platform, "Language": language, "Post Content": caption,
              "Image URL": image["url"], "Status": "DRAFT", "Scheduled Date": sched_date,
              "Scheduled Time": sched_time, "Error Message": ""}
    if existing and existing["Status"] == "DRAFT" and existing["Business ID"] == business_id:
        db.update_post(post_id, fields)
        new_id = post_id
    else:
        new_id = db.save_post(dict(fields))
    post = db.get_post(new_id)
    post["_topic"], post["_image_query"] = result["topic"], result["image_query"]
    return {"ok": True, "post": post, "message": notes.strip()}


def change_image(post_id, caption):
    """Pick a different image for a draft. Returns dict with ok, image_url, caption."""
    post = db.get_post(post_id)
    if not post or post["Status"] != "DRAFT":
        return {"ok": False, "message": "Only DRAFT posts can change image."}
    business = db.get_business(post["Business ID"])
    website = website_reader.get_website_info(business)
    query = business.get("Business Type", "") or business["Business Name"]
    image = image_finder.find_image(query, website, post["Platform"], exclude=[post["Image URL"]])
    if not image["url"]:
        return {"ok": False, "message": image.get("message", "No other image found.")}
    caption = _with_credit(caption or post["Post Content"], image.get("credit", ""))
    db.update_post(post_id, {"Image URL": image["url"], "Post Content": caption})
    return {"ok": True, "image_url": image["url"], "caption": caption, "message": "Image changed."}


def save_edit(post_id, caption):
    post = db.get_post(post_id)
    if not post:
        return {"ok": False, "message": "Post not found."}
    if post["Status"] == "PUBLISHED":
        return {"ok": False, "message": "This post is already published."}
    try:
        _check_caption(post["Platform"], caption)
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    db.update_post(post_id, {"Post Content": caption})
    return {"ok": True, "message": "Edit saved."}


# ---------- Approve and schedule ----------
def _approve(post_id, caption):
    """Common approval checks. Returns (post, error_message)."""
    post = db.get_post(post_id)
    if not post:
        return None, "Post not found."
    if post["Status"] == "PUBLISHED":
        return None, "This post is already published."
    try:
        _check_caption(post["Platform"], caption)
    except ValueError as e:
        return None, str(e)
    if post["Platform"] == "Instagram" and not post["Image URL"]:
        return None, "Instagram needs an image. Use 'New image' or paste an image link and regenerate."
    # Duplicate check: a new or changed text must not match an earlier post
    new_hash = db.content_hash(post["Business ID"], caption)
    old_hash = db.content_hash(post["Business ID"], post["Post Content"])
    if (post["Status"] == "DRAFT" or new_hash != old_hash) and new_hash in db.history_hashes(post["Business ID"]):
        return None, "This exact post was already used before. Edit it or regenerate."
    post["Post Content"] = caption
    return post, ""


def approve_and_schedule(post_id, caption, day, date_text, time_text):
    post, error = _approve(post_id, caption)
    if error:
        return {"ok": False, "message": error}
    if not db.is_platform_connected(post["Business ID"], post["Platform"]):
        return {"ok": False, "message": "%s is not connected for this business. Open SOCIAL CONNECTIONS first." % post["Platform"]}
    try:
        post["Scheduled Date"], post["Scheduled Time"] = resolve_schedule(day, date_text, time_text)
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    db.update_post(post["Post ID"], {"Post Content": caption, "Status": "SCHEDULED",
                                     "Scheduled Date": post["Scheduled Date"],
                                     "Scheduled Time": post["Scheduled Time"], "Error Message": ""})
    db.upsert_schedule(post, day or post["Scheduled Date"])
    db.record_history(post, caption[:60], "SCHEDULED")
    return {"ok": True, "message": "Scheduled for %s at %s. It will be published when 'Publish due posts' runs." % (
        post["Scheduled Date"], format_time(post["Scheduled Time"]))}


def approve_and_publish_now(post_id, caption):
    post, error = _approve(post_id, caption)
    if error:
        return {"ok": False, "message": error}
    db.update_post(post_id, {"Post Content": caption, "Status": "APPROVED", "Error Message": ""})
    db.record_history(post, caption[:60], "APPROVED")
    ok, message = _publish_post(db.get_post(post_id), {})
    _mark_result(db.get_post(post_id), ok, message)
    return {"ok": ok, "message": message}


# ---------- Publishing ----------
def _publish_post(post, connection_cache):
    """Check connection, then publish. Returns (ok, message)."""
    platform, business_id = post["Platform"], post["Business ID"]
    if not db.is_platform_connected(business_id, platform):
        return False, "%s is not connected for this business." % platform
    if platform not in connection_cache:
        connection_cache[platform] = social_media.test_platform(platform)
    ok, message = connection_cache[platform]
    if not ok:
        return False, "%s connection failed: %s" % (platform, message)
    ok, message, _ = social_media.publish(platform, post["Post Content"], post["Image URL"])
    return ok, message


def _mark_result(post, ok, message):
    """Save PUBLISHED or FAILED (message is already free of secrets)."""
    status = "PUBLISHED" if ok else "FAILED"
    db.update_post(post["Post ID"], {
        "Status": status, "Error Message": "" if ok else config.safe_error(message)[:500],
        "Published At": db.now_text() if ok else ""})
    db.set_schedule_status(post["Post ID"], status)
    db.record_history(post, "", status)


def due_posts(now=None):
    now = now or datetime.now(ZoneInfo(config.TIMEZONE))
    due = []
    for post in db.all_posts_with_status("SCHEDULED"):
        try:
            if _due_time(post) <= now:
                due.append(post)
        except ValueError:
            continue
    return due


def publish_due_posts(dry_run=False):
    """Publish every SCHEDULED post whose time has come. Returns a list of results."""
    results, cache = [], {}
    for post in due_posts():
        line = {"post_id": post["Post ID"], "business": post["Business Name"],
                "platform": post["Platform"]}
        if dry_run:
            line.update(ok=None, message="DUE (dry run, not published)")
        else:
            ok, message = _publish_post(post, cache)
            _mark_result(post, ok, message)
            line.update(ok=ok, message=message)
        results.append(line)
    return results


def run_loop(check_every=60, max_minutes=60):
    """Keep checking for due posts while this notebook stays open."""
    end = time.time() + max_minutes * 60
    print("Scheduler loop started (every %ds, up to %d min). Stop with the notebook Stop button." % (
        check_every, max_minutes))
    while time.time() < end:
        for r in publish_due_posts():
            print(r["platform"], r["post_id"], "->", r["message"])
        time.sleep(check_every)


_bg = {"started": False}


def start_background(check_every=60):
    """Run the scheduler forever in a background thread. Safe to call once at
    app startup on an always-on server (Railway). Does nothing in Colab
    unless you call it yourself - Colab still uses run_loop() as before."""
    if _bg["started"]:
        return
    _bg["started"] = True
    import threading

    def loop():
        while True:
            try:
                for r in publish_due_posts():
                    print(r["platform"], r["post_id"], "->", r["message"])
            except Exception as e:
                print("Scheduler error:", e)
            time.sleep(check_every)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print("Background scheduler started (checks every %ds)." % check_every)
