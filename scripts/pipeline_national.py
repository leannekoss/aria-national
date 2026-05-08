#!/usr/bin/env python3
"""
Pipeline national ARIA/ANIA.

Construit les CSV intermédiaires utilisés par le site statique depuis les caches
présents dans build/raw et des sources officielles (Assemblée, Sénat).
"""

import csv
import io
import json
import shutil
import time
import re
import urllib.request
import urllib.parse
import zipfile
from collections import defaultdict
from pathlib import Path

from common import NORMALIZED_DIR, RAW_DIR, cache_fetch, ensure_dirs
from manual_companies import MANUAL_SITES


OUTPUT_DIR_NATIONAL = NORMALIZED_DIR
SCRUTINS_DIR = RAW_DIR / "scrutins"
SITES_FILE = RAW_DIR / "sites_iaa_national.json"
DEPUTES_AMO_ZIP = RAW_DIR / "amo10_deputes_actifs_mandats_actifs_organes.json.zip"
DEPUTES_AMO_ZIP_URL = (
    "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/"
    "deputes_actifs_mandats_actifs_organes/AMO10_deputes_actifs_mandats_actifs_organes.json.zip"
)

# Scrutins nominatifs clés pour l'analyse ARIA
SCRUTINS_CONFIG = [
    {'id': 'egalim1',     'label': 'EGALIM 1 - Équilibre relations commerciales (2018)', 'leg': 15, 'num': 1181,  'file': 'VTANR5L15V1181.json'},
    {'id': 'egalim2',     'label': 'EGALIM 2 - Protection rémunération agriculteurs (2021)', 'leg': 15, 'num': 3983, 'file': 'VTANR5L15V3983.json'},
    {'id': 'egalim3',     'label': 'EGALIM 3 / Descrozaille - Relations fournisseurs-distributeurs (2023)', 'leg': 16, 'num': 1254, 'file': 'VTANR5L16V1254.json'},
    {'id': 'loa2024',     'label': 'LOA 2024 - Souveraineté alimentaire et agricole', 'leg': 16, 'num': 3966, 'file': 'VTANR5L16V3966.json'},
    {'id': 'revenu_agri', 'label': 'PPL Revenu digne agriculteurs (2024)', 'leg': 16, 'num': 3653, 'file': 'VTANR5L16V3653.json'},
]
SCRUTIN_ZIP_URLS = {
    15: 'https://data.assemblee-nationale.fr/static/openData/repository/15/loi/scrutins/Scrutins_XV.json.zip',
    16: 'https://data.assemblee-nationale.fr/static/openData/repository/16/loi/scrutins/Scrutins.json.zip',
}

DEPT_MAP = {
    'ain': '01', 'aisne': '02', 'allier': '03', 'alpes-de-haute-provence': '04',
    'hautes-alpes': '05', 'alpes-maritimes': '06', 'ardèche': '07', 'ardennes': '08',
    'ariège': '09', 'aube': '10', 'aude': '11', 'aveyron': '12',
    'bouches-du-rhône': '13', 'calvados': '14', 'cantal': '15', 'charente': '16',
    'charente-maritime': '17', 'cher': '18', 'corrèze': '19', 'corse-du-sud': '2A',
    'haute-corse': '2B', "côte-d'or": '21', "côtes-d'armor": '22', 'creuse': '23',
    'dordogne': '24', 'doubs': '25', 'drôme': '26', 'eure': '27',
    'eure-et-loir': '28', 'finistère': '29', 'gard': '30', 'haute-garonne': '31',
    'gers': '32', 'gironde': '33', 'hérault': '34', 'ille-et-vilaine': '35',
    'indre': '36', 'indre-et-loire': '37', 'isère': '38', 'jura': '39',
    'landes': '40', 'loir-et-cher': '41', 'loire': '42', 'haute-loire': '43',
    'loire-atlantique': '44', 'loiret': '45', 'lot': '46', 'lot-et-garonne': '47',
    'lozère': '48', 'maine-et-loire': '49', 'manche': '50', 'marne': '51',
    'haute-marne': '52', 'mayenne': '53', 'meurthe-et-moselle': '54', 'meuse': '55',
    'morbihan': '56', 'moselle': '57', 'nièvre': '58', 'nord': '59',
    'oise': '60', 'orne': '61', 'pas-de-calais': '62', 'puy-de-dôme': '63',
    'pyrénées-atlantiques': '64', 'hautes-pyrénées': '65', 'pyrénées-orientales': '66',
    'bas-rhin': '67', 'haut-rhin': '68', 'rhône': '69', 'haute-saône': '70',
    'saône-et-loire': '71', 'sarthe': '72', 'savoie': '73', 'haute-savoie': '74',
    'paris': '75', 'seine-maritime': '76', 'seine-et-marne': '77', 'yvelines': '78',
    'deux-sèvres': '79', 'somme': '80', 'tarn': '81', 'tarn-et-garonne': '82',
    'var': '83', 'vaucluse': '84', 'vendée': '85', 'vienne': '86',
    'haute-vienne': '87', 'vosges': '88', 'yonne': '89', 'territoire de belfort': '90',
    'essonne': '91', 'hauts-de-seine': '92', 'seine-saint-denis': '93',
    'val-de-marne': '94', "val-d'oise": '95',
    'guadeloupe': '971', 'martinique': '972', 'guyane': '973',
    'la réunion': '974', 'mayotte': '976',
    # variantes
    "côte d'or": '21', "côtes d'armor": '22', "val d'oise": '95',
    'seine saint-denis': '93', 'hauts de seine': '92',
    'puy de dôme': '63', 'corse du sud': '2A', 'haute corse': '2B',
    'bas rhin': '67', 'haut rhin': '68',
}


def normalize(s):
    import unicodedata
    s = unicodedata.normalize('NFD', s.lower().strip())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def fetch_url(url, encoding='utf-8', retries=3, timeout=60):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ARIA-Lobbying-Pipeline/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return raw if encoding is None else raw.decode(encoding, errors='replace')
        except Exception as e:
            if attempt == retries - 1:
                print(f"  Erreur fetch {url}: {e}")
                return None
            time.sleep(1)


# ============================================================
# ÉTAPE 1 — Charger les sites IAA NATIONAUX
# ============================================================
def load_sites_national():
    """Charge les sites IAA France entière depuis sites_iaa_national.json.
    Tous les départements. Tous PME/ETI/GE (déjà filtré à la collecte)."""
    print(f"\n[1] Chargement des sites IAA nationaux ({SITES_FILE.name})...")
    with open(SITES_FILE, encoding='utf-8') as f:
        raw = json.load(f)
    etabs = raw['etablissements']

    sites = []
    groupes = {}
    for e in etabs:
        site = {
            'nom_entreprise_aria': e['nom_complet'],
            'nom_api': e['nom_complet'],
            'siren': e['siren'],
            'siret': e['siret'],
            'categorie_entreprise': e.get('categorie_entreprise', ''),
            'syndicat_regional': e.get('aria_region', ''),
            'code_dept': e.get('dept', ''),
            'adresse': e.get('adresse', ''),
            'commune': e.get('commune', ''),
            'code_postal': e.get('code_postal', ''),
            'naf': e.get('naf', ''),
            'aria_region': e.get('aria_region', ''),
            'latitude': e.get('latitude', 0),
            'longitude': e.get('longitude', 0),
        }
        sites.append(site)
        siren = e['siren']
        if siren not in groupes:
            groupes[siren] = {'nom': e['nom_complet'], 'nb_sites': 0, 'departements': set(), 'sites': []}
        groupes[siren]['nb_sites'] += 1
        groupes[siren]['departements'].add(e.get('dept', ''))
        groupes[siren]['sites'].append(site)

    existing_site_keys = {site.get('siret') or f"{site.get('siren')}|{site.get('adresse')}" for site in sites}
    for e in MANUAL_SITES:
        key = e.get('siret') or f"{e.get('siren')}|{e.get('adresse')}"
        if key in existing_site_keys:
            continue
        site = {
            'nom_entreprise_aria': e['nom_complet'],
            'nom_api': e['nom_complet'],
            'siren': e['siren'],
            'siret': e['siret'],
            'categorie_entreprise': e.get('categorie_entreprise', ''),
            'syndicat_regional': e.get('aria_region', ''),
            'code_dept': e.get('dept', ''),
            'adresse': e.get('adresse', ''),
            'commune': e.get('commune', ''),
            'code_postal': e.get('code_postal', ''),
            'naf': e.get('naf', ''),
            'aria_region': e.get('aria_region', ''),
            'latitude': e.get('latitude', 0),
            'longitude': e.get('longitude', 0),
        }
        sites.append(site)
        siren = e['siren']
        if siren not in groupes:
            groupes[siren] = {'nom': e['nom_complet'], 'nb_sites': 0, 'departements': set(), 'sites': []}
        groupes[siren]['nb_sites'] += 1
        groupes[siren]['departements'].add(e.get('dept', ''))
        groupes[siren]['sites'].append(site)
        existing_site_keys.add(key)

    print(f"    {len(etabs)} établissements bruts")
    print(f"    {len(sites)} sites retenus, {len(groupes)} groupes (SIREN uniques)")
    return sites, groupes


# ============================================================
# ÉTAPE 3 — Charger les parlementaires
# ============================================================
def load_deputes():
    print("\n[3a] Chargement des députés (Assemblée nationale AMO10)...")
    raw_amo, refreshed = cache_fetch(
        DEPUTES_AMO_ZIP_URL,
        DEPUTES_AMO_ZIP,
        max_age_hours=24,
        binary=True,
        timeout=120,
    )
    if refreshed:
        print(f"    Bundle AMO10 rafraîchi dans {DEPUTES_AMO_ZIP}")

    kw_agri = ['agriculture', 'alimenta', 'agroalim', 'rural', 'viticulture', 'filière']
    kw_eco = ['économiques', 'industrie', 'commerce', 'entreprise', 'distribut', 'consommat']
    kw_env = ['développement durable', 'transition', 'environnement', 'emballage', 'énergie']
    kw_egal = ['egalim', 'relations commerciales', 'grande distribution', 'fournisseur']

    deputes = []
    with zipfile.ZipFile(io.BytesIO(raw_amo)) as zf:
        organes = {}
        for name in zf.namelist():
            if not name.startswith('json/organe/') or not name.endswith('.json'):
                continue
            org = json.loads(zf.read(name)).get('organe', {})
            organes[org.get('uid', '')] = {
                'codeType': org.get('codeType', ''),
                'libelle': org.get('libelle', ''),
                'libelleAbrege': org.get('libelleAbrege', ''),
            }

        for name in zf.namelist():
            if not name.startswith('json/acteur/') or not name.endswith('.json'):
                continue
            acteur = json.loads(zf.read(name)).get('acteur', {})
            ident = acteur.get('etatCivil', {}).get('ident', {})
            acteur_id = acteur.get('uid', {}).get('#text', '')
            mandats = acteur.get('mandats', {}).get('mandat', [])
            if isinstance(mandats, dict):
                mandats = [mandats]

            mandat_principal = next(
                (m for m in mandats if m.get('typeOrgane') == 'ASSEMBLEE' and not m.get('dateFin')),
                None,
            )
            if not mandat_principal:
                continue

            election = mandat_principal.get('election', {}).get('lieu', {})
            dept = election.get('numDepartement', '') or DEPT_MAP.get(normalize(election.get('departement', '')), '')
            groupe = ''
            groupe_abrev = ''
            commission = ''
            flags = {'agri': False, 'eco': False, 'env': False, 'egalim': False}
            nb_commissions = 0

            for mandat in mandats:
                organes_ref = mandat.get('organes', {}).get('organeRef', '')
                if isinstance(organes_ref, str):
                    organes_refs = [organes_ref]
                elif isinstance(organes_ref, list):
                    organes_refs = organes_ref
                else:
                    organes_refs = []
                for org_ref in organes_refs:
                    org = organes.get(org_ref, {})
                    if mandat.get('typeOrgane') == 'GP' and org:
                        groupe = org.get('libelle', groupe)
                        groupe_abrev = org.get('libelleAbrege', groupe_abrev)
                    lib = (org.get('libelle') or '').lower()
                    is_agri = any(k in lib for k in kw_agri)
                    is_eco = any(k in lib for k in kw_eco)
                    is_env = any(k in lib for k in kw_env)
                    is_egal = any(k in lib for k in kw_egal)
                    if any((is_agri, is_eco, is_env, is_egal)):
                        nb_commissions += 1
                        commission = commission or org.get('libelle', '')
                        flags['agri'] = flags['agri'] or is_agri
                        flags['eco'] = flags['eco'] or is_eco
                        flags['env'] = flags['env'] or is_env
                        flags['egalim'] = flags['egalim'] or is_egal

            deputes.append({
                'id': acteur_id,
                'chambre': 'AN',
                'nom': ident.get('nom', ''),
                'prenom': ident.get('prenom', ''),
                'nom_complet': f"{ident.get('nom', '')} {ident.get('prenom', '')}".strip(),
                'groupe': groupe or 'Non inscrit',
                'groupe_abrev': groupe_abrev or (groupe[:10] if groupe else ''),
                'code_dept': dept,
                'nom_dept': election.get('departement', ''),
                'circo': election.get('numCirco', ''),
                'score_participation': 0.0,
                'score_loyaute': 0.0,
                'mail': '',
                'twitter': '',
                'commission': commission,
                'membre_commission_agri': flags['agri'],
                'membre_commission_eco': flags['eco'],
                'membre_commission_env': flags['env'],
                'membre_mission_egalim': flags['egalim'],
                'nb_commissions_aria': nb_commissions,
            })

    print(f"    {len(deputes)} députés chargés")
    return deputes


def load_senateurs():
    print("\n[3b] Chargement des sénateurs (data.senat.fr)...")
    raw = fetch_url('https://data.senat.fr/data/senateurs/ODSEN_GENERAL.csv', encoding='latin-1')
    if not raw:
        return []

    lines = [l for l in raw.split('\n') if not l.startswith('%') and l.strip()]
    reader = csv.DictReader(iter(lines))

    senateurs = []
    for row in reader:
        if row.get('État', '').strip() != 'ACTIF':
            continue
        dept_lib = row.get('Circonscription', '').strip()
        code_dept = DEPT_MAP.get(normalize(dept_lib), '')

        senateurs.append({
            'id': row.get('Matricule', ''),
            'chambre': 'SEN',
            'nom': row.get('Nom usuel', ''),
            'prenom': row.get('Prénom usuel', ''),
            'nom_complet': f"{row.get('Nom usuel', '')} {row.get('Prénom usuel', '')}",
            'groupe': row.get('Groupe politique', ''),
            'groupe_abrev': row.get('Groupe politique', '')[:10],
            'code_dept': code_dept,
            'nom_dept': dept_lib,
            'circo': '',
            'score_participation': 0.0,
            'score_loyaute': 0.0,
            'mail': row.get('Courrier électronique', ''),
            'twitter': '',
            'commission': row.get('Commission permanente', ''),
            'membre_commission_agri': False,
            'membre_commission_eco': False,
            'membre_commission_env': False,
            'membre_mission_egalim': False,
            'nb_commissions_aria': 0,
            'position_votes_agri': 'inconnu (Sénat)',
        })
    print(f"    {len(senateurs)} sénateurs actifs chargés")
    return senateurs


# ============================================================
# ÉTAPE 4 — Enrichir avec commissions et missions
# ============================================================
def enrich_commissions_senat(senateurs):
    print("\n[4a] Enrichissement commissions Sénat...")
    raw = fetch_url('https://data.senat.fr/data/senateurs/ODSEN_CUR_COMS.csv', encoding='latin-1')
    if not raw:
        return senateurs

    lines = [l for l in raw.split('\n') if not l.startswith('%') and l.strip()]
    reader = csv.DictReader(iter(lines))

    sen_commissions = defaultdict(list)
    for row in reader:
        matricule = row.get('Matricule', '')
        nom_com = row.get('Nom commission', '').lower()
        type_com = row.get('Type commission', '')
        sen_commissions[matricule].append({'nom': nom_com, 'type': type_com})

    kw_agri  = ['agriculture', 'alimenta', 'agroalim', 'rurale', 'rural', 'viande',
                'viticulture', 'arboricult', 'huile', 'produit laitier', 'filière']
    kw_eco   = ['économi', 'commerce', 'industrie', 'distribut', 'consommat',
                'relation commerc', 'entreprise', 'compétitivité']
    kw_env   = ['développement durable', 'transition écolog', 'environnement',
                'emballage', 'recyclage', 'plastique', 'énergie renouvelable']
    kw_egal  = ['egalim', 'grande distribution', 'marge', 'fournisseur distributeur',
                'relations commerciales agricoles']

    idx_sen = {s['id']: s for s in senateurs}
    for mat, coms in sen_commissions.items():
        s = idx_sen.get(mat)
        if not s:
            continue
        for com in coms:
            nom = com['nom']
            if any(k in nom for k in kw_agri):
                s['membre_commission_agri'] = True
                s['nb_commissions_aria'] += 1
            if any(k in nom for k in kw_eco):
                s['membre_commission_eco'] = True
                s['nb_commissions_aria'] += 1
            if any(k in nom for k in kw_env):
                s['membre_commission_env'] = True
                s['nb_commissions_aria'] += 1
            if any(k in nom for k in kw_egal):
                s['membre_mission_egalim'] = True
                s['nb_commissions_aria'] += 1

    nb_enrichis = sum(1 for s in senateurs if s['nb_commissions_aria'] > 0)
    print(f"    {nb_enrichis} sénateurs avec commissions ARIA pertinentes")
    return senateurs


def enrich_commissions_deputes(deputes):
    """Les commissions AN sont déjà intégrées lors du chargement AMO10.

    L'ancienne étape AMO30 ciblait des URLs de législature obsolètes et
    provoquait des 404. On garde cette fonction pour préserver l'ordre du
    pipeline sans ajouter un second fetch fragile.
    """
    print("\n[4b] Enrichissement commissions AN déjà intégré via AMO10")
    nb_enrichis = sum(1 for d in deputes if d.get('nb_commissions_aria', 0) > 0)
    print(f"    {nb_enrichis} députés avec commission ou mission pertinente")
    return deputes


# ============================================================
# ÉTAPE 4c — Votes nominatifs EGALIM et textes agricoles (AN)
# ============================================================
def extract_votes(json_path):
    with open(json_path, encoding='utf-8') as f:
        d = json.load(f)
    sc = d.get('scrutin', {})
    votes = {}
    ventilation = sc.get('ventilationVotes', {})
    organe = ventilation.get('organe', {})
    groupes_raw = organe.get('groupes', {}).get('groupe', [])
    if not isinstance(groupes_raw, list):
        groupes_raw = [groupes_raw]

    for groupe in groupes_raw:
        vote = groupe.get('vote', {})
        decompte = vote.get('decompteNominatif', {})
        if not decompte:
            continue
        for cat_key, position in [('pours', 'pour'), ('contres', 'contre'),
                                   ('abstentions', 'abstention'), ('nonVotants', 'absent')]:
            cat = decompte.get(cat_key, {})
            if not cat:
                continue
            votants = cat.get('votant', [])
            if not isinstance(votants, list):
                votants = [votants] if votants else []
            for v in votants:
                if v and v.get('acteurRef'):
                    votes[v['acteurRef']] = position
    return votes


def load_scrutins_votes():
    print("\n[4c] Chargement des votes nominatifs EGALIM / agricoles...")
    SCRUTINS_DIR.mkdir(exist_ok=True)

    for sc in SCRUTINS_CONFIG:
        dst = SCRUTINS_DIR / sc['file']
        if not dst.exists():
            for tmp_base in [f'/tmp/scrutins{sc["leg"]}_key', f'/tmp/scrutins{sc["leg"]}']:
                tmp = Path(tmp_base) / 'json' / sc['file']
                if tmp.exists():
                    shutil.copy(tmp, dst)
                    break

    for leg in [15, 16]:
        missing = [sc for sc in SCRUTINS_CONFIG if sc['leg'] == leg
                   and not (SCRUTINS_DIR / sc['file']).exists()]
        if missing:
            print(f"  Téléchargement ZIP legislature {leg} (peut prendre 30s)...")
            raw = fetch_url(SCRUTIN_ZIP_URLS[leg], encoding=None)
            if raw:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for sc in missing:
                        try:
                            data = zf.read(f'json/{sc["file"]}')
                            (SCRUTINS_DIR / sc['file']).write_bytes(data)
                            print(f"    OK {sc['file']}")
                        except KeyError:
                            print(f"    MANQUANT {sc['file']} absent du ZIP")

    votes_by_scrutin = {}
    for sc in SCRUTINS_CONFIG:
        path = SCRUTINS_DIR / sc['file']
        if path.exists():
            v = extract_votes(path)
            votes_by_scrutin[sc['id']] = v
            print(f"  OK {sc['label'][:50]}: {len(v)} votes nominatifs")
        else:
            votes_by_scrutin[sc['id']] = {}
            print(f"  MANQUANT {sc['label'][:50]}: fichier manquant")
    return votes_by_scrutin


def enrich_votes_deputes(parlementaires, votes_by_scrutin):
    print("\n[4d] Enrichissement votes parlementaires...")
    vote_ids = [sc['id'] for sc in SCRUTINS_CONFIG]

    for p in parlementaires:
        for vid in vote_ids:
            p[f'vote_{vid}'] = None

    enrichis = 0
    for p in parlementaires:
        if p['chambre'] != 'AN':
            continue
        pa_id = p['id']
        for sc_cfg in SCRUTINS_CONFIG:
            vid = sc_cfg['id']
            pos = votes_by_scrutin.get(vid, {}).get(pa_id)
            if pos:
                p[f'vote_{vid}'] = pos
                enrichis += 1

    # EGALIM 3 (Descrozaille 2023) poids 2 : le plus récent et le plus spécifique
    # aux relations fournisseurs-distributeurs (cœur du dossier ARIA)
    VOTE_WEIGHT = {'egalim1': 1, 'egalim2': 1, 'egalim3': 2, 'loa2024': 1, 'revenu_agri': 1}
    for p in parlementaires:
        score = 0
        n = 0
        for vid, w in VOTE_WEIGHT.items():
            v = p.get(f'vote_{vid}')
            if v == 'pour':
                score += w
            elif v == 'contre':
                score -= w
            if v is not None and v != 'absent':
                n += 1

        # Score EGALIM spécifique (dossier ARIA prioritaire)
        score_egal = 0
        for vid in ['egalim1', 'egalim2', 'egalim3']:
            v = p.get(f'vote_{vid}')
            w = VOTE_WEIGHT[vid]
            if v == 'pour':
                score_egal += w
            elif v == 'contre':
                score_egal -= w
        if p['membre_mission_egalim']:
            score_egal += 2
        p['score_egalim'] = round(score_egal, 1)

        if n == 0:
            p['position_votes_agri'] = 'inconnu'
        elif score >= 5:
            p['position_votes_agri'] = 'très pro-filière IAA'
        elif score > 0:
            p['position_votes_agri'] = 'pro-filière IAA'
        elif score == 0:
            p['position_votes_agri'] = 'neutre / partagé'
        else:
            p['position_votes_agri'] = 'réservé sur régulation IAA'

    print(f"  {enrichis} votes individuels enrichis")
    return parlementaires


# ============================================================
# ÉTAPE 5 — Agréger les sites ARIA par département
# ============================================================
def aggregate_by_dept(sites):
    print("\n[5] Agrégation des sites ARIA par département...")
    by_dept = defaultdict(lambda: {
        'nb_sites': 0, 'nb_viande': 0, 'nb_boissons': 0, 'nb_vins': 0,
        'nb_laitier': 0, 'nb_fruits_legumes': 0, 'nb_huiles': 0,
        'entreprises': set(), 'coords': [], 'aria_regions': set(),
    })

    for site in sites:
        dept = site['code_dept']
        if not dept:
            continue
        naf = site.get('naf', '')
        by_dept[dept]['nb_sites'] += 1
        by_dept[dept]['entreprises'].add(site['nom_api'])
        if site.get('aria_region'):
            by_dept[dept]['aria_regions'].add(site['aria_region'])
        if site.get('latitude') and site.get('longitude'):
            try:
                by_dept[dept]['coords'].append({
                    'lat': float(site['latitude']),
                    'lng': float(site['longitude']),
                    'nom': site['nom_entreprise_aria'],
                    'adresse': site['adresse'],
                    'naf': naf,
                })
            except (ValueError, TypeError):
                pass
        if naf.startswith('10.1') and naf <= '10.13B':
            by_dept[dept]['nb_viande'] += 1
        elif naf.startswith('11.02'):  # vins AOC + autres vins
            by_dept[dept]['nb_vins'] += 1
            by_dept[dept]['nb_boissons'] += 1
        elif naf.startswith('11.'):
            by_dept[dept]['nb_boissons'] += 1
        elif naf.startswith('10.5'):
            by_dept[dept]['nb_laitier'] += 1
        elif naf.startswith('10.3'):
            by_dept[dept]['nb_fruits_legumes'] += 1
        elif naf.startswith('10.41') or naf.startswith('10.42'):
            by_dept[dept]['nb_huiles'] += 1

    print(f"    {len(by_dept)} départements avec au moins 1 site ARIA")
    return by_dept


# ============================================================
# ÉTAPE 5b — Agréger les sites ARIA par région ARIA
# ============================================================
def aggregate_by_aria_region(sites):
    print("\n[5b] Agrégation des sites ARIA par région ARIA...")
    by_region = defaultdict(lambda: {
        'nb_sites': 0, 'depts': defaultdict(int),
    })
    parl_by_region = defaultdict(list)  # filled later in join_and_score

    for site in sites:
        region = site.get('aria_region', 'Non rattaché') or 'Non rattaché'
        dept = site.get('code_dept', '')
        by_region[region]['nb_sites'] += 1
        if dept:
            by_region[region]['depts'][dept] += 1

    for region, data in by_region.items():
        top3 = sorted(data['depts'].items(), key=lambda x: -x[1])[:3]
        data['top3_depts'] = top3

    print(f"    {len(by_region)} régions ARIA identifiées")
    return by_region


# ============================================================
# ÉTAPE 6 — Jointure parlementaires × sites ARIA + scoring
# ============================================================
def join_and_score(parlementaires, by_dept):
    print("\n[6] Jointure et scoring...")

    for p in parlementaires:
        dept = p['code_dept']
        dept_data = by_dept.get(dept, {})

        nb_sites = dept_data.get('nb_sites', 0)
        p['nb_sites_aria'] = nb_sites
        p['nb_sites_viande'] = dept_data.get('nb_viande', 0)
        p['nb_sites_boissons'] = dept_data.get('nb_boissons', 0)
        p['nb_sites_vins'] = dept_data.get('nb_vins', 0)
        p['nb_sites_laitier'] = dept_data.get('nb_laitier', 0)
        p['nb_sites_fruits_legumes'] = dept_data.get('nb_fruits_legumes', 0)
        p['nb_sites_huiles'] = dept_data.get('nb_huiles', 0)
        p['entreprises_aria_zone'] = '; '.join(sorted(dept_data.get('entreprises', set())))
        p['aria_regions_zone'] = '; '.join(sorted(dept_data.get('aria_regions', set())))

        score_eco = nb_sites
        score_impl = (
            (3 if p['membre_commission_agri'] else 0)
            + (2 if p['membre_mission_egalim'] else 0)
            + (1 if p['membre_commission_eco'] else 0)
            + (1 if p.get('membre_commission_env') else 0)
            + p.get('score_participation', 0) * 0.5
        )

        # Score emballages : pression réglementaire PPWR (pertinent si beaucoup de sites boissons/laitier)
        score_emb = (
            (3 if p.get('membre_commission_env') else 0)
            + (1 if dept_data.get('nb_boissons', 0) > 10 else 0)
            + (1 if dept_data.get('nb_laitier', 0) > 5 else 0)
        )

        p['score_eco'] = round(score_eco, 1)
        p['score_implication'] = round(score_impl, 1)
        p['score_aria'] = round(score_eco * (1 + score_impl / 10), 2)
        p['score_emballages'] = round(score_emb, 1)
        if 'score_egalim' not in p:
            p['score_egalim'] = 0.0

    parlementaires.sort(key=lambda p: -p['score_aria'])
    print(f"    {sum(1 for p in parlementaires if p['nb_sites_aria'] > 0)} parlementaires en zone ARIA")
    return parlementaires


# ============================================================
# ÉTAPE 7 — Exports CSV
# ============================================================
def export_sites(sites):
    path = OUTPUT_DIR_NATIONAL / 'sites_production_national.csv'
    fields = ['nom_entreprise_aria', 'nom_api', 'siren', 'siret', 'categorie_entreprise',
              'syndicat_regional', 'code_dept', 'adresse', 'commune', 'code_postal',
              'naf', 'aria_region', 'latitude', 'longitude']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(sites)
    print(f"    OK {path.name} ({len(sites)} sites)")


def export_parlementaires(parlementaires):
    path = OUTPUT_DIR_NATIONAL / 'parlementaires_national.csv'
    vote_fields = [f'vote_{sc["id"]}' for sc in SCRUTINS_CONFIG]
    fields = [
        'id', 'nom', 'prenom', 'nom_complet', 'chambre', 'groupe', 'groupe_abrev', 'code_dept', 'nom_dept',
        'circo', 'commission', 'membre_commission_agri', 'membre_commission_eco',
        'membre_commission_env', 'membre_mission_egalim', 'nb_commissions_aria',
        'score_participation', 'score_loyaute',
        'nb_sites_aria', 'nb_sites_viande', 'nb_sites_boissons', 'nb_sites_vins',
        'nb_sites_laitier', 'nb_sites_fruits_legumes', 'nb_sites_huiles',
        'score_eco', 'score_implication', 'score_aria', 'score_egalim', 'score_emballages',
        'aria_regions_zone', 'entreprises_aria_zone', 'position_votes_agri',
    ] + vote_fields + ['mail', 'twitter']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(parlementaires)
    print(f"    OK {path.name} ({len(parlementaires)} parlementaires)")


def export_analyse_partis(parlementaires):
    path = OUTPUT_DIR_NATIONAL / 'analyse_partis_national.csv'

    partis = defaultdict(lambda: {
        'groupe': '', 'chambre': '', 'nb_elus': 0, 'nb_elus_zone_aria': 0,
        'total_sites_zones': 0, 'score_moyen': 0, 'scores': [],
    })

    for p in parlementaires:
        key = (p['groupe'], p['chambre'])
        d = partis[key]
        d['groupe'] = p['groupe']
        d['chambre'] = p['chambre']
        d['nb_elus'] += 1
        if p['nb_sites_aria'] > 0:
            d['nb_elus_zone_aria'] += 1
        d['total_sites_zones'] += p['nb_sites_aria']
        d['scores'].append(p['score_aria'])

    rows = []
    for key, d in partis.items():
        scores = d.pop('scores')
        d['score_moyen'] = round(sum(scores) / len(scores), 2) if scores else 0
        d['pct_elus_zone_aria'] = round(100 * d['nb_elus_zone_aria'] / d['nb_elus'], 1) if d['nb_elus'] else 0
        rows.append(d)

    rows.sort(key=lambda r: -r['total_sites_zones'])

    fields = ['groupe', 'chambre', 'nb_elus', 'nb_elus_zone_aria', 'pct_elus_zone_aria',
              'total_sites_zones', 'score_moyen']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"    OK {path.name} ({len(rows)} groupes/chambres)")


def export_groupes_multisite(groupes):
    path = OUTPUT_DIR_NATIONAL / 'groupes_industriels_multisite_national.csv'
    rows = []
    for siren, g in groupes.items():
        depts = sorted(g['departements'])
        rows.append({
            'siren': siren,
            'nom_complet': g['nom'],
            'nb_sites': g['nb_sites'],
            'nb_departements': len(depts),
            'departements': ', '.join(depts),
        })
    rows.sort(key=lambda r: -r['nb_departements'])

    fields = ['nom_complet', 'siren', 'nb_sites', 'nb_departements', 'departements']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"    OK {path.name} ({len(rows)} groupes)")


# ============================================================
# MAIN
# ============================================================
def main():
    ensure_dirs()
    print("=" * 60)
    print("PIPELINE ARIA LOBBYING — IAA NATIONAL")
    print("=" * 60)

    if not SITES_FILE.exists():
        print(f"Cache brut manquant ({SITES_FILE.name}), lancement de la collecte IAA...")
        from fetch_iaa_national import main as fetch_iaa_main

        fetch_iaa_main()

    # Étape 1 : sites IAA NATIONAUX
    sites, groupes = load_sites_national()

    # Étape 3 : parlementaires
    deputes = load_deputes()
    senateurs = load_senateurs()

    # Étape 4 : enrichissement commissions + votes
    senateurs = enrich_commissions_senat(senateurs)
    deputes = enrich_commissions_deputes(deputes)
    parlementaires = deputes + senateurs

    # Étape 4c : votes nominatifs EGALIM
    votes_data = load_scrutins_votes()
    parlementaires = enrich_votes_deputes(parlementaires, votes_data)

    # Étape 5 : agrégation ARIA par département
    by_dept = aggregate_by_dept(sites)

    # Étape 6 : jointure + scoring
    parlementaires = join_and_score(parlementaires, by_dept)

    # Étape 7 : exports CSV
    print("\n[7] Export des fichiers CSV...")
    export_sites(sites)
    export_parlementaires(parlementaires)
    export_analyse_partis(parlementaires)
    export_groupes_multisite(groupes)

    print("\n" + "=" * 60)
    print(f"PIPELINE TERMINE — Fichiers dans {OUTPUT_DIR_NATIONAL}/")
    print("=" * 60)

    # Aperçu TOP 10
    print("\nTOP 10 parlementaires nationaux (par score_aria) :")
    for p in parlementaires[:10]:
        marker = "AN" if p['chambre'] == 'AN' else "SE"
        print(f"  [{marker}] {p['nom_complet']:<30} | {p.get('groupe_abrev',''):<10} | Dept {p['code_dept']} | Score {p['score_aria']}")


if __name__ == '__main__':
    main()
