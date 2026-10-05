"""
AI Marketing Agent - FastAPI server + custom dashboard (no Gradio).
Run locally:  uvicorn main:app --reload
Railway:      uses Procfile.  Set env DASHBOARD_PASSWORD to protect the dashboard.
"""
import os, json, sqlite3, threading, time, uuid, hmac, base64, shutil
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import agent_adapter as agent

DB_PATH = os.environ.get("DB_PATH", "data.db")   # point to a Railway volume path for persistence
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
# uploads live next to the database (with DB_PATH=/data/data.db -> /data/uploads, on the Railway volume)
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="AI Marketing Agent")
_lock = threading.Lock()


# ---------------- DB ----------------
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS businesses(
          id TEXT PRIMARY KEY, name TEXT, brand_name TEXT, industry TEXT, audience TEXT,
          description TEXT, cta TEXT, website TEXT, fb_page_id TEXT, fb_token TEXT, ig_id TEXT,
          products TEXT DEFAULT '[]', language TEXT DEFAULT '', tone TEXT DEFAULT '', instructions TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS posts(
          id TEXT PRIMARY KEY, business_id TEXT, topic TEXT, content TEXT, platforms TEXT,
          image_path TEXT, status TEXT, scheduled_at TEXT, result TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS media(
          id TEXT PRIMARY KEY, business_id TEXT, kind TEXT, name TEXT, filename TEXT, created_at TEXT);
        """)
init_db()
with db() as _c:   # upgrade older databases that lack the new columns
    for _col in ("language", "tone", "instructions"):
        try: _c.execute(f"ALTER TABLE businesses ADD COLUMN {_col} TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass
os.makedirs("media", exist_ok=True)

def row_biz(r):
    d = dict(r); d["products"] = json.loads(d.get("products") or "[]"); return d


# ---------------- auth ----------------
def auth(x_auth: Optional[str] = Header(default=None)):
    if PASSWORD and not (x_auth and hmac.compare_digest(x_auth, PASSWORD)):
        raise HTTPException(401, "Unauthorized")


# ---------------- models ----------------
class BizIn(BaseModel):
    id: Optional[str] = None
    name: str
    brand_name: str = ""
    industry: str = ""
    audience: str = ""
    description: str = ""
    cta: str = ""
    website: str = ""
    fb_page_id: str = ""
    fb_token: str = ""
    ig_id: str = ""
    products: list = []
    language: str = ""
    tone: str = ""
    instructions: str = ""

class GenIn(BaseModel):
    business_id: str
    prompt: str = ""
    platforms: list = []          # e.g. ["facebook", "instagram"]
    languages: dict = {}          # e.g. {"facebook": "Urdu", "instagram": "English"}
    image_source: str = "ai"      # ai | unsplash | upload | none
    media_id: str = ""            # used when image_source == "upload"
    logo_pos: str = ""            # "" | tl | tr | bl | br

class SchedIn(BaseModel):
    when: str  # ISO local datetime e.g. 2026-10-06T10:00


# ---------------- business ----------------
@app.get("/api/login", dependencies=[Depends(auth)])
def login(): return {"ok": True}

@app.get("/api/businesses", dependencies=[Depends(auth)])
def list_biz():
    with db() as c:
        return [{"id": r["id"], "name": r["name"]} for r in c.execute("SELECT id,name FROM businesses")]

@app.get("/api/businesses/{bid}", dependencies=[Depends(auth)])
def get_biz(bid: str):
    with db() as c:
        r = c.execute("SELECT * FROM businesses WHERE id=?", (bid,)).fetchone()
    if not r: raise HTTPException(404, "Not found")
    d = row_biz(r); d["fb_token"] = "••••" if d.get("fb_token") else ""   # never send token back
    return d

@app.post("/api/businesses", dependencies=[Depends(auth)])
def save_biz(b: BizIn):
    bid = b.id or "BUS-" + uuid.uuid4().hex[:6]
    with _lock, db() as c:
        old = c.execute("SELECT fb_token FROM businesses WHERE id=?", (bid,)).fetchone()
        token = b.fb_token if (b.fb_token and b.fb_token != "••••") else (old["fb_token"] if old else "")
        c.execute("""INSERT OR REPLACE INTO businesses
          (id,name,brand_name,industry,audience,description,cta,website,fb_page_id,fb_token,ig_id,products,language,tone,instructions)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (bid, b.name, b.brand_name, b.industry, b.audience, b.description, b.cta, b.website,
           b.fb_page_id, token, b.ig_id, json.dumps(b.products), b.language, b.tone, b.instructions))
    return {"id": bid}


# ---------------- dashboard data ----------------
@app.get("/api/stats/{bid}", dependencies=[Depends(auth)])
def stats(bid: str):
    out = {k: 0 for k in ["draft", "approved", "scheduled", "published", "failed"]}
    with db() as c:
        for r in c.execute("SELECT status, COUNT(*) n FROM posts WHERE business_id=? GROUP BY status", (bid,)):
            out[r["status"]] = r["n"]
        biz = c.execute("SELECT fb_page_id, ig_id FROM businesses WHERE id=?", (bid,)).fetchone()
    out["platforms"] = [p for p, v in (("Facebook", biz and biz["fb_page_id"]), ("Instagram", biz and biz["ig_id"])) if v]
    return out

def row_post(r):
    d = dict(r)
    d["content"] = json.loads(d["content"] or "{}"); d["platforms"] = json.loads(d["platforms"] or "[]")
    d["result"] = json.loads(d["result"] or "{}")
    ip = d.get("image_path")
    d["image_url"] = "/uploads/" + os.path.basename(ip) if ip and os.path.abspath(ip).startswith(os.path.abspath(UPLOAD_DIR)) else None
    return d

@app.get("/api/posts", dependencies=[Depends(auth)])
def posts(business_id: str, status: Optional[str] = None):
    q, a = "SELECT * FROM posts WHERE business_id=?", [business_id]
    if status: q += " AND status=?"; a.append(status)
    with db() as c:
        return [row_post(r) for r in c.execute(q + " ORDER BY created_at DESC", a)]


# ---------------- media library ----------------
class MediaIn(BaseModel):
    business_id: str
    kind: str = "photo"           # logo | background | photo
    name: str = "image"
    data: str                     # data URL (base64)

@app.post("/api/media", dependencies=[Depends(auth)])
def add_media(m: MediaIn):
    try:
        head, b64 = m.data.split(",", 1); raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(400, "Could not read the file")
    mime = head.split(";")[0].replace("data:", "")
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(mime)
    if not ext or len(raw) > 8_000_000:
        raise HTTPException(400, "Use a PNG, JPG, WEBP or GIF under 8 MB")
    mid = uuid.uuid4().hex[:10]; fn = mid + ext
    with open(os.path.join(UPLOAD_DIR, fn), "wb") as f: f.write(raw)
    with _lock, db() as c:
        c.execute("INSERT INTO media VALUES(?,?,?,?,?,?)",
                  (mid, m.business_id, m.kind, m.name[:80], fn, datetime.now().isoformat(timespec="seconds")))
    return {"id": mid}

@app.get("/api/media", dependencies=[Depends(auth)])
def list_media(business_id: str):
    with db() as c:
        rows = c.execute("SELECT * FROM media WHERE business_id=? ORDER BY created_at DESC", (business_id,)).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "name": r["name"], "url": "/uploads/" + r["filename"]} for r in rows]

@app.delete("/api/media/{mid}", dependencies=[Depends(auth)])
def del_media(mid: str):
    with _lock, db() as c:
        r = c.execute("SELECT filename FROM media WHERE id=?", (mid,)).fetchone()
        c.execute("DELETE FROM media WHERE id=?", (mid,))
    if r:
        try: os.remove(os.path.join(UPLOAD_DIR, r["filename"]))
        except OSError: pass
    return {"ok": True}

def _logo(img_path, bid, pos):
    """Paste the newest uploaded logo onto the image (needs Pillow). Returns the new image path."""
    try:
        from PIL import Image
        with db() as c:
            r = c.execute("SELECT filename FROM media WHERE business_id=? AND kind='logo' ORDER BY created_at DESC", (bid,)).fetchone()
        if not r: return img_path
        base = Image.open(img_path).convert("RGBA")
        logo = Image.open(os.path.join(UPLOAD_DIR, r["filename"])).convert("RGBA")
        w = max(40, base.width // 5); logo = logo.resize((w, max(1, int(logo.height * w / logo.width))))
        mg = max(12, base.width // 40)
        x = mg if pos[1] == "l" else base.width - logo.width - mg
        y = mg if pos[0] == "t" else base.height - logo.height - mg
        base.alpha_composite(logo, (x, y))
        out = os.path.splitext(img_path)[0] + "_b.jpg"
        base.convert("RGB").save(out, quality=92)
        return out
    except Exception as e:
        print("[logo]", e); return img_path

def _build(g):
    """Make a draft using the chosen platforms, languages and image options."""
    biz = _biz(g.business_id)
    plats = [p for p in g.platforms if p in ("facebook", "instagram", "linkedin")]
    prompt = g.prompt.strip() or "Choose a fresh, relevant topic yourself."
    if plats:
        langs = "; ".join(f"{p}: {g.languages.get(p, 'English')}" for p in plats)
        prompt += f"\n\n[Instructions] Create posts ONLY for: {', '.join(plats)}. Language per platform -> {langs}. Image source preference: {g.image_source}."
    d = agent.make_draft(biz, prompt)
    if plats:
        d["content"] = {k: v for k, v in d["content"].items() if k in plats}
        d["platforms"] = [p for p in plats if p in d["content"]] or d["platforms"]
    img = d.get("image_path")
    if g.image_source == "none": img = None
    elif g.image_source == "upload" and g.media_id:
        with db() as c: r = c.execute("SELECT filename FROM media WHERE id=?", (g.media_id,)).fetchone()
        if r: img = os.path.join(UPLOAD_DIR, r["filename"])
    if img and os.path.exists(img):   # copy into uploads so it can be previewed and served publicly
        dst = os.path.join(UPLOAD_DIR, uuid.uuid4().hex[:10] + os.path.splitext(img)[1].lower())
        shutil.copy(img, dst); img = dst
        if g.logo_pos: img = _logo(img, g.business_id, g.logo_pos)
    d["image_path"] = img
    return d


# ---------------- actions ----------------
def _biz(bid):
    with db() as c:
        r = c.execute("SELECT * FROM businesses WHERE id=?", (bid,)).fetchone()
    if not r: raise HTTPException(404, "Business not found")
    return row_biz(r)

def _post(pid):
    with db() as c:
        r = c.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not r: raise HTTPException(404, "Post not found")
    return row_post(r)

def _set(pid, **kw):
    cols = ",".join(f"{k}=?" for k in kw)
    vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in kw.values()]
    with _lock, db() as c:
        c.execute(f"UPDATE posts SET {cols} WHERE id=?", vals + [pid])

@app.post("/api/generate", dependencies=[Depends(auth)])
def generate(g: GenIn):
    try:
        d = _build(g)
    except Exception as e:
        raise HTTPException(500, f"Draft failed: {e}")
    pid = uuid.uuid4().hex[:10]
    with _lock, db() as c:
        c.execute("INSERT INTO posts VALUES(?,?,?,?,?,?,?,?,?,?)",
          (pid, g.business_id, d["topic"], json.dumps(d["content"]), json.dumps(d["platforms"]),
           d.get("image_path"), "draft", None, "{}", datetime.now().isoformat(timespec="seconds")))
    return _post(pid)

@app.post("/api/posts/{pid}/regenerate", dependencies=[Depends(auth)])
def regenerate(pid: str, g: GenIn):
    old = _post(pid)
    if old["status"] == "published": raise HTTPException(400, "Already published")
    g.prompt = g.prompt or old["topic"]
    try:
        d = _build(g)
    except Exception as e:
        raise HTTPException(500, f"Draft failed: {e}")
    _set(pid, topic=d["topic"], content=d["content"], platforms=d["platforms"],
         image_path=d.get("image_path"), status="draft", scheduled_at=None, result={})
    return _post(pid)

class EditIn(BaseModel):
    content: dict

@app.put("/api/posts/{pid}", dependencies=[Depends(auth)])
def edit(pid: str, e: EditIn):
    _set(pid, content=e.content); return _post(pid)

@app.post("/api/posts/{pid}/approve", dependencies=[Depends(auth)])
def approve(pid: str):
    _set(pid, status="approved"); return _post(pid)

@app.post("/api/posts/{pid}/schedule", dependencies=[Depends(auth)])
def schedule(pid: str, s: SchedIn):
    p = _post(pid)
    if p["status"] not in ("approved", "scheduled"):
        raise HTTPException(400, "Approve the post first")
    _set(pid, status="scheduled", scheduled_at=s.when); return _post(pid)

def do_publish(pid):
    p = _post(pid); biz = _biz(p["business_id"])
    try:
        ip = p["image_path"]
        if ip and os.environ.get("PUBLIC_BASE_URL") and os.path.abspath(ip).startswith(os.path.abspath(UPLOAD_DIR)):
            ip = "uploads/" + os.path.basename(ip)   # backend builds PUBLIC_BASE_URL + "/" + image_path
        res = agent.publish(biz, {"content": p["content"], "image_path": ip, "topic": p["topic"]}, p["platforms"])
    except Exception as e:
        res = {"error": f"FAILED: {e}"}
    failed = any(str(v).startswith("FAILED") for v in res.values())
    _set(pid, status="failed" if failed else "published", result=res)

@app.post("/api/posts/{pid}/publish", dependencies=[Depends(auth)])
def publish_now(pid: str):
    if _post(pid)["status"] not in ("approved", "scheduled", "failed"):
        raise HTTPException(400, "Approve the post first (nothing is published without approval)")
    do_publish(pid); return _post(pid)

@app.delete("/api/posts/{pid}", dependencies=[Depends(auth)])
def delete(pid: str):
    with _lock, db() as c: c.execute("DELETE FROM posts WHERE id=?", (pid,))
    return {"ok": True}

@app.post("/api/chat", dependencies=[Depends(auth)])
def chat(g: GenIn):
    """Simple chat = natural-language request -> draft (your parse_user_request handles platforms/product)."""
    p = generate(g)
    return {"reply": f"Draft ready: “{p['topic']}”. Review it in Create Post / Home, then approve.", "post": p}


# ---------------- scheduler ----------------
def scheduler_loop():
    while True:
        try:
            now = datetime.utcnow().isoformat(timespec="minutes")  # scheduled_at is stored in UTC
            with db() as c:
                due = [r["id"] for r in c.execute(
                    "SELECT id FROM posts WHERE status='scheduled' AND scheduled_at<=?", (now,))]
            for pid in due: do_publish(pid)
        except Exception as e:
            print("[scheduler]", e)
        time.sleep(30)

threading.Thread(target=scheduler_loop, daemon=True).start()


# ---------------- frontend ----------------
@app.get("/")
def index(): return FileResponse("static/index.html")
app.mount("/media", StaticFiles(directory="media"), name="media")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")
