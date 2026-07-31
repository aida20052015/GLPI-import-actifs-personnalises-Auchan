#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import en masse d'un actif personnalisé GLPI (ex : Mobilier) via l'API REST.
À utiliser quand le plugin Data Injection ne peut pas être utilisé
(cas des types d'actifs créés via Définitions d'actifs / asset definitions).

PRÉREQUIS AVANT DE LANCER LE SCRIPT
------------------------------------
1. API activée : Configuration > Générale > onglet API > "Activer l'API REST".
2. App Token : Configuration > Générale > onglet API > créer/éditer un client API.
3. User Token : se connecter avec le compte qui doit exécuter l'import,
   puis Préférences personnelles > onglet "Clés d'API" > générer un jeton.
4. Le "nom système" (system name) exact du type d'actif personnalisé.
   Il se trouve dans Configuration > Définitions d'actifs > votre type (ex: Mobilier)
   -> c'est ce nom qui sert de nom d'itemtype dans l'API (ex: PluginFieldsMobilier,
   ou directement "Mobilier" selon la version — le script le vérifie automatiquement
   à l'étape de auto-détection ci-dessous).

Installer la dépendance si besoin :
    pip install requests --break-system-packages
"""

import csv
import sys
import json
import requests
import urllib3
import urllib.parse

# Le serveur GLPI utilise un certificat auto-signé -> on désactive
# juste l'avertissement associé (la vérification est déjà coupée via VERIFY_SSL).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================================================================
# 1. CONFIGURATION — à adapter avant exécution
# =========================================================================

GLPI_URL = "https://10.150.32.43/api.php/v1"  # le serveur redirige http -> https
APP_TOKEN = "MY3sAWaxZhNI6PvMKRljXa2lKfHXGCry4C2nlNua"
USER_TOKEN = "qeT6sUpOdADgFKB9mGZcP6LphvsL8bf9iX3GRXh1"

# Nom système exact du type d'actif personnalisé (visible dans Définitions d'actifs).
# Pour les actifs créés via Configuration > Définitions d'actifs (natif GLPI 11, pas un plugin),
# le nom de classe utilisé par l'API est "Glpi\CustomAsset\{NomSystème}Asset".
# Exemple : si le "nom système" saisi dans GLPI est "Mobilier", la classe est
# "Glpi\CustomAsset\MobilierAsset". Le script encode automatiquement les antislashs pour l'URL.
ITEMTYPE = "Glpi\\CustomAsset\\MobilierAsset"   # <-- À VÉRIFIER : adaptez "Mobilier" si besoin

# Fichier CSV à importer (le même que Generique_Autre.csv, complété avec vos données)
CSV_FILE = "Generique_Autre.csv"
CSV_DELIMITER = ";"

# Vérifier le certificat SSL (mettre False seulement si certificat auto-signé en test)
VERIFY_SSL = False  # certificat auto-signé sur le serveur GLPI

# Mapping colonne CSV -> champ GLPI de l'itemtype
# Adapter les clés de droite aux noms de champs réels de votre définition d'actif
# (visibles via l'étape d'auto-détection, section 3 plus bas).
FIELD_MAP = {
    "Nom": "name",
    "Numéro de série / réf.": "serial",
    "Numéro d'inventaire": "otherserial",
    "Commentaires": "comment",
    "Type de mobilier": "custom_type_de_mobilier",
    "État physique": "custom_etat_physique",
    # Les champs suivants nécessitent une résolution par nom -> ID (dropdowns) :
    # "Statut": "states_id",
    # "Entité": "entities_id",
    # "Emplacement": "locations_id",
}

# Colonnes qui sont des dropdowns GLPI standards (nom -> id à résoudre automatiquement)
DROPDOWN_MAP = {
    "Statut": ("states_id", "State"),
    "Entité": ("entities_id", "Entity"),
    "Emplacement": ("locations_id", "Location"),
}

CREATE_DROPDOWN_IF_MISSING = True  # crée la valeur du dropdown si elle n'existe pas encore

# =========================================================================
# 2. FONCTIONS API
# =========================================================================

def init_session():
    r = requests.get(
        f"{GLPI_URL}/initSession",
        headers={
            "App-Token": APP_TOKEN,
            "Authorization": f"user_token {USER_TOKEN}",
        },
        verify=VERIFY_SSL,
    )
    r.raise_for_status()
    return r.json()["session_token"]


def kill_session(session_token):
    requests.get(
        f"{GLPI_URL}/killSession",
        headers=headers(session_token),
        verify=VERIFY_SSL,
    )


def encoded_itemtype(itemtype):
    """Encode le nom d'itemtype pour l'URL (les actifs personnalisés GLPI 11
    utilisent un namespace avec antislash, ex: Glpi\\CustomAsset\\MobilierAsset)."""
    return urllib.parse.quote(itemtype, safe="")


def find_existing_item_id(session_token, itemtype, name):
    """Cherche un item existant de itemtype par correspondance exacte sur le nom.
    Retourne son id si trouvé, sinon None."""
    if not name:
        return None
    r = requests.get(
        f"{GLPI_URL}/{encoded_itemtype(itemtype)}",
        headers=headers(session_token),
        params={"range": "0-499"},
        verify=VERIFY_SSL,
    )
    if r.ok:
        items = r.json()
        if isinstance(items, list):
            for item in items:
                if str(item.get("name", "")).strip().lower() == name.strip().lower():
                    return item.get("id")
    else:
        print(f"  [!] Recherche d'existant échouée pour '{name}' ({r.status_code}) : {r.text}")
    return None


def headers(session_token):
    return {
        "App-Token": APP_TOKEN,
        "Session-Token": session_token,
        "Content-Type": "application/json",
    }


def get_or_create_dropdown_id(session_token, itemtype, name, cache):
    """Cherche l'ID d'une valeur de dropdown (State, Entity, Location...) par son nom.
    Crée la valeur si elle n'existe pas et CREATE_DROPDOWN_IF_MISSING est True."""
    if not name:
        return None
    key = (itemtype, name)
    if key in cache:
        return cache[key]

    # Liste les éléments existants de ce type et cherche une correspondance exacte sur le nom
    r = requests.get(
        f"{GLPI_URL}/{encoded_itemtype(itemtype)}",
        headers=headers(session_token),
        params={"range": "0-499"},
        verify=VERIFY_SSL,
    )
    if r.ok:
        items = r.json()
        if isinstance(items, list):
            for item in items:
                if str(item.get("name", "")).strip().lower() == name.strip().lower():
                    cache[key] = item["id"]
                    return item["id"]
    else:
        print(f"  [!] Recherche d'existant échouée pour '{name}' dans {itemtype} ({r.status_code}) : {r.text}")

    if CREATE_DROPDOWN_IF_MISSING:
        r = requests.post(
            f"{GLPI_URL}/{encoded_itemtype(itemtype)}",
            headers=headers(session_token),
            data=json.dumps({"input": {"name": name}}),
            verify=VERIFY_SSL,
        )
        if r.ok:
            new_id = r.json().get("id")
            cache[key] = new_id
            return new_id
        else:
            print(f"  [!] Impossible de créer '{name}' dans {itemtype} : {r.text}")
    return None


def discover_fields(session_token, itemtype):
    """Étape 3 : affiche les options de recherche disponibles pour l'itemtype,
    utile pour vérifier le nom exact des champs avant de lancer l'import réel."""
    r = requests.get(
        f"{GLPI_URL}/listSearchOptions/{encoded_itemtype(itemtype)}",
        headers=headers(session_token),
        verify=VERIFY_SSL,
    )
    if r.ok:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:3000])
    else:
        print(f"[!] Erreur en listant les champs de {itemtype} ({r.status_code}) : {r.text}")
        print("    -> Vérifiez le nom exact de ITEMTYPE dans Définitions d'actifs.")


# =========================================================================
# 3. IMPORT PRINCIPAL
# =========================================================================

def run_import():
    session_token = init_session()
    dropdown_cache = {}
    report = []

    try:
        with open(CSV_FILE, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
            rows = list(reader)

        print(f"{len(rows)} ligne(s) à importer dans {ITEMTYPE}\n")

        for i, row in enumerate(rows, start=1):
            payload = {}

            for csv_col, glpi_field in FIELD_MAP.items():
                if csv_col in row and row[csv_col]:
                    payload[glpi_field] = row[csv_col]

            for csv_col, (glpi_field, dropdown_itemtype) in DROPDOWN_MAP.items():
                value_name = row.get(csv_col)
                if value_name:
                    resolved_id = get_or_create_dropdown_id(
                        session_token, dropdown_itemtype, value_name, dropdown_cache
                    )
                    if resolved_id:
                        payload[glpi_field] = resolved_id

            item_name = payload.get("name")
            existing_id = find_existing_item_id(session_token, ITEMTYPE, item_name)

            if existing_id:
                payload["id"] = existing_id
                r = requests.put(
                    f"{GLPI_URL}/{encoded_itemtype(ITEMTYPE)}/{existing_id}",
                    headers=headers(session_token),
                    data=json.dumps({"input": payload}),
                    verify=VERIFY_SSL,
                )
                action = "MAJ"
            else:
                r = requests.post(
                    f"{GLPI_URL}/{encoded_itemtype(ITEMTYPE)}",
                    headers=headers(session_token),
                    data=json.dumps({"input": payload}),
                    verify=VERIFY_SSL,
                )
                action = "CRÉÉ"

            if r.ok:
                resp_json = r.json()
                if isinstance(resp_json, list) and resp_json:
                    resp_json = resp_json[0]
                if isinstance(resp_json, dict):
                    result_id = resp_json.get("id", existing_id or "?")
                else:
                    result_id = existing_id or "?"
                print(f"  [OK-{action}] Ligne {i} -> {action.lower()} (id={result_id}) : {payload.get('name')}")
                report.append({"ligne": i, "statut": f"OK-{action}", "id": result_id, "detail": ""})
            else:
                print(f"  [ERREUR] Ligne {i} : {r.status_code} {r.text}")
                report.append({"ligne": i, "statut": "ERREUR", "id": "", "detail": r.text})

    finally:
        kill_session(session_token)

    # Écrit un rapport d'import
    with open("rapport_import.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["ligne", "statut", "id", "detail"])
        writer.writeheader()
        writer.writerows(report)

    ok_count = sum(1 for r in report if r["statut"] == "OK")
    print(f"\nTerminé : {ok_count}/{len(report)} lignes importées avec succès.")
    print("Détail dans rapport_import.csv")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--discover":
        # Mode diagnostic : liste les champs disponibles pour ITEMTYPE
        # Usage : python3 import_glpi_api.py --discover
        st = init_session()
        try:
            discover_fields(st, ITEMTYPE)
        finally:
            kill_session(st)
    else:
        run_import()