"""Generator PKT Subassembly Composer.

Menyusun flowchart SAC (.xaml) beserta file pendamping (.atc, .cfg, .emd, .pvd) dari spesifikasi
Python, lalu mengemasnya menjadi .pkt. File .dll tidak ikut dibuat: SAC membuatnya sendiri saat
paket dibuka lalu disimpan (Save) di Subassembly Composer.

Pola penulisan elemen diambil dari PKT bawaan Civil 3D 2027.
"""
import uuid
import zipfile
from xml.sax.saxutils import escape

Q = {'"': "&quot;"}


def esc(text):
    return escape(str(text), Q)


def num(v):
    return ("%r" % float(v)).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


# ---------------------------------------------------------------- parameter
class Param:
    def __init__(self, name, kind, default, display=None, group=None):
        self.name, self.kind, self.default = name, kind, default
        self.display = display or name
        self.group = group          # nama EnumGroup untuk kind == "enum"


class EnumGroup:
    def __init__(self, name, items):
        self.name = name
        self.items = items          # list (Name, Key)

    def name_of(self, key):
        for n, k in self.items:
            if k == key:
                return n
        raise KeyError(key)


STD_ENUMS = [("Left", 1), ("LeftInsideLane", 20), ("LeftInsideShoulder", 21), ("LeftOutsideLane", 22),
             ("LeftOutsideShoulder", 23), ("No", 11), ("None", -1), ("Right", 0), ("RightInsideLane", 24),
             ("RightInsideShoulder", 25), ("RightOutsideLane", 26), ("RightOutsideShoulder", 27), ("Yes", 10)]
YESNO = EnumGroup("Yes\\No", [("Yes", 10), ("No", 11)])
SIDE = EnumGroup("Side", [("Left", 1), ("Right", 0)])


# ---------------------------------------------------------------- flowchart
class If:
    def __init__(self, cond, then, orelse=None):
        self.cond, self.then, self.orelse = cond, then, orelse or []


class Builder:
    """Mengumpulkan activity. Nama point/link/shape dibuat urut dan unik di seluruh flowchart."""

    COMMON = ('Geometry="[Geometry]" sap:VirtualizedContainerService.HintSize="200,22" ShowErrors="True" '
              'SubassemblyErrorCenter="[SubassemblyErrorCenter]" SubassemblyRunMode="[SubassemblyRunMode]"')

    def __init__(self):
        self.np = self.nl = self.ns = self.act = 0

    def _id(self):
        self.act += 1
        return self.act

    @staticmethod
    def _codes(tag, codes):
        if not codes:
            return ""
        # kode berawalan "[" adalah ekspresi VB (mis. kode yang bergantung pada sisi), selain itu teks biasa
        items = "".join('<InArgument x:TypeArguments="x:String">%s</InArgument>' % esc(c) for c in codes)
        return ('<asa1:%s><scg:List x:TypeArguments="InArgument(x:String)" Capacity="4">%s</scg:List></asa1:%s>'
                % (tag, items, tag))

    def _point(self, frm, positioning, args, codes, link_codes, autolink):
        self.np += 1
        name = "P%d" % self.np
        attrs = []
        lname = None
        if autolink:
            self.nl += 1
            lname = "L%d" % self.nl
            if not link_codes:
                attrs.append('AutoLinkCodes="{x:Null}"')
            attrs.append('AutoLinkGeometryName="%s"' % lname)
        else:
            attrs.append('AutoLinkCodes="{x:Null}" AutoLinkGeometryName="{x:Null}"')
        if not codes:
            attrs.append('PointCodes="{x:Null}"')
        if frm is None:
            attrs.append('FromPoint="{x:Null}"')
        else:
            attrs.append('FromPoint="%s"' % frm)
        display = name + ("&amp;" + lname if lname else "")
        xml = ('<asa1:CreatePoint %s ActivityId="%d" ApplyAOR="False" AutoLink="%s" DisplayName="%s" '
               'PointNumber="%s" Positioning="%s" Side="[Side]" %s>'
               % (" ".join(attrs), self._id(), "True" if autolink else "False", display, name, positioning,
                  self.COMMON))
        xml += "<asa1:CreatePoint.Arguments>%s</asa1:CreatePoint.Arguments>" % args
        if autolink:
            xml += self._codes("CreatePoint.AutoLinkCodes", link_codes)
        xml += self._codes("CreatePoint.PointCodes", codes)
        xml += "</asa1:CreatePoint>"
        return name, lname, xml

    def point(self, out, frm, dx, dy, codes=None, link=None, autolink=False):
        """Point dari `frm` dengan delta x/y (angka atau ekspresi VB). Mengembalikan nama point
        (dan nama link bila autolink)."""
        args = ('<InArgument x:TypeArguments="x:Double" x:Key="DeltaX1">%s</InArgument>'
                '<InArgument x:TypeArguments="x:Double" x:Key="DeltaY1">%s</InArgument>' % (self._expr(dx), self._expr(dy)))
        name, lname, xml = self._point(frm, "DeltaXAndDeltaY", args, codes, link, autolink)
        out.append(xml)
        return (name, lname) if autolink else name

    def point_to_surface(self, out, frm, slope, target, layout_dx, codes=None, link=None):
        """Point pada perpotongan garis miring dari `frm` dengan surface target (daylight)."""
        args = ('<InArgument x:TypeArguments="x:Double" x:Key="Slope3">%s</InArgument>'
                '<InArgument x:TypeArguments="x:Boolean" x:Key="ReverseSlopeDirection3">False</InArgument>'
                '<InArgument x:TypeArguments="asw:SurfaceTarget" x:Key="SurfaceTarget3">[%s]</InArgument>'
                '<InArgument x:TypeArguments="x:Double" x:Key="DeltaXForLayout3">%s</InArgument>'
                '<InArgument x:TypeArguments="x:Boolean" x:Key="ShowErrors">True</InArgument>'
                % (self._expr(slope), target, num(layout_dx)))
        name, lname, xml = self._point(frm, "SlopeToSurface", args, codes, link, True)
        out.append(xml)
        return name, lname

    def link(self, out, a, b, codes=None):
        self.nl += 1
        name = "L%d" % self.nl
        null = '' if codes else 'LinkCodes="{x:Null}" '
        head = ('<asa1:CreateLink %sActivityId="%d" ApplyAOR="False" DisplayName="%s" EndPoint="%s" IsEnabled="True" '
                'LinkNumber="%s" StartPoint="%s" %s' % (null, self._id(), name, b, name, a, self.COMMON))
        if codes:
            out.append(head + ">" + self._codes("CreateLink.LinkCodes", codes) + "</asa1:CreateLink>")
        else:
            out.append(head + " />")
        return name

    def shape(self, out, links, codes):
        self.ns += 1
        name = "S%d" % self.ns
        comps = "".join("<x:String>%s</x:String>" % l for l in links)
        null = '' if codes else 'ShapeCodes="{x:Null}" '
        out.append('<asa1:CreateShape %sActivityId="%d" DisplayName="%s" Links="%s" ShapeNumber="%s" %s>'
                   '<asa1:CreateShape.ComponentNames>%s</asa1:CreateShape.ComponentNames>%s</asa1:CreateShape>'
                   % (null, self._id(), name, ",".join(links), name, self.COMMON, comps,
                      self._codes("CreateShape.ShapeCodes", codes)))
        return name

    @staticmethod
    def _expr(v):
        if isinstance(v, (int, float)):
            return num(float(v)) if isinstance(v, float) else str(v)
        return "[%s]" % esc(v)


# ---------------------------------------------------------------- emit xaml
class Emitter:
    def __init__(self):
        self.ref = 0
        self.refs = []
        self.max_y = 0

    def _name(self):
        n = "__ReferenceID%d" % self.ref
        self.ref += 1
        self.refs.append(n)
        return n

    @staticmethod
    def _view(x, y, w, h):
        return ('<sap:WorkflowViewStateService.ViewState><scg:Dictionary x:TypeArguments="x:String, x:Object">'
                '<av:Point x:Key="ShapeLocation">%s,%s</av:Point><av:Size x:Key="ShapeSize">%s,%s</av:Size>'
                '</scg:Dictionary></sap:WorkflowViewStateService.ViewState>' % (num(x), num(y), w, h))

    @classmethod
    def depth(cls, nodes):
        d = 0
        for n in nodes:
            d += 4 + max(cls.depth(n.then), cls.depth(n.orelse)) if isinstance(n, If) else 1
        return d

    def chain(self, nodes, i, x, y, spread, tail=None):
        """Rantai node mulai indeks i. `tail` = lanjutan setelah rantai ini habis (dipakai saat cabang
        percabangan bergabung kembali): ditulis utuh sekali, lalu dirujuk dengan x:Reference."""
        if i >= len(nodes):
            return tail.use() if tail else ""
        self.max_y = max(self.max_y, y)
        node = nodes[i]
        if isinstance(node, If):
            name = self._name()
            inner = max(self.depth(node.then), self.depth(node.orelse))
            if i + 1 < len(nodes):
                rest_name = "__ReferenceID%d" % self.ref          # nama node pertama lanjutan
                rest = self.chain(nodes, i + 1, x, y + 150 + 45 * inner, spread, tail)
                tail = _Tail(rest, rest_name)
            xml = ('<FlowDecision x:Name="%s" Condition="[%s]" sap:VirtualizedContainerService.HintSize="70,87">'
                   % (name, esc(node.cond)))
            xml += self._view(x + 65, y, 70, 87)
            t = self.chain(node.then, 0, x - spread, y + 120, spread / 2, tail)
            f = self.chain(node.orelse, 0, x + spread, y + 120, spread / 2, tail)
            if t:
                xml += "<FlowDecision.True>%s</FlowDecision.True>" % t
            if f:
                xml += "<FlowDecision.False>%s</FlowDecision.False>" % f
            return xml + "</FlowDecision>"
        name = self._name()
        xml = '<FlowStep x:Name="%s">%s%s' % (name, self._view(x, y, 200, 22), node)
        nxt = self.chain(nodes, i + 1, x, y + 45, spread, tail)
        if nxt:
            xml += "<FlowStep.Next>%s</FlowStep.Next>" % nxt
        return xml + "</FlowStep>"


class _Tail:
    def __init__(self, xml, name):
        self.xml, self.name, self.used = xml, name, False

    def use(self):
        if not self.xml:
            return ""
        if self.used:
            return "<x:Reference>%s</x:Reference>" % self.name
        self.used = True
        return self.xml


class Geo:
    """Builder + penghitung koordinat: setiap point dihitung juga secara numerik dengan rumus yang sama,
    supaya hasilnya bisa dicocokkan dengan koordinat dari ASMDUMP."""

    class _Math:
        import math as _m
        Tan, Atan, Cos, Sin, Sqrt = _m.tan, _m.atan, _m.cos, _m.sin, _m.sqrt

    def __init__(self, params):
        self.b = Builder()
        self.env = {p.name: p.default for p in params if p.kind == "double"}
        self.env["Math"] = self._Math
        self.coord = {}

    def val(self, expr):
        return float(expr) if isinstance(expr, (int, float)) else float(eval(expr, {"__builtins__": {}}, self.env))

    def origin(self, out):
        p = self.b.point(out, None, 0, 0)
        self.coord[p] = (0.0, 0.0)
        return p

    def P(self, out, frm, dx, dy, codes=None, link=None, autolink=True):
        r = self.b.point(out, frm, dx, dy, codes, link, autolink)
        name = r[0] if autolink else r
        x0, y0 = self.coord[frm]
        self.coord[name] = (x0 + self.val(dx), y0 + self.val(dy))
        return r

    def Q(self, out, frm, dx, dy, codes=None):
        """Point tanpa link."""
        return self.P(out, frm, dx, dy, codes, None, False)

    def check(self, title, expect):
        worst = 0.0
        for name, (ex, ey) in expect.items():
            x, y = self.coord[name]
            worst = max(worst, abs(x - ex), abs(y - ey))
        print("  %-28s %2d titik, selisih terbesar %.4f m" % (title, len(expect), worst))
        return worst


NS = ('xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
      'xmlns:asa="clr-namespace:Autodesk.SubassemblyComposer.API;assembly=Subassembly.API" '
      'xmlns:asa1="clr-namespace:Autodesk.SubassemblyComposer.ActivityLibrary;assembly=Subassembly.ActivityLibrary" '
      'xmlns:asw="clr-namespace:Autodesk.SubassemblyComposer.WorkflowEngine;assembly=Subassembly.WorkflowEngine" '
      'xmlns:av="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
      'xmlns:mva="clr-namespace:Microsoft.VisualBasic.Activities;assembly=System.Activities" '
      'xmlns:s="clr-namespace:System;assembly=mscorlib" '
      'xmlns:sa="clr-namespace:System.Activities;assembly=System.Activities" '
      'xmlns:sap="http://schemas.microsoft.com/netfx/2009/xaml/activities/presentation" '
      'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=mscorlib" '
      'xmlns:this="clr-namespace:" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')
VBSET = "Assembly references and imported namespaces serialized as XML namespaces"


class Subassembly:
    def __init__(self, name, params, groups, surface_targets, nodes, preview_surface_elev=-3.0):
        self.name, self.params, self.groups = name, params, groups
        self.surface_targets, self.nodes = surface_targets, nodes
        self.preview_surface_elev = preview_surface_elev
        self.guid = uuid.uuid4().hex
        self.side = 0               # nilai default Side di pratinjau: 0 = Right, 1 = Left
        # SAC menomori ulang kunci enum saat membuka paket: urut abjad nama item, mulai 301, lintas grup.
        # Nilai default parameter tidak ikut diubah, jadi kunci di sini harus sudah mengikuti aturan itu.
        items = sorted((it for grp in groups for it in grp.items), key=lambda it: it[0].lower())
        for n, (name_, key) in enumerate(items):
            if key != 301 + n:
                raise ValueError("kunci enum %s=%d tidak sesuai urutan abjad SAC (seharusnya %d)" % (name_, key, 301 + n))

    def _group(self, p):
        if p.group == YESNO.name:
            return YESNO
        if p.group == SIDE.name:
            return SIDE
        return next(g for g in self.groups if g.name == p.group)

    def _default_attr(self, p):
        if p.kind == "enum":
            g = self._group(p)
            return '[new EnumType(%d, "%s", "%s")]' % (p.default, g.name_of(p.default), g.name)
        return num(p.default) if p.kind == "double" else str(p.default)

    def xaml(self):
        attrs = ['this:Subassembly.Side="%s"' % esc('[new EnumType(%d, "%s", "Side")]'
                                                    % (self.side, "Left" if self.side else "Right"))]
        members = ['<x:Property Name="Geometry" Type="InOutArgument(asw:Geometry)" />',
                   '<x:Property Name="SubassemblyErrorCenter" Type="InOutArgument(asw:SubassemblyErrorCenter)" />',
                   '<x:Property Name="SubassemblyRunMode" Type="InOutArgument(asw:SubassemblyRunMode)" />',
                   '<x:Property Name="Side" Type="InArgument(asw:EnumType)" />']
        types = {"double": "x:Double", "int": "x:Int32", "string": "x:String", "enum": "asw:EnumType"}
        for p in self.params:
            attrs.append('this:Subassembly.%s="%s"' % (p.name, esc(self._default_attr(p))))
            members.append('<x:Property Name="%s" Type="InArgument(%s)"><x:Property.Attributes>'
                           '<asw:DisplayName2Attribute DisplayName="%s" /></x:Property.Attributes></x:Property>'
                           % (p.name, types[p.kind], esc(p.display)))
        for t in self.surface_targets:
            e = num(float(self.preview_surface_elev))
            attrs.append('this:Subassembly.%s="%s"'
                         % (t, esc('[new PreviewSurfaceTarget("%s", True, 1000, %s, -1000, %s)]' % (t, e, e))))
            members.append('<x:Property Name="%s" Type="InArgument(asw:SurfaceTarget)" />' % t)

        variables = []
        seen = set()
        for n, k in STD_ENUMS + [it for g in self.groups for it in g.items]:
            if n in seen:
                continue
            seen.add(n)
            variables.append('<Variable x:TypeArguments="asw:EnumType" Default="%s" Modifiers="ReadOnly" Name="%s" />'
                             % (esc('[new EnumType(%d, "%s")]' % (k, n)), n))

        em = Emitter()
        body = em.chain(self.nodes, 0, 1600, 100, 800)
        refs = "".join("<x:Reference>%s</x:Reference>" % r for r in em.refs)
        h = em.max_y + 200
        return ('<Activity mc:Ignorable="sap" x:Class="Subassembly" %s %s><x:Members>%s</x:Members>'
                '<sap:VirtualizedContainerService.HintSize>1700,%d</sap:VirtualizedContainerService.HintSize>'
                '<mva:VisualBasic.Settings>%s</mva:VisualBasic.Settings>'
                '<Flowchart sap:VirtualizedContainerService.HintSize="1660,%d" mva:VisualBasic.Settings="%s">'
                '<Flowchart.Variables>%s</Flowchart.Variables>'
                '<sap:WorkflowViewStateService.ViewState><scg:Dictionary x:TypeArguments="x:String, x:Object">'
                '<x:Boolean x:Key="IsExpanded">False</x:Boolean><av:Point x:Key="ShapeLocation">770,2.5</av:Point>'
                '<av:Size x:Key="ShapeSize">60,75</av:Size><x:Double x:Key="Width">1640</x:Double>'
                '<x:Double x:Key="Height">%d</x:Double></scg:Dictionary></sap:WorkflowViewStateService.ViewState>'
                '<Flowchart.StartNode>%s</Flowchart.StartNode>%s</Flowchart></Activity>'
                % (" ".join(attrs), NS, "".join(members), h + 40, VBSET, h, VBSET, "".join(variables), h, body, refs))

    def atc(self):
        rows = ['<Side DataType="long" TypeInfo="16" DisplayName="Side" Description="Side">0<Enum>'
                '<Left DisplayName="Left">1</Left><Right DisplayName="Right">0</Right></Enum></Side>']
        dt = {"double": "double", "int": "long", "string": "string", "enum": "long"}
        for p in self.params:
            val = num(p.default) if p.kind == "double" else str(p.default)
            enum = ""
            if p.kind == "enum":
                enum = "<Enum>%s</Enum>" % "".join('<%s DisplayName="%s">%d</%s>' % (n, n, k, n)
                                                   for n, k in self._group(p).items)
            rows.append('<%s DataType="%s" TypeInfo="16" DisplayName="%s" Description="%s">%s%s</%s>'
                        % (p.name, dt[p.kind], esc(p.display), p.name, esc(val), enum, p.name))
        return ('<?xml version="1.0"?>\n<Category xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ItemID idValue="{%s}" /><Properties>'
                '<ItemName>Category1</ItemName><Images><Image cx="93" cy="123" /></Images></Properties><CustomData />'
                '<Source /><Palettes /><Packages /><Tools><Tool Name="%s"><ItemID idValue="{%s}" /><Properties>'
                '<ItemName>%s</ItemName><Images><Image cx="64" cy="64" /></Images><Help><HelpFile /><HelpCommand />'
                '<HelpData /></Help></Properties><Source /><StockToolRef idValue="{7F55AAC0-0256-48D7-BFA5-914702663FDE}" />'
                '<Data><AeccDbSubassembly><GeometryGenerateMode>UseDotNet</GeometryGenerateMode>'
                '<DotNetClass Assembly="%s.dll">Subassembly.%s</DotNetClass><Params>%s</Params></AeccDbSubassembly>'
                '<Units>m</Units></Data></Tool></Tools><StockTools /></Category>'
                % (uuid.uuid4(), self.name, uuid.uuid4(), self.name, self.guid, self.name, "".join(rows)))

    def emd(self):
        groups = "".join('<EnumGroup Name="%s"><Items>%s</Items></EnumGroup>'
                         % (esc(g.name), "".join('<EnumItem Name="%s" DisplayName="%s" Key="%d" />' % (n, n, k)
                                                 for n, k in g.items)) for g in self.groups)
        return ('<?xml version="1.0"?>\n<EnumData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xmlns:xsd="http://www.w3.org/2001/XMLSchema"><EnumDatas><Groups>%s</Groups><DefinedVariables />'
                '</EnumDatas></EnumData>' % groups)

    CFG = ('<?xml version="1.0"?><Configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xmlns:xsd="http://www.w3.org/2001/XMLSchema"><CreatedWith><ProductName>Autodesk Subassembly Composer'
           '</ProductName><Version>ForVail</Version><VersionNumber>12.0.842.0</VersionNumber></CreatedWith>'
           '</Configuration>')

    @staticmethod
    def pvd():
        segs = ["LeftInsideLane", "LeftInsideShoulder", "LeftOutsideLane", "LeftOutsideShoulder",
                "RightInsideLane", "RightInsideShoulder", "RightOutsideLane", "RightOutsideShoulder"]
        rows = "".join('<PreviewCrossSlope CrossSegmentType="%s" Slope="-0.02" IsDefined="true" />' % s for s in segs)
        return ('<?xml version="1.0"?>\n<PreviewData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xmlns:xsd="http://www.w3.org/2001/XMLSchema"><Superelevation><CrossSlopes>%s</CrossSlopes>'
                '</Superelevation><Cant><CantParams>'
                '<PreviewCantParam Name="CantPivotType" Value="CenterLine" />'
                '<PreviewCantParam Name="LeftRail" Value="" />'
                '<PreviewCantParam Name="LeftRailDeltaElevation" Value="0" />'
                '<PreviewCantParam Name="RightRail" Value="" />'
                '<PreviewCantParam Name="RightRailDeltaElevation" Value="0" />'
                '</CantParams></Cant></PreviewData>' % rows)   # bagian Cant wajib ada: SAC 2027 mengaksesnya saat membuka

    CONTENT_TYPES = ('<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/'
                     '2006/content-types"><Default Extension="atc" ContentType="" /><Default Extension="cfg" '
                     'ContentType="" /><Default Extension="xaml" ContentType="" /><Default Extension="pvd" '
                     'ContentType="" /><Default Extension="emd" ContentType="" /></Types>')

    def write_test_xaml(self, path, overrides, side=0):
        """Tulis XAML dengan nilai default parameter yang diganti, untuk diuji dengan mesin SAC."""
        import copy
        import os
        saved, saved_side = self.params, self.side
        self.params = [copy.copy(p) for p in saved]
        for p in self.params:
            if p.name in overrides:
                p.default = overrides[p.name]
        self.side = side
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.xaml())
        self.params, self.side = saved, saved_side

    def write(self, path, loose_dir=None):
        files = {"[Content_Types].xml": self.CONTENT_TYPES,
                 self.guid + ".atc": self.atc(), self.guid + ".cfg": self.CFG,
                 self.guid + ".xaml": self.xaml(), self.guid + ".pvd": self.pvd(), self.guid + ".emd": self.emd()}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for n, c in files.items():
                z.writestr(n, c.encode("utf-8"))
        if loose_dir:
            import os
            import shutil
            shutil.rmtree(loose_dir, ignore_errors=True)
            os.makedirs(loose_dir, exist_ok=True)
            for n, c in files.items():
                with open(os.path.join(loose_dir, n.replace("[", "").replace("]", "")), "w", encoding="utf-8") as f:
                    f.write(c)
        return files
