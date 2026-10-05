"""
backend.py - REBUILT from your notebook (cell 0 + patch cells 33-40).
Colab-only lines are removed. Everything is read from environment variables.
Heavy things (Gemini, Google Sheet, embedding model) load lazily on first use.
"""
import os, json, time, random, textwrap
from datetime import datetime
from io import BytesIO
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ---- CONFIG ----
SHEET_URL = os.environ.get("SHEET_URL", "https://docs.google.com/spreadsheets/d/1n3rRh79wacoYpNmNo2clroktaot1P2A-mzN1760YvrE/edit?usp=sharing")
TAB_NAME = os.environ.get("SHEET_TAB", "Sheet1")
DUPLICATE_THRESHOLD = 0.75
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-3.8-flash")
GRAPH_API_VERSION = "v23.0"
DEFAULT_WORKSPACE_ID = "leaders_academia"
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")
MEDIA_DIR = os.environ.get("MEDIA_DIR", "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

# ---- lazy singletons ----
_state = {}

def _creds():
    if "creds" not in _state:
        sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")   # for Railway
        if sa:
            from google.oauth2.service_account import Credentials
            _state["creds"] = Credentials.from_service_account_info(
                json.loads(sa), scopes=["https://www.googleapis.com/auth/spreadsheets",
                                        "https://www.googleapis.com/auth/drive"])
        else:                                                  # Colab (auth.authenticate_user() done in notebook)
            from google.auth import default
            _state["creds"], _ = default()
    return _state["creds"]

def get_worksheet():
    if "ws" not in _state:
        import gspread
        gc = gspread.authorize(_creds())
        _state["ws"] = gc.open_by_url(SHEET_URL).worksheet(TAB_NAME)
    return _state["ws"]

def get_gemini():
    if "gem" not in _state:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        _state["gem"] = genai.GenerativeModel(GEMINI_MODEL_NAME)
    return _state["gem"]

def get_embedder():
    if "emb" not in _state:
        from sentence_transformers import SentenceTransformer
        _state["emb"] = SentenceTransformer("all-MiniLM-L6-v2")
    return _state["emb"]

def get_drive():
    if "drive" not in _state:
        from googleapiclient.discovery import build
        _state["drive"] = build("drive", "v3", credentials=_creds())
    return _state["drive"]

def gemini_text(prompt):
    try:
        return get_gemini().generate_content(prompt).text.strip()
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            raise Exception("Aaj ka Gemini free quota khatam ho chuka hai. Kal dobara try karein.")
        raise

# ---- history + duplicate check ----
def get_topic_history(workspace_id=DEFAULT_WORKSPACE_ID):
    try:
        records = get_worksheet().get_all_records()
    except Exception as e:
        print("[backend] sheet history unavailable:", e); return []
    return [r["Topic"] for r in records
            if r.get("Topic") and r.get("workspace_id", DEFAULT_WORKSPACE_ID) in (workspace_id, "")]

def is_duplicate(candidate, history, threshold=DUPLICATE_THRESHOLD):
    if not history:
        return False, 0.0
    try:   # best: semantic similarity (needs sentence-transformers, ~1 GB RAM)
        from sentence_transformers import util
        emb = get_embedder()
        c = emb.encode(candidate, convert_to_tensor=True)
        h = emb.encode(history, convert_to_tensor=True)
        score = float(util.cos_sim(c, h)[0].max())
    except ImportError:   # light fallback for small servers (plain text similarity)
        import difflib
        score = max(difflib.SequenceMatcher(None, candidate.lower(), t.lower()).ratio() for t in history)
    return score >= threshold, round(score, 3)

def log_topic_to_history(workspace_id, topic, product, cta, status):
    matched = product["name"] if product else "None"
    row = [datetime.now().strftime("%Y-%m-%d"), topic, matched, cta or "None",
           status.get("facebook", "not attempted"), status.get("instagram", "not attempted"),
           workspace_id]
    get_worksheet().append_row(row, value_input_option="USER_ENTERED")

# ---- content ----
def generate_platform_content(topic, workspace, cta, platforms):
    cta_line = (f"\n\nCTA to include naturally (only if it fits): {cta}"
                if cta else "\n\nDo not include any CTA.")
    platform_blocks = "\n\n".join(
        f"{p.upper()}:\nA 2-3 line post for {p}, written in {workspace['content_language']}. "
        f"Tone: {workspace['brand_tone']}. " +
        ("Include 2-3 relevant hashtags." if p in ("instagram", "linkedin") else "")
        for p in platforms)
    prompt = f"""
You are a content writer for this business:
Business: {workspace['business_name']}
Description: {workspace['description']}
Industry: {workspace['industry']}
Target audience: {workspace['target_audience']}
Brand tone: {workspace['brand_tone']}
Extra brand instructions: {workspace.get('brand_instructions') or 'none'}

Topic for this post: "{topic}"
{cta_line}

Write SEPARATE short "community post" style updates for each platform below, clearly labeled.
Each must be ONLY 2-3 lines total.

{platform_blocks}

Return ONLY in this exact format, nothing else before or after:
""" + "\n\n".join(f"{p.upper()}:\n<content>" for p in platforms)
    return gemini_text(prompt)

def parse_platform_content(raw_text):
    parts = {"linkedin": "", "instagram": "", "facebook": ""}
    current = None
    for line in raw_text.splitlines():
        s = line.strip().upper()
        if s.startswith("LINKEDIN:"): current = "linkedin"; continue
        if s.startswith("INSTAGRAM:"): current = "instagram"; continue
        if s.startswith("FACEBOOK:"): current = "facebook"; continue
        if current: parts[current] += line + "\n"
    return {k: v.strip() for k, v in parts.items()}

def generate_topic_with_ai(workspace, product):
    return gemini_text(f"""
You are a social media strategist for this business:
Business: {workspace['business_name']}
Industry: {workspace['industry']}
Target audience: {workspace['target_audience']}
Brand tone: {workspace['brand_tone']}

Write ONE short, scroll-stopping social media post topic/hook (one sentence,
no hashtags, no emojis) that naturally leads into promoting:
Product/service: {product['name']} - {product['description']}

Return ONLY the single sentence topic, nothing else.
""").strip('"')

def generate_fresh_topic_for_product(workspace_id, workspace, product, max_attempts=5):
    history = get_topic_history(workspace_id)
    candidate, score = None, 0.0
    for _ in range(max_attempts):
        candidate = generate_topic_with_ai(workspace, product)
        dup, score = is_duplicate(candidate, history)
        if not dup: break
    cta = product.get("cta") or (f"Learn more: {product.get('url')}" if product.get("url") else "")
    return {"topic": candidate, "similarity_to_closest_past_topic": score,
            "history_count": len(history), "cta": cta}

def parse_user_request(user_text, workspace, products):
    plist = "\n".join(f"- id={p['product_id']}: {p['name']} ({p['category']})" for p in products) or "none"
    raw = gemini_text(f"""
The user typed this request (may be Roman Urdu/Urdu/English mix) to an AI marketing assistant:
"{user_text}"

Business: {workspace['business_name']}
Available products/services:
{plist}

Decide:
1. Which platforms they want (only from: facebook, instagram, linkedin). If unclear, default to ["facebook","instagram"].
2. Which product/service (by id) they are referring to, if any (null if unclear).
3. A short topic hint if they described one, else null.

Return ONLY valid JSON, no markdown:
{{"platforms": ["facebook","instagram"], "product_id": null, "topic_hint": null}}
""").replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"platforms": ["facebook", "instagram"], "product_id": None, "topic_hint": None}

# ---- image ----
def fetch_background_photo(query, size=1080):
    try:
        r = requests.get("https://api.unsplash.com/photos/random",
                         params={"query": query, "orientation": "squarish", "client_id": UNSPLASH_ACCESS_KEY}, timeout=10)
        data = requests.get(r.json()["urls"]["regular"], timeout=10).content
        return ImageOps.fit(Image.open(BytesIO(data)).convert("RGB"), (size, size), method=Image.LANCZOS)
    except Exception as e:
        print("Photo fetch failed (" + str(e) + "), using plain background.")
        return Image.new("RGB", (size, size), color=(16, 22, 48))

def create_post_image(topic, category="General", business_name="Business", filename="post_image.png"):
    W = H = 1080
    img = fetch_background_photo(category, size=W).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(H):
        od.line([(0, y), (W, y)], fill=(5, 8, 20, int(60 + (170 * (y / H)))))
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        f_cat = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        f_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 60)
        f_brand = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
    except Exception:
        f_cat = ImageFont.load_default(size=32); f_title = ImageFont.load_default(size=60); f_brand = ImageFont.load_default(size=36)
    accent = (130, 180, 255)
    badge = category.upper()
    bb = draw.textbbox((0, 0), badge, font=f_cat)
    draw.rounded_rectangle([80, 80, 80 + (bb[2] - bb[0]) + 50, 140], radius=28, outline=accent, width=2)
    draw.text((105, 96), badge, font=f_cat, fill=accent)
    wrapped = textwrap.wrap(topic, width=20)
    start_y = H - 260 - (len(wrapped) * 72)
    for i, line in enumerate(wrapped):
        draw.text((80, start_y + i * 72), line, font=f_title, fill=(255, 255, 255))
    draw.text((80, H - 90), business_name, font=f_brand, fill=(230, 230, 245))
    img.save(filename)
    return filename

def upload_image_to_drive(local_path, filename):
    from googleapiclient.http import MediaFileUpload
    drive = get_drive()
    f = drive.files().create(body={"name": filename}, media_body=MediaFileUpload(local_path, mimetype="image/png"), fields="id").execute()
    drive.permissions().create(fileId=f["id"], body={"type": "anyone", "role": "reader"}).execute()
    return "https://drive.google.com/uc?export=view&id=" + f["id"]

# ---- posting ----
def post_to_facebook(message, page_id, page_access_token):
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/feed"
    data = requests.post(url, data={"message": message, "access_token": page_access_token}).json()
    if "id" not in data:
        raise Exception("Facebook post failed: " + str(data))
    return data

def post_to_instagram(caption, image_url, ig_user_id, access_token):
    base = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
    container = requests.post(f"{base}/{ig_user_id}/media",
                              data={"image_url": image_url, "caption": caption, "access_token": access_token}).json()
    if "id" not in container:
        raise Exception("Instagram container creation failed: " + str(container))
    cid = container["id"]
    for _ in range(10):
        st = requests.get(f"{base}/{cid}", params={"fields": "status_code", "access_token": access_token}).json()
        code = st.get("status_code")
        if code == "FINISHED": break
        if code == "ERROR": raise Exception("Instagram media processing failed: " + str(st))
        time.sleep(3)
    else:
        raise Exception("Instagram media never finished processing after 30 seconds.")
    pub = requests.post(f"{base}/{ig_user_id}/media_publish", data={"creation_id": cid, "access_token": access_token}).json()
    if "id" not in pub:
        raise Exception("Instagram publish failed: " + str(pub))
    return pub

# ---- two-step pipeline: draft -> (approve) -> publish ----
def generate_draft(workspace_id, workspace, user_text, products):
    intent = parse_user_request(user_text, workspace, products) if user_text.strip() else {}
    platforms = intent.get("platforms") or ["facebook", "instagram"]
    product = next((p for p in products if p["product_id"] == intent.get("product_id")), None)
    if product is None and products:
        product = products[0]

    if intent.get("topic_hint"):
        topic = intent["topic_hint"]
        cta = product.get("cta") if product else workspace.get("default_cta", "")
        _, score = is_duplicate(topic, get_topic_history(workspace_id))
    else:
        fb = product or {"name": workspace["business_name"], "description": workspace["description"],
                         "cta": workspace.get("default_cta", "")}
        r = generate_fresh_topic_for_product(workspace_id, workspace, fb)
        topic, cta, score = r["topic"], r["cta"], r["similarity_to_closest_past_topic"]

    parsed = parse_platform_content(generate_platform_content(topic, workspace, cta, platforms))
    content = {p: parsed.get(p, "") for p in platforms}
    category = (product or {}).get("category") or workspace["industry"] or "General"
    image_path = create_post_image(topic, category=category,
                                   business_name=workspace.get("brand_name") or workspace["business_name"],
                                   filename=os.path.join(MEDIA_DIR, f"post_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"))
    return {"topic": topic, "cta": cta, "similarity": score, "platforms": platforms,
            "product": product, "content": content, "image_path": image_path}

def publish_draft(workspace, draft, platforms_to_publish):
    status, image_url = {}, None
    fb_id, token = workspace.get("fb_page_id"), workspace.get("fb_page_access_token")
    ig_id = workspace.get("ig_business_account_id")

    if "facebook" in platforms_to_publish:
        try:
            fb = post_to_facebook(draft["content"]["facebook"], fb_id, token)
            status["facebook"] = "posted (id: " + str(fb.get("id")) + ")"
        except Exception as e:
            status["facebook"] = "FAILED: " + str(e)

    if "instagram" in platforms_to_publish:
        try:
            image_url = upload_image_to_drive(draft["image_path"], "post_" + datetime.now().strftime("%Y%m%d%H%M%S") + ".png")
            ig = post_to_instagram(draft["content"]["instagram"], image_url, ig_id, token)
            status["instagram"] = "posted (id: " + str(ig.get("id")) + ")"
        except Exception as e:
            status["instagram"] = "FAILED: " + str(e)

    if "linkedin" in platforms_to_publish:
        status["linkedin"] = "content-ready (publishing not implemented yet)"

    try:   # keep the Google Sheet history in sync (duplicate check)
        log_topic_to_history(workspace.get("workspace_id", DEFAULT_WORKSPACE_ID), draft.get("topic", ""), None, None, status)
    except Exception as e:
        print("[backend] could not log to sheet:", e)
    return status, image_url
