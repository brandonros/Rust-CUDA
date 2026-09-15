; LLVM 19 / modern NVVM dialect: the operation is encoded in the intrinsic
; name, not an extra mode operand. Preserve the Rust-facing packed i64 ABI.
define i64 @__nvvm_warp_shuffle(i32 %mask, i32 %mode, i32 %value, i32 %offset, i32 %clamp) convergent #1 {
start:
  switch i32 %mode, label %invalid [
    i32 0, label %idx
    i32 1, label %up
    i32 2, label %down
    i32 3, label %bfly
  ]
idx:
  %ri = call { i32, i1 } @llvm.nvvm.shfl.sync.idx.i32p(i32 %mask, i32 %value, i32 %offset, i32 %clamp)
  br label %pack
up:
  %ru = call { i32, i1 } @llvm.nvvm.shfl.sync.up.i32p(i32 %mask, i32 %value, i32 %offset, i32 %clamp)
  br label %pack
down:
  %rd = call { i32, i1 } @llvm.nvvm.shfl.sync.down.i32p(i32 %mask, i32 %value, i32 %offset, i32 %clamp)
  br label %pack
bfly:
  %rb = call { i32, i1 } @llvm.nvvm.shfl.sync.bfly.i32p(i32 %mask, i32 %value, i32 %offset, i32 %clamp)
  br label %pack
invalid:
  unreachable
pack:
  %r = phi { i32, i1 } [ %ri, %idx ], [ %ru, %up ], [ %rd, %down ], [ %rb, %bfly ]
  %val = extractvalue { i32, i1 } %r, 0
  %pred = extractvalue { i32, i1 } %r, 1
  %val64 = zext i32 %val to i64
  %pred64 = zext i1 %pred to i64
  %pred_hi = shl i64 %pred64, 32
  %packed = or i64 %val64, %pred_hi
  ret i64 %packed
}

declare { i32, i1 } @llvm.nvvm.shfl.sync.idx.i32p(i32, i32, i32, i32) convergent
declare { i32, i1 } @llvm.nvvm.shfl.sync.up.i32p(i32, i32, i32, i32) convergent
declare { i32, i1 } @llvm.nvvm.shfl.sync.down.i32p(i32, i32, i32, i32) convergent
declare { i32, i1 } @llvm.nvvm.shfl.sync.bfly.i32p(i32, i32, i32, i32) convergent
