"""Tests hors ligne du catalogue de la veille (veille.py) : aucun appel réseau, aucun crédit.

    .venv/bin/python test_veille_catalogue.py
"""

from __future__ import annotations

import json
import unittest
from datetime import date

import veille
from veille import (
    CATEGORIES,
    ENDPOINTS,
    PAR_NOM,
    PRESELECTIONS,
    SELECTION_DEFAUT,
    SPECS_JEUX,
    ErreurArgumentsVeille,
    appel_interroger,
    attribuer_lignes,
    compacter_jeu,
    remplacer_jours,
    requete_rest,
)

AUJOURD_HUI = date(2026, 11, 14)  # un samedi : semaine du 09/11 au 15/11


class Catalogue(unittest.TestCase):
    def test_noms_uniques_et_categories_connues(self):
        noms = [e.nom for e in ENDPOINTS]
        self.assertEqual(len(noms), len(set(noms)))
        categories = {c["id"] for c in CATEGORIES}
        for e in ENDPOINTS:
            self.assertIn(e.categorie, categories, e.nom)
            self.assertIn(e.type, ("mcp", "local", "jeu"), e.nom)
            self.assertGreaterEqual(e.cout, 0)

    def test_specs_et_endpoints_jeu_coincident(self):
        self.assertEqual({e.nom for e in ENDPOINTS if e.type == "jeu"}, set(SPECS_JEUX))

    def test_selections_referencent_des_endpoints(self):
        for nom in SELECTION_DEFAUT:
            self.assertIn(nom, PAR_NOM)
        for preselection in PRESELECTIONS:
            for nom in preselection["outils"]:
                self.assertIn(nom, PAR_NOM, preselection["id"])

    def test_orcet_limite_et_opt_in(self):
        """Seul jeu Orcet : orcet_previsions_votes, par previsions_orcet (3 prévisions au plus) ; hors sélection par défaut."""
        jeux_orcet = {jeu for spec in SPECS_JEUX.values() for jeu in spec.jeux if jeu.startswith("orcet")}
        self.assertEqual(jeux_orcet, {"orcet_previsions_votes"})
        self.assertLessEqual(SPECS_JEUX["previsions_orcet"].limite_max, 3)
        self.assertNotIn("interroger", PAR_NOM)
        for nom in ("previsions_orcet", "predire_vote"):
            self.assertTrue(PAR_NOM[nom].opt_in, nom)
            self.assertNotIn(nom, SELECTION_DEFAUT)
        self.assertEqual({e.nom for e in ENDPOINTS if e.opt_in}, {"previsions_orcet", "predire_vote"})

    def test_cout_orcet_selon_limite(self):
        self.assertEqual(veille.cout_appel("previsions_orcet", {}), 25)
        self.assertEqual(veille.cout_appel("previsions_orcet", {"limite": 2}), 50)
        self.assertEqual(veille.cout_appel("previsions_orcet", {"limite": 99}), 75)
        self.assertEqual(veille.cout_appel("predire_vote", {"amendement": "AMANR5…"}), 50)
        self.assertEqual(veille.cout_appel("derniers_scrutins", {}), 1)

    def test_exemples_valides(self):
        """Chaque exemple d'endpoint « jeu » produit un appel `interroger` sans erreur."""
        for nom, spec in SPECS_JEUX.items():
            exemple = remplacer_jours(PAR_NOM[nom].exemple, AUJOURD_HUI)
            appel, contexte = appel_interroger(spec, exemple, AUJOURD_HUI)
            self.assertEqual(appel["jeu"], spec.jeu)
            self.assertLessEqual(appel["limite"], 200)
            self.assertIn("limite", contexte)


class RequeteRest(unittest.TestCase):
    def test_get_avec_identifiant(self):
        r = requete_rest("lire_scrutin", {"id": "VTANR5L17V9880"})
        self.assertEqual(r["texte"], "GET /v1/scrutins/VTANR5L17V9880")
        self.assertEqual(r["arguments"], {"id": "VTANR5L17V9880"})
        self.assertIsNone(r["corps"])

    def test_get_avec_query_lisible(self):
        r = requete_rest("rechercher", {"q": "feux de forêt", "types": "dossier,texte", "limit": 5})
        self.assertEqual(r["texte"], "GET /v1/recherche?q=feux de forêt&types=dossier,texte&limit=5")
        self.assertEqual(r["court"], "GET /v1/recherche")

    def test_post_interroger(self):
        r = requete_rest("interroger", {"jeu": "scrutins", "limite": 3})
        self.assertEqual(r["texte"], "POST /v1/jeux/interroger")
        self.assertEqual(r["court"], "POST /v1/jeux/interroger · scrutins")
        self.assertEqual(r["corps"], {"jeu": "scrutins", "limite": 3})

    def test_outil_inconnu(self):
        self.assertEqual(requete_rest("guide", {})["methode"], "MCP")


class ArgumentsJeu(unittest.TestCase):
    def test_parametre_inconnu(self):
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(SPECS_JEUX["chercher_depute"], {"prenom": "Didier"}, AUJOURD_HUI)

    def test_obligatoire_et_longueur_like(self):
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(SPECS_JEUX["chercher_depute"], {}, AUJOURD_HUI)
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(SPECS_JEUX["chercher_depute"], {"nom": "Le"}, AUJOURD_HUI)

    def test_periode_et_limite(self):
        appel, contexte = appel_interroger(
            SPECS_JEUX["amendements_deposes"], {"depuis": "2026-11-01", "jusqu_a": "2026-11-10", "limite": 99}, AUJOURD_HUI
        )
        self.assertEqual(contexte["limite"], 20)  # plafonnée à limite_max
        filtres = {(f["colonne"], f["op"]): f["valeur"] for f in appel["filtres"]}
        self.assertEqual(filtres[("date_depot", "gte")], "2026-11-01")
        self.assertEqual(filtres[("date_depot", "lt")], "2026-11-11")
        self.assertEqual(filtres[("legislature", "eq")], 17)

    def test_dates_inversees(self):
        with self.assertRaises(ErreurArgumentsVeille):
            appel_interroger(SPECS_JEUX["senat_derniers_scrutins"], {"depuis": "2026-11-10", "jusqu_a": "2026-11-01"}, AUJOURD_HUI)

    def test_agenda_senat_semaine_par_defaut_et_seances(self):
        appel, contexte = appel_interroger(SPECS_JEUX["senat_agenda"], {}, AUJOURD_HUI)
        self.assertEqual((contexte["depuis"], contexte["jusqu_a"]), (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertIn({"colonne": "type_reunion", "op": "eq", "valeur": "seance"}, appel["filtres"])
        appel, _ = appel_interroger(SPECS_JEUX["senat_agenda"], {"commissions": True}, AUJOURD_HUI)
        self.assertNotIn({"colonne": "type_reunion", "op": "eq", "valeur": "seance"}, appel["filtres"])

    def test_orcet_a_venir_ou_passees(self):
        spec = SPECS_JEUX["previsions_orcet"]
        appel, contexte = appel_interroger(spec, {"texte": "finances"}, AUJOURD_HUI)
        self.assertEqual(appel["jeu"], "orcet_previsions_votes")
        self.assertEqual((appel["tri"], appel["ordre"], appel["limite"]), ("date_prevue", "asc", 1))
        self.assertIn({"colonne": "date_prevue", "op": "gte", "valeur": "2026-11-14"}, appel["filtres"])
        self.assertIn({"colonne": "texte_titre", "op": "like", "valeur": "finances"}, appel["filtres"])
        appel, _ = appel_interroger(spec, {"passees": True, "limite": 2}, AUJOURD_HUI)
        self.assertEqual((appel["ordre"], appel["limite"]), ("desc", 2))
        self.assertIn({"colonne": "date_prevue", "op": "lt", "valeur": "2026-11-14"}, appel["filtres"])
        self.assertFalse(any(f["op"] == "gte" for f in appel["filtres"]))

    def test_nature_des_documents(self):
        appel, _ = appel_interroger(SPECS_JEUX["textes_deposes"], {"nature": "proposition de loi"}, AUJOURD_HUI)
        self.assertIn({"colonne": "type_libelle", "op": "like", "valeur": "Proposition de loi"}, appel["filtres"])


class Compaction(unittest.TestCase):
    SOURCE_AN = {"nom": "Assemblée nationale", "url": "https://data.assemblee-nationale.fr", "licence": "Licence Ouverte (Etalab)"}

    def test_textes_deposes(self):
        donnees = {"source": self.SOURCE_AN, "lignes": [
            {"uid": "PIONANR5L17B3442", "dossier_ref": "DLR5L17N51518", "titre_principal": "proposition de loi visant à X",
             "date_depot": "2026-11-05T00:00:00.000+01:00", "type_libelle": "Proposition de loi"},
        ]}
        contenu, sources = compacter_jeu(SPECS_JEUX["textes_deposes"], donnees, {"limite": 10})
        self.assertEqual(contenu["resultats"][0]["date_depot"], "05/11/2026")
        self.assertEqual(contenu["resultats"][0]["id"], "PIONANR5L17B3442")
        self.assertTrue(sources[0]["url"].endswith("/PIONANR5L17B3442.json"))

    def test_agenda_senat_filtre_en_heure_de_paris(self):
        donnees = {"source": {"nom": "Sénat"}, "lignes": [
            {"debut": "2026-11-08T23:00:00+00:00", "titre": "lundi 9 à Paris"},
            {"debut": "2026-11-15T23:00:00+00:00", "titre": "lundi 16 à Paris (hors période)"},
        ]}
        contenu, _ = compacter_jeu(SPECS_JEUX["senat_agenda"], donnees,
                                   {"limite": 20, "depuis": date(2026, 11, 9), "jusqu_a": date(2026, 11, 15)})
        self.assertEqual([r["titre"] for r in contenu["resultats"]], ["lundi 9 à Paris"])
        self.assertEqual(contenu["resultats"][0]["jour"], "09/11/2026")

    def test_fil_evenements_regroupe(self):
        lignes = [
            {"event_type": "acte", "event_date": "2026-11-14", "titre": "PLF 2027", "sous_titre": "Discussion en séance publique"},
            {"event_type": "acte", "event_date": "2026-11-14", "titre": "PLF 2027", "sous_titre": "Discussion en séance publique"},
            {"event_type": "amendements", "event_date": "2026-11-12", "texte_uid": "PRJLANR5L17BTC3188", "sous_titre": "SOC", "nb": 4},
            {"event_type": "amendements", "event_date": "2026-11-12", "texte_uid": "PRJLANR5L17BTC3188", "sous_titre": "RN", "nb": 2},
            {"event_type": "scrutin", "event_date": "2026-11-12", "titre": "l'ensemble du projet de loi X",
             "sous_titre": "scrutin public solennel", "statut": "L'Assemblée nationale n'a pas adopté",
             "payload": {"uid": "VTANR5L17V9895", "numero": "9895", "nb_pour": "49", "nb_contre": "63", "nb_abstentions": "76"}},
        ]
        contenu, sources = compacter_jeu(SPECS_JEUX["fil_evenements"], {"source": {"nom": "Hémicycle"}, "lignes": lignes}, {"limite": 15})
        types = [r["type"] for r in contenu["resultats"]]
        self.assertEqual(types, ["etape", "scrutin_solennel", "amendements"])  # jour le plus récent, puis priorité
        self.assertEqual(contenu["resultats"][0]["fois"], 2)
        self.assertEqual(contenu["resultats"][2]["par_auteur"], {"SOC": 4, "RN": 2})
        self.assertEqual(contenu["totaux_par_jour"]["12/11/2026"]["amendements"], 6)
        self.assertEqual(sources[0]["url"], "https://www.assemblee-nationale.fr/dyn/17/scrutins/9895")


class Orcet(unittest.TestCase):
    def test_compaction_et_citation(self):
        donnees = {"source": {"nom": "Hémicycle", "licence": "Tous usages, avec mention de la source « Hémicycle »"},
                   "lignes": [{"id": 7, "scrutin_uid": "VTANR5L17V9999", "texte_court": "PLF 2027",
                               "moyenne_probabilites_pour_pct": 46.2, "confiance_modele": 0.7,
                               "mis_a_jour_le": "2026-11-13T05:00:00Z"}]}
        contenu, sources = compacter_jeu(SPECS_JEUX["previsions_orcet"], donnees, {"limite": 1, "jeu": "orcet_previsions_votes"})
        self.assertIn("PAS la probabilité", contenu["a_savoir"])
        self.assertEqual(contenu["resultats"][0]["moyenne_probabilites_individuelles_pour_pct"], 46.2)
        self.assertEqual(sources[0]["nature"], "prevision_orcet")
        self.assertIn("13/11/2026", sources[0]["libelle"])
        lignes = attribuer_lignes("- **À suivre** : selon Orcet, 46,2 % en moyenne (prévision d'Orcet du 13/11/2026)",
                                  [(0, json.dumps(contenu, ensure_ascii=False), sources)])
        self.assertEqual(lignes[0]["appels"], [0])


class Attribution(unittest.TestCase):
    def test_par_source_puis_par_contenu(self):
        appels = [
            (0, json.dumps({"scrutins": [{"numero": 9895, "date": "12/11/2026"}]}),
             [{"ref": "VTANR5L17V9895", "numero": 9895, "nature": "scrutin"}]),
            (1, json.dumps({"resultats": [{"id": "PIONANR5L17B3442", "titre": "réserve communale"}]}), []),
            (2, json.dumps({"reunions": [{"quand": "mardi 10/11/2026 15:00"}]}),
             [{"nature": "agenda", "libelle": "Ordre du jour"}]),
        ]
        texte = ("- 12/11/2026 : PLF de fin de gestion rejeté (scrutin n° 9895).\n"
                 "- 05/11/2026 : dépôt du texte PIONANR5L17B3442.\n"
                 "- 10/11/2026 : séance publique (ordre du jour du 10/11/2026).\n"
                 "- Rien d'autre.")
        lignes = attribuer_lignes(texte, appels)
        self.assertEqual([l["appels"] for l in lignes], [[0], [1], [2], []])
        self.assertTrue(lignes[0]["texte"].startswith("- 12/11/2026"))

    def test_titre_de_section_sans_appel(self):
        appels = [(0, json.dumps({"scrutins": [{"numero": 9895, "titre": "loi de finances 2026"}]}), [])]
        lignes = attribuer_lignes("### Loi de finances 2026\n- **12/11/2026 · Rejeté** : ensemble (scrutin n° 9895)", appels)
        self.assertEqual([l["appels"] for l in lignes], [[], [0]])

    def test_numero_absent_et_date_ambigue(self):
        appels = [(0, '{"date":"12/11/2026"}', []), (1, '{"date":"12/11/2026"}', []), (2, '{"date":"12/11/2026"}', [])]
        lignes = attribuer_lignes("- 12/11/2026 : un fait sans référence.", appels)
        self.assertEqual(lignes[0]["appels"], [])  # date présente dans plus de deux résultats : pas d'attribution


if __name__ == "__main__":
    unittest.main(verbosity=1)
