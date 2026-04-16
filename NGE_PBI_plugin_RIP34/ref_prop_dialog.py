from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit,
    QHeaderView, QAbstractItemView,
)
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.PyQt.QtCore import Qt

# Roles UserRole stockes dans la checkbox (col 0)
_R_FID = Qt.ItemDataRole.UserRole       # ch_fid
_R_REF = Qt.ItemDataRole.UserRole + 1   # ref_prop propose
_R_OK = Qt.ItemDataRole.UserRole + 2    # deja correct (bool)


class _NumItem(QTableWidgetItem):
    """QTableWidgetItem avec tri numerique."""

    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)


class RefPropDialog(QDialog):
    """Dialog QTableWidget — remplissage REF_PROP appuis Orange.

    modifications : liste de dicts triee par distance
        cles : ch_fid, ref_prop, num_appui,
               code_commu, distance, actuel
    iface         : iface QGIS (zoom/flash)
    ch_layer      : couche *_CH (pour selectByIds)
    """

    def __init__(self, modifications, iface=None,
                 ch_layer=None, parent=None):
        super().__init__(parent)
        self.modifications = modifications
        self.iface = iface
        self.ch_layer = ch_layer
        self.setWindowTitle(
            "Remplir REF PROP — "
            + str(len(modifications))
            + " appui(s) trouve(s)"
        )
        self.setMinimumSize(900, 560)
        self.setup_ui()

    # ------------------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()

        # ---- Bandeau résumé ----
        n_cables = len(self.modifications)
        n_remplis = sum(
            1 for m in self.modifications if m["actuel"]
        )
        n_deja_ok = sum(
            1 for m in self.modifications
            if m["actuel"] == m["ref_prop"]
        )
        summary = QLabel(
            str(n_cables) + " appui(s) — "
            + str(n_remplis) + " deja rempli(s), "
            "<span style='color:green'>"
            + str(n_deja_ok) + " deja corrects</span>"
        )
        summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(summary)

        # ---- Barre de recherche ----
        s_layout = QHBoxLayout()
        s_layout.addWidget(QLabel("Recherche :"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Filtrer par REF PROP ou num appui..."
        )
        self.search_input.textChanged.connect(self.filter_rows)
        s_layout.addWidget(self.search_input)
        layout.addLayout(s_layout)

        # ---- Table ----
        cols = [
            "\u2611",
            "REF PROP propose",
            "Actuel",
            "Num appui",
            "Code INSEE",
            "Distance (m)",
        ]
        self.table = QTableWidget(
            len(self.modifications), len(cols)
        )
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setSortingEnabled(True)
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
        self.table.cellDoubleClicked.connect(
            self.on_double_click
        )

        C_GRN = QColor("#E8F5E9")   # deja correct
        C_ORA = QColor("#FFF3E0")   # a remplir / different

        self.table.setSortingEnabled(False)
        for row, mod in enumerate(self.modifications):
            ch_fid = mod["ch_fid"]
            ref_prop = mod["ref_prop"]
            actuel = mod["actuel"]
            already_ok = (actuel == ref_prop)
            bg = C_GRN if already_ok else C_ORA

            # Col 0 : checkbox + meta
            cb_item = QTableWidgetItem()
            cb_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            cb_item.setCheckState(
                Qt.CheckState.Unchecked
                if already_ok
                else Qt.CheckState.Checked
            )
            cb_item.setBackground(QBrush(bg))
            cb_item.setData(_R_FID, ch_fid)
            cb_item.setData(_R_REF, ref_prop)
            cb_item.setData(_R_OK, already_ok)
            self.table.setItem(row, 0, cb_item)

            # Cols 1-5 : données
            text_vals = [
                ref_prop,                    # 1 texte
                actuel if actuel else "",    # 2 texte
                mod["num_appui"],            # 3 texte
                mod["code_commu"],           # 4 texte
                str(mod["distance"]),        # 5 num
            ]
            for col, val in enumerate(text_vals, start=1):
                item = (
                    _NumItem(val)
                    if col == 5
                    else QTableWidgetItem(val)
                )
                item.setFlags(
                    item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                item.setBackground(QBrush(bg))
                self.table.setItem(row, col, item)

        self.table.setSortingEnabled(True)
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
    # Filtrage
    # ------------------------------------------------------------------
    def filter_rows(self, text):
        text = text.strip().upper()
        for row in range(self.table.rowCount()):
            ref_item = self.table.item(row, 1)
            num_item = self.table.item(row, 3)
            match = False
            if ref_item and text in ref_item.text().upper():
                match = True
            if num_item and text in num_item.text().upper():
                match = True
            self.table.setRowHidden(row, not match if text else False)

    # ------------------------------------------------------------------
    # Double-clic : zoom + flash sur l'appui CH
    # ------------------------------------------------------------------
    def on_double_click(self, row, col):
        if not self.iface or not self.ch_layer:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        ch_fid = item.data(_R_FID)
        self.ch_layer.selectByIds([ch_fid])
        self.iface.mapCanvas().zoomToSelected(self.ch_layer)
        self.iface.mapCanvas().flashFeatureIds(
            self.ch_layer, [ch_fid]
        )

    # ------------------------------------------------------------------
    # Sélection groupée
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Compteur dynamique
    # ------------------------------------------------------------------
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
        total = len(self.modifications)
        self.count_label.setText(
            str(n) + " / " + str(total)
            + " appui(s) selectionne(s)"
        )
        self.btn_apply.setText(
            "Appliquer (" + str(n) + ")"
        )

    # ------------------------------------------------------------------
    # Résultat : [(ch_fid, ref_prop)] cochés et non-OK
    # ------------------------------------------------------------------
    def get_chosen(self):
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            if item.checkState() != Qt.CheckState.Checked:
                continue
            if item.data(_R_OK):
                continue  # deja correct
            result.append(
                (item.data(_R_FID), item.data(_R_REF))
            )
        return result
