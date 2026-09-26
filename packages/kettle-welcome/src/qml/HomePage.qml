// SPDX-License-Identifier: BSD-3-Clause
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

BasePage {
    id: page

    signal navigate(string name)

    title: "Welcome"

    // hero: the splash's kettle and a short introduction
    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.gridUnit

        Image {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 9
            Layout.preferredHeight: Layout.preferredWidth
            source: "file://" + Constants.kettleArt
            fillMode: Image.PreserveAspectFit
            visible: status === Image.Ready
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Heading {
                Layout.fillWidth: true
                text: "Welcome to Kettle"
                level: 1
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2
                wrapMode: Text.Wrap
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Game Mode is where you play your Steam library. This desktop is for everything else: games from other stores, emulators, the web, files and settings. This window is your starting point for all of it. It's in the application menu as <b>Kettle Welcome</b> whenever you need it again."
            }
        }
    }

    Section {
        title: "Get started"
        description: "A few things worth doing first."
    }

    TileGrid {
        Tile {
            iconName: "network-wireless"
            title: "Connect to Wi-Fi"
            subtitle: "Pick a network and sign in."
            onClicked: Backend.openSettings("kcm_networkmanagement")
        }
        Tile {
            iconName: "dialog-password"
            title: "Change your password"
            subtitle: "The account starts with the password \"" + Constants.defaultUser + "\". Change it, since it also protects remote logins (SSH) and administrator tasks."
            onClicked: Backend.openSettings("kcm_users")
        }
        Tile {
            iconName: "download"
            title: "Get gaming apps"
            subtitle: "Emulators, game streaming and tools that bring other games into Steam."
            onClicked: page.navigate("extras")
        }
        Tile {
            iconName: "drive-harddisk"
            title: "Install to internal storage"
            subtitle: "Run Kettle without the microSD card, next to Android."
            onClicked: Backend.launchApp("kettle-installer")
        }
    }

    Section {
        title: "Find your way around"
    }

    TileGrid {
        Tile {
            iconName: "input-gamepad"
            title: "Desktop controls"
            subtitle: "The controller works as a mouse and keyboard. See which button does what."
            onClicked: page.navigate("controls")
        }
        Tile {
            iconName: "applications-games"
            title: "Games outside Steam"
            subtitle: "Epic, GOG and Amazon libraries, and your own Windows games."
            onClicked: page.navigate("games")
        }
        Tile {
            iconName: "gaming-return"
            title: "Return to Game Mode"
            subtitle: "Back to Steam's handheld interface."
            onClicked: Backend.returnToGameMode()
        }
    }

    Section {
        title: "Start up in"
        description: "What Kettle opens when it turns on. Switching modes from Steam's power menu or with Return to Game Mode lasts until the next restart."
    }

    // steamos-manager's default login mode; disabled until it has been read
    ColumnLayout {
        enabled: Backend.bootMode.length > 0
        spacing: Kirigami.Units.smallSpacing

        QQC2.RadioButton {
            text: "Game Mode (Steam)"
            checked: Backend.bootMode === "game"
            onToggled: if (checked) Backend.bootMode = "game"
        }
        QQC2.RadioButton {
            text: "Desktop"
            checked: Backend.bootMode === "desktop"
            onToggled: if (checked) Backend.bootMode = "desktop"
        }
    }

    QQC2.Switch {
        Layout.topMargin: Kirigami.Units.gridUnit
        text: "Show this window every time the desktop starts"
        checked: Backend.showAtLogin
        onToggled: Backend.showAtLogin = checked
    }
}
