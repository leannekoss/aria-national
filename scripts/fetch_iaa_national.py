#!/usr/bin/env python3
"""
Collecte les établissements IAA actifs depuis recherche-entreprises.api.gouv.fr.

Le collector écrit un cache brut versionné dans build/raw pour que le pipeline
statique puisse reconstruire le site sans dépendance à aria-lobbying.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict

from common import RAW_DIR, ensure_dirs, utc_now_iso


NAF_ARIA = [
    "10.11Z",
    "10.12Z",
    "10.13A",
    "10.13B",
    "10.31Z",
    "10.32Z",
    "10.39A",
    "10.39B",
    "10.41A",
    "10.41B",
    "10.42Z",
    "10.51A",
    "10.51B",
    "10.51C",
    "10.51D",
    "10.52Z",
    "10.72Z",
    "10.84Z",
    "10.85Z",
    "10.86Z",
    "10.89Z",
    "11.01Z",
    "11.02A",
    "11.02B",
    "11.03Z",
    "11.07A",
    "11.07B",
]
ARTISANAL = {"10.71A", "10.71B", "10.71C", "10.71D"}
ALL_DEPTS = [f"{i:02d}" for i in range(1, 96) if i != 20] + ["2A", "2B", "971", "972", "973", "974", "976"]
ARIA_REGIONS = {
    "ARIA Sud": ["04", "05", "06", "13", "83", "84"],
    "ARIA AURA": ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"],
    "AREA Occitanie": ["09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"],
    "AREA Nouvelle Aquitaine": ["16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"],
    "AREA Normandie": ["14", "27", "50", "61", "76"],
    "AREA Île-de-France": ["75", "77", "78", "91", "92", "93", "94", "95"],
    "AREA Centre-Val de Loire": ["18", "28", "36", "37", "41", "45"],
    "AREA Pays de la Loire": ["44", "49", "53", "72", "85"],
    "Agro-Spheres": ["02", "59", "60", "62", "80"],
    "ABEA": ["22", "29", "35", "56"],
    "ARIA Grand Est": ["08", "10", "51", "52", "54", "55", "57", "67", "68", "88"],
    "Vitagora": ["21", "25", "39", "58", "70", "71", "89", "90"],
    "ADIR": ["974"],
    "AMPI": ["972"],
    "FEINC": [],
    "ARIA Corse": ["2A", "2B"],
}
DEPT_TO_ARIA = {dept: region for region, depts in ARIA_REGIONS.items() for dept in depts}

API_BASE = "https://recherche-entreprises.api.gouv.fr/search"
PER_PAGE = 25
RATE_LIMIT = 0.1
OUTPUT_FILE = RAW_DIR / "sites_iaa_national.json"
CATEGORIES_KEEP = {"PME", "ETI", "GE"}


def dept_from_siret_or_cp(siret: str, cp: str) -> str:
    if cp:
        cp = str(cp).strip().zfill(5)
        if cp.startswith("20") and len(cp) == 5:
            return "2A" if int(cp) < 20200 else "2B"
        if cp.startswith(("971", "972", "973", "974", "976")):
            return cp[:3]
        if cp.startswith("97"):
            return cp[:3]
        return cp[:2]
    if siret and len(siret) >= 5:
        prefix = siret[:5]
        if prefix[:3] in ("971", "972", "973", "974", "976"):
            return prefix[:3]
        return prefix[:2]
    return ""


def fetch_url(url: str, retries: int = 3, timeout: int = 30) -> dict | None:
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "ANIA-Static-Build/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            if attempt == retries - 1:
                print(f"  ERREUR fetch: {exc} | {url[:90]}...")
                return None
            time.sleep(1.5)
    return None


def trim_company_payload(entreprise: dict) -> dict:
    return {
        "siren": entreprise.get("siren", ""),
        "nom_complet": entreprise.get("nom_complet", ""),
        "nom_raison_sociale": entreprise.get("nom_raison_sociale", ""),
        "sigle": entreprise.get("sigle", ""),
        "categorie_entreprise": entreprise.get("categorie_entreprise", ""),
        "nature_juridique": entreprise.get("nature_juridique", ""),
        "etat_administratif": entreprise.get("etat_administratif", ""),
        "activite_principale": entreprise.get("activite_principale", ""),
        "activite_principale_naf25": entreprise.get("activite_principale_naf25", ""),
        "section_activite_principale": entreprise.get("section_activite_principale", ""),
        "tranche_effectif_salarie": entreprise.get("tranche_effectif_salarie", ""),
        "annee_tranche_effectif_salarie": entreprise.get("annee_tranche_effectif_salarie", ""),
        "date_creation": entreprise.get("date_creation", ""),
        "date_mise_a_jour": entreprise.get("date_mise_a_jour", ""),
        "date_mise_a_jour_insee": entreprise.get("date_mise_a_jour_insee", ""),
        "date_mise_a_jour_rne": entreprise.get("date_mise_a_jour_rne", ""),
        "nombre_etablissements": entreprise.get("nombre_etablissements", 0),
        "nombre_etablissements_ouverts": entreprise.get("nombre_etablissements_ouverts", 0),
        "caractere_employeur": entreprise.get("caractere_employeur", ""),
        "complements": entreprise.get("complements") or {},
        "finances": entreprise.get("finances") or {},
        "dirigeants": entreprise.get("dirigeants") or [],
        "siege": entreprise.get("siege") or {},
        "matching_etablissements": entreprise.get("matching_etablissements") or [],
    }


def fetch_all_pages(naf: str, dept: str, company_index: dict[str, dict]) -> list[dict]:
    results: list[dict] = []
    page = 1

    while True:
        params = {
            "activite_principale": naf,
            "per_page": PER_PAGE,
            "page": page,
            "etat_administratif": "A",
            "departement": dept,
        }
        url = API_BASE + "?" + urllib.parse.urlencode(params)
        data = fetch_url(url)
        time.sleep(RATE_LIMIT)
        if not data:
            break

        page_results = data.get("results", [])
        total_pages = data.get("total_pages", 1)

        for entreprise in page_results:
            categorie = entreprise.get("categorie_entreprise", "")
            if categorie not in CATEGORIES_KEEP:
                continue

            siren = entreprise.get("siren", "")
            if siren and siren not in company_index:
                company_index[siren] = trim_company_payload(entreprise)

            for etab in entreprise.get("matching_etablissements", []):
                if etab.get("etat_administratif") != "A":
                    continue
                cp = etab.get("code_postal", "")
                siret = etab.get("siret", "")
                dept_etab = dept_from_siret_or_cp(siret, cp)
                aria_region = DEPT_TO_ARIA.get(dept_etab, "Non rattaché")
                try:
                    lat = float(etab.get("latitude")) if etab.get("latitude") else None
                except (TypeError, ValueError):
                    lat = None
                try:
                    lon = float(etab.get("longitude")) if etab.get("longitude") else None
                except (TypeError, ValueError):
                    lon = None

                results.append(
                    {
                        "siren": siren,
                        "siret": siret,
                        "nom_complet": entreprise.get("nom_complet", ""),
                        "categorie_entreprise": categorie,
                        "naf": entreprise.get("activite_principale") or naf,
                        "adresse": etab.get("adresse", ""),
                        "commune": etab.get("commune", ""),
                        "code_postal": cp,
                        "dept": dept_etab,
                        "aria_region": aria_region,
                        "latitude": lat,
                        "longitude": lon,
                    }
                )

        if page >= total_pages:
            break
        page += 1

    return results


def main() -> None:
    ensure_dirs()
    print("=" * 65)
    print("ARIA IAA NATIONAL — Fetch établissements PME/ETI/GE")
    print(f"  {len(NAF_ARIA)} codes NAF | {len(ALL_DEPTS)} départements")
    print(f"  {len(NAF_ARIA) * len(ALL_DEPTS)} requêtes estimées")
    print("=" * 65)

    all_sites: dict[str, dict] = {}
    company_index: dict[str, dict] = {}
    combo_n = 0
    total_combos = len(NAF_ARIA) * len(ALL_DEPTS)
    start_time = time.time()

    for naf in NAF_ARIA:
        for dept in ALL_DEPTS:
            combo_n += 1
            if combo_n % 50 == 1 or combo_n <= 5:
                elapsed = time.time() - start_time
                rate = combo_n / elapsed if elapsed > 0 else 0
                eta_sec = (total_combos - combo_n) / rate if rate > 0 else 0
                print(
                    f"  [{combo_n}/{total_combos}] NAF {naf} dept {dept} | "
                    f"total:{len(all_sites)} | eta:{eta_sec/60:.0f}min",
                    flush=True,
                )
            elif combo_n % 10 == 0:
                print(f"  [{combo_n}/{total_combos}] ...", end="\r", flush=True)

            for site in fetch_all_pages(naf, dept=dept, company_index=company_index):
                key = site["siret"] or f'{site["siren"]}|{site["adresse"]}'
                if key not in all_sites:
                    all_sites[key] = site

    elapsed = time.time() - start_time
    region_stats = defaultdict(int)
    dept_stats = defaultdict(int)
    naf_stats = defaultdict(int)
    categorie_stats = defaultdict(int)
    for site in all_sites.values():
        region_stats[site["aria_region"]] += 1
        dept_stats[site["dept"]] += 1
        naf_stats[site["naf"]] += 1
        categorie_stats[site["categorie_entreprise"]] += 1

    payload = {
        "metadata": {
            "source": "recherche-entreprises.api.gouv.fr",
            "source_url": API_BASE,
            "collected_at": utc_now_iso(),
            "naf_codes": NAF_ARIA,
            "artisanal_excluded": sorted(ARTISANAL),
            "categories_kept": sorted(CATEGORIES_KEEP),
            "total": len(all_sites),
            "duration_seconds": round(elapsed),
            "by_region": dict(region_stats),
            "by_dept": dict(dept_stats),
            "by_naf": dict(naf_stats),
            "by_category": dict(categorie_stats),
        },
        "entreprises": company_index,
        "etablissements": list(all_sites.values()),
    }

    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSauvegarde : {OUTPUT_FILE}")
    print(f"Entreprises uniques : {len(company_index)} | Établissements uniques : {len(all_sites)}")


if __name__ == "__main__":
    main()
