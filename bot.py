import asyncio
import json
import base64
import io
import cfg
import time
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from database import Database
from exchange_rate import calculate_commissions, get_sol_to_rub_rate
from qr_generator import QRCodeManager
from typing import Union
from solana_wallet import UniversalSolanaWallet

bot = Bot(token=cfg.TELEGRAM_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = Database()

class BotRateLimiter:
    def __init__(self):
        self.attempts = defaultdict(list)
    
    def check_limit(self, user_id, action, max_attempts=5, window_seconds=300):
        key = f"{user_id}_{action}"
        now = time.time()
        
        self.attempts[key] = [attempt for attempt in self.attempts[key] if now - attempt < window_seconds]
        
        if len(self.attempts[key]) >= max_attempts:
            return False
        
        self.attempts[key].append(now)
        return True
    
bot_rate_limiter = BotRateLimiter()

class AddBalanceStates(StatesGroup):
    waiting_for_user = State()
    waiting_for_amount = State()

class ResetTestBalanceStates(StatesGroup):
    waiting_for_user = State()

class PaymentStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_error = State()

class WithdrawalStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_address = State()

class AddWorkerStates(StatesGroup):
    waiting_for_worker_id = State()

class RemoveWorkerStates(StatesGroup):
    waiting_for_worker_id = State()

class UserConfirmationStates(StatesGroup):
    waiting_for_user_confirmation = State()

def is_admin(user_id: int) -> bool:
    return user_id in cfg.ADMIN_IDS

def is_worker(user_id: int) -> bool:
    """Проверка, является ли пользователь воркером (из конфига или БД)"""
    if user_id in cfg.WORKER_IDS:
        return True
    
    roles = db.get_user_roles(user_id)
    return 'worker' in roles or is_admin(user_id)

def get_user_role_display(user_id: int) -> str:
    roles = db.get_user_roles(user_id)
    if 'admin' in roles:
        return "👑 Администратор"
    elif 'worker' in roles:
        return "👨‍💼 Воркер"
    else:
        return "👤 Пользователь"

async def send_payment_to_workers(transaction_id: int, qr_code_data: str, 
                                  qr_code_image: str, user_info: str, amount_rub: float, 
                                  worker_earnings_sol: float = None, real_transaction: bool = False, 
                                  admin_tx_hash: str = None, worker_tx_hash: str = None,
                                  frozen_amount_sol: float = None):
    try:
        user_data = json.loads(user_info)
        
        payment_url = ""
        if 'https://' in qr_code_data:
            payment_url = qr_code_data
        elif qr_code_data.startswith('ST00012'):
            payment_url = f"https://qr.nspk.ru/proxy?qr={qr_code_data}"
        
        user_wallet = db.get_user_wallet(user_data['user_id'], 'SOL')
        if user_wallet:
            user_balance_sol = UniversalSolanaWallet.get_real_balance(user_wallet['wallet_address'])
        else:
            user_balance_sol = 0
            
        balance_status = "хватает" if user_balance_sol >= (frozen_amount_sol or 0) else "не хватает"
        
        worker_earnings_display = worker_earnings_sol or 0
        
        worker_message = f"""
🔔 *Новый платеж* {'(РЕАЛЬНЫЕ SOL)' if real_transaction else ''}

💰 *Сумма к оплате:* {amount_rub:.2f} ₽
💎 *Заработок:* {worker_earnings_display:.6f} SOL (105%)

💳 *Баланс пользователя:* {balance_status}

*ID транзакции:* {transaction_id}

*Для оплаты:*
1. Нажмите на ссылку ниже для оплаты
2. Или отсканируйте QR-код  
3. После оплаты нажмите "✅ Оплачено"
    """
        
        worker_keyboard_buttons = []
        
        if payment_url:
            worker_keyboard_buttons.append([
                InlineKeyboardButton(
                    text="🔗 Ссылка для оплаты",
                    url=payment_url
                )
            ])
        
        worker_keyboard_buttons.extend([
            [
                InlineKeyboardButton(
                    text="✅ Оплачено",
                    callback_data=f"approve_{transaction_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Ошибка",
                    callback_data=f"error_{transaction_id}"
                )
            ]
        ])
        
        worker_keyboard = InlineKeyboardMarkup(inline_keyboard=worker_keyboard_buttons)
        
        admin_message = f"""
🔔 *Новый платеж* {'(РЕАЛЬНЫЕ SOL)' if real_transaction else ''}

👤 *Пользователь:* {user_data.get('first_name', '')} (@{user_data.get('username', 'N/A')})
💰 *Сумма к оплате:* {amount_rub:.2f} ₽
💎 *Воркер получит:* {worker_earnings_display:.6f} SOL (5%)
👑 *Админ получит:* {worker_earnings_display:.6f} SOL (5%)

💳 *Баланс пользователя:* {user_balance_sol:.6f} SOL ({balance_status})
*ID транзакции:* {transaction_id}
    """
        
        admin_keyboard_buttons = []
        
        if payment_url:
            admin_keyboard_buttons.append([
                InlineKeyboardButton(
                    text="🔗 Ссылка для оплаты",
                    url=payment_url
                )
            ])
        
        admin_keyboard_buttons.extend([
            [
                InlineKeyboardButton(
                    text="✅ Оплачено",
                    callback_data=f"approve_{transaction_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Ошибка",
                    callback_data=f"error_{transaction_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Отмена",
                    callback_data=f"cancel_{transaction_id}"
                )
            ]
        ])
        
        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=admin_keyboard_buttons)
        
        workers_from_db = db.get_all_workers()
        worker_ids = [w['telegram_id'] for w in workers_from_db]
        worker_ids.extend(cfg.WORKER_IDS)
        worker_ids = list(set(worker_ids))
        
        print(f"[BOT] Отправка платежа {transaction_id} воркерам: {worker_ids}")
        print(f"[BOT] Воркер получит: {worker_earnings_display:.6f} SOL")
        print(f"[BOT] Баланс пользователя: {user_balance_sol:.6f} SOL, требуется: {frozen_amount_sol or 0:.6f} SOL, хватает: {balance_status}")
        
        sent_count = 0
        
        for worker_id in worker_ids:
            try:
                if qr_code_image:
                    try:
                        image_data = base64.b64decode(qr_code_image)
                        await bot.send_photo(
                            chat_id=worker_id,
                            photo=BufferedInputFile(image_data, filename='qr_code.png'),
                            caption=worker_message,
                            reply_markup=worker_keyboard,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        print(f"Ошибка отправки фото воркеру {worker_id}: {e}")
                        await bot.send_message(
                            chat_id=worker_id,
                            text=worker_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                            reply_markup=worker_keyboard,
                            parse_mode='Markdown'
                        )
                else:
                    await bot.send_message(
                        chat_id=worker_id,
                        text=worker_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                        reply_markup=worker_keyboard,
                        parse_mode='Markdown'
                    )
                
                sent_count += 1
                print(f"[BOT] Уведомление отправлено воркеру {worker_id}")
                    
            except Exception as e:
                print(f"[BOT] Ошибка отправки воркеру {worker_id}: {e}")
        
        admin_ids = cfg.ADMIN_IDS
        
        for admin_id in admin_ids:
            try:
                if qr_code_image:
                    try:
                        image_data = base64.b64decode(qr_code_image)
                        await bot.send_photo(
                            chat_id=admin_id,
                            photo=BufferedInputFile(image_data, filename='qr_code.png'),
                            caption=admin_message,
                            reply_markup=admin_keyboard,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        print(f"Ошибка отправки фото админу {admin_id}: {e}")
                        await bot.send_message(
                            chat_id=admin_id,
                            text=admin_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                            reply_markup=admin_keyboard,
                            parse_mode='Markdown'
                        )
                else:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                        reply_markup=admin_keyboard,
                        parse_mode='Markdown'
                    )
                
                sent_count += 1
                print(f"[BOT] Уведомление отправлено админу {admin_id}")
                    
            except Exception as e:
                print(f"[BOT] Ошибка отправки админу {admin_id}: {e}")
        
        print(f"[BOT] Всего отправлено уведомлений: {sent_count}")
        
    except Exception as e:
        print(f"❌ Критическая ошибка в send_payment_to_workers: {e}")
        import traceback
        traceback.print_exc()

async def send_withdrawal_notification_from_flask(withdrawal_data):
    """Отправка уведомления о выводе из Flask контекста"""
    try:
        withdrawal_id = withdrawal_data['withdrawal_id']
        user_id = withdrawal_data['user_id']
        user_name = withdrawal_data['user_name']
        user_username = withdrawal_data['user_username']
        user_wallet = withdrawal_data['user_wallet']
        to_wallet = withdrawal_data['to_wallet']
        amount_sol = withdrawal_data['amount_sol']
        amount_rub = withdrawal_data['amount_rub']
        transaction_id = withdrawal_data['transaction_id']
        
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
                
        return sent_count
        
    except Exception as e:
        print(f"❌ Error in send_withdrawal_notification_from_flask: {e}")
        return 0

async def send_withdrawal_request_to_admin(withdrawal_id, user_id, user_name, user_username, user_wallet, to_wallet, amount_sol, amount_rub):
    """Отправляет заявку на вывод админу"""
    try:
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
• ID заявки: {withdrawal_id}
        """
        
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
        
        for admin_id in cfg.ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=message_text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                print(f"✅ Withdrawal notification sent to admin {admin_id}")
            except Exception as e:
                print(f"❌ Error sending to admin {admin_id}: {e}")
                
    except Exception as e:
        print(f"❌ Error in send_withdrawal_request_to_admin: {e}")

def can_withdraw(user_id: int) -> bool:
    """Проверка, может ли пользователь выводить средства"""
    return is_admin(user_id)

@dp.message(Command("sync_workers"))
async def cmd_sync_workers(message: Message):
    """Синхронизировать воркеров из конфига с БД"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        synced_count = 0
        for worker_id in cfg.WORKER_IDS:
            user_roles = db.get_user_roles(worker_id)
            if 'worker' not in user_roles:
                user = db.get_user_by_telegram_id(worker_id)
                if not user:
                    user_id = db.create_user(
                        telegram_id=worker_id,
                        username=None,
                        first_name=None,
                        last_name=None
                    )
                    user = db.get_user_by_id(user_id)
                
                db.add_role(worker_id, 'worker', None)
                synced_count += 1
                print(f"✅ Добавлен воркер {worker_id}")
        
        await message.answer(f"✅ Синхронизировано {synced_count} воркеров из конфига")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка синхронизации: {str(e)}")

def can_process_payments(user_id: int) -> bool:
    """Проверка, может ли пользователь обрабатывать платежи"""
    return is_worker(user_id) or is_admin(user_id)

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активных команд для отмены.")
        return
    
    await state.clear()
    await message.answer("✅ Команда отменена.", reply_markup=get_main_keyboard(message.from_user.id))

async def add_cancel_button(message: Message, state: FSMContext):
    cancel_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )
    await message.answer("Для отмены введите /cancel или нажмите кнопку:", reply_markup=cancel_keyboard)

@dp.message(F.text == "❌ Отмена")
async def handle_cancel_button(message: Message, state: FSMContext):
    await cmd_cancel(message, state)

@dp.message(Command("reset_test_balance"))
async def cmd_reset_test_balance(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /reset_test_balance <telegram_id или @username>")
            return
        
        target = args[1]
        
        if target.startswith('@'):
            username = target[1:]
            user = db.get_user_by_username(username)
        else:
            telegram_id = int(target)
            user = db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            await message.answer("❌ Пользователь не найден.")
            return
        
        db.update_user_balance(user['id'], 'SOL', 0.0)
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE user_id = ? AND transaction_type = "test_deposit"', (user['id'],))
        conn.commit()
        conn.close()
        
        await message.answer(f"✅ Тестовый баланс пользователя {user.get('first_name', '')} (@{user.get('username', 'N/A')}) сброшен до 0.")
        
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте Telegram ID или @username.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.callback_query(F.data.startswith('approve_'))
async def handle_approve(callback: CallbackQuery, state: FSMContext):
    """Обработка подтверждения оплаты воркером"""
    if not bot_rate_limiter.check_limit(callback.from_user.id, 'approve', 10, 60):
        await callback.answer("Слишком много запросов. Подождите 1 минуту.", show_alert=True)
        return
    
    if not is_worker(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    transaction_id = int(callback.data.split('_')[1])
    transaction = db.get_transaction(transaction_id)
    
    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return
    
    if transaction['status'] != 'pending':
        await callback.answer(f"Транзакция уже обработана (статус: {transaction['status']})", show_alert=True)
        return
    
    worker_user = db.get_user_by_telegram_id(callback.from_user.id)
    if not worker_user:
        worker_user_id = db.create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name
        )
        worker_user = db.get_user_by_id(worker_user_id)
    else:
        worker_user_id = worker_user['id']
    
    success = db.assign_worker_to_transaction(transaction_id, worker_user_id)
    
    if not success:
        await callback.answer("❌ Операция уже взята другим воркером", show_alert=True)
        return
    
    payment_queue = db.get_payment_queue_by_transaction(transaction_id)
    if not payment_queue:
        await callback.answer("❌ Данные о платеже не найдены", show_alert=True)
        return
    
    user_info = json.loads(payment_queue['user_info'])
    
    db.update_transaction_status(
        transaction_id=transaction_id,
        status='waiting_user_confirmation',
        worker_id=worker_user_id
    )

    user = db.get_user_by_id(transaction['user_id'])
    
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    user_confirmation_message = f"""
🔔 Воркер подтвердил оплату

💰 Сумма: {abs(transaction['amount_rub']):.2f} ₽
💎 Будет списано: {user_info.get('frozen_amount_sol', 0):.6f} SOL

✅ Платеж прошел успешно?

Если да - средства будут списаны.
Если нет - операция будет отменена.
"""
    
    user_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Да, платеж прошел",
                callback_data=f"user_confirm_{transaction_id}"
            ),
            InlineKeyboardButton(
                text="❌ Нет, платеж не прошел", 
                callback_data=f"user_reject_{transaction_id}"
            )
        ]
    ])
    
    try:
        await bot.send_message(
            chat_id=user['telegram_id'],
            text=user_confirmation_message,
            reply_markup=user_keyboard
        )
        await callback.answer("✅ Запрос отправлен пользователю на подтверждение")
        
        worker_message = f"""
⏳ Ожидание подтверждения пользователя

💳 Сумма: {abs(transaction['amount_rub']):.2f} ₽

Ожидайте подтверждения от пользователя...
"""
    
        try:
            await callback.message.edit_text(
                worker_message,
                reply_markup=None
            )
        except Exception as e:
            print(f"Не удалось обновить сообщение воркера, отправляем новое: {e}")
            await callback.message.answer(worker_message)
            
    except Exception as e:
        print(f"Не удалось отправить запрос подтверждения пользователю: {e}")
        await callback.answer("❌ Ошибка отправки запроса пользователю", show_alert=True)
        db.update_transaction_status(
            transaction_id=transaction_id,
            status='pending',
            worker_id=None
        )

@dp.callback_query(F.data.startswith('user_confirm_'))
async def handle_user_confirm(callback: CallbackQuery):
    """Пользователь подтверждает успешный платеж"""
    transaction_id = int(callback.data.split('_')[2])
    transaction = db.get_transaction(transaction_id)
    
    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return
    
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    if transaction['user_id'] != user['id']:
        await callback.answer("❌ Это не ваша транзакция", show_alert=True)
        print(f"❌ User ID mismatch: transaction_user_id={transaction['user_id']}, current_user_id={user['id']}, telegram_id={callback.from_user.id}")
        return
    
    if transaction['status'] != 'waiting_user_confirmation':
        await callback.answer(f"Транзакция уже обработана (статус: {transaction['status']})", show_alert=True)
        return
    
    await callback.answer("✅ Платеж подтвержден!")
    
    try:
        await callback.message.edit_text(
            "✅ Платеж успешно завершен!\n\nСредства переведены воркеру и админу.",
            reply_markup=None
        )
    except Exception as e:
        print(f"Не удалось обновить сообщение пользователя: {e}")
        await callback.message.answer("✅ Платеж успешно завершен!\n\nСредства переведены воркеру и админу.")
    
    await process_successful_payment(transaction_id, user['id'])

@dp.callback_query(F.data.startswith('user_reject_'))
async def handle_user_reject(callback: CallbackQuery):
    """Пользователь отклоняет платеж"""
    transaction_id = int(callback.data.split('_')[2])
    transaction = db.get_transaction(transaction_id)
    
    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return
    
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    if transaction['user_id'] != user['id']:
        await callback.answer("❌ Это не ваша транзакция", show_alert=True)
        print(f"❌ User ID mismatch: transaction_user_id={transaction['user_id']}, current_user_id={user['id']}, telegram_id={callback.from_user.id}")
        return
    
    if transaction['status'] != 'waiting_user_confirmation':
        await callback.answer("Транзакция уже обработана", show_alert=True)
        return
    
    db.update_transaction_status(
        transaction_id=transaction_id,
        status='cancelled',
        error_message='Отклонено пользователем'
    )
    
    db.unfreeze_user_balance(transaction['user_id'], 'SOL')
    
    worker_user = db.get_user_by_id(transaction['worker_id'])
    if worker_user:
        try:
            await bot.send_message(
                chat_id=worker_user['telegram_id'],
                text=f"❌ Платеж отклонен пользователем\n\nТранзакция #{transaction_id} была отклонена.",
            )
        except Exception as e:
            print(f"Не удалось уведомить воркера об отмене: {e}")
    
    await callback.answer("❌ Платеж отклонен")
    
    try:
        await callback.message.edit_text(
            "❌ Платеж отклонен\n\nСредства остались на вашем балансе.",
            reply_markup=None
        )
    except Exception as e:
        print(f"Не удалось обновить сообщение пользователя: {e}")
        await callback.message.answer("❌ Платеж отклонен\n\nСредства остались на вашем балансе.")

async def process_successful_payment(transaction_id: int, user_id: int):
    """Обработка успешного платежа после подтверждения пользователем"""
    try:
        print(f"🔄 Начало обработки успешного платежа для транзакции {transaction_id}, user_id: {user_id}")
        
        transaction = db.get_transaction(transaction_id)
        payment_queue = db.get_payment_queue_by_transaction(transaction_id)
        
        if not transaction:
            print(f"❌ Транзакция {transaction_id} не найдена")
            return
        
        if not payment_queue:
            print(f"❌ Payment queue для транзакции {transaction_id} не найден")
            return
        
        user_info = json.loads(payment_queue['user_info'])
        frozen_amount_sol = user_info.get('frozen_amount_sol', 0)
        worker_earnings_sol = user_info.get('worker_earnings_sol', 0)
        admin_commission_sol = user_info.get('admin_commission_sol', 0)
        
        print(f"📊 Данные платежа: frozen={frozen_amount_sol}, worker_earnings={worker_earnings_sol}, admin_commission={admin_commission_sol}")
        
        user_wallet = db.get_user_wallet(transaction['user_id'], 'SOL')
        if not user_wallet or not user_wallet.get('private_key'):
            print(f"❌ Кошелек пользователя не найден для транзакции {transaction_id}")
            return
        
        print(f"📤 Отправка {admin_commission_sol:.6f} SOL админу...")
        admin_result = UniversalSolanaWallet.send_sol_to_admin(
            user_private_key=user_wallet['private_key'],
            admin_wallet=cfg.ADMIN_WALLET,
            amount_sol=admin_commission_sol
        )
        
        print(f"📤 Результат отправки админу: {admin_result['success']}")
        
        worker_wallet = db.get_user_wallet(transaction['worker_id'], 'SOL')
        if worker_wallet:
            print(f"📤 Отправка {worker_earnings_sol:.6f} SOL воркеру...")
            worker_result = UniversalSolanaWallet.send_sol_simple(
                from_private_key=user_wallet['private_key'],
                to_address=worker_wallet['wallet_address'],
                amount_sol=worker_earnings_sol
            )
            print(f"📤 Результат отправки воркеру: {worker_result['success']}")
        else:
            print(f"⚠️ Кошелек воркера не найден")
        
        real_balance = UniversalSolanaWallet.get_real_balance(user_wallet['wallet_address'])
        new_real_balance = real_balance - frozen_amount_sol
        db.update_user_balance(transaction['user_id'], 'SOL', new_real_balance)
        
        print(f"💰 Баланс пользователя обновлен: {real_balance:.6f} -> {new_real_balance:.6f} SOL")
        
        db.unfreeze_user_balance(transaction['user_id'], 'SOL')
        
        db.update_transaction_status(
            transaction_id=transaction_id,
            status='completed'
        )
        
        db.update_worker_stats(
            worker_id=transaction['worker_id'],
            completed_payments=1,
            total_commission_rub=abs(transaction['amount_rub']) * 0.05, 
            total_processed_rub=abs(transaction['amount_rub'])
        )
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE payment_queue 
            SET status = 'completed'
            WHERE transaction_id = ?
        ''', (transaction_id,))
        conn.commit()
        conn.close()
        
        worker_user = db.get_user_by_id(transaction['worker_id'])
        if worker_user:
            try:
                await bot.send_message(
                    chat_id=worker_user['telegram_id'],
                    text=f"✅ Платеж завершен!\n\n"
                         f"💳 Сумма: {abs(transaction['amount_rub']):.2f} ₽\n"
                         f"💎 Вы получили: {worker_earnings_sol:.6f} SOL (5%)\n"
                         f"👤 Пользователь подтвердил оплату",
                )
                print(f"✅ Уведомление отправлено воркеру {worker_user['telegram_id']}")
            except Exception as e:
                print(f"Не удалось уведомить воркера: {e}")
        
        print(f"✅ Платеж {transaction_id} успешно завершен")
        
    except Exception as e:
        print(f"❌ Ошибка в process_successful_payment для транзакции {transaction_id}: {e}")
        import traceback
        traceback.print_exc()
               
@dp.message(PaymentStates.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount_rub = float(message.text)
        
        if amount_rub <= 0:
            await message.answer("❌ Сумма должна быть больше нуля")
            return
        
        data = await state.get_data()
        transaction_id = data.get('transaction_id')
        
        if not transaction_id:
            await message.answer("❌ Ошибка: транзакция не найдена")
            await state.clear()
            return
        
        transaction = db.get_transaction(transaction_id)
        if not transaction:
            await message.answer("❌ Транзакция не найдена")
            await state.clear()
            return
        
        user = db.get_user_by_id(transaction['user_id'])
        if not user:
            await message.answer("❌ Пользователь не найден")
            await state.clear()
            return
        
        user_wallet = db.get_user_wallet(transaction['user_id'], 'SOL')
        if not user_wallet or not user_wallet.get('private_key'):
            await message.answer("❌ Кошелек пользователя не найден")
            await state.clear()
            return
        
        worker_user = db.get_user_by_telegram_id(message.from_user.id)
        worker_wallet = db.get_user_wallet(worker_user['id'], 'SOL') if worker_user else None
        
        if not worker_wallet:
            await message.answer("❌ У вас нет кошелька SOL. Зарегистрируйтесь на сайте.")
            await state.clear()
            return
        
        worker_earnings_sol = amount_rub * 0.05 / get_sol_to_rub_rate()
        
        worker_result = UniversalSolanaWallet.send_sol_to_worker(
            user_private_key=user_wallet['private_key'],
            worker_wallet=worker_wallet['wallet_address'],
            amount_sol=worker_earnings_sol
        )
        
        if not worker_result['success']:
            await message.answer(f"❌ Ошибка отправки SOL воркеру: {worker_result.get('error')}")
            await state.clear()
            return
        
        db.update_transaction_status(
            transaction_id=transaction_id,
            status='completed',
            worker_id=worker_user['id']
        )
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE transactions 
            SET amount_rub = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (amount_rub, transaction_id))
        conn.commit()
        conn.close()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE payment_queue 
            SET status = 'completed', assigned_worker_id = ?
            WHERE transaction_id = ?
        ''', (worker_user['id'], transaction_id))
        conn.commit()
        conn.close()
        
        db.update_worker_stats(
            worker_id=worker_user['id'],
            completed_payments=1,
            total_commission_rub=amount_rub * 0.05,  
            total_processed_rub=amount_rub
        )
        
        try:
            user_telegram_id = user['telegram_id']
            await bot.send_message(
                chat_id=user_telegram_id,
                text=f"✅ *Платеж выполнен!*\n\n"
                     f"💳 Сумма: {amount_rub:.2f} ₽\n"
                     f"💎 Воркер получил: {worker_earnings_sol:.6f} SOL\n"
                     f"🆔 Транзакция: #{transaction_id}",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Не удалось уведомить пользователя: {e}")
        
        await message.answer(
            f"✅ *Платеж успешно обработан!*\n\n"
            f"💳 Сумма платежа: {amount_rub:.2f} ₽\n"
            f"💎 Вы получили: {worker_earnings_sol:.6f} SOL (5%)\n"
            f"👑 Админ получил: {worker_earnings_sol:.6f} SOL (5%)\n"
            f"🔗 Ваша транзакция: {worker_result.get('tx_hash')}\n"
            f"👤 Пользователь уведомлен",
            parse_mode='Markdown'
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()

@dp.callback_query(F.data.startswith('error_'))
async def handle_error(callback: CallbackQuery, state: FSMContext):
    if not bot_rate_limiter.check_limit(callback.from_user.id, 'error', 10, 60):
        await callback.answer("Слишком много запросов. Подождите 1 минуту.", show_alert=True)
        return
    
    if not is_worker(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    transaction_id = int(callback.data.split('_')[1])
    transaction = db.get_transaction(transaction_id)
    
    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return
    
    if transaction['status'] != 'pending':
        await callback.answer("Транзакция уже обработана", show_alert=True)
        return
    
    worker_user = db.get_user_by_telegram_id(callback.from_user.id)
    if not worker_user:
        worker_user_id = db.create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name
        )
    else:
        worker_user_id = worker_user['id']
    
    success = db.assign_worker_to_transaction(transaction_id, worker_user_id)
    
    if not success:
        await callback.answer("❌ Операция уже взята другим воркером", show_alert=True)
        return
    
    await state.update_data(transaction_id=transaction_id)
    await state.set_state(PaymentStates.waiting_for_error)
    
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"❌ Введите описание ошибки для транзакции #{transaction_id}:"
    )

@dp.message(PaymentStates.waiting_for_error)
async def process_error(message: Message, state: FSMContext):
    error_text = message.text
    
    data = await state.get_data()
    transaction_id = data.get('transaction_id')
    
    if not transaction_id:
        await message.answer("❌ Ошибка: транзакция не найдена")
        await state.clear()
        return
    
    worker_user = db.get_user_by_telegram_id(message.from_user.id)
    if not worker_user:
        worker_user_id = db.create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
    else:
        worker_user_id = worker_user['id']
    
    transaction = db.get_transaction(transaction_id)
    if transaction:
        user_id = transaction['user_id']
        db.unfreeze_user_balance(user_id, 'SOL')
    
    db.update_transaction_status(
        transaction_id=transaction_id,
        status='error',
        worker_id=worker_user_id,
        error_message=error_text
    )
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE payment_queue 
        SET status = 'error', assigned_worker_id = ?
        WHERE transaction_id = ?
    ''', (worker_user_id, transaction_id))
    conn.commit()
    conn.close()
    
    try:
        user = db.get_user_by_id(transaction['user_id'])
        current_balance = db.get_user_balance(user_id, 'SOL')
        await bot.send_message(
            user['telegram_id'],
            f"❌ *Платеж отменен*\n\n"
            f"Причина: {error_text}\n"
            f"💎 Средства возвращены на ваш баланс\n"
            f"💰 Ваш баланс: {current_balance:.6f} SOL\n"
            f"🆔 Транзакция: #{transaction_id}",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя: {e}")
    
    await message.answer(f"❌ Платеж отменен. Средства возвращены пользователю.")
    await state.clear()

@dp.callback_query(F.data.startswith('cancel_'))
async def handle_cancel(callback: CallbackQuery):
    """Обработка отмены транзакции администратором"""
    if not callback.data.startswith('cancel_'):
        await callback.answer("❌ Неверная команда", show_alert=True)
        return
    
    try:
        parts = callback.data.split('_')
        if len(parts) < 2:
            await callback.answer("❌ Неверный формат команды", show_alert=True)
            return
            
        transaction_id = int(parts[1])
    except (IndexError, ValueError) as e:
        await callback.answer("❌ Неверный формат ID транзакции", show_alert=True)
        return
    
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Только для администраторов", show_alert=True)
        return
    
    transaction = db.get_transaction(transaction_id)
    
    if not transaction:
        await callback.answer("❌ Транзакция не найдена", show_alert=True)
        return
    
    if transaction['status'] != 'pending':
        await callback.answer("❌ Транзакция уже обработана", show_alert=True)
        return
    
    admin_user = db.get_user_by_telegram_id(callback.from_user.id)
    if not admin_user:
        admin_user_id = db.create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name
        )
    else:
        admin_user_id = admin_user['id']
    
    db.update_transaction_status(
        transaction_id=transaction_id,
        status='cancelled',
        admin_id=admin_user_id,
        error_message='Отменено администратором'
    )
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE payment_queue 
        SET status = 'cancelled', assigned_worker_id = ?
        WHERE transaction_id = ?
    ''', (admin_user_id, transaction_id))
    conn.commit()
    conn.close()
    
    user_id = transaction['user_id']
    amount_sol = abs(transaction['amount'])
    current_balance = db.get_user_balance(user_id, 'SOL')
    new_balance = current_balance + amount_sol
    db.update_user_balance(user_id, 'SOL', new_balance)
    
    await callback.answer("✅ Транзакция отменена")
    
    try:
        await callback.message.edit_text(
            f"🚫 Транзакция #{transaction_id} отменена.\n"
            f"💎 Возвращено пользователю: {amount_sol:.6f} SOL\n"
            f"💰 Новый баланс пользователя: {new_balance:.6f} SOL",
            reply_markup=None
        )
    except Exception as e:
        await callback.message.answer(
            f"🚫 Транзакция #{transaction_id} отменена.\n"
            f"💎 Возвращено пользователю: {amount_sol:.6f} SOL"
        )
    
    try:
        user = db.get_user_by_id(user_id)
        if user and user.get('telegram_id'):
            await bot.send_message(
                user['telegram_id'],
                f"💰 *Средства возвращены!*\n\n"
                f"Транзакция #{transaction_id} была отменена администратором.\n"
                f"💎 Возвращено: {amount_sol:.6f} SOL\n"
                f"💰 Ваш баланс: {new_balance:.6f} SOL",
                parse_mode='Markdown'
            )
    except Exception as e:
        print(f"Не удалось уведомить пользователя о возврате средств: {e}")

@dp.callback_query(F.data == "pending_operations")
async def handle_pending_operations(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    pending_txs = db.get_pending_transactions_for_admin()
    
    if not pending_txs:
        await callback.answer("Нет ожидающих операций", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for tx in pending_txs[:10]:
        user_info = f"{tx.get('first_name', '')} (@{tx.get('username', 'N/A')})"
        amount = abs(tx['amount_rub'] or 0)
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"#{tx['id']} - {amount}₽ - {user_info}",
                callback_data=f"admin_take_{tx['id']}"
            )
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="pending_operations"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")
    ])
    
    await callback.message.edit_text(
        "📋 *Ожидающие операции:*\n\n" +
        "\n".join([f"#{tx['id']} - {abs(tx['amount_rub'] or 0)}₽ - {tx.get('first_name', '')}" 
                  for tx in pending_txs[:10]]),
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@dp.callback_query(F.data.startswith('admin_take_'))
async def handle_admin_take_operation(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    transaction_id = int(callback.data.split('_')[2])
    
    transaction = db.get_transaction(transaction_id)
    if not transaction:
        await callback.answer("❌ Транзакция не найдена", show_alert=True)
        return
    
    if transaction['status'] != 'pending':
        await callback.answer(f"❌ Транзакция уже обработана (статус: {transaction['status']})", show_alert=True)
        return
    
    admin_user = db.get_user_by_telegram_id(callback.from_user.id)
    if not admin_user:
        admin_user_id = db.create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name
        )
    else:
        admin_user_id = admin_user['id']
    
    success = db.assign_worker_to_transaction(transaction_id, admin_user_id)
    
    if success:
        await callback.answer("✅ Операция взята в работу")
        
        transaction = db.get_transaction(transaction_id)
        user = db.get_user_by_id(transaction['user_id'])
        
        message_text = f"""
🔔 Операция взята в работу

👤 Пользователь: {user.get('first_name', '')} (@{user.get('username', 'N/A')})
💰 Сумма: {abs(transaction['amount_rub'] or 0):.2f} ₽
🆔 Транзакция: #{transaction_id}
📊 Статус: {transaction['status']}

Выберите действие:
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Оплачено",
                    callback_data=f"approve_{transaction_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Ошибка", 
                    callback_data=f"error_{transaction_id}"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Назад к операциям", callback_data="pending_operations")
            ]
        ])
        
        await callback.message.edit_text(message_text, reply_markup=keyboard)
    else:
        await callback.answer("❌ Операция уже взята другим воркером", show_alert=True)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    import secrets
    import string
    
    if message.from_user.id in cfg.WORKER_IDS:
        user_roles = db.get_user_roles(message.from_user.id)
        if 'worker' not in user_roles:
            try:
                db.add_role(message.from_user.id, 'worker', None)
                print(f"✅ Автоматически добавлен воркер {message.from_user.id}")
            except Exception as e:
                print(f"⚠️ Ошибка добавления воркера: {e}")
    
    command_args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if command_args:
        param = command_args[0]
        
        if param.startswith('register_'):
            session_code = param.replace('register_', '')
            code_type = 'register'
        elif param.startswith('login_'):
            session_code = param.replace('login_', '')
            code_type = 'login'
        elif param.startswith('pay_'):
            transaction_id = param.replace('pay_', '')
            await handle_quick_payment(message, int(transaction_id))
            return
        else:
            await message.answer("Неверная ссылка. Используйте ссылку с сайта.")
            return
        
        session = db.get_session_code(session_code)
        if not session:
            await message.answer("❌ Ссылка недействительна или истекла. Попробуйте снова с сайта.")
            return
        
        if session['code_type'] != code_type:
            await message.answer("❌ Неверный тип ссылки.")
            return
        
        auth_code = ''.join(secrets.choice(string.digits) for _ in range(6))
        
        db.create_auth_code(
            code=auth_code,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            code_type=code_type,
            expires_in_minutes=10
        )
        
        db.update_session_code_with_auth(session_code, auth_code, message.from_user.id)
        
        db.mark_session_code_as_used(session_code)
        
        action_text = "регистрации" if code_type == 'register' else "входа"
        await message.answer(
            f"🔐 *Код для {action_text}:*\n\n"
            f"`{auth_code}`\n\n"
            f"Введите этот код на сайте для {action_text}.\n"
            f"Код действителен 10 минут.",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(message.from_user.id)
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в CryptoPay!\n\n"
            "Используйте кнопки ниже для навигации.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        await show_profile(message)

async def handle_quick_payment(message: Message, transaction_id: int):
    if not is_worker(message.from_user.id):
        await message.answer("❌ У вас нет доступа к оплате платежей.")
        return
    
    transaction = db.get_transaction(transaction_id)
    if not transaction:
        await message.answer("❌ Транзакция не найдена.")
        return
    
    if transaction['status'] != 'pending':
        await message.answer("❌ Транзакция уже обработана.")
        return
    
    user = db.get_user_by_id(transaction['user_id'])
    amount_rub = transaction['amount_rub'] or 100
    
    message_text = f"""
💳 *Быстрая оплата*

👤 *Пользователь:* {user.get('first_name', '')} (@{user.get('username', 'N/A')})
💰 *Сумма:* {amount_rub:.2f} ₽
🆔 *Транзакция:* #{transaction_id}

*Выберите действие:*
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Оплачено",
                callback_data=f"approve_{transaction_id}"
            ),
            InlineKeyboardButton(
                text="❌ Ошибка",
                callback_data=f"error_{transaction_id}"
            )
        ]
    ])
    
    await message.answer(message_text, reply_markup=keyboard, parse_mode='Markdown')

async def show_profile(message: Union[Message, CallbackQuery]):
    """
    Показать профиль пользователя с обработкой ошибки 'message is not modified'
    """
    if isinstance(message, CallbackQuery):
        user_id = message.from_user.id
        message_obj = message.message
        is_callback = True
    else:
        user_id = message.from_user.id
        message_obj = message
        is_callback = False
    
    user = db.get_user_by_telegram_id(user_id)
    
    if not user:
        help_text = f"Привет, {message.from_user.first_name}!\n\n"
        help_text += "Вы еще не зарегистрированы в системе CryptoPay.\n"
        help_text += "Для регистрации используйте ссылку с сайта."
        
        if is_callback:
            try:
                await message_obj.edit_text(help_text, reply_markup=get_main_keyboard(user_id))
            except Exception as e:
                if "message is not modified" in str(e):
                    await message.answer()
                else:
                    await message_obj.answer(help_text, reply_markup=get_main_keyboard(user_id))
        else:
            await message_obj.answer(help_text, reply_markup=get_main_keyboard(user_id))
        return
    
    role_display = get_user_role_display(user_id)
    
    balance_sol = db.get_user_balance(user['id'], 'SOL')
    rate = get_sol_to_rub_rate()
    balance_rub = balance_sol * rate * 0.9
    
    balance_text = f"💰 *Баланс SOL:* {balance_sol:.6f} SOL ≈ {balance_rub:.0f} ₽\n"
    
    stats_text = ""
    if is_worker(user_id):
        stats = db.get_worker_stats(user['id'])
        if stats:
            stats_text = f"\n📊 *Ваш заработок:*\n"
            stats_text += f"• Обработано платежей: {stats['completed_payments']}\n"
            stats_text += f"• Общая сумма: {stats['total_processed_rub']:.0f} ₽\n"
            stats_text += f"• 💰 Заработано комиссий: {stats['total_commission_rub']:.0f} ₽\n"
            if stats['total_commission_rub'] > 0:
                stats_text += f"• 💎 Доступно для вывода: {(stats['total_commission_rub'] / rate):.6f} SOL\n"
    
    profile_text = f"""
👤 *Ваш профиль*

{balance_text}
{role_display}
📧 *Username:* @{user.get('username', 'не указан')}
👋 *Имя:* {user.get('first_name', 'не указано')}
{stats_text}
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    if is_admin(user_id):
        pending_count = len(db.get_pending_transactions_for_admin())
        withdrawal_count = len(db.get_pending_withdrawals())
        
        keyboard.inline_keyboard.extend([
            [InlineKeyboardButton(text=f"📋 Ожидающие операции ({pending_count})", callback_data="pending_operations")],
            [InlineKeyboardButton(text="👑 Админ панель", callback_data="admin_panel")],
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="withdraw")]
        ])
    
    elif is_worker(user_id) and not is_admin(user_id):
        stats = db.get_worker_stats(user['id'])
        has_earnings = stats and stats['total_commission_rub'] > 0
        
        keyboard.inline_keyboard.extend([
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="withdraw")],
            [InlineKeyboardButton(text="📈 Мой заработок", callback_data="worker_stats")]
        ])
        
        if has_earnings:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="💰 Вывод заработка", callback_data="withdraw_earnings")
            ])
    
    else:
        keyboard.inline_keyboard.extend([
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="withdraw")]
        ])
    
    keyboard.inline_keyboard.extend([
        [InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="refresh_balance")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    
    try:
        if is_callback:
            await message_obj.edit_text(profile_text, reply_markup=keyboard, parse_mode='Markdown')
        else:
            await message_obj.answer(profile_text, reply_markup=keyboard, parse_mode='Markdown')
            
    except Exception as e:
        error_msg = str(e).lower()
        
        if "message is not modified" in error_msg:
            if is_callback:
                await message.answer()
        elif "message to edit not found" in error_msg:
            if is_callback:
                await message_obj.answer(profile_text, reply_markup=keyboard, parse_mode='Markdown')
        elif "message can't be edited" in error_msg:
            if is_callback:
                await message_obj.answer(profile_text, reply_markup=keyboard, parse_mode='Markdown')
        else:
            print(f"Ошибка при показе профиля: {e}")
            if is_callback:
                try:
                    await message_obj.answer(profile_text, reply_markup=keyboard, parse_mode='Markdown')
                except Exception as e2:
                    print(f"Критическая ошибка при отправке профиля: {e2}")
                    await message.answer("❌ Ошибка при загрузке профиля")
            else:
                await message_obj.answer("❌ Ошибка при загрузке профиля")

@dp.callback_query(F.data == "deposit")
async def handle_deposit(callback: CallbackQuery):
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    wallet = db.get_user_wallet(user['id'], 'SOL')
    if not wallet:
        await callback.answer("❌ Кошелек не найден", show_alert=True)
        return
    
    network_info = "MAINNET (реальные средства)" if cfg.IS_MAINNET else "DEVNET (тестовые средства)"
    
    deposit_text = f"""
💰 *Пополнение баланса*

🏦 Адрес вашего кошелька:
`{wallet['wallet_address']}`

🌐 Сеть: {network_info}

*Инструкция:*
1. Отправьте SOL на указанный адрес
2. Нажмите "🔄 Обновить баланс"
3. Средства появятся на вашем балансе

⚠️ *Внимание:* Отправляйте только SOL!
Другие токены могут быть утеряны.
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="refresh_balance")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(deposit_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback.answer()

@dp.callback_query(F.data == "admin_panel")
async def handle_admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    pending_count = len(db.get_pending_transactions_for_admin())
    withdrawal_count = len(db.get_pending_withdrawals())
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📋 Ожидающие операции ({pending_count})", callback_data="pending_operations")],
        [InlineKeyboardButton(text=f"💸 Заявки на вывод ({withdrawal_count})", callback_data="withdrawal_requests")],
        [InlineKeyboardButton(text="👨‍💼 Управление воркерами", callback_data="manage_workers")],
        [InlineKeyboardButton(text="💰 Просмотр кошельков воркеров", callback_data="view_worker_wallets")],
        [InlineKeyboardButton(text="📊 Статистика системы", callback_data="system_stats")],
        [InlineKeyboardButton(text="💰 Управление балансами", callback_data="manage_balances")],
        [InlineKeyboardButton(text="📋 Список команд", callback_data="admin_commands")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(
        f"👑 *Админ панель*\n\n"
        f"📊 *Статистика:*\n"
        f"• Ожидающие операции: {pending_count}\n"
        f"• Заявки на вывод: {withdrawal_count}",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(F.data == "network_management")
async def handle_network_management(callback: CallbackQuery):
    """Управление сетями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    network_status = "MAINNET (реальные деньги)" if cfg.IS_MAINNET else "DEVNET (тестовые)"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Переключить сеть", callback_data="switch_network_menu")],
        [InlineKeyboardButton(text="🌐 Статус сети", callback_data="network_status_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        f"🌐 *Управление сетями*\n\n"
        f"Текущая сеть: **{network_status}**",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.message(Command("wallet_info"))
async def cmd_wallet_info(message: Message):
    """Информация о кошельке"""
    user = db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не зарегистрированы.")
        return
    
    wallet = db.get_user_wallet(user['id'], 'SOL')
    if not wallet:
        await message.answer("❌ Кошелек не найден.")
        return
    
    balance = UniversalSolanaWallet.get_balance(wallet['wallet_address'])
    
    network_info = "MAINNET (реальные средства)" if cfg.IS_MAINNET else "DEVNET (тестовые средства)"
    network_emoji = "💰" if cfg.IS_MAINNET else "🛠️"
    
    wallet_info = f"""
{network_emoji} *Информация о кошельке*

🏦 Адрес: `{wallet['wallet_address']}`
💎 Баланс: {balance:.6f} SOL
🌐 Сеть: {network_info}

*Для пополнения:* 
Отправьте SOL на адрес выше

*Команды:*
`/network_status` - статус сети
`/test_sol` - получить тестовые SOL (только devnet)
{'`/switch_network` - переключить сеть (админы)' if is_admin(message.from_user.id) else ''}
    """
    
    await message.answer(wallet_info, parse_mode='Markdown')

@dp.message(Command("network_status"))
async def cmd_network_status(message: Message):
    """Показать статус сети"""
    network_status = "🌐 *Статус сети:*\n\n"
    
    if cfg.IS_MAINNET:
        network_status += "✅ **MAINNET** - реальные деньги\n"
        network_status += "💎 Все операции с REAL SOL\n"
        network_status += "⚠️ Будьте осторожны!\n"
    else:
        network_status += "🛠️ **DEVNET** - тестовая сеть\n"
        network_status += "🎯 Все операции с TEST SOL\n"
        network_status += "🪂 Используйте /test_sol для получения тестовых средств\n"
    
    network_status += f"\n🔗 RPC: {cfg.SOLANA_RPC_URL}"
    
    await message.answer(network_status, parse_mode='Markdown')

@dp.message(Command("switch_network"))
async def cmd_switch_network(message: Message):
    """Переключить сеть (только для админов)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для администраторов.")
        return
    
    current_network = "mainnet" if cfg.IS_MAINNET else "devnet"
    new_network = "devnet" if cfg.IS_MAINNET else "mainnet"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Переключить на {new_network.upper()}", callback_data=f"confirm_switch_{new_network}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_switch")]
    ])
    
    warning = "⚠️ **ВНИМАНИЕ!** ⚠️\n\n" if new_network == "mainnet" else ""
    
    await message.answer(
        f"{warning}"
        f"Текущая сеть: **{current_network.upper()}**\n"
        f"Новая сеть: **{new_network.upper()}**\n\n"
        f"{'🚨 Вы переключаетесь на РЕАЛЬНЫЕ ДЕНЬГИ! 🚨' if new_network == 'mainnet' else '✅ Переключаемся на тестовую сеть'}\n\n"
        f"Подтвердите действие:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@dp.callback_query(F.data.startswith('confirm_switch_'))
async def handle_confirm_switch(callback: CallbackQuery):
    """Подтверждение переключения сети"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    new_network = callback.data.split('_')[2]
    
    try:
        import os
        import json
        
        config_path = 'cfg.py'
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = content.replace(
            f'SOLANA_NETWORK = "{cfg.SOLANA_NETWORK}"',
            f'SOLANA_NETWORK = "{new_network}"'
        )
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        import importlib
        import cfg
        importlib.reload(cfg)
        
        if new_network == "mainnet":
            new_rpc_content = new_content.replace(
                f'SOLANA_RPC_URL = "{cfg.SOLANA_RPC_URL}"',
                'SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"'
            )
        else:
            new_rpc_content = new_content.replace(
                f'SOLANA_RPC_URL = "{cfg.SOLANA_RPC_URL}"',
                'SOLANA_RPC_URL = "https://api.devnet.solana.com"'
            )
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_rpc_content)
        
        importlib.reload(cfg)
        
        await callback.message.edit_text(
            f"✅ Сеть успешно переключена!\n\n"
            f"🌐 Новая сеть: **{new_network.upper()}**\n"
            f"🔗 RPC: {cfg.SOLANA_RPC_URL}\n\n"
            f"{'🚨 Теперь все операции с REAL SOL!' if new_network == 'mainnet' else '✅ Теперь все операции с TEST SOL'}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка переключения сети: {str(e)}"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "cancel_switch")
async def handle_cancel_switch(callback: CallbackQuery):
    """Отмена переключения сети"""
    await callback.message.edit_text(
        "❌ Переключение сети отменено.\n"
        f"Текущая сеть: **{cfg.SOLANA_NETWORK.upper()}**",
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(F.data == "system_stats")
async def handle_system_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    stats = db.get_system_stats()
    
    total_users = stats.get('total_users', 0)
    active_users = stats.get('active_users', 0)
    total_transactions = stats.get('total_transactions', 0)
    total_volume_rub = stats.get('total_volume_rub', 0)
    completed_volume_rub = stats.get('completed_volume_rub', 0)
    total_worker_commission = stats.get('total_worker_commission', 0)
    total_admin_commission = stats.get('total_admin_commission', 0)
    
    stats_text = f"""
📊 Статистика системы:

👥 Пользователи: {total_users}
👤 Активные: {active_users}

💸 Транзакции:
• Всего: {total_transactions}
• Объем: {total_volume_rub:.0f} ₽
• Завершено: {completed_volume_rub:.0f} ₽

💰 Комиссии:
• Воркеры: {total_worker_commission:.0f} ₽
• Админы: {total_admin_commission:.0f} ₽
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(stats_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "manage_workers")
async def handle_manage_workers(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить воркера", callback_data="add_worker")],
        [InlineKeyboardButton(text="➖ Удалить воркера", callback_data="remove_worker")],
        [InlineKeyboardButton(text="📈 Топ воркеры", callback_data="top_workers")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text("👨‍💼 Управление воркерами:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "add_worker")
async def handle_add_worker(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await state.set_state(AddWorkerStates.waiting_for_worker_id)
    await callback.message.answer("Введите Telegram ID пользователя для добавления в воркеры:")
    await callback.answer()

@dp.message(AddWorkerStates.waiting_for_worker_id)
async def process_add_worker(message: Message, state: FSMContext):
    try:
        telegram_id = int(message.text)
        
        admin_user = db.get_user_by_telegram_id(message.from_user.id)
        added_by = admin_user['id'] if admin_user else None
        
        try:
            db.add_role(telegram_id, 'worker', added_by)
            
            target_user = db.get_user_by_telegram_id(telegram_id)
            if target_user:
                await message.answer(f"✅ Пользователь {target_user.get('first_name', '')} (@{target_user.get('username', 'N/A')}) добавлен как воркер.")
            else:
                await message.answer(f"✅ Пользователь с ID {telegram_id} добавлен как воркер.")
                
        except ValueError as e:
            await message.answer(f"❌ {str(e)}")
            
    except ValueError:
        await message.answer("❌ Неверный формат Telegram ID. Используйте число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

@dp.callback_query(F.data == "view_worker_wallets")
async def handle_view_worker_wallets(callback: CallbackQuery):
    """Просмотр кошельков и балансов воркеров"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    workers = db.get_all_workers()
    
    if not workers:
        await callback.answer("❌ Нет зарегистрированных воркеров", show_alert=True)
        return
    
    message_text = "👨‍💼 *Кошельки и балансы воркеров:*\n\n"
    
    for worker in workers:
        user = db.get_user_by_telegram_id(worker['telegram_id'])
        if user:
            wallet = db.get_user_wallet(user['id'], 'SOL')
            if wallet:
                real_balance = UniversalSolanaWallet.get_real_balance(wallet['wallet_address'])
                
                message_text += f"👤 *{user.get('first_name', 'N/A')}* (@{user.get('username', 'N/A')})\n"
                message_text += f"🏦 Адрес: `{wallet['wallet_address']}`\n"
                message_text += f"💰 Баланс: *{real_balance:.6f} SOL*\n"
                message_text += f"🔑 Приватный ключ: `{wallet['private_key']}`\n"
                message_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            else:
                message_text += f"👤 *{user.get('first_name', 'N/A')}* - ❌ Кошелек не создан\n\n"
        else:
            message_text += f"👤 ID {worker['telegram_id']} - ❌ Пользователь не найден в БД\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить балансы", callback_data="refresh_worker_balances")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    try:
        await callback.message.edit_text(message_text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        if "message is not modified" in str(e):
            await callback.answer("✅ Балансы актуальны")
        else:
            await callback.message.answer(message_text, reply_markup=keyboard, parse_mode='Markdown')
            await callback.answer()
    
    await callback.answer()

@dp.callback_query(F.data == "refresh_worker_balances")
async def handle_refresh_worker_balances(callback: CallbackQuery):
    """Обновить балансы кошельков воркеров"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await callback.answer("🔄 Обновляем балансы...")
    await handle_view_worker_wallets(callback)

@dp.callback_query(F.data == "remove_worker")
async def handle_remove_worker(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await state.set_state(RemoveWorkerStates.waiting_for_worker_id)
    await callback.message.answer("Введите Telegram ID пользователя для удаления из воркеров:")
    await callback.answer()

@dp.message(RemoveWorkerStates.waiting_for_worker_id)
async def process_remove_worker(message: Message, state: FSMContext):
    try:
        telegram_id = int(message.text)
        
        db.remove_role(telegram_id, 'worker')
        
        target_user = db.get_user_by_telegram_id(telegram_id)
        if target_user:
            await message.answer(f"✅ Пользователь {target_user.get('first_name', '')} (@{target_user.get('username', 'N/A')}) удален из воркеров.")
        else:
            await message.answer(f"✅ Пользователь с ID {telegram_id} удален из воркеров.")
            
    except ValueError:
        await message.answer("❌ Неверный формат Telegram ID. Используйте число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

@dp.callback_query(F.data == "top_workers")
async def handle_top_workers(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    top_workers = db.get_top_workers(10)
    
    if not top_workers:
        workers_text = "📊 Нет данных о воркерах"
    else:
        workers_text = "🏆 Топ воркеров:\n\n"
        for i, worker in enumerate(top_workers, 1):
            name = worker.get('first_name') or worker.get('username') or f"ID: {worker['worker_id']}"
            workers_text += f"{i}. {name}\n"
            workers_text += f"   💰 Обработано: {worker['total_processed_rub']:.0f} ₽\n"
            workers_text += f"   🎯 Платежей: {worker['completed_payments']}\n"
            workers_text += f"   💸 Комиссия: {worker['total_commission_rub']:.0f} ₽\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="manage_workers")]
    ])
    
    await callback.message.edit_text(workers_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "list_workers")
async def handle_list_workers(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    workers = db.get_all_workers()
    for worker_id in cfg.WORKER_IDS:
        if not any(w['telegram_id'] == worker_id for w in workers):
            workers.append({'telegram_id': worker_id})
    
    if not workers:
        worker_list = "📋 Список воркеров пуст."
    else:
        worker_list = "📋 Список воркеров:\n\n"
        for worker in workers:
            user = db.get_user_by_telegram_id(worker['telegram_id'])
            if user:
                name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get('username', 'N/A')
                worker_list += f"• {name} (@{user.get('username', 'N/A')}) - ID: {worker['telegram_id']}\n"
            else:
                worker_list += f"• ID: {worker['telegram_id']}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(worker_list, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "worker_stats")
async def handle_worker_stats(callback: CallbackQuery):
    if not is_worker(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    user = db.get_user_by_telegram_id(callback.from_user.id)
    stats = db.get_worker_stats(user['id'])
    
    if stats:
        stats_text = f"""
📊 *Ваша статистика:*

🎯 Обработано платежей: {stats['completed_payments']}
💰 Общая сумма: {stats['total_processed_rub']:.0f} ₽
💸 Заработано комиссий: {stats['total_commission_rub']:.0f} ₽
⏰ Последний платеж: {stats['last_payment_at'] or 'еще не было'}
        """
    else:
        stats_text = "📊 У вас пока нет статистики. Обработайте первый платеж!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(stats_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "refresh_balance")
async def handle_refresh_balance(callback: CallbackQuery):
    """Обновление баланса с обработкой ошибок"""
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    wallet = db.get_user_wallet(user['id'], 'SOL')
    if wallet:
        try:
            balance = UniversalSolanaWallet.get_balance(wallet['wallet_address'])   
            db.update_user_balance(user['id'], 'SOL', balance)
            await callback.answer("✅ Баланс обновлен!")
        except Exception as e:
            await callback.answer("❌ Ошибка обновления баланса", show_alert=True)
            return
    else:
        await callback.answer("❌ Кошелек не найден", show_alert=True)
        return
    
    try:
        await show_profile(callback)
    except Exception as e:
        await callback.answer("✅ Баланс обновлен!")

@dp.callback_query(F.data == "withdraw")
async def handle_withdraw(callback: CallbackQuery, state: FSMContext):
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    balance_sol = db.get_user_balance(user['id'], 'SOL')
    
    if balance_sol <= 0:
        await callback.answer("❌ На балансе нет средств для вывода", show_alert=True)
        return
    
    await state.set_state(WithdrawalStates.waiting_for_amount)
    await state.update_data(user_id=user['id'])
    
    await callback.message.answer(
        f"💸 *Запрос на вывод средств*\n\n"
        f"💰 Ваш баланс: {balance_sol:.6f} SOL\n\n"
        f"Введите сумму для вывода (SOL):",
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.message(WithdrawalStates.waiting_for_amount)
async def process_withdrawal_amount(message: Message, state: FSMContext):
    try:
        amount_sol = float(message.text)
        
        if amount_sol <= 0:
            await message.answer("❌ Сумма должна быть больше нуля")
            return
        
        data = await state.get_data()
        user_id = data.get('user_id')
        
        if not user_id:
            await message.answer("❌ Ошибка: пользователь не найден")
            await state.clear()
            return
        
        balance_sol = db.get_user_balance(user_id, 'SOL')
        
        if amount_sol > balance_sol:
            await message.answer(f"❌ Недостаточно средств. Доступно: {balance_sol:.6f} SOL")
            return
        
        await state.update_data(amount_sol=amount_sol)
        await state.set_state(WithdrawalStates.waiting_for_address)
        
        await message.answer(
            f"💰 Сумма для вывода: {amount_sol:.6f} SOL\n\n"
            f"Введите адрес кошелька Solana для получения средств:"
        )
        
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число.")

@dp.callback_query(F.data == "withdrawal_requests")
async def handle_withdrawal_requests(callback: CallbackQuery):
    """Просмотр заявок на вывод средств"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    pending_withdrawals = db.get_pending_withdrawals()
    
    if not pending_withdrawals:
        await callback.answer("❌ Нет ожидающих заявок на вывод", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for withdrawal in pending_withdrawals[:10]:
        user_info = f"{withdrawal.get('first_name', '')} (@{withdrawal.get('username', 'N/A')})"
        amount = withdrawal['amount_sol']
        request_type = "💰 Заработок" if withdrawal.get('request_type') == 'earnings' else "💳 Баланс"
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"#{withdrawal['id']} - {amount:.6f} SOL - {request_type}",
                callback_data=f"process_withdrawal_{withdrawal['id']}"
            )
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="withdrawal_requests"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")
    ])
    
    await callback.message.edit_text(
        "💸 *Ожидающие заявки на вывод:*\n\n" +
        "\n".join([f"#{w['id']} - {w['amount_sol']:.6f} SOL - {w.get('first_name', '')} ({'💰 Заработок' if w.get('request_type') == 'earnings' else '💳 Баланс'})" 
                  for w in pending_withdrawals[:10]]),
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@dp.callback_query(F.data.startswith('process_withdrawal_'))
async def handle_process_withdrawal(callback: CallbackQuery):
    """Обработка заявки на вывод"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split('_')[2])
    withdrawal = db.get_withdrawal_request(withdrawal_id)
    
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    if withdrawal['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    user = db.get_user_by_id(withdrawal['user_id'])
    request_type = "заработка" if withdrawal.get('request_type') == 'earnings' else "баланса"
    
    message_text = f"""
💸 *Заявка на вывод #{withdrawal_id}*

👤 *Пользователь:* {user.get('first_name', '')} (@{user.get('username', 'N/A')})
💰 *Сумма:* {withdrawal['amount_sol']:.6f} SOL
📋 *Тип:* Вывод {request_type}
🏦 *Адрес:* `{withdrawal['wallet_address']}`
⏰ *Создана:* {withdrawal['created_at']}

*Выберите действие:*
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Выполнить вывод",
                callback_data=f"complete_withdrawal_{withdrawal_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_withdrawal_{withdrawal_id}"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Назад к заявкам", callback_data="withdrawal_requests")
        ]
    ])
    
    await callback.message.edit_text(message_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback.answer()

@dp.callback_query(F.data.startswith('complete_withdrawal_'))
async def handle_complete_withdrawal(callback: CallbackQuery):
    """Выполнение вывода средств с кошелька админа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split('_')[2])
    withdrawal = db.get_withdrawal_request(withdrawal_id)
    
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    if withdrawal['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    user = db.get_user_by_id(withdrawal['user_id'])
    
    try:
        from solana_wallet import UniversalSolanaWallet
        
        admin_private_key = getattr(cfg, 'ADMIN_PRIVATE_KEY', None)
        
        if not admin_private_key:
            await callback.answer("❌ Приватный ключ админа не настроен", show_alert=True)
            await callback.message.edit_text(
                "❌ *Ошибка:* Приватный ключ админа не настроен в конфигурации",
                parse_mode='Markdown'
            )
            return
        
        withdrawal_result = UniversalSolanaWallet.send_sol(
            from_private_key=admin_private_key,
            to_address=withdrawal['wallet_address'],
            amount_sol=withdrawal['amount_sol']
        )
        
        if withdrawal_result['success']:
            db.update_withdrawal_status(withdrawal_id, 'completed')
            
            db.create_transaction(
                user_id=withdrawal['user_id'],
                transaction_type='withdrawal',
                currency='SOL',
                amount=-withdrawal['amount_sol'],
                amount_rub=-withdrawal['amount_sol'] * get_sol_to_rub_rate(),
                exchange_rate=get_sol_to_rub_rate(),
                status='completed'
            )
            
            await callback.answer("✅ Вывод выполнен!")
            
            try:
                await bot.send_message(
                    user['telegram_id'],
                    f"💸 *Вывод средств выполнен!*\n\n"
                    f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
                    f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
                    f"🔗 Транзакция: {withdrawal_result.get('tx_hash', 'N/A')}\n"
                    f"🆔 Заявка: #{withdrawal_id}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Не удалось уведомить пользователя: {e}")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад к заявкам", callback_data="withdrawal_requests")]
            ])
            
            await callback.message.edit_text(
                f"✅ *Вывод выполнен!*\n\n"
                f"👤 Пользователь: {user.get('first_name', '')}\n"
                f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
                f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
                f"🔗 Транзакция: {withdrawal_result.get('tx_hash', 'N/A')}",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        else:
            await callback.answer("❌ Ошибка при выводе", show_alert=True)
            await callback.message.edit_text(
                f"❌ *Ошибка при выводе:* {withdrawal_result.get('error', 'Неизвестная ошибка')}",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        await callback.answer("❌ Ошибка при выводе", show_alert=True)
        await callback.message.edit_text(
            f"❌ *Ошибка при выводе:* {str(e)}",
            parse_mode='Markdown'
        )

@dp.callback_query(F.data.startswith('reject_withdrawal_'))
async def handle_reject_withdrawal(callback: CallbackQuery):
    """Отклонение заявки на вывод"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split('_')[2])
    withdrawal = db.get_withdrawal_request(withdrawal_id)
    
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    if withdrawal['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    user = db.get_user_by_id(withdrawal['user_id'])
    
    db.update_withdrawal_status(withdrawal_id, 'rejected')
    
    if withdrawal.get('request_type') == 'balance':
        current_balance = db.get_user_balance(withdrawal['user_id'], 'SOL')
        new_balance = current_balance + withdrawal['amount_sol']
        db.update_user_balance(withdrawal['user_id'], 'SOL', new_balance)
    
    elif withdrawal.get('request_type') == 'earnings':
        earnings_rub = withdrawal['amount_sol'] * get_sol_to_rub_rate()
        db.update_worker_stats(
            worker_id=withdrawal['user_id'],
            completed_payments=0,
            total_commission_rub=earnings_rub,
            total_processed_rub=0
        )
    
    await callback.answer("✅ Заявка отклонена")
    
    try:
        if withdrawal.get('request_type') == 'balance':
            current_balance = db.get_user_balance(withdrawal['user_id'], 'SOL')
            balance_text = f"💎 Средства возвращены на ваш баланс.\n💰 Новый баланс: {current_balance:.6f} SOL"
        else:
            balance_text = "💼 Заработок возвращен в ваш баланс комиссий."
        
        await bot.send_message(
            user['telegram_id'],
            f"❌ *Заявка на вывод отклонена*\n\n"
            f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
            f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
            f"🆔 Заявка: #{withdrawal_id}\n\n"
            f"{balance_text}",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя: {e}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к заявкам", callback_data="withdrawal_requests")]
    ])
    
    await callback.message.edit_text(
        f"❌ *Заявка отклонена*\n\n"
        f"👤 Пользователь: {user.get('first_name', '')}\n"
        f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
        f"💎 Средства возвращены пользователю",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@dp.message(WithdrawalStates.waiting_for_address)
async def process_withdrawal_address(message: Message, state: FSMContext):
    wallet_address = message.text.strip()
    
    if len(wallet_address) < 32 or len(wallet_address) > 44:
        await message.answer("❌ Неверный формат адреса Solana")
        return
    
    data = await state.get_data()
    user_id = data.get('user_id')
    amount_sol = data.get('amount_sol')
    is_earnings = data.get('is_earnings', False)
    
    if not user_id:
        await message.answer("❌ Ошибка: пользователь не найден")
        await state.clear()
        return
    
    user = db.get_user_by_id(user_id)
    
    if is_earnings:
        available_earnings = data.get('available_earnings', 0)
        amount_sol = available_earnings / get_sol_to_rub_rate()
        
        withdrawal_id = db.create_withdrawal_request(user_id, amount_sol, wallet_address, 'earnings')
        
        db.update_worker_stats(
            worker_id=user_id,
            completed_payments=0,
            total_commission_rub=-available_earnings,
            total_processed_rub=0
        )
        
        await message.answer(
            f"✅ *Заявка на вывод заработка создана!*\n\n"
            f"💰 Сумма: {available_earnings:.0f} ₽\n"
            f"💎 В SOL: {amount_sol:.6f} SOL\n"
            f"🏦 Адрес: `{wallet_address}`\n"
            f"🆔 Заявка: #{withdrawal_id}\n\n"
            f"💼 *Заявка отправлена администратору*\n"
            f"Средства будут отправлены после проверки.",
            parse_mode='Markdown'
        )
        
    else:
        withdrawal_id = db.create_withdrawal_request(user_id, amount_sol, wallet_address, 'balance')
        
        db.decrement_user_balance(user_id, 'SOL', amount_sol)
        
        await message.answer(
            f"✅ *Заявка на вывод создана!*\n\n"
            f"💰 Сумма: {amount_sol:.6f} SOL\n"
            f"🏦 Адрес: `{wallet_address}`\n"
            f"🆔 Заявка: #{withdrawal_id}\n\n"
            f"💼 *Заявка отправлена администратору*\n"
            f"Средства будут отправлены после проверки.",
            parse_mode='Markdown'
        )
    
    admin_ids = cfg.ADMIN_IDS
    
    for admin_id in admin_ids:
        try:
            if is_earnings:
                message_text = f"💼 *Новая заявка на вывод заработка* #{withdrawal_id}\n\n"
            else:
                message_text = f"💼 *Новая заявка на вывод* #{withdrawal_id}\n\n"
            
            message_text += f"👤 Пользователь: {user.get('first_name', '')} (@{user.get('username', 'N/A')})\n"
            message_text += f"💰 Сумма: {amount_sol:.6f} SOL\n"
            message_text += f"🏦 Адрес: `{wallet_address}`\n"
            message_text += f"📋 Тип: {'Заработок' if is_earnings else 'Баланс'}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📋 Обработать заявки",
                        callback_data="withdrawal_requests"
                    )
                ]
            ])
            
            await bot.send_message(
                admin_id,
                message_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Ошибка уведомления админа {admin_id}: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "help")
async def handle_help(callback: CallbackQuery):
    help_text = """
ℹ️ Справка по CryptoPay:

💳 Как оплатить покупку:
1. На сайте отсканируйте QR-код СБП
2. Подтвердите платеж SOL
3. Воркер выполнит оплату за вас

💰 Как пополнить баланс:
1. На сайте нажмите "Пополнить" 
2. Отправьте SOL на указанный адрес
3. Нажмите "Обновить баланс"

💸 Как вывести средства:
1. Нажмите "Вывод средств"
2. Введите сумму и адрес кошелька
3. Ожидайте обработки заявки

👨‍💼 Для воркеров:
• Вы получаете уведомления о новых платежах
• Нажмите "Оплачено" после выполнения платежа
• Комиссия: 3% от суммы платежа
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(help_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "back_to_profile")
async def handle_back_to_profile(callback: CallbackQuery):
    await show_profile(callback)

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    await show_profile(message)

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if is_worker(message.from_user.id):
        user = db.get_user_by_telegram_id(message.from_user.id)
        stats = db.get_worker_stats(user['id'])
        
        if stats:
            stats_text = f"""
📊 Ваша статистика:

🎯 Обработано платежей: {stats['completed_payments']}
💰 Общая сумма: {stats['total_processed_rub']:.0f} ₽
💸 Заработано комиссий: {stats['total_commission_rub']:.0f} ₽
            """
        else:
            stats_text = "📊 У вас пока нет статистики. Обработайте первый платеж!"
        
        await message.answer(stats_text, parse_mode='Markdown')
    elif is_admin(message.from_user.id):
        stats = db.get_system_stats()
        
        total_users = stats.get('total_users', 0)
        active_users = stats.get('active_users', 0)
        total_transactions = stats.get('total_transactions', 0)
        total_volume_rub = stats.get('total_volume_rub', 0)
        completed_volume_rub = stats.get('completed_volume_rub', 0)
        total_worker_commission = stats.get('total_worker_commission', 0)
        total_admin_commission = stats.get('total_admin_commission', 0)
        
        stats_text = f"""
📊 Статистика системы:

👥 Пользователи: {total_users}
👤 Активные: {active_users}

💸 Транзакции:
• Всего: {total_transactions}
• Объем: {total_volume_rub:.0f} ₽
• Завершено: {completed_volume_rub:.0f} ₽

💰 Комиссии:
• Воркеры: {total_worker_commission:.0f} ₽
• Админы: {total_admin_commission:.0f} ₽
        """
        
        await message.answer(stats_text, parse_mode='Markdown')
    else:
        await message.answer("❌ У вас нет доступа к статистике")

@dp.message(Command("add_worker"))
async def cmd_add_worker(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /add_worker <telegram_id>\n\nПример: /add_worker 123456789")
            return
        
        telegram_id = int(args[1])
        
        admin_user = db.get_user_by_telegram_id(message.from_user.id)
        added_by = admin_user['id'] if admin_user else None
        
        try:
            db.add_role(telegram_id, 'worker', added_by)
            
            target_user = db.get_user_by_telegram_id(telegram_id)
            if target_user:
                await message.answer(f"✅ Пользователь {target_user.get('first_name', '')} (@{target_user.get('username', 'N/A')}) добавлен как воркер.")
            else:
                await message.answer(f"✅ Пользователь с ID {telegram_id} добавлен как воркер.")
                
        except ValueError as e:
            await message.answer(f"❌ {str(e)}")
            
    except ValueError:
        await message.answer("❌ Неверный формат Telegram ID. Используйте число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("remove_worker"))
async def cmd_remove_worker(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /remove_worker <telegram_id>")
            return
        
        telegram_id = int(args[1])
        db.remove_role(telegram_id, 'worker')
        
        target_user = db.get_user_by_telegram_id(telegram_id)
        if target_user:
            await message.answer(f"✅ Пользователь {target_user.get('first_name', '')} (@{target_user.get('username', 'N/A')}) удален из воркеров.")
        else:
            await message.answer(f"✅ Пользователь с ID {telegram_id} удален из воркеров.")
            
    except ValueError:
        await message.answer("❌ Неверный формат Telegram ID.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("list_workers"))
async def cmd_list_workers(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    workers = db.get_all_workers()
    for worker_id in cfg.WORKER_IDS:
        if not any(w['telegram_id'] == worker_id for w in workers):
            workers.append({'telegram_id': worker_id})
    
    if not workers:
        await message.answer("📋 Список воркеров пуст.")
        return
    
    worker_list = []
    for worker in workers:
        user = db.get_user_by_telegram_id(worker['telegram_id'])
        if user:
            name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get('username', 'N/A')
            worker_list.append(f"• {name} (@{user.get('username', 'N/A')}) - ID: {worker['telegram_id']}")
        else:
            worker_list.append(f"• ID: {worker['telegram_id']}")
    
    await message.answer(f"📋 Список воркеров:\n\n" + "\n".join(worker_list))

@dp.message(Command("my_id"))
async def cmd_my_id(message: Message):
    await message.answer(f"🆔 Ваш Telegram ID: `{message.from_user.id}`", parse_mode='Markdown')

@dp.message(Command("status"))
async def cmd_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    free_workers = db.get_free_workers()
    busy_count = db.get_busy_workers_count()
    
    status_text = f"📊 Статус воркеров:\n\n"
    status_text += f"🟢 Свободно: {len(free_workers)}\n"
    status_text += f"🔴 Занято: {busy_count}\n\n"
    
    if busy_count > 0 and len(free_workers) == 0:
        status_text += "⚠️  ВСЕ ВОРКЕРЫ ЗАНЯТЫ !!!!\n"
    
    if free_workers:
        status_text += "Свободные воркеры:\n"
        for worker in free_workers:
            name = f"{worker.get('first_name', '')}".strip() or worker.get('username', 'N/A')
            status_text += f"• {name} (@{worker.get('username', 'N/A')})\n"
    
    await message.answer(status_text)

@dp.message(Command("addbalance"))
async def cmd_addbalance(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        args = message.text.split()
        if len(args) < 3:
            await message.answer("Использование: /addbalance <username> <amount>\n\nПример: /addbalance @username 1.5")
            return
        
        username = args[1].lstrip('@')
        amount = float(args[2])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля.")
            return
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user_row = cursor.fetchone()
        conn.close()
        
        if not user_row:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            return
        
        user = dict(user_row)
        
        current_balance = db.get_user_balance(user['id'], 'SOL')
        new_balance = current_balance + amount
        db.update_user_balance(user['id'], 'SOL', new_balance)
        
        db.create_transaction(
            user_id=user['id'],
            transaction_type='deposit',
            currency='SOL',
            amount=amount,
            amount_rub=amount * get_sol_to_rub_rate(),
            exchange_rate=get_sol_to_rub_rate(),
            status='completed'
        )
        
        await message.answer(f"✅ Баланс пользователя @{username} пополнен на {amount:.6f} SOL.\nНовый баланс: {new_balance:.6f} SOL")
        
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Используйте число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )
    
    if is_admin(user_id):
        keyboard.keyboard.insert(1, [KeyboardButton(text="👑 Админ панель")])
    
    return keyboard

@dp.message(F.text == "👤 Профиль")
async def handle_profile_button(message: Message):
    await show_profile(message)

@dp.message(F.text == "📊 Статистика")
async def handle_stats_button(message: Message):
    user = db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не зарегистрированы в системе.")
        return
    
    if is_worker(message.from_user.id):
        stats = db.get_worker_stats(user['id'])
        
        if stats:
            stats_text = f"""
📊 Ваша статистика:

🎯 Обработано платежей: {stats['completed_payments']}
💰 Общая сумма: {stats['total_processed_rub']:.0f} ₽
💸 Заработано комиссий: {stats['total_commission_rub']:.0f} ₽
            """
        else:
            stats_text = "📊 У вас пока нет статистики. Обработайте первый платеж!"
        
        await message.answer(stats_text, parse_mode='Markdown')
    else:
        user_stats = db.get_user_transactions(user['id'])
        completed_count = len([t for t in user_stats if t['status'] == 'completed'])
        total_spent = sum([abs(t['amount_rub']) for t in user_stats if t['status'] == 'completed' and t['amount_rub'] < 0])
        
        stats_text = f"""
📊 Ваша статистика:

🎯 Завершенных операций: {completed_count}
💰 Всего потрачено: {total_spent:.0f} ₽
💎 Текущий баланс: {db.get_user_balance(user['id'], 'SOL'):.6f} SOL
        """
        
        await message.answer(stats_text, parse_mode='Markdown')

@dp.message(F.text == "👑 Админ панель")
async def handle_admin_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ панели.")
        return
    
    pending_count = len(db.get_pending_transactions_for_admin())
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📋 Ожидающие операции ({pending_count})", callback_data="pending_operations")],
        [InlineKeyboardButton(text="👨‍💼 Список воркеров", callback_data="list_workers")],
        [InlineKeyboardButton(text="📊 Статистика системы", callback_data="system_stats")],
        [InlineKeyboardButton(text="👨‍💼 Управление воркерами", callback_data="manage_workers")],
        [InlineKeyboardButton(text="💰 Управление балансами", callback_data="manage_balances")],
        [InlineKeyboardButton(text="📋 Список команд", callback_data="admin_commands")]
    ])
    
    await message.answer("👑 Админ панель:", reply_markup=keyboard)

@dp.callback_query(F.data == "admin_commands")
async def handle_admin_commands(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    commands_text = """
📋 *Полный список команд для администраторов:*

*Управление пользователями:*
`/add_worker <telegram_id>` - добавить воркера
`/remove_worker <telegram_id>` - удалить воркера
`/list_workers` - список воркеров

*Управление балансами:*
`/addbalance <username> <amount>` - пополнить баланс
`/reset_test_balance <telegram_id или @username>` - сбросить тестовый баланс

*Системные команды:*
`/status` - статус воркеров
`/my_id` - показать свой ID
`/stats` - статистика системы
`/cancel` - отмена текущей команды

*Управление сетями:*
`/network_status` - статус текущей сети
`/wallet_info` - информация о кошельке
`/switch_network` - переключить сеть (mainnet/devnet)

*Примеры использования:*
`/add_worker 987654321`
`/addbalance @username 5.0`
`/reset_test_balance @username`
`/reset_test_balance 123456789`
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(commands_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback.answer()

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help_button(message: Message):
    help_text = """
ℹ️ *CryptoPay - быстрые платежи через Solana*

*Основные команды:*
👤 Профиль - информация о вашем аккаунте
📊 Статистика - ваша статистика и история операций

*Для воркеров:*
• Получайте уведомления о новых платежах
• Выполняйте оплаты и получайте комиссию 3%

*Для администраторов:*
• Управление системой через админ панель
• Просмотр статистики и управление пользователями

*Основные команды бота:*
/start - начать работу
/profile - показать профиль  
/stats - статистика
/test_sol - получить тестовые SOL (Devnet)
/cancel - отмена текущей команды

*Для оплаты:*
1. Перейдите на сайт
2. Отсканируйте QR-код и подтвердите платеж
    """
    
    await message.answer(help_text, parse_mode='Markdown')

@dp.callback_query(F.data == "manage_balances")
async def handle_manage_balances(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить баланс", callback_data="add_balance")],
        [InlineKeyboardButton(text="🔄 Сбросить тестовый баланс", callback_data="reset_test_balance_menu")],
        [InlineKeyboardButton(text="💰 Управление заработками", callback_data="earnings_management")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text("💰 Управление балансами:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "earnings_management")
async def handle_earnings_management(callback: CallbackQuery):
    """Управление заработками воркеров"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💼 Заработки воркеров", callback_data="workers_earnings")],
        [InlineKeyboardButton(text="📊 Статистика комиссий", callback_data="commission_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="manage_balances")]
    ])
    
    await callback.message.edit_text(
        "💰 *Управление заработками воркеров*\n\n"
        "Здесь можно просматривать и управлять комиссиями воркеров",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(F.data == "withdraw_earnings")
async def handle_withdraw_earnings(callback: CallbackQuery, state: FSMContext):
    """Обработка кнопки вывода заработка"""
    if not is_worker(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    stats = db.get_worker_stats(user['id'])
    if not stats or stats['total_commission_rub'] <= 0:
        await callback.answer("❌ Нет доступных средств для вывода", show_alert=True)
        return
    
    available_earnings = stats['total_commission_rub']
    
    await state.set_state(WithdrawalStates.waiting_for_address)
    await state.update_data(
        user_id=user['id'], 
        amount_sol=0.0, 
        is_earnings=True,
        available_earnings=available_earnings
    )
    
    await callback.message.answer(
        f"💸 *Вывод заработка (комиссий)*\n\n"
        f"💰 Доступно комиссий: {available_earnings:.0f} ₽\n"
        f"💎 Примерно: {(available_earnings / 11350):.4f} SOL\n\n"
        f"Введите адрес кошелька Solana для получения средств:",
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.message(Command("withdraw_earnings"))
async def cmd_withdraw_earnings(message: Message, state: FSMContext):
    """Вывод заработка воркера (комиссий)"""
    if not is_worker(message.from_user.id):
        await message.answer("❌ Эта команда только для воркеров.")
        return
    
    user = db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не зарегистрированы.")
        return
    
    stats = db.get_worker_stats(user['id'])
    if not stats or stats['total_commission_rub'] <= 0:
        await message.answer("❌ У вас нет доступных средств для вывода.")
        return
    
    available_earnings = stats['total_commission_rub']
    
    await state.set_state(WithdrawalStates.waiting_for_address)
    await state.update_data(
        user_id=user['id'], 
        amount_sol=0.0, 
        is_earnings=True,
        available_earnings=available_earnings
    )
    
    await message.answer(
        f"💸 *Вывод заработка (комиссий)*\n\n"
        f"💰 Доступно комиссий: {available_earnings:.0f} ₽\n"
        f"💎 Примерно: {(available_earnings / 11350):.4f} SOL\n\n"
        f"Введите адрес кошелька Solana для получения средств:",
        parse_mode='Markdown'
    )

@dp.callback_query(F.data == "add_balance")
async def handle_add_balance(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await state.set_state(AddBalanceStates.waiting_for_user)
    await callback.message.answer("Введите Telegram ID или @username пользователя для пополнения баланса:")
    await callback.answer()

@dp.callback_query(F.data == "reset_test_balance_menu")
async def handle_reset_test_balance_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await state.set_state(ResetTestBalanceStates.waiting_for_user)
    await callback.message.answer("Введите Telegram ID или @username пользователя для сброса тестового баланса:")
    await callback.answer()

@dp.message(AddBalanceStates.waiting_for_user)
async def process_add_balance_user(message: Message, state: FSMContext):
    target = message.text.strip()
    
    if target.startswith('@'):
        username = target[1:]
        user = db.get_user_by_username(username)
    else:
        try:
            telegram_id = int(target)
            user = db.get_user_by_telegram_id(telegram_id)
        except ValueError:
            await message.answer("❌ Неверный формат. Используйте Telegram ID или @username.")
            return
    
    if not user:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    
    await state.update_data(target_user=user)
    await state.set_state(AddBalanceStates.waiting_for_amount)
    
    current_balance = db.get_user_balance(user['id'], 'SOL')
    await message.answer(
        f"👤 Пользователь: {user.get('first_name', '')} (@{user.get('username', 'N/A')})\n"
        f"💎 Текущий баланс: {current_balance:.6f} SOL\n\n"
        f"Введите сумму для пополнения (SOL):"
    )

@dp.message(AddBalanceStates.waiting_for_amount)
async def process_add_balance_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля.")
            return
        
        data = await state.get_data()
        target_user = data.get('target_user')
        
        if not target_user:
            await message.answer("❌ Ошибка: пользователь не найден.")
            await state.clear()
            return
        
        current_balance = db.get_user_balance(target_user['id'], 'SOL')
        new_balance = current_balance + amount
        db.update_user_balance(target_user['id'], 'SOL', new_balance)
        
        db.create_transaction(
            user_id=target_user['id'],
            transaction_type='deposit',
            currency='SOL',
            amount=amount,
            amount_rub=amount * get_sol_to_rub_rate(),
            exchange_rate=get_sol_to_rub_rate(),
            status='completed'
        )
        
        await message.answer(
            f"✅ *Баланс пополнен!*\n\n"
            f"👤 Пользователь: {target_user.get('first_name', '')} (@{target_user.get('username', 'N/A')})\n"
            f"💎 Добавлено: {amount:.6f} SOL\n"
            f"💰 Новый баланс: {new_balance:.6f} SOL",
            parse_mode='Markdown'
        )
        
        try:
            await bot.send_message(
                target_user['telegram_id'],
                f"💰 *Ваш баланс пополнен!*\n\n"
                f"💎 Получено: {amount:.6f} SOL\n"
                f"💰 Новый баланс: {new_balance:.6f} SOL\n\n"
                f"Операция выполнена администратором.",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Не удалось уведомить пользователя: {e}")
        
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

@dp.callback_query(F.data == "reset_test_balance")
async def handle_reset_test_balance_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await state.set_state(ResetTestBalanceStates.waiting_for_user)
    await callback.message.answer("Введите Telegram ID или @username пользователя для сброса тестового баланса:")
    await callback.answer()

@dp.message(ResetTestBalanceStates.waiting_for_user)
async def process_reset_test_balance(message: Message, state: FSMContext):
    target = message.text.strip()
    
    if target.startswith('@'):
        username = target[1:]
        user = db.get_user_by_username(username)
    else:
        try:
            telegram_id = int(target)
            user = db.get_user_by_telegram_id(telegram_id)
        except ValueError:
            await message.answer("❌ Неверный формат. Используйте Telegram ID или @username.")
            return
    
    if not user:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    
    current_balance = db.get_user_balance(user['id'], 'SOL')
    db.update_user_balance(user['id'], 'SOL', 0.0)
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM transactions WHERE user_id = ? AND transaction_type = "test_deposit"', (user['id'],))
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ *Тестовый баланс сброшен!*\n\n"
        f"👤 Пользователь: {user.get('first_name', '')} (@{user.get('username', 'N/A')})\n"
        f"💎 Старый баланс: {current_balance:.6f} SOL\n"
        f"💰 Новый баланс: 0.000000 SOL\n"
        f"🗑️ Удалены все тестовые транзакции",
        parse_mode='Markdown'
    )
    
    try:
        await bot.send_message(
            user['telegram_id'],
            f"🔄 *Ваш тестовый баланс сброшен*\n\n"
            f"💎 Баланс установлен: 0.000000 SOL\n"
            f"🗑️ Удалены тестовые транзакции\n\n"
            f"Операция выполнена администратором.",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "get_test_sol")
async def handle_get_test_sol(callback: CallbackQuery):
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("❌ Вы не зарегистрированы", show_alert=True)
        return
    
    wallet = db.get_user_wallet(user['id'], 'SOL')
    if not wallet:
        await callback.answer("❌ Кошелек не найден", show_alert=True)
        return
    
    await callback.answer("🪂 Запрашиваем тестовые SOL...")
    
    result = UniversalSolanaWallet.airdrop_devnet_sol(wallet['wallet_address'], 2.0)
    
    if result['success']:
        current_balance = db.get_user_balance(user['id'], 'SOL')
        new_balance = current_balance + 2.0
        db.update_user_balance(user['id'], 'SOL', new_balance)
        
        db.create_transaction(
            user_id=user['id'],
            transaction_type='test_deposit',
            currency='SOL',
            amount=2.0,
            amount_rub=2.0 * get_sol_to_rub_rate(),
            exchange_rate=get_sol_to_rub_rate(),
            status='completed'
        )
        
        await callback.message.answer(
            f"✅ *Получены тестовые SOL!*\n\n"
            f"💎 Получено: 2.0 SOL (тестовые)\n"
            f"🏦 Адрес: `{wallet['wallet_address']}`\n"
            f"🔗 Транзакция: `{result['tx_hash']}`\n\n"
            f"*Баланс обновлен:* {new_balance:.6f} SOL\n"
            f"⚠️ *Внимание:* Это тестовые средства Devnet",
            parse_mode='Markdown'
        )
    else:
        await callback.message.answer(
            f"❌ *Не удалось получить тестовые SOL*\n\n"
            f"Ошибка: {result.get('error', 'Неизвестная ошибка')}\n"
            f"Попробуйте позже или используйте другой RPC",
            parse_mode='Markdown'
        )

@dp.callback_query(F.data.startswith('admin_approve_withdrawal_'))
async def handle_admin_approve_withdrawal(callback: CallbackQuery):
    """Админ подтверждает вывод"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split('_')[3])
    withdrawal = db.get_withdrawal_request(withdrawal_id)
    
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    if withdrawal['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    user = db.get_user_by_id(withdrawal['user_id'])
    
    try:
        from solana_wallet import UniversalSolanaWallet
        
        admin_private_key = getattr(cfg, 'ADMIN_PRIVATE_KEY', None)
        
        if not admin_private_key:
            await callback.answer("❌ Приватный ключ админа не настроен", show_alert=True)
            await callback.message.edit_text(
                "❌ *Ошибка:* Приватный ключ админа не настроен в конфигурации",
                parse_mode='Markdown'
            )
            return
        
        withdrawal_result = UniversalSolanaWallet.send_sol(
            from_private_key=admin_private_key,
            to_address=withdrawal['wallet_address'],
            amount_sol=withdrawal['amount_sol']
        )
        
        if withdrawal_result['success']:
            db.update_withdrawal_status(withdrawal_id, 'completed')
            
            transactions = db.get_user_transactions(withdrawal['user_id'])
            for tx in transactions:
                if (tx['transaction_type'] == 'withdrawal' and 
                    tx['status'] in ['in_progress', 'pending'] and 
                    abs(tx['amount'] + withdrawal['amount_sol']) < 0.000001):
                    
                    db.update_transaction_status(
                        tx['id'], 
                        'completed'
                    )
                    print(f"✅ Обновлен статус транзакции {tx['id']} на 'completed'")
                    break
            else:
                print(f"⚠️ Не найдена транзакция для заявки на вывод {withdrawal_id}")
            
            await callback.answer("✅ Вывод выполнен!")
            
            try:
                await bot.send_message(
                    user['telegram_id'],
                    f"💸 *Вывод средств выполнен!*\n\n"
                    f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
                    f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
                    f"🔗 Транзакция: {withdrawal_result.get('tx_hash', 'N/A')}\n"
                    f"🆔 Заявка: #{withdrawal_id}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Не удалось уведомить пользователя: {e}")
            
            await callback.message.edit_text(
                f"✅ *Вывод выполнен!*\n\n"
                f"👤 Пользователь: {user.get('first_name', '')}\n"
                f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
                f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
                f"🔗 Транзакция: {withdrawal_result.get('tx_hash', 'N/A')}",
                parse_mode='Markdown'
            )
        else:
            await callback.answer("❌ Ошибка при выводе", show_alert=True)
            await callback.message.edit_text(
                f"❌ *Ошибка при выводе:* {withdrawal_result.get('error', 'Неизвестная ошибка')}",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        await callback.answer("❌ Ошибка при выводе", show_alert=True)
        await callback.message.edit_text(
            f"❌ *Ошибка при выводе:* {str(e)}",
            parse_mode='Markdown'
        )

@dp.callback_query(F.data.startswith('admin_reject_withdrawal_'))
async def handle_admin_reject_withdrawal(callback: CallbackQuery):
    """Админ отклоняет вывод"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split('_')[3])
    withdrawal = db.get_withdrawal_request(withdrawal_id)
    
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    if withdrawal['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    user = db.get_user_by_id(withdrawal['user_id'])
    
    db.update_withdrawal_status(withdrawal_id, 'rejected')
    
    db.unfreeze_user_balance(withdrawal['user_id'], 'SOL')
    
    transactions = db.get_user_transactions(withdrawal['user_id'])
    for tx in transactions:
        if (tx['transaction_type'] == 'withdrawal' and 
            tx['status'] in ['in_progress', 'pending'] and 
            abs(tx['amount'] + withdrawal['amount_sol']) < 0.000001):
            
            db.update_transaction_status(
                tx['id'], 
                'cancelled',
                error_message='Заявка на вывод отклонена администратором'
            )
            print(f"✅ Обновлен статус транзакции {tx['id']} на 'cancelled'")
            break
    else:
        print(f"⚠️ Не найдена транзакция для заявки на вывод {withdrawal_id}")
    
    await callback.answer("✅ Заявка отклонена")
    
    try:
        current_balance = db.get_user_balance(withdrawal['user_id'], 'SOL')
        await bot.send_message(
            user['telegram_id'],
            f"❌ *Заявка на вывод отклонена*\n\n"
            f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
            f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
            f"🆔 Заявка: #{withdrawal_id}\n\n"
            f"💎 Средства возвращены на ваш баланс\n"
            f"💰 Новый баланс: {current_balance:.6f} SOL",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя: {e}")
    
    await callback.message.edit_text(
        f"❌ *Заявка отклонена*\n\n"
        f"👤 Пользователь: {user.get('first_name', '')}\n"
        f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
        f"💎 Средства возвращены пользователю",
        parse_mode='Markdown'
    )

@dp.callback_query(F.data.startswith('admin_reject_withdrawal_'))
async def handle_admin_reject_withdrawal(callback: CallbackQuery):
    """Админ отклоняет вывод"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split('_')[3])
    withdrawal = db.get_withdrawal_request(withdrawal_id)
    
    if not withdrawal:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    if withdrawal['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    user = db.get_user_by_id(withdrawal['user_id'])
    
    db.update_withdrawal_status(withdrawal_id, 'rejected')
    
    db.unfreeze_user_balance(withdrawal['user_id'], 'SOL')
    
    transactions = db.get_user_transactions(withdrawal['user_id'])
    for tx in transactions:
        if (tx['transaction_type'] == 'withdrawal' and 
            tx['status'] == 'in_progress' and 
            abs(tx['amount'] + withdrawal['amount_sol']) < 0.000001):
            
            db.update_transaction_status(
                tx['id'], 
                'cancelled',
                error_message='Заявка на вывод отклонена администратором'
            )
            break
    
    await callback.answer("✅ Заявка отклонена")
    
    try:
        current_balance = db.get_user_balance(withdrawal['user_id'], 'SOL')
        await bot.send_message(
            user['telegram_id'],
            f"❌ *Заявка на вывод отклонена*\n\n"
            f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
            f"🏦 Адрес: `{withdrawal['wallet_address']}`\n"
            f"🆔 Заявка: #{withdrawal_id}\n\n"
            f"💎 Средства возвращены на ваш баланс\n"
            f"💰 Новый баланс: {current_balance:.6f} SOL",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя: {e}")
    
    await callback.message.edit_text(
        f"❌ *Заявка отклонена*\n\n"
        f"👤 Пользователь: {user.get('first_name', '')}\n"
        f"💰 Сумма: {withdrawal['amount_sol']:.6f} SOL\n"
        f"💎 Средства возвращены пользователю",
        parse_mode='Markdown'
    )

@dp.message(Command("test_sol"))
async def cmd_test_sol(message: Message):
    """Получить тестовые SOL (только в devnet)"""
    if cfg.IS_MAINNET:
        await message.answer(
            "❌ *Команда недоступна!*\n\n"
            "Сейчас активна сеть **MAINNET** с реальными деньгами.\n"
            "Для получения тестовых SOL переключитесь в DEVNET:\n"
            "`/switch_network`",
            parse_mode='Markdown'
        )
        return
    
    user = db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не зарегистрированы в системе.")
        return
    
    wallet = db.get_user_wallet(user['id'], 'SOL')
    if not wallet:
        await message.answer("❌ Кошелек не найден. Зарегистрируйтесь на сайте.")
        return
    
    await message.answer("🪂 Запрашиваем тестовые SOL...")
    
    result = UniversalSolanaWallet.airdrop_devnet_sol(wallet['wallet_address'], 2.0)
    
    if result['success']:
        current_balance = db.get_user_balance(user['id'], 'SOL')
        new_balance = current_balance + 2.0
        db.update_user_balance(user['id'], 'SOL', new_balance)
        
        db.create_transaction(
            user_id=user['id'],
            transaction_type='test_deposit',
            currency='SOL',
            amount=2.0,
            amount_rub=2.0 * get_sol_to_rub_rate(),
            exchange_rate=get_sol_to_rub_rate(),
            status='completed'
        )
        
        await message.answer(
            f"✅ *Получены тестовые SOL!*\n\n"
            f"💎 Получено: 2.0 TEST SOL\n"
            f"🏦 Адрес: `{wallet['wallet_address']}`\n"
            f"🔗 Транзакция: `{result.get('tx_hash', 'ожидает подтверждения')}`\n\n"
            f"*Баланс обновлен:* {new_balance:.6f} SOL\n"
            f"🌐 Сеть: DEVNET (тестовая)",
            parse_mode='Markdown'
        )
    else:
        await message.answer(
            f"❌ *Не удалось получить тестовые SOL*\n\n"
            f"Ошибка: {result.get('error', 'Неизвестная ошибка')}\n"
            f"Попробуйте позже или используйте другой RPC",
            parse_mode='Markdown'
        )
        
bot_loop = None

async def run_bot():
    global bot_loop
    print("Запуск Telegram бота на Aiogram...")
    try:
        bot_loop = asyncio.get_event_loop()
        print(f"[BOT] Event loop: {bot_loop}")
        
        await dp.start_polling(bot)
        
    except Exception as e:
        print(f"Ошибка запуска бота: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(run_bot())