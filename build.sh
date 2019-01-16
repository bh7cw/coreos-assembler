#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
  echo Usage: "build.sh CMD"
  echo "Supported commands:"
  echo "    configure_user"
  echo "    configure_yum_repos"
  echo "    configure_yum_repos_rhel"
  echo "    install_rpms"
  echo "    install_rpms_rhel"
  echo "    make_and_makeinstall"
  echo "    make_and_makeinstall_rhel"
  exit 1
fi

set -x
srcdir=$(pwd)

configure_yum_repos() {

    # Enable FAHC https://pagure.io/fedora-atomic-host-continuous
    # so we have ostree/rpm-ostree git master for our :latest
    # NOTE: The canonical copy of this code lives in rpm-ostree's CI:
    # https://github.com/projectatomic/rpm-ostree/blob/d2b0e42bfce972406ac69f8e2136c98f22b85fb2/ci/build.sh#L13
    # Please edit there first
    echo -e '[fahc]\nmetadata_expire=1m\nbaseurl=https://ci.centos.org/artifacts/sig-atomic/fahc/rdgo/build/\ngpgcheck=0\n' > /etc/yum.repos.d/fahc.repo
    # Until we fix https://github.com/rpm-software-management/libdnf/pull/149
    excludes='exclude=ostree ostree-libs ostree-grub2 rpm-ostree'
    for repo in /etc/yum.repos.d/fedora*.repo; do
        # reworked to remove useless `cat` - https://github.com/koalaman/shellcheck/wiki/SC2002
        (while read -r line; do if echo "$line" | grep -qE -e '^enabled=1'; then echo "${excludes}"; fi; echo "$line"; done < "${repo}") > "${repo}".new
        mv "${repo}".new "${repo}"
    done

    # enable `dustymabe/ignition` copr
    # pulled from https://copr.fedorainfracloud.org/coprs/dustymabe/ignition/repo/fedora-28/dustymabe-ignition-fedora-28.repo
    cat > /etc/yum.repos.d/dustymabe-ignition-fedora-28.repo <<'EOF'
[dustymabe-ignition]
name=Copr repo for ignition owned by dustymabe
baseurl=https://copr-be.cloud.fedoraproject.org/results/dustymabe/ignition/fedora-$releasever-$basearch/
type=rpm-md
skip_if_unavailable=True
gpgcheck=1
gpgkey=https://copr-be.cloud.fedoraproject.org/results/dustymabe/ignition/pubkey.gpg
repo_gpgcheck=0
enabled=1
enabled_metadata=1
EOF
}

configure_yum_repos_rhel() {
    # Until we fix https://github.com/rpm-software-management/libdnf/pull/149
    excludes='exclude=ostree ostree-libs ostree-grub2 rpm-ostree'
    for repo in /etc/yum.repos.d/*.repo; do
        # reworked to remove useless `cat` - https://github.com/koalaman/shellcheck/wiki/SC2002
        (while read -r line; do if echo "$line" | grep -qE -e '^enabled=1'; then echo "${excludes}"; fi; echo "$line"; done < "${repo}") > "${repo}".new
        mv "${repo}".new "${repo}"
    done
}


install_rpms() {

    # First, a general update; this is best practice.  We also hit an issue recently
    # where qemu implicitly depended on an updated libusbx but didn't have a versioned
    # requires https://bugzilla.redhat.com/show_bug.cgi?id=1625641
    dnf -y distro-sync

    # xargs is part of findutils, which may not be installed
    dnf -y install /usr/bin/xargs

    # These are only used to build things in here.  Today
    # we ship these in the container too to make it easier
    # to use the container as a development environment for itself.
    # Down the line we may strip these out, or have a separate
    # development version.
    self_builddeps=$(grep -v '^#' "${srcdir}"/build-deps.txt)

    # Process our base dependencies + build dependencies
    (echo "${self_builddeps}" && grep -v '^#' "${srcdir}"/deps.txt) | xargs dnf -y install

    # Commented out for now, see above
    #dnf remove -y ${self_builddeps}
    rpm -q grubby && dnf remove -y grubby
    # Further cleanup
    dnf clean all
}


install_rpms_rhel() {
    # First, a general update; this is best practice.  We also hit an issue recently
    # where qemu implicitly depended on an updated libusbx but didn't have a versioned
    # requires https://bugzilla.redhat.com/show_bug.cgi?id=1625641
    yum -y distro-sync

    # xargs is part of findutils, which may not be installed
    yum -y install /usr/bin/xargs

    # These are only used to build things in here.  Today
    # we ship these in the container too to make it easier
    # to use the container as a development environment for itself.
    # Down the line we may strip these out, or have a separate
    # development version.
    self_builddeps=$(grep -v '^#' "${srcdir}"/build-deps-rhel.txt)

    # Process our base dependencies + build dependencies
    (echo "${self_builddeps}" && grep -v '^#' "${srcdir}"/deps-rhel.txt) | xargs yum -y install

    # Commented out for now, see above
    #dnf remove -y ${self_builddeps}
    rpm -q grubby && yum remove -y grubby

    # Further cleanup
    yum clean all
}

_prep_make_and_make_install() {
    # Work around https://github.com/coreos/coreos-assembler/issues/27
    if ! test -d .git; then
        (git config --global user.email dummy@example.com
         git init && git add . && git commit -a -m 'dummy commit'
         git tag -m tag dummy-tag) >/dev/null
    fi

    # TODO: install these as e.g.
    # /usr/bin/ostree-releng-script-rsync-repos
    mkdir -p /usr/app/
    rsync -rlv "${srcdir}"/ostree-releng-scripts/ /usr/app/ostree-releng-scripts/

    if ! test -f mantle/README.md; then
        echo -e "\033[1merror: submodules not initialized. Run: git submodule update --init\033[0m" 1>&2
        exit 1
    fi
}

make_and_makeinstall() {
    _prep_make_and_make_install
    # And the main scripts
    make && make check && make install
}

make_and_makeinstall_rhel() {
    _prep_make_and_make_install
    # Copy our scl enabling script
    cp "${srcdir}"/scl-coreos-assembler /usr/bin/
    # And the main scripts through scl (for make check)
    echo "make && make check && make install" | scl enable rh-python36 bash
}


configure_user(){

    # We want to run what builds we can as an unprivileged user;
    # running as non-root is much better for the libvirt stack in particular
    # for the cases where we have --privileged in the container run for other reasons.
    # At some point we may make this the default.
    useradd builder -G wheel
    echo '%wheel ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers.d/wheel-nopasswd
}

# Run the function specified by the calling script
${1}
