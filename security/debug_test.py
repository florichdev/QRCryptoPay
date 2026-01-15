import requests

def final_check():
    base_url = "https://localhost:5000"
    session = requests.Session()
    session.verify = False
    
    print("🎯 FINAL CHECK - Basic API Functionality")
    print("=" * 40)
    
    tests = [
        ("GET /api/health", "GET", "/api/health", None),
        ("POST /api/auth/generate-session", "POST", "/api/auth/generate-session", {"type": "register"}),
        ("POST /api/auth/login", "POST", "/api/auth/login", {"code": "test123"}),
    ]
    
    for name, method, endpoint, data in tests:
        try:
            if method == "GET":
                response = session.get(f"{base_url}{endpoint}")
            else:
                response = session.post(f"{base_url}{endpoint}", json=data)
            
            status = "✅" if response.status_code in [200, 400] else "❌"
            print(f"{status} {name}: HTTP {response.status_code}")
            
        except Exception as e:
            print(f"❌ {name}: ERROR {e}")

if __name__ == "__main__":
    final_check()