# Vault — Public Library Prototype

A small Flask website for a public, no-account file library.

## Features
- Public gallery with no visitor login or registration
- Drawer menu with categories and Images / Videos / Files filters
- Search by display name, category, and tags
- Image and video previews
- Download buttons
- Light/dark theme toggle (preference saved in the browser)
- One private admin password for uploading and deleting
- No user database; metadata is stored in `library.json`
- Files are stored locally in `uploads/` in this prototype

## Run on Windows

1. Install Python 3.10+ from https://www.python.org/downloads/ (enable "Add Python to PATH").
2. Extract this ZIP.
3. Open Command Prompt in the extracted `public_library_prototype` folder.
4. Run:

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   set ADMIN_PASSWORD=make-a-long-private-password
   set FLASK_SECRET_KEY=replace-with-a-long-random-secret
   py app.py
   ```

5. Open http://127.0.0.1:5000
6. Open http://127.0.0.1:5000/admin/login to upload files.

Default password if you skip setting `ADMIN_PASSWORD`: `change-this-password`.
Do not use that default password on an internet-facing deployment.

## Important: cloud storage

This is a working local prototype, not yet connected to cloud object storage. Uploaded files are written to the `uploads/` folder on the computer running Flask. They will not automatically be available publicly on the internet, and some hosting providers erase local files on redeploy/restart.

To make it a real cloud-hosted library, deploy the frontend/backend and replace the local file save/read/delete operations with a cloud object-storage provider (for example Cloudinary for image/video media or an S3-compatible object-storage service for mixed file types). Keep cloud credentials server-side only. Do not put storage API secrets in frontend JavaScript.

## Safety / production notes
- Use HTTPS and a production WSGI server such as Waitress on Windows or Gunicorn on Linux; don't expose Flask's development server directly to the internet.
- Set a strong `ADMIN_PASSWORD` and `FLASK_SECRET_KEY` environment variable.
- Add rate limiting, upload quotas, file signature/content validation, malware scanning, CSRF protection, and backups before public deployment.
- Uploaded files are public by design. Only upload content you have rights to share.
- Maximum upload size defaults to 200 MB (`MAX_UPLOAD_MB`).
- Accepted file extensions are defined by `ALLOWED_EXTENSIONS` in `app.py`.
