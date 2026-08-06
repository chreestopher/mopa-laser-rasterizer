param(
    [string]$ImageName = "my-cgi-server",
    [string]$ImageTag = "local",
    [string]$Dockerfile = "Dockerfile",
    [string]$Context = "."
)

$fullTag = "$ImageName:$ImageTag"
Write-Host "Building Docker image $fullTag ..."
$build = docker build -t $fullTag -f $Dockerfile $Context
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed with exit code $LASTEXITCODE"
}

$tempTar = Join-Path $env:TEMP "$($ImageName.Replace('/','_'))-$($ImageTag)-$(Get-Date -Format yyyyMMddHHmmss).tar"
Write-Host "Saving image to $tempTar ..."
docker save $fullTag -o $tempTar
if ($LASTEXITCODE -ne 0) {
    throw "docker save failed with exit code $LASTEXITCODE"
}

$imported = $false
if (Get-Command k3s -ErrorAction SilentlyContinue) {
    Write-Host "Importing image into k3s containerd ..."
    k3s ctr -n k8s.io images import $tempTar
    $imported = $LASTEXITCODE -eq 0
}
elseif (Get-Command ctr -ErrorAction SilentlyContinue) {
    Write-Host "Importing image into containerd using ctr ..."
    ctr -n k8s.io images import $tempTar
    $imported = $LASTEXITCODE -eq 0
}
elseif (Get-Command crictl -ErrorAction SilentlyContinue) {
    Write-Host "Loading image into CRI runtime using crictl ..."
    crictl load $tempTar
    $imported = $LASTEXITCODE -eq 0
}
else {
    Write-Host "No supported loader found. Install k3s, ctr, or crictl and retry." -ForegroundColor Red
}

Remove-Item -Path $tempTar -ErrorAction SilentlyContinue

if (-not $imported) {
    throw "Image load failed. The image file has been removed, but the image was not imported into k3s/containerd."
}

Write-Host "Success. Image $fullTag is loaded into the k3s runtime."
Write-Host "Use this tag in your Kubernetes deployment, for example:"
Write-Host "  kubectl set image deployment/cgi-server cgi-server=$fullTag" -ForegroundColor Cyan
Write-Host "Then restart the deployment with: kubectl rollout restart deployment/cgi-server"
