// RCHEVRON - marka chevron / serong di dalam batas pulau lalu lintas (polyline tertutup).
using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivSurface = Autodesk.Civil.DatabaseServices.Surface;

namespace C3DTools
{
    public class ChevronParams
    {
        public Point2d AxisFrom;           // ujung V menghadap titik ini
        public Point2d AxisTo;
        public bool VShape = true;         // true: chevron (V); false: garis serong satu arah
        public double AngleDeg = 45.0;     // sudut garis terhadap sumbu
        public double Width = 0.30;        // lebar garis (m), tegak lurus garis
        public double Gap = 1.00;          // jarak bersih antar garis (m)
        public double Step = 1.0;          // sampling tepi untuk menempel ke surface (m)
        public double Lift = 0.005;
        public bool Hatch = true;          // isi hatch SOLID tiap garis
    }

    public static class ChevronCore
    {
        // boundary: poligon batas (WCS, 2D). surf boleh null -> marka datar di elevasi flatZ.
        public static MarkingResult Draw(Database db, Transaction tr, List<Point2d> boundary,
            CivSurface surf, double flatZ, ChevronParams p)
        {
            var res = new MarkingResult();
            Vector2d a = p.AxisTo - p.AxisFrom;
            if (a.Length < 1e-9 || boundary.Count < 3 || p.Width <= 0) return res;
            a = a.GetNormal();
            var u = new Vector2d(-a.Y, a.X);                       // tegak lurus kiri sumbu
            double t = p.AngleDeg * Math.PI / 180.0;
            Vector2d nL = a * (-Math.Sin(t)) + u * Math.Cos(t);    // normal garis sisi kiri
            Vector2d nR = a * (-Math.Sin(t)) - u * Math.Cos(t);    // cermin terhadap sumbu
            Point2d o = p.AxisFrom;

            ObjectId layerId = MarkingCore.EnsureLayer(db, tr, "MARKA-CHEVRON");
            var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);

            if (p.VShape)
            {
                double c = Dot(u, o);
                Stripes(tr, ms, layerId, Clip(boundary, u, c, true), nL, o, surf, flatZ, p, res);
                Stripes(tr, ms, layerId, Clip(boundary, u, c, false), nR, o, surf, flatZ, p, res);
            }
            else
            {
                Stripes(tr, ms, layerId, boundary, nL, o, surf, flatZ, p, res);
            }
            return res;
        }

        static void Stripes(Transaction tr, BlockTableRecord ms, ObjectId layerId, List<Point2d> poly,
            Vector2d n, Point2d o, CivSurface surf, double flatZ, ChevronParams p, MarkingResult res)
        {
            if (poly.Count < 3) return;
            double off = Dot(n, o), min = double.MaxValue, max = double.MinValue;
            foreach (Point2d q in poly)
            {
                double d = Dot(n, q) - off;
                if (d < min) min = d;
                if (d > max) max = d;
            }
            double pitch = p.Width + Math.Max(p.Gap, 0);
            for (double d = Math.Floor(min / pitch) * pitch; d < max; d += pitch)
            {
                List<Point2d> band = Clip(Clip(poly, n, off + d, true), n, off + d + p.Width, false);
                double area = Math.Abs(Area(band));
                if (band.Count < 3 || area < 1e-4) continue;

                Point3dCollection pts = Drape(band, surf, flatZ, p);
                if (pts == null) { res.Skipped++; continue; }
                var pl = new Polyline3d(Poly3dType.SimplePoly, pts, true);
                pl.LayerId = layerId;
                ms.AppendEntity(pl);
                tr.AddNewlyCreatedDBObject(pl, true);
                if (p.Hatch && MarkingCore.AddHatch(tr, ms, layerId, pts)) res.Hatches++;
                res.Created++;
                res.Area += area;
            }
        }

        // Tambah titik di sepanjang tepi lalu beri elevasi; null bila ada titik di luar surface.
        static Point3dCollection Drape(List<Point2d> poly, CivSurface surf, double flatZ, ChevronParams p)
        {
            var pts = new Point3dCollection();
            double step = Math.Max(p.Step, 0.05);
            try
            {
                for (int i = 0; i < poly.Count; i++)
                {
                    Point2d s = poly[i], e = poly[(i + 1) % poly.Count];
                    int nseg = Math.Max(1, (int)Math.Ceiling(s.GetDistanceTo(e) / step));
                    for (int k = 0; k < nseg; k++)
                    {
                        double f = (double)k / nseg;
                        double x = s.X + (e.X - s.X) * f, y = s.Y + (e.Y - s.Y) * f;
                        double z = surf == null ? flatZ : surf.FindElevationAtXY(x, y) + p.Lift;
                        pts.Add(new Point3d(x, y, z));
                    }
                }
            }
            catch (System.Exception) { return null; }
            return pts;
        }

        // Sutherland-Hodgman terhadap satu setengah-bidang: simpan n.p >= c (atau <= c).
        static List<Point2d> Clip(List<Point2d> poly, Vector2d n, double c, bool keepGreater)
        {
            var result = new List<Point2d>();
            if (poly.Count == 0) return result;
            double sign = keepGreater ? 1.0 : -1.0;
            Point2d prev = poly[poly.Count - 1];
            double dPrev = sign * (Dot(n, prev) - c);
            foreach (Point2d cur in poly)
            {
                double dCur = sign * (Dot(n, cur) - c);
                if ((dPrev >= 0) != (dCur >= 0))
                {
                    double f = dPrev / (dPrev - dCur);
                    result.Add(new Point2d(prev.X + (cur.X - prev.X) * f, prev.Y + (cur.Y - prev.Y) * f));
                }
                if (dCur >= 0) result.Add(cur);
                prev = cur; dPrev = dCur;
            }
            return result;
        }

        static double Dot(Vector2d n, Point2d q) { return n.X * q.X + n.Y * q.Y; }

        static double Area(List<Point2d> poly)
        {
            double s = 0;
            for (int i = 0; i < poly.Count; i++)
            {
                Point2d a = poly[i], b = poly[(i + 1) % poly.Count];
                s += a.X * b.Y - b.X * a.Y;
            }
            return s / 2.0;
        }

        // Ubah kurva tertutup menjadi poligon (busur dipecah menjadi segmen pendek).
        public static List<Point2d> ToPolygon(Curve cv, double arcStep)
        {
            var pts = new List<Point2d>();
            double len = cv.GetDistanceAtParameter(cv.EndParam);
            var pl = cv as Polyline;
            if (pl != null)
            {
                int n = pl.NumberOfVertices;
                int segs = pl.Closed ? n : n - 1;
                for (int i = 0; i < segs; i++)
                {
                    double d0 = pl.GetDistanceAtParameter(i);
                    double d1 = i + 1 >= n ? len : pl.GetDistanceAtParameter(i + 1);
                    int k = Math.Abs(pl.GetBulgeAt(i)) < 1e-9 ? 1 : Math.Max(4, (int)Math.Ceiling((d1 - d0) / arcStep));
                    for (int j = 0; j < k; j++) pts.Add(To2d(pl.GetPointAtDist(d0 + (d1 - d0) * j / k)));
                }
                if (!pl.Closed) pts.Add(To2d(pl.EndPoint));
            }
            else
            {
                int k = Math.Max(8, (int)Math.Ceiling(len / arcStep));
                for (int j = 0; j < k; j++) pts.Add(To2d(cv.GetPointAtDist(len * j / k)));
            }
            return pts;
        }

        static Point2d To2d(Point3d q) { return new Point2d(q.X, q.Y); }
    }

    public class ChevronCommands
    {
        static readonly ChevronParams Last = new ChevronParams();

        [CommandMethod("RCHEVRON")]
        public void Chevron()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);

            var peo = new PromptEntityOptions("\nPilih batas pulau (polyline tertutup): ");
            peo.SetRejectMessage("\nHarus polyline / kurva tertutup.");
            peo.AddAllowedClass(typeof(Curve), false);
            PromptEntityResult per = ed.GetEntity(peo);
            if (per.Status != PromptStatus.OK) return;

            Matrix3d ucs = ed.CurrentUserCoordinateSystem;
            var ppo = new PromptPointOptions("\nTitik sumbu 1 (ujung/hidung V menghadap ke sini): ");
            PromptPointResult p1 = ed.GetPoint(ppo);
            if (p1.Status != PromptStatus.OK) return;
            var ppo2 = new PromptPointOptions("\nTitik sumbu 2 (arah bukaan V): ") { UseBasePoint = true, BasePoint = p1.Value };
            PromptPointResult p2 = ed.GetPoint(ppo2);
            if (p2.Status != PromptStatus.OK) return;
            Point3d w1 = p1.Value.TransformBy(ucs), w2 = p2.Value.TransformBy(ucs);

            ChevronParams p = Last;
            p.AxisFrom = new Point2d(w1.X, w1.Y);
            p.AxisTo = new Point2d(w2.X, w2.Y);

            var pko = new PromptKeywordOptions("\nBentuk [Chevron/Serong]", "Chevron Serong") { AllowNone = true };
            pko.Keywords.Default = p.VShape ? "Chevron" : "Serong";
            PromptResult pkr = ed.GetKeywords(pko);
            if (pkr.Status != PromptStatus.OK && pkr.Status != PromptStatus.None) return;
            if (pkr.Status == PromptStatus.OK) p.VShape = pkr.StringResult == "Chevron";

            if (!Ask(ed, "\nSudut garis terhadap sumbu (derajat)", ref p.AngleDeg)) return;
            if (!Ask(ed, "\nLebar garis (m)", ref p.Width)) return;
            if (!Ask(ed, "\nJarak bersih antar garis (m)", ref p.Gap)) return;
            if (!MarkingCommands.AskHatch(ed, ref p.Hatch)) return;

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var cv = (Curve)tr.GetObject(per.ObjectId, OpenMode.ForRead);
                if (!cv.Closed) ed.WriteMessage("\nCatatan: batas tidak tertutup, dianggap ditutup dari titik akhir ke titik awal.");
                List<Point2d> boundary = ChevronCore.ToPolygon(cv, 0.25);

                // surface: 0 = datar di elevasi batas
                CivSurface surf = null;
                ObjectIdCollection surfIds = civ.GetSurfaceIds();
                if (surfIds.Count > 0)
                {
                    ed.WriteMessage("\nSurface tersedia:\n  0. (tanpa surface - datar di elevasi batas)");
                    for (int i = 0; i < surfIds.Count; i++)
                        ed.WriteMessage("\n  {0}. {1}", i + 1, ((CivSurface)tr.GetObject(surfIds[i], OpenMode.ForRead)).Name);
                    var pio = new PromptIntegerOptions("\nNomor surface tempat marka menempel: ") { LowerLimit = 0, UpperLimit = surfIds.Count };
                    PromptIntegerResult pir = ed.GetInteger(pio);
                    if (pir.Status != PromptStatus.OK) return;
                    if (pir.Value > 0) surf = (CivSurface)tr.GetObject(surfIds[pir.Value - 1], OpenMode.ForRead);
                }

                MarkingResult r = ChevronCore.Draw(db, tr, boundary, surf, cv.StartPoint.Z, p);
                tr.Commit();
                ed.WriteMessage("\nChevron dibuat: {0} garis, luas cat {1:F2} m2.", r.Created, r.Area);
                if (p.Hatch) ed.WriteMessage("\nHatch dibuat: {0} dari {1} garis.", r.Hatches, r.Created);
                if (r.Skipped > 0) ed.WriteMessage("\nPERHATIAN: {0} garis dilewati karena di luar surface.", r.Skipped);
            }
        }

        static bool Ask(Editor ed, string msg, ref double value)
        {
            var o = new PromptDoubleOptions(msg + ": ") { DefaultValue = value, UseDefaultValue = true, AllowNegative = false, AllowZero = false };
            PromptDoubleResult r = ed.GetDouble(o);
            if (r.Status != PromptStatus.OK) return false;
            value = r.Value;
            return true;
        }
    }
}
