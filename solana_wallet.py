import base58
import base64
import cfg
import time
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed

class UniversalSolanaWallet:
    LAMPORTS_PER_SOL = 1_000_000_000
    
    @staticmethod
    def get_client():
        """Получить клиент для текущей сети"""
        try:
            if cfg.IS_MAINNET:
                return Client(cfg.SOLANA_MAINNET_RPC)
            else:
                return Client(cfg.SOLANA_RPC_URL)
        except Exception as e:
            print(f"Ошибка создания клиента: {e}")
            return Client("https://api.mainnet-beta.solana.com")
    
    @staticmethod
    def generate_wallet():
        """Сгенерировать новый кошелек"""
        try:
            keypair = Keypair()
            
            return {
                'success': True,
                'address': str(keypair.pubkey()),
                'private_key': base58.b58encode(bytes(keypair)).decode('utf-8'),
                'seed_phrase': None,
                'public_key': str(keypair.pubkey()),
                'network': cfg.SOLANA_NETWORK
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def get_balance(wallet_address: str):
        """Получить баланс кошелька в текущей сети"""
        try:
            client = UniversalSolanaWallet.get_client()
            response = client.get_balance(Pubkey.from_string(wallet_address))
            
            if response.value is not None:
                return response.value / UniversalSolanaWallet.LAMPORTS_PER_SOL
            else:
                return 0.0
        except Exception as e:
            print(f"Ошибка получения баланса: {e}")
            return 0.0

    @staticmethod
    def get_real_balance(wallet_address: str):
        """Алиас для get_balance для совместимости"""
        return UniversalSolanaWallet.get_balance(wallet_address)
    
    @staticmethod
    def validate_private_key(private_key: str) -> bool:
        """Проверить валидность приватного ключа"""
        try:
            if len(private_key) == 64:
                keypair = Keypair.from_bytes(bytes.fromhex(private_key))
            else:
                keypair = Keypair.from_base58_string(private_key)
            return True
        except:
            return False
    
    @staticmethod
    def get_keypair_from_private_key(private_key: str):
        """Получить Keypair из приватного ключа"""
        try:
            if len(private_key) == 64:
                try:
                    return Keypair.from_bytes(bytes.fromhex(private_key))
                except:
                    pass
            
            return Keypair.from_base58_string(private_key)
        except Exception as e:
            print(f"Ошибка преобразования приватного ключа: {e}")
            raise ValueError(f"Неверный формат приватного ключа: {str(e)}")
    
    @staticmethod
    def send_sol_simple(from_private_key: str, to_address: str, amount_sol: float):
        """
        Отправка SOL - проверка минимальной суммы
        """
        try:
            MIN_PRACTICAL_SOL = 0.0011
            
            if amount_sol < MIN_PRACTICAL_SOL:
                print(f"⚠️ Сумма {amount_sol:.6f} SOL слишком мала для отправки. Минимум: {MIN_PRACTICAL_SOL} SOL")
                return {
                    'success': True,
                    'tx_hash': None,
                    'amount_sol': 0,
                    'message': f'Сумма {amount_sol:.6f} SOL накоплена для будущей отправки'
                }
            
            client = UniversalSolanaWallet.get_client()
            from_keypair = UniversalSolanaWallet.get_keypair_from_private_key(from_private_key)
            
            try:
                to_pubkey = Pubkey.from_string(to_address)
            except:
                return {
                    'success': False,
                    'error': f'Неверный адрес получателя: {to_address}'
                }
            
            lamports = int(amount_sol * UniversalSolanaWallet.LAMPORTS_PER_SOL)
            
            if lamports <= 0:
                return {
                    'success': False,
                    'error': 'Сумма должна быть больше 0'
                }
            
            print(f"🔄 Отправка {amount_sol:.6f} SOL ({lamports} lamports) с {from_keypair.pubkey()} на {to_address}")
            
            recent_blockhash = client.get_latest_blockhash().value.blockhash
            
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=from_keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            
            message = Message.new_with_blockhash(
                [transfer_ix],
                from_keypair.pubkey(),
                recent_blockhash
            )
            
            txn = Transaction([from_keypair], message, recent_blockhash)
            
            try:
                result = client.send_transaction(txn)
            except Exception as e:
                print(f"Ошибка отправки: {e}")
                return {
                    'success': False,
                    'error': f'Ошибка отправки транзакции: {str(e)}'
                }
            
            if result.value:
                tx_hash = str(result.value)
                print(f"✅ Транзакция отправлена: {tx_hash}")
                
                return {
                    'success': True,
                    'tx_hash': tx_hash,
                    'amount_sol': amount_sol,
                    'network': cfg.SOLANA_NETWORK,
                    'message': f'Успешно отправлено {amount_sol:.6f} SOL'
                }
            else:
                error_msg = getattr(result, 'error', 'Неизвестная ошибка')
                print(f"❌ Ошибка отправки транзакции: {error_msg}")
                return {
                    'success': False,
                    'error': f'Не удалось отправить транзакцию: {error_msg}'
                }
                
        except Exception as e:
            print(f"❌ Критическая ошибка отправки SOL: {e}")
            return {
                'success': False,
                'error': f'Ошибка отправки: {str(e)}'
            }
    
    @staticmethod
    def validate_wallet_address(address: str) -> bool:
        """Валидация адреса кошелька Solana"""
        try:
            if not address or len(address) < 32 or len(address) > 44:
                return False
            
            import base58
            decoded = base58.b58decode(address)
            
            if len(decoded) != 32:
                return False
                
            return True
        except Exception:
            return False

    @staticmethod
    def send_sol(from_private_key: str, to_address: str, amount_sol: float):
        """
        Отправка SOL - основной метод для выводов средств
        """
        try:
            client = UniversalSolanaWallet.get_client()
            
            from_keypair = UniversalSolanaWallet.get_keypair_from_private_key(from_private_key)
            
            try:
                to_pubkey = Pubkey.from_string(to_address)
            except:
                return {
                    'success': False,
                    'error': f'Неверный адрес получателя: {to_address}'
                }
            
            if amount_sol <= 0:
                return {
                    'success': False,
                    'error': 'Сумма должна быть больше 0'
                }
            
            lamports = int(amount_sol * UniversalSolanaWallet.LAMPORTS_PER_SOL)
            
            print(f"🔄 Отправка {amount_sol:.6f} SOL ({lamports} lamports) с {from_keypair.pubkey()} на {to_address}")
            
            recent_blockhash = client.get_latest_blockhash().value.blockhash
            
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=from_keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            
            message = Message.new_with_blockhash(
                [transfer_ix],
                from_keypair.pubkey(),
                recent_blockhash
            )
            
            txn = Transaction([from_keypair], message, recent_blockhash)
            
            try:
                result = client.send_transaction(txn)
            except Exception as e:
                print(f"Ошибка отправки транзакции: {e}")
                return {
                    'success': False,
                    'error': f'Ошибка отправки транзакции: {str(e)}'
                }
            
            if result.value:
                tx_hash = str(result.value)
                print(f"✅ Транзакция отправлена: {tx_hash}")
                
                return {
                    'success': True,
                    'tx_hash': tx_hash,
                    'amount_sol': amount_sol,
                    'from_address': str(from_keypair.pubkey()),
                    'to_address': to_address,
                    'network': cfg.SOLANA_NETWORK
                }
            else:
                error_msg = getattr(result, 'error', 'Неизвестная ошибка')
                print(f"❌ Ошибка отправки транзакции: {error_msg}")
                return {
                    'success': False,
                    'error': f'Не удалось отправить транзакцию: {error_msg}'
                }
                
        except Exception as e:
            print(f"❌ Критическая ошибка отправки SOL: {e}")
            return {
                'success': False,
                'error': f'Ошибка отправки: {str(e)}'
            }

    @staticmethod
    def send_sol_to_admin(user_private_key: str, admin_wallet: str, amount_sol: float):
        """Отправить SOL админу (его комиссия 5%)"""
        try:
            return UniversalSolanaWallet.send_sol_simple(
                from_private_key=user_private_key,
                to_address=admin_wallet,
                amount_sol=amount_sol
            )
                
        except Exception as e:
            print(f"❌ Ошибка отправки SOL админу: {e}")
            return {
                'success': False,
                'error': f'Ошибка отправки админу: {str(e)}'
            }
    
    @staticmethod
    def airdrop_devnet_sol(wallet_address: str, amount_sol: float = 2.0):
        """
        Запросить Devnet SOL через airdrop (только для devnet)
        """
        if cfg.IS_MAINNET:
            return {
                'success': False,
                'error': 'Airdrop доступен только в devnet'
            }
        
        try:
            client = Client("https://api.devnet.solana.com")
            
            lamports = int(amount_sol * UniversalSolanaWallet.LAMPORTS_PER_SOL)
            
            print(f"🪂 Запрос airdrop {amount_sol} TEST SOL на {wallet_address}")
            
            result = client.request_airdrop(
                Pubkey.from_string(wallet_address), 
                lamports
            )
            
            if hasattr(result, 'value') and result.value:
                tx_hash = str(result.value)
                print(f"⏳ Ожидание подтверждения airdrop: {tx_hash}")
                
                try:
                    confirmation = client.confirm_transaction(
                        result.value,
                        commitment=Confirmed,
                        sleep_seconds=1
                    )
                    
                    if confirmation.value:
                        print(f"✅ Airdrop успешно выполнен: {tx_hash}")
                        return {
                            'success': True,
                            'tx_hash': tx_hash,
                            'amount_sol': amount_sol,
                            'message': f'Успешно отправлено {amount_sol} Devnet SOL'
                        }
                    else:
                        print("❌ Airdrop не подтвержден")
                        return {
                            'success': False,
                            'error': 'Транзакция не подтверждена'
                        }
                except Exception as confirm_error:
                    print(f"⚠️ Airdrop отправлен, но не подтвержден: {confirm_error}")
                    return {
                        'success': True,
                        'tx_hash': tx_hash,
                        'amount_sol': amount_sol,
                        'message': f'Airdrop отправлен, но требует подтверждения: {tx_hash}'
                    }
            else:
                print("❌ Ошибка airdrop")
                error_msg = getattr(result, 'error', 'Неизвестная ошибка')
                return {
                    'success': False,
                    'error': f'Не удалось выполнить airdrop: {error_msg}'
                }
                
        except Exception as e:
            print(f"❌ Ошибка airdrop: {e}")
            return {
                'success': False,
                'error': f'Ошибка airdrop: {str(e)}'
            }

    @staticmethod
    def get_wallet_address_from_private_key(private_key: str):
        """Получить адрес кошелька из приватного ключа"""
        try:
            keypair = UniversalSolanaWallet.get_keypair_from_private_key(private_key)
            return str(keypair.pubkey())
        except Exception as e:
            print(f"Ошибка получения адреса из приватного ключа: {e}")
            return None
        
    @staticmethod
    def send_sol_simple(from_private_key: str, to_address: str, amount_sol: float):
        """Алиас для send_sol для обратной совместимости"""
        return UniversalSolanaWallet.send_sol(from_private_key, to_address, amount_sol)