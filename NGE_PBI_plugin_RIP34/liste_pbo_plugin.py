from qgis.PyQt.QtWidgets import (QAction, QFileDialog, QMessageBox,
                                  QMenu)
from qgis.PyQt.QtGui import QIcon, QCursor
from qgis.core import QgsProject, Qgis, QgsVectorLayer
from .liste_pbo_dialog import ListePBODialog
from .fibres_utiles_dialog import FibresUtilesDialog
import os
import math


class ListePBOPlugin:
    """v3 - Hierarchie BPE depart via couche CB (cables)."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(
            QIcon(icon_path),
            "NGE RIP34",
            self.iface.mainWindow()
        )
        self.action.setToolTip(
            "NGE RIP34 - Outils FTTH"
        )
        self.action.triggered.connect(self.show_menu)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Liste PBO", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("Liste PBO", self.action)

    def show_menu(self):
        menu = QMenu(self.iface.mainWindow())
        act_pbo = menu.addAction("Generer LISTE DES PBO")
        act_pbo.triggered.connect(self.run)
        act_fibres = menu.addAction("Calculer Fibres Utiles")
        act_fibres.triggered.connect(self.run_fibres)
        menu.exec(QCursor.pos())

    def find_parent(self, pbo_code, cables_to, bpe_types,
                    max_depth=10):
        """Remonte les cables DISTRIBUTION depuis un PBO
        jusqu'au premier BPE non-PBO (= BPE de depart).
        cables_to = {extremite: origine} pour cables DISTRIB.
        bpe_types = {code_bpe: type_fonc}.
        """
        current = pbo_code
        for _ in range(max_depth):
            upstream = cables_to.get(current)
            if not upstream:
                return None  # pas de cable en amont
            up_type = bpe_types.get(upstream, "")
            if "PBO" not in up_type.upper():
                return upstream  # c'est le BPE de depart
            current = upstream
        return None  # securite anti-boucle

    def run(self):
        # Chercher les couches BPE, ST et CB
        layers = QgsProject.instance().mapLayers().values()
        bpe_layer = None
        st_layer = None
        cb_layer = None

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            name = layer.name().upper()
            if name.endswith("_BPE"):
                bpe_layer = layer
            elif name.endswith("_ST"):
                st_layer = layer
            elif name.endswith("_CB"):
                cb_layer = layer

        if not bpe_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_BPE trouvee."
            )
            return
        if not st_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_ST trouvee."
            )
            return
        if not cb_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CB trouvee.\n"
                "(necessaire pour detecter les BPE de depart)"
            )
            return

        # BPE selectionnes sur la carte
        selected_codes = set()
        for feat in bpe_layer.selectedFeatures():
            selected_codes.add(
                str(feat["code_bpe"]).strip()
            )

        # Compter les BAT par BPE
        bpe_bats = {}
        for feat in st_layer.getFeatures():
            bpe_code = str(feat["code_bpe"]).strip()
            if bpe_code not in bpe_bats:
                bpe_bats[bpe_code] = 0
            bpe_bats[bpe_code] = bpe_bats[bpe_code] + 1

        # Construire donnees BPE
        bpe_data = {}
        bpe_types = {}  # code -> type_fonc brut

        for feat in bpe_layer.getFeatures():
            code = str(feat["code_bpe"]).strip()
            type_fonc = str(feat["type_fonc"]).strip()
            if "PBO" in type_fonc.upper():
                bpe_type = "PBO"
            else:
                bpe_type = "BPE"
            nb = bpe_bats.get(code, 0)
            bpe_data[code] = {
                "type": bpe_type, "nb_bats": nb
            }
            bpe_types[code] = type_fonc

        # Auto-detecter les noms de colonnes CB
        # (match par substring pour gerer espaces,
        #  BOM, troncatures DBF, etc.)
        cb_fields = [f.name() for f in cb_layer.fields()]

        def find_col(fields, patterns):
            """Cherche une colonne dont le nom contient
            un des patterns (insensible a la casse)."""
            for f in fields:
                fl = f.lower().strip()
                for p in patterns:
                    if p in fl:
                        return f
            return None

        col_orig = find_col(
            cb_fields, ["origine", "origin"]
        )
        col_extr = find_col(
            cb_fields, ["extremite", "extremit", "extr"]
        )

        if not col_orig or not col_extr:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Colonnes origine/extremite non trouvees "
                "dans la couche CB.\n\n"
                "Colonnes disponibles (" + str(
                    len(cb_fields)
                ) + ") :\n"
                + "\n".join(
                    repr(f) for f in cb_fields
                )
            )
            return

        col_cb_type = find_col(
            cb_fields, ["type_fonc", "type_fon"]
        )
        col_cap = find_col(
            cb_fields, ["capacite", "capacit"]
        )

        # Construire le graphe cable : extremite -> origine
        cables_to = {}  # extremite -> origine
        for feat in cb_layer.getFeatures():
            # Filtrer RACCORDEMENT
            if col_cb_type:
                cb_type = str(
                    feat[col_cb_type]
                ).strip().upper()
                if cb_type == "RACCORDEMENT":
                    continue
            elif col_cap:
                try:
                    cap = int(feat[col_cap])
                    if cap <= 1:
                        continue
                except Exception:
                    pass
            orig = str(feat[col_orig]).strip()
            extr = str(feat[col_extr]).strip()
            if orig and extr and orig != "NULL":
                cables_to[extr] = orig

        # Pour chaque PBO, trouver son BPE de depart
        # en remontant les cables
        parent_of = {}  # pbo_code -> parent_code

        for code, info in bpe_data.items():
            if info["type"] != "PBO":
                continue
            parent = self.find_parent(
                code, cables_to, bpe_types
            )
            if parent:
                parent_of[code] = parent

        # Construire la hierarchie parent -> [enfants]
        hierarchy = {}
        for child, parent in parent_of.items():
            if parent not in hierarchy:
                hierarchy[parent] = []
            hierarchy[parent].append(child)

        # Pre-selectionner les parents des PBO
        # selectionnes sur la carte
        for code in list(selected_codes):
            if code in parent_of:
                selected_codes.add(parent_of[code])

        # Ouvrir la fenetre de selection hierarchique
        dlg = ListePBODialog(
            bpe_data, hierarchy, selected_codes,
            self.iface.mainWindow()
        )
        if not dlg.exec():
            return

        chosen = dlg.get_selected_codes()
        if not chosen:
            self.iface.messageBar().pushMessage(
                "Liste PBO", "Aucun BPE selectionne.",
                level=Qgis.Warning, duration=5
            )
            return

        # Dossier de sortie
        dossier = QgsProject.instance().absolutePath()
        if not dossier:
            source = bpe_layer.source()
            if source:
                dossier = os.path.dirname(source)
        if not dossier or not os.path.isdir(dossier):
            dossier = QFileDialog.getExistingDirectory(
                self.iface.mainWindow(),
                "Choisir le dossier de sortie"
            )
            if not dossier:
                return

        # Construire la sortie groupee
        chosen_set = set(chosen)
        bpe_output = {}
        for code in chosen:
            bpe_output[code] = {
                "type": bpe_data[code]["type"],
                "bats": []
            }

        for feat in st_layer.getFeatures():
            bpe_code = str(feat["code_bpe"]).strip()
            if bpe_code in chosen_set:
                bat = str(feat["code_st"]).strip()
                bpe_output[bpe_code]["bats"].append(bat)

        # Organiser : BPE de depart -> PBO enfants
        parents_in_output = set()
        children_by_parent = {}
        standalone = []

        for code in chosen:
            par = parent_of.get(code)
            if par and par in chosen_set:
                if par not in children_by_parent:
                    children_by_parent[par] = []
                children_by_parent[par].append(code)
                parents_in_output.add(par)
            elif code in hierarchy:
                parents_in_output.add(code)
                if code not in children_by_parent:
                    children_by_parent[code] = []
            else:
                standalone.append(code)

        # Ecrire le fichier
        fichier = os.path.join(
            dossier, "LISTE_DES_PBO.txt"
        )
        nb_pbo = 0
        nb_dep = 0

        with open(fichier, "w", encoding="utf-8") as f:
            # Groupes parent -> enfants
            for p_code in sorted(parents_in_output):
                p_info = bpe_output.get(p_code, {})
                p_type = p_info.get("type", "BPE")
                f.write(
                    p_code + "  (" + p_type
                    + " - BPE DE DEPART)\n"
                )
                for bat in sorted(
                    p_info.get("bats", [])
                ):
                    f.write("\t>" + bat + "\n")
                nb_dep = nb_dep + 1

                kids = children_by_parent.get(
                    p_code, []
                )
                for c_code in sorted(kids):
                    c_info = bpe_output.get(c_code, {})
                    c_type = c_info.get("type", "PBO")
                    f.write(
                        "  " + c_code + "  ("
                        + c_type + ")\n"
                    )
                    for bat in sorted(
                        c_info.get("bats", [])
                    ):
                        f.write("\t>" + bat + "\n")
                    if c_type == "PBO":
                        nb_pbo = nb_pbo + 1
                    else:
                        nb_dep = nb_dep + 1
                f.write("\n")

            # BPE standalone (sans parent detecte)
            for s_code in sorted(standalone):
                if s_code in parents_in_output:
                    continue
                s_info = bpe_output.get(s_code, {})
                s_type = s_info.get("type", "PBO")
                f.write(
                    s_code + "  (" + s_type + ")\n"
                )
                for bat in sorted(
                    s_info.get("bats", [])
                ):
                    f.write("\t>" + bat + "\n")
                f.write("\n")
                if s_type == "PBO":
                    nb_pbo = nb_pbo + 1
                else:
                    nb_dep = nb_dep + 1

        self.iface.messageBar().pushMessage(
            "Liste PBO",
            "Fichier genere : " + fichier
            + " (" + str(nb_pbo) + " PBO, "
            + str(nb_dep) + " BPE depart)",
            level=Qgis.Success, duration=10
        )

    def run_fibres(self):
        """Calcule les fibres utiles sur les cables DISTRIBUTION."""
        # 1. Charger les couches
        layers = QgsProject.instance().mapLayers().values()
        bpe_layer = None
        st_layer = None
        cb_layer = None

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            name = layer.name().upper()
            if name.endswith("_BPE"):
                bpe_layer = layer
            elif name.endswith("_ST"):
                st_layer = layer
            elif name.endswith("_CB"):
                cb_layer = layer

        if not cb_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CB trouvee."
            )
            return

        # 2. Detecter les colonnes CB
        cb_fields = [f.name() for f in cb_layer.fields()]

        def find_col(fields, patterns):
            for f in fields:
                fl = f.lower().strip()
                for p in patterns:
                    if p in fl:
                        return f
            return None

        col_orig = find_col(
            cb_fields, ["origine", "origin"]
        )
        col_extr = find_col(
            cb_fields, ["extremite", "extremit", "extr"]
        )

        if not col_orig or not col_extr:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Colonnes origine/extremite non trouvees "
                "dans la couche CB.\n\n"
                "Colonnes disponibles ("
                + str(len(cb_fields)) + ") :\n"
                + "\n".join(repr(f) for f in cb_fields)
            )
            return

        col_cb_type = find_col(
            cb_fields, ["type_fonc", "type_fon"]
        )
        col_cap = find_col(
            cb_fields, ["capacite", "capacit"]
        )
        col_fibre_u = find_col(
            cb_fields, ["fibre_u", "fibres_u", "fibre_utile"]
        )
        col_code_cb = find_col(
            cb_fields, ["code_cb", "code_cable"]
        )

        # 3. Compter les BAT par BPE (depuis couche ST)
        bpe_bats = {}
        if st_layer:
            for feat in st_layer.getFeatures():
                bpe_code = str(feat["code_bpe"]).strip()
                bpe_bats[bpe_code] = (
                    bpe_bats.get(bpe_code, 0) + 1
                )

        # 4. Construire le graphe descendant DISTRIBUTION
        # children : origine -> [extremites]
        children = {}
        cables_feats = []

        for feat in cb_layer.getFeatures():
            # Filtrer RACCORDEMENT
            is_raccord = False
            if col_cb_type:
                cb_type = str(
                    feat[col_cb_type]
                ).strip().upper()
                if cb_type == "RACCORDEMENT":
                    is_raccord = True
            elif col_cap:
                try:
                    cap = int(feat[col_cap])
                    if cap <= 1:
                        is_raccord = True
                except Exception:
                    pass

            if is_raccord:
                continue

            orig = str(feat[col_orig]).strip()
            extr = str(feat[col_extr]).strip()
            if not orig or not extr or orig == "NULL":
                continue

            fid = feat.id()
            code_cb = (
                str(feat[col_code_cb]).strip()
                if col_code_cb
                else "FID_" + str(fid)
            )

            fibre_u_actuel = None
            if col_fibre_u:
                try:
                    v = feat[col_fibre_u]
                    if v is not None and str(
                        v
                    ).strip() not in ("", "NULL"):
                        fibre_u_actuel = int(v)
                except Exception:
                    pass

            if orig not in children:
                children[orig] = []
            children[orig].append(extr)

            cables_feats.append(
                (fid, code_cb, orig, extr, fibre_u_actuel)
            )

        if not cables_feats:
            QMessageBox.information(
                self.iface.mainWindow(), "Fibres Utiles",
                "Aucun cable DISTRIBUTION trouve "
                "dans la couche CB."
            )
            return

        # 5. DFS iteratif : compter les BAT en aval d'un noeud
        def count_bats_downstream(start):
            visited = set()
            stack = [start]
            total = 0
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                total = total + bpe_bats.get(node, 0)
                for child in children.get(node, []):
                    if child not in visited:
                        stack.append(child)
            return total

        # 6. Calculer FU et capacite proposee pour chaque cable
        modifications = []
        total_cables = len(cables_feats)

        for fid, code_cb, orig, extr, fibre_u_actuel in (
            cables_feats
        ):
            fu = count_bats_downstream(extr)

            # Dimensionnement : marge 30%, arrondi tube (x6),
            # minimum 12 FO
            marge = math.ceil(fu * 1.3)
            tubes = math.ceil(marge / 6)
            capacite_proposee = max(tubes * 6, 12)

            if fibre_u_actuel is None:
                ecart = capacite_proposee
                sous_dim = True
            else:
                ecart = abs(capacite_proposee - fibre_u_actuel)
                sous_dim = capacite_proposee > fibre_u_actuel

            if ecart > 0:
                modifications.append({
                    "fid": fid,
                    "code": code_cb,
                    "fu": fu,
                    "actuel": fibre_u_actuel,
                    "propose": capacite_proposee,
                    "ecart": ecart,
                    "sous_dim": sous_dim,
                })

        # Trier par ecart decroissant
        modifications.sort(
            key=lambda x: x["ecart"], reverse=True
        )

        if not modifications:
            QMessageBox.information(
                self.iface.mainWindow(), "Fibres Utiles",
                "Aucune modification proposee.\n"
                "Tous les " + str(total_cables)
                + " cables sont correctement dimensionnes."
            )
            return

        # 7. Recuperer les codes CB selectionnes sur la carte
        selected_codes = set()
        for feat in cb_layer.selectedFeatures():
            if col_code_cb:
                v = str(feat[col_code_cb]).strip()
                if v and v != "NULL":
                    selected_codes.add(v)

        # 8. Ouvrir la fenetre de resultats
        dlg = FibresUtilesDialog(
            modifications, total_cables,
            selected_codes,
            self.iface.mainWindow()
        )
        if not dlg.exec():
            return

        chosen = dlg.get_chosen()
        if not chosen:
            self.iface.messageBar().pushMessage(
                "Fibres Utiles", "Aucun cable selectionne.",
                level=Qgis.Warning, duration=5
            )
            return

        if not col_fibre_u:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Colonne fibre_u introuvable dans CB.\n"
                "Impossible d'appliquer les modifications."
            )
            return

        # 8. Appliquer les modifications dans la couche CB
        idx_fu = cb_layer.fields().indexOf(col_fibre_u)
        cb_layer.startEditing()
        nb_modif = 0
        for fid, new_val in chosen:
            cb_layer.changeAttributeValue(fid, idx_fu, new_val)
            nb_modif = nb_modif + 1
        cb_layer.commitChanges()

        self.iface.messageBar().pushMessage(
            "Fibres Utiles",
            str(nb_modif)
            + " cable(s) mis a jour dans la couche CB.",
            level=Qgis.Success, duration=10
        )