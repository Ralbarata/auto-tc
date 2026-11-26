// RAMBU - menempatkan keterangan posisi rambu lalu lintas di sepanjang corridor Main Road.
// Rambu dibaca dari geometri: tikungan (alignment), tanjakan (profil), jembatan (region corridor
// dengan assembly "Jembatan"), dan simpang (objek Intersection Civil 3D).
// Lalu lintas lajur kiri: rambu arah STA naik di sisi kiri (offset negatif), arah STA turun di sisi kanan alignment.
// Semua objek diberi XData "C3DRAMBU" sehingga RAMBU bisa dijalankan ulang (hasil lama dihapus dulu).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivIntersection = Autodesk.Civil.DatabaseServices.Intersection;
using Entity = Autodesk.AutoCAD.DatabaseServices.Entity;

namespace C3DRambu
{
    public class RambuParams
    {
        public string CorridorName = "15 Nov_Main Road";
        public double Speed = 60;          // kecepatan rencana (km/jam) -> batas kecepatan & jarak rambu peringatan
        public double CurveRmax = 1000;    // tikungan dengan R <= nilai ini diberi rambu tikungan
        public double GradeMin = 3.0;      // tanjakan >= % ini diberi rambu tanjakan
        public double GradeMinLen = 50;    // panjang minimum tanjakan (m)
        public double SignOffset = 14.5;   // jarak rambu dari as alignment (m)
        public double JunctionHalf = 50;   // setengah panjang zona simpang dari titik potong (m)
        public double GuideDist = 200;     // jarak rambu petunjuk arah sebelum zona simpang (m)
        public double TextHeight = 2.6;    // tinggi kode di dalam lingkaran (seperti gambar PGJ)
        public double CircleRadius = 3.6;  // jari-jari lingkaran keterangan (seperti gambar PGJ)
        public double CallOut = 12.0;      // jarak lingkaran dari titik rambu, ke arah luar jalan (m)
        public string Layer = "RAMBU.";
        public double MinorOffset = 7.5;   // jarak rambu dari as jalan simpang (lengan jalan lain) (m)
        public double MinorHalf = 30;      // jarak mulut simpang dari titik potong, diukur di lengan jalan lain (m)

        // Jarak minimum rambu peringatan sebelum bahaya (PM 13/2014): <=60 km/jam 50 m, <=80 km/jam 80 m, >80 km/jam 100 m
        public double WarnDist { get { return Speed <= 60 ? 50 : (Speed <= 80 ? 80 : 100); } }
    }

    public class Sign
    {
        public string Code;       // kode keterangan di dalam lingkaran (P1, P2, ...)
        public string Category;   // Larangan / Peringatan / Perintah / Petunjuk
        public string Type;       // keterangan jenis rambu
        public double Station;
        public int Dir;           // +1 arah STA naik, -1 arah STA turun
        public string Reason;     // keterangan lokasi bahaya/tujuan
        public double X, Y;
        public double OffsetUsed;
        public Alignment Al;      // alignment acuan STA (Main Road atau jalan simpang)
        public double SignOff;    // jarak titik rambu dari as alignment
        public string Road;       // nama ruas
    }

    public static class RambuCore
    {
        public const string App = "C3DRAMBU";

        // urutan legenda: kode -> (kategori, jenis rambu)
        public static readonly string[][] Legend =
        {
            new[] { "P1", "Larangan",   "Batas Kecepatan" },
            new[] { "P2", "Peringatan", "Tikungan Kiri" },
            new[] { "P3", "Peringatan", "Tikungan Kanan" },
            new[] { "P4", "Peringatan", "Tanjakan" },
            new[] { "P5", "Peringatan", "Jembatan" },
            new[] { "P6", "Peringatan", "APILL" },
            new[] { "P7", "Perintah",   "Belok Kiri Langsung" },
            new[] { "P8", "Petunjuk",   "Petunjuk Arah" },
        };

        public static string CodeOf(string type)
        {
            foreach (var l in Legend) if (type.StartsWith(l[2], StringComparison.OrdinalIgnoreCase)) return l[0];
            return "P?";
        }

        public static string Sta(double s)
        {
            if (s < 0) return "-" + Sta(-s);
            int km = (int)Math.Floor(s / 1000.0 + 1e-9);
            double m = s - km * 1000.0;
            return km.ToString(CultureInfo.InvariantCulture) + "+" + m.ToString("000.00", CultureInfo.InvariantCulture);
        }

        static double Heading(Alignment al, double s, double s0, double s1)
        {
            double a = Math.Max(s0, s - 1.0), b = Math.Min(s1, s + 1.0);
            double x1 = 0, y1 = 0, x2 = 0, y2 = 0;
            al.PointLocation(a, 0, ref x1, ref y1);
            al.PointLocation(b, 0, ref x2, ref y2);
            return Math.Atan2(y2 - y1, x2 - x1);
        }

        public static double AngDiffPub(double a, double b) { return AngDiff(a, b); }

        static double AngDiff(double a, double b)
        {
            double d = b - a;
            while (d > Math.PI) d -= 2 * Math.PI;
            while (d < -Math.PI) d += 2 * Math.PI;
            return d;
        }

        public class Span { public double S0, S1, Value; public string Name; public List<string> Roads = new List<string>(); public List<Arm> Arms = new List<Arm>(); }

        // lengan simpang pada jalan lain: Dir +1 = lalu lintas menuju simpang searah STA naik alignment jalan itu
        public class Arm { public Alignment Al; public double Sj; public int Dir; public double Len; public string Road; }

        public static double HeadingAt(Alignment al, double s)
        {
            return Heading(al, s, al.StartingStation, al.EndingStation);
        }

        // tikungan dari sampling arah alignment: Value = radius minimum, tanda = arah belok (+ kiri / - kanan untuk arah STA naik)
        public static List<Span> Curves(Alignment al, double s0, double s1, double rmax)
        {
            var res = new List<Span>();
            double step = 2.0;
            Span cur = null; int curSign = 0;
            for (double s = s0 + step; s < s1 - step; s += step)
            {
                double k = AngDiff(Heading(al, s - step, s0, s1), Heading(al, s + step, s0, s1)) / (2 * step);
                // toleransi 3%: busur dengan R = rmax persis tetap terhitung (sampling arah memberi kelengkungan sedikit lebih kecil)
                int sign = Math.Abs(k) >= 1.0 / (rmax * 1.03) ? Math.Sign(k) : 0;
                if (sign != 0 && cur != null && sign == curSign)
                {
                    cur.S1 = s;
                    cur.Value = Math.Min(cur.Value, 1.0 / Math.Abs(k));
                }
                else
                {
                    if (cur != null && cur.S1 - cur.S0 >= 10) res.Add(cur);
                    cur = null;
                    if (sign != 0) { cur = new Span { S0 = s, S1 = s, Value = 1.0 / Math.Abs(k) }; curSign = sign; cur.Name = sign > 0 ? "kiri" : "kanan"; }
                }
            }
            if (cur != null && cur.S1 - cur.S0 >= 10) res.Add(cur);
            return res;
        }

        // segmen kelandaian >= gmin (%), Value = kelandaian maks (%) bertanda
        public static List<Span> Grades(Profile pf, double s0, double s1, double gmin, double minLen, out double maxAbs)
        {
            var res = new List<Span>();
            maxAbs = 0;
            if (pf == null) return res;
            double a = Math.Max(s0, pf.StartingStation), b = Math.Min(s1, pf.EndingStation);
            double step = 5.0;
            Span cur = null; int curSign = 0;
            for (double s = a; s <= b; s += step)
            {
                double g;
                try { g = pf.GradeAt(s) * 100.0; } catch { continue; }
                maxAbs = Math.Max(maxAbs, Math.Abs(g));
                int sign = Math.Abs(g) >= gmin ? Math.Sign(g) : 0;
                if (sign != 0 && cur != null && sign == curSign)
                {
                    cur.S1 = s;
                    if (Math.Abs(g) > Math.Abs(cur.Value)) cur.Value = g;
                }
                else
                {
                    if (cur != null && cur.S1 - cur.S0 >= minLen) res.Add(cur);
                    cur = null;
                    if (sign != 0) { cur = new Span { S0 = s, S1 = s, Value = g }; curSign = sign; }
                }
            }
            if (cur != null && cur.S1 - cur.S0 >= minLen) res.Add(cur);
            return res;
        }

        public static string RoadName(string alName)
        {
            string n = alName ?? "";
            int i = n.IndexOf('_');
            if (i >= 0 && i < 3) n = n.Substring(i + 1);
            n = n.Replace("JL ", "Jl. ").Replace("JL. ", "Jl. ");
            return n.Trim();
        }
    }

    public class RambuCommands
    {
        static readonly RambuParams Last = new RambuParams();

        // nama command sengaja beda dari versi pertama (RAMBU) supaya bisa di-NETLOAD di sesi yang sama
        [CommandMethod("RAMBUV6")]
        public void Run()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);
            RambuParams p = Last;

            var pso = new PromptStringOptions("\nNama corridor Main Road") { AllowSpaces = true, DefaultValue = p.CorridorName, UseDefaultValue = true };
            PromptResult psr = ed.GetString(pso);
            if (psr.Status != PromptStatus.OK) return;
            p.CorridorName = psr.StringResult;
            if (!Ask(ed, "\nKecepatan rencana (km/jam)", ref p.Speed)) return;
            if (!Ask(ed, "\nRadius maks tikungan yang diberi rambu (m)", ref p.CurveRmax)) return;
            if (!Ask(ed, "\nKelandaian min untuk rambu tanjakan (%)", ref p.GradeMin)) return;
            if (!Ask(ed, "\nJarak rambu dari as jalan (m)", ref p.SignOffset)) return;
            if (!Ask(ed, "\nJarak rambu dari as jalan simpang/lengan lain (m)", ref p.MinorOffset)) return;

            var signs = new List<Sign>();
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                Corridor cor = null;
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c != null && string.Equals(c.Name, p.CorridorName, StringComparison.OrdinalIgnoreCase)) { cor = c; break; }
                }
                if (cor == null) { ed.WriteMessage("\nCorridor \"{0}\" tidak ditemukan.", p.CorridorName); return; }
                Baseline bl = cor.Baselines[0];
                var al = (Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead);
                Profile pf = null;
                try { pf = tr.GetObject(bl.ProfileId, OpenMode.ForRead) as Profile; } catch { }

                // rentang corridor + jembatan + celah (zona simpang)
                var regs = new List<BaselineRegion>();
                foreach (BaselineRegion r in bl.BaselineRegions) regs.Add(r);
                regs.Sort((a, b) => a.StartStation.CompareTo(b.StartStation));
                double s0 = regs.Min(r => r.StartStation), s1 = regs.Max(r => r.EndStation);

                var bridges = new List<RambuCore.Span>();
                foreach (var r in regs)
                {
                    string asm = "";
                    try { asm = ((Assembly)tr.GetObject(r.AssemblyId, OpenMode.ForRead)).Name; } catch { }
                    if (asm.IndexOf("jembatan", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    var last = bridges.LastOrDefault();
                    if (last != null && r.StartStation - last.S1 < 1.0) last.S1 = r.EndStation;
                    else bridges.Add(new RambuCore.Span { S0 = r.StartStation, S1 = r.EndStation });
                }

                // cakupan corridor per alignment (semua corridor di gambar): lengan simpang hanya diberi rambu
                // sampai batas corridor, karena paket pekerjaan hanya sampai corridor
                var cover = new Dictionary<ObjectId, List<double[]>>();
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    Corridor c2 = null;
                    try { c2 = tr.GetObject(cid, OpenMode.ForRead) as Corridor; } catch { }
                    if (c2 == null) continue;
                    foreach (Baseline b2 in c2.Baselines)
                    {
                        ObjectId aid;
                        try { aid = b2.AlignmentId; } catch { continue; }
                        if (!cover.ContainsKey(aid)) cover[aid] = new List<double[]>();
                        foreach (BaselineRegion r2 in b2.BaselineRegions) cover[aid].Add(new[] { r2.StartStation, r2.EndStation });
                    }
                }

                // simpang: objek Intersection yang titiknya dekat alignment Main Road
                var junctions = new List<RambuCore.Span>();
                var armsSkipped = new List<string>();
                foreach (ObjectId iid in civ.GetIntersectionIds())
                {
                    var ix = tr.GetObject(iid, OpenMode.ForRead) as CivIntersection;
                    if (ix == null) continue;
                    double st = 0, off = 0;
                    try { al.StationOffset(ix.Location.X, ix.Location.Y, ref st, ref off); } catch { continue; }
                    if (Math.Abs(off) > 30 || st < s0 - 100 || st > s1 + 100) continue;
                    var j = new RambuCore.Span { S0 = st - p.JunctionHalf, S1 = st + p.JunctionHalf, Value = st, Name = ix.Name };
                    try
                    {
                        double hMain = RambuCore.HeadingAt(al, Math.Max(al.StartingStation, Math.Min(al.EndingStation, st)));
                        var seen = new HashSet<ObjectId>();
                        foreach (IntersectionRoad rd in ix.IntersectionRoads)
                        {
                            var ra = tr.GetObject(rd.CenterlineAlignmentId, OpenMode.ForRead) as Alignment;
                            if (ra == null || ra.ObjectId == al.ObjectId || !seen.Add(ra.ObjectId)) continue;
                            double sj = 0, oj = 0;
                            try { ra.StationOffset(ix.Location.X, ix.Location.Y, ref sj, ref oj); } catch { continue; }
                            if (Math.Abs(oj) > 30) continue;
                            // alignment yang sejajar Main Road (mis. as Main Road versi lain) bukan lengan jalan lain
                            double ang = Math.Abs(Math.Sin(RambuCore.AngDiffPub(hMain, RambuCore.HeadingAt(ra, sj))));
                            if (ang < Math.Sin(25 * Math.PI / 180)) continue;
                            string rn = RambuCore.RoadName(ra.Name);
                            j.Roads.Add(rn);
                            double lenBefore = 0, lenAfter = 0;
                            List<double[]> cv;
                            if (cover.TryGetValue(ra.ObjectId, out cv))
                                foreach (var seg in cv)
                                {
                                    lenBefore = Math.Max(lenBefore, sj - seg[0]);   // batas corridor terjauh sebelum titik simpang
                                    lenAfter = Math.Max(lenAfter, seg[1] - sj);     // batas corridor terjauh sesudah titik simpang
                                }
                            lenBefore = Math.Min(lenBefore, sj - ra.StartingStation);
                            lenAfter = Math.Min(lenAfter, ra.EndingStation - sj);
                            if (lenBefore <= p.MinorHalf + 5) armsSkipped.Add(ix.Name + " / " + rn + " [sebelum, corridor " + lenBefore.ToString("0") + " m]");
                            if (lenAfter <= p.MinorHalf + 5) armsSkipped.Add(ix.Name + " / " + rn + " [sesudah, corridor " + lenAfter.ToString("0") + " m]");
                            if (lenBefore > p.MinorHalf + 5) j.Arms.Add(new RambuCore.Arm { Al = ra, Sj = sj, Dir = +1, Len = lenBefore, Road = rn });
                            if (lenAfter > p.MinorHalf + 5) j.Arms.Add(new RambuCore.Arm { Al = ra, Sj = sj, Dir = -1, Len = lenAfter, Road = rn });
                        }
                    }
                    catch { }
                    junctions.Add(j);
                }
                junctions.Sort((a, b) => a.Value.CompareTo(b.Value));

                var curves = RambuCore.Curves(al, s0, s1, p.CurveRmax);
                double gmax;
                var grades = RambuCore.Grades(pf, s0, s1, p.GradeMin, p.GradeMinLen, out gmax);
                double D = p.WarnDist;

                Action<string, string, double, int, string> add = (cat, type, sta, dir, why) =>
                {
                    if (sta < s0 || sta > s1) return;
                    signs.Add(new Sign { Code = RambuCore.CodeOf(type), Category = cat, Type = type, Station = sta, Dir = dir, Reason = why,
                                         Al = al, SignOff = p.SignOffset, Road = "JLS Main Road" });
                };
                string spd = "Batas Kecepatan " + p.Speed.ToString("0", CultureInfo.InvariantCulture) + " km/jam";

                // --- Larangan: batas kecepatan di awal ruas dan setelah tiap simpang ---
                add("Larangan", spd, s0 + 20, +1, "awal ruas Main Road");
                add("Larangan", spd, s1 - 20, -1, "awal ruas Main Road (arah turun)");
                foreach (var j in junctions)
                {
                    add("Larangan", spd, j.S1 + 50, +1, "setelah " + j.Name);
                    add("Larangan", spd, j.S0 - 50, -1, "setelah " + j.Name);
                }

                // --- Peringatan ---
                foreach (var c in curves)
                {
                    string r = "R min " + c.Value.ToString("0", CultureInfo.InvariantCulture) + " m, STA " + RambuCore.Sta(c.S0) + " - " + RambuCore.Sta(c.S1);
                    string up = c.Name == "kiri" ? "Tikungan Kiri" : "Tikungan Kanan";
                    string dn = c.Name == "kiri" ? "Tikungan Kanan" : "Tikungan Kiri";
                    add("Peringatan", up, c.S0 - D, +1, r);
                    add("Peringatan", dn, c.S1 + D, -1, r);
                }
                foreach (var g in grades)
                {
                    string r = "kelandaian " + g.Value.ToString("0.0", CultureInfo.InvariantCulture) + "%, STA " + RambuCore.Sta(g.S0) + " - " + RambuCore.Sta(g.S1);
                    if (g.Value > 0) add("Peringatan", "Tanjakan", g.S0 - D, +1, r);
                    else add("Peringatan", "Tanjakan", g.S1 + D, -1, r);
                }
                foreach (var b in bridges)
                {
                    string r = "jembatan STA " + RambuCore.Sta(b.S0) + " - " + RambuCore.Sta(b.S1);
                    add("Peringatan", "Jembatan", b.S0 - D, +1, r);
                    add("Peringatan", "Jembatan", b.S1 + D, -1, r);
                }
                foreach (var j in junctions)
                {
                    add("Peringatan", "APILL", j.S0 - D, +1, j.Name);
                    add("Peringatan", "APILL", j.S1 + D, -1, j.Name);
                }

                // --- Perintah: belok kiri langsung di mulut simpang ---
                foreach (var j in junctions)
                {
                    add("Perintah", "Belok Kiri Langsung", j.S0, +1, j.Name);
                    add("Perintah", "Belok Kiri Langsung", j.S1, -1, j.Name);
                }

                // --- Petunjuk arah sebelum simpang ---
                foreach (var j in junctions)
                {
                    string roads = j.Roads.Count > 0 ? string.Join(" / ", j.Roads.Distinct()) : j.Name;
                    add("Petunjuk", "Petunjuk Arah", j.S0 - p.GuideDist, +1, j.Name + ": " + roads);
                    add("Petunjuk", "Petunjuk Arah", j.S1 + p.GuideDist, -1, j.Name + ": " + roads);
                }

                // --- Lengan simpang pada jalan lain: rambu untuk lalu lintas yang menuju simpang ---
                int armCount = 0;
                foreach (var j in junctions)
                {
                    foreach (var a in j.Arms)
                    {
                        armCount++;
                        double lastX = -1e9;
                        Action<string, string, double, string> addArm = (cat, type, x, why) =>
                        {
                            if (x > a.Len)
                            {
                                // petunjuk arah tetap dipasang (16 buah), digeser ke ujung corridor lengan simpang;
                                // rambu lain di luar corridor tidak dipasang
                                if (type == "Petunjuk Arah") { x = a.Len - 5.0; why += " (ujung koridor, ± " + x.ToString("0", CultureInfo.InvariantCulture) + " m dari pusat simpang)"; }
                                else return;
                            }
                            if (x < lastX + 8.0) return;               // tidak bertumpuk
                            lastX = x;
                            signs.Add(new Sign
                            {
                                Code = RambuCore.CodeOf(type), Category = cat, Type = type,
                                Station = a.Sj - a.Dir * x, Dir = a.Dir, Reason = why,
                                Al = a.Al, SignOff = p.MinorOffset, Road = a.Road
                            });
                        };
                        string w = j.Name + ", lengan " + a.Road + " (menuju simpang)";
                        addArm("Perintah", "Belok Kiri Langsung", p.MinorHalf, w);
                        addArm("Peringatan", "APILL", p.MinorHalf + D, w);
                        addArm("Petunjuk", "Petunjuk Arah", p.MinorHalf + p.GuideDist, j.Name + ": arah JLS / " + a.Road);
                    }
                }

                // hapus hasil lama, lalu gambar
                int erased = EraseOld(db, tr);
                Draw(db, tr, al, signs, p);
                DrawLegend(db, tr, al, s0, signs, p);
                tr.Commit();

                ed.WriteMessage("\nRAMBU: corridor \"{0}\", alignment \"{1}\", STA {2} - {3}.", cor.Name, al.Name, RambuCore.Sta(s0), RambuCore.Sta(s1));
                ed.WriteMessage("\n  Simpang: {0}, tikungan (R<={1:0} m): {2}, tanjakan (>={3:0.0}%): {4} (kelandaian maks {5:0.00}%), jembatan: {6}.",
                    junctions.Count, p.CurveRmax, curves.Count, p.GradeMin, grades.Count, gmax, bridges.Count);
                ed.WriteMessage("\n  Rambu ditempatkan: {0} (hasil lama dihapus: {1}). Jarak rambu peringatan {2:0} m.", signs.Count, erased, D);
                ed.WriteMessage("\n  Lengan jalan lain: {0}, rambu di lengan jalan lain: {1}.", armCount, signs.Count(s => s.Al.ObjectId != al.ObjectId));
                foreach (var sk in armsSkipped) ed.WriteMessage("\n    Lengan tanpa rambu (corridor terlalu pendek/tidak ada): {0}", sk);
                foreach (var j in junctions)
                    ed.WriteMessage("\n    {0} @ STA {1}: {2}", j.Name, RambuCore.Sta(j.Value),
                        j.Arms.Count == 0 ? "(tidak ada lengan jalan lain)" : string.Join("; ", j.Arms.Select(a => a.Road + (a.Dir > 0 ? " [sebelum, " : " [sesudah, ") + a.Len.ToString("0") + " m]")));
            }

            string csv = WriteCsv(doc, signs);
            ed.WriteMessage("\n  Daftar rambu: {0}", csv);
        }

        static int EraseOld(Database db, Transaction tr)
        {
            int n = 0;
            var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
            foreach (ObjectId id in ms)
            {
                var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
                if (e == null) continue;
                ResultBuffer rb = e.GetXDataForApplication(RambuCore.App);
                if (rb == null) continue;
                rb.Dispose();
                e.UpgradeOpen();
                e.Erase();
                n++;
            }
            return n;
        }

        static void Draw(Database db, Transaction tr, Alignment al, List<Sign> signs, RambuParams p)
        {
            var rat = (RegAppTable)tr.GetObject(db.RegAppTableId, OpenMode.ForRead);
            if (!rat.Has(RambuCore.App))
            {
                rat.UpgradeOpen();
                var r = new RegAppTableRecord { Name = RambuCore.App };
                rat.Add(r); tr.AddNewlyCreatedDBObject(r, true);
            }
            var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);
            ObjectId layer = EnsureLayer(db, tr, p.Layer, 7);

            // lingkaran yang berdekatan di sisi yang sama digeser keluar supaya tidak bertumpuk
            double R = p.CircleRadius;
            foreach (var grp in signs.GroupBy(s => new { s.Al.ObjectId, s.Dir }))
            {
                int dir = grp.Key.Dir;
                var side = grp.OrderBy(s => s.Station).ToList();
                for (int i = 0; i < side.Count; i++)
                {
                    int stack = 0;
                    for (int k = 0; k < i; k++) if (Math.Abs(side[k].Station - side[i].Station) < 2 * R + 1) stack++;
                    side[i].OffsetUsed = -dir * (side[i].SignOff + p.CallOut + stack * (2 * R + 1.0));
                }
            }

            foreach (var s in signs)
            {
                double xs = 0, ys = 0, xc = 0, yc = 0;
                try
                {
                    s.Al.PointLocation(s.Station, -s.Dir * s.SignOff, ref xs, ref ys);     // titik rambu (tepi jalan)
                    s.Al.PointLocation(s.Station, s.OffsetUsed, ref xc, ref yc);           // pusat lingkaran keterangan
                }
                catch { continue; }
                s.X = xs; s.Y = ys;
                var ps = new Point3d(xs, ys, 0);
                var pc = new Point3d(xc, yc, 0);

                Add(ms, tr, new Circle(pc, Vector3d.ZAxis, R), layer);
                Vector3d v = (ps - pc);
                if (v.Length > R)
                {
                    // garis penunjuk dari tepi lingkaran ke titik rambu + titik kecil di posisi rambu
                    Add(ms, tr, new Line(pc + v.GetNormal() * R, ps), layer);
                    Add(ms, tr, new Circle(ps, Vector3d.ZAxis, 0.4), layer);
                }
                Add(ms, tr, new MText
                {
                    Location = pc,
                    TextHeight = p.TextHeight,
                    Attachment = AttachmentPoint.MiddleCenter,
                    Contents = s.Code
                }, layer);
            }
        }

        // tabel legenda: lingkaran kode + jenis rambu + jumlah, di sebelah awal ruas
        static void DrawLegend(Database db, Transaction tr, Alignment al, double s0, List<Sign> signs, RambuParams p)
        {
            var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);
            ObjectId layer = EnsureLayer(db, tr, p.Layer, 7);
            double x0 = 0, y0 = 0;
            try { al.PointLocation(s0, -(p.SignOffset + 120), ref x0, ref y0); } catch { return; }
            double R = p.CircleRadius, row = 2 * R + 2.5;
            Add(ms, tr, new MText
            {
                Location = new Point3d(x0 - R, y0 + row, 0), TextHeight = p.TextHeight * 1.3,
                Attachment = AttachmentPoint.BottomLeft, Contents = "KETERANGAN RAMBU (" + p.Layer + ")"
            }, layer);
            int i = 0;
            foreach (var l in RambuCore.Legend)
            {
                int n = signs.Count(s => s.Code == l[0]);
                var c = new Point3d(x0, y0 - i * row, 0);
                Add(ms, tr, new Circle(c, Vector3d.ZAxis, R), layer);
                Add(ms, tr, new MText { Location = c, TextHeight = p.TextHeight, Attachment = AttachmentPoint.MiddleCenter, Contents = l[0] }, layer);
                string name = l[2] == "Batas Kecepatan" ? "Batas Kecepatan " + p.Speed.ToString("0", CultureInfo.InvariantCulture) + " km/jam" : l[2];
                Add(ms, tr, new MText
                {
                    Location = new Point3d(c.X + R + 2.0, c.Y, 0), TextHeight = p.TextHeight,
                    Attachment = AttachmentPoint.MiddleLeft,
                    Contents = "RAMBU " + l[1].ToUpperInvariant() + " " + name.ToUpperInvariant() + " (" + n + " buah)"
                }, layer);
                i++;
            }
        }

        static void Add(BlockTableRecord ms, Transaction tr, Entity e, ObjectId layer)
        {
            e.LayerId = layer;
            e.ColorIndex = 256;
            ms.AppendEntity(e);
            tr.AddNewlyCreatedDBObject(e, true);
            // XData tanpa isi (hanya nama app) dibuang AutoCAD, jadi beri satu string penanda
            e.XData = new ResultBuffer(new TypedValue((int)DxfCode.ExtendedDataRegAppName, RambuCore.App),
                                       new TypedValue((int)DxfCode.ExtendedDataAsciiString, "rambu"));
        }

        static ObjectId EnsureLayer(Database db, Transaction tr, string name, short color)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(name)) return lt[name];
            lt.UpgradeOpen();
            var ltr = new LayerTableRecord { Name = name, Color = Color.FromColorIndex(ColorMethod.ByAci, color) };
            ObjectId id = lt.Add(ltr);
            tr.AddNewlyCreatedDBObject(ltr, true);
            return id;
        }

        static string WriteCsv(Document doc, List<Sign> signs)
        {
            var sb = new StringBuilder();
            sb.AppendLine("sep=;");
            sb.AppendLine("No;Ruas;Kode;Kategori;Jenis Rambu;STA;Station (m);Arah;Sisi;Keterangan;X;Y");
            int i = 0;
            foreach (var s in signs.OrderBy(s => s.Road != "JLS Main Road").ThenBy(s => s.Road).ThenBy(s => s.Dir < 0).ThenBy(s => s.Dir > 0 ? s.Station : -s.Station))
            {
                i++;
                sb.AppendLine(string.Join(";", new[]
                {
                    i.ToString(), "\"" + s.Road + "\"", s.Code, s.Category, s.Type, RambuCore.Sta(s.Station), s.Station.ToString("0.00", CultureInfo.InvariantCulture),
                    s.Dir > 0 ? "STA naik" : "STA turun", s.Dir > 0 ? "kiri as (offset -)" : "kanan as (offset +)",
                    "\"" + s.Reason.Replace("\"", "'") + "\"", s.X.ToString("0.000", CultureInfo.InvariantCulture), s.Y.ToString("0.000", CultureInfo.InvariantCulture)
                }));
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_rambu.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            return path;
        }

        static bool Ask(Editor ed, string msg, ref double v)
        {
            var o = new PromptDoubleOptions(msg + ": ") { DefaultValue = v, UseDefaultValue = true, AllowNegative = false, AllowZero = false };
            PromptDoubleResult r = ed.GetDouble(o);
            if (r.Status != PromptStatus.OK) return false;
            v = r.Value;
            return true;
        }
    }
}
