"""Tests hors ligne du serveur (sans réseau, sans LLM, sans crédit Hémicycle).

Couvre : questions sur un député (chercher_depute, lire_acteur, recherche automatique, sources)
et le flux de progression de POST /chat/flux.

Lancement (depuis backend/chatbot/) ::

    .venv/bin/python -m unittest test_serveur -v
"""

from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from typing import Any

from starlette.testclient import TestClient

import serveur
from featherless_client import ReponseChat
from hemicycle_tools import CompteurConversation, ResultatOutil, compacter_acteur
from outils_rapport import OutilsRapport
from veille import (
    PAR_NOM,
    PRESELECTIONS,
    SELECTION_DEFAUT,
    SPECS_JEUX,
    ErreurArgumentsVeille,
    appel_interroger,
    attribuer_lignes,
    definition,
    nom_de_famille,
    nomme_le_depute,
    source_depute,
)

AUJOURD_HUI = date(2026, 11, 14)


def noms_appels(question: str, selection=SELECTION_DEFAUT) -> list[tuple[str, dict]]:
    return [(a.function.name, json.loads(a.function.arguments))
            for a in serveur.appels_recherche_automatique(question, selection)]


class TestRechercheAutomatique(unittest.TestCase):
    def test_personne_nommee(self):
        self.assertEqual(noms_appels("Quel est le groupe de Didier Lemaire ?"), [("chercher_depute", {"nom": "Lemaire"})])
        self.assertEqual(noms_appels("Que fait Charles de Courson ?"), [("chercher_depute", {"nom": "Courson"})])
        self.assertEqual(noms_appels("Selon Didier Lemaire, quoi ?"), [("chercher_depute", {"nom": "Lemaire"})])

    def test_vote_d_un_depute_sur_un_scrutin(self):
        self.assertEqual(
            noms_appels("Comment a voté Marine Le Pen sur le scrutin n° 1234 ?"),
            [("chercher_depute", {"nom": "Pen"}), ("resultat_scrutin", {"id": "VTANR5L17V1234"})],
        )

    def test_pas_une_personne(self):
        for question in ("Où en est la Loi Duplomb ?", "La France insoumise a voté contre ?",
                         "Quoi de neuf à l'Assemblée cette semaine ?", "Le Rassemblement National a voté ?"):
            self.assertIsNone(serveur.personne_citee(question), question)

    def test_scrutin_numerote(self):
        self.assertEqual(noms_appels("Comment a voté le groupe RN sur le scrutin 4567 ?"),
                         [("resultat_scrutin", {"id": "VTANR5L17V4567"})])
        self.assertEqual(noms_appels("Que dit le scrutin n° 4567 ?"), [("lire_scrutin", {"id": "VTANR5L17V4567"})])

    def test_selection_sans_chercher_depute(self):
        # Le journaliste n'a pas choisi chercher_depute : recherche plein texte classique.
        appels = noms_appels("Quel est le groupe de Didier Lemaire ?", ["rechercher", "derniers_scrutins"])
        self.assertEqual([nom for nom, _ in appels], ["rechercher", "derniers_scrutins"])

    def test_actualite_generale(self):
        self.assertEqual([nom for nom, _ in noms_appels("Quoi de neuf cette semaine ?")],
                         ["derniers_scrutins", "agenda_seances"])


class TestChercherDepute(unittest.TestCase):
    spec = SPECS_JEUX["chercher_depute"]

    def test_nom_de_famille(self):
        self.assertEqual(nom_de_famille("Didier Lemaire"), "Lemaire")
        self.assertEqual(nom_de_famille("Lemaire"), "Lemaire")
        self.assertEqual(nom_de_famille("Mme Marine Le Pen"), "Pen")
        self.assertEqual(nom_de_famille("Le Pen"), "Pen")
        self.assertEqual(nom_de_famille("Charles de Courson"), "Courson")
        self.assertEqual(nom_de_famille("Nicolas Dupont-Aignan"), "Dupont-Aignan")

    def test_deputes_en_exercice_par_defaut(self):
        appel, contexte = appel_interroger(self.spec, {"nom": "Didier Lemaire", "groupe": "EPR"}, AUJOURD_HUI)
        self.assertEqual(appel["jeu"], "deputes_en_exercice")
        self.assertIn({"colonne": "nom", "op": "like", "valeur": "Lemaire"}, appel["filtres"])
        self.assertIn({"colonne": "groupe_sigle", "op": "eq", "valeur": "EPR"}, appel["filtres"])
        self.assertIn("groupe_sigle", appel["colonnes"])
        self.assertEqual(contexte["jeu"], "deputes_en_exercice")

    def test_anciens_deputes(self):
        appel, contexte = appel_interroger(self.spec, {"nom": "Lemaire", "prenom": "Didier", "anciens": True},
                                           AUJOURD_HUI)
        self.assertEqual(appel["jeu"], "deputes")
        self.assertNotIn("groupe_sigle", appel["colonnes"])  # colonne absente du jeu `deputes`
        self.assertIn({"colonne": "prenom", "op": "like", "valeur": "Didier"}, appel["filtres"])
        self.assertEqual(contexte["jeu"], "deputes")
        appel, _ = appel_interroger(self.spec, {"nom": "Lemaire", "anciens": False}, AUJOURD_HUI)
        self.assertEqual(appel["jeu"], "deputes_en_exercice")

    def test_refus(self):
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(self.spec, {"nom": "Lemaire", "anciens": True, "groupe": "RN"}, AUJOURD_HUI)
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(self.spec, {}, AUJOURD_HUI)  # nom obligatoire
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(self.spec, {"nom": "Lemaire", "jeu": "orcet_predictions"}, AUJOURD_HUI)

    def test_garde_fou_et_selection(self):
        self.assertTrue({"deputes", "deputes_en_exercice"} <= serveur.JEUX_AUTORISES)
        self.assertEqual({jeu for jeu in serveur.JEUX_AUTORISES if "orcet" in jeu}, {"orcet_previsions_votes"})
        self.assertIn("chercher_depute", SELECTION_DEFAUT)
        self.assertIn("lire_acteur", SELECTION_DEFAUT)
        for preselection in PRESELECTIONS:
            self.assertEqual(len(preselection["outils"]), len(set(preselection["outils"])), preselection["id"])
        schema = definition(PAR_NOM["chercher_depute"], {}, {})["function"]["parameters"]
        self.assertEqual(schema["properties"]["anciens"]["type"], "boolean")
        self.assertEqual(schema["required"], ["nom"])


MANDATS = (
    [{"organe": "PO873643", "nature": "MINISTERE", "qualite": "en mission", "debut": "2026-08-12", "fin": "2026-09-28",
      "legislature": "17"},
     {"organe": "PO59046", "nature": "COMPER", "qualite": "Membre", "debut": "2026-03-31", "fin": None,
      "legislature": "17"},
     {"organe": "PO854268", "nature": "GE", "qualite": "Vice-Président", "debut": "2025-03-05", "fin": None,
      "legislature": "17"},
     {"organe": "PO854268", "nature": "GE", "qualite": "Membre", "debut": "2025-01-13", "fin": None,
      "legislature": "17"}]
    + [{"organe": f"PO8515{i:02d}", "nature": "GA", "qualite": "Membre", "debut": "2025-07-10", "fin": None,
        "legislature": "17"} for i in range(20)]
)
FICHE = {"id": "PA794838", "type": "acteur", "civilite": "M.", "prenom": "Didier", "nom": "Lemaire",
         "source": {"editeur": "Assemblée nationale", "url": "https://www.assemblee-nationale.fr/dyn/deputes/PA794838",
                    "licence": "Licence Ouverte 2.0"},
         "mandats": MANDATS}


class TestCompacterActeur(unittest.TestCase):
    def test_compaction(self):
        compact = compacter_acteur(FICHE, "2026-11-14")
        self.assertEqual(compact["nom"], "Lemaire")
        self.assertNotIn("mandats", compact)
        self.assertEqual(compact["groupes_amitie_en_cours"], 20)
        self.assertEqual(compact["groupes_etudes_en_cours"], 1)
        en_cours = compact["mandats_en_cours"]
        self.assertEqual([m["type"] for m in en_cours], ["commission permanente", "groupe d'études"])
        self.assertEqual(en_cours[1]["qualite"], "Vice-Président")
        self.assertEqual(compact["mandats_termines_recents"][0]["type"], "ministère")
        self.assertIn("chercher_depute", compact["remarque"])  # groupe politique absent
        self.assertLess(len(json.dumps(compact, ensure_ascii=False)), len(json.dumps(FICHE, ensure_ascii=False)) / 2)

    def test_groupe_present_et_champs_inattendus(self):
        fiche = dict(FICHE, mandats=[{"organe": "PO845401", "nature": "GP", "qualite": "Membre", "debut": "2024-07-18",
                                      "fin": None, "legislature": "17"},
                                     {"organe": "PO838901", "nature": "ASSEMBLEE", "qualite": "membre",
                                      "debut": "2024-07-07", "fin": None, "legislature": "17",
                                      "circonscription": "Moselle (9e)"}])
        compact = compacter_acteur(fiche, "2026-11-14")
        self.assertEqual([m["type"] for m in compact["mandats_en_cours"]], ["groupe politique", "mandat de député"])
        self.assertEqual(compact["mandats_en_cours"][1]["circonscription"], "Moselle (9e)")
        self.assertNotIn("chercher_depute", compact["remarque"])

    def test_format_inattendu(self):
        for donnees in ({"id": "PA1"}, {"mandats": "?"}, {"mandats": [{"organe": "PO1"}]}, ["x"]):
            self.assertIs(compacter_acteur(donnees), donnees)


class TestSourcesDepute(unittest.TestCase):
    def test_source_et_citation(self):
        source = source_depute("PA794838", "M.", "Didier", "Lemaire", "EPR")
        self.assertEqual(source["libelle"], "M. Didier Lemaire (EPR)")
        self.assertTrue(nomme_le_depute(source, "Didier LEMAIRE siège au groupe EPR."))
        self.assertFalse(nomme_le_depute(source, "M. Lemaire-Dupont"))
        self.assertTrue(serveur.est_citee(source, "- Didier Lemaire est membre du groupe EPR (fiche du député)."))
        self.assertFalse(serveur.est_citee(source, "- Le scrutin n° 1234 a été adopté."))

    def test_fiche_lire_acteur(self):
        source = serveur.enrichir_source({"type": "hemicycle", "outil": "lire_acteur", "editeur": "Assemblée nationale",
                                          "url": "https://www.assemblee-nationale.fr/dyn/deputes/PA794838"})
        self.assertEqual((source["ref"], source["nature"]), ("PA794838", "depute"))
        resultat = ResultatOutil(outil="lire_acteur", contenu="{}", texte_brut=json.dumps(FICHE), sources=[source])
        serveur.completer_source_acteur(resultat)
        self.assertEqual(resultat.sources[0]["nom"], "Lemaire")
        self.assertEqual(resultat.sources[0]["libelle"], "Fiche de M. Didier Lemaire")

    def test_attribution_des_lignes(self):
        sources = [source_depute("PA794838", "M.", "Didier", "Lemaire", "EPR")]
        lignes = attribuer_lignes("- Didier Lemaire est membre du groupe EPR.\n- Autre fait.", [(0, "{}", sources)])
        self.assertEqual([l["appels"] for l in lignes], [[0], []])

    def test_page_publique_du_scrutin(self):
        source = serveur.enrichir_source({"type": "hemicycle", "outil": "resultat_scrutin",
                                          "url": "https://www.assemblee-nationale.fr/dyn/17/scrutins/9895"})
        self.assertEqual((source["ref"], source["numero"], source["libelle"]),
                         ("VTANR5L17V9895", 9895, "Scrutin n° 9895"))
        self.assertEqual(source["url"], "https://www.assemblee-nationale.fr/dyn/17/scrutins/9895")

    def test_vote_d_un_depute_rattache_aux_deux_appels(self):
        appels = [(0, '{"resultats":[{"id":"PA1"}]}', [source_depute("PA1", "M.", "Frédéric", "Valletoux")]),
                  (1, '{"numero":9895,"votes_par_groupe":{"HOR":{"pour":["Frédéric Valletoux"]}}}', [])]
        lignes = attribuer_lignes("Frédéric Valletoux a voté pour (scrutin n° 9895).", appels)
        self.assertEqual(lignes[0]["appels"], [0, 1])

    def test_attribution_fiche_et_dates_en_lettres(self):
        fiche = {**source_depute("PA794838", "M.", "Didier", "Lemaire"), "outil": "lire_acteur"}
        contenu = json.dumps(compacter_acteur(FICHE, "2026-11-14"))
        texte = ("Ses mandats en cours (fiche du député, non vérifiée par la rédaction) :\n"
                 "- Membre d'une commission permanente (depuis le 31 mars 2026) ;\n"
                 "- Vice-président d'un groupe d'études (depuis le 5 mars 2025).\n"
                 "- Rien le 1er janvier 2020.")
        lignes = attribuer_lignes(texte, [(1, contenu, [fiche]), (0, "{}", [source_depute("PA1", nom="Autre")])])
        self.assertEqual([l["appels"] for l in lignes], [[1], [1], [1], []])


DEFINITIONS = {nom: definition(PAR_NOM[nom], serveur.OUTILS_LOCAUX, {
    "lire_acteur": {"parameters": {"type": "object", "properties": {"id": {"type": "string"}}}},
    "rechercher": {"parameters": {"type": "object", "properties": {"q": {"type": "string"}, "limit": {}}}},
}) for nom in ("chercher_depute", "lire_acteur", "rechercher", "derniers_scrutins")}


class TestApercuRequete(unittest.TestCase):
    definitions = list(DEFINITIONS.values())

    def test_endpoints(self):
        requete = serveur.apercu_requete("chercher_depute", '{"nom": "Didier Lemaire"}', self.definitions)
        self.assertEqual(requete["court"], "POST /v1/jeux/interroger · deputes_en_exercice")
        self.assertEqual(requete["corps"]["filtres"], [{"colonne": "nom", "op": "like", "valeur": "Lemaire"}])
        self.assertEqual(serveur.apercu_requete("lire_acteur", {"id": "PA794838"}, self.definitions)["texte"],
                         "GET /v1/acteurs/PA794838")
        # Argument par défaut ajouté comme à l'exécution ; nom de paramètre approximatif corrigé.
        self.assertEqual(serveur.apercu_requete("rechercher", '{"recherche": "forêt"}', self.definitions)["texte"],
                         "GET /v1/recherche?limit=5&q=forêt")
        self.assertEqual(serveur.apercu_requete("derniers_scrutins", "{}", self.definitions)["court"],
                         "POST /v1/jeux/interroger · scrutins")

    def test_incalculable(self):
        self.assertIsNone(serveur.apercu_requete("chercher_depute", "{}", self.definitions))  # nom manquant
        self.assertIsNone(serveur.apercu_requete("chercher_depute", "{pas du json", self.definitions))
        self.assertIsNone(serveur.apercu_requete("predire_vote", '{"amendement": "x"}', self.definitions))


class TestPromptLecteur(unittest.TestCase):
    def test_methode_depute(self):
        prompt = serveur.prompt_lecteur(OutilsRapport("demo"), AUJOURD_HUI, 5)
        self.assertNotIn("ne permettent pas de retrouver un député", prompt)
        self.assertIn("chercher_depute", prompt)
        self.assertIn("lire_acteur", prompt)
        self.assertIn("resultat_scrutin", prompt)


# --------------------------------------------------------------------------
# repondre() de bout en bout, avec un faux modèle et un faux Hémicycle
# --------------------------------------------------------------------------

LIGNES_DEPUTES = {
    "jeu": "deputes_en_exercice",
    "source": {"nom": "Assemblée nationale", "url": "https://data.assemblee-nationale.fr",
               "licence": "Licence Ouverte (Etalab)"},
    "lignes": [{"uid": "PA794838", "civ": "M.", "prenom": "Didier", "nom": "Lemaire",
                "groupe_politique": "Ensemble pour la République", "groupe_sigle": "EPR", "profession": "Employé"}],
}


def reponse_modele(texte: str = "", appels: list[Any] | None = None) -> ReponseChat:
    return ReponseChat(texte=texte, reflexion=None, appels_outils=appels or [], raison_fin="stop", usage=None,
                       duree_s=0.1, message=None)


class FauxModele:
    modele = "faux-modele"
    config = SimpleNamespace(cle_api="cle-factice")
    nb_requetes = 0

    def __init__(self, reponses: list[ReponseChat]) -> None:
        self.reponses = list(reponses)

    async def discuter(self, messages, **options) -> ReponseChat:
        return self.reponses.pop(0)


class FauxHemicycle:
    config = SimpleNamespace(cle_api="autre-cle", max_caracteres_resultat=6000)

    def __init__(self) -> None:
        self.appels: list[tuple[str, dict]] = []

    def nouveau_compteur(self) -> CompteurConversation:
        return CompteurConversation(max_appels=5)

    async def appeler(self, nom, arguments, compteur, *, tool_call_id=None) -> ResultatOutil:
        self.appels.append((nom, arguments))
        compteur.nb_demandes += 1
        compteur.credits_factures += 1
        texte = json.dumps(LIGNES_DEPUTES, ensure_ascii=False)
        return ResultatOutil(outil=nom, contenu=texte, texte_brut=texte, credits_factures=1, tool_call_id=tool_call_id)


def faux_etat(reponses: list[ReponseChat]) -> serveur.EtatServeur:
    parametres = serveur.Parametres(
        port=0, reflexion=False, reflexion_premier_tour=False, max_tokens=900, temperature=0.3,
        max_credits_question=10, max_credits_plafond=30, max_appels_plafond=8, max_credits_serveur=300,
        cache_s=0, concurrence_llm=1, trace=None,
    )
    return serveur.EtatServeur(
        parametres=parametres, llm=FauxModele(reponses), hemicycle=FauxHemicycle(),
        outils=[DEFINITIONS["chercher_depute"]], verrou_llm=asyncio.Semaphore(1),
        definitions={"chercher_depute": DEFINITIONS["chercher_depute"]},
    )


def appel_outil(nom: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(id="appel_1", type="function",
                           function=SimpleNamespace(name=nom, arguments=json.dumps(arguments)))


class TestRepondreAvecSignaler(unittest.TestCase):
    def test_evenements(self):
        etat = faux_etat([
            reponse_modele(appels=[appel_outil("chercher_depute", {"nom": "Didier Lemaire"})]),
            reponse_modele("- Didier Lemaire siège au groupe EPR (fiche du député)."),
        ])
        evenements: list[dict] = []

        async def signaler(evenement: dict) -> None:
            evenements.append(evenement)

        corps = asyncio.run(serveur.repondre(etat, "Quel est le groupe de Didier Lemaire ?", [],
                                             outils=["chercher_depute"], signaler=signaler))
        codes = [e.get("code") or e["type"] for e in evenements]
        self.assertEqual(codes, ["analyse", "hemicycle", "appel", "redaction", "verification"])
        hemicycle = evenements[1]
        self.assertEqual(hemicycle["message"], "Recherche dans Hémicycle : Chercher un député…")
        self.assertEqual(hemicycle["outil"], "chercher_depute")
        self.assertEqual(hemicycle["requete"]["court"], "POST /v1/jeux/interroger · deputes_en_exercice")
        self.assertEqual(evenements[2], {"type": "appel", "appel": corps["outils_utilises"][0], "indice": 0})
        temps = [e["t"] for e in evenements if e["type"] == "etape"]
        self.assertEqual(temps, sorted(temps))
        # Réponse sourcée : la fiche du député est citée et la ligne rattachée à l'appel.
        self.assertIsNone(corps["meta"]["garde_fou"])
        self.assertEqual([s["ref"] for s in corps["sources"] if s.get("citee")], ["PA794838"])
        self.assertEqual(corps["lignes"][0]["appels"], [0])
        self.assertEqual(etat.hemicycle.appels[0][1]["jeu"], "deputes_en_exercice")

    def test_sans_signaler_meme_reponse(self):
        def lancer(signaler):
            etat = faux_etat([
                reponse_modele(appels=[appel_outil("chercher_depute", {"nom": "Lemaire"})]),
                reponse_modele("- Didier Lemaire siège au groupe EPR."),
            ])
            corps = asyncio.run(serveur.repondre(etat, "Groupe de Lemaire ?", [], outils=["chercher_depute"],
                                                 signaler=signaler))
            corps["meta"].pop("duree_s")
            for appel in corps["outils_utilises"]:
                appel.pop("duree_s")
            return corps

        async def ignorer(_evenement):
            return None

        self.assertEqual(lancer(None), lancer(ignorer))

    def test_recherche_automatique_et_mode_lecteur(self):
        etat = faux_etat([
            reponse_modele("Je ne sais pas."),  # aucun outil : le serveur cherche lui-même
            reponse_modele("Didier Lemaire siège au groupe EPR (fiche du député, non vérifiée par la rédaction)."),
        ])
        etat.definitions = {nom: DEFINITIONS["chercher_depute"] if nom == "chercher_depute" else {"function": {
            "name": nom, "parameters": {"type": "object", "properties": {}}}} for nom in SELECTION_DEFAUT}
        evenements: list[dict] = []

        async def signaler(evenement: dict) -> None:
            evenements.append(evenement)

        corps = asyncio.run(serveur.repondre(etat, "Quel est le groupe de Didier Lemaire ?", [], mois="demo",
                                             signaler=signaler))
        codes = [e.get("code") or e["type"] for e in evenements]
        self.assertEqual(codes, ["rapport", "analyse", "recherche_auto", "hemicycle", "appel", "redaction",
                                 "verification"])
        self.assertEqual(corps["outils_utilises"][0]["lance_par"], "serveur")
        self.assertEqual(corps["meta"]["mode"], "lecteur")


# --------------------------------------------------------------------------
# Routes POST /chat/flux et POST /chat (repondre remplacé par un faux)
# --------------------------------------------------------------------------


class TestRouteFlux(unittest.TestCase):
    def setUp(self):
        self.repondre = serveur.repondre
        serveur.app.state.etat = SimpleNamespace(masquer=lambda texte: texte)
        self.client = TestClient(serveur.app)  # sans `with` : pas de lifespan, donc ni Featherless ni MCP

    def tearDown(self):
        serveur.repondre = self.repondre

    def lignes(self, corps: dict) -> tuple[Any, list[dict]]:
        reponse = self.client.post("/chat/flux", json=corps)
        return reponse, [json.loads(ligne) for ligne in reponse.text.splitlines()]

    def test_contrat(self):
        async def faux_repondre(etat, question, historique, reflexion=None, mois=None, outils=None, budget=None,
                                max_appels=None, signaler=None):
            await signaler({"type": "etape", "code": "analyse", "message": "Analyse de la question…", "t": 0.0})
            await signaler({"type": "appel", "appel": {"outil": "chercher_depute"}, "indice": 0})
            return {"reponse": f"Réponse à : {question}\nsur deux lignes", "mois": mois}

        serveur.repondre = faux_repondre
        reponse, evenements = self.lignes({"question": "  Groupe de Lemaire ? ", "mois": "demo"})
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.headers["content-type"].startswith("application/x-ndjson"))
        self.assertEqual(reponse.headers["cache-control"], "no-store")
        self.assertEqual(reponse.headers["x-accel-buffering"], "no")
        self.assertEqual([e["type"] for e in evenements], ["etape", "appel", "reponse"])
        self.assertEqual(evenements[-1]["donnees"],
                         {"reponse": "Réponse à : Groupe de Lemaire ?\nsur deux lignes", "mois": "demo"})

    def test_erreurs_identiques_a_chat(self):
        cas = [
            (serveur.SelectionInvalide("Choisissez au moins un endpoint Hémicycle."), 400),
            (serveur.RapportIntrouvable("Numéro introuvable : 2020-01."), 404),
            (serveur.ConcurrenceDepassee("429"), 503),
        ]
        for exception, statut in cas:
            async def faux_repondre(*_args, exception=exception, **_kwargs):
                raise exception

            serveur.repondre = faux_repondre
            _, evenements = self.lignes({"question": "x"})
            chat = self.client.post("/chat", json={"question": "x"})
            self.assertEqual(chat.status_code, statut)
            self.assertEqual(evenements, [{"type": "erreur", "statut": statut, "detail": chat.json()["detail"]}])

    def test_erreur_inattendue(self):
        async def faux_repondre(*_args, **_kwargs):
            raise RuntimeError("boum")

        serveur.repondre = faux_repondre
        with self.assertLogs("outil_redaction", level="ERROR"):
            _, evenements = self.lignes({"question": "x"})
        self.assertEqual(evenements, [{"type": "erreur", "statut": 500, "detail": "Erreur interne du serveur."}])


if __name__ == "__main__":
    unittest.main()
