# app.py
# -*- coding: utf-8 -*-

import sqlite3
import io
import base64
import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


import yfinance as yf
import matplotlib
matplotlib.use("Agg")  # gunakan backend non-GUI
import matplotlib.pyplot as plt

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from email.mime.text import MIMEText
import smtplib

from fundamental_analyzer import analyze_stock_for_web, normalize_ticker

# =====================================================
# KONFIGURASI FLASK
# =====================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = "GANTI_INI_DENGAN_RANDOM_STRING_YANG_PANJANG"
app.config["DATABASE"] = "stockapp.db"

# =====================================================
# KONFIGURASI EMAIL (DEV MODE)
# =====================================================
# Kalau mau kirim email beneran, set SMTP_ENABLED = True
SMTP_ENABLED = False

SMTP_HOST = "smtp.gmail.com"   # contoh untuk Gmail
SMTP_PORT = 587
SMTP_USER = "emailkamu@gmail.com"
SMTP_PASS = "app_password_emailmu"  # jangan password biasa


def send_email(to_email: str, subject: str, body: str):
    """
    Dev-mode: default hanya print isi email ke terminal.
    Kalau mau kirim email beneran, set SMTP_ENABLED = True dan isi SMTP_USER/PASS.
    """
    print("\n======= EMAIL (DEV MODE) =======")
    print("Kepada :", to_email)
    print("Subjek :", subject)
    print("Isi    :")
    print(body)
    print("================================\n")

    if not SMTP_ENABLED:
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print("Email terkirim ke", to_email)
    except Exception as e:
        print("Gagal kirim email:", e)


# =====================================================
# HELPER DATABASE
# =====================================================
def get_db_connection():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row  # supaya hasil bisa diakses seperti dict
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # --- Buat tabel jika belum ada ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_verified INTEGER NOT NULL DEFAULT 0,
            verify_token TEXT,
            reset_token TEXT,
            reset_expires TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # --- Pastikan akun admin default ada ---
    admin_username = "admin"
    admin_email = "admin@example.com"
    admin_password_hash = generate_password_hash("asdfghjkl")
    now = datetime.utcnow().isoformat()

    # 1) Coba UPDATE kalau sudah ada user 'admin'
    cur.execute("""
        UPDATE users
        SET email = ?,
            password_hash = ?,
            is_admin = 1,
            is_verified = 1,
            verify_token = NULL,
            reset_token = NULL,
            reset_expires = NULL
        WHERE username = ?
    """, (admin_email, admin_password_hash, admin_username))

    # 2) Kalau tidak ada baris yang kena UPDATE → buat akun baru
    if cur.rowcount == 0:
        cur.execute("""
            INSERT INTO users (
                username, email, password_hash,
                is_admin, is_verified,
                verify_token, reset_token, reset_expires,
                created_at
            ) VALUES (?, ?, ?, 1, 1, NULL, NULL, NULL, ?)
        """, (admin_username, admin_email, admin_password_hash, now))

    conn.commit()
    conn.close()



# =====================================================
# HELPER LOGIN / USER
# =====================================================
def get_current_user():
    if "user_id" not in session:
        return None
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()
    return user


def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or not user["is_admin"]:
            flash("Anda tidak punya akses admin.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


# =====================================================
# HELPER: CHART HARGA
# =====================================================
def generate_price_chart_base64(ticker: str, period: str = "6mo"):
    """
    Ambil data harga pakai yfinance, buat plot, dan return string base64.
    """
    try:
        df = yf.download(ticker, period=period)
        if df.empty:
            return None

        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(df.index, df["Close"])
        ax.set_title(f"Price History - {ticker}")
        ax.set_xlabel("Date")
        ax.set_ylabel("Close")
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode("utf-8")
        return img_base64
    except Exception as e:
        print("Error generate_price_chart_base64:", e)
        return None


# =====================================================
# ROUTES UTAMA
# =====================================================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ------------------------ REGISTER ------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()

        if not username or not password or not email:
            flash("Username, email, dan password wajib diisi.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Password dan konfirmasi tidak sama.", "danger")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        created_at = datetime.utcnow().isoformat()
        verify_token = str(uuid.uuid4())

        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO users (
                    username, email, password_hash,
                    is_admin, is_verified, verify_token, created_at
                )
                VALUES (?, ?, ?, 0, 0, ?, ?)
            """, (username, email, password_hash, verify_token, created_at))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Username atau email sudah dipakai.", "danger")
            conn.close()
            return render_template("register.html")

        conn.close()

        # Kirim email verifikasi (link dicetak di terminal / email)
        verify_link = url_for("verify_email", token=verify_token, _external=True)
        body = f"""
Terima kasih sudah register di Stock Analyzer.

Klik link berikut untuk verifikasi email kamu:
{verify_link}

Jika kamu tidak merasa register, abaikan email ini.
"""
        send_email(email, "Verifikasi Email - Stock Analyzer", body)

        flash("Registrasi berhasil. Cek email untuk verifikasi akun (link juga ada di terminal).", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ------------------------ LOGIN ------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            if not user["is_verified"]:
                flash("Email belum diverifikasi. Cek inbox / lihat link di terminal.", "warning")
                return render_template("login.html")

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Login berhasil.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Username atau password salah.", "danger")

    return render_template("login.html")


# ------------------------ LOGOUT ------------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Anda telah logout.", "info")
    return redirect(url_for("login"))


# ------------------------ VERIFIKASI EMAIL ------------------------
@app.route("/verify/<token>")
def verify_email(token):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE verify_token = ?",
        (token,)
    ).fetchone()

    if not user:
        conn.close()
        flash("Token verifikasi tidak valid.", "danger")
        return redirect(url_for("login"))

    conn.execute("""
        UPDATE users
        SET is_verified = 1, verify_token = NULL
        WHERE id = ?
    """, (user["id"],))
    conn.commit()
    conn.close()

    flash("Email berhasil diverifikasi. Silakan login.", "success")
    return redirect(url_for("login"))


# ------------------------ LUPA PASSWORD ------------------------
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            flash("Email wajib diisi.", "danger")
            return render_template("forgot_password.html")

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if not user:
            conn.close()
            flash("Email tidak terdaftar.", "danger")
            return render_template("forgot_password.html")

        token = str(uuid.uuid4())
        reset_link = url_for("reset_password", token=token, _external=True)
        expires = datetime.utcnow().isoformat()  # di sini belum dipakai logic kadaluarsa

        conn.execute("""
            UPDATE users
            SET reset_token = ?, reset_expires = ?
            WHERE id = ?
        """, (token, expires, user["id"]))
        conn.commit()
        conn.close()

        body = f"""
Kamu meminta reset password di Stock Analyzer.

Klik link berikut untuk mengganti password:
{reset_link}

Jika kamu tidak merasa meminta reset, abaikan email ini.
"""
        send_email(email, "Reset Password - Stock Analyzer", body)

        flash("Link reset password sudah dikirim ke email (dan dicetak di terminal).", "info")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


# ------------------------ RESET PASSWORD ------------------------
@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE reset_token = ?",
        (token,)
    ).fetchone()

    if not user:
        conn.close()
        flash("Token reset tidak valid.", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not password or password != confirm:
            flash("Password kosong atau tidak sama.", "danger")
            conn.close()
            return render_template("reset_password.html", token=token)

        password_hash = generate_password_hash(password)
        conn.execute("""
            UPDATE users
            SET password_hash = ?, reset_token = NULL, reset_expires = NULL
            WHERE id = ?
        """, (password_hash, user["id"]))
        conn.commit()
        conn.close()

        flash("Password berhasil direset. Silakan login.", "success")
        return redirect(url_for("login"))

    conn.close()
    return render_template("reset_password.html", token=token)


# =====================================================
# ADMIN PANEL
# =====================================================
@app.route("/admin")
@admin_required
def admin_index():
    return redirect(url_for("admin_users"))


@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db_connection()
    users = conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)


@app.route("/admin/watchlist")
@admin_required
def admin_watchlist():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT w.*, u.username
        FROM watchlist w
        JOIN users u ON w.user_id = u.id
        ORDER BY w.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("admin_watchlist.html", rows=rows)


# OPSIONAL: route sekali pakai untuk menjadikan akun saat ini sebagai admin
@app.route("/make-me-admin")
@login_required
def make_me_admin():
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET is_admin = 1 WHERE id = ?",
        (session["user_id"],)
    )
    conn.commit()
    conn.close()
    flash("Akunmu sekarang admin. (Route ini bisa kamu hapus setelah dipakai)", "success")
    return redirect(url_for("dashboard"))


# =====================================================
# DASHBOARD (ANALISA + WATCHLIST)
# =====================================================
@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    user = get_current_user()
    conn = get_db_connection()

    # Ambil watchlist user
    watchlist_rows = conn.execute(
        "SELECT * FROM watchlist WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()
    conn.close()

    analyze_result = None
    chart_img = None
    ticker_input = ""

    if request.method == "POST":
        ticker_input = request.form.get("ticker", "").strip()
        if ticker_input:
            try:
                analyze_result = analyze_stock_for_web(ticker_input)
                norm = normalize_ticker(ticker_input)
                chart_img = generate_price_chart_base64(norm, period="6mo")
            except Exception as e:
                print("Error dashboard analyze:", e)
                flash("Gagal menganalisa saham. Coba lagi.", "danger")

    # Hitung last price sederhana untuk tiap watchlist
    watchlist_with_price = []
    for row in watchlist_rows:
        ticker = row["ticker"]
        price = None
        try:
            data = yf.Ticker(normalize_ticker(ticker)).fast_info
            price = data.get("lastPrice")
        except Exception:
            pass
        watchlist_with_price.append({
            "id": row["id"],
            "ticker": ticker,
            "note": row["note"],
            "created_at": row["created_at"],
            "last_price": price,
        })

    return render_template(
        "dashboard.html",
        user=user,
        watchlist=watchlist_with_price,
        analyze_result=analyze_result,
        chart_img=chart_img,
        ticker_input=ticker_input
    )


# ------------------------ TAMBAH WATCHLIST ------------------------
@app.route("/watchlist/add", methods=["POST"])
@login_required
def add_watchlist():
    user = get_current_user()
    ticker = request.form.get("ticker_watchlist", "").strip()
    note = request.form.get("note", "").strip()

    if not ticker:
        flash("Ticker tidak boleh kosong.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    created_at = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO watchlist (user_id, ticker, note, created_at)
        VALUES (?, ?, ?, ?)
    """, (user["id"], ticker.upper(), note, created_at))
    conn.commit()
    conn.close()

    flash(f"{ticker.upper()} ditambahkan ke watchlist.", "success")
    return redirect(url_for("dashboard"))


# ------------------------ HAPUS WATCHLIST ------------------------
@app.route("/watchlist/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_watchlist(item_id):
    user = get_current_user()
    conn = get_db_connection()
    conn.execute("""
        DELETE FROM watchlist
        WHERE id = ? AND user_id = ?
    """, (item_id, user["id"]))
    conn.commit()
    conn.close()

    flash("Item watchlist dihapus.", "info")
    return redirect(url_for("dashboard"))


# =====================================================
# API ANALISA (JSON)
# =====================================================
@app.route("/api/analyze")
@login_required
def api_analyze():
    ticker = request.args.get("ticker", "").strip()
    if not ticker:
        return jsonify({"error": "ticker parameter is required"}), 400

    try:
        data = analyze_stock_for_web(ticker)
        return jsonify(data)
    except Exception as e:
        print("Error api_analyze:", e)
        return jsonify({"error": "failed to analyze"}), 500


# =====================================================
# MAIN
# =====================================================
if __name__ == "__main__":
    init_db()          # ← penting!
    app.run(debug=True)

