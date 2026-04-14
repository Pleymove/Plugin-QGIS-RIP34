from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox
from qgis.core import QgsProject, Qgis
from .liste_pbo_dialog import ListePBODialog
import os


class ListePBOPlugin:
    """v3 - Hierarchie BPE depart via couche CB (cables)."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        self.action = QAction(
            "Generer LISTE DES PBO",
            self.iface.mainWindow()
        )
        self.action.setToolTip(
            "v3 - LISTE_DES_PBO.txt avec BPE de depart"
        )
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Liste PBO", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("Liste PBO", self.action)

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

        # Construire le graphe cable : extremite -> origine
        # (uniquement cables DISTRIBUTION, pas RACCORDEMENT)
        cb_fields = [f.name() for f in cb_layer.fields()]
        has_cb_type = "type_fonc" in cb_fields
        cables_to = {}  # extremite -> origine
        for feat in cb_layer.getFeatures():
            # Filtrer RACCORDEMENT si la colonne existe
            if has_cb_type:
                cb_type = str(feat["type_fonc"]).strip().upper()
                if cb_type == "RACCORDEMENT":
                    continue
            else:
                # Pas de colonne type_fonc : filtrer par
                # capacite (1 FO = raccordement)
                try:
                    cap = int(feat["capacite"])
                    if cap <= 1:
                        continue
                except Exception:
                    pass
            orig = str(feat["origine"]).strip()
            extr = str(feat["extremite"]).strip()
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