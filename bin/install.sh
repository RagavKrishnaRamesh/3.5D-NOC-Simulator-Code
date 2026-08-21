#!/bin/bash

set -e

JOBS=4

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# export SYSTEMC_HOME and YAML_HOME
source "$SCRIPT_DIR/env.sh"

#  compile YAML-cpp
if [ ! -d "$YAML_HOME/.git" ]; then
  git clone https://github.com/jbeder/yaml-cpp "$YAML_HOME"
fi
cd "$YAML_HOME"
git checkout -B r0.6.0 yaml-cpp-0.6.0
mkdir -p "$YAML_LIB" && cd "$YAML_LIB"
cmake "$YAML_HOME"
make -j"$JOBS"

#  compile and install SystemC
SYSTEMC_SRC_DIR="$SYSTEMC_HOME/src-build"
SYSTEMC_BUILD_DIR="$SYSTEMC_SRC_DIR/build"
SYSTEMC_INSTALL_DIR="$SYSTEMC_HOME"
SYSTEMC_URL=https://github.com/accellera-official/systemc/archive/refs/tags/2.3.4.tar.gz
mkdir -p "$SYSTEMC_SRC_DIR" && cd "$SYSTEMC_SRC_DIR"
if [ ! -d "$SYSTEMC_SRC_DIR/systemc-2.3.4" ]; then
  wget -qO- "$SYSTEMC_URL" | tar xvz -C "$SYSTEMC_SRC_DIR"
fi
mkdir -p "$SYSTEMC_BUILD_DIR" && cd "$SYSTEMC_BUILD_DIR"
cmake -DCMAKE_CXX_STANDARD=14 -DCMAKE_INSTALL_PREFIX="$SYSTEMC_INSTALL_DIR" ../systemc-2.3.4
make -j"$JOBS"
make install

#sudo ln -sf `pwd`/systemc.conf /etc/ld.so.conf.d/noxim_systemc.conf
#sudo ldconfig

#  compile Noxim
#cd $SCRIPT_DIR
#make -j$JOBS

#./noxim -config ../config_examples/default_config.yaml
