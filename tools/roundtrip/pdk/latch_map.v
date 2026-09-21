// From open_pdks 8afc8346a57fe1ab7934ba5a6056ea8b43078e71,
// sky130/openlane/sky130_fd_sc_hd/latch_map.v
// (https://github.com/RTimothyEdwards/open_pdks/blob/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130/openlane/sky130_fd_sc_hd/latch_map.v;
// a PDK build installs it as sky130A/libs.tech/openlane/sky130_fd_sc_hd/latch_map.v).
// open_pdks is distributed under the Apache License 2.0 (its LICENSE file; the upstream
// file carries no header or copyright line of its own).
// Changed here: this header added, and one extra newline at the end (upstream ends in a
// single newline); everything else below is the upstream file byte for byte.
module \$_DLATCH_P_ (input E, input D, output Q);
  sky130_fd_sc_hd__dlxtp_1 _TECHMAP_DLATCH_P (
    //# {{data|Data Signals}}
    .D(D),
    .Q(Q),

    //# {{clocks|Clocking}}
    .GATE(E)
  );
endmodule

module \$_DLATCH_N_ (input E, input D, output Q);
  sky130_fd_sc_hd__dlxtn_1 _TECHMAP_DLATCH_N (
    //# {{data|Data Signals}}
    .D(D),
    .Q(Q),

    //# {{clocks|Clocking}}
    .GATE_N(E)
  );
endmodule

