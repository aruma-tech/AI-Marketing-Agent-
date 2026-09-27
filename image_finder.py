"""image_finder.py - find a public image for a post.

Order: 1) image you paste  2) image from the business website  3) Unsplash.
Instagram only accepts JPEG images from a public URL, so we check that.
"""
import requests
import config
import website_reader as wr


def check_image(url, need_jpeg):
    """Return True if the URL is a public image Instagram/Facebook can use."""
    try:
        ok, _ = wr.host_is_public(wr.urlparse(url).hostname)
        if not ok:
            return False
        resp = requests.get(url, headers=wr.HEADERS, timeout=15, stream=True)
        ctype = resp.headers.get("Content-Type", "").lower()
        size = int(resp.headers.get("Content-Length", "0") or 0)
        resp.close()
        if resp.status_code != 200 or size > 8_000_000:
            return False
        if need_jpeg:
            return "image/jpeg" in ctype or "image/jpg" in ctype
        return ctype.startswith("image/") and "svg" not in ctype
    except Exception:
        return False


def search_unsplash(query, exclude=()):
    """Search Unsplash. Returns {'url','credit','source'} or None."""
    if not config.UNSPLASH_ACCESS_KEY or not query:
        return None
    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 10, "orientation": "squarish",
                    "content_filter": "high"},
            headers={"Authorization": "Client-ID " + config.UNSPLASH_ACCESS_KEY},
            timeout=20)
        if resp.status_code != 200:
            return None
        for photo in resp.json().get("results", []):
            width, height = photo.get("width", 1), photo.get("height", 1)
            ratio = width / float(height or 1)
            url = photo.get("urls", {}).get("regular", "")
            if not url or url in exclude or not (0.8 <= ratio <= 1.91):
                continue
            if "fm=jpg" not in url:
                url += ("&" if "?" in url else "?") + "fm=jpg"
            name = photo.get("user", {}).get("name", "an Unsplash photographer")
            # Tell Unsplash the photo is used (their API guideline)
            try:
                link = photo.get("links", {}).get("download_location")
                if link:
                    requests.get(link, headers={"Authorization": "Client-ID " + config.UNSPLASH_ACCESS_KEY},
                                 timeout=10)
            except Exception:
                pass
            return {"url": url, "credit": "Photo by %s on Unsplash" % name, "source": "unsplash"}
    except Exception:
        return None
    return None


def find_image(query, website_info, platform, manual_url="", exclude=()):
    """Return {'url','credit','source'}. url is '' if nothing usable was found."""
    need_jpeg = platform == "Instagram"
    manual_url = (manual_url or "").strip()
    if manual_url:
        if check_image(manual_url, need_jpeg):
            return {"url": manual_url, "credit": "", "source": "manual"}
        return {"url": "", "credit": "", "source": "",
                "message": "Your image link is not a public %s image." %
                           ("JPEG" if need_jpeg else "picture")}
    for url in (website_info or {}).get("images", [])[:6]:
        if url not in exclude and check_image(url, need_jpeg):
            return {"url": url, "credit": "", "source": "website"}
    found = search_unsplash(query, exclude)
    if found:
        return found
    return {"url": "", "credit": "", "source": "",
            "message": "No usable image found. Paste a public JPEG image link."}
