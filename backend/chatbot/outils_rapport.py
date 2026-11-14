"""Outils « rapport » du chatbot : lister les sections du numéro et surligner celle qui répond.

Le lecteur lit le rapport mensuel (``rapports/AAAA-MM/rapport.md``) sur une page web, à côté
du chatbot. Ce module donne au modèle deux outils (format ``tools`` d'OpenAI) :

- ``lister_sections_rapport()`` : les sections (catégories) du numéro, avec leur identifiant ;
- ``surligner_section(section_id, raison)`` : outil **côté client**. Le serveur ne fait que
  valider l'identifiant et enregistrer une *action* destinée à la page web (défilement jusqu'à
  la section, puis mise en évidence). Le modèle reçoit une confirmation courte, ou une erreur
  exploitable (avec la liste des identifiants valides) si l'identifiant n'existe pas.

Les actions sont renvoyées au front dans le champ ``actions`` de ``POST /chat`` (contrat dans
``docs/ARCHITECTURE.md``).

Exemple (une instance par question ; la lecture du fichier est mise en cache) ::

    rapport = OutilsRapport("2026-10")
    outils = [*outils_mcp, *rapport.outils_openai()]       # → paramètre tools= de Featherless
    for tool_call in message.tool_calls:
        if rapport.gere(tool_call.function.name):
            message_tool, actions = rapport.executer(tool_call)   # synchrone, sans réseau
            messages.append(message_tool)                         # message role: tool
    corps["actions"] = rapport.actions                            # champ actions de /chat
    corps["sources"] += rapport.sources()                         # sources de type « rapport »

Pas de dépendance hors bibliothèque standard (le front-matter YAML est lu par un mini-parseur).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_RAPPORTS = RACINE / "rapports"

# Numéros acceptés : un mois AAAA-MM, ou le numéro de démonstration. Rien d'autre (pas de chemin).
MOTIF_NUMERO = re.compile(r"^(?:\d{4}-(?:0[1-9]|1[0-2])|demo)$")

NOM_LISTER = "lister_sections_rapport"
NOM_SURLIGNER = "surligner_section"
NOMS_OUTILS = frozenset({NOM_LISTER, NOM_SURLIGNER})

TYPE_ACTION_SURLIGNER = "surligner_section"
MAX_SURLIGNAGES_PAR_DEFAUT = 2  # sections surlignées au plus par question
MAX_CARACTERES_EXTRAIT = 180
MAX_CARACTERES_RAISON = 200
MAX_CARACTERES_SLUG = 60
# Taille max du rapport injecté dans le prompt système (≈ 10K tokens).
MAX_CARACTERES_PROMPT = 40000


class NumeroInvalide(ValueError):
    """Le mois demandé n'a pas la forme AAAA-MM (ou « demo »)."""


class RapportIntrouvable(FileNotFoundError):
    """Aucun fichier ``rapports/<mois>/rapport.md``."""


# --------------------------------------------------------------------------
# Lecture du Markdown
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Section:
    id: str  # identifiant stable (slug), unique dans le rapport
    titre: str  # titre sans marques Markdown
    niveau: int  # 2 pour « ## », 3 pour « ### »
    parent: str | None  # id de la section « ## » qui contient une « ### »
    extrait: str  # début du texte, sans Markdown
    markdown: str  # corps de la section (jusqu'au titre suivant, quel que soit son niveau)

    def resume(self) -> dict[str, Any]:
        """Ce que voit le modèle via `lister_sections_rapport`."""
        return {"id": self.id, "titre": self.titre, "niveau": self.niveau, "parent": self.parent, "extrait": self.extrait}

    def en_json(self) -> dict[str, Any]:
        """Ce que reçoit la page web via `GET /api/rapport/{mois}`."""
        return {**self.resume(), "markdown": self.markdown}


@dataclass(frozen=True)
class Rapport:
    mois: str
    titre: str  # titre « # » du numéro (à défaut : `titre` du front-matter)
    meta: dict[str, Any]  # front-matter
    introduction: str  # Markdown entre le titre « # » et la première section (chapô, bandeau…)
    sections: tuple[Section, ...]
    chemin: Path = field(compare=False)

    @property
    def ids(self) -> list[str]:
        return [section.id for section in self.sections]

    @property
    def fictif(self) -> bool:
        return bool(self.meta.get("fictif"))

    def section(self, section_id: str) -> Section | None:
        return next((section for section in self.sections if section.id == section_id), None)

    def en_json(self) -> dict[str, Any]:
        return {
            "mois": self.mois,
            "titre": self.titre,
            "chapo": self.meta.get("chapo") or "",
            "fictif": self.fictif,
            "meta": self.meta,
            "introduction": self.introduction,
            "sections": [section.en_json() for section in self.sections],
        }

    def texte_pour_prompt(self, max_caracteres: int = MAX_CARACTERES_PROMPT) -> str:
        """Le rapport à injecter dans le prompt système, chaque section précédée de son identifiant."""
        blocs = [f"# {self.titre}"]
        if self.introduction:
            blocs.append(self.introduction)
        for section in self.sections:
            dans = ""
            if section.parent:
                parent = self.section(section.parent)
                dans = f" (sous-section de « {parent.titre if parent else section.parent} »)"
            entete = f"[{section.id}] {'#' * section.niveau} {section.titre}{dans}"
            blocs.append(f"{entete}\n{section.markdown}".rstrip())
        texte = "\n\n".join(blocs)
        if len(texte) > max_caracteres:
            texte = texte[:max_caracteres].rstrip() + "\n[… rapport tronqué]"
        return texte

    def texte_brut(self) -> str:
        """Tout le texte du rapport sans Markdown (par exemple pour vérifier les chiffres d'une réponse)."""
        morceaux = [self.titre, texte_brut(self.introduction)]
        morceaux += [f"{section.titre}\n{texte_brut(section.markdown)}" for section in self.sections]
        return "\n".join(m for m in morceaux if m)


def slugifier(texte: str) -> str:
    """« L'essentiel du mois » → « l-essentiel-du-mois » (sans accents, minuscules, tirets)."""
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae").replace("Æ", "ae")
    slug = re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")
    if len(slug) > MAX_CARACTERES_SLUG:
        coupe = slug[:MAX_CARACTERES_SLUG]
        slug = coupe.rsplit("-", 1)[0] if "-" in coupe else coupe
    return slug


_LIEN = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_GRAS = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIQUE = re.compile(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])")
_CODE = re.compile(r"`([^`]*)`")
_PUCE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SEPARATEUR_TABLEAU = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _ligne_brute(ligne: str) -> str:
    ligne = ligne.strip()
    if _SEPARATEUR_TABLEAU.match(ligne):
        return ""
    if ligne.startswith("|"):
        cellules = [c.strip() for c in ligne.strip("|").split("|")]
        ligne = " ; ".join(c for c in cellules if c)
    ligne = re.sub(r"^(?:>\s?)+", "", ligne)
    ligne = re.sub(r"^#{1,6}\s+", "", ligne)
    ligne = _PUCE.sub("", ligne)
    ligne = _LIEN.sub(r"\1", ligne)
    ligne = _CODE.sub(r"\1", ligne)
    ligne = _GRAS.sub(r"\2", ligne)
    ligne = _ITALIQUE.sub(r"\2", ligne)
    return ligne.strip()


def texte_brut(markdown: str) -> str:
    """Retire l'essentiel des marques Markdown (liens, emphase, puces, tableaux, citations)."""
    lignes = (_ligne_brute(ligne) for ligne in markdown.splitlines())
    return re.sub(r"\s+", " ", " ".join(ligne for ligne in lignes if ligne)).strip()


def couper(texte: str, max_caracteres: int) -> str:
    """Coupe à la fin d'un mot et ajoute « … » si besoin."""
    if len(texte) <= max_caracteres:
        return texte
    coupe = texte[: max_caracteres - 1]
    if " " in coupe:
        coupe = coupe.rsplit(" ", 1)[0]
    return coupe.rstrip(" ,;:.-") + "…"


def _valeur_yaml(brut: str) -> Any:
    brut = brut.strip()
    if len(brut) >= 2 and brut[0] == brut[-1] and brut[0] in "\"'":
        return brut[1:-1]
    if brut.startswith("[") and brut.endswith("]"):
        return [_valeur_yaml(v) for v in brut[1:-1].split(",") if v.strip()]
    if brut.lower() in ("true", "oui", "yes"):
        return True
    if brut.lower() in ("false", "non", "no"):
        return False
    return brut


def separer_front_matter(texte: str) -> tuple[dict[str, Any], str]:
    """Sépare le front-matter YAML (entre deux lignes « --- ») du corps.

    Mini-parseur : lignes « clé: valeur », chaînes entre guillemets, listes « [a, b] », booléens.
    Sans front-matter (ou s'il n'est jamais refermé), renvoie ({}, texte).
    """
    lignes = texte.lstrip("﻿").splitlines()
    if not lignes or lignes[0].strip() != "---":
        return {}, texte
    for fin in range(1, len(lignes)):
        if lignes[fin].strip() in ("---", "..."):
            break
    else:
        return {}, texte
    meta: dict[str, Any] = {}
    for ligne in lignes[1:fin]:
        if ":" in ligne and not ligne.startswith((" ", "\t", "#", "-")):
            cle, _, valeur = ligne.partition(":")
            meta[cle.strip()] = _valeur_yaml(valeur)
    return meta, "\n".join(lignes[fin + 1 :])


_TITRE = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_ID_EXPLICITE = re.compile(r"\s*\{#([^}\s]+)\}\s*$")
_CLOTURE = re.compile(r"^\s*(```|~~~)")
_CATEGORIE = re.compile(r"\s*:\s+")


def _identifiant(titre_md: str, deja: set[str]) -> tuple[str, str]:
    """(id, titre). Un « {#id} » final fixe l'id ; sinon slug de la partie avant « : » (« Focus : X » → focus)."""
    explicite = _ID_EXPLICITE.search(titre_md)
    titre = texte_brut(titre_md[: explicite.start()] if explicite else titre_md)
    if explicite:
        base = slugifier(explicite.group(1))
    else:
        base = slugifier(_CATEGORIE.split(titre, maxsplit=1)[0]) or slugifier(titre)
    base = base or "section"
    ident, n = base, 2
    while ident in deja:
        ident, n = f"{base}-{n}", n + 1
    deja.add(ident)
    return ident, titre


def analyser_rapport(texte: str, mois: str = "", chemin: Path | None = None) -> Rapport:
    """Découpe le Markdown en sections « ## » et « ### » (les titres plus profonds restent dans le corps).

    Ignorés : le front-matter, les titres dans les blocs de code. Le titre « # » donne le titre du numéro.
    """
    meta, corps = separer_front_matter(texte)
    titre_numero = ""
    introduction: list[str] = []
    brutes: list[dict[str, Any]] = []  # sections en cours de construction
    dans_code = False
    for ligne in corps.splitlines():
        if _CLOTURE.match(ligne):
            dans_code = not dans_code
        correspondance = None if dans_code else _TITRE.match(ligne)
        niveau = len(correspondance.group(1)) if correspondance else 0
        if niveau == 1 and not titre_numero and not brutes:
            titre_numero = texte_brut(correspondance.group(2))
            continue
        if niveau in (2, 3):
            brutes.append({"niveau": niveau, "titre_md": correspondance.group(2), "lignes": []})
            continue
        (brutes[-1]["lignes"] if brutes else introduction).append(ligne)

    deja: set[str] = set()
    sections: list[Section] = []
    parent: str | None = None
    for brute in brutes:
        ident, titre = _identifiant(brute["titre_md"], deja)
        markdown = "\n".join(brute["lignes"]).strip()
        niveau = brute["niveau"]
        if niveau == 2:
            parent = ident
        sections.append(Section(
            id=ident, titre=titre or ident, niveau=niveau,
            parent=parent if niveau == 3 else None,
            extrait="", markdown=markdown,
        ))
    # Extraits : le début du texte ; pour une section sans texte propre, ses sous-sections.
    finales = []
    for section in sections:
        extrait = texte_brut(section.markdown)
        if not extrait:
            enfants = [s.titre for s in sections if s.parent == section.id]
            extrait = f"Sous-sections : {', '.join(enfants)}." if enfants else ""
        finales.append(replace(section, extrait=couper(extrait, MAX_CARACTERES_EXTRAIT)))
    return Rapport(
        mois=mois or str(meta.get("mois") or ""),
        titre=titre_numero or str(meta.get("titre") or ""),
        meta=meta,
        introduction="\n".join(introduction).strip(),
        sections=tuple(finales),
        chemin=chemin or Path(),
    )


# --------------------------------------------------------------------------
# Accès aux fichiers
# --------------------------------------------------------------------------


def chemin_rapport(mois: str, dossier: Path = DOSSIER_RAPPORTS) -> Path:
    if not isinstance(mois, str) or not MOTIF_NUMERO.match(mois):
        raise NumeroInvalide(f"Mois invalide : {mois!r} (attendu : AAAA-MM ou « demo »).")
    return Path(dossier) / mois / "rapport.md"


@lru_cache(maxsize=32)
def _lire(chemin: Path, mois: str, _version: tuple[int, int]) -> Rapport:
    return analyser_rapport(chemin.read_text(encoding="utf-8"), mois, chemin)


def charger_rapport(mois: str, dossier: Path = DOSSIER_RAPPORTS) -> Rapport:
    """Lit `rapports/<mois>/rapport.md` (mis en cache ; relu si le fichier change)."""
    chemin = chemin_rapport(mois, dossier)
    try:
        etat = chemin.stat()
    except FileNotFoundError as erreur:
        raise RapportIntrouvable(f"Aucun rapport pour {mois} ({chemin}).") from erreur
    return _lire(chemin, mois, (etat.st_mtime_ns, etat.st_size))


def numeros_disponibles(dossier: Path = DOSSIER_RAPPORTS) -> list[str]:
    """Numéros qui ont un `rapport.md`, du plus récent au plus ancien (« demo » en dernier)."""
    if not Path(dossier).is_dir():
        return []
    numeros = [d.name for d in Path(dossier).iterdir() if MOTIF_NUMERO.match(d.name) and (d / "rapport.md").is_file()]
    return sorted(numeros, key=lambda n: (n != "demo", n), reverse=True)


# --------------------------------------------------------------------------
# Les outils
# --------------------------------------------------------------------------


# À ajouter à la FIN du prompt système, après le texte du rapport (`Rapport.texte_pour_prompt()`).
# Essais du 14/11/2026 avec Qwen/Qwen3.8-27B : sans réflexion, le modèle n'appelle pas
# surligner_section (il répond directement, annonce l'appel sans le faire, ou écrit l'identifiant
# en texte ; `tool_choice="required"` est ignoré par Featherless). Avec la réflexion activée AU
# PREMIER TOUR SEULEMENT, il appelle l'outil correctement ; les tours suivants restent sans réflexion.
CONSIGNE_PROMPT = """Rapport affiché et surlignage :
- Le lecteur lit le rapport du mois sur la même page que toi. Chaque section du rapport porte un identifiant entre crochets, par exemple [cohesion-des-groupes].
- Si la question porte sur un sujet traité dans le rapport, ta PREMIÈRE action est l'appel de l'outil surligner_section : c'est lui qui fait défiler la page du lecteur jusqu'à la bonne section (citer la section dans le texte ne suffit pas). N'écris aucun texte avant cet appel et ne l'annonce pas : appelle directement l'outil.
- Une seule section ; deux au maximum si la réponse est vraiment répartie entre deux sections. Choisis la section qui contient la réponse détaillée : la sous-section précise (« Cohésion des groupes ») plutôt que la section générale (« Baromètre ») ou le résumé (« L'essentiel du mois »).
- Après la confirmation de l'outil, réponds brièvement à partir du texte de cette section, en la citant entre parenthèses, par exemple : (section « Cohésion des groupes »).
- Si aucune section ne traite la question, n'appelle pas surligner_section : ne surligne jamais une section au hasard ou faute de mieux.
- lister_sections_rapport donne la liste des sections et de leurs identifiants si besoin."""


def _lire_tool_call(tool_call: Any) -> tuple[str | None, str, Any]:
    """(id, nom, arguments) d'un `tool_call` OpenAI, objet du SDK ou dictionnaire."""
    if isinstance(tool_call, Mapping):
        fonction = tool_call.get("function") or {}
        return tool_call.get("id"), str(fonction.get("name") or ""), fonction.get("arguments")
    fonction = getattr(tool_call, "function", None)
    return getattr(tool_call, "id", None), str(getattr(fonction, "name", "") or ""), getattr(fonction, "arguments", None)


class OutilsRapport:
    """Les deux outils « rapport » d'un numéro. Créer une instance PAR QUESTION.

    L'instance accumule les actions de la question (`actions`) et un journal des appels au
    même format que `outils_utilises` de `serveur.py` (`appels`). La lecture et le découpage
    du fichier sont mis en cache : construire une instance ne coûte presque rien.
    """

    def __init__(
        self,
        mois: str,
        *,
        dossier: Path = DOSSIER_RAPPORTS,
        max_surlignages: int = MAX_SURLIGNAGES_PAR_DEFAUT,
        rapport: Rapport | None = None,
    ) -> None:
        self.rapport = rapport or charger_rapport(mois, dossier)  # NumeroInvalide, RapportIntrouvable
        self.max_surlignages = max_surlignages
        self.actions: list[dict[str, Any]] = []
        self.appels: list[dict[str, Any]] = []

    # --- Définitions pour le modèle ---

    def outils_openai(self) -> list[dict[str, Any]]:
        """Définitions au format `tools` d'OpenAI (à ajouter à celles du MCP)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": NOM_LISTER,
                    "description": (
                        "Liste les sections (catégories) du rapport mensuel que le lecteur a sous les yeux : "
                        "identifiant, titre, section parente et court extrait. Gratuit."
                    ),
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": NOM_SURLIGNER,
                    "description": (
                        "Fait défiler la page du lecteur jusqu'à la section du rapport qui répond à sa question "
                        "et la met en évidence. À appeler seulement si une section du rapport traite vraiment "
                        "la question (une seule section, deux au maximum). Ne renvoie aucune donnée. Gratuit."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "section_id": {
                                "type": "string",
                                "enum": self.rapport.ids,
                                "description": "Identifiant de la section (entre crochets dans le rapport).",
                            },
                            "raison": {
                                "type": "string",
                                "description": "Une courte phrase neutre, montrée au lecteur : ce que la section "
                                "dit sur sa question (15 mots au plus).",
                            },
                        },
                        "required": ["section_id", "raison"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def gere(self, nom_outil: str) -> bool:
        return nom_outil in NOMS_OUTILS

    def consigne_prompt(self) -> str:
        """Texte à ajouter au prompt système (avec `rapport.texte_pour_prompt()`)."""
        return CONSIGNE_PROMPT

    # --- Exécution ---

    def executer(self, tool_call: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Exécute un `tool_call` du modèle (synchrone, sans réseau).

        Renvoie `(message_role_tool, nouvelles_actions)`. Les nouvelles actions sont aussi
        ajoutées à `self.actions` ; une erreur donne un message exploitable et aucune action.
        """
        ident, nom, brut = _lire_tool_call(tool_call)
        arguments, erreur = self._arguments(brut)
        actions: list[dict[str, Any]] = []
        if erreur:
            contenu = erreur
        elif nom == NOM_LISTER:
            contenu = self._lister()
        elif nom == NOM_SURLIGNER:
            contenu, actions = self._surligner(arguments)
            erreur = None if actions or contenu.startswith("OK") else contenu
        else:
            contenu = erreur = f"Erreur : outil « {nom} » inconnu. Outils du rapport : {', '.join(sorted(NOMS_OUTILS))}."
        self.actions.extend(actions)
        self.appels.append({
            "outil": nom, "arguments": arguments, "statut": "erreur" if erreur else "ok",
            "credits": 0, "nb_sources": len(actions), "duree_s": 0.0,
        })
        return {"role": "tool", "tool_call_id": ident or "", "content": contenu}, actions

    @staticmethod
    def _arguments(brut: Any) -> tuple[dict[str, Any], str | None]:
        if isinstance(brut, str):
            try:
                brut = json.loads(brut) if brut.strip() else {}
            except ValueError:
                return {}, "Erreur : arguments illisibles (JSON invalide)."
        brut = brut or {}
        if not isinstance(brut, dict):
            return {}, "Erreur : les arguments doivent être un objet JSON."
        return brut, None

    def _lister(self) -> str:
        return json.dumps(
            {
                "mois": self.rapport.mois,
                "titre": self.rapport.titre,
                "sections": [section.resume() for section in self.rapport.sections],
            },
            ensure_ascii=False, separators=(",", ":"),
        )

    def _liste_ids(self) -> str:
        return ", ".join(f"{s.id} (« {s.titre} »)" for s in self.rapport.sections)

    def resoudre(self, valeur: Any) -> Section | None:
        """Section désignée par un identifiant ; tolère un titre, un « # » ou des crochets à la place."""
        if not isinstance(valeur, str) or not valeur.strip():
            return None
        valeur = valeur.strip().strip("[]#").strip()
        section = self.rapport.section(valeur)
        if section is None:
            slug = slugifier(valeur)
            section = self.rapport.section(slug) or next(
                (s for s in self.rapport.sections if slugifier(s.titre) == slug), None
            )
        return section

    def _surligner(self, arguments: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        demande = arguments.get("section_id")
        section = self.resoudre(demande)
        if section is None:
            return (
                f"Erreur : section « {demande} » inconnue. Identifiants valides : {self._liste_ids()}. "
                "Rappelle surligner_section avec l'un d'eux, ou ne surligne rien si aucune section ne traite la question.",
                [],
            )
        deja = [action["section_id"] for action in self.actions]
        if section.id in deja:
            return f"OK : la section « {section.titre} » est déjà surlignée. Rédige maintenant ta réponse.", []
        if len(deja) >= self.max_surlignages:
            return (
                f"Refusé : {self.max_surlignages} section(s) déjà surlignée(s) ({', '.join(deja)}), c'est le maximum. "
                "N'appelle plus surligner_section ; rédige maintenant ta réponse.",
                [],
            )
        raison = couper(re.sub(r"\s+", " ", str(arguments.get("raison") or "")).strip(), MAX_CARACTERES_RAISON)
        action = {"type": TYPE_ACTION_SURLIGNER, "section_id": section.id, "titre": section.titre, "raison": raison}
        return (
            f"OK : la section « {section.titre} » [{section.id}] est surlignée sur la page du lecteur. "
            f"Réponds maintenant brièvement à partir de son texte, en citant (section « {section.titre} »).",
            [action],
        )

    # --- Pour la réponse de /chat ---

    def sources(self) -> list[dict[str, Any]]:
        """Entrées `{"type": "rapport", …}` du champ `sources` de /chat, une par section surlignée."""
        resultat = []
        for action in self.actions:
            section = self.rapport.section(action["section_id"])
            if section:
                resultat.append({
                    "type": "rapport", "mois": self.rapport.mois, "section": section.titre,
                    "section_id": section.id, "passage": section.extrait,
                })
        return resultat


if __name__ == "__main__":  # aperçu : python outils_rapport.py [mois]
    import sys

    numero = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RAPPORT_MOIS", "demo")
    rapport_lu = charger_rapport(numero)
    print(f"{rapport_lu.titre} ({rapport_lu.mois}){' [fictif]' if rapport_lu.fictif else ''}")
    for s in rapport_lu.sections:
        print(f"{'  ' * (s.niveau - 2)}[{s.id}] {s.titre} — {s.extrait[:80]}")
