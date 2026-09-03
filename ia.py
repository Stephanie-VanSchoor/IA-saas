from flask import Flask, request, jsonify, render_template_string, session
import secrets
import requests
import sqlite3
import datetime
import os

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# ============================================
# DESIGN MODERNE + SPINNER DE CHARGEMENT
# ============================================
HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mon SaaS IA</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 30px;
            padding: 30px;
            max-width: 700px;
            width: 100%;
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        h1 {
            color: #fff;
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        h1 span {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 5px 15px;
            border-radius: 50px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .subtitle {
            color: rgba(255, 255, 255, 0.5);
            font-size: 0.9rem;
            margin-bottom: 20px;
        }
        .quota {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }
        .badge {
            background: rgba(255, 255, 255, 0.08);
            padding: 8px 18px;
            border-radius: 50px;
            color: #fff;
            font-size: 0.85rem;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .badge strong {
            color: #a78bfa;
        }
        .chat-box {
            background: rgba(255, 255, 255, 0.04);
            border-radius: 20px;
            padding: 20px;
            min-height: 350px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        #messages {
            max-height: 320px;
            overflow-y: auto;
            margin-bottom: 15px;
            padding-right: 5px;
        }
        #messages::-webkit-scrollbar {
            width: 4px;
        }
        #messages::-webkit-scrollbar-track {
            background: transparent;
        }
        #messages::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.2);
            border-radius: 10px;
        }
        .message {
            padding: 12px 18px;
            border-radius: 16px;
            margin-bottom: 12px;
            max-width: 85%;
            word-wrap: break-word;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message.bot {
            background: rgba(255, 255, 255, 0.08);
            color: #e5e7eb;
            border: 1px solid rgba(255, 255, 255, 0.06);
            align-self: flex-start;
        }
        .message.user {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            margin-left: auto;
            text-align: right;
        }
        .input-area {
            display: flex;
            gap: 10px;
            margin-top: 5px;
        }
        .input-area input {
            flex: 1;
            padding: 14px 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 50px;
            background: rgba(255, 255, 255, 0.05);
            color: #fff;
            font-size: 1rem;
            outline: none;
            transition: 0.3s;
        }
        .input-area input::placeholder {
            color: rgba(255, 255, 255, 0.3);
        }
        .input-area input:focus {
            border-color: #667eea;
            background: rgba(255, 255, 255, 0.08);
        }
        .input-area button {
            padding: 14px 28px;
            border: none;
            border-radius: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: 0.3s;
            white-space: nowrap;
        }
        .input-area button:hover {
            transform: scale(1.02);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
        }
        .input-area button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        .error {
            color: #f87171;
            margin-top: 12px;
            text-align: center;
            font-size: 0.9rem;
        }
        .spinner {
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-top-color: #fff;
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .footer {
            margin-top: 20px;
            text-align: center;
            padding-top: 15px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }
        .footer .upgrade-btn {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #fff;
            padding: 8px 20px;
            border-radius: 50px;
            cursor: pointer;
            font-size: 0.85rem;
            margin: 0 5px;
            transition: 0.3s;
        }
        .footer .upgrade-btn:hover {
            background: rgba(255, 255, 255, 0.12);
        }
        .footer .upgrade-btn.pro {
            border-color: #667eea;
            color: #a78bfa;
        }
        .footer .upgrade-btn.business {
            border-color: #f472b6;
            color: #f472b6;
        }
        .redeem-section {
            margin-top: 15px;
            display: flex;
            gap: 10px;
            justify-content: center;
            flex-wrap: wrap;
        }
        .redeem-section input {
            padding: 10px 18px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 50px;
            background: rgba(255, 255, 255, 0.05);
            color: #fff;
            outline: none;
            width: 200px;
        }
        .redeem-section input::placeholder {
            color: rgba(255, 255, 255, 0.3);
        }
        .redeem-section button {
            background: #10b981;
            border: none;
            color: #fff;
            padding: 10px 24px;
            border-radius: 50px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
        }
        .redeem-section button:hover {
            background: #059669;
        }
        #redeemMessage {
            color: rgba(255, 255, 255, 0.6);
            font-size: 0.85rem;
            margin-top: 8px;
            text-align: center;
            width: 100%;
        }
        .built {
            color: rgba(255, 255, 255, 0.2);
            font-size: 0.7rem;
            margin-top: 15px;
            text-align: center;
        }
        .built a {
            color: rgba(255, 255, 255, 0.3);
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            🧠 Mon SaaS IA
            <span>v2</span>
        </h1>
        <div class="subtitle">Assistant IA 100% local • Alimenté par Llama</div>

        <div class="quota">
            <span class="badge">📋 Plan : <strong id="planDisplay">free</strong></span>
            <span class="badge">⚡ Requêtes : <strong id="quotaDisplay">20/20</strong></span>
        </div>

        <div class="chat-box">
            <div id="messages">
                <div class="message bot">👋 Bonjour ! Posez-moi une question sur votre activité.</div>
            </div>
            <div class="input-area">
                <input type="text" id="userPrompt" placeholder="Écrivez votre question..." autofocus>
                <button id="sendBtn">Envoyer</button>
            </div>
            <div id="errorMessage" class="error"></div>
        </div>

        <div class="footer">
            <div>
                <button onclick="upgradePlan('pro')" class="upgrade-btn pro">⬆ Plan Pro (10€)</button>
                <button onclick="upgradePlan('business')" class="upgrade-btn business">⬆ Business (50€)</button>
            </div>
            <div class="redeem-section">
                <input type="text" id="redeemCode" placeholder="🎁 Code d'activation...">
                <button onclick="redeemCode()">Activer</button>
                <div id="redeemMessage"></div>
            </div>
        </div>
        <div class="built">
            🦙 Built with <a href="https://llama.meta.com" target="_blank">Llama</a> by Meta
        </div>
    </div>

    <script>
        let totalLimit = 20;
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
            document.getElementById('quotaDisplay').textContent = remaining + '/' + total;
            totalLimit = total;
        }

        function updatePlan(plan) {
            document.getElementById('planDisplay').textContent = plan;
        }

        function setLoading(loading) {
            sendBtn.disabled = loading;
            sendBtn.innerHTML = loading ? '<span class="spinner"></span> Réflexion...' : 'Envoyer';
        }

        async function sendPrompt() {
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

        sendBtn.addEventListener('click', sendPrompt);
        userPrompt.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendPrompt();
        });

        async function upgradePlan(plan) {
            try {
                const response = await fetch('/upgrade/' + plan, { method: 'POST' });
                const data = await response.json();
                if (response.ok) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert('Erreur');
                }
            } catch(e) { alert('Erreur réseau'); }
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
                    updatePlan(data.plan);
                    updateQuota(data.remaining, data.total_limit);
                    input.value = '';
                } else {
                    msg.textContent = '❌ ' + data.error;
                }
            } catch(e) { msg.textContent = '❌ Erreur réseau'; }
        }
    </script>
</body>
</html>
"""

# ============================================
# BASE DE DONNÉES (identique)
# ============================================
DB_NAME = "saas.db"

def init_db():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"🗑️ Ancienne base {DB_NAME} supprimée")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE users (
        id TEXT PRIMARY KEY,
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

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, plan, requests_used, month_year FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if not user:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        current_month = datetime.datetime.now().strftime("%m-%Y")
        c.execute("INSERT INTO users (id, plan, requests_used, month_year) VALUES (?, ?, ?, ?)",
                  (user_id, 'free', 0, current_month))
        conn.commit()
        conn.close()
        return {'id': user_id, 'plan': 'free', 'requests_used': 0, 'month_year': current_month}
    return {'id': user[0], 'plan': user[1], 'requests_used': user[2], 'month_year': user[3]}

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

init_db()

# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    if 'user_id' not in session:
        session['user_id'] = secrets.token_urlsafe(16)
    user_id = session['user_id']
    user_data = get_user(user_id)
    user_data = reset_quota_if_needed(user_data)
    limit = get_plan_limit(user_data['plan'])
    remaining = limit - user_data['requests_used']
    return render_template_string(HTML, plan=user_data['plan'], remaining=remaining, total_limit=limit)

@app.route('/ask', methods=['POST'])
def ask():
    if 'user_id' not in session:
        return jsonify({'error': 'Session invalide'}), 401
    user_id = session['user_id']
    user_data = get_user(user_id)
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

        # ============================================
        # OPTIMISATION : modèle plus rapide (phi) + réponse courte
        # ============================================
        payload = {
            "model": "llama3.2:3b",
            "prompt": f"""Tu es un expert en e-commerce et marketing digital. 
        Tu aides les entrepreneurs à lancer et développer leur boutique en ligne.
        Tu réponds en français, de manière professionnelle, concise et utile.

        Voici la question de l'utilisateur : {prompt}

        Ta réponse :""",
            "stream": False,
            "options": {
                "temperature": 0.5,
                "num_predict": 200
            }
        }

        response = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=30)
        if response.status_code != 200:
            return jsonify({'error': f'Erreur IA HTTP {response.status_code}'}), 500

        answer = response.json().get('response', 'Pas de réponse')
        print(f"✅ Réponse envoyée ({len(answer)} caractères)")

        increment_request(user_id)
        new_remaining = remaining - 1

        return jsonify({
            'answer': answer,
            'remaining': new_remaining,
            'plan': user_data['plan'],
            'total_limit': limit
        })

    except requests.exceptions.ConnectionError:
        return jsonify({'error': '❌ Ollama pas démarré (127.0.0.1:11434)'}), 503
    except Exception as e:
        print(f"❌ ERREUR : {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/upgrade/<plan>', methods=['POST'])
def upgrade(plan):
    if 'user_id' not in session:
        return jsonify({'error': 'Non autorisé'}), 401
    if plan not in ['pro', 'business']:
        return jsonify({'error': 'Plan invalide'}), 400
    user_id = session['user_id']
    update_user_plan(user_id, plan)
    return jsonify({'message': f'Passé au plan {plan}'})

@app.route('/redeem', methods=['POST'])
def redeem():
    if 'user_id' not in session:
        return jsonify({'error': 'Non autorisé'}), 401
    data = request.get_json()
    code = data.get('code', '').strip().upper()
    if not code:
        return jsonify({'error': 'Code vide'}), 400
    user_id = session['user_id']
    new_plan = activate_plan_with_code(user_id, code)
    if new_plan is None:
        return jsonify({'error': 'Code invalide'}), 400
    user_data = get_user(user_id)
    limit = get_plan_limit(user_data['plan'])
    remaining = limit - user_data['requests_used']
    return jsonify({
        'message': f'Passé au plan {new_plan}',
        'plan': new_plan,
        'remaining': remaining,
        'total_limit': limit
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

