#!/usr/bin/env python3
"""
Import en masse de Lignes téléphoniques dans GLPI via l'API REST v1.

Lit un CSV avec les colonnes : Nom, Numéro de l'appelant, Statut
et crée un objet "Line" par ligne via POST /api.php/v1/Line

Prérequis GLPI :
  - API REST activée (Configuration > Générale > API)
  - Un App-Token généré (Configuration > Générale > API > Ajouter un client API)
  - Un User-Token généré sur le compte utilisé (Préférences > onglet "Clés API")

Usage :
  python3 import_lignes_glpi.py --csv Cartes_SIM_GLPI_import.csv --dry-run
  python3 import_lignes_glpi.py --csv Cartes_SIM_GLPI_import.csv
"""

import csv
import sys
import argparse
import requests
import urllib3
from time import sleep

# ============ CONFIGURATION — À ADAPTER ============
GLPI_URL = "https://10.150.32.43/api.php/v1"   # votre endpoint API (comme pour Mobilier)
APP_TOKEN = "MY3sAWaxZhNI6PvMKRljXa2lKfHXGCry4C2nlNua"
USER_TOKEN = "qeT6sUpOdADgFKB9mGZcP6LphvsL8bf9iX3GRXh1"
VERIFY_SSL = False   # False si certificat auto-signé (comme dans vos autres imports)
ENTITY_ID = 0        # 0 = Entité racine ; adaptez si besoin
# =====================================================

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def init_session():
    headers = {
        "App-Token": APP_TOKEN,
        "Authorization": f"user_token {USER_TOKEN}",
    }
    r = requests.get(f"{GLPI_URL}/initSession", headers=headers, verify=VERIFY_SSL)
    r.raise_for_status()
    return r.json()["session_token"]


def kill_session(session_token):
    headers = {"App-Token": APP_TOKEN, "Session-Token": session_token}
    requests.get(f"{GLPI_URL}/killSession", headers=headers, verify=VERIFY_SSL)


def get_or_create_state(session_token, name, cache):
    """Retrouve l'ID d'un statut (table State) par son nom, le crée s'il n'existe pas."""
    name = name.strip()
    if not name:
        return None
    if name in cache:
        return cache[name]

    headers = {"App-Token": APP_TOKEN, "Session-Token": session_token}

    # recherche par nom exact
    params = {
        "criteria[0][field]": "1",       # 1 = name dans la plupart des dropdowns GLPI
        "criteria[0][searchtype]": "equals",
        "criteria[0][value]": name,
    }
    r = requests.get(f"{GLPI_URL}/search/State", headers=headers, params=params, verify=VERIFY_SSL)
    if r.ok:
        data = r.json()
        if data.get("totalcount", 0) > 0:
            state_id = data["data"][0]["2"]  # colonne 2 = id généralement, on sécurise ci-dessous
            # fallback plus fiable : requête directe sur la liste complète
    # Fallback fiable : lister tous les statuts et comparer nom
    r2 = requests.get(f"{GLPI_URL}/State", headers=headers,
                       params={"range": "0-200"}, verify=VERIFY_SSL)
    r2.raise_for_status()
    for state in r2.json():
        if state.get("name", "").strip().lower() == name.lower():
            cache[name] = state["id"]
            return state["id"]

    # pas trouvé -> création
    payload = {"input": {"name": name}}
    rc = requests.post(f"{GLPI_URL}/State", headers=headers, json=payload, verify=VERIFY_SSL)
    rc.raise_for_status()
    new_id = rc.json()["id"]
    cache[name] = new_id
    print(f"  [+] Statut créé : '{name}' (id={new_id})")
    return new_id


def create_line(session_token, nom, numero, states_id):
    headers = {"App-Token": APP_TOKEN, "Session-Token": session_token}
    payload = {
        "input": {
            "name": nom.strip(),
            "caller_num": numero.strip(),
            "entities_id": ENTITY_ID,
        }
    }
    if states_id:
        payload["input"]["states_id"] = states_id

    r = requests.post(f"{GLPI_URL}/Line", headers=headers, json=payload, verify=VERIFY_SSL)
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Fichier CSV (Nom, Numéro de l'appelant, Statut)")
    parser.add_argument("--dry-run", action="store_true", help="Simule sans rien créer")
    parser.add_argument("--limit", type=int, default=None, help="Limiter à N lignes (pour tester)")
    args = parser.parse_args()

    with open(args.csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.limit:
        rows = rows[: args.limit]

    print(f"{len(rows)} lignes à importer depuis {args.csv}")

    if args.dry_run:
        for row in rows[:10]:
            print("  ", row)
        print("(dry-run : rien n'a été envoyé à GLPI)")
        return

    session_token = init_session()
    print("Session GLPI ouverte.")

    state_cache = {}
    errors = []
    created = 0

    try:
        for i, row in enumerate(rows, start=1):
            nom = row.get("Nom", "").strip()
            numero = row.get("Numéro de l'appelant", "").strip()
            statut = row.get("Statut", "").strip()

            if not nom and not numero:
                errors.append((i, nom, numero, "ligne vide, ignorée"))
                continue

            try:
                states_id = get_or_create_state(session_token, statut, state_cache) if statut else None
                r = create_line(session_token, nom, numero, states_id)
                if r.status_code in (200, 201):
                    created += 1
                    if created % 25 == 0:
                        print(f"  ... {created} lignes créées")
                else:
                    errors.append((i, nom, numero, f"HTTP {r.status_code} - {r.text[:200]}"))
            except requests.exceptions.RequestException as e:
                errors.append((i, nom, numero, str(e)))

            sleep(0.05)  # petite pause pour ne pas saturer l'API

    finally:
        kill_session(session_token)
        print("Session GLPI fermée.")

    print(f"\nTerminé : {created} lignes créées, {len(errors)} erreurs.")

    if errors:
        report_path = "import_errors.csv"
        with open(report_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ligne_csv", "nom", "numero", "erreur"])
            writer.writerows(errors)
        print(f"Détail des erreurs : {report_path}")


if __name__ == "__main__":
    main()
