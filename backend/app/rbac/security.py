
import hashlib
import hmac
import secrets

ALGO = "pbkdf2_sha256"
ITERATIONS = 240_000
MIN_PASSWORD_LEN = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGO}${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != ALGO:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
    return hmac.compare_digest(dk.hex(), hash_hex)


def password_ok(password: str) -> tuple[bool, str]:
    if len(password) < MIN_PASSWORD_LEN:
        return False, f"密码至少 {MIN_PASSWORD_LEN} 位"
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        return False, "密码需同时包含字母和数字"
    if not any(not c.isalnum() for c in password) and not (
        any(c.islower() for c in password) and any(c.isupper() for c in password)
    ):
        return False, "密码还需包含一个符号或大小写混合"
    return True, ""


def random_password(length: int = 14) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789@#$%*"
    pwd = "".join(secrets.choice(alphabet) for _ in range(length))
    if not any(c.isdigit() for c in pwd):
        pwd = pwd[:-1] + secrets.choice("23456789")
    return pwd

