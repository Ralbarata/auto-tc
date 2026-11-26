# Jalankan sac_doc_exec.ps1 di proses terpisah; bila proses itu berhenti di kotak pesan, baca teks kotak
# pesannya lewat UI Automation lalu hentikan prosesnya.
# Pakai: powershell -File sac_doc_exec_run.ps1 <file.pkt> [LayoutMode|RoadwayMode]
param([string]$Pkt, [string]$Mode = "")
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$here = Split-Path $MyInvocation.MyCommand.Path
$out = Join-Path $env:TEMP ("c3dt_docexec_" + [Guid]::NewGuid().ToString("N") + ".txt")
$argList = @('-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', "`"$here\sac_doc_exec.ps1`"", "`"$Pkt`"")
if ($Mode) { $argList += $Mode }
$p = Start-Process powershell.exe -ArgumentList $argList -RedirectStandardOutput $out -PassThru -WindowStyle Minimized
$deadline = [DateTime]::Now.AddSeconds(75)
$dialog = $null
while (-not $p.HasExited -and [DateTime]::Now -lt $deadline) {
    Start-Sleep -Milliseconds 1500
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$p.Id)
    $wins = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
    foreach ($w in $wins) {
        $texts = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
            (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Text)))
        $t = @($texts | ForEach-Object { $_.Current.Name }) -join "`n"
        if ($t.Trim()) { $dialog = "KOTAK PESAN [" + $w.Current.Name + "]:`n" + $t }
    }
    if ($dialog) { break }
}
if (-not $p.HasExited) { $p.Kill() }
Get-Content $out -ErrorAction SilentlyContinue
if ($dialog) { $dialog.Substring(0, [Math]::Min(3500, $dialog.Length)) }
[IO.File]::Delete($out)
