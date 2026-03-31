/*
 * Solve a single generated instance with k-step lookahead.
 * No hard-core filtering — just generate, solve, report backtracks.
 * Build: gcc -O3 -march=native -fopenmp -o solve_one solve_one.c -lm
 * Usage: ./solve_one <n_vars> <k_step> <seed> [beam]
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
#define MAX_VARS 250
#define MAX_CLAUSES 1200

static inline int popcnt128(u128 x){return __builtin_popcountll((uint64_t)x)+__builtin_popcountll((uint64_t)(x>>64));}
static inline u128 BIT(int i){return((u128)1)<<i;}
static inline int lowest_bit128(u128 x){uint64_t lo=(uint64_t)x;if(lo)return __builtin_ctzll(lo);return 64+__builtin_ctzll((uint64_t)(x>>64));}
static inline int next_bit128(u128*m){int b=lowest_bit128(*m);*m&=~BIT(b);return b;}

typedef struct{u128 pos;u128 neg;}BClause;
typedef struct{u128 t_mask;u128 f_mask;int n_set;}BAssign;
typedef struct{BAssign assign;BClause clauses[MAX_CLAUSES];int n_clauses;bool contradiction;}PropResult;

static int BEAM=0;
static unsigned long long rng_state;
void rng_seed(unsigned long long s){rng_state=s?s:1;}
unsigned long long rng_next(void){rng_state^=rng_state<<13;rng_state^=rng_state>>7;rng_state^=rng_state<<17;return rng_state;}
int rng_int(int n){return(int)(rng_next()%(unsigned long long)n);}

typedef struct{BClause clauses[MAX_CLAUSES];int n_clauses;int n_vars;}Formula;

void gen(Formula*f,int nv,double r,unsigned long long seed){
    rng_seed(seed);f->n_vars=nv;f->n_clauses=(int)(nv*r);
    if(f->n_clauses>MAX_CLAUSES)f->n_clauses=MAX_CLAUSES;
    for(int i=0;i<f->n_clauses;i++){
        f->clauses[i].pos=0;f->clauses[i].neg=0;
        int vs[3];
        for(int j=0;j<3;j++){int v;bool d;do{v=1+rng_int(nv);d=false;for(int k=0;k<j;k++)if(vs[k]==v){d=true;break;}}while(d);vs[j]=v;if(rng_next()&1)f->clauses[i].pos|=BIT(v-1);else f->clauses[i].neg|=BIT(v-1);}
    }
}

void up(const BClause*cl,int nc,const BAssign*ain,PropResult*out){
    out->assign=*ain;out->contradiction=false;memcpy(out->clauses,cl,sizeof(BClause)*nc);out->n_clauses=nc;
    bool ch=true;while(ch){ch=false;int nc2=0;for(int i=0;i<out->n_clauses;i++){
        u128 p=out->clauses[i].pos,n=out->clauses[i].neg;
        if((p&out->assign.t_mask)||(n&out->assign.f_mask))continue;
        u128 as=out->assign.t_mask|out->assign.f_mask;u128 pl=p&~as,nl=n&~as,al=pl|nl;
        if(!al){out->contradiction=true;return;}
        if(popcnt128(al)==1){int b=lowest_bit128(al);
            if(pl&BIT(b)){if(out->assign.f_mask&BIT(b)){out->contradiction=true;return;}if(!(out->assign.t_mask&BIT(b))){out->assign.t_mask|=BIT(b);out->assign.n_set++;ch=true;}}
            else{if(out->assign.t_mask&BIT(b)){out->contradiction=true;return;}if(!(out->assign.f_mask&BIT(b))){out->assign.f_mask|=BIT(b);out->assign.n_set++;ch=true;}}}
        out->clauses[nc2].pos=pl;out->clauses[nc2].neg=nl;nc2++;}out->n_clauses=nc2;}
}

u128 get_un(const BClause*c,int nc,const BAssign*a){u128 m=0;for(int i=0;i<nc;i++)m|=c[i].pos|c[i].neg;return m&~(a->t_mask|a->f_mask);}

double score(const BClause*cl,int nc,const BAssign*a,int vb,bool val,int nv,int k){
    BAssign na=*a;if(val)na.t_mask|=BIT(vb);else na.f_mask|=BIT(vb);na.n_set++;
    PropResult pr;up(cl,nc,&na,&pr);if(pr.contradiction)return-1000.0;
    double imm=(double)(pr.assign.n_set-a->n_set-1)+(double)(nc-pr.n_clauses);
    if(k<=1)return imm;
    u128 un=get_un(pr.clauses,pr.n_clauses,&pr.assign);if(!un)return imm+100.0*k;
    int vs[MAX_VARS],nv2=0;u128 t=un;while(t)vs[nv2++]=next_bit128(&t);
    if(BEAM>0&&nv2>BEAM){double jw[MAX_VARS]={0};
        for(int i=0;i<pr.n_clauses;i++){int cl2=popcnt128(pr.clauses[i].pos|pr.clauses[i].neg);double w=pow(2.0,-(double)cl2);u128 p2=pr.clauses[i].pos,n2=pr.clauses[i].neg;while(p2){jw[next_bit128(&p2)]+=w;}while(n2){jw[next_bit128(&n2)]+=w;}}
        for(int i=0;i<BEAM&&i<nv2;i++){int best=i;for(int j=i+1;j<nv2;j++)if(jw[vs[j]]>jw[vs[best]])best=j;if(best!=i){int tmp=vs[i];vs[i]=vs[best];vs[best]=tmp;}}nv2=BEAM;}
    double best=-1000.0;for(int i=0;i<nv2;i++)for(int v=0;v<=1;v++){double s=score(pr.clauses,pr.n_clauses,&pr.assign,vs[i],(bool)v,nv,k-1);if(s>best)best=s;}
    return imm+((best>-1000.0)?best:0.0);
}

int g_bt;
bool dpll(const BClause*cl,int nc,BAssign*a,int nv,int k){
    PropResult pr;up(cl,nc,a,&pr);if(pr.contradiction)return false;
    if(pr.n_clauses==0){*a=pr.assign;return true;}
    u128 un=get_un(pr.clauses,pr.n_clauses,&pr.assign);if(!un)return false;
    int cb[MAX_VARS*2],cv[MAX_VARS*2];int nc2=0;u128 t=un;
    while(t){int b=next_bit128(&t);cb[nc2]=b;cv[nc2]=1;nc2++;cb[nc2]=b;cv[nc2]=0;nc2++;}
    double sc[MAX_VARS*2];
    #pragma omp parallel for schedule(dynamic) if(nc2>8)
    for(int i=0;i<nc2;i++)sc[i]=score(pr.clauses,pr.n_clauses,&pr.assign,cb[i],(bool)cv[i],nv,k);
    double bs=-2000.0;int bi=0;for(int i=0;i<nc2;i++)if(sc[i]>bs){bs=sc[i];bi=i;}
    BAssign a1=pr.assign;if(cv[bi])a1.t_mask|=BIT(cb[bi]);else a1.f_mask|=BIT(cb[bi]);a1.n_set++;
    if(dpll(pr.clauses,pr.n_clauses,&a1,nv,k)){*a=a1;return true;}g_bt++;
    BAssign a2=pr.assign;if(!cv[bi])a2.t_mask|=BIT(cb[bi]);else a2.f_mask|=BIT(cb[bi]);a2.n_set++;
    bool r=dpll(pr.clauses,pr.n_clauses,&a2,nv,k);if(r)*a=a2;return r;
}

int main(int argc,char**argv){
    if(argc<4){fprintf(stderr,"Usage: %s <n> <k> <seed> [beam]\n",argv[0]);return 1;}
    int n=atoi(argv[1]),k=atoi(argv[2]);unsigned long long seed=atoll(argv[3]);
    if(argc>4)BEAM=atoi(argv[4]);
    if(n>128){fprintf(stderr,"n=%d exceeds 128-bit limit\n",n);return 1;}
    Formula f;gen(&f,n,4.0,seed);g_bt=0;
    BAssign a={0,0,0};
    struct timespec t0,t1;clock_gettime(CLOCK_MONOTONIC,&t0);
    bool sat=dpll(f.clauses,f.n_clauses,&a,n,k);
    clock_gettime(CLOCK_MONOTONIC,&t1);
    double el=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
    printf("n=%d k=%d seed=%llu beam=%d: %s bt=%d %.2fs\n",n,k,seed,BEAM,sat?"SAT":"UNSAT",g_bt,el);
    return 0;
}
