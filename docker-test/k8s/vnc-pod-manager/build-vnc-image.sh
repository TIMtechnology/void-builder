#!/bin/bash

# Build VNC Desktop Docker image for linux/amd64 platform

set -e

# Configuration
DOCKER_REGISTRY="192.168.10.252:31832"
IMAGE_NAME="vnc/void-desktop"
IMAGE_TAG="latest"
DOCKERFILE_PATH="../../Dockerfile"

# Check for --no-cache parameter
NO_CACHE=""
if [[ "$1" == "--no-cache" ]]; then
    NO_CACHE="--no-cache"
fi

# Nexus registry credentials
NEXUS_USER="admin"
NEXUS_PASSWORD="thinkgs123"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect architecture
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
    print_warn "Detected ARM64 architecture, will build for AMD64 platform"
    export DOCKER_DEFAULT_PLATFORM=linux/amd64
    BUILD_PLATFORM="--platform linux/amd64"
else
    print_info "Detected AMD64 architecture"
    BUILD_PLATFORM=""
fi

# Login to registry
print_info "Logging in to Docker registry..."
echo "${NEXUS_PASSWORD}" | docker login ${DOCKER_REGISTRY} -u ${NEXUS_USER} --password-stdin
if [ $? -eq 0 ]; then
    print_info "Successfully logged in to registry"
else
    print_error "Failed to login to registry"
    exit 1
fi

# Check if Dockerfile exists
if [ ! -f "${DOCKERFILE_PATH}" ]; then
    print_error "Dockerfile not found at ${DOCKERFILE_PATH}"
    print_info "Trying alternative location..."
    
    # Try current directory
    if [ -f "Dockerfile" ]; then
        DOCKERFILE_PATH="Dockerfile"
    else
        print_error "Cannot find Dockerfile"
        exit 1
    fi
fi

# Build the VNC image
if [ -n "${NO_CACHE}" ]; then
    print_info "Building VNC Desktop image for linux/amd64 with --no-cache (forcing rebuild to get latest Void version)..."
else
    print_info "Building VNC Desktop image for linux/amd64..."
fi
print_info "Using Dockerfile: ${DOCKERFILE_PATH}"

# Get the directory containing the Dockerfile
DOCKER_CONTEXT=$(dirname "${DOCKERFILE_PATH}")

# Build the image
docker build ${BUILD_PLATFORM} ${NO_CACHE} \
    -t ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} \
    -f ${DOCKERFILE_PATH} \
    ${DOCKER_CONTEXT}

if [ $? -eq 0 ]; then
    print_info "Successfully built VNC image"
else
    print_error "Failed to build VNC image"
    exit 1
fi

# Push the image
print_info "Pushing VNC image to registry..."
docker push ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}

if [ $? -eq 0 ]; then
    print_info "Successfully pushed VNC image to registry"
    print_info "Image available at: ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
else
    print_error "Failed to push VNC image"
    exit 1
fi

# Verify the image architecture
print_info "Verifying image architecture..."
docker inspect ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} --format='Architecture: {{.Architecture}}, OS: {{.Os}}' || true

print_info "✅ VNC Desktop image build completed successfully!"
print_info "Image: ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"