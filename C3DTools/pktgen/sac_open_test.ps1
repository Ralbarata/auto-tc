# Uji buka PKT dengan kode Subassembly Composer yang sebenarnya, tanpa membuka jendela SAC.
# Windows PowerShell 5.1 berjalan di .NET Framework, sama dengan SAC, jadi pustakanya bisa dimuat langsung.
# Pakai: powershell -STA -File sac_open_test.ps1 <file.pkt> [<file.pkt> ...]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Pkt)

$sac = "C:\Program Files\Autodesk\Subassembly Composer 2027"
# resolver ditulis dalam C#: scriptblock PowerShell sebagai AssemblyResolve bisa memicu rekursi tak berujung
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
[void][Reflection.Assembly]::LoadFrom("$sac\Subassembly.WorkflowEngine.dll")
[void][Reflection.Assembly]::LoadFrom("$sac\Subassembly.ActivityLibrary.dll")
$we = [Reflection.Assembly]::LoadFrom("$sac\WorkflowEditor.dll")
$docType = $we.GetType("Autodesk.SubassemblyComposer.WorkflowEditor.SubassemblyDocument")

# SAC mendaftarkan metadata perancang saat mulai; lakukan hal yang sama bila tersedia
try { (New-Object System.Activities.Core.Presentation.DesignerMetadata).Register() } catch { "catatan: DesignerMetadata gagal: " + $_.Exception.Message }

$fail = 0
foreach ($f in $Pkt) {
    try {
        $doc = [Activator]::CreateInstance($docType, [object[]]@([string]$f))
        $wf = $doc.Workflow
        $root = $wf.WorkflowDesigner.Context.Services.GetService([System.Activities.Presentation.Services.ModelService]).Root
        "OK    " + (Split-Path $f -Leaf) + "  nama=" + $doc.Settings.SAName + "  root=" + $root.ItemType.Name +
            "  superelevasi=" + ($null -ne $doc.SuperelevationPreviewData) + "  cant=" + ($null -ne $doc.CantPreviewData) +
            "  enum=" + ($null -ne $doc.EnumDatas)
    } catch {
        $fail++
        $ex = $_.Exception
        while ($ex.InnerException) { $ex = $ex.InnerException }
        "GAGAL " + (Split-Path $f -Leaf) + ": " + $ex.GetType().Name + ": " + $ex.Message
        ($ex.StackTrace -split "`n" | Select-Object -First 8) -join "`n"
    }
}
exit $fail
