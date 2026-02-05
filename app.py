from datetime import datetime
from pathlib import Path

from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    g,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'diary.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "dev-secret-change-me"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    event_time = db.Column(db.DateTime)
    location_label = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    weather = db.Column(db.String(120))
    context = db.Column(db.String(200))
    owner = db.relationship("User", backref="owned_entries")
    users = db.relationship("User", secondary=entry_users, backref="entries")
    people = db.relationship("Person", secondary=entry_people, backref="entries")
    attachments = db.relationship("Attachment", backref="entry", cascade="all, delete-orphan")


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entries.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(120))


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


@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))
    entries = db.session.execute(select(Entry).order_by(Entry.created_at.desc())).scalars().all()
    return render_template("index.html", entries=entries)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
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
    users = db.session.execute(select(User).order_by(User.name)).scalars().all()
    people = db.session.execute(select(Person).order_by(Person.name)).scalars().all()

    if request.method == "POST":
        event_time_raw = request.form.get("event_time")
        event_time = datetime.fromisoformat(event_time_raw) if event_time_raw else None
        entry = Entry(
            owner_id=g.user.id,
            title=request.form.get("title", "").strip(),
            notes=request.form.get("notes", "").strip(),
            event_time=event_time,
            location_label=request.form.get("location_label", "").strip(),
            latitude=_safe_float(request.form.get("latitude")),
            longitude=_safe_float(request.form.get("longitude")),
            weather=request.form.get("weather", "").strip(),
            context=request.form.get("context", "").strip(),
        )

        if not entry.title or not entry.notes:
            flash("Title and notes are required.", "warning")
            return render_template("entry_form.html", users=users, people=people, entry=entry)

        selected_users = request.form.getlist("users")
        selected_people = request.form.getlist("people")
        entry.users = [user for user in users if str(user.id) in selected_users]
        entry.people = [person for person in people if str(person.id) in selected_people]

        db.session.add(entry)
        db.session.commit()

        _save_attachments(entry)
        db.session.commit()
        flash("Entry saved!", "success")
        return redirect(url_for("entry_detail", entry_id=entry.id))

    return render_template(
        "entry_form.html",
        users=users,
        people=people,
        entry=None,
        form_action=url_for("new_entry"),
        event_time_value="",
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

    users = db.session.execute(select(User).order_by(User.name)).scalars().all()
    people = db.session.execute(select(Person).order_by(Person.name)).scalars().all()

    if request.method == "POST":
        event_time_raw = request.form.get("event_time")
        entry.title = request.form.get("title", "").strip()
        entry.notes = request.form.get("notes", "").strip()
        entry.event_time = datetime.fromisoformat(event_time_raw) if event_time_raw else None
        entry.location_label = request.form.get("location_label", "").strip()
        entry.latitude = _safe_float(request.form.get("latitude"))
        entry.longitude = _safe_float(request.form.get("longitude"))
        entry.weather = request.form.get("weather", "").strip()
        entry.context = request.form.get("context", "").strip()

        if not entry.title or not entry.notes:
            flash("Title and notes are required.", "warning")
            return render_template(
                "entry_form.html",
                users=users,
                people=people,
                entry=entry,
                form_action=url_for("edit_entry", entry_id=entry.id),
                event_time_value=_format_datetime_local(entry.event_time),
            )

        selected_users = request.form.getlist("users")
        selected_people = request.form.getlist("people")
        entry.users = [user for user in users if str(user.id) in selected_users]
        entry.people = [person for person in people if str(person.id) in selected_people]

        _save_attachments(entry)
        db.session.commit()
        flash("Entry updated.", "success")
        return redirect(url_for("entry_detail", entry_id=entry.id))

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
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted.", "success")
    return redirect(url_for("index"))


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
    if not g.user:
        return redirect(url_for("login"))
    if request.method == "POST":
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


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    if not g.user:
        return redirect(url_for("login"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


def _safe_float(value):
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _save_attachments(entry):
    files = request.files.getlist("attachments")
    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        safe_name = _sanitize_filename(uploaded.filename)
        stored_name = f"{entry.id}_{int(datetime.utcnow().timestamp())}_{safe_name}"
        path = UPLOAD_DIR / stored_name
        uploaded.save(path)
        attachment = Attachment(
            entry_id=entry.id,
            filename=stored_name,
            original_name=uploaded.filename,
            media_type=uploaded.mimetype,
        )
        db.session.add(attachment)


def _sanitize_filename(filename):
    return "".join(char for char in filename if char.isalnum() or char in (".", "_", "-"))


def _format_datetime_local(value):
    if not value:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def _can_edit_entry(entry):
    return g.user and (g.user.is_admin or entry.owner_id == g.user.id)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
