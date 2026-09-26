// SPDX-License-Identifier: BSD-3-Clause
// Shortcuts to the settings people look for first, each in its own System Settings window.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

BasePage {
    title: "Setup"
    heading: "Setup"
    description: "Each of these opens the matching page of System Settings in its own window."

    Section { title: "Account and network" }

    TileGrid {
        Tile {
            iconName: "dialog-password"
            title: "Password and account"
            subtitle: "Change your password, name and picture. The password starts as \"" + Constants.defaultUser + "\"."
            onClicked: Backend.openSettings("kcm_users")
        }
        Tile {
            iconName: "network-wireless"
            title: "Wi-Fi and internet"
            subtitle: "Networks, VPN and connection details."
            onClicked: Backend.openSettings("kcm_networkmanagement")
        }
    }

    Section {
        title: "Remote access"
        description: "An SSH server lets you log in to this device from another computer on your network, for copying files or using a terminal. Turn it on only when you need it, and change the password first: anyone on the network who knows it can log in. Changing this asks for your password."
    }

    Kirigami.AbstractCard {
        Layout.fillWidth: true

        contentItem: ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: implicitWidth
                    source: "network-server"
                    fallback: "network-wired"
                }
                QQC2.Switch {
                    Layout.fillWidth: true
                    text: "SSH server"
                    checked: Backend.sshEnabled
                    enabled: !Backend.sshBusy
                    onToggled: {
                        Backend.sshEnabled = checked;
                        checked = Qt.binding(() => Backend.sshEnabled);
                    }
                }
                QQC2.BusyIndicator {
                    visible: Backend.sshBusy
                    running: visible
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    Layout.preferredWidth: Layout.preferredHeight
                }
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                opacity: 0.8
                text: !Backend.sshEnabled ? "Off. Nothing on the network can log in to this device."
                    : Backend.addresses.length > 0
                        ? "On. From another computer: " + Backend.addresses.map(a => "<b>ssh " + Backend.userName + "@" + a + "</b>").join(" or ")
                        : "On. Connect to a network to log in from another computer."
            }
        }
    }

    Section { title: "Device" }

    TileGrid {
        Tile {
            iconName: "video-display"
            title: "Display"
            subtitle: "Scale, resolution, and external monitors."
            onClicked: Backend.openSettings("kcm_kscreen")
        }
        Tile {
            iconName: "audio-volume-high"
            title: "Sound"
            subtitle: "Speakers, headphones and microphones."
            onClicked: Backend.openSettings("kcm_pulseaudio")
        }
        Tile {
            iconName: "preferences-system-power-management"
            title: "Power"
            subtitle: "Screen dimming, sleep and what the power button does in the desktop."
            onClicked: Backend.openSettings("kcm_powerdevilprofilesconfig")
        }
        Tile {
            iconName: "input-gamepad"
            title: "Game controllers"
            subtitle: "Test connected controllers."
            onClicked: Backend.openSettings("kcm_gamecontroller")
        }
        Tile {
            iconName: "input-keyboard-virtual"
            title: "On-screen keyboard"
            subtitle: "Which on-screen keyboard the desktop uses."
            onClicked: Backend.openSettings("kcm_virtualkeyboard")
        }
    }

    Section { title: "Personal" }

    TileGrid {
        Tile {
            iconName: "preferences-desktop-locale"
            title: "Language and region"
            subtitle: "Language, number, date and currency formats."
            onClicked: Backend.openSettings("kcm_regionandlang")
        }
        Tile {
            iconName: "preferences-system-time"
            title: "Date and time"
            subtitle: "Time zone and clock."
            onClicked: Backend.openSettings("kcm_clock")
        }
        Tile {
            iconName: "preferences-desktop-theme-global"
            title: "Appearance"
            subtitle: "Light or dark theme, colors and wallpaper."
            onClicked: Backend.openSettings("kcm_lookandfeel")
        }
        Tile {
            iconName: "systemsettings"
            title: "All settings"
            subtitle: "Everything else, in System Settings."
            onClicked: Backend.openSystemSettings()
        }
    }
}
