"""
agent_adapter.py - bridge between the dashboard and your existing agent code.

Your notebook backend already has generate_draft(...) and publish_draft(...).
Put that code in backend.py (next to this file, WITHOUT the Colab-only lines
like auth.authenticate_user() / userdata.get -> use os.environ.get instead).
If backend.py is missing or fails to import, a demo stub is used so the
dashboard still works while you test the UI.
"""
import os, time

try:
    import backend  # your real code
    HAVE_BACKEND = True
except Exception as e:  # noqa
    print("[adapter] backend.py not loaded, using DEMO stub ->", e)
    HAVE_BACKEND = False


def _workspace(biz: dict) -> dict:
    """Map the dashboard business record to the dict your backend expects."""
    return {
        "workspace_id": biz["id"],
        "content_language": biz.get("language") or "English",
        "brand_tone": biz.get("tone") or "professional and friendly",
        "brand_instructions": biz.get("instructions") or "",
        "business_name": biz["name"],
        "brand_name": biz.get("brand_name") or biz["name"],
        "industry": biz.get("industry", ""),
        "target_audience": biz.get("audience", ""),
        "description": biz.get("description", ""),
        "default_cta": biz.get("cta", ""),
        "fb_page_id": biz.get("fb_page_id") or os.environ.get("FB_PAGE_ID"),
        "fb_page_access_token": biz.get("fb_token") or os.environ.get("FB_PAGE_ACCESS_TOKEN"),
        "ig_business_account_id": biz.get("ig_id") or os.environ.get("IG_BUSINESS_ACCOUNT_ID"),
    }


def make_draft(biz: dict, prompt: str) -> dict:
    """Returns {topic, cta, platforms, content:{facebook,instagram,linkedin}, image_path}"""
    if HAVE_BACKEND:
        products = biz.get("products") or []
        return backend.generate_draft(biz["id"], _workspace(biz), prompt, products)
    time.sleep(1)
    return {
        "topic": prompt[:80] or "Demo topic",
        "cta": biz.get("cta", ""),
        "platforms": ["facebook", "instagram"],
        "content": {
            "facebook": f"[DEMO] Facebook post for {biz['name']}: {prompt}",
            "instagram": f"[DEMO] Instagram caption for {biz['name']}: {prompt} #demo",
        },
        "image_path": None,
    }


def publish(biz: dict, draft: dict, platforms: list) -> dict:
    """Returns status dict like {'facebook': 'posted (id: ..)'}; any value starting with FAILED = failure."""
    if HAVE_BACKEND:
        status, _ = backend.publish_draft(_workspace(biz), draft, platforms)
        return status
    return {p: "posted (demo)" for p in platforms}
