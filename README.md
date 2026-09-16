# MOPA Laser Rasterizer

MOPA Laser Rasterizer is a browser-based artwork preparation system that converts raster images into color-separated vector geometry for laser engraving. Every successful Rasterizer job produces a layered SVG. When a compatible LightBurn Material Library is supplied, the job can also produce a `.lbrn2` project containing the operator's selected and matched cut settings.

The application prepares artwork and project files; it does not control a laser, generate safe laser parameters, or guarantee a physical result. Operators must inspect every output, confirm every setting, and test on expendable material before engraving.

- Production: <https://mopa-laser-rasterizer.com/>
- Public documentation: <https://mopa-laser-rasterizer.com/docs>
- Experimental laboratories: <https://mopa-laser-rasterizer.com/experimental-laboratories>

## Current capabilities

### Rasterizer

- Import JPG, JPEG, PNG, BMP, TIFF, and WebP artwork.
- Crop with movable and resizable Rectangle, Square, Oval, and Circle selections.
- Use **Crop transparency** to exclude transparent exterior areas and transparent holes from generated geometry.
- Quantize artwork to enabled LightBurn-compatible swatches and remove small islands while transferring their ownership to an adjacent color.
- Process artwork with Cartoon, Color Photo, Black and White Photo, or configurable abstract Image Styles, including Structure Tensor Flow.
- Select the final Geometry Style independently for compatible Image Styles:
  - Normal Vectors
  - Glyphs
  - Krasnow Grating
  - Choose by Swatch, which routes different colors to different geometry styles in the same job
- Configure Glyph geometry, including supported shape families, staggered packing, and invert-fill punch-throughs.
- Configure Krasnow Grating geometry with patch, spacing, angle, fauxlogram-gradient scope/direction, and painted flow-region controls.
- Export non-overlapping color geometry as layered SVG.
- Export LightBurn `.lbrn2` projects using settings imported from `.clb`, `.lbmat`, or compatible `.lbrn` files.
- Use SVG-Only mode without uploading laser settings or using LightBurn.
- Review browser-session or account-backed job history and stream active worker logs from CloudWatch.

### Palette and material tools

- Import, repair, reassign, edit, combine, and export saved libraries in **Swatch Palette Vault**.
- Maintain Color, Hatch, Depth, and Fauxlographic palettes.
- Build Hatch Palettes from a tested base setting and plan per-swatch scan angles and line intervals.
- Preserve LightBurn fill behavior, including grouped/individual fill choices and Flood Fill, while keeping implementation-only metadata out of the public editor.
- Generate labeled LightBurn material-test coupons from selected saved settings.
- Generate a blank 30-swatch LightBurn palette library for configuration.
- Browse and contribute deduplicated Community Set laser settings.

### Experimental laboratories

- **Color Discovery Lab** — generate parameter grids, photograph and align engraved grids, measure cells, select useful colors, and save resulting settings or palettes.
- **Fauxlographic Etching Lab** — create diffraction calibration grids, analyze photographed results, curate fauxlographic swatches, and generate artwork from measured grating settings.
- **Depthmap/Relief Engraving Lab** — generate or import relative depth data, apply palette guidance and manual corrections, preview relief and parallax interpretations, and export depthmaps or grating geometry.

The in-depth guides are available at:

- [MOPA Madness: The Wizzard of Awes' Full Tutorial on Fauxlographic Laser Engraving](https://mopa-laser-rasterizer.com/docs/fauxlogram-tutorial)
- [Geometric Alchemy: The Wizzard of Awes' Full Guide to Multi-Geometry Rasterizer Jobs](https://mopa-laser-rasterizer.com/docs/multi-geometry-rasterizer-guide)

## Rasterizer workflow

1. Develop and verify laser settings on the intended machine, lens, material, finish, focus arrangement, and cleaning process.
2. Back up the original LightBurn Material Library before editing it.
3. Prepare a compatible library by matching each cut setting's Description to the Rasterizer swatch it should serve, or import the library into Swatch Palette Vault and assign settings there.
4. Upload artwork and choose LightBurn output or SVG-Only mode.
5. Crop the artwork when needed, choose the processing dimensions and physical pixel size, select the desired palette and Image Style, then choose a Geometry Style or per-swatch routing.
6. Submit the job, follow its status and logs, and download whichever completed output files are useful for the workflow.
7. Inspect dimensions, geometry, layers, cut modes, output states, and every laser parameter before framing and testing the job.

For MOPA color work, Flood Fill has often produced the best combination of engraving quality and run time in this project's testing, but it remains an operator-controlled LightBurn setting that must be validated on the actual system.

## Production architecture

The live application is AWS-native and scales to zero when idle. It does not require an EC2 or Kubernetes cluster.

```text
Browser
  -> CloudFront + private S3 static site
  -> API Gateway HTTP API + Lambda
       -> Cognito authentication
       -> presigned S3 uploads and artifact delivery
       -> DynamoDB account, palette, job, and runtime state
       -> SQS job queue
            -> EventBridge Pipes + Step Functions
                 -> one-shot ECS Fargate worker
                      -> S3 outputs
                      -> DynamoDB status and ownership
                      -> CloudWatch job logs
```

Important production behaviors:

- Artifact buckets, queues, and DynamoDB storage are encrypted at rest.
- Job artifacts and transient runtime records expire automatically; durable account assets such as Material Libraries and palettes are not placed under the job TTL.
- Detailed worker output is written once to CloudWatch rather than duplicated into DynamoDB for every log line.
- A monthly AWS cost guard warns at 75% of the configured budget and provides independent pause/resume controls for staging and production job dispatch.
- The public site remains available while job dispatch is paused and explains when service is expected to resume.

CloudFormation templates live under [`ecs/`](ecs/). Operational recovery information is maintained in [`docs/AWS_DISASTER_RECOVERY.md`](docs/AWS_DISASTER_RECOVERY.md).

## Development and release workflow

The protected-branch promotion path is:

```text
feature branch
  -> pull request to staging
  -> automatic serverless staging tests and deployment
  -> staging acceptance
  -> pull request from staging to main
  -> required staging-source check
  -> automatic production tests, deployment, and endpoint verification
```

GitHub Actions uses OpenID Connect to obtain short-lived AWS credentials. No long-lived AWS access key is stored in GitHub. Staging and production use different GitHub environments and narrowly scoped deployment roles. Deployment concurrency is serialized so a new run does not cancel an active deployment.

Workstation deployment remains available through AWS SSO when it is needed. See:

- [GitHub Actions staging deployment](docs/github-actions-staging-deployment.md)
- [GitHub Actions production deployment](docs/github-actions-production-deployment.md)

### Local development requirements

- Ubuntu WSL or a compatible Linux environment
- Python 3.11 or newer
- Redis only when exercising the Redis-backed queue/runtime path

From the repository root inside Ubuntu WSL:

```bash
bash dev_setup/setup-wsl.sh
source .venv/bin/activate
python app.py
```

Open <http://localhost:8000>.

The application does not automatically load `.env` files. Export configuration in the shell or use the repository's environment-loading scripts where appropriate. Local submissions run in background threads by default. Set `RASTER_JOB_QUEUE_ENABLED=true` and run `python worker.py` separately to exercise the Redis-backed worker path.

### Docker

```bash
docker build -t mopa-laser-rasterizer .
docker run --rm -p 8000:8000 mopa-laser-rasterizer
```

The image starts Gunicorn with one process and four threads. AWS production uses the same image for one-shot Fargate processing while serving the public frontend and API through the serverless web stack.

### Command-line rasterizer

```bash
bash run-cli.sh INPUT OUTPUT_BASE PIXEL_MM WIDTH HEIGHT MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER
```

Optional filter JSON, palette-name JSON, and SVG-only arguments are forwarded to `lib/Material_Library.py`. Example:

```bash
bash run-cli.sh input.png output/job 0.125 800 0 settings.clb \
  "colors - stainless steel" "Red,Blue,Green" cartoon none '{}' '{}' false
```

For the repository sample, place `test-input.png` and `tests.clb` in the repository root and run:

```bash
bash run-sample.sh
```

Output is written beneath `uploads/cli-sample/`.

## Configuration

Core local/runtime variables include:

| Variable | Default | Purpose |
| --- | --- | --- |
| `UPLOAD_FOLDER` | `./uploads` | Node-local scratch and local artifact storage |
| `APP_SESSION_SECRET` | Development-only value | Signs Flask and anonymous browser sessions; replace outside local development |
| `SESSION_COOKIE_SECURE` | `false` | Restricts session cookies to HTTPS when `true` |
| `PUBLIC_APP_URL` | Request origin | Canonical public URL |
| `DAILY_JOB_LIMIT` | `3` | Flask-path anonymous daily job allowance |
| `RASTER_JOB_QUEUE_ENABLED` | `false` | Enables the Redis-backed queued worker path |
| `JOB_BACKEND` | `redis` | Selects `redis` or `aws` runtime state |
| `REDIS_URL` / `REDIS_HOST` / `REDIS_PORT` | local Redis | Redis connection settings for the legacy/local runtime |
| `AWS_REGION` | `us-east-2` | AWS client region |
| `S3_BUCKET_NAME` | empty | Durable input and output bucket |
| `DYNAMODB_TABLE_NAME` | empty | Durable account, library, palette, job, and runtime table |
| `JOB_RUNTIME_TABLE_NAME` | `DYNAMODB_TABLE_NAME` | Optional separate DynamoDB runtime table for `JOB_BACKEND=aws` |
| `SQS_QUEUE_URL` | empty | Serverless job queue |
| `COGNITO_DOMAIN` / `COGNITO_CLIENT_ID` | empty | Cognito login and logout integration |
| `RASTER_WORKER_PROCESSES` | `1` | CPU workers used by geometry-processing stages |

Deployment templates and scripts supply additional environment-specific values. Do not commit `.env.aws`, AWS credentials, staging access-gate credentials, Cognito secrets, or generated SSO cache data.

## Project structure

```text
mopa-laser-rasterizer/
|-- app.py                       Flask bootstrap and local development server
|-- services.py                  Shared job, storage, account, and palette services
|-- worker.py                    Redis or AWS job worker entry point
|-- job_runtime.py               Redis and DynamoDB runtime adapters
|-- routes/                      Flask routes and documentation content
|-- serverless_api/              API Gateway/Lambda serverless API handler
|-- serverless_web/              Static-site build/runtime support
|-- serverless_cost_guard/       Budget notification and service-control Lambda
|-- ecs/                         Active serverless AWS CloudFormation templates
|-- dev_setup/                   Local setup, build, deployment, and recovery scripts
|-- lib/
|   |-- vector_processing.py     Quantization and vector geometry pipeline
|   |-- Material_Library.py      Raster job entry point and library integration
|   |-- lightburn.py             LightBurn library and project model
|   |-- geometry_styles.py       Vector, Glyph, Krasnow, and per-swatch routing
|   `-- abstract_filters/        Registered abstract image/geometry transforms
|-- templates/                   Jinja application pages
|-- static/                      Shared browser assets, media, and documentation art
|-- tests/                       Regression and deployment-policy tests
|-- docs/                        Deployment, recovery, and operational documentation
`-- k8s/                         Retained legacy Kubernetes manifests; not used by production
```

Route modules are discovered by `routes.register_routes()`. Abstract filters are registered through `lib/abstract_filters`; each filter owns its defaults, controls, normalization, and transform implementation.

## Tests

The CI workflows install `requirements-dev.txt` and run the complete unittest suite before either environment receives AWS credentials:

```bash
python -m unittest discover -s tests
```

Focused pytest runs are also supported after installing the development requirements:

```bash
python -m pytest -q
```

The suite covers vector ownership and overlap prevention, SVG and LightBurn export, cropping and transparency, Image and Geometry Styles, authentication, job access/history/logs, palette import and editing, calibration labs, serverless handlers, cost controls, deployment permissions, and staging-to-production policy.

## Safety and result variability

Laser color, texture, depth, and diffraction results depend on the exact laser source, lens, focus, material alloy, finish, preparation, power, speed, frequency, pulse width, interval, scan direction, passes, fixturing, cleaning, and thermal history. A preview color or shared setting does not guarantee a matching physical result.

Use suitable materials, guarding, extraction, fixturing, and manufacturer-approved parameter ranges. Supervise every job and verify generated files in the software that will operate the laser before enabling output.
