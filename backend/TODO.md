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
- [ ] **Client LLM** : SDK OpenAI pointé sur `https://api.featherless.ai/v1`, clé `FEATHERLESS_API_KEY`.
- [ ] **Prompt système** rédigé à partir des règles éditoriales du chatbot ([`docs/EDITORIAL.md`](../docs/EDITORIAL.md)).
- [ ] **Réponse en streaming** vers le site.
- [ ] **Robustesse** :
  - [ ] gérer les `429` de Featherless (concurrence dépassée), avec un message clair au lecteur ;
  - [ ] limiter le nombre de requêtes par visiteur et la longueur des questions ;
  - [ ] configurer CORS pour le domaine du site.
- [ ] **Choisir l'hébergement** du chatbot.

## 5. Brancher le rapport et le MCP Hémicycle au chatbot

### Le rapport comme source

- [ ] Charger `rapports/AAAA-MM/rapport.md` et `data/processed/AAAA-MM/indicateurs.json` dans le prompt système.
- [ ] **Respecter le budget de contexte de 32K tokens** (prompt, rapport, définitions d'outils, résultats d'outils et réponse cumulés) : mesurer la taille du rapport en tokens, et prévoir une version condensée si besoin.
- [ ] Faire citer au modèle la **section du rapport** ou l'**identifiant de l'indicateur** utilisé.

### Le MCP Hémicycle comme complément

- [ ] **Client MCP** (SDK officiel) en *streamable HTTP* sur `HEMICYCLE_MCP_URL`, avec l'en-tête `Authorization: Bearer $HEMICYCLE_MCP_KEY`.
- [ ] Récupérer la liste des outils, **filtrer selon la liste blanche** ([`docs/API_HEMICYCLE.md`](../docs/API_HEMICYCLE.md#serveur-mcp)) et la convertir au format `tools` d'OpenAI.
- [ ] **Boucle d'outils** : le modèle renvoie des `tool_calls`, on appelle le MCP, on renvoie un message `role: tool`, et on recommence. Maximum `CHATBOT_MAX_TOOL_CALLS` appels par question.
- [ ] **Tronquer ou résumer** les résultats d'outils volumineux pour tenir dans le contexte.
- [ ] Marquer les sources issues du MCP `"verifie_par_la_redaction": false`.
- [ ] **Clé dédiée au chatbot** (`hmc_live_`) avec un plafond de crédits par jour. Pour l'instant, la même clé est utilisée pour le pipeline et le chatbot.

## 6. Modèle : Arete 27B

- [x] Disponibilité vérifiée sur Featherless : **`NousResearch/Arete-27B`** (fine-tune de Qwen3.8-27B par Nous Research, 32K de contexte servis, 2 unités de concurrence, *tool calling* indiqué comme supporté).
- [x] `FEATHERLESS_MODEL` mis à jour dans `.env.example`.
- [ ] **Tester le *tool calling* en conditions réelles** avec les outils MCP. La doc générale de Featherless ne garantit officiellement que Qwen 3 et Kimi-K2 ; Arete est basé sur Qwen 3.x et sa page l'annonce compatible, mais c'est à confirmer.
- [ ] **Gérer le raisonnement** : un modèle de la famille Qwen 3 peut produire un bloc de réflexion (`<think>…</think>`). Il faut le filtrer avant d'afficher la réponse.
- [ ] **Construire un jeu d'évaluation** d'une vingtaine de questions types (factuelles, comparaisons d'un mois à l'autre, « mon député », hors sujet, questions orientées), avec les réponses attendues.
  - Pourquoi c'est important : la fiche du modèle annonce un score factuel moyen de 2,98/5 sur l'évaluation de ses auteurs. L'ancrage sur le rapport et le MCP est donc indispensable.
  - Vérifier aussi la **neutralité politique** : le fine-tune d'Arete porte précisément sur les réponses politiques.
- [ ] **Prévoir un modèle de repli** (Qwen 3) si le *tool calling* ou la qualité ne suffisent pas.

---

## Plus tard

- [ ] Déclenchement automatique du pipeline le 1ᵉʳ du mois (GitHub Actions, clé en *secret* du repo).
- [ ] Requêtes sur l'ensemble des mois (DuckDB) pour les comparaisons dans le temps.
