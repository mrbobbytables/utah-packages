#!/usr/bin/bash
set -u

# helper functions
vcmp_lt () {
    # argument $1 is less than $2
    MV=$(echo "$@" | tr " " "\n" | sort -rV | head -n1)
    test "$1" != "$MV"
}

# main script
IT="${1:-source/tests/test-integration}"

# check if we need to install additional packages
# which is the case if we are on RHEL 8
source /etc/os-release || exit 1

if [[ "$ID" = *"rhel"* ]] && [[ "$VERSION_ID" == *"8"* ]]; then
    dnf config-manager -y --add-repo umockdev.repo
    dnf install -y umockdev-devel python3-gobject-base
    pip3 install python-dbusmock
fi

BOLT_VERSION=$(boltctl --version | cut -d " " -f2)

# check if we can even discover the tests
"$IT" list-tests > /dev/null || exit 1

# The format of "list-tests" changed with 0.6
if vcmp_lt $BOLT_VERSION 0.6; then
    echo "Old style integration test names"
    DELIM=" "
else
    DELIM=$'\n'
fi

# discover all the tests
declare -a TESTS=()
while IFS= read -r -d "$DELIM" line; do
    TESTS+=( "${line% *}" )
done < <( $IT list-tests )

# execute all the tests, one by one
RESULT=0
for test in ${TESTS[@]}; do
    echo "$test"
    umockdev-wrapper "$IT" "$test"
    ((RESULT += $?))
done

exit $RESULT
