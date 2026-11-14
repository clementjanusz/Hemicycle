"""Test de connexion au serveur MCP d'Hémicycle, sans LLM.

Étapes :
1. connexion et liste réelle des outils (nom, coût au barème, description courte) ;
2. définitions OpenAI de la liste blanche et leur taille estimée en tokens (≈ caractères / 4) ;
3. appels gratuits : solde_credits, guide (directement, puis via un tool_call OpenAI simulé) ;
4. garde-fous, sans coût : outil hors liste blanche, JSON invalide, sujet inconnu, limite d'appels ;
5. avec --payant seulement : deux appels payants peu chers (resultat_scrutin, 1 crédit ;
   rechercher, 2 crédits), plafonnés à BUDGET_MAX_CREDITS ;
6. solde après les appels et bilan du compteur.

Usage (depuis backend/chatbot/) :
    python mcp_smoke_test.py             # gratuit : 0 crédit
    python mcp_smoke_test.py --payant    # ≈ 3 crédits (clé hmc_live_ : crédits réels)

La clé est lue dans le `.env` racine (HEMICYCLE_MCP_KEY) et n'est jamais affichée.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from hemicycle_tools import (
    COUTS_CREDITS,
    CompteurConversation,
    ErreurConfiguration,
    ErreurConnexionHemicycle,
    OutilsHemicycle,
    ResultatOutil,
    charger_config_mcp,
    estimer_tokens,
    outil_vers_openai,
)

# Plafond de crédits de ce script : au-delà, les appels payants sont sautés.
BUDGET_MAX_CREDITS = 5
# Exemple d'identifiant donné par le serveur lui-même (description de positions_groupes).
SCRUTIN_PAR_DEFAUT = "VTANR5L17V2152"
RECHERCHE_PAR_DEFAUT = "assurance chômage"


def titre(texte: str) -> None:
    print(f"\n=== {texte} ===")


def courte(description: str | None, longueur: int = 90) -> str:
    texte = " ".join((description or "").split())
    return texte if len(texte) <= longueur else texte[: longueur - 1] + "…"


def taille_tokens(objet: object) -> str:
    texte = objet if isinstance(objet, str) else json.dumps(objet, ensure_ascii=False)
    return f"{len(texte):>6} car. ≈ {estimer_tokens(texte):>5} tokens"


def afficher_resultat(resultat: ResultatOutil, apercu: int = 400) -> None:
    etat = "ERREUR" if resultat.erreur else "OK"
    credits = "?" if resultat.credits_factures is None else resultat.credits_factures
    print(
        f"[{etat}] {resultat.outil} {json.dumps(resultat.arguments, ensure_ascii=False)} : "
        f"{credits} crédit(s) facturé(s), solde {resultat.solde_restant}, {resultat.duree_s} s"
    )
    if resultat.taille_brute:
        print(
            f"  réponse brute : {taille_tokens(resultat.texte_brut)} → renvoyée au modèle : "
            f"{len(resultat.contenu)} car. ({'TRONQUÉE' if resultat.tronque else 'complète'})"
        )
    if resultat.sources:
        print(f"  sources ({len(resultat.sources)}) :")
        for source in resultat.sources[:5]:
            print(f"    - {source['editeur']} | {source['url']} | {source['licence']}")
    elif not resultat.erreur:
        print("  sources : aucune")
    extrait = resultat.contenu if len(resultat.contenu) <= apercu else resultat.contenu[:apercu] + " […]"
    print("  contenu : " + extrait.replace("\n", "\n            "))


def sauver(dossier: Path | None, nom: str, resultat: ResultatOutil) -> None:
    """Enregistre la réponse complète (utile pour régler la troncature hors ligne)."""
    if dossier is None:
        return
    dossier.mkdir(parents=True, exist_ok=True)
    donnees = {
        "outil": resultat.outil,
        "arguments": resultat.arguments,
        "credits_factures": resultat.credits_factures,
        "solde_restant": resultat.solde_restant,
        "texte_brut": resultat.texte_brut,
        "contenu_renvoye": resultat.contenu,
        "tronque": resultat.tronque,
        "sources": resultat.sources,
    }
    (dossier / f"{nom}.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def arreter_si_fatal(resultat: ResultatOutil) -> None:
    if resultat.fatal:
        print(f"\nARRÊT : accès refusé par Hémicycle (HTTP {resultat.statut_refus}). Aucun autre appel.")
        sys.exit(2)


async def principal(options: argparse.Namespace) -> int:
    config = charger_config_mcp()
    if options.max_caracteres:
        from dataclasses import replace

        config = replace(config, max_caracteres_resultat=options.max_caracteres)
    print(f"Serveur : {config.url}")
    print(f"Liste blanche : {', '.join(config.liste_blanche)}")
    print(f"Taille max d'un résultat : {config.max_caracteres_resultat} caractères")

    async with OutilsHemicycle(config) as hemicycle:
        info = hemicycle.info_serveur
        print(f"Connecté : {info.name if info else '?'} (version {info.version if info else '?'})")

        # 1. Liste réelle des outils.
        titre(f"Outils proposés par le serveur ({len(hemicycle.outils_serveur)})")
        for outil in hemicycle.outils_serveur:
            marque = "LB" if outil.name in hemicycle.noms_autorises else "  "
            cout = COUTS_CREDITS.get(outil.name, "?")
            taille = len(json.dumps(outil_vers_openai(outil), ensure_ascii=False))
            print(f"{marque} {outil.name:<27} {cout!s:>3} cr. {taille:>5} car.  {courte(outil.description)}")
        print("(LB = dans la liste blanche ; car. = taille de la définition OpenAI)")
        if hemicycle.outils_absents:
            print(f"ATTENTION, absents du serveur : {', '.join(hemicycle.outils_absents)}")

        # 2. Définitions OpenAI de la liste blanche.
        outils_openai = hemicycle.outils_openai()
        titre("Définitions OpenAI de la liste blanche")
        if not options.sans_json:
            print(json.dumps(outils_openai, ensure_ascii=False, indent=2))
        print(f"\n{len(outils_openai)} outils : {taille_tokens(outils_openai)} (≈ caractères / 4)")
        tous = [outil_vers_openai(outil) for outil in hemicycle.outils_serveur]
        print(f"Pour comparaison, les {len(tous)} outils du serveur : {taille_tokens(tous)}")

        # 3. Appels gratuits.
        titre("Appels gratuits")
        solde_avant = await hemicycle.solde_credits()
        print(f"Solde avant : {solde_avant} crédits")
        compteur = CompteurConversation(max_appels=10)
        resultat = await hemicycle.appeler("guide", {}, compteur)
        afficher_resultat(resultat)
        arreter_si_fatal(resultat)
        sauver(options.sortie, "guide", resultat)

        # tool_call au format renvoyé par le modèle (ici simulé, sans LLM).
        tool_call = {
            "id": "appel_test_1",
            "type": "function",
            "function": {"name": "guide", "arguments": json.dumps({"sujet": "identifiants"})},
        }
        resultat = await hemicycle.executer(tool_call, compteur)
        afficher_resultat(resultat, apercu=200)
        arreter_si_fatal(resultat)
        print(f"  message renvoyé au modèle : clés {sorted(resultat.message_openai())}")

        # 4. Garde-fous, sans coût.
        titre("Garde-fous (aucun crédit)")
        essais = CompteurConversation(max_appels=10)
        cas = [
            ("outil hors liste blanche", "predire_vote", {"amendement": "AMANR5L17PO59048B0390P0D1N000012"}),
            ("JSON invalide", "guide", '{"sujet": '),
            ("sujet inconnu (erreur -32602 du serveur)", "guide", {"sujet": "sujet-inexistant"}),
        ]
        for libelle, nom, arguments in cas:
            resultat = await hemicycle.appeler(nom, arguments, essais)
            arreter_si_fatal(resultat)
            print(f"- {libelle} → erreur={resultat.erreur} : {courte(resultat.contenu, 160)}")
        limite = CompteurConversation(max_appels=0)
        resultat = await hemicycle.appeler("guide", {}, limite)
        print(f"- limite d'appels atteinte → erreur={resultat.erreur} : {courte(resultat.contenu, 160)}")

        # 5. Appels payants (seulement avec --payant).
        if options.payant:
            titre(f"Appels payants (plafond : {BUDGET_MAX_CREDITS} crédits)")
            payants = [
                ("resultat_scrutin", {"id": options.scrutin}),
                ("rechercher", {"q": options.recherche, "limit": 3}),
            ]
            for nom, arguments in payants:
                cout = COUTS_CREDITS.get(nom, BUDGET_MAX_CREDITS)
                if compteur.credits_factures + cout > BUDGET_MAX_CREDITS:
                    print(f"{nom} sauté : le plafond de {BUDGET_MAX_CREDITS} crédits serait dépassé.")
                    continue
                resultat = await hemicycle.appeler(nom, arguments, compteur)
                afficher_resultat(resultat, apercu=1200)
                arreter_si_fatal(resultat)
                sauver(options.sortie, nom, resultat)
        else:
            print("\n(Appels payants non lancés : ajouter --payant, ≈ 3 crédits.)")

        # 6. Bilan.
        titre("Bilan")
        solde_apres = await hemicycle.solde_credits()
        print(f"Solde après : {solde_apres} crédits")
        if isinstance(solde_avant, int) and isinstance(solde_apres, int):
            print(f"Crédits consommés d'après le solde : {solde_avant - solde_apres}")
        print(f"Compteur : {json.dumps(compteur.resume(), ensure_ascii=False)}")
        for ligne in compteur.journal:
            print(f"  {json.dumps(ligne, ensure_ascii=False)}")
    return 0


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Test de connexion au MCP Hémicycle (sans LLM).")
    analyseur.add_argument("--payant", action="store_true", help="lancer 2 appels payants (≈ 3 crédits)")
    analyseur.add_argument("--scrutin", default=SCRUTIN_PAR_DEFAUT, help="identifiant pour resultat_scrutin")
    analyseur.add_argument("--recherche", default=RECHERCHE_PAR_DEFAUT, help="requête pour rechercher")
    analyseur.add_argument("--max-caracteres", type=int, help="taille max d'un résultat renvoyé au modèle")
    analyseur.add_argument("--sans-json", action="store_true", help="ne pas afficher le JSON OpenAI complet")
    analyseur.add_argument("--sortie", type=Path, help="dossier où enregistrer les réponses complètes")
    options = analyseur.parse_args()
    try:
        return asyncio.run(principal(options))
    except ErreurConfiguration as erreur:
        print(f"Configuration : {erreur}", file=sys.stderr)
        return 1
    except ErreurConnexionHemicycle as erreur:
        print(f"Connexion : {erreur}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
