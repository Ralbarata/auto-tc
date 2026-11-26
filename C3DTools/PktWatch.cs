// Pemulihan PKT: Civil 3D memuat subassembly SAC yang tertanam di DWG dengan mengekstraknya
// sebentar ke folder kerja lalu menghapusnya. Selama file penanda %TEMP%\c3dt_pktwatch.on ada,
// plugin ini menyalin setiap file paket (pkt/xaml/atc/...) yang muncul ke %TEMP%\c3dt_pkt.
// Tanpa file penanda, tidak ada yang diawasi.
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using Autodesk.AutoCAD.Runtime;

[assembly: ExtensionApplication(typeof(C3DTools.PktWatch))]

namespace C3DTools
{
    public class PktWatch : IExtensionApplication
    {
        static readonly List<FileSystemWatcher> Watchers = new List<FileSystemWatcher>();
        static readonly string[] Exts = { ".pkt", ".xaml", ".atc", ".cfg", ".emd", ".pvd", ".png", ".chm" };
        static string outDir;
        static int counter;

        public void Initialize()
        {
            try
            {
                string temp = Path.GetTempPath();
                if (!File.Exists(Path.Combine(temp, "c3dt_pktwatch.on"))) return;
                outDir = Path.Combine(temp, "c3dt_pkt");
                Directory.CreateDirectory(outDir);
                Log("mulai mengawasi");
                Watch(temp);
                Watch(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData) + @"\Autodesk");
                Watch(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) + @"\Autodesk");
                Watch(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData) + @"\Autodesk");
            }
            catch (System.Exception) { }
        }

        public void Terminate()
        {
            foreach (FileSystemWatcher w in Watchers) { try { w.Dispose(); } catch (System.Exception) { } }
        }

        static void Watch(string dir)
        {
            if (!Directory.Exists(dir)) return;
            var w = new FileSystemWatcher(dir)
            {
                IncludeSubdirectories = true,
                InternalBufferSize = 64 * 1024,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size
            };
            foreach (string e in Exts) w.Filters.Add("*" + e);
            w.Created += OnEvent;
            w.Changed += OnEvent;
            w.Renamed += (s, e) => Grab(e.FullPath);
            w.EnableRaisingEvents = true;
            Watchers.Add(w);
        }

        static void OnEvent(object sender, FileSystemEventArgs e) { Grab(e.FullPath); }

        static void Grab(string path)
        {
            try
            {
                if (path.IndexOf("c3dt_pkt", StringComparison.OrdinalIgnoreCase) >= 0) return;
                if (path.IndexOf(@"\claude\", StringComparison.OrdinalIgnoreCase) >= 0) return;
                for (int attempt = 0; attempt < 5; attempt++)
                {
                    try
                    {
                        byte[] data;
                        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                        {
                            data = new byte[fs.Length];
                            int read = 0;
                            while (read < data.Length)
                            {
                                int n = fs.Read(data, read, data.Length - read);
                                if (n <= 0) break;
                                read += n;
                            }
                        }
                        if (data.Length == 0) { Thread.Sleep(30); continue; }
                        int no = Interlocked.Increment(ref counter);
                        string parent = Path.GetFileName(Path.GetDirectoryName(path)) ?? "";
                        string name = no.ToString("000") + "__" + parent + "__" + Path.GetFileName(path);
                        File.WriteAllBytes(Path.Combine(outDir, name), data);
                        Log(no.ToString("000") + " " + data.Length + " B  " + path);
                        return;
                    }
                    catch (FileNotFoundException) { return; }
                    catch (DirectoryNotFoundException) { return; }
                    catch (IOException) { Thread.Sleep(30); }
                }
            }
            catch (System.Exception) { }
        }

        static void Log(string line)
        {
            try
            {
                lock (Watchers)
                    File.AppendAllText(Path.Combine(outDir, "_log.txt"), DateTime.Now.ToString("HH:mm:ss.fff") + " " + line + Environment.NewLine);
            }
            catch (System.Exception) { }
        }
    }
}
