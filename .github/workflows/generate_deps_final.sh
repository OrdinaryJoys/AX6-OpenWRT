#!/bin/bash
set -euo pipefail

# 确保基础工具存在
ensure_dependencies() {
  local missing=()
  for tool in "lsb_release" "dpkg" "apt-cache"; do
    if ! command -v "$tool" &> /dev/null; then
      missing+=("$tool")
    fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "安装基础工具: ${missing[*]}"
    sudo apt update -y >/dev/null
    sudo apt install -y "${missing[@]}" >/dev/null
  fi
}

# 检测环境（架构+版本）
detect_environment() {
  ARCH=$(dpkg --print-architecture)
  UBUNTU_VERSION=$(lsb_release -r | awk '{print $2}' | cut -d. -f1)
  echo "===== 环境检测 ====="
  echo "架构: $ARCH"
  echo "Ubuntu版本: $UBUNTU_VERSION.04"
  echo "===================="
}

# 适配源（arm64需ports.ubuntu.com）
adapt_sources() {
  if [ "$ARCH" = "arm64" ] && ! grep -q "ports.ubuntu.com" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null; then
    echo "arm64架构，添加专用源..."
    sudo cp /etc/apt/sources.list.d/ubuntu.sources{,.bak} 2>/dev/null || true
    echo "Types: deb
URIs: http://ports.ubuntu.com/ubuntu-ports
Suites: $(lsb_release -cs) $(lsb_release -cs)-updates $(lsb_release -cs)-backports $(lsb_release -cs)-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" | sudo tee /etc/apt/sources.list.d/ubuntu.sources >/dev/null
    sudo apt update -y >/dev/null
  fi
}

# 定义OpenWRT编译必需的依赖
define_dependencies() {
  # 通用依赖（OpenWRT编译基础工具）
  COMMON_DEPS=(
    # 基础编译工具
    "build-essential" "gcc" "g++" "make" "cmake" "ninja-build"
    # 版本控制与下载工具
    "git" "subversion" "mercurial" "wget" "curl" "rsync"
    # 解析与压缩工具
    "flex" "bison" "gawk" "patch" "diffutils" "unzip" "zip" "tar" "xz-utils" "zlib1g-dev"
    # 库文件（OpenWRT核心依赖）
    "libssl-dev" "libncurses5-dev" "libncursesw5-dev" "libreadline-dev" "libelf-dev"
    "libpcre3-dev" "libjson-c-dev" "libsqlite3-dev" "libudev-dev"
    # Python相关（脚本支持）
    "python3" "python3-dev" "python3-pip" "python3-setuptools" "python-is-python3"
  )

  # 架构专属依赖（32位兼容库等）
  declare -A ARCH_DEPS
  ARCH_DEPS["amd64"]="libc6-dev-i386 lib32z1-dev gcc-multilib g++-multilib"
  ARCH_DEPS["arm64"]="libc6-dev-armhf-cross"  # arm64编译32位兼容库

  # 版本专属依赖（UUID相关）
  if [ "$UBUNTU_VERSION" -ge 24 ]; then
    UUID_DEP="libutil-linux-dev"
  else
    UUID_DEP="libuuid-dev"
  fi

  # 合并去重
  ALL_DEPS=($(printf "%s\n" "${COMMON_DEPS[@]}" "${ARCH_DEPS[$ARCH]}" "$UUID_DEP" | sort -u))
}

# 验证依赖是否适配当前架构
validate_dependencies() {
  echo "验证依赖适配性..."
  local missing=()
  for pkg in "${ALL_DEPS[@]}"; do
    if ! apt-cache show "$pkg" 2>/dev/null | grep -q "Architecture: $ARCH\|Architecture: all"; then
      missing+=("$pkg")
    fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "错误：以下包在 $ARCH 架构中不存在"
    echo "  ${missing[*]}" && exit 1
  fi
}

# 生成deps.txt
generate_deps_file() {
  printf "%s\n" "${ALL_DEPS[@]}" > "deps.txt"
  echo "生成依赖文件: deps.txt（共${#ALL_DEPS[@]}个包）"
}

# 主流程
main() {
  ensure_dependencies
  detect_environment
  adapt_sources
  define_dependencies
  validate_dependencies
  generate_deps_file
}

main
