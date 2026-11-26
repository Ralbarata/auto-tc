// C3DT_SELFTEST - uji asap: buat data uji (surface, alignment, profile), jalankan inti RMARK
// dan C3DMERGE, lalu tulis hasilnya. Tidak mengubah drawing proyek; jalankan di drawing kosong.
using System;
using System.IO;
using System.Text;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace C3DTools
{
    public class SelfTest
    {
        [CommandMethod("C3DT_SELFTEST")]
        public void Run()
        {
            var log = new StringBuilder();
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            string dir = Environment.GetEnvironmentVariable("C3DT_TESTDIR") ?? Path.GetTempPath();
            string srcPath = Path.Combine(dir, "c3dt_src.dwg");
            string destPath = Path.Combine(dir, "c3dt_dest.dwg");
            try
            {
                CivilDocument civ = CivilDocument.GetCivilDocument(db);
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    // surface bidang miring z = 10 + 0.02x
                    ObjectId sId = TinSurface.Create(db, "EG-TEST");
                    var surf = (TinSurface)tr.GetObject(sId, OpenMode.ForWrite);
                    var pts = new Point3dCollection();
                    for (int x = -10; x <= 110; x += 10)
                        for (int y = -20; y <= 20; y += 10)
                            pts.Add(new Point3d(x, y, 10 + 0.02 * x));
                    surf.AddVertices(pts);

                    ObjectId aStyle = GetOrAdd(civ.Styles.AlignmentStyles, "T");
                    ObjectId aLbl = GetOrAdd(civ.Styles.LabelSetStyles.AlignmentLabelSetStyles, "T");
                    ObjectId aId = Alignment.Create(civ, "AL-TEST", ObjectId.Null, db.Clayer, aStyle, aLbl);
                    var al = (Alignment)tr.GetObject(aId, OpenMode.ForWrite);
                    al.Entities.AddFixedLine(new Point3d(0, 0, 0), new Point3d(100, 0, 0));

                    ObjectId pStyle = GetOrAdd(civ.Styles.ProfileStyles, "T");
                    ObjectId pLbl = GetOrAdd(civ.Styles.LabelSetStyles.ProfileLabelSetStyles, "T");
                    Profile.CreateFromSurface("EG-PROF", aId, sId, db.Clayer, pStyle, pLbl);

                    var p = new MarkingParams { Offset = 1.75, Dashed = true, DashLength = 3, GapLength = 5, Width = 0.12, AsArea = true };
                    MarkingResult r = MarkingCore.Draw(db, tr, al, surf, p);
                    log.AppendLine($"RMARK putus: dibuat={r.Created} (harap 13) dilewati={r.Skipped} panjang={r.Length:F2} (harap 37.00) luas={r.Area:F3}");

                    var p2 = new MarkingParams { Offset = -1.75, Dashed = false, Width = 0.12, AsArea = false, StaStart = 20, StaEnd = 60 };
                    MarkingResult r2 = MarkingCore.Draw(db, tr, al, surf, p2);
                    log.AppendLine($"RMARK utuh : dibuat={r2.Created} (harap 1) panjang={r2.Length:F2} (harap 40.00)");

                    // cek elevasi vertex pertama marka terakhir: x=20 -> z = 10.4 + 0.005
                    var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
                    Polyline3d last = null;
                    foreach (ObjectId id in ms)
                        if (id.ObjectClass.DxfName == "POLYLINE") last = (Polyline3d)tr.GetObject(id, OpenMode.ForRead);
                    if (last != null)
                        log.AppendLine($"Vertex awal marka utuh: {last.StartPoint} (harap (20,-1.75,10.405)) layer={last.Layer}");

                    // di luar surface -> harus dilewati, bukan error
                    var p3 = new MarkingParams { Offset = 50, Dashed = true };
                    MarkingResult r3 = MarkingCore.Draw(db, tr, al, surf, p3);
                    log.AppendLine($"RMARK luar surface: dibuat={r3.Created} (harap 0) dilewati={r3.Skipped}");

                    // chevron di pulau persegi 10 x 10 m, sumbu di tengah
                    var sq = new System.Collections.Generic.List<Point2d> {
                        new Point2d(20, -5), new Point2d(30, -5), new Point2d(30, 5), new Point2d(20, 5) };
                    var cp = new ChevronParams { AxisFrom = new Point2d(20, 0), AxisTo = new Point2d(30, 0), VShape = true, AngleDeg = 45, Width = 0.30, Gap = 1.00 };
                    MarkingResult rc = ChevronCore.Draw(db, tr, sq, surf, 0, cp);
                    log.AppendLine($"RCHEVRON V: dibuat={rc.Created} dilewati={rc.Skipped} luas={rc.Area:F2} (harap sekitar 23 dari 100 m2)");
                    cp.VShape = false;
                    MarkingResult rs = ChevronCore.Draw(db, tr, sq, null, 12.0, cp);
                    log.AppendLine($"RCHEVRON serong datar: dibuat={rs.Created} luas={rs.Area:F2} (harap sekitar 23)");
                    tr.Commit();
                }

                db.SaveAs(srcPath, DwgVersion.Current);
                log.AppendLine("Sumber disimpan: " + srcPath);

                using (var dest = new Database(true, true))
                using (Database src = MergeCore.OpenSource(srcPath))
                {
                    var items = MergeCore.Catalog(src);
                    foreach (CivItem it in items) log.AppendLine($"  katalog: [{it.Kind}] {it.Name}");
                    ObjectIdCollection ids = MergeCore.Expand(src, items, false);
                    log.AppendLine($"Entity yang dipindah: {ids.Count}");
                    MergeResult m = MergeCore.Import(src, dest, ids);
                    log.AppendLine($"MERGE: +{m.Alignments} alignment (harap 1), +{m.Corridors} corridor, +{m.Surfaces} surface (harap 1), fallback={m.UsedFallback}");

                    CivilDocument dciv = CivilDocument.GetCivilDocument(dest);
                    using (Transaction tr = dest.TransactionManager.StartTransaction())
                    {
                        foreach (ObjectId id in dciv.GetAlignmentIds())
                        {
                            var al = (Alignment)tr.GetObject(id, OpenMode.ForRead);
                            log.AppendLine($"  tujuan: alignment {al.Name} panjang={al.Length:F2} jumlah profile={al.GetProfileIds().Count} (harap 1)");
                            foreach (ObjectId pid in al.GetProfileIds())
                            {
                                var pr = (Profile)tr.GetObject(pid, OpenMode.ForRead);
                                log.AppendLine($"    profile {pr.Name} elev@50={pr.ElevationAt(50):F3} (harap 11.000)");
                            }
                        }
                        foreach (ObjectId id in dciv.GetSurfaceIds())
                        {
                            var s = (TinSurface)tr.GetObject(id, OpenMode.ForRead);
                            log.AppendLine($"  tujuan: surface {s.Name} z@(50,0)={s.FindElevationAtXY(50, 0):F3} (harap 11.000)");
                        }
                        tr.Commit();
                    }
                    dest.SaveAs(destPath, DwgVersion.Current);
                }
                log.AppendLine("SELFTEST SELESAI");
            }
            catch (System.Exception ex)
            {
                log.AppendLine("SELFTEST GAGAL: " + ex);
            }
            File.WriteAllText(Path.Combine(dir, "c3dt_selftest.log"), log.ToString());
            doc.Editor.WriteMessage("\n" + log);
        }

        static ObjectId GetOrAdd(Autodesk.Civil.DatabaseServices.Styles.StyleCollectionBase col, string name)
        {
            try { return col[name]; } catch (System.Exception) { return col.Add(name); }
        }
    }
}
