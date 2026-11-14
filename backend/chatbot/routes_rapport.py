"""Routes FastAPI du rapport : les sections d'un numéro en JSON, pour la page de lecture.

À inclure dans l'application du chatbot ::

    from routes_rapport import routeur as routeur_rapport
    app.include_router(routeur_rapport)

Points d'accès (lecture seule, sans clé, sans appel au LLM ni à Hémicycle) :
- ``GET /api/rapports`` : numéros disponibles, du plus récent au plus ancien ;
- ``GET /api/rapport/{mois}`` : le numéro découpé en sections (``mois`` = ``AAAA-MM`` ou ``demo``).
  Chaque section porte l'identifiant que reçoit l'action ``surligner_section`` de ``POST /chat``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from outils_rapport import NumeroInvalide, RapportIntrouvable, charger_rapport, numeros_disponibles

routeur = APIRouter(tags=["rapport"])


@routeur.get("/api/rapports")
def lister_numeros() -> dict[str, Any]:
    return {"numeros": numeros_disponibles()}


@routeur.get("/api/rapport/{mois}")
def lire_rapport(mois: str) -> dict[str, Any]:
    try:
        return charger_rapport(mois).en_json()
    except NumeroInvalide as erreur:
        raise HTTPException(400, str(erreur)) from erreur
    except RapportIntrouvable as erreur:
        raise HTTPException(404, f"Aucun rapport pour « {mois} ».") from erreur
