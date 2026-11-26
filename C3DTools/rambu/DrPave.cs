// DRCHK   - ukur lebar antar garis "top saluran" (sampling 5 m) -> %TEMP%\c3d_drchk.csv
// PAVEVOL - volume shape perkerasan per corridor/baseline/region (luas ujung rata-rata) -> %TEMP%\c3d_pavevol.csv
// VOLSIMP - rebuild volume surface "VOL EG vs Corridor *" lalu baca cut/fill -> %TEMP%\c3d_volsimp.csv
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivSurface = Autodesk.Civil.DatabaseServices.Surface;

namespace C3DRambu
{
    public class DrPaveCommands
    {
        static string F(double v) { return v.ToString("0.###", CultureInfo.InvariantCulture); }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "'") + "\""; }
        static Editor Ed { get { return AcApp.DocumentManager.MdiActiveDocument.Editor; } }

        [CommandMethod("DRCHK")]
        public void DrChk() { try { DrChkImpl(); } catch (System.Exception ex) { Ed.WriteMessage("\nDRCHK ERROR: " + ex); } }

        void DrChkImpl()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database;
            var civ = CivilDocument.GetCivilDocument(db);
            var sb = new StringBuilder();
            sb.AppendLine("Handle;Layer;Panjang;S;X;Y;STA;Offset;Lebar;HandleLawan");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Alignment al = null;
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c != null && c.Name == "15 Nov_Main Road") al = (Alignment)tr.GetObject(c.Baselines[0].AlignmentId, OpenMode.ForRead);
                }
                var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
                var curves = new List<Curve>();
                foreach (ObjectId id in ms)
                {
                    var cu = tr.GetObject(id, OpenMode.ForRead) as Curve;
                    if (cu == null || !(cu is Polyline || cu is Line || cu is Polyline2d || cu is Polyline3d)) continue;
                    if (cu.Layer.IndexOf("saluran", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    curves.Add(cu);
                }
                var ext = curves.Select(c => { try { return c.GeometricExtents; } catch { return new Extents3d(); } }).ToList();
                for (int i = 0; i < curves.Count; i++)
                {
                    var c = curves[i];
                    double len = 0;
                    try { len = c.GetDistanceAtParameter(c.EndParam); } catch { continue; }
                    for (double s = 2.5; s < len; s += 5.0)
                    {
                        Point3d p;
                        try { p = c.GetPointAtDist(s); } catch { continue; }
                        double best = 1e9; string bh = "";
                        for (int j = 0; j < curves.Count; j++)
                        {
                            if (j == i) continue;
                            var e = ext[j];
                            if (p.X < e.MinPoint.X - 8 || p.X > e.MaxPoint.X + 8 || p.Y < e.MinPoint.Y - 8 || p.Y > e.MaxPoint.Y + 8) continue;
                            try
                            {
                                var q = curves[j].GetClosestPointTo(new Point3d(p.X, p.Y, curves[j].StartPoint.Z), false);
                                double d = Math.Sqrt((q.X - p.X) * (q.X - p.X) + (q.Y - p.Y) * (q.Y - p.Y));
                                if (d < best) { best = d; bh = curves[j].Handle.ToString(); }
                            }
                            catch { }
                        }
                        double st = 0, off = 0;
                        try { if (al != null) al.StationOffset(p.X, p.Y, ref st, ref off); } catch { st = double.NaN; }
                        sb.AppendLine(string.Join(";", c.Handle.ToString(), Q(c.Layer), F(len), F(s), F(p.X), F(p.Y), F(st), F(off), best < 1e8 ? F(best) : "", bh));
                    }
                }
                tr.Commit();
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_drchk.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            Ed.WriteMessage("\nDRCHK selesai: {0}", path);
        }

        [CommandMethod("PAVEVOL")]
        public void PaveVol() { try { PaveVolImpl(); } catch (System.Exception ex) { Ed.WriteMessage("\nPAVEVOL ERROR: " + ex); } }

        static double StationOf(AppliedAssembly aa)
        {
            foreach (string code in new[] { "Top", "Datum", "Pave", "Pave1", "SubBase", "Base" })
            {
                try
                {
                    foreach (CalculatedLink lk in aa.GetLinksByCode(code))
                        foreach (CalculatedPoint cp in lk.CalculatedPoints)
                            return cp.StationOffsetElevationToBaseline.X;
                }
                catch { }
            }
            return double.NaN;
        }

        void PaveVolImpl()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database;
            var civ = CivilDocument.GetCivilDocument(db);
            string[] codes = { "Pave1", "Pave2", "Base", "SubBase" };
            var sb = new StringBuilder();
            sb.AppendLine("Corridor;Baseline;Region;Assembly;Start;End;N;" + string.Join(";", codes) + ";LebarTop;LebarSubBaseBawah");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c == null) continue;
                    if (!(c.Name == "15 Nov_Main Road" || c.Name.StartsWith("Corridor - ("))) continue;
                    foreach (Baseline bl in c.Baselines)
                    {
                        string an = ""; try { an = ((Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead)).Name; } catch { }
                        foreach (BaselineRegion rg in bl.BaselineRegions)
                        {
                            string asm = ""; try { asm = ((Autodesk.Civil.DatabaseServices.Entity)tr.GetObject(rg.AssemblyId, OpenMode.ForRead)).Name; } catch { }
                            var vol = new double[codes.Length]; double topW = 0, subW = 0;
                            var prevA = new double[codes.Length]; double prevS = double.NaN; int n = 0;
                            AppliedAssemblyCollection col = null;
                            try { col = rg.AppliedAssemblies; } catch { }
                            if (col == null) continue;
                            for (int k = 0; k < col.Count; k++)
                            {
                                var aa = col[k];
                                double s = StationOf(aa);
                                if (double.IsNaN(s)) continue;
                                var a = new double[codes.Length];
                                for (int ci = 0; ci < codes.Length; ci++)
                                {
                                    try { foreach (CalculatedShape sh in aa.GetShapesByCode(codes[ci])) a[ci] += sh.Area; } catch { }
                                }
                                if (!double.IsNaN(prevS))
                                {
                                    double ds = Math.Abs(s - prevS);
                                    for (int ci = 0; ci < codes.Length; ci++) vol[ci] += (a[ci] + prevA[ci]) / 2.0 * ds;
                                    topW += ds * 0; // placeholder
                                }
                                prevA = a; prevS = s; n++;
                            }
                            sb.AppendLine(string.Join(";", Q(c.Name), Q(an), Q(rg.Name), Q(asm), F(rg.StartStation), F(rg.EndStation), n.ToString(),
                                string.Join(";", vol.Select(v => F(v))), "", ""));
                        }
                    }
                }
                tr.Commit();
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_pavevol.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            Ed.WriteMessage("\nPAVEVOL selesai: {0}", path);
        }

        [CommandMethod("VOLSIMP")]
        public void VolSimp() { try { VolSimpImpl(); } catch (System.Exception ex) { Ed.WriteMessage("\nVOLSIMP ERROR: " + ex); } }

        void VolSimpImpl()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database;
            var civ = CivilDocument.GetCivilDocument(db);
            var sb = new StringBuilder();
            sb.AppendLine("Nama;Cut;Fill;Net");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId sid in civ.GetSurfaceIds())
                {
                    var vs = tr.GetObject(sid, OpenMode.ForRead) as TinVolumeSurface;
                    if (vs == null) continue;
                    vs.UpgradeOpen();
                    try { vs.Rebuild(); } catch (System.Exception ex) { Ed.WriteMessage("\n  rebuild {0}: {1}", vs.Name, ex.Message); }
                    var vp = vs.GetVolumeProperties();
                    sb.AppendLine(string.Join(";", Q(vs.Name), F(vp.UnadjustedCutVolume), F(vp.UnadjustedFillVolume), F(vp.UnadjustedNetVolume)));
                }
                tr.Commit();
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_volsimp.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            Ed.WriteMessage("\nVOLSIMP selesai: {0}", path);
        }
    }
}
