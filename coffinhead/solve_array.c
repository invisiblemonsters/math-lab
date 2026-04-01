/*
 * COFFINHEAD Array-Based v3 — k-Step Lookahead to Arbitrary n
 * =============================================================
 * Pre-allocated flat buffers per scoring depth. No malloc in hot path.
 * Build: gcc -O3 -march=native -fopenmp -o solve_array solve_array.c -lm
 * Usage: ./solve_array <n> <k> <seed> [beam] [count] [ratio]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <omp.h>

static int NV;
static int NWORDS;
static int BEAM = 0;
static double RATIO = 4.0;
static int MAX_CL;

/* ─── Bitset ops (all operate on uint64_t[NWORDS]) ─── */
#define BS_BYTES     (NWORDS * 8)
#define BS_ZERO(b)   memset((b), 0, BS_BYTES)
#define BS_COPY(d,s) memcpy((d), (s), BS_BYTES)

static inline void bs_or(uint64_t *d, const uint64_t *a, const uint64_t *b) {
    for (int i=0;i<NWORDS;i++) d[i]=a[i]|b[i]; }
static inline void bs_and(uint64_t *d, const uint64_t *a, const uint64_t *b) {
    for (int i=0;i<NWORDS;i++) d[i]=a[i]&b[i]; }
static inline void bs_andnot(uint64_t *d, const uint64_t *a, const uint64_t *m) {
    for (int i=0;i<NWORDS;i++) d[i]=a[i]&~m[i]; }
static inline void bs_or_eq(uint64_t *d, const uint64_t *s) {
    for (int i=0;i<NWORDS;i++) d[i]|=s[i]; }
static inline bool bs_is_zero(const uint64_t *b) {
    for (int i=0;i<NWORDS;i++) if(b[i]) return false; return true; }
static inline void bs_set(uint64_t *b, int p) { b[p>>6]|=1ULL<<(p&63); }
static inline bool bs_tst(const uint64_t *b, int p) { return (b[p>>6]>>(p&63))&1; }
static inline int bs_popcnt(const uint64_t *b) {
    int c=0; for(int i=0;i<NWORDS;i++) c+=__builtin_popcountll(b[i]); return c; }
static inline int bs_lowest(const uint64_t *b) {
    for(int i=0;i<NWORDS;i++) if(b[i]) return (i<<6)+__builtin_ctzll(b[i]); return -1; }
static inline bool bs_singleton(const uint64_t *b) {
    int f=0; for(int i=0;i<NWORDS;i++){if(b[i]){if(f)return false;if(b[i]&(b[i]-1))return false;f=1;}} return f; }
static inline int bs_to_arr(const uint64_t *b, int *out) {
    int c=0; for(int i=0;i<NWORDS;i++){uint64_t w=b[i];while(w){out[c++]=(i<<6)+__builtin_ctzll(w);w&=w-1;}} return c; }

/* ─── RNG ─── */
static unsigned long long rng_s;
static inline void rng_seed(unsigned long long s){rng_s=s?s:1;}
static inline unsigned long long rng_next(void){rng_s^=rng_s<<13;rng_s^=rng_s>>7;rng_s^=rng_s<<17;return rng_s;}
static inline int rng_int(int n){return(int)(rng_next()%(unsigned long long)n);}

/* ─── Formula ─── */
typedef struct { int nv, nc; uint64_t *pos, *neg; } Formula;
#define FP(f,i) ((f)->pos+(i)*NWORDS)
#define FN(f,i) ((f)->neg+(i)*NWORDS)

static Formula fgen(int nv, double r, unsigned long long seed) {
    Formula f; f.nv=nv; f.nc=(int)(nv*r);
    f.pos=calloc(f.nc*NWORDS,8); f.neg=calloc(f.nc*NWORDS,8);
    rng_seed(seed);
    for(int i=0;i<f.nc;i++){
        int vs[3];
        for(int j=0;j<3;j++){int v;bool d;do{v=rng_int(nv);d=false;for(int k=0;k<j;k++)if(vs[k]==v){d=true;break;}}while(d);
        vs[j]=v;if(rng_next()&1)FP(&f,i)[v>>6]|=1ULL<<(v&63);else FN(&f,i)[v>>6]|=1ULL<<(v&63);}
    } return f;
}
static void ffree(Formula *f){free(f->pos);free(f->neg);}

/* ─── Scoring workspace: one set per depth level ─── */
/* Depth 0..K-1 for score_k recursion.
 * Each level has: clause buffer, assignment, temps */
typedef struct {
    uint64_t *cl_p, *cl_n;   /* [MAX_CL * NWORDS] */
    uint64_t *tm, *fm;       /* assignment masks */
    uint64_t *asgn, *pl, *nl, *al, *stmp, *un;  /* temps */
    double *jw;
    int *vars;
} Level;

static Level *levels;  /* allocated for K+1 levels */
static int K;

static void levels_init(int k) {
    K = k;
    levels = malloc((k+2) * sizeof(Level));
    for (int d = 0; d <= k+1; d++) {
        Level *l = &levels[d];
        l->cl_p = malloc(MAX_CL * BS_BYTES);
        l->cl_n = malloc(MAX_CL * BS_BYTES);
        l->tm = malloc(BS_BYTES);
        l->fm = malloc(BS_BYTES);
        l->asgn = malloc(BS_BYTES);
        l->pl = malloc(BS_BYTES);
        l->nl = malloc(BS_BYTES);
        l->al = malloc(BS_BYTES);
        l->stmp = malloc(BS_BYTES);
        l->un = malloc(BS_BYTES);
        l->jw = malloc(NV * sizeof(double));
        l->vars = malloc(NV * sizeof(int));
    }
}

static void levels_free(void) {
    for (int d = 0; d <= K+1; d++) {
        Level *l = &levels[d];
        free(l->cl_p);free(l->cl_n);free(l->tm);free(l->fm);
        free(l->asgn);free(l->pl);free(l->nl);free(l->al);free(l->stmp);free(l->un);
        free(l->jw);free(l->vars);
    }
    free(levels);
}

/* ─── Unit propagation at depth d ─── */
/* Returns remaining clause count, or -1 on contradiction.
 * Output: levels[d].cl_p/cl_n (reduced clauses), levels[d].tm/fm (assignment) */
static int up_at(const uint64_t *ip, const uint64_t *in, int nc,
                 const uint64_t *it, const uint64_t *ifm, int ins, int d, int *ons) {
    Level *l = &levels[d];
    BS_COPY(l->tm, it); BS_COPY(l->fm, ifm); *ons = ins;
    memcpy(l->cl_p, ip, nc*BS_BYTES);
    memcpy(l->cl_n, in, nc*BS_BYTES);

    bool ch = true;
    while (ch) {
        ch = false; bs_or(l->asgn, l->tm, l->fm);
        int nc2 = 0;
        for (int i = 0; i < nc; i++) {
            uint64_t *p = l->cl_p + i*NWORDS;
            uint64_t *n = l->cl_n + i*NWORDS;
            bs_and(l->stmp, p, l->tm); if(!bs_is_zero(l->stmp)) continue;
            bs_and(l->stmp, n, l->fm); if(!bs_is_zero(l->stmp)) continue;
            bs_andnot(l->pl, p, l->asgn);
            bs_andnot(l->nl, n, l->asgn);
            bs_or(l->al, l->pl, l->nl);
            if (bs_is_zero(l->al)) return -1;
            if (bs_singleton(l->al)) {
                int b = bs_lowest(l->al);
                if (bs_tst(l->pl, b)) {
                    if (bs_tst(l->fm, b)) return -1;
                    if (!bs_tst(l->tm, b)) { bs_set(l->tm, b); (*ons)++; ch=true; }
                } else {
                    if (bs_tst(l->tm, b)) return -1;
                    if (!bs_tst(l->fm, b)) { bs_set(l->fm, b); (*ons)++; ch=true; }
                }
            }
            uint64_t *op = l->cl_p + nc2*NWORDS;
            uint64_t *on_ = l->cl_n + nc2*NWORDS;
            BS_COPY(op, l->pl); BS_COPY(on_, l->nl);
            nc2++;
        }
        nc = nc2;
    }
    return nc;
}

/* ─── k-step scoring ─── */
static double score_k(const uint64_t *cp, const uint64_t *cn, int nc,
                       const uint64_t *tm, const uint64_t *fm, int ns,
                       int vb, bool val, int k, int d) {
    Level *l = &levels[d];

    /* Temp assignment: copy into l->un (reuse as temp) then propagate */
    uint64_t *tt = l->un; /* repurpose for the assignment copy */
    /* Actually we need un later. Use a different approach:
     * Copy tm/fm to l->stmp area, modify, then call up_at which copies into l->tm/fm */
    /* Just inline the var set into the up_at call by making a copy */
    /* Simpler: use stack alloc for the small modification */
    uint64_t t_tmp[NWORDS], f_tmp[NWORDS]; /* VLA — ok for reasonable NWORDS */
    memcpy(t_tmp, tm, BS_BYTES);
    memcpy(f_tmp, fm, BS_BYTES);
    if (val) t_tmp[vb>>6] |= 1ULL<<(vb&63);
    else     f_tmp[vb>>6] |= 1ULL<<(vb&63);

    int ons;
    int rnc = up_at(cp, cn, nc, t_tmp, f_tmp, ns+1, d, &ons);
    if (rnc < 0) return -1000.0;

    double imm = (double)(ons - ns - 1) + (double)(nc - rnc);
    if (k <= 1) return imm;
    if (rnc == 0) return imm + 100.0*k;

    /* Unassigned vars in remaining clauses */
    BS_ZERO(l->un);
    bs_or(l->asgn, l->tm, l->fm);
    for (int i = 0; i < rnc; i++) {
        bs_or_eq(l->un, l->cl_p + i*NWORDS);
        bs_or_eq(l->un, l->cl_n + i*NWORDS);
    }
    for (int w = 0; w < NWORDS; w++) l->un[w] &= ~l->asgn[w];
    if (bs_is_zero(l->un)) return imm;

    int nv2 = bs_to_arr(l->un, l->vars);

    /* Beam */
    if (BEAM > 0 && nv2 > BEAM) {
        memset(l->jw, 0, NV*sizeof(double));
        for (int i = 0; i < rnc; i++) {
            uint64_t *lp = l->cl_p + i*NWORDS;
            uint64_t *ln = l->cl_n + i*NWORDS;
            int csz = 0;
            for (int w=0;w<NWORDS;w++) csz += __builtin_popcountll(lp[w]|ln[w]);
            double wt = pow(2.0,-(double)csz);
            for (int w=0;w<NWORDS;w++){
                uint64_t pw=lp[w]; while(pw){l->jw[(w<<6)+__builtin_ctzll(pw)]+=wt;pw&=pw-1;}
                uint64_t nw=ln[w]; while(nw){l->jw[(w<<6)+__builtin_ctzll(nw)]+=wt;nw&=nw-1;}
            }
        }
        for(int i=0;i<BEAM&&i<nv2;i++){int best=i;for(int j=i+1;j<nv2;j++)if(l->jw[l->vars[j]]>l->jw[l->vars[best]])best=j;
            if(best!=i){int t=l->vars[i];l->vars[i]=l->vars[best];l->vars[best]=t;}}
        nv2 = BEAM;
    }

    /* Save vars and propagated state — deeper recursion will overwrite l */
    int saved_vars[nv2]; /* VLA */
    memcpy(saved_vars, l->vars, nv2*sizeof(int));
    /* cl_p/cl_n/tm/fm at this level are stable since deeper levels use d+1 */

    double best = -1000.0;
    for (int i = 0; i < nv2; i++) {
        for (int v = 0; v <= 1; v++) {
            double s = score_k(l->cl_p, l->cl_n, rnc,
                              l->tm, l->fm, ons,
                              saved_vars[i], (bool)v, k-1, d+1);
            if (s > best) best = s;
        }
    }
    return imm + ((best > -1000.0) ? best : 0.0);
}

/* ─── DPLL ─── */
static int g_bt;

static bool dpll(const uint64_t *cp, const uint64_t *cn, int nc,
                 uint64_t *at, uint64_t *af, int *ans, int k) {
    /* Use separate heap buffers for DPLL level (not shared with scoring levels) */
    uint64_t *d_cp = malloc(nc * BS_BYTES);
    uint64_t *d_cn = malloc(nc * BS_BYTES);
    uint64_t *d_tm = malloc(BS_BYTES);
    uint64_t *d_fm = malloc(BS_BYTES);
    uint64_t *d_asgn = malloc(BS_BYTES);
    uint64_t *d_stmp = malloc(BS_BYTES);
    uint64_t *d_pl = malloc(BS_BYTES);
    uint64_t *d_nl = malloc(BS_BYTES);
    uint64_t *d_al = malloc(BS_BYTES);
    uint64_t *d_un = malloc(BS_BYTES);

    /* Unit propagation inline */
    BS_COPY(d_tm, at); BS_COPY(d_fm, af);
    int ns = *ans;
    memcpy(d_cp, cp, nc*BS_BYTES);
    memcpy(d_cn, cn, nc*BS_BYTES);

    bool ch = true;
    while (ch) {
        ch = false; bs_or(d_asgn, d_tm, d_fm);
        int nc2 = 0;
        for (int i = 0; i < nc; i++) {
            uint64_t *p = d_cp + i*NWORDS;
            uint64_t *n = d_cn + i*NWORDS;
            bs_and(d_stmp, p, d_tm); if(!bs_is_zero(d_stmp)) continue;
            bs_and(d_stmp, n, d_fm); if(!bs_is_zero(d_stmp)) continue;
            bs_andnot(d_pl, p, d_asgn);
            bs_andnot(d_nl, n, d_asgn);
            bs_or(d_al, d_pl, d_nl);
            if(bs_is_zero(d_al)){free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);return false;}
            if(bs_singleton(d_al)){
                int b=bs_lowest(d_al);
                if(bs_tst(d_pl,b)){if(bs_tst(d_fm,b)){free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);return false;}
                    if(!bs_tst(d_tm,b)){bs_set(d_tm,b);ns++;ch=true;}}
                else{if(bs_tst(d_tm,b)){free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);return false;}
                    if(!bs_tst(d_fm,b)){bs_set(d_fm,b);ns++;ch=true;}}
            }
            BS_COPY(d_cp+nc2*NWORDS, d_pl);
            BS_COPY(d_cn+nc2*NWORDS, d_nl);
            nc2++;
        }
        nc = nc2;
    }

    if (nc == 0) {
        BS_COPY(at, d_tm); BS_COPY(af, d_fm); *ans = ns;
        free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);
        return true;
    }

    /* Get unassigned */
    BS_ZERO(d_un);
    bs_or(d_asgn, d_tm, d_fm);
    for(int i=0;i<nc;i++){bs_or_eq(d_un,d_cp+i*NWORDS);bs_or_eq(d_un,d_cn+i*NWORDS);}
    for(int w=0;w<NWORDS;w++) d_un[w] &= ~d_asgn[w];
    if(bs_is_zero(d_un)){free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);return false;}

    int *cand = malloc(NV * sizeof(int));
    int nv2 = bs_to_arr(d_un, cand);
    int ncand = nv2 * 2;

    double *sc = malloc(ncand * sizeof(double));

    /* Score all candidates using levels[0..k] for scoring recursion */
    for (int i = 0; i < nv2; i++) {
        sc[i*2]   = score_k(d_cp, d_cn, nc, d_tm, d_fm, ns, cand[i], true,  k, 0);
        sc[i*2+1] = score_k(d_cp, d_cn, nc, d_tm, d_fm, ns, cand[i], false, k, 0);
    }

    double bs_ = -2000.0; int bi = 0;
    for(int i=0;i<ncand;i++) if(sc[i]>bs_){bs_=sc[i];bi=i;}

    int pv = cand[bi/2]; bool pval = !(bi&1);

    /* Try best */
    uint64_t *tt = malloc(BS_BYTES), *tf = malloc(BS_BYTES);
    BS_COPY(tt, d_tm); BS_COPY(tf, d_fm);
    int tns = ns;
    if(pval) bs_set(tt,pv); else bs_set(tf,pv);
    tns++;

    if (dpll(d_cp, d_cn, nc, tt, tf, &tns, k)) {
        BS_COPY(at, tt); BS_COPY(af, tf); *ans = tns;
        free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);
        free(cand);free(sc);free(tt);free(tf);
        return true;
    }
    g_bt++;

    /* Try opposite */
    BS_COPY(tt, d_tm); BS_COPY(tf, d_fm);
    tns = ns;
    if(!pval) bs_set(tt,pv); else bs_set(tf,pv);
    tns++;

    bool r = dpll(d_cp, d_cn, nc, tt, tf, &tns, k);
    if(r){BS_COPY(at,tt);BS_COPY(af,tf);*ans=tns;}

    free(d_cp);free(d_cn);free(d_tm);free(d_fm);free(d_asgn);free(d_stmp);free(d_pl);free(d_nl);free(d_al);free(d_un);
    free(cand);free(sc);free(tt);free(tf);
    return r;
}

/* ─── JW greedy solve (hard core detection) ─── */
static int jw_solve(const Formula *f) {
    int nc = f->nc, nv = f->nv;
    uint64_t *wp = malloc(nc*BS_BYTES), *wn = malloc(nc*BS_BYTES);
    uint64_t *tm = calloc(NWORDS,8), *fm = calloc(NWORDS,8);
    memcpy(wp, f->pos, nc*BS_BYTES);
    memcpy(wn, f->neg, nc*BS_BYTES);
    int ns = 0, bt = 0;

    uint64_t *asgn=malloc(BS_BYTES), *stmp=malloc(BS_BYTES);
    uint64_t *pl=malloc(BS_BYTES), *nl=malloc(BS_BYTES), *al=malloc(BS_BYTES);
    double *jwp=malloc(nv*sizeof(double)), *jwn_=malloc(nv*sizeof(double));

    /* Propagate first */
    bool ch=true;
    while(ch){ch=false;bs_or(asgn,tm,fm);int nc2=0;
        for(int i=0;i<nc;i++){
            uint64_t *p=wp+i*NWORDS, *n=wn+i*NWORDS;
            bs_and(stmp,p,tm);if(!bs_is_zero(stmp))continue;
            bs_and(stmp,n,fm);if(!bs_is_zero(stmp))continue;
            bs_andnot(pl,p,asgn);bs_andnot(nl,n,asgn);bs_or(al,pl,nl);
            if(bs_is_zero(al)){bt++;goto done;}
            if(bs_singleton(al)){int b=bs_lowest(al);
                if(bs_tst(pl,b)){if(bs_tst(fm,b)){bt++;goto done;}if(!bs_tst(tm,b)){bs_set(tm,b);ns++;ch=true;}}
                else{if(bs_tst(tm,b)){bt++;goto done;}if(!bs_tst(fm,b)){bs_set(fm,b);ns++;ch=true;}}}
            BS_COPY(wp+nc2*NWORDS,pl);BS_COPY(wn+nc2*NWORDS,nl);nc2++;}
        nc=nc2;}

    while(nc > 0) {
        /* JW scoring */
        memset(jwp,0,nv*sizeof(double));
        memset(jwn_,0,nv*sizeof(double));
        for(int i=0;i<nc;i++){
            uint64_t *lp=wp+i*NWORDS, *ln=wn+i*NWORDS;
            int csz=0;for(int w=0;w<NWORDS;w++)csz+=__builtin_popcountll(lp[w]|ln[w]);
            double wt=pow(2.0,-(double)csz);
            for(int w=0;w<NWORDS;w++){
                uint64_t pw=lp[w];while(pw){jwp[(w<<6)+__builtin_ctzll(pw)]+=wt;pw&=pw-1;}
                uint64_t nw=ln[w];while(nw){jwn_[(w<<6)+__builtin_ctzll(nw)]+=wt;nw&=nw-1;}
            }
        }
        bs_or(asgn,tm,fm);
        int bv=-1; double bj=-1;
        for(int v=0;v<nv;v++){if(bs_tst(asgn,v))continue;
            double mx=(jwp[v]>jwn_[v])?jwp[v]:jwn_[v];if(mx>bj){bj=mx;bv=v;}}
        if(bv<0)break;

        if(jwp[bv]>=jwn_[bv]) bs_set(tm,bv); else bs_set(fm,bv);
        ns++;

        /* Propagate */
        ch=true;
        while(ch){ch=false;bs_or(asgn,tm,fm);int nc2=0;
            for(int i=0;i<nc;i++){
                uint64_t *p=wp+i*NWORDS,*n=wn+i*NWORDS;
                bs_and(stmp,p,tm);if(!bs_is_zero(stmp))continue;
                bs_and(stmp,n,fm);if(!bs_is_zero(stmp))continue;
                bs_andnot(pl,p,asgn);bs_andnot(nl,n,asgn);bs_or(al,pl,nl);
                if(bs_is_zero(al)){bt++;goto done;}
                if(bs_singleton(al)){int b=bs_lowest(al);
                    if(bs_tst(pl,b)){if(bs_tst(fm,b)){bt++;goto done;}if(!bs_tst(tm,b)){bs_set(tm,b);ns++;ch=true;}}
                    else{if(bs_tst(tm,b)){bt++;goto done;}if(!bs_tst(fm,b)){bs_set(fm,b);ns++;ch=true;}}}
                BS_COPY(wp+nc2*NWORDS,pl);BS_COPY(wn+nc2*NWORDS,nl);nc2++;}
            nc=nc2;}
    }

done:
    free(wp);free(wn);free(tm);free(fm);free(asgn);free(stmp);free(pl);free(nl);free(al);free(jwp);free(jwn_);
    return bt;
}

int main(int argc, char **argv) {
    if(argc<4){fprintf(stderr,"Usage: %s <n> <k> <seed> [beam] [count] [ratio]\n",argv[0]);return 1;}
    NV=atoi(argv[1]); int k=atoi(argv[2]); unsigned long long ss=atoll(argv[3]);
    if(argc>4) BEAM=atoi(argv[4]);
    int count=(argc>5)?atoi(argv[5]):1;
    if(argc>6) RATIO=atof(argv[6]);

    NWORDS=(NV+63)/64;
    MAX_CL=(int)(NV*RATIO)+10;

    printf("COFFINHEAD Array v3: n=%d k=%d beam=%d count=%d ratio=%.2f nwords=%d\n",
           NV, k, BEAM, count, RATIO, NWORDS);

    levels_init(k);

    int total_bt=0,zero_bt=0,sat_count=0,hc_count=0,hc_zero_bt=0;
    double total_time=0;

    for(int i=0;i<count;i++){
        unsigned long long seed=ss+i;
        Formula f=fgen(NV,RATIO,seed);
        int jw_bt=jw_solve(&f);
        bool is_hc=(jw_bt>0);

        uint64_t *at=calloc(NWORDS,8),*af=calloc(NWORDS,8);
        int ans=0; g_bt=0;

        struct timespec t0,t1;
        clock_gettime(CLOCK_MONOTONIC,&t0);
        bool sat=dpll(f.pos,f.neg,f.nc,at,af,&ans,k);
        clock_gettime(CLOCK_MONOTONIC,&t1);
        double el=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
        total_time+=el;

        if(!sat){printf("  seed=%llu: UNSAT %.2fs\n",seed,el);}
        else{
            sat_count++;if(is_hc)hc_count++;
            total_bt+=g_bt;if(g_bt==0)zero_bt++;if(is_hc&&g_bt==0)hc_zero_bt++;
            printf("  seed=%llu: SAT bt=%d jw_bt=%d %.2fs%s\n",seed,g_bt,jw_bt,el,is_hc?" [HC]":"");
        }
        free(at);free(af);ffree(&f);
        if(el>600.0){printf("  (timeout)\n");break;}
    }

    printf("\n=== SUMMARY ===\n");
    printf("Instances: %d total, %d SAT, %d hard core\n",count,sat_count,hc_count);
    printf("Zero-BT: %d/%d overall, %d/%d hard core\n",zero_bt,sat_count,hc_zero_bt,hc_count);
    if(hc_count>0) printf("Hard core zero-BT rate: %.1f%%\n",100.0*hc_zero_bt/hc_count);
    printf("Total time: %.1fs, avg %.2fs/instance\n",total_time,total_time/count);

    levels_free();
    return 0;
}
