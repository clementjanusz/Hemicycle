# Architecture

## Le principe

On fonctionne comme une **rédaction** qui publie un **rapport mensuel**, pas comme un SaaS :

- les données sont produites **une fois par mois**, hors ligne, puis vérifiées par des humains ;
- le site est **statique** : il affiche des fichiers déjà calculés ;
- la seule partie dynamique est le **chatbot** : il répond aux lecteurs en s'appuyant d'abord sur le rapport, et peut compléter via le **serveur MCP d'Hémicycle**. Le LLM est fourni par **Featherless**.

## Vue d'ensemble

```
─── UNE FOIS PAR MOIS (hors ligne) ─────────────────────────────────────────

  API Hémicycle ──▶ PIPELINE ──────────▶ data/processed/AAAA-MM/ ──▶ PR + vérification
  (REST)            collecte              indicateurs.json                 │
                    transformation                                         ▼
                    indicateurs              RÉDACTION ──▶ rapports/AAAA-MM/rapport.md

─── EN CONTINU (lecteurs) ──────────────────────────────────────────────────

  Lecteur ──▶ SITE STATIQUE   lit rapports/ et data/processed/
                   │
                   │  POST /chat
                   ▼
              CHATBOT ──────▶ Featherless (LLM, API compatible OpenAI)
              contexte :  │
              rapport +   └──▶ MCP Hémicycle (outils en lecture seule,
              indicateurs          liste blanche, budget limité)
```

Le détail du chatbot (boucle d'outils, règles de sourçage, garde-fous) est dans [`backend/README.md`](../backend/README.md#le-chatbot).

## Le cycle de production d'un numéro

1. **Collecte** — le pipeline tourne pour le mois écoulé (manuellement ou via GitHub Actions) et ouvre une PR `data: rapport AAAA-MM`.
2. **Vérification** — l'équipe relit les chiffres, compare avec le mois précédent, repère les anomalies.
3. **Choix du focus** — la rédaction choisit le sujet d'enquête du mois (une issue « Piste éditoriale »).
4. **Rédaction et dataviz** — texte dans `rapports/AAAA-MM/rapport.md`, graphiques dans le front.
5. **Relecture** — fact-checking (checklist dans [`EDITORIAL.md`](EDITORIAL.md)).
6. **Publication** — merge sur `main` : le site et le chatbot passent au nouveau numéro.

## Décisions techniques

| Sujet | Décision | Pourquoi | Qui |
| --- | --- | --- | --- |
| Fournisseur LLM du chatbot | **Featherless** | Choix de l'équipe : modèles open-weight, API compatible OpenAI | |
| Accès aux données pour le chatbot | **MCP Hémicycle** + rapport injecté dans le prompt | Le rapport fait foi, le MCP complète | |
| Modèle Featherless | **`NousResearch/Arete-27B`** | Choix de l'équipe ; *tool calling* annoncé, 32K de contexte | |
| Langage du pipeline | _…_ | | |
| Langage du chatbot | _…_ | | |
| Format de stockage (JSON, CSV, Parquet, DuckDB) | _…_ | | |
| Déclenchement du pipeline (manuel / GitHub Actions) | _…_ | | |
| Versionner `data/raw/` (archive de preuve) ou non | _…_ | | |
| Liste blanche des outils MCP du chatbot | _…_ | | |
| Framework du site statique | _…_ | | |
| Librairie de dataviz | _…_ | | |
| Hébergement du site | _…_ | | |
| Hébergement du chatbot | _…_ | | |

## Contrats de données

Fixés tôt, ils permettent au front, au pipeline et au chatbot d'avancer en parallèle (le front peut travailler avec des fichiers d'exemple).

### `data/processed/AAAA-MM/indicateurs.json`

Les chiffres du mois, lus par le site **et** par le chatbot. Format proposé :

```json
{
  "mois": "2026-10",
  "genere_le": "2026-11-01T06:00:00Z",
  "indicateurs": [
    {
      "id": "nb_scrutins_an",
      "rubrique": "barometre",
      "libelle": "Scrutins publics à l'Assemblée nationale",
      "valeur": 0,
      "unite": "scrutins",
      "valeur_mois_precedent": 0,
      "methode": "Nombre de scrutins publics dont la date tombe dans le mois",
      "source": {
        "editeur": "Assemblée nationale",
        "url": "https://…",
        "licence": "Licence Ouverte 2.0"
      }
    }
  ]
}
```

### `POST /chat` — le seul endpoint dynamique

Requête :

```json
{
  "mois": "2026-10",
  "question": "Comment a voté le groupe X sur le texte Y ?",
  "historique": [
    { "role": "user", "contenu": "…" },
    { "role": "assistant", "contenu": "…" }
  ]
}
```

Réponse (en streaming si possible) :

```json
{
  "reponse": "…",
  "sources": [
    { "type": "rapport", "section": "Baromètre", "passage": "…" },
    { "type": "indicateur", "id": "nb_scrutins_an" },
    { "type": "hemicycle", "outil": "resultat_scrutin", "url": "https://…", "verifie_par_la_redaction": false }
  ]
}
```

Le champ `type` permet au site d'afficher différemment ce qui vient du rapport (vérifié) et ce qui vient d'Hémicycle en direct (non vérifié).

### Conventions générales

- JSON, clés en `snake_case`, dates au format ISO 8601.
- Chaque donnée affichable porte un champ `source` : `{ "editeur", "url", "licence" }`.
- Les mois sont toujours notés `AAAA-MM`.

## Ports en local

| Service | Port |
| --- | --- |
| Site (front-end) | `5173` _(à ajuster selon le framework)_ |
| Chatbot | `8000` |
