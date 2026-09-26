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
