"""Download and verify rembg's free U2NET model for local CPU inference."""
import hashlib
import os
from pathlib import Path

import pooch


def main():
    path = Path(pooch.retrieve(
        'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx',
        known_hash='md5:60024c5c889badc19c04ad937298a77b', fname='u2net.onnx',
        path=os.path.expanduser(os.getenv('U2NET_HOME', os.path.join(os.getenv('XDG_DATA_HOME', '~'), '.u2net'))),
        downloader=pooch.HTTPDownloader(progressbar=False, timeout=30)))
    print('Local background-removal model ready:', path)
    print('Bytes:', path.stat().st_size)
    print('SHA-256:', hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
