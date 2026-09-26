# Kettle Linux: Plasma starts with the Kettle splash screen (kettle-plasma-splash). Sourced by
# startplasma before the splash. Plasma copies the global theme's splash (Valve's Vapor, which
# has none) into ~/.config/kdedefaults, ahead of /etc/xdg, so the choice goes in the user's own
# ksplashrc; only when there is none, so a splash picked in System Settings is kept.
kettle_ksplashrc="${XDG_CONFIG_HOME:-$HOME/.config}/ksplashrc"
if [ ! -e "$kettle_ksplashrc" ]; then
  mkdir -p "$(dirname "$kettle_ksplashrc")"
  printf '[KSplash]\nEngine=KSplashQML\nTheme=org.kettle.splash\n' >"$kettle_ksplashrc"
fi
unset kettle_ksplashrc
