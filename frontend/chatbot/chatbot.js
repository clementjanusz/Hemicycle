/*
 * Chatbot du dossier — module autonome.
 *
 * Intégration (une seule ligne, n'importe quelle page) :
 *   <script src="chatbot/chatbot.js" data-mois="2026-11" defer></script>
 *
 * Le script charge sa feuille de style (chatbot.css, à côté de lui), injecte le widget à la fin
 * de <body> et dialogue avec le backend via POST /chat/flux (NDJSON). Contrat des réponses :
 * docs/ARCHITECTURE.md. Aucune dépendance, aucune clé : tout passe par le backend.
 */
(function () {
  "use strict";

  // À capturer immédiatement : document.currentScript n'est défini que pendant l'exécution.
  var script = document.currentScript || document.querySelector('script[src*="chatbot.js"]');

  // ---------------------------------------------------------------- fonctions pures (début)

  var MAX_HISTORIQUE = 20; // messages (le serveur refuse au-delà : HTTP 422)
  var MAX_CONTENU_HISTORIQUE = 4000; // caractères par message d'historique (idem)
  var MAX_ACTIONS = 2;

  /** Échappe le HTML d'un texte. */
  function echapper(texte) {
    return String(texte == null ? "" : texte).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** Gras `**…**` sur un texte DÉJÀ échappé (sur une seule ligne). */
  function rendreGras(html) {
    return html.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, "<strong>$1</strong>");
  }

  var MOTIF_PUCE = /^\s*[-*•]\s+/;
  var MOTIF_TITRE = /^\s*#{1,6}\s+/;

  /**
   * Texte de réponse → HTML restreint : <p>, <ul><li>, <strong>. Tout le reste est échappé.
   * Une ligne « - … » (ou « * », « • ») est une puce ; les autres lignes consécutives forment un
   * paragraphe ; une ligne vide termine le bloc. Un titre « ### … » devient un paragraphe en gras.
   */
  function texteEnHtml(texte) {
    var lignes = String(texte == null ? "" : texte).replace(/\r\n?/g, "\n").split("\n");
    var html = [];
    var paragraphe = [];
    var puces = [];

    function fermerParagraphe() {
      if (paragraphe.length) html.push("<p>" + paragraphe.join(" ") + "</p>");
      paragraphe = [];
    }
    function fermerListe() {
      if (puces.length) html.push("<ul>" + puces.map(function (p) { return "<li>" + p + "</li>"; }).join("") + "</ul>");
      puces = [];
    }

    lignes.forEach(function (brute) {
      var ligne = brute.trim();
      if (!ligne) {
        fermerParagraphe();
        fermerListe();
      } else if (MOTIF_PUCE.test(brute)) {
        fermerParagraphe();
        puces.push(rendreGras(echapper(brute.replace(MOTIF_PUCE, "").trim())));
      } else if (MOTIF_TITRE.test(brute)) {
        fermerParagraphe();
        fermerListe();
        var titre = brute.replace(MOTIF_TITRE, "").replace(/\*\*/g, "").trim();
        html.push("<p><strong>" + echapper(titre) + "</strong></p>");
      } else {
        fermerListe();
        paragraphe.push(rendreGras(echapper(ligne)));
      }
    });
    fermerParagraphe();
    fermerListe();
    return html.join("");
  }

  /**
   * Découpage NDJSON : ajoute un morceau de texte au tampon, renvoie les lignes complètes
   * (non vides) et le reste (ligne incomplète, à garder pour la lecture suivante).
   */
  function decouperLignes(tampon, morceau) {
    var lignes = (tampon + morceau).split("\n");
    var reste = lignes.pop();
    return {
      lignes: lignes.filter(function (l) { return l.trim() !== ""; }),
      reste: reste,
    };
  }

  /** Historique à envoyer : les 20 derniers messages, chacun tronqué à 4 000 caractères. */
  function historiqueAEnvoyer(historique) {
    return historique.slice(-MAX_HISTORIQUE).map(function (m) {
      return { role: m.role, contenu: String(m.contenu || "").slice(0, MAX_CONTENU_HISTORIQUE) };
    });
  }

  /** Actions `surligner_section` valides : 2 au plus, sans doublon, types inconnus ignorés. */
  function actionsSurlignage(actions) {
    var vues = {};
    return (Array.isArray(actions) ? actions : []).filter(function (a) {
      if (!a || a.type !== "surligner_section" || typeof a.section_id !== "string" || !a.section_id) return false;
      if (vues[a.section_id]) return false;
      vues[a.section_id] = true;
      return true;
    }).slice(0, MAX_ACTIONS);
  }

  /** URL http(s) absolue, ou null (jamais de `javascript:` ni autre schéma). */
  function urlSure(url) {
    if (typeof url !== "string" || !url) return null;
    try {
      var u = new URL(url);
      return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  /** Message lisible pour une réponse HTTP en erreur (avant le flux : 422 surtout). */
  function messageHttp(statut, corps) {
    var detail = corps && corps.detail;
    if (typeof detail === "string" && detail) return detail;
    if (statut === 422) return "La question n’a pas pu être envoyée (format refusé par le serveur).";
    return "Le serveur a répondu par une erreur (HTTP " + statut + ").";
  }

  // ---------------------------------------------------------------- fonctions pures (fin)

  if (document.getElementById("cb-panneau")) return; // déjà chargé

  var donnees = (script && script.dataset) || {};
  var MOIS = donnees.mois || window.CHATBOT_MOIS || "2026-11";
  var API = String(donnees.api != null ? donnees.api : (window.CHATBOT_API != null ? window.CHATBOT_API : "")).replace(/\/+$/, "");
  var DUREE_SURLIGNAGE = 5000; // ms
  // Page du dossier (ex. « incendies.html ») : on y va quand la section visée n'est pas sur la page courante.
  var RAPPORT = donnees.rapport || window.CHATBOT_RAPPORT || "";

  var SUGGESTIONS = [
    "Que s’est-il passé sur les incendies ?",
    "Quelles aides pour les entreprises ?",
    "Qui a voté contre le budget ?",
  ];

  // Feuille de style du module, à côté du script. Renvoie le <link> (ou null) pour attendre son chargement.
  var feuilleStyle = (function chargerStyle() {
    var href;
    if (!script || !script.src) return null;
    try {
      href = new URL("chatbot.css", script.src).href;
    } catch (e) {
      return null;
    }
    var deja = Array.prototype.find.call(document.querySelectorAll('link[rel="stylesheet"]'), function (l) {
      return l.href === href;
    });
    if (deja) return deja;
    var lien = document.createElement("link");
    lien.rel = "stylesheet";
    lien.href = href;
    document.head.appendChild(lien);
    return lien;
  })();

  // ---------------------------------------------------------------- construction du DOM

  function el(balise, attributs, enfants) {
    var noeud = document.createElement(balise);
    Object.keys(attributs || {}).forEach(function (nom) {
      var valeur = attributs[nom];
      if (valeur == null || valeur === false) return;
      if (nom === "texte") noeud.textContent = valeur;
      else if (nom === "classe") noeud.className = valeur;
      else noeud.setAttribute(nom, valeur === true ? "" : valeur);
    });
    (enfants || []).forEach(function (enfant) {
      if (enfant) noeud.appendChild(enfant);
    });
    return noeud;
  }

  var lanceur, panneau, fil, formulaire, saisie, envoyer, accueil;

  function construire() {
    lanceur = el("button", { type: "button", classe: "cb-lanceur", "aria-expanded": "false", "aria-controls": "cb-panneau" }, [
      el("span", { classe: "cb-lanceur-icone", "aria-hidden": "true" }),
      el("span", { classe: "cb-lanceur-texte", texte: "Poser une question" }),
    ]);

    var fermer = el("button", { type: "button", classe: "cb-fermer", "aria-label": "Fermer", texte: "×" });

    accueil = el("div", { classe: "cb-accueil" }, [
      el("p", { texte: "Une question sur le dossier ou les votes ?" }),
      el("div", { classe: "cb-suggestions" }, SUGGESTIONS.map(function (s) {
        return el("button", { type: "button", classe: "cb-suggestion", texte: s });
      })),
    ]);

    fil = el("div", { classe: "cb-fil", "aria-live": "polite" }, [accueil]);

    saisie = el("textarea", {
      id: "cb-saisie", classe: "cb-saisie", rows: "2", maxlength: "1000", placeholder: "Posez votre question…",
    });
    envoyer = el("button", { type: "submit", classe: "cb-envoyer", texte: "Envoyer" });
    formulaire = el("form", { classe: "cb-formulaire" }, [
      el("label", { classe: "cb-label", for: "cb-saisie", texte: "Votre question" }),
      saisie,
      envoyer,
    ]);

    panneau = el("section", {
      id: "cb-panneau", classe: "cb-panneau", role: "dialog", "aria-modal": "false", "aria-labelledby": "cb-titre", hidden: true,
    }, [
      el("header", { classe: "cb-entete" }, [
        el("h2", { id: "cb-titre", classe: "cb-titre", texte: "Questions" }),
        fermer,
      ]),
      fil,
      formulaire,
      el("p", { classe: "cb-mention", texte: "Réponses automatiques · vérifiez les sources" }),
    ]);

    document.body.appendChild(lanceur);
    document.body.appendChild(panneau);

    lanceur.addEventListener("click", function () {
      if (panneau.hidden) ouvrir();
      else fermerPanneau();
    });
    fermer.addEventListener("click", fermerPanneau);
    accueil.addEventListener("click", function (evenement) {
      var bouton = evenement.target.closest(".cb-suggestion");
      if (bouton) poser(bouton.textContent);
    });
    formulaire.addEventListener("submit", function (evenement) {
      evenement.preventDefault();
      poser(saisie.value);
    });
    saisie.addEventListener("keydown", function (evenement) {
      if (evenement.key === "Enter" && !evenement.shiftKey && !evenement.isComposing) {
        evenement.preventDefault();
        poser(saisie.value);
      }
    });
    document.addEventListener("keydown", function (evenement) {
      if (evenement.key === "Escape" && !panneau.hidden && !evenement.defaultPrevented) {
        fermerPanneau();
      }
    });
    initialiserSession(); // fil conservé d'une page à l'autre, [data-chatbot-ouvrir]
  }

  // ---------------------------------------------------------------- ouverture, fermeture

  function ouvrir() {
    panneau.hidden = false;
    lanceur.setAttribute("aria-expanded", "true");
    document.documentElement.classList.add("cb-ouvert");
    if (!saisie.disabled) saisie.focus();
    apresOuverture();
  }

  function fermerPanneau() {
    abandonner();
    panneau.hidden = true;
    lanceur.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("cb-ouvert");
    lanceur.focus();
  }

  /** Le panneau masque-t-il presque toute la page (mobile) ? */
  function panneauCouvrePage() {
    if (panneau.hidden) return false;
    var r = panneau.getBoundingClientRect();
    return r.width >= window.innerWidth * 0.8;
  }

  // ---------------------------------------------------------------- fil de discussion

  function defilerFilEnBas() {
    fil.scrollTop = fil.scrollHeight;
  }

  function defilerFilVers(element) {
    fil.scrollTop += element.getBoundingClientRect().top - fil.getBoundingClientRect().top - 8;
  }

  function ajouterAuFil(element) {
    var etape = fil.querySelector(".cb-etape");
    if (etape && etape !== element) fil.insertBefore(element, etape);
    else fil.appendChild(element);
    return element;
  }

  function message(type, texte) {
    var attributs = { classe: "cb-msg cb-msg--" + type };
    if (type === "erreur") attributs.role = "alert";
    journaliser({ type: type, texte: texte });
    return ajouterAuFil(el("div", attributs, [el("p", { texte: texte })]));
  }

  // ---------------------------------------------------------------- surlignage des sections

  var minuteurs = {};

  function reduireAnimations() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function surligner(section) {
    var id = section.id;
    clearTimeout(minuteurs[id]);
    section.classList.remove("cb-surligne");
    void section.offsetWidth; // relance l'animation si la section était déjà surlignée
    section.classList.add("cb-surligne");
    minuteurs[id] = setTimeout(function () {
      section.classList.remove("cb-surligne");
      delete minuteurs[id];
    }, DUREE_SURLIGNAGE);
  }

  function defilerVers(section) {
    section.scrollIntoView({ behavior: reduireAnimations() ? "auto" : "smooth", block: "start" });
  }

  /** Clic sur « Voir la section » ou sur une source du rapport : défiler et surligner. */
  function allerALaSection(id) {
    var section = document.getElementById(id);
    if (!section) return allerAuRapport(id);
    if (panneauCouvrePage()) fermerPanneau();
    defilerVers(section);
    surligner(section);
  }

  function lienSection(classe, id, texte, titre) {
    var lien = el("a", { classe: classe, href: hrefSection(id), texte: texte, title: titre || null });
    lien.addEventListener("click", function (evenement) {
      evenement.preventDefault();
      allerALaSection(id);
    });
    return lien;
  }

  /** Exécute les actions : défile jusqu'à la première section présente, surligne toutes celles présentes. */
  function executerActions(actions) {
    if (restauration) return actionsAffichables(actions); // fil restauré : ni défilement ni surlignage
    var presentes = actionsSurlignage(actions).filter(function (a) {
      return document.getElementById(a.section_id);
    });
    presentes.forEach(function (a, indice) {
      var section = document.getElementById(a.section_id);
      if (indice === 0) defilerVers(section);
      surligner(section);
    });
    return actionsAffichables(actions); // les présentes, plus celles du dossier ouvert ailleurs (data-rapport)
  }

  // ---------------------------------------------------------------- affichage d'une réponse

  function blocSources(sources) {
    var items = [];
    (Array.isArray(sources) ? sources : []).forEach(function (s) {
      if (!s || typeof s !== "object") return;
      if (s.type === "rapport") {
        var libelle = s.section || s.section_id || "Le dossier";
        var lien = sectionAtteignable(s.section_id)
          ? lienSection(null, s.section_id, libelle, s.passage)
          : el("span", { classe: "cb-source-libelle", texte: libelle, title: s.passage || null });
        items.push(el("li", { classe: "cb-source cb-source--rapport" }, [
          lien,
          el("span", { classe: "cb-badge cb-badge--verifie", texte: "Dossier", title: "Vérifié par la rédaction" }),
        ]));
      } else if (s.type === "hemicycle") {
        var url = urlSure(s.url);
        var texte = s.libelle || s.titre || s.ref || "Données ouvertes de l’Assemblée";
        // Éditeur et licence restent accessibles au survol, sans ligne de texte en plus.
        var infos = [s.titre, [s.editeur, s.licence].filter(Boolean).join(" · ")].filter(Boolean).join("\n") || null;
        items.push(el("li", { classe: "cb-source cb-source--hemicycle" }, [
          url
            ? el("a", { href: url, target: "_blank", rel: "noopener", texte: texte, title: infos })
            : el("span", { classe: "cb-source-libelle", texte: texte, title: infos }),
          el("span", { classe: "cb-badge cb-badge--non-verifie", texte: "Non vérifié", title: "Hémicycle, non vérifié par la rédaction" }),
        ]));
      }
      // Autres types (ex. « indicateur ») : ignorés.
    });
    if (!items.length) return null;
    // Sources repliées par défaut : la réponse reste courte, le détail est à un clic.
    return el("details", { classe: "cb-sources" }, [
      el("summary", { classe: "cb-sources-titre", texte: "Sources (" + items.length + ")" }),
      el("ul", {}, items),
    ]);
  }

  function afficherReponse(donneesReponse) {
    var texte = el("div", { classe: "cb-texte" });
    texte.innerHTML = texteEnHtml(donneesReponse.reponse) || "<p>Pas de réponse.</p>";

    var actions = executerActions(donneesReponse.actions);
    var blocActions = actions.length
      ? el("div", { classe: "cb-actions" }, actions.map(function (a) {
        return lienSection("cb-lien-section", a.section_id, a.titre || "Voir dans le dossier", a.raison);
      }))
      : null;

    var reponse = el("div", { classe: "cb-msg cb-msg--reponse" }, [texte, blocActions, blocSources(donneesReponse.sources)]);
    ajouterAuFil(reponse);
    defilerFilVers(reponse);
  }

  // ---------------------------------------------------------------- appel au backend

  /** POST /chat/flux, lecture NDJSON. Renvoie `donnees` (le JSON de POST /chat). */
  async function poserAuServeur(question, historique, onEtape, signal) {
    var reponse;
    try {
      reponse = await fetch(API + "/chat/flux", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
        body: JSON.stringify({ mois: MOIS, question: question, historique: historiqueAEnvoyer(historique) }),
        signal: signal,
      });
    } catch (erreur) {
      if (erreur && erreur.name === "AbortError") throw erreur;
      throw new Error("Le service de questions ne répond pas. Réessayez dans un instant.");
    }
    if (!reponse.ok) {
      var corps = await reponse.json().catch(function () { return null; });
      throw new Error(messageHttp(reponse.status, corps));
    }
    if (!reponse.body || !reponse.body.getReader) throw new Error("Ce navigateur ne sait pas lire la réponse en flux.");

    var lecteur = reponse.body.getReader();
    var decodeur = new TextDecoder("utf-8");
    var tampon = "";

    function traiter(ligne) {
      var evenement;
      try {
        evenement = JSON.parse(ligne);
      } catch (e) {
        return null; // ligne illisible : ignorée
      }
      if (!evenement || typeof evenement !== "object") return null;
      if (evenement.type === "etape" && typeof evenement.message === "string") onEtape(evenement.message);
      else if (evenement.type === "reponse" && evenement.donnees) return { donnees: evenement.donnees };
      else if (evenement.type === "erreur") throw new Error(evenement.detail || "Le serveur n’a pas pu répondre.");
      // « appel » et types inconnus : ignorés.
      return null;
    }

    for (;;) {
      var lu = await lecteur.read();
      if (lu.done) break;
      var decoupe = decouperLignes(tampon, decodeur.decode(lu.value, { stream: true }));
      tampon = decoupe.reste;
      for (var i = 0; i < decoupe.lignes.length; i++) {
        var resultat = traiter(decoupe.lignes[i]);
        if (resultat) {
          lecteur.cancel().catch(function () {});
          return resultat.donnees;
        }
      }
    }
    tampon += decodeur.decode();
    if (tampon.trim()) {
      var fin = traiter(tampon);
      if (fin) return fin.donnees;
    }
    throw new Error("Connexion interrompue avant la réponse. Réessayez.");
  }

  // ---------------------------------------------------------------- une question

  var historique = [];
  var questionCourante = null; // { controleur, etape, abandonnee }

  function occupe(oui) {
    if (oui) panneau.setAttribute("aria-busy", "true");
    else panneau.removeAttribute("aria-busy");
    saisie.disabled = oui;
    envoyer.disabled = oui;
  }

  function retirer(element) {
    if (element && element.parentNode) element.parentNode.removeChild(element);
  }

  /** Abandonne la question en cours (« Annuler », nouvelle question, fermeture du panneau).
   *  Synchrone : le fil est à jour avant la suite (nouvelle question, fermeture). */
  function abandonner() {
    var q = questionCourante;
    if (!q) return;
    questionCourante = null;
    q.abandonnee = true;
    q.controleur.abort(); // le serveur annule la question et ne consomme plus de crédits
    retirer(q.etape);
    message("info", "Question annulée.");
    occupe(false);
  }

  async function poser(brute) {
    var question = String(brute || "").trim().slice(0, 1000);
    if (!question) return;
    abandonner();

    retirer(accueil);
    if (panneau.hidden) ouvrir();
    message("lecteur", question);
    saisie.value = "";

    var annuler = el("button", { type: "button", classe: "cb-annuler", texte: "Annuler" });
    var texteEtape = el("span", { classe: "cb-etape-texte", texte: "Envoi de la question…" });
    var courante = {
      controleur: new AbortController(),
      abandonnee: false,
      etape: el("div", { classe: "cb-etape" }, [
        el("span", { classe: "cb-indicateur", "aria-hidden": "true" }),
        texteEtape,
        annuler,
      ]),
    };
    annuler.addEventListener("click", function () {
      if (questionCourante !== courante) return;
      abandonner();
      saisie.focus();
    });
    questionCourante = courante;
    occupe(true);
    fil.appendChild(courante.etape);
    defilerFilEnBas();

    try {
      var donneesReponse = await poserAuServeur(question, historique, function (texte) {
        texteEtape.textContent = texte;
      }, courante.controleur.signal);
      if (courante.abandonnee) return;
      afficherReponse(donneesReponse);
      historique.push({ role: "user", contenu: question });
      historique.push({ role: "assistant", contenu: String(donneesReponse.reponse || "").slice(0, MAX_CONTENU_HISTORIQUE) });
      historique = historique.slice(-MAX_HISTORIQUE);
      apresReponse(donneesReponse); // enregistre le fil ; ouvre le dossier si la section n'est pas ici
    } catch (erreur) {
      if (courante.abandonnee) return; // « Question annulée. » déjà affiché
      message(erreur && erreur.name === "AbortError" ? "info" : "erreur",
        erreur && erreur.name === "AbortError" ? "Question annulée." : (erreur && erreur.message) || "Une erreur est survenue.");
      defilerFilEnBas();
    } finally {
      if (questionCourante === courante) {
        questionCourante = null;
        retirer(courante.etape);
        occupe(false);
        var actif = document.activeElement;
        if (!panneau.hidden && (!actif || actif === document.body || panneau.contains(actif))) {
          saisie.focus({ preventScroll: true });
        }
      }
    }
  }

  // ---------------------------------------------------------------- conversation conservée d'une page à l'autre
  //
  // sessionStorage (onglet courant) garde, par numéro : l'historique envoyé au serveur, le fil
  // affiché (questions, réponses brutes, messages) et une consigne en attente pour la page suivante
  // ({ouvrir: true, section: id}). Sans stockage disponible, tout marche, sans mémoire.

  var CLE_ETAT = "chapo-chatbot:" + MOIS;
  var CLE_VU = "chapo-chatbot:vu";
  var MAX_FIL = 60; // entrées du fil gardées
  var journal = []; // le fil affiché, dans l'ordre
  var attente = null; // consigne pour la page suivante
  var restauration = false; // vrai pendant la reconstruction du fil (aucun effet sur la page)
  var filARedescendre = false;

  function lireSession(cle) {
    try {
      var brut = window.sessionStorage.getItem(cle);
      return brut ? JSON.parse(brut) : null;
    } catch (e) {
      return null;
    }
  }

  function ecrireSession(cle, valeur) {
    try {
      window.sessionStorage.setItem(cle, JSON.stringify(valeur));
      return true;
    } catch (e) {
      return false;
    }
  }

  function etatSession(alleger) {
    return {
      v: 1,
      historique: historique,
      attente: attente,
      fil: journal.map(function (e) {
        if (!alleger || e.type !== "reponse") return e;
        var d = e.donnees || {};
        return { type: "reponse", donnees: { reponse: d.reponse, sources: d.sources, actions: d.actions } };
      }),
    };
  }

  function sauverSession() {
    // Réponses brutes ; si le quota est dépassé, version allégée (texte, sources, actions).
    if (!ecrireSession(CLE_ETAT, etatSession(false))) ecrireSession(CLE_ETAT, etatSession(true));
  }

  function journaliser(entree) {
    if (restauration) return;
    journal.push(entree);
    if (journal.length > MAX_FIL) journal = journal.slice(-MAX_FIL);
    sauverSession();
  }

  /** URL du dossier avec l'ancre, ou null (pas de data-rapport, ou on est déjà sur le dossier). */
  function urlRapport(id) {
    if (!RAPPORT) return null;
    try {
      var url = new URL(RAPPORT, window.location.href);
      if (url.pathname === window.location.pathname) return null;
      url.hash = id;
      return url.href;
    } catch (e) {
      return null;
    }
  }

  function sectionAtteignable(id) {
    return !!id && (!!document.getElementById(id) || !!urlRapport(id));
  }

  function hrefSection(id) {
    return document.getElementById(id) ? "#" + id : urlRapport(id) || "#" + id;
  }

  /** Actions de surlignage dont la section est ici, ou dans le dossier ouvert ailleurs. */
  function actionsAffichables(actions) {
    return actionsSurlignage(actions).filter(function (a) {
      return sectionAtteignable(a.section_id);
    });
  }

  /** Va sur le dossier, à la section `id`, en laissant la consigne d'ouvrir le panneau et de surligner. */
  function allerAuRapport(id, delai) {
    var url = urlRapport(id);
    if (!url) return false;
    attente = { ouvrir: true, section: id };
    sauverSession();
    setTimeout(function () {
      window.location.href = url;
    }, delai || 0);
    return true;
  }

  /** Après une réponse : l'enregistrer ; si sa section n'est pas sur cette page, ouvrir le dossier. */
  function apresReponse(donneesReponse) {
    journaliser({ type: "reponse", donnees: donneesReponse });
    var liste = actionsSurlignage(donneesReponse && donneesReponse.actions);
    var ici = liste.some(function (a) { return document.getElementById(a.section_id); });
    if (!liste.length || ici || !urlRapport(liste[0].section_id)) return;
    message("info", "Ouverture du rapport…");
    defilerFilEnBas();
    allerAuRapport(liste[0].section_id, 1000);
  }

  /** Le lanceur ne sautille que tant que le panneau n'a jamais été ouvert dans l'onglet. */
  function marquerVu() {
    document.documentElement.setAttribute("data-cb-vu", "1");
    ecrireSession(CLE_VU, 1);
  }

  function apresOuverture() {
    marquerVu();
    if (filARedescendre) {
      filARedescendre = false;
      defilerFilEnBas();
    }
  }

  /** Reconstruit le fil enregistré, sans défilement ni surlignage. Renvoie la consigne en attente. */
  function restaurerSession() {
    var etat = lireSession(CLE_ETAT);
    if (!etat || typeof etat !== "object") return null;
    if (Array.isArray(etat.historique)) {
      historique = etat.historique.filter(function (m) {
        return m && (m.role === "user" || m.role === "assistant") && typeof m.contenu === "string";
      }).slice(-MAX_HISTORIQUE);
    }
    var entrees = (Array.isArray(etat.fil) ? etat.fil : []).filter(function (e) {
      if (!e || typeof e !== "object") return false;
      if (e.type === "reponse") return !!e.donnees && typeof e.donnees === "object";
      return (e.type === "lecteur" || e.type === "info" || e.type === "erreur") && typeof e.texte === "string";
    });
    journal = [];
    if (entrees.length) retirer(accueil);
    restauration = true;
    try {
      entrees.forEach(function (e) {
        if (e.type === "reponse") afficherReponse(e.donnees);
        else message(e.type, e.texte);
        journal.push(e);
      });
    } catch (erreur) {
      // Une entrée illisible ne doit pas bloquer le widget.
    } finally {
      restauration = false;
    }
    filARedescendre = journal.length > 0;
    var derniere = journal[journal.length - 1];
    if (derniere && derniere.type === "lecteur") message("info", "Question interrompue par le changement de page.");
    return etat.attente && etat.attente.ouvrir ? etat.attente : null;
  }

  function initialiserSession() {
    var enAttente = restaurerSession();

    // Tout élément [data-chatbot-ouvrir] ouvre le panneau ; une valeur non vide est posée comme question.
    document.addEventListener("click", function (evenement) {
      var declencheur = evenement.target && evenement.target.closest && evenement.target.closest("[data-chatbot-ouvrir]");
      if (!declencheur || panneau.contains(declencheur)) return;
      evenement.preventDefault();
      var question = (declencheur.getAttribute("data-chatbot-ouvrir") || "").trim();
      if (question) poser(question);
      else ouvrir();
    });

    // Retour arrière (page ressortie du cache du navigateur) : le fil a pu continuer sur une autre
    // page ; on le relit pour ne pas renvoyer un historique périmé ni écraser l'état enregistré.
    window.addEventListener("pageshow", function (evenement) {
      if (!evenement.persisted) return;
      attente = null;
      Array.prototype.slice.call(fil.querySelectorAll(".cb-msg")).forEach(retirer);
      restaurerSession();
    });

    if (!enAttente) return;
    attente = null;
    sauverSession();
    ouvrir();
    var section = typeof enAttente.section === "string" && enAttente.section ? document.getElementById(enAttente.section) : null;
    if (section) {
      setTimeout(function () {
        defilerVers(section);
        surligner(section);
      }, 150);
    }
  }

  // Lanceur déjà vu dans cet onglet : pas de sautillement (posé avant l'injection du widget).
  if (lireSession(CLE_VU)) document.documentElement.setAttribute("data-cb-vu", "1");

  // ---------------------------------------------------------------- démarrage

  // N'injecte le widget qu'une fois sa feuille de style chargée (pas de lanceur sans style),
  // avec un repli si elle échoue ou tarde.
  function demarrer() {
    if (!feuilleStyle || feuilleStyle.sheet) return construire();
    var fait = false;
    function lancer() {
      if (fait) return;
      fait = true;
      construire();
    }
    feuilleStyle.addEventListener("load", lancer);
    feuilleStyle.addEventListener("error", lancer);
    setTimeout(lancer, 3000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
  else demarrer();
})();
