"""Mini-application d'essai des outils « rapport » (sans MCP Hémicycle).

Sert à tester `surligner_section` avec le vrai modèle avant l'intégration dans `serveur.py`.
Elle n'expose que :
- les routes de `routes_rapport.py` (``GET /api/rapports``, ``GET /api/rapport/{mois}``) ;
- un ``POST /chat`` minimal : Featherless + les deux outils du rapport, rapport injecté dans le
  prompt système, aucune autre source.

Lancement (depuis backend/chatbot/) ::

    .venv/bin/python essai_rapport.py            # http://127.0.0.1:8001
    curl -s localhost:8001/api/rapport/demo
    curl -s localhost:8001/chat -H 'Content-Type: application/json' \\
         -d '{"mois": "demo", "question": "Quel groupe est le plus divisé ?"}'

Chaque question coûte 1 requête Featherless (pas de surlignage) ou 2 (surlignage puis réponse).

Garde-fou de budget : au-delà de ESSAI_MAX_REQUETES requêtes Featherless depuis le démarrage
(12 par défaut), ``/chat`` répond 429 sans appeler le modèle.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from featherless_client import ClientFeatherlessAsync, charger_config
from outils_rapport import NumeroInvalide, OutilsRapport, RapportIntrouvable
from routes_rapport import routeur as routeur_rapport

journal = logging.getLogger("essai_rapport")

PORT = int(os.environ.get("ESSAI_PORT", "8001"))
MAX_REQUETES = int(os.environ.get("ESSAI_MAX_REQUETES", "12"))
MAX_TOURS = 3  # appels au modèle par question (le dernier sans outils)
MESSAGE_HORS_RAPPORT = "Le rapport de ce mois ne traite pas cette question."


def prompt_systeme(outils: OutilsRapport) -> str:
    rapport = outils.rapport
    return f"""Tu es l'assistant du rapport mensuel sur l'activité parlementaire. Le lecteur lit le rapport « {rapport.titre} » et te pose des questions à son sujet.

Règles :
- Tu t'appuies UNIQUEMENT sur le texte du rapport ci-dessous, construit à partir des données Hémicycle. Jamais sur tes connaissances propres : aucun nom, date ni chiffre absent du rapport.
- Si le rapport ne traite pas la question, réponds seulement : « {MESSAGE_HORS_RAPPORT} »
- Ton neutre : des faits, ni opinion ni pronostic.
- En français, très bref : trois phrases ou trois puces au plus, sans titre.

Rapport du mois (chaque section est précédée de son identifiant entre crochets) :

{rapport.texte_pour_prompt()}

{outils.consigne_prompt()}"""


class MessageHistorique(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    contenu: str = Field(default="", max_length=4000)


class RequeteChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mois: str = "demo"
    question: str = Field(min_length=1, max_length=1000)
    historique: list[MessageHistorique] = Field(default_factory=list, max_length=20)
    # Réflexion de Qwen 3 au premier tour seulement (choix de l'outil) ; les tours suivants sans réflexion.
    # Sans elle, Qwen3.8-27B n'appelle pas surligner_section : il répond directement, annonce l'appel
    # sans le faire, ou écrit l'identifiant en texte (essais du 14/11/2026).
    reflexion_premier_tour: bool = True


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    async with ClientFeatherlessAsync(charger_config(), tentatives_max=2) as llm:
        app.state.llm = llm
        journal.info("Prêt : modèle %s, %d requêtes Featherless au plus.", llm.modele, MAX_REQUETES)
        yield
        journal.info("Arrêt : %d requête(s) Featherless envoyée(s).", llm.nb_requetes)


app = FastAPI(title="Essai des outils du rapport", lifespan=cycle_de_vie, docs_url=None, redoc_url=None)
app.include_router(routeur_rapport)


@app.post("/chat")
async def chat(requete: RequeteChat, request: Request) -> dict[str, Any]:
    llm: ClientFeatherlessAsync = request.app.state.llm
    try:
        outils = OutilsRapport(requete.mois)  # une instance par question
    except NumeroInvalide as erreur:
        raise HTTPException(400, str(erreur)) from erreur
    except RapportIntrouvable as erreur:
        raise HTTPException(404, f"Aucun rapport pour « {requete.mois} ».") from erreur

    debut = time.perf_counter()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt_systeme(outils)},
        *({"role": m.role, "content": m.contenu} for m in requete.historique[-6:] if m.contenu.strip()),
        {"role": "user", "content": requete.question.strip()},
    ]
    reponse = None
    taille_reflexion = 0
    for tour in range(MAX_TOURS):
        if llm.nb_requetes >= MAX_REQUETES:
            raise HTTPException(429, f"Budget d'essai épuisé ({MAX_REQUETES} requêtes Featherless).")
        avec_outils = tour < MAX_TOURS - 1
        reflexion = tour == 0 and requete.reflexion_premier_tour
        reponse = await llm.discuter(
            messages, outils=outils.outils_openai() if avec_outils else None,
            sans_reflexion=not reflexion, max_tokens=4000 if reflexion else 600, temperature=0.2,
        )
        taille_reflexion += len(reponse.reflexion or "")
        if not reponse.appels_outils or not avec_outils:
            break
        messages.append(reponse.message_assistant())
        for tool_call in reponse.appels_outils:
            if outils.gere(tool_call.function.name):
                message_tool, _actions = outils.executer(tool_call)
            else:  # dans serveur.py : dispatch vers le MCP Hémicycle
                message_tool = {"role": "tool", "tool_call_id": tool_call.id, "content": "Erreur : outil indisponible."}
            messages.append(message_tool)

    texte = (reponse.texte if reponse else "").strip() or "Le modèle n'a pas rédigé de réponse exploitable."
    corps = {
        "reponse": texte,
        "sources": outils.sources(),
        "actions": outils.actions,
        "outils_utilises": outils.appels,
        "meta": {
            "modele": llm.modele,
            "mois": outils.rapport.mois,
            "duree_s": round(time.perf_counter() - debut, 1),
            "requetes_featherless_depuis_demarrage": llm.nb_requetes,
            "raison_fin": reponse.raison_fin if reponse else None,
            "taille_reflexion": taille_reflexion,
        },
    }
    journal.info("Question %r → actions %s, outils %s", requete.question[:80],
                 [a["section_id"] for a in outils.actions], [a["outil"] for a in outils.appels])
    return corps


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
