# Jalankan flowchart dengan mesin Subassembly Composer (WorkflowHost, mode pratinjau) tanpa jendela SAC,
# lalu cetak error dan ringkasan geometri. Pakai: powershell -STA -File sac_run_test.ps1 <file.xaml> [...]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Xaml)

$sac = "C:\Program Files\Autodesk\Subassembly Composer 2027"
Add-Type -ReferencedAssemblies System.Activities, System.Core -TypeDefinition @"
using System; using System.IO; using System.Reflection; using System.Threading; using System.Activities;
using System.Collections.Generic;
public static class SacResolver {
    static string dir; static bool busy;
    public static void Install(string d) { dir = d; AppDomain.CurrentDomain.AssemblyResolve += Resolve; }
    static Assembly Resolve(object s, ResolveEventArgs e) {
        if (busy) return null;
        busy = true;
        try {
            string p = Path.Combine(dir, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        } finally { busy = false; }
    }
}
public class RunWaiter {
    public ManualResetEvent Done = new ManualResetEvent(false);
    public IDictionary<string, object> Outputs; public Exception Fault; public string State;
    public Action<WorkflowApplicationCompletedEventArgs> Callback() {
        return a => { State = a.CompletionState.ToString(); Fault = a.TerminationException; Outputs = a.Outputs; Done.Set(); };
    }
}
"@
[SacResolver]::Install($sac)
Add-Type -AssemblyName System.Xaml, System.Activities, PresentationFramework, PresentationCore, WindowsBase
$eng = [Reflection.Assembly]::LoadFrom("$sac\Subassembly.WorkflowEngine.dll")
[void][Reflection.Assembly]::LoadFrom("$sac\Subassembly.ActivityLibrary.dll")
$we = [Reflection.Assembly]::LoadFrom("$sac\WorkflowEditor.dll")
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
$ns = "Autodesk.SubassemblyComposer.WorkflowEngine."
$hostType = $eng.GetType($ns + "WorkflowHost")

foreach ($f in $Xaml) {
    "=== " + (Split-Path (Split-Path $f -Parent) -Leaf)
    try {
        if ($f -like "*.pkt") {
            # tiru SAC: buka lewat perancang flowchart, lalu jalankan teks XAML hasil serialisasi ulangnya
            $docType = $we.GetType("Autodesk.SubassemblyComposer.WorkflowEditor.SubassemblyDocument")
            $doc = [Activator]::CreateInstance($docType, [object[]]@([string]$f))
            $des = $doc.Workflow.WorkflowDesigner
            # langkah yang dilakukan MainWindow.LoadDocument terhadap enum sebelum pratinjau pertama
            try {
                $ec = $eng.GetType($ns + "EnumContainer").GetProperty("Instance").GetValue($null, $null)
                $ec.WorkflowDesigner = $des
                $ec.EnumTypeData = $doc.EnumDatas
                [void]$ec.GetAllGroupDatas()
                $ec.UpdateEnumTypeData()
                $ec.UpdateWorkflow()
                if ($env:C3DT_RENUMBER) { $ec.AutoSetEnumItemKeys(); $ec.UpdateEnumTypeData(); $ec.UpdateWorkflow(); "penomoran ulang kunci enum dijalankan" }
                "EnumContainer: langkah LoadDocument ditiru"
            } catch { "EnumContainer gagal ditiru: " + $_.Exception.Message }
            # pengelola kode SAC memindai kode semua point/link/shape saat dokumen dibuka
            try {
                $cm = $null
                foreach ($a in @($we, $eng, [Reflection.Assembly]::LoadFrom("$sac\Subassembly.ActivityLibrary.dll"))) {
                    $t = $a.GetTypes() | Where-Object { $_.Name -eq "CodeManager" } | Select-Object -First 1
                    if ($t) { $cm = $t; break }
                }
                if ($cm) {
                    $m = $cm.GetMethod("ResetCodeData", [Reflection.BindingFlags]"Public,NonPublic,Static,Instance")
                    $target = $null
                    if (-not $m.IsStatic) { $target = $cm.GetProperty("Instance", [Reflection.BindingFlags]"Public,NonPublic,Static").GetValue($null, $null) }
                    [void]$m.Invoke($target, [object[]]@($des))
                    "CodeManager.ResetCodeData: OK"
                } else { "CodeManager tidak ditemukan" }
            } catch {
                $ex = $_.Exception; while ($ex.InnerException) { $ex = $ex.InnerException }
                "CodeManager.ResetCodeData GAGAL: " + $ex.GetType().Name + ": " + $ex.Message
                ($ex.StackTrace -split "`n" | Select-Object -First 5) -join "`n"
            }
            $des.Flush()
            $text = $des.Text
            "lewat perancang: panjang XAML " + $text.Length + " (file asli " + (Get-ChildItem (Split-Path $f) -Filter ((Split-Path $f -Leaf))).Length + " B zip)"
            [IO.File]::WriteAllText((Join-Path $env:TEMP "c3dt_designer_roundtrip.xaml"), $text)
        } else {
            $text = [IO.File]::ReadAllText($f)
        }
        $ctor = $hostType.GetConstructors()[0]
        $pars = $ctor.GetParameters()
        $args2 = @($text)
        if ($pars.Count -gt 1) {
            $t2 = $pars[1].ParameterType
            if ($t2 -eq [bool]) { $args2 += $false } elseif ($t2.IsValueType) { $args2 += [Activator]::CreateInstance($t2) } else { $args2 += $null }
        }
        $wh = $ctor.Invoke([object[]]$args2)
        $mpm = $we.GetType("Autodesk.SubassemblyComposer.WorkflowEditor.SACMarkPointManager")
        if ($mpm) { try { $wh.SubassemblyGeometry.MarkPointManager = [Activator]::CreateInstance($mpm) } catch { } }
        $wh.BaseLineInfo = [Activator]::CreateInstance($eng.GetType($ns + "PreviewBaselineInformation"))
        $wh.CantInfo = [Activator]::CreateInstance($eng.GetType($ns + "PreviewCantInformation"))
        # mode pratinjau: variabel lingkungan C3DT_RUNMODE = nama nilai enum SubassemblyRunMode (mis. LayoutMode)
        $modeType = $hostType.GetProperty("RunMode").PropertyType
        "mode tersedia: " + ([Enum]::GetNames($modeType) -join ", ") + "   | dipakai: " + $(if ($env:C3DT_RUNMODE) { $env:C3DT_RUNMODE } else { $wh.RunMode })
        if ($env:C3DT_RUNMODE) { $wh.RunMode = [Enum]::Parse($modeType, $env:C3DT_RUNMODE) }
        $w = New-Object RunWaiter
        $exec = $hostType.GetMethods() | Where-Object { $_.Name -eq "Execute" -and $_.GetParameters()[0].ParameterType.Name -like "Action*" }
        [void]$exec.Invoke($wh, [object[]]@($w.Callback()))
        if (-not $w.Done.WaitOne(60000)) { "TIDAK SELESAI dalam 60 detik"; continue }
        "state=" + $w.State + $(if ($w.Fault) { "  fault=" + $w.Fault.GetType().Name + ": " + $w.Fault.Message } else { "" })
        $errs = @($wh.ErrorInfoCenter.mErrorInfoList)
        if ($w.Outputs -and $w.Outputs.ContainsKey("SubassemblyErrorCenter")) { $errs = @($w.Outputs["SubassemblyErrorCenter"].mErrorInfoList) }
        "error mesin SAC: " + $errs.Count
        $errs | Select-Object -First 15 | ForEach-Object { "   [" + $_.mErrorLevel + "] " + $_.mErrorHost + ": " + $_.mErrorDescption }
        if ($w.Outputs -and $w.Outputs.ContainsKey("Geometry")) {
            $geo = $w.Outputs["Geometry"]
            $props = $geo.GetType().GetProperties() | Where-Object { $_.PropertyType.GetInterface("ICollection") -or $_.PropertyType.Name -like "*Collection*" -or $_.PropertyType.Name -like "*List*" -or $_.PropertyType.Name -like "*Dictionary*" }
            foreach ($p in $props) { try { $v = $p.GetValue($geo, $null); if ($v -ne $null) { "   " + $p.Name + ": " + $v.Count } } catch { } }
            # nama dan koordinat point hasil, untuk dicocokkan dengan hitungan generator
            try {
                $names = @()
                foreach ($pt in $geo.Points) {
                    $o = if ($pt.Value) { $pt.Value } else { $pt }
                    $nm = if ($pt.Key) { $pt.Key } else { $o.Name }
                    $names += ("{0}({1:0.####},{2:0.####})" -f $nm, $o.X, $o.Y)
                }
                "   point: " + ($names -join " ")
            } catch { "   (daftar point tidak terbaca: " + $_.Exception.Message + ")" }
        }
    } catch {
        $ex = $_.Exception
        while ($ex.InnerException) { $ex = $ex.InnerException }
        "GAGAL: " + $ex.GetType().Name + ": " + $ex.Message
        ($ex.StackTrace -split "`n" | Select-Object -First 6) -join "`n"
    }
}
