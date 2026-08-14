# pnpm --dir .\aearn dev：启动 Docker 依赖、bootstrap DB、API、Celery worker/beat、Tauri desktop
# pnpm --dir .\aearn dev:status：查看状态
# pnpm --dir .\aearn dev:restart：重启本脚本拉起的进程
# pnpm --dir .\aearn dev:stop：停止本脚本拉起的 API/worker/desktop
param(
  [switch]$Restart,
  [switch]$Stop,
  [switch]$Status,
  [switch]$SkipDocker,
  [switch]$SkipBootstrap,
  [switch]$NoWorker,
  [switch]$NoDesktop
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AearnDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent $AearnDir
$ApiDir = Join-Path $AearnDir "services\api"
$LogDir = Join-Path $AearnDir ".logs"
$StateFile = Join-Path $LogDir "dev-processes.json"
$ApiPort = 8001
$DesktopPort = 1420

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Write-Step([string]$Message) {
  Write-Host "[aearn-dev] $Message"
}

function Assert-Command([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $Name"
  }
}

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$FailureMessage
  )
  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) {
    throw $FailureMessage
  }
}

function Read-State {
  if (-not (Test-Path -LiteralPath $StateFile)) {
    return [ordered]@{}
  }
  try {
    $json = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    if ($null -eq $json) {
      return [ordered]@{}
    }
    $state = [ordered]@{}
    foreach ($property in $json.PSObject.Properties) {
      $state[$property.Name] = $property.Value
    }
    return $state
  } catch {
    return [ordered]@{}
  }
}

function Save-State([hashtable]$State) {
  $State.startedAt = (Get-Date).ToString("o")
  $State | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StateFile -Encoding UTF8
}

function Test-Http([string]$Url) {
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
  } catch {
    return $false
  }
}

function Wait-Http {
  param(
    [string]$Url,
    [string]$Name,
    [int]$TimeoutSeconds = 45
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-Http $Url) {
      return
    }
    Start-Sleep -Seconds 1
  }
  throw "$Name did not become ready at $Url within $TimeoutSeconds seconds"
}

function Find-ProcessIdByCommand([string]$Regex) {
  $currentPid = $PID
  $matches = Get-CimInstance Win32_Process |
    Where-Object {
      $_.ProcessId -ne $currentPid -and
      $_.CommandLine -and
      $_.CommandLine -match $Regex
    } |
    Sort-Object CreationDate
  if ($matches) {
    return [int]$matches[0].ProcessId
  }
  return $null
}

function Get-TrackedProcessPattern([string]$Key) {
  switch ($Key) {
    "apiPid" { return "uv --directory .*python -m uvicorn app\.main:app" }
    "workerPid" { return "aearn_worker\.worker_app:celery_app worker" }
    "beatPid" { return "aearn_worker\.worker_app:celery_app beat" }
    "desktopPid" { return "pnpm --dir .*desktop:dev" }
    default { return $null }
  }
}

function Get-TrackedProcessStatus {
  param(
    [string]$Key,
    [int]$ProcessId
  )
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if (-not $process) {
    return [ordered]@{
      status = "stale"
      reason = "process not found"
    }
  }

  $pattern = Get-TrackedProcessPattern -Key $Key
  if ($pattern -and (-not $process.CommandLine -or $process.CommandLine -notmatch $pattern)) {
    return [ordered]@{
      status = "untrusted"
      reason = "command mismatch"
      name = $process.Name
    }
  }

  return [ordered]@{
    status = "alive"
    reason = "command verified"
    name = $process.Name
  }
}

function Stop-ProcessTree([int]$ProcessId) {
  $children = Get-CimInstance Win32_Process |
    Where-Object { $_.ParentProcessId -eq $ProcessId } |
    Select-Object -ExpandProperty ProcessId
  foreach ($child in $children) {
    Stop-ProcessTree -ProcessId ([int]$child)
  }
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($process) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  }
}

function Stop-TrackedProcesses {
  $state = Read-State
  foreach ($key in @("apiPid", "workerPid", "beatPid", "desktopPid")) {
    if ($state.Contains($key) -and $state[$key]) {
      $processId = [int]$state[$key]
      $tracked = Get-TrackedProcessStatus -Key $key -ProcessId $processId
      if ($tracked.status -eq "alive") {
        Write-Step "Stopping $key=$processId"
        Stop-ProcessTree -ProcessId $processId
      } else {
        Write-Step "Skipping $key=$processId ($($tracked.status): $($tracked.reason))"
      }
    }
  }
  Remove-Item -LiteralPath $StateFile -ErrorAction SilentlyContinue
}

function Start-ManagedProcess {
  param(
    [string]$Name,
    [string]$Command,
    [string]$OutLog,
    [string]$ErrLog
  )
  Remove-Item -LiteralPath $OutLog, $ErrLog -ErrorAction SilentlyContinue
  $process = Start-Process `
    -FilePath "powershell" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -WindowStyle Hidden `
    -PassThru
  Write-Step "$Name started, pid=$($process.Id)"
  return [int]$process.Id
}

function Wait-LogContains {
  param(
    [string[]]$Paths,
    [string]$Pattern,
    [string]$Name,
    [int]$TimeoutSeconds = 45
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    foreach ($path in $Paths) {
      if ((Test-Path -LiteralPath $path) -and (Select-String -Path $path -Pattern $Pattern -Quiet -ErrorAction SilentlyContinue)) {
        return
      }
    }
    Start-Sleep -Seconds 1
  }
  throw "$Name did not write expected log pattern '$Pattern' within $TimeoutSeconds seconds"
}

function Show-Status {
  $state = Read-State
  Write-Step "status"
  Write-Host "  docker:"
  docker compose -f (Join-Path $AearnDir "infra\docker-compose.yml") ps
  $apiStatus = if (Test-Http "http://127.0.0.1:$ApiPort/health") { "ready http://127.0.0.1:$ApiPort" } else { "not ready" }
  $desktopStatus = if (Test-Http "http://127.0.0.1:$DesktopPort") { "ready http://127.0.0.1:$DesktopPort" } else { "not ready" }
  Write-Host "  api:     $apiStatus"
  Write-Host "  desktop: $desktopStatus"
  Write-Host "  tracked pids:"
  if ($state.Contains("startedAt") -and $state.startedAt) {
    Write-Host "    startedAt: $($state.startedAt)"
  }
  $printedPid = $false
  foreach ($key in @("apiPid", "workerPid", "beatPid", "desktopPid")) {
    if ($state.Contains($key) -and $state[$key]) {
      $printedPid = $true
      $processId = [int]$state[$key]
      $tracked = Get-TrackedProcessStatus -Key $key -ProcessId $processId
      $details = "$($tracked.status), $($tracked.reason)"
      if ($tracked.Contains("name") -and $tracked.name) {
        $details = "$details, $($tracked.name)"
      }
      Write-Host "    ${key}: $processId ($details)"
    }
  }
  if (-not $printedPid) {
    Write-Host "    none"
  }
}

if ($Stop) {
  Stop-TrackedProcesses
  Show-Status
  exit 0
}

if ($Restart) {
  Stop-TrackedProcesses
}

Assert-Command "uv"
Assert-Command "pnpm"
Assert-Command "docker"

if ($Status) {
  Show-Status
  exit 0
}

$state = [ordered]@{}

if (-not $SkipDocker) {
  Write-Step "starting PostgreSQL and Redis"
  Invoke-Checked `
    -FilePath "docker" `
    -ArgumentList @("compose", "-f", (Join-Path $AearnDir "infra\docker-compose.yml"), "up", "-d") `
    -FailureMessage "docker compose startup failed"
}

if (-not $SkipBootstrap) {
  Write-Step "bootstrapping database schema"
  Invoke-Checked `
    -FilePath "uv" `
    -ArgumentList @("--directory", $ApiDir, "run", "python", "-m", "app.db.bootstrap") `
    -FailureMessage "database bootstrap failed"
}

$apiHealthUrl = "http://127.0.0.1:$ApiPort/health"
if (Test-Http $apiHealthUrl) {
  Write-Step "api already ready at $apiHealthUrl"
  $apiPid = Find-ProcessIdByCommand "uv --directory .*python -m uvicorn app\.main:app"
  if ($apiPid) {
    $state.apiPid = $apiPid
  }
} else {
  $state.apiPid = Start-ManagedProcess `
    -Name "api" `
    -Command "uv --directory `"$ApiDir`" run python -m uvicorn app.main:app --host 127.0.0.1 --port $ApiPort --reload" `
    -OutLog (Join-Path $LogDir "api-dev.out.log") `
    -ErrLog (Join-Path $LogDir "api-dev.err.log")
  Wait-Http -Url $apiHealthUrl -Name "api"
}

if (-not $NoWorker) {
  $workerPid = Find-ProcessIdByCommand "aearn_worker\.worker_app:celery_app worker"
  if ($workerPid) {
    Write-Step "worker already running, pid=$workerPid"
    $state.workerPid = $workerPid
  } else {
    $workerOutLog = Join-Path $LogDir "worker-dev.out.log"
    $workerErrLog = Join-Path $LogDir "worker-dev.err.log"
    $state.workerPid = Start-ManagedProcess `
      -Name "worker" `
      -Command "uv --directory `"$ApiDir`" run python -m celery -A aearn_worker.worker_app:celery_app worker --loglevel=info --pool=solo" `
      -OutLog $workerOutLog `
      -ErrLog $workerErrLog
    Wait-LogContains -Paths @($workerOutLog, $workerErrLog) -Pattern "ready" -Name "worker"
  }

  $beatPid = Find-ProcessIdByCommand "aearn_worker\.worker_app:celery_app beat"
  if ($beatPid) {
    Write-Step "beat already running, pid=$beatPid"
    $state.beatPid = $beatPid
  } else {
    $beatOutLog = Join-Path $LogDir "beat-dev.out.log"
    $beatErrLog = Join-Path $LogDir "beat-dev.err.log"
    $state.beatPid = Start-ManagedProcess `
      -Name "beat" `
      -Command "uv --directory `"$ApiDir`" run python -m celery -A aearn_worker.worker_app:celery_app beat --loglevel=info --pidfile=" `
      -OutLog $beatOutLog `
      -ErrLog $beatErrLog
    Wait-LogContains -Paths @($beatOutLog, $beatErrLog) -Pattern "beat: Starting" -Name "beat"
  }
}

if (-not $NoDesktop) {
  $desktopUrl = "http://127.0.0.1:$DesktopPort"
  if (Test-Http $desktopUrl) {
    Write-Step "desktop dev server already ready at $desktopUrl"
    $desktopPid = Find-ProcessIdByCommand "pnpm --dir .*desktop:dev"
    if ($desktopPid) {
      $state.desktopPid = $desktopPid
    }
  } else {
    $state.desktopPid = Start-ManagedProcess `
      -Name "desktop" `
      -Command "pnpm --dir `"$AearnDir`" desktop:dev" `
      -OutLog (Join-Path $LogDir "desktop-dev.out.log") `
      -ErrLog (Join-Path $LogDir "desktop-dev.err.log")
    Wait-Http -Url $desktopUrl -Name "desktop dev server" -TimeoutSeconds 90
  }
}

Save-State -State $state
Show-Status
