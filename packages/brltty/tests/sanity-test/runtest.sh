#!/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
#   runtest.sh of /CoreOS/brltty/Sanity/sanity-test
#   Description: it check basic sanity of packahe
#   Author: Jan Scotka <jscotka@redhat.com>
#
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
#   Copyright (c) 2016 Red Hat, Inc.
#
#   This copyrighted material is made available to anyone wishing
#   to use, modify, copy, or redistribute it subject to the terms
#   and conditions of the GNU General Public License version 2.
#
#   This program is distributed in the hope that it will be
#   useful, but WITHOUT ANY WARRANTY; without even the implied
#   warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
#   PURPOSE. See the GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public
#   License along with this program; if not, write to the Free
#   Software Foundation, Inc., 51 Franklin Street, Fifth Floor,
#   Boston, MA 02110-1301, USA.
#
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Include Beaker environment
. /usr/bin/rhts-environment.sh || exit 1
. /usr/share/beakerlib/beakerlib.sh || exit 1

PACKAGE="brltty"
DISPLAY=99

rlJournalStart
    rlPhaseStartSetup
        rlAssertRpm $PACKAGE
        rlRun "Xvfb :$DISPLAY -screen 0 1024x768x24&"
        rlRun "sleep 5"
    rlPhaseEnd

    rlPhaseStartTest
        rlRun "DISPLAY=:$DISPLAY orca&"
        rlRun "sleep 5"
        rlRun "sleep 5"
        rlRun "DISPLAY=:$DISPLAY brltty -b xw -x a2 -A auth=none"
        rlRun "sleep 5"
        rlRun "BRPID=`pidof brltty`"
        rlRun "cat /proc/$BRPID/cmdline"
        rlRun "DISPLAY=:$DISPLAY import -window root example.png"
        rlRun "DISPLAY=:$DISPLAY xwininfo -tree -root"
        #rlRun "DISPLAY=:$DISPLAY xwininfo -tree -root| grep -A 2 children |grep brltty"
        #rlRun "DISPLAY=:$DISPLAY xwininfo -tree -root|grep +664+36"
        rlRun "killall brltty"
        rlRun "sleep 5"
        rlRun "DISPLAY=:$DISPLAY brltty -b vr -d server:127.0.0.1 -x a2 -A auth=none"
        rlRun "sleep 5"
        rlRun "echo cells 20 | ncat 127.0.0.1 35752 |grep 'Visual \"BRLTTY'"
        rlRun "echo cells 20 | ncat 127.0.0.1 35752 |grep '127.12357.1237.23457.23457.134567'"
        rlRun "echo quit | ncat 127.0.0.1 35752"
        rlRun "sleep 2"
        rlRun "test -x /usr/bin/brltty-config"
        rlRun "brltty-config"
    rlPhaseEnd

    rlPhaseStartCleanup
        rlRun "killall brltty"
        rlRun "killall Xvfb"
        rlFileSubmit example.png
    rlPhaseEnd
rlJournalPrintText
rlJournalEnd

