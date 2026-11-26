// C3DMERGE - impor object Civil 3D (alignment+profile, corridor+assembly, surface)
// dari DWG lain ke drawing aktif, untuk integrasi drawing antar tim.
using System;
using System.Collections.Generic;
using System.IO;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using CivEntity = Autodesk.Civil.DatabaseServices.Entity;

namespace C3DTools
{
    public enum CivKind { Alignment, Corridor, Surface }

    public class CivItem
    {
        public CivKind Kind;
        public string Name;
        public ObjectId Id;
    }

    public class MergeResult
    {
        public int Alignments, Corridors, Surfaces;   // jumlah yang bertambah di drawing tujuan
        public bool UsedFallback;
    }

    public static class MergeCore
    {
        public static Database OpenSource(string path)
        {
            var src = new Database(false, true);
            src.ReadDwgFile(path, FileOpenMode.OpenForReadAndAllShare, true, null);
            src.CloseInput(true);
            return src;
        }

        // unreadable: diisi keterangan object yang tidak terbaca sebagai object Civil (mis. proxy).
        public static List<CivItem> Catalog(Database db, List<string> unreadable = null)
        {
            var list = new List<CivItem>();
            CivilDocument civ = CivilDocument.GetCivilDocument(db);
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId id in civ.GetAlignmentIds()) Item(tr, id, CivKind.Alignment, list, unreadable);
                foreach (ObjectId id in civ.CorridorCollection) Item(tr, id, CivKind.Corridor, list, unreadable);
                foreach (ObjectId id in civ.GetSurfaceIds()) Item(tr, id, CivKind.Surface, list, unreadable);
                tr.Commit();
            }
            return list;
        }

        static void Item(Transaction tr, ObjectId id, CivKind kind, List<CivItem> list, List<string> unreadable)
        {
            try
            {
                Autodesk.AutoCAD.DatabaseServices.DBObject o = tr.GetObject(id, OpenMode.ForRead);
                var e = o as CivEntity;
                if (e != null) { list.Add(new CivItem { Kind = kind, Name = e.Name, Id = id }); return; }
                var px = o as ProxyEntity;
                string what = px != null
                    ? "proxy " + px.OriginalClassName + " (" + px.ApplicationDescription + ")"
                    : o.GetType().Name;
                if (unreadable != null) unreadable.Add("[" + kind + "] " + what);
            }
            catch (System.Exception ex)
            {
                if (unreadable != null) unreadable.Add("[" + kind + "] " + ex.Message);
            }
        }

        // Log langkah ke %TEMP%\c3dt_merge.log supaya penyebab kegagalan bisa dilacak.
        public static void Log(string text, bool reset = false)
        {
            try
            {
                string path = Path.Combine(Path.GetTempPath(), "c3dt_merge.log");
                string line = DateTime.Now.ToString("HH:mm:ss") + "  " + text + Environment.NewLine;
                if (reset) File.WriteAllText(path, line); else File.AppendAllText(path, line);
            }
            catch (System.Exception) { }
        }

        // Kumpulkan object terpilih + object yang menjadi dependensinya.
        public static ObjectIdCollection Expand(Database src, IEnumerable<CivItem> chosen, bool withProfileViews)
        {
            var set = new HashSet<ObjectId>();
            using (Transaction tr = src.TransactionManager.StartTransaction())
            {
                foreach (CivItem it in chosen)
                {
                    if (it.Kind == CivKind.Alignment) AddAlignment(tr, it.Id, set, withProfileViews);
                    else if (it.Kind == CivKind.Corridor) AddCorridor(tr, it.Id, set, withProfileViews);
                    else set.Add(it.Id);
                }
                tr.Commit();
            }

            // Wblock hanya menerima entity dari satu space: ambil yang di model space;
            // object anak (mis. profile) ikut lewat alignment induknya.
            ObjectId msId = SymbolUtilityServices.GetBlockModelSpaceId(src);
            var ids = new ObjectIdCollection();
            using (Transaction tr = src.TransactionManager.StartTransaction())
            {
                foreach (ObjectId id in set)
                {
                    if (id.IsNull || id.IsErased) continue;
                    Autodesk.AutoCAD.DatabaseServices.DBObject o = tr.GetObject(id, OpenMode.ForRead);
                    if (o.OwnerId == msId) ids.Add(id);
                }
                tr.Commit();
            }
            return ids;
        }

        static void AddAlignment(Transaction tr, ObjectId id, HashSet<ObjectId> set, bool withProfileViews)
        {
            if (id.IsNull || !set.Add(id)) return;
            var al = (Alignment)tr.GetObject(id, OpenMode.ForRead);
            foreach (ObjectId pid in al.GetProfileIds()) set.Add(pid);
            if (withProfileViews)
                foreach (ObjectId pv in al.GetProfileViewIds()) set.Add(pv);
        }

        static void AddCorridor(Transaction tr, ObjectId id, HashSet<ObjectId> set, bool withProfileViews)
        {
            if (!set.Add(id)) return;
            var cor = (Corridor)tr.GetObject(id, OpenMode.ForRead);
            foreach (Baseline bl in cor.Baselines)
            {
                try
                {
                    AddAlignment(tr, bl.AlignmentId, set, withProfileViews);
                    if (!bl.ProfileId.IsNull) set.Add(bl.ProfileId);
                }
                catch (System.Exception) { /* baseline berbasis feature line */ }

                foreach (BaselineRegion reg in bl.BaselineRegions)
                    AddAssembly(tr, reg.AssemblyId, set);
            }
            foreach (CorridorSurface cs in cor.CorridorSurfaces)
                if (!cs.SurfaceId.IsNull) set.Add(cs.SurfaceId);
        }

        static void AddAssembly(Transaction tr, ObjectId id, HashSet<ObjectId> set)
        {
            if (id.IsNull || !set.Add(id)) return;
            var asm = (Assembly)tr.GetObject(id, OpenMode.ForRead);
            foreach (AssemblyGroup g in asm.Groups)
                foreach (ObjectId sid in g.GetSubassemblyIds()) set.Add(sid);
        }

        public static int[] Count(Database db)
        {
            CivilDocument civ = CivilDocument.GetCivilDocument(db);
            return new[] { civ.GetAlignmentIds().Count, civ.CorridorCollection.Count, civ.GetSurfaceIds().Count };
        }

        // Pindahkan object dari database sumber ke database tujuan.
        public static MergeResult Import(Database src, Database dest, ObjectIdCollection ids)
        {
            var res = new MergeResult();
            int[] before = Count(dest);
            try
            {
                // Setara WBLOCK object terpilih lalu INSERT (explode) ke model space tujuan.
                using (Database tmp = src.Wblock(ids, Point3d.Origin))
                {
                    dest.Insert(Matrix3d.Identity, tmp, false);
                }
            }
            catch (System.Exception)
            {
                // Cadangan: clone langsung ke model space tujuan.
                res.UsedFallback = true;
                var map = new IdMapping();
                src.WblockCloneObjects(ids, SymbolUtilityServices.GetBlockModelSpaceId(dest), map,
                    DuplicateRecordCloning.Ignore, false);
            }
            int[] after = Count(dest);
            res.Alignments = after[0] - before[0];
            res.Corridors = after[1] - before[1];
            res.Surfaces = after[2] - before[2];
            return res;
        }

        // "1,3,5-7" atau "*" -> indeks (berbasis 0)
        public static List<int> ParseSelection(string text, int count)
        {
            var result = new SortedSet<int>();
            text = (text ?? "").Trim();
            if (text == "*" || text.Length == 0)
            {
                for (int i = 0; i < count; i++) result.Add(i);
                return new List<int>(result);
            }
            foreach (string part in text.Split(new[] { ',', ';', ' ' }, StringSplitOptions.RemoveEmptyEntries))
            {
                string[] r = part.Split('-');
                int a, b;
                if (!int.TryParse(r[0], out a)) continue;
                b = a;
                if (r.Length > 1 && !int.TryParse(r[1], out b)) continue;
                for (int i = Math.Min(a, b); i <= Math.Max(a, b); i++)
                    if (i >= 1 && i <= count) result.Add(i - 1);
            }
            return new List<int>(result);
        }
    }

    public class MergeCommands
    {
        [CommandMethod("C3DMERGE")]
        public void Merge()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            Database dest = doc.Database;

            var pfo = new PromptOpenFileOptions("Pilih DWG sumber (mis. FO Barat / FO Timur)") { Filter = "Drawing (*.dwg)|*.dwg" };
            PromptFileNameResult pfr = ed.GetFileNameForOpen(pfo);
            if (pfr.Status != PromptStatus.OK) return;
            string path = pfr.StringResult;
            if (string.Equals(Path.GetFullPath(path), Path.GetFullPath(doc.Name), StringComparison.OrdinalIgnoreCase))
            {
                ed.WriteMessage("\nFile sumber sama dengan drawing aktif.");
                return;
            }

            MergeCore.Log("C3DMERGE sumber=" + path + " tujuan=" + doc.Name, true);

            // Bila file sumber sedang terbuka di sesi ini, pakai database dokumennya (object Civil pasti
            // terbaca penuh); bila tidak, baca dari disk sebagai database samping.
            Database src = null;
            bool ownsSrc = false;
            DocumentLock srcLock = null;
            try
            {
                foreach (Document d in AcApp.DocumentManager)
                {
                    if (!string.Equals(Path.GetFullPath(d.Name), Path.GetFullPath(path), StringComparison.OrdinalIgnoreCase)) continue;
                    srcLock = d.LockDocument();
                    src = d.Database;
                    ed.WriteMessage("\nFile sumber sedang terbuka di sesi ini; object diambil dari dokumen yang terbuka.");
                    break;
                }
                if (src == null) { src = MergeCore.OpenSource(path); ownsSrc = true; }
                MergeCore.Log("sumber dibuka, dari dokumen terbuka=" + !ownsSrc);
            }
            catch (System.Exception ex)
            {
                MergeCore.Log("gagal membuka: " + ex);
                ed.WriteMessage("\nGagal membuka file: {0}", ex.Message);
                if (srcLock != null) srcLock.Dispose();
                return;
            }

            try
            {
                var unreadable = new List<string>();
                List<CivItem> items = MergeCore.Catalog(src, unreadable);
                MergeCore.Log("katalog sumber: " + items.Count + " terbaca, " + unreadable.Count + " tidak terbaca");
                foreach (string u in unreadable) MergeCore.Log("  tidak terbaca: " + u);
                if (unreadable.Count > 0)
                {
                    ed.WriteMessage("\nPERHATIAN: {0} object di file sumber tidak terbaca sebagai object Civil 3D dan dilewati:", unreadable.Count);
                    for (int i = 0; i < unreadable.Count && i < 10; i++) ed.WriteMessage("\n   {0}", unreadable[i]);
                    if (ownsSrc)
                        ed.WriteMessage("\nSupaya ikut terbaca: buka file sumber itu di Civil 3D ini (OPEN), kembali ke drawing tujuan, lalu jalankan C3DMERGE lagi.");
                }
                if (items.Count == 0) { ed.WriteMessage("\nTidak ada alignment/corridor/surface yang bisa diimpor dari file sumber."); return; }

                // nama yang sudah ada di drawing tujuan
                var existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (CivItem d in MergeCore.Catalog(dest)) existing.Add(d.Kind + "|" + d.Name);

                ed.WriteMessage("\nIsi {0}:", Path.GetFileName(path));
                for (int i = 0; i < items.Count; i++)
                {
                    bool dup = existing.Contains(items[i].Kind + "|" + items[i].Name);
                    ed.WriteMessage("\n  {0,3}. [{1}] {2}{3}", i + 1, items[i].Kind, items[i].Name,
                        dup ? "   <-- NAMA SUDAH ADA di drawing ini" : "");
                }

                var pso = new PromptStringOptions("\nNomor yang diimpor (mis. 1,3,5-7) atau * untuk semua <*>: ") { AllowSpaces = true };
                PromptResult psr = ed.GetString(pso);
                if (psr.Status != PromptStatus.OK) return;
                List<int> sel = MergeCore.ParseSelection(psr.StringResult, items.Count);
                if (sel.Count == 0) { ed.WriteMessage("\nTidak ada yang dipilih."); return; }

                var pko = new PromptKeywordOptions("\nIkutkan profile view? [Ya/Tidak]", "Ya Tidak") { AllowNone = true };
                pko.Keywords.Default = "Tidak";
                PromptResult pkr = ed.GetKeywords(pko);
                if (pkr.Status != PromptStatus.OK && pkr.Status != PromptStatus.None) return;
                bool withPv = pkr.Status == PromptStatus.OK && pkr.StringResult == "Ya";

                var chosen = new List<CivItem>();
                foreach (int i in sel) chosen.Add(items[i]);

                foreach (CivItem c in chosen) MergeCore.Log("dipilih: [" + c.Kind + "] " + c.Name);
                ObjectIdCollection ids = MergeCore.Expand(src, chosen, withPv);
                MergeCore.Log("entity termasuk dependensi: " + ids.Count);
                ed.WriteMessage("\nMengimpor {0} object pilihan ({1} entity termasuk dependensi)...", chosen.Count, ids.Count);

                MergeResult r = MergeCore.Import(src, dest, ids);
                MergeCore.Log("selesai: +" + r.Alignments + " alignment, +" + r.Corridors + " corridor, +" + r.Surfaces + " surface, cadangan=" + r.UsedFallback);
                ed.WriteMessage("\nSelesai. Bertambah di drawing ini: {0} alignment, {1} corridor, {2} surface.",
                    r.Alignments, r.Corridors, r.Surfaces);
                if (r.UsedFallback) ed.WriteMessage("\n(Catatan: memakai metode cadangan WblockClone.)");
                if (r.Corridors > 0) ed.WriteMessage("\nPeriksa target corridor lalu Rebuild corridor hasil impor.");
            }
            catch (System.Exception ex)
            {
                MergeCore.Log("GAGAL: " + ex);
                ed.WriteMessage("\nC3DMERGE gagal: {0}\n(rincian di %TEMP%\\c3dt_merge.log)", ex.Message);
            }
            finally
            {
                if (srcLock != null) srcLock.Dispose();
                if (ownsSrc) src.Dispose();
            }
            ed.Regen();
        }
    }
}
