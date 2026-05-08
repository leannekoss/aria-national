# ANIA Radar Parlementaire

Site statique GitHub Pages pour cartographier l'empreinte IAA, prioriser les élus et suivre les signaux parlementaires utiles aux affaires publiques ANIA/ARIA.

## Build local

Depuis ce repo:

```bash
python3 scripts/build_site.py
```

Ce build exécute:

1. `scripts/pipeline_national.py`: normalisation IAA, élus, commissions, votes et scores.
2. `scripts/fresh_data.py`: collecte des flux frais et publication des JSON de veille.
3. `scripts/render_site.py`: génération des pages HTML et JSON publics.

Pour régénérer uniquement le rendu après une modification d'interface:

```bash
python3 scripts/render_site.py
```

Servir ensuite le site en HTTP local:

```bash
python3 -m http.server 8080
```

## Sources et fraîcheur

Les sources officielles sont collectées côté build et exposées avec provenance dans `data/freshness.json`.

| Source | Type | Auth | Fréquence cible | Fallback |
|---|---|---|---|---|
| Assemblée nationale | RSS + open data AMO/scrutins | non | 15 min à 24 h selon flux | cache `build/raw` |
| Sénat | RSS + `data.senat.fr` | non | 1 h à 24 h | cache `build/raw` |
| HATVP | dump CSV zip vues fusionnées | non | nightly | cache zip |
| ANIA | RSS + WordPress JSON | non | 1 h | cache JSON/XML |
| Alim'confiance | export JSON | non | optionnel/nightly | n'est pas bloquant sans cache |
| Légifrance | API PISTE | OAuth | désactivé par défaut | à activer plus tard |

Chaque item frais doit conserver `source`, `source_url`, `published_at`, `collected_at` et `freshness_status`.

## Données publiques générées

Les fichiers consommés par le front sont dans `data/`:

- `parlementaires.json`
- `sites.json`
- `entreprises.json`
- `regions.json`
- `company_details.json`
- `freshness.json`
- `hot_dossiers.json`
- `timeline_reglementaire.json`
- `parlementaires_recent.json`
- `lobbying_recent.json`
- `veille_thematique.json`

## Garde-fous

- Ne pas éditer manuellement les HTML générés si une modification doit survivre au build: modifier `scripts/render_site.py`.
- Ne pas réintroduire d'appels navigateur vers les API métier (`recherche-entreprises`, Alim'confiance, GitHub raw GeoJSON).
- Conserver les volumes attendus après refonte: 925 élus, environ 27k sites IAA, environ 21k entreprises.
- Le score est une priorité relationnelle sourcée, pas une notation politique ou morale.
