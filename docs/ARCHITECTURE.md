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
| Modèle Featherless | **`Qwen/Qwen3.8-27B`** | Seul modèle testé qui réussit l'aller-retour d'outils complet (Qwen3-32B renvoyait des sorties de modération avec `tools`) ; 256K de contexte | |
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

Réponse (d'un bloc ; pour suivre la progression pendant l'attente, voir [`POST /chat/flux`](#post-chatflux--la-même-réponse-avec-la-progression) ci-dessous) :

```json
{
  "reponse": "…",
  "sources": [
    { "type": "rapport", "mois": "2026-10", "section": "Cohésion des groupes", "section_id": "cohesion-des-groupes", "passage": "…" },
    { "type": "indicateur", "id": "nb_scrutins_an" },
    { "type": "hemicycle", "outil": "resultat_scrutin", "url": "https://…", "verifie_par_la_redaction": false }
  ],
  "actions": [
    {
      "type": "surligner_section",
      "section_id": "cohesion-des-groupes",
      "titre": "Cohésion des groupes",
      "raison": "Indique le taux de cohésion de chaque groupe."
    }
  ]
}
```

Le champ `type` des sources permet au site d'afficher différemment ce qui vient du rapport (vérifié) et ce qui vient d'Hémicycle en direct (non vérifié).

#### Le champ `actions` : surligner la partie du rapport qui répond

`actions` est une liste d'instructions pour la page de lecture, **toujours présente** (liste vide si aucune action). Elle est produite par l'outil `surligner_section` du chatbot ([`backend/chatbot/outils_rapport.py`](../backend/chatbot/outils_rapport.py)) : quand la question porte sur un sujet traité dans le rapport, le modèle désigne la section la plus pertinente ; le serveur vérifie que l'identifiant existe, puis renvoie l'action au front. Rien n'est exécuté côté serveur.

| Champ | Type | Contenu |
| --- | --- | --- |
| `type` | chaîne | `"surligner_section"` (seul type pour l'instant ; ignorer tout type inconnu). |
| `section_id` | chaîne | Identifiant de la section, tel que renvoyé par `GET /api/rapport/{mois}` (ex. `cohesion-des-groupes`). Toujours valide pour le `mois` de la requête. |
| `titre` | chaîne | Titre de la section, pour un libellé du type « Voir la section « Cohésion des groupes » ». |
| `raison` | chaîne | Courte phrase (200 caractères au plus) rédigée par le modèle : ce que la section dit sur la question. Peut être vide. |

Garanties côté serveur : **deux actions au plus** par réponse, jamais deux fois la même section, aucune action quand la question n'est pas traitée par le rapport.

Ce que le front doit faire de chaque action `surligner_section`, dans l'ordre de la liste :

1. Retrouver l'élément de la page qui porte `id="<section_id>"` (chaque section du rapport est rendue avec son identifiant comme attribut `id`). S'il n'existe pas (ancienne version de la page, autre numéro affiché), ne rien faire : pas d'erreur, pas de défilement.
2. Faire défiler la page jusqu'à cette section avec un défilement doux (`scrollIntoView({ behavior: "smooth", block: "start" })`), en tenant compte d'un éventuel en-tête fixe (`scroll-margin-top`). Avec deux actions, ne défiler que jusqu'à la première ; surligner les deux.
3. Mettre la section en évidence de façon visible (fond coloré et/ou bordure latérale animée), puis estomper l'effet après quelques secondes (4 à 6 s). Respecter `prefers-reduced-motion` : sans animation, un simple surlignage temporaire suffit.
4. Option : afficher sous la réponse du chatbot un lien « Voir la section « `titre` » » (qui rejoue le défilement et le surlignage), avec `raison` en infobulle ; pour l'accessibilité, annoncer la section mise en évidence dans une zone `aria-live="polite"`.

Les identifiants sont des *slugs* stables calculés à partir des titres `##` et `###` du rapport : minuscules, sans accents, mots séparés par des tirets (`L'essentiel du mois` → `l-essentiel-du-mois`) ; pour un titre de la forme « Catégorie : sous-titre », seule la catégorie compte (`Focus : …` → `focus`) ; un titre peut fixer son identifiant avec un suffixe `{#mon-id}` ; en cas de doublon, `-2`, `-3`…

#### `POST /chat/flux` — la même réponse, avec la progression

Une question prend de 8 à 45 s (un à trois appels au modèle, plus les appels Hémicycle). Pour afficher où en est le chatbot pendant l'attente, `POST /chat/flux` accepte **exactement le même corps** que `POST /chat` (avec ou sans `mois`) et renvoie les événements au fil de l'eau ; `POST /chat` reste inchangé.

Réponse : HTTP 200, `Content-Type: application/x-ndjson`, en-têtes `Cache-Control: no-store` et `X-Accel-Buffering: no` (pas de mise en mémoire tampon par un proxy). **Un objet JSON par ligne**, terminé par `\n`, envoyé dès qu'il est prêt. Quatre types :

| `type` | Champs | Quand |
| --- | --- | --- |
| `etape` | `code`, `message` (texte à afficher tel quel), `t` (secondes depuis le début de la question, une décimale) ; pour `code: "hemicycle"`, aussi `outil` (nom de l'endpoint) et `requete` (requête REST équivalente, `null` si elle ne peut pas être calculée) | À chaque étape (voir ci-dessous) |
| `appel` | `appel` : l'entrée de `outils_utilises` de la réponse finale (mêmes champs : `outil`, `titre`, `arguments`, `statut`, `credits`, `duree_s`, `requete`…) ; `indice` : sa position dans `outils_utilises` | Quand un appel Hémicycle se termine |
| `reponse` | `donnees` : **exactement** le JSON que renverrait `POST /chat` (`reponse`, `sources`, `actions`, `outils_utilises`, `meta`…) | Dernière ligne, en cas de succès |
| `erreur` | `statut` (code HTTP), `detail` (message lisible) | Dernière ligne, en cas d'erreur : mêmes cas et mêmes messages que `POST /chat` (400 numéro ou endpoints invalides, 404 numéro introuvable, 502 / 503 / 504 modèle en erreur, saturé ou injoignable, 500 erreur inattendue) |

Codes d'étape, dans l'ordre où ils peuvent apparaître :

| `code` | `message` |
| --- | --- |
| `rapport` | « Lecture du rapport… » (chatbot du rapport seulement, au début) |
| `analyse` | « Analyse de la question… » (premier appel au modèle) |
| `rapport_section` | « Recherche dans le rapport… » (outils `lister_sections_rapport` et `surligner_section`) |
| `recherche_auto` | « Recherche automatique dans Hémicycle… » (le modèle n'a appelé aucun outil : le serveur cherche lui-même) |
| `hemicycle` | « Recherche dans Hémicycle : <titre de l'endpoint>… » (avant chaque appel Hémicycle, ex. « Recherche dans Hémicycle : Chercher un député… ») |
| `redaction` | « Rédaction de la réponse… » (chaque appel au modèle qui suit des résultats d'outils ; peut se répéter) |
| `verification` | « Vérification des sources… » (post-traitement final, juste avant `reponse`) |

Exemple (chatbot du rapport, `{"question": "Comment a voté Frédéric Valletoux sur le scrutin n° 9895 ?", "mois": "demo"}`, raccourci) :

```
{"type": "etape", "code": "rapport", "message": "Lecture du rapport…", "t": 0.0}
{"type": "etape", "code": "analyse", "message": "Analyse de la question…", "t": 0.0}
{"type": "etape", "code": "hemicycle", "message": "Recherche dans Hémicycle : Chercher un député…", "t": 9.9, "outil": "chercher_depute", "requete": {"texte": "POST /v1/jeux/interroger", …}}
{"type": "appel", "appel": {"outil": "chercher_depute", "statut": "ok", "credits": 1, …}, "indice": 0}
{"type": "etape", "code": "redaction", "message": "Rédaction de la réponse…", "t": 10.2}
{"type": "etape", "code": "hemicycle", "message": "Recherche dans Hémicycle : Résultat détaillé d'un scrutin…", "t": 13.3, "outil": "resultat_scrutin", "requete": {"texte": "GET /v1/scrutins/VTANR5L17V9895/resultat", …}}
{"type": "appel", "appel": {"outil": "resultat_scrutin", "statut": "ok", "credits": 1, …}, "indice": 1}
{"type": "etape", "code": "redaction", "message": "Rédaction de la réponse…", "t": 13.6}
{"type": "etape", "code": "verification", "message": "Vérification des sources…", "t": 27.5}
{"type": "reponse", "donnees": {"reponse": "Frédéric Valletoux, député du groupe « Horizons & Indépendants », a voté pour sur le scrutin n° 9895 (…)", "sources": […], "actions": [], …}}
```

Côté front :

- lire le corps avec `fetch(...).then(r => r.body.getReader())` (pas `EventSource`, qui ne fait que du GET), décoder en UTF-8, découper sur `\n` en gardant le morceau incomplet pour la lecture suivante, puis `JSON.parse` chaque ligne non vide ;
- afficher le `message` de la dernière `etape` (le texte est prêt à l'emploi) ; ignorer tout `type` ou `code` inconnu ;
- traiter `reponse.donnees` exactement comme la réponse de `POST /chat` (texte, sources, `actions` de surlignage) ; sur `erreur`, afficher `detail` ;
- si le flux se termine sans `reponse` ni `erreur` (coupure réseau), afficher une erreur générique ;
- un corps invalide (question vide, champ mal typé) reçoit un **HTTP 422** JSON classique, avant tout flux : vérifier `response.ok` avant de lire le flux ;
- pour abandonner une question (nouvelle question, page fermée), interrompre la requête (`AbortController`) : le serveur annule alors la question en cours, sans consommer d'autres crédits.

### `GET /api/rapport/{mois}` — le rapport découpé en sections

Lecture seule, sans appel au modèle ni à Hémicycle ([`backend/chatbot/routes_rapport.py`](../backend/chatbot/routes_rapport.py)). `mois` vaut `AAAA-MM` ou `demo` (numéro fictif de démonstration) ; 400 si le format est invalide, 404 si le numéro n'existe pas. `GET /api/rapports` liste les numéros disponibles.

```json
{
  "mois": "demo",
  "titre": "Numéro de démonstration (exemple fictif)",
  "chapo": "…",
  "fictif": true,
  "meta": { "mois": "demo", "titre": "…", "chapo": "…", "auteurs": [], "publie_le": "", "fictif": true },
  "introduction": "Markdown entre le titre du numéro et la première section (chapô, bandeau…)",
  "sections": [
    { "id": "barometre", "titre": "Baromètre", "niveau": 2, "parent": null, "extrait": "…", "markdown": "…" },
    { "id": "cohesion-des-groupes", "titre": "Cohésion des groupes", "niveau": 3, "parent": "barometre", "extrait": "…", "markdown": "…" }
  ]
}
```

Les sections sont dans l'ordre du document ; une section de niveau 3 indique sa section de niveau 2 dans `parent`. `markdown` est le corps de la section jusqu'au titre suivant (quel que soit son niveau) : le front le convertit lui-même en HTML. Quand `fictif` vaut `true`, le front affiche un bandeau « Exemple fictif ».

### Conventions générales

- JSON, clés en `snake_case`, dates au format ISO 8601.
- Chaque donnée affichable porte un champ `source` : `{ "editeur", "url", "licence" }`.
- Les mois sont toujours notés `AAAA-MM`.

## Ports en local

| Service | Port |
| --- | --- |
| Site (front-end) | `5173` _(à ajuster selon le framework)_ |
| Chatbot | `8000` |
| Essai des outils du rapport (`backend/chatbot/essai_rapport.py`) | `8001` |
