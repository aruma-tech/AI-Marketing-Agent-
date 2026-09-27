"""website_reader.py - read PUBLIC website pages and pull out business facts.

Safety rules:
  * respects robots.txt
  * never tries to pass login, CAPTCHA or blocked pages (it just stops)
  * refuses private / local network addresses
"""
import re
import json
import time
import socket
import ipaddress
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

import config

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketingAgentBot/1.0)"}
MAX_BYTES = 1_500_000
USEFUL_WORDS = ["about", "service", "course", "product", "program", "offer", "contact",
                "menu", "pricing", "collection", "shop", "team", "who-we-are", "what-we-do"]
SKIP_WORDS = ["login", "signin", "sign-in", "account", "cart", "checkout", "admin",
              "register", "password", "cdn-cgi", "wp-json", "logout"]
SKIP_FILES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".mp4", ".svg", ".webp")
IMAGE_SKIP_WORDS = ["logo", "icon", "sprite", "avatar", "pixel", "tracking", "spinner", "blank"]

_robots = {}


# ---------- URL safety ----------
def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("Website URL is empty.")
    if "://" in url and not re.match(r"^https?://", url, re.I):
        raise ValueError("Only http:// or https:// website links are allowed.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Website URL is not valid.")
    return url


def host_is_public(hostname):
    """Return (True, '') if the host points to a public internet address."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, "Website address could not be found."
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False, "Private or local addresses are not allowed."
    return True, ""


def safe_get(url):
    """GET a URL with redirect checks. Returns (status, content_type, text, final_url)."""
    for _ in range(4):
        ok, why = host_is_public(urlparse(url).hostname)
        if not ok:
            raise ValueError(why)
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False, stream=True)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise ValueError("Bad redirect.")
            url = urljoin(url, location)
            continue
        data = b""
        for chunk in resp.iter_content(65536):
            data += chunk
            if len(data) > MAX_BYTES:
                break
        resp.close()
        text = data.decode(resp.encoding or "utf-8", errors="ignore")
        return resp.status_code, resp.headers.get("Content-Type", ""), text, url
    raise ValueError("Too many redirects.")


def allowed_by_robots(url):
    parsed = urlparse(url)
    base = "%s://%s" % (parsed.scheme, parsed.netloc)
    if base not in _robots:
        parser = robotparser.RobotFileParser()
        try:
            status, _, text, _ = safe_get(base + "/robots.txt")
            if status == 200:
                parser.parse(text.splitlines())
                _robots[base] = parser
            else:
                _robots[base] = None        # no robots.txt = no restriction
        except Exception:
            _robots[base] = None
    parser = _robots[base]
    return True if parser is None else parser.can_fetch(HEADERS["User-Agent"], url)


# ---------- Page parsing ----------
def parse_page(html, page_url):
    """Return title, description, readable text, images, contacts and useful links."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    meta = (soup.find("meta", attrs={"name": "description"})
            or soup.find("meta", attrs={"property": "og:description"}))
    description = (meta.get("content") or "").strip() if meta else ""

    # Images: social preview image first, then normal images
    images = []
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        images.append(urljoin(page_url, og["content"]))
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        full = urljoin(page_url, src)
        low = full.lower().split("?")[0]
        if low.endswith((".svg", ".gif", ".ico")) or any(w in low for w in IMAGE_SKIP_WORDS):
            continue
        try:
            if int(re.sub(r"\D", "", img.get("width", "") or "999")) < 200:
                continue
        except ValueError:
            pass
        if full not in images:
            images.append(full)

    # Contacts
    page_text_all = soup.get_text(" ", strip=True)
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", page_text_all))
    phones = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            emails.add(href[7:].split("?")[0])
        elif href.lower().startswith("tel:"):
            phones.add(href[4:].strip())
    emails = {e for e in emails if not e.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))}

    # Useful internal links
    host = urlparse(page_url).netloc
    links = []
    for a in soup.find_all("a", href=True):
        full = urljoin(page_url, a["href"]).split("#")[0]
        parsed = urlparse(full)
        path = parsed.path.lower()
        if (parsed.netloc == host and parsed.scheme in ("http", "https")
                and not path.endswith(SKIP_FILES)
                and any(w in path for w in USEFUL_WORDS)
                and not any(w in path for w in SKIP_WORDS) and full not in links):
            links.append(full)

    # Readable text (headings and paragraphs only)
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    seen, parts = set(), []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        is_heading = el.name.startswith("h")
        if len(text) < (3 if is_heading else 25) or text in seen:
            continue
        seen.add(text)
        parts.append(("# " + text) if is_heading else text)
    return {"title": title, "description": description, "text": "\n".join(parts)[:3000],
            "images": images[:8], "emails": sorted(emails)[:3], "phones": sorted(phones)[:3],
            "links": links[:6]}


# ---------- Main function ----------
def read_website(url, max_pages=None):
    """Read the homepage and a few useful public pages. Never raises."""
    max_pages = max_pages or config.WEBSITE_MAX_PAGES
    out = {"ok": False, "url": "", "pages": [], "title": "", "description": "", "text": "",
           "images": [], "emails": [], "phones": [], "enough": False, "message": ""}
    try:
        start = normalize_url(url)
    except ValueError as e:
        out["message"] = str(e)
        return out
    out["url"] = start

    queue, visited, blocks, notes = [start], set(), [], []
    while queue and len(out["pages"]) < max_pages:
        page = queue.pop(0)
        if page in visited:
            continue
        visited.add(page)
        try:
            if not allowed_by_robots(page):
                notes.append("blocked by robots.txt: " + page)
                continue
            status, ctype, html, final = safe_get(page)
        except Exception as e:
            notes.append("could not open %s (%s)" % (page, config.safe_error(e)))
            continue
        if status in (401, 403, 429):
            notes.append("restricted page (HTTP %d): %s" % (status, page))
            continue
        if status != 200 or "html" not in ctype.lower():
            continue
        info = parse_page(html, final)
        out["pages"].append(final)
        blocks.append("[%s]\n%s" % (final, info["text"]))
        if page == start:
            out["title"], out["description"] = info["title"], info["description"]
            queue.extend(info["links"])
        for key in ("images", "emails", "phones"):
            for item in info[key]:
                if item not in out[key]:
                    out[key].append(item)
        time.sleep(0.5)      # be polite to the website

    out["text"] = "\n\n".join(blocks)[:config.WEBSITE_MAX_CHARS]
    out["ok"] = bool(out["pages"])
    out["enough"] = len(out["text"]) >= config.WEBSITE_MIN_CHARS
    if not out["ok"]:
        out["message"] = ("The website could not be read (it may block automated reading, "
                          "need a login, or be offline). Please add the business "
                          "information manually. " + "; ".join(notes[:2]))
    elif not out["enough"]:
        out["message"] = ("The website has very little readable text. Please add more "
                          "business information in the profile.")
    else:
        out["message"] = "Website read OK (%d page(s))." % len(out["pages"])
    return out


# ---------- Cache (so the website is not read on every click) ----------
def _cache_file(business_id):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / (re.sub(r"[^\w-]", "_", business_id) + ".json")


def get_website_info(business, refresh=False):
    """Return website info for ONE business (cached for a few hours)."""
    url = (business.get("Website URL") or "").strip()
    if not url:
        return {"ok": False, "url": "", "pages": [], "title": "", "description": "", "text": "",
                "images": [], "emails": [], "phones": [], "enough": False,
                "message": "This business has no website URL."}
    path = _cache_file(business["Business ID"])
    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text())
            fresh = datetime.fromisoformat(cached["saved_at"]) > datetime.now() - timedelta(hours=config.CACHE_HOURS)
            if cached["info"].get("url", "") == normalize_url(url) and fresh:
                return cached["info"]
        except Exception:
            pass
    info = read_website(url)
    if info["ok"]:
        path.write_text(json.dumps({"saved_at": datetime.now().isoformat(), "info": info}))
    return info
