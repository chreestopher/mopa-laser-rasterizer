"""Build the unpacked browser-extension download from repository source."""
import argparse
import json
import html
from urllib.parse import urlsplit
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

SOURCE = Path(__file__).resolve().parent / 'lightburn-extension-poc'

STAGING_ORIGIN = 'https://serverless-staging.mopa-laser-rasterizer.com'

def target(origin, environment):
    origin = origin.rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Extension target must be an HTTPS origin without a path or credentials')
    if environment not in {'staging', 'production'}:
        raise ValueError('Unknown deployment environment')
    name = 'MOPA LightBurn Extension' + (' - Development' if environment == 'staging' else ' - Beta')
    return origin, name

def build_guide(origin, environment):
    origin, name = target(origin, environment)
    source = (SOURCE.parents[1] / 'serverless_web/lightburn-extension.html').read_text(encoding='utf-8')
    source = source.replace(STAGING_ORIGIN, html.escape(origin, quote=True))
    source = source.replace('MOPA Rasterizer \u2014 LightBurn Connection POC', name)
    if environment == 'production':
        source = source.replace('staging Rasterizer website', 'Rasterizer website')
        source = source.replace(' It does not currently enable integration on the production website. You need access to staging and a Rasterizer account', ' You need a Rasterizer account')
        source = source.replace('the staging Vault', 'the Vault').replace('staging Swatch', 'Swatch').replace('staging Job', 'Job').replace('on staging,', 'on this website,')
    return source

def build_archive(destination, origin=STAGING_ORIGIN, environment='staging'):
    origin, name = target(origin, environment)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
    manifest['name'] = name
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
            content = json.dumps(manifest, ensure_ascii=False, indent=2) if file.name == 'manifest.json' else file.read_text(encoding='utf-8')
            content = content.replace(STAGING_ORIGIN, origin)
            archive.writestr(info, content.encode('utf-8'))
    return destination

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--environment', required=True, choices=['staging', 'production'])
    parser.add_argument('--guide-output', type=Path)
    args = parser.parse_args()
    build_archive(args.output, args.origin, args.environment)
    if args.guide_output:
        args.guide_output.write_text(build_guide(args.origin, args.environment), encoding='utf-8')
