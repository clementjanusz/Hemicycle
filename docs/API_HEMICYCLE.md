# Mémo — API Hémicycle

Résumé de la [documentation officielle](https://hemicycle.ai/docs) pour l'équipe. En cas de doute, la doc officielle fait foi.

## Ce que contient Hémicycle

Base de données publique qui relie textes, amendements, scrutins et élus, synchronisée chaque nuit à partir de :

- **Assemblée nationale** : textes, amendements, scrutins et votes, députés, organes (scrutins depuis 2012, amendements de la 17ᵉ législature)
- **Sénat** : textes, amendements, scrutins, sénateurs (depuis octobre 2023)
- **Dossiers législatifs** : parcours des lois depuis 1986
- **Journal officiel**, **HATVP** (représentants d'intérêts), **Conseil constitutionnel**, **data.gouv.fr**
- **Débats** (comptes rendus, vidéos) et **presse** (articles de 620 médias)

## Authentification

1. Créer un compte et une clé sur [hemicycle.ai/compte-api](https://hemicycle.ai/compte-api) — la clé ne s'affiche qu'une seule fois.
2. Deux types de clés :

| Clé | Préfixe | Coût | Quota | Données |
| --- | --- | --- | --- | --- |
| Test | `hmc_test_` | Gratuite | 100 appels/jour | Données réelles ; réponses des modèles (Orcet, Marianne…) fictives, marquées `"exemple": true` |
| Production | `hmc_live_` | Crédits (≥ 1 par appel) | Limites standard | Tout est réel |

3. Chaque requête porte deux en-têtes :

```bash
curl "https://api.hemicycle.ai/v1/scrutins?legislature=17&limit=5" \
  -H "Authorization: Bearer $HEMICYCLE_API_KEY" \
  -H "Hemicycle-Version: 2026-10-01"
```

- **Base URL** : `https://api.hemicycle.ai/v1`
- **Version** : en-tête `Hemicycle-Version` (on fixe `2026-10-01` pour tout le hackathon)

## Endpoints

Coût en crédits entre parenthèses (gratuit avec une clé de test).

**Données parlementaires**

| Endpoint | Description |
| --- | --- |
| `GET /textes` · `GET /textes/{id}` | Textes (1) |
| `GET /dossiers` · `GET /dossiers/{id}` | Dossiers législatifs (1) |
| `GET /amendements` · `GET /amendements/{id}` | Amendements (1) |
| `GET /scrutins` · `GET /scrutins/{id}` | Scrutins (1) |
| `GET /scrutins/{id}/votes` | Votes nominatifs d'un scrutin (1) |
| `GET /scrutins/{id}/resultat` | Résultat par groupe politique (1) |
| `GET /acteurs` · `GET /acteurs/{id}` | Députés, sénateurs et autres acteurs (1) |
| `GET /organes` | Groupes, commissions… (1) |
| `GET /recherche` | Recherche plein texte (2) |

**Agrégats prêts à l'emploi** — utiles pour un angle journalistique

| Endpoint | Description |
| --- | --- |
| `POST /agregats/positions-groupes` | Positions des groupes sur des scrutins (1) |
| `POST /agregats/accord-groupes` | Taux d'accord entre groupes (5) |
| `POST /agregats/loyaute-deputes` | Loyauté des députés envers leur groupe (5) |
| `POST /agregats/classement-auteurs` | Classement des auteurs d'amendements (5) |

**Autres sources**

| Endpoint | Description |
| --- | --- |
| `GET /jeux` | Lister les jeux de données (gratuit) |
| `POST /jeux/interroger` | Interroger un jeu de données (1) |
| `GET /entreprises` | Chercher une entreprise (2) |
| `GET /donnees-publiques` | Chercher sur data.gouv.fr (2) |
| `POST /donnees-publiques/lecture` | Lire un fichier data.gouv.fr (2) |

**Modèles IA** (chers — réponses fictives en clé de test)

| Endpoint | Description |
| --- | --- |
| `POST /orcet/predictions` | Prédire le vote d'un député (50) |
| `POST /marianne/reponses` | Poser une question à Marianne (50, Labs) |

**Compte**

| Endpoint | Description |
| --- | --- |
| `GET /credits` | Consulter le solde (gratuit) |

Détail des paramètres de chaque endpoint : [hemicycle.ai/docs/api](https://hemicycle.ai/docs/api) · Spécification OpenAPI : [hemicycle.ai/docs/openapi](https://hemicycle.ai/docs/openapi)

## Pagination

Les listes sont paginées par curseur :

- `limit` : 1 à 100 éléments par page (20 par défaut)
- Réponse : `{ "data": [...], "has_more": true, "next_cursor": "YW06MTIzNA" }`
- Page suivante : rappeler le même endpoint avec `cursor=<next_cursor>`, tant que `has_more` vaut `true`
- **Chaque page compte comme un appel** → avec une clé de test, bien choisir ses filtres avant de tout paginer.

## Erreurs

Format `application/problem+json` : `type`, `title`, `status`, `detail`, `request_id`.

| Code | Signification | Que faire |
| --- | --- | --- |
| 400 | Paramètre invalide | Corriger la requête (voir le champ `errors`) |
| 401 | Clé invalide | Vérifier l'en-tête `Authorization` |
| 402 | Crédits insuffisants | Recharger le compte |
| 403 | Droits insuffisants | Utiliser une clé avec les bons droits |
| 404 | Introuvable | Vérifier l'identifiant |
| 429 | Trop de requêtes | Attendre `Retry-After`, puis réessayer (1 s, 2 s, 4 s…) |
| 500 / 503 | Erreur / indisponibilité Hémicycle | Réessayer plus tard (non facturé) |
| 501 | Endpoint pas encore ouvert | En utiliser un autre |

Seuls 429, 500 et 503 justifient une nouvelle tentative.

## Limites de débit

- Lectures et recherches : 300 requêtes/minute
- Modèles : 30 requêtes/minute
- Clés de test : 100 requêtes/jour
- Limites appliquées par organisation (toutes clés confondues)
- En-têtes utiles : `RateLimit-Remaining`, `RateLimit-Reset`, `X-Credits-Cost`, `X-Credits-Remaining`

## Sources et citation

- Chaque réponse contient un objet `source` : éditeur, URL de la pièce officielle, licence (ex. Licence Ouverte 2.0).
- Données publiques brutes : citer l'éditeur d'origine (Assemblée nationale, Sénat…) en reprenant l'objet `source`.
- Données calculées par Hémicycle (agrégats, prédictions) : citer « Source : Hémicycle ».

## Serveur MCP

Utilisé par **le chatbot** (et pratique pour explorer les données à la main).

- **URL** : `https://api.hemicycle.ai/mcp`
- **Transport** : *streamable HTTP*
- **Authentification** : en-tête `Authorization: Bearer <clé>` — utiliser une clé dédiée au chatbot
- **Coût** : le MCP consomme les crédits et le quota de la clé utilisée
- Doc : [hemicycle.ai/docs/mcp](https://hemicycle.ai/docs/mcp) · [outils disponibles](https://hemicycle.ai/docs/mcp/outils)

### Outils disponibles (18, tous en lecture seule)

Liste et paramètres vérifiés sur le serveur le 14/11/2026 (`tools/list`, serveur `hemicycle` version `2026-10-01`). La colonne « Chatbot » est une **proposition** de liste blanche, à valider en équipe. Le code du chatbot l'applique dans [`backend/chatbot/hemicycle_tools.py`](../backend/chatbot/hemicycle_tools.py).

| Outil | Description | Paramètres principaux | Crédits | Chatbot |
| --- | --- | --- | --- | --- |
| `rechercher` | Recherche plein texte dans les textes, dossiers et amendements de l'**Assemblée nationale** (ni scrutins, ni acteurs) | `q` (requis), `types` (`texte,dossier,amendement`), `limit` (1 à 100) | 2 | ✅ |
| `lire_texte` | Un texte (projet ou proposition de loi, rapport) et son dossier | `id` (requis) | 1 | ✅ |
| `lire_amendement` | Un amendement : dispositif, exposé, auteurs et sort | `id` (requis) | 1 | ✅ |
| `lire_scrutin` | Un scrutin : objet, date, résultat et décompte | `id` (requis) | 1 | ✅ |
| `resultat_scrutin` | Décompte, position de chaque groupe et vote nominatif de chaque député (AN) | `id` (requis) | 1 | ✅ |
| `lire_acteur` | Fiche d'un parlementaire et ses mandats | `id` (requis, `PA…`) | 1 | ✅ |
| `positions_groupes` | Positions des groupes sur 1 à 100 scrutins (AN), sans les votes individuels | `scrutins` (liste d'identifiants, requis) | 1 | ✅ |
| `guide` | Fiches de savoir-faire en Markdown ; sans argument, l'arborescence | `sujet` (27 valeurs) | 0 | ✅ |
| `lister_jeux` | Jeux de données : source, licence, colonnes, filtres obligatoires, prix | — | 0 | ⚠️ |
| `interroger` | Page d'un jeu de données (132 jeux : Parlement, budget, emploi, collectivités, Orcet…) | `jeu` (requis), `filtres`, `recherche`, `colonnes`, `tri`, `ordre`, `limite` (≤ 200), `decalage` | 1 par page ; 5 sur un jeu dérivé ; **50 par prédiction Orcet renvoyée** | ⚠️ |
| `classement_auteurs` | Classement des députés premiers signataires d'amendements | `texte`, `recherche`, `depuis`, `jusqu_a`, `legislature`, `limite`, `exclure_rapporteurs` (un texte, une recherche ou une période d'un an au plus) | 5 | ⚠️ |
| `accord_groupes` | Pour **chaque paire** de groupes, part des scrutins où leurs positions majoritaires coïncident | `depuis`, `jusqu_a` ou `legislature` (obligatoire), `intitule`, `types` | 5 | ⚠️ |
| `loyaute_deputes` | Part des votes de chaque député conformes à la position majoritaire de son groupe | `depuis`, `jusqu_a` ou `legislature` (obligatoire), `intitule`, `groupe`, `min_votes`, `limite` | 5 | ⚠️ |
| `chercher_entreprise` | Entreprise par nom, SIREN ou dirigeant | `q` (requis), `page` | 2 | ❌ |
| `chercher_donnees_publiques` | Jeux certifiés de data.gouv.fr (note ≥ 70/100) | `q` (requis) | 2 | ❌ |
| `lire_donnees_publiques` | 50 lignes au plus d'un fichier data.gouv.fr | `fichier` (requis), `filtres`, `tri`, `ordre`, `lignes` | 2 | ❌ |
| `predire_vote` | Prédiction d'Orcet sur un amendement | `amendement` (requis) | 50 (0 si aucune prédiction) | ❌ |
| `solde_credits` | Solde de crédits du compte | — | 0 | ❌ |

✅ autorisé · ⚠️ à discuter (coût ou résultats volumineux) · ❌ exclu

### Ce qu'a montré le test de connexion (14/11/2026)

Script : `backend/chatbot/mcp_smoke_test.py`.

- **Protocole** : MCP `2025-11-25`, serveur **sans état** (pas d'en-tête `Mcp-Session-Id`). L'en-tête `Hemicycle-Version` n'est pas nécessaire.
- **Coût réel de chaque appel** : il figure dans le champ `_meta` du résultat d'outil (`credits_cost`, `credits_remaining`, `tarif_version`), et non dans les en-têtes HTTP `X-Credits-*`. 1 crédit = 0,01 € (`solde_credits` renvoie `valeur_eur`).
- **Format des réponses** : un bloc texte (JSON compact, ou Markdown pour une fiche `guide`) et `structuredContent` (même contenu). Aucun outil ne déclare d'`outputSchema`.
- **Champ `source`** `{editeur, url, licence}` : à la racine de `resultat_scrutin`, et dans chaque résultat de `rechercher`. Pour les textes, l'URL pointe vers le fichier JSON open data de l'Assemblée (`…/dyn/opendata/<id>.json`), pas vers une page lisible par un lecteur.
- **Tailles mesurées** :
  - `resultat_scrutin` : ≈ 86 caractères par votant, soit 15 133 caractères pour 149 votants et ≈ 50 000 caractères (≈ 12 500 tokens) pour un scrutin à 577 votants ;
  - `rechercher` : ≈ 575 caractères par résultat ;
  - `guide` sans argument : 4 239 caractères.
- **Définitions d'outils au format OpenAI** : les 8 outils ✅ font ≈ 4 330 caractères (≈ 1 100 tokens), les 18 outils ≈ 17 300 caractères (≈ 4 300 tokens), dont ≈ 5 100 pour `interroger` seul.
- **Erreurs** (non facturées) :
  - clé invalide : HTTP 401 avec une erreur JSON-RPC `-32001` (« Clé d'accès absente ou invalide. ») ;
  - paramètre invalide : erreur JSON-RPC `-32602`, dont le message liste les valeurs valides.
- **Identifiants** (fiche `guide` « identifiants ») : texte `PIONANR5L17B0390`, dossier `DLR5L17N51234`, amendement `AMANR5L17PO59048B0390P0D1N000012`, scrutin `VTANR5L17V1234`, acteur `PA841605`, organe `PO59048`.
- **Instructions du serveur** : elles demandent d'appeler `guide` en premier et orientent vers `lister_jeux` puis `interroger`. Ne pas les transmettre telles quelles au modèle du chatbot.

### Explorer à la main

Le même serveur peut être ajouté comme connecteur dans Claude, ChatGPT, Le Chat ou Cursor pour explorer les données en langage naturel, par exemple pour chercher l'angle du focus du mois.
