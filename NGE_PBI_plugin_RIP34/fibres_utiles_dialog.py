from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                  QScrollArea, QWidget, QPushButton,
                                  QLabel, QCheckBox, QLineEdit)
from qgis.PyQt.QtCore import Qt


class FibresUtilesDialog(QDialog):
    """Affiche les modifications de fibres utiles proposees.

    modifications   : liste de dicts triee par ecart decroissant
                      cles : fid, code, fu, actuel, propose,
                             ecart, sous_dim
    total_cables    : nb total de cables analyses
    selected_codes  : set de code_cb pre-selectionnes (carte QGIS)
    """

    def __init__(self, modifications, total_cables,
                 selected_codes=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            "Calcul Fibres Utiles — Modifications proposees"
        )
        self.setMinimumSize(820, 560)
        self.modifications = modifications
        self.total_cables = total_cables
        self.selected_codes = selected_codes or set()
        # (QCheckBox, fid, propose, code_upper)
        self.checkboxes = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Compteur
        self.count_label = QLabel()
        layout.addWidget(self.count_label)

        # Legende couleurs
        legend = QLabel(
            "<font color='red'>■ Sous-dimensionne</font>"
            "&nbsp;&nbsp;"
            "<font color='orange'>■ Sur-dimensionne</font>"
            "&nbsp;&nbsp;"
            "&#11088; = selectionne sur la carte"
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(legend)

        # Barre de recherche
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Recherche :"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Filtrer par code cable..."
        )
        self.search_input.textChanged.connect(self.filter_list)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # En-tete colonnes
        header = QLabel(
            "  CODE CABLE  |  FU calc.  |  "
            "Actuel  |  Propose  |  BAT aval"
        )
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout()
        scroll_layout.setSpacing(1)

        for mod in self.modifications:
            code = mod["code"]
            fu = mod["fu"]
            actuel = mod["actuel"]
            propose = mod["propose"]
            sous_dim = mod["sous_dim"]
            pre_coche = code in self.selected_codes

            actuel_str = (
                str(actuel) + " FO"
                if actuel is not None
                else "inconnu"
            )
            label = (
                code
                + "  |  FU: " + str(fu)
                + "  |  Actuel: " + actuel_str
                + "  |  Propose: " + str(propose) + " FO"
                + "  |  BAT aval: " + str(fu)
            )
            if pre_coche:
                label = label + "  ⭐"

            cb = QCheckBox(label)
            cb.setChecked(pre_coche)
            color = "red" if sous_dim else "orange"
            cb.setStyleSheet("color: " + color + ";")
            cb.stateChanged.connect(self.update_count)
            self.checkboxes.append(
                (cb, mod["fid"], mod["propose"], code.upper())
            )
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll_widget.setLayout(scroll_layout)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        self.update_count()

        # Boutons tout cocher / decocher
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("Tout cocher")
        btn_all.clicked.connect(self.select_all)
        btn_none = QPushButton("Tout decocher")
        btn_none.clicked.connect(self.deselect_all)
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Boutons Appliquer / Annuler
        action_layout = QHBoxLayout()
        btn_apply = QPushButton("Appliquer")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        action_layout.addStretch()
        action_layout.addWidget(btn_apply)
        action_layout.addWidget(btn_cancel)
        layout.addLayout(action_layout)

        self.setLayout(layout)

    # ---- filtrage ----
    def filter_list(self, text):
        text = text.strip().upper()
        for cb, _, __, code_upper in self.checkboxes:
            cb.setVisible(text in code_upper)

    # ---- selection ----
    def select_all(self):
        for cb, _, __, __ in self.checkboxes:
            if cb.isVisible():
                cb.setChecked(True)

    def deselect_all(self):
        for cb, _, __, __ in self.checkboxes:
            if cb.isVisible():
                cb.setChecked(False)

    # ---- compteur ----
    def update_count(self):
        n = sum(
            1 for cb, _, __, __ in self.checkboxes
            if cb.isChecked()
        )
        self.count_label.setText(
            str(n) + " modifications sur "
            + str(self.total_cables) + " cables analyses"
        )

    # ---- resultat ----
    def get_chosen(self):
        result = []
        for cb, fid, propose, _ in self.checkboxes:
            if cb.isChecked():
                result.append((fid, propose))
        return result
