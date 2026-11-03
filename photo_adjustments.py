"""Shared local photo adjustments; Item Intake keeps its JPEG wrapper."""
from __future__ import annotations
import io
import math
from typing import Any, Dict
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


def adjust_image(image: Image.Image, operation: str, options: Dict[str, Any]):
    width, height = image.size
    metadata: Dict[str, Any] = {"operation": operation, "engine": "local_pillow"}
    if operation == "crop":
        try:
            left_percent = float(options.get("left_percent") or 0)
            top_percent = float(options.get("top_percent") or 0)
            right_percent = float(options.get("right_percent") or 100)
            bottom_percent = float(options.get("bottom_percent") or 100)
        except (TypeError, ValueError):
            raise ValueError("Crop controls are invalid") from None
        if not all(math.isfinite(value) and 0 <= value <= 100 for value in (left_percent, top_percent, right_percent, bottom_percent)):
            raise ValueError("Crop controls must be percentages from 0 to 100")
        left, top = round(width * left_percent / 100), round(height * top_percent / 100)
        right, bottom = round(width * right_percent / 100), round(height * bottom_percent / 100)
        if right - left < 32 or bottom - top < 32:
            raise ValueError("Keep a crop area at least 32 pixels wide and high")
        image = image.crop((left, top, right, bottom))
        metadata["crop"] = {"left_percent": left_percent, "top_percent": top_percent, "right_percent": right_percent, "bottom_percent": bottom_percent}
    elif operation == "auto_crop":
        corners = [image.getpixel((x, y)) for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
        background = tuple(round(sum(color[index] for color in corners) / len(corners)) for index in range(3))
        difference = ImageOps.grayscale(ImageChops.difference(image, Image.new("RGB", image.size, background)))
        box = difference.point(lambda value: 255 if value > 18 else 0).getbbox()
        if box:
            padding = max(4, round(min(width, height) * 0.02))
            left, top, right, bottom = max(0, box[0] - padding), max(0, box[1] - padding), min(width, box[2] + padding), min(height, box[3] + padding)
            if right - left >= 32 and bottom - top >= 32:
                image = image.crop((left, top, right, bottom))
                metadata["crop"] = {"left": left, "top": top, "right": right, "bottom": bottom, "method": "edge-contrast"}
            else:
                metadata["crop"] = {"method": "edge-contrast", "applied": False}
        else:
            metadata["crop"] = {"method": "edge-contrast", "applied": False}
    elif operation == "adjust":
        def adjustment(name: str, default: float = 0.0, minimum: float = -100.0, maximum: float = 100.0) -> float:
            try:
                value = float(options.get(name, default))
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number") from None
            if not math.isfinite(value) or value < minimum or value > maximum:
                raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
            return value

        crop_values = [options.get(key) for key in ("left_percent", "top_percent", "right_percent", "bottom_percent")]
        if any(value is not None for value in crop_values):
            try:
                left_percent = float(options.get("left_percent") or 0)
                top_percent = float(options.get("top_percent") or 0)
                right_percent = float(options.get("right_percent") if options.get("right_percent") is not None else 100)
                bottom_percent = float(options.get("bottom_percent") if options.get("bottom_percent") is not None else 100)
            except (TypeError, ValueError):
                raise ValueError("Crop controls are invalid") from None
            if not all(math.isfinite(value) and 0 <= value <= 100 for value in (left_percent, top_percent, right_percent, bottom_percent)):
                raise ValueError("Crop controls must be percentages from 0 to 100")
            left, top = round(width * left_percent / 100), round(height * top_percent / 100)
            right, bottom = round(width * right_percent / 100), round(height * bottom_percent / 100)
            if right - left < 32 or bottom - top < 32:
                raise ValueError("Keep a crop area at least 32 pixels wide and high")
            image = image.crop((left, top, right, bottom))
            width, height = image.size
            metadata["crop"] = {"left_percent": left_percent, "top_percent": top_percent, "right_percent": right_percent, "bottom_percent": bottom_percent}

        rotation = adjustment("rotation", 0, -360, 360)
        if rotation:
            rotation = (round(rotation / 90) * 90) % 360
            image = image.rotate(-rotation, expand=True)
            metadata["rotation"] = rotation
        brightness = adjustment("brightness")
        exposure = adjustment("exposure")
        contrast = adjustment("contrast")
        saturation = adjustment("saturation")
        warmth = adjustment("warmth")
        highlights = adjustment("highlights")
        shadows = adjustment("shadows")
        sharpness = adjustment("sharpness")
        definition = adjustment("definition")
        if exposure or brightness:
            image = ImageEnhance.Brightness(image).enhance((2 ** (exposure / 100)) * (1 + brightness / 100))
        if contrast or definition:
            image = ImageEnhance.Contrast(image).enhance(max(0.05, 1 + contrast / 100 + definition / 200))
        if saturation:
            image = ImageEnhance.Color(image).enhance(max(0, 1 + saturation / 100))
        if sharpness:
            image = ImageEnhance.Sharpness(image).enhance(max(0, 1 + sharpness / 100))
        if warmth:
            warm = warmth / 100
            red_lookup = [max(0, min(255, round(value + 32 * warm))) for value in range(256)]
            blue_lookup = [max(0, min(255, round(value - 32 * warm))) for value in range(256)]
            red, green, blue = image.split()
            image = Image.merge("RGB", (red.point(red_lookup), green, blue.point(blue_lookup)))
        if highlights or shadows:
            def tone_lookup(value: int) -> int:
                level = value / 255
                delta = 0
                if shadows and level < 0.55:
                    delta += (shadows / 100) * ((0.55 - level) / 0.55) * 0.35
                if highlights and level > 0.45:
                    delta += (highlights / 100) * ((level - 0.45) / 0.55) * 0.35
                return max(0, min(255, round((level + delta) * 255)))
            lookup = [tone_lookup(value) for value in range(256)]
            image = Image.merge("RGB", tuple(channel.point(lookup) for channel in image.split()))
        metadata["adjustments"] = {
            key: value for key, value in {
                "brightness": brightness, "exposure": exposure, "contrast": contrast,
                "saturation": saturation, "warmth": warmth, "highlights": highlights,
                "shadows": shadows, "sharpness": sharpness, "definition": definition,
            }.items() if value
        }
    elif operation == "marketplace_auto":
        # Conservative, local-only marketplace pass. It improves the photograph
        # without synthesizing pixels, replacing the background, or changing the
        # object's geometry/condition. Highlight softening is limited to bright
        # low-saturation peaks whose surrounding area is materially darker.
        image = ImageOps.autocontrast(image, cutoff=1)
        image = ImageEnhance.Color(image).enhance(1.03)
        image = ImageEnhance.Contrast(image).enhance(1.03)
        image = ImageEnhance.Sharpness(image).enhance(1.04)
        gray = ImageOps.grayscale(image)
        blurred_gray = gray.filter(ImageFilter.GaussianBlur(radius=3))
        bright = gray.point(lambda value: 255 if value >= 245 else 0)
        surrounding = blurred_gray.point(lambda value: max(0, min(255, (232 - value) * 4)))
        glare_mask = ImageChops.multiply(bright, surrounding).filter(ImageFilter.GaussianBlur(radius=1.25))
        if glare_mask.getbbox():
            softened = ImageEnhance.Brightness(image).enhance(0.90)
            image = Image.composite(softened, image, glare_mask)
            metadata["glare_softening"] = {"applied": True, "method": "conservative-highlight-peaks", "strength": 0.10}
        else:
            metadata["glare_softening"] = {"applied": False, "method": "conservative-highlight-peaks"}
        metadata["adjustments"] = {"autocontrast_cutoff": 1, "color": 1.03, "contrast": 1.03, "sharpness": 1.04}
    elif operation == "auto_adjust":
        image = ImageOps.autocontrast(image, cutoff=1)
        image = ImageEnhance.Color(image).enhance(1.05)
        image = ImageEnhance.Contrast(image).enhance(1.04)
        image = ImageEnhance.Sharpness(image).enhance(1.08)
        metadata["adjustments"] = {"autocontrast_cutoff": 1, "color": 1.05, "contrast": 1.04, "sharpness": 1.08}
    else:
        raise ValueError("Unknown touch-up operation")
    return image, metadata


def _touchup_jpeg(content: bytes, operation: str, options: Dict[str, Any]) -> tuple[bytes, Dict[str, Any]]:
    with Image.open(io.BytesIO(content)) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
    image = image.convert("RGB")
    image, metadata = adjust_image(image, operation, options)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue(), metadata
