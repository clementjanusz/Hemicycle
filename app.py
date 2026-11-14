"""Point d'entrée Vercel : expose l'application FastAPI du chatbot (backend/chatbot/serveur.py).

Vercel cherche une variable ``app`` dans ``app.py`` à la racine du dépôt. Les modules du chatbot
s'importent entre eux « à plat » (``from featherless_client import …``) : on ajoute leur dossier
au chemin d'import avant de charger le serveur. Le code du chatbot n'est pas modifié.

En local, rien ne change : ``cd backend/chatbot && .venv/bin/python serveur.py``.
Pour reproduire le démarrage de Vercel depuis la racine :
``backend/chatbot/.venv/bin/uvicorn app:app --port 8000``.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "chatbot"))

# Sur Vercel, serveur.main() n'est jamais appelé : on règle ici les journaux (visibles dans Runtime Logs).
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s : %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)

import serveur  # noqa: E402

app = serveur.app
