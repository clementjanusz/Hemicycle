# Hémicycle — Hackathon open data

> Un **rapport journalistique mensuel** sur l'activité parlementaire, construit sur les données ouvertes via [Hémicycle](https://hemicycle.ai/), avec un **chatbot** pour que les lecteurs puissent creuser chaque numéro.

On travaille comme une rédaction, pas comme un SaaS :

- **une fois par mois**, un pipeline collecte et prépare les données, l'équipe vérifie et rédige ;
- **le site est statique** : il publie le numéro du mois et les archives ;
- **le chatbot** répond aux questions des lecteurs en se sourçant sur le rapport, et peut compléter avec le serveur MCP d'Hémicycle. Le LLM est fourni par [Featherless](https://featherless.ai/).

**Sujet / angle** : _à définir en équipe — voir [`docs/EDITORIAL.md`](docs/EDITORIAL.md)_

---

## L'équipe

| Nom | Rôle | Pôle | GitHub |
| --- | --- | --- | --- |
| _…_ | Rédaction / angle | Éditorial | `@…` |
| _…_ | Pipeline de données | Back-end | `@…` |
| _…_ | Chatbot | Back-end | `@…` |
| _…_ | Dataviz / intégration | Front-end | `@…` |
| _…_ | Design / UX | Front-end | `@…` |

## Organisation du repo

```
.
├── backend/
│   ├── pipeline/    # Batch mensuel : collecte Hémicycle → nettoyage → indicateurs
│   └── chatbot/     # Seul service en ligne : Featherless + MCP Hémicycle + rapport
├── frontend/        # Site statique : numéro du mois, dataviz, archives, widget chatbot
├── rapports/
│   ├── _modele/     # Modèle d'un numéro
│   └── AAAA-MM/     # Un dossier par numéro (rapport.md)
├── data/
│   ├── raw/         # Réponses brutes de l'API, par mois (non versionnées)
│   └── processed/   # Données vérifiées + indicateurs.json, par mois (versionnées)
├── docs/
│   ├── EDITORIAL.md       # Format du rapport, baromètre, focus, règles du chatbot
│   ├── ARCHITECTURE.md    # Vue d'ensemble, cycle mensuel, contrats de données
│   └── API_HEMICYCLE.md   # Mémo de l'API et du serveur MCP Hémicycle
└── .github/         # Modèles d'issues et de pull requests
```

Chaque partie a son README : [`backend/`](backend/README.md), [`frontend/`](frontend/README.md), [`rapports/`](rapports/README.md), [`data/`](data/README.md).

## Démarrage rapide

1. **Cloner le repo**
   ```bash
   git clone https://github.com/clementjanusz/Hemicycle.git
   cd Hemicycle
   ```
2. **Créer ses clés**
   - Hémicycle : [hemicycle.ai/compte-api](https://hemicycle.ai/compte-api) (clé de test `hmc_test_…`, gratuite)
   - Featherless (pour le chatbot) : depuis le [tableau de bord Featherless](https://featherless.ai/)
3. **Configurer l'environnement**
   ```bash
   cp .env.example .env
   # puis renseigner les clés dans .env
   ```
4. **Tester l'accès à l'API Hémicycle**
   ```bash
   source .env
   curl "https://api.hemicycle.ai/v1/scrutins?legislature=17&limit=5" \
     -H "Authorization: Bearer $HEMICYCLE_API_KEY" \
     -H "Hemicycle-Version: $HEMICYCLE_API_VERSION"
   ```
5. Lire [`CONTRIBUTING.md`](CONTRIBUTING.md) avant de pousser du code.

> ⚠️ **Quota des clés de test Hémicycle : 100 appels/jour par compte.** Mettez en cache tout ce que vous récupérez et évitez les boucles d'appels inutiles. Chaque membre peut créer son propre compte pour avoir son propre quota.

## Règles d'or

- **Les clés ne sortent jamais du back-end.** Jamais dans le code front, jamais dans un commit. `.env` est ignoré par git.
- **Toute donnée publiée est sourcée.** Chaque réponse de l'API contient un objet `source` (éditeur, URL officielle, licence) : on le conserve jusqu'au rapport final.
- **Le rapport fait foi.** Le chatbot s'appuie d'abord sur ce que la rédaction a vérifié, et signale ce qui vient d'Hémicycle en direct.
- **On ne pousse pas directement sur `main`** : une branche + une pull request relue par une autre personne.

## Liens utiles

- Documentation Hémicycle : <https://hemicycle.ai/docs>
- Référence de l'API : <https://hemicycle.ai/docs/api>
- Serveur MCP Hémicycle : <https://hemicycle.ai/docs/mcp>
- Documentation Featherless : <https://featherless.ai/docs/overview>
- Tool calling sur Featherless : <https://featherless.ai/docs/tool-calling>
