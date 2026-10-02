"""Directed row-count test of docs/SOLVE_ANALYTICAL.md section 4, against Icarus rec_left_top.

Every other row holds exactly 2 stars while one row's count is swept 0..4 (rows 0, 5, 10);
then five trials where every row gets a different random pair of columns. row_count_err must
be 0 exactly when every row has 2 stars. Run: python -m tools.solve.rowcount_check
"""
import itertools
import random
import sys

from tools.solve import starbattle as sb


def main():
    sb.build_testbenches()
    idx = {rc: k for k, rc in enumerate(sb.cell_order())}

    def seq(stars):
        v = [0] * 121
        for rc in stars:
            v[idx[rc]] = 1
        return v

    ok = True
    for target in (0, 5, 10):
        for k in range(5):
            stars = [(r, c) for r in range(11) if r != target for c in (1, 7)]
            stars += [(target, c) for c in (0, 2, 4, 6)[:k]]
            err, _, done = sb.run_icarus_left_top(seq(stars))
            ok &= done and err == (k != 2)
            print(f"row {target:2d} count {k}: row_count_err={int(err)} cnt_done={int(done)}")
    rng = random.Random(20261002)
    pairs = list(itertools.combinations(range(11), 2))
    for t in range(5):
        stars = [(r, c) for r, pair in enumerate(rng.sample(pairs, 11)) for c in pair]
        err, _, done = sb.run_icarus_left_top(seq(stars))
        ok &= done and not err
        print(f"random pairs {t}: row_count_err={int(err)} cnt_done={int(done)}")
    print("ALL MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
