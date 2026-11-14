# Rapports

Un dossier par numéro mensuel, nommé `AAAA-MM` (le mois couvert, pas le mois de publication).

```
rapports/
├── _modele/
│   └── rapport.md     # Modèle à copier pour chaque nouveau numéro
├── 2026-10/
│   └── rapport.md     # Numéro d'octobre 2026
└── …
```

Le fichier `rapport.md` est lu par :

- **le site**, qui l'affiche avec les dataviz ;
- **le chatbot**, qui s'en sert comme source principale pour répondre aux lecteurs.

## Créer un nouveau numéro

```bash
mkdir rapports/2026-11
cp rapports/_modele/rapport.md rapports/2026-11/rapport.md
```

Travailler sur une branche `rapport/2026-11`, puis ouvrir une pull request.

## Règles

- Les chiffres cités viennent de `data/processed/AAAA-MM/indicateurs.json` — on les référence par leur `id` pour pouvoir vérifier.
- Des titres de sections clairs : le chatbot les utilise pour citer ses sources.
- Un numéro publié ne se réécrit pas : les corrections passent par un encadré « Erratum ».
