# Front-end — le site du rapport

Un **site statique** qui publie chaque mois un nouveau numéro du rapport, avec ses visualisations, ses archives et un chatbot pour poser des questions.

## Ce que contient le site

- **La page du numéro du mois** : texte de `rapports/AAAA-MM/rapport.md` + dataviz construites à partir de `data/processed/AAAA-MM/`.
- **Les archives** : un numéro par mois, avec la possibilité de comparer dans le temps.
- **Une page Méthodologie** : d'où viennent les données, comment les chiffres sont calculés.
- **Le widget chatbot** : le lecteur pose une question, le site appelle `POST /chat` (voir [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)). Les sources de chaque réponse sont affichées, en distinguant visuellement celles **issues du rapport** (vérifiées par la rédaction) de celles **issues d'Hémicycle en direct** (non vérifiées).

## Ce que le front ne fait pas

- ❌ Appeler l'API Hémicycle — toutes les données sont déjà calculées par le pipeline.
- ❌ Calculer des chiffres : il affiche ceux de `indicateurs.json`, pour que le texte, les graphiques et le chatbot disent la même chose.
- ❌ Détenir une clé API.

## Stack

_À choisir en équipe — noter la décision dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)._

| Besoin | Options |
| --- | --- |
| Générateur de site | Astro (très adapté : contenu en Markdown + une page par mois), SvelteKit, Next.js en export statique |
| Dataviz | Observable Plot, D3.js, Chart.js, ECharts |
| Scrollytelling | Scrollama |
| Style | CSS natif, Tailwind |

## Travailler sans attendre le pipeline

Utiliser des fichiers d'exemple qui respectent les **contrats de données** de [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) (`indicateurs.json`, réponse de `/chat`) et les ranger dans `frontend/mocks/`.

## Lancer le projet

_À compléter une fois la stack choisie (installation, commande de dev, port)._

```bash
# exemple
cd frontend
npm install
npm run dev
```

## Checklist avant publication d'un numéro

- [ ] Chaque graphique a un titre, une légende et une source.
- [ ] Les chiffres du texte correspondent à ceux de `indicateurs.json`.
- [ ] Les couleurs des groupes politiques sont les mêmes d'un graphique et d'un mois à l'autre.
- [ ] La page est lisible sur mobile.
- [ ] Le numéro apparaît dans les archives.
