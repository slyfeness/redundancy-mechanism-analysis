param(
    [string]$Output,
    [string]$Python = 'python',
    [ValidateSet('custom', 'deepseek')][string]$Provider = 'custom',
    [switch]$RememberKey,
    [ValidateSet('terminal', 'dialog')][string]$InputMode = 'terminal'
)

$ErrorActionPreference = 'Stop'
if ($RememberKey -and $Provider -ne 'deepseek') {
    throw 'RememberKey requires Provider deepseek.'
}
$packageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $packageRoot 'src')).Path
if ([string]::IsNullOrWhiteSpace($Output)) {
    $runName = 'judge-smoke-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $Output = Join-Path (Join-Path (Join-Path $packageRoot 'outputs') $runName) 'result.json'
}
$previousPythonPath = $env:PYTHONPATH
$previousEncoding = $env:PYTHONIOENCODING
Push-Location -LiteralPath $packageRoot
try {
    $env:PYTHONPATH = $sourceRoot
    $env:PYTHONIOENCODING = 'utf-8'
    $pythonArguments = @('-m', 'ledger_grpo.judge_smoke', '--output', $Output)
    if ($Provider -ne 'custom') { $pythonArguments += @('--provider', $Provider) }
    if ($RememberKey) { $pythonArguments += '--remember-key' }
    if ($InputMode -ne 'terminal') { $pythonArguments += @('--input-mode', $InputMode) }
    & $Python @pythonArguments
    $runExitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONIOENCODING = $previousEncoding
    Pop-Location
}
exit $runExitCode
