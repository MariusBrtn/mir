"""
Réglages du nœud choisi dans le graphe d'un MIR Flow. Chaque modification est écrite tout de suite dans la
configuration du nœud (signal changed : le graphe est alors enregistré).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)
from mir_flow.agent import MODELS
from mir_flow.graph import (EDGE_TOOL, KINDS, KIND_SETPOINT, NAME, NODE_ACTION, NODE_LLM, QUANTITIES, SOURCE_SERVOS,
                            Graph, Node)
from mir_flow.runner import load_process
from mir_flow.tools import load_script
from mir_utils.ui import theme
from mir_utils.ui.code_editor import PythonCodeEditor


def python_editor(text: str = "", height: int = 220) -> PythonCodeEditor:
    """Éditeur de code Python de MIR (celui de l'onglet Scripts) : coloration, numéros de ligne, indentation."""
    editor = PythonCodeEditor()
    editor.setTheme("light")
    editor.setLineWrapMode(PythonCodeEditor.LineWrapMode.NoWrap)
    editor.setPlainText(text)
    editor.setMinimumHeight(height)
    return editor


@dataclass
class InspectorContext:
    """Ce que le robot ouvert propose : consignes, observations, politiques entraînées, préréglages."""
    actions: dict[str, Any] = field(default_factory=dict)            # nom -> DeviceAction
    observables: list[str] = field(default_factory=list)
    default_observables: list[str] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)     # model_info, "path" relatif au dossier du robot
    presets: dict[str, dict[str, float]] = field(default_factory=dict)
    cameras: list[str] = field(default_factory=list)
    lidars: list[str] = field(default_factory=list)


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


class NodeInspector(QWidget):
    changed = Signal(str)               # id du nœud modifié

    def __init__(self, parent=None):
        super().__init__(parent)
        self._node: Node | None = None
        self._graph: Graph | None = None
        self._ctx = InspectorContext()
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self._title = QLabel()
        self._title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title)
        self._pages = QStackedWidget()
        self._empty = _muted("Choisissez un nœud du graphe pour le régler.\n\n"
                             "« Ajouter » place un nœud à droite du nœud choisi et le relie à sa sortie. Un flux part "
                             "du nœud Départ (« Lancer le flux ») ; reliez une sortie (à droite) à l'entrée d'un "
                             "autre nœud (à gauche). Les outils (losange en haut) se branchent sous un LLM.")
        self._pages.addWidget(self._empty)
        self._pages.addWidget(self._make_llm())
        self._pages.addWidget(self._make_action())
        self._generic = QWidget()
        self._pages.addWidget(self._generic)
        layout.addWidget(self._pages, 1)
        self._name_editor: QLineEdit | None = None
        self.set_node(None, None)

    # ------------------------------------------------------------------ pages
    def _make_llm(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.llm_name = QLineEdit()
        self.llm_name.textChanged.connect(self._on_name)
        form.addRow("Nom", self.llm_name)
        self.llm_model = QComboBox()
        self.llm_model.setEditable(True)
        self.llm_model.addItems(MODELS)
        self.llm_model.currentTextChanged.connect(lambda t: self._set("model", t.strip()))
        form.addRow("Modèle OpenAI", self.llm_model)
        self.llm_instructions = QPlainTextEdit()
        self.llm_instructions.setPlaceholderText("Rôle, règles du jeu, ton… (le message système du modèle)")
        self.llm_instructions.textChanged.connect(lambda: self._set("instructions",
                                                                    self.llm_instructions.toPlainText()))
        form.addRow("Instructions", self.llm_instructions)
        self.llm_prompt = QPlainTextEdit()
        self.llm_prompt.setFixedHeight(70)
        self.llm_prompt.setPlaceholderText("Message reçu quand le flux arrive sur ce nœud, ex. : Le lidar mesure "
                                           "{script.valeur}. Que fais-tu ?")
        self.llm_prompt.textChanged.connect(lambda: self._set("prompt", self.llm_prompt.toPlainText()))
        form.addRow("Dans le flux", self.llm_prompt)
        self.llm_describe = QCheckBox("Décrire le robot au modèle (modules, actionneurs, capteurs)")
        self.llm_describe.toggled.connect(lambda v: self._set("describe_robot", v))
        form.addRow(self.llm_describe)
        form.addRow(_muted("Le modèle n'agit sur le robot qu'à travers les outils branchés sous lui : il voit leur nom "
                           "et leur description."))
        return page

    def _make_tool_header(self, form: QFormLayout, prefix: str):
        name = QLineEdit()
        name.setToolTip("Nom de l'outil vu par le modèle : lettres, chiffres, _ ou -, sans espace (ex. avancer)")
        name.textChanged.connect(self._on_name)
        form.addRow("Nom", name)
        description = QPlainTextEdit()
        description.setFixedHeight(60)
        description.setPlaceholderText("Ce que fait l'outil et quand l'utiliser : c'est ce que lit le modèle")
        description.textChanged.connect(lambda: self._set("description", description.toPlainText()))
        form.addRow("Description", description)
        setattr(self, f"{prefix}_name", name)
        setattr(self, f"{prefix}_description", description)
        setattr(self, f"{prefix}_form", form)

    def _make_action(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self._make_tool_header(form, "action")
        self.action_kind = QComboBox()
        for kind, label in KINDS.items():
            self.action_kind.addItem(label, kind)
        self.action_kind.currentIndexChanged.connect(self._on_kind)
        form.addRow("Sorte", self.action_kind)
        self.action_duration = QDoubleSpinBox()
        self.action_duration.setRange(0.1, 600)
        self.action_duration.setSuffix(" s")
        self.action_duration.setToolTip("Durée de l'action à chaque appel par le LLM (au plus, pour un script ou "
                                        "une politique qui s'arrête d'elle-même)")
        self.action_duration.valueChanged.connect(lambda v: self._set("duration_s", v))
        form.addRow("Durée", self.action_duration)
        self._action_main_form = form
        layout.addLayout(form)

        self.action_pages = QStackedWidget()
        # consigne
        consigne = QWidget()
        c = QVBoxLayout(consigne)
        c.setContentsMargins(0, 0, 0, 0)
        self.preset = QComboBox()
        self.preset.activated.connect(self._on_preset)
        c.addWidget(self.preset)
        self.setpoint_grid = QGridLayout()
        c.addLayout(self.setpoint_grid)
        c.addWidget(_muted("Valeurs envoyées au robot pendant toute la durée, puis les moteurs s'arrêtent. "
                           "Les actionneurs non cochés ne reçoivent rien."))
        c.addStretch(1)
        self.action_pages.addWidget(consigne)
        # mini script
        script = QWidget()
        s = QVBoxLayout(script)
        s.setContentsMargins(0, 0, 0, 0)
        self.script = python_editor()
        self.script.textChanged.connect(lambda: self._set("script", self.script.toPlainText()))
        s.addWidget(self.script, 1)
        ligne = QHBoxLayout()
        verifier = QPushButton("Vérifier")
        verifier.clicked.connect(self._on_check_script)
        ligne.addWidget(verifier)
        ligne.addWidget(QLabel("Fréquence"))
        self.script_fps = QSpinBox()
        self.script_fps.setRange(1, 100)
        self.script_fps.setSuffix(" Hz")
        self.script_fps.valueChanged.connect(lambda v: self._set("fps", v))
        ligne.addWidget(self.script_fps)
        ligne.addStretch(1)
        s.addLayout(ligne)
        self.script_status = _muted("Une Commande de MIR : action(observation) est appelée à chaque tour et renvoie "
                                    "les consignes ; self.terminer() arrête l'action avant la fin de la durée.")
        s.addWidget(self.script_status)
        self.action_pages.addWidget(script)
        # politique
        politique = QWidget()
        p = QVBoxLayout(politique)
        p.setContentsMargins(0, 0, 0, 0)
        self.policy = QComboBox()
        self.policy.currentIndexChanged.connect(self._on_policy)
        p.addWidget(self.policy)
        self.policy_info = _muted("")
        p.addWidget(self.policy_info)
        p.addStretch(1)
        self.action_pages.addWidget(politique)
        layout.addWidget(self.action_pages, 1)

        # « Arrêter quand » : une condition, vérifiée à chaque tour de l'action
        titre = QLabel("Arrêter quand…")
        titre.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(titre)
        self.watch_until = QLineEdit()
        self.watch_until.setFont(QFont(theme.MONO_FAMILIES[0]))
        self.watch_until.setPlaceholderText("ex. vision.nombre > 0   (vide : l'action va jusqu'au bout)")
        self.watch_until.textChanged.connect(lambda t: self._set("until", t.strip()))
        layout.addWidget(self.watch_until)
        layout.addWidget(_muted("Vérifiée à chaque tour de l'action, sur les données tenues à jour par une chaîne "
                                "« En continu ». Si elle devient vraie, l'action s'arrête et le programme continue "
                                "par la sortie « interrompu »."))
        return page

    # ------------------------------------------------------------------ nœud choisi
    def set_context(self, ctx: InspectorContext):
        self._ctx = ctx
        if self._node is not None:
            self.set_node(self._node, self._graph)

    def set_node(self, node: Node | None, graph: Graph | None):
        self._node, self._graph = node, graph
        self._loading = True
        try:
            if node is None:
                self._title.setText("")
                self._pages.setCurrentWidget(self._empty)
            elif node.type == NODE_LLM:
                self._title.setText("LLM")
                self._load_llm(node.config)
                self._pages.setCurrentIndex(1)
            elif node.type == NODE_ACTION:
                self._title.setText("Action")
                self._load_action(node.config)
                self._pages.setCurrentIndex(2)
            else:
                self._title.setText(node.spec.label)
                self._build_generic(node)
                self._pages.setCurrentWidget(self._generic)
        finally:
            self._loading = False

    def _load_llm(self, c: dict):
        self.llm_name.setText(c.get("name", ""))
        self._name_editor = self.llm_name
        self.llm_model.setCurrentText(c.get("model", ""))
        self.llm_instructions.setPlainText(c.get("instructions", ""))
        self.llm_describe.setChecked(bool(c.get("describe_robot", True)))
        self.llm_prompt.setPlainText(c.get("prompt", ""))

    def _load_action(self, c: dict):
        self.action_name.setText(c.get("name", ""))
        self._name_editor = self.action_name
        # la description ne sert qu'à un LLM qui utilise l'action comme outil
        self.action_form.setRowVisible(self.action_description, self._is_tool())
        self.action_description.setPlainText(c.get("description", ""))
        self.action_kind.setCurrentIndex(max(0, self.action_kind.findData(c.get("kind", KIND_SETPOINT))))
        self.action_pages.setCurrentIndex(list(KINDS).index(c.get("kind", KIND_SETPOINT)))
        self._duration_label(c.get("kind", KIND_SETPOINT))
        self.action_duration.setValue(float(c.get("duration_s") or 2))
        self._fill_setpoint(c.get("setpoint") or {})
        self.script.setPlainText(c.get("script", ""))
        self.script_fps.setValue(int(c.get("fps") or 20))
        self.watch_until.setText(c.get("until", ""))
        self.policy.clear()
        self.policy.addItem("Choisir une politique entraînée…", "")
        for info in self._ctx.policies:
            self.policy.addItem(f"{info['name']} · {info.get('kind', '?')} · {info['date']}", info["path"])
        index = self.policy.findData(c.get("policy", ""))
        if index < 0 and c.get("policy"):
            self.policy.addItem(f"{c['policy']} (introuvable)", c["policy"])
            index = self.policy.count() - 1
        self.policy.setCurrentIndex(max(0, index))
        self._show_policy_info()

    def _fill_setpoint(self, values: dict[str, float]):
        while self.setpoint_grid.count():
            w = self.setpoint_grid.takeAt(0).widget()
            if w is not None:
                w.hide()                # sinon l'ancien champ reste affiché jusqu'à sa destruction
                w.setParent(None)
                w.deleteLater()
        self._setpoint_widgets: dict[str, tuple[QCheckBox, QDoubleSpinBox]] = {}
        self.preset.clear()
        self.preset.addItem("Préremplir…")
        self.preset.addItems(list(self._ctx.presets))
        self.preset.setVisible(bool(self._ctx.presets))
        if not self._ctx.actions:
            self.setpoint_grid.addWidget(_muted("Connectez le robot (ou passez en simulé) pour choisir ses "
                                                "actionneurs."), 0, 0)
        for row, (name, action) in enumerate(self._ctx.actions.items()):
            check = QCheckBox(name)
            spin = QDoubleSpinBox()
            rng = action.get_range()
            spin.setRange(*(rng if rng else (-1e6, 1e6)))
            spin.setDecimals(1)
            spin.setSuffix(f" {action.get_unit()}")
            check.setChecked(name in values)
            spin.setValue(float(values.get(name, 0.0)))
            spin.setEnabled(name in values)
            check.toggled.connect(self._on_setpoint)
            spin.valueChanged.connect(self._on_setpoint)
            self.setpoint_grid.addWidget(check, row, 0)
            self.setpoint_grid.addWidget(spin, row, 1)
            self._setpoint_widgets[name] = (check, spin)

    # ------------------------------------------------------------------ modifications
    def _is_tool(self) -> bool:
        """Le nœud est-il branché comme outil sous un LLM ?"""
        return self._graph is not None and self._node is not None and \
            any(e.kind == EDGE_TOOL and e.src == self._node.id for e in self._graph.edges)

    def _set(self, key: str, value: Any):
        if self._loading or self._node is None:
            return
        self._node.config[key] = value
        self.changed.emit(self._node.id)

    def _on_name(self, text: str):
        if self._loading or self._node is None:
            return
        ok = bool(NAME.match(text)) and (self._graph is None or
                                         self._graph.unique_name(text, ignore=self._node.id) == text)
        if self._name_editor is not None:
            self._name_editor.setStyleSheet("" if ok else f"border: 1px solid {theme.ERROR};")
            self._name_editor.setToolTip("" if ok else "Lettres, chiffres ou _, sans espace ni accent ; deux nœuds ne "
                                                       "peuvent pas avoir le même nom")
        self._set("name", text)

    def _duration_label(self, kind: str):
        """Une consigne dure exactement la durée ; un script ou une politique peut finir avant : c'est un maximum."""
        label = self._action_main_form.labelForField(self.action_duration)
        if label is not None:
            label.setText("Durée" if kind == KIND_SETPOINT else "Durée maximale")

    def _on_kind(self):
        kind = self.action_kind.currentData()
        self.action_pages.setCurrentIndex(list(KINDS).index(kind))
        self._duration_label(kind)
        self._set("kind", kind)

    def _on_setpoint(self):
        if self._loading:
            return
        values = {}
        for name, (check, spin) in self._setpoint_widgets.items():
            spin.setEnabled(check.isChecked())
            if check.isChecked():
                values[name] = spin.value()
        self._set("setpoint", values)

    def _on_preset(self, index: int):
        if index <= 0:
            return
        values = self._ctx.presets[self.preset.itemText(index)]
        self._loading = True
        for name, (check, spin) in self._setpoint_widgets.items():
            check.setChecked(name in values)
            spin.setEnabled(name in values)
            if name in values:
                spin.setValue(values[name])
        self._loading = False
        self.preset.setCurrentIndex(0)
        self._on_setpoint()

    def _on_check_script(self):
        try:
            classe = load_script(self.script.toPlainText(), "verification")
            self.script_status.setText(f"✓ Classe {classe.__name__} trouvée.")
            self.script_status.setStyleSheet(f"color: {theme.OK};")
        except SyntaxError as e:
            self.script_status.setText(f"Erreur de syntaxe ligne {e.lineno} : {e.msg}")
            self.script_status.setStyleSheet(f"color: {theme.ERROR};")
        except Exception as e:
            self.script_status.setText(f"{type(e).__name__} : {e}")
            self.script_status.setStyleSheet(f"color: {theme.ERROR};")

    def _on_policy(self):
        self._set("policy", self.policy.currentData() or "")
        self._show_policy_info()

    def _show_policy_info(self):
        path = self.policy.currentData()
        info = next((i for i in self._ctx.policies if i["path"] == path), None)
        if info is None:
            self.policy_info.setText("Politiques entraînées dans l'étape « Entraîner un modèle » (ACT, PyTorch, RL…). "
                                     "Elle pilote le robot à sa fréquence pendant la durée, ou jusqu'à ce qu'elle "
                                     "s'arrête d'elle-même.")
            return
        lignes = []
        if info.get("inputs"):
            lignes.append(f"voit : {', '.join(info['inputs'])}")
        if info.get("actions"):
            lignes.append(f"commande : {', '.join(a.split('.')[0] for a in info['actions'])}")
        if info.get("fps"):
            lignes.append(f"fréquence : {info['fps']:g} Hz")
        self.policy_info.setText("\n".join(lignes))

    # ------------------------------------------------------------------ page générique (d'après la description du nœud)
    def _build_generic(self, node: Node):
        index = self._pages.indexOf(self._generic)
        self._pages.removeWidget(self._generic)
        self._generic.hide()
        self._generic.setParent(None)
        self._generic.deleteLater()
        self._generic = QWidget()
        self._pages.insertWidget(index, self._generic)
        layout = QVBoxLayout(self._generic)
        layout.setContentsMargins(0, 0, 0, 0)
        spec, c = node.spec, node.config
        if spec.help:
            layout.addWidget(_muted(spec.help))
        form = QFormLayout()
        name = QLineEdit(c.get("name", ""))
        name.setToolTip("Nom du nœud : ses résultats sont rangés sous ce nom dans les données du flux")
        name.textChanged.connect(self._on_name)
        self._name_editor = name
        form.addRow("Nom", name)
        if spec.tool and self._is_tool():
            description = QPlainTextEdit(c.get("description", ""))
            description.setFixedHeight(50)
            description.setPlaceholderText("Pour un LLM qui l'utilise comme outil : ce qu'il fait, quand s'en servir")
            description.textChanged.connect(lambda: self._set("description", description.toPlainText()))
            form.addRow("Description", description)
        for f in spec.fields:
            if f.kind in ("camera", "lidar") and len(self._ctx.cameras if f.kind == "camera" else self._ctx.lidars) <= 1:
                continue            # un seul capteur de ce type : rien à choisir
            if f.kind == "quantities" and c.get("source") != SOURCE_SERVOS:
                continue            # les grandeurs ne concernent que les servos
            form.addRow(f.label, self._field_widget(f, c))
            if f.help:
                form.addRow("", _muted(f.help))
        layout.addLayout(form)
        if spec.outputs_help:
            layout.addWidget(_muted("Résultat (données du flux) : " +
                                    spec.outputs_help.replace(f"{spec.default_name}.", f"{node.name}.")))
        layout.addStretch(1)

    def _field_widget(self, f, c: dict) -> QWidget:
        value = c.get(f.key, f.default)
        if f.kind in ("text", "expression"):
            w = QLineEdit(str(value if value is not None else ""))
            if f.kind == "expression":
                w.setFont(QFont(theme.MONO_FAMILIES[0]))
            w.textChanged.connect(lambda t, k=f.key: self._set(k, t))
            return w
        if f.kind == "code":
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            editor = python_editor(str(value or ""), 260)
            editor.textChanged.connect(lambda k=f.key, e=editor: self._set(k, e.toPlainText()))
            v.addWidget(editor)
            status = _muted("")
            check = QPushButton("Vérifier")

            def verifier():
                try:
                    load_process(editor.toPlainText(), "verification")
                    status.setText("✓ Fonction traiter trouvée.")
                    status.setStyleSheet(f"color: {theme.OK};")
                except SyntaxError as e:
                    status.setText(f"Erreur de syntaxe ligne {e.lineno} : {e.msg}")
                    status.setStyleSheet(f"color: {theme.ERROR};")
                except Exception as e:
                    status.setText(f"{type(e).__name__} : {e}")
                    status.setStyleSheet(f"color: {theme.ERROR};")
            check.clicked.connect(verifier)
            ligne = QHBoxLayout()
            ligne.addWidget(check)
            ligne.addWidget(status, 1)
            v.addLayout(ligne)
            return box
        if f.kind == "classes":
            return self._classes_widget(f, str(value or ""))
        if f.kind == "source":
            w = QComboBox()
            w.addItem("Choisir une source…", "")
            for camera in self._ctx.cameras:
                w.addItem(f"Caméra · {camera}", camera)
            for lidar in self._ctx.lidars:
                w.addItem(f"Lidar · {lidar}", lidar)
            w.addItem("Servos (codeurs : position, vitesse…)", SOURCE_SERVOS)
            if value and w.findData(value) < 0:
                w.addItem(f"{value} (absent du robot)", value)
            w.setCurrentIndex(max(0, w.findData(value or "")))

            def changed(_):
                self._set(f.key, w.currentData())
                if self._node is not None:      # les grandeurs n'apparaissent que pour les servos
                    QTimer.singleShot(0, lambda: self.set_node(self._node, self._graph))
            w.currentIndexChanged.connect(changed)
            return w
        if f.kind == "quantities":
            w = QListWidget()
            w.setMaximumHeight(120)
            chosen = set(value or [])
            for key, (_, unit) in QUANTITIES.items():
                item = QListWidgetItem(f"{key} ({unit})")
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if key in chosen else Qt.CheckState.Unchecked)
                w.addItem(item)
            w.itemChanged.connect(lambda _, k=f.key, w=w: self._set(k, [
                w.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.count())
                if w.item(i).checkState() == Qt.CheckState.Checked]))
            return w
        if f.kind == "multiline":
            w = QPlainTextEdit(str(value or ""))
            w.setFixedHeight(70)
            w.textChanged.connect(lambda k=f.key, w=w: self._set(k, w.toPlainText()))
            return w
        if f.kind in ("number", "int"):
            w = QDoubleSpinBox() if f.kind == "number" else QSpinBox()
            if f.kind == "number":
                w.setDecimals(2)
                w.setRange(f.minimum, f.maximum)
                w.setSingleStep(f.step)
            else:
                w.setRange(int(f.minimum), int(f.maximum))
            if f.unit:
                w.setSuffix(f" {f.unit}")
            w.setValue(float(value or 0) if f.kind == "number" else int(value or 0))
            w.valueChanged.connect(lambda v, k=f.key: self._set(k, v))
            return w
        if f.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(lambda v, k=f.key: self._set(k, v))
            return w
        if f.kind in ("choice", "camera", "lidar", "model"):
            w = QComboBox()
            if f.kind == "choice":
                w.addItems(f.choices)
            elif f.kind == "model":
                w.setEditable(True)
                w.addItems(MODELS)
            else:
                sensors = self._ctx.cameras if f.kind == "camera" else self._ctx.lidars
                w.addItem("(le premier du robot)", "")
                for sensor in sensors:
                    w.addItem(sensor, sensor)
                if value and value not in sensors:
                    w.addItem(f"{value} (absent)", value)
            if f.kind in ("camera", "lidar"):
                w.setCurrentIndex(max(0, w.findData(value or "")))
                w.currentIndexChanged.connect(lambda _, k=f.key, w=w: self._set(k, w.currentData()))
            else:
                w.setCurrentText(str(value or ""))
                w.currentTextChanged.connect(lambda t, k=f.key: self._set(k, t))
            return w
        raise ValueError(f"réglage de sorte inconnue : {f.kind}")

    def _classes_widget(self, f, value: str) -> QWidget:
        """Objets cherchés par la vision : texte libre (séparé par des virgules) et liste des objets reconnus."""
        from mir_flow.perception import COCO_LABELS, unknown_labels
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value)
        edit.setPlaceholderText("vide : tous les objets")
        status = _muted("")

        def check(text: str):
            unknown = unknown_labels(text.split(","))
            edit.setStyleSheet(f"border: 1px solid {theme.ERROR};" if unknown else "")
            status.setText(("Inconnu : " + ", ".join(unknown)) if unknown else "")
            status.setStyleSheet(f"color: {theme.ERROR};" if unknown else "")
            self._set(f.key, text)
        edit.textChanged.connect(check)
        v.addWidget(edit)
        add = QComboBox()
        add.addItem("Ajouter un objet…")
        add.addItems(sorted(COCO_LABELS))

        def append(index: int):
            if index <= 0:
                return
            names = [n.strip() for n in edit.text().split(",") if n.strip()]
            if add.itemText(index) not in names:
                names.append(add.itemText(index))
            edit.setText(", ".join(names))
            add.setCurrentIndex(0)
        add.activated.connect(append)
        v.addWidget(add)
        v.addWidget(status)
        unknown = unknown_labels(value.split(","))
        if unknown:
            edit.setStyleSheet(f"border: 1px solid {theme.ERROR};")
            status.setText("Inconnu : " + ", ".join(unknown))
            status.setStyleSheet(f"color: {theme.ERROR};")
        return box
