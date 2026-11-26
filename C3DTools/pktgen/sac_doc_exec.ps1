# Tiru pratinjau SAC sedekat mungkin: buka PKT sebagai SubassemblyDocument, lakukan langkah enum dan kode
# seperti MainWindow.LoadDocument, lalu panggil SubassemblyDocument.Execute() (fungsi yang dipakai preview).
# Bila Execute memunculkan kotak pesan error, proses ini berhenti di sana; pemanggil membaca teksnya.
# Pakai: powershell -STA -File sac_doc_exec.ps1 <file.pkt> [LayoutMode|RoadwayMode]
param([string]$Pkt, [string]$Mode = "")

$sac = "C:\Program Files\Autodesk\Subassembly Composer 2027"
Add-Type -TypeDefinition @"
using System; using System.IO; using System.Reflection;
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
"@
[SacResolver]::Install($sac)
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml, System.Activities, System.Activities.Presentation
$eng = [Reflection.Assembly]::LoadFrom("$sac\Subassembly.WorkflowEngine.dll")
[void][Reflection.Assembly]::LoadFrom("$sac\Subassembly.ActivityLibrary.dll")
$we = [Reflection.Assembly]::LoadFrom("$sac\WorkflowEditor.dll")
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
$ns = "Autodesk.SubassemblyComposer.WorkflowEngine."

function Pump([int]$ms) {
    $until = [DateTime]::Now.AddMilliseconds($ms)
    while ([DateTime]::Now -lt $until) {
        $frame = New-Object System.Windows.Threading.DispatcherFrame
        $cb = [System.Windows.Threading.DispatcherOperationCallback] { param($f) $f.Continue = $false; $null }
        [void][System.Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke([System.Windows.Threading.DispatcherPriority]::Background, $cb, $frame)
        [System.Windows.Threading.Dispatcher]::PushFrame($frame)
        Start-Sleep -Milliseconds 25
    }
}

try {
    $docType = $we.GetType("Autodesk.SubassemblyComposer.WorkflowEditor.SubassemblyDocument")
    $doc = [Activator]::CreateInstance($docType, [object[]]@([string]$Pkt))
    $des = $doc.Workflow.WorkflowDesigner
    $ec = $eng.GetType($ns + "EnumContainer").GetProperty("Instance").GetValue($null, $null)
    $ec.WorkflowDesigner = $des
    $ec.EnumTypeData = $doc.EnumDatas
    [void]$ec.GetAllGroupDatas()
    $ec.UpdateEnumTypeData()
    $ec.UpdateWorkflow()
    if ($Mode) { $doc.RunMode = [Enum]::Parse($doc.RunMode.GetType(), $Mode) }
    "dibuka: " + $doc.Settings.SAName + "  mode=" + $doc.RunMode
    [Console]::Out.Flush()
    $doc.Execute()
    Pump 6000
    "state=" + $doc.State
    $errs = @($doc.ErrorInfoCenter.mErrorInfoList)
    "error: " + $errs.Count
    $errs | Select-Object -First 20 | ForEach-Object { "   [" + $_.mErrorLevel + "] " + $_.mErrorHost + ": " + $_.mErrorDescption }
    $g = $doc.Geometries
    if ($g) { "geometri: point=" + $g.Points.Count + " link=" + $g.Links.Count + " shape=" + $g.Shapes.Count } else { "geometri: (kosong)" }
} catch {
    $ex = $_.Exception
    while ($ex.InnerException) { $ex = $ex.InnerException }
    "GAGAL: " + $ex.GetType().Name + ": " + $ex.Message
    ($ex.StackTrace -split "`n" | Select-Object -First 8) -join "`n"
}
