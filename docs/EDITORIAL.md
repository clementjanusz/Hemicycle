# Ligne éditoriale

Document de travail de la rédaction. C'est lui qui guide ce que le pipeline calcule, ce que le site montre et ce que le chatbot peut dire.

## Le projet

**Titre du rapport** : _à définir_

**Promesse au lecteur** : _une phrase — ce que le lecteur saura chaque mois en lisant le rapport._

## Format d'un numéro mensuel

Chaque numéro combine deux parties :

| Partie | Principe | Pourquoi |
| --- | --- | --- |
| **Baromètre** | Les mêmes indicateurs chaque mois, calculés de la même façon. | Permet de comparer d'un mois à l'autre et de suivre les tendances. |
| **Focus** | Un sujet d'enquête choisi par la rédaction pour le mois. | Apporte l'angle journalistique, l'analyse et le récit. |

Modèle d'un numéro : [`rapports/_modele/rapport.md`](../rapports/_modele/rapport.md).

### Indicateurs du baromètre

À définir une fois pour toutes (changer un indicateur casse la comparaison avec les mois précédents).

| Indicateur | Définition précise | Endpoint(s) Hémicycle |
| --- | --- | --- |
| _ex. Nombre de scrutins publics_ | _scrutins dont la date tombe dans le mois, AN uniquement_ | `GET /scrutins` |
| _ex. Taux de loyauté moyen par groupe_ | _…_ | `POST /agregats/loyaute-deputes` |
| _ex. Groupes qui votent le plus ensemble_ | _…_ | `POST /agregats/accord-groupes` |
| _ex. Amendements déposés / adoptés_ | _…_ | `GET /amendements` |
| _…_ | | |

### Idées de focus

Une piste = une issue GitHub « Piste éditoriale ».

- Les députés qui votent contre leur propre groupe.
- Les alliances de fait entre groupes, et sur quels sujets.
- La fabrique de la loi : qui dépose le plus d'amendements, et combien sont adoptés.
- Le parcours d'un texte phare, de son dépôt au Journal officiel.
- Le lobbying autour d'un texte (répertoire HATVP).
- L'écart entre discours (débats, presse) et votes.

## Le chatbot : règles éditoriales

Le chatbot parle au nom du rapport : il doit respecter les mêmes standards que le texte.

- **Uniquement Hémicycle.** Le chatbot ne s'appuie que sur des données Hémicycle : le rapport (construit à partir d'Hémicycle) et les résultats des outils du MCP Hémicycle. Jamais sur les connaissances propres du modèle : pas de date, de nom ni de chiffre absent de ces sources.
- **Le rapport fait foi.** Il répond d'abord à partir du rapport et des indicateurs du mois.
- **Transparence sur les sources.** Ce qui vient d'Hémicycle en direct (via le MCP) est signalé comme « non vérifié par la rédaction », avec le lien vers la source officielle.
- **Neutralité.** Des faits et des votes, pas d'opinions ni de pronostics politiques.
- **Humilité.** « Je ne sais pas » vaut mieux qu'une réponse inventée.
- **Périmètre.** Il refuse poliment les questions sans rapport avec le Parlement ou le rapport.

Ces règles serviront de base au prompt système du chatbot.

## Vérification (fact-checking)

Avant publication d'un numéro, pour chaque chiffre :

- [ ] Le chiffre est retrouvable à partir d'une source officielle (champ `source`).
- [ ] La période et le périmètre sont précisés (mois, chambre, législature).
- [ ] Une deuxième personne a refait le calcul ou vérifié la requête.
- [ ] Le chiffre est cohérent avec le mois précédent, ou l'écart est expliqué.
- [ ] Les données calculées par Hémicycle (agrégats, prédictions) sont présentées comme telles.
- [ ] Les formulations ne disent pas plus que ce que montrent les données.

## Citer les sources

- Données publiques brutes : citer l'éditeur d'origine (Assemblée nationale, Sénat…) et la licence, à partir du champ `source`.
- Données calculées par Hémicycle : « Source : Hémicycle ».
