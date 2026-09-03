from flask import Flask, request, jsonify, render_template_string, redirect, url_for, flash
import secrets
import requests
import sqlite3
import datetime
import os
import bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))

DB_NAME = "saas.db"

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ============================================
# MODÈLE UTILISATEUR
# ============================================
class User(UserMixin):
    def __init__(self, id, email, plan, requests_used, month_year, password_hash):
        self.id = id
        self.email = email
        self.plan = plan
        self.requests_used = requests_used
        self.month_year = month_year
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, email, plan, requests_used, month_year, password_hash FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2], user[3], user[4], user[5])
    return None

def get_user_by_email(email):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, email, plan, requests_used, month_year, password_hash FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2], user[3], user[4], user[5])
    return None

def create_user(email, password, plan='free'):
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user_id = secrets.token_urlsafe(16)
    current_month = datetime.datetime.now().strftime("%m-%Y")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO users (id, email, plan, requests_used, month_year, password_hash) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, email, plan, 0, current_month, password_hash))
    conn.commit()
    conn.close()
    return user_id

# ============================================
# BASE DE DONNÉES
# ============================================
def init_db():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"🗑️ Ancienne base {DB_NAME} supprimée")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        plan TEXT DEFAULT 'free',
        requests_used INTEGER DEFAULT 0,
        month_year TEXT DEFAULT ''
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
    print("✅ Base de données créée proprement")

init_db()

# ============================================
# FONCTIONS UTILITAIRES
# ============================================
def get_plan_limit(plan):
    limits = {'free': 20, 'pro': 200, 'business': 1000}
    return limits.get(plan, 20)

def increment_request(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET requests_used = requests_used + 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

def reset_quota_if_needed(user_data):
    current_month = datetime.datetime.now().strftime("%m-%Y")
    if user_data['month_year'] != current_month:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE users SET requests_used = 0, month_year = ? WHERE id = ?",
                  (current_month, user_data['id']))
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
    c.execute('''INSERT INTO activation_codes (code, plan, max_uses, expiry_date)
                 VALUES (?, ?, ?, ?)''', (code, plan, max_uses, expiry_date.isoformat()))
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

# ============================================
# HTML COMPLET (avec formulaires d'auth)
# ============================================
HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Mon SaaS IA</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); min-height:100vh; display:flex; justify-content:center; align-items:center; padding:20px; }
        .container { background:rgba(255,255,255,0.05); backdrop-filter:blur(20px); border-radius:30px; padding:30px; max-width:700px; width:100%; border:1px solid rgba(255,255,255,0.1); box-shadow:0 25px 50px -12px rgba(0,0,0,0.5); }
        h1 { color:#fff; font-size:2rem; margin-bottom:10px; }
        .subtitle { color:rgba(255,255,255,0.5); margin-bottom:20px; }
        .quota { display:flex; gap:15px; flex-wrap:wrap; margin-bottom:20px; }
        .badge { background:rgba(255,255,255,0.08); padding:8px 18px; border-radius:50px; color:#fff; border:1px solid rgba(255,255,255,0.06); }
        .badge strong { color:#a78bfa; }
        .chat-box { background:rgba(255,255,255,0.04); border-radius:20px; padding:20px; min-height:300px; border:1px solid rgba(255,255,255,0.06); }
        #messages { max-height:300px; overflow-y:auto; margin-bottom:15px; }
        .message { padding:12px 18px; border-radius:16px; margin-bottom:12px; max-width:85%; word-wrap:break-word; }
        .message.bot { background:rgba(255,255,255,0.08); color:#e5e7eb; border:1px solid rgba(255,255,255,0.06); }
        .message.user { background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; margin-left:auto; text-align:right; }
        .input-area { display:flex; gap:10px; margin-top:10px; }
        .input-area input { flex:1; padding:14px 20px; border:1px solid rgba(255,255,255,0.1); border-radius:50px; background:rgba(255,255,255,0.05); color:#fff; outline:none; }
        .input-area input::placeholder { color:rgba(255,255,255,0.3); }
        .input-area button { padding:14px 28px; border:none; border-radius:50px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; font-weight:600; cursor:pointer; transition:0.3s; }
        .input-area button:disabled { opacity:0.5; }
        .spinner { display:inline-block; width:18px; height:18px; border:2px solid rgba(255,255,255,0.1); border-top-color:#fff; border-radius:50%; animation:spin 0.6s linear infinite; }
        @keyframes spin { to { transform:rotate(360deg); } }
        .error { color:#f87171; margin-top:10px; text-align:center; }
        .footer { margin-top:20px; text-align:center; border-top:1px solid rgba(255,255,255,0.05); padding-top:15px; }
        .btn { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.08); color:#fff; padding:8px 20px; border-radius:50px; cursor:pointer; font-size:0.85rem; margin:5px; display:inline-block; text-decoration:none; }
        .btn-primary { background:#667eea; color:#fff; border:none; }
        .btn-danger { background:#ef4444; color:#fff; border:none; }
        .section { margin-top:20px; padding-top:15px; border-top:1px solid rgba(255,255,255,0.05); }
        .alert { padding:10px; border-radius:10px; margin-bottom:10px; }
        .alert-success { background:rgba(16,185,129,0.2); color:#10b981; }
        .alert-danger { background:rgba(239,68,68,0.2); color:#f87171; }
        .alert-warning { background:rgba(251,191,36,0.2); color:#fbbf24; }
        .hidden { display:none; }
        table { width:100%; color:white; border-collapse:collapse; margin:10px 0; }
        th, td { padding:8px; border:1px solid rgba(255,255,255,0.1); text-align:left; }
        th { background:rgba(255,255,255,0.05); }
        .admin-form input, .admin-form select { padding:10px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; margin:5px; }
        .admin-form button { background:#10b981; border:none; color:#fff; padding:10px 20px; border-radius:50px; cursor:pointer; }
        .auth-form input { width:100%; padding:14px 20px; margin-bottom:12px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff; font-size:1rem; outline:none; }
        .auth-form input::placeholder { color:rgba(255,255,255,0.3); }
        .auth-form button { width:100%; padding:14px; border:none; border-radius:50px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:#fff; font-weight:600; font-size:1rem; cursor:pointer; transition:0.3s; }
        .auth-form button:hover { transform:scale(1.02); }
        .auth-links { text-align:center; margin-top:15px; color:rgba(255,255,255,0.6); }
        .auth-links a { color:#a78bfa; text-decoration:none; }
    </style>
</head>
<body>
<div class="container">
    <h1>🧠 Mon SaaS IA</h1>
    <div class="subtitle">Assistant e-commerce 100% local</div>

    <!-- =========================================== -->
    <!-- AUTHENTIFICATION                            -->
    <!-- =========================================== -->
    {% if current_user.is_authenticated %}
        <!-- CONNECTÉ -->
        <div class="quota">
            <span class="badge">📋 Plan : <strong id="planDisplay">{{ plan }}</strong></span>
            <span class="badge">⚡ Requêtes : <strong id="quotaDisplay">{{ remaining }}/{{ total_limit }}</strong></span>
            <span class="badge">👤 {{ current_user.email }}</span>
            <a href="{{ url_for('logout') }}" class="btn btn-danger" style="padding:4px 12px;">Déconnexion</a>
        </div>
        {% if current_user.email == 'admin@monsaas.com' %}
            <div style="margin-bottom:10px;">
                <a href="#" onclick="toggleAdmin()" class="btn btn-primary">🛠️ Admin</a>
            </div>
        {% endif %}
    {% else %}
        <!-- NON CONNECTÉ : on affiche soit login, soit register, soit les boutons -->
        {% if request.path == '/login' %}
            <!-- Formulaire de connexion -->
            <h2 style="color:white; margin-bottom:15px;">🔐 Connexion</h2>
            <form method="POST" class="auth-form">
                <input type="email" name="email" placeholder="Email" required>
                <input type="password" name="password" placeholder="Mot de passe" required>
                <button type="submit">Se connecter</button>
            </form>
            <div class="auth-links">
                Pas encore de compte ? <a href="{{ url_for('register') }}">S'inscrire</a>
            </div>
        {% elif request.path == '/register' %}
            <!-- Formulaire d'inscription -->
            <h2 style="color:white; margin-bottom:15px;">📝 Inscription</h2>
            <form method="POST" class="auth-form">
                <input type="email" name="email" placeholder="Email" required>
                <input type="password" name="password" placeholder="Mot de passe" required>
                <input type="password" name="confirm_password" placeholder="Confirmer le mot de passe" required>
                <button type="submit">Créer mon compte</button>
            </form>
            <div class="auth-links">
                Déjà un compte ? <a href="{{ url_for('login') }}">Se connecter</a>
            </div>
        {% else %}
            <!-- Page d'accueil (boutons) -->
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:15px;">
                <a href="{{ url_for('login') }}" class="btn btn-primary">🔐 Connexion</a>
                <a href="{{ url_for('register') }}" class="btn">📝 Inscription</a>
            </div>
        {% endif %}
    {% endif %}

    <!-- Messages flash -->
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
            <div class="alert alert-{{ category }}">{{ message }}</div>
        {% endfor %}
    {% endwith %}

    <!-- =========================================== -->
    <!-- CHAT + ADMIN (seulement si connecté)       -->
    <!-- =========================================== -->
    {% if current_user.is_authenticated %}
        <div class="chat-box">
            <div id="messages">
                <div class="message bot">👋 Bonjour ! Posez-moi une question sur votre activité.</div>
            </div>
            <div class="input-area">
                <input type="text" id="userPrompt" placeholder="Ex: Comment lancer ma boutique ?" autofocus>
                <button id="sendBtn">Envoyer</button>
            </div>
            <div id="errorMessage" class="error"></div>
        </div>

        <div class="section">
            <h3 style="color:white;">🎁 Code d'activation</h3>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
                <input type="text" id="redeemCode" placeholder="Code..." style="flex:1; padding:10px; border-radius:50px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#fff;">
                <button onclick="redeemCode()" style="background:#10b981; border:none; color:#fff; padding:10px 20px; border-radius:50px; cursor:pointer;">Activer</button>
            </div>
            <div id="redeemMessage" style="color:rgba(255,255,255,0.6); margin-top:8px;"></div>
        </div>

        <!-- Admin Panel (visible uniquement pour admin) -->
        {% if current_user.email == 'admin@monsaas.com' %}
        <div id="adminPanel" class="section" style="border-top:2px solid #667eea;">
            <h3 style="color:#a78bfa;">🛠️ Administration</h3>
            <h4 style="color:white;">Utilisateurs</h4>
            <table>
                <tr><th>Email</th><th>Plan</th><th>Requêtes</th><th>Mois</th></tr>
                {% for u in users %}
                <tr><td>{{ u[1] }}</td><td>{{ u[2] }}</td><td>{{ u[3] }}</td><td>{{ u[4] }}</td></tr>
                {% endfor %}
            </table>
            <h4 style="color:white;">Codes d'activation</h4>
            <table>
                <tr><th>Code</th><th>Plan</th><th>Utilisé</th><th>Expire</th></tr>
                {% for c in codes %}
                <tr><td>{{ c[0] }}</td><td>{{ c[1] }}</td><td>{{ c[3] }}/{{ c[2] }}</td><td>{{ c[4] }}</td></tr>
                {% endfor %}
            </table>
            <h4 style="color:white;">Générer un code</h4>
            <form class="admin-form" id="codeForm">
                <select id="planSelect" style="color:white;background:rgba(255,255,255,0.05);">
                    <option value="pro">Pro</option>
                    <option value="business">Business</option>
                </select>
                <input type="number" id="maxUses" value="1" placeholder="Utilisations max" style="width:100px;">
                <input type="number" id="expiryDays" value="30" placeholder="Jours" style="width:100px;">
                <button type="submit">Générer</button>
            </form>
            <div id="codeResult" style="color:#10b981; margin-top:5px;"></div>
        </div>
        {% endif %}
    {% endif %}

    <div style="color:rgba(255,255,255,0.2); font-size:0.7rem; margin-top:15px; text-align:center;">
        🦙 Built with Llama by Meta
    </div>
</div>

<script>
    // ========== GLOBAL ==========
    let totalLimit = {{ total_limit if current_user.is_authenticated else 20 }};
    let isLoggedIn = {{ 'true' if current_user.is_authenticated else 'false' }};

    // ========== CHAT ==========
    const sendBtn = document.getElementById('sendBtn');
    const userPrompt = document.getElementById('userPrompt');

    function addMessage(text, sender) {
        const div = document.getElementById('messages');
        const msg = document.createElement('div');
        msg.className = 'message ' + sender;
        msg.textContent = text;
        div.appendChild(msg);
        div.scrollTop = div.scrollHeight;
    }

    function updateQuota(remaining, total) {
        const el = document.getElementById('quotaDisplay');
        if (el) el.textContent = remaining + '/' + total;
        totalLimit = total;
    }

    function updatePlan(plan) {
        const el = document.getElementById('planDisplay');
        if (el) el.textContent = plan;
    }

    function setLoading(loading) {
        if (!sendBtn) return;
        sendBtn.disabled = loading;
        sendBtn.innerHTML = loading ? '<span class="spinner"></span> Réflexion...' : 'Envoyer';
    }

    async function sendPrompt() {
        if (!isLoggedIn) { alert('Connectez-vous d\'abord.'); return; }
        const prompt = userPrompt.value.trim();
        if (!prompt) return;
        addMessage(prompt, 'user');
        userPrompt.value = '';
        document.getElementById('errorMessage').textContent = '';
        setLoading(true);
        try {
            const response = await fetch('/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: prompt })
            });
            const data = await response.json();
            if (response.ok) {
                addMessage(data.answer, 'bot');
                updateQuota(data.remaining, data.total_limit || totalLimit);
                updatePlan(data.plan);
            } else {
                document.getElementById('errorMessage').textContent = data.error || 'Erreur';
            }
        } catch(e) {
            document.getElementById('errorMessage').textContent = 'Erreur réseau';
        } finally {
            setLoading(false);
            userPrompt.focus();
        }
    }

    if (sendBtn) sendBtn.addEventListener('click', sendPrompt);
    if (userPrompt) userPrompt.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendPrompt(); });

    // ========== REDEEM ==========
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
                updatePlan(data.plan);
                updateQuota(data.remaining, data.total_limit);
                input.value = '';
            } else {
                msg.textContent = '❌ ' + data.error;
            }
        } catch(e) { msg.textContent = '❌ Erreur réseau'; }
    }

    // ========== ADMIN ==========
    function toggleAdmin() {
        const panel = document.getElementById('adminPanel');
        if (panel) panel.classList.toggle('hidden');
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
                document.getElementById('codeResult').textContent = 'Code généré : ' + data.code;
            };
        }
    });
</script>
</body>
</html>
"""

# ============================================
# ROUTES
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
    c.execute("SELECT id, email, plan, requests_used, month_year FROM users")
    users = c.fetchall()
    c.execute("SELECT code, plan, max_uses, used_count, expiry_date FROM activation_codes")
    codes = c.fetchall()
    conn.close()

    return render_template_string(HTML,
                                  plan=user_data['plan'],
                                  remaining=remaining,
                                  total_limit=limit,
                                  users=users,
                                  codes=codes,
                                  request=request)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        if password != confirm:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template_string(HTML, request=request)
        if get_user_by_email(email):
            flash('Email déjà utilisé', 'danger')
            return render_template_string(HTML, request=request)
        create_user(email, password)
        flash('Compte créé ! Connectez-vous.', 'success')
        return redirect(url_for('login'))
    return render_template_string(HTML, request=request)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = get_user_by_email(email)
        if user and bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            login_user(user)
            flash('Connecté avec succès', 'success')
            return redirect(url_for('index'))
        else:
            flash('Email ou mot de passe incorrect', 'danger')
    return render_template_string(HTML, request=request)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnecté', 'info')
    return redirect(url_for('login'))

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
    prompt = data.get('prompt', '')
    if not prompt:
        return jsonify({'error': 'Prompt vide'}), 400
    try:
        print(f"📩 Question reçue : {prompt}")
        payload = {
            "model": "llama3.2:3b",
            "prompt": f"Tu es un expert en e-commerce. Réponds en français : {prompt}",
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 200}
        }
        response = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=30)
        if response.status_code != 200:
            return jsonify({'error': f'Erreur IA HTTP {response.status_code}'}), 500
        answer = response.json().get('response', 'Pas de réponse')
        increment_request(user_data['id'])
        new_remaining = remaining - 1
        return jsonify({
            'answer': answer,
            'remaining': new_remaining,
            'plan': user_data['plan'],
            'total_limit': limit
        })
    except Exception as e:
        print(f"❌ ERREUR : {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/generate-code', methods=['POST'])
@login_required
def generate_code():
    if current_user.email != 'admin@monsaas.com':
        return jsonify({'error': 'Non autorisé'}), 401
    data = request.get_json()
    plan = data.get('plan', 'pro')
    max_uses = int(data.get('max_uses', 1))
    expiry_days = int(data.get('expiry_days', 30))
    code = create_activation_code(plan, max_uses, expiry_days)
    return jsonify({'code': code})

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
        'message': f'Passé au plan {new_plan}',
        'plan': new_plan,
        'remaining': remaining,
        'total_limit': limit
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
