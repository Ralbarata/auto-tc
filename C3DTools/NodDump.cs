// C3DT_NODDUMP - diagnostik: telusuri named objects dictionary dan extension dictionary subassembly,
// untuk mencari paket subassembly (PKT) yang tertanam di dalam DWG. Hanya membaca drawing.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using AcDbObject = Autodesk.AutoCAD.DatabaseServices.DBObject;

namespace C3DTools
{
    public class NodDump
    {
        StringBuilder log = new StringBuilder();
        string outDir;
        int blobNo;

        [CommandMethod("C3DT_NODDUMP")]
        public void Run()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            outDir = Environment.GetEnvironmentVariable("C3DT_TESTDIR") ?? Path.GetTempPath();
            try
            {
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    log.AppendLine("== Named Objects Dictionary");
                    Walk(tr, db.NamedObjectsDictionaryId, "NOD", 1, new HashSet<ObjectId>());

                    log.AppendLine("== Subassembly");
                    CivilDocument civ = CivilDocument.GetCivilDocument(db);
                    var seen = new HashSet<string>();
                    foreach (ObjectId sid in civ.SubassemblyCollection)
                    {
                        var sa = (Subassembly)tr.GetObject(sid, OpenMode.ForRead);
                        string cls = "?", prj = "?", emb = "?";
                        try { cls = sa.GeometryGenerator.MacroOrClassName; prj = sa.GeometryGenerator.ProjectOrAssemblyName; } catch (System.Exception) { }
                        try { emb = sa.UseEmbeddedProject.ToString(); } catch (System.Exception) { }
                        if (!seen.Add(cls)) continue;
                        log.AppendLine($"  {sa.Name} | class={cls} | embedded={emb} | {prj}");
                        if (!sa.ExtensionDictionary.IsNull)
                            Walk(tr, sa.ExtensionDictionary, "    xdict", 3, new HashSet<ObjectId>());
                    }
                    tr.Commit();
                }
            }
            catch (System.Exception ex) { log.AppendLine("GAGAL: " + ex); }

            // folder kerja runtime SAC (tempat PKT diekstrak saat subassembly dimuat)
            try
            {
                log.AppendLine("== Runtime SAC");
                foreach (System.Reflection.Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    string an = asm.GetName().Name;
                    if (an == "Microsoft.GeneratedCode") log.AppendLine("  workflow terkompilasi di memori: " + asm.FullName);
                    if (an != "Subassembly.CivilRuntime") continue;
                    Type t = asm.GetType("Autodesk.SubassemblyComposer.FileAccess.PktFileAccess");
                    var fld = t?.GetField("_workingFolder", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public);
                    string wf = fld?.GetValue(null) as string;
                    log.AppendLine("  PktFileAccess._workingFolder = " + (wf ?? "(null)"));
                    if (!string.IsNullOrEmpty(wf) && Directory.Exists(wf))
                        foreach (string f in Directory.GetFileSystemEntries(wf, "*", SearchOption.AllDirectories))
                            log.AppendLine("    " + f);
                }
            }
            catch (System.Exception ex) { log.AppendLine("  (gagal membaca runtime SAC: " + ex.Message + ")"); }
            // nama entri di drawing bisa berisi karakter rusak: jangan sampai menggagalkan penulisan log
            File.WriteAllText(Path.Combine(outDir, "c3dt_noddump.log"), log.ToString(), new UTF8Encoding(false, false));
            doc.Editor.WriteMessage("\nNODDUMP selesai: " + Path.Combine(outDir, "c3dt_noddump.log"));
        }

        void Walk(Transaction tr, ObjectId id, string label, int depth, HashSet<ObjectId> seen)
        {
            if (id.IsNull || !seen.Add(id) || depth > 8) return;
            string pad = new string(' ', depth * 2);
            AcDbObject o;
            try { o = tr.GetObject(id, OpenMode.ForRead); }
            catch (System.Exception ex) { log.AppendLine($"{pad}{label} : (tak terbuka: {ex.Message})"); return; }

            var dict = o as DBDictionary;
            var xr = o as Xrecord;
            if (dict != null)
            {
                log.AppendLine($"{pad}{label} : Dictionary [{dict.Count}]");
                int n = 0;
                foreach (DBDictionaryEntry e in dict)
                {
                    if (++n > 400) { log.AppendLine(pad + "  ... (dipotong)"); break; }
                    Walk(tr, e.Value, e.Key, depth + 1, seen);
                }
            }
            else if (xr != null)
            {
                long bytes = 0; int count = 0; string head = "";
                var blob = new MemoryStream();
                if (xr.Data != null)
                    foreach (TypedValue tv in xr.Data)
                    {
                        count++;
                        var b = tv.Value as byte[];
                        if (b != null)
                        {
                            if (bytes == 0) head = BitConverter.ToString(b, 0, Math.Min(8, b.Length));
                            bytes += b.Length; blob.Write(b, 0, b.Length);
                        }
                        else if (count <= 6) head += $" [{tv.TypeCode}:{Short(tv.Value)}]";
                    }
                log.AppendLine($"{pad}{label} : Xrecord item={count} biner={bytes}B {head}");
                if (bytes > 2000)
                {
                    string f = Path.Combine(outDir, $"blob_{++blobNo}.bin");
                    File.WriteAllBytes(f, blob.ToArray());
                    log.AppendLine($"{pad}  -> disimpan {f}");
                }
            }
            else
            {
                log.AppendLine($"{pad}{label} : {o.GetRXClass().Name}");
                if (!o.ExtensionDictionary.IsNull && depth < 6)
                    Walk(tr, o.ExtensionDictionary, "xdict", depth + 1, seen);
            }
        }

        static string Short(object v)
        {
            string s = v == null ? "" : v.ToString();
            return s.Length > 60 ? s.Substring(0, 60) + "..." : s;
        }
    }
}
