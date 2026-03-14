import random
import string

def generate_env():
    return "FAKE_API_KEY=" + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))

def generate_passwords():
    return "password: " + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(12))