# Contribuer

Quelques règles simples pour travailler à plusieurs sans se marcher dessus pendant le hackathon.

## Workflow Git

1. Partir de `main` à jour :
   ```bash
   git switch main && git pull
   ```
2. Créer une branche nommée selon le pôle et le sujet :
   ```
   front/<sujet>     ex. front/carte-hemicycle
   back/<sujet>      ex. back/chatbot-outils-mcp
   data/<sujet>      ex. data/nettoyage-amendements
   docs/<sujet>      ex. docs/regles-chatbot
   rapport/AAAA-MM   ex. rapport/2026-10   (rédaction d'un numéro)
   ```
3. Committer souvent, par petits morceaux.
4. Ouvrir une **pull request** vers `main` et demander une relecture à une personne de l'équipe.
5. Merger une fois la PR approuvée, puis supprimer la branche.

## Messages de commit

Format court : `<type>: <description>` — en français, à l'impératif.

| Type | Usage |
| --- | --- |
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction de bug |
| `data` | Ajout ou mise à jour d'un jeu de données |
| `docs` | Documentation, textes éditoriaux |
| `style` | Mise en forme, CSS, sans changement de logique |
| `chore` | Config, dépendances, outillage |

Exemples : `feat: ajoute la page de détail d'un scrutin`, `data: exporte les votes du groupe X en CSV`.

## Issues

Utiliser les modèles proposés à la création d'une issue :

- **Tâche** — un morceau de travail à faire (front, back, data, rédaction).
- **Piste éditoriale** — une question journalistique à creuser dans les données.
- **Bug** — quelque chose qui ne marche pas.

Ajouter un label de pôle (`frontend`, `backend`, `data`, `editorial`) et s'assigner l'issue avant de commencer.

## Ce qu'on ne commit jamais

- Le fichier `.env` ou toute clé API (Hémicycle `hmc_test_…` / `hmc_live_…`, Featherless).
- Les réponses brutes de l'API (`data/raw/`) — elles restent en local.
- Les dossiers de dépendances (`node_modules/`, `.venv/`…).

Si une clé a été commitée par erreur : la **révoquer immédiatement** (Hémicycle : [hemicycle.ai/compte-api](https://hemicycle.ai/compte-api) ; Featherless : tableau de bord) et en créer une nouvelle — la supprimer de l'historique ne suffit pas.

## Données et sources

- Chaque chiffre affiché dans le rapport doit pouvoir être retracé jusqu'à sa source officielle.
- Conserver l'objet `source` renvoyé par l'API dans les données traitées.
- Données calculées par Hémicycle (prédictions, agrégats) : citer « Source : Hémicycle ».
