"""Manual business inclusions for strategic ANIA coverage.

These entries are intentional exceptions to the default IAA production NAF
filter. They keep the data pipeline reproducible without widening the whole
scope to wholesale or services.
"""

from __future__ import annotations


MANUAL_COMPANY_INDEX = {
    "447654385": {
        "siren": "447654385",
        "nom_complet": "Sacré Willy (POIL A GRATTER)",
        "nom_raison_sociale": "POIL A GRATTER",
        "sigle": "Sacré Willy",
        "categorie_entreprise": "PME",
        "nature_juridique": "5710",
        "etat_administratif": "A",
        "activite_principale": "46.33Z",
        "activite_principale_naf25": "46.33Y",
        "section_activite_principale": "G",
        "tranche_effectif_salarie": "12",
        "annee_tranche_effectif_salarie": "2023",
        "date_creation": "2003-02-10",
        "date_mise_a_jour": "2026-05-08T10:50:27",
        "date_mise_a_jour_insee": "2025-12-06T05:52:22",
        "date_mise_a_jour_rne": "2024-05-19T17:01:20",
        "nombre_etablissements": 4,
        "nombre_etablissements_ouverts": 1,
        "caractere_employeur": "",
        "complements": {
            "est_alim_confiance": True,
            "convention_collective_renseignee": True,
            "liste_idcc": ["0573"],
        },
        "finances": {
            "2024": {
                "ca": 0,
                "resultat_net": 50232,
            }
        },
        "dirigeants": [
            {
                "nom": "GUINCHARD",
                "prenoms": "CHRISTIAN WILLY EDMOND",
                "annee_de_naissance": "1951",
                "date_de_naissance": "1951-12",
                "qualite": "Président de SAS",
                "type_dirigeant": "personne physique",
            },
            {
                "siren": "902650357",
                "denomination": "MGI",
                "qualite": "Directeur Général",
                "type_dirigeant": "personne morale",
            },
        ],
        "siege": {
            "activite_principale": "46.33Z",
            "adresse": "ZAE EST 5 RUE CHARLES NUNGESSER 05130 TALLARD",
            "code_postal": "05130",
            "commune": "05170",
            "departement": "05",
            "est_siege": True,
            "etat_administratif": "A",
            "latitude": "44.460368111",
            "libelle_commune": "TALLARD",
            "longitude": "6.0345120861",
            "siret": "44765438500049",
            "tranche_effectif_salarie": "12",
        },
        "matching_etablissements": [
            {
                "siret": "44765438500049",
                "commune": "05170",
                "libelle_commune": "TALLARD",
                "adresse": "ZAE EST 5 RUE CHARLES NUNGESSER 05130 TALLARD",
                "latitude": "44.460368111",
                "longitude": "6.0345120861",
                "etat_administratif": "A",
                "est_siege": True,
            }
        ],
        "aliases": ["Sacré Willy", "Sacre Willy", "POIL A GRATTER", "Poil à Gratter"],
        "manual_reason": "Exception métier ANIA: marque agroalimentaire stratégique hors NAF industriels 10/11.",
    }
}


MANUAL_SITES = [
    {
        "siren": "447654385",
        "siret": "44765438500049",
        "nom_complet": "Sacré Willy (POIL A GRATTER)",
        "categorie_entreprise": "PME",
        "naf": "46.33Z",
        "adresse": "ZAE EST 5 RUE CHARLES NUNGESSER 05130 TALLARD",
        "commune": "TALLARD",
        "code_postal": "05130",
        "dept": "05",
        "aria_region": "ARIA Sud",
        "latitude": 44.460368111,
        "longitude": 6.0345120861,
        "manual_reason": "Exception métier ANIA: marque agroalimentaire stratégique hors NAF industriels 10/11.",
    }
]
