// ASMDUMP - ekspor isi assembly (parameter, point, link, shape tiap subassembly) ke CSV,
// sebagai acuan membuat ulang subassembly di Subassembly Composer saat file .pkt hilang.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivPoint = Autodesk.Civil.DatabaseServices.Point;

namespace C3DTools
{
    public static class AsmDumpCore
    {
        const string S = ";";

        public static string Dump(Transaction tr, IEnumerable<ObjectId> assemblyIds)
        {
            var sb = new StringBuilder();
            sb.AppendLine("sep=" + S);
            foreach (ObjectId aid in assemblyIds)
            {
                var asm = (Assembly)tr.GetObject(aid, OpenMode.ForRead);
                sb.AppendLine();
                sb.AppendLine("ASSEMBLY" + S + Q(asm.Name));
                foreach (AssemblyGroup g in asm.Groups)
                {
                    foreach (ObjectId sid in g.GetSubassemblyIds())
                    {
                        var sa = (Subassembly)tr.GetObject(sid, OpenMode.ForRead);
                        try { DumpSubassembly(sb, sa, g.Name); }
                        catch (System.Exception ex) { sb.AppendLine("GAGAL membaca subassembly" + S + Q(sa.Name) + S + Q(ex.Message)); }
                    }
                }
            }
            return sb.ToString();
        }

        static void DumpSubassembly(StringBuilder sb, Subassembly sa, string group)
        {
            sb.AppendLine();
            sb.AppendLine("SUBASSEMBLY" + S + Q(sa.Name));
            sb.AppendLine("Grup" + S + Q(group));
            Try(sb, "Sisi", () => sa.HasSide ? sa.Side.ToString() : "(tanpa sisi)");
            Try(sb, "Buatan SAC", () => sa.IsFromSubassemblyComposer ? "Ya" : "Tidak");
            Try(sb, "Class/Macro", () => sa.GeometryGenerator.MacroOrClassName);
            Try(sb, "DLL/Project", () => sa.GeometryGenerator.ProjectOrAssemblyName);
            Try(sb, "Mode", () => sa.GeometryGenerator.GeometryGenerateMode.ToString());
            Try(sb, "Origin X;Y", () => N(sa.Origin.X) + S + N(sa.Origin.Y));

            sb.AppendLine("PARAMETER" + S + "Tipe" + S + "Nilai" + S + "Keterangan");
            foreach (var p in sa.ParamsDouble) sb.AppendLine(Q(p.DisplayName) + S + "Double" + S + N(p.Value) + S + Q(p.Description));
            foreach (var p in sa.ParamsLong) sb.AppendLine(Q(p.DisplayName) + S + "Integer" + S + p.Value + S + Q(p.Description));
            foreach (var p in sa.ParamsBool) sb.AppendLine(Q(p.DisplayName) + S + "Yes/No" + S + (p.Value ? "Yes" : "No") + S + Q(p.Description));
            foreach (var p in sa.ParamsString) sb.AppendLine(Q(p.DisplayName) + S + "String" + S + Q(p.Value) + S + Q(p.Description));

            // offset/elevasi juga ditulis relatif terhadap point pertama (biasanya origin di SAC)
            double o0 = 0, e0 = 0; bool first = true;
            sb.AppendLine("POINT" + S + "Kode" + S + "Offset" + S + "Elevasi" + S + "dOffset thd P pertama" + S + "dElev thd P pertama");
            foreach (CivPoint pt in sa.Points)
            {
                if (first) { o0 = pt.Offset; e0 = pt.Elevation; first = false; }
                sb.AppendLine("P" + pt.Index + S + Q(Codes(pt.Codes)) + S + N(pt.Offset) + S + N(pt.Elevation) + S + N(pt.Offset - o0) + S + N(pt.Elevation - e0));
            }

            sb.AppendLine("LINK" + S + "Kode" + S + "Point" + S + "dX" + S + "dY" + S + "Slope %");
            foreach (Link lk in sa.Links)
            {
                var idx = new List<string>();
                CivPoint a = null, b = null;
                foreach (CivPoint pt in lk.Points) { idx.Add("P" + pt.Index); if (a == null) a = pt; b = pt; }
                string dx = "", dy = "", sl = "";
                if (a != null && b != null && !ReferenceEquals(a, b))
                {
                    double x = b.Offset - a.Offset, y = b.Elevation - a.Elevation;
                    dx = N(x); dy = N(y);
                    sl = Math.Abs(x) < 1e-9 ? "vertikal" : N(y / Math.Abs(x) * 100.0);
                }
                sb.AppendLine("L" + lk.Index + S + Q(Codes(lk.Codes)) + S + string.Join(" - ", idx) + S + dx + S + dy + S + sl);
            }

            sb.AppendLine("SHAPE" + S + "Kode" + S + "Link");
            foreach (Autodesk.Civil.DatabaseServices.Shape sh in sa.Shapes)
            {
                var idx = new List<string>();
                foreach (Link lk in sh.Links) idx.Add("L" + lk.Index);
                sb.AppendLine("S" + sh.Index + S + Q(Codes(sh.Codes)) + S + string.Join(" ", idx));
            }
        }

        static void Try(StringBuilder sb, string label, Func<string> get)
        {
            string v;
            try { v = get(); } catch (System.Exception) { v = "(tidak terbaca)"; }
            sb.AppendLine(label + S + v);
        }

        static string Codes(CodeCollection codes)
        {
            var list = new List<string>();
            foreach (string c in codes) list.Add(c);
            return string.Join(", ", list);
        }

        static string N(double v) { return v.ToString("0.####", CultureInfo.InvariantCulture); }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "\"\"") + "\""; }
    }

    public class AsmDumpCommands
    {
        [CommandMethod("ASMDUMP")]
        public void AsmDump()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);

            // Boleh pilih banyak assembly sekaligus (klik satu per satu atau window), Enter untuk selesai.
            // Langsung Enter tanpa memilih = semua assembly di drawing.
            var pso = new PromptSelectionOptions
            {
                MessageForAdding = "\nPilih assembly, boleh banyak (Enter = selesai; langsung Enter = semua assembly): "
            };
            PromptSelectionResult psr = ed.GetSelection(pso);
            if (psr.Status == PromptStatus.Cancel) return;

            var ids = new List<ObjectId>();
            if (psr.Status == PromptStatus.OK)
            {
                RXClass asmClass = RXObject.GetClass(typeof(Assembly));
                foreach (ObjectId id in psr.Value.GetObjectIds())
                    if (id.ObjectClass.IsDerivedFrom(asmClass)) ids.Add(id);
                if (ids.Count == 0)
                {
                    ed.WriteMessage("\nTidak ada assembly di antara object yang dipilih (klik garis baseline assembly).");
                    return;
                }
            }
            else
            {
                foreach (ObjectId id in civ.AssemblyCollection) ids.Add(id);
            }
            if (ids.Count == 0) { ed.WriteMessage("\nTidak ada assembly di drawing ini."); return; }

            string text;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                text = AsmDumpCore.Dump(tr, ids);
                tr.Commit();
            }

            string dir = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), baseName = "Drawing";
            try
            {
                if (Path.IsPathRooted(doc.Name)) { dir = Path.GetDirectoryName(doc.Name); baseName = Path.GetFileNameWithoutExtension(doc.Name); }
            }
            catch (System.Exception) { }
            // nama file diberi jam supaya ekspor sebelumnya tidak tertimpa
            string path = Path.Combine(dir, baseName + "_assembly_" + DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".csv");
            try
            {
                File.WriteAllText(path, text, new UTF8Encoding(true));
                ed.WriteMessage("\n{0} assembly diekspor ke: {1}", ids.Count, path);
            }
            catch (System.Exception ex)
            {
                ed.WriteMessage("\nGagal menulis {0}: {1}", path, ex.Message);
            }
        }
    }
}
