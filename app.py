import os
import sqlite3
import secrets
import time
import feedparser
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
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
            image_url TEXT,
            published_at TEXT,
            status TEXT DEFAULT 'approved'
        )''')
        
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS portal_sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT DEFAULT 'عالمي')''')
        default_portal_sources = [
            ("BBC News Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "سياسة"),
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي"),
            ("DW Arabic", "https://rss.dw.com/xml/rss-ar-all", "تقارير"),
            ("France 24 Arabic", "https://www.france24.com/ar/rss", "أخبار"),
            ("Reuters World", "https://news.google.com/rss/search?q=site%3Areuters.com&hl=ar&gl=AE&ceid=AE%3Aar", "اقتصاد")
        ]
        cursor_p.executemany("INSERT OR IGNORE INTO portal_sources (name, url, category) VALUES (?, ?, ?)", default_portal_sources)
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
                    if not title: continue
                    cursor.execute("SELECT id FROM news WHERE title = ?", (title,))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'pending')", (title, category, name))
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass

    try:
        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute("SELECT name, url, category FROM portal_sources")
        for name, url, category in cursor_p.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:6]:
                    title = str(getattr(entry, 'title', '') or '').strip()
                    summary = str(getattr(entry, 'summary', '') or getattr(entry, 'description', '') or '').strip()
                    published = str(getattr(entry, 'published', 'منذ ساعة')).strip()
                    if not title: continue
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
    if os.path.exists("logo.png"): return FileResponse("logo.png")
    return HTMLResponse(status_code=404)

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


# --- 3. واجهة الموقع الإخباري الرئيسي ---
PORTAL_HOME_HTML = """
<!DOCTYPE html>
<html dir="{{ 'rtl' if lang != 'en' else 'ltr' }}" lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <title>BASHAN NEWS | شبكة باشان الإخبارية</title>
    <style>
        body { font-family: 'Tahoma', Arial, sans-serif; background: #f3f4f6; color: #111827; margin: 0; padding: 0; }
        .top-bar { background: #b91c1c; color: white; padding: 8px 30px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
        .top-bar a { color: white; text-decoration: none; margin-left: 15px; }
        header { background: #ffffff; border-bottom: 3px solid #b91c1c; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .logo-area h1 { color: #b91c1c; margin: 0; font-size: 28px; font-weight: 900; }
        .logo-area span { font-size: 13px; color: #4b5563; display: block; }
        .nav-links { display: flex; gap: 20px; font-weight: bold; font-size: 15px; }
        .nav-links a { color: #374151; text-decoration: none; }
        .nav-links a:hover { color: #b91c1c; }
        .lang-switch a { background: #e5e7eb; color: #1f2937; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-size: 12px; margin-left: 5px; }
        .lang-switch a.active { background: #b91c1c; color: white; }
        .container { max-width: 1200px; margin: 25px auto; padding: 0 15px; }
        .breaking-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 30px; }
        .main-lead { background: white; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-top: 4px solid #b91c1c; }
        .main-lead img { width: 100%; height: 280px; object-fit: cover; }
        .main-lead-content { padding: 20px; }
        .main-lead-content h2 { font-size: 24px; margin: 0 0 10px 0; color: #1f2937; }
        .main-lead-content p { color: #4b5563; line-height: 1.6; font-size: 15px; }
        .side-news { display: flex; flex-direction: column; gap: 15px; }
        .side-card { background: white; padding: 15px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-right: 3px solid #b91c1c; }
        .side-card h4 { margin: 0 0 8px 0; font-size: 15px; color: #1f2937; line-height: 1.4; }
        .section-title { font-size: 20px; font-weight: bold; border-bottom: 2px solid #b91c1c; padding-bottom: 8px; margin-bottom: 20px; color: #1f2937; }
        .articles-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        .article-card { background: white; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; flex-direction: column; justify-content: space-between; }
        .article-card img { width: 100%; height: 160px; object-fit: cover; }
        .article-body { padding: 15px; }
        .article-title { font-size: 17px; font-weight: bold; color: #1f2937; margin-bottom: 10px; line-height: 1.4; }
        .article-meta { font-size: 12px; color: #9ca3af; border-top: 1px solid #f3f4f6; padding: 12px 15px; display: flex; justify-content: space-between; background: #fafafa; }
        .admin-btn { display: inline-block; background: #1f2937; color: white; padding: 10px 20px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 14px; margin-top: 40px; }
    </style>
</head>
<body>
    <div class="top-bar">
        <div>🌍 شبكة باشان الإخبارية الشاملة — تغطية مستمرة على مدار الساعة</div>
        <div>
            <a href="/news/fetch_rss">🔄 تحديث الأخبار الآن</a>
            <a href="/news/admin">⚙️ لوحة التحكم الشاملة</a>
        </div>
    </div>
    <header>
        <div class="logo-area">
            <h1>BASHAN NEWS</h1>
            <span>باشان الإخبارية • المصدر الموثوق</span>
        </div>
        <div class="nav-links">
            <a href="/news">الرئيسية</a>
            <a href="/news?lang=ar">سياسة</a>
            <a href="/news?lang=ar">اقتصاد</a>
            <a href="/news?lang=ar">تقارير</a>
        </div>
        <div class="lang-switch">
            <a href="/news?lang=ar" class="{{ 'active' if lang == 'ar' else '' }}">العربية</a>
            <a href="/news?lang=en" class="{{ 'active' if lang == 'en' else '' }}">English</a>
            <a href="/news?lang=he" class="{{ 'active' if lang == 'he' else '' }}">עברית</a>
        </div>
    </header>
    <div class="container">
        {% if articles %}
        <div class="breaking-grid">
            <div class="main-lead">
                {% if articles[0][9] %}<img src="{{ articles[0][9] }}" alt="Lead">{% endif %}
                <div class="main-lead-content">
                    <span style="background: #b91c1c; color: white; padding: 3px 8px; font-size: 11px; border-radius: 3px; font-weight: bold;">عاجل رئيسي</span>
                    <h2 style="margin-top: 10px;">
                        {% if lang == 'en' and articles[0][3] %}{{ articles[0][3] }}{% elif lang == 'he' and articles[0][5] %}{{ articles[0][5] }}{% else %}{{ articles[0][1] }}{% endif %}
                    </h2>
                    <p>
                        {% if lang == 'en' and articles[0][4] %}{{ articles[0][4] }}{% elif lang == 'he' and articles[0][6] %}{{ articles[0][6] }}{% else %}{{ articles[0][2] }}{% endif %}
                    </p>
                    <div style="font-size: 12px; color: #6b7280; margin-top: 15px;">🌐 المصدر: {{ articles[0][8] }} | 🕒 {{ articles[0][10] }}</div>
                </div>
            </div>
            <div class="side-news">
                <h3 style="margin: 0; font-size: 16px; color: #b91c1c; border-bottom: 2px solid #b91c1c; padding-bottom: 5px;">أبرز العناوين</h3>
                {% for art in articles[1:4] %}
                <div class="side-card">
                    <h4>{{ art[1] }}</h4>
                    <span style="font-size: 11px; color: #9ca3af;">{{ art[8] }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="section-title">أحدث المقالات والتقارير</div>
        <div class="articles-grid">
            {% for art in articles[4:] %}
            <div class="article-card">
                <div>
                    {% if art[9] %}<img src="{{ art[9] }}" alt="Article Image">{% endif %}
                    <div class="article-body">
                        <div style="font-size: 11px; color: #b91c1c; font-weight: bold; margin-bottom: 5px;">{{ art[7] }}</div>
                        <div class="article-title">{{ art[1] }}</div>
                        <p style="font-size: 13px; color: #4b5563; line-height: 1.5;">{{ art[2][:100] }}...</p>
                    </div>
                </div>
                <div class="article-meta">
                    <span>{{ art[8] }}</span>
                    <span>{{ art[10] }}</span>
                </div>
            </div>
            {% endfor %}
        </div>
        <div style="text-align: center;">
            <a href="/news/admin" class="admin-btn">⚙️ الدخول إلى لوحة الإدارة والتحكم الكاملة (Admin)</a>
        </div>
    </div>
</body>
</html>
"""

# --- 4. لوحة التحكم الإدارية الشاملة ---
PORTAL_ADMIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>لوحة التحكم الإدارية الشاملة | BASHAN</title>
    <style>
        body { font-family: 'Tahoma', sans-serif; background: #f3f4f6; color: #1f2937; margin: 0; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-top: 4px solid #b91c1c; }
        h1 { color: #b91c1c; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; }
        h3 { color: #374151; margin-top: 25px; border-bottom: 1px solid #e5e7eb; padding-bottom: 5px; }
        input, textarea, select { width: 100%; padding: 10px; border: 1px solid #d1d5db; border-radius: 4px; box-sizing: border-box; margin-bottom: 15px; font-family: inherit; }
        .btn { background: #b91c1c; color: white; padding: 12px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; width: 100%; font-size: 15px; }
        .btn-green { background: #2563eb; margin-bottom: 15px; display: inline-block; text-align: center; text-decoration: none; color: white; padding: 10px; border-radius: 4px; font-weight: bold; }
        .back-link { display: inline-block; margin-bottom: 20px; color: #b91c1c; text-decoration: none; font-weight: bold; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/news" class="back-link">← العودة إلى الموقع الإخباري الرئيسي</a>
        <h1>⚙️ لوحة التحكم والتحرير الشاملة للوكالة</h1>
        
        <div style="background: #f8fafc; padding: 15px; border-radius: 6px; border: 1px solid #e2e8f0; margin-bottom: 25px;">
            <h3>🔄 نظام السحب التلقائي (RSS)</h3>
            <p style="font-size: 13px; color: #64748b;">جلب وتحديث أحدث المقالات من الوكالات العالمية فوراً.</p>
            <a href="/news/fetch_rss" class="btn-green" style="width: auto;">سحب الأخبار وتحديث الموقع الآن 🔄</a>
        </div>

        <div style="background: #f8fafc; padding: 15px; border-radius: 6px; border: 1px solid #e2e8f0; margin-bottom: 25px;">
            <h3>📤 رفع الصور والفيديوهات للمكتبة</h3>
            <form action="/news/admin/upload_media" method="post" enctype="multipart/form-data">
                <div class="grid-2">
                    <div>
                        <label>رفع صورة (PNG, JPG, WEBP):</label>
                        <input type="file" name="image_file" accept="image/*">
                    </div>
                    <div>
                        <label>رفع فيديو (MP4, WEBM):</label>
                        <input type="file" name="video_file" accept="video/*">
                    </div>
                </div>
                <button type="submit" class="btn" style="background: #0284c7;">رفع الملفات إلى الخادم 📁</button>
            </form>
        </div>

        <h3>✍️ نشر وتحرير مقال جديد (مع الترجمات واللغات)</h3>
        <form action="/news/admin/add" method="post">
            <div class="grid-2">
                <div>
                    <label>عنوان المقال (بالعربية)*:</label>
                    <input type="text" name="title_ar" required>
                </div>
                <div>
                    <label>التصنيف:</label>
                    <select name="category">
                        <option value="سياسة">سياسة</option>
                        <option value="اقتصاد">اقتصاد</option>
                        <option value="تقارير">تقارير وتحقيقات</option>
                        <option value="عالمي">عالمي</option>
                    </select>
                </div>
            </div>

            <label>محتوى المقال (بالعربية)*:</label>
            <textarea name="content_ar" rows="4" required></textarea>

            <div class="grid-2">
                <div>
                    <label>رابط الصورة المرفوعة (مثال: /images/filename.jpg أو رابط خارجي):</label>
                    <input type="text" name="image_url" placeholder="/images/photo.jpg">
                </div>
                <div>
                    <label>اسم الكاتب أو المصدر:</label>
                    <input type="text" name="source_name" value="هيئة التحرير">
                </div>
            </div>

            <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 15px 0;">
            
            <h4>🌐 الترجمات الإضافية (اختياري)</h4>
            <div class="grid-2">
                <div>
                    <label>Title (English):</label>
                    <input type="text" name="title_en">
                </div>
                <div>
                    <label>Content (English):</label>
                    <textarea name="content_en" rows="2"></textarea>
                </div>
            </div>
            <div class="grid-2">
                <div>
                    <label>כותרת (Hebrew):</label>
                    <input type="text" name="title_he">
                </div>
                <div>
                    <label>תוכן (Hebrew):</label>
                    <textarea name="content_he" rows="2"></textarea>
                </div>
            </div>

            <button type="submit" class="btn">نشر المقال على الموقع فوراً 🚀</button>
        </form>
    </div>
</body>
</html>
"""

@app.get("/news", response_class=HTMLResponse)
def portal_home(lang: str = "ar"):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, image_url, published_at FROM articles WHERE status='approved' ORDER BY id DESC LIMIT 30")
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

@app.post("/news/admin/upload_media")
async def upload_media(image_file: UploadFile = File(None), video_file: UploadFile = File(None), username: str = Depends(verify_portal_admin)):
    if image_file and image_file.filename:
        file_path = os.path.join(IMAGES_DIR, image_file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await image_file.read())
    if video_file and video_file.filename:
        file_path = os.path.join(VIDEOS_DIR, video_file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await video_file.read())
    return HTMLResponse("<script>alert('تم رفع الملف بنجاح!'); window.location.href='/news/admin';</script>")

@app.post("/news/admin/add")
def portal_admin_add(
    title_ar: str = Form(...),
    content_ar: str = Form(...),
    title_en: str = Form(""),
    content_en: str = Form(""),
    title_he: str = Form(""),
    content_he: str = Form(""),
    category: str = Form("سياسة"),
    source_name: str = Form("هيئة التحرير"),
    image_url: str = Form(""),
    username: str = Depends(verify_portal_admin)
):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO articles (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, image_url, published_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'الآن', 'approved')
    """, (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, image_url))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>alert('تم نشر المقال بنجاح!'); window.location.href='/news';</script>")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
