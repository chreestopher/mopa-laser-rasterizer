$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $root '.env.local'
$template = Join-Path $root 'k8s\deployment.yaml.template'
$target = Join-Path $root 'k8s\deployment.yaml'

if (-not (Test-Path $source)) {
    Write-Error "Source file '$source' does not exist."
    exit 1
}
if (-not (Test-Path $template)) {
    Write-Error "Template file '$template' does not exist."
    exit 1
}

$env = @{}
Get-Content $source | ForEach-Object {
    if ($_ -match '^[\s]*#') { return }
    if ($_ -match '^\s*$') { return }
    $parts = $_ -split '=', 2
    if ($parts.Count -eq 2) {
        $env[$parts[0].Trim()] = $parts[1].Trim()
    }
}

# Preserve compatibility with existing local environment files that specify
# the static directory. The repository root is its parent directory.
if (-not $env.ContainsKey('HOST_APP_PATH') -and $env.ContainsKey('HOST_STATIC_PATH')) {
    $env['HOST_APP_PATH'] = Split-Path -Parent $env['HOST_STATIC_PATH']
}

if (-not $env.ContainsKey('HOST_APP_PATH')) {
    Write-Error "HOST_APP_PATH is required (the absolute repository path on the Kubernetes node)."
    exit 1
}

$text = Get-Content $template -Raw
foreach ($key in $env.Keys) {
    $value = $env[$key]
    $token = '${' + $key + '}'
    $text = $text -replace [regex]::Escape($token), [regex]::Escape($value)
}
Set-Content -Path $target -Value $text -NoNewline
Write-Host "Generated $target from $source"
