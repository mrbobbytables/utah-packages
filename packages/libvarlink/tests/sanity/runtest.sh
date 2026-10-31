#!/bin/bash
# Include Beaker environment
. /usr/share/beakerlib/beakerlib.sh || exit 1

PACKAGE="libvarlink"

rlJournalStart
    rlPhaseStartSetup
        rlAssertRpm $PACKAGE
        rlRun "mkdir -p $HOME/.cargo/bin; cargo install --git https://github.com/varlink/rust varlink-certification"
    rlPhaseEnd

    rlPhaseStartTest
        rlLog "Starting test ..."
        rlRun "varlink --bridge \"varlink --bridge \\\"varlink -A '~/.cargo/bin/varlink-certification --varlink=\\\\\\\$VARLINK_ADDRESS' bridge\\\" bridge\" info | fgrep -q org.varlink.certification"
    rlPhaseEnd

    rlPhaseStartCleanup
       rlLog "libvarlink tests done"
       rlRun "rm -rf  $HOME/.cargo"
    rlPhaseEnd
rlJournalPrintText
rlJournalEnd

rlGetTestState
