// INVJLS - inventarisasi (hanya baca) untuk laporan: region corridor + assembly, PI alinyemen,
// dan teks nama jembatan/sungai di sekitar alignment Main Road. Hasil: %TEMP%\c3d_inv_*.csv
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivEntity = Autodesk.Civil.DatabaseServices.Entity;

namespace C3DRambu
{
    public class InventoryCommands
    {
        static string F(double v) { return v.ToString("0.000", CultureInfo.InvariantCulture); }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "'").Replace("\r", " ").Replace("\n", " ") + "\""; }

        [CommandMethod("INVJLS")]
        public void Run()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);
            string corName = "15 Nov_Main Road";
            string tmp = Path.GetTempPath();

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                // 1. semua corridor -> baseline -> region + assembly
                var sb = new StringBuilder();
                sb.AppendLine("Corridor;Baseline Alignment;Region;Start;End;Panjang;Assembly");
                Alignment main = null;
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c == null) continue;
                    foreach (Baseline bl in c.Baselines)
                    {
                        string an = "";
                        Alignment al = null;
                        try { al = tr.GetObject(bl.AlignmentId, OpenMode.ForRead) as Alignment; an = al != null ? al.Name : ""; } catch { }
                        if (main == null && al != null && string.Equals(c.Name, corName, StringComparison.OrdinalIgnoreCase)) main = al;
                        foreach (BaselineRegion r in bl.BaselineRegions)
                        {
                            string asm = "";
                            try { asm = ((CivEntity)tr.GetObject(r.AssemblyId, OpenMode.ForRead)).Name; } catch { }
                            sb.AppendLine(string.Join(";", Q(c.Name), Q(an), Q(r.Name), F(r.StartStation), F(r.EndStation), F(r.EndStation - r.StartStation), Q(asm)));
                        }
                    }
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_inv_regions.csv"), sb.ToString(), new UTF8Encoding(true));
                if (main == null) { ed.WriteMessage("\nINVJLS: corridor {0} tidak ditemukan.", corName); return; }

                // 2. elemen alinyemen horizontal Main Road (busur: radius & STA)
                sb.Clear();
                sb.AppendLine("No;Tipe;Start;End;Panjang;Radius;Arah");
                int n = 0;
                foreach (AlignmentEntity ae in main.Entities)
                {
                    for (int i = 0; i < ae.SubEntityCount; i++)
                    {
                        AlignmentSubEntity se = ae[i];
                        n++;
                        string typ = se.SubEntityType.ToString(), rad = "", dir = "";
                        var arc = se as AlignmentSubEntityArc;
                        if (arc != null) { rad = F(arc.Radius); dir = arc.Clockwise ? "kanan (CW)" : "kiri (CCW)"; }
                        sb.AppendLine(string.Join(";", n.ToString(), typ, F(se.StartStation), F(se.EndStation), F(se.Length), rad, dir));
                    }
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_inv_alignment.csv"), sb.ToString(), new UTF8Encoding(true));

                // 3. teks nama jembatan / sungai dekat Main Road
                sb.Clear();
                sb.AppendLine("Layer;STA;Offset;Teks");
                var rx = new Regex(@"JEMBATAN|JBT|SUNGAI|KALI|BENGAWAN|KALEN|AVOUR|AFVOUR|BOX\s*CULVERT|GORONG", RegexOptions.IgnoreCase);
                var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
                int nt = 0;
                foreach (ObjectId id in ms)
                {
                    if (!id.ObjectClass.DxfName.Contains("TEXT")) continue;
                    var e = tr.GetObject(id, OpenMode.ForRead);
                    string txt = null; Autodesk.AutoCAD.Geometry.Point3d p = default(Autodesk.AutoCAD.Geometry.Point3d); string lay = "";
                    var dt = e as DBText; var mt = e as MText;
                    if (dt != null) { txt = dt.TextString; p = dt.Position; lay = dt.Layer; }
                    else if (mt != null) { txt = mt.Text; p = mt.Location; lay = mt.Layer; }
                    if (txt == null || !rx.IsMatch(txt)) continue;
                    double st = 0, off = 0;
                    try { main.StationOffset(p.X, p.Y, ref st, ref off); } catch { continue; }
                    if (Math.Abs(off) > 250) continue;
                    sb.AppendLine(string.Join(";", Q(lay), F(st), F(off), Q(txt)));
                    nt++;
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_inv_text.csv"), sb.ToString(), new UTF8Encoding(true));
                tr.Commit();
                ed.WriteMessage("\nINVJLS: alignment {0}, {1} elemen, {2} teks. File di {3}c3d_inv_*.csv", main.Name, n, nt, tmp);
            }
        }
    }
}
