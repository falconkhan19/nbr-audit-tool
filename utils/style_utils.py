"""
style_utils.py

Applies graduated or categorized symbology to a vector layer (automatic
classification only - user picks the field, class count/method/ramp for
graduated, or ramp for categorized), and loading a previously saved .qml
style file.
"""

from qgis.core import (
    QgsGraduatedSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsClassificationEqualInterval,
    QgsClassificationQuantile,
    QgsClassificationJenks,
    QgsClassificationPrettyBreaks,
    QgsStyle,
    QgsGradientColorRamp,
)
from qgis.PyQt.QtGui import QColor

CLASSIFICATION_METHODS = {
    "Equal Interval": QgsClassificationEqualInterval,
    "Quantile": QgsClassificationQuantile,
    "Jenks Natural Breaks": QgsClassificationJenks,
    "Pretty Breaks": QgsClassificationPrettyBreaks,
}


def apply_graduated_style(layer, field, num_classes=5, method_name="Equal Interval",
                           ramp_name="Spectral"):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())

    renderer = QgsGraduatedSymbolRenderer()
    renderer.setClassAttribute(field)
    method_cls = CLASSIFICATION_METHODS.get(method_name, QgsClassificationEqualInterval)
    renderer.setClassificationMethod(method_cls())

    style = QgsStyle().defaultStyle()
    ramp = style.colorRamp(ramp_name)
    if ramp is None:
        ramp = QgsGradientColorRamp(QColor(255, 255, 178), QColor(189, 0, 38))

    renderer.updateClasses(layer, num_classes)
    renderer.updateColorRamp(ramp)
    renderer.setSourceSymbol(symbol)

    layer.setRenderer(renderer)
    layer.triggerRepaint()


def apply_categorized_style(layer, field, ramp_name="Set1"):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())

    unique_vals = sorted({str(f[field]) for f in layer.getFeatures()}) if layer.featureCount() else []

    style = QgsStyle().defaultStyle()
    ramp = style.colorRamp(ramp_name)

    categories = []
    n = max(len(unique_vals), 1)
    for i, val in enumerate(unique_vals):
        sym = symbol.clone()
        if ramp is not None:
            color = ramp.color(i / max(n - 1, 1))
        else:
            # deterministic fallback so re-styling is stable, not random each time
            h = (hash(val) % 360 + 360) % 360
            color = QColor.fromHsv(h, 200, 220)
        sym.setColor(color)
        categories.append(QgsRendererCategory(val, sym, str(val)))

    renderer = QgsCategorizedSymbolRenderer(field, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def apply_single_color_style(layer, hex_color, outline_hex_color="#000000", opacity=0.6):
    """
    Flat single-symbol style used to highlight the audit source cell
    (yellow) and its relation cells (green) so they're visually distinct
    from the rest of the map.
    """
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(QColor(hex_color))
    symbol.setOpacity(opacity)
    try:
        symbol.symbolLayer(0).setStrokeColor(QColor(outline_hex_color))
    except Exception:
        pass
    renderer = QgsSingleSymbolRenderer(symbol)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def load_saved_style(layer, qml_path):
    """Apply a previously saved .qml style file to the layer."""
    result = layer.loadNamedStyle(qml_path)
    ok = result[1] if isinstance(result, tuple) else bool(result)
    layer.triggerRepaint()
    return ok
