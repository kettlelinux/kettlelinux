#!/bin/sh
# Amethyst Mod Manager launcher, as upstream's own: the CLI's commands go to cli.py, the rest to
# the Qt app. XWayland (xcb) unless the user chose a platform: under native Wayland Qt mis-places
# tooltips; the marker tells the app the choice is ours, so it keeps it from what it launches.
APP=/usr/share/amethyst-mod-manager
export AMETHYST_DISTRO_PACKAGE=1
if [ -z "${QT_QPA_PLATFORM:-}" ]; then
  QT_QPA_PLATFORM=xcb
  _AMM_OWNS_QT_PLATFORM=1
  export _AMM_OWNS_QT_PLATFORM
fi
export QT_QPA_PLATFORM
case "${1:-}" in
  deploy|launch|restore|list-games|list-profiles|clear-credentials|export-filemap)
    exec python3 "$APP/cli.py" "$@" ;;
  *)
    exec python3 "$APP/run_qt.py" "$@" ;;
esac
