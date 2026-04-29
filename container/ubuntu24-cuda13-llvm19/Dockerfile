FROM nvcr.io/nvidia/cuda:13.0.2-cudnn-devel-ubuntu24.04 AS llvm-builder

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install \
    build-essential \
    clang \
    curl \
    libffi-dev \
    libedit-dev \
    libncurses5-dev \
    libssl-dev \
    libtinfo-dev \
    libxml2-dev \
    cmake \
    ninja-build \
    pkg-config \
    python3 \
    xz-utils \
    zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /data/llvm19

# Download and build LLVM 19.1.7 (the active LLVM 19 pin used by `rustc_codegen_nvvm`).
# LLVM 8+ ships as a monorepo tarball; cmake source root is the `llvm/` subdir.
RUN curl -sSf -L -O https://github.com/llvm/llvm-project/releases/download/llvmorg-19.1.7/llvm-project-19.1.7.src.tar.xz && \
    tar -xf llvm-project-19.1.7.src.tar.xz && \
    cd llvm-project-19.1.7.src && \
    mkdir build && cd build && \
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        TARGETS="X86;NVPTX"; \
    else \
        TARGETS="AArch64;NVPTX"; \
    fi && \
    cmake -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLVM_TARGETS_TO_BUILD="$TARGETS" \
        -DLLVM_BUILD_LLVM_DYLIB=ON \
        -DLLVM_LINK_LLVM_DYLIB=ON \
        -DLLVM_ENABLE_ASSERTIONS=OFF \
        -DLLVM_ENABLE_BINDINGS=OFF \
        -DLLVM_INCLUDE_EXAMPLES=OFF \
        -DLLVM_INCLUDE_TESTS=OFF \
        -DLLVM_INCLUDE_BENCHMARKS=OFF \
        -DLLVM_ENABLE_ZLIB=ON \
        -DLLVM_ENABLE_TERMINFO=ON \
        -DCMAKE_INSTALL_PREFIX=/opt/llvm-19 \
        ../llvm && \
    ninja -j$(nproc) && \
    ninja install && \
    cd ../.. && \
    rm -rf llvm-project-19.1.7.src*

FROM nvcr.io/nvidia/cuda:13.0.2-cudnn-devel-ubuntu24.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install \
    build-essential \
    clang \
    curl \
    libssl-dev \
    libtinfo-dev \
    pkg-config \
    xz-utils \
    zlib1g-dev \
    cmake \
    libfontconfig-dev \
    libx11-xcb-dev \
    libxcursor-dev \
    libxi-dev \
    libxinerama-dev \
    libxrandr-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=llvm-builder /opt/llvm-19 /opt/llvm-19
RUN ln -s /opt/llvm-19/bin/llvm-config /usr/bin/llvm-config && \
    ln -s /opt/llvm-19/bin/llvm-config /usr/bin/llvm-config-19 && \
    ln -s /opt/llvm-19/bin/llvm-as /usr/bin/llvm-as-19

# Get Rust (install rustup; toolchain installed from rust-toolchain.toml below)
RUN curl -sSf -L https://sh.rustup.rs | bash -s -- -y --profile minimal --default-toolchain none
ENV PATH="/root/.cargo/bin:${PATH}"

# Setup the workspace
WORKDIR /data/rust-cuda
RUN --mount=type=bind,source=rust-toolchain.toml,target=/data/rust-cuda/rust-toolchain.toml \
    rustup show

# Add nvvm + LLVM 19 dylib to the runtime linker path.
ENV LD_LIBRARY_PATH="/opt/llvm-19/lib:/usr/local/cuda/nvvm/lib64:${LD_LIBRARY_PATH}"

# `rustc_codegen_nvvm`'s build.rs probes `LLVM_CONFIG_19` to locate the LLVM 19
# toolchain when the `llvm19` cargo feature is on. The feature itself is gated;
# downstream crates that depend on `cuda_builder` must build with
# `--features llvm19` for this to take effect — that propagates through to
# `nvvm/llvm19` (default `NvvmArch` = Blackwell) and `rustc_codegen_nvvm/llvm19`
# (LLVM 19 codegen path) per crates/cuda_builder/Cargo.toml.
ENV LLVM_CONFIG_19=/opt/llvm-19/bin/llvm-config
ENV LLVM_LINK_STATIC=1
ENV RUST_LOG=info
