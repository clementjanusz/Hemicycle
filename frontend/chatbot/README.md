# Chatbot du dossier (module autonome)

Un bouton « Poser une question » qui ouvre un panneau de discussion. Le lecteur interroge le dossier du mois et les données de l'Assemblée ; la réponse cite ses sources et peut faire défiler la page jusqu'à la section concernée.

## Intégration : une ligne, avant `</body>`

```html
<script src="chatbot/chatbot.js" data-mois="2026-11" defer></script>
```

Le script charge `chatbot.css` (à côté de lui) et injecte le widget à la fin de `<body>`. Il ne dépend d'aucun script, variable ou classe de la page.

| Attribut | Défaut | Rôle |
| --- | --- | --- |
| `data-mois` | `2026-11` | Numéro du rapport (`AAAA-MM` ou `demo`). Repli : `window.CHATBOT_MOIS`. |
| `data-api` | `""` (même origine) | URL du backend si le site est servi ailleurs, ex. `http://127.0.0.1:8000`. Repli : `window.CHATBOT_API`. |

## Backend utilisé

- `POST /chat/flux` (NDJSON) : `{ mois, question, historique }`, 20 messages d'historique au plus. Formats : [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).
- Aucune clé côté navigateur. En local : `cd backend/chatbot && .venv/bin/python serveur.py`, puis `http://127.0.0.1:8000/site/`.

## Identifiants de section

Les actions `surligner_section` visent un élément `id="…"` de la page : `carte`, `aides`, `prevenir`, `cotisations`, `pompiers`, `suite`, `scrutins`. Un id absent de la page est ignoré (pas de défilement, source affichée sans lien).

`rapports/<mois>/rapport.md` doit porter les mêmes ids, avec le suffixe `{#id}` sur les titres `##` (ex. `## Un crédit d’impôt pour débroussailler {#prevenir}`). Si la page change d'ids, mettre à jour le rapport en même temps.
