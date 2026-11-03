"""Local, source-preserving image previews and explicit artifact handoffs."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageOps

from photo_adjustments import adjust_image
from veridex_rooms import room_by_id

ADJUSTMENTS = ('exposure', 'brightness', 'highlights', 'shadows', 'contrast',
               'saturation', 'warmth', 'definition', 'sharpness')
MAX_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 40_000_000
_BACKGROUND_LOCK = threading.Lock()
_BACKGROUND_SESSION = None


def background_mask(image):
    """Infer only an alpha mask locally; preserve the source RGB pixels."""
    global _BACKGROUND_SESSION
    with _BACKGROUND_LOCK:
        if _BACKGROUND_SESSION is None:
            model = Path(os.path.expanduser(os.getenv('U2NET_HOME', os.path.join(os.getenv('XDG_DATA_HOME', '~'), '.u2net')))) / 'u2net.onnx'
            if not model.is_file():
                raise ValueError('The local background-removal model is missing; run .venv/Scripts/python.exe scripts/prepare_background_removal.py on the Veridex computer')
            # Fail locally on a damaged model instead of silently downloading during editing.
            if hashlib.md5(model.read_bytes()).hexdigest() != '60024c5c889badc19c04ad937298a77b':
                raise ValueError('The local background-removal model failed verification; prepare it again')
        try:
            from rembg import new_session, remove
        except ImportError:
            raise ValueError('Local background removal is not installed; run scripts/setup.ps1') from None
        if _BACKGROUND_SESSION is None:
            _BACKGROUND_SESSION = new_session('u2net', providers=['CPUExecutionProvider'])
        mask = remove(image, session=_BACKGROUND_SESSION, only_mask=True)
        if not isinstance(mask, Image.Image) or mask.size != image.size:
            raise ValueError('Background removal returned an invalid mask; keep the original')
        return mask.convert('L')


def recipe(value):
    if not isinstance(value, dict) or set(value) - {'auto', 'adjustments', 'crop', 'rotation', 'remove_background'}:
        raise ValueError('Invalid image adjustments')
    if type(value.get('auto', False)) is not bool:
        raise ValueError('Automatic adjustment must be on or off')
    if type(value.get('remove_background', False)) is not bool:
        raise ValueError('Background removal must be on or off')
    settings = value.get('adjustments', {})
    if not isinstance(settings, dict) or set(settings) - set(ADJUSTMENTS):
        raise ValueError('Unknown image adjustment')
    result = {'auto': value.get('auto', False), 'remove_background': value.get('remove_background', False), 'adjustments': {}}
    for key, number in settings.items():
        if type(number) not in (int, float) or not math.isfinite(number) or not -100 <= number <= 100:
            raise ValueError(f'{key} must be between -100 and 100')
        if number:
            result['adjustments'][key] = number
    rotation = value.get('rotation', 0)
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError('Rotate in quarter turns')
    result['rotation'] = rotation
    crop = value.get('crop')
    if crop is not None:
        keys = ('left_percent', 'top_percent', 'right_percent', 'bottom_percent')
        if not isinstance(crop, dict) or set(crop) != set(keys):
            raise ValueError('Specify all four crop edges')
        if any(type(crop[key]) not in (int, float) or not math.isfinite(crop[key]) or not 0 <= crop[key] <= 100 for key in keys):
            raise ValueError('Crop edges must be percentages between 0 and 100')
        if crop['left_percent'] >= crop['right_percent'] or crop['top_percent'] >= crop['bottom_percent']:
            raise ValueError('Keep a nonempty crop')
        result['crop'] = dict(crop)
    return result


def render(content, options):
    options = recipe(options)
    with Image.open(io.BytesIO(content)) as opened:
        if opened.format not in {'JPEG', 'PNG', 'WEBP'} or getattr(opened, 'n_frames', 1) != 1:
            raise ValueError('Editing supports static JPEG, PNG, and WebP images')
        if opened.width * opened.height > MAX_PIXELS:
            raise ValueError('This image is too large to edit (40 megapixel limit)')
        image = ImageOps.exif_transpose(opened)
        image.load()
        alpha = image.convert('RGBA').getchannel('A') if 'A' in image.getbands() or 'transparency' in image.info else None
        profile = opened.info.get('icc_profile')
        if profile:
            try:
                image = ImageCms.profileToProfile(image.convert('RGB'), ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile('sRGB'), outputMode='RGB')
            except (ImageCms.PyCMSError, OSError, ValueError):
                raise ValueError('The color profile could not be converted; keep the original') from None
        else:
            image = image.convert('RGB')
        if options['remove_background']:
            mask = background_mask(image)
            alpha = ImageChops.multiply(alpha, mask) if alpha is not None else mask
        if options['auto']:
            image, _ = adjust_image(image, 'auto_adjust', {})
        image, _ = adjust_image(image, 'adjust', options['adjustments'])
        if alpha is not None:
            image.putalpha(alpha)
        if options.get('crop'):
            image, _ = adjust_image(image, 'crop', options['crop'])
        if options['rotation']:
            image = image.rotate(-options['rotation'], expand=True)
        output = io.BytesIO()
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        image.save(output, format='PNG', icc_profile=profile)
        return output.getvalue()


class ImagePreview:
    def __init__(self, store, verify):
        self.store, self.verify = store, verify

    def context(self, value):
        ws, session = str(value.get('workspace_id', '')), str(value.get('session_id', ''))
        if self.store.get_workspace(ws).get('workspace_id') != ws:
            raise ValueError('Invalid source workspace')
        current = self.store.find_session(session)
        if current['session_id'] != session or current['workspace_id'] != ws or current['active_room'] != value.get('room_id'):
            raise ValueError('The workspace or active room changed; reopen the image')
        return ws, session

    def source(self, value):
        ws, session = self.context(value)
        library = value.get('library')
        if library == 'session':
            rows = self.store.list_files(ws, session)
        elif library == 'room' and value['room_id'] != 'lobby':
            rows = self.store.list_room_files(ws, value['room_id'])
        else:
            raise ValueError('Choose a session or room image')
        row = next((row for row in rows if row['file_id'] == value.get('file_id')), None)
        if not row or not str(row.get('content_type', '')).startswith('image/'):
            raise ValueError('The image is unavailable in this library')
        if row.get('sha256') != value.get('sha256'):
            raise ValueError('The source image changed; reopen it')
        self.verify(ws, [row])
        if row['size'] > MAX_BYTES:
            raise ValueError('This image is too large to edit or send (50 MB limit)')
        return row

    def preview(self, value):
        row = self.source(value)
        return render(self.content(row), value.get('recipe', {}))

    @staticmethod
    def content(row):
        content = Path(row['path']).read_bytes()
        if len(content) != row['size'] or hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('The source image changed while reading; reopen it')
        return content

    def _signature(self, value):
        key = str(value.get('request_id', ''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', key):
            raise ValueError('A request ID is required')
        fingerprint = {k: v for k, v in value.items() if k != 'request_id'}
        return key, hashlib.sha256(json.dumps(fingerprint, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _existing(self, ws, key, signature):
        for row in self.store.list_artifact_ledger(ws):
            record = row.get('metadata', {}).get('image_preview', {})
            if record.get('request_id') == key:
                if record.get('signature') != signature:
                    raise ValueError('This request ID was already used for another image action')
                self.verify(ws, [row])
                return row

    def save(self, value):
        if value.get('confirm') is not True:
            raise ValueError('Confirm Save copy')
        key, signature = self._signature(value)
        row = self.source(value)
        ws, session = self.context(value)
        with self.store._lock:
            existing = self._existing(ws, key, signature)
            if existing:
                return existing
            output = self.preview(value)
            # Recheck room and source after processing, before persisting anything.
            self.source(value)
            name = (Path(row['name']).stem[:100] or 'image') + '--edited.png'
            saved = self.store.save_file(ws, session, name, output, 'image/png', source='local_image_edit',
                kind='generated_image', scope='room', scope_ref=value['room_id'], expected_room=value['room_id'],
                metadata={'image_preview': {'request_id': key, 'signature': signature,
                    'source_file_id': row['file_id'], 'source_workspace_id': ws,
                    'source_sha256': row['sha256'], 'recipe': recipe(value.get('recipe', {}))}})
            self.verify(ws, [saved])
            return saved

    def send(self, value):
        if value.get('confirm') is not True:
            raise ValueError('Confirm Send to room')
        key, signature = self._signature(value)
        row = self.source(value)
        target_ws, target_room = str(value.get('target_workspace_id', '')), str(value.get('target_room_id', ''))
        if self.store.get_workspace(target_ws).get('workspace_id') != target_ws:
            raise ValueError('Invalid destination workspace')
        room = room_by_id(target_room)
        if not room or room['id'] != target_room or room.get('is_active') is False or target_room == 'lobby':
            raise ValueError('Choose an available destination room')
        with self.store._lock:
            existing = self._existing(target_ws, key, signature)
            if existing:
                return existing
            content = self.content(row)
            # Copies keep their exact original bytes; validate the image without transforming it.
            with Image.open(io.BytesIO(content)) as opened:
                if opened.format not in {'JPEG', 'PNG', 'WEBP'} or getattr(opened, 'n_frames', 1) != 1:
                    raise ValueError('Send supports static JPEG, PNG, and WebP images')
                opened.verify()
            self.source(value)
            saved = self.store.save_file(target_ws, '', row['name'], content, row['content_type'],
                source='room_image_copy', kind='generated_image', scope='room', scope_ref=target_room, room_only=True,
                metadata={'image_preview': {'request_id': key, 'signature': signature,
                    'source_workspace_id': value['workspace_id'], 'source_room_id': value['room_id'],
                    'source_file_id': row['file_id'], 'source_sha256': row['sha256']}})
            self.verify(target_ws, [saved])
            return saved
