# Bitmap Brush for Glyphs 3

*Bitmap Brush* is a drawing tool for *Glyphs 3* that lets you paint directly in the Edit View using a raster bitmap.

The bitmap is stored as a PNG next to your `.glyphs` file and attached to the current layer as a locked background image. One bitmap pixel corresponds to one font unit, so the result stays aligned with the Glyphs coordinate grid.

## Features

- Paint directly in the Glyphs Edit View
- Automatic `bitmaps` folder next to the `.glyphs` file
- **Alt / Option + drag** works as an eraser
- **Command + drag** temporarily passes control to the Selection Tool

## Installation

1. Download and unzip `BitmapBrush.glyphsTool`.
2. Drag and drop `BitmapBrush.glyphsTool` onto the Glyphs app.
3. Restart Glyphs.

## File handling

*Bitmap Brush* stores bitmap files relative to the saved `.glyphs` document:

```text
<font folder>/bitmaps/<glyphname>.png
```

If the current layer already contains a different background image, *Bitmap Brush* will not replace it automatically.

## Current version

`v0.2.2`

## License

*Bitmap Brush* is released under the [MIT License](LICENSE).

