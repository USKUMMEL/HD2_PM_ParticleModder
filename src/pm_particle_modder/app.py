from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from pm_particle_modder import __version__
from pm_particle_modder.application import ParticleController


def main() -> int:
    QCoreApplication.setOrganizationName("Personal Modder")
    QCoreApplication.setApplicationName("PM ParticleModder")
    QCoreApplication.setApplicationVersion(__version__)
    QQuickStyle.setStyle("Basic")

    app = QApplication(sys.argv)
    package_dir = Path(__file__).resolve().parent
    icon_path = package_dir / "ui" / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    controller = ParticleController(app)
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("controller", controller)
    context.setContextProperty("documentsModel", controller.documents_model)
    context.setContextProperty("colorModel", controller.color_model)
    context.setContextProperty("opacityModel", controller.opacity_model)
    context.setContextProperty("intensityModel", controller.intensity_model)
    context.setContextProperty("visualizerModel", controller.visualizer_model)

    qml_path = package_dir / "ui" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

