# Données

| Dossier | Contenu | Versionné ? |
| --- | --- | --- |
| `raw/` | Réponses brutes de l'API Hémicycle, telles que reçues (cache). | ❌ Non — chacun garde son cache en local |
| `processed/` | Données nettoyées et agrégées, prêtes à être affichées par le front. | ✅ Oui |

## Conventions

- Nommer les fichiers de façon explicite : `<objet>_<filtre>_<date>.json`, ex. `scrutins_l17_2026-11-14.json`.
- Préférer JSON pour le front, CSV pour l'analyse et le partage.
- Garder les identifiants officiels (ex. `PA…` pour les acteurs, `PIONANR…` pour les textes) pour pouvoir recouper.
- Chaque fichier de `processed/` doit garder la trace de ses sources (champ `source` ou fichier `*.sources.json` à côté).

## Inventaire des jeux de données

| Fichier | Description | Source (endpoint) | Produit par |
| --- | --- | --- | --- |
| _…_ | _…_ | _ex. `GET /scrutins`_ | _script / personne_ |
