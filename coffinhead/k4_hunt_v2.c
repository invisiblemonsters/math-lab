/*
 * THE COFFINHEAD CONJECTURE — k=4 Boundary Hunter v2
 * ====================================================
 * Optimized for k=4 boundary search:
 * - Uses uint64_t arrays sized to actual n (not fixed 256)
 * - For n<=128: uses 2 words. For n<=192: 3 words. Etc.
 * - Eliminated clause compaction in unit prop (just marks satisfied)
 * - Added early termination in scoring when contradiction found
 *
 * Build: gcc -O3 -march=native -fopenmp -o k4v2 k4_hunt_v2.c -lm
 * Usage: ./k4v2 <n_vars> <k_step> <n_target> [ratio] [threads]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <omp.h>

/* Dynamic word count based on n_vars, set at startup */
static int NW;  /* Number of uint64_t words needed */

#define MAX_VARS 256
#define MAX_WORDS 4
#define MAX_CLAUSES 1200

/* ─── Inline bitmask ops on uint64_t[MAX_WORDS] ─── */
/* Using static arrays to avoid struct overhead */

typedef uint64_t BV[MAX_WORDS];

static inline void bv_zero_out(BV r) {
    for (int i = 0; i < NW; i++) r[i] = 0;
}

static inline void bv_copy(BV dst, const BV src) {
    for (int i = 0; i < NW; i++) dst[i] = src[i];
}

static inline void bv_set_bit(BV r, int bit) {
    r[bit / 64] |= (uint64_t)1 << (bit % 64);
}

static inline bool bv_test_bit(const BV r, int bit) {
    return (r[bit / 64] >> (bit % 64)) & 1;
}

static inline void bv_clear_bit_inplace(BV r, int bit) {
    r[bit / 64] &= ~((uint64_t)1 << (bit % 64));
}

static inline bool bv_is_zero(const BV a) {
    for (int i = 0; i < NW; i++) if (a[i]) return false;
    return true;
}

static inline void bv_or_into(BV dst, const BV src) {
    for (int i = 0; i < NW; i++) dst[i] |= src[i];
}

static inline bool bv_and_nonzero(const BV a, const BV b) {
    for (int i = 0; i < NW; i++) if (a[i] & b[i]) return true;
    return false;
}

/* a & ~b, store in dst */
static inline void bv_andnot(BV dst, const BV a, const BV b) {
    for (int i = 0; i < NW; i++) dst[i] = a[i] & ~b[i];
}

static inline void bv_or(BV dst, const BV a, const BV b) {
    for (int i = 0; i < NW; i++) dst[i] = a[i] | b[i];
}

static inline int bv_popcount(const BV a) {
    int c = 0;
    for (int i = 0; i < NW; i++) c += __builtin_popcountll(a[i]);
    return c;
}

static inline int bv_lowest(const BV a) {
    for (int i = 0; i < NW; i++)
        if (a[i]) return i * 64 + __builtin_ctzll(a[i]);
    return -1;
}

static inline int bv_next(BV mask) {
    int b = bv_lowest(mask);
    bv_clear_bit_inplace(mask, b);
    return b;
}

/* ─── Data structures ─── */

typedef struct { BV pos; BV neg; } BClause;

typedef struct {
    BClause clauses[MAX_CLAUSES];
    int n_clauses;
    int n_vars;
} Formula;

typedef struct {
    BV t_mask;
    BV f_mask;
    int n_set;
} BAssign;

typedef struct {
    BAssign assign;
    BClause clauses[MAX_CLAUSES];
    int n_clauses;
    bool contradiction;
} PropResult;

/* ─── RNG ─── */
static unsigned long long rng_state;
void rng_seed(unsigned long long s) { rng_state = s ? s : 1; }
unsigned long long rng_next(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return rng_state;
}
int rng_int(int n) { return (int)(rng_next() % (unsigned long long)n); }

void generate_random_3sat(Formula *f, int n_vars, double ratio, unsigned long long seed) {
    rng_seed(seed);
    f->n_vars = n_vars;
    f->n_clauses = (int)(n_vars * ratio);
    if (f->n_clauses > MAX_CLAUSES) f->n_clauses = MAX_CLAUSES;
    for (int i = 0; i < f->n_clauses; i++) {
        bv_zero_out(f->clauses[i].pos);
        bv_zero_out(f->clauses[i].neg);
        int clen = (n_vars >= 3) ? 3 : n_vars;
        int vars[3];
        for (int j = 0; j < clen; j++) {
            int v; bool dup;
            do { v = 1 + rng_int(n_vars); dup = false;
                 for (int k = 0; k < j; k++) if (vars[k] == v) { dup = true; break; }
            } while (dup);
            vars[j] = v;
            if (rng_next() & 1) bv_set_bit(f->clauses[i].pos, v-1);
            else                bv_set_bit(f->clauses[i].neg, v-1);
        }
    }
}

/* ─── Unit propagation ─── */

void unit_propagate(const BClause *clauses, int n_clauses,
                    const BAssign *ain, PropResult *out) {
    out->assign = *ain;
    out->contradiction = false;
    memcpy(out->clauses, clauses, sizeof(BClause) * n_clauses);
    out->n_clauses = n_clauses;

    bool changed = true;
    while (changed) {
        changed = false;
        int new_count = 0;
        for (int i = 0; i < out->n_clauses; i++) {
            /* Clause satisfied? */
            if (bv_and_nonzero(out->clauses[i].pos, out->assign.t_mask) ||
                bv_and_nonzero(out->clauses[i].neg, out->assign.f_mask)) continue;

            BV assigned, p_live, n_live, all_live;
            bv_or(assigned, out->assign.t_mask, out->assign.f_mask);
            bv_andnot(p_live, out->clauses[i].pos, assigned);
            bv_andnot(n_live, out->clauses[i].neg, assigned);
            bv_or(all_live, p_live, n_live);

            if (bv_is_zero(all_live)) { out->contradiction = true; return; }

            if (bv_popcount(all_live) == 1) {
                int bit = bv_lowest(all_live);
                if (bv_test_bit(p_live, bit)) {
                    if (bv_test_bit(out->assign.f_mask, bit)) { out->contradiction = true; return; }
                    if (!bv_test_bit(out->assign.t_mask, bit)) {
                        bv_set_bit(out->assign.t_mask, bit);
                        out->assign.n_set++; changed = true;
                    }
                } else {
                    if (bv_test_bit(out->assign.t_mask, bit)) { out->contradiction = true; return; }
                    if (!bv_test_bit(out->assign.f_mask, bit)) {
                        bv_set_bit(out->assign.f_mask, bit);
                        out->assign.n_set++; changed = true;
                    }
                }
            }
            bv_copy(out->clauses[new_count].pos, p_live);
            bv_copy(out->clauses[new_count].neg, n_live);
            new_count++;
        }
        out->n_clauses = new_count;
    }
}

void get_unassigned_mask(BV out, const BClause *clauses, int n_clauses, const BAssign *a) {
    BV assigned;
    bv_zero_out(out);
    for (int i = 0; i < n_clauses; i++) {
        bv_or_into(out, clauses[i].pos);
        bv_or_into(out, clauses[i].neg);
    }
    bv_or(assigned, a->t_mask, a->f_mask);
    for (int i = 0; i < NW; i++) out[i] &= ~assigned[i];
}

/* ─── k-step lookahead ─── */

double score_kstep(const BClause *clauses, int n_clauses,
                   const BAssign *assign, int var_bit, bool value,
                   int n_vars, int k) {
    BAssign new_a = *assign;
    if (value) bv_set_bit(new_a.t_mask, var_bit);
    else       bv_set_bit(new_a.f_mask, var_bit);
    new_a.n_set++;

    PropResult pr;
    unit_propagate(clauses, n_clauses, &new_a, &pr);
    if (pr.contradiction) return -1000.0;

    double immediate = (double)(pr.assign.n_set - assign->n_set - 1)
                     + (double)(n_clauses - pr.n_clauses);
    if (k <= 1) return immediate;

    BV unassigned;
    get_unassigned_mask(unassigned, pr.clauses, pr.n_clauses, &pr.assign);
    if (bv_is_zero(unassigned)) return immediate + 100.0 * k;

    double best_next = -1000.0;
    BV tmp;
    bv_copy(tmp, unassigned);
    while (!bv_is_zero(tmp)) {
        int b = bv_next(tmp);
        for (int v = 0; v <= 1; v++) {
            double s = score_kstep(pr.clauses, pr.n_clauses,
                                   &pr.assign, b, (bool)v, n_vars, k - 1);
            if (s > best_next) best_next = s;
        }
    }
    return immediate + ((best_next > -1000.0) ? best_next : 0.0);
}

/* ─── DPLL with PARALLEL top-level scoring ─── */

int g_backtracks;

bool dpll_kstep(const BClause *clauses, int n_clauses,
                BAssign *assign, int n_vars, int k) {
    PropResult pr;
    unit_propagate(clauses, n_clauses, assign, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *assign = pr.assign; return true; }

    BV unassigned;
    get_unassigned_mask(unassigned, pr.clauses, pr.n_clauses, &pr.assign);
    if (bv_is_zero(unassigned)) return false;

    /* Collect candidates */
    int cand_bits[MAX_VARS * 2];
    int cand_vals[MAX_VARS * 2];
    int n_cand = 0;

    BV tmp;
    bv_copy(tmp, unassigned);
    while (!bv_is_zero(tmp)) {
        int b = bv_next(tmp);
        cand_bits[n_cand] = b; cand_vals[n_cand] = 1; n_cand++;
        cand_bits[n_cand] = b; cand_vals[n_cand] = 0; n_cand++;
    }

    double scores[MAX_VARS * 2];

    #pragma omp parallel for schedule(dynamic)
    for (int i = 0; i < n_cand; i++) {
        scores[i] = score_kstep(pr.clauses, pr.n_clauses,
                                &pr.assign, cand_bits[i], (bool)cand_vals[i],
                                n_vars, k);
    }

    double best_score = -2000.0;
    int best_idx = 0;
    for (int i = 0; i < n_cand; i++) {
        if (scores[i] > best_score) {
            best_score = scores[i];
            best_idx = i;
        }
    }

    int best_bit = cand_bits[best_idx];
    bool best_val = (bool)cand_vals[best_idx];

    BAssign a1 = pr.assign;
    if (best_val) bv_set_bit(a1.t_mask, best_bit);
    else          bv_set_bit(a1.f_mask, best_bit);
    a1.n_set++;
    if (dpll_kstep(pr.clauses, pr.n_clauses, &a1, n_vars, k)) {
        *assign = a1; return true;
    }
    g_backtracks++;

    BAssign a2 = pr.assign;
    if (!best_val) bv_set_bit(a2.t_mask, best_bit);
    else           bv_set_bit(a2.f_mask, best_bit);
    a2.n_set++;
    bool r = dpll_kstep(pr.clauses, pr.n_clauses, &a2, n_vars, k);
    if (r) *assign = a2;
    return r;
}

bool solve_kstep(Formula *f, int k, int *out_bt) {
    g_backtracks = 0;
    BAssign a;
    bv_zero_out(a.t_mask);
    bv_zero_out(a.f_mask);
    a.n_set = 0;
    bool r = dpll_kstep(f->clauses, f->n_clauses, &a, f->n_vars, k);
    *out_bt = g_backtracks;
    return r;
}

/* ─── Hard core detection ─── */

int g_bt_jw, g_bt_pol;

bool dpll_jw(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    BV unassigned;
    get_unassigned_mask(unassigned, pr.clauses, pr.n_clauses, &pr.assign);
    if (bv_is_zero(unassigned)) return false;
    double jw[MAX_VARS]={0}, jp[MAX_VARS]={0}, jn[MAX_VARS]={0};
    for (int i = 0; i < pr.n_clauses; i++) {
        BV both;
        bv_or(both, pr.clauses[i].pos, pr.clauses[i].neg);
        int cl2 = bv_popcount(both);
        double w = pow(2.0, -(double)cl2);
        BV p, n;
        bv_copy(p, pr.clauses[i].pos); bv_copy(n, pr.clauses[i].neg);
        while (!bv_is_zero(p)) { int b = bv_next(p); jw[b] += w; jp[b] += w; }
        while (!bv_is_zero(n)) { int b = bv_next(n); jw[b] += w; jn[b] += w; }
    }
    int bb = bv_lowest(unassigned); double bs = -1;
    BV t; bv_copy(t, unassigned);
    while (!bv_is_zero(t)) { int b = bv_next(t); if (jw[b] > bs) { bs = jw[b]; bb = b; } }
    bool val = jp[bb] >= jn[bb];
    BAssign a1 = pr.assign;
    if (val) bv_set_bit(a1.t_mask, bb);
    else     bv_set_bit(a1.f_mask, bb);
    a1.n_set++;
    if (dpll_jw(pr.clauses, pr.n_clauses, &a1, nv)) { *a = a1; return true; }
    g_bt_jw++;
    BAssign a2 = pr.assign;
    if (!val) bv_set_bit(a2.t_mask, bb);
    else      bv_set_bit(a2.f_mask, bb);
    a2.n_set++;
    bool r = dpll_jw(pr.clauses, pr.n_clauses, &a2, nv);
    if (r) *a = a2;
    return r;
}

bool dpll_pol(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    BV unassigned;
    get_unassigned_mask(unassigned, pr.clauses, pr.n_clauses, &pr.assign);
    if (bv_is_zero(unassigned)) return false;
    int pc[MAX_VARS]={0}, nc2[MAX_VARS]={0};
    for (int i = 0; i < pr.n_clauses; i++) {
        BV p, n;
        bv_copy(p, pr.clauses[i].pos); bv_copy(n, pr.clauses[i].neg);
        while (!bv_is_zero(p)) { pc[bv_next(p)]++; }
        while (!bv_is_zero(n)) { nc2[bv_next(n)]++; }
    }
    int bb = bv_lowest(unassigned); int bbias = -1;
    BV t; bv_copy(t, unassigned);
    while (!bv_is_zero(t)) {
        int b = bv_next(t);
        int bi = abs(pc[b] - nc2[b]);
        if (bi > bbias) { bbias = bi; bb = b; }
    }
    bool val = pc[bb] >= nc2[bb];
    BAssign a1 = pr.assign;
    if (val) bv_set_bit(a1.t_mask, bb);
    else     bv_set_bit(a1.f_mask, bb);
    a1.n_set++;
    if (dpll_pol(pr.clauses, pr.n_clauses, &a1, nv)) { *a = a1; return true; }
    g_bt_pol++;
    BAssign a2 = pr.assign;
    if (!val) bv_set_bit(a2.t_mask, bb);
    else      bv_set_bit(a2.f_mask, bb);
    a2.n_set++;
    bool r = dpll_pol(pr.clauses, pr.n_clauses, &a2, nv);
    if (r) *a = a2;
    return r;
}

int is_hard_core(Formula *f) {
    BAssign a; bv_zero_out(a.t_mask); bv_zero_out(a.f_mask); a.n_set = 0;
    g_bt_pol = 0;
    if (!dpll_pol(f->clauses, f->n_clauses, &a, f->n_vars)) return -1;
    if (g_bt_pol == 0) return 0;
    bv_zero_out(a.t_mask); bv_zero_out(a.f_mask); a.n_set = 0;
    g_bt_jw = 0;
    if (!dpll_jw(f->clauses, f->n_clauses, &a, f->n_vars)) return -1;
    if (g_bt_jw == 0) return 0;
    return 1;
}

/* ─── Main: boundary scan mode ─── */

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <n_vars> <k_step> <n_target> [ratio] [threads]\n", argv[0]);
        fprintf(stderr, "  n_vars: problem size (max %d)\n", MAX_VARS);
        fprintf(stderr, "  k_step: lookahead depth\n");
        fprintf(stderr, "  n_target: hard-core instances to test\n");
        return 1;
    }
    int n_vars = atoi(argv[1]);
    int k_step = atoi(argv[2]);
    int n_target = atoi(argv[3]);
    double ratio = (argc > 4) ? atof(argv[4]) : 4.0;
    int threads = (argc > 5) ? atoi(argv[5]) : omp_get_max_threads();

    if (n_vars > MAX_VARS) { fprintf(stderr, "n_vars > %d\n", MAX_VARS); return 1; }

    /* Set word count based on actual n */
    NW = (n_vars + 63) / 64;
    if (NW < 1) NW = 1;
    if (NW > MAX_WORDS) NW = MAX_WORDS;

    omp_set_num_threads(threads);

    printf("======================================================================\n");
    printf("  COFFINHEAD — k=%d Boundary Hunter v2 (%d threads, %d-bit)\n",
           k_step, threads, NW * 64);
    printf("  n=%d, target=%d hard-core, ratio=%.1f\n", n_vars, n_target, ratio);
    printf("======================================================================\n\n");
    fflush(stdout);

    int found = 0, zero_bt = 0, total_bt = 0;
    unsigned long long seed = 0, max_seed = (unsigned long long)n_target * 2000;
    double total_time = 0.0;

    while (found < n_target && seed < max_seed) {
        Formula f;
        generate_random_3sat(&f, n_vars, ratio, seed); seed++;
        if (is_hard_core(&f) != 1) continue;
        generate_random_3sat(&f, n_vars, ratio, seed - 1);
        found++;

        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        int bt; solve_kstep(&f, k_step, &bt);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        double elapsed = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;

        total_time += elapsed;
        total_bt += bt;
        if (bt == 0) {
            zero_bt++;
            printf("  OK  #%d: seed=%llu, 0 bt, %.1fs (total %.0fs)\n",
                   found, seed-1, elapsed, total_time);
        } else {
            printf("  FAIL #%d: seed=%llu, bt=%d, %.1fs  *** BOUNDARY CANDIDATE ***\n",
                   found, seed-1, bt, elapsed);
        }
        fflush(stdout);
    }

    if (found > 0) {
        double rate = 100.0 * zero_bt / found;
        printf("\n  RESULT k=%d n=%d: %d/%d = %.1f%% zero-BT, %.0fs total\n",
               k_step, n_vars, zero_bt, found, rate, total_time);
        printf(rate == 100.0 ? "  >>> PERFECT <<<\n" : "  >>> BREAKS <<<\n");
    }
    fflush(stdout);
    return 0;
}
