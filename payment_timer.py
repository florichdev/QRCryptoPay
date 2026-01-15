"""
Модуль для управления таймерами платежей и штрафами
"""

import asyncio
import threading
import cfg
from datetime import datetime, timedelta
from database import Database
from exchange_rate import usd_to_sol

class PaymentTimerManager:
    def __init__(self):
        self.db = Database()
        self.active_timers = {}
        self.penalty_lock = threading.Lock()
    
    def start_payment_timer(self, transaction_id: int, worker_id: int):
        """Запустить таймер на 3 минуты для платежа"""
        timer_key = f"{transaction_id}_{worker_id}"
        
        if timer_key in self.active_timers:
            self.active_timers[timer_key].cancel()
        
        timer = threading.Timer(cfg.PAYMENT_TIMEOUT, self._handle_payment_timeout, [transaction_id, worker_id])
        timer.daemon = True
        timer.start()
        
        self.active_timers[timer_key] = timer
        print(f"[TIMER] Таймер запущен для транзакции {transaction_id}, воркер {worker_id}")
    
    def stop_payment_timer(self, transaction_id: int, worker_id: int):
        """Остановить таймер платежа"""
        timer_key = f"{transaction_id}_{worker_id}"
        
        if timer_key in self.active_timers:
            self.active_timers[timer_key].cancel()
            del self.active_timers[timer_key]
            print(f"[TIMER] Таймер остановлен для транзакции {transaction_id}")
    
    def _handle_payment_timeout(self, transaction_id: int, worker_id: int):
        """Обработать просрочку платежа"""
        with self.penalty_lock:
            try:
                print(f"[TIMER] Таймер истек для транзакции {transaction_id}")
                
                transaction = self.db.get_transaction(transaction_id)
                if not transaction or transaction['status'] != 'pending':
                    return
                
                self._apply_penalty(worker_id, transaction_id)
                
                self._free_worker(worker_id)
                
                self._notify_timeout(transaction_id, worker_id)
                
            except Exception as e:
                print(f"[TIMER] Ошибка обработки таймаута: {e}")
    
    def _apply_penalty(self, worker_id: int, transaction_id: int):
        """Применить штраф к воркеру"""
        try:
            penalty_sol = usd_to_sol(cfg.PENALTY_AMOUNT_USD)
            
            worker = self.db.get_user_by_id(worker_id)
            if worker:
                new_balance = max(0, worker['balance_sol'] - penalty_sol)
                self.db.update_user_balance(worker_id, balance_sol=new_balance)
                
                self.db.create_transaction(
                    user_id=worker_id,
                    transaction_type='penalty',
                    amount_sol=-penalty_sol,
                    amount_rub=-cfg.PENALTY_AMOUNT_USD * 100,
                    exchange_rate=cfg.DEFAULT_SOL_TO_RUB_RATE,
                    error_message=f'Штраф за просрочку платежа #{transaction_id}'
                )
                
                print(f"[PENALTY] Штраф {penalty_sol:.6f} SOL применен к воркеру {worker_id}")
        except Exception as e:
            print(f"[PENALTY] Ошибка применения штрафа: {e}")
    
    def _free_worker(self, worker_id: int):
        """Освободить воркера"""
        print(f"[WORKER] Воркер {worker_id} освобожден")
    
    def _notify_timeout(self, transaction_id: int, worker_id: int):
        """Уведомить о просрочке платежа"""
        try:
            from bot import bot, bot_loop
            import asyncio
            
            message = f"⏰ ПРОСРОЧКА! Транзакция #{transaction_id}\nВоркер {worker_id} не успел обработать платеж за 3 минуты.\nШтраф $1 применен."
            
            admins = self.db.get_all_admins()
            for admin in admins:
                try:
                    if bot_loop and bot_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            bot.send_message(admin['telegram_id'], message),
                            bot_loop
                        )
                except Exception as e:
                    print(f"[NOTIFY] Ошибка уведомления админа: {e}")
                    
        except Exception as e:
            print(f"[NOTIFY] Ошибка отправки уведомления: {e}")

timer_manager = PaymentTimerManager()