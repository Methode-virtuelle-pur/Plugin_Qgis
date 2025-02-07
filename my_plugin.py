# -*- coding: utf-8 -*-
"""
/***************************************************************************
 MyPlugin
                                 A QGIS plugin
 Plugin de visualisation
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2025-02-06
        git sha              : $Format:%H$
        copyright            : (C) 2025 by Antoine Anquetil
        email                : antoine.anquetil@ensg.eu
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
# Imports PyQt (Interface utilisateur)
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QComboBox

# Imports QGIS (Géométrie, Cartographie, Analyse)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsFeatureRequest, QgsGeometry, QgsMessageLog, Qgis,
    QgsFeature, QgsField, QgsFillSymbol, QgsSymbol, QgsSingleSymbolRenderer
)

# Imports GUI QGIS (Outils interactifs)
from qgis.gui import QgsMapTool, QgsMessageBar

# Import PyQt (Correction de la virgule en trop)
from PyQt5.QtCore import Qt

# Import de la gestion des requêtes HTTP (ex: géocodage)
import requests


# Initialize Qt resources from file resources.py
from .resources import *
# Import the code for the dialog
from .my_plugin_dialog import MyPluginDialog
import os.path





class PointClickTool(QgsMapTool):
    def __init__(self, iface, plugin):
        """Initialisation de l'outil de clic"""
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.plugin = plugin  # Référence à MyPlugin
        self.buffer_layer = None  # Stocke la couche temporaire


    def create_or_clear_buffer_layer(self):
        """Crée une couche temporaire pour le buffer si elle n'existe pas encore, sinon la vide"""
        if self.buffer_layer is None:
            # Créer une couche temporaire vectorielle de type polygone
            self.buffer_layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "Buffer Temporaire", "memory")
            self.buffer_layer.dataProvider().addAttributes([QgsField("id", QVariant.Int)])
            self.buffer_layer.updateFields()

            # Ajouter un style : contour noir, remplissage transparent
            symbol = QgsFillSymbol.createSimple({
                'color': 'transparent',  # Remplissage transparent
                'outline_color': '#000000',  # Contour noir
                'outline_width': '1'  # Ligne fine
            })

            self.buffer_layer.renderer().setSymbol(symbol)

            # Ajouter la couche à la carte
            QgsProject.instance().addMapLayer(self.buffer_layer)

        # Supprimer les anciennes géométries
        self.buffer_layer.startEditing()
        self.buffer_layer.dataProvider().truncate()  # Efface tout
        self.buffer_layer.commitChanges()


    def canvasReleaseEvent(self, event):
        """Détecte le clic et effectue l'analyse des objets autour"""
        try:
            # Récupérer les coordonnées du clic
            point = self.canvas.getCoordinateTransform().toMapCoordinates(event.pos().x(), event.pos().y())

            # Convertir en WGS84 (EPSG:4326)
            crs_src = self.canvas.mapSettings().destinationCrs()
            crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform_to_wgs84 = QgsCoordinateTransform(crs_src, crs_wgs84, QgsProject.instance())
            point_wgs84 = transform_to_wgs84.transform(point)

            # Mettre à jour les labels avec les coordonnées
            self.plugin.dlg.longitude.setText(f"Longitude: {point_wgs84.x():.6f}")
            self.plugin.dlg.latitude.setText(f"Latitude: {point_wgs84.y():.6f}")

            # Récupérer la distance entrée par l'utilisateur
            distance_text = self.plugin.dlg.distance.text()
            try:
                buffer_distance = float(distance_text)
                if buffer_distance <= 0:
                    raise ValueError("La distance doit être positive.")
            except ValueError:
                self.iface.messageBar().pushMessage("Erreur", "Distance invalide. Veuillez entrer un nombre positif.", level=Qgis.Critical, duration=5)
                return

            # Transformer le point vers un CRS projeté en mètres (EPSG:3857)
            crs_meters = QgsCoordinateReferenceSystem("EPSG:3857")
            transform_to_meters = QgsCoordinateTransform(crs_src, crs_meters, QgsProject.instance())
            point_meters = transform_to_meters.transform(point)

            # Créer un buffer correctement projeté en mètres
            point_geom = QgsGeometry.fromPointXY(QgsPointXY(point_meters))
            buffer_geom = point_geom.buffer(buffer_distance, 50)  # 50 segments pour un buffer lisse

            # Ajouter le buffer à la couche temporaire
            self.create_or_clear_buffer_layer()  # Assurer que la couche est prête

            self.buffer_layer.startEditing()
            feature = QgsFeature()
            feature.setGeometry(buffer_geom)
            feature.setAttributes([1])  # Ajoute un ID unique
            self.buffer_layer.addFeature(feature)
            self.buffer_layer.commitChanges()

            # Récupérer la couche sélectionnée
            selected_layer_name = self.plugin.dlg.ponctuelle.currentText()
            layer = None
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.name() == selected_layer_name:
                    layer = lyr
                    break

            if not layer:
                self.iface.messageBar().pushMessage("Erreur", "Aucune couche sélectionnée.", level=Qgis.Critical, duration=5)
                return

            # Vérifier si le CRS de la couche est en mètres
            crs_layer = layer.crs()
            if crs_layer.isGeographic():
                # Transformer le buffer vers le CRS de la couche sélectionnée
                transform_to_layer = QgsCoordinateTransform(crs_meters, crs_layer, QgsProject.instance())
                buffer_geom.transform(transform_to_layer)

            # Vérifier les objets intersectant le buffer
            request = QgsFeatureRequest().setFilterRect(buffer_geom.boundingBox())
            count = 0
            for feature in layer.getFeatures(request):
                if feature.geometry().intersects(buffer_geom):
                    count += 1

            # Mettre à jour le label avec le nombre d'objets trouvés
            self.plugin.dlg.objet.setText(f"Il y a : {count}")

            # Rafraîchir la carte pour voir la mise à jour
            self.canvas.refresh()

        except Exception as e:
            self.iface.messageBar().pushMessage("Erreur", f"Une erreur est survenue : {str(e)}", level=Qgis.Critical, duration=5)

        
        


class MyPlugin:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'MyPlugin_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Plugin_Cool')

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('MyPlugin', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/my_plugin/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Menu de fous'),
            callback=self.run,
            parent=self.iface.mainWindow())

        # will be set False in run()
        self.first_start = True


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Plugin_Cool'),
                action)
            self.iface.removeToolBarIcon(action)


    def run(self):
        """Run method that performs all the real work"""

        # Create the dialog with elements (after translation) and keep reference
        # Only create GUI ONCE in callback, so that it will only load when the plugin is started
        if self.first_start == True:
            self.first_start = False
            self.dlg = MyPluginDialog()

        # Récupérer toutes les couches du projet
        layers = QgsProject.instance().mapLayers().values()

        # Filtrer uniquement les couches de type "Point"
        point_layers = [
            layer for layer in layers
            if isinstance(layer, QgsVectorLayer) and layer.wkbType() == QgsWkbTypes.Point
        ]

        # Ajouter les noms des couches au combo
        for layer in point_layers:
            self.dlg.ponctuelle.addItem(layer.name())



        # Activer l'outil de clic personnalisé
        self.click_tool = PointClickTool(self.iface, self)
        self.iface.mapCanvas().setMapTool(self.click_tool)

        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result:
            # Do something useful here - delete the line containing pass and
            # substitute with your code.
            pass

