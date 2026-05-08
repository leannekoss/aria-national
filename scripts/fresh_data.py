#!/usr/bin/env python3
"""Collect official fresh sources and publish normalized public JSON files."""

from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from common import (
    DATA_DIR,
    NORMALIZED_DIR,
    RAW_DIR,
    REPORTS_DIR,
    cache_fetch,
    ensure_dirs,
    read_json,
    utc_now_iso,
    write_json,
)


THEME_KEYWORDS = {
    "Egalim & relations commerciales": ["egalim", "relations commerciales", "fournisseur", "distributeur", "descrozaille"],
    "Agriculture & souveraineté": ["agriculture", "agricole", "agriculteur", "souveraineté alimentaire", "alimentation"],
    "Emballages & environnement": ["emballage", "plastique", "déchet", "recycl", "ppwr", "environnement", "consigne"],
    "Santé & nutrition": ["nutrition", "santé", "étiquetage", "nutri", "sanitaire", "sécurité alimentaire"],
    "Compétitivité & export": ["industrie", "export", "compétitivité", "économie", "commerce", "douane", "prix"],
}

BUSINESS_KEYWORDS = sorted({kw for values in THEME_KEYWORDS.values() for kw in values})

RSS_SOURCES = [
    {
        "id": "assemblee_documents",
        "label": "Assemblée nationale · publications",
        "url": "https://www2.assemblee-nationale.fr/feeds/detail/documents-parlementaires",
        "cache": RAW_DIR / "feeds" / "assemblee_documents.xml",
        "max_age_hours": 0.25,
        "category": "parlementaire",
    },
    {
        "id": "assemblee_debats",
        "label": "Assemblée nationale · débats",
        "url": "https://www2.assemblee-nationale.fr/feeds/detail/crs",
        "cache": RAW_DIR / "feeds" / "assemblee_debats.xml",
        "max_age_hours": 0.25,
        "category": "débat",
    },
    {
        "id": "assemblee_presse",
        "label": "Assemblée nationale · presse",
        "url": "https://www.assemblee-nationale.fr/dyn/rss/communiques-de-presse.xml",
        "cache": RAW_DIR / "feeds" / "assemblee_presse.xml",
        "max_age_hours": 1,
        "category": "presse",
    },
    {
        "id": "senat_rapports",
        "label": "Sénat · rapports",
        "url": "https://www.senat.fr/rss/rapports.rss",
        "cache": RAW_DIR / "feeds" / "senat_rapports.xml",
        "max_age_hours": 1,
        "category": "parlementaire",
    },
    {
        "id": "senat_textes",
        "label": "Sénat · textes",
        "url": "https://www.senat.fr/rss/textes.rss",
        "cache": RAW_DIR / "feeds" / "senat_textes.xml",
        "max_age_hours": 1,
        "category": "parlementaire",
    },
    {
        "id": "senat_presse",
        "label": "Sénat · presse",
        "url": "https://www.senat.fr/rss/presse.rss",
        "cache": RAW_DIR / "feeds" / "senat_presse.xml",
        "max_age_hours": 1,
        "category": "presse",
    },
    {
        "id": "senat_agriculture",
        "label": "Sénat · thème agriculture",
        "url": "https://www.senat.fr/themes/rss/therss2.rss",
        "cache": RAW_DIR / "feeds" / "senat_agriculture.xml",
        "max_age_hours": 1,
        "category": "thématique",
    },
    {
        "id": "ania_feed",
        "label": "ANIA · flux RSS",
        "url": "https://www.ania.net/feed",
        "cache": RAW_DIR / "feeds" / "ania_feed.xml",
        "max_age_hours": 1,
        "category": "fédération",
    },
]

JSON_SOURCES = [
    {
        "id": "ania_posts",
        "label": "ANIA · WordPress posts",
        "url": "https://www.ania.net/wp-json/wp/v2/posts?per_page=25&_fields=id,date,modified,slug,link,title.rendered",
        "cache": RAW_DIR / "ania_posts.json",
        "max_age_hours": 1,
        "category": "fédération",
    },
    {
        "id": "ania_events",
        "label": "ANIA · WordPress events",
        "url": "https://www.ania.net/wp-json/tribe/events/v1/events?per_page=25",
        "cache": RAW_DIR / "ania_events.json",
        "max_age_hours": 6,
        "category": "fédération",
    },
]

HATVP_ZIP = "https://www.hatvp.fr/agora/opendata/csv/Vues_Fusionnees.zip"
ALIM_EXPORT = (
    "https://dgal.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "export_alimconfiance/exports/json"
)
MAX_HATVP_ACTION_ROWS = 150_000


def slugify(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value).lower()
    value = re.sub(r"[^a-z0-9à-ÿ]+", "-", value)
    return value.strip("-")


def strip_html(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def to_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
    return None


def freshness_status(published_at: str | None) -> str:
    if not published_at:
        return "unknown"
    dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if age_hours <= 24:
        return "fresh"
    if age_hours <= 24 * 7:
        return "recent"
    return "stale"


def classify_themes(text: str) -> list[str]:
    haystack = strip_html(text).lower()
    matches = [theme for theme, keywords in THEME_KEYWORDS.items() if any(keyword in haystack for keyword in keywords)]
    return matches or ["Autres signaux"]


def source_error_status(source: dict, exc: Exception) -> dict:
    cache = source.get("cache")
    has_fallback = bool(cache and Path(cache).exists())
    return {
        "id": source.get("id", "unknown"),
        "label": source.get("label", source.get("id", "Source")),
        "url": source.get("url", ""),
        "refreshed_now": False,
        "collected_at": utc_now_iso(),
        "item_count": 0,
        "freshness_status": "stale" if has_fallback else "error",
        "fallback_used": has_fallback,
        "stale_since": utc_now_iso(),
        "error": str(exc),
    }


def parse_rss_items(source: dict) -> tuple[list[dict], dict]:
    content, refreshed = cache_fetch(
        source["url"],
        source["cache"],
        max_age_hours=source["max_age_hours"],
        binary=False,
        timeout=60,
    )
    root = ET.fromstring(content)
    channel = root.find("channel")
    items = []
    for item in channel.findall("item")[:30]:
        title = strip_html(item.findtext("title"))
        description_nodes = item.findall("description")
        description = strip_html(" ".join(node.text or "" for node in description_nodes))
        published_at = to_iso_date(item.findtext("pubDate"))
        url = item.findtext("link") or item.findtext("guid") or ""
        body = f"{title} {description}"
        items.append(
            {
                "id": f'{source["id"]}:{slugify(title or url)}',
                "source_id": source["id"],
                "source": source["label"],
                "source_url": url or source["url"],
                "published_at": published_at,
                "collected_at": utc_now_iso(),
                "freshness_status": freshness_status(published_at),
                "type": source["category"],
                "title": title,
                "summary": description,
                "themes": classify_themes(body),
            }
        )

    meta = {
        "id": source["id"],
        "label": source["label"],
        "url": source["url"],
        "refreshed_now": refreshed,
        "collected_at": utc_now_iso(),
        "item_count": len(items),
        "freshness_status": "fresh" if items else "unknown",
        "fallback_used": not refreshed and source["cache"].exists(),
    }
    return items, meta


def parse_json_sources() -> tuple[list[dict], list[dict]]:
    items = []
    statuses = []
    for source in JSON_SOURCES:
        content, refreshed = cache_fetch(
            source["url"],
            source["cache"],
            max_age_hours=source["max_age_hours"],
            binary=False,
            timeout=60,
        )
        payload = json.loads(content)
        if source["id"] == "ania_posts":
            for post in payload:
                title = strip_html(post.get("title", {}).get("rendered"))
                published_at = to_iso_date(post.get("date"))
                items.append(
                    {
                        "id": f'ania_posts:{post.get("id")}',
                        "source_id": source["id"],
                        "source": source["label"],
                        "source_url": post.get("link", ""),
                        "published_at": published_at,
                        "collected_at": utc_now_iso(),
                        "freshness_status": freshness_status(published_at),
                        "type": "fédération",
                        "title": title,
                        "summary": "",
                        "themes": classify_themes(title),
                    }
                )
        else:
            for event in payload.get("events", [])[:25]:
                title = strip_html(event.get("title"))
                published_at = to_iso_date(event.get("date_utc") or event.get("date"))
                items.append(
                    {
                        "id": f'ania_events:{event.get("id")}',
                        "source_id": source["id"],
                        "source": source["label"],
                        "source_url": event.get("url", ""),
                        "published_at": published_at,
                        "collected_at": utc_now_iso(),
                        "freshness_status": freshness_status(published_at),
                        "type": "événement",
                        "title": title,
                        "summary": strip_html(event.get("description", "")),
                        "themes": classify_themes(f"{title} {event.get('description', '')}"),
                    }
                )
        statuses.append(
            {
                "id": source["id"],
                "label": source["label"],
                "url": source["url"],
                "refreshed_now": refreshed,
                "collected_at": utc_now_iso(),
                "item_count": len(payload) if isinstance(payload, list) else len(payload.get("events", [])),
                "freshness_status": "fresh",
                "fallback_used": not refreshed and source["cache"].exists(),
            }
        )
    return items, statuses


def collect_hatvp() -> tuple[dict, dict]:
    content, refreshed = cache_fetch(
        HATVP_ZIP,
        RAW_DIR / "hatvp_vues_fusionnees.zip",
        max_age_hours=18,
        binary=True,
        timeout=120,
    )
    info_by_id = {}
    actions = []

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        with archive.open("Vues_Fusionnees/1_informations_generales.csv") as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8"), delimiter=";")
            for row in reader:
                info_by_id[row["representants_id"]] = {
                    "organisation": row.get("denomination") or row.get("sigle_HATVP") or "",
                    "identifiant_national": row.get("identifiant_national") or "",
                    "categorie": row.get("label_categorie_organisation") or "",
                    "ville": row.get("ville") or "",
                    "site_web": row.get("site_web") or "",
                }
        with archive.open("Vues_Fusionnees/2_actions.csv") as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8"), delimiter=";")
            for row_index, row in enumerate(reader):
                if row_index >= MAX_HATVP_ACTION_ROWS:
                    break
                published_at = to_iso_date(row.get("date_publication_activite") or row.get("date_publication"))
                info = info_by_id.get(row.get("representants_id", ""), {})
                title = row.get("objet_activite") or row.get("decision_concernee") or row.get("action_menee") or "Action HATVP"
                summary = " · ".join(
                    filter(
                        None,
                        [
                            row.get("domaines_intervention_actions_menees"),
                            row.get("responsable_public"),
                            row.get("beneficiaire_action_menee"),
                        ],
                    )
                )
                body = f'{info.get("organisation", "")} {title} {summary}'.lower()
                themes = classify_themes(body)
                actions.append(
                    {
                        "id": f'hatvp:{row.get("activite_id") or row.get("action_representation_interet_id") or row.get("representants_id")}',
                        "organisation": info.get("organisation", ""),
                        "identifiant_national": info.get("identifiant_national", ""),
                        "categorie": info.get("categorie", ""),
                        "ville": info.get("ville", ""),
                        "published_at": published_at,
                        "title": title,
                        "summary": summary,
                        "decision": row.get("decision_concernee") or "",
                        "responsable_public": row.get("responsable_public") or "",
                        "beneficiaire_action_menee": row.get("beneficiaire_action_menee") or "",
                        "themes": themes,
                        "sector_match": any(keyword in body for keyword in BUSINESS_KEYWORDS),
                    }
                )

    actions = [item for item in actions if item["published_at"]]
    actions.sort(key=lambda item: item["published_at"], reverse=True)
    relevant = [item for item in actions if item["sector_match"]] or actions[:40]
    yearly_counter = Counter(item["published_at"][:4] for item in relevant if item.get("published_at"))
    top_orgs = Counter(item["organisation"] for item in relevant if item.get("organisation")).most_common(10)

    payload = {
        "generated_at": utc_now_iso(),
        "source": "HATVP · Vues fusionnées",
        "source_url": HATVP_ZIP,
        "recent_actions": relevant[:60],
        "volumes_by_year": dict(sorted(yearly_counter.items(), reverse=True)),
        "top_organisations": [{"organisation": name, "count": count} for name, count in top_orgs],
    }
    meta = {
        "id": "hatvp",
        "label": "HATVP · vues fusionnées",
        "url": HATVP_ZIP,
        "refreshed_now": refreshed,
        "collected_at": utc_now_iso(),
        "item_count": len(actions),
        "freshness_status": "fresh" if actions else "unknown",
        "fallback_used": not refreshed and (RAW_DIR / "hatvp_vues_fusionnees.zip").exists(),
    }
    return payload, meta


def collect_alim_index() -> tuple[dict, dict]:
    cache_path = RAW_DIR / "alimconfiance.json"
    if cache_path.exists():
        content, refreshed = cache_fetch(
            ALIM_EXPORT,
            cache_path,
            max_age_hours=24,
            binary=False,
            timeout=45,
        )
        rows = json.loads(content)
    else:
        rows = []
        refreshed = False
    index = defaultdict(list)
    for row in rows:
        siret = (row.get("siret") or "").strip()
        siren = siret[:9] if len(siret) >= 9 else ""
        if not siren:
            continue
        index[siren].append(
            {
                "siret": siret,
                "date_inspection": row.get("date_inspection"),
                "type_activite": row.get("type_activite"),
                "synthese_eval_sanit": row.get("synthese_eval_sanit"),
                "app_code_synthese_eval_sanit": row.get("app_code_synthese_eval_sanit"),
                "type_suite": row.get("type_suite"),
                "evaluation_globale": row.get("evaluation_globale"),
                "denree": row.get("denree"),
                "agrement": row.get("agrement"),
                "libelle_agrement": row.get("libelle_agrement"),
                "adresse_activite": row.get("adresse_activite"),
                "libelle_commune": row.get("libelle_commune"),
            }
        )
    compact_index = {siren: sorted(records, key=lambda row: row.get("date_inspection") or "", reverse=True)[:10] for siren, records in index.items()}
    meta = {
        "id": "alimconfiance",
        "label": "Alim'confiance · export JSON",
        "url": ALIM_EXPORT,
        "refreshed_now": refreshed,
        "collected_at": utc_now_iso(),
        "item_count": len(rows),
        "freshness_status": "fresh" if rows else "stale",
        "fallback_used": not refreshed and (RAW_DIR / "alimconfiance.json").exists(),
        "note": "Enrichissement optionnel: le build ne bloque pas si le dump complet n'est pas encore cache.",
    }
    return compact_index, meta


def load_parliamentarians() -> list[dict]:
    path = NORMALIZED_DIR / "parlementaires_national.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_parliamentarian_recent(items: list[dict], parliamentarians: list[dict]) -> dict:
    matched = defaultdict(list)
    needles = []
    for row in parliamentarians:
        pid = row.get("id") or slugify(row.get("nom_complet", ""))
        full = f'{row.get("prenom", "").strip()} {row.get("nom", "").strip()}'.strip()
        surname = row.get("nom", "").strip()
        patterns = [full] if full else []
        if surname and len(re.sub(r"[^A-Za-zÀ-ÿ]", "", surname)) >= 4:
            patterns.append(surname)
        if patterns:
            needles.append((pid, row.get("nom_complet", full), [p.lower() for p in patterns if p]))

    for item in items:
        haystack = f'{item.get("title", "")} {item.get("summary", "")}'.lower()
        for pid, name, patterns in needles:
            if any(pattern and pattern in haystack for pattern in patterns):
                matched[pid].append(
                    {
                        "title": item["title"],
                        "source": item["source"],
                        "source_url": item["source_url"],
                        "published_at": item["published_at"],
                        "themes": item["themes"],
                    }
                )

    return {
        pid: {"nom": name, "items": sorted(rows, key=lambda row: row["published_at"], reverse=True)[:8]}
        for pid, rows in matched.items()
        for _, name, _ in [next(entry for entry in needles if entry[0] == pid)]
    }


def build_hot_dossiers(items: list[dict]) -> list[dict]:
    buckets = defaultdict(lambda: {"count": 0, "latest_at": None, "sources": set(), "evidence": []})
    for item in items:
        for theme in item["themes"]:
            bucket = buckets[theme]
            bucket["count"] += 1
            bucket["sources"].add(item["source"])
            if not bucket["latest_at"] or item["published_at"] > bucket["latest_at"]:
                bucket["latest_at"] = item["published_at"]
            if len(bucket["evidence"]) < 4:
                bucket["evidence"].append(
                    {
                        "title": item["title"],
                        "source": item["source"],
                        "source_url": item["source_url"],
                        "published_at": item["published_at"],
                    }
                )
    hot = []
    for theme, bucket in buckets.items():
        hot.append(
            {
                "theme": theme,
                "score": bucket["count"],
                "latest_at": bucket["latest_at"],
                "source_count": len(bucket["sources"]),
                "sources": sorted(bucket["sources"]),
                "evidence": bucket["evidence"],
            }
        )
    hot.sort(key=lambda row: (row["score"], row["latest_at"] or ""), reverse=True)
    return hot[:8]


def build_veille_thematique(items: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for item in items:
        for theme in item["themes"]:
            groups[theme].append(item)
    payload = []
    for theme, rows in groups.items():
        rows.sort(key=lambda item: item["published_at"] or "", reverse=True)
        payload.append(
            {
                "theme": theme,
                "count": len(rows),
                "latest_at": rows[0]["published_at"] if rows else None,
                "items": [
                    {
                        "title": item["title"],
                        "source": item["source"],
                        "source_url": item["source_url"],
                        "published_at": item["published_at"],
                    }
                    for item in rows[:12]
                ],
            }
        )
    payload.sort(key=lambda row: (row["count"], row["latest_at"] or ""), reverse=True)
    return payload


def main() -> None:
    ensure_dirs()
    statuses = []
    all_items = []

    for source in RSS_SOURCES:
        try:
            items, meta = parse_rss_items(source)
        except Exception as exc:
            items = []
            meta = source_error_status(source, exc)
        all_items.extend(items)
        statuses.append(meta)

    try:
        json_items, json_statuses = parse_json_sources()
    except Exception as exc:
        json_items = []
        json_statuses = [
            source_error_status(source, exc)
            for source in JSON_SOURCES
        ]
    all_items.extend(json_items)
    statuses.extend(json_statuses)

    try:
        hatvp_payload, hatvp_status = collect_hatvp()
    except Exception as exc:
        hatvp_payload = {
            "generated_at": utc_now_iso(),
            "source": "HATVP · Vues fusionnées",
            "source_url": HATVP_ZIP,
            "recent_actions": [],
            "volumes_by_year": {},
            "top_organisations": [],
        }
        hatvp_status = source_error_status({"id": "hatvp", "label": "HATVP · vues fusionnées", "url": HATVP_ZIP}, exc)

    try:
        alim_index, alim_status = collect_alim_index()
    except Exception as exc:
        alim_index = read_json(NORMALIZED_DIR / "alim_index.json", default={}) or {}
        alim_status = source_error_status({"id": "alimconfiance", "label": "Alim'confiance · export JSON", "url": ALIM_EXPORT}, exc)
    statuses.extend([hatvp_status, alim_status])

    all_items = [item for item in all_items if item.get("published_at")]
    all_items.sort(key=lambda item: item["published_at"], reverse=True)

    parliamentarians = load_parliamentarians()
    parlementaires_recent = build_parliamentarian_recent(all_items, parliamentarians)
    hot_dossiers = build_hot_dossiers(all_items)
    veille_thematique = build_veille_thematique(all_items)

    freshness_payload = {
        "generated_at": utc_now_iso(),
        "overall_status": "fresh" if statuses else "unknown",
        "sources": statuses
        + [
            {
                "id": "legifrance",
                "label": "Légifrance API",
                "url": "https://www.legifrance.gouv.fr/contenu/pied-de-page/open-data-et-api",
                "enabled": False,
                "freshness_status": "disabled",
                "note": "Prévu mais désactivé par défaut tant que PISTE/OAuth n'est pas configuré.",
            }
        ],
    }
    run_report = {
        "generated_at": utc_now_iso(),
        "sources": statuses,
        "counts": {
            "timeline_items": len(all_items),
            "hot_dossiers": len(hot_dossiers),
            "veille_thematique": len(veille_thematique),
            "parlementaires_recent": len(parlementaires_recent),
            "lobbying_recent": len(hatvp_payload["recent_actions"]),
            "alim_index": len(alim_index),
        },
    }

    write_json(NORMALIZED_DIR / "fresh_timeline.json", all_items)
    write_json(NORMALIZED_DIR / "parlementaires_recent.json", parlementaires_recent)
    write_json(NORMALIZED_DIR / "alim_index.json", alim_index)
    write_json(DATA_DIR / "timeline_reglementaire.json", all_items[:120])
    write_json(DATA_DIR / "hot_dossiers.json", hot_dossiers)
    write_json(DATA_DIR / "veille_thematique.json", veille_thematique)
    write_json(DATA_DIR / "parlementaires_recent.json", parlementaires_recent)
    write_json(DATA_DIR / "lobbying_recent.json", hatvp_payload)
    write_json(DATA_DIR / "freshness.json", freshness_payload)
    write_json(REPORTS_DIR / "run-report.json", run_report, pretty=True)
    print("Collecte fraîche terminée.")


if __name__ == "__main__":
    main()
