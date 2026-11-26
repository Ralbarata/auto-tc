// INVBOQ - pembacaan (read-only) data drawing untuk pembanding BoQ:
// volume surface, lebar link corridor, elevasi FG/EG tiap 50 m, dan jumlah objek per layer/block.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivSurface = Autodesk.Civil.DatabaseServices.Surface;

namespace C3DRambu
{
    public class InvBoqCommands
    {
        static string F(double v) { return v.ToString("0.###", CultureInfo.InvariantCulture); }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "'") + "\""; }

        [CommandMethod("INVBOQ")]
        public void Run()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);
            string tmp = Path.GetTempPath();
            var log = new StringBuilder();

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                // ---------- 1. surfaces ----------
                var sb = new StringBuilder();
                sb.AppendLine("Nama;Tipe;Cut;Fill;Net;Area2D");
                var tins = new List<TinSurface>();
                foreach (ObjectId sid in civ.GetSurfaceIds())
                {
                    var s = tr.GetObject(sid, OpenMode.ForRead) as CivSurface;
                    if (s == null) continue;
                    string cut = "", fill = "", net = "", area = "";
                    try { var ts = s as TinSurface; if (ts != null) area = F(ts.GetTerrainProperties().SurfaceArea2D); } catch { }
                    var vs = s as TinVolumeSurface;
                    if (vs != null)
                    {
                        try { var vp = vs.GetVolumeProperties(); cut = F(vp.UnadjustedCutVolume); fill = F(vp.UnadjustedFillVolume); net = F(vp.UnadjustedNetVolume); } catch (System.Exception ex) { cut = "ERR " + ex.Message; }
                    }
                    else { var t = s as TinSurface; if (t != null) tins.Add(t); }
                    sb.AppendLine(string.Join(";", Q(s.Name), s.GetType().Name, cut, fill, net, area));
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_boq_surfaces.csv"), sb.ToString(), new UTF8Encoding(true));

                // ---------- 2. corridor Main Road: link codes & offsets ----------
                sb.Clear();
                sb.AppendLine("Region;Station;Code;MinOffset;MaxOffset;MinElev;MaxElev");
                Corridor cor = null;
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c != null && c.Name == "15 Nov_Main Road") cor = c;
                }
                Alignment al = null; Profile pf = null;
                if (cor != null)
                {
                    Baseline bl = cor.Baselines[0];
                    al = (Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead);
                    try { pf = tr.GetObject(bl.ProfileId, OpenMode.ForRead) as Profile; } catch { }
                    string[] codes = new string[0];
                    try { codes = cor.GetLinkCodes(); } catch (System.Exception ex) { log.Append(" linkcodes:" + ex.Message); }
                    foreach (BaselineRegion r in bl.BaselineRegions)
                    {
                        AppliedAssembly aa = null;
                        try
                        {
                            var col = r.AppliedAssemblies;
                            if (col.Count == 0) continue;
                            aa = col[col.Count / 2];
                        }
                        catch (System.Exception ex) { log.Append(" aa:" + ex.Message); break; }
                        foreach (string code in codes)
                        {
                            try
                            {
                                var links = aa.GetLinksByCode(code);
                                double mn = 1e9, mx = -1e9, zn = 1e9, zx = -1e9, st = 0; int np = 0;
                                foreach (CalculatedLink lk in links)
                                    foreach (CalculatedPoint cp in lk.CalculatedPoints)
                                    {
                                        var p = cp.StationOffsetElevationToBaseline;
                                        st = p.X; np++;
                                        mn = Math.Min(mn, p.Y); mx = Math.Max(mx, p.Y); zn = Math.Min(zn, p.Z); zx = Math.Max(zx, p.Z);
                                    }
                                if (np > 0) sb.AppendLine(string.Join(";", Q(r.Name), F(st), Q(code), F(mn), F(mx), F(zn), F(zx)));
                            }
                            catch { }
                        }
                    }
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_boq_links.csv"), sb.ToString(), new UTF8Encoding(true));

                // ---------- 3. FG / EG tiap 50 m ----------
                sb.Clear();
                if (al != null)
                {
                    sb.Append("STA;FG");
                    foreach (var t in tins) sb.Append(";" + Q(t.Name));
                    sb.AppendLine();
                    double s0 = Math.Ceiling(al.StartingStation / 50.0) * 50.0;
                    for (double s = s0; s <= al.EndingStation; s += 50.0)
                    {
                        double x = 0, y = 0;
                        try { al.PointLocation(s, 0, ref x, ref y); } catch { continue; }
                        string fg = "";
                        try { if (pf != null) fg = F(pf.ElevationAt(s)); } catch { }
                        sb.Append(F(s) + ";" + fg);
                        foreach (var t in tins)
                        {
                            string z = "";
                            try { z = F(t.FindElevationAtXY(x, y)); } catch { }
                            sb.Append(";" + z);
                        }
                        sb.AppendLine();
                    }
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_boq_fgeg.csv"), sb.ToString(), new UTF8Encoding(true));

                // ---------- 4. objek per layer / block ----------
                var cnt = new Dictionary<string, int>();
                var len = new Dictionary<string, double>();
                var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    string cls = id.ObjectClass.DxfName;
                    if (cls != "INSERT" && cls != "LWPOLYLINE" && cls != "LINE" && cls != "POLYLINE" && cls != "CIRCLE") continue;
                    var e = tr.GetObject(id, OpenMode.ForRead) as Autodesk.AutoCAD.DatabaseServices.Entity;
                    if (e == null) continue;
                    string key;
                    if (e is BlockReference)
                    {
                        var br = (BlockReference)e;
                        string bn = br.Name;
                        try { if (br.IsDynamicBlock) bn = ((BlockTableRecord)tr.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead)).Name; } catch { }
                        key = "INSERT|" + e.Layer + "|" + bn;
                    }
                    else key = cls + "|" + e.Layer;
                    cnt[key] = (cnt.ContainsKey(key) ? cnt[key] : 0) + 1;
                    var cu = e as Curve;
                    if (cu != null && !(e is Circle))
                    {
                        double l = 0;
                        try { l = cu.GetDistanceAtParameter(cu.EndParam) - cu.GetDistanceAtParameter(cu.StartParam); } catch { }
                        len[key] = (len.ContainsKey(key) ? len[key] : 0) + l;
                    }
                }
                sb.Clear();
                sb.AppendLine("Tipe;Layer;Block;Jumlah;Panjang");
                foreach (var kv in cnt.OrderBy(k => k.Key))
                {
                    var p = kv.Key.Split('|');
                    sb.AppendLine(string.Join(";", p[0], Q(p[1]), Q(p.Length > 2 ? p[2] : ""), kv.Value.ToString(), len.ContainsKey(kv.Key) ? F(len[kv.Key]) : ""));
                }
                File.WriteAllText(Path.Combine(tmp, "c3d_boq_objects.csv"), sb.ToString(), new UTF8Encoding(true));
                tr.Commit();
            }
            ed.WriteMessage("\nINVBOQ selesai. File: {0}c3d_boq_*.csv {1}", tmp, log.ToString());
        }
    }
}
