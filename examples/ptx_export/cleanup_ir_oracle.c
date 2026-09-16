// Independent index oracle for the five actual compiler-emitted helpers.
// The generated header binds their Rust symbol names; no Rust source is rebuilt.
#include <stdint.h>
#include <stdio.h>
#include "helpers.h"

int main(void) {
 uint64_t seeds[] = {0, 1, UINT64_C(1)<<63, UINT64_MAX};
 uint64_t initials[] = {0,1,17,63,64,UINT64_MAX};
 unsigned cases=0;
 for (unsigned t=0;t<4;t++) {
  uint64_t table[64];
  for (unsigned i=0;i<64;i++) table[i]=UINT64_C(0x9e3779b97f4a7c15)*i+seeds[t];
  for (unsigned l=0;l<67;l++) for (unsigned a=0;a<6;a++) {
   uint32_t limit=l==66?UINT32_MAX:l;
   unsigned n=limit<64?limit:64;
   uint64_t odd=0,live=0;
   for (unsigned i=1;i<n;i+=2) odd+=table[i];
   for (unsigned i=0;i<n;i++) live+=table[i==0?(initials[a]&63):((i-1)|1)];
   if (filtered(table,limit)!=odd || stepped(table,limit)!=odd ||
       preserved(table,limit,initials[a])!=odd || direct(table,limit)!=odd ||
       observed(table,limit,initials[a])!=live) {
    fprintf(stderr,"FAIL table=%u limit=%u initial=%llu\n",t,limit,(unsigned long long)initials[a]); return 1;
   }
   cases++;
  }
 }
 printf("HOST_IR_NUMERICAL_PASS: %u cases across five extracted helpers\n",cases);
 return 0;
}
