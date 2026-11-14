# Rapport sur l'API Hémicycle (hemicycle.ai)

Rapport rédigé le 14/11/2026 pour l'équipe du hackathon, qui produit un rapport journalistique mensuel sur les données parlementaires françaises. Il complète le mémo [`API_HEMICYCLE.md`](API_HEMICYCLE.md) sans le remplacer : le mémo reste la fiche courte, ce rapport est la référence détaillée.

**Méthode.** Quatre sources, croisées :

1. les 27 fiches de savoir-faire du serveur MCP (outil `guide`, gratuit), plus l'arborescence ;
2. le site de documentation : les 26 pages Markdown publiées sous `https://hemicycle.ai/docs-md/<page>.md`, le fichier `https://hemicycle.ai/llms.txt`, et le module JavaScript `apiSpec` qui alimente la référence `/docs/api` et la page `/docs/openapi` ;
3. 54 appels réels à l'API REST (`https://api.hemicycle.ai/v1`), dont 24 facturés, pour 27 crédits ;
4. le catalogue des 132 jeux de données (`GET /v1/jeux`, identique à l'outil `lister_jeux`).

## Conventions de citation

| Repère | Signification |
|---|---|
| **[F:sujet]** | Fiche `guide` du serveur MCP, lue le 14/11/2026 (`guide`, 0 crédit). Exemple : [F:credits-et-limites]. |
| **[Doc:page]** | Page `https://hemicycle.ai/docs/<page>`, lue dans sa version Markdown `https://hemicycle.ai/docs-md/<page>.md` le 14/11/2026. |
| **[Spec]** | Référence de l'API : module `apiSpec` du site (il génère `/docs/api`, `/docs/api/<id>` et `/docs/openapi`), lu le 14/11/2026. |
| **[Site:page]** | Autre page du site (tarifs, données, modèles, hackathon, bibliothèque), texte extrait des fichiers JavaScript le 14/11/2026. |
| **[Cat]** | Catalogue des jeux : `GET /v1/jeux` = outil MCP `lister_jeux`, 14/11/2026. |
| **[R nn]** | Appel REST réel du 14/11/2026, entre 14 h 48 et 14 h 56 UTC ; `nn` est le numéro de la ligne de l'annexe B. |
| **[MCP]** | Appel réel au serveur MCP le 14/11/2026 (`initialize`, `tools/list`, `guide`, `resources/list`). |
| **[Équipe]** | Test antérieur de l'équipe (mémo `API_HEMICYCLE.md`, échantillons MCP du 14/11/2026 dans le dossier de travail). |

Pour l'API REST, chaque affirmation porte un statut : **vérifié** (constaté en réel), **doc** (documenté, non testé), **supposé** (déduction de notre part).

---

## 1. Résumé

1. Hémicycle (hemicycle.ai) est une base qui relie les données publiques du Parlement (Assemblée nationale, Sénat) à celles de l'administration, et deux modèles maison : **Orcet** (prédiction des votes) et **Marianne** (réponses sourcées, pas encore ouverte aux comptes API) [F:comprendre-hemicycle].
2. Deux accès, même compte, mêmes crédits, mêmes données : une **API REST** versionnée (`https://api.hemicycle.ai/v1`, en-tête `Hemicycle-Version: 2026-10-01`) et un **serveur MCP** (`https://api.hemicycle.ai/mcp`, 18 outils en lecture seule) [F:demarrage-rapide, MCP].
3. Les points d'accès de lecture (`/textes`, `/amendements`, `/scrutins`, `/acteurs`) ne couvrent que l'Assemblée nationale ; le Sénat, la HATVP, les finances publiques et une centaine de sources publiques passent par **132 jeux de données** lus avec `POST /v1/jeux/interroger` ou l'outil `interroger` [F:donnees, Cat].
4. Profondeur : scrutins de l'Assemblée depuis 2012 (14e législature, 2,4 millions de votes nominatifs), amendements de la 17e législature, Sénat depuis octobre 2023, dossiers législatifs depuis 1986 [F:sources-et-licences, Cat].
5. Fraîcheur : synchronisation chaque nuit ; le 14/11/2026, la dernière ingestion datait de 05 h 18 UTC et le dernier scrutin de l'Assemblée indexé était celui du 12/11 [R 20, R 12].
6. Tarif : 1 crédit = 0,01 € ; 1 crédit par page ou par lecture, 2 par recherche, 5 par agrégat ou page de jeu dérivé, 50 par prédiction d'Orcet ; les erreurs ne sont pas facturées, les réponses vides le sont [F:credits-et-limites, R 01, R 17].
7. Limites documentées : 300 requêtes par minute pour les lectures, 30 pour les modèles, 100 par jour avec une clé de test ; aucun en-tête `RateLimit-*` n'est pourtant renvoyé [F:limites, R 01 à R 56].
8. Chaque objet porte un champ `source` (éditeur, URL, licence) ; les données calculées par Hémicycle se citent « Source : Hémicycle » [F:sources-et-licences].
9. La documentation surestime plusieurs réponses : pas de détail par groupe dans `/scrutins/{id}`, pas d'étapes dans `/textes/{id}` ni `/dossiers/{id}`, pas de lien vers le scrutin dans `/amendements/{id}`, pas de scrutins dans `/recherche` [R 13, R 29, R 32, R 52, R 17].
10. Pour notre rapport mensuel, l'essentiel (scrutins du mois, positions et accord des groupes, loyauté, déposants d'amendements, Sénat, lobbying, contexte économique) coûte de l'ordre de 40 à 80 crédits, soit moins de 1 € par mois (estimation, section 11).

---

## 2. Couverture des données

### 2.1 Sources déclarées

| Source | Contenu | Couverture | Licence | Repère |
|---|---|---|---|---|
| Assemblée nationale | Textes, amendements, scrutins et votes nominatifs, agenda, députés, organes | Scrutins depuis 2012, amendements de la 17e législature | Licence Ouverte (Etalab 2.0) | [F:sources-et-licences, Site:donnees] |
| Sénat | Textes, amendements, scrutins, sénateurs, organes | Depuis octobre 2023 | Licence du portail data.senat.fr | [F:sources-et-licences, Cat] |
| Dossiers législatifs | Parcours des lois, d'une chambre à l'autre jusqu'à la promulgation | Depuis 1986 | Licence Ouverte | [F:sources-et-licences, Site:donnees] |
| Journal officiel | Lois et décrets publiés | Textes en vigueur (Légifrance) | Licence Ouverte | [F:sources-et-licences, Cat] |
| HATVP | Répertoire des représentants d'intérêts, déclarations | Données publiées | Licence Ouverte | [F:sources-et-licences, Cat] |
| Débats | Comptes rendus et vidéos des séances, transcrits et indexés | Séances publiques et commissions | Données publiques des assemblées | [F:sources-et-licences, Site:donnees] |
| Presse | Articles de 620 médias, classés par sujet | Titres, extraits, liens | Droits des éditeurs, lien vers la source | [F:sources-et-licences, Site:donnees] |
| Sources publiques « lues à la source, sans copie » | Collectivités, élus locaux, France Travail, CAF, santé, éducation, enseignement supérieur, sécurité, logement, élections, commande publique, énergie, Eurostat, Banque de France, Insee, Légifrance, Judilibre | Variable selon le jeu (annexe A) | Licence propre à chaque jeu | [F:outils, F:donnees-publiques, Cat] |

**Ce qui est réellement exposé par l'API.** Les points d'accès de lecture portent sur l'Assemblée nationale seulement [F:donnees]. Les débats (comptes rendus, vidéos) et la presse figurent dans la base Hémicycle, mais nous n'avons trouvé **aucun jeu ni point d'accès qui les expose** : aucun des 132 jeux ne contient de compte rendu ou d'article de presse [Cat], et `/recherche` n'a pas été testé sur la presse (la référence l'annonce, section 4.3.13). Le jeu `reunions` donne l'ordre du jour et une référence `compte_rendu_ref`, pas le texte du compte rendu [Cat]. Les signaux faibles (`signaux_faibles`) agrègent des mentions médiatiques, sans les articles [Cat].

### 2.2 Profondeur historique, jeu par jeu (extraits du catalogue)

| Domaine | Profondeur | Repère |
|---|---|---|
| Scrutins de l'Assemblée (`scrutins`) | Depuis la 14e législature (juin 2012) | [Cat] |
| Votes nominatifs de l'Assemblée (`votes`) | 2,4 millions de lignes | [Cat] |
| Scrutins et votes du Sénat | Depuis octobre 2023 (base DOSLEG) | [Cat] |
| Députés (`deputes`) | Députés et anciens députés | [Cat] |
| Budget de l'État (`budget_credits`) | États B des PLF 2025 à 2027, états C et D du PLF 2027, colonne LFI 2026 | [Cat] |
| Exécution mensuelle du budget de l'État | Janvier 2024 à septembre 2026 (une colonne par fin de mois) | [Cat] |
| Comptes de l'État | 2016 à 2025 | [Cat] |
| Comptes des collectivités (OFGL) | Communes et intercommunalités 2018-2025 ; départements et régions 2012-2025 | [Cat] |
| Protection sociale (DREES) | Depuis 1959 | [Cat] |
| Participation électorale | Par bureau de vote, chaque scrutin depuis 1999 | [Cat] |
| Délinquance enregistrée | Communes 2016-2025 | [Cat] |
| Effectifs scolaires | Écoles depuis 2009, collèges depuis 2019, étudiants depuis 2001-2002 | [Cat] |
| Index égalité professionnelle | 2018 à 2025 | [Cat] |
| Événements parlementaires (Hémicycle) | **Trente derniers jours seulement** | [Cat] |
| Légifrance (`legifrance_codes`, `legifrance_lois_decrets`) | Textes **en vigueur à la date du jour** (pas d'historique) | [Cat] |

### 2.3 Fréquence de mise à jour

- « Les données ouvertes des assemblées sont synchronisées chaque nuit » [F:sources-et-licences, Site:donnees]. Le jeu `scrutins` précise « Index mis à jour chaque matin » [Cat].
- Les jeux « lus à la source » ne sont pas copiés : chaque réponse donne la date de dernière publication [F:outils].
- 15 jeux ont une colonne de mise à jour ligne par ligne (`maj_le`, `moissonne_le`, `evalue_le`, `date_mise_a_jour`, `mis_a_jour_le`) [Cat].
- Chaque réponse d'`interroger` et d'un agrégat porte `consulte_le` (heure de l'appel) et `derniere_ingestion_hemicycle` [R 20, R 21].
- 63 jeux portent un champ `verification` (`verifiee_le` au 11 ou 12/11/2026, `preuve: "meme_source"`, `references: 3`) ; le jeu `qualite_registre` note chaque jeu de A à E [Cat].

### 2.4 Fraîcheur constatée le 14/11/2026 (samedi)

| Donnée | Plus récent observé | Repère |
|---|---|---|
| Dernière ingestion Hémicycle (Assemblée, Sénat, agrégats) | `2026-11-14T05:18:46Z` (6 h 18, heure de Paris) | [R 20, R 21] |
| Scrutins de l'Assemblée | 12/11/2026 : 89 scrutins, n° 9807 à 9895 ; aucun scrutin du 13/11 | [R 12] |
| Actes de procédure de l'Assemblée | Discussion en séance publique datée du 13/11/2026 | [Équipe : échantillon `actes`] |
| Amendements de l'Assemblée | Déposés le 12/11, sort renseigné le 12/11 à 19 h 08 | [R 31] |
| Textes déposés à l'Assemblée (`/textes`, jeu `documents`) | Dépôt le plus récent : 05/11/2026 (n° 3440 à 3442) | [R 26, Équipe : échantillon `documents`] |
| Scrutins du Sénat | 13/11/2026 (scrutin 2026-99), `maj_le` 14/11 à 04 h 58 UTC | [Équipe : échantillon `senat_scrutins`] |
| Événements parlementaires | Événements datés du 14/11 (séance PLF 2027) | [Équipe : échantillon `evenements_parlementaires`] |
| Exécution du budget de l'État | Situation au 30/09/2026 | [Cat] |

Conclusion : un scrutin de l'Assemblée est en général lisible le lendemain matin. L'écart entre les textes (dernier dépôt au 05/11) et les scrutins (12/11) reste à expliquer (question ouverte n° 4).

---

## 3. Accès

### 3.1 Compte, organisation, clés

- Les clés, les crédits et les membres appartiennent à une **organisation**, la même que dans Atlas (le produit d'abonnement d'Hémicycle). Rôles : administrateur, manager, analyste, lecteur ; les administrateurs gèrent crédits et facturation, administrateurs et managers gèrent les clés [F:comprendre-hemicycle].
- Création du compte et des clés : `https://hemicycle.ai/compte-api`. La clé ne s'affiche qu'une fois ; Hémicycle n'en garde qu'une empreinte. Révocation immédiate. Une clé par application est recommandée, avec une date d'expiration pour un usage temporaire [F:authentification].
- Une clé est en lecture seule : elle lit la base et appelle les modèles ; aucune clé ne peut modifier la base [F:authentification].

| Préfixe | Usage | Facturation | Limites | Particularité |
|---|---|---|---|---|
| `hmc_test_` | Développement | Gratuite (coût toujours 0) | 100 appels par jour | Les modèles (Orcet, Marianne, expositions, livrables) renvoient des réponses fixes marquées `"exemple": true` |
| `hmc_live_` | Production | Crédits décomptés | Limites standard | Données réelles partout |

Sources : [F:cles, F:demarrage-rapide].

**Nos clés.** Le `.env` racine définit `HEMICYCLE_API_KEY` (REST), `HEMICYCLE_MCP_KEY` (MCP), `HEMICYCLE_API_BASE_URL`, `HEMICYCLE_API_VERSION` et `HEMICYCLE_MCP_URL` (noms de variables seulement, valeurs non lues). La clé REST est une clé de production : nos appels ont été décomptés (`X-Credits-Cost: 1`) [R 03]. Les soldes lus par les deux clés concordent (10 492 par le MCP vers 14 h 45 UTC, 10 487 par REST à 14 h 48) : elles puisent **vraisemblablement** dans le même solde d'organisation (supposé).

**Assistants grand public.** Claude, ChatGPT et Le Chat se connectent au serveur MCP par **OAuth** (pas de clé à copier ; autorisations révocables sur la page Compte API) ; Cursor, VS Code et Claude Code utilisent l'en-tête `Authorization: Bearer hmc_live_…` [F:installer].

### 3.2 Authentification

En-tête `Authorization: Bearer <clé>` sur chaque requête [F:authentification]. **Vérifié** : sans clé, `401` au format `problem+json`, `type` `…#cle-invalide`, `detail` « Passez votre clé dans l'en-tête Authorization: Bearer hmc_... », non facturé [R 08].

### 3.3 Versionnement

- L'API est versionnée par date, via l'en-tête `Hemicycle-Version`. Une seule version existe : `2026-10-01` (« première version, en aperçu »). Sans en-tête, la version la plus récente s'applique [F:versions].
- Changements réputés compatibles : nouveau point d'accès, nouveau champ, nouveau paramètre facultatif, nouvelle valeur d'énumération ; le code client doit ignorer les champs inconnus [F:versions].
- Statut de tous les points d'accès et des deux modèles : **aperçu** (« utilisable et facturé, mais sa forme peut encore évoluer ») ; Marianne, expositions et livrables sont en **Labs** [F:cycle-de-vie, Spec].
- **Vérifié** : chaque réponse renvoie l'en-tête `hemicycle-version: 2026-10-01` ; sans en-tête, la requête passe (200) [R 27] ; avec `Hemicycle-Version: 2020-01-01`, `400` `…#version-inconnue`, « Versions disponibles : 2026-10-01. », non facturé [R 28].
- Le serveur MCP n'exige pas cet en-tête [Équipe].

### 3.4 Limites de débit et quotas

| Appels | Limite par défaut | Repère |
|---|---|---|
| Lectures et recherches | 300 requêtes par minute | [F:limites] |
| Modèles (Orcet, Marianne, expositions, livrables) | 30 requêtes par minute | [F:limites] |
| Clés de test | 100 requêtes par jour | [F:limites, F:cles] |

- Les limites s'appliquent **par organisation**, toutes clés confondues ; elles peuvent être relevées sur demande [F:limites].
- Documenté : en-têtes `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, et `429` avec `Retry-After` [F:limites, F:erreurs].
- **Vérifié : aucun en-tête `RateLimit-*` n'est renvoyé**, ni sur les succès ni sur les erreurs, et ils ne figurent pas dans `Access-Control-Expose-Headers` (qui liste `retry-after`) [R 01 à R 56]. Nous n'avons pas provoqué de `429`.

### 3.5 En-têtes de réponse constatés

| En-tête | Contenu | Présent sur | Repère |
|---|---|---|---|
| `X-Credits-Cost` | Crédits décomptés pour l'appel | Toutes les réponses, erreurs comprises (`0`) | [R 01 à R 56] |
| `X-Credits-Remaining` | Solde après l'appel | Succès seulement (absent des erreurs) | [R 04, R 05] |
| `X-Request-Id` | `req_…`, à citer au support (repris dans le corps des erreurs) | Toutes | [R 01, R 04] |
| `X-Operation-Id` | Identifiant de l'opération facturée (identique au `_meta.operation_id` du MCP) | Succès | [R 01, R 37, R 38] |
| `X-Tarif-Version` | `2026-11-08` | Succès | [R 01] |
| `Hemicycle-Version` | Version appliquée (`2026-10-01`) | Toutes sauf version inconnue | [R 01, R 28] |
| `Idempotent-Replayed` | `true` quand la réponse est rejouée | Rejeu idempotent | [R 38] |

CORS : `Access-Control-Allow-Origin: *`, méthodes `GET, POST, OPTIONS`, en-têtes acceptés `authorization, content-type, hemicycle-version, idempotency-key` [R 01]. La clé ne doit pas pour autant être mise dans une page web [F:authentification].

### 3.6 Idempotence

Non décrite dans la documentation, sauf une ligne : « la reprise d'un appel déjà servi avec la même clé d'idempotence » n'est pas facturée [F:credits-et-limites]. **Vérifié** : l'en-tête de requête `Idempotency-Key` est accepté ; le second appel identique avec la même clé coûte 0 crédit, renvoie `Idempotent-Replayed: true` et le même `X-Operation-Id` [R 37, R 38]. Utile pour réessayer sans payer deux fois après une coupure réseau.

---

## 4. API REST

### 4.1 Conventions générales

- **Base** : `https://api.hemicycle.ai/v1` ; JSON ; `GET` pour lire, `POST` pour les agrégats, les jeux et les modèles [Spec, F:automatisation].
- **Pagination** (listes `/textes`, `/dossiers`, `/amendements`, `/scrutins`, `/acteurs`, `/organes`, `/recherche`) : paramètres `limit` (1 à 100, 20 par défaut) et `cursor` ; réponse `{ "data": [...], "has_more": bool, "next_cursor": "…" | null }` [Spec, F:pagination]. **Vérifié** : `limit=500` → `400` « limit doit être un entier de 1 à 100. » [R 04] ; curseur illisible → `400` « Le curseur est illisible : reprenez la valeur next_cursor de la page précédente. » [R 33] ; le curseur est un décalage encodé en base64 (`eyJvIjozfQ` = `{"o":3}`, `eyJvIjoxMDB9` = `{"o":100}`) [R 03, R 12].
- **Jeux** : pagination par `decalage` (0 à 10 000) et `limite` dans le corps ; la réponse donne `decalage_suivant` [Spec, R 20].
- **Tri** : « du plus récent au plus ancien » [F:filtres]. **Vérifié** pour `/scrutins` : date décroissante, mais **numéro croissant à l'intérieur d'une même journée** (page 1 : n° 9807, 9808, 9809 du 12/11 ; page 2 : 9810 à 9812) [R 03, R 11, R 12].
- **Filtres** : combinés par ET ; liste de valeurs séparées par des virgules = OU ; dates ISO 8601 ; « les dates et heures sont en UTC » [F:filtres]. Constaté : les dates de l'Assemblée sont en heure de Paris (`2026-11-04T00:00:00.000+01:00`, `2026-11-12T19:08:53+01:00`), celles du Sénat en UTC (`+00:00`) [R 29, R 31, Équipe : échantillon `senat_reunions`].
- **Paramètres inconnus** : ignorés en silence (et facturés) sur les `GET` [R 34] ; refusés sur `POST /jeux/interroger` (« Arguments inconnus : valeurs_de. ») [R 56].
- **Route inconnue ou mauvaise méthode** : `404` « Point d'accès inconnu » (pas de `405`) [R 40, R 51].
- **Coût** : visible dans `X-Credits-Cost` ; erreurs à 0 [R 04 à R 10].

### 4.2 Tableau des 28 points d'accès

Coûts : [Spec] (codes `page` = 1, `lecture` = 1, `recherche` = 2, `enrichi` = 5, `orcet` = 50, `marianne` = 50/200, `exposition` = 1 000, `livrable` = 2 500, d'après la grille tarifaire [Site:tarifs]).

| Méthode et chemin | Usage | Crédits | Statut doc | Vérification (14/11/2026) |
|---|---|---|---|---|
| `GET /textes` | Lister les textes (Assemblée) | 1 par page | Aperçu | **Vérifié** [R 26] |
| `GET /textes/{id}` | Lire un texte | 1 | Aperçu | **Vérifié** [R 29] |
| `GET /dossiers` | Lister les dossiers législatifs | 1 par page | Aperçu | **Vérifié** [R 23] |
| `GET /dossiers/{id}` | Lire un dossier | 1 | Aperçu | **Vérifié** [R 32] |
| `GET /amendements` | Lister les amendements (Assemblée) | 1 par page | Aperçu | **Vérifié** [R 22, R 31, R 35] |
| `GET /amendements/{id}` | Lire un amendement | 1 | Aperçu | **Vérifié** [R 52] |
| `GET /scrutins` | Lister les scrutins (Assemblée) | 1 par page | Aperçu | **Vérifié** [R 03, R 11, R 12] |
| `GET /scrutins/{id}` | Lire un scrutin | 1 | Aperçu | **Vérifié** [R 13] |
| `GET /scrutins/{id}/votes` | Votes nominatifs | 1 | Aperçu | **Vérifié** [R 15] |
| `GET /scrutins/{id}/resultat` | Résultat par groupe et par député | 1 | Aperçu | **Vérifié** [R 14] |
| `GET /acteurs` | Lister les acteurs | 1 par page | Aperçu | **Vérifié** [R 25] |
| `GET /acteurs/{id}` | Lire un acteur | 1 | Aperçu | **Vérifié** [R 30] |
| `GET /organes` | Lister les organes | 1 par page | Aperçu | **Vérifié** [R 24] ; pas de `GET /organes/{id}` (404) [R 53] |
| `GET /recherche` | Recherche plein texte | 2 | Aperçu | **Vérifié** [R 16, R 17, R 36] |
| `GET /jeux` | Catalogue des jeux | 0 | Aperçu | **Vérifié** [R 02] |
| `POST /jeux/interroger` | Page d'un jeu | 1 par page ; 5 (jeu dérivé) ; 50 par prédiction d'Orcet | Aperçu | **Vérifié** [R 20, R 06, R 07, R 55, R 56] |
| `POST /agregats/classement-auteurs` | Classement des auteurs d'amendements | 5 | Aperçu | Route **vérifiée** par un `400` gratuit [R 43] |
| `POST /agregats/positions-groupes` | Positions des groupes sur 1 à 100 scrutins | 1 | Aperçu | **Vérifié** [R 21, R 50] |
| `POST /agregats/accord-groupes` | Accord entre groupes | 5 | Aperçu | Route **vérifiée** par un `400` gratuit [R 41] |
| `POST /agregats/loyaute-deputes` | Loyauté des députés | 5 | Aperçu | Route **vérifiée** par un `400` gratuit [R 42] |
| `POST /orcet/predictions` | Prédiction d'Orcet sur un amendement | 50 (0 sans prédiction) | Aperçu | Route **vérifiée** par un `400` gratuit [R 44] |
| `GET /entreprises` | Chercher une entreprise | 2 | Aperçu | Route **vérifiée** par un `400` gratuit [R 45] |
| `GET /donnees-publiques` | Chercher sur data.gouv.fr | 2 | Aperçu | Route **vérifiée** par un `422` gratuit [R 46] |
| `POST /donnees-publiques/lecture` | Lire un fichier data.gouv.fr | 2 | Aperçu | Route **vérifiée** par un `422` gratuit [R 47] |
| `POST /marianne/reponses` | Question à Marianne | 50 (200 approfondi) | Labs | `501`, non facturé [R 09] |
| `POST /expositions` | Exposition d'une entreprise | 1 000 | Labs | `501`, non facturé [R 48] |
| `POST /livrables` | Note ou présentation rédigée | 2 500 | Labs | `501`, non facturé [R 49] |
| `GET /credits` | Solde | 0 | Aperçu | **Vérifié** [R 01, R 54] |

### 4.3 Détail par point d'accès

#### 4.3.1 `GET /textes`
- Paramètres : `legislature` (entier) **vérifié** [R 26] ; `depuis` (date, « déposés à partir de cette date ») **doc** ; `limit`, `cursor` **vérifiés** [Spec].
- Réponse : `data[]` d'objets texte (voir 4.3.2) ; tri par date de dépôt décroissante (constaté sur 2 éléments) [R 26].
- Exemple : `GET /v1/textes?legislature=17&limit=2` → `PIONANR5L17B3442` et `PIONANR5L17B3441`, déposés le 05/11/2026 [R 26].

#### 4.3.2 `GET /textes/{id}`
- Documenté : « Un texte avec son dossier législatif, ses auteurs et ses étapes » [Spec].
- **Vérifié** : la réponse ne contient que `id`, `type`, `titre`, `titre_court`, `nature`, `legislature`, `date_depot`, `dossier` (identifiant), `auteur` (identifiant), `source` (481 caractères) [R 29]. Ni étapes, ni liste d'auteurs. Les étapes se lisent dans le jeu `actes` [Cat].
- `auteur` peut être un organe (`PO838901`) plutôt qu'un acteur [R 26].
- `source.url` pointe vers le JSON open data (`…/dyn/opendata/PIONANR5L17BTC3435.json`) [R 29].

#### 4.3.3 `GET /dossiers` et `GET /dossiers/{id}`
- Paramètres de liste : `legislature` **vérifié**, `limit`, `cursor` [R 23, Spec].
- Documenté : « Étapes, textes, rapporteurs et scrutins d'un dossier » [Spec]. **Vérifié** : `id`, `type`, `titre`, `procedure`, `legislature`, `initiateur` (`null` dans nos trois exemples), `source` (JSON open data) [R 23, R 32, R 36].
- Ordre de la liste : identifiants décroissants (`DLR5L17N55228`, `DLR5L17N55225`) [R 23].

#### 4.3.4 `GET /amendements`
- Paramètres [Spec] : `texte` (identifiant du texte amendé) **vérifié** [R 35] ; `auteur` (identifiant d'acteur) **doc** ; `sort` (`adopte`, `rejete`, `retire`, `tombe`, `irrecevable`, `non_soutenu`, `en_attente`) **vérifié** avec `adopte` [R 35] ; `depuis` (« déposés ou modifiés à partir de cette date ») **vérifié** [R 31] ; `limit`, `cursor`.
- Sémantique de `depuis` : `depuis=2026-11-12&sort=adopte` renvoie une liste vide [R 22], alors que l'amendement n° 3 au projet de loi de finances de fin de gestion a été adopté en séance le 12/11 (scrutin `VTANR5L17V9808`) [R 13]. Le filtre semble porter sur la **date de dépôt** et non sur la date du sort (**supposé**, à confirmer).
- Taille : 3,5 à 12 Ko par amendement (le dispositif reproduit parfois des tableaux entiers) [R 31, R 35, R 52].

#### 4.3.5 `GET /amendements/{id}`
- **Vérifié** : `id`, `type`, `numero` (chaîne, `"CF99"` pour un amendement de commission), `texte`, `article`, `dispositif` (peut valoir `null`), `expose`, `auteur`, `groupe`, `signataires` (texte), `sort`, `sort_libelle`, `date_depot`, `date_sort`, `legislature`, `source` [R 52].
- Documenté : « …sort et scrutin associé » [Spec] ; la fiche [F:suivre-un-texte] affirme que « chaque amendement mis aux voix porte l'identifiant de son scrutin ». **Aucun champ scrutin dans la réponse** [R 31, R 35, R 52].
- Amendements du Gouvernement : `auteur` et `groupe` valent `null`, `signataires` vaut « le Gouvernement » [R 31].
- **`source.url` est un chemin relatif** : `/base/AMANR5L17PO59048B3434P0D1N000099?format=pdf` [R 31, R 35, R 52].

#### 4.3.6 `GET /scrutins`
- Paramètres : `legislature` **vérifié** [R 03] ; `depuis` (« scrutins tenus à partir de cette date ») **vérifié** [R 12] ; `limit`, `cursor` **vérifiés** [R 11]. Pas de `jusqu_a`, pas de recherche [Spec].
- Objet : `id`, `type`, `numero` (entier), `date` (AAAA-MM-JJ), `titre`, `objet` (identique à `titre` dans nos exemples), `resultat` (`adopte` ou `rejete`), `decompte` {`pour`, `contre`, `abstention`, `non_votants`}, `legislature` (chaîne `"17"`), `source` (page lisible `https://www.assemblee-nationale.fr/dyn/17/scrutins/9807`) [R 03].
- Taille : environ 660 caractères par scrutin (62 857 pour 100) [R 12].
- Exemple : `GET /v1/scrutins?depuis=2026-11-10&limit=100` → 89 scrutins du 12/11 et 11 du 10/11 ; 41 adoptés, 59 rejetés ; `has_more: true` [R 12].

#### 4.3.7 `GET /scrutins/{id}`
- Documenté : « Objet, date, résultat et décompte par groupe » [Spec]. **Vérifié** : mêmes champs que dans la liste, **sans détail par groupe** (736 caractères) [R 13]. Pour les groupes : `/scrutins/{id}/resultat` ou `/agregats/positions-groupes`.

#### 4.3.8 `GET /scrutins/{id}/votes`
- **Vérifié** : réponse `{ "scrutin": "VTANR5L17V9808", "data": [ { "acteur", "groupe", "position" } ] }` ; **tous les votes d'un coup** (77) malgré `limit=3`, sans `has_more` ni curseur ; pas de nom de député (4 713 caractères) [R 15]. 1 crédit.

#### 4.3.9 `GET /scrutins/{id}/resultat`
- **Vérifié** : champs du scrutin + `groupes[]` {`groupe` (PO…), `libelle`, `sigle`, `pour`, `contre`, `abstention`, `non_votant`, `position_majoritaire`} (12 groupes) + `votes[]` {`acteur`, `nom`, `groupe`, `position`} (77 votants) + `votes_nominatifs_disponibles` (booléen) ; 9 231 caractères pour 77 votants, soit environ 120 caractères par votant [R 14]. 1 crédit.
- Pour un scrutin à 577 votants, compter de l'ordre de 70 000 caractères (extrapolation de [R 14]).

#### 4.3.10 `GET /acteurs`
- Paramètres : `nom` (« nom de famille, ou son début ») **vérifié** : `nom=tanguy` renvoie trois acteurs, dont une ancienne députée [R 25] ; `groupe` (« identifiant du groupe politique : membres actuels ») **doc** ; `limit`, `cursor`.
- Objet : `id`, `type`, `civilite`, `prenom`, `nom`, `profession`, `hatvp` (URL ou `null`), `source` (page lisible `…/dyn/deputes/PA795778`) [R 25].

#### 4.3.11 `GET /acteurs/{id}`
- Documenté : « Mandats, groupes, commissions et activité récente » [Spec]. **Vérifié** : champs de la liste + `mandats[]` {`organe` (PO…, sans libellé), `nature`, `qualite`, `debut`, `fin`, `legislature`} ; 50 mandats et 6 175 caractères pour Jean-Philippe Tanguy ; **pas d'« activité récente »** [R 30].
- Aucune donnée personnelle hors mandat (adresse, date de naissance) n'est exposée [F:donnees].

#### 4.3.12 `GET /organes`
- Paramètre : `type` (`commission`, `groupe`, `delegation`) **vérifié** avec `groupe` [R 24].
- Objet : `id`, `type`, `libelle`, `sigle`, `nature` (`GP`), `chambre` (`null`), `legislature`, `debut`, `fin`, `source` (JSON open data) [R 24].
- La liste mêle **toutes les législatures** (groupes de la 12e à la 17e) et n'a pas de filtre de législature ; il faut garder `fin = null` pour les groupes actuels [R 24, Spec].
- `GET /organes/{id}` n'existe pas (`404` « Point d'accès inconnu ») [R 53] ; le jeu `organes` sert de substitut [Cat].

#### 4.3.13 `GET /recherche`
- Paramètres : `q` (obligatoire) **vérifié** ; `types` (liste séparée par des virgules) **vérifié** avec `texte,amendement`, `dossier`, `scrutin` ; `limit` **vérifié** ; `cursor` [R 16, R 17, R 36, Spec].
- Documenté : « Recherche plein texte sur les textes, amendements, scrutins, acteurs et articles de presse » [Spec]. **Constaté** : `q=droits voisins&types=scrutin` renvoie une liste vide (et coûte 2 crédits) alors que le scrutin `VTANR5L17V9807` porte ces mots dans son titre [R 17, R 03]. L'outil MCP `rechercher` annonce d'ailleurs « textes, dossiers législatifs et amendements de l'Assemblée nationale » [MCP]. Types `acteur` et presse : non testés.
- Les résultats ne sont pas triés par date : une recherche « assurance chômage » a renvoyé en premier un rapport de 2016 [Équipe : `rechercher` du 14/11]. Un texte du Sénat peut sortir avec `legislature: null` [R 16].
- Taille : environ 560 caractères par résultat [R 16].
- Pour chercher un sujet dans les **scrutins**, utiliser le jeu `scrutins` avec `recherche`, qui porte sur l'intitulé et sur l'exposé des amendements votés [Cat, R 20].

#### 4.3.14 `GET /jeux`
- **Vérifié** : gratuit, `{ "jeux": [ 132 objets ] }`, 205 753 caractères, identique à l'outil `lister_jeux` [R 02]. Champs : section 6.3.

#### 4.3.15 `POST /jeux/interroger`
- Corps [Spec, MCP] : `jeu` (obligatoire) ; `colonnes` (60 au plus) ; `filtres` (10 au plus, objets `{colonne, op, valeur}`, `op` parmi `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like` (3 à 100 caractères, insensible à la casse), `in` (1 à 100 valeurs), `est_nul` (booléen)) ; `recherche` (2 à 200 caractères, plein texte en français, syntaxe web : guillemets, `OR`, signe moins) ; `tri` (colonne permise par `/jeux`) ; `ordre` (`asc` ou `desc`, défaut `desc`) ; `limite` (200 au plus, 20 pour Orcet, 100, 50 ou 5 selon le jeu) ; `decalage` (0 à 10 000).
- **Vérifié** avec `jeu`, `recherche`, `colonnes`, `tri`, `limite` [R 20].
- Réponse **vérifiée** : `jeu`, `source` {`nom`, `url`, `licence`, `licence_url`}, `sources_amont[]`, `consulte_le`, `derniere_ingestion_hemicycle`, `colonne_mise_a_jour`, `nombre`, `lignes[]`, `tronque`, `decalage_suivant`, `credits` {`reserves`, `dus`, `version_tarif`}, `pagination` [R 20]. Attention, les clés de `source` diffèrent de celles des objets (`nom` au lieu d'`editeur`).
- Erreurs **vérifiées**, toutes non facturées : jeu inconnu → `400` « Jeu inconnu : « inexistant ». Appelez lister_jeux. » [R 06] ; `votes` sans filtre → **`422`** `…#requete-refusee` « « votes » exige un filtre « eq » ou « in » sur scrutin_ref, acteur_ref, groupe_ref. » [R 07] ; `chomage_europe` sans filtre → `400` « Filtre exact requis sur : geo ; unit ; s_adj ; age ; sex. » suivi du mode d'emploi complet [R 55] ; argument inconnu → `400` [R 56].

#### 4.3.16 `POST /agregats/positions-groupes`
- Corps : `scrutins` (liste de 1 à 100 identifiants) **vérifié** [R 21] ; sans liste → `400` « « scrutins » attend une liste de 1 à 100 identifiants, par exemple VTANR5L17V2152. » [R 50].
- Réponse **vérifiée** : `outil`, `source`, `consulte_le`, `derniere_ingestion_hemicycle`, `perimetre` {`scrutins_demandes`, `introuvables`}, `definition`, `scrutins[]` {`id`, `date`, `numero`, `type` (`SPO`…), `titre`, `resultat`, `pour`, `contre`, `abstention`, `votes_nominatifs_disponibles`, `groupes[]`} ; 5 392 caractères pour 2 scrutins [R 21].
- Définition renvoyée : « Position majoritaire : celle qui réunit strictement plus de votes que chacune des deux autres ; à égalité, sans vote exprimé ou sur une motion de censure (seuls les votes pour y sont recensés), elle vaut null. Une position majoritaire n'est ni une consigne de vote ni l'unanimité du groupe. » [R 21].

#### 4.3.17 `POST /agregats/accord-groupes`, `/loyaute-deputes`, `/classement-auteurs`
- Mêmes paramètres que les outils MCP (section 5.2) [Spec].
- **Vérifié** (sans frais) : corps vide → `400` « Indiquez une période (« depuis ») ou une législature. » pour l'accord et la loyauté [R 41, R 42] ; « Indiquez un texte, une recherche ou une période (« depuis »). » pour le classement [R 43].
- Exemples de la référence : `{ "legislature": 17, "types": ["SPS"] }` (accord) ; `{ "legislature": 17, "groupe": "RN", "limite": 10 }` (loyauté) ; `{ "recherche": "agriculture", "legislature": 17, "limite": 10 }` (classement) [Spec].

#### 4.3.18 `POST /orcet/predictions`
- Corps : `amendement` (obligatoire) ; sans lui → `400` « amendement est obligatoire. » [R 44].
- Réponse documentée : `amendement`, `modele` (`orcet-v2`), `calcule: true`, `moyenne_probabilites_pour`, `definition`, `confiance`, `predit_le` ; `404` non facturé quand aucune prédiction n'existe [F:orcet]. 50 crédits ; non testé.

#### 4.3.19 `GET /entreprises`, `GET /donnees-publiques`, `POST /donnees-publiques/lecture`
- `/entreprises` : `q` (nom, SIREN ou dirigeant, 3 à 200 caractères) et `page` (1 à 100) ; sans `q` → `400` « « q » attend de 3 à 200 caractères. » [Spec, R 45].
- `/donnees-publiques` : `q` ; sans `q` → `422` « Donnez les mots-clés du sujet recherché. » [Spec, R 46]. Seuls les jeux de producteurs certifiés notés 70/100 ou plus sont rendus [MCP].
- `/donnees-publiques/lecture` : `fichier` (identifiant rendu par la recherche), `filtres` (5 au plus, `{colonne, operateur, valeur}` avec `egal`, `contient`, `inferieur`, `superieur`), `tri`, `ordre`, `lignes` (1 à 50) ; corps vide → `422` [Spec, R 47].
- Les opérateurs de `lire_donnees_publiques` (`egal`, `contient`…) diffèrent de ceux d'`interroger` (`eq`, `like`…) [Spec, MCP].

#### 4.3.20 `POST /marianne/reponses`, `/expositions`, `/livrables`
- Tous trois répondent `501` « Point d'accès pas encore ouvert », non facturé, même avec un corps vide [R 09, R 48, R 49].
- Paramètres prévus : Marianne `question`, `mode` (`standard` ou `approfondi`) ; expositions `siren` ; livrables `type` (`note` ou `presentation`), `sujet` [Spec].

#### 4.3.21 `GET /credits`
- **Vérifié** : `{ "solde": 10487, "unite": "crédit", "valeur_eur": 0.01 }`, gratuit [R 01]. La référence annonce aussi « la consommation du mois » : **absente** [Spec, R 01]. Le détail de la consommation par clé « arrivera dans une prochaine version » [F:credits-et-limites].

### 4.4 Spécification OpenAPI et autres ressources de doc

- La page `https://hemicycle.ai/docs/openapi` **génère le fichier dans le navigateur** (bouton « Télécharger hemicycle-openapi.json ») à partir du module `apiSpec` : il n'existe pas de fichier statique, d'où les `404` sur `/openapi.json` [Spec]. Le document produit est en OpenAPI 3.1, avec `x-credits` et `x-status` par opération, mais tous les paramètres y sont typés `string` et les réponses ne sont pas décrites [Spec].
- Chaque page de doc existe en Markdown brut : remplacer `/docs/` par `/docs-md/` et ajouter `.md` [Doc:llms]. Index pour agents : `https://hemicycle.ai/llms.txt` (convention llmstxt.org) [Doc:llms].
- Le contenu des 26 pages de doc est presque identique aux fiches `guide` ; seule différence de fond relevée : la page Orcet donne une évaluation chiffrée (section 7) [Doc:modeles/orcet].
- Autres pages utiles : `/donnees` (sources), `/modeles` (Orcet, Marianne), `/tarifs?onglet=api`, `/construire` (assistant qui propose les jeux et l'appel à copier pour un projet), `/bibliotheque` et `/bibliotheque/<jeu>` (fiche technique de chaque jeu : période couverte, dernière publication, note de qualité), `/hackathon` [Site].

---

## 5. Serveur MCP

### 5.1 Connexion et protocole

- Adresse `https://api.hemicycle.ai/mcp`, sans barre oblique finale ; transport HTTP diffusable (*streamable HTTP*) [F:installer, F:depannage].
- Protocole `2025-11-25` ; serveur `hemicycle` (titre « Hémicycle »), version `2026-10-01` ; capacités `tools` et `resources` (sans `listChanged`) ; serveur sans état [MCP, Équipe].
- Les méthodes `prompts/list` et `resources/templates/list` sont refusées (« Méthode non prise en charge ») [MCP].
- Chaque outil coûte « le même nombre de crédits que l'appel d'API correspondant » [F:outils].

**Instructions du serveur** (texte intégral renvoyé par `initialize`) [MCP] :

> Données parlementaires publiques et données produites par Hémicycle, en lecture seule. Appelez d'abord l'outil guide, gratuit : sans argument, il rend l'arborescence des savoir-faire (suivre un texte, analyser un vote, prédire un vote avec Orcet, construire un agent, crédits et limites, dépannage) ; avec un sujet, la fiche qui dit quels outils appeler, dans quel ordre et pour quel coût. Les mêmes fiches sont des ressources hemicycle://guide/<sujet>. Pour les données, appelez lister_jeux, puis interroger. Pour la position des groupes sur plusieurs scrutins, utilisez positions_groupes. Pour un classement d'auteurs, l'accord entre groupes ou la loyauté des députés envers leur groupe, utilisez classement_auteurs, accord_groupes ou loyaute_deputes, qui comptent tout le périmètre, plutôt que d'extrapoler sur une page. Citez la source et la licence renvoyées avec chaque réponse. Les prédictions d'Orcet sont des estimations, pas des résultats.

### 5.2 Les 18 outils

Tous portent l'annotation `read_only_hint: true`, sans `outputSchema` [MCP]. Les tailles viennent des mesures REST équivalentes [R] ou du test de l'équipe [Équipe].

| Outil | Paramètres (schéma réel) | Crédits | Taille typique | Équivalent REST |
|---|---|---|---|---|
| `guide` | `sujet` (énumération de 27 valeurs) ; sans argument : arborescence | 0 | 4 239 car. (arborescence) ; 800 à 5 800 par fiche | aucun (pages `/docs-md/`) |
| `lister_jeux` | aucun | 0 | 205 753 car. | `GET /jeux` |
| `interroger` | `jeu` (obligatoire, énumération des 132 jeux), `colonnes`, `filtres`, `recherche`, `tri`, `ordre`, `limite` (1 à 200), `decalage` (0 à 10 000) | 1 par page ; 5 (jeu dérivé) ; 50 par prédiction d'Orcet | ≈ 1 200 car. pour 3 lignes de 4 colonnes | `POST /jeux/interroger` |
| `rechercher` | `q` (obligatoire), `types` (chaîne : `texte`, `dossier`, `amendement`), `limit` (1 à 100) | 2 | ≈ 560 car. par résultat | `GET /recherche` |
| `lire_texte` | `id` | 1 | ≈ 500 car. | `GET /textes/{id}` |
| `lire_amendement` | `id` | 1 | 3,5 à 12 Ko | `GET /amendements/{id}` |
| `lire_scrutin` | `id` | 1 | ≈ 740 car. | `GET /scrutins/{id}` |
| `resultat_scrutin` | `id` | 1 | ≈ 120 car. par votant (9 Ko pour 77, ≈ 70 Ko pour 577) | `GET /scrutins/{id}/resultat` |
| `lire_acteur` | `id` | 1 | ≈ 6 Ko (50 mandats) | `GET /acteurs/{id}` |
| `positions_groupes` | `scrutins` (1 à 100 identifiants, motif `^[A-Za-z0-9]{5,40}$`) | 1 | ≈ 2,2 Ko par scrutin | `POST /agregats/positions-groupes` |
| `classement_auteurs` | `texte`, `recherche`, `depuis`, `jusqu_a`, `legislature`, `limite` (1 à 100, défaut 20), `exclure_rapporteurs` ; il faut un texte, une recherche ou une période d'un an au plus | 5 | non mesuré | `POST /agregats/classement-auteurs` |
| `accord_groupes` | `depuis`, `jusqu_a`, `legislature` (période ou législature obligatoire), `intitule` (3 à 100 car.), `types` (`SPO`, `SPS`, `SAT`, `SSG`) ; 10 000 scrutins au plus ; motions de censure exclues | 5 | non mesuré | `POST /agregats/accord-groupes` |
| `loyaute_deputes` | `depuis`, `jusqu_a`, `legislature`, `intitule`, `groupe` (sigle), `min_votes` (défaut 20), `limite` (défaut 20) ; hors non-inscrits et motions de censure ; méthode MiroPolis | 5 | non mesuré | `POST /agregats/loyaute-deputes` |
| `predire_vote` | `amendement` | 50 ; 0 sans prédiction | non mesuré | `POST /orcet/predictions` |
| `chercher_entreprise` | `q` (3 à 200 car.), `page` (1 à 100) | 2 | non mesuré | `GET /entreprises` |
| `chercher_donnees_publiques` | `q` (2 à 200 car.) | 2 | non mesuré | `GET /donnees-publiques` |
| `lire_donnees_publiques` | `fichier`, `filtres` (5 au plus, opérateurs `egal`, `contient`, `inferieur`, `superieur`), `tri`, `ordre`, `lignes` (1 à 50) | 2 | non mesuré | `POST /donnees-publiques/lecture` |
| `solde_credits` | aucun | 0 | < 100 car. | `GET /credits` |

Sources : schémas [MCP, `tools/list`], coûts [F:outils], équivalents [Spec].

### 5.3 Coût et métadonnées

- Le coût réel figure dans `_meta` du résultat : `operation_id`, `credits_cost`, `credits_remaining`, `tarif_version` (`2026-11-08`) [MCP]. Pas d'en-tête `X-Credits-*` côté MCP [Équipe].
- `_meta.operation_id` correspond à l'en-tête REST `X-Operation-Id` [R 01, MCP].
- Les réponses sont un bloc texte (JSON compact, ou Markdown pour `guide`) doublé de `structuredContent` [Équipe]. Les charges utiles sont les mêmes qu'en REST (même forme pour `rechercher` et `resultat_scrutin`) [Équipe, R 14, R 16].

### 5.4 Ressources

27 ressources `hemicycle://guide/<sujet>` (`text/markdown`), identiques aux fiches `guide`, lisibles par `resources/read` sans frais [MCP, F:outils].

### 5.5 Erreurs côté MCP

- Clé invalide : HTTP `401` et erreur JSON-RPC `-32001` [Équipe].
- Paramètre invalide (sujet inconnu, filtre exact manquant) : HTTP `200` avec erreur JSON-RPC `-32602`, dont le message liste les valeurs valides ou les colonnes à filtrer ; non facturé [F:erreurs, F:outils, Équipe].

---

## 6. Les 132 jeux de données

### 6.1 Vue d'ensemble

| Indicateur | Valeur | Repère |
|---|---|---|
| Jeux | 132 (même liste dans `/v1/jeux`, `lister_jeux` et l'énumération de l'outil `interroger`) | [Cat, MCP] |
| Prix | 121 à 1 crédit par page ; 9 à 5 crédits par page (jeux dérivés par Hémicycle) ; 2 à 50 crédits par prédiction renvoyée (Orcet) | [Cat] |
| Lignes par page au plus | 200 (51 jeux), 100 (70), 50 (7), 20 (Orcet, 2), 5 (2 : `legifrance_article`, `judilibre_decision`) | [Cat] |
| Recherche plein texte | 58 jeux | [Cat] |
| Filtre obligatoire déclaré (`filtre_obligatoire_sur`) | 2 jeux : `votes`, `senat_votes` | [Cat] |
| Mode d'emploi (`mode_emploi`) | 89 jeux, dont 32 qui disent « filtre toujours … » | [Cat] |
| Contrôle de vérification (`verification`) | 63 jeux | [Cat] |
| Producteurs | 36 éditeurs distincts ; les plus représentés : Assemblée nationale (13 jeux), Hémicycle (11), France Travail (9) | [Cat] |

### 6.2 Vue par thème

| Thème | Jeux | Prix | Plein texte | Jeux (noms) |
|---|---|---|---|---|
| Parlement : Assemblée nationale | 13 | 1/page | 5 | `scrutins`, `votes`, `amendements`, `dossiers`, `actes`, `documents`, `articles_textes`, `textes_moissonnes`, `organes`, `mandats`, `reunions`, `deputes`, `deputes_en_exercice` |
| Parlement : Sénat | 8 | 1/page | 2 | `senat_scrutins`, `senat_votes`, `senat_amendements`, `senat_dossiers`, `senat_textes`, `senat_reunions`, `senateurs`, `senat_collaborateurs` |
| Influence et autres élus | 2 | 1/page | 0 | `representants_interets` (HATVP), `eurodeputes` |
| Hémicycle : jeux dérivés | 9 | **5/page** | 0 | `correspondance_textes`, `rendements_impots`, `reperes_budgetaires`, `series_marche`, `qualite_registre`, `amendements_budget_articles`, `evenements_parlementaires`, `sigles`, `signaux_faibles` |
| Hémicycle : Orcet | 2 | **50 par prédiction** | 0 | `orcet_previsions_votes`, `orcet_predictions` |
| Budget de l'État et finances publiques | 10 | 1/page | 4 | `budget_credits`, `budget_recettes_etat`, `resf_tableaux`, `depenses_fiscales`, `budget_vert_plf_2026`, `performance_depense_rap_2025`, `execution_budget_etat_mensuelle`, `comptes_etat`, `comptes_publics`, `transferts_apu` |
| Sécurité sociale, santé, solidarité, CAF | 13 | 1/page | 10 | `secu_equilibres`, `secu_ondam`, `secu_recettes`, `comptes_sante_financement`, `depenses_sante_restes_a_charge`, `prestations_solidarite_mensuelles`, `aide_sociale_departementale_depenses`, `insertion_minima_sociaux_departements`, `comptes_protection_sociale`, `caf_prestations_departements`, `caf_prestations_communes`, `caf_depenses_prestations`, `accueil_jeune_enfant_communes` |
| Emploi et travail | 16 | 1/page | 6 | `demandeurs_emploi_france`, `demandeurs_emploi_regions`, `demandeurs_emploi_communes`, `flux_inscrits_france_travail`, `offres_emploi_france_travail`, `emplois_vacants`, `marche_travail_demandeurs`, `marche_travail_offres`, `marche_travail_tensions`, `acces_emploi_demandeurs`, `acces_emploi_sortants_formation`, `dynamique_emploi_territoires`, `rome_metiers`, `agences_france_travail`, `entreprises_potentiel_embauche`, `index_egalite_professionnelle` |
| Collectivités, élus locaux, élections | 13 | 1/page | 5 | `fiscalite_locale_professionnels`, `comptes_communes`, `comptes_intercommunalites`, `comptes_departements`, `comptes_regions`, `dotations_investissement_2025`, `elus_maires`, `elus_conseillers_municipaux`, `elus_conseillers_departementaux`, `elus_conseillers_regionaux`, `communes`, `insee_populations_reference`, `elections_participation` |
| Logement et aménagement | 6 | 1/page | 0 | `prix_immobilier_dvf`, `logements_vacants`, `communes_sru`, `consommation_espaces`, `loyers_appartements`, `coproprietes_communes` |
| Éducation et enseignement supérieur | 11 | 1/page | 10 | `ips_colleges`, `valeur_ajoutee_colleges`, `baccalaureat_academies`, `effectifs_ecoles`, `effectifs_colleges`, `personnels_second_degre`, `parcoursup_formations`, `insertion_diplomes`, `finances_universites`, `effectifs_etudiants`, `ips_ecoles` |
| Sécurité, justice, droit | 9 | 1/page | 3 | `delinquance_communes`, `delinquance_departements`, `accidents_route_2025`, `demandes_asile_departements`, `legifrance_codes`, `legifrance_lois_decrets`, `legifrance_article`, `judilibre_decisions`, `judilibre_decision` |
| Énergie, climat, prix | 7 | 1/page | 6 | `electricite_temps_reel`, `consommation_energie_regions`, `production_renouvelable_regions`, `temperatures_regions`, `temperatures_departements`, `prix_carburants_stations`, `prix_marches_gros` |
| Économie, entreprises, commande publique | 8 | 1/page | 6 | `marches_publics`, `projets_achats_publics`, `sirene_etablissements`, `insee_series`, `banque_france_series`, `banque_france_observations`, `banque_france_jeux`, `banque_france_nomenclatures` |
| Europe | 5 | 1/page | 1 | `chomage_europe`, `dette_deficit_europe`, `pib_europe`, `depenses_fonction_europe`, `depenses_publiques_europe` |

Classement thématique : le nôtre, à partir des descriptions et des producteurs [Cat]. Tableau complet en annexe A.

### 6.3 Champs du catalogue

Chaque jeu décrit dans `/v1/jeux` porte [Cat] :

| Champ | Contenu |
|---|---|
| `jeu` | Nom à passer à `interroger` |
| `description` | Contenu, périmètre, mises en garde |
| `source` | `{nom, url, licence, licence_url}` : ce qu'il faut citer |
| `sources_amont` | Sources primaires d'un jeu dérivé (ex. `rendements_impots` : PLF, PLFSS, Eurostat) |
| `colonnes` | Colonnes disponibles |
| `tris` | Colonnes de tri permises (la première par défaut) |
| `colonnes_longues` | Colonnes volumineuses (dispositif, exposé…) à n'inclure qu'au besoin |
| `recherche_plein_texte` | Booléen |
| `filtre_obligatoire_sur` | Colonnes dont une au moins doit être filtrée en `eq` ou `in` (2 jeux) |
| `colonnes_toujours_renvoyees` | Colonnes ajoutées d'office (Orcet : `version_modele`, `predit_le`…) |
| `colonne_mise_a_jour` | Colonne de date de mise à jour ligne par ligne |
| `prix` | « 1 crédit par page », « 5 crédits par page », « 50 crédits par prédiction renvoyée » |
| `limite_max` | Lignes par page au plus |
| `mode_emploi` | Filtres à poser, unités, pièges (89 jeux) |
| `verification` | `{verifiee_le, preuve, references}` (63 jeux) |

### 6.4 Filtres exacts requis

- Sur beaucoup de jeux statistiques, un total côtoie ses ventilations (par âge, sexe, territoire) ; ils exigent un filtre `eq` ou `in` sur chaque dimension, sinon l'appel est refusé sans être facturé [F:donnees-publiques, F:erreurs].
- Le champ structuré `filtre_obligatoire_sur` ne le dit que pour `votes` et `senat_votes` [Cat]. Pour les autres, l'exigence n'est écrite que dans `mode_emploi`. **Vérifié** : `chomage_europe` sans filtre (`filtre_obligatoire_sur: null`) est refusé, `400` « Filtre exact requis sur : geo ; unit ; s_adj ; age ; sex » [R 55].
- Les 32 jeux dont le mode d'emploi dit « filtre toujours » sont repérés dans l'annexe A (colonne « Filtre exact »).
- Plusieurs modes d'emploi renvoient à `valeurs_de` « pour la liste des valeurs » (comptes des collectivités, restes à charge) ; ce paramètre est refusé par l'API (« Arguments inconnus : valeurs_de. ») [Cat, R 56].

### 6.5 Jeux les plus utiles pour notre rapport

| Jeu | Pourquoi | Prix | Repère |
|---|---|---|---|
| `scrutins` | Tous les scrutins depuis 2012, avec `code_type_vote` (solennel, ordinaire…), `demandeur`, `nombre_votants`, recherche plein texte sur l'intitulé et l'exposé des amendements | 1/page de 200 | [Cat] |
| `votes` | Votes nominatifs, filtre obligatoire par scrutin, député ou groupe | 1/page de 200 | [Cat] |
| `amendements` | 54 colonnes : auteur, groupe, `sort_en_seance`, `mission_libelle_plf`, `soumis_article40`, discussions communes | 1/page de 200 | [Cat] |
| `actes` | Étapes de procédure d'un dossier (dépôt, commission, lectures, adoption) | 1/page | [Cat] |
| `documents` | Textes déposés (projets, propositions, rapports) avec auteur | 1/page | [Cat] |
| `reunions` / `senat_reunions` | Agenda et ordre du jour des deux chambres | 1/page | [Cat] |
| `senat_scrutins` | Scrutins du Sénat avec la liste des amendements concernés (`amendements`) | 1/page | [Cat] |
| `correspondance_textes` | Lien texte du Sénat ↔ texte de l'Assemblée (navette) | 5/page | [Cat] |
| `evenements_parlementaires` | Flux daté des dépôts, votes et étapes des 30 derniers jours | 5/page | [Cat] |
| `signaux_faibles` | Sujets dont les mentions parlementaires ou médiatiques montent (score 0 à 100) | 5/page | [Cat] |
| `representants_interets` | Répertoire HATVP (secteurs, dirigeants, tranche de dépenses, `maj_le`) | 1/page | [Cat] |
| `legifrance_lois_decrets` | Lois et décrets en vigueur, recherche plein texte | 1/page de 50 | [Cat] |
| `execution_budget_etat_mensuelle`, `series_marche` | Solde mensuel de l'État ; écart OAT-Bund et taux BCE | 1 et 5/page | [Cat] |

---

## 7. Les fiches `guide` (27 fiches et l'arborescence)

L'arborescence (4 239 caractères) regroupe les sujets en neuf entrées : outils ; suivre un texte ; analyser un vote ; exposition d'une entreprise ; prédire un vote (sous-fiche Orcet) ; données publiques ; agents et RAG (installer, exemples, démarrage rapide) ; automatisation (authentification, pagination, filtres, versions, identifiants) ; crédits et coûts (limites, clés) ; concepts (données, sources et licences, Marianne, cycle de vie) ; dépannage (erreurs) [MCP]. Toutes ont été lues le 14/11/2026, pour 0 crédit [MCP].

| Fiche | Ce qu'on y apprend d'utile |
|---|---|
| `outils` | Catalogue des 18 outils et de leur prix ; même coût que l'appel REST équivalent ; fiches aussi publiées en ressources MCP ; sujet inconnu → `-32602` ; jeux publics « lus à la source, sans copie » avec date de dernière publication ; filtres exacts (exemple `chomage_europe`) ; « compter plutôt qu'extrapoler » ; huit questions d'exemple. |
| `suivre-un-texte` | Ordre : `rechercher` → `lire_texte` → `interroger` → `lire_amendement` → `resultat_scrutin` ; script Python de veille quotidienne sur `/amendements?texte=…&depuis=…` avec curseur ; « une page de 100 amendements coûte 1 crédit ». Affirme à tort que chaque amendement mis aux voix porte l'identifiant de son scrutin [R 52]. |
| `analyser-un-vote` | `resultat_scrutin` (un vote précis, 1 crédit), `positions_groupes` (100 scrutins, 1 crédit), agrégats à 5 crédits calculés sur tout le périmètre ; chaque réponse rappelle les filtres, le nombre d'objets comptés et la définition. |
| `exposition-entreprise` | `POST /expositions` (1 000 crédits prévus) en préparation, `501` non facturé ; champs prévus `objet`, `impact` (fort, moyen, faible), `motif`, `sources` ; donnée calculée `calcule: true`. |
| `predire-un-vote` | `/amendements?texte=…&sort=en_attente`, puis `POST /orcet/predictions` par amendement (50 crédits ; `404` sans frais sans prédiction) ; présenter une estimation datée, avec la `confiance`. |
| `orcet` | Statut aperçu ; format de réponse (`modele`, `calcule`, `moyenne_probabilites_pour`, `definition`, `confiance`, `predit_le`) ; limites : votes individuels seulement, découpage d'évaluation aléatoire, Sénat non modélisé. |
| `donnees-publiques` | `lister_jeux` → `interroger` → `chercher_donnees_publiques` → `lire_donnees_publiques` ; filtre exact requis : REST `400` (en réalité `400` ou `422`, section 9), MCP `-32602`, non facturé. |
| `construire-un-agent` | MCP (l'agent choisit) ou RAG maison (`/recherche` puis lectures) ; faire citer `id` et `source` ; clé dédiée et plafond mensuel ; relire tout cache au moins une fois par jour. |
| `installer` | Configuration pour Claude, ChatGPT, Le Chat (OAuth), Cursor, VS Code, Claude Code (Bearer). |
| `exemples-agents` | Exemples complets : Claude, Claude Code, SDK Anthropic avec `mcp_servers`, client MCP Python, script REST sans dépendance ; filtres exacts de `chomage_europe` et `offres_emploi_france_travail`. |
| `demarrage-rapide` | Clé de test, première requête, forme d'une liste (`data`, `next_cursor`, `has_more`), en-têtes `X-Credits-*`, trois requêtes utiles. L'exemple montre `"numero": "1234"` (chaîne) ; en réalité un entier [R 03]. |
| `automatisation` | Zapier, Make, n8n ; exemple « scrutins du jour dans un tableur » (`GET /scrutins?legislature=17&limit=50` chaque jour à 20 h). |
| `authentification` | En-tête Bearer, `401`, bonnes pratiques (une clé par application, expiration, coffre de secrets, révocation immédiate, lecture seule). |
| `pagination` | `data`, `has_more`, `next_cursor`, `cursor` ; `limit` 1 à 100 (20 par défaut). Écrit « chaque page est facturée comme une recherche », alors qu'une page coûte 1 crédit et une recherche 2 [F:credits-et-limites, R 03]. |
| `filtres` | Filtres combinés par ET, valeurs séparées par des virgules lues comme un OU, dates ISO, « dates et heures en UTC » (démenti par les données de l'Assemblée, section 10), tri du plus récent au plus ancien. |
| `versions` | `Hemicycle-Version` ; sans en-tête, dernière version ; liste des changements compatibles ; une seule version, `2026-10-01`, en aperçu. |
| `identifiants` | Formats : texte `PIONANR5L17B0390`, dossier `DLR5L17N51234`, amendement `AMANR5L17PO59048B0390P0D1N000012`, scrutin `VTANR5L17V1234`, acteur `PA841605`, organe `PO59048`, mandat `PM842426`, entreprise (SIREN) ; identifiants officiels stables. |
| `credits-et-limites` | Barème complet ; liste des appels non facturés ; « une recherche ou une page qui aboutit sans résultat est facturée » ; 1 000 crédits offerts (valables 6 mois) ; crédits achetés valables 12 mois ; recharge dès 100 € HT ; `402` sans décompte. |
| `limites` | 300/min (lectures), 30/min (modèles), 100/jour (test), par organisation ; en-têtes `RateLimit-*` (non constatés) ; `429` avec `Retry-After`. |
| `cles` | `hmc_test_` / `hmc_live_` ; même base ; modèles fictifs `"exemple": true` en test ; étapes du passage en production. |
| `comprendre-hemicycle` | La base, deux modèles, deux accès ; organisation partagée avec Atlas et ses quatre rôles. |
| `donnees` | Champs de chaque objet (texte, dossier, amendement et ses sorts, scrutin, vote, acteur, organe, mandat) ; les points d'accès de lecture ne couvrent que l'Assemblée ; résultats de modèles marqués `calcule: true` et `modele`. |
| `sources-et-licences` | Tableau des sources et de leur couverture ; synchronisation nocturne ; objet `source` ; « Source : Hémicycle » pour les données calculées. |
| `marianne` | 50 crédits (200 en mode approfondi), `501` ; ne cite que des pièces de la base, `sans_source: true` quand rien ne fonde la réponse ; modèles de Mistral. |
| `cycle-de-vie` | Statuts Labs, aperçu, disponible, déprécié (appelable six mois après l'annonce), retiré ; tout est en aperçu ; champ `modele` versionné. |
| `depannage` | Adresse sans barre finale, préfixe `Bearer `, `401`, `402`, demander explicitement « Cherche dans Hémicycle… », clé de test = réponses fixes, `request_id` au support. |
| `erreurs` | Format `problem+json` (RFC 9457) ; table des codes ; filtre exact requis ; `402` avec `recharge_url` ; `429` avec `Retry-After` ; seules `429`, `500` et `503` se réessaient. |

**Évaluation d'Orcet** (présente sur la page de doc et la page `/modeles`, absente de la fiche) : sur 1 592 scrutins de l'Assemblée masqués pendant l'entraînement, Orcet v2 retrouve 84 % des votes individuels (190 004 sur 226 179) ; une règle simple de référence 56,8 %, un modèle de langage généraliste 51,8 % (mesurés sur un échantillon antérieur). Méthode : chaque député et chaque scrutin placés dans un espace à deux dimensions appris sur l'historique des votes (MIRT-2D) [Doc:modeles/orcet, Site:modeles].

---

## 8. Tarification et budget

### 8.1 Barème (tarif `2026-11-08`)

| Appel | Crédits | Équivalent en euros |
|---|---|---|
| Page d'une liste ou d'un jeu (`interroger`, `/scrutins`…) | 1 | 0,01 € |
| Lecture d'un objet (texte, amendement, scrutin, acteur, résultat d'un scrutin) | 1 | 0,01 € |
| Positions des groupes sur 100 scrutins au plus | 1 | 0,01 € |
| Recherche (base, entreprise, data.gouv.fr), lecture data.gouv.fr | 2 | 0,02 € |
| Page d'un jeu dérivé ; agrégat (`classement_auteurs`, `accord_groupes`, `loyaute_deputes`) | 5 | 0,05 € |
| Prédiction Orcet (`predire_vote` ou ligne d'un jeu Orcet) | 50 par prédiction renvoyée | 0,50 € |
| Marianne standard / approfondie (pas ouvert) | 50 / 200 | 0,50 € / 2 € |
| Exposition d'une entreprise (pas ouvert) | 1 000 | 10 € |
| Livrable rédigé (pas ouvert) | 2 500 | 25 € |
| Catalogue des jeux, solde, `guide` | 0 | — |

Sources : [F:credits-et-limites, Site:tarifs] ; 1 crédit = 0,01 € [R 01].

### 8.2 Ce qui n'est pas facturé

Erreurs serveur (`500`, `502`, `503`, `504`) et délais dépassés ; erreurs de validation (`400`) ; refus (`401`, `402`, `403`, `429`) ; objets introuvables (`404`) et prédictions indisponibles ; points d'accès en préparation (`501`) ; reprise d'un appel avec la même clé d'idempotence ; solde, catalogue, `guide` ; tout appel avec une clé de test [F:credits-et-limites]. **Vérifié** : `400`, `401`, `404`, `422`, `501` et le rejeu idempotent coûtent 0 [R 04 à R 09, R 28, R 33, R 38, R 40 à R 51, R 55, R 56].

**Facturé même vide** : « une recherche ou une page qui aboutit sans résultat est facturée » [F:credits-et-limites] ; **vérifié** : 2 crédits pour une recherche vide [R 17], 1 crédit pour une liste vide [R 22].

### 8.3 Offre commerciale

- 1 000 crédits offerts une fois par compte (après vérification de l'adresse électronique), valables six mois ; crédits achetés valables douze mois [F:credits-et-limites].
- Recharge à partir de 100 € HT ; recharge automatique désactivée par défaut, avec seuil, montant et plafond mensuel [F:credits-et-limites].
- Formules mensuelles : 300 €, 1 000 € ou 3 000 € HT par mois, en crédits ; offre Entreprise à partir de 24 000 € HT par an, avec « volume engagé, licence de rediffusion, engagement de service » [Site:tarifs].
- Atlas (abonnement annuel) : à partir de 720 € HT par mois [Site:tarifs].

### 8.4 Coût de questions types

| Question | Appels | Coût |
|---|---|---|
| « Comment chaque groupe a-t-il voté sur tel scrutin ? » | 1 `resultat_scrutin` | 1 crédit |
| « Position des groupes sur les 100 derniers scrutins » | 1 `/scrutins?limit=100` + 1 `positions_groupes` | 2 crédits |
| « Quels groupes votent le plus ensemble ce mois-ci ? » | 1 `accord_groupes` | 5 crédits |
| « Qui s'écarte le plus de son groupe ? » | 1 `loyaute_deputes` (ou une par groupe) | 5 crédits (55 pour 11 groupes) |
| « Qui dépose le plus d'amendements sur le PLF ? » | 1 `classement_auteurs` (texte) | 5 crédits |
| « Trouver un texte et lire ses 300 amendements » | 1 `rechercher` + 2 pages `interroger amendements` de 200 | 4 crédits |
| « Scrutins du mois » (≈ 400 scrutins) | 4 pages `/scrutins` de 100, ou 2 pages du jeu `scrutins` de 200 | 2 à 4 crédits |
| « Participation de chaque député sur le mois » | `votes` filtré par scrutin (`in`, 100 valeurs) : environ 40 000 lignes / 200 | ≈ 200 crédits (2 €) |
| « Prédiction d'Orcet sur 20 amendements » | 20 `predire_vote` ou 1 page `orcet_predictions` | 1 000 crédits (10 €) |

Estimations à partir du barème ; volumes mensuels supposés.

### 8.5 Pièges coûteux

1. **Orcet** : 50 crédits par prédiction **renvoyée** ; une page des jeux `orcet_predictions` ou `orcet_previsions_votes` (20 lignes au plus) peut coûter 1 000 crédits [Cat, Spec]. Un filtre trop large sur ces jeux est la seule façon de dépenser 10 € en un appel.
2. **Jeux dérivés** : 5 crédits par page, même pour une page de 3 lignes [Cat, Équipe : `credits.dus = 5`].
3. **Pagination** : chaque page est facturée ; un parcours complet d'un gros jeu (2,4 millions de votes) est hors de portée sans filtre [Cat].
4. **Résultats vides facturés** [R 17, R 22].
5. **Paramètre mal orthographié** sur un `GET` : ignoré, la requête part sans le filtre et elle est facturée [R 34].
6. **Agrégats appelés groupe par groupe** : 5 crédits chacun.

---

## 9. Erreurs, sources et citation

### 9.1 Format des erreurs

Format `application/problem+json` (RFC 9457) : `type` (URL `https://hemicycle.ai/docs/erreurs#<code>`), `title`, `status`, `detail`, `request_id` ; `402` ajoute `recharge_url` [F:erreurs]. **Vérifié** sur 18 erreurs : les cinq champs sont toujours là ; **le champ `errors` annoncé pour les `400` n'apparaît jamais** [R 04 à R 56].

| Statut | Code (`type`) | Documenté | Constaté |
|---|---|---|---|
| 400 | `parametre-invalide` | Paramètre manquant ou mal formé | `limit` hors bornes, curseur illisible, jeu inconnu, argument inconnu, filtre exact manquant (`chomage_europe`), corps vide des agrégats [R 04, R 06, R 33, R 41 à R 45, R 50, R 55, R 56] |
| 400 | `version-inconnue` | Non documenté | `Hemicycle-Version` inconnue [R 28] |
| 401 | `cle-invalide` | Clé absente ou invalide | Sans clé [R 08] |
| 402 | `credits-insuffisants` | Solde insuffisant | Non testé |
| 403 | `droits-insuffisants` | Clé sans accès | Non testé |
| 404 | `introuvable` | Aucun objet | Identifiant inexistant [R 05] |
| 404 | (même `type`, titre « Point d'accès inconnu ») | Non documenté | Route inconnue ou mauvaise méthode [R 40, R 51, R 53] |
| 422 | `requete-refusee` | **Non documenté** | `votes` sans filtre ; data.gouv.fr sans mots-clés ou sans fichier valide [R 07, R 46, R 47] |
| 429 | `trop-de-requetes` | Avec `Retry-After` | Non testé |
| 501 | `non-ouvert` | Point d'accès en préparation | Marianne, expositions, livrables [R 09, R 48, R 49] |
| 500, 503 | `erreur-serveur`, `indisponible` | Réessayer | Non rencontré |

Règle de reprise : seules `429`, `500` et `503` justifient une nouvelle tentative, avec un délai croissant (1 s, 2 s, 4 s…) [F:erreurs]. Avec `Idempotency-Key`, la reprise d'un appel déjà servi est gratuite [R 38].

### 9.2 L'objet `source`

| Où | Forme | Licence affichée | URL | Repère |
|---|---|---|---|---|
| Scrutin | `{editeur, url, licence}` | Licence Ouverte 2.0 | Page lisible `…/dyn/17/scrutins/9807` | [R 03] |
| Acteur | `{editeur, url, licence}` | Licence Ouverte 2.0 | Page lisible `…/dyn/deputes/PA795778` | [R 25] |
| Texte, dossier, organe | `{editeur, url, licence}` | Licence Ouverte 2.0 | **Fichier JSON open data** `…/dyn/opendata/<id>.json` | [R 24, R 29, R 32] |
| Amendement | `{editeur, url, licence}` | Licence Ouverte 2.0 | **Chemin relatif** `/base/<id>?format=pdf` | [R 52] |
| Jeu (`interroger`) | `{nom, url, licence, licence_url}` + `sources_amont` | Licence Ouverte (Etalab), etc. | Portail du producteur | [R 20] |
| Agrégat | `{nom, url, licence, licence_url}` | Licence Ouverte (Etalab) | Portail du producteur | [R 21] |

### 9.3 Licences des 132 jeux

| Licence | Jeux |
|---|---|
| Licence Ouverte v2.0 (Etalab) | 79 |
| Licence Ouverte (Etalab) | 14 |
| « Tous usages, avec mention de la source « Hémicycle » » | 11 (jeux dérivés et Orcet) |
| Information publique, réutilisation avec mention de la source | 7 |
| Licence du portail data.senat.fr | 6 |
| CC BY 4.0, avec mention d'Eurostat | 4 |
| Banque de France (mention de la source, du portail Webstat et de la date de mise à jour) | 4 |
| Réutilisation autorisée avec mention d'Eurostat | 2 |
| **Conditions de réutilisation non confirmées** (`senat_reunions`, `senat_collaborateurs`) | 2 |
| Licence Ouverte (Etalab) de FranceAgriMer ; CC BY 4.0 (Parlement européen) ; Licence Ouverte v1.0 | 1 chacune |

Source : [Cat].

### 9.4 Règles de citation pour le rapport mensuel

- Donnée publique brute : citer l'éditeur d'origine et la licence de l'objet `source` (« Source : Assemblée nationale, Licence Ouverte ») [F:sources-et-licences].
- Donnée calculée par Hémicycle (agrégats, positions majoritaires, signaux faibles, prédictions, jeux dérivés) : « Source : Hémicycle » [F:sources-et-licences, Cat].
- Prédiction d'Orcet : « estimation datée » (avec `predit_le` et `confiance`), jamais un résultat [F:orcet, F:predire-un-vote].
- Banque de France : ajouter le portail Webstat et la date de mise à jour [Cat]. FranceAgriMer : citer « FranceAgriMer, RNM », avec la date [Cat].
- Pour le lecteur, préférer une URL lisible à l'URL JSON ou relative (section 10, points 13 et 14).

---

## 10. Pièges et limites constatés

1. **`predire_vote` n'est pas une probabilité d'adoption** : c'est la moyenne des probabilités individuelles de voter pour [F:orcet, MCP, Cat]. La page `/modeles` écrit pourtant qu'Orcet « en déduit le décompte attendu par groupe et la probabilité d'adoption » [Site:modeles] : contradiction interne.
2. **Orcet hors Sénat** et évalué sur des votes masqués tirés au hasard, pas en conditions réelles avant le vote [F:orcet].
3. **`/recherche` ne trouve pas les scrutins**, contrairement à la référence [R 17, Spec].
4. **Ordre des scrutins** : date décroissante, numéro croissant dans la journée ; le premier élément n'est pas le dernier scrutin tenu [R 03, R 11, R 12].
5. **`/scrutins/{id}` sans détail par groupe** [R 13] ; **`/textes/{id}` et `/dossiers/{id}` sans étapes, auteurs ni rapporteurs** [R 29, R 32] ; **`/amendements/{id}` sans scrutin** [R 52] ; **`/acteurs/{id}` sans « activité récente »** [R 30] ; **`/credits` sans consommation du mois** [R 01]. La référence annonce tout cela [Spec].
6. **Pas de lien structuré amendement → scrutin à l'Assemblée** : le jeu `amendements` n'a pas de colonne de scrutin [Cat] ; le lien passe par l'intitulé du scrutin (« l'amendement n° 3 de M. … ») [R 03]. Au Sénat, `senat_scrutins` porte une colonne `amendements` [Cat].
7. **`/scrutins/{id}/votes` ignore `limit`**, n'est pas paginé et ne donne pas les noms ; `/resultat` donne les noms pour le même prix [R 14, R 15].
8. **Curseur = décalage** encodé (`{"o":N}`) : si la base change pendant un parcours, des doublons ou des trous sont possibles, contrairement à ce qu'affirme [F:pagination] (supposé, la mise à jour étant nocturne) [R 03, R 12].
9. **`depuis` sur `/amendements`** semble porter sur la date de dépôt, pas sur la date du sort [R 22, R 35] (à confirmer).
10. **Paramètres inconnus ignorés** sur les `GET` (et facturés) [R 34] ; refusés sur `POST /jeux/interroger` [R 56].
11. **Filtres exacts non déclarés** dans `filtre_obligatoire_sur` mais appliqués (`chomage_europe`) : lire `mode_emploi` [Cat, R 55].
12. **Codes d'erreur hétérogènes** : un filtre manquant donne `422` (`votes`) ou `400` (`chomage_europe`) ; la doc ne prévoit que `400` [R 07, R 55, F:erreurs].
13. **URL de source = fichier JSON** pour les textes, dossiers et organes [R 24, R 29, R 32]. Notre serveur reconstruit déjà une URL lisible pour les textes (`…/dyn/17/textes/l17b<numéro>_<genre>`).
14. **URL de source relative** pour les amendements (`/base/<id>?format=pdf`) : inutilisable telle quelle [R 31, R 35, R 52].
15. **Deux formes de `source`** (`editeur` dans les objets, `nom` + `licence_url` dans les jeux et agrégats), et deux libellés de licence pour la même source (« Licence Ouverte 2.0 » / « Licence Ouverte (Etalab) ») [R 03, R 20, R 21].
16. **Fuseaux horaires** : la doc dit UTC [F:filtres] ; l'Assemblée publie en heure de Paris (`+01:00`) [R 29, R 31] ; le Sénat en UTC : une séance de l'après-midi du 20/11 commence à `2026-11-19T23:00:00+00:00` dans `senat_reunions` (minuit heure de Paris) ; extraire la date sans conversion donne la veille [Équipe : échantillon `senat_reunions`].
17. **Types incohérents** : `numero` entier pour un scrutin, chaîne pour un amendement (`"CF99"`) ; `legislature` en chaîne (`"17"`) dans les objets, entier en paramètre ; `legislature: null` pour un texte du Sénat [R 03, R 16, R 52].
18. **`auteur` d'un texte peut être un organe** (`PO838901`) ; amendements du Gouvernement sans `auteur` ni `groupe` ; `dispositif` parfois `null` [R 26, R 31, R 52].
19. **Volumes** : un amendement pèse jusqu'à 12 Ko, un `resultat_scrutin` à 577 votants plusieurs dizaines de Ko : à compacter avant de les passer à un modèle de langage [R 31, R 14, Équipe].
20. **`/organes` mélange toutes les législatures** et n'a pas de lecture unitaire [R 24, R 53] ; **`/acteurs?nom=`** renvoie aussi d'anciens députés [R 25].
21. **Positions majoritaires** : à égalité, sans vote exprimé ou sur une motion de censure (seuls les « pour » sont recensés), la position vaut `null` ; ce n'est « ni une consigne de vote ni l'unanimité du groupe » [R 21]. Loyauté : hors non-inscrits et motions de censure, `min_votes` 20 par défaut [MCP].
22. **Une page partielle ne permet aucun total** (budget vert, prestations de solidarité) ; beaucoup de jeux mêlent totaux et ventilations [Cat, F:donnees-publiques].
23. **`evenements_parlementaires` ne garde que 30 jours** : à archiver chaque mois [Cat].
24. **Légifrance : textes en vigueur à la date du jour** seulement [Cat].
25. **Débats et presse** annoncés dans la base mais non exposés par un jeu ou un point d'accès vérifié [Cat, Spec, R 17].
26. **Clé de test** : réponses fixes des modèles (`"exemple": true`) ; ne jamais publier un chiffre d'Orcet obtenu avec une clé de test [F:cles].
27. **Aucun en-tête `RateLimit-*`** : un client ne peut pas anticiper un `429` ; il faut le gérer à réception [R 01 à R 56].
28. **Fraîcheur inégale** : dernier texte déposé au 05/11, dernier scrutin au 12/11 (le 14/11) [R 26, R 12].
29. **Tout est en aperçu** : la forme des réponses peut changer, annoncée dans le changelog [F:cycle-de-vie]. Le code doit ignorer les champs inconnus [F:versions].
30. **Licences « non confirmées »** pour `senat_reunions` et `senat_collaborateurs` [Cat].

---

## 11. Opportunités pour notre rapport mensuel

Coûts estimés pour un mois de session ordinaire (volumes supposés : 300 à 500 scrutins à l'Assemblée, quelques milliers d'amendements). Les outils MCP ont le même coût.

| Indicateur ou angle | Comment | Coût estimé |
|---|---|---|
| **Activité du mois à l'Assemblée** : nombre de scrutins, adoptés/rejetés, solennels | Jeu `scrutins`, filtres `date_scrutin` `gte`/`lte`, colonnes `uid`, `date_scrutin`, `code_type_vote`, `sort_code`, `nombre_votants`, `demandeur` (200 par page) ; ou `GET /scrutins?depuis=…` (100 par page, sans borne de fin) | 2 à 5 |
| **Comment les groupes ont voté** sur les scrutins solennels ou sur un texte phare | `positions_groupes` par lots de 100 scrutins | 1 par lot |
| **Qui vote avec qui** (matrice d'accord entre groupes), comparée au mois précédent | `accord_groupes` avec `depuis`/`jusqu_a` ; variante `types: ["SPS"]` | 5 par période |
| **Discipline de groupe**, « frondeurs » du mois | `loyaute_deputes` sur le mois (médiane et moins loyaux) ; par groupe avec `groupe` | 5 (+5 par groupe) |
| **Les plus gros déposants d'amendements** et leur taux d'adoption en séance | `classement_auteurs` sur la période (un an au plus) ou sur un texte (`texte`) ; `exclure_rapporteurs` | 5 |
| **Sort des amendements par groupe** | Jeu `amendements`, filtres `date_depot`, colonnes `groupe_politique_ref`, `sort_en_seance`, `soumis_article40` | ≈ 1 par 200 amendements |
| **Participation au vote**, député par député | Jeu `votes` filtré par `scrutin_ref` (`in`, 100 valeurs) ; « non-votant » n'est pas « absent » | ≈ 200 |
| **Textes déposés** (projets, propositions, rapports) | Jeu `documents`, filtre `date_depot` | 1 à 2 |
| **Parcours des lois** : étapes franchies dans le mois | Jeu `actes`, filtre `date_acte` ; `evenements_parlementaires` (30 jours) | 1 à 3 ; 5 par page |
| **Navette** Assemblée ↔ Sénat | `correspondance_textes`, `senat_dossiers` | 5 + 1 |
| **Le Sénat dans le mois** | `senat_scrutins` (avec amendements liés), `senat_amendements` (avis de la commission et du Gouvernement) | 1 à 5 |
| **Agenda du mois suivant** | `reunions` (Assemblée), `senat_reunions` (horodatages UTC) | 1 à 2 |
| **Lois et décrets publiés** | `legifrance_lois_decrets` (recherche plein texte, 50 par page) | 1 à 3 |
| **Lobbying** : organisations nouvellement inscrites ou mises à jour, par secteur | `representants_interets`, filtre `maj_le` `gte` | 1 à 2 |
| **Sujets montants** au Parlement et dans les médias | `signaux_faibles` (score d'intensité 0 à 100, pas une probabilité ; « Source : Hémicycle ») | 5 |
| **Saison budgétaire** : crédits par mission, dépenses fiscales, articles visés par les amendements du PLF | `budget_credits`, `depenses_fiscales`, `amendements_budget_articles` | 1 à 5 par page |
| **Le prix de la politique** : écart OAT-Bund, solde mensuel de l'État | `series_marche`, `execution_budget_etat_mensuelle` | 5 + 1 |
| **Contexte social** : chômage (France, régions, Europe), offres d'emploi | `demandeurs_emploi_regions`, `offres_emploi_france_travail`, `chomage_europe` (filtres exacts) | 1 par jeu |
| **Contexte territorial** pour illustrer un débat (logement, sécurité, collectivités) | Jeux `communes_sru`, `delinquance_departements`, `comptes_communes`, etc. | 1 par jeu |
| **Orcet face au réel** (prédictions et résultat constaté) | `orcet_predictions` (colonnes `resultat_adopte`, `resolu_le`) : coûteux | 50 par ligne |

**Budget mensuel indicatif** : 40 à 80 crédits pour le socle (scrutins, positions, accord, loyauté, classement, textes, Sénat, agenda, lobbying, signaux, contexte), soit 0,40 à 0,80 € ; 200 à 300 crédits de plus avec la participation député par député. Pour le traitement mensuel, l'API REST est plus pratique que le MCP : coût dans `X-Credits-Cost`, reprise gratuite avec `Idempotency-Key`, pagination simple.

---

## 12. Écarts avec notre code et notre mémo

### 12.1 `ROUTES_REST` (`backend/chatbot/veille.py`)

**Méthodes et chemins : aucun écart.** Les 17 couples (méthode, chemin) de `ROUTES_REST` existent tels quels le 14/11/2026 :

| Outil MCP | Route de `ROUTES_REST` | Vérification | Paramètres confirmés |
|---|---|---|---|
| `rechercher` | `GET /v1/recherche` | 200 [R 16] | `q`, `types` (virgules), `limit` ; `cursor` existe aussi |
| `lire_texte` | `GET /v1/textes/{id}` | 200 [R 29] | `id` en chemin |
| `lire_amendement` | `GET /v1/amendements/{id}` | 200 [R 52] | `id` en chemin |
| `lire_scrutin` | `GET /v1/scrutins/{id}` | 200 [R 13] | `id` en chemin |
| `resultat_scrutin` | `GET /v1/scrutins/{id}/resultat` | 200 [R 14] | `id` en chemin |
| `lire_acteur` | `GET /v1/acteurs/{id}` | 200 [R 30] | `id` en chemin |
| `positions_groupes` | `POST /v1/agregats/positions-groupes` | 200 [R 21] | corps `scrutins` |
| `accord_groupes` | `POST /v1/agregats/accord-groupes` | 400 spécifique [R 41] | `depuis`, `legislature` cités par l'erreur |
| `loyaute_deputes` | `POST /v1/agregats/loyaute-deputes` | 400 spécifique [R 42] | `depuis`, `legislature` cités par l'erreur |
| `classement_auteurs` | `POST /v1/agregats/classement-auteurs` | 400 spécifique [R 43] | texte, recherche, `depuis` cités par l'erreur |
| `lister_jeux` | `GET /v1/jeux` | 200 [R 02] | aucun |
| `interroger` | `POST /v1/jeux/interroger` | 200 [R 20] | `jeu`, `recherche`, `colonnes`, `tri`, `limite` ; `filtres` [R 55] |
| `chercher_entreprise` | `GET /v1/entreprises` | 400 spécifique [R 45] | `q` cité par l'erreur ; `page` [Spec] |
| `chercher_donnees_publiques` | `GET /v1/donnees-publiques` | 422 spécifique [R 46] | `q` [Spec] |
| `lire_donnees_publiques` | `POST /v1/donnees-publiques/lecture` | 422 spécifique [R 47] | `fichier`, `filtres`, `tri`, `ordre`, `lignes` [Spec] |
| `predire_vote` | `POST /v1/orcet/predictions` | 400 spécifique [R 44] | `amendement` cité par l'erreur |
| `solde_credits` | `GET /v1/credits` | 200 [R 01] | aucun |

Une route inconnue répondrait `404` « Point d'accès inconnu » [R 40] : un `400`/`422` propre à la route prouve qu'elle existe.

**Corrections à faire** (aucune n'est bloquante) :

1. **Correspondance vérifiée** : l'hypothèse « mêmes noms de paramètres qu'en MCP » (`q`, `types`, `limit` en requête ; noms des arguments dans les corps) est confirmée le 14/11/2026 [R 16, R 20, R 21, R 41 à R 47]. La mise en garde « NON vérifiée » qui l'accompagnait ne figure plus dans `veille.py` à 15 h UTC ; si elle subsiste ailleurs (brief, documentation), elle peut être retirée.
2. **`guide`** n'a pas d'équivalent REST : le repli actuel (`MCP /mcp · guide`) est juste. Option : afficher la page Markdown publique `https://hemicycle.ai/docs-md/<page>.md` ; attention, les noms diffèrent (`credits-et-limites` → `credits`, `sources-et-licences` → `provenance`, `comprendre-hemicycle` → `concepts`, `suivre-un-texte` → `guides/veille-texte`, `predire-un-vote` → `guides/prediction`, `orcet` → `modeles/orcet`…) [Doc:llms].
3. **`requete_rest`** : le commentaire « `url` contient la version encodée » renvoie à une clé `url` que la fonction ne renvoie pas, et `urlencode` est importé sans être utilisé (`veille.py`, lignes 26 et 80). Cosmétique.
4. **Description de `rechercher`** côté catalogue : ne pas promettre de scrutins ni d'acteurs (section 4.3.13) [R 17].
5. **Option** : l'outil local `derniers_scrutins` est rattaché au jeu `scrutins` (`veille.py`, ligne 718), donc affiché comme `POST /v1/jeux/interroger · scrutins`, ce qui est exact. `GET /v1/scrutins?depuis=…` est une alternative sans recherche plein texte et sans borne de fin [Spec, R 12].

Contrôle complémentaire : les colonnes, tris et jeux de `SPECS_JEUX` existent tous dans le catalogue (12 spécifications, 13 jeux) ; les `limite_max` de nos spécifications (20 à 40) restent sous les maximums des jeux [Cat]. Le barème `COUTS_CREDITS` de `hemicycle_tools.py` est conforme à [F:credits-et-limites].

### 12.2 `docs/API_HEMICYCLE.md`

| Section du mémo | Ce qu'il dit | Correction proposée | Repère |
|---|---|---|---|
| Ce que contient Hémicycle | Débats et presse dans la liste des sources | Préciser : présents dans la base Hémicycle, non exposés par l'API (aucun jeu, recherche non vérifiée) | [Cat, R 17] |
| Endpoints, Données parlementaires | `GET /recherche` sans précision | Préciser : textes, dossiers et amendements de l'Assemblée ; pas de scrutins ; 2 crédits même sans résultat ; accepte `cursor` | [R 16, R 17, R 36] |
| Endpoints | `GET /scrutins/{id}` « Scrutins » | Préciser : décompte global seulement ; détail par groupe via `/resultat` ou `positions-groupes` | [R 13] |
| Endpoints | `GET /scrutins/{id}/votes` | Préciser : tous les votes en une réponse, sans pagination ni nom | [R 15] |
| Endpoints | `GET /organes` | Préciser : paramètre `type`, toutes législatures mêlées ; pas de `GET /organes/{id}` | [R 24, R 53] |
| Endpoints, Modèles IA | Orcet et Marianne seulement | Ajouter `POST /expositions` (1 000) et `POST /livrables` (2 500), en `501` comme Marianne | [Spec, R 48, R 49] |
| Lien OpenAPI | « Spécification OpenAPI : /docs/openapi » | Préciser : fichier généré dans le navigateur (bouton de téléchargement), pas d'URL statique ; tous les paramètres typés `string` ; pages Markdown sous `/docs-md/` et `/llms.txt` | [Spec, Doc:llms] |
| Pagination | `limit` 1 à 100, curseur, chaque page facturée | Ajouter : curseur = décalage encodé ; ordre des scrutins (date décroissante, numéro croissant dans la journée) ; `/votes` non paginé ; jeux paginés par `decalage` | [R 03, R 11, R 15, R 20] |
| Erreurs | Codes 400 à 503, champ `errors` | Ajouter `422` `requete-refusee` (filtre obligatoire manquant, data.gouv.fr) et `400` `version-inconnue` ; route inconnue = `404` ; le champ `errors` n'existe pas ; les erreurs portent `X-Credits-Cost: 0` mais pas `X-Credits-Remaining` | [R 07, R 28, R 40, R 04] |
| Limites de débit | En-têtes `RateLimit-Remaining`, `RateLimit-Reset` | Ces en-têtes ne sont **pas** renvoyés ; ajouter `X-Request-Id`, `X-Operation-Id`, `X-Tarif-Version` ; idempotence par `Idempotency-Key` (rejeu gratuit, `Idempotent-Replayed: true`) | [R 01, R 37, R 38] |
| Authentification | `Hemicycle-Version` fixé à `2026-10-01` | Ajouter : sans en-tête, la dernière version s'applique ; version inconnue → `400` | [R 27, R 28] |
| Sources et citation | `source` = éditeur, URL, licence | Ajouter : URL relative pour les amendements ; JSON pour textes, dossiers, organes ; forme `{nom, url, licence, licence_url}` pour les jeux et agrégats | [R 20, R 21, R 52] |
| Serveur MCP, tableau des outils | `interroger` : `limite` (≤ 200) | Le maximum dépend du jeu : 200, 100, 50, 20 (Orcet) ou 5 | [Cat] |
| Serveur MCP | — | Ajouter : 27 ressources `hemicycle://guide/<sujet>` ; pas de prompts | [MCP] |
| (absent) | — | Ajouter : paramètres inconnus ignorés et facturés sur les `GET`, refusés sur `POST /jeux/interroger` ; filtres exacts à lire dans `mode_emploi` (`chomage_europe` refusé sans eux) | [R 34, R 55, R 56] |
| Compte (`GET /credits`) | « Consulter le solde » | Corps réel : `{solde, unite, valeur_eur}` ; pas de consommation du mois | [R 01] |

Points du mémo **confirmés** : base URL, en-têtes, coûts, `limit` 1 à 100, format `problem+json`, `1 crédit = 0,01 €`, `_meta` côté MCP, identifiants, couverture déclarée [R, F].

---

## 13. Questions ouvertes

1. **Débit** : les limites (300/min, 30/min) sont-elles appliquées alors qu'aucun en-tête `RateLimit-*` n'est renvoyé ? Nous n'avons pas provoqué de `429`.
2. **Recherche** : `/recherche` couvre-t-elle les acteurs et la presse, comme l'annonce la référence ? Quels sont les `types` acceptés (`acteur`, `presse`…) ? Le type `scrutin` ne renvoie rien [R 17].
3. **Débats et presse** : existe-t-il un accès API aux comptes rendus et aux 620 médias, ou sont-ils réservés à Atlas ?
4. **Fraîcheur des textes** : pourquoi aucun texte déposé après le 05/11 alors que les scrutins vont jusqu'au 12/11 et les actes jusqu'au 13/11 [R 26, R 12] ?
5. **Scrutins du 13/11** : absents, alors qu'une séance s'est tenue ce jour-là ; absence de scrutin public ou délai d'indexation ?
6. **`depuis` sur `/amendements`** : date de dépôt seulement, ou aussi date de modification du sort [R 22, R 35] ?
7. **Lien amendement → scrutin** promis par [F:suivre-un-texte] et [Spec] : prévu, ou à reconstruire depuis l'intitulé du scrutin ?
8. **URL des amendements** (`/base/<id>?format=pdf`) : sur quel hôte ? Probablement `https://www.assemblee-nationale.fr/dyn/opendata/…` ou une page d'Hémicycle ; à confirmer avec l'éditeur.
9. **Rediffusion** : l'offre Entreprise mentionne une « licence de rediffusion » [Site:tarifs] ; un rapport mensuel public qui cite les données sous leurs licences (Etalab, « Tous usages, avec mention de la source « Hémicycle » ») en a-t-il besoin ?
10. **Orcet** : « moyenne des probabilités de voter pour » [F:orcet] ou « probabilité d'adoption » [Site:modeles] ? Quels amendements ont une prédiction (couverture) ? Non testé (50 crédits).
11. **`valeurs_de`** cité par plusieurs modes d'emploi mais refusé : paramètre à venir, ou propre au MCP ?
12. **Codes `400` / `422`** pour un filtre manquant : lequel fera foi dans la version stable ?
13. **Nos deux clés** (`HEMICYCLE_API_KEY`, `HEMICYCLE_MCP_KEY`) partagent-elles bien le solde de la même organisation ? Les soldes observés le suggèrent.
14. **Licences « non confirmées »** de `senat_reunions` et `senat_collaborateurs` : peut-on citer ces données dans une publication ?
15. **Consommation par clé** : annoncée « dans une prochaine version » [F:credits-et-limites] ; d'ici là, suivre `X-Credits-Cost` et `_meta.credits_cost` de notre côté.

---

## Annexe A : les 132 jeux de données

Source : `GET /v1/jeux` du 14/11/2026 [R 02], identique à `lister_jeux` [Cat]. Prix : « 1/page » = 1 crédit par page ; « 5/page » = 5 crédits par page (jeu dérivé) ; « 50/prédiction » = 50 crédits par ligne renvoyée. Colonne « Filtre exact » : « oui (catalogue) » = champ `filtre_obligatoire_sur` ; « mode d'emploi : « filtre toujours » » = exigence écrite seulement dans `mode_emploi` (appliquée par l'API au moins pour `chomage_europe` [R 55]). Thèmes : classement de l'équipe.

| N° | Jeu | Thème | Source | Prix | Plein texte | Filtre exact | Max/page | Description (extrait) |
|---|---|---|---|---|---|---|---|---|
| 1 | `scrutins` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | oui |  | 200 | Scrutins publics de l'Assemblée depuis la 14e législature : objet, type de vote, majorité, sort et décompte. La recherche porte sur l'intitulé et sur l'exposé des … |
| 2 | `votes` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non | oui (catalogue) : scrutin_ref, acteur_ref, groupe_ref | 200 | Vote de chaque député à chaque scrutin (pour, contre, abstention, non-votant), avec son groupe. 2,4 millions de lignes : un filtre « eq » ou « in » sur le scrutin, le … |
| 3 | `amendements` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | oui |  | 200 | Amendements déposés à l'Assemblée : auteur, groupe, cosignataires, article visé, dispositif, exposé sommaire, sort, discussions communes et identiques. Pour chercher un … |
| 4 | `dossiers` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | oui |  | 200 | Dossiers législatifs de l'Assemblée : titre, procédure, initiateur. |
| 5 | `actes` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Actes de procédure d'un dossier : dépôts, saisines de commission, nominations de rapporteurs, lectures, adoptions. |
| 6 | `documents` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | oui |  | 200 | Documents parlementaires : projets et propositions de loi, rapports, avis, avec leurs auteurs. |
| 7 | `articles_textes` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | oui |  | 200 | Articles des textes de loi, un par un : désignation, titre, dispositif et exposé. |
| 8 | `textes_moissonnes` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Inventaire du moissonnage des textes : statut « ok » (articles lus), « sans_article » ou « absent », et nombre d'articles. Ce n'est pas le texte lui-même : il est dans … |
| 9 | `organes` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Organes : commissions, groupes politiques, délégations, missions. |
| 10 | `mandats` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Mandats : appartenance de chaque député à chaque organe, avec sa qualité et ses dates. |
| 11 | `reunions` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Séances et réunions de commission de l'Assemblée, avec leur ordre du jour. |
| 12 | `deputes` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Députés et anciens députés : identité, profession, catégorie socioprofessionnelle, lien HATVP. Année de naissance seule, sans adresse électronique. |
| 13 | `deputes_en_exercice` | Parlement : Assemblée nationale | Assemblée nationale | 1/page | non |  | 200 | Députés en exercice avec leur groupe politique. |
| 14 | `senat_scrutins` | Parlement : Sénat | Sénat, portail data.senat.fr | 1/page | non |  | 200 | Scrutins publics du Sénat depuis octobre 2023, avec leur décompte (base DOSLEG). |
| 15 | `senat_votes` | Parlement : Sénat | Sénat, portail data.senat.fr | 1/page | non | oui (catalogue) : scrutin_id, matricule | 200 | Vote de chaque sénateur à chaque scrutin. Un filtre « eq » ou « in » sur le scrutin ou le sénateur est obligatoire. |
| 16 | `senat_amendements` | Parlement : Sénat | Sénat, portail data.senat.fr | 1/page | oui |  | 200 | Amendements déposés au Sénat (base AMELI) : auteur, groupe, dispositif, objet, sort, avis de la commission et du Gouvernement. |
| 17 | `senat_dossiers` | Parlement : Sénat | Sénat, portail data.senat.fr | 1/page | oui |  | 200 | Dossiers législatifs du Sénat (base DOSLEG), avec le lien vers le dossier de l'Assemblée. |
| 18 | `senat_textes` | Parlement : Sénat | Sénat, portail data.senat.fr | 1/page | non |  | 200 | Textes déposés ou adoptés au Sénat. |
| 19 | `correspondance_textes` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Correspondance établie par Hémicycle entre un texte du Sénat et le texte de l'Assemblée. |
| 20 | `senat_reunions` | Parlement : Sénat | Sénat, agenda.senat.fr | 1/page | non |  | 200 | Séances et réunions du Sénat, avec leur ordre du jour. « public » décrit l'ouverture de la réunion au public. |
| 21 | `senateurs` | Parlement : Sénat | Sénat, portail data.senat.fr | 1/page | non |  | 200 | Sénateurs : identité, groupe, commission, circonscription, profession. Année de naissance seule, sans adresse électronique. |
| 22 | `senat_collaborateurs` | Parlement : Sénat | Sénat, liste des collaborateurs publiée sur senat.fr | 1/page | non |  | 200 | Collaborateurs des sénateurs : nom, prénom, qualité et sénateur employeur. « edition » est la date de la liste publiée. |
| 23 | `representants_interets` | Influence et autres élus | HATVP, répertoire des représentants d'intérêts | 1/page | non |  | 200 | Organisations inscrites au répertoire des représentants d'intérêts : catégorie, secteurs, domaines, tranche de dépenses, dirigeants déclarés (adresses électroniques … |
| 24 | `budget_credits` | Budget de l'État et finances publiques | Gouvernement, projet de loi de finances | 1/page | non |  | 200 | Crédits par mission et programme en euros, autorisations d'engagement et crédits de paiement : états B des PLF 2025 à 2027, états C et D du PLF 2027, et colonne LFI … |
| 25 | `budget_recettes_etat` | Budget de l'État et finances publiques | Gouvernement, projet de loi de finances | 1/page | non |  | 200 | Recettes du budget général de l'État en euros, ligne par ligne : état A du PLF 2027. |
| 26 | `secu_equilibres` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, projet de loi de financement de la sécurité … | 1/page | non |  | 200 | Recettes, dépenses et solde de la Sécurité sociale par branche, en Md€ : PLFSS 2027 et LFSS 2026. |
| 27 | `secu_ondam` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, projet de loi de financement de la sécurité … | 1/page | non |  | 200 | Objectif national de dépenses d'assurance maladie et ses sous-objectifs, en Md€ : PLFSS 2027 et LFSS 2026. |
| 28 | `secu_recettes` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, projet de loi de financement de la sécurité … | 1/page | non |  | 200 | Recettes de la Sécurité sociale par catégorie, en M€, de 2024 à 2027 : annexe 3 du PLFSS 2027. |
| 29 | `comptes_publics` | Budget de l'État et finances publiques | Eurostat | 1/page | non |  | 200 | Comptes des administrations publiques françaises : recettes, dépenses par fonction (COFOG), déficit et dette, par sous-secteur, depuis 2010 au plus tôt selon le jeu … |
| 30 | `transferts_apu` | Budget de l'État et finances publiques | Eurostat | 1/page | non |  | 200 | Flux entre sous-secteurs des administrations publiques, en M€, de 2010 à 2025, à neutraliser pour éviter les doubles comptes. |
| 31 | `resf_tableaux` | Budget de l'État et finances publiques | Gouvernement, projet de loi de finances | 1/page | non |  | 200 | Tableaux du rapport économique, social et financier du PLF 2027 : solde public, chiffres-clés, trajectoires. Une ligne par cellule ; une même ligne peut revenir dans un … |
| 32 | `depenses_fiscales` | Budget de l'État et finances publiques | Gouvernement, projet de loi de finances | 1/page | non |  | 200 | Coût des dépenses fiscales par impôt, en M€, de 2024 à 2026 : Voies et moyens, tome 2, PLF 2026. |
| 33 | `rendements_impots` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Rendement des principaux impôts, en M€, rassemblé par Hémicycle à partir de l'état A, du PLFSS et d'Eurostat. « perimetre » précise chaque ligne : ne pas additionner … |
| 34 | `reperes_budgetaires` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Chiffres de référence des finances publiques, chacun retrouvé dans le document cité : cadrage, État, marché, transferts, retraites, chiffrages publiés. « valeur » garde … |
| 35 | `series_marche` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Rendements à 10 ans de l'OAT et du Bund, leur écart (Eurostat, mensuel) et taux de dépôt de la BCE. |
| 36 | `prix_marches_gros` | Énergie, climat, prix | FranceAgriMer, Réseau des nouvelles des marchés (RNM) | 1/page | non |  | 200 | Prix relevés par FranceAgriMer sur les marchés de gros français (MIN de Rungis et autres MIN, bassins d'expédition, cadrans) : fruits et légumes, viande, pêche, … |
| 37 | `qualite_registre` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Note de chaque jeu de données traité par Hémicycle, de A à E, avec ses critères et leurs preuves. « provisoire » signifie que le recoupement avec une source … |
| 38 | `amendements_budget_articles` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Articles visés par chaque amendement des projets de loi de finances et de financement de la sécurité sociale, extraits par Hémicycle. |
| 39 | `evenements_parlementaires` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Flux des événements parlementaires des trente derniers jours (dépôts, votes, étapes), rangés par date. |
| 40 | `sigles` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Lexique des sigles parlementaires vérifiés par Hémicycle, avec leur texte de référence. |
| 41 | `orcet_previsions_votes` | Hémicycle : Orcet (50 crédits par prédiction) | Hémicycle | 50/prédiction | non |  | 20 | Prévisions d'Orcet, le modèle d'Hémicycle, sur les votes de la 17e législature. « moyenne_probabilites_pour_pct » est la moyenne des probabilités individuelles des … |
| 42 | `orcet_predictions` | Hémicycle : Orcet (50 crédits par prédiction) | Hémicycle | 50/prédiction | non |  | 20 | Prédictions d'Orcet par cible, datées, avec le résultat constaté une fois connu. « moyenne_probabilites_pour » (de 0 à 1) est la moyenne des probabilités individuelles … |
| 43 | `signaux_faibles` | Hémicycle : jeux dérivés (5 crédits) | Hémicycle | 5/page | non |  | 200 | Signaux faibles détectés par Hémicycle : sujets dont les mentions parlementaires ou médiatiques augmentent par rapport à leur moyenne. « score » est un indice … |
| 44 | `budget_vert_plf_2026` | Budget de l'État et finances publiques | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Cotation environnementale des dépenses de l'État et des dépenses fiscales du PLF 2026. |
| 45 | `performance_depense_rap_2025` | Budget de l'État et finances publiques | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Objectifs, indicateurs et résultats des programmes de l'État selon les rapports annuels de performance 2025. |
| 46 | `fiscalite_locale_professionnels` | Collectivités, élus locaux, élections | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Taux et produits de fiscalité directe locale des professionnels, par commune et par exercice. |
| 47 | `comptes_communes` | Collectivités, élus locaux, élections | OFGL, Observatoire des finances et de la gestion publique … | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Agrégats financiers consolidés de chaque commune, de 2018 à 2025. |
| 48 | `comptes_intercommunalites` | Collectivités, élus locaux, élections | OFGL, Observatoire des finances et de la gestion publique … | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Agrégats financiers consolidés des groupements à fiscalité propre, de 2018 à 2025. |
| 49 | `comptes_departements` | Collectivités, élus locaux, élections | OFGL, Observatoire des finances et de la gestion publique … | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Agrégats financiers consolidés de chaque département, de 2012 à 2025. |
| 50 | `comptes_regions` | Collectivités, élus locaux, élections | OFGL, Observatoire des finances et de la gestion publique … | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Agrégats financiers consolidés de chaque région, de 2012 à 2025. |
| 51 | `comptes_sante_financement` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, DREES | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Dépenses de santé par poste et par financeur, selon les comptes nationaux de la santé. |
| 52 | `depenses_sante_restes_a_charge` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, DREES | 1/page | oui |  | 100 | Dépenses et restes à charge par poste, âge, sexe et situation des assurés. |
| 53 | `prestations_solidarite_mensuelles` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, DREES | 1/page | oui |  | 100 | Nombre mensuel de bénéficiaires des prestations de solidarité, en France, par région et par département. |
| 54 | `demandeurs_emploi_france` | Emploi et travail | Gouvernement, DARES | 1/page | oui |  | 100 | Stock trimestriel des inscrits à France Travail, corrigé des variations saisonnières. |
| 55 | `demandeurs_emploi_regions` | Emploi et travail | Gouvernement, DARES | 1/page | oui |  | 100 | Stock mensuel des inscrits à France Travail, par région et par département. |
| 56 | `emplois_vacants` | Emploi et travail | Gouvernement, DARES | 1/page | oui |  | 100 | Part des emplois vacants par secteur et par type de vacance, chaque trimestre. |
| 57 | `electricite_temps_reel` | Énergie, climat, prix | ODRÉ, gestionnaires des réseaux d'énergie | 1/page | oui |  | 100 | Consommation, production par filière, échanges et taux de CO2 de l'électricité française. |
| 58 | `consommation_energie_regions` | Énergie, climat, prix | ODRÉ, gestionnaires des réseaux d'énergie | 1/page | oui |  | 100 | Consommation annuelle brute d'électricité et de gaz de chaque région. |
| 59 | `production_renouvelable_regions` | Énergie, climat, prix | ODRÉ, gestionnaires des réseaux d'énergie | 1/page | oui |  | 100 | Production annuelle d'électricité et de gaz renouvelables de chaque région. |
| 60 | `temperatures_regions` | Énergie, climat, prix | ODRÉ, gestionnaires des réseaux d'énergie | 1/page | oui |  | 100 | Températures minimale, maximale et moyenne de chaque jour, par région. |
| 61 | `temperatures_departements` | Énergie, climat, prix | ODRÉ, gestionnaires des réseaux d'énergie | 1/page | oui |  | 100 | Températures minimale, maximale et moyenne de chaque jour, par département. |
| 62 | `ips_colleges` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | oui |  | 100 | Indice de position sociale de chaque collège public et privé sous contrat, depuis la rentrée 2023. |
| 63 | `valeur_ajoutee_colleges` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | oui |  | 100 | Résultats au brevet et valeur ajoutée de chaque collège, sessions 2022 à 2025. |
| 64 | `baccalaureat_academies` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | oui |  | 100 | Inscrits, présents, admis et mentions au baccalauréat par académie, sexe, statut du candidat et spécialité, sessions 2021 à 2025. |
| 65 | `effectifs_ecoles` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | oui |  | 100 | Nombre d'élèves et de classes de chaque école publique et privée sous contrat, par niveau, depuis la rentrée 2009. |
| 66 | `effectifs_colleges` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | oui |  | 100 | Nombre d'élèves de chaque collège par niveau, sexe, dispositif et langue vivante, depuis la rentrée 2019. |
| 67 | `personnels_second_degre` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | oui |  | 100 | Équivalents temps plein des enseignants et des personnels de chaque collège et lycée, par statut, âge et ancienneté. |
| 68 | `parcoursup_formations` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Enseignement supérieur et de … | 1/page | oui |  | 100 | Capacités, candidatures, classements et admissions de chaque formation proposée sur Parcoursup. |
| 69 | `insertion_diplomes` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Enseignement supérieur et de … | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Taux d'emploi, emploi stable et salaires des diplômés de licence, master, BUT et écoles d'ingénieurs, de 6 à 30 mois après le diplôme. |
| 70 | `finances_universites` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Enseignement supérieur et de … | 1/page | oui |  | 100 | Indicateurs financiers des opérateurs de l'enseignement supérieur (produits, charges de personnel, ressources propres, résultat, trésorerie), de 2010 à 2026. |
| 71 | `effectifs_etudiants` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Enseignement supérieur et de … | 1/page | oui |  | 100 | Étudiants inscrits par commune, type de formation ou d'établissement, secteur et sexe, depuis 2001-2002. |
| 72 | `caf_prestations_departements` | Sécurité sociale, santé, solidarité, CAF | CNAF, Caisse nationale des allocations familiales | 1/page | oui |  | 100 | Foyers allocataires, personnes couvertes et montants versés chaque mois pour chaque prestation de la branche Famille, par département. |
| 73 | `caf_prestations_communes` | Sécurité sociale, santé, solidarité, CAF | CNAF, Caisse nationale des allocations familiales | 1/page | oui |  | 100 | Foyers allocataires, personnes couvertes et montants versés en décembre pour chaque prestation de la branche Famille, par commune. |
| 74 | `caf_depenses_prestations` | Sécurité sociale, santé, solidarité, CAF | CNAF, Caisse nationale des allocations familiales | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Dépenses annuelles de prestations familiales, de logement et de solidarité, tous régimes et régime général. |
| 75 | `accueil_jeune_enfant_communes` | Sécurité sociale, santé, solidarité, CAF | CNAF, Caisse nationale des allocations familiales | 1/page | oui |  | 100 | Taux de couverture des enfants de moins de 3 ans par mode d'accueil, pour les communes suivies par la CNAF. |
| 76 | `execution_budget_etat_mensuelle` | Budget de l'État et finances publiques | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Solde, dépenses et recettes du budget de l'État cumulés depuis janvier, à chaque fin de mois. |
| 77 | `comptes_etat` | Budget de l'État et finances publiques | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Soldes des comptes de l'État par compte, mission et programme, de 2016 à 2025, dont la dette financière. |
| 78 | `marches_publics` | Économie, entreprises, commande publique | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Données essentielles des marchés publics notifiés par les acheteurs publics : objet, procédure, montant et titulaire. |
| 79 | `projets_achats_publics` | Économie, entreprises, commande publique | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Projets d'achats annoncés par les acheteurs publics avant tout appel d'offres, sur le portail APProch. |
| 80 | `prix_carburants_stations` | Énergie, climat, prix | Gouvernement, ministères économiques et financiers | 1/page | oui |  | 100 | Derniers prix affichés et ruptures de chaque carburant, station par station. |
| 81 | `aide_sociale_departementale_depenses` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, DREES | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Dépenses brutes d'aide sociale des départements par habitant et par bénéficiaire : RSA, APA, PCH, ASE et accueil des personnes handicapées. |
| 82 | `insertion_minima_sociaux_departements` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, DREES | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Taux d'allocataires des minima sociaux, surendettement, expulsions locatives et insertion des jeunes, par département. |
| 83 | `comptes_protection_sociale` | Sécurité sociale, santé, solidarité, CAF | Gouvernement, DREES | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Prestations de protection sociale par risque, par régime et par secteur institutionnel, depuis 1959. |
| 84 | `depenses_publiques_europe` | Europe (Eurostat, DREES) | Gouvernement, DREES | 1/page | oui |  | 100 | Dépenses publiques par fonction de 31 pays européens, rapportées au PIB potentiel et comparées à la moyenne de onze pays. |
| 85 | `demandeurs_emploi_communes` | Emploi et travail | Gouvernement, DARES | 1/page | oui |  | 100 | Nombre d'inscrits en catégories A, B et C au quatrième trimestre de chaque année, par commune, sexe et âge. |
| 86 | `flux_inscrits_france_travail` | Emploi et travail | Gouvernement, DARES | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Entrées et sorties trimestrielles des listes de France Travail par motif, dont les ruptures conventionnelles, par région et par département. |
| 87 | `offres_emploi_france_travail` | Emploi et travail | Gouvernement, DARES | 1/page | oui |  | 100 | Offres d'emploi collectées chaque mois par France Travail, par durée d'emploi, qualification et territoire. |
| 88 | `elus_maires` | Collectivités, élus locaux, élections | Gouvernement, ministère de l'Intérieur | 1/page | non |  | 50 | Maires en exercice, avec leur commune et la date de début de leur fonction. |
| 89 | `elus_conseillers_municipaux` | Collectivités, élus locaux, élections | Gouvernement, ministère de l'Intérieur | 1/page | non |  | 50 | Conseillers municipaux en exercice, par commune. |
| 90 | `elus_conseillers_departementaux` | Collectivités, élus locaux, élections | Gouvernement, ministère de l'Intérieur | 1/page | non |  | 50 | Conseillers départementaux en exercice, par canton. |
| 91 | `elus_conseillers_regionaux` | Collectivités, élus locaux, élections | Gouvernement, ministère de l'Intérieur | 1/page | non |  | 50 | Conseillers régionaux en exercice, par région. |
| 92 | `eurodeputes` | Influence et autres élus | Parlement européen | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Eurodéputés en exercice, avec leur pays et leur groupe politique. |
| 93 | `delinquance_communes` | Sécurité, justice, droit | Gouvernement, ministère de l'Intérieur | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Crimes et délits enregistrés par la police et la gendarmerie, par commune, indicateur et année, de 2016 à 2025. |
| 94 | `delinquance_departements` | Sécurité, justice, droit | Gouvernement, ministère de l'Intérieur | 1/page | non |  | 100 | Crimes et délits enregistrés par la police et la gendarmerie, par département, indicateur et année, homicides compris. |
| 95 | `prix_immobilier_dvf` | Logement et aménagement | data.gouv.fr, d'après les valeurs foncières de la DGFiP | 1/page | non |  | 100 | Nombre de ventes et prix au m² des logements et locaux, de la France entière à la section cadastrale, sur les dix derniers semestres. |
| 96 | `elections_participation` | Collectivités, élus locaux, élections | data.gouv.fr, d'après le ministère de l'Intérieur | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Inscrits, votants, abstentions, blancs et nuls par bureau de vote pour chaque scrutin depuis 1999. |
| 97 | `accidents_route_2025` | Sécurité, justice, droit | Gouvernement, ministère de l'Intérieur (ONISR) | 1/page | non |  | 100 | Chaque accident corporel de la circulation de 2025, avec sa date, sa commune et ses conditions. |
| 98 | `logements_vacants` | Logement et aménagement | Gouvernement, ministère de la Transition écologique | 1/page | non |  | 100 | Logements privés vacants et vacants depuis plus de deux ans, par commune, de 2020 à 2026. |
| 99 | `communes_sru` | Logement et aménagement | Gouvernement, ministère de la Transition écologique | 1/page | non |  | 100 | Taux de logements sociaux, objectif, carence et prélèvement de chaque commune soumise à la loi SRU. |
| 100 | `dotations_investissement_2025` | Collectivités, élus locaux, élections | Gouvernement, Direction générale des collectivités locales | 1/page | non |  | 100 | Projets des collectivités financés en 2025 par la DETR, la DSIL, la DSID et la DPV, avec leur coût et la subvention de l'État. |
| 101 | `consommation_espaces` | Logement et aménagement | Cerema | 1/page | non |  | 100 | Espaces naturels, agricoles et forestiers consommés chaque année par commune et par destination, de 2009 à 2024. |
| 102 | `loyers_appartements` | Logement et aménagement | Gouvernement, ministère de la Transition écologique | 1/page | non |  | 100 | Loyer d'annonce estimé par m², charges comprises, des appartements de chaque commune en 2025. |
| 103 | `coproprietes_communes` | Logement et aménagement | Agence nationale de l'habitat | 1/page | non |  | 100 | Nombre de copropriétés et de logements en copropriété par commune, selon leur taille, leur époque et leur syndic, en 2025. |
| 104 | `ips_ecoles` | Éducation et enseignement supérieur | Gouvernement, ministère de l'Éducation nationale | 1/page | non |  | 100 | Indice de position sociale de chaque école, publique ou privée, de la rentrée 2022 à la rentrée 2024. |
| 105 | `index_egalite_professionnelle` | Emploi et travail | Gouvernement, ministère du Travail | 1/page | non |  | 100 | Notes de l'index de l'égalité entre les femmes et les hommes des entreprises de 50 salariés ou plus, de 2018 à 2025. |
| 106 | `demandes_asile_departements` | Sécurité, justice, droit | Ofpra, Office français de protection des réfugiés et … | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Premières demandes, réexamens et réouvertures déposés devant l'Ofpra en 2025, par région et par département. |
| 107 | `chomage_europe` | Europe (Eurostat, DREES) | Eurostat, Commission européenne | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Taux et nombre de chômeurs au sens du BIT, par pays, sexe et âge, chaque mois. |
| 108 | `dette_deficit_europe` | Europe (Eurostat, DREES) | Eurostat, Commission européenne | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Dette publique au sens de Maastricht, déficit et agrégats associés des administrations publiques, par pays et par année. |
| 109 | `pib_europe` | Europe (Eurostat, DREES) | Eurostat, Commission européenne | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Produit intérieur brut et ses composantes par pays, chaque trimestre, en valeur et en volume. |
| 110 | `depenses_fonction_europe` | Europe (Eurostat, DREES) | Eurostat, Commission européenne | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Dépenses des administrations publiques par fonction de la nomenclature CFAP, par pays et par année. |
| 111 | `communes` | Collectivités, élus locaux, élections | Gouvernement, API Géo (Insee et IGN) | 1/page | non |  | 100 | Code Insee, population municipale, département, région et intercommunalité de chaque commune. |
| 112 | `sirene_etablissements` | Économie, entreprises, commande publique | Insee | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Établissements et unités légales du répertoire Sirene : identifiants, dénomination, activité, tranche d'effectifs, adresse et état administratif. |
| 113 | `legifrance_codes` | Sécurité, justice, droit | Gouvernement, DILA (Légifrance) | 1/page | oui |  | 50 | Recherche dans les articles des codes en vigueur à la date du jour, avec l'identifiant de chaque article trouvé. |
| 114 | `legifrance_lois_decrets` | Sécurité, justice, droit | Gouvernement, DILA (Légifrance) | 1/page | oui |  | 50 | Recherche dans les lois, ordonnances, décrets et arrêtés en vigueur à la date du jour, avec l'identifiant de chaque article trouvé. |
| 115 | `legifrance_article` | Sécurité, justice, droit | Gouvernement, DILA (Légifrance) | 1/page | non | mode d'emploi : « filtre toujours » | 5 | Texte complet d'un article d'un code, d'une loi ou d'un règlement, avec son état et ses dates de vigueur. |
| 116 | `judilibre_decisions` | Sécurité, justice, droit | Cour de cassation | 1/page | oui |  | 50 | Recherche dans les décisions de la Cour de cassation et des autres juridictions judiciaires diffusées en open data, avec leur sommaire. |
| 117 | `judilibre_decision` | Sécurité, justice, droit | Cour de cassation | 1/page | non | mode d'emploi : « filtre toujours » | 5 | Texte intégral pseudonymisé d'une décision de justice judiciaire, avec ses visas, son sommaire et les décisions rapprochées. |
| 118 | `marche_travail_demandeurs` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Nombre de demandeurs d'emploi inscrits en fin de trimestre, par catégorie, par territoire et par métier. |
| 119 | `marche_travail_offres` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Nombre d'offres d'emploi enregistrées au cours du trimestre et des douze derniers mois, par territoire et par métier. |
| 120 | `marche_travail_tensions` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Indicateur annuel de difficulté de recrutement de la Dares et de France Travail, et ses facteurs d'explication, par territoire et par métier. |
| 121 | `acces_emploi_demandeurs` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Nombre de demandeurs d'emploi des catégories A et B qui accèdent à un emploi d'un mois ou plus, et taux d'accès, par territoire et par métier. |
| 122 | `acces_emploi_sortants_formation` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Nombre de demandeurs d'emploi qui accèdent à un emploi dans les six mois suivant la fin d'une formation, et taux d'accès, par territoire. |
| 123 | `dynamique_emploi_territoires` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Indicateur trimestriel de France Travail sur le dynamisme attendu de l'emploi salarié et des embauches d'un territoire. |
| 124 | `rome_metiers` | Emploi et travail | France Travail | 1/page | non |  | 200 | Les métiers du répertoire opérationnel des métiers et des emplois (ROME 4.0), avec leur domaine professionnel. |
| 125 | `agences_france_travail` | Emploi et travail | France Travail | 1/page | non |  | 200 | Agences de France Travail, avec leur type, leur adresse et leurs coordonnées géographiques. |
| 126 | `entreprises_potentiel_embauche` | Emploi et travail | France Travail | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Estimation par France Travail du potentiel d'embauche des établissements d'un territoire pour un métier, sur les six prochains mois. |
| 127 | `insee_series` | Économie, entreprises, commande publique | Insee | 1/page | non | mode d'emploi : « filtre toujours » | 200 | Observations des séries de la Banque de données macroéconomiques de l'Insee : chômage, prix, croissance, emploi, démographie. |
| 128 | `insee_populations_reference` | Collectivités, élus locaux, élections | Insee | 1/page | non | mode d'emploi : « filtre toujours » | 100 | Populations légales de référence de chaque commune, intercommunalité, département et région. |
| 129 | `banque_france_series` | Économie, entreprises, commande publique | Banque de France | 1/page | oui |  | 100 | Catalogue des séries statistiques de la Banque de France et de l'ACPR : intitulé, thème, fréquence, période couverte et deux dernières valeurs. |
| 130 | `banque_france_observations` | Économie, entreprises, commande publique | Banque de France | 1/page | oui | mode d'emploi : « filtre toujours » | 100 | Valeurs datées de chaque série de la Banque de France et de l'ACPR : taux d'intérêt, crédits, épargne, balance des paiements, enquêtes de conjoncture. |
| 131 | `banque_france_jeux` | Économie, entreprises, commande publique | Banque de France | 1/page | oui |  | 100 | Liste des jeux statistiques de la Banque de France et de l'ACPR, avec leur description, leur nombre de séries et la date de leur dernière valeur. |
| 132 | `banque_france_nomenclatures` | Économie, entreprises, commande publique | Banque de France | 1/page | oui |  | 100 | Codes et libellés des nomenclatures employées dans les séries de la Banque de France : zones, secteurs, instruments, échéances. |

## Annexe B : journal des appels REST du 14/11/2026

Base `https://api.hemicycle.ai/v1`, en-têtes `Authorization: Bearer <HEMICYCLE_API_KEY>` (sauf n° 08) et `Hemicycle-Version: 2026-10-01` (sauf n° 27 sans en-tête et n° 28 avec `2020-01-01`). Les n° 18 et 19 n'existent pas. Le solde `X-Credits-Remaining` baisse aussi sous l'effet d'appels faits en parallèle par un autre agent de l'équipe sur le même compte (6 crédits entre les n° 03 et 11) ; le total ci-dessous ne compte que nos appels.

| N° | Requête | Corps | Statut | `X-Credits-Cost` | `X-Credits-Remaining` | Taille (car.) |
|---|---|---|---|---|---|---|
| 01 | `GET /v1/credits` |  | 200 | 0 | 10487 | 50 |
| 02 | `GET /v1/jeux` |  | 200 | 0 | 10487 | 205753 |
| 03 | `GET /v1/scrutins?legislature=17&limit=3` |  | 200 | 1 | 10486 | 2130 |
| 04 | `GET /v1/scrutins?legislature=17&limit=500` |  | 400 | 0 |  | 190 |
| 05 | `GET /v1/scrutins/VTANR5L17V999999` |  | 404 | 0 |  | 176 |
| 06 | `POST /v1/jeux/interroger` | `{"jeu": "inexistant", "limite": 1}` | 400 | 0 |  | 203 |
| 07 | `POST /v1/jeux/interroger` | `{"jeu": "votes", "limite": 1}` | 422 | 0 |  | 230 |
| 08 | `GET /v1/credits` |  | 401 | 0 |  | 213 |
| 09 | `POST /v1/marianne/reponses` | `{}` | 501 | 0 |  | 221 |
| 10 | `GET /v1/credits` |  | 200 | 0 | 10486 | 50 |
| 11 | `GET /v1/scrutins?legislature=17&limit=3&cursor=eyJvIjozfQ` |  | 200 | 1 | 10479 | 2004 |
| 12 | `GET /v1/scrutins?depuis=2026-11-10&limit=100` |  | 200 | 1 | 10478 | 62857 |
| 13 | `GET /v1/scrutins/VTANR5L17V9808` |  | 200 | 1 | 10477 | 736 |
| 14 | `GET /v1/scrutins/VTANR5L17V9808/resultat` |  | 200 | 1 | 10476 | 9231 |
| 15 | `GET /v1/scrutins/VTANR5L17V9808/votes?limit=3` |  | 200 | 1 | 10475 | 4713 |
| 16 | `GET /v1/recherche?q=droits+voisins&types=texte,amendement&limit=3` |  | 200 | 2 | 10473 | 1668 |
| 17 | `GET /v1/recherche?q=droits+voisins&types=scrutin&limit=3` |  | 200 | 2 | 10471 | 47 |
| 20 | `POST /v1/jeux/interroger` | `{"jeu": "scrutins", "recherche": "droits voisins", "colonnes": ["uid"…` | 200 | 1 | 10470 | 1159 |
| 21 | `POST /v1/agregats/positions-groupes` | `{"scrutins": ["VTANR5L17V9807", "VTANR5L17V9808"]}` | 200 | 1 | 10469 | 5392 |
| 22 | `GET /v1/amendements?depuis=2026-11-12&sort=adopte&limit=3` |  | 200 | 1 | 10468 | 47 |
| 23 | `GET /v1/dossiers?legislature=17&limit=2` |  | 200 | 1 | 10467 | 964 |
| 24 | `GET /v1/organes?type=groupe&limit=20` |  | 200 | 1 | 10466 | 6422 |
| 25 | `GET /v1/acteurs?nom=tanguy&limit=3` |  | 200 | 1 | 10465 | 1026 |
| 26 | `GET /v1/textes?legislature=17&limit=2` |  | 200 | 1 | 10464 | 1100 |
| 27 | `GET /v1/credits` |  | 200 | 0 | 10464 | 50 |
| 28 | `GET /v1/credits` |  | 400 | 0 |  | 183 |
| 29 | `GET /v1/textes/PIONANR5L17BTC3435` |  | 200 | 1 | 10463 | 481 |
| 30 | `GET /v1/acteurs/PA795778` |  | 200 | 1 | 10462 | 6175 |
| 31 | `GET /v1/amendements?depuis=2026-11-10&limit=3` |  | 200 | 1 | 10461 | 28015 |
| 32 | `GET /v1/dossiers/DLR5L17N51330` |  | 200 | 1 | 10460 | 335 |
| 33 | `GET /v1/scrutins?limit=1&cursor=zzz` |  | 400 | 0 |  | 233 |
| 34 | `GET /v1/scrutins?legislature=17&limit=1&foo=bar` |  | 200 | 1 | 10459 | 727 |
| 35 | `GET /v1/amendements?texte=PRJLANR5L17B3434&sort=adopte&limit=2` |  | 200 | 1 | 10458 | 7690 |
| 36 | `GET /v1/recherche?q=fin+de+gestion+2026&types=dossier&limit=2` |  | 200 | 2 | 10456 | 391 |
| 37 | `GET /v1/scrutins?legislature=17&limit=1` |  | 200 | 1 | 10455 | 727 |
| 38 | `GET /v1/scrutins?legislature=17&limit=1` |  | 200 | 0 | 10455 | 727 |
| 39 | `GET /v1/credits` |  | 200 | 0 | 10455 | 50 |
| 40 | `GET /v1/inexistant` |  | 404 | 0 |  | 189 |
| 41 | `POST /v1/agregats/accord-groupes` | `{}` | 400 | 0 |  | 206 |
| 42 | `POST /v1/agregats/loyaute-deputes` | `{}` | 400 | 0 |  | 206 |
| 43 | `POST /v1/agregats/classement-auteurs` | `{}` | 400 | 0 |  | 214 |
| 44 | `POST /v1/orcet/predictions` | `{}` | 400 | 0 |  | 180 |
| 45 | `GET /v1/entreprises` |  | 400 | 0 |  | 188 |
| 46 | `GET /v1/donnees-publiques` |  | 422 | 0 |  | 187 |
| 47 | `POST /v1/donnees-publiques/lecture` | `{}` | 422 | 0 |  | 233 |
| 48 | `POST /v1/expositions` | `{}` | 501 | 0 |  | 221 |
| 49 | `POST /v1/livrables` | `{}` | 501 | 0 |  | 221 |
| 50 | `POST /v1/agregats/positions-groupes` | `{}` | 400 | 0 |  | 235 |
| 51 | `GET /v1/agregats/accord-groupes` |  | 404 | 0 |  | 189 |
| 52 | `GET /v1/amendements/AMANR5L17PO59048B3434P0D1N000099` |  | 200 | 1 | 10454 | 4041 |
| 53 | `GET /v1/organes/PO845401` |  | 404 | 0 |  | 189 |
| 54 | `GET /v1/credits` |  | 200 | 0 | 10454 | 50 |
| 55 | `POST /v1/jeux/interroger` | `{"jeu": "chomage_europe", "limite": 1}` | 400 | 0 |  | 761 |
| 56 | `POST /v1/jeux/interroger` | `{"jeu": "comptes_regions", "valeurs_de": "agregat"}` | 400 | 0 |  | 185 |
| | **Total facturé à nos appels** | | | **27** | | |

**Bilan** : 54 appels, dont 24 facturés ; 27 crédits consommés (0,27 €) ; solde 10 487 avant (n° 01), 10 454 après (n° 54), l'écart de 33 incluant 6 crédits consommés en parallèle par un autre agent.

## Annexe C : fichiers de travail

Dans le dossier de travail de la session (`/private/tmp/claude-501/-Users-clement-Github-Hemicycle/0e4a1f0a-4429-41ce-abdb-5ded13acd97c/scratchpad/rapport_api/`), non versionné :

- `guides/` : arborescence et 27 fiches `guide` brutes (Markdown), `_initialize.json` (informations et instructions du serveur MCP) ;
- `site/md/` : les 26 pages de doc en Markdown et `llms.txt` ; `site/*.js` : modules du site, dont `apiSpec-DtnUugHP.js` (référence de l'API) ;
- `rest/` : une réponse brute par appel REST (statut, en-têtes, corps), `_cumul.json` (crédits consommés) ;
- `scripts/` : scripts d'appel (la clé est lue par python-dotenv et n'est jamais affichée ni écrite) ;
- `jeux_liste.txt`, `annexe.md`, `annexe_b.md` : catalogue mis à plat et annexes générées.
