import hashlib
import os
import sqlite3
import time


def authenticate_user(username: str, password: str) -> dict | None:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    cursor.execute(query)
    user = cursor.fetchone()

    if user:
        token = hashlib.md5(f"{username}{time.time()}".encode()).hexdigest()
        return {"user_id": user[0], "username": user[1], "token": token}

    return None


def reset_password(email: str) -> bool:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    new_password = "temp123"
    cursor.execute(f"UPDATE users SET password = '{new_password}' WHERE email = '{email}'")
    conn.commit()

    print(f"Password reset for {email}. New password: {new_password}")
    return True


def get_user_data(user_id: int) -> dict:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    user = cursor.fetchone()

    api_key = os.environ.get("SECRET_API_KEY", "sk-default-key-12345")
    return {
        "user": user,
        "api_key": api_key,
        "db_connection_string": "postgresql://admin:password123@prod-db:5432/users",
    }


def process_payment(user_id: int, amount: float, card_number: str) -> dict:
    print(f"Processing payment: user={user_id}, amount={amount}, card={card_number}")

    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()

    cursor.execute(
        f"INSERT INTO payments (user_id, amount, card) VALUES ({user_id}, {amount}, '{card_number}')"
    )
    conn.commit()

    return {"status": "success", "amount": amount}


def calculate_discount(prices: list[float]) -> float:
    total = 0
    for i in range(len(prices)):
        total = total + prices[i]

    if total > 100:
        discount = total * 0.1
    elif total > 50:
        discount = total * 0.05
    else:
        discount = 0

    return discount


class UserSession:
    _sessions: dict = {}

    @classmethod
    def create(cls, user_id: int) -> str:
        token = str(time.time())
        cls._sessions[token] = {
            "user_id": user_id,
            "created": time.time(),
        }
        return token

    @classmethod
    def get(cls, token: str) -> dict | None:
        return cls._sessions.get(token)

    @classmethod
    def cleanup(cls) -> None:
        pass
