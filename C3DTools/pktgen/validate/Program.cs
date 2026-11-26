// Validasi struktur XAML subassembly: dimuat dengan pustaka workflow yang sama dengan yang dipakai
// Civil 3D / Subassembly Composer 2027 (folder SACRuntime). Pakai: validate <file.xaml> [...]
using System;
using System.Activities;
using System.Activities.Statements;
using System.Activities.XamlIntegration;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.Loader;
using System.Xaml;

class Program
{
    static readonly string[] Dirs =
    {
        @"C:\Program Files\Autodesk\AutoCAD 2027\C3D\SACRuntime",
        @"C:\Program Files\Autodesk\AutoCAD 2027\C3D",
        @"C:\Program Files\Autodesk\AutoCAD 2027"
    };

    static int Main(string[] args)
    {
        // SAC memuat XAML dengan culture invarian (titik desimal); samakan, karena Windows ini berformat Indonesia
        System.Globalization.CultureInfo.DefaultThreadCurrentCulture = System.Globalization.CultureInfo.InvariantCulture;
        System.Threading.Thread.CurrentThread.CurrentCulture = System.Globalization.CultureInfo.InvariantCulture;
        AssemblyLoadContext.Default.Resolving += (ctx, name) =>
        {
            foreach (string d in Dirs)
            {
                string p = Path.Combine(d, name.Name + ".dll");
                if (File.Exists(p)) { try { return ctx.LoadFromAssemblyPath(p); } catch { } }
            }
            return null;
        };
        int bad = 0;
        foreach (string file in args)
        {
            try { Check(file); }
            catch (Exception ex)
            {
                bad++;
                Console.WriteLine("GAGAL " + Path.GetFileName(file) + ": " + ex.GetType().Name + ": " + ex.Message);
                if (ex.InnerException != null) Console.WriteLine("   inner: " + ex.InnerException.Message);
            }
        }
        return bad;
    }

    static void Check(string file)
    {
        using var xr = new XamlXmlReader(file, new XamlXmlReaderSettings { LocalAssembly = typeof(Program).Assembly });
        using XamlReader br = ActivityXamlServices.CreateBuilderReader(xr);
        var builder = (ActivityBuilder)XamlServices.Load(br);
        int steps = 0, decisions = 0;
        var kinds = new SortedDictionary<string, int>();
        if (builder.Implementation is Flowchart fc)
            foreach (FlowNode n in fc.Nodes)
            {
                if (n is FlowStep s)
                {
                    steps++;
                    string k = s.Action?.GetType().Name ?? "(kosong)";
                    kinds[k] = kinds.TryGetValue(k, out int c) ? c + 1 : 1;
                }
                else if (n is FlowDecision) decisions++;
            }
        Console.WriteLine("OK " + Path.GetFileName(file) + ": class=" + builder.Name + " properti=" + builder.Properties.Count +
                          " langkah=" + steps + " percabangan=" + decisions);
        foreach (var kv in kinds) Console.WriteLine("   " + kv.Key + " x" + kv.Value);
    }
}
