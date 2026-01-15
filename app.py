"""
Основное веб-приложение CryptoPay
"""

import os
import ssl
import cfg
import json
import base64
import asyncio
import secrets
import string
import time
import hashlib
import hmac
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import Database
from solana_wallet import UniversalSolanaWallet
from exchange_rate import get_sol_to_rub_rate, calculate_commissions, rub_to_sol, sol_to_rub_with_commissions
from qr_generator import QRCodeManager
from datetime import datetime, timedelta
from functools import wraps
from security_logger import SecurityLogger
from rate_limiter import rate_limiter, get_session_key, get_auth_code_key, get_login_key

app = Flask(__name__)
app.secret_key = cfg.SECRET_KEY
app.config['WTF_CSRF_ENABLED'] = False
app.config['WTF_CSRF_CHECK_DEFAULT'] = False
db = Database()

def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf_token(token):
    expected_token = session.get('csrf_token')
    if not expected_token or not token:
        return False
    return secrets.compare_digest(token, expected_token)

@app.before_request
def init_csrf():
    if 'user_id' in session:
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)

@app.after_request
def set_csrf_cookie(response):
    if 'user_id' in session:
        csrf_token = session.get('csrf_token')
        if csrf_token:
            response.set_cookie('X-CSRF-Token', csrf_token, httponly=False, samesite='Lax')
    return response

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Требуется авторизация'}), 401
        
        if 'session_created' in session:
            try:
                session_age = datetime.now() - datetime.fromisoformat(session['session_created'])
                if session_age > timedelta(hours=24):
                    session.clear()
                    return jsonify({'error': 'Сессия истекла'}), 401
            except:
                session.clear()
                return jsonify({'error': 'Неверная сессия'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def verify_telegram_webapp_data(telegram_init_data):
    """Верификация данных от Telegram Web App"""
    try:
        data = {}
        for part in telegram_init_data.split('&'):
            key, value = part.split('=')
            data[key] = value
        
        received_hash = data.get('hash', '')
        
        secret_key = hmac.new(
            b"WebAppData", 
            msg=cfg.TELEGRAM_BOT_TOKEN.encode(), 
            digestmod=hashlib.sha256
        ).digest()
        
        data_check_string = '\n'.join(sorted([
            f"{key}={value}" 
            for key, value in data.items() 
            if key != 'hash'
        ]))
        
        calculated_hash = hmac.new(
            secret_key, 
            msg=data_check_string.encode(), 
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return calculated_hash == received_hash
    except Exception:
        return False

@app.route('/webapp')
def webapp_main():
    """Главная страница для Telegram Web App"""
    telegram_data = request.args.get('tgWebAppData', '')
    
    if not verify_telegram_webapp_data(telegram_data):
        return "Unauthorized", 401
    
    return render_template('webapp_index.html')

@app.route('/api/webapp/auth')
def webapp_auth():
    """Авторизация через Telegram Web App"""
    try:
        telegram_data = request.args.get('tgWebAppData', '')
        
        if not verify_telegram_webapp_data(telegram_data):
            return jsonify({'error': 'Invalid data'}), 401
        
        import urllib.parse
        data_dict = {}
        for item in telegram_data.split('&'):
            key, value = item.split('=')
            data_dict[key] = urllib.parse.unquote(value)
        
        user_str = data_dict.get('user', '{}')
        import json
        user_data = json.loads(user_str)
        
        telegram_id = user_data.get('id')
        username = user_data.get('username', '')
        first_name = user_data.get('first_name', '')
        last_name = user_data.get('last_name', '')
        
        user = db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            user_id = db.create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name
            )
            
            wallet_data = UniversalSolanaWallet.generate_wallet()
            db.create_wallet(
                user_id=user_id,
                currency='SOL',
                wallet_address=wallet_data['address'],
                private_key=wallet_data.get('private_key'),
                seed_phrase=wallet_data.get('seed_phrase')
            )
            
            user = db.get_user_by_id(user_id)
        
        session.clear()
        session['user_id'] = user['id']
        session['telegram_id'] = user['telegram_id']
        session['session_created'] = datetime.now().isoformat()
        
        SecurityLogger.log_login_success()
        
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'telegram_id': user['telegram_id'],
                'username': user['username'],
                'first_name': user['first_name']
            }
        })
        
    except Exception as e:
        SecurityLogger.log_suspicious_activity(f'Webapp auth error: {str(e)}')
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/webapp/user')
def webapp_user_info():
    """Информация о пользователе для Web App"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    user = db.get_user_by_telegram_id(session['telegram_id'])
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    balance_sol = db.get_user_balance(user_id, 'SOL')
    balance_rub = sol_to_rub_with_commissions(balance_sol)
    
    wallet = db.get_user_wallet(user_id, 'SOL')
    
    return jsonify({
        'id': user['id'],
        'telegram_id': user['telegram_id'],
        'username': user['username'],
        'first_name': user['first_name'],
        'balance_sol': float(balance_sol),
        'balance_rub': float(balance_rub),
        'wallet_address': wallet['wallet_address'] if wallet else None
    })

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html', bot_username=cfg.TELEGRAM_BOT_USERNAME)

@app.route('/api/auth/generate-session', methods=['POST'])
@rate_limiter.limit(get_session_key, max_attempts=10, window_seconds=3600)
def generate_session():
    try:
        print("🔄 GENERATE SESSION CALLED")
        
        if not request.is_json:
            print("❌ Not JSON request")
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        data = request.get_json()
        print("📦 Received data:", data)
        
        if not data:
            print("❌ No data received")
            return jsonify({'error': 'No data provided'}), 400
            
        code_type = data.get('type', 'register')
        print(f"🎯 Code type: {code_type}")
        
        if code_type not in ['register', 'login']:
            print(f"❌ Invalid code type: {code_type}")
            return jsonify({'error': 'Invalid type'}), 400
        
        session_code = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        
        db.create_session_code(session_code, code_type, expires_in_minutes=10)
        
        bot_url = f"https://t.me/{cfg.TELEGRAM_BOT_USERNAME}?start={code_type}_{session_code}"
        
        print(f"✅ Generated session code: {session_code}")
        print(f"🤖 Bot URL: {bot_url}")
        
        return jsonify({
            'success': True,
            'session_code': session_code,
            'bot_url': bot_url
        })
        
    except Exception as e:
        print(f"💥 ERROR in generate_session: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500
           
@app.route('/api/auth/register', methods=['POST'])
@rate_limiter.limit(get_auth_code_key, max_attempts=5, window_seconds=300)
def auth_register():
    try:
        print("🔄 REGISTER CALLED")
        
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        data = request.get_json()
        print("📦 Register data:", data)
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        code = data.get('code', '').strip()
        print(f"🔑 Code received: {code}")
        
        if not code:
            return jsonify({'error': 'Code is required'}), 400
        
        auth_code = db.use_auth_code(code)
        print(f"🔍 Auth code from DB: {auth_code}")
        
        if not auth_code:
            return jsonify({'error': 'Invalid or expired code'}), 400
        
        if auth_code['code_type'] != 'register':
            return jsonify({'error': 'Этот код не для регистрации'}), 400
        
        existing_user = db.get_user_by_telegram_id(auth_code['telegram_id'])
        if existing_user:
            return jsonify({'error': 'Пользователь уже зарегистрирован. Пожалуйста, авторизуйтесь.'}), 400
        
        user_id = db.create_user(
            telegram_id=auth_code['telegram_id'],
            username=auth_code['username'],
            first_name=auth_code['first_name'],
            last_name=auth_code['last_name']
        )
        print(f"👤 User created with ID: {user_id}")
        
        wallet_data = UniversalSolanaWallet.generate_wallet()
        db.create_wallet(
            user_id=user_id,
            currency='SOL',
            wallet_address=wallet_data['address'],
            private_key=wallet_data.get('private_key'),
            seed_phrase=wallet_data.get('seed_phrase')
        )
        print(f"💰 Wallet created: {wallet_data['address']}")
        
        db.mark_code_as_used(code)
        
        user = db.get_user_by_id(user_id)
        
        session.clear()
        session['user_id'] = user['id']
        session['telegram_id'] = user['telegram_id']
        session['session_created'] = datetime.now().isoformat()
        
        print(f"🔐 Session created for user: {user['id']}")
        
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'telegram_id': user['telegram_id'],
                'username': user['username'],
                'first_name': user['first_name']
            }
        })
        
    except Exception as e:
        print(f"💥 ERROR in register: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500
      
@app.route('/api/auth/login', methods=['POST'])
@rate_limiter.limit(get_login_key, max_attempts=5, window_seconds=300) 
def auth_login():
    try:
        print("🔄 LOGIN CALLED")
        
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        data = request.get_json()
        print("📦 Login data:", data)
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        code = data.get('code', '').strip()
        print(f"🔑 Code received: {code}")
        
        if not code:
            return jsonify({'error': 'Code is required'}), 400
        
        auth_code = db.use_auth_code(code)
        print(f"🔍 Auth code from DB: {auth_code}")
        
        if not auth_code:
            return jsonify({'error': 'Invalid or expired code'}), 400
        
        if auth_code['code_type'] != 'login':
            return jsonify({'error': 'This code is not for login'}), 400
        
        user = db.get_user_by_telegram_id(auth_code['telegram_id'])
        if not user:
            return jsonify({'error': 'User not found. Please register first.'}), 404
        
        db.mark_code_as_used(code)
        
        session.clear()
        session['user_id'] = user['id']
        session['telegram_id'] = user['telegram_id']
        session['session_created'] = datetime.now().isoformat()
        
        print(f"🔐 Login successful for user: {user['id']}")
        
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'telegram_id': user['telegram_id'],
                'username': user['username'],
                'first_name': user['first_name']
            }
        })
        
    except Exception as e:
        print(f"💥 ERROR in login: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500
     
@app.route('/api/user/info')
@login_required
def user_info():
    user_id = session['user_id']
    user = db.get_user_by_telegram_id(session['telegram_id'])
    
    if not user:
        return jsonify({'error': 'Пользователь не найден'}), 404
    
    balance_sol = db.get_user_balance(user_id, 'SOL')
    balance_rub = sol_to_rub_with_commissions(balance_sol)
    
    wallet = db.get_user_wallet(user_id, 'SOL')
    
    transactions = db.get_user_transactions(user_id, limit=10)
    has_test_deposit = any(t.get('transaction_type') == 'test_deposit' for t in transactions)
    
    return jsonify({
        'id': user['id'],
        'telegram_id': user['telegram_id'],
        'username': user['username'],
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'balance_sol': float(balance_sol),
        'balance_rub': float(balance_rub),
        'wallet_address': wallet['wallet_address'] if wallet else None,
        'is_test_balance': has_test_deposit
    })

@app.route('/api/user/transactions')
@login_required
def user_transactions():
    """Получить историю транзакций пользователя"""
    user_id = session['user_id']
    
    transactions = db.get_user_transactions(user_id)
    
    pending_withdrawals = db.get_pending_withdrawals_for_user(user_id)
    
    for transaction in transactions:
        if (transaction.get('transaction_type') == 'withdrawal' and 
            transaction.get('status') == 'pending'):
            
            for withdrawal in pending_withdrawals:
                if (abs(transaction.get('amount', 0) + withdrawal['amount_sol']) < 0.000001 and
                    withdrawal['status'] != 'pending'):
                    
                    if withdrawal['status'] == 'rejected':
                        transaction['status'] = 'cancelled'
                    elif withdrawal['status'] == 'completed':
                        transaction['status'] = 'completed'
        
        created_at = transaction.get('created_at')
        if created_at:
            try:
                if isinstance(created_at, str):
                    cleaned_date = created_at.replace('Z', '').replace('+00:00', '').strip()
                    
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
                        try:
                            dt = datetime.strptime(cleaned_date, fmt)
                            transaction['created_at'] = dt.strftime('%d.%m.%Y %H:%M:%S')
                            break
                        except ValueError:
                            continue
                    else:
                        transaction['created_at'] = created_at
                else:
                    transaction['created_at'] = created_at.strftime('%d.%m.%Y %H:%M:%S')
                    
            except Exception as e:
                print(f"Ошибка форматирования даты {created_at}: {e}")
                transaction['created_at'] = "Дата не определена"
        else:
            transaction['created_at'] = "Дата не определена"
    
    return jsonify({'transactions': transactions})

@app.route('/api/wallet/refresh-balance', methods=['POST'])
@login_required
def refresh_balance():
    """Обновить баланс SOL"""
    try:
        user_id = session['user_id']
        user = db.get_user_by_telegram_id(session['telegram_id'])
        
        wallet = db.get_user_wallet(user_id, 'SOL')
        if wallet:
            balance = UniversalSolanaWallet.get_real_balance(wallet['wallet_address'])
            db.update_user_balance(user_id, 'SOL', balance)
        
        SecurityLogger.log_security_event('info', 'refresh_balance', 'Обновлен баланс пользователя')
        
        return jsonify({
            'success': True,
            'balance_sol': balance,
            'message': 'Баланс обновлен'
        })
    except Exception as e:
        SecurityLogger.log_suspicious_activity(f'Refresh balance error: {str(e)}')
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500
    
@app.route('/api/wallet/deposit')
@login_required
def get_deposit_address():
    """Получить адрес для депозита SOL"""
    try:
        user_id = session['user_id']
        
        wallet = db.get_user_wallet(user_id, 'SOL')
        if not wallet:
            return jsonify({'error': 'Кошелек не найден'}), 404
        
        return jsonify({
            'success': True,
            'currency': 'SOL',
            'address': wallet['wallet_address'],
            'currency_name': 'Solana'
        })
    except Exception as e:
        SecurityLogger.log_suspicious_activity(f'Get deposit address error: {str(e)}')
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/payment/scan', methods=['POST'])
@login_required
def scan_qr():
    try:
        data = request.json
        qr_code_data = data.get('qr_code_data', '')
        
        if not qr_code_data:
            return jsonify({'error': 'QR-код не распознан'}), 400
        
        user_id = session['user_id']
        user = db.get_user_by_telegram_id(session['telegram_id'])
        
        qr_info = QRCodeManager.parse_qr_data(qr_code_data)
        
        if not qr_info['valid']:
            SecurityLogger.log_suspicious_activity('Invalid QR code scanned', {'qr_data': qr_code_data[:100]})
            return jsonify({'error': 'Неверный формат QR-кода'}), 400
        
        amount_rub = qr_info['amount_rub']
        
        if amount_rub < cfg.MIN_PAYMENT_AMOUNT_RUB:
            return jsonify({
                'error': f'Минимальная сумма платежа: {cfg.MIN_PAYMENT_AMOUNT_RUB} RUB'
            }), 400
        
        if amount_rub > cfg.MAX_PAYMENT_AMOUNT_RUB:
            return jsonify({
                'error': f'Максимальная сумма платежа: {cfg.MAX_PAYMENT_AMOUNT_RUB} RUB'
            }), 400
        
        SecurityLogger.log_security_event('info', 'qr_scan_success', 'QR-код успешно распознан', {'amount_rub': amount_rub})
        
        return jsonify({
            'success': True,
            'amount_rub': amount_rub,
            'description': qr_info['description'],
            'qr_data': qr_code_data,
            'message': 'QR-код успешно распознан'
        })
        
    except Exception as e:
        SecurityLogger.log_suspicious_activity(f'QR scan error: {str(e)}')
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500
    
@app.route('/api/payment/process', methods=['POST'])
@login_required
def process_payment():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        amount_rub_str = data.get('amount_rub', '0')
        try:
            amount_rub = float(amount_rub_str)
            if amount_rub <= 0:
                return jsonify({'error': 'Сумма должна быть больше нуля'}), 400
            if amount_rub > 1000000:
                return jsonify({'error': 'Сумма слишком большая'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Неверный формат суммы'}), 400
        
        qr_code_data = data.get('qr_code_data', '')
        
        if amount_rub < cfg.MIN_PAYMENT_AMOUNT_RUB or amount_rub > cfg.MAX_PAYMENT_AMOUNT_RUB:
            return jsonify({'error': f'Сумма должна быть от {cfg.MIN_PAYMENT_AMOUNT_RUB} до {cfg.MAX_PAYMENT_AMOUNT_RUB} RUB'}), 400
        
        user_id = session['user_id']
        user = db.get_user_by_telegram_id(session['telegram_id'])
        
        exchange_rate = get_sol_to_rub_rate()
        amount_sol_without_commission = amount_rub / exchange_rate
        worker_earnings_sol = amount_sol_without_commission * 1.05
        admin_commission_sol = amount_sol_without_commission * 0.05
        total_user_payment_sol = amount_sol_without_commission * 1.10
        
        wallet = db.get_user_wallet(user_id, 'SOL')
        if not wallet or not wallet.get('private_key'):
            return jsonify({'error': 'Кошелек пользователя не найден'}), 400
        
        real_balance = UniversalSolanaWallet.get_real_balance(wallet['wallet_address'])
        required_balance = total_user_payment_sol + 0.0001
        
        if real_balance < required_balance:
            return jsonify({
                'error': 'Недостаточно SOL на кошельке'
            }), 400

        if admin_commission_sol < 0.00001 or worker_earnings_sol < 0.00001:
            return jsonify({
                'error': 'Сумма для транзакции слишком мала'
            }), 400

        frozen_balance = total_user_payment_sol
        if not db.freeze_user_balance_atomic(user_id, 'SOL', frozen_balance, real_balance):
            return jsonify({'error': 'Недостаточно средств или произошла ошибка'}), 400
        
        transaction_id = db.create_transaction(
            user_id=user_id,
            transaction_type='payment',
            currency='SOL',
            amount=-total_user_payment_sol,
            amount_rub=-amount_rub,
            exchange_rate=exchange_rate,
            qr_code_data=qr_code_data,
            status='pending'
        )
        
        qr_result = QRCodeManager.generate_payment_qr(amount_rub, "Оплата покупки")
        
        user_balances = {
            'SOL': real_balance - frozen_balance,
            'RUB': sol_to_rub_with_commissions(real_balance - frozen_balance)
        }
        
        user_info = json.dumps({
            'user_id': user['id'],
            'telegram_id': user['telegram_id'],
            'username': user['username'],
            'first_name': user['first_name'],
            'wallet_address': wallet['wallet_address'],
            'balances': user_balances,
            'real_transaction': True,
            'frozen_amount_sol': frozen_balance,
            'worker_earnings_sol': worker_earnings_sol,
            'admin_commission_sol': admin_commission_sol
        })
        
        db.add_to_payment_queue(
            transaction_id=transaction_id,
            qr_code_data=qr_code_data,
            qr_code_image=qr_result['qr_image'] if qr_result['success'] else '',
            user_info=user_info,
            amount_rub=amount_rub,
            worker_earnings_rub=worker_earnings_sol * exchange_rate
        )
        
        SecurityLogger.log_payment_event(transaction_id, 'created', amount_rub)
        
        try:
            from bot_notifications import send_payment_notification_sync
            
            print(f"📤 Sending payment notification for transaction #{transaction_id}")
            
            sent_count = send_payment_notification_sync(
                transaction_id=transaction_id,
                qr_code_data=qr_code_data,
                qr_code_image=qr_result['qr_image'] if qr_result['success'] else '',
                user_info=user_info,
                amount_rub=amount_rub,
                worker_earnings_sol=worker_earnings_sol,
                frozen_amount_sol=frozen_balance
            )
            
            if sent_count > 0:
                print(f"✅ Payment notification sent successfully to {sent_count} recipients")
            else:
                print(f"⚠️ Payment notification failed to send to any recipient")
            
        except Exception as e:
            print(f"❌ Error sending payment notification: {e}")
            SecurityLogger.log_suspicious_activity(f'Payment notification error: {str(e)}')
        
        return jsonify({
            'success': True,
            'transaction_id': transaction_id,
            'amount_rub': amount_rub,
            'amount_sol': total_user_payment_sol,
            'worker_earnings_sol': worker_earnings_sol,
            'admin_commission_sol': admin_commission_sol,
            'frozen_balance': real_balance - frozen_balance,
            'status': 'pending',
            'message': 'Средства заморожены. Ожидайте подтверждения оплаты воркером.'
        })
    except Exception as e:
        SecurityLogger.log_suspicious_activity(f'Process payment error: {str(e)}')
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500
            
@app.errorhandler(Exception)
def handle_exception(e):
    """Глобальный обработчик исключений"""
    SecurityLogger.log_suspicious_activity(f'Unhandled exception: {str(e)}')
    
    return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/withdrawal/request', methods=['POST'])
@login_required
def withdrawal_request():
    """Создание заявки на вывод"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        amount_sol_str = data.get('amount_sol', '0')
        wallet_address = data.get('wallet_address', '').strip()
        
        try:
            amount_sol = float(amount_sol_str)
            if amount_sol <= 0:
                return jsonify({'error': 'Сумма должна быть больше нуля'}), 400
            if amount_sol > 1000000:
                return jsonify({'error': 'Сумма слишком большая'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Неверный формат суммы'}), 400
        
        if not wallet_address:
            return jsonify({'error': 'Адрес кошелька обязателен'}), 400
        
        from solana_wallet import UniversalSolanaWallet
        if not UniversalSolanaWallet.validate_wallet_address(wallet_address):
            SecurityLogger.log_suspicious_activity('Invalid wallet address provided', {'address': wallet_address})
            return jsonify({'error': 'Неверный адрес кошелька Solana'}), 400
        
        user_id = session['user_id']
        user = db.get_user_by_telegram_id(session['telegram_id'])
        
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        wallet = db.get_user_wallet(user_id, 'SOL')
        if not wallet:
            return jsonify({'error': 'Кошелек не найден'}), 400
        
        available_balance = db.get_available_balance(user_id, 'SOL')
        
        if available_balance < amount_sol:
            return jsonify({
                'error': f'Недостаточно SOL на кошельке. Доступно: {available_balance:.6f} SOL, запрошено: {amount_sol:.6f} SOL'
            }), 400
        
        frozen_balance = amount_sol
        if not db.freeze_user_balance_atomic(user_id, 'SOL', frozen_balance, available_balance):
            return jsonify({'error': 'Недостаточно средств или произошла ошибка при заморозке баланса'}), 400
        
        withdrawal_id = db.create_withdrawal_request(user_id, amount_sol, wallet_address, 'balance')
        
        exchange_rate = get_sol_to_rub_rate()
        amount_rub = amount_sol * exchange_rate
        
        transaction_id = db.create_transaction(
            user_id=user_id,
            transaction_type='withdrawal',
            currency='SOL',
            amount=-amount_sol,
            amount_rub=-amount_rub,
            exchange_rate=exchange_rate,
            status='in_progress'
        )
        
        try:
            print(f"📤 Sending withdrawal notification to admins: withdrawal_id={withdrawal_id}")
            
            from bot_notifications import send_withdrawal_notification_sync
            
            sent_count = send_withdrawal_notification_sync(
                withdrawal_id=withdrawal_id,
                user_id=user['id'],
                user_name=user.get('first_name', ''),
                user_username=user.get('username', ''),
                user_wallet=wallet['wallet_address'],
                to_wallet=wallet_address,
                amount_sol=amount_sol,
                amount_rub=amount_rub,
                transaction_id=transaction_id
            )
            
            if sent_count > 0:
                print(f"✅ Withdrawal notification sent successfully to {sent_count} admins")
            else:
                print(f"⚠️ Withdrawal notification failed to send to any admin")
            
        except Exception as e:
            print(f"❌ Error sending withdrawal notification: {e}")
            SecurityLogger.log_suspicious_activity(f'Withdrawal notification error: {str(e)}')
        
        SecurityLogger.log_withdrawal_event(withdrawal_id, 'pending', amount_sol)
        
        return jsonify({
            'success': True,
            'withdrawal_id': withdrawal_id,
            'transaction_id': transaction_id,
            'amount_sol': amount_sol,
            'amount_rub': amount_rub,
            'wallet_address': wallet_address,
            'frozen_balance': available_balance - frozen_balance,
            'available_balance': available_balance - frozen_balance,
            'status': 'in_progress',
            'message': 'Заявка на вывод создана. Ожидайте подтверждения администратора.'
        })
        
    except Exception as e:
        error_msg = f'Withdrawal request error: {str(e)}'
        print(f"💥 {error_msg}")
        SecurityLogger.log_suspicious_activity(error_msg)
        
        try:
            user_id = session.get('user_id')
            if user_id:
                db.unfreeze_user_balance(user_id, 'SOL')
        except Exception as rollback_error:
            print(f"⚠️ Error unfreezing balance: {rollback_error}")
        
        return jsonify({'error': 'Внутренняя ошибка сервера при создании заявки на вывод'}), 500
               
def send_withdrawal_to_admins_sync(withdrawal_id, user_id, user_name, user_username, user_wallet, to_wallet, amount_sol, amount_rub, transaction_id):
    """Синхронная отправка уведомления админам"""
    try:
        import asyncio
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(send_withdrawal_to_admins_async(
                withdrawal_id, user_id, user_name, user_username, 
                user_wallet, to_wallet, amount_sol, amount_rub, transaction_id
            ))
        finally:
            loop.close()
            
        print(f"✅ Withdrawal notification completed for withdrawal #{withdrawal_id}")
            
    except Exception as e:
        print(f"❌ Error in send_withdrawal_to_admins_sync: {e}")
        import traceback
        traceback.print_exc()

async def send_withdrawal_to_admins_async(withdrawal_id, user_id, user_name, user_username, user_wallet, to_wallet, amount_sol, amount_rub, transaction_id):
    """Асинхронная отправка уведомления админам"""
    try:
        from bot import bot
        
        message_text = f"""
💸 *НОВАЯ ЗАЯВКА НА ВЫВОД* #{withdrawal_id}

👤 *Пользователь:* {user_name} (@{user_username})
💰 *Сумма:* {amount_sol:.6f} SOL ({amount_rub:.0f} ₽)

🏦 *Кошелек пользователя:* 
`{user_wallet}`

🎯 *Кошелек получателя:* 
`{to_wallet}`

📊 *Данные:*
• ID пользователя: {user_id}
• ID транзакции: {transaction_id}
• ID заявки: {withdrawal_id}
        """
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить вывод",
                    callback_data=f"admin_approve_withdrawal_{withdrawal_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", 
                    callback_data=f"admin_reject_withdrawal_{withdrawal_id}"
                )
            ]
        ])
        
        sent_count = 0
        for admin_id in cfg.ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=message_text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                sent_count += 1
                print(f"✅ Withdrawal notification sent to admin {admin_id}")
            except Exception as e:
                print(f"❌ Error sending to admin {admin_id}: {e}")
                
        print(f"📤 Sent {sent_count}/{len(cfg.ADMIN_IDS)} withdrawal notifications")
                
    except Exception as e:
        print(f"❌ Error in send_withdrawal_to_admins_async: {e}")
        import traceback
        traceback.print_exc()

@app.route('/api/payment/status/<int:transaction_id>')
@login_required
def payment_status(transaction_id):
    """Получить статус платежа"""
    transaction = db.get_transaction(transaction_id)
    
    if not transaction:
        return jsonify({'error': 'Транзакция не найдена'}), 404
    
    if transaction['user_id'] != session['user_id']:
        SecurityLogger.log_suspicious_activity('Unauthorized payment status access', {'transaction_id': transaction_id})
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    return jsonify({
        'transaction_id': transaction['id'],
        'status': transaction['status'],
        'amount_rub': transaction['amount_rub'],
        'currency': transaction['currency'],
        'error_message': transaction['error_message'],
        'created_at': transaction['created_at']
    })

@app.route('/api/exchange/rates')
def exchange_rates():
    """Получить актуальные курсы обмена"""
    rate = get_sol_to_rub_rate()
    return jsonify({
        'SOL': rate,
        'commission_markup': cfg.COMMISSION_MARKUP
    })

@app.route('/api/logout', methods=['POST'])
def logout():
    """Выход из системы"""
    SecurityLogger.log_security_event('info', 'logout', 'Пользователь вышел из системы')
    session.clear()
    return jsonify({'success': True})

def check_ssl_files():
    """Проверяет наличие SSL файлов"""
    cert_path = 'ssl/localhost.crt'
    key_path = 'ssl/localhost.key'
    
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print("❌ SSL файлы не найдены! Создайте их командой: python create_ssl.py")
        return False
    return True

@app.route('/api/home/text')
def home_text():
    """Получить текст для главной страницы"""
    try:
        home_text = db.get_setting('home_page_text')
        if not home_text:
            home_text = "Добро пожаловать в CryptoPay! Пополняйте баланс Solana и оплачивайте покупки по QR-коду."
        
        return jsonify({
            'success': True,
            'text': home_text
        })
    except Exception as e:
        return jsonify({
            'success': True,
            'text': "Добро пожаловать в CryptoPay! Пополняйте баланс Solana и оплачивайте покупки по QR-коду."
        })

@app.route('/api/test-deposit', methods=['POST'])
@login_required
def test_deposit():
    """Тестовое пополнение баланса (только для devnet)"""
    try:
        if cfg.IS_MAINNET:
            return jsonify({'error': 'Тестовое пополнение недоступно в mainnet'}), 400
        
        user_id = session['user_id']
        
        current_balance = db.get_user_balance(user_id, 'SOL')
        new_balance = current_balance + 2.0
        db.update_user_balance(user_id, 'SOL', new_balance)
        
        db.create_transaction(
            user_id=user_id,
            transaction_type='test_deposit',
            currency='SOL',
            amount=2.0,
            amount_rub=2.0 * get_sol_to_rub_rate(),
            exchange_rate=get_sol_to_rub_rate(),
            status='completed'
        )
        
        return jsonify({
            'success': True,
            'amount': 2.0,
            'new_balance': new_balance,
            'message': 'Тестовые SOL добавлены на баланс'
        })
        
    except Exception as e:
        SecurityLogger.log_suspicious_activity(f'Test deposit error: {str(e)}')
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500
    
@app.route('/api/health')
def health_check():
    """Проверка статуса сервера"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'service': 'CryptoPay API'
    })

@app.errorhandler(404)
def not_found(error):
    """Обработчик для 404 ошибок"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return redirect(url_for('index'))

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Проверить статус авторизации"""
    if 'user_id' in session:
        user = db.get_user_by_id(session['user_id'])
        if user:
            return jsonify({
                'authenticated': True,
                'user': {
                    'id': user['id'],
                    'telegram_id': user['telegram_id'],
                    'username': user['username'],
                    'first_name': user['first_name']
                }
            })
    
    return jsonify({'authenticated': False})

if __name__ == '__main__':
    if check_ssl_files():
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.load_cert_chain('ssl/localhost.crt', 'ssl/localhost.key')
        print(f"🚀 Запуск сервера с HTTPS на {cfg.WEB_HOST}:{cfg.WEB_PORT}")
        app.run(host=cfg.WEB_HOST, port=cfg.WEB_PORT, ssl_context=context, debug=cfg.DEBUG)
    else:
        print("⚠️  Запуск без HTTPS")
        app.run(host=cfg.WEB_HOST, port=cfg.WEB_PORT, debug=cfg.DEBUG)