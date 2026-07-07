# DEMO FILE — intentionally vulnerable. Used to showcase Tythan Code's
# security audit. Do NOT deploy or reuse this code.

import hashlib
import sqlite3
import subprocess

import requests
from flask import Flask, request

app = Flask(__name__)

# Hardcoded credential (the audit flags this as HIGH)
DB_PASSWORD = "supersecret-demo-password-123"

# Debug mode left on (MEDIUM — RCE if ever deployed like this)
DEBUG = True


@app.route("/user")
def get_user():
    username = request.args.get("name", "")
    conn = sqlite3.connect("demo.db")
    # SQL built with an f-string (HIGH — classic injection)
    cursor = conn.execute(f"SELECT * FROM users WHERE name = '{username}'")
    row = cursor.fetchone()
    return {"user": row}


@app.route("/ping")
def ping():
    host = request.args.get("host", "localhost")
    # shell=True with user input (MEDIUM — command injection)
    result = subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)
    return {"output": result.stdout.decode()}


@app.route("/login", methods=["POST"])
def login():
    password = request.form.get("password", "")
    # MD5 for passwords (MEDIUM — not a password hash)
    digest = hashlib.md5(password.encode()).hexdigest()
    return {"digest": digest}


def fetch_partner_data():
    # TLS verification disabled + plain http fallback (HIGH / MEDIUM)
    response = requests.get("https://partner.example.com/api", verify=False)
    backup = requests.get("http://partner-backup.example.com/api")
    return response.json() or backup.json()


if __name__ == "__main__":
    # Bound to all interfaces with debug on (MEDIUM)
    app.run(host="0.0.0.0", debug=True)
