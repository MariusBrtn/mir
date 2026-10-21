"""
MIR Flow : à gauche la bibliothèque de nœuds ; au centre le graphe et les réglages du nœud choisi ; à droite le robot
simulé en 3D et la discussion (ce que fait le programme, ce que répond le LLM).
Ctrl+Z / Ctrl+Maj+Z annulent et rétablissent les modifications du graphe ; Ctrl+0 ajuste la vue.
"""
from __future__ import annotations
import html
import json
import time
from PySide6.QtCore import QPoint, QPointF, Qt, QSize, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)
from mir_flow.graph import Graph
from mir_flow.runner import FlowEvent
from mir_robot_editor.flow.node_data_view import DataCatalog, NodeDataView, describe
from mir_robot_editor.flow.node_palette import NodePalette
from mir_robot_editor.flow.scope_window import ScopeWindow
from mir_robot_editor.flow.flow_view_model import FlowViewModel, FlowVMAction
from mir_robot_editor.flow.graph_editor import GraphEditor
from mir_robot_editor.flow.node_inspector import InspectorContext, NodeInspector
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_utils.ui import theme
from mir_utils.ui.widgets import DialogFooter, DialogHeader, Section, dialog_frame, mono_font
from mir_robot_editor.flow.node_icons import CATEGORY_COLORS, icon_color, icon_pixmap
from mir_utils.ui.view_base import ViewBase

RESULTAT_MAX = 300          # caractères d'un résultat affichés dans la discussion (le modèle reçoit tout)


class FlowView(QWidget, ViewBase[FlowViewModel, FlowVMAction]):
    def __init__(self, parent, view_model: FlowViewModel):
        super().__init__(parent, view_model=view_model)  # type: ignore
        vm = self._view_model
        vm.robot_changed.connect(self._on_robot_changed)
        vm.graph_loaded.connect(self._on_graph_loaded)
        vm.busy_state_changed.connect(lambda _: self._update_buttons())
        vm.account_changed.connect(self._update_account)
        vm.event.connect(self._on_event)
        self._simulation = False

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._make_graph_side())
        droite = QSplitter(Qt.Orientation.Vertical)
        self._viewport = MujocoWidget()
        droite.addWidget(self._viewport)
        droite.addWidget(self._make_chat())
        droite.setSizes([300, 400])
        splitter.addWidget(droite)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([650, 430])
        root.addWidget(splitter, 1)

        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)
        self._update_account()
        self._on_graph_loaded()
        self._on_robot_changed()

    # ------------------------------------------------------------------ construction
    def _make_graph_side(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        barre = QHBoxLayout()
        barre.setSpacing(4)
        titre = QLabel("MIR Flow")
        titre.setStyleSheet("font-weight: bold; font-size: 15px; margin-right: 8px;")
        barre.addWidget(titre)

        voir_tout = QPushButton("Voir tout")
        voir_tout.setToolTip("Recentrer le graphe (Ctrl+0). Zoom : Ctrl + molette ou pincement. Annuler : Ctrl+Z. "
                             "Supprimer : touche Suppr ou clic droit.")
        voir_tout.clicked.connect(lambda: self.graph.fit())
        barre.addWidget(voir_tout)
        barre.addStretch(1)
        self.btn_lancer = QPushButton(self._icon("play"), "Lancer")
        self.btn_lancer.setToolTip("Exécute le programme depuis le nœud Départ")
        self.btn_lancer.clicked.connect(self._on_lancer)
        barre.addWidget(self.btn_lancer)
        self.btn_arreter_flux = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_arreter_flux.clicked.connect(self._view_model.arreter)
        barre.addWidget(self.btn_arreter_flux)
        layout.addLayout(barre)

        horizontal = QSplitter(Qt.Orientation.Horizontal)
        self.palette = NodePalette()
        self.palette.add_requested.connect(self._ajouter)
        horizontal.addWidget(self.palette)
        self.graph = GraphEditor()
        self.graph.selection_changed.connect(self._on_node_selected)
        self.graph.graph_changed.connect(self._on_graph_changed)
        self.graph.node_dropped.connect(lambda t, c, pos: self._ajouter(t, c, pos))
        self.graph.node_double_clicked.connect(self._open_settings)
        self.graph.scope_requested.connect(lambda node: self._scope_window(node, show=True))
        self._scopes: dict[str, ScopeWindow] = {}       # fenêtres des nœuds Scope (id du nœud -> fenêtre)
        self._scopes_fermes: set[str] = set()           # fermées par l'utilisateur pendant ce lancement
        horizontal.addWidget(self.graph)
        # réglages d'un nœud : fenêtre ouverte par un double-clic (le graphe se met à jour pendant qu'on règle)
        self.inspector = NodeInspector()
        self.inspector.changed.connect(self._on_node_changed)
        self._settings = QDialog(self)
        self._settings.setModal(False)
        self._settings.resize(1100, 640)
        self._settings_header = DialogHeader("")
        self._settings_footer = DialogFooter()
        self._settings_footer.add_button("Fermer", lambda: self._settings.close())
        boite = dialog_frame(self._settings, self._settings_header, self._settings_footer, margins=(0, 0, 0, 0),
                             scroll=False)
        colonnes = QSplitter(Qt.Orientation.Horizontal)
        # comme dans n8n : ce que le nœud a reçu | ses réglages | ce qu'il a produit, au dernier passage
        gauche = QSplitter(Qt.Orientation.Vertical)
        self.catalog = DataCatalog()
        self.catalog.chosen.connect(self._insert_data_name)
        gauche.addWidget(self.catalog)
        self.data_in = NodeDataView("Entrée")
        gauche.addWidget(self.data_in)
        gauche.setSizes([260, 300])
        colonnes.addWidget(gauche)
        self._last_field = None                 # dernier champ de réglage où l'on a écrit (pour y insérer un nom)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.inspector)
        colonnes.addWidget(scroll)
        self.data_out = NodeDataView("Sortie")
        colonnes.addWidget(self.data_out)
        colonnes.setStretchFactor(1, 1)
        colonnes.setSizes([280, 520, 280])
        boite.addWidget(colonnes, 1)
        self._io_timer = QTimer(self)
        self._io_timer.setSingleShot(True)
        self._io_timer.setInterval(300)         # au plus 3 mises à jour par seconde (chaînes en continu)
        self._io_timer.timeout.connect(self._show_io)
        self._view_model.io_changed.connect(self._on_io_changed)
        self._pending_edit: str | None = None
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(300)       # après la dernière frappe
        self._edit_timer.timeout.connect(self._flush_edit)
        horizontal.setStretchFactor(1, 1)
        horizontal.setSizes([210, 600])
        layout.addWidget(horizontal, 1)
        self.lbl_problemes = QLabel()
        self.lbl_problemes.setWordWrap(True)
        layout.addWidget(self.lbl_problemes)

        # raccourcis : sur toute la page MIR Flow, sauf quand on écrit dans un champ (il garde son propre Ctrl+Z)
        for sequence, action in ((QKeySequence.StandardKey.Undo, self._undo), (QKeySequence.StandardKey.Redo, self._redo),
                                 (QKeySequence("Ctrl+0"), lambda: self.graph.fit()),
                                 (QKeySequence.StandardKey.ZoomIn, lambda: self.graph.zoom(1.2)),
                                 (QKeySequence.StandardKey.ZoomOut, lambda: self.graph.zoom(1 / 1.2))):
            raccourci = QShortcut(sequence, self.graph)
            raccourci.setContext(Qt.ShortcutContext.WidgetShortcut)
            raccourci.activated.connect(action)
        self._history: list[str] = []
        self._future: list[str] = []
        self._last_edit: tuple[str, float] | None = None
        return panel

    def _make_chat(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        haut = QHBoxLayout()
        self.cb_llm = QComboBox()
        self.cb_llm.setToolTip("Le nœud LLM avec qui vous discutez")
        self.cb_llm.currentIndexChanged.connect(lambda _: self._view_model.set_chat_llm(self.cb_llm.currentData()))
        haut.addWidget(self.cb_llm)
        self.lbl_compte = QLabel()
        self.lbl_compte.setObjectName("Muted")
        haut.addWidget(self.lbl_compte, 1)
        self.btn_compte = QPushButton("Compte")
        self.btn_compte.clicked.connect(self._on_compte)
        haut.addWidget(self.btn_compte)
        layout.addLayout(haut)

        self.discussion = QTextBrowser()
        self.discussion.setOpenExternalLinks(True)
        layout.addWidget(self.discussion, 1)
        self.saisie = QPlainTextEdit()
        self.saisie.setPlaceholderText("Message au LLM (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)")
        self.saisie.setFixedHeight(60)
        self.saisie.installEventFilter(self)
        layout.addWidget(self.saisie)

        boutons = QHBoxLayout()
        self.btn_envoyer = QPushButton(self._icon("play"), "Envoyer")
        self.btn_envoyer.setIconSize(QSize(20, 20))
        self.btn_envoyer.clicked.connect(self._on_envoyer)
        boutons.addWidget(self.btn_envoyer)
        self.btn_arreter = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_arreter.setIconSize(QSize(20, 20))
        self.btn_arreter.setToolTip("Interrompt le LLM et l'action en cours, et arrête les moteurs")
        self.btn_arreter.clicked.connect(self._view_model.arreter)
        boutons.addWidget(self.btn_arreter)
        boutons.addStretch(1)
        self.btn_contexte = QPushButton("Ce que sait le LLM")
        self.btn_contexte.setToolTip("La description du robot donnée au LLM, générée à partir de sa configuration")
        self.btn_contexte.clicked.connect(self._on_contexte)
        boutons.addWidget(self.btn_contexte)
        self.btn_nouvelle = QPushButton("Effacer")
        self.btn_nouvelle.setToolTip("Nouvelle discussion")
        self.btn_nouvelle.clicked.connect(self._on_nouvelle)
        boutons.addWidget(self.btn_nouvelle)
        layout.addLayout(boutons)
        return panel

    def eventFilter(self, obj, event):
        if obj is self.saisie and event.type() == event.Type.KeyPress and \
                event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._on_envoyer()
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ graphe
    def _on_graph_loaded(self):
        self._settings.close()
        self._close_scopes()
        self.graph.set_graph(self._view_model.graph)
        self._history, self._future, self._last_edit = [self._snapshot()], [], None
        self._refresh_inspector_context()
        self._update_graph_state()

    def _refresh_inspector_context(self, refresh: bool = False):
        self.inspector.set_context(InspectorContext(**self._view_model.inspector_lists(refresh)))

    def _on_node_selected(self, node):
        if node is not None and self._settings.isVisible():
            self._open_settings(node)               # la fenêtre de réglages suit le nœud choisi

    def _open_settings(self, node):
        self._settings.setWindowTitle(f"Réglages · {node.spec.label} « {node.name} »")
        couleur = CATEGORY_COLORS.get(node.spec.category, theme.INK)
        self._settings_header.set_content(node.name, node.spec.summary, kind=f"{node.spec.category} · {node.spec.label}",
                                          tile_color=couleur)
        self._settings_header.title_label().setFont(mono_font(18))
        self._settings_header.set_tile_pixmap(icon_pixmap(node.type, 22, icon_color(node.spec.category)), couleur)
        self.inspector.set_node(node, self._view_model.graph)
        self._show_io()
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _on_node_changed(self, node_id: str):
        """Un réglage modifié (à chaque frappe) : le nœud se redessine tout de suite ; l'enregistrement, l'historique
        et la vérification du graphe attendent que l'on s'arrête de taper."""
        self.graph.refresh_node(node_id)
        self._pending_edit = node_id
        self._edit_timer.start()

    def _flush_edit(self):
        if self._pending_edit is not None:
            node_id, self._pending_edit = self._pending_edit, None
            self._on_graph_changed(node_id)

    def _on_graph_changed(self, edited_node: str | None = None):
        if edited_node is None and self._pending_edit is not None:
            self._edit_timer.stop()
            self._flush_edit()              # une modification de réglage en attente passe avant
        if self._settings.isVisible() and self.inspector._node not in self._view_model.graph.nodes:
            self._settings.close()          # le nœud réglé vient d'être supprimé
        self._close_scopes({n.id for n in self._view_model.graph.nodes if n.type == "scope"})
        self._view_model.save_graph()
        self._remember(edited_node)
        self._update_graph_state()

    # ------------------------------------------------------------------ annuler / rétablir
    def _snapshot(self) -> str:
        return json.dumps(self._view_model.graph.to_dict(), sort_keys=True)

    def _remember(self, edited_node: str | None):
        """Garde l'état du graphe pour Ctrl+Z. Les réglages d'un même nœud tapés à la suite (moins d'une seconde
        d'écart) comptent pour une seule modification."""
        state = self._snapshot()
        if self._history and self._history[-1] == state:
            return
        now = time.monotonic()
        grouped = edited_node is not None and self._last_edit is not None and self._last_edit[0] == edited_node \
            and now - self._last_edit[1] < 1.0 and len(self._history) > 1
        if grouped:
            self._history[-1] = state
        else:
            self._history.append(state)
            del self._history[:-200]
        self._last_edit = (edited_node, now) if edited_node is not None else None
        self._future.clear()

    def _undo(self):
        self._edit_timer.stop()
        self._flush_edit()              # la frappe en cours compte comme une modification
        if len(self._history) > 1 and not self._view_model.is_running():
            self._future.append(self._history.pop())
            self._restore(self._history[-1])

    def _redo(self):
        self._edit_timer.stop()
        self._flush_edit()              # la frappe en cours compte comme une modification
        if self._future and not self._view_model.is_running():
            self._history.append(self._future.pop())
            self._restore(self._history[-1])

    def _restore(self, state: str):
        self._settings.close()              # le nœud réglé n'existe peut-être plus
        selected = self.graph.selected_node()
        self._view_model.graph = Graph.from_dict(json.loads(state))
        self._view_model.save_graph()
        self._last_edit = None
        self.graph.set_graph(self._view_model.graph, keep_view=True, select=selected.id if selected else None)
        self._update_graph_state()

    # ------------------------------------------------------------------ données du dernier passage
    def _on_io_changed(self, node_id: str):
        # n'importe quel nœud : la liste des données disponibles change aussi
        if self._settings.isVisible() and self.inspector._node is not None and not self._io_timer.isActive():
            self._io_timer.start()

    def _on_focus_changed(self, _old, new):
        if isinstance(new, (QLineEdit, QPlainTextEdit)) and self.inspector.isAncestorOf(new):
            self._last_field = new

    def _insert_data_name(self, name: str, key: str):
        """Insère le nom d'une donnée dans le dernier champ utilisé : expression (carte.image) ou script
        (donnees["carte"]["image"])."""
        field = self._last_field
        if field is None or not self.inspector.isAncestorOf(field) or not field.isEnabled():
            QApplication.clipboard().setText(f"{name}.{key}" if key else name)
            self.lbl_problemes.setText(f"« {name}.{key if key else ''} » copié : collez-le dans un champ (Cmd+V).")
            return
        if isinstance(field, QLineEdit):
            field.insert(f"{name}.{key}" if key else name)
        else:
            if name == "entree":
                text = f'entree["{key}"]' if key else "entree"
            else:
                text = f'donnees["{name}"]' + (f'["{key}"]' if key else "")
            field.insertPlainText(text)
        field.setFocus()

    def _catalog_entries(self, node, io) -> list:
        """Les données qu'un nœud peut lire : son entrée, puis le résultat de chaque autre nœud (dernier passage)."""
        entries = []
        if node.spec.has_input and io is not None:
            entries.append(("entree", {k: describe(v) for k, v in io["entree"].items()}))
        for other in self._view_model.graph.nodes:
            if other.id == node.id or other.type in ("start", "continuous", "trigger", "end", "message"):
                continue
            last = self._view_model.last_io.get(other.id)
            entries.append((other.name, {k: describe(v) for k, v in last["sortie"].items()} if last else None))
        return entries

    def _show_io(self):
        node = self.inspector._node
        if node is None:
            return
        io = self._view_model.last_io.get(node.id)
        self.catalog.set_entries(self._catalog_entries(node, io))
        if io is None:
            self.data_in.show_data(None, None)
            self.data_out.show_data(None, None)
            return
        info = {"time": io["time"], "port": io["port"], "multiple_outputs": len(node.outputs) > 1}
        if node.spec.has_input:
            self.data_in.show_data(io["entree"], {"time": io["time"]})
        else:
            self.data_in.show_data(None, None, "Ce nœud n'a pas d'entrée : une chaîne commence ici.")
        self.data_out.show_data(io["sortie"], info)

    def _update_graph_state(self):
        problemes = self._view_model.problems()
        if problemes:
            self.lbl_problemes.setText(" ".join(problemes))
            self.lbl_problemes.setStyleSheet(f"color: {theme.ERROR};")
        else:
            self.lbl_problemes.setText("Double-cliquez sur un nœud pour le régler. Ajoutez des nœuds depuis la "
                                       "bibliothèque (clic ou glisser).")
            self.lbl_problemes.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        if self._settings.isVisible() and self.inspector._node is not None:
            self._settings.setWindowTitle(f"Réglages · {self.inspector._node.spec.label} "
                                          f"« {self.inspector._node.name} »")
        # discussion : avec quel LLM (liste seulement s'il y en a plusieurs)
        llms = self._view_model.graph.llms()
        courant = self._view_model.chat_llm_id
        self.cb_llm.blockSignals(True)
        self.cb_llm.clear()
        for node in llms:
            self.cb_llm.addItem(f"Discuter avec {node.name}", node.id)
        self.cb_llm.setCurrentIndex(max(0, self.cb_llm.findData(courant)))
        self.cb_llm.blockSignals(False)
        self.cb_llm.setVisible(len(llms) > 1)
        # sans nœud LLM, pas de discussion : il ne reste que le journal du programme
        for w in (self.lbl_compte, self.btn_compte, self.saisie, self.btn_envoyer, self.btn_arreter,
                  self.btn_contexte):
            w.setVisible(bool(llms))
        lists = self._view_model.inspector_lists()
        contenu = (tuple(lists["cameras"]), tuple(lists["lidars"]), self._view_model.graph.start() is not None)
        if contenu != getattr(self, "_palette_contenu", None):       # la bibliothèque ne change que rarement
            self._palette_contenu = contenu
            self.palette.refresh(*contenu)

    def _ajouter(self, node_type: str, sensor: str | None = None, at: QPointF | None = None):
        """Un nœud de la bibliothèque : clic (à côté du nœud choisi, relié) ou glisser (à l'endroit du dépôt)."""
        if self._view_model.is_running():
            return
        node = self.graph.add_node(node_type, at)
        if node is not None and node.type == "measure" and not node.config.get("source"):
            # une seule source possible (ex. pas de caméra ni de lidar) : choisie d'office
            lists = self._view_model.inspector_lists()
            if not lists["cameras"] and not lists["lidars"]:
                node.config["source"] = "servos"
                self.graph.refresh_node(node.id)
                self._view_model.save_graph()
                self._history[-1] = self._snapshot()

    # ------------------------------------------------------------------ robot et simulation
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
        self._update_3d()

    def _update_3d(self):
        world = self._view_model.sim_world() if self._simulation else None
        self._viewport.setVisible(world is not None)
        if world is None:
            self._timer_3d.stop()
            return
        self._viewport.set_sim_world(world)
        self._timer_3d.start()

    def close_3d(self):
        self._timer_3d.stop()
        self._viewport.show_message("")

    def _on_robot_changed(self):
        self._update_3d()
        self._refresh_inspector_context()
        self._update_graph_state()          # capteurs absents du robot
        self._update_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_inspector_context(refresh=True)       # politiques entraînées entre-temps

    # ------------------------------------------------------------------ discussion
    def _on_envoyer(self):
        texte = self.saisie.toPlainText().strip()
        if texte and self._view_model.send(texte):
            self._ajouter_texte(f"<p style='margin-top:10px'><b>Vous</b><br>{_html(texte)}</p>")
            self.saisie.clear()

    def _scope_window(self, node, show: bool = False) -> ScopeWindow:
        window = self._scopes.get(node.id)
        if window is None:
            window = self._scopes[node.id] = ScopeWindow(self, f"Scope · {node.name}")
            window.move(self.mapToGlobal(self.rect().topLeft()) + QPoint(80 + 30 * len(self._scopes),
                                                                       80 + 30 * len(self._scopes)))
            window.closeEvent = lambda event, i=node.id: (self._scopes_fermes.add(i), event.accept())
        window.setWindowTitle(f"Scope · {node.name}")
        if show:
            self._scopes_fermes.discard(node.id)
            window.show()
            window.raise_()
        return window

    def _on_scope(self, event: FlowEvent):
        node = self._view_model.graph.node(event.data["id"])
        if node is None:
            return
        window = self._scope_window(node, show=node.id not in self._scopes_fermes
                                    and not (node.id in self._scopes and self._scopes[node.id].isVisible()))
        if event.data.get("erreur"):
            window.show_error(event.data["erreur"])
            return
        window.push(event.data["value"], event.data["temps"], "automatique",
                    float(node.config.get("history_s") or 30), node.name)

    def _close_scopes(self, keep: set[str] | None = None):
        for node_id in list(self._scopes):
            if keep is None or node_id not in keep:
                self._scopes.pop(node_id).deleteLater()

    def _on_lancer(self):
        self._edit_timer.stop()
        self._flush_edit()
        for window in self._scopes.values():
            window.reset()
        self._scopes_fermes.clear()
        if self._view_model.run_flow():
            self._ajouter_texte(f"<p style='margin-top:10px; color:{theme.OK}'><b>▶ Flux lancé</b></p>")

    def _on_event(self, event: FlowEvent):
        if event.kind == "scope":
            self._on_scope(event)
        elif event.kind == "node":
            self.graph.set_active(event.data.get("id"))
        elif event.kind == "step":
            self._ajouter_texte(f"<div style='color:{theme.TEXT_MUTED}; font-family:monospace; font-size:11px'>"
                                f"{_html(event.text)}</div>")
        elif event.kind == "trigger":
            self._ajouter_texte(f"<p style='color:{theme.WARNING}'><b>⚡ Quand</b> {_html(event.text)}</p>")
        elif event.kind == "message":
            self._ajouter_texte(f"<p><b>Message</b><br>{_html(event.text)}</p>")
        elif event.kind == "end":
            self.graph.set_active(None)
            self._ajouter_texte(f"<p style='color:{theme.OK}'><b>■ Flux terminé</b> : {_html(event.text)}</p>")
        elif event.kind == "call":
            self._ajouter_texte(f"<div style='color:{theme.SLATE}; font-family:monospace'>→ {_html(event.text)}</div>")
        elif event.kind == "result":
            texte = event.text if len(event.text) <= RESULTAT_MAX else event.text[:RESULTAT_MAX] + " …"
            couleur = theme.ERROR if event.text.startswith("Error") else theme.TEXT_MUTED
            self._ajouter_texte(f"<div style='color:{couleur}; font-family:monospace; font-size:11px'>"
                          f"&nbsp;&nbsp;{_html(texte)}</div>")
        elif event.kind == "reply":
            self._ajouter_texte(f"<p><b>Robot</b><br>{_html(event.text)}</p>")
        elif event.kind == "error":
            self._ajouter_texte(f"<p style='color:{theme.ERROR}'>{_html(event.text)}</p>")

    def _ajouter_texte(self, fragment: str):
        self.discussion.append(fragment)
        barre = self.discussion.verticalScrollBar()
        barre.setValue(barre.maximum())

    def _on_nouvelle(self):
        self._view_model.new_conversation()
        self.discussion.clear()

    def _on_contexte(self):
        dialogue = QDialog(self)
        dialogue.setWindowTitle("Ce que sait le LLM")
        dialogue.resize(760, 620)
        layout = QVBoxLayout(dialogue)
        aide = QLabel("Description du robot ajoutée aux instructions du nœud LLM. Elle est générée à partir de la "
                      "configuration du robot (structure, moteurs, capteurs) : modifier le robot la met à jour. "
                      "Le LLM voit aussi le nom et la description de chaque outil branché sous lui.")
        aide.setWordWrap(True)
        aide.setObjectName("Muted")
        layout.addWidget(aide)
        texte = QPlainTextEdit(self._view_model.robot_context() or "Pas de robot.")
        texte.setReadOnly(True)
        layout.addWidget(texte, 1)
        fermer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        fermer.rejected.connect(dialogue.reject)
        layout.addWidget(fermer)
        dialogue.exec()

    # ------------------------------------------------------------------ compte
    def _on_compte(self):
        CompteDialog(self, self._view_model).exec()

    def _update_account(self):
        self.lbl_compte.setText(self._view_model.account_text())
        self._update_buttons()

    def _update_buttons(self):
        if not hasattr(self, "btn_envoyer"):
            return
        vm = self._view_model
        busy = vm.is_running()
        self.btn_envoyer.setEnabled(not busy and vm.has_robot() and vm.has_api_key())
        if not vm.has_api_key():
            tip = "Connectez d'abord votre compte OpenAI (bouton « Compte »)"
        elif not vm.has_robot():
            tip = "Pas de robot : connectez le robot réel, ou utilisez le robot simulé"
        else:
            tip = "Envoyer le message au LLM, qui appelle ses outils"
        self.btn_envoyer.setToolTip(tip)
        self.btn_arreter.setEnabled(busy)
        self.btn_nouvelle.setEnabled(not busy)
        self.btn_contexte.setEnabled(vm.has_robot())
        # pendant qu'un message est traité, le graphe ne change pas
        for w in (self.palette, self.inspector, self.cb_llm):
            w.setEnabled(not busy)
        self.graph.set_read_only(busy)          # pendant l'exécution, on peut toujours ouvrir un nœud pour le regarder
        if not busy:
            self.btn_lancer.setEnabled(not busy and vm.has_robot())
        self.btn_lancer.setToolTip("Exécute le programme depuis le nœud Départ" if vm.has_robot() else
                                   "Pas de robot : connectez le robot réel, ou utilisez le robot simulé")
        self.btn_arreter_flux.setEnabled(busy)


class CompteDialog(QDialog):
    """Connexion au compte OpenAI : la clé API est vérifiée puis rangée dans le trousseau du système."""

    def __init__(self, parent, view_model: FlowViewModel):
        super().__init__(parent)
        self._vm = view_model
        self.setWindowTitle("Compte OpenAI")
        self.setMinimumWidth(560)
        footer = DialogFooter()
        self.btn_oublier = QPushButton("Oublier la clé")
        self.btn_oublier.setAutoDefault(False)
        self.btn_oublier.setToolTip("Retire la clé du trousseau de cet ordinateur")
        self.btn_oublier.clicked.connect(self._on_oublier)
        footer.add_left(self.btn_oublier)
        footer.add_button("Fermer", self.accept)
        layout = dialog_frame(self, DialogHeader("Compte OpenAI", "Le nœud LLM de MIR Flow utilise votre propre "
                                                 "compte OpenAI.", icon="enter"), footer, scroll=False)
        aide = QLabel("Créez une clé API sur "
                      "<a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>, puis "
                      "collez-la ici. Les demandes au modèle sont facturées sur votre compte.")
        aide.setWordWrap(True)
        aide.setOpenExternalLinks(True)
        layout.addWidget(aide)
        section = Section("Clé API")
        ligne = QHBoxLayout()
        self.champ = QLineEdit()
        self.champ.setEchoMode(QLineEdit.EchoMode.Password)
        self.champ.setPlaceholderText("sk-…")
        self.champ.setFont(mono_font())
        ligne.addWidget(self.champ, 1)
        self.btn_enregistrer = QPushButton("Vérifier et enregistrer")
        self.btn_enregistrer.setObjectName("Primary")
        self.btn_enregistrer.setDefault(True)
        self.btn_enregistrer.clicked.connect(self._on_enregistrer)
        ligne.addWidget(self.btn_enregistrer)
        section.body.addLayout(ligne)
        self.lbl_etat = QLabel()
        self.lbl_etat.setWordWrap(True)
        section.body.addWidget(self.lbl_etat)
        layout.addWidget(section)
        securite = QLabel("La clé est rangée dans le trousseau sécurisé de votre ordinateur (Trousseau d'accès sur "
                          "macOS, Gestionnaire d'identification sur Windows) : elle n'est jamais écrite dans les "
                          "fichiers de MIR ni dans les robots que vous partagez.")
        securite.setObjectName("Muted")
        securite.setWordWrap(True)
        layout.addWidget(securite)
        layout.addStretch(1)
        self._update()

    def _update(self, message: str = "", erreur: bool = False):
        etat = self._vm.account_text()
        if self._vm.key_from_environment():
            etat += " : la variable d'environnement est prioritaire sur le trousseau."
        self.lbl_etat.setText(message or etat)
        self.lbl_etat.setStyleSheet(f"color: {theme.ERROR if erreur else theme.TEXT_MUTED};")
        self.btn_oublier.setEnabled(self._vm.has_api_key() and not self._vm.key_from_environment())

    def _on_enregistrer(self):
        self.lbl_etat.setText("Vérification auprès d'OpenAI…")
        self.repaint()
        erreur = self._vm.save_api_key(self.champ.text())
        self.champ.clear()
        if erreur:
            self._update(erreur, erreur=True)
        else:
            self._update("✓ Clé vérifiée et enregistrée dans le trousseau.")

    def _on_oublier(self):
        self._vm.delete_api_key()
        self._update("Clé retirée du trousseau.")


def _html(texte: str) -> str:
    return html.escape(texte).replace("\n", "<br>")
