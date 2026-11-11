"""Aplicación de escritorio de Rell Engine (PySide6)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engine import Engine, GenerationError, render_text
from .export import export_file, export_json

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QSplitter,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    print(
        "La interfaz necesita PySide6. Instálalo con:  pip install PySide6\n"
        "También puedes usar la línea de comandos:      python rell.py --help",
        file=sys.stderr,
    )
    raise SystemExit(1)

ANY = "Cualquiera"


def app_root() -> Path:
    if getattr(sys, "frozen", False):  # ejecutable creado con PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class MainWindow(QMainWindow):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.engine = Engine(root)
        self.items: List[Dict[str, Any]] = []
        self.setWindowTitle("Rell Engine")
        self.resize(1050, 680)
        icon = root / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        tabs = QTabWidget()
        tabs.addTab(self._build_generate_tab(), "Generar")
        tabs.addTab(self._build_expansions_tab(), "Expansiones")
        self.tabs = tabs
        self.setCentralWidget(tabs)
        self._refresh_from_engine()

    # ---------------------------------------------------------- pestaña Generar
    def _build_generate_tab(self) -> QWidget:
        self.cmb_tag = QComboBox()
        self.cmb_type = QComboBox()
        self.cmb_object = QComboBox()
        self.cmb_rarity = QComboBox()
        self.cmb_bad = QComboBox()
        self.cmb_bad.addItem("Según la rareza", None)
        self.cmb_bad.addItem("Maldito (al menos uno)", True)
        self.cmb_bad.addItem("Ninguno", False)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 50)
        self.chk_debug = QCheckBox("Mostrar costes y tablas de origen")
        self.cmb_tag.currentIndexChanged.connect(self._fill_types)
        self.cmb_type.currentIndexChanged.connect(self._fill_objects)
        self.chk_debug.toggled.connect(self._show_selected)

        form = QFormLayout()
        form.addRow("Categoría", self.cmb_tag)
        form.addRow("Tipo", self.cmb_type)
        form.addRow("Objeto base", self.cmb_object)
        form.addRow("Rareza", self.cmb_rarity)
        form.addRow("Efectos negativos", self.cmb_bad)
        form.addRow("Cantidad", self.spin_count)
        box = QGroupBox("Qué generar")
        box.setLayout(form)

        btn_generate = QPushButton("Generar")
        btn_generate.setDefault(True)
        btn_generate.setMinimumHeight(38)
        btn_generate.clicked.connect(self.on_generate)

        left = QVBoxLayout()
        left.addWidget(box)
        left.addWidget(self.chk_debug)
        left.addWidget(btn_generate)
        left.addStretch(1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(320)

        self.lst_items = QListWidget()
        self.lst_items.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.lst_items.itemSelectionChanged.connect(self._show_selected)
        self.txt_item = QPlainTextEdit()
        self.txt_item.setReadOnly(True)
        self.txt_item.setPlaceholderText("Pulsa «Generar» para crear objetos. Aparecerán en la lista de la izquierda.")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.lst_items)
        splitter.addWidget(self.txt_item)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        def button(text: str, slot: Any, tip: str = "") -> QPushButton:
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setToolTip(tip)
            return b

        row = QHBoxLayout()
        row.addWidget(button("Copiar texto", self.on_copy_text))
        row.addWidget(button("Quitar", self.on_remove, "Quita de la lista los objetos seleccionados"))
        row.addWidget(button("Vaciar lista", self.on_clear))
        row.addStretch(1)
        row.addWidget(button("Copiar para Foundry", self.on_copy_json,
                             "Copia los objetos seleccionados para pegarlos en el módulo de Foundry"))
        row.addWidget(button("Exportar para Foundry…", self.on_export,
                             "Guarda los objetos seleccionados (o todos) en un archivo .json"))

        right = QVBoxLayout()
        right.addWidget(splitter, 1)
        right.addLayout(row)
        right_w = QWidget()
        right_w.setLayout(right)

        layout = QHBoxLayout()
        layout.addWidget(left_w)
        layout.addWidget(right_w, 1)
        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def _fill_types(self) -> None:
        tag = self.cmb_tag.currentData()
        self.cmb_type.blockSignals(True)
        self.cmb_type.clear()
        self.cmb_type.addItem(ANY, None)
        for info in self.engine.types_for_tag(tag):
            self.cmb_type.addItem(info.label, info.id)
        self.cmb_type.blockSignals(False)
        self._fill_objects()

    def _fill_objects(self) -> None:
        type_id = self.cmb_type.currentData()
        self.cmb_object.clear()
        self.cmb_object.addItem(ANY, None)
        if type_id:
            for obj in self.engine.types[type_id].objects:
                self.cmb_object.addItem(obj.name, obj.id)
        self.cmb_object.setEnabled(bool(type_id))

    def on_generate(self) -> None:
        first_new = len(self.items)
        try:
            for _ in range(self.spin_count.value()):
                item = self.engine.generate(
                    self.cmb_rarity.currentData(),
                    tag=self.cmb_tag.currentData(),
                    type_id=self.cmb_type.currentData(),
                    object_id=self.cmb_object.currentData(),
                    cursed=self.cmb_bad.currentData(),
                )
                self.items.append(item)
                self.lst_items.addItem(QListWidgetItem(f"{item['name']}  ·  {item['rarityLabel']}"))
        except GenerationError as e:
            QMessageBox.warning(self, "No se pudo generar", str(e))
        if len(self.items) > first_new:
            self.lst_items.clearSelection()
            self.lst_items.setCurrentRow(first_new)

    def _selected_rows(self) -> List[int]:
        return sorted(i.row() for i in self.lst_items.selectedIndexes())

    def _selected_items(self) -> List[Dict[str, Any]]:
        return [self.items[r] for r in self._selected_rows()]

    def _show_selected(self) -> None:
        sep = "\n\n" + "─" * 40 + "\n\n"
        debug = self.chk_debug.isChecked()
        self.txt_item.setPlainText(sep.join(render_text(i, debug=debug) for i in self._selected_items()))

    def on_copy_text(self) -> None:
        if self.txt_item.toPlainText():
            QApplication.clipboard().setText(self.txt_item.toPlainText())
            self.statusBar().showMessage("Texto copiado.", 3000)

    def on_remove(self) -> None:
        for row in reversed(self._selected_rows()):
            del self.items[row]
            self.lst_items.takeItem(row)

    def on_clear(self) -> None:
        if not self.items:
            return
        answer = QMessageBox.question(self, "Vaciar lista", "¿Quitar todos los objetos generados de la lista?")
        if answer == QMessageBox.StandardButton.Yes:
            self.items.clear()
            self.lst_items.clear()

    def _items_to_export(self) -> List[Dict[str, Any]]:
        selected = self._selected_items()
        if not selected:
            QMessageBox.information(self, "Nada que exportar", "Genera y selecciona al menos un objeto.")
        return selected

    def on_copy_json(self) -> None:
        items = self._items_to_export()
        if items:
            QApplication.clipboard().setText(export_json(items))
            self.statusBar().showMessage(f"{len(items)} objeto(s) copiados. Pégalos en el módulo de Foundry.", 5000)

    def on_export(self) -> None:
        items = self._items_to_export()
        if not items:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar para Foundry", "objetos-rell.json", "JSON (*.json)")
        if not path:
            return
        try:
            export_file(items, Path(path))
        except OSError as e:
            QMessageBox.critical(self, "No se pudo guardar", str(e))
            return
        self.statusBar().showMessage(f"{len(items)} objeto(s) exportados a {path}", 6000)

    # ------------------------------------------------------ pestaña Expansiones
    def _build_expansions_tab(self) -> QWidget:
        self.lst_exp = QListWidget()
        self.txt_errors = QPlainTextEdit()
        self.txt_errors.setReadOnly(True)
        self.lbl_summary = QLabel()

        btn_apply = QPushButton("Guardar selección y recargar")
        btn_apply.clicked.connect(self.on_apply_expansions)
        btn_reload = QPushButton("Recargar tablas")
        btn_reload.setToolTip("Vuelve a leer todos los archivos de texto tras editarlos")
        btn_reload.clicked.connect(self.on_reload)
        btn_folder = QPushButton("Abrir carpeta de expansiones")
        btn_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.engine.root / "expansions")))
        )
        row = QHBoxLayout()
        row.addWidget(btn_apply)
        row.addWidget(btn_reload)
        row.addWidget(btn_folder)
        row.addStretch(1)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Expansiones encontradas (marca las que quieras usar):"))
        layout.addWidget(self.lst_exp, 1)
        layout.addLayout(row)
        layout.addWidget(self.lbl_summary)
        layout.addWidget(QLabel("Problemas encontrados en las tablas:"))
        layout.addWidget(self.txt_errors, 1)
        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def on_apply_expansions(self) -> None:
        enabled = []
        for i in range(self.lst_exp.count()):
            it = self.lst_exp.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                enabled.append(it.data(Qt.ItemDataRole.UserRole))
        try:
            self.engine.save_enabled(enabled)
        except OSError as e:
            QMessageBox.critical(self, "No se pudo guardar", str(e))
            return
        self.on_reload()

    def on_reload(self) -> None:
        self.engine.load()
        self._refresh_from_engine()
        self.statusBar().showMessage("Tablas recargadas.", 3000)

    def _refresh_from_engine(self) -> None:
        eng = self.engine
        self.lst_exp.clear()
        for exp in eng.expansions.values():
            label = f"{exp.name}  (v{exp.version})" + (f"  — ERROR: {exp.error}" if exp.error else "")
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, exp.id)
            if exp.error:
                it.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if exp.enabled else Qt.CheckState.Unchecked)
            self.lst_exp.addItem(it)

        n_objects = sum(len(t.objects) for t in eng.types.values())
        self.lbl_summary.setText(f"Cargados {len(eng.types)} tipos, {n_objects} objetos base y {len(eng.rarities)} rarezas.")
        self.txt_errors.setPlainText("\n".join(eng.errors) if eng.errors else "Ninguno.")
        self.tabs.setTabText(1, f"Expansiones ({len(eng.errors)} avisos)" if eng.errors else "Expansiones")

        previous_rarity: Optional[str] = self.cmb_rarity.currentData()
        self.cmb_rarity.clear()
        for r in eng.rarities.values():
            self.cmb_rarity.addItem(r.name, r.id)
        index = self.cmb_rarity.findData(previous_rarity or "raro")
        self.cmb_rarity.setCurrentIndex(max(index, 0))

        self.cmb_tag.blockSignals(True)
        self.cmb_tag.clear()
        self.cmb_tag.addItem(ANY, None)
        for tag in eng.all_tags():
            self.cmb_tag.addItem(tag.replace("_", " ").capitalize(), tag)
        self.cmb_tag.blockSignals(False)
        self._fill_types()


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow(app_root())
    win.show()
    return app.exec()
