"""Technology description for the RETRACE extractor (tools/retrace/extract.py).

A `Tech` captures everything about a process/cell-library that the extractor's
algorithm (union-find over conductor shapes, cut layers that join adjacent
conductors, intra-cell pin geometry) needs to know, so the *algorithm* stays the
same across processes and only this table changes.

`SKY130_HD` reproduces exactly what `extract.py` did before this module existed
(see docs/spec/APPROACH.md S2/S3); it is the default `Tech` for extract.py so
every existing caller and test is unaffected. `IHP_SG13CMOS5L` describes the IHP
`sg13cmos5l` (M1-M4-TM1, 5 metal) stack used by the sister project TEMPO
(docs/TEMPO_LVS.md has the findings this table is built from).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Conductor:
    """One routing layer, in stack order (index 0 = lowest / closest to the gates).

    `datatypes` are the GDS datatypes on `layer` that count as conductor material
    for top-level routing (paths and polygons) *and* for intra-cell pin shapes.
    `label_dt` is the text (label) datatype/texttype that carries pin and port
    names on this layer.
    """

    name: str
    layer: int
    datatypes: tuple
    label_dt: int


@dataclass(frozen=True)
class Cut:
    """A via/contact layer that joins two adjacent `Conductor`s where a cut shape
    overlaps both. `below`/`above` are `Conductor.name`s."""

    layer: int
    datatype: int
    below: str
    above: str


@dataclass(frozen=True)
class Tech:
    name: str
    prefix: str  # std-cell master name prefix, e.g. "sky130_fd_sc_hd__"
    conductors: tuple  # Conductor, stack order, lowest first
    cuts: tuple  # Cut
    pin_conductors: tuple  # names of Conductors that can carry a cell-internal pin
    poly_layer: tuple | None  # (layer, datatype) gate poly drawing, for intra-cell
    #                           island joining on the lowest pin conductor; None if
    #                           the tech needs no such step
    poly_cut: tuple | None  # (layer, datatype) contact joining poly to the lowest
    #                          pin conductor (sky130: licon; IHP: Cont)
    poly_resistor_cut: tuple | None  # (layer, datatype) marker that cuts poly before
    #                                  joining, so a tie cell's output does not reach
    #                                  the supply through the gate poly (sky130 only;
    #                                  verified not needed for IHP, see TEMPO_LVS.md)
    physical_prefixes: tuple  # master suffixes (after `prefix`) with no logic
    #                           function: tap/decap/fill/diode/antenna
    supply_pins: tuple  # pin/label names that are supplies, not signals
    via_prefix: str  # top-level instance name prefix for via/connector cells
    macro_prefixes: tuple = ()  # master (name, not prefix-stripped) treated as an
    #                              opaque black box: its own top-level pin shapes
    #                              or LEF pins are its interface, its internal
    #                              hierarchy is never flattened into chip nets

    # -- derived lookups, built once -------------------------------------------
    _by_layer: dict = field(default=None, repr=False, compare=False)
    _by_name: dict = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_by_layer", {c.layer: c for c in self.conductors})
        object.__setattr__(self, "_by_name", {c.name: c for c in self.conductors})

    def conductor(self, layer):
        return self._by_layer.get(layer)

    def conductor_named(self, name):
        return self._by_name.get(name)

    def conductor_layers(self):
        return frozenset(self._by_layer)

    def is_conductor_shape(self, layer, datatype):
        c = self._by_layer.get(layer)
        return c is not None and datatype in c.datatypes

    def cut_endpoints(self, layer, datatype):
        """Return (below_layer, above_layer) for a cut shape, or None."""
        for cut in self.cuts:
            if cut.layer == layer and cut.datatype == datatype:
                return self._by_name[cut.below].layer, self._by_name[cut.above].layer
        return None

    def lowest_conductor(self):
        return self.conductors[0]


# --------------------------------------------------------------------------
# sky130_fd_sc_hd, open_pdks 8afc8346 (docs/STATUS.md), as built into
# extract.py before this refactor. GDS layer numbers as observed in this
# project's puzzle/warm-up/TEMPO-sibling GDS: li1=67 .. met5=72, conductor
# datatypes (20, 16) = (drawing, pin-marker), label texttype 5, cuts share the
# layer number of the conductor below them with datatype 44 (mcon on 67,
# licon on 66, via1..via4 on 68..71).

_SKY_CONDUCTORS = tuple(
    Conductor(name, layer, (20, 16), 5)
    for name, layer in [("li1", 67), ("met1", 68), ("met2", 69), ("met3", 70), ("met4", 71), ("met5", 72)]
)
_SKY_CUTS = tuple(
    Cut(layer=below.layer, datatype=44, below=below.name, above=above.name)
    for below, above in zip(_SKY_CONDUCTORS, _SKY_CONDUCTORS[1:])
)

SKY130_HD = Tech(
    name="sky130_hd",
    prefix="sky130_fd_sc_hd__",
    conductors=_SKY_CONDUCTORS,
    cuts=_SKY_CUTS,
    pin_conductors=("li1", "met1"),
    poly_layer=(66, 20),
    poly_cut=(66, 44),  # licon: same (layer, dt) as the li1 pin-conductor's own
    #                     cut list entry would suggest, but licon sits on the poly
    #                     layer number (66) with the shared cut datatype (44);
    #                     kept distinct from the `cuts` table because it only ever
    #                     joins poly to li1 *inside a cell*, never two routing nets
    poly_resistor_cut=(66, 15),
    physical_prefixes=("tapvpwrvgnd", "decap", "fill", "diode"),
    supply_pins=("VPWR", "VGND", "VPB", "VNB"),
    via_prefix="VIA",
)


# --------------------------------------------------------------------------
# IHP sg13cmos5l (M1-M4-TM1, 5 metal stack), from
# ~/ttsetup/pdk/ihp-sg13cmos5l/libs.tech/klayout/tech/{sg13cmos5l.map,.lyp} and
# the observed TEMPO GDS. See docs/TEMPO_LVS.md for how each entry was checked.
#
#   Metal1  8/0 drawing, 8/2 pin, 8/25 label   (map: "Metal1 NET,SPNET,PIN,LEFPIN,VIA 8 0")
#   Via1   19/0                                 joins Metal1 <-> Metal2
#   Metal2 10/0 drawing, 10/2 pin, 10/25 label
#   Via2   29/0                                 joins Metal2 <-> Metal3
#   Metal3 30/0 drawing, 30/2 pin, 30/25 label
#   Via3   49/0                                 joins Metal3 <-> Metal4
#   Metal4 50/0 drawing, 50/2 pin, 50/25 label  (TT top-level ports, per PRD)
#   TopVia1 125/0                               joins Metal4 <-> TopMetal1
#   TopMetal1 126/0 drawing, 126/2 pin, 126/25 label
#
# The .map file's own header says "M1-M4-TM1 stack": this variant of the PDK has
# five metals total (Metal1..Metal4, TopMetal1) and *no* Via4/Metal5/TopVia2/
# TopMetal2 -- those layer numbers the task brief flagged as "presumably" present
# do not appear in this PDK's layer map, and cellcheck below confirms every
# via/metal master used in TEMPO resolves to this five-layer stack.
#
# Gate poly is GatPoly (5/0); Cont (6/0) joins Metal1 to GatPoly (and, separately,
# to Activ 1/0, which the extractor never follows -- diffusion is not a signal
# conductor). Std-cell pins are plain Metal1 islands labelled on 8/25 (verified on
# sg13cmos5l_nand2_1, sg13cmos5l_tiehi/tielo in the PDK's own stdcell GDS): unlike
# sky130, a tie cell's output does not reach a Metal1-GatPoly-Cont-joined VDD/VSS
# island even without a resistor cut, so `poly_resistor_cut` is None (docs/TEMPO_LVS.md).

_IHP_CONDUCTORS = tuple(
    Conductor(name, layer, (0, 2), 25)
    for name, layer in [("Metal1", 8), ("Metal2", 10), ("Metal3", 30), ("Metal4", 50), ("TopMetal1", 126)]
)
_IHP_CUTS = (
    Cut(layer=19, datatype=0, below="Metal1", above="Metal2"),
    Cut(layer=29, datatype=0, below="Metal2", above="Metal3"),
    Cut(layer=49, datatype=0, below="Metal3", above="Metal4"),
    Cut(layer=125, datatype=0, below="Metal4", above="TopMetal1"),
)

IHP_SG13CMOS5L = Tech(
    name="ihp_sg13cmos5l",
    prefix="sg13cmos5l_",
    conductors=_IHP_CONDUCTORS,
    cuts=_IHP_CUTS,
    pin_conductors=("Metal1",),
    poly_layer=(5, 0),  # GatPoly
    poly_cut=(6, 0),  # Cont (also touches Activ 1/0, which we never follow)
    poly_resistor_cut=None,  # no poly-resistor marker in this PDK; verified
    #                          unnecessary for sg13cmos5l_tiehi/tielo (TEMPO_LVS.md)
    physical_prefixes=("decap", "fill", "antennanp"),
    supply_pins=("VDD", "VSS"),
    via_prefix="VIA",
    macro_prefixes=("RM_IHPSG13_1P_1024x32_c2_bm_bist",),
)
