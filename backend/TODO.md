# Back-end — éléments à compléter

Liste de travail du pôle back-end. Cocher au fur et à mesure, et ouvrir une issue GitHub (label `backend`) pour chaque bloc pris en charge.

Contexte : [`backend/README.md`](README.md) · [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) · [`docs/API_HEMICYCLE.md`](../docs/API_HEMICYCLE.md)

---

## 1. Données : quoi utiliser, et est-ce pertinent à extraire ?

- [ ] **Explorer les données disponibles** : via le MCP Hémicycle dans Claude ou Cursor, ou avec `GET /jeux` (gratuit).
- [ ] **Inventorier chaque type de données** et noter sa couverture réelle :

  | Données | Couverture connue | Utile pour le rapport ? | Coût mensuel estimé |
  | --- | --- | --- | --- |
  | Scrutins + votes (AN) | Depuis 2012 | _…_ | _…_ |
  | Scrutins (Sénat) | Depuis octobre 2023 | _…_ | _…_ |
  | Amendements | 17ᵉ législature uniquement | _…_ | _…_ |
  | Textes et dossiers législatifs | Dossiers depuis 1986 | _…_ | _…_ |
  | Acteurs et organes (référentiel) | — | _…_ | _…_ |
  | Agrégats (loyauté, accord, positions, auteurs) | — | _…_ | _…_ |
  | Débats, presse, HATVP, Journal officiel | — | _…_ | _…_ |

- [ ] **Définir avec la rédaction les indicateurs du baromètre** (voir [`docs/EDITORIAL.md`](../docs/EDITORIAL.md)) : pour chacun, une définition précise et stable d'un mois à l'autre.
- [ ] **Évaluer la pertinence de chaque extraction** : est-ce que la donnée raconte quelque chose ? Est-elle assez fiable et complète sur un mois ? Combien d'appels et de crédits coûte-t-elle ?
- [ ] **Trancher ce qui va où** :
  - dans le **pipeline**, ce qui est publié et vérifié (baromètre, focus) ;
  - dans le **chatbot via le MCP**, le détail consulté à la demande (un député, un amendement précis).
- [ ] **Remplir l'inventaire** dans [`data/README.md`](../data/README.md).

## 2. Connexion à l'API Hémicycle

- [ ] **Choisir le langage et la stack** du pipeline, puis noter la décision dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
- [ ] **Test de connexion** avec `GET /credits` (gratuit) : vérifier que la clé du `.env` fonctionne.
- [ ] **Client HTTP commun** :
  - [ ] base URL, en-têtes `Authorization: Bearer` et `Hemicycle-Version: 2026-10-01` ;
  - [ ] clés lues depuis `.env` (`HEMICYCLE_API_KEY`), jamais en dur ;
  - [ ] pagination par curseur (`limit` ≤ 100, `cursor` / `has_more`) ;
  - [ ] nouvelles tentatives uniquement sur `429`, `500` et `503`, en respectant `Retry-After` (1 s, 2 s, 4 s…) ;
  - [ ] erreurs `400`, `401`, `402`, `403` et `404` remontées clairement, sans nouvelle tentative.
- [ ] **Cache disque** dans `data/raw/AAAA-MM/` : ne jamais rappeler l'API pour une réponse déjà reçue.
- [ ] **Suivi des coûts** : journaliser `X-Credits-Cost`, `X-Credits-Remaining` et `RateLimit-Remaining`.

## 3. Endpoints à utiliser

- [ ] **Récupérer la spécification OpenAPI** ([hemicycle.ai/docs/openapi](https://hemicycle.ai/docs/openapi)) et identifier les paramètres de filtrage par date. C'est indispensable pour un rapport mensuel.
- [ ] **Associer chaque indicateur à son endpoint**, avec les paramètres exacts. Candidats de départ :

  | Besoin | Endpoint |
  | --- | --- |
  | Scrutins du mois | `GET /scrutins` |
  | Résultat par groupe d'un scrutin | `GET /scrutins/{id}/resultat` |
  | Cohésion des groupes | `POST /agregats/loyaute-deputes` |
  | Alliances entre groupes | `POST /agregats/accord-groupes`, `POST /agregats/positions-groupes` |
  | Activité d'amendement | `GET /amendements`, `POST /agregats/classement-auteurs` |
  | Parcours des textes | `GET /dossiers`, `GET /textes` |
  | Référentiel députés et groupes | `GET /acteurs`, `GET /organes` |

- [ ] **Tester chaque endpoint sur un mois réel** et noter le volume renvoyé et le nombre d'appels nécessaires.
- [ ] **Écrire la commande du pipeline** `--mois AAAA-MM` : collecte → `data/raw/` → transformation → `data/processed/` → `indicateurs.json` au format du contrat.

## 4. Chatbot avec l'API Featherless

- [ ] **Serveur** exposant `POST /chat`, conforme au contrat de [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
- [x] **Client LLM** : SDK OpenAI pointé sur `https://api.featherless.ai/v1`, clé `FEATHERLESS_API_KEY` → [`chatbot/featherless_client.py`](chatbot/featherless_client.py), connexion vérifiée avec `chatbot/smoke_test.py`.
- [ ] **Prompt système** rédigé à partir des règles éditoriales du chatbot ([`docs/EDITORIAL.md`](../docs/EDITORIAL.md)).
- [ ] **Réponse en streaming** vers le site.
  - [x] Streaming depuis Featherless vérifié (`smoke_test.py`) ; reste à le relayer au site.
- [ ] **Robustesse** :
  - [ ] gérer les `429` de Featherless (concurrence dépassée), avec un message clair au lecteur. Nouvelles tentatives espacées (`Retry-After` respecté) déjà dans `featherless_client.py`, testées sur des réponses simulées seulement (aucun vrai `429` rencontré) ; message au lecteur à faire ;
  - [ ] limiter le nombre de requêtes par visiteur et la longueur des questions ;
  - [ ] configurer CORS pour le domaine du site.
- [ ] **Choisir l'hébergement** du chatbot.

## 5. Brancher le rapport et le MCP Hémicycle au chatbot

### Le rapport comme source

- [ ] Charger `rapports/AAAA-MM/rapport.md` et `data/processed/AAAA-MM/indicateurs.json` dans le prompt système.
- [ ] **Respecter le budget de contexte de 32K tokens** (prompt, rapport, définitions d'outils, résultats d'outils et réponse cumulés) : mesurer la taille du rapport en tokens, et prévoir une version condensée si besoin.
- [ ] Faire citer au modèle la **section du rapport** ou l'**identifiant de l'indicateur** utilisé.

### Le MCP Hémicycle comme complément

- [x] **Client MCP** (SDK officiel `mcp` 2.3) en *streamable HTTP* sur `HEMICYCLE_MCP_URL`, avec l'en-tête `Authorization: Bearer $HEMICYCLE_MCP_KEY` — `chatbot/hemicycle_tools.py`.
- [x] Récupérer la liste des outils, **filtrer selon la liste blanche** ([`docs/API_HEMICYCLE.md`](../docs/API_HEMICYCLE.md#serveur-mcp)) et la convertir au format `tools` d'OpenAI (8 outils ≈ 1 100 tokens).
- [x] **Exécuter un `tool_call`** et renvoyer un message `role: tool`, avec erreurs exploitables par le modèle (outil non autorisé, JSON invalide, limite atteinte…).
- [x] **Tronquer** les résultats d'outils volumineux (6 000 caractères par résultat, 40 000 par question ; compacteur dédié pour `resultat_scrutin`).
- [ ] **Boucle d'outils de bout en bout** avec Featherless : le modèle renvoie des `tool_calls`, on appelle le MCP, on renvoie le résultat, et on recommence. Maximum `CHATBOT_MAX_TOOL_CALLS` appels par question.
  - Attention : le SDK MCP est **asynchrone** et `featherless_client.py` est **synchrone** → passer à `AsyncOpenAI` (ou faire un pont), et ouvrir la session MCP dans le *lifespan* du serveur.
- [ ] Marquer les sources issues du MCP `"verifie_par_la_redaction": false` dans la réponse de `/chat` (les sources sont déjà extraites par le module).
- [ ] **Ne pas transmettre au modèle les instructions du serveur MCP** (elles orientent vers `guide` et `interroger`).
- [ ] **Mettre dans le prompt système** les formats d'identifiants (`VTANR5L17V…` scrutins, `PA…` députés, `PIONANR5L17B…` textes) et la consigne de limiter `positions_groupes` à une dizaine de scrutins par appel.
- [ ] **Décider de la liste blanche** (recommandations du test) :
  - retirer `guide` (définition la plus lourde, inutile pour les lecteurs) ;
  - `lire_acteur` exige un identifiant `PA…` qu'aucun outil autorisé ne fournit → garder les `PA` dans le compacteur de `resultat_scrutin`, ou autoriser `interroger` limité aux jeux `deputes` / `deputes_en_exercice` ;
  - garder `interroger` exclu sinon (jusqu'à 50 crédits par prédiction Orcet renvoyée).
- [ ] Les URL de source renvoyées par `rechercher` pointent vers des fichiers JSON open data : construire des liens lisibles pour les lecteurs.
- [ ] **Clé dédiée au chatbot** (`hmc_live_`) avec un plafond de crédits par jour. Pour l'instant, la même clé est utilisée pour le pipeline et le chatbot.

## 6. Modèle : Qwen3-32B

- [x] Disponibilité vérifiée sur Featherless : **`Qwen/Qwen3-32B`** (32K de contexte servis, 2 unités de concurrence, FP8, *tool calling* natif documenté par Featherless).
- [x] `FEATHERLESS_MODEL` mis à jour dans `.env.example`.
- [ ] **Premier test de *tool calling*** avec un ou deux outils MCP (ex. `rechercher`, `lire_scrutin`) avant de brancher toute la liste blanche.
  - [x] Aller-retour complet avec un outil factice `lire_scrutin` (`smoke_test.py`, 14/11/2026) : format OpenAI natif (`tool_calls`, `arguments` en chaîne JSON) et bons arguments sur les deux modèles.
  - [ ] **Anomalie `Qwen/Qwen3-32B` avec `tools`** : 2 requêtes sur 3 ont renvoyé `Safety: Safe / Categories: None…` (format d'un classifieur de modération, type Qwen3Guard) au lieu d'une réponse, alors que le champ `model` annonce bien `Qwen/Qwen3-32B` ; même requête comptée 310 puis 421 tokens d'entrée. Non observé sans `tools` ni sur `Qwen/Qwen3.8-27B`. À signaler au support Featherless.
- [ ] **Gérer le raisonnement** : Qwen 3 peut produire un bloc de réflexion (`<think>…</think>`). Soit le filtrer avant d'afficher la réponse, soit le désactiver. Attention, ce bloc consomme aussi du contexte.
  - [x] Filtrage en mode normal : vérifié sur les deux modèles (`featherless_client.separer_reflexion`).
  - [ ] Filtrage en streaming : Qwen3.8-27B n'émet que `</think>` (balise ouvrante dans le gabarit) ; correction vérifiée hors ligne sur ce motif, à revérifier en réel (`smoke_test.py --model Qwen/Qwen3.8-27B --tests flux`).
  - [x] Désactivation : `chat_template_kwargs: {"enable_thinking": false}` (paramètre documenté par Featherless) fonctionne sur les deux modèles. `/no_think` fonctionne sur Qwen3-32B (bloc vide) mais est ignoré par Qwen3.8-27B.
- [ ] **Construire un jeu d'évaluation** d'une vingtaine de questions types (factuelles, comparaisons d'un mois à l'autre, « mon député », hors sujet, questions orientées), avec les réponses attendues.
  - Vérifier que les réponses s'appuient bien sur le rapport et citent leurs sources.
  - Vérifier la qualité du français et la **neutralité politique**.

---

## Plus tard

- [ ] Déclenchement automatique du pipeline le 1ᵉʳ du mois (GitHub Actions, clé en *secret* du repo).
- [ ] Requêtes sur l'ensemble des mois (DuckDB) pour les comparaisons dans le temps.
