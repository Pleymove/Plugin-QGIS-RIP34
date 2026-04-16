from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
from qgis.PyQt.QtWidgets import QLineEdit, QCheckBox, QScrollArea
from qgis.PyQt.QtWidgets import QWidget, QPushButton, QLabel, QFrame
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtCore import Qt


class ListePBODialog(QDialog):
    """v3 - Affichage hierarchique BPE de depart -> PBO enfants."""

    def __init__(self, bpe_data, hierarchy, selected_codes,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generer LISTE DES PBO  (v3)")
        self.setMinimumSize(620, 700)
        self.bpe_data = bpe_data
        self.hierarchy = hierarchy  # {parent_code: [child_codes]}
        self.selected_codes = selected_codes
        self.checkboxes = {}       # code -> QCheckBox
        self.parent_map = {}       # child_code -> parent_code
        self._building = False
        self.setup_ui()

    # ---- construction de l'interface ----
    def setup_ui(self):
        layout = QVBoxLayout()

        titre = QLabel(
            "Cochez les PBO a livrer. "
            "Le BPE de depart sera auto-coche."
        )
        layout.addWidget(titre)

        # Barre de recherche
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Recherche :"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Filtrer par code BPE..."
        )
        self.search_input.textChanged.connect(self.filter_list)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout()

        self._building = True
        bold = QFont()
        bold.setBold(True)

        # --- BPE qui sont parents (ont des enfants) ---
        parent_codes = sorted(self.hierarchy.keys())
        shown = set()

        for p_code in parent_codes:
            children = self.hierarchy[p_code]
            p_info = self.bpe_data.get(p_code, {})
            p_type = p_info.get("type", "BPE")
            p_nb = p_info.get("nb_bats", 0)

            # Separateur leger
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            self.scroll_layout.addWidget(line)

            # Checkbox parent
            lbl = p_code + "  [BPE DE DEPART]  ("
            lbl = lbl + p_type + ") - "
            lbl = lbl + str(p_nb) + " BAT"
            if p_code in self.selected_codes:
                lbl = lbl + "  *"
            cb_p = QCheckBox(lbl)
            cb_p.setFont(bold)
            cb_p.setChecked(p_code in self.selected_codes)
            cb_p.code_bpe = p_code
            cb_p.is_parent = True
            self.checkboxes[p_code] = cb_p
            self.scroll_layout.addWidget(cb_p)
            shown.add(p_code)

            # Checkboxes enfants (indentes)
            for c_code in sorted(children):
                c_info = self.bpe_data.get(c_code, {})
                c_type = c_info.get("type", "PBO")
                c_nb = c_info.get("nb_bats", 0)
                clbl = "     " + c_code + "  (" + c_type
                clbl = clbl + ") - " + str(c_nb) + " BAT"
                if c_code in self.selected_codes:
                    clbl = clbl + "  *"
                cb_c = QCheckBox(clbl)
                cb_c.setChecked(c_code in self.selected_codes)
                cb_c.code_bpe = c_code
                cb_c.is_parent = False
                self.checkboxes[c_code] = cb_c
                self.parent_map[c_code] = p_code
                self.scroll_layout.addWidget(cb_c)
                shown.add(c_code)

        # --- BPE orphelins (pas parent, pas enfant) ---
        orphans = sorted(
            c for c in self.bpe_data if c not in shown
        )
        if orphans:
            line2 = QFrame()
            line2.setFrameShape(QFrame.Shape.HLine)
            line2.setFrameShadow(QFrame.Shadow.Sunken)
            self.scroll_layout.addWidget(line2)
            lbl_orph = QLabel("--- Autres BPE (sans parent) ---")
            self.scroll_layout.addWidget(lbl_orph)

        for o_code in orphans:
            o_info = self.bpe_data[o_code]
            olbl = o_code + "  (" + o_info["type"] + ") - "
            olbl = olbl + str(o_info["nb_bats"]) + " BAT"
            if o_code in self.selected_codes:
                olbl = olbl + "  *"
            cb_o = QCheckBox(olbl)
            cb_o.setChecked(o_code in self.selected_codes)
            cb_o.code_bpe = o_code
            cb_o.is_parent = False
            self.checkboxes[o_code] = cb_o
            self.scroll_layout.addWidget(cb_o)

        self.scroll_widget.setLayout(self.scroll_layout)
        scroll.setWidget(self.scroll_widget)
        layout.addWidget(scroll)

        self._building = False

        # Boutons Tout cocher / Decocher / Inverser
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("Tout cocher")
        btn_all.clicked.connect(self.select_all)
        btn_none = QPushButton("Tout decocher")
        btn_none.clicked.connect(self.deselect_all)
        btn_invert = QPushButton("Inverser")
        btn_invert.clicked.connect(self.invert_selection)
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addWidget(btn_invert)
        layout.addLayout(btn_layout)

        # Compteur
        self.count_label = QLabel()
        self.update_count()
        layout.addWidget(self.count_label)

        # Boutons Generer / Annuler
        action_layout = QHBoxLayout()
        btn_gen = QPushButton("Generer le fichier")
        btn_gen.clicked.connect(self.accept)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        action_layout.addWidget(btn_gen)
        action_layout.addWidget(btn_cancel)
        layout.addLayout(action_layout)

        self.setLayout(layout)

        # Connecter les signaux APRES construction
        for cb in self.checkboxes.values():
            cb.stateChanged.connect(self.on_check_changed)

    # ---- auto-coche/decoche du parent ----
    def on_check_changed(self, state):
        if self._building:
            return
        sender = self.sender()
        if not sender:
            return
        code = sender.code_bpe
        if code in self.parent_map:
            p = self.parent_map[code]
            if p not in self.checkboxes:
                self.update_count()
                return
            if state == Qt.CheckState.Checked.value:
                # Coche enfant -> coche le parent
                self.checkboxes[p].setChecked(True)
            else:
                # Decoche enfant -> decoche parent SI
                # plus aucun enfant de ce parent n'est coche
                has_child = False
                for c, cb in self.checkboxes.items():
                    if c == p:
                        continue
                    if self.parent_map.get(c) == p:
                        if cb.isChecked():
                            has_child = True
                            break
                if not has_child:
                    self._building = True
                    self.checkboxes[p].setChecked(False)
                    self._building = False
        self.update_count()

    # ---- filtrage ----
    def filter_list(self, text):
        text = text.upper()
        for code, cb in self.checkboxes.items():
            cb.setVisible(text in code.upper())

    def select_all(self):
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.setChecked(True)

    def deselect_all(self):
        self._building = True
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.setChecked(False)
        self._building = False
        self.update_count()

    def invert_selection(self):
        self._building = True
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.setChecked(not cb.isChecked())
        self._building = False
        self.update_count()

    def update_count(self):
        nb_pbo = 0
        nb_dep = 0
        for code, cb in self.checkboxes.items():
            if cb.isChecked():
                info = self.bpe_data.get(code, {})
                if info.get("type") == "PBO":
                    nb_pbo = nb_pbo + 1
                else:
                    nb_dep = nb_dep + 1
        self.count_label.setText(
            str(nb_pbo) + " PBO + "
            + str(nb_dep) + " BPE depart"
        )

    def get_selected_codes(self):
        result = []
        for code, cb in self.checkboxes.items():
            if cb.isChecked():
                result.append(code)
        return result