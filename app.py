import os
import sqlite3
import secrets
import time
import feedparser
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from apscheduler.schedulers.background import BackgroundScheduler
from jinja2 import Template
import uvicorn

# --- 1. إعداد قواعد البيانات والمجلدات ---
DB_NAME = "bashan_radio.db"
DB_PORTAL = "bashan_portal.db"
UPLOAD_DIR = "music_library"
IMAGES_DIR = "images"
VIDEOS_DIR = "videos"

for directory in [UPLOAD_DIR, IMAGES_DIR, VIDEOS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

default_vid_file = ""
if os.path.exists(VIDEOS_DIR):
    vids = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))]
    if vids:
        default_vid_file = f"/videos/{vids[0]}"

CURRENT_STATE = {
    "media_type": "youtube",
    "active_song": "",
    "active_video": default_vid_file,
    "youtube_url": "https://www.youtube.com/watch?v=5qap5aO4i9A",
    "breaking_banner": "",
    "sweida_speed": 90,
    "world_speed": 90,
    "playlist": [],
    "playlist_started_at": 0,
    "video_playlist_started_at": 0
}

# --- 2. إعدادات الحماية ---
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = "Bashan2026!"
PORTAL_ADMIN_USER = "portal_admin"
PORTAL_ADMIN_PASS = "BashanNews2026!"

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, ADMIN_USER) and secrets.compare_digest(credentials.password, ADMIN_PASS)):
        raise HTTPException(status_code=401, detail="غير مسموح", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def verify_portal_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, PORTAL_ADMIN_USER) and secrets.compare_digest(credentials.password, PORTAL_ADMIN_PASS)):
        raise HTTPException(status_code=401, detail="غير مسموح", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def init_dbs():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT, source_name TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT DEFAULT 'عالمي')''')
        conn.commit()
        conn.close()

        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_ar TEXT NOT NULL,
            content_ar TEXT,
            title_en TEXT,
            content_en TEXT,
            title_he TEXT,
            content_he TEXT,
            category TEXT NOT NULL,
            source_name TEXT,
            published_at TEXT,
            status TEXT DEFAULT 'approved'
        )''')
        
        # مصادر RSS العالمية للموقع الإخباري
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS portal_sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT DEFAULT 'عالمي')''')
        default_portal_sources = [
            ("BBC News Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي"),
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي"),
            ("DW Arabic", "https://rss.dw.com/xml/rss-ar-all", "عالمي"),
            ("France 24 Arabic", "https://www.france24.com/ar/rss", "عالمي"),
            ("Reuters World (Google News)", "https://news.google.com/rss/search?q=site%3Areuters.com&hl=ar&gl=AE&ceid=AE%3Aar", "صحافة عالمية")
        ]
        cursor_p.executemany("INSERT OR IGNORE INTO portal_sources (name, url, category) VALUES (?, ?, ?)", default_portal_sources)
        conn_p.commit()
        conn_p.close()
    except Exception:
        pass

def fetch_portal_news():
    # سحب أخبار الشريط (القاعدة القديمة)
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT name, url, category FROM sources")
        for name, url, category in cursor.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    title = str(getattr(entry, 'title', '') or '').strip()
                    if not title:
                        continue
                    cursor.execute("SELECT id FROM news WHERE title = ?", (title,))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'pending')", (title, category, name))
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass

    # سحب المقالات للموقع الإخباري الرئيسي (RSS تلقائي من الوكالات)
    try:
        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute("SELECT name, url, category FROM portal_sources")
        for name, url, category in cursor_p.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:8]:
                    title = str(getattr(entry, 'title', '') or '').strip()
                    summary = str(getattr(entry, 'summary', '') or getattr(entry, 'description', '') or '').strip()
                    published = str(getattr(entry, 'published', 'حديثاً')).strip()
                    if not title:
                        continue
                    cursor_p.execute("SELECT id FROM articles WHERE title_ar = ?", (title,))
                    if not cursor_p.fetchone():
                        cursor_p.execute("""
                            INSERT INTO articles (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, published_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved')
                        """, (title, summary, title, summary, title, summary, category, name, published))
            except Exception:
                pass
        conn_p.commit()
        conn_p.close()
    except Exception:
        pass

app = FastAPI(title="BASHAN SYSTEM")
app.mount("/music", StaticFiles(directory=UPLOAD_DIR), name="music")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/videos", StaticFiles(directory=VIDEOS_DIR), name="videos")

scheduler = BackgroundScheduler()
@app.on_event("startup")
def startup_event():
    init_dbs()
    fetch_portal_news()
    try:
        scheduler.add_job(fetch_portal_news, 'interval', minutes=15)
        scheduler.start()
    except Exception:
        pass

@app.get("/logo.png")
def get_logo():
    if os.path.exists("logo.png"):
        return FileResponse("logo.png")
    return HTMLResponse(status_code=404)

@app.get("/api/get_images")
def get_images():
    if os.path.exists(IMAGES_DIR):
        return [f"/images/{f}" for f in os.listdir(IMAGES_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    return []

@app.get("/api/get_songs")
def get_songs():
    if os.path.exists(UPLOAD_DIR):
        return [f"/music/{f}" for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))]
    return []

@app.get("/api/get_videos")
def get_videos():
    if os.path.exists(VIDEOS_DIR):
        return sorted([f"/videos/{f}" for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))], key=str.lower)
    return []

@app.get("/api/live_state")
def get_live_state():
    state = CURRENT_STATE.copy()
    state["server_time"] = time.time()
    return state


# --- 3. نظام لوحة التحكم للبث والشريط ---
ADMIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN - لوحة تحكم البث المباشر</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 20px; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #121824; padding: 20px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; font-size: 13px; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-left: 3px; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-fetch { background: #3b82f6; color: white; }
        input, textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>BASHAN LINE — لوحة تحكم البث المباشر 🔒</h1>
    <div style="margin-bottom: 15px;">
        <a href="/admin/fetch_now" class="btn btn-fetch" style="padding: 8px 16px; text-decoration: none; display: inline-block;">سحب الأخبار فوراً 🔄</a>
        <a href="/news/admin" style="background: #d4af37; color: black; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; margin-right: 10px;">الانتقال لوحة إخبار الموقع 📰</a>
    </div>
    <div class="grid">
        <div>
            <div class="card" style="border: 2px solid #3b82f6;">
                <h2 style="color: #60a5fa;">📺 وضع العرض السريع</h2>
                <a href="/switch_to_images"><button class="btn" style="background:#3b82f6; color:#fff; width:31%; padding:10px;">عرض الصور 🖼️</button></a>
                <a href="/switch_to_video"><button class="btn" style="background:#22c55e; color:#fff; width:31%; padding:10px;">الفيديو المحلي 🎬</button></a>
                <a href="/admin/clear_stage"><button class="btn" style="background:#c62828; color:#fff; width:30%; padding:10px;">إيقاف الكل ❌</button></a>
            </div>
            <div class="card" style="border: 2px solid #ff0000;">
                <h2 style="color: #ff4444;">▶️ رابط البث المباشر (يوتيوب)</h2>
                <form action="/set_youtube_video" method="post">
                    <input type="text" name="youtube_url" value="{{ current_youtube }}" placeholder="ضع رابط يوتيوب هنا..." required>
                    <button type="submit" class="btn" style="background:#ff0000; color:#fff; width:100%;">تشغيل يوتيوب فوراً 🚀</button>
                </form>
            </div>
        </div>
        <div>
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">✍️ إضافة خبر جديد للشريط</h2>
                <form action="/admin/add_ticker_news" method="post">
                    <input type="text" name="title" placeholder="اكتب نص الخبر..." required>
                    <input type="hidden" name="category" value="السويداء">
                    <button type="submit" class="btn btn-approve" style="width:100%;">نشر مباشر 🚀</button>
                </form>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(username: str = Depends(verify_admin)):
    return HTMLResponse(ADMIN_HTML.replace("{{ current_youtube }}", CURRENT_STATE["youtube_url"]))

@app.get("/admin/fetch_now")
def fetch_now_endpoint(username: str = Depends(verify_admin)):
    fetch_portal_news()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/admin/add_ticker_news")
def add_ticker_news(title: str = Form(...), category: str = Form(...), username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, 'لوحة البث', 'approved')", (title, category))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/switch_to_images")
def switch_to_images(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "image"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/switch_to_video")
def switch_to_video(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/admin/clear_stage")
def clear_stage(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "none"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_youtube_video")
def set_youtube_video(youtube_url: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "youtube"
    CURRENT_STATE["youtube_url"] = youtube_url.strip()
    return HTMLResponse("<script>window.location.href='/admin';</script>")


# --- 4. واجهة شريط البث ---
TICKER_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN LINE - البث المباشر</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #02040a; color: #fff; font-family: 'Segoe UI', Tahoma, sans-serif; overflow: hidden; }
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: inline-block; white-space: nowrap; padding-right: 100%; font-size: 17px; color: #ffffff; animation: ticker 60s linear infinite; }
        .ticker-item { display: inline-block; padding: 0 20px; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(100%, 0, 0); } }
    </style>
</head>
<body>
    <div class="ticker-container">
        <div class="ticker-title">أخبار عالمية</div>
        <div class="ticker-wrap"><div class="ticker-move" id="ticker-content">جاري التحميل...</div></div>
    </div>
    <script>
        async function updateTickers() {
            try {
                const res = await fetch('/api/approved_news');
                const data = await res.json();
                let html = data.bottom?.length ? data.bottom.map(i => `<span class="ticker-item">${i.title}</span> • `).join('') : '<span class="ticker-item">شبكة باشان الإعلامية</span> • ';
                document.getElementById('ticker-content').innerHTML = html;
            } catch(e){}
        }
        updateTickers();
        setInterval(updateTickers, 10000);
    </script>
</body>
</html>
"""

@app.get("/ticker", response_class=HTMLResponse)
def get_ticker():
    return TICKER_HTML

@app.get("/api/approved_news")
def get_approved_news():
    bottom_items = []
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, category, source_name FROM news ORDER BY id DESC LIMIT 50")
        for r in cursor.fetchall(): bottom_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
    finally:
        conn.close()
    return {"top": [], "bottom": bottom_items}


# --- 5. الموقع الإخباري الاحترافي المتعدد اللغات مع السحب التلقائي (RSS) ---
PORTAL_HOME_HTML = """
<!DOCTYPE html>
<html dir="{{ 'rtl' if lang != 'en' else 'ltr' }}" lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <title>BASHAN NEWS PORTAL</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 0; }
        header { background: #1e293b; border-bottom: 2px solid #3b82f6; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; }
        h1 { color: #60a5fa; margin: 0; font-size: 24px; }
        .lang-switch a { color: #fff; margin-left: 15px; text-decoration: none; padding: 5px 10px; background: #334155; border-radius: 4px; font-size: 14px; }
        .lang-switch a.active { background: #3b82f6; font-weight: bold; }
        .container { max-width: 1000px; margin: 30px auto; padding: 0 20px; }
        .article-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .article-title { font-size: 20px; font-weight: bold; color: #38bdf8; margin-bottom: 10px; }
        .article-meta { font-size: 12px; color: #94a3b8; margin-bottom: 15px; }
        .article-content { font-size: 15px; line-height: 1.6; color: #cbd5e1; }
        .admin-link { display: inline-block; margin-top: 20px; background: #d4af37; color: #000; padding: 10px 20px; border-radius: 5px; text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <header>
        <h1>📰 BASHAN NEWS PORTAL (Live RSS)</h1>
        <div class="lang-switch">
            <a href="/news?lang=ar" class="{{ 'active' if lang == 'ar' else '' }}">العربية</a>
            <a href="/news?lang=en" class="{{ 'active' if lang == 'en' else '' }}">English</a>
            <a href="/news?lang=he" class="{{ 'active' if lang == 'he' else '' }}">עברית</a>
        </div>
    </header>
    <div class="container">
        <h2 style="border-bottom: 2px solid #334155; padding-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
            <span>{% if lang == 'ar' %}أحدث الأخبار والوكالات العالمية{% elif lang == 'en' %}Latest Global News{% else %}חדשות עולמיות אחרונות{% endif %}</span>
            <a href="/news/fetch_rss" style="font-size: 14px; background: #3b82f6; color: #fff; padding: 5px 12px; border-radius: 4px; text-decoration: none;">تحديث الأخبار الآن 🔄</a>
        </h2>
        
        {% if articles %}
            {% for art in articles %}
            <div class="article-card">
                <div class="article-title">{{ art[1] }}</div>
                <div class="article-meta">🌐 المصدر: {{ art[4] }} | 🕒 {{ art[5] or 'اليوم' }}</div>
                <div class="article-content">{{ art[2] }}</div>
            </div>
            {% endfor %}
        {% else %}
            <p style="text-align: center; color: #94a3b8; padding: 40px;">جاري سحب الأخبار من الوكالات...</p>
        {% endif %}
        
        <div style="text-align: center; margin-top: 40px;">
            <a href="/news/admin" class="admin-link">⚙️ لوحة إدارة الموقع الإخباري (Admin)</a>
        </div>
    </div>
</body>
</html>
"""

PORTAL_ADMIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>لوحة تحكم الموقع الإخباري</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: #1e293b; padding: 30px; border-radius: 8px; border: 1px solid #334155; }
        h1 { color: #d4af37; border-bottom: 2px solid #334155; padding-bottom: 10px; }
        input, textarea { width: 100%; padding: 10px; background: #0f172a; color: #fff; border: 1px solid #475569; border-radius: 4px; box-sizing: border-box; margin-bottom: 15px; }
        .btn { background: #3b82f6; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; width: 100%; }
        .back-link { display: inline-block; margin-bottom: 20px; color: #38bdf8; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/news" class="back-link">← العودة إلى الموقع الإخباري</a>
        <h1>⚙️ لوحة إدارة الموقع الإخباري والسحب التلقائي</h1>
        <div style="margin-bottom: 20px;">
            <a href="/news/fetch_rss" style="background: #2e7d32; color: #fff; padding: 10px 20px; border-radius: 5px; text-decoration: none; font-weight: bold; display: inline-block;">سحب الأخبار من كافة الوكالات الآن 🔄</a>
        </div>
        <form action="/news/admin/add" method="post">
            <label>عنوان المقال:</label>
            <input type="text" name="title_ar" required>
            <label>محتوى المقال:</label>
            <textarea name="content_ar" rows="4" required></textarea>
            <label>التصنيف:</label>
            <input type="text" name="category" value="عام" required>
            <button type="submit" class="btn">نشر المقال يدوياً 🚀</button>
        </form>
    </div>
</body>
</html>
"""

@app.get("/news", response_class=HTMLResponse)
def portal_home(lang: str = "ar"):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title_ar, content_ar, category, source_name, published_at FROM articles WHERE status='approved' ORDER BY id DESC LIMIT 40")
    articles = cursor.fetchall()
    conn.close()
    return Template(PORTAL_HOME_HTML).render(articles=articles, lang=lang)

@app.get("/news/fetch_rss")
def trigger_fetch_rss():
    fetch_portal_news()
    return HTMLResponse("<script>alert('تم سحب الأخبار وتحديث الموقع بنجاح!'); window.location.href='/news';</script>")

@app.get("/news/admin", response_class=HTMLResponse)
def portal_admin_page(username: str = Depends(verify_portal_admin)):
    return HTMLResponse(PORTAL_ADMIN_HTML)

@app.post("/news/admin/add")
def portal_admin_add(
    title_ar: str = Form(...),
    content_ar: str = Form(...),
    category: str = Form("عام"),
    username: str = Depends(verify_portal_admin)
):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO articles (title_ar, content_ar, category, source_name, published_at, status)
        VALUES (?, ?, ?, 'إدارة الموقع', 'اليوم', 'approved')
    """, (title_ar, content_ar, category))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>alert('تم نشر المقال بنجاح!'); window.location.href='/news';</script>")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
