"""
Модуль для отправки уведомлений через Telegram бота
"""

import asyncio
import cfg
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from solana_wallet import UniversalSolanaWallet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()

async def send_withdrawal_notification_async(withdrawal_id, user_id, user_name, user_username, user_wallet, to_wallet, amount_sol, amount_rub, transaction_id):
    """Асинхронная отправка уведомления о выводе - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        bot = Bot(token=cfg.TELEGRAM_BOT_TOKEN)
        
        from database import Database
        db = Database()
        user = db.get_user_by_id(user_id)
        if user:
            user_balance_sol = db.get_user_balance(user_id, 'SOL')
        else:
            user_balance_sol = 0
        
        message_text = f"""
💸 НОВАЯ ЗАЯВКА НА ВЫВОД #{withdrawal_id}

👤 Пользователь: {user_name} (@{user_username})
💰 Сумма: {amount_sol:.6f} SOL ({amount_rub:.0f} ₽)
💳 Текущий баланс: {user_balance_sol:.6f} SOL

🏦 Кошелек пользователя: 
{user_wallet}

🎯 Кошелек получателя: 
{to_wallet}

📊 Данные:
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
                    reply_markup=keyboard
                )
                sent_count += 1
                logger.info(f"✅ Withdrawal notification sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"❌ Error sending to admin {admin_id}: {e}")
                
        logger.info(f"📤 Sent {sent_count}/{len(cfg.ADMIN_IDS)} withdrawal notifications")
        
        await bot.session.close()
        
        return sent_count
                
    except Exception as e:
        logger.error(f"❌ Error in send_withdrawal_notification_async: {e}")
        return 0
    
def send_withdrawal_notification_sync(withdrawal_id, user_id, user_name, user_username, user_wallet, to_wallet, amount_sol, amount_rub, transaction_id):
    """Синхронная обертка для отправки уведомления о выводе"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                send_withdrawal_notification_async(
                    withdrawal_id, user_id, user_name, user_username, 
                    user_wallet, to_wallet, amount_sol, amount_rub, transaction_id
                )
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Error in send_withdrawal_notification_sync: {e}")
        return 0

async def send_payment_notification_async(transaction_id, qr_code_data, qr_code_image, user_info, amount_rub, worker_earnings_sol=None, frozen_amount_sol=None):
    """Асинхронная отправка уведомления о платеже - ИСПРАВЛЕННАЯ ВЕРСИЯ БЕЗ USERNAME"""
    try:
        import json
        import base64
        from aiogram.types import BufferedInputFile
        
        bot = Bot(token=cfg.TELEGRAM_BOT_TOKEN)
        user_data = json.loads(user_info)
        
        payment_url = ""
        if 'https://' in qr_code_data:
            payment_url = qr_code_data
        elif qr_code_data.startswith('ST00012'):
            payment_url = f"https://qr.nspk.ru/proxy?qr={qr_code_data}"
        
        worker_earnings_display = worker_earnings_sol or 0
        
        from database import Database
        db = Database()
        user_wallet = db.get_user_wallet(user_data['user_id'], 'SOL')
        if user_wallet:
            user_balance_sol = UniversalSolanaWallet.get_real_balance(user_wallet['wallet_address'])
        else:
            user_balance_sol = 0
            
        balance_status = "✅ хватает" if user_balance_sol >= (frozen_amount_sol or 0) else "❌ не хватает"
        
        worker_message = f"""
🔔 Новый платеж

💰 Сумма к оплате: {amount_rub:.2f} ₽
💎 Заработок воркера: {worker_earnings_display:.6f} SOL (5%)
💳 Баланс пользователя: {balance_status}

ID транзакции: {transaction_id}

Для оплаты:
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
🔔 Новый платеж

💰 Сумма к оплате: {amount_rub:.2f} ₽
💎 Воркер получит: {worker_earnings_display:.6f} SOL (5%)
👑 Админ получит: {worker_earnings_display:.6f} SOL (5%)
💳 Баланс пользователя: {user_balance_sol:.6f} SOL ({balance_status})

ID транзакции: {transaction_id}
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
                            reply_markup=worker_keyboard
                        )
                    except Exception as e:
                        print(f"Ошибка отправки фото воркеру {worker_id}: {e}")
                        await bot.send_message(
                            chat_id=worker_id,
                            text=worker_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                            reply_markup=worker_keyboard
                        )
                else:
                    await bot.send_message(
                        chat_id=worker_id,
                        text=worker_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                        reply_markup=worker_keyboard
                    )
                
                sent_count += 1
                logger.info(f"✅ Payment notification sent to worker {worker_id}")
                    
            except Exception as e:
                logger.error(f"❌ Error sending to worker {worker_id}: {e}")
        
        for admin_id in cfg.ADMIN_IDS:
            try:
                if qr_code_image:
                    try:
                        image_data = base64.b64decode(qr_code_image)
                        await bot.send_photo(
                            chat_id=admin_id,
                            photo=BufferedInputFile(image_data, filename='qr_code.png'),
                            caption=admin_message,
                            reply_markup=admin_keyboard
                        )
                    except Exception as e:
                        print(f"Ошибка отправки фото админу {admin_id}: {e}")
                        await bot.send_message(
                            chat_id=admin_id,
                            text=admin_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                            reply_markup=admin_keyboard
                        )
                else:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_message + f"\n\n🔗 Ссылка для оплаты: {payment_url}",
                        reply_markup=admin_keyboard
                    )
                
                sent_count += 1
                logger.info(f"✅ Payment notification sent to admin {admin_id}")
                    
            except Exception as e:
                logger.error(f"❌ Error sending to admin {admin_id}: {e}")
        
        await bot.session.close()
        
        logger.info(f"📤 Sent {sent_count} payment notifications total")
        print(f"📊 Balance info: user_balance={user_balance_sol:.6f} SOL, required={frozen_amount_sol:.6f} SOL, status={balance_status}")
        return sent_count
        
    except Exception as e:
        logger.error(f"❌ Error in send_payment_notification_async: {e}")
        return 0
          
def send_payment_notification_sync(transaction_id, qr_code_data, qr_code_image, user_info, amount_rub, worker_earnings_sol=None, frozen_amount_sol=None):
    """Синхронная обертка для отправки уведомления о платеже"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                send_payment_notification_async(
                    transaction_id, qr_code_data, qr_code_image, user_info, 
                    amount_rub, worker_earnings_sol, frozen_amount_sol
                )
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Error in send_payment_notification_sync: {e}")
        return 0