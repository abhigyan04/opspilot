# Run the grounding baseline

Run these PowerShell blocks from the repository root with the virtual environment
active and Ollama running. This performs nine diagnosis calls, without retrieval
or PostgreSQL. Do not edit code or update the model during the batch.

The [source manifest](grounding-baseline-sources.json) pins three existing local
reports by SHA-256. These files are under ignored `out/` paths and are not bundled
in a fresh clone. Missing or changed inputs must be resolved before execution;
do not substitute reports without creating a new source manifest.

## Prepare and record provenance

This block validates all sources before creating a unique output directory. It
copies the original reports unchanged and captures runtime model identity. It
does not call a model for generation.

```powershell
$ErrorActionPreference = 'Stop'
$baselinePython = (Resolve-Path '.venv/Scripts/python.exe').Path
$pythonIdentity = & $baselinePython -c "import json,sys; print(json.dumps({'executable':sys.executable,'version':sys.version}))" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify project Python.' }
$baselinePlan = Get-Content -Raw docs/grounding-baseline-sources.json | ConvertFrom-Json
foreach ($source in $baselinePlan.sources) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.path).Hash.ToLowerInvariant()
    if ($actual -ne $source.sha256) { throw "Source hash mismatch: $($source.path)" }
}

$ollamaEndpoint = if ($env:OLLAMA_HOST) { $env:OLLAMA_HOST.TrimEnd('/') } else { 'http://localhost:11434' }
$ollamaVersion = Invoke-RestMethod "$ollamaEndpoint/api/version"
$availableModels = Invoke-RestMethod "$ollamaEndpoint/api/tags"
$selectedModel = @($availableModels.models | Where-Object { $_.name -eq $baselinePlan.diagnosis_model })
if ($selectedModel.Count -ne 1) { throw 'Expected exactly one installed qwen3:8b model.' }

$baselineCommit = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine repository commit.' }
$baselineStatus = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine repository status.' }
$baselineDiff = @(git diff HEAD --binary)
if ($LASTEXITCODE -ne 0) { throw 'Cannot capture working-tree changes.' }

$baselineDir = "out/grounding-baseline/$([guid]::NewGuid())"
New-Item -ItemType Directory -Path "$baselineDir/sources" | Out-Null
Copy-Item docs/grounding-baseline-sources.json "$baselineDir/source-manifest.json"
Copy-Item docs/evaluation-plan.md "$baselineDir/evaluation-plan.md"
$baselineDiff | Set-Content -Encoding utf8 "$baselineDir/working-tree.patch"

$baselineInputs = foreach ($source in $baselinePlan.sources) {
    $snapshot = "$baselineDir/sources/$($source.run_id).json"
    Copy-Item -LiteralPath $source.path -Destination $snapshot
    if ((Get-FileHash $snapshot -Algorithm SHA256).Hash.ToLowerInvariant() -ne $source.sha256) {
        throw "Snapshot hash mismatch: $snapshot"
    }
    @{ case_id = $source.case_id; path = $snapshot; sha256 = $source.sha256 }
}

# Fingerprint the actual Python source, including untracked Python files.
$codeHashes = @(Get-ChildItem app,evals -Recurse -File -Filter '*.py' | ForEach-Object {
    @{ path = [IO.Path]::GetRelativePath((Get-Location).Path, $_.FullName);
       sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
})
@{
    protocol = $baselinePlan.protocol
    started_at = [DateTimeOffset]::UtcNow.ToString('o')
    commit = $baselineCommit
    working_tree = $baselineStatus
    code_hashes = $codeHashes
    model = $selectedModel[0].name
    model_digest = $selectedModel[0].digest
    ollama_version = $ollamaVersion.version
    python = $pythonIdentity
    settings = $baselinePlan.diagnosis_settings
    seeds = $baselinePlan.seeds
    with_references = $false
    sources = @($baselineInputs)
    planned_attempts = 9
} | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 "$baselineDir/manifest.json"
& $baselinePython -m pip freeze | Set-Content -Encoding utf8 "$baselineDir/python-packages.txt"
if ($LASTEXITCODE -ne 0) { throw 'Cannot capture Python package versions.' }
Write-Output "Prepared batch: $baselineDir"
```

The patch records tracked changes; untracked files are listed and Python source
is fingerprinted, but hashes are not a source archive. Preserve any untracked
implementation files or commit them before claiming a reproducible release.

## Execute the nine attempts

Run in the same PowerShell session. Each attempt gets a separate directory and
console log. A failed attempt is retained, and subsequent planned attempts still
run. Do not rerun this block in the same batch directory; use a new batch for
additional attempts.

```powershell
if (Test-Path "$baselineDir/attempts") { throw 'This batch already has attempts. Prepare a new batch.' }
New-Item -ItemType Directory -Path "$baselineDir/attempts" | Out-Null
foreach ($source in $baselineInputs) {
    foreach ($seed in $baselinePlan.seeds) {
        $attemptDir = "$baselineDir/attempts/$($source.case_id)-seed-$seed"
        New-Item -ItemType Directory -Path $attemptDir | Out-Null
        & $baselinePython -m evals.replay $source.path --model qwen3:8b --seed $seed --num-ctx 8192 --num-predict 2048 --temperature 0.6 --top-p 0.95 --top-k 20 --think --output-dir $attemptDir 2> "$attemptDir/stderr.txt" |
            Tee-Object -FilePath "$attemptDir/console.txt"
        $attemptExit = $LASTEXITCODE
        @{ case_id = $source.case_id; seed = $seed; exit_code = $attemptExit; directory = $attemptDir } |
            ConvertTo-Json | Set-Content -Encoding utf8 "$attemptDir/attempt.json"
    }
}
Get-ChildItem "$baselineDir/attempts" -Recurse -Filter attempt.json |
    ForEach-Object { Get-Content -Raw $_.FullName | ConvertFrom-Json } |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 "$baselineDir/attempt-summary.json"
Get-Content -Raw "$baselineDir/attempt-summary.json"
Write-Output "Batch directory: $baselineDir"
```

Inspect actual report statuses as well as exit codes. An infrastructure failure
may produce no report; the console log and attempt metadata still preserve that
attempt. These are unreviewed outputs, not scored results. The next step is to
review each report using the criteria in [the evaluation plan](evaluation-plan.md).
