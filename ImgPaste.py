import logging
import sys
import numpy as np
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtWidgets import QStyle
from pynput import keyboard
from paddleocr import PaddleOCR
from PIL import ImageGrab, ImageDraw
from PyQt5.QtCore import QObject, QThread, pyqtSignal


# 初始化logger
def init_logger():
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s %(filename)s:%(lineno)d - %(message)s'
    )
    global logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
init_logger()

class HotkeyHandler(QObject):
    # 定义发送给主线程的信号
    paste_triggered = pyqtSignal()
    ocr_triggered = pyqtSignal()
    screenshot_triggered = pyqtSignal()  # 新增截图信号
    
    def __init__(self):
        super().__init__()
        self.listener = None
        self.setup_hotkeys()
    
    def setup_hotkeys(self):
        self.listener = keyboard.GlobalHotKeys({
            '<ctrl>+<alt>+z': self.on_paste_hotkey,
            '<ctrl>+<alt>+x': self.on_ocr_hotkey,
            '<ctrl>+<alt>+a': self.on_screenshot_hotkey  # 新增截图快捷键
        })
        self.listener.start()
    
    def on_paste_hotkey(self):
        logger.info("收到粘贴快捷键（子线程）")
        # 通过信号通知主线程
        self.paste_triggered.emit()
    
    def on_ocr_hotkey(self):
        logger.info("收到OCR快捷键（子线程）")
        # 通过信号通知主线程
        self.ocr_triggered.emit()
    
    def on_screenshot_hotkey(self):
        logger.info("收到截图快捷键（子线程）")
        # 通过信号通知主线程
        self.screenshot_triggered.emit()
    
    def stop(self):
        if self.listener:
            self.listener.stop()

class FloatingImageWindow(QtWidgets.QWidget):
    BORDER = 3  # 边框宽度
    def __init__(self, image, ocr_processor, parent=None):
        super().__init__(parent)
        self.ocr_processor = ocr_processor
        self.image = image
        self.scale = 1.0
        self.drag_pos = None
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        # 初始化窗口尺寸比图片多出边框
        self.resize(image.width() + self.BORDER * 2, image.height() + self.BORDER * 2)
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def paintEvent(self, event):
        logger.debug("FloatingImageWindow.paintEvent触发")
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        # Draw blue border
        rect = self.rect()
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 120, 255), self.BORDER))
        painter.drawRect(rect.adjusted(1, 1, -2, -2))
        # Draw image (居中显示)
        scaled_img = self.image.scaled(
            int(self.image.width() * self.scale),
            int(self.image.height() * self.scale),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )
        # 图片居中，且留出边框
        x = (self.width() - scaled_img.width()) // 2
        y = (self.height() - scaled_img.height()) // 2
        painter.drawPixmap(x, y, scaled_img)
        # Draw scale percent
        painter.setPen(QtGui.QColor(0, 120, 255))
        painter.setFont(QtGui.QFont("Arial", 10, QtGui.QFont.Bold))
        painter.drawText(10, 20, f"{int(self.scale*100)}%")
    def wheelEvent(self, event):
        logger.debug(f"FloatingImageWindow.wheelEvent: delta={event.angleDelta().y()}")
        delta = event.angleDelta().y()
        if delta > 0:
            self.scale = min(self.scale + 0.1, 5.0)
        else:
            self.scale = max(self.scale - 0.1, 0.2)
        # 缩放后窗口尺寸始终比图片多出边框
        new_w = int(self.image.width() * self.scale) + self.BORDER * 2
        new_h = int(self.image.height() * self.scale) + self.BORDER * 2
        self.resize(new_w, new_h)
        self.update()
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            self.setCursor(QtCore.Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag_pos and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPos() - self.drag_pos)

    def mouseReleaseEvent(self, event):
        logger.debug("FloatingImageWindow.mouseReleaseEvent")
        self.drag_pos = None
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        logger.info("FloatingImageWindow.mouseDoubleClickEvent，窗口关闭")
        self.close()

    def contextMenuEvent(self, event):
        logger.info("FloatingImageWindow.contextMenuEvent")
        menu = QtWidgets.QMenu(self)
        copy_action = menu.addAction("复制到剪切板")
        ocr_action = menu.addAction("OCR识别")
        save_action = menu.addAction("保存图片") 
        close_action = menu.addAction("关闭窗口")
        action = menu.exec_(event.globalPos())
        if action == copy_action:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setPixmap(self.image)
        elif action == save_action:
            self.save_image()  # 执行保存图片
        elif action == ocr_action:
            self.perform_ocr()  # 执行OCR识别
        elif action == close_action:
            self.close()
    def save_image(self):
        """保存图片功能"""
        try:
            # 打开文件保存对话框
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "保存图片",
                "screenshot.png",  # 默认文件名
                "Images (*.png *.jpg *.jpeg *.bmp *.tiff)"
            )
            
            if file_path:
                # 保存图片
                qimage = self.image.toImage()
                success = qimage.save(file_path)
                
                if success:
                    logger.info(f"图片已保存到: {file_path}")
                    # 显示保存成功的提示
                    QtWidgets.QMessageBox.information(self, "保存成功", f"图片已保存到:\n{file_path}")
                else:
                    logger.error(f"保存图片失败: {file_path}")
                    QtWidgets.QMessageBox.critical(self, "保存失败", f"无法保存图片到:\n{file_path}")
                    
        except Exception as e:
            logger.error(f"保存图片异常: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            QtWidgets.QMessageBox.critical(self, "保存错误", f"保存图片时发生错误:\n{str(e)}")

    def perform_ocr(self):
        """执行OCR识别，复用ScreenshotOCR的逻辑"""
        logger.info("开始贴图OCR识别")
        
        try:
            import tempfile
            import os
            from PIL import Image
            
            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                tmp_filename = tmp_file.name
            
            try:
                # 将QPixmap保存为临时文件
                qimage = self.image.toImage()
                qimage.save(tmp_filename, 'PNG')
                
                # 从临时文件加载PIL Image
                pil_image = Image.open(tmp_filename)
                
                # 确保图像是RGB模式
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                
                # 调用OCR处理器处理图像
                self.ocr_processor.image_ocr(pil_image)
                
            finally:
                # 清理临时文件
                if os.path.exists(tmp_filename):
                    os.unlink(tmp_filename)
            
        except Exception as e:
            logger.error(f"贴图OCR识别异常: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            QtWidgets.QMessageBox.critical(self, "OCR错误", str(e))
   

class TrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        menu = QtWidgets.QMenu(parent)
        exit_action = menu.addAction("退出")
        exit_action.triggered.connect(QtWidgets.qApp.quit)
        self.setContextMenu(menu)

class ImgPasteApp(QtWidgets.QApplication):
    def __init__(self, argv):
        logger.info("ImgPasteApp初始化")
        super().__init__(argv)
        self.windows = []
        self.tray = TrayIcon(QtGui.QIcon(), None)
        self.tray.setIcon(QtGui.QIcon(self.style().standardIcon(QStyle.SP_ComputerIcon)))
        self.tray.setVisible(True)
        self.tray.show()
        logger.info("系统托盘初始化完成")
        
        self.screenshot_ocr = ScreenshotOCR()
        logger.info("ScreenshotOCR初始化完成")
        
        # 创建并启动快捷键监听线程
        self.hotkey_thread = QThread()
        self.hotkey_handler = HotkeyHandler()
        self.hotkey_handler.moveToThread(self.hotkey_thread)
        
        # 连接信号到槽函数
        self.hotkey_handler.paste_triggered.connect(self.paste_clipboard_image)
        self.hotkey_handler.ocr_triggered.connect(self.screenshot_ocr.screenshot_and_ocr)
        self.hotkey_handler.screenshot_triggered.connect(self.take_screenshot)  # 连接截图信号
        
        self.hotkey_thread.start()
        logger.info("快捷键监听器启动")

    def quit(self):
        logger.info("应用退出，停止快捷键监听器")
        self.hotkey_handler.stop()
        self.hotkey_thread.quit()
        logger.info("等待快捷键监听线程结束...")
        self.hotkey_thread.wait()
        logger.info("快捷键监听线程已结束")
        super().quit()
   
    def take_screenshot(self):
        """公共截图功能"""
        logger.info("收到截图快捷键")
        try:
            # 使用ScreenshotOCR的截图功能
            rect = self.screenshot_ocr.get_rect()
            if rect is None:
                logger.warning("未选择截图区域")
                return

            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            logger.debug(f"截图区域大小: {width}x{height}")

            if width <= 0 or height <= 0:
                logger.error("截图区域无效")
                return

            # 执行截图
            img = ImageGrab.grab(bbox=rect)
            logger.debug(f"截图完成，图像大小: {img.size}")

            # 将截图转换为QPixmap并显示
            img_array = np.array(img)
            height, width = img_array.shape[:2]
            bytes_per_line = 3 * width
            qimage = QtGui.QImage(img_array.data, width, height, bytes_per_line, QtGui.QImage.Format_RGB888)
            pixmap = QtGui.QPixmap.fromImage(qimage)
            
            # 显示截图窗口
            win = FloatingImageWindow(pixmap, self.screenshot_ocr)
            win.show()
            self.windows.append(win)
            logger.info("截图窗口已显示")
            
        except Exception as e:
            logger.error(f"截图异常: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            QtWidgets.QMessageBox.critical(None, "截图错误", str(e))

    def paste_clipboard_image(self):
        try:
            logger.info("收到粘贴快捷键")
            clipboard = QtWidgets.QApplication.clipboard()
            if clipboard.mimeData().hasImage():
                logger.info("剪贴板有图片")
                image = clipboard.image()
                pixmap = QtGui.QPixmap.fromImage(image)
                logger.info("pixmap有图片")
                win = FloatingImageWindow(pixmap, self.screenshot_ocr)
                logger.info("win：%s", win)
                try:
                    win.show()
                    logger.info("win.show")
                except Exception as e:
                    logger.error(f"显示图片窗口异常: {e}")
                self.windows.append(win)
                logger.info("图片窗口已显示")
            else:
                logger.warning("剪贴板没有图片")
        except Exception as e:
            logger.error(f"贴图异常: {e}")
            QtWidgets.QMessageBox.critical(None, "贴图错误", str(e))

class ZoomableImageLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.scale_factor = 1.0
        self.original_pixmap = None
        
    def setPixmap(self, pixmap):
        self.original_pixmap = pixmap
        self.pixmap = pixmap
        self.scale_factor = 1.0
        super().setPixmap(pixmap)
        
    def wheelEvent(self, event):
        if self.original_pixmap is None:
            return
            
        # 获取滚轮滚动方向
        delta = event.angleDelta().y()
        
        # 根据滚动方向调整缩放因子
        if delta > 0:
            self.scale_factor *= 1.1  # 放大
        else:
            self.scale_factor /= 1.1  # 缩小
            
        # 限制缩放范围
        self.scale_factor = max(0.1, min(self.scale_factor, 10.0))
        
        # 应用缩放
        self.apply_scale()
        
    def apply_scale(self):
        if self.original_pixmap is None:
            return
            
        # 根据缩放因子调整图片大小，确保参数为整数
        scaled_pixmap = self.original_pixmap.scaled(
            int(self.original_pixmap.width() * self.scale_factor),
            int(self.original_pixmap.height() * self.scale_factor),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )
        
        super().setPixmap(scaled_pixmap)
        
        # 更新父控件（QScrollArea）的大小
        self.update_parent_size()
        
    def update_parent_size(self):
        """更新父控件（QScrollArea）的大小"""
        if isinstance(self.parent(), QtWidgets.QScrollArea):
            self.parent().adjustSize()
        
    def reset_scale(self):
        """重置缩放"""
        self.scale_factor = 1.0
        if self.original_pixmap is not None:
            super().setPixmap(self.original_pixmap)
            self.update_parent_size()

class OcrScreenshotDialog(QtWidgets.QDialog):
    def __init__(self, img, text, parent=None):
        logger.info("OcrScreenshotDialog初始化")
        super().__init__(parent)
        self.setWindowTitle("OCR识别结果")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
        self.resize(1000, 800)  # 调整窗口大小

        layout = QtWidgets.QHBoxLayout(self)  # 使用水平布局

        # 左边：显示图片
        self.image_label = ZoomableImageLabel(self)
        pixmap = QtGui.QPixmap.fromImage(img)
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        
        # 创建一个包含滚动区域的容器来显示图片
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setAlignment(QtCore.Qt.AlignCenter)
        self.scroll_area.setWidgetResizable(True)  # 允许自动调整大小
        layout.addWidget(self.scroll_area)

        # 右边：显示识别内容
        self.text_edit = QtWidgets.QTextEdit(self)
        self.text_edit.setFont(QtGui.QFont("Arial", 14))
        self.text_edit.setPlainText(text)
        layout.addWidget(self.text_edit)

        # 复制按钮
        btn_copy = QtWidgets.QPushButton("复制到剪切板", self)
        btn_copy.clicked.connect(self.copy_text)
        
        # 添加重置缩放按钮
        btn_reset = QtWidgets.QPushButton("重置缩放", self)
        btn_reset.clicked.connect(self.reset_image_scale)
        
        # 创建按钮布局
        button_layout = QtWidgets.QVBoxLayout()
        button_layout.addWidget(btn_copy)
        button_layout.addWidget(btn_reset)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)

    def copy_text(self):
        logger.info("复制OCR文本到剪切板")
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text_edit.toPlainText())
        
    def reset_image_scale(self):
        """重置图片缩放"""
        self.image_label.reset_scale()

class ScreenshotOCR(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        logger.debug("初始化PaddleOCR")
        logging.getLogger('PIL').setLevel(logging.CRITICAL)
        logging.getLogger('ppocr').setLevel(logging.CRITICAL)
        logging.getLogger('paddle').setLevel(logging.CRITICAL)
        logging.getLogger('paddlex').setLevel(logging.CRITICAL)
        self.ocr = PaddleOCR(use_textline_orientation=True, lang='ch', ocr_version='PP-OCRv5')
        logger.info("PaddleOCR初始化完成")

    def screenshot_and_ocr(self):
        logger.info("收到OCR快捷键")
        try:
            logger.info("开始截图OCR流程")
            rect = self.get_rect()
            logger.debug(f"截图区域: {rect}")
            if rect is None:
                logger.warning("未选择截图区域")
                return

            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            logger.debug(f"截图区域大小: {width}x{height}")

            if width <= 0 or height <= 0:
                logger.error("截图区域无效")
                return

            img = ImageGrab.grab(bbox=rect)
            logger.debug(f"截图完成，图像大小: {img.size}")

            # 复用图像OCR处理逻辑
            self.process_ocr(img)
        except Exception as e:
            logger.error(f"OCR流程异常: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            QtWidgets.QMessageBox.critical(None, "错误", str(e))

    def image_ocr(self, img):
        """处理传入的PIL图像进行OCR识别"""
        try:
            logger.info("开始图像OCR流程")
            logger.debug(f"图像大小: {img.size}")
            
            # 复用图像OCR处理逻辑
            self.process_ocr(img)
        except Exception as e:
            logger.error(f"图像OCR流程异常: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            QtWidgets.QMessageBox.critical(None, "错误", str(e))

    def process_ocr(self, img):
        """核心OCR处理逻辑"""
        # 将PIL.Image对象转换为numpy数组
        result = self.ocr.predict(np.array(img))
        
        # 解析OCR结果
        text_lines = []
        draw = ImageDraw.Draw(img)  # 创建绘图对象

        if len(result) > 0:
            # 收集所有文本和坐标信息
            texts = []
            polys = []
            
            for line in result:
                if line:
                    for i, text_line in enumerate(line['rec_texts']):
                        texts.append(text_line)
                        polys.append(line['rec_polys'][i])
            
            # 根据坐标进行排版
            formatted_text = self.format_text_by_position(texts, polys)
            text_lines = formatted_text.split('\n')
            
            # 在图片上绘制边界框
            for poly in polys:
                points = [(int(point[0]), int(point[1])) for point in poly]
                draw.polygon(points, outline="red")  # 绘制红色边界框

        text = "\n".join(text_lines) if text_lines else "未识别到文字"
        
        # 确保图像是RGB模式
        if img.mode != "RGB":
            img = img.convert("RGB")

        # 将PIL.Image对象转换为 QImage
        img_array = np.array(img)
        height, width = img_array.shape[:2]
        bytes_per_line = 3 * width
        qimage = QtGui.QImage(img_array.data, width, height, bytes_per_line, QtGui.QImage.Format_RGB888)

        dlg = OcrScreenshotDialog(qimage, text)
        dlg.exec_()

    def get_rect(self):
        """公共截图区域选择功能"""
        logger.info("弹出截图遮罩")
        class Mask(QtWidgets.QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                # 更全面的窗口标志设置
                self.setWindowFlags(
                    QtCore.Qt.FramelessWindowHint |
                    QtCore.Qt.WindowStaysOnTopHint |
                    QtCore.Qt.Tool |
                    QtCore.Qt.X11BypassWindowManagerHint
                )
                # 确保窗口在所有桌面元素之上
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
                
                # 获取主屏幕几何信息
                screen = QtWidgets.QApplication.primaryScreen()
                if screen:
                    self.setGeometry(screen.geometry())
                    self.screen_geometry = screen.geometry()
                else:
                    desktop = QtWidgets.QApplication.desktop()
                    self.setGeometry(desktop.screenGeometry())
                    self.screen_geometry = desktop.screenGeometry()
                    
                self.begin = self.end = None
                self.setCursor(QtCore.Qt.CrossCursor)
                # 设置为应用程序模态
                self.setModal(True)
                
                QtCore.QTimer.singleShot(200, self.show_and_raise)

            def show_and_raise(self):
                # 尝试多种显示方法
                self.show()
                self.showFullScreen()
                self.raise_()
                self.activateWindow()
                
                # 强制置顶
                self.setWindowState(QtCore.Qt.WindowFullScreen)
                
                # 多次刷新确保显示
                self.repaint()
                QtWidgets.QApplication.processEvents()
                
                # 再次确保置顶
                self.raise_()
                self.activateWindow()
                
                logger.debug(f"遮罩窗口已显示, 可见性: {self.isVisible()}, 活动: {self.isActiveWindow()}")
                logger.debug(f"窗口几何: {self.geometry()}, 屏幕几何: {self.screen_geometry}")

            def paintEvent(self, event):
                # 始终绘制背景
                qp = QtGui.QPainter(self)
                qp.setPen(QtCore.Qt.NoPen)
                qp.setBrush(QtGui.QColor(0, 0, 0, 100))  # 半透明黑色背景
                qp.drawRect(self.rect())
                
                # 绘制选区
                if self.begin and self.end:
                    qp.setPen(QtGui.QPen(QtGui.QColor(0, 120, 255), 2))
                    qp.setBrush(QtGui.QColor(0, 0, 0, 80))
                    r = QtCore.QRect(self.begin, self.end).normalized()
                    qp.drawRect(r)
                    # 绘制选区大小信息
                    qp.setPen(QtGui.QColor(255, 255, 255))
                    qp.setFont(QtGui.QFont("Arial", 10))
                    size_text = f"{r.width()} x {r.height()}"
                    qp.drawText(r.topLeft() + QtCore.QPoint(10, 20), size_text)

            def mousePressEvent(self, event):
                logger.debug(f"鼠标按下: {event.pos()}")
                self.begin = event.pos()
                self.end = self.begin
                self.update()

            def mouseMoveEvent(self, event):
                self.end = event.pos()
                self.update()

            def mouseReleaseEvent(self, event):
                logger.debug(f"鼠标释放: {event.pos()}")
                self.end = event.pos()
                self.update()
                self.accept()

        # 创建并显示遮罩
        mask = Mask()
        logger.debug("即将执行 Mask.exec_()")
        
        # 在执行exec_前添加额外的处理
        result = mask.exec_()
        
        logger.debug(f"Mask.exec_() 执行完毕, 结果: {result}")
        if result == QtWidgets.QDialog.Accepted and mask.begin and mask.end:
            # 转换为屏幕坐标
            x1, y1 = mask.begin.x(), mask.begin.y()
            x2, y2 = mask.end.x(), mask.end.y()
            left, top = min(x1, x2), min(y1, y2)
            right, bottom = max(x1, x2), max(y1, y2)
            
            # 确保坐标在屏幕范围内
            left = max(left, mask.screen_geometry.left())
            top = max(top, mask.screen_geometry.top())
            right = min(right, mask.screen_geometry.right())
            bottom = min(bottom, mask.screen_geometry.bottom())
            
            logger.info(f"选区坐标: {(left, top, right, bottom)}")
            return (left, top, right, bottom)
        logger.warning("遮罩窗口未正常关闭或未选择区域")
        return None

    def format_text_by_position(self, texts, polys, line_threshold=10):
        """
        根据文本框的垂直位置对文本进行排版
        
        :param texts: 文本列表
        :param polys: 对应的坐标列表
        :param line_threshold: 判断是否为同一行的垂直距离阈值
        :return: 排版后的文本
        """
        if not texts or not polys or len(texts) != len(polys):
            return "\n".join(texts)
        
        # 创建文本和坐标的配对列表
        text_positions = []
        for i, (text, poly) in enumerate(zip(texts, polys)):
            # 计算文本框的中心点Y坐标
            y_coords = [point[1] for point in poly]
            center_y = sum(y_coords) / len(y_coords)
            
            # 计算文本框的X坐标（用于排序同一行内的文本）
            x_coords = [point[0] for point in poly]
            min_x = min(x_coords)
            
            text_positions.append({
                'text': text,
                'center_y': center_y,
                'min_x': min_x,
                'index': i
            })
        
        # 根据Y坐标排序
        text_positions.sort(key=lambda x: x['center_y'])
        
        # 分组同一行的文本
        lines = []
        current_line = []
        last_y = None
        
        for item in text_positions:
            if last_y is None or abs(item['center_y'] - last_y) <= line_threshold:
                # 同一行
                current_line.append(item)
            else:
                # 新的一行
                if current_line:
                    # 对当前行内的文本按X坐标排序
                    current_line.sort(key=lambda x: x['min_x'])
                    lines.append(current_line)
                current_line = [item]
            last_y = item['center_y']
        
        # 处理最后一行
        if current_line:
            current_line.sort(key=lambda x: x['min_x'])
            lines.append(current_line)
        
        # 构建最终文本
        result_lines = []
        for line in lines:
            line_text = ''.join([item['text'] for item in line])
            result_lines.append(line_text)
        
        return '\n'.join(result_lines)
    
def main():
    app = ImgPasteApp(sys.argv)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()