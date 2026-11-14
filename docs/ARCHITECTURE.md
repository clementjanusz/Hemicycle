# Architecture

## Vue d'ensemble

```
┌────────────────────┐        ┌────────────────────┐        ┌──────────────────────┐
│     FRONT-END      │  HTTP  │      BACK-END      │  HTTPS │    API HÉMICYCLE     │
│  rapport + dataviz │ ─────▶ │ cache, nettoyage,  │ ─────▶ │ api.hemicycle.ai/v1  │
│                    │        │ agrégats, sources  │        │  (clé API secrète)   │
└────────────────────┘        └─────────┬──────────┘        └──────────────────────┘
          │                             │
          │                             ▼
          │                   ┌────────────────────┐
          └─────────────────▶ │  data/processed/   │  fichiers JSON / CSV
             (mode statique)  └────────────────────┘
```

- Le **front** ne connaît que le back-end (ou les fichiers de `data/processed/`).
- Le **back** est le seul à parler à Hémicycle et à détenir la clé.

## Décisions techniques

À remplir dès le début du hackathon pour que tout le monde parte sur les mêmes bases.

| Sujet | Décision | Pourquoi | Qui |
| --- | --- | --- | --- |
| Mode back-end (export statique / API proxy / les deux) | _…_ | | |
| Langage back-end | _…_ | | |
| Framework back-end | _…_ | | |
| Framework front-end | _…_ | | |
| Librairie de dataviz | _…_ | | |
| Gestionnaire de paquets (npm, pnpm, uv, pip…) | _…_ | | |
| Hébergement de la démo | _…_ | | |

## Contrat d'API interne (front ↔ back)

**À figer tôt** : une fois le format des réponses défini, front et back peuvent avancer en parallèle (le front travaille avec des mocks).

| Endpoint back-end (ou fichier) | Paramètres | Réponse | Utilisé par (section du rapport) | Endpoint(s) Hémicycle |
| --- | --- | --- | --- | --- |
| _ex. `GET /api/scrutins-cles`_ | _—_ | _liste de `{ id, titre, date, pour, contre, abstention, source }`_ | _Partie 1_ | _`GET /scrutins`, `GET /scrutins/{id}/resultat`_ |
| _…_ | | | | |

### Conventions de réponse

- Format JSON, clés en `snake_case`.
- Dates au format ISO 8601 (`2026-11-14`).
- Chaque objet affichable porte un champ `source` : `{ "editeur": "...", "url": "...", "licence": "..." }`.
- Erreurs : `{ "error": "message lisible" }` avec un code HTTP adapté.

## Ports en local

| Service | Port |
| --- | --- |
| Front-end | `5173` _(à ajuster selon le framework)_ |
| Back-end | `8000` |
