from flask import Flask, request, jsonify, render_template_string, redirect, url_for, flash
import secrets
import requests
import sqlite3
import datetime
import os
import bcrypt
import re
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@monsaas.com')
DB_NAME = "saas_pro.db"
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'mistral')  # Utilise Mistral par défaut

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ============================================
# MODÈLE UTILISATEUR
# ============================================
class User(UserMixin):
    def __init__(self, id, email, plan, requests_used, month_year, password_hash, is_admin=False):
        self.id = id
        self.email = email
        self.plan = plan
        self.requests_used = requests_used
        self.month_year = month_year
        self.password_hash = password_hash
        self.is_admin = is_admin


@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, email, plan, requests_used, month_year, password_hash, is_admin FROM users WHERE id = ?",
              (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2], user[3], user[4], user[5], user[6])
    return None


def get_user_by_email(email):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, email, plan, requests_used, month_year, password_hash, is_admin FROM users WHERE email = ?",
              (email,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2], user[3], user[4], user[5], user[6])
    return None


def create_user(email, password, plan='free'):
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user_id = secrets.token_urlsafe(16)
    current_month = datetime.datetime.now().strftime("%m-%Y")
    is_admin = 1 if email == ADMIN_EMAIL else 0
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (id, email, plan, requests_used, month_year, password_hash, is_admin) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, email, plan, 0, current_month, password_hash, is_admin))
    conn.commit()
    conn.close()
    return user_id


def init_db():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        plan TEXT DEFAULT 'free',
        requests_used INTEGER DEFAULT 0,
        month_year TEXT DEFAULT '',
        is_admin INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        content TEXT NOT NULL,
        is_user INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE activation_codes (
        code TEXT PRIMARY KEY,
        plan TEXT NOT NULL,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        expiry_date TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE user_activations (
        user_id TEXT,
        code TEXT,
        activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, code)
    )''')
    conn.commit()
    conn.close()
    print("✅ Base de données créée")


init_db()


def get_plan_limit(plan):
    limits = {'free': 20, 'pro': 200, 'business': 1000}
    return limits.get(plan, 20)


def reset_quota_if_needed(user_data):
    current_month = datetime.datetime.now().strftime("%m-%Y")
    if user_data['month_year'] != current_month:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE users SET requests_used = 0, month_year = ? WHERE id = ?", (current_month, user_data['id']))
        conn.commit()
        conn.close()
        user_data['requests_used'] = 0
        user_data['month_year'] = current_month
    return user_data


def update_user_plan(user_id, new_plan):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET plan = ? WHERE id = ?", (new_plan, user_id))
    conn.commit()
    conn.close()


def create_activation_code(plan, max_uses=1, expiry_days=30):
    code = secrets.token_hex(8).upper()
    expiry_date = datetime.datetime.now() + datetime.timedelta(days=expiry_days)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT INTO activation_codes (code, plan, max_uses, expiry_date) VALUES (?, ?, ?, ?)''',
              (code, plan, max_uses, expiry_date.isoformat()))
    conn.commit()
    conn.close()
    return code


def activate_plan_with_code(user_id, code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT plan, max_uses, used_count, expiry_date FROM activation_codes WHERE code = ?''', (code,))
    result = c.fetchone()
    if not result:
        conn.close()
        return None
    plan, max_uses, used_count, expiry_date = result
    expiry_date = datetime.datetime.fromisoformat(expiry_date)
    if expiry_date < datetime.datetime.now():
        conn.close()
        return None
    if used_count >= max_uses:
        conn.close()
        return None
    c.execute('''SELECT COUNT(*) FROM user_activations WHERE user_id = ? AND code = ?''', (user_id, code))
    if c.fetchone()[0] > 0:
        conn.close()
        return None
    c.execute('''INSERT INTO user_activations (user_id, code) VALUES (?, ?)''', (user_id, code))
    c.execute('''UPDATE activation_codes SET used_count = used_count + 1 WHERE code = ?''', (code,))
    c.execute('''UPDATE users SET plan = ? WHERE id = ?''', (plan, user_id))
    conn.commit()
    conn.close()
    return plan


def clean_response(text):
    if not text:
        return "Je n'ai pas de réponse."
    text = re.sub(r'(\.\s+)(?=[A-ZÀ-Ö])', r'.\n', text)
    text = re.sub(r'(\*\*.*?\*\*)', r'\n\1\n', text)
    text = re.sub(r'(\d+)\.\s+', r'\n\1. ', text)
    text = re.sub(r'-\s*', r'\n- ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ============================================
# HTML COMPLET (PROFESSIONNEL)
# ============================================
HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🤖 IA Pro</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); min-height:100vh; display:flex; justify-content:center; align-items:center; padding:20px; }
        .container { background:rgba(255,255,255,0.05); backdrop-filter:blur(20px); border-radius:30px; padding:30px; max-width:900px; width:100%; border:1px solid rgba(255,255,255,0.1); box-shadow:0 25px 50px -12px rgba(0,0,0,0.5); }
        .header { display:flex; justify-content:space-between; align-items:center; padding-bottom:20px; border-bottom:1px solid rgba(255,255,255,0.1); margin-bottom:20px; flex-wrap:wrap; gap:10px; }
        .header h1 { color:#fff; font-size:1.8rem; }
        .header h1 span { color:#a78bfa; }
        .user-info { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
        .badge { background:rgba(255,255,255,0.08); padding:8px 18px; border-radius:50px; color:#fff; border:1px solid rgba(255,255,255,0.06); font-size:0.9rem; }
        .badge strong { color:#a78bfa; }
        .badge-admin { background:rgba(251,191,36,0.2); color:#fbbf24; border-color:rgba(251,191,36,0.2); }
        .badge-pro { background:rgba(16,185,129,0.2); color:#10b981; border-color:rgba(16,185,129,0.2); }
        .badge-business { background:rgba(139,92,246,0.2); color:#a78bfa; border-color:rgba(139,92,246,0.2); }
        .quota-bar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:20px; padding:10px 15px; background:rgba(255,255,255,0.03); border-radius:15px; align-items:center; }
        .btn { padding:8px 20px; border:none; border-radius:50px; cursor:pointer; font-size:0.9rem; text-decoration:none; display:inline-block; transition:0.3s; }
        .btn:hover { transform:translateY(-2px); box-shadow:0 10px 20px rgba(0,0,0,0.2); }
        .btn-primary { background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; }
        .btn-danger { background:#ef4444; color:#fff; }
        .btn-success { background:#10b981; color:#fff; }
        .btn-admin { background:#f59e0b; color:#000; }
        .btn-small { padding:4px 12px; font-size:0.8rem; }
        .btn-paypal { background:#0070ba; color:#fff; font-weight:bold; }
        .messages-container { background:rgba(255,255,255,0.02); border-radius:20px; padding:20px; min-height:400px; max-height:500px; overflow-y:auto; border:1px solid rgba(255,255,255,0.05); margin-bottom:20px; }
        .message { padding:12px 18px; border-radius:16px; margin-bottom:12px; max-width:85%; word-wrap:break-word; white-space:pre-wrap; line-height:1.6; }
        .message.bot { background:rgba(255,255,255,0.08); color:#e5e7eb; border:1px solid rgba(255,255,255,0.06); margin-right:auto; }
        .message.user { background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; margin-left:auto; text-align:right; }
        .message-time { font-size:0.7rem; opacity:0.5; margin-top:5px; }
        .message.user .message-time { text-align:right; }
        .input-area { display:flex; gap:10px; }
        .input-area input { flex:1; padding:14px 20px; border:1px solid rgba(255,255,255,0.1); border-radius:50px; background:rgba(255,255,255,0.05); color:#fff; outline:none; font-size:1rem; }
        .input-area input::placeholder { color:rgba(255,255,255,0.3); }
        .input-area input:focus { border-color:#a78bfa; }
        .input-area button { padding:14px 30px; border:none; border-radius:50px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; font-weight:600; cursor:pointer; transition:0.3s; }
        .input-area button:disabled { opacity:0.5; cursor:not-allowed; }
        .error { color:#f87171; margin-top:10px; text-align:center; min-height:30px; }
        .spinner { display:inline-block; width:18px; height:18px; border:2px solid rgba(255,255,255,0.1); border-top-color:#fff; border-radius:50%; animation:spin 0.6s linear infinite; }
        @keyframes spin { to { transform:rotate(360deg); } }
        .auth-container { max-width:400px; margin:0 auto; padding:20px; }
        .auth-form input { width:100%; padding:14px 20px; margin-bottom:15px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; font-size:1rem; outline:none; }
        .auth-form input::placeholder { color:rgba(255,255,255,0.3); }
        .auth-form input:focus { border-color:#a78bfa; }
        .auth-form button { width:100%; padding:14px; border:none; border-radius:50px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; font-weight:600; font-size:1.1rem; cursor:pointer; transition:0.3s; }
        .auth-form button:hover { transform:scale(1.02); }
        .auth-links { text-align:center; margin-top:20px; color:rgba(255,255,255,0.6); }
        .auth-links a { color:#a78bfa; text-decoration:none; }
        .admin-section { margin-top:20px; border-top:2px solid rgba(251,191,36,0.2); padding-top:20px; }
        .admin-section h2 { color:#fbbf24; margin-bottom:15px; }
        .admin-card { background:rgba(255,255,255,0.03); border-radius:15px; padding:20px; border:1px solid rgba(255,255,255,0.05); margin-bottom:20px; }
        .admin-card h3 { color:#a78bfa; margin-bottom:15px; font-size:1rem; }
        .admin-table { width:100%; color:#e5e7eb; border-collapse:collapse; font-size:0.9rem; }
        .admin-table th, .admin-table td { padding:10px; text-align:left; border-bottom:1px solid rgba(255,255,255,0.05); }
        .admin-table th { color:#a78bfa; font-weight:600; }
        .admin-table .text-muted { color:rgba(255,255,255,0.4); }
        .admin-table .message-preview { max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .hidden { display:none; }
        .section-title { color:#fff; font-size:1.1rem; margin-top:15px; margin-bottom:8px; }
        .pricing-card { background:rgba(255,255,255,0.03); border-radius:15px; padding:15px; border:1px solid rgba(255,255,255,0.05); margin-bottom:10px; }
        .pricing-card h4 { color:#fff; }
        .pricing-card ul { color:rgba(255,255,255,0.6); list-style:none; padding:0; }
        .pricing-card ul li { padding:3px 0; }
        .pricing-card .price { color:#10b981; font-size:1.3rem; font-weight:bold; }
        @media (max-width:600px) { .container { padding:15px; } .header h1 { font-size:1.3rem; } .input-area { flex-direction:column; } .input-area button { width:100%; } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🧠 <span>IA Pro</span></h1>
        <div class="user-info">
            {% if current_user.is_authenticated %}
                <span class="badge">👤 {{ current_user.email }}</span>
                <span class="badge">📋 <strong>{{ plan }}</strong></span>
                <span class="badge">🦙 Mistral</span>
                {% if current_user.is_admin %}
                    <span class="badge badge-admin">⭐ Admin</span>
                {% endif %}
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-small">Déconnexion</a>
            {% endif %}
        </div>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
            <div class="alert alert-{{ category }}" style="padding:12px 18px; border-radius:10px; margin-bottom:10px; {% if category == 'success' %}background:rgba(16,185,129,0.2);color:#10b981;{% elif category == 'danger' %}background:rgba(239,68,68,0.2);color:#f87171;{% endif %}">
                {{ message }}
            </div>
        {% endfor %}
    {% endwith %}

    {% if current_user.is_authenticated %}
        <div class="quota-bar">
            <span class="badge">⚡ Requêtes : <strong>{{ remaining }}/{{ total_limit }}</strong></span>
            {% if plan == 'pro' %}
                <span class="badge badge-pro">🚀 Pro</span>
            {% elif plan == 'business' %}
                <span class="badge badge-business">💼 Business</span>
            {% else %}
                <span class="badge">🧠 Free</span>
            {% endif %}
            {% if current_user.is_admin %}
                <a href="#" onclick="toggleAdmin()" class="btn btn-admin btn-small">🛠️ Admin</a>
            {% endif %}
        </div>

        <div class="messages-container" id="messages">
            {% for msg in messages %}
                <div class="message {% if msg.is_user %}user{% else %}bot{% endif %}">{{ msg.content | safe }}<div class="message-time">{{ msg.created_at }}</div></div>
            {% endfor %}
            {% if not messages %}
                <div class="message bot">👋 Bonjour ! Je suis votre assistant IA professionnel (Mistral). Posez-moi n'importe quelle question.</div>
            {% endif %}
        </div>

        <div class="input-area">
            <input type="text" id="userPrompt" placeholder="Posez votre question..." autofocus>
            <button id="sendBtn" onclick="sendPrompt()" class="btn btn-primary">Envoyer</button>
        </div>
        <div id="errorMessage" class="error"></div>

        <!-- SECTION ABONNEMENT -->
        {% if plan == 'free' %}
        <div style="margin-top:15px; padding-top:15px; border-top:1px solid rgba(255,255,255,0.05);">
            <h3 class="section-title">🔥 Passez en Pro (29€/mois)</h3>
            <div class="pricing-card">
                <h4>📋 Plan Pro</h4>
                <ul>
                    <li>✅ Réponses <strong>plus longues</strong> (400 tokens)</li>
                    <li>✅ Qualité <strong>professionnelle</strong></li>
                    <li>✅ <strong>200 requêtes</strong> par mois</li>
                    <li>✅ Support prioritaire</li>
                </ul>
                <p class="price">29€/mois</p>
            </div>
            <div class="pricing-card">
                <h4>💼 Plan Business</h4>
                <ul>
                    <li>✅ Réponses <strong>maximales</strong> (600 tokens)</li>
                    <li>✅ Qualité <strong>expert</strong></li>
                    <li>✅ <strong>1000 requêtes</strong> par mois</li>
                    <li>✅ Support prioritaire 24/7</li>
                </ul>
                <p class="price">99€/mois</p>
            </div>
            <a href="https://paypal.me/creatydesign/29" target="_blank" class="btn btn-paypal" style="display:block; width:100%; padding:14px; border-radius:50px; text-align:center; font-size:1.1rem;">
                💳 Payer avec PayPal
            </a>
            <p style="color:rgba(255,255,255,0.3); font-size:0.7rem; margin-top:5px;">
                Après paiement, votre compte sera activé manuellement par l'administrateur.
            </p>
        </div>
        {% elif plan == 'pro' %}
        <div style="margin-top:15px; padding-top:15px; border-top:1px solid rgba(255,255,255,0.05);">
            <h3 class="section-title">🚀 Vous êtes en Pro !</h3>
            <p style="color:rgba(255,255,255,0.5);">Merci de votre confiance. Profitez de nos services premium.</p>
            <a href="https://paypal.me/creatydesign/99" target="_blank" class="btn btn-paypal" style="display:block; width:100%; padding:14px; border-radius:50px; text-align:center; font-size:1.1rem;">
                💳 Passer en Business (99€/mois)
            </a>
        </div>
        {% endif %}

        <!-- CODES D'ACTIVATION -->
        <div style="margin-top:15px; padding-top:15px; border-top:1px solid rgba(255,255,255,0.05);">
            <h3 class="section-title">🎁 Code d'activation</h3>
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:8px;">
                <input type="text" id="redeemCode" placeholder="Entrez votre code..." style="flex:1; padding:10px 18px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; outline:none;">
                <button onclick="redeemCode()" class="btn btn-success">Activer</button>
            </div>
            <div id="redeemMessage" style="color:rgba(255,255,255,0.6); margin-top:8px;"></div>
        </div>

        <!-- PANEL ADMIN -->
        <div id="adminPanel" class="admin-section hidden">
            <h2>🛠️ Administration</h2>
            <div class="admin-card">
                <h3>👥 Utilisateurs</h3>
                <table class="admin-table">
                    <thead><tr><th>Email</th><th>Plan</th><th>Requêtes</th><th>Actions</th></tr></thead>
                    <tbody>
                        {% for u in users %}
                        <tr>
                            <td>{{ u[1] }}</td>
                            <td><span style="background:{% if u[2] == 'pro' %}#10b981{% elif u[2] == 'business' %}#8b5cf6{% else %}#6b7280{% endif %}; padding:2px 12px; border-radius:20px; font-size:0.8rem; color:white;">{{ u[2] }}</span></td>
                            <td>{{ u[3] }}</td>
                            <td>
                                {% if u[1] != admin_email %}
                                    <button class="btn btn-success btn-small" onclick="changePlan('{{ u[0] }}', 'pro')">Pro</button>
                                    <button class="btn btn-admin btn-small" onclick="changePlan('{{ u[0] }}', 'business')">Business</button>
                                    <button class="btn btn-danger btn-small" onclick="resetQuota('{{ u[0] }}')">Reset</button>
                                {% else %}
                                    <span class="text-muted">⭐ Admin</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="admin-card">
                <h3>🎫 Générer un code</h3>
                <form id="codeForm" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                    <select id="planSelect" style="padding:10px 18px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; outline:none;">
                        <option value="pro">Pro</option>
                        <option value="business">Business</option>
                    </select>
                    <input type="number" id="maxUses" value="1" style="padding:10px 18px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; width:100px; outline:none;">
                    <input type="number" id="expiryDays" value="30" style="padding:10px 18px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; width:100px; outline:none;">
                    <button type="submit" class="btn btn-primary">Générer</button>
                </form>
                <div id="codeResult" style="color:#10b981; margin-top:8px;"></div>
            </div>
            <div class="admin-card">
                <h3>📊 Statistiques</h3>
                <p style="color:rgba(255,255,255,0.6);">Total utilisateurs : {{ users|length }}<br>Messages envoyés : {{ total_messages }}</p>
            </div>
        </div>

    {% else %}
        {% if request.path == '/login' %}
            <div class="auth-container">
                <h2 style="color:#fff; text-align:center; margin-bottom:30px;">🔐 Connexion</h2>
                <form method="POST" class="auth-form">
                    <input type="email" name="email" placeholder="Email" required>
                    <input type="password" name="password" placeholder="Mot de passe" required>
                    <button type="submit">Se connecter</button>
                </form>
                <div class="auth-links">Pas encore de compte ? <a href="{{ url_for('register') }}">S'inscrire</a></div>
            </div>
        {% elif request.path == '/register' %}
            <div class="auth-container">
                <h2 style="color:#fff; text-align:center; margin-bottom:30px;">📝 Inscription</h2>
                <form method="POST" class="auth-form">
                    <input type="email" name="email" placeholder="Email" required>
                    <input type="password" name="password" placeholder="Mot de passe" required>
                    <input type="password" name="confirm_password" placeholder="Confirmer" required>
                    <button type="submit">Créer mon compte</button>
                </form>
                <div class="auth-links">Déjà un compte ? <a href="{{ url_for('login') }}">Se connecter</a></div>
            </div>
        {% else %}
            <div style="text-align:center; padding:40px 0;">
                <h2 style="color:#fff; font-size:2rem; margin-bottom:20px;">🤖 IA Pro</h2>
                <p style="color:rgba(255,255,255,0.5); margin-bottom:30px;">Assistant professionnel avec Mistral</p>
                <div style="display:flex; gap:15px; justify-content:center; flex-wrap:wrap;">
                    <a href="{{ url_for('login') }}" class="btn btn-primary" style="padding:14px 40px; font-size:1.1rem;">🔐 Connexion</a>
                    <a href="{{ url_for('register') }}" class="btn" style="padding:14px 40px; font-size:1.1rem; background:rgba(255,255,255,0.08); color:#fff;">📝 Inscription</a>
                </div>
            </div>
        {% endif %}
    {% endif %}

    <div style="margin-top:20px; padding-top:15px; border-top:1px solid rgba(255,255,255,0.05); text-align:center; color:rgba(255,255,255,0.2); font-size:0.7rem;">
        🧠 Propulsé par Mistral (Ollama) • IA Pro v5.0
    </div>
</div>

<script>
    function sendPrompt() {
        const input = document.getElementById('userPrompt');
        const prompt = input.value.trim();
        if (!prompt) {
            document.getElementById('errorMessage').textContent = '❌ Veuillez écrire une question.';
            return;
        }
        const messagesDiv = document.getElementById('messages');
        const userMsg = document.createElement('div');
        userMsg.className = 'message user';
        userMsg.textContent = prompt;
        messagesDiv.appendChild(userMsg);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        input.value = '';
        document.getElementById('errorMessage').textContent = '';
        const btn = document.getElementById('sendBtn');
        btn.disabled = true;
        btn.innerHTML = '⏳ Réflexion...';
        fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: prompt })
        })
        .then(response => response.json())
        .then(data => {
            const botMsg = document.createElement('div');
            botMsg.className = 'message bot';
            botMsg.innerHTML = data.answer || 'Pas de réponse';
            messagesDiv.appendChild(botMsg);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            const quota = document.querySelector('.quota-bar .badge:first-child');
            if (quota && data.remaining !== undefined) {
                quota.innerHTML = '⚡ Requêtes : <strong>' + data.remaining + '/' + data.total_limit + '</strong>';
            }
        })
        .catch(error => {
            document.getElementById('errorMessage').textContent = '❌ Erreur : Ollama est-il lancé ? (lancez "ollama serve")';
            console.error('Erreur:', error);
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = 'Envoyer';
            input.focus();
        });
    }

    async function redeemCode() {
        const input = document.getElementById('redeemCode');
        const msg = document.getElementById('redeemMessage');
        const code = input.value.trim().toUpperCase();
        if (!code) { msg.textContent = '❌ Entrez un code'; return; }
        msg.textContent = '⏳ Vérification...';
        try {
            const response = await fetch('/redeem', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code })
            });
            const data = await response.json();
            if (response.ok) {
                msg.textContent = '✅ ' + data.message;
                const plan = document.querySelector('.quota-bar .badge:nth-child(2)');
                if (plan) plan.innerHTML = '📋 Plan : <strong>' + data.plan + '</strong>';
                input.value = '';
                location.reload();
            } else {
                msg.textContent = '❌ ' + data.error;
            }
        } catch(e) { msg.textContent = '❌ Erreur réseau'; }
    }

    function toggleAdmin() {
        const panel = document.getElementById('adminPanel');
        if (panel) panel.classList.toggle('hidden');
    }

    async function changePlan(userId, plan) {
        if (!confirm('Passer cet utilisateur en plan ' + plan + ' ?')) return;
        const response = await fetch('/admin/change-plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, plan: plan })
        });
        if (response.ok) location.reload();
        else alert('Erreur');
    }

    async function resetQuota(userId) {
        if (!confirm('Réinitialiser le quota ?')) return;
        const response = await fetch('/admin/reset-quota', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        if (response.ok) location.reload();
        else alert('Erreur');
    }

    document.addEventListener('DOMContentLoaded', function() {
        const form = document.getElementById('codeForm');
        if (form) {
            form.onsubmit = async function(e) {
                e.preventDefault();
                const plan = document.getElementById('planSelect').value;
                const max_uses = document.getElementById('maxUses').value;
                const expiry_days = document.getElementById('expiryDays').value;
                const response = await fetch('/admin/generate-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ plan, max_uses, expiry_days })
                });
                const data = await response.json();
                document.getElementById('codeResult').textContent = '🎫 Code : ' + data.code;
            };
        }
        const input = document.getElementById('userPrompt');
        if (input) {
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); sendPrompt(); }
            });
        }
        const messagesDiv = document.getElementById('messages');
        if (messagesDiv) messagesDiv.scrollTop = messagesDiv.scrollHeight;
    });
</script>
</body>
</html>
"""


# ============================================
# ROUTES AUTH
# ============================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        if password != confirm:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template_string(HTML, request=request, admin_email=ADMIN_EMAIL)
        if get_user_by_email(email):
            flash('Cet email est déjà utilisé', 'danger')
            return render_template_string(HTML, request=request, admin_email=ADMIN_EMAIL)
        create_user(email, password)
        flash('Compte créé ! Connectez-vous.', 'success')
        return redirect(url_for('login'))
    return render_template_string(HTML, request=request, admin_email=ADMIN_EMAIL)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = get_user_by_email(email)
        if user and bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            login_user(user)
            flash('Connecté !', 'success')
            return redirect(url_for('index'))
        else:
            flash('Email ou mot de passe incorrect', 'danger')
    return render_template_string(HTML, request=request, admin_email=ADMIN_EMAIL)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnecté', 'info')
    return redirect(url_for('login'))


# ============================================
# ROUTE INDEX
# ============================================

@app.route('/')
@login_required
def index():
    user = get_user_by_email(current_user.email)
    user_data = user.__dict__
    user_data = reset_quota_if_needed(user_data)
    limit = get_plan_limit(user_data['plan'])
    remaining = limit - user_data['requests_used']
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT content, is_user, created_at FROM messages WHERE user_id = ? ORDER BY created_at ASC", (user.id,))
    messages = c.fetchall()
    c.execute("SELECT id, email, plan, requests_used FROM users")
    users = c.fetchall()
    c.execute(
        "SELECT u.email, m.content, m.is_user, m.created_at FROM messages m JOIN users u ON m.user_id = u.id ORDER BY m.created_at DESC LIMIT 20")
    last_messages = c.fetchall()
    c.execute("SELECT COUNT(*) FROM messages")
    total_messages = c.fetchone()[0]
    conn.close()
    formatted_messages = []
    for msg in messages:
        formatted_messages.append({
            'content': msg[0],
            'is_user': bool(msg[1]),
            'created_at': msg[2][:16] if msg[2] else ''
        })
    return render_template_string(HTML,
                                  plan=user_data['plan'],
                                  remaining=remaining,
                                  total_limit=limit,
                                  messages=formatted_messages,
                                  users=users,
                                  last_messages=last_messages,
                                  total_messages=total_messages,
                                  request=request,
                                  admin_email=ADMIN_EMAIL)


# ============================================
# ROUTE ASK (OLLAMA + MISTRAL - GRATUIT)
# ============================================

@app.route('/ask', methods=['POST'])
@login_required
def ask():
    user = get_user_by_email(current_user.email)
    user_data = user.__dict__
    user_data = reset_quota_if_needed(user_data)
    limit = get_plan_limit(user_data['plan'])
    remaining = limit - user_data['requests_used']

    if remaining <= 0:
        return jsonify({'error': f'Quota atteint ({limit})'}), 429

    data = request.get_json()
    prompt = data.get('prompt', '').strip()

    if not prompt:
        return jsonify({'error': 'Message vide'}), 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, content, is_user) VALUES (?, ?, 1)", (user.id, prompt))
    conn.commit()

    try:
        print(f"📩 Question : {prompt}")

        # Différenciation selon le plan
        plan = user_data['plan']
        if plan == 'business':
            max_tokens = 600
            temp = 0.4
            system = "Tu es un expert de niveau Sénior. Réponds de manière très complète, structurée et professionnelle."
        elif plan == 'pro':
            max_tokens = 400
            temp = 0.3
            system = "Tu es un professionnel. Réponds de manière structurée, utile et précise."
        else:  # free
            max_tokens = 200
            temp = 0.2
            system = "Tu es un assistant. Réponds de manière concise, utile et structurée."

        # Appel à Ollama avec Mistral
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": f"""{system}

RÈGLES OBLIGATOIRES :
1. Structure TA réponse avec :
   **Titre principal**
   - Point 1 avec explication claire
   - Point 2 avec explication claire
   - Point 3 avec explication claire
   **Exemple** (si pertinent)
   **Conclusion** (1 phrase)

2. Pour les cours de langue : donne des PHRASES UTILES avec traduction.

3. Pour les conseils : donne des étapes NUMÉROTÉES (1., 2., 3.).

4. Si tu ne sais pas, dis "Je ne sais pas" (n'invente JAMAIS).

5. Réponds dans la LANGUE de la question.

Question : {prompt}""",
            "stream": False,
            "options": {
                "temperature": temp,
                "num_predict": max_tokens
            }
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if response.status_code == 200:
            raw_answer = response.json().get('response', 'Pas de réponse')
            answer = clean_response(raw_answer)
        else:
            answer = "❌ L'IA ne répond pas. Vérifiez que le modèle est installé."

    except requests.exceptions.Timeout:
        answer = "⏳ L'IA met trop de temps. Essayez une question plus courte."
    except requests.exceptions.ConnectionError:
        answer = "❌ Ollama n'est pas lancé. Démarrez 'ollama serve' dans un terminal."
    except Exception as e:
        print(f"❌ ERREUR : {e}")
        answer = "❌ Erreur technique. Réessayez."

    c.execute("INSERT INTO messages (user_id, content, is_user) VALUES (?, ?, 0)", (user.id, answer))
    c.execute("UPDATE users SET requests_used = requests_used + 1 WHERE id = ?", (user.id,))
    conn.commit()
    conn.close()

    new_remaining = remaining - 1

    return jsonify({
        'answer': answer,
        'remaining': new_remaining,
        'total_limit': limit,
        'plan': user_data['plan']
    })


# ============================================
# ROUTES ADMIN
# ============================================

@app.route('/admin/change-plan', methods=['POST'])
@login_required
def admin_change_plan():
    if current_user.email != ADMIN_EMAIL:
        return jsonify({'error': 'Non autorisé'}), 401
    data = request.get_json()
    user_id = data.get('user_id')
    new_plan = data.get('plan')
    update_user_plan(user_id, new_plan)
    return jsonify({'success': True})


@app.route('/admin/reset-quota', methods=['POST'])
@login_required
def admin_reset_quota():
    if current_user.email != ADMIN_EMAIL:
        return jsonify({'error': 'Non autorisé'}), 401
    data = request.get_json()
    user_id = data.get('user_id')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET requests_used = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/admin/generate-code', methods=['POST'])
@login_required
def admin_generate_code():
    if current_user.email != ADMIN_EMAIL:
        return jsonify({'error': 'Non autorisé'}), 401
    data = request.get_json()
    plan = data.get('plan', 'pro')
    max_uses = int(data.get('max_uses', 1))
    expiry_days = int(data.get('expiry_days', 30))
    code = create_activation_code(plan, max_uses, expiry_days)
    return jsonify({'code': code})


# ============================================
# ROUTE REDEEM
# ============================================

@app.route('/redeem', methods=['POST'])
@login_required
def redeem():
    data = request.get_json()
    code = data.get('code', '').strip().upper()
    if not code:
        return jsonify({'error': 'Code vide'}), 400
    new_plan = activate_plan_with_code(current_user.id, code)
    if new_plan is None:
        return jsonify({'error': 'Code invalide'}), 400
    user = get_user_by_email(current_user.email)
    limit = get_plan_limit(user.plan)
    remaining = limit - user.requests_used
    return jsonify({
        'message': f'Passé au plan {new_plan} !',
        'plan': new_plan,
        'remaining': remaining,
        'total_limit': limit
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
