/*
 * COFFINHEAD 256-bit — k-Step Lookahead to n=256
 * ================================================
 * Uses two u128 for pos/neg masks, supporting up to 256 variables.
 * Build: gcc -O3 -march=native -fopenmp -o solve_256 solve_256.c -lm
 * Usage: ./solve_256 <n> <k> <seed> [beam] [n_instances]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <omp.h>

/* ─── 256-bit type from two u128 ─── */
typedef unsigned __int128 u128;
typedef struct { u128 lo; u128 hi; } u256;

static inline u256 U256_ZERO(void) { return (u256){0, 0}; }
static inline u256 u256_or(u256 a, u256 b) { return (u256){a.lo|b.lo, a.hi|b.hi}; }
static inline u256 u256_and(u256 a, u256 b) { return (u256){a.lo&b.lo, a.hi&b.hi}; }
static inline u256 u256_not(u256 a) { return (u256){~a.lo, ~a.hi}; }
static inline u256 u256_andnot(u256 a, u256 mask) { return (u256){a.lo & ~mask.lo, a.hi & ~mask.hi}; }
static inline bool u256_zero(u256 a) { return !a.lo && !a.hi; }
static inline u256 u256_bit(int i) {
    u256 r = {0, 0};
    if (i < 128) r.lo = ((u128)1) << i;
    else r.hi = ((u128)1) << (i - 128);
    return r;
}
static inline bool u256_test(u256 a, int i) {
    if (i < 128) return (a.lo >> i) & 1;
    return (a.hi >> (i - 128)) & 1;
}
static inline int u256_popcnt(u256 a) {
    return __builtin_popcountll((uint64_t)a.lo) + __builtin_popcountll((uint64_t)(a.lo >> 64))
         + __builtin_popcountll((uint64_t)a.hi) + __builtin_popcountll((uint64_t)(a.hi >> 64));
}
static inline int u256_lowest(u256 a) {
    if (a.lo) {
        uint64_t lo64 = (uint64_t)a.lo;
        if (lo64) return __builtin_ctzll(lo64);
        return 64 + __builtin_ctzll((uint64_t)(a.lo >> 64));
    }
    uint64_t lo64 = (uint64_t)a.hi;
    if (lo64) return 128 + __builtin_ctzll(lo64);
    return 192 + __builtin_ctzll((uint64_t)(a.hi >> 64));
}
static inline int u256_next_bit(u256 *m) {
    int b = u256_lowest(*m);
    u256 bit = u256_bit(b);
    m->lo &= ~bit.lo; m->hi &= ~bit.hi;
    return b;
}

#define MAX_VARS 256
#define MAX_CLAUSES 1200

typedef struct { u256 pos; u256 neg; } BClause;
typedef struct { u256 t_mask; u256 f_mask; int n_set; } BAssign;
typedef struct { BAssign assign; BClause clauses[MAX_CLAUSES]; int n_clauses; bool contradiction; } PropResult;

static int BEAM = 0;

/* ─── RNG ─── */
static unsigned long long rng_state;
void rng_seed(unsigned long long s) { rng_state = s ? s : 1; }
unsigned long long rng_next(void) { rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17; return rng_state; }
int rng_int(int n) { return (int)(rng_next() % (unsigned long long)n); }

typedef struct { BClause clauses[MAX_CLAUSES]; int n_clauses; int n_vars; } Formula;

void gen(Formula *f, int nv, double r, unsigned long long seed) {
    rng_seed(seed); f->n_vars = nv; f->n_clauses = (int)(nv * r);
    if (f->n_clauses > MAX_CLAUSES) f->n_clauses = MAX_CLAUSES;
    for (int i = 0; i < f->n_clauses; i++) {
        f->clauses[i].pos = U256_ZERO(); f->clauses[i].neg = U256_ZERO();
        int vs[3];
        for (int j = 0; j < 3; j++) {
            int v; bool d;
            do { v = 1 + rng_int(nv); d = false; for (int k2 = 0; k2 < j; k2++) if (vs[k2] == v) { d = true; break; } } while (d);
            vs[j] = v;
            u256 bit = u256_bit(v - 1);
            if (rng_next() & 1) { f->clauses[i].pos = u256_or(f->clauses[i].pos, bit); }
            else                { f->clauses[i].neg = u256_or(f->clauses[i].neg, bit); }
        }
    }
}

/* ─── Unit propagation ─── */
void up(const BClause *cl, int nc, const BAssign *ain, PropResult *out) {
    out->assign = *ain; out->contradiction = false;
    memcpy(out->clauses, cl, sizeof(BClause) * nc); out->n_clauses = nc;
    bool ch = true;
    while (ch) {
        ch = false; int nc2 = 0;
        u256 assigned = u256_or(out->assign.t_mask, out->assign.f_mask);
        for (int i = 0; i < out->n_clauses; i++) {
            u256 p = out->clauses[i].pos, n = out->clauses[i].neg;
            /* Satisfied? */
            if (!u256_zero(u256_and(p, out->assign.t_mask)) ||
                !u256_zero(u256_and(n, out->assign.f_mask))) continue;
            u256 pl = u256_andnot(p, assigned);
            u256 nl = u256_andnot(n, assigned);
            u256 al = u256_or(pl, nl);
            if (u256_zero(al)) { out->contradiction = true; return; }
            /* Fast unit check: exactly one bit set = popcount==1.
               Faster: x & (x-1) == 0 and x != 0 */
            u128 al_full = al.lo | al.hi;
            bool is_unit;
            if (!al.hi) is_unit = al.lo && !(al.lo & (al.lo - 1));
            else if (!al.lo) is_unit = al.hi && !(al.hi & (al.hi - 1));
            else is_unit = false; /* bits in both halves = at least 2 */
            if (is_unit) {
                int b = u256_lowest(al);
                u256 bit = u256_bit(b);
                if (u256_test(pl, b)) {
                    if (u256_test(out->assign.f_mask, b)) { out->contradiction = true; return; }
                    if (!u256_test(out->assign.t_mask, b)) {
                        out->assign.t_mask = u256_or(out->assign.t_mask, bit);
                        out->assign.n_set++; ch = true;
                    }
                } else {
                    if (u256_test(out->assign.t_mask, b)) { out->contradiction = true; return; }
                    if (!u256_test(out->assign.f_mask, b)) {
                        out->assign.f_mask = u256_or(out->assign.f_mask, bit);
                        out->assign.n_set++; ch = true;
                    }
                }
            }
            out->clauses[nc2].pos = pl; out->clauses[nc2].neg = nl; nc2++;
        }
        out->n_clauses = nc2;
    }
}

u256 get_un(const BClause *c, int nc, const BAssign *a) {
    u256 m = U256_ZERO();
    for (int i = 0; i < nc; i++) m = u256_or(m, u256_or(c[i].pos, c[i].neg));
    u256 assigned = u256_or(a->t_mask, a->f_mask);
    return u256_andnot(m, assigned);
}

/* ─── k-step scoring ─── */
double score_k(const BClause *cl, int nc, const BAssign *a, int vb, bool val, int nv, int k) {
    BAssign na = *a;
    u256 bit = u256_bit(vb);
    if (val) na.t_mask = u256_or(na.t_mask, bit);
    else     na.f_mask = u256_or(na.f_mask, bit);
    na.n_set++;
    PropResult pr; up(cl, nc, &na, &pr);
    if (pr.contradiction) return -1000.0;
    double imm = (double)(pr.assign.n_set - a->n_set - 1) + (double)(nc - pr.n_clauses);
    if (k <= 1) return imm;
    u256 un = get_un(pr.clauses, pr.n_clauses, &pr.assign);
    if (u256_zero(un)) return imm + 100.0 * k;

    int vs[MAX_VARS], nv2 = 0;
    u256 tmp = un; while (!u256_zero(tmp)) vs[nv2++] = u256_next_bit(&tmp);

    if (BEAM > 0 && nv2 > BEAM) {
        double jw[MAX_VARS] = {0};
        for (int i = 0; i < pr.n_clauses; i++) {
            int cl2 = u256_popcnt(u256_or(pr.clauses[i].pos, pr.clauses[i].neg));
            double w = pow(2.0, -(double)cl2);
            u256 p2 = pr.clauses[i].pos, n2 = pr.clauses[i].neg;
            while (!u256_zero(p2)) { jw[u256_next_bit(&p2)] += w; }
            while (!u256_zero(n2)) { jw[u256_next_bit(&n2)] += w; }
        }
        for (int i = 0; i < BEAM && i < nv2; i++) {
            int best = i;
            for (int j = i + 1; j < nv2; j++) if (jw[vs[j]] > jw[vs[best]]) best = j;
            if (best != i) { int t = vs[i]; vs[i] = vs[best]; vs[best] = t; }
        }
        nv2 = BEAM;
    }

    double best = -1000.0;
    for (int i = 0; i < nv2; i++)
        for (int v = 0; v <= 1; v++) {
            double s = score_k(pr.clauses, pr.n_clauses, &pr.assign, vs[i], (bool)v, nv, k - 1);
            if (s > best) best = s;
        }
    return imm + ((best > -1000.0) ? best : 0.0);
}

/* ─── DPLL ─── */
int g_bt;
bool dpll(const BClause *cl, int nc, BAssign *a, int nv, int k) {
    PropResult pr; up(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    u256 un = get_un(pr.clauses, pr.n_clauses, &pr.assign);
    if (u256_zero(un)) return false;

    int cb[MAX_VARS * 2], cv[MAX_VARS * 2]; int ncand = 0;
    u256 tmp = un;
    while (!u256_zero(tmp)) { int b = u256_next_bit(&tmp); cb[ncand] = b; cv[ncand] = 1; ncand++; cb[ncand] = b; cv[ncand] = 0; ncand++; }

    double sc[MAX_VARS * 2];
    #pragma omp parallel for schedule(dynamic) if(ncand > 8)
    for (int i = 0; i < ncand; i++)
        sc[i] = score_k(pr.clauses, pr.n_clauses, &pr.assign, cb[i], (bool)cv[i], nv, k);

    double bs = -2000.0; int bi = 0;
    for (int i = 0; i < ncand; i++) if (sc[i] > bs) { bs = sc[i]; bi = i; }

    BAssign a1 = pr.assign;
    u256 bit = u256_bit(cb[bi]);
    if (cv[bi]) a1.t_mask = u256_or(a1.t_mask, bit);
    else        a1.f_mask = u256_or(a1.f_mask, bit);
    a1.n_set++;
    if (dpll(pr.clauses, pr.n_clauses, &a1, nv, k)) { *a = a1; return true; }
    g_bt++;

    BAssign a2 = pr.assign;
    if (!cv[bi]) a2.t_mask = u256_or(a2.t_mask, bit);
    else         a2.f_mask = u256_or(a2.f_mask, bit);
    a2.n_set++;
    bool r = dpll(pr.clauses, pr.n_clauses, &a2, nv, k);
    if (r) *a = a2; return r;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "Usage: %s <n> <k> <seed> [beam] [count]\n", argv[0]); return 1; }
    int n = atoi(argv[1]), k = atoi(argv[2]); unsigned long long seed_start = atoll(argv[3]);
    if (argc > 4) BEAM = atoi(argv[4]);
    int count = (argc > 5) ? atoi(argv[5]) : 1;
    if (n > MAX_VARS) { fprintf(stderr, "n=%d > MAX_VARS=%d\n", n, MAX_VARS); return 1; }

    printf("COFFINHEAD 256-bit: n=%d k=%d beam=%d count=%d\n", n, k, BEAM, count);

    int total_bt = 0, zero_bt = 0;
    double total_time = 0;
    for (int i = 0; i < count; i++) {
        unsigned long long seed = seed_start + i;
        Formula f; gen(&f, n, 4.0, seed);
        g_bt = 0;
        BAssign a; a.t_mask = U256_ZERO(); a.f_mask = U256_ZERO(); a.n_set = 0;
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        bool sat = dpll(f.clauses, f.n_clauses, &a, n, k);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        double el = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
        total_time += el;
        total_bt += g_bt;
        if (g_bt == 0) zero_bt++;
        printf("  seed=%llu: %s bt=%d %.1fs\n", seed, sat ? "SAT" : "UNSAT", g_bt, el);
        if (el > 120.0) { printf("  (timeout)\n"); break; }
    }
    printf("SUMMARY: %d/%d zero-BT, avg_bt=%.1f, %.1fs total\n",
           zero_bt, count, (double)total_bt / count, total_time);
    return 0;
}
