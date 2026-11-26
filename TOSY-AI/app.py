import os, sqlite3, secrets, time
from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from ai_gateway import ai_reply, ai_analyze_image

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "tosy.db"))
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, mode=0o700, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or "dev-only-change-this-secret"
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
ALLOWED = {"txt", "md", "pdf", "png", "jpg", "jpeg"}

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    conn = g.pop("db", None)
    if conn: conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      plan TEXT NOT NULL DEFAULT 'free', plan_expires_at TEXT,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('user','assistant')),
      content TEXT NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id,id);
    CREATE TABLE IF NOT EXISTS payment_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
      reference TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL,
      plan TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def current_user():
    if not session.get("user_id"): return None
    return db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

def effective_plan(user):
    """Only grant Pro while its database plan is active and not expired."""
    if not user or user["plan"] != "pro":
        return "free"
    expiry = user["plan_expires_at"]
    if expiry:
        try:
            expires_at = datetime.fromisoformat(expiry)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                return "free"
        except (TypeError, ValueError):
            app.logger.warning("Invalid Pro expiry value; treating account as Free")
            return "free"
    return "pro"

@app.route("/")
def home():
    return render_template("index.html", user=current_user())

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        if not name or len(name)>80 or "@" not in email or len(password)<8:
            flash("Enter a name, valid email and password of at least 8 characters.","error")
            return render_template("signup.html")
        try:
            cur=db().execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
              (name,email,generate_password_hash(password),datetime.now(timezone.utc).isoformat()))
            db().commit(); session.clear(); session["user_id"]=cur.lastrowid
            return redirect(url_for("chat"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.","error")
    return render_template("signup.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        user=db().execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if user and check_password_hash(user["password_hash"],request.form.get("password","")):
            session.clear(); session["user_id"]=user["id"]
            return redirect(url_for("chat"))
        flash("Email or password is incorrect.","error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/chat")
@login_required
def chat():
    return render_template("chat.html", user=current_user())

@app.route("/api/history")
@login_required
def history():
    rows=db().execute("SELECT role,content,created_at FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 60",(session["user_id"],)).fetchall()
    return jsonify({"messages":[dict(r) for r in reversed(rows)]})

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data=request.get_json(silent=True) or {}
    prompt=(data.get("message") or "").strip()
    if not prompt or len(prompt)>12000: return jsonify(error="Message is empty or too long."),400
    user=current_user()
    if user["plan"]=="free":
        count=db().execute("SELECT COUNT(*) n FROM messages WHERE user_id=? AND role='user' AND date(created_at)=date('now')",(user["id"],)).fetchone()["n"]
        if count>=25: return jsonify(error="You've reached today's free message limit. Check the plans page for Pro options."),429
    hist=db().execute("SELECT role,content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 12",(user["id"],)).fetchall()
    history=[dict(x) for x in reversed(hist)]
    now=datetime.now(timezone.utc).isoformat()
    db().execute("INSERT INTO messages(user_id,role,content,created_at) VALUES(?,?,?,?)",(user["id"],"user",prompt,now)); db().commit()
    try:
        answer=ai_reply(prompt, history, plan=effective_plan(user))
    except Exception:
        app.logger.exception("AI provider request failed")
        answer="I’m having trouble generating a reply right now. Please try again in a moment."
    db().execute("INSERT INTO messages(user_id,role,content,created_at) VALUES(?,?,?,?)",(user["id"],"assistant",answer,datetime.now(timezone.utc).isoformat())); db().commit()
    return jsonify(reply=answer)


@app.route("/api/analyze-image", methods=["POST"])
@login_required
def analyze_image():
    image = request.files.get("file")
    if not image or not image.filename:
        return jsonify(error="Choose an image first."), 400
    mime_type = (image.mimetype or "").lower()
    if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        return jsonify(error="Please upload a PNG, JPG or WEBP image."), 400
    raw = image.read(10 * 1024 * 1024 + 1)
    if not raw:
        return jsonify(error="The selected image is empty."), 400
    if len(raw) > 10 * 1024 * 1024:
        return jsonify(error="Images must be 10 MB or smaller."), 413
    # Check file signatures rather than trusting the browser-provided MIME type.
    valid = (mime_type == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")) or (
        mime_type == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")
    ) or (mime_type == "image/webp" and len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
    if not valid:
        return jsonify(error="The image content does not match its file type."), 400
    user = current_user()
    prompt = request.form.get("prompt", "").strip() or "Describe this image and help me understand it."
    try:
        answer = ai_analyze_image(raw, mime_type, prompt, plan=effective_plan(user))
    except Exception:
        app.logger.exception("Image understanding request failed")
        return jsonify(error="TOSY couldn't understand that image right now. Please try again."), 503
    now = datetime.now(timezone.utc).isoformat()
    db().execute("INSERT INTO messages(user_id,role,content,created_at) VALUES(?,?,?,?)",
                 (user["id"], "user", "[Image uploaded] " + prompt, now))
    db().execute("INSERT INTO messages(user_id,role,content,created_at) VALUES(?,?,?,?)",
                 (user["id"], "assistant", answer, datetime.now(timezone.utc).isoformat()))
    db().commit()
    return jsonify(reply=answer, message="Image analyzed successfully.")

@app.route("/pricing")
def pricing():
    return render_template("pricing.html", user=current_user())

@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    # Safe placeholder: no charge is made. Configure a supported payment provider
    # and server-side webhook verification before enabling real subscriptions.
    plan=(request.json or {}).get("plan")
    if plan not in ("monthly","yearly"): return jsonify(error="Invalid plan."),400
    return jsonify(error="Payments are currently in setup mode. No money has been charged. Configure and verify a payment provider before launch."),503

@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    f=request.files.get("file")
    if not f or not f.filename: return jsonify(error="Choose a file first."),400
    name=secure_filename(f.filename)
    ext=name.rsplit(".",1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED: return jsonify(error="Supported formats: TXT, MD, PDF, PNG and JPG."),400
    if not name or len(name) > 180:
        return jsonify(error="The filename is invalid or too long."), 400

    # Malware scanning is intentionally disabled in this deployment.
    # Keep basic format checks, use a random storage name, and never claim a file is malware-free.
    token = secrets.token_hex(16)
    stored_name = token + "." + ext
    stored_path = os.path.join(UPLOAD_DIR, stored_name)
    try:
        f.save(stored_path)
        with open(stored_path, "rb") as handle:
            head = handle.read(8192)
        valid = True
        if ext == "pdf":
            valid = head.startswith(b"%PDF-")
        elif ext == "png":
            valid = head.startswith(b"\x89PNG\r\n\x1a\n")
        elif ext in {"jpg", "jpeg"}:
            valid = head.startswith(b"\xff\xd8\xff")
        else:
            try:
                with open(stored_path, "r", encoding="utf-8-sig") as handle:
                    content = handle.read()
                valid = "\x00" not in content
            except UnicodeDecodeError:
                valid = False
        if not valid:
            os.remove(stored_path)
            return jsonify(error="The file content does not match its extension or is not valid UTF-8 text."), 400
    except OSError:
        app.logger.exception("File upload storage failed")
        return jsonify(error="TOSY could not store this file. Please try again."), 500

    return jsonify(
        message=f"{name} was uploaded. Malware scanning is currently disabled, so only upload files you trust. File understanding will be connected separately.",
        scanned=False
    )

@app.errorhandler(413)
def too_large(_): return jsonify(error="File is too large. Maximum upload size is 12 MB."),413

@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify(error="That action is not available. Please refresh and try again."), 404
    return render_template("index.html", user=current_user()), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Unexpected application error", exc_info=error)
    if request.path.startswith("/api/"):
        return jsonify(error="Something went wrong on our side. Please try again shortly."), 500
    return render_template("index.html", user=None), 500

@app.errorhandler(Exception)
def unexpected_error(error):
    # Keep technical details in server logs; never expose tracebacks to visitors.
    app.logger.exception("Unhandled request error")
    if request.path.startswith("/api/"):
        return jsonify(error="We couldn’t complete that action. Please try again shortly."), 500
    return render_template("index.html", user=None), 500

@app.route("/health")
def health(): return jsonify(status="ok",app="TOSY AI")

init_db()
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)),debug=os.getenv("FLASK_DEBUG")=="1")
