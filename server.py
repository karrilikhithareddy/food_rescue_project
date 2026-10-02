from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = "foodrescue_secret_key_change_me"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "foodrescue.db")

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fullname TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'donor'
    );

    CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER NOT NULL,
        food_name TEXT NOT NULL,
        food_type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        pickup_location TEXT NOT NULL,
        available_time TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL DEFAULT 'Available',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (donor_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donation_id INTEGER NOT NULL,
        volunteer_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'Requested',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (donation_id) REFERENCES donations(id),
        FOREIGN KEY (volunteer_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) c FROM donations").fetchone()["c"]
    available = conn.execute("SELECT COUNT(*) c FROM donations WHERE status='Available'").fetchone()["c"]
    completed = conn.execute("SELECT COUNT(*) c FROM donations WHERE status='Completed'").fetchone()["c"]
    conn.close()
    return render_template("home.html", total=total, available=available, completed=completed)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form["fullname"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return redirect(url_for("register"))

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users(fullname,email,password,role) VALUES(?,?,?,?)",
                (fullname, email, generate_password_hash(password), role)
            )
            conn.commit()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")
    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    user_id = session["user_id"]
    role = session["role"]

    if role == "donor":
        donations = conn.execute(
            "SELECT * FROM donations WHERE donor_id=? ORDER BY id DESC", (user_id,)
        ).fetchall()
        conn.close()
        return render_template("donor_dashboard.html", donations=donations)

    if role == "volunteer":
        donations = conn.execute("""
            SELECT d.*, u.fullname AS donor_name
            FROM donations d JOIN users u ON d.donor_id=u.id
            WHERE d.status='Available'
            ORDER BY d.id DESC
        """).fetchall()
        requests = conn.execute("""
            SELECT r.*, d.food_name, d.quantity, d.pickup_location, u.fullname AS donor_name
            FROM requests r
            JOIN donations d ON r.donation_id=d.id
            JOIN users u ON d.donor_id=u.id
            WHERE r.volunteer_id=?
            ORDER BY r.id DESC
        """, (user_id,)).fetchall()
        conn.close()
        return render_template("volunteer_dashboard.html", donations=donations, requests=requests)

    donations = conn.execute("""
        SELECT d.*, u.fullname AS donor_name
        FROM donations d JOIN users u ON d.donor_id=u.id
        ORDER BY d.id DESC
    """).fetchall()
    requests = conn.execute("""
        SELECT r.*, d.food_name, d.quantity, d.pickup_location,
               u.fullname AS volunteer_name, du.fullname AS donor_name
        FROM requests r
        JOIN donations d ON r.donation_id=d.id
        JOIN users u ON r.volunteer_id=u.id
        JOIN users du ON d.donor_id=du.id
        ORDER BY r.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin_dashboard.html", donations=donations, requests=requests)

@app.route("/add-donation", methods=["GET", "POST"])
@login_required
def add_donation():
    if session["role"] != "donor":
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        conn = get_db()
        conn.execute("""
            INSERT INTO donations
            (donor_id,food_name,food_type,quantity,pickup_location,available_time,description)
            VALUES(?,?,?,?,?,?,?)
        """, (
            session["user_id"], request.form["food_name"], request.form["food_type"],
            request.form["quantity"], request.form["pickup_location"],
            request.form["available_time"], request.form["description"]
        ))
        conn.commit()
        conn.close()
        flash("Food donation posted successfully!", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_donation.html")


@app.route("/edit-donation/<int:donation_id>", methods=["GET", "POST"])
@login_required
def edit_donation(donation_id):
    if session["role"] != "donor":
        return redirect(url_for("dashboard"))

    conn = get_db()
    donation = conn.execute(
        "SELECT * FROM donations WHERE id=? AND donor_id=?",
        (donation_id, session["user_id"])
    ).fetchone()

    if not donation:
        conn.close()
        flash("Donation not found.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        conn.execute("""
            UPDATE donations
            SET food_name=?, food_type=?, quantity=?, pickup_location=?,
                available_time=?, description=?
            WHERE id=? AND donor_id=?
        """, (
            request.form["food_name"],
            request.form["food_type"],
            request.form["quantity"],
            request.form["pickup_location"],
            request.form["available_time"],
            request.form["description"],
            donation_id,
            session["user_id"]
        ))
        conn.commit()
        conn.close()
        flash("Donation updated successfully!", "success")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template("edit_donation.html", donation=donation)

@app.route("/request/<int:donation_id>", methods=["POST"])
@login_required
def request_donation(donation_id):
    if session["role"] != "volunteer":
        return redirect(url_for("dashboard"))

    conn = get_db()
    donation = conn.execute("SELECT * FROM donations WHERE id=?", (donation_id,)).fetchone()
    if donation and donation["status"] == "Available":
        conn.execute(
            "INSERT INTO requests(donation_id,volunteer_id) VALUES(?,?)",
            (donation_id, session["user_id"])
        )
        conn.execute("UPDATE donations SET status='Requested' WHERE id=?", (donation_id,))
        conn.commit()
        flash("Donation request sent!", "success")
    else:
        flash("This donation is no longer available.", "error")
    conn.close()
    return redirect(url_for("dashboard"))

@app.route("/update-request/<int:request_id>/<status>", methods=["POST"])
@login_required
def update_request(request_id, status):
    allowed = {"Accepted", "Picked Up", "Completed", "Rejected"}
    if status not in allowed:
        return redirect(url_for("dashboard"))

    conn = get_db()
    req = conn.execute("""
        SELECT r.*, d.donor_id FROM requests r
        JOIN donations d ON r.donation_id=d.id
        WHERE r.id=?
    """, (request_id,)).fetchone()

    if not req:
        conn.close()
        return redirect(url_for("dashboard"))

    if session["role"] == "admin" or session["user_id"] in (req["volunteer_id"], req["donor_id"]):
        conn.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
        if status == "Completed":
            conn.execute("UPDATE donations SET status='Completed' WHERE id=?", (req["donation_id"],))
        elif status == "Accepted":
            conn.execute("UPDATE donations SET status='Accepted' WHERE id=?", (req["donation_id"],))
        elif status == "Rejected":
            conn.execute("UPDATE donations SET status='Available' WHERE id=?", (req["donation_id"],))
        conn.commit()

    conn.close()
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
