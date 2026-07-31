import requests
import json
import urllib3
import urllib.parse

urllib3.disable_warnings()

GLPI_URL = "https://10.150.32.43/api.php/v1"
APP_TOKEN = "MY3sAWaxZhNI6PvMKRljXa2lKfHXGCry4C2nlNua"
USER_TOKEN = "qeT6sUpOdADgFKB9mGZcP6LphvsL8bf9iX3GRXh1"

ITEMTYPE = "Glpi\\CustomAsset\\MobilierAsset"
ITEM_ID = 6
import requests
import json
import urllib3
import urllib.parse

urllib3.disable_warnings()

GLPI_URL = "https://10.150.32.43/api.php/v1"
APP_TOKEN = "MY3sAWaxZhNI6PvMKRljXa2lKfHXGCry4C2nlNua"
USER_TOKEN = "qeT6sUpOdADgFKB9mGZcP6LphvsL8bf9iX3GRXh1"

ITEMTYPE = "Glpi\\CustomAsset\\MobilierAsset"
ITEM_ID = 6

# Ouverture de session
r = requests.get(
    f"{GLPI_URL}/initSession",
    headers={
        "App-Token": APP_TOKEN,
        "Authorization": f"user_token {USER_TOKEN}",
    },
    verify=False,
)

r.raise_for_status()
session = r.json()["session_token"]

headers = {
    "App-Token": APP_TOKEN,
    "Session-Token": session,
}

# Récupération du mobilier
url = f"{GLPI_URL}/{urllib.parse.quote(ITEMTYPE, safe='')}/{ITEM_ID}"

r = requests.get(url, headers=headers, verify=False)

print("===== MOBILIER =====")
print("HTTP :", r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Recherche des champs contenant "type"
print("\n===== CHAMPS TYPE =====")

r = requests.get(
    f"{GLPI_URL}/listSearchOptions/{urllib.parse.quote(ITEMTYPE, safe='')}",
    headers=headers,
    verify=False,
)

options = r.json()

for k, v in options.items():
    if isinstance(v, dict):
        nom = str(v.get("name", ""))
        champ = str(v.get("field", ""))
        uid = str(v.get("uid", ""))

        if "type" in nom.lower() or "type" in champ.lower() or "type" in uid.lower():
            print(f"{k} :")
            print("  Nom   :", nom)
            print("  Champ :", champ)
            print("  UID   :", uid)
            print()

# Fermeture de session
requests.get(
    f"{GLPI_URL}/killSession",
    headers=headers,
    verify=False,
)
# Ouverture de session
r = requests.get(
    f"{GLPI_URL}/initSession",
    headers={
        "App-Token": APP_TOKEN,
        "Authorization": f"user_token {USER_TOKEN}",
    },
    verify=False,
)

r.raise_for_status()
session = r.json()["session_token"]

headers = {
    "App-Token": APP_TOKEN,
    "Session-Token": session,
}

url = f"{GLPI_URL}/{urllib.parse.quote(ITEMTYPE, safe='')}/{ITEM_ID}"

r = requests.get(url, headers=headers, verify=False)

print("HTTP :", r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

requests.get(
    f"{GLPI_URL}/killSession",
    headers=headers,
    verify=False,
)

r = requests.get(
    f"{GLPI_URL}/listSearchOptions/{urllib.parse.quote(ITEMTYPE, safe='')}",
    headers=headers,
    verify=False,
)

options = r.json()

print("\n===== CHAMPS TYPE =====")

options = r.json()

for v in options:
    if not isinstance(v, dict):
        continue

    nom = str(v.get("name", ""))
    champ = str(v.get("field", ""))
    uid = str(v.get("uid", ""))

    if "type" in nom.lower() or "type" in champ.lower():
        print()
        print("Nom   :", nom)
        print("Champ :", champ)
        print("UID   :", uid)