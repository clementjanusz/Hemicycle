# Chatbot du dossier (module autonome)

Un bouton « Poser une question » qui ouvre un panneau de discussion. Le lecteur interroge le dossier du mois et les données de l'Assemblée ; la réponse cite ses sources et peut faire défiler la page jusqu'à la section concernée.

## Intégration : une ligne, avant `</body>`

```html
<script src="chatbot/chatbot.js" data-mois="2026-11" defer></script>
<!-- sur une page sans les sections du dossier (accueil) : -->
<script src="chatbot/chatbot.js" data-mois="2026-11" data-rapport="incendies.html" defer></script>
```

Le script charge `chatbot.css` (à côté de lui) et injecte le widget à la fin de `<body>`. Il ne dépend d'aucun script, variable ou classe de la page.

| Attribut | Défaut | Rôle |
| --- | --- | --- |
| `data-mois` | `2026-11` | Numéro du rapport (`AAAA-MM` ou `demo`). Repli : `window.CHATBOT_MOIS`. |
| `data-api` | `""` (même origine) | URL du backend si le site est servi ailleurs, ex. `http://127.0.0.1:8000`. Repli : `window.CHATBOT_API`. |
| `data-rapport` | aucun | Page du dossier. Si une réponse vise une section absente de la page courante, le widget y va (`incendies.html#prevenir`), rouvre le panneau, défile et surligne. Repli : `window.CHATBOT_RAPPORT`. |

Dans la page, tout élément `[data-chatbot-ouvrir]` ouvre le panneau. Une valeur non vide est posée comme question, ex. `<button data-chatbot-ouvrir="Que s’est-il passé sur les incendies ?">`.

**Mémoire de l'onglet** (`sessionStorage`, clé `chapo-chatbot:<mois>`) : historique envoyé au serveur, fil affiché et consigne pour la page suivante. La conversation suit le lecteur d'une page à l'autre. `<html data-cb-vu="1">` est posé dès la première ouverture du panneau : le CSS cesse alors de faire sautiller le lanceur. Sans stockage disponible, le widget marche sans mémoire.

## Backend utilisé

- `POST /chat/flux` (NDJSON) : `{ mois, question, historique }`, 20 messages d'historique au plus. Formats : [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).
- Aucune clé côté navigateur. En local : `cd backend/chatbot && .venv/bin/python serveur.py`, puis `http://127.0.0.1:8000/`.

## Identifiants de section

Les actions `surligner_section` visent un élément `id="…"` du dossier : `carte`, `aides`, `prevenir`, `cotisations`, `pompiers`, `suite`, `scrutins`, `donnees`. Si l'id manque dans la page et sans `data-rapport`, l'action est ignorée : pas de défilement, et la source s'affiche sans lien.

`rapports/<mois>/rapport.md` doit porter les mêmes ids, avec le suffixe `{#id}` sur les titres `##` (ex. `## Un crédit d’impôt pour débroussailler {#prevenir}`). Si la page change d'ids, mettre à jour le rapport en même temps.
