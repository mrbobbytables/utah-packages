%global gtk4_version 4.23.4
%global glibmm_version 2.90.0
%global gtkmm_version 4.24.0
%global libadwaita_version 1.8~beta
%global libgtop2_version 2.41.2
# These floors intentionally exceed Fedora's imported recipe: glibmm 2.90
# fixes Gio wrappers for GLib final types, and gtkmm 4.24 fixes GdkCursor
# wrappers. Preserve them on re-import; the buildroot's older wrappers fail
# against those final types.

Name:           gnome-system-monitor
Version:        51.1
Release:        %autorelease
Summary:        Process and resource monitor

License:        GPL-2.0-or-later AND CC-BY-SA-3.0 AND CC0-1.0
URL:            https://wiki.gnome.org/Apps/SystemMonitor
Source0:        https://download.gnome.org/sources/%{name}/51/%{name}-%{version}.tar.xz

BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  meson
BuildRequires:  pkgconfig(catch2-with-main)
BuildRequires:  pkgconfig(giomm-2.68) >= %{glibmm_version}
BuildRequires:  pkgconfig(gtk4) >= %{gtk4_version}
BuildRequires:  pkgconfig(gtkmm-4.0) >= %{gtkmm_version}
BuildRequires:  pkgconfig(libadwaita-1) >= %{libadwaita_version}
BuildRequires:  pkgconfig(libgtop-2.0) >= %{libgtop2_version}
BuildRequires:  pkgconfig(libsystemd)
BuildRequires:  pkgconfig(librsvg-2.0)
BuildRequires:  pkgconfig(libxml-2.0)
BuildRequires:  desktop-file-utils
BuildRequires:  gettext
BuildRequires:  itstool

Requires:       hicolor-icon-theme
Requires:       gtk4%{?_isa} >= %{gtk4_version}
Requires:       glibmm2.68%{?_isa} >= %{glibmm_version}
Requires:       gtkmm4.0%{?_isa} >= %{gtkmm_version}
Requires:       libadwaita%{?_isa} >= %{libadwaita_version}
Requires:       libgtop2%{?_isa} >= %{libgtop2_version}

%description
GNOME System Monitor allows users to graphically view and manipulate running
processes and provides an overview of available resources such as CPU and memory.

%prep
%autosetup -p1 -n %{name}-%{version}

%build
%meson
%meson_build

%install
%meson_install
%find_lang %{name} --with-gnome

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/org.gnome.SystemMonitor.desktop
desktop-file-validate %{buildroot}%{_datadir}/applications/gnome-system-monitor-kde.desktop

%files -f %{name}.lang
%license COPYING
%doc AUTHORS NEWS README.md
%{_bindir}/gnome-system-monitor
%{_datadir}/applications/org.gnome.SystemMonitor.desktop
%{_datadir}/applications/gnome-system-monitor-kde.desktop
%{_datadir}/dbus-1/services/org.gnome.SystemMonitor.service
%{_datadir}/glib-2.0/schemas/org.gnome.gnome-system-monitor.enums.xml
%{_datadir}/glib-2.0/schemas/org.gnome.gnome-system-monitor.gschema.xml
%{_datadir}/icons/hicolor/scalable/apps/org.gnome.SystemMonitor*.svg
%{_datadir}/icons/hicolor/symbolic/apps/org.gnome.SystemMonitor-symbolic.svg
%{_datadir}/icons/hicolor/symbolic/apps/processes-symbolic.svg
%{_datadir}/icons/hicolor/symbolic/apps/resources-symbolic.svg
%{_metainfodir}/org.gnome.SystemMonitor.metainfo.xml
%{_datadir}/polkit-1/actions/org.gnome.gnome-system-monitor.policy
%{_libexecdir}/gnome-system-monitor/

%changelog
%autochangelog
