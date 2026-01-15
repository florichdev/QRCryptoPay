import requests
import time

def test_rate_limits():
    base_url = "https://localhost:5000"
    session = requests.Session()
    session.verify = False
    
    print("🚫 Testing Rate Limits")
    print("=" * 40)
    
    print("1. Session Generation Rate Limit (10 attempts max):")
    for i in range(12):
        response = session.post(
            f"{base_url}/api/auth/generate-session",
            json={"type": "register"}
        )
        status = "✅" if response.status_code != 429 else "🚫"
        print(f"   Attempt {i+1}: {status} HTTP {response.status_code}")
        
        if response.status_code == 429:
            print("   ✅ RATE LIMIT WORKING!")
            break
        time.sleep(0.1)
    
    print("\n2. Login Rate Limit (5 attempts max):")
    for i in range(7):
        response = session.post(
            f"{base_url}/api/auth/login", 
            json={"code": f"test{i}"}
        )
        status = "✅" if response.status_code != 429 else "🚫"
        print(f"   Attempt {i+1}: {status} HTTP {response.status_code}")
        
        if response.status_code == 429:
            print("   ✅ RATE LIMIT WORKING!")
            break
        time.sleep(0.1)

if __name__ == "__main__":
    test_rate_limits()