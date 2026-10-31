#!/bin/sh

VERSION=0.5.3

rm -rf vpnc-${VERSION}

svn export http://svn.unix-ag.uni-kl.de/vpnc/trunk vpnc-${VERSION}
SVN_REV=$(LANG=C svn info http://svn.unix-ag.uni-kl.de/vpnc/trunk | grep 'Revision: ' | cut -d ' ' -f2)

TARFILE=vpnc-${VERSION}.svn${SVN_REV}.tar.gz
rm -f "${TARFILE}"

tar -czf "${TARFILE}" vpnc-${VERSION}
rm -rf vpnc-${VERSION}

