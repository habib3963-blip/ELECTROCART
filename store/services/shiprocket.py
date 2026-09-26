import os
import requests
from dotenv import load_dotenv

load_dotenv()


SHIPROCKET_LOGIN_URL = (
    "https://apiv2.shiprocket.in/v1/external/auth/login"
)


def get_shiprocket_token():

    email = os.getenv("SHIPROCKET_EMAIL")
    password = os.getenv("SHIPROCKET_PASSWORD")

    if not email or not password:
        raise ValueError(
            "Shiprocket credentials are not configured."
        )

    response = requests.post(
        SHIPROCKET_LOGIN_URL,
        json={
            "email": email,
            "password": password,
        },
        headers={
            "Content-Type": "application/json",
        },
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    token = data.get("token")

    if not token:
        raise ValueError(
            "Shiprocket authentication failed."
        )

    return token