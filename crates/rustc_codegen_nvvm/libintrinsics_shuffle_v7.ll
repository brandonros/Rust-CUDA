define i64 @__nvvm_warp_shuffle(i32, i32, i32, i32, i32) #1 {
start:
  %r = call { i32, i1 } @llvm.nvvm.shfl.sync.i32(i32 %0, i32 %1, i32 %2, i32 %3, i32 %4)
  %val = extractvalue { i32, i1 } %r, 0
  %pred = extractvalue { i32, i1 } %r, 1
  %val64 = zext i32 %val to i64
  %pred64 = zext i1 %pred to i64
  %pred_hi = shl i64 %pred64, 32
  %packed = or i64 %val64, %pred_hi
  ret i64 %packed
}

declare { i32, i1 } @llvm.nvvm.shfl.sync.i32(i32, i32, i32, i32, i32) #1

