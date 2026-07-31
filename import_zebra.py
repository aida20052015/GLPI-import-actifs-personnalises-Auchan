import requests
import csv
import re
import urllib3
urllib3.disable_warnings()

BASE_URL = "https://10.150.32.43/api.php/v1"
APP_TOKEN = "MY3sAWaxZhNI6PvMKRljXa2lKfHXGCry4C2nlNua"
USER_TOKEN = "qeT6sUpOdADgFKB9mGZcP6LphvsL8bf9iX3GRXh1"
ASSETS_DEFINITION_ID = 1  # ID de la définition Zebra
CSV_PATH = "ZEBRA.csv"

# Modèles pré-créés manuellement (IDs confirmés)
MODELES = {
    "TC53E": 2,
    "TC57": 3,
}

MOIS_FR = {
    "janvier": "01", "février": "02", "fevrier": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08", "aout": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12", "decembre": "12"
}

def convertir_date_fr(date_str):
    m = re.match(r"(\d{1,2})\s+(\S+)\s+(\d{4})", date_str.strip())
    if not m:
        return None
    jour, mois_nom, annee = m.groups()
    mois = MOIS_FR.get(mois_nom.lower())
    if not mois:
        return None
    return f"{annee}-{mois}-{jour.zfill(2)}"

def convertir_datetime(dt_str):
    return dt_str.strip()[:19]

# --- Init session ---
r = requests.get(f"{BASE_URL}/initSession",
    headers={"App-Token": APP_TOKEN, "Authorization": f"user_token {USER_TOKEN}"},
    verify=False)
r.raise_for_status()
session_token = r.json()["session_token"]
headers = {"App-Token": APP_TOKEN, "Session-Token": session_token, "Content-Type": "application/json"}

def get_or_create_location(name, cache={}):
    if not name:
        return None
    if name in cache:
        return cache[name]

    listing_key = "__locations__"
    if listing_key not in cache:
        resp = requests.get(f"{BASE_URL}/Location", params={"range": "0-2000"}, headers=headers, verify=False)
        items = resp.json() if resp.status_code == 200 else []
        cache[listing_key] = {i["name"]: i["id"] for i in items if isinstance(i, dict) and "name" in i}

    existing = cache[listing_key]
    if name in existing:
        cache[name] = existing[name]
        return existing[name]

    payload = {"input": {"name": name}}
    resp = requests.post(f"{BASE_URL}/Location", json=payload, headers=headers, verify=False)
    if resp.status_code not in (200, 201):
        print(f"  Erreur création Lieu '{name}': {resp.status_code} {resp.text}")
        return None
    new_id = resp.json().get("id")
    existing[name] = new_id
    cache[name] = new_id
    return new_id

# --- Récupération des items Zebra déjà existants (pour éviter les doublons) ---
print("Récupération des items déjà existants...")
resp = requests.get(f"{BASE_URL}/Glpi\\CustomAsset\\ZebraAsset", params={"range": "0-2000"}, headers=headers, verify=False)
existants = resp.json() if resp.status_code == 200 else []
series_existantes = {i["serial"] for i in existants if isinstance(i, dict) and i.get("serial")}
print(f"{len(series_existantes)} items déjà présents (par numéro de série).\n")

# --- Lecture du CSV et import ---
success, errors, skipped = 0, 0, 0
with open(CSV_PATH, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f, delimiter=";")
    for i, row in enumerate(reader):
        serial = row["Serial number"].strip()
        if serial in series_existantes:
            skipped += 1
            continue

        model_name = row["Model"].strip()
        model_id = MODELES.get(model_name)
        if model_id is None:
            print(f"Modèle inconnu pour {row['Device name']}: '{model_name}'")
            errors += 1
            continue

        location_id = get_or_create_location(row["Category"].strip())

        payload_input = {
            "name": row["Device name"].strip(),
            "serial": row["Serial number"].strip(),
            "assets_assetmodels_id": model_id,
            "custom_os": row["OS"].strip(),
            "custom_version_os": row["OS version"].strip(),
            "custom_dernier_contact": convertir_datetime(row["Last check-in"]),
            "custom_date_entree": convertir_date_fr(row["DATE D'entree"])
        }
        if location_id is not None:
            payload_input["locations_id"] = location_id

        payload = {"input": payload_input}

        resp = requests.post(f"{BASE_URL}/Glpi\\CustomAsset\\ZebraAsset", json=payload, headers=headers, verify=False)
        if resp.status_code in (200, 201):
            success += 1
        else:
            errors += 1
            print(f"Échec pour {row['Device name']}: {resp.status_code} {resp.text}")

print(f"\nTerminé : {success} créés, {errors} en erreur, {skipped} doublons ignorés")

requests.get(f"{BASE_URL}/killSession", headers=headers, verify=False)