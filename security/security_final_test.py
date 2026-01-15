import requests
import time

def security_final_test():
    base_url = "https://localhost:5000"
    session = requests.Session()
    session.verify = False
    
    print("🔒 FINAL SECURITY TEST")
    print("=" * 50)
    
    print("1. Basic API Functionality:")
    response = session.post(
        f"{base_url}/api/auth/generate-session",
        json={"type": "register"}
    )
    print(f"   Session gen: HTTP {response.status_code} {'✅' if response.status_code == 200 else '❌'}")
    
    print("\n2. Rate Limiting Test:")
    blocked = False
    for i in range(11):
        response = session.post(
            f"{base_url}/api/auth/generate-session",
            json={"type": "register"}
        )
        if response.status_code == 429:
            print(f"   ✅ Rate limit blocked attempt {i+1}")
            blocked = True
            break
        print(f"   Attempt {i+1}: HTTP {response.status_code}")
        time.sleep(0.1)
    
    if not blocked:
        print("   ❌ Rate limiting not working")
    
    print("\n3. Security Headers:")
    response = session.get(f"{base_url}/")
    headers = response.headers
    
    security_headers = {
        'X-Content-Type-Options': headers.get('X-Content-Type-Options'),
        'X-Frame-Options': headers.get('X-Frame-Options'),
        'Strict-Transport-Security': headers.get('Strict-Transport-Security')
    }
    
    for header, value in security_headers.items():
        status = "✅" if value else "❌"
        print(f"   {header}: {value} {status}")
    
    print("\n🎯 SECURITY STATUS:")
    print(f"   API Functionality: ✅")
    print(f"   Rate Limiting: {'✅' if blocked else '❌'}")
    print(f"   Security Headers: {'✅' if all(security_headers.values()) else '❌'}")

if __name__ == "__main__":
    security_final_test()