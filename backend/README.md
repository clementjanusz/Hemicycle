# Back-end — la chaîne de production du rapport mensuel

On travaille comme une rédaction, pas comme un SaaS : le back-end ne sert pas des utilisateurs en continu, il **produit les données du rapport une fois par mois**. Le seul service en ligne est le **chatbot**, qui répond aux questions des lecteurs en s'appuyant sur le rapport publié et sur le serveur MCP d'Hémicycle.

```
backend/
├── pipeline/   # Le batch mensuel : collecte → transformation → indicateurs
├── chatbot/    # Le seul service en ligne : questions des lecteurs
└── TODO.md     # Liste des éléments à compléter
```

👉 **Ce qu'il reste à faire : [`TODO.md`](TODO.md)**

| Brique | Rôle | Quand ça tourne | Accès à Hémicycle |
| --- | --- | --- | --- |
| `pipeline/` | Collecter, nettoyer et calculer les chiffres du mois | Une fois par mois (+ relances manuelles) | API REST (`api.hemicycle.ai/v1`) |
| `chatbot/` | Répondre aux lecteurs à partir du rapport, compléter si besoin avec Hémicycle | En continu | Serveur MCP (`api.hemicycle.ai/mcp`), de façon limitée |

---

## Le pipeline mensuel

```
API Hémicycle
     │
     ▼
1. COLLECTE ─────────▶ data/raw/AAAA-MM/          réponses brutes, telles que reçues
     │
     ▼
2. TRANSFORMATION ───▶ data/processed/AAAA-MM/    données propres, normalisées, croisées
     │
     ▼
3. INDICATEURS ──────▶ data/processed/AAAA-MM/indicateurs.json
     │
     ▼
Pull request « data: rapport AAAA-MM »  →  vérification humaine  →  rédaction
```

1. **Collecte** — récupère tout ce qui concerne le mois (scrutins, amendements, textes, dossiers, acteurs…) et l'enregistre tel quel dans `data/raw/AAAA-MM/`. Si une réponse est déjà en cache, on ne rappelle pas l'API.
2. **Transformation** — nettoie et normalise (identifiants officiels, noms de groupes, dates), croise les sources. Résultat dans `data/processed/AAAA-MM/`.
3. **Indicateurs** — calcule les chiffres du **baromètre** (les mêmes chaque mois, pour pouvoir comparer) et ceux du **focus** du mois. Chaque chiffre est livré avec sa méthode de calcul et sa source.

### Principes

- **Une commande = un mois.** Relancer le pipeline sur `2026-10` doit redonner exactement les mêmes chiffres (reproductibilité).
- **Un mois publié est figé.** On ne réécrit pas les données d'un rapport sorti : en cas d'erreur, on publie un erratum.
- **Le pipeline ne publie rien.** Il propose des données ; l'équipe les vérifie (pull request), puis rédige.

### Déclenchement

| Option | Principe |
| --- | --- |
| Manuel | Une personne lance le pipeline en local en début de mois. |
| GitHub Actions (planifié) | Un workflow programmé le 1ᵉʳ du mois lance le pipeline et ouvre automatiquement une PR avec les nouvelles données. La clé Hémicycle est stockée dans les *secrets* du repo. |

### Budget d'appels

- Clé de test : **100 appels/jour**. Une collecte mensuelle complète peut dépasser ce quota → étaler la collecte sur plusieurs jours (le cache le permet), ou utiliser une clé de production.
- Privilégier les **agrégats** (`/agregats/…`) : un seul appel calcule ce qui en demanderait des centaines (par exemple les votes nominatifs scrutin par scrutin).
- Journaliser les en-têtes `X-Credits-Cost` et `RateLimit-Remaining` pour connaître le coût réel d'un mois.
- Filtrage par période : dates au format ISO 8601 ; le nom exact des paramètres est à vérifier dans la [référence de l'API](https://hemicycle.ai/docs/api) ou la [spécification OpenAPI](https://hemicycle.ai/docs/openapi).

---

## Le chatbot

Il permet aux lecteurs de creuser le rapport : « D'où vient ce chiffre ? », « Comment a voté le groupe X sur ce texte ? », « Et mon député, il a voté quoi ? ».

### Les trois briques

| Brique | Rôle |
| --- | --- |
| **Featherless** | Le LLM. API compatible OpenAI (`https://api.featherless.ai/v1`), modèles open-weight. |
| **MCP Hémicycle** | Les données parlementaires en direct, pour les questions qui dépassent le rapport. |
| **Notre rapport** | La source principale : texte publié + indicateurs du mois, injectés dans le prompt. |

### Fonctionnement

Featherless ne sait pas se connecter seul à un serveur MCP : **c'est notre serveur qui fait le pont**. Il se connecte au MCP Hémicycle, transmet la liste des outils au modèle au format *tools* d'OpenAI, et exécute les appels que le modèle demande.

```
Lecteur ── question ──▶ POST /chat
                            │
                            ▼
   ┌──────────────────────────────────────────────────┐
   │ CHATBOT (notre serveur)                          │
   │                                                  │
   │ Prompt système = consignes éditoriales           │
   │                + rapport du mois (rapport.md)    │
   │                + indicateurs.json                │
   │                                                  │
   │ Boucle :                                         │
   │  1. envoie la conversation au modèle ──────────────────▶ Featherless
   │  2. le modèle demande un outil ?                 │
   │     → appel au MCP Hémicycle ──────────────────────────▶ api.hemicycle.ai/mcp
   │     → résultat renvoyé au modèle, retour en 1    │
   │  3. sinon : réponse finale + sources             │
   └──────────────────────────────────────────────────┘
```

### Règles de sourçage

1. **Le rapport d'abord.** Si la réponse est dans le rapport ou les indicateurs, le chatbot s'appuie dessus et cite la section ou l'indicateur.
2. **Hémicycle en complément.** S'il appelle le MCP, la réponse le signale clairement : _« Donnée complémentaire issue d'Hémicycle, non vérifiée par la rédaction »_, avec le lien vers la source officielle (champ `source`).
3. **Pas de source, pas de réponse.** S'il ne trouve rien de solide, il le dit.
4. **Neutralité.** Il expose des faits et des votes, pas d'opinion politique.

### Modèle : Qwen3.8-27B

Modèle retenu : **[`Qwen/Qwen3.8-27B`](https://featherless.ai/models/Qwen/Qwen3.8-27B)**. C'est le seul des deux modèles testés qui a réussi l'aller-retour d'outils complet : `Qwen/Qwen3-32B` renvoyait des sorties de modération dès qu'on lui passait des `tools`.

| Caractéristique | Valeur sur Featherless |
| --- | --- |
| Contexte servi | **256K tokens** |
| Concurrence | 2 unités par requête |
| *Tool calling* | Natif quand la réflexion est active ; en texte (format XML de type Qwen3-Coder) quand elle est désactivée, récupéré par le serveur |
| Quantification | FP8 |

Points de vigilance (détail dans [`TODO.md`](TODO.md#6-modèle--qwen3827b)) :

- la réflexion (`<think>…</think>`) rend le modèle lent : désactivée par défaut via `chat_template_kwargs: {"enable_thinking": false}` (`/no_think` est ignoré par ce modèle) ;
- tester la qualité des réponses en français et la neutralité politique sur un jeu de questions types.

### Garde-fous

- **Outils autorisés** : n'exposer au modèle qu'une liste blanche d'outils MCP utiles et peu coûteux (voir [`docs/API_HEMICYCLE.md`](../docs/API_HEMICYCLE.md#serveur-mcp)). Exclure par exemple `predire_vote` (50 crédits) et `solde_credits`.
- **Budget par question** : nombre maximum d'appels d'outils par question (ex. 5), et plafond de crédits par jour.
- **Contexte** : tronquer ou résumer les résultats d'outils volumineux (un résultat de scrutin député par député peut faire plusieurs milliers de tokens).
- **Clé dédiée** : une clé Hémicycle propre au chatbot, distincte de celle du pipeline, pour pouvoir la révoquer seule. Une clé de test (100 appels/jour) ne suffira pas pour un chatbot public.
- **Trafic** : limite de requêtes par visiteur ; gérer les erreurs `429` de Featherless (concurrence dépassée) et d'Hémicycle (quota).

---

## Stack

_À choisir en équipe — noter la décision dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)._

| Besoin | Options |
| --- | --- |
| Langage du pipeline | Python (pandas, Polars, DuckDB) — le plus adapté à l'analyse de données |
| Stockage | Fichiers JSON / CSV / Parquet par mois ; DuckDB pour requêter tous les mois d'un coup |
| Client LLM | SDK OpenAI (Python ou TypeScript) pointé sur `https://api.featherless.ai/v1` |
| Client MCP | SDK MCP officiel (`mcp` en Python, `@modelcontextprotocol/sdk` en TypeScript), transport *streamable HTTP* |
| Serveur du chatbot | FastAPI, Hono, Express… ou fonction serverless |

## Lancer le projet

_À compléter une fois la stack choisie._

```bash
# exemples de commandes attendues
# pipeline : produire les données d'un mois
#   <commande> --mois 2026-10
# chatbot : lancer le serveur en local
#   <commande>
```

### Tester la connexion à Featherless

Prérequis : un `.env` à la racine du dépôt avec `FEATHERLESS_API_KEY`, `FEATHERLESS_BASE_URL` et `FEATHERLESS_MODEL` (voir [`.env.example`](../.env.example)).

```bash
cd backend/chatbot

# Installation (avec uv)
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
# … ou sans uv
# python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Test sur le modèle du .env, puis sur un autre modèle
.venv/bin/python smoke_test.py
.venv/bin/python smoke_test.py --model Qwen/Qwen3.8-27B

# Seulement certains tests (simple, flux, outils, no_think, kwargs)
.venv/bin/python smoke_test.py --tests simple,outils
```

Le script vérifie une réponse simple en français, le streaming, un aller-retour complet de *tool calling* avec un outil factice (`lire_scrutin`, données inventées et marquées comme telles), et la désactivation de la réflexion (`/no_think` et `chat_template_kwargs`). Il affiche pour chaque test le résultat, la latence, la présence d'un bloc `<think>` et les tokens consommés. Tous les tests coûtent 6 requêtes par modèle. La clé n'est jamais affichée ; en cas d'erreur 401 ou 403, le script s'arrête aussitôt.

Le client réutilisable est dans [`chatbot/featherless_client.py`](chatbot/featherless_client.py) : configuration lue dans le `.env`, appels normal et en streaming, nouvelles tentatives espacées sur `429` et `503` (en respectant `Retry-After`), retrait des blocs `<think>…</think>`.

### Tester la connexion au MCP Hémicycle

Prérequis : `HEMICYCLE_MCP_URL` et `HEMICYCLE_MCP_KEY` dans le `.env` racine. Même environnement que ci-dessus (`requirements.txt` inclut le SDK MCP).

```bash
cd backend/chatbot
.venv/bin/python mcp_smoke_test.py            # gratuit : connexion, outils, JSON OpenAI, appels à 0 crédit
.venv/bin/python mcp_smoke_test.py --payant   # + resultat_scrutin et rechercher : ≈ 3 crédits réels
```

Options : `--sans-json`, `--max-caracteres N`, `--scrutin ID`, `--recherche TEXTE`, `--sortie DOSSIER` (réponses complètes en JSON).

Le module réutilisable est dans [`chatbot/hemicycle_tools.py`](chatbot/hemicycle_tools.py) : connexion MCP, liste blanche, conversion au format `tools` d'OpenAI, exécution des `tool_calls` (sans jamais lever d'exception : les erreurs sont renvoyées au modèle sous une forme exploitable), troncature des gros résultats, extraction des sources, compteur d'appels et de crédits par question.

Variables facultatives : `CHATBOT_MCP_OUTILS` (liste blanche, vide = valeur par défaut du code), `CHATBOT_MCP_MAX_CARACTERES` (6000 par résultat), `CHATBOT_MCP_MAX_CARACTERES_QUESTION` (40000 cumulés par question), `CHATBOT_MAX_TOOL_CALLS` (5).

---

## Outil de rédaction (journalistes)

Petit outil web interne : un journaliste pose une question (« Quoi de neuf à l'Assemblée cette semaine ? », « Où en est le texte sur X ? ») et obtient une **réponse très brève et sourcée**, pour préparer le rapport mensuel. Serveur : [`chatbot/serveur.py`](chatbot/serveur.py) (FastAPI, lié à `127.0.0.1`). Page : [`frontend/outil-redaction/index.html`](../frontend/outil-redaction/index.html) (un seul fichier, sans dépendance).

```bash
cd backend/chatbot
uv pip install --python .venv/bin/python -r requirements.txt   # une fois (ajoute fastapi et uvicorn)
.venv/bin/python serveur.py                                     # puis ouvrir http://127.0.0.1:8000/
# Autre modèle ou réflexion activée, le temps d'un lancement :
FEATHERLESS_MODEL=Qwen/Qwen3.8-27B .venv/bin/python serveur.py --reflexion
```

- **Points d'accès** : `GET /` (la page), `POST /chat` (`{"question", "historique"}` → `{"reponse", "sources", "outils_utilises", "credits", "avertissements", "meta"}`), `POST /chat/flux` (même corps, même réponse finale, avec la progression au fil de l'eau : voir ci-dessous), `GET /etat` (modèle, outils, crédits consommés depuis le démarrage).
- **Hémicycle uniquement** : le prompt interdit les connaissances propres du modèle ; si aucun appel d'outil n'a ramené de source, le serveur remplace la réponse par « Je n'ai pas trouvé cette information dans Hémicycle. » (avec les recherches effectuées). Si le modèle répond sans appeler d'outil, il est relancé une fois. Les dates et nombres de la réponse absents des résultats d'outils sont signalés (« À vérifier »). Toutes les sources portent `"verifie_par_la_redaction": false`.
- **L'actualité** : deux outils locaux, `derniers_scrutins` (jeu `scrutins`, 17ᵉ législature, du plus récent au plus ancien, filtres date / mots-clés / solennels) et `agenda_seances` (jeu `reunions`, ordre du jour des séances de la semaine). Ils appellent `interroger` **côté serveur**, sur ces deux jeux seulement (jamais Orcet) ; `interroger` n'est jamais exposé au modèle. Outils MCP exposés en plus : `rechercher`, `lire_texte`, `lire_scrutin`, `positions_groupes`, `resultat_scrutin`, `lire_amendement`.
- **Coût mesuré (14/11/2026, `Qwen/Qwen3.8-27B`)** : 0 à 4 crédits Hémicycle par question (0 à 0,04 €), 2 à 4 requêtes Featherless, 9 à 32 s. Résultats d'outils en cache 10 minutes (même outil, mêmes arguments → 0 crédit).
- **Garde-fous** : 5 appels d'outils au plus par question (`CHATBOT_MAX_TOOL_CALLS`, jusqu'à `CHATBOT_MAX_TOOL_CALLS_PLAFOND` au choix du journaliste), 10 crédits par question (jusqu'à `CHATBOT_MAX_CREDITS_QUESTION_PLAFOND`, 200), 1 000 crédits depuis le démarrage du serveur (`CHATBOT_MAX_CREDITS_SERVEUR`, compteur en mémoire), 14 puces au plus dans la réponse, question de 1 000 caractères au plus. Le coût de chaque appel est vérifié contre le budget **avant** l'appel.
- **Liens** : page publique de l'Assemblée pour les scrutins (`/dyn/17/scrutins/<numéro>`) et les projets ou propositions de loi (`/dyn/17/textes/l17b<numéro>_projet-loi`) ; fichier open data sinon.
- **Un député précis** (« Quel est le groupe de X ? », « Que fait la députée Y ? », « Comment a voté X sur le scrutin n° N ? ») : `chercher_depute` (jeu `deputes_en_exercice`, filtre `like` sur le nom de famille, 1 crédit ; `anciens: true` → jeu `deputes`, anciens députés compris, sans le groupe) donne l'identifiant `PA…`, le groupe et la profession ; puis `lire_acteur` (fiche et mandats, 1 crédit) ou `resultat_scrutin` (vote nominatif). Les deux endpoints font partie de la sélection par défaut. `interroger` reste limité côté serveur aux jeux prévus (`JEUX_AUTORISES`, ici `deputes_en_exercice` et `deputes`). Limites de `lire_acteur` : Hémicycle renvoie les 50 mandats les plus récents, sans le nom des organes (`PO…`) ni la circonscription ; le groupe actuel vient donc de `chercher_depute`. Le compacteur `compacter_acteur` ([`hemicycle_tools.py`](chatbot/hemicycle_tools.py)) ramène la fiche de ≈ 5 800 à ≈ 1 900 caractères (identité, mandats en cours, groupes d'amitié et d'études comptés, derniers mandats terminés). Une réponse qui nomme le député cite sa fiche (source `nature: "depute"`).
- **Prévisions d'Orcet** (catégorie « Prévisions », **décochées par défaut**, hors du bouton « Tout » ; la page relève le budget quand on les coche) :
  - `previsions_orcet` lit le jeu `orcet_previsions_votes` : par défaut les votes à venir (`date_prevue` ≥ aujourd'hui, les plus proches d'abord), ou les votes passés avec le résultat constaté (`passees: true`). Filtre facultatif `texte` sur le titre ; 1 prévision par défaut, 3 au plus. Coût : **25 crédits par prévision renvoyée** (grille du 14/11/2026, contre 50 auparavant), rien sans résultat.
  - `predire_vote` porte sur un amendement : 50 crédits au plus d'après la fiche, rien si aucune prévision (`404`).
  - Le résultat porte une note `a_savoir`, et le prompt impose la lecture suivante : moyenne des probabilités individuelles des députés de voter pour, **pas** une probabilité d'adoption ; estimation datée, avec la confiance ; rangée dans « À suivre ».
  - **Constat du 14/11/2026** : aucune prévision de vote à venir. La plus récente porte sur un vote du 27/06/2026 (modèle `v1-mirt2d-tfidf-2026-06`). Aucune prévision non plus pour un amendement déposé le 12/11/2026. Sans prévision, le modèle le dit puis répond avec l'état du texte.
- **Mesuré le 14/11/2026** : « Quel est le groupe de Didier Lemaire ? » → `chercher_depute`, 1 crédit, 8 s ; « Comment a voté Didier Lemaire sur le scrutin n° 9895 ? » → `chercher_depute` + `resultat_scrutin`, 2 crédits, 23 s (« n'apparaît pas dans la liste des votants »).

### Progression en direct : `POST /chat/flux`

Une question prend 8 à 45 s. `POST /chat/flux` accepte le même corps que `POST /chat` et renvoie, au fil de l'eau, une ligne JSON par événement (`application/x-ndjson`, en-têtes `Cache-Control: no-store` et `X-Accel-Buffering: no`) ; `POST /chat` ne change pas.

```bash
curl -N -X POST http://127.0.0.1:8000/chat/flux -H 'Content-Type: application/json' \
  -d '{"question": "Quel est le groupe de Didier Lemaire ?"}'
```

```
{"type": "etape", "code": "analyse", "message": "Analyse de la question…", "t": 0.0}
{"type": "etape", "code": "hemicycle", "message": "Recherche dans Hémicycle : Chercher un député…", "t": 5.2, "outil": "chercher_depute", "requete": {"methode": "POST", "chemin": "/v1/jeux/interroger", "texte": "POST /v1/jeux/interroger", "court": "POST /v1/jeux/interroger · deputes_en_exercice", …}}
{"type": "appel", "appel": {"outil": "chercher_depute", "titre": "Chercher un député", "statut": "ok", "credits": 1, …}, "indice": 0}
{"type": "etape", "code": "redaction", "message": "Rédaction de la réponse…", "t": 5.5}
{"type": "etape", "code": "verification", "message": "Vérification des sources…", "t": 8.2}
{"type": "reponse", "donnees": {"reponse": "- Didier Lemaire appartient au groupe « Horizons & Indépendants » (HOR) (fiche du député).", "sources": […], "outils_utilises": […], …}}
```

- **Étapes** (`code` → `message`) : `rapport` (« Lecture du rapport… », mode lecteur, au début), `analyse` (premier appel au modèle), `hemicycle` (« Recherche dans Hémicycle : <titre de l'endpoint>… », avant chaque appel d'endpoint, avec `outil` et `requete`, la requête REST équivalente, ou `null` si les arguments sont invalides), `rapport_section` (outils du rapport, mode lecteur), `recherche_auto` (le serveur lance lui-même la recherche), `redaction` (appels au modèle après des résultats d'outils), `verification` (post-traitement final). `t` : secondes depuis le début de la question (une décimale).
- **`appel`** : un appel Hémicycle terminé ; `appel` est l'entrée de `outils_utilises` de la réponse finale (même contenu), `indice` sa position dans cette liste.
- **Fin du flux** : `{"type": "reponse", "donnees": <exactement le JSON de POST /chat>}` ou `{"type": "erreur", "statut": <code HTTP>, "detail": "…"}` (mêmes cas et messages que `POST /chat` : 400, 404, 502, 503, 504 ; 500 pour une erreur inattendue). Un corps invalide reçoit un 422 JSON classique, avant tout flux.
- **Déconnexion** : si le client ferme la connexion, la question est annulée (plus d'appel au modèle ni à Hémicycle). Vérifié : coupure à 3 s → aucun crédit, aucune autre requête Featherless.
- Implémentation : paramètre `signaler` de `repondre()` ; la route lance `repondre` dans une tâche, pousse les événements dans une `asyncio.Queue` et renvoie une `StreamingResponse`. Contrat détaillé, pour le front, dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#post-chatflux--la-même-réponse-avec-la-progression).

Variables facultatives : `CHATBOT_REFLEXION` (0 par défaut ; 1 = réflexion de Qwen 3 activée, plus lent), `CHATBOT_MAX_CREDITS_QUESTION` (10), `CHATBOT_MAX_CREDITS_SERVEUR` (300), `CHATBOT_CACHE_S` (600), `CHATBOT_MAX_TOKENS` (1800, sans réflexion ; réponses détaillées : phrase de synthèse + 12 puces au plus), `CHATBOT_CONCURRENCE_LLM` (1), `CHATBOT_TRACE` (chemin d'un fichier JSONL : question, résultats d'outils vus par le modèle, réponse ; pour vérifier une réponse). Pour comparer, `POST /chat` accepte aussi `"reflexion": true|false`.

Limites connues (détail dans [`TODO.md`](TODO.md#7-outil-de-rédaction-journalistes)) : réponses souvent plus longues que la cible de 80 mots ; avec la réflexion désactivée, `Qwen3.8-27B` écrit ses appels d'outils dans le texte (le serveur les récupère) et oublie parfois d'appeler un outil.

## Chatbot du rapport (mode lecteur)

Le même serveur sert aussi le chatbot intégré au rapport publié. Il suffit d'envoyer le numéro du rapport dans la requête :

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question": "Quel groupe est le plus divisé ce mois-ci ?", "mois": "demo"}'
```

| | Outil de rédaction (sans `mois`) | Chatbot du rapport (avec `mois`) |
| --- | --- | --- |
| Public | Journalistes de l'équipe | Lecteurs du rapport |
| Sources | Hémicycle uniquement (outils MCP) | Le rapport du mois, puis Hémicycle en complément |
| Outils | Outils Hémicycle | Outils Hémicycle + `lister_sections_rapport` + `surligner_section` |
| Réponse | `reponse`, `sources`, `outils_utilises` | idem + `actions` (sections du rapport à mettre en évidence) |

- **`surligner_section`** indique quelle partie du rapport répond à la question : la réponse de `/chat` contient alors `"actions": [{"type": "surligner_section", "section_id": "cohesion-des-groupes", "titre": "…", "raison": "…"}]`. Ce que la page devra en faire est décrit dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) (à implémenter côté front).
- Le rapport est lu dans `rapports/<mois>/rapport.md` ; `GET /api/rapport/<mois>` renvoie ses sections en JSON et `GET /api/rapports` la liste des numéros. `rapports/demo/` est un numéro de démonstration au contenu fictif.
- Les outils du rapport sont gratuits ; une question traitée par le rapport seul ne coûte aucun crédit Hémicycle.
- **Questions sur un député** : le prompt lecteur donne la méthode `chercher_depute` → identifiant `PA…` → `lire_acteur` (mandats et fonctions) ou `resultat_scrutin` (vote nominatif) ; ces endpoints font partie des outils du chatbot du rapport.
- **Progression** : `POST /chat/flux` fonctionne aussi avec `mois` (mêmes événements, plus `rapport` au début et `rapport_section` pour `lister_sections_rapport` et `surligner_section`) ; voir « Progression en direct » ci-dessus. Les `actions` arrivent dans l'événement final `reponse`.
- Testé le 14/11/2026 sur `demo` : « Quel groupe est le plus divisé ? » → `surligner_section(cohesion-des-groupes)`, réponse citant la section, 0 crédit, 13 s ; « Où en sont les textes sur les incendies de forêt ? » (hors rapport) → aucun surlignage, outils Hémicycle (`derniers_scrutins`, `rechercher`, `lire_texte` ×3), 6 crédits, 22 s ; « Que fait le député Didier Lemaire ? » (flux) → `chercher_depute` puis `lire_acteur`, mandats en cours cités « (fiche du député, non vérifiée par la rédaction) », 1 crédit (recherche en cache), 34 s ; « Comment a voté Frédéric Valletoux sur le scrutin n° 9895 ? » → `chercher_depute` + `resultat_scrutin`, « a voté pour », 2 crédits, 28 s.
