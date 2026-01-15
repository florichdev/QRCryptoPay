import sqlite3
import json
import cfg
from datetime import datetime, timedelta
from typing import Optional, List, Dict

class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or cfg.DATABASE_PATH
        self.init_db()
            
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                balance REAL DEFAULT 0.0,
                frozen_balance REAL DEFAULT 0.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, currency)
            )
    ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                private_key TEXT,
                seed_phrase TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, currency)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS frozen_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, currency)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                wallet_id INTEGER,
                transaction_type TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount REAL,
                amount_rub REAL,
                exchange_rate REAL,
                commission_markup REAL,
                worker_commission REAL,
                admin_commission REAL,
                status TEXT DEFAULT 'pending',
                qr_code_data TEXT,
                worker_id INTEGER,
                admin_id INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (wallet_id) REFERENCES wallets(id),
                FOREIGN KEY (worker_id) REFERENCES users(id),
                FOREIGN KEY (admin_id) REFERENCES users(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS security_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_description TEXT NOT NULL,
                severity TEXT DEFAULT 'info',
                user_id INTEGER,
                ip_address TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_sol REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                request_type TEXT DEFAULT 'balance',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

        try:
            cursor.execute('ALTER TABLE withdrawal_requests ADD COLUMN request_type TEXT DEFAULT "balance"')
        except sqlite3.OperationalError:
            pass
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                qr_code_data TEXT NOT NULL,
                qr_code_image TEXT,
                user_info TEXT NOT NULL,
                amount_rub REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                assigned_worker_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (transaction_id) REFERENCES transactions(id),
                FOREIGN KEY (assigned_worker_id) REFERENCES users(id)
            )
        ''')
        try:
            cursor.execute('ALTER TABLE payment_queue ADD COLUMN worker_earnings_rub REAL')
        except sqlite3.OperationalError:
            pass
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auth_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                code_type TEXT NOT NULL,
                is_used BOOLEAN DEFAULT 0,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_code TEXT UNIQUE NOT NULL,
                code_type TEXT NOT NULL,
                auth_code TEXT,
                telegram_id INTEGER,
                is_used BOOLEAN DEFAULT 0,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(telegram_id, role),
                FOREIGN KEY (added_by) REFERENCES users(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                language TEXT DEFAULT 'ru',
                notifications_enabled BOOLEAN DEFAULT 1,
                auto_withdraw_enabled BOOLEAN DEFAULT 0,
                preferred_currency TEXT DEFAULT 'SOL',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                completed_payments INTEGER DEFAULT 0,
                total_commission_rub REAL DEFAULT 0.0,
                total_processed_rub REAL DEFAULT 0.0,
                last_payment_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES users(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER UNIQUE NOT NULL,
                status TEXT DEFAULT 'free',
                current_transaction_id INTEGER,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES users(id),
                FOREIGN KEY (current_transaction_id) REFERENCES transactions(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                attempts INTEGER DEFAULT 1,
                first_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(key)
            )
        ''')
        
        for admin_id in cfg.ADMIN_IDS:
            cursor.execute('''
                INSERT OR IGNORE INTO user_roles (telegram_id, role)
                VALUES (?, 'admin')
            ''', (admin_id,))
        
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value) 
            VALUES ('home_page_text', 'Добро пожаловать в CryptoPay! Пополняйте баланс Solana и оплачивайте покупки по QR-коду.')
        ''')
        
        try:
            cursor.execute('ALTER TABLE user_balances ADD COLUMN frozen_balance REAL DEFAULT 0.0')
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()
    
    def update_rate_limit(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO rate_limits (key, attempts, first_attempt, last_attempt)
                VALUES (?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    attempts = CASE 
                        WHEN datetime(last_attempt, ? || ' seconds') < CURRENT_TIMESTAMP THEN 1
                        ELSE attempts + 1 
                    END,
                    last_attempt = CURRENT_TIMESTAMP,
                    first_attempt = CASE 
                        WHEN datetime(last_attempt, ? || ' seconds') < CURRENT_TIMESTAMP THEN CURRENT_TIMESTAMP
                        ELSE first_attempt 
                    END
                WHERE key = ?
                RETURNING attempts
            ''', (key, f"-{window_seconds}", f"-{window_seconds}", key))
            
            result = cursor.fetchone()
            conn.commit()
            
            if result and result[0] > max_attempts:
                return False
            return True
            
        except Exception as e:
            conn.rollback()
            return True
        finally:
            conn.close()

    def validate_and_fix_private_key(private_key: str) -> str:
        """Проверить и исправить формат приватного ключа"""
        if not private_key:
            return private_key
        
        if len(private_key) == 64:
            try:
                bytes.fromhex(private_key)
                return private_key
            except:
                pass
        
        try:
            import base58
            decoded = base58.b58decode(private_key)
            if len(decoded) == 64:
                return private_key
        except:
            pass
        
        from solana_wallet import UniversalSolanaWallet
        new_wallet = UniversalSolanaWallet.generate_wallet()
        return new_wallet['private_key']

    def create_user(self, telegram_id: int, username: str = None, 
                   first_name: str = None, last_name: str = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (telegram_id, username, first_name, last_name))
        user_id = cursor.lastrowid
        
        cursor.execute('''
            INSERT INTO user_balances (user_id, currency, balance)
            VALUES (?, 'SOL', ?)
        ''', (user_id, 0.0))
        
        cursor.execute('''
            INSERT INTO user_profiles (user_id)
            VALUES (?)
        ''', (user_id,))
        
        conn.commit()
        conn.close()
        return user_id
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_all_workers_with_wallets(self) -> List[Dict]:
        """Получить всех воркеров с их кошельками"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                ur.telegram_id,
                u.id as user_id,
                u.username,
                u.first_name,
                u.last_name,
                w.wallet_address,
                w.private_key,
                ub.balance as current_balance
            FROM user_roles ur
            JOIN users u ON ur.telegram_id = u.telegram_id
            LEFT JOIN wallets w ON u.id = w.user_id AND w.currency = 'SOL'
            LEFT JOIN user_balances ub ON u.id = ub.user_id AND ub.currency = 'SOL'
            WHERE ur.role = "worker"
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_user_balance(self, user_id: int, currency: str) -> float:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT balance FROM user_balances 
            WHERE user_id = ? AND currency = ?
        ''', (user_id, currency))
        row = cursor.fetchone()
        conn.close()
        return float(row['balance']) if row and row['balance'] is not None else 0.0
    
    def get_available_balance(self, user_id: int, currency: str) -> float:
        """Получить доступный баланс (без замороженных средств)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT balance - frozen_balance as available_balance 
            FROM user_balances 
            WHERE user_id = ? AND currency = ?
        ''', (user_id, currency))
        row = cursor.fetchone()
        conn.close()
        return float(row['available_balance']) if row and row['available_balance'] is not None else 0.0
    
    def get_all_user_balances(self, user_id: int) -> Dict[str, float]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT currency, balance FROM user_balances 
            WHERE user_id = ?
        ''', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        balances = {}
        for row in rows:
            balances[row['currency']] = row['balance']
        return balances
    
    def update_user_balance(self, user_id: int, currency: str, balance: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_balances (user_id, currency, balance, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, currency, float(balance)))
        conn.commit()
        conn.close()
    
    def increment_user_balance(self, user_id: int, currency: str, amount: float):
        current_balance = self.get_user_balance(user_id, currency)
        new_balance = current_balance + amount
        self.update_user_balance(user_id, currency, new_balance)
        return new_balance
    
    def decrement_user_balance(self, user_id: int, currency: str, amount: float):
        current_balance = self.get_user_balance(user_id, currency)
        if current_balance < amount:
            raise ValueError("Недостаточно средств")
        new_balance = current_balance - amount
        self.update_user_balance(user_id, currency, new_balance)
        return new_balance
    
    def create_wallet(self, user_id: int, currency: str, wallet_address: str,
                    private_key: str = None, seed_phrase: str = None) -> int:
        """Создать кошелек с валидацией приватного ключа"""
        if private_key:
            from solana_wallet import UniversalSolanaWallet
            if not UniversalSolanaWallet.validate_private_key(private_key):
                print(f"⚠️  Невалидный приватный ключ для пользователя {user_id}, генерируем новый")
                new_wallet = UniversalSolanaWallet.generate_wallet()
                private_key = new_wallet['private_key']
                wallet_address = new_wallet['address']
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO wallets 
            (user_id, currency, wallet_address, private_key, seed_phrase)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, currency, wallet_address, private_key, seed_phrase))
        wallet_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return wallet_id
    
    def get_user_wallet(self, user_id: int, currency: str) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM wallets 
            WHERE user_id = ? AND currency = ?
        ''', (user_id, currency))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def create_transaction(self, user_id: int, transaction_type: str, currency: str,
                          amount: float = None, amount_rub: float = None,
                          exchange_rate: float = None, qr_code_data: str = None,
                          wallet_id: int = None, status: str = 'completed') -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions 
            (user_id, wallet_id, transaction_type, currency, amount, amount_rub, 
             exchange_rate, qr_code_data, commission_markup, worker_commission, admin_commission, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, wallet_id, transaction_type, currency, amount, amount_rub,
              exchange_rate, qr_code_data, cfg.COMMISSION_MARKUP, 
              cfg.WORKER_COMMISSION, cfg.ADMIN_COMMISSION, status))
        transaction_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return transaction_id
    
    def update_transaction_status(self, transaction_id: int, status: str,
                            worker_id: int = None, admin_id: int = None,
                            error_message: str = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE transactions 
            SET status = ?, worker_id = ?, admin_id = ?, error_message = ?, 
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, worker_id, admin_id, error_message, transaction_id))
        conn.commit()
        conn.close()

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_transaction(self, transaction_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM transactions WHERE id = ?', (transaction_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_user_transactions(self, user_id: int, limit: int = 50) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM transactions 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        transactions = []
        for row in rows:
            transaction = dict(row)
            
            if transaction.get('created_at'):
                try:
                    if isinstance(transaction['created_at'], datetime):
                        transaction['created_at'] = transaction['created_at'].isoformat()
                    elif isinstance(transaction['created_at'], str):
                        pass
                    else:
                        transaction['created_at'] = str(transaction['created_at'])
                except Exception as e:
                    print(f"Ошибка обработки даты транзакции: {e}")
                    transaction['created_at'] = datetime.now().isoformat()
            else:
                transaction['created_at'] = datetime.now().isoformat()
                
            transactions.append(transaction)
        
        return transactions
    
    def assign_worker_to_transaction(self, transaction_id: int, worker_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE transactions 
                SET worker_id = ?, status = 'in_progress'
                WHERE id = ? AND status = 'pending' AND worker_id IS NULL
            ''', (worker_id, transaction_id))
            
            success = cursor.rowcount > 0
            conn.commit()
            return success
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()
        
    def get_pending_transactions_for_admin(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.*, u.username, u.first_name 
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE t.status = 'pending' AND t.worker_id IS NULL
            ORDER BY t.created_at ASC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def create_withdrawal_request(self, user_id, amount_sol, wallet_address, request_type='balance'):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO withdrawal_requests 
            (user_id, amount_sol, wallet_address, request_type, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
        ''', (user_id, amount_sol, wallet_address, request_type))
        withdrawal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return withdrawal_id

    def get_withdrawal_request(self, withdrawal_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wr.*, u.telegram_id, u.username, u.first_name
            FROM withdrawal_requests wr
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE wr.id = ?
        ''', (withdrawal_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    
    def get_pending_withdrawals_for_user(self, user_id):
        """Получить заявки на вывод для конкретного пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM withdrawal_requests 
            WHERE user_id = ? AND status != 'completed'
            ORDER BY created_at DESC
        ''', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows] if rows else []

    def get_pending_withdrawals(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wr.*, u.telegram_id, u.username, u.first_name
            FROM withdrawal_requests wr
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE wr.status = 'pending'
            ORDER BY wr.created_at ASC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def reset_test_balance(self, user_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE user_balances SET balance = 0.0 WHERE user_id = ? AND currency = "SOL"', (user_id,))
        cursor.execute('DELETE FROM transactions WHERE user_id = ? AND transaction_type = "test_deposit"', (user_id,))
        
        conn.commit()
        conn.close()
    
    def update_withdrawal_status(self, withdrawal_id, status, error_message=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if error_message:
            cursor.execute('''
                UPDATE withdrawal_requests 
                SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, error_message, withdrawal_id))
        else:
            cursor.execute('''
                UPDATE withdrawal_requests 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, withdrawal_id))
        conn.commit()
        conn.close()
    
    def add_to_payment_queue(self, transaction_id, qr_code_data, qr_code_image, user_info, amount_rub, worker_earnings_rub=None):
        """Добавить платеж в очередь с учетом заработка воркера"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if worker_earnings_rub is None:
            worker_earnings_rub = amount_rub * 0.03
        
        cursor.execute('''
            INSERT INTO payment_queue 
            (transaction_id, qr_code_data, qr_code_image, user_info, amount_rub, worker_earnings_rub)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (transaction_id, qr_code_data, qr_code_image, user_info, amount_rub, worker_earnings_rub))
        queue_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return queue_id
    
    def freeze_user_balance(self, user_id, currency, amount):
        """Заморозить средства на балансе пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO frozen_balances 
            (user_id, currency, amount, created_at) 
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, currency, amount))
        
        conn.commit()
        conn.close()

    def unfreeze_user_balance(self, user_id, currency):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT frozen_balance FROM user_balances 
                WHERE user_id = ? AND currency = ?
            ''', (user_id, currency))
            
            result = cursor.fetchone()
            if result:
                frozen_amount = result[0]
                
                cursor.execute('''
                    UPDATE user_balances 
                    SET balance = balance + ?, frozen_balance = 0
                    WHERE user_id = ? AND currency = ?
                ''', (frozen_amount, user_id, currency))
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"Error unfreezing balance: {e}")
            return False
        finally:
            conn.close()

    def get_frozen_balance(self, user_id, currency):
        """Получить сумму замороженных средств"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT amount FROM frozen_balances 
            WHERE user_id = ? AND currency = ?
        ''', (user_id, currency))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else 0.0

    def get_payment_queue_by_transaction(self, transaction_id):
        """Получить запись из очереди платежей по ID транзакции"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM payment_queue 
            WHERE transaction_id = ?
        ''', (transaction_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return dict(result) if result else None

    def get_pending_payments(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM payment_queue 
            WHERE status = 'pending' 
            ORDER BY created_at ASC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def create_auth_code(self, code: str, telegram_id: int, username: str = None,
                        first_name: str = None, last_name: str = None,
                        code_type: str = 'register', expires_in_minutes: int = 10) -> int:
        expires_at = datetime.now() + timedelta(minutes=expires_in_minutes)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO auth_codes 
            (code, telegram_id, username, first_name, last_name, code_type, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (code, telegram_id, username, first_name, last_name, code_type, expires_at))
        code_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return code_id
    
    def get_auth_code(self, code: str) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM auth_codes 
            WHERE code = ? AND is_used = 0 AND expires_at > ?
        ''', (code, datetime.now()))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def mark_code_as_used(self, code: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE auth_codes 
            SET is_used = 1
            WHERE code = ?
        ''', (code,))
        conn.commit()
        conn.close()
    
    def create_session_code(self, session_code: str, code_type: str, expires_in_minutes: int = 10) -> int:
        expires_at = datetime.now() + timedelta(minutes=expires_in_minutes)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO session_codes 
            (session_code, code_type, expires_at)
            VALUES (?, ?, ?)
        ''', (session_code, code_type, expires_at))
        code_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return code_id
    
    def get_session_code(self, session_code: str) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM session_codes 
            WHERE session_code = ? AND is_used = 0 AND expires_at > ?
        ''', (session_code, datetime.now()))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def update_session_code_with_auth(self, session_code: str, auth_code: str, telegram_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE session_codes 
            SET auth_code = ?, telegram_id = ?
            WHERE session_code = ?
        ''', (auth_code, telegram_id, session_code))
        conn.commit()
        conn.close()
    
    def mark_session_code_as_used(self, session_code: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE session_codes 
            SET is_used = 1
            WHERE session_code = ?
        ''', (session_code,))
        conn.commit()
        conn.close()
    
    def add_role(self, telegram_id: int, role: str, added_by: int = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        current_roles = self.get_user_roles(telegram_id)
        
        if role == 'admin':
            raise ValueError("Добавление администраторов запрещено. Используйте статичную конфигурацию.")

        if role in current_roles:
            raise ValueError(f"У пользователя уже есть роль '{role}'")
        
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            user_id = self.create_user(
                telegram_id=telegram_id,
                username=None,
                first_name=None,
                last_name=None
            )
        else:
            user_id = user['id']
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_roles (telegram_id, role, added_by)
            VALUES (?, ?, ?)
        ''', (telegram_id, role, added_by))
        conn.commit()
        conn.close()
    
    def remove_role(self, telegram_id: int, role: str):
        conn = self.get_connection()

        if role == 'admin':
            raise ValueError("Удаление администраторов запрещено. Используйте статичную конфигурацию.")

        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM user_roles 
            WHERE telegram_id = ? AND role = ?
        ''', (telegram_id, role))
        conn.commit()
        conn.close()
    
    def get_user_roles(self, telegram_id: int) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT role FROM user_roles WHERE telegram_id = ?', (telegram_id,))
        rows = cursor.fetchall()
        conn.close()
        return [row['role'] for row in rows] if rows else []
    
    def get_all_admins(self) -> List[Dict]:
        """Получить всех администраторов (только статичные из конфига)"""
        admins = []
        for admin_id in cfg.ADMIN_IDS:
            user = self.get_user_by_telegram_id(admin_id)
            if user:
                admins.append({
                    'telegram_id': admin_id,
                    'username': user.get('username'),
                    'first_name': user.get('first_name'),
                    'last_name': user.get('last_name')
                })
            else:
                admins.append({
                    'telegram_id': admin_id,
                    'username': None,
                    'first_name': None,
                    'last_name': None
                })
        return admins
    
    def get_all_workers(self) -> List[Dict]:
        """Получить всех воркеров (из конфига + из БД)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ur.telegram_id, u.username, u.first_name, u.last_name
            FROM user_roles ur
            LEFT JOIN users u ON ur.telegram_id = u.telegram_id
            WHERE ur.role = "worker"
        ''')
        db_workers = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        config_workers = []
        for worker_id in cfg.WORKER_IDS:
            if not any(w['telegram_id'] == worker_id for w in db_workers):
                user = self.get_user_by_telegram_id(worker_id)
                if user:
                    config_workers.append({
                        'telegram_id': worker_id,
                        'username': user.get('username'),
                        'first_name': user.get('first_name'),
                        'last_name': user.get('last_name')
                    })
                else:
                    config_workers.append({
                        'telegram_id': worker_id,
                        'username': None,
                        'first_name': None,
                        'last_name': None
                    })
        
        return db_workers + config_workers
    
    def get_top_workers(self, limit: int = 10) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                ws.worker_id,
                u.username,
                u.first_name,
                ws.completed_payments,
                ws.total_processed_rub,
                ws.total_commission_rub
            FROM worker_stats ws
            JOIN users u ON ws.worker_id = u.id
            ORDER BY ws.total_processed_rub DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_worker_stats(self, worker_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM worker_stats WHERE worker_id = ?', (worker_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def update_worker_stats(self, worker_id: int, completed_payments: int = None,
                      total_commission_rub: float = None, 
                      total_processed_rub: float = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            current_stats = self.get_worker_stats(worker_id)
            
            if not current_stats:
                cursor.execute('''
                    INSERT INTO worker_stats 
                    (worker_id, completed_payments, total_commission_rub, total_processed_rub)
                    VALUES (?, ?, ?, ?)
                ''', (worker_id, completed_payments or 0, total_commission_rub or 0, total_processed_rub or 0))
            else:
                updates = []
                params = []
                
                if completed_payments is not None:
                    updates.append("completed_payments = completed_payments + ?")
                    params.append(completed_payments)
                if total_commission_rub is not None:
                    updates.append("total_commission_rub = total_commission_rub + ?")
                    params.append(total_commission_rub)
                if total_processed_rub is not None:
                    updates.append("total_processed_rub = total_processed_rub + ?")
                    params.append(total_processed_rub)
                
                if updates:
                    updates.append("last_payment_at = CURRENT_TIMESTAMP")
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(worker_id)
                    
                    query = "UPDATE worker_stats SET " + ", ".join(updates) + " WHERE worker_id = ?"
                    cursor.execute(query, params)
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def freeze_user_balance_atomic(self, user_id, currency, amount, current_balance):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE user_balances 
                SET balance = balance - ?, frozen_balance = frozen_balance + ?
                WHERE user_id = ? AND currency = ? AND balance >= ?
            ''', (amount, amount, user_id, currency, amount))
            
            affected_rows = cursor.rowcount
            conn.commit()
            
            return affected_rows > 0
            
        except Exception as e:
            conn.rollback()
            print(f"Error freezing balance: {e}")
            return False
        finally:
            conn.close()

    def update_balance_atomic(self, user_id, currency, new_balance):
        """Атомарное обновление баланса"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE user_balances 
                SET balance = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND currency = ?
            ''', (new_balance, user_id, currency))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    def use_auth_code(self, code: str) -> Optional[Dict]:
        """Атомарное использование кода авторизации"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE auth_codes 
                SET is_used = 1
                WHERE code = ? AND is_used = 0 AND expires_at > ?
                RETURNING *
            ''', (code, datetime.now()))
            row = cursor.fetchone()
            conn.commit()
            return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            return None
        finally:
            conn.close()
    
    def get_setting(self, key: str) -> Optional[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        return row['value'] if row else None
    
    def update_setting(self, key: str, value: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))
        conn.commit()
        conn.close()
    
    def get_free_workers(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT ur.telegram_id, u.username, u.first_name 
            FROM user_roles ur 
            JOIN users u ON ur.telegram_id = u.telegram_id 
            LEFT JOIN worker_status ws ON u.id = ws.worker_id 
            WHERE ur.role = "worker" AND (ws.status IS NULL OR ws.status = "free")
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_busy_workers_count(self) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM worker_status WHERE status = "busy"')
        row = cursor.fetchone()
        conn.close()
        return row['count'] if row else 0
    
    def get_system_stats(self) -> Dict:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        cursor.execute('SELECT COUNT(*) as count FROM users')
        stats['total_users'] = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT COUNT(DISTINCT ub.user_id) as count 
            FROM user_balances ub 
            WHERE ub.balance > 0
        ''')
        stats['active_users'] = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_transactions,
                COALESCE(SUM(amount_rub), 0) as total_volume_rub,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN amount_rub ELSE 0 END), 0) as completed_volume_rub
            FROM transactions
        ''')
        transaction_stats = cursor.fetchone()
        stats.update(dict(transaction_stats))
        
        cursor.execute('''
            SELECT 
                COALESCE(SUM(worker_commission * amount_rub / 100), 0) as total_worker_commission,
                COALESCE(SUM(admin_commission * amount_rub / 100), 0) as total_admin_commission
            FROM transactions 
            WHERE status = 'completed'
        ''')
        commission_stats = cursor.fetchone()
        stats.update(dict(commission_stats))
        
        conn.close()
        return stats