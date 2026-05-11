#!/usr/bin/env python3
"""Generate the static ANIA cockpit from normalized CSV/JSON inputs."""

import csv
import json
from collections import defaultdict

from common import ASSETS_DIR, DATA_DIR, NORMALIZED_DIR, RAW_DIR, ROOT_DIR, ensure_dirs, read_json, write_json
from manual_companies import MANUAL_COMPANY_INDEX, MANUAL_SITES

OUTPUT_DIR = NORMALIZED_DIR
SITE_DIR = ROOT_DIR
LOCAL_GEOJSON = "assets/departements-version-simplifiee.geojson"

SCRUTINS_META = [
    {'id': 'egalim1',     'label': 'EGALIM 1 (2018)', 'loi': '2018-938'},
    {'id': 'egalim2',     'label': 'EGALIM 2 (2021)', 'loi': '2021-1357'},
    {'id': 'egalim3',     'label': 'EGALIM 3 / Descrozaille (2023)', 'loi': '2023-221'},
    {'id': 'loa2024',     'label': 'LOA 2024', 'loi': 'PLOA-2024'},
    {'id': 'revenu_agri', 'label': 'PPL Revenu agri (2024)', 'loi': 'PPL'},
]

# 16 associations ARIA régionales
ARIA_REGIONS = [
    'AREA Occitanie', 'AREA Nouvelle Aquitaine', 'ARIA AURA', 'ARIA Grand Est',
    'ARIA Sud', 'AREA Île-de-France', 'ABEA', 'AREA Pays de la Loire',
    'Vitagora', 'Agro-Spheres', 'AREA Normandie', 'AREA Centre-Val de Loire',
    'ADIR', 'ARIA Corse', 'AMPI', 'Non rattaché',
]

GROUP_COLORS = {
    'RN': '#003189', 'DR': '#4b0082', 'NFP': '#e31d1c', 'EPR': '#ff8c00',
    'LIOT': '#008000', 'UDR': '#6a0dad', 'GDR': '#cc0000', 'Ensemble': '#ff8c00',
    'Socialistes': '#e31d1c', 'Écologiste': '#00aa44', 'LFI': '#cc0000',
}

def group_color(groupe):
    for k, v in GROUP_COLORS.items():
        if k.lower() in groupe.lower():
            return v
    return '#666'


def csv_to_list(path):
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def build_json_data():
    print('[1] Chargement des CSV nationaux et génération JSON...')
    ensure_dirs()

    # Parlementaires
    parl = csv_to_list(OUTPUT_DIR / 'parlementaires_national.csv')
    parl_json = []
    for p in parl:
        votes = {sc['id']: (p.get(f'vote_{sc["id"]}') or None) for sc in SCRUTINS_META}
        parl_json.append({
            'id': p.get('id', '') or p.get('nom_complet', '').lower().replace(' ', '-'),
            'nom': p['nom_complet'],
            'chambre': p['chambre'],
            'groupe': p['groupe'],
            'groupe_abrev': p.get('groupe_abrev', p['groupe'][:6]),
            'dept': p['code_dept'],
            'nom_dept': p['nom_dept'],
            'circo': p.get('circo', ''),
            'commission': p.get('commission', ''),
            'commission_agri': p.get('membre_commission_agri', '') == 'True',
            'commission_eco': p.get('membre_commission_eco', '') == 'True',
            'commission_env': p.get('membre_commission_env', '') == 'True',
            'mission_egalim': p.get('membre_mission_egalim', '') == 'True',
            'nb_commissions': int(p.get('nb_commissions_aria', 0) or 0),
            'participation': float(p.get('score_participation', 0) or 0),
            'loyaute': float(p.get('score_loyaute', 0) or 0),
            'nb_sites': int(p.get('nb_sites_aria', 0) or 0),
            'nb_vins': int(p.get('nb_sites_vins', 0) or 0),
            'nb_huiles': int(p.get('nb_sites_huiles', 0) or 0),
            'score_eco': float(p.get('score_eco', 0) or 0),
            'score_impl': float(p.get('score_implication', 0) or 0),
            'score_egalim': float(p.get('score_egalim', 0) or 0),
            'score_emballages': float(p.get('score_emballages', 0) or 0),
            'aria_regions': p.get('aria_regions_zone', ''),
            'score': round(
                float(p.get('score_eco', 0) or 0) *
                (1 + float(p.get('score_implication', 0) or 0) / 10),
                2
            ),
            'position': p.get('position_votes_agri', 'inconnu'),
            'entreprises': p.get('entreprises_aria_zone', ''),
            'mail': p.get('mail', ''),
            'twitter': p.get('twitter', ''),
            'votes': votes,
        })
    write_json(DATA_DIR / 'parlementaires.json', parl_json)
    print(f'    OK parlementaires.json ({len(parl_json)} entrees)')

    # Sites de production
    sites_raw = csv_to_list(OUTPUT_DIR / 'sites_production_national.csv')
    naf_labels = {
        '10.11Z': 'Abattage / transformation viande', '10.12Z': 'Transformation volaille',
        '10.13A': 'Preparation industrielle viande', '10.13B': 'Charcuterie',
        '10.31Z': 'Transformation pommes de terre', '10.32Z': 'Preparation jus de fruits/legumes',
        '10.39A': 'Autres legumes (surgeles)', '10.39B': 'Transformation fruits/legumes (autre)',
        '10.41A': 'Huile olive vierge', '10.41B': 'Autres huiles vegetales brutes',
        '10.51A': 'Lait liquide / creme', '10.51C': 'Beurre', '10.51D': 'Fromage',
        '10.52Z': 'Glaces et sorbets', '10.72Z': 'Biscuits et patisseries',
        '10.84Z': 'Condiments et assaisonnements', '10.85Z': 'Plats prepares',
        '10.86Z': 'Aliments homogeneises / dietetiques', '10.89Z': 'Autres produits alimentaires',
        '11.01Z': 'Eaux-de-vie naturelles', '11.02A': 'Vins AOC', '11.02B': 'Autres vins',
        '11.03Z': 'Cidre / autres vins de fruits', '11.07A': 'Eaux minerales',
        '11.07B': 'Limonades et boissons',
        '46.33Z': 'Commerce de gros produits laitiers',
    }
    sites_json = []
    for s in sites_raw:
        try:
            lat = float(s['latitude']) if s.get('latitude') else None
            lng = float(s['longitude']) if s.get('longitude') else None
        except (ValueError, TypeError):
            lat = lng = None
        if not lat or not lng:
            continue
        sites_json.append({
            'nom': s['nom_entreprise_aria'],
            'siren': s.get('siren', ''),
            'syndicat': s.get('syndicat_regional', ''),
            'aria_region': s.get('aria_region', ''),
            'dept': s['code_dept'],
            'commune': s.get('commune', ''),
            'cp': s.get('code_postal', ''),
            'naf': s.get('naf', ''),
            'naf_label': naf_labels.get(s.get('naf', ''), s.get('naf', '')),
            'lat': lat,
            'lng': lng,
        })
    write_json(DATA_DIR / 'sites.json', sites_json)
    print(f'    OK sites.json ({len(sites_json)} sites avec coordonnees)')

    # Partis
    partis_raw = csv_to_list(OUTPUT_DIR / 'analyse_partis_national.csv')
    partis_json = [
        {
            'groupe': p['groupe'],
            'chambre': p['chambre'],
            'nb_elus': int(p.get('nb_elus', 0) or 0),
            'nb_elus_zone': int(p.get('nb_elus_zone_aria', 0) or 0),
            'pct_zone': float(p.get('pct_elus_zone_aria', 0) or 0),
            'total_sites': int(p.get('total_sites_zones', 0) or 0),
            'score_moyen': float(p.get('score_moyen', 0) or 0),
            'color': group_color(p['groupe']),
        }
        for p in partis_raw
    ]
    write_json(DATA_DIR / 'partis.json', partis_json)
    print(f'    OK partis.json ({len(partis_json)} groupes)')

    # Groupes industriels
    groupes_enrichis = OUTPUT_DIR / 'groupes_industriels_enrichis.csv'
    groupes_source = groupes_enrichis if groupes_enrichis.exists() else OUTPUT_DIR / 'groupes_industriels_multisite_national.csv'
    groupes_raw = csv_to_list(groupes_source)
    groupes_json = [
        {
            'nom': g.get('denomination') or g.get('nom_complet') or '',
            'siren': g.get('siren', ''),
            'nb_sites': int(g.get('nb_sites', 0) or 0),
            'nb_depts': int(g.get('nb_departements', 0) or 0),
            'depts': g.get('departements', ''),
            'categorie': g.get('categorie_entreprise', ''),
            'effectif': g.get('effectif_code', ''),
            'commune': g.get('commune_siege', ''),
        }
        for g in groupes_raw
        if int(g.get('nb_departements', 0) or 0) >= 2
    ]
    write_json(DATA_DIR / 'groupes.json', groupes_json)
    print(f'    OK groupes.json ({len(groupes_json)} groupes multi-departements)')

    # Entreprises (agregation de sites par SIREN)
    ent_agg = defaultdict(lambda: {'nom': '', 'naf': '', 'naf_label': '', 'sites': 0, 'depts': set(), 'regions': set()})
    for s in sites_json:
        siren = s.get('siren', '')
        if not siren:
            continue
        agg = ent_agg[siren]
        if not agg['nom']:
            agg['nom'] = s['nom']
            agg['naf'] = s.get('naf', '')
            agg['naf_label'] = s.get('naf_label', '')
        agg['sites'] += 1
        if s.get('dept'):
            agg['depts'].add(s['dept'])
        if s.get('aria_region'):
            agg['regions'].add(s['aria_region'])
    entreprises_json = [
        {
            'nom': v['nom'], 'siren': k, 'nb_sites': v['sites'],
            'naf': v['naf'], 'naf_label': v['naf_label'],
            'nb_depts': len(v['depts']),
            'aria_region': sorted(v['regions'])[0] if v['regions'] else '',
            'aliases': MANUAL_COMPANY_INDEX.get(k, {}).get('aliases', []),
            'manual_priority': bool(MANUAL_COMPANY_INDEX.get(k)),
        }
        for k, v in ent_agg.items()
    ]
    entreprises_json.sort(key=lambda e: -e['nb_sites'])
    write_json(DATA_DIR / 'entreprises.json', entreprises_json)
    print(f'    OK entreprises.json ({len(entreprises_json)} entreprises uniques)')

    raw_sites_payload = read_json(RAW_DIR / 'sites_iaa_national.json', default={}) or {}
    raw_company_index = raw_sites_payload.get('entreprises', {}) or {}
    raw_company_index.update(MANUAL_COMPANY_INDEX)
    alim_index = read_json(NORMALIZED_DIR / 'alim_index.json', default={}) or {}
    sites_by_siren = defaultdict(list)
    for site in sites_json:
        siren = site.get('siren')
        if siren:
            sites_by_siren[siren].append(site)
    raw_sites_by_siren = defaultdict(list)
    for raw_site in raw_sites_payload.get('etablissements', []):
        siren = raw_site.get('siren')
        if siren:
            raw_sites_by_siren[siren].append(raw_site)
    for raw_site in MANUAL_SITES:
        raw_sites_by_siren[raw_site['siren']].append(raw_site)
    company_details = {}
    for entreprise in entreprises_json:
        siren = entreprise['siren']
        raw_company = raw_company_index.get(siren, {})
        sites_for_company = sites_by_siren.get(siren, [])
        site_coordinates = [
            {
                'siret': raw_site.get('siret', ''),
                'commune': raw_site.get('commune', ''),
                'adresse': raw_site.get('adresse', ''),
                'latitude': raw_site.get('latitude'),
                'longitude': raw_site.get('longitude'),
                'est_siege': False,
            }
            for raw_site in raw_sites_by_siren.get(siren, [])
        ]
        company_details[siren] = {
            'siren': siren,
            'nom_complet': raw_company.get('nom_complet') or entreprise['nom'],
            'categorie_entreprise': raw_company.get('categorie_entreprise') or entreprise.get('categorie', ''),
            'activite_principale': raw_company.get('activite_principale') or entreprise.get('naf', ''),
            'tranche_effectif_salarie': raw_company.get('tranche_effectif_salarie', ''),
            'date_creation': raw_company.get('date_creation', ''),
            'etat_administratif': raw_company.get('etat_administratif') or 'A',
            'nombre_etablissements': raw_company.get('nombre_etablissements', len(sites_for_company)),
            'nombre_etablissements_ouverts': raw_company.get('nombre_etablissements_ouverts', len(sites_for_company)),
            'complements': raw_company.get('complements') or {},
            'finances': raw_company.get('finances') or {},
            'dirigeants': raw_company.get('dirigeants') or [],
            'aliases': raw_company.get('aliases') or [],
            'manual_reason': raw_company.get('manual_reason') or '',
            'siege': raw_company.get('siege') or {},
            'matching_etablissements': raw_company.get('matching_etablissements') or site_coordinates,
            'ania_sites': sites_for_company,
            'alim_records': alim_index.get(siren, []),
            'provenance': {
                'company': 'recherche-entreprises.api.gouv.fr',
                'inspections': 'export_alimconfiance',
            },
        }
    write_json(DATA_DIR / 'company_details.json', company_details)
    print(f'    OK company_details.json ({len(company_details)} entreprises)')

    # Regions ARIA
    by_region = defaultdict(lambda: {'nb_sites': 0, 'depts': defaultdict(int)})
    for s in sites_raw:
        r = s.get('aria_region', 'Non rattaché') or 'Non rattaché'
        d = s.get('code_dept', '')
        by_region[r]['nb_sites'] += 1
        if d:
            by_region[r]['depts'][d] += 1

    # Trouver le top parlementaire par region (via les departements de la region)
    parl_by_dept = defaultdict(list)
    for p in parl_json:
        parl_by_dept[p['dept']].append(p)

    regions_json = []
    for region in ARIA_REGIONS:
        data = by_region.get(region, {'nb_sites': 0, 'depts': {}})
        top3_depts = sorted(data['depts'].items(), key=lambda x: -x[1])[:3]
        # Top parlementaire : celui avec le plus haut score dans les depts de la region
        all_parl_region = []
        for dept, _ in data['depts'].items():
            all_parl_region.extend(parl_by_dept.get(dept, []))
        all_parl_region.sort(key=lambda p: -p['score'])
        top_parl = all_parl_region[0] if all_parl_region else None
        regions_json.append({
            'nom': region,
            'nb_sites': data['nb_sites'],
            'top3_depts': [{'dept': d, 'nb': n} for d, n in top3_depts],
            'top_parl': {
                'nom': top_parl['nom'],
                'chambre': top_parl['chambre'],
                'dept': top_parl['dept'],
                'score': top_parl['score'],
            } if top_parl else None,
        })
    regions_json.sort(key=lambda r: -r['nb_sites'])
    write_json(DATA_DIR / 'regions.json', regions_json)
    print(f'    OK regions.json ({len(regions_json)} regions ARIA)')

    return parl_json, sites_json, partis_json, groupes_json, regions_json, entreprises_json


SITE_URL = "https://leannekoss.github.io/aria-national/"
NOINDEX = f"""<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="description" content="Cockpit ANIA de cartographie d'influence, veille parlementaire et intelligence territoriale pour les affaires publiques agroalimentaires.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="ANIA Radar">
<meta property="og:title" content="ANIA Radar · Cockpit affaires publiques">
<meta property="og:description" content="Dossiers chauds, élus prioritaires, entreprises alimentaires, régions ARIA et sources fraîches.">
<meta property="og:url" content="{SITE_URL}">
<meta name="twitter:card" content="summary">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; base-uri 'self'; object-src 'none'; script-src 'self' 'unsafe-inline' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: https://*.tile.openstreetmap.fr https://tile.openstreetmap.fr; font-src 'self' data:; connect-src 'self'; frame-src 'none'; form-action 'self' mailto:;">"""
FAVICON = '<link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 32 32\'><rect x=\'2\' y=\'17\' width=\'6\' height=\'13\' fill=\'%23e85d04\'/><rect x=\'11\' y=\'9\' width=\'6\' height=\'21\' fill=\'%231a1a2e\'/><rect x=\'20\' y=\'2\' width=\'6\' height=\'28\' fill=\'%23e85d04\'/><rect x=\'1\' y=\'30\' width=\'30\' height=\'2\' fill=\'%231a1a2e\'/></svg>">'

JS_SAFE_HELPERS = """
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function safeHref(value) {
  try {
    const url = new URL(String(value || ''), location.href);
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : '#';
  } catch (_) {
    return '#';
  }
}
function fmtDateSafe(value, withTime=false) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '-';
  return withTime ? d.toLocaleString('fr-FR') : d.toLocaleDateString('fr-FR');
}
"""


def write_nav(active_page):
    pages = [
        ('accueil.html', 'Cockpit'),
        ('dossiers-chauds.html', 'Dossiers'),
        ('timeline-reglementaire.html', 'Timeline'),
        ('parlementaires.html', 'Élus'),
        ('index.html', 'Carte'),
        ('entreprises.html', 'Entreprises'),
        ('regions.html', 'Régions'),
        ('methodologie.html', 'Sources'),
    ]
    items = ''
    for href, label in pages:
        cls = 'active' if href == active_page else ''
        items += f'<a href="{href}" class="nav-link {cls}">{label}</a>'
    return (
        '<nav class="top-nav">'
        '<a href="accueil.html" class="nav-brand-link">ANIA Radar</a>'
        f'<div class="nav-links">{items}</div>'
        '</nav>'
    )


BASE_CSS = """
:root {
  --ink: #172033;
  --muted: #647084;
  --line: #dbe2ea;
  --paper: #fbfcf8;
  --surface: #ffffff;
  --navy: #1a1a2e;
  --navy-2: #26324a;
  --accent: #d85b12;
  --accent-soft: #fff1e8;
  --success: #176b4d;
  --warning: #9a5b00;
  --danger: #9f2a2a;
  --info: #245d86;
  --radius: 8px;
  --shadow: 0 1px 2px rgba(18, 30, 50, .08), 0 10px 30px rgba(18, 30, 50, .05);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html { background: var(--paper); color: var(--ink); }
body { font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--paper); color: var(--ink); line-height: 1.45; }
a { color: inherit; }
.top-nav { background: var(--navy); color: white; padding: 0 22px; min-height: 56px; position: sticky; top: 0; z-index: 1000; display: flex; align-items: center; gap: 18px; border-bottom: 1px solid rgba(255,255,255,.08); }
.nav-brand-link { color: white; text-decoration: none; font-weight: 800; font-size: 15px; letter-spacing: .01em; white-space: nowrap; }
.nav-links { display: flex; gap: 4px; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
.nav-links::-webkit-scrollbar { display: none; }
.nav-link { color: rgba(255,255,255,.72); text-decoration: none; padding: 8px 11px; border-radius: 7px; font-size: 13px; font-weight: 650; white-space: nowrap; transition: background .16s, color .16s; }
.nav-link:hover, .nav-link.active { background: rgba(255,255,255,.12); color: white; }
.container { max-width: 1200px; margin: 0 auto; padding: 28px 20px; }
.page-title { font-size: clamp(24px, 3vw, 34px); font-weight: 850; line-height: 1.12; margin-bottom: 8px; color: var(--ink); letter-spacing: 0; }
.page-subtitle { font-size: 14px; color: var(--muted); margin-bottom: 22px; max-width: 78ch; }
.section-title { font-size: 16px; font-weight: 820; color: var(--ink); margin-bottom: 4px; }
.section-note { font-size: 12px; color: var(--muted); margin-bottom: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); }
.card:hover { box-shadow: var(--shadow); }
.evidence { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; color: var(--muted); font-size: 11px; margin-top: 10px; }
.badge, .chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 750; line-height: 1.35; border: 1px solid transparent; white-space: nowrap; }
.badge-agri { background: #edf7f1; color: var(--success); border-color: #cde8d8; }
.badge-eco { background: #edf5fb; color: var(--info); border-color: #c9e0f1; }
.badge-egalim { background: #fff7df; color: var(--warning); border-color: #f4df9d; }
.badge-an { background: var(--accent-soft); color: #8b3908; border-color: #f1c7ad; }
.badge-sen { background: #edf2ff; color: #24406f; border-color: #ccd7f4; }
.badge-danger { background: #fff0f0; color: var(--danger); border-color: #f0caca; }
.badge-neutral { background: #f4f6f8; color: #526071; border-color: #dce3eb; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 11px 12px; background: #f6f8fa; font-weight: 750; font-size: 11px; color: #4d5968; border-bottom: 1px solid var(--line); cursor: pointer; user-select: none; white-space: nowrap; text-transform: uppercase; letter-spacing: .03em; }
th:hover { background: #eef2f6; }
td { padding: 11px 12px; border-bottom: 1px solid #eef2f5; vertical-align: middle; }
tr:hover td { background: #fbfcfe; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: white; }
.search-bar { width: 100%; padding: 11px 13px; border: 1px solid var(--line); border-radius: var(--radius); font-size: 14px; margin-bottom: 12px; background: white; color: var(--ink); }
.search-bar:focus, .filter-select:focus { outline: 2px solid color-mix(in srgb, var(--accent), white 68%); outline-offset: 1px; border-color: var(--accent); }
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.filter-select { padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius); font-size: 13px; background: white; color: var(--ink); }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-card { background: white; border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 16px; box-shadow: var(--shadow); min-width: 0; }
.stat-value { font-size: clamp(24px, 3vw, 34px); font-weight: 850; color: var(--navy); line-height: 1.05; overflow-wrap: anywhere; }
.stat-label { font-size: 12px; color: var(--muted); margin-top: 8px; }
.pagination { display: flex; gap: 4px; justify-content: center; margin-top: 16px; flex-wrap: wrap; }
.page-btn { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: white; cursor: pointer; font-size: 13px; color: var(--ink); }
.page-btn.active { background: var(--navy); color: white; border-color: var(--navy); }
.page-btn:hover:not(.active) { background: #f0f3f6; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.mobile-cards { display: none; }
@media(max-width:760px) {
  .top-nav { padding: 8px 12px; align-items: flex-start; flex-direction: column; gap: 6px; min-height: 0; }
  .nav-links { width: 100%; }
  .nav-link { font-size: 12px; padding: 7px 9px; }
  .container { padding: 20px 14px; }
  .filter-row { flex-direction: column; }
  .filter-select { width: 100%; }
  .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .card { padding: 16px; }
  table { font-size: 12px; }
  th, td { padding: 8px; }
}
@media(max-width:430px) {
  .stats-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-card { padding: 13px 12px; }
  .stat-label { font-size: 11px; }
}
"""


def write_accueil(parl_json, sites_json, regions_json):
    nb_parls = len(parl_json)
    top10 = sorted(parl_json, key=lambda p: -p['score'])[:10]
    top10_html = ''.join(
        f'<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #f0f0f0">'
        f'<span style="width:22px;height:22px;border-radius:50%;background:#e85d04;color:white;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0">{i+1}</span>'
        f'<div style="flex:1;min-width:0"><div style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{p["nom"]}</div>'
        f'<div style="font-size:11px;color:#888">{p["chambre"]} · {p["dept"]} {p["nom_dept"]}</div></div>'
        f'<span style="background:#1a1a2e;color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;flex-shrink:0">{p["score"]:.1f}</span>'
        f'</div>'
        for i, p in enumerate(top10)
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>Cockpit ANIA · accueil</title>
{FAVICON}
<style>{BASE_CSS}
.hero {{ background:#1a1a2e; color:white; padding:56px 20px; }}
.hero-grid {{ max-width:1200px; margin:0 auto; display:grid; grid-template-columns:1.3fr .9fr; gap:18px; align-items:start; }}
.hero-panel {{ background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:22px; }}
.hero-kicker {{ display:inline-block; background:rgba(232,93,4,.2); color:#ffb27a; border:1px solid rgba(232,93,4,.35); padding:5px 12px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; margin-bottom:18px; }}
.hero-title {{ font-size:clamp(28px,4vw,46px); line-height:1.05; font-weight:850; max-width:14ch; margin-bottom:14px; }}
.hero-subtitle {{ font-size:15px; line-height:1.65; color:rgba(255,255,255,.78); max-width:60ch; }}
.hero-cta {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:20px; }}
.btn-primary {{ background:var(--accent); color:white; padding:12px 18px; border-radius:8px; text-decoration:none; font-weight:750; font-size:14px; }}
.btn-secondary {{ background:rgba(255,255,255,.08); color:white; padding:12px 18px; border-radius:8px; text-decoration:none; font-weight:750; font-size:14px; border:1px solid rgba(255,255,255,.15); }}
.hero-aside-title {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#ffb27a; margin-bottom:10px; }}
.signal-row {{ display:grid; grid-template-columns:1fr auto; gap:8px; padding:10px 0; border-bottom:1px solid rgba(255,255,255,.08); }}
.signal-row:last-child {{ border-bottom:none; }}
.signal-title {{ font-size:13px; line-height:1.35; }}
.signal-meta {{ font-size:11px; color:rgba(255,255,255,.65); margin-top:4px; }}
.signal-badge {{ font-size:11px; border-radius:999px; padding:3px 8px; background:rgba(255,255,255,.08); color:white; align-self:start; }}
.exec-grid {{ display:grid; grid-template-columns:1.2fr .8fr; gap:16px; margin:24px 0; }}
.exec-list {{ display:grid; gap:10px; }}
.exec-item {{ display:grid; grid-template-columns:1fr auto; gap:10px; padding:12px 0; border-bottom:1px solid #f0f0f0; }}
.exec-item:last-child {{ border-bottom:none; }}
.exec-item-title {{ font-size:14px; font-weight:700; }}
.exec-item-meta {{ font-size:11px; color:#777; margin-top:4px; }}
.chip {{ display:inline-flex; align-items:center; padding:3px 8px; border-radius:999px; font-size:11px; font-weight:700; background:#f3f4f6; color:#334155; }}
.stacked-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:24px; }}
.feature-card {{ background:white; border-radius:var(--radius); padding:22px; box-shadow:var(--shadow); text-decoration:none; color:inherit; transition:all .2s; border:1px solid var(--line); border-top:4px solid var(--accent); }}
.feature-card:hover {{ transform:translateY(-2px); box-shadow:var(--shadow); }}
.feature-icon {{ font-size:11px; font-weight:850; letter-spacing:.08em; color:var(--accent); text-transform:uppercase; margin-bottom:10px; }}
.feature-title {{ font-size:15px; font-weight:700; margin-bottom:5px; }}
.feature-desc {{ font-size:12px; color:#666; line-height:1.5; }}
@media(max-width:900px) {{ .hero-grid,.exec-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
{write_nav('accueil.html')}
<div class="hero">
  <div class="hero-grid">
    <div class="hero-panel">
      <div class="hero-kicker">Cockpit ANIA · affaires publiques</div>
      <div class="hero-title">Voir ce qui bouge, ce qui compte, et où agir maintenant.</div>
      <div class="hero-subtitle">Un front unique pour suivre les dossiers chauds, les signaux parlementaires, la pression réglementaire et la fraîcheur des sources officielles sans quitter le site statique.</div>
      <div class="hero-cta">
        <a href="dossiers-chauds.html" class="btn-primary">Ouvrir les dossiers chauds</a>
        <a href="timeline-reglementaire.html" class="btn-secondary">Lire la timeline réglementaire</a>
      </div>
    </div>
    <div class="hero-panel">
      <div class="hero-aside-title">Signaux des 7 derniers jours</div>
      <div id="hero-signals">
        <div class="signal-row"><div><div class="signal-title">Chargement des derniers signaux...</div></div></div>
      </div>
    </div>
  </div>
</div>
<div class="container">
  <div class="stats-grid" style="margin-top:32px">
    <div class="stat-card"><div class="stat-value">{len(sites_json):,}</div><div class="stat-label">Sites IAA géolocalisés</div></div>
    <div class="stat-card"><div class="stat-value">{nb_parls}</div><div class="stat-label">Élus scorés</div></div>
    <div class="stat-card"><div class="stat-value">{len(regions_json)}</div><div class="stat-label">Régions ARIA</div></div>
    <div class="stat-card"><div class="stat-value" id="fresh-source-count">-</div><div class="stat-label">Sources actives</div></div>
  </div>

  <div class="exec-grid">
    <div class="card">
      <div class="page-title" style="font-size:18px;margin-bottom:2px">Dossiers à arbitrer</div>
      <div class="page-subtitle" style="margin-bottom:12px">Les sujets les plus actifs selon les flux officiels croisés</div>
      <div class="exec-list" id="hot-dossiers-list"><div class="exec-item"><div>Chargement...</div></div></div>
    </div>
    <div class="card">
      <div class="page-title" style="font-size:18px;margin-bottom:2px">Fraîcheur des sources</div>
      <div class="page-subtitle" style="margin-bottom:12px">Provenance, dernière collecte et statut de repli</div>
      <div class="exec-list" id="freshness-list"><div class="exec-item"><div>Chargement...</div></div></div>
    </div>
  </div>

  <div class="stacked-grid">
    <a href="index.html" class="feature-card"><div class="feature-icon">Territoires</div><div class="feature-title">Carte interactive</div><div class="feature-desc">Lecture géographique de l’empreinte IAA et des élus exposés.</div></a>
    <a href="dossiers-chauds.html" class="feature-card"><div class="feature-icon">Priorité</div><div class="feature-title">Dossiers chauds</div><div class="feature-desc">Priorisation par intensité de signal, récence et diversité des sources.</div></a>
    <a href="timeline-reglementaire.html" class="feature-card"><div class="feature-icon">Veille</div><div class="feature-title">Timeline réglementaire</div><div class="feature-desc">Fil unifié des publications AN, Sénat, ANIA et signaux HATVP.</div></a>
    <a href="veille-thematique.html" class="feature-card"><div class="feature-icon">Thèmes</div><div class="feature-title">Veille thématique</div><div class="feature-desc">Regroupement par thème métier: EGALIM, agriculture, emballages, santé, export.</div></a>
    <a href="lobbying.html" class="feature-card"><div class="feature-icon">HATVP</div><div class="feature-title">Lobbying récent</div><div class="feature-desc">Lecture structurée: actions, volumes, décideurs publics et organisations.</div></a>
    <a href="methodologie.html" class="feature-card"><div class="feature-icon">Preuves</div><div class="feature-title">Sources et méthode</div><div class="feature-desc">Règles de scoring, sources officielles et limites connues du build statique.</div></a>
  </div>

  <div class="card">
    <div style="font-size:15px;font-weight:700;margin-bottom:12px;color:#1a1a2e">Top 10 score ARIA · national</div>
    {top10_html}
    <div style="margin-top:12px;text-align:right"><a href="parlementaires.html" style="font-size:12px;color:#e85d04;text-decoration:none;font-weight:600">Voir les {nb_parls} élus</a></div>
  </div>

  <footer style="text-align:center;color:#888;font-size:12px;padding:32px 0">Sources officielles: Assemblée nationale · Sénat · HATVP · ANIA · Recherche-entreprises · Alim'confiance</footer>
</div>
<script>
function prettyDate(value) {{
  if (!value) return 'n.c.';
  return new Date(value).toLocaleString('fr-FR', {{ dateStyle:'short', timeStyle:'short' }});
}}
Promise.all([
  fetch('data/hot_dossiers.json').then(r => r.json()),
  fetch('data/freshness.json').then(r => r.json()),
  fetch('data/timeline_reglementaire.json').then(r => r.json())
]).then(([hot, freshness, timeline]) => {{
  document.getElementById('fresh-source-count').textContent = (freshness.sources||[]).filter(s => s.freshness_status !== 'disabled').length;
  document.getElementById('hero-signals').innerHTML = (timeline||[]).slice(0, 5).map(item => `
    <div class="signal-row">
      <div>
        <div class="signal-title">${{item.title}}</div>
        <div class="signal-meta">${{item.source}} · ${{prettyDate(item.published_at)}}</div>
      </div>
      <span class="signal-badge">${{(item.themes||[])[0]||'Signal'}}</span>
    </div>`).join('') || '<div class="signal-row"><div><div class="signal-title">Aucun signal récent</div></div></div>';
  document.getElementById('hot-dossiers-list').innerHTML = (hot||[]).slice(0, 6).map(item => `
    <div class="exec-item">
      <div>
        <div class="exec-item-title">${{item.theme}}</div>
        <div class="exec-item-meta">${{item.score}} signaux · ${{item.sources.join(' · ')}}</div>
      </div>
      <span class="chip">${{prettyDate(item.latest_at).split(' ')[0]}}</span>
    </div>`).join('') || '<div class="exec-item"><div>Aucun dossier chaud calculé.</div></div>';
  document.getElementById('freshness-list').innerHTML = (freshness.sources||[]).slice(0, 8).map(source => `
    <div class="exec-item">
      <div>
        <div class="exec-item-title">${{source.label}}</div>
        <div class="exec-item-meta">${{source.fallback_used ? 'fallback cache' : 'collecte nominale'}} · ${{source.item_count || 0}} items</div>
      </div>
      <span class="chip">${{source.freshness_status}}</span>
    </div>`).join('');
}}).catch(err => {{
  document.getElementById('hero-signals').innerHTML = `<div class="signal-row"><div class="signal-title">Erreur de chargement: ${{err.message}}</div></div>`;
}});
</script>
</body>
</html>"""
    (SITE_DIR / 'accueil.html').write_text(html, encoding='utf-8')
    print('    OK accueil.html')


def write_index():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - Carte parlementaire</title>
{FAVICON}
<style>{BASE_CSS}
#map {{ width:100%; height:calc(100vh - 52px); }}
#side-panel {{ width:380px; flex-shrink:0; background:white; border-left:1px solid #ddd; overflow-y:auto; display:flex; flex-direction:column; }}
.map-wrap {{ display:flex; height:calc(100vh - 52px); }}
@media(max-width:768px) {{
  .map-wrap {{ flex-direction:column; height:auto; }}
  #map {{ height:50vh; }}
  #side-panel {{ width:100%; border-left:none; border-top:1px solid #ddd; max-height:50vh; }}
}}
#panel-header {{ padding:14px 16px; background:#1a1a2e; color:white; font-weight:600; font-size:14px; }}
#panel-header span {{ display:block; font-size:11px; font-weight:400; opacity:.7; margin-top:3px; }}
#panel-filters {{ padding:8px 12px; border-bottom:1px solid #eee; }}
#filter-chambre {{ width:100%; padding:5px 8px; border:1px solid #ddd; border-radius:4px; font-size:12px; background:white; }}
#panel-content {{ padding:12px; flex:1; }}
.dept-title {{ font-size:17px; font-weight:700; color:#1a1a2e; margin-bottom:3px; }}
.dept-stats {{ font-size:12px; color:#666; margin-bottom:10px; }}
.parl-card {{ background:#f8f9fa; border-radius:8px; padding:10px 12px; margin-bottom:8px; border-left:4px solid #ccc; }}
.parl-card.an {{ border-left-color:#e85d04; }}
.parl-card.sen {{ border-left-color:#4361ee; }}
.parl-nom {{ font-weight:600; font-size:13px; }}
.parl-groupe {{ font-size:11px; color:#666; margin-top:2px; }}
.parl-score {{ float:right; font-size:12px; background:#1a1a2e; color:white; padding:2px 7px; border-radius:4px; }}
.empty-state {{ text-align:center; color:#999; padding:40px 16px; font-size:13px; }}
.legend {{ background:white; padding:10px 14px; border-radius:8px; box-shadow:0 1px 5px rgba(0,0,0,.3); font-size:11px; }}
</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
</head>
<body>
{write_nav('index.html')}
<div class="map-wrap">
<div id="map"></div>
<div id="side-panel">
  <div id="panel-header">Carte ANIA - 27 201 sites IAA
    <span>Cliquez sur un département pour voir les parlementaires</span>
  </div>
  <div id="panel-filters">
    <label for="filter-chambre" class="sr-only">Filtrer par chambre</label>
    <select id="filter-chambre" onchange="renderPanel()" style="width:100%;margin-bottom:6px;padding:5px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px;background:white">
      <option value="">AN + Sénat</option>
      <option value="AN">Assemblée Nationale</option>
      <option value="SEN">Sénat</option>
    </select>
    <label for="filter-region" class="sr-only">Filtrer par région ARIA</label>
    <select id="filter-region" onchange="applyRegionFilter()" style="width:100%;margin-bottom:6px;padding:5px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px;background:white">
      <option value="">Toutes les régions</option>
      <option value="ARIA Sud">ARIA Sud (PACA)</option>
      <option value="ARIA Auvergne-Rhone-Alpes">Auvergne-Rhone-Alpes</option>
      <option value="ARIA Grand Est">Grand Est</option>
      <option value="ARIA Hauts-de-France">Hauts-de-France</option>
      <option value="ARIA Ile-de-France">Ile-de-France</option>
      <option value="ARIA Normandie">Normandie</option>
      <option value="ARIA Nouvelle-Aquitaine">Nouvelle-Aquitaine</option>
      <option value="ARIA Occitanie">Occitanie</option>
      <option value="ARIA Pays de la Loire">Pays de la Loire</option>
      <option value="ARIA Bretagne">Bretagne</option>
      <option value="ARIA Bourgogne-Franche-Comte">Bourgogne-Franche-Comte</option>
      <option value="ARIA Centre-Val de Loire">Centre-Val de Loire</option>
      <option value="ARIA Corse">Corse</option>
    </select>
    <button onclick="focusSud()" style="width:100%;padding:5px 8px;border:none;border-radius:4px;background:#e85d04;color:white;font-size:12px;font-weight:600;cursor:pointer">Focus Sud - PACA</button>
  </div>
  <div id="panel-content"><div class="empty-state">Cliquez sur un département coloré pour explorer</div></div>
</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const SCRUTIN_LABELS = {{"egalim1":"EGALIM 1","egalim2":"EGALIM 2","egalim3":"EGALIM 3 (Descrozaille)","loa2024":"LOA 2024","revenu_agri":"PPL Revenu Agri"}};
const VOTE_COLORS = {{pour:"#28a745",contre:"#dc3545",abstention:"#fd7e14",absent:"#aaa"}};
const NAF_COLORS = {{"10.1":"#7b2d8b","10.3":"#2e8b57","10.4":"#6b9e3a","10.5":"#d4a017","10.7":"#c17f3a","11.":"#c0392b"}};
const REGION_BOUNDS = {{
  'ARIA Sud': [[43.0,4.2],[45.2,7.7]],
  'ARIA Auvergne-Rhone-Alpes': [[44.1,2.0],[46.8,7.2]],
  'ARIA Grand Est': [[47.4,5.8],[49.5,8.2]],
  'ARIA Hauts-de-France': [[49.7,1.4],[51.1,4.3]],
  'ARIA Ile-de-France': [[48.1,1.4],[49.2,3.6]],
  'ARIA Normandie': [[48.6,-1.8],[50.0,1.8]],
  'ARIA Nouvelle-Aquitaine': [[43.0,-1.8],[47.1,2.6]],
  'ARIA Occitanie': [[42.3,-0.3],[45.0,4.9]],
  'ARIA Pays de la Loire': [[46.3,-2.6],[48.2,0.9]],
  'ARIA Bretagne': [[47.3,-5.1],[48.8,-1.1]],
  'ARIA Bourgogne-Franche-Comte': [[46.1,2.8],[48.0,7.0]],
  'ARIA Centre-Val de Loire': [[46.3,0.1],[48.9,3.2]],
  'ARIA Corse': [[41.3,8.5],[43.1,9.6]],
}};
const sitesByDept = {{}};
const activeMarkers = [];

function focusSud() {{
  map.fitBounds(REGION_BOUNDS['ARIA Sud']);
  document.getElementById('filter-region').value = 'ARIA Sud';
}}

function applyRegionFilter() {{
  const region = document.getElementById('filter-region').value;
  if (region && REGION_BOUNDS[region]) map.fitBounds(REGION_BOUNDS[region]);
  else if (!region) map.setView([46.5, 2.5], 6);
}}

function showDeptMarkers(deptCode) {{
  activeMarkers.forEach(m => map.removeLayer(m));
  activeMarkers.length = 0;
  (sitesByDept[deptCode] || []).forEach(s => {{
    if (!s.lat || !s.lng) return;
    const nafKey = Object.keys(NAF_COLORS).find(k => s.naf && s.naf.startsWith(k)) || null;
    const color = nafKey ? NAF_COLORS[nafKey] : '#555';
    const icon = L.divIcon({{
      className:'',
      html:`<div style="width:8px;height:8px;border-radius:50%;background:${{color}};border:1px solid white;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
      iconSize:[8,8], iconAnchor:[4,4]
    }});
    const marker = L.marker([s.lat,s.lng],{{icon}}).bindPopup(
      `<div style="min-width:190px;font-size:13px"><b>${{s.nom}}</b>` +
      `<div style="margin-top:5px"><span style="background:${{color}};color:white;padding:2px 6px;border-radius:3px;font-size:11px">${{s.naf_label}}</span></div>` +
      `<div style="margin-top:4px;color:#444">${{s.commune}} ${{s.cp}}</div>` +
      (s.aria_region?`<div style="font-size:11px;color:#888">ARIA: ${{s.aria_region}}</div>`:'') +
      `</div>`
    ).addTo(map);
    activeMarkers.push(marker);
  }});
}}

function voteCell(v) {{
  if (!v) return '<span style="color:#bbb;font-size:10px">-</span>';
  const c = VOTE_COLORS[v] || '#ddd';
  return `<span style="display:inline-block;padding:1px 5px;border-radius:3px;background:${{c}};color:${{v==='absent'?'#555':'white'}};font-size:10px;font-weight:600">${{v}}</span>`;
}}

const map = L.map('map').setView([46.5, 2.5], 6);
L.tileLayer('https://{{s}}.tile.openstreetmap.fr/osmfr/{{z}}/{{x}}/{{y}}.png', {{
  attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributeurs - Rendu OpenStreetMap France',
  subdomains:'abc', maxZoom:20
}}).addTo(map);

function getColor(nb) {{
  return nb>=100?'#800026':nb>=60?'#BD0026':nb>=40?'#E31A1C':nb>=25?'#FC4E2A':nb>=15?'#FD8D3C':nb>=8?'#FEB24C':nb>=1?'#FED976':'#eee';
}}

let currentDept=null, geojsonLayer=null, deptData={{}};

Promise.all([
  fetch('data/sites.json').then(r=>r.json()),
  fetch('data/parlementaires.json').then(r=>r.json()),
]).then(([sites, parls]) => {{
  parls.forEach(p => {{
    if (!p.dept) return;
    if (!deptData[p.dept]) deptData[p.dept] = {{nb_sites:0, parl:[]}};
    deptData[p.dept].parl.push(p);
  }});

  sites.forEach(s => {{
    if (!s.dept) return;
    if (!sitesByDept[s.dept]) sitesByDept[s.dept] = [];
    sitesByDept[s.dept].push(s);
    if (!deptData[s.dept]) deptData[s.dept] = {{nb_sites:0,parl:[]}};
    deptData[s.dept].nb_sites++;
  }});

  return fetch('{LOCAL_GEOJSON}');
}}).then(r=>r.json()).then(geo => {{
  function style(f) {{
    const nb = (deptData[f.properties.code]||{{}}).nb_sites||0;
    return {{fillColor:getColor(nb),weight:1,color:'#666',fillOpacity:.75}};
  }}
  function onEach(f,l) {{
    l.on({{
      mouseover: e => {{ e.target.setStyle({{weight:2.5,color:'#333',fillOpacity:.9}}); e.target.bringToFront(); }},
      mouseout: e => {{ if (currentDept!==f.properties.code) geojsonLayer.resetStyle(e.target); }},
      click: e => {{
        if (currentDept) geojsonLayer.eachLayer(ll => {{ if(ll.feature&&ll.feature.properties.code===currentDept) geojsonLayer.resetStyle(ll); }});
        currentDept=f.properties.code;
        e.target.setStyle({{weight:3,color:'#1a1a2e',fillOpacity:.9}});
        showDeptMarkers(f.properties.code);
        renderPanel(f.properties);
      }}
    }});
    const nb=(deptData[f.properties.code]||{{}}).nb_sites||0;
    const nbParl=((deptData[f.properties.code]||{{}}).parl||[]).length;
    l.bindTooltip(`<b>${{f.properties.nom}} (${{f.properties.code}})</b><br>${{nb}} sites IAA · ${{nbParl}} élu(s)`,{{sticky:true}});
  }}
  geojsonLayer = L.geoJSON(geo,{{style,onEachFeature:onEach}}).addTo(map);
}}).catch(e=>console.warn('GeoJSON error',e));

function renderPanel(deptProps) {{
  const content=document.getElementById('panel-content');
  if(!deptProps) return;
  const code=deptProps.code, nom=deptProps.nom;
  const dd=deptData[code]||{{}};
  const nb=dd.nb_sites||0;
  const parl=dd.parl||[];
  const filter=document.getElementById('filter-chambre').value;
  const filtered=filter?parl.filter(p=>p.chambre===filter):parl;
  filtered.sort((a,b)=>b.score-a.score);

  let html=`<div class="dept-title">${{nom}} (${{code}})</div>
    <div class="dept-stats">${{nb}} sites IAA · ${{parl.filter(p=>p.chambre==='AN').length}} député(s) · ${{parl.filter(p=>p.chambre==='SEN').length}} sénateur(s)</div>`;

  if (!filtered.length) {{
    html+='<div class="empty-state">Aucun parlementaire</div>';
  }} else {{
    filtered.forEach(p => {{
      const posColor=p.position&&p.position.includes('pro')?'color:#155724':p.position&&p.position.includes('reserve')?'color:#721c24':'color:#555';
      let votesHtml='';
      if (p.chambre==='AN'&&p.votes) {{
        const hasVotes=Object.values(p.votes).some(v=>v&&v!=='absent');
        if (hasVotes) {{
          votesHtml='<div style="margin-top:5px;border-top:1px solid #eee;padding-top:4px">'+
            Object.entries(SCRUTIN_LABELS).map(([k,label])=>
              `<div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;margin:1px 0"><span style="color:#777">${{label}}</span>${{voteCell((p.votes||{{}})[k])}}</div>`
            ).join('')+'</div>';
        }}
      }}
      html+=`<div class="parl-card ${{p.chambre.toLowerCase()}}">
        <span class="parl-score">${{p.score.toFixed(1)}}</span>
        <div class="parl-nom">${{p.nom}} ${{p.mail?`<a href="mailto:${{p.mail}}" style="color:#4361ee;font-size:11px">mail</a>`:''}}</div>
        <div class="parl-groupe">${{p.chambre==='AN'?'AN':'Sénat'}} - ${{p.groupe}}</div>
        <div style="display:flex;gap:3px;flex-wrap:wrap;margin:3px 0">
          ${{p.commission_agri?'<span class="badge badge-agri">Agri</span>':''}}
          ${{p.commission_eco?'<span class="badge badge-eco">Eco</span>':''}}
          ${{p.mission_egalim?'<span class="badge badge-egalim">EGALIM</span>':''}}
          ${{p.commission_env?'<span class="badge" style="background:#d1e7dd;color:#0a4023">Env</span>':''}}
          ${{p.score_egalim>3?'<span class="badge" style="background:#fff3cd;color:#7a5c00;font-size:10px">EGALIM \u2605</span>':''}}
        </div>
        ${{p.position&&p.chambre==='AN'?`<div style="font-size:10px;margin-top:2px;${{posColor}}">${{p.position}}</div>`:''}}
        ${{p.nb_sites>0?`<div style="font-size:11px;color:#666;margin-top:2px">Zone: ${{p.nb_sites}} IAA${{p.nb_vins>0?' \u00b7 '+p.nb_vins+' vins':''}}</div>`:''}}
        ${{votesHtml}}
      </div>`;
    }});
  }}
  content.innerHTML=html;
}}

const leg=L.control({{position:'bottomleft'}});
leg.onAdd=()=>{{
  const d=L.DomUtil.create('div','legend');
  d.style.cssText='background:white;padding:12px 16px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.25);font-size:12px;min-width:140px';
  d.innerHTML='<div style="font-weight:700;font-size:13px;margin-bottom:8px;color:#1a1a2e">Sites IAA / dép.</div>'+
    [{{n:100,l:'100+'}},{{n:60,l:'60-99'}},{{n:40,l:'40-59'}},{{n:25,l:'25-39'}},{{n:15,l:'15-24'}},{{n:8,l:'8-14'}},{{n:1,l:'1-7'}},{{n:0,l:'0'}}]
    .map(({{n,l}})=>`<div style="display:flex;align-items:center;gap:8px;margin:3px 0"><div style="width:18px;height:14px;border-radius:2px;background:${{getColor(n)}};border:1px solid rgba(0,0,0,.1)"></div><span>${{l}}</span></div>`)
    .join('');
  return d;
}};
leg.addTo(map);
</script>
</body>
</html>"""
    (SITE_DIR / 'index.html').write_text(html, encoding='utf-8')
    print('    OK index.html (carte Leaflet)')


def write_parlementaires():
    scrutin_id_list = json.dumps([s['id'] for s in SCRUTINS_META])
    scrutin_label_list = json.dumps({s['id']: s['label'] for s in SCRUTINS_META})

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - Élus prioritaires</title>
{FAVICON}
<style>{BASE_CSS}
.priority-cell {{ display:grid; gap:4px; min-width:190px; }}
.priority-label {{ font-size:12px; color:var(--muted); }}
.score-meter {{ height:7px; border-radius:999px; background:#eef2f6; overflow:hidden; }}
.score-meter span {{ display:block; height:100%; background:var(--accent); border-radius:999px; }}
.action-link {{ color:var(--accent); font-weight:750; text-decoration:none; white-space:nowrap; }}
.mobile-elect-card {{ display:none; }}
@media(max-width:760px) {{
  .desktop-table {{ display:none; }}
  .mobile-elect-card {{ display:block; padding:14px 0; border-bottom:1px solid var(--line); }}
  .mobile-elect-card:last-child {{ border-bottom:none; }}
}}
</style>
</head>
<body>
{write_nav('parlementaires.html')}
<div class="container">
  <div class="page-title">Élus prioritaires</div>
  <div class="page-subtitle">Classement opérationnel des députés et sénateurs selon exposition IAA, rôle parlementaire, signaux publics et capacité d'activation territoriale.</div>
  <div class="stats-grid" id="stats-grid"></div>
  <div class="card">
    <label for="search" class="sr-only">Rechercher un parlementaire</label>
    <input type="text" class="search-bar" id="search" placeholder="Rechercher par nom, groupe, département..." oninput="renderTable()">
    <div class="filter-row">
      <select class="filter-select" id="f-chambre" onchange="renderTable()"><option value="">AN + Sénat</option><option value="AN">Assemblée Nationale</option><option value="SEN">Sénat</option></select>
      <select class="filter-select" id="f-dept" onchange="renderTable()"><option value="">Tous les dép.</option></select>
      <select class="filter-select" id="f-groupe" onchange="renderTable()"><option value="">Tous les groupes</option></select>
      <select class="filter-select" id="f-commission" onchange="renderTable()">
        <option value="">Toutes commissions</option>
        <option value="agri">Commission Agriculture</option>
        <option value="eco">Commission Economique</option>
        <option value="egalim">Mission EGALIM</option>
      </select>
      <select class="filter-select" id="f-sites" onchange="renderTable()"><option value="">Tous les élus</option><option value="1">Avec sites IAA</option></select>
    </div>
    <div id="result-count" style="font-size:12px;color:#666;margin-bottom:8px"></div>
    <div id="mobile-list"></div>
    <div class="table-wrap desktop-table">
    <table id="table">
      <thead><tr>
        <th onclick="sortTable(0)">Élu</th>
        <th onclick="sortTable(1)">Chambre</th>
        <th onclick="sortTable(5)">Priorité de contact</th>
        <th onclick="sortTable(3)">Territoire</th>
        <th>Posture observée</th>
        <th>Signaux clés</th>
        <th>Action</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    </div>
    <div class="pagination" id="pagination"></div>
  </div>
</div>
<script>
const SCRUTIN_IDS = {scrutin_id_list};
const SCRUTIN_LABELS = {scrutin_label_list};
const PAGE_SIZE = 50;
let allData = [], filtered = [], sortCol = 5, sortDir = -1, page = 0;

function priorityLabel(p) {{
  if (p.score >= 250) return 'Priorité forte';
  if (p.score >= 80) return 'Priorité moyenne';
  if (p.nb_sites > 0 || p.commission_agri || p.commission_eco || p.mission_egalim) return 'À qualifier';
  return 'Veille simple';
}}

function actionLabel(p) {{
  if (p.score >= 250) return 'Préparer rendez-vous';
  if (p.mission_egalim || p.commission_agri || p.commission_eco) return 'Qualifier position';
  if (p.nb_sites > 0) return 'Activer angle territorial';
  return 'Surveiller';
}}

fetch('data/parlementaires.json').then(r=>r.json()).then(data => {{
  allData = data;
  const depts = [...new Set(data.map(p=>p.dept+' - '+p.nom_dept).filter(Boolean))].sort();
  const groupes = [...new Set(data.map(p=>p.groupe).filter(Boolean))].sort();
  const sel_d = document.getElementById('f-dept');
  depts.forEach(d => sel_d.add(new Option(d, d.split(' - ')[0])));
  const sel_g = document.getElementById('f-groupe');
  groupes.forEach(g => sel_g.add(new Option(g, g)));
  document.getElementById('stats-grid').innerHTML = `
    <div class="stat-card"><div class="stat-value">${{data.filter(p=>p.chambre==='AN').length}}</div><div class="stat-label">Députés</div></div>
    <div class="stat-card"><div class="stat-value">${{data.filter(p=>p.chambre==='SEN').length}}</div><div class="stat-label">Sénateurs</div></div>
    <div class="stat-card"><div class="stat-value">${{data.filter(p=>p.nb_sites>0).length}}</div><div class="stat-label">Élus avec exposition IAA</div></div>
    <div class="stat-card"><div class="stat-value">${{data.filter(p=>p.commission_agri||p.commission_eco||p.mission_egalim).length}}</div><div class="stat-label">Rôles agri / EGALIM</div></div>
  `;
  renderTable();
}});

function filterData() {{
  const q = document.getElementById('search').value.toLowerCase();
  const fc = document.getElementById('f-chambre').value;
  const fd = document.getElementById('f-dept').value;
  const fg = document.getElementById('f-groupe').value;
  const fcom = document.getElementById('f-commission').value;
  const fs = document.getElementById('f-sites').value;
  return allData.filter(p =>
    (!q || p.nom.toLowerCase().includes(q) || (p.groupe||'').toLowerCase().includes(q) || (p.nom_dept||'').toLowerCase().includes(q)) &&
    (!fc || p.chambre === fc) &&
    (!fd || p.dept === fd) &&
    (!fg || p.groupe === fg) &&
    (!fcom || (fcom==='agri'&&p.commission_agri) || (fcom==='eco'&&p.commission_eco) || (fcom==='egalim'&&p.mission_egalim)) &&
    (!fs || p.nb_sites > 0)
  );
}}

function sortTable(col) {{
  if (sortCol === col) sortDir *= -1; else {{ sortCol = col; sortDir = col === 0 ? 1 : -1; }}
  page = 0; renderTable();
}}

function sortKey(p, col) {{
  switch(col) {{
    case 0: return p.nom; case 1: return p.chambre; case 2: return p.groupe;
    case 3: return p.dept; case 4: return p.nb_sites; case 5: return p.score;
    default: return p.score;
  }}
}}

function renderTable() {{
  filtered = filterData();
  filtered.sort((a,b) => {{
    const ka=sortKey(a,sortCol), kb=sortKey(b,sortCol);
    return typeof ka==='number' ? (ka-kb)*sortDir : (ka<kb?-1:ka>kb?1:0)*sortDir;
  }});
  page = Math.max(0, Math.min(page, Math.floor((filtered.length-1)/PAGE_SIZE)));
  document.getElementById('result-count').textContent = `${{filtered.length}} résultats`;
  const slice = filtered.slice(page*PAGE_SIZE, (page+1)*PAGE_SIZE);
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = slice.map(p => {{
    const badges = [
      p.commission_agri?'<span class="badge badge-agri">Agriculture</span>':'',
      p.commission_eco?'<span class="badge badge-eco">Économie</span>':'',
      p.mission_egalim?'<span class="badge badge-egalim">EGALIM</span>':'',
      p.commission_env?'<span class="badge badge-agri">Environnement</span>':''
    ].filter(Boolean).join(' ') || '<span class="badge badge-neutral">Aucun rôle ciblé</span>';
    const scoreMax = 800;
    const scorePct = Math.min(100, Math.round((p.score / scoreMax) * 100));
    return `<tr>
      <td><div style="font-weight:750"><a href="fiche.html?id=${{p.id}}" style="text-decoration:none">${{p.nom}}</a></div><div style="font-size:11px;color:var(--muted)">${{p.groupe||''}}</div></td>
      <td><span class="badge ${{p.chambre==='AN'?'badge-an':'badge-sen'}}">${{p.chambre}}</span></td>
      <td><div class="priority-cell"><strong>${{priorityLabel(p)}}</strong><span class="priority-label">score ${{p.score.toFixed(1)}} · ${{p.nb_sites}} sites</span><div class="score-meter"><span style="width:${{scorePct}}%"></span></div></div></td>
      <td><strong>${{p.dept}}</strong><div style="font-size:11px;color:var(--muted)">${{p.nom_dept||''}}</div></td>
      <td><span class="badge badge-neutral">${{p.position||'non qualifiée'}}</span></td>
      <td>${{badges}}</td>
      <td><a class="action-link" href="fiche.html?id=${{p.id}}">${{actionLabel(p)}}</a></td>
    </tr>`;
  }}).join('');
  document.getElementById('mobile-list').innerHTML = slice.map(p => `
    <div class="mobile-elect-card">
      <div style="display:flex;justify-content:space-between;gap:12px">
        <div><a href="fiche.html?id=${{p.id}}" style="font-weight:800;text-decoration:none">${{p.nom}}</a><div style="font-size:12px;color:var(--muted)">${{p.chambre}} · ${{p.dept}} ${{p.nom_dept||''}}</div></div>
        <span class="badge ${{p.score>=250?'badge-an':'badge-neutral'}}">${{priorityLabel(p)}}</span>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted)">${{p.nb_sites}} sites IAA · ${{p.position||'posture non qualifiée'}}</div>
      <div style="margin-top:10px"><a class="action-link" href="fiche.html?id=${{p.id}}">${{actionLabel(p)}}</a></div>
    </div>`).join('');
  const totalPages = Math.ceil(filtered.length/PAGE_SIZE);
  const pag = document.getElementById('pagination');
  let pagHtml = '';
  for (let i=0; i<totalPages; i++) {{
    if (i===0||i===totalPages-1||Math.abs(i-page)<=2) pagHtml+=`<button class="page-btn${{i===page?' active':''}}" onclick="goPage(${{i}})">${{i+1}}</button>`;
    else if (Math.abs(i-page)===3) pagHtml+='<span style="padding:5px">...</span>';
  }}
  pag.innerHTML = pagHtml;
}}

function goPage(p) {{ page=p; renderTable(); window.scrollTo(0,0); }}
</script>
</body>
</html>"""
    (SITE_DIR / 'parlementaires.html').write_text(html, encoding='utf-8')
    print('    OK parlementaires.html')


def write_regions(regions_json):
    """Page listant les 16 associations ARIA avec nb_sites, top 3 depts, top parlementaire."""
    regions_js = json.dumps(regions_json, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - 16 régions ARIA</title>
{FAVICON}
<style>{BASE_CSS}
.region-card {{ background:white; border-radius:12px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:14px; display:flex; align-items:flex-start; gap:16px; border-left:5px solid #e85d04; }}
.region-rank {{ width:36px; height:36px; border-radius:50%; background:#e85d04; color:white; font-size:14px; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
.region-body {{ flex:1; min-width:0; }}
.region-name {{ font-size:18px; font-weight:700; color:#1a1a2e; margin-bottom:4px; }}
.region-sites {{ font-size:24px; font-weight:800; color:#e85d04; }}
.region-sub {{ font-size:12px; color:#888; }}
.dept-tag {{ display:inline-block; background:#f0f0f0; border-radius:4px; padding:2px 8px; font-size:12px; margin:2px; }}
.top-parl {{ background:#f8f9fa; border-radius:8px; padding:10px 12px; margin-top:10px; display:flex; justify-content:space-between; align-items:center; }}
.top-parl-name {{ font-weight:600; font-size:13px; }}
.top-parl-meta {{ font-size:11px; color:#888; }}
.score-badge {{ background:#1a1a2e; color:white; padding:3px 9px; border-radius:4px; font-size:13px; font-weight:700; }}
#choropleth {{ width:100%; height:420px; border-radius:12px; overflow:hidden; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,.12); }}
</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
</head>
<body>
{write_nav('regions.html')}
<div class="container">
  <div class="page-title">Régions ARIA</div>
  <div class="page-subtitle">27 201 sites IAA (PME+) répartis par association ARIA régionale - Classés par volume</div>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-value">16</div><div class="stat-label">Associations ARIA</div></div>
    <div class="stat-card"><div class="stat-value">27 201</div><div class="stat-label">Sites IAA total</div></div>
    <div class="stat-card"><div class="stat-value" id="sites-with-region">-</div><div class="stat-label">Sites rattachés à une ARIA</div></div>
    <div class="stat-card"><div class="stat-value">103</div><div class="stat-label">Départements couverts</div></div>
  </div>
  <div id="choropleth"></div>
  <input type="text" class="search-bar" id="search" placeholder="Filtrer par région ARIA..." oninput="renderRegions()">
  <div id="regions-list"></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const REGIONS_DATA = {regions_js};

// Stats
const attached = REGIONS_DATA.filter(r => r.nom !== 'Non rattaché').reduce((a, r) => a + r.nb_sites, 0);
document.getElementById('sites-with-region').textContent = attached.toLocaleString('fr-FR');

// Couleurs par region
const REGION_COLORS = [
  '#e85d04','#1a1a2e','#2e8b57','#8b1a1a','#0057b8','#6a0dad',
  '#c17f3a','#2e6db4','#d4a017','#7b2d8b','#cc4400','#155724',
  '#3d5a80','#8b4513','#003366','#666666'
];
const regionColorMap = {{}};
REGIONS_DATA.forEach((r, i) => {{ regionColorMap[r.nom] = REGION_COLORS[i % REGION_COLORS.length]; }});

// Carte choroplèthe par region
const mapEl = document.getElementById('choropleth');
const map = L.map(mapEl).setView([46.5, 2.5], 5);
L.tileLayer('https://{{s}}.tile.openstreetmap.fr/osmfr/{{z}}/{{x}}/{{y}}.png', {{
  attribution:'© OpenStreetMap France', subdomains:'abc', maxZoom:20
}}).addTo(map);

// Mapping dept → region (via REGIONS_DATA top3 + total)
// On construit depuis les données : tous les depts dans top3_depts
const deptToRegion = {{}};
REGIONS_DATA.forEach(r => {{
  r.top3_depts.forEach(d => {{ deptToRegion[d.dept] = r.nom; }});
}});

const maxSites = Math.max(...REGIONS_DATA.map(r => r.nb_sites));
function regionColor(regionNom) {{
  return regionColorMap[regionNom] || '#ccc';
}}

fetch('{LOCAL_GEOJSON}')
  .then(r => r.json())
  .then(geo => {{
    L.geoJSON(geo, {{
      style: f => {{
        const region = deptToRegion[f.properties.code];
        const color = region ? regionColor(region) : '#eee';
        return {{fillColor: color, weight: 1, color: '#fff', fillOpacity: 0.7}};
      }},
      onEachFeature: (f, l) => {{
        const region = deptToRegion[f.properties.code];
        const regionData = region ? REGIONS_DATA.find(r => r.nom === region) : null;
        const tooltip = region
          ? `<b>${{f.properties.nom}} (${{f.properties.code}})</b><br>${{region}}: ${{regionData ? regionData.nb_sites : '-'}} sites`
          : `<b>${{f.properties.nom}}</b><br>Non classifié`;
        l.bindTooltip(tooltip, {{sticky: true}});
      }}
    }}).addTo(map);

    // Legende
    const leg = L.control({{position: 'bottomright'}});
    leg.onAdd = () => {{
      const d = L.DomUtil.create('div');
      d.style.cssText = 'background:white;padding:10px 14px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.2);font-size:11px;max-height:260px;overflow-y:auto;max-width:200px';
      d.innerHTML = '<b style="font-size:12px">Régions ARIA</b><br>' +
        REGIONS_DATA.filter(r => r.nom !== 'Non rattaché').map(r =>
          `<div style="display:flex;align-items:center;gap:6px;margin:3px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${{r.nom}}">
            <div style="width:14px;height:10px;border-radius:2px;background:${{regionColor(r.nom)}};flex-shrink:0"></div>
            <span style="overflow:hidden;text-overflow:ellipsis">${{r.nom.replace('AREA ','').replace('ARIA ','')}}</span>
          </div>`).join('');
      return d;
    }};
    leg.addTo(map);
  }});

function renderRegions() {{
  const q = document.getElementById('search').value.toLowerCase();
  const data = q ? REGIONS_DATA.filter(r => r.nom.toLowerCase().includes(q)) : REGIONS_DATA;
  const container = document.getElementById('regions-list');
  container.innerHTML = data.map((r, i) => {{
    const realRank = REGIONS_DATA.indexOf(r) + 1;
    const top3Html = r.top3_depts.map(d =>
      `<span class="dept-tag">Dép. ${{d.dept}}: ${{d.nb}} sites</span>`
    ).join('');
    const toplParl = r.top_parl ? `
      <div class="top-parl">
        <div>
          <div class="top-parl-name">Élu clé : ${{r.top_parl.nom}}</div>
          <div class="top-parl-meta">${{r.top_parl.chambre}} - Dept. ${{r.top_parl.dept}}</div>
        </div>
        <span class="score-badge">${{r.top_parl.score.toFixed(0)}}</span>
      </div>` : '';
    return `<div class="region-card">
      <div class="region-rank">${{realRank}}</div>
      <div class="region-body">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div>
            <div class="region-name" style="border-left:4px solid ${{regionColor(r.nom)}};padding-left:8px">${{r.nom}}</div>
          </div>
          <div style="text-align:right">
            <div class="region-sites">${{r.nb_sites.toLocaleString('fr-FR')}}</div>
            <div class="region-sub">sites IAA</div>
          </div>
        </div>
        <div style="margin-top:8px">${{top3Html}}</div>
        ${{toplParl}}
      </div>
    </div>`;
  }}).join('');
}}

renderRegions();
</script>
</body>
</html>"""
    (SITE_DIR / 'regions.html').write_text(html, encoding='utf-8')
    print('    OK regions.html')


def write_partis():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - Analyse par parti</title>
{FAVICON}
<style>{BASE_CSS}
.parti-card {{ background:white; border-radius:10px; padding:16px; box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:12px; display:flex; align-items:center; gap:16px; }}
.parti-bar-bg {{ flex:1; background:#eee; border-radius:4px; height:8px; }}
.parti-bar-fill {{ height:8px; border-radius:4px; }}
.parti-name {{ font-weight:700; font-size:14px; min-width:200px; }}
.parti-stats {{ font-size:12px; color:#666; margin-top:3px; }}
</style>
</head>
<body>
{write_nav('partis.html')}
<div class="container">
  <div class="page-title">Analyse par parti politique</div>
  <div class="page-subtitle">Classement par exposition aux zones de production IAA nationale</div>
  <div class="filter-row">
    <select class="filter-select" id="f-chambre" onchange="renderPartis()"><option value="">AN + Sénat</option><option value="AN">Assemblée Nationale</option><option value="SEN">Sénat</option></select>
    <select class="filter-select" id="f-sort" onchange="renderPartis()">
      <option value="total_sites">Total sites en zone</option>
      <option value="pct_zone">% élus en zone IAA</option>
      <option value="score_moyen">Score ARIA moyen</option>
      <option value="nb_elus">Nombre d'élus</option>
    </select>
  </div>
  <div id="partis-content"></div>
</div>
<script>
let partisData = [];
fetch('data/partis.json').then(r=>r.json()).then(data => {{
  partisData = data;
  renderPartis();
}});

function renderPartis() {{
  const fc = document.getElementById('f-chambre').value;
  const fs = document.getElementById('f-sort').value;
  let data = fc ? partisData.filter(p=>p.chambre===fc) : partisData;
  data = [...data].sort((a,b) => b[fs] - a[fs]);
  const maxSites = Math.max(...data.map(p=>p.total_sites)) || 1;

  document.getElementById('partis-content').innerHTML = data.map(p => {{
    const pct = Math.round(p.pct_zone);
    const barW = Math.round((p.total_sites/maxSites)*100);
    const chambreLabel = p.chambre === 'AN' ? '<span class="badge badge-an">AN</span>' : '<span class="badge badge-sen">Sénat</span>';
    return `<div class="parti-card">
      <div style="width:14px;height:44px;border-radius:3px;background:${{p.color}};flex-shrink:0"></div>
      <div style="flex:1">
        <div class="parti-name">${{chambreLabel}} ${{p.groupe}}</div>
        <div class="parti-stats">${{p.nb_elus}} élu(s) - ${{p.nb_elus_zone}} en zone IAA (${{pct}}%) - Score moy. ${{p.score_moyen.toFixed(1)}}</div>
        <div style="margin-top:6px;display:flex;align-items:center;gap:8px">
          <div class="parti-bar-bg"><div class="parti-bar-fill" style="width:${{barW}}%;background:${{p.color}}"></div></div>
          <span style="font-size:13px;font-weight:700;min-width:30px">${{p.total_sites}}</span>
          <span style="font-size:11px;color:#888">sites</span>
        </div>
      </div>
    </div>`;
  }}).join('');
}}
</script>
</body>
</html>"""
    (SITE_DIR / 'partis.html').write_text(html, encoding='utf-8')
    print('    OK partis.html')


def write_groupes():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - Groupes industriels</title>
{FAVICON}
<style>{BASE_CSS}
@media(max-width:768px) {{ table th:nth-child(2), table td:nth-child(2) {{ display:none; }} }}
</style>
</head>
<body>
{write_nav('groupes.html')}
<div class="container">
  <div class="page-title">Groupes industriels</div>
  <div class="page-subtitle">Groupes IAA multi-départements (21 374 SIREN uniques - groupes avec 2+ départements)</div>
  <div class="card">
    <label for="search" class="sr-only">Rechercher un groupe industriel</label>
    <input type="text" class="search-bar" id="search" placeholder="Rechercher un groupe..." oninput="renderGroupes()">
    <div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th onclick="sortTable(0)">Groupe</th>
        <th onclick="sortTable(1)">Catégorie</th>
        <th onclick="sortTable(2)">Sites</th>
        <th onclick="sortTable(3)">Dép.</th>
        <th>Départements couverts</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    </div>
  </div>
</div>
<script>
let allData = [], sortCol = 2, sortDir = -1;

const EFFECTIF_LABELS = {{'11':'1-9','12':'10-19','21':'20-49','22':'50-99','31':'100-199','32':'200-499','41':'500-999','42':'1000-1999','51':'2000-4999','52':'5000+','NN':'?'}};

fetch('data/groupes.json').then(r=>r.json()).then(data => {{
  allData = data;
  renderGroupes();
}});

function renderGroupes() {{
  const q = document.getElementById('search').value.toLowerCase();
  let data = q ? allData.filter(g=>(g.nom||'').toLowerCase().includes(q)||(g.siren||'').includes(q)) : allData;
  data = [...data].sort((a,b) => {{
    const vals = [[a.nom,b.nom],[a.categorie,b.categorie],[a.nb_sites,b.nb_sites],[a.nb_depts,b.nb_depts]];
    const [ka,kb] = vals[Math.min(sortCol,3)] || [0,0];
    return typeof ka === 'number' ? (ka-kb)*sortDir : (String(ka||'') < String(kb||'') ? -1 : String(ka||'') > String(kb||'') ? 1 : 0)*sortDir;
  }});
  document.getElementById('tbody').innerHTML = data.slice(0, 500).map(g => {{
    const depts = (g.depts||'').split(',').map(d=>d.trim()).filter(Boolean);
    const deptsHtml = depts.map(d=>`<span style="background:#f0f0f0;border-radius:3px;padding:1px 5px;font-size:11px;margin:1px">${{d}}</span>`).join('');
    const multiStyle = g.nb_depts >= 10 ? 'font-weight:700;color:#e85d04' : g.nb_depts >= 5 ? 'font-weight:600' : '';
    const catBadge = g.categorie ? `<span style="font-size:10px;background:#e8f4fd;color:#1a3a5c;padding:1px 5px;border-radius:3px;margin-left:4px">${{g.categorie}}</span>` : '';
    const effLabel = EFFECTIF_LABELS[g.effectif] || g.effectif || '';
    const subInfo = [g.commune, effLabel ? effLabel+' sal.' : ''].filter(Boolean).join(' · ');
    return `<tr>
      <td><b>${{g.nom||g.siren}}</b>${{catBadge}}<div style="font-size:11px;color:#888;margin-top:1px">${{subInfo}}</div></td>
      <td style="font-size:11px;color:#888">${{g.siren}}</td>
      <td style="text-align:center">${{g.nb_sites}}</td>
      <td style="text-align:center;${{multiStyle}}">${{g.nb_depts}}</td>
      <td>${{deptsHtml}}</td>
    </tr>`;
  }}).join('');
}}

function sortTable(col) {{
  if (sortCol===col) sortDir*=-1; else {{sortCol=col;sortDir=col>=2?-1:1;}}
  renderGroupes();
}}
</script>
</body>
</html>"""
    (SITE_DIR / 'groupes.html').write_text(html, encoding='utf-8')
    print('    OK groupes.html')


def write_entreprises():
    nav = write_nav('entreprises.html')
    naf_labels_js = json.dumps({
        '10.11Z': 'Abattage / viande', '10.12Z': 'Volaille', '10.13A': 'Prépa viande',
        '10.13B': 'Charcuterie', '10.31Z': 'Pommes de terre', '10.32Z': 'Jus fruits/légumes',
        '10.39A': 'Légumes surgelés', '10.39B': 'Transfo fruits/légumes',
        '10.41A': 'Huile olive', '10.41B': 'Huiles végétales',
        '10.51A': 'Lait/crème', '10.51C': 'Beurre', '10.51D': 'Fromage',
        '10.52Z': 'Glaces/sorbets', '10.72Z': 'Biscuits/pâtisseries',
        '10.84Z': 'Condiments', '10.85Z': 'Plats préparés',
        '10.86Z': 'Aliments diététiques', '10.89Z': 'Autres alimentaires',
        '11.01Z': 'Eaux-de-vie', '11.02A': 'Vins AOC', '11.02B': 'Autres vins',
        '11.03Z': 'Cidre/fruits', '11.07A': 'Eaux minérales', '11.07B': 'Limonades/boissons',
        '46.33Z': 'Commerce de gros produits laitiers',
    }, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{NOINDEX}
<title>ANIA - Entreprises IAA</title>
{FAVICON}
<style>{BASE_CSS}
.siren-link {{ color: #1a1a2e; font-weight: 600; text-decoration: none; border-bottom: 1px dotted #ccc; }}
.siren-link:hover {{ color: #e85d04; border-bottom-color: #e85d04; }}
.naf-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
@media(max-width:768px) {{ table th:nth-child(n+5), table td:nth-child(n+5) {{ display:none; }} }}
</style>
</head>
<body>
{nav}
<div class="container">
<h1 class="page-title">Entreprises IAA</h1>
<p class="page-subtitle">Référentiel des entreprises alimentaires croisable avec territoires ARIA, sites de production et élus exposés. Utiliser cette vue pour préparer une preuve économique locale.</p>
<div class="stats-grid" id="stats"></div>
<div class="card">
<label for="search" class="sr-only">Rechercher</label>
<input class="search-bar" id="search" placeholder="Rechercher une entreprise, un SIREN..." oninput="render()">
<div class="filter-row">
  <label for="fRegion" class="sr-only">Région ARIA</label>
  <select class="filter-select" id="fRegion" onchange="render()"><option value="">Toutes les régions ARIA</option></select>
  <label for="fNaf" class="sr-only">Secteur</label>
  <select class="filter-select" id="fNaf" onchange="render()"><option value="">Tous les secteurs</option></select>
  <label for="fSites" class="sr-only">Nombre de sites</label>
  <select class="filter-select" id="fSites" onchange="render()">
    <option value="">Toutes tailles</option>
    <option value="10">10+ sites</option>
    <option value="5">5+ sites</option>
    <option value="2">Multi-sites (2+)</option>
  </select>
</div>
<div id="count" style="font-size:13px;color:#888;margin-bottom:12px"></div>
<div style="overflow-x:auto"><table><thead><tr>
  <th onclick="sortBy('nom')">Entreprise ↕</th>
  <th onclick="sortBy('siren')">SIREN</th>
  <th onclick="sortBy('naf')">Secteur</th>
  <th onclick="sortBy('nb_sites')" style="text-align:center">Sites ↕</th>
  <th onclick="sortBy('nb_depts')" style="text-align:center">Depts</th>
  <th onclick="sortBy('aria_region')">Région ARIA</th>
</tr></thead><tbody id="tbody"></tbody></table></div>
<div class="pagination" id="pagination"></div>
</div>
</div>
<script>
const NAF_LABELS = {naf_labels_js};
const NAF_COLORS = {{'10.1':'#7b2d8b','10.3':'#2e8b57','10.4':'#6b9e3a','10.5':'#d4a017','10.7':'#c17f3a','10.8':'#e85d04','10.9':'#555','11.0':'#8b1a1a'}};
function nafColor(c) {{ const p=c?c.slice(0,4):''; for(const[k,v] of Object.entries(NAF_COLORS)) if(p.startsWith(k)) return v; return '#666'; }}
let data=[], filtered=[], sortCol='nb_sites', sortDir=-1, page=1;
const PAGE=50;
fetch('data/entreprises.json').then(r=>r.json()).then(d=>{{
  data=d;
  const regions=[...new Set(d.map(e=>e.aria_region).filter(Boolean))].sort();
  const nafs=[...new Set(d.map(e=>e.naf).filter(Boolean))].sort();
  regions.forEach(s=>{{const o=document.createElement('option');o.value=s;o.textContent=s;document.getElementById('fRegion').appendChild(o);}});
  nafs.forEach(n=>{{const o=document.createElement('option');o.value=n;o.textContent=(NAF_LABELS[n]||n)+' ('+n+')';document.getElementById('fNaf').appendChild(o);}});
  const ts=d.reduce((a,e)=>a+e.nb_sites,0);
  const ms=d.filter(e=>e.nb_sites>=2).length;
  document.getElementById('stats').innerHTML=`
    <div class="stat-card"><div class="stat-value">${{d.length.toLocaleString()}}</div><div class="stat-label">Entreprises IAA</div></div>
    <div class="stat-card"><div class="stat-value">${{ts.toLocaleString()}}</div><div class="stat-label">Sites de production</div></div>
    <div class="stat-card"><div class="stat-value">${{ms.toLocaleString()}}</div><div class="stat-label">Multi-sites (2+)</div></div>
    <div class="stat-card"><div class="stat-value">${{regions.length}}</div><div class="stat-label">Régions ARIA</div></div>`;
  render();
}});
function render(){{
  const q=document.getElementById('search').value.toLowerCase();
  const reg=document.getElementById('fRegion').value;
  const naf=document.getElementById('fNaf').value;
  const minS=parseInt(document.getElementById('fSites').value)||0;
  filtered=data.filter(e=>{{
    const haystack = [e.nom, e.siren, ...(e.aliases||[])].join(' ').toLowerCase();
    if(q&&!haystack.includes(q)) return false;
    if(reg&&e.aria_region!==reg) return false;
    if(naf&&e.naf!==naf) return false;
    if(minS&&e.nb_sites<minS) return false;
    return true;
  }});
  filtered.sort((a,b)=>{{
    if(q) {{
      const ma = a.manual_priority ? 1 : 0;
      const mb = b.manual_priority ? 1 : 0;
      if (ma !== mb) return mb - ma;
    }}
    const va=a[sortCol]??'', vb=b[sortCol]??'';
    return sortDir*(va>vb?1:va<vb?-1:0);
  }});
  page=1; paginate();
}}
function sortBy(col){{sortCol===col?sortDir*=-1:(sortCol=col,sortDir=-1);render();}}
function paginate(){{
  const total=filtered.length, pages=Math.ceil(total/PAGE)||1;
  document.getElementById('count').textContent=total.toLocaleString()+' entreprise'+(total>1?'s':'');
  const slice=filtered.slice((page-1)*PAGE,page*PAGE);
  document.getElementById('tbody').innerHTML=slice.map(e=>`<tr>
    <td><a href="fiche-entreprise.html?siren=${{e.siren}}" class="siren-link">${{e.nom}}</a></td>
    <td style="font-family:monospace;font-size:12px;color:#888">${{e.siren}}</td>
    <td><span class="naf-dot" style="background:${{nafColor(e.naf)}}"></span><span style="font-size:12px">${{NAF_LABELS[e.naf]||e.naf}}</span></td>
    <td style="text-align:center;font-weight:700">${{e.nb_sites}}</td>
    <td style="text-align:center">${{e.nb_depts}}</td>
    <td style="font-size:12px">${{e.aria_region||'-'}}</td>
  </tr>`).join('');
  const pag=document.getElementById('pagination'); pag.innerHTML='';
  if(pages<=1) return;
  for(let i=1;i<=Math.min(pages,10);i++){{const b=document.createElement('button');b.className='page-btn'+(i===page?' active':'');b.textContent=i;b.onclick=(p=>()=>{{page=p;paginate();}})(i);pag.appendChild(b);}}
  if(pages>10){{const s=document.createElement('span');s.textContent=` ... ${{pages}}`;s.style.cssText='padding:5px;font-size:13px;color:#888';pag.appendChild(s);}}
}}
</script>
</body>
</html>"""
    (SITE_DIR / 'entreprises.html').write_text(html, encoding='utf-8')
    print('    OK entreprises.html')


def write_fiche_entreprise():
    nav = write_nav('entreprises.html')
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{NOINDEX}
<title>Fiche entreprise - ANIA x Parlementaires</title>
{FAVICON}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9/dist/leaflet.css"/>
<style>{BASE_CSS}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
@media(max-width:768px) {{ .grid-2 {{ grid-template-columns:1fr; }} }}
.info-row {{ display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #f0f0f0; font-size:13px; gap:12px; }}
.info-label {{ color:#888; }}
.info-value {{ font-weight:600; text-align:right; }}
.score-badge {{ display:inline-block; padding:4px 12px; border-radius:20px; font-weight:700; font-size:14px; }}
.score-1 {{ background:#d4edda; color:#155724; }}
.score-2 {{ background:#cce5ff; color:#004085; }}
.score-3 {{ background:#fff3cd; color:#856404; }}
.score-4 {{ background:#f8d7da; color:#721c24; }}
.dirigeant {{ padding:6px 0; border-bottom:1px solid #f5f5f5; font-size:13px; }}
.dir-qualite {{ font-size:11px; color:#888; }}
.etab-item {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:13px; display:flex; justify-content:space-between; align-items:center; }}
.etab-item:last-child {{ border-bottom:none; }}
.spinner {{ width:40px; height:40px; border:4px solid #eee; border-top:4px solid #1a1a2e; border-radius:50%; animation:spin 1s linear infinite; margin:40px auto 16px; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
.back-link {{ display:inline-flex; align-items:center; gap:6px; color:#666; text-decoration:none; font-size:13px; margin-bottom:16px; }}
.status-dot {{ width:8px; height:8px; border-radius:99px; display:inline-block; margin-right:6px; vertical-align:middle; background:currentColor; }}
.denree-tag {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; background:#f0f0f0; margin:2px; }}
</style>
</head>
<body>
{nav}
<div class="container">
<a href="entreprises.html" class="back-link">← Retour aux entreprises</a>
<div id="loading"><div class="spinner"></div><p style="text-align:center;color:#888">Chargement de la fiche entreprise...</p></div>
<div id="error" style="display:none;text-align:center;padding:40px">
  <h2>Entreprise non trouvée</h2>
  <p id="error-msg" style="color:#888;margin-top:8px"></p>
  <a href="entreprises.html" style="display:inline-block;margin-top:16px;padding:8px 20px;background:#1a1a2e;color:white;border-radius:8px;text-decoration:none">Revenir à la liste</a>
</div>
<div id="content" style="display:none">
  <div id="header"></div>
  <div class="grid-2">
    <div class="card" id="info-card"></div>
    <div class="card" style="padding:0;overflow:hidden"><div id="map" style="height:350px"></div></div>
  </div>
  <div class="grid-2">
    <div class="card" id="finance-card"></div>
    <div class="card" id="alim-card"></div>
  </div>
  <div class="card" id="parl-card" style="margin-top:16px"></div>
  <div class="card" id="sites-card" style="margin-top:16px"></div>
</div>
</div>
<script src="https://unpkg.com/leaflet@1.9/dist/leaflet.js"></script>
<script>
const EFFECTIF = {{'00':'Non employeur','01':'1-2','02':'3-5','03':'6-9','11':'10-19','12':'20-49','21':'50-99','22':'100-199','31':'200-249','32':'250-499','41':'500-999','42':'1 000-1 999','51':'2 000-4 999','52':'5 000-9 999','53':'10 000+'}};
const CAT_LABELS = {{'PME':'PME','ETI':'ETI','GE':'Grande entreprise','MIC':'Micro-entreprise'}};
const ALIM_SCORES = {{1:'Très satisfaisant',2:'Satisfaisant',3:'À améliorer',4:'À corriger de manière urgente'}};
const NAF_LABELS = {{'10.11Z':'Abattage/viande','10.12Z':'Volaille','10.13A':'Prépa viande','10.13B':'Charcuterie','10.31Z':'Pommes de terre','10.32Z':'Jus','10.39A':'Légumes surgelés','10.39B':'Fruits/légumes','10.41A':'Huile olive','10.41B':'Huiles végétales','10.51A':'Lait/crème','10.51C':'Beurre','10.51D':'Fromage','10.52Z':'Glaces','10.72Z':'Biscuits','10.84Z':'Condiments','10.85Z':'Plats préparés','10.86Z':'Diététiques','10.89Z':'Autres alim.','11.01Z':'Eaux-de-vie','11.02A':'Vins AOC','11.02B':'Autres vins','11.03Z':'Cidre','11.07A':'Eaux minérales','11.07B':'Boissons','46.33Z':'Commerce de gros produits laitiers'}};
const params = new URLSearchParams(location.search);
const siren = params.get('siren') || (params.get('siret') ? params.get('siret').slice(0,9) : null);
function fmtDate(value) {{ return value ? new Date(value).toLocaleDateString('fr-FR') : '-'; }}
if (!siren) {{
  document.getElementById('loading').style.display='none';
  document.getElementById('error').style.display='block';
  document.getElementById('error-msg').textContent='Paramètre manquant. Utilisez ?siren=XXXXXXXXX ou ?siret=XXXXXXXXXXXXXX.';
}} else {{
  (async()=>{{
    try {{
      const [detailsIndex, parlData, freshness] = await Promise.all([
        fetch('data/company_details.json').then(r => r.json()),
        fetch('data/parlementaires.json').then(r => r.json()),
        fetch('data/freshness.json').then(r => r.json()),
      ]);
      const ent = detailsIndex[siren];
      if (!ent) {{
        document.getElementById('loading').style.display='none';
        document.getElementById('error').style.display='block';
        document.getElementById('error-msg').textContent='SIREN '+siren+' absent du cache local.';
        return;
      }}
      const alimFreshness = (freshness.sources||[]).find(s => s.id === 'alimconfiance');
      document.getElementById('loading').style.display='none';
      document.getElementById('content').style.display='block';
      document.title = ent.nom_complet + ' - Fiche ANIA';

      const cat = CAT_LABELS[ent.categorie_entreprise] || ent.categorie_entreprise || '';
      const nafLabel = NAF_LABELS[ent.activite_principale] || ent.activite_principale || '';
      const siege = ent.siege || {{}};
      document.getElementById('header').innerHTML = `
        <h1 class="page-title" style="margin-bottom:4px">${{ent.nom_complet}}</h1>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">
          <span class="badge badge-eco">SIREN ${{ent.siren}}</span>
          ${{cat?'<span class="badge badge-agri">'+cat+'</span>':''}}
          ${{nafLabel?'<span class="badge badge-egalim">'+nafLabel+'</span>':''}}
          ${{(ent.aliases||[]).length?'<span class="badge">Alias: '+ent.aliases[0]+'</span>':''}}
          <span class="badge" style="background:${{ent.etat_administratif==='A'?'#d4edda':'#f8d7da'}};color:${{ent.etat_administratif==='A'?'#155724':'#721c24'}}"><span class="status-dot"></span>${{ent.etat_administratif==='A'?'Active':'Fermée'}}</span>
        </div>`;

      const dirs = (ent.dirigeants||[]).map(d => (String(d.type_dirigeant||'').toLowerCase().includes('physique')
        ? `<div class="dirigeant">${{d.prenoms||''}} ${{d.nom||''}}<div class="dir-qualite">${{d.qualite||''}}</div></div>`
        : `<div class="dirigeant">${{d.denomination||d.siren||''}}<div class="dir-qualite">${{d.qualite||''}}</div></div>`)).join('');
      const labels = [];
      if (ent.complements) {{
        if (ent.complements.est_bio) labels.push('Bio');
        if (ent.complements.est_ess) labels.push('ESS');
        if (ent.complements.est_rge) labels.push('RGE');
        if (ent.complements.est_societe_mission) labels.push('Société à mission');
      }}
      document.getElementById('info-card').innerHTML = `
        <h3 style="margin-bottom:12px">Informations</h3>
        <div class="info-row"><span class="info-label">Adresse siège</span><span class="info-value">${{siege.adresse||'-'}}</span></div>
        <div class="info-row"><span class="info-label">Commune</span><span class="info-value">${{siege.libelle_commune||siege.commune||'-'}} (${{siege.departement||''}})</span></div>
        <div class="info-row"><span class="info-label">Effectif</span><span class="info-value">${{EFFECTIF[String(ent.tranche_effectif_salarie)]||'-'}} salariés</span></div>
        <div class="info-row"><span class="info-label">Création</span><span class="info-value">${{fmtDate(ent.date_creation)}}</span></div>
        <div class="info-row"><span class="info-label">Établissements</span><span class="info-value">${{ent.nombre_etablissements_ouverts||0}} ouverts / ${{ent.nombre_etablissements||0}} total</span></div>
        ${{ent.manual_reason?'<div class="info-row"><span class="info-label">Périmètre</span><span class="info-value">Exception ANIA documentée</span></div>':''}}
        ${{labels.length?'<div style="margin-top:8px">'+labels.join(' ')+'</div>':''}}
        ${{dirs?'<h4 style="margin-top:16px;margin-bottom:8px">Dirigeants</h4>'+dirs:''}}
        <div style="margin-top:14px;font-size:11px;color:#888">Cache local généré au build · provenance visible dans Méthodologie.</div>`;

      const map = L.map('map').setView([46.5, 2.5], 5);
      L.tileLayer('https://{{s}}.tile.openstreetmap.fr/osmfr/{{z}}/{{x}}/{{y}}.png', {{ maxZoom:18, attribution:'OSM France' }}).addTo(map);
      const bounds = [];
      const pushMarker = (lat, lng, html, color, radius) => {{
        if (!lat || !lng) return;
        const ll = [parseFloat(lat), parseFloat(lng)];
        bounds.push(ll);
        L.circleMarker(ll, {{radius, fillColor:color, fillOpacity:.8, color:'white', weight:1}}).addTo(map).bindPopup(html);
      }};
      if (siege.latitude && siege.longitude) pushMarker(siege.latitude, siege.longitude, '<b>Siège</b><br>'+(siege.adresse||''), '#e85d04', 7);
      (ent.matching_etablissements||[]).forEach(site => pushMarker(site.latitude, site.longitude, '<b>Établissement</b><br>'+(site.commune||site.libelle_commune||'')+'<br>'+(site.adresse||''), '#1a1a2e', 6));
      (ent.ania_sites||[]).forEach(site => pushMarker(site.lat, site.lng, '<b>Site IAA</b><br>'+site.nom+'<br>'+site.naf_label, '#2e8b57', 5));
      if (bounds.length) map.fitBounds(bounds, {{padding:[30,30]}});

      const years = Object.keys(ent.finances||{{}}).sort().reverse();
      let finHtml = '<h3 style="margin-bottom:12px">Données financières</h3>';
      if (years.length) {{
        years.forEach(y => {{
          const f = ent.finances[y] || {{}};
          const ca = f.ca!=null ? (f.ca>1e6 ? (f.ca/1e6).toFixed(1)+' M€' : Number(f.ca).toLocaleString('fr-FR')+' €') : '-';
          const rn = f.resultat_net!=null ? Number(f.resultat_net).toLocaleString('fr-FR')+' €' : '-';
          finHtml += `<div class="info-row"><span class="info-label">CA ${{y}}</span><span class="info-value">${{ca}}</span></div>`;
          finHtml += `<div class="info-row"><span class="info-label">Résultat net ${{y}}</span><span class="info-value">${{rn}}</span></div>`;
        }});
      }} else {{
        finHtml += '<p style="color:#888;font-size:13px">Aucune donnée financière disponible dans le cache actuel.</p>';
      }}
      document.getElementById('finance-card').innerHTML = finHtml;

      const alimRecs = ent.alim_records || [];
      let alimHtml = '<h3 style="margin-bottom:12px">Alim\\'confiance - inspections</h3>';
      if (alimRecs.length) {{
        alimRecs.forEach(rec => {{
          const denrees = (rec.denree||'').split('|').filter(Boolean);
          alimHtml += `
            <div style="margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid #f0f0f0">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <span class="score-badge score-${{rec.app_code_synthese_eval_sanit||2}}">${{ALIM_SCORES[rec.app_code_synthese_eval_sanit] || rec.synthese_eval_sanit || 'Inspection'}}</span>
                <span style="font-size:12px;color:#888">${{fmtDate(rec.date_inspection)}}</span>
              </div>
              <div class="info-row"><span class="info-label">Activité</span><span class="info-value">${{rec.type_activite||'-'}}</span></div>
              <div class="info-row"><span class="info-label">Suite</span><span class="info-value">${{rec.type_suite||'-'}}</span></div>
              ${{denrees.length?'<div style="margin-top:8px">'+denrees.map(d=>'<span class="denree-tag">'+d.trim()+'</span>').join('')+'</div>':''}}
            </div>`;
        }});
      }} else {{
        alimHtml += '<p style="color:#888;font-size:13px">Aucune inspection trouvée dans le cache local pour ce SIREN.</p>';
      }}
      if (alimFreshness) alimHtml += `<p style="font-size:11px;color:#aaa;margin-top:8px">Dernière collecte Alim'confiance: ${{fmtDate(alimFreshness.collected_at)}}</p>`;
      document.getElementById('alim-card').innerHTML = alimHtml;

      const deptSet = new Set([...(ent.ania_sites||[]).map(s => s.dept), siege.departement].filter(Boolean));
      const myParls = parlData.filter(p => deptSet.has(p.dept)).sort((a,b) => b.score-a.score).slice(0, 20);
      let parlHtml = '<h3 style="margin-bottom:12px">Élus du territoire</h3>';
      if (myParls.length) {{
        parlHtml += '<div style="overflow-x:auto"><table><thead><tr><th>Élu</th><th>Chambre</th><th>Groupe</th><th>Dept</th><th style="text-align:center">Score ARIA</th></tr></thead><tbody>';
        myParls.forEach(p => {{
          const chambreBadge = p.chambre==='AN' ? 'badge-an' : 'badge-sen';
          parlHtml += `<tr><td><a href="fiche.html?id=${{p.id}}" style="color:#1a1a2e;text-decoration:none;font-weight:600;border-bottom:1px dotted #ccc">${{p.nom}}</a></td><td><span class="badge ${{chambreBadge}}">${{p.chambre}}</span></td><td style="font-size:12px">${{p.groupe_abrev}}</td><td style="text-align:center">${{p.dept}}</td><td style="text-align:center;font-weight:700">${{p.score.toFixed(1)}}</td></tr>`;
        }});
        parlHtml += '</tbody></table></div>';
      }} else {{
        parlHtml += '<p style="color:#888;font-size:13px">Aucun parlementaire identifié pour les départements couverts.</p>';
      }}
      document.getElementById('parl-card').innerHTML = parlHtml;

      let sitesHtml = '<h3 style="margin-bottom:12px">Sites de production ANIA ('+(ent.ania_sites||[]).length+')</h3>';
      if ((ent.ania_sites||[]).length) {{
        ent.ania_sites.forEach(site => {{
          sitesHtml += `<div class="etab-item"><div><b>${{site.nom}}</b><div style="font-size:11px;color:#888">${{site.naf_label}} (${{site.naf}})</div></div><div style="text-align:right;font-size:12px;color:#666">${{site.cp}} ${{site.commune}}<br><span style="font-size:11px">Dept ${{site.dept}} - ${{site.aria_region}}</span></div></div>`;
        }});
      }} else {{
        sitesHtml += '<p style="color:#888;font-size:13px">Cette entreprise n\\'apparaît pas dans le périmètre IAA retenu.</p>';
      }}
      document.getElementById('sites-card').innerHTML = sitesHtml;
    }} catch(error) {{
      document.getElementById('loading').style.display='none';
      document.getElementById('error').style.display='block';
      document.getElementById('error-msg').textContent='Erreur technique: '+error.message;
    }}
  }})();
}}
</script>
</body>
</html>"""
    (SITE_DIR / 'fiche-entreprise.html').write_text(html, encoding='utf-8')
    print('    OK fiche-entreprise.html')


def write_methodologie():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - Méthodologie</title>
{FAVICON}
<style>{BASE_CSS}
.meth-section {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; }}
.meth-title {{ font-size: 17px; font-weight: 700; margin-bottom: 16px; color: #1a1a2e; border-bottom: 2px solid #e85d04; padding-bottom: 8px; }}
.formula-box {{ background: #1a1a2e; color: white; border-radius: 8px; padding: 16px 20px; font-family: 'Courier New', monospace; font-size: 14px; line-height: 1.8; margin: 12px 0; }}
.vote-item {{ display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; align-items: flex-start; }}
.vote-badge {{ background: #1a1a2e; color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; white-space: nowrap; }}
</style>
</head>
<body>
{write_nav('methodologie.html')}
<div class="container" style="max-width:900px">
  <div class="page-title">Méthodologie et Sources</div>
  <div class="page-subtitle">Comment sont calculés les scores et d'où viennent les données</div>

  <div class="meth-section">
    <div class="meth-title">Formule du score ARIA</div>
    <p style="font-size:13px;color:#555;margin-bottom:12px">Le score ARIA mesure la <strong>priorité de contact</strong> d'un élu pour les affaires publiques des industries alimentaires : un élu fortement ancré dans une zone de production IAA ET actif sur les dossiers agricoles est prioritaire.</p>
    <div class="formula-box">
score_aria = score_eco x (1 + score_impl / 10)<br>
<br>
# Score implantation (poids économique de la zone)<br>
score_eco = nb_sites_aria (établissements IAA dans le département)<br>
<br>
# Score implication parlementaire<br>
score_impl = 3 x membre_commission_agriculture<br>
           + 2 x membre_mission_egalim<br>
           + 1 x membre_commission_economique<br>
           + 0.5 x taux_participation
    </div>
  </div>

  <div class="meth-section">
    <div class="meth-title">Votes nominatifs suivis (5 scrutins)</div>
    <div class="vote-item"><span class="vote-badge">EGALIM 1</span><div><strong>Loi 2018-938</strong> - Relations commerciales dans le secteur agricole et alimentation</div></div>
    <div class="vote-item"><span class="vote-badge">EGALIM 2</span><div><strong>Loi 2021-1357</strong> - Protection de la rémunération des agriculteurs</div></div>
    <div class="vote-item"><span class="vote-badge">EGALIM 3</span><div><strong>Loi 2023-221 / Descrozaille</strong> - Equilibre des relations commerciales</div></div>
    <div class="vote-item"><span class="vote-badge">LOA 2024</span><div><strong>Loi d'orientation agricole 2024</strong> - Souveraineté agricole</div></div>
    <div class="vote-item" style="border-bottom:none"><span class="vote-badge">PPL Revenu Agri</span><div><strong>2024</strong> - PPL relative au revenu des agriculteurs</div></div>
  </div>

  <div class="meth-section">
    <div class="meth-title">Périmètre national - 16 associations ARIA</div>
    <p style="font-size:13px;color:#555;margin-bottom:12px">27 201 établissements IAA (PME, ETI, GE - codes NAF 10.* et 11.*) sur l'ensemble du territoire français.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px">
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AREA Occitanie (3 415 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AREA Nouvelle Aquitaine (3 252 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">ARIA AURA (3 183 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">ARIA Grand Est (2 291 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">ARIA Sud (2 275 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AREA Ile-de-France (2 221 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">ABEA (1 487 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AREA Pays de la Loire (1 305 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">Vitagora (1 295 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">Agro-Spheres (1 294 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AREA Normandie (1 127 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AREA Centre-Val de Loire (841 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">ADIR - Reunion (770 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">ARIA Corse (593 sites)</div>
      <div style="padding:8px;background:#f8f9fa;border-radius:6px">AMPI - Martinique (417 sites)</div>
    </div>
  </div>

  <div class="meth-section">
    <div class="meth-title">Sources de données</div>
    <table style="font-size:13px">
      <thead><tr><th>Source</th><th>Données</th></tr></thead>
      <tbody>
        <tr><td><strong>Assemblée Nationale</strong> (open data)</td><td>Députés, groupes, scrutins nominatifs, commissions</td></tr>
        <tr><td><strong>Sénat</strong> (data.senat.fr)</td><td>Sénateurs actifs, commissions permanentes</td></tr>
        <tr><td><strong>SIRENE / INSEE</strong></td><td>27 201 établissements IAA actifs (codes NAF 10.* + 11.*) - géolocalisation</td></tr>
        <tr><td><strong>16 associations ARIA</strong></td><td>Rattachement régional de chaque établissement</td></tr>
      </tbody>
    </table>
  </div>

  <div style="background:#1a1a2e;color:rgba(255,255,255,.7);border-radius:12px;padding:20px 24px;text-align:center;font-size:13px">
    Cartographie <strong style="color:#e85d04">ANIA × Parlementaires</strong> - 16 associations ARIA - Données collectées en avril 2026
  </div>
</div>
</body>
</html>"""
    (SITE_DIR / 'methodologie.html').write_text(html, encoding='utf-8')
    print('    OK methodologie.html')


def write_fiche():
    """Fiche individuelle d'un parlementaire (chargée côté client via ?id=xxx)."""
    scrutin_meta_json = json.dumps(SCRUTINS_META, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA - Fiche parlementaire</title>
{FAVICON}
<style>{BASE_CSS}
.fiche-header {{ background:#1a1a2e; color:white; padding:28px 32px; border-radius:12px; margin-bottom:20px; }}
.fiche-nom {{ font-size:26px; font-weight:700; margin-bottom:6px; }}
.fiche-meta {{ font-size:14px; opacity:.8; display:flex; gap:16px; flex-wrap:wrap; }}
.section-title {{ font-size:15px; font-weight:700; margin-bottom:12px; color:#1a1a2e; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
.vote-row {{ display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:13px; }}
.vote-row:last-child {{ border-bottom:none; }}
.score-bar {{ background:#eee; border-radius:4px; height:8px; margin-top:4px; }}
.score-bar-fill {{ height:8px; border-radius:4px; background:#e85d04; }}
.recent-row {{ display:grid; grid-template-columns:1fr auto; gap:10px; padding:10px 0; border-bottom:1px solid #f0f0f0; }}
.recent-row:last-child {{ border-bottom:none; }}
.brief-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-bottom:14px; }}
.score-breakdown {{ margin-top:12px; display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
@media(max-width:768px) {{
  .grid-2, .brief-grid, .score-breakdown {{ grid-template-columns:1fr; }}
  .fiche-header {{ padding:22px 20px; }}
}}
</style>
</head>
<body>
{write_nav('parlementaires.html')}
<div class="container" style="max-width:900px">
<a href="parlementaires.html" style="color:#666;font-size:13px;display:inline-block;margin-bottom:16px">← Retour à la liste</a>
<div id="content"><div class="card" style="padding:40px;text-align:center;color:#888">Chargement...</div></div>
</div>
<script>
const SCRUTINS_META = {scrutin_meta_json};
const VOTE_COLORS = {{pour:'#28a745',contre:'#dc3545',abstention:'#fd7e14',absent:'#bbb'}};
const VOTE_LABELS = {{pour:'Pour',contre:'Contre',abstention:'Abstention',absent:'Absent'}};

function voteRow(label, v, loi) {{
  const c = VOTE_COLORS[v] || '#eee';
  const voteLabel = VOTE_LABELS[v] || '-';
  return `<div class="vote-row">
    <div>
      <div style="font-weight:600">${{label}}</div>
      ${{loi?`<div style="font-size:11px;color:#888">Loi ${{loi}}</div>`:''}}
    </div>
    <span style="background:${{c}};color:${{v==='absent'||!v?'#555':'white'}};padding:4px 12px;border-radius:5px;font-size:12px;font-weight:600">${{voteLabel}}</span>
  </div>`;
}}

function priorityLabel(p) {{
  if (p.score >= 250) return 'Priorité forte';
  if (p.score >= 80) return 'Priorité moyenne';
  if (p.nb_sites > 0 || p.commission_agri || p.commission_eco || p.mission_egalim) return 'À qualifier';
  return 'Veille simple';
}}

function approachAngle(p) {{
  if (p.mission_egalim) return 'Entrer par les relations commerciales et la chaîne de valeur alimentaire.';
  if (p.commission_agri) return 'Entrer par la souveraineté alimentaire, les producteurs et la transformation locale.';
  if (p.commission_eco) return 'Entrer par compétitivité, emploi industriel et contraintes réglementaires.';
  if (p.nb_sites > 0) return 'Entrer par l’empreinte économique locale et les sites IAA de son territoire.';
  return 'Surveiller les prises de position publiques avant sollicitation prioritaire.';
}}

function vigilancePoint(p) {{
  if ((p.position||'').includes('contre')) return 'Historique de vote défavorable: préparer des preuves territoriales factuelles.';
  if ((p.position||'').includes('partag')) return 'Posture mixte: cadrer le rendez-vous sur un dossier précis.';
  if (!p.nb_sites) return 'Faible exposition territoriale identifiée: ne pas prioriser sans signal parlementaire récent.';
  return 'Rester factuel: score de priorité relationnelle, pas notation politique.';
}}

const params = new URLSearchParams(window.location.search);
const id = params.get('id');
if (!id) {{ document.getElementById('content').innerHTML='<div class="card" style="padding:24px">ID manquant dans l\\'URL</div>'; }}

Promise.all([
  fetch('data/parlementaires.json').then(r=>r.json()),
  fetch('data/parlementaires_recent.json').then(r=>r.json()).catch(()=>({{}})),
]).then(([data, recentIndex]) => {{
  const p = data.find(d => d.id === id || d.nom.toLowerCase().replace(/\\s+/g,'-') === id);
  if (!p) {{
    document.getElementById('content').innerHTML = '<div class="card" style="padding:24px">Parlementaire non trouvé.</div>';
    return;
  }}
  document.title = `ANIA - ${{p.nom}}`;
  const chambreColor = p.chambre === 'AN' ? '#e85d04' : '#4361ee';

  const badgesHtml = [
    p.commission_agri ? '<span class="badge badge-agri">Commission Agriculture</span>' : '',
    p.commission_eco  ? '<span class="badge badge-eco">Commission Économique</span>' : '',
    p.mission_egalim  ? '<span class="badge badge-egalim">Mission EGALIM</span>' : '',
    p.commission_env  ? '<span class="badge" style="background:#d1e7dd;color:#0a4023">Commission Environnement</span>' : '',
  ].filter(Boolean).join(' ');

  const votesHtml = p.chambre === 'AN' ?
    SCRUTINS_META.map(s => voteRow(s.label, (p.votes||{{}})[s.id], s.loi)).join('') :
    '<div style="padding:16px;color:#888;font-size:13px">Les votes nominatifs sont disponibles uniquement pour les députés (AN). Les sénateurs votent selon des procédures différentes.</div>';

  const scoreMax = 800;
  const scoreWidth = Math.min(100, (p.score / scoreMax) * 100);
  const recentItems = ((recentIndex||{{}})[p.id]||{{}}).items || [];

  const sitesList = p.entreprises ? p.entreprises.split(';').filter(Boolean).slice(0, 30).map(e=>`<div style="font-size:12px;padding:3px 0;border-bottom:1px solid #f5f5f5">${{e.trim()}}</div>`).join('') + (p.entreprises.split(';').length > 30 ? `<div style="font-size:11px;color:#888;padding:6px 0">... et ${{p.entreprises.split(';').length - 30}} autres</div>` : '') : '<span style="color:#999;font-size:12px">Aucun site IAA dans la zone</span>';
  const recentHtml = recentItems.length
    ? recentItems.map(item => `<div class="recent-row"><div><div style="font-weight:600;font-size:13px">${{item.title}}</div><div style="font-size:11px;color:#888">${{item.source}} · ${{new Date(item.published_at).toLocaleDateString('fr-FR')}}</div></div><span class="badge" style="background:#f8f9fa;color:#445">${{(item.themes||[])[0]||'Signal'}}</span></div>`).join('')
    : '<div style="font-size:13px;color:#888">Aucun signal récent rattaché nominativement dans les flux suivis.</div>';

  document.getElementById('content').innerHTML = `
    <div class="fiche-header">
      <div class="fiche-nom">${{p.nom}}</div>
      <div class="fiche-meta">
        <span style="background:${{chambreColor}};padding:3px 10px;border-radius:5px;font-size:13px;font-weight:600">${{p.chambre === 'AN' ? 'Assemblée nationale' : 'Sénat'}}</span>
        <span>${{p.groupe}}</span>
        <span>Dept. ${{p.dept}} - ${{p.nom_dept}}</span>
        ${{p.circo ? `<span>Circ. ${{p.circo}}</span>` : ''}}
      </div>
    </div>

    <div class="card" style="margin-bottom:16px;border-left:4px solid var(--accent)">
      <div class="section-title">Brief rendez-vous</div>
      <div class="brief-grid">
        <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Priorité</div><div style="font-weight:800">${{priorityLabel(p)}}</div></div>
        <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Preuve locale</div><div style="font-weight:800">${{p.nb_sites}} site${{p.nb_sites>1?'s':''}} IAA</div></div>
        <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Posture</div><div style="font-weight:800">${{p.position||'non qualifiée'}}</div></div>
      </div>
      <div style="display:grid;gap:10px;font-size:13px;line-height:1.55">
        <div><strong>Angle d’approche.</strong> ${{approachAngle(p)}}</div>
        <div><strong>Justification.</strong> Score ${{p.score.toFixed(1)}} combinant exposition territoriale, commissions, historique public et votes suivis.</div>
        <div><strong>Point de vigilance.</strong> ${{vigilancePoint(p)}}</div>
      </div>
      <div class="evidence">Sources: Assemblée nationale, Sénat, SIRENE, scrutins publics, flux de veille · données générées localement</div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="section-title">Score ANIA</div>
        <div style="font-size:13px;color:#666;margin-bottom:4px">Score global (implantation × implication)</div>
        <div style="font-size:32px;font-weight:700;color:#e85d04">${{p.score.toFixed(1)}}</div>
        <div class="score-bar"><div class="score-bar-fill" style="width:${{scoreWidth}}%"></div></div>
        <div class="score-breakdown">
          <div style="text-align:center;background:#f8f9fa;border-radius:6px;padding:8px">
            <div style="font-size:18px;font-weight:700">${{p.score_eco.toFixed(1)}}</div>
            <div style="font-size:10px;color:#888">Implantation</div>
          </div>
          <div style="text-align:center;background:#f8f9fa;border-radius:6px;padding:8px">
            <div style="font-size:18px;font-weight:700">${{p.score_impl.toFixed(1)}}</div>
            <div style="font-size:10px;color:#888">Implication</div>
          </div>
          <div style="text-align:center;background:#f8f9fa;border-radius:6px;padding:8px">
            <div style="font-size:18px;font-weight:700">${{p.score_egalim||0}}</div>
            <div style="font-size:10px;color:#888">EGALIM</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="section-title">Engagement parlementaire</div>
        ${{badgesHtml || '<span style="color:#999;font-size:13px">Pas de commission agriculture identifiée</span>'}}
        ${{p.position && p.position !== 'inconnu' ? `<div style="margin-top:10px;font-size:13px;font-weight:600">Position votes : ${{p.position}}</div>` : ''}}
        ${{p.commission ? `<div style="font-size:12px;color:#888;margin-top:8px">${{p.commission}}</div>` : ''}}
        ${{p.aria_regions && p.aria_regions !== 'Non rattaché' ? `<div style="font-size:12px;color:#888;margin-top:4px">Région : ${{p.aria_regions}}</div>` : ''}}
        ${{p.mail ? `<div style="margin-top:12px"><a href="mailto:${{p.mail}}" style="color:#4361ee;font-size:13px">${{p.mail}}</a></div>` : ''}}
        ${{p.twitter ? `<div style="margin-top:4px"><a href="https://twitter.com/${{p.twitter.replace('@','')}}" target="_blank" rel="noopener noreferrer" style="color:#1d9bf0;font-size:13px">@${{p.twitter.replace('@','')}}</a></div>` : ''}}
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="section-title">Votes nominatifs</div>
        ${{votesHtml}}
      </div>

      <div class="card">
        <div class="section-title">Sites IAA dans la zone (${{p.nb_sites}} site${{p.nb_sites>1?'s':''}})</div>
        ${{p.nb_vins > 0 ? '<div style="font-size:11px;color:#8b1a1a;margin-bottom:6px">dont '+p.nb_vins+' sites viticoles</div>' : ''}}
        ${{p.nb_huiles > 0 ? '<div style="font-size:11px;color:#6b9e3a;margin-bottom:6px">dont '+p.nb_huiles+' sites oléicoles</div>' : ''}}
        <div style="max-height:300px;overflow-y:auto">${{sitesList}}</div>
      </div>
    </div>

    <div class="card">
      <div class="section-title">Activité récente détectée</div>
      <div style="font-size:12px;color:#666;margin-bottom:8px">Flux croisés Assemblée, Sénat, ANIA et signaux de veille associés.</div>
      ${{recentHtml}}
    </div>
  `;
}});
</script>
</body>
</html>"""
    (SITE_DIR / 'fiche.html').write_text(html, encoding='utf-8')
    print('    OK fiche.html')


def write_dossiers_chauds():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA · Dossiers chauds</title>
{FAVICON}
<style>{BASE_CSS}
.dossier-card {{ background:white; border-radius:14px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:14px; border-left:5px solid #e85d04; }}
.evidence-item {{ padding:8px 0; border-top:1px solid #f1f1f1; font-size:13px; }}
</style>
</head>
<body>
{write_nav('dossiers-chauds.html')}
<div class="container">
  <div class="page-title">Dossiers chauds</div>
  <div class="page-subtitle">Priorisation par volume de signaux, récence et diversité des sources officielles.</div>
  <div id="dossiers"></div>
</div>
<script>
{JS_SAFE_HELPERS}
fetch('data/hot_dossiers.json').then(r => r.json()).then(rows => {{
  document.getElementById('dossiers').innerHTML = rows.map(row => `
    <div class="dossier-card">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
        <div>
          <div style="font-size:20px;font-weight:800;color:#1a1a2e">${{esc(row.theme)}}</div>
          <div style="font-size:12px;color:#666;margin-top:4px">${{Number(row.score||0)}} signaux · ${{Number(row.source_count||0)}} sources · dernier signal ${{fmtDateSafe(row.latest_at)}}</div>
        </div>
        <span class="badge badge-egalim">Priorité ${{Number(row.score||0)}}</span>
      </div>
      <div style="margin-top:12px;font-size:12px;color:#555">Sources: ${{(row.sources||[]).map(esc).join(' · ')}}</div>
      ${{(row.evidence||[]).map(item => `<div class="evidence-item"><a href="${{safeHref(item.source_url)}}" target="_blank" rel="noopener noreferrer" style="color:#1a1a2e;text-decoration:none;font-weight:600">${{esc(item.title)}}</a><div style="font-size:11px;color:#888">${{esc(item.source)}} · ${{fmtDateSafe(item.published_at)}}</div></div>`).join('')}}
    </div>`).join('') || '<div class="card">Aucun dossier chaud calculé.</div>';
}});
</script>
</body>
</html>"""
    (SITE_DIR / 'dossiers-chauds.html').write_text(html, encoding='utf-8')
    print('    OK dossiers-chauds.html')


def write_timeline_reglementaire():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA · Timeline réglementaire</title>
{FAVICON}
<style>{BASE_CSS}
.timeline-item {{ background:white; border-radius:14px; padding:18px 20px; box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:12px; }}
</style>
</head>
<body>
{write_nav('timeline-reglementaire.html')}
<div class="container">
  <div class="page-title">Timeline réglementaire</div>
  <div class="page-subtitle">Fil consolidé des publications parlementaires, débats, presse institutionnelle et signaux ANIA.</div>
  <div id="timeline"></div>
</div>
<script>
{JS_SAFE_HELPERS}
fetch('data/timeline_reglementaire.json').then(r => r.json()).then(rows => {{
  document.getElementById('timeline').innerHTML = rows.slice(0, 120).map(item => `
    <div class="timeline-item">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
        <div>
          <a href="${{safeHref(item.source_url)}}" target="_blank" rel="noopener noreferrer" style="font-size:16px;font-weight:700;color:#1a1a2e;text-decoration:none">${{esc(item.title)}}</a>
          <div style="font-size:12px;color:#777;margin-top:6px">${{esc(item.source)}} · ${{fmtDateSafe(item.published_at, true)}}</div>
          ${{item.summary ? `<div style="font-size:13px;color:#444;line-height:1.5;margin-top:10px">${{esc(item.summary)}}</div>` : ''}}
        </div>
        <span class="badge" style="background:#f3f4f6;color:#374151">${{esc((item.themes||[])[0]||'Signal')}}</span>
      </div>
    </div>`).join('');
}});
</script>
</body>
</html>"""
    (SITE_DIR / 'timeline-reglementaire.html').write_text(html, encoding='utf-8')
    print('    OK timeline-reglementaire.html')


def write_veille_thematique():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA · Veille thématique</title>
{FAVICON}
<style>{BASE_CSS}
.theme-card {{ background:white; border-radius:14px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:14px; }}
</style>
</head>
<body>
{write_nav('veille-thematique.html')}
<div class="container">
  <div class="page-title">Veille thématique</div>
  <div class="page-subtitle">Agrégation des flux par thème métier pour préparer notes, rendez-vous et arbitrages.</div>
  <div id="themes"></div>
</div>
<script>
{JS_SAFE_HELPERS}
fetch('data/veille_thematique.json').then(r => r.json()).then(rows => {{
  document.getElementById('themes').innerHTML = rows.map(row => `
    <div class="theme-card">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
        <div><div style="font-size:18px;font-weight:800">${{esc(row.theme)}}</div><div style="font-size:12px;color:#777;margin-top:4px">${{Number(row.count||0)}} signaux · dernier mouvement ${{fmtDateSafe(row.latest_at)}}</div></div>
        <span class="badge badge-eco">${{Number(row.count||0)}}</span>
      </div>
      <div style="margin-top:12px;display:grid;gap:8px">
        ${{(row.items||[]).map(item => `<div style="padding-top:8px;border-top:1px solid #f1f1f1"><a href="${{safeHref(item.source_url)}}" target="_blank" rel="noopener noreferrer" style="color:#1a1a2e;text-decoration:none;font-weight:600">${{esc(item.title)}}</a><div style="font-size:11px;color:#888">${{esc(item.source)}} · ${{fmtDateSafe(item.published_at)}}</div></div>`).join('')}}
      </div>
    </div>`).join('');
}});
</script>
</body>
</html>"""
    (SITE_DIR / 'veille-thematique.html').write_text(html, encoding='utf-8')
    print('    OK veille-thematique.html')


def write_lobbying():
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{NOINDEX}
<title>ANIA · Lobbying récent</title>
{FAVICON}
<style>{BASE_CSS}
.action-card {{ background:white; border-radius:14px; padding:18px 20px; box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:12px; }}
</style>
</head>
<body>
{write_nav('lobbying.html')}
<div class="container">
  <div class="page-title">Lobbying récent</div>
  <div class="page-subtitle">Lecture HATVP structurée pour repérer thèmes, volumes et interlocuteurs publics autour des dossiers suivis.</div>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-value" id="lobby-actions">-</div><div class="stat-label">Actions récentes</div></div>
    <div class="stat-card"><div class="stat-value" id="lobby-orgs">-</div><div class="stat-label">Organisations visibles</div></div>
    <div class="stat-card"><div class="stat-value" id="lobby-years">-</div><div class="stat-label">Années couvertes</div></div>
  </div>
  <div id="top-orgs" class="card" style="margin-bottom:16px"></div>
  <div id="actions"></div>
</div>
<script>
{JS_SAFE_HELPERS}
fetch('data/lobbying_recent.json').then(r => r.json()).then(payload => {{
  const actions = payload.recent_actions || [];
  const orgs = payload.top_organisations || [];
  const years = Object.keys(payload.volumes_by_year || {{}}).length;
  document.getElementById('lobby-actions').textContent = actions.length;
  document.getElementById('lobby-orgs').textContent = orgs.length;
  document.getElementById('lobby-years').textContent = years;
  document.getElementById('top-orgs').innerHTML = '<div style="font-size:16px;font-weight:700;margin-bottom:10px">Organisations les plus visibles</div>' + orgs.map(row => `<div style="display:flex;justify-content:space-between;padding:8px 0;border-top:1px solid #f1f1f1"><span>${{esc(row.organisation)}}</span><span class="badge badge-agri">${{Number(row.count||0)}}</span></div>`).join('');
  document.getElementById('actions').innerHTML = actions.map(action => `
    <div class="action-card">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
        <div>
          <div style="font-size:16px;font-weight:800;color:#1a1a2e">${{esc(action.organisation || 'Organisation non renseignée')}}</div>
          <div style="font-size:12px;color:#777;margin-top:4px">${{fmtDateSafe(action.published_at)}} · ${{esc(action.categorie || 'Catégorie non renseignée')}}</div>
          <div style="font-size:14px;font-weight:700;margin-top:10px">${{esc(action.title)}}</div>
          ${{action.summary ? `<div style="font-size:13px;color:#444;margin-top:8px;line-height:1.5">${{esc(action.summary)}}</div>` : ''}}
        </div>
        <span class="badge" style="background:#f3f4f6;color:#374151">${{esc((action.themes||[])[0]||'Signal')}}</span>
      </div>
    </div>`).join('');
}});
</script>
</body>
</html>"""
    (SITE_DIR / 'lobbying.html').write_text(html, encoding='utf-8')
    print('    OK lobbying.html')


def write_index_redirect():
    """Ajoute un index.html a la racine si accueil.html est la page principale."""
    pass  # index.html est deja la carte interactive


def write_seo_files():
    pages = [
        "accueil.html",
        "dossiers-chauds.html",
        "timeline-reglementaire.html",
        "veille-thematique.html",
        "parlementaires.html",
        "index.html",
        "entreprises.html",
        "regions.html",
        "methodologie.html",
        "lobbying.html",
        "groupes.html",
        "partis.html",
    ]
    robots = "\n".join([
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {SITE_URL}sitemap.xml",
        "",
    ])
    (SITE_DIR / "robots.txt").write_text(robots, encoding="utf-8")

    sitemap_items = "\n".join(
        f"  <url><loc>{SITE_URL}{page}</loc><changefreq>daily</changefreq><priority>{'1.0' if page == 'accueil.html' else '0.7'}</priority></url>"
        for page in pages
    )
    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{sitemap_items}
</urlset>
"""
    (SITE_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print("    OK robots.txt / sitemap.xml / .nojekyll")


def main():
    print('=' * 55)
    print('GENERATEUR MINISITE IAA FRANCE x PARLEMENTAIRES')
    print('=' * 55)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    parl, sites, partis, groupes, regions, entreprises = build_json_data()

    print('\n[2] Generation des pages HTML...')
    write_accueil(parl, sites, regions)
    write_index()
    write_dossiers_chauds()
    write_timeline_reglementaire()
    write_veille_thematique()
    write_parlementaires()
    write_fiche()
    write_lobbying()
    write_entreprises()
    write_fiche_entreprise()
    write_regions(regions)
    write_partis()
    write_groupes()
    write_methodologie()
    write_seo_files()

    print(f'\nMinisite genere dans {SITE_DIR}/')
    print(f'   {len(list(SITE_DIR.glob("*.html")))} pages HTML')
    print(f'   {len(list(DATA_DIR.glob("*.json")))} fichiers JSON')


if __name__ == '__main__':
    main()
