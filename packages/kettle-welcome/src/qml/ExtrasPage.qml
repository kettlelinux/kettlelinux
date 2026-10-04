// SPDX-License-Identifier: BSD-3-Clause
// Gaming Extras: optional apps from Flathub, installed for this user only. Every app listed
// has an aarch64 build on Flathub; x86-only ones (PCSX2, DuckStation, Cemu, Bottles, ...) are
// left out. The installs run in welcome-flatpak, outside this window, so closing it is fine.
// Below them, Battle.net (BattleNetSection, welcome-battlenet) and community Proton builds for
// Steam (ProtonSection, welcome-proton).
// Game Mode's Welcome (kettle-decky-plugins welcome/src/extras.tsx) offers the ones that work with
// a controller: keep the two lists in step.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.kettle.welcome

BasePage {
    id: page

    title: "Gaming Extras"
    heading: "Gaming Extras"
    description: "Optional apps for gaming beyond the Steam library: emulators, game streaming, and tools that bring other games into Steam. Tick what you want and press Install. The apps come from Flathub and are installed for your user only; you can remove them any time in Discover."

    // suggested: ticked to begin with
    readonly property var groups: [
        { title: "Steam helpers and tools", apps: [
            { id: "io.github.philipk.boilr", name: "BoilR", suggested: true,
              description: "Adds games from Lutris, Heroic, emulators and other launchers to your Steam library, with artwork, so they show up in Game Mode." },
            { id: "com.github.mtkennerly.ludusavi", name: "Ludusavi", suggested: true,
              description: "Backs up and restores save games, for Steam and other launchers." },
            { id: "net.davidotek.pupgui2", name: "ProtonUp-Qt",
              description: "Installs and updates extra compatibility tools for Steam, Lutris and Heroic." },
            { id: "com.steamgriddb.SGDBoop", name: "SGDBoop",
              description: "Applies artwork from SteamGridDB to games in your Steam library in one click." },
            { id: "io.github.antimicrox.antimicrox", name: "AntiMicroX",
              description: "Maps controller buttons to keyboard keys and the mouse, for games without controller support." },
            { id: "io.github.benjamimgois.goverlay", name: "GOverlay",
              description: "Settings for the MangoHud performance overlay." },
            { id: "com.github.tchx84.Flatseal", name: "Flatseal",
              description: "Changes what installed Flatpak apps may access, for example a game folder on the microSD card." },
            { id: "io.github.flattool.Warehouse", name: "Warehouse",
              description: "Manages Flatpak apps and their data: clean up, downgrade, back up." }
        ] },
        { title: "Emulators", apps: [
            { id: "org.libretro.RetroArch", name: "RetroArch", suggested: true,
              description: "One app for many classic consoles, through downloadable emulator cores." },
            { id: "org.DolphinEmu.dolphin-emu", name: "Dolphin", description: "Nintendo GameCube and Wii." },
            { id: "org.ppsspp.PPSSPP", name: "PPSSPP", description: "Sony PlayStation Portable." },
            { id: "org.azahar_emu.Azahar", name: "Azahar", description: "Nintendo 3DS." },
            { id: "net.kuribo64.melonDS", name: "melonDS", description: "Nintendo DS." },
            { id: "io.github.ryubing.Ryujinx", name: "Ryujinx", description: "Nintendo Switch." },
            { id: "net.rpcs3.RPCS3", name: "RPCS3", description: "Sony PlayStation 3. Demanding: many games run slowly on a handheld." },
            { id: "app.xemu.xemu", name: "xemu", description: "The original Microsoft Xbox." },
            { id: "org.flycast.Flycast", name: "Flycast", description: "Sega Dreamcast, Naomi and Atomiswave." },
            { id: "com.github.Rosalie241.RMG", name: "Rosalie's Mupen GUI", description: "Nintendo 64." },
            { id: "io.mgba.mGBA", name: "mGBA", description: "Game Boy Advance, Game Boy and Game Boy Color." },
            { id: "org.mamedev.MAME", name: "MAME", description: "Arcade machines and many vintage computers." },
            { id: "org.scummvm.ScummVM", name: "ScummVM", description: "Classic point-and-click adventures, using the original game data." },
            { id: "io.github.dosbox-staging", name: "DOSBox Staging", description: "DOS games." }
        ] },
        { title: "Streaming and more", apps: [
            { id: "com.moonlight_stream.Moonlight", name: "Moonlight", suggested: true,
              description: "Streams games from your gaming PC (Sunshine or NVIDIA GameStream) to this device." },
            { id: "io.github.streetpea.Chiaki4deck", name: "Chiaki4deck", description: "PlayStation 4 and 5 Remote Play." },
            { id: "org.prismlauncher.PrismLauncher", name: "Prism Launcher", description: "Minecraft: Java Edition, with mod packs and multiple instances." },
            { id: "dev.vencord.Vesktop", name: "Vesktop",
              description: "Discord, with voice chat and screen sharing (Discord's own app has no build for this device)." }
        ] }
    ]

    property var chosen: ({})    // app ID -> ticked; unset means "suggested"
    readonly property var statusWords: Backend.installStatus.split(" ")
    readonly property bool busy: statusWords[0] === "running"
    readonly property var pending: {
        const ids = [];
        for (const g of groups) {
            for (const a of g.apps) {
                if (isTicked(a) && !Backend.installedApps.includes(a.id)) {
                    ids.push(a.id);
                }
            }
        }
        return ids;
    }

    function isTicked(app) {
        return app.id in chosen ? chosen[app.id] : app.suggested === true;
    }

    function setTicked(id, ticked) {
        const c = Object.assign({}, chosen);
        c[id] = ticked;
        chosen = c;
    }

    function appName(id) {
        for (const g of groups) {
            const a = g.apps.find(a => a.id === id);
            if (a) {
                return a.name;
            }
        }
        return id;
    }

    Component.onCompleted: Backend.refreshApps()

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing

        QQC2.Button {
            id: installButton
            icon.name: "download"
            text: page.pending.length > 0 ? "Install (" + page.pending.length + ")" : "Install"
            enabled: !page.busy && page.pending.length > 0
            onClicked: Backend.installApps(page.pending)
        }

        QQC2.BusyIndicator {
            visible: page.busy
            running: visible
            Layout.preferredHeight: installButton.implicitHeight
            Layout.preferredWidth: Layout.preferredHeight
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: page.statusWords[0] === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            text: {
                const w = page.statusWords;
                switch (w[0]) {
                case "running":
                    return +w[1] === 0 ? "Getting ready…"
                        : "Installing " + page.appName(w[3]) + " (" + w[1] + " of " + w[2] + ")…";
                case "done":
                    return +w[1] === 1 ? "Installed. Find it in the application menu." : "All " + w[1] + " installed. Find them in the application menu.";
                case "error":
                    return (w[1] === "-" || w[1] === "flathub" ? "" : page.appName(w[1]) + " could not be installed: ") + w.slice(2).join(" ");
                default:
                    return "";
                }
            }
        }
    }

    Repeater {
        model: page.groups

        delegate: ColumnLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 0

            FormCard.FormHeader {
                title: modelData.title
                maximumWidth: page.width
            }

            FormCard.FormCard {
                maximumWidth: page.width

                Repeater {
                    model: modelData.apps

                    delegate: FormCard.FormCheckDelegate {
                        required property var modelData
                        readonly property bool isInstalled: Backend.installedApps.includes(modelData.id)

                        text: modelData.name + (isInstalled ? "  (installed)" : "")
                        description: modelData.description
                        enabled: !isInstalled && !page.busy
                        checked: isInstalled || page.isTicked(modelData)
                        onToggled: {
                            page.setTicked(modelData.id, checked);
                            checked = Qt.binding(() => isInstalled || page.isTicked(modelData));
                        }
                    }
                }
            }
        }
    }

    BattleNetSection {
        maximumWidth: page.width
    }

    ProtonSection {
        maximumWidth: page.width
    }
}
