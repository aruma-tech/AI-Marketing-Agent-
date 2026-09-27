"""tests.py - 11 automatic checks before starting the app.

Nothing is published. Test data is created with a 'ZZ TEST' name and deleted at the end.
"""
import config
import database as db
import google_services as gs
import website_reader
import ai_agent
import social_media
import scheduler

ctx = {}      # small memory shared between tests


def _t1():
    missing = config.missing_secrets()
    assert not missing, "Missing: %s" % ", ".join(missing)


def _t2():
    gs.get_gspread_client()


def _t3():
    sh = db.setup()
    ctx["sheet_id"] = sh.id
    ctx["sheet_url"] = sh.url


def _t4():
    assert db.form_tab() is not None, "No 'Form Responses' tab in the Sheet."


def _t5():
    ctx["bid"] = db.save_business({
        "Business Name": "ZZ TEST Business", "Owner Name": "Test Owner",
        "Email": "zz-test@example.com", "Business Type": ctx.get("type", "Test"),
        "Website URL": ctx.get("url", ""), "Preferred Language": "English",
        "Description": ctx.get("desc", ""), "Products/Services": ctx.get("prod", "")})
    assert db.get_business(ctx["bid"]), "Saved business could not be read back."


def _t6():
    business = db.get_business(ctx["bid"])
    info = website_reader.get_website_info(business, refresh=True)
    ctx["site"] = info
    assert info["ok"] and info["enough"], info["message"]


def _t7():
    ok, message = ai_agent.ping()
    assert ok, message


def _t8():
    business = db.get_business(ctx["bid"])
    result = ai_agent.generate_post(business, ctx["site"], "Facebook", "Roman Urdu",
                                    "Write a short post about our services.")
    assert result["ok"], result["message"]
    ctx["generated"] = result


def _t9():
    business = db.get_business(ctx["bid"])
    # Use the AI text if test 8 worked, otherwise a plain test text (so saving is still tested)
    text = ctx.get("generated", {}).get("caption") or "Test post text (not from the AI)"
    ctx["pid"] = db.save_post({
        "Business ID": ctx["bid"], "Business Name": business["Business Name"],
        "Platform": "Facebook", "Language": "Roman Urdu",
        "Post Content": text, "Image URL": ""})
    saved = db.get_post(ctx["pid"])
    assert saved and saved["Status"] == "DRAFT", "Post was not saved as DRAFT."


def _t10():
    results = social_media.test_social_connections(show=False)
    failed = ["%s: %s" % (n, r["message"]) for n, r in results.items() if not r["ok"]]
    assert not failed, " | ".join(failed)


def _t11():
    date, time24 = scheduler.resolve_schedule("Tomorrow", "", "10:00 AM")
    post = db.get_post(ctx["pid"])
    post["Scheduled Date"], post["Scheduled Time"] = date, time24
    db.update_post(ctx["pid"], {"Status": "SCHEDULED", "Scheduled Date": date,
                                "Scheduled Time": time24})
    db.upsert_schedule(post, "Tomorrow")
    rows = db.rows("Schedule", **{"Post ID": ctx["pid"]})
    assert rows and rows[0]["Scheduled Date"] == date, "Schedule row was not saved."


TESTS = [
    (1, "Required secrets exist", _t1, None,
     "One or more Colab Secrets are empty or Notebook access is OFF.",
     "Open the Secrets panel (key icon), add the name, paste the value, switch Notebook access ON, run again.", None),
    (2, "Google login works", _t2, None,
     "Google sign-in was cancelled or not allowed.",
     "Run again and click Allow in the Google popup (use the same account that owns your Drive).", None),
    (3, "Google Sheet opens with all 6 tabs", _t3, None,
     "Login is missing, or a tab has different column names.",
     "Run cell 4 again. If a tab has wrong columns, delete that tab in the Sheet and run again.", None),
    (4, "Google Form is connected to the Sheet", _t4, None,
     "The Form has not been created/linked to the Sheet yet.",
     "Create it with the Apps Script printed by cell 4 (google_services.form_setup_steps).", None),
    (5, "Business profile can be saved", _t5, None,
     "The Sheet is not reachable or the Businesses tab is wrong.",
     "Make sure test 3 passed, then run again.", 3),
    (6, "Website can be read", _t6, None,
     "The website is empty, offline, blocks bots (robots.txt / login / CAPTCHA) or has too little text.",
     "Use a public website with real text, or add the business description manually.", 5),
    (7, "AI model responds", _t7, None,
     "GEMINI_API_KEY is wrong, the model name is not available for your key, or the free limit is used up.",
     "Check the key in Google AI Studio and GEMINI_MODEL in config.py (the backup model gemini-3.5-flash-lite is tried automatically).", 1),
    (8, "Post can be generated", _t8, None,
     "The AI answered badly or there is not enough business/website information.",
     "Add a longer description and products/services, then run again.", 7),
    (9, "Post can be saved", _t9, None,
     "The Posts tab could not be written.",
     "Make sure test 3 passed and the Sheet is not full.", 5),
    (10, "Social connection test works", _t10, None,
     "Meta token expired, wrong Page/Instagram ID, or Instagram is not linked to the Page.",
     "Create a new long-lived Page token, check FB_PAGE_ID and IG_BUSINESS_ACCOUNT_ID, link Instagram Business to the Page.", None),
    (11, "Schedule can be saved", _t11, None,
     "The Schedule tab could not be written.",
     "Make sure tests 3 and 9 passed.", 9),
]


def _cleanup():
    """Delete the test rows so the Sheet stays clean."""
    try:
        bid = ctx.get("bid")
        if bid:
            for tab in ("Schedule", "Posts", "Content History", "Businesses"):
                db.delete_where(tab, "Business ID", bid)
            db.delete_where("Users", "Email", "zz-test@example.com")
    except Exception as e:
        print("(cleanup warning: %s)" % config.safe_error(e))


def _explain(error, cause, fix):
    """Give the REAL cause for temporary AI errors instead of the generic text."""
    text = str(error).lower()
    if "503" in text or "unavailable" in text or "high demand" in text:
        return ("Google's AI model is busy right now. This is temporary and not your mistake.",
                "Wait 2-5 minutes and run this cell again. The agent also tries a backup model automatically.")
    if "429" in text or "resource_exhausted" in text or "quota" in text:
        return ("The free AI limit was reached (per minute or per day).",
                "Wait a few minutes and run again. If it keeps happening, try again tomorrow.")
    return cause, fix


def run_all(website_url="", description="", products="", business_type="Test"):
    """Run all tests. website_url should be a real public website."""
    ctx.clear()
    ctx.update(url=website_url, desc=description, prod=products, type=business_type)
    passed = {}
    for number, name, func, _, cause, fix, needs in TESTS:
        if needs is not None and not passed.get(needs):
            print("SKIPPED  %2d. %s (needs test %d first)" % (number, name, needs))
            passed[number] = False
            continue
        try:
            func()
            passed[number] = True
            print("PASSED   %2d. %s" % (number, name))
        except Exception as e:
            passed[number] = False
            print("FAILED   %2d. %s" % (number, name))
            real_cause, real_fix = _explain(e, cause, fix) if number in (7, 8) else (cause, fix)
            print("   ERROR: %s" % config.safe_error(e))
            print("   CAUSE: %s" % real_cause)
            print("   FIX:   %s" % real_fix)
    _cleanup()
    total = sum(passed.values())
    print("\n%d of %d tests passed." % (total, len(TESTS)))
    return passed
