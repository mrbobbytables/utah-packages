#!/usr/bin/bash


VERSION=$1

if [ "${VERSION:="*"}" == "*" ]
then
  echo "Define a version of hplip as an argument."
  exit 1
fi

# extract the original tarball
tar -xaf hplip-$VERSION.tar.gz || exit 1

# remove unwanted files - license-related ones reported here https://bugs.launchpad.net/hplip/+bug/2028938
rm hplip-$VERSION/locatedriver

# compress into a new tarball
tar -cjvf hplip-$VERSION-repack.tar.gz hplip-$VERSION || exit 1

# check whether plugin is available
wget -O hplip-plugin.run https://www.openprinting.org/download/printdriver/auxfiles/HP/plugins/hplip-$1-plugin.run || wget --user-agent='Mozilla/5.0 (compatible; hplip-plugin/1.0)' -O hplip-plugin.run https://developers.hp.com/sites/default/files/2026-05/hplip-$1-plugin.run || exit 1

# check whether the file is sane
file --mime hplip-plugin.run | grep 'x-shellscript' || exit 1

echo "hplip-${VERSION}-repack.tar.gz is prepared for uploading..."

exit 0

# upload a new source tarball
#fedpkg new-sources hplip-$VERSION-repack.tar.gz || exit 1
