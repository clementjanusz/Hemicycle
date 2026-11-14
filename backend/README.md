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

### Modèle : Qwen3-32B

Modèle retenu : **[`Qwen/Qwen3-32B`](https://featherless.ai/models/Qwen/Qwen3-32B)**. La famille Qwen 3 fait partie des modèles pour lesquels Featherless documente officiellement le *tool calling* natif, et c'est le modèle utilisé dans leur [exemple](https://featherless.ai/docs/tool-calling).

| Caractéristique | Valeur sur Featherless |
| --- | --- |
| Contexte servi | **32K tokens** → rapport et résultats d'outils à garder compacts |
| Concurrence | 2 unités par requête |
| *Tool calling* | Supporté nativement (format OpenAI `tools` / `tool_calls`) |
| Quantification | FP8 |

Points de vigilance (détail dans [`TODO.md`](TODO.md#6-modèle--qwen3-32b)) :

- Qwen 3 peut produire un bloc de raisonnement (`<think>…</think>`) : le filtrer avant d'afficher la réponse, ou le désactiver ;
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
