import requests
import time
import cfg
from typing import Optional

class ExchangeRateManager:
    _last_rate = None
    _last_update = 0
    _cache_duration = 60
    
    @classmethod
    def get_sol_to_rub_rate(cls) -> float:
        current_time = time.time()
        
        if cls._last_rate and (current_time - cls._last_update) < cls._cache_duration:
            return cls._last_rate
        
        try:
            rate = cls._get_rate_from_bybit_p2p()
            if rate and rate > 0:
                cls._last_rate = rate
                cls._last_update = current_time
                print(f"✅ Курс получен: {rate} RUB/SOL")
                return rate
        except Exception as e:
            print(f"⚠️ Ошибка получения курса: {e}")
        
        print("⚠️ Источник недоступен, использую курс по умолчанию")
        return cfg.DEFAULT_SOL_TO_RUB_RATE
    
    @classmethod
    def _get_rate_from_bybit_p2p(cls) -> Optional[float]:
        try:
            sol_usdt_url = "https://api.bybit.com/v5/market/tickers?category=spot&symbol=SOLUSDT"
            response_sol = requests.get(sol_usdt_url, timeout=10)
            data_sol = response_sol.json()
            
            if data_sol['retCode'] != 0 or not data_sol['result']['list']:
                return None
                
            sol_usdt = float(data_sol['result']['list'][0]['lastPrice'])
            print(f"Bybit SOL/USDT: {sol_usdt}")
            
            p2p_url = "https://api2.bybit.com/fiat/otc/item/online"
            p2p_payload = {
                "tokenId": "USDT",
                "currencyId": "RUB", 
                "payment": ["64"],
                "side": "0",
                "size": "3",
                "page": "0",
                "amount": "10000",
                "authMaker": False,
                "canTrade": False
            }
            
            p2p_headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            p2p_response = requests.post(p2p_url, json=p2p_payload, headers=p2p_headers, timeout=10)
            
            if p2p_response.status_code != 200:
                print(f"P2P HTTP error: {p2p_response.status_code}")
                return None
                
            p2p_data = p2p_response.json()
            print(f"P2P items found: {p2p_data.get('result', {}).get('count', 0)}")
            
            if p2p_data.get('result', {}).get('items'):
                prices = []
                for i, item in enumerate(p2p_data['result']['items'][:3]):
                    if 'price' in item:
                        price = float(item['price'])
                        prices.append(price)
                        print(f"P2P offer {i+1}: {price} RUB")
                
                if prices:
                    avg_p2p_price = sum(prices) / len(prices)
                    print(f"Bybit P2P USDT/RUB (avg of {len(prices)} offers): {avg_p2p_price}")
                    
                    result = sol_usdt * avg_p2p_price
                    print(f"Итоговый курс SOL/RUB: {result}")
                    return result
            
            print("No P2P data found")
            return None
                
        except Exception as e:
            print(f"Bybit P2P error: {e}")
            return None

def get_sol_to_rub_rate() -> float:
    return ExchangeRateManager.get_sol_to_rub_rate()

def calculate_commissions(amount_rub: float) -> dict:
    worker_commission_rub = amount_rub * 0.05
    admin_commission_rub = amount_rub * 0.05
    total_with_commission = amount_rub + worker_commission_rub + admin_commission_rub
    
    return {
        'total_rub': total_with_commission,
        'worker_commission_rub': worker_commission_rub,
        'admin_commission_rub': admin_commission_rub,
        'original_amount_rub': amount_rub,
        'total_commission_rub': worker_commission_rub + admin_commission_rub 
    }

def rub_to_sol(rub_amount: float) -> float:
    total_rub = rub_amount * 1.10
    rate = get_sol_to_rub_rate()
    return total_rub / rate

def sol_to_rub_with_commissions(sol_amount: float) -> float:
    rate = get_sol_to_rub_rate()
    return sol_amount * rate

def calculate_worker_earnings(amount_rub: float) -> float:
    return amount_rub * 0.05