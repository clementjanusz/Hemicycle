# Données

Les données sont rangées **par mois** (`AAAA-MM`), un dossier par numéro du rapport.

```
data/
├── raw/
│   └── 2026-10/         # Réponses brutes de l'API Hémicycle (cache de collecte)
└── processed/
    └── 2026-10/
        ├── indicateurs.json   # Les chiffres du mois (lus par le site et le chatbot)
        └── …                  # Données détaillées : votes, amendements, textes…
```

| Dossier | Contenu | Versionné ? |
| --- | --- | --- |
| `raw/AAAA-MM/` | Réponses brutes de l'API, telles que reçues. | ❌ Non par défaut (décision à prendre : voir [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)) |
| `processed/AAAA-MM/` | Données nettoyées et indicateurs du mois. | ✅ Oui — c'est ce qui est publié |

## Règles

- **Un mois publié ne se modifie plus.** En cas d'erreur : corriger, regénérer, et signaler l'erratum dans le rapport.
- **Pas de chiffre sans méthode ni source** : chaque indicateur a un champ `methode` et un champ `source`.
- **Identifiants officiels conservés** (acteurs, textes, scrutins) pour pouvoir recouper d'un mois à l'autre.
- Format des indicateurs : voir le contrat dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Inventaire des jeux de données

| Fichier (dans `processed/AAAA-MM/`) | Description | Endpoint(s) Hémicycle | Utilisé par |
| --- | --- | --- | --- |
| `indicateurs.json` | Chiffres du baromètre et du focus | _plusieurs_ | Site, chatbot |
| _…_ | _…_ | _ex. `GET /scrutins`_ | _…_ |
