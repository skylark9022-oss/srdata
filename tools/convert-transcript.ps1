param(
    [Parameter(Mandatory)] [string] $In,
    [Parameter(Mandatory)] [string] $Out,
    [string] $Title = "세션 기록"
)

function Strip-Reminders([string] $s) {
    $s = [regex]::Replace($s, '(?s)<system-reminder>.*?</system-reminder>', '')
    $s = [regex]::Replace($s, '(?s)<ide_selection>.*?</ide_selection>', '')
    return $s.Trim()
}

function Tool-Hint($name, $inp) {
    switch -Regex ($name) {
        '^(Write|Edit|Read)$'            { return $inp.file_path }
        '^PowerShell$'                   { return $inp.description }
        '^AskUserQuestion$'              { return ($inp.questions | ForEach-Object { $_.question }) -join ' / ' }
        'propose_branch'                 { return "suggested: $($inp.suggested)" }
        'change_directory'               { return $inp.path }
        'update_plan'                    { if ($inp.items) { return ($inp.items | ForEach-Object { $_.content }) -join ' → ' } else { return 'advance' } }
        'wrap_up'                        { return $inp.recap }
        'ToolSearch'                     { return $inp.query }
        default                          { return '' }
    }
}

function Add-Heading([string] $h) {
    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -ne '') { $lines.Add('') }
    $lines.Add($h); $lines.Add('')
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# $Title")
$lines.Add("")
$lines.Add("Claude Code 세션 기록을 읽기 쉽게 정리한 것. 도구 호출은 한 줄로 요약했고, 내부 사고와 시스템 안내문은 뺐다.")
$lines.Add("")

$toolNames = @{}
$firstTs = $null

Get-Content -Path $In -Encoding UTF8 | ForEach-Object {
    $o = $_ | ConvertFrom-Json
    if ($o.type -notin @('user', 'assistant')) { return }
    if (-not $firstTs -and $o.timestamp) { $firstTs = $o.timestamp }
    $content = $o.message.content

    if ($o.type -eq 'user') {
        if ($content -is [string]) {
            $t = Strip-Reminders $content
            if ($t) { Add-Heading "## 사용자"; $lines.Add($t); $lines.Add("") }
            return
        }
        foreach ($b in $content) {
            if ($b.type -eq 'text') {
                $t = Strip-Reminders $b.text
                if ($t) { Add-Heading "## 사용자"; $lines.Add($t); $lines.Add("") }
            }
            elseif ($b.type -eq 'tool_result') {
                $name = $toolNames[$b.tool_use_id]
                if ($name -eq 'AskUserQuestion') {
                    $txt = if ($b.content -is [string]) { $b.content } else { ($b.content | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.text }) -join "`n" }
                    if ($lines[$lines.Count - 1] -ne '') { $lines.Add('') }
                    $lines.Add("> **사용자 답변:** $(Strip-Reminders $txt)"); $lines.Add("")
                }
            }
        }
        return
    }

    # assistant
    foreach ($b in $content) {
        if ($b.type -eq 'text') {
            $t = $b.text.Trim()
            if ($t) { Add-Heading "## Claude"; $lines.Add($t); $lines.Add("") }
        }
        elseif ($b.type -eq 'tool_use') {
            $toolNames[$b.id] = $b.name
            $short = $b.name -replace '^mcp__[^_]+(_[^_]+)*?__', ''
            $hint = Tool-Hint $b.name $b.input
            if ($hint) { $hint = ($hint -replace '\s+', ' ').Trim(); if ($hint.Length -gt 160) { $hint = $hint.Substring(0, 157) + '...' } }
            $lines.Add("- 🔧 ``$short``$(if ($hint) { " — $hint" })")
        }
    }
}

if ($firstTs) { $lines.Insert(2, "시작: $firstTs"); $lines.Insert(3, "") }

$dir = Split-Path -Parent $Out
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($Out, ($lines -join "`n") + "`n", $utf8)
"written: $Out ($(($lines -join "`n").Length) chars)"
