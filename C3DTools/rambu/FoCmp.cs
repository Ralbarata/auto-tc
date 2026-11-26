// FODUMP - dump (read-only) alignment, profile (PVI), corridor, profile view, sample line group dan layout
// untuk SEMUA drawing yang sedang terbuka -> %TEMP%\c3d_fodump_<nama>.txt
using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace C3DRambu
{
    public class FoCmpCommands
    {
        static string F(double v) { return v.ToString("0.###", CultureInfo.InvariantCulture); }

        [CommandMethod("FODUMP", CommandFlags.Session)]
        public void Run()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument.Editor;
            foreach (Document doc in AcApp.DocumentManager)
            {
                string outPath = Path.Combine(Path.GetTempPath(), "c3d_fodump_" + Path.GetFileNameWithoutExtension(doc.Name).Replace(" ", "_") + ".txt");
                try
                {
                    using (doc.LockDocument())
                        File.WriteAllText(outPath, Dump(doc.Database), new UTF8Encoding(true));
                    ed.WriteMessage("\nFODUMP: {0} -> {1}", doc.Name, outPath);
                }
                catch (System.Exception ex) { ed.WriteMessage("\nFODUMP ERROR {0}: {1}", doc.Name, ex.Message); }
            }
        }

        static string Dump(Database db)
        {
            var sb = new StringBuilder();
            var civ = CivilDocument.GetCivilDocument(db);
            using (var tr = db.TransactionManager.StartTransaction())
            {
                // alignments + profiles
                foreach (ObjectId aid in civ.GetAlignmentIds())
                {
                    var al = tr.GetObject(aid, OpenMode.ForRead) as Alignment;
                    if (al == null) continue;
                    double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
                    try { al.PointLocation(al.StartingStation, 0, ref x0, ref y0); al.PointLocation(al.EndingStation, 0, ref x1, ref y1); } catch { }
                    sb.AppendFormat("ALIGN|{0}|type={1}|sta={2}..{3}|len={4}|start={5},{6}|end={7},{8}|ent={9}\n",
                        al.Name, al.AlignmentType, F(al.StartingStation), F(al.EndingStation), F(al.Length), F(x0), F(y0), F(x1), F(y1), al.Entities.Count);
                    try
                    {
                        foreach (AlignmentEntity ae in al.Entities)
                            for (int i = 0; i < ae.SubEntityCount; i++)
                            {
                                var se = ae[i]; var arc = se as AlignmentSubEntityArc;
                                sb.AppendFormat("  SUB|{0}|{1}|{2}..{3}|L={4}|R={5}\n", al.Name, se.SubEntityType, F(se.StartStation), F(se.EndStation), F(se.Length), arc != null ? F(arc.Radius) : "");
                            }
                    }
                    catch { }
                    foreach (ObjectId pid in al.GetProfileIds())
                    {
                        var pf = tr.GetObject(pid, OpenMode.ForRead) as Profile;
                        if (pf == null) continue;
                        sb.AppendFormat("PROF|{0}|{1}|type={2}|sta={3}..{4}\n", al.Name, pf.Name, pf.ProfileType, F(pf.StartingStation), F(pf.EndingStation));
                        if (pf.ProfileType == ProfileType.FG || pf.ProfileType == ProfileType.File)
                        {
                            try
                            {
                                foreach (ProfilePVI v in pf.PVIs)
                                {
                                    string cl = "";
                                    try { if (v.VerticalCurve != null) cl = F(v.VerticalCurve.Length); } catch { }
                                    sb.AppendFormat("  PVI|{0}|{1}|{2}|{3}|VC={4}\n", al.Name, pf.Name, F(v.Station), F(v.Elevation), cl);
                                }
                            }
                            catch { }
                        }
                    }
                    try
                    {
                        foreach (ObjectId pvId in al.GetProfileViewIds())
                        {
                            var pv = tr.GetObject(pvId, OpenMode.ForRead) as ProfileView;
                            if (pv == null) continue;
                            sb.AppendFormat("PVIEW|{0}|{1}|loc={2},{3}|sta={4}..{5}|el={6}..{7}\n", al.Name, pv.Name, F(pv.Location.X), F(pv.Location.Y),
                                F(pv.StationStart), F(pv.StationEnd), F(pv.ElevationMin), F(pv.ElevationMax));
                        }
                    }
                    catch { }
                    try
                    {
                        foreach (ObjectId gid in al.GetSampleLineGroupIds())
                        {
                            var g = tr.GetObject(gid, OpenMode.ForRead) as SampleLineGroup;
                            if (g != null) sb.AppendFormat("SLG|{0}|{1}|lines={2}\n", al.Name, g.Name, g.GetSampleLineIds().Count);
                        }
                    }
                    catch { }
                }
                // corridors
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c == null) continue;
                    sb.AppendFormat("COR|{0}\n", c.Name);
                    foreach (Baseline bl in c.Baselines)
                    {
                        string an = "", pn = "";
                        try { an = ((Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead)).Name; } catch { }
                        try { pn = ((Profile)tr.GetObject(bl.ProfileId, OpenMode.ForRead)).Name; } catch { }
                        sb.AppendFormat("  BL|{0}|{1}|{2}\n", c.Name, an, pn);
                        foreach (BaselineRegion r in bl.BaselineRegions)
                        {
                            string asm = ""; try { asm = ((Autodesk.Civil.DatabaseServices.Entity)tr.GetObject(r.AssemblyId, OpenMode.ForRead)).Name; } catch { }
                            sb.AppendFormat("  RG|{0}|{1}|{2}..{3}|{4}\n", c.Name, an, F(r.StartStation), F(r.EndStation), asm);
                        }
                    }
                }
                // layouts
                var ld = (DBDictionary)tr.GetObject(db.LayoutDictionaryId, OpenMode.ForRead);
                foreach (DBDictionaryEntry de in ld)
                {
                    var lo = (Layout)tr.GetObject(de.Value, OpenMode.ForRead);
                    if (lo.ModelType) continue;
                    var btr = (BlockTableRecord)tr.GetObject(lo.BlockTableRecordId, OpenMode.ForRead);
                    var vps = new StringBuilder(); int nvp = 0, nent = 0;
                    foreach (ObjectId eid in btr)
                    {
                        nent++;
                        var vp = tr.GetObject(eid, OpenMode.ForRead) as Viewport;
                        if (vp == null || vp.Number == 1) continue;
                        nvp++;
                        vps.AppendFormat(" [vc={0},{1} h={2} scale={3}]", F(vp.ViewCenter.X), F(vp.ViewCenter.Y), F(vp.ViewHeight), F(vp.CustomScale));
                    }
                    sb.AppendFormat("LAYOUT|{0}|tab={1}|ents={2}|vp={3}|{4}\n", lo.LayoutName, lo.TabOrder, nent, nvp, vps.ToString());
                }
                tr.Commit();
            }
            return sb.ToString();
        }
    }
}
