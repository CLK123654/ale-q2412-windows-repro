$ErrorActionPreference = "Stop"
$aleRef = Join-Path $env:RUNNER_TEMP "ale-reference"
Expand-Archive -LiteralPath ./task/reference.zip -DestinationPath $aleRef
$charts = Get-ChildItem -LiteralPath $aleRef -Recurse -Filter Chart.yaml -File
if (-not $charts) { throw "Chart.yaml missing" }
foreach ($chart in $charts) {
  $dir = Split-Path -Parent $chart.FullName
  helm lint $dir --strict
  if ($LASTEXITCODE -ne 0) { throw "helm lint failed" }
  helm template ale-smoke $dir --namespace ale-smoke | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "helm template failed" }
}
helm version --short
