# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import math
import objc
import os
import traceback

from GlyphsApp import Glyphs, GSBackgroundImage
from GlyphsApp.plugins import SelectTool

from AppKit import (
    NSAffineTransform,
    NSAlert,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSCursor,
    NSFont,
    NSGraphicsContext,
    NSImage,
    NSPanel,
    NSRectFill,
    NSSlider,
    NSTextField,
    NSView,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskUtilityWindow,
)
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

try:
    from AppKit import NSBitmapImageFileTypePNG
except Exception:
    # Older AppKit name.
    from AppKit import NSPNGFileType as NSBitmapImageFileTypePNG

try:
    from AppKit import NSCompositingOperationClear
except Exception:
    from AppKit import NSCompositeClear as NSCompositingOperationClear

try:
    from AppKit import NSCompositingOperationSourceOver
except Exception:
    from AppKit import NSCompositeSourceOver as NSCompositingOperationSourceOver

try:
    from AppKit import NSDeviceRGBColorSpace
except Exception:
    from AppKit import NSCalibratedRGBColorSpace as NSDeviceRGBColorSpace

try:
    from AppKit import NSImageInterpolationNone
except Exception:
    NSImageInterpolationNone = None

try:
    from AppKit import NSRectFillUsingOperation
except Exception:
    NSRectFillUsingOperation = None

try:
    from AppKit import NSFloatingWindowLevel
except Exception:
    NSFloatingWindowLevel = 3

try:
    from AppKit import NSEventModifierFlagOption
except Exception:
    NSEventModifierFlagOption = 1 << 19

try:
    from AppKit import NSAlternateKeyMask
except Exception:
    NSAlternateKeyMask = NSEventModifierFlagOption

try:
    from AppKit import NSEventModifierFlagCommand
except Exception:
    NSEventModifierFlagCommand = 1 << 20

try:
    from AppKit import NSCommandKeyMask
except Exception:
    NSCommandKeyMask = NSEventModifierFlagCommand


class BitmapBrushPreviewView(NSView):
    """Small raster preview used by the floating brush palette."""

    def drawRect_(self, rect):
        try:
            bounds = self.bounds()

            frame = NSMakeRect(
                bounds.origin.x + 1,
                bounds.origin.y + 1,
                max(0, bounds.size.width - 2),
                max(0, bounds.size.height - 2),
            )
            try:
                background = NSColor.controlBackgroundColor()
            except Exception:
                background = NSColor.colorWithCalibratedWhite_alpha_(0.96, 1.0)
            background.setFill()
            NSRectFill(frame)

            try:
                borderColor = NSColor.separatorColor()
            except Exception:
                borderColor = NSColor.colorWithCalibratedWhite_alpha_(0.72, 1.0)
            border = NSBezierPath.bezierPathWithRect_(frame)
            border.setLineWidth_(1.0)
            borderColor.setStroke()
            border.stroke()

            owner = BitmapBrush._activePaletteOwner
            if owner is None:
                return

            spans = getattr(owner, "brushSpans", None) or []
            brushBounds = getattr(owner, "brushBoundsOffsets", None)
            if not spans or brushBounds is None:
                return

            left, bottom, right, top = brushBounds
            brushWidth = max(1.0, float(right - left))
            brushHeight = max(1.0, float(top - bottom))
            availableWidth = max(1.0, float(bounds.size.width) - 28.0)
            availableHeight = max(1.0, float(bounds.size.height) - 24.0)
            scale = min(availableWidth / brushWidth, availableHeight / brushHeight, 10.0)

            originX = (
                float(bounds.origin.x)
                + (float(bounds.size.width) - brushWidth * scale) * 0.5
                - float(left) * scale
            )
            originY = (
                float(bounds.origin.y)
                + (float(bounds.size.height) - brushHeight * scale) * 0.5
                - float(bottom) * scale
            )

            try:
                ownerGray = max(0.0, min(1.0, float(owner.brushGray) / 255.0))
            except Exception:
                ownerGray = 0.5
            ink = NSColor.colorWithDeviceRed_green_blue_alpha_(ownerGray, ownerGray, ownerGray, 1.0)
            ink.setFill()
            for yOffset, xLeftOffset, xRightOffset in spans:
                NSRectFill(
                    NSMakeRect(
                        originX + float(xLeftOffset) * scale,
                        originY + float(yOffset) * scale,
                        float(xRightOffset - xLeftOffset + 1) * scale,
                        scale,
                    )
                )
        except Exception:
            print(traceback.format_exc())


class BitmapBrush(SelectTool):
    """Paint a 1-pixel-per-font-unit bitmap directly in Glyphs Edit View."""

    BITMAP_FOLDER = "bitmaps"
    BITMAP_ALPHA = 100

    DEFAULT_ANGLE = 0.0
    DEFAULT_ROUNDNESS = 100.0
    DEFAULT_SIZE = 10
    DEFAULT_GRAY = 128
    MIN_ANGLE = -180.0
    MAX_ANGLE = 180.0
    MIN_ROUNDNESS = 1.0
    MAX_ROUNDNESS = 100.0
    MIN_SIZE = 1
    MAX_SIZE = 200
    MIN_GRAY = 0
    MAX_GRAY = 255

    DEFAULT_KEY_ANGLE = "com.ruzvaliakhmetov.BitmapBrush.angle"
    DEFAULT_KEY_ROUNDNESS = "com.ruzvaliakhmetov.BitmapBrush.roundness"
    DEFAULT_KEY_SIZE = "com.ruzvaliakhmetov.BitmapBrush.size"
    DEFAULT_KEY_GRAY = "com.ruzvaliakhmetov.BitmapBrush.gray"

    windowAutosaveName = "com.ruzvaliakhmetov.BitmapBrush.palette.window"

    # Glyphs may instantiate a Python tool more than once. Keep one shared
    # floating palette and retarget it to whichever tool instance is active.
    _sharedWindow = None
    _sharedPreviewView = None
    _sharedAngleSlider = None
    _sharedRoundnessSlider = None
    _sharedSizeSlider = None
    _sharedGraySlider = None
    _sharedAngleField = None
    _sharedRoundnessField = None
    _sharedSizeField = None
    _sharedGrayField = None
    _activePaletteOwner = None

    @objc.python_method
    def settings(self):
        self.name = Glyphs.localize({"en": "Bitmap Brush"})

        resourcesPath = os.path.dirname(self.__file__())
        iconPath = os.path.join(resourcesPath, "toolbarIconTemplate.png")
        self._icon = NSImage.alloc().initByReferencingFile_(iconPath)
        try:
            self._icon.setTemplate_(True)
        except Exception:
            pass
        self.tool_bar_image = self._icon

        self.bitmapBrushCursor = self.makeBitmapBrushCursor()
        self.optionKeyDown = False
        self.commandKeyDown = False
        self.temporarySelectMode = False
        self.toolActive = False

        self.painting = False
        self.strokeErasing = False
        self.paintingLayer = None
        self.paintingGlyph = None
        self.paintingFont = None
        self.bitmapPath = None
        self.lastBrushCenter = None
        self.strokeRows = {}
        self.strokeBounds = None
        self.lastLayer = None

        self.cursorLocation = None
        self.cursorLayer = None

        self.window = None
        self.previewView = None
        self.angleSlider = None
        self.roundnessSlider = None
        self.sizeSlider = None
        self.graySlider = None
        self.angleField = None
        self.roundnessField = None
        self.sizeField = None
        self.grayField = None

        try:
            Glyphs.registerDefault(self.DEFAULT_KEY_ANGLE, self.DEFAULT_ANGLE)
            Glyphs.registerDefault(self.DEFAULT_KEY_ROUNDNESS, self.DEFAULT_ROUNDNESS)
            Glyphs.registerDefault(self.DEFAULT_KEY_SIZE, self.DEFAULT_SIZE)
            Glyphs.registerDefault(self.DEFAULT_KEY_GRAY, self.DEFAULT_GRAY)
        except Exception:
            pass

        self.brushAngle = self.readPreferenceFloat(
            self.DEFAULT_KEY_ANGLE, self.DEFAULT_ANGLE, self.MIN_ANGLE, self.MAX_ANGLE
        )
        self.brushRoundness = self.readPreferenceFloat(
            self.DEFAULT_KEY_ROUNDNESS,
            self.DEFAULT_ROUNDNESS,
            self.MIN_ROUNDNESS,
            self.MAX_ROUNDNESS,
        )
        self.brushSize = int(
            round(
                self.readPreferenceFloat(
                    self.DEFAULT_KEY_SIZE,
                    self.DEFAULT_SIZE,
                    self.MIN_SIZE,
                    self.MAX_SIZE,
                )
            )
        )
        self.brushGray = int(
            round(
                self.readPreferenceFloat(
                    self.DEFAULT_KEY_GRAY,
                    self.DEFAULT_GRAY,
                    self.MIN_GRAY,
                    self.MAX_GRAY,
                )
            )
        )

        # All expensive ellipse/rotation work is done here, never in the
        # mouse-drag hot path.
        self.brushSpans = []
        self.brushPixels = set()
        self.brushBoundsOffsets = (0, 0, 1, 1)
        self.brushOutlinePath = None
        self.rebuildBrushGeometry()

    @objc.python_method
    def activate(self):
        self.toolActive = True
        self.optionKeyDown = False
        self.commandKeyDown = False
        self.temporarySelectMode = False
        BitmapBrush._activePaletteOwner = self

        try:
            self.adoptSharedPalette()
            if self.window is None:
                self.buildPalette()
            else:
                self.retargetPaletteControls()
            self.syncPaletteControls()
            if self.window is not None:
                self.window.orderFrontRegardless()
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()

        self.forceBitmapBrushCursor()
        Glyphs.redraw()

    @objc.python_method
    def deactivate(self):
        try:
            if self.painting:
                self.finishStroke(commit=True)
        finally:
            self.toolActive = False
            self.optionKeyDown = False
            self.commandKeyDown = False
            self.temporarySelectMode = False
            self.cursorLocation = None
            self.cursorLayer = None
            if BitmapBrush._activePaletteOwner is self:
                BitmapBrush._activePaletteOwner = None
            try:
                if self.window is not None:
                    self.window.orderOut_(None)
            except Exception:
                pass
            try:
                NSCursor.arrowCursor().set()
            except Exception:
                pass
            try:
                Glyphs.redraw()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cursor and temporary Selection Tool pass-through
    # ------------------------------------------------------------------

    @objc.python_method
    def makeBitmapBrushCursor(self):
        try:
            return NSCursor.crosshairCursor()
        except Exception:
            return None

    def standardCursor(self):
        if self.isSelectModifierDown() or self.temporarySelectMode:
            try:
                return NSCursor.arrowCursor()
            except Exception:
                return None
        if self.bitmapBrushCursor is not None:
            return self.bitmapBrushCursor
        try:
            return NSCursor.crosshairCursor()
        except Exception:
            return None

    @objc.python_method
    def cursor(self):
        return self.standardCursor()

    @objc.python_method
    def isOptionKeyPressed(self, event):
        try:
            flags = int(event.modifierFlags())
            mask = int(NSEventModifierFlagOption) | int(NSAlternateKeyMask)
            return bool(flags & mask)
        except Exception:
            return False

    @objc.python_method
    def isCommandKeyPressed(self, event):
        try:
            flags = int(event.modifierFlags())
            mask = int(NSEventModifierFlagCommand) | int(NSCommandKeyMask)
            return bool(flags & mask)
        except Exception:
            return False

    @objc.python_method
    def updateModifierState(self, event):
        self.optionKeyDown = self.isOptionKeyPressed(event)
        self.commandKeyDown = self.isCommandKeyPressed(event)
        return self.isSelectModifierDown()

    @objc.python_method
    def isSelectModifierDown(self):
        # Alt/Option is reserved for the eraser. Command keeps the temporary
        # Selection Tool pass-through from earlier versions.
        return bool(self.commandKeyDown)

    @objc.python_method
    def forceBitmapBrushCursor(self, event=None):
        try:
            if event is not None:
                self.updateModifierState(event)
            cursor = self.standardCursor()
            if cursor is not None:
                cursor.set()
        except Exception:
            pass

    @objc.python_method
    def clearCursorPreview(self):
        self.cursorLocation = None
        self.cursorLayer = None

    @objc.python_method
    def updateCursorLocation(self, event, redraw=True):
        try:
            graphicView = self.editViewController().graphicView()
            point = graphicView.getActiveLocation_(event)
            layer = graphicView.activeLayer()
        except Exception:
            self.clearCursorPreview()
            return

        if point is None or layer is None:
            self.clearCursorPreview()
            return

        location = NSMakePoint(
            float(int(round(float(point.x)))),
            float(int(round(float(point.y)))),
        )

        changed = True
        if self.cursorLocation is not None and self.cursorLayer is layer:
            try:
                changed = (
                    float(self.cursorLocation.x) != float(location.x)
                    or float(self.cursorLocation.y) != float(location.y)
                )
            except Exception:
                changed = True

        self.cursorLocation = location
        self.cursorLayer = layer
        if redraw and changed:
            try:
                Glyphs.redraw()
            except Exception:
                pass

    @objc.python_method
    def drawBrushCursorPreview(self, layer):
        if (
            not self.toolActive
            or self.isSelectModifierDown()
            or self.temporarySelectMode
            or self.cursorLocation is None
            or self.cursorLayer is not layer
            or self.brushOutlinePath is None
        ):
            return

        path = self.brushOutlinePath.copy()
        transform = NSAffineTransform.transform()
        transform.translateXBy_yBy_(
            float(self.cursorLocation.x),
            float(self.cursorLocation.y),
        )
        path.transformUsingAffineTransform_(transform)

        try:
            scale = float(self.getScale())
            if scale <= 0:
                scale = 1.0
        except Exception:
            scale = 1.0

        # Two-pass outline stays visible over both dark glyphs and a light
        # canvas while preserving the raster footprint exactly.
        try:
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.90).setStroke()
            path.setLineWidth_(2.0 / scale)
            path.stroke()
        except Exception:
            pass

        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.92).setStroke()
        path.setLineWidth_(1.0 / scale)
        path.stroke()

    @objc.python_method
    def forwardEventToSelectTool(self, selectorName, event):
        try:
            selector = getattr(super(BitmapBrush, self), selectorName)
            return selector(event)
        except AttributeError:
            pass
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()
            return None

        try:
            selector = getattr(SelectTool, selectorName)
        except Exception:
            selector = None
        if selector is not None:
            try:
                return selector(self, event)
            except Exception:
                print(traceback.format_exc())
                Glyphs.showMacroWindow()
        return None

    def flagsChanged_(self, event):
        try:
            wasSelect = self.isSelectModifierDown()
            wasOption = bool(self.optionKeyDown)
            isSelect = self.updateModifierState(event)
            optionChanged = wasOption != bool(self.optionKeyDown)
            if wasSelect != isSelect or optionChanged:
                if isSelect:
                    self.clearCursorPreview()
                self.forceBitmapBrushCursor()
                Glyphs.redraw()
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()

    # ------------------------------------------------------------------
    # Mouse handling: the hot path stays entirely in memory.
    # ------------------------------------------------------------------

    def mouseMoved_(self, event):
        wasSelect = self.isSelectModifierDown()
        selectModifierDown = self.updateModifierState(event)
        if selectModifierDown:
            if not wasSelect:
                self.clearCursorPreview()
                self.forceBitmapBrushCursor()
                Glyphs.redraw()
            return self.forwardEventToSelectTool("mouseMoved_", event)

        self.forceBitmapBrushCursor()
        self.updateCursorLocation(event)

    def mouseDown_(self, event):
        try:
            selectModifierDown = self.updateModifierState(event)
            if selectModifierDown:
                if self.painting:
                    self.finishStroke(commit=True)
                self.temporarySelectMode = True
                self.clearCursorPreview()
                self.forceBitmapBrushCursor()
                return self.forwardEventToSelectTool("mouseDown_", event)

            self.temporarySelectMode = False
            self.forceBitmapBrushCursor()
            self.updateCursorLocation(event, redraw=False)
            self.startStroke(event)
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()

    def mouseDragged_(self, event):
        # Selection-tool pass-through stays intentionally tiny: no palette work,
        # no brush rebuilding, and no bitmap I/O in this hot path.
        if self.temporarySelectMode:
            return self.forwardEventToSelectTool("mouseDragged_", event)

        try:
            selectModifierDown = self.updateModifierState(event)
            if self.painting:
                return self.paintAtEvent(event)
            if selectModifierDown:
                self.clearCursorPreview()
                return self.forwardEventToSelectTool("mouseDragged_", event)
            self.updateCursorLocation(event)
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()

    def mouseUp_(self, event):
        try:
            if self.temporarySelectMode:
                try:
                    return self.forwardEventToSelectTool("mouseUp_", event)
                finally:
                    self.temporarySelectMode = False
                    selectModifierDown = self.updateModifierState(event)
                    if selectModifierDown:
                        self.clearCursorPreview()
                    else:
                        self.updateCursorLocation(event, redraw=False)
                    self.forceBitmapBrushCursor()
                    Glyphs.redraw()

            self.updateModifierState(event)
            if self.painting:
                self.paintAtEvent(event)
                self.finishStroke(commit=True)
                self.updateCursorLocation(event, redraw=False)
                Glyphs.redraw()
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()

    # ------------------------------------------------------------------
    # Brush palette
    # ------------------------------------------------------------------

    @objc.python_method
    def readPreferenceFloat(self, key, fallback, minimum, maximum):
        value = fallback
        try:
            stored = Glyphs.defaults[key]
            if stored is not None:
                value = float(stored)
        except Exception:
            value = fallback
        return max(float(minimum), min(float(maximum), float(value)))

    @objc.python_method
    def saveBrushPreferences(self):
        try:
            Glyphs.defaults[self.DEFAULT_KEY_ANGLE] = float(self.brushAngle)
            Glyphs.defaults[self.DEFAULT_KEY_ROUNDNESS] = float(self.brushRoundness)
            Glyphs.defaults[self.DEFAULT_KEY_SIZE] = int(self.brushSize)
            Glyphs.defaults[self.DEFAULT_KEY_GRAY] = int(self.brushGray)
        except Exception:
            pass

    @objc.python_method
    def setBrushParameters(self, angle=None, roundness=None, size=None, gray=None):
        newAngle = self.brushAngle if angle is None else float(angle)
        newRoundness = self.brushRoundness if roundness is None else float(roundness)
        newSize = self.brushSize if size is None else int(round(float(size)))
        newGray = self.brushGray if gray is None else int(round(float(gray)))

        newAngle = round(max(self.MIN_ANGLE, min(self.MAX_ANGLE, newAngle)))
        newRoundness = round(
            max(self.MIN_ROUNDNESS, min(self.MAX_ROUNDNESS, newRoundness))
        )
        newSize = max(self.MIN_SIZE, min(self.MAX_SIZE, newSize))
        newGray = max(self.MIN_GRAY, min(self.MAX_GRAY, newGray))

        geometryChanged = (
            float(newAngle) != float(self.brushAngle)
            or float(newRoundness) != float(self.brushRoundness)
            or int(newSize) != int(self.brushSize)
        )
        changed = geometryChanged or int(newGray) != int(self.brushGray)

        self.brushAngle = float(newAngle)
        self.brushRoundness = float(newRoundness)
        self.brushSize = int(newSize)
        self.brushGray = int(newGray)

        if geometryChanged:
            self.rebuildBrushGeometry()
        if changed:
            self.saveBrushPreferences()

        self.syncPaletteControls()
        try:
            if self.previewView is not None:
                self.previewView.setNeedsDisplay_(True)
        except Exception:
            pass
        if changed:
            try:
                Glyphs.redraw()
            except Exception:
                pass

    @objc.python_method
    def adoptSharedPalette(self):
        self.window = BitmapBrush._sharedWindow
        self.previewView = BitmapBrush._sharedPreviewView
        self.angleSlider = BitmapBrush._sharedAngleSlider
        self.roundnessSlider = BitmapBrush._sharedRoundnessSlider
        self.sizeSlider = BitmapBrush._sharedSizeSlider
        self.graySlider = BitmapBrush._sharedGraySlider
        self.angleField = BitmapBrush._sharedAngleField
        self.roundnessField = BitmapBrush._sharedRoundnessField
        self.sizeField = BitmapBrush._sharedSizeField
        self.grayField = BitmapBrush._sharedGrayField
        self.retargetPaletteControls()

    @objc.python_method
    def storeSharedPalette(self):
        BitmapBrush._sharedWindow = self.window
        BitmapBrush._sharedPreviewView = self.previewView
        BitmapBrush._sharedAngleSlider = self.angleSlider
        BitmapBrush._sharedRoundnessSlider = self.roundnessSlider
        BitmapBrush._sharedSizeSlider = self.sizeSlider
        BitmapBrush._sharedGraySlider = self.graySlider
        BitmapBrush._sharedAngleField = self.angleField
        BitmapBrush._sharedRoundnessField = self.roundnessField
        BitmapBrush._sharedSizeField = self.sizeField
        BitmapBrush._sharedGrayField = self.grayField

    @objc.python_method
    def clearSharedPalette(self):
        if BitmapBrush._sharedWindow is self.window:
            BitmapBrush._sharedWindow = None
            BitmapBrush._sharedPreviewView = None
            BitmapBrush._sharedAngleSlider = None
            BitmapBrush._sharedRoundnessSlider = None
            BitmapBrush._sharedSizeSlider = None
            BitmapBrush._sharedGraySlider = None
            BitmapBrush._sharedAngleField = None
            BitmapBrush._sharedRoundnessField = None
            BitmapBrush._sharedSizeField = None
            BitmapBrush._sharedGrayField = None

        self.window = None
        self.previewView = None
        self.angleSlider = None
        self.roundnessSlider = None
        self.sizeSlider = None
        self.graySlider = None
        self.angleField = None
        self.roundnessField = None
        self.sizeField = None
        self.grayField = None

    @objc.python_method
    def retargetPaletteControls(self):
        try:
            if self.window is not None:
                self.window.setDelegate_(self)
        except Exception:
            pass

        controlActions = (
            (self.angleSlider, "angleSlider:"),
            (self.roundnessSlider, "roundnessSlider:"),
            (self.sizeSlider, "sizeSlider:"),
            (self.graySlider, "graySlider:"),
            (self.angleField, "angleField:"),
            (self.roundnessField, "roundnessField:"),
            (self.sizeField, "sizeField:"),
            (self.grayField, "grayField:"),
        )
        for control, action in controlActions:
            if control is None:
                continue
            try:
                control.setTarget_(self)
                control.setAction_(action)
            except Exception:
                pass

        try:
            if self.previewView is not None:
                self.previewView.setNeedsDisplay_(True)
        except Exception:
            pass

    @objc.python_method
    def buildPalette(self):
        mask = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskUtilityWindow
        )
        width = 310
        height = 352
        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(360, 360, width, height),
            mask,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Bitmap Brush")
        self.window.setFloatingPanel_(True)
        self.window.setHidesOnDeactivate_(True)
        try:
            self.window.setLevel_(NSFloatingWindowLevel)
        except Exception:
            pass
        try:
            self.window.setBecomesKeyOnlyIfNeeded_(True)
        except Exception:
            pass
        try:
            self.window.setWorksWhenModal_(True)
        except Exception:
            pass
        try:
            self.window.setFrameAutosaveName_(self.windowAutosaveName)
        except Exception:
            pass
        try:
            self.window.setMinSize_(NSMakeSize(width, height))
            self.window.setMaxSize_(NSMakeSize(width, height))
        except Exception:
            pass
        self.window.setDelegate_(self)

        content = self.window.contentView()

        self.previewView = BitmapBrushPreviewView.alloc().initWithFrame_(
            NSMakeRect(95, 194, 120, 112)
        )
        content.addSubview_(self.previewView)

        self.addPaletteRow(
            content,
            "Angle:",
            150,
            self.MIN_ANGLE,
            self.MAX_ANGLE,
            float(self.brushAngle),
            "angle",
        )
        self.addPaletteRow(
            content,
            "Roundness:",
            108,
            self.MIN_ROUNDNESS,
            self.MAX_ROUNDNESS,
            float(self.brushRoundness),
            "roundness",
        )
        self.addPaletteRow(
            content,
            "Size:",
            66,
            self.MIN_SIZE,
            self.MAX_SIZE,
            float(self.brushSize),
            "size",
        )
        self.addPaletteRow(
            content,
            "Gray:",
            24,
            self.MIN_GRAY,
            self.MAX_GRAY,
            float(self.brushGray),
            "gray",
        )

        self.storeSharedPalette()
        self.retargetPaletteControls()
        self.syncPaletteControls()

    @objc.python_method
    def addPaletteRow(self, content, title, y, minimum, maximum, value, kind):
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(18, y + 3, 82, 22))
        label.setStringValue_(title)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(NSFont.systemFontOfSize_(13))
        content.addSubview_(label)

        slider = NSSlider.alloc().initWithFrame_(NSMakeRect(100, y, 126, 24))
        slider.setMinValue_(float(minimum))
        slider.setMaxValue_(float(maximum))
        slider.setDoubleValue_(float(value))
        slider.setContinuous_(True)
        content.addSubview_(slider)

        field = NSTextField.alloc().initWithFrame_(NSMakeRect(232, y - 1, 62, 25))
        field.setFont_(NSFont.systemFontOfSize_(13))
        content.addSubview_(field)

        if kind == "angle":
            self.angleSlider = slider
            self.angleField = field
        elif kind == "roundness":
            self.roundnessSlider = slider
            self.roundnessField = field
        elif kind == "size":
            self.sizeSlider = slider
            self.sizeField = field
        else:
            self.graySlider = slider
            self.grayField = field

    @objc.python_method
    def syncPaletteControls(self):
        try:
            if self.angleSlider is not None:
                self.angleSlider.setDoubleValue_(float(self.brushAngle))
            if self.roundnessSlider is not None:
                self.roundnessSlider.setDoubleValue_(float(self.brushRoundness))
            if self.sizeSlider is not None:
                self.sizeSlider.setDoubleValue_(float(self.brushSize))
            if self.graySlider is not None:
                self.graySlider.setDoubleValue_(float(self.brushGray))

            if self.angleField is not None:
                self.angleField.setStringValue_("%d°" % int(round(self.brushAngle)))
            if self.roundnessField is not None:
                self.roundnessField.setStringValue_(
                    "%d%%" % int(round(self.brushRoundness))
                )
            if self.sizeField is not None:
                self.sizeField.setStringValue_("%d px" % int(self.brushSize))
            if self.grayField is not None:
                self.grayField.setStringValue_("%d" % int(self.brushGray))
        except Exception:
            pass

    @objc.python_method
    def numberFromField(self, sender, fallback):
        try:
            value = str(sender.stringValue()).strip().lower()
            value = value.replace("px", "").replace("°", "").replace("%", "")
            value = value.replace(",", ".").strip()
            return float(value)
        except Exception:
            return float(fallback)

    def angleSlider_(self, sender):
        self.setBrushParameters(angle=sender.doubleValue())

    def roundnessSlider_(self, sender):
        self.setBrushParameters(roundness=sender.doubleValue())

    def sizeSlider_(self, sender):
        self.setBrushParameters(size=sender.doubleValue())

    def graySlider_(self, sender):
        self.setBrushParameters(gray=sender.doubleValue())

    def angleField_(self, sender):
        self.setBrushParameters(
            angle=self.numberFromField(sender, self.brushAngle)
        )
        self.refocusEditView()

    def roundnessField_(self, sender):
        self.setBrushParameters(
            roundness=self.numberFromField(sender, self.brushRoundness)
        )
        self.refocusEditView()

    def sizeField_(self, sender):
        self.setBrushParameters(
            size=self.numberFromField(sender, self.brushSize)
        )
        self.refocusEditView()

    def grayField_(self, sender):
        self.setBrushParameters(
            gray=self.numberFromField(sender, self.brushGray)
        )
        self.refocusEditView()

    def windowWillClose_(self, notification):
        try:
            self.clearSharedPalette()
        except Exception:
            pass

    @objc.python_method
    def refocusEditView(self):
        try:
            graphicView = self.editViewController().graphicView()
            document = Glyphs.currentDocument
            if callable(document):
                document = document()
            if document is None:
                return
            controller = document.windowController()
            if controller is None:
                return
            window = controller.window()
            if window is None:
                return
            try:
                window.makeKeyWindow()
            except Exception:
                pass
            try:
                window.makeFirstResponder_(graphicView)
            except Exception:
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Stroke model
    # ------------------------------------------------------------------

    @objc.python_method
    def startStroke(self, event):
        font = Glyphs.font
        layer = self.activeLayer()
        if font is None or layer is None:
            Glyphs.showNotification("Bitmap Brush", "Open a font and select a glyph layer first.")
            return

        fontPath = self.fontFilePath(font)
        if not fontPath:
            self.showAlert(
                "Bitmap Brush",
                "Save the Glyphs file first. Bitmap Brush stores PNG files in a 'bitmaps' folder next to the .glyphs document, so it cannot paint until the document has been saved.",
            )
            return

        glyph = layer.parent
        if glyph is None or not getattr(glyph, "name", None):
            Glyphs.showNotification("Bitmap Brush", "The active layer has no named glyph.")
            return

        bitmapPath = self.bitmapPathForGlyph(fontPath, glyph.name)
        if not self.canUseLayerBackgroundImage(layer, bitmapPath, fontPath):
            Glyphs.showNotification(
                "Bitmap Brush",
                "This layer already has another background image. Remove it before using Bitmap Brush.",
            )
            return

        erasing = self.isOptionKeyPressed(event)
        # Do not create an empty PNG, and do not guess the origin of an orphan
        # PNG that is not attached to this layer. Erasing only makes sense for
        # a bitmap whose font-unit origin we already know.
        if erasing and self.existingBitmapInfo(layer, bitmapPath) is None:
            return

        self.painting = True
        self.strokeErasing = bool(erasing)
        self.paintingLayer = layer
        self.paintingGlyph = glyph
        self.paintingFont = font
        self.bitmapPath = bitmapPath
        self.lastBrushCenter = None
        self.strokeRows = {}
        self.strokeBounds = None
        self.lastLayer = layer

        self.paintAtEvent(event)

        # On the very first stroke, create the PNG immediately after the first
        # stamp, as requested. This is only a tiny one-off write; the rest of
        # the drag remains in memory and is committed on mouseUp.
        if (
            self.strokeRows
            and not self.strokeErasing
            and not os.path.isfile(bitmapPath)
        ):
            try:
                self.writeStrokeToPNG(layer, bitmapPath, self.strokeRows)
                self.attachFreshBackgroundImages(bitmapPath, layer, font)
                # The first stamp is now part of the background image. Keep the
                # current brush centre, but start a fresh in-memory delta for
                # the remainder of the same stroke.
                self.strokeRows = {}
                self.strokeBounds = None
            except Exception:
                self.painting = False
                self.strokeErasing = False
                self.paintingLayer = None
                self.paintingGlyph = None
                self.paintingFont = None
                self.bitmapPath = None
                self.lastBrushCenter = None
                self.strokeRows = {}
                self.strokeBounds = None
                self.lastLayer = None
                raise

    @objc.python_method
    def finishStroke(self, commit=True):
        if not self.painting:
            return

        layer = self.paintingLayer
        bitmapPath = self.bitmapPath
        font = self.paintingFont or Glyphs.font
        rows = self.strokeRows

        try:
            if commit and layer is not None and bitmapPath and rows:
                self.writeStrokeToPNG(layer, bitmapPath, rows)
                self.attachFreshBackgroundImages(bitmapPath, layer, font)
        except Exception:
            print(traceback.format_exc())
            Glyphs.showMacroWindow()
            try:
                Glyphs.showNotification("Bitmap Brush", "Could not update the bitmap PNG. See Macro Panel.")
            except Exception:
                pass
        finally:
            self.painting = False
            self.strokeErasing = False
            self.paintingLayer = None
            self.paintingGlyph = None
            self.paintingFont = None
            self.bitmapPath = None
            self.lastBrushCenter = None
            self.strokeRows = {}
            self.strokeBounds = None
            self.lastLayer = None
            try:
                Glyphs.redraw()
            except Exception:
                pass

    @objc.python_method
    def paintAtEvent(self, event):
        if not self.painting:
            return

        try:
            graphicView = self.editViewController().graphicView()
            point = graphicView.getActiveLocation_(event)
            currentLayer = graphicView.activeLayer()
        except Exception:
            return

        if point is None or currentLayer is not self.paintingLayer:
            return

        center = (int(round(float(point.x))), int(round(float(point.y))))
        self.cursorLocation = NSMakePoint(float(center[0]), float(center[1]))
        self.cursorLayer = currentLayer

        previous = self.lastBrushCenter

        if previous is None:
            centers = [center]
        elif previous == center:
            return
        else:
            centers = self.pixelLine(previous, center)

        for cx, cy in centers:
            self.stampBrush(cx, cy)

        self.lastBrushCenter = center
        Glyphs.redraw()

    @objc.python_method
    def rebuildBrushGeometry(self):
        """Rasterise the current ellipse once and cache spans + cursor outline."""
        size = max(self.MIN_SIZE, min(self.MAX_SIZE, int(round(self.brushSize))))
        roundness = max(
            self.MIN_ROUNDNESS,
            min(self.MAX_ROUNDNESS, float(self.brushRoundness)),
        )
        angle = max(self.MIN_ANGLE, min(self.MAX_ANGLE, float(self.brushAngle)))

        self.brushSize = size
        self.brushRoundness = roundness
        self.brushAngle = angle

        majorDiameter = float(size)
        minorDiameter = max(1.0, majorDiameter * roundness / 100.0)
        majorRadius = max(0.5, majorDiameter * 0.5)
        minorRadius = max(0.5, minorDiameter * 0.5)

        radians = math.radians(angle)
        cosA = math.cos(radians)
        sinA = math.sin(radians)

        # Preserve the v0.1 default brush exactly for even diameters while
        # giving odd diameters a natural pixel-centred footprint.
        centerShift = 0.5 if (size % 2) else 0.0

        # Conservative bounds for a rotated ellipse. This runs only when a
        # palette value changes, not while painting.
        extentX = math.sqrt(
            (majorRadius * cosA) * (majorRadius * cosA)
            + (minorRadius * sinA) * (minorRadius * sinA)
        )
        extentY = math.sqrt(
            (majorRadius * sinA) * (majorRadius * sinA)
            + (minorRadius * cosA) * (minorRadius * cosA)
        )
        xLimit = int(math.ceil(extentX + 1.5))
        yLimit = int(math.ceil(extentY + 1.5))

        pixels = set()
        epsilon = 1e-9

        for oy in range(-yLimit, yLimit + 1):
            py = float(oy) + 0.5 - centerShift
            for ox in range(-xLimit, xLimit + 1):
                px = float(ox) + 0.5 - centerShift

                # Rotate sample point into the ellipse's local coordinate
                # system. Angle 0° means the major axis is horizontal.
                u = cosA * px + sinA * py
                v = -sinA * px + cosA * py
                value = (u * u) / (majorRadius * majorRadius) + (
                    v * v
                ) / (minorRadius * minorRadius)
                if value <= 1.0 + epsilon:
                    pixels.add((int(ox), int(oy)))

        # A sub-2-pixel minor axis can fall entirely between pixel centres,
        # especially with even brush sizes. Add the nearest one-pixel digital
        # major-axis skeleton so a very narrow ellipse remains drawable and
        # still reaches the requested major-axis size.
        if minorDiameter < 2.0:
            if size <= 1:
                lineSamples = [0.0]
            else:
                lineSamples = [
                    float(i) - (float(size) - 1.0) * 0.5
                    for i in range(size)
                ]
            for distance in lineSamples:
                px = distance * cosA
                py = distance * sinA
                ox = int(round(px - 0.5 + centerShift))
                oy = int(round(py - 0.5 + centerShift))
                pixels.add((ox, oy))

        if not pixels:
            pixels.add((0, 0))

        rows = {}
        for ox, oy in pixels:
            rows.setdefault(oy, []).append(ox)

        spans = []
        for oy in sorted(rows.keys()):
            xs = sorted(rows[oy])
            start = xs[0]
            previous = xs[0]
            for x in xs[1:]:
                if x == previous + 1:
                    previous = x
                    continue
                spans.append((oy, start, previous))
                start = x
                previous = x
            spans.append((oy, start, previous))

        minX = min(x for x, _ in pixels)
        maxX = max(x for x, _ in pixels)
        minY = min(y for _, y in pixels)
        maxY = max(y for _, y in pixels)

        self.brushPixels = pixels
        self.brushSpans = spans
        self.brushBoundsOffsets = (minX, minY, maxX + 1, maxY + 1)
        self.brushOutlinePath = self.makeBrushOutlinePath(pixels)

    @objc.python_method
    def makeBrushOutlinePath(self, pixels):
        """Build only the exposed unit-pixel edges of the raster brush."""
        path = NSBezierPath.bezierPath()
        if not pixels:
            return path

        for x, y in pixels:
            if (x - 1, y) not in pixels:
                path.moveToPoint_(NSMakePoint(x, y))
                path.lineToPoint_(NSMakePoint(x, y + 1))
            if (x + 1, y) not in pixels:
                path.moveToPoint_(NSMakePoint(x + 1, y))
                path.lineToPoint_(NSMakePoint(x + 1, y + 1))
            if (x, y - 1) not in pixels:
                path.moveToPoint_(NSMakePoint(x, y))
                path.lineToPoint_(NSMakePoint(x + 1, y))
            if (x, y + 1) not in pixels:
                path.moveToPoint_(NSMakePoint(x, y + 1))
                path.lineToPoint_(NSMakePoint(x + 1, y + 1))
        return path

    @objc.python_method
    def pixelLine(self, start, end):
        """Integer Bresenham centres, excluding start and including end."""
        x0, y0 = int(start[0]), int(start[1])
        x1, y1 = int(end[0]), int(end[1])
        points = []

        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        err = dx + dy

        while not (x0 == x1 and y0 == y1):
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
            points.append((x0, y0))
        return points

    @objc.python_method
    def stampBrush(self, cx, cy):
        for yOffset, xLeftOffset, xRightOffset in self.brushSpans:
            y = cy + yOffset
            left = cx + xLeftOffset
            right = cx + xRightOffset
            self.addInterval(y, left, right)

        leftOffset, bottomOffset, rightOffset, topOffset = self.brushBoundsOffsets
        self.extendStrokeBounds(
            cx + leftOffset,
            cy + bottomOffset,
            cx + rightOffset,
            cy + topOffset,
        )

    @objc.python_method
    def addInterval(self, y, left, right):
        """Insert and merge an inclusive x interval in one bitmap row."""
        if right < left:
            left, right = right, left

        intervals = self.strokeRows.setdefault(int(y), [])
        if not intervals:
            intervals.append([int(left), int(right)])
            return

        newLeft = int(left)
        newRight = int(right)
        merged = []
        inserted = False

        for oldLeft, oldRight in intervals:
            if oldRight + 1 < newLeft:
                merged.append([oldLeft, oldRight])
            elif newRight + 1 < oldLeft:
                if not inserted:
                    merged.append([newLeft, newRight])
                    inserted = True
                merged.append([oldLeft, oldRight])
            else:
                newLeft = min(newLeft, oldLeft)
                newRight = max(newRight, oldRight)

        if not inserted:
            merged.append([newLeft, newRight])
        self.strokeRows[int(y)] = merged

    @objc.python_method
    def extendStrokeBounds(self, left, bottom, right, top):
        if self.strokeBounds is None:
            self.strokeBounds = [int(left), int(bottom), int(right), int(top)]
            return
        self.strokeBounds[0] = min(self.strokeBounds[0], int(left))
        self.strokeBounds[1] = min(self.strokeBounds[1], int(bottom))
        self.strokeBounds[2] = max(self.strokeBounds[2], int(right))
        self.strokeBounds[3] = max(self.strokeBounds[3], int(top))

    # ------------------------------------------------------------------
    # Fast live overlay: one rect per merged horizontal run, not per pixel.
    # ------------------------------------------------------------------

    @objc.python_method
    def foreground(self, layer):
        try:
            # Live stroke delta: merged horizontal runs, so the draw cost is
            # proportional to run count rather than individual pixels.
            if self.painting and layer is self.paintingLayer and self.strokeRows:
                if self.strokeErasing:
                    # Screen-only feedback for an erase stroke. The actual PNG
                    # pixels are cleared on commit below.
                    NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.42).setFill()
                else:
                    gray = max(0.0, min(1.0, float(self.brushGray) / 255.0))
                    NSColor.colorWithDeviceRed_green_blue_alpha_(gray, gray, gray, 0.88).setFill()
                for y, intervals in self.strokeRows.items():
                    for left, right in intervals:
                        NSRectFill(NSMakeRect(left, y, right - left + 1, 1))

            self.drawBrushCursorPreview(layer)
        except Exception:
            print(traceback.format_exc())

    # ------------------------------------------------------------------
    # PNG persistence and GSBackgroundImage refresh
    # ------------------------------------------------------------------

    @objc.python_method
    def writeStrokeToPNG(self, layer, path, rows):
        directory = os.path.dirname(path)
        if not os.path.isdir(directory):
            os.makedirs(directory)

        old = self.existingBitmapInfo(layer, path)
        stroke = self.strokeBoundsFromRows(rows)
        if stroke is None:
            return

        if self.strokeErasing:
            if old is None:
                return
            oldLeft, oldBottom, oldRight, oldTop = old["bounds"]
            # The eraser must never enlarge the bitmap with transparent space.
            if (
                stroke[2] <= oldLeft
                or stroke[0] >= oldRight
                or stroke[3] <= oldBottom
                or stroke[1] >= oldTop
            ):
                return
            newLeft, newBottom, newRight, newTop = old["bounds"]
        elif old is None:
            newLeft, newBottom, newRight, newTop = stroke
        else:
            oldLeft, oldBottom, oldRight, oldTop = old["bounds"]
            newLeft = min(oldLeft, stroke[0])
            newBottom = min(oldBottom, stroke[1])
            newRight = max(oldRight, stroke[2])
            newTop = max(oldTop, stroke[3])

        width = int(newRight - newLeft)
        height = int(newTop - newBottom)
        if width <= 0 or height <= 0:
            return

        rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None,
            width,
            height,
            8,
            4,
            True,
            False,
            NSDeviceRGBColorSpace,
            0,
            32,
        )
        if rep is None:
            raise RuntimeError("Could not allocate bitmap image representation")

        context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
        if context is None:
            raise RuntimeError("Could not create bitmap graphics context")

        NSGraphicsContext.saveGraphicsState()
        try:
            NSGraphicsContext.setCurrentContext_(context)
            if NSImageInterpolationNone is not None:
                try:
                    context.setImageInterpolation_(NSImageInterpolationNone)
                except Exception:
                    pass

            fullRect = NSMakeRect(0, 0, width, height)
            if NSRectFillUsingOperation is not None:
                NSRectFillUsingOperation(fullRect, NSCompositingOperationClear)

            if old is not None and old.get("image") is not None:
                oldImage = old["image"]
                oldWidth = old["width"]
                oldHeight = old["height"]
                oldLeft = old["bounds"][0]
                oldBottom = old["bounds"][1]
                destRect = NSMakeRect(
                    oldLeft - newLeft,
                    oldBottom - newBottom,
                    oldWidth,
                    oldHeight,
                )
                sourceSize = oldImage.size()
                sourceRect = NSMakeRect(0, 0, sourceSize.width, sourceSize.height)
                self.drawImage(oldImage, destRect, sourceRect)

            if self.strokeErasing:
                for y, intervals in rows.items():
                    if y < newBottom or y >= newTop:
                        continue
                    destY = int(y - newBottom)
                    for left, right in intervals:
                        clippedLeft = max(int(left), int(newLeft))
                        clippedRight = min(int(right), int(newRight - 1))
                        if clippedRight < clippedLeft:
                            continue
                        rect = NSMakeRect(
                            int(clippedLeft - newLeft),
                            destY,
                            int(clippedRight - clippedLeft + 1),
                            1,
                        )
                        if NSRectFillUsingOperation is not None:
                            NSRectFillUsingOperation(rect, NSCompositingOperationClear)
                        else:
                            # Very old AppKit fallback. This path is not used on
                            # current Glyphs 3/macOS, but keeps the operation
                            # correct if NSRectFillUsingOperation is unavailable.
                            clear = NSColor.clearColor()
                            for px in range(clippedLeft, clippedRight + 1):
                                try:
                                    rep.setColor_atX_y_(
                                        clear, int(px - newLeft), destY
                                    )
                                except Exception:
                                    pass
            else:
                gray = max(0.0, min(1.0, float(self.brushGray) / 255.0))
                NSColor.colorWithDeviceRed_green_blue_alpha_(gray, gray, gray, 1.0).setFill()
                for y, intervals in rows.items():
                    destY = int(y - newBottom)
                    for left, right in intervals:
                        NSRectFill(
                            NSMakeRect(
                                int(left - newLeft),
                                destY,
                                int(right - left + 1),
                                1,
                            )
                        )
        finally:
            NSGraphicsContext.restoreGraphicsState()

        data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        if data is None:
            raise RuntimeError("Could not encode bitmap as PNG")
        if not data.writeToFile_atomically_(path, True):
            raise IOError("Could not write bitmap PNG: %s" % path)

        # Store the exact image origin for attachFreshBackgroundImages().
        self._lastWrittenOrigin = (int(newLeft), int(newBottom))

    @objc.python_method
    def drawImage(self, image, destRect, sourceRect):
        try:
            image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                destRect,
                sourceRect,
                NSCompositingOperationSourceOver,
                1.0,
                False,
                None,
            )
            return
        except Exception:
            pass

        image.drawInRect_fromRect_operation_fraction_(
            destRect,
            sourceRect,
            NSCompositingOperationSourceOver,
            1.0,
        )

    @objc.python_method
    def existingBitmapInfo(self, layer, targetPath):
        if not os.path.isfile(targetPath):
            return None

        backgroundImage = getattr(layer, "backgroundImage", None)
        if backgroundImage is None:
            # An orphan PNG cannot tell us its font-unit origin. Treat the next
            # stroke as a fresh bitmap rather than guessing and shifting pixels.
            return None

        font = Glyphs.font
        fontPath = self.fontFilePath(font) if font is not None else None
        existingPath = self.absoluteBackgroundPath(backgroundImage, fontPath)
        if existingPath is None or not self.samePath(existingPath, targetPath):
            return None

        image = NSImage.alloc().initWithContentsOfFile_(targetPath)
        if image is None:
            return None

        width = 0
        height = 0
        try:
            for rep in image.representations():
                try:
                    pixelWidth = int(rep.pixelsWide())
                    pixelHeight = int(rep.pixelsHigh())
                    if pixelWidth > 0 and pixelHeight > 0:
                        width = pixelWidth
                        height = pixelHeight
                        break
                except Exception:
                    pass
        except Exception:
            pass

        if width <= 0 or height <= 0:
            size = image.size()
            width = int(round(size.width))
            height = int(round(size.height))

        if width <= 0 or height <= 0:
            return None

        try:
            position = backgroundImage.position
            left = int(round(float(position.x)))
            bottom = int(round(float(position.y)))
        except Exception:
            left = 0
            bottom = 0

        return {
            "image": image,
            "width": width,
            "height": height,
            "bounds": (left, bottom, left + width, bottom + height),
        }

    @objc.python_method
    def attachFreshBackgroundImages(self, path, activeLayer, font):
        origin = getattr(self, "_lastWrittenOrigin", None)
        if origin is None:
            origin = self.originFromLayerBackground(activeLayer, path, font)
        if origin is None:
            origin = (0, 0)

        # Refresh all layers of this glyph that already point at the same PNG,
        # plus the layer we just painted. This avoids stale NSImage caches.
        layers = [activeLayer]
        glyph = getattr(activeLayer, "parent", None)
        if glyph is not None:
            try:
                for candidate in glyph.layers:
                    if candidate is activeLayer:
                        continue
                    bg = getattr(candidate, "backgroundImage", None)
                    if bg is None:
                        continue
                    candidatePath = self.absoluteBackgroundPath(bg, self.fontFilePath(font))
                    if candidatePath and self.samePath(candidatePath, path):
                        layers.append(candidate)
            except Exception:
                pass

        for candidate in layers:
            fresh = GSBackgroundImage(path)
            fresh.position = NSMakePoint(float(origin[0]), float(origin[1]))
            fresh.scale = (1.0, 1.0)
            fresh.rotation = 0.0
            fresh.locked = True
            try:
                fresh.alpha = self.BITMAP_ALPHA
            except Exception:
                pass
            candidate.backgroundImage = fresh

        try:
            del self._lastWrittenOrigin
        except Exception:
            pass

    @objc.python_method
    def originFromLayerBackground(self, layer, path, font):
        bg = getattr(layer, "backgroundImage", None)
        if bg is None:
            return None
        existingPath = self.absoluteBackgroundPath(bg, self.fontFilePath(font))
        if existingPath is None or not self.samePath(existingPath, path):
            return None
        try:
            return (int(round(float(bg.position.x))), int(round(float(bg.position.y))))
        except Exception:
            return None

    @objc.python_method
    def strokeBoundsFromRows(self, rows):
        if self.strokeBounds is not None:
            return tuple(self.strokeBounds)
        if not rows:
            return None

        minY = min(rows.keys())
        maxY = max(rows.keys())
        minX = None
        maxX = None
        for intervals in rows.values():
            for left, right in intervals:
                minX = left if minX is None else min(minX, left)
                maxX = right if maxX is None else max(maxX, right)
        if minX is None:
            return None
        return (int(minX), int(minY), int(maxX + 1), int(maxY + 1))

    # ------------------------------------------------------------------
    # Paths, layer checks, and Glyphs helpers
    # ------------------------------------------------------------------

    @objc.python_method
    def activeLayer(self):
        try:
            return self.editViewController().graphicView().activeLayer()
        except Exception:
            try:
                font = Glyphs.font
                if font is not None and font.selectedLayers:
                    return font.selectedLayers[0]
            except Exception:
                pass
        return None

    @objc.python_method
    def fontFilePath(self, font):
        if font is None:
            return None
        for attr in ("filepath", "filePath"):
            try:
                value = getattr(font, attr)
                if callable(value):
                    value = value()
                if value:
                    return os.path.abspath(os.path.expanduser(str(value)))
            except Exception:
                pass
        return None

    @objc.python_method
    def bitmapPathForGlyph(self, fontPath, glyphName):
        root = os.path.dirname(fontPath)
        # Glyph names normally make safe filenames. Protect only actual path
        # separators while otherwise preserving the glyph name verbatim.
        safeName = str(glyphName).replace(os.sep, "_")
        if os.altsep:
            safeName = safeName.replace(os.altsep, "_")
        return os.path.join(root, self.BITMAP_FOLDER, safeName + ".png")

    @objc.python_method
    def canUseLayerBackgroundImage(self, layer, targetPath, fontPath):
        bg = getattr(layer, "backgroundImage", None)
        if bg is None:
            return True
        existingPath = self.absoluteBackgroundPath(bg, fontPath)
        if existingPath is None:
            return False
        return self.samePath(existingPath, targetPath)

    @objc.python_method
    def absoluteBackgroundPath(self, backgroundImage, fontPath):
        try:
            path = backgroundImage.path
        except Exception:
            path = None
        if not path:
            try:
                path = backgroundImage.imagePath()
            except Exception:
                path = None
        if not path:
            return None

        path = os.path.expanduser(str(path))
        if os.path.isabs(path):
            absolute = os.path.abspath(path)
            if os.path.exists(absolute) or not fontPath:
                return absolute

            # Some Glyphs files have historically serialised document-relative
            # image paths with a leading slash (e.g. /bitmaps/a.png). If that
            # absolute path does not exist, also resolve it next to the font.
            relativeCandidate = os.path.abspath(
                os.path.join(os.path.dirname(fontPath), path.lstrip("/\\"))
            )
            if os.path.exists(relativeCandidate):
                return relativeCandidate
            return absolute
        if fontPath:
            return os.path.abspath(os.path.join(os.path.dirname(fontPath), path))
        return os.path.abspath(path)

    @objc.python_method
    def samePath(self, pathA, pathB):
        try:
            return os.path.realpath(pathA) == os.path.realpath(pathB)
        except Exception:
            return os.path.abspath(pathA) == os.path.abspath(pathB)

    @objc.python_method
    def showAlert(self, title, message):
        try:
            alert = NSAlert.alloc().init()
            alert.setMessageText_(str(title))
            alert.setInformativeText_(str(message))
            alert.addButtonWithTitle_("OK")
            try:
                alert.runModal()
                return
            except Exception:
                pass
        except Exception:
            pass
        try:
            Glyphs.showNotification(str(title), str(message))
        except Exception:
            pass

    @objc.python_method
    def __file__(self):
        """Return this module path. Required by Glyphs Python tool plug-ins."""
        return __file__
