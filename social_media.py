"""social_media.py - Facebook Page and Instagram Business posting (Meta Graph API).

Facebook and Instagram use DIFFERENT flows:
  Facebook : one call  -> /{page-id}/feed  or  /{page-id}/photos
  Instagram: three steps -> create media container, wait until ready, publish it
Instagram needs an Instagram Business/Creator account linked to the Facebook Page,
and a public JPEG image URL (Instagram cannot post text-only).
"""
import time
import requests
import config

HINTS = {
    190: "The token is expired or invalid. Create a new Page access token and update the Colab secret.",
    10: "Missing permission. Check the token permissions (pages_manage_posts, instagram_content_publish).",
    200: "Missing permission. Check the token permissions (pages_manage_posts, instagram_content_publish).",
    368: "Facebook temporarily blocked this action.",
}


def _url(path):
    return "https://graph.facebook.com/%s/%s" % (config.GRAPH_VERSION, path)


def _graph(method, path, fields=None):
    """Call the Graph API. Returns (True, json) or (False, safe_error_text).
    The token is sent in the request body/params and is never printed."""
    payload = dict(fields or {})
    payload["access_token"] = config.FB_PAGE_ACCESS_TOKEN
    try:
        if method == "GET":
            resp = requests.get(_url(path), params=payload, timeout=30)
        else:
            resp = requests.post(_url(path), data=payload, timeout=60)
        data = resp.json()
    except Exception as e:
        return False, config.safe_error("Network problem: %s" % type(e).__name__)
    if "error" in data:
        err = data["error"]
        text = "Meta error %s: %s" % (err.get("code"), err.get("message", "unknown"))
        if err.get("code") in HINTS:
            text += " -> " + HINTS[err["code"]]
        return False, config.safe_error(text)
    return True, data


# ---------- Connection tests ----------
def test_facebook():
    missing = [n for n in ("FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID") if not getattr(config, n)]
    if missing:
        return {"ok": False, "message": "missing " + ", ".join(missing), "label": ""}
    ok, page = _graph("GET", config.FB_PAGE_ID, {"fields": "name,id"})
    if not ok:
        return {"ok": False, "message": page, "label": ""}
    ok, me = _graph("GET", "me", {"fields": "id"})
    if ok and str(me.get("id")) != str(config.FB_PAGE_ID):
        return {"ok": False, "label": "",
                "message": "the token is not a Page access token for this Page ID "
                           "(a normal user token cannot post to a Page)"}
    return {"ok": True, "message": "Page: %s" % page.get("name", ""), "label": page.get("name", "")}


def test_instagram():
    missing = [n for n in ("FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID", "IG_BUSINESS_ACCOUNT_ID")
               if not getattr(config, n)]
    if missing:
        return {"ok": False, "message": "missing " + ", ".join(missing), "label": ""}
    ok, ig = _graph("GET", config.IG_BUSINESS_ACCOUNT_ID, {"fields": "username,id"})
    if not ok:
        return {"ok": False, "message": ig, "label": ""}
    ok, page = _graph("GET", config.FB_PAGE_ID, {"fields": "instagram_business_account"})
    if ok:
        linked = str(page.get("instagram_business_account", {}).get("id", ""))
        if linked != str(config.IG_BUSINESS_ACCOUNT_ID):
            return {"ok": False, "label": "",
                    "message": "this Instagram account is not linked to the Facebook Page "
                               "(link it in Meta Business settings; it must be a Business/Creator account)"}
    return {"ok": True, "message": "Instagram: @%s" % ig.get("username", ""),
            "label": "@" + ig.get("username", "")}


def test_platform(platform):
    """Return (ok, message) for one platform."""
    if platform == "Facebook":
        result = test_facebook()
    elif platform == "Instagram":
        result = test_instagram()
    else:
        return False, "%s is not supported yet." % platform
    return result["ok"], result["message"]


def test_social_connections(show=True):
    """Test all supported platforms. Prints simple messages and returns details."""
    results = {"Facebook": test_facebook(), "Instagram": test_instagram()}
    if show:
        for line in connection_lines(results):
            print(line)
    return results


def connection_lines(results):
    lines = []
    for name, r in results.items():
        if r["ok"]:
            lines.append("%s connection: OK  (%s)" % (name, r["message"]))
        else:
            lines.append("%s connection: FAILED\nReason: %s" % (name, r["message"]))
    return lines


# ---------- Publishing ----------
def publish_facebook(message, image_url=""):
    """Post to the Facebook Page (with a photo when an image URL is given)."""
    if image_url:
        ok, data = _graph("POST", config.FB_PAGE_ID + "/photos", {"url": image_url, "caption": message})
    else:
        ok, data = _graph("POST", config.FB_PAGE_ID + "/feed", {"message": message})
    if not ok:
        return False, data, ""
    return True, "Published on Facebook.", str(data.get("post_id") or data.get("id", ""))


def publish_instagram(caption, image_url):
    """Post to Instagram: create container -> wait -> publish."""
    if not image_url:
        return False, "Instagram needs an image. Add a public JPEG image link.", ""
    ok, data = _graph("POST", config.IG_BUSINESS_ACCOUNT_ID + "/media",
                      {"image_url": image_url, "caption": caption})
    if not ok:
        return False, "Could not create the Instagram media. " + data, ""
    creation_id = data.get("id")
    for _ in range(12):                                   # wait up to about 24 seconds
        ok, status = _graph("GET", creation_id, {"fields": "status_code"})
        if ok and status.get("status_code") == "FINISHED":
            break
        if ok and status.get("status_code") == "ERROR":
            return False, "Instagram could not process the image (use a public JPEG).", ""
        time.sleep(2)
    ok, data = _graph("POST", config.IG_BUSINESS_ACCOUNT_ID + "/media_publish",
                      {"creation_id": creation_id})
    if not ok:
        return False, "Could not publish on Instagram. " + data, ""
    return True, "Published on Instagram.", str(data.get("id", ""))


def publish(platform, text, image_url=""):
    """Publish to one platform. Returns (ok, message, external_id). Never raises."""
    try:
        if platform == "Facebook":
            return publish_facebook(text, image_url)
        if platform == "Instagram":
            return publish_instagram(text, image_url)
        return False, "%s is not supported yet." % platform, ""
    except Exception as e:
        return False, config.safe_error("Unexpected error: %s" % e), ""
