#!/bin/bash

CURR_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

export SYSTEMC_HOME="$CURR_DIR/systemc/2.3.4"
export YAML_HOME="$CURR_DIR/yaml-cpp"

if [ -d "$SYSTEMC_HOME/lib64" ]; then
  SYSTEMC_LIB="$SYSTEMC_HOME/lib64"
else
  SYSTEMC_LIB="$SYSTEMC_HOME/lib"
fi

if [ -d "$YAML_HOME/lib64" ]; then
  YAML_LIB="$YAML_HOME/lib64"
else
  YAML_LIB="$YAML_HOME/lib"
fi

export SYSTEMC_LIB
export YAML_LIB
export LD_LIBRARY_PATH="$SYSTEMC_LIB:$YAML_LIB:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$SYSTEMC_LIB:$YAML_LIB:${LIBRARY_PATH:-}"

