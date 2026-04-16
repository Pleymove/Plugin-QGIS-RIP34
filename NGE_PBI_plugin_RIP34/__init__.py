def classFactory(iface):
    from .liste_pbo_plugin import ListePBOPlugin
    return ListePBOPlugin(iface)