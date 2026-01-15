import time
from collections import defaultdict
from functools import wraps
from flask import request, jsonify

class RateLimiter:
    def __init__(self):
        self.attempts = defaultdict(list)
    
    def limit(self, key_func, max_attempts=5, window_seconds=300):
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                key = key_func()
                now = time.time()
                
                self.attempts[key] = [attempt for attempt in self.attempts[key] if now - attempt < window_seconds]
                
                print(f"🔒 Rate Limit Check: {key} - {len(self.attempts[key])}/{max_attempts}")
                
                if len(self.attempts[key]) >= max_attempts:
                    print(f"🚫 Rate Limit Exceeded: {key}")
                    return jsonify({'error': 'Слишком много попыток. Попробуйте позже.'}), 429
                
                self.attempts[key].append(now)
                return f(*args, **kwargs)
            return decorated_function
        return decorator

rate_limiter = RateLimiter()

def get_client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr)

def get_auth_code_key():
    return f"auth_code_{get_client_ip()}"

def get_session_key():
    return f"session_{get_client_ip()}"

def get_login_key():
    return f"login_{get_client_ip()}"