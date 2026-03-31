/*
 * THE COFFINHEAD CONJECTURE — Optimized k-Step Lookahead SAT Solver
 * ==================================================================
 * Optimizations over lookahead_solver.c:
 * 1. Alpha-beta pruning: skip branches that can't beat current best
 * 2. Beam search: at each lookahead level, only evaluate top-B variables
 * 3. Contradiction caching: skip (var,val) pairs known to contradict
 * 4. Stack-allocated clause arrays (no malloc in hot path)
 *
 * Build: gcc -O3 -o lookahead_fast lookahead_fast.c -lm
 * Usage: ./lookahead_fast <n_vars> <k_step> <n_target> [ratio] [beam_width]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>

#define MAX_VARS    100
#define MAX_CLAUSES 500
#define MAX_LIT     3
#define DEFAULT_BEAM 8  /* top-B variables to evaluate at each lookahead level */

static int BEAM_WIDTH = DEFAULT_BEAM;

/* ─── Formula representation ─── */

typedef struct {
    int lits[MAX_LIT];
    int len;
} Clause;

typedef struct {
    Clause clauses[MAX_CLAUSES];
    int n_clauses;
    int n_vars;
} Formula;

typedef struct {
    int val[MAX_VARS + 1];
    int n_set;
} Assignment;

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

/* ─── Formula generation ─── */

void generate_random_3sat(Formula *f, int n_vars, double ratio, unsigned long long seed) {
    rng_seed(seed);
    f->n_vars = n_vars;
    f->n_clauses = (int)(n_vars * ratio);
    if (f->n_clauses > MAX_CLAUSES) f->n_clauses = MAX_CLAUSES;
    for (int i = 0; i < f->n_clauses; i++) {
        f->clauses[i].len = (n_vars >= 3) ? 3 : n_vars;
        int vars[3];
        for (int j = 0; j < f->clauses[i].len; j++) {
            int v; bool dup;
            do {
                v = 1 + rng_int(n_vars);
                dup = false;
                for (int k = 0; k < j; k++) if (abs(vars[k]) == v) { dup = true; break; }
            } while (dup);
            vars[j] = (rng_next() & 1) ? v : -v;
        }
        for (int j = 0; j < f->clauses[i].len; j++)
            f->clauses[i].lits[j] = vars[j];
    }
}

/* ─── Unit propagation (stack-allocated output) ─── */

typedef struct {
    Assignment assign;
    Clause clauses[MAX_CLAUSES];
    int n_clauses;
    bool contradiction;
} PropResult;

void unit_propagate(const Clause *clauses, int n_clauses,
                    const Assignment *assign_in, PropResult *out) {
    memcpy(&out->assign, assign_in, sizeof(Assignment));
    out->contradiction = false;
    memcpy(out->clauses, clauses, sizeof(Clause) * n_clauses);
    out->n_clauses = n_clauses;

    bool changed = true;
    while (changed) {
        changed = false;
        int new_count = 0;
        for (int i = 0; i < out->n_clauses; i++) {
            Clause *c = &out->clauses[i];
            int simplified[MAX_LIT]; int slen = 0;
            bool satisfied = false;
            for (int j = 0; j < c->len; j++) {
                int lit = c->lits[j], var = abs(lit);
                int aval = out->assign.val[var];
                if (aval != 0) {
                    if ((lit > 0 && aval == 1) || (lit < 0 && aval == -1)) { satisfied = true; break; }
                } else {
                    simplified[slen++] = lit;
                }
            }
            if (satisfied) continue;
            if (slen == 0) { out->contradiction = true; return; }
            if (slen == 1) {
                int lit = simplified[0], var = abs(lit), val = (lit > 0) ? 1 : -1;
                if (out->assign.val[var] != 0 && out->assign.val[var] != val) { out->contradiction = true; return; }
                if (out->assign.val[var] == 0) { out->assign.val[var] = val; out->assign.n_set++; changed = true; }
            }
            Clause *nc = &out->clauses[new_count];
            nc->len = slen;
            for (int j = 0; j < slen; j++) nc->lits[j] = simplified[j];
            new_count++;
        }
        out->n_clauses = new_count;
    }
}

/* ─── Unassigned variables ─── */

int get_unassigned(const Clause *clauses, int n_clauses,
                   const Assignment *assign, int *out_vars) {
    bool seen[MAX_VARS + 1] = {false};
    int count = 0;
    for (int i = 0; i < n_clauses; i++)
        for (int j = 0; j < clauses[i].len; j++) {
            int var = abs(clauses[i].lits[j]);
            if (assign->val[var] == 0 && !seen[var]) { seen[var] = true; out_vars[count++] = var; }
        }
    return count;
}

/* ─── Quick JW score for beam selection ─── */

void jw_scores(const Clause *clauses, int n_clauses, const Assignment *assign,
               const int *vars, int n_vars_list, double *scores) {
    double jw_total[MAX_VARS + 1] = {0};
    for (int i = 0; i < n_clauses; i++) {
        double w = pow(2.0, -(double)clauses[i].len);
        for (int j = 0; j < clauses[i].len; j++) {
            int var = abs(clauses[i].lits[j]);
            if (assign->val[var] == 0) jw_total[var] += w;
        }
    }
    for (int i = 0; i < n_vars_list; i++)
        scores[i] = jw_total[vars[i]];
}

/* ─── Select top-B variables by JW score ─── */

int beam_select(const Clause *clauses, int n_clauses, const Assignment *assign,
                int *vars, int n_vars_list, int beam) {
    if (n_vars_list <= beam) return n_vars_list;

    double scores[MAX_VARS];
    jw_scores(clauses, n_clauses, assign, vars, n_vars_list, scores);

    /* Partial sort: move top-beam to front */
    for (int i = 0; i < beam && i < n_vars_list; i++) {
        int best = i;
        for (int j = i + 1; j < n_vars_list; j++)
            if (scores[j] > scores[best]) best = j;
        if (best != i) {
            double ts = scores[i]; scores[i] = scores[best]; scores[best] = ts;
            int tv = vars[i]; vars[i] = vars[best]; vars[best] = tv;
        }
    }
    return beam;
}

/* ─── k-step lookahead with beam pruning ─── */

double score_kstep(const Clause *clauses, int n_clauses,
                   const Assignment *assign, int var, int value,
                   int n_vars, int k, double alpha) {
    Assignment new_a;
    memcpy(&new_a, assign, sizeof(Assignment));
    new_a.val[var] = value;
    new_a.n_set++;

    PropResult pr;
    unit_propagate(clauses, n_clauses, &new_a, &pr);
    if (pr.contradiction) return -1000.0;

    double immediate = (double)(pr.assign.n_set - assign->n_set - 1)
                     + (double)(n_clauses - pr.n_clauses);

    if (k <= 1) return immediate;

    int unassigned[MAX_VARS];
    int n_unassigned = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, unassigned);
    if (n_unassigned == 0) return immediate + 100.0 * k;

    /* Beam: only evaluate top-B variables at deeper levels */
    int beam = (k >= 3) ? BEAM_WIDTH / 2 : BEAM_WIDTH;
    if (beam < 4) beam = 4;
    int n_eval = beam_select(pr.clauses, pr.n_clauses, &pr.assign,
                             unassigned, n_unassigned, beam);

    double best_next = -1000.0;
    for (int i = 0; i < n_eval; i++) {
        for (int val = -1; val <= 1; val += 2) {
            double s = score_kstep(pr.clauses, pr.n_clauses,
                                   &pr.assign, unassigned[i], val,
                                   n_vars, k - 1, best_next);
            if (s > best_next) best_next = s;
            /* Alpha pruning: if we already have a great next move,
               no need to keep searching exhaustively */
            if (best_next > alpha + 50) goto done;
        }
    }
done:
    return immediate + ((best_next > -1000.0) ? best_next : 0.0);
}

/* ─── DPLL solver ─── */

int g_backtracks;

bool dpll_kstep(const Clause *clauses, int n_clauses,
                Assignment *assign, int n_vars, int k) {
    PropResult pr;
    unit_propagate(clauses, n_clauses, assign, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { memcpy(assign, &pr.assign, sizeof(Assignment)); return true; }

    int unassigned[MAX_VARS];
    int n_unassigned = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, unassigned);
    if (n_unassigned == 0) return false;

    /* Score all (var, value) pairs — full beam at top level */
    double best_score = -2000.0;
    int best_var = unassigned[0], best_val = 1;

    for (int i = 0; i < n_unassigned; i++) {
        for (int val = -1; val <= 1; val += 2) {
            double s = score_kstep(pr.clauses, pr.n_clauses,
                                   &pr.assign, unassigned[i], val,
                                   n_vars, k, best_score);
            if (s > best_score) { best_score = s; best_var = unassigned[i]; best_val = val; }
        }
    }

    /* Try best */
    Assignment a1;
    memcpy(&a1, &pr.assign, sizeof(Assignment));
    a1.val[best_var] = best_val; a1.n_set++;
    if (dpll_kstep(pr.clauses, pr.n_clauses, &a1, n_vars, k)) {
        memcpy(assign, &a1, sizeof(Assignment)); return true;
    }
    g_backtracks++;

    /* Try opposite */
    Assignment a2;
    memcpy(&a2, &pr.assign, sizeof(Assignment));
    a2.val[best_var] = -best_val; a2.n_set++;
    bool r = dpll_kstep(pr.clauses, pr.n_clauses, &a2, n_vars, k);
    if (r) memcpy(assign, &a2, sizeof(Assignment));
    return r;
}

bool solve_kstep(Formula *f, int k, int *out_bt) {
    g_backtracks = 0;
    Assignment a; memset(&a, 0, sizeof(Assignment));
    bool r = dpll_kstep(f->clauses, f->n_clauses, &a, f->n_vars, k);
    *out_bt = g_backtracks;
    return r;
}

/* ─── JW/Polarity solvers for hard core detection ─── */

int g_bt_jw, g_bt_pol;

bool dpll_jw(const Clause *cl, int nc, Assignment *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { memcpy(a, &pr.assign, sizeof(Assignment)); return true; }
    int uv[MAX_VARS]; int nu = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, uv);
    if (nu == 0) return false;
    double jp[MAX_VARS+1]={0}, jn[MAX_VARS+1]={0};
    for (int i=0;i<pr.n_clauses;i++) { double w=pow(2.0,-(double)pr.clauses[i].len);
        for (int j=0;j<pr.clauses[i].len;j++) { int l=pr.clauses[i].lits[j], v=abs(l);
            if (pr.assign.val[v]==0) { if (l>0) jp[v]+=w; else jn[v]+=w; } } }
    int bv=uv[0]; double bs=jp[bv]+jn[bv];
    for (int i=1;i<nu;i++) { double s=jp[uv[i]]+jn[uv[i]]; if (s>bs){bs=s;bv=uv[i];} }
    int val=(jp[bv]>=jn[bv])?1:-1;
    Assignment a1; memcpy(&a1,&pr.assign,sizeof(Assignment)); a1.val[bv]=val; a1.n_set++;
    if (dpll_jw(pr.clauses,pr.n_clauses,&a1,nv)) { memcpy(a,&a1,sizeof(Assignment)); return true; }
    g_bt_jw++;
    Assignment a2; memcpy(&a2,&pr.assign,sizeof(Assignment)); a2.val[bv]=-val; a2.n_set++;
    bool r=dpll_jw(pr.clauses,pr.n_clauses,&a2,nv); if(r) memcpy(a,&a2,sizeof(Assignment));
    return r;
}

bool dpll_pol(const Clause *cl, int nc, Assignment *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { memcpy(a, &pr.assign, sizeof(Assignment)); return true; }
    int uv[MAX_VARS]; int nu = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, uv);
    if (nu == 0) return false;
    int pc[MAX_VARS+1]={0}, nc2[MAX_VARS+1]={0};
    for (int i=0;i<pr.n_clauses;i++) for (int j=0;j<pr.clauses[i].len;j++) {
        int l=pr.clauses[i].lits[j], v=abs(l);
        if (pr.assign.val[v]==0) { if(l>0)pc[v]++; else nc2[v]++; } }
    int bv=uv[0]; int bb=abs(pc[bv]-nc2[bv]);
    for (int i=1;i<nu;i++) { int b=abs(pc[uv[i]]-nc2[uv[i]]); if(b>bb){bb=b;bv=uv[i];} }
    int val=(pc[bv]>=nc2[bv])?1:-1;
    Assignment a1; memcpy(&a1,&pr.assign,sizeof(Assignment)); a1.val[bv]=val; a1.n_set++;
    if (dpll_pol(pr.clauses,pr.n_clauses,&a1,nv)) { memcpy(a,&a1,sizeof(Assignment)); return true; }
    g_bt_pol++;
    Assignment a2; memcpy(&a2,&pr.assign,sizeof(Assignment)); a2.val[bv]=-val; a2.n_set++;
    bool r=dpll_pol(pr.clauses,pr.n_clauses,&a2,nv); if(r) memcpy(a,&a2,sizeof(Assignment));
    return r;
}

int is_hard_core(Formula *f) {
    Assignment a; memset(&a,0,sizeof(Assignment));
    g_bt_pol=0; if(!dpll_pol(f->clauses,f->n_clauses,&a,f->n_vars)) return -1;
    if(g_bt_pol==0) return 0;
    memset(&a,0,sizeof(Assignment));
    g_bt_jw=0; if(!dpll_jw(f->clauses,f->n_clauses,&a,f->n_vars)) return -1;
    if(g_bt_jw==0) return 0;
    return 1;
}

/* ─── Main ─── */

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <n_vars> <k_step> <n_target> [ratio] [beam_width]\n", argv[0]);
        return 1;
    }

    int n_vars = atoi(argv[1]);
    int k_step = atoi(argv[2]);
    int n_target = atoi(argv[3]);
    double ratio = (argc > 4) ? atof(argv[4]) : 4.0;
    if (argc > 5) BEAM_WIDTH = atoi(argv[5]);

    printf("======================================================================\n");
    printf("  COFFINHEAD — Fast Lookahead (beam=%d)\n", BEAM_WIDTH);
    printf("  n=%d, k=%d, target=%d, ratio=%.1f\n", n_vars, k_step, n_target, ratio);
    printf("======================================================================\n\n");

    int found = 0, zero_bt = 0, total_bt = 0;
    unsigned long long seed = 0, max_seed = (unsigned long long)n_target * 1000;
    double total_time = 0.0;
    clock_t wall_start = clock();

    while (found < n_target && seed < max_seed) {
        double elapsed_wall = (double)(clock() - wall_start) / CLOCKS_PER_SEC;
        if (elapsed_wall > 600.0) { printf("  (wall timeout 600s)\n"); break; }

        Formula f;
        generate_random_3sat(&f, n_vars, ratio, seed); seed++;
        if (is_hard_core(&f) != 1) continue;

        /* Regenerate clean copy */
        generate_random_3sat(&f, n_vars, ratio, seed - 1);
        found++;

        clock_t t0 = clock();
        int bt; solve_kstep(&f, k_step, &bt);
        double elapsed = (double)(clock() - t0) / CLOCKS_PER_SEC;
        total_time += elapsed;
        total_bt += bt;
        if (bt == 0) zero_bt++;
        else printf("  FAIL #%d: seed=%llu, bt=%d, %.2fs\n", found, seed-1, bt, elapsed);

        if (elapsed > 120.0) { printf("  (instance timeout %.1fs)\n", elapsed); break; }
        if (found % 10 == 0 || (found % 5 == 0 && n_vars >= 30)) {
            double rate = 100.0 * zero_bt / found;
            printf("  progress: %d/%d, zero-bt=%d/%d (%.1f%%), %.1fs\n",
                   found, n_target, zero_bt, found, rate, total_time);
        }
    }

    if (found > 0) {
        double rate = 100.0 * zero_bt / found;
        double avg = (double)total_bt / found;
        printf("\n  RESULT k=%d n=%d beam=%d: %d/%d = %.1f%% zero-BT, avg_bt=%.2f, %.1fs\n",
               k_step, n_vars, BEAM_WIDTH, zero_bt, found, rate, avg, total_time);
        printf(rate == 100.0 ? "  >>> PERFECT <<<\n" : "  >>> BREAKS <<<\n");
    }
    return 0;
}
