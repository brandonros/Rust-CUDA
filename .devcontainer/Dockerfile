FROM nvidia/cuda:12.9.0-cudnn-devel-ubuntu24.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install \
    build-essential \
    clang \
    curl \
    libssl-dev \
    libtinfo-dev \
    pkg-config \
    xz-utils \
    zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Needed to build `path_tracer`, `optix/ex03_window` example
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install \
    cmake \
    libfontconfig-dev \
    libx11-xcb-dev \
    libxcursor-dev \
    libxi-dev \
    libxinerama-dev \
    libxrandr-dev && \
    rm -rf /var/lib/apt/lists/*

# Get Rust
RUN curl -sSf -L https://sh.rustup.rs | bash -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Setup the workspace
WORKDIR /data/Rust-CUDA
RUN --mount=type=bind,source=rust-toolchain.toml,target=/data/Rust-CUDA/rust-toolchain.toml \
    rustup show

# Add nvvm to LD_LIBRARY_PATH.
ENV LD_LIBRARY_PATH="/usr/local/cuda/nvvm/lib64:${LD_LIBRARY_PATH}"
ENV LLVM_LINK_STATIC=1
ENV RUST_LOG=info

# install git + miscellaneous
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install \
    git \
    gdb \
    lldb \
    psmisc \
    libzstd-dev && \
    rm -rf /var/lib/apt/lists/*

# ln -s /opt/llvm-19-debug/bin/llvm-config /usr/bin/llvm-config 
# export PATH="/opt/llvm-19-debug/bin:$PATH"