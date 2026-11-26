"""MainStructureUGM - pembuatan ulang terbatas dari hasil ASMDUMP (assembly "1. Mainroad Structure").

Penampang jalan di atas struktur: barrier median, deck slab, AC-WC, barrier tepi, marka, dan label.
Nama parameter, nama tampilan, nilai default, dan kode mengikuti aslinya; rumus posisi adalah
rekonstruksi dari koordinat.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pktgen import EnumGroup, Geo, If, Param, Subassembly, YESNO  # noqa: E402

# dua item supaya penomoran abjad SAC memberi MainStructure kunci 302 seperti aslinya
ROAD = EnumGroup("StructureRoadType", [("Approach", 301), ("MainStructure", 302)])
PARAMS = [
    Param("GradeRd", "double", -0.03, "Grade Road"),
    Param("GradeSh", "double", -0.04, "Grade Shoulder"),
    Param("HtBarrier", "double", 0.75, "Height Barrier"),
    Param("HtLab1", "double", 2.5, "Height Label"),
    Param("WiBarrier", "double", 0.5, "Width Barrier"),
    Param("WiInner", "double", 0.5, "Width Inner Shoulder"),
    Param("WiMark", "double", 0.12, "Width Marking"),
    Param("WiMedian", "double", 0.8, "Width Median"),
    Param("WiOuter", "double", 2.0, "Width Outer Shoulder"),
    Param("WiRoad", "double", 3.5, "Width Road Lane"),
    Param("TypeRoad", "enum", 302, "Road Type", ROAD.name),
    Param("WithLabel", "enum", 10, "With Label", YESNO.name),
]

g = Geo(PARAMS)
b, P, Q = g.b, g.P, g.Q
BAR, YM, WM = ["Barrier"], ["Yellow Marking"], ["White Marking"]


def build():
    out = []
    o = g.origin(out)

    # barrier median
    m1, l0 = P(out, o, "WiMedian/2", 0, BAR, BAR)
    a1, la1 = P(out, m1, 0, 0.1, BAR, BAR)
    a2, la2 = P(out, a1, -0.2, 0.25, BAR, BAR)
    a3, la3 = P(out, a2, -0.045, "HtBarrier", BAR, BAR)
    a4, la4 = P(out, a3, -0.025, 0.025, BAR, BAR)
    a5, la5 = P(out, a4, "-(WiMedian/2-0.27)", 0)
    la6 = b.link(out, a5, o)
    b.shape(out, [l0, la1, la2, la3, la4, la5, la6], BAR)

    # deck slab di bawah median
    d7, l7 = P(out, m1, 0, -0.05)
    d8, l8 = P(out, d7, 0, -0.25)
    d9, l9 = P(out, o, 0, -0.3)
    l10 = b.link(out, d8, d9)
    b.shape(out, [l0, l7, l8, l10, l9], ["DeckSlab"])

    # permukaan
    p10, l11 = P(out, m1, "WiInner", "WiInner*GradeRd", ["Inner Shoulder"], ["Top", "Inner Shoulder"])
    wr = "(2*WiRoad+WiMark)"
    p11, l12 = P(out, p10, wr, wr + "*GradeRd", ["Road"], ["Top", "Road"])
    p12, l13 = P(out, p11, "WiOuter", "WiOuter*GradeRd", ["Outer Shoulder"], ["Top", "Outer Shoulder"])

    # AC-WC 5 cm dan deck slab 25 cm
    q13 = Q(out, p11, 0, -0.05)
    q15, l14 = P(out, p12, 0, -0.05)
    l16 = b.link(out, d7, q13)
    l17 = b.link(out, q13, q15)
    b.shape(out, [l7, l16, l17, l14, l13, l12, l11], ["AC-WC"])
    q14 = Q(out, q13, 0, -0.25)
    q16, l15 = P(out, q15, 0, -0.25)
    l18 = b.link(out, d8, q14)
    l19 = b.link(out, q14, q16)
    b.shape(out, [l8, l18, l19, l15, l17, l16], ["DeckSlab"])

    # barrier tepi
    p17, l20 = P(out, p12, "WiBarrier", "WiBarrier*GradeRd", None, BAR)
    b18, l21 = P(out, p12, 0, 0.1, BAR, BAR)
    b19, l22 = P(out, b18, 0.2, 0.25, BAR, BAR)
    b20, l23 = P(out, b19, 0.045, "HtBarrier", BAR, BAR)
    b21, l24 = P(out, b20, 0.025, 0.025, BAR, BAR)
    b22, l25 = P(out, p17, 0, "HtBarrier+0.375-WiBarrier*GradeRd", None, BAR)
    l26 = b.link(out, b21, b22, BAR)
    b.shape(out, [l26, l25, l20, l21, l22, l23, l24], BAR)
    p23, l27 = P(out, p17, 0, -0.15, None, BAR)
    p24, l28 = P(out, q16, 0.15, "0.15*GradeRd", None, BAR)
    l29 = b.link(out, p23, p24, BAR)
    b.shape(out, [l14, l15, l28, l29, l27, l20], BAR)

    # marka
    y25, l30 = P(out, p10, "-WiMark", "-WiMark*GradeRd", None, YM)
    y26, l31 = P(out, p10, 0, 0.015, None, YM)
    y27, l32 = P(out, y25, 0, 0.015, None, YM)
    l33 = b.link(out, y26, y27, YM)
    b.shape(out, [l33, l32, l30, l31], YM)
    w28 = Q(out, p10, "WiRoad", "WiRoad*GradeRd")
    w29, l34 = P(out, w28, "WiMark", "WiMark*GradeRd", None, WM)
    w30, l35 = P(out, w29, 0, 0.015)
    w31, l36 = P(out, w28, 0, 0.015)
    l37 = b.link(out, w30, w31)
    b.shape(out, [l34, l35, l37, l36], WM)
    w32, l38 = P(out, p11, "WiMark", "WiMark*GradeRd", None, WM)
    w33, l39 = P(out, p11, 0, 0.015)
    w34, l40 = P(out, w32, 0, 0.015)
    l41 = b.link(out, w33, w34)
    b.shape(out, [l38, l40, l41, l39], WM)

    # label lebar
    lab = []
    pts = [Q(lab, o, 0, "HtLab1", ["PoinLabel"])]
    for w in ["WiMedian/2", "WiInner", "WiRoad", "WiMark", "WiRoad", "WiOuter", "WiBarrier"]:
        pts.append(Q(lab, pts[-1], w, 0, ["PoinLabel"]))
    for a, c, code in [(0, 1, "MedianLabel"), (1, 2, "InnerLabel"), (2, 3, "RoadLabel"), (4, 5, "RoadLabel"),
                       (5, 6, "OuterLabel"), (6, 7, "BarrierLabel")]:
        b.link(lab, pts[a], pts[c], [code])
    t0 = Q(lab, pts[0], 0, 1.25, ["PoinLabel"])
    t1 = Q(lab, pts[7], 0, 1.25, ["PoinLabel"])
    b.link(lab, t0, t1, ["TotalLabel"])
    out.append(If("WithLabel=Yes", lab))

    expect = {m1: (0.4, 0), a4: (0.13, 1.125), a5: (0, 1.125), d8: (0.4, -0.3), p10: (0.9, -0.015),
              p11: (8.02, -0.2286), p12: (10.02, -0.2886), q14: (8.02, -0.5286), q16: (10.02, -0.5886),
              p17: (10.52, -0.3036), b20: (10.265, 0.8114), b22: (10.52, 0.8364), p23: (10.52, -0.4536),
              p24: (10.17, -0.5931), y25: (0.78, -0.0114), w29: (4.52, -0.1236), w32: (8.14, -0.2322),
              pts[7]: (10.52, 2.5), t1: (10.52, 3.75)}
    return out, expect


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    nodes, expect = build()
    print("MainStructureUGM - cocokkan koordinat hitungan dengan CSV:")
    worst = g.check("Mainroad Structure", expect)
    sa = Subassembly("MainStructureUGM", PARAMS, [ROAD], [], nodes)
    path = os.path.abspath(os.path.join(here, "..", "pkt", "MainStructureUGM.pkt"))
    sa.write(path, loose_dir=os.path.join(here, "_out", "MainStructureUGM"))
    print("point=%d link=%d shape=%d activity=%d  selisih terbesar=%.4f m" % (b.np, b.nl, b.ns, b.act, worst))
    print("ditulis:", path)
    sa.write_test_xaml(os.path.join(here, "_out", "uji", "struktur_kiri", "x.xaml"), {}, 1)
