# Validasi flowchart (termasuk kompilasi rumus VB) dengan mesin workflow .NET Framework yang dipakai SAC.
# Pakai: powershell -STA -File sac_validate.ps1 <file.xaml> [...]
# Bandingkan dengan file yang diketahui berjalan di SAC: error yang muncul di keduanya berasal dari
# cara uji ini (mis. import namespace), bukan dari flowchart.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Xaml)

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
Add-Type -AssemblyName System.Xaml, System.Activities
[void][Reflection.Assembly]::LoadFrom("$sac\Subassembly.WorkflowEngine.dll")
[void][Reflection.Assembly]::LoadFrom("$sac\Subassembly.ActivityLibrary.dll")
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture

foreach ($f in $Xaml) {
    "=== " + (Split-Path (Split-Path $f -Parent) -Leaf)
    try {
        $act = [System.Activities.XamlIntegration.ActivityXamlServices]::Load($f)
        $res = [System.Activities.Validation.ActivityValidationServices]::Validate($act)
        "error=" + $res.Errors.Count + " peringatan=" + $res.Warnings.Count
        $res.Errors | Group-Object Message | Sort-Object Count -Descending | Select-Object -First 25 | ForEach-Object {
            "  x" + $_.Count + "  " + $_.Name + "   [mis. di: " + $_.Group[0].Source.DisplayName + "]"
        }
    } catch {
        $ex = $_.Exception
        while ($ex.InnerException) { $ex = $ex.InnerException }
        "GAGAL memuat: " + $ex.GetType().Name + ": " + $ex.Message
    }
}
