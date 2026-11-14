"""Client minimal pour Featherless, le LLM du chatbot (API compatible OpenAI).

- La configuration est lue dans le `.env` à la racine du dépôt
  (`FEATHERLESS_API_KEY`, `FEATHERLESS_BASE_URL`, `FEATHERLESS_MODEL`).
  La clé n'est jamais affichée ni journalisée.
- Appels chat normal et en streaming, avec ou sans outils (format OpenAI).
- Erreurs 429 (concurrence dépassée) et 503 (capacité insuffisante) :
  quelques nouvelles tentatives espacées, en respectant `Retry-After` s'il est présent.
- Les blocs de réflexion `<think>…</think>` de Qwen 3 sont retirés du texte renvoyé.
- Deux clients : `ClientFeatherless` (synchrone) et `ClientFeatherlessAsync`
  (asynchrone, pour un serveur FastAPI qui partage sa boucle avec le SDK MCP).
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import openai
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

journal = logging.getLogger("featherless")

FICHIER_ENV = Path(__file__).resolve().parents[2] / ".env"
URL_PAR_DEFAUT = "https://api.featherless.ai/v1"

# Codes HTTP pour lesquels une nouvelle tentative a un sens.
CODES_A_RETENTER = (429, 503)


class ErreurConfiguration(RuntimeError):
    """Variable manquante dans le `.env`."""


class ConcurrenceDepassee(RuntimeError):
    """Toujours en 429 après toutes les tentatives : budget de concurrence épuisé."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigFeatherless:
    # repr=False : la clé n'apparaît pas si l'objet est affiché.
    cle_api: str = field(repr=False)
    base_url: str
    modele: str


def charger_config(modele: str | None = None) -> ConfigFeatherless:
    """Lit la configuration dans le `.env` racine (les variables d'environnement déjà définies priment)."""
    load_dotenv(FICHIER_ENV, override=False)
    cle = os.getenv("FEATHERLESS_API_KEY", "").strip()
    if not cle:
        raise ErreurConfiguration(f"FEATHERLESS_API_KEY absente (attendue dans {FICHIER_ENV}).")
    modele = modele or os.getenv("FEATHERLESS_MODEL", "").strip()
    if not modele:
        raise ErreurConfiguration("FEATHERLESS_MODEL absent : le définir dans le .env ou passer un modèle.")
    base_url = os.getenv("FEATHERLESS_BASE_URL", "").strip() or URL_PAR_DEFAUT
    return ConfigFeatherless(cle_api=cle, base_url=base_url, modele=modele)


# --------------------------------------------------------------------------
# Blocs de réflexion <think>…</think>
# --------------------------------------------------------------------------

OUVRANTE, FERMANTE = "<think>", "</think>"
_MOTIF_REFLEXION = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def separer_reflexion(texte: str | None) -> tuple[str, str | None]:
    """Sépare la réponse de la réflexion.

    Renvoie `(reponse, reflexion)`. `reflexion` vaut None s'il n'y avait aucun
    bloc, et une chaîne (éventuellement vide) sinon.
    """
    if not texte:
        return "", None
    morceaux: list[str] = []

    def _extraire(correspondance: re.Match[str]) -> str:
        morceaux.append(correspondance.group(1))
        return ""

    reponse = _MOTIF_REFLEXION.sub(_extraire, texte)
    # Balise ouvrante injectée par le gabarit de chat : seule `</think>` apparaît.
    if FERMANTE in reponse:
        avant, _, reponse = reponse.rpartition(FERMANTE)
        morceaux.append(avant)
    # Bloc jamais refermé (réponse coupée par max_tokens) : tout le reste est de la réflexion.
    if OUVRANTE in reponse:
        reponse, _, apres = reponse.partition(OUVRANTE)
        morceaux.append(apres)
    if not morceaux:
        return texte.strip(), None
    return reponse.strip(), "\n".join(m.strip() for m in morceaux).strip()


def retirer_reflexion(texte: str | None) -> str:
    return separer_reflexion(texte)[0]


def _debut_de_balise(texte: str, balise: str) -> int:
    """Longueur du plus long suffixe de `texte` qui commence `balise` (balise coupée entre deux morceaux)."""
    for n in range(min(len(texte), len(balise) - 1), 0, -1):
        if texte.endswith(balise[:n]):
            return n
    return 0


class FiltreReflexion:
    """Retire les blocs `<think>…</think>` d'un texte qui arrive par morceaux.

    `reflexion_au_depart=True` (réflexion activée) : certains gabarits de chat placent
    eux-mêmes `<think>` dans le prompt, si bien que la sortie ne contient que `</think>`
    (observé avec Qwen3.8-27B en streaming). Le texte est alors retenu jusqu'au premier
    `</think>` et traité comme de la réflexion. Si une balise `<think>` explicite arrive
    d'abord (Qwen3-32B), on revient au cas normal. Si le flux se termine sans `</think>`,
    le texte retenu est livré comme réponse : le modèle n'a pas réfléchi.
    """

    def __init__(self, reflexion_au_depart: bool = False) -> None:
        self._tampon = ""
        self._dans_reflexion = reflexion_au_depart
        self._implicite = reflexion_au_depart  # bloc ouvert sans balise <think> visible
        self._retenu: list[str] = []  # texte du bloc implicite, en attente de verdict
        self._reponse_commencee = False
        self.reflexion_detectee = False
        self.taille_reflexion = 0  # en caractères

    def _emettre(self, texte: str) -> str:
        # Supprime les espaces et sauts de ligne en tête de réponse (souvent laissés après `</think>`).
        if not self._reponse_commencee:
            texte = texte.lstrip()
            self._reponse_commencee = bool(texte)
        return texte

    def _avancer(self, n: int) -> str:
        avant, self._tampon = self._tampon[:n], self._tampon[n:]
        return avant

    def ajouter(self, morceau: str) -> str:
        self._tampon += morceau
        sortie: list[str] = []
        while self._tampon:
            if not self._dans_reflexion:
                debut = self._tampon.find(OUVRANTE)
                if debut == -1:
                    # On garde en attente une éventuelle balise coupée en deux.
                    attente = _debut_de_balise(self._tampon, OUVRANTE)
                    sortie.append(self._emettre(self._avancer(len(self._tampon) - attente)))
                    break
                sortie.append(self._emettre(self._avancer(debut)))
                self._avancer(len(OUVRANTE))
                self._dans_reflexion = self.reflexion_detectee = True
                continue

            fin = self._tampon.find(FERMANTE)
            if self._implicite:
                debut = self._tampon.find(OUVRANTE)
                if debut != -1 and (fin == -1 or debut < fin):
                    # Balise <think> explicite : ce qui précède était de la réponse.
                    sortie.append(self._emettre("".join(self._retenu) + self._avancer(debut)))
                    self._retenu.clear()
                    self._avancer(len(OUVRANTE))
                    self._implicite = False
                    self.reflexion_detectee = True
                    continue
            if fin == -1:
                attente = _debut_de_balise(self._tampon, FERMANTE)
                if self._implicite:
                    attente = max(attente, _debut_de_balise(self._tampon, OUVRANTE))
                pret = self._avancer(len(self._tampon) - attente)
                if self._implicite:
                    self._retenu.append(pret)
                else:
                    self.taille_reflexion += len(pret)
                break
            self.taille_reflexion += len("".join(self._retenu)) + len(self._avancer(fin))
            self._retenu.clear()
            self._avancer(len(FERMANTE))
            self._dans_reflexion = self._implicite = False
            self.reflexion_detectee = True
        return "".join(sortie)

    def terminer(self) -> str:
        reste, self._tampon = self._tampon, ""
        if self._dans_reflexion and self._implicite:
            # Aucun </think> : il n'y avait pas de réflexion, tout est réponse.
            texte, self._retenu = "".join(self._retenu) + reste, []
            self._dans_reflexion = self._implicite = False
            return self._emettre(texte)
        if self._dans_reflexion:
            # Bloc jamais refermé (réponse coupée par max_tokens).
            self.taille_reflexion += len(reste)
            return ""
        return self._emettre(reste)


def _reflexion_separee(objet: Any) -> str | None:
    """Réflexion renvoyée dans un champ à part (`reasoning_content` ou `reasoning`), si le serveur le fait."""
    extra = getattr(objet, "model_extra", None) or {}
    for nom in ("reasoning_content", "reasoning"):
        valeur = extra.get(nom) or getattr(objet, nom, None)
        if isinstance(valeur, str) and valeur:
            return valeur
    return None


# --------------------------------------------------------------------------
# Résultats
# --------------------------------------------------------------------------


@dataclass
class ReponseChat:
    texte: str  # réponse sans la réflexion
    reflexion: str | None  # None : aucun bloc de réflexion
    appels_outils: list[Any]  # tool_calls au format OpenAI (vide si aucun)
    raison_fin: str | None  # finish_reason : "stop", "tool_calls", "length"…
    usage: Any  # tokens consommés, si le serveur les renvoie
    duree_s: float
    message: Any  # message brut renvoyé par le SDK
    modele_servi: str | None = None  # champ `model` de la réponse (modèle déclaré par le serveur)
    id_requete: str | None = None  # à communiquer au support Featherless en cas d'anomalie

    def message_assistant(self) -> dict[str, Any]:
        """Message à réinjecter dans la conversation (sans la réflexion)."""
        message: dict[str, Any] = {"role": "assistant", "content": self.texte or None}
        if self.appels_outils:
            message["tool_calls"] = [
                {
                    "id": appel.id,
                    "type": "function",
                    "function": {"name": appel.function.name, "arguments": appel.function.arguments},
                }
                for appel in self.appels_outils
            ]
        return message


class FluxChat:
    """Réponse en streaming : itérer dessus donne le texte visible, morceau par morceau.

    Une fois le flux consommé : `texte`, `reflexion_detectee`, `usage`, `raison_fin`
    et `delai_premier_morceau_s` sont renseignés.
    """

    def __init__(self, flux: Any, debut: float, *, reflexion_au_depart: bool) -> None:
        self._flux = flux
        self._debut = debut
        self._filtre = FiltreReflexion(reflexion_au_depart)
        self._morceaux: list[str] = []
        self._reflexion_champ_separe = 0
        self.usage: Any = None
        self.raison_fin: str | None = None
        self.delai_premier_morceau_s: float | None = None
        self.duree_s: float | None = None

    def __iter__(self) -> Iterator[str]:
        for paquet in self._flux:
            if getattr(paquet, "usage", None):
                self.usage = paquet.usage
            if not paquet.choices:
                continue
            choix = paquet.choices[0]
            if choix.finish_reason:
                self.raison_fin = choix.finish_reason
            reflexion = _reflexion_separee(choix.delta)
            if reflexion:
                self._reflexion_champ_separe += len(reflexion)
            if choix.delta.content:
                yield from self._livrer(self._filtre.ajouter(choix.delta.content))
        yield from self._livrer(self._filtre.terminer())
        self.duree_s = time.perf_counter() - self._debut

    def _livrer(self, texte: str) -> Iterator[str]:
        if texte:
            if self.delai_premier_morceau_s is None:
                self.delai_premier_morceau_s = time.perf_counter() - self._debut
            self._morceaux.append(texte)
            yield texte

    @property
    def texte(self) -> str:
        return "".join(self._morceaux).strip()

    @property
    def reflexion_detectee(self) -> bool:
        return self._filtre.reflexion_detectee or self._reflexion_champ_separe > 0

    @property
    def taille_reflexion(self) -> int:
        return self._filtre.taille_reflexion + self._reflexion_champ_separe


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


def _lire_retry_after(reponse: Any) -> float | None:
    """Délai demandé par le serveur (en secondes), d'après `Retry-After-Ms` ou `Retry-After`."""
    if reponse is None:
        return None
    en_tetes = reponse.headers
    try:
        return float(en_tetes["retry-after-ms"]) / 1000
    except (KeyError, ValueError):
        pass
    valeur = en_tetes.get("retry-after")
    if not valeur:
        return None
    try:
        return float(valeur)
    except ValueError:
        pass
    # Retry-After peut aussi être une date HTTP.
    try:
        date = email.utils.parsedate_to_datetime(valeur)
    except (TypeError, ValueError):
        return None
    return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())


def _reponse_chat(completion: Any, duree: float) -> ReponseChat:
    """Construit un `ReponseChat` à partir de la réponse complète du SDK."""
    choix = completion.choices[0]
    texte, reflexion = separer_reflexion(choix.message.content)
    if reflexion is None:
        reflexion = _reflexion_separee(choix.message)
    return ReponseChat(
        texte=texte,
        reflexion=reflexion,
        appels_outils=list(choix.message.tool_calls or []),
        raison_fin=choix.finish_reason,
        usage=completion.usage,
        duree_s=duree,
        message=choix.message,
        modele_servi=getattr(completion, "model", None),
        id_requete=getattr(completion, "_request_id", None) or getattr(completion, "id", None),
    )


class _ClientBase:
    """Partie commune aux clients synchrone et asynchrone : configuration, paramètres, nouvelles tentatives."""

    def __init__(
        self,
        config: ConfigFeatherless | None,
        *,
        modele: str | None,
        tentatives_max: int,
        delai_initial_s: float,
        delai_max_s: float,
    ) -> None:
        self.config = config or charger_config(modele)
        self.tentatives_max = tentatives_max
        self.delai_initial_s = delai_initial_s
        self.delai_max_s = delai_max_s
        self.nb_requetes = 0  # requêtes HTTP réellement envoyées, nouvelles tentatives comprises

    @property
    def modele(self) -> str:
        return self.config.modele

    def _delai(self, erreur: openai.APIStatusError, tentative: int) -> float:
        demande = _lire_retry_after(erreur.response)
        if demande is None:
            demande = self.delai_initial_s * 2 ** (tentative - 1) + random.uniform(0, 0.5)
        return min(demande, self.delai_max_s)

    def _delai_avant_nouvelle_tentative(self, erreur: openai.APIStatusError, tentative: int) -> float:
        """Délai avant la tentative suivante ; relève l'erreur s'il ne faut pas réessayer."""
        if erreur.status_code not in CODES_A_RETENTER:
            raise erreur  # 400, 401, 403, 404… : inutile de réessayer
        if tentative == self.tentatives_max:
            if erreur.status_code == 429:
                raise ConcurrenceDepassee(
                    f"Featherless : HTTP 429 après {tentative} tentatives "
                    "(budget de concurrence du plan dépassé)."
                ) from erreur
            raise erreur
        delai = self._delai(erreur, tentative)
        journal.warning(
            "Featherless : HTTP %s, nouvelle tentative dans %.1f s (%d/%d)",
            erreur.status_code, delai, tentative + 1, self.tentatives_max,
        )
        return delai

    def _parametres(
        self, messages: list[dict[str, Any]], outils: list[dict[str, Any]] | None,
        sans_reflexion: bool, options: dict[str, Any],
    ) -> dict[str, Any]:
        parametres: dict[str, Any] = {"model": self.modele, "messages": messages, **options}
        if outils:
            parametres["tools"] = outils
        if sans_reflexion:
            # Paramètre documenté par Featherless (« Chat template kwargs ») pour couper la réflexion de Qwen 3.
            extra = dict(parametres.get("extra_body") or {})
            extra["chat_template_kwargs"] = {**extra.get("chat_template_kwargs", {}), "enable_thinking": False}
            parametres["extra_body"] = extra
        return parametres


class ClientFeatherless(_ClientBase):
    """Accès au LLM via le SDK OpenAI pointé sur Featherless (synchrone)."""

    def __init__(
        self,
        config: ConfigFeatherless | None = None,
        *,
        modele: str | None = None,
        tentatives_max: int = 4,
        delai_initial_s: float = 2.0,
        delai_max_s: float = 30.0,
        timeout_s: float = 180.0,
    ) -> None:
        super().__init__(
            config, modele=modele, tentatives_max=tentatives_max,
            delai_initial_s=delai_initial_s, delai_max_s=delai_max_s,
        )
        # max_retries=0 : on gère nous-mêmes les nouvelles tentatives (voir _creer).
        self._openai = OpenAI(
            api_key=self.config.cle_api,
            base_url=self.config.base_url,
            max_retries=0,
            timeout=timeout_s,
        )

    def _creer(self, **parametres: Any) -> Any:
        """Envoie la requête ; nouvelles tentatives espacées sur 429 et 503 uniquement."""
        for tentative in range(1, self.tentatives_max + 1):
            self.nb_requetes += 1
            try:
                return self._openai.chat.completions.create(**parametres)
            except openai.APIStatusError as erreur:
                time.sleep(self._delai_avant_nouvelle_tentative(erreur, tentative))
        raise AssertionError("inaccessible")

    def discuter(
        self,
        messages: list[dict[str, Any]],
        *,
        outils: list[dict[str, Any]] | None = None,
        sans_reflexion: bool = False,
        **options: Any,
    ) -> ReponseChat:
        """Appel chat classique (réponse complète d'un coup)."""
        debut = time.perf_counter()
        completion = self._creer(**self._parametres(messages, outils, sans_reflexion, options))
        return _reponse_chat(completion, time.perf_counter() - debut)

    def discuter_en_flux(
        self,
        messages: list[dict[str, Any]],
        *,
        sans_reflexion: bool = False,
        **options: Any,
    ) -> FluxChat:
        """Appel chat en streaming, sans outils (la boucle d'outils passe par `discuter`).

        Réflexion activée : le texte n'est livré qu'une fois la réflexion terminée
        (voir `FiltreReflexion`). Avec `sans_reflexion=True`, il est livré dès le premier token.
        """
        options.setdefault("stream_options", {"include_usage": True})
        debut = time.perf_counter()
        flux = self._creer(stream=True, **self._parametres(messages, None, sans_reflexion, options))
        return FluxChat(flux, debut, reflexion_au_depart=not sans_reflexion)


class ClientFeatherlessAsync(_ClientBase):
    """Variante asynchrone (`AsyncOpenAI`), pour la boucle d'outils du serveur FastAPI.

    Même configuration, mêmes nouvelles tentatives (429 et 503) et même retrait de la
    réflexion que `ClientFeatherless`. Pas de streaming pour l'instant.

    Exemple ::

        async with ClientFeatherlessAsync() as llm:
            reponse = await llm.discuter(messages, outils=outils, sans_reflexion=True)
    """

    def __init__(
        self,
        config: ConfigFeatherless | None = None,
        *,
        modele: str | None = None,
        tentatives_max: int = 4,
        delai_initial_s: float = 2.0,
        delai_max_s: float = 30.0,
        timeout_s: float = 180.0,
    ) -> None:
        super().__init__(
            config, modele=modele, tentatives_max=tentatives_max,
            delai_initial_s=delai_initial_s, delai_max_s=delai_max_s,
        )
        self._openai = AsyncOpenAI(
            api_key=self.config.cle_api,
            base_url=self.config.base_url,
            max_retries=0,
            timeout=timeout_s,
        )

    async def __aenter__(self) -> ClientFeatherlessAsync:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.fermer()

    async def fermer(self) -> None:
        await self._openai.close()

    async def _creer(self, **parametres: Any) -> Any:
        """Envoie la requête ; nouvelles tentatives espacées sur 429 et 503 uniquement."""
        for tentative in range(1, self.tentatives_max + 1):
            self.nb_requetes += 1
            try:
                return await self._openai.chat.completions.create(**parametres)
            except openai.APIStatusError as erreur:
                await asyncio.sleep(self._delai_avant_nouvelle_tentative(erreur, tentative))
        raise AssertionError("inaccessible")

    async def discuter(
        self,
        messages: list[dict[str, Any]],
        *,
        outils: list[dict[str, Any]] | None = None,
        sans_reflexion: bool = False,
        **options: Any,
    ) -> ReponseChat:
        """Appel chat classique (réponse complète d'un coup)."""
        debut = time.perf_counter()
        completion = await self._creer(**self._parametres(messages, outils, sans_reflexion, options))
        return _reponse_chat(completion, time.perf_counter() - debut)
