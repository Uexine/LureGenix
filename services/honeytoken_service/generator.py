import random
import string

def rand(n=16):
    return ''.join(random.choices(string.ascii_letters+string.digits,k=n))

def generate_env():

    return f"""
AWS_ACCESS_KEY={rand()}
AWS_SECRET_KEY={rand(32)}
DB_PASSWORD={rand()}
"""

def generate_passwords():

    return f"""
root:{rand()}
admin:{rand()}
backup:{rand()}
"""