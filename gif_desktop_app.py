#!/usr/bin/env python3
import sys
import os
import time
import math
import random
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple

# Автоматическая настройка XWayland (xcb) на Linux, чтобы при запуске с ярлыка
# гифки могли свободно перемещаться по координатам рабочего стола на KDE / GNOME (Wayland).
if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

import numpy as np
from PIL import Image, ImageSequence, ImageOps, ImageEnhance

from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QSize, QThread, pyqtSignal, QEvent
)
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QFont, QPen, QBrush, QCursor, QAction,
    QIcon, QDragEnterEvent, QDropEvent
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QSlider,
    QFileDialog, QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox,
    QColorDialog, QMenu, QMessageBox, QProgressBar, QGroupBox, QFormLayout,
    QListWidget, QListWidgetItem, QAbstractItemView, QSpinBox, QSystemTrayIcon
)

# Опциональная поддержка нейросетевого удаления фона (rembg)
try:
    from rembg import remove as rembg_remove
    HAS_REMBG = True
except ImportError:
    HAS_REMBG = False


SUPPORTED_EXTENSIONS = (".gif", ".webp", ".png", ".apng", ".jpg", ".jpeg")


def create_app_icon() -> QIcon:
    """Генерирует фирменную иконку приложения (в стиле макета Figma) программно."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QBrush(QColor("#292C30")))
    painter.setPen(QPen(QColor("#5294E2"), 3))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QPen(QColor("#D7D7D9"), 4))
    painter.drawLine(32, 18, 32, 46)
    painter.drawLine(18, 32, 46, 32)
    painter.end()
    return QIcon(pix)


def install_desktop_shortcut(parent_widget: Optional[QWidget] = None):
    """
    Создаёт ярлык запуска приложения на Рабочем столе и в меню приложений:
    - На Linux: создаёт ~/.local/share/applications/gif-desktop-manager.desktop
      и ярлык на Рабочем столе (~/Desktop или ~/Рабочий стол) с правами +x.
    - На Windows 10/11: создаёт ярлык GIF Desktop Manager.lnk на Рабочем столе и в меню Пуск,
      а также генерирует готовый скрипт сборки в один .exe файл (build_windows_exe.bat).
    """
    script_path = Path(__file__).resolve()

    if sys.platform.startswith("linux"):
        icon_dir = Path.home() / ".local" / "share" / "icons"
        icon_dir.mkdir(parents=True, exist_ok=True)
        icon_path = icon_dir / "gif-desktop-manager.png"
        create_app_icon().pixmap(64, 64).save(str(icon_path), "PNG")

        # Делаем сам скрипт исполняемым
        try:
            script_path.chmod(script_path.stat().st_mode | 0o755)
        except OSError:
            pass

        python_bin = sys.executable or "/usr/bin/python3"
        desktop_entry = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=GIF Desktop Manager\n"
            "Comment=Анимированные GIF-виджеты с физикой на рабочем столе\n"
            f'Exec=env QT_QPA_PLATFORM=xcb "{python_bin}" "{script_path}"\n'
            f"Icon={icon_path}\n"
            "Terminal=false\n"
            "Categories=Utility;Graphics;\n"
            "StartupNotify=false\n"
        )

        apps_dir = Path.home() / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        app_menu_file = apps_dir / "gif-desktop-manager.desktop"
        app_menu_file.write_text(desktop_entry, encoding="utf-8")
        app_menu_file.chmod(0o755)

        created_paths = [str(app_menu_file)]
        for candidate in [Path.home() / "Desktop", Path.home() / "Рабочий стол"]:
            if candidate.is_dir():
                desk_file = candidate / "GIF Desktop Manager.desktop"
                desk_file.write_text(desktop_entry, encoding="utf-8")
                desk_file.chmod(0o755)
                created_paths.append(str(desk_file))

        if parent_widget:
            QMessageBox.information(
                parent_widget,
                "Ярлык успешно создан",
                "Ярлык приложения создан и готов к запуску без терминала:\n\n"
                + "\n".join(created_paths)
                + "\n\nТеперь программу можно открывать через меню приложений или двойным кликом по ярлыку на Рабочем столе.",
            )

    elif sys.platform == "win32":
        # На Windows 10/11 создаём ярлык .lnk через встроенный PowerShell WScript.Shell
        pythonw_bin = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw_bin.exists():
            pythonw_bin = Path(sys.executable)

        ps_cmd = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$desk = [Environment]::GetFolderPath('Desktop'); "
            "$lnk = $ws.CreateShortcut((Join-Path $desk 'GIF Desktop Manager.lnk')); "
            f"$lnk.TargetPath = '{pythonw_bin}'; "
            f"$lnk.Arguments = '\"{script_path}\"'; "
            f"$lnk.WorkingDirectory = '{script_path.parent}'; "
            "$lnk.Save()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if parent_widget:
                QMessageBox.information(
                    parent_widget,
                    "Ярлык создан",
                    "Ярлык «GIF Desktop Manager» успешно создан на Рабочем столе Windows!",
                )
        except Exception as e:
            if parent_widget:
                QMessageBox.warning(
                    parent_widget,
                    "Ошибка создания ярлыка",
                    f"Не удалось создать ярлык автоматически:\n{e}",
                )


@dataclass
class FunConfig:
    """
    Конфигурация развлекательных функций и модификаторов физики.
    Все параметры строятся на независимых переключателях и множителях
    с контролем взаимно противоречащих режимов:
    - infinite_dvd (Бесконечное скольжение DVD) и gravity (Гравитация) не могут быть включены одновременно.
    - evade_mouse (Убегать от мыши) и chase_mouse (Догонять мышь) не могут быть включены одновременно.
    - magnet_attract (Притяжение гифок) и magnet_repel (Отталкивание гифок) не могут быть включены одновременно.
    """
    infinite_dvd: bool = False          # Бесконечное скольжение (без трения, постоянный полёт)
    chaos_mode: bool = False            # Режим ХАОС (переключатель: вечное бешеное скольжение и рикошеты)
    gravity: bool = False               # Гравитация (притяжение вниз + прыжки от пола)
    evade_mouse: bool = False           # Убегать от курсора мыши
    chase_mouse: bool = False           # Догонять курсор мыши
    collide_gifs: bool = True           # Сталкиваться и отскакивать друг от друга
    bounce_edges: bool = True           # Упругий отскок от краёв экрана (иначе телепорт сквозь край)
    magnet_attract: bool = False        # Гравитационное притяжение гифок друг к другу
    magnet_repel: bool = False          # Антигравитация: гифки отталкиваются на расстоянии
    pulse_size: bool = False            # Пульсация размера в движении
    rainbow_tint: bool = False          # Перелив оттенков (RGB-подсветка)

    # Множители (поддерживают скраббинг мышью влево/вправо и ползунки):
    glide_speed_mult: float = 1.0       # Множитель скорости скольжения: от 1x до 100x
    bounciness_mult: float = 1.0        # Множитель упругости отскока: от 0.5x до 3.0x
    mouse_force_mult: float = 2.0       # Множитель силы реакции на мышь: от 1x до 50x
    gravity_mult: float = 1.0           # Множитель силы гравитации: от 0.5x до 10x

    def enforce_consistency(self):
        """Гарантирует отсутствие конфликтующих переключателей."""
        if self.infinite_dvd or self.chaos_mode:
            self.gravity = False
        if self.evade_mouse and self.chase_mouse:
            self.chase_mouse = False
        if self.magnet_attract and self.magnet_repel:
            self.magnet_repel = False

    def copy(self) -> "FunConfig":
        c = replace(self)
        c.enforce_consistency()
        return c

    def summary_text(self) -> str:
        active = []
        if self.chaos_mode:
            active.append("ХАОС")
        if self.infinite_dvd:
            active.append("DVD")
        if self.gravity:
            active.append("ГРАВИТ")
        if self.evade_mouse:
            active.append("ОТ МЫШИ")
        if self.chase_mouse:
            active.append("ЗА МЫШЬЮ")
        if self.glide_speed_mult > 1.05:
            active.append(f"x{int(round(self.glide_speed_mult))}")
        if not active:
            return "ОТКРЫТЬ"
        return "+".join(active[:2])


def pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    """Конвертирует PIL Image (RGBA) в QPixmap."""
    rgba_img = pil_img.convert("RGBA")
    data = rgba_img.tobytes("raw", "RGBA")
    qimg = QImage(
        data,
        rgba_img.width,
        rgba_img.height,
        rgba_img.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    return QPixmap.fromImage(qimg.copy())


def extract_gif_frames(path: str) -> Tuple[List[Image.Image], List[int]]:
    """Извлекает все кадры GIF/WebP/PNG и их длительность в мс."""
    frames: List[Image.Image] = []
    durations: List[int] = []
    with Image.open(path) as img:
        for frame in ImageSequence.Iterator(img):
            frames.append(frame.convert("RGBA").copy())
            dur = frame.info.get("duration", 80)
            if not dur or dur < 15:
                dur = 80
            durations.append(int(dur))
    if not frames:
        raise ValueError("Не удалось прочитать кадры из файла.")
    return frames, durations


def remove_bg_chromakey(
    frames: List[Image.Image],
    target_rgb: Tuple[int, int, int] = (255, 255, 255),
    tolerance: int = 38,
    soft_edge: int = 12,
) -> List[Image.Image]:
    """Удаляет однотонный фон (хромакей / белый фон) с мягким сглаживанием краёв."""
    out: List[Image.Image] = []
    tr, tg, tb = target_rgb
    for frame in frames:
        arr = np.array(frame.convert("RGBA"), dtype=np.float32)
        r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
        dist = np.sqrt((r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2)

        if soft_edge > 0:
            alpha_factor = np.clip((dist - tolerance) / float(soft_edge), 0.0, 1.0)
        else:
            alpha_factor = np.where(dist <= tolerance, 0.0, 1.0)

        arr[:, :, 3] = a * alpha_factor
        out.append(Image.fromarray(arr.astype(np.uint8), "RGBA"))
    return out


def apply_gif_edits(
    frames: List[Image.Image],
    durations: List[int],
    start_frame: int = 0,
    end_frame: Optional[int] = None,
    reverse_frames: bool = False,
    rotate_deg: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    auto_crop_alpha: bool = False,
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    color_filter: str = "none",
    border_px: int = 0,
    border_color: Tuple[int, int, int] = (255, 255, 255),
) -> Tuple[List[Image.Image], List[int]]:
    """Применяет визуальные трансформации и эффекты редактора гифки."""
    if not frames:
        return [], []

    total = len(frames)
    s_idx = max(0, min(total - 1, start_frame))
    e_idx = total - 1 if end_frame is None else max(s_idx, min(total - 1, end_frame))

    sliced_frames = [f.copy() for f in frames[s_idx : e_idx + 1]]
    sliced_durs = list(durations[s_idx : e_idx + 1])

    if reverse_frames:
        sliced_frames.reverse()
        sliced_durs.reverse()

    crop_box = None
    if auto_crop_alpha:
        min_x, min_y = 999999, 999999
        max_x, max_y = 0, 0
        found_any = False
        for f in sliced_frames:
            alpha = f.split()[-1]
            bbox = alpha.getbbox()
            if bbox:
                found_any = True
                min_x = min(min_x, bbox[0])
                min_y = min(min_y, bbox[1])
                max_x = max(max_x, bbox[2])
                max_y = max(max_y, bbox[3])
        if found_any and max_x > min_x and max_y > min_y:
            crop_box = (min_x, min_y, max_x, max_y)

    out_frames: List[Image.Image] = []
    for f in sliced_frames:
        img = f.convert("RGBA")

        if crop_box:
            img = img.crop(crop_box)

        if rotate_deg in (90, 180, 270):
            img = img.rotate(-rotate_deg, expand=True)

        if flip_h:
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if flip_v:
            img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        r, g, b, a = img.split()
        rgb = Image.merge("RGB", (r, g, b))

        if abs(brightness - 1.0) > 0.02:
            rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
        if abs(contrast - 1.0) > 0.02:
            rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
        if abs(saturation - 1.0) > 0.02:
            rgb = ImageEnhance.Color(rgb).enhance(saturation)

        if color_filter == "grayscale":
            gray = ImageOps.grayscale(rgb)
            rgb = Image.merge("RGB", (gray, gray, gray))
        elif color_filter == "invert":
            rgb = ImageOps.invert(rgb)
        elif color_filter == "sepia":
            arr = np.array(rgb, dtype=np.float32)
            tr = np.clip(0.393 * arr[:, :, 0] + 0.769 * arr[:, :, 1] + 0.189 * arr[:, :, 2], 0, 255)
            tg = np.clip(0.349 * arr[:, :, 0] + 0.686 * arr[:, :, 1] + 0.168 * arr[:, :, 2], 0, 255)
            tb = np.clip(0.272 * arr[:, :, 0] + 0.534 * arr[:, :, 1] + 0.131 * arr[:, :, 2], 0, 255)
            rgb = Image.fromarray(np.stack([tr, tg, tb], axis=-1).astype(np.uint8), "RGB")
        elif color_filter == "cyberpunk":
            arr = np.array(rgb, dtype=np.float32)
            arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.25 + 15, 0, 255)
            arr[:, :, 1] = np.clip(arr[:, :, 1] * 0.85, 0, 255)
            arr[:, :, 2] = np.clip(arr[:, :, 2] * 1.35 + 25, 0, 255)
            rgb = Image.fromarray(arr.astype(np.uint8), "RGB")

        r, g, b = rgb.split()
        img = Image.merge("RGBA", (r, g, b, a))

        if border_px > 0:
            pad = border_px
            padded = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
            padded.paste(img, (pad, pad))
            arr = np.array(padded)
            alpha_mask = arr[:, :, 3] > 25

            dilated = np.zeros_like(alpha_mask)
            for dy in range(-border_px, border_px + 1):
                for dx in range(-border_px, border_px + 1):
                    if dx * dx + dy * dy <= border_px * border_px:
                        shifted = np.roll(np.roll(alpha_mask, dy, axis=0), dx, axis=1)
                        dilated |= shifted

            outline_only = dilated & (~alpha_mask)
            outline_arr = np.array(padded)
            outline_arr[outline_only, 0] = border_color[0]
            outline_arr[outline_only, 1] = border_color[1]
            outline_arr[outline_only, 2] = border_color[2]
            outline_arr[outline_only, 3] = 255
            img = Image.fromarray(outline_arr, "RGBA")

        out_frames.append(img)

    return out_frames, sliced_durs


class ScrubbableLineEdit(QLineEdit):
    """
    Поле ввода числа с поддержкой «мягкой настройки» (scrubbing):
    - Зажмите ЛКМ на поле и тяните мышь влево/вправо, чтобы плавно уменьшать/увеличивать число.
    - Крутите колёсико мыши над полем для шага ±5 (или ±1 с зажатым Ctrl, ±20 с Shift).
    """
    valueScrubbed = pyqtSignal(int)

    def __init__(
        self,
        text: str = "100",
        parent: Optional[QWidget] = None,
        minimum: int = 1,
        maximum: int = 2500,
        prefix: str = "",
        suffix: str = "",
    ):
        super().__init__(text, parent)
        self.min_val = minimum
        self.max_val = maximum
        self.prefix = prefix
        self.suffix = suffix
        self._pressing = False
        self._scrubbing = False
        self._press_x = 0
        self._start_val = 100
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def current_int(self) -> int:
        raw = self.text().strip()
        if self.prefix and raw.startswith(self.prefix):
            raw = raw[len(self.prefix):]
        if self.suffix and raw.endswith(self.suffix):
            raw = raw[:-len(self.suffix)]
        raw = "".join(ch for ch in raw if ch.isdigit() or ch == "-")
        try:
            return max(self.min_val, min(self.max_val, int(raw)))
        except ValueError:
            return max(self.min_val, min(self.max_val, 1))

    def set_int(self, val: int, emit_signal: bool = True):
        clamped = max(self.min_val, min(self.max_val, int(val)))
        self.setText(f"{self.prefix}{clamped}{self.suffix}")
        if emit_signal:
            self.valueScrubbed.emit(clamped)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressing = True
            self._scrubbing = False
            self._press_x = int(event.globalPosition().x())
            self._start_val = self.current_int()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressing:
            dx = int(event.globalPosition().x()) - self._press_x
            if not self._scrubbing and abs(dx) >= 3:
                self._scrubbing = True
                self.clearFocus()
                self.deselect()

            if self._scrubbing:
                mods = event.modifiers()
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    delta = dx * 3
                elif mods & Qt.KeyboardModifier.ControlModifier:
                    delta = int(round(dx * 0.25))
                else:
                    delta = dx
                self.set_int(self._start_val + delta, emit_signal=True)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressing:
            was_scrubbing = self._scrubbing
            self._pressing = False
            self._scrubbing = False
            if not was_scrubbing:
                self.setFocus()
                self.selectAll()
            else:
                self.editingFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        mods = event.modifiers()
        step = 5 if self.max_val > 200 else 1
        if mods & Qt.KeyboardModifier.ShiftModifier:
            step = 20 if self.max_val > 200 else 5
        elif mods & Qt.KeyboardModifier.ControlModifier:
            step = 1
        direction = 1 if event.angleDelta().y() > 0 else -1
        self.set_int(self.current_int() + direction * step, emit_signal=True)
        self.editingFinished.emit()
        event.accept()


class BgProcessWorker(QThread):
    """Фоновый поток для покадровой обработки фона GIF (Хромакей или AI rembg)."""
    progress = pyqtSignal(int, int)
    finished_frames = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        frames: List[Image.Image],
        mode: str,
        target_rgb: Tuple[int, int, int] = (255, 255, 255),
        tolerance: int = 38,
        soft_edge: int = 12,
    ):
        super().__init__()
        self.frames = frames
        self.mode = mode
        self.target_rgb = target_rgb
        self.tolerance = tolerance
        self.soft_edge = soft_edge

    def run(self):
        try:
            total = len(self.frames)
            if self.mode == "keep":
                self.finished_frames.emit([f.copy() for f in self.frames])
                return

            if self.mode == "chromakey":
                out = []
                for idx, frame in enumerate(self.frames):
                    processed = remove_bg_chromakey(
                        [frame], self.target_rgb, self.tolerance, self.soft_edge
                    )[0]
                    out.append(processed)
                    self.progress.emit(idx + 1, total)
                self.finished_frames.emit(out)
                return

            if self.mode == "ai":
                out = []
                for idx, frame in enumerate(self.frames):
                    if HAS_REMBG:
                        res = rembg_remove(frame)
                        out.append(res.convert("RGBA"))
                    else:
                        arr = np.array(frame.convert("RGBA"))
                        corners = [
                            arr[0, 0, :3],
                            arr[0, -1, :3],
                            arr[-1, 0, :3],
                            arr[-1, -1, :3],
                        ]
                        avg_rgb = tuple(int(x) for x in np.mean(corners, axis=0))
                        processed = remove_bg_chromakey(
                            [frame], avg_rgb, max(self.tolerance, 42), self.soft_edge
                        )[0]
                        out.append(processed)
                    self.progress.emit(idx + 1, total)
                self.finished_frames.emit(out)
        except Exception as e:
            self.error.emit(str(e))


class BackgroundChoiceDialog(QDialog):
    """Диалог выбора и настройки ФОНА (вызывается при загрузке GIF и по кнопке «ФОН ГИФКИ»)."""
    def __init__(
        self,
        parent: QWidget,
        raw_frames: List[Image.Image],
        initial_mode: str = "keep",
        initial_color: Tuple[int, int, int] = (255, 255, 255),
        initial_tolerance: int = 38,
    ):
        super().__init__(parent)
        self.setWindowTitle("Обработка фона GIF")
        self.setFixedSize(460, 420)
        self.raw_frames = raw_frames
        self.result_frames: List[Image.Image] = [f.copy() for f in raw_frames]
        self.selected_mode = initial_mode
        self.target_color = initial_color
        self.tolerance = initial_tolerance
        self.worker: Optional[BgProcessWorker] = None

        first_arr = np.array(raw_frames[0].convert("RGBA"))
        if first_arr[0, 0, 3] > 200:
            self.target_color = (
                int(first_arr[0, 0, 0]),
                int(first_arr[0, 0, 1]),
                int(first_arr[0, 0, 2]),
            )

        self.setStyleSheet("""
            QDialog {
                background-color: #292C30;
                color: #D7D7D9;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QLabel { color: #D7D7D9; }
            QComboBox, QPushButton, QSlider {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                padding: 5px 8px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #8E8E8E;
            }
            QProgressBar {
                background-color: #1F2124;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                text-align: center;
                color: #D7D7D9;
            }
            QProgressBar::chunk { background-color: #5294E2; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Выберите способ обработки фона гифки:")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(180, 180)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #1E1E1E; border: 1px solid #5E5E5E; border-radius: 4px;"
        )
        preview_row = QHBoxLayout()
        preview_row.addStretch()
        preview_row.addWidget(self.preview_label)
        preview_row.addStretch()
        layout.addLayout(preview_row)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Оставить как есть (оригинальный фон)", "keep")
        self.mode_combo.addItem("Убрать фон: Хромакей / по цвету (белый и др.)", "chromakey")
        ai_label = (
            "Убрать фон: ИИ / Мощности ПК (rembg)"
            if HAS_REMBG
            else "Убрать фон: Авто-вырезание по краям (установите rembg для нейросети)"
        )
        self.mode_combo.addItem(ai_label, "ai")

        idx = self.mode_combo.findData(initial_mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(self.on_params_changed)
        layout.addWidget(self.mode_combo)

        self.chroma_box = QWidget()
        chroma_layout = QFormLayout(self.chroma_box)
        chroma_layout.setContentsMargins(0, 0, 0, 0)

        color_row = QHBoxLayout()
        self.color_btn = QPushButton("Выбрать цвет фона")
        self.color_btn.clicked.connect(self.pick_color)
        self.white_btn = QPushButton("Белый (#FFFFFF)")
        self.white_btn.clicked.connect(self.set_white_color)
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.white_btn)
        chroma_layout.addRow("Цвет:", color_row)

        self.tol_slider = QSlider(Qt.Orientation.Horizontal)
        self.tol_slider.setRange(5, 140)
        self.tol_slider.setValue(self.tolerance)
        self.tol_slider.valueChanged.connect(self.on_params_changed)
        self.tol_label = QLabel(f"{self.tolerance}")
        tol_row = QHBoxLayout()
        tol_row.addWidget(self.tol_slider)
        tol_row.addWidget(self.tol_label)
        chroma_layout.addRow("Допуск:", tol_row)

        layout.addWidget(self.chroma_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("ОТМЕНА")
        self.cancel_btn.clicked.connect(self.reject)
        self.apply_btn = QPushButton("ПРИМЕНИТЬ")
        self.apply_btn.clicked.connect(self.start_processing)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.apply_btn)
        layout.addLayout(btn_row)

        self.update_color_btn_style()
        self.on_params_changed()

    def update_color_btn_style(self):
        r, g, b = self.target_color
        self.color_btn.setText(f"Цвет: #{r:02X}{g:02X}{b:02X}")

    def pick_color(self):
        r, g, b = self.target_color
        col = QColorDialog.getColor(QColor(r, g, b), self, "Выберите цвет фона для удаления")
        if col.isValid():
            self.target_color = (col.red(), col.green(), col.blue())
            self.update_color_btn_style()
            self.on_params_changed()

    def set_white_color(self):
        self.target_color = (255, 255, 255)
        self.update_color_btn_style()
        self.on_params_changed()

    def on_params_changed(self):
        mode = self.mode_combo.currentData()
        self.selected_mode = mode
        self.tolerance = self.tol_slider.value()
        self.tol_label.setText(str(self.tolerance))
        self.chroma_box.setVisible(mode == "chromakey")
        self.update_preview()

    def update_preview(self):
        sample = self.raw_frames[0]
        mode = self.mode_combo.currentData()
        if mode == "chromakey":
            sample = remove_bg_chromakey([sample], self.target_color, self.tolerance)[0]
        elif mode == "ai" and not HAS_REMBG:
            arr = np.array(sample.convert("RGBA"))
            corners = [arr[0, 0, :3], arr[0, -1, :3], arr[-1, 0, :3], arr[-1, -1, :3]]
            avg_rgb = tuple(int(x) for x in np.mean(corners, axis=0))
            sample = remove_bg_chromakey([sample], avg_rgb, max(self.tolerance, 42))[0]

        checker = self.make_checkerboard(172, 172)
        fg = pil_to_qpixmap(sample).scaled(
            168, 168,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(checker)
        x = (172 - fg.width()) // 2
        y = (172 - fg.height()) // 2
        painter.drawPixmap(x, y, fg)
        painter.end()
        self.preview_label.setPixmap(checker)

    @staticmethod
    def make_checkerboard(w: int, h: int, cell: int = 12) -> QPixmap:
        pix = QPixmap(w, h)
        painter = QPainter(pix)
        c1 = QColor(45, 45, 45)
        c2 = QColor(68, 68, 68)
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                painter.fillRect(x, y, cell, cell, c1 if ((x // cell + y // cell) % 2 == 0) else c2)
        painter.end()
        return pix

    def start_processing(self):
        mode = self.mode_combo.currentData()
        self.apply_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.raw_frames))
        self.progress_bar.setValue(0)

        self.worker = BgProcessWorker(
            self.raw_frames,
            mode=mode,
            target_rgb=self.target_color,
            tolerance=self.tolerance,
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_frames.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)

    def on_finished(self, frames: List[Image.Image]):
        self.result_frames = frames
        self.accept()

    def on_error(self, msg: str):
        self.apply_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "Ошибка обработки", f"Не удалось обработать фон:\n{msg}")


class GifEditorDialog(QDialog):
    """
    Полноценная студия редактирования самой гифки по кнопке «РЕДАКТИРОВАТЬ»
    (отличается от кнопки «ФОН ГИФКИ»).
    """
    def __init__(
        self,
        parent: QWidget,
        source_frames: List[Image.Image],
        source_durations: List[int],
    ):
        super().__init__(parent)
        self.setWindowTitle("Редактор GIF (Кадры, Поворот, Эффекты, Стикер-обводка)")
        self.setFixedSize(540, 560)
        self.source_frames = source_frames
        self.source_durations = source_durations
        self.edited_frames: List[Image.Image] = [f.copy() for f in source_frames]
        self.edited_durations: List[int] = list(source_durations)
        self.border_color: Tuple[int, int, int] = (255, 255, 255)

        self.setStyleSheet("""
            QDialog {
                background-color: #292C30;
                color: #D7D7D9;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QLabel, QCheckBox { color: #D7D7D9; }
            QComboBox, QPushButton, QSpinBox, QSlider {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                padding: 4px 6px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #8E8E8E;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(170, 170)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #1E1E1E; border: 1px solid #5E5E5E; border-radius: 4px;"
        )
        prev_row = QHBoxLayout()
        prev_row.addStretch()
        prev_row.addWidget(self.preview_label)
        prev_row.addStretch()
        layout.addLayout(prev_row)

        form = QFormLayout()
        form.setSpacing(7)

        total_f = len(source_frames)
        frame_row = QHBoxLayout()
        self.spin_start = QSpinBox()
        self.spin_start.setRange(1, total_f)
        self.spin_start.setValue(1)
        self.spin_end = QSpinBox()
        self.spin_end.setRange(1, total_f)
        self.spin_end.setValue(total_f)
        self.chk_reverse = QCheckBox("Задом наперёд (Реверс)")
        frame_row.addWidget(QLabel("С:"))
        frame_row.addWidget(self.spin_start)
        frame_row.addWidget(QLabel("По:"))
        frame_row.addWidget(self.spin_end)
        frame_row.addWidget(self.chk_reverse)
        form.addRow(f"Кадры (всего {total_f}):", frame_row)

        geo_row = QHBoxLayout()
        self.combo_rotate = QComboBox()
        self.combo_rotate.addItem("0 градусов", 0)
        self.combo_rotate.addItem("90 градусов вправо", 90)
        self.combo_rotate.addItem("180 градусов", 180)
        self.combo_rotate.addItem("270 градусов влево", 270)
        self.chk_flip_h = QCheckBox("Отразить по гориз.")
        self.chk_flip_v = QCheckBox("Отразить по верт.")
        geo_row.addWidget(self.combo_rotate)
        geo_row.addWidget(self.chk_flip_h)
        geo_row.addWidget(self.chk_flip_v)
        form.addRow("Поворот / Отражение:", geo_row)

        self.chk_autocrop = QCheckBox("Обрезать пустые прозрачные поля вокруг гифки")
        form.addRow("Кадрирование:", self.chk_autocrop)

        self.sld_bright = QSlider(Qt.Orientation.Horizontal)
        self.sld_bright.setRange(40, 180)
        self.sld_bright.setValue(100)
        self.lbl_bright = QLabel("100%")
        b_row = QHBoxLayout()
        b_row.addWidget(self.sld_bright)
        b_row.addWidget(self.lbl_bright)
        form.addRow("Яркость:", b_row)

        self.sld_contrast = QSlider(Qt.Orientation.Horizontal)
        self.sld_contrast.setRange(40, 180)
        self.sld_contrast.setValue(100)
        self.lbl_contrast = QLabel("100%")
        c_row = QHBoxLayout()
        c_row.addWidget(self.sld_contrast)
        c_row.addWidget(self.lbl_contrast)
        form.addRow("Контраст:", c_row)

        self.sld_sat = QSlider(Qt.Orientation.Horizontal)
        self.sld_sat.setRange(0, 220)
        self.sld_sat.setValue(100)
        self.lbl_sat = QLabel("100%")
        s_row = QHBoxLayout()
        s_row.addWidget(self.sld_sat)
        s_row.addWidget(self.lbl_sat)
        form.addRow("Насыщенность:", s_row)

        self.combo_filter = QComboBox()
        self.combo_filter.addItem("Без фильтра", "none")
        self.combo_filter.addItem("Чёрно-белый (Нуар)", "grayscale")
        self.combo_filter.addItem("Негатив (Инверсия)", "invert")
        self.combo_filter.addItem("Винтаж (Сепия)", "sepia")
        self.combo_filter.addItem("Неон / Киберпанк", "cyberpunk")
        form.addRow("Фильтр:", self.combo_filter)

        border_row = QHBoxLayout()
        self.spin_border = QSpinBox()
        self.spin_border.setRange(0, 10)
        self.spin_border.setValue(0)
        self.spin_border.setSuffix(" px")
        self.btn_border_col = QPushButton("Цвет обводки (#FFFFFF)")
        self.btn_border_col.clicked.connect(self.pick_border_color)
        border_row.addWidget(self.spin_border)
        border_row.addWidget(self.btn_border_col)
        form.addRow("Стикер-контур:", border_row)

        layout.addLayout(form)
        layout.addStretch()

        for w_sig in (
            self.spin_start.valueChanged,
            self.spin_end.valueChanged,
            self.chk_reverse.toggled,
            self.combo_rotate.currentIndexChanged,
            self.chk_flip_h.toggled,
            self.chk_flip_v.toggled,
            self.chk_autocrop.toggled,
            self.sld_bright.valueChanged,
            self.sld_contrast.valueChanged,
            self.sld_sat.valueChanged,
            self.combo_filter.currentIndexChanged,
            self.spin_border.valueChanged,
        ):
            w_sig.connect(self.update_live_preview)

        btn_row = QHBoxLayout()
        btn_reset = QPushButton("Сбросить")
        btn_reset.clicked.connect(self.reset_defaults)
        btn_cancel = QPushButton("ОТМЕНА")
        btn_cancel.clicked.connect(self.reject)
        btn_apply = QPushButton("ПРИМЕНИТЬ К ГИФКЕ")
        btn_apply.clicked.connect(self.apply_all_frames)
        btn_row.addWidget(btn_reset)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_apply)
        layout.addLayout(btn_row)

        self.update_live_preview()

    def pick_border_color(self):
        r, g, b = self.border_color
        col = QColorDialog.getColor(QColor(r, g, b), self, "Выберите цвет контура")
        if col.isValid():
            self.border_color = (col.red(), col.green(), col.blue())
            self.btn_border_col.setText(
                f"Цвет обводки (#{col.red():02X}{col.green():02X}{col.blue():02X})"
            )
            self.update_live_preview()

    def reset_defaults(self):
        self.spin_start.setValue(1)
        self.spin_end.setValue(len(self.source_frames))
        self.chk_reverse.setChecked(False)
        self.combo_rotate.setCurrentIndex(0)
        self.chk_flip_h.setChecked(False)
        self.chk_flip_v.setChecked(False)
        self.chk_autocrop.setChecked(False)
        self.sld_bright.setValue(100)
        self.sld_contrast.setValue(100)
        self.sld_sat.setValue(100)
        self.combo_filter.setCurrentIndex(0)
        self.spin_border.setValue(0)
        self.update_live_preview()

    def update_live_preview(self):
        self.lbl_bright.setText(f"{self.sld_bright.value()}%")
        self.lbl_contrast.setText(f"{self.sld_contrast.value()}%")
        self.lbl_sat.setText(f"{self.sld_sat.value()}%")

        idx = max(0, min(len(self.source_frames) - 1, self.spin_start.value() - 1))
        sample_frames, _ = apply_gif_edits(
            [self.source_frames[idx]],
            [80],
            start_frame=0,
            end_frame=0,
            reverse_frames=False,
            rotate_deg=self.combo_rotate.currentData(),
            flip_h=self.chk_flip_h.isChecked(),
            flip_v=self.chk_flip_v.isChecked(),
            auto_crop_alpha=self.chk_autocrop.isChecked(),
            brightness=self.sld_bright.value() / 100.0,
            contrast=self.sld_contrast.value() / 100.0,
            saturation=self.sld_sat.value() / 100.0,
            color_filter=self.combo_filter.currentData(),
            border_px=self.spin_border.value(),
            border_color=self.border_color,
        )
        checker = BackgroundChoiceDialog.make_checkerboard(164, 164)
        if sample_frames:
            fg = pil_to_qpixmap(sample_frames[0]).scaled(
                158, 158,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter = QPainter(checker)
            x = (164 - fg.width()) // 2
            y = (164 - fg.height()) // 2
            painter.drawPixmap(x, y, fg)
            painter.end()
        self.preview_label.setPixmap(checker)

    def apply_all_frames(self):
        s_idx = self.spin_start.value() - 1
        e_idx = self.spin_end.value() - 1
        if e_idx < s_idx:
            s_idx, e_idx = e_idx, s_idx

        self.edited_frames, self.edited_durations = apply_gif_edits(
            self.source_frames,
            self.source_durations,
            start_frame=s_idx,
            end_frame=e_idx,
            reverse_frames=self.chk_reverse.isChecked(),
            rotate_deg=self.combo_rotate.currentData(),
            flip_h=self.chk_flip_h.isChecked(),
            flip_v=self.chk_flip_v.isChecked(),
            auto_crop_alpha=self.chk_autocrop.isChecked(),
            brightness=self.sld_bright.value() / 100.0,
            contrast=self.sld_contrast.value() / 100.0,
            saturation=self.sld_sat.value() / 100.0,
            color_filter=self.combo_filter.currentData(),
            border_px=self.spin_border.value(),
            border_color=self.border_color,
        )
        self.accept()


class FunFeaturesDialog(QDialog):
    """
    Отдельное окно «РАЗВЛЕЧЕНИЯ И ФИЗИКА», где все фан-режимы строятся
    на независимых переключателях и множителях (от x1 до x100) с автоматической
    блокировкой противоречащих друг другу функций.
    """
    def __init__(self, main_win: "MainDesignerWindow"):
        super().__init__(main_win)
        self.main_win = main_win
        self.cfg: FunConfig = main_win.fun_cfg.copy()
        self.setWindowTitle("Развлекательные функции и физика")
        self.setFixedSize(520, 520)

        self.setStyleSheet("""
            QDialog {
                background-color: #292C30;
                color: #D7D7D9;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QGroupBox {
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                color: #D7D7D9;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLabel, QCheckBox {
                color: #D7D7D9;
                font-weight: normal;
            }
            QCheckBox:disabled {
                color: #6E6E6E;
            }
            QPushButton, QSlider, QLineEdit {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #8E8E8E;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        grp_move = QGroupBox("Переключатели режимов движения и физики")
        v_move = QVBoxLayout(grp_move)

        self.chk_dvd = QCheckBox("Бесконечное скольжение (DVD-режим без трения и остановки)")
        self.chk_chaos = QCheckBox("Режим ХАОС (переключатель: вечное скоростное скольжение всех гифок)")
        self.chk_gravity = QCheckBox("Гравитация и прыжки от нижней границы экрана (несовместимо с DVD/ХАОС)")
        self.chk_evade = QCheckBox("Убегать от курсора мыши (гифка уворачивается от мыши)")
        self.chk_chase = QCheckBox("Догонять курсор мыши (гифка преследует мышь)")
        self.chk_collide = QCheckBox("Сталкиваться и упруго отскакивать друг от друга (2D коллизии гифок)")
        self.chk_bounce_wall = QCheckBox("Отскакивать от краёв экрана (если выкл — пролетает сквозь край напротив)")
        self.chk_attract = QCheckBox("Взаимное притяжение гифок друг к другу (гравитация между гифками)")
        self.chk_repel = QCheckBox("Взаимное отталкивание гифок на расстоянии (антигравитация)")
        self.chk_pulse = QCheckBox("Пульсация размера в такт скорости движения")
        self.chk_rainbow = QCheckBox("RGB перелив оттенков гифки")

        for chk in (
            self.chk_dvd,
            self.chk_chaos,
            self.chk_gravity,
            self.chk_evade,
            self.chk_chase,
            self.chk_collide,
            self.chk_bounce_wall,
            self.chk_attract,
            self.chk_repel,
            self.chk_pulse,
            self.chk_rainbow,
        ):
            v_move.addWidget(chk)

        layout.addWidget(grp_move)

        grp_mult = QGroupBox("Множители силы и скорости (можно тянуть ползунок или число мышью)")
        form_mult = QFormLayout(grp_mult)

        self.sld_glide_mult = QSlider(Qt.Orientation.Horizontal)
        self.sld_glide_mult.setRange(1, 100)
        self.inp_glide_mult = ScrubbableLineEdit("x1", self, minimum=1, maximum=100, prefix="x")
        self.inp_glide_mult.setFixedWidth(54)
        self.inp_glide_mult.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_gm = QHBoxLayout()
        r_gm.addWidget(self.sld_glide_mult)
        r_gm.addWidget(self.inp_glide_mult)
        form_mult.addRow("Множитель скорости скольжения (x1..x100):", r_gm)

        self.sld_mouse_mult = QSlider(Qt.Orientation.Horizontal)
        self.sld_mouse_mult.setRange(1, 50)
        self.inp_mouse_mult = ScrubbableLineEdit("x2", self, minimum=1, maximum=50, prefix="x")
        self.inp_mouse_mult.setFixedWidth(54)
        self.inp_mouse_mult.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_mm = QHBoxLayout()
        r_mm.addWidget(self.sld_mouse_mult)
        r_mm.addWidget(self.inp_mouse_mult)
        form_mult.addRow("Множитель силы от мыши / к мыши (x1..x50):", r_mm)

        self.sld_bounce_mult = QSlider(Qt.Orientation.Horizontal)
        self.sld_bounce_mult.setRange(50, 250)
        self.inp_bounce_mult = ScrubbableLineEdit("100%", self, minimum=50, maximum=250, suffix="%")
        self.inp_bounce_mult.setFixedWidth(54)
        self.inp_bounce_mult.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_bm = QHBoxLayout()
        r_bm.addWidget(self.sld_bounce_mult)
        r_bm.addWidget(self.inp_bounce_mult)
        form_mult.addRow("Множитель упругости ударов (50%..250%):", r_bm)

        self.sld_grav_mult = QSlider(Qt.Orientation.Horizontal)
        self.sld_grav_mult.setRange(1, 10)
        self.inp_grav_mult = ScrubbableLineEdit("x1", self, minimum=1, maximum=10, prefix="x")
        self.inp_grav_mult.setFixedWidth(54)
        self.inp_grav_mult.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_grm = QHBoxLayout()
        r_grm.addWidget(self.sld_grav_mult)
        r_grm.addWidget(self.inp_grav_mult)
        form_mult.addRow("Множитель силы гравитации (x1..x10):", r_grm)

        layout.addWidget(grp_mult)

        self.chk_apply_existing = QCheckBox("Сразу применить эти настройки ко всем гифкам, которые уже на экране")
        self.chk_apply_existing.setChecked(True)
        layout.addWidget(self.chk_apply_existing)

        btn_row = QHBoxLayout()
        btn_reset = QPushButton("Сбросить всё по умолчанию")
        btn_reset.clicked.connect(self.reset_defaults)
        btn_cancel = QPushButton("ОТМЕНА")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("ПРИМЕНИТЬ")
        btn_ok.clicked.connect(self.save_and_accept)
        btn_row.addWidget(btn_reset)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        self._load_from_cfg()
        self._connect_signals()
        self._update_conflict_states()

    def _load_from_cfg(self):
        self.chk_dvd.setChecked(self.cfg.infinite_dvd)
        self.chk_chaos.setChecked(self.cfg.chaos_mode)
        self.chk_gravity.setChecked(self.cfg.gravity)
        self.chk_evade.setChecked(self.cfg.evade_mouse)
        self.chk_chase.setChecked(self.cfg.chase_mouse)
        self.chk_collide.setChecked(self.cfg.collide_gifs)
        self.chk_bounce_wall.setChecked(self.cfg.bounce_edges)
        self.chk_attract.setChecked(self.cfg.magnet_attract)
        self.chk_repel.setChecked(self.cfg.magnet_repel)
        self.chk_pulse.setChecked(self.cfg.pulse_size)
        self.chk_rainbow.setChecked(self.cfg.rainbow_tint)

        gm = max(1, min(100, int(round(self.cfg.glide_speed_mult))))
        self.sld_glide_mult.setValue(gm)
        self.inp_glide_mult.set_int(gm, emit_signal=False)

        mm = max(1, min(50, int(round(self.cfg.mouse_force_mult))))
        self.sld_mouse_mult.setValue(mm)
        self.inp_mouse_mult.set_int(mm, emit_signal=False)

        bm = max(50, min(250, int(round(self.cfg.bounciness_mult * 100))))
        self.sld_bounce_mult.setValue(bm)
        self.inp_bounce_mult.set_int(bm, emit_signal=False)

        grm = max(1, min(10, int(round(self.cfg.gravity_mult))))
        self.sld_grav_mult.setValue(grm)
        self.inp_grav_mult.set_int(grm, emit_signal=False)

    def _connect_signals(self):
        self.chk_dvd.toggled.connect(self._on_dvd_or_chaos_toggled)
        self.chk_chaos.toggled.connect(self._on_dvd_or_chaos_toggled)
        self.chk_gravity.toggled.connect(self._on_gravity_toggled)

        self.chk_evade.toggled.connect(self._on_evade_toggled)
        self.chk_chase.toggled.connect(self._on_chase_toggled)

        self.chk_attract.toggled.connect(self._on_attract_toggled)
        self.chk_repel.toggled.connect(self._on_repel_toggled)

        self.sld_glide_mult.valueChanged.connect(
            lambda v: self.inp_glide_mult.set_int(v, emit_signal=False)
        )
        self.inp_glide_mult.valueScrubbed.connect(self.sld_glide_mult.setValue)
        self.inp_glide_mult.editingFinished.connect(
            lambda: self.sld_glide_mult.setValue(self.inp_glide_mult.current_int())
        )

        self.sld_mouse_mult.valueChanged.connect(
            lambda v: self.inp_mouse_mult.set_int(v, emit_signal=False)
        )
        self.inp_mouse_mult.valueScrubbed.connect(self.sld_mouse_mult.setValue)
        self.inp_mouse_mult.editingFinished.connect(
            lambda: self.sld_mouse_mult.setValue(self.inp_mouse_mult.current_int())
        )

        self.sld_bounce_mult.valueChanged.connect(
            lambda v: self.inp_bounce_mult.set_int(v, emit_signal=False)
        )
        self.inp_bounce_mult.valueScrubbed.connect(self.sld_bounce_mult.setValue)
        self.inp_bounce_mult.editingFinished.connect(
            lambda: self.sld_bounce_mult.setValue(self.inp_bounce_mult.current_int())
        )

        self.sld_grav_mult.valueChanged.connect(
            lambda v: self.inp_grav_mult.set_int(v, emit_signal=False)
        )
        self.inp_grav_mult.valueScrubbed.connect(self.sld_grav_mult.setValue)
        self.inp_grav_mult.editingFinished.connect(
            lambda: self.sld_grav_mult.setValue(self.inp_grav_mult.current_int())
        )

    def _on_dvd_or_chaos_toggled(self, checked: bool):
        if checked and self.chk_gravity.isChecked():
            self.chk_gravity.setChecked(False)
        self._update_conflict_states()

    def _on_gravity_toggled(self, checked: bool):
        if checked:
            if self.chk_dvd.isChecked():
                self.chk_dvd.setChecked(False)
            if self.chk_chaos.isChecked():
                self.chk_chaos.setChecked(False)
        self._update_conflict_states()

    def _on_evade_toggled(self, checked: bool):
        if checked and self.chk_chase.isChecked():
            self.chk_chase.setChecked(False)
        self._update_conflict_states()

    def _on_chase_toggled(self, checked: bool):
        if checked and self.chk_evade.isChecked():
            self.chk_evade.setChecked(False)
        self._update_conflict_states()

    def _on_attract_toggled(self, checked: bool):
        if checked and self.chk_repel.isChecked():
            self.chk_repel.setChecked(False)
        self._update_conflict_states()

    def _on_repel_toggled(self, checked: bool):
        if checked and self.chk_attract.isChecked():
            self.chk_attract.setChecked(False)
        self._update_conflict_states()

    def _update_conflict_states(self):
        inf_active = self.chk_dvd.isChecked() or self.chk_chaos.isChecked()
        grav_active = self.chk_gravity.isChecked()

        self.chk_gravity.setEnabled(not inf_active)
        self.sld_grav_mult.setEnabled(not inf_active)
        self.inp_grav_mult.setEnabled(not inf_active)

        self.chk_dvd.setEnabled(not grav_active)
        self.chk_chaos.setEnabled(not grav_active)

    def reset_defaults(self):
        self.cfg = FunConfig()
        self._load_from_cfg()
        self._update_conflict_states()

    def save_and_accept(self):
        self.cfg.infinite_dvd = self.chk_dvd.isChecked()
        self.cfg.chaos_mode = self.chk_chaos.isChecked()
        self.cfg.gravity = self.chk_gravity.isChecked()
        self.cfg.evade_mouse = self.chk_evade.isChecked()
        self.cfg.chase_mouse = self.chk_chase.isChecked()
        self.cfg.collide_gifs = self.chk_collide.isChecked()
        self.cfg.bounce_edges = self.chk_bounce_wall.isChecked()
        self.cfg.magnet_attract = self.chk_attract.isChecked()
        self.cfg.magnet_repel = self.chk_repel.isChecked()
        self.cfg.pulse_size = self.chk_pulse.isChecked()
        self.cfg.rainbow_tint = self.chk_rainbow.isChecked()

        self.cfg.glide_speed_mult = float(self.inp_glide_mult.current_int())
        self.cfg.mouse_force_mult = float(self.inp_mouse_mult.current_int())
        self.cfg.bounciness_mult = float(self.inp_bounce_mult.current_int()) / 100.0
        self.cfg.gravity_mult = float(self.inp_grav_mult.current_int())
        self.cfg.enforce_consistency()

        self.main_win.apply_fun_config(self.cfg, apply_to_existing=self.chk_apply_existing.isChecked())
        self.accept()


class DesktopGifWidget(QWidget):
    """
    Независимое окно-виджет GIF на рабочем столе (совместимо с Linux и Windows 10/11).
    """
    closed_widget = pyqtSignal(object)
    changed_widget = pyqtSignal(object)

    MODES = [
        "ЦИКЛИЧНЫЙ",
        "1 РАЗ (ПАУЗА)",
        "БУМЕРАНГ",
        "ПРИ НАВЕДЕНИИ",
        "ПАУЗА",
    ]

    _id_counter = 1

    def __init__(
        self,
        frames: List[Image.Image],
        durations: List[int],
        title_name: str = "GIF",
        width: int = 100,
        height: int = 100,
        glide_level: int = 10,
        mode: str = "ЦИКЛИЧНЫЙ",
        fun_cfg: Optional[FunConfig] = None,
        always_on_top: bool = True,
        flip_x: bool = False,
        opacity: float = 1.0,
        speed_mult: float = 1.0,
    ):
        super().__init__(None)
        self.widget_id = DesktopGifWidget._id_counter
        DesktopGifWidget._id_counter += 1

        self.title_name = title_name
        self.raw_pil_frames = frames
        self.durations = durations
        self.base_w = max(20, width)
        self.base_h = max(20, height)
        self.target_w = self.base_w
        self.target_h = self.base_h
        self.glide_level = max(0, min(20, glide_level))
        self.mode = mode if mode in self.MODES else "ЦИКЛИЧНЫЙ"
        self.fun_cfg: FunConfig = (fun_cfg.copy() if fun_cfg else FunConfig())
        self.always_on_top = always_on_top
        self.flip_x = flip_x
        self.widget_opacity = max(0.15, min(1.0, opacity))
        self.speed_mult = max(0.2, min(3.0, speed_mult))

        self.current_idx = 0
        self.direction = 1
        self.is_hovered = False
        self.single_cycle_done = False
        self.hue_shift = random.randint(0, 359)
        self.pulse_phase = 0.0

        self.dragging = False
        self.drag_offset = QPoint(0, 0)
        self.pos_f = QPointF(250.0, 250.0)
        self.vx = 0.0
        self.vy = 0.0
        self.pointer_history: List[Tuple[float, int, int]] = []

        self.scaled_pixmaps: List[QPixmap] = []
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setMouseTracking(True)

        self.rebuild_pixmaps()
        self.resize(self.target_w, self.target_h)

        screen = QApplication.primaryScreen().availableGeometry()
        offset_shift = ((self.widget_id - 1) % 7) * 32
        start_x = screen.center().x() - self.target_w // 2 + offset_shift
        start_y = screen.center().y() - self.target_h // 2 + offset_shift
        self.move(start_x, start_y)
        self.pos_f = QPointF(float(start_x), float(start_y))

        if self.fun_cfg.infinite_dvd or self.fun_cfg.chaos_mode:
            self.ensure_infinite_velocity()

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.next_frame)
        self.schedule_next_frame()

    def target_cruise_speed(self) -> float:
        lvl = max(1, self.glide_level)
        base = 4.0 + (lvl / 20.0) * 18.0
        mult = self.fun_cfg.glide_speed_mult
        if self.fun_cfg.chaos_mode:
            mult = max(mult, 2.5)
        effective_mult = 1.0 + (mult - 1.0) * 0.45
        return min(145.0, base * effective_mult)

    def ensure_infinite_velocity(self):
        want_spd = self.target_cruise_speed()
        cur_spd = math.hypot(self.vx, self.vy)
        if cur_spd < 0.8:
            angle = random.uniform(0.25, 1.3) * random.choice([-1.0, 1.0])
            self.vx = math.cos(angle) * want_spd * random.choice([-1.0, 1.0])
            self.vy = math.sin(angle) * want_spd
        else:
            scale = want_spd / cur_spd
            self.vx = self.vx * (0.85 + 0.15 * scale)
            self.vy = self.vy * (0.85 + 0.15 * scale)

    @property
    def mass(self) -> float:
        return float(max(400, self.target_w * self.target_h))

    def display_label(self) -> str:
        return f"#{self.widget_id} {self.title_name} ({self.base_w}x{self.base_h})"

    def thumbnail_icon(self) -> QIcon:
        if self.scaled_pixmaps:
            pix = self.scaled_pixmaps[0].scaled(
                32, 32,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            return QIcon(pix)
        return QIcon()

    def _apply_window_flags(self):
        """
        Кроссплатформенные флаги окна (Linux + Windows 10/11):
        - На Linux используем ToolTip, чтобы KWin/Mutter не сворачивал гифки вместе с главным окном.
        - На Windows 10/11 у независимых (parent=None) окон используем Tool, чтобы гифки
          принимали клики и перетаскивание мышью, не создавали иконок в панели задач
          и не сворачивались при сворачивании главного окна.
        """
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if sys.platform == "win32":
            flags |= Qt.WindowType.Tool
        else:
            flags |= Qt.WindowType.ToolTip

        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags |= Qt.WindowType.WindowStaysOnBottomHint
        self.setWindowFlags(flags)

    def set_custom_size(self, w: int, h: int):
        self.base_w = max(20, min(2500, int(w)))
        self.base_h = max(20, min(2500, int(h)))
        self.target_w = self.base_w
        self.target_h = self.base_h
        self.resize(self.target_w, self.target_h)
        self.rebuild_pixmaps()
        self.changed_widget.emit(self)

    def rebuild_pixmaps(self):
        self.scaled_pixmaps.clear()
        for pil_f in self.raw_pil_frames:
            work_img = pil_f.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if self.flip_x else pil_f
            resized = work_img.resize((self.target_w, self.target_h), Image.Resampling.LANCZOS)
            self.scaled_pixmaps.append(pil_to_qpixmap(resized))
        self.update()

    def schedule_next_frame(self):
        if not self.durations:
            return
        dur = int(self.durations[self.current_idx] / self.speed_mult)
        self.anim_timer.start(max(10, dur))

    def next_frame(self):
        total = len(self.scaled_pixmaps)
        if self.fun_cfg.rainbow_tint:
            self.hue_shift = (self.hue_shift + 14) % 360

        if total <= 1:
            if self.fun_cfg.rainbow_tint:
                self.update()
            self.schedule_next_frame()
            return

        if self.mode == "ПАУЗА":
            return

        if self.mode == "ПРИ НАВЕДЕНИИ" and not self.is_hovered:
            return

        if self.mode == "1 РАЗ (ПАУЗА)":
            if self.single_cycle_done:
                return
            if self.current_idx + 1 < total:
                self.current_idx += 1
            else:
                self.single_cycle_done = True
        elif self.mode == "БУМЕРАНГ":
            nxt = self.current_idx + self.direction
            if nxt >= total:
                self.direction = -1
                nxt = max(0, total - 2)
            elif nxt < 0:
                self.direction = 1
                nxt = min(total - 1, 1)
            self.current_idx = nxt
        else:
            self.current_idx = (self.current_idx + 1) % total

        self.update()
        self.schedule_next_frame()

    def paintEvent(self, event):
        if not self.scaled_pixmaps:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(self.widget_opacity)
        pix = self.scaled_pixmaps[self.current_idx]

        if self.fun_cfg.pulse_size:
            spd = math.hypot(self.vx, self.vy)
            self.pulse_phase += 0.15 + min(0.45, spd * 0.015)
            scale = 1.0 + 0.08 * math.sin(self.pulse_phase)
            pw = max(16, int(round(self.width() * scale)))
            ph = max(16, int(round(self.height() * scale)))
            ox = (self.width() - pw) // 2
            oy = (self.height() - ph) // 2
            painter.drawPixmap(QRect(ox, oy, pw, ph), pix)
        else:
            painter.drawPixmap(0, 0, pix)

        if self.fun_cfg.rainbow_tint:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            tint = QColor.fromHsv(self.hue_shift, 200, 255, 95)
            painter.fillRect(self.rect(), tint)

        painter.end()

    def enterEvent(self, event):
        self.is_hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        super().leaveEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.08 if event.angleDelta().y() > 0 else 0.92
            nw = max(24, int(round(self.base_w * factor)))
            nh = max(24, int(round(self.base_h * factor)))
            self.set_custom_size(nw, nh)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            mult = max(1.0, self.fun_cfg.glide_speed_mult * 0.35)
            self.vy = -22.0 * mult
            self.vx += random.uniform(-12.0, 12.0) * mult
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.vx = 0.0
            self.vy = 0.0
            global_pos = event.globalPosition().toPoint()
            self.drag_offset = global_pos - self.frameGeometry().topLeft()
            now = time.perf_counter()
            self.pointer_history = [(now, global_pos.x(), global_pos.y())]
            if self.mode == "1 РАЗ (ПАУЗА)" and self.single_cycle_done:
                self.current_idx = 0
                self.single_cycle_done = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            global_pos = event.globalPosition().toPoint()
            new_pos = global_pos - self.drag_offset
            self.move(new_pos)
            self.pos_f = QPointF(float(new_pos.x()), float(new_pos.y()))

            now = time.perf_counter()
            self.pointer_history.append((now, global_pos.x(), global_pos.y()))
            cutoff = now - 0.10
            self.pointer_history = [p for p in self.pointer_history if p[0] >= cutoff]
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            now = time.perf_counter()
            global_pos = event.globalPosition().toPoint()
            self.pointer_history.append((now, global_pos.x(), global_pos.y()))

            if self.glide_level > 0 and len(self.pointer_history) >= 2:
                t0, x0, y0 = self.pointer_history[0]
                t1, x1, y1 = self.pointer_history[-1]
                dt = max(0.005, t1 - t0)

                recent = [p for p in self.pointer_history if now - p[0] <= 0.065]
                recent_dist = 0.0
                if len(recent) >= 2:
                    recent_dist = float(
                        np.hypot(recent[-1][1] - recent[0][1], recent[-1][2] - recent[0][2])
                    )

                if recent_dist > 2.0:
                    raw_vx = ((x1 - x0) / dt) * 0.016
                    raw_vy = ((y1 - y0) / dt) * 0.016
                    speed = float(np.hypot(raw_vx, raw_vy))
                    if speed > 1.5:
                        level_boost = 0.85 + (self.glide_level / 20.0) * 1.95
                        mult_boost = 1.0 + (self.fun_cfg.glide_speed_mult - 1.0) * 0.45
                        total_boost = level_boost * mult_boost
                        max_speed = min(160.0, 75.0 + self.fun_cfg.glide_speed_mult * 1.2)
                        self.vx = float(np.clip(raw_vx * total_boost, -max_speed, max_speed))
                        self.vy = float(np.clip(raw_vy * total_boost, -max_speed, max_speed))

            if self.fun_cfg.infinite_dvd or self.fun_cfg.chaos_mode:
                self.ensure_infinite_velocity()
            event.accept()

    def show_context_menu(self, global_pt: QPoint):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #292C30;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #3E434A;
            }
        """)

        header_act = QAction(f"Гифка: {self.display_label()}", menu)
        header_act.setEnabled(False)
        menu.addAction(header_act)
        menu.addSeparator()

        mode_menu = menu.addMenu(f"Режим анимации ({self.mode})")
        for m in self.MODES:
            act = QAction(m, menu)
            act.setCheckable(True)
            act.setChecked(self.mode == m)
            act.triggered.connect(lambda checked, mode_name=m: self.set_mode(mode_name))
            mode_menu.addAction(act)

        fun_menu = menu.addMenu("Развлечения (переключатели)")

        dvd_act = QAction("Бесконечное скольжение (DVD)", fun_menu)
        dvd_act.setCheckable(True)
        dvd_act.setChecked(self.fun_cfg.infinite_dvd)
        dvd_act.setEnabled(not self.fun_cfg.gravity)
        dvd_act.triggered.connect(self.toggle_dvd)
        fun_menu.addAction(dvd_act)

        chaos_act = QAction("Режим ХАОС (бесконечный)", fun_menu)
        chaos_act.setCheckable(True)
        chaos_act.setChecked(self.fun_cfg.chaos_mode)
        chaos_act.setEnabled(not self.fun_cfg.gravity)
        chaos_act.triggered.connect(self.toggle_chaos)
        fun_menu.addAction(chaos_act)

        grav_act = QAction("Гравитация и прыжки", fun_menu)
        grav_act.setCheckable(True)
        grav_act.setChecked(self.fun_cfg.gravity)
        grav_act.setEnabled(not (self.fun_cfg.infinite_dvd or self.fun_cfg.chaos_mode))
        grav_act.triggered.connect(self.toggle_gravity)
        fun_menu.addAction(grav_act)

        evade_act = QAction("Убегать от мыши", fun_menu)
        evade_act.setCheckable(True)
        evade_act.setChecked(self.fun_cfg.evade_mouse)
        evade_act.triggered.connect(self.toggle_evade)
        fun_menu.addAction(evade_act)

        chase_act = QAction("Догонять мышь", fun_menu)
        chase_act.setCheckable(True)
        chase_act.setChecked(self.fun_cfg.chase_mouse)
        chase_act.triggered.connect(self.toggle_chase)
        fun_menu.addAction(chase_act)

        collide_act = QAction("Сталкиваться с другими гифками", fun_menu)
        collide_act.setCheckable(True)
        collide_act.setChecked(self.fun_cfg.collide_gifs)
        collide_act.triggered.connect(self.toggle_collide)
        fun_menu.addAction(collide_act)

        rainbow_act = QAction("RGB перелив оттенков", fun_menu)
        rainbow_act.setCheckable(True)
        rainbow_act.setChecked(self.fun_cfg.rainbow_tint)
        rainbow_act.triggered.connect(self.toggle_rainbow)
        fun_menu.addAction(rainbow_act)

        mult_menu = menu.addMenu(f"Множитель скорости (x{int(round(self.fun_cfg.glide_speed_mult))})")
        for mval in [1, 2, 5, 10, 25, 50, 100]:
            act = QAction(f"x{mval}", mult_menu)
            act.setCheckable(True)
            act.setChecked(int(round(self.fun_cfg.glide_speed_mult)) == mval)
            act.triggered.connect(lambda checked, v=mval: self.set_glide_mult(v))
            mult_menu.addAction(act)

        glide_menu = menu.addMenu(f"Скольжение ({self.glide_level}/20)")
        for val in [0, 5, 10, 15, 20]:
            act = QAction(f"{val}/20" + (" (без скольжения)" if val == 0 else ""), glide_menu)
            act.setCheckable(True)
            act.setChecked(self.glide_level == val)
            act.triggered.connect(lambda checked, v=val: self.set_glide(v))
            glide_menu.addAction(act)

        flip_act = QAction("Отразить по горизонтали", menu)
        flip_act.setCheckable(True)
        flip_act.setChecked(self.flip_x)
        flip_act.triggered.connect(self.toggle_flip)
        menu.addAction(flip_act)

        top_act = QAction("Поверх всех окон", menu)
        top_act.setCheckable(True)
        top_act.setChecked(self.always_on_top)
        top_act.triggered.connect(self.toggle_on_top)
        menu.addAction(top_act)

        menu.addSeparator()
        close_act = QAction("Убрать эту гифку с экрана", menu)
        close_act.triggered.connect(self.close)
        menu.addAction(close_act)

        menu.exec(global_pt)

    def set_mode(self, mode_name: str):
        self.mode = mode_name
        self.single_cycle_done = False
        self.changed_widget.emit(self)

    def toggle_dvd(self):
        self.fun_cfg.infinite_dvd = not self.fun_cfg.infinite_dvd
        if self.fun_cfg.infinite_dvd:
            self.fun_cfg.gravity = False
            if self.glide_level == 0:
                self.glide_level = 15
            self.ensure_infinite_velocity()
        self.changed_widget.emit(self)

    def toggle_chaos(self):
        self.fun_cfg.chaos_mode = not self.fun_cfg.chaos_mode
        if self.fun_cfg.chaos_mode:
            self.fun_cfg.gravity = False
            if self.glide_level == 0:
                self.glide_level = 20
            self.ensure_infinite_velocity()
        self.changed_widget.emit(self)

    def toggle_gravity(self):
        self.fun_cfg.gravity = not self.fun_cfg.gravity
        if self.fun_cfg.gravity:
            self.fun_cfg.infinite_dvd = False
            self.fun_cfg.chaos_mode = False
        self.changed_widget.emit(self)

    def toggle_evade(self):
        self.fun_cfg.evade_mouse = not self.fun_cfg.evade_mouse
        if self.fun_cfg.evade_mouse:
            self.fun_cfg.chase_mouse = False
        self.changed_widget.emit(self)

    def toggle_chase(self):
        self.fun_cfg.chase_mouse = not self.fun_cfg.chase_mouse
        if self.fun_cfg.chase_mouse:
            self.fun_cfg.evade_mouse = False
        self.changed_widget.emit(self)

    def set_glide_mult(self, val: int):
        self.fun_cfg.glide_speed_mult = float(val)
        if self.fun_cfg.infinite_dvd or self.fun_cfg.chaos_mode:
            self.ensure_infinite_velocity()
        self.changed_widget.emit(self)

    def set_glide(self, val: int):
        self.glide_level = val
        if val == 0 and not (self.fun_cfg.infinite_dvd or self.fun_cfg.chaos_mode):
            self.vx = 0.0
            self.vy = 0.0
        self.changed_widget.emit(self)

    def toggle_collide(self):
        self.fun_cfg.collide_gifs = not self.fun_cfg.collide_gifs

    def toggle_rainbow(self):
        self.fun_cfg.rainbow_tint = not self.fun_cfg.rainbow_tint
        self.update()

    def toggle_flip(self):
        self.flip_x = not self.flip_x
        self.rebuild_pixmaps()

    def toggle_on_top(self):
        self.always_on_top = not self.always_on_top
        pos = self.pos()
        self._apply_window_flags()
        self.move(pos)
        self.show()

    def closeEvent(self, event):
        self.anim_timer.stop()
        self.closed_widget.emit(self)
        super().closeEvent(event)


class ManageActiveGifsDialog(QDialog):
    """Окно выборочного управления гифками, которые уже находятся на рабочем столе."""
    def __init__(self, main_win: "MainDesignerWindow"):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Гифки на рабочем столе")
        self.setFixedSize(440, 340)
        self.setStyleSheet("""
            QDialog {
                background-color: #292C30;
                color: #D7D7D9;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QLabel { color: #D7D7D9; }
            QListWidget {
                background-color: #1F2124;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item { padding: 6px; border-radius: 3px; }
            QListWidget::item:selected { background-color: #3E434A; color: #FFFFFF; }
            QPushButton {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QPushButton:hover { background-color: #3D3D3D; }
        """)

        layout = QVBoxLayout(self)
        info = QLabel("Выберите гифки в списке, чтобы убрать их по отдельности:")
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setIconSize(QSize(28, 28))
        layout.addWidget(self.list_widget)

        btn_row1 = QHBoxLayout()
        self.btn_remove_selected = QPushButton("Удалить выбранную")
        self.btn_remove_selected.clicked.connect(self.remove_selected)

        self.btn_center_selected = QPushButton("В центр экрана")
        self.btn_center_selected.clicked.connect(self.center_selected)

        btn_row1.addWidget(self.btn_remove_selected)
        btn_row1.addWidget(self.btn_center_selected)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_remove_all = QPushButton("Убрать вообще все")
        self.btn_remove_all.clicked.connect(self.remove_all)

        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.accept)

        btn_row2.addWidget(self.btn_remove_all)
        btn_row2.addWidget(self.btn_close)
        layout.addLayout(btn_row2)

        self.populate_list()

    def populate_list(self):
        self.list_widget.clear()
        for w in self.main_win.spawned_widgets:
            item = QListWidgetItem(w.thumbnail_icon(), w.display_label())
            item.setData(Qt.ItemDataRole.UserRole, w)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def remove_selected(self):
        selected_items = self.list_widget.selectedItems()
        for item in selected_items:
            w = item.data(Qt.ItemDataRole.UserRole)
            if w is not None:
                w.close()
        self.populate_list()

    def center_selected(self):
        selected_items = self.list_widget.selectedItems()
        screen = QApplication.primaryScreen().availableGeometry()
        for item in selected_items:
            w: DesktopGifWidget = item.data(Qt.ItemDataRole.UserRole)
            if w is not None:
                cx = screen.center().x() - w.width() // 2
                cy = screen.center().y() - w.height() // 2
                w.vx = 0.0
                w.vy = 0.0
                w.pos_f = QPointF(float(cx), float(cy))
                w.move(cx, cy)

    def remove_all(self):
        self.main_win.clear_all_desktop_gifs()
        self.populate_list()


class ExtraSettingsDialog(QDialog):
    """Базовые настройки отображения + кнопка создания ярлыка на Рабочем столе."""
    def __init__(self, parent_window: "MainDesignerWindow"):
        super().__init__(parent_window)
        self.main_win = parent_window
        self.setWindowTitle("Основные настройки отображения")
        self.setFixedSize(410, 310)
        self.setStyleSheet("""
            QDialog {
                background-color: #292C30;
                color: #D7D7D9;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QLabel, QCheckBox { color: #D7D7D9; }
            QPushButton, QSlider {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                border-radius: 4px;
                padding: 5px 10px;
            }
            QPushButton:hover { background-color: #3D3D3D; }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(int(self.main_win.cfg_opacity * 100))
        self.opacity_lbl = QLabel(f"{int(self.main_win.cfg_opacity * 100)}%")
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_lbl.setText(f"{v}%")
        )
        op_row = QHBoxLayout()
        op_row.addWidget(self.opacity_slider)
        op_row.addWidget(self.opacity_lbl)
        form.addRow("Прозрачность:", op_row)

        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 300)
        self.speed_slider.setValue(int(self.main_win.cfg_speed * 100))
        self.speed_lbl = QLabel(f"{self.main_win.cfg_speed:.2f}x")
        self.speed_slider.valueChanged.connect(
            lambda v: self.speed_lbl.setText(f"{v / 100.0:.2f}x")
        )
        sp_row = QHBoxLayout()
        sp_row.addWidget(self.speed_slider)
        sp_row.addWidget(self.speed_lbl)
        form.addRow("Скорость GIF (до 3x):", sp_row)

        self.chk_top = QCheckBox("Поверх всех окон")
        self.chk_top.setChecked(self.main_win.cfg_always_on_top)
        form.addRow("", self.chk_top)

        self.chk_flip = QCheckBox("Отразить гифку по горизонтали")
        self.chk_flip.setChecked(self.main_win.cfg_flip_x)
        form.addRow("", self.chk_flip)

        self.chk_keep_aspect = QCheckBox("Сохранять пропорции при изменении размера")
        self.chk_keep_aspect.setChecked(self.main_win.cfg_keep_aspect)
        form.addRow("", self.chk_keep_aspect)

        layout.addLayout(form)
        layout.addStretch()

        shortcut_btn = QPushButton("Создать ярлык запуска на Рабочем столе / в Меню")
        shortcut_btn.clicked.connect(lambda: install_desktop_shortcut(self))
        layout.addWidget(shortcut_btn)

        btns = QHBoxLayout()
        fun_btn = QPushButton("Развлечения и физика...")
        fun_btn.clicked.connect(self.main_win.open_fun_dialog)
        ok_btn = QPushButton("СОХРАНИТЬ")
        ok_btn.clicked.connect(self.save_and_close)
        btns.addWidget(fun_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def save_and_close(self):
        self.main_win.cfg_opacity = self.opacity_slider.value() / 100.0
        self.main_win.cfg_speed = self.speed_slider.value() / 100.0
        self.main_win.cfg_always_on_top = self.chk_top.isChecked()
        self.main_win.cfg_flip_x = self.chk_flip.isChecked()
        self.main_win.cfg_keep_aspect = self.chk_keep_aspect.isChecked()
        self.accept()


class FigmaGlideSlider(QWidget):
    """
    Кастомный слайдер скольжения, в точности повторяющий CSS из Figma:
    Rectangle 17 (width: 40px, height: 2px, left: 459px, top: 102px, #2D2D2D)
    Ellipse 1 (width: 4px, height: 4px, background: #2D2D2D, border: 0.5px solid #D7D7D9)
    """
    valueChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget, minimum: int = 0, maximum: int = 20, value: int = 0):
        super().__init__(parent)
        self.min_val = minimum
        self.max_val = maximum
        self.val = value
        self.dragging = False
        self.setGeometry(455, 93, 48, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setValue(self, v: int):
        v = max(self.min_val, min(self.max_val, v))
        if v != self.val:
            self.val = v
            self.update()
            self.valueChanged.emit(self.val)

    def value(self) -> int:
        return self.val

    def _update_from_x(self, local_x: float):
        ratio = (local_x - 4.0) / 40.0
        ratio = max(0.0, min(1.0, ratio))
        new_val = int(round(self.min_val + ratio * (self.max_val - self.min_val)))
        self.setValue(new_val)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._update_from_x(event.position().x())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self._update_from_x(event.position().x())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            event.accept()

    def wheelEvent(self, event):
        delta = 1 if event.angleDelta().y() > 0 else -1
        self.setValue(self.val + delta)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(4, 9, 40, 2, QColor("#2D2D2D"))

        ratio = (self.val - self.min_val) / float(max(1, self.max_val - self.min_val))
        cx = 4.0 + ratio * 40.0
        knob_rect = QRect(int(round(cx - 2.0)), 8, 4, 4)

        painter.setBrush(QBrush(QColor("#2D2D2D")))
        pen = QPen(QColor("#D7D7D9"))
        pen.setWidthF(0.8)
        painter.setPen(pen)
        painter.drawEllipse(knob_rect)
        painter.end()


class MainDesignerWindow(QWidget):
    """
    Главное окно приложения по размерам и координатам из Figma (606x380).
    Поддерживает системный трей (System Tray) на Linux и Windows 10/11.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GIF Desktop Manager")
        self.setWindowIcon(create_app_icon())
        self.setFixedSize(606, 380)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self._drag_hover = False

        self.current_file_name = "GIF"
        self.raw_frames: List[Image.Image] = []
        self.raw_durations: List[int] = []
        self.bg_removed_frames: List[Image.Image] = []
        self.processed_frames: List[Image.Image] = []
        self.durations: List[int] = []
        self.preview_idx = 0
        self.bg_mode = "keep"
        self.bg_color = (255, 255, 255)
        self.bg_tolerance = 38

        self.cfg_opacity = 1.0
        self.cfg_speed = 1.0
        self.cfg_always_on_top = True
        self.cfg_flip_x = False
        self.cfg_keep_aspect = False
        self.aspect_ratio = 1.0

        self.fun_cfg = FunConfig()
        self.spawned_widgets: List[DesktopGifWidget] = []

        self._dragging_win = False
        self._drag_win_offset = QPoint(0, 0)

        self._build_figma_ui()
        self._setup_system_tray()

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._tick_preview)

        self.world_physics_timer = QTimer(self)
        self.world_physics_timer.setInterval(16)
        self.world_physics_timer.timeout.connect(self._step_world_physics)
        self.world_physics_timer.start()

    def _setup_system_tray(self):
        """Добавляет иконку в системный трей Linux / Windows 10 для быстрого управления."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon(create_app_icon(), self)
        self.tray_icon.setToolTip("GIF Desktop Manager")

        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #292C30;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QMenu::item:selected { background-color: #3E434A; }
        """)

        act_show = QAction("Показать / Развернуть окно", tray_menu)
        act_show.triggered.connect(self.restore_from_tray)
        tray_menu.addAction(act_show)

        act_fun = QAction("Развлечения и физика...", tray_menu)
        act_fun.triggered.connect(self.open_fun_dialog)
        tray_menu.addAction(act_fun)

        act_shortcut = QAction("Создать ярлык на Рабочем столе", tray_menu)
        act_shortcut.triggered.connect(lambda: install_desktop_shortcut(self))
        tray_menu.addAction(act_shortcut)

        tray_menu.addSeparator()
        act_clear = QAction("Убрать все гифки с экрана", tray_menu)
        act_clear.triggered.connect(self.clear_all_desktop_gifs)
        tray_menu.addAction(act_clear)

        act_quit = QAction("Выход", tray_menu)
        act_quit.triggered.connect(self.close)
        tray_menu.addAction(act_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _build_figma_ui(self):
        btn_style_top = """
            QPushButton {
                background: transparent;
                color: #D7D7D9;
                border: none;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3E434A;
                border-radius: 2px;
            }
        """
        self.btn_min = QPushButton("_", self)
        self.btn_min.setGeometry(566, 1, 13, 19)
        self.btn_min.setStyleSheet(btn_style_top)
        self.btn_min.setToolTip("Свернуть окно (гифки останутся на рабочем столе)")
        self.btn_min.clicked.connect(self.minimize_main_window)

        self.btn_extra = QPushButton("=", self)
        self.btn_extra.setGeometry(579, 1, 13, 19)
        self.btn_extra.setStyleSheet(btn_style_top)
        self.btn_extra.setToolTip("Основные настройки и создание ярлыка")
        self.btn_extra.clicked.connect(self.open_extra_settings)

        self.btn_close = QPushButton("X", self)
        self.btn_close.setGeometry(592, 1, 13, 19)
        self.btn_close.setStyleSheet(
            btn_style_top + "QPushButton:hover { background-color: #C42B1C; color: white; }"
        )
        self.btn_close.setToolTip("Закрыть приложение")
        self.btn_close.clicked.connect(self.close)

        # --- Область превью / загрузки (Rectangle 2: 297x297, left 6, top 25) ---
        self.preview_area = QLabel(self)
        self.preview_area.setGeometry(6, 25, 297, 297)
        self.preview_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_area.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_area.setToolTip("Нажмите или перетащите сюда GIF-файл мышкой")
        self._update_preview_area_style(False)
        self.preview_area.mousePressEvent = lambda ev: self.load_gif_dialog()

        self.lbl_upload = QLabel("ЗАГРУЗИТЬ\n(или перетащите файл)", self)
        self.lbl_upload.setGeometry(65, 204, 180, 32)
        self.lbl_upload.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_upload.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_upload.setStyleSheet("""
            color: #D7D7D9;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            font-size: 11px;
            font-weight: 400;
            background: transparent;
        """)

        bottom_btn_style = """
            QPushButton {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: none;
                border-radius: 4px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 8px;
                font-weight: 400;
            }
            QPushButton:hover {
                background-color: #3A3A3A;
                border: 0.5px solid #6E6E6E;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
            QPushButton:checked {
                background-color: #3B5B84;
                color: #FFFFFF;
                border: 0.5px solid #78A9E6;
            }
        """

        self.btn_cancel = QPushButton("ОТМЕНА", self)
        self.btn_cancel.setGeometry(6, 341, 90, 20)
        self.btn_cancel.setStyleSheet(bottom_btn_style)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reset_current_gif)

        self.btn_edit = QPushButton("РЕДАКТИРОВАТЬ", self)
        self.btn_edit.setGeometry(110, 341, 90, 20)
        self.btn_edit.setStyleSheet(bottom_btn_style)
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setToolTip(
            "Редактор самой гифки: обрезка кадров, реверс, поворот, фильтры, стикер-обводка"
        )
        self.btn_edit.clicked.connect(self.open_gif_editor_dialog)

        self.btn_add = QPushButton("ДОБАВИТЬ", self)
        self.btn_add.setGeometry(213, 341, 90, 20)
        self.btn_add.setStyleSheet(bottom_btn_style)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self.spawn_gif_on_desktop)

        # --- Правая колонка: «настройки» ---
        self.btn_header_settings = QPushButton("настройки", self)
        self.btn_header_settings.setGeometry(382, 25, 145, 24)
        self.btn_header_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_header_settings.setToolTip("Нажмите для открытия дополнительных настроек и создания ярлыка")
        self.btn_header_settings.setStyleSheet("""
            QPushButton {
                background-color: rgba(39, 39, 39, 178);
                color: #D7D7D9;
                border: none;
                border-radius: 4px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 16px;
                font-weight: 400;
            }
            QPushButton:hover {
                background-color: rgba(52, 52, 52, 200);
            }
        """)
        self.btn_header_settings.clicked.connect(self.open_extra_settings)

        pill_label_style = """
            QLabel {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border-radius: 4px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 8px;
                font-weight: 400;
            }
        """

        input_style = """
            QLineEdit {
                background-color: #2D2D2D;
                color: #D7D7D9;
                border: none;
                border-radius: 4px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 8px;
                selection-background-color: #5294E2;
            }
            QLineEdit:hover {
                background-color: #363636;
                border: 0.5px solid #6E6E6E;
            }
            QLineEdit:focus {
                border: 0.5px solid #8E8E8E;
            }
        """

        # 1. РАЗМЕР (top 60)
        self.lbl_size = QLabel("РАЗМЕР", self)
        self.lbl_size.setGeometry(361, 60, 90, 20)
        self.lbl_size.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_size.setStyleSheet(pill_label_style)

        self.input_w = ScrubbableLineEdit("100", self, minimum=20, maximum=2500)
        self.input_w.setGeometry(459, 60, 40, 20)
        self.input_w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_w.setStyleSheet(input_style)
        self.input_w.setToolTip("Ширина (px). Зажмите ЛКМ и ведите мышь влево/вправо")
        self.input_w.valueScrubbed.connect(self._on_width_scrubbed)
        self.input_w.editingFinished.connect(self._on_width_edited)

        self.input_h = ScrubbableLineEdit("100", self, minimum=20, maximum=2500)
        self.input_h.setGeometry(507, 60, 40, 20)
        self.input_h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_h.setStyleSheet(input_style)
        self.input_h.setToolTip("Высота (px). Зажмите ЛКМ и ведите мышь влево/вправо")
        self.input_h.valueScrubbed.connect(self._on_height_scrubbed)
        self.input_h.editingFinished.connect(self._on_height_edited)

        # 2. СКОЛЬЖЕНИЕ (top 93) + МНОЖИТЕЛЬ СКОЛЬЖЕНИЯ (x1..x100)
        self.lbl_glide = QLabel("СКОЛЬЖЕНИЕ", self)
        self.lbl_glide.setGeometry(361, 93, 90, 20)
        self.lbl_glide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_glide.setStyleSheet(pill_label_style)

        self.glide_slider = FigmaGlideSlider(self, minimum=0, maximum=20, value=15)
        self.glide_slider.valueChanged.connect(self._on_glide_changed)

        self.lbl_glide_val = QLabel("15/20", self)
        self.lbl_glide_val.setGeometry(507, 93, 40, 20)
        self.lbl_glide_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_glide_val.setStyleSheet(pill_label_style)

        self.input_glide_mult = ScrubbableLineEdit("x1", self, minimum=1, maximum=100, prefix="x")
        self.input_glide_mult.setGeometry(553, 93, 42, 20)
        self.input_glide_mult.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_glide_mult.setStyleSheet(input_style)
        self.input_glide_mult.setToolTip(
            "Множитель скорости скольжения (от x1 до x100).\n"
            "Зажмите ЛКМ и тяните вправо/влево для изменения!"
        )
        self.input_glide_mult.valueScrubbed.connect(self._on_glide_mult_changed)
        self.input_glide_mult.editingFinished.connect(
            lambda: self._on_glide_mult_changed(self.input_glide_mult.current_int())
        )

        # 3. РЕЖИМ АНИМАЦИИ (top 126)
        self.lbl_mode = QLabel("РЕЖИМ", self)
        self.lbl_mode.setGeometry(361, 126, 90, 20)
        self.lbl_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_mode.setStyleSheet(pill_label_style)

        self.mode_index = 0
        self.btn_mode_val = QPushButton(DesktopGifWidget.MODES[self.mode_index], self)
        self.btn_mode_val.setGeometry(459, 126, 90, 20)
        self.btn_mode_val.setStyleSheet(bottom_btn_style)
        self.btn_mode_val.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_val.setToolTip("Режим проигрывания кадров GIF")
        self.btn_mode_val.clicked.connect(self.cycle_mode)

        # 4. РАЗВЛЕЧЕНИЯ (top 159) + переключатель ХАОС
        self.lbl_fun_title = QLabel("РАЗВЛЕЧЕНИЯ", self)
        self.lbl_fun_title.setGeometry(361, 159, 90, 20)
        self.lbl_fun_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fun_title.setStyleSheet(pill_label_style)

        self.btn_fun_menu = QPushButton("ОТКРЫТЬ", self)
        self.btn_fun_menu.setGeometry(459, 159, 68, 20)
        self.btn_fun_menu.setStyleSheet(bottom_btn_style)
        self.btn_fun_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fun_menu.setToolTip(
            "Открыть панель развлекательных функций (переключатели и множители:\n"
            "Бесконечный DVD, Убегать от мыши, Гравитация, Множители до x100 и др.)"
        )
        self.btn_fun_menu.clicked.connect(self.open_fun_dialog)

        self.btn_chaos_toggle = QPushButton("ХАОС: ВЫКЛ", self)
        self.btn_chaos_toggle.setCheckable(True)
        self.btn_chaos_toggle.setGeometry(531, 159, 64, 20)
        self.btn_chaos_toggle.setStyleSheet(bottom_btn_style)
        self.btn_chaos_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_chaos_toggle.setToolTip(
            "Переключатель режима ХАОС: делает скольжение всех гифок бесконечным и быстрым"
        )
        self.btn_chaos_toggle.toggled.connect(self.toggle_chaos_switch)

        # 5. СТОЛКНОВЕНИЯ (top 192)
        self.lbl_physics_title = QLabel("СТОЛКНОВЕНИЯ", self)
        self.lbl_physics_title.setGeometry(361, 192, 90, 20)
        self.lbl_physics_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_physics_title.setStyleSheet(pill_label_style)

        self.btn_collide_val = QPushButton("ГИФКИ: ВКЛ", self)
        self.btn_collide_val.setGeometry(459, 192, 66, 20)
        self.btn_collide_val.setStyleSheet(bottom_btn_style)
        self.btn_collide_val.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collide_val.setToolTip("Упругий отскок гифок друг от друга при столкновении")
        self.btn_collide_val.clicked.connect(self.toggle_collide_btn)

        self.btn_bounce_val = QPushButton("КРАЯ: ВКЛ", self)
        self.btn_bounce_val.setGeometry(529, 192, 66, 20)
        self.btn_bounce_val.setStyleSheet(bottom_btn_style)
        self.btn_bounce_val.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bounce_val.setToolTip("Отскок от краёв экрана")
        self.btn_bounce_val.clicked.connect(self.toggle_bounce_btn)

        # 6. СКОРОСТЬ ДО 3.0x (top 225)
        self.lbl_speed_title = QLabel("СКОРОСТЬ", self)
        self.lbl_speed_title.setGeometry(361, 225, 90, 20)
        self.lbl_speed_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_speed_title.setStyleSheet(pill_label_style)

        self.btn_speed_val = QPushButton("1.0x", self)
        self.btn_speed_val.setGeometry(459, 225, 66, 20)
        self.btn_speed_val.setStyleSheet(bottom_btn_style)
        self.btn_speed_val.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_speed_val.setToolTip("Скорость анимации от 0.25x до 3.0x")
        self.btn_speed_val.clicked.connect(self.cycle_speed)

        self.btn_opacity_val = QPushButton("ПРОЗР: 100%", self)
        self.btn_opacity_val.setGeometry(529, 225, 66, 20)
        self.btn_opacity_val.setStyleSheet(bottom_btn_style)
        self.btn_opacity_val.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_opacity_val.setToolTip("Прозрачность гифки")
        self.btn_opacity_val.clicked.connect(self.cycle_opacity)

        # 7. ФОН ГИФКИ (top 258)
        self.lbl_bg_title = QLabel("ФОН ГИФКИ", self)
        self.lbl_bg_title.setGeometry(361, 258, 90, 20)
        self.lbl_bg_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_bg_title.setStyleSheet(pill_label_style)

        self.btn_bg_status = QPushButton("ОРИГИНАЛ", self)
        self.btn_bg_status.setGeometry(459, 258, 136, 20)
        self.btn_bg_status.setStyleSheet(bottom_btn_style)
        self.btn_bg_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bg_status.setToolTip("Удаление фона гифки (Хромакей / Белый фон / ИИ rembg)")
        self.btn_bg_status.clicked.connect(self.edit_background_dialog)

        # 8. НА ЭКРАНЕ (top 291)
        self.lbl_manage_title = QLabel("НА ЭКРАНЕ", self)
        self.lbl_manage_title.setGeometry(361, 291, 90, 20)
        self.lbl_manage_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_manage_title.setStyleSheet(pill_label_style)

        self.btn_manage_active = QPushButton("0 шт. (УБРАТЬ)", self)
        self.btn_manage_active.setGeometry(459, 291, 136, 20)
        self.btn_manage_active.setStyleSheet(bottom_btn_style)
        self.btn_manage_active.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manage_active.setToolTip("Выборочно убрать любую гифку с экрана")
        self.btn_manage_active.clicked.connect(self.show_selective_remove_menu)

        # 9. Кнопка быстрого создания ярлыка прямо в нижней строке справа (top 341)
        self.btn_make_shortcut = QPushButton("СОЗДАТЬ ЯРЛЫК", self)
        self.btn_make_shortcut.setGeometry(361, 341, 90, 20)
        self.btn_make_shortcut.setStyleSheet(bottom_btn_style)
        self.btn_make_shortcut.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_make_shortcut.setToolTip(
            "Создать ярлык на Рабочем столе и в меню приложений, чтобы открывать без консоли"
        )
        self.btn_make_shortcut.clicked.connect(lambda: install_desktop_shortcut(self))

        self.lbl_hint = QLabel("Тяните числа мышью | ПКМ — меню", self)
        self.lbl_hint.setGeometry(456, 341, 144, 20)
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hint.setStyleSheet("""
            color: #9E9EA2;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            font-size: 7.5px;
            background: transparent;
        """)

    # --- Глобальный 2D физический движок (60 FPS) ---
    def _step_world_physics(self):
        active = [w for w in self.spawned_widgets if w.isVisible()]
        if not active:
            return

        cursor_pt = QCursor.pos()
        cx_mouse, cy_mouse = float(cursor_pt.x()), float(cursor_pt.y())

        n = len(active)
        for i in range(n):
            a = active[i]
            if a.dragging:
                continue
            if not (a.fun_cfg.magnet_attract or a.fun_cfg.magnet_repel):
                continue
            acx = a.pos_f.x() + a.width() * 0.5
            acy = a.pos_f.y() + a.height() * 0.5
            for j in range(n):
                if i == j:
                    continue
                b = active[j]
                bcx = b.pos_f.x() + b.width() * 0.5
                bcy = b.pos_f.y() + b.height() * 0.5
                dx = bcx - acx
                dy = bcy - acy
                dist = math.hypot(dx, dy)
                if dist < 20.0 or dist > 650.0:
                    continue
                strength = (180.0 / max(60.0, dist)) * 0.35
                if a.fun_cfg.magnet_attract:
                    a.vx += (dx / dist) * strength
                    a.vy += (dy / dist) * strength
                elif a.fun_cfg.magnet_repel:
                    a.vx -= (dx / dist) * strength * 1.4
                    a.vy -= (dy / dist) * strength * 1.4

        for w in active:
            if w.dragging:
                w.vx = 0.0
                w.vy = 0.0
                continue

            cfg = w.fun_cfg
            is_infinite = cfg.infinite_dvd or cfg.chaos_mode

            if not is_infinite and not cfg.gravity and not cfg.evade_mouse and not cfg.chase_mouse:
                if w.glide_level == 0:
                    w.vx = 0.0
                    w.vy = 0.0
                    continue

            screen_obj = QApplication.screenAt(w.geometry().center()) or QApplication.primaryScreen()
            bounds = screen_obj.availableGeometry()
            min_x = float(bounds.left())
            max_x = float(bounds.right() - w.width())
            min_y = float(bounds.top())
            max_y = float(bounds.bottom() - w.height())

            center_x = w.pos_f.x() + w.width() * 0.5
            center_y = w.pos_f.y() + w.height() * 0.5

            if cfg.evade_mouse:
                dx = center_x - cx_mouse
                dy = center_y - cy_mouse
                dist = math.hypot(dx, dy)
                fear_radius = max(190.0, max(w.width(), w.height()) * 1.6)
                if dist < fear_radius and dist > 0.5:
                    push = ((fear_radius - dist) / fear_radius) * (2.5 + cfg.mouse_force_mult * 0.85)
                    w.vx += (dx / dist) * push
                    w.vy += (dy / dist) * push
            elif cfg.chase_mouse:
                dx = cx_mouse - center_x
                dy = cy_mouse - center_y
                dist = math.hypot(dx, dy)
                if dist > 24.0:
                    pull = 0.35 + cfg.mouse_force_mult * 0.28
                    w.vx += (dx / dist) * pull
                    w.vy += (dy / dist) * pull

            if is_infinite:
                w.ensure_infinite_velocity()
                friction = 1.0
                bounciness = 1.0 * cfg.bounciness_mult
            elif cfg.gravity:
                w.vy += 0.62 * cfg.gravity_mult
                friction = 0.994
                bounciness = (0.76 + (w.glide_level / 20.0) * 0.20) * cfg.bounciness_mult
            else:
                t_norm = w.glide_level / 20.0
                friction = 0.91 + (t_norm ** 0.55) * 0.0875
                bounciness = (0.82 + t_norm * 0.17) * cfg.bounciness_mult

            max_spd = min(175.0, 75.0 + cfg.glide_speed_mult * 1.3)
            spd = math.hypot(w.vx, w.vy)
            if spd > max_spd:
                w.vx = (w.vx / spd) * max_spd
                w.vy = (w.vy / spd) * max_spd

            if not is_infinite and not cfg.gravity and abs(w.vx) < 0.05 and abs(w.vy) < 0.05:
                w.vx = 0.0
                w.vy = 0.0
                continue

            nx = w.pos_f.x() + w.vx
            ny = w.pos_f.y() + w.vy

            if cfg.bounce_edges or is_infinite or cfg.gravity:
                if nx < min_x:
                    nx = min_x
                    w.vx = abs(w.vx) * bounciness
                elif nx > max_x:
                    nx = max_x
                    w.vx = -abs(w.vx) * bounciness

                if ny < min_y:
                    ny = min_y
                    w.vy = abs(w.vy) * bounciness
                elif ny > max_y:
                    ny = max_y
                    if cfg.gravity and abs(w.vy) < 2.4:
                        w.vy = 0.0
                        w.vx *= 0.94
                    else:
                        w.vy = -abs(w.vy) * bounciness
            else:
                if nx < min_x - w.width() * 0.5:
                    nx = max_x
                elif nx > max_x + w.width() * 0.5:
                    nx = min_x
                if ny < min_y - w.height() * 0.5:
                    ny = max_y
                elif ny > max_y + w.height() * 0.5:
                    ny = min_y

            w.vx *= friction
            w.vy *= friction
            w.pos_f = QPointF(nx, ny)

        for i in range(n):
            a = active[i]
            if not a.fun_cfg.collide_gifs:
                continue
            for j in range(i + 1, n):
                b = active[j]
                if not b.fun_cfg.collide_gifs:
                    continue
                self._resolve_pair_collision(a, b)

        for w in active:
            if not w.dragging:
                target_pt = QPoint(int(round(w.pos_f.x())), int(round(w.pos_f.y())))
                if w.pos() != target_pt:
                    w.move(target_pt)
            if w.fun_cfg.pulse_size:
                w.update()

    @staticmethod
    def _resolve_pair_collision(a: DesktopGifWidget, b: DesktopGifWidget):
        ax, ay = a.pos_f.x(), a.pos_f.y()
        aw, ah = float(a.width()), float(a.height())
        bx, by = b.pos_f.x(), b.pos_f.y()
        bw, bh = float(b.width()), float(b.height())

        acx, acy = ax + aw * 0.5, ay + ah * 0.5
        bcx, bcy = bx + bw * 0.5, by + bh * 0.5

        dx = bcx - acx
        dy = bcy - acy

        overlap_x = (aw + bw) * 0.5 - abs(dx)
        if overlap_x <= 0:
            return
        overlap_y = (ah + bh) * 0.5 - abs(dy)
        if overlap_y <= 0:
            return

        if abs(dx) < 0.01 and abs(dy) < 0.01:
            dx = 1.0
            dy = 0.0

        if overlap_x < overlap_y:
            sep_nx = 1.0 if dx >= 0 else -1.0
            sep_ny = 0.0
            penetration = overlap_x + 0.5
        else:
            sep_nx = 0.0
            sep_ny = 1.0 if dy >= 0 else -1.0
            penetration = overlap_y + 0.5

        if a.dragging and not b.dragging:
            b.pos_f = QPointF(bx + sep_nx * penetration, by + sep_ny * penetration)
        elif b.dragging and not a.dragging:
            a.pos_f = QPointF(ax - sep_nx * penetration, ay - sep_ny * penetration)
        elif not a.dragging and not b.dragging:
            total_m = a.mass + b.mass
            ratio_a = b.mass / total_m
            ratio_b = a.mass / total_m
            a.pos_f = QPointF(ax - sep_nx * penetration * ratio_a, ay - sep_ny * penetration * ratio_a)
            b.pos_f = QPointF(bx + sep_nx * penetration * ratio_b, by + sep_ny * penetration * ratio_b)

        avx, avy = a.vx, a.vy
        bvx, bvy = b.vx, b.vy
        if a.dragging and len(a.pointer_history) >= 2:
            t0, x0, y0 = a.pointer_history[0]
            t1, x1, y1 = a.pointer_history[-1]
            dt = max(0.005, t1 - t0)
            avx = np.clip(((x1 - x0) / dt) * 0.022, -75.0, 75.0)
            avy = np.clip(((y1 - y0) / dt) * 0.022, -75.0, 75.0)
        if b.dragging and len(b.pointer_history) >= 2:
            t0, x0, y0 = b.pointer_history[0]
            t1, x1, y1 = b.pointer_history[-1]
            dt = max(0.005, t1 - t0)
            bvx = np.clip(((x1 - x0) / dt) * 0.022, -75.0, 75.0)
            bvy = np.clip(((y1 - y0) / dt) * 0.022, -75.0, 75.0)

        center_dist = math.hypot(dx, dy)
        if center_dist > 1.0:
            cnx, cny = dx / center_dist, dy / center_dist
            nx = sep_nx * 0.65 + cnx * 0.35
            ny = sep_ny * 0.65 + cny * 0.35
            n_len = math.hypot(nx, ny)
            nx, ny = nx / n_len, ny / n_len
        else:
            nx, ny = sep_nx, sep_ny

        rvx = bvx - avx
        rvy = bvy - avy
        vel_along_normal = rvx * nx + rvy * ny

        if vel_along_normal > 0:
            return

        restitution = 0.95 * ((a.fun_cfg.bounciness_mult + b.fun_cfg.bounciness_mult) * 0.5)
        if (
            a.fun_cfg.infinite_dvd
            or a.fun_cfg.chaos_mode
            or b.fun_cfg.infinite_dvd
            or b.fun_cfg.chaos_mode
        ):
            restitution = max(1.0, restitution)

        inv_ma = 0.0 if a.dragging else (1.0 / a.mass)
        inv_mb = 0.0 if b.dragging else (1.0 / b.mass)
        inv_sum = inv_ma + inv_mb
        if inv_sum <= 0:
            return

        j_impulse = -(1.0 + restitution) * vel_along_normal / inv_sum
        impulse_x = j_impulse * nx
        impulse_y = j_impulse * ny

        if not a.dragging:
            a.vx = avx - impulse_x * inv_ma
            a.vy = avy - impulse_y * inv_ma
        if not b.dragging:
            b.vx = bvx + impulse_x * inv_mb
            b.vy = bvy + impulse_y * inv_mb

    def apply_fun_config(self, new_cfg: FunConfig, apply_to_existing: bool = True):
        self.fun_cfg = new_cfg.copy()
        self.input_glide_mult.set_int(int(round(self.fun_cfg.glide_speed_mult)), emit_signal=False)
        self.btn_chaos_toggle.blockSignals(True)
        self.btn_chaos_toggle.setChecked(self.fun_cfg.chaos_mode)
        self.btn_chaos_toggle.setText("ХАОС: ВКЛ" if self.fun_cfg.chaos_mode else "ХАОС: ВЫКЛ")
        self.btn_chaos_toggle.blockSignals(False)

        self.btn_collide_val.setText("ГИФКИ: ВКЛ" if self.fun_cfg.collide_gifs else "ГИФКИ: ВЫКЛ")
        self.btn_bounce_val.setText("КРАЯ: ВКЛ" if self.fun_cfg.bounce_edges else "КРАЯ: ВЫКЛ")
        self.btn_fun_menu.setText(self.fun_cfg.summary_text())

        if apply_to_existing:
            for w in self.spawned_widgets:
                w.fun_cfg = self.fun_cfg.copy()
                if w.fun_cfg.infinite_dvd or w.fun_cfg.chaos_mode:
                    if w.glide_level == 0:
                        w.glide_level = max(15, self.glide_slider.value())
                    w.ensure_infinite_velocity()
                w.update()

    def toggle_chaos_switch(self, checked: bool):
        self.fun_cfg.chaos_mode = checked
        if checked:
            self.fun_cfg.gravity = False
            if self.glide_slider.value() == 0:
                self.glide_slider.setValue(18)
        self.apply_fun_config(self.fun_cfg, apply_to_existing=True)

    def _on_glide_mult_changed(self, val: int):
        self.fun_cfg.glide_speed_mult = float(val)
        self.btn_fun_menu.setText(self.fun_cfg.summary_text())
        for w in self.spawned_widgets:
            w.fun_cfg.glide_speed_mult = float(val)
            if w.fun_cfg.infinite_dvd or w.fun_cfg.chaos_mode:
                w.ensure_infinite_velocity()

    def open_fun_dialog(self):
        dlg = FunFeaturesDialog(self)
        dlg.exec()

    def _update_preview_area_style(self, highlight_drop: bool):
        if highlight_drop:
            self.preview_area.setStyleSheet("""
                QLabel {
                    background-color: rgba(58, 75, 98, 210);
                    border: 1.5px dashed #5294E2;
                    border-radius: 4px;
                }
            """)
        else:
            self.preview_area.setStyleSheet("""
                QLabel {
                    background-color: rgba(39, 39, 39, 178);
                    border-radius: 4px;
                }
                QLabel:hover {
                    background-color: rgba(48, 48, 48, 195);
                }
            """)

    def minimize_main_window(self):
        self.showMinimized()
        QTimer.singleShot(50, self._ensure_spawned_visible)

    def changeEvent(self, event: QEvent):
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                QTimer.singleShot(30, self._ensure_spawned_visible)
        super().changeEvent(event)

    def _ensure_spawned_visible(self):
        for w in self.spawned_widgets:
            if not w.isVisible():
                w.show()

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                local_path = url.toLocalFile()
                if local_path and local_path.lower().endswith(SUPPORTED_EXTENSIONS):
                    self._drag_hover = True
                    self._update_preview_area_style(True)
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._drag_hover = False
        self._update_preview_area_style(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._drag_hover = False
        self._update_preview_area_style(False)
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                local_path = url.toLocalFile()
                if local_path and os.path.isfile(local_path):
                    event.acceptProposedAction()
                    self.load_gif_from_path(local_path)
                    return
        event.ignore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        painter.fillRect(0, 0, 606, 380, QColor(55, 55, 55, 232))
        painter.setPen(QPen(QColor("#5E5E5E"), 1))
        painter.drawRect(0, 0, 605, 379)
        painter.fillRect(1, 1, 604, 19, QColor("#292C30"))

        if not self.processed_frames:
            painter.fillRect(153, 100, 4, 70, QColor("#D7D7D9"))
            painter.fillRect(120, 133, 70, 4, QColor("#D7D7D9"))

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 22:
            self._dragging_win = True
            self._drag_win_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging_win:
            self.move(event.globalPosition().toPoint() - self._drag_win_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_win = False
            event.accept()

    def _on_glide_changed(self, val: int):
        self.lbl_glide_val.setText(f"{val}/20")
        for w in self.spawned_widgets:
            w.glide_level = val
            if w.fun_cfg.infinite_dvd or w.fun_cfg.chaos_mode:
                w.ensure_infinite_velocity()

    def _on_width_scrubbed(self, w: int):
        if self.cfg_keep_aspect and self.aspect_ratio > 0:
            h = max(20, min(2500, int(round(w / self.aspect_ratio))))
            self.input_h.set_int(h, emit_signal=False)

    def _on_height_scrubbed(self, h: int):
        if self.cfg_keep_aspect and self.aspect_ratio > 0:
            w = max(20, min(2500, int(round(h * self.aspect_ratio))))
            self.input_w.set_int(w, emit_signal=False)

    def _on_width_edited(self):
        w = self.input_w.current_int()
        self.input_w.set_int(w, emit_signal=False)
        if self.cfg_keep_aspect and self.aspect_ratio > 0:
            h = max(20, min(2500, int(round(w / self.aspect_ratio))))
            self.input_h.set_int(h, emit_signal=False)

    def _on_height_edited(self):
        h = self.input_h.current_int()
        self.input_h.set_int(h, emit_signal=False)
        if self.cfg_keep_aspect and self.aspect_ratio > 0:
            w = max(20, min(2500, int(round(h * self.aspect_ratio))))
            self.input_w.set_int(w, emit_signal=False)

    def cycle_mode(self):
        self.mode_index = (self.mode_index + 1) % len(DesktopGifWidget.MODES)
        self.btn_mode_val.setText(DesktopGifWidget.MODES[self.mode_index])

    def cycle_opacity(self):
        steps = [1.0, 0.85, 0.7, 0.5, 0.35]
        cur = min(steps, key=lambda x: abs(x - self.cfg_opacity))
        idx = (steps.index(cur) + 1) % len(steps)
        self.cfg_opacity = steps[idx]
        self.btn_opacity_val.setText(f"ПРОЗР: {int(self.cfg_opacity * 100)}%")

    def cycle_speed(self):
        steps = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
        cur = min(steps, key=lambda x: abs(x - self.cfg_speed))
        idx = (steps.index(cur) + 1) % len(steps)
        self.cfg_speed = steps[idx]
        self.btn_speed_val.setText(f"{self.cfg_speed:g}x")

    def toggle_collide_btn(self):
        self.fun_cfg.collide_gifs = not self.fun_cfg.collide_gifs
        self.btn_collide_val.setText("ГИФКИ: ВКЛ" if self.fun_cfg.collide_gifs else "ГИФКИ: ВЫКЛ")
        for w in self.spawned_widgets:
            w.fun_cfg.collide_gifs = self.fun_cfg.collide_gifs

    def toggle_bounce_btn(self):
        self.fun_cfg.bounce_edges = not self.fun_cfg.bounce_edges
        self.btn_bounce_val.setText("КРАЯ: ВКЛ" if self.fun_cfg.bounce_edges else "КРАЯ: ВЫКЛ")
        for w in self.spawned_widgets:
            w.fun_cfg.bounce_edges = self.fun_cfg.bounce_edges

    def open_extra_settings(self):
        dlg = ExtraSettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.btn_opacity_val.setText(f"ПРОЗР: {int(self.cfg_opacity * 100)}%")
            self.btn_speed_val.setText(f"{self.cfg_speed:g}x")

    def show_selective_remove_menu(self):
        if not self.spawned_widgets:
            QMessageBox.information(
                self,
                "На экране пусто",
                "Сейчас на рабочем столе нет добавленных гифок.",
            )
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #292C30;
                color: #D7D7D9;
                border: 1px solid #5E5E5E;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #3E434A;
            }
        """)

        title_act = QAction("Нажмите на гифку, чтобы убрать её:", menu)
        title_act.setEnabled(False)
        menu.addAction(title_act)
        menu.addSeparator()

        for w in list(self.spawned_widgets):
            act = QAction(w.thumbnail_icon(), f"Убрать {w.display_label()}", menu)
            act.triggered.connect(lambda checked=False, target=w: target.close())
            menu.addAction(act)

        menu.addSeparator()
        dlg_act = QAction("Открыть окно управления списком...", menu)
        dlg_act.triggered.connect(self.open_manage_gifs_dialog)
        menu.addAction(dlg_act)

        clear_act = QAction("Убрать вообще все с экрана", menu)
        clear_act.triggered.connect(self.clear_all_desktop_gifs)
        menu.addAction(clear_act)

        btn_pos = self.btn_manage_active.mapToGlobal(
            QPoint(0, self.btn_manage_active.height())
        )
        menu.exec(btn_pos)

    def open_manage_gifs_dialog(self):
        dlg = ManageActiveGifsDialog(self)
        dlg.exec()

    def load_gif_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите GIF или анимацию",
            "",
            "Анимации и изображения (*.gif *.webp *.png *.apng *.jpg *.jpeg);;Все файлы (*)",
        )
        if not path:
            return
        self.load_gif_from_path(path)

    def load_gif_from_path(self, path: str):
        try:
            frames, durations = extract_gif_frames(path)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка чтения файла", f"Не удалось загрузить файл:\n{e}")
            return

        self.current_file_name = os.path.splitext(os.path.basename(path))[0] or "GIF"
        self.raw_frames = frames
        self.raw_durations = list(durations)
        self.durations = list(durations)

        w0, h0 = frames[0].size
        self.aspect_ratio = w0 / float(max(1, h0))
        self.input_w.set_int(w0, emit_signal=False)
        self.input_h.set_int(h0, emit_signal=False)

        dlg = BackgroundChoiceDialog(
            self,
            self.raw_frames,
            initial_mode="keep",
            initial_color=self.bg_color,
            initial_tolerance=self.bg_tolerance,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.bg_removed_frames = dlg.result_frames
            self.bg_mode = dlg.selected_mode
            self.bg_color = dlg.target_color
            self.bg_tolerance = dlg.tolerance
        else:
            self.bg_removed_frames = [f.copy() for f in self.raw_frames]
            self.bg_mode = "keep"

        self.processed_frames = [f.copy() for f in self.bg_removed_frames]
        self._update_bg_status_label()
        self.lbl_upload.setVisible(False)
        self.preview_idx = 0
        self._render_preview_frame()
        self.preview_timer.start(self.durations[0])
        self.update()

    def _update_bg_status_label(self):
        names = {
            "keep": "ОРИГИНАЛ",
            "chromakey": "ХРОМАКЕЙ",
            "ai": "БЕЗ ФОНА (ИИ)",
        }
        self.btn_bg_status.setText(names.get(self.bg_mode, "ОРИГИНАЛ"))

    def edit_background_dialog(self):
        if not self.raw_frames:
            self.load_gif_dialog()
            return

        dlg = BackgroundChoiceDialog(
            self,
            self.raw_frames,
            initial_mode=self.bg_mode,
            initial_color=self.bg_color,
            initial_tolerance=self.bg_tolerance,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.bg_removed_frames = dlg.result_frames
            self.processed_frames = [f.copy() for f in self.bg_removed_frames]
            self.durations = list(self.raw_durations)
            self.bg_mode = dlg.selected_mode
            self.bg_color = dlg.target_color
            self.bg_tolerance = dlg.tolerance
            self._update_bg_status_label()
            self.preview_idx = 0
            self._render_preview_frame()

    def open_gif_editor_dialog(self):
        if not self.bg_removed_frames:
            self.load_gif_dialog()
            return

        dlg = GifEditorDialog(
            self,
            source_frames=self.bg_removed_frames,
            source_durations=self.raw_durations,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.edited_frames:
            self.processed_frames = dlg.edited_frames
            self.durations = dlg.edited_durations
            w0, h0 = self.processed_frames[0].size
            self.aspect_ratio = w0 / float(max(1, h0))
            self.input_w.set_int(w0, emit_signal=False)
            self.input_h.set_int(h0, emit_signal=False)
            self.preview_idx = 0
            self._render_preview_frame()

    def _tick_preview(self):
        if not self.processed_frames:
            self.preview_timer.stop()
            return
        self.preview_idx = (self.preview_idx + 1) % len(self.processed_frames)
        self._render_preview_frame()
        dur = int(self.durations[self.preview_idx] / self.cfg_speed)
        self.preview_timer.start(max(12, dur))

    def _render_preview_frame(self):
        if not self.processed_frames:
            self.preview_area.clear()
            return
        frame = self.processed_frames[self.preview_idx]
        if self.cfg_flip_x:
            frame = frame.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        pix = pil_to_qpixmap(frame).scaled(
            285, 285,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_area.setPixmap(pix)

    def reset_current_gif(self):
        self.preview_timer.stop()
        self.raw_frames.clear()
        self.raw_durations.clear()
        self.bg_removed_frames.clear()
        self.processed_frames.clear()
        self.durations.clear()
        self.preview_area.clear()
        self.lbl_upload.setVisible(True)
        self.bg_mode = "keep"
        self._update_bg_status_label()
        self.update()

    def spawn_gif_on_desktop(self):
        if not self.processed_frames:
            QMessageBox.information(
                self,
                "Сначала загрузите GIF",
                "Нажмите на область с плюсом или перетащите туда GIF-файл мышкой.",
            )
            return

        w = self.input_w.current_int()
        h = self.input_h.current_int()
        mode_str = DesktopGifWidget.MODES[self.mode_index]
        glide_val = self.glide_slider.value()

        widget = DesktopGifWidget(
            frames=[f.copy() for f in self.processed_frames],
            durations=list(self.durations),
            title_name=self.current_file_name,
            width=w,
            height=h,
            glide_level=glide_val,
            mode=mode_str,
            fun_cfg=self.fun_cfg.copy(),
            always_on_top=self.cfg_always_on_top,
            flip_x=self.cfg_flip_x,
            opacity=self.cfg_opacity,
            speed_mult=self.cfg_speed,
        )
        widget.closed_widget.connect(self._on_widget_closed)
        widget.changed_widget.connect(lambda _: self._update_active_counter())
        widget.show()
        self.spawned_widgets.append(widget)
        self._update_active_counter()

    def _on_widget_closed(self, w: object):
        if w in self.spawned_widgets:
            self.spawned_widgets.remove(w)
        self._update_active_counter()

    def clear_all_desktop_gifs(self):
        for w in list(self.spawned_widgets):
            w.close()
        self.spawned_widgets.clear()
        self._update_active_counter()

    def _update_active_counter(self):
        count = len(self.spawned_widgets)
        self.btn_manage_active.setText(f"{count} шт. (УБРАТЬ)")

    def closeEvent(self, event):
        self.world_physics_timer.stop()
        if getattr(self, "tray_icon", None):
            self.tray_icon.hide()
        self.clear_all_desktop_gifs()
        super().closeEvent(event)


def main():
    if "--install-shortcut" in sys.argv:
        app = QApplication(sys.argv)
        install_desktop_shortcut(None)
        return

    app = QApplication(sys.argv)
    app.setApplicationName("GIF Desktop Manager")
    app.setWindowIcon(create_app_icon())
    win = MainDesignerWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()