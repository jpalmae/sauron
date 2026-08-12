#!/bin/sh
set -eu

mkdir -p /models/tao
cp --update=none /opt/sauron/tao-seed/* /models/tao/

exec /opt/sauron/bin/sauron-deepstream
