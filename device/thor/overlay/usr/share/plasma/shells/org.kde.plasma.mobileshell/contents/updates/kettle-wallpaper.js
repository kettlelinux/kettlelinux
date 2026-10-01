// Kettle Linux: the bottom screen's shell (bottom-shell) has the Kettle wallpaper too. Its Plasma
// theme (Breeze, "default") names Next as its default wallpaper, which comes before
// /etc/xdg/plasmarc (kettle-wallpaper), so it is set here instead. Plasma runs this once per
// user, after the shell's first layout; a wallpaper picked in the shell's settings is kept.
const kettle = "file:///usr/share/wallpapers/Kettle/";
for (const desktop of desktops()) {
    if (desktop.wallpaperPlugin !== "org.kde.image") {
        continue;
    }
    desktop.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    if (!desktop.readConfig("Image")) {
        desktop.writeConfig("Image", kettle);
    }
}
