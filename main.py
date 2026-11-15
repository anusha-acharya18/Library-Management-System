from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

SECRET_KEY_FILE = ".flask_secret_key"

if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, "r") as file:
        app.secret_key = file.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w") as file:
        file.write(app.secret_key)


# Database connection
def get_db():
    conn = sqlite3.connect("library.db")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Create database
def create_database():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS borrow_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            borrowed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Borrowed',
            returned_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    cursor.execute("PRAGMA table_info(borrow_records)")
    columns = [column[1] for column in cursor.fetchall()]

    if "returned_at" not in columns:
        cursor.execute("""
            ALTER TABLE borrow_records
            ADD COLUMN returned_at TIMESTAMP
        """)

    cursor.execute(
        "SELECT id FROM students WHERE email = ?",
        ("admin@library.com",)
    )

    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO students (fullname, email, password, role)
            VALUES (?, ?, ?, ?)
        """, (
            "Library Admin",
            "admin@library.com",
            generate_password_hash("Admin@123"),
            "admin"
        ))

    conn.commit()
    conn.close()


# Home
@app.route("/")
def home():
    return render_template("index.html")


# Login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, fullname, email, password, role
            FROM students
            WHERE email = ? AND role = ?
        """, (email, role))

        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):
            session["user_id"] = user[0]
            session["fullname"] = user[1]
            session["role"] = user[4]

            if role == "admin":
                return redirect(url_for("admin"))

            return redirect(url_for("student"))

        return "Invalid email or password!"

    return render_template("login.html")


# Registration
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form["fullname"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        role = request.form["role"]

        if password != confirm_password:
            return "Passwords do not match!"

        if role != "student":
            return "Invalid role!"

        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO students (fullname, email, password, role)
                VALUES (?, ?, ?, ?)
            """, (
                fullname,
                email,
                generate_password_hash(password),
                role
            ))

            conn.commit()

            session["user_id"] = cursor.lastrowid
            session["fullname"] = fullname
            session["role"] = role

            conn.close()
            return redirect(url_for("student"))

        except sqlite3.IntegrityError:
            conn.close()
            return "This email is already registered!"

    return render_template("register.html")


# Student dashboard
@app.route("/student")
def student():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM books")
    available_books = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM borrow_records
        WHERE student_id = ? AND status = 'Borrowed'
    """, (session["user_id"],))
    borrowed_books = cursor.fetchone()[0]

    cursor.execute("""
        SELECT title, author, category, quantity
        FROM books
        ORDER BY id DESC
        LIMIT 5
    """)
    recent_books = cursor.fetchall()

    cursor.execute("""
        SELECT books.title, books.author,
               borrow_records.borrowed_at,
               borrow_records.status
        FROM borrow_records
        JOIN books ON borrow_records.book_id = books.id
        WHERE borrow_records.student_id = ?
        ORDER BY borrow_records.id DESC
        LIMIT 5
    """, (session["user_id"],))
    my_borrowed_books = cursor.fetchall()

    conn.close()

    return render_template(
        "student_dashboard.html",
        fullname=session.get("fullname"),
        total_books=total_books,
        available_books=available_books,
        borrowed_books=borrowed_books,
        recent_books=recent_books,
        my_borrowed_books=my_borrowed_books
    )


# Admin dashboard
@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM books")
    available_books = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM students
        WHERE role = 'student'
    """)
    registered_students = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM borrow_records
        WHERE status = 'Borrowed'
    """)
    borrowed_books = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_books=total_books,
        available_books=available_books,
        registered_students=registered_students,
        borrowed_books=borrowed_books
    )
# Add books
@app.route("/add_book", methods=["GET", "POST"])
def add_book():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form["title"]
        author = request.form["author"]
        isbn = request.form["isbn"]
        category = request.form["category"]

        try:
            quantity = int(request.form["quantity"])
            if quantity < 1:
                return "Quantity must be at least 1!"
        except ValueError:
            return "Please enter a valid quantity!"

        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO books
                (title, author, isbn, category, quantity)
                VALUES (?, ?, ?, ?, ?)
            """, (title, author, isbn, category, quantity))

            conn.commit()
            conn.close()

            return redirect(url_for("view_books"))

        except sqlite3.IntegrityError:
            conn.close()
            return "This ISBN already exists!"

    return render_template("add_book.html")


# View books
@app.route("/view_books")
def view_books():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, author, isbn, category, quantity
        FROM books
        ORDER BY id DESC
    """)

    books = cursor.fetchall()
    conn.close()

    return render_template("view_books.html", books=books)


# Book details
@app.route("/book_details/<int:book_id>")
def book_details(book_id):
    if session.get("role") != "student":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, author, isbn, category, quantity
        FROM books
        WHERE id = ?
    """, (book_id,))

    book = cursor.fetchone()
    conn.close()

    if book is None:
        return "Book not found!", 404

    return render_template("book_details.html", book=book)


# Manage students
@app.route("/manage_students")
def manage_students():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, fullname, email
        FROM students
        WHERE role = 'student'
        ORDER BY id DESC
    """)

    students = cursor.fetchall()
    conn.close()

    return render_template("manage_students.html", students=students)


# Admin borrowed books
@app.route("/admin_borrowed_books")
def admin_borrowed_books():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT students.fullname,
               students.email,
               books.title,
               books.author,
               borrow_records.borrowed_at,
               borrow_records.status
        FROM borrow_records
        JOIN students ON borrow_records.student_id = students.id
        JOIN books ON borrow_records.book_id = books.id
        WHERE borrow_records.status = 'Borrowed'
        ORDER BY borrow_records.id DESC
    """)

    borrowed_books = cursor.fetchall()
    conn.close()

    return render_template(
        "admin_borrowed_books.html",
        borrowed_books=borrowed_books
    )


# Admin returned books
@app.route("/admin_returned_books")
def admin_returned_books():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT students.fullname,
               students.email,
               books.title,
               books.author,
               borrow_records.borrowed_at,
               borrow_records.status,
               datetime(
                   borrow_records.returned_at,
                   '+5 hours',
                   '+30 minutes'
               )
        FROM borrow_records
        JOIN students ON borrow_records.student_id = students.id
        JOIN books ON borrow_records.book_id = books.id
        WHERE borrow_records.status = 'Returned'
        ORDER BY borrow_records.id DESC
    """)

    returned_books = cursor.fetchall()
    conn.close()

    return render_template(
        "admin_returned_books.html",
        returned_books=returned_books
    )


# Borrow books page
@app.route("/borrow_books")
def borrow_books():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    search_query = request.args.get("q", "").strip()

    if search_query:
        cursor.execute("""
            SELECT id, title, author, category, quantity
            FROM books
            WHERE quantity > 0
            AND (title LIKE ? OR author LIKE ?)
            ORDER BY id DESC
        """, (f"%{search_query}%", f"%{search_query}%"))
    else:
        cursor.execute("""
            SELECT id, title, author, category, quantity
            FROM books
            WHERE quantity > 0
            ORDER BY id DESC
        """)

    books = cursor.fetchall()
    conn.close()

    return render_template(
        "borrow_books.html",
        books=books,
        search_query=search_query
    )
# Borrow book
@app.route("/borrow_book", methods=["POST"])
def borrow_book():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    try:
        book_id = int(request.form["book_id"])
    except (ValueError, KeyError):
        return "Invalid book selection!"

    student_id = session["user_id"]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE books
        SET quantity = quantity - 1
        WHERE id = ? AND quantity > 0
    """, (book_id,))

    if cursor.rowcount == 0:
        conn.rollback()
        conn.close()
        return "This book is currently unavailable!"

    cursor.execute("""
        INSERT INTO borrow_records (student_id, book_id)
        VALUES (?, ?)
    """, (student_id, book_id))

    conn.commit()
    conn.close()

    return redirect(url_for("my_borrowed_books"))


# My borrowed books
@app.route("/my_borrowed_books")
def my_borrowed_books():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT borrow_records.id,
               books.title,
               books.author,
               borrow_records.borrowed_at,
               borrow_records.status
        FROM borrow_records
        JOIN books ON borrow_records.book_id = books.id
        WHERE borrow_records.student_id = ?
        ORDER BY borrow_records.id DESC
    """, (session["user_id"],))

    borrowed_books = cursor.fetchall()
    conn.close()

    return render_template(
        "my_borrowed_books.html",
        borrowed_books=borrowed_books
    )


# Return book
@app.route("/return_book", methods=["POST"])
def return_book():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    try:
        borrow_id = int(request.form["borrow_id"])
    except (ValueError, KeyError):
        return "Invalid borrowed book!"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT book_id
        FROM borrow_records
        WHERE id = ?
        AND student_id = ?
        AND status = 'Borrowed'
    """, (borrow_id, session["user_id"]))

    record = cursor.fetchone()

    if record is None:
        conn.close()
        return "This book cannot be returned!"

    book_id = record[0]

    cursor.execute("""
        UPDATE borrow_records
        SET status = 'Returned',
            returned_at = CURRENT_TIMESTAMP
        WHERE id = ?
        AND student_id = ?
        AND status = 'Borrowed'
    """, (borrow_id, session["user_id"]))

    if cursor.rowcount == 1:
        cursor.execute("""
            UPDATE books
            SET quantity = quantity + 1
            WHERE id = ?
        """, (book_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("my_borrowed_books"))


# Logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    create_database()
    app.run(debug=True)