"""Tests des outils « rapport » (sans réseau, sans LLM).

Lancement (depuis backend/chatbot/) ::

    .venv/bin/python -m unittest test_outils_rapport -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from outils_rapport import (
    DOSSIER_RAPPORTS,
    NOM_LISTER,
    NOM_SURLIGNER,
    NumeroInvalide,
    OutilsRapport,
    RapportIntrouvable,
    analyser_rapport,
    charger_rapport,
    chemin_rapport,
    separer_front_matter,
    slugifier,
    texte_brut,
)
from routes_rapport import routeur

IDS_MODELE = [
    "l-essentiel-du-mois",
    "barometre",
    "activite-parlementaire",
    "cohesion-des-groupes",
    "alliances-et-oppositions",
    "focus",
    "ce-qu-il-faut-surveiller-le-mois-prochain",
    "methodologie",
    "sources",
]


def appel(nom: str, arguments: object, ident: str = "appel_1") -> dict:
    """tool_call au format OpenAI (dictionnaire), arguments sérialisés comme le fait le modèle."""
    brut = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return {"id": ident, "type": "function", "function": {"name": nom, "arguments": brut}}


class TestParseur(unittest.TestCase):
    def test_modele(self):
        rapport = analyser_rapport((DOSSIER_RAPPORTS / "_modele" / "rapport.md").read_text(encoding="utf-8"))
        self.assertEqual(rapport.ids, IDS_MODELE)
        self.assertEqual(rapport.titre, "Titre du numéro")
        par_id = {s.id: s for s in rapport.sections}
        self.assertEqual(par_id["cohesion-des-groupes"].niveau, 3)
        self.assertEqual(par_id["cohesion-des-groupes"].parent, "barometre")
        self.assertIsNone(par_id["barometre"].parent)
        self.assertEqual(par_id["focus"].titre, "Focus : titre du sujet du mois")  # emphase retirée
        self.assertNotIn("|", par_id["sources"].extrait)

    def test_front_matter_ignore(self):
        texte = '---\nmois: 2026-10\ntitre: "## Pas une section"\nauteurs: [A, "B"]\nfictif: true\n---\n\n## Vraie section\n\nTexte.\n'
        meta, corps = separer_front_matter(texte)
        self.assertEqual(meta, {"mois": "2026-10", "titre": "## Pas une section", "auteurs": ["A", "B"], "fictif": True})
        self.assertNotIn("mois:", corps)
        rapport = analyser_rapport(texte)
        self.assertEqual(rapport.ids, ["vraie-section"])
        self.assertEqual(rapport.mois, "2026-10")

    def test_front_matter_non_referme(self):
        texte = "---\nmois: x\n## Titre\n"
        self.assertEqual(separer_front_matter(texte), ({}, texte))

    def test_blocs_de_code_doublons_id_explicite(self):
        texte = (
            "# Numéro\n\nIntro.\n\n## Activité\n\n```\n## pas un titre\n```\n\n#### Détail\n\nTexte.\n\n"
            "## Activité\n\nBis.\n\n## Titre libre {#mon-id}\n\nTer.\n\n### Sous-partie\n"
        )
        rapport = analyser_rapport(texte)
        self.assertEqual(rapport.ids, ["activite", "activite-2", "mon-id", "sous-partie"])
        self.assertEqual(rapport.introduction, "Intro.")
        self.assertIn("## pas un titre", rapport.sections[0].markdown)  # le bloc de code reste dans le corps
        self.assertIn("#### Détail", rapport.sections[0].markdown)  # niveau 4 : dans le corps
        self.assertEqual(rapport.section("mon-id").titre, "Titre libre")
        self.assertEqual(rapport.section("sous-partie").parent, "mon-id")

    def test_extrait_section_sans_texte(self):
        rapport = analyser_rapport("## Baromètre\n\n### A\n\nTexte A.\n\n### B\n\nTexte B.\n")
        self.assertEqual(rapport.section("barometre").extrait, "Sous-sections : A, B.")

    def test_slug_et_texte_brut(self):
        self.assertEqual(slugifier("L’essentiel du mois"), "l-essentiel-du-mois")
        self.assertEqual(slugifier("Cohésion des groupes"), "cohesion-des-groupes")
        self.assertEqual(slugifier("Œuvres & Ça"), "oeuvres-ca")
        self.assertLessEqual(len(slugifier("mot " * 40)), 60)
        self.assertEqual(texte_brut("- _Fait_ **gras** [lien](https://x) `{{nb_scrutins_an}}`"), "Fait gras lien {{nb_scrutins_an}}")

    def test_extrait_court(self):
        rapport = analyser_rapport("## A\n\n" + "mot " * 200)
        self.assertLessEqual(len(rapport.sections[0].extrait), 180)
        self.assertTrue(rapport.sections[0].extrait.endswith("…"))

    def test_numero_demo(self):
        rapport = charger_rapport("demo")
        self.assertEqual(rapport.ids, IDS_MODELE)
        self.assertTrue(rapport.fictif)
        self.assertIn("[cohesion-des-groupes] ### Cohésion des groupes", rapport.texte_pour_prompt())
        # Chaque paragraphe de section est marqué comme fictif.
        for section in rapport.sections:
            self.assertIn("[Exemple fictif]", section.markdown, section.id)

    def test_mois_invalides(self):
        for mois in ("../etc", "2026-13", "_modele", "2026-1", "", "demo/../x"):
            with self.assertRaises(NumeroInvalide, msg=mois):
                chemin_rapport(mois)
        with self.assertRaises(RapportIntrouvable):
            charger_rapport("1999-01")

    def test_cache_relu_si_fichier_modifie(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "2026-10" / "rapport.md"
            fichier.parent.mkdir()
            fichier.write_text("## Un\n", encoding="utf-8")
            self.assertEqual(charger_rapport("2026-10", Path(dossier)).ids, ["un"])
            fichier.write_text("## Un\n\n## Deux plus long\n", encoding="utf-8")
            self.assertEqual(charger_rapport("2026-10", Path(dossier)).ids, ["un", "deux-plus-long"])


class TestOutils(unittest.TestCase):
    def setUp(self):
        self.outils = OutilsRapport("demo")

    def test_definitions(self):
        definitions = self.outils.outils_openai()
        self.assertEqual([d["function"]["name"] for d in definitions], [NOM_LISTER, NOM_SURLIGNER])
        schema = definitions[1]["function"]["parameters"]
        self.assertEqual(schema["properties"]["section_id"]["enum"], IDS_MODELE)
        self.assertEqual(schema["required"], ["section_id", "raison"])
        self.assertTrue(self.outils.gere(NOM_SURLIGNER) and self.outils.gere(NOM_LISTER))
        self.assertFalse(self.outils.gere("rechercher"))

    def test_lister(self):
        message, actions = self.outils.executer(appel(NOM_LISTER, {}))
        self.assertEqual(actions, [])
        self.assertEqual(message["role"], "tool")
        self.assertEqual(message["tool_call_id"], "appel_1")
        contenu = json.loads(message["content"])
        self.assertEqual([s["id"] for s in contenu["sections"]], IDS_MODELE)
        self.assertNotIn("markdown", contenu["sections"][0])
        self.assertEqual(self.outils.appels[-1]["statut"], "ok")

    def test_surligner_ok(self):
        message, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "cohesion-des-groupes", "raison": "Taux de cohésion."}))
        self.assertEqual(actions, [{
            "type": "surligner_section", "section_id": "cohesion-des-groupes",
            "titre": "Cohésion des groupes", "raison": "Taux de cohésion.",
        }])
        self.assertTrue(message["content"].startswith("OK"))
        self.assertEqual(self.outils.actions, actions)
        self.assertEqual(self.outils.sources()[0]["type"], "rapport")
        self.assertEqual(self.outils.sources()[0]["section"], "Cohésion des groupes")

    def test_surligner_id_inconnu(self):
        message, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "meteo", "raison": "x"}))
        self.assertEqual(actions, [])
        self.assertTrue(message["content"].startswith("Erreur"))
        for ident in IDS_MODELE:  # l'erreur liste les identifiants valides
            self.assertIn(ident, message["content"])
        self.assertEqual(self.outils.appels[-1]["statut"], "erreur")
        self.assertEqual(self.outils.actions, [])

    def test_surligner_titre_au_lieu_de_l_id(self):
        _, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "Cohésion des groupes", "raison": ""}))
        self.assertEqual(actions[0]["section_id"], "cohesion-des-groupes")
        _, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "[methodologie]", "raison": ""}))
        self.assertEqual(actions[0]["section_id"], "methodologie")

    def test_surligner_doublon_et_maximum(self):
        self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "focus", "raison": "a"}))
        _, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "focus", "raison": "a"}))
        self.assertEqual(actions, [])  # pas de doublon
        self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "sources", "raison": "b"}))
        message, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "methodologie", "raison": "c"}))
        self.assertEqual(actions, [])  # 2 au plus
        self.assertTrue(message["content"].startswith("Refusé"))
        self.assertEqual([a["section_id"] for a in self.outils.actions], ["focus", "sources"])

    def test_arguments_invalides(self):
        message, actions = self.outils.executer(appel(NOM_SURLIGNER, "{pas du json"))
        self.assertTrue(message["content"].startswith("Erreur") and actions == [])
        message, actions = self.outils.executer(appel(NOM_SURLIGNER, {"raison": "sans id"}))
        self.assertTrue(message["content"].startswith("Erreur") and actions == [])
        message, _ = self.outils.executer(appel("autre_outil", {}))
        self.assertIn("inconnu", message["content"])

    def test_tool_call_objet_sdk(self):
        class Fonction:
            name, arguments = NOM_SURLIGNER, '{"section_id": "focus", "raison": "r"}'

        class ToolCall:
            id, function = "call_9", Fonction()

        message, actions = self.outils.executer(ToolCall())
        self.assertEqual(message["tool_call_id"], "call_9")
        self.assertEqual(actions[0]["section_id"], "focus")

    def test_raison_tronquee(self):
        _, actions = self.outils.executer(appel(NOM_SURLIGNER, {"section_id": "focus", "raison": "mot " * 200}))
        self.assertLessEqual(len(actions[0]["raison"]), 200)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(routeur)
        self.client = TestClient(app)

    def test_rapport_demo(self):
        reponse = self.client.get("/api/rapport/demo")
        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertTrue(corps["fictif"])
        self.assertEqual([s["id"] for s in corps["sections"]], IDS_MODELE)
        self.assertIn("markdown", corps["sections"][0])

    def test_erreurs(self):
        self.assertEqual(self.client.get("/api/rapport/1999-01").status_code, 404)
        self.assertEqual(self.client.get("/api/rapport/_modele").status_code, 400)

    def test_numeros(self):
        self.assertIn("demo", self.client.get("/api/rapports").json()["numeros"])


if __name__ == "__main__":
    unittest.main()
