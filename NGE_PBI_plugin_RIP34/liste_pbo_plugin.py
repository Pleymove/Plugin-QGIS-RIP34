from qgis.PyQt.QtWidgets import (QAction, QFileDialog, QMessageBox,
                                  QMenu)
from qgis.PyQt.QtGui import QIcon, QCursor
from qgis.core import (QgsProject, Qgis, QgsVectorLayer,
                       QgsSpatialIndex, QgsFeatureRequest,
                       QgsGeometry, QgsFeature,
                       QgsCoordinateTransform)
from .liste_pbo_dialog import ListePBODialog
from .fibres_utiles_dialog import FibresUtilesDialog
from .ref_prop_dialog import RefPropDialog
from .renommage_apd_dialog import RenommageAPDDialog
import os
import math
import re
import shutil


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
        act_rename = menu.addAction(
            "Renommer APS \u2192 APD"
        )
        act_rename.triggered.connect(self.run_renommage_apd)
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
        # Chercher les couches BPE, ST et CB (multi-SRO)
        layers = QgsProject.instance().mapLayers().values()
        bpe_layers = []
        st_layers = []
        cb_layers = []

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            name = layer.name().upper()
            if name.endswith("_BPE"):
                bpe_layers.append(layer)
            elif name.endswith("_ST"):
                st_layers.append(layer)
            elif name.endswith("_CB"):
                cb_layers.append(layer)

        if not bpe_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_BPE trouvee."
            )
            return
        if not st_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_ST trouvee."
            )
            return
        if not cb_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CB trouvee.\n"
                "(necessaire pour detecter les BPE de depart)"
            )
            return

        # BPE selectionnes sur la carte
        selected_codes = set()
        for bpe_l in bpe_layers:
            for feat in bpe_l.selectedFeatures():
                selected_codes.add(
                    str(feat["code_bpe"]).strip()
                )

        # Compter les BAT par BPE
        bpe_bats = {}
        for st_l in st_layers:
            for feat in st_l.getFeatures():
                bpe_code = str(feat["code_bpe"]).strip()
                if bpe_code not in bpe_bats:
                    bpe_bats[bpe_code] = 0
                bpe_bats[bpe_code] = bpe_bats[bpe_code] + 1

        # Construire donnees BPE
        bpe_data = {}
        bpe_types = {}  # code -> type_fonc brut

        for bpe_l in bpe_layers:
            for feat in bpe_l.getFeatures():
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
        cb_fields = [f.name() for f in cb_layers[0].fields()]

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
        for cb_l in cb_layers:
            for feat in cb_l.getFeatures():
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
            source = bpe_layers[0].source()
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

        for st_l in st_layers:
            for feat in st_l.getFeatures():
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
        # 1. Charger les couches (multi-SRO)
        layers = QgsProject.instance().mapLayers().values()
        bpe_layers = []
        st_layers = []
        cb_layers = []

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            name = layer.name().upper()
            if name.endswith("_BPE"):
                bpe_layers.append(layer)
            elif name.endswith("_ST"):
                st_layers.append(layer)
            elif name.endswith("_CB"):
                cb_layers.append(layer)

        if not cb_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CB trouvee."
            )
            return

        # 1b. Selection obligatoire (toutes couches CB)
        total_selected = sum(
            l.selectedFeatureCount() for l in cb_layers
        )
        if total_selected == 0:
            cb_names = ", ".join(l.name() for l in cb_layers)
            QMessageBox.information(
                self.iface.mainWindow(), "Fibres Utiles",
                "Veuillez d'abord selectionner au moins un cable\n"
                "dans une couche CB (" + cb_names
                + ") sur la carte,\n"
                "puis relancer le calcul."
            )
            return

        # 2. Detecter les colonnes CB
        cb_fields = [f.name() for f in cb_layers[0].fields()]

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

        # FID des cables selectionnes + mapping vers leur couche
        selected_fids = set()
        fid_to_cb_layer = {}
        for cb_l in cb_layers:
            for feat in cb_l.selectedFeatures():
                selected_fids.add(feat.id())
                fid_to_cb_layer[feat.id()] = cb_l

        # 3. Compter les BAT par BPE (depuis couche ST)
        bpe_bats = {}
        for st_l in st_layers:
            for feat in st_l.getFeatures():
                bpe_code = str(feat["code_bpe"]).strip()
                bpe_bats[bpe_code] = (
                    bpe_bats.get(bpe_code, 0) + 1
                )

        # 4. Construire le graphe descendant DISTRIBUTION
        # children : origine -> [extremites]
        children = {}
        cables_feats = []

        for cb_l in cb_layers:
            for feat in cb_l.getFeatures():
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
                        (fid, code_cb, orig, extr,
                         fibre_u_actuel)
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
            cb_layer=cb_layers[0],
            fid_to_layer=fid_to_cb_layer,
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

        # 8. Appliquer les modifications par couche CB source
        by_layer = {}
        for fid, new_val in chosen:
            lyr = fid_to_cb_layer.get(fid, cb_layers[0])
            if lyr not in by_layer:
                by_layer[lyr] = []
            by_layer[lyr].append((fid, new_val))

        nb_modif = 0
        for lyr, changes in by_layer.items():
            idx_fu = lyr.fields().indexOf(col_fibre_u)
            lyr.startEditing()
            for fid, new_val in changes:
                lyr.changeAttributeValue(
                    fid, idx_fu, new_val
                )
                nb_modif = nb_modif + 1
            lyr.commitChanges()

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
        # 1. Trouver les couches (multi-SRO)
        layers = list(
            QgsProject.instance().mapLayers().values()
        )
        cb_layers = []
        ch_layers = []
        ft_appui_layers = []

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            name = layer.name()
            name_up = name.upper()
            name_lo = name.lower()
            if name_up.endswith("_CB"):
                cb_layers.append(layer)
            elif name_up.endswith("_CH"):
                ch_layers.append(layer)
            elif "ft_appui" in name_lo:
                ft_appui_layers.append(layer)

        if not cb_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CB trouvee."
            )
            return
        if not ch_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche *_CH trouvee."
            )
            return
        if not ft_appui_layers:
            QMessageBox.warning(
                self.iface.mainWindow(), "Erreur",
                "Aucune couche ft_appui trouvee.\n"
                "(cherche 'ft_appui' dans le nom de couche)"
            )
            return

        # 2. Selection obligatoire sur CB (toutes couches)
        total_selected = sum(
            l.selectedFeatureCount() for l in cb_layers
        )
        if total_selected == 0:
            cb_names = ", ".join(l.name() for l in cb_layers)
            QMessageBox.information(
                self.iface.mainWindow(), "REF PROP",
                "Veuillez d'abord selectionner au moins "
                "un cable\ndans une couche CB ("
                + cb_names
                + ") sur la carte,\npuis relancer l'outil."
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

        ch_fields = [f.name() for f in ch_layers[0].fields()]
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

        col_type_struc = find_col(ch_fields, ["type_struc"])

        ft_fields = [
            f.name() for f in ft_appui_layers[0].fields()
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

        # Reprojection : tout en CRS de CB (reference commune)
        project_instance = QgsProject.instance()
        cb_crs = cb_layers[0].crs()

        # Transforms par couche CH et ft_appui
        ch_transforms = {}
        for ch_l in ch_layers:
            if ch_l.crs() != cb_crs:
                ch_transforms[ch_l.id()] = (
                    QgsCoordinateTransform(
                        ch_l.crs(), cb_crs, project_instance
                    )
                )
        ft_transforms = {}
        for ft_l in ft_appui_layers:
            if ft_l.crs() != cb_crs:
                ft_transforms[ft_l.id()] = (
                    QgsCoordinateTransform(
                        ft_l.crs(), cb_crs, project_instance
                    )
                )

        # 4. Index spatial ft_appui (geometries en CRS CB)
        ft_index = QgsSpatialIndex()
        ft_features = {}
        ft_geoms = {}
        for ft_l in ft_appui_layers:
            ft_tr = ft_transforms.get(ft_l.id())
            for feat in ft_l.getFeatures():
                geom = QgsGeometry(feat.geometry())
                if ft_tr:
                    geom.transform(ft_tr)
                idx_feat = QgsFeature(feat.id())
                idx_feat.setGeometry(geom)
                ft_index.addFeature(idx_feat)
                ft_features[feat.id()] = feat
                ft_geoms[feat.id()] = geom

        # 5. Charger les appuis CH POTEAUX uniquement (CRS CB)
        ch_features = {}
        ch_geoms = {}
        ch_fid_to_layer = {}
        for ch_l in ch_layers:
            ch_tr = ch_transforms.get(ch_l.id())
            for feat in ch_l.getFeatures():
                if col_type_struc:
                    type_struc = str(
                        feat[col_type_struc]
                    ).strip().upper()
                    if type_struc != "POTEAU":
                        continue
                geom = QgsGeometry(feat.geometry())
                if ch_tr:
                    geom.transform(ch_tr)
                ch_features[feat.id()] = feat
                ch_geoms[feat.id()] = geom
                ch_fid_to_layer[feat.id()] = ch_l

        # 6. Collecter les geometries des cables selectionnes
        selected_cable_geoms = []
        for cb_l in cb_layers:
            for feat in cb_l.selectedFeatures():
                g = feat.geometry()
                if not g.isEmpty():
                    selected_cable_geoms.append(g)

        if not selected_cable_geoms:
            QMessageBox.warning(
                self.iface.mainWindow(), "REF PROP",
                "Aucun cable selectionne avec geometrie valide."
            )
            return

        SEUIL_CABLE = 10.0   # metres : appui CH sur/pres du cable
        SEUIL_FT = 15.0      # metres : tolerance appui Orange vs CH

        # 7. Pour chaque appui CH, distance min aux cables
        #    selectionnes (tout en CRS CB)
        modifications = {}
        for ch_fid, ch_geom in ch_geoms.items():
            min_dist_cable = min(
                ch_geom.distance(cg)
                for cg in selected_cable_geoms
            )
            if min_dist_cable > SEUIL_CABLE:
                continue

            # Appui proche d'un cable : chercher ft_appui voisin
            nearest = ft_index.nearestNeighbor(
                ch_geom.asPoint(), 1
            )
            if not nearest:
                continue
            ft_fid = nearest[0]
            ft_geom = ft_geoms.get(ft_fid)
            ft_data = ft_features.get(ft_fid)
            if not ft_geom or not ft_data:
                continue
            dist_ft = ch_geom.distance(ft_geom)
            if dist_ft > SEUIL_FT:
                continue

            num_appui = str(int(str(
                ft_data[col_num_appui]
            ).strip()))
            code_commu = str(
                ft_data[col_code_commu]
            ).strip()
            ref_prop_new = (
                "ORA_" + num_appui + "-" + code_commu
            )

            ch_data = ch_features[ch_fid]
            actuel_raw = ch_data[col_ref_prop]
            actuel = (
                str(actuel_raw).strip()
                if actuel_raw is not None
                and str(actuel_raw).strip()
                not in ("", "NULL", "None")
                else ""
            )

            if ch_fid not in modifications or (
                dist_ft < modifications[ch_fid]["distance"]
            ):
                modifications[ch_fid] = {
                    "ch_fid": ch_fid,
                    "ref_prop": ref_prop_new,
                    "num_appui": num_appui,
                    "code_commu": code_commu,
                    "distance": round(dist_ft, 2),
                    "actuel": actuel,
                }

        modifications = list(modifications.values())
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
            ch_layer=ch_layers[0],
            ch_fid_to_layer=ch_fid_to_layer,
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

        by_layer = {}
        for ch_fid, ref_prop_val in chosen:
            lyr = ch_fid_to_layer.get(ch_fid, ch_layers[0])
            if lyr not in by_layer:
                by_layer[lyr] = []
            by_layer[lyr].append((ch_fid, ref_prop_val))

        for lyr, changes in by_layer.items():
            idx = lyr.fields().indexOf(col_ref_prop)
            lyr.startEditing()
            for ch_fid, ref_prop_val in changes:
                lyr.changeAttributeValue(
                    ch_fid, idx, ref_prop_val
                )
            lyr.commitChanges()

        self.iface.messageBar().pushMessage(
            "REF PROP",
            str(len(chosen))
            + " appui(s) REF_PROP mis a jour.",
            level=Qgis.Success, duration=10
        )

    def run_renommage_apd(self):
        """Renomme les couches APS -> APD dans QGIS
        et sur le disque (shapefile).
        """
        # 1. Scanner les couches dont le nom contient "-APS-"
        candidates = []
        for layer in (
            QgsProject.instance().mapLayers().values()
        ):
            name = layer.name()
            if re.search(r"-APS-", name, re.IGNORECASE):
                new_name = re.sub(
                    r"-APS-", "-APD-", name,
                    flags=re.IGNORECASE
                )
                candidates.append({
                    "layer": layer,
                    "old_name": name,
                    "new_name": new_name,
                })

        if not candidates:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Renommage APS \u2192 APD",
                "Aucune couche contenant '-APS-' "
                "trouvee dans le projet."
            )
            return

        # 2. Ouvrir le dialog de selection
        dlg = RenommageAPDDialog(
            candidates, self.iface.mainWindow()
        )
        if not dlg.exec():
            return

        chosen = dlg.get_chosen()
        if not chosen:
            self.iface.messageBar().pushMessage(
                "Renommage APS \u2192 APD",
                "Aucune couche selectionnee.",
                level=Qgis.Warning, duration=5
            )
            return

        # 3. Confirmation (operation irreversible)
        reply = QMessageBox.question(
            self.iface.mainWindow(), "Confirmation",
            "Renommer " + str(len(chosen))
            + " couche(s) APS \u2192 APD ?\n\n"
            "Cette operation renomme les fichiers "
            "sur le disque et est irreversible.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 4. Appliquer le renommage
        nb_ok = 0
        nb_err = 0
        SHP_EXTS = [
            ".shp", ".shx", ".dbf", ".prj",
            ".cpg", ".qix", ".qpj", ".sbn", ".sbx",
        ]

        for item in chosen:
            layer = item["layer"]
            old_name = item["old_name"]
            new_name = item["new_name"]

            # Extraire le chemin source (avant '|' eventuel)
            source = layer.source().split("|")[0].strip()
            is_shp = source.lower().endswith(".shp")

            if not is_shp:
                # Format non-shapefile : renommage QGIS seul
                layer.setName(new_name)
                nb_ok += 1
                continue

            dir_path = os.path.dirname(source)
            old_stem = os.path.splitext(
                os.path.basename(source)
            )[0]
            new_stem = re.sub(
                r"-APS-", "-APD-", old_stem,
                flags=re.IGNORECASE
            )

            if old_stem == new_stem:
                # Le nom de fichier ne contient pas -APS-
                # (nom QGIS seul change)
                layer.setName(new_name)
                nb_ok += 1
                continue

            new_shp = os.path.join(
                dir_path, new_stem + ".shp"
            )
            if os.path.exists(new_shp):
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Renommage APS \u2192 APD",
                    "Fichier deja existant, couche ignoree :\n"
                    + new_shp
                )
                nb_err += 1
                continue

            # Renommer tous les fichiers associes
            try:
                for ext in SHP_EXTS:
                    old_f = os.path.join(
                        dir_path, old_stem + ext
                    )
                    if os.path.exists(old_f):
                        shutil.move(
                            old_f,
                            os.path.join(
                                dir_path, new_stem + ext
                            )
                        )
            except OSError as e:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Renommage APS \u2192 APD",
                    "Erreur fichier pour '"
                    + old_name + "' :\n" + str(e)
                )
                nb_err += 1
                continue

            # Supprimer l'ancienne couche et recharger
            QgsProject.instance().removeMapLayer(
                layer.id()
            )
            new_layer = QgsVectorLayer(
                new_shp, new_name, "ogr"
            )
            if new_layer.isValid():
                QgsProject.instance().addMapLayer(
                    new_layer
                )
                nb_ok += 1
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Renommage APS \u2192 APD",
                    "Couche rechargee invalide : "
                    + new_name
                )
                nb_err += 1

        # 5. Message de resultat
        msg = str(nb_ok) + " couche(s) renommee(s)."
        if nb_err:
            msg += " " + str(nb_err) + " erreur(s)."
        self.iface.messageBar().pushMessage(
            "Renommage APS \u2192 APD",
            msg,
            level=(
                Qgis.Success if nb_ok > 0
                else Qgis.Warning
            ),
            duration=10
        )