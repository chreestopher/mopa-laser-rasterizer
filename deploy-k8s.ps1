param(
    [string]$ImageName = "mopa-laser-rasterizer",
    [string]$ImageTag = "local",
    [string]$Dockerfile = "Dockerfile",
    [string]$Context = ".",
    [string]$KubeConfigPath = "/etc/rancher/k3s/k3s.yaml",
    [switch]$SkipClean
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function ExitWithError($message) {
    Write-Error $message
    exit 1
}

function Invoke-WslCommand($command) {
    Write-Host "Running in WSL: $command"
    & wsl -e sh -lc $command
    if ($LASTEXITCODE -ne 0) {
        ExitWithError "WSL command failed: $command"
    }
}

function Get-WslPath($windowsPath) {
    if ($windowsPath -match '^[A-Za-z]:(\\|/).*') {
        $drive = $windowsPath.Substring(0, 1).ToLower()
        $rest = $windowsPath.Substring(2).TrimStart('\','/') -replace '\\', '/'
        return "/mnt/$drive/$rest"
    }

    $wslPath = & wsl wslpath -a "$windowsPath" 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($wslPath)) {
        ExitWithError "Unable to convert path to WSL path: $windowsPath"
    }
    return $wslPath.Trim()
}

$fullTag = "${ImageName}:${ImageTag}"
$root = Resolve-Path "." | Select-Object -ExpandProperty Path
$rootWsl = Get-WslPath $root
$k8sPathWsl = "$rootWsl/k8s"

Write-Host "Repository root: $root"
Write-Host "WSL repo root: $rootWsl"
Write-Host "Image: $fullTag"

if (-not (Test-Path "$root\.env.local")) {
    ExitWithError ".env.local not found in repository root"
}

if (-not (Test-Path "$root\k8s\deployment.yaml.template")) {
    ExitWithError "k8s/deployment.yaml.template not found"
}

Write-Host "Generating Kubernetes deployment manifest from .env.local..."
& "$root\sync-env.ps1"
if (-not $?) {
    ExitWithError "sync-env.ps1 failed"
}

$dockerNative = Get-Command docker -ErrorAction SilentlyContinue
$useWslDocker = -not $dockerNative -and (Get-Command wsl -ErrorAction SilentlyContinue)
if (-not $dockerNative -and -not $useWslDocker) {
    ExitWithError "Docker is not available on Windows and WSL is not available for Docker commands."
}

Write-Host "Building Docker image $fullTag..."
if ($dockerNative) {
    docker build -t $fullTag -f "$Dockerfile" "$Context"
    if ($LASTEXITCODE -ne 0) {
        ExitWithError "Docker build failed"
    }
} else {
    $dockerfileAbs = Resolve-Path $Dockerfile | Select-Object -ExpandProperty Path
    $contextAbs = Resolve-Path $Context | Select-Object -ExpandProperty Path
    $dockerfileWsl = Get-WslPath $dockerfileAbs
    $contextWsl = Get-WslPath $contextAbs
    Invoke-WslCommand "cd '$contextWsl' && docker build -t '$fullTag' -f '$dockerfileWsl' ."
}

$tempTar = Join-Path $env:TEMP "$($ImageName.Replace('/', '_'))-$($ImageTag)-$(Get-Date -Format yyyyMMddHHmmss).tar"
Write-Host "Saving Docker image to $tempTar..."
if ($dockerNative) {
    docker save $fullTag -o "$tempTar"
    if ($LASTEXITCODE -ne 0) {
        ExitWithError "docker save failed"
    }
} else {
    $tempTarWsl = Get-WslPath $tempTar
    Invoke-WslCommand "docker save -o '$tempTarWsl' '$fullTag'"
}

try {
    $imageLoaded = $false

    if (Get-Command k3s -ErrorAction SilentlyContinue) {
        Write-Host "Loading image into k3s containerd via k3s..."
        k3s ctr -n k8s.io images import "$tempTar"
        if ($LASTEXITCODE -ne 0) { ExitWithError "k3s ctr image import failed" }
        $imageLoaded = $true
    }
    elseif (Get-Command ctr -ErrorAction SilentlyContinue) {
        Write-Host "Loading image into containerd via ctr..."
        ctr -n k8s.io images import "$tempTar"
        if ($LASTEXITCODE -ne 0) { ExitWithError "ctr image import failed" }
        $imageLoaded = $true
    }
    elseif (Get-Command crictl -ErrorAction SilentlyContinue) {
        Write-Host "Loading image into CRI runtime via crictl..."
        crictl load "$tempTar"
        if ($LASTEXITCODE -ne 0) { ExitWithError "crictl load failed" }
        $imageLoaded = $true
    }
    elseif (Get-Command wsl -ErrorAction SilentlyContinue) {
        Write-Host "Loading image into k3s containerd via WSL..."
        $tempTarWsl = Get-WslPath $tempTar
        Invoke-WslCommand "sudo k3s ctr -n k8s.io images import '$tempTarWsl'"
        $imageLoaded = $true
    }
    else {
        ExitWithError "No supported runtime loader found. Install k3s, ctr, crictl, or make WSL available."
    }

    if (-not $imageLoaded) {
        ExitWithError "Image load did not complete successfully"
    }
}
finally {
    if (Test-Path $tempTar) {
        Remove-Item $tempTar -ErrorAction SilentlyContinue
    }
}

if (-not $SkipClean) {
    Write-Host "Cleaning existing Kubernetes resources..."
    Invoke-WslCommand "sudo KUBECONFIG=$KubeConfigPath kubectl delete -k '$k8sPathWsl' --ignore-not-found=true"
    Invoke-WslCommand "sudo KUBECONFIG=$KubeConfigPath kubectl delete service mopa-laser-rasterizer-mopa-laser-rasterizer --ignore-not-found=true"
}

Write-Host "Applying Kubernetes configuration..."
Invoke-WslCommand "cd '$rootWsl' && sudo KUBECONFIG=$KubeConfigPath kubectl apply -k 'k8s'"

Write-Host "Restarting the deployment to pick up the new image..."
Invoke-WslCommand "cd '$rootWsl' && sudo KUBECONFIG=$KubeConfigPath kubectl rollout restart deployment/mopa-laser-rasterizer -n default"

Write-Host "Deployment complete. Current pods:"
Invoke-WslCommand "cd '$rootWsl' && sudo KUBECONFIG=$KubeConfigPath kubectl get pods -n default -l app=mopa-laser-rasterizer"

Write-Host "Done. Your image is loaded into the local k3s runtime and Kubernetes was updated."
