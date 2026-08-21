# MOPA Laser Rasterizer

MOPA Laser Rasterizer is a Flask web application that converts raster artwork into color-separated vector geometry for laser engraving. It exports a layered SVG and, when supplied with a compatible LightBurn Material Library, a `.lbrn2` project containing the operator's matched settings.

The vector pipeline gives each processed color its own closed region. Adjacent regions are fitted together and removed from the geometry around them, avoiding unintended gaps and stacked overlaps between color layers.

The application prepares artwork and project files; it does not control a laser or determine safe engraving parameters. Every generated project and Material Library setting must be reviewed and tested by the operator.

## Features

- Raster-to-vector conversion for JPG, JPEG, PNG, BMP, TIFF, and WebP artwork
- Layered SVG output with no Material Library required
- LightBurn `.lbrn2` export using settings from `.clb`, `.lbmat`, or compatible `.lbrn` files
- Editable palette selection and Material Library description matching
- Cartoon, Color Photo, and dithered Black and White Photo presets
- Abstract vector filters with configurable controls
- Material Vault for importing, editing, combining, and exporting saved libraries
- Hatch Palettes that clone a base Fill or Offset Fill setting across LightBurn swatches and plan per-layer hatch angles and line intervals
- Labeled LightBurn material-coupon generation
- Color Discovery calibration, photo analysis, and recipe saving
- Browser-session and account-backed job history
- Community settings browser
- Experimental Holographic Etching Lab for diffraction-grid calibration and artwork generation
- Public user documentation at `/docs`

## Rasterizer workflow

1. Develop and verify color settings on the actual machine, lens, material, finish, and focus arrangement.
2. Store the settings in a LightBurn Material Library. Setting descriptions should match Rasterizer palette names; palette labels can also be edited in the UI to match an existing library.
3. Upload artwork and optionally select or upload the Material Library.
4. Choose the material, processing dimensions, physical pixel size, palette, and image preset.
5. Build the project and download the SVG or `.lbrn2` output.
6. Inspect the scale, geometry, layers, cut modes, and every laser parameter in LightBurn before testing on expendable stock.

Leaving the material blank and confirming SVG-only mode skips Material Library parsing and `.lbrn2` generation. The resulting SVG contains vector geometry but no machine settings.

## Local development

### Requirements

- Ubuntu WSL
- Python 3.11 or newer
- Redis when exercising queued jobs or Redis-backed production behavior

The Docker image installs the required Debian packages: `build-essential`, `libpotrace-dev`, `libagg-dev`, `pkg-config`, and `python3-dev`.

### Run the web application

From the repository root inside Ubuntu WSL, install the native packages,
create `.venv`, and install the application and test dependencies:

```bash
bash dev_setup/setup-wsl.sh
```

Activate the environment in each new WSL shell:

```bash
source .venv/bin/activate
```

Start Flask:

```bash
python app.py
```

Open `http://localhost:8000`.

Local submissions run in background threads by default. Set `RASTER_JOB_QUEUE_ENABLED=true` and run `python worker.py` separately to use the Redis-backed worker path.

Run the rasterizer command-line application through the WSL environment with:

```bash
bash run-cli.sh INPUT OUTPUT_BASE PIXEL_MM WIDTH HEIGHT MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER
```

Optional filter JSON, palette-name JSON, and SVG-only arguments are forwarded
to `lib/Material_Library.py`. For example:

```bash
bash run-cli.sh input.png output/job 0.125 800 0 settings.clb "colors - stainless steel" "Red,Blue,Green" cartoon none '{}' '{}' false
```

For the repository's hardcoded sample configuration, place `test-input.png`
and `tests.clb` in the repository root, then run:

```bash
bash run-sample.sh
```

The sample uses all 30 default swatches, the `colors - stainless steel`
material, an 800-pixel target width, 0.125 mm pixel size, Cartoon processing,
and a minimum island area of 50. Output is written under
`uploads/cli-sample/`.

### Run with Docker

```bash
docker build -t mopa-laser-rasterizer .
docker run --rm -p 8000:8000 mopa-laser-rasterizer
```

The production container starts Gunicorn with one process and four threads so the process-local task cache remains shared.

## Configuration

The application reads configuration from environment variables. It does not automatically load `.env` files.

| Variable | Default | Purpose |
| --- | --- | --- |
| `UPLOAD_FOLDER` | `./uploads` | Node-local job and artifact storage |
| `APP_SESSION_SECRET` | Development-only value | Signs Flask and anonymous browser sessions; replace in production |
| `SESSION_COOKIE_SECURE` | `false` | Restricts session cookies to HTTPS when `true` |
| `PUBLIC_APP_URL` | Request origin | Canonical public URL used by documentation and metadata |
| `DAILY_JOB_LIMIT` | `3` | Anonymous daily Rasterizer job allowance |
| `RASTER_JOB_QUEUE_ENABLED` | `false` | Sends Rasterizer work to the Redis queue when `true` |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `AWS_REGION` | `us-east-2` | AWS region for S3 and DynamoDB clients |
| `S3_BUCKET_NAME` | empty | Durable job input and output bucket |
| `DYNAMODB_TABLE_NAME` | empty | Account, job, library, and recipe data table |
| `COGNITO_DOMAIN` | empty | Cognito sign-in domain |
| `COGNITO_CLIENT_ID` | empty | Cognito application client ID |
| `COMMUNITY_CONTRIBUTOR_SECRET` | Session secret | Signs community-contributor operations |

Worker lease and recovery timing can be tuned with `RASTER_JOB_LEASE_SECONDS`, `RASTER_JOB_HEARTBEAT_SECONDS`, `RASTER_JOB_RECOVERY_INTERVAL_SECONDS`, and `RASTER_JOB_RECOVERY_LOCK_SECONDS`.

Production infrastructure and deployment instructions are maintained in [README-K8S.md](README-K8S.md).

## Project structure

```text
mopa-laser-rasterizer/
|-- app.py                    Flask application factory and local server
|-- services.py               Shared storage, queue, session, and job services
|-- worker.py                 Redis-backed raster job worker
|-- routes/                   HTTP routes grouped by application area
|-- lib/
|   |-- vector_processing.py  Raster quantization and vector geometry pipeline
|   |-- Material_Library.py   Raster job entry point and library integration
|   |-- lightburn.py          LightBurn library and project model
|   `-- abstract_filters/     Registered abstract geometry transforms
|-- templates/                Jinja application pages
|-- static/                   Shared browser assets and documentation diagrams
|-- tests/                    Unit and route-level regression tests
|-- k8s/                      Kubernetes resources
`-- docs/                     Operational and recovery documentation
```

Route modules are discovered automatically by `routes/register_routes()`. Add a module beneath `routes/` and decorate views with the shared `routes` blueprint.

Abstract filters are registered through `lib/abstract_filters`. Each filter owns its manifest metadata, controls, normalization, and geometry transform.

## Tests

Run the test suite from the repository root:

```bash
python -m unittest discover -s tests
```

The tests cover vector export behavior, SVG-only jobs, authentication intent, job access and history, Material Library coupons, Color Discovery, palette generation, and Holographic Lab access paths.

## Holographic Etching Lab

The Holographic Lab is an experimental calibration workflow for angle-dependent diffraction structures:

1. Generate and engrave a grid that sweeps fill interval, angle, and optionally another laser parameter.
2. Upload a controlled photograph of the finished grid.
3. Align and analyze the grid, curate useful measured cells, and save a recipe profile.
4. Apply that recipe to artwork as small grating patches and inspect the generated LightBurn project.

Resolution grows project complexity quickly because each processed artwork pixel can become physical vector geometry. Start with small calibration pieces and low processing dimensions.

## Safety and result variability

MOPA Laser color and diffraction results depend on the exact source, lens, focus, material alloy, finish, preparation, power, speed, frequency, pulse width, interval, scan direction, passes, and thermal history. A screen color or shared recipe does not guarantee a matching physical result.

Use suitable materials, guarding, extraction, fixturing, and manufacturer-approved parameter ranges. Supervise every job and verify generated files in LightBurn before enabling output.
