// INVVOL - volume galian/timbunan Main Road: EG vs Datum corridor, memakai TinVolumeSurface sementara
// yang dibuat di dalam transaksi lalu dibatalkan (drawing tidak berubah). Hasil: %TEMP%\c3d_boq_vol.csv
using System;
using System.Globalization;
using System.IO;
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
    public class InvVolCommands
    {
        [CommandMethod("INVVOL")]
        public void Run()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            CivilDocument civ = CivilDocument.GetCivilDocument(db);
            string[][] pairs =
            {
                new[] { "EG-Existing (1)", "15 Nov_Main Road Datum" },
                new[] { "EG-Existing (1)", "15 Nov_Main Road Top" },
            };
            var sb = new StringBuilder();
            sb.AppendLine("Base;Comparison;Cut;Fill;Net;Status");
            foreach (var pr in pairs)
            {
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    ObjectId b = ObjectId.Null, c = ObjectId.Null;
                    foreach (ObjectId sid in civ.GetSurfaceIds())
                    {
                        var s = tr.GetObject(sid, OpenMode.ForRead) as CivSurface;
                        if (s == null) continue;
                        if (s.Name == pr[0]) b = sid;
                        if (s.Name == pr[1]) c = sid;
                    }
                    string status = "ok", cut = "", fill = "", net = "";
                    try
                    {
                        if (b.IsNull || c.IsNull) throw new System.Exception("surface tidak ditemukan");
                        ObjectId vid = TinVolumeSurface.Create("TMP_INVVOL_" + Guid.NewGuid().ToString("N").Substring(0, 6), b, c);
                        var vs = (TinVolumeSurface)tr.GetObject(vid, OpenMode.ForWrite);
                        try { vs.Rebuild(); } catch { }
                        var vp = vs.GetVolumeProperties();
                        cut = vp.UnadjustedCutVolume.ToString("0.00", CultureInfo.InvariantCulture);
                        fill = vp.UnadjustedFillVolume.ToString("0.00", CultureInfo.InvariantCulture);
                        net = vp.UnadjustedNetVolume.ToString("0.00", CultureInfo.InvariantCulture);
                        vs.Erase();
                    }
                    catch (System.Exception ex) { status = "ERR " + ex.Message; }
                    tr.Abort();   // batalkan: volume surface sementara tidak tersimpan
                    sb.AppendLine(string.Join(";", pr[0], pr[1], cut, fill, net, status));
                }
            }
            string path = Path.Combine(Path.GetTempPath(), "c3d_boq_vol.csv");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
            ed.WriteMessage("\nINVVOL selesai: {0}", path);
        }
    }
}
