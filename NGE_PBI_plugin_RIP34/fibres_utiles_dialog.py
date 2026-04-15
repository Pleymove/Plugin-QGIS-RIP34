from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                  QScrollArea, QWidget, QPushButton,
                                  QLabel, QCheckBox)
from qgis.PyQt.QtCore import Qt


class FibresUtilesDialog(QDialog):
    """Affiche les modifications de fibres utiles proposees.

    modifications : liste de dicts avec cles :
        fid, code, fu, actuel, propose, ecart, sous_dim
    total_cables  : nb total de cables analyses
    """

    def __init__(self, modifications, total_cables, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            "Calcul Fibres Utiles — Modifications proposees"
        )
        self.setMinimumSize(780, 520)
        self.modifications = modifications
        self.total_cables = total_cables
        self.checkboxes = []  # (QCheckBox, fid, propose)
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
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(legend)

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

            cb = QCheckBox(label)
            cb.setChecked(True)
            color = "red" if sous_dim else "orange"
            cb.setStyleSheet("color: " + color + ";")
            cb.stateChanged.connect(self.update_count)
            self.checkboxes.append(
                (cb, mod["fid"], mod["propose"])
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

    def update_count(self):
        n = sum(
            1 for cb, _, __ in self.checkboxes
            if cb.isChecked()
        )
        self.count_label.setText(
            str(n) + " modifications sur "
            + str(self.total_cables) + " cables analyses"
        )

    def select_all(self):
        for cb, _, __ in self.checkboxes:
            cb.setChecked(True)

    def deselect_all(self):
        for cb, _, __ in self.checkboxes:
            cb.setChecked(False)

    def get_chosen(self):
        result = []
        for cb, fid, propose in self.checkboxes:
            if cb.isChecked():
                result.append((fid, propose))
        return result
