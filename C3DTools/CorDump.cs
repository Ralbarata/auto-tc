// CORDUMP - ekspor data corridor (baseline, region, feature line per kode) ke CSV,
// sebagai bahan menyusun rencana marka otomatis.
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
using CivEntity = Autodesk.Civil.DatabaseServices.Entity;

namespace C3DTools
{
    public class CorDumpCommands
    {
        // kode yang titik-titiknya ditulis lengkap (dijarangkan); kode lain hanya ringkasan
        static readonly string[] KeyWords = { "mark", "road", "shoulder", "curb", "barrier", "guardrail", "etw", "crown", "lane", "median" };
        const double Thin = 10.0;   // jarak minimum antar titik yang ditulis (m)

        static string F(double v) { return v.ToString("0.###", CultureInfo.InvariantCulture); }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "'") + "\""; }

        [CommandMethod("CORDUMP")]
        public void Run()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            var sb = new StringBuilder();
            sb.AppendLine("sep=;");
            sb.AppendLine("DWG;" + Q(doc.Name));
            int nCor = 0, nFl = 0;
            try
            {
                CivilDocument civ = CivilDocument.GetCivilDocument(db);
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    sb.AppendLine("# ALIGNMENT;nama;STA awal;STA akhir;panjang");
                    foreach (ObjectId id in civ.GetAlignmentIds())
                    {
                        var al = tr.GetObject(id, OpenMode.ForRead) as Alignment;
                        if (al == null) continue;
                        sb.AppendLine("ALIGNMENT;" + Q(al.Name) + ";" + F(al.StartingStation) + ";" + F(al.EndingStation) + ";" + F(al.Length));
                    }
                    sb.AppendLine("# SURFACE;nama;tipe");
                    foreach (ObjectId id in civ.GetSurfaceIds())
                    {
                        var s = tr.GetObject(id, OpenMode.ForRead) as CivEntity;
                        if (s != null) sb.AppendLine("SURFACE;" + Q(s.Name) + ";" + s.GetType().Name);
                    }

                    foreach (ObjectId cid in civ.CorridorCollection)
                    {
                        var cor = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                        if (cor == null) { sb.AppendLine("CORRIDOR;(tidak terbaca)"); continue; }
                        nCor++;
                        sb.AppendLine();
                        sb.AppendLine("CORRIDOR;" + Q(cor.Name) + ";outOfDate=" + Safe(() => cor.IsOutOfDate.ToString()));
                        int bi = 0;
                        foreach (Baseline bl in cor.Baselines)
                        {
                            bi++;
                            string alName = Safe(() => ((Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead)).Name);
                            sb.AppendLine("BASELINE;" + bi + ";" + Q(Safe(() => bl.Name)) + ";" + Safe(() => bl.BaselineType.ToString()) + ";" + Q(alName));
                            try
                            {
                                foreach (BaselineRegion reg in bl.BaselineRegions)
                                {
                                    string asm = Safe(() => ((Assembly)tr.GetObject(reg.AssemblyId, OpenMode.ForRead)).Name);
                                    sb.AppendLine("REGION;" + Q(Safe(() => reg.Name)) + ";" + F(reg.StartStation) + ";" + F(reg.EndStation) + ";" + Q(asm));
                                }
                            }
                            catch (System.Exception ex) { sb.AppendLine("REGION;GAGAL;" + Q(ex.Message)); }

                            try { nFl += DumpLines(sb, bl.MainBaselineFeatureLines, "main"); }
                            catch (System.Exception ex) { sb.AppendLine("FL;GAGAL main;" + Q(ex.Message)); }
                            try
                            {
                                int oi = 0;
                                foreach (BaselineFeatureLines ofl in bl.OffsetBaselineFeatureLinesCol)
                                    nFl += DumpLines(sb, ofl, "offset" + (++oi));
                            }
                            catch (System.Exception ex) { sb.AppendLine("FL;GAGAL offset;" + Q(ex.Message)); }
                        }
                    }
                    tr.Commit();
                }
            }
            catch (System.Exception ex)
            {
                sb.AppendLine("GAGAL;" + Q(ex.ToString()));
                ed.WriteMessage("\nCORDUMP berhenti karena error: {0}", ex.Message);
            }

            string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
            string dir = Path.GetDirectoryName(doc.Name);
            string baseName = Path.GetFileNameWithoutExtension(doc.Name) + "_corridor_" + stamp + ".csv";
            string temp = Path.Combine(Path.GetTempPath(), "c3dt_cordump.csv");
            var enc = new UTF8Encoding(true, false);
            try { File.WriteAllText(temp, sb.ToString(), enc); } catch (System.Exception) { }
            string outPath = temp;
            if (!string.IsNullOrEmpty(dir) && Directory.Exists(dir))
            {
                try { outPath = Path.Combine(dir, baseName); File.WriteAllText(outPath, sb.ToString(), enc); }
                catch (System.Exception) { outPath = temp; }
            }
            ed.WriteMessage("\nCORDUMP: {0} corridor, {1} feature line.\nFile: {2}", nCor, nFl, outPath);
        }

        static int DumpLines(StringBuilder sb, BaselineFeatureLines bfl, string where)
        {
            int n = 0;
            if (bfl == null) return 0;
            sb.AppendLine("# FL;lokasi;kode;no;jumlah titik;STA awal;STA akhir;offset min;offset maks");
            foreach (FeatureLineCollection col in bfl.FeatureLineCollectionMap)
            {
                int li = 0;
                foreach (CorridorFeatureLine fl in col)
                {
                    li++; n++;
                    string code = fl.CodeName ?? "";
                    var pts = new List<double[]>();
                    double s0 = double.MaxValue, s1 = double.MinValue, o0 = double.MaxValue, o1 = double.MinValue;
                    foreach (FeatureLinePoint p in fl.FeatureLinePoints)
                    {
                        double st = p.Station, of = p.Offset;
                        if (st < s0) s0 = st; if (st > s1) s1 = st;
                        if (of < o0) o0 = of; if (of > o1) o1 = of;
                        pts.Add(new[] { st, of, p.XYZ.X, p.XYZ.Y, p.XYZ.Z, p.IsBreak ? 1.0 : 0.0 });
                    }
                    if (pts.Count == 0) continue;
                    sb.AppendLine("FL;" + where + ";" + Q(code) + ";" + li + ";" + pts.Count + ";" + F(s0) + ";" + F(s1) + ";" + F(o0) + ";" + F(o1));
                    if (!IsKey(code)) continue;
                    double last = double.NegativeInfinity;
                    for (int i = 0; i < pts.Count; i++)
                    {
                        double[] q = pts[i];
                        bool edge = i == 0 || i == pts.Count - 1 || q[5] > 0 || (i > 0 && pts[i - 1][5] > 0);
                        if (!edge && Math.Abs(q[0] - last) < Thin) continue;
                        last = q[0];
                        sb.AppendLine("PT;" + F(q[0]) + ";" + F(q[1]) + ";" + F(q[4]) + ";" + F(q[2]) + ";" + F(q[3]) + ";" + (q[5] > 0 ? "break" : ""));
                    }
                }
            }
            return n;
        }

        static bool IsKey(string code)
        {
            string c = code.ToLowerInvariant();
            foreach (string k in KeyWords) if (c.Contains(k)) return true;
            return false;
        }

        static string Safe(Func<string> f)
        {
            try { return f() ?? ""; } catch (System.Exception ex) { return "?(" + ex.Message + ")"; }
        }
    }
}
