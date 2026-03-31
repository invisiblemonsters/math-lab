/*
 * COFFINHEAD — k-Step Lookahead on DIMACS CNF files
 * ===================================================
 * Reads standard .cnf files, runs JW/polarity + k-step lookahead.
 * Reports: zero-BT rate, avg backtracks, hard core fraction.
 *
 * Build: gcc -O3 -march=native -fopenmp -o lookahead_cnf lookahead_cnf.c -lm
 * Usage: ./lookahead_cnf <k_step> <file1.cnf> [file2.cnf ...]
 *    or: ./lookahead_cnf <k_step> --dir <directory> [--limit N] [--beam B]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <dirent.h>
#include <omp.h>

typedef unsigned __int128 u128;
#define MAX_VARS    200
#define MAX_CLAUSES 1000

static inline int popcnt128(u128 x) {
    return __builtin_popcountll((uint64_t)x) + __builtin_popcountll((uint64_t)(x >> 64));
}
static inline u128 BIT(int i) { return ((u128)1) << i; }
static inline int lowest_bit(u128 x) {
    uint64_t lo = (uint64_t)x;
    if (lo) return __builtin_ctzll(lo);
    return 64 + __builtin_ctzll((uint64_t)(x >> 64));
}
static inline int next_bit(u128 *mask) {
    int b = lowest_bit(*mask); *mask &= ~BIT(b); return b;
}

typedef struct { u128 pos; u128 neg; } BClause;
typedef struct { BClause clauses[MAX_CLAUSES]; int n_clauses; int n_vars; } Formula;
typedef struct { u128 t_mask; u128 f_mask; int n_set; } BAssign;
typedef struct { BAssign assign; BClause clauses[MAX_CLAUSES]; int n_clauses; bool contradiction; } PropResult;

static int BEAM_WIDTH = 0; /* 0 = exact (no beam) */

/* ─── DIMACS parser ─── */
bool parse_cnf(const char *filename, Formula *f) {
    FILE *fp = fopen(filename, "r");
    if (!fp) return false;
    char line[1024];
    f->n_vars = 0; f->n_clauses = 0;
    int clause_idx = 0;
    while (fgets(line, sizeof(line), fp)) {
        if (line[0] == 'c') continue;
        if (line[0] == 'p') { sscanf(line, "p cnf %d %d", &f->n_vars, &f->n_clauses); continue; }
        if (line[0] == '%') break;
        if (f->n_vars == 0) continue;
        /* Parse clause literals */
        if (clause_idx >= MAX_CLAUSES) continue;
        f->clauses[clause_idx].pos = 0;
        f->clauses[clause_idx].neg = 0;
        char *p = line;
        int lit;
        bool has_lits = false;
        while (sscanf(p, "%d", &lit) == 1) {
            if (lit == 0) break;
            int var = abs(lit);
            if (var > MAX_VARS) { fclose(fp); return false; }
            if (lit > 0) f->clauses[clause_idx].pos |= BIT(var - 1);
            else         f->clauses[clause_idx].neg |= BIT(var - 1);
            has_lits = true;
            while (*p == ' ' || *p == '\t') p++;
            if (*p == '-') p++;
            while (*p >= '0' && *p <= '9') p++;
            while (*p == ' ' || *p == '\t') p++;
        }
        if (has_lits) clause_idx++;
    }
    fclose(fp);
    f->n_clauses = clause_idx;
    return f->n_vars > 0 && f->n_vars <= MAX_VARS;
}

/* ─── Unit propagation ─── */
void unit_propagate(const BClause *clauses, int n_clauses, const BAssign *ain, PropResult *out) {
    out->assign = *ain; out->contradiction = false;
    memcpy(out->clauses, clauses, sizeof(BClause) * n_clauses);
    out->n_clauses = n_clauses;
    bool changed = true;
    while (changed) {
        changed = false; int nc = 0;
        for (int i = 0; i < out->n_clauses; i++) {
            u128 p = out->clauses[i].pos, n = out->clauses[i].neg;
            if ((p & out->assign.t_mask) || (n & out->assign.f_mask)) continue;
            u128 as = out->assign.t_mask | out->assign.f_mask;
            u128 pl = p & ~as, nl = n & ~as, al = pl | nl;
            if (!al) { out->contradiction = true; return; }
            if (popcnt128(al) == 1) {
                int b = lowest_bit(al);
                if (pl & BIT(b)) {
                    if (out->assign.f_mask & BIT(b)) { out->contradiction = true; return; }
                    if (!(out->assign.t_mask & BIT(b))) { out->assign.t_mask |= BIT(b); out->assign.n_set++; changed = true; }
                } else {
                    if (out->assign.t_mask & BIT(b)) { out->contradiction = true; return; }
                    if (!(out->assign.f_mask & BIT(b))) { out->assign.f_mask |= BIT(b); out->assign.n_set++; changed = true; }
                }
            }
            out->clauses[nc].pos = pl; out->clauses[nc].neg = nl; nc++;
        }
        out->n_clauses = nc;
    }
}

u128 get_unassigned_mask(const BClause *c, int nc, const BAssign *a) {
    u128 m = 0; for (int i = 0; i < nc; i++) m |= c[i].pos | c[i].neg;
    return m & ~(a->t_mask | a->f_mask);
}

/* ─── k-step scoring ─── */
double score_kstep(const BClause *clauses, int nc, const BAssign *a, int vb, bool val, int nv, int k) {
    BAssign na = *a;
    if (val) na.t_mask |= BIT(vb); else na.f_mask |= BIT(vb); na.n_set++;
    PropResult pr; unit_propagate(clauses, nc, &na, &pr);
    if (pr.contradiction) return -1000.0;
    double imm = (double)(pr.assign.n_set - a->n_set - 1) + (double)(nc - pr.n_clauses);
    if (k <= 1) return imm;
    u128 un = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!un) return imm + 100.0 * k;

    /* Beam: at deeper levels, only top-B variables */
    int vars[MAX_VARS], nv2 = 0;
    u128 tmp = un; while (tmp) vars[nv2++] = next_bit(&tmp);

    if (BEAM_WIDTH > 0 && nv2 > BEAM_WIDTH) {
        /* JW pre-score for beam selection */
        double jw[MAX_VARS] = {0};
        for (int i = 0; i < pr.n_clauses; i++) {
            int cl = popcnt128(pr.clauses[i].pos | pr.clauses[i].neg);
            double w = pow(2.0, -(double)cl);
            u128 p = pr.clauses[i].pos, n = pr.clauses[i].neg;
            while (p) { jw[next_bit(&p)] += w; }
            while (n) { jw[next_bit(&n)] += w; }
        }
        /* Partial sort top-BEAM */
        for (int i = 0; i < BEAM_WIDTH && i < nv2; i++) {
            int best = i;
            for (int j = i+1; j < nv2; j++)
                if (jw[vars[j]] > jw[vars[best]]) best = j;
            if (best != i) { int t = vars[i]; vars[i] = vars[best]; vars[best] = t; }
        }
        nv2 = BEAM_WIDTH;
    }

    double best = -1000.0;
    for (int i = 0; i < nv2; i++)
        for (int v = 0; v <= 1; v++) {
            double s = score_kstep(pr.clauses, pr.n_clauses, &pr.assign, vars[i], (bool)v, nv, k-1);
            if (s > best) best = s;
        }
    return imm + ((best > -1000.0) ? best : 0.0);
}

/* ─── DPLL solver ─── */
int g_bt;
bool dpll(const BClause *cl, int nc, BAssign *a, int nv, int k) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    u128 un = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!un) return false;
    int cands[MAX_VARS*2]; int cvals[MAX_VARS*2]; int ncand = 0;
    u128 tmp = un;
    while (tmp) { int b = next_bit(&tmp); cands[ncand]=b;cvals[ncand]=1;ncand++; cands[ncand]=b;cvals[ncand]=0;ncand++; }
    double scores[MAX_VARS*2];
    #pragma omp parallel for schedule(dynamic) if(ncand > 8)
    for (int i = 0; i < ncand; i++)
        scores[i] = score_kstep(pr.clauses, pr.n_clauses, &pr.assign, cands[i], (bool)cvals[i], nv, k);
    double bs = -2000.0; int bi = 0;
    for (int i = 0; i < ncand; i++) if (scores[i] > bs) { bs = scores[i]; bi = i; }
    BAssign a1 = pr.assign;
    if (cvals[bi]) a1.t_mask |= BIT(cands[bi]); else a1.f_mask |= BIT(cands[bi]); a1.n_set++;
    if (dpll(pr.clauses, pr.n_clauses, &a1, nv, k)) { *a = a1; return true; }
    g_bt++;
    BAssign a2 = pr.assign;
    if (!cvals[bi]) a2.t_mask |= BIT(cands[bi]); else a2.f_mask |= BIT(cands[bi]); a2.n_set++;
    bool r = dpll(pr.clauses, pr.n_clauses, &a2, nv, k);
    if (r) *a = a2; return r;
}

/* ─── JW solver ─── */
int g_bt_jw;
bool dpll_jw(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    u128 un = get_unassigned_mask(pr.clauses, pr.n_clauses, &pr.assign);
    if (!un) return false;
    double jp[MAX_VARS]={0},jn[MAX_VARS]={0},jt[MAX_VARS]={0};
    for (int i=0;i<pr.n_clauses;i++){int cl2=popcnt128(pr.clauses[i].pos|pr.clauses[i].neg);double w=pow(2.0,-(double)cl2);u128 p=pr.clauses[i].pos,n=pr.clauses[i].neg;while(p){int b=next_bit(&p);jt[b]+=w;jp[b]+=w;}while(n){int b=next_bit(&n);jt[b]+=w;jn[b]+=w;}}
    int bb=lowest_bit(un);double bs=-1;u128 t=un;while(t){int b=next_bit(&t);if(jt[b]>bs){bs=jt[b];bb=b;}}
    bool val=jp[bb]>=jn[bb];
    BAssign a1=pr.assign;if(val)a1.t_mask|=BIT(bb);else a1.f_mask|=BIT(bb);a1.n_set++;
    if(dpll_jw(pr.clauses,pr.n_clauses,&a1,nv)){*a=a1;return true;}g_bt_jw++;
    BAssign a2=pr.assign;if(!val)a2.t_mask|=BIT(bb);else a2.f_mask|=BIT(bb);a2.n_set++;
    bool r=dpll_jw(pr.clauses,pr.n_clauses,&a2,nv);if(r)*a=a2;return r;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <k_step> --dir <directory> [--limit N] [--beam B]\n", argv[0]);
        return 1;
    }
    int k = atoi(argv[1]);
    char *dir = NULL; int limit = 1000;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--dir") && i+1 < argc) dir = argv[++i];
        else if (!strcmp(argv[i], "--limit") && i+1 < argc) limit = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--beam") && i+1 < argc) BEAM_WIDTH = atoi(argv[++i]);
    }
    if (!dir) { fprintf(stderr, "Need --dir\n"); return 1; }

    printf("======================================================================\n");
    printf("  COFFINHEAD on SATLIB — k=%d, beam=%d, dir=%s\n", k, BEAM_WIDTH, dir);
    printf("======================================================================\n\n");

    DIR *d = opendir(dir); if (!d) { perror("opendir"); return 1; }
    struct dirent *ent;
    int total=0, solved=0, hard_core=0, k_zero_bt=0, k_zero_bt_hc=0;
    int total_bt_jw=0, total_bt_k=0;
    double total_time = 0;

    while ((ent = readdir(d)) && total < limit) {
        if (!strstr(ent->d_name, ".cnf")) continue;
        char path[512]; snprintf(path, sizeof(path), "%s/%s", dir, ent->d_name);
        Formula f;
        if (!parse_cnf(path, &f)) continue;
        total++;

        /* JW baseline */
        BAssign a = {0,0,0}; g_bt_jw = 0;
        bool sat = dpll_jw(f.clauses, f.n_clauses, &a, f.n_vars);
        if (!sat) continue; /* skip UNSAT */
        total_bt_jw += g_bt_jw;
        bool is_hc = (g_bt_jw > 0);
        if (is_hc) hard_core++;

        /* k-step lookahead */
        a = (BAssign){0,0,0}; g_bt = 0;
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        sat = dpll(f.clauses, f.n_clauses, &a, f.n_vars, k);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        double elapsed = (t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
        total_time += elapsed;
        total_bt_k += g_bt;

        if (g_bt == 0) {
            k_zero_bt++;
            if (is_hc) k_zero_bt_hc++;
        }

        if (elapsed > 60.0) {
            printf("  TIMEOUT: %s (%.1fs, bt=%d)\n", ent->d_name, elapsed, g_bt);
            break;
        }

        if (total % 100 == 0) {
            printf("  %d files: JW avg_bt=%.1f, k=%d zero-bt=%d/%d (%.1f%%), %.1fs\n",
                   total, (double)total_bt_jw/total, k, k_zero_bt, total, 100.0*k_zero_bt/total, total_time);
        }
    }
    closedir(d);

    printf("\n======================================================================\n");
    printf("  RESULTS: %d instances from %s\n", total, dir);
    printf("======================================================================\n");
    printf("  JW baseline:  avg backtracks = %.2f\n", total > 0 ? (double)total_bt_jw/total : 0);
    printf("  Hard core:    %d/%d (%.1f%%)\n", hard_core, total, total > 0 ? 100.0*hard_core/total : 0);
    printf("  k=%d overall: %d/%d zero-BT (%.1f%%), avg_bt=%.2f\n",
           k, k_zero_bt, total, total > 0 ? 100.0*k_zero_bt/total : 0,
           total > 0 ? (double)total_bt_k/total : 0);
    if (hard_core > 0)
        printf("  k=%d on HC:   %d/%d zero-BT (%.1f%%)\n",
               k, k_zero_bt_hc, hard_core, 100.0*k_zero_bt_hc/hard_core);
    printf("  Total time:   %.1fs\n", total_time);
    return 0;
}
