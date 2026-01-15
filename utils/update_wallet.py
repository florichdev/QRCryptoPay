import sqlite3
import sys

def update_wallet(user_id, new_address, new_private_key):
    conn = sqlite3.connect('cryptopay.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE wallets 
        SET wallet_address = ?, private_key = ?
        WHERE user_id = ? AND currency = 'SOL'
    ''', (new_address, new_private_key, user_id))
    
    conn.commit()
    conn.close()
    print(f"✅ Кошелек пользователя {user_id} обновлен")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Использование: python update_wallet.py <user_id> <new_address> <new_private_key>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    new_address = sys.argv[2]
    new_private_key = sys.argv[3]
    
    update_wallet(user_id, new_address, new_private_key)