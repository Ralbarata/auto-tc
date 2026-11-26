"""NewRoadUGM - pembuatan ulang terbatas dari hasil ASMDUMP file 30 Oktober.dwg.

Mencakup kombinasi parameter yang dipakai di drawing:
  - Road Type = Lokal          (assembly "2. Lokal Road", "2. Lokal Median")
  - Road Type = Mainroad       (assembly "1. Mainroad Wall", "1. Mainroad Daylight Right")
  - Road Type = Intersection   (assembly "3.Intersesction")
Nama parameter, nama tampilan, nilai default, dan kode point/link/shape mengikuti aslinya.
Rumus posisi adalah rekonstruksi dari koordinat, bukan logika asli.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pktgen import EnumGroup, Geo, If, Param, Subassembly, YESNO  # noqa: E402

ROAD = EnumGroup("RoadType", [("Intersection", 306), ("Lokal", 307), ("Mainroad", 308)])
SIDESTRUC = EnumGroup("SideStructure", [("BarrierWall", 301), ("SideSlope", 309)])
PAVE = EnumGroup("PavementType", [("Concrete", 302), ("Flexible", 304)])
MEDIAN = EnumGroup("MedianType", [("CurbMedian", 303), ("GuardrailMedian", 305)])
# Nama pilihan adalah karangan (nama asli tidak tersimpan di drawing), tetapi dipilih supaya urutan
# abjadnya menghasilkan nomor kunci yang sama dengan aslinya (301..309) saat SAC menomori ulang.
GROUPS = [ROAD, SIDESTRUC, PAVE, MEDIAN]

PARAMS = [
    Param("GradeRd", "double", -0.03, "Grade Road"),
    Param("GradeSh", "double", -0.04, "Grade Shoulder"),
    Param("HtBarrier", "double", 0.75, "Height Barrier"),
    Param("HtLab1", "double", 2.5, "Height Label "),
    Param("RetTol", "double", 0.5, "Retaining Wall Tolerance"),
    Param("Slope", "double", 0.5, "Slope Daylight"),
    Param("WiInner", "double", 0.5, "Width Inner Shoulder"),
    Param("WiMark", "double", 0.12, "Width Marking"),
    Param("WiMedian", "double", 0.8, "Width Median"),
    Param("WiOuter", "double", 2.0, "Width Outer Shoulder"),
    Param("WiRoad", "double", 3.5, "Width Road Lane"),
    Param("WiRounding", "double", 1.0, "Width Rounding"),
    Param("WiSidBarr", "double", 0.5, "Width Side Barrier"),
    Param("WiSidewalk", "double", 1.0, "Width Sidewalk"),
    Param("WiTol", "double", 1.2, "Width Tolerance Full Recon"),
    Param("MedLokal", "enum", 11, "Median Lokal", YESNO.name),
    Param("MedType", "enum", 303, "Median Type", MEDIAN.name),
    Param("PaveMain", "enum", 302, "Pavement Type", PAVE.name),
    Param("RetwithBar", "enum", 10, "Retaining Wall With Barrier", YESNO.name),
    Param("SideStrucMain", "enum", 309, "Side Structure Mainroad", SIDESTRUC.name),
    Param("TypeRoad", "enum", 307, "Road Type", ROAD.name),
    Param("WithDitch", "enum", 10, "Daylight With Ditch", YESNO.name),
    Param("WithLabel", "enum", 10, "With Label", YESNO.name),
]
TARGET = "DaylightSurface"

g = Geo(PARAMS)
b, P, Q = g.b, g.P, g.Q
EXPECT = {}          # judul varian -> {nama point: (offset, elevasi) dari CSV}

CA = "Math.Cos(Math.Atan(Slope))"
SA_ = "Math.Sin(Math.Atan(Slope))"


def rounding(out, r0, grade, bottom, depth):
    """Rounding dari tepi luar: tangen lereng `grade` -> busur R = 2 m (digantikan tali busur) -> lereng
    Slope, sampai memotong garis dasar perkerasan. Mengembalikan point ujung rounding."""
    t = "(2*Math.Tan((Math.Atan(Slope)+Math.Atan(%s))/2))" % grade
    cg = "Math.Cos(Math.Atan(%s))" % grade
    d = "(%s/(Slope+%s))" % (depth, grade)
    a1 = "(WiRounding-%s*%s)" % (t, cg)
    pa, la = P(out, r0, a1, "%s*%s" % (a1, grade), None, ["Top", "Rounding"])
    pb, lb = P(out, pa, "%s*%s+%s*%s" % (t, cg, t, CA), "%s*%s*%s-%s*%s" % (t, cg, grade, t, SA_),
               None, ["Top", "Rounding"])
    c1 = "(%s-%s*%s)" % (d, t, CA)
    pc, lc = P(out, pb, c1, "-Slope*%s" % c1, ["Rounding"], ["Top", "Rounding"])
    ldatum = b.link(out, bottom, pc, ["Datum"])
    lvert = b.link(out, r0, bottom)
    b.shape(out, [lb, lc, ldatum, lvert, la], ["Rounding"])
    return pa, pb, pc


def fill(out, frm):
    b.point_to_surface(out, frm, "-Slope", TARGET, 5, ["Daylight"], ["Top", "Daylight", "Datum"])


def cut(out, frm):
    b.point_to_surface(out, frm, "Slope", TARGET, 5, ["Daylight"], ["Top", "Datum", "Daylight"])


def ditch(out, frm):
    """Saluran DS2 (ukuran tetap seperti aslinya) + lean concrete, lalu daylight galian."""
    q, _ = P(out, frm, 0.2, "-0.2*Slope")
    top, cur = [], q
    for dx, dy in [(0.08, 0), (0.02, -0.75), (0.05, -0.05), (0.46, 0), (0.05, 0.05), (0.02, 0.75), (0.08, 0)]:
        cur, lk = P(out, cur, dx, dy, ["Ditch DS2"], ["Top", "Ditch DS2"])
        top.append(lk)
    end = cur
    wo, lwo = P(out, end, 0, -0.88, None, ["Ditch DS2", "Datum"])
    wi, lwi = P(out, q, 0, -0.88, None, ["Ditch DS2", "Datum"])
    lbot = b.link(out, wo, wi, ["Ditch DS2"])
    b.shape(out, top + [lwo, lbot, lwi], ["Ditch DS2"])
    lean = ["Datum", "Lean Concrete"]
    eo, leo = P(out, wo, 0.05, 0, None, lean)
    ei, lei = P(out, wi, -0.05, 0, None, lean)
    bi, lbi = P(out, ei, 0, -0.12, None, lean)
    bo, lbo = P(out, eo, 0, -0.12, None, lean)
    lbb = b.link(out, bi, bo, lean)
    b.shape(out, [lbot, lei, lbi, lbb, lbo, leo], ["Lean Concrete"])
    cut(out, end)
    return q, end


def daylight(out, frm):
    """Node penutup rantai: layout menggambar timbunan dan galian; saat dipakai di corridor dipilih
    menurut posisi point `frm` terhadap surface target."""
    lay = []
    fill(lay, frm)
    chk = ditch(lay, frm)
    d_fill, d_ditch, d_cut = [], [], []
    fill(d_fill, frm)
    ditch(d_ditch, frm)
    cut(d_cut, frm)
    out.append(If("SA.IsLayout", lay,
                  [If("%s.distancetosurface(%s)>=0" % (frm, TARGET), d_fill,
                      [If("WithDitch=Yes", d_ditch, d_cut)])]))
    return chk


def labels(out, o, widths, upper_dy):
    """Deret point label pada ketinggian HtLab1; widths = lebar tiap ruas. Mengembalikan daftar point
    dan point label atas di sumbu."""
    pts = [Q(out, o, 0, "HtLab1", ["PoinLabel"])]
    for w in widths:
        pts.append(Q(out, pts[-1], w, 0, ["PoinLabel"]))
    top = Q(out, pts[0], 0, upper_dy, ["PoinLabel"])
    return pts, top


# ================================================================ Road Type = Lokal
def lokal(out, o):
    med = []
    m1, lm = P(med, o, "WiMedian/2", "WiMedian/2*GradeRd")
    c1, lc1 = P(med, m1, 0, 0.1, ["Curb"], ["Curb"])
    c2, lc2 = P(med, c1, -0.025, 0.175, ["Curb"], ["Curb"])
    c3, lc3 = P(med, c2, -0.025, 0.025, ["Curb"], ["Curb"])
    c4, lc4 = P(med, c3, "-(WiMedian/2-0.05)", 0, None, ["Sidewalk"])
    lc5 = b.link(med, o, c4, ["Sidewalk"])
    b.shape(med, [lc5, lc4, lc3, lc2, lc1, lm], ["Curb"])
    out.append(If("MedLokal=Yes", med))

    w1 = "(2*WiRoad-WiOuter)"
    p2, l1 = P(out, o, w1, w1 + "*GradeRd", ["Road"], ["Top", "Road"])
    p3, l2 = P(out, p2, "WiOuter", "WiOuter*GradeRd", ["Road"], ["Top", "Road"])
    p4, l3 = P(out, o, 0, -0.05)
    p5, l4 = P(out, p3, 0, -0.05)
    l5 = b.link(out, p4, p5)
    b.shape(out, [l2, l4, l5, l3, l1], ["AC-WC"])
    p6, l6 = P(out, p5, "-WiOuter", "-WiOuter*GradeRd")
    po, pi, pl = p5, p6, l6
    for thick, code in [(0.25, "AC-Base"), (0.15, "LFA Class A"), (0.20, "Drainage Layer"), (0.20, "Selected Material")]:
        qo, lo = P(out, po, 0, -thick)
        qi, li = P(out, pi, 0, -thick)
        lb = b.link(out, qo, qi)
        b.shape(out, [pl, li, lb, lo], [code])
        po, pi, pl = qo, qi, lb
    pa, pb, pc = rounding(out, p3, "GradeRd", po, 0.85)
    dq, de = daylight(out, pc)
    EXPECT["Lokal"] = {p2: (5, -0.15), p3: (7, -0.21), p5: (7, -0.26), po: (7, -1.06), pa: (7.5596, -0.2268),
                       pb: (8.3941, -0.437), pc: (9.8085, -1.1443), dq: (10.0085, -1.2443), de: (10.7685, -1.2443),
                       m1: (0.4, -0.012), c3: (0.35, 0.288), c4: (0, 0.288)}


# ================================================================ Road Type = Mainroad
def mainroad(out, o):
    # median: curb + sidewalk
    m1, lm = P(out, o, "WiMedian/2", 0, ["Barrier"], ["Barrier"])
    c1, lc1 = P(out, m1, 0, 0.1, ["Curb"], ["Curb"])
    c2, lc2 = P(out, c1, -0.025, 0.175, ["Curb"], ["Curb"])
    c3, lc3 = P(out, c2, -0.025, 0.025, ["Curb"], ["Curb"])
    k1, lk1 = P(out, m1, -0.2, 0)
    k2, lk2 = P(out, k1, 0, 0.3)
    lk3 = b.link(out, c3, k2)
    k3, lk4 = P(out, o, 0, 0.3)
    lk5 = b.link(out, k1, o)
    lk6 = b.link(out, k2, k3, ["Sidewalk"])
    b.shape(out, [lc1, lc2, lc3, lk3, lk2, lk1], ["Curb"])
    b.shape(out, [lk2, lk6, lk4, lk5], ["Sidewalk"])

    # permukaan
    p8, l10 = P(out, m1, "WiInner", "WiInner*GradeRd", ["Inner Shoulder"], ["Top", "Inner Shoulder"])
    wr = "(2*WiRoad+WiMark)"
    p9, l11 = P(out, p8, wr, wr + "*GradeRd", ["Road"], ["Top", "Road"])
    p10, l12 = P(out, p9, "WiOuter", "WiOuter*GradeRd", ["Outer Shoulder"], ["Top", "Outer Shoulder"])

    # lapis perkerasan di bawah [median .. tepi lajur .. tepi bahu]
    tops, top_links = [m1, p9, p10], [l10, l11, l12]
    first_verts = None
    for thick, code, bc in [(0.33, "Concrete Pavement", None), (0.15, "Lean Concrete", None),
                            (0.20, "Drainage Layer", None), (0.20, "Selected Material", ["Datum"])]:
        new, verts = [], []
        for c in tops:
            q, lv = P(out, c, 0, -thick)
            new.append(q)
            verts.append(lv)
        bottoms = [b.link(out, new[0], new[1], bc), b.link(out, new[1], new[2], bc)]
        b.shape(out, top_links + [verts[2]] + list(reversed(bottoms)) + [verts[0]], [code])
        tops, top_links = new, bottoms
    base_in, base_mid, base_out = tops

    # LFA Class B di bawah median
    u1, lu1 = P(out, o, 0, -0.88)
    lu2 = b.link(out, base_in, u1, ["Datum"])
    lu3 = b.link(out, m1, base_in)
    b.shape(out, [lm, lu3, lu2, lu1], ["LFA Class B"])

    # marka: kuning di tepi dalam, putih di tengah dan tepi luar lajur
    y1, ly1 = P(out, p8, "-WiMark", "-WiMark*GradeRd", ["Yellow Marking"])
    y2, ly2 = P(out, y1, 0, 0.015)
    y3, ly3 = P(out, p8, 0, 0.015)
    ly4 = b.link(out, y2, y3)
    b.shape(out, [ly1, ly2, ly4, ly3], ["Yellow Marking"])
    w0 = Q(out, p8, "WiRoad", "WiRoad*GradeRd", ["White Marking"])
    marking_from(out, w0)
    w2 = Q(out, p9, 0, 0, ["White Marking"])
    marking_from(out, w2)

    # label lebar
    lab = []
    pts, top = labels(lab, o, ["WiMedian/2", "WiInner", "WiRoad", "WiMark", "WiRoad", "WiOuter"], 2)
    for a, c, code in [(0, 1, "MedianLabel"), (1, 2, "InnerLabel"), (2, 3, "RoadLabel"), (4, 5, "RoadLabel"),
                       (5, 6, "ShoulderLabel")]:
        b.link(lab, pts[a], pts[c], [code])
    pv1 = Q(lab, pts[1], 0, 1, ["PoinLabel"])
    pv2 = Q(lab, pts[6], 0, 1, ["PoinLabel"])
    b.link(lab, pv1, pv2, ["Pavement Label"])
    out.append(If("WithLabel=Yes", lab))

    # ---- sisi luar: dinding penahan + barrier
    wall = []
    w24, l32 = P(wall, p10, "WiSidBarr", 0, None, ["Barrier"])
    bar = []
    b1, lb1 = P(bar, p10, 0, 0.1, ["Barrier"], ["Barrier"])
    b2, lb2 = P(bar, b1, 0.2, 0.25, ["Barrier"], ["Barrier"])
    b3, lb3 = P(bar, b2, 0.075, "HtBarrier", ["Barrier"], ["Barrier"])
    b4, lb4 = P(bar, b3, 0.025, 0.025, ["Barrier"], ["Barrier"])
    b5, lb5 = P(bar, w24, 0, "HtBarrier+0.375", None, ["Barrier"])
    lb6 = b.link(bar, b4, b5, ["Barrier"])
    b.shape(bar, [l32, lb5, lb6, lb4, lb3, lb2, lb1], ["Barrier"])
    wall.append(If("RetwithBar=Yes", bar))
    r31, lr1 = P(wall, w24, -0.3, 0)
    r33, lr2 = P(wall, w24, 0, -0.3)
    r34, lr3 = P(wall, r31, 0, -0.3)
    r35, lr4 = P(wall, r33, 0.2, 0)
    r36, lr5 = P(wall, r34, -0.2, 0)
    r37, lr6 = P(wall, r35, 0, -0.2)
    r38, lr7 = P(wall, r36, 0, -0.2)
    lr8 = b.link(wall, r37, r38)
    b.shape(wall, [lr2, lr4, lr6, lr8, lr7, lr5, lr3, lr1], ["RetainingWall"])
    wlab = []
    e1 = Q(wlab, pts[6], "WiSidBarr", 0, ["PoinLabel"])
    b.link(wlab, pts[6], e1, ["BarrierLabel"])
    e2 = Q(wlab, e1, 0, 2, ["PoinLabel"])
    b.link(wlab, top, e2, ["TotalLabel"])
    wall.append(If("WithLabel=Yes", wlab))

    # ---- sisi luar: rounding + daylight
    day = []
    # kode point SAC harus teks biasa atau nama parameter (rumus ditolak), jadi sisi dipilih lewat percabangan
    g_left, g_right = [], []
    Q(g_left, p10, 0.75, 0, ["Guardrail Left"])
    Q(g_right, p10, 0.75, 0, ["Guardrail Right"])
    day.append(If("Side=Left", g_left, g_right))
    pa, pb, pc = rounding(day, p10, "GradeRd", base_out, 0.88)
    dlab = []
    dx_round = "(WiRounding+0.88/(Slope+GradeRd))"
    f1 = Q(dlab, pts[6], dx_round, 0, ["PoinLabel"])
    b.link(dlab, pts[6], f1, ["RoundingLabel"])
    f2 = Q(dlab, f1, 0, 2, ["PoinLabel"])
    b.link(dlab, top, f2, ["TotalLabel"])
    day.append(If("WithLabel=Yes", dlab))
    daylight(day, pc)

    out.append(If("SideStrucMain=BarrierWall", wall, day))
    EXPECT["Mainroad"] = {m1: (0.4, 0), c3: (0.35, 0.3), k2: (0.2, 0.3), p8: (0.9, -0.015), p9: (8.02, -0.2286),
                          p10: (10.02, -0.2886), base_in: (0.4, -0.88), base_mid: (8.02, -1.1086),
                          base_out: (10.02, -1.1686), y1: (0.78, -0.0114), w0: (4.4, -0.12),
                          pts[6]: (10.02, 2.5), top: (0, 4.5), pv2: (10.02, 3.5)}
    EXPECT["Mainroad + dinding"] = {w24: (10.52, -0.2886), b3: (10.295, 0.8114), b5: (10.52, 0.8364),
                                    r37: (10.72, -0.7886), r38: (10.02, -0.7886), e2: (10.52, 4.5)}
    EXPECT["Mainroad + daylight"] = {pa: (10.5796, -0.3054), pb: (11.4141, -0.5156), pc: (12.8923, -1.2548),
                                     f1: (12.8924, 2.5)}


def marking_from(out, m0):
    """Marka putih setebal 1,5 cm selebar WiMark mulai dari point m0 (sudah berkode White Marking)."""
    m1, l1 = P(out, m0, "WiMark", "WiMark*GradeRd", ["White Marking"], ["White Marking"])
    u0, lu0 = P(out, m0, 0, 0.015, None, ["White Marking"])
    u1, lu1 = P(out, m1, 0, 0.015, None, ["White Marking"])
    lt = b.link(out, u0, u1)
    b.shape(out, [l1, lu1, lt, lu0], ["White Marking"])


# ================================================================ Road Type = Intersection
def intersection(out, o):
    def body(dst, width, grade):
        p5, l4 = P(dst, o, width, "%s*%s" % (width, grade), ["Road"] if grade == "GradeRd" else None, ["Top", "Road"])
        ti, to, tl = o, p5, l4
        for n, thick in enumerate([0.33, 0.15, 0.20, 0.20]):
            qi, li = P(dst, ti, 0, -thick)
            qo, lo = P(dst, to, 0, -thick)
            lb = b.link(dst, qi, qo, ["Datum"] if n == 3 else None)
            b.shape(dst, [li, lb, lo, tl], None)
            ti, to, tl = qi, qo, lb
        return p5, to

    left, right = [], []
    lp, lbot = body(left, "(2*WiRoad-WiOuter)", "GradeRd")
    rp, rbot = body(right, "WiOuter", "GradeSh")
    pa, pb, pc = rounding(right, rp, "GradeSh", rbot, 0.88)
    daylight(right, pc)
    out.append(If("Side=Left", left, right))
    EXPECT["Intersection kiri"] = {lp: (5, -0.15), lbot: (5, -1.03)}
    EXPECT["Intersection kanan"] = {rp: (2, -0.08), rbot: (2, -0.96), pa: (2.5702, -0.1028), pb: (3.3847, -0.3124),
                                    pc: (4.913, -1.0765)}


def build():
    main = []
    o = g.origin(main)
    lo, mr, ix = [], [], []
    lokal(lo, o)
    mainroad(mr, o)
    intersection(ix, o)
    main.append(If("TypeRoad=Lokal", lo, [If("TypeRoad=Mainroad", mr, ix)]))
    return main


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    nodes = build()
    print("NewRoadUGM - cocokkan koordinat hitungan dengan CSV:")
    worst = max(g.check(k, v) for k, v in EXPECT.items())
    sa = Subassembly("NewRoadUGM", PARAMS, GROUPS, [TARGET], nodes)
    path = os.path.abspath(os.path.join(here, "..", "pkt", "NewRoadUGM.pkt"))
    sa.write(path, loose_dir=os.path.join(here, "_out", "NewRoadUGM"))
    print("point=%d link=%d shape=%d activity=%d  selisih terbesar=%.4f m" % (b.np, b.nl, b.ns, b.act, worst))
    print("ditulis:", path)
    tests = {
        "lokal": ({"TypeRoad": 307, "MedLokal": 11}, 0),
        "lokal_median": ({"TypeRoad": 307, "MedLokal": 10}, 1),
        "mainroad_dinding": ({"TypeRoad": 308, "SideStrucMain": 301}, 1),
        "mainroad_daylight_kanan": ({"TypeRoad": 308, "SideStrucMain": 309}, 0),
        "mainroad_daylight_kiri": ({"TypeRoad": 308, "SideStrucMain": 309}, 1),
        "intersection_kiri": ({"TypeRoad": 306}, 1),
        "intersection_kanan": ({"TypeRoad": 306}, 0),
    }
    for name, (ov, side) in tests.items():
        sa.write_test_xaml(os.path.join(here, "_out", "uji", name, "x.xaml"), ov, side)
