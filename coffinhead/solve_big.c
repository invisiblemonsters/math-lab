/*
 * COFFINHEAD Big — k-Step Lookahead, Compile-Time NWORDS
 * =======================================================
 * Set NWORDS at compile time for max performance.
 * Variants: NW=4 (n<=256), NW=8 (n<=512), NW=16 (n<=1024)
 *
 * Build examples:
 *   gcc -O3 -march=native -DNW=4 -o solve_256a solve_big.c -lm    # n<=256
 *   gcc -O3 -march=native -DNW=8 -o solve_512 solve_big.c -lm     # n<=512
 *   gcc -O3 -march=native -DNW=16 -o solve_1024 solve_big.c -lm   # n<=1024
 *   gcc -O3 -march=native -DNW=32 -o solve_2048 solve_big.c -lm   # n<=2048
 *
 * Usage: ./solve_XXX <n> <k> <seed> [beam] [count] [ratio]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>

#ifndef NW
#define NW 8  /* default: n<=512 */
#endif

#define MAX_N (NW * 64)

static int NV, BEAM = 0, MAX_CL;
static double RATIO = 4.0;

/* ─── Fixed-size bitset operations — compiler will unroll for constant NW ─── */
typedef struct { uint64_t w[NW]; } Bits;

static const Bits BITS_ZERO = {{0}};

static inline Bits bits_or(Bits a, Bits b) {
    Bits r; for(int i=0;i<NW;i++) r.w[i]=a.w[i]|b.w[i]; return r; }
static inline Bits bits_and(Bits a, Bits b) {
    Bits r; for(int i=0;i<NW;i++) r.w[i]=a.w[i]&b.w[i]; return r; }
static inline Bits bits_andnot(Bits a, Bits m) {
    Bits r; for(int i=0;i<NW;i++) r.w[i]=a.w[i]&~m.w[i]; return r; }
static inline bool bits_zero(Bits a) {
    for(int i=0;i<NW;i++) if(a.w[i]) return false; return true; }
static inline bool bits_has_common(Bits a, Bits b) {
    for(int i=0;i<NW;i++) if(a.w[i]&b.w[i]) return true; return false; }
static inline Bits bits_set(Bits a, int p) {
    a.w[p>>6]|=1ULL<<(p&63); return a; }
static inline bool bits_tst(Bits a, int p) {
    return (a.w[p>>6]>>(p&63))&1; }
static inline int bits_lowest(Bits a) {
    for(int i=0;i<NW;i++) if(a.w[i]) return (i<<6)+__builtin_ctzll(a.w[i]); return -1; }
static inline bool bits_singleton(Bits a) {
    int f=0; for(int i=0;i<NW;i++){if(a.w[i]){if(f)return false;if(a.w[i]&(a.w[i]-1))return false;f=1;}} return f; }
static inline int bits_popcnt(Bits a) {
    int c=0; for(int i=0;i<NW;i++) c+=__builtin_popcountll(a.w[i]); return c; }
static inline int bits_to_arr(Bits b, int *out) {
    int c=0; for(int i=0;i<NW;i++){uint64_t w=b.w[i];while(w){out[c++]=(i<<6)+__builtin_ctzll(w);w&=w-1;}} return c; }

/* ─── Clause: two bitmasks ─── */
typedef struct { Bits pos, neg; } Clause;

/* ─── RNG ─── */
static unsigned long long rng_s;
static inline void rng_seed(unsigned long long s){rng_s=s?s:1;}
static inline unsigned long long rng_next(void){rng_s^=rng_s<<13;rng_s^=rng_s>>7;rng_s^=rng_s<<17;return rng_s;}
static inline int rng_int(int n){return(int)(rng_next()%(unsigned long long)n);}

/* ─── Formula ─── */
typedef struct { int nv, nc; Clause *cl; } Formula;

static Formula fgen(int nv, double r, unsigned long long seed) {
    Formula f; f.nv=nv; f.nc=(int)(nv*r);
    f.cl=calloc(f.nc, sizeof(Clause));
    rng_seed(seed);
    for(int i=0;i<f.nc;i++){
        int vs[3];
        for(int j=0;j<3;j++){int v;bool d;
            do{v=rng_int(nv);d=false;for(int k=0;k<j;k++)if(vs[k]==v){d=true;break;}}while(d);
            vs[j]=v;
            if(rng_next()&1) f.cl[i].pos=bits_set(f.cl[i].pos,v);
            else             f.cl[i].neg=bits_set(f.cl[i].neg,v);
        }
    }
    return f;
}
static void ffree(Formula *f){free(f->cl);}

/* ─── Level buffers for scoring recursion ─── */
#define MAX_K 20

typedef struct {
    Clause *cl;     /* [MAX_CL] */
    Bits tm, fm;    /* assignment */
    int ns;         /* vars set */
    double *jw;     /* [MAX_N] */
    int *vars;      /* [MAX_N] */
} Level;

static Level levels[MAX_K+2];

static void levels_init(void) {
    for(int d=0;d<MAX_K+2;d++){
        levels[d].cl=malloc(MAX_CL*sizeof(Clause));
        levels[d].jw=malloc(MAX_N*sizeof(double));
        levels[d].vars=malloc(MAX_N*sizeof(int));
    }
}
static void levels_free(void) {
    for(int d=0;d<MAX_K+2;d++){free(levels[d].cl);free(levels[d].jw);free(levels[d].vars);}
}

/* ─── Unit propagation at depth d ─── */
/* Returns remaining clause count, -1 on contradiction */
static inline int up_at(const Clause *in, int nc, Bits it, Bits ifm, int ins, int d) {
    Level *l = &levels[d];
    l->tm=it; l->fm=ifm; l->ns=ins;
    memcpy(l->cl, in, nc*sizeof(Clause));

    bool ch = true;
    while (ch) {
        ch = false;
        Bits asgn = bits_or(l->tm, l->fm);
        int nc2 = 0;
        for (int i = 0; i < nc; i++) {
            Bits p = l->cl[i].pos, n = l->cl[i].neg;
            if (bits_has_common(p, l->tm)) continue;
            if (bits_has_common(n, l->fm)) continue;
            Bits pl = bits_andnot(p, asgn);
            Bits nl = bits_andnot(n, asgn);
            Bits al = bits_or(pl, nl);
            if (bits_zero(al)) return -1;
            if (bits_singleton(al)) {
                int b = bits_lowest(al);
                if (bits_tst(pl, b)) {
                    if (bits_tst(l->fm, b)) return -1;
                    if (!bits_tst(l->tm, b)) { l->tm=bits_set(l->tm,b); l->ns++; ch=true; }
                } else {
                    if (bits_tst(l->tm, b)) return -1;
                    if (!bits_tst(l->fm, b)) { l->fm=bits_set(l->fm,b); l->ns++; ch=true; }
                }
            }
            l->cl[nc2].pos = pl;
            l->cl[nc2].neg = nl;
            nc2++;
        }
        nc = nc2;
    }
    return nc;
}

/* ─── k-step scoring ─── */
static double score_k(const Clause *cl, int nc, Bits tm, Bits fm, int ns,
                       int vb, bool val, int k, int d) {
    Bits tt=tm, tf=fm;
    if(val) tt=bits_set(tt,vb); else tf=bits_set(tf,vb);

    int rnc = up_at(cl, nc, tt, tf, ns+1, d);
    if (rnc < 0) return -1000.0;

    Level *l = &levels[d];
    double imm = (double)(l->ns - ns - 1) + (double)(nc - rnc);
    if (k <= 1) return imm;
    if (rnc == 0) return imm + 100.0*k;

    /* Unassigned vars */
    Bits un = BITS_ZERO;
    Bits asgn = bits_or(l->tm, l->fm);
    for(int i=0;i<rnc;i++) {
        un = bits_or(un, bits_or(l->cl[i].pos, l->cl[i].neg));
    }
    un = bits_andnot(un, asgn);
    if (bits_zero(un)) return imm;

    int nv2 = bits_to_arr(un, l->vars);

    /* Beam */
    if (BEAM > 0 && nv2 > BEAM) {
        memset(l->jw, 0, NV*sizeof(double));
        for(int i=0;i<rnc;i++){
            Bits lits = bits_or(l->cl[i].pos, l->cl[i].neg);
            int csz = bits_popcnt(lits);
            double wt = pow(2.0,-(double)csz);
            for(int w=0;w<NW;w++){
                uint64_t pw=l->cl[i].pos.w[w];
                while(pw){l->jw[(w<<6)+__builtin_ctzll(pw)]+=wt;pw&=pw-1;}
                uint64_t nw=l->cl[i].neg.w[w];
                while(nw){l->jw[(w<<6)+__builtin_ctzll(nw)]+=wt;nw&=nw-1;}
            }
        }
        for(int i=0;i<BEAM&&i<nv2;i++){int best=i;
            for(int j=i+1;j<nv2;j++)if(l->jw[l->vars[j]]>l->jw[l->vars[best]])best=j;
            if(best!=i){int t=l->vars[i];l->vars[i]=l->vars[best];l->vars[best]=t;}}
        nv2=BEAM;
    }

    /* Save vars */
    int sv[nv2];
    memcpy(sv, l->vars, nv2*sizeof(int));

    double best = -1000.0;
    for(int i=0;i<nv2;i++)
        for(int v=0;v<=1;v++){
            double s = score_k(l->cl, rnc, l->tm, l->fm, l->ns,
                              sv[i], (bool)v, k-1, d+1);
            if(s>best) best=s;
        }
    return imm + ((best>-1000.0)?best:0.0);
}

/* ─── DPLL ─── */
static int g_bt;

static bool dpll(const Clause *cl, int nc, Bits *at, Bits *af, int *ans, int k) {
    /* Propagate */
    Clause *wcl = malloc(nc*sizeof(Clause));
    memcpy(wcl, cl, nc*sizeof(Clause));
    Bits tm=*at, fm=*af; int ns=*ans;

    bool ch=true;
    while(ch){ch=false;Bits asgn=bits_or(tm,fm);int nc2=0;
        for(int i=0;i<nc;i++){
            Bits p=wcl[i].pos,n=wcl[i].neg;
            if(bits_has_common(p,tm))continue;if(bits_has_common(n,fm))continue;
            Bits pl=bits_andnot(p,asgn),nl=bits_andnot(n,asgn),al=bits_or(pl,nl);
            if(bits_zero(al)){free(wcl);return false;}
            if(bits_singleton(al)){int b=bits_lowest(al);
                if(bits_tst(pl,b)){if(bits_tst(fm,b)){free(wcl);return false;}if(!bits_tst(tm,b)){tm=bits_set(tm,b);ns++;ch=true;}}
                else{if(bits_tst(tm,b)){free(wcl);return false;}if(!bits_tst(fm,b)){fm=bits_set(fm,b);ns++;ch=true;}}}
            wcl[nc2].pos=pl;wcl[nc2].neg=nl;nc2++;}nc=nc2;}

    if(nc==0){*at=tm;*af=fm;*ans=ns;free(wcl);return true;}

    /* Unassigned */
    Bits un=BITS_ZERO,asgn=bits_or(tm,fm);
    for(int i=0;i<nc;i++)un=bits_or(un,bits_or(wcl[i].pos,wcl[i].neg));
    un=bits_andnot(un,asgn);
    if(bits_zero(un)){free(wcl);return false;}

    int cand[MAX_N],nv2=bits_to_arr(un,cand);
    int ncand=nv2*2;
    double *sc=malloc(ncand*sizeof(double));

    for(int i=0;i<nv2;i++){
        sc[i*2]  =score_k(wcl,nc,tm,fm,ns,cand[i],true, k,0);
        sc[i*2+1]=score_k(wcl,nc,tm,fm,ns,cand[i],false,k,0);
    }

    double bs_=-2000.0;int bi=0;
    for(int i=0;i<ncand;i++)if(sc[i]>bs_){bs_=sc[i];bi=i;}
    int pv=cand[bi/2];bool pval=!(bi&1);
    free(sc);

    /* Try best */
    Bits tt=tm,tf=fm;int tns=ns;
    if(pval)tt=bits_set(tt,pv);else tf=bits_set(tf,pv);tns++;
    if(dpll(wcl,nc,&tt,&tf,&tns,k)){*at=tt;*af=tf;*ans=tns;free(wcl);return true;}
    g_bt++;

    /* Opposite */
    tt=tm;tf=fm;tns=ns;
    if(!pval)tt=bits_set(tt,pv);else tf=bits_set(tf,pv);tns++;
    bool r=dpll(wcl,nc,&tt,&tf,&tns,k);
    if(r){*at=tt;*af=tf;*ans=tns;}
    free(wcl);return r;
}

/* ─── JW greedy ─── */
static int jw_solve(const Formula *f) {
    int nc=f->nc,nv=f->nv,bt=0;
    Clause *wcl=malloc(nc*sizeof(Clause));
    memcpy(wcl,f->cl,nc*sizeof(Clause));
    Bits tm=BITS_ZERO,fm=BITS_ZERO; int ns=0;
    double *jwp=malloc(nv*sizeof(double)),*jwn_=malloc(nv*sizeof(double));

    /* Initial propagation */
    bool ch=true;
    while(ch){ch=false;Bits asgn=bits_or(tm,fm);int nc2=0;
        for(int i=0;i<nc;i++){Bits p=wcl[i].pos,n=wcl[i].neg;
            if(bits_has_common(p,tm))continue;if(bits_has_common(n,fm))continue;
            Bits pl=bits_andnot(p,asgn),nl=bits_andnot(n,asgn),al=bits_or(pl,nl);
            if(bits_zero(al)){bt++;goto jd;}
            if(bits_singleton(al)){int b=bits_lowest(al);
                if(bits_tst(pl,b)){if(bits_tst(fm,b)){bt++;goto jd;}if(!bits_tst(tm,b)){tm=bits_set(tm,b);ns++;ch=true;}}
                else{if(bits_tst(tm,b)){bt++;goto jd;}if(!bits_tst(fm,b)){fm=bits_set(fm,b);ns++;ch=true;}}}
            wcl[nc2].pos=pl;wcl[nc2].neg=nl;nc2++;}nc=nc2;}

    while(nc>0){
        memset(jwp,0,nv*sizeof(double));memset(jwn_,0,nv*sizeof(double));
        for(int i=0;i<nc;i++){
            int csz=bits_popcnt(bits_or(wcl[i].pos,wcl[i].neg));
            double wt=pow(2.0,-(double)csz);
            for(int w=0;w<NW;w++){
                uint64_t pw=wcl[i].pos.w[w];while(pw){jwp[(w<<6)+__builtin_ctzll(pw)]+=wt;pw&=pw-1;}
                uint64_t nw=wcl[i].neg.w[w];while(nw){jwn_[(w<<6)+__builtin_ctzll(nw)]+=wt;nw&=nw-1;}}}
        Bits asgn=bits_or(tm,fm);
        int bv=-1;double bj=-1;
        for(int v=0;v<nv;v++){if(bits_tst(asgn,v))continue;
            double mx=(jwp[v]>jwn_[v])?jwp[v]:jwn_[v];if(mx>bj){bj=mx;bv=v;}}
        if(bv<0)break;
        if(jwp[bv]>=jwn_[bv])tm=bits_set(tm,bv);else fm=bits_set(fm,bv);ns++;

        ch=true;
        while(ch){ch=false;Bits ag=bits_or(tm,fm);int nc2=0;
            for(int i=0;i<nc;i++){Bits p=wcl[i].pos,n=wcl[i].neg;
                if(bits_has_common(p,tm))continue;if(bits_has_common(n,fm))continue;
                Bits pl=bits_andnot(p,ag),nl=bits_andnot(n,ag),al=bits_or(pl,nl);
                if(bits_zero(al)){bt++;goto jd;}
                if(bits_singleton(al)){int b=bits_lowest(al);
                    if(bits_tst(pl,b)){if(bits_tst(fm,b)){bt++;goto jd;}if(!bits_tst(tm,b)){tm=bits_set(tm,b);ns++;ch=true;}}
                    else{if(bits_tst(tm,b)){bt++;goto jd;}if(!bits_tst(fm,b)){fm=bits_set(fm,b);ns++;ch=true;}}}
                wcl[nc2].pos=pl;wcl[nc2].neg=nl;nc2++;}nc=nc2;}
    }
jd: free(wcl);free(jwp);free(jwn_);return bt;
}

int main(int argc, char **argv) {
    if(argc<4){fprintf(stderr,"Usage: %s <n> <k> <seed> [beam] [count] [ratio]\n  Max n=%d (NW=%d)\n",argv[0],MAX_N,NW);return 1;}
    NV=atoi(argv[1]);int k=atoi(argv[2]);unsigned long long ss=atoll(argv[3]);
    if(argc>4)BEAM=atoi(argv[4]);int count=(argc>5)?atoi(argv[5]):1;if(argc>6)RATIO=atof(argv[6]);
    if(NV>MAX_N){fprintf(stderr,"n=%d > MAX_N=%d. Recompile with -DNW=%d\n",NV,MAX_N,(NV+63)/64);return 1;}
    MAX_CL=(int)(NV*RATIO)+10;

    printf("COFFINHEAD Big (NW=%d, max_n=%d): n=%d k=%d beam=%d count=%d ratio=%.2f\n",
           NW,MAX_N,NV,k,BEAM,count,RATIO);

    levels_init();

    int total_bt=0,zero_bt=0,sat_count=0,hc_count=0,hc_zero_bt=0;
    double total_time=0;

    for(int i=0;i<count;i++){
        unsigned long long seed=ss+i;
        Formula f=fgen(NV,RATIO,seed);
        int jw_bt=jw_solve(&f);bool is_hc=(jw_bt>0);

        Bits at=BITS_ZERO,af=BITS_ZERO;int ans=0;g_bt=0;
        struct timespec t0,t1;
        clock_gettime(CLOCK_MONOTONIC,&t0);
        bool sat=dpll(f.cl,f.nc,&at,&af,&ans,k);
        clock_gettime(CLOCK_MONOTONIC,&t1);
        double el=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
        total_time+=el;

        if(!sat){printf("  seed=%llu: UNSAT %.2fs\n",seed,el);}
        else{sat_count++;if(is_hc)hc_count++;
            total_bt+=g_bt;if(g_bt==0)zero_bt++;if(is_hc&&g_bt==0)hc_zero_bt++;
            printf("  seed=%llu: SAT bt=%d jw_bt=%d %.2fs%s\n",seed,g_bt,jw_bt,el,is_hc?" [HC]":"");}
        ffree(&f);
        if(el>600.0){printf("  (timeout)\n");break;}
    }

    printf("\n=== SUMMARY ===\n");
    printf("Instances: %d total, %d SAT, %d hard core\n",count,sat_count,hc_count);
    printf("Zero-BT: %d/%d overall, %d/%d hard core\n",zero_bt,sat_count,hc_zero_bt,hc_count);
    if(hc_count>0)printf("Hard core zero-BT rate: %.1f%%\n",100.0*hc_zero_bt/hc_count);
    printf("Total time: %.1fs, avg %.2fs/instance\n",total_time,total_time/count);
    levels_free();return 0;
}
