# Front-end — le rapport

Ce dossier contient la partie visible du projet : la page (ou les pages) du rapport journalistique, avec la mise en récit et les visualisations de données.

## Responsabilités

- Afficher le récit : textes, chiffres clés, citations, encadrés méthodologiques.
- Construire les dataviz (graphiques, hémicycle, cartes, tableaux interactifs).
- Récupérer les données **uniquement via le back-end** (ou les fichiers de `data/processed/`).
- Afficher les sources sous chaque visualisation.

## Ce que le front ne fait pas

- ❌ Appeler directement `api.hemicycle.ai` — la clé API exposerait le compte et les crédits de l'équipe.
- ❌ Faire des calculs lourds sur les données : ils sont faits en amont par le back-end.

## Stack

_À choisir en équipe — noter la décision dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)._

Pistes adaptées à un rapport de type « long format » / scrollytelling :

| Besoin | Options |
| --- | --- |
| Framework | Astro, SvelteKit, Next.js, ou simple Vite + HTML |
| Dataviz | Observable Plot, D3.js, Chart.js, ECharts |
| Scrollytelling | Scrollama |
| Style | CSS natif, Tailwind |

## Travailler sans attendre le back-end

Tant que le back-end n'est pas prêt, utiliser des fichiers JSON d'exemple qui respectent le **contrat d'API interne** décrit dans [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md). Les ranger dans `frontend/mocks/`.

## Lancer le projet

_À compléter une fois la stack choisie (installation, commande de dev, port)._

```bash
# exemple
cd frontend
npm install
npm run dev
```

## Checklist avant la démo

- [ ] Chaque graphique a un titre, une légende et une source.
- [ ] Les chiffres du texte correspondent à ceux des graphiques.
- [ ] La page est lisible sur mobile.
- [ ] Les couleurs des groupes politiques sont cohérentes d'un graphique à l'autre.
- [ ] Une section « Méthodologie » explique d'où viennent les données.
