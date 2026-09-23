# S3 prior art: recovering word-level structure from gate-level netlists

Survey notes for RETRACE stretch goal S3 (automatic structure recognition: word grouping, shift
registers, counters, LFSRs/CRCs, adders, comparators). Written 2026-09-21.

Purpose: (a) borrow proven methods, (b) not claim novelty for known ideas, (c) copy good
evaluation practice.

## 0. How this survey was done (and its limits)

- Tools: Crossref search (most citations and DOIs come from here), Semantic Scholar (paper
  lookups by DOI worked; keyword search was rate-limited with HTTP 429 about half the time),
  WebSearch and WebFetch. The arXiv API tool returned HTTP 406 on every query, and the IEEE Xplore
  tool reported itself unavailable (it needs a subscription), so arXiv papers were reached through
  WebFetch on arxiv.org, and IEEE papers through Crossref, Semantic Scholar and open PDFs.
- Every citation below turned up in a search run for this survey. Titles, authors, venues and
  DOIs come from Crossref or Semantic Scholar records. Each entry is tagged with how deeply it was
  read:
  - **[full]**: I extracted the PDF text with `pdftotext` and read the method and evaluation
    sections. Papers read this way: DANA, WordRev, Subramanyan DATE'13, Gascón FMCAD'14, RELIC,
    ReIGNN, Klix CCS'24, Wallat IVSW'17, the Azriel survey and the 2026 SoK.
  - **[abstract]**: I read only the abstract or the publisher/arXiv landing page.
  - **[secondary]**: I know only the title, plus how a survey I did read describes the paper.
    Treat claims about these as unverified.
- The TCHES DOIs use the current `10.46586` prefix (Crossref). The DANA PDF header still prints
  the older `10.13154` prefix.
- I found no paper whose title or abstract is about recognising CRC units in netlists. That is a
  negative search result, not proof that none exists.

## 1. One-screen summary

| Theme | Key prior art | What we borrow |
|---|---|---|
| Bitslice aggregation, word identification | Subramanyan et al. DATE'13 / TETC'14; WordRev (HOST'13) | cut enumeration + NPN (permutation-independent) matching of 6-input cuts; grouping by common select signal and by propagated (chain) signal; word propagation |
| Counters, shift registers by topology + SAT | Subramanyan et al. DATE'13 | first guess the candidate from its topology, then confirm it with SAT; aggregate by length and by identical set/reset/enable functions |
| Register grouping (dataflow) | DANA (TCHES'20); Klix et al. (CCS'24); Tashjian and Davoodi (DAC'15) | multiple passes (control signals, shared predecessor/successor register groups), majority voting iterated to a fixed point, no thresholds; NMI + purity against a ground truth built from names |
| Functional matching with unknown I/O mapping | WordRev QBF; Gascón et al. FMCAD'14 (PICEC, ∃∀ SMT); Klix et al. (SMT); Soeken et al. FMCAD'15 | encode "exists a permutation/control setting such that for all inputs the slice equals the template"; prune with signatures (LSB influences many outputs, MSB few) |
| Bit order | Klix et al. CCS'24 (HAL bitorder propagation) | take anchors (carry chains, shift registers, known I/O) and propagate by consensus; score as % ordered and % correct |
| LFSRs | Wallat et al. IVSW'17; SPHINX (GLSVLSI'26); HAWKEYE (CRYPTO'24) | a flop chain plus a DFS for feedback cycles gives the taps and hence the polynomial; structural features locate LFSR-like logic |
| Control registers and FSMs | Shi et al. '10; RELIC '16; REFSM '16; fastRELIC '19; RELIC-FUN '20; FSMx-Ultra '23; ReIGNN '21 | SCC and feedback detection; fan-in similarity; control/datapath separation (a useful negative class for us) |
| Learned sub-circuit identification | GNN-RE (TCAD'22); ABGNN (ICCAD'21, TCAD'23); Gamora (DAC'23); ReBERT (DATE'25) | node features and evaluation protocols; they cover combinational operators, and none of the GNN-RE classes is a counter or shift register |
| Frameworks | HAL (TDSC'19, CF'19, arXiv'25): DANA, module identification, bitorder propagation, HAWKEYE plugins | reference implementation to compare against |
| Surveys and evaluation critique | Azriel et al. JCEN'21; Karadağ et al. SoK TCHES'26; Meade et al. JHSS'18 | NMI as the standard partition metric; avoid "magic" parameters; the field's reproducibility problem (4 % of 187 papers reproducible) |

## 2. Works, grouped by theme

### 2.1 Foundations and surveys

1. **Hansen, M.C.; Yalcin, H.; Hayes, J.P.** "Unveiling the ISCAS-85 benchmarks: a case study in
   reverse engineering." *IEEE Design & Test of Computers*, 1999. DOI 10.1109/54.785838.
   [secondary: WordRev, DATE'13, DANA and the survey describe it]
   - *What:* the high-level function of the ISCAS-85 combinational circuits, recovered by hand.
   - *Method:* manual strategies: look for common library components and repeated structures,
     compute truth tables of small blocks, find buses and control signals.
   - *Evaluation:* case study.
   - *Relevance:* the origin of the "replicated bitslice" and "common control signal" ideas that
     later automated work formalises. Nothing here to claim.

2. **Chisholm, G.H.; Eckmann, S.T.; Lain, C.M.; Veroff, R.L.** "Understanding integrated
   circuits." *IEEE Design & Test of Computers*, 1999. DOI 10.1109/54.765201. Also **Doom, T.;
   White, J.; Wojcik, A.; Chisholm, G.** "Identifying high-level components in combinational
   circuits." *GLSVLSI*, 1998. DOI 10.1109/GLSV.1998.665284. [secondary: the SoK]
   - *What:* early component identification.
   - *Method:* subgraph isomorphism, BDD matching, and evaluation on all-zero / one-hot inputs to
     recover the I/O mapping.
   - *Relevance:* probing with one-hot inputs to fix the bit order is 1990s prior art.

3. **Ohlrich, M.; Ebeling, C.; Ginting, E.; Sather, L.** "SubGemini: identifying subcircuits
   using a fast subgraph isomorphism algorithm." *DAC*, 1993. DOI 10.1145/157485.164556.
   [secondary]
   - *What:* exact structural sub-circuit matching (transistor or gate level).
   - *Relevance:* baseline for pure structural matching; fragile under technology mapping.

4. **Azriel, L.; Speith, J.; Albartus, N.; Ginosar, R.; Mendelson, A.; Paar, C.** "A survey of
   algorithmic methods in IC reverse engineering." *Journal of Cryptographic Engineering*
   11(3):299–315, 2021. DOI 10.1007/s13389-021-00268-5. [full, sections 3–6]
   - *What:* a taxonomy of partitioning, structural analysis, functional analysis, FSM extraction,
     SAT, ML, word-level identification and dataflow.
   - *Evaluation critique:* ISCAS-85 is outdated, there are no common benchmarks, and it
     recommends NMI following Meade et al. 2018.
   - *Relevance:* it summarises the counter test as "every consecutive node depends on the
     lower-order ones, verified with SAT; shift registers similarly". So counter and
     shift-register detection by topology + SAT is established.

5. **Karadağ, Z.; Klix, S.; Walendy, R.; Hahn, F.; Dorschel, K.; Speith, J.; Paar, C.; Becker,
   S.** "SoK: From Silicon to Netlist and Beyond – Two Decades of Hardware Reverse Engineering
   Research." *IACR TCHES* 2026(4):116–155. DOI 10.46586/tches.v2026.i4.116-155 (arXiv
   2603.17883). [full, netlist section 3.3 and the evaluation section]
   - *What:* covers 187 papers. It splits netlist reverse engineering into four steps:
     partitioning, module identification, algorithmic recovery and sensemaking.
   - *What it says about our first slice:*
     - Word grouping by shared control signals and by shared predecessor/successor register
       groups is a known family.
     - Detecting LFSRs and counters by their flip-flop structure is listed as a known
       domain-specific method (it cites Subramanyan '13/'14 and Wallat '17).
     - Recovering I/O order from "LSB influences many outputs" is common.
     - Confirming with SAT, SMT, QBF or BDDs is common.
   - *Evaluation findings:* key results could be reproduced for only 7 of the 187 papers (4 %).
     Almost all methods assume error-free netlists; some assume a perfect partition or a known I/O
     mapping; hand-tuned thresholds are common. Its proposals: benchmarks from open-source designs
     (IC images paired with GDSII and netlists, with ground truth), multiple metrics, realistic
     and erroneous netlists, varied synthesis settings.
   - *Relevance:* the most direct statement of the evaluation gap S3 can speak to (section 4).

6. **Fyrbiak, M.; Strauss, S.; Kison, C.; Wallat, S.; Elson, M.; Rummel, N.; Paar, C.** "Hardware
   reverse engineering: Overview and open challenges." *IVSW*, 2017. DOI 10.1109/IVSW.2017.8031550.
   **Keshavarz, S.; Yu, C.; Ghandali, S.; Xu, X.; Holcomb, D.** "Survey on Applications of Formal
   Methods in Reverse Engineering and Intellectual Property Protection." *J. Hardware and Systems
   Security*, 2018. DOI 10.1007/s41635-018-0044-3. [secondary]
   - *Relevance:* background only.

### 2.2 Word identification and bitslice aggregation

7. **Subramanyan, P.; Tsiskaridze, N.; Pasricha, K.; Reisman, D.; Susnea, A.; Malik, S.**
   "Reverse Engineering Digital Circuits Using Functional Analysis." *DATE*, 2013. DOI
   10.7873/DATE.2013.264. [full]
   - *What:* multibit multiplexers, decoders, adders/subtracters, parity trees, comparators,
     register files and RAMs, **counters and shift registers**.
   - *Method:*
     - Enumerate 6-feasible cuts; classify them with permutation-independent Boolean matching
       into "bitslices".
     - Aggregate the bitslices (a) by a common input signal, such as a mux select, and (b) by a
       propagated signal, such as a carry chain or parity tree. The inputs and outputs of an
       aggregate become "words", and words are propagated across structurally identical gates.
     - Build candidate modules between words and match them against a component library with
       BDD-based permutation/phase-independent matching.
     - **Counters:** find sets of latches whose latch-to-latch flow matches the counter topology
       (bit *i* is driven by all lower bits). A SAT check then confirms that (i) each bit toggles
       exactly when all lower bits are 1 (up counter) or all are 0 (down counter), and (ii) the
       enable and reset conditions are the same for every bit.
     - **Shift registers:** find cascading latch chains, verify them with SAT, group the chains by
       length, and merge chains with the same set, reset and shift-enable functions into one
       multibit shift register.
   - *Evaluation:*
     - 8 OpenCores netlists synthesised by the authors (router, eVoter, Open8, cpu8080, ae18,
       mips16, oc8051, RISC FPU; up to 14,291 gates and 3,097 latches).
     - The metric is **coverage**: the % of gates whose function is determined, 51–93 %.
     - Also reported are counts of found components, e.g. 5 counters in oc8051 and 7 shift
       registers in the RISC FPU.
     - No precision or recall against an RTL ground truth.
   - *Relevance:* **this is the closest prior art to our first slice.** Topology + SAT for
     counters and shift registers, and grouping by identical set/reset/enable functions, are
     theirs, so we must not claim either. Its counter test covers only binary up/down counters.

8. **Subramanyan, P.; Tsiskaridze, N.; Li, W.; Gascón, A.; Tan, W.Y.; Tiwari, A.; Shankar, N.;
   Seshia, S.A.; Malik, S.** "Reverse Engineering Digital Circuits Using Structural and
   Functional Analyses." *IEEE Trans. Emerging Topics in Computing*, 2014. DOI
   10.1109/TETC.2013.2294918. [abstract]
   - *What:* the journal version of the above.
   - *Evaluation:* coverage >45 % and up to 93 % of gates; an SoC with >375,000 combinational
     elements gets 68 % coverage. It also shows the results helping an analyst find Trojans.
   - *Relevance:* as above; also the scale reference.

9. **Li, W.; Gascón, A.; Subramanyan, P.; Tan, W.Y.; Tiwari, A.; Malik, S.; Shankar, N.;
   Seshia, S.A.** "WordRev: Finding word-level structures in a sea of bit-level gates." *IEEE
   HOST*, 2013, pp. 67–74. DOI 10.1109/HST.2013.6581568. [full]
   - *What:* candidate words, propagated words, a word-level dataflow graph, and word operations
     (add, subtract, Boolean ops, shift and rotate).
   - *Method:*
     - (1) Candidate words come from **shape hashing** (a hash of each wire's k-bounded
       backward-reachable DAG, k ∈ {2,3,4}, refined by gate distance) and from bitslice
       aggregation as in [7].
     - (2) **Word propagation** by guess-and-check: guess target words one gate level away with
       structural heuristics, then check with symbolic D-calculus evaluation, enumerating
       assignments to up to 3 nearby "control" wires taken from the intersection of the fan-ins.
     - (3) Word operations are checked as **2QBF**: there exist side-input values such that, for
       all word inputs, the slice equals the reference; DepQBF is the solver.
     - It *assumes the bit order is known* for the QBF check.
   - *Evaluation:*
     - OpenCores designs plus a 375k-cell "BigSoC" (IBM 45 nm SOI, Synopsys DC).
     - Reported: counts of candidate and propagated words, runtime (1–330 min), and a case study
       on a CMP router across two cell libraries and two optimisation settings (54, 52 and 50
       words found).
     - QBF runtimes for 7 ALU operations on an oc8051 slice (435 gates, 87 side inputs).
     - The word graph is judged qualitatively; there are no precision/recall numbers.
   - *Relevance:* our "shared enable" idea is a special case of their control-wire propagation.
     The cross-library / cross-optimisation robustness check is good practice to copy.

10. **Li, W.; Wasson, Z.; Seshia, S.A.** "Reverse engineering circuits using behavioral pattern
    mining." *IEEE HOST*, 2012. DOI 10.1109/HST.2012.6224325. Also **Li, W.** "Formal Methods for
    Reverse Engineering Gate-Level Netlists." Technical report (UC Berkeley PhD thesis), 2013. DOI
    10.21236/ADA623698. [secondary: survey and WordRev]
    - *What:* matching sub-circuits against a library of behavioural specifications.
    - *Method:* mine temporal patterns from simulation traces; match I/O correspondence through a
      maximum common subgraph; confirm with model checking.
    - *Relevance:* resolving the I/O mapping from simulation behaviour is prior art.

11. **Tashjian, E.; Davoodi, A.** "On using control signals for word-level identification in a
    gate-level netlist." *DAC*, 2015. DOI 10.1145/2744769.2744878. [abstract via search
    snippets; Semantic Scholar has no abstract]
    - *What:* groups of wires that form words.
    - *Method:* find and use a small subset of relevant control signals, including the many
      inserted by CAD tools, and exploit partial structural similarity.
    - *Evaluation:* not read. DANA and ReBERT use it as a baseline.
    - *Relevance:* **word grouping by shared control signals is Tashjian and Davoodi's idea**
      (with DANA and Chisholm'99), not ours.

12. **Meade, T.; Shamsi, K.; Le, T.; Di, J.; Zhang, S.; Jin, Y.** "The Old Frontier of Reverse
    Engineering: Netlist Partitioning." *J. Hardware and Systems Security* 2(3):201–213, 2018.
    DOI 10.1007/s41635-018-0043-4. [secondary: DANA, survey, SoK]
    - *What:* netlist partitioning into words.
    - *Method:* fan-in cut similarity; PCA embedding so that bits of one word land close together.
    - *Evaluation:* argues that netlist reverse engineering lacks proper evaluation and proposes
      **Normalized Mutual Information (NMI)** against a golden partition.
    - *Relevance:* the source of the NMI convention.

13. **Zhang, L.; Davoodi, A.; Topaloglu, R.O.** "ReBERT: LLM for Gate-Level to Word-Level Reverse
    Engineering." *DATE*, 2025. DOI 10.23919/DATE64628.2025.10993097. [abstract]
    - *What:* grouping bits into words.
    - *Method:* a BERT model fine-tuned on fan-in-cone sequences, with a tree embedding.
    - *Evaluation:* against a partial-structural-matching baseline; average improvements of
      12.2–218.1 % depending on how much the structural patterns are corrupted.
    - *Relevance:* the learned word-grouping state of the art. It needs training data, which
      TEMPO could supply, but that is not our first slice.

14. **McKendrick, R.; Simpson, C.; Nelson, B.; Goeders, J.** "Leveraging FPGA Primitives to
    Improve Word Reconstruction during Netlist Reverse Engineering." *ICFPT*, 2022. DOI
    10.1109/ICFPT56656.2022.9974401. [abstract]
    - *Method:* hard blocks (carry chains, BRAMs, DSP multipliers) serve as word anchors.
    - *Evaluation:* VTR benchmarks on Xilinx 7-series, compared with DANA.
    - *Relevance:* anchors improve grouping. The ASIC analogues are adder carry structure, shift
      chains and macro ports; in TEMPO that includes the SRAM macro's 32-bit data and 10-bit
      address pins.

15. **Nathamuni-Venkatesan, A.; Narayanan, R.-V.; Pula, K.; Muthukumaran, S.; Vemuri, R.**
    "Word-Level Structure Identification In FPGA Designs Using Cell Proximity Information."
    *VLSID*, 2023. DOI 10.1109/VLSID57277.2023.00083 (arXiv 2303.07405). [abstract]
    - *Method:* group elements by their placed location after place and route (Xilinx 7-series,
      Zynq).
    - *Evaluation:* average **NMI 0.73** over all element types against ground-truth groupings.
    - *Relevance:* **placement as a grouping cue is published for FPGAs.** We have ASIC
      placement for free from GDS and DEF, but should present it as an application of this idea,
      not a new one.

16. **Narayanan, R.V.; Nathamuni Venkatesan, A.; Pula, K.; Muthukumaran, S.; Vemuri, R.** "Reverse
    Engineering Word-Level Models from Look-Up Table Netlists." *ISQED*, 2023. DOI
    10.1109/ISQED57927.2023.10129373 (arXiv 2303.02762). [abstract]
    - *What:* word-level operations and sequential modules in LUT netlists.
    - *Method:* carry-chain analysis plus adapted ASIC techniques.
    - *Evaluation:* 34–100 % of elements inferred as parts of identified operations or modules.
    - *Relevance:* the FPGA counterpart.

### 2.3 Register grouping and dataflow

17. **Albartus, N.; Hoffmann, M.; Temme, S.; Azriel, L.; Paar, C.** "DANA Universal Dataflow
    Analysis for Gate-Level Netlist Reverse Engineering." *IACR TCHES* 2020(4):309–336. DOI
    10.46586/tches.v2020.i4.309-336. [full]
    - *What:* multi-bit registers (groups of flip-flops) and the dataflow between them.
    - *Method:*
      - Abstract the netlist to a flip-flop graph by tracing each flip-flop's output to the next
        flip-flops.
      - Start with every flip-flop in its own group. Apply every ordered pair of passes; the
        passes use control signals (clk, enable, set, reset pins) and shared successor or
        predecessor groups (register stages).
      - A specialised majority vote favours groupings that leave few flip-flops isolated.
      - Iterate until the grouping repeats. There are no thresholds; an optional "steered mode"
        takes expected register widths.
    - *Evaluation:*
      - 9 open designs (AES, DES, PRESENT, RSA, SHA-3, edge MIPS, ibex, open8, OpenTitan),
        synthesised for ASIC (Synopsys DC, LSI10k, gated clock tree) and FPGA (Vivado).
      - **Ground truth:** flip-flops grouped automatically by the human-readable names the
        synthesiser kept.
      - **Metrics: NMI and purity.** Most designs score NMI > 0.90. DES scores 0.84 / 0.48 because
        the key and both state halves merge into one 120-bit group; the SHA-3 (Synopsys) run
        scores NMI 0.67 with purity 1.00 because one register is split into chains.
      - Runtime from 0.1 s to 201 s; OpenTitan has 22k flip-flops.
      - Netlists and code are public (github.com/emsec/hal-benchmarks).
    - *Relevance:* **the reference method and the evaluation protocol for our word grouping.** Two
      lessons from its own discussion: NMI and purity can mislead in opposite directions, and a
      design where every flip-flop shares clock and control defeats the control pass.

18. **Klix, S.; Albartus, N.; Speith, J.; Staat, P.; Verstege, A.; Wilde, A.; Lammers, D.;
    Langheinrich, J.; Kison, C.; Sester-Wehle, S.; Holcomb, D.; Paar, C.** "Stealing Maggie's
    Secrets – On the Challenges of IP Theft Through FPGA Reverse Engineering." *ACM CCS*, 2024.
    DOI 10.1145/3658644.3690235 (arXiv 2312.06195). [full, sections 4.2–4.4]
    - *What:* arithmetic operations (add, subtract, constant multiply, counters, comparisons),
      word-level multiplexers, registers, and **bit order**.
    - *Method:*
      - Structural candidates come from carry chains, extended by varying sets of neighbouring
        gates. Boolean functions are derived for the candidate outputs.
      - Several functional candidates are generated (operand membership, control inputs, bit
        order). Orderings are pruned with influence counts: the LSB of an adder influences all
        outputs, the MSB one.
      - Each candidate is checked against a library of models with SMT.
      - DANA is extended to arbitrary gate types and to take known groups.
      - Bit order is propagated from anchors (DSPs, BRAMs, arithmetic operands) along the
        datapath, with consensus over the candidate indices.
    - *Evaluation:*
      - 6 benchmarks for Xilinx and Lattice iCE40, plus a real iPhone 7 FPGA (black box, no
        ground truth).
      - Function verified for 94 % of carry chains; 1–91 % (average 32 %) of combinational gates
        verified as arithmetic.
      - DANA refinement raises NMI by up to 0.14 and purity by up to 0.30.
      - Bit order: an average of **86 % of bit orders reconstructed, 97 % of them correct**.
        Bit-order ground truth exists only for registers, taken from synthesiser labels and
        restricted to registers wider than 3 flip-flops.
      - It notes that word-level MUXes have no ground truth.
    - *Relevance:* **SMT-verified operations with recovered bit order are published (for FPGA,
      anchored on carry primitives).** ASIC standard-cell netlists have no carry primitive, so
      candidate generation differs, but the verification idea is theirs. It also shows how to
      score bit order.

19. **Werner, M.; Lippmann, B.; Baehr, J.; Gräb, H.** "Reverse Engineering of Cryptographic
    Cores by Structural Interpretation Through Graph Analysis." *IVSW*, 2018. DOI
    10.1109/IVSW.2018.8494896. [abstract + survey]
    - *Method:* Louvain modularity clustering with edge weights by signal type (clock, reset,
      enable, select, other), distance and betweenness; the γ parameter is tuned per case.
    - *Evaluation:* real-world netlists including crypto cores.
    - *Relevance:* signal-type-weighted clustering, for core-level partitioning.

20. **Couch, J.; Reilly, E.; Schuyler, M.; Barrett, B.** "Functional block identification in
    circuit design recovery." *IEEE HOST*, 2016. DOI 10.1109/HST.2016.7495560. [secondary]
    - *Method:* NCut-style graph partitioning without functional information.
    - *Relevance:* core-level partitioning baseline.

21. **Fyrbiak, M.; Wallat, S.; Reinhard, S.; Bissantz, N.; Paar, C.** "Graph Similarity and its
    Applications to Hardware Security." *IEEE Trans. Computers* 69(4):505–519, 2020. DOI
    10.1109/TC.2019.2953752. [secondary]
    - *Method:* register stages found from control signals; graph edit distance, neighbour
      matching and spectral similarity against a library.
    - *Relevance:* structural similarity scoring.

22. **Hong, X.; Lin, T.; Shi, Y.; Gwee, B.H.** "GraphClusNet: A Hierarchical Graph Neural Network
    for Recovered Circuit Netlist Partitioning." *IEEE Trans. Artificial Intelligence* 4(5),
    2023. DOI 10.1109/TAI.2022.3198930. [secondary: the SoK says it uses placement information]
    - *Relevance:* placement-aware partitioning of *recovered* netlists is published.

### 2.4 Functional matching with unknown I/O mapping (SAT / QBF / SMT)

23. **Gascón, A.; Subramanyan, P.; Dutertre, B.; Tiwari, A.; Jovanović, D.; Malik, S.**
    "Template-based circuit understanding." *FMCAD*, 2014, pp. 83–90. DOI
    10.1109/FMCAD.2014.6987599. [full]
    - *What:* word-level descriptions of combinational slices from templates: adders,
      subtracters, shifters, multipliers, **counters**. One benchmark is a 22-bit up counter
      modulo (2^20 + 2^21) with synchronous reset and hold, obtained by unfolding an FSM.
    - *Method:* **Permutation-Independent Conditional Equivalence Checking (PICEC)**. It
      synthesises input/output permutations *and* control-signal conditions as an ∃∀ bit-vector
      formula, solved with a modified Yices (plus Z3 and QBF solvers). Distinguishing signatures
      (input/output dependency counts) prune the permutations. Permutations are encoded with
      quadratically many Boolean variables.
    - *Evaluation:*
      - 40 instances (half match, half do not) from ISCAS-85, an academic ALU and synthetic
        circuits (Synopsys DC); one-hour timeout.
      - Yices with positive branching solves 37 of 40; the QBF solvers solve at most 3.
      - Signatures speed up most instances.
    - *Relevance:* **synthesising the bit order and control conditions inside a formal match is
      published.** It also shows that full permutation search is expensive; fixing the order
      structurally first and then running one equivalence check is the cheaper route.

24. **Soeken, M.; Sterin, B.; Drechsler, R.; Brayton, R.** "Simulation graphs for reverse
    engineering." *FMCAD*, 2015. DOI 10.1109/FMCAD.2015.7542265. [secondary]
    - *Method:* behavioural signatures from simulation that identify a module and its I/O
      mapping at the same time.
    - *Relevance:* simulation-first candidate filtering before SAT.

25. **Diao, Y.; Wei, X.; Lam, T.-K.; Wu, Y.-L.** "Coupling reverse engineering and SAT to tackle
    NP-complete arithmetic circuitry verification in ∼O(# of gates)." *ASP-DAC*, 2016. DOI
    10.1109/ASPDAC.2016.7428002. [secondary]
    - *Method:* recognise arithmetic structure, rewrite it into a canonical form, then use SAT.
    - *Relevance:* for adders and multipliers later, not the first slice.

26. **Yu, C.; Holcomb, D.; Ciesielski, M.** "Reverse engineering of irreducible polynomials in
    GF(2^m) arithmetic." *DATE*, 2017. DOI 10.23919/DATE.2017.7927238. [abstract]
    - *Method:* computer-algebra extraction of each output's polynomial; this recovers the
      irreducible polynomial P(x) of a GF(2^m) multiplier from its gates.
    - *Relevance:* **recovering a polynomial algebraically from gates is published for GF
      multipliers.** LFSR and CRC polynomial recovery is the same algebra on the sequential
      side.

27. **Ho, K.-W.; Chung, S.-T.; Chen, T.-F.; Fan, Y.-W.; Cheng, C.; Liu, C.-H.; Jiang, J.-H.R.**
    "WolFEx: Word-Level Function Extraction and Simplification from Gate-Level Arithmetic
    Circuits." *ICCAD*, 2023. DOI 10.1109/ICCAD57390.2023.10323906. [secondary: the SoK says it
    uses polynomial rewriting, linear coefficient fitting and symbolic regression, and uses
    LSB/MSB influence for the I/O mapping]
    - *Relevance:* combinational arithmetic, later slices.

28. **Le, T.; Di, J.** "Golden reference matching for gate-level netlist functionality
    identification." *MWSCAS*, 2017. DOI 10.1109/MWSCAS.2017.8052986. [metadata only]

### 2.5 Sequential structures: counters, shift registers, LFSRs, CRCs

- **Counters and shift registers:** Subramanyan DATE'13 [7] is the main reference, with the
  topology + SAT test and grouping by the same set/reset/enable. Gascón FMCAD'14 [23] matches a
  *modulo* counter with synchronous reset and hold through a template. Klix CCS'24 [18] verifies
  counters as `A ± n` with SMT, from carry-chain candidates on FPGAs.

29. **Wallat, S.; Fyrbiak, M.; Schlögel, M.; Paar, C.** "A look at the dark side of hardware
    reverse engineering – a case study." *IVSW*, 2017. DOI 10.1109/IVSW.2017.8031551 (arXiv
    1910.01519). [full, sections III and V]
    - *What:* **LFSRs**, their taps and feedback polynomial. It then finds LFSR-based constant
      generators used as watermark opaque predicates, and locates LFSRs in A5/1 to insert a
      Trojan.
    - *Method:* find flip-flop chains, skipping pass-through LUTs and buffers. The start flop is
      one whose predecessor is a flop; a modified DFS then looks for cycles through the taps. The
      polynomial follows from the start flop and the tap positions.
    - *Evaluation:* FPGA case studies (an AES IP core on a Spartan-6; A5/1). No metrics.
    - *Relevance:* **structural LFSR detection with polynomial read-out is published.** It is
      purely structural: it does not prove linearity and handles only simple (XOR, Fibonacci)
      forms.

30. **Hossain, T.; Ahsan, S.M.M.; Hoque, T.** "SPHINX: A Framework for Security Primitive
    Hardware Identification and Extraction." *GLSVLSI*, 2026. DOI 10.1145/3787109.3815307.
    [abstract]
    - *What:* locating design-for-security primitives, including **LFSRs** (also PUFs, PRNGs and
      obfuscated scan chains).
    - *Method:* 53 structural features per cell plus unsupervised clustering.
    - *Evaluation:* 5 classes, 35 benchmark configurations, mean **F1 > 0.95**.
    - *Relevance:* current LFSR localisation baseline; it uses per-class F1 as its metric.

31. **Leander, G.; Paar, C.; Speith, J.; Stennes, L.** "HAWKEYE – Recovering Symmetric
    Cryptography From Hardware Circuits." *CRYPTO*, 2024 (LNCS 14923, pp. 340–376). DOI
    10.1007/978-3-031-68385-5_11. [abstract]
    - *What:* locating symmetric-crypto implementations (SPN, ARX, Feistel, **LFSR-based**
      ciphers) by finding highly local computation.
    - *Evaluation:* FPGA and ASIC; a 424,341-gate netlist in 44.3 s. Available as a HAL plugin.
    - *Relevance:* localisation of LFSR-based logic at scale.

- **CRCs:** no netlist reverse-engineering paper found (see section 0).

**Yosys passes (tools, not papers).** I checked these locally with oss-cad-suite Yosys 0.69:
- `shregmap` maps DFF chains to shift-register cells. It converted a 6-deep chain in a small test
  only when the intermediate taps had no other fanout (no enables unless `-enpol` is given).
- `extract_counter` is described as converting "non-resettable or async resettable counters" to
  counter cells. In a small test (an 8-bit async-reset down counter) it extracted nothing, either
  after coarse synthesis (`$alu`) or at gate level. I did not investigate why, so the only
  conclusion is that it is not usable as-is here.
- `extract_fa` extracts full and half adders from gate-level logic. `extract -mine` mines
  frequent subcircuits. Both are relevant to the adder and comparator slices later.

### 2.6 Control registers and FSM extraction (the negative class for datapath words)

32. **Shi, Y.; Ting, C.W.; Gwee, B.-H.; Ren, Y.** "A highly efficient method for extracting FSMs
    from flattened gate-level netlist." *ISCAS*, 2010. DOI 10.1109/ISCAS.2010.5537093.
    [secondary: survey]
    - *Method:* state registers sit on combinational feedback (SCCs), filtered to registers that
      control datapath elements. Registers are grouped by the same enable signal and by shared
      gates on the feedback path.
    - *Evaluation:* DW8051, where 36 candidate FSMs were found.
    - *Relevance:* SCCs also catch counters, which the survey flags as a false-positive source.
      For us that is a feature.

33. **Meade, T.; Jin, Y.; Tehranipoor, M.; Zhang, S.** "Gate-level netlist reverse engineering
    for hardware security: Control logic register identification" (RELIC). *ISCAS*, 2016, pp.
    1334–1337. DOI 10.1109/ISCAS.2016.7527495. [full]
    - *What:* separates control (state) registers from data registers.
    - *Method:* simplify the logic to AND/OR/INV and colour the nodes. A recursive, memoised
      fan-in similarity score uses bipartite maximum matching of children, with a depth limit
      and thresholds. Registers with many similar partners are classed as data.
    - *Evaluation:* MC8051, RS232, RSA, AES-128 and others. Accuracy 79.6–100 % at 100 %
      sensitivity; parameters were tuned per design.
    - *Relevance:* "bits of one word have similar fan-in" underlies word grouping too. Its
      reliance on parameters is the "magic values" that DANA and the SoK criticise.

34. **Meade, T.; Zhang, S.; Jin, Y.** "Netlist reverse engineering for high-level functionality
    reconstruction" (REFSM). *ASP-DAC*, 2016, pp. 655–660. DOI 10.1109/ASPDAC.2016.7428086.
    [abstract only]
    - *What:* recovers the FSM behind the control logic from a flattened netlist, for Trojan
      detection. REFSM is part of the NETA toolset (with RELIC and others). Also **Meade, T.;
      Zhang, S.; Jin, Y.; Zhao, Z.; Pan, D.** "Gate-Level Netlist Reverse Engineering Tool Set for
      Functionality Recovery and Malicious Logic Detection." *ISTFA*, 2016. DOI
      10.31399/asm.cp.istfa2016p0342. [metadata]

35. **Brunner, M.; Baehr, J.; Sigl, G.** "Improving on State Register Identification in
    Sequential Hardware Reverse Engineering" (fastRELIC). *IEEE HOST*, 2019. DOI
    10.1109/HST.2019.8740844. [abstract + survey]
    - *What:* up to 100× faster than RELIC; designs up to 4,000 registers and 50,000 gates.
    - *Evaluation:* the survey reports accuracy of 23.53–100 %.

36. **Geist, J.; Meade, T.; Zhang, S.; Jin, Y.** "RELIC-FUN: Logic Identification through
    Functional Signal Comparisons." *DAC*, 2020. DOI 10.1109/DAC18072.2020.9218616. [abstract]
    - *Method:* netlist slicing plus *functional* comparison, which holds up better than
      topology after resynthesis.
    - *Relevance:* supports comparing cone functions rather than cone shapes.

37. **Fyrbiak, M.; Wallat, S.; Déchelotte, J.; Albartus, N.; Böcker, S.; Tessier, R.; Paar, C.**
    "On the Difficulty of FSM-based Hardware Obfuscation." *IACR TCHES* 2018(3):293–330. DOI
    10.46586/tches.v2018.i3.293-330. **Kibria, R.; Farahmandi, F.; Tehranipoor, M.**
    "FSMx-Ultra: Finite State Machine Extraction From Gate-Level Netlist for Security
    Assessment." *IEEE TCAD*, 2023. DOI 10.1109/TCAD.2023.3266368 [abstract: graph-theoretic
    state-FF detection plus ATPG-based state transition graphs; recovers all FSMs in 14
    open-source benchmarks]. **Brunner, M.; Hepp, A.; Baehr, J.; Sigl, G.** "Toward a
    Human-Readable State Machine Extraction." *ACM TODAES*, 2022. DOI 10.1145/3513086.
    [secondary]

38. **Dutta Chowdhury, S.; Yang, K.; Nuzzo, P.** "ReIGNN: State Register Identification Using
    Graph Neural Networks for Circuit Reverse Engineering." *ICCAD*, 2021. DOI
    10.1109/ICCAD51958.2021.9643498 (arXiv 2112.00806). [full, evaluation section]
    - *Method:* 3-layer GraphSAGE node classification of registers; structural post-processing
      through SCCs.
    - *Evaluation:*
      - 10 designs (OpenCores, secworks, RISC-V blocks; Nangate 45 nm), each synthesised under
        4 constraint sets, with one-hot and binary FSM encodings.
      - **Labels from the RTL.** Leave-one-design-out cross-validation: all 4 variants of a
        design form the test set.
      - Balanced accuracy 96.5 %, sensitivity 97.7 %.
    - *Relevance:* a good protocol for learned methods: hold out a whole design, and vary
      synthesis to test robustness.

39. **Pan, W.; Dong, M.; Qiu, Z.; Yang, J.; Di, Z.; Gao, Y.** "RELIC-GNN: Efficient State
    Registers Identification with Graph Neural Network for Reverse Engineering." arXiv
    2512.15037, 2025. [abstract]
    - *Evaluation:* recall 100 %, precision 30.49 %, accuracy 88.37 %.
    - *Relevance:* a reminder to report precision, not only recall.

### 2.7 Learned sub-circuit identification (GNN and deep learning)

40. **Alrahis, L.; Sengupta, A.; Knechtel, J.; Patnaik, S.; Saleh, H.; Mohammad, B.;
    Al-Qutayri, M.; Sinanoglu, O.** "GNN-RE: Graph Neural Networks for Reverse Engineering of
    Gate-Level Netlists." *IEEE TCAD* 41(8):2435–2448, 2022. DOI 10.1109/TCAD.2021.3110807.
    [abstract + dataset README]
    - *What:* classifies each gate into a sub-circuit class; the classes are **adders,
      multipliers, subtractors, comparators, control logic**, with no sequential classes.
    - *Method:* GNN node classification with structural and functional neighbourhood features.
    - *Evaluation:*
      - A custom dataset (GF 65 nm LPe, Synopsys DC; 37 interconnected-module designs, RTL
        released), plus EPFL, ISCAS-85 and 74X-series benchmarks.
      - 98.82 % average accuracy mapping gates to modules.
    - *Relevance:* comparator and adder labels for later slices. It does not cover counters,
      shift registers or LFSRs.

41. **He, Z.; Wang, Z.; Bai, C.; Yang, H.; Yu, B.** "Graph Learning-Based Arithmetic Block
    Identification." *ICCAD*, 2021. DOI 10.1109/ICCAD51958.2021.9643581. **Wang, Z.; He, Z.;
    Bai, C.; Yang, H.; Yu, B.** "Efficient Arithmetic Block Identification With Graph Learning
    and Network-Flow." *IEEE TCAD*, 2023. DOI 10.1109/TCAD.2022.3227815. [abstract]
    - *Method:* an asynchronous bidirectional GNN (ABGNN) on DAGs.
    - *Evaluation:* open-source RISC-V CPUs.

42. **Wu, N.; Li, Y.; Hao, C.; Dai, S.; Yu, C.; Xie, Y.** "Gamora: Graph Learning based Symbolic
    Reasoning for Large-Scale Boolean Networks." *DAC*, 2023. DOI 10.1109/DAC56929.2023.10247828
    (arXiv 2303.08256). [abstract]
    - *What:* XOR/MAJ adder-tree reasoning in multipliers; scales to 33M nodes.
    - *Evaluation:* about 100 % (CSA) and >97 % (Booth) accuracy against ABC's exact reasoning;
      >92 % after technology mapping.

43. **Dai, Y.-Y.; Brayton, R.K.** "Circuit recognition with deep learning." *IEEE HOST*, 2017.
    DOI 10.1109/HST.2017.7951826. **Baehr, J.; Bernardini, A.; Sigl, G.; Schlichtmann, U.**
    "Machine learning and structural characteristics for reverse engineering." *ASP-DAC*, 2019.
    DOI 10.1145/3287624.3288740. **Zhao, G.; Shamsi, K.** "Adversarial Circuit Rewriting against
    Graph Neural Network-based Operator Detection." *ACM TODAES*, 2025. DOI 10.1145/3703911.
    [secondary / title]
    - *Relevance:* learned detectors are fragile under adversarial rewriting. This is an argument
      for confirming every detection with SAT.

### 2.8 Frameworks and layout-to-netlist

44. **Fyrbiak, M.; Wallat, S.; Swierczynski, P.; Hoffmann, M.; Hoppach, S.; Wilhelm, M.;
    Weidlich, T.; Tessier, R.; Paar, C.** "HAL—The Missing Piece of the Puzzle for Hardware
    Reverse Engineering, Trojan Detection and Insertion." *IEEE TDSC*, 2019. DOI
    10.1109/TDSC.2018.2812183. **Wallat, S.; Albartus, N.; Becker, S.; Hoffmann, M.; Ender, M.;
    Fyrbiak, M.; Drees, A.; Maaßen, S.; Paar, C.** "Highway to HAL: Open-Sourcing the First
    Extendable Gate-Level Netlist Reverse Engineering Framework." *ACM Computing Frontiers*,
    2019. DOI 10.1145/3310273.3323419. **Speith, J.; Langheinrich, J.; Fyrbiak, M.; Hoffmann, M.;
    Wallat, S.; Klix, S.; Albartus, N.; Walendy, R.; Becker, S.; Paar, C.** "HAL – An
    Open-Source Framework for Gate-Level Netlist Analysis." arXiv 2512.14139, 2025. [abstract +
    wiki]
    - *What:* a C++/Python netlist framework (github.com/emsec/hal) with plugins: dataflow
      analysis (DANA), module identification (SMT-verified add, subtract, constant multiply,
      counters; from CCS'24), bitorder propagation (anchors, then consensus propagation; from
      CCS'24), HAWKEYE, simulation and graph exploration.
    - *Relevance:* the obvious external baseline. HAL reads gate libraries and Verilog, so
      running DANA on TEMPO's and the puzzle's extracted netlists should be possible. Not tried.

45. **Rajarathnam, R.S.; Lin, Y.; Jin, Y.; Pan, D.Z.** "ReGDS: A Reverse Engineering Framework
    from GDSII to Gate-level Netlist." *IEEE HOST*, 2020. DOI 10.1109/HOST45689.2020.9300272.
    [abstract]
    - *What:* GDSII plus the technology library give transistor connectivity, then
      relationship-based gate matching.
    - *Evaluation:* 100 % recovery from hundreds to millions of transistors; applied to locked
      circuits, then a SAT attack.
    - *Relevance:* **GDS-to-netlist is published.** RETRACE's extractor is not the novelty in
      S3; what S3 would add sits after the netlist.

### 2.9 Netlist abstraction for Trojan detection

No single "netlist abstraction for Trojan detection" paper stood out in the searches. The
abstraction line is the reverse-engineering work above, used to help analysts:
- Subramanyan TETC'14 [8] helps an analyst find Trojans.
- DANA [17] shows simple Trojans stand out in the register graph.
- REFSM and the ISTFA'16 toolset [34] target malicious control logic.
- WordRev [9] is motivated by localising the gates behind a misbehaving function.

Adjacent netlist-level detectors, which are not structure recovery:
- **Waksman, A.; Suozzo, M.; Sethumadhavan, S.** "FANCI: identification of stealthy malicious
  logic using Boolean functional analysis." *ACM CCS*, 2013. DOI 10.1145/2508859.2516654.
  [metadata]
- **Salmani, H.** "COTD: Reference-Free Hardware Trojan Detection and Recovery Based on
  Controllability and Observability in Gate-Level Netlist." *IEEE TIFS*, 2017. DOI
  10.1109/TIFS.2016.2613842. [metadata]
- **Yan, T.; Wang, J.; Cheng, Z.-H.** "Hardware Trojan Detection for Incomplete Gate-Level Reverse
  Netlist." *IEEE TDSC*, 2025. DOI 10.1109/TDSC.2025.3589244. [title only; relevant to extracted,
  possibly erroneous netlists]

## 3. Evaluation practice to copy

1. **Ground truth from names, joined to an anonymous netlist.** DANA, ReIGNN and Klix label
   flip-flops from synthesiser names or RTL. For S3:
   - Run the algorithm on the extracted netlist, whose names are `master_x_y` and generated
     nets.
   - Label from the sign-off netlist, whose flop Q nets keep register names, joined by instance
     position: TEMPO LVS check (a) already maps all 62,151 extracted instances to their DEF
     instances (`docs/TEMPO_LVS.md`).
   - Make the algorithm unable to see the names: the extracted netlist, not the sign-off one, is
     its input.
2. **Grouping metrics:** NMI and purity, as in DANA, Klix and the VLSID'23 paper. Report both,
   plus **exact-word recall** (fraction of RTL registers recovered exactly as one group) and
   **split/merge counts**. DANA's own DES and SHA-3 cases show that NMI and purity alone mislead.
   Report on flops in words of width ≥ 2, and separately on all flops.
3. **Classification metrics:** per-class precision, recall and F1 for shift register, counter,
   LFSR/CRC and none (SPHINX reports F1; ReIGNN balanced accuracy and sensitivity; RELIC-GNN shows
   why precision must be reported).
4. **Bit order:** % of recognised words with an order assigned, and % of those correct (Klix:
   86 % / 97 %). Counters and shift registers carry their own order, so this should be near
   100 % on those classes.
5. **Coverage:** % of flops, and of their next-state cones' gates, explained by a recognised
   structure (Subramanyan: 45–93 % of gates).
6. **No per-design tuning.** DANA and the SoK criticise thresholds and search depths. Fix any
   parameters once, on the puzzle or on synthetic designs, *before* scoring TEMPO, and say so.
7. **Robustness:** WordRev varied cell library and optimisation, ReIGNN used 4 constraint sets per
   design, and the SoK asks for varied synthesis and erroneous netlists. The round-trip flow
   (`tools/roundtrip`) can re-synthesise the recovered puzzle RTL and TEMPO's RTL with different
   settings. The mutation tooling (`tools/retrace/mutate.py`) can inject extraction-style errors.
8. **Proof, not only a match.** Where a structure is claimed, emit its word-level model and check
   it against the netlist with an equivalence or induction proof (SymbiYosys / z3). Report how
   many claims are proven and how many are only matched.
9. **Runtime and artifacts.** Report wall time. Only 4 % of 187 papers were reproducible, so
   publish the scripts and the labelled data (TEMPO's RTL is ours, so publishing the labels is
   not blocked by the licensing problems the SoK lists).

## 4. What this project has that is uncommon

Measured here (script in the session scratchpad, not committed):
- **TEMPO's sign-off netlist has 2,832 `sg13cmos5l_dfrbpq` flip-flops.** Every flop's `RESET_B`
  sits on its own `tiehi` net (2,832 distinct nets), so every reset is synchronous and lives in
  the D-cone.
- **The flops' `CLK` pins are spread over 239 distinct CTS leaf nets.** No flop has an enable pin.
- **Consequence:** DANA-style grouping by shared *pins* (clock, enable, reset) finds almost
  nothing on TEMPO unless the clock tree is traced back to its root and the enables and resets
  are recovered *functionally* from each flop's next-state cone.
- **The puzzle:** by `docs/INTENT.md`, `clk` and `rst_n` reach all 92 flops directly; the flops
  mix sky130 `dfrtp`, `dfstp` and `dfxtp`; enables are also in the D-logic. So pin-based
  grouping yields roughly one group there too.

Both are therefore realistic stress cases for pin-based grouping. Functional enable recovery is
itself prior art: WordRev's control wires, Subramanyan's "same enable/reset for all bits" check,
Tashjian and Davoodi.

## 5. Gaps this project could fill (stated modestly)

These are gaps *in what I found*. Absence from a search is not proof of absence.

1. **Evaluation on a real sign-off ASIC design, starting from its GDS, with RTL ground truth.**
   - Published grouping and recognition evaluations use synthesised netlists that keep their
     names: DANA (DC / LSI10k and Vivado), Subramanyan, WordRev, ReIGNN, GNN-RE.
   - Otherwise they use a black-box product with little ground truth (Klix: iPhone FPGA).
   - ReGDS goes from GDS to netlist but stops there.
   - The 2026 SoK proposes benchmarks pairing layouts and images with netlists and ground truth
     as future work.
   - TEMPO offers exactly this pairing, in an open PDK (IHP sg13cmos5l): GDS → RETRACE
     extraction → anonymous netlist → structures, scored against RTL names. It is 62,151
     instances, with a black-box SRAM macro and real CTS, hold buffers and tie cells.
   - The puzzle is a second, third-party GDS (sky130) with proven recovered RTL.
   - *Caveats:* TEMPO is one design, written by us; the puzzle is tiny. Neither is a fabricated
     die imaged by SEM, so extraction errors from imaging are not exercised.
2. **Proven sequential semantics per structure, including non-binary forms.** Prior work
   verifies:
   - binary up/down counters and shift registers with SAT (Subramanyan);
   - combinational templates, including a modulo counter slice, with ∃∀ SMT (Gascón);
   - arithmetic operations with SMT (Klix).

   What S3 could add is a word-level sequential model per structure, proven equivalent to the
   netlist fragment it replaces. The model would carry the bit order, the enable and synchronous
   reset conditions, and parameters: modulus (the puzzle's base-11 digits), saturation limit
   (the 2-bit bins) and feedback polynomial (the scrambler, TEMPO's CRCs). I did not find this
   end-to-end "recognise, then prove substitution" reported in the works above.
3. **LFSR and CRC characterisation by a GF(2)-linearity proof.**
   - Published LFSR handling is structural: a flop chain plus a DFS over the taps (Wallat'17);
     SPHINX's features and clustering; HAWKEYE's locality.
   - Algebraic polynomial recovery is published for combinational GF(2^m) multipliers (Yu et
     al.).

   I found no netlist reverse-engineering paper that proves a register's next-state map is
   affine over GF(2), extracts the matrix, and classifies it (Fibonacci or Galois LFSR, serial
   or parallel CRC with data injection). The technique itself is textbook linear algebra, so
   only its application and evaluation here would be new.
4. **ASIC standard-cell placement as a grouping cue, scored.** Proximity-based word grouping is
   published for FPGAs (VLSID'23, NMI 0.73), and placement-aware GNN partitioning for recovered
   netlists (GraphClusNet). I found no scored use of ASIC placement from GDS for *word*
   grouping. The cue is available here, but should be presented as a transfer of the FPGA idea.
5. **Pin-less control recovery at scale.** Functional recovery of enable and synchronous reset
   is known (item 4 above). TEMPO's 2,832 flops, with no usable control pins, are a larger
   labelled test of it than those I saw reported. This is a modest measurement contribution,
   not a method contribution.

## 6. Recommended methods for the first slice

The pipeline is ordered from cheap to expensive. Each step names where the idea comes from.

**Step 0: build a flop graph from the extracted netlist.**
- Treat flops as nodes; trace each D-input's combinational cone back to flop Qs, primary inputs
  and macro pins (DANA's abstraction).
- Resolve clocks to their root through CTS buffers and inverters, and treat tie cells as
  constants.
- Record placement (x, y) per flop.

**Step 1: functional control signatures for each flop** (Subramanyan's same enable/reset
condition; WordRev's control wires; Tashjian and Davoodi).
- For flop *q* with next-state function `f(q, X)`, take the candidate control nets *c* in its
  cone: those shared by many flops' cones, and the macro and top-level control pins.
- Use SAT (z3 or Yosys `sat`, or exhaustive evaluation when the support is ≤ 16 inputs) to find:
  - a **hold** literal: `f|c=v ≡ q`;
  - a **synchronous reset or set** literal: `f|c=v ≡ const`.
- Conjunctions of up to 2–3 literals should suffice, following WordRev's cap of 3.
- The flop's signature is (clock root, set of hold literals, set of reset literals and reset
  value). Signatures compare exactly, so no thresholds are needed.

**Step 2: word grouping.**
- Start from the partition by exact control signature. Refine it with DANA's
  successor/predecessor-group passes and majority vote, run to a fixed point.
- Optionally add a placement tie-breaker (VLSID'23) as a *separately reported ablation*.
- Score against the name-derived ground truth with NMI, purity, exact-word recall and
  split/merge counts (section 3).
- Also run HAL's DANA unchanged on the same extracted netlist, as the published baseline.

**Step 3: shift registers** (Subramanyan topology + SAT; Yosys `shregmap` as a pure-chain
sanity check).
- Candidate: a chain `q_i → q_{i+1}` where, under the group's enable, `f_{i+1}|en ≡ q_i`, and
  otherwise the flop holds.
- Aggregate parallel chains with identical signatures into multibit shift registers
  (Subramanyan).
- The bit order is the chain order.
- Prove the recognised model by substitution plus equivalence.
- Puzzle target: the 12-tap `I` shift register, whose taps are scattered over f56–f68, so its
  order must come out of the function, not the flop numbering.

**Step 4: counters.**
- Candidate topology: within a group, the dependency sets form a chain, and bit *i*'s cone
  depends on bits < *i* (Subramanyan, Fig. 2). This also gives the bit order.
- Confirm with a template family, not only the binary-toggle test:
  - up/down binary;
  - modulo-M, with M searched by SAT or by exhaustive evaluation for widths ≤ 8, where
    `next = (cur == M−1) ? 0 : cur ± 1`;
  - saturating;
  - each under the recovered enable and synchronous reset.

  This is Gascón's template idea specialised to sequential next-state functions; with the bit
  order fixed structurally, no permutation search is needed.
- Puzzle targets: the base-11 × base-11 counter as two mod-11 digits with a carry enable, the
  22 two-bit saturating bins, and `left_bottom`'s 8-bit up counter.

**Step 5: LFSRs and CRCs.**
- Candidate: a group whose next-state cone is built only of XOR/XNOR (after constant
  propagation), with a flop chain (Wallat'17's structural test).
- Confirm GF(2)-affinity: prove `f(a⊕b) ⊕ f(a) ⊕ f(b) ⊕ f(0) = 0` with SAT, or read off the
  matrix from n+1 evaluations and then prove it. Include data inputs as extra columns (CRC or
  scrambler injection).
- Classify the matrix: a companion (Fibonacci) or Galois form gives an LFSR, and its taps give
  the polynomial; a data column into the feedback gives a serial CRC; a full-rank matrix power
  gives a parallel CRC.
- Puzzle target: the 8-bit scrambler (mixed reset and set initial value `8'b1011_0110`, two
  update modes). TEMPO targets: its CRC units.

**Scoring and hygiene.**
- Per-class precision, recall and F1 against RTL-derived labels.
- Coverage of flops.
- Bit-order correctness.
- Counts of proven and merely matched structures; runtime.
- Freeze all parameters on the puzzle and on synthetic RTL before scoring TEMPO.
- Report where the method fails, e.g. words split by clock gating or by retiming, if present.

**Do not claim as new:**
- word grouping by shared control signals (Chisholm'99, Tashjian'15, DANA'20);
- grouping by shared predecessor/successor registers (DANA);
- topology + SAT counter and shift-register detection, and aggregation by identical
  set/reset/enable (Subramanyan'13);
- formal matching that also synthesises the I/O permutation and control conditions (Gascón'14,
  WordRev'13);
- SMT-verified arithmetic with bit order, and bit-order propagation from anchors (Klix'24 / HAL);
- structural LFSR detection with polynomial read-out (Wallat'17);
- NMI and purity as metrics (Meade'18, DANA);
- placement proximity for word grouping (VLSID'23);
- GDS-to-netlist extraction (ReGDS'20).

## 7. Search log (queries run)

**Crossref:**
- Subramanyan structural and functional analysis
- DANA
- RELIC-FUN
- REFSM / FSM gate-level
- netlist reverse engineering for high-level functionality
- GNN-RE
- ReIGNN
- HAL missing piece
- template-based circuit understanding
- functional matching SAT library components
- netlist abstraction Trojan detection (twice)
- identification of counters and shift registers in gate-level netlists
- Soeken simulation graphs
- ISCAS-85 case study
- Highway to HAL
- survey of algorithmic methods
- arithmetic block identification
- Gamora
- FPGA primitives word reconstruction
- LFSR identification netlist
- Stealing Maggie's Secrets
- word-level FPGA proximity
- LUT netlist word-level models
- ReBERT
- old frontier netlist partitioning
- Werner graph analysis
- Couch functional block identification
- Fyrbiak graph similarity
- Shi FSM extraction
- Fyrbiak FSM obfuscation
- Li-Wasson-Seshia pattern mining
- Diao coupling RE and SAT
- Dai-Brayton deep learning
- Wallat dark side
- Chisholm understanding ICs
- Doom high-level components
- HAWKEYE
- WolFEx
- Brunner human-readable FSM
- Keshavarz formal methods survey
- ABGNN network-flow
- SoK silicon to netlist
- Baehr ML structural
- Zhao-Shamsi adversarial
- SubGemini
- GraphClusNet
- SPHINX
- Yu-Holcomb-Ciesielski GF(2^m)
- FANCI
- word-level register recovery since 2022

**Semantic Scholar:**
- WordRev search
- DOI lookups: TETC'14, FMCAD'14, DAC'15, Old Frontier, Gamora, ABGNN, REFSM, ReBERT, fastRELIC,
  RELIC-FUN, FPT'22, IVSW'18, ReGDS, FSMx-Ultra, HOST'16
- bit order recovery search
- counter identification search

**WebSearch:**
- LFSR in gate-level netlists
- REFSM
- HAL plugins
- functional matching QBF
- Trojan netlist abstraction
- TETC PDF
- Tashjian abstract
- Template-based PDF
- GNN-RE arXiv
- ReIGNN arXiv
- Maggie CCS'24
- GF(2^m) reverse engineering
- CRC/LFSR GF(2) identification
- HAWKEYE

**WebFetch (read):**
- DANA eprint 2020/751
- WordRev PDF
- DATE'13 PDF
- FMCAD'14 PDF
- RELIC PDF
- ReIGNN arXiv PDF
- Maggie arXiv PDF
- Azriel eprint 2021/1278
- SoK arXiv 2603.17883
- Wallat arXiv 1910.01519
- HAL arXiv 2512.14139
- HAL wiki pages (Bitorder Propagation, Dataflow Analysis)
- GNN-RE GitHub README
- VLSID'23 and ISQED'23 arXiv abstracts
- RELIC-GNN arXiv abstract

**Failed:**
- arXiv API tool (HTTP 406 on every query)
- IEEE Xplore tool (unavailable)
- Semantic Scholar keyword search (intermittent HTTP 429)
- UCSB copy of the TETC'14 PDF (HTTP 403)
