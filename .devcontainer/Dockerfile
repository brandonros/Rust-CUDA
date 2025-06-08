FROM ghcr.io/rust-gpu/rust-cuda-ubuntu24-cuda12:latest
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install \
    git && \
    rm -rf /var/lib/apt/lists/*
