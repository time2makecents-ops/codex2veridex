"""Bounded local-media transfer helpers; authorization belongs to the caller."""
import mmap
import re
import tempfile


def byte_range(header, size):
    if not header: return 0, size - 1
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
    if not match or not any(match.groups()) or size <= 0: raise ValueError('Unsatisfiable range')
    first, last = match.groups()
    if not first:
        if int(last) <= 0: raise ValueError('Unsatisfiable range')
        return max(0, size - int(last)), size - 1
    start, end = int(first), min(int(last) if last else size - 1, size - 1)
    if start >= size or end < start: raise ValueError('Unsatisfiable range')
    return start, end


def receive_upload(stream, length, maximum, save):
    if length <= 0 or length > maximum: raise ValueError('Video room upload exceeds the configured limit or is empty')
    with tempfile.TemporaryFile() as temporary:
        remaining = length
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            if not block: raise ValueError('Upload interrupted; no file registered')
            temporary.write(block); remaining -= len(block)
        temporary.flush()
        with mmap.mmap(temporary.fileno(), 0, access=mmap.ACCESS_READ) as content:
            return save(content)
