#include "rustllvm.h"
#include "llvm/IR/Verifier.h"
#include <cstdlib>

extern "C" void LLVMRustSetNormalizedTarget(LLVMModuleRef, const char *);
extern "C" void LLVMRustAddFunctionAttribute(LLVMValueRef, unsigned, LLVMRustAttribute);
extern "C" void LLVMRustAddFunctionAttributeWithType(LLVMValueRef, unsigned, LLVMRustAttribute, LLVMTypeRef);
extern "C" void LLVMRustRemoveFunctionAttributes(LLVMValueRef, unsigned, LLVMRustAttribute);
extern "C" void LLVMRustAddCallSiteAttribute(LLVMValueRef, unsigned, LLVMRustAttribute);

// These tests never request Rust-owned string output.
extern "C" void LLVMRustStringWriteImpl(RustStringRef, const char *, size_t) {
  std::abort();
}

static void require(bool Condition) {
  if (!Condition)
    std::abort();
}

int main() {
  llvm::LLVMContext C;
  llvm::Module M("wrapper-test", C);
  LLVMRustSetNormalizedTarget(llvm::wrap(&M), "nvptx64-nvidia-cuda");
  require(M.getTargetTriple().str() == "nvptx64-nvidia-cuda");
  auto *Ptr = llvm::PointerType::get(C, 0);
  auto *FT = llvm::FunctionType::get(llvm::Type::getVoidTy(C), {Ptr}, false);
  auto *F = llvm::Function::Create(FT, llvm::GlobalValue::ExternalLinkage, "callee", M);
  auto CheckCapture = [](llvm::Attribute A) {
    require(A.isValid());
    require(A.getCaptureInfo() == llvm::CaptureInfo::none());
    require(A.getAsString() == "captures(none)");
  };
  LLVMRustAddFunctionAttribute(llvm::wrap(F), 1, NoCapture);
  CheckCapture(F->getAttributes().getParamAttr(0, llvm::Attribute::Captures));
  LLVMRustRemoveFunctionAttributes(llvm::wrap(F), 1, NoCapture);
  require(!F->hasParamAttribute(0, llvm::Attribute::Captures));
  LLVMRustAddFunctionAttributeWithType(llvm::wrap(F), 1, NoCapture, llvm::wrap(Ptr));
  CheckCapture(F->getAttributes().getParamAttr(0, llvm::Attribute::Captures));
  auto *Caller = llvm::Function::Create(FT, llvm::GlobalValue::ExternalLinkage, "caller", M);
  llvm::IRBuilder<> B(llvm::BasicBlock::Create(C, "entry", Caller));
  auto *Call = B.CreateCall(F, {Caller->getArg(0)});
  LLVMRustAddCallSiteAttribute(llvm::wrap(Call), 1, NoCapture);
  CheckCapture(Call->getAttributes().getParamAttr(0, llvm::Attribute::Captures));
  B.CreateRetVoid();
  require(!llvm::verifyModule(M, &llvm::errs()));
}
