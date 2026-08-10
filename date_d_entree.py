#!/usr/bin/env python3
"""
Import direct en base MariaDB de la "Date d'entrée" (champ additionnel du
plugin Fields) sur les Ordinateurs GLPI, à partir d'un fichier CSV.

Contourne les limites de pagination rencontrées avec l'API REST en écrivant
directement dans la base de données.

Pré-requis :
    pip install pymysql --break-system-packages

CSV attendu :
    Device name,DATE D'ENTREE
    DSN-SH00027,01-11-2025

Usage :
    python3 import_date_entree_db.py --dry-run      # simulation, aucune écriture
    python3 import_date_entree_db.py                # exécution réelle

Si la connexion échoue (timeout / connexion refusée), c'est probablement que
le port 3306 n'est pas ouvert depuis ce poste : il faudra alors exécuter ce
script directement sur le serveur GLPI (ou via un tunnel SSH, voir plus bas).
"""

import argparse
import csv
import sys
from datetime import datetime

try:
    import pymysql
except ImportError:
    print("Le module pymysql est requis : pip install pymysql --break-system-packages")
    sys.exit(1)

# ============================== CONFIGURATION ==============================

DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "glpiuser"
DB_PASSWORD = "Auch@nYoff2026!"
DB_NAME = "glpi"

CSV_PATH = "DATE_D_ENTREE.csv"
CSV_NAME_COLUMN = "Device name"
CSV_DATE_COLUMN = "DATE D'ENTREE"
CSV_DATE_FORMAT = "%d-%m-%Y"          # format des dates dans le CSV (JJ-MM-AAAA)

FIELD_NAME = "datedentrefield"        # nom système du champ (field.form.php?id=5)

# =============================================================================


def connect():
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            connect_timeout=6,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        print(f"Connecté à {DB_HOST}:{DB_PORT}/{DB_NAME}")
        return conn
    except pymysql.err.OperationalError as e:
        print(f"\nEchec de connexion MariaDB : {e}")
        print(
            "\nSi l'erreur mentionne un timeout ou une connexion refusée, le port "
            f"{DB_PORT} n'est probablement pas accessible depuis ce poste "
            "(pare-feu / bind-address MariaDB en localhost uniquement).\n"
            "Solutions :\n"
            "  1) Exécuter ce script directement sur le serveur GLPI (SSH puis "
            "python3 import_date_entree_db.py), avec DB_HOST='localhost' ou '127.0.0.1'.\n"
            "  2) Ou ouvrir un tunnel SSH depuis ce poste :\n"
            f"     ssh -L 3306:localhost:3306 utilisateur@{DB_HOST}\n"
            "     puis mettre DB_HOST='127.0.0.1' dans ce script.\n"
        )
        sys.exit(1)


def find_field_table(conn):
    """Recherche la table du plugin Fields, spécifique aux Ordinateurs, qui
    contient la colonne FIELD_NAME. Le même nom de champ existe dans de
    nombreuses tables (le conteneur peut être appliqué à plusieurs types
    d'objets GLPI), donc on filtre explicitement sur la table Computer."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT TABLE_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND COLUMN_NAME = %s
              AND TABLE_NAME LIKE 'glpi_plugin_fields_%%'
            """,
            (DB_NAME, FIELD_NAME),
        )
        candidates = [r["TABLE_NAME"] for r in cur.fetchall()]

    if not candidates:
        raise RuntimeError(
            f"Aucune table 'glpi_plugin_fields_%' ne contient la colonne '{FIELD_NAME}'. "
            "Vérifie le nom système du champ."
        )

    # Priorité 1 : nom exact connu (confirmé via l'API listSearchOptions/Computer)
    if "glpi_plugin_fields_computerpropritaires" in candidates:
        return "glpi_plugin_fields_computerpropritaires"

    # Priorité 2 : tables commençant par "..._computer" mais en excluant les
    # variantes non pertinentes (computermodel, computertype, etc.)
    computer_candidates = [
        t for t in candidates
        if t.startswith("glpi_plugin_fields_computer")
        and t != "glpi_plugin_fields_computermodelpropritaires"
        and t != "glpi_plugin_fields_computertypepropritaires"
    ]
    if len(computer_candidates) == 1:
        return computer_candidates[0]

    raise RuntimeError(
        f"Impossible d'identifier sans ambiguïté la table Computer parmi : {computer_candidates or candidates}. "
        "Renseigne le nom de table manuellement dans le script."
    )


def get_table_columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (DB_NAME, table),
        )
        return {r["COLUMN_NAME"] for r in cur.fetchall()}


def get_default_container_id(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT plugin_fields_containers_id FROM `{table}` LIMIT 1")
        row = cur.fetchone()
    if row:
        return row["plugin_fields_containers_id"]
    # fallback : trouver le conteneur correspondant à cette table
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM glpi_plugin_fields_containers WHERE %s LIKE CONCAT('%%', name, '%%')",
            (table,),
        )
        row = cur.fetchone()
    if row:
        return row["id"]
    raise RuntimeError(
        "Impossible de déterminer plugin_fields_containers_id automatiquement. "
        "Renseigne-le manuellement dans le script."
    )


def build_computer_index(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, entities_id FROM glpi_computers WHERE is_deleted = 0")
        rows = cur.fetchall()
    return {(r["name"] or "").strip().lower(): r for r in rows if r["name"]}


def build_existing_records_index(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, items_id FROM `{table}` WHERE itemtype = 'Computer'"
        )
        rows = cur.fetchall()
    return {r["items_id"]: r["id"] for r in rows}


def parse_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get(CSV_NAME_COLUMN) or "").strip()
            raw_date = (row.get(CSV_DATE_COLUMN) or "").strip()
            if not name or not raw_date:
                continue
            try:
                dt = datetime.strptime(raw_date, CSV_DATE_FORMAT)
            except ValueError:
                print(f"  [!] Date illisible pour {name} : '{raw_date}' -> ignoré")
                continue
            rows.append((name, dt.strftime("%Y-%m-%d")))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simule sans écrire dans la base")
    args = parser.parse_args()

    print("Lecture du CSV...")
    rows = parse_csv(CSV_PATH)
    print(f"  {len(rows)} lignes avec une date à importer.")
    if not rows:
        print("Rien à faire.")
        return

    conn = connect()
    try:
        table = find_field_table(conn)
        print(f"Table du champ trouvée : {table}")

        columns = get_table_columns(conn, table)
        container_id = get_default_container_id(conn, table)
        print(f"plugin_fields_containers_id : {container_id}")

        print("Indexation des ordinateurs...")
        computers = build_computer_index(conn)
        print(f"  -> {len(computers)} ordinateurs en base.")

        print("Indexation des enregistrements existants...")
        existing = build_existing_records_index(conn, table)
        print(f"  -> {len(existing)} enregistrements existants.")

        not_found = []
        updated = 0
        created = 0

        with conn.cursor() as cur:
            for name, date_str in rows:
                computer = computers.get(name.lower())
                if not computer:
                    not_found.append(name)
                    continue
                computer_id = computer["id"]

                if args.dry_run:
                    action = "MAJ" if computer_id in existing else "CREATION"
                    print(f"  [dry-run] {action} {name} (id={computer_id}) -> {FIELD_NAME}={date_str}")
                    continue

                if computer_id in existing:
                    record_id = existing[computer_id]
                    set_clause = f"`{FIELD_NAME}` = %s"
                    params = [date_str]
                    if "date_mod" in columns:
                        set_clause += ", date_mod = NOW()"
                    cur.execute(
                        f"UPDATE `{table}` SET {set_clause} WHERE id = %s",
                        params + [record_id],
                    )
                    updated += 1
                    print(f"  [OK] MAJ {name} -> {date_str}")
                else:
                    cols = ["itemtype", "items_id", "plugin_fields_containers_id", FIELD_NAME]
                    vals = ["Computer", computer_id, container_id, date_str]
                    if "entities_id" in columns:
                        cols.append("entities_id")
                        vals.append(computer.get("entities_id", 0))
                    if "is_recursive" in columns:
                        cols.append("is_recursive")
                        vals.append(0)
                    if "date_creation" in columns:
                        cols.append("date_creation")
                        vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    if "date_mod" in columns:
                        cols.append("date_mod")
                        vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

                    placeholders = ", ".join(["%s"] * len(cols))
                    col_list = ", ".join(f"`{c}`" for c in cols)
                    cur.execute(
                        f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})",
                        vals,
                    )
                    created += 1
                    print(f"  [OK] CREATION {name} -> {date_str}")

        if not args.dry_run:
            conn.commit()

        print(f"\n--- Résumé ---")
        print(f"Mis à jour   : {updated}")
        print(f"Créés        : {created}")
        print(f"Non trouvés  : {len(not_found)}")
        if not_found:
            print("  " + ", ".join(not_found))
            print("\n  Recherche approchée des non-trouvés (nom similaire en base) :")
            with conn.cursor() as cur:
                for name in set(not_found):
                    cur.execute(
                        "SELECT id, name, is_deleted FROM glpi_computers WHERE name LIKE %s",
                        (f"%{name}%",),
                    )
                    matches = cur.fetchall()
                    if matches:
                        print(f"    {name} -> candidats : {matches}")
                    else:
                        print(f"    {name} -> aucun candidat trouvé (même approché)")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()