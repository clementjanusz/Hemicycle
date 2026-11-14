# Lisière V6 — passer du prototype à une édition actualisable

[Ouvrir la V6](index-v6.html) · [Recherche Hémicycle précédente](recherche-hemicycle.md) · [Contours départementaux](departements.geojson)

## Résultat attendu

Un lecteur ouvre le même récit au défilement, sélectionne un département sur la carte et explore les scrutins par groupe, nom ou circonscription. Une personne qui maintient le site peut relancer la collecte, voir ce qui a changé et reconstruire le site avec les données vérifiées. La page affiche la date de l’édition et les sources de chaque scène. 

Pour une première implémentation, utiliser **un collecteur Python et une génération HTML/JS statique**. Le site pourra être reconstruit à la demande, puis sur un rythme choisi par l’équipe. La collecte s’exécute en CI, sur un serveur ou sur le poste de la personne qui maintient l’édition. Le navigateur charge uniquement les données publiques générées.

## Point de départ dans le projet

- `index-v6.html` contient le récit, le style, les interactions et un bloc JSON `#edition-data` avec quatre clés : `map`, `scrutins`, `actors`, `texts`.
- La liste des départements documentés est dans l’objet JavaScript `affected`. Les textes des scènes, leurs sources et les liens vers les scrutins sont inscrits dans le HTML. Les identifiants et libellés des cinq scrutins sont repris dans `ballotNames`.
- L’édition de référence est arrêtée au **14 novembre 2026**. Elle contient 28 départements renseignés sur 96 contours métropolitains, cinq scrutins, 574 fiches de députés et treize autres textes. Ces valeurs servent à vérifier la reconstruction de cette édition. Elles ne constituent pas des objectifs pour les éditions suivantes.
- Partir des fichiers versionnés et des sources publiques. Les fichiers temporaires de collecte utilisés pour le prototype ne sont pas requis pour la future implémentation.

## Rejouer la collecte Hémicycle

Base utilisée lors de la V6 : `https://api.hemicycle.ai/v1`. Les appels testés portent l’en-tête `Hemicycle-Version: 2026-10-01`. Confirmer la version et le contrat dans la [documentation Hémicycle](https://hemicycle.ai/docs) lors de l’implémentation.

Injecter la clé par la variable d’environnement `HEMICYCLE_API_KEY`, depuis un secret local ou de CI. Garder cette valeur hors du dépôt, des journaux, des réponses publiques et des ressources du site. Exemple d’appel de diagnostic avec une clé déjà chargée dans l’environnement :

```sh
curl --fail-with-body --silent --show-error --max-time 20 \
  -H "Authorization: Bearer ${HEMICYCLE_API_KEY:?Clé Hémicycle requise}" \
  -H "Hemicycle-Version: 2026-10-01" \
  -H "Accept: application/json" \
  "https://api.hemicycle.ai/v1/scrutins/VTANR5L17V8924/resultat"
```

| Étape | Requête utilisée | Traitement |
| --- | --- | --- |
| Balayer les dépôts | `GET /textes?legislature=17&depuis=2026-07-01&limit=100` | Filtrer les dates de dépôt à la date d’édition, dédupliquer par identifiant et sélectionner les textes pertinents. |
| Balayer les scrutins | `GET /scrutins?legislature=17&depuis=2026-07-01&limit=100` | Examiner aussi les votes dont le titre ne cite pas le sujet, notamment ceux sur un article ou un numéro d’amendement. |
| Chercher par thème | `GET /recherche?q=<terme>&types=texte,amendement,scrutin,dossier&limit=100` | Utiliser les huit termes ci-dessous. Les résultats peuvent atteindre la limite de retour de la recherche, même sans curseur suivant. Le balayage des listes complète cette recherche sans garantir une couverture nationale exhaustive. |
| Vérifier le texte et le dossier | `GET /textes/{id}`, `GET /dossiers/{id}`, `GET /amendements/{id}` | Vérifier le rattachement exact, le texte visé, l’article, l’auteur et le sort de l’amendement. Un numéro isolé peut désigner plusieurs amendements. |
| Vérifier un scrutin retenu | `GET /scrutins/{id}`, `GET /scrutins/{id}/resultat`, `GET /scrutins/{id}/votes` | Le premier donne l’objet et le décompte. Le second donne notamment les groupes et leurs décomptes. Le troisième retourne les positions nominatives associées à l’identifiant du scrutin. |
| Identifier les élus | `GET /acteurs/{id}` et `GET /organes` selon les besoins | Utiliser l’annuaire de l’Assemblée pour la circonscription et le département. Pour un vote, afficher le groupe fourni dans le scrutin à cette date. |

Termes de recherche V6 : `incendies`, `feux de forêt`, `Saumos`, `débroussaillement`, `sapeurs-pompiers`, `sécurité civile`, `sinistrés`, `reconstruction`.

Pour les listes paginées, lire les objets dans `data` et renvoyer `next_cursor` dans le paramètre `cursor` tant que `has_more` est vrai. Avec `has_more: true`, un curseur absent ou répété indique une collecte incomplète. Conserver les paramètres de recherche entre les pages. Appliquer la date de fin localement à `date_depot` ou à `date`, selon la ressource. Lors de la collecte d’origine, Hémicycle a renvoyé **489 entrées de textes avant déduplication** et **1 992 entrées de scrutins** depuis le 1ᵉʳ juillet. Ces volumes résument ce qui a été interrogé à l’époque.

Limiter la concurrence et fixer un délai pour chaque appel. Réessayer de manière bornée sur `429` et les erreurs serveur transitoires en respectant `Retry-After` s’il est présent. Une réponse `401` ou `403` nécessite de vérifier le secret. Un `404` sur une référence attendue doit être signalé avec son identifiant. Si une collecte échoue ou reste partielle, conserver la dernière édition publiée et remonter quelles routes ou pages manquent.

## Liens législatifs confirmés dans la V6

| Scène et objet exact | Rattachement | Pour / contre / abstentions | Source officielle |
| --- | --- | --- | --- |
| Crédit d’impôt pour le débroussaillement | PLF 2027 `PRJLANR5L17B3210`, amendement I-3339 de Sophie Pantel et amendement identique, scrutin `VTANR5L17V8775` | 53 / 14 / 40 | [Amendement](https://www.assemblee-nationale.fr/dyn/17/amendements/3210A/AN/3339) · [Scrutin](https://www.assemblee-nationale.fr/dyn/17/scrutins/8775) |
| Calcul de l’aide aux indépendants | PLFSS 2027 `PRJLANR5L17B3211`, amendement n° 39 d’Arnaud Simion à l’article 4, scrutin `VTANR5L17V8904` | 72 / 33 / 74 | [Amendement](https://www.assemblee-nationale.fr/dyn/17/amendements/3211/AN/39) · [Scrutin](https://www.assemblee-nationale.fr/dyn/17/scrutins/8904) |
| Aides après les feux et soutien au volontariat | PLFSS 2027, vote sur l’article 4 dans son ensemble en première lecture, scrutin `VTANR5L17V8905` | 159 / 9 / 3 | [Projet déposé](https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3211.raw) · [Scrutin](https://www.assemblee-nationale.fr/dyn/17/scrutins/8905) |
| Cotisations des services d’incendie | PLFSS 2027, amendement n° 306 rectifié de Sophie Panonacle après l’article 4, scrutin `VTANR5L17V8924` | 62 / 10 / 46 | [Amendement](https://www.assemblee-nationale.fr/dyn/17/amendements/3211/AN/306) · [Scrutin](https://www.assemblee-nationale.fr/dyn/17/scrutins/8924) |
| Rejet de la partie recettes | PLFSS 2027, dossier `DLR5L17N54951`, scrutin `VTANR5L17V9097` sur la deuxième partie. Son rejet entraîne celui du projet à l’Assemblée à cette étape. | 1 / 115 / 22 | [Scrutin](https://www.assemblee-nationale.fr/dyn/17/scrutins/9097) · [Dossier du Sénat](https://www.senat.fr/dossier-legislatif/plfss2027.html) |

Le projet de loi de finances (PLF) et le projet de loi de financement de la Sécurité sociale (PLFSS) suivent chacun leur procédure. Le rejet du PLFSS ne change pas le statut du crédit d’impôt débattu dans le PLF. Pour un texte à plusieurs étapes, conserver la date, la chambre, l’objet précis et le stade de chaque vote. Renseigner l’application d’une mesure à partir d’une loi promulguée, d’un décret ou d’une autre source officielle confirmant son entrée en vigueur.

## Actualiser la carte et le récit

1. **Carte.** Utiliser le code INSEE du département comme clé et conserver une source datée pour chaque zone rouge. Le [bilan provisoire du CNPF](https://www.cnpf.fr/actualites/feux-de-foret-un-ete-2026-hors-norme-le-cnpf-pleinement-mobilise) atteste des feux dans les départements nommés et dans l’ensemble du Grand Est. La [préfecture de Gironde](https://www.gironde.gouv.fr/layout/set/print/Actualites/Communiques-de-presse/Communiques-de-presse-2026/Septembre-2026/Le-feu-de-Saumos-est-desormais-eteint) documente le bilan de Saumos. Le gris signifie « non renseigné ». Conserver la distinction entre hectares parcourus, hectares détruits, feu isolé et total départemental. Si un jeu de données plus complet devient disponible, vérifier période, définition du feu et couverture avant de l’intégrer. [BDIFF](https://bdiff.agriculture.gouv.fr/)
2. **Aides et reconstruction.** Vérifier sur Légifrance la publication, la période couverte et les conditions communales des mesures d’urgence. L’arrêté reconnaissant le sinistre de grande ampleur, le décret d’activité partielle et le point du Gouvernement sur les indemnisations sont trois événements distincts. [Arrêté du 31 juillet](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000054618751) · [Décret du 17 septembre](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000054860173) · [Point du 25 septembre](https://www.info.gouv.fr/public/index.php/communique/incendies-en-gironde-et-dans-les-landes-l-etat-accelere-la-reconstruction)
3. **Veille.** Reprendre les recherches sur les incendies, les aides, la reconstruction, la fiscalité locale et le financement des secours. Utiliser la presse pour repérer des événements à vérifier. Recouper les décisions et leur statut avec les décrets, dossiers et comptes rendus officiels. Un résultat de recherche entre d’abord dans les candidats à relire. Ajouter au récit les éléments dont le lien avec le sujet est établi et enregistrer la source ainsi que sa date de consultation. [Article 14 du PLF déposé](https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw) · [Données des scrutins](https://data.assemblee-nationale.fr/travaux-parlementaires/votes)

## Structure de la future implémentation

Arborescence proposée pour la suite :

```text
src/
  template.html                  # structure du récit, carte et explorateur
  story.css                      # style du prototype
  story.js                       # scènes au scroll, carte, groupes et filtres
editorial/
  incendies-2026.json             # scènes, sources, départements et liens confirmés
scripts/
  lisiere.py                     # commandes collect, prepare et build
data/
  raw/                           # réponses publiques de collecte
  editions/                     # instantanés validés, datés et reproductibles
dist/
  index.html                     # édition prête à servir
```

- **`collect`** télécharge et archive les réponses brutes utiles, avec le moment de collecte, les paramètres non sensibles, le statut et l’état de pagination. Le rapport liste les références nouvelles ou modifiées et les échecs de collecte. La date d’édition est distincte de la date de collecte.
- **`prepare`** applique l’adaptateur Hémicycle, produit un instantané et un diff lisible, puis vérifie les liens et décomptes. Le fichier éditorial contient les scènes, l’interprétation et les sources confirmées. Les nouveaux candidats peuvent être inspectés puis intégrés en modifiant ce fichier.
- **`build`** construit la page depuis un instantané précis, sans accès réseau. Au début, conserver le bloc JSON embarqué pour pouvoir ouvrir le HTML directement. Échapper les données injectées dans le HTML, en particulier les séquences qui pourraient fermer une balise `script`. Le site publie la dernière édition validée après une construction réussie. Conserver les anciennes éditions pour permettre un retour à une version antérieure.

Commandes à implémenter, données ici comme interface cible :

```sh
python3 scripts/lisiere.py collect --since 2026-07-01 --as-of 2026-11-14
python3 scripts/lisiere.py prepare --as-of 2026-11-14
python3 scripts/lisiere.py build --edition 2026-11-14 --output dist/index.html
```

Un déploiement statique suffit pour cette première version. Si le site doit afficher les nouvelles données sans reconstruire le HTML, servir le même instantané validé comme JSON public et mettre à jour ce fichier après validation. Les appels avec la clé restent côté collecte dans les deux cas.

### Contrat entre données et interface

Conserver d’abord la forme que la V6 sait lire, puis faire évoluer le schéma avec un champ de version :

- `map` contient les contours, indexés par code INSEE. Ajouter un registre `departments` avec le statut documentaire, un éventuel événement ou chiffre qualifié, et la source. Une valeur inconnue reste `null` ou absente.
- `scrutins[id]` contient le numéro, la date, le titre, la source, les groupes et les positions. Dans la V6, `totals` suit l’ordre **pour, contre, abstentions, non-votants de droit**. Les lignes `votes` contiennent `[acteurId, groupeId, position]`, avec les codes `0` à `3` dans ce même ordre. Côté import, la position API du non-votant s’écrit `nonVotant`, tandis que le champ du décompte général s’écrit `non_votants`.
- `actors[acteurId]` contient `[nom, groupeAnnuaire, département, circonscription]`. Préserver une position publiée même si la fiche territoriale manque. Un élu absent des lignes publiées s’affiche comme « aucune position publiée ». Ce libellé reste distinct de l’abstention et du statut « non-votant de droit ». [Annuaire officiel](https://www2.assemblee-nationale.fr/deputes/liste/regions?vue=tableau)
- `texts` contient les notices repérées. Déplacer la chronologie et les libellés aujourd’hui dispersés dans le HTML et le JS vers `scenes`, avec un identifiant stable, des références de sources et, si confirmé, un identifiant de scrutin. Cela permet d’ajouter une scène sans modifier le code qui pilote le défilement.

### Vérifications avant de livrer une mise à jour

- Reconstituer l’édition du 14 novembre depuis son instantané et retrouver les cinq scrutins, les treize textes, les 96 contours et les 28 départements documentés. Conserver cet instantané comme référence de comparaison.
- Aligner chaque scrutin sur son identifiant et son objet officiel. Comparer les votes individuels aux totaux et aux groupes publiés. Pour le 8775, le résultat attendu est **107 votants et 108 lignes nominatives** en comptant le non-votant de droit. Inspecter toute divergence, tout identifiant manquant et tout doublon conflictuel avant d’utiliser les résultats.
- Vérifier que les codes de départements existent dans le fond de carte, que chaque sélection rouge a une source, et que toutes les scènes et leurs liens utilisent des références présentes dans l’instantané.
- Vérifier dans un navigateur le passage entre scènes au scroll, la carte au clic et au clavier, ainsi que les filtres de scrutin, groupe, nom et position. Contrôler la lecture sur mobile et avec les animations réduites.
- Simuler une collecte indisponible, un curseur manquant et un décompte contradictoire. Vérifier que le rapport explique l’erreur et que la dernière édition publiée reste disponible.
