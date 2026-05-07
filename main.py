import logging
import sys
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(threadName)s/%(thread)d] %(name)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("QuickPic")
    app.setOrganizationName("QuickPic")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
