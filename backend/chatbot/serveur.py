"""Outil de rédaction : un petit serveur web interne pour les journalistes de l'équipe.

Un journaliste pose une question sur l'actualité parlementaire (« Quoi de neuf à
l'Assemblée cette semaine ? », « Où en est le texte sur X ? ») ; le serveur fait tourner
la boucle d'outils Featherless ↔ MCP Hémicycle et renvoie une réponse très brève et sourcée.

Règle centrale : la réponse ne s'appuie QUE sur les données d'Hémicycle obtenues pendant
la question. Si aucun appel d'outil n'a ramené de source, le serveur remplace la réponse
du modèle par « Je n'ai pas trouvé cette information dans Hémicycle. ».

Lancement (depuis backend/chatbot/) ::

    .venv/bin/python serveur.py                                   # modèle du .env (FEATHERLESS_MODEL)
    FEATHERLESS_MODEL=Qwen/Qwen3.8-27B .venv/bin/python serveur.py  # autre modèle
    .venv/bin/python serveur.py --modele Qwen/Qwen3.8-27B --reflexion

puis ouvrir http://127.0.0.1:8000/ (port : CHATBOT_PORT).

Points d'accès :
- ``GET /`` : la page de l'outil (frontend/outil-redaction/index.html) ;
- ``GET /site/`` : le site du rapport (dossier frontend/, fichiers statiques) ;
- ``POST /chat`` : ``{"question", "historique"}`` → ``{"reponse", "sources", "outils_utilises", "credits", …}`` ;
- ``POST /chat/flux`` : même corps, réponse NDJSON : les étapes au fil de l'eau, puis la réponse de ``/chat`` ;
- ``GET /etat`` : modèle, outils exposés, crédits consommés depuis le démarrage, solde Hémicycle ;
- ``GET /api/catalogue`` : les endpoints de la veille (catégories, coût, paramètres, requête REST équivalente) ;
- ``POST /api/appel`` : ``{"outil", "arguments"}`` → appel direct d'un endpoint, sans le modèle.

Le journaliste choisit, question par question, les endpoints que le modèle peut appeler
(champ ``outils`` de ``POST /chat``) ; le catalogue est défini dans ``veille.py``.

Les clés ne sont jamais affichées ni journalisées.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import time
import traceback
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from zoneinfo import ZoneInfo

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from featherless_client import (
    ClientFeatherlessAsync,
    ConcurrenceDepassee,
    ReponseChat,
    charger_config,
)
from outils_rapport import NumeroInvalide, OutilsRapport, RapportIntrouvable
from routes_rapport import routeur as routeur_rapport
from veille import (
    CATEGORIES,
    ENDPOINTS,
    NON_PROPOSES,
    PAR_NOM,
    PRESELECTIONS,
    SELECTION_DEFAUT,
    SPECS_JEUX,
    ErreurArgumentsVeille,
    appel_interroger,
    attribuer_lignes,
    compacter_jeu,
    definition as definition_endpoint,
    nom_de_famille,
    nomme_le_depute,
    remplacer_jours,
    requete_rest,
    source_depute,
    url_scrutin,
)
from hemicycle_tools import (
    ARGUMENTS_PAR_DEFAUT,
    COUT_INCONNU,
    COUTS_CREDITS,
    CompteurConversation,
    OutilsHemicycle,
    ResultatOutil,
    charger_config_mcp,
    lire_tool_call,
    tronquer,
)

journal = logging.getLogger("outil_redaction")

RACINE = Path(__file__).resolve().parents[2]
FICHIER_ENV = RACINE / ".env"
FICHIER_PAGE = RACINE / "frontend" / "outil-redaction" / "index.html"
FUSEAU = ZoneInfo("Europe/Paris")

# Les endpoints proposés (outils MCP, outils locaux et jeux de données ciblés), leurs descriptions
# et la sélection par défaut sont définis dans veille.py. `interroger` n'est jamais exposé tel
# quel au modèle : 132 jeux, dont les prédictions Orcet à 50 crédits pièce.

# Seuls jeux que les outils locaux peuvent interroger (garde-fou contre Orcet et les jeux dérivés) :
# ceux des endpoints « jeu » de veille.py, variantes comprises (`deputes` pour chercher_depute
# avec anciens = true).
JEUX_AUTORISES = frozenset({"scrutins", "reunions", *(jeu for spec in SPECS_JEUX.values() for jeu in spec.jeux)})
LEGISLATURE = 17
EDITEUR_AN = "Assemblée nationale"
LICENCE_AN = "Licence Ouverte (Etalab)"
URL_OPEN_DATA_AN = "https://data.assemblee-nationale.fr"

MESSAGE_INTROUVABLE = "Je n'ai pas trouvé cette information dans Hémicycle."
# Chatbot du rapport : question hors sujet ou demande d'opinion (ni recherche automatique, ni garde-fou).
MESSAGE_HORS_PERIMETRE = "Je ne peux répondre qu'aux questions sur l'activité du Parlement et sur ce rapport."
MESSAGE_AIDE = (
    "Posez une question sur l'activité du Parlement : derniers scrutins, ordre du jour des séances, "
    "état d'un texte, position des groupes sur un vote… Choisissez les endpoints Hémicycle à utiliser "
    "dans « Endpoints de la veille ». Les réponses s'appuient uniquement sur les données d'Hémicycle "
    "consultées en direct."
)
# Salutations et questions sur l'outil : réponse fixe, sans appel au modèle ni à Hémicycle.
MOTIF_AIDE = re.compile(
    r"^\s*(bonjour|bonsoir|salut|coucou|hello|merci( beaucoup)?|aide|help|"
    r"(que|qu'est-ce que) (tu (peux|sais)|(peux|sais)[- ]tu) faire|[àa] quoi sers[- ]tu|"
    r"comment (ça|ca) marche|comment fonctionne(s)?[- ]tu)\s*[?!.]*\s*$",
    re.IGNORECASE,
)
NOTE_LIMITE = (
    "\n\n[Note du serveur : limite d'appels d'outils atteinte. N'appelle plus d'outil ; rédige "
    "maintenant la réponse finale, uniquement avec les résultats ci-dessus.]"
)
# Recherche automatique : quand le modèle n'appelle aucun outil, le serveur interroge lui-même
# Hémicycle avec les mots-clés de la question (mots vides et mots génériques retirés).
MOTS_VIDES = frozenset("""
a à ai au aux avec ce ces cet cette c ça d de des du dans donc elle elles en est et été être
fait faire il ils je j l la le les leur leurs lui m ma mais me mes moi mon n ne ni nos notre nous
on ont ou où par pas plus pour qu que quel quelle quelles quels qui quoi s sa sans se ses si son
sont sous sur t ta te tes toi ton tous tout toute toutes tu un une vos votre vous y
comment pourquoi quand combien est-ce y-a-t-il a-t-il
actualité actualités actu info infos information informations nouvelle nouvelles nouveau neuf
récent récente récents récentes récemment dernier dernière derniers dernières semaine mois jour
aujourd hui hier ce-mois-ci cette-semaine sujet concernant propos point où-en état passé passe
assemblée nationale parlement parlementaire parlementaires député députés députée députées hémicycle
texte textes loi lois projet proposition données donnée beaucoup plein eu avoir y-a
vote votes voté votée votés voter
""".split())


def mots_cles(question: str) -> str:
    """Mots-clés d'une question pour la recherche automatique (au plus 6)."""
    mots = re.findall(r"[a-zà-ÿœæç0-9-]+", question.lower().replace("’", " ").replace("'", " "))
    utiles = [mot for mot in mots if len(mot) > 2 and mot not in MOTS_VIDES]
    return " ".join(dict.fromkeys(utiles))[:120] if utiles else ""


# « Prénom Nom » dans une question (« Didier Lemaire », « Marine Le Pen », « Charles de Courson »).
MAJ, MIN = "A-ZÀ-ÖØ-Þ", "a-zß-öø-ÿ"
MOTIF_PERSONNE = re.compile(
    rf"(?<![\w-])([{MAJ}][{MIN}]+(?:-[{MAJ}][{MIN}]+)?)\s+"  # prénom, éventuellement composé
    rf"((?:(?:de|du|des|d'|d’|van|von|di|da)\s*)?[{MAJ}][{MIN}'’]*[{MIN}](?:[\s-][{MAJ}][{MIN}'’]*[{MIN}])?)"  # nom
)
# Premiers mots à ignorer : début de phrase, institutions, groupes, lieux.
PAS_UN_PRENOM = frozenset("""
quel quelle quels quelles que qui quoi comment combien pourquoi quand où est le la les un une des du de et ou
mais donc sur dans pour par avec sans selon depuis entre vers chez monsieur madame m mme assemblée sénat
parlement gouvernement république rassemblement national nationale ensemble france union droite gauche
démocrate démocrates socialistes écologiste écologistes horizons libertés indépendants outre mer territoires
nouveau nouvelle front populaire insoumise conseil constitutionnel cour premier première ministre président
présidente commission groupe hémicycle europe européen européenne paris loi lois texte projet proposition
réforme amendement rapport mission plan budget scrutin vote
""".split())
MOTIF_NUMERO_SCRUTIN = re.compile(r"scrutin(?:\s+public)?(?:\s+solennel)?\s*(?:n\s*[°o]\.?\s*)?(\d{1,5})\b", re.IGNORECASE)
MOTIF_MAJUSCULE = re.compile(rf"(?<![\w-])[{MAJ}]")


def personne_citee(question: str) -> str | None:
    """Nom de famille d'une personne nommée « Prénom Nom » dans la question (None sinon)."""
    # Chaque mot à majuscule est essayé comme prénom (« Selon Didier Lemaire » : « Selon » puis « Didier »).
    for debut in (m.start() for m in MOTIF_MAJUSCULE.finditer(question)):
        correspondance = MOTIF_PERSONNE.match(question, debut)
        if correspondance is None:
            continue
        prenom, nom = correspondance.groups()
        if prenom.lower() in PAS_UN_PRENOM or nom.split()[0].lower() in PAS_UN_PRENOM - {"de", "du", "des", "le", "la"}:
            continue
        famille = nom_de_famille(nom)
        if len(famille) >= 3:
            return famille
    return None


def appels_recherche_automatique(question: str, selection: tuple[str, ...] | list[str] = SELECTION_DEFAUT) -> list[Any]:
    """Appels d'outils lancés par le serveur quand le modèle n'en a appelé aucun : les deux premiers
    endpoints de recherche choisis par le journaliste (liste vide si aucun ne convient).

    Question sur une personne nommée (« Comment a voté Didier Lemaire sur le scrutin n° 1234 ? ») :
    chercher_depute, et resultat_scrutin si un numéro de scrutin est donné ; pas de recherche plein texte.
    Question sur un scrutin numéroté : resultat_scrutin (question de vote) ou lire_scrutin, seul."""
    personne = personne_citee(question)
    numero = MOTIF_NUMERO_SCRUTIN.search(question)
    if personne and "chercher_depute" in selection:
        candidats = [("chercher_depute", {"nom": personne})]
        if numero:
            candidats.append(("resultat_scrutin", {"id": f"VTANR5L{LEGISLATURE}V{int(numero.group(1))}"}))
        return _appels_serveur(candidats, selection)
    cles = mots_cles(question)
    if numero:  # « Que dit le scrutin n° 1234 ? », « Comment a voté le groupe X sur le scrutin n° 1234 ? »
        prefere = "resultat_scrutin" if re.search(r"\bvot", question, re.IGNORECASE) else "lire_scrutin"
        for nom in dict.fromkeys((prefere, "lire_scrutin", "resultat_scrutin")):
            if nom in selection:  # un seul appel, sur le scrutin désigné
                return _appels_serveur([(nom, {"id": f"VTANR5L{LEGISLATURE}V{int(numero.group(1))}"})], selection)
    if cles:
        candidats = [
            ("rechercher", {"q": cles, "limit": 5}), ("derniers_scrutins", {"recherche": cles, "limite": 5}),
            ("senat_dossiers", {"recherche": cles}), ("amendements_deposes", {"recherche": cles, "limite": 5}),
            ("textes_deposes", {"recherche": cles, "limite": 5}), ("senat_amendements", {"recherche": cles, "limite": 5}),
        ]
    else:  # question générale d'actualité (« quoi de neuf ? »)
        candidats = [
            ("derniers_scrutins", {"limite": 8}), ("agenda_seances", {}), ("fil_evenements", {}),
            ("senat_derniers_scrutins", {"limite": 8}), ("senat_agenda", {}),
        ]
    return _appels_serveur(candidats, selection)


def _appels_serveur(candidats: list[tuple[str, dict[str, Any]]], selection: tuple[str, ...] | list[str]) -> list[Any]:
    """Les deux premiers candidats choisis par le journaliste, au format des `tool_calls` du SDK."""
    specs = [(nom, arguments) for nom, arguments in candidats if nom in selection][:2]
    return [
        SimpleNamespace(
            id=f"recherche_auto_{indice}",
            type="function",
            function=SimpleNamespace(name=nom, arguments=json.dumps(arguments, ensure_ascii=False)),
        )
        for indice, (nom, arguments) in enumerate(specs, start=1)
    ]


JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)


# --------------------------------------------------------------------------
# Paramètres
# --------------------------------------------------------------------------


def _entier_env(nom: str, defaut: int, minimum: int = 0) -> int:
    brut = os.environ.get(nom, "").strip()
    if not brut:
        return defaut
    try:
        return max(minimum, int(brut))
    except ValueError as erreur:
        raise SystemExit(f"{nom} doit être un entier (valeur actuelle : {brut!r})") from erreur


def _booleen_env(nom: str, defaut: bool) -> bool:
    brut = os.environ.get(nom, "").strip().lower()
    if not brut:
        return defaut
    return brut in ("1", "true", "oui", "yes", "on")


@dataclass(frozen=True)
class Parametres:
    port: int
    reflexion: bool  # False : chat_template_kwargs {"enable_thinking": false}
    # True : réflexion activée au 1er appel du modèle seulement. Avec la réflexion, Qwen3.8-27B émet
    # des `tool_calls` natifs et choisit lui-même ses appels Hémicycle ; sans, il répond souvent sans
    # chercher. Les tours suivants (rédaction à partir des résultats) restent rapides.
    reflexion_premier_tour: bool
    max_tokens: int  # sans réflexion (CHATBOT_MAX_TOKENS)
    temperature: float
    max_credits_question: int  # budget par défaut d'une question
    max_credits_plafond: int  # budget maximal qu'un journaliste peut choisir pour une question
    max_appels_plafond: int  # nombre maximal d'appels d'outils qu'un journaliste peut choisir
    max_credits_serveur: int  # plafond depuis le démarrage du serveur (compteur en mémoire)
    cache_s: int  # durée de vie du cache des résultats d'outils
    concurrence_llm: int
    trace: str | None  # fichier JSONL : question, résultats d'outils vus par le modèle, réponse


def charger_parametres() -> Parametres:
    load_dotenv(FICHIER_ENV, override=False)
    reflexion = _booleen_env("CHATBOT_REFLEXION", False)
    return Parametres(
        port=_entier_env("CHATBOT_PORT", 8000, 1),
        reflexion=reflexion,
        reflexion_premier_tour=_booleen_env("CHATBOT_REFLEXION_PREMIER_TOUR", True),
        # La réflexion compte dans les tokens de sortie : prévoir large quand elle est active.
        max_tokens=_entier_env("CHATBOT_MAX_TOKENS", 1800, 100),
        temperature=0.3,
        max_credits_question=_entier_env("CHATBOT_MAX_CREDITS_QUESTION", 10, 1),
        max_credits_plafond=_entier_env("CHATBOT_MAX_CREDITS_QUESTION_PLAFOND", 30, 1),
        max_appels_plafond=_entier_env("CHATBOT_MAX_TOOL_CALLS_PLAFOND", 8, 1),
        max_credits_serveur=_entier_env("CHATBOT_MAX_CREDITS_SERVEUR", 300, 0),
        cache_s=_entier_env("CHATBOT_CACHE_S", 600, 0),
        concurrence_llm=_entier_env("CHATBOT_CONCURRENCE_LLM", 1, 1),
        trace=os.environ.get("CHATBOT_TRACE", "").strip() or None,
    )


# --------------------------------------------------------------------------
# Prompt système
# --------------------------------------------------------------------------


def _date_fr(jour: date) -> str:
    return jour.strftime("%d/%m/%Y")


def _date_longue(jour: date) -> str:
    return f"{JOURS[jour.weekday()]} {jour.day} {MOIS[jour.month - 1]} {jour.year}"


def semaine_en_cours(aujourd_hui: date) -> tuple[date, date]:
    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())
    return lundi, lundi + timedelta(days=6)


def consignes_outils(selection: list[str] | tuple[str, ...], aujourd_hui: date) -> str:
    """Une ligne de méthode par endpoint choisi par le journaliste (dans l'ordre du catalogue)."""
    lignes = [f"   - {remplacer_jours(e.consigne, aujourd_hui)}" for e in ENDPOINTS if e.nom in selection]
    if not any(PAR_NOM[nom].categorie == "senat" for nom in selection if nom in PAR_NOM):
        lignes.append("   - Les outils disponibles couvrent l'Assemblée nationale, pas le Sénat.")
    return "\n".join(lignes)


def prompt_systeme(aujourd_hui: date, max_appels: int, selection: list[str] | tuple[str, ...] = SELECTION_DEFAUT) -> str:
    lundi, dimanche = semaine_en_cours(aujourd_hui)
    return f"""Tu es l'assistant de veille parlementaire d'une rédaction. Des journalistes t'interrogent sur l'actualité du Parlement pour préparer un rapport mensuel.

Aujourd'hui : {_date_longue(aujourd_hui)}. Semaine en cours : du lundi {_date_fr(lundi)} au dimanche {_date_fr(dimanche)}.

Méthode, pour CHAQUE question :
1. Ta première action est TOUJOURS d'appeler des outils ({max_appels} appels au plus ; tu peux en appeler plusieurs à la fois). Ne réponds jamais avant d'avoir appelé un outil. Outils choisis par le journaliste pour cette question :
{consignes_outils(selection, aujourd_hui)}
2. Approfondis avant de répondre : une liste ou une recherche ne suffit pas. Pour les deux ou trois faits les plus importants trouvés, appelle les outils de détail disponibles parmi ceux ci-dessus (contenu et étapes du texte ou du dossier, décompte et positions des groupes d'un scrutin, suite au Sénat, ordre du jour à venir), tant qu'il te reste des appels.
3. Puis réponds UNIQUEMENT avec ce que contiennent les résultats des outils. Tu ne sais rien du Parlement par toi-même : chaque fait (date, nom, chiffre, résultat, intitulé, étape) doit figurer dans un résultat d'outil de cette conversation. N'utilise jamais tes connaissances propres, même pour compléter, contextualiser ou corriger.
4. Si, après les appels d'outils, les résultats ne contiennent pas l'information demandée, réponds seulement : « {MESSAGE_INTROUVABLE} »

Identifiants : scrutin VTANR5L17V<numéro> (VTANR5L17V1234 = scrutin n° 1234) ; député PA<chiffres> ; texte PRJLANR5L17B<numéro> (projet de loi) ou PIONANR5L17B<numéro> (proposition de loi) ; dossier DLR5L17N<chiffres> ; amendement AMANR5L17….

Forme de la réponse : une note de veille en français, claire et utile à un journaliste, lisible en trente secondes. Modèle (les éléments entre chevrons sont à remplacer ; une section sans contenu disparaît) :

**En bref** : <une ou deux phrases, 40 mots au plus : le fait le plus important et son chiffre clé>

### <Titre de section : le texte ou le sujet, 2 à 6 mots>
- **<JJ/MM/AAAA> · <sort ou étape>** : <le fait, dit simplement> (<source>)

### Chiffres clés
- <un décompte ou une comparaison, chiffres à l'appui> (<source>)

### À suivre
- **<échéance ou étape à venir>** : <ce qui doit se passer> (<source>)

Règles de fond :
- Ne retiens que les faits qui portent sur le sujet de la question ; écarte un résultat hors sujet même si un outil l'a renvoyé.
- Commence par ce qui existe ou s'est passé (textes, votes, étapes), pas par ce qui manque.
- Dis ce que fait un texte ou un amendement (son objet, en quelques mots tirés des résultats) plutôt que son numéro ou son article.
- Regroupe ce qui se ressemble : plusieurs amendements sur un même sujet ou un même jour tiennent en une puce (« trois amendements sur l'indemnisation des sinistrés, tous rejetés le 12/11/2026 »). Ne détaille à part que les plus marquants : ceux du Gouvernement, ceux adoptés, les votes les plus serrés.

Règles de forme :
- Adapte la longueur à la question. Question précise (un vote, un député, une date) : « En bref » puis 1 à 3 puces, sans titre de section. Question large (la semaine, un texte, un thème) : 2 à 4 sections, 10 puces au plus en tout, 300 mots au plus.
- Une puce = un fait, 25 mots au plus, qui commence en gras par la date et le sort ou l'étape : « **12/11/2026 · Rejeté** », « **15/09/2026 · Déposée** », « **10/11/2026 · En séance** ». Vote : « rejeté (25 pour, 49 contre) », abstentions seulement si elles ne sont pas nulles. Auteur et groupe si les résultats les donnent.
- Aucun code dans les phrases : jamais d'identifiant (DLR…, PRJL…, PION…, PA…, VTANR…, AMANR…, PO…), ni « texte n° », « dossier », numéro d'amendement ou d'article, sauf si la question les demande. Les numéros vont seulement dans la source finale.
- Termine chaque puce par UNE seule source entre parenthèses, la plus précise : « (scrutin n° 1234) », « (texte n° 567) », « (amendement n° 89) », « (scrutin du Sénat n° 99) », « (fiche du député) » ou « (ordre du jour du JJ/MM/AAAA) ». Pas de source dans « En bref » ni dans les titres.
- Intitulés : l'intitulé exact à la première mention, ensuite une désignation courte tirée de cet intitulé (« la proposition de loi sur les incendies volontaires »). Sigles admis : PLF, PLFSS, CMP et les sigles de groupes donnés par les résultats.
- « Chiffres clés » (1 à 3 puces, question large seulement) : des décomptes ou comparaisons que l'on peut refaire avec les chiffres des résultats, chiffres à l'appui (« 3 propositions de loi déposées depuis le 23/07/2026 », « 49 voix contre, 25 pour »). N'écris « unanimité », « large » ou « serré » que si les chiffres le montrent (unanimité = 0 voix dans un des camps). Jamais un zéro ni une absence (« 0 scrutin… ») dans les chiffres clés. Aucune cause, aucune interprétation, aucun pronostic.
- Cohérence : compte les éléments de ta propre liste avant d'écrire un total ; un même nombre partout (« En bref », puces, chiffres clés).
- « À suivre » : uniquement ce qui reste à venir après aujourd'hui ({_date_fr(aujourd_hui)}) — séance prévue à une date future, texte ou amendement en attente d'examen, transmission au Sénat, commission mixte paritaire. En gras, l'échéance ou l'étape (« **Séance du 18/11/2026** », « **En attente d'examen** »), jamais une date passée. Rien à venir dans les résultats : pas de section. N'invente jamais de suite.
- N'écris qu'un fait est absent que si un outil l'a vérifié, et cite cet outil.
- Chiffres et intitulés exacts. Ton neutre, phrases courtes, sans qualificatif. Gras seulement pour « En bref » et le début des puces. Pas de liens (les sources sont affichées à part), pas de tableau, pas de conclusion."""


def mois_long(mois: str) -> str:
    """« 2026-10 » → « octobre 2026 » ; « demo » → « un mois fictif »."""
    if not re.fullmatch(r"\d{4}-\d{2}", mois):
        return "un mois fictif"
    annee, numero = mois.split("-")
    return f"{MOIS[int(numero) - 1]} {annee}"


def prompt_lecteur(rapport: OutilsRapport, aujourd_hui: date, max_appels: int) -> str:
    """Prompt système complet du chatbot du rapport (requête avec un `mois`).

    Remplace `prompt_systeme` (outil de rédaction) au lieu de s'y ajouter : les deux se contredisaient
    (outil Hémicycle toujours en premier, réponse en puces, public de journalistes)."""
    numero = rapport.rapport
    periode = mois_long(numero.mois)
    publie = f", publié le {numero.meta['publie_le']}" if numero.meta.get("publie_le") else ""
    fictif = (
        "\nCe numéro est un exemple fictif : si le lecteur demande des chiffres réels, rappelle-le.\n"
        if numero.fictif else ""
    )
    return f"""Tu es l'assistant du rapport mensuel « {numero.titre} », qui couvre {periode} à l'Assemblée nationale. Un lecteur t'interroge depuis la page où il lit ce numéro{publie}, rédigé par la rédaction à partir des données d'Hémicycle. Vouvoie-le.
Aujourd'hui : {_date_longue(aujourd_hui)}.
{fictif}
TES SOURCES, par ordre de priorité
1. Le rapport ci-dessous : vérifié par la rédaction, il fait foi.
2. Les outils Hémicycle : données publiques consultées en direct, NON vérifiées par la rédaction. Ils complètent le rapport (détail d'un vote, texte non traité, actualité postérieure au numéro).
Tu ne sais rien du Parlement par toi-même : chaque fait (date, nom, chiffre, résultat, intitulé) doit figurer dans le rapport ou dans un résultat d'outil de cette conversation. N'utilise jamais tes connaissances propres, même pour compléter, contextualiser ou corriger.

RÈGLES ÉDITORIALES
- Neutralité : des faits et des votes ; ni opinion, ni jugement, ni qualificatif (« historique », « camouflet »…), ni pronostic. Ne prête pas d'intentions aux députés ou aux groupes. Ne donne jamais de consigne de vote.
- Désigne les groupes et les textes par leur nom exact, tel qu'écrit dans les sources.
- Si le lecteur demande un avis (« qui a raison ? », « est-ce une bonne loi ? »), donne les faits disponibles sans trancher.
- « Je ne sais pas » vaut mieux qu'une réponse inventée.

=== RAPPORT DU MOIS (chaque section est précédée de son identifiant entre crochets) ===
{numero.texte_pour_prompt()}

=== MÉTHODE, pour chaque question ===
{rapport.consigne_prompt()}

Classe d'abord la question :
A. Traitée par le rapport → surligner_section, puis réponds avec le texte du rapport, sans outil Hémicycle.
B. Traitée en partie par le rapport, mais le lecteur veut un détail qu'il ne contient pas (vote d'un groupe sur un scrutin précis, suite d'un texte cité) → surligner_section, puis les outils Hémicycle pour le détail. Sépare clairement ce qui vient du rapport et ce qui vient d'Hémicycle.
C. Sur le Parlement mais absente du rapport → outils Hémicycle seulement ({max_appels} appels au plus), aucune section surlignée.
   - Derniers votes : derniers_scrutins. Ordre du jour : agenda_seances. « Où en est le texte sur X ? » : derniers_scrutins (recherche = mots-clés de X, sans « depuis ») et rechercher (q = mots-clés de X). Positions des groupes : positions_groupes (10 scrutins au plus par appel).
   - Un député précis (« Quel est le groupe de X ? », « Que fait la députée Y ? », « Comment a voté X sur le scrutin n° N ? ») : d'abord chercher_depute (nom = son nom de famille seul ; anciens = true pour un ancien député), qui donne son identifiant PA…, son groupe actuel et sa profession. Puis, selon la question : lire_acteur (identifiant PA…) pour ses mandats et fonctions en cours, ou resultat_scrutin (VTANR5L17V<N>) pour son vote, où il figure par son nom dans le vote de son groupe ; s'il n'y figure pas, dis qu'il ne fait pas partie des votants de ce scrutin. Si plusieurs députés correspondent et que le prénom ne permet pas de choisir, cite-les et demande lequel le lecteur vise.
   - Les outils couvrent l'Assemblée nationale, pas le Sénat.
   - Si les résultats ne contiennent pas la réponse, réponds seulement : « {MESSAGE_INTROUVABLE} »
D. Sans lien avec le Parlement ni avec le rapport, ou simple demande d'opinion ou de pronostic → aucun outil ; réponds seulement : « {MESSAGE_HORS_PERIMETRE} »

Si le rapport et un résultat d'outil divergent sur la même période, donne le chiffre du rapport et signale l'écart sans trancher.
« Ce mois-ci » désigne le mois couvert par le numéro ({periode}), sauf si le lecteur parle explicitement d'aujourd'hui.

=== FORME DE LA RÉPONSE ===
- En français, clair pour un lecteur non spécialiste. Commence par la réponse elle-même (le chiffre, le résultat du vote, l'étape du texte).
- Chiffres et intitulés repris exactement. Si un terme technique est indispensable (scrutin solennel, cohésion), explique-le en quelques mots, avec la définition du rapport s'il en donne une.
- Source après chaque fait, entre parenthèses : (section « Cohésion des groupes ») ou, pour Hémicycle, (scrutin n° 1234, non vérifié par la rédaction) ou (fiche du député, non vérifiée par la rédaction).
- Pas de liens : les sources sont affichées à part.

Exemples de forme (contenu fictif, à ne jamais réutiliser) :
- « Le groupe X a voté comme la majorité de ses membres dans N % des scrutins (section « Cohésion des groupes »). »
- « Le rapport n'en parle pas. D'après Hémicycle, le texte sur X a été adopté le JJ/MM/AAAA (scrutin n° N, non vérifié par la rédaction). »"""


# --------------------------------------------------------------------------
# Outils locaux : « l'actualité » via `interroger`, restreint côté serveur
# --------------------------------------------------------------------------

OUTIL_DERNIERS_SCRUTINS: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "derniers_scrutins",
        "description": (
            "Scrutins publics de l'Assemblée nationale (17e législature), du plus récent au plus ancien : "
            "identifiant, numéro, date, objet, résultat et décompte. Pour l'actualité (« cette semaine », "
            "« derniers votes ») ou pour suivre un texte (paramètre recherche). 1 crédit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "depuis": {"type": "string", "description": "Date de début incluse, AAAA-MM-JJ."},
                "jusqu_a": {"type": "string", "description": "Date de fin incluse, AAAA-MM-JJ."},
                "recherche": {
                    "type": "string",
                    "description": "Mots-clés en français, cherchés dans l'objet des scrutins et l'exposé des "
                    "amendements votés (ex. « aide à mourir »).",
                },
                "solennels": {
                    "type": "boolean",
                    "description": "true : seulement les scrutins publics solennels (votes sur l'ensemble d'un texte).",
                },
                "limite": {
                    "type": "integer", "minimum": 1, "maximum": 20,
                    "description": "Nombre de scrutins (10 par défaut).",
                },
            },
            "additionalProperties": False,
        },
    },
}

OUTIL_AGENDA_SEANCES: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "agenda_seances",
        "description": (
            "Ordre du jour des séances publiques de l'Assemblée nationale sur une période (par défaut, la "
            "semaine en cours) : jour, heure et points inscrits (textes en discussion). Avec commissions = "
            "true, ajoute les réunions de commission. 1 crédit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "depuis": {"type": "string", "description": "Date de début incluse, AAAA-MM-JJ (défaut : lundi de la semaine)."},
                "jusqu_a": {"type": "string", "description": "Date de fin incluse, AAAA-MM-JJ (défaut : dimanche de la semaine)."},
                "commissions": {"type": "boolean", "description": "Inclure les réunions de commission (plus volumineux)."},
            },
            "additionalProperties": False,
        },
    },
}

OUTILS_LOCAUX = {
    "derniers_scrutins": OUTIL_DERNIERS_SCRUTINS,
    "agenda_seances": OUTIL_AGENDA_SEANCES,
}
COLONNES_SCRUTINS = [
    "uid", "numero", "date_scrutin", "titre", "sort_libelle", "libelle_type_vote",
    "nb_pour", "nb_contre", "nb_abstentions",
]
COLONNES_REUNIONS = ["uid", "type_reunion", "debut", "etat", "odj_resume", "points_odj"]
MAX_JOURS_AGENDA = 31
# Avec la réflexion, les tokens de réflexion comptent dans la sortie : prévoir large.
MAX_TOKENS_AVEC_REFLEXION = 6000


class ErreurArguments(ValueError):
    """Arguments invalides pour un outil local : le message est renvoyé au modèle."""


def _date_argument(valeur: Any, nom: str) -> date | None:
    if valeur in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valeur).strip()[:10])
    except ValueError as erreur:
        raise ErreurArguments(f"« {nom} » doit être une date AAAA-MM-JJ (reçu : {valeur!r}).") from erreur


def _resultat_scrutin(sort_libelle: str | None) -> str | None:
    if not sort_libelle:
        return None
    texte = sort_libelle.lower()
    if "pas adopté" in texte:
        return "rejeté"
    if "adopté" in texte:
        return "adopté"
    return sort_libelle


def _type_vote(libelle: str | None) -> str | None:
    if libelle and libelle.lower().startswith("scrutin public "):
        return libelle[len("scrutin public "):]
    return libelle


def arguments_derniers_scrutins(arguments: dict[str, Any]) -> dict[str, Any]:
    """Traduit les arguments de `derniers_scrutins` en appel `interroger` (jeu `scrutins`)."""
    depuis = _date_argument(arguments.get("depuis"), "depuis")
    jusqu_a = _date_argument(arguments.get("jusqu_a"), "jusqu_a")
    try:
        limite = min(20, max(1, int(arguments.get("limite") or 10)))
    except (TypeError, ValueError) as erreur:
        raise ErreurArguments("« limite » doit être un entier entre 1 et 20.") from erreur
    filtres: list[dict[str, Any]] = [{"colonne": "legislature", "op": "eq", "valeur": LEGISLATURE}]
    if depuis:
        filtres.append({"colonne": "date_scrutin", "op": "gte", "valeur": depuis.isoformat()})
    if jusqu_a:
        filtres.append({"colonne": "date_scrutin", "op": "lte", "valeur": jusqu_a.isoformat()})
    if arguments.get("solennels") is True:
        filtres.append({"colonne": "libelle_type_vote", "op": "eq", "valeur": "scrutin public solennel"})
    appel: dict[str, Any] = {
        "jeu": "scrutins", "filtres": filtres, "tri": "date_scrutin", "ordre": "desc",
        "limite": limite, "colonnes": COLONNES_SCRUTINS,
    }
    recherche = str(arguments.get("recherche") or "").strip()
    if recherche:
        if len(recherche) < 2:
            raise ErreurArguments("« recherche » doit faire au moins 2 caractères.")
        appel["recherche"] = recherche[:200]
    return appel


def compacter_scrutins(donnees: Any, limite: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Réponse du jeu `scrutins` → (contenu pour le modèle, une source par scrutin)."""
    lignes = [ligne for ligne in (donnees or {}).get("lignes") or [] if isinstance(ligne, dict)]
    lignes.sort(key=lambda l: (str(l.get("date_scrutin") or ""), int(l.get("numero") or 0)), reverse=True)
    scrutins, sources = [], []
    for ligne in lignes:
        jour = _date_argument(ligne.get("date_scrutin"), "date_scrutin")
        date_fr = _date_fr(jour) if jour else None
        scrutins.append({
            "id": ligne.get("uid"),
            "numero": ligne.get("numero"),
            "date": date_fr,
            "objet": ligne.get("titre"),
            "resultat": _resultat_scrutin(ligne.get("sort_libelle")),
            "type": _type_vote(ligne.get("libelle_type_vote")),
            "pour": ligne.get("nb_pour"),
            "contre": ligne.get("nb_contre"),
            "abstentions": ligne.get("nb_abstentions"),
        })
        if ligne.get("numero") is not None:
            sources.append({
                "type": "hemicycle",
                "outil": "derniers_scrutins",
                "editeur": EDITEUR_AN,
                "url": url_scrutin(ligne["numero"]),
                "licence": LICENCE_AN,
                "libelle": f"Scrutin n° {ligne['numero']}" + (f" du {date_fr}" if date_fr else ""),
                "titre": (ligne.get("titre") or "")[:160] or None,
                "ref": ligne.get("uid"),
                "numero": ligne.get("numero"),
                "nature": "scrutin",
                "verifie_par_la_redaction": False,
            })
    contenu: dict[str, Any] = {
        "source": f"{EDITEUR_AN}, open data ({LICENCE_AN}), via Hémicycle",
        "nombre": len(scrutins),
        "scrutins": scrutins,
    }
    if not scrutins:
        contenu["message"] = "Aucun scrutin trouvé pour ces critères."
    elif len(scrutins) >= limite:
        contenu["remarque"] = f"Les {limite} plus récents seulement ; d'autres scrutins correspondent peut-être."
    return contenu, sources


def arguments_agenda(arguments: dict[str, Any], aujourd_hui: date) -> tuple[dict[str, Any], date, date]:
    """Traduit les arguments de `agenda_seances` en appel `interroger` (jeu `reunions`)."""
    lundi, dimanche = semaine_en_cours(aujourd_hui)
    depuis = _date_argument(arguments.get("depuis"), "depuis") or lundi
    jusqu_a = _date_argument(arguments.get("jusqu_a"), "jusqu_a") or max(dimanche, depuis)
    if jusqu_a < depuis:
        raise ErreurArguments("« jusqu_a » doit être postérieure à « depuis ».")
    if (jusqu_a - depuis).days > MAX_JOURS_AGENDA:
        jusqu_a = depuis + timedelta(days=MAX_JOURS_AGENDA)
    commissions = arguments.get("commissions") is True
    filtres: list[dict[str, Any]] = [
        {"colonne": "debut", "op": "gte", "valeur": depuis.isoformat()},
        {"colonne": "debut", "op": "lt", "valeur": (jusqu_a + timedelta(days=1)).isoformat()},
        {"colonne": "etat", "op": "neq", "valeur": "Supprimé"},
    ]
    if not commissions:
        filtres.append({"colonne": "type_reunion", "op": "eq", "valeur": "seance"})
    appel = {
        "jeu": "reunions", "filtres": filtres, "tri": "debut", "ordre": "asc",
        "limite": 40 if commissions else 25, "colonnes": COLONNES_REUNIONS,
    }
    return appel, depuis, jusqu_a


def _quand(debut: Any) -> str | None:
    try:
        moment = datetime.fromisoformat(str(debut)).astimezone(FUSEAU)
    except ValueError:
        return None
    return f"{JOURS[moment.weekday()]} {moment:%d/%m/%Y %H:%M}"


def compacter_agenda(donnees: Any, depuis: date, jusqu_a: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Réponse du jeu `reunions` → (contenu pour le modèle, sources)."""
    reunions = []
    for ligne in (donnees or {}).get("lignes") or []:
        if not isinstance(ligne, dict):
            continue
        points: list[str] = []
        for point in ligne.get("points_odj") or []:
            if isinstance(point, dict) and point.get("etat") != "Supprimé" and point.get("objet"):
                if point["objet"] not in points:
                    points.append(point["objet"])
        if not points and ligne.get("odj_resume"):
            points.append(" ".join(str(ligne["odj_resume"]).split())[:300])
        reunions.append({
            "quand": _quand(ligne.get("debut")),
            "type": "séance publique" if ligne.get("type_reunion") == "seance" else ligne.get("type_reunion"),
            "etat": ligne.get("etat"),
            "points": points,
        })
    contenu: dict[str, Any] = {
        "source": f"{EDITEUR_AN}, open data ({LICENCE_AN}), via Hémicycle",
        "periode": f"du {_date_fr(depuis)} au {_date_fr(jusqu_a)}",
        "nombre": len(reunions),
        "reunions": reunions,
    }
    sources = []
    if reunions:
        sources.append({
            "type": "hemicycle",
            "outil": "agenda_seances",
            "editeur": EDITEUR_AN,
            "url": URL_OPEN_DATA_AN,
            "licence": LICENCE_AN,
            "libelle": f"Ordre du jour de l'Assemblée, {contenu['periode']} (open data)",
            "nature": "agenda",
            "verifie_par_la_redaction": False,
        })
    else:
        contenu["message"] = "Aucune séance trouvée sur cette période."
    return contenu, sources


# --------------------------------------------------------------------------
# Sources : liens lisibles, citées ou seulement consultées
# --------------------------------------------------------------------------

MOTIF_TEXTE = re.compile(r"(PRJL|PION)AN(R5)L(\d+)B(\d+)")
MOTIF_SCRUTIN = re.compile(r"VTANR5L(\d+)V(\d+)")
MOTIF_DOCUMENT = re.compile(r"/opendata/([A-Z]{4})(AN|SN)([A-Z0-9]+)\.json")
MOTIF_FICHE_DEPUTE = re.compile(r"/dyn/deputes/(PA\d+)")
MOTIF_PAGE_SCRUTIN = re.compile(r"assemblee-nationale\.fr/dyn/(\d+)/scrutins/(\d+)")  # resultat_scrutin, lire_scrutin
NATURES_DOCUMENT = {"PION": "Proposition de loi", "PRJL": "Projet de loi", "RAPP": "Rapport", "AVIS": "Avis",
                    "RION": "Proposition de résolution"}


def enrichir_source(source: dict[str, Any]) -> dict[str, Any]:
    """Ajoute un lien lisible (page de l'Assemblée au lieu du fichier JSON open data),
    une référence et un libellé quand on sait les déduire de l'URL."""
    source = dict(source)
    url = str(source.get("url") or "")
    if source.get("ref"):
        return source
    texte = MOTIF_TEXTE.search(url)
    scrutin = MOTIF_SCRUTIN.search(url)
    document = MOTIF_DOCUMENT.search(url)
    fiche = MOTIF_FICHE_DEPUTE.search(url)
    page_scrutin = MOTIF_PAGE_SCRUTIN.search(url)
    if fiche:  # lire_acteur : page publique du député (nom ajouté par completer_source_acteur)
        source["ref"] = fiche.group(1)
        source["nature"] = "depute"
        source["libelle"] = f"Fiche du député {fiche.group(1)}"
    elif page_scrutin:  # déjà la page publique du scrutin : référence et libellé seulement
        legislature, numero = page_scrutin.groups()
        source["ref"] = f"VTANR5L{legislature}V{numero}"
        source["numero"] = int(numero)
        source["nature"] = "scrutin"
        source["libelle"] = f"Scrutin n° {int(numero)}"
    elif texte and texte.group(0) + ".json" in url:
        nature, _, legislature, numero = texte.groups()
        genre = "projet-loi" if nature == "PRJL" else "proposition-loi"
        source["url_donnees"] = url
        source["url"] = f"https://www.assemblee-nationale.fr/dyn/{legislature}/textes/l{legislature}b{numero}_{genre}"
        source["ref"] = texte.group(0)
        source["numero"] = int(numero)
        source["nature"] = "texte"
        source["libelle"] = f"{'Projet' if nature == 'PRJL' else 'Proposition'} de loi n° {int(numero)}"
    elif scrutin:
        legislature, numero = scrutin.groups()
        source["url_donnees"] = url
        source["url"] = url_scrutin(int(numero), int(legislature))
        source["ref"] = scrutin.group(0)
        source["numero"] = int(numero)
        source["nature"] = "scrutin"
        source["libelle"] = f"Scrutin n° {int(numero)}"
    elif document:
        # Autres documents (rapports, textes adoptés, textes du Sénat) : pas de page lisible vérifiée,
        # on garde le fichier open data mais on donne un libellé et une référence.
        prefixe, chambre, reste = document.groups()
        ref = f"{prefixe}{chambre}{reste}"
        nature = NATURES_DOCUMENT.get(prefixe, "Document")
        source["ref"] = ref
        source["nature"] = "document"
        numero = re.fullmatch(r"R5L\d+B(\d+)", reste) if chambre == "AN" else None
        adopte = re.fullmatch(r"R5L\d+(?:BTA|TAP)(\d+)", reste) if chambre == "AN" else None
        if numero:
            source["numero"] = int(numero.group(1))
            source["libelle"] = f"{nature} n° {int(numero.group(1))}"
        elif adopte:
            source["numero"] = int(adopte.group(1))
            source["libelle"] = f"Texte adopté n° {int(adopte.group(1))}"
        else:
            source["libelle"] = f"{nature} {'du Sénat' if chambre == 'SN' else ''} ({ref})".replace("  ", " ")
    return source


def completer_source_acteur(resultat: ResultatOutil) -> None:
    """lire_acteur : ajoute civilité, prénom et nom à la source « fiche du député », pour la reconnaître
    dans la réponse (qui cite le nom du député, rarement son identifiant PA…)."""
    try:
        fiche = json.loads(resultat.texte_brut)
    except ValueError:
        return
    if not isinstance(fiche, dict) or not str(fiche.get("id") or "").startswith("PA"):
        return
    for indice, source in enumerate(resultat.sources):
        if source.get("nature") == "depute" and source.get("ref") == fiche["id"]:
            identite = source_depute(fiche["id"], fiche.get("civilite"), fiche.get("prenom"), fiche.get("nom"))
            resultat.sources[indice] = {**source, "prenom": identite["prenom"], "nom": identite["nom"],
                                        "libelle": f"Fiche de {identite['libelle']}"}


def est_citee(source: dict[str, Any], reponse: str) -> bool:
    if source.get("nature") == "agenda":
        return "ordre du jour" in reponse.lower()
    ref = source.get("ref")
    if ref and ref in reponse:
        return True
    if nomme_le_depute(source, reponse):
        return True
    numero = source.get("numero")
    if numero is None:
        return False
    return re.search(rf"n\s*°\s*{int(numero)}(?!\d)", reponse) is not None


def choisir_sources(consultees: list[dict[str, Any]], reponse: str, max_sources: int = 8) -> list[dict[str, Any]]:
    """Sources citées dans la réponse d'abord (et sources générales sans référence) ;
    si rien n'est identifiable, les sources consultées, marquées `citee: false`."""
    uniques: dict[str, dict[str, Any]] = {}
    for source in consultees:
        cle = str(source.get("url") or "") + "|" + str(source.get("ref") or source.get("libelle") or "")
        uniques.setdefault(cle, source)
    sources = list(uniques.values())
    citees = [dict(s, citee=True) for s in sources if est_citee(s, reponse)]
    generales = [dict(s, citee=False) for s in sources if not s.get("ref") and not est_citee(s, reponse)]
    if citees:
        return (citees + generales)[:max_sources]
    return [dict(s, citee=False) for s in sources][:max_sources]


# --------------------------------------------------------------------------
# Vérification d'ancrage : chiffres et dates absents des résultats d'outils
# --------------------------------------------------------------------------

MOTIF_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
MOTIF_NOMBRE = re.compile(r"\d+(?:[.,]\d+)?")


def elements_non_retrouves(reponse: str, corpus: str) -> list[str]:
    """Dates et nombres (≥ 10) de la réponse qu'on ne retrouve pas dans ce que le modèle
    a reçu (question, prompt, résultats d'outils). Signal d'alerte, pas une preuve."""
    nombres_corpus = {n.lstrip("0") or "0" for n in re.findall(r"\d+", corpus)}
    manquants: list[str] = []

    def signaler(element: str) -> None:
        if element not in manquants:
            manquants.append(element)

    for correspondance in MOTIF_DATE.finditer(reponse):
        jour, mois, annee = correspondance.groups()
        jour, mois = f"{int(jour):02d}", f"{int(mois):02d}"
        candidats = [f"{jour}/{mois}/{annee}", f"{annee}-{mois}-{jour}"] if annee else [f"{jour}/{mois}/", f"-{mois}-{jour}"]
        if not any(c in corpus for c in candidats):
            signaler(correspondance.group(0))
    sans_dates = MOTIF_DATE.sub(" ", reponse)
    for nombre in MOTIF_NOMBRE.findall(sans_dates):
        entier = re.split(r"[.,]", nombre)[0]
        if len(entier.lstrip("0")) < 2:
            continue  # petits nombres (puces, « 2 scrutins »…) : trop de faux positifs
        if all((partie.lstrip("0") or "0") in nombres_corpus for partie in re.findall(r"\d+", nombre)):
            continue
        signaler(nombre)
    return manquants[:10]


MOTIF_APPEL_TEXTE = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.DOTALL)
MOTIF_FONCTION = re.compile(r"<function=([^>\s]+)>(.*?)(?:</function>|$)", re.DOTALL)
MOTIF_PARAMETRE = re.compile(r"<parameter=([^>\s]+)>(.*?)(?:</parameter>|(?=<parameter=)|$)", re.DOTALL)


def _valeur_parametre(brut: str) -> Any:
    """`17` → 17, `true` → True, `["a"]` → liste ; sinon la chaîne telle quelle."""
    try:
        valeur = json.loads(brut)
    except ValueError:
        return brut
    return valeur if not isinstance(valeur, str) else brut


def appels_outils_en_texte(texte: str, schemas: dict[str, set[str]]) -> list[Any]:
    """Appels d'outils écrits dans le texte de la réponse, que Featherless n'a pas convertis en `tool_calls`.

    Observé avec Qwen3.8-27B quand la réflexion est désactivée : format XML de Qwen3-Coder
    (``<tool_call><function=NOM><parameter=CLÉ>valeur</parameter></function></tool_call>``),
    parfois malformé (``<function=tool>`` avec le vrai nom dans ``<parameter=action>``,
    nom de paramètre tronqué). Le format JSON de Hermes (``{"name", "arguments"}``) est aussi accepté.
    Renvoie des objets au format des `tool_calls` du SDK (id, type, function.name, function.arguments).
    """
    appels: list[Any] = []
    for indice, bloc in enumerate(MOTIF_APPEL_TEXTE.findall(texte or "")):
        bloc = bloc.strip()
        nom: str | None = None
        arguments: dict[str, Any] = {}
        if bloc.startswith("{"):
            try:
                donnees = json.loads(bloc)
            except ValueError:
                donnees = {}
            if isinstance(donnees, dict):
                nom = donnees.get("name")
                arguments = donnees.get("arguments") or donnees.get("parameters") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
        else:
            fonction = MOTIF_FONCTION.search(bloc)
            if fonction:
                nom = fonction.group(1).strip()
                for cle, valeur in MOTIF_PARAMETRE.findall(fonction.group(2)):
                    arguments[cle.strip()] = _valeur_parametre(valeur.strip())
        if not isinstance(arguments, dict):
            arguments = {}
        if nom not in schemas:  # vrai nom rangé dans un paramètre (`action`, `name`…)
            for cle in ("action", "name", "tool", "outil", "function"):
                if arguments.get(cle) in schemas:
                    nom = arguments.pop(cle)
                    break
        if not nom:
            continue
        appels.append(SimpleNamespace(
            id=f"appel_texte_{indice + 1}",
            type="function",
            function=SimpleNamespace(name=nom, arguments=json.dumps(arguments, ensure_ascii=False)),
        ))
    return appels


def _sans_ponctuation(nom: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nom.lower())


ALIAS_PARAMETRES = {"recherche": "q", "query": "q", "requete": "q", "requête": "q", "texte": "q", "q": "recherche"}


def corriger_noms_parametres(arguments: dict[str, Any], proprietes: set[str]) -> dict[str, Any]:
    """Rattache un nom de paramètre approximatif au seul paramètre du schéma qui lui
    correspond (`jusqu` ou `jusquau` → `jusqu_a`, `recherche` → `q`). Les autres noms restent tels quels."""
    corriges = dict(arguments)
    for cle in [c for c in arguments if c not in proprietes]:
        alias = ALIAS_PARAMETRES.get(cle)
        if alias in proprietes and alias not in corriges:
            corriges[alias] = corriges.pop(cle)
            continue
        court = _sans_ponctuation(cle)
        candidats = [
            p for p in proprietes
            if court and (_sans_ponctuation(p).startswith(court) or court.startswith(_sans_ponctuation(p)))
        ]
        if len(candidats) == 1 and candidats[0] not in corriges:
            corriges[candidats[0]] = corriges.pop(cle)
    return corriges


MAX_PUCES = 14
MOTIF_PUCE = re.compile(r"^\s*([-*•]|\d+[.)])\s+")


def limiter_puces(texte: str, maximum: int = MAX_PUCES) -> tuple[str, bool]:
    """Garde les `maximum` premières puces (la consigne de brièveté n'est pas toujours suivie)."""
    lignes, gardees, nb_puces, coupe = texte.splitlines(), [], 0, False
    for ligne in lignes:
        if MOTIF_PUCE.match(ligne):
            nb_puces += 1
            if nb_puces > maximum:
                coupe = True
                continue
        elif coupe:
            continue
        gardees.append(ligne)
    return "\n".join(retirer_sections_vides(gardees)).strip(), coupe


def retirer_sections_vides(lignes: list[str]) -> list[str]:
    """Retire les titres « ### … » sans contenu avant le titre suivant ou la fin (section vide ou coupée)."""
    gardees: list[str] = []
    for i, ligne in enumerate(lignes):
        if ligne.lstrip().startswith("#"):
            suite = next((l for l in lignes[i + 1:] if l.strip()), None)
            if suite is None or suite.lstrip().startswith("#"):
                continue
        gardees.append(ligne)
    return gardees


def nettoyer_reponse(texte: str) -> str:
    """Retire un éventuel appel d'outil écrit en texte brut et les balises résiduelles."""
    texte = re.sub(r"<tool_call>.*?(</tool_call>|$)", "", texte or "", flags=re.DOTALL)
    texte = texte.replace("<think>", "").replace("</think>", "")
    return texte.strip()


def hors_perimetre(texte: str | None) -> bool:
    """Le modèle a répondu par le refus prévu (cas D du prompt lecteur), éventuellement reformulé à la marge."""
    normalise = (texte or "").replace("’", "'").lower()
    return "je ne peux répondre qu'aux questions" in normalise


def sortie_de_moderation(texte: str) -> bool:
    """Sortie d'un classifieur de modération (anomalie observée avec Qwen3-32B et des `tools`)."""
    return texte.lstrip().startswith("Safety:")


# --------------------------------------------------------------------------
# État du serveur et exécution des outils
# --------------------------------------------------------------------------


@dataclass
class EtatServeur:
    parametres: Parametres
    llm: ClientFeatherlessAsync
    hemicycle: OutilsHemicycle
    outils: list[dict[str, Any]]  # définitions de la sélection par défaut (chatbot du rapport, /chat sans « outils »)
    verrou_llm: asyncio.Semaphore
    definitions: dict[str, dict[str, Any]] = field(default_factory=dict)  # tous les endpoints disponibles
    indisponibles: dict[str, str] = field(default_factory=dict)  # endpoint → raison
    solde: int | None = None  # solde de crédits Hémicycle (dernier connu)
    cache: dict[tuple[str, str], tuple[float, ResultatOutil]] = field(default_factory=dict)
    credits_serveur: int = 0  # crédits Hémicycle consommés depuis le démarrage
    acces_refuse: int | None = None  # 401/402/403 renvoyé par Hémicycle
    demarre_le: str = field(default_factory=lambda: datetime.now(FUSEAU).isoformat(timespec="seconds"))

    @property
    def noms_outils(self) -> list[str]:
        return [outil["function"]["name"] for outil in self.outils]

    @property
    def schemas(self) -> dict[str, set[str]]:
        return {
            outil["function"]["name"]: set((outil["function"].get("parameters") or {}).get("properties") or {})
            for outil in self.outils
        }

    def masquer(self, texte: str) -> str:
        for cle in (self.llm.config.cle_api, self.hemicycle.config.cle_api):
            if cle:
                texte = texte.replace(cle, "***")
        return texte


def _refus(nom: str, contenu: str, compteur: CompteurConversation, tool_call_id: str | None,
           arguments: Any = None) -> ResultatOutil:
    """Refus local (sans appel réseau) ; compte comme une demande pour borner la boucle."""
    compteur.nb_demandes += 1
    compteur.nb_erreurs += 1
    compteur.caracteres_renvoyes += len(contenu)
    compteur.journal.append({"outil": nom, "statut": "refuse", "message": contenu[:300]})
    return ResultatOutil(
        outil=nom, contenu=contenu, tool_call_id=tool_call_id, erreur=True,
        arguments=arguments if isinstance(arguments, dict) else {},
    )


async def _executer_local(etat: EtatServeur, nom: str, arguments: dict[str, Any],
                          compteur: CompteurConversation, tool_call_id: str | None) -> ResultatOutil:
    """Outil local : appel `interroger` sur un jeu autorisé, puis réécriture compacte du résultat."""
    aujourd_hui = datetime.now(FUSEAU).date()
    try:
        if nom == "derniers_scrutins":
            appel = arguments_derniers_scrutins(arguments)
            depuis = jusqu_a = None
        else:
            appel, depuis, jusqu_a = arguments_agenda(arguments, aujourd_hui)
    except ErreurArguments as erreur:
        return _refus(nom, f"Erreur : {erreur}", compteur, tool_call_id, arguments)
    if appel["jeu"] not in JEUX_AUTORISES:  # garde-fou : jamais Orcet ni jeu dérivé
        return _refus(nom, "Erreur : jeu non autorisé.", compteur, tool_call_id, arguments)

    resultat = await etat.hemicycle.appeler("interroger", appel, compteur, tool_call_id=tool_call_id)
    resultat.outil, resultat.arguments = nom, dict(arguments)
    resultat.requete_hemicycle = {"outil": "interroger", "arguments": appel}
    if resultat.erreur:
        return resultat
    try:
        donnees = json.loads(resultat.texte_brut)
    except ValueError:
        return resultat  # format inattendu : on garde le résultat (tronqué) tel quel
    try:
        if nom == "derniers_scrutins":
            contenu, sources = compacter_scrutins(donnees, appel["limite"])
        else:
            contenu, sources = compacter_agenda(donnees, depuis, jusqu_a)
    except (TypeError, ValueError, AttributeError) as erreur:
        journal.warning("Compaction de %s impossible (%s) : résultat brut renvoyé.", nom, type(erreur).__name__)
        return resultat
    texte, resultat.tronque = tronquer(
        json.dumps(contenu, ensure_ascii=False, separators=(",", ":")),
        etat.hemicycle.config.max_caracteres_resultat,
    )
    compteur.caracteres_renvoyes += len(texte) - len(resultat.contenu)
    resultat.contenu, resultat.sources = texte, sources
    return resultat


async def _executer_jeu(etat: EtatServeur, nom: str, arguments: dict[str, Any],
                        compteur: CompteurConversation, tool_call_id: str | None) -> ResultatOutil:
    """Endpoint « jeu » de veille.py : un appel `interroger` sur UN jeu précis, puis compaction."""
    spec = SPECS_JEUX[nom]
    try:
        appel, contexte = appel_interroger(spec, arguments, datetime.now(FUSEAU).date())
    except ErreurArgumentsVeille as erreur:
        return _refus(nom, f"Erreur : {erreur}", compteur, tool_call_id, arguments)
    if appel["jeu"] not in JEUX_AUTORISES:  # garde-fou : jamais Orcet ni un jeu non prévu
        return _refus(nom, "Erreur : jeu non autorisé.", compteur, tool_call_id, arguments)
    resultat = await etat.hemicycle.appeler("interroger", appel, compteur, tool_call_id=tool_call_id)
    resultat.outil, resultat.arguments = nom, dict(arguments)
    resultat.requete_hemicycle = {"outil": "interroger", "arguments": appel}
    if resultat.erreur:
        return resultat
    try:
        contenu, sources = compacter_jeu(spec, json.loads(resultat.texte_brut), contexte)
    except (TypeError, ValueError, AttributeError, KeyError) as erreur:
        journal.warning("Compaction de %s impossible (%s) : résultat brut renvoyé.", nom, type(erreur).__name__)
        return resultat
    texte, resultat.tronque = tronquer(
        json.dumps(contenu, ensure_ascii=False, separators=(",", ":")),
        etat.hemicycle.config.max_caracteres_resultat,
    )
    compteur.caracteres_renvoyes += len(texte) - len(resultat.contenu)
    resultat.contenu = texte
    resultat.sources = [enrichir_source(source) for source in sources]
    return resultat


def cout_estime(nom: str) -> int:
    endpoint = PAR_NOM.get(nom)
    return endpoint.cout if endpoint else COUTS_CREDITS.get(nom, COUT_INCONNU)


async def executer_appel(etat: EtatServeur, tool_call: Any, compteur: CompteurConversation,
                         definitions: list[dict[str, Any]] | None = None,
                         max_credits: int | None = None) -> tuple[ResultatOutil, bool]:
    """Exécute un `tool_call` du modèle (ou du journaliste). Renvoie (résultat, servi depuis le cache ?).

    `definitions` : endpoints autorisés pour cette question (défaut : sélection par défaut) ;
    `max_credits` : budget de la question (défaut : CHATBOT_MAX_CREDITS_QUESTION)."""
    ident, nom, brut = lire_tool_call(tool_call)
    definitions = etat.outils if definitions is None else definitions
    noms = [d["function"]["name"] for d in definitions]
    if nom not in noms:
        return _refus(nom, f"Erreur : l'outil « {nom} » n'est pas disponible. Outils : {', '.join(noms)}.",
                      compteur, ident), False
    proprietes = next(set((d["function"].get("parameters") or {}).get("properties") or {})
                      for d in definitions if d["function"]["name"] == nom)
    if isinstance(brut, str):
        try:
            arguments = json.loads(brut) if brut.strip() else {}
        except ValueError:
            return _refus(nom, f"Erreur : arguments illisibles pour « {nom} » (JSON invalide).", compteur, ident), False
    else:
        arguments = brut or {}
    if not isinstance(arguments, dict):
        return _refus(nom, f"Erreur : les arguments de « {nom} » doivent être un objet JSON.", compteur, ident), False
    arguments = {cle: valeur for cle, valeur in arguments.items() if valeur is not None}
    arguments = corriger_noms_parametres(arguments, proprietes)

    # Cache : même outil, mêmes arguments, résultat récent → 0 crédit.
    cle_cache = (nom, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
    en_cache = etat.cache.get(cle_cache)
    if en_cache and time.monotonic() - en_cache[0] < etat.parametres.cache_s and not compteur.limite_atteinte:
        resultat = replace(en_cache[1], tool_call_id=ident, credits_factures=0, duree_s=0.0)
        compteur.nb_demandes += 1
        compteur.caracteres_renvoyes += len(resultat.contenu)
        compteur.journal.append({"outil": nom, "arguments": arguments, "statut": "cache", "credits": 0})
        return resultat, True

    # Plafonds de crédits (par question, et depuis le démarrage du serveur).
    cout = cout_estime(nom)
    deja = max(compteur.credits_estimes, compteur.credits_factures)
    budget = max_credits or etat.parametres.max_credits_question
    if not compteur.limite_atteinte:
        if deja + cout > budget:
            return _refus(nom, "Limite atteinte : budget de crédits de la question épuisé. N'appelle plus d'outil ; "
                          "réponds avec les résultats déjà obtenus.", compteur, ident, arguments), False
        if etat.credits_serveur + cout > etat.parametres.max_credits_serveur:
            return _refus(nom, "Limite atteinte : plafond de crédits du serveur épuisé. N'appelle plus d'outil ; "
                          "réponds avec les résultats déjà obtenus.", compteur, ident, arguments), False

    if nom in OUTILS_LOCAUX:
        resultat = await _executer_local(etat, nom, arguments, compteur, ident)
    elif nom in SPECS_JEUX:
        resultat = await _executer_jeu(etat, nom, arguments, compteur, ident)
    else:
        resultat = await etat.hemicycle.appeler(nom, arguments, compteur, tool_call_id=ident)
        resultat.sources = [enrichir_source(source) for source in resultat.sources]
        resultat.arguments = resultat.arguments or arguments
        if nom == "lire_acteur" and not resultat.erreur:
            completer_source_acteur(resultat)

    if resultat.credits_factures is not None:
        etat.credits_serveur += resultat.credits_factures
    if resultat.solde_restant is not None:
        etat.solde = resultat.solde_restant
    if resultat.fatal:
        etat.acces_refuse = resultat.statut_refus
        journal.error("Hémicycle refuse l'accès (HTTP %s) : vérifier la clé et le solde.", resultat.statut_refus)
    if not resultat.erreur and etat.parametres.cache_s:
        maintenant = time.monotonic()
        for cle in [c for c, (date_mise, _) in etat.cache.items() if maintenant - date_mise >= etat.parametres.cache_s]:
            del etat.cache[cle]  # purge des entrées expirées
        etat.cache[cle_cache] = (maintenant, resultat)
    return resultat, False


# --------------------------------------------------------------------------
# Boucle d'outils
# --------------------------------------------------------------------------


async def _appeler_llm(etat: EtatServeur, messages: list[dict[str, Any]],
                       outils: list[dict[str, Any]] | None, reflexion: bool,
                       schemas_extra: dict[str, set[str]] | None = None) -> ReponseChat:
    options = {
        "outils": outils,
        "sans_reflexion": not reflexion,
        "max_tokens": MAX_TOKENS_AVEC_REFLEXION if reflexion else etat.parametres.max_tokens,
        "temperature": etat.parametres.temperature,
    }
    async with etat.verrou_llm:
        reponse = await etat.llm.discuter(messages, **options)
        if sortie_de_moderation(reponse.texte) and not reponse.appels_outils:
            journal.warning("Sortie de modération au lieu d'une réponse (requête %s) : nouvel essai.", reponse.id_requete)
            reponse = await etat.llm.discuter(messages, **options)
    if outils and not reponse.appels_outils and "<tool_call>" in reponse.texte:
        appels = appels_outils_en_texte(reponse.texte, {**etat.schemas, **(schemas_extra or {})})
        if appels:
            journal.info("Appels d'outils écrits en texte, récupérés par le serveur : %s",
                         [(a.function.name, a.function.arguments) for a in appels])
            reponse.appels_outils = appels
            reponse.texte = reponse.texte.split("<tool_call>", 1)[0].strip()
            reponse.appels_en_texte = len(appels)  # type: ignore[attr-defined]
    return reponse


def _tracer(etat: EtatServeur, entree: dict[str, Any]) -> None:
    """Ajoute une ligne au fichier de trace (débogage : vérifier sur quoi le modèle s'est appuyé)."""
    try:
        with open(etat.parametres.trace, "a", encoding="utf-8") as fichier:
            fichier.write(etat.masquer(json.dumps(entree, ensure_ascii=False)) + "\n")
    except OSError as erreur:
        journal.warning("Trace impossible : %s", erreur)


def _historique(messages: list[MessageHistorique]) -> list[dict[str, Any]]:
    """Derniers échanges, texte seul (pas les résultats d'outils), tronqués."""
    return [
        {"role": message.role, "content": message.contenu[:1500]}
        for message in messages[-6:]
        if message.contenu.strip()
    ]


class SelectionInvalide(ValueError):
    """Endpoints demandés inconnus ou indisponibles (→ HTTP 400)."""


def choisir_selection(etat: EtatServeur, outils: list[str] | None) -> list[str]:
    """Endpoints autorisés pour une question : ceux choisis par le journaliste, sinon la sélection par défaut."""
    if outils is None:
        return [nom for nom in SELECTION_DEFAUT if nom in etat.definitions]
    demandes = list(dict.fromkeys(nom.strip() for nom in outils if nom and nom.strip()))
    if not demandes:
        raise SelectionInvalide("Choisissez au moins un endpoint Hémicycle.")
    inconnus = [nom for nom in demandes if nom not in etat.definitions]
    if inconnus:
        raise SelectionInvalide(
            f"Endpoint(s) inconnu(s) ou indisponible(s) : {', '.join(inconnus)}. Voir GET /api/catalogue."
        )
    return demandes


def apercu_requete(nom: str, brut: Any, definitions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Requête REST équivalente à un appel d'endpoint, calculée AVANT l'appel (étape « hemicycle » du flux).

    Mêmes traductions que l'exécution (noms de paramètres corrigés, filtres des endpoints « jeu »,
    arguments par défaut) ; None si l'endpoint n'est pas autorisé ou si ses arguments sont invalides."""
    proprietes = next((set((d["function"].get("parameters") or {}).get("properties") or {})
                       for d in definitions if d["function"]["name"] == nom), None)
    if proprietes is None:
        return None
    try:
        arguments = json.loads(brut) if isinstance(brut, str) and brut.strip() else (brut or {})
        if not isinstance(arguments, dict):
            return None
        arguments = corriger_noms_parametres({c: v for c, v in arguments.items() if v is not None}, proprietes)
        aujourd_hui = datetime.now(FUSEAU).date()
        if nom == "derniers_scrutins":
            return requete_rest("interroger", arguments_derniers_scrutins(arguments))
        if nom == "agenda_seances":
            return requete_rest("interroger", arguments_agenda(arguments, aujourd_hui)[0])
        if nom in SPECS_JEUX:
            return requete_rest("interroger", appel_interroger(SPECS_JEUX[nom], arguments, aujourd_hui)[0])
        return requete_rest(nom, {**ARGUMENTS_PAR_DEFAUT.get(nom, {}), **arguments})
    except (ValueError, TypeError, AttributeError, KeyError):  # ErreurArguments* sont des ValueError
        return None


def ligne_appel(resultat: ResultatOutil, depuis_cache: bool, lance_par: str, etape: int | None) -> dict[str, Any]:
    """Entrée de `outils_utilises` : l'endpoint, ses arguments et l'appel Hémicycle réellement envoyé."""
    requete = resultat.requete_hemicycle
    return {
        "outil": resultat.outil,
        "titre": PAR_NOM[resultat.outil].titre if resultat.outil in PAR_NOM else resultat.outil,
        "arguments": resultat.arguments,
        "statut": "erreur" if resultat.erreur else ("cache" if depuis_cache else "ok"),
        "message": resultat.contenu[:300] if resultat.erreur else None,
        "credits": resultat.credits_factures or 0,
        "nb_sources": len(resultat.sources),
        "duree_s": resultat.duree_s,
        "requete": requete_rest(requete["outil"], requete["arguments"]) if requete else None,
        "lance_par": lance_par,
        "etape": etape,
    }


# Étapes envoyées par POST /chat/flux (code → message) ; « hemicycle » reçoit le titre de l'endpoint.
MESSAGES_ETAPES = {
    "rapport": "Lecture du rapport…",
    "analyse": "Analyse de la question…",
    "hemicycle": "Recherche dans Hémicycle : {titre}…",
    "rapport_section": "Recherche dans le rapport…",
    "recherche_auto": "Recherche automatique dans Hémicycle…",
    "redaction": "Rédaction de la réponse…",
    "verification": "Vérification des sources…",
}
Signaler = Callable[[dict[str, Any]], Awaitable[None]]


async def repondre(etat: EtatServeur, question: str, historique: list[MessageHistorique],
                   reflexion: bool | None = None, mois: str | None = None, outils: list[str] | None = None,
                   budget: int | None = None, max_appels: int | None = None,
                   signaler: Signaler | None = None) -> dict[str, Any]:
    """Répond à une question. Avec `mois` : chatbot du rapport (rapport + outils de sections + Hémicycle).
    Sans `mois` : outil de rédaction des journalistes (Hémicycle seulement), avec les endpoints
    choisis (`outils`), un budget de crédits (`budget`) et un nombre d'appels (`max_appels`).

    `signaler` (POST /chat/flux) : fonction asynchrone appelée avec chaque événement de progression,
    ``{"type": "etape", "code", "message", "t", …}`` ou ``{"type": "appel", "appel", "indice"}``.
    Sans effet sur la réponse renvoyée."""
    debut = time.perf_counter()

    async def signaler_etape(code: str, **extra: Any) -> None:
        if signaler is not None:
            titre = extra.pop("titre", "")
            await signaler({"type": "etape", "code": code, "message": MESSAGES_ETAPES[code].format(titre=titre),
                            "t": round(time.perf_counter() - debut, 1), **extra})
    reflexion = etat.parametres.reflexion if reflexion is None else reflexion
    # Lève NumeroInvalide / RapportIntrouvable (convertis en 400 / 404 par la route /chat).
    rapport = OutilsRapport(mois) if mois else None
    # Le chatbot du rapport garde la sélection par défaut ; lève SelectionInvalide (→ 400).
    selection = choisir_selection(etat, None if rapport else outils)
    budget = min(budget or etat.parametres.max_credits_question, etat.parametres.max_credits_plafond)
    if MOTIF_AIDE.match(question):
        return {
            "reponse": MESSAGE_AIDE, "lignes": [], "sources": [], "outils_utilises": [], "credits": 0,
            "avertissements": [], "actions": [],
            "meta": {"modele": etat.llm.modele, "duree_s": 0.0, "appels_llm": 0, "garde_fou": "aide"},
        }
    if rapport:
        await signaler_etape("rapport")

    aujourd_hui = datetime.now(FUSEAU).date()
    compteur = etat.hemicycle.nouveau_compteur()
    if max_appels and not rapport:
        compteur.max_appels = max(1, min(max_appels, etat.parametres.max_appels_plafond))
    systeme = (prompt_lecteur(rapport, aujourd_hui, compteur.max_appels) if rapport
               else prompt_systeme(aujourd_hui, compteur.max_appels, selection))
    definitions_requete = [etat.definitions[nom] for nom in selection]
    outils_rapport = rapport.outils_openai() if rapport else []
    schemas_requete = {
        d["function"]["name"]: set((d["function"].get("parameters") or {}).get("properties") or {})
        for d in definitions_requete + outils_rapport
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": systeme}, *_historique(historique), {"role": "user", "content": question},
    ]
    resultats: list[ResultatOutil] = []
    outils_utilises: list[dict[str, Any]] = []
    appels_reussis: list[tuple[int, ResultatOutil]] = []  # (indice dans outils_utilises, résultat)
    latences: list[float] = []
    tokens = {"entree": 0, "sortie": 0}
    taille_reflexion = 0
    recherche_auto = False
    appels_en_texte = 0
    reponse: ReponseChat | None = None

    etapes_llm: list[dict[str, Any]] = []

    async def executer_lot(appels: list[Any], etape: int) -> None:
        """Exécute des appels d'outils et ajoute les messages `role: tool` à la conversation."""
        dans_le_rapport = False  # une seule étape « rapport_section » pour des outils du rapport consécutifs
        for tool_call in appels:
            _, nom_outil, brut = lire_tool_call(tool_call)
            if rapport and rapport.gere(nom_outil):
                # Outils du rapport : locaux, gratuits, ils produisent des `actions` pour la page.
                if not dans_le_rapport:
                    await signaler_etape("rapport_section")
                    dans_le_rapport = True
                message_tool, _ = rapport.executer(tool_call)
                messages.append(message_tool)
                outils_utilises.append({**rapport.appels[-1], "lance_par": "modele", "etape": etape})
                continue
            dans_le_rapport = False
            await signaler_etape(
                "hemicycle", titre=PAR_NOM[nom_outil].titre if nom_outil in PAR_NOM else nom_outil,
                outil=nom_outil, requete=apercu_requete(nom_outil, brut, definitions_requete),
            )
            resultat, depuis_cache = await executer_appel(etat, tool_call, compteur, definitions_requete, budget)
            resultats.append(resultat)
            messages.append(resultat.message_openai())
            lance_par = "serveur" if str(tool_call.id).startswith("recherche_auto_") else "modele"
            ligne = ligne_appel(resultat, depuis_cache, lance_par, etape)
            outils_utilises.append(ligne)
            if not resultat.erreur:
                appels_reussis.append((len(outils_utilises) - 1, resultat))
            if signaler is not None:
                await signaler({"type": "appel", "appel": ligne, "indice": len(outils_utilises) - 1})
        if compteur.limite_atteinte:
            messages[-1]["content"] += NOTE_LIMITE

    for tour in range(compteur.max_appels + 2):
        avec_outils = not compteur.limite_atteinte
        reflexion_tour = reflexion or (tour == 0 and avec_outils and etat.parametres.reflexion_premier_tour)
        # Premier appel : analyse de la question ; ensuite, le modèle repart de résultats d'outils.
        await signaler_etape("analyse" if tour == 0 else "redaction")
        reponse = await _appeler_llm(etat, messages, (definitions_requete + outils_rapport) if avec_outils else None,
                                     reflexion_tour, schemas_requete)
        appels_en_texte += getattr(reponse, "appels_en_texte", 0)
        etapes_llm.append({
            "etape": tour + 1,
            "duree_s": round(reponse.duree_s, 1),
            "reflexion": reflexion_tour,
            "outils_demandes": [appel.function.name for appel in (reponse.appels_outils or [])],
            "appels_en_texte": getattr(reponse, "appels_en_texte", 0),
        })
        latences.append(round(reponse.duree_s, 1))
        if reponse.usage:
            tokens["entree"] += getattr(reponse.usage, "prompt_tokens", 0) or 0
            tokens["sortie"] += getattr(reponse.usage, "completion_tokens", 0) or 0
        taille_reflexion += len(reponse.reflexion or "")
        if (not reponse.appels_outils and not resultats and not (rapport and rapport.appels)
                and avec_outils and not recherche_auto and not hors_perimetre(reponse.texte)):
            # Le modèle a répondu sans chercher : sa réponse ne peut pas venir d'Hémicycle.
            # Le serveur lance lui-même la recherche avec les mots-clés de la question,
            # puis redonne la main au modèle avec les résultats.
            recherche_auto = True
            appels = appels_recherche_automatique(question, selection)
            if appels:
                journal.info("Aucun outil appelé par le modèle : recherche automatique %s",
                             [(a.function.name, a.function.arguments) for a in appels])
                await signaler_etape("recherche_auto")
                messages.append({
                    "role": "assistant", "content": None,
                    "tool_calls": [
                        {"id": a.id, "type": "function",
                         "function": {"name": a.function.name, "arguments": a.function.arguments}}
                        for a in appels
                    ],
                })
                await executer_lot(appels, tour + 1)
                continue
        if not reponse.appels_outils or not avec_outils:
            break
        messages.append(reponse.message_assistant())
        await executer_lot(reponse.appels_outils, tour + 1)

    await signaler_etape("verification")
    texte = nettoyer_reponse(reponse.texte if reponse else "")
    # Outil de rédaction : réponses en MAX_PUCES puces au plus. Chatbot du rapport (démo) : pas de limite.
    texte, puces_coupees = (texte, False) if rapport else limiter_puces(texte)
    if reponse is not None and reponse.raison_fin == "length" and texte:
        texte += " […]"
    consultees = [source for resultat in resultats if not resultat.erreur for source in resultat.sources]
    avertissements: list[str] = []
    garde_fou = None

    sources_rapport = rapport.sources() if rapport else []

    if not consultees and not sources_rapport and hors_perimetre(texte):
        # Refus demandé par le prompt lecteur : réponse fixe, sans source ni recherche.
        texte, sources, garde_fou = MESSAGE_HORS_PERIMETRE, [], "hors_perimetre"
    # Garde-fou : aucune source (ni Hémicycle, ni section du rapport) → aucun contenu factuel du modèle.
    elif not consultees and not sources_rapport:
        garde_fou = "aucune_source"
        if texte and texte != MESSAGE_INTROUVABLE:
            journal.info("Réponse du modèle écartée (aucune source) : %d caractères.", len(texte))
        cherches = [
            f"{appel['outil']} « {appel['arguments'].get('recherche') or appel['arguments'].get('q')} »"
            for appel in outils_utilises
            if appel["statut"] != "erreur" and (appel["arguments"].get("recherche") or appel["arguments"].get("q"))
        ]
        texte = MESSAGE_INTROUVABLE + (f" Recherches effectuées : {', '.join(cherches)}." if cherches else "")
        sources: list[dict[str, Any]] = []
    else:
        if not texte or sortie_de_moderation(texte):
            texte = "Le modèle n'a pas rédigé de réponse exploitable. Réessayez ou reformulez la question."
            garde_fou = "reponse_vide"
        sources = sources_rapport + (choisir_sources(consultees, texte) if consultees else [])
        # Contexte autorisé : la question, les dates du jour, les résultats d'outils et le rapport
        # (pas le prompt et ses exemples).
        lundi, dimanche = semaine_en_cours(aujourd_hui)
        dates = " ".join(f"{_date_fr(jour)} {jour.isoformat()}" for jour in (aujourd_hui, lundi, dimanche))
        texte_rapport = rapport.rapport.texte_brut() if rapport else ""
        corpus = "\n".join([dates, question, texte_rapport, *(resultat.contenu for resultat in resultats)])
        non_retrouves = elements_non_retrouves(texte, corpus)
        if non_retrouves:
            avertissements.append(
                "À vérifier : absent des données consultées → " + ", ".join(non_retrouves)
            )
    if puces_coupees and not garde_fou:
        avertissements.append(f"Réponse raccourcie aux {MAX_PUCES} premières puces.")
    if compteur.acces_refuse:
        avertissements.append(f"Hémicycle a refusé l'accès (HTTP {compteur.acces_refuse}) : prévenir l'équipe technique.")
    if compteur.limite_atteinte and any(appel["statut"] == "erreur" for appel in outils_utilises):
        avertissements.append("Limite d'appels ou de crédits atteinte : la réponse peut être incomplète.")

    credits = sum(appel["credits"] for appel in outils_utilises)
    duree = round(time.perf_counter() - debut, 1)
    # Chaque ligne de la réponse, avec les appels Hémicycle dont elle reprend une donnée (affichés à droite).
    lignes = [] if garde_fou else attribuer_lignes(
        texte, [(indice, r.contenu, r.sources) for indice, r in appels_reussis]
    )
    if etat.parametres.trace:
        _tracer(etat, {
            "date": datetime.now(FUSEAU).isoformat(timespec="seconds"), "question": question,
            "reflexion": reflexion, "reponse_modele": reponse.texte if reponse else None, "reponse": texte,
            "outils": [{"outil": r.outil, "arguments": r.arguments, "contenu": r.contenu} for r in resultats],
        })
    journal.info(
        "Question traitée en %.1f s : %d appel(s) LLM, outils %s, %d crédit(s), garde-fou %s",
        duree, len(latences), [(a["outil"], a["arguments"], a["statut"]) for a in outils_utilises], credits, garde_fou,
    )
    return {
        "reponse": texte,
        "lignes": lignes,
        "sources": sources,
        "outils_utilises": outils_utilises,
        "credits": credits,
        "avertissements": avertissements,
        # Actions pour la page du rapport (ex. surligner une section) : voir docs/ARCHITECTURE.md.
        "actions": rapport.actions if rapport else [],
        "meta": {
            "mode": "lecteur" if rapport else "redaction",
            "mois": mois,
            "modele": etat.llm.modele,
            "reflexion": reflexion,
            "reflexion_premier_tour": etat.parametres.reflexion_premier_tour,
            "duree_s": duree,
            "appels_llm": len(latences),
            "etapes_llm": etapes_llm,
            "latences_llm_s": latences,
            "tokens": tokens,
            "taille_reflexion": taille_reflexion,
            "garde_fou": garde_fou,
            "recherche_automatique": recherche_auto,
            "appels_outils_en_texte": appels_en_texte,
            "credits_serveur": etat.credits_serveur,
            "outils_choisis": selection,
            "budget_credits": budget,
            "max_appels": compteur.max_appels,
            "solde_hemicycle": etat.solde,
        },
    }


# --------------------------------------------------------------------------
# Application FastAPI
# --------------------------------------------------------------------------


class MessageHistorique(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    contenu: str = Field(default="", max_length=4000, validation_alias=AliasChoices("contenu", "content"))


class RequeteChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = Field(min_length=1, max_length=1000)
    historique: list[MessageHistorique] = Field(default_factory=list, max_length=20)
    # Numéro du rapport (AAAA-MM ou « demo ») : active le chatbot du rapport (mode lecteur).
    # Absent : outil de rédaction des journalistes.
    mois: str | None = None
    # Option de test : forcer la réflexion de Qwen 3 pour cette question (défaut : CHATBOT_REFLEXION).
    reflexion: bool | None = None
    # Outil de rédaction : endpoints que le modèle peut appeler (noms de GET /api/catalogue ;
    # défaut : sélection « Essentiel »), budget de crédits et nombre d'appels pour la question
    # (plafonnés par CHATBOT_MAX_CREDITS_QUESTION_PLAFOND et CHATBOT_MAX_TOOL_CALLS_PLAFOND).
    outils: list[str] | None = Field(default=None, max_length=40)
    budget_credits: int | None = Field(default=None, ge=1, le=200)
    max_appels: int | None = Field(default=None, ge=1, le=20)


class RequeteAppel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    outil: str = Field(min_length=1, max_length=60)
    arguments: dict[str, Any] = Field(default_factory=dict)


def construire_catalogue(hemicycle: OutilsHemicycle) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Définitions OpenAI de chaque endpoint disponible, et raison de chaque endpoint indisponible."""
    schemas_mcp = {d["function"]["name"]: d["function"] for d in hemicycle.outils_openai()}
    definitions: dict[str, dict[str, Any]] = {}
    indisponibles: dict[str, str] = {}
    for endpoint in ENDPOINTS:
        if endpoint.type == "mcp" and endpoint.nom not in hemicycle.config.liste_blanche:
            indisponibles[endpoint.nom] = "désactivé par CHATBOT_MCP_OUTILS"
            continue
        if endpoint.type in ("jeu", "local") and "interroger" not in hemicycle.noms_autorises:
            indisponibles[endpoint.nom] = "outil MCP « interroger » absent du serveur"
            continue
        definition = definition_endpoint(endpoint, OUTILS_LOCAUX, schemas_mcp)
        if definition is None:
            indisponibles[endpoint.nom] = "absent du serveur MCP d'Hémicycle"
        else:
            definitions[endpoint.nom] = definition
    return definitions, indisponibles


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    parametres = charger_parametres()
    config_llm = charger_config()  # FEATHERLESS_MODEL (variable d'environnement ou .env)
    config_mcp = charger_config_mcp()
    # Liste blanche : les outils MCP du catalogue (veille.py), restreints par CHATBOT_MCP_OUTILS s'il est
    # renseigné. `interroger` sert aux endpoints « jeu » et « local » : il n'est jamais exposé au modèle.
    restriction = {nom.strip() for nom in os.environ.get("CHATBOT_MCP_OUTILS", "").split(",") if nom.strip()}
    noms_mcp = [e.nom for e in ENDPOINTS if e.type == "mcp" and (not restriction or e.nom in restriction)]
    config_mcp = replace(config_mcp, liste_blanche=tuple(dict.fromkeys((*noms_mcp, "interroger"))))
    async with ClientFeatherlessAsync(config_llm) as llm, OutilsHemicycle(config_mcp) as hemicycle:
        # Les instructions du serveur MCP (« appelez guide », « interroger »…) ne sont pas transmises au modèle.
        definitions, indisponibles = construire_catalogue(hemicycle)
        etat = EtatServeur(
            parametres=parametres,
            llm=llm,
            hemicycle=hemicycle,
            outils=[definitions[nom] for nom in SELECTION_DEFAUT if nom in definitions],
            verrou_llm=asyncio.Semaphore(parametres.concurrence_llm),
            definitions=definitions,
            indisponibles=indisponibles,
        )
        try:
            etat.solde = await hemicycle.solde_credits()  # gratuit
        except Exception as erreur:  # le solde est un confort d'affichage : on démarre quand même
            journal.warning("Solde Hémicycle illisible au démarrage : %s", type(erreur).__name__)
        if indisponibles:
            journal.warning("Endpoints indisponibles : %s", indisponibles)
        app.state.etat = etat
        journal.info(
            "Prêt : modèle %s, réflexion %s, outils %s, plafonds %d crédits/question et %d depuis le démarrage",
            llm.modele, "activée" if parametres.reflexion else "désactivée", ", ".join(etat.noms_outils),
            parametres.max_credits_question, parametres.max_credits_serveur,
        )
        yield
        journal.info("Arrêt : %d crédit(s) Hémicycle consommé(s), %d requête(s) Featherless.",
                     etat.credits_serveur, llm.nb_requetes)


app = FastAPI(title="Outil de rédaction Hémicycle", lifespan=cycle_de_vie, docs_url=None, redoc_url=None)
app.include_router(routeur_rapport)  # GET /api/rapport/{mois}, GET /api/rapports
# CORS ouvert à toutes les origines (démo) : le site peut être servi ailleurs que par ce serveur.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# Le site du rapport (frontend/) servi tel quel sous /site/ : même origine que /chat, URL relatives possibles.
app.mount("/site", StaticFiles(directory=RACINE / "frontend", html=True, check_dir=False), name="site")


@app.get("/", include_in_schema=False)
async def page() -> FileResponse:
    if not FICHIER_PAGE.is_file():
        raise HTTPException(404, f"Page introuvable : {FICHIER_PAGE}")
    return FileResponse(FICHIER_PAGE, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/etat")
async def lire_etat(request: Request) -> dict[str, Any]:
    etat: EtatServeur = request.app.state.etat
    return {
        "modele": etat.llm.modele,
        "reflexion": etat.parametres.reflexion,
        "outils": etat.noms_outils,
        "max_appels_question": etat.hemicycle.config.max_appels_par_question,
        "max_credits_question": etat.parametres.max_credits_question,
        "credits_serveur": etat.credits_serveur,
        "plafond_credits_serveur": etat.parametres.max_credits_serveur,
        "solde_hemicycle": etat.solde,
        "nb_endpoints": len(etat.definitions),
        "requetes_featherless": etat.llm.nb_requetes,
        "acces_hemicycle_refuse": etat.acces_refuse,
        "demarre_le": etat.demarre_le,
    }


def erreur_http(etat: EtatServeur, erreur: Exception) -> tuple[int, str] | None:
    """Exception levée par `repondre` → (statut HTTP, message pour l'utilisateur), journalisée au besoin.

    Partagé par POST /chat (HTTPException) et POST /chat/flux (événement « erreur »). None : exception
    inattendue (HTTP 500)."""
    if isinstance(erreur, (NumeroInvalide, SelectionInvalide)):
        return 400, str(erreur)
    if isinstance(erreur, RapportIntrouvable):
        return 404, str(erreur)
    if isinstance(erreur, ConcurrenceDepassee):
        return 503, "Le modèle est saturé (Featherless, HTTP 429). Réessayez dans une minute."
    if isinstance(erreur, (openai.AuthenticationError, openai.PermissionDeniedError)):
        journal.error("Featherless refuse l'accès : HTTP %s", erreur.status_code)
        return 502, f"Featherless refuse l'accès (HTTP {erreur.status_code}) : vérifier la clé."
    if isinstance(erreur, openai.APIStatusError):
        journal.error("Featherless : HTTP %s : %s", erreur.status_code, etat.masquer(str(erreur))[:300])
        return 502, f"Erreur du modèle (Featherless, HTTP {erreur.status_code}). Réessayez."
    if isinstance(erreur, (openai.APITimeoutError, openai.APIConnectionError)):
        journal.error("Featherless injoignable : %s", type(erreur).__name__)
        return 504, "Le modèle ne répond pas (Featherless injoignable ou trop lent). Réessayez."
    return None


def _arguments_repondre(requete: RequeteChat) -> dict[str, Any]:
    return {
        "question": requete.question.strip(), "historique": requete.historique, "reflexion": requete.reflexion,
        "mois": requete.mois, "outils": requete.outils, "budget": requete.budget_credits,
        "max_appels": requete.max_appels,
    }


@app.post("/chat")
async def chat(requete: RequeteChat, request: Request) -> JSONResponse:
    etat: EtatServeur = request.app.state.etat
    try:
        corps = await repondre(etat, **_arguments_repondre(requete))
    except Exception as erreur:
        statut = erreur_http(etat, erreur)
        if statut is None:
            raise
        raise HTTPException(*statut) from erreur
    return JSONResponse(corps)


ENTETES_FLUX = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def ligne_ndjson(evenement: dict[str, Any]) -> str:
    """Un événement du flux : un objet JSON sur une ligne (les retours à la ligne des textes sont échappés)."""
    return json.dumps(evenement, ensure_ascii=False, default=str) + "\n"


@app.post("/chat/flux")
async def chat_flux(requete: RequeteChat, request: Request) -> StreamingResponse:
    """Comme POST /chat, mais la progression arrive au fil de l'eau (NDJSON, un événement par ligne) :
    étapes (`etape`), appels Hémicycle terminés (`appel`), puis `reponse` (le JSON de /chat) ou `erreur`.
    Contrat détaillé dans docs/ARCHITECTURE.md. Si le client se déconnecte, la question est abandonnée
    (tâche annulée : plus d'appel au modèle ni à Hémicycle)."""
    etat: EtatServeur = request.app.state.etat
    arguments = _arguments_repondre(requete)
    file: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def produire() -> None:
        try:
            corps = await repondre(etat, **arguments, signaler=file.put)
            await file.put({"type": "reponse", "donnees": corps})
        except asyncio.CancelledError:
            raise
        except Exception as erreur:
            statut = erreur_http(etat, erreur)
            if statut is None:
                journal.error("Erreur inattendue (/chat/flux) :\n%s",
                              etat.masquer("".join(traceback.format_exception(erreur))))
                statut = (500, "Erreur interne du serveur.")
            await file.put({"type": "erreur", "statut": statut[0], "detail": statut[1]})
        finally:
            file.put_nowait(None)  # fin du flux

    async def flux():
        tache = asyncio.create_task(produire())
        try:
            while (evenement := await file.get()) is not None:
                yield ligne_ndjson(evenement)
        finally:
            # Client déconnecté (Starlette annule l'itération) : on annule aussi la question en cours,
            # pour ne pas continuer à consommer des crédits pour personne.
            if not tache.done():
                tache.cancel()
                journal.info("Client déconnecté pendant /chat/flux : question annulée.")

    return StreamingResponse(flux(), media_type="application/x-ndjson", headers=ENTETES_FLUX)


@app.get("/api/catalogue")
async def catalogue(request: Request) -> dict[str, Any]:
    """Les endpoints de la veille : ce que le journaliste peut activer, leur coût et l'appel Hémicycle."""
    etat: EtatServeur = request.app.state.etat
    aujourd_hui = datetime.now(FUSEAU).date()
    endpoints = []
    for e in ENDPOINTS:
        definition = etat.definitions.get(e.nom)
        exemple = remplacer_jours(e.exemple, aujourd_hui)
        if e.type == "mcp":
            requete = requete_rest(e.nom, exemple)
        elif e.type == "jeu":
            try:
                appel, _ = appel_interroger(SPECS_JEUX[e.nom], exemple, aujourd_hui)
            except ErreurArgumentsVeille:
                appel = {"jeu": e.jeu}
            requete = requete_rest("interroger", appel)
        else:
            requete = requete_rest("interroger", {"jeu": e.jeu})
        endpoints.append({
            "nom": e.nom,
            "titre": e.titre,
            "categorie": e.categorie,
            "type": e.type,
            "outil_mcp": e.outil_mcp,
            "jeu": e.jeu,
            "cout": e.cout,
            "description": (definition or {}).get("function", {}).get("description") or e.description or e.titre,
            "parametres": (definition or {}).get("function", {}).get("parameters") or {"type": "object", "properties": {}},
            "exemple": exemple,
            "requete_exemple": requete,
            "disponible": definition is not None,
            "raison": etat.indisponibles.get(e.nom),
            "par_defaut": e.nom in SELECTION_DEFAUT,
        })
    return {
        "categories": CATEGORIES,
        "endpoints": endpoints,
        "preselections": PRESELECTIONS,
        "non_proposes": NON_PROPOSES,
        "budget": {"defaut": etat.parametres.max_credits_question, "plafond": etat.parametres.max_credits_plafond},
        "appels": {"defaut": etat.hemicycle.config.max_appels_par_question, "plafond": etat.parametres.max_appels_plafond},
        "api": {"base": "https://api.hemicycle.ai", "version": "2026-10-01", "mcp": etat.hemicycle.config.url,
                "remarque": "Le serveur appelle Hémicycle par son serveur MCP ; la requête REST est l'équivalent "
                            "documenté (docs/API_HEMICYCLE.md)."},
    }


MAX_CARACTERES_BRUT = 300_000


@app.post("/api/appel")
async def appel_direct(requete: RequeteAppel, request: Request) -> JSONResponse:
    """Appel direct d'un endpoint par le journaliste, sans le modèle (mêmes plafonds de crédits)."""
    etat: EtatServeur = request.app.state.etat
    definition = etat.definitions.get(requete.outil)
    if definition is None:
        raise HTTPException(404, f"Endpoint inconnu ou indisponible : {requete.outil}. Voir GET /api/catalogue.")
    compteur = etat.hemicycle.nouveau_compteur()
    compteur.max_appels = 1
    tool_call = SimpleNamespace(
        id="direct", type="function",
        function=SimpleNamespace(name=requete.outil, arguments=json.dumps(requete.arguments, ensure_ascii=False)),
    )
    debut = time.perf_counter()
    resultat, depuis_cache = await executer_appel(etat, tool_call, compteur, [definition],
                                                  etat.parametres.max_credits_plafond)
    try:
        compact: Any = json.loads(resultat.contenu)
    except ValueError:
        compact = resultat.contenu
    brut: Any = None
    if not resultat.erreur and resultat.texte_brut:
        texte_brut = resultat.texte_brut[:MAX_CARACTERES_BRUT]
        try:
            brut = json.loads(texte_brut)
        except ValueError:
            brut = texte_brut
    appel = ligne_appel(resultat, depuis_cache, "journaliste", None)
    return JSONResponse({
        **appel,
        "resultat": compact,
        "brut": brut,
        "brut_tronque": len(resultat.texte_brut) > MAX_CARACTERES_BRUT,
        "taille_brute": resultat.taille_brute,
        "tronque": resultat.tronque,
        "sources": resultat.sources,
        "duree_totale_s": round(time.perf_counter() - debut, 2),
        "solde_hemicycle": etat.solde,
        "credits_serveur": etat.credits_serveur,
    })


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Outil de rédaction : serveur local (127.0.0.1).")
    analyseur.add_argument("--modele", help="modèle Featherless (défaut : FEATHERLESS_MODEL)")
    analyseur.add_argument("--port", type=int, help="port (défaut : CHATBOT_PORT, sinon 8000)")
    analyseur.add_argument("--reflexion", action="store_true", help="activer la réflexion de Qwen 3 (plus lent)")
    options = analyseur.parse_args()
    # Les options passent par l'environnement, que le lifespan relit (le .env ne les écrase pas).
    if options.modele:
        os.environ["FEATHERLESS_MODEL"] = options.modele
    if options.reflexion:
        os.environ["CHATBOT_REFLEXION"] = "1"
    if options.port:
        os.environ["CHATBOT_PORT"] = str(options.port)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    # Les URL de requêtes HTTP sortantes ne contiennent pas de clé, mais on évite le bruit.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=charger_parametres().port, log_level="info")


if __name__ == "__main__":
    main()
