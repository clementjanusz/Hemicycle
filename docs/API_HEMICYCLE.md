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

La colonne « Chatbot » est une **proposition** de liste blanche, à valider en équipe.

| Outil | Description | Crédits | Chatbot |
| --- | --- | --- | --- |
| `rechercher` | Recherche plein texte (textes, dossiers, amendements) | 2 | ✅ |
| `lire_texte` | Un texte et son dossier législatif | 1 | ✅ |
| `lire_amendement` | Un amendement et son sort | 1 | ✅ |
| `lire_scrutin` | Un scrutin et son décompte | 1 | ✅ |
| `resultat_scrutin` | Résultat par groupe et par député | 1 | ✅ |
| `lire_acteur` | Fiche d'un parlementaire | 1 | ✅ |
| `positions_groupes` | Position de chaque groupe sur jusqu'à 100 scrutins | 1 | ✅ |
| `guide` | Fiches de savoir-faire | 0 | ✅ |
| `lister_jeux` | Liste des jeux de données | 0 | ⚠️ |
| `interroger` | Page d'un jeu de données (filtres, tri, pagination) | 1 à 5 par page | ⚠️ |
| `classement_auteurs` | Classement des auteurs d'amendements | 5 | ⚠️ |
| `accord_groupes` | Accord entre deux groupes | 5 | ⚠️ |
| `loyaute_deputes` | Loyauté des députés envers leur groupe | 5 | ⚠️ |
| `chercher_entreprise` | Recherche d'entreprise (nom, SIREN, dirigeant) | 2 | ❌ |
| `chercher_donnees_publiques` | Recherche sur data.gouv.fr | 2 | ❌ |
| `lire_donnees_publiques` | Lecture de 50 lignes d'un fichier data.gouv.fr | 2 | ❌ |
| `predire_vote` | Prédiction d'Orcet sur un amendement | 50 | ❌ |
| `solde_credits` | Solde de crédits du compte | 0 | ❌ |

✅ autorisé · ⚠️ à discuter (coût ou résultats volumineux) · ❌ exclu

### Explorer à la main

Le même serveur peut être ajouté comme connecteur dans Claude, ChatGPT, Le Chat ou Cursor pour explorer les données en langage naturel, par exemple pour chercher l'angle du focus du mois.
