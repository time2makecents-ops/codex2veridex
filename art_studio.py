"""Free-only Visual Design providers, finishing tools, projects, and jobs."""

from __future__ import annotations

import base64
import io
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps


MAX_PROVIDER_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
FREE_POLLINATIONS_MODELS = {"flux", "zimage"}

ART_PRESETS = [
    {"id": "photography", "name": "Photography", "suffix": "natural photography, believable materials, controlled light, realistic detail"},
    {"id": "cinematic", "name": "Cinematic", "suffix": "cinematic composition, motivated lighting, atmospheric depth, deliberate color grade"},
    {"id": "illustration", "name": "Illustration", "suffix": "editorial illustration, confident shapes, refined color palette, clean focal hierarchy"},
    {"id": "watercolor", "name": "Watercolor", "suffix": "watercolor on textured paper, translucent washes, expressive edges, restrained pigment blooms"},
    {"id": "comic", "name": "Comic", "suffix": "graphic novel illustration, clear silhouettes, expressive ink, controlled halftone texture"},
    {"id": "pixel", "name": "Pixel art", "suffix": "intentional pixel art, limited palette, readable silhouette, crisp nearest-neighbor edges"},
    {"id": "product", "name": "Product mockup", "suffix": "premium product photography, clean staging, accurate proportions, commercial lighting"},
    {"id": "poster", "name": "Poster", "suffix": "poster composition, strong negative space, clear hierarchy, legible integrated typography"},
    {"id": "icon", "name": "Logo or icon concept", "suffix": "simple symbol concept, flat vector-like shapes, memorable silhouette, no trademarked marks"},
    {"id": "social", "name": "Social post", "suffix": "social campaign art, immediate focal point, mobile-readable composition, clear safe areas"},
    {"id": "wallpaper", "name": "Wallpaper", "suffix": "wide wallpaper composition, edge-to-edge detail, calm negative space for desktop icons"},
    {"id": "transparent", "name": "Transparent asset", "suffix": "single isolated subject, clean studio edge, plain high-contrast background for cutout"},
]

ART_MODELS = [
    {"id": "auto", "name": "Auto", "provider": "auto", "capabilities": ["generate", "edit"]},
    {"id": "fast", "name": "Fast draft", "provider": "cloudflare", "remote_id": "@cf/black-forest-labs/flux-1-schnell", "capabilities": ["generate"]},
    {"id": "edit", "name": "Reference edit", "provider": "cloudflare", "remote_id": "@cf/black-forest-labs/flux-2-klein-4b", "capabilities": ["generate", "edit"]},
    {"id": "text", "name": "Text and poster", "provider": "cloudflare", "remote_id": "@cf/leonardo/phoenix-1.0", "capabilities": ["generate"]},
    {"id": "quality", "name": "Quality", "provider": "cloudflare", "remote_id": "@cf/leonardo/lucid-origin", "capabilities": ["generate"]},
    {"id": "pollinations_flux", "name": "Fallback Flux", "provider": "pollinations", "remote_id": "flux", "capabilities": ["generate"]},
    {"id": "pollinations_zimage", "name": "Fallback Z-Image", "provider": "pollinations", "remote_id": "zimage", "capabilities": ["generate"]},
]

ASPECT_SIZES = {
    "square": (1024, 1024),
    "portrait": (832, 1216),
    "landscape": (1216, 832),
    "story": (768, 1344),
    "wide": (1344, 768),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _safe_name(value: str, fallback: str = "artwork") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._-")
    return cleaned[:90] or fallback


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def validate_image_bytes(content: bytes) -> Dict[str, Any]:
    if not content or len(content) > MAX_PROVIDER_BYTES:
        raise ValueError("Image output is empty or exceeds the 20 MB safety limit")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image_format = str(image.format or "").upper()
    except Exception as exc:
        raise ValueError("Provider returned an unreadable image") from exc
    if image_format not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported generated image format: {image_format or 'unknown'}")
    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("Image dimensions exceed the 25 megapixel safety limit")
    return {
        "width": width,
        "height": height,
        "format": image_format,
        "content_type": {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[image_format],
    }


class ArtProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, *, retryable: bool = False, quota: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.quota = quota


def _http_request(request: Request, *, timeout: int = 90) -> tuple[bytes, str]:
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read(MAX_PROVIDER_BYTES + 1)
            if len(content) > MAX_PROVIDER_BYTES:
                raise ArtProviderError("remote", "Provider response exceeded 20 MB")
            return content, str(response.headers.get("Content-Type") or "")
    except HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", errors="replace")
        lowered = detail.lower()
        quota = exc.code in {402, 429} or "quota" in lowered or "neuron" in lowered or "balance" in lowered
        raise ArtProviderError("remote", f"Provider request failed ({exc.code})", retryable=exc.code >= 500 or exc.code == 429, quota=quota) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ArtProviderError("remote", "Provider is temporarily unavailable", retryable=True) from exc


def _image_from_response(content: bytes, content_type: str) -> bytes:
    if content_type.lower().startswith("image/"):
        return content
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtProviderError("remote", "Provider returned an unexpected response") from exc
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    encoded = result.get("image") if isinstance(result, dict) else None
    if not encoded and isinstance(result, dict):
        encoded = result.get("b64_json")
    if not encoded and isinstance(result, dict) and isinstance(result.get("data"), list) and result["data"]:
        encoded = result["data"][0].get("b64_json")
    if not encoded:
        raise ArtProviderError("remote", "Provider did not return image data")
    try:
        return base64.b64decode(str(encoded), validate=True)
    except Exception as exc:
        raise ArtProviderError("remote", "Provider returned invalid image encoding") from exc


def _multipart(fields: Dict[str, str], files: Iterable[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    boundary = "----VeridexArt" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode("utf-8"), b"\r\n",
        ])
    for field, filename, content_type, content in files:
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{_safe_name(filename)}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content, b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class CloudflareArtProvider:
    name = "cloudflare"

    @staticmethod
    def configured() -> bool:
        return bool(os.environ.get("VERIDEX_CLOUDFLARE_ACCOUNT_ID") and os.environ.get("VERIDEX_CLOUDFLARE_API_TOKEN"))

    def _request(self, model: str, payload: Dict[str, Any] | None = None, *, body: bytes | None = None, content_type: str = "application/json") -> bytes:
        if not self.configured():
            raise ArtProviderError(self.name, "Cloudflare Workers AI is not configured")
        account = str(os.environ.get("VERIDEX_CLOUDFLARE_ACCOUNT_ID") or "").strip()
        token = str(os.environ.get("VERIDEX_CLOUDFLARE_API_TOKEN") or "").strip()
        url = f"https://api.cloudflare.com/client/v4/accounts/{quote(account)}/ai/run/{model}"
        data = body if body is not None else json.dumps(payload or {}).encode("utf-8")
        request = Request(url, data=data, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": content_type})
        try:
            content, response_type = _http_request(request)
            return _image_from_response(content, response_type)
        except ArtProviderError as exc:
            exc.provider = self.name
            raise

    def generate(self, prompt: str, model: str, width: int, height: int, seed: int, negative_prompt: str, references: list[Dict[str, Any]]) -> bytes:
        if model == "@cf/black-forest-labs/flux-2-klein-4b":
            fields = {"prompt": prompt, "width": str(width), "height": str(height), "seed": str(seed)}
            files = [
                (f"input_image_{index}", str(row.get("name") or f"reference-{index}.png"), str(row.get("content_type") or "image/png"), bytes(row["content"]))
                for index, row in enumerate(references[:4])
            ]
            body, content_type = _multipart(fields, files)
            return self._request(model, body=body, content_type=content_type)
        payload: Dict[str, Any] = {"prompt": prompt, "width": width, "height": height, "seed": seed}
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if model.endswith("flux-1-schnell"):
            payload["num_steps"] = 4
        elif model.endswith("phoenix-1.0"):
            payload.update({"num_steps": 20, "guidance": 4})
        elif model.endswith("lucid-origin"):
            payload.update({"num_steps": 24, "guidance": 4.5})
        return self._request(model, payload)

    def text(self, model: str, messages: list[Dict[str, str]], *, max_tokens: int = 700) -> str:
        if not self.configured():
            raise ArtProviderError(self.name, "Cloudflare Workers AI is not configured")
        account = str(os.environ.get("VERIDEX_CLOUDFLARE_ACCOUNT_ID") or "").strip()
        token = str(os.environ.get("VERIDEX_CLOUDFLARE_API_TOKEN") or "").strip()
        request = Request(
            f"https://api.cloudflare.com/client/v4/accounts/{quote(account)}/ai/run/{model}",
            data=json.dumps({"messages": messages, "max_tokens": max_tokens}).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            content, _ = _http_request(request, timeout=60)
            payload = json.loads(content.decode("utf-8"))
            result = payload.get("result", payload)
            if isinstance(result, dict) and result.get("response"):
                return str(result["response"]).strip()
            choices = result.get("choices") if isinstance(result, dict) else None
            if isinstance(choices, list) and choices:
                return str((choices[0].get("message") or {}).get("content") or "").strip()
            raise ArtProviderError(self.name, "Art Director returned no text")
        except ArtProviderError as exc:
            exc.provider = self.name
            raise

    def vision(self, image_content: bytes, question: str) -> str:
        if not self.configured():
            raise ArtProviderError(self.name, "Cloudflare Workers AI is not configured")
        account = str(os.environ.get("VERIDEX_CLOUDFLARE_ACCOUNT_ID") or "").strip()
        token = str(os.environ.get("VERIDEX_CLOUDFLARE_API_TOKEN") or "").strip()
        data_uri = "data:image/png;base64," + base64.b64encode(image_content).decode("ascii")
        request = Request(
            f"https://api.cloudflare.com/client/v4/accounts/{quote(account)}/ai/run/@cf/moondream/moondream3.1-9B-A2B",
            data=json.dumps({"task": "query", "image": data_uri, "question": question}).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            content, _ = _http_request(request, timeout=60)
            payload = json.loads(content.decode("utf-8"))
            result = payload.get("result", payload)
            return str((result or {}).get("answer") or (result or {}).get("response") or "").strip()
        except ArtProviderError as exc:
            exc.provider = self.name
            raise


class PollinationsArtProvider:
    name = "pollinations"

    @staticmethod
    def configured() -> bool:
        return bool(os.environ.get("VERIDEX_POLLINATIONS_API_KEY"))

    def balance(self) -> float | None:
        if not self.configured():
            return None
        request = Request(
            "https://gen.pollinations.ai/account/balance",
            headers={"Authorization": f"Bearer {str(os.environ.get('VERIDEX_POLLINATIONS_API_KEY') or '').strip()}"},
        )
        try:
            content, _ = _http_request(request, timeout=8)
            return float(json.loads(content.decode("utf-8")).get("balance"))
        except Exception:
            return None

    def generate(self, prompt: str, model: str, width: int, height: int, seed: int, references: list[Dict[str, Any]]) -> bytes:
        if references:
            raise ArtProviderError(self.name, "Free Pollinations fallback does not support reference editing")
        if not self.configured():
            raise ArtProviderError(self.name, "Pollinations is not configured")
        if model not in FREE_POLLINATIONS_MODELS:
            raise ArtProviderError(self.name, "Paid or unapproved Pollinations model blocked")
        query = urlencode({"model": model, "width": width, "height": height, "seed": seed})
        request = Request(
            f"https://gen.pollinations.ai/image/{quote(prompt, safe='')}?{query}",
            headers={"Authorization": f"Bearer {str(os.environ.get('VERIDEX_POLLINATIONS_API_KEY') or '').strip()}"},
        )
        try:
            content, content_type = _http_request(request)
            if not content_type.lower().startswith("image/"):
                raise ArtProviderError(self.name, "Pollinations did not return an image")
            return content
        except ArtProviderError as exc:
            exc.provider = self.name
            raise


class LocalFinishPlugin:
    @staticmethod
    def capabilities() -> Dict[str, Any]:
        background = importlib.util.find_spec("rembg") is not None
        executable = Path(str(os.environ.get("VERIDEX_REALESRGAN_PATH") or ""))
        return {
            "resize": True,
            "crop": True,
            "convert": True,
            "add_text": True,
            "collage": True,
            "remove_background": background,
            "realesrgan": executable.is_file(),
        }

    @staticmethod
    def _open(row: Dict[str, Any]) -> Image.Image:
        validate_image_bytes(bytes(row["content"]))
        image = Image.open(io.BytesIO(bytes(row["content"])))
        image.load()
        return ImageOps.exif_transpose(image)

    @staticmethod
    def _encode(image: Image.Image, output_format: str = "PNG", quality: int = 92) -> tuple[bytes, str, str]:
        normalized = output_format.upper()
        if normalized not in ALLOWED_FORMATS:
            raise ValueError("Output format must be PNG, JPEG, or WEBP")
        if normalized == "JPEG" and image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image.convert("RGB"))
            image = background
        output = io.BytesIO()
        image.save(output, format=normalized, quality=max(40, min(100, int(quality))), optimize=True)
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[normalized]
        content_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[normalized]
        return output.getvalue(), extension, content_type

    def apply(self, operation: str, sources: list[Dict[str, Any]], options: Dict[str, Any]) -> Dict[str, Any]:
        if not sources:
            raise ValueError("Choose at least one source image")
        image = self._open(sources[0])
        output_format = str(options.get("format") or "PNG").upper()
        if operation == "remove_background":
            try:
                from rembg import remove
            except ImportError as exc:
                raise ValueError("Background removal is not installed; run scripts/setup.ps1") from exc
            content = remove(bytes(sources[0]["content"]))
            facts = validate_image_bytes(content)
            return {"content": content, "extension": ".png", "content_type": facts["content_type"], "operation": operation, "model": "rembg"}
        if operation == "resize" or operation == "upscale":
            if operation == "upscale":
                scale = max(2, min(4, int(options.get("scale") or 2)))
                executable = Path(str(os.environ.get("VERIDEX_REALESRGAN_PATH") or ""))
                if executable.is_file() and options.get("enhance", True):
                    with tempfile.TemporaryDirectory(prefix="veridex-upscale-") as temporary:
                        source_path = Path(temporary) / "source.png"
                        output_path = Path(temporary) / "upscaled.png"
                        source_path.write_bytes(bytes(sources[0]["content"]))
                        completed = subprocess.run(
                            [str(executable), "-i", str(source_path), "-o", str(output_path), "-s", str(scale)],
                            capture_output=True,
                            timeout=240,
                            check=False,
                        )
                        if completed.returncode == 0 and output_path.is_file():
                            content = output_path.read_bytes()
                            facts = validate_image_bytes(content)
                            return {"content": content, "extension": ".png", "content_type": facts["content_type"], "operation": operation, "model": "realesrgan"}
                width, height = image.width * scale, image.height * scale
            else:
                width = max(64, min(5000, int(options.get("width") or image.width)))
                height = max(64, min(5000, int(options.get("height") or image.height)))
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Requested dimensions exceed 25 megapixels")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        elif operation == "crop":
            left = max(0, int(options.get("left") or 0))
            top = max(0, int(options.get("top") or 0))
            right = min(image.width, int(options.get("right") or image.width))
            bottom = min(image.height, int(options.get("bottom") or image.height))
            if right <= left or bottom <= top:
                raise ValueError("Crop bounds are invalid")
            image = image.crop((left, top, right, bottom))
        elif operation == "add_text":
            text = str(options.get("text") or "").strip()
            if not text:
                raise ValueError("Text is required")
            image = image.convert("RGBA")
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            size = max(14, min(240, int(options.get("font_size") or max(24, image.width // 18))))
            try:
                font = ImageFont.truetype("arial.ttf", size)
            except OSError:
                font = ImageFont.load_default()
            margin = max(12, image.width // 30)
            bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=6)
            x = margin
            y = image.height - (bbox[3] - bbox[1]) - margin
            draw.rounded_rectangle((x - 10, y - 8, min(image.width - margin, x + bbox[2] + 10), y + bbox[3] + 8), radius=8, fill=(0, 0, 0, 150))
            draw.multiline_text((x, y), text, font=font, fill=str(options.get("color") or "white"), spacing=6)
            image = Image.alpha_composite(image, overlay)
        elif operation == "collage":
            images = [self._open(row).convert("RGB") for row in sources[:4]]
            cell_w = max(image.width for image in images)
            cell_h = max(image.height for image in images)
            cols = 2 if len(images) > 1 else 1
            rows = (len(images) + cols - 1) // cols
            canvas = Image.new("RGB", (cell_w * cols, cell_h * rows), str(options.get("background") or "white"))
            for index, item in enumerate(images):
                fitted = ImageOps.contain(item, (cell_w, cell_h), Image.Resampling.LANCZOS)
                x = (index % cols) * cell_w + (cell_w - fitted.width) // 2
                y = (index // cols) * cell_h + (cell_h - fitted.height) // 2
                canvas.paste(fitted, (x, y))
            image = canvas
        elif operation != "convert":
            raise ValueError("Unknown local finishing operation")
        content, extension, content_type = self._encode(image, output_format, int(options.get("quality") or 92))
        return {"content": content, "extension": extension, "content_type": content_type, "operation": operation, "model": "pillow"}


class ArtStudio:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).resolve()
        self.cloudflare = CloudflareArtProvider()
        self.pollinations = PollinationsArtProvider()
        self.local = LocalFinishPlugin()

    def studio_dir(self, workspace_id: str) -> Path:
        return self.data_root / "workspaces" / str(workspace_id) / "art_studio"

    def list_projects(self, workspace_id: str) -> list[Dict[str, Any]]:
        rows = _read_json(self.studio_dir(workspace_id) / "projects.json", [])
        return sorted((row for row in rows if isinstance(row, dict)), key=lambda row: str(row.get("updated_at") or ""), reverse=True)

    def save_project(self, workspace_id: str, project: Dict[str, Any]) -> Dict[str, Any]:
        rows = self.list_projects(workspace_id)
        project_id = str(project.get("project_id") or f"art_{uuid.uuid4().hex[:12]}")
        prior = next((row for row in rows if row.get("project_id") == project_id), {})
        version = int(prior.get("version") or 0) + 1
        saved = {
            "project_id": project_id,
            "version": version,
            "name": str(project.get("name") or "Untitled art project").strip()[:160],
            "prompt": str(project.get("prompt") or "")[:32_000],
            "preset_id": str(project.get("preset_id") or "photography"),
            "model_id": str(project.get("model_id") or "auto"),
            "aspect": str(project.get("aspect") or "square"),
            "selected_file_id": str(project.get("selected_file_id") or ""),
            "file_ids": [str(value) for value in project.get("file_ids", []) if str(value)][:100],
            "created_at": str(prior.get("created_at") or utc_now()),
            "updated_at": utc_now(),
        }
        rows = [row for row in rows if row.get("project_id") != project_id]
        rows.append(saved)
        _atomic_json(self.studio_dir(workspace_id) / "projects.json", rows)
        versions = self.studio_dir(workspace_id) / "versions"
        _atomic_json(versions / f"{_safe_name(project_id)}-v{version}.json", saved)
        return saved

    def bootstrap(self, workspace_id: str) -> Dict[str, Any]:
        balance = self.pollinations.balance() if self.pollinations.configured() else None
        return {
            "providers": [
                {"id": "cloudflare", "name": "Cloudflare Free", "configured": self.cloudflare.configured(), "free_only": True, "quota_label": "10,000 neurons/day; hard stop"},
                {"id": "pollinations", "name": "Pollinations fallback", "configured": self.pollinations.configured(), "free_only": True, "balance": balance, "quota_label": "Free Pollen only"},
                {"id": "local", "name": "Local finishing", "configured": True, "free_only": True, "capabilities": self.local.capabilities()},
            ],
            "models": ART_MODELS,
            "presets": ART_PRESETS,
            "aspects": [{"id": key, "width": value[0], "height": value[1]} for key, value in ASPECT_SIZES.items()],
            "projects": self.list_projects(workspace_id),
        }

    @staticmethod
    def expanded_prompt(prompt: str, preset_id: str) -> str:
        preset = next((row for row in ART_PRESETS if row["id"] == preset_id), ART_PRESETS[0])
        return f"{str(prompt or '').strip()}. {preset['suffix']}".strip(". ")

    def improve_prompt(self, prompt: str, preset_id: str) -> str:
        if not str(prompt or "").strip():
            raise ValueError("Describe the image first")
        return self.cloudflare.text(
            "@cf/zai-org/glm-4.7-flash",
            [
                {"role": "system", "content": "You are an art director. Rewrite the request as one precise image-generation prompt. Preserve every requested subject and constraint. Add composition, lighting, material, palette, and camera or medium detail. Do not name living artists. Return only the prompt."},
                {"role": "user", "content": self.expanded_prompt(prompt, preset_id)},
            ],
            max_tokens=500,
        )

    def critique(self, source: Dict[str, Any]) -> str:
        return self.cloudflare.vision(
            bytes(source["content"]),
            "Act as a concise art director. Evaluate composition, hierarchy, lighting/color, legibility, anatomy or object defects, and suitability for professional use. Give the three most useful improvements. Do not speculate about identity.",
        )

    def generate(self, payload: Dict[str, Any], references: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Describe the image to create")
        preset_id = str(payload.get("preset_id") or "photography")
        prompt = self.expanded_prompt(prompt, preset_id)
        if payload.get("improve_prompt"):
            prompt = self.improve_prompt(prompt, preset_id)
        aspect = str(payload.get("aspect") or "square")
        width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["square"])
        width = max(256, min(1920, int(payload.get("width") or width)))
        height = max(256, min(1920, int(payload.get("height") or height)))
        if width * height > MAX_IMAGE_PIXELS:
            raise ValueError("Requested dimensions exceed 25 megapixels")
        variants = max(1, min(4, int(payload.get("variants") or 1)))
        base_seed = max(0, int(payload.get("seed") or 0)) or int(uuid.uuid4().hex[:8], 16)
        model_id = str(payload.get("model_id") or "auto")
        operation = str(payload.get("operation") or "generate")
        if model_id == "auto":
            model_id = "edit" if references or operation == "edit" else ("text" if preset_id in {"poster", "icon"} else "fast")
        model = next((row for row in ART_MODELS if row["id"] == model_id), None)
        if not model:
            raise ValueError("Unknown art model")
        results: list[Dict[str, Any]] = []
        for index in range(variants):
            seed = base_seed + index
            provider = str(model["provider"])
            remote_model = str(model.get("remote_id") or "")
            attempts: list[str] = []
            try:
                if provider == "pollinations":
                    content = self.pollinations.generate(prompt, remote_model, width, height, seed, references)
                else:
                    content = self.cloudflare.generate(prompt, remote_model, width, height, seed, str(payload.get("negative_prompt") or ""), references)
                    provider = "cloudflare"
            except ArtProviderError as primary:
                attempts.append(f"{primary.provider}: {primary}")
                if provider != "pollinations" and not references and (primary.retryable or primary.quota or not self.cloudflare.configured()):
                    fallback_model = "zimage" if preset_id not in {"poster", "icon"} else "flux"
                    try:
                        content = self.pollinations.generate(prompt, fallback_model, width, height, seed, [])
                        provider, remote_model = "pollinations", fallback_model
                    except ArtProviderError as fallback:
                        attempts.append(f"{fallback.provider}: {fallback}")
                        raise ArtProviderError("auto", "; ".join(attempts)) from fallback
                else:
                    raise
            facts = validate_image_bytes(content)
            extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[facts["format"]]
            results.append({
                "content": content,
                "extension": extension,
                "content_type": facts["content_type"],
                "metadata": {
                    "provider": provider,
                    "model": remote_model,
                    "operation": operation,
                    "seed": seed,
                    "prompt": prompt,
                    "preset_id": preset_id,
                    "width": facts["width"],
                    "height": facts["height"],
                    "parent_file_ids": [str(row.get("file_id") or "") for row in references],
                },
            })
        return results


class ArtJobManager:
    def __init__(self, workers: int = 2, prefix: str = "artjob", label: str = "Art Studio"):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._futures: Dict[str, Future[Any]] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()
        self._prefix = re.sub(r"[^A-Za-z0-9_-]+", "", prefix) or "job"
        self._label = str(label or "Job")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"veridex-{self._prefix}")

    def submit(self, payload: Dict[str, Any], runner: Callable[[str, Callable[[int, str], None], Callable[[], bool]], Dict[str, Any]]) -> Dict[str, Any]:
        job_id = f"{self._prefix}_{uuid.uuid4().hex[:16]}"
        now = utc_now()
        with self._lock:
            self._jobs[job_id] = {"job_id": job_id, "status": "queued", "progress": 0, "message": "Queued", "created_at": now, "updated_at": now, "operation": str(payload.get("operation") or "generate")}

        def progress(value: int, message: str) -> None:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id].update({"progress": max(0, min(100, int(value))), "message": str(message), "updated_at": utc_now()})

        def cancelled() -> bool:
            with self._lock:
                return job_id in self._cancelled

        def work() -> None:
            progress(5, "Starting")
            with self._lock:
                self._jobs[job_id]["status"] = "running"
            try:
                result = runner(job_id, progress, cancelled)
                with self._lock:
                    if cancelled():
                        self._jobs[job_id].update({"status": "canceled", "progress": 100, "message": "Canceled", "updated_at": utc_now()})
                    else:
                        self._jobs[job_id].update({"status": "completed", "progress": 100, "message": "Complete", "result": result, "updated_at": utc_now()})
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id].update({"status": "canceled" if cancelled() else "failed", "progress": 100, "message": "Canceled" if cancelled() else str(exc), "error": "" if cancelled() else str(exc), "updated_at": utc_now()})

        future = self._executor.submit(work)
        with self._lock:
            self._futures[job_id] = future
        return self.get(job_id)

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown {self._label} job")
            return dict(self._jobs[job_id])

    def wait(self, job_id: str, timeout: float | None = None) -> Dict[str, Any]:
        """Wait for one known job without timing-sensitive polling."""
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown {self._label} job")
            future = self._futures.get(job_id)
        if future is None:
            return self.get(job_id)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            pass
        return self.get(job_id)

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown {self._label} job")
            if self._jobs[job_id].get("status") in {"completed", "failed", "canceled"}:
                return dict(self._jobs[job_id])
            self._cancelled.add(job_id)
            self._jobs[job_id].update({"status": "canceling", "message": "Canceling", "updated_at": utc_now()})
            return dict(self._jobs[job_id])
