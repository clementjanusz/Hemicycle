"""Couche « outils » du chatbot : le pont entre le serveur MCP d'Hémicycle et le modèle.

Featherless (API compatible OpenAI) ne sait pas se connecter seul à un serveur MCP.
Ce module fait le pont :

1. connexion au MCP Hémicycle avec le SDK MCP officiel (paquet ``mcp`` ≥ 2.3,
   transport *streamable HTTP*, en-tête ``Authorization: Bearer <clé>``) ;
2. liste des outils, filtrée par une **liste blanche** configurable ;
3. conversion au format ``tools`` d'OpenAI ;
4. exécution des ``tool_calls`` demandés par le modèle, avec un résultat toujours
   exploitable (message d'erreur clair plutôt qu'une exception) et **tronqué** au besoin
   pour tenir dans le contexte de 32K tokens de Qwen3-32B ;
5. extraction des sources (éditeur, URL, licence) pour le champ ``sources`` de ``POST /chat`` ;
6. compteur d'appels et de crédits par conversation (limite ``CHATBOT_MAX_TOOL_CALLS``).

Le SDK MCP est asynchrone : tout s'utilise dans une boucle ``asyncio``. Ouvrir et fermer
la connexion dans la même tâche (par exemple dans le *lifespan* de FastAPI).

Exemple ::

    async with OutilsHemicycle(charger_config_mcp()) as hemicycle:
        outils = hemicycle.outils_openai()            # → paramètre tools= de Featherless
        compteur = hemicycle.nouveau_compteur()        # un compteur par question (/chat)
        for tool_call in message.tool_calls:          # réponse du modèle
            resultat = await hemicycle.executer(tool_call, compteur)
            messages.append(resultat.message_openai())  # message role: tool
            sources.extend(resultat.sources)            # champ sources de /chat

La clé n'est jamais affichée ni journalisée.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import mcp.types as types_mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

journal = logging.getLogger("hemicycle_mcp")

FICHIER_ENV = Path(__file__).resolve().parents[2] / ".env"
URL_PAR_DEFAUT = "https://api.hemicycle.ai/mcp"

# Liste blanche par défaut : les outils marqués ✅ dans docs/API_HEMICYCLE.md.
# Surchargeable par la variable CHATBOT_MCP_OUTILS (noms séparés par des virgules).
LISTE_BLANCHE_PAR_DEFAUT: tuple[str, ...] = (
    "rechercher",
    "lire_texte",
    "lire_amendement",
    "lire_scrutin",
    "resultat_scrutin",
    "lire_acteur",
    "positions_groupes",
    "guide",
)

# Barème en crédits (fiche guide « credits-et-limites », tarif 2026-11-08).
# Sert à estimer le coût AVANT l'appel ; le coût réel est lu ensuite dans
# `_meta.credits_cost` de la réponse du serveur.
COUTS_CREDITS: dict[str, int] = {
    "guide": 0,
    "lister_jeux": 0,
    "solde_credits": 0,
    "lire_texte": 1,
    "lire_amendement": 1,
    "lire_scrutin": 1,
    "resultat_scrutin": 1,
    "lire_acteur": 1,
    "positions_groupes": 1,
    "interroger": 1,  # 1 par page ; 5 sur un jeu dérivé ; 50 par prédiction Orcet renvoyée
    "rechercher": 2,
    "chercher_entreprise": 2,
    "chercher_donnees_publiques": 2,
    "lire_donnees_publiques": 2,
    "classement_auteurs": 5,
    "accord_groupes": 5,
    "loyaute_deputes": 5,
    "predire_vote": 50,  # 0 si aucune prédiction n'existe
}
# Par prudence, un outil absent du barème est compté comme un agrégat.
COUT_INCONNU = 5

# Outils dont le résultat est calculé par Hémicycle : sans objet `source` dans la
# réponse, on cite « Source : Hémicycle » (cf. docs/API_HEMICYCLE.md, « Sources et citation »).
OUTILS_CALCULES_PAR_HEMICYCLE = frozenset(
    {"positions_groupes", "accord_groupes", "loyaute_deputes", "classement_auteurs", "predire_vote"}
)

# Taille max d'un résultat renvoyé au modèle : ≈ 1 500 à 2 000 tokens.
MAX_CARACTERES_PAR_DEFAUT = 6000
# Exceptions par outil. resultat_scrutin : même compacté, un scrutin à 577 votants pèse
# ≈ 13 000 caractères ; le tronquer ferait perdre le vote de la plupart des députés.
MAX_CARACTERES_PAR_OUTIL: dict[str, int] = {"resultat_scrutin": 16000}
# Budget cumulé des résultats d'outils pour une question : ≈ 10K tokens sur les 32K du modèle
# (le reste va au prompt système, au rapport, aux définitions d'outils et à la réponse).
MAX_CARACTERES_PAR_QUESTION = 40000
# En dessous de ce budget restant, on n'appelle plus Hémicycle (inutile de payer pour rien).
MIN_CARACTERES_UTILES = 800
# Arguments ajoutés quand le modèle ne les précise pas (mesuré : ≈ 575 caractères par résultat
# de `rechercher`).
ARGUMENTS_PAR_DEFAUT: dict[str, dict[str, Any]] = {"rechercher": {"limit": 5}}
MAX_APPELS_PAR_DEFAUT = 5
DELAI_LECTURE_S = 60.0
MAX_SOURCES_PAR_APPEL = 10

# Statuts HTTP qui signifient « accès refusé » : inutile d'insister.
CODES_REFUS = {
    401: "clé absente, inconnue, expirée ou désactivée",
    402: "crédits insuffisants",
    403: "droits insuffisants pour cet outil",
}


class ErreurConfiguration(RuntimeError):
    """Variable manquante ou invalide dans le `.env`."""


class ErreurConnexionHemicycle(RuntimeError):
    """Connexion au serveur MCP impossible (réseau, serveur indisponible…)."""


class ErreurAccesHemicycle(ErreurConnexionHemicycle):
    """Accès refusé par Hémicycle : 401 (clé), 402 (crédits) ou 403 (droits)."""

    def __init__(self, statut: int, detail: str = "") -> None:
        self.statut = statut
        message = f"Accès refusé par Hémicycle (HTTP {statut} : {CODES_REFUS.get(statut, 'refus')})"
        super().__init__(f"{message}. {detail}".strip() if detail else message)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigHemicycleMCP:
    # repr=False : la clé n'apparaît pas si l'objet est affiché ou journalisé.
    cle_api: str = field(repr=False)
    url: str = URL_PAR_DEFAUT
    liste_blanche: tuple[str, ...] = LISTE_BLANCHE_PAR_DEFAUT
    max_caracteres_resultat: int = MAX_CARACTERES_PAR_DEFAUT
    max_caracteres_par_outil: Mapping[str, int] = field(default_factory=lambda: dict(MAX_CARACTERES_PAR_OUTIL))
    max_caracteres_question: int = MAX_CARACTERES_PAR_QUESTION
    max_appels_par_question: int = MAX_APPELS_PAR_DEFAUT
    delai_lecture_s: float = DELAI_LECTURE_S

    def limite_caracteres(self, outil: str) -> int:
        return self.max_caracteres_par_outil.get(outil, self.max_caracteres_resultat)


def _lire_entier(nom: str, defaut: int, minimum: int) -> int:
    brut = os.environ.get(nom, "").strip()
    if not brut:
        return defaut
    try:
        valeur = int(brut)
    except ValueError as erreur:
        raise ErreurConfiguration(f"{nom} doit être un entier (valeur actuelle : {brut!r})") from erreur
    if valeur < minimum:
        raise ErreurConfiguration(f"{nom} doit valoir au moins {minimum}")
    return valeur


def _lire_liste(brut: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(nom.strip() for nom in brut.split(",") if nom.strip()))


def charger_config_mcp(
    *, liste_blanche: Sequence[str] | None = None, charger_env: bool = True
) -> ConfigHemicycleMCP:
    """Lit la configuration dans le `.env` racine (les variables déjà définies priment).

    Variables : ``HEMICYCLE_MCP_KEY`` (obligatoire), ``HEMICYCLE_MCP_URL``,
    ``CHATBOT_MCP_OUTILS`` (liste blanche, noms séparés par des virgules),
    ``CHATBOT_MCP_MAX_CARACTERES`` (taille max d'un résultat d'outil),
    ``CHATBOT_MCP_MAX_CARACTERES_QUESTION`` (budget cumulé des résultats pour une question),
    ``CHATBOT_MAX_TOOL_CALLS`` (appels d'outils max par question).
    """
    if charger_env:
        from dotenv import load_dotenv

        load_dotenv(FICHIER_ENV, override=False)

    cle = os.environ.get("HEMICYCLE_MCP_KEY", "").strip()
    if not cle:
        raise ErreurConfiguration(f"HEMICYCLE_MCP_KEY manquante (attendue dans {FICHIER_ENV})")
    if not cle.startswith(("hmc_live_", "hmc_test_")):
        journal.warning("HEMICYCLE_MCP_KEY ne commence ni par hmc_live_ ni par hmc_test_")

    # Pas de barre oblique finale (cf. fiche guide « depannage »).
    url = (os.environ.get("HEMICYCLE_MCP_URL", "").strip() or URL_PAR_DEFAUT).rstrip("/")

    if liste_blanche is None:
        brut = os.environ.get("CHATBOT_MCP_OUTILS", "").strip()
        liste_blanche = _lire_liste(brut) if brut else LISTE_BLANCHE_PAR_DEFAUT

    return ConfigHemicycleMCP(
        cle_api=cle,
        url=url,
        liste_blanche=tuple(liste_blanche),
        max_caracteres_resultat=_lire_entier("CHATBOT_MCP_MAX_CARACTERES", MAX_CARACTERES_PAR_DEFAUT, 500),
        max_caracteres_question=_lire_entier(
            "CHATBOT_MCP_MAX_CARACTERES_QUESTION", MAX_CARACTERES_PAR_QUESTION, MIN_CARACTERES_UTILES
        ),
        max_appels_par_question=_lire_entier("CHATBOT_MAX_TOOL_CALLS", MAX_APPELS_PAR_DEFAUT, 0),
    )


# --------------------------------------------------------------------------
# Conversion MCP → OpenAI et estimation de taille
# --------------------------------------------------------------------------


def outil_vers_openai(outil: types_mcp.Tool) -> dict[str, Any]:
    """Convertit un outil MCP (nom, description, inputSchema) au format `tools` d'OpenAI."""
    schema = copy.deepcopy(outil.input_schema) if outil.input_schema else {}
    # Certains fournisseurs refusent la clé `$schema` ; elle n'apporte rien au modèle.
    schema.pop("$schema", None)
    schema.setdefault("type", "object")
    if schema.get("type") == "object":
        schema.setdefault("properties", {})
    description = (outil.description or outil.title or outil.name).strip()
    return {
        "type": "function",
        "function": {"name": outil.name, "description": description, "parameters": schema},
    }


def estimer_tokens(objet: Any) -> int:
    """Estimation grossière : ≈ 4 caractères par token.

    Les objets sont sérialisés comme le gabarit de chat de Qwen les rend (``tojson`` :
    séparateurs avec espace, accents conservés). Pour du français et du JSON, le compte
    réel est souvent 10 à 30 % plus élevé : garder de la marge.
    """
    texte = objet if isinstance(objet, str) else json.dumps(objet, ensure_ascii=False)
    return math.ceil(len(texte) / 4)


# --------------------------------------------------------------------------
# Troncature des résultats volumineux
# --------------------------------------------------------------------------


def _json_compact(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, separators=(",", ":"))


def _json_ou_none(texte: str) -> Any:
    texte = texte.strip()
    if not texte or texte[0] not in "{[":
        return None
    try:
        return json.loads(texte)
    except ValueError:
        return None


def _marqueur_omission(nb_omis: int, total: int) -> str:
    return f"… {nb_omis} élément(s) omis sur {total} (résultat tronqué)"


def _plus_gros_element(valeur: Any, longueurs: dict[int, int]) -> tuple[str, Any, Any, int] | None:
    """Trouve ce qui pèse le plus dans `valeur` : la plus grosse liste raccourcissable
    ou la plus longue chaîne. Renvoie (genre, conteneur, clé ou liste, taille)."""
    meilleur: tuple[str, Any, Any, int] | None = None

    def visiter(noeud: Any) -> None:
        nonlocal meilleur
        if isinstance(noeud, dict):
            for cle, enfant in noeud.items():
                if isinstance(enfant, str) and len(enfant) > 200:
                    if meilleur is None or len(enfant) > meilleur[3]:
                        meilleur = ("chaine", noeud, cle, len(enfant))
                else:
                    visiter(enfant)
        elif isinstance(noeud, list):
            reels = len(noeud) - (1 if id(noeud) in longueurs else 0)
            if reels >= 2:
                taille = len(_json_compact(noeud))
                if meilleur is None or taille > meilleur[3]:
                    meilleur = ("liste", noeud, None, taille)
            for indice, enfant in enumerate(noeud):
                if isinstance(enfant, str) and len(enfant) > 200:
                    if meilleur is None or len(enfant) > meilleur[3]:
                        meilleur = ("chaine", noeud, indice, len(enfant))
                else:
                    visiter(enfant)

    visiter(valeur)
    return meilleur


def _reduire_json(donnees: Any, budget: int) -> str | None:
    """Réduit un JSON en raccourcissant d'abord ce qui pèse le plus (la liste des votes
    de 577 députés, un exposé des motifs très long…), en gardant les petites listes
    (positions des groupes, décompte) intactes. Le résultat reste du JSON valide."""
    donnees = copy.deepcopy(donnees)
    longueurs: dict[int, int] = {}  # id(liste raccourcie) → longueur d'origine
    for _ in range(300):
        texte = _json_compact(donnees)
        if len(texte) <= budget:
            return texte
        cible = _plus_gros_element(donnees, longueurs)
        if cible is None:
            return None
        genre, conteneur, cle, taille = cible
        exces = len(texte) - budget
        if genre == "chaine":
            # On retire juste l'excédent (sans descendre sous 200 caractères).
            chaine = conteneur[cle]
            conteneur[cle] = chaine[: max(200, len(chaine) - exces - 10)] + " […]"
            continue
        liste = conteneur
        total = longueurs.get(id(liste), len(liste))
        reels = liste[:-1] if id(liste) in longueurs else liste[:]
        # Retire à peu près l'excédent, d'après la taille moyenne d'un élément (+1 pour le marqueur).
        moyenne = max(1.0, taille / len(reels))
        a_retirer = max(1, math.ceil(exces / moyenne) + 1)
        garde = reels[: max(1, len(reels) - a_retirer)]
        liste[:] = garde + [_marqueur_omission(total - len(garde), total)]
        longueurs[id(liste)] = total
    return None


def tronquer(texte: str, max_caracteres: int) -> tuple[str, bool]:
    """Ramène `texte` sous `max_caracteres` (note de troncature comprise).

    Renvoie ``(texte, tronqué ?)``. Un JSON est réduit intelligemment (il reste valide) ;
    sinon (Markdown, texte), coupe nette en fin de ligne.
    """
    taille = len(texte)
    if taille <= max_caracteres:
        return texte, False

    def note(gardes: int) -> str:
        return (
            f"\n[Résultat tronqué par le chatbot : {gardes} caractères gardés sur {taille}. "
            "Pour le détail, affiner la requête (identifiant précis, paramètre limite).]"
        )

    budget = max(0, max_caracteres - len(note(taille)))
    donnees = _json_ou_none(texte)
    if isinstance(donnees, (dict, list)):
        reduit = _reduire_json(donnees, budget)
        if reduit is not None:
            return reduit + note(len(reduit)), True

    coupe = texte[:budget]
    fin_de_ligne = coupe.rfind("\n")
    if fin_de_ligne > budget * 0.8:
        coupe = coupe[:fin_de_ligne]
    return coupe + note(len(coupe)), True


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def _source_contrat(outil: str, editeur: Any, url: Any, licence: Any) -> dict[str, Any]:
    """Une entrée du champ `sources` du contrat POST /chat (docs/ARCHITECTURE.md)."""
    return {
        "type": "hemicycle",
        "outil": outil,
        "editeur": editeur,
        "url": url,
        "licence": licence,
        "verifie_par_la_redaction": False,
    }


def extraire_sources(donnees: Any, outil: str, max_sources: int = MAX_SOURCES_PAR_APPEL) -> list[dict[str, Any]]:
    """Collecte les objets `source` (ou `sources`) d'une réponse, sans doublon d'URL.

    Format documenté par Hémicycle : ``{"editeur", "url", "licence"}``.
    """
    trouvees: list[dict[str, Any]] = []
    vues: set[tuple[str, str]] = set()

    def ajouter(source: Any) -> None:
        if isinstance(source, dict):
            editeur = source.get("editeur") or source.get("nom") or source.get("publisher")
            url = source.get("url") or source.get("lien")
            licence = source.get("licence") or source.get("license")
        elif isinstance(source, str):
            editeur, url, licence = source, None, None
        else:
            return
        cle = (str(url or ""), str(editeur or ""))
        if not any(cle) or cle in vues:
            return
        vues.add(cle)
        trouvees.append(_source_contrat(outil, editeur, url, licence))

    def visiter(noeud: Any) -> None:
        if isinstance(noeud, dict):
            for cle, enfant in noeud.items():
                if cle in ("source", "sources"):
                    for source in enfant if isinstance(enfant, list) else [enfant]:
                        ajouter(source)
                else:
                    visiter(enfant)
        elif isinstance(noeud, list):
            for enfant in noeud:
                visiter(enfant)

    visiter(donnees)
    if not trouvees and outil in OUTILS_CALCULES_PAR_HEMICYCLE:
        trouvees.append(_source_contrat(outil, "Hémicycle", "https://hemicycle.ai", None))
    return trouvees[:max_sources]


# --------------------------------------------------------------------------
# Compacteurs : réécriture sans perte utile des réponses connues pour être volumineuses
# --------------------------------------------------------------------------


def compacter_resultat_scrutin(donnees: Any) -> Any:
    """Regroupe les votes nominatifs par groupe puis par position, avec les noms seuls.

    Réponse brute mesurée : ≈ 86 caractères par député
    (``{"acteur": "PA1327", "nom": "…", "groupe": "PO845425", "position": "contre"}``).
    Format compact : ≈ 20 caractères par député, soit 4 fois moins.
    Perdus : les identifiants PA (acteur) et PO (groupe). Si le format change, la réponse
    est renvoyée telle quelle.
    """
    if not isinstance(donnees, dict) or not isinstance(donnees.get("votes"), list):
        return donnees
    groupes = [g for g in donnees.get("groupes") or [] if isinstance(g, dict)]
    sigles = {g.get("groupe"): g.get("sigle") or g.get("groupe") for g in groupes}
    votes_par_groupe: dict[str, dict[str, list[str]]] = {}
    for vote in donnees["votes"]:
        if not isinstance(vote, dict) or not vote.get("nom"):
            return donnees  # format inattendu : pas de compactage
        groupe = str(sigles.get(vote.get("groupe")) or vote.get("groupe") or "sans groupe")
        position = str(vote.get("position") or "inconnue")
        votes_par_groupe.setdefault(groupe, {}).setdefault(position, []).append(vote["nom"])

    compact = {cle: valeur for cle, valeur in donnees.items() if cle not in ("votes", "groupes")}
    if compact.get("objet") == compact.get("titre"):
        compact.pop("objet", None)  # doublon fréquent du titre
    compact["groupes"] = [{cle: valeur for cle, valeur in g.items() if cle != "groupe"} for g in groupes]
    compact["votes_par_groupe"] = votes_par_groupe
    return compact


# Types d'organes de l'open data de l'Assemblée (champ `nature` des mandats de `lire_acteur`).
# Libellés vérifiés le 14/11/2026 sur le jeu `organes` d'Hémicycle (colonne code_type) pour les
# codes observés ; un code absent de la table est laissé tel quel.
TYPES_ORGANES: dict[str, str] = {
    "ASSEMBLEE": "mandat de député",
    "GP": "groupe politique",
    "COMPER": "commission permanente",
    "CNPE": "commission d'enquête",
    "CNPS": "commission spéciale",
    "MISINFO": "mission d'information",
    "GE": "groupe d'études",
    "GA": "groupe d'amitié",
    "ORGEXTPARL": "organisme extraparlementaire",
    "PARPOL": "parti politique",
    "MINISTERE": "ministère",
}
# Mandats nombreux et peu informatifs : comptés, sauf fonction particulière (président…).
TYPES_COMPTES = {"GA": "groupes_amitie_en_cours", "GE": "groupes_etudes_en_cours"}
MAX_MANDATS_TERMINES = 6


def compacter_acteur(donnees: Any, aujourd_hui: str | None = None) -> Any:
    """Fiche `lire_acteur` : identité, mandats en cours, derniers mandats terminés.

    Réponse brute mesurée (PA794838, 14/11/2026) : 5 837 caractères, dont 6 060 pour 50 mandats
    (les 50 plus récents : le groupe politique et le mandat de député, plus anciens, n'y figuraient
    pas), aux trois quarts des groupes d'amitié et d'études. Format compact : ≈ 1 000 caractères.
    Chaque mandat garde l'identifiant de l'organe (PO…) : Hémicycle ne donne pas son nom ici.
    Si le format change, la réponse est renvoyée telle quelle.
    """
    if not isinstance(donnees, dict) or not isinstance(donnees.get("mandats"), list):
        return donnees
    mandats = donnees["mandats"]
    if not all(isinstance(m, dict) and m.get("nature") for m in mandats):
        return donnees
    jour = aujourd_hui or time.strftime("%Y-%m-%d")

    def resume(m: dict[str, Any]) -> dict[str, Any]:
        nature = str(m.get("nature"))
        sortie = {"type": TYPES_ORGANES.get(nature, nature), "organe": m.get("organe"), "qualite": m.get("qualite"),
                  "debut": m.get("debut")}
        if m.get("fin"):
            sortie["fin"] = m["fin"]
        # Champs inattendus (circonscription, lieu d'élection…) : gardés tels quels.
        sortie.update({c: v for c, v in m.items()
                       if c not in ("organe", "nature", "qualite", "debut", "fin", "legislature") and v not in (None, "")})
        return sortie

    en_cours, termines = [], []
    for m in mandats:
        (en_cours if not m.get("fin") or str(m["fin"]) >= jour else termines).append(m)
    compact = {cle: valeur for cle, valeur in donnees.items() if cle != "mandats"}
    comptes: dict[str, set[str]] = {}
    for m in en_cours:
        cle = TYPES_COMPTES.get(str(m["nature"]))
        if cle and str(m.get("qualite") or "").lower() == "membre":
            comptes.setdefault(cle, set()).add(str(m.get("organe")))
    compact["mandats_en_cours"] = [
        resume(m) for m in en_cours
        if not (m["nature"] in TYPES_COMPTES and str(m.get("qualite") or "").lower() == "membre")
    ]
    for cle in TYPES_COMPTES.values():
        if comptes.get(cle):
            compact[cle] = len(comptes[cle])
    compact["mandats_termines_recents"] = [
        resume(m) for m in termines if m["nature"] not in TYPES_COMPTES
    ][:MAX_MANDATS_TERMINES]
    natures = {str(m["nature"]) for m in en_cours}
    remarques = ["Organes désignés par leur identifiant (PO…) : Hémicycle ne donne pas leur nom dans cette fiche."]
    if "GP" not in natures:
        remarques.append(f"Groupe politique absent des {len(mandats)} mandats renvoyés (les plus récents) : "
                         "le groupe actuel est donné par chercher_depute.")
    compact["remarque"] = " ".join(remarques)
    return compact


COMPACTEURS = {"resultat_scrutin": compacter_resultat_scrutin, "lire_acteur": compacter_acteur}


# --------------------------------------------------------------------------
# Résultat d'un appel et compteur par conversation
# --------------------------------------------------------------------------


@dataclass
class ResultatOutil:
    """Résultat d'un appel d'outil, prêt à renvoyer au modèle."""

    outil: str
    contenu: str  # texte du message role: tool (éventuellement tronqué, ou message d'erreur)
    tool_call_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    erreur: bool = False
    fatal: bool = False  # accès refusé (401/402/403) : ne plus appeler Hémicycle
    statut_refus: int | None = None  # 401, 402 ou 403 quand `fatal`
    tronque: bool = False
    taille_brute: int = 0  # caractères avant troncature
    sources: list[dict[str, Any]] = field(default_factory=list)
    credits_factures: int | None = None  # lu dans _meta.credits_cost
    solde_restant: int | None = None  # lu dans _meta.credits_remaining
    duree_s: float = 0.0
    texte_brut: str = field(default="", repr=False)  # réponse complète, pour le débogage
    # Appel réellement envoyé au MCP : {"outil", "arguments"} (pour l'afficher au journaliste).
    requete_hemicycle: dict[str, Any] | None = None

    def message_openai(self) -> dict[str, Any]:
        """Message `role: tool` à ajouter à la conversation envoyée au modèle."""
        return {"role": "tool", "tool_call_id": self.tool_call_id or "", "content": self.contenu}


@dataclass
class CompteurConversation:
    """Compteur d'appels et de crédits d'une conversation (une question posée à /chat).

    Chaque `tool_call` demandé par le modèle compte, même refusé : cela borne la boucle.
    """

    max_appels: int = MAX_APPELS_PAR_DEFAUT
    nb_demandes: int = 0  # tool_calls demandés par le modèle (refusés compris)
    nb_appels_mcp: int = 0  # appels réellement envoyés à Hémicycle
    nb_erreurs: int = 0
    credits_estimes: int = 0  # d'après le barème COUTS_CREDITS, avant l'appel
    credits_factures: int = 0  # d'après _meta.credits_cost renvoyé par Hémicycle
    caracteres_renvoyes: int = 0  # taille cumulée des résultats renvoyés au modèle
    solde_restant: int | None = None
    acces_refuse: int | None = None  # statut HTTP (401/402/403) si Hémicycle a refusé l'accès
    journal: list[dict[str, Any]] = field(default_factory=list)

    @property
    def appels_restants(self) -> int:
        return max(0, self.max_appels - self.nb_demandes)

    @property
    def limite_atteinte(self) -> bool:
        """Vrai quand le modèle ne doit plus recevoir d'outils (ou `tool_choice="none"`)."""
        return self.nb_demandes >= self.max_appels or self.acces_refuse is not None

    def resume(self) -> dict[str, Any]:
        return {
            "nb_demandes": self.nb_demandes,
            "nb_appels_mcp": self.nb_appels_mcp,
            "nb_erreurs": self.nb_erreurs,
            "credits_estimes": self.credits_estimes,
            "credits_factures": self.credits_factures,
            "caracteres_renvoyes": self.caracteres_renvoyes,
            "solde_restant": self.solde_restant,
            "acces_refuse": self.acces_refuse,
        }


def lire_tool_call(tool_call: Any) -> tuple[str | None, str, Any]:
    """Extrait (id, nom, arguments) d'un `tool_call` OpenAI, objet du SDK ou dictionnaire."""
    if isinstance(tool_call, Mapping):
        fonction = tool_call.get("function") or {}
        return tool_call.get("id"), str(fonction.get("name") or ""), fonction.get("arguments")
    fonction = getattr(tool_call, "function", None)
    nom = str(getattr(fonction, "name", "") or "")
    return getattr(tool_call, "id", None), nom, getattr(fonction, "arguments", None)


def _texte_du_resultat(resultat: types_mcp.CallToolResult) -> str:
    """Concatène les blocs texte ; à défaut, sérialise le contenu structuré."""
    morceaux: list[str] = []
    for bloc in resultat.content:
        if isinstance(bloc, types_mcp.TextContent):
            morceaux.append(bloc.text)
        else:
            morceaux.append(f"[contenu de type {getattr(bloc, 'type', '?')} ignoré]")
    texte = "\n".join(morceaux).strip()
    if not texte and resultat.structured_content is not None:
        texte = _json_compact(resultat.structured_content)
    return texte


def traiter_resultat(
    outil: str, resultat: types_mcp.CallToolResult, max_caracteres: int = MAX_CARACTERES_PAR_DEFAUT
) -> ResultatOutil:
    """Transforme la réponse brute du MCP en `ResultatOutil` (fonction pure, testable hors ligne)."""
    texte = _texte_du_resultat(resultat)
    meta = resultat.meta or {}
    donnees = resultat.structured_content
    if not isinstance(donnees, (dict, list)):
        donnees = _json_ou_none(texte)

    sortie = ResultatOutil(
        outil=outil,
        contenu="",
        taille_brute=len(texte),
        credits_factures=meta.get("credits_cost") if isinstance(meta.get("credits_cost"), int) else None,
        solde_restant=meta.get("credits_remaining") if isinstance(meta.get("credits_remaining"), int) else None,
        texte_brut=texte,
    )

    if resultat.is_error:
        # Erreur métier renvoyée comme résultat (format problem+json possible : champ `status`).
        statut = donnees.get("status") if isinstance(donnees, dict) else None
        sortie.erreur = True
        if statut in CODES_REFUS:
            sortie.fatal, sortie.statut_refus = True, statut
        detail, _ = tronquer(texte or "erreur sans détail", 1500)
        sortie.contenu = f"Erreur renvoyée par Hémicycle pour « {outil} » : {detail}"
        return sortie

    # Sources extraites AVANT compactage et troncature, pour ne pas en perdre.
    sortie.sources = extraire_sources(donnees, outil)
    texte_modele = texte
    compacteur = COMPACTEURS.get(outil)
    if compacteur is not None and donnees is not None:
        compacte = compacteur(donnees)
        if compacte is not donnees:
            texte_modele = _json_compact(compacte)
    sortie.contenu, sortie.tronque = tronquer(texte_modele or "(résultat vide)", max_caracteres)
    return sortie


def _message_exception(erreur: BaseException) -> str:
    """Message lisible, y compris pour les ExceptionGroup imbriqués d'anyio."""
    if isinstance(erreur, BaseExceptionGroup):
        return " ; ".join(_message_exception(sous) for sous in erreur.exceptions)
    if isinstance(erreur, MCPError):
        return f"{erreur.message} (code {erreur.code})"
    return f"{type(erreur).__name__} : {erreur}" if str(erreur) else type(erreur).__name__


# --------------------------------------------------------------------------
# Client MCP
# --------------------------------------------------------------------------


class OutilsHemicycle:
    """Connexion au MCP Hémicycle + liste blanche + exécution des tool_calls."""

    def __init__(self, config: ConfigHemicycleMCP) -> None:
        self.config = config
        self._pile: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._outils: dict[str, types_mcp.Tool] = {}
        # Refus HTTP observés (401/402/403) : le SDK les transforme en erreur générique,
        # on les capte donc directement sur les réponses HTTP.
        self._nb_refus = 0
        self._dernier_refus: int | None = None
        self.info_serveur: types_mcp.Implementation | None = None
        self.instructions_serveur: str | None = None

    # --- connexion -------------------------------------------------------

    async def __aenter__(self) -> OutilsHemicycle:
        await self.connecter()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.fermer()

    async def _observer_reponse(self, reponse: httpx2.Response) -> None:
        if reponse.status_code in CODES_REFUS:
            self._nb_refus += 1
            self._dernier_refus = reponse.status_code

    def _masquer(self, texte: str) -> str:
        """Garde-fou : la clé ne doit jamais sortir de ce module."""
        return texte.replace(self.config.cle_api, "***") if self.config.cle_api else texte

    async def connecter(self) -> None:
        """Ouvre la session MCP et charge la liste des outils."""
        if self._session is not None:
            return
        pile = AsyncExitStack()
        try:
            http = await pile.enter_async_context(
                httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {self.config.cle_api}"},
                    timeout=httpx2.Timeout(30.0, read=self.config.delai_lecture_s),
                    event_hooks={"response": [self._observer_reponse]},
                )
            )
            lecture, ecriture = await pile.enter_async_context(
                streamable_http_client(self.config.url, http_client=http)
            )
            session = await pile.enter_async_context(
                ClientSession(
                    lecture,
                    ecriture,
                    read_timeout_seconds=self.config.delai_lecture_s,
                    client_info=types_mcp.Implementation(name="hemicycle-chatbot", version="0.1.0"),
                )
            )
            init = await session.initialize()
            self._session = session
            self.info_serveur = init.server_info
            self.instructions_serveur = init.instructions
            await self.rafraichir_outils()
        except Exception as erreur:
            self._session = None
            try:
                await pile.aclose()
            except Exception:  # la connexion est déjà en échec : on garde la première erreur
                pass
            detail = self._masquer(_message_exception(erreur))
            if self._dernier_refus is not None:
                raise ErreurAccesHemicycle(self._dernier_refus, detail) from erreur
            raise ErreurConnexionHemicycle(f"Connexion au MCP Hémicycle impossible : {detail}") from erreur
        self._pile = pile
        absents = self.outils_absents
        if absents:
            journal.warning("Outils de la liste blanche absents du serveur : %s", ", ".join(absents))

    async def fermer(self) -> None:
        pile, self._pile, self._session = self._pile, None, None
        if pile is not None:
            await pile.aclose()

    def _session_ouverte(self) -> ClientSession:
        if self._session is None:
            raise ErreurConnexionHemicycle("Session MCP non ouverte : utiliser `async with OutilsHemicycle(...)`")
        return self._session

    # --- outils ----------------------------------------------------------

    async def rafraichir_outils(self) -> list[types_mcp.Tool]:
        """Relit la liste des outils du serveur (avec pagination, au cas où)."""
        session = self._session_ouverte()
        outils: list[types_mcp.Tool] = []
        curseur: str | None = None
        for _ in range(20):
            params = types_mcp.PaginatedRequestParams(cursor=curseur) if curseur else None
            reponse = await session.list_tools(params=params)
            outils.extend(reponse.tools)
            curseur = reponse.next_cursor
            if not curseur:
                break
        self._outils = {outil.name: outil for outil in outils}
        return outils

    @property
    def outils_serveur(self) -> list[types_mcp.Tool]:
        """Tous les outils proposés par le serveur, liste blanche ou non."""
        return list(self._outils.values())

    @property
    def noms_autorises(self) -> list[str]:
        """Outils de la liste blanche réellement proposés par le serveur (ordre de la liste blanche)."""
        return [nom for nom in self.config.liste_blanche if nom in self._outils]

    @property
    def outils_absents(self) -> list[str]:
        return [nom for nom in self.config.liste_blanche if nom not in self._outils]

    def outils_openai(self, noms: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Définitions au format `tools` d'OpenAI, pour la liste blanche (ou un sous-ensemble)."""
        autorises = self.noms_autorises
        if noms is not None:
            demandes = list(noms)
            interdits = [nom for nom in demandes if nom not in autorises]
            if interdits:
                raise ValueError(f"Outils hors liste blanche ou absents du serveur : {', '.join(interdits)}")
            autorises = [nom for nom in autorises if nom in demandes]
        return [outil_vers_openai(self._outils[nom]) for nom in autorises]

    def nouveau_compteur(self) -> CompteurConversation:
        return CompteurConversation(max_appels=self.config.max_appels_par_question)

    # --- exécution -------------------------------------------------------

    async def executer(self, tool_call: Any, compteur: CompteurConversation) -> ResultatOutil:
        """Exécute un `tool_call` OpenAI (objet du SDK ou dict). Ne lève pas d'exception :
        en cas de problème, le résultat contient un message d'erreur destiné au modèle."""
        ident, nom, arguments = lire_tool_call(tool_call)
        return await self.appeler(nom, arguments, compteur, tool_call_id=ident)

    async def appeler(
        self,
        nom: str,
        arguments: Mapping[str, Any] | str | None = None,
        compteur: CompteurConversation | None = None,
        *,
        tool_call_id: str | None = None,
    ) -> ResultatOutil:
        """Appelle un outil de la liste blanche. `arguments` : dict ou chaîne JSON."""
        compteur = compteur if compteur is not None else self.nouveau_compteur()
        compteur.nb_demandes += 1

        def refus(contenu: str, *, statut_refus: int | None = None, statut: str = "refuse") -> ResultatOutil:
            compteur.nb_erreurs += 1
            compteur.caracteres_renvoyes += len(contenu)
            compteur.journal.append({"outil": nom, "statut": statut, "message": contenu[:300]})
            return ResultatOutil(
                outil=nom,
                contenu=contenu,
                tool_call_id=tool_call_id,
                erreur=True,
                fatal=statut_refus is not None,
                statut_refus=statut_refus,
            )

        # 1. Garde-fous locaux, sans appel réseau.
        if compteur.acces_refuse is not None:
            return refus(
                f"Erreur : l'accès à Hémicycle est refusé (HTTP {compteur.acces_refuse}). "
                "N'appelle plus d'outil ; réponds à partir du rapport, en le signalant.",
                statut_refus=compteur.acces_refuse,
            )
        if compteur.nb_demandes > compteur.max_appels:
            return refus(
                f"Limite atteinte : {compteur.max_appels} appels d'outils au plus par question. "
                "N'appelle plus d'outil ; réponds avec les informations déjà obtenues, ou dis que tu ne sais pas."
            )
        if nom not in self.noms_autorises:
            return refus(
                f"Erreur : l'outil « {nom} » n'est pas disponible. "
                f"Outils autorisés : {', '.join(self.noms_autorises)}."
            )

        # 2. Arguments : chaîne JSON (format OpenAI) ou dictionnaire.
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError as erreur:
                return refus(
                    f"Erreur : arguments illisibles pour « {nom} » (JSON invalide : {erreur}). "
                    "Renvoie un objet JSON conforme au schéma de l'outil."
                )
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            return refus(f"Erreur : les arguments de « {nom} » doivent être un objet JSON.")
        # Le modèle met parfois `null` sur les paramètres facultatifs : on les retire.
        arguments = {
            **ARGUMENTS_PAR_DEFAUT.get(nom, {}),
            **{cle: valeur for cle, valeur in arguments.items() if valeur is not None},
        }

        # 3. Budget de contexte : la taille du résultat s'adapte à ce qu'il reste pour la question.
        restant = self.config.max_caracteres_question - compteur.caracteres_renvoyes
        if restant < MIN_CARACTERES_UTILES:
            return refus(
                "Limite atteinte : les résultats d'outils de cette question remplissent déjà le contexte. "
                "N'appelle plus d'outil ; réponds avec les informations déjà obtenues."
            )
        limite = min(self.config.limite_caracteres(nom), restant)

        # 4. Appel au MCP.
        compteur.nb_appels_mcp += 1
        compteur.credits_estimes += COUTS_CREDITS.get(nom, COUT_INCONNU)
        refus_avant = self._nb_refus
        debut = time.monotonic()
        try:
            brut = await self._session_ouverte().call_tool(
                nom, arguments, read_timeout_seconds=self.config.delai_lecture_s
            )
            resultat = traiter_resultat(nom, brut, limite)
        except MCPError as erreur:
            message = self._masquer(erreur.message)
            if self._nb_refus > refus_avant and self._dernier_refus is not None:
                statut_http = self._dernier_refus
                compteur.acces_refuse = statut_http
                return refus(
                    f"Erreur : l'accès à Hémicycle est refusé (HTTP {statut_http} : {CODES_REFUS[statut_http]}). "
                    "N'appelle plus d'outil ; réponds à partir du rapport, en le signalant.",
                    statut_refus=statut_http,
                    statut="acces_refuse",
                )
            detail, _ = tronquer(message, 1500)
            return refus(
                f"Erreur renvoyée par Hémicycle pour « {nom} » (code {erreur.code}) : {detail} "
                "Corrige les arguments ou utilise un autre outil.",
                statut="erreur",
            )
        except Exception as erreur:  # réseau, délai dépassé, réponse illisible…
            journal.warning("Appel %s en échec : %s", nom, self._masquer(_message_exception(erreur)))
            return refus(
                f"Erreur : Hémicycle n'a pas répondu correctement pour « {nom} » "
                f"({type(erreur).__name__}). Réessaie au plus une fois, sinon réponds sans cette donnée.",
                statut="erreur",
            )

        # 5. Bilan.
        resultat.tool_call_id = tool_call_id
        resultat.requete_hemicycle = {"outil": nom, "arguments": dict(arguments)}
        resultat.arguments = dict(arguments)
        resultat.duree_s = round(time.monotonic() - debut, 2)
        resultat.contenu = self._masquer(resultat.contenu)
        if resultat.fatal:
            compteur.acces_refuse = resultat.statut_refus
        if resultat.erreur:
            compteur.nb_erreurs += 1
        if resultat.credits_factures is not None:
            compteur.credits_factures += resultat.credits_factures
        if resultat.solde_restant is not None:
            compteur.solde_restant = resultat.solde_restant
        compteur.caracteres_renvoyes += len(resultat.contenu)
        compteur.journal.append(
            {
                "outil": nom,
                "arguments": resultat.arguments,
                "statut": "erreur" if resultat.erreur else "ok",
                "credits": resultat.credits_factures,
                "taille_brute": resultat.taille_brute,
                "taille_renvoyee": len(resultat.contenu),
                "tronque": resultat.tronque,
                "nb_sources": len(resultat.sources),
                "duree_s": resultat.duree_s,
            }
        )
        journal.info(
            "Outil %s : %s car. (%s), %s crédit(s), %.2f s",
            nom,
            resultat.taille_brute,
            "tronqué" if resultat.tronque else "complet",
            resultat.credits_factures,
            resultat.duree_s,
        )
        return resultat

    async def solde_credits(self) -> int | None:
        """Solde du compte (outil gratuit). Réservé à l'administration : jamais exposé au modèle."""
        refus_avant = self._nb_refus
        try:
            brut = await self._session_ouverte().call_tool(
                "solde_credits", {}, read_timeout_seconds=self.config.delai_lecture_s
            )
        except MCPError as erreur:
            if self._nb_refus > refus_avant and self._dernier_refus is not None:
                raise ErreurAccesHemicycle(self._dernier_refus, self._masquer(erreur.message)) from erreur
            journal.warning("solde_credits en échec : %s", self._masquer(erreur.message))
            return None
        donnees = brut.structured_content
        if not isinstance(donnees, dict):
            donnees = _json_ou_none(_texte_du_resultat(brut)) or {}
        solde = donnees.get("solde")
        return solde if isinstance(solde, int) else None
