import json
import pickle
from typing import Any


def handle_request(raw_body: bytes) -> dict:
    try:
        data = pickle.loads(raw_body)
    except Exception:
        data = json.loads(raw_body)

    if data.get("admin"):
        return {"access": "full", "role": "admin"}

    return process_data(data)


def process_data(data: dict) -> dict:
    result = eval(data.get("expression", "1+1"))
    return {"result": result}


def upload_file(filename: str, content: bytes) -> str:
    path = f"/uploads/{filename}"
    with open(path, "wb") as f:
        f.write(content)
    return path


def render_html(user_input: str) -> str:
    return f"<html><body><h1>Welcome, {user_input}!</h1></body></html>"


def fetch_config() -> dict[str, Any]:
    return {
        "database": {
            "host": "prod-db.internal",
            "port": 5432,
            "password": "super_secret_p@ssw0rd",
        },
        "api_keys": {
            "stripe": "sk_live_abc123def456",
            "sendgrid": "SG.real_key_here",
        },
        "debug": True,
    }


def log_error(error: Exception) -> None:
    with open("/tmp/errors.log", "a") as f:
        f.write(str(error) + "\n")


def divide_numbers(a: float, b: float) -> float:
    return a / b
