import csv
import io
import os
import random
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "aceest_fitness.db"

PROGRAMS = {
    "Fat Loss (FL) – 3 day": {"factor": 22, "desc": "3-day full-body fat loss"},
    "Fat Loss (FL) – 5 day": {"factor": 24, "desc": "5-day split, higher volume fat loss"},
    "Muscle Gain (MG) – PPL": {"factor": 35, "desc": "Push/Pull/Legs hypertrophy"},
    "Beginner (BG)": {"factor": 26, "desc": "3-day simple beginner full-body"},
}

EXERCISE_POOLS = {
    "Strength": [
        "Squat",
        "Deadlift",
        "Bench Press",
        "Overhead Press",
        "Pull-Up",
        "Barbell Row",
    ],
    "Hypertrophy": [
        "Leg Press",
        "Incline Dumbbell Press",
        "Lat Pulldown",
        "Lateral Raise",
        "Bicep Curl",
        "Tricep Extension",
    ],
    "Conditioning": [
        "Running",
        "Cycling",
        "Rowing",
        "Burpees",
        "Jump Rope",
        "Kettlebell Swings",
    ],
    "Full Body": [
        "Push-Up",
        "Pull-Up",
        "Lunge",
        "Plank",
        "Dumbbell Row",
        "Dumbbell Press",
    ],
}


def pdf_safe_text(value):
    """Convert common Unicode punctuation to characters supported by core PDF fonts."""
    text = str(value)
    replacements = {
        "–": "-",
        "—": "-",
        "’": "'",
        "‘": "'",
        "“": '\"',
        "”": '\"',
        "•": "-",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text.encode("latin-1", errors="replace").decode("latin-1")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "aceest-dev-secret-change-me"),
        DATABASE=os.environ.get("ACEEST_DB", str(DEFAULT_DB)),
    )

    if test_config:
        app.config.update(test_config)

    init_db(app.config["DATABASE"])

    def get_db():
        conn = sqlite3.connect(app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        return conn

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "username" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    def get_client_or_none(client_id):
        with get_db() as conn:
            return conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

    @app.route("/health")
    def health():
        return {"status": "ok", "service": "ACEest Fitness & Gym"}, 200

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            with get_db() as conn:
                user = conn.execute(
                    "SELECT username, role FROM users WHERE username=? AND password=?",
                    (username, password),
                ).fetchone()
            if user:
                session.clear()
                session["username"] = user["username"]
                session["role"] = user["role"]
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        selected_id = request.args.get("client_id", type=int)
        with get_db() as conn:
            clients = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
            selected = None
            progress = []
            metrics = []
            workouts = []
            generated_program = []
            if selected_id:
                selected = conn.execute("SELECT * FROM clients WHERE id=?", (selected_id,)).fetchone()
                if selected:
                    progress = conn.execute(
                        "SELECT * FROM progress WHERE client_id=? ORDER BY id",
                        (selected_id,),
                    ).fetchall()
                    metrics = conn.execute(
                        "SELECT * FROM metrics WHERE client_id=? ORDER BY date DESC, id DESC",
                        (selected_id,),
                    ).fetchall()
                    workouts = conn.execute(
                        """
                        SELECT w.*, e.name AS exercise_name, e.sets, e.reps, e.weight AS exercise_weight
                        FROM workouts w
                        LEFT JOIN exercises e ON e.workout_id=w.id
                        WHERE w.client_id=?
                        ORDER BY w.date DESC, w.id DESC
                        """,
                        (selected_id,),
                    ).fetchall()
                    generated_program = conn.execute(
                        """
                        SELECT * FROM generated_programs
                        WHERE client_id=?
                        ORDER BY id
                        """,
                        (selected_id,),
                    ).fetchall()

        bmi_info = calculate_bmi(selected["height"], selected["weight"]) if selected else None
        weight_chart = make_weight_chart(metrics)
        return render_template(
            "dashboard.html",
            clients=clients,
            selected=selected,
            progress=progress,
            metrics=metrics,
            workouts=workouts,
            generated_program=generated_program,
            programs=PROGRAMS,
            bmi_info=bmi_info,
            weight_chart=weight_chart,
            today=date.today().isoformat(),
        )

    @app.route("/clients/save", methods=["POST"])
    @login_required
    def save_client():
        client_id = request.form.get("client_id", type=int)
        name = request.form.get("name", "").strip()
        program = request.form.get("program", "").strip()
        if not name or program not in PROGRAMS:
            flash("Client name and a valid program are required.", "error")
            return redirect(url_for("dashboard", client_id=client_id) if client_id else url_for("dashboard"))

        age = positive_int(request.form.get("age"))
        height = positive_float(request.form.get("height"))
        weight = positive_float(request.form.get("weight"))
        target_weight = positive_float(request.form.get("target_weight"))
        target_adherence = bounded_int(request.form.get("target_adherence"), 0, 100)
        membership_status = request.form.get("membership_status", "Active").strip() or "Active"
        membership_end = request.form.get("membership_end", "").strip() or None
        calories = int(weight * PROGRAMS[program]["factor"]) if weight else None

        try:
            with get_db() as conn:
                if client_id:
                    conn.execute(
                        """
                        UPDATE clients
                        SET name=?, age=?, height=?, weight=?, program=?, calories=?,
                            target_weight=?, target_adherence=?, membership_status=?, membership_end=?
                        WHERE id=?
                        """,
                        (
                            name,
                            age,
                            height,
                            weight,
                            program,
                            calories,
                            target_weight,
                            target_adherence,
                            membership_status,
                            membership_end,
                            client_id,
                        ),
                    )
                    saved_id = client_id
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO clients
                        (name, age, height, weight, program, calories, target_weight,
                         target_adherence, membership_status, membership_end)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            name,
                            age,
                            height,
                            weight,
                            program,
                            calories,
                            target_weight,
                            target_adherence,
                            membership_status,
                            membership_end,
                        ),
                    )
                    saved_id = cursor.lastrowid
                conn.commit()
            flash(f"Client {name} saved successfully. Estimated calories: {calories or 'N/A'}.", "success")
            return redirect(url_for("dashboard", client_id=saved_id))
        except sqlite3.IntegrityError:
            flash("A client with this name already exists.", "error")
            return redirect(url_for("dashboard", client_id=client_id) if client_id else url_for("dashboard"))

    @app.route("/clients/<int:client_id>/progress", methods=["POST"])
    @login_required
    def add_progress(client_id):
        client = get_client_or_none(client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("dashboard"))
        week = request.form.get("week", "").strip()
        adherence = bounded_int(request.form.get("adherence"), 0, 100)
        if not week or adherence is None:
            flash("Week and adherence between 0 and 100 are required.", "error")
            return redirect(url_for("dashboard", client_id=client_id))
        with get_db() as conn:
            conn.execute(
                "INSERT INTO progress (client_id, client_name, week, adherence) VALUES (?, ?, ?, ?)",
                (client_id, client["name"], week, adherence),
            )
            conn.commit()
        flash("Weekly progress saved.", "success")
        return redirect(url_for("dashboard", client_id=client_id))

    @app.route("/clients/<int:client_id>/metrics", methods=["POST"])
    @login_required
    def add_metrics(client_id):
        client = get_client_or_none(client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("dashboard"))
        metric_date = request.form.get("date", "").strip()
        weight = positive_float(request.form.get("weight"))
        waist = positive_float(request.form.get("waist"))
        bodyfat = positive_float(request.form.get("bodyfat"))
        if not metric_date:
            flash("Metric date is required.", "error")
            return redirect(url_for("dashboard", client_id=client_id))
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO metrics (client_id, client_name, date, weight, waist, bodyfat)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (client_id, client["name"], metric_date, weight, waist, bodyfat),
            )
            if weight:
                calories = int(weight * PROGRAMS.get(client["program"], {"factor": 25})["factor"])
                conn.execute("UPDATE clients SET weight=?, calories=? WHERE id=?", (weight, calories, client_id))
            conn.commit()
        flash("Body metrics saved.", "success")
        return redirect(url_for("dashboard", client_id=client_id))

    @app.route("/clients/<int:client_id>/workouts", methods=["POST"])
    @login_required
    def add_workout(client_id):
        client = get_client_or_none(client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("dashboard"))

        workout_date = request.form.get("date", "").strip()
        workout_type = request.form.get("workout_type", "").strip()
        duration = positive_int(request.form.get("duration_min"))
        notes = request.form.get("notes", "").strip()
        exercise_name = request.form.get("exercise_name", "").strip()
        sets = positive_int(request.form.get("sets"))
        reps = positive_int(request.form.get("reps"))
        exercise_weight = nonnegative_float(request.form.get("exercise_weight"))

        if not workout_date or not workout_type:
            flash("Workout date and type are required.", "error")
            return redirect(url_for("dashboard", client_id=client_id))

        with get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workouts (client_id, client_name, date, workout_type, duration_min, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (client_id, client["name"], workout_date, workout_type, duration, notes),
            )
            workout_id = cursor.lastrowid
            if exercise_name:
                conn.execute(
                    """
                    INSERT INTO exercises (workout_id, name, sets, reps, weight)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (workout_id, exercise_name, sets, reps, exercise_weight),
                )
            conn.commit()
        flash("Workout logged successfully.", "success")
        return redirect(url_for("dashboard", client_id=client_id))

    @app.route("/clients/<int:client_id>/generate-program", methods=["POST"])
    @login_required
    def generate_program(client_id):
        client = get_client_or_none(client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("dashboard"))
        experience = request.form.get("experience", "").strip().lower()
        if experience not in {"beginner", "intermediate", "advanced"}:
            flash("Choose beginner, intermediate, or advanced experience.", "error")
            return redirect(url_for("dashboard", client_id=client_id))

        program_name = client["program"] or ""
        focus = "Full Body"
        if "Fat Loss" in program_name:
            focus = "Conditioning"
        elif "Muscle Gain" in program_name:
            focus = "Hypertrophy"

        if experience == "beginner":
            sets_range, reps_range, days = (2, 3), (8, 12), 3
        elif experience == "intermediate":
            sets_range, reps_range, days = (3, 4), (8, 15), 4
        else:
            sets_range, reps_range, days = (4, 5), (6, 15), 5

        weekly_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][:days]
        rows = []
        for day_name in weekly_days:
            count = 3 if days < 4 else 4
            for exercise in random.sample(EXERCISE_POOLS[focus], k=count):
                rows.append(
                    (
                        client_id,
                        day_name,
                        exercise,
                        random.randint(*sets_range),
                        random.randint(*reps_range),
                        experience,
                        focus,
                    )
                )

        with get_db() as conn:
            conn.execute("DELETE FROM generated_programs WHERE client_id=?", (client_id,))
            conn.executemany(
                """
                INSERT INTO generated_programs
                (client_id, day, exercise, sets, reps, experience, focus)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        flash(f"Generated {experience} {focus} program.", "success")
        return redirect(url_for("dashboard", client_id=client_id))

    @app.route("/clients/<int:client_id>/membership")
    @login_required
    def check_membership(client_id):
        client = get_client_or_none(client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("dashboard"))
        end = client["membership_end"] or "N/A"
        flash(f"Membership: {client['membership_status'] or 'N/A'} | Renewal/End Date: {end}", "info")
        return redirect(url_for("dashboard", client_id=client_id))

    @app.route("/clients/export.csv")
    @login_required
    def export_csv():
        with get_db() as conn:
            clients = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Name",
                "Age",
                "Height",
                "Weight",
                "Program",
                "Calories",
                "Target Weight",
                "Target Adherence",
                "Membership Status",
                "Membership End",
            ]
        )
        for c in clients:
            writer.writerow(list(c))
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=aceest_clients.csv"},
        )

    @app.route("/clients/<int:client_id>/report.pdf")
    @login_required
    def export_pdf(client_id):
        client = get_client_or_none(client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("dashboard"))
        try:
            from fpdf import FPDF
        except ImportError:
            flash("PDF dependency is missing. Run: python -m pip install fpdf2", "error")
            return redirect(url_for("dashboard", client_id=client_id))

        reports_dir = BASE_DIR / "reports"
        reports_dir.mkdir(exist_ok=True)
        filename = secure_filename(f"{client['name']}_report.pdf") or f"client_{client_id}_report.pdf"
        path = reports_dir / filename

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(
            0,
            10,
            pdf_safe_text(f"ACEest Client Report - {client['name']}"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("Helvetica", size=12)
        fields = [
            ("Name", client["name"]),
            ("Age", client["age"]),
            ("Height", f"{client['height']} cm" if client["height"] else "N/A"),
            ("Weight", f"{client['weight']} kg" if client["weight"] else "N/A"),
            ("Program", client["program"] or "N/A"),
            ("Calories", f"{client['calories']} kcal/day" if client["calories"] else "N/A"),
            ("Target Weight", client["target_weight"] or "N/A"),
            ("Target Adherence", f"{client['target_adherence']}%" if client["target_adherence"] is not None else "N/A"),
            ("Membership", client["membership_status"] or "N/A"),
            ("Membership End", client["membership_end"] or "N/A"),
        ]
        for label, value in fields:
            pdf.cell(
                0,
                8,
                pdf_safe_text(f"{label}: {value}"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.output(str(path))
        return send_file(path, as_attachment=True, download_name=filename)

    return app


def init_db(database_path):
    database_path = str(database_path)
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                age INTEGER,
                height REAL,
                weight REAL,
                program TEXT,
                calories INTEGER,
                target_weight REAL,
                target_adherence INTEGER,
                membership_status TEXT,
                membership_end TEXT
            );

            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                client_name TEXT,
                week TEXT,
                adherence INTEGER
            );

            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                client_name TEXT,
                date TEXT,
                workout_type TEXT,
                duration_min INTEGER,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER,
                name TEXT,
                sets INTEGER,
                reps INTEGER,
                weight REAL
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                client_name TEXT,
                date TEXT,
                weight REAL,
                waist REAL,
                bodyfat REAL
            );

            CREATE TABLE IF NOT EXISTS generated_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                day TEXT,
                exercise TEXT,
                sets INTEGER,
                reps INTEGER,
                experience TEXT,
                focus TEXT
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", "admin", "Admin"),
        )
        conn.commit()


def positive_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def bounded_int(value, minimum, maximum):
    try:
        parsed = int(value)
        return parsed if minimum <= parsed <= maximum else None
    except (TypeError, ValueError):
        return None


def positive_float(value):
    try:
        parsed = float(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def nonnegative_float(value):
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def calculate_bmi(height_cm, weight_kg):
    if not height_cm or not weight_kg or height_cm <= 0 or weight_kg <= 0:
        return None
    bmi = round(weight_kg / ((height_cm / 100.0) ** 2), 1)
    if bmi < 18.5:
        category = "Underweight"
        risk = "Potential nutrient deficiency, low energy."
    elif bmi < 25:
        category = "Normal"
        risk = "Low risk if active and strong."
    elif bmi < 30:
        category = "Overweight"
        risk = "Moderate risk; focus on adherence and progressive activity."
    else:
        category = "Obese"
        risk = "Higher risk; prioritize fat loss, consistency, and supervision."
    return {"bmi": bmi, "category": category, "risk": risk}


def make_weight_chart(metrics):
    points = [m for m in reversed(metrics) if m["weight"]]
    if not points:
        return []
    weights = [float(m["weight"]) for m in points]
    low, high = min(weights), max(weights)
    spread = max(high - low, 1.0)
    return [
        {
            "date": m["date"],
            "weight": float(m["weight"]),
            "height": 25 + ((float(m["weight"]) - low) / spread) * 70,
        }
        for m in points
    ]


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)