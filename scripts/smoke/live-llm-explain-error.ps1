[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:18001",
    [int]$StartupTimeoutSeconds = 45,
    [switch]$SkipInfra,
    [switch]$KeepServer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$apiDir = Join-Path $repoRoot "aearn\services\api"
$pythonExe = Join-Path $apiDir ".venv\Scripts\python.exe"
$composeFile = Join-Path $repoRoot "aearn\infra\docker-compose.yml"
$baseUri = [Uri]$BaseUrl
$port = if ($baseUri.IsDefaultPort) {
    if ($baseUri.Scheme -eq "https") { 443 } else { 80 }
} else {
    $baseUri.Port
}

function Require-Env {
    param([string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required environment variable: $Name"
    }
    return $value
}

function Invoke-AearnJson {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [int]$TimeoutSeconds = 120
    )

    $uri = "$BaseUrl$Path"
    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Method $Method -Uri $uri -TimeoutSec $TimeoutSeconds
        }

        $json = $Body | ConvertTo-Json -Depth 20
        return Invoke-RestMethod -Method $Method -Uri $uri -ContentType "application/json" -Body $json -TimeoutSec $TimeoutSeconds
    } catch {
        $message = $_.Exception.Message
        if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
            $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
            $responseBody = $reader.ReadToEnd()
            $reader.Dispose()
            if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
                $message = "$message`n$responseBody"
            }
        }
        throw "API request failed: $Method $Path`n$message"
    }
}

function Assert-Condition {
    param(
        [bool]$Condition,
        [string]$Message,
        [object]$Detail = $null
    )

    if (-not $Condition) {
        if ($null -ne $Detail) {
            $detailJson = $Detail | ConvertTo-Json -Depth 20
            throw "$Message`n$detailJson"
        }
        throw $Message
    }
}

$apiKey = Require-Env "OPENAI_API_KEY"
$providerBaseUrl = Require-Env "OPENAI_BASE_URL"
$model = Require-Env "OPENAI_MODEL"
if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("LLM_TYPE"))) {
    $env:LLM_TYPE = "openai"
}

Write-Host "Live LLM smoke starting"
Write-Host "Provider: $providerBaseUrl"
Write-Host "Model: $model"
Write-Host "API key: configured ($($apiKey.Length) chars, not printed)"

if (-not $SkipInfra) {
    Write-Host "Ensuring PostgreSQL and Redis are running..."
    docker compose -f $composeFile up -d | Out-Host
}

if (-not (Test-Path $pythonExe)) {
    throw "Python virtualenv not found at $pythonExe. Run backend dependency setup first."
}

$startedServer = $false
$serverProcess = $null
$outLog = Join-Path $env:TEMP "aearn-live-llm-smoke.out.log"
$errLog = Join-Path $env:TEMP "aearn-live-llm-smoke.err.log"
Remove-Item -LiteralPath $outLog, $errLog -ErrorAction SilentlyContinue

try {
    $listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $listening) {
        Write-Host "Starting local API server on $BaseUrl ..."
        $serverProcess = Start-Process `
            -FilePath $pythonExe `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $baseUri.Host, "--port", [string]$port) `
            -WorkingDirectory $apiDir `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -WindowStyle Hidden `
            -PassThru
        $startedServer = $true
    } else {
        Write-Host "Port $port is already listening; reusing the existing API server."
    }

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        try {
            $health = Invoke-AearnJson -Method GET -Path "/health" -TimeoutSeconds 3
            if ($health.status -eq "ok") {
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    $health = Invoke-AearnJson -Method GET -Path "/health" -TimeoutSeconds 5
    Assert-Condition ($health.status -eq "ok") "Health check failed" $health

    $courses = Invoke-AearnJson -Method GET -Path "/api/language-courses?language=javascript"
    $course = $courses.items[0]
    Assert-Condition ($null -ne $course) "No JavaScript course returned" $courses

    $userResponse = Invoke-AearnJson -Method POST -Path "/api/users" -Body @{
        display_name = "Live LLM Smoke $((New-Guid).ToString().Substring(0, 8))"
        learning_style = "practice_first"
        teaching_preference = "step_by_step"
    }
    $user = $userResponse.user

    $draftResponse = Invoke-AearnJson -Method POST -Path "/api/plans/generate" -Body @{
        user_id = $user.id
        mode = "goal_based"
        goal_text = "Practice JavaScript DOM event state with a real LLM explain-error smoke."
        course_id = $course.id
    }
    $planResponse = Invoke-AearnJson -Method POST -Path "/api/plans" -Body @{
        user_id = $user.id
        plan_draft = $draftResponse.plan_draft
    }
    $planId = $planResponse.LearningPlan.id
    $knowledgePointId = $planResponse.knowledge_points[0].id

    $null = Invoke-AearnJson -Method GET -Path "/api/dashboard?user_id=$([Uri]::EscapeDataString($user.id))"

    $session = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/start" -Body @{
        user_id = $user.id
        plan_id = $planId
        knowledge_point_id = $knowledgePointId
    }
    $exercise = $session.exercise
    $filledBlanks = @{
        blank_1 = "addEventListener"
        blank_2 = "count += 1"
    }

    $flawedCode = @'
const button = document.querySelector("#counter-button");
const output = document.querySelector("#counter-output");

button.addEventListener("click", () => {
  let count = 0;
  count += 1;
  output.textContent = String(count);
});
'@

    $failedRun = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/$($session.session_id)/exercises/$($exercise.id)/run" -Body @{
        code = $flawedCode
        filled_blanks = $filledBlanks
        runtime_profile_id = $exercise.runtime_profile.id
        run_mode = "visible_tests"
    }
    $failedTests = @($failedRun.test_results | Where-Object { -not $_.passed })
    Assert-Condition ($failedRun.runtime_status -eq "success") "Expected flawed JS to execute with failing tests" $failedRun
    Assert-Condition (($failedRun.test_pass_rate -lt 1.0) -and ($failedTests.Count -gt 0)) "Expected at least one failed test" $failedRun

    $explainPayload = @{
        error_message = $failedRun.error_message
        stderr = $failedRun.stderr
        failed_tests = @($failedTests | ForEach-Object {
            @{
                case_id = $_.case_id
                case_type = $_.case_type
                message = $_.message
            }
        })
        current_code = $flawedCode
    }
    $explanation = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/$($session.session_id)/attempts/$($failedRun.attempt_id)/explain-error" -Body $explainPayload -TimeoutSeconds 180
    Assert-Condition ($explanation.generation_source -eq "llm") "explain-error did not use live LLM" $explanation
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($explanation.generation_model)) "Missing generation_model" $explanation
    $explanationText = $explanation | ConvertTo-Json -Depth 20
    Assert-Condition (-not $explanationText.Contains("LatteCode_")) "Explanation leaked an API key-like token" $explanation
    Assert-Condition (-not $explanationText.Contains("hidden_three_clicks")) "Explanation leaked hidden case id" $explanation

    $replayedExplanation = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/$($session.session_id)/attempts/$($failedRun.attempt_id)/explain-error" -Body $explainPayload -TimeoutSeconds 180
    Assert-Condition ($replayedExplanation.idempotency_replayed -eq $true) "explain-error replay did not hit idempotency" $replayedExplanation

    $fixedCode = @'
const button = document.querySelector("#counter-button");
const output = document.querySelector("#counter-output");
let count = 0;

button.addEventListener("click", () => {
  count += 1;
  output.textContent = String(count);
});
'@

    $fixedRun = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/$($session.session_id)/exercises/$($exercise.id)/run" -Body @{
        code = $fixedCode
        filled_blanks = $filledBlanks
        runtime_profile_id = $exercise.runtime_profile.id
        run_mode = "visible_tests"
    }
    Assert-Condition (($fixedRun.runtime_status -eq "success") -and ($fixedRun.test_pass_rate -eq 1.0)) "Fixed JS did not pass visible tests" $fixedRun

    $studentExplanation = "状态变量放在事件回调外层，所以多次点击会共享同一个 count；如果放在回调里，每次点击都会重新初始化。"
    $explanationCheck = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/$($session.session_id)/attempts/$($fixedRun.attempt_id)/check-explanation" -Body @{
        explanation = $studentExplanation
        focus = "core_logic"
        round = 1
    }
    Assert-Condition ($explanationCheck.result -eq "passed") "Explanation check did not pass" $explanationCheck

    $submit = Invoke-AearnJson -Method POST -Path "/api/learning-sessions/$($session.session_id)/exercises/$($exercise.id)/submit" -Body @{
        attempt_id = $fixedRun.attempt_id
        code = $fixedCode
        filled_blanks = $filledBlanks
        submit_version = 1
        explanation = $studentExplanation
        hint_usage_count = 0
        error_count = 0
    }
    $submitResult = $submit.code_completion_result.result
    Assert-Condition (($submitResult -eq "passed") -or ($submitResult -eq "easy")) "Submit did not pass" $submit

    $dashboardAfter = Invoke-AearnJson -Method GET -Path "/api/dashboard?user_id=$([Uri]::EscapeDataString($user.id))"
    $resume = Invoke-AearnJson -Method GET -Path "/api/learning-sessions/resume?user_id=$([Uri]::EscapeDataString($user.id))&plan_id=$([Uri]::EscapeDataString($planId))"

    $summary = [ordered]@{
        health = $health
        course = $course.title
        user_id = $user.id
        plan_id = $planId
        session_id = $session.session_id
        failed_run = [ordered]@{
            runtime_status = $failedRun.runtime_status
            test_pass_rate = $failedRun.test_pass_rate
            failed_test_count = $failedTests.Count
        }
        explain_error = [ordered]@{
            generation_source = $explanation.generation_source
            generation_model = $explanation.generation_model
            error_cause = $explanation.error_cause
            replay_idempotent = $replayedExplanation.idempotency_replayed
        }
        fixed_run = [ordered]@{
            runtime_status = $fixedRun.runtime_status
            test_pass_rate = $fixedRun.test_pass_rate
        }
        explanation_check = [ordered]@{
            result = $explanationCheck.result
            score = $explanationCheck.score
        }
        submit = [ordered]@{
            result = $submitResult
            next_action = $submit.next_action
            fsrs_rating = $submit.code_completion_result.fsrs_rating
        }
        dashboard_after = [ordered]@{
            resume_available = $dashboardAfter.resume_available
            today_review_count = $dashboardAfter.today_review_count
            next_entry_point = $dashboardAfter.next_entry_point
        }
        resume = [ordered]@{
            resume_available = $resume.resume_available
            next_entry_point = $resume.next_entry_point
        }
    }

    Write-Host "Live LLM smoke passed."
    $summary | ConvertTo-Json -Depth 20
} finally {
    if ($startedServer -and $null -ne $serverProcess -and -not $KeepServer) {
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped local API server pid=$($serverProcess.Id)"
    } elseif ($startedServer -and $KeepServer) {
        Write-Host "Keeping local API server running pid=$($serverProcess.Id)"
    }

    if (-not $KeepServer) {
        Remove-Item -LiteralPath $outLog, $errLog -ErrorAction SilentlyContinue
    }
}
