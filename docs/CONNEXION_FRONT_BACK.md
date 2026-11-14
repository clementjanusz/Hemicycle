# Connecter le site du rapport au chatbot (front ↔ back)

Brief de passation, à jour au 14/11/2026 (branche `backend`). Le backend est prêt : il reste à brancher la page du rapport dessus.

## En bref

- **Le site** : `frontend/index.html`, le dossier « Après les flammes » en scrollytelling, écrit par l'équipe front. C'est une page statique, sans widget de chatbot pour l'instant.
- **Le backend** : un serveur FastAPI, `backend/chatbot/serveur.py`, sur le port 8000. Il expose le chatbot du rapport (`POST /chat` et `POST /chat/flux`) et sert aussi le site à la racine `/` (alias `/site/`).
- **Ce qui manque** :
  1. Le texte du numéro en Markdown, que le chatbot lit pour répondre.
  2. Un widget de chatbot dans la page.

Le contrat complet est dans [`docs/ARCHITECTURE.md`](ARCHITECTURE.md), sections `POST /chat`, `POST /chat/flux` et `GET /api/rapport/{mois}`. Ce document dit **quoi faire** ; ARCHITECTURE.md fait foi pour le **format**.

## 1. Lancer le backend

Il faut un `.env` à la racine du dépôt. Il n'est jamais commité ; on le copie depuis `.env.example`. Variables nécessaires :
- `HEMICYCLE_API_KEY`, `HEMICYCLE_MCP_URL`, `HEMICYCLE_MCP_KEY` ;
- `FEATHERLESS_API_KEY`, `FEATHERLESS_BASE_URL`, `FEATHERLESS_MODEL`.

```bash
cd backend/chatbot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # première fois seulement
.venv/bin/python serveur.py                                            # http://127.0.0.1:8000
```

Vérifications rapides, toutes gratuites :

```bash
curl -s http://127.0.0.1:8000/etat            # modèle, solde Hémicycle
curl -s http://127.0.0.1:8000/api/rapports    # numéros disponibles (aujourd'hui : ["demo"])
open http://127.0.0.1:8000/                   # le site du rapport, servi par le backend (page d'accueil)
```

**URL de base côté front :**
- **Recommandé** : ouvrir le site par `http://127.0.0.1:8000/`. La page et l'API ont alors la même origine, et les appels peuvent utiliser des URL relatives (`fetch("/chat/flux", …)`).
- **Site servi ailleurs** (autre port, hébergeur statique) : le CORS est ouvert à toutes les origines. Il faut alors une URL absolue, configurable, par exemple `const API = window.CHATBOT_API ?? "http://127.0.0.1:8000";`. À distance, via Tailscale : `http://desktop:8000`.

## 2. Écrire le numéro en Markdown : `rapports/2026-11/rapport.md`

Le chatbot ne lit pas le HTML. Il lit `rapports/<mois>/rapport.md`, découpé en sections par les titres `##` et `###`. Sans ce fichier, seul le numéro fictif `demo` existe.

- **Point de départ** : partir de [`rapports/_modele/rapport.md`](../rapports/_modele/rapport.md). L'en-tête YAML contient `mois`, `titre`, `chapo`, `auteurs` et `publie_le` ; ne pas mettre `fictif: true`.
- **Contenu** : reprendre le texte de la page, section par section, avec ses chiffres et ses sources.
- **Identifiants** : donner à chaque section **le même identifiant que dans la page**, avec le suffixe `{#id}`. C'est ce qui permet au chatbot de faire défiler la page jusqu'à la bonne section et de la surligner.

| Identifiant dans `frontend/index.html` | Titre dans la page | Titre Markdown à écrire |
| --- | --- | --- |
| `carte` | Où le feu est passé | `## Où le feu est passé {#carte}` |
| `aides` | L'aide est arrivée par décret | `## L'aide est arrivée par décret {#aides}` |
| `prevenir` | Un crédit d'impôt pour débroussailler | `## Un crédit d'impôt pour débroussailler {#prevenir}` |
| `cotisations` | Un répit pour les entreprises et les indépendants | `## … {#cotisations}` |
| `pompiers` | Alléger la facture des services d'incendie | `## … {#pompiers}` |
| `suite` | Le budget est rejeté malgré ces votes | `## … {#suite}` |
| `scrutins` | Qui a voté quoi ? | `## Qui a voté quoi ? {#scrutins}` (liste des 5 scrutins, avec leur numéro) |

Ajouter aussi `## Méthodologie` et `## Sources`. L'inventaire `inventaire-donnees.csv` dit d'où vient chaque donnée et quelles en sont les limites éditoriales : le chatbot s'en servira pour répondre « d'où vient ce chiffre ? ».

**Vérification** : `curl -s http://127.0.0.1:8000/api/rapport/2026-11` doit renvoyer `sections[].id` = `carte`, `aides`… Le fichier est relu à chaque modification, sans redémarrer le serveur.

## 3. Ajouter le widget de chatbot dans `frontend/index.html`

**Règle** : on ajoute un widget, on ne touche pas au texte éditorial ni aux visualisations. Le widget est un bouton flottant « Poser une question », qui ouvre un panneau avec une zone de saisie et un fil de réponses.

### Requête

```js
POST /chat/flux
Content-Type: application/json
{ "mois": "2026-11", "question": "…", "historique": [ {"role": "user", "contenu": "…"}, {"role": "assistant", "contenu": "…"} ] }
```

- `mois` est **obligatoire** pour le chatbot du rapport. Sans lui, la requête part vers l'outil de rédaction des journalistes.
- `historique` contient les échanges précédents (20 messages au plus), pour les questions de suivi.

### Lecture du flux (NDJSON : un objet JSON par ligne)

```js
async function poserQuestion(question, historique, { onEtape, signal }) {
  const r = await fetch("/chat/flux", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal,
    body: JSON.stringify({ mois: "2026-11", question, historique }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`); // 422 : corps invalide
  const lecteur = r.body.getReader(), decodeur = new TextDecoder();
  let tampon = "";
  for (;;) {
    const { value, done } = await lecteur.read();
    if (done) break;
    tampon += decodeur.decode(value, { stream: true });
    const lignes = tampon.split("\n"); tampon = lignes.pop();
    for (const ligne of lignes) {
      if (!ligne.trim()) continue;
      const e = JSON.parse(ligne);
      if (e.type === "etape") onEtape(e.message);          // « Lecture du rapport… », « Recherche dans Hémicycle : … »
      else if (e.type === "reponse") return e.donnees;      // même JSON que POST /chat
      else if (e.type === "erreur") throw new Error(e.detail);
      // type « appel » : détail d'un appel Hémicycle, facultatif ; ignorer les types inconnus
    }
  }
  throw new Error("Connexion interrompue.");
}
```

- **Annuler** une question : `AbortController`, au clic sur « Annuler », à l'envoi d'une nouvelle question ou à la fermeture du panneau. Le serveur arrête alors la question et ne consomme plus de crédits.
- **Durée** : 10 à 45 s par question. Afficher le `message` de la dernière étape, avec un indicateur d'activité.

### Afficher la réponse (`donnees`)

| Champ | Affichage |
| --- | --- |
| `reponse` | Texte de la réponse. Il peut contenir des puces `- ` et du **gras** `**…**` : échapper le HTML et ne rendre que ces deux éléments. |
| `sources[]` | Liste sous la réponse. `type: "rapport"` : « Dans le rapport : section X », avec un lien vers `#section_id`, à présenter comme vérifié par la rédaction. `type: "hemicycle"` : lien `url`, `libelle`, `editeur` et `licence`, avec la mention « Hémicycle, non vérifié par la rédaction ». |
| `actions[]` | Pour chaque `{type: "surligner_section", section_id, titre, raison}` : défiler jusqu'à `#section_id` avec `scrollIntoView({behavior: "smooth", block: "start"})`, surligner la section 4 à 6 s, et ajouter le lien « Voir la section « titre » ». Au plus 2 actions ; ignorer un `id` absent ; respecter `prefers-reduced-motion`. |

**Cas particuliers** :
- Une salutation reçoit une réponse d'aide fixe.
- Une question hors sujet reçoit un refus poli, déjà rédigé par le serveur.
- « Je n'ai pas trouvé cette information… » est une réponse normale : à afficher telle quelle.

## 4. Tester

Remplacer `"2026-11"` par `"demo"` tant que le fichier Markdown n'existe pas. Questions à essayer :

1. « Que dit le rapport sur le crédit d'impôt débroussaillement ? » : réponse tirée du rapport, et surlignage de `#prevenir`.
2. « Comment a voté le RN sur le budget ? » : réponse du rapport et d'Hémicycle, avec sources des deux types.
3. « Comment a voté Frédéric Valletoux sur le scrutin n° 9895 ? » : réponse tirée d'Hémicycle, avec la source du scrutin.
4. « Quel temps fera-t-il demain ? » : refus poli.

Chaque question coûte 0 à 5 crédits Hémicycle (1 crédit = 0,01 €), plus les appels au modèle Featherless.

## 5. À ne pas faire

- Mettre une clé (Hémicycle ou Featherless) dans le front, ou appeler Hémicycle depuis le navigateur. Tout passe par le backend.
- Modifier `backend/` sans prévenir l'équipe back. Le contrat est figé dans `docs/ARCHITECTURE.md` ; une demande d'évolution s'ajoute dans `backend/TODO.md`.
- Changer le texte du dossier dans `frontend/index.html` : seul l'ajout du widget est prévu.
- Commiter le `.env`.

## Annexe : les autres routes du backend

| Route | Usage |
| --- | --- |
| `POST /chat` | Même corps que `/chat/flux` ; réponse d'un bloc, sans progression. Solution de repli. |
| `GET /api/rapport/{mois}`, `GET /api/rapports` | Le rapport découpé en sections, et la liste des numéros. |
| `GET /etat` | Modèle, crédits consommés, solde Hémicycle. |
| `GET /redaction` | Outil de rédaction des journalistes (veille parlementaire), sans lien avec le site public. |
| `GET /api/catalogue`, `POST /api/appel` | Endpoints de la veille (outil interne). |
