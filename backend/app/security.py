import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from zxcvbn import zxcvbn


password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def valid_password(password: str) -> bool:
    if len(password) < 12 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return False
    return zxcvbn(password)["score"] >= 3


def random_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def otp_hash(code: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), code.encode(), hashlib.sha256).hexdigest()


def otp_matches(code: str, expected_hash: str, pepper: str) -> bool:
    return hmac.compare_digest(otp_hash(code, pepper), expected_hash)