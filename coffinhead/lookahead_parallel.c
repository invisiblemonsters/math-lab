/*
 * THE COFFINHEAD CONJECTURE — Parallel Bitwise k-Step Lookahead
 * ==============================================================
 * OpenMP-parallelized exact solver. Parallelism at the top-level
 * scoring loop: each (variable, value) pair scored in its own thread.
 *
 * Build: gcc -O3 -march=native -fopenmp -o lookahead_par lookahead_parallel.c -lm
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <omp.h>

typedef unsigned __int128 u128;

#define MAX_VARS    100
#define MAX_CLAUSES 500

static inline int popcnt128(u128 x) {
    return __builtin_popcountll((uint64_t)x) +
           __builtin_popcountll((uint64_t)(x >> 64));
}
static inline u128 BIT(int i) { return ((u128)1) << i; }
static inline int lowest_bit(u128 x) {
    uint64_t lo = (uint64_t)x;
    if (lo) return __builtin_ctzll(lo);
    return 64 + __builtin_ctzll((uint64_t)(x >> 64));
}
static inline int next_bit(u128 *mask) {
    int b = lowest_bit(*mask);
    *mask &= ~BIT(b);
    return b;
}

typedef struct { u128 pos; u128 neg; } BClause;
typedef struct { BClause clauses[MAX_CLAUSES]; int n_clauses; int n_vars; } Formula;
typedef struct { u128 t_mask; u128 f_mask; int n_set; } BAssign;

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
        f->clauses[i].pos = 0; f->clauses[i].neg = 0;
        int clen = (n_vars >= 3) ? 3 : n_vars;
        int vars[3];
        for (int j = 0; j < clen; j++) {
            int v; bool dup;
            do { v = 1 + rng_int(n_vars); dup = false;
                 for (int k = 0; k < j; k++) if (vars[k] == v) { dup = true; break; }
            } while (dup);
            vars[j] = v;
            if (rng_next() & 1) f->clauses[i].pos |= BIT(v-1);
            else                f->clauses[i].neg |= BIT(v-1);
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
            u128 p = out->clauses[i].pos, n = out->clauses[i].neg;
            if ((p & out->assign.t_mask) || (n & out->assign.f_mask)) continue;
            u128 assigned = out->assign.t_mask | out->assign.f_mask;
            u128 p_live = p & ~assigned, n_live = n & ~assigned;
            u128 all_live = p_live | n_live;
            if (!all_live) { out->contradiction = true; return; }
            if (popcnt128(all_live) == 1) {
                int bit = lowest_bit(all_live);
                if (p_live & BIT(bit)) {
                    if (out->assign.f_mask & BIT(bit)) { out->contradiction = true; return; }
                    if (!(out->assign.t_mask & BIT(bit))) {
                        out->assign.t_mask |= BIT(bit); out->assign.n_set++; changed = true;
                    }
                } else {
                    if (out->assign.t_mask & BIT(bit)) { out->contradiction = true; return; }
                    if (!(out->assign.f_mask & BIT(bit))) {
                        out->assign.f_mask |= BIT(bit); out->assign.n_set++; changed = true;
                    }
                }
            }
            out->clauses[new_count].pos = p_live;
            out->clauses[new_count].neg = n_live;
            new_count++;
        }
        out->n_clauses = new_count;
    }
}

u128 get_unassigned_mask(const BClause *clauses, int n_clauses, const BAssign *a) {
    u128 mask = 0;
    for (int i = 0; i < n_clauses; i++) mask |= clauses[i].pos | clauses[i].neg;
    mask &= ~(a->t_mask | a->f_mask);
    return mask;
}

/* ─── k-step lookahead (serial, called from threads) ─── */

double score_kstep(const BClause *clauses, int n_clauses,
                   const BAssign *assign, int var_bit, bool value,
                   int n_vars, int k) {
    BAssign new_a = *assign;
    if (value) new_a.t_mask |= BIT(var_bit);
    else       new_a.f_mask |= BIT(var_bit);
    new_a.n_set++;

    PropResult pr;
    unit_propagate(clauses, n_clauses, &new_a, &pr);
    if (pr.contradiction) return -1000.0;

    double immediate = (double)(pr.assign.n_set - assign->n_set - 1)
                     + (double)(n_clauses - pr.n_clauses);
    if (k <= 1) return immediate;

    u128 unassigned = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!unassigned) return immediate + 100.0 * k;

    double best_next = -1000.0;
    u128 tmp = unassigned;
    while (tmp) {
        int b = next_bit(&tmp);
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

    u128 unassigned = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!unassigned) return false;

    /* Collect candidates into array for OpenMP */
    int cand_bits[MAX_VARS * 2];
    int cand_vals[MAX_VARS * 2];
    int n_cand = 0;

    u128 tmp = unassigned;
    while (tmp) {
        int b = next_bit(&tmp);
        cand_bits[n_cand] = b; cand_vals[n_cand] = 1; n_cand++;
        cand_bits[n_cand] = b; cand_vals[n_cand] = 0; n_cand++;
    }

    double scores[MAX_VARS * 2];

    /* PARALLEL: score all candidates */
    #pragma omp parallel for schedule(dynamic)
    for (int i = 0; i < n_cand; i++) {
        scores[i] = score_kstep(pr.clauses, pr.n_clauses,
                                &pr.assign, cand_bits[i], (bool)cand_vals[i],
                                n_vars, k);
    }

    /* Find best */
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

    /* Try best */
    BAssign a1 = pr.assign;
    if (best_val) a1.t_mask |= BIT(best_bit);
    else          a1.f_mask |= BIT(best_bit);
    a1.n_set++;
    if (dpll_kstep(pr.clauses, pr.n_clauses, &a1, n_vars, k)) {
        *assign = a1; return true;
    }
    g_backtracks++;

    /* Try opposite */
    BAssign a2 = pr.assign;
    if (!best_val) a2.t_mask |= BIT(best_bit);
    else           a2.f_mask |= BIT(best_bit);
    a2.n_set++;
    bool r = dpll_kstep(pr.clauses, pr.n_clauses, &a2, n_vars, k);
    if (r) *assign = a2;
    return r;
}

bool solve_kstep(Formula *f, int k, int *out_bt) {
    g_backtracks = 0;
    BAssign a = {0, 0, 0};
    bool r = dpll_kstep(f->clauses, f->n_clauses, &a, f->n_vars, k);
    *out_bt = g_backtracks;
    return r;
}

/* ─── Hard core detection (serial, fast) ─── */

int g_bt_jw, g_bt_pol;

bool dpll_jw(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    u128 unassigned = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!unassigned) return false;
    double jw[MAX_VARS]={0}, jp[MAX_VARS]={0}, jn[MAX_VARS]={0};
    for (int i=0;i<pr.n_clauses;i++) {
        int cl2 = popcnt128(pr.clauses[i].pos|pr.clauses[i].neg);
        double w = pow(2.0,-(double)cl2);
        u128 p=pr.clauses[i].pos, n=pr.clauses[i].neg;
        while(p){int b=next_bit(&p);jw[b]+=w;jp[b]+=w;}
        while(n){int b=next_bit(&n);jw[b]+=w;jn[b]+=w;}
    }
    int bb=lowest_bit(unassigned); double bs=-1;
    u128 t=unassigned; while(t){int b=next_bit(&t);if(jw[b]>bs){bs=jw[b];bb=b;}}
    bool val=jp[bb]>=jn[bb];
    BAssign a1=pr.assign;
    if(val)a1.t_mask|=BIT(bb);else a1.f_mask|=BIT(bb); a1.n_set++;
    if(dpll_jw(pr.clauses,pr.n_clauses,&a1,nv)){*a=a1;return true;}
    g_bt_jw++;
    BAssign a2=pr.assign;
    if(!val)a2.t_mask|=BIT(bb);else a2.f_mask|=BIT(bb); a2.n_set++;
    bool r=dpll_jw(pr.clauses,pr.n_clauses,&a2,nv);if(r)*a=a2;return r;
}

bool dpll_pol(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    u128 unassigned = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!unassigned) return false;
    int pc[MAX_VARS]={0}, nc2[MAX_VARS]={0};
    for (int i=0;i<pr.n_clauses;i++) {
        u128 p=pr.clauses[i].pos, n=pr.clauses[i].neg;
        while(p){pc[next_bit(&p)]++;}
        while(n){nc2[next_bit(&n)]++;}
    }
    int bb=lowest_bit(unassigned); int bbias=-1;
    u128 t=unassigned; while(t){int b=next_bit(&t);int bi=abs(pc[b]-nc2[b]);
        if(bi>bbias){bbias=bi;bb=b;}}
    bool val=pc[bb]>=nc2[bb];
    BAssign a1=pr.assign;
    if(val)a1.t_mask|=BIT(bb);else a1.f_mask|=BIT(bb); a1.n_set++;
    if(dpll_pol(pr.clauses,pr.n_clauses,&a1,nv)){*a=a1;return true;}
    g_bt_pol++;
    BAssign a2=pr.assign;
    if(!val)a2.t_mask|=BIT(bb);else a2.f_mask|=BIT(bb); a2.n_set++;
    bool r=dpll_pol(pr.clauses,pr.n_clauses,&a2,nv);if(r)*a=a2;return r;
}

int is_hard_core(Formula *f) {
    BAssign a={0,0,0}; g_bt_pol=0;
    if(!dpll_pol(f->clauses,f->n_clauses,&a,f->n_vars)) return -1;
    if(g_bt_pol==0) return 0;
    a=(BAssign){0,0,0}; g_bt_jw=0;
    if(!dpll_jw(f->clauses,f->n_clauses,&a,f->n_vars)) return -1;
    if(g_bt_jw==0) return 0;
    return 1;
}

/* ─── Main ─── */

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <n_vars> <k_step> <n_target> [ratio] [threads]\n", argv[0]);
        return 1;
    }
    int n_vars = atoi(argv[1]);
    int k_step = atoi(argv[2]);
    int n_target = atoi(argv[3]);
    double ratio = (argc > 4) ? atof(argv[4]) : 4.0;
    int threads = (argc > 5) ? atoi(argv[5]) : omp_get_max_threads();

    if (n_vars > MAX_VARS) { fprintf(stderr, "n_vars > %d\n", MAX_VARS); return 1; }

    omp_set_num_threads(threads);

    printf("======================================================================\n");
    printf("  COFFINHEAD — Parallel Exact Lookahead (%d threads)\n", threads);
    printf("  n=%d, k=%d, target=%d, ratio=%.1f\n", n_vars, k_step, n_target, ratio);
    printf("======================================================================\n\n");

    int found = 0, zero_bt = 0, total_bt = 0;
    unsigned long long seed = 0, max_seed = (unsigned long long)n_target * 1000;
    double total_time = 0.0;
    struct timespec wall_start, wall_now;
    clock_gettime(CLOCK_MONOTONIC, &wall_start);

    while (found < n_target && seed < max_seed) {
        clock_gettime(CLOCK_MONOTONIC, &wall_now);
        double wel = (wall_now.tv_sec-wall_start.tv_sec)+(wall_now.tv_nsec-wall_start.tv_nsec)/1e9;
        if (wel > 600.0) { printf("  (wall timeout 600s)\n"); break; }

        Formula f;
        generate_random_3sat(&f, n_vars, ratio, seed); seed++;
        if (is_hard_core(&f) != 1) continue;
        generate_random_3sat(&f, n_vars, ratio, seed - 1);
        found++;

        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        int bt; solve_kstep(&f, k_step, &bt);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        double elapsed = (t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;

        total_time += elapsed;
        total_bt += bt;
        if (bt == 0) zero_bt++;
        else printf("  FAIL #%d: seed=%llu, bt=%d, %.2fs\n", found, seed-1, bt, elapsed);

        if (elapsed > 120.0) { printf("  (instance timeout %.1fs)\n", elapsed); break; }
        if (found % 5 == 0) {
            double rate = 100.0 * zero_bt / found;
            printf("  progress: %d/%d, zero-bt=%d/%d (%.1f%%), %.1fs\n",
                   found, n_target, zero_bt, found, rate, total_time);
        }
    }

    if (found > 0) {
        double rate = 100.0 * zero_bt / found;
        double avg = (double)total_bt / found;
        printf("\n  RESULT k=%d n=%d (%d threads): %d/%d = %.1f%% zero-BT, avg_bt=%.2f, %.1fs\n",
               k_step, n_vars, threads, zero_bt, found, rate, avg, total_time);
        printf(rate == 100.0 ? "  >>> PERFECT <<<\n" : "  >>> BREAKS <<<\n");
    }
    return 0;
}
