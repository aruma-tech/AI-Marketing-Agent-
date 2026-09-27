"""app.py - simple Gradio dashboard: HOME, BUSINESS PROFILE, CREATE POST, AI CHAT,
SCHEDULE, POST HISTORY, SOCIAL CONNECTIONS, SETTINGS."""
import html
import inspect

import gradio as gr

import config
import database as db
import google_services as gs
import website_reader
import ai_agent
import social_media
import scheduler
from theme import CSS, RAW_CSS, HERO, STATUS_COLORS, make_theme

PROFILE_FIELDS = ["Business Name", "Owner Name", "Email", "Business Type", "Website URL",
                  "Description", "Products/Services", "Target Audience", "Contact Info",
                  "Preferred Language"]
DAY_CHOICES = ["Today", "Tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday",
               "Friday", "Saturday", "Sunday"]
TIME_CHOICES = ["%d:%02d %s" % ((m // 60) % 12 or 12, m % 60, "AM" if m < 720 else "PM")
                for m in range(0, 1440, 30)]



# Colors live in theme.py (change PRESET there)


def esc(value):
    """Make text safe to show inside HTML (business names, captions and links come from users)."""
    return html.escape(str(value or ""), quote=True)


def pill(status):
    return '<span class="pill" style="background:%s">%s</span>' % (
        STATUS_COLORS.get(status, "#64748b"), esc(status))


def fail(e):
    return "❌ " + config.safe_error(e)


def biz_choices():
    try:
        return [("%s (%s)" % (b["Business Name"], b["Business ID"]), b["Business ID"])
                for b in db.list_businesses()]
    except Exception:
        return []


def platform_choices(bid):
    """Only connected platforms. If none is connected yet, show all supported ones."""
    try:
        connected = db.connected_platforms(bid) if bid else []
    except Exception:
        connected = []
    return connected or list(config.PLATFORMS)


# ---------- HOME ----------
def home_view(bid):
    if not bid:
        return ('<div class="box">No business selected. Add one in <b>BUSINESS PROFILE</b> '
                'or import it from the Google Form.</div>')
    try:
        biz = db.get_business(bid)
        posts = db.list_posts(bid)
        counts = {s: sum(1 for p in posts if p["Status"] == s) for s in config.STATUSES}
        upcoming = sorted((p for p in posts if p["Status"] == "SCHEDULED"),
                          key=lambda p: (p["Scheduled Date"], p["Scheduled Time"]))
        connected = ", ".join(db.connected_platforms(bid)) or "none yet"
        cards = "".join('<div class="card" style="background:%s"><b>%d</b><span>%s</span></div>'
                        % (STATUS_COLORS[s], counts[s], s.title()) for s in config.STATUSES)
        text = '<h3 style="margin:6px 0">%s</h3><div class="cards">%s</div>' % (esc(biz["Business Name"]), cards)
        text += '<div class="box"><b>Connected platforms:</b> %s</div>' % esc(connected)
        if upcoming:
            n = upcoming[0]
            text += '<div class="box"><b>Next scheduled post:</b> %s on %s at %s</div>' % (
                esc(n["Platform"]), esc(n["Scheduled Date"]), scheduler.format_time(n["Scheduled Time"]))
        else:
            text += '<div class="box">No scheduled posts yet.</div>'
        missing = config.missing_secrets()
        if missing:
            text += '<div class="box warn">⚠️ Missing secrets: %s</div>' % esc(", ".join(missing))
        return text
    except Exception as e:
        return '<div class="box warn">%s</div>' % esc(fail(e))


# ---------- BUSINESS PROFILE ----------
def load_profile(bid):
    biz = db.get_business(bid) if bid else None
    values = [(biz or {}).get(f, "") for f in PROFILE_FIELDS]
    values[-1] = values[-1] or "English"
    return values


def new_dropdown(selected=None):
    choices = biz_choices()
    value = selected or (choices[0][1] if choices else None)
    return gr.Dropdown(choices=choices, value=value)


def save_new_business(*values):
    try:
        bid = db.save_business(dict(zip(PROFILE_FIELDS, values)))
        return "✅ Saved. Business ID: %s" % bid, new_dropdown(bid)
    except Exception as e:
        return fail(e), new_dropdown()


def update_business(bid, *values):
    try:
        if not bid:
            return "Select a business first."
        db.update_business(bid, dict(zip(PROFILE_FIELDS, values)))
        return "✅ Profile updated."
    except Exception as e:
        return fail(e)


def import_form():
    try:
        result = db.sync_form_responses()
        return ("✅ " if result["ok"] else "⚠️ ") + result["message"], new_dropdown()
    except Exception as e:
        return fail(e), new_dropdown()


def read_site(bid):
    try:
        biz = db.get_business(bid)
        if not biz:
            return "Select a business first."
        info = website_reader.get_website_info(biz, refresh=True)
        text = "**%s**\n\n" % info["message"]
        if info["ok"]:
            text += "Title: %s\n\nPages read: %d | Images found: %d | Emails: %s | Phones: %s\n\n" % (
                info["title"], len(info["pages"]), len(info["images"]),
                ", ".join(info["emails"]) or "-", ", ".join(info["phones"]) or "-")
            text += "Preview of what the agent will use:\n\n> " + info["text"][:700].replace("\n", "\n> ")
        return text
    except Exception as e:
        return fail(e)


# ---------- CREATE POST ----------
def preview_html(post):
    if not post:
        return ""
    image = ('<img src="%s" style="max-width:320px;border-radius:12px;margin-top:8px">' % esc(post["Image URL"])
             if post["Image URL"] else "<i>No image found yet</i>")
    return ('<div class="box"><b>POST PREVIEW</b><br>Platform: <b>%s</b> | Language: <b>%s</b><br>'
            'Scheduled: %s, %s<br>Status: %s<br>%s</div>') % (
        esc(post["Platform"]), esc(post["Language"]), esc(post["Scheduled Date"]),
        scheduler.format_time(post["Scheduled Time"]), pill(post["Status"]), image)


def review_settings(bid, platform, language, day, date_text, time_text):
    if not bid:
        return "Select a business first.", gr.Group(visible=False)
    try:
        date, time24 = scheduler.resolve_schedule(day, date_text, time_text)
    except ValueError as e:
        return "❌ " + str(e), gr.Group(visible=False)
    warning = ""
    if platform not in db.connected_platforms(bid):
        warning = "\n\n⚠️ %s is not connected for this business. You can preview, but not publish." % platform
    text = ("### Please confirm\n**Platform:** %s\n\n**Language:** %s\n\n**Date:** %s\n\n"
            "**Time:** %s\n\nDo you want me to create the post using your business information?%s") % (
        platform, language, date, scheduler.format_time(time24), warning)
    return text, gr.Group(visible=True)


def _draft_outputs(result):
    """Turn a create_draft result into the values the screen needs."""
    if not result["ok"]:
        return "❌ " + result["message"], "", "", {}, gr.Group(visible=False)
    post = result["post"]
    state = {"post_id": post["Post ID"]}
    return ("✅ Draft ready. Read it, then Approve. Nothing is published yet. " + result["message"],
            preview_html(post), post["Post Content"], state, gr.Group(visible=True))


def create_post(bid, platform, language, day, date_text, time_text, instruction, image_url, state):
    try:
        result = scheduler.create_draft(bid, platform, language, instruction, day, date_text,
                                        time_text, image_url)
        return _draft_outputs(result)
    except Exception as e:
        return fail(e), "", "", {}, gr.Group(visible=False)


def regenerate(bid, platform, language, day, date_text, time_text, instruction, image_url, state):
    try:
        result = scheduler.create_draft(bid, platform, language, instruction, day, date_text,
                                        time_text, image_url, post_id=(state or {}).get("post_id"))
        return _draft_outputs(result)
    except Exception as e:
        return fail(e), "", "", state, gr.Group(visible=False)


def approve_schedule(state, caption, day, date_text, time_text):
    try:
        r = scheduler.approve_and_schedule((state or {}).get("post_id", ""), caption, day, date_text, time_text)
        return ("✅ " if r["ok"] else "❌ ") + r["message"]
    except Exception as e:
        return fail(e)


def approve_publish(state, caption):
    try:
        r = scheduler.approve_and_publish_now((state or {}).get("post_id", ""), caption)
        return ("✅ " if r["ok"] else "❌ ") + r["message"]
    except Exception as e:
        return fail(e)


def save_edit(state, caption):
    try:
        r = scheduler.save_edit((state or {}).get("post_id", ""), caption)
        return ("✅ " if r["ok"] else "❌ ") + r["message"]
    except Exception as e:
        return fail(e)


def new_image(state, caption):
    try:
        post_id = (state or {}).get("post_id", "")
        r = scheduler.change_image(post_id, caption)
        post = db.get_post(post_id)
        if not r["ok"]:
            return "❌ " + r["message"], preview_html(post), caption
        return "✅ Image changed.", preview_html(post), r["caption"]
    except Exception as e:
        return fail(e), "", caption


def ai_change(state, caption, request):
    try:
        post = db.get_post((state or {}).get("post_id", ""))
        if not post or not request.strip():
            return "Write what you want changed first.", caption
        ok, text = ai_agent.rewrite_post(caption, request, post["Platform"], post["Language"])
        return ("✅ Caption changed. Read it, then save/approve." if ok else "❌ " + text), (text if ok else caption)
    except Exception as e:
        return fail(e), caption


# ---------- AI CHAT ----------
def chat_send(bid, message, history):
    history = history or []
    if not bid:
        return "Select a business first.", "", history
    if not message.strip():
        return render_chat(history), "", history
    try:
        biz = db.get_business(bid)
        site = website_reader.get_website_info(biz)
        reply = ai_agent.chat(biz, site, history, message)
        history = history + [("user", message), ("assistant", reply)]
    except Exception as e:
        history = history + [("user", message), ("assistant", fail(e))]
    return render_chat(history), "", history


def render_chat(history):
    return "\n\n".join(("**You:** " if r == "user" else "**Agent:** ") + t for r, t in history)


def last_reply(history):
    replies = [t for r, t in (history or []) if r == "assistant"]
    return replies[-1] if replies else ""


# ---------- SCHEDULE / HISTORY ----------
def schedule_rows(bid):
    if not bid:
        return []
    posts = [p for p in db.list_posts(bid) if p["Status"] in ("SCHEDULED", "APPROVED", "FAILED")]
    posts.sort(key=lambda p: (p["Scheduled Date"], p["Scheduled Time"]))
    return [[p["Post ID"], p["Platform"], p["Language"], p["Scheduled Date"],
             scheduler.format_time(p["Scheduled Time"]) if p["Scheduled Time"] else "",
             p["Status"], p["Post Content"][:80]] for p in posts]


def run_due():
    try:
        results = scheduler.publish_due_posts()
        if not results:
            return "No posts are due right now."
        return "\n".join("%s %s (%s): %s" % ("✅" if r["ok"] else "❌", r["post_id"], r["platform"], r["message"])
                         for r in results)
    except Exception as e:
        return fail(e)


def history_rows(bid):
    if not bid:
        return []
    return [[p["Post ID"], p["Date"], p["Platform"], p["Language"], p["Status"],
             p["Scheduled Date"], p["Published At"], p["Post Content"][:80], p["Error Message"][:80]]
            for p in reversed(db.list_posts(bid))]


# ---------- SOCIAL CONNECTIONS ----------
def test_connections():
    return "\n\n".join(social_media.connection_lines(social_media.test_social_connections(show=False)))


def connect_accounts(bid):
    if not bid:
        return "Select a business first.", []
    results = social_media.test_social_connections(show=False)
    for name, r in results.items():
        db.set_social_account(bid, name, r["label"], "CONNECTED" if r["ok"] else "FAILED",
                              "" if r["ok"] else r["message"][:150])
    text = "\n\n".join(social_media.connection_lines(results))
    return text + "\n\nSaved for this business.", account_rows(bid)


def account_rows(bid):
    if not bid:
        return []
    return [[a["Platform"], a["Account Label"], a["Status"], a["Last Tested"], a["Notes"]]
            for a in db.get_social_accounts(bid)]


# ---------- SETTINGS ----------
def settings_view():
    lines = ["### Secrets (values are never shown)"]
    for name, ok in config.secret_status().items():
        optional = " (optional)" if name in config.OPTIONAL_SECRETS else ""
        lines.append("- %s%s: %s" % (name, optional, "OK" if ok else "missing"))
    lines.append("\n**AI model:** %s\n\n**Timezone:** %s" % (config.GEMINI_MODEL, config.TIMEZONE))
    try:
        lines.append("\n**Google Sheet:** %s" % db.spreadsheet().url)
        lines.append("\n**Google Form connected:** %s" % ("yes" if db.form_tab() else "no - see the setup script below"))
    except Exception as e:
        lines.append("\nSheet not available: " + config.safe_error(e))
    return "\n".join(lines)


# ---------- Build the screen ----------
def _accepts(func, name):
    """True if this function has a parameter with that name (works across Gradio versions)."""
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def _blocks():
    """Create the page. Gradio 5: theme/css go in Blocks(). Gradio 6: they go in launch()."""
    kwargs = {"title": "AI Marketing Agent"}
    if _accepts(gr.Blocks.__init__, "theme"):
        theme = make_theme()
        if theme is not None:
            kwargs["theme"] = theme
    if _accepts(gr.Blocks.__init__, "css"):
        kwargs["css"] = RAW_CSS
    return gr.Blocks(**kwargs)


def build_ui():
    with _blocks() as demo:
        gr.HTML(CSS + HERO)
        with gr.Row():
            biz = gr.Dropdown(choices=biz_choices(), label="Business", scale=4,
                              value=(biz_choices()[0][1] if biz_choices() else None))
            refresh_btn = gr.Button("↻ Refresh list", scale=1)
        refresh_btn.click(new_dropdown, outputs=biz)

        with gr.Tabs():
            # HOME
            with gr.Tab("HOME"):
                home = gr.HTML()
                home_btn = gr.Button("Refresh")
                home_btn.click(home_view, biz, home)
                biz.change(home_view, biz, home)

            # BUSINESS PROFILE
            with gr.Tab("BUSINESS PROFILE"):
                prof = [gr.Textbox(label=f, lines=3 if f in ("Description", "Products/Services") else 1)
                        for f in PROFILE_FIELDS[:-1]]
                prof.append(gr.Dropdown(config.LANGUAGES, value="English", label="Preferred Language"))
                prof_msg = gr.Markdown()
                with gr.Row():
                    gr.Button("Load selected business").click(load_profile, biz, prof)
                    gr.Button("Save as NEW business").click(save_new_business, prof, [prof_msg, biz])
                    gr.Button("Update selected business").click(update_business, [biz] + prof, prof_msg)
                with gr.Row():
                    gr.Button("Import from Google Form").click(import_form, None, [prof_msg, biz])
                    gr.Button("Test: read website").click(read_site, biz, prof_msg)

            # CREATE POST
            with gr.Tab("CREATE POST"):
                gr.Markdown("**Step 1:** choose settings. **Step 2:** confirm. **Step 3:** read the preview and approve.")
                with gr.Row():
                    platform = gr.Dropdown(platform_choices(None), label="Which social media account do you want to post on?",
                                           value=platform_choices(None)[0])
                    language = gr.Dropdown(config.LANGUAGES, value="English", label="What language do you want for this post?")
                with gr.Row():
                    day = gr.Dropdown(DAY_CHOICES, value="Tomorrow", label="Day")
                    date_text = gr.Textbox(label="Or exact date (YYYY-MM-DD, optional)")
                    time_text = gr.Dropdown(TIME_CHOICES, value="10:00 AM", allow_custom_value=True, label="Time")
                instruction = gr.Textbox(label="What should the post be about? (optional)", lines=2,
                                         placeholder="Example: create a post about my new course")
                image_url = gr.Textbox(label="Your own image link (optional, public JPEG for Instagram)")
                biz.change(lambda b: gr.Dropdown(choices=platform_choices(b), value=platform_choices(b)[0]),
                           biz, platform)
                review_btn = gr.Button("1. Review settings", variant="primary")
                with gr.Group(visible=False) as confirm_box:
                    confirm_md = gr.Markdown()
                    with gr.Row():
                        confirm_btn = gr.Button("✅ Confirm - create the post", variant="primary")
                        change_btn = gr.Button("✏️ Change settings")
                status = gr.Markdown()
                state = gr.State({})
                with gr.Group(visible=False) as preview_box:
                    preview = gr.HTML()
                    caption = gr.Textbox(label="Caption (you can edit it)", lines=10)
                    with gr.Row():
                        approve_btn = gr.Button("✅ Approve & Schedule", variant="primary")
                        publish_btn = gr.Button("🚀 Approve & Publish now")
                        edit_btn = gr.Button("💾 Save edit")
                        regen_btn = gr.Button("🔄 Regenerate (uses settings above)")
                        image_btn = gr.Button("🖼️ New image")
                    ai_request = gr.Textbox(label="Ask AI to change this caption",
                                            placeholder="Example: make it shorter / write in professional English")
                    ai_btn = gr.Button("Apply AI change")
                    gr.Markdown("To **change platform, language or schedule**: change the settings above, then press "
                                "Regenerate (platform/language) or Approve & Schedule (day/time).")

                settings = [biz, platform, language, day, date_text, time_text, instruction, image_url, state]
                draft_out = [status, preview, caption, state, preview_box]
                review_btn.click(review_settings, [biz, platform, language, day, date_text, time_text],
                                 [confirm_md, confirm_box])
                change_btn.click(lambda: gr.Group(visible=False), None, confirm_box)
                confirm_btn.click(create_post, settings, draft_out)
                regen_btn.click(regenerate, settings, draft_out)
                approve_btn.click(approve_schedule, [state, caption, day, date_text, time_text], status)
                publish_btn.click(approve_publish, [state, caption], status)
                edit_btn.click(save_edit, [state, caption], status)
                image_btn.click(new_image, [state, caption], [status, preview, caption])
                ai_btn.click(ai_change, [state, caption, ai_request], [status, caption])

            # AI CHAT
            with gr.Tab("AI CHAT"):
                gr.Markdown("Ask about your business or marketing. The agent answers from your stored business information.")
                chat_view = gr.Markdown()
                chat_state = gr.State([])
                chat_box = gr.Textbox(label="Your message", lines=2)
                with gr.Row():
                    send_btn = gr.Button("Send", variant="primary")
                    clear_btn = gr.Button("Clear")
                    use_btn = gr.Button("Use last reply as post request")
                send_btn.click(chat_send, [biz, chat_box, chat_state], [chat_view, chat_box, chat_state])
                chat_box.submit(chat_send, [biz, chat_box, chat_state], [chat_view, chat_box, chat_state])
                clear_btn.click(lambda: ("", []), None, [chat_view, chat_state])
                use_btn.click(last_reply, chat_state, instruction)

            # SCHEDULE
            with gr.Tab("SCHEDULE"):
                gr.Markdown("Times use **%s**. Colab is not an always-on server: posts are published when you press "
                            "the button below (or run the scheduler loop in the notebook)." % config.TIMEZONE)
                sched_table = gr.Dataframe(headers=["Post ID", "Platform", "Language", "Date", "Time", "Status", "Content"],
                                           interactive=False, wrap=True)
                due_msg = gr.Markdown()
                with gr.Row():
                    gr.Button("Refresh").click(schedule_rows, biz, sched_table)
                    gr.Button("Publish due posts now", variant="primary").click(run_due, None, due_msg)

            # POST HISTORY
            with gr.Tab("POST HISTORY"):
                hist_table = gr.Dataframe(headers=["Post ID", "Date", "Platform", "Language", "Status",
                                                   "Scheduled", "Published", "Content", "Error"],
                                          interactive=False, wrap=True)
                gr.Button("Refresh").click(history_rows, biz, hist_table)

            # SOCIAL CONNECTIONS
            with gr.Tab("SOCIAL CONNECTIONS"):
                gr.Markdown("The Facebook/Instagram secrets in Colab belong to ONE Page. Connect them only to the "
                            "business that owns that Page. Instagram must be a Business/Creator account linked to it.")
                conn_msg = gr.Markdown()
                acc_table = gr.Dataframe(headers=["Platform", "Account", "Status", "Last tested", "Notes"],
                                         interactive=False, wrap=True)
                with gr.Row():
                    gr.Button("Test connections").click(test_connections, None, conn_msg)
                    gr.Button("Test and connect to selected business", variant="primary").click(
                        connect_accounts, biz, [conn_msg, acc_table])

            # SETTINGS
            with gr.Tab("SETTINGS"):
                settings_md = gr.Markdown()
                gr.Button("Refresh").click(settings_view, None, settings_md)
                with gr.Accordion("Google Form setup script (one time)", open=False):
                    try:
                        gr.Code(value=gs.form_setup_steps(db.spreadsheet().id), language="javascript")
                    except Exception:
                        gr.Markdown("Sheet not available yet.")

        demo.load(home_view, biz, home)
        demo.load(settings_view, None, settings_md)
    return demo


def launch(share=True):
    """Start the dashboard.

    In Colab: share=True opens a temporary public tunnel link, same as before.
    On a server (Railway etc.): set the RAILWAY_ENVIRONMENT env var (Railway
    sets this automatically) and it instead binds to 0.0.0.0:$PORT, which is
    what Railway requires, and skips the Colab-style tunnel.
    Set APP_PASSWORD (Colab Secret or Railway variable) to protect it (user: admin).
    """
    import os
    db.setup()
    try:
        scheduler.start_background()
    except Exception as e:
        print("NOTE: scheduler did not start:", config.safe_error(e))
    demo = build_ui()
    auth = ("admin", config.APP_PASSWORD) if config.APP_PASSWORD else None
    if auth is None:
        print("NOTE: no APP_PASSWORD secret set - anyone with the link can open this dashboard.")

    on_server = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PORT"))
    options = {"auth": auth, "debug": True}
    if on_server:
        options["share"] = False
        options["server_name"] = "0.0.0.0"
        options["server_port"] = int(os.environ.get("PORT", 7860))
    else:
        options["share"] = share

    if _accepts(demo.launch, "theme"):            # Gradio 6
        theme = make_theme()
        if theme is not None:
            options["theme"] = theme
    if _accepts(demo.launch, "css"):              # Gradio 6
        options["css"] = RAW_CSS
    demo.launch(**options)


if __name__ == "__main__":
    launch()
