// RMARK - marka jalan 3D di atas surface, berdasarkan alignment + offset.
using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivSurface = Autodesk.Civil.DatabaseServices.Surface;

namespace C3DTools
{
    public class MarkingParams
    {
        public double Offset = 0.0;        // + kanan, - kiri (arah stasiun)
        public bool Dashed = true;         // putus-putus atau utuh
        public double DashLength = 3.0;    // panjang garis (m)
        public double GapLength = 5.0;     // panjang celah (m)
        public double Width = 0.12;        // lebar marka (m)
        public double StaStart = double.NaN;
        public double StaEnd = double.NaN;
        public bool AsArea = true;         // true: outline tertutup selebar marka; false: garis sumbu
        public double Step = 1.0;          // jarak sampling sepanjang alignment (m)
        public double Lift = 0.005;        // angkat sedikit di atas surface (m)
        public bool Hatch = true;          // isi hatch SOLID (hanya untuk bentuk Area)
    }

    public class MarkingResult
    {
        public int Created;
        public int Skipped;      // segmen di luar surface
        public double Length;    // total panjang marka (m)
        public double Area;      // total luas cat (m2)
        public int Hatches;      // jumlah hatch yang berhasil dibuat
    }

    public static class MarkingCore
    {
        public static MarkingResult Draw(Database db, Transaction tr, Alignment al, CivSurface surf, MarkingParams p)
        {
            var res = new MarkingResult();
            double s0 = double.IsNaN(p.StaStart) ? al.StartingStation : Math.Max(p.StaStart, al.StartingStation);
            double s1 = double.IsNaN(p.StaEnd) ? al.EndingStation : Math.Min(p.StaEnd, al.EndingStation);
            if (s1 <= s0) return res;

            string layer = p.Dashed ? "MARKA-PUTUS" : "MARKA-UTUH";
            ObjectId layerId = EnsureLayer(db, tr, layer);
            var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);

            double s = s0;
            while (s < s1 - 1e-6)
            {
                double e = p.Dashed ? Math.Min(s + p.DashLength, s1) : s1;
                Point3dCollection pts = BuildSegment(al, surf, p, s, e);
                if (pts == null)
                {
                    res.Skipped++;
                }
                else
                {
                    var pl = new Polyline3d(Poly3dType.SimplePoly, pts, p.AsArea);
                    pl.LayerId = layerId;
                    ms.AppendEntity(pl);
                    tr.AddNewlyCreatedDBObject(pl, true);
                    if (p.AsArea && p.Hatch && AddHatch(tr, ms, layerId, pts)) res.Hatches++;
                    res.Created++;
                    res.Length += e - s;
                    res.Area += (e - s) * p.Width;
                }
                if (!p.Dashed) break;
                s = e + p.GapLength;
            }
            return res;
        }

        // Titik-titik satu segmen marka; null bila ada titik di luar surface.
        static Point3dCollection BuildSegment(Alignment al, CivSurface surf, MarkingParams p, double s, double e)
        {
            var stations = new List<double>();
            double step = Math.Max(p.Step, 0.05);
            for (double x = s; x < e - 1e-6; x += step) stations.Add(x);
            stations.Add(e);

            var pts = new Point3dCollection();
            try
            {
                if (p.AsArea)
                {
                    double h = p.Width / 2.0;
                    for (int i = 0; i < stations.Count; i++) pts.Add(PointAt(al, surf, stations[i], p.Offset + h, p.Lift));
                    for (int i = stations.Count - 1; i >= 0; i--) pts.Add(PointAt(al, surf, stations[i], p.Offset - h, p.Lift));
                }
                else
                {
                    foreach (double x in stations) pts.Add(PointAt(al, surf, x, p.Offset, p.Lift));
                }
            }
            catch (System.Exception)
            {
                return null; // di luar batas surface / stasiun tidak valid
            }
            return pts;
        }

        static Point3d PointAt(Alignment al, CivSurface surf, double station, double offset, double lift)
        {
            double east = 0, north = 0;
            al.PointLocation(station, offset, ref east, ref north);
            double z = surf.FindElevationAtXY(east, north);
            return new Point3d(east, north, z + lift);
        }

        // Hatch SOLID dari outline tertutup. Hatch harus datar, jadi diletakkan di elevasi rata-rata
        // outline; outline Polyline3d tetap mengikuti surface. false bila hatch gagal dibuat.
        internal static bool AddHatch(Transaction tr, BlockTableRecord ms, ObjectId layerId, Point3dCollection outline)
        {
            if (outline.Count < 3) return false;
            var loop = new Point2dCollection();
            var bulges = new DoubleCollection();
            double z = 0;
            Point2d last = new Point2d(double.NaN, double.NaN);
            foreach (Point3d q in outline)
            {
                z += q.Z;
                var q2 = new Point2d(q.X, q.Y);
                if (loop.Count > 0 && q2.GetDistanceTo(last) < 1e-6) continue;   // buang titik kembar
                loop.Add(q2); bulges.Add(0.0); last = q2;
            }
            z /= outline.Count;
            if (loop.Count < 3) return false;
            if (loop[0].GetDistanceTo(last) > 1e-6) { loop.Add(loop[0]); bulges.Add(0.0); }   // tutup loop

            var h = new Autodesk.AutoCAD.DatabaseServices.Hatch();
            ms.AppendEntity(h);
            tr.AddNewlyCreatedDBObject(h, true);
            try
            {
                h.SetDatabaseDefaults();
                h.LayerId = layerId;
                h.Normal = Vector3d.ZAxis;
                h.Elevation = z;
                h.SetHatchPattern(HatchPatternType.PreDefined, "SOLID");
                h.Associative = false;
                h.AppendLoop(HatchLoopTypes.Default, loop, bulges);
                h.EvaluateHatch(true);
                return true;
            }
            catch (System.Exception)
            {
                h.Erase();
                return false;
            }
        }

        internal static ObjectId EnsureLayer(Database db, Transaction tr, string name)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(name)) return lt[name];
            lt.UpgradeOpen();
            var ltr = new LayerTableRecord { Name = name, Color = Color.FromColorIndex(ColorMethod.ByAci, 7) };
            ObjectId id = lt.Add(ltr);
            tr.AddNewlyCreatedDBObject(ltr, true);
            return id;
        }
    }

    public class MarkingCommands
    {
        // nilai terakhir diingat selama sesi supaya pengulangan cepat
        static readonly MarkingParams Last = new MarkingParams();

        [CommandMethod("RMARK")]
        public void RoadMarking()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);

            var peo = new PromptEntityOptions("\nPilih alignment: ");
            peo.SetRejectMessage("\nHarus alignment.");
            peo.AddAllowedClass(typeof(Alignment), false);
            PromptEntityResult per = ed.GetEntity(peo);
            if (per.Status != PromptStatus.OK) return;

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var al = (Alignment)tr.GetObject(per.ObjectId, OpenMode.ForRead);

                // --- surface ---
                ObjectIdCollection surfIds = civ.GetSurfaceIds();
                if (surfIds.Count == 0) { ed.WriteMessage("\nTidak ada surface di drawing ini."); return; }
                int idx = 1;
                if (surfIds.Count > 1)
                {
                    ed.WriteMessage("\nSurface tersedia:");
                    for (int i = 0; i < surfIds.Count; i++)
                    {
                        var sf = (CivSurface)tr.GetObject(surfIds[i], OpenMode.ForRead);
                        ed.WriteMessage("\n  {0}. {1}", i + 1, sf.Name);
                    }
                    var pio = new PromptIntegerOptions("\nNomor surface tempat marka menempel: ") { LowerLimit = 1, UpperLimit = surfIds.Count };
                    PromptIntegerResult pir = ed.GetInteger(pio);
                    if (pir.Status != PromptStatus.OK) return;
                    idx = pir.Value;
                }
                var surf = (CivSurface)tr.GetObject(surfIds[idx - 1], OpenMode.ForRead);

                // --- parameter ---
                MarkingParams p = Last;
                if (!AskDouble(ed, "\nOffset dari alignment (+ kanan, - kiri)", ref p.Offset, true)) return;

                var pko = new PromptKeywordOptions("\nJenis marka [Utuh/Putus]", "Utuh Putus") { AllowNone = true };
                pko.Keywords.Default = p.Dashed ? "Putus" : "Utuh";
                PromptResult pkr = ed.GetKeywords(pko);
                if (pkr.Status != PromptStatus.OK && pkr.Status != PromptStatus.None) return;
                if (pkr.Status == PromptStatus.OK) p.Dashed = pkr.StringResult == "Putus";

                if (p.Dashed)
                {
                    if (!AskDouble(ed, "\nPanjang garis (m)", ref p.DashLength, false)) return;
                    if (!AskDouble(ed, "\nPanjang celah (m)", ref p.GapLength, false)) return;
                }
                if (!AskDouble(ed, "\nLebar marka (m)", ref p.Width, false)) return;

                double sa = al.StartingStation, sb = al.EndingStation;
                if (!AskStation(ed, al, "\nKlik titik STA awal", ref sa)) return;
                if (!AskStation(ed, al, "\nKlik titik STA akhir", ref sb)) return;
                if (sb < sa) { double t = sa; sa = sb; sb = t; }
                p.StaStart = sa; p.StaEnd = sb;

                var pko2 = new PromptKeywordOptions("\nBentuk hasil [Area/Garis]", "Area Garis") { AllowNone = true };
                pko2.Keywords.Default = p.AsArea ? "Area" : "Garis";
                PromptResult pkr2 = ed.GetKeywords(pko2);
                if (pkr2.Status != PromptStatus.OK && pkr2.Status != PromptStatus.None) return;
                if (pkr2.Status == PromptStatus.OK) p.AsArea = pkr2.StringResult == "Area";

                if (p.AsArea && !AskHatch(ed, ref p.Hatch)) return;

                MarkingResult r = MarkingCore.Draw(db, tr, al, surf, p);
                tr.Commit();

                ed.WriteMessage("\nMarka dibuat: {0} segmen, panjang {1:F2} m, luas cat {2:F2} m2.", r.Created, r.Length, r.Area);
                if (p.AsArea && p.Hatch)
                    ed.WriteMessage("\nHatch dibuat: {0} dari {1} segmen.", r.Hatches, r.Created);
                if (r.Skipped > 0)
                    ed.WriteMessage("\nPERHATIAN: {0} segmen dilewati karena berada di luar surface \"{1}\".", r.Skipped, surf.Name);
            }
        }

        // Stasiun dari klik titik di layar (diproyeksikan tegak lurus ke alignment).
        // Enter = pakai nilai default (awal/akhir alignment); kata kunci Ketik = isi angka.
        static bool AskStation(Editor ed, Alignment al, string msg, ref double station)
        {
            while (true)
            {
                var ppo = new PromptPointOptions(string.Format("{0} atau [Ketik] <{1:F3}>: ", msg, station), "Ketik") { AllowNone = true };
                PromptPointResult r = ed.GetPoint(ppo);
                if (r.Status == PromptStatus.None) return true;
                if (r.Status == PromptStatus.Keyword) return AskDouble(ed, "\nSTA", ref station, true);
                if (r.Status != PromptStatus.OK) return false;

                Point3d w = r.Value.TransformBy(ed.CurrentUserCoordinateSystem);
                try
                {
                    double sta = 0, off = 0;
                    al.StationOffset(w.X, w.Y, ref sta, ref off);
                    station = sta;
                    ed.WriteMessage("\n  STA {0:F3} (titik berjarak {1:F3} m dari alignment)", sta, off);
                    return true;
                }
                catch (System.Exception)
                {
                    ed.WriteMessage("\nTitik itu berada di luar rentang alignment, klik lagi.");
                }
            }
        }

        // Enter = pakai pilihan terakhir (awal: Ya).
        internal static bool AskHatch(Editor ed, ref bool hatch)
        {
            var o = new PromptKeywordOptions("\nIsi dengan hatch solid [Ya/Tidak]", "Ya Tidak") { AllowNone = true };
            o.Keywords.Default = hatch ? "Ya" : "Tidak";
            PromptResult r = ed.GetKeywords(o);
            if (r.Status != PromptStatus.OK && r.Status != PromptStatus.None) return false;
            if (r.Status == PromptStatus.OK) hatch = r.StringResult == "Ya";
            return true;
        }

        static bool AskDouble(Editor ed, string msg, ref double value, bool allowNegOrZero)
        {
            var o = new PromptDoubleOptions(msg + ": ")
            {
                DefaultValue = value,
                UseDefaultValue = true,
                AllowNegative = allowNegOrZero,
                AllowZero = allowNegOrZero
            };
            PromptDoubleResult r = ed.GetDouble(o);
            if (r.Status != PromptStatus.OK) return false;
            value = r.Value;
            return true;
        }
    }
}
