"""Veille parlementaire : catalogue des endpoints Hémicycle proposés aux journalistes.

Chaque endpoint du catalogue est un outil que le modèle peut appeler, et que le journaliste
peut activer ou désactiver question par question (ou appeler lui-même, sans le modèle).
Trois familles :

- ``mcp``   : un outil du serveur MCP d'Hémicycle, appelé tel quel (``lire_scrutin``…) ;
- ``local`` : un outil écrit dans ``serveur.py`` (``derniers_scrutins``, ``agenda_seances``) ;
- ``jeu``   : un outil défini ici, qui lit UN jeu de données précis via l'outil MCP
  ``interroger`` avec des filtres fixés côté serveur (jamais un jeu au choix du modèle :
  certains coûtent 50 crédits par ligne).

Pour l'affichage, chaque appel est aussi traduit en requête REST équivalente
(``GET /v1/scrutins/{id}``…), d'après la table des endpoints de docs/API_HEMICYCLE.md.
Le serveur passe toujours par le MCP : la requête REST est montrée à titre de référence.
"""

from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

FUSEAU = ZoneInfo("Europe/Paris")
LEGISLATURE = 17
EDITEUR_AN = "Assemblée nationale"
LICENCE_AN = "Licence Ouverte (Etalab)"
URL_OPEN_DATA_AN = "https://data.assemblee-nationale.fr"


def url_scrutin(numero: Any, legislature: int = LEGISLATURE) -> str:
    """Page publique d'analyse d'un scrutin de l'Assemblée (format vérifié le 14/11/2026)."""
    return f"https://www.assemblee-nationale.fr/dyn/{legislature}/scrutins/{numero}"


# --------------------------------------------------------------------------
# Requête REST équivalente à un appel MCP
# --------------------------------------------------------------------------

# outil MCP → (méthode, chemin) ; « {id} » est remplacé par l'argument `id`.
ROUTES_REST: dict[str, tuple[str, str]] = {
    "rechercher": ("GET", "/v1/recherche"),
    "lire_texte": ("GET", "/v1/textes/{id}"),
    "lire_amendement": ("GET", "/v1/amendements/{id}"),
    "lire_scrutin": ("GET", "/v1/scrutins/{id}"),
    "resultat_scrutin": ("GET", "/v1/scrutins/{id}/resultat"),
    "lire_acteur": ("GET", "/v1/acteurs/{id}"),
    "positions_groupes": ("POST", "/v1/agregats/positions-groupes"),
    "accord_groupes": ("POST", "/v1/agregats/accord-groupes"),
    "loyaute_deputes": ("POST", "/v1/agregats/loyaute-deputes"),
    "classement_auteurs": ("POST", "/v1/agregats/classement-auteurs"),
    "lister_jeux": ("GET", "/v1/jeux"),
    "interroger": ("POST", "/v1/jeux/interroger"),
    "chercher_entreprise": ("GET", "/v1/entreprises"),
    "chercher_donnees_publiques": ("GET", "/v1/donnees-publiques"),
    "lire_donnees_publiques": ("POST", "/v1/donnees-publiques/lecture"),
    "predire_vote": ("POST", "/v1/orcet/predictions"),
    "solde_credits": ("GET", "/v1/credits"),
}


def requete_rest(outil_mcp: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Appel MCP → requête REST équivalente, pour l'affichage.

    Renvoie ``{"mcp", "arguments", "methode", "chemin", "corps", "texte", "court"}`` :
    ``texte`` est la requête complète (avec la query string), ``court`` un libellé compact
    pour une étiquette (``POST /v1/jeux/interroger · scrutins``)."""
    originaux = dict(arguments or {})
    arguments = dict(originaux)
    methode, chemin = ROUTES_REST.get(outil_mcp, ("MCP", f"/mcp · {outil_mcp}"))
    corps: dict[str, Any] | None = None
    if "{id}" in chemin:
        chemin = chemin.replace("{id}", str(arguments.pop("id", "") or "?"))
    if methode == "GET" and arguments:
        # Affichage lisible, non encodé. Noms de paramètres identiques au MCP (vérifié en REST le 14/11/2026,
        # docs/RAPPORT_API_HEMICYCLE.md § 12.1) ; sur un GET, un paramètre inconnu est ignoré mais facturé.
        chemin += "?" + "&".join(
            f"{cle}={','.join(map(str, v)) if isinstance(v, list) else v}" for cle, v in arguments.items()
        )
    elif methode == "POST":
        corps = arguments
    court = chemin.split("?", 1)[0]
    if outil_mcp == "interroger" and arguments.get("jeu"):
        court += f" · {arguments['jeu']}"
    return {
        "mcp": outil_mcp,
        "arguments": originaux,
        "methode": methode,
        "chemin": chemin,
        "corps": corps,
        "texte": f"{methode} {chemin}",
        "court": f"{methode} {court}",
    }


# --------------------------------------------------------------------------
# Endpoints « jeu » : un jeu de données précis, filtres fixés côté serveur
# --------------------------------------------------------------------------


class ErreurArgumentsVeille(ValueError):
    """Arguments invalides : le message est renvoyé au modèle (ou au journaliste)."""


@dataclass(frozen=True)
class VarianteJeu:
    """Autre jeu lu quand un paramètre booléen vaut true (ex. `deputes`, anciens députés compris).

    Toujours un jeu fixé ici (jamais au choix du modèle) ; `sans` : paramètres sans colonne
    correspondante dans ce jeu, refusés avec un message clair."""

    jeu: str
    colonnes: tuple[str, ...]
    sans: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParamJeu:
    """Un paramètre exposé au modèle, et sa traduction en filtre `interroger`."""

    nom: str
    schema: dict[str, Any]
    role: str = "filtre"  # filtre | recherche | depuis | jusqu_a | limite | booleen | variante
    colonne: str | None = None
    op: str = "eq"  # eq, like, in…
    # Pour role="booleen" : filtre ajouté quand la valeur est fausse (ou absente).
    filtre_si_faux: dict[str, Any] | None = None
    # Pour role="variante" : jeu lu à la place du jeu principal quand la valeur est true.
    variante: VarianteJeu | None = None
    transformer: Callable[[Any], Any] | None = None
    requis: bool = False


@dataclass(frozen=True)
class SpecJeu:
    jeu: str
    colonnes: tuple[str, ...]
    params: tuple[ParamJeu, ...]
    tri: str | None = None
    ordre: str = "desc"
    filtres_fixes: tuple[dict[str, Any], ...] = ()
    colonne_date: str | None = None  # colonne filtrée par depuis / jusqu_a
    # Horodatages UTC (Sénat) : la période est élargie d'un jour et filtrée en heure de Paris.
    date_horodatee: bool = False
    limite_defaut: int = 10
    limite_max: int = 20
    lignes_lues: int | None = None  # lignes lues quand le résultat est regroupé (sinon : limite)
    periode_defaut_semaine: bool = False
    tronquer: dict[str, int] = field(default_factory=dict)
    renommer: dict[str, str] = field(default_factory=dict)
    source_ligne: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    regrouper: Callable[[list[dict[str, Any]], int], tuple[list[dict[str, Any]], dict[str, Any]]] | None = None
    sources_regroupees: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None

    @property
    def jeux(self) -> tuple[str, ...]:
        """Tous les jeux que cet endpoint peut lire (le principal et ses variantes)."""
        return (self.jeu, *(p.variante.jeu for p in self.params if p.variante))


def _date(valeur: Any, nom: str) -> date | None:
    if valeur in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valeur).strip()[:10])
    except ValueError as erreur:
        raise ErreurArgumentsVeille(f"« {nom} » doit être une date AAAA-MM-JJ (reçu : {valeur!r}).") from erreur


def date_fr(valeur: Any) -> Any:
    """'2026-11-05T00:00:00.000+01:00' ou '2026-11-05' → '05/11/2026' (heure de Paris si horodaté)."""
    if not isinstance(valeur, str) or not re.match(r"^\d{4}-\d{2}-\d{2}", valeur):
        return valeur
    if "T" in valeur and len(valeur) > 10:
        try:
            moment = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
            if moment.tzinfo is not None:
                moment = moment.astimezone(FUSEAU)
            return moment.strftime("%d/%m/%Y")
        except ValueError:
            pass
    try:
        return date.fromisoformat(valeur[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return valeur


def _jour_paris(valeur: Any) -> date | None:
    texte = date_fr(valeur)
    try:
        return datetime.strptime(str(texte), "%d/%m/%Y").date()
    except ValueError:
        return None


def semaine(aujourd_hui: date) -> tuple[date, date]:
    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())
    return lundi, lundi + timedelta(days=6)


def appel_interroger(spec: SpecJeu, arguments: dict[str, Any], aujourd_hui: date) -> tuple[dict[str, Any], dict[str, Any]]:
    """Arguments du modèle → (appel `interroger`, contexte pour la compaction)."""
    connus = {p.nom for p in spec.params}
    inconnus = sorted(set(arguments) - connus)
    if inconnus:
        raise ErreurArgumentsVeille(
            f"Paramètre(s) inconnu(s) : {', '.join(inconnus)}. Paramètres possibles : {', '.join(sorted(connus))}."
        )
    filtres: list[dict[str, Any]] = [dict(f) for f in spec.filtres_fixes]
    appel: dict[str, Any] = {"jeu": spec.jeu, "colonnes": list(spec.colonnes)}
    # Variante (ex. anciens = true → jeu `deputes`) : un autre jeu, lui aussi fixé ici.
    variante = next((p for p in spec.params if p.role == "variante" and arguments.get(p.nom) is True), None)
    if variante is not None and variante.variante is not None:
        appel = {"jeu": variante.variante.jeu, "colonnes": list(variante.variante.colonnes)}
        en_trop = [nom for nom in variante.variante.sans if arguments.get(nom) not in (None, "", [])]
        if en_trop:
            raise ErreurArgumentsVeille(
                f"« {', '.join(en_trop)} » ne s'applique pas avec « {variante.nom} » = true : retire ce paramètre."
            )
    if spec.tri:
        appel["tri"], appel["ordre"] = spec.tri, spec.ordre
    limite = spec.limite_defaut
    depuis = jusqu_a = None
    for param in spec.params:
        valeur = arguments.get(param.nom)
        if param.requis and valeur in (None, ""):
            raise ErreurArgumentsVeille(f"« {param.nom} » est obligatoire.")
        if param.role == "variante":
            continue
        if param.role == "booleen":
            if valeur is not True and param.filtre_si_faux:
                filtres.append(dict(param.filtre_si_faux))
            continue
        if valeur in (None, "", []):
            continue
        if param.role == "limite":
            try:
                limite = min(spec.limite_max, max(1, int(valeur)))
            except (TypeError, ValueError) as erreur:
                raise ErreurArgumentsVeille(f"« {param.nom} » doit être un entier.") from erreur
        elif param.role == "depuis":
            depuis = _date(valeur, param.nom)
        elif param.role == "jusqu_a":
            jusqu_a = _date(valeur, param.nom)
        elif param.role == "recherche":
            texte = " ".join(str(valeur).split())
            if len(texte) < 2:
                raise ErreurArgumentsVeille(f"« {param.nom} » doit faire au moins 2 caractères.")
            appel["recherche"] = texte[:200]
        else:
            texte = param.transformer(valeur) if param.transformer else valeur
            if param.op == "like":
                texte = " ".join(str(texte).split())
                if len(texte) < 3:
                    raise ErreurArgumentsVeille(f"« {param.nom} » doit faire au moins 3 caractères.")
                texte = texte[:100]
            filtres.append({"colonne": param.colonne, "op": param.op, "valeur": texte})
    if spec.periode_defaut_semaine and depuis is None and jusqu_a is None:
        depuis, jusqu_a = semaine(aujourd_hui)
    if depuis and jusqu_a and jusqu_a < depuis:
        raise ErreurArgumentsVeille("« jusqu_a » doit être postérieure à « depuis ».")
    if spec.colonne_date:
        marge = timedelta(days=1 if spec.date_horodatee else 0)
        if depuis:
            filtres.append({"colonne": spec.colonne_date, "op": "gte", "valeur": (depuis - marge).isoformat()})
        if jusqu_a:
            filtres.append({"colonne": spec.colonne_date, "op": "lt",
                            "valeur": (jusqu_a + timedelta(days=1) + marge).isoformat()})
    if filtres:
        appel["filtres"] = filtres
    appel["limite"] = spec.lignes_lues or (limite + (10 if spec.date_horodatee else 0))
    return appel, {"limite": limite, "depuis": depuis, "jusqu_a": jusqu_a, "jeu": appel["jeu"]}


def _compacter_valeur(cle: str, valeur: Any, tronquer: dict[str, int]) -> Any:
    if isinstance(valeur, str):
        valeur = " ".join(valeur.split())
        if cle in tronquer and len(valeur) > tronquer[cle]:
            valeur = valeur[: tronquer[cle]].rstrip() + "…"
        return date_fr(valeur) if re.match(r"^\d{4}-\d{2}-\d{2}(T|$)", valeur) else valeur
    if isinstance(valeur, list):
        elements = [_compacter_valeur(cle, v, tronquer) for v in valeur[:6]]
        return elements + ([f"… (+{len(valeur) - 6})"] if len(valeur) > 6 else [])
    return valeur


def compacter_jeu(spec: SpecJeu, donnees: Any, contexte: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Réponse brute d'`interroger` → (contenu compact pour le modèle, sources)."""
    donnees = donnees if isinstance(donnees, dict) else {}
    lignes = [l for l in donnees.get("lignes") or [] if isinstance(l, dict)]
    if spec.date_horodatee and spec.colonne_date and (contexte.get("depuis") or contexte.get("jusqu_a")):
        depuis, jusqu_a = contexte.get("depuis"), contexte.get("jusqu_a")
        lignes = [
            l for l in lignes
            if (jour := _jour_paris(l.get(spec.colonne_date))) is None
            or ((not depuis or jour >= depuis) and (not jusqu_a or jour <= jusqu_a))
        ]
    source_jeu = donnees.get("source") if isinstance(donnees.get("source"), dict) else {}
    editeur = source_jeu.get("nom") or "Hémicycle"
    licence = source_jeu.get("licence")
    extra: dict[str, Any] = {}
    if spec.regrouper:
        elements, extra = spec.regrouper(lignes, contexte["limite"])
        sources = spec.sources_regroupees(elements) if spec.sources_regroupees else []
    else:
        lignes = lignes[: contexte["limite"]]
        elements, sources = [], []
        for ligne in lignes:
            element = {
                spec.renommer.get(cle, cle): _compacter_valeur(cle, valeur, spec.tronquer)
                for cle, valeur in ligne.items()
                if valeur not in (None, "", [], {})
            }
            elements.append(element)
            if spec.source_ligne:
                source = spec.source_ligne(ligne)
                if source:
                    sources.append({"type": "hemicycle", "editeur": editeur, "licence": licence,
                                    "verifie_par_la_redaction": False, **source})
    if not any(s.get("url") for s in sources) and elements:
        # Source générale du jeu (éditeur, URL et licence renvoyés par Hémicycle).
        sources.append({
            "type": "hemicycle", "editeur": editeur, "url": source_jeu.get("url"), "licence": licence,
            "libelle": f"{editeur} — jeu « {contexte.get('jeu') or spec.jeu} » (via Hémicycle)", "nature": "jeu",
            "verifie_par_la_redaction": False,
        })
    contenu: dict[str, Any] = {
        "source": f"{editeur}" + (f" ({licence})" if licence else "") + ", via Hémicycle",
        "nombre": len(elements),
        **extra,
        "resultats": elements,
    }
    if not elements:
        contenu["message"] = "Aucun résultat pour ces critères."
    elif not spec.regrouper and len(elements) >= contexte["limite"]:
        contenu["remarque"] = f"Les {contexte['limite']} premiers résultats seulement ; d'autres correspondent peut-être."
    return contenu, sources


# --- sources par ligne -----------------------------------------------------


def _entier(valeur: Any) -> int | None:
    correspondance = re.match(r"\s*(\d+)", str(valeur or ""))
    return int(correspondance.group(1)) if correspondance else None


def _source_amendement_an(l: dict[str, Any]) -> dict[str, Any] | None:
    numero = _entier(l.get("numero_long"))
    return {
        "url": URL_OPEN_DATA_AN, "ref": l.get("uid"), "numero": numero, "nature": "amendement",
        "libelle": f"Amendement n° {l.get('numero_long')}" + (f" (texte {l['ref_texte_legislatif']})" if l.get("ref_texte_legislatif") else ""),
        "titre": (l.get("article_designation_courte") or None),
    }


def _source_document_an(l: dict[str, Any]) -> dict[str, Any] | None:
    uid = l.get("uid")
    if not uid:
        return None
    # Même forme que l'URL renvoyée par les outils MCP : serveur.enrichir_source en fait un lien lisible.
    return {"url": f"https://www.assemblee-nationale.fr/dyn/opendata/{uid}.json", "titre": (l.get("titre_principal") or "")[:160] or None}


def source_depute(uid: str, civilite: Any = None, prenom: Any = None, nom: Any = None,
                  groupe: Any = None) -> dict[str, Any]:
    """Source « fiche d'un député » (page publique de l'Assemblée).

    `prenom` et `nom` servent à reconnaître la source dans la réponse (`_cite`, `serveur.est_citee`) :
    une réponse sur un député cite son nom, rarement son identifiant PA…"""
    complet = " ".join(str(v).strip() for v in (civilite, prenom, nom) if v).strip()
    return {
        "url": f"https://www.assemblee-nationale.fr/dyn/deputes/{uid}", "ref": uid, "nature": "depute",
        "libelle": (complet or uid) + (f" ({groupe})" if groupe else ""),
        "prenom": str(prenom).strip() if prenom else None, "nom": str(nom).strip() if nom else None,
    }


def _source_depute(l: dict[str, Any]) -> dict[str, Any] | None:
    if not l.get("uid"):
        return None
    return source_depute(l["uid"], l.get("civ"), l.get("prenom"), l.get("nom"), l.get("groupe_sigle"))


PARTICULES = frozenset({"de", "du", "des", "d", "le", "la", "van", "von", "di", "da", "del", "della", "dos"})
MOTIF_CIVILITE = re.compile(r"^(m\.?|mme\.?|mlle\.?|monsieur|madame|mademoiselle|député|députée)\s+", re.IGNORECASE)


def nom_de_famille(valeur: Any) -> str:
    """« Didier Lemaire » → « Lemaire » ; « Marine Le Pen » → « Pen » ; « Mme de Courson » → « Courson ».

    Le jeu des députés sépare prénom et nom : un filtre « like » sur le nom complet ne trouve rien.
    On garde le dernier mot (3 lettres au moins), qui figure dans le nom de famille, particules comprises."""
    texte = MOTIF_CIVILITE.sub("", " ".join(str(valeur or "").replace("’", "'").split()))
    mots = [m for m in re.split(r"[\s']+", texte) if m]
    if len(mots) <= 1:
        return texte
    utiles = [m for m in mots if m.lower() not in PARTICULES]
    dernier = utiles[-1] if utiles else mots[-1]
    return dernier if len(dernier) >= 3 else texte


def _source_url_ligne(libelle: Callable[[dict[str, Any]], str], nature: str, ref: str = "id") -> Callable:
    def source(l: dict[str, Any]) -> dict[str, Any] | None:
        if not l.get("url"):
            return None
        numero = _entier(l.get("numero_complet") or l.get("numero")) if nature != "dossier" else None
        return {"url": l["url"], "ref": l.get(ref), "numero": numero, "nature": nature, "libelle": libelle(l)}
    return source


# --- fil des événements : regroupement --------------------------------------

PRIORITE_EVENEMENT = {"scrutin_solennel": 0, "etape": 1, "amendements": 2, "scrutin": 3}


def regrouper_evenements(lignes: list[dict[str, Any]], limite: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Le flux brut répète chaque acte et chaque scrutin d'amendement : on regroupe par jour."""
    elements: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()
    totaux: Counter = Counter()
    for l in lignes:
        jour = date_fr(l.get("event_date"))
        genre = l.get("event_type")
        payload = l.get("payload") if isinstance(l.get("payload"), dict) else {}
        if genre == "scrutin":
            solennel = "solennel" in str(l.get("sous_titre") or "")
            totaux[(jour, "scrutins")] += 1
            cle = ("scrutin", payload.get("uid") or l.get("item_key") or l.get("titre"))
            elements.setdefault(cle, {
                "date": jour, "type": "scrutin_solennel" if solennel else "scrutin",
                "objet": " ".join(str(l.get("titre") or "").split())[:220], "resultat": l.get("statut"),
                "numero": payload.get("numero"), "id": payload.get("uid"),
                "pour": payload.get("nb_pour"), "contre": payload.get("nb_contre"),
                "abstentions": payload.get("nb_abstentions"),
            })
        elif genre == "amendements":
            totaux[(jour, "amendements")] += int(l.get("nb") or 0)
            cle = ("amendements", jour, l.get("texte_uid"))
            element = elements.setdefault(cle, {"date": jour, "type": "amendements", "texte": l.get("texte_uid"),
                                                "nombre": 0, "par_auteur": {}})
            element["nombre"] += int(l.get("nb") or 0)
            auteur = str(l.get("sous_titre") or "?")
            element["par_auteur"][auteur] = element["par_auteur"].get(auteur, 0) + int(l.get("nb") or 0)
        else:
            totaux[(jour, "etapes")] += 1
            cle = ("etape", jour, l.get("titre"), l.get("sous_titre"))
            element = elements.setdefault(cle, {"date": jour, "type": "etape", "texte": l.get("titre"),
                                                "etape": l.get("sous_titre"), "id_texte": l.get("texte_uid"), "fois": 0})
            element["fois"] += 1
    tries = sorted(
        elements.values(),
        key=lambda e: (-(_jour_paris_fr(e["date"]) or date.min).toordinal(), PRIORITE_EVENEMENT.get(e["type"], 9)),
    )
    retenus = tries[:limite]
    par_jour: dict[str, dict[str, int]] = {}
    for (jour, genre), nombre in totaux.items():
        par_jour.setdefault(jour, {})[genre] = nombre
    extra = {"totaux_par_jour": par_jour}
    if len(tries) > limite:
        extra["remarque"] = f"{len(tries)} événements regroupés ; les {limite} plus récents ou importants sont listés."
    return retenus, extra


def _jour_paris_fr(texte: Any) -> date | None:
    try:
        return datetime.strptime(str(texte), "%d/%m/%Y").date()
    except ValueError:
        return None


def sources_evenements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources = []
    for e in elements:
        if e["type"] in ("scrutin", "scrutin_solennel") and e.get("numero"):
            sources.append({
                "type": "hemicycle", "editeur": EDITEUR_AN, "licence": LICENCE_AN, "nature": "scrutin",
                "url": url_scrutin(e["numero"]), "ref": e.get("id"), "numero": _entier(e["numero"]),
                "libelle": f"Scrutin n° {e['numero']} du {e['date']}", "titre": e.get("objet"),
                "verifie_par_la_redaction": False,
            })
    sources.append({
        "type": "hemicycle", "editeur": "Hémicycle", "url": "https://hemicycle.ai",
        "licence": "Mention « Source : Hémicycle »", "nature": "jeu",
        "libelle": "Hémicycle — flux des événements parlementaires (30 derniers jours)",
        "verifie_par_la_redaction": False,
    })
    return sources


# --- paramètres réutilisés ------------------------------------------------------


def _p_depuis(description: str = "Date de début incluse, AAAA-MM-JJ.") -> ParamJeu:
    return ParamJeu("depuis", {"type": "string", "description": description}, role="depuis")


def _p_jusqu_a(description: str = "Date de fin incluse, AAAA-MM-JJ.") -> ParamJeu:
    return ParamJeu("jusqu_a", {"type": "string", "description": description}, role="jusqu_a")


def _p_limite(defaut: int, maximum: int, quoi: str = "résultats") -> ParamJeu:
    return ParamJeu("limite", {"type": "integer", "minimum": 1, "maximum": maximum,
                               "description": f"Nombre de {quoi} ({defaut} par défaut, {maximum} au plus)."}, role="limite")


def _p_recherche(description: str, requis: bool = False) -> ParamJeu:
    return ParamJeu("recherche", {"type": "string", "description": description}, role="recherche", requis=requis)


def _p_contient(nom: str, colonne: str, description: str, requis: bool = False) -> ParamJeu:
    return ParamJeu(nom, {"type": "string", "description": description}, colonne=colonne, op="like", requis=requis)


NATURES_DOCUMENTS = {
    "projet de loi": "Projet de loi",
    "proposition de loi": "Proposition de loi",
    "proposition de résolution": "Proposition de résolution",
    "rapport": "Rapport",
    "avis": "Avis",
}


SPECS_JEUX: dict[str, SpecJeu] = {
    "amendements_deposes": SpecJeu(
        jeu="amendements",
        colonnes=("uid", "ref_texte_legislatif", "numero_long", "date_depot", "etat", "sort_en_seance",
                  "signataires_affichable", "article_designation_courte", "expose_sommaire"),
        params=(
            _p_recherche("Mots-clés cherchés dans le dispositif et l'exposé des amendements (ex. « feux de forêt »)."),
            ParamJeu("texte", {"type": "string", "description": "Identifiant du texte amendé (PRJLANR5L17B…, PIONANR5L17B…)."},
                     colonne="ref_texte_legislatif"),
            _p_depuis("Date de dépôt minimale, AAAA-MM-JJ."), _p_jusqu_a("Date de dépôt maximale, AAAA-MM-JJ."),
            _p_limite(8, 20, "amendements"),
        ),
        tri="date_depot", filtres_fixes=({"colonne": "legislature", "op": "eq", "valeur": LEGISLATURE},),
        colonne_date="date_depot", limite_defaut=8,
        tronquer={"signataires_affichable": 160, "expose_sommaire": 280},
        renommer={"uid": "id", "ref_texte_legislatif": "texte", "numero_long": "numero", "signataires_affichable": "signataires",
                  "article_designation_courte": "article", "expose_sommaire": "expose", "sort_en_seance": "sort"},
        source_ligne=_source_amendement_an,
    ),
    "textes_deposes": SpecJeu(
        jeu="documents",
        colonnes=("uid", "dossier_ref", "titre_principal", "date_depot", "type_libelle"),
        params=(
            _p_recherche("Mots-clés cherchés dans le titre (ex. « logement »)."),
            ParamJeu("nature", {"type": "string", "enum": list(NATURES_DOCUMENTS),
                                "description": "Nature du document."},
                     colonne="type_libelle", op="like", transformer=lambda v: NATURES_DOCUMENTS.get(str(v).lower(), v)),
            _p_depuis("Date de dépôt minimale, AAAA-MM-JJ."), _p_jusqu_a("Date de dépôt maximale, AAAA-MM-JJ."),
            _p_limite(10, 20, "documents"),
        ),
        tri="date_depot", filtres_fixes=({"colonne": "legislature", "op": "eq", "valeur": LEGISLATURE},),
        colonne_date="date_depot",
        renommer={"uid": "id", "dossier_ref": "dossier", "titre_principal": "titre", "type_libelle": "nature"},
        source_ligne=_source_document_an,
    ),
    "chercher_depute": SpecJeu(
        jeu="deputes_en_exercice",
        colonnes=("uid", "civ", "prenom", "nom", "groupe_politique", "groupe_sigle", "profession"),
        params=(
            ParamJeu("nom", {"type": "string",
                             "description": "Nom de famille du député (3 lettres au moins), sans le prénom : "
                                            "« Lemaire », « Le Pen »."},
                     colonne="nom", op="like", transformer=nom_de_famille, requis=True),
            _p_contient("prenom", "prenom", "Prénom, pour départager des homonymes (facultatif)."),
            ParamJeu("groupe", {"type": "string", "description": "Sigle du groupe (RN, EPR, LFI-NFP, SOC, DR…)."},
                     colonne="groupe_sigle"),
            ParamJeu("anciens", {"type": "boolean",
                                 "description": "true : cherche aussi parmi les anciens députés (sans leur groupe)."},
                     role="variante",
                     variante=VarianteJeu("deputes", ("uid", "civ", "prenom", "nom", "profession", "date_deces"),
                                          sans=("groupe",))),
            _p_limite(5, 10, "députés"),
        ),
        tri="nom", ordre="asc", limite_defaut=5,
        renommer={"uid": "id"},
        source_ligne=_source_depute,
    ),
    "fil_evenements": SpecJeu(
        jeu="evenements_parlementaires",
        colonnes=("event_type", "event_date", "titre", "sous_titre", "statut", "texte_uid", "nb", "payload", "item_key"),
        params=(
            _p_depuis(), _p_jusqu_a(),
            ParamJeu("type", {"type": "string", "enum": ["scrutin", "acte", "amendements"],
                              "description": "scrutin (votes), acte (étapes de procédure) ou amendements (dépôts)."},
                     colonne="event_type"),
            _p_contient("recherche", "titre", "Mot contenu dans l'intitulé (3 lettres au moins)."),
            _p_limite(15, 30, "événements regroupés"),
        ),
        tri="event_date", colonne_date="event_date", limite_defaut=15, limite_max=30, lignes_lues=200,
        regrouper=regrouper_evenements, sources_regroupees=sources_evenements,
    ),
    "signaux_faibles": SpecJeu(
        jeu="signaux_faibles",
        colonnes=("titre", "score", "tendance", "categorie", "themes", "date_detection", "mentions_count_current",
                  "mentions_count_baseline_avg", "periode_start", "periode_end", "parlementaires_lies"),
        params=(
            _p_contient("theme", "titre", "Thème cherché dans l'intitulé du signal (3 lettres au moins)."),
            _p_limite(8, 15, "signaux"),
        ),
        tri="date_detection", limite_defaut=8,
        renommer={"mentions_count_current": "mentions_periode", "mentions_count_baseline_avg": "mentions_moyenne_habituelle"},
    ),
    "senat_dossiers": SpecJeu(
        jeu="senat_dossiers",
        colonnes=("signet", "titre_court", "type_libelle", "etat", "derniere_etape", "date_derniere_etape", "date_depot",
                  "procedure_acceleree", "date_loi", "numero_loi", "url", "dossier_an_uid"),
        params=(_p_recherche("Mots-clés du texte (ex. « incendies de forêt »).", requis=True), _p_limite(5, 10, "dossiers")),
        limite_defaut=5,
        renommer={"dossier_an_uid": "dossier_assemblee", "type_libelle": "nature"},
        source_ligne=_source_url_ligne(lambda l: f"Dossier législatif du Sénat « {l.get('titre_court') or l.get('signet')} »",
                                       "dossier", ref="signet"),
    ),
    "senat_derniers_scrutins": SpecJeu(
        jeu="senat_scrutins",
        colonnes=("id", "numero", "date_scrutin", "intitule", "resultat", "pour", "contre", "votants", "url"),
        params=(
            _p_depuis(), _p_jusqu_a(),
            _p_contient("recherche", "intitule", "Mot contenu dans l'intitulé du scrutin (3 lettres au moins)."),
            _p_limite(10, 20, "scrutins"),
        ),
        tri="date_scrutin", colonne_date="date_scrutin",
        tronquer={"intitule": 260}, renommer={"intitule": "objet"},
        source_ligne=_source_url_ligne(lambda l: f"Scrutin du Sénat n° {l.get('numero')} du {date_fr(l.get('date_scrutin'))}",
                                       "scrutin_senat"),
    ),
    "senat_agenda": SpecJeu(
        jeu="senat_reunions",
        colonnes=("debut", "heure_libelle", "organe", "titre", "contenu", "type_reunion", "previsionnel"),
        params=(
            _p_depuis("Date de début incluse, AAAA-MM-JJ (défaut : lundi de la semaine)."),
            _p_jusqu_a("Date de fin incluse, AAAA-MM-JJ (défaut : dimanche de la semaine)."),
            ParamJeu("commissions", {"type": "boolean", "description": "true : ajoute les réunions de commission."},
                     role="booleen", filtre_si_faux={"colonne": "type_reunion", "op": "eq", "valeur": "seance"}),
            _p_limite(20, 40, "réunions"),
        ),
        tri="debut", ordre="asc", colonne_date="debut", date_horodatee=True, periode_defaut_semaine=True,
        limite_defaut=20, limite_max=40,
        tronquer={"contenu": 300}, renommer={"debut": "jour", "heure_libelle": "moment"},
    ),
    "senat_amendements": SpecJeu(
        jeu="senat_amendements",
        colonnes=("id", "numero_complet", "texte_id", "date_depot", "auteur_libelle", "groupe", "sort",
                  "avis_commission", "avis_gouvernement", "objet", "url"),
        params=(
            _p_recherche("Mots-clés cherchés dans le dispositif et l'objet des amendements."),
            _p_depuis("Date de dépôt minimale, AAAA-MM-JJ."), _p_jusqu_a("Date de dépôt maximale, AAAA-MM-JJ."),
            _p_limite(8, 20, "amendements"),
        ),
        tri="date_depot", colonne_date="date_depot", limite_defaut=8,
        tronquer={"objet": 280}, renommer={"numero_complet": "numero", "auteur_libelle": "auteur"},
        source_ligne=_source_url_ligne(lambda l: f"Amendement n° {l.get('numero_complet')} (Sénat)", "amendement_senat"),
    ),
    "lois_publiees": SpecJeu(
        jeu="legifrance_lois_decrets",
        colonnes=("texte_id", "titre", "nature", "etat", "date", "articles", "extraits"),
        params=(
            _p_recherche("Mots qui doivent TOUS figurer dans un même article (2 ou 3 mots précis).", requis=True),
            ParamJeu("nature", {"type": "string", "enum": ["LOI", "ORDONNANCE", "DECRET", "ARRETE"],
                                "description": "Type de texte."}, colonne="nature"),
            _p_limite(5, 10, "textes"),
        ),
        limite_defaut=5, tronquer={"extraits": 300, "titre": 220},
    ),
    "lobbying_hatvp": SpecJeu(
        jeu="representants_interets",
        colonnes=("denomination", "categorie", "secteurs", "domaines", "dirigeants", "depenses_tranche", "nb_salaries",
                  "site_web", "identifiant_national"),
        params=(
            _p_contient("nom", "denomination", "Nom de l'organisation (3 lettres au moins).", requis=True),
            _p_limite(5, 10, "organisations"),
        ),
        limite_defaut=5,
    ),
}


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

CATEGORIES: list[dict[str, str]] = [
    {"id": "actualite", "titre": "Actualité de l'Assemblée", "aide": "Votes, ordre du jour et dépôts récents."},
    {"id": "textes", "titre": "Textes et amendements (Assemblée)", "aide": "Retrouver un texte, son dossier, ses amendements."},
    {"id": "votes", "titre": "Votes et groupes", "aide": "Détail d'un scrutin, positions des groupes, tendances."},
    {"id": "deputes", "titre": "Députés", "aide": "Retrouver un député et sa fiche."},
    {"id": "senat", "titre": "Sénat et navette", "aide": "État d'un texte au Sénat, scrutins, agenda, amendements."},
    {"id": "signaux", "titre": "Signaux et fil d'Hémicycle", "aide": "Données calculées par Hémicycle (5 crédits)."},
    {"id": "contexte", "titre": "Contexte", "aide": "Lois en vigueur, lobbying, données publiques."},
]


@dataclass(frozen=True)
class Endpoint:
    nom: str
    titre: str
    categorie: str
    type: str  # mcp | local | jeu
    cout: int  # crédits par appel (estimation, d'après le barème)
    consigne: str  # ligne du prompt système : quand utiliser l'outil ({lundi} = lundi de la semaine)
    description: str | None = None  # description pour le modèle (sinon : celle du serveur MCP)
    exemple: dict[str, Any] = field(default_factory=dict)
    aide: str = ""  # pour le journaliste (sinon : description)

    @property
    def outil_mcp(self) -> str:
        return self.nom if self.type == "mcp" else "interroger"

    @property
    def jeu(self) -> str | None:
        if self.type == "jeu":
            return SPECS_JEUX[self.nom].jeu
        return {"derniers_scrutins": "scrutins", "agenda_seances": "reunions"}.get(self.nom)


def _definition_jeu(nom: str, description: str) -> dict[str, Any]:
    spec = SPECS_JEUX[nom]
    return {
        "type": "function",
        "function": {
            "name": nom,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {p.nom: p.schema for p in spec.params},
                **({"required": [p.nom for p in spec.params if p.requis]} if any(p.requis for p in spec.params) else {}),
                "additionalProperties": False,
            },
        },
    }


ENDPOINTS: list[Endpoint] = [
    # --- Actualité ---
    Endpoint("derniers_scrutins", "Derniers scrutins", "actualite", "local", 1,
             "Actualité, « cette semaine », derniers votes à l'Assemblée : derniers_scrutins (depuis = {lundi}). "
             "Pour suivre un texte : recherche = mots-clés, sans « depuis ».",
             exemple={"depuis": "{lundi}", "limite": 10}),
    Endpoint("agenda_seances", "Ordre du jour des séances", "actualite", "local", 1,
             "Ordre du jour et textes en discussion à l'Assemblée : agenda_seances (commissions = true pour les commissions).",
             exemple={}),
    Endpoint("textes_deposes", "Textes déposés", "actualite", "jeu", 1,
             "Textes récemment déposés à l'Assemblée (projets et propositions de loi, rapports) : textes_deposes.",
             description="Documents déposés à l'Assemblée nationale (17e législature), du plus récent au plus ancien : "
                         "projets et propositions de loi, propositions de résolution, rapports, avis. 1 crédit.",
             exemple={"nature": "proposition de loi", "depuis": "{lundi}"}),
    Endpoint("fil_evenements", "Fil des événements (30 jours)", "signaux", "jeu", 5,
             "Vue d'ensemble des 30 derniers jours (votes, étapes de procédure, dépôts d'amendements par groupe) : "
             "fil_evenements (5 crédits).",
             description="Flux des événements parlementaires de l'Assemblée des 30 derniers jours, calculé par Hémicycle et "
                         "regroupé par jour : scrutins (solennels d'abord), étapes de procédure, amendements déposés par "
                         "auteur. 5 crédits.",
             exemple={"depuis": "{lundi}"}),
    # --- Textes ---
    Endpoint("rechercher", "Recherche plein texte (AN)", "textes", "mcp", 2,
             "« Où en est le texte sur X ? » : rechercher (q = mots-clés de X, types \"dossier,texte\") et "
             "derniers_scrutins (recherche = mots-clés). Donne d'abord l'étape la plus récente.",
             description="Recherche plein texte dans les textes, dossiers législatifs et amendements de l'Assemblée "
                         "nationale (ni scrutins, ni députés). Pour retrouver un texte par son sujet. 2 crédits.",
             exemple={"q": "incendies de forêt", "types": "dossier,texte", "limit": 5}),
    Endpoint("lire_texte", "Lire un texte", "textes", "mcp", 1,
             "Détail d'un texte : lire_texte avec un identifiant PRJL… ou PION… (jamais un dossier DLR…).",
             description="Lit un texte (projet ou proposition de loi, rapport) et son dossier législatif, par son "
                         "identifiant (ex. PRJLANR5L17B0123). 1 crédit.",
             exemple={"id": "PRJLANR5L17B3440"}),
    Endpoint("amendements_deposes", "Amendements déposés (AN)", "textes", "jeu", 1,
             "Amendements déposés à l'Assemblée sur un sujet ou un texte : amendements_deposes.",
             description="Amendements déposés à l'Assemblée nationale (17e législature), du plus récent au plus ancien : "
                         "numéro, texte, article, signataires, état, sort et début de l'exposé. 1 crédit.",
             exemple={"recherche": "feux de forêt", "limite": 8}),
    Endpoint("lire_amendement", "Lire un amendement", "textes", "mcp", 1,
             "Détail d'un amendement de l'Assemblée : lire_amendement (identifiant AMANR5…).",
             exemple={"id": "AMANR5L17PO838901BTC3188P0D1N001090"}),
    # --- Votes ---
    Endpoint("lire_scrutin", "Lire un scrutin", "votes", "mcp", 1,
             "Détail d'un vote : lire_scrutin (identifiant VTANR5L17V<numéro>).",
             exemple={"id": "VTANR5L17V9895"}),
    Endpoint("resultat_scrutin", "Résultat détaillé d'un scrutin", "votes", "mcp", 1,
             "Vote de chaque groupe et de chaque député sur un scrutin : resultat_scrutin (VTANR5L17V<numéro>).",
             exemple={"id": "VTANR5L17V9895"}),
    Endpoint("positions_groupes", "Positions des groupes", "votes", "mcp", 1,
             "Position des groupes sur plusieurs scrutins : positions_groupes (10 scrutins au plus par appel).",
             exemple={"scrutins": ["VTANR5L17V9895"]}),
    Endpoint("accord_groupes", "Accord entre groupes", "votes", "mcp", 5,
             "Groupes qui votent ensemble sur une période : accord_groupes (5 crédits ; depuis/jusqu_a ou legislature = 17).",
             exemple={"depuis": "2026-10-01", "jusqu_a": "2026-10-31"}),
    Endpoint("loyaute_deputes", "Loyauté des députés", "votes", "mcp", 5,
             "Députés qui votent le moins comme leur groupe : loyaute_deputes (5 crédits ; période obligatoire).",
             exemple={"depuis": "2026-10-01", "jusqu_a": "2026-10-31", "groupe": "RN"}),
    Endpoint("classement_auteurs", "Classement des auteurs d'amendements", "votes", "mcp", 5,
             "Qui dépose le plus d'amendements (sur un texte, un sujet ou une période) : classement_auteurs (5 crédits).",
             exemple={"texte": "PRJLANR5L17BTC3188", "limite": 10}),
    # --- Députés ---
    Endpoint("chercher_depute", "Chercher un député", "deputes", "jeu", 1,
             "Un député précis (son groupe, ses fonctions, son vote) : chercher_depute (nom = nom de famille seul ; "
             "anciens = true pour un ancien député) donne son identifiant PA… et son groupe.",
             description="Députés en exercice dont le nom de famille contient le texte donné : identifiant (PA…), "
                         "civilité, prénom, nom, groupe politique actuel et profession. Avec anciens = true : députés et "
                         "anciens députés (sans le groupe). 1 crédit.",
             exemple={"nom": "Lemaire"}),
    Endpoint("lire_acteur", "Fiche d'un parlementaire", "deputes", "mcp", 1,
             "Mandats et fonctions d'un député (commissions, missions, rapports) : lire_acteur (identifiant PA… donné "
             "par chercher_depute). Son vote sur un scrutin : resultat_scrutin, où il figure par son nom (absent : "
             "il ne fait pas partie des votants).",
             description="Fiche d'un député par son identifiant PA… (donné par chercher_depute) : identité, profession "
                         "et mandats en cours (commissions, missions, fonctions), désignés par l'identifiant de "
                         "l'organe (PO…). Le groupe politique est donné par chercher_depute. 1 crédit.",
             exemple={"id": "PA794838"}),
    # --- Sénat ---
    Endpoint("senat_dossiers", "Dossiers du Sénat (navette)", "senat", "jeu", 1,
             "État d'un texte dans la navette (dernière étape, adoption définitive, promulgation, numéro de loi) : "
             "senat_dossiers (recherche = mots-clés).",
             description="Dossiers législatifs du Sénat : état, dernière étape et sa date, procédure accélérée, date et "
                         "numéro de la loi une fois promulguée, lien vers le dossier de l'Assemblée. 1 crédit.",
             exemple={"recherche": "incendies de forêt"}),
    Endpoint("senat_derniers_scrutins", "Scrutins du Sénat", "senat", "jeu", 1,
             "Votes au Sénat : senat_derniers_scrutins.",
             description="Scrutins publics du Sénat, du plus récent au plus ancien : numéro, date, objet, résultat et "
                         "décompte. 1 crédit.",
             exemple={"depuis": "{lundi}"}),
    Endpoint("senat_agenda", "Agenda du Sénat", "senat", "jeu", 1,
             "Ordre du jour du Sénat : senat_agenda.",
             description="Séances publiques du Sénat sur une période (par défaut la semaine en cours) : jour, moment, "
                         "titre et ordre du jour ; commissions = true ajoute les commissions. 1 crédit.",
             exemple={}),
    Endpoint("senat_amendements", "Amendements du Sénat", "senat", "jeu", 1,
             "Amendements déposés au Sénat : senat_amendements.",
             description="Amendements déposés au Sénat, du plus récent au plus ancien : numéro, auteur, groupe, sort, avis "
                         "de la commission et du Gouvernement, début de l'objet. 1 crédit.",
             exemple={"recherche": "incendie"}),
    # --- Signaux ---
    Endpoint("signaux_faibles", "Signaux faibles", "signaux", "jeu", 5,
             "Sujets montants dans les débats et les médias : signaux_faibles (5 crédits ; le score est un indice "
             "d'intensité de 0 à 100, pas une probabilité).",
             description="Signaux faibles détectés par Hémicycle : sujets dont les mentions parlementaires ou médiatiques "
                         "augmentent par rapport à leur moyenne (score : indice d'intensité de 0 à 100, pas une "
                         "probabilité). 5 crédits.",
             exemple={"limite": 8}),
    # --- Contexte ---
    Endpoint("lois_publiees", "Lois et décrets en vigueur", "contexte", "jeu", 1,
             "Loi, ordonnance ou décret publié et en vigueur (Légifrance) : lois_publiees (2 ou 3 mots précis).",
             description="Recherche dans les lois, ordonnances, décrets et arrêtés en vigueur (Légifrance) : titre, nature, "
                         "date de publication, articles et extraits. Tous les mots doivent figurer dans un même article. "
                         "1 crédit.",
             exemple={"recherche": "débroussaillement", "nature": "LOI"}),
    Endpoint("lobbying_hatvp", "Représentants d'intérêts (HATVP)", "contexte", "jeu", 1,
             "Organisation inscrite au répertoire des représentants d'intérêts : lobbying_hatvp (nom de l'organisation).",
             description="Organisations inscrites au répertoire des représentants d'intérêts de la HATVP : catégorie, "
                         "secteurs, domaines, dirigeants déclarés, tranche de dépenses. 1 crédit.",
             exemple={"nom": "TotalEnergies"}),
    Endpoint("chercher_donnees_publiques", "Chercher sur data.gouv.fr", "contexte", "mcp", 2,
             "Données publiques complémentaires : chercher_donnees_publiques, puis lire_donnees_publiques.",
             exemple={"q": "feux de forêt"}),
    Endpoint("lire_donnees_publiques", "Lire un fichier data.gouv.fr", "contexte", "mcp", 2,
             "Lire un fichier trouvé par chercher_donnees_publiques : lire_donnees_publiques (identifiant du fichier).",
             exemple={"fichier": "<identifiant renvoyé par chercher_donnees_publiques>", "lignes": 20}),
]
PAR_NOM: dict[str, Endpoint] = {e.nom: e for e in ENDPOINTS}

# Outils d'Hémicycle volontairement non proposés (affichés avec la raison dans l'outil).
NON_PROPOSES: list[dict[str, Any]] = [
    {"nom": "predire_vote", "cout": 50, "raison": "Prédiction d'un modèle (Orcet), pas une donnée publique ; 50 crédits."},
    {"nom": "interroger", "cout": 1, "raison": "Accès brut aux 132 jeux, dont les prédictions Orcet à 50 crédits par ligne : "
                                              "remplacé par les endpoints ciblés ci-dessus."},
    {"nom": "chercher_entreprise", "cout": 2, "raison": "Hors du périmètre de la veille parlementaire."},
    {"nom": "guide", "cout": 0, "raison": "Documentation d'Hémicycle, inutile pour répondre."},
    {"nom": "lister_jeux", "cout": 0, "raison": "Catalogue technique des jeux de données."},
    {"nom": "solde_credits", "cout": 0, "raison": "Affiché dans l'en-tête de l'outil, jamais donné au modèle."},
]

# Sélection par défaut (outil de rédaction) et sélections prêtes à l'emploi.
# Aussi la sélection du chatbot du rapport (lecteurs) : chercher_depute et lire_acteur y répondent
# aux questions sur un député précis.
SELECTION_DEFAUT: tuple[str, ...] = (
    "derniers_scrutins", "agenda_seances", "rechercher", "lire_texte", "lire_scrutin",
    "positions_groupes", "resultat_scrutin", "lire_amendement", "chercher_depute", "lire_acteur",
)
PRESELECTIONS: list[dict[str, Any]] = [
    {"id": "essentiel", "titre": "Essentiel", "outils": list(SELECTION_DEFAUT)},
    {"id": "assemblee", "titre": "Assemblée complète", "outils": [
        *SELECTION_DEFAUT, "textes_deposes", "amendements_deposes", "fil_evenements"]},
    {"id": "navette", "titre": "Navette AN + Sénat", "outils": [
        "derniers_scrutins", "agenda_seances", "rechercher", "lire_texte", "senat_dossiers", "senat_derniers_scrutins",
        "senat_agenda", "senat_amendements", "lois_publiees"]},
    {"id": "votes", "titre": "Analyse des votes", "outils": [
        "derniers_scrutins", "lire_scrutin", "resultat_scrutin", "positions_groupes", "accord_groupes",
        "loyaute_deputes", "classement_auteurs", "chercher_depute", "lire_acteur"]},
    {"id": "signaux", "titre": "Signaux et contexte", "outils": [
        "fil_evenements", "signaux_faibles", "derniers_scrutins", "rechercher", "lobbying_hatvp", "lois_publiees",
        "chercher_donnees_publiques", "lire_donnees_publiques"]},
]


def definition(endpoint: Endpoint, definitions_locales: dict[str, dict[str, Any]],
               schemas_mcp: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Définition d'outil au format OpenAI, ou None si l'endpoint est indisponible."""
    if endpoint.type == "jeu":
        return _definition_jeu(endpoint.nom, endpoint.description or endpoint.titre)
    if endpoint.type == "local":
        return json.loads(json.dumps(definitions_locales.get(endpoint.nom))) if endpoint.nom in definitions_locales else None
    schema_serveur = schemas_mcp.get(endpoint.nom)
    if schema_serveur is None:
        return None
    return {
        "type": "function",
        "function": {
            "name": endpoint.nom,
            "description": endpoint.description or schema_serveur.get("description") or endpoint.titre,
            "parameters": schema_serveur.get("parameters") or {"type": "object", "properties": {}},
        },
    }


def remplacer_jours(valeur: Any, aujourd_hui: date) -> Any:
    """Remplace « {lundi} » / « {aujourd_hui} » dans un exemple ou une consigne."""
    lundi, _ = semaine(aujourd_hui)
    if isinstance(valeur, str):
        return valeur.replace("{lundi}", lundi.isoformat()).replace("{aujourd_hui}", aujourd_hui.isoformat())
    if isinstance(valeur, dict):
        return {cle: remplacer_jours(v, aujourd_hui) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [remplacer_jours(v, aujourd_hui) for v in valeur]
    return valeur


# --------------------------------------------------------------------------
# Attribution : quel appel Hémicycle justifie chaque ligne de la réponse ?
# --------------------------------------------------------------------------

MOTIF_IDENTIFIANT = re.compile(r"\b(VTANR5L\d+V\d+|(?:PRJL|PION|RAPP|AVIS|RION)ANR5L\d+B(?:TC|TA)?\d+|AMANR5L\w+|DLR5L\d+N\d+|PA\d{4,}|PO\d{4,})\b")
MOTIF_NUMERO = re.compile(r"n\s*°\s*(\d+)", re.IGNORECASE)
MOTIF_DATE_FR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre")
# « 31 mars 2026 », « 1er décembre 2025 » (chatbot du rapport : dates en toutes lettres).
MOTIF_DATE_LONGUE = re.compile(rf"\b(\d{{1,2}})(?:er)?\s+({'|'.join(MOIS_FR)})\s+(\d{{4}})\b", re.IGNORECASE)
MOTIF_FICHE = re.compile(r"\bfiche\s+(?:du|de\s+la|de)\s+(?:député|députée|parlementaire)", re.IGNORECASE)


def dates_de_la_ligne(ligne: str) -> list[tuple[str, str, str]]:
    """Dates (jour, mois, année) sur deux chiffres / deux chiffres / quatre chiffres, quel que soit le format."""
    dates = MOTIF_DATE_FR.findall(ligne)
    for jour, mois, annee in MOTIF_DATE_LONGUE.findall(ligne):
        dates.append((f"{int(jour):02d}", f"{MOIS_FR.index(mois.lower()) + 1:02d}", annee))
    return dates


def nomme_le_depute(source: dict[str, Any], texte: str) -> bool:
    """Source « député » : son nom de famille figure dans le texte, en mot entier (casse ignorée)."""
    nom = str(source.get("nom") or "").strip()
    if source.get("nature") != "depute" or len(nom) < 2:
        return False
    return re.search(rf"(?<![\w-]){re.escape(nom)}(?![\w-])", texte, re.IGNORECASE) is not None


def _cite(source: dict[str, Any], ligne: str) -> bool:
    if source.get("nature") == "agenda":
        return "ordre du jour" in ligne.lower()
    ref = source.get("ref")
    if ref and str(ref) in ligne:
        return True
    if nomme_le_depute(source, ligne):
        return True
    # « (fiche du député, …) » : la fiche lue par lire_acteur.
    if source.get("nature") == "depute" and source.get("outil") == "lire_acteur" and MOTIF_FICHE.search(ligne):
        return True
    numero = source.get("numero")
    return numero is not None and re.search(rf"n\s*°\s*{int(numero)}(?!\d)", ligne) is not None


def attribuer_lignes(texte: str, appels: Iterable[tuple[int, str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Découpe la réponse en lignes et associe à chacune les appels dont elle reprend une donnée.

    `appels` : (indice dans outils_utilises, contenu renvoyé au modèle, sources de l'appel), appels réussis seulement.
    Preuves : source citée (référence, n° ou nom du député) et identifiant ou n° présent dans le résultat
    (cumulés) ; à défaut, date présente dans au plus deux résultats."""
    appels = list(appels)
    lignes: list[dict[str, Any]] = []
    for brute in texte.split("\n"):
        ligne = brute.strip()
        if not ligne:
            continue
        if ligne.startswith("#"):  # titre de section : pas de donnée à justifier
            lignes.append({"texte": ligne, "appels": []})
            continue
        trouves: list[int] = [i for i, _, sources in appels if any(_cite(s, ligne) for s in sources)]
        # Identifiant ou n° repris d'un résultat : cumulé avec les sources citées (« Didier Lemaire a voté
        # pour (scrutin n° 9895) » s'appuie sur chercher_depute ET sur resultat_scrutin).
        identifiants = MOTIF_IDENTIFIANT.findall(ligne)
        numeros = [n for n in MOTIF_NUMERO.findall(ligne) if len(n) >= 2]
        for i, contenu, _ in appels:
            if i not in trouves and (any(ident in contenu for ident in identifiants) or any(
                re.search(rf"(?<![\d.,]){n}(?![\d])", contenu) for n in numeros
            )):
                trouves.append(i)
        if not trouves:
            dates = dates_de_la_ligne(ligne)
            candidats = [
                i for i, contenu, _ in appels
                if any(f"{j}/{m}/{a}" in contenu or f"{a}-{m}-{j}" in contenu for j, m, a in dates)
            ]
            if 0 < len(candidats) <= 2:
                trouves = candidats
        lignes.append({"texte": ligne, "appels": sorted(set(trouves))})
    return lignes
