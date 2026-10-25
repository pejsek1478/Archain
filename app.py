import json
import os
import tempfile
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
    g,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from werkzeug.security import check_password_hash, generate_password_hash

import ai

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
TILES_DIR = BASE_DIR / "tiles"
TILES_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'diary.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "dev-secret-change-me"
# Total size of one upload request (all files of one entry together).
# Override with e.g. ARCHAIN_MAX_UPLOAD_MB=500 on a Pi with a big SD card.
MAX_UPLOAD_MB = int(os.environ.get("ARCHAIN_MAX_UPLOAD_MB", "200"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Map tile server - override with ARCHAIN_TILE_URL for local/offline tiles
# Default: OSM. For local tiles: "http://localhost:8080/{z}/{x}/{y}.png" (tileserver-gl)
# For local directory: "/tiles/{z}/{x}/{y}.png" (place tiles in tiles/ dir)
TILE_URL_TEMPLATE = os.environ.get("ARCHAIN_TILE_URL", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")
TILE_ATTRIBUTION = os.environ.get("ARCHAIN_TILE_ATTRIBUTION", "&copy; OpenStreetMap contributors")

# Optional local AI assistant (see README). Everything is configured through ARCHAIN_AI_* variables.
AI_CONFIG = ai.AIConfig()
AI_CLIENT = ai.AIClient(AI_CONFIG)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)


db = SQLAlchemy(app)


entry_people = db.Table(
    "entry_people",
    db.Column("entry_id", db.Integer, db.ForeignKey("entries.id"), primary_key=True),
    db.Column("person_id", db.Integer, db.ForeignKey("people.id"), primary_key=True),
)

entry_users = db.Table(
    "entry_users",
    db.Column("entry_id", db.Integer, db.ForeignKey("entries.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(120), default="Field Archaeologist")
    contact = db.Column(db.String(120))
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text)
    photo_filename = db.Column(db.String(255))


class Person(db.Model):
    __tablename__ = "people"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    affiliation = db.Column(db.String(120))


class Entry(db.Model):
    __tablename__ = "entries"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    event_time = db.Column(db.DateTime)
    location_label = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    weather = db.Column(db.String(120))
    owner = db.relationship("User", backref="owned_entries")
    users = db.relationship("User", secondary=entry_users, backref="entries")
    people = db.relationship("Person", secondary=entry_people, backref="entries")
    attachments = db.relationship("Attachment", backref="entry", cascade="all, delete-orphan")
    tags = db.relationship("Tag", secondary="entry_tags", backref="entries")


entry_tags = db.Table(
    "entry_tags",
    db.Column("entry_id", db.Integer, db.ForeignKey("entries.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
)


class Tag(db.Model):
    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entries.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(120))

    @property
    def kind(self):
        """Coarse file type used by the templates: image, model, pdf or file."""
        name = (self.original_name or "").lower()
        media = (self.media_type or "").lower()
        if media.startswith("image/"):
            return "image"
        if name.endswith((".glb", ".gltf")):
            return "model"
        if media == "application/pdf" or name.endswith(".pdf"):
            return "pdf"
        return "file"


@app.before_request
def initialize_database():
    if getattr(app, "_db_initialized", False):
        return
    db.create_all()
    app._db_initialized = True
    _ensure_first_admin()


@app.before_request
def load_current_user():
    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id else None
    if _needs_setup() and request.endpoint not in {"setup", "static"}:
        return redirect(url_for("setup"))


@app.context_processor
def inject_upload_limits():
    return {
        "max_upload_mb": MAX_UPLOAD_MB, 
        "ai_enabled": AI_CONFIG.enabled,
        "tile_url_template": TILE_URL_TEMPLATE,
        "tile_attribution": TILE_ATTRIBUTION,
    }


@app.errorhandler(413)
def upload_too_large(_error):
    message = (
        f"The upload is larger than the {MAX_UPLOAD_MB} MB limit. "
        "Remove some files or split them across several entries."
    )
    if _is_xhr():
        return jsonify(error=message), 413
    flash(message, "warning")
    return redirect(url_for("index"))


@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))
    query = request.args.get("q", "").strip()
    entries_query = _accessible_entries_query()
    if query:
        entries_query = entries_query.where(
            or_(
                Entry.title.ilike(f"%{query}%"),
                Entry.notes.ilike(f"%{query}%"),
                Entry.tags.any(Tag.name.ilike(f"%{query}%")),
            )
        )
    entries_query = entries_query.options(
        selectinload(Entry.tags), selectinload(Entry.attachments)
    )
    entries = db.session.execute(entries_query.order_by(Entry.created_at.desc())).scalars().all()
    return render_template("index.html", entries=entries, query=query)


@app.route("/map")
def map_view():
    if not g.user:
        return redirect(url_for("login"))
    if g.user.is_admin:
        entries_query = select(Entry)
    else:
        entries_query = select(Entry).where(Entry.users.any(User.id == g.user.id))
    entries = db.session.execute(entries_query.order_by(Entry.created_at.desc())).scalars().all()
    mapped_entries = [
        entry
        for entry in entries
        if entry.latitude is not None and entry.longitude is not None
    ]
    return render_template("map.html", entries=mapped_entries)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if _needs_setup():
        return redirect(url_for("setup"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        user = db.session.execute(select(User).where(User.name == name)).scalar_one_or_none()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            flash("Welcome back!", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials.", "warning")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    flash("Signed out.", "success")
    return redirect(url_for("login"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if db.session.execute(select(User)).first():
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not name or not password:
            flash("Name and password are required.", "warning")
            return render_template("setup.html")
        admin = User(
            name=name,
            password_hash=generate_password_hash(password),
            role="Owner",
            contact=request.form.get("contact", "").strip(),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()
        flash("Admin account created. Please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("setup.html")


@app.route("/entries/new", methods=["GET", "POST"])
def new_entry():
    if not g.user:
        return redirect(url_for("login"))
    users = db.session.execute(
        select(User).where(User.is_admin.is_(False)).order_by(User.name)
    ).scalars().all()
    people = db.session.execute(select(Person).order_by(Person.name)).scalars().all()

    if request.method == "POST":
        event_time = _parse_event_time(request.form.get("event_time"))
        entry = Entry(
            owner_id=g.user.id,
            title=request.form.get("title", "").strip(),
            notes=request.form.get("notes", "").strip(),
            event_time=event_time,
            location_label=request.form.get("location_label", "").strip(),
            latitude=_safe_float(request.form.get("latitude")),
            longitude=_safe_float(request.form.get("longitude")),
            weather=request.form.get("weather", "").strip(),
        )

        if not entry.title or not entry.notes:
            return _form_error(
                "Title and notes are required.",
                users=users,
                people=people,
                entry=entry,
                form_action=url_for("new_entry"),
            )

        selected_users = request.form.getlist("users")
        selected_people = request.form.getlist("people")
        entry.users = [user for user in users if str(user.id) in selected_users]
        entry.people = [person for person in people if str(person.id) in selected_people]
        entry.tags = _parse_tags(request.form.get("tags", ""))

        db.session.add(entry)
        db.session.commit()

        _set_weather_if_missing(entry)
        _save_attachments(entry)
        db.session.commit()
        flash("Entry saved!", "success")
        return _form_redirect(url_for("entry_detail", entry_id=entry.id))

    return render_template(
        "entry_form.html",
        users=users,
        people=people,
        entry=None,
        form_action=url_for("new_entry"),
        event_time_value=_format_datetime_local(datetime.now()),
    )


@app.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
def edit_entry(entry_id):
    entry = db.session.get(Entry, entry_id)
    if not entry:
        flash("Entry not found.", "warning")
        return redirect(url_for("index"))
    if not g.user:
        return redirect(url_for("login"))
    if not _can_edit_entry(entry):
        flash("You do not have permission to edit this entry.", "warning")
        return redirect(url_for("entry_detail", entry_id=entry.id))

    users = db.session.execute(
        select(User).where(User.is_admin.is_(False)).order_by(User.name)
    ).scalars().all()
    people = db.session.execute(select(Person).order_by(Person.name)).scalars().all()

    if request.method == "POST":
        entry.title = request.form.get("title", "").strip()
        entry.notes = request.form.get("notes", "").strip()
        entry.event_time = _parse_event_time(request.form.get("event_time"))
        entry.location_label = request.form.get("location_label", "").strip()
        entry.latitude = _safe_float(request.form.get("latitude"))
        entry.longitude = _safe_float(request.form.get("longitude"))
        entry.weather = request.form.get("weather", "").strip()

        if not entry.title or not entry.notes:
            return _form_error(
                "Title and notes are required.",
                users=users,
                people=people,
                entry=entry,
                form_action=url_for("edit_entry", entry_id=entry.id),
            )

        selected_users = request.form.getlist("users")
        selected_people = request.form.getlist("people")
        entry.users = [user for user in users if str(user.id) in selected_users]
        entry.people = [person for person in people if str(person.id) in selected_people]
        entry.tags = _parse_tags(request.form.get("tags", ""))

        _set_weather_if_missing(entry)
        removed_files = _remove_attachments(entry, request.form.getlist("remove_attachments"))
        _save_attachments(entry)
        db.session.commit()
        _delete_files(removed_files)
        flash("Entry updated.", "success")
        return _form_redirect(url_for("entry_detail", entry_id=entry.id))

    return render_template(
        "entry_form.html",
        users=users,
        people=people,
        entry=entry,
        form_action=url_for("edit_entry", entry_id=entry.id),
        event_time_value=_format_datetime_local(entry.event_time),
    )


@app.route("/entries/<int:entry_id>")
def entry_detail(entry_id):
    entry = db.session.get(Entry, entry_id)
    if not entry:
        flash("Entry not found.", "warning")
        return redirect(url_for("index"))
    if not g.user:
        return redirect(url_for("login"))
    if not _can_view_entry(entry):
        flash("You do not have access to this entry.", "warning")
        return redirect(url_for("index"))
    return render_template("entry_detail.html", entry=entry)


@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
def delete_entry(entry_id):
    entry = db.session.get(Entry, entry_id)
    if not entry:
        flash("Entry already removed.", "warning")
        return redirect(url_for("index"))
    if not g.user:
        return redirect(url_for("login"))
    if not _can_edit_entry(entry):
        flash("You do not have permission to delete this entry.", "warning")
        return redirect(url_for("entry_detail", entry_id=entry.id))
    stored_files = [attachment.filename for attachment in entry.attachments]
    db.session.delete(entry)
    db.session.commit()
    _delete_files(stored_files)
    flash("Entry deleted.", "success")
    return redirect(url_for("index"))


@app.route("/assistant")
def assistant():
    if not g.user:
        return redirect(url_for("login"))
    if not AI_CONFIG.enabled:
        flash("The AI assistant is switched off (ARCHAIN_AI=off).", "warning")
        return redirect(url_for("index"))
    entries = _ai_entries()
    focus = None
    focus_id = request.args.get("entry", type=int)
    if focus_id:
        focus = next(({"id": e["id"], "title": e["title"]} for e in entries if e["id"] == focus_id), None)
    return render_template(
        "assistant.html",
        stats=ai.build_stats(entries),
        focus=focus,
        ai_info=AI_CLIENT.describe(),
    )


@app.route("/assistant/status")
def assistant_status():
    if not g.user:
        return jsonify(error="Sign in required."), 401
    if not AI_CONFIG.enabled:
        return jsonify(enabled=False, state="disabled"), 404
    return jsonify(AI_CLIENT.status())


@app.route("/assistant/models")
def assistant_models():
    if not g.user:
        return jsonify(error="Sign in required."), 401
    if not AI_CONFIG.enabled:
        return jsonify(enabled=False), 404
    if AI_CONFIG.backend != "ollama":
        return jsonify(models=[AI_CONFIG.model])
    models = [name for name in ai.fetch_ollama_models(AI_CONFIG.url) if name]
    current = AI_CLIENT.refresh_model(force=True)
    if not models:
        return jsonify(models=[], current=current, error="No models found. Is Ollama running and a model installed?")
    return jsonify(models=models, current=current)


@app.route("/assistant/warmup", methods=["POST"])
def assistant_warmup():
    if not g.user:
        return jsonify(error="Sign in required."), 401
    if AI_CONFIG.enabled:
        AI_CLIENT.warm_up_async()
    return jsonify(ok=True), 202


@app.route("/assistant/chat", methods=["POST"])
def assistant_chat():
    payload, error = _ai_request_payload()
    if error:
        return error
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify(error="Type a question first."), 400
    focus_id = payload.get("entry")
    focus_id = focus_id if isinstance(focus_id, int) and not isinstance(focus_id, bool) else None
    # Only entries this user may see ever reach the prompt (the focus entry is looked up in the same list).
    entries = _ai_entries()
    messages, sources = ai.build_chat_messages(
        question, payload.get("history"), entries, AI_CONFIG, focus_id=focus_id
    )

    def generate():
        yield _ndjson({"type": "meta", "sources": sources})
        try:
            for event in AI_CLIENT.stream_chat(messages, model=payload.get("model")):
                yield _ndjson(event)
        except ai.AIError as err:
            app.logger.warning("AI chat failed (model %s, HTTP %s): %s", AI_CONFIG.model, err.status, err.message)
            yield _ndjson({"type": "error", "message": err.message})
        except Exception:  # noqa: BLE001 - never leave the browser hanging on a half-open stream
            app.logger.exception("Unexpected error in the AI assistant")
            yield _ndjson({"type": "error", "message": "Unexpected error in the AI assistant."})

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/assistant/suggest", methods=["POST"])
def assistant_suggest():
    payload, error = _ai_request_payload()
    if error:
        return error
    title = str(payload.get("title", ""))[:200]
    notes = str(payload.get("notes", ""))[:4000]
    if len(notes.strip()) < 15:
        return jsonify(error="Write a few more words of field notes first."), 400
    messages = ai.build_suggest_messages(title, notes, ai.popular_tags(_ai_entries()), AI_CONFIG)
    try:
        reply = AI_CLIENT.complete(messages, max_tokens=80, temperature=0.2)
    except ai.AIError as err:
        app.logger.warning("AI suggest failed (model %s, HTTP %s): %s", AI_CONFIG.model, err.status, err.message)
        return jsonify(error=err.message), (429 if err.status == 429 else 503)
    return jsonify(ai.parse_suggestion(reply))


@app.route("/entries/<int:entry_id>/attachments.zip")
def download_attachments(entry_id):
    if not g.user:
        return redirect(url_for("login"))
    entry = db.session.get(Entry, entry_id)
    if not entry:
        flash("Entry not found.", "warning")
        return redirect(url_for("index"))
    if not _can_view_entry(entry):
        flash("You do not have access to this entry.", "warning")
        return redirect(url_for("index"))

    archive = tempfile.TemporaryFile()
    used_names = set()
    # Photos, PDFs and GLB models are already compressed, so just store them.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as bundle:
        for attachment in entry.attachments:
            path = UPLOAD_DIR / attachment.filename
            if not path.is_file():
                continue
            bundle.write(path, arcname=_unique_archive_name(attachment.original_name, used_names))
    if not used_names:
        archive.close()
        flash("This entry has no downloadable attachments.", "warning")
        return redirect(url_for("entry_detail", entry_id=entry.id))
    archive.seek(0)
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"archain-entry-{entry.id}-attachments.zip",
    )


@app.route("/users", methods=["GET", "POST"])
def manage_users():
    if not _require_admin():
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if name and password:
            user = User(
                name=name,
                password_hash=generate_password_hash(password),
                role=request.form.get("role", "").strip(),
                contact=request.form.get("contact", "").strip(),
                is_admin=bool(request.form.get("is_admin")),
            )
            db.session.add(user)
            db.session.commit()
            flash("User added.", "success")
        else:
            flash("Name and password are required.", "warning")
        return redirect(url_for("manage_users"))

    users = db.session.execute(select(User).order_by(User.name)).scalars().all()
    return render_template("users.html", users=users)


@app.route("/directory")
def user_directory():
    if not g.user:
        return redirect(url_for("login"))
    users = db.session.execute(select(User).order_by(User.name)).scalars().all()
    return render_template("user_directory.html", users=users)


@app.route("/users/<int:user_id>")
def user_profile(user_id):
    if not g.user:
        return redirect(url_for("login"))
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("user_directory"))
    entries_query = select(Entry).where(
        or_(Entry.owner_id == user.id, Entry.users.any(User.id == user.id))
    )
    entries = db.session.execute(entries_query.order_by(Entry.created_at.desc())).scalars().all()
    return render_template("user_profile.html", profile=user, entries=entries)


@app.route("/users/<int:user_id>/profile", methods=["GET", "POST"])
def edit_profile(user_id):
    if not g.user:
        return redirect(url_for("login"))
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("user_directory"))
    if not (g.user.is_admin or g.user.id == user.id):
        flash("You do not have permission to edit this profile.", "warning")
        return redirect(url_for("user_profile", user_id=user.id))

    if request.method == "POST":
        user.name = request.form.get("name", "").strip() or user.name
        user.role = request.form.get("role", "").strip()
        user.contact = request.form.get("contact", "").strip()
        user.bio = request.form.get("bio", "").strip()
        file = request.files.get("photo")
        if file and file.filename:
            safe_name = _sanitize_filename(file.filename)
            stored_name = f"user_{user.id}_{int(datetime.utcnow().timestamp())}_{safe_name}"
            path = UPLOAD_DIR / stored_name
            file.save(path)
            user.photo_filename = stored_name
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("user_profile", user_id=user.id))

    return render_template("edit_profile.html", profile=user)


@app.route("/users/<int:user_id>/password", methods=["POST"])
def change_password(user_id):
    if not g.user:
        return redirect(url_for("login"))
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("user_directory"))
    if not (g.user.is_admin or g.user.id == user.id):
        flash("You do not have permission to change this password.", "warning")
        return redirect(url_for("user_profile", user_id=user.id))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if g.user.id == user.id and not check_password_hash(user.password_hash, current_password):
        flash("Current password is incorrect.", "warning")
        return redirect(url_for("user_profile", user_id=user.id))
    if not new_password or new_password != confirm_password:
        flash("New password and confirmation must match.", "warning")
        return redirect(url_for("user_profile", user_id=user.id))

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash("Password updated.", "success")
    return redirect(url_for("user_profile", user_id=user.id))


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def edit_user(user_id):
    if not _require_admin():
        return redirect(url_for("index"))
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("manage_users"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "warning")
            return render_template("edit_user.html", user=user)
        user.name = name
        user.role = request.form.get("role", "").strip()
        user.contact = request.form.get("contact", "").strip()
        user.is_admin = bool(request.form.get("is_admin"))
        password = request.form.get("password", "")
        if password:
            user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash("User updated.", "success")
        return redirect(url_for("manage_users"))

    return render_template("edit_user.html", user=user)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    if not _require_admin():
        return redirect(url_for("index"))
    user = db.session.get(User, user_id)
    if not user:
        flash("User already removed.", "warning")
        return redirect(url_for("manage_users"))
    if user.id == g.user.id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("manage_users"))
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("manage_users"))


@app.route("/people", methods=["GET", "POST"])
def manage_people():
    if not _require_admin():
        return redirect(url_for("index"))
    if request.method == "POST":
        # Handle delete
        delete_id = request.form.get("delete_id", type=int)
        if delete_id:
            person = db.session.get(Person, delete_id)
            if person:
                db.session.delete(person)
                db.session.commit()
                flash("Person deleted.", "success")
            else:
                flash("Person not found.", "warning")
            return redirect(url_for("manage_people"))

        # Handle add
        name = request.form.get("name", "").strip()
        if name:
            person = Person(
                name=name,
                affiliation=request.form.get("affiliation", "").strip(),
            )
            db.session.add(person)
            db.session.commit()
            flash("Person added.", "success")
        else:
            flash("Name is required.", "warning")
        return redirect(url_for("manage_people"))

    people = db.session.execute(select(Person).order_by(Person.name)).scalars().all()
    return render_template("people.html", people=people)


@app.route("/tags.json")
def tag_list():
    """Existing tag names (most used first) for the entry form autocomplete.

    Only tags from entries the signed-in user may see, so names never leak across entries.
    """
    if not g.user:
        return jsonify(tags=[]), 401
    query = _accessible_entries_query().options(selectinload(Entry.tags))
    entries = db.session.execute(query).scalars().all()
    counts = Counter(tag.name for entry in entries for tag in entry.tags)
    return jsonify(tags=sorted(counts, key=lambda name: (-counts[name], name)))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    if not g.user:
        return redirect(url_for("login"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/tiles/<path:path>")
def tile_file(path):
    """Serve local map tiles from tiles/ directory for offline use."""
    if not g.user:
        return redirect(url_for("login"))
    return send_from_directory(TILES_DIR, path)


@app.route("/weather")
def weather_lookup():
    if not g.user:
        return {"weather": ""}, 401
    latitude = _safe_float(request.args.get("lat"))
    longitude = _safe_float(request.args.get("lon"))
    if latitude is None or longitude is None:
        return {"weather": ""}, 400
    summary = _fetch_weather(latitude, longitude)
    return {"weather": summary or ""}, 200


def _safe_float(value):
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _save_attachments(entry):
    for uploaded in request.files.getlist("attachments"):
        if not uploaded or not uploaded.filename:
            continue
        safe_name = _sanitize_filename(uploaded.filename) or "file"
        # uuid keeps names unique even when many files arrive in the same second
        stored_name = f"{entry.id}_{uuid.uuid4().hex[:8]}_{safe_name}"
        uploaded.save(UPLOAD_DIR / stored_name)
        attachment = Attachment(
            entry_id=entry.id,
            filename=stored_name,
            original_name=uploaded.filename,
            media_type=uploaded.mimetype,
        )
        db.session.add(attachment)


def _remove_attachments(entry, raw_ids):
    """Delete the selected attachment rows and return their stored filenames."""
    wanted = {value for value in raw_ids if value.isdigit()}
    removed = []
    for attachment in list(entry.attachments):
        if str(attachment.id) in wanted:
            removed.append(attachment.filename)
            db.session.delete(attachment)
    return removed


def _delete_files(filenames):
    for name in filenames:
        try:
            (UPLOAD_DIR / name).unlink(missing_ok=True)
        except OSError:
            app.logger.warning("Could not remove upload %s", name)


def _unique_archive_name(original_name, used_names):
    base = Path((original_name or "file").replace("\\", "/")).name or "file"
    candidate = base
    counter = 2
    while candidate in used_names:
        stem, suffix = Path(base).stem, Path(base).suffix
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    used_names.add(candidate)
    return candidate


def _sanitize_filename(filename):
    cleaned = "".join(char for char in filename if char.isalnum() or char in (".", "_", "-"))
    return cleaned[-120:]


def _accessible_entries_query():
    """Entries the signed-in user may see: admins everything, others their own and shared ones."""
    if g.user.is_admin:
        return select(Entry)
    return select(Entry).where(or_(Entry.owner_id == g.user.id, Entry.users.any(User.id == g.user.id)))


def _ai_entries():
    query = _accessible_entries_query().options(
        selectinload(Entry.tags),
        selectinload(Entry.people),
        selectinload(Entry.attachments),
        selectinload(Entry.owner),
    )
    entries = [
        {
            "id": entry.id,
            "title": entry.title,
            "notes": entry.notes,
            "when": entry.event_time or entry.created_at,
            "location": entry.location_label,
            "lat": entry.latitude,
            "lon": entry.longitude,
            "weather": entry.weather,
            "tags": sorted(tag.name for tag in entry.tags),
            "people": sorted(person.name for person in entry.people),
            "author": entry.owner.name if entry.owner else None,
            "files": len(entry.attachments),
        }
        for entry in db.session.execute(query).scalars().all()
    ]
    entries.sort(key=lambda item: item["when"] or datetime.min, reverse=True)
    return entries


def _ai_request_payload():
    """Common checks for the JSON AI endpoints. Returns (payload, error_response)."""
    if not g.user:
        return None, (jsonify(error="Sign in required."), 401)
    if not AI_CONFIG.enabled:
        return None, (jsonify(error="The AI assistant is switched off."), 404)
    # Requiring a JSON content type also blocks cross-site HTML form posts.
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        return None, (jsonify(error="Send a JSON body."), 400)
    return payload, None


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


def _is_xhr():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _form_redirect(url):
    """The entry form submits via XHR (for the upload progress bar); plain posts still work."""
    if _is_xhr():
        return jsonify(redirect=url)
    return redirect(url)


def _form_error(message, **context):
    if _is_xhr():
        db.session.rollback()
        return jsonify(error=message), 400
    flash(message, "warning")
    return render_template(
        "entry_form.html",
        event_time_value=_format_datetime_local(context["entry"].event_time),
        **context,
    )


def _parse_event_time(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _format_datetime_local(value):
    if not value:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def _can_edit_entry(entry):
    return g.user and (g.user.is_admin or entry.owner_id == g.user.id)


def _can_view_entry(entry):
    if not g.user:
        return False
    if g.user.is_admin or entry.owner_id == g.user.id:
        return True
    return any(user.id == g.user.id for user in entry.users)


def _require_admin():
    if not g.user:
        flash("Please sign in to continue.", "warning")
        return False
    if not g.user.is_admin:
        flash("Admin access required.", "warning")
        return False
    return True


def _ensure_first_admin():
    if db.session.execute(select(User)).first():
        return
    app.logger.info("No users found. Visit /setup to create the first admin account.")


def _needs_setup():
    return not db.session.execute(select(User)).first()


def _parse_tags(raw_value):
    tags = []
    for token in raw_value.split(","):
        name = token.strip().lower()
        if not name:
            continue
        tag = db.session.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()
        if not tag:
            tag = Tag(name=name)
            db.session.add(tag)
        tags.append(tag)
    return tags


def _set_weather_if_missing(entry):
    if entry.weather or entry.latitude is None or entry.longitude is None:
        return
    summary = _fetch_weather(entry.latitude, entry.longitude)
    if summary:
        entry.weather = summary


def _fetch_weather(latitude, longitude):
    import subprocess

    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                f"https://wttr.in/{latitude},{longitude}?format=%C+%t",
            ],
            check=True,
            timeout=5,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return result.stdout.strip()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
