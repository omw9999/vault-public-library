import os
import json
import secrets
import mimetypes
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, session, flash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_FILE = BASE_DIR / "library.json"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-this-password")
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

ALLOWED_CATEGORIES = [
    "Memes", "Funny", "Random Clicks", "Informative",
    "Wallpapers", "Nature", "Videos", "Documents", "Other"
]
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp4", ".webm", ".mov", ".m4v",
    ".pdf", ".txt", ".zip", ".rar", ".7z",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".mp3", ".wav", ".ogg"
}

def read_library():
    if not DATA_FILE.exists():
        return []
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []

def write_library(items):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_FILE)

def is_image(item):
    return item.get("mime", "").startswith("image/")

def is_video(item):
    return item.get("mime", "").startswith("video/")

def is_audio(item):
    return item.get("mime", "").startswith("audio/")

def is_admin():
    return session.get("is_admin") is True

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

@app.context_processor
def inject_helpers():
    return dict(is_image=is_image, is_video=is_video, is_audio=is_audio, categories=ALLOWED_CATEGORIES)

@app.route("/")
def index():
    items = read_library()
    q = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip()
    kind = request.args.get("type", "").strip()
    if category and category != "All":
        items = [x for x in items if x.get("category") == category]
    if kind == "images":
        items = [x for x in items if is_image(x)]
    elif kind == "videos":
        items = [x for x in items if is_video(x)]
    elif kind == "files":
        items = [x for x in items if not is_image(x) and not is_video(x)]
    if q:
        items = [x for x in items if q in " ".join([
            x.get("name", ""), x.get("category", ""), " ".join(x.get("tags", []))
        ]).lower()]
    items.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return render_template("index.html", items=items, q=q, selected_category=category, selected_type=kind)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Only filenames recorded in the manifest can be served.
    if not any(x.get("stored_name") == filename for x in read_library()):
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False, conditional=True)

@app.route("/download/<path:filename>")
def download_file(filename):
    item = next((x for x in read_library() if x.get("stored_name") == filename), None)
    if not item:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True, download_name=item.get("name", filename), conditional=True)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin"))
        flash("Incorrect password.", "error")
    return render_template("login.html")

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin():
    items = read_library()
    items.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return render_template("admin.html", items=items)

@app.route("/admin/upload", methods=["POST"])
@admin_required
def upload():
    uploaded = request.files.get("file")
    name = (request.form.get("display_name") or "").strip()
    category = request.form.get("category", "Other")
    tags_raw = request.form.get("tags", "")
    if not uploaded or not uploaded.filename:
        flash("Choose a file first.", "error")
        return redirect(url_for("admin"))
    original_name = secure_filename(uploaded.filename)
    if not original_name:
        flash("That filename is not supported.", "error")
        return redirect(url_for("admin"))
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        flash("File type not allowed. Add it to ALLOWED_EXTENSIONS in app.py if needed.", "error")
        return redirect(url_for("admin"))
    if category not in ALLOWED_CATEGORIES:
        category = "Other"
    stored_name = secrets.token_hex(16) + ext
    target = UPLOAD_DIR / stored_name
    uploaded.save(target)
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    if not name:
        name = uploaded.filename
    tags = [x.strip()[:40] for x in tags_raw.split(",") if x.strip()][:12]
    from datetime import datetime, timezone
    item = {
        "id": secrets.token_hex(8),
        "name": name[:120],
        "stored_name": stored_name,
        "category": category,
        "tags": tags,
        "mime": mime,
        "size": target.stat().st_size,
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }
    items = read_library()
    items.append(item)
    write_library(items)
    flash("File uploaded.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/delete/<item_id>", methods=["POST"])
@admin_required
def delete_item(item_id):
    items = read_library()
    item = next((x for x in items if x.get("id") == item_id), None)
    if not item:
        abort(404)
    path = UPLOAD_DIR / item.get("stored_name", "")
    try:
        if path.is_file() and path.parent.resolve() == UPLOAD_DIR.resolve():
            path.unlink()
    except OSError:
        pass
    write_library([x for x in items if x.get("id") != item_id])
    flash("File deleted.", "success")
    return redirect(url_for("admin"))

@app.errorhandler(413)
def too_large(_):
    return "Upload too large. Increase MAX_UPLOAD_MB if you intentionally want a higher limit.", 413

if __name__ == "__main__":
    # Local prototype only. For public deployment, use a production WSGI server and HTTPS.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
