/*
 * COFFINHEAD Array-Based v4 — k-Step Lookahead, Any n
 * =====================================================
 * Specializes bitset ops for NWORDS=1..8 (n up to 512).
 * Falls back to generic loop for larger n.
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

static int NV, NWORDS, BEAM = 0, MAX_CL;
static double RATIO = 4.0;

/* ─── Specialized bitset operations ─── */
/* The compiler will constant-fold NWORDS when it's known at the call site.
 * But since NWORDS is set at runtime, we use function pointers or switch dispatch.
 * Better approach: since the hot loop is unit propagation, we write
 * the ENTIRE up+score function specialized for each NWORDS. Too much code.
 *
 * Instead: use __builtin_expect and keep NWORDS in a global, letting -O3
 * do its thing. The loop overhead for NWORDS=2 is ~2 iterations which
 * should be unrolled by gcc. The real bottleneck is the number of calls.
 *
 * KEY OPTIMIZATION: Avoid malloc in the hot path. Use pre-allocated levels.
 * Also: skip memcpy when possible — only copy what's needed.
 */

#define BS_BYTES     (NWORDS * 8)
#define BS_ZERO(b)   memset((b), 0, BS_BYTES)
#define BS_COPY(d,s) memcpy((d), (s), BS_BYTES)

/* Force inline all bitset ops */
static inline __attribute__((always_inline)) void bs_or(uint64_t *__restrict d,
    const uint64_t *__restrict a, const uint64_t *__restrict b) {
    for (int i=0;i<NWORDS;i++) d[i]=a[i]|b[i]; }
static inline __attribute__((always_inline)) void bs_and(uint64_t *__restrict d,
    const uint64_t *__restrict a, const uint64_t *__restrict b) {
    for (int i=0;i<NWORDS;i++) d[i]=a[i]&b[i]; }
static inline __attribute__((always_inline)) void bs_andnot(uint64_t *__restrict d,
    const uint64_t *__restrict a, const uint64_t *__restrict m) {
    for (int i=0;i<NWORDS;i++) d[i]=a[i]&~m[i]; }
static inline __attribute__((always_inline)) void bs_or_eq(uint64_t *__restrict d,
    const uint64_t *__restrict s) {
    for (int i=0;i<NWORDS;i++) d[i]|=s[i]; }
static inline __attribute__((always_inline)) bool bs_is_zero(const uint64_t *b) {
    for (int i=0;i<NWORDS;i++) if(b[i]) return false; return true; }
static inline void bs_set(uint64_t *b, int p) { b[p>>6]|=1ULL<<(p&63); }
static inline bool bs_tst(const uint64_t *b, int p) { return (b[p>>6]>>(p&63))&1; }
static inline int bs_popcnt(const uint64_t *b) {
    int c=0; for(int i=0;i<NWORDS;i++) c+=__builtin_popcountll(b[i]); return c; }
static inline int bs_lowest(const uint64_t *b) {
    for(int i=0;i<NWORDS;i++) if(b[i]) return (i<<6)+__builtin_ctzll(b[i]); return -1; }
static inline bool bs_singleton(const uint64_t *b) {
    int f=0; for(int i=0;i<NWORDS;i++){if(b[i]){if(f)return false;if(b[i]&(b[i]-1))return false;f=1;}} return f; }

/* Fast has-any-common-bit (for satisfaction check) */
static inline __attribute__((always_inline)) bool bs_has_common(
    const uint64_t *__restrict a, const uint64_t *__restrict b) {
    for (int i=0;i<NWORDS;i++) if(a[i]&b[i]) return true; return false; }

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
    for(int i=0;i<f.nc;i++){int vs[3];
        for(int j=0;j<3;j++){int v;bool d;do{v=rng_int(nv);d=false;for(int k=0;k<j;k++)if(vs[k]==v){d=true;break;}}while(d);
        vs[j]=v;if(rng_next()&1)FP(&f,i)[v>>6]|=1ULL<<(v&63);else FN(&f,i)[v>>6]|=1ULL<<(v&63);}} return f;
}
static void ffree(Formula *f){free(f->pos);free(f->neg);}

/* ─── Level buffers for scoring recursion ─── */
#define MAX_K 20
typedef struct {
    uint64_t *cl_p, *cl_n;          /* clause buffers [MAX_CL * NWORDS] */
    uint64_t *tm, *fm;              /* assignment */
    uint64_t *asgn, *pl, *nl, *al;  /* temps for UP */
    uint64_t *un;                    /* unassigned vars */
    double *jw;                      /* JW scores */
    int *vars;                       /* variable list */
} Level;

static Level *levels;
static int K_DEPTH;

static void levels_init(int k) {
    K_DEPTH = k+2;
    levels = malloc(K_DEPTH * sizeof(Level));
    for (int d = 0; d < K_DEPTH; d++) {
        Level *l = &levels[d];
        l->cl_p = malloc(MAX_CL * BS_BYTES);
        l->cl_n = malloc(MAX_CL * BS_BYTES);
        l->tm = malloc(BS_BYTES); l->fm = malloc(BS_BYTES);
        l->asgn = malloc(BS_BYTES); l->pl = malloc(BS_BYTES);
        l->nl = malloc(BS_BYTES); l->al = malloc(BS_BYTES);
        l->un = malloc(BS_BYTES);
        l->jw = malloc(NV * sizeof(double));
        l->vars = malloc(NV * sizeof(int));
    }
}
static void levels_free(void) {
    for(int d=0;d<K_DEPTH;d++){Level *l=&levels[d];
        free(l->cl_p);free(l->cl_n);free(l->tm);free(l->fm);
        free(l->asgn);free(l->pl);free(l->nl);free(l->al);free(l->un);
        free(l->jw);free(l->vars);}
    free(levels);
}

/* ─── Unit propagation at depth d ─── */
static inline int up_at(const uint64_t *ip, const uint64_t *in, int nc,
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
            /* Satisfied check — early out with bs_has_common */
            if (bs_has_common(p, l->tm)) continue;
            if (bs_has_common(n, l->fm)) continue;
            /* Remaining literals */
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
    /* Set variable in temp (VLA on stack — fast for small NWORDS) */
    uint64_t tt[NWORDS], tf[NWORDS];
    memcpy(tt, tm, BS_BYTES); memcpy(tf, fm, BS_BYTES);
    if (val) tt[vb>>6] |= 1ULL<<(vb&63);
    else     tf[vb>>6] |= 1ULL<<(vb&63);

    int ons;
    int rnc = up_at(cp, cn, nc, tt, tf, ns+1, d, &ons);
    if (rnc < 0) return -1000.0;

    Level *l = &levels[d];
    double imm = (double)(ons - ns - 1) + (double)(nc - rnc);
    if (k <= 1) return imm;
    if (rnc == 0) return imm + 100.0*k;

    /* Unassigned vars */
    BS_ZERO(l->un);
    bs_or(l->asgn, l->tm, l->fm);
    for (int i = 0; i < rnc; i++) {
        bs_or_eq(l->un, l->cl_p + i*NWORDS);
        bs_or_eq(l->un, l->cl_n + i*NWORDS);
    }
    for (int w = 0; w < NWORDS; w++) l->un[w] &= ~l->asgn[w];
    if (bs_is_zero(l->un)) return imm;

    int nv2 = bs_to_arr(l->un, l->vars);

    /* Beam pruning */
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
        for(int i=0;i<BEAM&&i<nv2;i++){int best=i;for(int j=i+1;j<nv2;j++)
            if(l->jw[l->vars[j]]>l->jw[l->vars[best]])best=j;
            if(best!=i){int t=l->vars[i];l->vars[i]=l->vars[best];l->vars[best]=t;}}
        nv2 = BEAM;
    }

    /* Save vars (deeper recursion overwrites l->vars via level d+1) */
    int saved_vars[nv2];  /* VLA */
    memcpy(saved_vars, l->vars, nv2*sizeof(int));

    double best = -1000.0;
    for (int i = 0; i < nv2; i++)
        for (int v = 0; v <= 1; v++) {
            double s = score_k(l->cl_p, l->cl_n, rnc,
                              l->tm, l->fm, ons,
                              saved_vars[i], (bool)v, k-1, d+1);
            if (s > best) best = s;
        }
    return imm + ((best > -1000.0) ? best : 0.0);
}

/* ─── DPLL ─── */
static int g_bt;

static bool dpll(const uint64_t *cp, const uint64_t *cn, int nc,
                 uint64_t *at, uint64_t *af, int *ans, int k) {
    /* Inline unit propagation with heap buffers */
    uint64_t *wp = malloc(nc*BS_BYTES), *wn = malloc(nc*BS_BYTES);
    uint64_t *tm = malloc(BS_BYTES), *fm = malloc(BS_BYTES);
    uint64_t *asgn=malloc(BS_BYTES), *pl=malloc(BS_BYTES);
    uint64_t *nl=malloc(BS_BYTES), *al=malloc(BS_BYTES);
    uint64_t *un=malloc(BS_BYTES);
    BS_COPY(tm,at);BS_COPY(fm,af);int ns=*ans;
    memcpy(wp,cp,nc*BS_BYTES);memcpy(wn,cn,nc*BS_BYTES);

    bool ch=true;
    while(ch){ch=false;bs_or(asgn,tm,fm);int nc2=0;
        for(int i=0;i<nc;i++){
            uint64_t *p=wp+i*NWORDS,*n=wn+i*NWORDS;
            if(bs_has_common(p,tm))continue;
            if(bs_has_common(n,fm))continue;
            bs_andnot(pl,p,asgn);bs_andnot(nl,n,asgn);bs_or(al,pl,nl);
            if(bs_is_zero(al)){goto fail;}
            if(bs_singleton(al)){int b=bs_lowest(al);
                if(bs_tst(pl,b)){if(bs_tst(fm,b))goto fail;if(!bs_tst(tm,b)){bs_set(tm,b);ns++;ch=true;}}
                else{if(bs_tst(tm,b))goto fail;if(!bs_tst(fm,b)){bs_set(fm,b);ns++;ch=true;}}}
            BS_COPY(wp+nc2*NWORDS,pl);BS_COPY(wn+nc2*NWORDS,nl);nc2++;}
        nc=nc2;}

    if(nc==0){BS_COPY(at,tm);BS_COPY(af,fm);*ans=ns;
        free(wp);free(wn);free(tm);free(fm);free(asgn);free(pl);free(nl);free(al);free(un);return true;}

    /* Get unassigned */
    BS_ZERO(un);bs_or(asgn,tm,fm);
    for(int i=0;i<nc;i++){bs_or_eq(un,wp+i*NWORDS);bs_or_eq(un,wn+i*NWORDS);}
    for(int w=0;w<NWORDS;w++) un[w]&=~asgn[w];
    if(bs_is_zero(un)) goto fail;

    {
    int *cand=malloc(NV*sizeof(int));
    int nv2=bs_to_arr(un,cand);
    int ncand=nv2*2;
    double *sc=malloc(ncand*sizeof(double));

    for(int i=0;i<nv2;i++){
        sc[i*2]  =score_k(wp,wn,nc,tm,fm,ns,cand[i],true, k,0);
        sc[i*2+1]=score_k(wp,wn,nc,tm,fm,ns,cand[i],false,k,0);
    }

    double bs_=-2000.0;int bi=0;
    for(int i=0;i<ncand;i++)if(sc[i]>bs_){bs_=sc[i];bi=i;}
    int pv=cand[bi/2]; bool pval=!(bi&1);
    free(cand);free(sc);

    /* Try best */
    uint64_t *tt=malloc(BS_BYTES),*tf=malloc(BS_BYTES);
    BS_COPY(tt,tm);BS_COPY(tf,fm);int tns=ns;
    if(pval)bs_set(tt,pv);else bs_set(tf,pv);tns++;

    if(dpll(wp,wn,nc,tt,tf,&tns,k)){
        BS_COPY(at,tt);BS_COPY(af,tf);*ans=tns;
        free(wp);free(wn);free(tm);free(fm);free(asgn);free(pl);free(nl);free(al);free(un);free(tt);free(tf);return true;}
    g_bt++;

    /* Opposite */
    BS_COPY(tt,tm);BS_COPY(tf,fm);tns=ns;
    if(!pval)bs_set(tt,pv);else bs_set(tf,pv);tns++;
    bool r=dpll(wp,wn,nc,tt,tf,&tns,k);
    if(r){BS_COPY(at,tt);BS_COPY(af,tf);*ans=tns;}
    free(wp);free(wn);free(tm);free(fm);free(asgn);free(pl);free(nl);free(al);free(un);free(tt);free(tf);
    return r;
    }

fail:
    free(wp);free(wn);free(tm);free(fm);free(asgn);free(pl);free(nl);free(al);free(un);
    return false;
}

/* ─── JW greedy solve ─── */
static int jw_solve(const Formula *f) {
    int nc=f->nc,nv=f->nv;
    uint64_t *wp=malloc(nc*BS_BYTES),*wn=malloc(nc*BS_BYTES);
    uint64_t *tm=calloc(NWORDS,8),*fm=calloc(NWORDS,8);
    memcpy(wp,f->pos,nc*BS_BYTES);memcpy(wn,f->neg,nc*BS_BYTES);
    int ns=0,bt=0;
    uint64_t *asgn=malloc(BS_BYTES),*pl=malloc(BS_BYTES),*nl=malloc(BS_BYTES),*al=malloc(BS_BYTES);
    double *jwp=malloc(nv*sizeof(double)),*jwn_=malloc(nv*sizeof(double));

    /* Initial propagation */
    bool ch=true;
    while(ch){ch=false;bs_or(asgn,tm,fm);int nc2=0;
        for(int i=0;i<nc;i++){uint64_t *p=wp+i*NWORDS,*n=wn+i*NWORDS;
            if(bs_has_common(p,tm))continue;if(bs_has_common(n,fm))continue;
            bs_andnot(pl,p,asgn);bs_andnot(nl,n,asgn);bs_or(al,pl,nl);
            if(bs_is_zero(al)){bt++;goto jdone;}
            if(bs_singleton(al)){int b=bs_lowest(al);
                if(bs_tst(pl,b)){if(bs_tst(fm,b)){bt++;goto jdone;}if(!bs_tst(tm,b)){bs_set(tm,b);ns++;ch=true;}}
                else{if(bs_tst(tm,b)){bt++;goto jdone;}if(!bs_tst(fm,b)){bs_set(fm,b);ns++;ch=true;}}}
            BS_COPY(wp+nc2*NWORDS,pl);BS_COPY(wn+nc2*NWORDS,nl);nc2++;}nc=nc2;}

    while(nc>0){
        memset(jwp,0,nv*sizeof(double));memset(jwn_,0,nv*sizeof(double));
        for(int i=0;i<nc;i++){uint64_t *lp=wp+i*NWORDS,*ln=wn+i*NWORDS;
            int csz=0;for(int w=0;w<NWORDS;w++)csz+=__builtin_popcountll(lp[w]|ln[w]);
            double wt=pow(2.0,-(double)csz);
            for(int w=0;w<NWORDS;w++){uint64_t pw=lp[w];while(pw){jwp[(w<<6)+__builtin_ctzll(pw)]+=wt;pw&=pw-1;}
                uint64_t nw=ln[w];while(nw){jwn_[(w<<6)+__builtin_ctzll(nw)]+=wt;nw&=nw-1;}}}
        bs_or(asgn,tm,fm);
        int bv=-1;double bj=-1;
        for(int v=0;v<nv;v++){if(bs_tst(asgn,v))continue;
            double mx=(jwp[v]>jwn_[v])?jwp[v]:jwn_[v];if(mx>bj){bj=mx;bv=v;}}
        if(bv<0)break;
        if(jwp[bv]>=jwn_[bv])bs_set(tm,bv);else bs_set(fm,bv);ns++;

        ch=true;
        while(ch){ch=false;bs_or(asgn,tm,fm);int nc2=0;
            for(int i=0;i<nc;i++){uint64_t *p=wp+i*NWORDS,*n=wn+i*NWORDS;
                if(bs_has_common(p,tm))continue;if(bs_has_common(n,fm))continue;
                bs_andnot(pl,p,asgn);bs_andnot(nl,n,asgn);bs_or(al,pl,nl);
                if(bs_is_zero(al)){bt++;goto jdone;}
                if(bs_singleton(al)){int b=bs_lowest(al);
                    if(bs_tst(pl,b)){if(bs_tst(fm,b)){bt++;goto jdone;}if(!bs_tst(tm,b)){bs_set(tm,b);ns++;ch=true;}}
                    else{if(bs_tst(tm,b)){bt++;goto jdone;}if(!bs_tst(fm,b)){bs_set(fm,b);ns++;ch=true;}}}
                BS_COPY(wp+nc2*NWORDS,pl);BS_COPY(wn+nc2*NWORDS,nl);nc2++;}nc=nc2;}
    }
jdone:
    free(wp);free(wn);free(tm);free(fm);free(asgn);free(pl);free(nl);free(al);free(jwp);free(jwn_);
    return bt;
}

int main(int argc, char **argv) {
    if(argc<4){fprintf(stderr,"Usage: %s <n> <k> <seed> [beam] [count] [ratio]\n",argv[0]);return 1;}
    NV=atoi(argv[1]);int k=atoi(argv[2]);unsigned long long ss=atoll(argv[3]);
    if(argc>4)BEAM=atoi(argv[4]);
    int count=(argc>5)?atoi(argv[5]):1;
    if(argc>6)RATIO=atof(argv[6]);
    NWORDS=(NV+63)/64;MAX_CL=(int)(NV*RATIO)+10;

    printf("COFFINHEAD Array v4: n=%d k=%d beam=%d count=%d ratio=%.2f nwords=%d\n",
           NV,k,BEAM,count,RATIO,NWORDS);

    levels_init(k);

    int total_bt=0,zero_bt=0,sat_count=0,hc_count=0,hc_zero_bt=0;
    double total_time=0;

    for(int i=0;i<count;i++){
        unsigned long long seed=ss+i;
        Formula f=fgen(NV,RATIO,seed);
        int jw_bt=jw_solve(&f);
        bool is_hc=(jw_bt>0);

        uint64_t *at=calloc(NWORDS,8),*af=calloc(NWORDS,8);
        int ans=0;g_bt=0;

        struct timespec t0,t1;
        clock_gettime(CLOCK_MONOTONIC,&t0);
        bool sat=dpll(f.pos,f.neg,f.nc,at,af,&ans,k);
        clock_gettime(CLOCK_MONOTONIC,&t1);
        double el=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
        total_time+=el;

        if(!sat){printf("  seed=%llu: UNSAT %.2fs\n",seed,el);}
        else{sat_count++;if(is_hc)hc_count++;
            total_bt+=g_bt;if(g_bt==0)zero_bt++;if(is_hc&&g_bt==0)hc_zero_bt++;
            printf("  seed=%llu: SAT bt=%d jw_bt=%d %.2fs%s\n",seed,g_bt,jw_bt,el,is_hc?" [HC]":"");}
        free(at);free(af);ffree(&f);
        if(el>600.0){printf("  (timeout)\n");break;}
    }

    printf("\n=== SUMMARY ===\n");
    printf("Instances: %d total, %d SAT, %d hard core\n",count,sat_count,hc_count);
    printf("Zero-BT: %d/%d overall, %d/%d hard core\n",zero_bt,sat_count,hc_zero_bt,hc_count);
    if(hc_count>0)printf("Hard core zero-BT rate: %.1f%%\n",100.0*hc_zero_bt/hc_count);
    printf("Total time: %.1fs, avg %.2fs/instance\n",total_time,total_time/count);
    levels_free();
    return 0;
}
