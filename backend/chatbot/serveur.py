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
- ``POST /chat`` : ``{"question", "historique"}`` → ``{"reponse", "sources", "outils_utilises", "credits", …}`` ;
- ``GET /etat`` : modèle, outils exposés, crédits consommés depuis le démarrage.

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
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from featherless_client import (
    ClientFeatherlessAsync,
    ConcurrenceDepassee,
    ReponseChat,
    charger_config,
)
from hemicycle_tools import (
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

# Outils MCP exposés au modèle de l'outil de rédaction (intersection avec la liste blanche
# du .env). Exclus volontairement : `guide` (inutile ici, définition lourde), `lire_acteur`
# (exige un identifiant PA… qu'aucun outil exposé ne fournit), `interroger` (jamais exposé
# tel quel : 132 jeux, dont les prédictions Orcet à 50 crédits pièce).
OUTILS_MCP_REDACTION: tuple[str, ...] = (
    "rechercher",
    "lire_texte",
    "lire_scrutin",
    "positions_groupes",
    "resultat_scrutin",
    "lire_amendement",
)
# Descriptions plus directives que celles du serveur, pour orienter le modèle.
DESCRIPTIONS_SURCHARGEES = {
    "rechercher": (
        "Recherche plein texte dans les textes, dossiers législatifs et amendements de l'Assemblée "
        "nationale (ni scrutins, ni députés). Pour retrouver un texte par son sujet. 2 crédits."
    ),
    "lire_texte": (
        "Lit un texte (projet ou proposition de loi, rapport) et son dossier législatif, par son "
        "identifiant (ex. PRJLANR5L17B0123). 1 crédit."
    ),
}

# Seuls jeux que les outils locaux peuvent interroger (garde-fou contre Orcet et les jeux dérivés).
JEUX_AUTORISES = frozenset({"scrutins", "reunions"})
LEGISLATURE = 17
EDITEUR_AN = "Assemblée nationale"
LICENCE_AN = "Licence Ouverte (Etalab)"
URL_OPEN_DATA_AN = "https://data.assemblee-nationale.fr"

MESSAGE_INTROUVABLE = "Je n'ai pas trouvé cette information dans Hémicycle."
MESSAGE_AIDE = (
    "Posez une question sur l'activité de l'Assemblée nationale : derniers scrutins, ordre du jour "
    "des séances, état d'un texte, position des groupes sur un vote… Les réponses s'appuient "
    "uniquement sur les données d'Hémicycle consultées en direct (non vérifiées par la rédaction)."
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
assemblée nationale parlement parlementaire parlementaires député députés hémicycle
texte textes loi lois projet proposition données donnée beaucoup plein eu avoir y-a
vote votes voté votée votés voter
""".split())


def mots_cles(question: str) -> str:
    """Mots-clés d'une question pour la recherche automatique (au plus 6)."""
    mots = re.findall(r"[a-zà-ÿœæç0-9-]+", question.lower().replace("’", " ").replace("'", " "))
    utiles = [mot for mot in mots if len(mot) > 2 and mot not in MOTS_VIDES]
    return " ".join(dict.fromkeys(utiles))[:120] if utiles else ""


def appels_recherche_automatique(question: str) -> list[Any]:
    """Appels d'outils lancés par le serveur quand le modèle n'en a appelé aucun."""
    cles = mots_cles(question)
    if cles:
        specs = [("rechercher", {"q": cles, "limit": 5}), ("derniers_scrutins", {"recherche": cles, "limite": 5})]
    else:  # question générale d'actualité (« quoi de neuf ? »)
        specs = [("derniers_scrutins", {"limite": 8}), ("agenda_seances", {})]
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
    max_tokens: int  # sans réflexion (CHATBOT_MAX_TOKENS)
    temperature: float
    max_credits_question: int
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
        # La réflexion compte dans les tokens de sortie : prévoir large quand elle est active.
        max_tokens=_entier_env("CHATBOT_MAX_TOKENS", 900, 100),
        temperature=0.3,
        max_credits_question=_entier_env("CHATBOT_MAX_CREDITS_QUESTION", 10, 1),
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


def prompt_systeme(aujourd_hui: date, max_appels: int) -> str:
    lundi, dimanche = semaine_en_cours(aujourd_hui)
    return f"""Tu es l'assistant de veille parlementaire d'une rédaction. Des journalistes t'interrogent sur l'actualité de l'Assemblée nationale pour préparer un rapport mensuel.

Aujourd'hui : {_date_longue(aujourd_hui)}. Semaine en cours : du lundi {_date_fr(lundi)} au dimanche {_date_fr(dimanche)}.

Méthode, pour CHAQUE question :
1. Ta première action est TOUJOURS d'appeler un ou deux outils ({max_appels} appels au plus). Ne réponds jamais avant d'avoir appelé un outil.
   - Actualité, « cette semaine », derniers votes : derniers_scrutins (depuis = {lundi.isoformat()}) ; ordre du jour et textes en discussion : agenda_seances.
   - « Où en est le texte sur X ? » : derniers_scrutins avec recherche = mots-clés de X, SANS « depuis », et rechercher avec q = mots-clés de X (types "dossier,texte"). Donne d'abord l'étape la plus récente (date la plus proche d'aujourd'hui). lire_texte n'accepte qu'un identifiant de texte (PRJL…, PION…), jamais un dossier DLR….
   - Position des groupes sur des scrutins : positions_groupes (10 scrutins au plus par appel).
   - Les outils couvrent l'Assemblée nationale, pas le Sénat.
2. Puis réponds UNIQUEMENT avec ce que contiennent les résultats des outils. Tu ne sais rien du Parlement par toi-même : chaque fait (date, nom, chiffre, résultat, intitulé, étape) doit figurer dans un résultat d'outil de cette conversation. N'utilise jamais tes connaissances propres, même pour compléter, contextualiser ou corriger.
3. Si, après les appels d'outils, les résultats ne contiennent pas l'information demandée, réponds seulement : « {MESSAGE_INTROUVABLE} »

Identifiants : scrutin VTANR5L17V<numéro> (VTANR5L17V1234 = scrutin n° 1234) ; député PA<chiffres> ; texte PRJLANR5L17B<numéro> (projet de loi) ou PIONANR5L17B<numéro> (proposition de loi) ; dossier DLR5L17N<chiffres> ; amendement AMANR5L17….

Forme de la réponse :
- En français, très brève : 80 mots au total au maximum, en 5 puces au plus, sans titre, introduction ni conclusion. Ne garde que les faits les plus importants (votes sur l'ensemble d'un texte, textes inscrits en séance).
- Chaque puce tient en une ligne (20 mots au plus) : la date (JJ/MM/AAAA), le fait, puis sa source entre parenthèses, par exemple « (scrutin n° 1234) », « (texte n° 567) » ou « (ordre du jour du JJ/MM/AAAA) ».
- Chiffres et intitulés repris exactement des résultats d'outils. Ton neutre : ni opinion, ni qualificatif, ni pronostic.
- Pas de liens : les sources sont affichées à part."""


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


def url_scrutin(numero: Any, legislature: int = LEGISLATURE) -> str:
    """Page publique d'analyse du scrutin (format vérifié le 14/11/2026)."""
    return f"https://www.assemblee-nationale.fr/dyn/{legislature}/scrutins/{numero}"


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
    if texte and texte.group(0) + ".json" in url:
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


def est_citee(source: dict[str, Any], reponse: str) -> bool:
    if source.get("nature") == "agenda":
        return "ordre du jour" in reponse.lower()
    ref = source.get("ref")
    if ref and ref in reponse:
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


MAX_PUCES = 5
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
    return "\n".join(gardees).strip(), coupe


def nettoyer_reponse(texte: str) -> str:
    """Retire un éventuel appel d'outil écrit en texte brut et les balises résiduelles."""
    texte = re.sub(r"<tool_call>.*?(</tool_call>|$)", "", texte or "", flags=re.DOTALL)
    texte = texte.replace("<think>", "").replace("</think>", "")
    return texte.strip()


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
    outils: list[dict[str, Any]]  # définitions envoyées au modèle
    verrou_llm: asyncio.Semaphore
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


async def executer_appel(etat: EtatServeur, tool_call: Any, compteur: CompteurConversation) -> tuple[ResultatOutil, bool]:
    """Exécute un `tool_call` du modèle. Renvoie (résultat, servi depuis le cache ?)."""
    ident, nom, brut = lire_tool_call(tool_call)
    if nom not in etat.noms_outils:
        return _refus(nom, f"Erreur : l'outil « {nom} » n'est pas disponible. Outils : {', '.join(etat.noms_outils)}.",
                      compteur, ident), False
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
    arguments = corriger_noms_parametres(arguments, etat.schemas.get(nom, set()))

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
    cout = COUTS_CREDITS.get("interroger" if nom in OUTILS_LOCAUX else nom, COUT_INCONNU)
    deja = max(compteur.credits_estimes, compteur.credits_factures)
    if not compteur.limite_atteinte:
        if deja + cout > etat.parametres.max_credits_question:
            return _refus(nom, "Limite atteinte : budget de crédits de la question épuisé. N'appelle plus d'outil ; "
                          "réponds avec les résultats déjà obtenus.", compteur, ident, arguments), False
        if etat.credits_serveur + cout > etat.parametres.max_credits_serveur:
            return _refus(nom, "Limite atteinte : plafond de crédits du serveur épuisé. N'appelle plus d'outil ; "
                          "réponds avec les résultats déjà obtenus.", compteur, ident, arguments), False

    if nom in OUTILS_LOCAUX:
        resultat = await _executer_local(etat, nom, arguments, compteur, ident)
    else:
        resultat = await etat.hemicycle.appeler(nom, arguments, compteur, tool_call_id=ident)
        resultat.sources = [enrichir_source(source) for source in resultat.sources]
        resultat.arguments = resultat.arguments or arguments

    if resultat.credits_factures is not None:
        etat.credits_serveur += resultat.credits_factures
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
                       outils: list[dict[str, Any]] | None, reflexion: bool) -> ReponseChat:
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
        appels = appels_outils_en_texte(reponse.texte, etat.schemas)
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


async def repondre(etat: EtatServeur, question: str, historique: list[MessageHistorique],
                   reflexion: bool | None = None) -> dict[str, Any]:
    debut = time.perf_counter()
    reflexion = etat.parametres.reflexion if reflexion is None else reflexion
    if MOTIF_AIDE.match(question):
        return {
            "reponse": MESSAGE_AIDE, "sources": [], "outils_utilises": [], "credits": 0, "avertissements": [],
            "meta": {"modele": etat.llm.modele, "duree_s": 0.0, "appels_llm": 0, "garde_fou": "aide"},
        }

    aujourd_hui = datetime.now(FUSEAU).date()
    compteur = etat.hemicycle.nouveau_compteur()
    systeme = prompt_systeme(aujourd_hui, compteur.max_appels)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": systeme}, *_historique(historique), {"role": "user", "content": question},
    ]
    resultats: list[ResultatOutil] = []
    outils_utilises: list[dict[str, Any]] = []
    latences: list[float] = []
    tokens = {"entree": 0, "sortie": 0}
    taille_reflexion = 0
    recherche_auto = False
    appels_en_texte = 0
    reponse: ReponseChat | None = None

    async def executer_lot(appels: list[Any]) -> None:
        """Exécute des appels d'outils et ajoute les messages `role: tool` à la conversation."""
        for tool_call in appels:
            resultat, depuis_cache = await executer_appel(etat, tool_call, compteur)
            resultats.append(resultat)
            messages.append(resultat.message_openai())
            outils_utilises.append({
                "outil": resultat.outil,
                "arguments": resultat.arguments,
                "statut": "erreur" if resultat.erreur else ("cache" if depuis_cache else "ok"),
                "credits": resultat.credits_factures or 0,
                "nb_sources": len(resultat.sources),
                "duree_s": resultat.duree_s,
                "lance_par": "serveur" if str(tool_call.id).startswith("recherche_auto_") else "modele",
            })
        if compteur.limite_atteinte:
            messages[-1]["content"] += NOTE_LIMITE

    for _ in range(compteur.max_appels + 2):
        avec_outils = not compteur.limite_atteinte
        reponse = await _appeler_llm(etat, messages, etat.outils if avec_outils else None, reflexion)
        appels_en_texte += getattr(reponse, "appels_en_texte", 0)
        latences.append(round(reponse.duree_s, 1))
        if reponse.usage:
            tokens["entree"] += getattr(reponse.usage, "prompt_tokens", 0) or 0
            tokens["sortie"] += getattr(reponse.usage, "completion_tokens", 0) or 0
        taille_reflexion += len(reponse.reflexion or "")
        if not reponse.appels_outils and not resultats and avec_outils and not recherche_auto:
            # Le modèle a répondu sans chercher : sa réponse ne peut pas venir d'Hémicycle.
            # Le serveur lance lui-même la recherche avec les mots-clés de la question,
            # puis redonne la main au modèle avec les résultats.
            recherche_auto = True
            appels = appels_recherche_automatique(question)
            journal.info("Aucun outil appelé par le modèle : recherche automatique %s",
                         [(a.function.name, a.function.arguments) for a in appels])
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": a.id, "type": "function",
                     "function": {"name": a.function.name, "arguments": a.function.arguments}}
                    for a in appels
                ],
            })
            await executer_lot(appels)
            continue
        if not reponse.appels_outils or not avec_outils:
            break
        messages.append(reponse.message_assistant())
        await executer_lot(reponse.appels_outils)

    texte, puces_coupees = limiter_puces(nettoyer_reponse(reponse.texte if reponse else ""))
    if reponse is not None and reponse.raison_fin == "length" and texte:
        texte += " […]"
    consultees = [source for resultat in resultats if not resultat.erreur for source in resultat.sources]
    avertissements: list[str] = []
    garde_fou = None

    # Garde-fou : aucune source Hémicycle → aucun contenu factuel du modèle.
    if not consultees:
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
        sources = choisir_sources(consultees, texte)
        # Contexte autorisé : la question, les dates du jour et les résultats d'outils (pas le prompt et ses exemples).
        lundi, dimanche = semaine_en_cours(aujourd_hui)
        dates = " ".join(f"{_date_fr(jour)} {jour.isoformat()}" for jour in (aujourd_hui, lundi, dimanche))
        corpus = "\n".join([dates, question, *(resultat.contenu for resultat in resultats)])
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
        "sources": sources,
        "outils_utilises": outils_utilises,
        "credits": credits,
        "avertissements": avertissements,
        "meta": {
            "modele": etat.llm.modele,
            "reflexion": reflexion,
            "duree_s": duree,
            "appels_llm": len(latences),
            "latences_llm_s": latences,
            "tokens": tokens,
            "taille_reflexion": taille_reflexion,
            "garde_fou": garde_fou,
            "recherche_automatique": recherche_auto,
            "appels_outils_en_texte": appels_en_texte,
            "credits_serveur": etat.credits_serveur,
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
    mois: str | None = None  # prévu par le contrat de docs/ARCHITECTURE.md ; inutilisé ici
    # Option de test : forcer la réflexion de Qwen 3 pour cette question (défaut : CHATBOT_REFLEXION).
    reflexion: bool | None = None


def _definitions_outils(hemicycle: OutilsHemicycle, exposes_mcp: list[str]) -> list[dict[str, Any]]:
    definitions = [OUTIL_DERNIERS_SCRUTINS, OUTIL_AGENDA_SEANCES]
    for definition in hemicycle.outils_openai(noms=[n for n in exposes_mcp if n in hemicycle.noms_autorises]):
        nom = definition["function"]["name"]
        if nom in DESCRIPTIONS_SURCHARGEES:
            definition["function"]["description"] = DESCRIPTIONS_SURCHARGEES[nom]
        definitions.append(definition)
    return definitions


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    parametres = charger_parametres()
    config_llm = charger_config()  # FEATHERLESS_MODEL (variable d'environnement ou .env)
    config_mcp = charger_config_mcp()
    exposes_mcp = [nom for nom in OUTILS_MCP_REDACTION if nom in config_mcp.liste_blanche]
    # `interroger` est ajouté pour les outils locaux uniquement : il n'est jamais exposé au modèle.
    config_mcp = replace(config_mcp, liste_blanche=tuple(dict.fromkeys((*exposes_mcp, "interroger"))))
    async with ClientFeatherlessAsync(config_llm) as llm, OutilsHemicycle(config_mcp) as hemicycle:
        # Les instructions du serveur MCP (« appelez guide », « interroger »…) ne sont pas transmises au modèle.
        etat = EtatServeur(
            parametres=parametres,
            llm=llm,
            hemicycle=hemicycle,
            outils=_definitions_outils(hemicycle, exposes_mcp),
            verrou_llm=asyncio.Semaphore(parametres.concurrence_llm),
        )
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
        "requetes_featherless": etat.llm.nb_requetes,
        "acces_hemicycle_refuse": etat.acces_refuse,
        "demarre_le": etat.demarre_le,
    }


@app.post("/chat")
async def chat(requete: RequeteChat, request: Request) -> JSONResponse:
    etat: EtatServeur = request.app.state.etat
    try:
        corps = await repondre(etat, requete.question.strip(), requete.historique, requete.reflexion)
    except ConcurrenceDepassee:
        raise HTTPException(503, "Le modèle est saturé (Featherless, HTTP 429). Réessayez dans une minute.")
    except (openai.AuthenticationError, openai.PermissionDeniedError) as erreur:
        journal.error("Featherless refuse l'accès : HTTP %s", erreur.status_code)
        raise HTTPException(502, f"Featherless refuse l'accès (HTTP {erreur.status_code}) : vérifier la clé.")
    except openai.APIStatusError as erreur:
        journal.error("Featherless : HTTP %s : %s", erreur.status_code, etat.masquer(str(erreur))[:300])
        raise HTTPException(502, f"Erreur du modèle (Featherless, HTTP {erreur.status_code}). Réessayez.")
    except (openai.APITimeoutError, openai.APIConnectionError) as erreur:
        journal.error("Featherless injoignable : %s", type(erreur).__name__)
        raise HTTPException(504, "Le modèle ne répond pas (Featherless injoignable ou trop lent). Réessayez.")
    return JSONResponse(corps)


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
