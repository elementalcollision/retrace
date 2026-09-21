// From open_pdks 8afc8346a57fe1ab7934ba5a6056ea8b43078e71,
// sky130/openlane/sky130_fd_sc_hd/tribuff_map.v
// (https://github.com/RTimothyEdwards/open_pdks/blob/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130/openlane/sky130_fd_sc_hd/tribuff_map.v;
// a PDK build installs it as sky130A/libs.tech/openlane/sky130_fd_sc_hd/tribuff_map.v).
// open_pdks is distributed under the Apache License 2.0 (its LICENSE file; the upstream
// file carries no header or copyright line of its own).
// Changed here: this header added, and a newline added at the end (upstream ends without
// one); everything else below is the upstream file byte for byte.
module \$_TBUF_ (input A, input E, output Y);
  sky130_fd_sc_hd__ebufn_2 _TECHMAP_EBUF_N_ (
    .A(A),
    .Z(Y),
    .TE_B(~E));
endmodule
