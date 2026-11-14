"""Test de connexion à Featherless : réponse simple, streaming, tool calling, réflexion.

Usage (depuis backend/chatbot/) :
    .venv/bin/python smoke_test.py                          # modèle du .env (FEATHERLESS_MODEL)
    .venv/bin/python smoke_test.py --model Qwen/Qwen3.8-27B
    .venv/bin/python smoke_test.py --tests simple,outils     # sous-ensemble de tests

Coût : 6 requêtes par modèle avec tous les tests (l'aller-retour d'outils en compte 2).
La clé API n'est jamais affichée.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

import openai

from featherless_client import (
    ClientFeatherless,
    ConcurrenceDepassee,
    ErreurConfiguration,
    ReponseChat,
    charger_config,
)

TESTS_DISPONIBLES = ("simple", "flux", "outils", "no_think", "kwargs")
MAX_TOKENS = 4096  # large : la réflexion de Qwen 3 compte dans la sortie

CONSIGNE = "Tu es un assistant qui répond en français, de façon concise et neutre."
QUESTION = "En deux phrases maximum, explique ce qu'est un amendement au Parlement français."

# --- Outil factice pour le test de tool calling ----------------------------

ID_ATTENDU = "VTANR5L17V4242"
OUTIL_LIRE_SCRUTIN = {
    "type": "function",
    "function": {
        "name": "lire_scrutin",
        "description": (
            "Lit un scrutin public de l'Assemblée nationale et son décompte (pour, contre, abstentions). "
            "L'identifiant a la forme VTANR5L17V<numéro> pour la 17e législature, "
            "par exemple VTANR5L17V1234 pour le scrutin n° 1234."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Identifiant du scrutin, par exemple VTANR5L17V1234."},
            },
            "required": ["id"],
        },
    },
}


def lire_scrutin_factice(id: str) -> dict[str, Any]:
    """Renvoie des données INVENTÉES, clairement marquées comme telles."""
    return {
        "donnees_fictives": True,
        "avertissement": "DONNÉES FICTIVES générées pour un test technique : ce scrutin n'existe pas.",
        "id": id,
        "titre": "Scrutin fictif sur l'ensemble d'un projet de loi imaginaire",
        "date": "2026-10-15",
        "sort": "adopté",
        "decompte": {"votants": 517, "exprimes": 498, "pour": 312, "contre": 186, "abstentions": 19},
    }


# --- Affichage -------------------------------------------------------------


@dataclass
class Resultat:
    nom: str
    ok: bool = False
    duree_s: float | None = None
    reflexion: str = "?"
    tokens: str = "non renvoyé"
    details: list[str] = field(default_factory=list)


class Masque:
    """Retire la clé de tout texte affiché (messages d'erreur compris)."""

    def __init__(self, cle: str) -> None:
        self._cle = cle

    def __call__(self, texte: Any) -> str:
        return str(texte).replace(self._cle, "***") if self._cle else str(texte)


def decrire_reflexion(reflexion: str | None) -> str:
    if reflexion is None:
        return "aucun bloc"
    if not reflexion.strip():
        return "bloc vide"
    return f"oui ({len(reflexion)} car.)"


def decrire_usage(usage: Any) -> str:
    if not usage:
        return "non renvoyé"
    texte = f"{usage.prompt_tokens} entrée / {usage.completion_tokens} sortie"
    details = getattr(usage, "completion_tokens_details", None)
    raisonnement = getattr(details, "reasoning_tokens", None) if details else None
    if raisonnement:
        texte += f" (dont {raisonnement} de réflexion)"
    return texte


def extrait(texte: str, longueur: int = 300) -> str:
    texte = " ".join(texte.split())
    return texte if len(texte) <= longueur else texte[:longueur] + "…"


def semble_francais(texte: str) -> bool:
    mots = f" {texte.lower()} "
    return sum(m in mots for m in (" le ", " la ", " les ", " de ", " des ", " est ", " un ", " une ")) >= 3


def anomalies(texte: str) -> list[str]:
    """Problèmes visibles dans le texte livré au lecteur."""
    trouvees = []
    if "<think>" in texte or "</think>" in texte:
        trouvees.append("balise de réflexion visible dans la réponse")
    if texte.lstrip().startswith("Safety:"):
        trouvees.append("sortie au format d'un classifieur de modération (type Qwen3Guard), pas une réponse du modèle")
    return trouvees


# --- Tests -----------------------------------------------------------------


def _reponse_texte(resultat: Resultat, reponse: ReponseChat) -> None:
    resultat.duree_s = reponse.duree_s
    resultat.reflexion = decrire_reflexion(reponse.reflexion)
    resultat.tokens = decrire_usage(reponse.usage)
    problemes = anomalies(reponse.texte)
    resultat.ok = bool(reponse.texte) and reponse.raison_fin != "length" and not problemes
    resultat.details.append(
        f"finish_reason : {reponse.raison_fin} · modèle servi : {reponse.modele_servi} · "
        f"français : {'oui' if semble_francais(reponse.texte) else 'à vérifier'}"
    )
    resultat.details.append(f"réponse : « {extrait(reponse.texte)} »")
    resultat.details += [f"ANOMALIE : {p} (requête {reponse.id_requete})" for p in problemes]


def test_simple(client: ClientFeatherless, resultat: Resultat) -> None:
    messages = [{"role": "system", "content": CONSIGNE}, {"role": "user", "content": QUESTION}]
    _reponse_texte(resultat, client.discuter(messages, max_tokens=MAX_TOKENS))


def test_flux(client: ClientFeatherless, resultat: Resultat) -> None:
    messages = [
        {"role": "system", "content": CONSIGNE},
        {"role": "user", "content": "Cite trois étapes de l'examen d'un projet de loi au Parlement français, en liste courte."},
    ]
    flux = client.discuter_en_flux(messages, max_tokens=MAX_TOKENS)
    nb_morceaux = 0
    print("     ↳ ", end="", flush=True)
    for morceau in flux:
        nb_morceaux += 1
        print(morceau.replace("\n", "\n       "), end="", flush=True)
    print()
    resultat.duree_s = flux.duree_s
    resultat.reflexion = f"oui ({flux.taille_reflexion} car.)" if flux.reflexion_detectee else "aucun bloc"
    resultat.tokens = decrire_usage(flux.usage)
    problemes = anomalies(flux.texte)
    resultat.ok = bool(flux.texte) and nb_morceaux > 1 and flux.raison_fin != "length" and not problemes
    resultat.details += [f"ANOMALIE : {p}" for p in problemes]
    premier = f"{flux.delai_premier_morceau_s:.1f} s" if flux.delai_premier_morceau_s is not None else "—"
    resultat.details.append(
        f"{nb_morceaux} morceaux visibles · premier morceau visible après {premier} · finish_reason : {flux.raison_fin}"
    )


def test_outils(client: ClientFeatherless, resultat: Resultat) -> None:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                f"{CONSIGNE} Pour toute question sur un scrutin précis, appelle l'outil lire_scrutin "
                "au lieu de répondre de mémoire. Si les données d'un outil sont marquées comme fictives, signale-le."
            ),
        },
        {"role": "user", "content": "Quel a été le résultat du scrutin n° 4242 de la 17e législature à l'Assemblée nationale ?"},
    ]
    # 1er appel : le modèle doit demander l'outil.
    premiere = client.discuter(messages, outils=[OUTIL_LIRE_SCRUTIN], max_tokens=MAX_TOKENS)
    resultat.reflexion = f"1er appel : {decrire_reflexion(premiere.reflexion)}"
    resultat.details.append(
        f"1er appel : {premiere.duree_s:.1f} s · finish_reason : {premiere.raison_fin} · "
        f"modèle servi : {premiere.modele_servi} · {decrire_usage(premiere.usage)}"
    )
    if not premiere.appels_outils:
        format_texte = "<tool_call>" in (premiere.message.content or "")
        resultat.details.append(
            "aucun tool_calls natif"
            + (" (appel écrit en texte brut <tool_call>, non parsé par le serveur)" if format_texte else "")
            + f" · texte : « {extrait(premiere.texte)} »"
        )
        resultat.details += [f"ANOMALIE : {p}" for p in anomalies(premiere.texte)]
        resultat.details.append(f"identifiant de requête : {premiere.id_requete}")
        resultat.duree_s = premiere.duree_s
        resultat.tokens = decrire_usage(premiere.usage)
        return

    arguments_ok = True
    messages.append(premiere.message_assistant())
    for appel in premiere.appels_outils:
        brut = appel.function.arguments
        try:
            arguments = json.loads(brut)
        except (TypeError, json.JSONDecodeError):
            arguments, arguments_ok = None, False
        bon_nom = appel.function.name == "lire_scrutin"
        bon_id = isinstance(arguments, dict) and arguments.get("id") == ID_ATTENDU
        arguments_ok = arguments_ok and bon_nom and bon_id
        resultat.details.append(
            f"tool_call : type={appel.type} · id={'présent' if appel.id else 'ABSENT'} · "
            f"nom={appel.function.name} · arguments={brut} (chaîne JSON : {'oui' if isinstance(brut, str) else 'non'}) · "
            f"id attendu {ID_ATTENDU} : {'oui' if bon_id else 'NON'}"
        )
        contenu = lire_scrutin_factice(**arguments) if bon_nom and isinstance(arguments, dict) and "id" in arguments \
            else {"erreur": "outil ou arguments inconnus"}
        messages.append({
            "role": "tool",
            "tool_call_id": appel.id,
            "name": appel.function.name,
            "content": json.dumps(contenu, ensure_ascii=False),
        })

    # 2e appel : le modèle rédige la réponse finale à partir du résultat.
    finale = client.discuter(messages, outils=[OUTIL_LIRE_SCRUTIN], max_tokens=MAX_TOKENS)
    resultat.duree_s = premiere.duree_s + finale.duree_s
    resultat.reflexion += f" · 2e appel : {decrire_reflexion(finale.reflexion)}"
    resultat.tokens = f"{decrire_usage(premiere.usage)} puis {decrire_usage(finale.usage)}"
    chiffres_repris = all(n in finale.texte for n in ("312", "186"))
    fictif_signale = "ficti" in finale.texte.lower()
    resultat.details.append(
        f"2e appel : {finale.duree_s:.1f} s · finish_reason : {finale.raison_fin} · "
        f"modèle servi : {finale.modele_servi} · {decrire_usage(finale.usage)}"
    )
    resultat.details.append(
        f"réponse finale : chiffres repris : {'oui' if chiffres_repris else 'NON'} · "
        f"caractère fictif signalé : {'oui' if fictif_signale else 'non'} · "
        f"nouvel appel d'outil : {'oui' if finale.appels_outils else 'non'}"
    )
    resultat.details.append(f"réponse : « {extrait(finale.texte)} »")
    resultat.ok = arguments_ok and bool(finale.texte) and chiffres_repris
    if not resultat.ok:
        resultat.details += [f"ANOMALIE : {p}" for p in anomalies(finale.texte)]
        resultat.details.append(f"contenu brut du 2e appel : {extrait(repr(finale.message.content), 500)}")
        resultat.details.append(f"identifiant de requête : {finale.id_requete}")


def test_no_think(client: ClientFeatherless, resultat: Resultat) -> None:
    """Interrupteur « doux » de Qwen 3 : /no_think à la fin du message utilisateur."""
    messages = [{"role": "system", "content": CONSIGNE}, {"role": "user", "content": f"{QUESTION} /no_think"}]
    _reponse_texte(resultat, client.discuter(messages, max_tokens=MAX_TOKENS))


def test_kwargs(client: ClientFeatherless, resultat: Resultat) -> None:
    """Paramètre documenté par Featherless : chat_template_kwargs = {"enable_thinking": false}."""
    messages = [{"role": "system", "content": CONSIGNE}, {"role": "user", "content": QUESTION}]
    _reponse_texte(resultat, client.discuter(messages, sans_reflexion=True, max_tokens=MAX_TOKENS))


TESTS: dict[str, tuple[str, Callable[[ClientFeatherless, Resultat], None]]] = {
    "simple": ("Réponse simple", test_simple),
    "flux": ("Streaming", test_flux),
    "outils": ("Tool calling (aller-retour)", test_outils),
    "no_think": ("Sans réflexion : /no_think", test_no_think),
    "kwargs": ("Sans réflexion : enable_thinking=false", test_kwargs),
}


# --- Programme principal ---------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Test de connexion à Featherless.")
    parser.add_argument("--model", help="Modèle à tester (défaut : FEATHERLESS_MODEL du .env).")
    parser.add_argument(
        "--tests", default=",".join(TESTS_DISPONIBLES),
        help=f"Tests à lancer, séparés par des virgules (défaut : tous). Choix : {', '.join(TESTS_DISPONIBLES)}.",
    )
    args = parser.parse_args()
    choisis = [t.strip() for t in args.tests.split(",") if t.strip()]
    inconnus = [t for t in choisis if t not in TESTS]
    if inconnus:
        parser.error(f"tests inconnus : {', '.join(inconnus)}")

    try:
        config = charger_config(args.model)
    except ErreurConfiguration as erreur:
        print(f"Configuration : {erreur}")
        return 2
    masque = Masque(config.cle_api)
    client = ClientFeatherless(config)
    print(f"Modèle : {config.modele}\nURL    : {config.base_url}\nClé    : chargée depuis le .env (non affichée)\n")

    resultats: list[Resultat] = []
    for cle in choisis:
        libelle, fonction = TESTS[cle]
        resultat = Resultat(libelle)
        resultats.append(resultat)
        print(f"── {libelle}")
        try:
            fonction(client, resultat)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as erreur:
            print(f"   ARRÊT : erreur d'authentification HTTP {erreur.status_code} : {masque(erreur)}")
            print(f"   Requêtes envoyées : {client.nb_requetes}")
            return 2
        except ConcurrenceDepassee as erreur:
            resultat.details.append(f"erreur : {masque(erreur)}")
        except openai.APIStatusError as erreur:
            resultat.details.append(f"erreur HTTP {erreur.status_code} : {masque(erreur)}")
        except openai.APIError as erreur:
            resultat.details.append(f"erreur {type(erreur).__name__} : {masque(erreur)}")
        duree = f"{resultat.duree_s:.1f} s" if resultat.duree_s is not None else "—"
        print(f"   {'SUCCÈS' if resultat.ok else 'ÉCHEC'} · latence {duree} · <think> : {resultat.reflexion} · tokens : {resultat.tokens}")
        for ligne in resultat.details:
            print(f"   · {ligne}")
        print()

    print(f"Bilan {config.modele} : {sum(r.ok for r in resultats)}/{len(resultats)} tests réussis · "
          f"{client.nb_requetes} requêtes envoyées")
    for r in resultats:
        duree = f"{r.duree_s:5.1f} s" if r.duree_s is not None else "    —  "
        print(f"  {'OK   ' if r.ok else 'ÉCHEC'} {duree}  {r.nom:<40} <think> : {r.reflexion}")
    return 0 if all(r.ok for r in resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
