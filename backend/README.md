# Back-end — données et API

Ce dossier contient tout ce qui touche à la récupération et à la préparation des données : appels à l'API Hémicycle, mise en cache, nettoyage, calculs, et exposition des données au front-end.

## Responsabilités

- **Seul détenteur de la clé API** Hémicycle (lue depuis `.env`).
- Appeler l'API Hémicycle et **mettre en cache** les réponses (`data/raw/`) pour économiser le quota.
- Nettoyer, croiser et agréger les données.
- Exposer au front un petit nombre d'endpoints simples, ou exporter des fichiers dans `data/processed/`.
- Conserver l'objet `source` de chaque donnée pour permettre la citation.

## Deux modes possibles (à trancher en équipe)

| Mode | Principe | Quand le choisir |
| --- | --- | --- |
| **Export statique** | Des scripts récupèrent les données et produisent des fichiers JSON/CSV dans `data/processed/`, lus directement par le front. | Rapport figé, hébergement simple, zéro serveur pendant la démo. |
| **API proxy** | Un serveur expose des endpoints au front et interroge Hémicycle (avec cache). | Besoin d'interactivité : recherche d'un député, filtres dynamiques… |

Pour un hackathon, l'**export statique** est souvent le plus sûr ; on peut combiner les deux.

## Stack

_À choisir en équipe — noter la décision dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)._

| Besoin | Options |
| --- | --- |
| Langage | Python (pratique pour l'analyse de données) ou Node.js / TypeScript (même langage que le front) |
| Serveur | FastAPI, Flask · Express, Hono, Fastify |
| Analyse | pandas, Polars, DuckDB, notebooks Jupyter |
| Cache | Fichiers JSON dans `data/raw/`, SQLite |

## Points d'attention avec l'API Hémicycle

Résumé complet dans [`docs/API_HEMICYCLE.md`](../docs/API_HEMICYCLE.md). L'essentiel :

- En-têtes obligatoires : `Authorization: Bearer <clé>` et `Hemicycle-Version: 2026-10-01`.
- Pagination par curseur (`limit` ≤ 100, puis `cursor=<next_cursor>` tant que `has_more` vaut `true`).
- Clé de test : **100 appels/jour**. Toujours vérifier le cache avant d'appeler l'API.
- Réessayer uniquement sur `429`, `500` et `503`, en respectant `Retry-After`.

## Lancer le projet

_À compléter une fois la stack choisie (installation, commande de dev, port)._

```bash
# exemple
cd backend
cp ../.env.example ../.env   # si pas déjà fait
# installer les dépendances puis lancer le serveur
```
