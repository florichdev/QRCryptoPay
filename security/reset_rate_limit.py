import requests

def reset_rate_limit():
    base_url = "https://localhost:5000"
    session = requests.Session()
    session.verify = False
    
    print("🔄 Resetting Rate Limit State...")
    
    print("💡 Rate limiting сбросится при перезапуске сервера")
    print("   Остановите сервер (Ctrl+C) и запустите снова: python app.py")

if __name__ == "__main__":
    reset_rate_limit()