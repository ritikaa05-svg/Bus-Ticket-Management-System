import random
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from flask import send_file, render_template_string, make_response
import sqlite3
import uuid
import base64
import os
from io import BytesIO
from flask_bcrypt import Bcrypt
from datetime import date, datetime

app = Flask(__name__)
app.secret_key = 'supersecretkey'
bcrypt = Bcrypt(app)

# ------------------------ DB Connection Helper ------------------------

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# ------------------------ Auth Routes ------------------------

@app.route('/')
def home():
    conn = get_db()

    # Get 5 most popular or latest routes
    popular_routes = conn.execute("""
        SELECT * FROM routes
        ORDER BY date DESC
        LIMIT 5
    """).fetchall()

    # Get all unique origin/destination locations from `routes`
    origins = conn.execute("SELECT DISTINCT origin FROM routes").fetchall()
    destinations = conn.execute("SELECT DISTINCT destination FROM routes").fetchall()
    conn.close()

    # Flatten and merge the list into a unique set of locations
    origin_list = [row['origin'] for row in origins if row['origin']]
    destination_list = [row['destination'] for row in destinations if row['destination']]
    locations = sorted(set(origin_list + destination_list))

    return render_template(
        'home.html',
        popular_routes=popular_routes,
        locations=locations,
        current_date=date.today().isoformat()
    )

@app.route('/search')
def search():
    origin = request.args.get('origin')
    destination = request.args.get('destination')
    travel_date = request.args.get('date')

    conn = get_db()
    results = conn.execute("""
        SELECT * FROM routes
        WHERE origin = ? AND destination = ? AND date = ?
    """, (origin, destination, travel_date)).fetchall()
    conn.close()

    return render_template('search_results.html', routes=results, origin=origin, destination=destination, travel_date=travel_date)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['username']
            session['role'] = user['role']
            flash("Login successful.", "success")
            # Redirect to the correct dashboard based on role
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "danger")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        role = request.form['role']

        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
                         (name, email, password, role))
            conn.commit()
            flash("Registered successfully. Please log in.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Email already exists.", "danger")
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('home'))

# ------------------------ Helper Functions ------------------------

def is_admin():
    return 'user_id' in session and session.get('role') == 'admin'

def create_seats_for_route(route_id, total_seats=30, conn=None):
    if conn is None:
        conn = get_db()
        close_connection_locally = True
    else:
        close_connection_locally = False

    cur = conn.cursor()

    # Create standard seats (80%)
    standard_seats = int(total_seats * 0.8)
    for i in range(1, standard_seats + 1):
        seat_number = f"S{i:02d}"
        cur.execute("""
            INSERT INTO seats (seat_number, is_booked, route_id, seat_type)
            VALUES (?, 0, ?, 'standard')
        """, (seat_number, route_id))

    # Create premium seats (20%)
    premium_seats = total_seats - standard_seats
    for i in range(1, premium_seats + 1):
        seat_number = f"P{i:02d}"
        cur.execute("""
            INSERT INTO seats (seat_number, is_booked, route_id, seat_type)
            VALUES (?, 0, ?, 'premium')
        """, (seat_number, route_id))

    if close_connection_locally:
        conn.commit()
        conn.close()

# ------------------------ Seeding Routes (for development) ------------------------

@app.route('/seed')
def seed():
    conn = get_db()
    conn.execute("""
        INSERT INTO routes (origin, destination, departure_time, date, price, bus_number, driver_name, driver_contact)
        VALUES ('City A', 'City B', '10:00 AM', '2025-05-10', 299.99, 'AB-123', 'John Doe', '1234567890')
    """)
    conn.commit()
    conn.close()
    return "Seeded!"

@app.route('/api/search')
def api_search():
    origin = request.args.get('origin')
    destination = request.args.get('destination')
    search_date = request.args.get('date')

    conn = get_db()
    query = """
        SELECT * FROM routes
        WHERE origin = ? AND destination = ? AND date = ?
        ORDER BY departure_time
    """
    routes = conn.execute(query, (origin, destination, search_date)).fetchall()
    conn.close()

    return jsonify([dict(route) for route in routes])

@app.route('/search_routes')
def search_routes():
    origin = request.args.get('origin')
    destination = request.args.get('destination')
    search_date = request.args.get('date')

    if not origin or not destination or not search_date:
        return jsonify([])

    conn = get_db()
    query = """
        SELECT * FROM routes
        WHERE origin = ? AND destination = ? AND date = ?
        ORDER BY departure_time
    """
    routes = conn.execute(query, (origin, destination, search_date)).fetchall()
    conn.close()

    result = []
    for r in routes:
        result.append({
            "id": r['id'],
            "origin": r['origin'],
            "destination": r['destination'],
            "date": r['date'],
            "departure_time": r['departure_time'],
            "price": float(r['price'])
        })

    return jsonify(result)

# ------------------------ User Routes: View & Book Routes ------------------------

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for('login'))

    conn = get_db()
    user_id = session['user_id']
    pending_cancellations_count = 0
    stats = {}

    if session.get('role') == 'admin':
        # Admin stats
        pending_cancellations_count = conn.execute(
            "SELECT COUNT(*) FROM cancellation_requests WHERE status = 'pending'"
        ).fetchone()[0]
        
        stats['total_bookings'] = conn.execute(
            "SELECT COUNT(*) FROM bookings"
        ).fetchone()[0]
        
        stats['upcoming_trips'] = conn.execute(
            """SELECT COUNT(*) FROM bookings b
               JOIN routes r ON b.route_id = r.id
               WHERE r.date >= DATE('now')"""
        ).fetchone()[0]
    else:
        # Regular user stats
        stats['total_bookings'] = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE user_id = ?",
            (user_id,)
        ).fetchone()[0]
        
        stats['upcoming_trips'] = conn.execute(
            """SELECT COUNT(*) FROM bookings b
               JOIN routes r ON b.route_id = r.id
               WHERE b.user_id = ? AND r.date >= DATE('now')""",
            (user_id,)
        ).fetchone()[0]
    
    conn.close()
    
    return render_template('dashboard.html',
                         name=session['user_name'],
                         role=session['role'],
                         pending_cancellations_count=pending_cancellations_count,
                         stats=stats)

# ------------------------ Admin Routes: Manage Routes ------------------------

@app.route('/admin/dashboard')
def admin_dashboard():
    # Placeholder for the admin dashboard. Could be a different template or logic
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/admin/routes')
def admin_routes():
    if not is_admin():
        return redirect(url_for('login'))

    conn = get_db()
    
    # Base query
    query = "SELECT * FROM routes"
    conditions = []
    params = []
    
    # Origin filter
    if request.args.get('origin'):
        conditions.append("origin = ?")
        params.append(request.args.get('origin'))
    
    # Destination filter
    if request.args.get('destination'):
        conditions.append("destination = ?")
        params.append(request.args.get('destination'))
    
    # Date range filter
    if request.args.get('date_from'):
        conditions.append("date >= ?")
        params.append(request.args.get('date_from'))
    if request.args.get('date_to'):
        conditions.append("date <= ?")
        params.append(request.args.get('date_to'))
    
    # Combine conditions
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY date, departure_time"
    
    routes = conn.execute(query, params).fetchall()
    locations = conn.execute("SELECT DISTINCT origin FROM routes UNION SELECT DISTINCT destination FROM routes").fetchall()
    conn.close()
    
    return render_template('admin_routes.html', routes=routes, locations=[loc[0] for loc in locations])


@app.route('/admin/routes/add', methods=['GET', 'POST'])
def add_route():
    if not is_admin():
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        # Extract all form values
        origin = request.form['origin']
        destination = request.form['destination']
        departure_time = request.form['departure_time']
        route_date = request.form['date']
        price = float(request.form['price'])
        bus_number = request.form['bus_number']
        driver_name = request.form['driver_name']
        driver_contact = request.form['driver_contact']
        total_seats = int(request.form['total_seats'])

        try:
            cur.execute("""
                INSERT INTO routes
                (origin, destination, departure_time, date, price, bus_number,
                 driver_name, driver_contact, total_seats)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (origin, destination, departure_time, route_date, price,
                  bus_number, driver_name, driver_contact, total_seats))

            route_id = cur.lastrowid
            create_seats_for_route(route_id, total_seats, conn=conn)

            conn.commit()
            flash('Route added successfully!', 'success')
            return redirect(url_for('admin_routes'))
        except Exception as e:
            conn.rollback()
            flash(f'An error occurred: {e}', 'danger')
        finally:
            conn.close()

    conn.close()
    return render_template('add_route.html')


@app.route('/admin/routes/edit/<int:route_id>', methods=['GET', 'POST'])
def edit_route(route_id):
    if not is_admin():
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        origin = request.form['origin']
        destination = request.form['destination']
        departure_time = request.form['departure_time']
        route_date = request.form['date']
        price = float(request.form['price'])
        bus_number = request.form['bus_number']
        driver_name = request.form['driver_name']
        driver_contact = request.form['driver_contact']
        total_seats = int(request.form['total_seats'])

        # Get current seat count
        current_route = cur.execute("SELECT total_seats FROM routes WHERE id=?", (route_id,)).fetchone()
        current_seats = current_route['total_seats'] if current_route else 0

        # Update route info
        cur.execute("""
            UPDATE routes SET
            origin=?, destination=?, departure_time=?, date=?, price=?,
            bus_number=?, driver_name=?, driver_contact=?,
            total_seats=?
            WHERE id=?
        """, (origin, destination, departure_time, route_date, price,
              bus_number, driver_name, driver_contact,
              total_seats, route_id))

        # Update seats if count changed
        if total_seats != current_seats:
            cur.execute("DELETE FROM seats WHERE route_id=?", (route_id,))
            create_seats_for_route(route_id, total_seats, conn=conn)

        conn.commit()
        flash("Route updated successfully!", "success")
        conn.close()
        return redirect(url_for('admin_routes'))

    route = cur.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
    conn.close()
    return render_template('edit_route.html', route=route)


@app.route('/admin/routes/delete/<int:id>')
def delete_route(id):
    if not is_admin():
        return redirect(url_for('login'))

    conn = get_db()
    conn.execute("DELETE FROM routes WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash('Route deleted successfully!', 'success')
    return redirect(url_for('admin_routes'))

@app.route('/admin/reports')
def admin_reports():
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))
    
    # Get filter parameters
    report_type = request.args.get('report_type', 'weekly')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    route_id = request.args.get('route')
    page = request.args.get('page', 1, type=int)
    
    conn = get_db()
    
    # Get all routes for filter dropdown
    all_routes = conn.execute("SELECT id, origin, destination FROM routes").fetchall()
    
    # Build base query for transactions
    query = """
        SELECT 
            b.booking_id,
            r.date as date,
            r.origin,
            r.destination,
            b.passenger_name,
            b.seat_number,
            p.payment_method,
            COALESCE(p.amount, 0) as amount,
            COALESCE(p.status, 'pending') as status
        FROM bookings b
        JOIN routes r ON b.route_id = r.id
        LEFT JOIN payments p ON b.payment_id = p.id
    """
    
    conditions = []
    params = []
    
    # Apply date filters based on report type
    if report_type == 'daily':
        conditions.append("DATE(b.booking_date) = DATE('now')")
        report_period_text = "Today"
    elif report_type == 'weekly':
        conditions.append("DATE(b.booking_date) BETWEEN DATE('now', '-7 days') AND DATE('now')")
        report_period_text = "This Week"
    elif report_type == 'monthly':
        conditions.append("strftime('%Y-%m', b.booking_date) = strftime('%Y-%m', 'now')")
        report_period_text = "This Month"
    elif report_type == 'yearly':
        conditions.append("strftime('%Y', b.booking_date) = strftime('%Y', 'now')")
        report_period_text = "This Year"
    elif report_type == 'custom' and date_from and date_to:
        conditions.append("DATE(b.booking_date) BETWEEN ? AND ?")
        params.extend([date_from, date_to])
        report_period_text = f"Custom: {date_from} to {date_to}"
    else:
        report_period_text = "All Time"
    
    # Apply route filter
    if route_id:
        conditions.append("r.id = ?")
        params.append(route_id)
    
    # Combine conditions
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    # Get paginated results
    per_page = 10
    offset = (page - 1) * per_page
    
    transactions = conn.execute(
        query + " ORDER BY b.booking_date DESC LIMIT ? OFFSET ?",
        (*params, per_page, offset)
    ).fetchall()
    
    # Get total count for pagination
    total_count = conn.execute(
        "SELECT COUNT(*) FROM (" + query + ")",
        params
    ).fetchone()[0]
    
    # Calculate summary statistics
    summary_query = """
        SELECT 
            COUNT(DISTINCT b.booking_id) as total_bookings,
            COALESCE(SUM(p.amount), 0) as total_revenue,
            CASE 
                WHEN COUNT(DISTINCT b.booking_id) > 0 
                THEN COALESCE(SUM(p.amount), 0) / COUNT(DISTINCT b.booking_id)
                ELSE 0
            END as average_fare
        FROM bookings b
        LEFT JOIN payments p ON b.payment_id = p.id
        JOIN routes r ON b.route_id = r.id
    """ + (" WHERE " + " AND ".join(conditions) if conditions else "")
    
    summary = conn.execute(summary_query, params).fetchone()
    
    # Calculate percentage changes (simplified - would need historical data for accurate comparison)
    summary = dict(summary)
    summary['booking_change'] = 5.2  # Placeholder - implement actual comparison
    summary['revenue_change'] = 7.8  # Placeholder - implement actual comparison
    summary['fare_change'] = 1.5     # Placeholder - implement actual comparison
    
    # Generate chart data
    # Bookings trend data
    if report_type == 'daily':
        trend_query = """
            SELECT strftime('%H', booking_date) as hour, COUNT(*) as count
            FROM bookings
            WHERE DATE(booking_date) = DATE('now')
            GROUP BY strftime('%H', booking_date)
            ORDER BY hour
        """
        trend_data = conn.execute(trend_query).fetchall()
        bookings_trend_labels = [f"{row['hour']}:00" for row in trend_data]
        bookings_trend_data = [row['count'] for row in trend_data]
    elif report_type == 'weekly':
        trend_query = """
            SELECT strftime('%w', booking_date) as day, COUNT(*) as count
            FROM bookings
            WHERE DATE(booking_date) BETWEEN DATE('now', '-7 days') AND DATE('now')
            GROUP BY strftime('%w', booking_date)
            ORDER BY day
        """
        trend_data = conn.execute(trend_query).fetchall()
        days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        bookings_trend_labels = [days[int(row['day'])] for row in trend_data]
        bookings_trend_data = [row['count'] for row in trend_data]
    elif report_type == 'monthly':
        trend_query = """
            SELECT strftime('%d', booking_date) as day, COUNT(*) as count
            FROM bookings
            WHERE strftime('%Y-%m', booking_date) = strftime('%Y-%m', 'now')
            GROUP BY strftime('%d', booking_date)
            ORDER BY day
        """
        trend_data = conn.execute(trend_query).fetchall()
        bookings_trend_labels = [f"Day {row['day']}" for row in trend_data]
        bookings_trend_data = [row['count'] for row in trend_data]
    else:
        # Fallback if no specific trend data available
        bookings_trend_labels = []
        bookings_trend_data = []
    
    # Revenue distribution by route
    revenue_query = """
        SELECT r.origin, r.destination, COALESCE(SUM(p.amount), 0) as revenue
        FROM bookings b
        JOIN routes r ON b.route_id = r.id
        LEFT JOIN payments p ON b.payment_id = p.id
        """ + (" WHERE " + " AND ".join(conditions) if conditions else "") + """
        GROUP BY r.id
        ORDER BY revenue DESC
        LIMIT 5
    """
    revenue_data = conn.execute(revenue_query, params).fetchall()
    revenue_distribution_labels = [f"{row['origin']} → {row['destination']}" for row in revenue_data]
    revenue_distribution_data = [row['revenue'] for row in revenue_data]
    
    conn.close()
    
    # Create pagination object
    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total_count,
        'pages': (total_count + per_page - 1) // per_page,
        'has_prev': page > 1,
        'has_next': page * per_page < total_count,
        'prev_num': page - 1,
        'next_num': page + 1,
        'iter_pages': lambda left_edge=2, left_current=2, right_current=5, right_edge=2: 
            list(range(1, left_edge + 1)) + 
            (['...'] if page - left_current - left_edge > 1 else []) + 
            list(range(max(1, page - left_current), min(page + right_current + 1, (total_count + per_page - 1) // per_page + 1))) + 
            (['...'] if page + right_current + right_edge < (total_count + per_page - 1) // per_page else []) + 
            list(range(max(1, (total_count + per_page - 1) // per_page - right_edge + 1), (total_count + per_page - 1) // per_page + 1))
    }
    
    return render_template('admin_reports.html',
                         transactions=transactions,
                         summary=summary,
                         all_routes=all_routes,
                         pagination=pagination,
                         report_type=report_type,
                         date_from=date_from,
                         date_to=date_to,
                         route_id=route_id,
                         report_period_text=report_period_text,
                         bookings_trend_labels=bookings_trend_labels,
                         bookings_trend_data=bookings_trend_data,
                         revenue_distribution_labels=revenue_distribution_labels,
                         revenue_distribution_data=revenue_distribution_data)

@app.route('/admin/export_reports')
def export_reports():
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))
    
    format = request.args.get('format', 'csv')
    # In a real implementation, you would generate the file here
    # This is just a placeholder for the example
    
    if format == 'csv':
        # Generate CSV file
        flash("CSV export started", "success")
        return "CSV export would be generated here"
    elif format == 'excel':
        # Generate Excel file
        flash("Excel export started", "success")
        return "Excel export would be generated here"
    elif format == 'pdf':
        # Generate PDF file
        flash("PDF export started", "success")
        return "PDF export would be generated here"
    else:
        flash("Invalid export format", "danger")
        return redirect(url_for('admin_reports'))


@app.route('/admin/bookings')
def admin_view_bookings():
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))

    conn = get_db()
    
    # Base query
    query = """
        SELECT b.booking_id, b.passenger_name, b.contact, b.seat_number,
               r.origin, r.destination, r.date, r.departure_time, r.bus_number,
               CASE WHEN cr.id IS NOT NULL THEN 1 ELSE 0 END as cancellation_requested
        FROM bookings b
        JOIN routes r ON b.route_id = r.id
        LEFT JOIN cancellation_requests cr ON b.booking_id = cr.booking_id AND cr.status = 'pending'
    """
    
    # Filter conditions
    conditions = []
    params = []
    
    # Booking ID filter
    if request.args.get('booking_id'):
        conditions.append("b.booking_id LIKE ?")
        params.append(f"%{request.args.get('booking_id')}%")
    
    # Route filter
    if request.args.get('route'):
        conditions.append("b.route_id = ?")
        params.append(request.args.get('route'))
    
    # Date range filter
    if request.args.get('date_from'):
        conditions.append("r.date >= ?")
        params.append(request.args.get('date_from'))
    if request.args.get('date_to'):
        conditions.append("r.date <= ?")
        params.append(request.args.get('date_to'))
    
    # Seat type filter
    if request.args.get('seat_type'):
        conditions.append("b.seat_number LIKE ?")
        params.append(f"{'P' if request.args.get('seat_type') == 'premium' else 'S'}%")
    
    # Status filter
    if request.args.get('status') == 'cancelled':
        conditions.append("cr.status = 'approved'")
    elif request.args.get('status') == 'active':
        conditions.append("(cr.status IS NULL OR cr.status != 'approved')")
    
    # Combine conditions
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY r.date DESC, r.departure_time DESC"
    
    # Execute query
    bookings = conn.execute(query, params).fetchall()
    all_routes = conn.execute("SELECT id, origin, destination FROM routes").fetchall()
    conn.close()
    
    return render_template('admin_bookings.html', bookings=bookings, all_routes=all_routes)

# ------------------------ User Routes: View & Book Routes ------------------------

@app.route('/routes')
def show_routes():
    conn = get_db()
    
    # Base query
    query = "SELECT * FROM routes WHERE date >= DATE('now')"
    conditions = []
    params = []
    
    # Origin filter
    if request.args.get('origin'):
        conditions.append("origin = ?")
        params.append(request.args.get('origin'))
    
    # Destination filter
    if request.args.get('destination'):
        conditions.append("destination = ?")
        params.append(request.args.get('destination'))
    
    # Specific date filter
    if request.args.get('date'):
        conditions.append("date = ?")
        params.append(request.args.get('date'))
    
    # Price range filter
    if request.args.get('price_range'):
        price_range = request.args.get('price_range')
        if price_range == '0-500':
            conditions.append("price <= 500")
        elif price_range == '500-1000':
            conditions.append("price > 500 AND price <= 1000")
        elif price_range == '1000':
            conditions.append("price > 1000")
    
    # Combine conditions
    if conditions:
        query += " AND " + " AND ".join(conditions)
    
    query += " ORDER BY date, departure_time"
    
    routes = conn.execute(query, params).fetchall()
    locations = conn.execute("SELECT DISTINCT origin FROM routes UNION SELECT DISTINCT destination FROM routes").fetchall()
    conn.close()
    
    return render_template('routes.html', routes=routes, locations=[loc[0] for loc in locations])


@app.route('/book/<int:route_id>')
def book_seats(route_id):
    if 'user_id' not in session:
        flash("Please log in to book tickets.", "warning")
        return redirect(url_for('login'))

    conn = get_db()
    route = conn.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
    seats = conn.execute("""
        SELECT * FROM seats
        WHERE route_id = ?
        ORDER BY
            CASE WHEN seat_type = 'premium' THEN 1 ELSE 2 END,
            seat_number
    """, (route_id,)).fetchall()
    conn.close()
    
    if not route:
        flash("Route not found.", "danger")
        return redirect(url_for('show_routes'))
    
    user_id = session.get('user_id')
    conn = get_db()
    user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    return render_template('select_seats.html',
                            user=user,
                            seats=seats,
                            route=route,
                            route_id=route_id)

@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    if 'user_id' not in session:
        flash("You must be logged in to book tickets.", "danger")
        return redirect(url_for('login'))

    route_id = request.form.get('route_id')
    selected_seats = request.form.getlist('selected_seats')
    passenger_name = request.form.get('passenger_name')
    contact = request.form.get('contact')
    user_id = session['user_id']

    if not selected_seats:
        flash("Please select at least one seat.", "warning")
        return redirect(url_for('book_seats', route_id=route_id))

    conn = get_db()
    cur = conn.cursor()
    booking_ids = []

    try:
        # First verify all seats are available
        for seat in selected_seats:
            seat_status = cur.execute("""
                SELECT is_booked FROM seats
                WHERE route_id = ? AND seat_number = ?
            """, (route_id, seat)).fetchone()
            if seat_status and seat_status['is_booked'] == 1:
                flash(f"Seat {seat} is already booked. Please try again.", "danger")
                conn.close()
                return redirect(url_for('book_seats', route_id=route_id))

        # If all seats available, create bookings
        for seat in selected_seats:
            booking_id = str(uuid.uuid4())[:8]
            cur.execute("""
                INSERT INTO bookings (booking_id, route_id, seat_number, passenger_name, contact, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (booking_id, route_id, seat, passenger_name, contact, user_id))
            
            # Mark seat as booked
            cur.execute("""
                UPDATE seats SET is_booked = 1 WHERE route_id = ? AND seat_number = ?
            """, (route_id, seat))
            booking_ids.append(booking_id)

        conn.commit()
        
        # Redirect to payment with booking IDs and route ID
        return redirect(url_for('payment', booking_ids=','.join(booking_ids), route_id=route_id))
    
    except Exception as e:
        conn.rollback()
        flash(f"An error occurred during booking: {e}", "danger")
        return redirect(url_for('show_routes'))
    finally:
        conn.close()


@app.route('/payment')
def payment():
    if 'user_id' not in session:
        flash("Please log in to complete your booking.", "warning")
        return redirect(url_for('login'))

    booking_ids_str = request.args.get('booking_ids')
    route_id = request.args.get('route_id')

    if not booking_ids_str or not route_id:
        flash("Invalid payment request.", "danger")
        return redirect(url_for('show_routes'))

    booking_ids = booking_ids_str.split(',')
    conn = get_db()
    
    try:
        # Fetch bookings and route details
        placeholders = ','.join(['?'] * len(booking_ids))
        bookings = conn.execute(f"""
            SELECT b.*, r.price, r.origin, r.destination, r.date, r.departure_time
            FROM bookings b
            JOIN routes r ON b.route_id = r.id
            WHERE b.booking_id IN ({placeholders})
        """, booking_ids).fetchall()

        if not bookings:
            flash("No bookings found for payment.", "danger")
            return redirect(url_for('show_routes'))

        route = conn.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
        
        # Calculate total amount
        total_fare = sum(booking['price'] for booking in bookings)
        service_fee = total_fare * 0.05
        
        return render_template('payment.html',
                               bookings=bookings,
                               route=route,
                               total_amount=total_fare,
                               service_fee=service_fee,
                               booking_ids=booking_ids_str)
    except Exception as e:
        flash(f"An error occurred: {e}", "danger")
        return redirect(url_for('show_routes'))
    finally:
        conn.close()

@app.route('/process_payment', methods=['POST'])
def process_payment():
    if 'user_id' not in session:
        flash("You must be logged in to process a payment.", "danger")
        return redirect(url_for('login'))

    booking_ids_str = request.form.get('booking_ids')
    route_id = request.form.get('route_id')
    payment_method = request.form.get('payment_method')

    if not booking_ids_str or not route_id or not payment_method:
        flash("Invalid payment data.", "danger")
        return redirect(url_for('routes'))

    user_id = session['user_id']
    booking_ids = booking_ids_str.split(',')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Get total amount from bookings
        placeholders = ','.join(['?'] * len(booking_ids))
        total_amount = cur.execute(f"""
            SELECT SUM(r.price)
            FROM bookings b
            JOIN routes r ON b.route_id = r.id
            WHERE b.booking_id IN ({placeholders})
        """, booking_ids).fetchone()[0]
        
        service_fee = total_amount * 0.05
        total_with_fee = total_amount + service_fee

        # Create payment record
        transaction_id = str(uuid.uuid4())
        
        cur.execute("""
            INSERT INTO payments (booking_ids, route_id, user_id, amount, payment_method, transaction_id, status)
            VALUES (?, ?, ?, ?, ?, ?, 'completed')
        """, (booking_ids_str, route_id, user_id, total_with_fee, payment_method, transaction_id))
        
        payment_id = cur.lastrowid

        # Update bookings with payment info
        for booking_id in booking_ids:
            cur.execute("""
                UPDATE bookings SET
                payment_id = ?,
                status = 'confirmed',
                booking_date = datetime('now')
                WHERE booking_id = ?
            """, (payment_id, booking_id))
            
            # Create a ticket
            ticket_id = f"TICK-{random.randint(10000, 99999)}"
            cur.execute("""
                INSERT INTO tickets (booking_id, ticket_id, issue_date)
                VALUES ((SELECT id FROM bookings WHERE booking_id = ?), ?, datetime('now'))
            """, (booking_id, ticket_id))

        conn.commit()
        
        flash("Payment successful! Your booking is confirmed.", "success")
        return redirect(url_for('payment_success', payment_id=payment_id))

    except Exception as e:
        conn.rollback()
        flash(f"An error occurred during payment processing: {e}", "danger")
        return redirect(url_for('payment', booking_ids=booking_ids_str, route_id=route_id))
    finally:
        conn.close()

@app.route('/payment_success')
def payment_success():
    if 'user_id' not in session:
        flash("Please log in.", "warning")
        return redirect(url_for('login'))
    
    payment_id = request.args.get('payment_id')
    if not payment_id:
        flash("Invalid request. No payment details found.", "danger")
        return redirect(url_for('dashboard'))
    
    conn = get_db()
    
    try:
        # Get payment details
        payment_details = conn.execute("""
            SELECT * FROM payments WHERE id = ? AND user_id = ?
        """, (payment_id, session['user_id'])).fetchone()
        
        if not payment_details:
            flash("Payment details not found or access denied.", "danger")
            return redirect(url_for('dashboard'))

        # Get all bookings for this payment
        booking_ids = payment_details['booking_ids'].split(',')
        placeholders = ','.join(['?'] * len(booking_ids))

        bookings = conn.execute(f"""
            SELECT 
                b.booking_id,
                b.passenger_name,
                b.contact,
                b.seat_number,
                b.booking_date,
                r.origin, 
                r.destination, 
                r.date, 
                r.departure_time,
                r.price,
                t.ticket_id
            FROM bookings b
            JOIN routes r ON b.route_id = r.id
            JOIN tickets t ON b.id = t.booking_id
            WHERE b.booking_id IN ({placeholders})
            ORDER BY b.id
        """, booking_ids).fetchall()
        
        # Calculate total amount
        total_amount = sum(booking['price'] for booking in bookings)
        service_fee = total_amount * 0.05
        
        return render_template('payment_success.html',
                            payment=payment_details,
                            bookings=bookings,  # This is now a list of all bookings
                            total_amount=total_amount,
                            service_fee=service_fee)
    except Exception as e:
        flash(f"An error occurred: {e}", "danger")
        return render_template('payment_success.html',
                            payment=payment_details,
                            bookings=bookings,  # This is now a list of all bookings
                            total_amount=total_amount,
                            service_fee=service_fee)
    finally:
        conn.close()

TICKETS_DIR = os.path.join(os.path.dirname(__file__), 'tickets')
os.makedirs(TICKETS_DIR, exist_ok=True)

def generate_ticket_pdf(ticket_id, booking_details):
    """Generate a PDF ticket file"""
    file_path = os.path.join(TICKETS_DIR, f"{ticket_id}.pdf")
    c = canvas.Canvas(file_path)
    
    # Customize your ticket design here
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 800, "BUS TICKET")
    c.setFont("Helvetica", 12)
    c.drawString(100, 770, f"Ticket ID: {ticket_id}")
    c.drawString(100, 750, f"Route: {booking_details['origin']} → {booking_details['destination']}")
    # Add more details as needed
    
    c.save()
    return file_path

def get_ticket_data(ticket_id):
    """Retrieve ticket data from database"""
    conn = get_db_connection()
    try:
        ticket = conn.execute("""
            SELECT 
                t.ticket_id,
                b.booking_id,
                b.passenger_name,
                b.seat_number,
                r.origin,
                r.destination,
                r.date,
                r.departure_time,
                r.price
            FROM tickets t
            JOIN bookings b ON t.booking_id = b.id
            JOIN routes r ON b.route_id = r.id
            WHERE t.ticket_id = ?
        """, (ticket_id,)).fetchone()
        
        return dict(ticket) if ticket else None
        
    except Exception as e:
        print(f"Error fetching ticket data: {e}")
        return None
    finally:
        conn.close()

from flask import render_template_string, make_response

from flask import render_template_string, make_response

@app.route('/download-ticket/<ticket_id>')
def download_ticket(ticket_id):
    ticket_data = get_ticket_data(ticket_id)
    
    if not ticket_data:
        flash("Ticket not found", "error")
        return redirect(url_for('dashboard'))
    
    html_ticket = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ticket {ticket_id}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap');
            
            body {{
                font-family: 'Poppins', sans-serif;
                margin: 0;
                padding: 20px;
                background: #f8f9fa;
                display: flex;
                justify-content: center;
                min-height: 100vh;
            }}
            
            .ticket-container {{
                width: 100%;
                max-width: 420px;
            }}
            
            .ticket {{
                background: white;
                border-radius: 12px;
                box-shadow: 0 6px 18px rgba(0,0,0,0.08);
                overflow: hidden;
                position: relative;
            }}
            
            .ticket:before {{
                content: "";
                position: absolute;
                top: 0;
                left: 30px;
                right: 30px;
                height: 1px;
                background: repeating-linear-gradient(
                    to right,
                    transparent 0,
                    transparent 5px,
                    #e0e0e0 5px,
                    #e0e0e0 10px
                );
            }}
            
            .ticket-header {{
                background: linear-gradient(135deg, #0d6efd, #0b5ed7);
                color: white;
                padding: 20px;
                text-align: center;
                position: relative;
            }}
            
            .ticket-header h2 {{
                margin: 0;
                font-weight: 600;
                letter-spacing: 0.5px;
            }}
            
            .ticket-header p {{
                margin: 5px 0 0;
                opacity: 0.9;
                font-size: 14px;
            }}
            
            .ticket-body {{
                padding: 25px;
            }}
            
            .ticket-info {{
                display: grid;
                gap: 16px;
            }}
            
            .info-section {{
                margin-bottom: 20px;
            }}
            
            .info-section h3 {{
                margin: 0 0 12px 0;
                color: #0d6efd;
                font-size: 16px;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            
            .info-row {{
                display: flex;
                margin-bottom: 8px;
                align-items: center;
            }}
            
            .info-label {{
                width: 100px;
                color: #666;
                font-size: 14px;
                font-weight: 400;
            }}
            
            .info-value {{
                flex: 1;
                font-weight: 500;
            }}
            
            .highlight-value {{
                font-weight: 600;
                color: #0d6efd;
            }}
            
            .seat-badge {{
                display: inline-block;
                padding: 4px 10px;
                background: #f0f7ff;
                color: #0d6efd;
                border-radius: 20px;
                font-size: 14px;
                font-weight: 500;
                border: 1px solid rgba(13, 110, 253, 0.2);
            }}
            
            .route-display {{
                display: flex;
                align-items: center;
                margin: 15px 0;
            }}
            
            .route-stops {{
                flex: 1;
                text-align: center;
            }}
            
            .route-origin, .route-destination {{
                font-weight: 500;
                font-size: 16px;
            }}
            
            .route-arrow {{
                margin: 0 10px;
                color: #0d6efd;
                font-size: 20px;
            }}
            
            .ticket-footer {{
                background: #f8f9fa;
                padding: 15px 25px;
                text-align: center;
                border-top: 1px dashed #e0e0e0;
                font-size: 13px;
                color: #666;
            }}
            
            @media print {{
                body {{
                    background: white;
                    padding: 0;
                }}
                .ticket {{
                    box-shadow: none;
                    border-radius: 0;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="ticket-container">
            <div class="ticket">
                <div class="ticket-header">
                    <h2>BUS TICKET</h2>
                    <p>Booking Reference: {ticket_data['booking_id']}</p>
                </div>
                
                <div class="ticket-body">
                    <div class="info-section">
                        <h3>Passenger Information</h3>
                        <div class="ticket-info">
                            <div class="info-row">
                                <span class="info-label">Name:</span>
                                <span class="info-value highlight-value">{ticket_data['passenger_name']}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Seat:</span>
                                <span class="info-value">
                                    <span class="seat-badge">{ticket_data['seat_number']}</span>
                                </span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="info-section">
                        <h3>Journey Details</h3>
                        <div class="route-display">
                            <div class="route-stops">
                                <div class="route-origin">{ticket_data['origin']}</div>
                            </div>
                            <div class="route-arrow">→</div>
                            <div class="route-stops">
                                <div class="route-destination">{ticket_data['destination']}</div>
                            </div>
                        </div>
                        
                        <div class="ticket-info">
                            <div class="info-row">
                                <span class="info-label">Date:</span>
                                <span class="info-value">{ticket_data['date']}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Time:</span>
                                <span class="info-value">{ticket_data['departure_time']}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Duration:</span>
                                <span class="info-value">Approx. 4 hours</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="info-section">
                        <h3>Fare Details</h3>
                        <div class="ticket-info">
                            <div class="info-row">
                                <span class="info-label">Fare:</span>
                                <span class="info-value highlight-value">Rs. {ticket_data['price']:.2f}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Status:</span>
                                <span class="info-value" style="color: #28a745;">Confirmed</span>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="ticket-footer">
                    <p>Please present this ticket when boarding the bus</p>
                    <p>Thank you for choosing our service</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    response = make_response(html_ticket)
    response.headers['Content-Type'] = 'text/html'
    response.headers['Content-Disposition'] = f'attachment; filename=ticket_{ticket_id}.html'
    return response

# ------------------------ User Bookings ------------------------

@app.route('/my_bookings')
def user_bookings():
    if 'user_id' not in session:
        flash("Please log in to view your bookings.", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db()
    
    # Base query
    query = """
        SELECT b.*, r.origin, r.destination, r.date, r.departure_time, r.bus_number, r.driver_name, r.driver_contact, r.price, cr.status as cancellation_status
        FROM bookings b
        JOIN routes r ON b.route_id = r.id
        LEFT JOIN cancellation_requests cr ON b.booking_id = cr.booking_id
        WHERE b.user_id = ?
    """
    params = [user_id]
    conditions = []

    # Status filter
    status = request.args.get('status')
    if status == 'upcoming':
        conditions.append("(r.date > DATE('now') OR (r.date = DATE('now') AND r.departure_time > TIME('now')))")
    elif status == 'past':
        conditions.append("(r.date < DATE('now') OR (r.date = DATE('now') AND r.departure_time < TIME('now')))")
    elif status == 'cancelled':
        conditions.append("cr.status = 'approved'")
    
    # Date range filter
    if request.args.get('date_from'):
        conditions.append("r.date >= ?")
        params.append(request.args.get('date_from'))
    if request.args.get('date_to'):
        conditions.append("r.date <= ?")
        params.append(request.args.get('date_to'))

    # Combine conditions
    if conditions:
        query += " AND " + " AND ".join(conditions)
    
    query += " ORDER BY r.date DESC, r.departure_time DESC"

    bookings = conn.execute(query, params).fetchall()
    conn.close()

    return render_template('my_bookings.html', bookings=bookings)

# User cancellation request
@app.route('/request_cancellation/<booking_id>', methods=['GET', 'POST'])
def request_cancellation(booking_id):
    if 'user_id' not in session:
        flash("Please log in to request a cancellation.", "warning")
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db()
    
    # Check if the booking belongs to the current user
    booking = conn.execute("""
        SELECT * FROM bookings WHERE booking_id = ? AND user_id = ?
    """, (booking_id, user_id)).fetchone()
    
    if not booking:
        flash("Booking not found or you do not have permission to cancel it.", "danger")
        return redirect(url_for('user_bookings'))
    
    # Check if a cancellation request already exists
    existing_request = conn.execute("""
        SELECT * FROM cancellation_requests WHERE booking_id = ? AND status = 'pending'
    """, (booking_id,)).fetchone()
    
    if existing_request:
        flash("A cancellation request for this booking is already pending.", "info")
        return redirect(url_for('user_bookings'))
        
    if request.method == 'POST':
        reason = request.form.get('reason')
        if not reason:
            flash("Please provide a reason for cancellation.", "danger")
            return redirect(url_for('request_cancellation', booking_id=booking_id))
        
        try:
            conn.execute("""
                INSERT INTO cancellation_requests (booking_id, user_id, reason, status)
                VALUES (?, ?, ?, 'pending')
            """, (booking_id, user_id, reason))
            conn.commit()
            flash("Cancellation request submitted successfully. It will be reviewed by an admin.", "success")
            return redirect(url_for('user_bookings'))
        except Exception as e:
            conn.rollback()
            flash(f"An error occurred while submitting the request: {e}", "danger")
        finally:
            conn.close()
    
    conn.close()
    return render_template('request_cancellation.html', booking=booking)


@app.route('/admin/cancellations')
def admin_cancellations():
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))

    # Get filter parameters from request
    booking_id = request.args.get('booking_id')
    route_id = request.args.get('route')
    passenger_name = request.args.get('passenger')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    conn = get_db()
    
    # Base query
    query = """
        SELECT 
            cr.*, 
            u.username, 
            u.email,
            b.passenger_name,
            b.seat_number,
            r.origin, 
            r.destination, 
            r.date, 
            r.departure_time
        FROM cancellation_requests cr
        JOIN users u ON cr.user_id = u.id
        JOIN bookings b ON cr.booking_id = b.booking_id
        JOIN routes r ON b.route_id = r.id
        WHERE cr.status = 'pending'
    """
    
    conditions = []
    params = []
    
    # Booking ID filter
    if booking_id:
        conditions.append("b.booking_id LIKE ?")
        params.append(f"%{booking_id}%")
    
    # Route filter
    if route_id:
        conditions.append("b.route_id = ?")
        params.append(route_id)
    
    # Passenger name filter
    if passenger_name:
        conditions.append("b.passenger_name LIKE ?")
        params.append(f"%{passenger_name}%")
    
    # Date range filter
    if date_from:
        conditions.append("r.date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("r.date <= ?")
        params.append(date_to)
    
    # Combine conditions
    if conditions:
        query += " AND " + " AND ".join(conditions)
    
    query += " ORDER BY cr.created_at DESC"
    
    requests = conn.execute(query, params).fetchall()
    all_routes = conn.execute("SELECT id, origin, destination FROM routes").fetchall()
    conn.close()
    
    # Prepare filter_args to preserve filter values in the form
    filter_args = {
        'booking_id': booking_id or '',
        'route': route_id or '',
        'passenger': passenger_name or '',
        'date_from': date_from or '',
        'date_to': date_to or ''
    }
    
    return render_template('admin_cancellations.html',
                         requests=requests,
                         all_routes=all_routes,
                         filter_args=filter_args)

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/admin/cancellations/<int:id>/<status>')
def handle_cancellation(id, status):
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        request_details = cur.execute("SELECT * FROM cancellation_requests WHERE id = ?", (id,)).fetchone()
        
        if not request_details:
            flash("Cancellation request not found.", "danger")
            return redirect(url_for('admin_cancellations'))
            
        booking_id = request_details['booking_id']
        
        if status == 'approve':
            # Update request status
            cur.execute("UPDATE cancellation_requests SET status = 'approved', processed_at = CURRENT_TIMESTAMP WHERE id = ?", (id,))
            
            # Find the booking and associated seat
            booking_to_cancel = cur.execute("SELECT seat_number, route_id FROM bookings WHERE booking_id = ?", (booking_id,)).fetchone()
            
            if booking_to_cancel:
                seat_number = booking_to_cancel['seat_number']
                route_id = booking_to_cancel['route_id']
                
                # Unbook the seat
                cur.execute("UPDATE seats SET is_booked = 0 WHERE route_id = ? AND seat_number = ?", (route_id, seat_number))
                
                # Update booking status (optional, but good practice)
                cur.execute("UPDATE bookings SET status = 'cancelled' WHERE booking_id = ?", (booking_id,))
                
                flash(f"Cancellation for booking {booking_id} approved. Seat is now available.", "success")
            else:
                flash("Booking not found during cancellation process. Seat not unbooked.", "warning")
            
        elif status == 'reject':
            cur.execute("UPDATE cancellation_requests SET status = 'rejected', processed_at = CURRENT_TIMESTAMP WHERE id = ?", (id,))
            flash(f"Cancellation for booking {booking_id} rejected.", "info")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"An error occurred: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_cancellations'))

@app.route('/admin/cancellations/<int:request_id>/<action>')
def process_cancellation(request_id, action):
    if not is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for('login'))

    if action not in ['approve', 'reject']:
        flash("Invalid action.", "danger")
        return redirect(url_for('admin_cancellations'))

    conn = get_db()
    
    try:
        # Get the cancellation request
        request_data = conn.execute("""
            SELECT * FROM cancellation_requests 
            WHERE id = ? AND status = 'pending'
        """, (request_id,)).fetchone()
        
        if not request_data:
            flash("Request not found or already processed.", "warning")
            return redirect(url_for('admin_cancellations'))
        
        booking_id = request_data['booking_id']
        
        if action == 'approve':
            # Get booking details
            booking = conn.execute("""
                SELECT seat_number, route_id FROM bookings 
                WHERE booking_id = ?
            """, (booking_id,)).fetchone()
            
            if booking:
                # Free up the seat
                conn.execute("""
                    UPDATE seats SET is_booked = 0 
                    WHERE route_id = ? AND seat_number = ?
                """, (booking['route_id'], booking['seat_number']))
                
                # Update booking status
                conn.execute("""
                    UPDATE bookings SET status = 'cancelled' 
                    WHERE booking_id = ?
                """, (booking_id,))
                
                flash_message = f"Cancellation for booking {booking_id} approved. Seat is now available."
            else:
                flash_message = "Booking not found during cancellation process."
            
            # Update request status
            conn.execute("""
                UPDATE cancellation_requests 
                SET status = 'approved', processed_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (request_id,))
            
            flash(flash_message, "success")
            
        elif action == 'reject':
            conn.execute("""
                UPDATE cancellation_requests 
                SET status = 'rejected', processed_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (request_id,))
            flash(f"Cancellation for booking {booking_id} rejected.", "info")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f"An error occurred: {str(e)}", "danger")
    finally:
        conn.close()
    
    return redirect(url_for('admin_cancellations'))

if __name__ == '__main__':
    app.run(debug=True)