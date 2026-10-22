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
        news_columns = {row[1] for row in cursor.execute("PRAGMA table_info(news)").fetchall()}
        for column, definition in [
            ("category", "TEXT"),
            ("source_name", "TEXT"),
            ("status", "TEXT DEFAULT 'pending'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            if column not in news_columns:
                cursor.execute(f"ALTER TABLE news ADD COLUMN {column} {definition}")
        
        default_sources = [
            ("BBC News عربي", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي"),
            ("Reuters عبر Google News", "https://news.google.com/rss/search?q=site%3Areuters.com&hl=ar&gl=AE&ceid=AE%3Aar", "صحافة عالمية"),
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي"),
            ("i24NEWS عربي عبر Google News", "https://news.google.com/rss/search?q=site%3Ai24news.tv%2Far&hl=ar&gl=IL&ceid=IL%3Aar", "عالمي"),
            ("DW عربي", "https://rss.dw.com/xml/rss-ar-all", "عالمي"),
            ("France 24", "https://www.france24.com/ar/rss", "صحافة عالمية")
        ]
        cursor.executemany("INSERT OR IGNORE INTO sources (name, url, category) VALUES (?, ?, ?)", default_sources)
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
            author TEXT,
            published_at TEXT,
            status TEXT DEFAULT 'approved'
        )''')
        conn_p.commit()
        conn_p.close()
    except Exception:
        pass

def fetch_portal_news():
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
        scheduler.add_job(fetch_portal_news, 'interval', minutes=5)
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
        <a href="/admin/approve_all" style="background: #2e7d32; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; margin-right: 10px;">اعتماد كافة الأخبار التلقائية ✓✓</a>
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

            <div class="card" style="border: 2px solid #4ade80;">
                <h2 style="color: #4ade80;">🎬 اختيار الفيديو المحلي والتحكم به</h2>
                <form action="/set_active_video" method="post">
                    <select name="video_name" required>
                        {% for vid in video_files %}<option value="{{ vid }}" {% if current_video == '/videos/' + vid %}selected{% endif %}>{{ vid }}</option>{% endfor %}
                    </select><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تشغيل هذا الفيديو 🎬</button>
                </form>
            </div>
        </div>

        <div>
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">✍️ إضافة خبر جديد للشريط العلوي يدوياً</h2>
                <form action="/admin/add_ticker_news" method="post">
                    <input type="text" name="title" placeholder="اكتب نص الخبر..." required>
                    <input type="hidden" name="category" value="السويداء">
                    <button type="submit" class="btn btn-approve" style="width:100%;">نشر مباشر 🚀</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 إدارة شريط السويداء (العلوي)</h2>
                <table>
                    <tr><th>الخبر</th><th>الحالة</th><th>الإجراءات</th></tr>
                    {% for item in sweida_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td>{% if item[4] == 'approved' %}<span style="color:#4ade80;">معتمد</span>{% else %}<span style="color:#f59e0b;">معلق</span>{% endif %}</td>
                        <td style="white-space:nowrap;">
                            {% if item[4] == 'pending' %}<a href="/approve/{{ item[0] }}"><button class="btn btn-approve" style="padding:3px 6px;">اعتماد</button></a>{% endif %}
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 6px;">حذف</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>

            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ مراجعة أخبار المواقع للشريط السفلي فقط</h2>
                <table>
                    <tr><th>الخبر</th><th>الحالة</th><th>الإجراءات</th></tr>
                    {% for item in world_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td>{% if item[4] == 'approved' %}<span style="color:#4ade80;">معتمد</span>{% else %}<span style="color:#f59e0b;">معلق</span>{% endif %}</td>
                        <td style="white-space:nowrap;">
                            {% if item[4] == 'pending' %}<a href="/approve/{{ item[0] }}"><button class="btn btn-approve" style="padding:3px 6px;">اعتماد</button></a>{% endif %}
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 6px;">حذف</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE source_name = 'لوحة البث' ORDER BY id DESC LIMIT 50")
    sweida_news = cursor.fetchall()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE source_name IS NOT NULL AND source_name <> 'لوحة البث' ORDER BY id DESC LIMIT 100")
    world_news = cursor.fetchall()
    conn.close()
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    return Template(ADMIN_HTML).render(
        sweida_news=sweida_news, world_news=world_news, music_files=music_files, video_files=video_files,
        sweida_speed=CURRENT_STATE["sweida_speed"], world_speed=CURRENT_STATE["world_speed"],
        current_youtube=CURRENT_STATE["youtube_url"], current_video=CURRENT_STATE["active_video"], current_banner=CURRENT_STATE["breaking_banner"]
    )

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

@app.get("/approve/{news_id}")
def approve_news(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET status = 'approved' WHERE id = ?", (news_id,))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/admin/approve_all")
def approve_all_news(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET status = 'approved' WHERE status = 'pending'")
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/reject/{news_id}")
def reject_news(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM news WHERE id = ?", (news_id,))
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
    CURRENT_STATE["video_playlist_started_at"] = time.time()
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

@app.post("/set_active_video")
def set_active_video(video_name: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    CURRENT_STATE["active_video"] = f"/videos/{video_name}"
    CURRENT_STATE["video_playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

TICKER_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BASHAN LINE - البث المباشر</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #02040a; color: #fff; font-family: 'Segoe UI', Tahoma, sans-serif; overflow: hidden; user-select: none; }
        .corner-logo { position: absolute; top: 65px; right: 15px; z-index: 100; width: 130px; pointer-events: none; }
        .corner-logo img { width: 100%; height: auto; }
        .top-ticker-container { position: absolute; top: 0; left: 0; width: 100%; height: 50px; background: rgba(20, 10, 30, 0.98); border-bottom: 2px solid #7b1fa2; display: flex; align-items: center; z-index: 1000; pointer-events: none; }
        .top-ticker-title { background: linear-gradient(135deg, #7b1fa2, #4a148c); color: #fff; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .center-stage { position: absolute; top: 50px; left: 0; width: 100%; height: calc(100% - 100px); display: flex; justify-content: center; align-items: center; z-index: 10; padding: 15px; box-sizing: border-box; }
        .image-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); background-size: contain; background-repeat: no-repeat; background-position: center; background-color: #000; }
        video.video-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); object-fit: contain; background-color: #000; pointer-events: none; }
        .youtube-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); background-color: #000; pointer-events: none; }
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; pointer-events: none; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: inline-block; white-space: nowrap; padding-right: 100%; font-size: 17px; color: #ffffff; will-change: transform; }
        .ticker-item { display: inline-block; padding: 0 20px; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(100%, 0, 0); } }
    </style>
</head>
<body>
    <div class="corner-logo"><img src="/logo.png" alt="Logo"></div>
    <div class="top-ticker-container">
        <div class="top-ticker-title">أخبار السويداء</div>
        <div class="ticker-wrap"><div class="ticker-move" id="top-ticker-content">جاري التحميل...</div></div>
    </div>
    <div class="center-stage" id="stage-container"></div>
    <div class="ticker-container">
        <div class="ticker-title">أخبار عالمية</div>
        <div class="ticker-wrap"><div class="ticker-move" id="ticker-content">جاري التحميل...</div></div>
    </div>
    <script>
        let imageList = [], videoList = [], lastMediaType = "", lastYoutubeUrl = "", activeVideoUrl = "";
        async function loadAssets() {
            try {
                imageList = await (await fetch('/api/get_images')).json();
                videoList = await (await fetch('/api/get_videos')).json();
            } catch(e){}
        }
        function getYoutubeEmbedUrl(url) {
            let videoId = "";
            if (url.includes('youtu.be/')) { videoId = url.split('youtu.be/')[1]?.split('?')[0]; }
            else if (url.includes('youtube.com/watch')) { videoId = new URLSearchParams(url.split('?')[1]).get('v'); }
            else { videoId = url.trim(); }
            if (!videoId) return "";
            return `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=0&controls=0&disablekb=1&fs=0&iv_load_policy=3&playsinline=1`;
        }
        async function checkLiveState() {
            try {
                const response = await fetch('/api/live_state');
                const state = await response.json();
                const serverTime = state.server_time || (Date.now() / 1000);
                document.getElementById('top-ticker-content').style.animation = `ticker ${state.sweida_speed}s linear infinite`;
                document.getElementById('ticker-content').style.animation = `ticker ${state.world_speed}s linear infinite`;
                const stage = document.getElementById('stage-container');
                if(state.media_type === 'youtube' && state.youtube_url) {
                    let embedUrl = getYoutubeEmbedUrl(state.youtube_url);
                    if(embedUrl && (lastMediaType !== 'youtube' || lastYoutubeUrl !== state.youtube_url)) {
                        stage.innerHTML = `<iframe id="youtube-frame" class="youtube-card" src="${embedUrl}" frameborder="0" allow="autoplay"></iframe>`;
                        lastMediaType = 'youtube'; lastYoutubeUrl = state.youtube_url;
                    }
                } else if(state.media_type === 'video' && state.active_video) {
                    let vidEl = document.getElementById('live-video');
                    if (!vidEl || lastMediaType !== 'video' || activeVideoUrl !== state.active_video) {
                        stage.innerHTML = `<video id="live-video" class="video-card" src="${state.active_video}" autoplay playsinline muted loop></video>`;
                        lastMediaType = 'video'; activeVideoUrl = state.active_video;
                    }
                } else if(state.media_type === 'image') {
                    if(lastMediaType !== 'image') { stage.innerHTML = `<div class="image-card" id="main-image"></div>`; lastMediaType = 'image'; }
                    if(imageList.length > 0) {
                        const idx = Math.floor(serverTime / 6) % imageList.length;
                        document.getElementById('main-image').style.backgroundImage = `url('${imageList[idx]}')`;
                    }
                } else { stage.innerHTML = ``; }
            } catch(e){}
        }
        async function updateTickers() {
            try {
                const res = await fetch('/api/approved_news');
                const data = await res.json();
                let topHtml = data.top?.length ? data.top.map(i => `<span class="ticker-item">${i.title}</span> • `).join('') : '<span class="ticker-item">شبكة باشان الإعلامية</span> • ';
                let bottomHtml = data.bottom?.length ? data.bottom.map(i => `<span class="ticker-item">${i.title}</span> • `).join('') : '<span class="ticker-item">أخبار عالمية</span> • ';
                document.getElementById('top-ticker-content').innerHTML = topHtml;
                document.getElementById('ticker-content').innerHTML = bottomHtml;
            } catch(e){}
        }
        loadAssets(); checkLiveState(); updateTickers();
        setInterval(checkLiveState, 400);
        setInterval(updateTickers, 8000);
    </script>
</body>
</html>
"""

@app.get("/ticker", response_class=HTMLResponse)
def get_ticker():
    return TICKER_HTML

@app.get("/api/approved_news")
def get_approved_news():
    top_items, bottom_items = [], []
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, category, source_name FROM news WHERE lower(trim(status)) = 'approved' AND source_name = 'لوحة البث' ORDER BY id DESC LIMIT 50")
        for r in cursor.fetchall(): top_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
        
        cursor.execute("SELECT title, category, source_name FROM news WHERE lower(trim(status)) = 'approved' AND source_name IS NOT NULL AND source_name <> 'لوحة البث' ORDER BY id DESC LIMIT 50")
        for r in cursor.fetchall(): bottom_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
        
        if not bottom_items:
            cursor.execute("SELECT title, category, source_name FROM news WHERE source_name <> 'لوحة البث' LIMIT 5")
            for r in cursor.fetchall(): bottom_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
    finally:
        conn.close()
    return {"top": top_items, "bottom": bottom_items}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)