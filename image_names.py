"""Image presentation names, independent of immutable artifact storage paths."""
import re


def image_name(value, extension='.png', fallback='image', index=1, count=1):
    value = str(value or fallback).strip()
    if not value or len(value) > 120 or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError('Use an image name of at most 120 characters without path or filename symbols')
    if value in {'.','..'} or value.endswith(('.', ' ')):
        raise ValueError('Choose a valid image name')
    stem = re.sub(r'\.(png|jpe?g|webp|gif)$', '', value, flags=re.I)
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', stem, re.I):
        raise ValueError('That image name is reserved by Windows')
    suffix = f'_{index:02d}' if count > 1 else ''
    extension = str(extension).lower()
    if extension not in {'.png','.jpg','.jpeg','.webp','.gif'}:
        raise ValueError('Unsupported image extension')
    return f'{stem}{suffix}{extension}'
