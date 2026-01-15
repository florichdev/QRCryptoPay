import logging
import os
import cfg
from datetime import datetime
from flask import request, session
from database import Database

def setup_security_logging():
    """Настройка логирования безопасности"""
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    security_logger = logging.getLogger('security')
    security_logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(ip)s] [%(user_id)s] [%(action)s] - %(message)s'
    )
    
    file_handler = logging.FileHandler('logs/security.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    security_logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    security_logger.addHandler(console_handler)
    
    return security_logger

security_logger = setup_security_logging()

class SecurityLogger:
    @staticmethod
    def get_client_ip():
        """Получить IP клиента"""
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0]
        return request.remote_addr
    
    @staticmethod
    def get_user_info():
        """Получить информацию о пользователе"""
        user_id = session.get('user_id', 'anonymous')
        telegram_id = session.get('telegram_id', 'unknown')
        return user_id, telegram_id
    
    @staticmethod
    def log_security_event(severity, event_type, description, user_id=None, ip_address=None, user_agent=None):
        try:
            conn = Database().get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO security_logs 
                (event_type, event_description, severity, user_id, ip_address, user_agent, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (event_type, description, severity, user_id, ip_address, user_agent))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error logging security event: {e}")
    
    @staticmethod
    def log_login_success():
        SecurityLogger.log_security_event('info', 'login_success', 'Успешный вход в систему')

    @staticmethod
    def log_suspicious_activity(description, extra_data=None):
        SecurityLogger.log_security_event('warning', 'suspicious_activity', description)

    @staticmethod
    def log_payment_event(transaction_id, status, amount_rub):
        SecurityLogger.log_security_event('info', 'payment', f'Payment {transaction_id} {status}: {amount_rub} RUB')
    
    @staticmethod
    def log_login_failed(reason, username=None):
        extra = {'reason': reason}
        if username:
            extra['username'] = username
        SecurityLogger.log_security_event('warning', 'login_failed', f'Неудачная попытка входа: {reason}', extra)
    
    @staticmethod
    def log_csrf_violation():
        SecurityLogger.log_security_event('warning', 'csrf_violation', 'Нарушение CSRF защиты')
    
    @staticmethod
    def log_bruteforce_attempt(ip, action):
        SecurityLogger.log_security_event('error', 'bruteforce_attempt', 
                                        f'Обнаружена атака брутфорса с IP {ip} для действия {action}')
    
    @staticmethod
    def log_suspicious_activity(description, data=None):
        SecurityLogger.log_security_event('warning', 'suspicious_activity', 
                                        f'Подозрительная активность: {description}', data)
    
    @staticmethod
    def log_payment_event(transaction_id, action, amount=None):
        extra = {'transaction_id': transaction_id}
        if amount:
            extra['amount'] = amount
        SecurityLogger.log_security_event('info', f'payment_{action}', 
                                        f'Событие платежа: {action}', extra)
    
    @staticmethod
    def log_withdrawal_event(withdrawal_id, status, amount_sol):
        try:
            conn = Database().get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO security_logs 
                (event_type, event_description, severity, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', ('withdrawal', f'Withdrawal {withdrawal_id} {status}: {amount_sol} SOL', 'info'))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error logging withdrawal event: {e}")
    
    @staticmethod
    def log_admin_action(action, target_user=None, details=None):
        extra = {'admin_action': action}
        if target_user:
            extra['target_user'] = target_user
        if details:
            extra['details'] = details
        SecurityLogger.log_security_event('info', 'admin_action', 
                                        f'Действие администратора: {action}', extra)