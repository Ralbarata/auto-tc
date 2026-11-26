// SUTTX - cari perpotongan kabel SUTT (layer *Sutet*/*SUTT*) dengan alignment Main Road, hitung clearance
// elevasi kabel terhadap as jalan (profil FG), lalu buat sample line group "SLG SUTT" + section view per titik.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using AcEntity = Autodesk.AutoCAD.DatabaseServices.Entity;
using CivSurface = Autodesk.Civil.DatabaseServices.Surface;

namespace C3DRambu
{
    public class SuttCommands
    {
        static string StaF(double s) { int km = (int)Math.Floor(s / 1000.0 + 1e-9); return km.ToString(CultureInfo.InvariantCulture) + "+" + (s - km * 1000.0).ToString("000.00", CultureInfo.InvariantCulture); }
        static string F(double v, string f = "0.000") { return v.ToString(f, CultureInfo.InvariantCulture); }

        class Hit { public double Sta, Z, X, Y, Fg, Top, Eg; public string Src; public int NVert; public double ZMin, ZMax; }

        static List<Point3d> Vertices(Transaction tr, AcEntity e)
        {
            var pts = new List<Point3d>();
            if (e is Polyline3d)
            {
                foreach (ObjectId vid in (Polyline3d)e) pts.Add(((PolylineVertex3d)tr.GetObject(vid, OpenMode.ForRead)).Position);
            }
            else if (e is Polyline2d)
            {
                var p2 = (Polyline2d)e;
                foreach (ObjectId vid in p2) { var v = (Vertex2d)tr.GetObject(vid, OpenMode.ForRead); pts.Add(p2.VertexPosition(v)); }
            }
            else if (e is Polyline)
            {
                var p = (Polyline)e; for (int i = 0; i < p.NumberOfVertices; i++) pts.Add(p.GetPoint3dAt(i));
            }
            else if (e is Line) { pts.Add(((Line)e).StartPoint); pts.Add(((Line)e).EndPoint); }
            return pts;
        }

        static ObjectId Layer(Database db, Transaction tr, string name, short color)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(name)) return lt[name];
            lt.UpgradeOpen();
            var r = new LayerTableRecord { Name = name, Color = Color.FromColorIndex(ColorMethod.ByAci, color) };
            var id = lt.Add(r); tr.AddNewlyCreatedDBObject(r, true); return id;
        }

        static void Add(BlockTableRecord ms, Transaction tr, AcEntity e, ObjectId layer)
        {
            e.LayerId = layer; ms.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true);
        }

        [CommandMethod("SUTTX")]
        public void Run()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database; var ed = doc.Editor;
            try { Impl(doc, db, ed); } catch (System.Exception ex) { ed.WriteMessage("\nSUTTX ERROR: " + ex); }
        }

        void Impl(Autodesk.AutoCAD.ApplicationServices.Document doc, Database db, Editor ed)
        {
            var civ = CivilDocument.GetCivilDocument(db);
            var hits = new List<Hit>();
            var log = new StringBuilder();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Corridor cor = null;
                foreach (ObjectId cid in civ.CorridorCollection) { var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor; if (c != null && c.Name == "15 Nov_Main Road") cor = c; }
                var bl = cor.Baselines[0];
                var al = (Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead);
                var pf = (Profile)tr.GetObject(bl.ProfileId, OpenMode.ForRead);
                TinSurface eg = null, top = null;
                foreach (ObjectId sid in civ.GetSurfaceIds())
                {
                    var s = tr.GetObject(sid, OpenMode.ForRead) as TinSurface; if (s == null) continue;
                    if (s.Name == "EG-Existing (1)") eg = s; if (s.Name == "15 Nov_Main Road Top") top = s;
                }

                // ---- cari kabel ----
                var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var e = tr.GetObject(id, OpenMode.ForRead) as AcEntity;
                    if (e == null) continue;
                    string lay = e.Layer.ToUpperInvariant();
                    if (!(lay.Contains("SUTET") || lay.Contains("SUTT") || lay.Contains("KABEL"))) continue;
                    var pts = Vertices(tr, e);
                    if (pts.Count < 2) continue;
                    double zmin = pts.Min(p => p.Z), zmax = pts.Max(p => p.Z);
                    log.AppendFormat("\n  {0} [{1}] {2} titik, z {3} .. {4}", e.GetType().Name, e.Layer, pts.Count, F(zmin, "0.00"), F(zmax, "0.00"));
                    // telusuri segmen: titik potong = perubahan tanda offset terhadap alignment
                    for (int i = 0; i < pts.Count - 1; i++)
                    {
                        Point3d a = pts[i], b = pts[i + 1];
                        int n = Math.Max(2, (int)(a.DistanceTo(b) / 0.5));
                        double prevOff = double.NaN, prevSta = 0; Point3d prev = a;
                        for (int k = 0; k <= n; k++)
                        {
                            double t = (double)k / n;
                            var p = a + (b - a) * t;
                            double st = 0, off = 0;
                            try { al.StationOffset(p.X, p.Y, ref st, ref off); } catch { prevOff = double.NaN; continue; }
                            if (!double.IsNaN(prevOff) && Math.Sign(off) != Math.Sign(prevOff) && Math.Abs(off - prevOff) < 5)
                            {
                                double f = prevOff / (prevOff - off);
                                var q = prev + (p - prev) * f;
                                double sq = 0, oq = 0; al.StationOffset(q.X, q.Y, ref sq, ref oq);
                                var h = new Hit { Sta = sq, Z = q.Z, X = q.X, Y = q.Y, Src = e.Layer, NVert = pts.Count, ZMin = zmin, ZMax = zmax };
                                try { h.Fg = pf.ElevationAt(sq); } catch { h.Fg = double.NaN; }
                                try { h.Top = top.FindElevationAtXY(q.X, q.Y); } catch { h.Top = double.NaN; }
                                try { h.Eg = eg.FindElevationAtXY(q.X, q.Y); } catch { h.Eg = double.NaN; }
                                hits.Add(h);
                            }
                            prevOff = off; prevSta = st; prev = p;
                        }
                    }
                }
                tr.Commit();
            }
            ed.WriteMessage("\nSUTTX: objek kabel:{0}", log.ToString());
            if (hits.Count == 0) { ed.WriteMessage("\nSUTTX: tidak ada perpotongan dengan as jalan."); return; }

            // ---- sample line group + section view ----
            var csv = new StringBuilder();
            csv.AppendLine("No;STA;X;Y;Elev kabel;FG as jalan;Top corridor;EG;Clearance kabel-FG;Clearance kabel-EG;Vertex kabel;Zmin;Zmax");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Corridor cor = null;
                foreach (ObjectId cid in civ.CorridorCollection) { var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor; if (c != null && c.Name == "15 Nov_Main Road") cor = c; }
                var al = (Alignment)tr.GetObject(cor.Baselines[0].AlignmentId, OpenMode.ForRead);
                // hapus SLG SUTT lama bila ada
                foreach (ObjectId gid in al.GetSampleLineGroupIds())
                {
                    var g = tr.GetObject(gid, OpenMode.ForRead) as SampleLineGroup;
                    if (g != null && g.Name == "SLG SUTT") { g.UpgradeOpen(); g.Erase(); }
                }
                ObjectId slgId = SampleLineGroup.Create("SLG SUTT", al.ObjectId);
                var slg = (SampleLineGroup)tr.GetObject(slgId, OpenMode.ForWrite);
                var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);
                ObjectId lay = Layer(db, tr, "SUTT_CLEARANCE", 1);
                int no = 0;
                var svIds = new List<ObjectId>();
                foreach (var h in hits.OrderBy(x => x.Sta))
                {
                    no++;
                    double xl = 0, yl = 0, xr = 0, yr = 0;
                    al.PointLocation(h.Sta, -60, ref xl, ref yl); al.PointLocation(h.Sta, 60, ref xr, ref yr);
                    var pc = new Point2dCollection { new Point2d(xl, yl), new Point2d(xr, yr) };
                    ObjectId slId = SampleLine.Create("SUTT-" + no + " STA " + F(h.Sta, "0.00"), slgId, pc);
                    csv.AppendLine(string.Join(";", no.ToString(), F(h.Sta, "0.00"), F(h.X), F(h.Y), F(h.Z), F(h.Fg), F(h.Top), F(h.Eg),
                        F(h.Z - h.Fg), F(h.Z - h.Eg), h.NVert.ToString(), F(h.ZMin), F(h.ZMax)));
                }
                // sumber section: EG, Top, Datum, corridor
                try
                {
                    foreach (SectionSource ss in slg.GetSectionSources())
                    {
                        string nm = "";
                        try { var o = tr.GetObject(ss.SourceId, OpenMode.ForRead); nm = (o is CivSurface) ? ((CivSurface)o).Name : (o is Corridor ? ((Corridor)o).Name : ""); } catch { }
                        if (nm == "EG-Existing (1)" || nm == "15 Nov_Main Road Top" || nm == "15 Nov_Main Road Datum" || nm == "15 Nov_Main Road")
                            ss.IsSampled = true;
                    }
                }
                catch (System.Exception ex) { ed.WriteMessage("\n  section source: " + ex.Message); }
                tr.Commit();
            }

            // section view (transaksi terpisah setelah section terbentuk)
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Corridor cor = null;
                foreach (ObjectId cid in civ.CorridorCollection) { var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor; if (c != null && c.Name == "15 Nov_Main Road") cor = c; }
                var al = (Alignment)tr.GetObject(cor.Baselines[0].AlignmentId, OpenMode.ForRead);
                SampleLineGroup slg = null;
                foreach (ObjectId gid in al.GetSampleLineGroupIds()) { var g = tr.GetObject(gid, OpenMode.ForRead) as SampleLineGroup; if (g != null && g.Name == "SLG SUTT") slg = g; }
                var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);
                ObjectId lay = Layer(db, tr, "SUTT_CLEARANCE", 1);
                var sorted = hits.OrderBy(x => x.Sta).ToList();
                int i = 0;
                foreach (ObjectId slId in slg.GetSampleLineIds())
                {
                    var h = sorted[Math.Min(i, sorted.Count - 1)];
                    // letakkan section view 250 m di kanan titik potong (arah tegak lurus alignment)
                    double xs = 0, ys = 0; al.PointLocation(h.Sta, 250, ref xs, ref ys);
                    ObjectId svId = ObjectId.Null;
                    try { svId = SectionView.Create("SV SUTT-" + (i + 1), slId, new Point3d(xs, ys, 0)); }
                    catch (System.Exception ex) { ed.WriteMessage("\n  section view gagal: " + ex.Message); i++; continue; }
                    var sv = (SectionView)tr.GetObject(svId, OpenMode.ForWrite);
                    try
                    {
                        sv.IsElevationRangeAutomatic = false;
                        double lo = Math.Min(h.Eg, h.Fg); if (double.IsNaN(lo)) lo = h.Fg;
                        sv.ElevationMin = Math.Floor(lo - 3);
                        sv.ElevationMax = Math.Ceiling(h.Z + 3);
                    }
                    catch (System.Exception ex) { ed.WriteMessage("\n  rentang elevasi: " + ex.Message); }
                    // titik kabel + garis clearance + label di section view (offset 0 = as jalan)
                    try
                    {
                        double xc = 0, yc = 0, xf = 0, yf = 0;
                        sv.FindXYAtOffsetAndElevation(0, h.Z, ref xc, ref yc);
                        sv.FindXYAtOffsetAndElevation(0, h.Fg, ref xf, ref yf);
                        Add(ms, tr, new Circle(new Point3d(xc, yc, 0), Vector3d.ZAxis, 0.6), lay);
                        Add(ms, tr, new Line(new Point3d(xf, yf, 0), new Point3d(xc, yc, 0)), lay);
                        Add(ms, tr, new MText
                        {
                            Location = new Point3d(xc + 2, yc + 1.5, 0), TextHeight = 1.5, Attachment = AttachmentPoint.BottomLeft,
                            Contents = "KABEL SUTT  El. " + F(h.Z, "0.00") + "\\P" + "AS JALAN (FG) El. " + F(h.Fg, "0.00") + "\\P" +
                                       "CLEARANCE = " + F(h.Z - h.Fg, "0.00") + " m  (STA " + StaF(h.Sta).Replace('.', ',') + ")"
                        }, lay);
                    }
                    catch (System.Exception ex) { ed.WriteMessage("\n  marker: " + ex.Message); }
                    // penanda di plan
                    Add(ms, tr, new Circle(new Point3d(h.X, h.Y, 0), Vector3d.ZAxis, 2.0), lay);
                    ed.WriteMessage("\n  SUTT-{0}: STA {1}, kabel El {2}, FG {3}, clearance {4} m, section view di ({5}, {6})",
                        i + 1, StaF(h.Sta), F(h.Z, "0.00"), F(h.Fg, "0.00"), F(h.Z - h.Fg, "0.00"), F(xs, "0"), F(ys, "0"));
                    i++;
                }
                tr.Commit();
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_sutt.csv");
            File.WriteAllText(path, csv.ToString(), new UTF8Encoding(true));
            ed.WriteMessage("\nSUTTX selesai: {0} titik potong. {1}", hits.Count, path);
        }
    }
}

