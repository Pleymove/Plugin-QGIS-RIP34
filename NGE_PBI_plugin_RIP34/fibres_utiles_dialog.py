from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit,
    QHeaderView, QAbstractItemView,
)
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.PyQt.QtCore import Qt

# Roles UserRole stockes dans la checkbox (col 0) de chaque ligne
_R_FID = Qt.ItemDataRole.UserRole
_R_OK = Qt.ItemDataRole.UserRole + 1
_R_SOUS = Qt.ItemDataRole.UserRole + 2
_R_PROP = Qt.ItemDataRole.UserRole + 3


class _NumItem(QTableWidgetItem):
    """QTableWidgetItem avec tri numerique."""

    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)


class FibresUtilesDialog(QDialog):
    """Dialog QTableWidget — resultats calcul fibres utiles.

    modifications   : liste de dicts (triee par ecart desc)
                      cles : fid, code, fu, actuel, propose,
                             ecart, sous_dim, ok
    total_selected  : nb de cables selectionnes sur la carte
    iface           : iface QGIS (pour zoom/flash)
    cb_layer        : couche CB (pour selectByIds)
    """

    def __init__(self, modifications, total_selected,
                 iface=None, cb_layer=None,
                 fid_to_layer=None, parent=None):
        super().__init__(parent)
        self.modifications = modifications
        self.total_selected = total_selected
        self.iface = iface
        self.cb_layer = cb_layer
        self.fid_to_layer = fid_to_layer or {}
        self.setWindowTitle(
            "Calcul Fibres Utiles — "
            + str(total_selected)
            + " cable(s) selectionne(s)"
        )
        self.setMinimumSize(920, 600)
        self.setup_ui()

    # ------------------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()

        # ---- Bandeau résumé ----
        n_sous = sum(
            1 for m in self.modifications
            if not m["ok"] and m["sous_dim"]
        )
        n_sur = sum(
            1 for m in self.modifications
            if not m["ok"] and not m["sous_dim"]
        )
        n_ok = sum(1 for m in self.modifications if m["ok"])

        summary = QLabel(
            str(len(self.modifications)) + " cable(s) : "
            "<span style='color:red'>"
            + str(n_sous) + " sous-dim.</span>, "
            "<span style='color:darkorange'>"
            + str(n_sur) + " sur-dim.</span>, "
            "<span style='color:green'>"
            + str(n_ok) + " OK</span>"
        )
        summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(summary)

        # ---- Barre de recherche ----
        s_layout = QHBoxLayout()
        s_layout.addWidget(QLabel("Recherche :"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Filtrer par code cable..."
        )
        self.search_input.textChanged.connect(self.filter_rows)
        s_layout.addWidget(self.search_input)
        layout.addLayout(s_layout)

        # ---- Table ----
        cols = [
            "\u2611", "Code cable", "FU calc.",
            "Actuel (FO)", "Propose (FO)",
            "Ecart", "BAT aval", "Statut",
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

        # Couleurs de fond par statut
        C_RED = QColor("#FFE0E0")
        C_ORA = QColor("#FFF3E0")
        C_GRN = QColor("#E8F5E9")

        # Remplissage (tri desactive pour conserver l'ordre initial)
        self.table.setSortingEnabled(False)
        for row, mod in enumerate(self.modifications):
            fid = mod["fid"]
            ok = mod["ok"]
            sous_dim = mod["sous_dim"]
            bg = C_GRN if ok else (C_RED if sous_dim else C_ORA)
            actuel_str = (
                str(mod["actuel"])
                if mod["actuel"] is not None
                else "?"
            )

            # Col 0 : checkbox + meta-donnees (acces post-tri)
            cb_item = QTableWidgetItem()
            cb_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            cb_item.setCheckState(
                Qt.CheckState.Unchecked
                if ok
                else Qt.CheckState.Checked
            )
            cb_item.setBackground(QBrush(bg))
            cb_item.setData(_R_FID, fid)
            cb_item.setData(_R_OK, ok)
            cb_item.setData(_R_SOUS, sous_dim)
            cb_item.setData(_R_PROP, mod["propose"])
            self.table.setItem(row, 0, cb_item)

            # Cols 1-6 : données texte / numériques
            text_vals = [
                mod["code"],          # 1 - texte
                str(mod["fu"]),       # 2 - num
                actuel_str,           # 3 - num (peut etre "?")
                str(mod["propose"]),  # 4 - num
                str(mod["ecart"]),    # 5 - num
                str(mod["fu"]),       # 6 - num (BAT aval = fu)
            ]
            for col, val in enumerate(text_vals, start=1):
                item = (
                    QTableWidgetItem(val)
                    if col == 1
                    else _NumItem(val)
                )
                item.setFlags(
                    item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                item.setBackground(QBrush(bg))
                self.table.setItem(row, col, item)

            # Col 7 : statut coloré
            if ok:
                s_txt, s_fg = "OK", QColor("green")
            elif sous_dim:
                s_txt, s_fg = "SOUS-DIM", QColor("red")
            else:
                s_txt, s_fg = "SUR-DIM", QColor("darkorange")
            s_item = QTableWidgetItem(s_txt)
            s_item.setFlags(
                s_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            s_item.setBackground(QBrush(bg))
            s_item.setForeground(QBrush(s_fg))
            self.table.setItem(row, 7, s_item)

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
        btn_sous = QPushButton("Cocher sous-dim. uniquement")
        btn_sous.clicked.connect(self.select_sous_dim)
        sel_layout.addWidget(btn_all)
        sel_layout.addWidget(btn_none)
        sel_layout.addWidget(btn_sous)
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
            item = self.table.item(row, 1)  # col Code cable
            if item:
                self.table.setRowHidden(
                    row, text not in item.text().upper()
                )

    # ------------------------------------------------------------------
    # Double-clic : zoom + flash sur la carte
    # ------------------------------------------------------------------
    def on_double_click(self, row, col):
        if not self.iface:
            return
        cb_item = self.table.item(row, 0)
        if not cb_item:
            return
        fid = cb_item.data(_R_FID)
        layer = self.fid_to_layer.get(fid, self.cb_layer)
        if not layer:
            return
        layer.selectByIds([fid])
        self.iface.mapCanvas().zoomToSelected(layer)
        self.iface.mapCanvas().flashFeatureIds(layer, [fid])

    # ------------------------------------------------------------------
    # Sélection groupée (respecte la visibilité du filtre)
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

    def select_sous_dim(self):
        self.table.itemChanged.disconnect(self.update_count)
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if not item:
                continue
            ok = item.data(_R_OK)
            sous_dim = item.data(_R_SOUS)
            item.setCheckState(
                Qt.CheckState.Checked
                if (not ok and sous_dim)
                else Qt.CheckState.Unchecked
            )
        self.table.itemChanged.connect(self.update_count)
        self.update_count()

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
        self.count_label.setText(
            str(n) + " / "
            + str(len(self.modifications))
            + " cable(s) selectionne(s) pour modification"
        )
        self.btn_apply.setText(
            "Appliquer (" + str(n) + ")"
        )

    # ------------------------------------------------------------------
    # Résultat : [(fid, propose)] pour les cochés non-OK
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
                continue  # deja correct, pas de modif
            result.append(
                (item.data(_R_FID), item.data(_R_PROP))
            )
        return result
