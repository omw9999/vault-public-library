import os
import secrets
import mimetypes
from pathlib import Path
from functools import wraps
from datetime import datetime, timezone
from urllib.parse import quote

import cloudinary
import cloudinary.uploader
import cloudinary.api
from flask import Flask, render_template, request, redirect, url_for, abort, session, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-this-password")
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
CLOUDINARY_TAG = "vault-public-library"
if CLOUD_NAME and API_KEY and API_SECRET:
    cloudinary.config(cloud_name=CLOUD_NAME, api_key=API_KEY, api_secret=API_SECRET, secure=True)

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

def cloud_ready():
    return bool(CLOUD_NAME and API_KEY and API_SECRET)

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

def _context_value(resource, key, default=""):
    context = resource.get("context") or {}
    custom = context.get("custom") or {}
    return custom.get(key, default)

def read_library():
    """Read metadata from Cloudinary itself; no user database or local manifest."""
    if not cloud_ready():
        return []
    items = []
    for resource_type in ("image", "video", "raw"):
        cursor = None
        while True:
            params = {"resource_type": resource_type, "max_results": 100, "tags": True, "context": True}
            if cursor:
                params["next_cursor"] = cursor
            try:
                result = cloudinary.api.resources_by_tag(CLOUDINARY_TAG, **params)
            except Exception as exc:
                app.logger.exception("Cloudinary listing failed: %s", exc)
                return items
            for resource in result.get("resources", []):
                context = resource.get("context") or {}
                custom = context.get("custom") or {}
                fmt = resource.get("format", "")
                name = custom.get("display_name") or resource.get("public_id", "file")
                mime = custom.get("mime") or mimetypes.guess_type(name)[0] or ("application/octet-stream" if resource_type == "raw" else f"{resource_type}/{fmt}")
                category = custom.get("category", "Other")
                tags_text = custom.get("search_tags", "")
                stored_name = resource.get("public_id", "")
                items.append({
                    "id": f"{resource_type}:{stored_name}",
                    "stored_name": stored_name,
                    "resource_type": resource_type,
                    "name": name,
                    "category": category if category in ALLOWED_CATEGORIES else "Other",
                    "tags": [x for x in tags_text.split(",") if x],
                    "mime": mime,
                    "size": int(resource.get("bytes", 0)),
                    "uploaded_at": resource.get("created_at", ""),
                    "url": resource.get("secure_url", ""),
                })
            cursor = result.get("next_cursor")
            if not cursor:
                break
    items.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return items

@app.route("/")
def index():
    items = read_library()
    q = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip()
    kind = request.args.get("type", "").strip()
    if category and category != "All":
        items = [x for x in items if x.get("category") == category]
    if kind == "images": items = [x for x in items if is_image(x)]
    elif kind == "videos": items = [x for x in items if is_video(x)]
    elif kind == "files": items = [x for x in items if not is_image(x) and not is_video(x)]
    if q:
        items = [x for x in items if q in " ".join([x.get("name", ""), x.get("category", ""), " ".join(x.get("tags", []))]).lower()]
    return render_template("index.html", items=items, q=q, selected_category=category, selected_type=kind)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    item = next((x for x in read_library() if x.get("stored_name") == filename), None)
    if not item or not item.get("url"): abort(404)
    return redirect(item["url"], code=302)

@app.route("/download/<path:filename>")
def download_file(filename):
    item = next((x for x in read_library() if x.get("stored_name") == filename), None)
    if not item or not item.get("url"): abort(404)
    # Cloudinary serves the stored asset. The browser may preview some media types.
    return redirect(item["url"], code=302)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear(); session["is_admin"] = True
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
    return render_template("admin.html", items=items)


@app.route("/admin/upload", methods=["POST"])
@admin_required
def upload():
    if not cloud_ready():
        flash("Cloud storage is not configured.", "error")
        return redirect(url_for("admin"))

    files = [f for f in request.files.getlist("files") if f and f.filename]

    if not files:
        flash("Choose at least one file.", "error")
        return redirect(url_for("admin"))

    if len(files) > 25:
        flash("Upload a maximum of 25 files at a time.", "error")
        return redirect(url_for("admin"))

    category = request.form.get("category", "Other")
    if category not in ALLOWED_CATEGORIES:
        category = "Other"

    tags_raw = request.form.get("tags", "")
    tags = [x.strip()[:40] for x in tags_raw.split(",") if x.strip()][:12]

    success = 0
    failed = 0

    for uploaded in files:
        original_name = secure_filename(uploaded.filename)
        if not original_name or Path(original_name).suffix.lower() not in ALLOWED_EXTENSIONS:
            failed += 1
            continue

        mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"

        if mime.startswith("image/"):
            resource_type = "image"
        elif mime.startswith(("video/", "audio/")):
            resource_type = "video"
        else:
            resource_type = "raw"

        try:
            cloudinary.uploader.upload(
                uploaded.stream,
                resource_type=resource_type,
                public_id="vault_" + secrets.token_hex(16),
                folder="vault-public-library",
                tags=[
                    CLOUDINARY_TAG,
                    "category_" + category.lower().replace(" ", "_")
                ],
                context={
                    "display_name": original_name[:120],
                    "category": category,
                    "search_tags": ",".join(tags),
                    "mime": mime
                },
                overwrite=False,
                use_filename=False,
                unique_filename=False,
            )
            success += 1
        except Exception:
            failed += 1
            app.logger.exception("Upload failed for %s", original_name)

    if success:
        flash(f"Successfully uploaded {success} file(s).", "success")
    if failed:
        flash(f"{failed} file(s) failed or were unsupported.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/delete/<item_id>", methods=["POST"])
@admin_required
def delete_item(item_id):
    item = next((x for x in read_library() if x.get("id") == item_id), None)
    if not item:
    app.logger.warning("Delete lookup failed: item_id=%r; available_ids=%r",
                       item_id, [x.get("id") for x in read_library()])
    abort(404)
    try:
        cloudinary.uploader.destroy(item["stored_name"], resource_type=item["resource_type"], invalidate=True)
    except Exception:
        app.logger.exception("Cloudinary delete failed")
        flash("Could not delete this cloud file. Check Render logs.", "error")
        return redirect(url_for("admin"))
    flash("File deleted from cloud storage.", "success")
    return redirect(url_for("admin"))

@app.errorhandler(413)
def too_large(_):
    return "Upload too large. Increase MAX_UPLOAD_MB if your cloud plan supports it.", 413

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
