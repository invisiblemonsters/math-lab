/*
 * CDCL Hard-Core Tester
 * =====================
 * Generates hard-core random 3-SAT instances and outputs them as DIMACS CNF
 * files for testing with CaDiCaL/Kissat.
 *
 * Two modes:
 *   dump:  output a single instance as DIMACS to stdout
 *   batch: generate N hard-core instances as files in a directory
 *
 * Build: gcc -O3 -march=native -o cdcl_test cdcl_test.c -lm
 * Usage:
 *   ./cdcl_test dump <n_vars> <seed>              # single DIMACS to stdout
 *   ./cdcl_test batch <n_vars> <count> <outdir>    # batch generate
 *   ./cdcl_test seeds <n_vars> <count>             # list hard-core seeds
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>

#define MAX_VARS 256
#define MAX_WORDS 4
#define MAX_CLAUSES 1200

typedef uint64_t BV[MAX_WORDS];
static int NW;

static inline void bv_zero_out(BV r) { for (int i=0;i<NW;i++) r[i]=0; }
static inline void bv_copy(BV d, const BV s) { for (int i=0;i<NW;i++) d[i]=s[i]; }
static inline void bv_set_bit(BV r, int b) { r[b/64] |= (uint64_t)1<<(b%64); }
static inline bool bv_test_bit(const BV r, int b) { return (r[b/64]>>(b%64))&1; }
static inline void bv_clear_bit_inplace(BV r, int b) { r[b/64] &= ~((uint64_t)1<<(b%64)); }
static inline bool bv_is_zero(const BV a) { for (int i=0;i<NW;i++) if(a[i]) return false; return true; }
static inline void bv_or_into(BV d, const BV s) { for (int i=0;i<NW;i++) d[i]|=s[i]; }
static inline bool bv_and_nonzero(const BV a, const BV b) { for (int i=0;i<NW;i++) if(a[i]&b[i]) return true; return false; }
static inline void bv_andnot(BV d, const BV a, const BV b) { for (int i=0;i<NW;i++) d[i]=a[i]&~b[i]; }
static inline void bv_or(BV d, const BV a, const BV b) { for (int i=0;i<NW;i++) d[i]=a[i]|b[i]; }
static inline int bv_popcount(const BV a) { int c=0; for (int i=0;i<NW;i++) c+=__builtin_popcountll(a[i]); return c; }
static inline int bv_lowest(const BV a) { for (int i=0;i<NW;i++) if(a[i]) return i*64+__builtin_ctzll(a[i]); return -1; }
static inline int bv_next(BV m) { int b=bv_lowest(m); bv_clear_bit_inplace(m,b); return b; }

typedef struct { BV pos; BV neg; } BClause;
typedef struct { BClause clauses[MAX_CLAUSES]; int n_clauses; int n_vars; } Formula;
typedef struct { BV t_mask; BV f_mask; int n_set; } BAssign;
typedef struct { BAssign assign; BClause clauses[MAX_CLAUSES]; int n_clauses; bool contradiction; } PropResult;

static unsigned long long rng_state;
void rng_seed(unsigned long long s) { rng_state=s?s:1; }
unsigned long long rng_next(void) { rng_state^=rng_state<<13; rng_state^=rng_state>>7; rng_state^=rng_state<<17; return rng_state; }
int rng_int(int n) { return (int)(rng_next()%(unsigned long long)n); }

/* Store raw clause data for DIMACS output */
int raw_clauses[MAX_CLAUSES][3]; /* 1-indexed, negative = negated */
int raw_n_clauses;

void generate_random_3sat(Formula *f, int n_vars, double ratio, unsigned long long seed) {
    rng_seed(seed);
    f->n_vars = n_vars;
    f->n_clauses = (int)(n_vars * ratio);
    if (f->n_clauses > MAX_CLAUSES) f->n_clauses = MAX_CLAUSES;
    raw_n_clauses = f->n_clauses;
    for (int i = 0; i < f->n_clauses; i++) {
        bv_zero_out(f->clauses[i].pos); bv_zero_out(f->clauses[i].neg);
        int vars[3];
        for (int j = 0; j < 3; j++) {
            int v; bool dup;
            do { v = 1 + rng_int(n_vars); dup = false;
                 for (int k = 0; k < j; k++) if (vars[k] == v) { dup = true; break; }
            } while (dup);
            vars[j] = v;
            if (rng_next() & 1) {
                bv_set_bit(f->clauses[i].pos, v-1);
                raw_clauses[i][j] = v;  /* positive literal */
            } else {
                bv_set_bit(f->clauses[i].neg, v-1);
                raw_clauses[i][j] = -v; /* negative literal */
            }
        }
    }
}

void unit_propagate(const BClause *clauses, int n_clauses, const BAssign *ain, PropResult *out) {
    out->assign = *ain; out->contradiction = false;
    memcpy(out->clauses, clauses, sizeof(BClause)*n_clauses); out->n_clauses = n_clauses;
    bool changed = true;
    while (changed) {
        changed = false; int new_count = 0;
        for (int i = 0; i < out->n_clauses; i++) {
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
                    if (!bv_test_bit(out->assign.t_mask, bit)) { bv_set_bit(out->assign.t_mask, bit); out->assign.n_set++; changed = true; }
                } else {
                    if (bv_test_bit(out->assign.t_mask, bit)) { out->contradiction = true; return; }
                    if (!bv_test_bit(out->assign.f_mask, bit)) { bv_set_bit(out->assign.f_mask, bit); out->assign.n_set++; changed = true; }
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
    BV assigned; bv_zero_out(out);
    for (int i=0;i<n_clauses;i++) { bv_or_into(out,clauses[i].pos); bv_or_into(out,clauses[i].neg); }
    bv_or(assigned, a->t_mask, a->f_mask);
    for (int i=0;i<NW;i++) out[i] &= ~assigned[i];
}

int g_bt_jw, g_bt_pol;

bool dpll_jw(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    BV unassigned; get_unassigned_mask(unassigned, pr.clauses, pr.n_clauses, &pr.assign);
    if (bv_is_zero(unassigned)) return false;
    double jw[MAX_VARS]={0}, jp[MAX_VARS]={0}, jn[MAX_VARS]={0};
    for (int i=0;i<pr.n_clauses;i++) {
        BV both; bv_or(both, pr.clauses[i].pos, pr.clauses[i].neg);
        double w = pow(2.0,-(double)bv_popcount(both));
        BV p,n; bv_copy(p,pr.clauses[i].pos); bv_copy(n,pr.clauses[i].neg);
        while (!bv_is_zero(p)) { int b=bv_next(p); jw[b]+=w; jp[b]+=w; }
        while (!bv_is_zero(n)) { int b=bv_next(n); jw[b]+=w; jn[b]+=w; }
    }
    int bb=bv_lowest(unassigned); double bs=-1;
    BV t; bv_copy(t,unassigned);
    while (!bv_is_zero(t)) { int b=bv_next(t); if(jw[b]>bs){bs=jw[b];bb=b;} }
    bool val=jp[bb]>=jn[bb];
    BAssign a1=pr.assign;
    if(val) bv_set_bit(a1.t_mask,bb); else bv_set_bit(a1.f_mask,bb); a1.n_set++;
    if(dpll_jw(pr.clauses,pr.n_clauses,&a1,nv)){*a=a1;return true;}
    g_bt_jw++;
    BAssign a2=pr.assign;
    if(!val) bv_set_bit(a2.t_mask,bb); else bv_set_bit(a2.f_mask,bb); a2.n_set++;
    bool r=dpll_jw(pr.clauses,pr.n_clauses,&a2,nv); if(r)*a=a2; return r;
}

bool dpll_pol(const BClause *cl, int nc, BAssign *a, int nv) {
    PropResult pr; unit_propagate(cl, nc, a, &pr);
    if (pr.contradiction) return false;
    if (pr.n_clauses == 0) { *a = pr.assign; return true; }
    BV unassigned; get_unassigned_mask(unassigned, pr.clauses, pr.n_clauses, &pr.assign);
    if (bv_is_zero(unassigned)) return false;
    int pc[MAX_VARS]={0}, nc2[MAX_VARS]={0};
    for (int i=0;i<pr.n_clauses;i++) {
        BV p,n; bv_copy(p,pr.clauses[i].pos); bv_copy(n,pr.clauses[i].neg);
        while (!bv_is_zero(p)) { pc[bv_next(p)]++; }
        while (!bv_is_zero(n)) { nc2[bv_next(n)]++; }
    }
    int bb=bv_lowest(unassigned); int bbias=-1;
    BV t; bv_copy(t,unassigned);
    while (!bv_is_zero(t)) { int b=bv_next(t); int bi=abs(pc[b]-nc2[b]); if(bi>bbias){bbias=bi;bb=b;} }
    bool val=pc[bb]>=nc2[bb];
    BAssign a1=pr.assign;
    if(val) bv_set_bit(a1.t_mask,bb); else bv_set_bit(a1.f_mask,bb); a1.n_set++;
    if(dpll_pol(pr.clauses,pr.n_clauses,&a1,nv)){*a=a1;return true;}
    g_bt_pol++;
    BAssign a2=pr.assign;
    if(!val) bv_set_bit(a2.t_mask,bb); else bv_set_bit(a2.f_mask,bb); a2.n_set++;
    bool r=dpll_pol(pr.clauses,pr.n_clauses,&a2,nv); if(r)*a=a2; return r;
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

void print_dimacs(Formula *f) {
    printf("c Coffinhead hard-core instance n=%d ratio=4.0\n", f->n_vars);
    printf("p cnf %d %d\n", f->n_vars, f->n_clauses);
    for (int i = 0; i < f->n_clauses; i++) {
        printf("%d %d %d 0\n", raw_clauses[i][0], raw_clauses[i][1], raw_clauses[i][2]);
    }
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s dump <n_vars> <seed>           # DIMACS to stdout\n", argv[0]);
        fprintf(stderr, "  %s batch <n_vars> <count> <dir>   # batch generate files\n", argv[0]);
        fprintf(stderr, "  %s seeds <n_vars> <count>         # list hard-core seeds\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "dump") == 0 && argc >= 4) {
        int n = atoi(argv[2]);
        unsigned long long seed = atoll(argv[3]);
        NW = (n+63)/64;
        Formula f;
        generate_random_3sat(&f, n, 4.0, seed);
        if (is_hard_core(&f) != 1) {
            fprintf(stderr, "Seed %llu is not hard-core at n=%d\n", seed, n);
            return 1;
        }
        generate_random_3sat(&f, n, 4.0, seed); /* regenerate to get raw_clauses */
        print_dimacs(&f);
        return 0;
    }

    if (strcmp(argv[1], "seeds") == 0 && argc >= 4) {
        int n = atoi(argv[2]);
        int count = atoi(argv[3]);
        NW = (n+63)/64;
        int found = 0;
        for (unsigned long long seed = 0; found < count && seed < (unsigned long long)count * 2000; seed++) {
            Formula f;
            generate_random_3sat(&f, n, 4.0, seed);
            int hc = is_hard_core(&f);
            if (hc == 1) {
                printf("%llu\n", seed);
                found++;
            }
        }
        fprintf(stderr, "Found %d hard-core seeds at n=%d\n", found, n);
        return 0;
    }

    if (strcmp(argv[1], "batch") == 0 && argc >= 5) {
        int n = atoi(argv[2]);
        int count = atoi(argv[3]);
        const char *dir = argv[4];
        NW = (n+63)/64;

        char cmd[512];
        snprintf(cmd, sizeof(cmd), "mkdir -p %s", dir);
        system(cmd);

        int found = 0;
        for (unsigned long long seed = 0; found < count && seed < (unsigned long long)count * 2000; seed++) {
            Formula f;
            generate_random_3sat(&f, n, 4.0, seed);
            if (is_hard_core(&f) != 1) continue;
            generate_random_3sat(&f, n, 4.0, seed);

            char fname[512];
            snprintf(fname, sizeof(fname), "%s/hc_n%d_s%llu.cnf", dir, n, seed);
            FILE *fp = fopen(fname, "w");
            if (!fp) { perror(fname); continue; }
            fprintf(fp, "c Coffinhead hard-core n=%d seed=%llu ratio=4.0\n", n, seed);
            fprintf(fp, "p cnf %d %d\n", f.n_vars, f.n_clauses);
            for (int i = 0; i < f.n_clauses; i++) {
                fprintf(fp, "%d %d %d 0\n", raw_clauses[i][0], raw_clauses[i][1], raw_clauses[i][2]);
            }
            fclose(fp);
            found++;
            fprintf(stderr, "  Generated %s (seed %llu)\n", fname, seed);
        }
        fprintf(stderr, "Generated %d hard-core instances in %s/\n", found, dir);
        return 0;
    }

    fprintf(stderr, "Unknown command: %s\n", argv[1]);
    return 1;
}
