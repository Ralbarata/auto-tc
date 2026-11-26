// INVASM  - daftar assembly -> subassembly -> parameter Depth/Width (read-only) -> %TEMP%\c3d_asm.csv
// ASMSET  - ubah satu parameter double pada subassembly di assembly tertentu, lalu rebuild corridor yang memakainya
// VOLREG  - volume timbunan/galian EG vs Datum per region baseline corridor (grid 2,5 m x 1 m) -> %TEMP%\c3d_volreg.csv
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
    public class Boq2Commands
    {
        static string F(double v) { return v.ToString("0.####", CultureInfo.InvariantCulture); }
        static string PKey(object p) { var pr = p.GetType().GetProperty("Key") ?? p.GetType().GetProperty("DisplayName"); return pr == null ? "" : (string)pr.GetValue(p) ?? ""; }
        static double PVal(object p) { return Convert.ToDouble(p.GetType().GetProperty("Value").GetValue(p)); }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "'") + "\""; }

        [CommandMethod("INVASM3")]
        public void InvAsm() { try { InvAsmImpl(); } catch (System.Exception ex) { AcApp.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nINVASM2 ERROR: " + ex.ToString()); } }
        void InvAsmImpl()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database;
            var civ = CivilDocument.GetCivilDocument(db);
            var sb = new StringBuilder();
            sb.AppendLine("Assembly;Group;Subassembly;Param;Value");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId aid in civ.AssemblyCollection)
                {
                    var asm = tr.GetObject(aid, OpenMode.ForRead) as Assembly;
                    if (asm == null) continue;
                    foreach (AssemblyGroup g in asm.Groups)
                        foreach (ObjectId sid in g.GetSubassemblyIds())
                        {
                            if (sid.IsNull || sid.IsErased) continue; var sa = tr.GetObject(sid, OpenMode.ForRead) as Subassembly;
                            if (sa == null) continue;
                            foreach (object p in (System.Collections.IEnumerable)sa.ParamsDouble)
                            {
                                string k = PKey(p);
                                if (k.IndexOf("Depth", StringComparison.OrdinalIgnoreCase) >= 0 || k.IndexOf("Width", StringComparison.OrdinalIgnoreCase) >= 0
                                    || k.IndexOf("Pave", StringComparison.OrdinalIgnoreCase) >= 0 || k.IndexOf("Thick", StringComparison.OrdinalIgnoreCase) >= 0
                                    || k.IndexOf("Tebal", StringComparison.OrdinalIgnoreCase) >= 0 || k.IndexOf("Lebar", StringComparison.OrdinalIgnoreCase) >= 0)
                                    sb.AppendLine(string.Join(";", Q(asm.Name), Q(g.Name), Q(sa.Name), Q(k), F(PVal(p))));
                            }
                        }
                }
                tr.Commit();
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_asm.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            doc.Editor.WriteMessage("\nINVASM selesai: {0}", path);
        }

        [CommandMethod("ASMSET3")]
        public void AsmSet() { try { AsmSetImpl(); } catch (System.Exception ex) { AcApp.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nASMSET2 ERROR: " + ex.ToString()); } }
        void AsmSetImpl()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database; var ed = doc.Editor;
            var civ = CivilDocument.GetCivilDocument(db);
            var r1 = ed.GetString(new PromptStringOptions("\nNama assembly (pisahkan dengan |)") { AllowSpaces = true }); if (r1.Status != PromptStatus.OK) return;
            var r2 = ed.GetString(new PromptStringOptions("\nNama subassembly berisi (kosong = semua)") { AllowSpaces = true }); if (r2.Status != PromptStatus.OK) return;
            var r3 = ed.GetString(new PromptStringOptions("\nKey parameter") { AllowSpaces = false }); if (r3.Status != PromptStatus.OK) return;
            var r4 = ed.GetDouble(new PromptDoubleOptions("\nNilai baru") { AllowNegative = false }); if (r4.Status != PromptStatus.OK) return;
            var names = new HashSet<string>(r1.StringResult.Split('|').Select(s => s.Trim()), StringComparer.OrdinalIgnoreCase);
            var asmIds = new HashSet<ObjectId>();
            int changed = 0; var log = new StringBuilder();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId aid in civ.AssemblyCollection)
                {
                    var asm = tr.GetObject(aid, OpenMode.ForRead) as Assembly;
                    if (asm == null || !names.Contains(asm.Name)) continue;
                    asmIds.Add(aid);
                    foreach (AssemblyGroup g in asm.Groups)
                        foreach (ObjectId sid in g.GetSubassemblyIds())
                        {
                            if (sid.IsNull || sid.IsErased) continue; var sa = tr.GetObject(sid, OpenMode.ForWrite) as Subassembly;
                            if (sa == null) continue;
                            if (r2.StringResult.Length > 0 && sa.Name.IndexOf(r2.StringResult, StringComparison.OrdinalIgnoreCase) < 0) continue;
                            foreach (object p in (System.Collections.IEnumerable)sa.ParamsDouble)
                                if (string.Equals(PKey(p), r3.StringResult, StringComparison.OrdinalIgnoreCase))
                                {
                                    log.AppendFormat("\n  {0} / {1}: {2} -> {3}", asm.Name, sa.Name, F(PVal(p)), F(r4.Value));
                                    p.GetType().GetProperty("Value").SetValue(p, r4.Value); changed++;
                                }
                        }
                }
                tr.Commit();
            }
            ed.WriteMessage("\nASMSET: {0} parameter diubah.{1}", changed, log.ToString());
            if (changed == 0) return;
            // rebuild corridor yang memakai assembly tersebut
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId cid in civ.CorridorCollection)
                {
                    var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor;
                    if (c == null) continue;
                    bool uses = false;
                    foreach (Baseline bl in c.Baselines)
                        foreach (BaselineRegion rg in bl.BaselineRegions)
                            if (!rg.AssemblyId.IsNull && asmIds.Contains(rg.AssemblyId)) uses = true;
                    if (!uses) continue;
                    c.UpgradeOpen();
                    try { c.Rebuild(); ed.WriteMessage("\n  rebuild: {0}", c.Name); }
                    catch (System.Exception ex) { ed.WriteMessage("\n  rebuild GAGAL {0}: {1}", c.Name, ex.Message); }
                }
                tr.Commit();
            }
        }

        [CommandMethod("VOLREG3")]
        public void VolReg() { try { VolRegImpl(); } catch (System.Exception ex) { AcApp.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nVOLREG2 ERROR: " + ex.ToString()); } }
        void VolRegImpl()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument; var db = doc.Database; var ed = doc.Editor;
            var civ = CivilDocument.GetCivilDocument(db);
            const string corName = "15 Nov_Main Road", egName = "EG-Existing (1)", datName = "15 Nov_Main Road Datum";
            const double ds = 2.5, dof = 1.0;
            var sb = new StringBuilder();
            sb.AppendLine("Region;Assembly;Start;End;Panjang;Fill;Cut");
            double tf = 0, tc = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Corridor cor = null; TinSurface eg = null, dat = null;
                foreach (ObjectId cid in civ.CorridorCollection) { var c = tr.GetObject(cid, OpenMode.ForRead) as Corridor; if (c != null && c.Name == corName) cor = c; }
                foreach (ObjectId sid in civ.GetSurfaceIds())
                {
                    var s = tr.GetObject(sid, OpenMode.ForRead) as TinSurface; if (s == null) continue;
                    if (s.Name == egName) eg = s; if (s.Name == datName) dat = s;
                }
                if (cor == null || eg == null || dat == null) { ed.WriteMessage("\nVOLREG: objek tidak ditemukan."); return; }
                Baseline bl = cor.Baselines[0];
                var al = (Alignment)tr.GetObject(bl.AlignmentId, OpenMode.ForRead);
                foreach (BaselineRegion rg in bl.BaselineRegions)
                {
                    string asm = ""; try { asm = ((Autodesk.Civil.DatabaseServices.Entity)tr.GetObject(rg.AssemblyId, OpenMode.ForRead)).Name; } catch { }
                    double fill = 0, cut = 0;
                    for (double s = rg.StartStation + ds / 2; s < rg.EndStation; s += ds)
                    {
                        double w = Math.Min(ds, rg.EndStation - (s - ds / 2));
                        foreach (int side in new[] { -1, 1 })
                        {
                            int miss = 0;
                            for (double o = (side < 0 ? 0.5 : 0.5); o < 150 && miss < 4; o += dof)
                            {
                                double x = 0, y = 0;
                                try { al.PointLocation(s, side * o, ref x, ref y); } catch { break; }
                                double zd, ze;
                                try { zd = dat.FindElevationAtXY(x, y); } catch { miss++; continue; }
                                try { ze = eg.FindElevationAtXY(x, y); } catch { miss++; continue; }
                                miss = 0;
                                double dz = zd - ze;
                                if (dz > 0) fill += dz * w * dof; else cut += -dz * w * dof;
                            }
                        }
                    }
                    tf += fill; tc += cut;
                    sb.AppendLine(string.Join(";", Q(rg.Name), Q(asm), F(rg.StartStation), F(rg.EndStation), F(rg.EndStation - rg.StartStation), F(fill), F(cut)));
                }
                tr.Commit();
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_volreg.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            ed.WriteMessage("\nVOLREG: fill {0:0} m3, cut {1:0} m3 -> {2}", tf, tc, path);
        }
    }
}



