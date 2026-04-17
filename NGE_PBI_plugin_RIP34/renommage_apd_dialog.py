from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit,
    QHeaderView, QAbstractItemView,
)
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.PyQt.QtCore import Qt

_R_IDX = Qt.ItemDataRole.UserRole   # index dans candidates


class RenommageAPDDialog(QDialog):
    """Dialog QTableWidget — renommage couches APS → APD.

    candidates : liste de dicts
        cles : layer, old_name, new_name
    """

    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.candidates = candidates
        self.setWindowTitle(
            "Renommer APS → APD — "
            + str(len(candidates))
            + " couche(s) candidate(s)"
        )
        self.setMinimumSize(700, 420)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # ---- Barre de recherche ----
        s_layout = QHBoxLayout()
        s_layout.addWidget(QLabel("Recherche :"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Filtrer par nom de couche..."
        )
        self.search_input.textChanged.connect(self.filter_rows)
        s_layout.addWidget(self.search_input)
        layout.addLayout(s_layout)

        # ---- Table ----
        cols = ["\u2611", "Nom actuel", "Nouveau nom"]
        self.table = QTableWidget(
            len(self.candidates), len(cols)
        )
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        hh.setStretchLastSection(True)

        C_YEL = QColor("#FFF9C4")

        for row, cand in enumerate(self.candidates):
            # Col 0 : checkbox
            cb_item = QTableWidgetItem()
            cb_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            cb_item.setCheckState(Qt.CheckState.Checked)
            cb_item.setBackground(QBrush(C_YEL))
            cb_item.setForeground(QBrush(QColor("black")))
            cb_item.setData(_R_IDX, row)
            self.table.setItem(row, 0, cb_item)

            # Col 1 : nom actuel
            old_item = QTableWidgetItem(cand["old_name"])
            old_item.setBackground(QBrush(C_YEL))
            old_item.setForeground(QBrush(QColor("black")))
            self.table.setItem(row, 1, old_item)

            # Col 2 : nouveau nom
            new_item = QTableWidgetItem(cand["new_name"])
            new_item.setBackground(QBrush(C_YEL))
            new_item.setForeground(
                QBrush(QColor("#1565C0"))
            )
            self.table.setItem(row, 2, new_item)

        self.table.itemChanged.connect(self.update_count)
        layout.addWidget(self.table)

        # ---- Compteur ----
        self.count_label = QLabel()
        layout.addWidget(self.count_label)

        # ---- Boutons sélection ----
        sel_layout = QHBoxLayout()
        btn_all = QPushButton("Tout cocher")
        btn_all.clicked.connect(self.select_all)
        btn_none = QPushButton("Tout decocher")
        btn_none.clicked.connect(self.deselect_all)
        sel_layout.addWidget(btn_all)
        sel_layout.addWidget(btn_none)
        sel_layout.addStretch()
        layout.addLayout(sel_layout)

        # ---- Boutons Appliquer / Annuler ----
        self.btn_apply = QPushButton("Appliquer (0)")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self.accept)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        a_layout = QHBoxLayout()
        a_layout.addStretch()
        a_layout.addWidget(self.btn_apply)
        a_layout.addWidget(btn_cancel)
        layout.addLayout(a_layout)

        self.setLayout(layout)
        self.update_count()

    # ------------------------------------------------------------------
    def filter_rows(self, text):
        text = text.strip().upper()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            match = (not text) or (
                item and text in item.text().upper()
            )
            self.table.setRowHidden(row, not match)

    def _toggle_visible(self, state):
        self.table.itemChanged.disconnect(self.update_count)
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)
        self.table.itemChanged.connect(self.update_count)
        self.update_count()

    def select_all(self):
        self._toggle_visible(Qt.CheckState.Checked)

    def deselect_all(self):
        self._toggle_visible(Qt.CheckState.Unchecked)

    def update_count(self):
        n = sum(
            1
            for row in range(self.table.rowCount())
            if (
                self.table.item(row, 0)
                and self.table.item(row, 0).checkState()
                == Qt.CheckState.Checked
            )
        )
        self.count_label.setText(
            str(n) + " / " + str(len(self.candidates))
            + " couche(s) selectionnee(s)"
        )
        self.btn_apply.setText(
            "Appliquer (" + str(n) + ")"
        )

    def get_chosen(self):
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            if item.checkState() != Qt.CheckState.Checked:
                continue
            idx = item.data(_R_IDX)
            result.append(self.candidates[idx])
        return result
