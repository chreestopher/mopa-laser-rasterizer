"""Build the unpacked browser-extension download from repository source."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

SOURCE = Path(__file__).resolve().parent / 'lightburn-extension-poc'

def build_archive(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
    required = [manifest['background']['service_worker'], 'console.html']
    required += [file for script in manifest['content_scripts'] for file in script['js']]
    for file in required:
        if not (SOURCE / file).is_file():
            raise ValueError(f'Missing extension file: {file}')
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as archive:
        for file in sorted(SOURCE.iterdir()):
            if not file.is_file() or file.suffix not in {'.js', '.css', '.html', '.json', '.md'}:
                continue
            info = ZipInfo('mopa-lightburn-extension-beta/' + file.name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, file.read_bytes())
    return destination

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    build_archive(parser.parse_args().output)
