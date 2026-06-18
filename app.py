from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'dev-secret')

DATABASE = "shop.db"

# Create database and products table
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        unit TEXT NOT NULL
    )
    """)
     
    # Ensure `unit` column exists for older databases
    cursor.execute("PRAGMA table_info(products)")
    cols = [row[1] for row in cursor.fetchall()]
    if 'unit' not in cols:
        cursor.execute("ALTER TABLE products ADD COLUMN unit TEXT DEFAULT 'Piece'")
    if 'reorder_level' not in cols:
        cursor.execute("ALTER TABLE products ADD COLUMN reorder_level INTEGER DEFAULT 5")

    # Create reports table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT NOT NULL,
        total_value REAL NOT NULL,
        total_items INTEGER NOT NULL,
        snapshot TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # Create sales table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        total_price REAL NOT NULL,
        sold_at TEXT NOT NULL
    )
    """)

    # Create alerts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved INTEGER NOT NULL DEFAULT 0
    )
    """)

    conn.commit()
    # create default admin if no users exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    if count == 0:
        pwd = generate_password_hash('admin')
        cursor.execute("INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)", ('admin', pwd, 1, datetime.utcnow().isoformat()))

    conn.commit()
    conn.close()
    # initialization complete
# Home page
@app.route('/')
def home():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()

    conn.close()

    return render_template("shop.html", products=products)


def requires_admin(f):
    from functools import wraps

    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        if not session.get('is_admin'):
            return redirect(url_for('home'))
        return f(*args, **kwargs)

    return wrapped


def requires_login(f):
    from functools import wraps

    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)

    return wrapped


@app.route('/report')
@requires_admin
def report():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    conn.close()

    total_value = sum((p[2] or 0) * (p[3] or 0) for p in products)
    total_items = sum((p[3] or 0) for p in products)

    report = {
        'date': datetime.utcnow().date().isoformat(),
        'total_value': total_value,
        'total_items': total_items,
        'products': [
            {'id': p[0], 'name': p[1], 'price': p[2], 'quantity': p[3], 'unit': p[4] if len(p) > 4 else 'Piece'}
            for p in products
        ]
    }

    return render_template('report.html', report=report)


@app.route('/product/<int:product_id>')
def view_product(product_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, quantity, unit FROM products WHERE id = ?", (product_id,))
    p = cursor.fetchone()
    conn.close()

    if not p:
        return redirect('/')

    product = {'id': p[0], 'name': p[1], 'price': p[2], 'quantity': p[3], 'unit': p[4]}
    return render_template('product_detail.html', product=product)


def requires_admin(f):
    from functools import wraps

    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        if not session.get('is_admin'):
            return redirect(url_for('home'))
        return f(*args, **kwargs)

    return wrapped


@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
@requires_admin
def edit_product(product_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        try:
            price = float(request.form.get('price', 0))
        except (ValueError, TypeError):
            price = 0.0
        try:
            quantity = int(request.form.get('quantity', 0))
        except (ValueError, TypeError):
            quantity = 0
        unit = request.form.get('unit', 'Piece')

        cursor.execute(
            "UPDATE products SET name = ?, price = ?, quantity = ?, unit = ? WHERE id = ?",
            (name, price, quantity, unit, product_id)
        )
        conn.commit()
        conn.close()
        return redirect('/')

    cursor.execute("SELECT id, name, price, quantity, unit FROM products WHERE id = ?", (product_id,))
    p = cursor.fetchone()
    conn.close()

    if not p:
        return redirect('/')

    product = {'id': p[0], 'name': p[1], 'price': p[2], 'quantity': p[3], 'unit': p[4]}
    return render_template('edit_product.html', product=product)


@app.route('/delete/<int:product_id>', methods=['POST'])
@requires_admin
def delete_product(product_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return redirect('/')


@app.route('/search')
def search_products():
    q = request.args.get('q', '').strip()
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    if q:
        like = f"%{q}%"
        cursor.execute("SELECT id, name, price, quantity, unit FROM products WHERE name LIKE ? ORDER BY id DESC", (like,))
    else:
        cursor.execute("SELECT id, name, price, quantity, unit FROM products ORDER BY id DESC")
    products = cursor.fetchall()
    conn.close()
    return render_template('shop.html', products=products, query=q)


@app.route('/sell/<int:product_id>', methods=['POST'])
@requires_login
def sell_product(product_id):
    try:
        qty = int(request.form.get('sell_qty', 1))
    except (ValueError, TypeError):
        qty = 1

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, quantity, reorder_level FROM products WHERE id = ?", (product_id,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        return redirect('/')

    current_qty = p[3] or 0
    new_qty = max(0, current_qty - qty)
    total_price = (p[2] or 0) * qty

    cursor.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product_id))
    sold_at = datetime.utcnow().isoformat()
    cursor.execute("INSERT INTO sales (product_id, quantity, total_price, sold_at) VALUES (?, ?, ?, ?)", (product_id, qty, total_price, sold_at))

    # Create alert if below reorder level
    reorder_level = p[4] if len(p) > 4 and p[4] is not None else 5
    if new_qty <= reorder_level:
        message = f"Low stock for {p[1]} (qty: {new_qty}, reorder level: {reorder_level})"
        cursor.execute("INSERT INTO alerts (product_id, message, created_at) VALUES (?, ?, ?)", (product_id, message, sold_at))

    conn.commit()
    conn.close()
    return redirect('/')


@app.route('/alerts')
def alerts_list():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT a.id, a.product_id, a.message, a.created_at, a.resolved, p.name FROM alerts a LEFT JOIN products p ON p.id = a.product_id ORDER BY a.id DESC")
    rows = cursor.fetchall()
    conn.close()

    alerts = [
        {'id': r[0], 'product_id': r[1], 'message': r[2], 'created_at': r[3], 'resolved': bool(r[4]), 'product_name': r[5]} for r in rows
    ]
    return render_template('alerts.html', alerts=alerts)


@app.route('/alerts/resolve/<int:alert_id>', methods=['POST'])
@requires_admin
def resolve_alert(alert_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    return redirect('/alerts')


@app.route('/sales')
def sales_list():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT s.id, s.product_id, p.name, s.quantity, s.total_price, s.sold_at FROM sales s LEFT JOIN products p ON p.id = s.product_id ORDER BY s.sold_at DESC")
    rows = cursor.fetchall()
    cursor.execute("SELECT SUM(total_price), SUM(quantity) FROM sales")
    totals = cursor.fetchone()
    conn.close()

    sales = [{'id': r[0], 'product_id': r[1], 'product_name': r[2], 'quantity': r[3], 'total_price': r[4], 'sold_at': r[5]} for r in rows]
    overall_total = totals[0] or 0
    overall_qty = totals[1] or 0
    return render_template('sales_list.html', sales=sales, overall_total=overall_total, overall_qty=overall_qty)


@app.route('/sales/product/<int:product_id>')
def sales_by_product(product_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM products WHERE id = ?", (product_id,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        return redirect('/sales')
    cursor.execute("SELECT id, quantity, total_price, sold_at FROM sales WHERE product_id = ? ORDER BY sold_at DESC", (product_id,))
    rows = cursor.fetchall()
    cursor.execute("SELECT SUM(total_price), SUM(quantity) FROM sales WHERE product_id = ?", (product_id,))
    totals = cursor.fetchone()
    conn.close()

    sales = [{'id': r[0], 'quantity': r[1], 'total_price': r[2], 'sold_at': r[3]} for r in rows]
    total_value = totals[0] or 0
    total_qty = totals[1] or 0
    product = {'id': p[0], 'name': p[1]}
    return render_template('product_sales.html', sales=sales, product=product, total_value=total_value, total_qty=total_qty)


@app.route('/receipt/<int:sale_id>')
def receipt(sale_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT s.id, s.product_id, p.name, s.quantity, s.total_price, s.sold_at, p.unit FROM sales s LEFT JOIN products p ON p.id = s.product_id WHERE s.id = ?", (sale_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return redirect('/sales')

    sale = {
        'id': row[0],
        'product_id': row[1],
        'product_name': row[2],
        'quantity': row[3],
        'total_price': row[4],
        'sold_at': row[5],
        'unit': row[6] or 'Piece'
    }
    # compute unit price
    try:
        sale['unit_price'] = sale['total_price'] / sale['quantity'] if sale['quantity'] else 0
    except Exception:
        sale['unit_price'] = 0

    return render_template('receipt.html', sale=sale)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, is_admin FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            flash('Invalid username or password')
            return render_template('login.html')
        user_id, uname, pw_hash, is_admin = row
        if check_password_hash(pw_hash, password):
            session['user_id'] = user_id
            session['username'] = uname
            session['is_admin'] = bool(is_admin)
            next_url = request.args.get('next') or url_for('home')
            return redirect(next_url)
        flash('Invalid username or password')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/users')
@requires_admin
def users_list():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    users = [{'id': r[0], 'username': r[1], 'is_admin': bool(r[2]), 'created_at': r[3]} for r in rows]
    return render_template('users_list.html', users=users)


@app.route('/users/add', methods=['GET', 'POST'])
@requires_admin
def add_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        if not username or not password:
            flash('Username and password required')
            return render_template('edit_user.html')
        pw_hash = generate_password_hash(password)
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)", (username, pw_hash, is_admin, datetime.utcnow().isoformat()))
            conn.commit()
        except Exception as e:
            flash('Could not create user')
        conn.close()
        return redirect(url_for('users_list'))
    return render_template('edit_user.html')


@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@requires_admin
def edit_user(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        if password:
            pw_hash = generate_password_hash(password)
            cursor.execute("UPDATE users SET username = ?, password_hash = ?, is_admin = ? WHERE id = ?", (username, pw_hash, is_admin, user_id))
        else:
            cursor.execute("UPDATE users SET username = ?, is_admin = ? WHERE id = ?", (username, is_admin, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('users_list'))

    cursor.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return redirect(url_for('users_list'))
    user = {'id': row[0], 'username': row[1], 'is_admin': bool(row[2])}
    return render_template('edit_user.html', user=user)


@app.route('/users/delete/<int:user_id>', methods=['POST'])
@requires_admin
def delete_user(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('users_list'))


@app.route('/report/save', methods=['POST'])
@requires_admin
def save_report():
    # Recompute current report and save to DB
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()

    total_value = sum((p[2] or 0) * (p[3] or 0) for p in products)
    total_items = sum((p[3] or 0) for p in products)

    snapshot = json.dumps([
        {'id': p[0], 'name': p[1], 'price': p[2], 'quantity': p[3], 'unit': p[4] if len(p) > 4 else 'Piece'}
        for p in products
    ])

    report_date = datetime.utcnow().date().isoformat()
    created_at = datetime.utcnow().isoformat()

    cursor.execute(
        "INSERT INTO reports (report_date, total_value, total_items, snapshot, created_at) VALUES (?, ?, ?, ?, ?)",
        (report_date, total_value, total_items, snapshot, created_at)
    )
    conn.commit()
    conn.close()

    return redirect('/reports')


@app.route('/reports')
def reports_list():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, report_date, total_value, total_items, created_at FROM reports ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    reports = [
        {'id': r[0], 'report_date': r[1], 'total_value': r[2], 'total_items': r[3], 'created_at': r[4]}
        for r in rows
    ]

    return render_template('reports_list.html', reports=reports)


@app.route('/reports/<int:report_id>')
def view_report(report_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, report_date, total_value, total_items, snapshot, created_at FROM reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return redirect('/reports')

    report = {
        'id': row[0],
        'report_date': row[1],
        'total_value': row[2],
        'total_items': row[3],
        'snapshot': json.loads(row[4]),
        'created_at': row[5]
    }

    return render_template('report.html', report=report)

# Add product
@app.route('/add', methods=['POST'])
def add_product():
    name = request.form.get('name', '').strip()
    try:
        price = float(request.form.get('price', 0))
    except (ValueError, TypeError):
        price = 0.0
    try:
        quantity = int(request.form.get('quantity', 0))
    except (ValueError, TypeError):
        quantity = 0
    unit = request.form.get('unit', 'Piece')

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO products (name, price, quantity, unit) VALUES (?, ?, ?, ?)",
        (name, price, quantity, unit)
    )

    conn.commit()
    conn.close()

    return redirect('/')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)