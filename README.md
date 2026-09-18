# RETRACE

The inverse of TEMPO's flow: GDS to cells to nets to netlist to RTL to intent. It is
first applied to Jane Street's ASIC reverse-engineering puzzle
(https://blog.janestreet.com/can-you-reverse-engineer-an-asic/), whose contest
closed on 2026-09-04.

* `docs/prd/PRD.md`: what we are building and why, with measured facts about the target
* `docs/spec/APPROACH.md`: the eight-stage pipeline and the oracle for each stage
* `docs/spec/VERIFICATION.md`: check layers V0-V8 and the layout-mutation campaign
* `docs/STATUS.md`: current state
* `upstream/`: the puzzle repo, vendored read-only
