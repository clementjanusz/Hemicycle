# Ligne éditoriale

Document de travail de la rédaction. C'est lui qui guide ce que le back-end va chercher et ce que le front-end va montrer.

## Angle

**Question centrale** : _une phrase, la question à laquelle le rapport répond._

**Pourquoi maintenant** : _actualité, enjeu, ce qui rend le sujet pertinent._

**Ce qu'on veut montrer** : _le ou les messages principaux, si les données les confirment._

## Pistes à explorer

Une piste = une issue GitHub « Piste éditoriale ». Quelques idées pour démarrer, à partir de ce que permet l'API :

- Cohésion des groupes : quels députés votent le plus souvent contre leur groupe ? (`/agregats/loyaute-deputes`)
- Alliances de fait : quels groupes votent ensemble, sur quels sujets ? (`/agregats/accord-groupes`)
- Fabrique de la loi : qui dépose le plus d'amendements, et combien sont adoptés ? (`/agregats/classement-auteurs`, `/amendements`)
- Parcours d'un texte : de son dépôt à sa promulgation au Journal officiel (`/dossiers`)
- Lobbying : quels représentants d'intérêts gravitent autour d'un texte ? (HATVP)
- Écart entre discours et votes : croiser débats, presse et scrutins

## Plan du rapport

| # | Section | Message clé | Données / dataviz | Statut |
| --- | --- | --- | --- | --- |
| 0 | Introduction / chapô | | | ⬜ |
| 1 | _…_ | | | ⬜ |
| 2 | _…_ | | | ⬜ |
| 3 | _…_ | | | ⬜ |
| — | Méthodologie et sources | Comment on a travaillé | | ⬜ |

## Vérification (fact-checking)

Avant publication, pour chaque chiffre du rapport :

- [ ] Le chiffre est retrouvable à partir d'une source officielle (lien dans l'objet `source`).
- [ ] La période et le périmètre sont précisés (législature, dates, chambre).
- [ ] Une deuxième personne a refait le calcul ou vérifié la requête.
- [ ] Les données calculées par Hémicycle (agrégats, prédictions) sont présentées comme telles.
- [ ] Les formulations ne disent pas plus que ce que montrent les données.

## Sources

| Donnée | Éditeur | Lien officiel | Licence |
| --- | --- | --- | --- |
| _…_ | _Assemblée nationale_ | | _Licence Ouverte 2.0_ |
