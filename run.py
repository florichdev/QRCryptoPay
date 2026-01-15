"""
Главный файл запуска CryptoPay
Запускает веб-приложение и Telegram бота одновременно
"""

import asyncio
import threading
import time
import ssl
import os
import cfg
from app import app
from bot import run_bot, send_payment_to_workers
from database import Database

def check_ssl_files():
    """Проверяет наличие SSL файлов"""
    cert_path = 'ssl/localhost.crt'
    key_path = 'ssl/localhost.key'
    
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print("❌ SSL файлы не найдены! Создайте их командой: python create_ssl.py")
        return False
    return True

def run_web_app():
    """Запустить веб-приложение с HTTPS"""
    print("Запуск веб-приложения...")
    
    if check_ssl_files():
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.load_cert_chain('ssl/localhost.crt', 'ssl/localhost.key')
        print(f"🚀 Запуск сервера с HTTPS на {cfg.WEB_HOST}:{cfg.WEB_PORT}")
        app.run(host=cfg.WEB_HOST, port=cfg.WEB_PORT, ssl_context=context, debug=cfg.DEBUG, use_reloader=False)
    else:
        print("⚠️ Запуск без HTTPS")
        app.run(host=cfg.WEB_HOST, port=cfg.WEB_PORT, debug=cfg.DEBUG, use_reloader=False)

async def check_pending_payments():
    """Периодически проверять новые платежи и отправлять их воркерам"""
    from bot import bot_loop
    import asyncio
    
    db = Database()
    processed_ids = set()
    
    await asyncio.sleep(5)
    
    while True:
        try:
            if not bot_loop or not bot_loop.is_running():
                await asyncio.sleep(5)
                continue
            
            pending_payments = db.get_pending_payments()
            
            for payment in pending_payments:
                payment_id = payment['id']
                transaction_id = payment['transaction_id']
                
                if payment_id not in processed_ids:
                    transaction = db.get_transaction(transaction_id)
                    
                    if transaction and transaction['status'] == 'pending':
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                send_payment_to_workers(
                                    transaction_id=transaction_id,
                                    qr_code_data=payment['qr_code_data'],
                                    qr_code_image=payment['qr_code_image'],
                                    user_info=payment['user_info'],
                                    amount_rub=payment['amount_rub'] or 0
                                ),
                                bot_loop
                            )
                            processed_ids.add(payment_id)
                        except Exception as e:
                            print(f"[PAYMENT_CHECKER] Ошибка отправки платежа {transaction_id}: {e}")
            
            if len(processed_ids) > 1000:
                processed_ids.clear()
                
        except Exception as e:
            print(f"[PAYMENT_CHECKER] Ошибка проверки платежей: {e}")
            import traceback
            traceback.print_exc()
        
        await asyncio.sleep(5)

def run_payment_checker():
    """Запустить проверку платежей в отдельном event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_pending_payments())

def run_telegram_bot():
    """Запустить Telegram бота"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    print("=" * 50)
    print("CryptoPay - Запуск системы")
    print("=" * 50)
    
    if check_ssl_files():
        print(f"Веб-приложение: https://{cfg.WEB_HOST}:{cfg.WEB_PORT}")
    else:
        print(f"Веб-приложение: http://{cfg.WEB_HOST}:{cfg.WEB_PORT}")
        
    print(f"Telegram бот: запускается...")
    print("=" * 50)
    
    db_check = Database()
    workers = db_check.get_all_workers()
    admins = db_check.get_all_admins()
    
    worker_ids = [w['telegram_id'] for w in workers] + cfg.WORKER_IDS
    admin_ids = [a['telegram_id'] for a in admins] + cfg.ADMIN_IDS
    
    print(f"Администраторы: {list(set(admin_ids)) if admin_ids else 'НЕТ'}")
    print(f"Воркеры: {list(set(worker_ids)) if worker_ids else 'НЕТ'}")
    
    if not worker_ids and not admin_ids:
        print("⚠️  ВНИМАНИЕ: Нет воркеров и админов! Добавьте их через команды бота или в cfg.py")
    elif not worker_ids:
        print("⚠️  ВНИМАНИЕ: Нет воркеров! Добавьте их командой /add_worker в боте")
    
    print("=" * 50)
    
    payment_thread = threading.Thread(target=run_payment_checker, daemon=True)
    payment_thread.start()
    
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    time.sleep(3)
    
    print("Система запущена и готова к работе")
    print("=" * 50)
    
    run_web_app()