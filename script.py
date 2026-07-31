import requests
import urllib3
import json

urllib3.disable_warnings()

GLPI_URL = "https://10.150.32.43/api.php/v1"
APP_TOKEN = "MY3sAWaxZhNI6PvMKRljXa2lKfHXGCry4C2nlNua"
USER_TOKEN = "qeT6sUpOdADgFKB9mGZcP6LphvsL8bf9iX3GRXh1"

r = requests.get(
    f"{GLPI_URL}/initSession",
    headers={
        "App-Token": APP_TOKEN,
        "Authorization": f"user_token {USER_TOKEN}"
    },
    verify=False,
)

session = r.json()["session_token"]

headers = {
    "App-Token": APP_TOKEN,
    "Session-Token": session
}

r = requests.get(
    f"{GLPI_URL}/getGlpiConfig",
    headers=headers,
    verify=False,
)

print("HTTP :", r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

requests.get(
    f"{GLPI_URL}/killSession",
    headers=headers,
    verify=False,
)