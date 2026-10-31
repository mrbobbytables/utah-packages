#!/bin/bash
pushd sanity-test || exit
./runtest.sh
popd || exit
