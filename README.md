# Hémicycle — Hackathon open data

> Rapport journalistique interactif construit sur les données parlementaires ouvertes, via l'API [Hémicycle](https://hemicycle.ai/).

**Sujet / angle** : _à définir en équipe — voir [`docs/EDITORIAL.md`](docs/EDITORIAL.md)_

---

## L'équipe

| Nom | Rôle | Pôle | GitHub |
| --- | --- | --- | --- |
| _…_ | Rédaction / angle | Éditorial | `@…` |
| _…_ | Analyse de données | Back-end | `@…` |
| _…_ | API / back-end | Back-end | `@…` |
| _…_ | Dataviz / intégration | Front-end | `@…` |
| _…_ | Design / UX | Front-end | `@…` |

## Organisation du repo

```
.
├── frontend/        # Le rapport : page web, dataviz, mise en récit
├── backend/         # Appels à l'API Hémicycle, cache, préparation des données
├── data/
│   ├── raw/         # Réponses brutes de l'API (non versionnées)
│   └── processed/   # Jeux de données nettoyés, prêts pour le front (versionnés)
├── docs/
│   ├── EDITORIAL.md       # Angle, questions, plan du rapport, sources
│   ├── ARCHITECTURE.md    # Comment front et back communiquent + choix techniques
│   └── API_HEMICYCLE.md   # Mémo de l'API Hémicycle (auth, endpoints, limites…)
└── .github/         # Modèles d'issues et de pull requests
```

Chaque pôle a son propre README : [`frontend/README.md`](frontend/README.md) et [`backend/README.md`](backend/README.md).

## Démarrage rapide

1. **Cloner le repo**
   ```bash
   git clone <url-du-repo>
   cd Hemicycle
   ```
2. **Créer sa clé API Hémicycle** sur [hemicycle.ai/compte-api](https://hemicycle.ai/compte-api) (clé de test `hmc_test_…`, gratuite).
3. **Configurer l'environnement**
   ```bash
   cp .env.example .env
   # puis renseigner HEMICYCLE_API_KEY dans .env
   ```
4. **Tester l'accès à l'API**
   ```bash
   source .env
   curl "https://api.hemicycle.ai/v1/scrutins?legislature=17&limit=5" \
     -H "Authorization: Bearer $HEMICYCLE_API_KEY" \
     -H "Hemicycle-Version: $HEMICYCLE_API_VERSION"
   ```
5. Lire [`CONTRIBUTING.md`](CONTRIBUTING.md) avant de pousser du code.

> ⚠️ **Quota des clés de test : 100 appels/jour par compte.** Mettez en cache tout ce que vous récupérez (`data/raw/`) et évitez les boucles d'appels inutiles. Chaque membre peut créer son propre compte pour avoir son propre quota.

## Règles d'or

- **La clé API ne sort jamais du back-end.** Jamais dans le code front, jamais dans un commit. `.env` est ignoré par git.
- **Toute donnée publiée est sourcée.** Chaque réponse de l'API contient un objet `source` (éditeur, URL officielle, licence) : on le conserve jusqu'au rapport final.
- **On ne pousse pas directement sur `main`** : une branche + une pull request relue par une autre personne.

## Liens utiles

- Documentation Hémicycle : <https://hemicycle.ai/docs>
- Référence de l'API : <https://hemicycle.ai/docs/api>
- Spécification OpenAPI : <https://hemicycle.ai/docs/openapi>
- Serveur MCP (pour explorer les données depuis Claude, ChatGPT, Cursor…) : `https://api.hemicycle.ai/mcp`
