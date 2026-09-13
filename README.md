# Bus Ticket Management System

A Flask-based bus ticket booking application for managing routes, seat selection, bookings, payments, ticket generation, and cancellation workflows for both users and administrators.

## Features

- User registration and login
- Search available bus routes by origin, destination, and date
- Seat selection and booking flow
- Payment processing and confirmation
- Ticket generation and download support
- User dashboard for viewing bookings
- Booking cancellation requests
- Admin dashboard for managing routes and bookings
- Reports and analytics for admin users
- SQLite-backed database for application data

## Tech Stack

- Python 3.x
- Flask
- SQLite
- Flask-Bcrypt
- Jinja2 templates
- HTML/CSS/JavaScript

## Project Structure

- `app.py` – Main Flask application and route logic
- `requirements.txt` – Python dependencies
- `static/` – CSS, images, and frontend assets
- `templates/` – HTML templates for the web UI
- `db/` – Database files

## Getting Started

### 1. Clone the repository

```bash
git clone <repository-url>
cd Bus-Ticket-Management-System
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

On Windows:

```bash
venv\Scripts\activate
```

On macOS/Linux:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

```bash
python app.py
```

Then open your browser at:

```text
http://127.0.0.1:5000/
```

## Default Access

### User

- Register a new account from the home page or login page
- Browse and search routes
- Book a ticket and make payment

### Admin

- Log in with an admin account
- Manage routes, reports, bookings, and cancellation requests

## Functional Overview

### User Flow

1. Register or login
2. Search routes by route details
3. Select a seat
4. Confirm booking
5. Complete payment
6. View booking history and download ticket

### Admin Flow

1. Login as admin
2. Add, edit, or delete routes
3. View booking records
4. Review cancellation requests
5. View reports and analytics

## Database

The system uses SQLite for persistent data such as:

- users
- routes
- seats
- bookings
- payments
- tickets
- cancellation requests

If needed, the database file can be created or adjusted based on your local environment setup.

## Notes

- The application runs in debug mode during local development.
- You may need to initialize or verify the SQLite database schema before first use depending on your environment.
- For production deployment, configure a secure secret key and disable debug mode.

## License

This project is intended for educational and local development use.
