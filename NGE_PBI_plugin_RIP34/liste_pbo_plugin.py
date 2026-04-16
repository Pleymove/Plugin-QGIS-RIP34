from qgis.PyQt.QtWidgets import (QAction, QFileDialog, QMessageBox,
                                  QMenu)
from qgis.PyQt.QtGui import QIcon, QCursor
from qgis.core import (QgsProject, Qgis, QgsVectorLayer,
                       QgsSpatialIndex, QgsFeatureRequest,
                       QgsGeometry)
from .liste_pbo_dialog import ListePBODialog
from .fibres_utiles_dialog import FibresUtilesDialog
from .ref_prop_dialog import RefPropDialog
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
        act_ref = menu.addAction(
            "Remplir REF PROP (appuis Orange)"
        )
        act_ref.triggered.connect(self.run_ref_prop)
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

        # 1b. Selection obligatoire
        if cb_layer.selectedFeatureCount() == 0:
            QMessageBox.information(
                self.iface.mainWindow(), "Fibres Utiles",
                "Veuillez d'abord selectionner au moins un cable\n"
                "dans la couche " + cb_layer.name()
                + " sur la carte,\n"
                "puis relancer le calcul."
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

        # FID des cables selectionnes sur la carte
        selected_fids = set(
            f.id() for f in cb_layer.selectedFeatures()
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

            if fid in selected_fids:
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

            modifications.append({
                "fid": fid,
                "code": code_cb,
                "fu": fu,
                "actuel": fibre_u_actuel,
                "propose": capacite_proposee,
                "ecart": ecart,
                "sous_dim": sous_dim,
                "ok": ecart == 0,
            })

        # Trier par ecart decroissant
        modifications.sort(
            key=lambda x: x["ecart"], reverse=True
        )

        # 7. Ouvrir la fenetre de resultats
        dlg = FibresUtilesDialog(
            modifications, len(cables_feats),
            iface=self.iface,
            cb_layer=cb_layer,
            parent=self.iface.mainWindow()
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

        reply = QMessageBox.question(
            self.iface.mainWindow(), "Confirmation",
            "Modifier fibre_u pour "
            + str(len(chosen)) + " cable(s) ?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
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

    def run_ref_prop(self):
        """Remplit REF_PROP des appuis CH via match spatial
        avec la couche ft_appui Orange.
        Convention : ORA_{num_appui}-{code_commu}
        """
        # 1. Trouver les 3 couches
        layers = list(
            QgsProject.instance().mapLayers().values()
        )
        cb_layer = None
        ch_layer = None
        ft_appui_layer = None

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            name = layer.name()
            name_up = name.upper()
            name_lo = name.lower()
            if name_up.endswith("_CB"):
                cb_layer = layer
            elif name_up.endswith("_CH"):
                ch_layer = layer
            elif "ft_appui" in name_lo:
                ft_appui_layer = layer

        if not cb_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CB trouvee."
            )
            return
        if not ch_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CH trouvee."
            )
            return
        if not ft_appui_layer:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche ft_appui trouvee.\n"
                "(cherche 'ft_appui' dans le nom de couche)"
            )
            return

        # 2. Selection obligatoire sur CB
        if cb_layer.selectedFeatureCount() == 0:
            QMessageBox.information(
                self.iface.mainWindow(), "REF PROP",
                "Veuillez d'abord selectionner au moins "
                "un cable\ndans la couche "
                + cb_layer.name()
                + " sur la carte,\npuis relancer l'outil."
            )
            return

        # 3. Detecter les colonnes
        def find_col(fields, patterns):
            for f in fields:
                fl = f.lower().strip()
                for p in patterns:
                    if p in fl:
                        return f
            return None

        ch_fields = [f.name() for f in ch_layer.fields()]
        col_ref_prop = find_col(
            ch_fields, ["ref_prop", "ref prop", "refprop"]
        )
        if not col_ref_prop:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Colonne ref_prop introuvable dans *_CH.\n"
                "Colonnes : " + ", ".join(ch_fields)
            )
            return

        ft_fields = [
            f.name() for f in ft_appui_layer.fields()
        ]
        col_num_appui = find_col(
            ft_fields, ["num_appui", "num appui"]
        )
        col_code_commu = find_col(
            ft_fields,
            ["code_commu", "code_comm", "code_insee"]
        )
        if not col_num_appui or not col_code_commu:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Colonnes num_appui / code_commu introuvables"
                " dans la couche ft_appui.\n"
                "Colonnes : " + ", ".join(ft_fields)
            )
            return

        # 4. Index spatial ft_appui
        ft_index = QgsSpatialIndex(
            ft_appui_layer.getFeatures()
        )
        ft_features = {}
        for feat in ft_appui_layer.getFeatures():
            ft_features[feat.id()] = feat

        # 5. Index spatial ch_layer
        ch_index = QgsSpatialIndex(ch_layer.getFeatures())
        ch_features = {}
        for feat in ch_layer.getFeatures():
            ch_features[feat.id()] = feat

        # 6. Pour chaque cable selectionne, trouver les
        #    appuis CH dans un buffer de 2 m, puis
        #    matcher avec ft_appui (seuil 5 m)
        # best_match : ch_fid -> {distance, ref_prop, ...}
        best_match = {}

        for cable_feat in cb_layer.selectedFeatures():
            cable_geom = cable_feat.geometry()
            if cable_geom.isEmpty():
                continue
            buffer_geom = cable_geom.buffer(2, 5)
            bbox = buffer_geom.boundingBox()

            for ch_fid in ch_index.intersects(bbox):
                ch_feat = ch_features.get(ch_fid)
                if not ch_feat:
                    continue
                if not buffer_geom.intersects(
                    ch_feat.geometry()
                ):
                    continue

                # Chercher l'appui Orange le plus proche
                nearest = ft_index.nearestNeighbor(
                    ch_feat.geometry().asPoint(), 1
                )
                if not nearest:
                    continue
                ft_feat = ft_features.get(nearest[0])
                if not ft_feat:
                    continue
                dist = ch_feat.geometry().distance(
                    ft_feat.geometry()
                )
                if dist > 5.0:
                    continue

                num_appui = str(
                    ft_feat[col_num_appui]
                ).strip()
                code_commu = str(
                    ft_feat[col_code_commu]
                ).strip()
                ref_prop = (
                    "ORA_" + num_appui + "-" + code_commu
                )

                # Dédupliquer : garder le match le + proche
                if ch_fid not in best_match or (
                    dist < best_match[ch_fid]["distance"]
                ):
                    actuel_raw = ch_feat[col_ref_prop]
                    actuel = (
                        str(actuel_raw).strip()
                        if actuel_raw is not None
                        and str(actuel_raw).strip()
                        not in ("", "NULL")
                        else ""
                    )
                    best_match[ch_fid] = {
                        "ch_fid": ch_fid,
                        "ref_prop": ref_prop,
                        "num_appui": num_appui,
                        "code_commu": code_commu,
                        "distance": round(dist, 2),
                        "actuel": actuel,
                    }

        modifications = list(best_match.values())
        modifications.sort(key=lambda x: x["distance"])

        # 7. Ouvrir le dialog
        if not modifications:
            QMessageBox.information(
                self.iface.mainWindow(), "REF PROP",
                "Aucun appui a mettre a jour sur les "
                "cables selectionnes."
            )
            return

        dlg = RefPropDialog(
            modifications,
            iface=self.iface,
            ch_layer=ch_layer,
            parent=self.iface.mainWindow()
        )
        if not dlg.exec():
            return

        # 8. Appliquer
        chosen = dlg.get_chosen()
        if not chosen:
            self.iface.messageBar().pushMessage(
                "REF PROP", "Aucun appui selectionne.",
                level=Qgis.Warning, duration=5
            )
            return

        reply = QMessageBox.question(
            self.iface.mainWindow(), "Confirmation",
            "Remplir REF_PROP pour "
            + str(len(chosen)) + " appui(s) ?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        idx = ch_layer.fields().indexOf(col_ref_prop)
        ch_layer.startEditing()
        for ch_fid, ref_prop_val in chosen:
            ch_layer.changeAttributeValue(
                ch_fid, idx, ref_prop_val
            )
        ch_layer.commitChanges()

        self.iface.messageBar().pushMessage(
            "REF PROP",
            str(len(chosen))
            + " appui(s) REF_PROP mis a jour.",
            level=Qgis.Success, duration=10
        )