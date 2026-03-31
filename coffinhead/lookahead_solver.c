/*
 * THE COFFINHEAD CONJECTURE — Fast k-Step Lookahead SAT Solver
 * =============================================================
 * C rewrite of phase9b/9c Python code for 10-100x speedup.
 * Goal: test k=3,4 at n=25-50 on hard core instances.
 *
 * Build: gcc -O3 -o lookahead_solver lookahead_solver.c -lm
 * Usage: ./lookahead_solver <n_vars> <k_step> <n_target> [ratio]
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

/* Assignment: 0=unset, 1=true, -1=false */
typedef struct {
    int val[MAX_VARS + 1];  /* 1-indexed */
    int n_set;
} Assignment;

/* ─── RNG (xorshift64) ─── */

static unsigned long long rng_state;

void rng_seed(unsigned long long s) {
    rng_state = s ? s : 1;
}

unsigned long long rng_next(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return rng_state;
}

int rng_int(int n) {
    return (int)(rng_next() % (unsigned long long)n);
}

/* ─── Formula generation ─── */

void generate_random_3sat(Formula *f, int n_vars, double ratio, unsigned long long seed) {
    rng_seed(seed);
    f->n_vars = n_vars;
    f->n_clauses = (int)(n_vars * ratio);
    if (f->n_clauses > MAX_CLAUSES) f->n_clauses = MAX_CLAUSES;

    for (int i = 0; i < f->n_clauses; i++) {
        f->clauses[i].len = (n_vars >= 3) ? 3 : n_vars;
        /* Sample 3 distinct variables */
        int vars[3];
        for (int j = 0; j < f->clauses[i].len; j++) {
            int v;
            bool dup;
            do {
                v = 1 + rng_int(n_vars);
                dup = false;
                for (int k = 0; k < j; k++)
                    if (abs(vars[k]) == v) { dup = true; break; }
            } while (dup);
            vars[j] = (rng_next() & 1) ? v : -v;
        }
        for (int j = 0; j < f->clauses[i].len; j++)
            f->clauses[i].lits[j] = vars[j];
    }
}

/* ─── Unit propagation ─── */

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

    /* Copy clauses */
    memcpy(out->clauses, clauses, sizeof(Clause) * n_clauses);
    out->n_clauses = n_clauses;

    bool changed = true;
    while (changed) {
        changed = false;
        int new_count = 0;
        for (int i = 0; i < out->n_clauses; i++) {
            Clause *c = &out->clauses[i];
            int simplified[MAX_LIT];
            int slen = 0;
            bool satisfied = false;

            for (int j = 0; j < c->len; j++) {
                int lit = c->lits[j];
                int var = abs(lit);
                int aval = out->assign.val[var];
                if (aval != 0) {
                    bool is_true = (lit > 0 && aval == 1) || (lit < 0 && aval == -1);
                    if (is_true) { satisfied = true; break; }
                    /* else: literal is false, skip it */
                } else {
                    simplified[slen++] = lit;
                }
            }

            if (satisfied) continue;

            if (slen == 0) {
                out->contradiction = true;
                return;
            }

            if (slen == 1) {
                int lit = simplified[0];
                int var = abs(lit);
                int val = (lit > 0) ? 1 : -1;
                if (out->assign.val[var] != 0 && out->assign.val[var] != val) {
                    out->contradiction = true;
                    return;
                }
                if (out->assign.val[var] == 0) {
                    out->assign.val[var] = val;
                    out->assign.n_set++;
                    changed = true;
                }
            }

            /* Keep this clause */
            Clause *nc = &out->clauses[new_count];
            if (nc != c) {
                nc->len = slen;
                for (int j = 0; j < slen; j++) nc->lits[j] = simplified[j];
            } else {
                nc->len = slen;
                for (int j = 0; j < slen; j++) nc->lits[j] = simplified[j];
            }
            new_count++;
        }
        out->n_clauses = new_count;
    }
}

/* ─── Get unassigned variables in remaining clauses ─── */

int get_unassigned(const Clause *clauses, int n_clauses,
                   const Assignment *assign, int *out_vars) {
    bool seen[MAX_VARS + 1] = {false};
    int count = 0;
    for (int i = 0; i < n_clauses; i++) {
        for (int j = 0; j < clauses[i].len; j++) {
            int var = abs(clauses[i].lits[j]);
            if (assign->val[var] == 0 && !seen[var]) {
                seen[var] = true;
                out_vars[count++] = var;
            }
        }
    }
    return count;
}

/* ─── k-step lookahead scoring ─── */

double score_kstep(const Clause *clauses, int n_clauses,
                   const Assignment *assign, int var, int value, int n_vars, int k) {
    /* Set var=value, propagate */
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

    double best_next = -1000.0;
    for (int i = 0; i < n_unassigned; i++) {
        for (int val = -1; val <= 1; val += 2) {
            double s = score_kstep(pr.clauses, pr.n_clauses,
                                   &pr.assign, unassigned[i], val, n_vars, k - 1);
            if (s > best_next) best_next = s;
        }
    }

    return immediate + ((best_next > -1000.0) ? best_next : 0.0);
}

/* ─── DPLL with k-step lookahead ─── */

int g_backtracks;

bool dpll_kstep(const Clause *clauses, int n_clauses,
                Assignment *assign, int n_vars, int k) {
    PropResult pr;
    unit_propagate(clauses, n_clauses, assign, &pr);

    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) {
        memcpy(assign, &pr.assign, sizeof(Assignment));
        return true;
    }

    int unassigned[MAX_VARS];
    int n_unassigned = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, unassigned);
    if (n_unassigned == 0) return false;

    /* Score all (var, value) pairs */
    double best_score = -2000.0;
    int best_var = unassigned[0];
    int best_val = 1;

    for (int i = 0; i < n_unassigned; i++) {
        for (int val = -1; val <= 1; val += 2) {
            double s = score_kstep(pr.clauses, pr.n_clauses,
                                   &pr.assign, unassigned[i], val, n_vars, k);
            if (s > best_score) {
                best_score = s;
                best_var = unassigned[i];
                best_val = val;
            }
        }
    }

    /* Try best choice */
    Assignment a1;
    memcpy(&a1, &pr.assign, sizeof(Assignment));
    a1.val[best_var] = best_val;
    a1.n_set++;

    /* Deep copy clauses for recursion */
    Clause *cl_copy = malloc(sizeof(Clause) * pr.n_clauses);
    memcpy(cl_copy, pr.clauses, sizeof(Clause) * pr.n_clauses);

    if (dpll_kstep(cl_copy, pr.n_clauses, &a1, n_vars, k)) {
        memcpy(assign, &a1, sizeof(Assignment));
        free(cl_copy);
        return true;
    }

    g_backtracks++;

    /* Try opposite */
    Assignment a2;
    memcpy(&a2, &pr.assign, sizeof(Assignment));
    a2.val[best_var] = -best_val;
    a2.n_set++;

    memcpy(cl_copy, pr.clauses, sizeof(Clause) * pr.n_clauses);
    bool result = dpll_kstep(cl_copy, pr.n_clauses, &a2, n_vars, k);
    if (result) memcpy(assign, &a2, sizeof(Assignment));
    free(cl_copy);
    return result;
}

bool solve_kstep(Formula *f, int k, int *out_backtracks) {
    g_backtracks = 0;
    Assignment assign;
    memset(&assign, 0, sizeof(Assignment));

    bool result = dpll_kstep(f->clauses, f->n_clauses, &assign, f->n_vars, k);
    *out_backtracks = g_backtracks;
    return result;
}

/* ─── Adaptive JW solver (for hard core detection) ─── */

int g_bt_jw;

bool dpll_jw(const Clause *clauses, int n_clauses, Assignment *assign, int n_vars) {
    PropResult pr;
    unit_propagate(clauses, n_clauses, assign, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { memcpy(assign, &pr.assign, sizeof(Assignment)); return true; }

    int unassigned[MAX_VARS];
    int n_unassigned = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, unassigned);
    if (n_unassigned == 0) return false;

    double jw_pos[MAX_VARS + 1] = {0}, jw_neg[MAX_VARS + 1] = {0};
    for (int i = 0; i < pr.n_clauses; i++) {
        double w = pow(2.0, -(double)pr.clauses[i].len);
        for (int j = 0; j < pr.clauses[i].len; j++) {
            int lit = pr.clauses[i].lits[j];
            int var = abs(lit);
            if (pr.assign.val[var] == 0) {
                if (lit > 0) jw_pos[var] += w;
                else jw_neg[var] += w;
            }
        }
    }

    int bv = unassigned[0];
    double best = jw_pos[bv] + jw_neg[bv];
    for (int i = 1; i < n_unassigned; i++) {
        double score = jw_pos[unassigned[i]] + jw_neg[unassigned[i]];
        if (score > best) { best = score; bv = unassigned[i]; }
    }
    int val = (jw_pos[bv] >= jw_neg[bv]) ? 1 : -1;

    Assignment a1;
    memcpy(&a1, &pr.assign, sizeof(Assignment));
    a1.val[bv] = val; a1.n_set++;

    Clause *cl = malloc(sizeof(Clause) * pr.n_clauses);
    memcpy(cl, pr.clauses, sizeof(Clause) * pr.n_clauses);
    if (dpll_jw(cl, pr.n_clauses, &a1, n_vars)) {
        memcpy(assign, &a1, sizeof(Assignment));
        free(cl);
        return true;
    }
    g_bt_jw++;

    Assignment a2;
    memcpy(&a2, &pr.assign, sizeof(Assignment));
    a2.val[bv] = -val; a2.n_set++;
    memcpy(cl, pr.clauses, sizeof(Clause) * pr.n_clauses);
    bool r = dpll_jw(cl, pr.n_clauses, &a2, n_vars);
    if (r) memcpy(assign, &a2, sizeof(Assignment));
    free(cl);
    return r;
}

/* ─── Adaptive Polarity solver ─── */

int g_bt_pol;

bool dpll_pol(const Clause *clauses, int n_clauses, Assignment *assign, int n_vars) {
    PropResult pr;
    unit_propagate(clauses, n_clauses, assign, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { memcpy(assign, &pr.assign, sizeof(Assignment)); return true; }

    int unassigned[MAX_VARS];
    int n_unassigned = get_unassigned(pr.clauses, pr.n_clauses, &pr.assign, unassigned);
    if (n_unassigned == 0) return false;

    int pos_count[MAX_VARS + 1] = {0}, neg_count[MAX_VARS + 1] = {0};
    for (int i = 0; i < pr.n_clauses; i++) {
        for (int j = 0; j < pr.clauses[i].len; j++) {
            int lit = pr.clauses[i].lits[j];
            int var = abs(lit);
            if (pr.assign.val[var] == 0) {
                if (lit > 0) pos_count[var]++;
                else neg_count[var]++;
            }
        }
    }

    int bv = unassigned[0];
    int best_bias = abs(pos_count[bv] - neg_count[bv]);
    for (int i = 1; i < n_unassigned; i++) {
        int v = unassigned[i];
        int bias = abs(pos_count[v] - neg_count[v]);
        if (bias > best_bias) { best_bias = bias; bv = v; }
    }
    int val = (pos_count[bv] >= neg_count[bv]) ? 1 : -1;

    Assignment a1;
    memcpy(&a1, &pr.assign, sizeof(Assignment));
    a1.val[bv] = val; a1.n_set++;

    Clause *cl = malloc(sizeof(Clause) * pr.n_clauses);
    memcpy(cl, pr.clauses, sizeof(Clause) * pr.n_clauses);
    if (dpll_pol(cl, pr.n_clauses, &a1, n_vars)) {
        memcpy(assign, &a1, sizeof(Assignment));
        free(cl);
        return true;
    }
    g_bt_pol++;

    Assignment a2;
    memcpy(&a2, &pr.assign, sizeof(Assignment));
    a2.val[bv] = -val; a2.n_set++;
    memcpy(cl, pr.clauses, sizeof(Clause) * pr.n_clauses);
    bool r = dpll_pol(cl, pr.n_clauses, &a2, n_vars);
    if (r) memcpy(assign, &a2, sizeof(Assignment));
    free(cl);
    return r;
}

/* ─── Hard core detection ─── */

int is_hard_core(Formula *f) {
    /* Returns: -1=UNSAT, 0=easy, 1=hard core */
    Assignment a;

    /* Polarity solver */
    memset(&a, 0, sizeof(Assignment));
    g_bt_pol = 0;
    bool sat = dpll_pol(f->clauses, f->n_clauses, &a, f->n_vars);
    if (!sat) return -1;
    if (g_bt_pol == 0) return 0;

    /* JW solver */
    memset(&a, 0, sizeof(Assignment));
    g_bt_jw = 0;
    sat = dpll_jw(f->clauses, f->n_clauses, &a, f->n_vars);
    if (!sat) return -1;
    if (g_bt_jw == 0) return 0;

    return 1;
}

/* ─── Main experiment ─── */

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <n_vars> <k_step> <n_target> [ratio] [max_k]\n", argv[0]);
        fprintf(stderr, "\nModes:\n");
        fprintf(stderr, "  Single k: %s 25 3 30 4.0\n", argv[0]);
        fprintf(stderr, "  Sweep k:  %s 25 1 30 4.0 4   (tests k=1..4)\n", argv[0]);
        return 1;
    }

    int n_vars = atoi(argv[1]);
    int k_step = atoi(argv[2]);
    int n_target = atoi(argv[3]);
    double ratio = (argc > 4) ? atof(argv[4]) : 4.0;
    int max_k = (argc > 5) ? atoi(argv[5]) : k_step;  /* sweep mode if max_k > k_step */

    printf("======================================================================\n");
    printf("  COFFINHEAD CONJECTURE — C Lookahead Solver\n");
    printf("  n=%d, k=%d..%d, target=%d hard core instances, ratio=%.1f\n",
           n_vars, k_step, max_k, n_target, ratio);
    printf("======================================================================\n\n");

    for (int k = k_step; k <= max_k; k++) {
        printf("--- k=%d-step lookahead on hard core (n=%d) ---\n", k, n_vars);

        int found = 0, zero_bt = 0, total_bt = 0;
        unsigned long long seed = 0;
        unsigned long long max_seed = (unsigned long long)n_target * 1000;
        double total_time = 0.0;

        clock_t wall_start = clock();

        while (found < n_target && seed < max_seed) {
            /* Time limit: 600s per k */
            double elapsed_wall = (double)(clock() - wall_start) / CLOCKS_PER_SEC;
            if (elapsed_wall > 600.0) {
                printf("  (timeout after %.0fs)\n", elapsed_wall);
                break;
            }

            Formula f;
            generate_random_3sat(&f, n_vars, ratio, seed);
            seed++;

            int hc = is_hard_core(&f);
            if (hc != 1) continue;
            found++;

            /* Re-generate (since solvers modified clauses via malloc copies) */
            generate_random_3sat(&f, n_vars, ratio, seed - 1);

            clock_t t0 = clock();
            int bt;
            bool sat = solve_kstep(&f, k, &bt);
            double elapsed = (double)(clock() - t0) / CLOCKS_PER_SEC;
            total_time += elapsed;
            total_bt += bt;

            if (bt == 0) {
                zero_bt++;
            } else {
                printf("  FAIL #%d: seed=%llu, bt=%d, %.2fs\n", found, seed - 1, bt, elapsed);
            }

            /* Per-instance timeout */
            if (elapsed > 60.0) {
                printf("  (single instance too slow: %.1fs)\n", elapsed);
                break;
            }

            if (found % 10 == 0) {
                double rate = 100.0 * zero_bt / found;
                printf("  progress: %d/%d, zero-bt=%d/%d (%.1f%%), %.1fs\n",
                       found, n_target, zero_bt, found, rate, total_time);
            }
        }

        if (found > 0) {
            double rate = 100.0 * zero_bt / found;
            double avg_bt = (double)total_bt / found;
            printf("\n  k=%d RESULT (n=%d): %d/%d = %.1f%% zero-BT, avg_bt=%.2f, %.1fs total\n",
                   k, n_vars, zero_bt, found, rate, avg_bt, total_time);
            if (rate == 100.0)
                printf("  >>> PERFECT <<<\n");
            else
                printf("  >>> BREAKS (%.1f%% failure rate) <<<\n", 100.0 - rate);
        } else {
            printf("  No hard core instances found in %llu attempts\n", seed);
        }
        printf("\n");
    }

    return 0;
}
