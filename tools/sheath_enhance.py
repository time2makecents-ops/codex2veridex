from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


SOURCE = Path(r"C:\Users\Accordion to JR\Documents\items_selling\boyscout_knife")
OUTPUT = SOURCE / "sheath_analysis"


def to_bgr(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def clahe(channel: np.ndarray, clip: float = 2.5) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(channel)


def fit_panel(image: np.ndarray, width: int = 900, height: int = 700) -> Image.Image:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    panel = Image.fromarray(rgb)
    panel.thumbnail((width, height - 44), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(panel, ((width - panel.width) // 2, 44 + (height - 44 - panel.height) // 2))
    return canvas


def add_label(panel: Image.Image, label: str) -> None:
    ImageDraw.Draw(panel).text((14, 10), label, fill="black", font=ImageFont.load_default(size=26))


def variants(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blue, green, red = cv2.split(image)
    lab_l = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[:, :, 0]
    blur = cv2.GaussianBlur(gray, (0, 0), 25)
    normalized = cv2.divide(gray, blur, scale=180)
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    return [
        ("original", image),
        ("gray + CLAHE", clahe(gray)),
        ("red channel + CLAHE", clahe(red)),
        ("green channel + CLAHE", clahe(green)),
        ("blue channel + CLAHE", clahe(blue)),
        ("LAB lightness + CLAHE", clahe(lab_l)),
        ("background normalized", clahe(normalized)),
        ("dark-stroke blackhat", cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)),
    ]


def contact_sheet(path: Path, crop=None) -> Path:
    image = to_bgr(path)
    if crop:
        x1, y1, x2, y2 = crop
        image = image[y1:y2, x1:x2]
    panels = []
    for label, variant in variants(image):
        panel = fit_panel(variant)
        add_label(panel, label)
        panels.append(panel)
    sheet = Image.new("RGB", (1800, 2800), "#dddddd")
    for index, panel in enumerate(panels):
        sheet.paste(panel, ((index % 2) * 900, (index // 2) * 700))
    out = OUTPUT / f"{path.stem}_comparison.jpg"
    sheet.save(out, quality=95, subsampling=0)
    return out


def rotate_bound(image: np.ndarray, angle: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_width = int(height * sine + width * cosine)
    new_height = int(height * cosine + width * sine)
    matrix[0, 2] += new_width / 2 - center[0]
    matrix[1, 2] += new_height / 2 - center[1]
    return cv2.warpAffine(image, matrix, (new_width, new_height), borderValue=(255, 255, 255))


def rotation_sheet() -> Path:
    image = to_bgr(SOURCE / "sheath6.jpg")[1150:2400, 650:2550]
    red = clahe(image[:, :, 2], 2.0)
    panels = []
    for angle in (-20, -15, -10, -5, 0, 5, 10, 15):
        panel = fit_panel(rotate_bound(red, angle))
        add_label(panel, f"red channel, rotation {angle:+d} degrees")
        panels.append(panel)
    sheet = Image.new("RGB", (1800, 2800), "#dddddd")
    for index, panel in enumerate(panels):
        sheet.paste(panel, ((index % 2) * 900, (index // 2) * 700))
    out = OUTPUT / "sheath6_rotation_comparison.jpg"
    sheet.save(out, quality=95, subsampling=0)
    return out


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    jobs = {
        "sheath1.jpg": None,
        "sheath2.jpg": None,
        "sheath6.jpg": (500, 950, 2600, 2500),
        "sheath7.jpg": (180, 420, 1160, 1270),
        "sheath8.jpg": (500, 1250, 2800, 2900),
        "sheath9.jpg": (500, 1250, 2800, 2900),
    }
    for name, crop in jobs.items():
        out = contact_sheet(SOURCE / name, crop)
        print(out)
    print(rotation_sheet())


if __name__ == "__main__":
    main()
