# pnpm --dir .\aearn dev：启动 Docker 依赖、只读检查 DB、API、Celery worker/beat、Tauri desktop
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
  [switch]$NoCodexWorker,
  [switch]$NoDesktop
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSEdition -ne "Core" -or $PSVersionTable.PSVersion.Major -lt 7) {
  throw "start-dev.ps1 requires pwsh (PowerShell 7 or newer)."
}

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
    "workerPid" { return "aearn_worker\.worker_app:celery_app worker.*-Q celery,tutor-interactive,tutor-proactive,tutor-curation.*-n tutor-main@%h" }
    "codexWorkerPid" { return "aearn_worker\.worker_app:celery_app worker.*tutor-codex" }
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
  foreach ($key in @("apiPid", "workerPid", "codexWorkerPid", "beatPid", "desktopPid")) {
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
    -FilePath "pwsh" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -WindowStyle Hidden `
    -PassThru
  Write-Step "$Name started, pid=$($process.Id)"
  return [int]$process.Id
}

function Assert-CompletionStartupQuiescent {
  # PIDs, command lines and the legacy static health response cannot establish
  # which database contract an already-running process loaded. Never kill it.
  $listener = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
    Where-Object { $_.Port -eq $ApiPort }
  $apiPid = Find-ProcessIdByCommand "uvicorn.*app\.main:app"
  $workerOrBeatPid = Find-ProcessIdByCommand "aearn_worker\.worker_app.*\b(worker|beat)\b"
  if ($listener -or $apiPid -or $workerOrBeatPid) {
    throw "completion_non_b1d_v1 requires a controlled restart: quiesce existing API/worker/beat and finish in-flight work first. No existing process was stopped or accepted as contract-ready."
  }
}

function Wait-LogContains {
  param(
    [string[]]$Paths,
    [string]$Pattern,
    [string]$Name,
    [int]$TimeoutSeconds = 45,
    [int]$ProcessId = 0
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if ($ProcessId -and -not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
      throw "$Name exited before startup completed; inspect its startup logs."
    }
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
  $apiStatus = if (Test-Http "http://127.0.0.1:$ApiPort/health") { "HTTP reachable http://127.0.0.1:$ApiPort (not database-contract readiness)" } else { "not reachable" }
  $desktopStatus = if (Test-Http "http://127.0.0.1:$DesktopPort") { "ready http://127.0.0.1:$DesktopPort" } else { "not ready" }
  Write-Host "  api:     $apiStatus"
  Write-Host "  desktop: $desktopStatus"
  Write-Host "  tracked pids:"
  if ($state.Contains("startedAt") -and $state.startedAt) {
    Write-Host "    startedAt: $($state.startedAt)"
  }
  $printedPid = $false
  foreach ($key in @("apiPid", "workerPid", "codexWorkerPid", "beatPid", "desktopPid")) {
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

Assert-Command "uv"
Assert-Command "pnpm"
Assert-Command "docker"

if ($Status) {
  Show-Status
  exit 0
}

# Resolve exactly the same process-env/.env precedence as API/worker without
# opening a database connection or printing settings/credentials.
$databaseContractJson = Invoke-Checked `
  -FilePath "uv" `
  -ArgumentList @("--directory", $ApiDir, "run", "python", "-c", "import json, os; import app.core.config; print(json.dumps(os.environ.get('AEARN_DATABASE_CONTRACT')))") `
  -FailureMessage "database contract selection failed"
$databaseContract = $databaseContractJson | ConvertFrom-Json
$completionContractSelected = $databaseContract -ceq "completion_non_b1d_v1"
if (-not $completionContractSelected) {
  throw "Managed startup requires AEARN_DATABASE_CONTRACT=completion_non_b1d_v1; missing or unsupported selection cannot run legacy DDL or seeds."
}
if ($completionContractSelected) {
  if ($Restart) {
    throw "completion_non_b1d_v1 requires a controlled restart after in-flight work is quiescent; automatic -Restart is disabled. No process was stopped."
  }
  Assert-CompletionStartupQuiescent
} elseif ($Restart) {
  Stop-TrackedProcesses
}

$state = [ordered]@{}

if (-not $SkipDocker) {
  Write-Step "starting PostgreSQL and Redis"
  Invoke-Checked `
    -FilePath "docker" `
    -ArgumentList @("compose", "-f", (Join-Path $AearnDir "infra\docker-compose.yml"), "up", "-d") `
    -FailureMessage "docker compose startup failed"
}

if ($completionContractSelected) {
  # SkipBootstrap never skips this readonly gate, and this branch never installs
  # schema, seeds data, or falls back to the legacy bootstrap.
  Write-Step "checking completion_non_b1d_v1 database contract (readonly)"
  Invoke-Checked `
    -FilePath "uv" `
    -ArgumentList @("--directory", $ApiDir, "run", "python", "-m", "app.db.bootstrap", "--contract", "completion_non_b1d_v1", "--check") `
    -FailureMessage "completion_non_b1d_v1 readiness failed; no API/worker/beat started"
  Assert-CompletionStartupQuiescent
}

$apiHealthUrl = "http://127.0.0.1:$ApiPort/health"
if (-not $completionContractSelected -and (Test-Http $apiHealthUrl)) {
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
  if ($completionContractSelected) {
    Wait-LogContains -Paths @((Join-Path $LogDir "api-dev.out.log"), (Join-Path $LogDir "api-dev.err.log")) -Pattern "^INFO:\s+Application startup complete\.$" -Name "api lifespan" -ProcessId $state.apiPid
  }
  Wait-Http -Url $apiHealthUrl -Name "api"
}

if (-not $NoWorker) {
  $workerPid = Find-ProcessIdByCommand "aearn_worker\.worker_app:celery_app worker.*-Q celery,tutor-interactive,tutor-proactive,tutor-curation.*-n tutor-main@%h"
  if ($workerPid) {
    if ($completionContractSelected) {
      throw "Existing worker requires a controlled restart; it was not accepted as contract-ready."
    }
    Write-Step "worker already running, pid=$workerPid"
    $state.workerPid = $workerPid
  } else {
    $workerOutLog = Join-Path $LogDir "worker-dev.out.log"
    $workerErrLog = Join-Path $LogDir "worker-dev.err.log"
    $state.workerPid = Start-ManagedProcess `
      -Name "worker" `
      -Command "uv --directory `"$ApiDir`" run python -m celery -A aearn_worker.worker_app:celery_app worker --loglevel=info --pool=solo --concurrency=1 -Q celery,tutor-interactive,tutor-proactive,tutor-curation -n tutor-main@%h" `
      -OutLog $workerOutLog `
      -ErrLog $workerErrLog
    $workerReadyPattern = if ($completionContractSelected) { "\]\s+tutor-main@\S+ ready\.$" } else { "ready" }
    Wait-LogContains -Paths @($workerOutLog, $workerErrLog) -Pattern $workerReadyPattern -Name "worker" -ProcessId $state.workerPid
  }

  if (-not $NoCodexWorker) {
    $codexWorkerPid = Find-ProcessIdByCommand "aearn_worker\.worker_app:celery_app worker.*tutor-codex"
    if ($codexWorkerPid) {
      if ($completionContractSelected) {
        throw "Existing tutor-codex worker requires a controlled restart; it was not accepted as contract-ready."
      }
      Write-Step "tutor-codex worker already running, pid=$codexWorkerPid"
      $state.codexWorkerPid = $codexWorkerPid
    } else {
      $codexWorkerOutLog = Join-Path $LogDir "codex-worker-dev.out.log"
      $codexWorkerErrLog = Join-Path $LogDir "codex-worker-dev.err.log"
      $state.codexWorkerPid = Start-ManagedProcess `
        -Name "tutor-codex worker" `
        -Command "uv --directory `"$ApiDir`" run python -m celery -A aearn_worker.worker_app:celery_app worker --loglevel=info --pool=solo --concurrency=1 -Q tutor-codex -n tutor-codex@%h" `
        -OutLog $codexWorkerOutLog `
        -ErrLog $codexWorkerErrLog
      $codexReadyPattern = if ($completionContractSelected) { "\]\s+tutor-codex@\S+ ready\.$" } else { "ready" }
      Wait-LogContains -Paths @($codexWorkerOutLog, $codexWorkerErrLog) -Pattern $codexReadyPattern -Name "tutor-codex worker" -ProcessId $state.codexWorkerPid
    }
  }

  $beatPid = Find-ProcessIdByCommand "aearn_worker\.worker_app:celery_app beat"
  if ($beatPid) {
    if ($completionContractSelected) {
      throw "Existing beat requires a controlled restart; it was not accepted as contract-ready."
    }
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
    $beatReadyPattern = if ($completionContractSelected) { "\]\s+aearn beat scheduler startup complete$" } else { "beat: Starting" }
    Wait-LogContains -Paths @($beatOutLog, $beatErrLog) -Pattern $beatReadyPattern -Name "beat" -ProcessId $state.beatPid
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
